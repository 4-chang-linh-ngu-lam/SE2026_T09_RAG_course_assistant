from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

__all__ = ["ClassPost"]


class ClassPost(Base):
    """Class feed post model.

    Adheres to Business Rules:
    - G1: Class feed post owned by an ACTIVE student/lecturer.
    - L1: Soft-delete via deleted_at timestamp.
    """

    __tablename__ = "class_posts"
    __table_args__ = (
        CheckConstraint(
            "length(body) >= 1 AND length(body) <= 10000",
            name="ck_posts_body_length",
        ),
    )

    class_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.subject_classes.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    body: Mapped[str] = mapped_column(String(10000))
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


Index(
    "idx_posts_class_created",
    ClassPost.class_id,
    ClassPost.created_at.desc(),
    ClassPost.id.desc(),
)
