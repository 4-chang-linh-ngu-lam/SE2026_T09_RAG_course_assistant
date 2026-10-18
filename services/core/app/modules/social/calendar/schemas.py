from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.common.pagination import Page
from app.modules.social.calendar.models import CalendarOrigin


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime must include a timezone")
    return value


class CalendarEventCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    starts_at: datetime
    ends_at: datetime

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Title cannot be blank")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        return _aware(value)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        return self


class CalendarEventUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Title cannot be blank")
        return value

    @field_validator("starts_at", "ends_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)

    id: UUID
    class_id: UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    origin: CalendarOrigin
    external_ref: str | None


class CalendarEventListResponse(Page[CalendarEventResponse]):
    pass
