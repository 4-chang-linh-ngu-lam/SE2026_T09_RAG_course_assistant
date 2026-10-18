import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, or_, select
from sqlalchemy.orm import Session

from app.bootstrap import register_routers
from app.common.audit import AuditEvent
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, register_error_handlers
from app.modules.identity.email_delivery import get_token_sender
from app.modules.identity.http_security import REFRESH_COOKIE
from app.modules.identity.idempotency import IdempotencyStore, get_idempotency_store
from app.modules.identity.models import DataRequest, Role, RoleAssignment, User, UserStatus
from app.modules.identity.rate_limit import RateLimiter, get_rate_limiter
from app.modules.identity.schemas import RegisterRequest
from app.modules.identity.service import IdentityService

PASSWORD = "test-only password long enough"
ORIGIN = {"Origin": "https://app.example.com"}


class FakeSender:
    def __init__(self):
        self.deliveries = []
        self.fail = False

    def send(self, delivery):
        if self.fail:
            raise AppError(503, "Email delivery unavailable")
        self.deliveries.append(delivery)


@pytest.fixture(scope="module")
def engine():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    core_dir = Path(__file__).resolve().parents[2]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "migrations"))
    previous = settings.database_url
    settings.database_url = database_url
    try:
        command.upgrade(config, "head")
        command.check(config)
    finally:
        settings.database_url = previous
    test_engine = create_engine(
        database_url, hide_parameters=True, connect_args={"options": "-c timezone=UTC"}
    )
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def http(engine, monkeypatch):
    monkeypatch.setattr(
        settings, "secret_key", SecretStr("test-only-router-signing-key-" + "x" * 32)
    )
    monkeypatch.setattr(settings, "cors_origins", ["https://app.example.com"])
    monkeypatch.setattr(settings, "cookie_secure", True)
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)
    sender = FakeSender()
    limiter = RateLimiter()
    cache = IdempotencyStore()
    emails = []
    app.state.student_ids = []

    def test_db():
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_token_sender] = lambda: sender
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_idempotency_store] = lambda: cache
    with TestClient(app, base_url="https://core.example.com") as client:

        def register(*, verify=True, email=None, headers=None):
            # Seed a pre-existing legacy account; the public registration route is blocked.
            email = email or f"student-{uuid4().hex}@example.com"
            emails.append(email.lower())
            with Session(engine, autoflush=False, expire_on_commit=False) as session:
                result = IdentityService(session).register(
                    RegisterRequest(email=email, password=PASSWORD), deliver=sender.send
                )
                assignment = session.scalar(
                    select(RoleAssignment).where(RoleAssignment.user_id == result.response.user_id)
                )
                assignment.role = Role.LECTURER
                session.commit()
            response = Response(201, json=result.response.model_dump(mode="json"))
            if response.status_code == 201 and verify:
                verification = client.post(
                    "/api/v1/auth/verify-email",
                    json={"token": sender.deliveries[-1].token.get_secret_value()},
                )
                assert verification.status_code == 200
            return email, response

        yield client, sender, register, app
    with engine.begin() as connection:
        owned_ids = list(connection.scalars(select(User.id).where(User.email.in_(emails))))
        owned_ids.extend(app.state.student_ids)
        connection.execute(delete(DataRequest).where(DataRequest.user_id.in_(owned_ids)))
        connection.execute(
            delete(AuditEvent).where(
                or_(AuditEvent.actor_id.in_(owned_ids), AuditEvent.target_id.in_(owned_ids))
            )
        )
        connection.execute(delete(User).where(User.id.in_(owned_ids)))


def login(client, email, password=PASSWORD, headers=None):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}, headers=headers
    )


def bearer(response):
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_legacy_verify_login_and_cookie_rotation(http):
    client, sender, register, _ = http
    email, registered = register(verify=False)
    assert registered.status_code == 201
    assert registered.json()["status"] == "PENDING_VERIFICATION"
    assert sender.deliveries[-1].token.get_secret_value() not in registered.text
    assert login(client, email).status_code == 401
    token = sender.deliveries[-1].token.get_secret_value()
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).json() == {
        "verified": True
    }
    authenticated = login(client, email)
    assert authenticated.status_code == 200
    assert set(authenticated.json()) == {"access_token", "token_type", "expires_in"}
    cookie = authenticated.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
    assert "Path=/api/v1/auth" in cookie and "Max-Age=" in cookie
    assert authenticated.headers["cache-control"] == "no-store"
    original = client.cookies.get(REFRESH_COOKIE)
    refreshed = client.post("/api/v1/auth/refresh", headers=ORIGIN)
    assert refreshed.status_code == 200
    assert client.cookies.get(REFRESH_COOKIE) != original
    logout = client.post("/api/v1/auth/logout", headers=ORIGIN)
    assert logout.status_code == 204 and not logout.content
    assert "Max-Age=0" in logout.headers["set-cookie"]
    assert client.cookies.get(REFRESH_COOKIE) is None


@pytest.mark.parametrize("path", ["refresh", "logout"])
def test_cookie_mutations_reject_missing_or_foreign_origin(http, path):
    client, _, register, _ = http
    email, _ = register()
    assert login(client, email).status_code == 200
    before = client.cookies.get(REFRESH_COOKIE)
    for headers in (
        {},
        {"Origin": "https://attacker.com"},
        {"Origin": "null", "Referer": "https://app.example.com"},
    ):
        response = client.post(f"/api/v1/auth/{path}", headers=headers)
        assert response.status_code == 403
        assert client.cookies.get(REFRESH_COOKIE) == before
    assert client.post(
        f"/api/v1/auth/{path}", headers={"Referer": "https://app.example.com/settings"}
    ).status_code in (200, 204)


def test_login_rejects_foreign_origin_before_setting_cookie(http):
    client, _, register, _ = http
    email, _ = register()
    response = login(client, email, headers={"Origin": "https://attacker.com"})
    assert response.status_code == 403 and "set-cookie" not in response.headers


def test_login_rate_limit(http):
    client, _, register, _ = http
    email, _ = register()
    for _ in range(5):
        assert login(client, email, "incorrect").status_code == 401
    denied = login(client, email, "incorrect", {"X-Forwarded-For": "192.0.2.200"})
    assert denied.status_code == 429
    assert denied.json()["error"]["code"] == "RATE_LIMITED"
    assert int(denied.headers["retry-after"]) > 0


def test_public_registration_always_blocked_without_db_smtp_or_cache(http, engine, monkeypatch):
    client, sender, _, app = http
    app.dependency_overrides.pop(get_token_sender)
    monkeypatch.setattr(settings, "smtp_host", None)
    email = f"blocked-{uuid4().hex}@example.com"
    headers = {"Idempotency-Key": str(uuid4())}
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/register", headers=headers, json={"email": email, "password": PASSWORD}
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "FORBIDDEN"
    assert sender.deliveries == []
    with Session(engine) as session:
        assert session.scalar(select(User).where(User.email == email)) is None


def test_forgot_is_generic_and_rate_limited(http):
    client, _, register, _ = http
    email, _ = register()
    known = client.post("/api/v1/auth/password/forgot", json={"email": email})
    unknown = client.post("/api/v1/auth/password/forgot", json={"email": "unknown@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert client.post("/api/v1/auth/password/forgot", json={"email": email}).status_code == 200
    assert client.post("/api/v1/auth/password/forgot", json={"email": email}).status_code == 429


def test_reset_password_http_revokes_access_and_refresh(http):
    client, sender, register, _ = http
    email, _ = register()
    authenticated = login(client, email)
    headers = bearer(authenticated)
    assert client.post("/api/v1/auth/password/forgot", json={"email": email}).status_code == 200
    payload = {
        "token": sender.deliveries[-1].token.get_secret_value(),
        "new_password": "new test-only password long enough",
    }
    reset = client.post("/api/v1/auth/password/reset", json=payload)
    assert reset.status_code == 204 and "Max-Age=0" in reset.headers["set-cookie"]
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/password/reset", json=payload).status_code == 400
    assert login(client, email).status_code == 401
    assert login(client, email, payload["new_password"]).status_code == 200


def test_profile_and_logout_all(http):
    client, _, register, _ = http
    email, registered = register()
    headers = bearer(login(client, email))
    assert client.get("/api/v1/users/me").status_code == 401
    profile = client.get("/api/v1/users/me", headers=headers)
    assert profile.status_code == 200
    assert set(profile.json()) == {
        "id",
        "email",
        "username",
        "school_id",
        "display_name",
        "roles",
        "status",
    }
    assert profile.json()["id"] == registered.json()["user_id"]
    assert "hash" not in profile.text
    updated = client.patch("/api/v1/users/me", headers=headers, json={"display_name": "Student"})
    assert updated.json()["display_name"] == "Student"
    assert (
        client.patch("/api/v1/users/me", headers=headers, json={}).json()["display_name"]
        == "Student"
    )
    assert (
        client.patch("/api/v1/users/me", headers=headers, json={"roles": ["ADMIN"]}).status_code
        == 422
    )
    key_headers = {**headers, "Idempotency-Key": str(uuid4())}
    assert client.patch("/api/v1/users/me", headers=key_headers, json={}).status_code == 200
    assert (
        client.patch(
            "/api/v1/users/me", headers=key_headers, json={"display_name": None}
        ).status_code
        == 409
    )
    assert client.post("/api/v1/auth/logout-all", headers=headers).status_code == 204
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers=ORIGIN).status_code == 401


def test_locked_user_cannot_read_profile_or_login(http, engine):
    client, _, register, _ = http
    email, registered = register()
    authenticated = login(client, email)
    with Session(engine) as session:
        IdentityService(session).set_user_status(registered.json()["user_id"], UserStatus.LOCKED)
    assert client.get("/api/v1/users/me", headers=bearer(authenticated)).status_code == 401
    assert login(client, email).status_code == 401


def test_email_failure_rolls_back_legacy_fixture_and_reset(http, engine, caplog):
    client, sender, register, _ = http
    sender.fail = True
    email = f"delivery-{uuid4().hex}@example.com"
    with pytest.raises(AppError, match="Email delivery unavailable"):
        register(verify=False, email=email)
    with Session(engine) as session:
        assert session.scalar(select(User).where(User.email == email)) is None
    sender.fail = False
    register(email=email)
    sender.fail = True
    response = client.post("/api/v1/auth/password/forgot", json={"email": email})
    assert response.status_code == 200
    assert "Password reset email delivery failed" in caplog.text
    assert email not in caplog.text


def test_missing_smtp_configuration_rejects_before_registration(http, engine, monkeypatch):
    client, _, _, app = http
    app.dependency_overrides.pop(get_token_sender)
    monkeypatch.setattr(settings, "smtp_host", None)
    email = f"blocked-{uuid4().hex}@example.com"
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 403
    with Session(engine) as session:
        assert session.scalar(select(User).where(User.email == email)) is None


def test_idempotent_legacy_verify_login_refresh_and_blocked_register(http):
    client, sender, register, _ = http
    headers = {"Idempotency-Key": str(uuid4())}
    email, first = register(verify=False, headers=headers)
    assert first.status_code == 201 and len(sender.deliveries) == 1
    mismatch = client.post(
        "/api/v1/auth/register",
        headers=headers,
        json={"email": email, "password": "different test-only password"},
    )
    assert mismatch.status_code == 403
    verify_headers = {"Idempotency-Key": str(uuid4())}
    body = {"token": sender.deliveries[-1].token.get_secret_value()}
    assert (
        client.post("/api/v1/auth/verify-email", headers=verify_headers, json=body).status_code
        == 200
    )
    assert (
        client.post("/api/v1/auth/verify-email", headers=verify_headers, json=body).status_code
        == 200
    )
    login_headers = {"Idempotency-Key": str(uuid4())}
    first_login = login(client, email, headers=login_headers)
    repeat_login = login(client, email, headers=login_headers)
    assert first_login.json() == repeat_login.json()
    old_cookie = client.cookies.get(REFRESH_COOKIE)
    refresh_headers = {
        **ORIGIN,
        "Idempotency-Key": str(uuid4()),
        "Cookie": f"{REFRESH_COOKIE}={old_cookie}",
    }
    first_refresh = client.post("/api/v1/auth/refresh", headers=refresh_headers)
    second_refresh = client.post("/api/v1/auth/refresh", headers=refresh_headers)
    assert first_refresh.status_code == second_refresh.status_code == 200
    assert first_refresh.headers["set-cookie"] == second_refresh.headers["set-cookie"]
    assert (
        client.post("/api/v1/auth/refresh", headers={"Idempotency-Key": str(uuid4())}).status_code
        == 403
    )


def test_cached_login_cannot_bypass_lock_or_logout_all(http, engine):
    client, _, register, _ = http
    email, registered = register()
    headers = {"Idempotency-Key": str(uuid4())}
    authenticated = login(client, email, headers=headers)
    assert authenticated.status_code == 200
    assert client.post("/api/v1/auth/logout-all", headers=bearer(authenticated)).status_code == 204
    assert login(client, email, headers=headers).status_code == 401
    with Session(engine) as session:
        IdentityService(session).set_user_status(registered.json()["user_id"], UserStatus.LOCKED)
    assert login(client, email, headers=headers).status_code == 401


def test_cached_refresh_cannot_replay_revoked_session(http):
    client, _, register, _ = http
    email, _ = register()
    authenticated = login(client, email)
    old_cookie = client.cookies.get(REFRESH_COOKIE)
    refresh_headers = {
        **ORIGIN,
        "Idempotency-Key": str(uuid4()),
        "Cookie": f"{REFRESH_COOKIE}={old_cookie}",
    }
    assert client.post("/api/v1/auth/refresh", headers=refresh_headers).status_code == 200
    assert client.post("/api/v1/auth/logout-all", headers=bearer(authenticated)).status_code == 204
    assert client.post("/api/v1/auth/refresh", headers=refresh_headers).status_code == 401


def test_login_without_signing_key_fails_closed(http, monkeypatch):
    client, _, register, _ = http
    email, _ = register()
    monkeypatch.setattr(settings, "secret_key", None)
    response = login(client, email)
    assert response.status_code == 503
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("request_type", ["ACCESS", "EXPORT", "CORRECTION", "DELETE"])
def test_personal_data_requests_create_and_list(http, request_type):
    client, _, register, _ = http
    email, registered = register()
    headers = bearer(login(client, email))
    body = {"type": request_type, "reason": "test-only personal request"}
    created = client.post("/api/v1/users/me/data-requests", headers=headers, json=body)
    assert created.status_code == 201
    request = created.json()
    assert request["user_id"] == registered.json()["user_id"]
    assert request["type"] == request_type and request["status"] == "PENDING"
    assert request["resolution_note"] is None
    listed = client.get("/api/v1/users/me/data-requests", headers=headers)
    assert listed.json() == {"items": [request], "next_cursor": None}
    assert listed.headers["cache-control"] == "no-store"
    # Creating DELETE records an application request; it does not delete/lock the account.
    assert client.get("/api/v1/users/me", headers=headers).status_code == 200


def test_data_requests_pagination_and_cross_user_access(http):
    client, _, register, _ = http
    first_email, first_user = register()
    first_headers = bearer(login(client, first_email))
    second_email, second_user = register()
    second_headers = bearer(login(client, second_email))
    foreign = client.post(
        "/api/v1/users/me/data-requests",
        headers=second_headers,
        json={"type": "EXPORT", "reason": "foreign private reason"},
    ).json()
    ids = []
    for request_type in ("ACCESS", "EXPORT", "DELETE"):
        created = client.post(
            "/api/v1/users/me/data-requests", headers=first_headers, json={"type": request_type}
        )
        assert created.status_code == 201
        ids.append(created.json()["id"])
    seen = []
    cursor = None
    while True:
        params = {"limit": 1, "user_id": second_user.json()["user_id"]}
        if cursor:
            params["cursor"] = cursor
        response = client.get(
            "/api/v1/users/me/data-requests", headers=first_headers, params=params
        )
        assert response.status_code == 200 and "foreign private reason" not in response.text
        page = response.json()
        assert all(item["user_id"] == first_user.json()["user_id"] for item in page["items"])
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == sorted(ids)
    assert foreign["id"] not in seen
    assert (
        client.get(
            f"/api/v1/users/me/data-requests/{foreign['id']}", headers=first_headers
        ).status_code
        == 404
    )
    forged = client.post(
        "/api/v1/users/me/data-requests",
        headers=first_headers,
        json={"type": "DELETE", "user_id": second_user.json()["user_id"]},
    )
    assert forged.status_code == 422


def test_data_request_alias_idempotency_and_validation(http, engine):
    client, _, register, _ = http
    email, registered = register()
    headers = {**bearer(login(client, email)), "Idempotency-Key": str(uuid4())}
    canonical = client.post(
        "/api/v1/users/me/data-requests", headers=headers, json={"type": "EXPORT"}
    )
    alias = client.post(
        "/api/v1/users/me/data-requests", headers=headers, json={"request_type": "EXPORT"}
    )
    assert canonical.status_code == alias.status_code == 201
    assert canonical.json() == alias.json()
    assert (
        client.post(
            "/api/v1/users/me/data-requests", headers=headers, json={"type": "DELETE"}
        ).status_code
        == 409
    )
    for body in (
        {"type": "UNKNOWN"},
        {"type": "EXPORT", "status": "COMPLETED"},
        {"type": "ACCESS", "resolution_note": "forged"},
        {"type": "ACCESS", "request_type": "DELETE"},
    ):
        assert (
            client.post("/api/v1/users/me/data-requests", headers=headers, json=body).status_code
            == 422
        )
    assert (
        client.get(
            "/api/v1/users/me/data-requests", headers=headers, params={"limit": 101}
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/users/me/data-requests", headers=headers, params={"cursor": "invalid"}
        ).status_code
        == 400
    )
    with Session(engine) as session:
        IdentityService(session).set_user_status(registered.json()["user_id"], UserStatus.LOCKED)
    assert (
        client.post(
            "/api/v1/users/me/data-requests", headers=headers, json={"type": "EXPORT"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/users/me/data-requests", headers=headers).status_code == 401
    assert client.post("/api/v1/users/me/data-requests", json={"type": "EXPORT"}).status_code == 401


def test_lecturer_can_submit_data_request(http, engine):
    client, _, register, _ = http
    email, registered = register()
    with Session(engine) as session:
        assert (
            session.scalar(
                select(RoleAssignment.role).where(
                    RoleAssignment.user_id == registered.json()["user_id"]
                )
            )
            == Role.LECTURER
        )
    headers = bearer(login(client, email))
    assert (
        client.post(
            "/api/v1/users/me/data-requests", headers=headers, json={"type": "DELETE"}
        ).status_code
        == 201
    )


@pytest.fixture
def student_http(http, engine):
    client, _, register, app = http
    email, account = register()
    actor_id = UUID(account.json()["user_id"])
    with Session(engine) as session:
        session.get(User, actor_id).school_id = uuid4()
        session.add(RoleAssignment(user_id=actor_id, role=Role.ADMIN))
        session.commit()
    headers = bearer(login(client, email))
    username = "student." + uuid4().hex
    created = client.post("/api/v1/admin/students", headers=headers, json={"username": username})
    assert created.status_code == 201
    data = created.json()
    app.state.student_ids.append(UUID(data["student"]["id"]))
    return client, headers, data, app


def activate(client, data, *, code=None, username=None):
    return client.post(
        "/api/v1/auth/activate",
        json={
            "username": username or data["student"]["username"],
            "activation_code": code or data["code"],
            "new_password": PASSWORD,
        },
    )


def student_login(client, data, *, headers=None, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login",
        headers=headers,
        json={
            "username": data["student"]["username"],
            "password": password,
        },
    )


def test_student_without_email_activates_and_uses_profile_refresh_requests(
    student_http, monkeypatch
):
    client, admin, data, app = student_http
    app.dependency_overrides.pop(get_token_sender)
    monkeypatch.setattr(settings, "smtp_host", None)
    assert data["student"]["email"] is None and data["purpose"] == "ACTIVATION"
    extra = client.post(
        "/api/v1/admin/students",
        headers=admin,
        json={"username": "student.extra." + uuid4().hex, "display_name": "Học sinh mới"},
    )
    assert extra.status_code == 201
    assert extra.json()["student"]["display_name"] == "Học sinh mới"
    app.state.student_ids.append(UUID(extra.json()["student"]["id"]))
    assert student_login(client, data).status_code == 401
    assert activate(client, data, username="another.student").status_code == 400
    activated = activate(client, data)
    assert activated.status_code == 204 and "Max-Age=0" in activated.headers["set-cookie"]
    assert activate(client, data).status_code == 400
    authenticated = student_login(client, data)
    assert authenticated.status_code == 200 and "HttpOnly" in authenticated.headers["set-cookie"]
    headers = bearer(authenticated)
    profile = client.get("/api/v1/users/me", headers=headers)
    assert profile.status_code == 200 and profile.json()["email"] is None
    assert profile.json()["username"] == data["student"]["username"]
    assert client.post("/api/v1/auth/refresh", headers=ORIGIN).status_code == 200
    assert (
        client.post(
            "/api/v1/users/me/data-requests", headers=headers, json={"type": "CORRECTION"}
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/v1/admin/students", headers=headers, json={"username": "forged.student"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/admin/students", headers=admin, json={"username": data["student"]["username"]}
        ).status_code
        == 409
    )


def test_student_code_reissue_recovery_and_lock_are_separate(student_http, engine):
    client, admin, data, _ = student_http
    path = f"/api/v1/admin/students/{data['student']['id']}/activation-codes"
    issued = client.post(path, headers=admin, json={})
    assert issued.status_code == 200
    assert activate(client, data).status_code == 400
    code = issued.json()["code"]
    assert activate(client, data, code=code).status_code == 204
    authenticated = student_login(client, data)
    headers = bearer(authenticated)
    assert client.post(path, headers=admin, json={}).status_code == 409
    recovery = client.post(path, headers=admin, json={"identity_verified": True})
    assert recovery.status_code == 200 and recovery.json()["purpose"] == "PASSWORD_RESET"
    assert client.get("/api/v1/users/me", headers=headers).status_code == 401
    reset_code = recovery.json()["code"]
    assert activate(client, data, code=reset_code).status_code == 400
    reset = {"token": reset_code, "new_password": "new test-only password long enough"}
    assert client.post("/api/v1/auth/password/reset", json=reset).status_code == 204
    assert client.post("/api/v1/auth/password/reset", json=reset).status_code == 400
    assert student_login(client, data).status_code == 401
    assert student_login(client, data, password=reset["new_password"]).status_code == 200
    with Session(engine) as session:
        user = session.get(User, UUID(data["student"]["id"]))
        IdentityService(session).set_user_status(user.id, UserStatus.LOCKED)
    assert client.post(path, headers=admin, json={"identity_verified": True}).status_code == 409
    assert student_login(client, data, password=reset["new_password"]).status_code == 401


def test_student_code_mutations_do_not_cache_secrets_and_scope_is_checked(student_http, engine):
    client, admin, data, app = student_http
    headers = {**admin, "Idempotency-Key": str(uuid4())}
    assert (
        client.post(
            "/api/v1/admin/students", headers=headers, json={"username": "unused.student"}
        ).status_code
        == 400
    )
    path = f"/api/v1/admin/students/{data['student']['id']}/activation-codes"
    assert client.post(path, headers=headers, json={}).status_code == 400
    assert (
        client.post(
            "/api/v1/auth/activate",
            headers=headers,
            json={
                "username": data["student"]["username"],
                "activation_code": data["code"],
                "new_password": PASSWORD,
            },
        ).status_code
        == 400
    )
    with Session(engine) as session:
        session.get(User, UUID(data["student"]["id"])).school_id = uuid4()
        session.commit()
    assert client.post(path, headers=admin, json={}).status_code == 404
    with Session(engine) as session:
        audits = session.scalars(
            select(AuditEvent).where(AuditEvent.target_id == UUID(data["student"]["id"]))
        ).all()
        assert len(audits) == 1 and data["code"] not in str([a.metadata_json for a in audits])
    store = app.dependency_overrides[get_idempotency_store]()
    assert data["code"] not in repr(store.entries)


def test_student_login_cache_checks_recovery_and_activation_rate_limit(student_http):
    client, admin, data, _ = student_http
    assert activate(client, data).status_code == 204
    headers = {"Idempotency-Key": str(uuid4())}
    first = student_login(client, data, headers=headers)
    second = student_login(client, data, headers=headers)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    path = f"/api/v1/admin/students/{data['student']['id']}/activation-codes"
    assert client.post(path, headers=admin, json={"identity_verified": True}).status_code == 200
    assert student_login(client, data, headers=headers).status_code == 401
    for _ in range(4):
        assert activate(client, data).status_code == 400
    assert activate(client, data).status_code == 429
