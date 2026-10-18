import base64
import io
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID, uuid4

import pytest
from alembic import command
from openpyxl import Workbook
from sqlalchemy import delete, func, select, text, update

from app.common.audit import AuditEvent
from app.common.errors import AppError
from app.common.outbox import OutboxEvent
from app.common.security import hash_refresh_token
from app.modules.administration.models import StudentImportBatch
from app.modules.administration.service import AdministrationService
from app.modules.classroom.models import ClassMembership, HomeroomRoster
from app.modules.classroom.schemas import (
    ClassCreateRequest,
    CourseCreateRequest,
    HomeroomCreateRequest,
)
from app.modules.classroom.service import ClassroomService
from app.modules.identity.models import (
    AuthSession,
    OneTimeToken,
    Role,
    RoleAssignment,
    User,
    UserStatus,
)
from app.modules.notification.models import Notification
from app.modules.notification.worker import drain_outbox


def csv_body(value, **kwargs):
    return {"format": "CSV", "content_base64": base64.b64encode(value.encode()).decode(), **kwargs}


def preview(system, value="username,display_name\nstudent.import,Imported Student\n", **kwargs):
    response = system.client.post(
        "/api/v1/admin/students/imports/preview",
        json=csv_body(value, **kwargs),
        headers=system.headers(),
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(system, id, **kwargs):
    return system.client.post(
        "/api/v1/admin/students/imports/confirm",
        json={"preview_id": id},
        headers=system.headers(**kwargs),
    )


def test_staff_invitation_no_secret_response_audit_once_and_smtp_failure_rollback(system):
    response = system.client.post(
        "/api/v1/admin/users",
        json={"email": "Staff@Example.com", "roles": ["LECTURER"]},
        headers=system.headers(**{"X-Admin-Reason": "USER_REQUEST"}),
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    token = system.sender.deliveries[0].token.get_secret_value()
    assert token not in response.text and response.json()["status"] == "PENDING_VERIFICATION"
    assert response.headers["Cache-Control"] == "no-store"
    with system.factory() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.target_id == user_id)))
        assert len(events) == 1 and events[0].metadata_json["reason_code"] == "USER_REQUEST"
        assert events[0].school_id == system.school_id
        assert db.scalar(
            select(OneTimeToken).where(OneTimeToken.user_id == user_id)
        ).token_hash == hash_refresh_token(token)
        assert token not in str(events[0].metadata_json)
    system.sender.fail = True
    failed = system.client.post(
        "/api/v1/admin/users",
        json={"email": "failed@example.com", "roles": ["ADMIN"]},
        headers=system.headers(),
    )
    assert failed.status_code == 503
    with system.factory() as db:
        assert db.scalar(select(User).where(User.email == "failed@example.com")) is None
    assert (
        system.client.post(
            "/api/v1/admin/users",
            json={"email": "student@example.com", "roles": ["STUDENT"]},
            headers=system.headers(),
        ).status_code
        == 422
    )


def test_lock_revokes_access_refresh_and_unlock_does_not_bypass_activation(system):
    teacher = system.users["teacher"]
    old_headers = system.headers("teacher")
    with system.factory.begin() as db:
        db.add(
            AuthSession(
                user_id=teacher.id,
                refresh_hash=uuid4().hex,
                family_id=uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
    response = system.client.patch(
        f"/api/v1/admin/users/{teacher.id}/status",
        json={"status": "LOCKED"},
        headers=system.headers(**{"X-Admin-Reason": "POLICY_VIOLATION"}),
    )
    assert response.status_code == 204
    assert system.client.get("/api/v1/users/me", headers=old_headers).status_code == 401
    with system.factory() as db:
        assert db.get(User, teacher.id).session_version == teacher.session_version + 1
        assert (
            db.scalar(select(AuthSession).where(AuthSession.user_id == teacher.id)).revoked_at
            is not None
        )
        assert (
            db.scalar(select(AuditEvent).where(AuditEvent.target_id == teacher.id)).metadata_json[
                "reason_code"
            ]
            == "POLICY_VIOLATION"
        )
    provision = system.client.post(
        "/api/v1/admin/students", json={"username": "pending.import"}, headers=system.headers()
    ).json()
    pending = provision["student"]["id"]
    assert (
        system.client.patch(
            f"/api/v1/admin/users/{pending}/status",
            json={"status": "ACTIVE"},
            headers=system.headers(),
        ).status_code
        == 409
    )


def test_roles_revoke_old_token_and_cannot_convert_missing_credentials(system):
    teacher = system.users["teacher"]
    old_headers = system.headers("teacher")
    response = system.client.put(
        f"/api/v1/admin/users/{teacher.id}/roles",
        json={"roles": ["ADMIN", "LECTURER"]},
        headers=system.headers(),
    )
    assert response.status_code == 200
    assert system.client.get("/api/v1/users/me", headers=old_headers).status_code == 401
    with system.factory() as db:
        assert set(
            db.scalars(select(RoleAssignment.role).where(RoleAssignment.user_id == teacher.id))
        ) == {Role.ADMIN, Role.LECTURER}
        assert db.scalar(
            select(AuditEvent).where(AuditEvent.target_id == teacher.id)
        ).metadata_json["changed_fields"] == ["roles"]
    student = system.users["student"]
    assert (
        system.client.put(
            f"/api/v1/admin/users/{student.id}/roles",
            json={"roles": ["ADMIN"]},
            headers=system.headers(),
        ).status_code
        == 409
    )
    assert (
        system.client.put(
            f"/api/v1/admin/users/{teacher.id}/roles",
            json={"roles": ["STUDENT"]},
            headers=system.headers(),
        ).status_code
        == 409
    )


def test_cross_school_and_null_scope_are_hidden_and_current_role_is_authoritative(system):
    for name in ("other_student", "unscoped"):
        target = system.users[name]
        assert (
            system.client.patch(
                f"/api/v1/admin/users/{target.id}/status",
                json={"status": "LOCKED"},
                headers=system.headers(),
            ).status_code
            == 404
        )
        assert (
            system.client.put(
                f"/api/v1/admin/users/{target.id}/roles",
                json={"roles": ["LECTURER"]},
                headers=system.headers(),
            ).status_code
            == 404
        )
    assert (
        system.client.get(
            "/api/v1/admin/audit-events", headers=system.headers("unscoped")
        ).status_code
        == 404
    )
    old = system.headers("admin2")
    with system.factory.begin() as db:
        db.execute(
            delete(RoleAssignment).where(RoleAssignment.user_id == system.users["admin2"].id)
        )
        db.add(RoleAssignment(user_id=system.users["admin2"].id, role=Role.LECTURER))
    assert system.client.get("/api/v1/admin/audit-events", headers=old).status_code == 403


@pytest.mark.parametrize("operation", ["roles", "status"])
def test_last_admin_survives_concurrent_mutations(system, operation):
    # Keep exactly two active admins globally; other_school does not authorize mutations.
    with system.factory.begin() as db:
        db.execute(
            delete(RoleAssignment).where(
                RoleAssignment.user_id.in_(
                    [system.users["other_admin"].id, system.users["unscoped"].id]
                )
            )
        )
    barrier = Barrier(2)

    def mutate(name):
        actor = system.users[name]
        with system.factory() as session:
            service = AdministrationService(session, uuid4())
            barrier.wait(timeout=10)
            try:
                if operation == "roles":
                    service.set_roles(actor.id, actor.id, ["LECTURER"], "ADMIN_INTERVENTION")
                else:
                    service.set_status(actor.id, actor.id, "LOCKED", "ADMIN_INTERVENTION")
                return 200
            except AppError as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(mutate, ["admin", "admin2"]))
    assert sorted(results) == [200, 400]
    with system.factory() as db:
        usable = db.scalar(
            select(func.count())
            .select_from(User)
            .join(RoleAssignment)
            .where(User.status == UserStatus.ACTIVE, RoleAssignment.role == Role.ADMIN)
        )
        assert usable == 1


def test_import_confirm_replay_reimport_and_reissue_never_persist_codes(system):
    draft = preview(system)
    assert draft["valid"] and draft["items"][0]["action"] == "CREATE"
    response = confirm(system, draft["preview_id"])
    assert response.status_code == 200, response.text
    first = response.json()
    code, id = first["items"][0]["code"], first["items"][0]["student"]["id"]
    assert code and not first["replayed"]
    again = confirm(system, draft["preview_id"]).json()
    assert again["replayed"] and again["items"][0]["code"] is None
    assert again["items"][0]["student"]["id"] == id
    reimport = preview(system)
    assert reimport["items"][0]["action"] == "EXISTING"
    assert confirm(system, reimport["preview_id"]).json()["items"][0]["code"] is None
    with system.factory() as db:
        batch = db.get(StudentImportBatch, draft["preview_id"])
        assert batch.rows_json == []
        assert code not in str(batch.checks_json) + str(batch.results_json)
        assert (
            db.scalar(
                select(func.count()).select_from(User).where(User.username == "student.import")
            )
            == 1
        )
        assert code not in str(list(db.scalars(select(AuditEvent.metadata_json))))
    reissue = system.client.post(
        f"/api/v1/admin/students/{id}/activation-codes", json={}, headers=system.headers()
    ).json()
    assert reissue["code"] != code
    with system.factory() as db:
        assert (
            db.scalar(
                select(OneTimeToken).where(OneTimeToken.token_hash == hash_refresh_token(code))
            ).consumed_at
            is not None
        )


def test_import_invalid_duplicates_cross_school_and_expired_or_stale_preview(system):
    invalid = preview(system, "username\nduplicate\n DUPLICATE \n")
    assert not invalid["valid"] and invalid["preview_id"] is None
    other = system.session.get(User, system.users["other_student"].id)
    unavailable = preview(system, f"username\n{other.username}\n")
    assert not unavailable["valid"] and unavailable["errors"][0]["code"] == "ACCOUNT_UNAVAILABLE"
    draft = preview(system)
    with system.factory.begin() as db:
        db.get(StudentImportBatch, draft["preview_id"]).expires_at = (
            func.clock_timestamp() - timedelta(minutes=1)
        )
    assert confirm(system, draft["preview_id"]).status_code == 409
    draft = preview(system)
    system.client.post(
        "/api/v1/admin/students", json={"username": "student.import"}, headers=system.headers()
    )
    assert confirm(system, draft["preview_id"]).status_code == 409
    assert confirm(system, draft["preview_id"], name="other_admin").status_code == 404


def test_import_legacy_assign_preserves_identity_credentials_and_lock(system):
    id = uuid4()
    with system.factory.begin() as db:
        db.add(
            User(
                id=id,
                email="legacy@example.com",
                username=None,
                school_id=system.school_id,
                password_hash="legacy-preserved-hash",
                status=UserStatus.LOCKED,
                email_verified_at=datetime.now(UTC),
                session_version=7,
            )
        )
        db.flush()
        db.add(RoleAssignment(user_id=id, role=Role.STUDENT))
    draft = preview(system, f"username,user_id\nlegacy.student,{id}\n")
    assert draft["items"][0]["action"] == "ASSIGN_USERNAME"
    result = confirm(system, draft["preview_id"])
    assert result.status_code == 200, result.text
    assert result.json()["items"][0]["student"]["id"] == str(id)
    with system.factory() as db:
        user = db.get(User, id)
        assert user.password_hash == "legacy-preserved-hash" and user.status == UserStatus.LOCKED
        assert user.username == "legacy.student" and user.session_version == 8


def test_import_failure_rolls_back_entire_batch_and_retry_succeeds(system, monkeypatch):
    from app.modules.administration import service as admin_service

    draft = preview(system, "username\nimport.first\nimport.second\n")
    original = admin_service.identity.admin_create_student
    calls = 0

    def fail_second(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AppError(503, "Synthetic import failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(admin_service.identity, "admin_create_student", fail_second)
    assert confirm(system, draft["preview_id"]).status_code == 503
    with system.factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.username.in_(["import.first", "import.second"]))
            )
            == 0
        )
        assert db.get(StudentImportBatch, draft["preview_id"]).status == "PREVIEW"
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "ADMIN_CREATE_STUDENT")
            )
            == 0
        )
    monkeypatch.setattr(admin_service.identity, "admin_create_student", original)
    assert len(confirm(system, draft["preview_id"]).json()["items"]) == 2


def test_import_optional_roster_is_atomic_and_stale_roster_rejected(system, monkeypatch):
    classroom = ClassroomService(system.session)
    room = classroom.create_homeroom(
        system.users["admin"],
        HomeroomCreateRequest(name="9A", grade_level=9, academic_year="2026-2027"),
    )
    draft = preview(system, homeroom_class_id=str(room.id))
    classroom.set_roster(system.users["admin"], room.id, [system.users["student"].id])
    assert confirm(system, draft["preview_id"]).status_code == 409
    with system.factory() as db:
        assert db.scalar(select(User).where(User.username == "student.import")) is None
    draft = preview(system, homeroom_class_id=str(room.id))
    result = confirm(system, draft["preview_id"])
    assert result.status_code == 200, result.text
    imported_id = result.json()["items"][0]["student"]["id"]
    with system.factory() as db:
        assert set(
            db.scalars(
                select(HomeroomRoster.student_id).where(
                    HomeroomRoster.homeroom_class_id == room.id, HomeroomRoster.ended_at.is_(None)
                )
            )
        ) == {system.users["student"].id, UUID(imported_id)}


def test_concurrent_confirm_only_one_response_has_codes(system):
    draft = preview(system)
    barrier = Barrier(2)

    def run(_):
        with system.factory() as session:
            barrier.wait(timeout=10)
            return AdministrationService(session, uuid4()).confirm_students(
                system.users["admin"].id, UUID(draft["preview_id"]), "ADMIN_INTERVENTION"
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert sorted(result.replayed for result in results) == [False, True]
    assert sum(result.items[0].code is not None for result in results) == 1


def test_xlsx_http_preview_confirm(system):
    workbook = Workbook()
    workbook.active.append(["username", "display_name"])
    workbook.active.append(["excel.student", "Synthetic Excel Student"])
    data = io.BytesIO()
    workbook.save(data)
    workbook.close()
    response = system.client.post(
        "/api/v1/admin/students/imports/preview",
        json={"format": "XLSX", "content_base64": base64.b64encode(data.getvalue()).decode()},
        headers=system.headers(),
    )
    assert response.status_code == 200 and response.json()["valid"]
    result = confirm(system, response.json()["preview_id"])
    assert (
        result.status_code == 200
        and result.json()["items"][0]["student"]["username"] == "excel.student"
    )


def test_import_auto_enrollment_outbox_failure_rolls_back_every_owner(system, monkeypatch):
    classroom = ClassroomService(system.session)
    room = classroom.create_homeroom(
        system.users["admin"],
        HomeroomCreateRequest(name="AUTO 9A", grade_level=9, academic_year="2026-2027"),
    )
    course = classroom.create_course(
        system.users["admin"], CourseCreateRequest(code="AUTO", name="Synthetic course")
    )
    klass = classroom.create_class(
        system.users["admin"],
        ClassCreateRequest(
            course_id=course.id,
            name="AUTO subject",
            academic_year="2026-2027",
            semester="1",
            grade_level=9,
            enrollment_mode="AUTO",
            homeroom_class_id=room.id,
            primary_lecturer_id=system.users["teacher"].id,
        ),
    )
    draft = preview(system, homeroom_class_id=str(room.id))
    from app.modules.classroom import service as classroom_service

    original = classroom_service.record_outbox_event

    def fail(*args, **kwargs):
        raise AppError(503, "Synthetic outbox failure")

    monkeypatch.setattr(classroom_service, "record_outbox_event", fail)
    assert confirm(system, draft["preview_id"]).status_code == 503
    with system.factory() as db:
        assert db.scalar(select(User).where(User.username == "student.import")) is None
        assert db.scalar(select(func.count()).select_from(HomeroomRoster)) == 0
        assert db.scalar(select(func.count()).select_from(ClassMembership)) == 0
        assert db.scalar(select(func.count()).select_from(OutboxEvent)) == 0
        assert db.get(StudentImportBatch, draft["preview_id"]).status == "PREVIEW"
    monkeypatch.setattr(classroom_service, "record_outbox_event", original)
    result = confirm(system, draft["preview_id"])
    assert result.status_code == 200, result.text
    imported_id = UUID(result.json()["items"][0]["student"]["id"])
    # This assertion exercises committed recipients/rollback, not wall-clock
    # scheduling. Establish due events explicitly; retry scheduling has its own tests.
    with system.factory.begin() as db:
        db.execute(
            update(OutboxEvent)
            .where(OutboxEvent.attempts == 0)
            .values(available_at=func.now() - timedelta(days=1))
        )
    delivered = drain_outbox(session_factory=system.factory)
    with system.factory() as db:
        timing = db.execute(
            text(
                "SELECT attempts,available_at,clock_timestamp(),published_at FROM core.outbox_events"
            )
        ).all()
    assert delivered == 1, timing
    with system.factory() as db:
        assert (
            db.scalar(
                select(ClassMembership).where(
                    ClassMembership.class_id == klass.id, ClassMembership.student_id == imported_id
                )
            )
            is not None
        )
        assert (
            db.scalar(select(Notification).where(Notification.recipient_id == imported_id))
            is not None
        )


def test_audit_tenant_filter_pagination_and_redaction_do_not_leak(system):
    with system.factory.begin() as db:
        for index in range(3):
            db.add(
                AuditEvent(
                    actor_id=system.users["admin"].id,
                    school_id=system.school_id,
                    action="SYNTHETIC_ACTION",
                    target_type="USER",
                    target_id=uuid4(),
                    correlation_id=uuid4(),
                    metadata_json={"token": "test-only-never-echo"}
                    if index == 0
                    else {"reason_code": "USER_REQUEST"},
                )
            )
        db.add(
            AuditEvent(
                actor_id=None,
                school_id=None,
                action="LEGACY_SCOPE_UNKNOWN",
                target_type="USER",
                target_id=uuid4(),
                correlation_id=uuid4(),
                metadata_json={},
            )
        )
        db.add(
            AuditEvent(
                actor_id=system.users["other_admin"].id,
                school_id=system.users["other_admin"].school_id,
                action="OTHER_SCHOOL",
                target_type="USER",
                target_id=uuid4(),
                correlation_id=uuid4(),
                metadata_json={},
            )
        )
    first = system.client.get(
        "/api/v1/admin/audit-events?limit=2&action=SYNTHETIC_ACTION", headers=system.headers()
    ).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    second = system.client.get(
        f"/api/v1/admin/audit-events?limit=2&action=SYNTHETIC_ACTION&cursor={first['next_cursor']}",
        headers=system.headers(),
    ).json()
    assert len(second["items"]) == 1
    assert "test-only-never-echo" not in str(first) + str(second)
    all_events = system.client.get("/api/v1/admin/audit-events", headers=system.headers()).json()[
        "items"
    ]
    assert not any(row["action"] in {"OTHER_SCHOOL", "LEGACY_SCOPE_UNKNOWN"} for row in all_events)
    assert (
        system.client.get(
            f"/api/v1/admin/audit-events?cursor={first['next_cursor']}",
            headers=system.headers("other_admin"),
        ).status_code
        == 400
    )


@pytest.mark.parametrize("request_type", ["ACCESS", "EXPORT", "CORRECTION", "DELETE"])
def test_data_requests_verify_defer_without_false_completion_and_reject_with_audit(
    system, request_type
):
    created = system.client.post(
        "/api/v1/users/me/data-requests",
        json={"type": request_type, "reason": "Synthetic request context"},
        headers=system.headers("student"),
    )
    assert created.status_code == 201
    id = created.json()["id"]
    assert (
        system.client.get(
            f"/api/v1/admin/data-requests/{id}", headers=system.headers("other_admin")
        ).status_code
        == 404
    )
    assert (
        system.client.get(f"/api/v1/admin/data-requests/{id}", headers=system.headers()).status_code
        == 200
    )
    command = {"status": "COMPLETED", "resolution_note": "POLICY_PENDING"}
    assert (
        system.client.patch(
            f"/api/v1/admin/data-requests/{id}", json=command, headers=system.headers()
        ).status_code
        == 409
    )
    command["identity_verified"] = True
    result = system.client.patch(
        f"/api/v1/admin/data-requests/{id}", json=command, headers=system.headers()
    )
    assert result.status_code == 200 and result.json()["status"] == "IN_REVIEW"
    assert result.json()["resolution_note"] == "POLICY_PENDING"
    rejected = system.client.patch(
        f"/api/v1/admin/data-requests/{id}",
        json={
            "status": "REJECTED",
            "resolution_note": "REQUEST_REJECTED",
            "identity_verified": True,
        },
        headers=system.headers(),
    )
    assert rejected.json()["status"] == "REJECTED"
    assert (
        system.client.patch(
            f"/api/v1/admin/data-requests/{id}", json=command, headers=system.headers()
        ).status_code
        == 409
    )
    with system.factory() as db:
        assert db.get(User, system.users["student"].id) is not None
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.target_id == id)))
        assert sum(row.action == "DATA_REQUEST_DEFERRED" for row in events) == 1
        assert all("Synthetic request context" not in str(row.metadata_json) for row in events)


def test_administration_migration_preserves_legacy_audit_and_blocks_loss(database):
    command.downgrade(database.config, "0011")
    legacy = uuid4()
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO core.audit_events(id,actor_id,action,target_type,target_id,correlation_id,metadata_json) VALUES (:id,NULL,'LEGACY_EVENT','USER',:target,:correlation,'{}')"
            ),
            {"id": legacy, "target": uuid4(), "correlation": uuid4()},
        )
    command.upgrade(database.config, "head")
    command.check(database.config)
    with database.factory() as db:
        assert db.get(AuditEvent, legacy).school_id is None
    command.downgrade(database.config, "0011")
    command.upgrade(database.config, "head")
    with database.factory.begin() as db:
        db.get(AuditEvent, legacy).school_id = uuid4()
    with pytest.raises(RuntimeError, match="Preserve audit school scope"):
        command.downgrade(database.config, "0011")
