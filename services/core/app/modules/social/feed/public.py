from contextlib import nullcontext
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.common.db import SessionLocal
from app.modules.social.feed.repository import FeedRepository

__all__ = ["PostRefDTO", "get_visible_post_ref"]


class PostRefDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    class_id: UUID
    author_id: UUID


def get_visible_post_ref(
    class_id: UUID,
    post_id: UUID,
    *,
    session: Session | None = None,
    for_update: bool = False,
) -> PostRefDTO | None:
    """for_update khóa bài trong transaction của caller để không ghi lên bài vừa bị xóa."""
    with SessionLocal() if session is None else nullcontext(session) as db:
        post = FeedRepository(db).get_post_by_id(post_id, for_update=for_update)
        if post is None or post.class_id != class_id:
            return None
        return PostRefDTO(id=post.id, class_id=post.class_id, author_id=post.author_id)
