from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from app.bootstrap import register_routers
from app.common.audit import AuditEvent
from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.db import get_db
from app.common.errors import AppError, register_error_handlers
from app.common.pagination import Pagination, encode_cursor
from app.modules.classroom import public as classroom_public
from app.modules.identity import public as identity_public
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.schemas import (
    PostAuthorSummary,
    PostCreateRequest,
    PostListResponse,
    PostResponse,
    PostUpdateRequest,
)
from app.modules.social.feed.service import FeedService


# -------------------------------------------------------------------------
# 1. Models & Database Schema Tests
# -------------------------------------------------------------------------
def test_feed_model_schema_ddl():
    table = ClassPost.__table__
    assert table.schema == "core"
    assert table.name == "class_posts"
    assert table.c.id.primary_key
    assert table.c.body.type.length == 10000
    assert table.c.deleted_at.nullable is True
    assert table.c.created_at.type.timezone is True

    # Register stub referenced table if not present for DDL compilation
    from sqlalchemy import Column, Table, Uuid

    if "core.classes" not in table.metadata.tables:
        Table("classes", table.metadata, Column("id", Uuid, primary_key=True), schema="core")

    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "core.class_posts" in ddl
    assert "deleted_at TIMESTAMP WITH TIME ZONE" in ddl
    assert "ck_posts_body_length" in ddl


# -------------------------------------------------------------------------
# 2. Pydantic Schemas Validation Tests
# -------------------------------------------------------------------------
def test_feed_schemas_validation():
    # Valid post body
    req = PostCreateRequest(body="Hello class, this is my first post!")
    assert req.body == "Hello class, this is my first post!"

    # Empty or whitespace only body must be rejected
    with pytest.raises(ValidationError):
        PostCreateRequest(body="")

    with pytest.raises(ValidationError):
        PostCreateRequest(body="   \n\t  ")

    # Body exceeding 10000 chars must be rejected
    with pytest.raises(ValidationError):
        PostCreateRequest(body="a" * 10001)

    # Update request empty body must be rejected
    with pytest.raises(ValidationError):
        PostUpdateRequest(body="  ")


# -------------------------------------------------------------------------
# 3. Service Layer Unit Tests
# -------------------------------------------------------------------------
@pytest.fixture
def service_env(monkeypatch):
    session = MagicMock(spec=Session)
    service = FeedService(session)

    # Mock user summary lookup
    user_id_1 = uuid4()
    user_id_2 = uuid4()
    user_dto_1 = identity_public.UserSummaryDTO(
        id=user_id_1, email="student1@example.com", status="ACTIVE"
    )
    user_dto_2 = identity_public.UserSummaryDTO(
        id=user_id_2, email="lecturer@example.com", status="ACTIVE"
    )

    monkeypatch.setattr(
        identity_public,
        "get_user_summary",
        lambda uid, session=None: {user_id_1: user_dto_1, user_id_2: user_dto_2}.get(uid),
    )
    monkeypatch.setattr(
        identity_public,
        "get_users_summaries",
        lambda uids, session=None: {
            uid: dto
            for uid, dto in {user_id_1: user_dto_1, user_id_2: user_dto_2}.items()
            if uid in uids
        },
    )

    return service, session, user_id_1, user_id_2


def test_create_post_success(service_env, monkeypatch):
    service, _session, student_id, _ = service_env
    class_id = uuid4()
    current_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])

    monkeypatch.setattr(classroom_public, "is_active_member", lambda cid, uid, session=None: True)
    monkeypatch.setattr(classroom_public, "get_class_status", lambda cid, session=None: "ACTIVE")

    # Mock repository behavior
    def fake_create(post):
        post.id = uuid4()
        post.created_at = datetime.now(UTC)
        post.updated_at = datetime.now(UTC)
        return post

    monkeypatch.setattr(service.repository, "create_post", fake_create)

    response = service.create_post(
        class_id, PostCreateRequest(body="Discussion on homework 1"), current_user
    )

    assert response.class_id == class_id
    assert response.author.id == student_id
    assert response.author.email == "student1@example.com"
    assert response.body == "Discussion on homework 1"


def test_create_post_forbidden_for_non_member(service_env, monkeypatch):
    service, _, student_id, _ = service_env
    class_id = uuid4()
    current_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])

    # Non-member
    monkeypatch.setattr(classroom_public, "is_active_member", lambda cid, uid, session=None: False)
    monkeypatch.setattr(classroom_public, "get_class_status", lambda cid, session=None: "ACTIVE")

    with pytest.raises(AppError) as exc_info:
        service.create_post(
            class_id, PostCreateRequest(body="Attempting post from outside"), current_user
        )
    assert exc_info.value.status_code == 403


def test_create_post_bad_request_when_class_archived(service_env, monkeypatch):
    service, _, student_id, _ = service_env
    class_id = uuid4()
    current_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])

    monkeypatch.setattr(classroom_public, "is_active_member", lambda cid, uid, session=None: True)
    monkeypatch.setattr(classroom_public, "get_class_status", lambda cid, session=None: "ARCHIVED")

    # Rule H5: Lớp lưu trữ không cho đăng bài
    with pytest.raises(AppError) as exc_info:
        service.create_post(
            class_id, PostCreateRequest(body="Posting in archived class"), current_user
        )
    assert exc_info.value.status_code == 400


def test_list_posts_active_member_and_cursor(service_env, monkeypatch):
    service, _, student_id, _ = service_env
    class_id = uuid4()
    current_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])

    monkeypatch.setattr(classroom_public, "is_active_member", lambda cid, uid, session=None: True)

    post1 = ClassPost(
        class_id=class_id,
        author_id=student_id,
        body="Post 1",
        deleted_at=None,
    )
    post1.id = uuid4()
    post1.created_at = datetime.now(UTC)
    post1.updated_at = datetime.now(UTC)

    post2 = ClassPost(
        class_id=class_id,
        author_id=student_id,
        body="Post 2",
        deleted_at=None,
    )
    post2.id = uuid4()
    post2.created_at = datetime.now(UTC)
    post2.updated_at = datetime.now(UTC)

    # Return 2 posts when limit is 1 -> next_cursor should be generated
    monkeypatch.setattr(
        service.repository, "list_posts_by_class", lambda cid, limit, cursor: [post1, post2]
    )

    pagination = Pagination(limit=1, cursor=None)
    result = service.list_posts(class_id, pagination, current_user)

    assert len(result.items) == 1
    assert result.items[0].id == post1.id
    assert result.next_cursor == encode_cursor(post1.id)


def test_list_posts_forbidden_for_non_member(service_env, monkeypatch):
    service, _, student_id, _ = service_env
    class_id = uuid4()
    current_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])

    monkeypatch.setattr(classroom_public, "is_active_member", lambda cid, uid, session=None: False)

    with pytest.raises(AppError) as exc:
        service.list_posts(class_id, Pagination(limit=20, cursor=None), current_user)
    assert exc.value.status_code == 403


def test_update_post_author_only(service_env, monkeypatch):
    service, _session, student_id, other_user_id = service_env
    class_id = uuid4()
    post_id = uuid4()

    post = ClassPost(
        class_id=class_id,
        author_id=student_id,
        body="Original body",
        deleted_at=None,
    )
    post.id = post_id
    post.created_at = datetime.now(UTC)
    post.updated_at = datetime.now(UTC)

    monkeypatch.setattr(service.repository, "get_post_by_id", lambda pid, **kwargs: post)
    monkeypatch.setattr(classroom_public, "get_class_status", lambda cid, session=None: "ACTIVE")

    # 1. Author updates post -> Success
    author_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])
    res = service.update_post(
        class_id, post_id, PostUpdateRequest(body="Updated body"), author_user
    )
    assert res.body == "Updated body"

    # 2. Other user tries to update -> 403
    other_user = CurrentUser(
        id=other_user_id, status="ACTIVE", session_version=1, roles=["STUDENT"]
    )
    with pytest.raises(AppError) as exc:
        service.update_post(class_id, post_id, PostUpdateRequest(body="Hacked body"), other_user)
    assert exc.value.status_code == 403

    # 3. Update in ARCHIVED class -> 400
    monkeypatch.setattr(classroom_public, "get_class_status", lambda cid, session=None: "ARCHIVED")
    with pytest.raises(AppError) as exc_archived:
        service.update_post(class_id, post_id, PostUpdateRequest(body="Edit archived"), author_user)
    assert exc_archived.value.status_code == 400


def test_delete_post_author_soft_deletes_without_audit(service_env, monkeypatch):
    service, session, student_id, _ = service_env
    class_id = uuid4()
    post_id = uuid4()

    post = ClassPost(
        class_id=class_id,
        author_id=student_id,
        body="Body to delete",
        deleted_at=None,
    )
    post.id = post_id

    monkeypatch.setattr(service.repository, "get_post_by_id", lambda pid, **kwargs: post)

    author_user = CurrentUser(id=student_id, status="ACTIVE", session_version=1, roles=["STUDENT"])
    correlation_id = uuid4()

    service.delete_post(class_id, post_id, author_user, correlation_id)

    # Soft deleted
    assert post.deleted_at is not None
    # No audit record since author deleted their own post
    session.add.assert_not_called()


def test_delete_post_lecturer_moderates_with_audit(service_env, monkeypatch):
    service, session, student_id, lecturer_id = service_env
    class_id = uuid4()
    post_id = uuid4()

    post = ClassPost(
        class_id=class_id,
        author_id=student_id,
        body="Violating post",
        deleted_at=None,
    )
    post.id = post_id

    monkeypatch.setattr(service.repository, "get_post_by_id", lambda pid, **kwargs: post)
    monkeypatch.setattr(
        classroom_public,
        "is_class_lecturer",
        lambda cid, uid, session=None: uid == lecturer_id,
    )

    lecturer_user = CurrentUser(
        id=lecturer_id, status="ACTIVE", session_version=1, roles=["LECTURER"]
    )
    correlation_id = uuid4()

    service.delete_post(class_id, post_id, lecturer_user, correlation_id)

    # Soft-deleted
    assert post.deleted_at is not None
    # Audit log recorded according to Rule L5
    session.add.assert_called_once()
    added_event = session.add.call_args[0][0]
    assert isinstance(added_event, AuditEvent)
    assert added_event.actor_id == lecturer_id
    assert added_event.action == "MODERATE_DELETE_POST"
    assert added_event.target_type == "CLASS_POST"
    assert added_event.target_id == post_id
    assert added_event.metadata_json == {
        "changed_fields": [],
        "reason_code": "POLICY_VIOLATION",
    }


def test_delete_post_unauthorized_student_forbidden(service_env, monkeypatch):
    service, _, student_id, other_student_id = service_env
    class_id = uuid4()
    post_id = uuid4()

    post = ClassPost(
        class_id=class_id,
        author_id=student_id,
        body="Student post",
        deleted_at=None,
    )
    post.id = post_id

    monkeypatch.setattr(service.repository, "get_post_by_id", lambda pid, **kwargs: post)
    monkeypatch.setattr(classroom_public, "is_class_lecturer", lambda cid, uid, session=None: False)

    unauthorized_user = CurrentUser(
        id=other_student_id, status="ACTIVE", session_version=1, roles=["STUDENT"]
    )

    with pytest.raises(AppError) as exc:
        service.delete_post(class_id, post_id, unauthorized_user, uuid4())
    assert exc.value.status_code == 403


# -------------------------------------------------------------------------
# 4. Router HTTP Contract Tests via TestClient
# -------------------------------------------------------------------------
@pytest.fixture
def api_client(monkeypatch):
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)

    current_test_user = CurrentUser(
        id=uuid4(), status="ACTIVE", session_version=1, roles=["STUDENT"]
    )

    app.dependency_overrides[get_current_user] = lambda: current_test_user
    app.dependency_overrides[get_db] = lambda: MagicMock(spec=Session)

    client = TestClient(app)
    return client, current_test_user


def test_feed_router_http_flow(api_client, monkeypatch):
    client, user = api_client
    class_id = uuid4()
    post_id = uuid4()

    # Mock classroom checks
    monkeypatch.setattr(classroom_public, "is_active_member", lambda cid, uid, session=None: True)
    monkeypatch.setattr(classroom_public, "get_class_status", lambda cid, session=None: "ACTIVE")
    monkeypatch.setattr(
        identity_public,
        "get_user_summary",
        lambda uid, session=None: identity_public.UserSummaryDTO(
            id=uid, email="user@example.com", status="ACTIVE"
        ),
    )
    monkeypatch.setattr(
        identity_public,
        "get_users_summaries",
        lambda uids, session=None: {
            uid: identity_public.UserSummaryDTO(id=uid, email="user@example.com", status="ACTIVE")
            for uid in uids
        },
    )

    fake_post = ClassPost(
        class_id=class_id,
        author_id=user.id,
        body="Hello world",
        deleted_at=None,
    )
    fake_post.id = post_id
    fake_post.created_at = datetime.now(UTC)
    fake_post.updated_at = datetime.now(UTC)

    # 1. POST /api/v1/classes/{class_id}/posts
    monkeypatch.setattr(
        FeedService,
        "create_post",
        lambda self, cid, req, u: PostResponse(
            id=post_id,
            class_id=cid,
            author=PostAuthorSummary(id=u.id, display_name="User", email="user@example.com"),
            body=req.body,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )

    resp = client.post(
        f"/api/v1/classes/{class_id}/posts",
        json={"body": "Hello world"},
        headers={"X-Correlation-ID": str(uuid4())},
    )
    assert resp.status_code == 201
    assert resp.json()["body"] == "Hello world"
    assert "X-Correlation-ID" in resp.headers

    # 2. GET /api/v1/classes/{class_id}/posts
    monkeypatch.setattr(
        FeedService,
        "list_posts",
        lambda self, cid, pag, u: PostListResponse(
            items=[
                PostResponse(
                    id=post_id,
                    class_id=cid,
                    author=PostAuthorSummary(
                        id=u.id, display_name="User", email="user@example.com"
                    ),
                    body="Hello world",
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            ],
            next_cursor=None,
        ),
    )

    resp_list = client.get(f"/api/v1/classes/{class_id}/posts")
    assert resp_list.status_code == 200
    assert len(resp_list.json()["items"]) == 1

    # 3. PATCH /api/v1/classes/{class_id}/posts/{post_id}
    monkeypatch.setattr(
        FeedService,
        "update_post",
        lambda self, cid, pid, req, u: PostResponse(
            id=pid,
            class_id=cid,
            author=PostAuthorSummary(id=u.id, display_name="User", email="user@example.com"),
            body=req.body,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
    )

    resp_patch = client.patch(
        f"/api/v1/classes/{class_id}/posts/{post_id}",
        json={"body": "Updated body"},
    )
    assert resp_patch.status_code == 200
    assert resp_patch.json()["body"] == "Updated body"

    # 4. DELETE /api/v1/classes/{class_id}/posts/{post_id}
    monkeypatch.setattr(FeedService, "delete_post", lambda self, cid, pid, u, corr: None)

    resp_delete = client.delete(f"/api/v1/classes/{class_id}/posts/{post_id}")
    assert resp_delete.status_code == 204
