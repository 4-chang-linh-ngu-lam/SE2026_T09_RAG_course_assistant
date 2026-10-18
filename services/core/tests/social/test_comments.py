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
from app.modules.social.comments.models import PostComment
from app.modules.social.comments.schemas import CommentCreateRequest, CommentUpdateRequest
from app.modules.social.comments.service import CommentsService
from app.modules.social.feed import public as feed_public


def _user(user_id=None, role="STUDENT"):
    return CurrentUser(id=user_id or uuid4(), status="ACTIVE", session_version=1, roles=[role])


def _access(monkeypatch, *, read=True, write=True, moderate=False, archived=False):
    def check(_class_id, _user_id, action, *, session):
        action = str(action)
        allowed = read if action == "read_class_content" else write
        if action == "moderate_class_content":
            allowed = moderate
        return SimpleNamespace(
            allowed=allowed,
            class_status="ARCHIVED" if archived and read else "ACTIVE",
        )

    monkeypatch.setattr(classroom_public, "check_class_action", check)


def _comment(post_id, author_id):
    comment = PostComment(post_id=post_id, author_id=author_id, body="comment")
    comment.id = uuid4()
    comment.created_at = datetime.now(UTC)
    comment.updated_at = datetime.now(UTC)
    return comment


@pytest.fixture
def service(monkeypatch):
    session = MagicMock(spec=Session)
    comments = CommentsService(session)
    monkeypatch.setattr(
        identity_public,
        "get_users_summaries",
        lambda ids, *, session: {
            user_id: identity_public.UserSummaryDTO(
                id=user_id, email=None, username="student", status="ACTIVE"
            )
            for user_id in ids
        },
    )
    return comments, session


@pytest.mark.parametrize("body", ["", "   ", "x" * 10001])
def test_comment_body_rejects_invalid_values(body):
    with pytest.raises(ValidationError):
        CommentCreateRequest(body=body)


@pytest.mark.parametrize("body", ["x", "x" * 10000])
def test_comment_body_accepts_boundaries(body):
    assert CommentUpdateRequest(body=body).body == body


def test_deleted_or_cross_class_post_blocks_comment_routes(service, monkeypatch):
    comments, _ = service
    user, class_id, post_id = _user(), uuid4(), uuid4()
    _access(monkeypatch)
    monkeypatch.setattr(feed_public, "get_visible_post_ref", lambda *args, **kwargs: None)
    with pytest.raises(AppError) as hidden:
        comments.list_comments(class_id, post_id, Pagination(limit=20, cursor=None), user)
    assert hidden.value.status_code == 404
    with pytest.raises(AppError):
        comments.create_comment(class_id, post_id, CommentCreateRequest(body="comment"), user)


def test_create_comment_emits_minimal_outbox_for_other_author(service, monkeypatch):
    comments, _ = service
    user, class_id, post_id, post_author = _user(), uuid4(), uuid4(), uuid4()
    _access(monkeypatch)
    monkeypatch.setattr(
        feed_public,
        "get_visible_post_ref",
        lambda *args, **kwargs: feed_public.PostRefDTO(
            id=post_id, class_id=class_id, author_id=post_author
        ),
    )
    monkeypatch.setattr(
        comments.repository,
        "create",
        lambda value: _comment(value.post_id, value.author_id),
    )
    recorded = []
    monkeypatch.setattr(
        "app.modules.social.comments.service.record_outbox_event",
        lambda _session, **values: recorded.append(values),
    )
    comments.create_comment(class_id, post_id, CommentCreateRequest(body="comment"), user)
    assert len(recorded) == 1
    assert recorded[0]["event_type"] == "SOCIAL_COMMENT_CREATED"
    assert "body" not in recorded[0]["payload_json"]


def test_comment_outbox_failure_rolls_back(service, monkeypatch):
    comments, session = service
    user, class_id, post_id = _user(), uuid4(), uuid4()
    _access(monkeypatch)
    monkeypatch.setattr(
        feed_public,
        "get_visible_post_ref",
        lambda *args, **kwargs: feed_public.PostRefDTO(
            id=post_id, class_id=class_id, author_id=uuid4()
        ),
    )
    monkeypatch.setattr(
        comments.repository,
        "create",
        lambda value: _comment(value.post_id, value.author_id),
    )
    monkeypatch.setattr(
        "app.modules.social.comments.service.record_outbox_event",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("outbox unavailable")),
    )
    with pytest.raises(RuntimeError):
        comments.create_comment(class_id, post_id, CommentCreateRequest(body="comment"), user)
    session.rollback.assert_called_once()


def test_cross_post_comment_is_hidden(service, monkeypatch):
    comments, _ = service
    user, class_id, post_id = _user(), uuid4(), uuid4()
    _access(monkeypatch)
    monkeypatch.setattr(
        feed_public,
        "get_visible_post_ref",
        lambda *args, **kwargs: feed_public.PostRefDTO(
            id=post_id, class_id=class_id, author_id=user.id
        ),
    )
    monkeypatch.setattr(
        comments.repository,
        "get",
        lambda *args, **kwargs: _comment(uuid4(), user.id),
    )
    with pytest.raises(AppError) as hidden:
        comments.update_comment(
            class_id,
            post_id,
            uuid4(),
            CommentUpdateRequest(body="new"),
            user,
        )
    assert hidden.value.status_code == 404


def test_archived_comment_write_returns_conflict(service, monkeypatch):
    comments, _ = service
    _access(monkeypatch, archived=True, write=False)
    with pytest.raises(AppError) as denied:
        comments.create_comment(uuid4(), uuid4(), CommentCreateRequest(body="comment"), _user())
    assert denied.value.status_code == 409


def test_comment_moderation_records_audit(service, monkeypatch):
    comments, session = service
    moderator, class_id, post_id = _user(role="LECTURER"), uuid4(), uuid4()
    comment = _comment(post_id, uuid4())
    _access(monkeypatch, moderate=True)
    monkeypatch.setattr(
        feed_public,
        "get_visible_post_ref",
        lambda *args, **kwargs: feed_public.PostRefDTO(
            id=post_id, class_id=class_id, author_id=uuid4()
        ),
    )
    monkeypatch.setattr(comments.repository, "get", lambda *args, **kwargs: comment)
    comments.delete_comment(class_id, post_id, comment.id, moderator, uuid4())
    assert comment.deleted_at is not None
    assert any(
        getattr(call.args[0], "action", None) == "MODERATE_DELETE_COMMENT"
        for call in session.add.call_args_list
    )


@pytest.mark.parametrize("operation", ["create", "update", "delete"])
def test_comment_mutations_lock_parent_post_inside_transaction(monkeypatch, operation):
    session = MagicMock(spec=Session)
    service = CommentsService(session)
    user, class_id, post_id = _user(), uuid4(), uuid4()
    _access(monkeypatch)
    calls = []

    def visible(_class_id, _post_id, *, session, for_update=False):
        calls.append(for_update)

    monkeypatch.setattr(feed_public, "get_visible_post_ref", visible)
    with pytest.raises(AppError) as missing:
        if operation == "create":
            service.create_comment(class_id, post_id, CommentCreateRequest(body="x"), user)
        elif operation == "update":
            service.update_comment(class_id, post_id, uuid4(), CommentUpdateRequest(body="x"), user)
        else:
            service.delete_comment(class_id, post_id, uuid4(), user, uuid4())
    assert missing.value.status_code == 404
    assert calls == [True]
