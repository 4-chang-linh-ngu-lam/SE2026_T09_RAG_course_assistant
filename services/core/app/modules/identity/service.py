from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
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
from app.modules.identity.models import (
    AuthSession,
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
    AdminCreateUserRequest,
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


@dataclass(frozen=True)
class RegistrationResult:
    response: RegisterResponse
    delivery: TokenDelivery = field(repr=False)


@dataclass(frozen=True)
class AuthTokens:
    response: TokenResponse = field(repr=False)
    refresh_token: SecretStr = field(repr=False)
    refresh_expires_at: datetime


class IdentityService:
    """Auth/profile/request mutations commit; Admin helpers use savepoints in a caller-owned unit."""

    def __init__(self, session: Session):
        self.session = session
        self.repository = IdentityRepository(session)

    def register(
        self, request: RegisterRequest, *, deliver: Callable[[TokenDelivery], None] | None = None
    ) -> RegistrationResult:
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
            if user.status != UserStatus.PENDING_VERIFICATION:
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
                or user.email_verified_at is None
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
        user = self.repository.get_by_email(request.email, for_update=True)
        password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
        password_valid = verify_password(request.password.get_secret_value(), password_hash)
        if (
            user is None
            or not password_valid
            or user.status != UserStatus.ACTIVE
            or user.email_verified_at is None
        ):
            raise AppError(401)
        return user

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
                or user.email_verified_at is None
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
        *,
        deliver: Callable[[TokenDelivery], None] | None = None,
    ) -> TokenDelivery | None:
        with transaction(self.session):
            user = self.repository.get_by_email(request.email, for_update=True)
            if user is None or user.status != UserStatus.ACTIVE or user.email_verified_at is None:
                return None
            self.repository.invalidate_one_time_tokens(
                user.id, TokenPurpose.PASSWORD_RESET, datetime.now(UTC)
            )
            delivery = self._issue_one_time_token(
                user,
                TokenPurpose.PASSWORD_RESET,
                timedelta(minutes=settings.password_reset_expire_minutes),
            )
            if deliver is not None:
                deliver(delivery)
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

    def reset_password(self, request: ResetPasswordRequest) -> None:
        with transaction(self.session):
            user, token = self._lock_one_time_token(
                request.token.get_secret_value(),
                (TokenPurpose.PASSWORD_RESET, TokenPurpose.ADMIN_INVITATION),
            )
            if token.purpose == TokenPurpose.ADMIN_INVITATION:
                if user.status != UserStatus.PENDING_VERIFICATION:
                    raise AppError(400, "Invalid invitation token")
                user.status = UserStatus.ACTIVE
                user.email_verified_at = datetime.now(UTC)
            elif user.status != UserStatus.ACTIVE or user.email_verified_at is None:
                raise AppError(400, "Invalid reset token")
            user.password_hash = hash_password(request.new_password.get_secret_value())
            self.repository.consume_one_time_token(token, datetime.now(UTC))
            self.repository.invalidate_one_time_tokens(user.id, token.purpose, datetime.now(UTC))
            self._revoke_all(user)

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
        if status == UserStatus.ACTIVE and user.email_verified_at is None:
            raise AppError(409, "Email verification required")
        if user.status != status:
            user.status = status
            self._revoke_all(user)

    def admin_create_user(
        self,
        request: AdminCreateUserRequest,
        *,
        actor_id: UUID,
        correlation_id: UUID,
        deliver: Callable[[TokenDelivery], None] | None = None,
    ) -> tuple[UserSummaryDTO, SecretStr]:
        """Caller owns commit; savepoint keeps user, invitation and audit atomic."""
        try:
            with self.session.begin_nested():
                actor = self.repository.lock_users([actor_id]).get(actor_id)
                self._require_admin(actor)
                if self.repository.get_by_email(request.email) is not None:
                    raise AppError(409, "Email already registered")
                user = self.repository.create_user(
                    User(
                        email=request.email,
                        password_hash=hash_password(generate_refresh_token()),
                        status=UserStatus.PENDING_VERIFICATION,
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
                    action="ADMIN_CREATE_USER",
                    target_type="USER",
                    target_id=user.id,
                    correlation_id=correlation_id,
                    metadata_json=AuditMetadata(
                        changed_fields=["roles", "status"],
                        new_status=user.status.value,
                        reason_code="ADMIN_INTERVENTION",
                    ),
                )
                if deliver is not None:
                    deliver(delivery)
                return UserSummaryDTO(
                    id=user.id, email=user.email, status=user.status
                ), delivery.token
        except IntegrityError as exc:
            if (
                getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
                == "uq_users_email"
            ):
                raise AppError(409, "Email already registered") from exc
            raise

    def admin_set_user_status(
        self,
        user_id: UUID,
        status: UserStatus,
        *,
        actor_id: UUID,
        correlation_id: UUID,
    ) -> None:
        with self.session.begin_nested():
            users = self.repository.lock_users([actor_id, user_id])
            self._require_admin(users.get(actor_id))
            user = users.get(user_id)
            if user is None:
                raise AppError(404)
            previous = user.status.value
            self._apply_status(user, status)
            record_audit(
                self.session,
                actor_id=actor_id,
                action="ADMIN_SET_USER_STATUS",
                target_type="USER",
                target_id=user.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(
                    changed_fields=["status"],
                    previous_status=previous,
                    new_status=user.status.value,
                    reason_code="ADMIN_INTERVENTION",
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
        raw = generate_refresh_token()
        expiry = datetime.now(UTC) + lifetime
        self.repository.create_one_time_token(
            OneTimeToken(
                user_id=user.id,
                purpose=purpose,
                token_hash=hash_refresh_token(raw),
                expires_at=expiry,
            )
        )
        return TokenDelivery(user.email, purpose, SecretStr(raw), expiry)

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
