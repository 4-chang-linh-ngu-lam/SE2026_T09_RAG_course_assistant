from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser
from app.common.db import transaction
from app.common.errors import AppError
from app.common.pagination import Pagination, encode_cursor
from app.modules.classroom import public as classroom_public
from app.modules.identity import public as identity_public
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.repository import FeedRepository
from app.modules.social.feed.schemas import (
    PostAuthorSummary,
    PostCreateRequest,
    PostListResponse,
    PostResponse,
    PostUpdateRequest,
)

__all__ = ["FeedService"]


class FeedService:
    def __init__(self, session: Session):
        self.session = session
        self.repository = FeedRepository(session)

    def _resolve_author_summary(
        self, author_id: UUID, summaries: dict[UUID, identity_public.UserSummaryDTO] | None = None
    ) -> PostAuthorSummary:
        if summaries and author_id in summaries:
            user = summaries[author_id]
            return PostAuthorSummary(
                id=user.id,
                display_name=getattr(user, "display_name", None),
                email=user.email,
            )
        user = identity_public.get_user_summary(author_id, session=self.session)
        if user is not None:
            return PostAuthorSummary(
                id=user.id,
                display_name=getattr(user, "display_name", None),
                email=user.email,
            )
        return PostAuthorSummary(id=author_id, display_name=None, email="")

    def create_post(
        self,
        class_id: UUID,
        request: PostCreateRequest,
        current_user: CurrentUser,
    ) -> PostResponse:
        # Rule G1: Phải là thành viên ACTIVE của lớp
        is_member = classroom_public.is_active_member(
            class_id, current_user.id, session=self.session
        )
        if not is_member and "ADMIN" not in current_user.roles:
            raise AppError(403, "Chỉ thành viên hoạt động mới có quyền đăng bài")

        # Rule H5: Lớp ARCHIVED không cho đăng bài mới
        class_status = classroom_public.get_class_status(class_id, session=self.session)
        if class_status == "ARCHIVED":
            raise AppError(400, "Lớp học đã lưu trữ, không thể đăng bài mới")

        with transaction(self.session):
            post = ClassPost(
                class_id=class_id,
                author_id=current_user.id,
                body=request.body,
            )
            created = self.repository.create_post(post)
            author_summary = self._resolve_author_summary(current_user.id)
            return PostResponse(
                id=created.id,
                class_id=created.class_id,
                author=author_summary,
                body=created.body,
                created_at=created.created_at,
                updated_at=created.updated_at,
            )

    def list_posts(
        self,
        class_id: UUID,
        pagination: Pagination,
        current_user: CurrentUser,
    ) -> PostListResponse:
        # Rule G1 / Fail-closed: Kiểm tra quyền xem bảng tin
        is_member = classroom_public.is_active_member(
            class_id, current_user.id, session=self.session
        )
        if not is_member and "ADMIN" not in current_user.roles:
            raise AppError(403, "Không có quyền truy cập lớp học này")

        rows = self.repository.list_posts_by_class(
            class_id, limit=pagination.limit, cursor=pagination.cursor
        )
        items = rows[: pagination.limit]

        # Batch lookup thông tin tác giả từ identity.public
        author_ids = list({post.author_id for post in items})
        summaries = (
            identity_public.get_users_summaries(author_ids, session=self.session)
            if author_ids
            else {}
        )

        response_items = [
            PostResponse(
                id=post.id,
                class_id=post.class_id,
                author=self._resolve_author_summary(post.author_id, summaries),
                body=post.body,
                created_at=post.created_at,
                updated_at=post.updated_at,
            )
            for post in items
        ]

        next_cursor = (
            encode_cursor(items[-1].id) if len(rows) > pagination.limit and items else None
        )
        return PostListResponse(items=response_items, next_cursor=next_cursor)

    def update_post(
        self,
        class_id: UUID,
        post_id: UUID,
        request: PostUpdateRequest,
        current_user: CurrentUser,
    ) -> PostResponse:
        with transaction(self.session):
            post = self.repository.get_post_by_id(post_id, for_update=True)
            if post is None or post.class_id != class_id:
                raise AppError(404, "Bài viết không tồn tại")

            # Rule G1: Chỉ chính tác giả mới được sửa bài
            if post.author_id != current_user.id:
                raise AppError(403, "Chỉ tác giả mới có quyền chỉnh sửa bài viết")

            # Rule H5: Lớp ARCHIVED từ chối hoạt động ghi
            class_status = classroom_public.get_class_status(class_id, session=self.session)
            if class_status == "ARCHIVED":
                raise AppError(400, "Lớp học đã lưu trữ, không thể chỉnh sửa bài viết")

            post.body = request.body
            self.session.flush()

            author_summary = self._resolve_author_summary(post.author_id)
            return PostResponse(
                id=post.id,
                class_id=post.class_id,
                author=author_summary,
                body=post.body,
                created_at=post.created_at,
                updated_at=post.updated_at,
            )

    def delete_post(
        self,
        class_id: UUID,
        post_id: UUID,
        current_user: CurrentUser,
        correlation_id: UUID,
    ) -> None:
        with transaction(self.session):
            post = self.repository.get_post_by_id(post_id, for_update=True)
            if post is None or post.class_id != class_id:
                raise AppError(404, "Bài viết không tồn tại")

            now = datetime.now(UTC)

            # Trường hợp 1: Tác giả tự xóa bài viết
            if post.author_id == current_user.id:
                post.deleted_at = now
                self.session.flush()
                return

            # Trường hợp 2: Giảng viên hoặc Admin kiểm duyệt xóa (Rule L5)
            is_lecturer = classroom_public.is_class_lecturer(
                class_id, current_user.id, session=self.session
            )
            is_admin = "ADMIN" in current_user.roles

            if not is_lecturer and not is_admin:
                raise AppError(403, "Không có quyền xóa bài viết này")

            # Soft delete và ghi audit log bắt buộc theo Rule L5
            post.deleted_at = now
            self.session.flush()

            record_audit(
                self.session,
                actor_id=current_user.id,
                action="MODERATE_DELETE_POST",
                target_type="CLASS_POST",
                target_id=post.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(
                    reason_code="POLICY_VIOLATION",
                ),
            )
