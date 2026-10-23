import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Annotated
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.bootstrap import register_routers
from app.common.audit import AuditEvent
from app.common.auth_dependencies import CurrentUser, get_current_user, require_roles
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, register_error_handlers
from app.common.security import decode_access_token, hash_refresh_token, verify_password
from app.modules.identity import public
from app.modules.identity.models import (
    AuthSession,
    OneTimeToken,
    Role,
    RoleAssignment,
    TokenPurpose,
    User,
    UserStatus,
)
from app.modules.identity.public import get_current_user_snapshot
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    ActivateStudentRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from app.modules.identity.service import IdentityService

PASSWORD = "test-only password long enough"


@pytest.fixture(scope="module")
def engine():
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[2] / "migrations")
    )
    previous_url = settings.database_url
    settings.database_url = database_url
    try:
        command.upgrade(config, "head")
        command.check(config)
    finally:
        settings.database_url = previous_url
    test_engine = create_engine(
        database_url, hide_parameters=True, connect_args={"options": "-c timezone=UTC"}
    )
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def identity(engine, monkeypatch):
    monkeypatch.setattr(
        settings, "secret_key", SecretStr("test-only-identity-signing-key-" + "x" * 32)
    )
    session = Session(engine, autoflush=False, expire_on_commit=False)
    service = IdentityService(session)
    created_ids = []
    school_id = uuid4()

    def register(*, active=True):
        request = RegisterRequest(email=f"student-{uuid4().hex}@example.com", password=PASSWORD)
        result = service.register(request)
        created_ids.append(result.response.user_id)
        session.get(User, result.response.user_id).school_id = school_id
        # Staff fixture: the production Student email login/verification path is now disabled.
        assignment = session.scalar(
            select(RoleAssignment).where(RoleAssignment.user_id == result.response.user_id)
        )
        assignment.role = Role.LECTURER
        session.commit()
        if active:
            service.verify_email(VerifyEmailRequest(token=result.delivery.token))
        return request, result

    yield session, service, register
    session.close()
    with engine.begin() as connection:
        connection.execute(delete(User).where(User.id.in_(created_ids)))


def login(service, request):
    return service.login(LoginRequest(email=request.email, password=request.password))


def raw(tokens):
    return tokens.refresh_token.get_secret_value()


def test_auth_lookup_releases_connection_before_endpoint_and_reads_current_status(identity, engine):
    session, _, register = identity
    _, registered = register()
    user_id = registered.response.user_id
    constrained = create_engine(
        engine.url, hide_parameters=True, pool_size=1, max_overflow=0, pool_timeout=0.1
    )
    try:
        with Session(constrained) as endpoint_session:
            lookup = public.get_identity_user_lookup(endpoint_session)
            assert lookup(user_id).status == "ACTIVE"
            assert not endpoint_session.in_transaction()
            assert constrained.pool.checkedout() == 0
            # The endpoint can acquire the only connection without waiting for
            # request-dependency teardown or increasing pool/thread limits.
            assert endpoint_session.scalar(select(User.id).where(User.id == user_id)) == user_id
            endpoint_session.rollback()
            session.get(User, user_id).status = UserStatus.LOCKED
            session.commit()
            assert lookup(user_id).status == "LOCKED"
            assert constrained.pool.checkedout() == 0
    finally:
        constrained.dispose()


def expect_error(status, operation):
    with pytest.raises(AppError) as raised:
        operation()
    assert raised.value.status_code == status


def test_legacy_staff_email_verification(identity):
    session, service, register = identity
    request, result = register(active=False)
    repository = IdentityRepository(session)
    user = repository.get_by_id(result.response.user_id)
    assert user.status == UserStatus.PENDING_VERIFICATION
    assert user.session_version == 1
    assert repository.get_user_roles(user.id) == [Role.LECTURER]
    assert user.password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, user.password_hash)
    token = repository.get_one_time_token(
        hash_refresh_token(result.delivery.token.get_secret_value()),
        TokenPurpose.EMAIL_VERIFICATION,
    )
    assert token.token_hash != result.delivery.token.get_secret_value()
    assert token.consumed_at is None
    assert "password" not in result.response.model_dump()
    expect_error(401, lambda: login(service, request))
    expect_error(409, lambda: service.register(request))
    service.verify_email(VerifyEmailRequest(token=result.delivery.token))
    session.refresh(user)
    assert user.status == UserStatus.ACTIVE and user.email_verified_at is not None
    expect_error(400, lambda: service.verify_email(VerifyEmailRequest(token=result.delivery.token)))
    assert login(service, request).response.expires_in == 900


def test_locked_account_and_wrong_password(identity):
    session, service, register = identity
    request, result = register()
    initial = login(service, request)
    service.set_user_status(result.response.user_id, UserStatus.LOCKED)
    expect_error(401, lambda: login(service, request))
    expect_error(401, lambda: service.refresh(raw(initial)))
    service.set_user_status(result.response.user_id, UserStatus.ACTIVE)
    expect_error(
        401, lambda: service.login(LoginRequest(email=request.email, password="incorrect"))
    )
    expect_error(
        401, lambda: service.login(LoginRequest(email="absent@example.com", password=PASSWORD))
    )
    expect_error(401, lambda: service.refresh(raw(initial)))
    user = session.get(User, result.response.user_id)
    assert user.session_version == 3


def test_pending_account_cannot_be_unlocked_without_verification(identity):
    _, service, register = identity
    _, result = register(active=False)
    expect_error(409, lambda: service.set_user_status(result.response.user_id, UserStatus.ACTIVE))


def test_refresh_rotation_and_replay_persists_family_revocation(identity, engine):
    session, service, register = identity
    request, _ = register()
    original = login(service, request)
    another_family = login(service, request)
    rotated = service.refresh(raw(original))
    assert raw(rotated) != raw(original)
    assert rotated.refresh_expires_at == original.refresh_expires_at
    previous = IdentityRepository(session).get_session_by_refresh_hash(
        hash_refresh_token(raw(original))
    )
    session.refresh(previous)
    assert previous.revoked_at is not None
    family_id = previous.family_id
    expect_error(401, lambda: service.refresh(raw(original)))
    # A separate connection proves revocation survives the failing request's transaction.
    with Session(engine) as independent:
        family = independent.scalars(
            select(AuthSession).where(AuthSession.family_id == family_id)
        ).all()
        assert len(family) == 2 and all(item.revoked_at is not None for item in family)
    expect_error(401, lambda: service.refresh(raw(rotated)))
    assert service.refresh(raw(another_family)).response.access_token


def test_expired_and_unknown_refresh(identity):
    session, service, register = identity
    request, _ = register()
    tokens = login(service, request)
    auth_session = IdentityRepository(session).get_session_by_refresh_hash(
        hash_refresh_token(raw(tokens))
    )
    auth_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    expect_error(401, lambda: service.refresh(raw(tokens)))
    expect_error(401, lambda: service.refresh("unknown-token"))


def test_logout_and_logout_all(identity):
    session, service, register = identity
    request, result = register()
    first, second = login(service, request), login(service, request)
    service.logout(raw(first))
    service.logout(raw(first))
    service.logout("unknown-token")
    expect_error(401, lambda: service.refresh(raw(first)))
    assert service.refresh(raw(second)).response.access_token
    claims = decode_access_token(second.response.access_token)
    service.logout_all(result.response.user_id)
    snapshot = get_current_user_snapshot(session, result.response.user_id)
    assert snapshot.session_version == claims.session_version + 1
    expect_error(401, lambda: service.refresh(raw(second)))


def test_password_reset_revokes_sessions_and_is_single_use(identity):
    session, service, register = identity
    request, result = register()
    tokens = login(service, request)
    assert service.forgot_password(ForgotPasswordRequest(email="absent@example.com")) is None
    delivery = service.forgot_password(ForgotPasswordRequest(email=request.email))
    assert raw(tokens) not in repr(tokens)
    assert delivery.token.get_secret_value() not in repr(delivery)
    expect_error(400, lambda: service.verify_email(VerifyEmailRequest(token=delivery.token)))
    reset = ResetPasswordRequest(
        token=delivery.token, new_password="new test-only password long enough"
    )
    service.reset_password(reset)
    expect_error(400, lambda: service.reset_password(reset))
    expect_error(401, lambda: login(service, request))
    expect_error(401, lambda: service.refresh(raw(tokens)))
    user = session.get(User, result.response.user_id)
    assert user.session_version == 2
    assert service.login(LoginRequest(email=request.email, password=reset.new_password))


@pytest.mark.parametrize("purpose", [TokenPurpose.EMAIL_VERIFICATION, TokenPurpose.PASSWORD_RESET])
def test_one_time_token_expiry(identity, purpose):
    session, service, register = identity
    request, result = register(active=purpose == TokenPurpose.PASSWORD_RESET)
    delivery = (
        result.delivery
        if purpose == TokenPurpose.EMAIL_VERIFICATION
        else (service.forgot_password(ForgotPasswordRequest(email=request.email)))
    )
    token = IdentityRepository(session).get_one_time_token(
        hash_refresh_token(delivery.token.get_secret_value()), purpose
    )
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    if purpose == TokenPurpose.EMAIL_VERIFICATION:
        expect_error(400, lambda: service.verify_email(VerifyEmailRequest(token=delivery.token)))
    else:
        expect_error(
            400,
            lambda: service.reset_password(
                ResetPasswordRequest(token=delivery.token, new_password=PASSWORD)
            ),
        )


def test_new_reset_request_invalidates_older_token(identity):
    _, service, register = identity
    request, _ = register()
    first = service.forgot_password(ForgotPasswordRequest(email=request.email))
    second = service.forgot_password(ForgotPasswordRequest(email=request.email))
    expect_error(
        400,
        lambda: service.reset_password(
            ResetPasswordRequest(token=first.token, new_password=PASSWORD)
        ),
    )
    service.reset_password(ResetPasswordRequest(token=second.token, new_password=PASSWORD))


def test_db_constraints_and_cascade(identity):
    session, service, register = identity
    request, result = register()
    login(service, request)
    session.add(RoleAssignment(user_id=result.response.user_id, role=Role.LECTURER))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    session.execute(delete(User).where(User.id == result.response.user_id))
    session.commit()
    for model in (RoleAssignment, AuthSession, OneTimeToken):
        assert session.scalar(select(model).where(model.user_id == result.response.user_id)) is None


def test_public_lookup_does_not_select_hashes(identity, engine):
    session, _, register = identity
    _, result = register()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        snapshot = get_current_user_snapshot(session, result.response.user_id)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert snapshot.roles == ["LECTURER"]
    assert len(statements) == 1
    assert "password_hash" not in statements[0] and "refresh_hash" not in statements[0]
    assert get_current_user_snapshot(session, uuid4()) is None


def test_refresh_concurrency_revokes_family(identity, engine):
    _, service, register = identity
    request, _ = register()
    tokens = login(service, request)
    barrier = Barrier(2)

    def refresh_once():
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            try:
                return IdentityService(session).refresh(raw(tokens))
            except AppError as exc:
                assert exc.status_code == 401
                return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: refresh_once(), range(2)))
    successes = [outcome for outcome in outcomes if outcome is not None]
    assert len(successes) == 1
    expect_error(401, lambda: service.refresh(raw(successes[0])))


def test_verification_concurrency_consumes_once(identity, engine):
    _, _, register = identity
    _, result = register(active=False)
    barrier = Barrier(2)

    def verify_once():
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            try:
                IdentityService(session).verify_email(
                    VerifyEmailRequest(token=result.delivery.token)
                )
                return 200
            except AppError as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: verify_once(), range(2)))
    assert sorted(outcomes) == [200, 400]


def test_auth_dependency_reads_db_and_revokes_old_access(identity, engine):
    _, service, register = identity
    request, result = register()
    tokens = login(service, request)
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)

    def test_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = test_db

    @app.get("/current")
    def current(user: Annotated[CurrentUser, Depends(get_current_user)]):
        return user

    @app.get("/admin")
    def administrator(user: Annotated[CurrentUser, Depends(require_roles("ADMIN"))]):
        return user

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {tokens.response.access_token}"}
    assert client.get("/current", headers=headers).status_code == 200
    assert client.get("/admin", headers=headers).status_code == 403
    with Session(engine) as session:
        session.add(RoleAssignment(user_id=result.response.user_id, role=Role.ADMIN))
        session.commit()
    assert client.get("/admin", headers=headers).status_code == 200
    service.logout_all(result.response.user_id)
    assert client.get("/current", headers=headers).status_code == 401


def test_registration_concurrency_creates_one_account(identity, engine):
    email = f"concurrent-{uuid4().hex}@example.com"
    barrier = Barrier(2)

    def register_once():
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            try:
                IdentityService(session).register(RegisterRequest(email=email, password=PASSWORD))
                return 201
            except AppError as exc:
                return exc.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: register_once(), range(2)))
        assert sorted(outcomes) == [201, 409]
        with Session(engine) as session:
            users = session.scalars(select(User).where(User.email == email)).all()
            assert len(users) == 1
            assert IdentityRepository(session).get_user_roles(users[0].id) == [Role.STUDENT]
    finally:
        with engine.begin() as connection:
            connection.execute(delete(User).where(User.email == email))


def test_password_reset_concurrency_consumes_once(identity, engine):
    _, service, register = identity
    request, result = register()
    delivery = service.forgot_password(ForgotPasswordRequest(email=request.email))
    barrier = Barrier(2)

    def reset_once():
        with Session(engine, autoflush=False, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            try:
                IdentityService(session).reset_password(
                    ResetPasswordRequest(
                        token=delivery.token, new_password="new test-only password long enough"
                    )
                )
                return 204
            except AppError as exc:
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: reset_once(), range(2)))
    assert sorted(outcomes) == [204, 400]
    with Session(engine) as session:
        assert session.get(User, result.response.user_id).session_version == 2


def test_public_batch_fetch_reads_one_query_without_hashes(identity, engine):
    session, _, register = identity
    _, first = register()
    _, second = register(active=False)
    ids = [first.response.user_id, second.response.user_id]
    session.get(User, ids[0]).display_name = "Student One"
    session.flush()
    queries = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        summaries = public.get_users_summaries(ids + [ids[0], uuid4()], session=session)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert set(summaries) == set(ids)
    assert len(queries) == 1 and "password_hash" not in queries[0]
    assert summaries[ids[0]].display_name == "Student One"
    assert summaries[ids[1]].display_name is None
    assert summaries[ids[1]].status == "PENDING_VERIFICATION"
    assert public.get_users_summaries([], session=session) == {}
    assert public.verify_user_active(ids[0], session=session)
    assert not public.verify_user_active(ids[1], session=session)


def test_public_admin_invitation_and_status_are_authorized_and_audited(
    identity, engine, monkeypatch
):
    session, service, register = identity
    _, actor_result = register()
    actor_id = actor_result.response.user_id
    session.add(RoleAssignment(user_id=actor_id, role=Role.ADMIN))
    session.commit()
    monkeypatch.setattr(
        public, "SessionLocal", lambda: Session(engine, autoflush=False, expire_on_commit=False)
    )
    email = f"invited-{uuid4().hex}@example.com"
    correlation_id = uuid4()
    created_id = None
    try:
        summary, invitation = public.admin_create_user(
            email.upper(), ["LECTURER"], actor_id=actor_id, correlation_id=correlation_id
        )
        created_id = summary.id
        assert isinstance(summary, public.UserSummaryDTO) and isinstance(invitation, SecretStr)
        assert summary.email == email and summary.status == "PENDING_VERIFICATION"
        assert public.get_user_summary(created_id).model_dump() == summary.model_dump()
        assert public.get_user_roles(created_id) == ["LECTURER"]
        assert not public.check_user_is_lecturer(created_id)
        expect_error(401, lambda: service.login(LoginRequest(email=email, password=PASSWORD)))
        expect_error(400, lambda: service.verify_email(VerifyEmailRequest(token=invitation)))
        service.reset_password(ResetPasswordRequest(token=invitation, new_password=PASSWORD))
        tokens = service.login(LoginRequest(email=email, password=PASSWORD))
        assert public.check_user_is_lecturer(created_id)
        expect_error(
            400,
            lambda: service.reset_password(
                ResetPasswordRequest(token=invitation, new_password=PASSWORD)
            ),
        )
        public.admin_set_user_status(
            created_id, "LOCKED", actor_id=actor_id, correlation_id=uuid4()
        )
        assert not public.verify_user_active(created_id) and not public.check_user_is_lecturer(
            created_id
        )
        expect_error(401, lambda: service.refresh(raw(tokens)))
        public.admin_set_user_status(
            created_id, "ACTIVE", actor_id=actor_id, correlation_id=uuid4()
        )
        assert public.verify_user_active(created_id)
        expect_error(401, lambda: service.refresh(raw(tokens)))
        with Session(engine) as independent:
            audits = independent.scalars(
                select(AuditEvent).where(AuditEvent.target_id == created_id)
            ).all()
            assert len(audits) == 3
            assert {item.action for item in audits} == {
                "ADMIN_CREATE_USER",
                "ADMIN_SET_USER_STATUS",
            }
            assert invitation.get_secret_value() not in str([item.metadata_json for item in audits])
            assert all(item.actor_id == actor_id for item in audits)
        expect_error(
            409,
            lambda: public.admin_create_user(
                email, ["LECTURER"], actor_id=actor_id, correlation_id=uuid4()
            ),
        )
    finally:
        with engine.begin() as connection:
            connection.execute(delete(AuditEvent).where(AuditEvent.actor_id == actor_id))
            if created_id is not None:
                connection.execute(delete(User).where(User.id == created_id))


def test_public_admin_permission_rollback_and_invitation_expiry(identity, engine):
    session, service, register = identity
    _, actor_result = register()
    actor_id = actor_result.response.user_id
    _, target_result = register()
    target_id = target_result.response.user_id
    correlation_id = uuid4()
    email = f"uncommitted-{uuid4().hex}@example.com"
    expect_error(
        403,
        lambda: public.admin_create_user(
            email, ["ADMIN"], actor_id=actor_id, correlation_id=correlation_id, session=session
        ),
    )
    expect_error(
        403,
        lambda: public.admin_set_user_status(
            target_id, "LOCKED", actor_id=uuid4(), correlation_id=correlation_id, session=session
        ),
    )
    session.add(RoleAssignment(user_id=actor_id, role=Role.ADMIN))
    session.commit()
    summary, invitation = public.admin_create_user(
        email, ["LECTURER"], actor_id=actor_id, correlation_id=correlation_id, session=session
    )
    with Session(engine) as independent:
        assert independent.get(User, summary.id) is None
    session.rollback()
    assert public.get_user_summary(summary.id, session=session) is None
    assert (
        session.scalar(select(AuditEvent).where(AuditEvent.correlation_id == correlation_id))
        is None
    )
    expect_error(
        404,
        lambda: public.admin_set_user_status(
            uuid4(), "LOCKED", actor_id=actor_id, correlation_id=uuid4(), session=session
        ),
    )
    _, pending_result = register(active=False)
    expect_error(
        409,
        lambda: public.admin_set_user_status(
            pending_result.response.user_id,
            "ACTIVE",
            actor_id=actor_id,
            correlation_id=uuid4(),
            session=session,
        ),
    )
    # Invitation acceptance respects expiry and does not unlock a blocked invited account.
    created_id = None
    try:
        summary, invitation = public.admin_create_user(
            email, ["LECTURER"], actor_id=actor_id, correlation_id=uuid4(), session=session
        )
        created_id = summary.id
        token = IdentityRepository(session).get_one_time_token(
            hash_refresh_token(invitation.get_secret_value()), TokenPurpose.ADMIN_INVITATION
        )
        token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        expect_error(
            400,
            lambda: service.reset_password(
                ResetPasswordRequest(token=invitation, new_password=PASSWORD)
            ),
        )
        token = IdentityRepository(session).get_one_time_token(
            hash_refresh_token(invitation.get_secret_value()), TokenPurpose.ADMIN_INVITATION
        )
        token.expires_at = datetime.now(UTC) + timedelta(hours=1)
        service.set_user_status(created_id, UserStatus.LOCKED)
        expect_error(
            400,
            lambda: service.reset_password(
                ResetPasswordRequest(token=invitation, new_password=PASSWORD)
            ),
        )
        service.set_user_status(actor_id, UserStatus.LOCKED)
        expect_error(
            403,
            lambda: public.admin_set_user_status(
                target_id, "LOCKED", actor_id=actor_id, correlation_id=uuid4(), session=session
            ),
        )
    finally:
        session.rollback()
        with engine.begin() as connection:
            connection.execute(delete(AuditEvent).where(AuditEvent.actor_id == actor_id))
            if created_id is not None:
                connection.execute(delete(User).where(User.id == created_id))


def test_admin_school_boundary_and_creation_context(identity):
    session, _, register = identity
    _, actor = register()
    _, target = register()
    actor_id, target_id = actor.response.user_id, target.response.user_id
    school_id = uuid4()
    session.get(User, actor_id).school_id = school_id
    session.get(User, target_id).school_id = None
    session.add(RoleAssignment(user_id=actor_id, role=Role.ADMIN))
    session.commit()
    # Missing context and another school are both concealed, even for a valid Admin.
    expect_error(
        404,
        lambda: public.admin_set_user_status(
            target_id, "LOCKED", actor_id=actor_id, correlation_id=uuid4(), session=session
        ),
    )
    session.get(User, target_id).school_id = uuid4()
    session.commit()
    expect_error(
        404,
        lambda: public.admin_set_user_status(
            target_id, "LOCKED", actor_id=actor_id, correlation_id=uuid4(), session=session
        ),
    )
    assert session.get(User, target_id).status == UserStatus.ACTIVE

    session.get(User, target_id).school_id = school_id
    session.flush()
    public.admin_set_user_status(
        target_id, "LOCKED", actor_id=actor_id, correlation_id=uuid4(), session=session
    )
    assert session.get(User, target_id).status == UserStatus.LOCKED
    summary, _ = public.admin_create_user(
        f"school-{uuid4().hex}@example.com",
        ["LECTURER"],
        actor_id=actor_id,
        correlation_id=uuid4(),
        session=session,
    )
    assert summary.school_id == school_id
    # The caller owns these mutations; rollback removes the account and audit together.
    session.rollback()
    assert session.get(User, summary.id) is None
    assert session.get(User, target_id).status == UserStatus.ACTIVE


@pytest.fixture
def student(identity, engine):
    session, service, register = identity
    _, actor = register()
    actor_id = actor.response.user_id
    session.add(RoleAssignment(user_id=actor_id, role=Role.ADMIN))
    session.commit()
    result = public.admin_create_student(
        "student." + uuid4().hex, actor_id=actor_id, correlation_id=uuid4(), session=session
    )
    session.commit()
    yield session, service, actor_id, result
    session.rollback()
    with engine.begin() as connection:
        connection.execute(delete(AuditEvent).where(AuditEvent.target_id == result.student.id))
        connection.execute(delete(User).where(User.id == result.student.id))


def activation(result):
    return ActivateStudentRequest(
        username=result.student.username, activation_code=result.code, new_password=PASSWORD
    )


def test_student_activation_expiry_purpose_reissue_and_config(student, monkeypatch):
    session, service, actor_id, result = student
    token = IdentityRepository(session).get_one_time_token(
        hash_refresh_token(result.code.get_secret_value()), TokenPurpose.STUDENT_ACTIVATION
    )
    assert result.code.get_secret_value() != token.token_hash
    assert 23 * 3600 < (result.expires_at - datetime.now(UTC)).total_seconds() <= 24 * 3600
    expect_error(
        400,
        lambda: service.reset_password(
            ResetPasswordRequest(token=result.code, new_password=PASSWORD)
        ),
    )
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    expect_error(400, lambda: service.activate_student(activation(result), correlation_id=uuid4()))
    monkeypatch.setattr(settings, "student_activation_expire_hours", 2)
    new = public.admin_issue_student_code(
        result.student.id, actor_id=actor_id, correlation_id=uuid4(), session=session
    )
    session.commit()
    assert 7100 < (new.expires_at - datetime.now(UTC)).total_seconds() <= 7200
    expect_error(400, lambda: service.activate_student(activation(result), correlation_id=uuid4()))
    service.activate_student(activation(new), correlation_id=uuid4())
    assert service.login(LoginRequest(username=result.student.username, password=PASSWORD))
    assert service.forgot_password(ForgotPasswordRequest(email="absent@example.com")) is None


def test_student_activation_concurrency_consumes_once(student, engine):
    session, _, _, result = student
    barrier = Barrier(2)

    def run():
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            try:
                IdentityService(db).activate_student(activation(result), correlation_id=uuid4())
                return 204
            except AppError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: run(), range(2))) == [204, 400]
    session.expire_all()
    user = session.get(User, result.student.id)
    assert user.email_verified_at is None and user.activated_at is not None
    assert user.session_version == 2


def test_student_username_assignment_preserves_identity_and_invalidates_email_tokens(identity):
    session, service, register = identity
    request, legacy = register()
    _, actor = register()
    user = session.get(User, legacy.response.user_id)
    before_hash = user.password_hash
    tokens = login(service, request)
    old_reset = service.forgot_password(ForgotPasswordRequest(email=request.email))
    # Model an existing Student: only the privileged migration helper may assign username.
    assignment = session.scalar(select(RoleAssignment).where(RoleAssignment.user_id == user.id))
    assignment.role = Role.STUDENT
    session.add(RoleAssignment(user_id=actor.response.user_id, role=Role.ADMIN))
    session.commit()
    expect_error(401, lambda: login(service, request))
    expect_error(401, lambda: service.refresh(raw(tokens)))
    assert service.forgot_password(ForgotPasswordRequest(email=request.email)) is None
    expect_error(
        400,
        lambda: service.reset_password(
            ResetPasswordRequest(token=old_reset.token, new_password=PASSWORD)
        ),
    )
    username = "legacy." + uuid4().hex
    converted = public.admin_assign_student_username(
        user.id,
        username.upper(),
        actor_id=actor.response.user_id,
        correlation_id=uuid4(),
        session=session,
    )
    assert converted.id == user.id and converted.email == request.email
    assert user.password_hash == before_hash and user.activated_at is not None
    assert converted.username == username
    session.commit()
    assert service.login(LoginRequest(username=username, password=PASSWORD))
    expect_error(401, lambda: login(service, request))
    expect_error(
        401, lambda: service.validate_cached_refresh(raw(tokens), tokens.response.access_token)
    )
    session.execute(delete(AuditEvent).where(AuditEvent.target_id == user.id))
    session.commit()


def test_student_public_creation_rolls_back_and_requires_admin_scope(identity):
    session, _, register = identity
    _, actor = register()
    actor_id = actor.response.user_id
    expect_error(
        403,
        lambda: public.admin_create_student(
            "student." + uuid4().hex, actor_id=actor_id, correlation_id=uuid4(), session=session
        ),
    )
    session.add(RoleAssignment(user_id=actor_id, role=Role.ADMIN))
    session.get(User, actor_id).school_id = None
    session.commit()
    expect_error(
        404,
        lambda: public.admin_create_student(
            "student." + uuid4().hex, actor_id=actor_id, correlation_id=uuid4(), session=session
        ),
    )
    session.get(User, actor_id).school_id = uuid4()
    session.flush()
    result = public.admin_create_student(
        "student." + uuid4().hex, actor_id=actor_id, correlation_id=uuid4(), session=session
    )
    assert session.get(User, result.student.id) is not None
    session.rollback()
    assert session.get(User, result.student.id) is None


def test_student_provisioning_concurrency_does_not_duplicate_username(student, engine):
    _, _, actor_id, _ = student
    username = "concurrent.student." + uuid4().hex
    barrier = Barrier(2)

    def create():
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            try:
                public.admin_create_student(
                    username, actor_id=actor_id, correlation_id=uuid4(), session=db
                )
                db.commit()
                return 201
            except AppError as error:
                db.rollback()
                return error.status_code

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(lambda _: create(), range(2))) == [201, 409]
        with Session(engine) as db:
            users = db.scalars(select(User).where(User.username == username)).all()
            assert len(users) == 1 and users[0].email is None
    finally:
        with engine.begin() as connection:
            ids = select(User.id).where(User.username == username)
            connection.execute(delete(AuditEvent).where(AuditEvent.target_id.in_(ids)))
            connection.execute(delete(User).where(User.username == username))


def test_student_recovery_expiry_and_concurrency(student, engine):
    session, service, actor_id, result = student
    service.activate_student(activation(result), correlation_id=uuid4())
    first = public.admin_issue_student_code(
        result.student.id,
        actor_id=actor_id,
        correlation_id=uuid4(),
        identity_verified=True,
        session=session,
    )
    token = IdentityRepository(session).get_one_time_token(
        hash_refresh_token(first.code.get_secret_value()), TokenPurpose.STUDENT_PASSWORD_RESET
    )
    token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    session.commit()
    expect_error(
        400,
        lambda: service.reset_password(
            ResetPasswordRequest(token=first.code, new_password=PASSWORD)
        ),
    )
    second = public.admin_issue_student_code(
        result.student.id,
        actor_id=actor_id,
        correlation_id=uuid4(),
        identity_verified=True,
        session=session,
    )
    session.commit()
    version_before = session.get(User, result.student.id).session_version
    barrier = Barrier(2)

    def reset():
        with Session(engine, autoflush=False, expire_on_commit=False) as db:
            barrier.wait(timeout=10)
            try:
                IdentityService(db).reset_password(
                    ResetPasswordRequest(token=second.code, new_password=PASSWORD)
                )
                return 204
            except AppError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: reset(), range(2))) == [204, 400]
    session.expire_all()
    assert session.get(User, result.student.id).session_version == version_before + 1
    audits = session.scalars(
        select(AuditEvent).where(
            AuditEvent.target_id == result.student.id, AuditEvent.action == "STUDENT_PASSWORD_RESET"
        )
    ).all()
    assert len(audits) == 1
