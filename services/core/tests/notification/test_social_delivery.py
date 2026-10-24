"""Focused worker regressions without HTTP clients or an operational database."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.common.outbox import OutboxEvent
from app.modules.notification import events
from app.modules.social.comments import public


@pytest.fixture
def delivery(monkeypatch):
    school, klass, post_id, comment_id, author, recipient = (uuid4() for _ in range(6))
    event = OutboxEvent(
        id=uuid4(),
        event_type="SOCIAL_COMMENT_CREATED",
        schema_version=2,
        aggregate_id=str(comment_id),
        payload_json={
            "class_id": str(klass),
            "post_id": str(post_id),
            "comment_id": str(comment_id),
            "author_id": str(author),
            "post_author_id": str(recipient),
            "recipient_ids": [str(recipient), str(author)],
        },
    )
    monkeypatch.setattr(
        events,
        "get_notification_audience",
        lambda *a, **k: SimpleNamespace(school_id=school, recipient_ids=[recipient]),
    )
    monkeypatch.setattr(
        events, "get_visible_post_ref", lambda *a, **k: SimpleNamespace(author_id=recipient)
    )
    monkeypatch.setattr(
        events, "get_visible_comment_ref", lambda *a, **k: SimpleNamespace(author_id=author)
    )
    monkeypatch.setattr(
        events,
        "get_users_summaries",
        lambda *a, **k: {recipient: SimpleNamespace(school_id=school)},
    )
    monkeypatch.setattr(events, "check_class_action", lambda *a, **k: SimpleNamespace(allowed=True))
    return event, recipient


def test_comment_delivery_only_to_current_post_author(delivery):
    event, recipient = delivery
    recipients, payload = events.prepare_delivery(MagicMock(), event)
    assert recipients == [recipient]
    assert payload["comment_id"] == event.aggregate_id
    assert "recipient_ids" not in payload and "post_author_id" not in payload


@pytest.mark.parametrize("missing", ["post", "comment"])
def test_deleted_content_is_not_delivered(delivery, monkeypatch, missing):
    event, _ = delivery
    monkeypatch.setattr(events, f"get_visible_{missing}_ref", lambda *a, **k: None)
    assert events.prepare_delivery(MagicMock(), event) == ([], {})


@pytest.mark.parametrize("field", ["author_id", "post_author_id"])
def test_mismatched_comment_authors_fail_closed(delivery, field):
    event, _ = delivery
    event.payload_json[field] = str(uuid4())
    with pytest.raises(events.InvalidEvent):
        events.prepare_delivery(MagicMock(), event)


def test_current_permission_is_checked_at_delivery(delivery, monkeypatch):
    event, _ = delivery
    monkeypatch.setattr(
        events, "check_class_action", lambda *a, **k: SimpleNamespace(allowed=False)
    )
    assert events.prepare_delivery(MagicMock(), event)[0] == []


@pytest.mark.parametrize("same_post", [True, False, None])
def test_public_comment_reference_is_scoped_and_does_not_commit(monkeypatch, same_post):
    post, comment, author = uuid4(), uuid4(), uuid4()
    row = (
        None
        if same_post is None
        else SimpleNamespace(id=comment, post_id=post if same_post else uuid4(), author_id=author)
    )
    repo = MagicMock()
    repo.get.return_value = row
    monkeypatch.setattr(public, "CommentsRepository", lambda session: repo)
    session = MagicMock()
    result = public.get_visible_comment_ref(post, comment, session=session)
    assert (result is not None) is (same_post is True)
    if result is not None:
        assert result.model_dump() == {"id": comment, "post_id": post, "author_id": author}
    session.commit.assert_not_called()
