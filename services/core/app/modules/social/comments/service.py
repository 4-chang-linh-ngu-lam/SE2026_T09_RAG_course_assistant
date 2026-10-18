from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser
from app.common.db import transaction
from app.common.errors import AppError
from app.common.outbox import record_outbox_event
from app.common.pagination import Pagination, encode_cursor
from app.modules.classroom.public import ClassAccessAction
from app.modules.identity import public as identity_public
from app.modules.notification.public import snapshot_audience
from app.modules.social.access import get_delete_access, require_read_access, require_write_access
from app.modules.social.comments.models import PostComment
from app.modules.social.comments.repository import CommentsRepository
from app.modules.social.comments.schemas import (
    CommentCreateRequest,
    CommentListResponse,
    CommentResponse,
    CommentUpdateRequest,
)
from app.modules.social.feed import public as feed_public
from app.modules.social.schemas import AuthorSummary


class CommentsService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = CommentsRepository(session)

    def _response(
        self,
        comment: PostComment,
        summaries: dict[UUID, identity_public.UserSummaryDTO] | None = None,
    ) -> CommentResponse:
        if summaries is None:
            summaries = identity_public.get_users_summaries(
                [comment.author_id], session=self.session
            )
        user = summaries.get(comment.author_id)
        return CommentResponse(
            id=comment.id,
            post_id=comment.post_id,
            author=AuthorSummary(
                id=comment.author_id,
                display_name=user.display_name if user is not None else None,
            ),
            body=comment.body,
            created_at=comment.created_at,
            updated_at=comment.updated_at,
        )

    def _post(
        self, class_id: UUID, post_id: UUID, *, for_update: bool = False
    ) -> feed_public.PostRefDTO:
        post = feed_public.get_visible_post_ref(
            class_id, post_id, session=self.session, for_update=for_update
        )
        if post is None:
            raise AppError(404)
        return post

    def list_comments(
        self,
        class_id: UUID,
        post_id: UUID,
        pagination: Pagination,
        current_user: CurrentUser,
    ) -> CommentListResponse:
        require_read_access(self.session, class_id, current_user)
        self._post(class_id, post_id)
        rows = self.repository.list(post_id, limit=pagination.limit, cursor=pagination.cursor)
        items = rows[: pagination.limit]
        summaries = (
            identity_public.get_users_summaries(
                list({comment.author_id for comment in items}), session=self.session
            )
            if items
            else {}
        )
        return CommentListResponse(
            items=[self._response(comment, summaries) for comment in items],
            next_cursor=(
                encode_cursor(items[-1].id) if len(rows) > pagination.limit and items else None
            ),
        )

    def create_comment(
        self,
        class_id: UUID,
        post_id: UUID,
        request: CommentCreateRequest,
        current_user: CurrentUser,
    ) -> CommentResponse:
        with transaction(self.session):
            require_write_access(
                self.session,
                class_id,
                current_user,
                ClassAccessAction.PARTICIPATE_CURRENT_CLASS,
            )
            post = self._post(class_id, post_id, for_update=True)
            comment = self.repository.create(
                PostComment(post_id=post_id, author_id=current_user.id, body=request.body)
            )
            if current_user.id != post.author_id:
                record_outbox_event(
                    self.session,
                    event_type="SOCIAL_COMMENT_CREATED",
                    aggregate_id=comment.id,
                    payload_json={
                        **snapshot_audience(self.session, class_id),
                        "class_id": str(class_id),
                        "post_id": str(post_id),
                        "comment_id": str(comment.id),
                        "author_id": str(current_user.id),
                        "post_author_id": str(post.author_id),
                    },
                )
            return self._response(comment)

    def update_comment(
        self,
        class_id: UUID,
        post_id: UUID,
        comment_id: UUID,
        request: CommentUpdateRequest,
        current_user: CurrentUser,
    ) -> CommentResponse:
        with transaction(self.session):
            require_write_access(
                self.session,
                class_id,
                current_user,
                ClassAccessAction.PARTICIPATE_CURRENT_CLASS,
            )
            self._post(class_id, post_id, for_update=True)
            comment = self.repository.get(comment_id, for_update=True)
            if comment is None or comment.post_id != post_id:
                raise AppError(404)
            if comment.author_id != current_user.id:
                raise AppError(403)
            comment.body = request.body
            self.session.flush()
            return self._response(comment)

    def delete_comment(
        self,
        class_id: UUID,
        post_id: UUID,
        comment_id: UUID,
        current_user: CurrentUser,
        correlation_id: UUID,
    ) -> None:
        with transaction(self.session):
            access = get_delete_access(self.session, class_id, current_user)
            self._post(class_id, post_id, for_update=True)
            comment = self.repository.get(comment_id, for_update=True)
            if comment is None or comment.post_id != post_id:
                raise AppError(404)
            self_delete = comment.author_id == current_user.id
            if self_delete and not access.can_participate:
                raise AppError(403)
            if not self_delete and not access.can_moderate:
                raise AppError(403)
            comment.deleted_at = datetime.now(UTC)
            self.session.flush()
            if not self_delete:
                record_audit(
                    self.session,
                    actor_id=current_user.id,
                    school_id=current_user.school_id,
                    action="MODERATE_DELETE_COMMENT",
                    target_type="POST_COMMENT",
                    target_id=comment.id,
                    correlation_id=correlation_id,
                    metadata_json=AuditMetadata(reason_code="POLICY_VIOLATION"),
                )
