"""
NHTSA VIN decode — drivetrain enrichment.

Uses the free US government batch VIN decode API to populate the
'drivetrain' field (AWD/FWD/RWD/4WD) on listings.

No API key required. One POST per make/model group, up to 50 VINs per
request. All listings that pass filters are enriched, not just those
that appear in the email table.
"""

import logging
from collections import defaultdict

import requests

log = logging.getLogger(__name__)

_NHTSA_BATCH_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVINValuesBatch/"
_BATCH_SIZE = 50  # NHTSA hard limit per request


def normalize_drivetrain(raw: str) -> str | None:
    """
    Map any raw drivetrain string to one of: AWD, 4WD, FWD, RWD.
    Handles schema.org URLs (e.g. "AllWheelDriveConfiguration"),
    abbreviations, NHTSA strings (e.g. "AWD/All-Wheel Drive"), and
    plain-English phrases. Returns None if empty or unrecognized.
    """
    if not raw:
        return None
    v = raw.lower().replace("-", "").replace("_", "").replace(" ", "")
    if "allwheel" in v or "awd" in v:
        return "AWD"
    if "fourwheel" in v or "4wd" in v or "4x4" in v:
        return "4WD"
    if "frontwheel" in v or "fwd" in v or "front" in v:
        return "FWD"
    if "rearwheel" in v or "rwd" in v or "rear" in v:
        return "RWD"
    return None


def _fetch_drivetrain_batch(vins: list[str]) -> dict[str, str]:
    """
    POST up to 50 VINs to the NHTSA batch decode endpoint.
    Returns a dict of VIN (uppercase) → raw DriveType string.
    Returns {} on any error so callers can continue gracefully.
    """
    if not vins:
        return {}
    try:
        resp = requests.post(
            _NHTSA_BATCH_URL,
            data={"DATA": ";".join(vins), "format": "json"},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("Results", [])
    except Exception as exc:
        log.warning("NHTSA VIN decode request failed: %s", exc)
        return {}

    out: dict[str, str] = {}
    for item in results:
        vin   = (item.get("VIN") or "").strip().upper()
        drive = (item.get("DriveType") or "").strip()
        if vin and drive:
            out[vin] = drive
    return out


def enrich_drivetrain(listings: list[dict]) -> None:
    """
    Populate the 'drivetrain' field on every listing that doesn't already
    have one. Two-pass approach:

      1. Trim inference — parse AWD/FWD/RWD/4WD keywords from the listing's
         trim string. Carvana's own trim label takes priority over any external
         source, preventing mismatches like NHTSA calling a crossover AWD
         system "4WD" when the manufacturer markets it as AWD.

      2. NHTSA batch VIN decode — for any listing still unresolved after the
         trim pass, call the free NHTSA API (one POST per make/model group,
         chunked at 50 VINs per request).

    Mutates listings in-place.
    """
    # ── Pass 1: Trim-based inference ──────────────────────────────────────────
    trim_resolved = 0
    for listing in listings:
        if not listing.get("drivetrain"):
            inferred = normalize_drivetrain(listing.get("trim") or "")
            if inferred:
                listing["drivetrain"] = inferred
                trim_resolved += 1
    if trim_resolved:
        log.info("Drivetrain inferred from trim: %d listing(s)", trim_resolved)

    # ── Pass 2: NHTSA batch for any still unresolved ──────────────────────────
    by_model: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for listing in listings:
        if not listing.get("drivetrain"):
            key = (listing.get("make") or "", listing.get("model") or "")
            by_model[key].append(listing)

    if not by_model:
        log.debug("All listings have drivetrain after trim pass — skipping NHTSA")
        return

    total_resolved = 0
    total_needed   = sum(len(v) for v in by_model.values())

    for (make, model), model_listings in by_model.items():
        vins = [
            l.get("vin", "").strip().upper()
            for l in model_listings
            if l.get("vin")
        ]
        if not vins:
            continue

        # Build vin → listing map for fast lookup
        vin_to_listing: dict[str, dict] = {
            l.get("vin", "").strip().upper(): l
            for l in model_listings
            if l.get("vin")
        }

        # Fetch in chunks of up to 50
        drive_map: dict[str, str] = {}
        for i in range(0, len(vins), _BATCH_SIZE):
            chunk = vins[i : i + _BATCH_SIZE]
            drive_map.update(_fetch_drivetrain_batch(chunk))

        filled = 0
        for vin, raw_drive in drive_map.items():
            normalized = normalize_drivetrain(raw_drive)
            if normalized and vin in vin_to_listing:
                vin_to_listing[vin]["drivetrain"] = normalized
                filled += 1

        log.info(
            "NHTSA drivetrain — %s %s: %d/%d resolved",
            make, model, filled, len(vins),
        )
        total_resolved += filled

    log.info(
        "NHTSA drivetrain total: %d/%d listings resolved",
        total_resolved, total_needed,
    )
