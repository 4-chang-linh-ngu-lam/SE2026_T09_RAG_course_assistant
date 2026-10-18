"""Transactional outbox (TASK-012): business writes and events commit atomically.

A notifier worker later drains unpublished events; failure to deliver never
rolls back the business operation. Any module writes rows here in the same
transaction as its business change.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.common.db import Base

OUTBOX_SCHEMA_VERSION = 2


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("schema_version >= 1", name="ck_outbox_schema_version"),
        CheckConstraint("attempts >= 0", name="ck_outbox_attempts"),
        CheckConstraint(
            "aggregate_version IS NULL OR aggregate_version >= 1",
            name="ck_outbox_aggregate_version",
        ),
        Index(
            "idx_outbox_unpublished", "published_at", postgresql_where=text("published_at IS NULL")
        ),
    )

    id: Mapped[UUID]
    event_type: Mapped[str] = mapped_column(String(100))
    aggregate_id: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The database default stays at v1 for old app instances during a rolling
    # migration; current producers explicitly write v2 with an audience snapshot.
    schema_version: Mapped[int] = mapped_column(
        Integer, default=OUTBOX_SCHEMA_VERSION, server_default="1"
    )
    aggregate_version: Mapped[int | None] = mapped_column(BigInteger)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64))


def record_outbox_event(
    session: Session,
    *,
    event_type: str,
    aggregate_id: str | UUID,
    payload_json: dict,
    schema_version: int = OUTBOX_SCHEMA_VERSION,
    aggregate_version: int | None = None,
) -> OutboxEvent:
    """Append an outbox row; the caller's transaction publishes it atomically."""
    event = OutboxEvent(
        id=uuid4(),
        event_type=event_type,
        aggregate_id=str(aggregate_id),
        payload_json=payload_json,
        schema_version=schema_version,
        aggregate_version=aggregate_version
        if aggregate_version is not None
        else payload_json.get("version"),
    )
    session.add(event)
    return event
