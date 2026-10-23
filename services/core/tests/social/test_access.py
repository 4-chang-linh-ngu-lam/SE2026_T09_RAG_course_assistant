from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.errors import AppError
from app.modules.classroom import public as classroom_public
from app.modules.classroom.models import ClassStatus
from app.modules.classroom.schemas import ClassAccessDTO
from app.modules.social import access
from app.modules.social.calendar import service as calendar_service
from app.modules.social.calendar.schemas import (
    CalendarEventCreateRequest,
    CalendarEventUpdateRequest,
)
from app.modules.social.comments import service as comments_service
from app.modules.social.comments.schemas import CommentCreateRequest, CommentUpdateRequest
from app.modules.social.feed import service as feed_service
from app.modules.social.feed.schemas import PostCreateRequest, PostUpdateRequest


@pytest.mark.parametrize(
    "operation",
    [
        "create_post",
        "update_post",
        "delete_post",
        "create_comment",
        "update_comment",
        "delete_comment",
        "create_event",
        "update_event",
        "delete_event",
    ],
)
def test_social_writes_lock_class_inside_transaction(monkeypatch, operation):
    session = MagicMock(spec=Session)
    user = CurrentUser(id=uuid4(), status="ACTIVE", session_version=1, roles=["LECTURER"])
    class_id, post_id, comment_id, event_id = (uuid4() for _ in range(4))
    now = datetime.now(UTC)
    in_transaction = False
    lock_checks = 0

    @contextmanager
    def tracked_transaction(_session):
        nonlocal in_transaction
        assert _session is session
        in_transaction = True
        try:
            yield _session
        finally:
            in_transaction = False

    class Checked(Exception):
        pass

    def check_class_action(_class_id, _user_id, _action, *, session, lock=False):
        nonlocal lock_checks
        assert session is not None
        assert in_transaction
        assert lock is True
        lock_checks += 1
        raise Checked

    monkeypatch.setattr(classroom_public, "check_class_action", check_class_action)
    for module in (feed_service, comments_service, calendar_service):
        monkeypatch.setattr(module, "transaction", tracked_transaction)

    feed = feed_service.FeedService(session)
    comments = comments_service.CommentsService(session)
    calendar = calendar_service.CalendarService(session)
    operations = {
        "create_post": lambda: feed.create_post(class_id, PostCreateRequest(body="post"), user),
        "update_post": lambda: feed.update_post(
            class_id, post_id, PostUpdateRequest(body="post"), user
        ),
        "delete_post": lambda: feed.delete_post(class_id, post_id, user, uuid4()),
        "create_comment": lambda: comments.create_comment(
            class_id, post_id, CommentCreateRequest(body="comment"), user
        ),
        "update_comment": lambda: comments.update_comment(
            class_id, post_id, comment_id, CommentUpdateRequest(body="comment"), user
        ),
        "delete_comment": lambda: comments.delete_comment(
            class_id, post_id, comment_id, user, uuid4()
        ),
        "create_event": lambda: calendar.create_event(
            class_id,
            CalendarEventCreateRequest(
                title="Event", starts_at=now, ends_at=now + timedelta(hours=1)
            ),
            user,
        ),
        "update_event": lambda: calendar.update_event(
            class_id, event_id, CalendarEventUpdateRequest(title="Event"), user
        ),
        "delete_event": lambda: calendar.delete_event(class_id, event_id, user),
    }

    with pytest.raises(Checked):
        operations[operation]()
    assert lock_checks == 1
    assert not in_transaction


@pytest.mark.parametrize(
    ("role", "class_status", "expected_status"),
    [
        ("ADMIN", ClassStatus.ARCHIVED, 409),
        ("ADMIN", None, 404),
        ("STUDENT", ClassStatus.ARCHIVED, 404),
    ],
)
def test_delete_access_uses_scoped_archived_status(
    monkeypatch, role, class_status, expected_status
):
    class_id = uuid4()
    user = CurrentUser(id=uuid4(), status="ACTIVE", session_version=1, roles=[role])

    def check_class_action(_class_id, _user_id, _action, *, session, lock=False):
        if lock:
            assert _action == classroom_public.ClassAccessAction.READ_CLASS_CONTENT
        return ClassAccessDTO(allowed=False, class_id=class_id, class_status=class_status)

    monkeypatch.setattr(classroom_public, "check_class_action", check_class_action)
    with pytest.raises(AppError) as denied:
        access.get_delete_access(MagicMock(spec=Session), class_id, user)
    assert denied.value.status_code == expected_status
