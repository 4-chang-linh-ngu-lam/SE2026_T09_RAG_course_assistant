"""Action-based Classroom boundary for Core modules and the internal API."""

from contextlib import nullcontext
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.db import SessionLocal
from app.common.errors import AppError
from app.modules.classroom.maintenance import (
    maintenance_provision_schools,
    maintenance_schools,
    maintenance_user_schools,
    seed_dev_classroom,
)
from app.modules.classroom.models import ClassStatus
from app.modules.classroom.repository import ClassroomRepository
from app.modules.classroom.schemas import (
    ClassAccessAction,
    ClassAccessDTO,
    NotificationAudienceDTO,
    RosterImportSnapshot,
)
from app.modules.identity.public import get_user_roles, get_user_summary

__all__ = ["ClassAccessAction", "ClassAccessDTO", "check_class_action", "get_class_lecturer_ids"]
__all__ += ["NotificationAudienceDTO", "get_notification_audience"]
__all__ += ["RosterImportSnapshot", "admin_append_roster", "admin_preview_roster"]
__all__ += ["maintenance_provision_schools", "maintenance_schools", "seed_dev_classroom"]
__all__ += ["maintenance_user_schools"]


def admin_preview_roster(
    homeroom_id: UUID, *, actor_id: UUID, session: Session, lock: bool = False
) -> RosterImportSnapshot:
    from app.modules.classroom.service import ClassroomService
    from app.modules.identity.public import admin_actor

    actor = admin_actor(actor_id, session=session)
    service = ClassroomService(session)
    room = service._homeroom_for_admin(homeroom_id, actor, for_update=lock)
    return RosterImportSnapshot(
        homeroom_class_id=room.id,
        school_id=room.school_id,
        roster_version=room.roster_version,
        student_ids=sorted(row.student_id for row in service.repository.active_roster(room.id)),
    )


def admin_append_roster(
    homeroom_id: UUID,
    student_ids: list[UUID],
    *,
    expected_roster_version: int,
    actor_id: UUID,
    correlation_id: UUID,
    reason_code: str,
    session: Session,
):
    """Append without removing roster members; caller commits the complete import."""
    from app.modules.classroom.service import ClassroomService
    from app.modules.identity.public import admin_actor

    snapshot = admin_preview_roster(homeroom_id, actor_id=actor_id, session=session, lock=True)
    if snapshot.roster_version != expected_roster_version:
        raise AppError(409, "Roster changed; preview the import again")
    actor = admin_actor(actor_id, session=session)
    return ClassroomService(
        session, correlation_id=correlation_id, reason_code=reason_code
    ).set_roster(
        actor,
        homeroom_id,
        sorted(set(snapshot.student_ids) | set(student_ids)),
        expected_roster_version=expected_roster_version,
        commit=False,
    )


def get_notification_audience(
    class_id: UUID, *, session: Session | None = None, homeroom: bool = False
) -> NotificationAudienceDTO | None:
    """Current enrollment/assignment IDs, for transactional notification snapshots.

    Caller owns the transaction. Flush producer changes before taking the snapshot;
    consumers must still check Identity school scope and resource permissions.
    """
    with SessionLocal() if session is None else nullcontext(session) as db:
        repository = ClassroomRepository(db)
        if homeroom:
            room = repository.get_homeroom(class_id)
            return (
                None
                if room is None
                else NotificationAudienceDTO(
                    school_id=room.school_id,
                    recipient_ids=sorted(
                        {row.student_id for row in repository.active_roster(class_id)}
                    ),
                )
            )
        klass = repository.get_class(class_id)
        if klass is None:
            return None
        return NotificationAudienceDTO(
            school_id=klass.school_id,
            recipient_ids=sorted(
                {row.student_id for row in repository.active_memberships(class_id)}
                | {row.lecturer_id for row in repository.active_teachers(class_id)}
            ),
        )


def check_class_action(
    class_id: UUID,
    user_id: UUID,
    action: ClassAccessAction | str,
    *,
    session: Session | None = None,
    lock: bool = False,
) -> ClassAccessDTO:
    try:
        action = ClassAccessAction(action)
    except ValueError as exc:
        raise AppError(400, "Unknown class action") from exc

    with SessionLocal() if session is None else nullcontext(session) as db:
        user = get_user_summary(user_id, session=db)
        if user is None or user.status != "ACTIVE" or user.school_id is None:
            return ClassAccessDTO(allowed=False, class_id=class_id)
        repository = ClassroomRepository(db)
        # lock=True lets a consumer take a FOR SHARE row lock inside its own
        # write transaction, so Classroom mutations (set_teachers, archive,
        # enrollment sync, ...) that hold FOR UPDATE commit first and the
        # access decision cannot race them.
        klass = repository.get_class(class_id, for_share=lock)
        if klass is None or klass.school_id != user.school_id:
            # Unknown or cross-school class stays indistinguishable (404-che).
            return ClassAccessDTO(allowed=False, class_id=class_id)
        denied = ClassAccessDTO(allowed=False, class_id=class_id, class_status=klass.status)

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
