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
from app.common.service_jwt import (
    InsufficientServiceScope,
    InvalidServiceJwt,
    ServiceJwtConfigurationError,
    ServicePrincipal,
    verify_service_jwt,
)

bearer = HTTPBearer(auto_error=False)
service_bearer = HTTPBearer(auto_error=False, scheme_name="ServiceJWT")


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


def require_service_scopes(*required_scopes: str, audience: str | None = None) -> Callable:
    """Build a fail-closed dependency for the shared SYS-02 Service JWT contract."""
    scopes = frozenset(required_scopes)
    if not scopes or any(not scope for scope in scopes):
        raise ValueError("At least one non-empty service scope is required")

    def check_service(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(service_bearer)],
    ) -> ServicePrincipal:
        if credentials is None:
            raise AppError(401)
        try:
            return verify_service_jwt(
                credentials.credentials,
                required_scopes=scopes,
                audience=audience,
            )
        except ServiceJwtConfigurationError as exc:
            raise AppError(503, "Internal authentication unavailable") from exc
        except InsufficientServiceScope as exc:
            raise AppError(403) from exc
        except InvalidServiceJwt as exc:
            raise AppError(401) from exc

    return check_service
