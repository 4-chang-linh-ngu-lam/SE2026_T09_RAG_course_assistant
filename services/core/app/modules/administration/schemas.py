from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.identity.public import (
    AdminUserUpdateCommand,
    DataResolutionCommand,
    RoleUpdateCommand,
    UserSummaryDTO,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminCreateUserRequest(RequestModel):
    email: EmailStr = Field(max_length=320)
    roles: list[Literal["ADMIN", "LECTURER"]] = Field(min_length=1, max_length=2)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("Duplicate roles")
        return value

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value):
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Display name cannot be blank")
        return value


class AdminUserStatusRequest(RequestModel):
    status: Literal["ACTIVE", "LOCKED"]


AdminUserRolesRequest = RoleUpdateCommand
AdminUserUpdateRequest = AdminUserUpdateCommand
AdminDataRequestResolve = DataResolutionCommand


class AuditEventResponse(BaseModel):
    id: UUID
    actor_id: UUID | None
    actor_name: str = "Người dùng trong trường"
    action: str
    target_type: str
    target_id: UUID
    correlation_id: UUID
    metadata_json: dict
    occurred_at: datetime


class ImportPreviewRequest(RequestModel):
    format: Literal["CSV", "XLSX"]
    content_base64: str = Field(min_length=1, max_length=2800000, repr=False)
    homeroom_class_id: UUID | None = None
    username_header: str = Field(default="username", min_length=1, max_length=200)
    display_name_header: str | None = Field(default=None, min_length=1, max_length=200)
    user_id_header: str | None = Field(default=None, min_length=1, max_length=200)


class ImportConfirmRequest(RequestModel):
    preview_id: UUID


class ImportErrorResponse(BaseModel):
    row: int
    code: str


class ImportPreviewItem(BaseModel):
    row: int
    action: Literal["CREATE", "EXISTING", "ASSIGN_USERNAME"]
    username: str
    user_id: UUID | None


class ImportPreviewResponse(BaseModel):
    valid: bool
    preview_id: UUID | None = None
    expires_at: datetime | None = None
    items: list[ImportPreviewItem] = []
    errors: list[ImportErrorResponse] = []


class ImportStatusItem(BaseModel):
    row: int
    action: Literal["CREATE", "EXISTING", "ASSIGN_USERNAME"] | None = None
    outcome: Literal["CREATED", "EXISTING", "USERNAME_ASSIGNED"] | None = None
    username: str | None = None
    user_id: UUID | None = None


class ImportStatusResponse(BaseModel):
    preview_id: UUID
    status: Literal["PREVIEW", "COMPLETED", "EXPIRED"]
    expires_at: datetime | None = None
    items: list[ImportStatusItem] = []


class ImportResultItem(BaseModel):
    row: int
    outcome: Literal["CREATED", "EXISTING", "USERNAME_ASSIGNED"]
    student: UserSummaryDTO
    code: str | None = Field(default=None, repr=False)
    expires_at: datetime | None = None


class ImportConfirmResponse(BaseModel):
    preview_id: UUID
    status: Literal["COMPLETED"] = "COMPLETED"
    replayed: bool
    items: list[ImportResultItem]
