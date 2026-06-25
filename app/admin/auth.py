"""Authentication helpers for the admin panel."""

from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Optional

import bcrypt
from itsdangerous import BadSignature, BadTimeSignature, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlmodel import select

from app.config import (
    ADMIN_COOKIE_NAME,
    ADMIN_SESSION_MAX_AGE_SECONDS,
    ADMIN_SESSION_SECRET,
)
from app.db.models import AdminUser
from app.db.session import Session as SessionFactory, engine


PASSWORD_CONTEXT = CryptContext(schemes=["bcrypt_sha256", "bcrypt"], deprecated="auto")
SESSION_SALT = "voice-command-api-admin-session"


@dataclass
class AdminSessionData:
    """Decoded session payload."""

    user_id: int
    email: str
    csrf_token: str


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(ADMIN_SESSION_SECRET, salt=SESSION_SALT)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a password hash with safe fallbacks for local environments."""

    try:
        return PASSWORD_CONTEXT.verify(plain_password, password_hash)
    except Exception:
        try:
            return bcrypt.checkpw(
                plain_password.encode("utf-8"),
                password_hash.encode("utf-8"),
            )
        except Exception:
            return False


def authenticate_admin_user(email: str, password: str) -> Optional[AdminUser]:
    """Return the matching active admin user when credentials are valid."""

    if SessionFactory is None or engine is None:
        return None

    with SessionFactory(engine) as session:
        user = session.exec(select(AdminUser).where(AdminUser.email == email)).first()
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return user


def create_session_token(user: AdminUser) -> str:
    """Create a signed session token for the admin user."""

    serializer = _get_serializer()
    return serializer.dumps(
        {
            "user_id": user.id,
            "email": user.email,
            "csrf_token": secrets.token_urlsafe(24),
        }
    )


def decode_session_token(token: str) -> Optional[AdminSessionData]:
    """Decode and validate a signed session token."""

    serializer = _get_serializer()
    try:
        payload = serializer.loads(token, max_age=ADMIN_SESSION_MAX_AGE_SECONDS)
    except (BadSignature, BadTimeSignature):
        return None

    user_id = payload.get("user_id")
    email = payload.get("email")
    csrf_token = payload.get("csrf_token")
    if (
        not isinstance(user_id, int)
        or not isinstance(email, str)
        or not isinstance(csrf_token, str)
        or not csrf_token
    ):
        return None
    return AdminSessionData(user_id=user_id, email=email, csrf_token=csrf_token)


def get_csrf_token(session_token: Optional[str]) -> Optional[str]:
    """Return the CSRF token embedded in the signed session cookie."""

    if not session_token:
        return None
    session_data = decode_session_token(session_token)
    if session_data is None:
        return None
    return session_data.csrf_token


def get_current_admin_user(session_token: Optional[str]) -> Optional[AdminUser]:
    """Resolve the current admin user from the signed session cookie."""

    if not session_token or SessionFactory is None or engine is None:
        return None

    session_data = decode_session_token(session_token)
    if session_data is None:
        return None

    with SessionFactory(engine) as session:
        user = session.get(AdminUser, session_data.user_id)
        if user is None or not user.is_active or user.email != session_data.email:
            return None
        return user


__all__ = [
    "ADMIN_COOKIE_NAME",
    "authenticate_admin_user",
    "create_session_token",
    "decode_session_token",
    "get_csrf_token",
    "get_current_admin_user",
]
