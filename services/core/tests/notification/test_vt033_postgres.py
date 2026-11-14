"""VT-033 business outcomes with committed PostgreSQL and real Identity lookup."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.bootstrap import register_routers
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.common.pagination import encode_cursor
from app.common.security import create_access_token
from app.modules.classroom.models import School
from app.modules.identity.models import Role, RoleAssignment, User, UserStatus
from app.modules.notification.models import Notification
from app.modules.notification.repository import NotificationRepository

from . import test_postgres

database = test_postgres.database  # reuse only fixture; no duplicate tests


class SyntheticInbox(SimpleNamespace):
    def __repr__(self):
        return "SyntheticInbox(3 users, 106 notifications; credentials omitted)"


@pytest.fixture
def inbox(database, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr("vt033-test-signing-" + "x" * 40))
    with database.factory.begin() as session:
        school = School(id=uuid4(), name="VT033 synthetic school")
        session.add(school)
        session.flush()
        ids = [uuid4(), uuid4(), uuid4()]
        session.add_all(
            User(
                id=user_id,
                school_id=school.id,
                username="vt033." + user_id.hex,
                password_hash="unusable-fixture-" + uuid4().hex,
                status=UserStatus.ACTIVE,
                activated_at=datetime.now(UTC),
            )
            for user_id in ids
        )
        session.flush()
        session.add_all(RoleAssignment(user_id=user_id, role=Role.STUDENT) for user_id in ids)
        own, other = [], []
        # Interleave recipients so accidental unfiltered list queries are observable.
        for index in range(103):
            row = Notification(
                id=uuid4(),
                recipient_id=ids[0],
                type="CLASS_STATUS_CHANGED",
                payload_json={"version": index + 1},
                dedup_key=uuid4().hex,
                read_at=datetime(2026, 1, 1, tzinfo=UTC) if index == 0 else None,
            )
            session.add(row)
            session.flush()
            own.append(row.id)
            if index in (0, 50, 102):
                row = Notification(
                    id=uuid4(),
                    recipient_id=ids[1],
                    type="CLASS_STATUS_CHANGED",
                    payload_json={"version": 900 + index},
                    dedup_key=uuid4().hex,
                )
                session.add(row)
                session.flush()
                other.append(row.id)
    app = FastAPI()
    register_error_handlers(app)
    register_routers(app)

    def db():
        with database.factory() as session:
            yield session

    app.dependency_overrides[get_db] = db
    headers = [
        {"Authorization": "Bearer " + create_access_token(user_id, ["STUDENT"], 1)}
        for user_id in ids
    ]
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SyntheticInbox(
            client=client,
            factory=database.factory,
            users=ids,
            own=list(reversed(own)),
            other=list(reversed(other)),
            headers=headers,
        )


def state(inbox):
    with inbox.factory() as session:
        return dict(session.execute(select(Notification.id, Notification.read_at)).all())


def check_page(inbox, response, expected, unread=102, has_more=True):
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {"items", "unread_count", "next_cursor"}
    assert [row["id"] for row in body["items"]] == [str(value) for value in expected]
    assert not set(expected) & set(inbox.other)
    assert body["unread_count"] == unread
    assert body["next_cursor"] == (encode_cursor(expected[-1]) if has_more else None)
    with inbox.factory() as session:
        for item in body["items"]:
            row = session.get(Notification, UUID(item["id"]))
            assert row.recipient_id == inbox.users[0]
            assert item["type"] == row.type
            assert item["payload_json"] == row.payload_json
            assert item["read"] == (row.read_at is not None)
            assert datetime.fromisoformat(item["created_at"]) == row.created_at
    return body


@pytest.mark.parametrize("default", [1, 2, 100])
def test_configured_inbox_business_outcome(inbox, monkeypatch, default):
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", default)
    before = state(inbox)
    first = check_page(
        inbox,
        inbox.client.get("/api/v1/notifications", headers=inbox.headers[0]),
        inbox.own[:default],
    )
    expected = inbox.own[default : default * 2]
    second = check_page(
        inbox,
        inbox.client.get(
            "/api/v1/notifications",
            params={"cursor": first["next_cursor"]},
            headers=inbox.headers[0],
        ),
        expected,
        has_more=len(inbox.own) > default * 2,
    )
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}
    assert state(inbox) == before


@pytest.mark.parametrize("limit", [1, 2, 99, 100])
def test_explicit_limit_business_outcome(inbox, monkeypatch, limit):
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", 2)
    before = state(inbox)
    check_page(
        inbox,
        inbox.client.get(
            "/api/v1/notifications",
            params={"limit": limit},
            headers=inbox.headers[0],
        ),
        inbox.own[:limit],
    )
    assert state(inbox) == before


def test_foreign_cursor_does_not_change_state(inbox, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", 2)
    before = state(inbox)
    response = inbox.client.get(
        "/api/v1/notifications",
        params={"cursor": encode_cursor(inbox.other[0])},
        headers=inbox.headers[0],
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
    assert state(inbox) == before


@pytest.mark.parametrize("default", [1, 2, 100])
def test_cross_recipient_mark_read_preserves_business_state(inbox, monkeypatch, default):
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", default)
    before = state(inbox)
    response = inbox.client.patch(
        f"/api/v1/notifications/{inbox.other[0]}/read",
        headers=inbox.headers[0],
    )
    # Mutation oracle is persisted business state, before any HTTP assertion.
    assert state(inbox) == before, "cross-recipient mark-read changed persisted read_at"
    assert state(inbox)[inbox.other[0]] is None
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_own_read_and_read_all_preserve_other_inbox(inbox):
    own_id = inbox.own[0]
    for _ in range(2):
        response = inbox.client.patch(
            f"/api/v1/notifications/{own_id}/read",
            headers=inbox.headers[0],
        )
        assert response.json() == {"id": str(own_id), "read": True}
        assert response.status_code == 200
        current = state(inbox)[own_id]
        assert current is not None
        if _ == 0:
            first_read = current
        assert current == first_read
    assert (
        inbox.client.get("/api/v1/notifications", headers=inbox.headers[0]).json()["unread_count"]
        == 101
    )
    response = inbox.client.post("/api/v1/notifications/read-all", headers=inbox.headers[0])
    assert response.status_code == 204 and response.content == b""
    final = state(inbox)
    assert all(final[value] is not None for value in inbox.own)
    assert all(final[value] is None for value in inbox.other)
    assert (
        inbox.client.get("/api/v1/notifications", headers=inbox.headers[0]).json()["unread_count"]
        == 0
    )


def test_locked_user_cannot_read_inbox(inbox):
    before = state(inbox)
    with inbox.factory.begin() as session:
        session.get(User, inbox.users[0]).status = UserStatus.LOCKED
    response = inbox.client.get("/api/v1/notifications", headers=inbox.headers[0])
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"
    assert state(inbox) == before


def test_list_failure_rolls_back_and_recovers(inbox, monkeypatch):
    before = state(inbox)
    original = NotificationRepository.unread_count

    def fail(self, user_id):
        # An actual server-side SQL error aborts the current PostgreSQL transaction.
        self.session.connection().exec_driver_sql("SELECT 1 / 0")

    monkeypatch.setattr(NotificationRepository, "unread_count", fail)
    response = inbox.client.get("/api/v1/notifications", headers=inbox.headers[0])
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "division" not in response.text.lower()
    assert state(inbox) == before
    monkeypatch.setattr(NotificationRepository, "unread_count", original)
    check_page(
        inbox,
        inbox.client.get("/api/v1/notifications", headers=inbox.headers[0]),
        inbox.own[:20],
    )


def test_baseline_default_and_empty_inbox(inbox):
    check_page(
        inbox,
        inbox.client.get("/api/v1/notifications", headers=inbox.headers[0]),
        inbox.own[:20],
    )
    response = inbox.client.get("/api/v1/notifications", headers=inbox.headers[2])
    assert response.json() == {"items": [], "unread_count": 0, "next_cursor": None}
    assert response.status_code == 200
