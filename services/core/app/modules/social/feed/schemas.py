from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.pagination import Page

__all__ = [
    "PostAuthorSummary",
    "PostCreateRequest",
    "PostListResponse",
    "PostResponse",
    "PostUpdateRequest",
]


class PostAuthorSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    display_name: str | None = None
    email: str


class PostCreateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str = Field(..., min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def validate_body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Post body cannot be empty or contain only whitespace")
        return value


class PostUpdateRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str = Field(..., min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def validate_body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Post body cannot be empty or contain only whitespace")
        return value


class PostResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    class_id: UUID
    author: PostAuthorSummary
    body: str
    created_at: datetime
    updated_at: datetime


class PostListResponse(Page[PostResponse]):
    pass
