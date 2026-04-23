"""
Profiles router — CRUD operations against profiles.yaml.

Validation uses the same rules as profiles.load_profiles() so the dashboard
cannot write a YAML that the tracker would reject on startup.
"""

import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from profiles import load_profiles

router = APIRouter(prefix="/profiles", tags=["profiles"])

_PROFILES_YAML = Path(__file__).parent.parent.parent.parent / "profiles.yaml"
_PROFILE_ID_RE = re.compile(r"^[a-z0-9_]+$")


# ── Pydantic model ────────────────────────────────────────────────────────────

class ProfileModel(BaseModel):
    profile_id:             str
    label:                  str
    vehicles:               list[list[str]]          # [[make, model], ...]
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
    def validate_profile(self) -> "ProfileModel":
        if not _PROFILE_ID_RE.match(self.profile_id):
            raise ValueError("profile_id must match [a-z0-9_]+")
        if not self.label.strip():
            raise ValueError("label must not be empty")
        if not self.vehicles:
            raise ValueError("vehicles must contain at least one entry")
        for v in self.vehicles:
            if len(v) != 2 or not all(isinstance(x, str) and x.strip() for x in v):
                raise ValueError("each vehicle must be [make, model] with non-empty strings")
        if not self.email_to:
            raise ValueError("email_to must contain at least one address")
        if self.min_year > self.max_year:
            raise ValueError("min_year must be <= max_year")
        return self


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_raw() -> list[dict]:
    """Return profiles as raw dicts from YAML (preserves field order)."""
    if not _PROFILES_YAML.exists():
        return []
    with open(_PROFILES_YAML, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data.get("profiles", [])


def _write_raw(raw_profiles: list[dict]) -> None:
    content = yaml.dump(
        {"profiles": raw_profiles},
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    _PROFILES_YAML.write_text(content, encoding="utf-8")


def _model_to_raw(p: ProfileModel) -> dict[str, Any]:
    """Convert a validated ProfileModel to the dict shape load_profiles() expects."""
    d: dict[str, Any] = {
        "profile_id":             p.profile_id,
        "label":                  p.label,
        "vehicles":               p.vehicles,
        "max_price":              p.max_price,
        "max_mileage":            p.max_mileage,
        "min_year":               p.min_year,
        "max_year":               p.max_year,
        "email_to":               p.email_to,
        "fuel_type_filters":      p.fuel_type_filters,
        "model_preference":       p.model_preference,
        "excluded_trim_keywords": p.excluded_trim_keywords,
        "excluded_years":         p.excluded_years,
        "show_financing":         p.show_financing,
        "down_payment":           p.down_payment,
        "email_only_on_new_or_drops": p.email_only_on_new_or_drops,
    }
    if p.reference_doc_path:
        d["reference_doc_path"] = p.reference_doc_path
    return d


def _profile_to_model(raw: dict) -> dict:
    """Convert a raw YAML profile dict to the API response shape."""
    # Normalise fuel_type_filters: the YAML may store null or None
    fuel = raw.get("fuel_type_filters")
    if fuel is None:
        fuel = [None]
    else:
        fuel = [None if f is None or str(f).lower() in ("null", "none", "") else f for f in fuel]

    return {
        "profile_id":             raw.get("profile_id", ""),
        "label":                  raw.get("label", ""),
        "vehicles":               raw.get("vehicles", []),
        "max_price":              raw.get("max_price"),
        "max_mileage":            raw.get("max_mileage", 0),
        "min_year":               raw.get("min_year", 0),
        "max_year":               raw.get("max_year", 0),
        "email_to":               raw.get("email_to", []),
        "fuel_type_filters":      fuel,
        "model_preference":       raw.get("model_preference") or [],
        "reference_doc_path":     raw.get("reference_doc_path"),
        "excluded_trim_keywords": raw.get("excluded_trim_keywords") or [],
        "excluded_years":         raw.get("excluded_years") or [],
        "show_financing":         raw.get("show_financing", True),
        "down_payment":           raw.get("down_payment"),
        "email_only_on_new_or_drops": raw.get("email_only_on_new_or_drops", False),
    }


def _assert_profiles_yaml_exists() -> None:
    if not _PROFILES_YAML.exists():
        raise HTTPException(404, "profiles.yaml not found")


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_profiles():
    """Return all profiles from profiles.yaml."""
    _assert_profiles_yaml_exists()
    return [_profile_to_model(r) for r in _load_raw()]


@router.post("", status_code=201)
def create_profile(profile: ProfileModel):
    """Append a new profile to profiles.yaml."""
    _assert_profiles_yaml_exists()
    raw_list = _load_raw()

    existing_ids = {r.get("profile_id") for r in raw_list}
    if profile.profile_id in existing_ids:
        raise HTTPException(409, f"profile_id '{profile.profile_id}' already exists")

    raw_list.append(_model_to_raw(profile))
    _write_raw(raw_list)

    # Verify the resulting YAML is still loadable
    _round_trip_check()
    return _profile_to_model(_model_to_raw(profile))


@router.put("/{profile_id}")
def update_profile(profile_id: str, profile: ProfileModel):
    """Replace an existing profile by ID."""
    _assert_profiles_yaml_exists()
    raw_list = _load_raw()

    idx = next(
        (i for i, r in enumerate(raw_list) if r.get("profile_id") == profile_id),
        None,
    )
    if idx is None:
        raise HTTPException(404, f"Profile '{profile_id}' not found")

    # Prevent changing profile_id via PUT body (body profile_id must match URL)
    if profile.profile_id != profile_id:
        raise HTTPException(
            422, "profile_id in body must match the URL parameter"
        )

    raw_list[idx] = _model_to_raw(profile)
    _write_raw(raw_list)
    _round_trip_check()
    return _profile_to_model(_model_to_raw(profile))


@router.delete("/{profile_id}", status_code=204)
def delete_profile(profile_id: str):
    """Remove a profile by ID."""
    _assert_profiles_yaml_exists()
    raw_list = _load_raw()

    new_list = [r for r in raw_list if r.get("profile_id") != profile_id]
    if len(new_list) == len(raw_list):
        raise HTTPException(404, f"Profile '{profile_id}' not found")

    _write_raw(new_list)


def _round_trip_check() -> None:
    """Verify the written YAML can be re-loaded by load_profiles()."""
    try:
        load_profiles(str(_PROFILES_YAML))
    except Exception as exc:
        raise HTTPException(500, f"Profile saved but failed validation round-trip: {exc}")
