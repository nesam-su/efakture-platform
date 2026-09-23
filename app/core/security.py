import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from cryptography.fernet import Fernet, InvalidToken
from pwdlib import PasswordHash

from app.core.config import get_settings

password_hash = PasswordHash.recommended()
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password-used-only-for-timing-equalization")
ALGORITHM = "HS256"


@dataclass(frozen=True)
class TokenClaims:
    user_id: UUID
    session_id: UUID


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    return password_hash.verify(password, encoded)


def verify_password_safe(password: str, encoded: str | None) -> bool:
    valid = password_hash.verify(password, encoded or DUMMY_PASSWORD_HASH)
    return encoded is not None and valid


def create_access_token(user_id: UUID, session_id: UUID) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenClaims:
    payload = jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Pogrešan tip tokena")
    return TokenClaims(user_id=UUID(payload["sub"]), session_id=UUID(payload["sid"]))


def login_throttle_key(email: str, ip_address: str | None) -> str:
    normalized = f"{email.strip().lower()}|{ip_address or 'unknown'}"
    return hashlib.sha256(normalized.encode()).hexdigest()


def encrypt_secret(value: str) -> str:
    cipher = Fernet(get_settings().credential_encryption_key.encode())
    return cipher.encrypt(value.encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        cipher = Fernet(get_settings().credential_encryption_key.encode())
        return cipher.decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Integracioni podatak nije moguće dešifrovati") from exc


def create_invitation_secret() -> tuple[str, str]:
    """Return a one-time invitation secret and the SHA-256 value stored in the database."""
    secret = secrets.token_urlsafe(32)
    return secret, hash_invitation_secret(secret)


def hash_invitation_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
