from datetime import UTC, datetime
from typing import Annotated
from unittest.mock import Mock
from uuid import UUID, uuid4

import jwt
import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.common.audit import AuditEvent, AuditMetadata, record_audit
from app.common.auth_dependencies import (
    CurrentUser,
    get_user_lookup,
    require_roles,
    verify_internal_service_key,
)
from app.common.config import Settings, settings
from app.common.db import transaction
from app.common.errors import AppError, register_error_handlers
from app.common.pagination import Page, Pagination, decode_cursor, encode_cursor, get_pagination
from app.common.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


@pytest.fixture
def signing_key(monkeypatch):
    key = SecretStr("test-only-signing-key-" + "x" * 32)
    monkeypatch.setattr(settings, "secret_key", key)
    return key.get_secret_value()


def test_password_hashing():
    password = "test-only password"
    hashed = hash_password(password)
    assert hashed.startswith("$argon2id$")
    assert password not in hashed
    assert hash_password(password) != hashed
    assert verify_password(password, hashed)
    assert not verify_password("incorrect password", hashed)
    assert not verify_password(password, "invalid hash")


def test_access_token_roundtrip(signing_key):
    user_id = uuid4()
    claims = decode_access_token(create_access_token(user_id, ["STUDENT"], 3))
    assert claims.sub == user_id
    assert claims.roles == ["STUDENT"]
    assert claims.session_version == 3
    assert claims.exp - claims.iat == 15 * 60


@pytest.mark.parametrize(
    "invalid",
    ["expired", "signature", "missing", "uuid", "roles", "version", "algorithm", "future", "times"],
)
def test_access_token_rejects_invalid_claims(signing_key, invalid):
    now = int(datetime.now(UTC).timestamp())
    claims = {
        "sub": str(uuid4()),
        "roles": ["STUDENT"],
        "session_version": 1,
        "iat": now,
        "exp": now + 900,
    }
    key, algorithm = signing_key, "HS256"
    if invalid == "expired":
        claims.update(iat=now - 1000, exp=now - 100)
    elif invalid == "signature":
        key = "wrong-key-" + "x" * 32
    elif invalid == "missing":
        del claims["session_version"]
    elif invalid == "uuid":
        claims["sub"] = "invalid UUID"
    elif invalid == "roles":
        claims["roles"] = ["SUPERUSER"]
    elif invalid == "version":
        claims["session_version"] = True
    elif invalid == "algorithm":
        algorithm = "HS384"
    elif invalid == "future":
        claims["iat"] = now + 100
    else:
        claims["iat"] = claims["exp"]
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(jwt.encode(claims, key, algorithm=algorithm))


def test_refresh_tokens():
    first, second = generate_refresh_token(), generate_refresh_token()
    assert len(bytes.fromhex(first)) == 32
    assert first != second
    assert len(hash_refresh_token(first)) == 64
    assert hash_refresh_token(first) == hash_refresh_token(first)
    assert hash_refresh_token(first) != hash_refresh_token(second)


def test_config_validation():
    config = Settings(_env_file=None)
    assert config.access_token_expire_minutes == 15
    assert config.refresh_token_expire_days == 7
    assert config.cookie_secure and config.cookie_httponly
    assert config.cookie_samesite == "lax"
    for options in (
        {"secret_key": "short"},
        {"algorithm": "none"},
        {"cookie_httponly": False},
        {"access_token_expire_minutes": 0},
    ):
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **options)


@pytest.fixture
def test_app():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/error/{status}")
    def error(status: int):
        raise HTTPException(status, detail="private value")

    @app.get("/hidden")
    def hidden():
        raise AppError(404, "private resource name")

    @app.get("/unexpected")
    def unexpected():
        raise RuntimeError("private server data")

    @app.get("/page")
    def page(pagination: Annotated[Pagination, Depends(get_pagination)]):
        return pagination

    @app.get("/protected")
    def protected(user: Annotated[CurrentUser, Depends(require_roles("LECTURER"))]):
        return {"id": str(user.id)}

    @app.get("/internal")
    def internal(scopes: Annotated[frozenset[str], Depends(verify_internal_service_key)]):
        return sorted(scopes)

    return app


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "BAD_REQUEST"),
        (401, "UNAUTHENTICATED"),
        (403, "FORBIDDEN"),
        (404, "NOT_FOUND"),
        (409, "CONFLICT"),
        (422, "VALIDATION_ERROR"),
        (429, "RATE_LIMITED"),
        (503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_http_errors(test_app, status, code):
    correlation_id = str(uuid4())
    response = TestClient(test_app).get(
        f"/error/{status}", headers={"X-Correlation-ID": correlation_id}
    )
    assert response.status_code == status
    assert response.json() == {
        "error": {"code": code, "message": code, "correlation_id": correlation_id}
    }
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert "private" not in response.text


@pytest.mark.parametrize("header", [None, "invalid", str(uuid4())])
def test_correlation_id(test_app, header):
    headers = {} if header is None else {"X-Correlation-ID": header}
    response = TestClient(test_app).get("/page", headers=headers)
    returned = response.headers["X-Correlation-ID"]
    assert str(UUID(returned)) == returned
    if header not in (None, "invalid"):
        assert returned == header


def test_errors_redact_details(test_app):
    client = TestClient(test_app, raise_server_exceptions=False)
    for path, status in (
        ("/hidden", 404),
        ("/unexpected", 500),
        ("/page?limit=private-value", 422),
        ("/missing", 404),
    ):
        response = client.get(path)
        assert response.status_code == status
        assert "private" not in response.text
        assert response.json()["error"]["correlation_id"] == response.headers["X-Correlation-ID"]


def test_pagination(test_app):
    last_id = uuid4()
    cursor = encode_cursor(last_id)
    assert decode_cursor(cursor) == last_id
    client = TestClient(test_app)
    assert client.get("/page").json() == {"limit": 20, "cursor": None}
    assert client.get("/page", params={"limit": 100, "cursor": cursor}).json() == {
        "limit": 100,
        "cursor": str(last_id),
    }
    assert Page[int](items=[1]).model_dump() == {"items": [1], "next_cursor": None}
    for limit in (0, 101):
        assert client.get("/page", params={"limit": limit}).status_code == 422
    for invalid in ("", "not-a-cursor", "!" * 22):
        assert client.get("/page", params={"cursor": invalid}).status_code == 400


@pytest.mark.parametrize(
    "status,version,roles,expected",
    [
        ("ACTIVE", 2, ["LECTURER"], 200),
        ("LOCKED", 2, ["LECTURER"], 401),
        ("PENDING_VERIFICATION", 2, ["LECTURER"], 401),
        ("ACTIVE", 3, ["LECTURER"], 401),
        ("ACTIVE", 2, ["STUDENT"], 403),
    ],
)
def test_current_user_uses_live_identity(test_app, signing_key, status, version, roles, expected):
    user_id = uuid4()
    lookup = Mock(
        return_value=CurrentUser(id=user_id, status=status, session_version=version, roles=roles)
    )
    test_app.dependency_overrides[get_user_lookup] = lambda: lookup
    token = create_access_token(user_id, ["LECTURER"], 2)
    response = TestClient(test_app).get("/protected", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == expected
    lookup.assert_called_once_with(user_id)


def test_authentication_fails_closed(test_app, signing_key, monkeypatch):
    client = TestClient(test_app)
    token = create_access_token(uuid4(), ["LECTURER"], 0)
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 503
    lookup = Mock(return_value=None)
    test_app.dependency_overrides[get_user_lookup] = lambda: lookup
    assert client.get("/protected").status_code == 401
    assert client.get("/protected", headers={"Authorization": "Bearer forged"}).status_code == 401
    lookup.assert_not_called()
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    monkeypatch.setattr(settings, "secret_key", None)
    assert client.get("/protected", headers={"Authorization": f"Bearer {token}"}).status_code == 503


def test_internal_service_auth(test_app, monkeypatch):
    client = TestClient(test_app)
    monkeypatch.setattr(settings, "internal_service_secret", None)
    assert client.get("/internal").status_code == 503
    key = "test-only-internal-key-" + "x" * 32
    monkeypatch.setattr(settings, "internal_service_secret", SecretStr(key))
    assert client.get("/internal").status_code == 401
    assert client.get("/internal", headers={"X-Service-Key": "incorrect"}).status_code == 401
    response = client.get("/internal", headers={"X-Service-Key": key})
    assert response.status_code == 200
    assert response.json() == ["core:check_access"]


def test_transaction_commit_and_rollback():
    session = Mock()
    with transaction(session) as current:
        assert current is session
    session.commit.assert_called_once()
    session.rollback.assert_not_called()
    session.reset_mock()
    with pytest.raises(ValueError), transaction(session):
        raise ValueError("failed business operation")
    session.commit.assert_not_called()
    session.rollback.assert_called_once()
    session.reset_mock()
    session.commit.side_effect = RuntimeError("commit failed")
    with pytest.raises(RuntimeError), transaction(session):
        pass
    session.rollback.assert_called_once()


def test_audit_is_safe_and_does_not_commit():
    session = Mock()
    event = record_audit(
        session,
        actor_id=uuid4(),
        action="USER_LOCKED",
        target_type="USER",
        target_id=uuid4(),
        correlation_id=uuid4(),
        metadata_json=AuditMetadata(new_status="LOCKED"),
    )
    session.add.assert_called_once_with(event)
    session.commit.assert_not_called()
    assert event.metadata_json == {"changed_fields": [], "new_status": "LOCKED"}
    for field in ("password", "token", "chat", "document_text", "nested"):
        with pytest.raises(ValidationError):
            AuditMetadata(**{field: "private data"})
    with pytest.raises(ValidationError):
        AuditMetadata(changed_fields=["password"])
    mutated_metadata = AuditMetadata()
    mutated_metadata.changed_fields.append("password")
    with pytest.raises(ValidationError):
        record_audit(
            session,
            actor_id=None,
            action="LOCK",
            target_type="USER",
            target_id=uuid4(),
            correlation_id=uuid4(),
            metadata_json=mutated_metadata,
        )
    with pytest.raises(TypeError):
        record_audit(
            session,
            actor_id=None,
            action="LOCK",
            target_type="USER",
            target_id=uuid4(),
            correlation_id=uuid4(),
            metadata_json={"token": "private"},
        )


def test_base_and_audit_postgresql_schema():
    table = AuditEvent.__table__
    assert table.schema == "core"
    assert table.c.id.primary_key
    assert str(table.c.id.server_default.arg) == "gen_random_uuid()"
    assert table.c.created_at.type.timezone and table.c.updated_at.type.timezone
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "core.audit_events" in ddl
    assert "JSONB" in ddl
