"""
Portal API — auth-gated routes for the web portal.

Admin users have full access to all profiles, docs, settings, and users.
Regular users can only view/edit their own assigned profile and manage docs.

All routes share the /portal prefix to keep them separate from the desktop
dashboard routes (which remain unprotected for Tauri/localhost access).
"""

import logging
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

import config
from profiles import load_profiles, _find_vehicle_doc
from dashboard.backend import auth_utils, settings_store
from dashboard.backend.auth_deps import get_current_user, require_admin
from dashboard.backend.app import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portal", tags=["portal"])

_PROFILES_YAML = Path(__file__).parent.parent.parent.parent / "profiles.yaml"
_PROFILE_ID_RE = re.compile(r"^[a-z0-9_]+$")
_SAFE_FILENAME_RE = re.compile(r"^[\w\-]+\.md$")


# ══════════════════════════════════════════════════════════════════════════════
# Profiles
# ══════════════════════════════════════════════════════════════════════════════

class ProfileModel(BaseModel):
    profile_id:             str
    label:                  str
    vehicles:               list[list[str]]
    max_price:              int | None = None
    max_mileage:            int
    min_year:               int
    max_year:               int
    email_to:               list[str]
    fuel_type_filters:      list[str | None] = Field(default_factory=lambda: [None])
    model_preference:       list[str] = Field(default_factory=list)
    reference_doc_path:     str | None = None
    excluded_trim_keywords: list[str] = Field(default_factory=list)
    excluded_years:         list[int] = Field(default_factory=list)
    show_financing:         bool = True
    down_payment:           int | None = None
    email_only_on_new_or_drops: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "ProfileModel":
        if not _PROFILE_ID_RE.match(self.profile_id):
            raise ValueError("profile_id must match [a-z0-9_]+")
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if not self.vehicles:
            raise ValueError("vehicles must have at least one entry")
        for v in self.vehicles:
            if len(v) != 2 or not all(isinstance(x, str) and x.strip() for x in v):
                raise ValueError("each vehicle must be [make, model] with non-empty strings")
        if not self.email_to:
            raise ValueError("email_to must have at least one address")
        if self.min_year > self.max_year:
            raise ValueError("min_year must be <= max_year")
        return self


def _load_raw() -> list[dict]:
    if not _PROFILES_YAML.exists():
        return []
    with open(_PROFILES_YAML, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("profiles", [])


def _write_raw(raw: list[dict]) -> None:
    _PROFILES_YAML.write_text(
        yaml.dump({"profiles": raw}, allow_unicode=True, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )


def _to_api(r: dict) -> dict:
    fuel = r.get("fuel_type_filters")
    if fuel is None:
        fuel = [None]
    else:
        fuel = [None if f is None or str(f).lower() in ("null", "none", "") else f for f in fuel]
    return {
        "profile_id":             r.get("profile_id", ""),
        "label":                  r.get("label", ""),
        "vehicles":               r.get("vehicles", []),
        "max_price":              r.get("max_price"),
        "max_mileage":            r.get("max_mileage", 0),
        "min_year":               r.get("min_year", 0),
        "max_year":               r.get("max_year", 0),
        "email_to":               r.get("email_to", []),
        "fuel_type_filters":      fuel,
        "model_preference":       r.get("model_preference") or [],
        "reference_doc_path":     r.get("reference_doc_path"),
        "excluded_trim_keywords": r.get("excluded_trim_keywords") or [],
        "excluded_years":         r.get("excluded_years") or [],
        "show_financing":         r.get("show_financing", True),
        "down_payment":           r.get("down_payment"),
        "email_only_on_new_or_drops": r.get("email_only_on_new_or_drops", False),
    }


def _from_model(p: ProfileModel) -> dict:
    d: dict = {
        "profile_id": p.profile_id, "label": p.label, "vehicles": p.vehicles,
        "max_price": p.max_price, "max_mileage": p.max_mileage,
        "min_year": p.min_year, "max_year": p.max_year,
        "email_to": p.email_to, "fuel_type_filters": p.fuel_type_filters,
        "model_preference": p.model_preference,
        "excluded_trim_keywords": p.excluded_trim_keywords,
        "excluded_years": p.excluded_years,
        "show_financing": p.show_financing,
        "down_payment": p.down_payment,
        "email_only_on_new_or_drops": p.email_only_on_new_or_drops,
    }
    if p.reference_doc_path:
        d["reference_doc_path"] = p.reference_doc_path
    return d


def _round_trip() -> None:
    try:
        load_profiles(str(_PROFILES_YAML))
    except Exception as exc:
        raise HTTPException(500, f"Saved but failed round-trip validation: {exc}")


@router.get("/profiles")
def list_profiles(user: dict = Depends(get_current_user)):
    raw = _load_raw()
    if user["role"] == "admin":
        return [_to_api(r) for r in raw]
    pid = user.get("profile_id")
    return [_to_api(r) for r in raw if r.get("profile_id") == pid] if pid else []


@router.post("/profiles", status_code=201)
def create_profile(profile: ProfileModel, _: dict = Depends(require_admin)):
    if not _PROFILES_YAML.exists():
        raise HTTPException(404, "profiles.yaml not found")
    raw = _load_raw()
    if any(r.get("profile_id") == profile.profile_id for r in raw):
        raise HTTPException(409, f"profile_id '{profile.profile_id}' already exists")
    new = _from_model(profile)
    raw.append(new)
    _write_raw(raw)
    _round_trip()
    return _to_api(new)


@router.put("/profiles/{profile_id}")
def update_profile(profile_id: str, profile: ProfileModel, user: dict = Depends(get_current_user)):
    if user["role"] != "admin" and user.get("profile_id") != profile_id:
        raise HTTPException(403, "Cannot edit another user's profile")
    raw = _load_raw()
    idx = next((i for i, r in enumerate(raw) if r.get("profile_id") == profile_id), None)
    if idx is None:
        raise HTTPException(404, f"Profile '{profile_id}' not found")
    if profile.profile_id != profile_id:
        raise HTTPException(422, "profile_id in body must match URL parameter")
    raw[idx] = _from_model(profile)
    _write_raw(raw)
    _round_trip()
    return _to_api(raw[idx])


@router.delete("/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, _: dict = Depends(require_admin)):
    raw = _load_raw()
    new = [r for r in raw if r.get("profile_id") != profile_id]
    if len(new) == len(raw):
        raise HTTPException(404, f"Profile '{profile_id}' not found")
    _write_raw(new)


# ══════════════════════════════════════════════════════════════════════════════
# Docs
# ══════════════════════════════════════════════════════════════════════════════

def _docs_dir() -> Path:
    return Path(config.VEHICLE_REFERENCE_DIR)


def _check_filename(filename: str) -> None:
    if not _SAFE_FILENAME_RE.match(filename):
        raise HTTPException(422, "Filename must match [a-zA-Z0-9_-]+\\.md")


def _matched_profiles(filename: str) -> list[str]:
    docs_dir = _docs_dir()
    if not docs_dir.is_dir():
        return []
    try:
        profiles = load_profiles(str(_PROFILES_YAML))
    except Exception:
        return []
    matched: list[str] = []
    for p in profiles:
        for make, model in p.vehicles:
            best = _find_vehicle_doc(make, model, docs_dir)
            if best and best.name == filename:
                matched.append(p.profile_id)
                break
    return matched


class DocContent(BaseModel):
    content: str


class GenerateRequest(BaseModel):
    make: str
    model: str
    year_start: int
    year_end: int
    notes: str = ""


# Register /docs/generate BEFORE /docs/{filename} so the literal path wins.
@router.post("/docs/generate")
@limiter.limit("20/hour")
async def generate_doc(request: Request, body: GenerateRequest, _: dict = Depends(get_current_user)):
    """Use Cerebras to generate a vehicle reference markdown document."""
    from dashboard.backend.doc_generator import generate_vehicle_doc
    try:
        content = generate_vehicle_doc(body.make.strip(), body.model.strip(), body.year_start, body.year_end, body.notes)
        return {"content": content}
    except ValueError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"Generation failed: {exc}")


@router.get("/docs")
def list_docs(_: dict = Depends(get_current_user)):
    docs_dir = _docs_dir()
    if not docs_dir.is_dir():
        return []
    return [
        {"filename": p.name, "size_bytes": p.stat().st_size, "matched_profiles": _matched_profiles(p.name)}
        for p in sorted(docs_dir.glob("*.md"))
    ]


@router.get("/docs/{filename}")
def get_doc(filename: str, _: dict = Depends(get_current_user)):
    _check_filename(filename)
    path = _docs_dir() / filename
    if not path.exists():
        raise HTTPException(404, f"Doc '{filename}' not found")
    return {"filename": filename, "content": path.read_text(encoding="utf-8")}


@router.put("/docs/{filename}")
def put_doc(filename: str, body: DocContent, _: dict = Depends(get_current_user)):
    _check_filename(filename)
    docs_dir = _docs_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / filename
    path.write_text(body.content, encoding="utf-8")
    return {
        "filename": filename,
        "size_bytes": path.stat().st_size,
        "matched_profiles": _matched_profiles(filename),
    }


@router.delete("/docs/{filename}", status_code=204)
def delete_doc(filename: str, _: dict = Depends(require_admin)):
    _check_filename(filename)
    path = _docs_dir() / filename
    if not path.exists():
        raise HTTPException(404, f"Doc '{filename}' not found")
    path.unlink()


# ══════════════════════════════════════════════════════════════════════════════
# Settings  (admin only)
# ══════════════════════════════════════════════════════════════════════════════

_ENV_KEYS = {
    "anthropic_api_key", "ollama_network_host", "ollama_network_host_2",
    "gmail_sender", "gmail_client_id", "gmail_client_secret",
    "gmail_refresh_token", "email_from_name",
}
_ALLOWED_KEYS = set(settings_store._DEFAULTS.keys())
_SECRET_SUBSTRINGS = ("key", "token", "secret")


@router.get("/settings")
def get_settings(_: dict = Depends(require_admin)):
    return {
        k: "***" if any(s in k.lower() for s in _SECRET_SUBSTRINGS) else v
        for k, v in settings_store.load().items()
    }


@router.patch("/settings")
def patch_settings(body: dict, _: dict = Depends(require_admin)):
    unknown = set(body.keys()) - _ALLOWED_KEYS - _ENV_KEYS
    if unknown:
        raise HTTPException(422, f"Unknown setting key(s): {sorted(unknown)}")
    to_save = {k: v for k, v in body.items() if k in _ALLOWED_KEYS}
    skipped = [k for k in body if k in _ENV_KEYS]
    if to_save:
        settings_store.save(to_save)
    resp: dict[str, Any] = {"saved": list(to_save.keys())}
    if skipped:
        resp["skipped"] = skipped
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# Users  (admin only, except own password change)
# ══════════════════════════════════════════════════════════════════════════════

class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    profile_id: Optional[str] = None


class UpdatePasswordRequest(BaseModel):
    password: str


class AssignProfileRequest(BaseModel):
    profile_id: Optional[str] = None


def _pub(u: dict) -> dict:
    return {"username": u["username"], "role": u["role"], "profile_id": u.get("profile_id")}


@router.get("/users")
def list_users(_: dict = Depends(require_admin)):
    return [_pub(u) for u in auth_utils.get_users()]


@router.post("/users", status_code=201)
def create_user(body: CreateUserRequest, admin: dict = Depends(require_admin)):
    if auth_utils.get_user(body.username):
        raise HTTPException(409, f"User '{body.username}' already exists")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    if body.role not in ("admin", "user"):
        raise HTTPException(422, "role must be 'admin' or 'user'")
    result = auth_utils.create_user(body.username.strip(), body.password, body.role, body.profile_id)
    logger.info("User %r created (role=%s) by admin %r", body.username, body.role, admin["username"])
    return _pub(result)


@router.delete("/users/{username}", status_code=204)
def delete_user(username: str, current: dict = Depends(require_admin)):
    if username == current["username"]:
        raise HTTPException(400, "Cannot delete your own account")
    if not auth_utils.delete_user(username):
        raise HTTPException(404, f"User '{username}' not found")
    logger.info("User %r deleted by admin %r", username, current["username"])


@router.put("/users/{username}/password")
def change_password(username: str, body: UpdatePasswordRequest, current: dict = Depends(get_current_user)):
    if current["role"] != "admin" and current["username"] != username:
        raise HTTPException(403, "Cannot change another user's password")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    if not auth_utils.update_password(username, body.password):
        raise HTTPException(404, f"User '{username}' not found")
    logger.info("Password changed for %r by %r", username, current["username"])
    return {"message": "Password updated"}


@router.put("/users/{username}/profile")
def assign_profile(username: str, body: AssignProfileRequest, _: dict = Depends(require_admin)):
    if not auth_utils.update_profile_id(username, body.profile_id):
        raise HTTPException(404, f"User '{username}' not found")
    return {"message": "Profile assigned"}
