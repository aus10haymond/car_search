"""
FastAPI dependencies for portal authentication.
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from dashboard.backend import auth_utils

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/portal/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    try:
        payload = auth_utils.decode_token(token)
    except JWTError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = auth_utils.get_user(payload.get("sub", ""))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    # Reject tokens issued before the user's last password change.
    pw_changed_at = user.get("pw_changed_at")
    token_iat = payload.get("iat")
    if pw_changed_at and token_iat and token_iat < pw_changed_at:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Session expired — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
