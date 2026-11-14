import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select, update

from app.common.outbox import OutboxEvent
from app.modules.notification.models import Notification
from app.modules.notification.repository import NotificationRepository
from app.modules.notification.worker import drain_outbox
from app.modules.social.feed.models import ClassPost
from app.modules.social.feed.schemas import PostCreateRequest, PostUpdateRequest
from app.modules.social.feed.service import FeedService
from tests.vt034.conftest import headers
from tests.vt034.pairwise import CASES

EVENT = "SOCIAL_POST_UPDATED"


def make_post(system):
    post = FeedService(system.session).create_post(
        system.class_id, PostCreateRequest(body="original"), system.users["teacher"]
    )
    with system.factory.begin() as db:
        db.execute(delete(Notification))
        db.execute(delete(OutboxEvent))
    return post


def edit(system, post, body):
    return FeedService(system.session).update_post(
        system.class_id, post.id, PostUpdateRequest(body=body), system.users["teacher"]
    )


def update_events(system):
    with system.factory() as db:
        return list(db.scalars(select(OutboxEvent).where(OutboxEvent.event_type == EVENT)))


def inbox(system):
    with system.factory() as db:
        return list(db.scalars(select(Notification).where(Notification.type == EVENT)))


def body_in_db(system, post):
    with system.factory() as db:
        return db.get(ClassPost, post.id).body


def due(system):
    with system.factory.begin() as db:
        db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.event_type == EVENT, OutboxEvent.published_at.is_(None))
            .values(available_at=func.clock_timestamp() - timedelta(seconds=1))
        )


def fail_delivery(monkeypatch):
    original = NotificationRepository.create

    def create(self, **kwargs):
        if kwargs["event_type"] == EVENT:
            raise RuntimeError("vt034-private-body-must-not-be-logged")
        return original(self, **kwargs)

    monkeypatch.setattr(NotificationRepository, "create", create)


def test_tc07_commit_and_minimal_payload(system):
    post = make_post(system)
    edit(system, post, "đ" * 10000)
    assert body_in_db(system, post) == "đ" * 10000
    events = update_events(system)
    assert len(events) == 1
    assert events[0].aggregate_id == str(post.id)
    payload = events[0].payload_json
    assert set(payload) == {"class_id", "post_id", "author_id", "school_id", "recipient_ids"}
    assert payload["author_id"] == str(system.users["teacher"].id)
    assert payload["post_id"] == str(post.id)
    assert "đ" * 10 not in json.dumps(payload, ensure_ascii=False)
    assert len(json.dumps(payload)) < 1500  # This fixture: 3 class members, not a global limit.


def test_tc08_identical_body_is_noop(system):
    post = make_post(system)
    edit(system, post, "original")
    assert update_events(system) == []
    assert body_in_db(system, post) == "original"


def test_tc09_enqueue_failure_rolls_back_edit(system, monkeypatch):
    post = make_post(system)

    def unavailable(*args, **kwargs):
        raise RuntimeError("synthetic outbox failure")

    monkeypatch.setattr("app.modules.social.feed.service.record_outbox_event", unavailable)
    with pytest.raises(RuntimeError, match="synthetic outbox failure"):
        edit(system, post, "changed")
    assert body_in_db(system, post) == "original"
    assert update_events(system) == []


def test_tc10_delivery_failure_retry_replay_preserves_large_edit(system, monkeypatch, caplog):
    post = make_post(system)
    edit(system, post, "x" * 10000)
    assert len(update_events(system)) == 1
    with monkeypatch.context() as failure:
        fail_delivery(failure)
        due(system)
        assert drain_outbox(session_factory=system.factory, batch_size=1) == 0
    failed = update_events(system)[0]
    assert failed.attempts == 1 and failed.last_error_code == "DELIVERY_FAILED"
    assert failed.published_at is None and inbox(system) == []
    assert body_in_db(system, post) == "x" * 10000
    assert "vt034-private-body" not in caplog.text
    due(system)  # deterministic scheduling; never sleep until backoff elapses
    assert drain_outbox(session_factory=system.factory, batch_size=1) == 1
    rows = inbox(system)
    assert {row.recipient_id for row in rows} == {
        system.users["student"].id,
        system.users["student2"].id,
    }
    with system.factory.begin() as db:
        db.execute(update(OutboxEvent).where(OutboxEvent.id == failed.id).values(published_at=None))
    due(system)
    assert drain_outbox(session_factory=system.factory, batch_size=1) == 1
    assert len(inbox(system)) == 2


@pytest.mark.parametrize("removed", ["student", "source"])
def test_tc11_current_access_and_deleted_source(system, removed):
    post = make_post(system)
    edit(system, post, "changed")
    if removed == "student":
        system.classroom.end_member(
            system.class_id, system.users["admin"], system.users["student"].id
        )
    else:
        with system.factory.begin() as db:
            db.execute(
                update(ClassPost).where(ClassPost.id == post.id).values(deleted_at=func.now())
            )
    due(system)
    drain_outbox(session_factory=system.factory)
    assert {row.recipient_id for row in inbox(system)} == (
        {system.users["student2"].id} if removed == "student" else set()
    )


@pytest.mark.parametrize("length,actor,state,delivery", CASES)
def test_tc12_pairwise_http(system, client, monkeypatch, length, actor, state, delivery):
    post = make_post(system)
    if state == "ARCHIVED":
        system.classroom.set_archived(system.class_id, system.users["admin"], archived=True)
    with system.factory.begin() as db:
        db.execute(delete(OutboxEvent))
    response = client.patch(
        f"/api/v1/classes/{system.class_id}/posts/{post.id}",
        headers=headers(system.users[actor]),
        json={"body": "x" * length},
    )
    expected = (
        422
        if length > 10000
        else 404
        if actor == "outsider"
        else 409
        if state == "ARCHIVED"
        else 403
        if actor == "student"
        else 200
    )
    assert response.status_code == expected, response.text
    events = update_events(system)
    assert len(events) == (1 if expected == 200 else 0)
    if expected != 200:
        assert body_in_db(system, post) == "original"
        return  # delivery factor is masked when validation/permission rejects the operation
    assert body_in_db(system, post) == "x" * length
    if delivery == "fail":
        fail_delivery(monkeypatch)
    due(system)
    delivered = drain_outbox(session_factory=system.factory, batch_size=1)
    assert delivered == (1 if delivery == "ok" else 0)
    assert len(inbox(system)) == (2 if delivery == "ok" else 0)


def test_tc13_backend_journey_patch_worker_inbox_read(system, client):
    post = make_post(system)
    response = client.patch(
        f"/api/v1/classes/{system.class_id}/posts/{post.id}",
        headers=headers(system.users["teacher"]),
        json={"body": "corrected"},
    )
    assert response.status_code == 200 and response.json()["body"] == "corrected"
    due(system)
    assert drain_outbox(session_factory=system.factory) == 1
    auth = headers(system.users["student"])
    result = client.get("/api/v1/notifications", headers=auth)
    assert result.status_code == 200
    items = [item for item in result.json()["items"] if item["type"] == EVENT]
    assert len(items) == 1 and items[0]["payload_json"]["post_id"] == str(post.id)
    assert "body" not in items[0]["payload_json"]
    assert (
        client.patch(f"/api/v1/notifications/{items[0]['id']}/read", headers=auth).status_code
        == 200
    )
    listing = client.get(f"/api/v1/classes/{system.class_id}/posts", headers=auth)
    assert listing.status_code == 200
    assert any(
        item["id"] == str(post.id) and item["body"] == "corrected"
        for item in listing.json()["items"]
    )


def test_tc15_two_workers_deliver_each_event_once(system):
    post = make_post(system)
    for i in range(5):
        edit(system, post, f"correction-{i}")
    due(system)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: drain_outbox(session_factory=system.factory, batch_size=10), range(2)
            )
        )
    assert sum(results) == 5
    rows = inbox(system)
    assert len(rows) == 10 and len({row.dedup_key for row in rows}) == 10
    assert body_in_db(system, post) == "correction-4"
