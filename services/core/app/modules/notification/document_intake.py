"""Scoped Document event intake. No Document tables or private source contents."""

import hashlib
import hmac
import json
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from starlette.requests import Request

from app.common.config import settings
from app.common.db import get_db
from app.common.errors import AppError, error_response
from app.common.outbox import record_outbox_event
from app.modules.classroom.public import get_notification_audience
from app.modules.identity.public import get_users_summaries
from app.modules.notification.models import DocumentEventReceipt

router = APIRouter(prefix="/internal/v1", tags=["Internal Document notifications"])


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID
    owner_user_id: UUID
    actor_user_id: UUID | None = None
    class_id: UUID | None = None
    grant_id: UUID | None = None
    grant_revision: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    document_version: int | None = Field(default=None, gt=0)
    artifact_revision: int | None = Field(default=None, gt=0)


class DocumentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: UUID
    event_type: Literal[
        "document.version.ready.v1", "document.grant.changed.v1", "document.source.deleted.v1"
    ]
    schema_version: Literal[1]
    occurred_at: AwareDatetime
    school_id: UUID
    aggregate_id: UUID
    aggregate_revision: int = Field(gt=0)
    payload: Payload

    @model_validator(mode="after")
    def valid_aggregate(self):
        p = self.payload
        if self.event_type == "document.grant.changed.v1":
            if (
                p.class_id is None
                or p.grant_id != self.aggregate_id
                or p.grant_revision != self.aggregate_revision
                or p.actor_user_id is None
                or p.is_active is None
                or p.artifact_revision is not None
            ):
                raise ValueError("Invalid grant event")
        elif self.aggregate_id != p.document_id or any(
            v is not None
            for v in (
                p.class_id,
                p.grant_id,
                p.grant_revision,
                p.is_active,
            )
        ):
            raise ValueError("Invalid source event")
        elif self.event_type == "document.version.ready.v1" and (
            p.document_version is None or p.artifact_revision is None or p.actor_user_id is not None
        ):
            raise ValueError("Invalid version event")
        elif self.event_type == "document.source.deleted.v1" and (
            p.actor_user_id is None
            or p.document_version is not None
            or p.artifact_revision is not None
        ):
            raise ValueError("Invalid deletion event")
        return self


def authorize_document(key: Annotated[str | None, Header(alias="X-Service-Key")] = None):
    expected = settings.document_events_service_secret
    others = (settings.secret_key, settings.internal_service_secret, settings.core_proxy_secret)
    if expected is None or any(
        candidate is not None
        and hmac.compare_digest(
            candidate.get_secret_value().encode(), expected.get_secret_value().encode()
        )
        for candidate in others
    ):
        raise AppError(503, "Document event intake is not configured")
    if (
        not key
        or len(key) > 512
        or not hmac.compare_digest(key.encode(), expected.get_secret_value().encode())
    ):
        raise AppError(403, "Invalid service credential")


class DocumentEventAdmission:
    """Authenticate the internal intake before JSON parsing; bound event bytes."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("path") != "/internal/v1/document-events"
            or scope.get("method") != "POST"
        ):
            return await self.app(scope, receive, send)
        try:
            authorize_document(Headers(scope=scope).get("X-Service-Key"))
        except AppError as error:
            return await error_response(Request(scope), error.status_code, str(error.detail))(
                scope, receive, send
            )
        count = 0

        async def bounded():
            nonlocal count
            message = await receive()
            count += len(message.get("body", b""))
            if count > 65536:
                raise AppError(413, "Document event payload exceeds limit")
            return message

        return await self.app(scope, bounded, send)


@router.post("/document-events", dependencies=[Depends(authorize_document)])
def accept_document_event(body: DocumentEvent, session: Annotated[Session, Depends(get_db)]):
    value = body.model_dump(mode="json", exclude_none=True)
    digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    payload = body.payload
    user_ids = sorted({payload.owner_user_id, payload.actor_user_id or payload.owner_user_id})
    users = get_users_summaries(user_ids, session=session)
    if any(
        user_id not in users or users[user_id].school_id != body.school_id for user_id in user_ids
    ):
        raise AppError(403, "Event scope is not valid")
    audience = None
    if payload.class_id is not None:
        audience = get_notification_audience(payload.class_id, session=session)
        if audience is None or audience.school_id != body.school_id:
            raise AppError(403, "Event scope is not valid")
    created = session.scalar(
        insert(DocumentEventReceipt)
        .values(
            id=body.event_id,
            payload_hash=digest,
        )
        .on_conflict_do_nothing(index_elements=[DocumentEventReceipt.id])
        .returning(DocumentEventReceipt.id)
    )
    if created is None:
        existing = session.get(DocumentEventReceipt, body.event_id)
        if existing.payload_hash != digest:
            raise AppError(409, "Event ID already used by another payload")
    elif audience is not None:
        record_outbox_event(
            session,
            event_type="DOCUMENT_GRANT_CHANGED",
            aggregate_id=payload.grant_id,
            payload_json={
                "class_id": str(payload.class_id),
                "school_id": str(body.school_id),
                "recipient_ids": [str(user_id) for user_id in audience.recipient_ids],
                **payload.model_dump(mode="json", exclude_none=True),
            },
        )
    session.commit()
    return {"event_id": str(body.event_id), "accepted": True}
