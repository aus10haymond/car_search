"""
Search profiles — each profile defines a set of vehicles, filters, and email recipients.
Profiles are loaded from profiles.yaml at startup.
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

import config

log = logging.getLogger(__name__)

_REQUIRED_FIELDS = {
    "profile_id", "label", "vehicles",
    "max_mileage", "min_year", "max_year", "email_to",
}


@dataclass
class SearchProfile:
    profile_id:         str
    label:              str
    vehicles:           list[tuple[str, str]]   # [(make, model), ...]
    max_price:          Optional[int]   # None = no upper price limit
    max_mileage:        int
    min_year:           int
    max_year:           int
    email_to:           list[str]
    fuel_type_filters:        list[str | None] = field(default_factory=lambda: [None])
    model_preference:         list[str] = field(default_factory=list)  # ordered best→worst; [] = no preference
    reference_doc_path:       Optional[str] = None
    excluded_trim_keywords:   list[str] = field(default_factory=list)  # case-insensitive substrings to drop
    show_financing:           bool = True          # include Est. Payment column in email table
    down_payment:             Optional[int] = None  # override config.DOWN_PAYMENT for this profile


def load_profiles(path: str) -> list[SearchProfile]:
    """Load and validate profiles from a YAML file. Raises on invalid config."""
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"profiles.yaml not found at {yaml_path.resolve()}. "
            "Create one using profiles.yaml as a template."
        )

    with open(yaml_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "profiles" not in data:
        raise ValueError("profiles.yaml must have a top-level 'profiles' key")

    raw_profiles = data["profiles"]
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise ValueError("profiles.yaml must contain at least one profile under 'profiles'")

    profiles: list[SearchProfile] = []
    seen_ids: set[str] = set()

    for i, raw in enumerate(raw_profiles):
        missing = _REQUIRED_FIELDS - set(raw.keys())
        if missing:
            raise ValueError(f"Profile #{i + 1} is missing required fields: {missing}")

        pid = raw["profile_id"]
        if not isinstance(pid, str) or not pid.strip():
            raise ValueError(f"Profile #{i + 1}: profile_id must be a non-empty string")
        if pid in seen_ids:
            raise ValueError(f"Duplicate profile_id: '{pid}'")
        seen_ids.add(pid)

        vehicles_raw = raw["vehicles"]
        if not isinstance(vehicles_raw, list) or not vehicles_raw:
            raise ValueError(f"Profile '{pid}': vehicles must be a non-empty list")
        vehicles: list[tuple[str, str]] = []
        for v in vehicles_raw:
            if not isinstance(v, (list, tuple)) or len(v) != 2:
                raise ValueError(
                    f"Profile '{pid}': each vehicle must be [make, model], got: {v}"
                )
            vehicles.append((str(v[0]), str(v[1])))

        email_to_raw = raw["email_to"]
        if isinstance(email_to_raw, str):
            email_to = [e.strip() for e in email_to_raw.split(",") if e.strip()]
        elif isinstance(email_to_raw, list):
            email_to = [str(e).strip() for e in email_to_raw if str(e).strip()]
        else:
            raise ValueError(f"Profile '{pid}': email_to must be a list or comma-separated string")
        if not email_to:
            raise ValueError(f"Profile '{pid}': email_to must contain at least one address")

        fuel_raw = raw.get("fuel_type_filters")
        if fuel_raw is None:
            fuel_type_filters: list[str | None] = [None]
        else:
            fuel_type_filters = [
                None if (f is None or str(f).lower() in ("null", "none", ""))
                else str(f)
                for f in fuel_raw
            ]

        model_pref_raw = raw.get("model_preference") or []
        model_preference = [str(m) for m in model_pref_raw]

        excluded_trim_raw = raw.get("excluded_trim_keywords") or []
        excluded_trim_keywords = [str(k).lower() for k in excluded_trim_raw]

        profiles.append(SearchProfile(
            profile_id=pid,
            label=str(raw["label"]),
            vehicles=vehicles,
            max_price=int(raw["max_price"]) if raw.get("max_price") is not None else None,
            max_mileage=int(raw["max_mileage"]),
            min_year=int(raw["min_year"]),
            max_year=int(raw["max_year"]),
            email_to=email_to,
            fuel_type_filters=fuel_type_filters,
            model_preference=model_preference,
            reference_doc_path=raw.get("reference_doc_path"),
            excluded_trim_keywords=excluded_trim_keywords,
            show_financing=bool(raw.get("show_financing", True)),
            down_payment=int(raw["down_payment"]) if raw.get("down_payment") is not None else None,
        ))

    log.info("Loaded %d profile(s): %s", len(profiles), [p.profile_id for p in profiles])
    return profiles


def _tokens(text: str) -> list[str]:
    """Lowercase words with 2+ characters from make/model strings."""
    return [t for t in re.sub(r"[^a-z0-9]", " ", text.lower()).split() if len(t) >= 2]


def _find_vehicle_doc(make: str, model: str, ref_dir: Path) -> Path | None:
    """
    Return the best-matching .md file in ref_dir for a given make/model,
    or None if no file scores at least 1 token match.

    Scoring: count how many normalized make+model tokens appear as substrings
    in the normalized filename. Highest score wins.
    """
    query = _tokens(f"{make} {model}")
    if not query or not ref_dir.is_dir():
        return None

    best_path, best_score = None, 0
    for f in ref_dir.glob("*.md"):
        fname_norm = re.sub(r"[^a-z0-9]", " ", f.stem.lower())
        score = sum(1 for t in query if t in fname_norm)
        if score > best_score:
            best_score, best_path = score, f

    return best_path if best_score > 0 else None


def _auto_discover_reference_docs(profile: "SearchProfile") -> str:
    """
    Look in VEHICLE_REFERENCE_DIR for a matching .md file for each vehicle
    in the profile. Returns the concatenated content of all matched docs
    (separated by headers), or "" if none are found.
    """
    ref_dir = Path(config.VEHICLE_REFERENCE_DIR)
    if not ref_dir.is_dir():
        return ""

    sections: list[str] = []
    for make, model in profile.vehicles:
        doc_path = _find_vehicle_doc(make, model, ref_dir)
        if doc_path:
            text = doc_path.read_text(encoding="utf-8").strip()
            if text:
                log.info(
                    "[%s] Auto-discovered reference doc for %s %s: %s (%d chars)",
                    profile.profile_id, make, model, doc_path.name, len(text),
                )
                sections.append(text)
        else:
            log.debug(
                "[%s] No reference doc found in %s for %s %s",
                profile.profile_id, ref_dir, make, model,
            )

    return "\n\n---\n\n".join(sections)


def resolve_reference_doc(profile: "SearchProfile") -> str:
    """
    Load and return the reference doc text for a profile.

    Fallback chain:
      1. profile.reference_doc_path — if set and file exists, use it
      2. Auto-discover per-vehicle docs from VEHICLE_REFERENCE_DIR
      3. config.REFERENCE_DOC_PATH  — global fallback, if file exists
      4. ""                         — no reference data; LLM prompt will note this
    """
    # Step 1: profile-specific path
    if profile.reference_doc_path:
        p = Path(profile.reference_doc_path)
        if p.exists():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                log.info("[%s] Loaded reference doc from %s (%d chars)",
                         profile.profile_id, p, len(text))
                return text
            log.warning("[%s] Reference doc at %s is empty — falling back to global",
                        profile.profile_id, p)
        else:
            log.warning("[%s] Reference doc not found at '%s' — falling back to auto-discovery",
                        profile.profile_id, p)

    # Step 2: auto-discover per-vehicle docs from vehicle_reference/
    discovered = _auto_discover_reference_docs(profile)
    if discovered:
        return discovered

    # Step 3: global fallback
    global_path = getattr(config, "REFERENCE_DOC_PATH", "")
    if global_path:
        gp = Path(global_path)
        if gp.exists():
            text = gp.read_text(encoding="utf-8").strip()
            if text:
                log.info("[%s] Using global reference doc from %s (%d chars)",
                         profile.profile_id, gp, len(text))
                return text
            log.warning("[%s] Global reference doc at %s is empty — no reference data",
                        profile.profile_id, gp)
        else:
            log.warning("[%s] Global reference doc not found at '%s' — no reference data",
                        profile.profile_id, gp)

    log.warning(
        "[%s] No reference doc available — LLM will evaluate on listing data alone",
        profile.profile_id,
    )
    return ""
