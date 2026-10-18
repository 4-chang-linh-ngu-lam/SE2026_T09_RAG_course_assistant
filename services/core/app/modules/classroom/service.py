from contextlib import nullcontext
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError

from app.common.audit import AuditMetadata, record_audit
from app.common.auth_dependencies import CurrentUser, require_school_scope
from app.common.db import transaction
from app.common.errors import AppError
from app.common.outbox import record_outbox_event
from app.common.pagination import Page, Pagination, encode_cursor
from app.modules.classroom.models import (
    ClassMembership,
    ClassStatus,
    Course,
    EnrollmentMode,
    HomeroomClass,
    HomeroomRoster,
    MembershipStatus,
    SubjectClass,
    TeachingAssignment,
    TeachingRole,
)
from app.modules.classroom.permissions import require_admin, require_class_read
from app.modules.classroom.public import get_notification_audience
from app.modules.classroom.repository import ClassroomRepository
from app.modules.classroom.schemas import (
    ClassCreateRequest,
    ClassResponse,
    CourseCreateRequest,
    CourseResponse,
    EnrollmentModeRequest,
    EnrollmentPreviewResponse,
    HomeroomCreateRequest,
    HomeroomResponse,
    MembershipResponse,
    RosterResponse,
    TeachingAssignmentResponse,
    TeachingAssignmentsRequest,
)
from app.modules.identity.public import get_user_roles, get_user_summary


def _now() -> datetime:
    return datetime.now(UTC)


def _page(rows, limit, schema):
    items = [schema.model_validate(row) for row in rows[:limit]]
    return Page[schema](
        items=items,
        next_cursor=encode_cursor(rows[limit - 1].id) if len(rows) > limit else None,
    )


class ClassroomService:
    def __init__(
        self,
        session,
        correlation_id: UUID | None = None,
        reason_code: str = "ADMIN_INTERVENTION",
        reason_supplied: bool = False,
    ):
        self.session = session
        self.repository = ClassroomRepository(session)
        self.correlation_id = correlation_id or uuid4()
        self.reason_code = reason_code
        self.reason_supplied = reason_supplied

    def _audit(
        self, actor_id: UUID, action: str, target_id: UUID, *, target_type: str = "CLASS"
    ) -> None:
        actor = get_user_summary(actor_id, session=self.session)
        record_audit(
            self.session,
            actor_id=actor_id,
            school_id=actor.school_id if actor is not None else None,
            action=action,
            target_type=target_type,
            target_id=target_id,
            correlation_id=self.correlation_id,
            metadata_json=AuditMetadata(reason_code=self.reason_code),
        )

    def _event(self, event_type: str, class_id: UUID, *, extra_recipients=(), **payload) -> None:
        self.session.flush()
        if event_type == "HOMEROOM_STUDENT_TRANSFERRED":
            homeroom = self.repository.get_homeroom(class_id)
            scope = {
                "school_id": str(homeroom.school_id),
                "recipient_ids": [str(payload["student_id"])],
            }
        else:
            audience = get_notification_audience(class_id, session=self.session)
            if audience is None:
                raise AppError(503, "Notification audience unavailable")
            scope = {
                "school_id": str(audience.school_id),
                "recipient_ids": [
                    str(value)
                    for value in sorted(set(audience.recipient_ids) | set(extra_recipients))
                ],
            }
        record_outbox_event(
            self.session,
            event_type=event_type,
            aggregate_id=class_id,
            payload_json={
                "class_id": str(class_id),
                **scope,
                **{k: str(v) if isinstance(v, (UUID, datetime)) else v for k, v in payload.items()},
            },
        )

    def _class_for_admin(
        self, class_id: UUID, actor: CurrentUser, *, for_update: bool = False
    ) -> SubjectClass:
        school_id = require_admin(actor)
        klass = self.repository.get_class(class_id, for_update=for_update)
        if klass is None:
            raise AppError(404)
        require_school_scope(school_id, klass.school_id)
        return klass

    def _homeroom_for_admin(
        self, homeroom_id: UUID, actor: CurrentUser, *, for_update: bool = False
    ) -> HomeroomClass:
        school_id = require_admin(actor)
        homeroom = self.repository.get_homeroom(homeroom_id, for_update=for_update)
        if homeroom is None:
            raise AppError(404)
        require_school_scope(school_id, homeroom.school_id)
        return homeroom

    def _student(self, student_id: UUID, school_id: UUID) -> None:
        student = get_user_summary(student_id, session=self.session)
        if student is None:
            raise AppError(404)
        require_school_scope(school_id, student.school_id)
        if set(get_user_roles(student_id, session=self.session)) != {"STUDENT"}:
            raise AppError(400, "Expected a Student account")

    def _lecturer(self, lecturer_id: UUID, school_id: UUID) -> None:
        lecturer = get_user_summary(lecturer_id, session=self.session)
        if lecturer is None:
            raise AppError(404)
        require_school_scope(school_id, lecturer.school_id)
        if lecturer.status != "ACTIVE" or "LECTURER" not in get_user_roles(
            lecturer_id, session=self.session
        ):
            raise AppError(400, "Expected an active lecturer")

    @staticmethod
    def _active(klass: SubjectClass) -> None:
        if klass.status != ClassStatus.ACTIVE:
            raise AppError(409, "Archived classes are read-only")

    def create_course(
        self, actor: CurrentUser, request: CourseCreateRequest, *, commit: bool = True
    ) -> CourseResponse:
        school_id = require_admin(actor)
        try:
            with transaction(self.session) if commit else nullcontext(self.session):
                self.repository.ensure_school(school_id)
                if self.repository.get_course_by_code(school_id, request.code):
                    raise AppError(409, "Course code already exists")
                course = self.repository.add(
                    Course(school_id=school_id, code=request.code, name=request.name)
                )
                self._audit(actor.id, "ADMIN_CREATE_COURSE", course.id, target_type="COURSE")
                return CourseResponse.model_validate(course)
        except IntegrityError as exc:
            raise AppError(409, "Course code already exists") from exc

    def create_homeroom(
        self, actor: CurrentUser, request: HomeroomCreateRequest, *, commit: bool = True
    ) -> HomeroomResponse:
        school_id = require_admin(actor)
        try:
            with transaction(self.session) if commit else nullcontext(self.session):
                self.repository.ensure_school(school_id)
                year = self.repository.ensure_academic_year(school_id, request.academic_year)
                if self.repository.get_homeroom_by_name(school_id, year.id, request.name):
                    raise AppError(409, "Homeroom already exists")
                homeroom = self.repository.add(
                    HomeroomClass(
                        school_id=school_id,
                        academic_year_id=year.id,
                        name=request.name,
                        grade_level=request.grade_level,
                    )
                )
                self._audit(actor.id, "ADMIN_CREATE_HOMEROOM", homeroom.id, target_type="HOMEROOM")
                return HomeroomResponse.model_validate(homeroom)
        except IntegrityError as exc:
            raise AppError(409, "Homeroom already exists") from exc

    def set_roster(
        self, actor: CurrentUser, homeroom_id: UUID, student_ids: list[UUID], *, commit: bool = True
    ) -> RosterResponse:
        with transaction(self.session) if commit else nullcontext(self.session):
            homeroom = self._homeroom_for_admin(homeroom_id, actor, for_update=True)
            for student_id in sorted(student_ids):
                self._student(student_id, homeroom.school_id)
            existing = {row.student_id: row for row in self.repository.active_roster(homeroom_id)}
            incoming = set(student_ids)
            if incoming != set(existing):
                now = _now()
                for student_id in set(existing) - incoming:
                    existing[student_id].ended_at = now
                for student_id in incoming - set(existing):
                    self.repository.add(
                        HomeroomRoster(
                            homeroom_class_id=homeroom_id,
                            student_id=student_id,
                            joined_at=now,
                        )
                    )
                homeroom.roster_version += 1
                for klass in self.repository.auto_classes_for_homeroom(homeroom_id):
                    self._sync_class(klass, incoming, bump_version=True)
                self._audit(actor.id, "ADMIN_UPDATE_ROSTER", homeroom_id, target_type="HOMEROOM")
            return RosterResponse(
                homeroom_class_id=homeroom_id,
                student_ids=sorted(incoming),
                roster_version=homeroom.roster_version,
            )

    def transfer_homeroom_student(
        self,
        source_id: UUID,
        destination_id: UUID,
        student_id: UUID,
        actor: CurrentUser,
    ) -> RosterResponse:
        if source_id == destination_id:
            raise AppError(400, "Select a different destination homeroom")
        with transaction(self.session):
            homerooms = {
                homeroom_id: self._homeroom_for_admin(homeroom_id, actor, for_update=True)
                for homeroom_id in sorted([source_id, destination_id])
            }
            source, destination = homerooms[source_id], homerooms[destination_id]
            if (
                source.academic_year_id != destination.academic_year_id
                or source.grade_level != destination.grade_level
            ):
                raise AppError(400, "Homerooms must share a year and grade")
            self._student(student_id, source.school_id)
            source_rows = {row.student_id: row for row in self.repository.active_roster(source_id)}
            destination_rows = {
                row.student_id: row for row in self.repository.active_roster(destination_id)
            }
            if student_id not in source_rows:
                raise AppError(404)
            if student_id in destination_rows:
                raise AppError(409, "Student already belongs to destination homeroom")
            now = _now()
            source_rows[student_id].ended_at = now
            self.repository.add(
                HomeroomRoster(
                    homeroom_class_id=destination_id,
                    student_id=student_id,
                    joined_at=now,
                )
            )
            source.roster_version += 1
            destination.roster_version += 1
            for klass in self.repository.auto_classes_for_homeroom(source_id):
                self._sync_class(klass, set(source_rows) - {student_id}, bump_version=True)
            for klass in self.repository.auto_classes_for_homeroom(destination_id):
                self._sync_class(klass, set(destination_rows) | {student_id}, bump_version=True)
            self._audit(
                actor.id,
                "ADMIN_TRANSFER_HOMEROOM_STUDENT",
                source_id,
                target_type="HOMEROOM",
            )
            self._event(
                "HOMEROOM_STUDENT_TRANSFERRED",
                source_id,
                destination_homeroom_id=destination_id,
                student_id=student_id,
                effective_at=now.isoformat(),
            )
            return RosterResponse(
                homeroom_class_id=destination_id,
                student_ids=sorted(set(destination_rows) | {student_id}),
                roster_version=destination.roster_version,
            )

    def create_class(
        self, actor: CurrentUser, request: ClassCreateRequest, *, commit: bool = True
    ) -> ClassResponse:
        school_id = require_admin(actor)
        try:
            with transaction(self.session) if commit else nullcontext(self.session):
                self._lecturer(request.primary_lecturer_id, school_id)
                self.repository.ensure_school(school_id)
                course = self.repository.get_course(request.course_id)
                if course is None:
                    raise AppError(404)
                require_school_scope(school_id, course.school_id)
                year = self.repository.ensure_academic_year(school_id, request.academic_year)
                semester = self.repository.ensure_semester(year.id, request.semester)
                homeroom = None
                if request.homeroom_class_id is not None:
                    homeroom = self._homeroom_for_admin(request.homeroom_class_id, actor)
                    if (
                        homeroom.academic_year_id != year.id
                        or homeroom.grade_level != request.grade_level
                    ):
                        raise AppError(400, "Homeroom must match year and grade")
                if request.enrollment_mode == EnrollmentMode.AUTO and homeroom is None:
                    raise AppError(400, "AUTO enrollment requires a homeroom")
                klass = self.repository.add(
                    SubjectClass(
                        school_id=school_id,
                        academic_year_id=year.id,
                        semester_id=semester.id,
                        course_id=course.id,
                        homeroom_class_id=homeroom.id if homeroom else None,
                        name=request.name,
                        grade_level=request.grade_level,
                        enrollment_mode=request.enrollment_mode,
                    )
                )
                self.repository.add(
                    TeachingAssignment(
                        class_id=klass.id,
                        lecturer_id=request.primary_lecturer_id,
                        role=TeachingRole.PRIMARY,
                        assigned_at=_now(),
                    )
                )
                if request.enrollment_mode == EnrollmentMode.AUTO:
                    self._sync_class(
                        klass,
                        {row.student_id for row in self.repository.active_roster(homeroom.id)},
                        bump_version=False,
                    )
                self._audit(actor.id, "ADMIN_CREATE_CLASS", klass.id)
                return ClassResponse.model_validate(klass)
        except IntegrityError as exc:
            raise AppError(409, "Class creation conflicts with current data") from exc

    def list_classes(self, actor: CurrentUser, pagination: Pagination) -> Page[ClassResponse]:
        if actor.status != "ACTIVE" or actor.school_id is None:
            raise AppError(404)
        rows = self.repository.list_classes(
            actor.school_id,
            actor.id,
            is_admin="ADMIN" in actor.roles,
            limit=pagination.limit,
            cursor=pagination.cursor,
        )
        return _page(rows, pagination.limit, ClassResponse)

    def get_class(self, class_id: UUID, actor: CurrentUser) -> ClassResponse:
        require_class_read(self.session, class_id, actor)
        klass = self.repository.get_class(class_id)
        return ClassResponse.model_validate(klass)

    def list_members(self, class_id: UUID, actor: CurrentUser) -> list[MembershipResponse]:
        require_class_read(self.session, class_id, actor)
        return [
            MembershipResponse.model_validate(row)
            for row in self.repository.active_memberships(class_id)
        ]

    def set_teachers(
        self,
        class_id: UUID,
        actor: CurrentUser,
        request: TeachingAssignmentsRequest,
        *,
        commit: bool = True,
    ) -> list[TeachingAssignmentResponse]:
        with transaction(self.session) if commit else nullcontext(self.session):
            klass = self._class_for_admin(class_id, actor, for_update=True)
            self._active(klass)
            desired = {request.primary_lecturer_id: TeachingRole.PRIMARY}
            desired.update(
                {
                    lecturer_id: TeachingRole.ASSISTING
                    for lecturer_id in request.assisting_lecturer_ids
                }
            )
            for lecturer_id in sorted(desired):
                self._lecturer(lecturer_id, klass.school_id)
            current = {row.lecturer_id: row for row in self.repository.active_teachers(class_id)}
            if {key: row.role for key, row in current.items()} == desired:
                return [TeachingAssignmentResponse.model_validate(row) for row in current.values()]
            now = _now()
            for row in current.values():
                row.ended_at = now
            self.session.flush()
            for lecturer_id, role in desired.items():
                self.repository.add(
                    TeachingAssignment(
                        class_id=class_id, lecturer_id=lecturer_id, role=role, assigned_at=now
                    )
                )
            klass.version += 1
            self._audit(actor.id, "ADMIN_SET_TEACHERS", class_id)
            self._event(
                "CLASS_TEACHERS_CHANGED", class_id, version=klass.version, extra_recipients=current
            )
            return [
                TeachingAssignmentResponse.model_validate(row)
                for row in self.repository.active_teachers(class_id)
            ]

    def _sync_class(self, klass: SubjectClass, target: set[UUID], *, bump_version: bool) -> bool:
        current = {row.student_id: row for row in self.repository.active_memberships(klass.id)}
        if set(current) == target:
            return False
        now = _now()
        for student_id in set(current) - target:
            current[student_id].status = MembershipStatus.ENDED
            current[student_id].ended_at = now
        for student_id in target - set(current):
            self.repository.add(
                ClassMembership(
                    class_id=klass.id,
                    student_id=student_id,
                    source=EnrollmentMode.AUTO,
                    status=MembershipStatus.ACTIVE,
                    joined_at=now,
                )
            )
        if bump_version:
            klass.version += 1
        self._event(
            "CLASS_ENROLLMENT_CHANGED", klass.id, version=klass.version, extra_recipients=current
        )
        return True

    def preview_auto(self, class_id: UUID, actor: CurrentUser) -> EnrollmentPreviewResponse:
        klass = self._class_for_admin(class_id, actor)
        self._active(klass)
        if klass.homeroom_class_id is None:
            raise AppError(400, "A homeroom is required")
        homeroom = self._homeroom_for_admin(klass.homeroom_class_id, actor)
        roster = {row.student_id for row in self.repository.active_roster(homeroom.id)}
        current = {row.student_id for row in self.repository.active_memberships(class_id)}
        return EnrollmentPreviewResponse(
            class_id=class_id,
            target_mode=EnrollmentMode.AUTO,
            class_version=klass.version,
            roster_version=homeroom.roster_version,
            add_student_ids=sorted(roster - current),
            end_student_ids=sorted(current - roster),
        )

    def set_enrollment_mode(
        self, class_id: UUID, actor: CurrentUser, request: EnrollmentModeRequest
    ) -> ClassResponse:
        with transaction(self.session):
            klass = self._class_for_admin(class_id, actor, for_update=True)
            self._active(klass)
            if klass.enrollment_mode == request.mode:
                return ClassResponse.model_validate(klass)
            if request.mode == EnrollmentMode.AUTO:
                if klass.homeroom_class_id is None:
                    raise AppError(400, "AUTO enrollment requires a homeroom")
                homeroom = self._homeroom_for_admin(klass.homeroom_class_id, actor)
                if (
                    request.expected_class_version != klass.version
                    or request.expected_roster_version != homeroom.roster_version
                ):
                    raise AppError(409, "Enrollment preview is stale or missing")
                target = {row.student_id for row in self.repository.active_roster(homeroom.id)}
                klass.enrollment_mode = EnrollmentMode.AUTO
                klass.version += 1
                self._sync_class(klass, target, bump_version=False)
            else:
                klass.enrollment_mode = EnrollmentMode.MANUAL
                klass.version += 1
            self._audit(actor.id, "ADMIN_CHANGE_ENROLLMENT_MODE", class_id)
            self._event("CLASS_ENROLLMENT_MODE_CHANGED", class_id, version=klass.version)
            return ClassResponse.model_validate(klass)

    def sync_enrollment(self, class_id: UUID, actor: CurrentUser) -> ClassResponse:
        with transaction(self.session):
            klass = self._class_for_admin(class_id, actor, for_update=True)
            self._active(klass)
            if klass.enrollment_mode != EnrollmentMode.AUTO or klass.homeroom_class_id is None:
                raise AppError(409, "Only AUTO classes can sync a roster")
            homeroom = self._homeroom_for_admin(klass.homeroom_class_id, actor)
            target = {row.student_id for row in self.repository.active_roster(homeroom.id)}
            if self._sync_class(klass, target, bump_version=True):
                self._audit(actor.id, "ADMIN_SYNC_ENROLLMENT", class_id)
            return ClassResponse.model_validate(klass)

    def add_member(
        self, class_id: UUID, actor: CurrentUser, student_id: UUID, *, commit: bool = True
    ) -> MembershipResponse:
        with transaction(self.session) if commit else nullcontext(self.session):
            klass = self._class_for_admin(class_id, actor, for_update=True)
            self._active(klass)
            if klass.enrollment_mode != EnrollmentMode.MANUAL:
                raise AppError(409, "Switch to MANUAL enrollment before exceptions")
            self._student(student_id, klass.school_id)
            member = self.repository.active_membership(class_id, student_id)
            if member is None:
                member = self.repository.add(
                    ClassMembership(
                        class_id=class_id,
                        student_id=student_id,
                        source=EnrollmentMode.MANUAL,
                        status=MembershipStatus.ACTIVE,
                        joined_at=_now(),
                    )
                )
                klass.version += 1
                self._audit(actor.id, "ADMIN_ADD_STUDENT", class_id)
                self._event("CLASS_ENROLLMENT_CHANGED", class_id, version=klass.version)
            return MembershipResponse.model_validate(member)

    def end_member(self, class_id: UUID, actor: CurrentUser, student_id: UUID) -> None:
        with transaction(self.session):
            klass = self._class_for_admin(class_id, actor, for_update=True)
            self._active(klass)
            if klass.enrollment_mode != EnrollmentMode.MANUAL:
                raise AppError(409, "Switch to MANUAL enrollment before exceptions")
            member = self.repository.active_membership(class_id, student_id)
            if member is None:
                if not self.repository.has_membership_history(class_id, student_id):
                    raise AppError(404)
                return
            member.status = MembershipStatus.ENDED
            member.ended_at = _now()
            klass.version += 1
            self._audit(actor.id, "ADMIN_END_ENROLLMENT", class_id)
            self._event(
                "CLASS_ENROLLMENT_CHANGED",
                class_id,
                version=klass.version,
                extra_recipients=[student_id],
            )

    def transfer(
        self, source_id: UUID, destination_id: UUID, student_id: UUID, actor: CurrentUser
    ) -> MembershipResponse:
        if source_id == destination_id:
            raise AppError(400, "Select a different destination class")
        with transaction(self.session):
            classes = [
                self._class_for_admin(class_id, actor, for_update=True)
                for class_id in sorted([source_id, destination_id])
            ]
            by_id = {klass.id: klass for klass in classes}
            source, destination = by_id[source_id], by_id[destination_id]
            self._active(source)
            self._active(destination)
            if (
                source.enrollment_mode != EnrollmentMode.MANUAL
                or destination.enrollment_mode != EnrollmentMode.MANUAL
            ):
                raise AppError(409, "AUTO transfers follow the homeroom roster")
            if (
                source.course_id != destination.course_id
                or source.academic_year_id != destination.academic_year_id
                or source.semester_id != destination.semester_id
            ):
                raise AppError(400, "Transfer requires the same subject and term")
            self._student(student_id, source.school_id)
            old = self.repository.active_membership(source_id, student_id)
            if old is None:
                raise AppError(404)
            if self.repository.active_membership(destination_id, student_id):
                raise AppError(409, "Student already enrolled in destination")
            now = _now()
            old.status = MembershipStatus.ENDED
            old.ended_at = now
            new = self.repository.add(
                ClassMembership(
                    class_id=destination_id,
                    student_id=student_id,
                    source=EnrollmentMode.MANUAL,
                    status=MembershipStatus.ACTIVE,
                    joined_at=now,
                )
            )
            source.version += 1
            destination.version += 1
            self._audit(actor.id, "ADMIN_TRANSFER_STUDENT", source_id)
            self._event(
                "CLASS_STUDENT_TRANSFERRED",
                source_id,
                extra_recipients=[student_id],
                version=source.version,
                destination_class_id=destination_id,
                student_id=student_id,
                effective_at=now.isoformat(),
            )
            return MembershipResponse.model_validate(new)

    def set_archived(self, class_id: UUID, actor: CurrentUser, *, archived: bool) -> ClassResponse:
        with transaction(self.session):
            klass = self._class_for_admin(class_id, actor, for_update=True)
            target = ClassStatus.ARCHIVED if archived else ClassStatus.ACTIVE
            if klass.status != target:
                klass.status = target
                klass.version += 1
                self._audit(
                    actor.id,
                    "ADMIN_ARCHIVE_CLASS" if archived else "ADMIN_RESTORE_CLASS",
                    class_id,
                )
                self._event(
                    "CLASS_STATUS_CHANGED", class_id, version=klass.version, status=target.value
                )
            return ClassResponse.model_validate(klass)
