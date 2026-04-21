"""
Persistent settings store — reads/writes dashboard_settings.json.

All user-configurable values that were previously hardcoded in config.py live
here. Secrets (API keys, OAuth tokens) remain in .env only.

On first load, if dashboard_settings.json does not exist it is created from
the built-in defaults so the file is always present after the first import.
"""

import json
from pathlib import Path

# Resolve relative to project root regardless of CWD.
# settings_store.py lives at <root>/dashboard/backend/settings_store.py,
# so three .parent steps reach the project root.
SETTINGS_PATH = Path(__file__).parent.parent.parent / "dashboard_settings.json"

_DEFAULTS: dict = {
    "zip_code": "85286",
    "down_payment": 3000,
    "interest_rate": 7.5,
    "loan_term_months": 60,
    "check_interval_hours": 24,
    "schedule_enabled": False,
    "schedule_interval_hours": 24,
    "schedule_profile_ids": [],
    "max_pages_per_search": 5,
    "send_email": True,
    "headless": True,
    "request_delay_seconds": 4,
    "page_timeout_seconds": 30,
    "ollama_enabled": False,
    "ollama_timeout": 600,
    "ollama_ref_doc_max_chars": 6000,
    "ollama_preferred_models": [
        "qwen3.5:9b",
        "deepseek-r1:latest",
        "gemma4:e4b",
        "qwen3.5:4b",
        "gemma4:e2b",
    ],
    "anthropic_enabled": True,
    "anthropic_model": "claude-haiku-4-5-20251001",
    "anthropic_max_tokens": 1500,
    "output_dir": "./carvana_results",
    "vehicle_reference_dir": "./vehicle_reference",
    "db_path": "./carvana_results/history.db",
    "log_file": "./carvana_results/tracker.log",
}


def load() -> dict:
    """Return merged settings: defaults overlaid with any values from the JSON file.

    If the file does not exist it is created from defaults on this first call.
    Unknown keys in the file are preserved (forward-compatibility).
    """
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        return {**_DEFAULTS, **data}

    # First load — materialise the file so users can see (and edit) all options.
    _write_raw(dict(_DEFAULTS))
    return dict(_DEFAULTS)


def save(settings: dict) -> None:
    """Persist a partial or complete settings dict, merging with existing values."""
    merged = {**load(), **settings}
    _write_raw(merged)


def get(key: str):
    """Return a single setting value, or None if the key is not in defaults."""
    return load().get(key)


def _write_raw(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
