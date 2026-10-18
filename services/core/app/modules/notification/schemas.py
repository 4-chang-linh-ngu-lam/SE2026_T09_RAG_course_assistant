from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: UUID
    type: str
    payload_json: dict
    read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationResponse]
    unread_count: int
    next_cursor: str | None = None


class MarkReadResponse(BaseModel):
    id: UUID
    read: bool
