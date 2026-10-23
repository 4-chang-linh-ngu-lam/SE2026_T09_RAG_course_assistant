"""Identity-owned Administration operations, re-exported by identity.public.

No ORM objects cross this boundary. Explicit sessions remain caller-owned.
"""

import hashlib
import json
from contextlib import contextmanager, nullcontext
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser, require_school_scope
from app.common.db import SessionLocal, transaction
from app.common.errors import AppError
from app.common.pagination import Page, Pagination, encode_cursor
from app.modules.identity.admin_schemas import (
    AdminReason,
    AdminUserReadDTO,
    DataResolutionCommand,
    RoleUpdateCommand,
    StudentImportCheck,
    StudentImportRow,
)
from app.modules.identity.admin_security import ensure_other_admin, lock_admin_changes
from app.modules.identity.models import (
    DataRequest,
    DataRequestStatus,
    Role,
    RoleAssignment,
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


def _read_actor(db, actor_id):
    # A scalar projection observes current DB state even when a caller-owned
    # session has an older User object in its identity map.
    actor = db.execute(
        select(User.id, User.school_id, User.status, User.email_verified_at).where(
            User.id == actor_id
        )
    ).one_or_none()
    IdentityService(db)._require_admin(actor)
    require_school_scope(actor.school_id, actor.school_id)
    return actor


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


def admin_get_user(
    user_id: UUID, *, actor_id: UUID, session: Session | None = None
) -> AdminUserReadDTO:
    with _scope(session) as db:
        actor = _read_actor(db, actor_id)
        user = IdentityRepository(db).admin_user_projection(actor.school_id, user_id)
        if user is None:
            raise AppError(404)
        return user


def admin_list_users(
    pagination: Pagination, *, actor_id: UUID, session: Session | None = None
) -> Page[AdminUserReadDTO]:
    with _scope(session) as db:
        actor = _read_actor(db, actor_id)
        repository = IdentityRepository(db)
        if (
            pagination.cursor is not None
            and repository.admin_user_projection(actor.school_id, pagination.cursor) is None
        ):
            raise AppError(404)
        rows = repository.admin_user_projections(
            actor.school_id, limit=pagination.limit, cursor=pagination.cursor
        )
        return Page[AdminUserReadDTO](
            items=rows[: pagination.limit],
            next_cursor=encode_cursor(rows[pagination.limit - 1].id)
            if len(rows) > pagination.limit
            else None,
        )


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
                return DataRequestResponse.model_validate(row)
            raise AppError(409, "Data request is already final")
        if command.status in ("COMPLETED", "REJECTED") and not command.identity_verified:
            raise AppError(409, "Administrator identity verification required")
        # No approved retention/deletion or cross-service fulfillment policy yet.
        # A browser flag cannot assert that these actions actually succeeded.
        status = "IN_REVIEW" if command.status == "COMPLETED" else command.status
        note = "POLICY_PENDING" if command.status == "COMPLETED" else command.resolution_note
        if str(row.status) != status or row.resolution_note != note:
            row.status = DataRequestStatus(status)
            row.resolution_note = note
            record_audit(
                db,
                school_id=actor.school_id,
                actor_id=actor_id,
                action="DATA_REQUEST_DEFERRED"
                if command.status == "COMPLETED"
                else "DATA_REQUEST_REVIEWED",
                target_type="DATA_REQUEST",
                target_id=row.id,
                correlation_id=correlation_id,
                metadata_json=AuditMetadata(
                    changed_fields=["data_request_status"],
                    reason_code=reason_code,
                    identity_verified=command.identity_verified,
                ),
            )
            db.flush()
        return DataRequestResponse.model_validate(row)
