"""Version-one allowlist for the existing Classroom and Social producers."""

import hashlib
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.common.outbox import OUTBOX_SCHEMA_VERSION, OutboxEvent
from app.modules.classroom.public import (
    ClassAccessAction,
    check_class_action,
    get_notification_audience,
)
from app.modules.identity.public import get_users_summaries
from app.modules.social.comments.public import get_visible_comment_ref
from app.modules.social.feed.public import get_visible_post_ref


class EventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    class_id: UUID
    school_id: UUID | None = None
    recipient_ids: list[UUID] | None = None


class ClassChanged(EventPayload):
    version: int = Field(ge=1)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class StudentTransferred(EventPayload):
    destination_class_id: UUID
    student_id: UUID
    effective_at: AwareDatetime
    version: int | None = Field(default=None, ge=1)


class HomeroomTransferred(EventPayload):
    destination_homeroom_id: UUID
    student_id: UUID
    effective_at: AwareDatetime


class PostCreated(EventPayload):
    post_id: UUID
    author_id: UUID


class CommentCreated(PostCreated):
    comment_id: UUID
    post_author_id: UUID


class DeadlineChanged(EventPayload):
    event_id: UUID
    external_ref: str = Field(min_length=1, max_length=200)
    version: int = Field(ge=1)


class DocumentGrantChanged(EventPayload):
    document_id: UUID
    owner_user_id: UUID
    actor_user_id: UUID
    grant_id: UUID
    grant_revision: int = Field(gt=0)
    is_active: bool
    document_version: int | None = Field(default=None, gt=0)


EVENT_SCHEMAS = {
    "CLASS_ENROLLMENT_CHANGED": ClassChanged,
    "CLASS_ENROLLMENT_MODE_CHANGED": ClassChanged,
    "CLASS_TEACHERS_CHANGED": ClassChanged,
    "CLASS_STATUS_CHANGED": ClassChanged,
    "CLASS_STUDENT_TRANSFERRED": StudentTransferred,
    "HOMEROOM_STUDENT_TRANSFERRED": HomeroomTransferred,
    "SOCIAL_POST_CREATED": PostCreated,
    "SOCIAL_COMMENT_CREATED": CommentCreated,
    "CALENDAR_DEADLINE_CHANGED": DeadlineChanged,
    "DOCUMENT_GRANT_CHANGED": DocumentGrantChanged,
}


class InvalidEvent(ValueError):
    pass


def prepare_delivery(session: Session, event: OutboxEvent) -> tuple[list[UUID], dict]:
    if event.schema_version != OUTBOX_SCHEMA_VERSION:
        raise InvalidEvent("Unsupported envelope")
    payload = EVENT_SCHEMAS[event.event_type].model_validate(event.payload_json)
    aggregate_id = (
        payload.comment_id
        if isinstance(payload, CommentCreated)
        else payload.post_id
        if isinstance(payload, PostCreated)
        else payload.event_id
        if isinstance(payload, DeadlineChanged)
        else payload.grant_id
        if isinstance(payload, DocumentGrantChanged)
        else payload.class_id
    )
    if str(aggregate_id) != event.aggregate_id:
        raise InvalidEvent("Mismatched aggregate")
    version = getattr(payload, "version", None)
    if event.aggregate_version is not None and event.aggregate_version != version:
        raise InvalidEvent("Mismatched aggregate version")
    homeroom = isinstance(payload, HomeroomTransferred)
    audience = get_notification_audience(payload.class_id, session=session, homeroom=homeroom)
    if audience is None:
        # No usable source scope: retain the row for operator investigation/retry.
        raise InvalidEvent("Missing source scope")
    if payload.school_id is not None and payload.school_id != audience.school_id:
        raise InvalidEvent("Mismatched school")
    candidates = set(
        payload.recipient_ids if payload.recipient_ids is not None else audience.recipient_ids
    )
    if isinstance(payload, (StudentTransferred, HomeroomTransferred)):
        candidates = {payload.student_id}
    elif isinstance(payload, CommentCreated):
        candidates &= {payload.post_author_id}
    if isinstance(payload, PostCreated):
        candidates.discard(payload.author_id)
        post = get_visible_post_ref(payload.class_id, payload.post_id, session=session)
        if post is None:
            return [], {}
        if isinstance(payload, CommentCreated):
            comment = get_visible_comment_ref(payload.post_id, payload.comment_id, session=session)
            if comment is None:
                return [], {}
            if comment.author_id != payload.author_id or post.author_id != payload.post_author_id:
                raise InvalidEvent("Mismatched comment authors")
        elif post.author_id != payload.author_id:
            raise InvalidEvent("Mismatched post author")
    users = get_users_summaries(sorted(candidates), session=session)
    recipients = []
    for user_id in sorted(candidates):
        user = users.get(user_id)
        if user is None or user.school_id != audience.school_id:
            continue
        if (
            isinstance(payload, (PostCreated, DeadlineChanged, DocumentGrantChanged))
            and not check_class_action(
                payload.class_id,
                user_id,
                ClassAccessAction.READ_DOCUMENT_SOURCE
                if isinstance(payload, DocumentGrantChanged)
                else ClassAccessAction.READ_CLASS_CONTENT,
                session=session,
            ).allowed
        ):
            continue
        recipients.append(user_id)
    # No free text, credentials, external_ref or recipient lists in inbox payloads.
    safe = {
        key: str(value) if isinstance(value, (UUID, datetime)) else value
        for key, value in payload.model_dump(exclude_none=True).items()
        if key not in {"recipient_ids", "school_id", "post_author_id", "external_ref"}
    }
    if homeroom:
        safe["homeroom_id"] = safe.pop("class_id")
    safe.update(event_id=str(event.id), schema_version=event.schema_version)
    return recipients, safe


def dedup_key(event: OutboxEvent, recipient_id: UUID) -> str:
    # An event retry reuses its UUID; versioned producer replay is also deduped.
    version = event.aggregate_version or event.payload_json.get("version")
    identity = f"{event.aggregate_id}:{version}" if version is not None else str(event.id)
    return hashlib.sha256(
        f"v{event.schema_version}:{event.event_type}:{identity}:{recipient_id}".encode()
    ).hexdigest()
