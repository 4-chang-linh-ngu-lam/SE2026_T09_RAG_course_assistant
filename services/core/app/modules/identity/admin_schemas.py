from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.identity.schemas import AdminCreateStudentRequest

AdminReason = Literal["ADMIN_INTERVENTION", "POLICY_VIOLATION", "USER_REQUEST"]
ResolutionNote = Literal[
    "VERIFICATION_IN_PROGRESS",
    "POLICY_PENDING",
    "OUTSIDE_CORE_SCOPE",
    "INSUFFICIENT_VERIFICATION",
    "REQUEST_REJECTED",
    "DUPLICATE_REQUEST",
    "MANUAL_FULFILLMENT_CONFIRMED",
]


class StudentImportRow(AdminCreateStudentRequest):
    user_id: UUID | None = None


class StudentImportCheck(BaseModel):
    model_config = ConfigDict(frozen=True)
    action: Literal["CREATE", "EXISTING", "ASSIGN_USERNAME", "ERROR"]
    user_id: UUID | None = None
    error: str | None = None
    fingerprint: str


class RoleUpdateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    roles: list[Literal["ADMIN", "LECTURER", "STUDENT"]] = Field(min_length=1, max_length=3)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, roles):
        if len(roles) != len(set(roles)):
            raise ValueError("Duplicate roles")
        return sorted(roles)


class DataResolutionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["IN_REVIEW", "COMPLETED", "REJECTED"]
    resolution_note: ResolutionNote
    identity_verified: bool = Field(default=False, strict=True)
    manual_fulfillment_confirmed: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def manual_fulfillment_matches_resolution(self):
        manual_note = self.resolution_note == "MANUAL_FULFILLMENT_CONFIRMED"
        if self.manual_fulfillment_confirmed != manual_note:
            raise ValueError("Manual fulfillment flag and resolution note must match")
        if manual_note and self.status != "COMPLETED":
            raise ValueError("Manual fulfillment confirmation requires COMPLETED status")
        return self


class AdminUserListItem(BaseModel):
    id: UUID
    email: str | None
    username: str | None
    school_id: UUID
    display_name: str | None
    status: Literal["ACTIVE", "PENDING_VERIFICATION", "LOCKED"]
    roles: list[Literal["ADMIN", "LECTURER", "STUDENT"]]
    revision: int
    created_at: datetime
    email_verified: bool
    activation_required: bool
    last_admin: bool
    invitation_expires_at: datetime | None = None
    invitation_delivery_status: (
        Literal["PENDING", "DELIVERED", "CANCELLED", "NEEDS_REISSUE"] | None
    ) = None


class AdminUserUpdateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    roles: list[Literal["ADMIN", "LECTURER", "STUDENT"]] | None = Field(
        default=None, min_length=1, max_length=3
    )
    status: Literal["ACTIVE", "PENDING_VERIFICATION", "LOCKED"] | None = None

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value):
        if value is not None and len(value) != len(set(value)):
            raise ValueError("Duplicate roles")
        return value

    @model_validator(mode="after")
    def has_update(self):
        if self.roles is None and self.status is None:
            raise ValueError("At least one account field must be changed")
        return self
