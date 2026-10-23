from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base

__all__ = ["PostComment"]


class PostComment(Base):
    __tablename__ = "post_comments"
    __table_args__ = (
        CheckConstraint(
            "length(body) >= 1 AND length(body) <= 10000",
            name="ck_comments_body_length",
        ),
    )

    post_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.class_posts.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("core.users.id", ondelete="RESTRICT"), index=True
    )
    body: Mapped[str] = mapped_column(String(10000))
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


Index(
    "idx_comments_post_created",
    PostComment.post_id,
    PostComment.created_at.asc(),
    PostComment.id.asc(),
)
