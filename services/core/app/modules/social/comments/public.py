"""Read-only comment identity for other Core modules; no access-policy bypass."""

from contextlib import nullcontext
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.common.db import SessionLocal
from app.modules.social.comments.repository import CommentsRepository

__all__ = ["CommentRefDTO", "get_visible_comment_ref"]


class CommentRefDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    post_id: UUID
    author_id: UUID


def get_visible_comment_ref(
    post_id: UUID, comment_id: UUID, *, session: Session | None = None
) -> CommentRefDTO | None:
    with SessionLocal() if session is None else nullcontext(session) as db:
        comment = CommentsRepository(db).get(comment_id)
        if comment is None or comment.post_id != post_id:
            return None
        return CommentRefDTO(id=comment.id, post_id=comment.post_id, author_id=comment.author_id)
