from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock
from uuid import uuid4

import pytest
from pydantic import SecretStr, ValidationError
from sqlalchemy.orm import Session

from app.modules.identity import public


@pytest.fixture
def boundary(monkeypatch):
    db = MagicMock(spec=Session)
    db.__enter__.return_value = db
    repository = Mock()
    service = Mock()
    monkeypatch.setattr(public, "SessionLocal", lambda: db)
    monkeypatch.setattr(public, "_IdentityRepository", lambda session: repository)
    monkeypatch.setattr(public, "_IdentityService", lambda session: service)
    return db, repository, service


def test_summary_batch_and_roles_only_use_public_dtos(boundary):
    db, repository, _ = boundary
    user_id = uuid4()
    dto = public.UserSummaryDTO(id=user_id, email="student@example.com", status="ACTIVE")
    repository.get_users_summaries.return_value = {user_id: dto}
    assert public.get_user_summary(user_id) == dto
    assert public.get_user_summary(user_id, session=db) == dto
    assert public.get_users_summaries([user_id, user_id], session=db) == {user_id: dto}
    assert public.verify_user_active(user_id)
    assert set(dto.model_dump()) == {
        "id",
        "email",
        "username",
        "school_id",
        "display_name",
        "status",
    }
    repository.get_users_summaries.return_value = {}
    assert public.get_user_summary(uuid4()) is None
    assert not public.verify_user_active(uuid4(), session=db)
    repository.get_users_summaries.return_value = {
        user_id: dto.model_copy(update={"status": "LOCKED"})
    }
    assert not public.verify_user_active(user_id, session=db)
    repository.get_user_roles.return_value = ["LECTURER", "STUDENT"]
    assert public.get_user_roles(user_id, session=db) == ["LECTURER", "STUDENT"]
    repository.get_user_roles.return_value = []
    assert public.get_user_roles(uuid4()) == []
    assert not hasattr(public, "User") and not hasattr(public, "IdentityRepository")


def test_student_summary_without_email_preserves_school(boundary):
    _, repository, _ = boundary
    user_id, school_id = uuid4(), uuid4()
    dto = public.UserSummaryDTO(
        id=user_id,
        email=None,
        username="student.test",
        school_id=school_id,
        display_name="Học sinh kiểm thử",
        status="ACTIVE",
    )
    repository.get_users_summaries.return_value = {user_id: dto}
    assert public.get_user_summary(user_id) == dto
    assert dto.model_dump()["email"] is None
    assert dto.display_name == "Học sinh kiểm thử"
    assert "hash" not in dto.model_dump()


@pytest.mark.parametrize(
    "status,role,expected",
    [
        ("ACTIVE", "LECTURER", True),
        ("ACTIVE", "STUDENT", False),
        ("LOCKED", "LECTURER", False),
        ("PENDING_VERIFICATION", "LECTURER", False),
        ("ACTIVE", None, False),
    ],
)
def test_snapshot_lecturer_and_dependency_lookup(boundary, status, role, expected):
    db, _, _ = boundary
    user_id = uuid4()
    row = SimpleNamespace(
        id=user_id,
        status=status,
        session_version=1,
        school_id=uuid4(),
        role=SimpleNamespace(value=role) if role else None,
    )
    db.execute.return_value.all.return_value = [row]
    snapshot = public.get_current_user_snapshot(db, user_id)
    assert snapshot.school_id == row.school_id
    assert snapshot.roles == ([role] if role else [])
    assert public.get_identity_user_lookup(db)(user_id) == snapshot
    assert public.check_user_is_lecturer(user_id, session=db) is expected
    db.execute.return_value.all.return_value = []
    assert public.get_current_user_snapshot(db, uuid4()) is None
    assert not public.check_user_is_lecturer(uuid4())


@pytest.mark.parametrize("owned", [True, False])
def test_admin_interfaces_delegate_and_respect_transaction_ownership(boundary, owned):
    db, _, service = boundary
    actor_id, target_id, correlation_id = uuid4(), uuid4(), uuid4()
    dto = public.UserSummaryDTO(
        id=target_id, email="lecturer@example.com", status="PENDING_VERIFICATION"
    )
    invitation = SecretStr("test-only-invitation")
    service.admin_create_user.return_value = dto, invitation
    arguments = {} if owned else {"session": db}
    result = public.admin_create_user(
        "LECTURER@EXAMPLE.COM",
        ["LECTURER"],
        actor_id=actor_id,
        correlation_id=correlation_id,
        **arguments,
    )
    assert result == (dto, invitation)
    assert invitation.get_secret_value() not in repr(result)
    request = service.admin_create_user.call_args.args[0]
    assert request.email == "lecturer@example.com" and request.roles == ["LECTURER"]
    public.admin_set_user_status(
        target_id, "LOCKED", actor_id=actor_id, correlation_id=correlation_id, **arguments
    )
    service.admin_set_user_status.assert_called_once_with(
        target_id, "LOCKED", actor_id=actor_id, correlation_id=correlation_id
    )
    assert db.commit.call_count == (2 if owned else 0)
    db.rollback.assert_not_called()


def test_public_errors_propagate_without_fail_open(boundary):
    db, repository, service = boundary
    repository.get_users_summaries.side_effect = RuntimeError("DB unavailable")
    with pytest.raises(RuntimeError):
        public.verify_user_active(uuid4())
    service.admin_create_user.side_effect = RuntimeError("DB unavailable")
    with pytest.raises(RuntimeError):
        public.admin_create_user(
            "user@example.com", ["LECTURER"], actor_id=uuid4(), correlation_id=uuid4()
        )
    db.rollback.assert_called_once()


def test_admin_reason_codes_forward_to_owner_without_new_transaction(boundary):
    db, _, service = boundary
    actor_id, user_id, correlation_id = uuid4(), uuid4(), uuid4()
    public.admin_create_user(
        "staff@example.com",
        ["LECTURER"],
        actor_id=actor_id,
        correlation_id=correlation_id,
        reason_code="USER_REQUEST",
        session=db,
    )
    assert service.admin_create_user.call_args.kwargs["reason_code"] == "USER_REQUEST"
    public.admin_set_user_status(
        user_id,
        "LOCKED",
        actor_id=actor_id,
        correlation_id=correlation_id,
        reason_code="POLICY_VIOLATION",
        session=db,
    )
    assert service.admin_set_user_status.call_args.kwargs["reason_code"] == "POLICY_VIOLATION"
    db.commit.assert_not_called()


@pytest.mark.parametrize("owned", [True, False])
def test_student_public_helpers_keep_secrets_internal_and_share_transactions(boundary, owned):
    db, _, service = boundary
    user_id, actor_id, correlation_id = uuid4(), uuid4(), uuid4()
    summary = public.UserSummaryDTO(id=user_id, username="student", email=None, status="ACTIVE")
    code = public.StudentCode(
        summary, "ACTIVATION", SecretStr("test-only-secret"), datetime.now(UTC)
    )
    service.admin_create_student.return_value = code
    service.admin_assign_student_username.return_value = summary
    service.admin_issue_student_code.return_value = code
    arguments = {} if owned else {"session": db}
    assert (
        public.admin_create_student(
            " STUDENT ", actor_id=actor_id, correlation_id=correlation_id, **arguments
        )
        is code
    )
    assert service.admin_create_student.call_args.args[0].username == "student"
    assert (
        public.admin_assign_student_username(
            user_id, " STUDENT ", actor_id=actor_id, correlation_id=correlation_id, **arguments
        )
        is summary
    )
    assert service.admin_assign_student_username.call_args.args[1].username == "student"
    assert (
        public.admin_issue_student_code(
            user_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            identity_verified=True,
            **arguments,
        )
        is code
    )
    assert service.admin_issue_student_code.call_args.kwargs["identity_verified"] is True
    assert db.commit.call_count == (3 if owned else 0)
    assert "test-only-secret" not in repr(code)


@pytest.mark.parametrize("roles", [[], ["UNKNOWN"], ["ADMIN", "ADMIN"], ["STUDENT"]])
def test_public_create_rejects_invalid_roles(boundary, roles):
    with pytest.raises(ValidationError):
        public.admin_create_user(
            "user@example.com", roles, actor_id=uuid4(), correlation_id=uuid4()
        )
    with pytest.raises(ValidationError):
        public.admin_set_user_status(
            uuid4(), "PENDING_VERIFICATION", actor_id=uuid4(), correlation_id=uuid4()
        )
