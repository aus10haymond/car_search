"""
User store and JWT utilities for the web portal.

Users are persisted in users.json at the project root alongside a randomly-generated
secret key that is created on first access and never changes unless the file is deleted.
"""

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from jose import jwt

_USERS_FILE = Path(__file__).parent.parent.parent / "users.json"
_ALGORITHM = "HS256"
_TOKEN_HOURS = 8


# ── Internal store helpers ────────────────────────────────────────────────────

def _load() -> dict:
    if not _USERS_FILE.exists():
        return {"secret_key": secrets.token_hex(32), "users": []}
    try:
        return json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"secret_key": secrets.token_hex(32), "users": []}


def _save(store: dict) -> None:
    _USERS_FILE.write_text(json.dumps(store, indent=2), encoding="utf-8")


def _secret_key() -> str:
    store = _load()
    if "secret_key" not in store:
        store["secret_key"] = secrets.token_hex(32)
        _save(store)
        return store["secret_key"]
    return store["secret_key"]


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
