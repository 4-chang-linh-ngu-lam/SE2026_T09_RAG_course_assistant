"""Transactional outbox (TASK-012): business writes and events commit atomically.

A notifier worker later drains unpublished events; failure to deliver never
rolls back the business operation. Any module writes rows here in the same
transaction as its business change.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.db import Base


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index(
            "idx_outbox_unpublished", "published_at", postgresql_where=text("published_at IS NULL")
        ),
    )

    id: Mapped[UUID]
    event_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def record_outbox_event(
    session: Session,
    *,
    event_type: str,
    aggregate_id: str | UUID,
    payload_json: dict,
) -> OutboxEvent:
    """Append an outbox row; the caller's transaction publishes it atomically."""
    event = OutboxEvent(
        event_type=event_type,
        aggregate_id=str(aggregate_id),
        payload_json=payload_json,
    )
    session.add(event)
    return event
