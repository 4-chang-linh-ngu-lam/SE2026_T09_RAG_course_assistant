from uuid import UUID

from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.errors import AppError
from app.modules.classroom.models import ClassRole
from app.modules.classroom.repository import ClassroomRepository


def is_admin(user: CurrentUser) -> bool:
    return "ADMIN" in user.roles


def require_class_member(session: Session, class_id: UUID, user: CurrentUser) -> None:
    """Any ACTIVE membership; the repository does not decide policy."""
    membership = ClassroomRepository(session).get_active_membership(class_id, user.id)
    if membership is None:
        # Indistinguishable from a nonexistent class; PENDING/LEFT/REMOVED learn nothing.
        raise AppError(404)


def require_class_role(
    session: Session,
    class_id: UUID,
    user: CurrentUser,
    roles: set[ClassRole],
    *,
    admin_intervenes: bool = False,
) -> None:
    """OWNER/CO_LECTURER/STUDENT membership check; Admin only when admin_intervenes."""
    membership = ClassroomRepository(session).get_active_membership(class_id, user.id)
    if membership is not None and membership.class_role in roles:
        return
    if admin_intervenes and is_admin(user):
        return
    # 404 for non-members, 403 for members lacking the role: cross-class probes learn
    # nothing, while a real member gets an actionable denial.
    raise AppError(404 if membership is None else 403)


def require_class_owner(session: Session, class_id: UUID, user: CurrentUser) -> None:
    require_class_role(session, class_id, user, {ClassRole.OWNER}, admin_intervenes=True)


def require_class_lecturer(session: Session, class_id: UUID, user: CurrentUser) -> None:
    require_class_role(
        session, class_id, user, {ClassRole.OWNER, ClassRole.CO_LECTURER}, admin_intervenes=True
    )
