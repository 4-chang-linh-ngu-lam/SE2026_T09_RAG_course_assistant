from __future__ import annotations

import json
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.common.auth_dependencies import require_service_scopes
from app.common.config import settings
from app.common.errors import register_error_handlers
from app.common.security import create_access_token
from app.common.service_jwt import (
    InvalidServiceJwt,
    ServiceJwtConfigurationError,
    ServicePrincipal,
    issue_service_jwt,
    verify_service_jwt,
)

SERVICE_AUTH_DEPENDENCY = Depends(require_service_scopes("core:check_access"))

ISSUER = "https://issuer.example.invalid/document"
SERVICE_ID = "document"
AUDIENCE = "core"
KEY_ID = "document-key-1"
ALLOWED_SCOPES = ["core:check_access", "core:read"]


def _key_pair(tmp_path: Path, name: str):
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = tmp_path / f"{name}-private.pem"
    public_path = tmp_path / f"{name}-public.pem"
    private_path.write_bytes(
        private.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private, private_path, public_path


def _trust_entry(
    issuer: str,
    subject: str,
    public_path: Path,
    scopes: list[str] | None = None,
) -> dict:
    return {
        "issuer": issuer,
        "subject": subject,
        "public_key_file": str(public_path),
        "audiences": [AUDIENCE],
        "scopes": scopes if scopes is not None else ALLOWED_SCOPES,
    }


@pytest.fixture
def service_keys(tmp_path, monkeypatch):
    private, private_path, public_path = _key_pair(tmp_path, KEY_ID)
    trusted = {KEY_ID: _trust_entry(ISSUER, SERVICE_ID, public_path)}
    monkeypatch.setattr(settings, "service_jwt_identity", SERVICE_ID)
    monkeypatch.setattr(settings, "service_jwt_issuer", ISSUER)
    monkeypatch.setattr(settings, "service_jwt_key_id", KEY_ID)
    monkeypatch.setattr(settings, "service_jwt_private_key_file", str(private_path))
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", json.dumps(trusted))
    monkeypatch.setattr(settings, "service_jwt_expected_audience", AUDIENCE)
    monkeypatch.setattr(settings, "service_jwt_issued_audiences", [AUDIENCE])
    monkeypatch.setattr(settings, "service_jwt_issued_scopes", ALLOWED_SCOPES)
    monkeypatch.setattr(settings, "service_jwt_ttl_seconds", 300)
    monkeypatch.setattr(settings, "service_jwt_clock_skew_seconds", 30)
    return private, private_path, public_path, trusted


def _payload(**changes) -> dict:
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "sub": SERVICE_ID,
        "aud": AUDIENCE,
        "scope": ["core:check_access"],
        "token_type": "service",
        "iat": now,
        "exp": now + 300,
    }
    payload.update(changes)
    return payload


def _sign(payload: dict, private_key, kid: str = KEY_ID, algorithm: str = "RS256") -> str:
    return jwt.encode(
        payload,
        private_key if algorithm == "RS256" else "test-not-a-service-key-" + "x" * 32,
        algorithm=algorithm,
        headers={"kid": kid, "typ": "JWT"},
    )


def _sign_raw_claims(payload: dict, private_key, kid: str = KEY_ID) -> str:
    header = jwt.utils.base64url_encode(
        json.dumps({"alg": "RS256", "kid": kid, "typ": "JWT"}, separators=(",", ":")).encode()
    )
    body = jwt.utils.base64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = header + b"." + body
    signature = private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return (signing_input + b"." + jwt.utils.base64url_encode(signature)).decode()


def _app():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/internal")
    def internal(principal: ServicePrincipal = SERVICE_AUTH_DEPENDENCY):
        return {"service_id": principal.service_id, "scopes": sorted(principal.scopes)}

    return app


def test_issue_and_verify_service_jwt(service_keys):
    token = issue_service_jwt(audience=AUDIENCE, scopes={"core:check_access"})
    principal = verify_service_jwt(token, audience=AUDIENCE, required_scopes={"core:check_access"})
    assert principal.service_id == SERVICE_ID
    assert principal.issuer == ISSUER
    assert principal.audience == AUDIENCE
    assert principal.scopes == {"core:check_access"}
    assert principal.key_id == KEY_ID


def test_fastapi_service_dependency_accepts_valid_token(service_keys):
    token = issue_service_jwt(audience=AUDIENCE, scopes={"core:check_access"})
    response = TestClient(_app()).get("/internal", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["service_id"] == SERVICE_ID


def test_fastapi_service_dependency_rejects_missing_token(service_keys):
    response = TestClient(_app()).get("/internal")
    assert response.status_code == 401


def test_x_service_key_does_not_authenticate_service_jwt_dependency(service_keys):
    response = TestClient(_app()).get("/internal", headers={"X-Service-Key": "legacy-key"})
    assert response.status_code == 401


def test_malformed_token_is_rejected(service_keys):
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt("not-a-jwt", required_scopes={"core:check_access"})


def test_unsupported_algorithm_is_rejected(service_keys):
    token = _sign(_payload(), service_keys[0], algorithm="HS256")
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_invalid_signature_is_rejected(service_keys, tmp_path):
    untrusted, _, _ = _key_pair(tmp_path, "untrusted")
    token = _sign(_payload(), untrusted)
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_wrong_issuer_is_rejected(service_keys):
    token = _sign(_payload(iss="https://issuer.example.invalid/other"), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_wrong_audience_is_rejected(service_keys):
    token = _sign(_payload(aud="learning"), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_spoofed_service_subject_is_rejected(service_keys):
    token = _sign(_payload(sub="core"), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


@pytest.mark.parametrize("claim", ["iss", "sub", "aud", "scope", "token_type", "iat", "exp"])
def test_missing_required_claim_is_rejected(service_keys, claim):
    payload = _payload()
    payload.pop(claim)
    token = _sign(payload, service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_expired_token_is_rejected(service_keys):
    now = int(time.time())
    token = _sign(_payload(iat=now - 600, exp=now - 300), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_future_issued_token_outside_skew_is_rejected(service_keys):
    now = int(time.time())
    token = _sign(_payload(iat=now + 120, exp=now + 420), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_token_ttl_over_system_limit_is_rejected(service_keys):
    now = int(time.time())
    token = _sign(_payload(iat=now, exp=now + 301), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_missing_required_scope_is_forbidden(service_keys):
    token = issue_service_jwt(audience=AUDIENCE, scopes={"core:read"})
    response = TestClient(_app()).get("/internal", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_user_jwt_is_not_a_service_jwt(service_keys, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr("unit-test-user-key-" + "x" * 32))
    token = create_access_token(__import__("uuid").uuid4(), ["LECTURER"], 1)
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_user_token_type_is_not_accepted_as_service_token(service_keys):
    token = _sign(_payload(token_type="user"), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_unknown_kid_is_rejected(service_keys):
    token = _sign(_payload(), service_keys[0], kid="unknown-key")
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_invalid_token_error_does_not_echo_bearer_token(service_keys):
    token = "opaque-private-token-value"
    with pytest.raises(InvalidServiceJwt) as error:
        verify_service_jwt(token, required_scopes={"core:check_access"})
    assert token not in str(error.value)


def test_scope_escalation_is_rejected_for_trusted_key(service_keys):
    token = _sign(_payload(scope=["core:admin"]), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:admin"})


def test_allowed_scopes_are_bound_to_each_calling_service(service_keys, tmp_path, monkeypatch):
    _private, _, document_public, _ = service_keys
    learning_private, _, learning_public = _key_pair(tmp_path, "learning-key")
    learning_issuer = "https://issuer.example.invalid/learning"
    learning_id = "learning"
    trusted = {
        KEY_ID: _trust_entry(ISSUER, SERVICE_ID, document_public, ["core:check_access"]),
        "learning-key": _trust_entry(
            learning_issuer, learning_id, learning_public, ["core:read_progress"]
        ),
    }
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", json.dumps(trusted))
    learning_token = _sign(
        _payload(
            iss=learning_issuer,
            sub=learning_id,
            scope=["core:read_progress"],
        ),
        learning_private,
        kid="learning-key",
    )
    assert (
        verify_service_jwt(learning_token, required_scopes={"core:read_progress"}).service_id
        == learning_id
    )

    escalated_token = _sign(
        _payload(
            iss=learning_issuer,
            sub=learning_id,
            scope=["core:check_access"],
        ),
        learning_private,
        kid="learning-key",
    )
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(escalated_token, required_scopes={"core:check_access"})


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("iss", [ISSUER]),
        ("sub", 123),
        ("aud", [AUDIENCE]),
        ("scope", "core:check_access"),
        ("token_type", ["service"]),
        ("iat", 1.5),
        ("exp", True),
    ],
)
def test_invalid_claim_types_are_rejected(service_keys, claim, value):
    token = _sign_raw_claims(_payload(**{claim: value}), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


@pytest.mark.parametrize("claim", ["iat", "exp", "nbf"])
@pytest.mark.parametrize(
    "value",
    [[], {}, None, True, False],
    ids=["list", "dict", "null", "true", "false"],
)
def test_invalid_temporal_claim_types_are_rejected(service_keys, claim, value):
    token = _sign_raw_claims(_payload(**{claim: value}), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


@pytest.mark.parametrize("claim", ["iat", "exp", "nbf"])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
    ],
)
def test_non_finite_temporal_claims_are_rejected(service_keys, claim, value):
    token = _sign_raw_claims(_payload(**{claim: value}), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


def test_optional_not_before_claim_is_supported(service_keys):
    token = _sign(_payload(nbf=int(time.time()) - 1), service_keys[0])
    principal = verify_service_jwt(token, required_scopes={"core:check_access"})
    assert principal.service_id == SERVICE_ID


def test_not_before_claim_is_enforced_with_clock_skew(service_keys):
    now = int(time.time())
    token = _sign(_payload(nbf=now + 120), service_keys[0])
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(token, required_scopes={"core:check_access"})


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("exp", []),
        ("nbf", {}),
        ("iat", float("inf")),
    ],
)
def test_fastapi_dependency_returns_401_for_malformed_signed_temporal_claims(
    service_keys, claim, value
):
    token = _sign_raw_claims(_payload(**{claim: value}), service_keys[0])
    response = TestClient(_app(), raise_server_exceptions=False).get(
        "/internal", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 401


def test_rotation_accepts_old_and_new_kids_during_overlap(service_keys, tmp_path, monkeypatch):
    old_private, _, old_public, _ = service_keys
    _new_private, new_private_path, new_public = _key_pair(tmp_path, "document-key-2")
    trusted = {
        KEY_ID: _trust_entry(ISSUER, SERVICE_ID, old_public),
        "document-key-2": _trust_entry(ISSUER, SERVICE_ID, new_public),
    }
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", json.dumps(trusted))
    old_token = _sign(_payload(), old_private, kid=KEY_ID)
    monkeypatch.setattr(settings, "service_jwt_key_id", "document-key-2")
    monkeypatch.setattr(settings, "service_jwt_private_key_file", str(new_private_path))
    new_token = issue_service_jwt(audience=AUDIENCE, scopes={"core:check_access"})
    assert verify_service_jwt(old_token, required_scopes={"core:check_access"}).key_id == KEY_ID
    assert (
        verify_service_jwt(new_token, required_scopes={"core:check_access"}).key_id
        == "document-key-2"
    )


def test_removed_key_is_rejected_after_rotation(service_keys, tmp_path, monkeypatch):
    old_private, _, _, _ = service_keys
    _new_private, _, new_public = _key_pair(tmp_path, "document-key-2")
    old_token = _sign(_payload(), old_private, kid=KEY_ID)
    trusted = {"document-key-2": _trust_entry(ISSUER, SERVICE_ID, new_public)}
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", json.dumps(trusted))
    with pytest.raises(InvalidServiceJwt):
        verify_service_jwt(old_token, required_scopes={"core:check_access"})


def test_signer_rejects_unconfigured_audience(service_keys):
    with pytest.raises(ServiceJwtConfigurationError):
        issue_service_jwt(audience="notification", scopes={"core:check_access"})


def test_signer_rejects_unconfigured_scope(service_keys):
    with pytest.raises(ServiceJwtConfigurationError):
        issue_service_jwt(audience=AUDIENCE, scopes={"core:admin"})


def test_missing_trust_configuration_fails_closed(service_keys, monkeypatch):
    token = issue_service_jwt(audience=AUDIENCE, scopes={"core:check_access"})
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", None)
    response = TestClient(_app()).get("/internal", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503


def test_invalid_trust_json_fails_closed(service_keys, monkeypatch):
    token = issue_service_jwt(audience=AUDIENCE, scopes={"core:check_access"})
    monkeypatch.setattr(settings, "service_jwt_trusted_keys_json", "{")
    response = TestClient(_app()).get("/internal", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 503


def test_private_key_failure_is_configuration_error(service_keys, monkeypatch):
    monkeypatch.setattr(settings, "service_jwt_private_key_file", "missing-private.pem")
    with pytest.raises(ServiceJwtConfigurationError):
        issue_service_jwt(audience=AUDIENCE, scopes={"core:check_access"})
