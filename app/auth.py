from __future__ import annotations

import os
from typing import Optional

from itsdangerous import BadSignature, URLSafeSerializer
from passlib.context import CryptContext


# PBKDF2 is widely supported and avoids bcrypt backend issues on some systems.
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _secret_key() -> str:
    return os.environ.get("SECRET_KEY", "dev-secret-key-change-me")


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(_secret_key(), salt="notes-sharing-session")


SESSION_COOKIE_NAME = "ns_session"


def sign_session(user_id: int) -> str:
    return _serializer().dumps({"user_id": user_id})


def read_session(cookie_value: Optional[str]) -> Optional[int]:
    if not cookie_value:
        return None
    try:
        data = _serializer().loads(cookie_value)
    except BadSignature:
        return None
    user_id = data.get("user_id")
    if isinstance(user_id, int):
        return user_id
    return None
