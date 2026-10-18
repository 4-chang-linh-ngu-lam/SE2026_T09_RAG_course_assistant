from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser
from app.common.db import transaction
from app.common.errors import AppError
from app.common.outbox import record_outbox_event
from app.common.pagination import Pagination, encode_cursor
from app.modules.classroom.schemas import ClassAccessAction
from app.modules.identity import public as identity_public
from app.modules.social.access import get_delete_access, require_read_access, require_write_access
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.repository import FeedRepository
from app.modules.social.feed.schemas import (
    PostCreateRequest,
    PostListResponse,
    PostResponse,
    PostUpdateRequest,
)
from app.modules.social.schemas import AuthorSummary

__all__ = ["FeedService"]


class FeedService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = FeedRepository(session)

    @staticmethod
    def _author(
        author_id: UUID, summaries: dict[UUID, identity_public.UserSummaryDTO]
    ) -> AuthorSummary:
        user = summaries.get(author_id)
        return AuthorSummary(
            id=author_id,
            display_name=user.display_name if user is not None else None,
        )

    def _response(
        self,
        post: ClassPost,
        summaries: dict[UUID, identity_public.UserSummaryDTO] | None = None,
    ) -> PostResponse:
        if summaries is None:
            summaries = identity_public.get_users_summaries([post.author_id], session=self.session)
        return PostResponse(
            id=post.id,
            class_id=post.class_id,
            author=self._author(post.author_id, summaries),
            body=post.body,
            created_at=post.created_at,
            updated_at=post.updated_at,
        )

    def create_post(
        self, class_id: UUID, request: PostCreateRequest, current_user: CurrentUser
    ) -> PostResponse:
        require_write_access(
            self.session,
            class_id,
            current_user,
            ClassAccessAction.PARTICIPATE_CURRENT_CLASS,
        )
        with transaction(self.session):
            post = self.repository.create_post(
                ClassPost(class_id=class_id, author_id=current_user.id, body=request.body)
            )
            record_outbox_event(
                self.session,
                event_type="SOCIAL_POST_CREATED",
                aggregate_id=post.id,
                payload_json={
                    "class_id": str(class_id),
                    "post_id": str(post.id),
                    "author_id": str(current_user.id),
                },
            )
            return self._response(post)

    def list_posts(
        self, class_id: UUID, pagination: Pagination, current_user: CurrentUser
    ) -> PostListResponse:
        require_read_access(self.session, class_id, current_user)
        rows = self.repository.list_posts_by_class(
            class_id, limit=pagination.limit, cursor=pagination.cursor
        )
        items = rows[: pagination.limit]
        summaries = (
            identity_public.get_users_summaries(
                list({post.author_id for post in items}), session=self.session
            )
            if items
            else {}
        )
        return PostListResponse(
            items=[self._response(post, summaries) for post in items],
            next_cursor=(
                encode_cursor(items[-1].id) if len(rows) > pagination.limit and items else None
            ),
        )

    def update_post(
        self,
        class_id: UUID,
        post_id: UUID,
        request: PostUpdateRequest,
        current_user: CurrentUser,
    ) -> PostResponse:
        require_write_access(
            self.session,
            class_id,
            current_user,
            ClassAccessAction.PARTICIPATE_CURRENT_CLASS,
        )
        with transaction(self.session):
            post = self.repository.get_post_by_id(post_id, for_update=True)
            if post is None or post.class_id != class_id:
                raise AppError(404)
            if post.author_id != current_user.id:
                raise AppError(403)
            post.body = request.body
            self.session.flush()
            return self._response(post)

    def delete_post(
        self,
        class_id: UUID,
        post_id: UUID,
        current_user: CurrentUser,
        correlation_id: UUID,
    ) -> None:
        access = get_delete_access(self.session, class_id, current_user)
        with transaction(self.session):
            post = self.repository.get_post_by_id(post_id, for_update=True)
            if post is None or post.class_id != class_id:
                raise AppError(404)
            self_delete = post.author_id == current_user.id
            if self_delete and not access.can_participate:
                raise AppError(403)
            if not self_delete and not access.can_moderate:
                raise AppError(403)
            post.deleted_at = datetime.now(UTC)
            self.session.flush()
            if not self_delete:
                record_audit(
                    self.session,
                    actor_id=current_user.id,
                    action="MODERATE_DELETE_POST",
                    target_type="CLASS_POST",
                    target_id=post.id,
                    correlation_id=correlation_id,
                    metadata_json=AuditMetadata(reason_code="POLICY_VIOLATION"),
                )
