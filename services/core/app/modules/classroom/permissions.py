from uuid import UUID

from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser, require_school_scope
from app.common.errors import AppError
from app.modules.classroom.public import check_class_action
from app.modules.classroom.repository import ClassroomRepository
from app.modules.classroom.schemas import ClassAccessAction


def require_admin(user: CurrentUser) -> UUID:
    if user.status != "ACTIVE" or "ADMIN" not in user.roles:
        raise AppError(403)
    require_school_scope(user.school_id, user.school_id)
    return user.school_id


def require_class_read(session: Session, class_id: UUID, user: CurrentUser) -> None:
    if "ADMIN" in user.roles and user.school_id is not None:
        klass = ClassroomRepository(session).get_class(class_id)
        if klass is None:
            raise AppError(404)
        require_school_scope(user.school_id, klass.school_id)
        return
    if not check_class_action(
        class_id, user.id, ClassAccessAction.READ_CLASS_CONTENT, session=session
    ).allowed:
        raise AppError(404)
