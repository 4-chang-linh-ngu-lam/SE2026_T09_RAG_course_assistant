import secrets
from collections.abc import Callable
from typing import Annotated, Protocol
from uuid import UUID

import jwt
from fastapi import Depends, Header
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict

from app.common.config import settings
from app.common.errors import AppError
from app.common.security import SYSTEM_ROLES, decode_access_token

bearer = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    status: str
    session_version: int
    roles: list[str]
    school_id: UUID | None = None


def require_school_scope(actor_school_id: UUID | None, resource_school_id: UUID | None) -> None:
    if (
        actor_school_id is None
        or resource_school_id is None
        or actor_school_id != resource_school_id
    ):
        raise AppError(404)


class UserLookup(Protocol):
    def __call__(self, user_id: UUID) -> CurrentUser | None: ...


def get_user_lookup() -> UserLookup:
    """Identity must supply a DB-backed lookup through its public interface."""

    def unavailable(user_id: UUID) -> CurrentUser | None:
        raise AppError(503, "Identity lookup unavailable")

    return unavailable


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    lookup: Annotated[UserLookup, Depends(get_user_lookup)],
) -> CurrentUser:
    if credentials is None:
        raise AppError(401)
    try:
        claims = decode_access_token(credentials.credentials)
    except jwt.InvalidTokenError as exc:
        raise AppError(401) from exc
    except RuntimeError as exc:
        raise AppError(503, "Authentication unavailable") from exc
    user = lookup(claims.sub)
    if (
        user is None
        or user.id != claims.sub
        or user.status != "ACTIVE"
        or user.session_version != claims.session_version
    ):
        raise AppError(401)
    return user


def require_roles(*roles: str) -> Callable:
    if not roles or not set(roles) <= SYSTEM_ROLES:
        raise ValueError("Expected system roles")

    def check_roles(user: Annotated[CurrentUser, Depends(get_current_user)]) -> CurrentUser:
        # Current DB roles are authoritative; roles embedded in JWT may be stale.
        if not set(roles).intersection(user.roles):
            raise AppError(403)
        return user

    return check_roles


def verify_internal_service_key(
    service_key: Annotated[str | None, Header(alias="X-Service-Key")] = None,
) -> frozenset[str]:
    expected = settings.internal_service_secret
    if expected is None:
        raise AppError(503, "Internal authentication unavailable")
    if service_key is None or not secrets.compare_digest(
        service_key.encode("utf-8"), expected.get_secret_value().encode("utf-8")
    ):
        raise AppError(401)
    return frozenset({"core:check_access"})
