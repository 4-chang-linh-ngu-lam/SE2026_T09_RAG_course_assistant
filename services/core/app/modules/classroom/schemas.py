from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.classroom.models import (
    ClassStatus,
    EnrollmentMode,
    MembershipStatus,
    TeachingRole,
)


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClassAccessAction(StrEnum):
    READ_CLASS_CONTENT = "read_class_content"
    PARTICIPATE_CURRENT_CLASS = "participate_current_class"
    MODERATE_CLASS_CONTENT = "moderate_class_content"
    MANAGE_CLASS_CALENDAR = "manage_class_calendar"
    READ_OWN_HISTORY = "read_own_history"
    READ_DOCUMENT_SOURCE = "read_document_source"
    USE_AI_TUTOR = "use_ai_tutor"
    GRADE_SUBMITTED_WORK = "grade_submitted_work"


class CourseCreateRequest(RequestModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)


class CourseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    school_id: UUID


class AcademicYearResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    school_id: UUID
    label: str


class SemesterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    academic_year_id: UUID
    name: str


class HomeroomCreateRequest(RequestModel):
    name: str = Field(min_length=1, max_length=200)
    academic_year: str = Field(min_length=1, max_length=30)
    grade_level: int = Field(ge=6, le=12)


class HomeroomResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    school_id: UUID
    academic_year_id: UUID
    name: str
    grade_level: int
    roster_version: int
    student_count: int = 0


class AdminCatalogResponse(BaseModel):
    courses: list[CourseResponse]
    academic_years: list[AcademicYearResponse]
    semesters: list[SemesterResponse]
    homerooms: list[HomeroomResponse]
    grades: list[int]


class RosterRequest(RequestModel):
    student_ids: list[UUID]
    expected_roster_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def unique_students(self):
        if len(self.student_ids) != len(set(self.student_ids)):
            raise ValueError("Duplicate student")
        return self


class RosterResponse(BaseModel):
    homeroom_class_id: UUID
    student_ids: list[UUID]
    roster_version: int


class ClassCreateRequest(RequestModel):
    course_id: UUID
    name: str = Field(min_length=1, max_length=200)
    academic_year: str = Field(min_length=1, max_length=30)
    semester: str = Field(min_length=1, max_length=50)
    grade_level: int = Field(ge=6, le=12)
    homeroom_class_id: UUID | None = None
    enrollment_mode: EnrollmentMode
    primary_lecturer_id: UUID
    assisting_lecturer_ids: list[UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_teachers(self):
        if self.primary_lecturer_id in self.assisting_lecturer_ids or len(
            self.assisting_lecturer_ids
        ) != len(set(self.assisting_lecturer_ids)):
            raise ValueError("A teacher can have one assignment per class")
        return self


class ClassResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    school_id: UUID
    academic_year_id: UUID
    semester_id: UUID
    course_id: UUID
    homeroom_class_id: UUID | None
    name: str
    grade_level: int
    enrollment_mode: EnrollmentMode
    status: ClassStatus
    version: int
    teaching_role: TeachingRole | None = None


class TeachingAssignmentsRequest(RequestModel):
    primary_lecturer_id: UUID
    assisting_lecturer_ids: list[UUID] = Field(default_factory=list)
    expected_class_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def unique_teachers(self):
        if self.primary_lecturer_id in self.assisting_lecturer_ids or len(
            self.assisting_lecturer_ids
        ) != len(set(self.assisting_lecturer_ids)):
            raise ValueError("A teacher can have one assignment per class")
        return self


class TeachingAssignmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_id: UUID
    lecturer_id: UUID
    role: TeachingRole
    assigned_at: datetime
    ended_at: datetime | None = None


class MembershipRequest(RequestModel):
    student_id: UUID


class MembershipRosterRequest(RequestModel):
    student_ids: list[UUID]
    expected_class_version: int = Field(ge=1)

    @model_validator(mode="after")
    def unique_students(self):
        if len(self.student_ids) != len(set(self.student_ids)):
            raise ValueError("Duplicate student")
        return self


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    class_id: UUID
    student_id: UUID
    source: EnrollmentMode
    status: MembershipStatus
    joined_at: datetime
    ended_at: datetime | None = None


class ClassManagementResponse(BaseModel):
    subject_class: ClassResponse
    teaching_assignments: list[TeachingAssignmentResponse]
    members: list[MembershipResponse]


class EnrollmentPreviewResponse(BaseModel):
    class_id: UUID
    target_mode: EnrollmentMode
    class_version: int
    roster_version: int
    add_student_ids: list[UUID]
    end_student_ids: list[UUID]


class EnrollmentModeRequest(RequestModel):
    mode: EnrollmentMode
    expected_class_version: int | None = Field(default=None, ge=1)
    expected_roster_version: int | None = Field(default=None, ge=1)


class EnrollmentSyncRequest(RequestModel):
    expected_class_version: int = Field(ge=1)
    expected_roster_version: int = Field(ge=1)


class ClassVersionRequest(RequestModel):
    expected_class_version: int = Field(ge=1)


class TransferRequest(RequestModel):
    destination_class_id: UUID


class HomeroomTransferRequest(RequestModel):
    destination_homeroom_id: UUID
    expected_source_roster_version: int | None = Field(default=None, ge=1)
    expected_destination_roster_version: int | None = Field(default=None, ge=1)


class ClassAccessDTO(BaseModel):
    allowed: bool
    class_id: UUID
    school_id: UUID | None = None
    class_status: ClassStatus | None = None
    teaching_role: TeachingRole | None = None


class InternalAccessResponse(ClassAccessDTO):
    user_id: UUID
    action: ClassAccessAction


class NotificationAudienceDTO(BaseModel):
    """Identifiers only; this snapshot never grants access to class content."""

    school_id: UUID
    recipient_ids: list[UUID]


class RosterImportSnapshot(BaseModel):
    homeroom_class_id: UUID
    school_id: UUID
    roster_version: int
    student_ids: list[UUID]
