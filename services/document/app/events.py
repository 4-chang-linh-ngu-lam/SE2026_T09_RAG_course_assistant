from datetime import UTC
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Document, Grant, Outbox


def append_event(
    session: Session, doc: Document, event_type: str, payload: dict, grant: Grant | None = None
):
    now = session.scalar(select(func.clock_timestamp()))
    row = Outbox(
        id=uuid4(),
        available_at=now,
        notification_payload=grant is not None,
        envelope={
            "event_id": str(uuid4()),
            "event_type": event_type,
            "schema_version": 1,
            "occurred_at": now.astimezone(UTC).isoformat(),
            "school_id": str(doc.school_id),
            "aggregate_id": str(grant.id if grant is not None else doc.id),
            "aggregate_revision": grant.revision if grant is not None else doc.revision,
            "payload": payload,
        },
    )
    session.add(row)


def grant_event(session: Session, doc: Document, grant: Grant, actor_id):
    append_event(
        session,
        doc,
        "document.grant.changed.v1",
        {
            "document_id": str(doc.id),
            "owner_user_id": str(doc.owner_id),
            "actor_user_id": str(actor_id),
            "class_id": str(grant.class_id),
            "grant_id": str(grant.id),
            "grant_revision": grant.revision,
            "is_active": grant.active,
            "document_version": doc.serving_version,
        },
        grant,
    )
