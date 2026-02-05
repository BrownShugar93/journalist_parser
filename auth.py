import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Tuple

from db import store_session


def generate_salt() -> str:
    return secrets.token_hex(16)


def hash_password(password: str, salt: str) -> str:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return dk.hex()


def verify_password(password: str, salt: str, password_hash: str) -> bool:
    calc = hash_password(password, salt)
    return hmac.compare_digest(calc, password_hash)


def create_session_token(user_id: int, ttl_days: int = 7) -> Tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    store_session(token, user_id, expires_at)
    return token, expires_at
