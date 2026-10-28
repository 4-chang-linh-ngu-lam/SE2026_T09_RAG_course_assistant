from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, UserLookup
from app.common.db import SessionLocal, get_db, transaction
from app.modules.identity.admin_public import (
    admin_actor,
    admin_check_student_import,
    admin_get_data_request,
    admin_list_data_requests,
    admin_list_users,
    admin_resolve_data_request,
    admin_update_account,
    admin_update_user_roles,
)
from app.modules.identity.admin_schemas import (
    AdminReason,
    AdminUserListItem,
    AdminUserUpdateCommand,
    DataResolutionCommand,
    ResolutionNote,
    RoleUpdateCommand,
    StudentImportCheck,
    StudentImportRow,
)
from app.modules.identity.email_delivery import get_token_sender
from app.modules.identity.idempotency import Mutation, get_mutation
from app.modules.identity.maintenance import (
    bootstrap_dev_identity,
    maintenance_assign_school,
    maintenance_identity_report,
)
from app.modules.identity.models import RoleAssignment as _RoleAssignment
from app.modules.identity.models import User as _User
from app.modules.identity.models import UserStatus as _UserStatus
from app.modules.identity.repository import IdentityRepository as _IdentityRepository
from app.modules.identity.schemas import AdminCreateStudentRequest as _AdminCreateStudentRequest
from app.modules.identity.schemas import AdminCreateUserRequest as _AdminCreateUserRequest
from app.modules.identity.schemas import AdminSetStatusRequest as _AdminSetStatusRequest
from app.modules.identity.schemas import (
    AssignStudentUsernameRequest as _AssignStudentUsernameRequest,
)
from app.modules.identity.schemas import DataRequestResponse, UserSummaryDTO
from app.modules.identity.service import IdentityService as _IdentityService
from app.modules.identity.service import StudentCode, TokenDelivery

__all__ = [
    "AdminReason",
    "AdminUserListItem",
    "AdminUserUpdateCommand",
    "DataRequestResponse",
    "DataResolutionCommand",
    "Mutation",
    "ResolutionNote",
    "RoleUpdateCommand",
    "StudentCode",
    "StudentImportCheck",
    "StudentImportRow",
    "TokenDelivery",
    "UserSummaryDTO",
    "admin_actor",
    "admin_assign_student_username",
    "admin_check_student_import",
    "admin_create_student",
    "admin_create_user",
    "admin_get_data_request",
    "admin_issue_student_code",
    "admin_list_data_requests",
    "admin_list_users",
    "admin_reissue_user_invitation",
    "admin_resolve_data_request",
    "admin_set_user_status",
    "admin_update_account",
    "admin_update_user_roles",
    "attempt_token_delivery",
    "bootstrap_dev_identity",
    "check_user_is_lecturer",
    "get_current_user_snapshot",
    "get_identity_user_lookup",
    "get_mutation",
    "get_token_sender",
    "get_user_roles",
    "get_user_summary",
    "get_users_summaries",
    "maintenance_assign_school",
    "maintenance_identity_report",
    "verify_user_active",
]


@contextmanager
def _session_scope(session: Session | None, *, write: bool = False) -> Iterator[Session]:
    with (
        SessionLocal() if session is None else nullcontext(session) as db,
        transaction(db) if write and session is None else nullcontext(db),
    ):
        yield db


def get_user_summary(user_id: UUID, *, session: Session | None = None) -> UserSummaryDTO | None:
    with _session_scope(session) as db:
        return _IdentityRepository(db).get_users_summaries([user_id]).get(user_id)


def get_users_summaries(
    user_ids: list[UUID], *, session: Session | None = None
) -> dict[UUID, UserSummaryDTO]:
    with _session_scope(session) as db:
        return _IdentityRepository(db).get_users_summaries(user_ids)


def verify_user_active(user_id: UUID, *, session: Session | None = None) -> bool:
    user = get_user_summary(user_id, session=session)
    return user is not None and user.status == "ACTIVE"


def get_user_roles(user_id: UUID, *, session: Session | None = None) -> list[str]:
    with _session_scope(session) as db:
        return [str(role) for role in _IdentityRepository(db).get_user_roles(user_id)]


def check_user_is_lecturer(user_id: UUID, *, session: Session | None = None) -> bool:
    with _session_scope(session) as db:
        user = get_current_user_snapshot(db, user_id)
        return user is not None and user.status == "ACTIVE" and "LECTURER" in user.roles


def admin_create_user(
    email: str,
    roles: list[str],
    *,
    actor_id: UUID,
    correlation_id: UUID,
    display_name: str | None = None,
    session: Session | None = None,
    reason_code: str | None = None,
) -> tuple[UserSummaryDTO, TokenDelivery]:
    request = _AdminCreateUserRequest(email=email, roles=roles, display_name=display_name)
    with _session_scope(session, write=True) as db:
        return _IdentityService(db).admin_create_user(
            request,
            actor_id=actor_id,
            correlation_id=correlation_id,
            **({"reason_code": reason_code} if reason_code is not None else {}),
        )


def admin_reissue_user_invitation(
    user_id: UUID,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    session: Session | None = None,
    reason_code: str | None = None,
) -> tuple[UserSummaryDTO, TokenDelivery]:
    with _session_scope(session, write=True) as db:
        return _IdentityService(db).admin_reissue_user_invitation(
            user_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            **({"reason_code": reason_code} if reason_code is not None else {}),
        )


def attempt_token_delivery(
    token_id: UUID,
    deliver: Callable[[TokenDelivery], None],
    *,
    session: Session | None = None,
) -> str:
    with _session_scope(session) as db:
        return _IdentityService(db).attempt_token_delivery(token_id, deliver)


def admin_set_user_status(
    user_id: UUID,
    status: str,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    session: Session | None = None,
    reason_code: str | None = None,
) -> None:
    request = _AdminSetStatusRequest(status=status)
    with _session_scope(session, write=True) as db:
        _IdentityService(db).admin_set_user_status(
            user_id,
            _UserStatus(request.status),
            actor_id=actor_id,
            correlation_id=correlation_id,
            **({"reason_code": reason_code} if reason_code is not None else {}),
        )


def admin_create_student(
    username: str,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    display_name: str | None = None,
    session: Session | None = None,
) -> StudentCode:
    request = _AdminCreateStudentRequest(username=username, display_name=display_name)
    with _session_scope(session, write=True) as db:
        return _IdentityService(db).admin_create_student(
            request, actor_id=actor_id, correlation_id=correlation_id
        )


def admin_assign_student_username(
    user_id: UUID,
    username: str,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    session: Session | None = None,
) -> UserSummaryDTO:
    request = _AssignStudentUsernameRequest(username=username)
    with _session_scope(session, write=True) as db:
        return _IdentityService(db).admin_assign_student_username(
            user_id, request, actor_id=actor_id, correlation_id=correlation_id
        )


def admin_issue_student_code(
    user_id: UUID,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    identity_verified: bool = False,
    session: Session | None = None,
) -> StudentCode:
    with _session_scope(session, write=True) as db:
        return _IdentityService(db).admin_issue_student_code(
            user_id,
            actor_id=actor_id,
            correlation_id=correlation_id,
            identity_verified=identity_verified,
        )


def get_current_user_snapshot(session: Session, user_id: UUID) -> CurrentUser | None:
    """Read only non-secret fields, in one statement with current role assignments."""
    rows = session.execute(
        select(_User.id, _User.status, _User.session_version, _User.school_id, _RoleAssignment.role)
        .outerjoin(_RoleAssignment, _RoleAssignment.user_id == _User.id)
        .where(_User.id == user_id)
    ).all()
    if not rows:
        return None
    first = rows[0]
    return CurrentUser(
        id=first.id,
        status=first.status,
        session_version=first.session_version,
        school_id=first.school_id,
        roles=[row.role.value for row in rows if row.role is not None],
    )


def get_identity_user_lookup(session: Annotated[Session, Depends(get_db)]) -> UserLookup:
    def lookup(user_id: UUID) -> CurrentUser | None:
        return get_current_user_snapshot(session, user_id)

    return lookup
