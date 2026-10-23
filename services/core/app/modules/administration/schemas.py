from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.modules.identity.public import DataResolutionCommand, RoleUpdateCommand, UserSummaryDTO


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminCreateUserRequest(RequestModel):
    email: EmailStr = Field(max_length=320)
    roles: list[Literal["ADMIN", "LECTURER"]] = Field(min_length=1, max_length=2)

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


class AdminUserStatusRequest(RequestModel):
    status: Literal["ACTIVE", "LOCKED"]


AdminUserRolesRequest = RoleUpdateCommand
AdminDataRequestResolve = DataResolutionCommand


class AuditEventResponse(BaseModel):
    id: UUID
    actor_id: UUID | None
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
