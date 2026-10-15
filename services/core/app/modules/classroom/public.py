"""Stable Python interface for other Core modules (social, notification, administration).

Consumers import only from here — never classroom.models or classroom.repository.
All functions accept an existing Session so callers share their transaction, or
open a short read-only session themselves when called outside a request.
"""

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.db import SessionLocal
from app.modules.classroom.models import ClassRole
from app.modules.classroom.schemas import MembershipResponse

__all__ = [
    "MembershipDTO",
    "check_user_in_class",
    "get_class_lecturer_ids",
    "get_class_status",
    "is_active_member",
    "is_class_lecturer",
]

MembershipDTO = MembershipResponse


@contextmanager
def _session_scope(session: Session | None) -> Iterator[Session]:
    with SessionLocal() if session is None else nullcontext(session) as db:
        yield db


def _repo(session: Session):
    from app.modules.classroom.repository import ClassroomRepository

    return ClassroomRepository(session)


def check_user_in_class(
    class_id: UUID, user_id: UUID, *, session: Session | None = None
) -> MembershipDTO | None:
    """The user's ACTIVE membership, or None when absent/left/removed."""
    with _session_scope(session) as db:
        membership = _repo(db).get_active_membership(class_id, user_id)
        return MembershipResponse.model_validate(membership) if membership else None


def is_active_member(class_id: UUID, user_id: UUID, *, session: Session | None = None) -> bool:
    return check_user_in_class(class_id, user_id, session=session) is not None


def is_class_lecturer(class_id: UUID, user_id: UUID, *, session: Session | None = None) -> bool:
    """True for OWNER or CO_LECTURER with an ACTIVE membership."""
    membership = check_user_in_class(class_id, user_id, session=session)
    return membership is not None and membership.class_role in {
        ClassRole.OWNER,
        ClassRole.CO_LECTURER,
    }


def get_class_status(class_id: UUID, *, session: Session | None = None) -> str | None:
    with _session_scope(session) as db:
        klass = _repo(db).get_class_by_id(class_id)
        return klass.status.value if klass else None


def get_class_lecturer_ids(class_id: UUID, *, session: Session | None = None) -> list[UUID]:
    with _session_scope(session) as db:
        return [member.user_id for member in _repo(db).list_class_lecturers(class_id)]
