"""VT-033 Settings/query boundaries; service doubles prove routing only."""

import os
import subprocess
import sys
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.config import Settings, settings
from app.common.errors import register_error_handlers
from app.common.pagination import Page, Pagination
from app.modules.classroom.router import get_classroom_service
from app.modules.classroom.router import router as classroom_router
from app.modules.notification.router import get_notification_service, router
from app.modules.notification.schemas import NotificationListResponse


@pytest.fixture
def api():
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)
    app.include_router(classroom_router)
    actor = CurrentUser(id=uuid4(), status="ACTIVE", roles=["STUDENT"], session_version=1)
    notifications = MagicMock()
    notifications.list_notifications.return_value = NotificationListResponse(
        items=[], unread_count=0
    )
    classroom = MagicMock()
    classroom.list_classes.return_value = Page(items=[])
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_notification_service] = lambda: notifications
    app.dependency_overrides[get_classroom_service] = lambda: classroom
    with TestClient(app) as client:
        yield client, actor, notifications, classroom


def test_settings_default(monkeypatch):
    monkeypatch.delenv("NOTIFICATION_PAGE_SIZE_DEFAULT", raising=False)
    assert Settings(_env_file=None).notification_page_size_default == 20


@pytest.mark.parametrize("value", [0, 1, 2, 99, 100, 101])
def test_settings_boundaries(monkeypatch, value):
    monkeypatch.setenv("NOTIFICATION_PAGE_SIZE_DEFAULT", str(value))
    if 1 <= value <= 100:
        assert Settings(_env_file=None).notification_page_size_default == value
    else:
        with pytest.raises(ValidationError, match="notification_page_size_default"):
            Settings(_env_file=None)


@pytest.mark.parametrize("value", ["0", "101", "not-an-integer"])
def test_invalid_env_prevents_startup(value):
    env = {**os.environ, "NOTIFICATION_PAGE_SIZE_DEFAULT": value}
    result = subprocess.run(
        [sys.executable, "-c", "from app.common.config import settings"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "ValidationError" in result.stderr
    assert "notification_page_size_default" in result.stderr


@pytest.mark.parametrize("default", [1, 2, 100])
def test_route_resolves_default(api, monkeypatch, default):
    # Set the loaded singleton in memory (including on baseline); this is not env reload.
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", default)
    client, actor, service, _ = api
    response = client.get("/api/v1/notifications")
    assert response.json() == {"items": [], "unread_count": 0, "next_cursor": None}
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    service.list_notifications.assert_called_once_with(
        actor.id, Pagination(limit=default, cursor=None)
    )


@pytest.mark.parametrize("limit", [1, 2, 99, 100])
def test_explicit_limit_overrides_default(api, monkeypatch, limit):
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", 2)
    client, actor, service, _ = api
    response = client.get(f"/api/v1/notifications?limit={limit}")
    assert response.json() == {"items": [], "unread_count": 0, "next_cursor": None}
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    service.list_notifications.assert_called_once_with(
        actor.id, Pagination(limit=limit, cursor=None)
    )


@pytest.mark.parametrize(
    "query,status",
    [
        ("limit=0", 422),
        ("limit=101", 422),
        ("limit=abc", 422),
        ("cursor=invalid", 400),
        ("cursor=" + "a" * 23, 422),
    ],
)
def test_invalid_query_never_calls_service(api, query, status):
    client, _, service, _ = api
    response = client.get("/api/v1/notifications?" + query)
    assert response.status_code == status
    assert response.json()["error"]["code"] in {"VALIDATION_ERROR", "BAD_REQUEST"}
    assert response.headers["Cache-Control"] == "no-store"
    service.list_notifications.assert_not_called()


def test_other_endpoint_keeps_twenty(api, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "notification_page_size_default", 2)
    client, actor, _, classroom = api
    response = client.get("/api/v1/classes")
    assert response.json() == {"items": [], "next_cursor": None}
    assert response.status_code == 200
    classroom.list_classes.assert_called_once_with(actor, Pagination(limit=20, cursor=None))
