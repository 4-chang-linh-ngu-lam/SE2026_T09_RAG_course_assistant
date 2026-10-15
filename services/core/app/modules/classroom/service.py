import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser
from app.common.db import transaction
from app.common.errors import AppError
from app.common.outbox import record_outbox_event
from app.common.pagination import Page, Pagination, encode_cursor
from app.modules.classroom.models import (
    Class,
    ClassMembership,
    ClassRole,
    ClassStatus,
    CoLecturerInvitation,
    CoLecturerInvitationStatus,
    Course,
    JoinRequest,
    JoinRequestStatus,
    MembershipStatus,
)
from app.modules.classroom.permissions import is_admin, require_class_lecturer, require_class_role
from app.modules.classroom.repository import ClassroomRepository
from app.modules.classroom.schemas import (
    ClassCreateRequest,
    ClassResponse,
    ClassUpdateRequest,
    CoLecturerInvitationResponse,
    CoLecturerInviteRequest,
    CourseCreateRequest,
    CourseResponse,
    JoinRequestCreatedResponse,
    JoinRequestResponse,
    MembershipResponse,
    OwnershipTransferRequest,
)
from app.modules.identity.public import check_user_is_lecturer

_JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_JOIN_CODE_LENGTH = 8
_CO_LECTURER_INVITATION_TTL = timedelta(days=7)


def generate_join_code() -> str:
    """Crockford-like alphabet (no I/O/0/1) so codes survive transcription."""
    return "".join(secrets.choice(_JOIN_CODE_ALPHABET) for _ in range(_JOIN_CODE_LENGTH))


def hash_join_code(code: str) -> str:
    """SHA-256 of the uppercased code; the raw code is never persisted."""
    normalized = code.strip().upper()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ClassroomService:
    """Business rules commit per unit of work; Admin-intervention paths audit with reason."""

    def __init__(self, session, correlation_id: UUID | None = None):
        self.session = session
        self.repository = ClassroomRepository(session)
        # Injected from X-Correlation-ID by the router; None in direct unit use.
        self.correlation_id = correlation_id

    # -- Course ----------------------------------------------------------------

    def create_course(self, user: CurrentUser, request: CourseCreateRequest) -> CourseResponse:
        """Creates a catalog course; LECTURER or ADMIN (409 on duplicate code)."""
        if not (check_user_is_lecturer(user.id, session=self.session) or is_admin(user)):
            raise AppError(403)
        with transaction(self.session):
            if self.repository.get_course_by_code(request.code) is not None:
                raise AppError(409, "Course code already exists")
            try:
                course = self.repository.create_course(
                    Course(code=request.code, name=request.name, description=request.description)
                )
            except IntegrityError as exc:
                if _constraint(exc) == "courses_code_key":
                    raise AppError(409, "Course code already exists") from exc
                raise
            return CourseResponse.model_validate(course)

    def list_courses(self, pagination: Pagination) -> Page[CourseResponse]:
        rows = self.repository.list_courses(pagination.limit, pagination.cursor)
        return _page(rows, pagination.limit, CourseResponse)

    # -- Class -------------------------------------------------------------------

    def create_class(
        self, user: CurrentUser, request: ClassCreateRequest
    ) -> tuple[ClassResponse, str]:
        """Returns the response plus the raw join code; the code is shown once.

        Rule: only LECTURER-role users open classes; admin intervention uses
        dedicated lifecycle endpoints, not class creation.
        """
        if not check_user_is_lecturer(user.id, session=self.session):
            raise AppError(403)
        with transaction(self.session):
            if self.repository.get_course_by_id(request.course_id) is None:
                raise AppError(404, "Course not found")
            join_code = generate_join_code()
            klass = Class(
                course_id=request.course_id,
                owner_user_id=user.id,
                name=request.name,
                join_code_hash=hash_join_code(join_code),
            )
            try:
                created = self.repository.create_class(klass)
            except IntegrityError as exc:
                # Collisions are astronomically unlikely; one regenerate suffices,
                # and a repeat collision means the store is unhealthy.
                if _constraint(exc) == "classes_join_code_hash_key":
                    raise AppError(503, "Join code generation unavailable") from exc
                raise
            membership = ClassMembership(
                class_id=created.id,
                user_id=user.id,
                class_role=ClassRole.OWNER,
                status=MembershipStatus.ACTIVE,
            )
            self.repository.create_membership(membership)
            return ClassResponse.model_validate(created), join_code

    def list_my_classes(self, user: CurrentUser, pagination: Pagination) -> Page[ClassResponse]:
        rows = self.repository.list_classes_for_user(user.id, pagination.limit, pagination.cursor)
        return _page(rows, pagination.limit, ClassResponse)

    def get_class(self, class_id: UUID, user: CurrentUser) -> ClassResponse:
        """Any ACTIVE member (or admin) may view the class; others get 404."""
        klass = self.repository.get_class_by_id(class_id)
        if klass is None:
            raise AppError(404)
        require_class_role(self.session, class_id, user, set(ClassRole), admin_intervenes=True)
        return ClassResponse.model_validate(klass)

    def update_class(
        self, class_id: UUID, user: CurrentUser, request: ClassUpdateRequest
    ) -> ClassResponse:
        """Owner renames or toggles join_enabled; archived classes reject writes."""
        require_class_role(self.session, class_id, user, {ClassRole.OWNER}, admin_intervenes=True)
        with transaction(self.session):
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is None:
                raise AppError(404)
            if klass.status == ClassStatus.ARCHIVED:
                # Archived classes are read-only, even for the owner (Rule F5).
                raise AppError(400, "Archived classes are read-only")
            if request.name is not None:
                klass.name = request.name
            if request.join_enabled is not None:
                klass.join_enabled = request.join_enabled
            return ClassResponse.model_validate(klass)

    # -- Join requests -------------------------------------------------------------

    def create_join_request(self, user: CurrentUser, join_code: str) -> JoinRequestCreatedResponse:
        """Student redeems a join code; REMOVED members must be re-invited first (Rule L2)."""
        with transaction(self.session):
            klass = self.repository.find_class_by_join_code_hash(hash_join_code(join_code))
            if klass is None or klass.status != ClassStatus.ACTIVE:
                # Same answer for wrong code and archived class; codes are secrets.
                raise AppError(404, "Invalid join code")
            if not klass.join_enabled:
                raise AppError(400, "This class is not accepting join requests")
            membership = self.repository.get_active_membership(klass.id, user.id)
            if membership is not None:
                raise AppError(409, "Already a member of this class")
            previous = self.repository.get_membership(klass.id, user.id)
            if previous is not None and previous.status == MembershipStatus.REMOVED:
                raise AppError(403, "A lecturer must re-invite you before rejoining")
            if self.repository.get_pending_join_request(klass.id, user.id) is not None:
                raise AppError(409, "A join request is already pending")
            try:
                join_request = self.repository.create_join_request(
                    JoinRequest(class_id=klass.id, student_id=user.id)
                )
            except IntegrityError as exc:
                if _constraint(exc) == "ix_core_join_requests_pending":
                    raise AppError(409, "A join request is already pending") from exc
                raise
            # TASK-006 line 28: notify lecturers via the transactional outbox.
            self._record_event(
                "JOIN_REQUEST_SUBMITTED",
                aggregate_id=klass.id,
                payload_json={
                    "class_id": str(klass.id),
                    "request_id": str(join_request.id),
                    "student_id": str(user.id),
                },
            )
            return JoinRequestCreatedResponse(
                request_id=join_request.id, class_id=klass.id, status=join_request.status
            )

    def list_join_requests(
        self,
        class_id: UUID,
        user: CurrentUser,
        pagination: Pagination,
        *,
        pending_only: bool = False,
    ) -> Page[JoinRequestResponse]:
        """Lecturer view; pending_only=True narrows to the PENDING approval queue."""
        require_class_lecturer(self.session, class_id, user)
        rows = self.repository.list_join_requests(
            class_id, pagination.limit, pagination.cursor, pending_only=pending_only
        )
        return _page(rows, pagination.limit, JoinRequestResponse)

    def _decide_join_request(
        self,
        request_id: UUID,
        actor: CurrentUser,
        target: JoinRequestStatus,
        *,
        class_id: UUID | None = None,
    ) -> JoinRequestResponse | MembershipResponse:
        """Shared approve/reject/cancel path; the URL class_id must match the row."""
        with transaction(self.session):
            join_request = self.repository.get_join_request(request_id, for_update=True)
            if join_request is None:
                raise AppError(404)
            # The URL class_id must match the row; a wrong path never mutates.
            if class_id is not None and join_request.class_id != class_id:
                raise AppError(404)
            resolved_class_id = join_request.class_id
            if target is JoinRequestStatus.CANCELLED:
                if join_request.student_id != actor.id:
                    raise AppError(403, "Only the requester can cancel")
            else:
                require_class_lecturer(self.session, resolved_class_id, actor)
            if join_request.status == target and target is JoinRequestStatus.APPROVED:
                existing = self.repository.get_active_membership(
                    resolved_class_id, join_request.student_id
                )
                if existing is not None:
                    return MembershipResponse.model_validate(existing)
            if join_request.status != JoinRequestStatus.PENDING:
                raise AppError(409, "Join request is no longer pending")
            klass = self.repository.get_class_by_id(resolved_class_id, for_update=True)
            if klass is None or klass.status != ClassStatus.ACTIVE:
                raise AppError(400, "Class is not active")
            join_request.status = target
            join_request.decided_by = actor.id
            join_request.decided_at = _utcnow()
            if target is JoinRequestStatus.APPROVED:
                membership = ClassMembership(
                    class_id=resolved_class_id,
                    user_id=join_request.student_id,
                    class_role=ClassRole.STUDENT,
                    status=MembershipStatus.ACTIVE,
                )
                try:
                    created = self.repository.create_membership(membership)
                except IntegrityError as exc:
                    if _constraint(exc) == "ix_core_class_memberships_active":
                        raise AppError(409, "Already a member of this class") from exc
                    raise
                # TASK-006 line 35: approval notifies the student via the outbox.
                self._record_event(
                    "JOIN_REQUEST_APPROVED",
                    aggregate_id=resolved_class_id,
                    payload_json={
                        "class_id": str(resolved_class_id),
                        "request_id": str(join_request.id),
                        "student_id": str(join_request.student_id),
                        "decided_by": str(actor.id),
                    },
                )
                return MembershipResponse.model_validate(created)
            return JoinRequestResponse.model_validate(join_request)

    def approve_join_request(
        self, class_id: UUID, request_id: UUID, user: CurrentUser
    ) -> JoinRequestResponse | MembershipResponse:
        return self._decide_join_request(
            request_id, user, JoinRequestStatus.APPROVED, class_id=class_id
        )

    def reject_join_request(
        self, class_id: UUID, request_id: UUID, user: CurrentUser
    ) -> JoinRequestResponse | MembershipResponse:
        return self._decide_join_request(
            request_id, user, JoinRequestStatus.REJECTED, class_id=class_id
        )

    def cancel_join_request(
        self, class_id: UUID, request_id: UUID, user: CurrentUser
    ) -> JoinRequestResponse | MembershipResponse:
        return self._decide_join_request(
            request_id, user, JoinRequestStatus.CANCELLED, class_id=class_id
        )

    def readmit_student(
        self, class_id: UUID, member_user_id: UUID, user: CurrentUser
    ) -> MembershipResponse:
        """Re-activate a REMOVED membership so the student can rejoin (Rules A1/L2)."""
        with transaction(self.session):
            require_class_role(
                self.session,
                class_id,
                user,
                {ClassRole.OWNER, ClassRole.CO_LECTURER},
                admin_intervenes=True,
            )
            membership = self.repository.get_membership(class_id, member_user_id, for_update=True)
            if membership is None:
                raise AppError(404)
            if membership.status == MembershipStatus.ACTIVE:
                raise AppError(409, "Already a member of this class")
            if membership.status != MembershipStatus.REMOVED:
                raise AppError(404)  # LEFT members simply rejoin via join code.
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is None or klass.status != ClassStatus.ACTIVE:
                raise AppError(400, "Class is not active")
            if self.repository.get_active_membership(class_id, member_user_id) is not None:
                raise AppError(409, "Already a member of this class")
            membership.status = MembershipStatus.ACTIVE
            membership.ended_at = None
            return MembershipResponse.model_validate(membership)

    # -- Membership -------------------------------------------------------------------

    def list_members(
        self, class_id: UUID, user: CurrentUser, pagination: Pagination
    ) -> Page[MembershipResponse]:
        """Roster of ACTIVE members; any class member may view it."""
        require_class_role(self.session, class_id, user, set(ClassRole), admin_intervenes=True)
        rows = self.repository.list_active_members(class_id, pagination.limit, pagination.cursor)
        return _page(rows, pagination.limit, MembershipResponse)

    def leave_class(self, class_id: UUID, user: CurrentUser) -> None:
        """Self-leave marks the membership LEFT; the owner must transfer first."""
        with transaction(self.session):
            membership = self.repository.get_membership(class_id, user.id, for_update=True)
            active = (
                membership
                if membership is not None and membership.status == MembershipStatus.ACTIVE
                else None
            )
            if active is None:
                raise AppError(404)
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is not None and klass.status == ClassStatus.ARCHIVED:
                raise AppError(400, "Archived classes are read-only")
            if active.class_role == ClassRole.OWNER:
                raise AppError(400, "Transfer ownership before leaving the class")
            active.status = MembershipStatus.LEFT
            active.ended_at = _utcnow()

    def remove_member(self, class_id: UUID, member_user_id: UUID, user: CurrentUser) -> None:
        """Lecturer marks a student REMOVED; re-entry then requires re-admission."""
        with transaction(self.session):
            require_class_role(
                self.session,
                class_id,
                user,
                {ClassRole.OWNER, ClassRole.CO_LECTURER},
                admin_intervenes=True,
            )
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is None:
                raise AppError(404)
            if klass.status == ClassStatus.ARCHIVED:
                raise AppError(400, "Archived classes are read-only")
            membership = self.repository.get_membership(class_id, member_user_id, for_update=True)
            if membership is None or membership.status != MembershipStatus.ACTIVE:
                raise AppError(404)
            if membership.class_role == ClassRole.OWNER:
                raise AppError(400, "The owner cannot be removed")
            membership.status = MembershipStatus.REMOVED
            membership.ended_at = _utcnow()

    # -- Co-lecturer ------------------------------------------------------------------

    def invite_co_lecturer(
        self, class_id: UUID, user: CurrentUser, request: CoLecturerInviteRequest
    ) -> CoLecturerInvitationResponse:
        """Owner invites a system lecturer; one PENDING per pair, 7-day TTL."""
        with transaction(self.session):
            require_class_role(
                self.session, class_id, user, {ClassRole.OWNER}, admin_intervenes=True
            )
            if not check_user_is_lecturer(request.lecturer_id, session=self.session):
                raise AppError(400, "Invitee must be an active system lecturer")
            membership = self.repository.get_active_membership(class_id, request.lecturer_id)
            if membership is not None:
                raise AppError(409, "User already belongs to this class")
            klass = self.repository.get_class_by_id(class_id)
            if klass is None or klass.status != ClassStatus.ACTIVE:
                raise AppError(400, "Class is not active")
            invitation = CoLecturerInvitation(
                class_id=class_id,
                lecturer_id=request.lecturer_id,
                expires_at=_utcnow() + _CO_LECTURER_INVITATION_TTL,
            )
            try:
                # Savepoint: the failed insert must not abort the surrounding transaction.
                with self.session.begin_nested():
                    created = self.repository.create_co_lecturer_invitation(invitation)
            except IntegrityError as exc:
                # A stale PENDING row (expired but never answered) must not block
                # re-inviting: retire it and insert the fresh invitation.
                if _constraint(exc) == "ix_core_co_lecturer_invitations_pending":
                    stale = self.repository.get_pending_invitation(
                        class_id, request.lecturer_id, for_update=True
                    )
                    if stale is not None and stale.expires_at <= _utcnow():
                        stale.status = CoLecturerInvitationStatus.CANCELLED
                        self.session.flush()
                        try:
                            with self.session.begin_nested():
                                created = self.repository.create_co_lecturer_invitation(invitation)
                        except IntegrityError:
                            raise AppError(409, "An invitation is already pending") from None
                    else:
                        raise AppError(409, "An invitation is already pending") from exc
                else:
                    raise
            return CoLecturerInvitationResponse.model_validate(created)

    def accept_co_lecturer_invitation(
        self, class_id: UUID, invitation_id: UUID, user: CurrentUser
    ) -> CoLecturerInvitationResponse:
        """Invitee accepts; an existing ACTIVE member is upgraded to CO_LECTURER in place."""
        with transaction(self.session):
            invitation = self.repository.get_co_lecturer_invitation(invitation_id, for_update=True)
            if invitation is None or invitation.class_id != class_id:
                raise AppError(404)
            if invitation.lecturer_id != user.id:
                raise AppError(403, "Only the invitee can accept")
            if invitation.status == CoLecturerInvitationStatus.ACCEPTED:
                return CoLecturerInvitationResponse.model_validate(invitation)
            if (
                invitation.status != CoLecturerInvitationStatus.PENDING
                or invitation.expires_at <= _utcnow()
            ):
                raise AppError(409, "Invitation is no longer valid")
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is None or klass.status != ClassStatus.ACTIVE:
                raise AppError(400, "Class is not active")
            invitation.status = CoLecturerInvitationStatus.ACCEPTED
            previous = self.repository.get_membership(class_id, user.id)
            if previous is not None and previous.status == MembershipStatus.ACTIVE:
                previous.class_role = ClassRole.CO_LECTURER
            else:
                try:
                    self.repository.create_membership(
                        ClassMembership(
                            class_id=class_id,
                            user_id=user.id,
                            class_role=ClassRole.CO_LECTURER,
                            status=MembershipStatus.ACTIVE,
                        )
                    )
                except IntegrityError as exc:
                    # Concurrent accept/invite raced the partial unique index.
                    if _constraint(exc) == "ix_core_class_memberships_active":
                        raise AppError(409, "User already belongs to this class") from exc
                    raise
            return CoLecturerInvitationResponse.model_validate(invitation)

    def reject_co_lecturer_invitation(
        self, class_id: UUID, invitation_id: UUID, user: CurrentUser
    ) -> CoLecturerInvitationResponse:
        """Invitee rejects a PENDING invitation; other states return unchanged."""
        with transaction(self.session):
            invitation = self.repository.get_co_lecturer_invitation(invitation_id, for_update=True)
            if invitation is None or invitation.class_id != class_id:
                raise AppError(404)
            if invitation.lecturer_id != user.id:
                raise AppError(403, "Only the invitee can reject")
            if invitation.status == CoLecturerInvitationStatus.PENDING:
                invitation.status = CoLecturerInvitationStatus.REJECTED
            return CoLecturerInvitationResponse.model_validate(invitation)

    def cancel_co_lecturer_invitation(
        self, class_id: UUID, invitation_id: UUID, user: CurrentUser
    ) -> CoLecturerInvitationResponse:
        """Owner withdraws a pending invitation (reaches the CANCELLED state)."""
        with transaction(self.session):
            require_class_role(
                self.session, class_id, user, {ClassRole.OWNER}, admin_intervenes=True
            )
            invitation = self.repository.get_co_lecturer_invitation(invitation_id, for_update=True)
            if invitation is None or invitation.class_id != class_id:
                raise AppError(404)
            if invitation.status == CoLecturerInvitationStatus.CANCELLED:
                return CoLecturerInvitationResponse.model_validate(invitation)
            if invitation.status != CoLecturerInvitationStatus.PENDING:
                raise AppError(409, "Invitation is no longer pending")
            invitation.status = CoLecturerInvitationStatus.CANCELLED
            return CoLecturerInvitationResponse.model_validate(invitation)

    # -- Lifecycle / ownership --------------------------------------------------------

    def archive_class(self, class_id: UUID, user: CurrentUser) -> ClassResponse:
        return self._set_class_status(class_id, user, ClassStatus.ARCHIVED)

    def restore_class(self, class_id: UUID, user: CurrentUser) -> ClassResponse:
        return self._set_class_status(class_id, user, ClassStatus.ACTIVE)

    def _set_class_status(self, class_id: UUID, user: CurrentUser, status: ClassStatus):
        """Idempotent archive/restore; audits only when the status actually changes."""
        require_class_role(self.session, class_id, user, {ClassRole.OWNER}, admin_intervenes=True)
        with transaction(self.session):
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is None:
                raise AppError(404)
            if klass.status != status:
                previous = klass.status.value
                klass.status = status
                self._record_status_audit(
                    class_id,
                    actor_id=user.id,
                    admin_reason=is_admin(user),
                    previous_status=previous,
                    new_status=status.value,
                )
            return ClassResponse.model_validate(klass)

    def transfer_ownership(
        self, class_id: UUID, user: CurrentUser, request: OwnershipTransferRequest
    ) -> ClassResponse:
        """Hands OWNER to an active CO_LECTURER (old owner becomes co-lecturer); audited."""
        with transaction(self.session):
            klass = self.repository.get_class_by_id(class_id, for_update=True)
            if klass is None:
                raise AppError(404)
            if klass.status == ClassStatus.ARCHIVED:
                raise AppError(400, "Archived classes are read-only")
            require_class_role(
                self.session, class_id, user, {ClassRole.OWNER}, admin_intervenes=True
            )
            new_membership = self.repository.get_active_membership(
                class_id, request.new_owner_user_id
            )
            if new_membership is None or new_membership.class_role != ClassRole.CO_LECTURER:
                raise AppError(400, "New owner must be an active co-lecturer of this class")
            if request.new_owner_user_id == user.id and not is_admin(user):
                raise AppError(400, "You already own this class")
            old_owner_id = klass.owner_user_id
            klass.owner_user_id = request.new_owner_user_id
            old_membership = self.repository.get_active_membership(class_id, old_owner_id)
            if old_membership is not None:
                old_membership.class_role = ClassRole.CO_LECTURER
            new_membership.class_role = ClassRole.OWNER
            # TASK-007: ownership transfer is audited.
            self._record_event_audit(
                class_id,
                action="ADMIN_OWNERSHIP_TRANSFER" if is_admin(user) else "OWNERSHIP_TRANSFER",
                actor_id=user.id,
                metadata_json=AuditMetadata(
                    changed_fields=["owner_user_id"],
                    previous_status=klass.status.value,
                    new_status=klass.status.value,
                    reason_code="ADMIN_INTERVENTION" if is_admin(user) else "USER_REQUEST",
                ),
            )
            return ClassResponse.model_validate(klass)

    # -- Cross-cutting helpers ----------------------------------------------------------

    def _record_event(self, event_type: str, *, aggregate_id: UUID, payload_json: dict) -> None:
        record_outbox_event(
            self.session,
            event_type=event_type,
            aggregate_id=aggregate_id,
            payload_json=payload_json,
        )

    def _record_status_audit(
        self,
        class_id: UUID,
        *,
        actor_id: UUID,
        admin_reason: bool,
        previous_status: str,
        new_status: str,
        changed_fields: list[str] | None = None,
    ) -> None:
        fields = changed_fields if changed_fields is not None else ["status"]
        self._record_event_audit(
            class_id,
            action="ADMIN_CLASS_STATUS" if admin_reason else "CLASS_STATUS",
            actor_id=actor_id,
            metadata_json=AuditMetadata(
                changed_fields=fields,
                previous_status=previous_status,
                new_status=new_status,
                reason_code="ADMIN_INTERVENTION" if admin_reason else "USER_REQUEST",
            ),
        )

    def _record_event_audit(
        self, class_id: UUID, *, action: str, actor_id: UUID, metadata_json: AuditMetadata
    ) -> None:
        if self.correlation_id is None:
            return  # No request context (scripts/tests); nothing audit-safe to record.
        record_audit(
            self.session,
            actor_id=actor_id,
            action=action,
            target_type="CLASS",
            target_id=class_id,
            correlation_id=self.correlation_id,
            metadata_json=metadata_json,
        )


def _constraint(exc: IntegrityError) -> str | None:
    """Constraint name of the wrapped PG error, used to dispatch IntegrityError."""
    return getattr(getattr(exc.orig, "diag", None), "constraint_name", None)


def _page(rows: list, limit: int, model):
    """Builds a cursor page; repositories return limit+1 rows, the extra implies next_cursor."""
    items = rows[:limit]
    next_cursor = encode_cursor(items[-1].id) if len(rows) > limit else None
    return Page(items=[model.model_validate(item) for item in items], next_cursor=next_cursor)
