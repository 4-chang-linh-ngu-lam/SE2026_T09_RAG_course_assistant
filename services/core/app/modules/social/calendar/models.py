from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

__all__ = ["CalendarEvent", "CalendarOrigin"]


class CalendarOrigin(StrEnum):
    CORE = "CORE"
    LEARNING = "LEARNING"


class CalendarEvent(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(
            "length(title) >= 1 AND length(title) <= 200", name="ck_calendar_title_length"
        ),
        CheckConstraint(
            "description IS NULL OR length(description) <= 10000",
            name="ck_calendar_description_length",
        ),
        CheckConstraint("starts_at < ends_at", name="ck_calendar_time_order"),
        CheckConstraint("origin IN ('CORE', 'LEARNING')", name="ck_calendar_origin"),
        CheckConstraint("version >= 1", name="ck_calendar_version_positive"),
        Index(
            "uq_calendar_origin_ext_ref",
            "origin",
            "external_ref",
            unique=True,
            postgresql_where=text("external_ref IS NOT NULL"),
        ),
        Index("idx_calendar_class_time", "class_id", "starts_at"),
    )

    class_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.subject_classes.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(10000))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    origin: Mapped[CalendarOrigin] = mapped_column(String(8))
    external_ref: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
