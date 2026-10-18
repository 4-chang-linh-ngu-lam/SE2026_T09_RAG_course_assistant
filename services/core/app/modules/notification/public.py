"""Producer boundary: snapshot the audience inside the caller's transaction.

Outbox ownership/enqueue stays in app.common.outbox.record_outbox_event. Neither
this helper nor enqueue commits; failure must abort the producer mutation.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.modules.classroom.public import get_notification_audience

__all__ = ["snapshot_audience"]


def snapshot_audience(session: Session, class_id: UUID) -> dict:
    audience = get_notification_audience(class_id, session=session)
    if audience is None:
        raise AppError(503, "Notification audience unavailable")
    return audience.model_dump(mode="json")
