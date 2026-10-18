"""Core-04: actual HTTP authentication, workflow transactions and worker delivery."""

import secrets
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.common.config import settings
from app.modules.notification.worker import drain_outbox


def ok(response, status=200):
    assert response.status_code == status, response.text
    assert response.headers.get("Cache-Control") == "no-store"
    return response.json() if response.content else None


def test_provision_to_social_transfer_archive_and_revocation(backend, caplog):
    b = backend
    login = b.client.post(
        "/api/v1/auth/login", json={"email": "admin@seed.example.com", "password": b.password}
    )
    admin = {
        "Authorization": "Bearer " + ok(login)["access_token"],
        "X-Admin-Reason": "ADMIN_INTERVENTION",
    }
    assert "HttpOnly" in login.headers["set-cookie"] and "Secure" in login.headers["set-cookie"]
    created = ok(
        b.client.post(
            "/api/v1/admin/students", json={"username": "journey.student"}, headers=admin
        ),
        201,
    )
    student_id, code = created["student"]["id"], created["code"]
    assert created["student"]["email"] is None
    password = secrets.token_urlsafe(32)
    activation = {"username": "journey.student", "activation_code": code, "new_password": password}
    ok(b.client.post("/api/v1/auth/activate", json=activation), 204)
    assert b.client.post("/api/v1/auth/activate", json=activation).status_code == 400
    student_login = b.client.post(
        "/api/v1/auth/login", json={"username": "journey.student", "password": password}
    )
    student = {"Authorization": "Bearer " + ok(student_login)["access_token"]}
    ok(b.client.post("/api/v1/auth/refresh", headers={"Origin": "https://testserver"}))
    first, second = b.classes["9:MANUAL"], b.classes["8:MANUAL"]
    # Both seeded classes share course/year/semester; only Admin may enroll/transfer.
    ok(
        b.client.post(
            f"/api/v1/admin/classes/{first}/members", headers=admin, json={"student_id": student_id}
        ),
        201,
    )
    teacher = b.headers("primary@seed.example.com")
    post = ok(
        b.client.post(
            f"/api/v1/classes/{first}/posts",
            headers=student,
            json={"body": "Synthetic class discussion"},
        ),
        201,
    )
    comments_path = f"/api/v1/classes/{first}/posts/{post['id']}/comments"
    comment = ok(
        b.client.post(comments_path, headers=teacher, json={"body": "Synthetic teacher response"}),
        201,
    )
    event = ok(
        b.client.post(
            f"/api/v1/classes/{first}/calendar",
            headers=teacher,
            json={
                "title": "Synthetic class event",
                "starts_at": "2026-11-01T01:00:00Z",
                "ends_at": "2026-11-01T02:00:00Z",
            },
        ),
        201,
    )
    assert any(
        item["id"] == event["id"]
        for item in ok(b.client.get(f"/api/v1/classes/{first}/calendar", headers=student))["items"]
    )
    drain_outbox(session_factory=b.factory, batch_size=1000)
    inbox = ok(b.client.get("/api/v1/notifications", headers=student))
    assert inbox["unread_count"] > 0
    notification = inbox["items"][0]["id"]
    assert (
        b.client.patch(f"/api/v1/notifications/{notification}/read", headers=teacher).status_code
        == 404
    )
    ok(b.client.patch(f"/api/v1/notifications/{notification}/read", headers=student))
    ok(b.client.delete(f"{comments_path}/{comment['id']}", headers=admin), 204)
    assert ok(b.client.get(comments_path, headers=student))["items"] == []
    ok(
        b.client.post(
            f"/api/v1/admin/classes/{first}/members/{student_id}/transfer",
            headers=admin,
            json={"destination_class_id": str(second)},
        )
    )
    assert b.client.get(f"/api/v1/classes/{first}/posts", headers=student).status_code == 404
    decision = b.client.get(
        f"/internal/v1/classes/{first}/access",
        params={"user_id": student_id, "action": "read_own_history"},
        headers={"X-Service-Key": settings.internal_service_secret.get_secret_value()},
    )
    assert decision.json()["allowed"] is True
    assert (
        b.client.get(
            f"/internal/v1/classes/{first}/access",
            params={"user_id": student_id, "action": "read_own_history"},
            headers=student,
        ).status_code
        == 401
    )
    ok(b.client.post(f"/api/v1/admin/classes/{second}/archive", headers=admin))
    assert (
        b.client.post(
            f"/api/v1/classes/{second}/posts", headers=student, json={"body": "Blocked"}
        ).status_code
        == 409
    )
    ok(b.client.get(f"/api/v1/classes/{second}", headers=student))
    ok(b.client.post(f"/api/v1/admin/classes/{second}/restore", headers=admin))
    ok(
        b.client.patch(
            f"/api/v1/admin/users/{student_id}/status", headers=admin, json={"status": "LOCKED"}
        ),
        204,
    )
    assert b.client.get("/api/v1/users/me", headers=student).status_code == 401
    assert (
        b.client.post("/api/v1/auth/refresh", headers={"Origin": "https://testserver"}).status_code
        == 401
    )
    with b.factory() as db:
        assert (
            db.scalar(
                text("SELECT count(*) FROM core.class_memberships WHERE student_id=:id"),
                {"id": student_id},
            )
            == 2
        )
        audit = db.execute(text("SELECT action,metadata_json FROM core.audit_events")).all()
        assert any(row.action == "ADMIN_TRANSFER_STUDENT" for row in audit)
        assert any("COMMENT" in row.action for row in audit)
        serialized = str(audit)
        assert code not in serialized and password not in serialized
    assert code not in caplog.text and password not in caplog.text


@pytest.mark.parametrize("request_type", ["ACCESS", "EXPORT", "CORRECTION", "DELETE"])
def test_unfulfilled_data_requests_stay_in_review_and_audit_is_redacted(backend, request_type):
    b = backend
    student = b.headers("seed.student.1")
    private = "Synthetic private request " + uuid4().hex
    request = ok(
        b.client.post(
            "/api/v1/users/me/data-requests",
            headers=student,
            json={"request_type": request_type, "reason": private},
        ),
        201,
    )
    route = f"/api/v1/admin/data-requests/{request['id']}"
    assert (
        b.client.patch(
            route,
            headers=b.headers(),
            json={"status": "COMPLETED", "resolution_note": "POLICY_PENDING"},
        ).status_code
        == 409
    )
    deferred = ok(
        b.client.patch(
            route,
            headers=b.headers(),
            json={
                "status": "COMPLETED",
                "resolution_note": "POLICY_PENDING",
                "identity_verified": True,
            },
        )
    )
    assert (deferred["status"], deferred["resolution_note"]) == ("IN_REVIEW", "POLICY_PENDING")
    audit = ok(b.client.get("/api/v1/admin/audit-events", headers=b.headers()))
    assert private not in str(audit)
    assert b.client.get(route, headers=student).status_code == 403
