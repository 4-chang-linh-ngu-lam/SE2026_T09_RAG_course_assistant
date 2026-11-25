from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jwt
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

SERVICE_JWT_ALGORITHM = "RS256"
SERVICE_JWT_TYPE = "service"
MAX_SERVICE_JWT_TTL_SECONDS = 300
MAX_SERVICE_JWT_CLOCK_SKEW_SECONDS = 30


class ServiceJwtError(Exception):
    """Base error for the Service JWT boundary."""


class ServiceJwtConfigurationError(ServiceJwtError):
    """The local service trust or signing configuration is missing or invalid."""


class InvalidServiceJwt(ServiceJwtError):
    """The presented token is not a trusted Service JWT."""


class InsufficientServiceScope(ServiceJwtError):
    """The token is valid but does not authorize the requested operation."""


@dataclass(frozen=True)
class ServiceAuthConfig:
    service_identity: str | None
    issuer: str | None
    key_id: str | None
    private_key_file: str | None
    trusted_keys_json: str | None
    expected_audience: str | None
    issued_audiences: tuple[str, ...] = ()
    issued_scopes: tuple[str, ...] = ()
    ttl_seconds: int = MAX_SERVICE_JWT_TTL_SECONDS
    clock_skew_seconds: int = MAX_SERVICE_JWT_CLOCK_SKEW_SECONDS


@dataclass(frozen=True)
class ServicePrincipal:
    issuer: str
    service_id: str
    audience: str
    scopes: frozenset[str]
    key_id: str


@dataclass(frozen=True)
class _TrustedServiceKey:
    issuer: str
    subject: str
    public_key_file: Path
    audiences: frozenset[str]
    scopes: frozenset[str]


def _required_setting(value: str | None, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ServiceJwtConfigurationError(f"{name} is not configured")
    return value.strip()


def _scope_set(value: Iterable[str], name: str) -> frozenset[str]:
    if isinstance(value, (str, bytes)):
        raise ServiceJwtConfigurationError(f"{name} must be a collection of scope strings")
    try:
        items = tuple(value)
    except TypeError as exc:
        raise ServiceJwtConfigurationError(f"{name} must be a collection of scope strings") from exc
    if not items or any(not isinstance(item, str) or not item.strip() for item in items):
        raise ServiceJwtConfigurationError(f"{name} must contain non-empty strings")
    normalized = tuple(item.strip() for item in items)
    if len(set(normalized)) != len(normalized):
        raise ServiceJwtConfigurationError(f"{name} contains duplicates")
    return frozenset(normalized)


def _string_set(value: Any, name: str) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ServiceJwtConfigurationError(f"{name} must be a non-empty string list")
    result = frozenset(item.strip() for item in value)
    if len(result) != len(value):
        raise ServiceJwtConfigurationError(f"{name} contains duplicates")
    return result


def _trusted_keys(config: ServiceAuthConfig) -> dict[str, _TrustedServiceKey]:
    raw = config.trusted_keys_json
    if not isinstance(raw, str) or not raw.strip():
        raise ServiceJwtConfigurationError("Service JWT trust keys are not configured")
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ServiceJwtConfigurationError("Service JWT trust keys are invalid") from exc
    if not isinstance(entries, dict) or not entries:
        raise ServiceJwtConfigurationError("Service JWT trust keys are empty")
    result: dict[str, _TrustedServiceKey] = {}
    for key_id, entry in entries.items():
        if not isinstance(key_id, str) or not key_id.strip() or not isinstance(entry, dict):
            raise ServiceJwtConfigurationError("Service JWT trust entry is invalid")
        issuer = _required_setting(entry.get("issuer"), "trusted issuer")
        subject = _required_setting(entry.get("subject"), "trusted service identity")
        public_key_file = _required_setting(entry.get("public_key_file"), "public key file")
        result[key_id] = _TrustedServiceKey(
            issuer=issuer,
            subject=subject,
            public_key_file=Path(public_key_file),
            audiences=_string_set(entry.get("audiences"), "trusted audiences"),
            scopes=_string_set(entry.get("scopes"), "trusted scopes"),
        )
    return result


def _load_private_key(path_value: str) -> RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(Path(path_value).read_bytes(), password=None)
    except (OSError, TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise ServiceJwtConfigurationError(
            "Service JWT private key is unavailable or invalid"
        ) from exc
    if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
        raise ServiceJwtConfigurationError(
            "Service JWT private key must be RSA with at least 2048 bits"
        )
    return key


def _load_public_key(path: Path) -> RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(path.read_bytes())
    except (OSError, TypeError, ValueError, UnsupportedAlgorithm) as exc:
        raise ServiceJwtConfigurationError(
            "Trusted Service JWT public key is unavailable or invalid"
        ) from exc
    if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
        raise ServiceJwtConfigurationError(
            "Trusted Service JWT key must be RSA with at least 2048 bits"
        )
    return key


def issue_service_jwt(
    config: ServiceAuthConfig,
    *,
    audience: str,
    scopes: Iterable[str],
    now: int | None = None,
) -> str:
    audience = _required_setting(audience, "issued audience")
    service_id = _required_setting(config.service_identity, "service identity")
    issuer = _required_setting(config.issuer, "service issuer")
    key_id = _required_setting(config.key_id, "service key ID")
    private_key_file = _required_setting(config.private_key_file, "private key file")
    allowed_audiences = _scope_set(config.issued_audiences, "issued audiences")
    allowed_scopes = _scope_set(config.issued_scopes, "issued scopes")
    normalized_scopes = _scope_set(scopes, "requested scopes")
    if audience not in allowed_audiences:
        raise ServiceJwtConfigurationError("Service JWT audience is not allowed for this service")
    if not normalized_scopes.issubset(allowed_scopes):
        raise ServiceJwtConfigurationError("Service JWT scope is not allowed for this service")
    if (
        type(config.ttl_seconds) is not int
        or not 1 <= config.ttl_seconds <= MAX_SERVICE_JWT_TTL_SECONDS
    ):
        raise ServiceJwtConfigurationError("Service JWT TTL exceeds the system limit")

    issued_at = int(time.time()) if now is None else int(now)
    payload = {
        "iss": issuer,
        "sub": service_id,
        "aud": audience,
        "scope": sorted(normalized_scopes),
        "token_type": SERVICE_JWT_TYPE,
        "iat": issued_at,
        "exp": issued_at + config.ttl_seconds,
    }
    try:
        return jwt.encode(
            payload,
            _load_private_key(private_key_file),
            algorithm=SERVICE_JWT_ALGORITHM,
            headers={"kid": key_id, "typ": "JWT"},
        )
    except (jwt.PyJWTError, TypeError, ValueError) as exc:
        raise ServiceJwtConfigurationError("Service JWT signing failed") from exc


def verify_service_jwt(
    token: str,
    config: ServiceAuthConfig,
    *,
    required_scopes: Iterable[str],
    audience: str | None = None,
) -> ServicePrincipal:
    expected_audience = _required_setting(
        audience if audience is not None else config.expected_audience, "expected audience"
    )
    required = _scope_set(required_scopes, "required scopes")
    if (
        type(config.clock_skew_seconds) is not int
        or not 0 <= config.clock_skew_seconds <= MAX_SERVICE_JWT_CLOCK_SKEW_SECONDS
    ):
        raise ServiceJwtConfigurationError("Service JWT clock skew exceeds the system limit")
    if not isinstance(token, str) or not token:
        raise InvalidServiceJwt("Token is missing")
    try:
        header = jwt.get_unverified_header(token)
    except (jwt.PyJWTError, TypeError, ValueError, OverflowError) as exc:
        raise InvalidServiceJwt("Malformed Service JWT") from exc
    if not isinstance(header, dict):
        raise InvalidServiceJwt("Malformed Service JWT header")
    if header.get("alg") != SERVICE_JWT_ALGORITHM or header.get("typ") != "JWT":
        raise InvalidServiceJwt("Unsupported Service JWT type or algorithm")
    key_id = header.get("kid")
    if not isinstance(key_id, str) or not key_id:
        raise InvalidServiceJwt("Service JWT key ID is missing")

    trusted = _trusted_keys(config).get(key_id)
    if trusted is None or expected_audience not in trusted.audiences:
        raise InvalidServiceJwt("Service JWT key or audience is not trusted")

    try:
        payload = jwt.decode(
            token,
            _load_public_key(trusted.public_key_file),
            algorithms=[SERVICE_JWT_ALGORITHM],
            issuer=trusted.issuer,
            audience=expected_audience,
            leeway=config.clock_skew_seconds,
            options={
                "require": ["iss", "sub", "aud", "scope", "token_type", "iat", "exp"],
                "verify_iat": True,
            },
        )
    except ServiceJwtConfigurationError:
        raise
    except jwt.PyJWTError as exc:
        raise InvalidServiceJwt("Service JWT validation failed") from exc
    except (TypeError, ValueError, OverflowError) as exc:
        raise InvalidServiceJwt("Service JWT validation failed") from exc

    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    raw_scopes = payload.get("scope")
    not_before = payload.get("nbf")
    if (
        not isinstance(payload.get("iss"), str)
        or not isinstance(payload.get("sub"), str)
        or not isinstance(payload.get("aud"), str)
        or not isinstance(payload.get("token_type"), str)
        or type(issued_at) is not int
        or type(expires_at) is not int
        or ("nbf" in payload and type(not_before) is not int)
        or not isinstance(raw_scopes, list)
        or any(not isinstance(scope, str) or not scope.strip() for scope in raw_scopes)
        or len(set(raw_scopes)) != len(raw_scopes)
    ):
        raise InvalidServiceJwt("Service JWT claim types are invalid")
    current_time = int(time.time())
    if (
        expires_at <= issued_at
        or expires_at - issued_at > MAX_SERVICE_JWT_TTL_SECONDS
        or issued_at > current_time + config.clock_skew_seconds
        or ("nbf" in payload and not_before > current_time + config.clock_skew_seconds)
    ):
        raise InvalidServiceJwt("Service JWT time claims are invalid")

    service_id = payload["sub"]
    if payload["token_type"] != SERVICE_JWT_TYPE or service_id != trusted.subject:
        raise InvalidServiceJwt("Service JWT identity is not trusted")
    token_scopes = frozenset(raw_scopes)
    if not token_scopes.issubset(trusted.scopes):
        raise InvalidServiceJwt("Service JWT contains an untrusted scope")
    if not required.issubset(token_scopes):
        raise InsufficientServiceScope("Required Service JWT scope is missing")

    return ServicePrincipal(
        issuer=trusted.issuer,
        service_id=service_id,
        audience=expected_audience,
        scopes=token_scopes,
        key_id=key_id,
    )
