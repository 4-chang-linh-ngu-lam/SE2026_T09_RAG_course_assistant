from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.modules.social.feed.models import ClassPost

__all__ = ["FeedRepository"]


class FeedRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_post(self, post: ClassPost) -> ClassPost:
        self.session.add(post)
        self.session.flush()
        return post

    def get_post_by_id(
        self,
        post_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> ClassPost | None:
        query = select(ClassPost).where(ClassPost.id == post_id)
        if not include_deleted:
            query = query.where(ClassPost.deleted_at.is_(None))
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def list_posts_by_class(
        self,
        class_id: UUID,
        *,
        limit: int,
        cursor: UUID | None,
    ) -> list[ClassPost]:
        query = select(ClassPost).where(
            ClassPost.class_id == class_id,
            ClassPost.deleted_at.is_(None),
        )
        if cursor is not None:
            cursor_post = self.get_post_by_id(cursor, include_deleted=True)
            if cursor_post is not None:
                query = query.where(
                    or_(
                        ClassPost.created_at < cursor_post.created_at,
                        and_(
                            ClassPost.created_at == cursor_post.created_at,
                            ClassPost.id < cursor_post.id,
                        ),
                    )
                )
        query = query.order_by(ClassPost.created_at.desc(), ClassPost.id.desc()).limit(limit + 1)
        return list(self.session.scalars(query))
