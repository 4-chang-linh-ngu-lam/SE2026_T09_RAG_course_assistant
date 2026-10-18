from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.modules.identity.models import DataRequestStatus, DataRequestType, Role, UserStatus


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailRequest(RequestModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class RegisterRequest(EmailRequest):
    password: SecretStr = Field(min_length=12, max_length=128)


class RegisterResponse(BaseModel):
    user_id: UUID
    email: EmailStr
    status: UserStatus


class VerifyEmailRequest(RequestModel):
    token: SecretStr = Field(min_length=1, max_length=256)


def normalize_username(value):
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if not normalized.isprintable():
        raise ValueError("Username must be printable")
    return normalized


Username = Annotated[
    str,
    BeforeValidator(normalize_username),
    Field(min_length=1, max_length=200, pattern=r"^[^\s@]+$"),
]


class LoginRequest(RequestModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "oneOf": [
                {
                    "required": ["email"],
                    "properties": {"email": {"type": "string"}, "username": {"type": "null"}},
                },
                {
                    "required": ["username"],
                    "properties": {"username": {"type": "string"}, "email": {"type": "null"}},
                },
            ]
        },
    )
    email: EmailStr | None = None
    username: Username | None = None
    password: SecretStr = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower() if value is not None else None

    @model_validator(mode="after")
    def one_identifier(self):
        if (self.email is None) == (self.username is None):
            raise ValueError("Provide exactly one of email or username")
        return self

    @property
    def login_key(self) -> str:
        return "username:" + self.username if self.username is not None else "email:" + self.email


class AdminCreateStudentRequest(RequestModel):
    username: Username
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class AssignStudentUsernameRequest(RequestModel):
    username: Username


class ActivateStudentRequest(RequestModel):
    username: Username
    activation_code: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class IssueStudentCodeRequest(RequestModel):
    identity_verified: bool = Field(default=False, strict=True)


class TokenResponse(BaseModel):
    access_token: str = Field(repr=False)
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 900


class ForgotPasswordRequest(EmailRequest):
    pass


class ResetPasswordRequest(RequestModel):
    token: SecretStr = Field(min_length=1, max_length=256)
    new_password: SecretStr = Field(min_length=12, max_length=128)


class VerifyEmailResponse(BaseModel):
    verified: Literal[True] = True


class ForgotPasswordResponse(BaseModel):
    message: str = "If the account is eligible, password reset instructions will be sent."


class UserProfile(BaseModel):
    id: UUID
    email: EmailStr | None
    username: str | None = None
    school_id: UUID | None = None
    display_name: str | None
    roles: list[Role]
    status: UserStatus


class UpdateProfileRequest(RequestModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)


class UserSummaryDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    email: EmailStr | None
    username: str | None = None
    school_id: UUID | None = None
    display_name: str | None = None
    status: Literal["PENDING_VERIFICATION", "ACTIVE", "LOCKED"]


class AdminCreateUserRequest(EmailRequest):
    roles: list[Role] = Field(min_length=1, max_length=3)

    @field_validator("roles")
    @classmethod
    def unique_roles(cls, value: list[Role]) -> list[Role]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate roles")
        if Role.STUDENT in value:
            raise ValueError("Use Student provisioning instead of an email invitation")
        return value


class StudentCodeResponse(BaseModel):
    student: UserSummaryDTO
    purpose: Literal["ACTIVATION", "PASSWORD_RESET"]
    code: str = Field(repr=False)
    expires_at: datetime


class AdminSetStatusRequest(RequestModel):
    status: Literal["ACTIVE", "LOCKED"]


class CreateDataRequest(RequestModel):
    type: DataRequestType = Field(validation_alias=AliasChoices("type", "request_type"))
    reason: str | None = Field(default=None, max_length=10000)


class DataRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    type: DataRequestType = Field(validation_alias="request_type")
    reason: str | None
    status: DataRequestStatus
    resolution_note: str | None
    created_at: datetime
    updated_at: datetime
