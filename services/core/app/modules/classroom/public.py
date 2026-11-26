"""Action-based Classroom boundary for Core modules and the internal API."""

from contextlib import nullcontext
from dataclasses import dataclass
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
from app.modules.classroom.models import ClassStatus, SubjectClass, TeachingAssignment
from app.modules.classroom.repository import ClassroomRepository
from app.modules.classroom.schemas import (
    AuthorizationAction,
    ClassAccessAction,
    ClassAccessDTO,
    NotificationAudienceDTO,
    RosterImportSnapshot,
)
from app.modules.identity.public import get_user_roles, get_user_summary

__all__ = [
    "AuthorizationAction",
    "ClassAccessAction",
    "ClassAccessDTO",
    "check_class_action",
    "check_class_authorization_action",
    "get_class_lecturer_ids",
]
__all__ += ["NotificationAudienceDTO", "get_notification_audience"]
__all__ += ["RosterImportSnapshot", "admin_append_roster", "admin_preview_roster"]
__all__ += ["maintenance_provision_schools", "maintenance_schools", "seed_dev_classroom"]
__all__ += ["maintenance_user_schools"]


@dataclass(frozen=True)
class _ClassAuthorizationContext:
    user_id: UUID
    class_id: UUID
    klass: SubjectClass
    roles: frozenset[str]
    repository: ClassroomRepository
    current_student: bool
    current_teacher: bool
    assignment: TeachingAssignment | None

    @property
    def active_class(self) -> bool:
        return self.klass.status == ClassStatus.ACTIVE


def _class_authorization_context(
    class_id: UUID,
    user_id: UUID,
    db: Session,
    *,
    lock: bool,
) -> _ClassAuthorizationContext | None:
    user = get_user_summary(user_id, session=db)
    if user is None or user.status != "ACTIVE" or user.school_id is None:
        return None
    repository = ClassroomRepository(db)
    # Locking here serializes the decision against roster, assignment and lifecycle
    # mutations when the caller supplies a transaction that needs this guarantee.
    klass = repository.get_class(class_id, for_share=lock)
    if klass is None or klass.school_id != user.school_id:
        return None
    roles = frozenset(get_user_roles(user_id, session=db))
    member = repository.active_membership(class_id, user_id)
    assignment = repository.active_teacher(class_id, user_id)
    return _ClassAuthorizationContext(
        user_id=user_id,
        class_id=class_id,
        klass=klass,
        roles=roles,
        repository=repository,
        current_student=member is not None and "STUDENT" in roles,
        current_teacher=assignment is not None and "LECTURER" in roles,
        assignment=assignment,
    )


def _legacy_class_action_allowed(
    context: _ClassAuthorizationContext, action: ClassAccessAction
) -> bool:
    if action == ClassAccessAction.READ_CLASS_CONTENT:
        return context.current_student or context.current_teacher
    if action == ClassAccessAction.PARTICIPATE_CURRENT_CLASS:
        return context.active_class and (context.current_student or context.current_teacher)
    if action == ClassAccessAction.MODERATE_CLASS_CONTENT:
        return context.active_class and (context.current_teacher or "ADMIN" in context.roles)
    if action == ClassAccessAction.MANAGE_CLASS_CALENDAR:
        return context.active_class and context.current_teacher
    if action == ClassAccessAction.READ_OWN_HISTORY:
        return "STUDENT" in context.roles and context.repository.has_membership_history(
            context.class_id, context.user_id
        )
    if action == ClassAccessAction.READ_DOCUMENT_SOURCE:
        return context.current_student or context.current_teacher
    if action == ClassAccessAction.USE_AI_TUTOR:
        return context.active_class and context.current_student
    # GRADE_SUBMITTED_WORK; Learning checks the assigned submission separately.
    return context.active_class and context.current_teacher


def _core04_class_action_allowed(
    context: _ClassAuthorizationContext, action: AuthorizationAction
) -> bool:
    compatible_legacy_actions = {
        AuthorizationAction.DOCUMENT_READ: ClassAccessAction.READ_DOCUMENT_SOURCE,
        AuthorizationAction.AI_QUERY: ClassAccessAction.USE_AI_TUTOR,
        AuthorizationAction.GRADE_MANAGE: ClassAccessAction.GRADE_SUBMITTED_WORK,
    }
    legacy_action = compatible_legacy_actions.get(action)
    if legacy_action is not None:
        return _legacy_class_action_allowed(context, legacy_action)

    if action in {
        AuthorizationAction.DOCUMENT_SHARE,
        AuthorizationAction.DOCUMENT_MANAGE,
        AuthorizationAction.ASSIGNMENT_CREATE,
        AuthorizationAction.ASSESSMENT_MANAGE,
    }:
        # Document must still validate source ownership/grants; Learning owns
        # draft, primary-approval and assessment-state checks.
        return context.active_class and context.current_teacher
    if action == AuthorizationAction.PRACTICE_ACCESS:
        return context.active_class and context.current_student
    if action == AuthorizationAction.ASSIGNMENT_SUBMIT:
        return context.active_class and context.current_student
    if action == AuthorizationAction.ANALYTICS_VIEW:
        student_history = "STUDENT" in context.roles and context.repository.has_membership_history(
            context.class_id, context.user_id
        )
        return student_history or context.current_teacher or "ADMIN" in context.roles
    return False


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
        context = _class_authorization_context(class_id, user_id, db, lock=lock)
        if context is None:
            return ClassAccessDTO(allowed=False, class_id=class_id)
        denied = ClassAccessDTO(allowed=False, class_id=class_id, class_status=context.klass.status)
        allowed = _legacy_class_action_allowed(context, action)
        if not allowed:
            return denied
        return ClassAccessDTO(
            allowed=True,
            class_id=class_id,
            school_id=context.klass.school_id,
            class_status=context.klass.status,
            teaching_role=context.assignment.role if context.current_teacher else None,
        )


def check_class_authorization_action(
    class_id: UUID,
    user_id: UUID,
    action: AuthorizationAction | str,
    *,
    session: Session | None = None,
    lock: bool = False,
) -> bool:
    """Return only the Core class-side gate; the resource-owning service must check its own data."""
    try:
        action = AuthorizationAction(action)
    except ValueError as exc:
        raise AppError(400, "Unknown authorization action") from exc

    with SessionLocal() if session is None else nullcontext(session) as db:
        context = _class_authorization_context(class_id, user_id, db, lock=lock)
        if context is None:
            return False
        return _core04_class_action_allowed(context, action)


def get_class_lecturer_ids(class_id: UUID, *, session: Session | None = None) -> list[UUID]:
    with SessionLocal() if session is None else nullcontext(session) as db:
        return [
            assignment.lecturer_id
            for assignment in ClassroomRepository(db).active_teachers(class_id)
        ]
