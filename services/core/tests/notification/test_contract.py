import ast
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.errors import AppError
from app.common.outbox import OutboxEvent, record_outbox_event
from app.common.pagination import Pagination
from app.main import app
from app.modules.classroom.schemas import NotificationAudienceDTO
from app.modules.notification import events, public
from app.modules.notification.router import get_notification_service
from app.modules.notification.schemas import MarkReadResponse, NotificationListResponse


def test_notification_openapi_and_authentication():
    paths = app.openapi()["paths"]
    actual = {path: set(value) for path, value in paths.items() if "/notifications" in path}
    assert actual == {
        "/api/v1/notifications": {"get"},
        "/api/v1/notifications/{id}/read": {"patch"},
        "/api/v1/notifications/read-all": {"post"},
    }
    assert "content" not in paths["/api/v1/notifications/read-all"]["post"]["responses"]["204"]
    with TestClient(app) as client:
        for method, path in (
            ("get", "/api/v1/notifications"),
            ("patch", f"/api/v1/notifications/{uuid4()}/read"),
            ("post", "/api/v1/notifications/read-all"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_routes_use_authenticated_user_and_no_store():
    actor = CurrentUser(id=uuid4(), status="ACTIVE", roles=["STUDENT"], session_version=1)
    service = MagicMock()
    service.list_notifications.return_value = NotificationListResponse(items=[], unread_count=0)
    notification_id = uuid4()
    service.mark_as_read.return_value = MarkReadResponse(id=notification_id, read=True)
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_notification_service] = lambda: service
    try:
        with TestClient(app) as client:
            response = client.get(f"/api/v1/notifications?user_id={uuid4()}")
            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "no-store"
            service.list_notifications.assert_called_once_with(
                actor.id, Pagination(limit=20, cursor=None)
            )
            assert client.patch(f"/api/v1/notifications/{notification_id}/read").json() == {
                "id": str(notification_id),
                "read": True,
            }
            service.mark_as_read.assert_called_once_with(notification_id, actor.id)
            result = client.post("/api/v1/notifications/read-all")
            assert result.status_code == 204 and result.content == b""
            assert result.headers["Cache-Control"] == "no-store"
            service.mark_all_as_read.assert_called_once_with(actor.id)
            for query in ("limit=0", "limit=101", "cursor=invalid"):
                assert client.get(f"/api/v1/notifications?{query}").status_code in (400, 422)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_public_snapshot_is_dto_only_and_does_not_commit(monkeypatch):
    session = MagicMock()
    audience = NotificationAudienceDTO(school_id=uuid4(), recipient_ids=[uuid4()])
    monkeypatch.setattr(public, "get_notification_audience", lambda *args, **kwargs: audience)
    assert public.snapshot_audience(session, uuid4()) == audience.model_dump(mode="json")
    session.commit.assert_not_called()
    monkeypatch.setattr(public, "get_notification_audience", lambda *args, **kwargs: None)
    with pytest.raises(AppError) as failure:
        public.snapshot_audience(session, uuid4())
    assert failure.value.status_code == 503


def test_common_enqueue_assigns_stable_id_and_keeps_transaction_with_caller():
    session = MagicMock()
    event = record_outbox_event(
        session,
        event_type="CLASS_STATUS_CHANGED",
        aggregate_id=uuid4(),
        payload_json={"version": 3},
    )
    assert event.id is not None and event.schema_version == 2 and event.aggregate_version == 3
    session.add.assert_called_once_with(event)
    session.commit.assert_not_called()


@pytest.fixture
def delivery(monkeypatch):
    school, klass, student, outsider = (uuid4() for _ in range(4))
    monkeypatch.setattr(
        events,
        "get_notification_audience",
        lambda *args, **kwargs: NotificationAudienceDTO(
            school_id=school, recipient_ids=[student, outsider]
        ),
    )
    monkeypatch.setattr(
        events,
        "get_users_summaries",
        lambda *args, **kwargs: {
            student: SimpleNamespace(school_id=school),
            outsider: SimpleNamespace(school_id=uuid4()),
        },
    )
    event = OutboxEvent(
        id=uuid4(),
        event_type="CLASS_STATUS_CHANGED",
        aggregate_id=str(klass),
        schema_version=2,
        aggregate_version=2,
        payload_json={"class_id": str(klass), "version": 2, "status": "ARCHIVED"},
    )
    return event, student


def test_dispatch_filters_cross_school_and_excludes_private_fields(delivery):
    event, student = delivery
    recipients, safe = events.prepare_delivery(MagicMock(), event)
    assert recipients == [student]
    assert safe == {
        "class_id": event.aggregate_id,
        "version": 2,
        "status": "ARCHIVED",
        "event_id": str(event.id),
        "schema_version": 2,
    }


@pytest.mark.parametrize("change", ["secret", "aggregate", "school", "version", "envelope"])
def test_dispatch_fails_closed_for_malformed_events(delivery, change):
    event, _ = delivery
    if change == "secret":
        event.payload_json["token"] = "test-only-value-never-exposed"
    elif change == "aggregate":
        event.aggregate_id = str(uuid4())
    elif change == "school":
        event.payload_json["school_id"] = str(uuid4())
    elif change == "version":
        event.aggregate_version = 5
    else:
        event.schema_version = 1
    with pytest.raises((events.InvalidEvent, ValidationError)):
        events.prepare_delivery(MagicMock(), event)


def test_dedup_is_recipient_scoped_and_version_replay_safe(delivery):
    event, student = delivery
    first = events.dedup_key(event, student)
    event.id = uuid4()
    assert events.dedup_key(event, student) == first
    assert events.dedup_key(event, uuid4()) != first
    event.aggregate_version = 3
    assert events.dedup_key(event, student) != first


def test_unversioned_dedup_reuses_event_uuid(delivery):
    event, student = delivery
    event.aggregate_version = None
    event.payload_json = {}
    key = events.dedup_key(event, student)
    assert events.dedup_key(event, student) == key
    event.id = uuid4()
    assert events.dedup_key(event, student) != key


def test_notification_uses_only_other_modules_public_interfaces():
    root = Path(__file__).resolve().parents[2] / "app/modules/notification"
    for source in root.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("app.modules.")
            ):
                assert node.module.startswith("app.modules.notification.") or node.module.endswith(
                    ".public"
                ), source


def test_aware_transfer_timestamp_required():
    with pytest.raises(ValidationError):
        events.StudentTransferred(
            class_id=uuid4(),
            destination_class_id=uuid4(),
            student_id=uuid4(),
            effective_at=datetime.now().isoformat(),
        )
    assert (
        events.StudentTransferred(
            class_id=uuid4(),
            destination_class_id=uuid4(),
            student_id=uuid4(),
            effective_at=datetime.now(UTC),
        ).effective_at.tzinfo
        is not None
    )
