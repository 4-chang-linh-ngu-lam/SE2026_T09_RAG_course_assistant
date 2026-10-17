from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.common.errors import AppError
from app.main import app
from app.modules.classroom import public
from app.modules.classroom.models import ClassStatus, TeachingRole
from app.modules.classroom.schemas import (
    ClassAccessAction,
    ClassCreateRequest,
    TeachingAssignmentsRequest,
)
from app.modules.identity.schemas import UserSummaryDTO


def test_openapi_exposes_admin_classroom_without_legacy_join_flows():
    paths = app.openapi()["paths"]
    assert "/api/v1/admin/classes" in paths
    assert "/api/v1/admin/homeroom-classes" in paths
    assert "/api/v1/admin/classes/{class_id}/enrollment/preview" in paths
    assert "/internal/v1/classes/{class_id}/access" in paths
    assert not any(
        "join-request" in path
        or "ownership-transfer" in path
        or "co-lecturers/invitations" in path
        or path.endswith("/members/me")
        for path in paths
    )
    assert "/api/v1/classes" in paths
    assert "post" not in paths["/api/v1/classes"]


def test_classroom_requests_validate_grade_and_teacher_assignment():
    values = {
        "course_id": uuid4(),
        "name": "Toán 9A",
        "academic_year": "2026-2027",
        "semester": "1",
        "primary_lecturer_id": uuid4(),
        "enrollment_mode": "AUTO",
    }
    with pytest.raises(ValidationError):
        ClassCreateRequest(**values, grade_level=5)
    with pytest.raises(ValidationError):
        ClassCreateRequest(**values, grade_level=13)
    with pytest.raises(ValidationError):
        TeachingAssignmentsRequest(
            primary_lecturer_id=values["primary_lecturer_id"],
            assisting_lecturer_ids=[values["primary_lecturer_id"]],
        )


def test_class_access_separates_archived_reads_and_current_writes(monkeypatch):
    school_id, class_id, student_id = uuid4(), uuid4(), uuid4()
    state = {
        "status": ClassStatus.ACTIVE,
        "current": True,
        "history": True,
        "roles": ["STUDENT"],
        "school_id": school_id,
        "user_status": "ACTIVE",
        "teacher": False,
    }

    class Repository:
        def get_class(self, requested_id):
            assert requested_id == class_id
            return SimpleNamespace(school_id=school_id, status=state["status"])

        def active_membership(self, requested_id, requested_student):
            return object() if state["current"] else None

        def active_teacher(self, requested_id, requested_user):
            return SimpleNamespace(role=TeachingRole.PRIMARY) if state["teacher"] else None

        def has_membership_history(self, requested_id, requested_user):
            return state["history"]

    monkeypatch.setattr(public, "ClassroomRepository", lambda _: Repository())
    monkeypatch.setattr(
        public,
        "get_user_summary",
        lambda *args, **kwargs: UserSummaryDTO(
            id=student_id,
            email=None,
            username="student.test",
            school_id=state["school_id"],
            status=state["user_status"],
        ),
    )
    monkeypatch.setattr(public, "get_user_roles", lambda *args, **kwargs: state["roles"])
    check = lambda action: public.check_class_action(class_id, student_id, action, session=object())
    assert check(ClassAccessAction.PARTICIPATE_CURRENT_CLASS).allowed
    assert check(ClassAccessAction.USE_AI_TUTOR).allowed
    state["status"] = ClassStatus.ARCHIVED
    assert check(ClassAccessAction.READ_CLASS_CONTENT).allowed
    assert not check(ClassAccessAction.PARTICIPATE_CURRENT_CLASS).allowed
    assert not check(ClassAccessAction.USE_AI_TUTOR).allowed
    state["current"] = False
    assert not check(ClassAccessAction.READ_CLASS_CONTENT).allowed
    assert check(ClassAccessAction.READ_OWN_HISTORY).allowed
    state["school_id"] = uuid4()
    assert not check(ClassAccessAction.READ_OWN_HISTORY).allowed
    state["school_id"] = school_id
    state["user_status"] = "LOCKED"
    assert not check(ClassAccessAction.READ_OWN_HISTORY).allowed
    state["user_status"] = "ACTIVE"
    state["roles"] = ["LECTURER"]
    state["teacher"] = True
    state["status"] = ClassStatus.ACTIVE
    assert check(ClassAccessAction.GRADE_SUBMITTED_WORK).allowed
    state["teacher"] = False
    assert not check(ClassAccessAction.GRADE_SUBMITTED_WORK).allowed
    state["roles"] = ["ADMIN"]
    assert check(ClassAccessAction.MODERATE_CLASS_CONTENT).allowed
    assert not check(ClassAccessAction.READ_CLASS_CONTENT).allowed
    with pytest.raises(AppError) as error:
        check("join_by_code")
    assert error.value.status_code == 400


def test_class_access_propagates_database_outage(monkeypatch):
    monkeypatch.setattr(public, "get_user_summary", lambda *args, **kwargs: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        public.check_class_action(
            uuid4(), uuid4(), ClassAccessAction.READ_CLASS_CONTENT, session=object()
        )
