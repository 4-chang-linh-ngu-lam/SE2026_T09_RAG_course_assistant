from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.common.errors import AppError
from app.modules.social.comments.models import PostComment


class CommentsRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(self, comment: PostComment) -> PostComment:
        self.session.add(comment)
        self.session.flush()
        return comment

    def get(self, comment_id: UUID, *, for_update: bool = False) -> PostComment | None:
        query = select(PostComment).where(
            PostComment.id == comment_id,
            PostComment.deleted_at.is_(None),
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def list(self, post_id: UUID, *, limit: int, cursor: UUID | None) -> list[PostComment]:
        query = select(PostComment).where(
            PostComment.post_id == post_id,
            PostComment.deleted_at.is_(None),
        )
        if cursor is not None:
            cursor_comment = self.session.scalar(
                select(PostComment).where(
                    PostComment.id == cursor,
                    PostComment.post_id == post_id,
                )
            )
            if cursor_comment is None:
                raise AppError(400, "Invalid cursor")
            query = query.where(
                or_(
                    PostComment.created_at > cursor_comment.created_at,
                    and_(
                        PostComment.created_at == cursor_comment.created_at,
                        PostComment.id > cursor_comment.id,
                    ),
                )
            )
        return list(
            self.session.scalars(
                query.order_by(PostComment.created_at.asc(), PostComment.id.asc()).limit(limit + 1)
            )
        )
