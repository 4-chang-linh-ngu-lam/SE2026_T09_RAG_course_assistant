import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.common.config import settings

password_hasher = PasswordHasher(type=Type.ID)
SYSTEM_ROLES = frozenset({"STUDENT", "LECTURER", "ADMIN"})


class AccessClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: UUID
    roles: list[str]
    session_version: int = Field(ge=0, strict=True)
    exp: int = Field(strict=True)
    iat: int = Field(strict=True)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def _signing_key() -> str:
    if settings.secret_key is None:
        raise RuntimeError("SECRET_KEY must be configured for authentication")
    return settings.secret_key.get_secret_value()


def create_access_token(user_id: UUID, roles: list[str], session_version: int) -> str:
    if not set(roles) <= SYSTEM_ROLES:
        raise ValueError("Unknown system role")
    now = datetime.now(UTC)
    claims = AccessClaims(
        sub=user_id,
        roles=roles,
        session_version=session_version,
        iat=int(now.timestamp()),
        exp=int((now + timedelta(minutes=settings.access_token_expire_minutes)).timestamp()),
    )
    return jwt.encode(claims.model_dump(mode="json"), _signing_key(), algorithm=settings.algorithm)


def decode_access_token(token: str) -> AccessClaims:
    payload = jwt.decode(
        token,
        _signing_key(),
        algorithms=[settings.algorithm],
        options={"require": ["sub", "roles", "session_version", "exp", "iat"]},
    )
    try:
        claims = AccessClaims.model_validate(payload)
    except ValidationError as exc:
        raise jwt.InvalidTokenError("Invalid access claims") from exc
    if not set(claims.roles) <= SYSTEM_ROLES or claims.exp <= claims.iat:
        raise jwt.InvalidTokenError("Invalid access claims")
    return claims


def generate_refresh_token() -> str:
    return secrets.token_hex(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
