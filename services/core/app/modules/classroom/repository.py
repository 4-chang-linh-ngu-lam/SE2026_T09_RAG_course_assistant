from uuid import UUID

from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.modules.classroom.models import (
    Class,
    ClassMembership,
    ClassRole,
    CoLecturerInvitation,
    CoLecturerInvitationStatus,
    Course,
    JoinRequest,
    MembershipStatus,
)
from app.modules.identity.public import check_user_is_lecturer, get_user_roles


class ClassroomRepository:
    """Query layer for the classroom tables; policy lives in permissions/service.

    List methods fetch limit+1 rows so callers can derive next_cursor cheaply.
    """

    def __init__(self, session: Session):
        self.session = session

    def get_course_by_id(self, course_id: UUID) -> Course | None:
        return self.session.scalar(select(Course).where(Course.id == course_id))

    def get_course_by_code(self, code: str) -> Course | None:
        return self.session.scalar(select(Course).where(Course.code == code))

    def list_courses(self, limit: int, cursor: UUID | None) -> list[Course]:
        """Keyset page ordered by id; returns limit+1 rows (extra implies next_cursor)."""
        query = select(Course)
        if cursor is not None:
            query = query.where(Course.id > cursor)
        return list(self.session.scalars(query.order_by(Course.id).limit(limit + 1)))

    def create_course(self, course: Course) -> Course:
        self.session.add(course)
        self.session.flush()
        return course

    def get_class_by_id(self, class_id: UUID, *, for_update: bool = False) -> Class | None:
        """FOR UPDATE with populate_existing re-reads fresh state inside mutations."""
        query = select(Class).where(Class.id == class_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def find_class_by_join_code_hash(self, join_code_hash: str) -> Class | None:
        """Join-code lookup; the raw code is never stored, only its SHA-256."""
        return self.session.scalar(select(Class).where(Class.join_code_hash == join_code_hash))

    def list_classes_for_user(self, user_id: UUID, limit: int, cursor: UUID | None) -> list[Class]:
        """Classes where the user holds an ACTIVE membership."""
        query = (
            select(Class)
            .join(ClassMembership, ClassMembership.class_id == Class.id)
            .where(
                ClassMembership.user_id == user_id,
                ClassMembership.status == MembershipStatus.ACTIVE,
            )
        )
        if cursor is not None:
            query = query.where(Class.id > cursor)
        return list(self.session.scalars(query.order_by(Class.id).limit(limit + 1)))

    def create_class(self, klass: Class) -> Class:
        self.session.add(klass)
        self.session.flush()
        return klass

    def get_membership(
        self, class_id: UUID, user_id: UUID, *, for_update: bool = False
    ) -> ClassMembership | None:
        """Prefer the ACTIVE row when several exist (re-admitted members keep history)."""
        active_first = case((ClassMembership.status == MembershipStatus.ACTIVE, 0), else_=1)
        query = (
            select(ClassMembership)
            .where(ClassMembership.class_id == class_id, ClassMembership.user_id == user_id)
            .order_by(active_first, ClassMembership.id.desc())
            .limit(1)
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_active_membership(self, class_id: UUID, user_id: UUID) -> ClassMembership | None:
        return self.session.scalar(
            select(ClassMembership).where(
                ClassMembership.class_id == class_id,
                ClassMembership.user_id == user_id,
                ClassMembership.status == MembershipStatus.ACTIVE,
            )
        )

    def list_active_members(
        self, class_id: UUID, limit: int, cursor: UUID | None
    ) -> list[ClassMembership]:
        """Paged ACTIVE roster (all roles)."""
        query = select(ClassMembership).where(
            ClassMembership.class_id == class_id,
            ClassMembership.status == MembershipStatus.ACTIVE,
        )
        if cursor is not None:
            query = query.where(ClassMembership.id > cursor)
        return list(self.session.scalars(query.order_by(ClassMembership.id).limit(limit + 1)))

    def create_membership(self, membership: ClassMembership) -> ClassMembership:
        self.session.add(membership)
        self.session.flush()
        return membership

    def list_class_lecturers(self, class_id: UUID) -> list[ClassMembership]:
        """ACTIVE OWNER/CO_LECTURER rows only — unbounded, unlike list_active_members."""
        return list(
            self.session.scalars(
                select(ClassMembership).where(
                    ClassMembership.class_id == class_id,
                    ClassMembership.status == MembershipStatus.ACTIVE,
                    ClassMembership.class_role.in_((ClassRole.OWNER, ClassRole.CO_LECTURER)),
                )
            )
        )

    def get_join_request(self, request_id: UUID, *, for_update: bool = False) -> JoinRequest | None:
        query = select(JoinRequest).where(JoinRequest.id == request_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_pending_join_request(self, class_id: UUID, student_id: UUID) -> JoinRequest | None:
        """Guards create_join_request against the partial PENDING unique index."""
        return self.session.scalar(
            select(JoinRequest).where(
                JoinRequest.class_id == class_id,
                JoinRequest.student_id == student_id,
                JoinRequest.status == "PENDING",
            )
        )

    def list_join_requests(
        self, class_id: UUID, limit: int, cursor: UUID | None, *, pending_only: bool = False
    ) -> list[JoinRequest]:
        """Keyset page over a class's join requests (PENDING slice when pending_only)."""
        query = select(JoinRequest).where(JoinRequest.class_id == class_id)
        if pending_only:
            query = query.where(JoinRequest.status == "PENDING")
        if cursor is not None:
            query = query.where(JoinRequest.id > cursor)
        return list(self.session.scalars(query.order_by(JoinRequest.id).limit(limit + 1)))

    def create_join_request(self, join_request: JoinRequest) -> JoinRequest:
        self.session.add(join_request)
        self.session.flush()
        return join_request

    def get_pending_invitation(
        self, class_id: UUID, lecturer_id: UUID, *, for_update: bool = False
    ) -> CoLecturerInvitation | None:
        """Re-reads the PENDING row after an index conflict (see invite_co_lecturer)."""
        query = select(CoLecturerInvitation).where(
            CoLecturerInvitation.class_id == class_id,
            CoLecturerInvitation.lecturer_id == lecturer_id,
            CoLecturerInvitation.status == CoLecturerInvitationStatus.PENDING,
        )
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def get_co_lecturer_invitation(
        self, invitation_id: UUID, *, for_update: bool = False
    ) -> CoLecturerInvitation | None:
        """Fetch by id for accept/reject/cancel; FOR UPDATE serializes state flips."""
        query = select(CoLecturerInvitation).where(CoLecturerInvitation.id == invitation_id)
        if for_update:
            query = query.with_for_update().execution_options(populate_existing=True)
        return self.session.scalar(query)

    def create_co_lecturer_invitation(
        self, invitation: CoLecturerInvitation
    ) -> CoLecturerInvitation:
        self.session.add(invitation)
        self.session.flush()
        return invitation

    def is_lecturer(self, user_id: UUID) -> bool:
        """Delegates to identity via public API (cross-module rule)."""
        return check_user_is_lecturer(user_id, session=self.session)

    def roles_of(self, user_id: UUID) -> list[str]:
        """System roles for the user, again via identity's public API."""
        return get_user_roles(user_id, session=self.session)


__all__ = ["ClassroomRepository"]
