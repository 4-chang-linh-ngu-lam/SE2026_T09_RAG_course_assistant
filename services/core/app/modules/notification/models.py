from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, ForeignKey, Identity, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Notification(Base):
    __tablename__ = "notifications"

    recipient_id: Mapped[UUID] = mapped_column(ForeignKey("core.users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(100))
    payload_json: Mapped[dict] = mapped_column(JSONB)
    dedup_key: Mapped[str] = mapped_column(String(64), unique=True)
    sequence: Mapped[int] = mapped_column(BigInteger, Identity(), unique=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Delivery time, rather than the producer transaction's start time.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


Index(
    "idx_notifications_recipient_created", Notification.recipient_id, Notification.created_at.desc()
)
Index(
    "idx_notifications_recipient_sequence", Notification.recipient_id, Notification.sequence.desc()
)
