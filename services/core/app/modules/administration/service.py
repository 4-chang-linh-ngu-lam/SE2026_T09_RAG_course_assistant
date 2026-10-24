from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.audit import AuditMetadata, record_audit
from app.common.db import transaction
from app.common.errors import AppError
from app.common.pagination import Page, Pagination, encode_cursor
from app.modules.administration.import_parser import parse_students
from app.modules.administration.models import StudentImportBatch
from app.modules.administration.repository import AdministrationRepository
from app.modules.administration.schemas import (
    AuditEventResponse,
    ImportConfirmResponse,
    ImportErrorResponse,
    ImportPreviewItem,
    ImportPreviewRequest,
    ImportPreviewResponse,
    ImportResultItem,
)
from app.modules.classroom import public as classroom
from app.modules.identity import public as identity


class AdministrationService:
    def __init__(self, session: Session, correlation_id: UUID):
        self.session = session
        self.correlation_id = correlation_id
        self.repository = AdministrationRepository(session)

    def list_users(self, actor_id: UUID, pagination: Pagination):
        return identity.admin_list_users(pagination, actor_id=actor_id, session=self.session)

    def get_user(self, actor_id: UUID, user_id: UUID):
        return identity.admin_get_user(user_id, actor_id=actor_id, session=self.session)

    def _audit(
        self, actor, action, target_id, *, reason="ADMIN_INTERVENTION", target_type="IMPORT"
    ):
        record_audit(
            self.session,
            school_id=actor.school_id,
            actor_id=actor.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            correlation_id=self.correlation_id,
            metadata_json=AuditMetadata(reason_code=reason),
        )

    def create_staff(self, actor_id, request, sender, reason):
        with transaction(self.session):
            identity.admin_actor(actor_id, session=self.session)
            user, _token = identity.admin_create_user(
                str(request.email),
                request.roles,
                actor_id=actor_id,
                correlation_id=self.correlation_id,
                session=self.session,
                deliver=sender.send,
                reason_code=reason,
            )
            return user

    def set_status(self, actor_id, user_id, status, reason):
        with transaction(self.session):
            identity.admin_set_user_status(
                user_id,
                status,
                actor_id=actor_id,
                correlation_id=self.correlation_id,
                reason_code=reason,
                session=self.session,
            )

    def set_roles(self, actor_id, user_id, roles, reason):
        with transaction(self.session):
            return identity.admin_update_user_roles(
                user_id,
                roles,
                actor_id=actor_id,
                correlation_id=self.correlation_id,
                reason_code=reason,
                session=self.session,
            )

    def list_audits(
        self,
        actor_id: UUID,
        pagination: Pagination,
        *,
        filter_actor: UUID | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ):
        if since is not None and until is not None and since > until:
            raise AppError(422, "Invalid time interval")
        with transaction(self.session):
            actor = identity.admin_actor(actor_id, session=self.session, lock=True)
            rows = self.repository.audit_events(
                actor.school_id,
                limit=pagination.limit,
                cursor=pagination.cursor,
                actor_id=filter_actor,
                action=action,
                since=since,
                until=until,
            )
            items = []
            for row in rows[: pagination.limit]:
                try:
                    safe = AuditMetadata.model_validate(row.metadata_json).model_dump(
                        exclude_none=True
                    )
                except ValidationError:
                    safe = {}  # Never reflect legacy/unreviewed metadata fields.
                items.append(
                    AuditEventResponse(
                        id=row.id,
                        actor_id=row.actor_id,
                        action=row.action,
                        target_type=row.target_type,
                        target_id=row.target_id,
                        correlation_id=row.correlation_id,
                        metadata_json=safe,
                        occurred_at=row.occurred_at,
                    )
                )
            result = Page[AuditEventResponse](
                items=items,
                next_cursor=encode_cursor(items[-1].id) if len(rows) > pagination.limit else None,
            )
            self._audit(actor, "ADMIN_VIEW_AUDIT_EVENTS", actor.id, target_type="USER")
            return result

    def list_data_requests(self, actor_id, pagination):
        with transaction(self.session):
            actor = identity.admin_actor(actor_id, session=self.session, lock=True)
            result = identity.admin_list_data_requests(
                pagination, actor_id=actor_id, session=self.session
            )
            self._audit(actor, "ADMIN_VIEW_DATA_REQUESTS", actor.id, target_type="USER")
            return result

    def get_data_request(self, actor_id, request_id):
        with transaction(self.session):
            actor = identity.admin_actor(actor_id, session=self.session, lock=True)
            result = identity.admin_get_data_request(
                request_id, actor_id=actor_id, session=self.session
            )
            self._audit(actor, "ADMIN_VIEW_DATA_REQUEST", request_id, target_type="DATA_REQUEST")
            return result

    def resolve_data_request(self, actor_id, request_id, command, reason):
        with transaction(self.session):
            return identity.admin_resolve_data_request(
                request_id,
                command,
                actor_id=actor_id,
                correlation_id=self.correlation_id,
                reason_code=reason,
                session=self.session,
            )

    def preview_students(
        self, actor_id: UUID, request: ImportPreviewRequest
    ) -> ImportPreviewResponse:
        with transaction(self.session):
            actor = identity.admin_actor(actor_id, session=self.session, lock=True)
            rows, errors = parse_students(request)
            checks = identity.admin_check_student_import(
                [identity.StudentImportRow.model_validate(row["values"]) for row in rows],
                actor_id=actor_id,
                session=self.session,
            )
            for row, check in zip(rows, checks, strict=True):
                if check.error:
                    errors.append(ImportErrorResponse(row=row["number"], code=check.error))
            roster = (
                classroom.admin_preview_roster(
                    request.homeroom_class_id, actor_id=actor_id, session=self.session
                )
                if request.homeroom_class_id
                else None
            )
            preview_id = uuid4()
            if errors:
                self._audit(actor, "ADMIN_IMPORT_PREVIEW_REJECTED", preview_id)
                return ImportPreviewResponse(valid=False, errors=errors)
            now = self.session.scalar(select(func.clock_timestamp()))
            batch = StudentImportBatch(
                id=preview_id,
                school_id=actor.school_id,
                actor_id=actor_id,
                status="PREVIEW",
                rows_json=rows,
                checks_json=[check.model_dump(mode="json") for check in checks],
                results_json=[],
                homeroom_id=request.homeroom_class_id,
                roster_version=roster.roster_version if roster else None,
                expires_at=now + timedelta(minutes=30),
            )
            self.session.add(batch)
            self._audit(actor, "ADMIN_IMPORT_PREVIEW", batch.id)
            return ImportPreviewResponse(
                valid=True,
                preview_id=batch.id,
                expires_at=batch.expires_at,
                items=[
                    ImportPreviewItem(
                        row=row["number"],
                        username=row["values"]["username"],
                        action=check.action,
                        user_id=check.user_id,
                    )
                    for row, check in zip(rows, checks, strict=True)
                ],
            )

    def confirm_students(
        self, actor_id: UUID, preview_id: UUID, reason: str
    ) -> ImportConfirmResponse:
        with transaction(self.session):
            actor = identity.admin_actor(actor_id, session=self.session)
            batch = self.repository.batch(preview_id, actor.id, actor.school_id)
            # Acquire all existing users in UUID order before calling Identity
            # helpers, avoiding actor/target lock inversion across batch imports.
            identity.admin_actor(
                actor_id,
                session=self.session,
                lock=True,
                related_user_ids=[
                    UUID(check["user_id"]) for check in batch.checks_json if check["user_id"]
                ],
            )
            if batch.status == "COMPLETED":
                summaries = identity.get_users_summaries(
                    [UUID(row["user_id"]) for row in batch.results_json], session=self.session
                )
                items = []
                for row in batch.results_json:
                    user = summaries.get(UUID(row["user_id"]))
                    if user is None or user.school_id != actor.school_id:
                        raise AppError(404)
                    items.append(
                        ImportResultItem(row=row["row"], outcome=row["outcome"], student=user)
                    )
                return ImportConfirmResponse(preview_id=preview_id, replayed=True, items=items)
            if batch.expires_at <= self.session.scalar(select(func.clock_timestamp())):
                raise AppError(409, "Import preview expired")
            rows = [
                identity.StudentImportRow.model_validate(row["values"]) for row in batch.rows_json
            ]
            checks = identity.admin_check_student_import(
                rows, actor_id=actor_id, session=self.session
            )
            if [check.model_dump(mode="json") for check in checks] != batch.checks_json:
                raise AppError(409, "Accounts changed; preview the import again")
            if batch.homeroom_id:
                roster = classroom.admin_preview_roster(
                    batch.homeroom_id, actor_id=actor_id, session=self.session, lock=True
                )
                if roster.roster_version != batch.roster_version:
                    raise AppError(409, "Roster changed; preview the import again")
            results = []
            for stored, row, check in zip(batch.rows_json, rows, checks, strict=True):
                code, expires = None, None
                if check.action == "CREATE":
                    provision = identity.admin_create_student(
                        row.username,
                        display_name=row.display_name,
                        actor_id=actor_id,
                        correlation_id=self.correlation_id,
                        session=self.session,
                    )
                    user, code, expires = (
                        provision.student,
                        provision.code.get_secret_value(),
                        provision.expires_at,
                    )
                    outcome = "CREATED"
                elif check.action == "ASSIGN_USERNAME":
                    user = identity.admin_assign_student_username(
                        check.user_id,
                        row.username,
                        actor_id=actor_id,
                        correlation_id=self.correlation_id,
                        session=self.session,
                    )
                    outcome = "USERNAME_ASSIGNED"
                else:
                    user = identity.get_user_summary(check.user_id, session=self.session)
                    outcome = "EXISTING"
                results.append(
                    ImportResultItem(
                        row=stored["number"],
                        outcome=outcome,
                        student=user,
                        code=code,
                        expires_at=expires,
                    )
                )
            if batch.homeroom_id:
                classroom.admin_append_roster(
                    batch.homeroom_id,
                    [row.student.id for row in results],
                    expected_roster_version=batch.roster_version,
                    actor_id=actor_id,
                    correlation_id=self.correlation_id,
                    reason_code=reason,
                    session=self.session,
                )
            batch.results_json = [
                {"row": item.row, "outcome": item.outcome, "user_id": str(item.student.id)}
                for item in results
            ]
            batch.status = "COMPLETED"
            batch.rows_json = []  # Discard staging names; never persist raw codes.
            self._audit(actor, "ADMIN_IMPORT_CONFIRMED", batch.id, reason=reason)
            return ImportConfirmResponse(preview_id=batch.id, replayed=False, items=results)
