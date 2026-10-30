"""Identity-owned Administration operations, re-exported by identity.public.

No ORM objects cross this boundary. Explicit sessions remain caller-owned.
"""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from uuid import UUID

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser, require_school_scope
from app.common.db import SessionLocal, transaction
from app.common.errors import AppError
from app.common.pagination import Page, Pagination, encode_cursor
from app.modules.identity.admin_schemas import (
    AdminReason,
    AdminUserListItem,
    AdminUserUpdateCommand,
    DataResolutionCommand,
    RoleUpdateCommand,
    StudentImportCheck,
    StudentImportRow,
)
from app.modules.identity.admin_security import ensure_other_admin, lock_admin_changes
from app.modules.identity.models import (
    CredentialDelivery,
    DataRequest,
    DataRequestStatus,
    OneTimeToken,
    Role,
    RoleAssignment,
    TokenPurpose,
    User,
    UserStatus,
)
from app.modules.identity.repository import IdentityRepository
from app.modules.identity.schemas import DataRequestResponse, UserSummaryDTO
from app.modules.identity.service import IdentityService


@contextmanager
def _scope(session: Session | None, *, write=False):
    with (
        SessionLocal() if session is None else nullcontext(session) as db,
        transaction(db) if write and session is None else nullcontext(db),
    ):
        yield db


def _actor(db, actor_id, *, lock=False):
    user = IdentityRepository(db).get_by_id(actor_id, for_update=lock)
    IdentityService(db)._require_admin(user)
    require_school_scope(user.school_id, user.school_id)
    return user


def admin_actor(
    actor_id: UUID,
    *,
    session: Session | None = None,
    lock: bool = False,
    related_user_ids: list[UUID] | None = None,
) -> CurrentUser:
    with _scope(session) as db:
        if lock:
            user = (
                IdentityRepository(db)
                .lock_users([actor_id, *(related_user_ids or [])])
                .get(actor_id)
            )
            IdentityService(db)._require_admin(user)
            require_school_scope(user.school_id, user.school_id)
        else:
            user = _actor(db, actor_id)
        return CurrentUser(
            id=user.id,
            school_id=user.school_id,
            roles=[str(role) for role in IdentityRepository(db).get_user_roles(user.id)],
            status=str(user.status),
            session_version=user.session_version,
        )


def admin_list_users(
    pagination: Pagination,
    *,
    actor_id: UUID,
    user_id: UUID | None = None,
    account_type: str | None = None,
    role: str | None = None,
    status: str | None = None,
    search: str | None = None,
    username_missing: bool = False,
    session: Session | None = None,
) -> Page[AdminUserListItem]:
    with _scope(session) as db:
        actor = _actor(db, actor_id)
        query = select(User).where(User.school_id == actor.school_id)
        if user_id is not None:
            query = query.where(User.id == user_id)
        if account_type is not None:
            if account_type == "STUDENT":
                account_roles = [Role.STUDENT]
            elif account_type == "STAFF":
                account_roles = [Role.ADMIN, Role.LECTURER]
            else:
                raise AppError(422, "Unknown account type")
            query = query.where(
                exists(
                    select(RoleAssignment.id).where(
                        RoleAssignment.user_id == User.id,
                        RoleAssignment.role.in_(account_roles),
                    )
                )
            )
        if username_missing:
            query = query.where(User.username.is_(None))
        if role is not None:
            try:
                selected_role = Role(role)
            except ValueError:
                raise AppError(422, "Unknown account role") from None
            query = query.where(
                exists(
                    select(RoleAssignment.id).where(
                        RoleAssignment.user_id == User.id,
                        RoleAssignment.role == selected_role,
                    )
                )
            )
        if status is not None:
            try:
                selected_status = UserStatus(status)
            except ValueError:
                raise AppError(422, "Unknown account status") from None
            query = query.where(User.status == selected_status)
        if search:
            value = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            if value:
                pattern = f"%{value}%"
                query = query.where(
                    or_(
                        User.email.ilike(pattern, escape="\\"),
                        User.username.ilike(pattern, escape="\\"),
                        User.display_name.ilike(pattern, escape="\\"),
                    )
                )
        if pagination.cursor is not None:
            query = query.where(User.id > pagination.cursor)
        rows = list(db.scalars(query.order_by(User.id).limit(pagination.limit + 1)))
        users = rows[: pagination.limit]
        user_ids = [user.id for user in users]
        role_rows = (
            db.execute(
                select(RoleAssignment.user_id, RoleAssignment.role).where(
                    RoleAssignment.user_id.in_(user_ids)
                )
            ).all()
            if user_ids
            else []
        )
        roles_by_user: dict[UUID, list[str]] = {}
        for role_user_id, assigned_role in role_rows:
            roles_by_user.setdefault(role_user_id, []).append(str(assigned_role))
        active_admin_count = (
            db.scalar(
                select(func.count(User.id))
                .join(RoleAssignment, RoleAssignment.user_id == User.id)
                .where(
                    User.school_id == actor.school_id,
                    User.status == UserStatus.ACTIVE,
                    User.email_verified_at.is_not(None),
                    RoleAssignment.role == Role.ADMIN,
                )
            )
            or 0
        )
        invitation_rows = (
            db.execute(
                select(
                    OneTimeToken.user_id,
                    OneTimeToken.expires_at,
                    CredentialDelivery.status,
                )
                .join(CredentialDelivery, CredentialDelivery.token_id == OneTimeToken.id)
                .where(
                    OneTimeToken.user_id.in_(user_ids),
                    OneTimeToken.purpose == TokenPurpose.ADMIN_INVITATION,
                    OneTimeToken.consumed_at.is_(None),
                )
                .order_by(OneTimeToken.created_at.desc())
            ).all()
            if user_ids
            else []
        )
        invitations = {}
        for invitation_user_id, expires_at, delivery_status in invitation_rows:
            invitations.setdefault(invitation_user_id, (expires_at, delivery_status))
        items = []
        for user in users:
            assigned = roles_by_user.get(user.id, [])
            expires_at, delivery_status = invitations.get(user.id, (None, None))
            items.append(
                AdminUserListItem(
                    id=user.id,
                    email=user.email,
                    username=user.username,
                    school_id=user.school_id,
                    display_name=user.display_name,
                    status=str(user.status),
                    roles=assigned,
                    revision=user.session_version,
                    created_at=user.created_at,
                    email_verified=user.email_verified_at is not None,
                    activation_required=(
                        user.status == UserStatus.PENDING_VERIFICATION
                        and Role.STUDENT in {Role(value) for value in assigned}
                    ),
                    last_admin=(
                        Role.ADMIN.value in assigned
                        and user.status == UserStatus.ACTIVE
                        and user.email_verified_at is not None
                        and active_admin_count == 1
                    ),
                    invitation_expires_at=expires_at,
                    invitation_delivery_status=delivery_status,
                )
            )
        return Page[AdminUserListItem](
            items=items,
            next_cursor=encode_cursor(users[-1].id) if len(rows) > pagination.limit else None,
        )


def admin_update_account(
    user_id: UUID,
    command: AdminUserUpdateCommand,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    reason_code: AdminReason,
    session: Session | None = None,
) -> UserSummaryDTO:
    with _scope(session, write=True) as db, db.begin_nested():
        lock_admin_changes(db)
        repository = IdentityRepository(db)
        users = repository.lock_users([actor_id, user_id])
        actor, user = users.get(actor_id), users.get(user_id)
        service = IdentityService(db)
        service._require_admin(actor)
        if user is None:
            raise AppError(404)
        require_school_scope(actor.school_id, user.school_id)
        if user.session_version != command.expected_revision:
            raise AppError(409, "Account changed; reload before updating")

        current_roles = set(repository.get_user_roles(user.id))
        desired_roles = (
            {Role(role) for role in command.roles} if command.roles is not None else current_roles
        )
        desired_status = UserStatus(command.status) if command.status is not None else user.status
        roles_changed = desired_roles != current_roles
        status_changed = desired_status != user.status
        if status_changed and desired_status == UserStatus.PENDING_VERIFICATION:
            raise AppError(409, "An account cannot return to pending verification")

        if (
            (roles_changed or status_changed)
            and Role.ADMIN in current_roles
            and (Role.ADMIN not in desired_roles or desired_status == UserStatus.LOCKED)
        ):
            ensure_other_admin(db, user.id)
        if roles_changed:
            if desired_roles & {Role.ADMIN, Role.LECTURER} and user.email is None:
                raise AppError(409, "Staff roles require staff credentials")
            if desired_roles == {Role.STUDENT} and user.username is None:
                raise AppError(409, "Student credential migration required")
            db.execute(delete(RoleAssignment).where(RoleAssignment.user_id == user.id))
            db.add_all(RoleAssignment(user_id=user.id, role=role) for role in desired_roles)
            db.flush()
        if desired_status == UserStatus.ACTIVE and not service._credentials_ready(user):
            raise AppError(409, "Account activation required")
        if status_changed:
            service._apply_status(user, desired_status)
        elif roles_changed:
            service._revoke_all(user)
        changed_fields = []
        if roles_changed:
            changed_fields.append("roles")
        if status_changed:
            changed_fields.append("status")
        if changed_fields:
            record_audit(
                db,
                actor_id=actor_id,
                school_id=actor.school_id,
                action="ADMIN_UPDATE_USER",
                target_type="USER",
                target_id=user.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(
                    changed_fields=changed_fields,
                    new_status=user.status.value,
                    reason_code=reason_code,
                ),
            )
        return IdentityService._summary(user)


def admin_update_user_roles(
    user_id: UUID,
    roles: list[str],
    *,
    actor_id: UUID,
    correlation_id: UUID,
    reason_code: AdminReason = "ADMIN_INTERVENTION",
    session: Session | None = None,
) -> UserSummaryDTO:
    command = RoleUpdateCommand(roles=roles)
    with _scope(session, write=True) as db, db.begin_nested():
        lock_admin_changes(db)
        repository = IdentityRepository(db)
        users = repository.lock_users([actor_id, user_id])
        actor = users.get(actor_id)
        IdentityService(db)._require_admin(actor)
        user = users.get(user_id)
        if user is None:
            raise AppError(404)
        require_school_scope(actor.school_id, user.school_id)
        current = set(repository.get_user_roles(user_id))
        desired = {Role(role) for role in command.roles}
        if desired != current:
            if Role.ADMIN in current and Role.ADMIN not in desired:
                ensure_other_admin(db, user_id)
            if desired & {Role.ADMIN, Role.LECTURER} and user.email is None:
                raise AppError(409, "Staff roles require staff credentials")
            if desired == {Role.STUDENT} and user.username is None:
                raise AppError(409, "Student credential migration required")
            db.execute(delete(RoleAssignment).where(RoleAssignment.user_id == user_id))
            db.add_all(RoleAssignment(user_id=user_id, role=role) for role in desired)
            db.flush()
            service = IdentityService(db)
            if user.status == UserStatus.ACTIVE and not service._credentials_ready(user):
                raise AppError(409, "Credential verification required")
            service._revoke_all(user)
            record_audit(
                db,
                school_id=user.school_id,
                actor_id=actor_id,
                action="ADMIN_UPDATE_USER_ROLES",
                target_type="USER",
                target_id=user.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(changed_fields=["roles"], reason_code=reason_code),
            )
        return IdentityService._summary(user)


def admin_check_student_import(
    rows: list[StudentImportRow], *, actor_id: UUID, session: Session | None = None
) -> list[StudentImportCheck]:
    with _scope(session) as db:
        actor = _actor(db, actor_id)
        repository = IdentityRepository(db)
        checks = []
        for row in rows:
            by_name = repository.get_by_username(row.username)
            user = repository.get_by_id(row.user_id) if row.user_id else by_name
            error = None
            action = "CREATE"
            if row.user_id and user is None:
                error = "ACCOUNT_UNAVAILABLE"
            elif user is not None:
                if user.school_id != actor.school_id or set(repository.get_user_roles(user.id)) != {
                    Role.STUDENT
                }:
                    error = "ACCOUNT_UNAVAILABLE"
                elif by_name is not None and by_name.id != user.id:
                    error = "USERNAME_UNAVAILABLE"
                elif user.username not in (None, row.username):
                    error = "USERNAME_MISMATCH"
                elif row.display_name is not None and row.display_name != user.display_name:
                    error = "DISPLAY_NAME_MISMATCH"
                elif user.username is None:
                    action = "ASSIGN_USERNAME"
                    if (
                        user.status in (UserStatus.ACTIVE, UserStatus.LOCKED)
                        and user.email_verified_at is None
                    ):
                        error = "LEGACY_VERIFICATION_REQUIRED"
                else:
                    action = "EXISTING"
            state = {
                "row": row.model_dump(mode="json"),
                "user": None
                if user is None
                else {
                    "id": str(user.id),
                    "school": str(user.school_id),
                    "username": user.username,
                    "name": user.display_name,
                    "status": str(user.status),
                    "version": user.session_version,
                    "verified": str(user.email_verified_at),
                    "activated": str(user.activated_at),
                    "roles": sorted(str(role) for role in repository.get_user_roles(user.id)),
                },
            }
            fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
            checks.append(
                StudentImportCheck(
                    action="ERROR" if error else action,
                    user_id=user.id if user is not None and error is None else None,
                    error=error,
                    fingerprint=fingerprint,
                )
            )
        return checks


def admin_get_data_request(
    request_id: UUID, *, actor_id: UUID, session: Session | None = None
) -> DataRequestResponse:
    with _scope(session) as db:
        actor = _actor(db, actor_id)
        row = db.get(DataRequest, request_id)
        user = IdentityRepository(db).get_by_id(row.user_id) if row is not None else None
        if user is None:
            raise AppError(404)
        require_school_scope(actor.school_id, user.school_id)
        return DataRequestResponse.model_validate(row)


def admin_list_data_requests(
    pagination: Pagination, *, actor_id: UUID, session: Session | None = None
) -> Page[DataRequestResponse]:
    from app.modules.identity.models import User

    with _scope(session) as db:
        actor = _actor(db, actor_id)
        query = (
            select(DataRequest)
            .join(User, User.id == DataRequest.user_id)
            .where(User.school_id == actor.school_id)
        )
        if pagination.cursor is not None:
            admin_get_data_request(pagination.cursor, actor_id=actor_id, session=db)
            query = query.where(DataRequest.id > pagination.cursor)
        rows = list(db.scalars(query.order_by(DataRequest.id).limit(pagination.limit + 1)))
        return Page[DataRequestResponse](
            items=[DataRequestResponse.model_validate(row) for row in rows[: pagination.limit]],
            next_cursor=encode_cursor(rows[pagination.limit - 1].id)
            if len(rows) > pagination.limit
            else None,
        )


def admin_resolve_data_request(
    request_id: UUID,
    command: DataResolutionCommand,
    *,
    actor_id: UUID,
    correlation_id: UUID,
    reason_code: AdminReason = "USER_REQUEST",
    session: Session | None = None,
) -> DataRequestResponse:
    with _scope(session, write=True) as db, db.begin_nested():
        actor = _actor(db, actor_id, lock=True)
        row = db.scalar(
            select(DataRequest)
            .where(DataRequest.id == request_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        user = IdentityRepository(db).get_by_id(row.user_id) if row is not None else None
        if user is None:
            raise AppError(404)
        require_school_scope(actor.school_id, user.school_id)
        if row.status in (DataRequestStatus.COMPLETED, DataRequestStatus.REJECTED):
            if str(row.status) == command.status and row.resolution_note == command.resolution_note:
                if command.status in ("COMPLETED", "REJECTED") and not command.identity_verified:
                    raise AppError(409, "Administrator identity verification required")
                if (
                    command.status == "COMPLETED"
                    and str(row.request_type) != "DELETE"
                    and not command.manual_fulfillment_confirmed
                ):
                    raise AppError(409, "Manual fulfillment confirmation required")
                return DataRequestResponse.model_validate(row)
            raise AppError(409, "Data request is already final")
        if command.status in ("COMPLETED", "REJECTED") and not command.identity_verified:
            raise AppError(409, "Administrator identity verification required")
        action = "DATA_REQUEST_REVIEWED"
        manual_fulfillment_confirmed = None
        if command.status == "COMPLETED" and str(row.request_type) == "DELETE":
            # The approved MVP workflow deliberately keeps delete requests pending until
            # retention rules and acknowledgements from every owning service exist.
            status, note, action = "IN_REVIEW", "POLICY_PENDING", "DATA_REQUEST_DEFERRED"
        elif command.status == "COMPLETED":
            if not command.manual_fulfillment_confirmed or (
                command.resolution_note != "MANUAL_FULFILLMENT_CONFIRMED"
            ):
                raise AppError(409, "Manual fulfillment confirmation required")
            # Admin attests that ACCESS/EXPORT used the approved secure handoff, or that
            # the owning service completed CORRECTION. Core never stores or sends payloads.
            status, note, action = (
                "COMPLETED",
                "MANUAL_FULFILLMENT_CONFIRMED",
                "DATA_REQUEST_FULFILLED_MANUALLY",
            )
            manual_fulfillment_confirmed = True
        else:
            status, note = command.status, command.resolution_note
        if str(row.status) != status or row.resolution_note != note:
            row.status = DataRequestStatus(status)
            row.resolution_note = note
            record_audit(
                db,
                school_id=actor.school_id,
                actor_id=actor_id,
                action=action,
                target_type="DATA_REQUEST",
                target_id=row.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(
                    changed_fields=["data_request_status"],
                    reason_code=reason_code,
                    identity_verified=command.identity_verified,
                    manual_fulfillment_confirmed=manual_fulfillment_confirmed,
                ),
            )
            db.flush()
        return DataRequestResponse.model_validate(row)
