from collections.abc import Iterable

from lumi_service_auth import (
    MAX_SERVICE_JWT_TTL_SECONDS,
    SERVICE_JWT_ALGORITHM,
    SERVICE_JWT_TYPE,
    InsufficientServiceScope,
    InvalidServiceJwt,
    ServiceAuthConfig,
    ServiceJwtConfigurationError,
    ServiceJwtError,
    ServicePrincipal,
)
from lumi_service_auth import (
    issue_service_jwt as _issue_service_jwt,
)
from lumi_service_auth import (
    verify_service_jwt as _verify_service_jwt,
)

from app.common.config import settings


def _auth_config() -> ServiceAuthConfig:
    return ServiceAuthConfig(
        service_identity=settings.service_jwt_identity,
        issuer=settings.service_jwt_issuer,
        key_id=settings.service_jwt_key_id,
        private_key_file=settings.service_jwt_private_key_file,
        trusted_keys_json=settings.service_jwt_trusted_keys_json,
        expected_audience=settings.service_jwt_expected_audience,
        issued_audiences=tuple(settings.service_jwt_issued_audiences),
        issued_scopes=tuple(settings.service_jwt_issued_scopes),
        ttl_seconds=settings.service_jwt_ttl_seconds,
        clock_skew_seconds=settings.service_jwt_clock_skew_seconds,
    )


def issue_service_jwt(*, audience: str, scopes: Iterable[str], now: int | None = None) -> str:
    return _issue_service_jwt(_auth_config(), audience=audience, scopes=scopes, now=now)


def verify_service_jwt(
    token: str,
    *,
    required_scopes: Iterable[str],
    audience: str | None = None,
) -> ServicePrincipal:
    return _verify_service_jwt(
        token,
        _auth_config(),
        required_scopes=required_scopes,
        audience=audience,
    )


__all__ = [
    "MAX_SERVICE_JWT_TTL_SECONDS",
    "SERVICE_JWT_ALGORITHM",
    "SERVICE_JWT_TYPE",
    "InsufficientServiceScope",
    "InvalidServiceJwt",
    "ServiceAuthConfig",
    "ServiceJwtConfigurationError",
    "ServiceJwtError",
    "ServicePrincipal",
    "issue_service_jwt",
    "verify_service_jwt",
]
