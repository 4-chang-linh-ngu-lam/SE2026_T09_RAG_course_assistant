from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.identity.schemas import AdminCreateStudentRequest, UserSummaryDTO

AdminReason = Literal["ADMIN_INTERVENTION", "POLICY_VIOLATION", "USER_REQUEST"]
ResolutionNote = Literal[
    "VERIFICATION_IN_PROGRESS",
    "POLICY_PENDING",
    "OUTSIDE_CORE_SCOPE",
    "INSUFFICIENT_VERIFICATION",
    "REQUEST_REJECTED",
    "DUPLICATE_REQUEST",
]


class AdminUserReadDTO(UserSummaryDTO):
    """Current school-scoped account metadata; credentials never cross this boundary."""

    roles: list[Literal["ADMIN", "LECTURER", "STUDENT"]]


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
