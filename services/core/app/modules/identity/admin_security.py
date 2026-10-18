"""Serialize changes that could remove the last usable system administrator."""

from uuid import UUID

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus

ADMIN_CHANGE_LOCK = 7338401301


def lock_admin_changes(session: Session) -> None:
    # Take this BEFORE user locks, consistently for status and role mutations.
    session.execute(select(func.pg_advisory_xact_lock(ADMIN_CHANGE_LOCK)))


def ensure_other_admin(session: Session, user_id: UUID) -> None:
    other = session.scalar(
        select(
            exists().where(
                RoleAssignment.user_id == User.id,
                RoleAssignment.role == Role.ADMIN,
                User.id != user_id,
                User.status == UserStatus.ACTIVE,
                User.school_id.is_not(None),
                User.email_verified_at.is_not(None),
            )
        )
    )
    if not other:
        raise AppError(400, "Cannot remove or lock the last active administrator")
