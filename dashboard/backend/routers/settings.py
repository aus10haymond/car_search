"""
Settings router — read/write dashboard_settings.json via settings_store.

Secrets (keys whose name contains "key", "token", or "secret") are never
returned in GET responses.  They can be submitted via PATCH but are currently
written to .env by a separate flow (not yet implemented); for now they are
accepted and silently skipped with a warning in the response.
"""

from fastapi import APIRouter, HTTPException
from dashboard.backend import settings_store

router = APIRouter(prefix="/settings", tags=["settings"])

# Known keys that live in .env, not settings.json.
# Accepted in PATCH but not stored in the JSON file.
_ENV_KEYS = {
    "nvidia_api_key",
    "anthropic_api_key",
    "cerebras_api_key",
    "ollama_network_host",
    "ollama_network_host_2",
    "gmail_sender",
    "gmail_client_id",
    "gmail_client_secret",
    "gmail_refresh_token",
    "email_from_name",
}

_SECRET_SUBSTRINGS = ("key", "token", "secret")

_ALLOWED_KEYS = set(settings_store._DEFAULTS.keys())


def _mask_secrets(data: dict) -> dict:
    """Return a copy of data with secret-like values replaced by '***'."""
    return {
        k: "***" if any(s in k.lower() for s in _SECRET_SUBSTRINGS) else v
        for k, v in data.items()
    }


@router.get("")
def get_settings():
    """Return all settings from dashboard_settings.json (secrets masked)."""
    return _mask_secrets(settings_store.load())


@router.patch("")
def patch_settings(body: dict):
    """
    Partial update — merge provided keys into dashboard_settings.json.

    Unknown keys (not in the defaults schema) are rejected with 422.
    .env-only keys are accepted but skipped (returns list of skipped keys).
    """
    unknown = set(body.keys()) - _ALLOWED_KEYS - _ENV_KEYS
    if unknown:
        raise HTTPException(
            422,
            {"detail": f"Unknown settings key(s): {sorted(unknown)}"},
        )

    to_save = {k: v for k, v in body.items() if k in _ALLOWED_KEYS}
    skipped = [k for k in body if k in _ENV_KEYS]

    if to_save:
        settings_store.save(to_save)

    response: dict = {"saved": list(to_save.keys())}
    if skipped:
        response["skipped"] = skipped
        response["note"] = (
            "Skipped keys belong to .env — edit that file directly or use "
            "the OAuth setup flow for Gmail credentials."
        )
    return response
