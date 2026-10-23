from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.errors import AppError
from app.modules.classroom import public as classroom_public
from app.modules.classroom.public import ClassAccessAction, ClassAccessDTO


def require_read_access(
    session: Session, class_id: UUID, user: CurrentUser, *, lock: bool = False
) -> ClassAccessDTO:
    access = classroom_public.check_class_action(
        class_id, user.id, ClassAccessAction.READ_CLASS_CONTENT, session=session, lock=lock
    )
    if not access.allowed:
        raise AppError(404)
    return access


def require_write_access(
    session: Session,
    class_id: UUID,
    user: CurrentUser,
    action: ClassAccessAction,
) -> ClassAccessDTO:
    read = require_read_access(session, class_id, user, lock=True)
    if str(read.class_status) == "ARCHIVED":
        raise AppError(409, "Lớp đã lưu trữ")
    access = classroom_public.check_class_action(class_id, user.id, action, session=session)
    if not access.allowed:
        raise AppError(403)
    return access


@dataclass(frozen=True)
class DeleteAccess:
    can_read: bool
    can_participate: bool
    can_moderate: bool


def get_delete_access(session: Session, class_id: UUID, user: CurrentUser) -> DeleteAccess:
    """Allow same-school Admin moderation without granting Social read access."""
    read = classroom_public.check_class_action(
        class_id, user.id, ClassAccessAction.READ_CLASS_CONTENT, session=session, lock=True
    )
    if str(read.class_status) == "ARCHIVED" and (read.allowed or "ADMIN" in user.roles):
        raise AppError(409, "Lớp đã lưu trữ")
    moderate = classroom_public.check_class_action(
        class_id, user.id, ClassAccessAction.MODERATE_CLASS_CONTENT, session=session
    )
    if not read.allowed and not moderate.allowed:
        raise AppError(404)
    participate = classroom_public.check_class_action(
        class_id, user.id, ClassAccessAction.PARTICIPATE_CURRENT_CLASS, session=session
    )
    return DeleteAccess(
        can_read=read.allowed,
        can_participate=participate.allowed,
        can_moderate=moderate.allowed,
    )
