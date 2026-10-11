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
    assert set(dto.model_dump()) == {"id", "email", "status"}
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
        role=SimpleNamespace(value=role) if role else None,
    )
    db.execute.return_value.all.return_value = [row]
    snapshot = public.get_current_user_snapshot(db, user_id)
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
            "user@example.com", ["STUDENT"], actor_id=uuid4(), correlation_id=uuid4()
        )
    db.rollback.assert_called_once()


@pytest.mark.parametrize("roles", [[], ["UNKNOWN"], ["ADMIN", "ADMIN"]])
def test_public_create_rejects_invalid_roles(boundary, roles):
    with pytest.raises(ValidationError):
        public.admin_create_user(
            "user@example.com", roles, actor_id=uuid4(), correlation_id=uuid4()
        )
    with pytest.raises(ValidationError):
        public.admin_set_user_status(
            uuid4(), "PENDING_VERIFICATION", actor_id=uuid4(), correlation_id=uuid4()
        )
