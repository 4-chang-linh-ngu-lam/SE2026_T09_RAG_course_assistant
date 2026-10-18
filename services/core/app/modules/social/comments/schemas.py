from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.common.pagination import Page
from app.modules.social.schemas import AuthorSummary


class CommentBody(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    body: str = Field(min_length=1, max_length=10000)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Comment body cannot be blank")
        return value


class CommentCreateRequest(CommentBody):
    pass


class CommentUpdateRequest(CommentBody):
    pass


class CommentResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    post_id: UUID
    author: AuthorSummary
    body: str
    created_at: datetime
    updated_at: datetime


class CommentListResponse(Page[CommentResponse]):
    pass
