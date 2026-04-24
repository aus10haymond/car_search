"""
Auth endpoints for the web portal.

Public:
  GET  /portal/auth/setup-required  — first-run check
  POST /portal/auth/setup           — create initial admin (only when no users exist)
  POST /portal/auth/login           — returns JWT bearer token

Protected:
  GET  /portal/auth/me              — current user info
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from dashboard.backend import auth_utils
from dashboard.backend.auth_deps import get_current_user

router = APIRouter(prefix="/portal/auth", tags=["portal-auth"])


class SetupRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


@router.get("/setup-required")
def setup_required():
    return {"required": not auth_utils.users_exist()}


@router.post("/setup", status_code=201)
def setup(body: SetupRequest):
    if auth_utils.users_exist():
        raise HTTPException(400, "Admin already exists — use /portal/auth/login instead")
    if not body.username.strip():
        raise HTTPException(422, "Username is required")
    if len(body.password) < 8:
        raise HTTPException(422, "Password must be at least 8 characters")
    auth_utils.create_user(body.username.strip(), body.password, role="admin")
    return {"message": "Admin account created"}


@router.post("/login")
def login(body: LoginRequest):
    user = auth_utils.get_user(body.username)
    if not user or not auth_utils.verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token = auth_utils.create_access_token(
        sub=user["username"],
        role=user["role"],
        profile_id=user.get("profile_id"),
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "username": user["username"],
        "role": user["role"],
        "profile_id": user.get("profile_id"),
    }


@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    return {
        "username": user["username"],
        "role": user["role"],
        "profile_id": user.get("profile_id"),
    }
