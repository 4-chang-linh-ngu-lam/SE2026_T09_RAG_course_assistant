from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import require_school_scope
from app.common.config import settings
from app.common.db import transaction
from app.common.errors import AppError
from app.common.pagination import Page, Pagination, encode_cursor
from app.common.security import (
    AccessClaims,
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.modules.identity.admin_security import ensure_other_admin, lock_admin_changes
from app.modules.identity.credential_tokens import derive_email_token
from app.modules.identity.models import (
    AuthSession,
    CredentialDelivery,
    DataRequest,
    OneTimeToken,
    Role,
    RoleAssignment,
    TokenPurpose,
    User,
    UserStatus,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import (
    ActivateStudentRequest,
    AdminCreateStudentRequest,
    AdminCreateUserRequest,
    AssignStudentUsernameRequest,
    CreateDataRequest,
    DataRequestResponse,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserProfile,
    UserSummaryDTO,
    VerifyEmailRequest,
)

_DUMMY_PASSWORD_HASH = hash_password(generate_refresh_token())


@dataclass(frozen=True)
class TokenDelivery:
    """Internal handoff to an email adapter; never serialize this as an API response."""

    recipient: str = field(repr=False)
    purpose: TokenPurpose
    token: SecretStr = field(repr=False)
    expires_at: datetime
    token_id: UUID | None = None


@dataclass(frozen=True)
class RegistrationResult:
    response: RegisterResponse
    delivery: TokenDelivery = field(repr=False)


@dataclass(frozen=True)
class AuthTokens:
    response: TokenResponse = field(repr=False)
    refresh_token: SecretStr = field(repr=False)
    refresh_expires_at: datetime


@dataclass(frozen=True)
class StudentCode:
    student: UserSummaryDTO
    purpose: str
    code: SecretStr = field(repr=False)
    expires_at: datetime


class IdentityService:
    """Auth/profile/request mutations commit; Admin helpers use savepoints in a caller-owned unit."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = IdentityRepository(session)

    def register(
        self, request: RegisterRequest, *, deliver: Callable[[TokenDelivery], None] | None = None
    ) -> RegistrationResult:
        """Legacy internal workflow retained for compatibility; public registration is blocked."""
        try:
            with transaction(self.session):
                if self.repository.get_by_email(request.email) is not None:
                    raise AppError(409, "Email already registered")
                user = self.repository.create_user(
                    User(
                        email=request.email,
                        password_hash=hash_password(request.password.get_secret_value()),
                        status=UserStatus.PENDING_VERIFICATION,
                    )
                )
                self.session.add(RoleAssignment(user_id=user.id, role=Role.STUDENT))
                delivery = self._issue_one_time_token(
                    user,
                    TokenPurpose.EMAIL_VERIFICATION,
                    timedelta(hours=settings.email_verification_expire_hours),
                )
                response = RegisterResponse(user_id=user.id, email=user.email, status=user.status)
                if deliver is not None:
                    deliver(delivery)
            return RegistrationResult(response, delivery)
        except IntegrityError as exc:
            # Only the expected registration race maps to a conflict; other DB failures propagate.
            if (
                getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                == "uq_users_email"
            ):
                raise AppError(409, "Email already registered") from exc
            raise

    def verify_email(self, request: VerifyEmailRequest) -> None:
        with transaction(self.session):
            user, token = self._lock_one_time_token(
                request.token.get_secret_value(), TokenPurpose.EMAIL_VERIFICATION
            )
            if user.status != UserStatus.PENDING_VERIFICATION or not self._is_staff(user):
                raise AppError(400, "Invalid verification token")
            now = datetime.now(UTC)
            self.repository.consume_one_time_token(token, now)
            user.email_verified_at = now
            user.status = UserStatus.ACTIVE

    def login(self, request: LoginRequest) -> AuthTokens:
        with transaction(self.session):
            user = self._authenticate(request)
            return self._issue_session(user, uuid4())

    def validate_cached_login(self, request: LoginRequest, access_token: str) -> None:
        claims = self._access_claims(access_token)
        with transaction(self.session):
            user = self._authenticate(request)
            if user.id != claims.sub or user.session_version != claims.session_version:
                raise AppError(401)

    def validate_cached_refresh(self, refresh_token: str, access_token: str) -> datetime:
        claims = self._access_claims(access_token)
        with transaction(self.session):
            user, current = self._lock_refresh_session(refresh_token)
            if (
                current.revoked_at is not None
                or current.expires_at <= datetime.now(UTC)
                or user.status != UserStatus.ACTIVE
                or not self._credentials_ready(user)
                or user.id != claims.sub
                or user.session_version != claims.session_version
            ):
                raise AppError(401)
            return current.expires_at

    def get_refresh_owner(self, refresh_token: str) -> UUID:
        current = self.repository.get_session_by_refresh_hash(hash_refresh_token(refresh_token))
        if current is None:
            raise AppError(401)
        return current.user_id

    def _authenticate(self, request: LoginRequest) -> User:
        user = (
            self.repository.get_by_username(request.username, for_update=True)
            if request.username is not None
            else self.repository.get_by_email(request.email, for_update=True)
        )
        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_valid = verify_password(request.password.get_secret_value(), password_hash)
        if (
            user is None
            or not password_valid
            or user.status != UserStatus.ACTIVE
            or not self._credentials_ready(user)
            or (request.username is not None) == self._is_staff(user)
        ):
            raise AppError(401)
        return user

    def _is_staff(self, user: User) -> bool:
        return bool(
            {Role.ADMIN, Role.LECTURER}.intersection(self.repository.get_user_roles(user.id))
        )

    def _credentials_ready(self, user: User) -> bool:
        roles = set(self.repository.get_user_roles(user.id))
        if roles.intersection({Role.ADMIN, Role.LECTURER}):
            return user.email is not None and user.email_verified_at is not None
        return (
            roles == {Role.STUDENT}
            and user.username is not None
            and user.activated_at is not None
            and user.school_id is not None
        )

    @staticmethod
    def _access_claims(access_token: str) -> AccessClaims:
        try:
            return decode_access_token(access_token)
        except jwt.InvalidTokenError as exc:
            raise AppError(401) from exc
        except RuntimeError as exc:
            raise AppError(503, "Authentication unavailable") from exc

    def refresh(self, refresh_token: str) -> AuthTokens:
        replay = False
        tokens = None
        with transaction(self.session):
            user, current = self._lock_refresh_session(refresh_token)
            now = datetime.now(UTC)
            if current.revoked_at is not None:
                self.repository.revoke_session_family(current.family_id, now)
                replay = True
            elif (
                current.expires_at <= now
                or user.status != UserStatus.ACTIVE
                or not self._credentials_ready(user)
            ):
                raise AppError(401)
            else:
                current.revoked_at = now
                tokens = self._issue_session(user, current.family_id, expires_at=current.expires_at)
        # Raising inside the transaction would roll back the security response to replay.
        if replay:
            raise AppError(401)
        assert tokens is not None
        return tokens

    def logout(self, refresh_token: str) -> None:
        with transaction(self.session):
            current = self.repository.get_session_by_refresh_hash(hash_refresh_token(refresh_token))
            if current is None:
                return
            self.repository.get_by_id(current.user_id, for_update=True)
            current = self.repository.get_session_by_refresh_hash(
                hash_refresh_token(refresh_token), for_update=True
            )
            if current is not None and current.revoked_at is None:
                current.revoked_at = datetime.now(UTC)

    def logout_all(self, user_id: UUID) -> None:
        with transaction(self.session):
            user = self.repository.get_by_id(user_id, for_update=True)
            if user is None:
                raise AppError(401)
            self._revoke_all(user)

    def forgot_password(
        self,
        request: ForgotPasswordRequest,
    ) -> TokenDelivery | None:
        with transaction(self.session):
            user = self.repository.get_by_email(request.email, for_update=True)
            if (
                user is None
                or user.status != UserStatus.ACTIVE
                or user.email_verified_at is None
                or not self._is_staff(user)
            ):
                return None
            pending = self.repository.get_pending_email_token(
                user.id, TokenPurpose.PASSWORD_RESET, datetime.now(UTC)
            )
            if pending is not None:
                raw = derive_email_token(
                    pending.id, pending.user_id, pending.purpose, pending.expires_at
                )
                if hash_refresh_token(raw) == pending.token_hash:
                    return TokenDelivery(
                        user.email,
                        pending.purpose,
                        SecretStr(raw),
                        pending.expires_at,
                        pending.id,
                    )
            self.repository.invalidate_one_time_tokens(
                user.id, TokenPurpose.PASSWORD_RESET, datetime.now(UTC)
            )
            delivery = self._issue_one_time_token(
                user,
                TokenPurpose.PASSWORD_RESET,
                timedelta(minutes=settings.password_reset_expire_minutes),
            )
            return delivery

    def get_profile(self, user_id: UUID) -> UserProfile:
        profile = self.repository.get_profile(user_id)
        if profile is None or profile.status != UserStatus.ACTIVE:
            raise AppError(401)
        return profile

    def update_profile(self, user_id: UUID, request: UpdateProfileRequest) -> UserProfile:
        with transaction(self.session):
            user = self.repository.get_by_id(user_id, for_update=True)
            if user is None or user.status != UserStatus.ACTIVE:
                raise AppError(401)
            if "display_name" in request.model_fields_set:
                user.display_name = request.display_name
            self.session.flush()
            return self.get_profile(user_id)

    def reset_password(
        self,
        request: ResetPasswordRequest,
        *,
        correlation_id: UUID | None = None,
        commit: bool = True,
    ) -> None:
        with transaction(self.session) if commit else nullcontext(self.session):
            user, token = self._lock_one_time_token(
                request.token.get_secret_value(),
                (
                    TokenPurpose.PASSWORD_RESET,
                    TokenPurpose.ADMIN_INVITATION,
                    TokenPurpose.STUDENT_PASSWORD_RESET,
                ),
            )
            if token.purpose == TokenPurpose.STUDENT_PASSWORD_RESET:
                if (
                    user.status != UserStatus.ACTIVE
                    or not self._credentials_ready(user)
                    or self._is_staff(user)
                ):
                    raise AppError(400, "Invalid reset token")
            elif not self._is_staff(user):
                raise AppError(400, "Invalid reset token")
            if token.purpose == TokenPurpose.ADMIN_INVITATION:
                if user.status != UserStatus.PENDING_VERIFICATION:
                    raise AppError(400, "Invalid invitation token")
                user.status = UserStatus.ACTIVE
                user.email_verified_at = datetime.now(UTC)
            elif user.status != UserStatus.ACTIVE or not self._credentials_ready(user):
                raise AppError(400, "Invalid reset token")
            user.password_hash = hash_password(request.new_password.get_secret_value())
            self.repository.consume_one_time_token(token, datetime.now(UTC))
            self.repository.invalidate_one_time_tokens(user.id, token.purpose, datetime.now(UTC))
            self._revoke_all(user)
            if token.purpose == TokenPurpose.STUDENT_PASSWORD_RESET:
                self._audit_student(
                    user.id,
                    user,
                    correlation_id or uuid4(),
                    "STUDENT_PASSWORD_RESET",
                    ["credentials"],
                )

    def set_user_status(self, user_id: UUID, status: UserStatus) -> None:
        """Internal mutation; the future Admin workflow must authorize and audit the caller."""
        with transaction(self.session):
            user = self.repository.get_by_id(user_id, for_update=True)
            if user is None:
                raise AppError(404)
            self._apply_status(user, status)

    def _apply_status(self, user: User, status: UserStatus) -> None:
        if status not in (UserStatus.ACTIVE, UserStatus.LOCKED):
            raise ValueError("Expected ACTIVE or LOCKED")
        if status == UserStatus.ACTIVE and not self._credentials_ready(user):
            raise AppError(409, "Account activation required")
        if user.status != status:
            user.status = status
            self._revoke_all(user)

    def admin_create_user(
        self,
        request: AdminCreateUserRequest,
        *,
        actor_id: UUID,
        correlation_id: UUID,
        reason_code: str = "ADMIN_INTERVENTION",
    ) -> tuple[UserSummaryDTO, TokenDelivery]:
        """Caller owns commit; savepoint keeps user, invitation and audit atomic."""
        try:
            with self.session.begin_nested():
                actor = self.repository.lock_users([actor_id]).get(actor_id)
                self._require_admin(actor)
                require_school_scope(actor.school_id, actor.school_id)
                if self.repository.get_by_email(request.email) is not None:
                    raise AppError(409, "Email already registered")
                user = self.repository.create_user(
                    User(
                        email=request.email,
                        password_hash=hash_password(generate_refresh_token()),
                        status=UserStatus.PENDING_VERIFICATION,
                        school_id=actor.school_id,
                    )
                )
                self.session.add_all(
                    RoleAssignment(user_id=user.id, role=role) for role in request.roles
                )
                delivery = self._issue_one_time_token(
                    user,
                    TokenPurpose.ADMIN_INVITATION,
                    timedelta(hours=settings.admin_invitation_expire_hours),
                )
                record_audit(
                    self.session,
                    actor_id=actor_id,
                    school_id=actor.school_id,
                    action="ADMIN_CREATE_USER",
                    target_type="USER",
                    target_id=user.id,
                    correlation_id=correlation_id,
                    metadata_json=AuditMetadata(
                        changed_fields=["roles", "status"],
                        new_status=user.status.value,
                        reason_code=reason_code,
                    ),
                )
                return self._summary(user), delivery
        except IntegrityError as exc:
            if (
                getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                == "uq_users_email"
            ):
                raise AppError(409, "Email already registered") from exc
            raise

    def admin_reissue_user_invitation(
        self,
        user_id: UUID,
        *,
        actor_id: UUID,
        correlation_id: UUID,
        reason_code: str = "ADMIN_INTERVENTION",
    ) -> tuple[UserSummaryDTO, TokenDelivery]:
        try:
            with self.session.begin_nested():
                users = self.repository.lock_users([actor_id, user_id])
                actor, user = users.get(actor_id), users.get(user_id)
                self._require_admin(actor)
                if user is None:
                    raise AppError(404)
                require_school_scope(actor.school_id, user.school_id)
                if (
                    user.status != UserStatus.PENDING_VERIFICATION
                    or user.email_verified_at is not None
                    or not self._is_staff(user)
                ):
                    raise AppError(409, "Only a pending staff invitation can be reissued")
                self.repository.invalidate_one_time_tokens(
                    user.id, TokenPurpose.ADMIN_INVITATION, datetime.now(UTC)
                )
                delivery = self._issue_one_time_token(
                    user,
                    TokenPurpose.ADMIN_INVITATION,
                    timedelta(hours=settings.admin_invitation_expire_hours),
                )
                record_audit(
                    self.session,
                    actor_id=actor_id,
                    school_id=actor.school_id,
                    action="ADMIN_REISSUE_INVITATION",
                    target_type="USER",
                    target_id=user.id,
                    correlation_id=correlation_id,
                    metadata_json=AuditMetadata(
                        changed_fields=["credentials"],
                        new_status=user.status.value,
                        reason_code=reason_code,
                    ),
                )
                return self._summary(user), delivery
        except IntegrityError as exc:
            raise AppError(409, "Invitation could not be reissued") from exc

    def attempt_token_delivery(
        self, token_id: UUID, deliver: Callable[[TokenDelivery], None]
    ) -> str:
        with transaction(self.session):
            token = self.repository.get_one_time_token_by_id(token_id)
            if token is None:
                return "CANCELLED"
            user = self.repository.get_by_id(token.user_id, for_update=True)
            token = self.repository.get_one_time_token_by_id(token_id, for_update=True)
            delivery = self.repository.get_credential_delivery(token_id, for_update=True)
            if delivery is None:
                return "UNTRACKED"
            if delivery.status != "PENDING":
                return delivery.status
            now = datetime.now(UTC)
            if (
                user is None
                or token is None
                or token.consumed_at is not None
                or token.expires_at <= now
                or user.email is None
                or not self._is_staff(user)
            ):
                delivery.status = "CANCELLED"
                delivery.last_error_code = "TOKEN_UNAVAILABLE"
                return delivery.status
            if delivery.available_at > now:
                return "PENDING"
            if token.purpose in (TokenPurpose.EMAIL_VERIFICATION, TokenPurpose.ADMIN_INVITATION):
                valid_account = (
                    user.status == UserStatus.PENDING_VERIFICATION
                    and user.email_verified_at is None
                )
            elif token.purpose == TokenPurpose.PASSWORD_RESET:
                valid_account = (
                    user.status == UserStatus.ACTIVE and user.email_verified_at is not None
                )
            else:
                valid_account = False
            if not valid_account:
                delivery.status = "CANCELLED"
                delivery.last_error_code = "TOKEN_UNAVAILABLE"
                return delivery.status
            raw = derive_email_token(token.id, token.user_id, token.purpose, token.expires_at)
            if hash_refresh_token(raw) != token.token_hash:
                delivery.status = "NEEDS_REISSUE"
                delivery.last_error_code = "DELIVERY_KEY_CHANGED"
                return delivery.status
            delivery.attempts += 1
            try:
                deliver(
                    TokenDelivery(
                        user.email,
                        token.purpose,
                        SecretStr(raw),
                        token.expires_at,
                        token.id,
                    )
                )
            except AppError as exc:
                if exc.status_code != 503:
                    raise
                delivery.available_at = now + timedelta(minutes=15)
                delivery.last_error_code = "SMTP_UNAVAILABLE"
                return "PENDING"
            delivery.status = "DELIVERED"
            delivery.delivered_at = now
            delivery.last_error_code = None
            return delivery.status

    def admin_set_user_status(
        self,
        user_id: UUID,
        status: UserStatus,
        *,
        actor_id: UUID,
        correlation_id: UUID,
        reason_code: str = "ADMIN_INTERVENTION",
    ) -> None:
        with self.session.begin_nested():
            lock_admin_changes(self.session)
            users = self.repository.lock_users([actor_id, user_id])
            self._require_admin(users.get(actor_id))
            user = users.get(user_id)
            if user is None:
                raise AppError(404)
            actor = users[actor_id]
            require_school_scope(actor.school_id, user.school_id)
            previous = user.status.value
            if status == UserStatus.LOCKED and Role.ADMIN in self.repository.get_user_roles(
                user.id
            ):
                ensure_other_admin(self.session, user.id)
            self._apply_status(user, status)
            record_audit(
                self.session,
                actor_id=actor_id,
                school_id=user.school_id,
                action="ADMIN_SET_USER_STATUS",
                target_type="USER",
                target_id=user.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(
                    changed_fields=["status"],
                    previous_status=previous,
                    new_status=user.status.value,
                    reason_code=reason_code,
                ),
            )

    def _require_admin(self, actor: User | None) -> None:
        if (
            actor is None
            or actor.status != UserStatus.ACTIVE
            or actor.email_verified_at is None
            or Role.ADMIN not in self.repository.get_user_roles(actor.id)
        ):
            raise AppError(403)

    def admin_create_student(
        self,
        request: AdminCreateStudentRequest,
        *,
        actor_id: UUID,
        correlation_id: UUID,
    ) -> StudentCode:
        try:
            with self.session.begin_nested():
                actor = self.repository.lock_users([actor_id]).get(actor_id)
                self._require_admin(actor)
                require_school_scope(actor.school_id, actor.school_id)
                if self.repository.get_by_username(request.username) is not None:
                    raise AppError(409, "Username already assigned")
                user = self.repository.create_user(
                    User(
                        username=request.username,
                        school_id=actor.school_id,
                        display_name=request.display_name,
                        email=None,
                        password_hash=hash_password(generate_refresh_token()),
                        status=UserStatus.PENDING_VERIFICATION,
                    )
                )
                self.session.add(RoleAssignment(user_id=user.id, role=Role.STUDENT))
                self.session.flush()
                result = self._issue_student_code(user, TokenPurpose.STUDENT_ACTIVATION)
                self._audit_student(
                    actor_id,
                    user,
                    correlation_id,
                    "ADMIN_CREATE_STUDENT",
                    ["roles", "status", "credentials"],
                )
                return result
        except IntegrityError as exc:
            self._username_conflict(exc)
            raise

    def admin_assign_student_username(
        self,
        user_id: UUID,
        request: AssignStudentUsernameRequest,
        *,
        actor_id: UUID,
        correlation_id: UUID,
    ) -> UserSummaryDTO:
        try:
            with self.session.begin_nested():
                user = self._lock_admin_student(actor_id, user_id)
                if user.username is not None:
                    if user.username != request.username:
                        raise AppError(409, "Username already assigned to this account")
                    return self._summary(user)
                if user.status in (UserStatus.ACTIVE, UserStatus.LOCKED):
                    if user.email_verified_at is None:
                        raise AppError(409, "Legacy account verification required")
                    user.activated_at = datetime.now(UTC)
                user.username = request.username
                for purpose in TokenPurpose:
                    self.repository.invalidate_one_time_tokens(user.id, purpose, datetime.now(UTC))
                self._revoke_all(user)
                self.session.flush()
                self._audit_student(
                    actor_id,
                    user,
                    correlation_id,
                    "ADMIN_ASSIGN_STUDENT_USERNAME",
                    ["username", "credentials"],
                )
                return self._summary(user)
        except IntegrityError as exc:
            self._username_conflict(exc)
            raise

    def admin_issue_student_code(
        self,
        user_id: UUID,
        *,
        actor_id: UUID,
        correlation_id: UUID,
        identity_verified: bool = False,
    ) -> StudentCode:
        with self.session.begin_nested():
            user = self._lock_admin_student(actor_id, user_id)
            if user.username is None:
                raise AppError(409, "Assign a username before issuing a code")
            if user.status == UserStatus.PENDING_VERIFICATION:
                purpose = TokenPurpose.STUDENT_ACTIVATION
            elif user.status == UserStatus.ACTIVE and self._credentials_ready(user):
                if identity_verified is not True:
                    raise AppError(409, "Administrator identity verification required")
                purpose = TokenPurpose.STUDENT_PASSWORD_RESET
                # Verified recovery revokes existing sessions without unlocking the account.
                self._revoke_all(user)
            else:
                raise AppError(409, "Account cannot receive a code in its current state")
            result = self._issue_student_code(user, purpose)
            self._audit_student(
                actor_id,
                user,
                correlation_id,
                "ADMIN_ISSUE_STUDENT_RESET_CODE"
                if purpose == TokenPurpose.STUDENT_PASSWORD_RESET
                else "ADMIN_ISSUE_STUDENT_ACTIVATION_CODE",
                ["credentials"],
            )
            return result

    def activate_student(
        self, request: ActivateStudentRequest, *, correlation_id: UUID, commit: bool = True
    ) -> None:
        with transaction(self.session) if commit else nullcontext(self.session):
            user, token = self._lock_one_time_token(
                request.activation_code.get_secret_value(), TokenPurpose.STUDENT_ACTIVATION
            )
            if (
                user.username != request.username
                or user.status != UserStatus.PENDING_VERIFICATION
                or user.school_id is None
                or self.repository.get_user_roles(user.id) != [Role.STUDENT]
            ):
                raise AppError(400, "Invalid or expired activation code")
            user.password_hash = hash_password(request.new_password.get_secret_value())
            user.status = UserStatus.ACTIVE
            user.activated_at = datetime.now(UTC)
            self.repository.invalidate_one_time_tokens(user.id, token.purpose, datetime.now(UTC))
            self._revoke_all(user)
            self._audit_student(
                user.id, user, correlation_id, "STUDENT_ACTIVATED", ["status", "credentials"]
            )

    def _lock_admin_student(self, actor_id: UUID, user_id: UUID) -> User:
        users = self.repository.lock_users([actor_id, user_id])
        actor, user = users.get(actor_id), users.get(user_id)
        self._require_admin(actor)
        if user is None:
            raise AppError(404)
        require_school_scope(actor.school_id, user.school_id)
        if self.repository.get_user_roles(user.id) != [Role.STUDENT]:
            raise AppError(409, "Expected a Student account without staff roles")
        return user

    @staticmethod
    def _username_conflict(exc: IntegrityError) -> None:
        if getattr(getattr(exc.orig, "diag", None), "constraint_name", None) == "uq_users_username":
            raise AppError(409, "Username already assigned") from exc

    @staticmethod
    def _summary(user: User) -> UserSummaryDTO:
        return UserSummaryDTO(
            id=user.id,
            email=user.email,
            username=user.username,
            school_id=user.school_id,
            display_name=user.display_name,
            status=user.status,
        )

    def _issue_student_code(self, user: User, purpose: TokenPurpose) -> StudentCode:
        now = datetime.now(UTC)
        for previous in (TokenPurpose.STUDENT_ACTIVATION, TokenPurpose.STUDENT_PASSWORD_RESET):
            self.repository.invalidate_one_time_tokens(user.id, previous, now)
        code = generate_refresh_token()
        expiry = now + (
            timedelta(hours=settings.student_activation_expire_hours)
            if purpose == TokenPurpose.STUDENT_ACTIVATION
            else timedelta(minutes=settings.password_reset_expire_minutes)
        )
        self.repository.create_one_time_token(
            OneTimeToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_refresh_token(code),
                expires_at=expiry,
            )
        )
        return StudentCode(
            self._summary(user),
            "ACTIVATION" if purpose == TokenPurpose.STUDENT_ACTIVATION else "PASSWORD_RESET",
            SecretStr(code),
            expiry,
        )

    def _audit_student(
        self,
        actor_id: UUID,
        user: User,
        correlation_id: UUID,
        action: str,
        changed_fields: list,
    ) -> None:
        record_audit(
            self.session,
            actor_id=actor_id,
            school_id=user.school_id,
            action=action,
            target_type="USER",
            target_id=user.id,
            correlation_id=correlation_id,
            metadata_json=AuditMetadata(
                changed_fields=changed_fields,
                new_status=user.status.value,
                reason_code="ADMIN_INTERVENTION" if actor_id != user.id else "USER_REQUEST",
            ),
        )

    def create_data_request(self, user_id: UUID, request: CreateDataRequest) -> DataRequestResponse:
        with transaction(self.session):
            user = self.repository.get_by_id(user_id, for_update=True)
            if user is None or user.status != UserStatus.ACTIVE:
                raise AppError(401)
            data_request = self.repository.create_data_request(
                DataRequest(
                    user_id=user_id,
                    request_type=request.type,
                    reason=request.reason,
                )
            )
            return DataRequestResponse.model_validate(data_request)

    def list_data_requests(
        self, user_id: UUID, pagination: Pagination
    ) -> Page[DataRequestResponse]:
        user = self.repository.get_by_id(user_id)
        if user is None or user.status != UserStatus.ACTIVE:
            raise AppError(401)
        rows = self.repository.list_data_requests(user_id, pagination.limit, pagination.cursor)
        items = rows[: pagination.limit]
        return Page[DataRequestResponse](
            items=[DataRequestResponse.model_validate(item) for item in items],
            next_cursor=encode_cursor(items[-1].id) if len(rows) > pagination.limit else None,
        )

    def _revoke_all(self, user: User) -> None:
        user.session_version += 1
        self.repository.revoke_all_user_sessions(user.id, datetime.now(UTC))

    def _issue_session(
        self, user: User, family_id: UUID, *, expires_at: datetime | None = None
    ) -> AuthTokens:
        refresh = generate_refresh_token()
        expiry = expires_at or datetime.now(UTC) + timedelta(
            days=settings.refresh_token_expire_days
        )
        try:
            access = create_access_token(
                user.id, self.repository.get_user_roles(user.id), user.session_version
            )
        except RuntimeError as exc:
            raise AppError(503, "Authentication unavailable") from exc
        self.repository.create_session(
            AuthSession(
                user_id=user.id,
                refresh_hash=hash_refresh_token(refresh),
                family_id=family_id,
                expires_at=expiry,
            )
        )
        return AuthTokens(
            TokenResponse(
                access_token=access, expires_in=settings.access_token_expire_minutes * 60
            ),
            SecretStr(refresh),
            expiry,
        )

    def _issue_one_time_token(
        self, user: User, purpose: TokenPurpose, lifetime: timedelta
    ) -> TokenDelivery:
        token_id = uuid4()
        expiry = datetime.now(UTC) + lifetime
        email_delivery = purpose in {
            TokenPurpose.PASSWORD_RESET,
            TokenPurpose.ADMIN_INVITATION,
        }
        raw = (
            derive_email_token(token_id, user.id, purpose, expiry)
            if email_delivery
            else generate_refresh_token()
        )
        self.repository.create_one_time_token(
            OneTimeToken(
                id=token_id,
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_refresh_token(raw),
                expires_at=expiry,
            )
        )
        if email_delivery:
            self.session.add(CredentialDelivery(token_id=token_id))
        return TokenDelivery(user.email, purpose, SecretStr(raw), expiry, token_id)

    def _lock_refresh_session(self, raw: str) -> tuple[User, AuthSession]:
        hashed = hash_refresh_token(raw)
        current = self.repository.get_session_by_refresh_hash(hashed)
        if current is None:
            raise AppError(401)
        # All Identity mutations lock the user first, then token/session, to avoid lock inversion.
        user = self.repository.get_by_id(current.user_id, for_update=True)
        current = self.repository.get_session_by_refresh_hash(hashed, for_update=True)
        if user is None or current is None:
            raise AppError(401)
        return user, current

    def _lock_one_time_token(
        self, raw: str, purpose: TokenPurpose | tuple[TokenPurpose, ...]
    ) -> tuple[User, OneTimeToken]:
        hashed = hash_refresh_token(raw)
        token = self.repository.get_one_time_token(hashed, purpose)
        if token is None:
            raise AppError(400, "Invalid or expired token")
        user = self.repository.get_by_id(token.user_id, for_update=True)
        token = self.repository.get_one_time_token(hashed, purpose, for_update=True)
        if (
            user is None
            or token is None
            or token.consumed_at is not None
            or token.expires_at <= datetime.now(UTC)
        ):
            raise AppError(400, "Invalid or expired token")
        return user, token
