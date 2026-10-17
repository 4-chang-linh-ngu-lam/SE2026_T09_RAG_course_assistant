"""Action-based Classroom boundary for Core modules and the internal API."""

from contextlib import nullcontext
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.db import SessionLocal
from app.common.errors import AppError
from app.modules.classroom.models import ClassStatus
from app.modules.classroom.repository import ClassroomRepository
from app.modules.classroom.schemas import ClassAccessAction, ClassAccessDTO
from app.modules.identity.public import get_user_roles, get_user_summary

__all__ = ["ClassAccessAction", "ClassAccessDTO", "check_class_action", "get_class_lecturer_ids"]


def check_class_action(
    class_id: UUID,
    user_id: UUID,
    action: ClassAccessAction | str,
    *,
    session: Session | None = None,
) -> ClassAccessDTO:
    try:
        action = ClassAccessAction(action)
    except ValueError as exc:
        raise AppError(400, "Unknown class action") from exc

    with SessionLocal() if session is None else nullcontext(session) as db:
        denied = ClassAccessDTO(allowed=False, class_id=class_id)
        user = get_user_summary(user_id, session=db)
        if user is None or user.status != "ACTIVE" or user.school_id is None:
            return denied
        repository = ClassroomRepository(db)
        klass = repository.get_class(class_id)
        if klass is None or klass.school_id != user.school_id:
            return denied

        roles = set(get_user_roles(user_id, session=db))
        member = repository.active_membership(class_id, user_id)
        assignment = repository.active_teacher(class_id, user_id)
        current_student = member is not None and "STUDENT" in roles
        current_teacher = assignment is not None and "LECTURER" in roles
        is_admin = "ADMIN" in roles
        active_class = klass.status == ClassStatus.ACTIVE

        if action == ClassAccessAction.READ_CLASS_CONTENT:
            allowed = current_student or current_teacher
        elif action == ClassAccessAction.PARTICIPATE_CURRENT_CLASS:
            allowed = active_class and (current_student or current_teacher)
        elif action == ClassAccessAction.MODERATE_CLASS_CONTENT:
            allowed = active_class and (current_teacher or is_admin)
        elif action == ClassAccessAction.MANAGE_CLASS_CALENDAR:
            allowed = active_class and current_teacher
        elif action == ClassAccessAction.READ_OWN_HISTORY:
            allowed = "STUDENT" in roles and repository.has_membership_history(class_id, user_id)
        elif action == ClassAccessAction.READ_DOCUMENT_SOURCE:
            allowed = current_student or current_teacher
        elif action == ClassAccessAction.USE_AI_TUTOR:
            allowed = active_class and current_student
        else:  # GRADE_SUBMITTED_WORK; Learning checks the assigned submission separately.
            allowed = active_class and current_teacher

        if not allowed:
            return denied
        return ClassAccessDTO(
            allowed=True,
            class_id=class_id,
            school_id=klass.school_id,
            class_status=klass.status,
            teaching_role=assignment.role if current_teacher else None,
        )


def get_class_lecturer_ids(class_id: UUID, *, session: Session | None = None) -> list[UUID]:
    with SessionLocal() if session is None else nullcontext(session) as db:
        return [
            assignment.lecturer_id
            for assignment in ClassroomRepository(db).active_teachers(class_id)
        ]
