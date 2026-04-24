"""
User store and JWT utilities for the web portal.

Users are persisted in users.json at the project root.
The JWT signing secret is stored separately in auth_secret.key (also at the
project root) so it is never co-located with password hashes.  Both files are
gitignored.
"""

import json
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from jose import jwt

_USERS_FILE  = Path(__file__).parent.parent.parent / "users.json"
_SECRET_FILE = Path(__file__).parent.parent.parent / "auth_secret.key"
_ALGORITHM   = "HS256"
_TOKEN_HOURS = 8

logger = logging.getLogger(__name__)


# ── JWT signing key ───────────────────────────────────────────────────────────

def _secret_key() -> str:
    """Return the persistent JWT signing secret, creating it on first use."""
    if _SECRET_FILE.exists():
        key = _SECRET_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    # Generate and persist a new key.
    key = secrets.token_hex(32)
    _SECRET_FILE.write_text(key, encoding="utf-8")
    logger.info("auth_secret.key created")
    return key


# ── Internal user-store helpers ───────────────────────────────────────────────

def _load() -> dict:
    if not _USERS_FILE.exists():
        return {"users": []}
    try:
        data = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        # Migrate: remove legacy secret_key field if present.
        if "secret_key" in data:
            # Recover the key into auth_secret.key if we haven't generated one yet.
            if not _SECRET_FILE.exists():
                _SECRET_FILE.write_text(data["secret_key"], encoding="utf-8")
                logger.info("Migrated JWT secret from users.json to auth_secret.key")
            del data["secret_key"]
            _save(data)
        return data
    except Exception:
        logger.error("Failed to parse users.json — treating as empty")
        return {"users": []}


def _save(store: dict) -> None:
    _USERS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


# ── Public API ────────────────────────────────────────────────────────────────

def get_users() -> list[dict]:
    return _load().get("users", [])


def users_exist() -> bool:
    return bool(get_users())


def get_user(username: str) -> Optional[dict]:
    return next((u for u in get_users() if u["username"] == username), None)


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def create_access_token(sub: str, role: str, profile_id: Optional[str]) -> str:
    payload = {
        "sub": sub,
        "role": role,
        "profile_id": profile_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=_TOKEN_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _secret_key(), algorithm=_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _secret_key(), algorithms=[_ALGORITHM])


def create_user(username: str, password: str, role: str, profile_id: Optional[str] = None) -> dict:
    store = _load()
    user: dict = {
        "username": username,
        "hashed_password": hash_password(password),
        "role": role,
        "profile_id": profile_id,
        "pw_changed_at": int(time.time()),
    }
    store.setdefault("users", []).append(user)
    _save(store)
    return user


def delete_user(username: str) -> bool:
    store = _load()
    before = len(store.get("users", []))
    store["users"] = [u for u in store.get("users", []) if u["username"] != username]
    if len(store["users"]) < before:
        _save(store)
        return True
    return False


def update_password(username: str, new_password: str) -> bool:
    store = _load()
    for u in store.get("users", []):
        if u["username"] == username:
            u["hashed_password"] = hash_password(new_password)
            u["pw_changed_at"] = int(time.time())
            _save(store)
            return True
    return False


def update_profile_id(username: str, profile_id: Optional[str]) -> bool:
    store = _load()
    for u in store.get("users", []):
        if u["username"] == username:
            u["profile_id"] = profile_id
            _save(store)
            return True
    return False
