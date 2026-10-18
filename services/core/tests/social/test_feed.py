from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.errors import AppError
from app.common.pagination import Pagination
from app.modules.classroom import public as classroom_public
from app.modules.identity import public as identity_public
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.schemas import PostCreateRequest, PostUpdateRequest
from app.modules.social.feed.service import FeedService


def _user(user_id=None, role="STUDENT"):
    return CurrentUser(
        id=user_id or uuid4(),
        status="ACTIVE",
        session_version=1,
        roles=[role],
    )


def _access(monkeypatch, *, read=True, write=True, moderate=False, archived=False):
    def check(_class_id, _user_id, action, *, session, lock=False):
        action = str(action)
        allowed = read if action == "read_class_content" else write
        if action == "moderate_class_content":
            allowed = moderate
        return SimpleNamespace(
            allowed=allowed,
            class_status="ARCHIVED" if archived else "ACTIVE",
        )

    monkeypatch.setattr(classroom_public, "check_class_action", check)


def _post(class_id, author_id, body="body"):
    post = ClassPost(class_id=class_id, author_id=author_id, body=body)
    post.id = uuid4()
    post.created_at = datetime.now(UTC)
    post.updated_at = datetime.now(UTC)
    return post


@pytest.fixture
def service(monkeypatch):
    session = MagicMock(spec=Session)
    result = FeedService(session)
    monkeypatch.setattr(
        identity_public,
        "get_users_summaries",
        lambda ids, *, session: {
            user_id: identity_public.UserSummaryDTO(
                id=user_id,
                email=None,
                username="student.login",
                display_name="Student",
                status="ACTIVE",
            )
            for user_id in ids
        },
    )
    return result, session


@pytest.mark.parametrize("body", ["", " \n\t", "x" * 10001])
def test_post_body_rejects_invalid_boundaries(body):
    with pytest.raises(ValidationError):
        PostCreateRequest(body=body)


@pytest.mark.parametrize("body", ["x", "x" * 10000])
def test_post_body_accepts_contract_boundaries(body):
    assert PostCreateRequest(body=body).body == body
    assert PostUpdateRequest(body=body).body == body


def test_create_post_uses_current_access_and_minimal_outbox(service, monkeypatch):
    feed, session = service
    user, class_id = _user(), uuid4()
    _access(monkeypatch)

    def create(post):
        created = _post(post.class_id, post.author_id, post.body)
        return created

    monkeypatch.setattr(feed.repository, "create_post", create)
    recorded = []
    monkeypatch.setattr(
        "app.modules.social.feed.service.record_outbox_event",
        lambda _session, **values: recorded.append(values),
    )
    response = feed.create_post(class_id, PostCreateRequest(body="hello"), user)
    assert response.author.model_dump() == {"id": user.id, "display_name": "Student"}
    assert recorded[0]["event_type"] == "SOCIAL_POST_CREATED"
    assert "body" not in recorded[0]["payload_json"]
    session.commit.assert_called_once()


def test_outbox_failure_rolls_back_post(service, monkeypatch):
    feed, session = service
    _access(monkeypatch)
    monkeypatch.setattr(
        feed.repository, "create_post", lambda post: _post(post.class_id, post.author_id)
    )
    monkeypatch.setattr(
        "app.modules.social.feed.service.record_outbox_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("outbox unavailable")),
    )
    with pytest.raises(RuntimeError):
        feed.create_post(uuid4(), PostCreateRequest(body="hello"), _user())
    session.rollback.assert_called_once()


def test_non_member_and_admin_cannot_read_feed(service, monkeypatch):
    feed, _ = service
    _access(monkeypatch, read=False, write=False)
    for user in (_user(), _user(role="ADMIN")):
        with pytest.raises(AppError) as denied:
            feed.list_posts(uuid4(), Pagination(limit=20, cursor=None), user)
        assert denied.value.status_code == 404


def test_archived_class_is_readable_but_rejects_writes(service, monkeypatch):
    feed, _ = service
    user, class_id = _user(), uuid4()
    _access(monkeypatch, archived=True, write=False)
    monkeypatch.setattr(feed.repository, "list_posts_by_class", lambda *args, **kwargs: [])
    assert feed.list_posts(class_id, Pagination(limit=20, cursor=None), user).items == []
    with pytest.raises(AppError) as denied:
        feed.create_post(class_id, PostCreateRequest(body="hello"), user)
    assert denied.value.status_code == 409


def test_author_must_retain_participation_to_update(service, monkeypatch):
    feed, _ = service
    user, class_id = _user(), uuid4()
    _access(monkeypatch, read=True, write=False)
    with pytest.raises(AppError) as denied:
        feed.update_post(class_id, uuid4(), PostUpdateRequest(body="new"), user)
    assert denied.value.status_code == 403


def test_moderator_delete_records_audit(service, monkeypatch):
    feed, session = service
    moderator, author, class_id = _user(role="LECTURER"), uuid4(), uuid4()
    post = _post(class_id, author)
    _access(monkeypatch, moderate=True)
    monkeypatch.setattr(feed.repository, "get_post_by_id", lambda *args, **kwargs: post)
    feed.delete_post(class_id, post.id, moderator, uuid4())
    assert post.deleted_at is not None
    assert any(
        getattr(call.args[0], "action", None) == "MODERATE_DELETE_POST"
        for call in session.add.call_args_list
    )


def test_author_delete_has_no_audit_and_other_student_is_forbidden(service, monkeypatch):
    feed, session = service
    author, other, class_id = _user(), _user(), uuid4()
    post = _post(class_id, author.id)
    _access(monkeypatch, moderate=False)
    monkeypatch.setattr(feed.repository, "get_post_by_id", lambda *args, **kwargs: post)
    with pytest.raises(AppError) as denied:
        feed.delete_post(class_id, post.id, other, uuid4())
    assert denied.value.status_code == 403
    feed.delete_post(class_id, post.id, author, uuid4())
    assert post.deleted_at is not None
    assert not any(
        getattr(call.args[0], "action", None) == "MODERATE_DELETE_POST"
        for call in session.add.call_args_list
    )


def test_admin_moderation_branch_does_not_require_read_access(service, monkeypatch):
    feed, session = service
    admin, class_id = _user(role="ADMIN"), uuid4()
    post = _post(class_id, uuid4())
    _access(monkeypatch, read=False, write=False, moderate=True)
    monkeypatch.setattr(feed.repository, "get_post_by_id", lambda *args, **kwargs: post)
    feed.delete_post(class_id, post.id, admin, uuid4())
    assert any(
        getattr(call.args[0], "action", None) == "MODERATE_DELETE_POST"
        for call in session.add.call_args_list
    )


def test_cross_class_post_is_hidden(service, monkeypatch):
    feed, _ = service
    user = _user()
    _access(monkeypatch)
    monkeypatch.setattr(
        feed.repository,
        "get_post_by_id",
        lambda *args, **kwargs: _post(uuid4(), user.id),
    )
    with pytest.raises(AppError) as hidden:
        feed.update_post(uuid4(), uuid4(), PostUpdateRequest(body="new"), user)
    assert hidden.value.status_code == 404
