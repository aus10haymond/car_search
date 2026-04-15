"""
Search profiles — each profile defines a set of vehicles, filters, and email recipients.
Profiles are loaded from profiles.yaml at startup.
"""

import logging
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


def resolve_reference_doc(profile: SearchProfile) -> str:
    """
    Load and return the reference doc text for a profile.

    Fallback chain:
      1. profile.reference_doc_path — if set and file exists, use it
      2. config.REFERENCE_DOC_PATH  — global fallback, if file exists
      3. ""                         — no reference data; LLM prompt will note this
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
            log.warning("[%s] Reference doc not found at '%s' — falling back to global",
                        profile.profile_id, p)

    # Step 2: global fallback
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
