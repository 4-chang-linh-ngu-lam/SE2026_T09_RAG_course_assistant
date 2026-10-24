# ruff: noqa: F811 -- imported pytest fixtures intentionally share test argument names
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import func, select

from app.bootstrap import register_routers
from app.common.config import settings
from app.common.db import get_db
from app.common.errors import register_error_handlers
from app.common.outbox import OutboxEvent
from app.modules.notification.models import DocumentEventReceipt, Notification
from app.modules.notification.worker import drain_outbox
from tests.notification.test_postgres import (  # noqa: F401 -- shared real PG fixtures
    database,
    system,
)

KEY = "synthetic-document-events-" + "x" * 32


@pytest.fixture
def intake(system, monkeypatch):
    monkeypatch.setattr(settings, "document_events_service_secret", SecretStr(KEY))
    application = FastAPI()
    register_error_handlers(application)
    register_routers(application)

    def sessions():
        with system.factory() as session:
            yield session

    application.dependency_overrides[get_db] = sessions
    with TestClient(application) as client:
        yield client


def event(system, revision=1):
    grant_id = uuid4()
    return {
        "event_id": str(uuid4()),
        "event_type": "document.grant.changed.v1",
        "schema_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "school_id": str(system.users["teacher"].school_id),
        "aggregate_id": str(grant_id),
        "aggregate_revision": revision,
        "payload": {
            "document_id": str(uuid4()),
            "owner_user_id": str(system.users["teacher"].id),
            "actor_user_id": str(system.users["teacher"].id),
            "class_id": str(system.class_id),
            "grant_id": str(grant_id),
            "grant_revision": revision,
            "is_active": True,
            "document_version": 1,
        },
    }


def send(intake, body, key=KEY):
    return intake.post("/internal/v1/document-events", headers={"X-Service-Key": key}, json=body)


def test_document_event_receipt_durable_replay_hash_and_delivery(system, intake):
    body = event(system)
    assert send(intake, body).json() == {"event_id": body["event_id"], "accepted": True}
    assert send(intake, body).status_code == 200
    with system.factory() as session:
        assert session.scalar(select(func.count()).select_from(DocumentEventReceipt)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxEvent)) == 1
    body["payload"]["is_active"] = False
    assert send(intake, body).status_code == 409
    assert drain_outbox(session_factory=system.factory) == 1
    assert drain_outbox(session_factory=system.factory) == 0
    with system.factory() as session:
        rows = list(
            session.scalars(
                select(Notification).where(Notification.type == "DOCUMENT_GRANT_CHANGED")
            )
        )
        assert rows
        assert len({row.dedup_key for row in rows}) == len(rows)
        assert all(
            row.payload_json["document_id"] == body["payload"]["document_id"] for row in rows
        )
        assert all("recipient_ids" not in row.payload_json for row in rows)


@pytest.mark.parametrize("bad_key", ["", "wrong", "jwt-signing-key-is-not-service-scope"])
def test_only_the_scoped_document_credential_is_accepted(system, intake, bad_key):
    assert send(intake, event(system), bad_key).status_code == 403


def test_wrong_school_class_actor_and_free_text_are_rejected(system, intake):
    for field in ("school_id", "class_id", "actor_user_id"):
        body = event(system)
        (body if field == "school_id" else body["payload"])[field] = str(uuid4())
        assert send(intake, body).status_code == 403
    body = event(system)
    body["payload"]["source_quote"] = "must never be accepted"
    assert send(intake, body).status_code == 422
    body = event(system)
    body["aggregate_id"] = str(uuid4())
    assert send(intake, body).status_code == 422


def test_distinct_grant_revisions_do_not_collapse_to_file_version(system, intake):
    body = event(system)
    assert send(intake, body).status_code == 200
    body["event_id"] = str(uuid4())
    body["aggregate_revision"] = body["payload"]["grant_revision"] = 2
    body["payload"]["is_active"] = False
    assert send(intake, body).status_code == 200
    assert drain_outbox(session_factory=system.factory) == 2
    with system.factory() as session:
        values = list(
            session.scalars(
                select(Notification).where(Notification.recipient_id == system.users["student"].id)
            )
        )
        assert len(values) == 2
        assert {row.payload_json["grant_revision"] for row in values} == {1, 2}


def test_delivery_rechecks_current_membership(system, intake):
    body = event(system)
    assert send(intake, body).status_code == 200
    system.classroom.end_member(system.class_id, system.users["admin"], system.users["student"].id)
    drain_outbox(session_factory=system.factory)
    with system.factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Notification)
                .where(
                    Notification.recipient_id == system.users["student"].id,
                    Notification.type == "DOCUMENT_GRANT_CHANGED",
                )
            )
            == 0
        )


def test_reused_jwt_secret_is_a_configuration_failure(system, intake, monkeypatch):
    monkeypatch.setattr(settings, "secret_key", SecretStr(KEY))
    assert send(intake, event(system)).status_code == 503


def test_intake_rejects_unauthorized_or_oversized_body_before_validation(system, intake):
    assert intake.post("/internal/v1/document-events", content="not JSON").status_code == 403
    response = intake.post(
        "/internal/v1/document-events", headers={"X-Service-Key": KEY}, content="x" * 65537
    )
    assert response.status_code == 413
