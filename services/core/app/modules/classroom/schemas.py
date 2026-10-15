from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.modules.classroom.models import (
    ClassRole,
    ClassStatus,
    CoLecturerInvitationStatus,
    JoinRequestStatus,
    MembershipStatus,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CourseCreateRequest(RequestModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10000)


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    description: str | None
    created_at: datetime


class ClassCreateRequest(RequestModel):
    course_id: UUID
    name: str = Field(min_length=1, max_length=200)


class ClassUpdateRequest(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    join_enabled: bool | None = None


class ClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    course_id: UUID
    owner_user_id: UUID
    name: str
    join_enabled: bool
    status: ClassStatus
    created_at: datetime
    updated_at: datetime


class JoinCodeResponse(BaseModel):
    class_id: UUID
    join_code: str = Field(repr=False)


class JoinRequestCreateRequest(RequestModel):
    join_code: SecretStr = Field(min_length=1, max_length=256)


class JoinRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_id: UUID
    student_id: UUID
    status: JoinRequestStatus
    created_at: datetime
    decided_by: UUID | None = None
    decided_at: datetime | None = None


class JoinRequestCreatedResponse(BaseModel):
    request_id: UUID
    class_id: UUID
    status: Literal[JoinRequestStatus.PENDING]


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_id: UUID
    user_id: UUID
    class_role: ClassRole
    status: MembershipStatus
    joined_at: datetime
    ended_at: datetime | None = None


class CoLecturerInviteRequest(RequestModel):
    lecturer_id: UUID


class CoLecturerInvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_id: UUID
    lecturer_id: UUID
    status: Literal[
        CoLecturerInvitationStatus.PENDING,
        CoLecturerInvitationStatus.ACCEPTED,
        CoLecturerInvitationStatus.REJECTED,
        CoLecturerInvitationStatus.CANCELLED,
    ]
    expires_at: datetime
    created_at: datetime


class OwnershipTransferRequest(RequestModel):
    new_owner_user_id: UUID


class DecisionResponse(BaseModel):
    request_id: UUID
    status: JoinRequestStatus


class ClassStatusResponse(BaseModel):
    class_id: UUID
    status: ClassStatus


class InternalAccessResponse(BaseModel):
    allowed: bool
    class_id: UUID
    user_id: UUID
    action: str
    class_role: str | None = None
    class_status: str | None = None
