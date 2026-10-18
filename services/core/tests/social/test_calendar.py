import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.common.auth_dependencies import CurrentUser
from app.common.errors import AppError
from app.modules.classroom import public as classroom_public
from app.modules.social.calendar.models import CalendarEvent, CalendarOrigin
from app.modules.social.calendar.schemas import (
    CalendarEventCreateRequest,
    CalendarEventUpdateRequest,
)
from app.modules.social.calendar.service import CalendarService


def _user(role="LECTURER"):
    return CurrentUser(id=uuid4(), status="ACTIVE", session_version=1, roles=[role])


def _access(monkeypatch, *, read=True, write=True, archived=False):
    def check(_class_id, _user_id, action, *, session):
        return SimpleNamespace(
            allowed=read if str(action) == "read_class_content" else write,
            class_status="ARCHIVED"
            if archived and str(action) == "read_class_content"
            else "ACTIVE",
        )

    monkeypatch.setattr(classroom_public, "check_class_action", check)


def _event(class_id, *, origin=CalendarOrigin.CORE):
    start = datetime.now(UTC)
    event = CalendarEvent(
        class_id=class_id,
        title="Event",
        description=None,
        starts_at=start,
        ends_at=start + timedelta(hours=1),
        origin=origin,
        external_ref="learning-1" if origin == CalendarOrigin.LEARNING else None,
        version=1,
    )
    event.id = uuid4()
    event.created_at = start
    event.updated_at = start
    return event


@pytest.mark.parametrize(
    "start,end",
    [
        (datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
        (datetime.now(UTC), datetime.now(UTC) - timedelta(hours=1)),
        (datetime.now(), datetime.now() + timedelta(hours=1)),
    ],
)
def test_calendar_create_rejects_invalid_or_naive_intervals(start, end):
    with pytest.raises(ValidationError):
        CalendarEventCreateRequest(title="Event", starts_at=start, ends_at=end)


@pytest.mark.parametrize("field", ["title", "starts_at", "ends_at"])
def test_calendar_patch_rejects_explicit_null_for_required_fields(field):
    with pytest.raises(ValidationError):
        CalendarEventUpdateRequest.model_validate({field: None})


def test_calendar_patch_allows_clearing_description():
    request = CalendarEventUpdateRequest.model_validate({"description": None})
    assert request.model_dump(exclude_unset=True) == {"description": None}


def test_calendar_patch_checks_value_remaining_in_database(monkeypatch):
    session = MagicMock(spec=Session)
    service = CalendarService(session)
    user, class_id = _user(), uuid4()
    event = _event(class_id)
    _access(monkeypatch)
    monkeypatch.setattr(service.repository, "get", lambda *args, **kwargs: event)
    with pytest.raises(AppError) as invalid:
        service.update_event(
            class_id,
            event.id,
            CalendarEventUpdateRequest(starts_at=event.ends_at),
            user,
        )
    assert invalid.value.status_code == 422


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_learning_events_are_read_only(monkeypatch, operation):
    session = MagicMock(spec=Session)
    service = CalendarService(session)
    user, class_id = _user(), uuid4()
    event = _event(class_id, origin=CalendarOrigin.LEARNING)
    _access(monkeypatch)
    monkeypatch.setattr(service.repository, "get", lambda *args, **kwargs: event)
    with pytest.raises(AppError) as denied:
        if operation == "update":
            service.update_event(
                class_id,
                event.id,
                CalendarEventUpdateRequest(title="Changed"),
                user,
            )
        else:
            service.delete_event(class_id, event.id, user)
    assert denied.value.status_code == 400


def test_student_cannot_manage_calendar(monkeypatch):
    service = CalendarService(MagicMock(spec=Session))
    _access(monkeypatch, read=True, write=False)
    now = datetime.now(UTC)
    with pytest.raises(AppError) as denied:
        service.create_event(
            uuid4(),
            CalendarEventCreateRequest(
                title="Event", starts_at=now, ends_at=now + timedelta(hours=1)
            ),
            _user("STUDENT"),
        )
    assert denied.value.status_code == 403


def test_archived_calendar_write_returns_conflict(monkeypatch):
    service = CalendarService(MagicMock(spec=Session))
    _access(monkeypatch, read=True, write=False, archived=True)
    now = datetime.now(UTC)
    with pytest.raises(AppError) as denied:
        service.create_event(
            uuid4(),
            CalendarEventCreateRequest(
                title="Event", starts_at=now, ends_at=now + timedelta(hours=1)
            ),
            _user(),
        )
    assert denied.value.status_code == 409


def test_cross_class_calendar_event_is_hidden(monkeypatch):
    service = CalendarService(MagicMock(spec=Session))
    user, class_id = _user(), uuid4()
    _access(monkeypatch)
    event = _event(uuid4())
    monkeypatch.setattr(service.repository, "get", lambda *args, **kwargs: event)
    with pytest.raises(AppError) as hidden:
        service.update_event(
            class_id,
            event.id,
            CalendarEventUpdateRequest(title="Changed"),
            user,
        )
    assert hidden.value.status_code == 404


def test_social_openapi_snapshot():
    from app.main import app

    spec = app.openapi()
    paths = {
        path: sorted(spec["paths"][path])
        for path in spec["paths"]
        if path.startswith("/api/v1/classes/") and ("/posts" in path or "/calendar" in path)
    }
    contract = {
        "paths": paths,
        "author_properties": sorted(spec["components"]["schemas"]["AuthorSummary"]["properties"]),
        "calendar_origin": spec["components"]["schemas"]["CalendarOrigin"]["enum"],
    }
    snapshot = Path(__file__).with_name("openapi_contract.json")
    assert contract == json.loads(snapshot.read_text(encoding="utf-8"))
    assert "get" not in paths["/api/v1/classes/{class_id}/posts/{post_id}"]
