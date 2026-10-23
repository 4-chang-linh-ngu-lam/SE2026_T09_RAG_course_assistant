import base64
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.modules.identity.idempotency import IdempotencyStore, get_idempotency_store


@pytest.mark.parametrize("operation", ["sync", "transfer", "import"])
def test_one_hundred_concurrent_operations_keep_membership_and_manual_history(backend, operation):
    b = backend
    first, second = b.classes["9:MANUAL"], b.classes["8:MANUAL"]
    student = b.users["seed.student.1"].id
    with b.engine.connect() as connection:
        manual_before = set(
            connection.scalars(
                text(
                    "SELECT student_id FROM core.class_memberships WHERE class_id=:id AND status='ACTIVE'"
                ),
                {"id": first},
            )
        )
    headers = b.headers(**{"Idempotency-Key": str(uuid4())})
    preview_id = None
    if operation == "sync":
        path, body = f"/api/v1/admin/classes/{b.classes['9:AUTO']}/enrollment/sync", None

        # Sync requests compete with real roster mutations; MANUAL stays independent.
        def invoke(index):
            if index % 4 == 0:
                return b.client.put(
                    f"/api/v1/admin/homeroom-classes/{b.rooms[9]}/roster",
                    headers=b.headers(),
                    json={
                        "student_ids": [str(student)]
                        if index % 8 == 0
                        else [str(student), str(b.users["seed.student.2"].id)]
                    },
                )
            return b.client.post(path, headers=b.headers())
    elif operation == "transfer":
        path = f"/api/v1/admin/classes/{first}/members/{student}/transfer"
        body = {"destination_class_id": str(second)}

        def invoke(_):
            return b.client.post(path, headers=headers, json=body)
    else:
        content = base64.b64encode(b"username\nconcurrent.import.student\n").decode()
        preview = b.client.post(
            "/api/v1/admin/students/imports/preview",
            headers=b.headers(),
            json={"format": "CSV", "content_base64": content, "homeroom_class_id": str(b.rooms[9])},
        )
        assert preview.status_code == 200 and preview.json()["valid"]
        preview_id = preview.json()["preview_id"]
        path, body = "/api/v1/admin/students/imports/confirm", {"preview_id": preview_id}

        def invoke(_):
            return b.client.post(path, headers=b.headers(), json=body)

    with ThreadPoolExecutor(max_workers=16) as pool:
        responses = list(pool.map(invoke, range(100)))
    assert all(response.status_code == 200 for response in responses), [
        r.status_code for r in responses
    ]
    if operation == "import":
        assert sum(not r.json()["replayed"] for r in responses) == 1
        assert sum(item["code"] is not None for r in responses for item in r.json()["items"]) == 1
        # A new app/cache represents process restart. Durable import IDs survive,
        # while first-response code must never be replayed from the database.
        restarted = b.make_app()
        restarted.dependency_overrides[get_idempotency_store] = lambda: IdempotencyStore()
        with TestClient(restarted) as client:
            replay = client.post(path, headers=b.headers(), json={"preview_id": preview_id})
            assert replay.status_code == 200 and replay.json()["replayed"]
            assert replay.json()["items"][0]["code"] is None
    with b.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM (SELECT class_id,student_id FROM core.class_memberships WHERE status='ACTIVE' GROUP BY class_id,student_id HAVING count(*)>1) duplicates"
                )
            )
            == 0
        )
        rows = connection.execute(
            text(
                "SELECT class_id,status,ended_at FROM core.class_memberships WHERE student_id=:id AND class_id IN (:first,:second)"
            ),
            {"id": student, "first": first, "second": second},
        ).all()
        if operation == "transfer":
            assert len(rows) == 2
            assert sum(row.status == "ACTIVE" for row in rows) == 1
            assert sum(row.status == "ENDED" and row.ended_at is not None for row in rows) == 1
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM core.audit_events WHERE action='ADMIN_TRANSFER_STUDENT'"
                    )
                )
                == 1
            )
        else:
            assert len(rows) == 1 and rows[0].status == "ACTIVE"
            manual_after = set(
                connection.scalars(
                    text(
                        "SELECT student_id FROM core.class_memberships WHERE class_id=:id AND status='ACTIVE'"
                    ),
                    {"id": first},
                )
            )
            assert manual_after == manual_before
        if operation == "sync":
            # Reconcile final committed roster after concurrent requests settle.
            final = b.client.post(path, headers=b.headers())
            assert final.status_code == 200
            roster = set(
                connection.scalars(
                    text(
                        "SELECT student_id FROM core.homeroom_rosters WHERE homeroom_class_id=:id AND ended_at IS NULL"
                    ),
                    {"id": b.rooms[9]},
                )
            )
            current = set(
                connection.scalars(
                    text(
                        "SELECT student_id FROM core.class_memberships WHERE class_id=:id AND status='ACTIVE'"
                    ),
                    {"id": b.classes["9:AUTO"]},
                )
            )
            assert roster == current
