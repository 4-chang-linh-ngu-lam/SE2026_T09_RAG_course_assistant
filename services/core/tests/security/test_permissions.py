from uuid import uuid4

import pytest
from sqlalchemy import text

from app.common.auth_dependencies import get_user_lookup
from app.common.errors import AppError


@pytest.mark.parametrize(
    "actor", ["seed.student.1", "primary@seed.example.com", "assisting@seed.example.com"]
)
def test_non_admin_cannot_manage_classes_and_cannot_self_join_or_leave(backend, actor):
    b = backend
    klass = b.classes["9:MANUAL"]
    student = b.users["seed.student.1"].id
    headers = b.headers(actor)
    requests = [
        (
            "post",
            "/api/v1/admin/classes",
            {
                "course_id": str(uuid4()),
                "name": "Denied",
                "academic_year": "2026-2027",
                "semester": "1",
                "grade_level": 9,
                "enrollment_mode": "MANUAL",
                "primary_lecturer_id": str(b.users["primary@seed.example.com"].id),
            },
        ),
        ("put", f"/api/v1/admin/homeroom-classes/{b.rooms[9]}/roster", {"student_ids": []}),
        (
            "put",
            f"/api/v1/admin/classes/{klass}/teaching-assignments",
            {"primary_lecturer_id": str(b.users["primary@seed.example.com"].id)},
        ),
        ("post", f"/api/v1/admin/classes/{klass}/members", {"student_id": str(student)}),
        ("delete", f"/api/v1/admin/classes/{klass}/members/{student}", None),
        ("post", f"/api/v1/admin/classes/{klass}/archive", None),
        ("post", f"/api/v1/admin/classes/{klass}/restore", None),
    ]
    for method, path, body in requests:
        result = b.client.request(method, path, headers=headers, json=body)
        assert result.status_code == 403, (method, path, result.status_code)
    for method, path in [
        ("post", f"/api/v1/classes/{klass}/join-requests"),
        ("delete", f"/api/v1/classes/{klass}/members/me"),
    ]:
        assert b.client.request(method, path, headers=headers).status_code in (404, 405)
    assert (
        b.client.post(
            "/api/v1/auth/register",
            json={"email": "denied@example.com", "password": "Synthetic-Registration-Only"},
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "state", ["LOCKED", "PENDING_VERIFICATION", "NO_SCOPE", "OTHER_SCHOOL", "OTHER_CLASS"]
)
def test_current_database_state_overrides_issued_jwt(backend, state):
    b = backend
    student = b.users["seed.student.1"]
    headers = b.headers("seed.student.1")
    klass = b.classes["9:MANUAL"]
    assert b.client.get(f"/api/v1/classes/{klass}/posts", headers=headers).status_code == 200
    with b.engine.begin() as connection:
        if state in ("LOCKED", "PENDING_VERIFICATION"):
            connection.execute(
                text("UPDATE core.users SET status=:state WHERE id=:id"),
                {"state": state, "id": student.id},
            )
        elif state in ("NO_SCOPE", "OTHER_SCHOOL"):
            scope = uuid4() if state == "OTHER_SCHOOL" else None
            if scope is not None:
                connection.execute(
                    text("INSERT INTO core.schools(id,name) VALUES (:id,'Other synthetic school')"),
                    {"id": scope},
                )
            connection.execute(
                text("UPDATE core.users SET school_id=:scope WHERE id=:id"),
                {"scope": scope, "id": student.id},
            )
        else:
            connection.execute(
                text(
                    "UPDATE core.class_memberships SET status='ENDED',ended_at=now() WHERE class_id=:class AND student_id=:id"
                ),
                {"class": klass, "id": student.id},
            )
    response = b.client.get(f"/api/v1/classes/{klass}/posts", headers=headers)
    assert response.status_code == (401 if state in ("LOCKED", "PENDING_VERIFICATION") else 404)
    assert "Synthetic" not in response.text


def test_class_post_comment_relations_and_identity_failure_are_fail_closed(backend):
    b = backend
    first, second = b.classes["9:AUTO"], b.classes["8:MANUAL"]
    teacher = b.headers("primary@seed.example.com")
    post = b.client.post(
        f"/api/v1/classes/{first}/posts", headers=teacher, json={"body": "Private synthetic body"}
    ).json()
    comment = b.client.post(
        f"/api/v1/classes/{first}/posts/{post['id']}/comments",
        headers=teacher,
        json={"body": "Private synthetic comment"},
    ).json()
    for method, path, body in [
        ("get", f"/api/v1/classes/{second}/posts/{post['id']}/comments", None),
        ("patch", f"/api/v1/classes/{second}/posts/{post['id']}", {"body": "Denied"}),
        ("delete", f"/api/v1/classes/{second}/posts/{post['id']}/comments/{comment['id']}", None),
        ("get", f"/api/v1/classes/{uuid4()}/posts", None),
    ]:
        response = b.client.request(method, path, headers=teacher, json=body)
        assert response.status_code == 404
        assert "Private synthetic" not in response.text

    def unavailable():
        def lookup(_):
            raise AppError(503, "Identity unavailable")

        return lookup

    b.app.dependency_overrides[get_user_lookup] = unavailable
    response = b.client.get(f"/api/v1/classes/{first}/posts", headers=teacher)
    assert response.status_code == 503
    assert "Private synthetic" not in response.text


@pytest.mark.parametrize(
    "operation", ["archive", "end", "roster", "transfer", "course", "homeroom", "teachers"]
)
def test_cached_classroom_mutation_cannot_cross_changed_school_scope(backend, operation):
    b = backend
    klass = b.classes["9:MANUAL"]
    method, path, body = "post", f"/api/v1/admin/classes/{klass}/archive", None
    if operation == "end":
        method, path = (
            "delete",
            f"/api/v1/admin/classes/{klass}/members/{b.users['seed.student.1'].id}",
        )
    elif operation == "roster":
        method, path, body = (
            "put",
            f"/api/v1/admin/homeroom-classes/{b.rooms[9]}/roster",
            {"student_ids": []},
        )
    elif operation == "transfer":
        path, body = (
            f"/api/v1/admin/classes/{klass}/members/{b.users['seed.student.1'].id}/transfer",
            {"destination_class_id": str(b.classes["8:MANUAL"])},
        )
    elif operation == "course":
        path, body = "/api/v1/admin/courses", {"code": "CACHE-TEST", "name": "Cache test"}
    elif operation == "homeroom":
        path, body = (
            "/api/v1/admin/homeroom-classes",
            {"name": "Cache test", "academic_year": "2026-2027", "grade_level": 9},
        )
    elif operation == "teachers":
        method, path, body = (
            "put",
            f"/api/v1/admin/classes/{klass}/teaching-assignments",
            {"primary_lecturer_id": str(b.users["primary@seed.example.com"].id)},
        )
    headers = b.headers(**{"Idempotency-Key": str(uuid4())})
    first = b.client.request(method, path, headers=headers, json=body)
    assert first.status_code in (200, 201, 204)
    other_school = uuid4()
    with b.engine.begin() as connection:
        connection.execute(
            text("INSERT INTO core.schools(id,name) VALUES (:id,'Other synthetic school')"),
            {"id": other_school},
        )
        connection.execute(
            text("UPDATE core.users SET school_id=:school WHERE id=:id"),
            {"school": other_school, "id": b.users["admin@seed.example.com"].id},
        )
    # JWT stays valid, but current resource scope is no longer authorized.
    replay = b.client.request(method, path, headers=headers, json=body)
    assert replay.status_code == 404
