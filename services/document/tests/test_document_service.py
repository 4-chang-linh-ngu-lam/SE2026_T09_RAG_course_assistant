import asyncio
import io
import subprocess
import sys
from datetime import timedelta
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from conftest import (
    ADMIN,
    ASSISTANT,
    CLASS,
    OTHER_CLASS,
    OTHER_STUDENT,
    OUTSIDER,
    STUDENT,
    TEACHER,
    auth,
    office_bytes,
    pdf_bytes,
)
from pydantic import SecretStr
from sqlalchemy import func, select, text

from app.config import settings
from app.db import SessionLocal
from app.main import app
from app.models import Outbox, Version
from app.processing import ProcessingError, extract
from app.worker import claim, deliver, process, publish


def upload(client, content=b"Hello source", filename="source.txt", request_id=None, doc=None):
    path = f"/api/v1/documents/{doc}/versions" if doc else "/api/v1/documents"
    return client.post(
        path,
        headers={**auth(), "Idempotency-Key": str(request_id or uuid4())},
        files={"file": (filename, content)},
        data={} if doc else {"title": "Synthetic source"},
    )


def ready(client):
    result = upload(client)
    assert result.status_code == 201
    doc = result.json()["data"]["document_id"]
    job = claim()
    assert job
    assert publish(job, process(job))
    return doc


def grant(client, doc):
    result = client.put(
        f"/api/v1/classes/{CLASS}/documents/{doc}/grant",
        headers=auth(),
        json={"expected_revision": 0},
    )
    assert result.status_code == 200
    return result.json()["data"]


@pytest.mark.parametrize("format_", ["PDF", "PPTX", "DOCX", "TXT", "MD"])
def test_actual_file_bytes_extraction_download_and_receipt(client, format_):
    content = (
        pdf_bytes()
        if format_ == "PDF"
        else office_bytes(format_)
        if format_ in {"DOCX", "PPTX"}
        else b"Hello source\n\nSecond section"
    )
    result = upload(client, content, "source." + format_.lower())
    assert result.status_code == 201
    receipt = result.json()["data"]
    assert receipt["status"] == "PENDING"
    job = claim()
    assert publish(job, process(job))
    doc = receipt["document_id"]
    page = client.get(f"/api/v1/documents/{doc}/versions/1/content", headers=auth()).json()["data"]
    assert "Hello source" in page["locators"][0]["text"]
    assert page["locator_kind"] == (
        "PAGE" if format_ == "PDF" else "SLIDE" if format_ == "PPTX" else "SECTION"
    )
    downloaded = client.get(f"/api/v1/documents/{doc}/versions/1/file", headers=auth())
    assert downloaded.content == content
    assert downloaded.headers["cache-control"] == "no-store"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert (
        client.get(f"/api/v1/uploads/{receipt['request_id']}", headers=auth()).json()["data"][
            "status"
        ]
        == "READY"
    )


def test_failed_new_version_preserves_old_and_retry_original(client):
    doc = ready(client)
    grant(client, doc)
    result = upload(client, b"\xff\x00invalid", "bad.txt", doc=doc)
    assert result.status_code == 201
    job = claim()
    assert publish(job, process(job))
    detail = client.get(f"/api/v1/documents/{doc}", headers=auth()).json()["data"]
    assert detail["latest_status"] == "FAILED" and detail["serving_version"] == 1
    assert (
        client.get(
            f"/api/v1/classes/{CLASS}/documents/{doc}/versions/1/content", headers=auth(STUDENT)
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/classes/{CLASS}/documents/{doc}/versions/2/content", headers=auth(STUDENT)
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/documents/{doc}/versions/2/retry",
            headers=auth(),
            json={"expected_generation": detail["versions"][0]["generation"]},
        ).status_code
        == 202
    )
    next_job = claim()
    assert next_job["storage_key"] == job["storage_key"]
    assert publish(next_job, process(next_job))


def test_internal_ai_reads_only_current_serving_version(client, monkeypatch):
    doc = ready(client)
    grant(client, doc)
    assert upload(client, b"New serving source", doc=doc).status_code == 201
    job = claim()
    assert publish(job, process(job))
    key = "source-" + "a" * 32
    monkeypatch.setattr(settings, "document_internal_service_secret", SecretStr(key))
    base = f"/internal/v1/classes/{CLASS}/documents/{doc}/versions"
    current = client.get(
        f"/internal/v1/classes/{CLASS}/documents/active-grants",
        headers={**auth(STUDENT), "X-Service-Key": key},
    ).json()["data"][0]
    revision = current["grant_revision"]
    for version, expected in ((1, 409), (2, 200)):
        assert (
            client.get(
                f"{base}/{version}/content?expected_grant_revision={revision}",
                headers={**auth(STUDENT), "X-Service-Key": key},
            ).status_code
            == expected
        )
    assert (
        client.get(
            f"/api/v1/classes/{CLASS}/documents/{doc}/versions/1/content",
            headers=auth(STUDENT),
        ).status_code
        == 200
    )  # Human historical citations remain version-bound.


def test_crash_reclaim_rejects_stale_worker_and_retains_blob(client):
    assert upload(client).status_code == 201
    killed = subprocess.run(
        [sys.executable, "-c", "from app.worker import claim; import os; claim(); os._exit(137)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    assert killed.returncode == 137
    with SessionLocal() as session:
        row = session.scalar(select(Version))
        old = {"id": row.id, "document_id": row.document_id, "generation": row.generation}
        row.lease_until = session.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
        session.commit()
    replacement = claim()
    assert replacement["generation"] > old["generation"]
    assert publish(old, {"content": [{"id": "1", "text": "stale"}]}) is False
    assert publish(replacement, process(replacement))


def test_out_of_order_success_never_regresses_serving_version(client):
    doc = ready(client)
    assert upload(client, b"v2", doc=doc).status_code == 201
    job2 = claim()
    assert upload(client, b"v3", doc=doc).status_code == 201
    job3 = claim()
    assert publish(job3, process(job3))
    assert publish(job2, process(job2))
    assert (
        client.get(f"/api/v1/documents/{doc}", headers=auth()).json()["data"]["serving_version"]
        == 3
    )


def test_upload_idempotency_actor_scope_and_payload_conflict(client):
    key = uuid4()
    first = upload(client, request_id=key)
    replay = upload(client, request_id=key)
    assert first.status_code == replay.status_code == 201
    assert first.json()["data"]["document_id"] == replay.json()["data"]["document_id"]
    assert upload(client, b"different", request_id=key).status_code == 409
    assert client.get(f"/api/v1/uploads/{key}", headers=auth(ASSISTANT)).status_code == 404
    assert len(client.get("/api/v1/documents", headers=auth()).json()["data"]) == 1


def test_cross_scope_admin_and_assisting_source_permissions(client):
    doc = ready(client)
    grant(client, doc)
    for user in (ADMIN, STUDENT, ASSISTANT, OUTSIDER):
        assert client.get(f"/api/v1/documents/{doc}", headers=auth(user)).status_code in {403, 404}
    for class_id, user in ((OTHER_CLASS, STUDENT), (CLASS, OUTSIDER), (CLASS, ADMIN)):
        assert (
            client.get(
                f"/api/v1/classes/{class_id}/documents/{doc}/versions/1/file", headers=auth(user)
            ).status_code
            == 403
        )
    assert (
        client.post(
            f"/api/v1/documents/{doc}/versions",
            headers={**auth(ASSISTANT), "Idempotency-Key": str(uuid4())},
            files={"file": ("x.txt", b"x")},
        ).status_code
        == 404
    )
    assert (
        client.request(
            "DELETE",
            f"/api/v1/classes/{CLASS}/documents/{doc}/grant",
            headers=auth(ASSISTANT),
            json={"expected_revision": 1},
        ).status_code
        == 200
    )


def test_revoke_redacts_quote_keeps_handwritten_and_owner_only(client):
    doc = ready(client)
    grant(client, doc)
    path = f"/api/v1/classes/{CLASS}/documents/{doc}"
    request = {
        "version": 1,
        "locator_id": "1",
        "note_text": "My own handwriting",
        "source_quote": "Hello source",
        "client_request_id": str(uuid4()),
    }
    result = client.post(path + "/notes", headers=auth(STUDENT), json=request)
    assert result.status_code == 201
    note_id = result.json()["data"]["id"]
    assert (
        client.post(path + "/notes", headers=auth(STUDENT), json=request).json()["data"]["id"]
        == note_id
    )
    assert client.get("/api/v1/notes", headers=auth(OTHER_STUDENT)).json()["data"] == []
    assert (
        client.patch(
            f"/api/v1/notes/{note_id}",
            headers=auth(OTHER_STUDENT),
            json={"note_text": "stolen", "expected_revision": 1},
        ).status_code
        == 404
    )
    assert (
        client.put(
            path + "/bookmarks/1/1", headers=auth(STUDENT), json={"bookmarked": True}
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE", path + "/grant", headers=auth(), json={"expected_revision": 1}
        ).status_code
        == 200
    )
    assert client.get(path + "/versions/1/content", headers=auth(STUDENT)).status_code == 403
    assert client.get(path + "/versions/1/file", headers=auth(STUDENT)).status_code == 403
    detail = client.get(f"/api/v1/documents/{doc}", headers=auth()).json()["data"]
    assert (
        client.patch(
            f"/api/v1/documents/{doc}",
            headers=auth(),
            json={
                "title": "New private title after revoke",
                "description": "private",
                "expected_revision": detail["revision"],
            },
        ).status_code
        == 200
    )
    note = client.get("/api/v1/notes", headers=auth(STUDENT)).json()["data"][0]
    bookmark = client.get("/api/v1/bookmarks", headers=auth(STUDENT)).json()["data"][0]
    for history in (note, bookmark):
        assert history["document_title"] == "Synthetic source"
        assert history["class_name"] == "Synthetic class"
    assert (
        note["source_quote"] is None
        and note["note_text"] == request["note_text"]
        and note["source_access"] == "REVOKED"
    )
    assert (
        client.patch(
            f"/api/v1/notes/{note_id}",
            headers=auth(STUDENT),
            json={"note_text": "new", "expected_revision": 1},
        ).status_code
        == 403
    )
    assert (
        client.request(
            "DELETE",
            f"/api/v1/notes/{note_id}",
            headers=auth(STUDENT),
            json={"expected_revision": 1},
        ).status_code
        == 200
    )
    assert (
        client.put(
            path + "/bookmarks/1/1", headers=auth(STUDENT), json={"bookmarked": False}
        ).json()["data"]["bookmarked"]
        is False
    )


def test_archived_o2_allows_personal_edits_blocks_grant_changes(client):
    doc = ready(client)
    grant(client, doc)
    app.state.core.archived = True
    path = f"/api/v1/classes/{CLASS}/documents/{doc}"
    result = client.post(
        path + "/notes",
        headers=auth(STUDENT),
        json={
            "version": 1,
            "locator_id": "1",
            "note_text": "archived",
            "client_request_id": str(uuid4()),
        },
    )
    assert result.status_code == 201
    note = result.json()["data"]
    assert (
        client.patch(
            f"/api/v1/notes/{note['id']}",
            headers=auth(STUDENT),
            json={"note_text": "edited", "expected_revision": 1},
        ).status_code
        == 200
    )
    assert (
        client.put(
            path + "/bookmarks/1/1", headers=auth(STUDENT), json={"bookmarked": True}
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE", path + "/grant", headers=auth(), json={"expected_revision": 1}
        ).status_code
        == 403
    )


def test_transfer_ended_assignment_and_core_outage_fail_closed(client):
    doc = ready(client)
    grant(client, doc)
    path = f"/api/v1/classes/{CLASS}/documents/{doc}/versions/1/content"
    app.state.core.member = False
    assert client.get(path, headers=auth(STUDENT)).status_code == 403
    app.state.core.teacher_assigned = False
    assert client.get(path, headers=auth(TEACHER)).status_code == 403
    app.state.core.available = False
    assert client.get(path, headers=auth(STUDENT)).status_code == 503
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 503


def test_delete_confirmation_revision_and_active_processing(client):
    doc = ready(client)
    before = client.get(f"/api/v1/documents/{doc}", headers=auth()).json()["data"]
    grant(client, doc)
    assert (
        client.request(
            "DELETE",
            f"/api/v1/documents/{doc}",
            headers=auth(),
            json={"expected_revision": before["revision"], "confirmed_shared_class_count": 0},
        ).status_code
        == 409
    )
    assert upload(client, b"pending version", doc=doc).status_code == 201
    job = claim()
    latest = client.get(f"/api/v1/documents/{doc}", headers=auth()).json()["data"]
    assert (
        client.request(
            "DELETE",
            f"/api/v1/documents/{doc}",
            headers=auth(),
            json={"expected_revision": latest["revision"], "confirmed_shared_class_count": 1},
        ).status_code
        == 200
    )
    assert publish(job, process(job)) is False
    assert (
        client.get(f"/api/v1/classes/{CLASS}/documents/{doc}", headers=auth(STUDENT)).status_code
        == 403
    )


def test_batch_share_atomic_and_metadata_revision(client):
    doc = ready(client)
    detail = client.get(f"/api/v1/documents/{doc}", headers=auth()).json()["data"]
    assert (
        client.post(
            f"/api/v1/documents/{doc}/grants",
            headers=auth(),
            json={"class_ids": [CLASS, OTHER_CLASS], "expected_revision": detail["revision"]},
        ).status_code
        == 403
    )
    assert client.get(f"/api/v1/documents/{doc}/grants", headers=auth()).json()["data"] == []
    assert (
        client.patch(
            f"/api/v1/documents/{doc}",
            headers=auth(),
            json={
                "title": "updated",
                "description": "test",
                "expected_revision": detail["revision"],
            },
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/documents/{doc}",
            headers=auth(),
            json={"title": "stale", "expected_revision": detail["revision"]},
        ).status_code
        == 409
    )


def test_quote_and_locator_validation_and_explicit_bookmark_state(client):
    doc = ready(client)
    grant(client, doc)
    path = f"/api/v1/classes/{CLASS}/documents/{doc}"
    for quote, locator in (("not in source", "1"), ("Hello source", "999")):
        assert (
            client.post(
                path + "/notes",
                headers=auth(STUDENT),
                json={
                    "version": 1,
                    "locator_id": locator,
                    "note_text": "note",
                    "source_quote": quote,
                    "client_request_id": str(uuid4()),
                },
            ).status_code
            == 422
        )
    first = client.put(
        path + "/bookmarks/1/1", headers=auth(STUDENT), json={"bookmarked": True}
    ).json()["data"]
    second = client.put(
        path + "/bookmarks/1/1", headers=auth(STUDENT), json={"bookmarked": True}
    ).json()["data"]
    assert first["bookmark"]["id"] == second["bookmark"]["id"]


def test_internal_scopes_revision_and_event_delivery(client, monkeypatch):
    doc = ready(client)
    grant(client, doc)
    base = f"/internal/v1/classes/{CLASS}/documents"
    assert client.get(base + "/active-grants", headers=auth(STUDENT)).status_code == 403
    monkeypatch.setattr(
        settings, "document_internal_service_secret", SecretStr("source-" + "a" * 32)
    )
    monkeypatch.setattr(settings, "document_event_reader_secret", SecretStr("events-" + "b" * 32))
    headers = {**auth(STUDENT), "X-Service-Key": "source-" + "a" * 32}
    assert (
        client.get(base + "/active-grants", headers=headers).json()["data"][0]["document_id"] == doc
    )
    assert (
        client.get(
            base + f"/{doc}/versions/1/content?expected_grant_revision=2", headers=headers
        ).status_code
        == 409
    )
    assert (
        client.get(
            base + f"/{doc}/versions/1/content?expected_grant_revision=1", headers=headers
        ).status_code
        == 200
    )
    assert client.get("/internal/v1/events", headers=headers).status_code == 403
    journal = client.get(
        "/internal/v1/events", headers={"X-Service-Key": "events-" + "b" * 32}
    ).json()["data"]
    assert len(journal) == 2 and all("Hello source" not in str(event) for event in journal)
    assert deliver(app.state.core)
    assert deliver(app.state.core) is False
    with SessionLocal() as session:
        assert (
            session.scalar(select(Outbox).where(Outbox.notification_payload.is_(True))).delivered_at
            is not None
        )


def test_file_validation_limits_bad_zip_and_entities(client, tmp_path, monkeypatch):
    for filename, content in (("../x.txt", b"a"), ("x.exe", b"MZ"), ("empty.txt", b"")):
        assert upload(client, content, filename).status_code == 422
    assert (
        client.post(
            "/api/v1/documents",
            headers={**auth(), "Idempotency-Key": str(uuid4())},
            files={"file": ("source.txt", b"real bytes")},
            data={"title": "source", "owner_id": OTHER_STUDENT},
        ).status_code
        == 422
    )
    monkeypatch.setattr(settings, "max_file_size_bytes", 3)
    assert upload(client, b"1234").status_code == 413
    with pytest.raises(ProcessingError):
        path = tmp_path / "not-a-pdf"
        path.write_bytes(b"fake")
        extract(path, "PDF")
    for name, xml in (
        ("../escape", "x"),
        (
            "word/document.xml",
            '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><doc>&xxe;</doc>',
        ),
    ):
        output = io.BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr(name, xml)
        path = tmp_path / "unsafe.docx"
        path.write_bytes(output.getvalue())
        with pytest.raises(ProcessingError):
            extract(path, "DOCX")


def test_pagination_auth_errors_and_no_arbitrary_filters(client):
    assert client.get("/api/v1/capabilities").status_code == 401
    for _ in range(3):
        assert upload(client).status_code == 201
    first = client.get("/api/v1/documents?limit=2", headers=auth()).json()
    assert len(first["data"]) == 2 and first["meta"]["next_cursor"]
    second = client.get(
        "/api/v1/documents",
        headers=auth(),
        params={"cursor": first["meta"]["next_cursor"], "limit": 2},
    ).json()
    assert len(second["data"]) == 1
    assert client.get("/api/v1/documents?cursor=bad", headers=auth()).status_code == 422
    assert client.get("/api/v1/documents?user_id=someone", headers=auth()).status_code == 422
    assert client.get("/api/v1/documents?limit=101", headers=auth()).status_code == 422


def test_runtime_schema_isolation():
    with SessionLocal() as session:
        role = session.execute(
            text(
                "SELECT rolsuper, rolcreatedb, rolcreaterole, rolbypassrls FROM pg_roles WHERE rolname=current_user"
            )
        ).one()
        assert not any(role)
        assert session.scalar(
            text("SELECT has_schema_privilege(current_user, 'document', 'USAGE')")
        )


def test_unauthenticated_upload_does_not_consume_body():
    messages = []

    async def receive():
        raise AssertionError("Unauthenticated body was consumed")

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/documents",
        "raw_path": b"/api/v1/documents",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"content-type", b"multipart/form-data; boundary=test")],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    assert messages[0]["status"] == 401


def test_upload_receipt_survives_logical_source_deletion(client):
    result = upload(client)
    receipt = result.json()["data"]
    doc = client.get(f"/api/v1/documents/{receipt['document_id']}", headers=auth()).json()["data"]
    assert (
        client.request(
            "DELETE",
            f"/api/v1/documents/{doc['id']}",
            headers=auth(),
            json={"expected_revision": doc["revision"], "confirmed_shared_class_count": 0},
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/uploads/{receipt['request_id']}", headers=auth()).status_code == 200
