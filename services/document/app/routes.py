import base64
import json
import re
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.auth import AccessContext, get_access, require_service
from app.db import get_db
from app.documents import Documents, grant_dto, version_dto
from app.errors import DocumentError, conflict, denied, missing
from app.models import Bookmark, Document, Grant, Note, Outbox, UploadReceipt, Version
from app.personal import Personal
from app.schemas import (
    BookmarkState,
    Deletion,
    EditNote,
    Metadata,
    NewNote,
    Retry,
    Revision,
    Sharing,
)
from app.storage import capabilities, path_for

router = APIRouter(prefix="/api/v1")
internal = APIRouter(prefix="/internal/v1")
DB = Annotated[Session, Depends(get_db)]
Access = Annotated[AccessContext, Depends(get_access)]
Positive = Annotated[int, Query(gt=0)]


def data(value, next_cursor=None):
    return {"data": value, "meta": {"next_cursor": next_cursor}}


def filters(request: Request, allowed):
    if any(
        key not in allowed or len(request.query_params.getlist(key)) != 1
        for key in request.query_params
    ):
        raise DocumentError(422, "VALIDATION_ERROR", "Bộ lọc không hợp lệ.")


def upload_fields(allowed):
    async def validate(request: Request):
        form = await request.form()
        if any(key not in allowed or len(form.getlist(key)) != 1 for key in form):
            raise DocumentError(422, "VALIDATION_ERROR", "Invalid multipart fields")

    return validate


def page(session, model, query, cursor, limit):
    if cursor:
        try:
            payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            timestamp = datetime.fromisoformat(payload[0])
            if timestamp.tzinfo is None:
                raise ValueError()
            id_ = UUID(payload[1])
            query = query.where(tuple_(model.created_at, model.id) < tuple_(timestamp, id_))
        except (ValueError, TypeError, KeyError, IndexError):
            raise DocumentError(422, "INVALID_CURSOR", "Mốc phân trang không hợp lệ.")
    rows = list(
        session.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1))
    )
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = (
            base64.urlsafe_b64encode(
                json.dumps([last.created_at.isoformat(), str(last.id)]).encode()
            )
            .decode()
            .rstrip("=")
        )
    return rows[:limit], next_cursor


Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[str | None, Query(max_length=512)]


@router.get("/capabilities")
def get_capabilities(access: Access):
    result = capabilities()
    assigned = []
    if "LECTURER" in access.actor.roles:
        cursor, seen = None, set()
        while True:
            suffix = "?limit=100" + ("&cursor=" + cursor if cursor else "")
            page_ = access.gateway.request("/api/v1/classes" + suffix, bearer=access.bearer)
            if not isinstance(page_, dict) or not isinstance(page_.get("items"), list):
                raise DocumentError(503, "INVALID_CORE_RESPONSE", "Chưa đọc được danh sách lớp.")
            for row in page_["items"]:
                try:
                    class_id = UUID(row["id"])
                    current = access.class_access(class_id)
                    if current["allowed"] and current.get("teaching_role") in {
                        "PRIMARY",
                        "ASSISTING",
                    }:
                        assigned.append(
                            {
                                "id": str(class_id),
                                "name": str(row["name"]),
                                "status": current["class_status"],
                                "teaching_role": current["teaching_role"],
                            }
                        )
                except (KeyError, ValueError, TypeError):
                    raise DocumentError(503, "INVALID_CORE_RESPONSE", "Thông tin lớp chưa hợp lệ.")
            cursor = page_.get("next_cursor")
            if cursor is None:
                break
            if (
                not isinstance(cursor, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{22}", cursor)
                or cursor in seen
                or len(seen) >= 99
            ):
                raise DocumentError(503, "INVALID_CORE_RESPONSE", "Chưa đọc đủ danh sách lớp.")
            seen.add(cursor)
    result["assigned_classes"] = assigned
    return data(result)


@router.get("/documents")
def list_documents(
    request: Request,
    db: DB,
    access: Access,
    cursor: Cursor = None,
    limit: Limit = 20,
    search: str = Query(default="", max_length=200),
    format: str | None = None,
    status: str | None = None,
):
    filters(request, {"cursor", "limit", "search", "format", "status"})
    service = Documents(db, access)
    service.lecturer()
    query = select(Document).where(
        Document.owner_id == access.actor.id,
        Document.school_id == access.actor.school_id,
        Document.deleted.is_(False),
    )
    if search:
        query = query.where(Document.title.icontains(search, autoescape=True))
    if format:
        if format not in {"PDF", "PPTX", "DOCX", "TXT", "MD"}:
            raise DocumentError(422, "VALIDATION_ERROR", "Định dạng không hợp lệ.")
        query = query.where(Document.format == format)
    if status:
        if status not in {"PENDING", "PROCESSING", "READY", "FAILED"}:
            raise DocumentError(422, "VALIDATION_ERROR", "Trạng thái không hợp lệ.")
        latest = (
            select(Version.status)
            .where(Version.document_id == Document.id)
            .order_by(Version.number.desc())
            .limit(1)
            .scalar_subquery()
        )
        query = query.where(latest == status)
    rows, next_cursor = page(db, Document, query, cursor, limit)
    return data([service.summary(doc) for doc in rows], next_cursor)


@router.post(
    "/documents",
    status_code=201,
    dependencies=[Depends(upload_fields({"file", "title", "description"}))],
)
def upload_document(
    db: DB,
    access: Access,
    file: Annotated[UploadFile, File()],
    title: Annotated[str, Form(min_length=1, max_length=200)],
    request_id: Annotated[UUID, Header(alias="Idempotency-Key")],
    description: Annotated[str, Form(max_length=4000)] = "",
):
    return data(Documents(db, access).upload(file, request_id, title, description))


@router.get("/documents/{document_id}")
def get_document(document_id: UUID, db: DB, access: Access):
    service = Documents(db, access)
    return data(service.detail(service.owned(document_id)))


@router.patch("/documents/{document_id}")
def edit_document(document_id: UUID, body: Metadata, db: DB, access: Access):
    service = Documents(db, access)
    doc = service.owned(document_id, lock=True)
    if doc.revision != body.expected_revision:
        conflict()
    doc.title, doc.description, doc.revision = body.title, body.description, doc.revision + 1
    db.commit()
    return data(service.detail(doc))


@router.delete("/documents/{document_id}")
def delete_document(document_id: UUID, body: Deletion, db: DB, access: Access):
    service = Documents(db, access)
    return data(
        service.delete(
            service.owned(document_id, lock=True),
            body.expected_revision,
            body.confirmed_shared_class_count,
        )
    )


@router.get("/documents/{document_id}/versions")
def list_versions(
    document_id: UUID,
    request: Request,
    db: DB,
    access: Access,
    cursor: int | None = Query(default=None, gt=0),
    limit: Limit = 20,
):
    filters(request, {"cursor", "limit"})
    service = Documents(db, access)
    doc = service.owned(document_id)
    query = select(Version).where(Version.document_id == doc.id)
    if cursor:
        query = query.where(Version.number < cursor)
    rows = list(db.scalars(query.order_by(Version.number.desc()).limit(limit + 1)))
    return data(
        [version_dto(v, doc) for v in rows[:limit]],
        str(rows[limit - 1].number) if len(rows) > limit else None,
    )


@router.post(
    "/documents/{document_id}/versions",
    status_code=201,
    dependencies=[Depends(upload_fields({"file"}))],
)
def upload_version(
    document_id: UUID,
    db: DB,
    access: Access,
    file: Annotated[UploadFile, File()],
    request_id: Annotated[UUID, Header(alias="Idempotency-Key")],
):
    return data(Documents(db, access).upload(file, request_id, document_id=document_id))


@router.post("/documents/{document_id}/versions/{version}/retry", status_code=202)
def retry_version(document_id: UUID, version: int, body: Retry, db: DB, access: Access):
    service = Documents(db, access)
    return data(
        service.retry(service.owned(document_id, lock=True), version, body.expected_generation)
    )


def source_file(version: Version):
    target = path_for(version.storage_key)
    if not target.is_file():
        raise DocumentError(503, "STORAGE_UNAVAILABLE", "Chưa đọc được tệp gốc.")
    return FileResponse(
        target,
        media_type="application/octet-stream",
        filename=version.filename,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/documents/{document_id}/versions/{version}/content")
def owner_content(
    document_id: UUID,
    version: int,
    request: Request,
    db: DB,
    access: Access,
    cursor: int = Query(default=0, ge=0, le=5000),
    limit: Limit = 20,
):
    filters(request, {"cursor", "limit"})
    service = Documents(db, access)
    doc = service.owned(document_id)
    return data(service.content(doc, service.version(doc, version, ready=True), cursor, limit))


@router.get("/documents/{document_id}/versions/{version}/file")
def owner_file(document_id: UUID, version: int, db: DB, access: Access):
    service = Documents(db, access)
    return source_file(service.version(service.owned(document_id), version, ready=True))


@router.get("/documents/{document_id}/grants")
def list_grants(
    document_id: UUID,
    request: Request,
    db: DB,
    access: Access,
    cursor: Cursor = None,
    limit: Limit = 20,
):
    filters(request, {"cursor", "limit"})
    Documents(db, access).owned(document_id)
    rows, next_cursor = page(
        db, Grant, select(Grant).where(Grant.document_id == document_id), cursor, limit
    )
    return data([grant_dto(row) for row in rows], next_cursor)


@router.post("/documents/{document_id}/grants")
def share_batch(document_id: UUID, body: Sharing, db: DB, access: Access):
    service = Documents(db, access)
    doc = service.owned(document_id, lock=True)
    if doc.revision != body.expected_revision:
        conflict()
    if len(set(body.class_ids)) != len(body.class_ids):
        raise DocumentError(422, "VALIDATION_ERROR", "Danh sách lớp bị trùng.")
    for class_id in body.class_ids:
        service.teaching(class_id)
    grants = [
        service.set_grant(doc, class_id, True, 0, check_revision=False)
        for class_id in sorted(body.class_ids)
    ]
    db.commit()
    return data([grant_dto(row) for row in grants])


@router.get("/classes/{class_id}/documents")
def list_class_documents(
    class_id: UUID,
    request: Request,
    db: DB,
    access: Access,
    cursor: Cursor = None,
    limit: Limit = 20,
    search: str = Query(default="", max_length=200),
    format: str | None = None,
):
    filters(request, {"cursor", "limit", "search", "format"})
    current = access.class_access(class_id)
    if not current["allowed"]:
        denied()
    query = (
        select(Grant)
        .join(Document, Grant.document_id == Document.id)
        .where(
            Grant.class_id == class_id,
            Grant.active.is_(True),
            Document.deleted.is_(False),
            Document.school_id == access.actor.school_id,
            Grant.school_id == access.actor.school_id,
        )
    )
    if search:
        query = query.where(Document.title.icontains(search, autoescape=True))
    if format:
        if format not in {"PDF", "PPTX", "DOCX", "TXT", "MD"}:
            raise DocumentError(422, "VALIDATION_ERROR", "Định dạng không hợp lệ.")
        query = query.where(Document.format == format)
    rows, next_cursor = page(db, Grant, query, cursor, limit)
    service = Documents(db, access)
    return data(
        [service.class_dto(db.get(Document, row.document_id), row, current) for row in rows],
        next_cursor,
    )


@router.get("/classes/{class_id}/documents/{document_id}")
def get_class_document(class_id: UUID, document_id: UUID, db: DB, access: Access):
    service = Documents(db, access)
    return data(service.class_dto(*service.class_source(class_id, document_id)))


@router.put("/classes/{class_id}/documents/{document_id}/grant")
def add_grant(class_id: UUID, document_id: UUID, body: Revision, db: DB, access: Access):
    service = Documents(db, access)
    grant = service.set_grant(
        service.owned(document_id, lock=True), class_id, True, body.expected_revision
    )
    db.commit()
    return data(grant_dto(grant))


@router.delete("/classes/{class_id}/documents/{document_id}/grant")
def remove_grant(class_id: UUID, document_id: UUID, body: Revision, db: DB, access: Access):
    service = Documents(db, access)
    service.teaching(class_id)
    doc = db.scalar(
        select(Document)
        .where(
            Document.id == document_id,
            Document.school_id == access.actor.school_id,
            Document.deleted.is_(False),
        )
        .with_for_update()
    )
    if doc is None:
        denied()
    grant = service.set_grant(doc, class_id, False, body.expected_revision)
    db.commit()
    return data(grant_dto(grant))


@router.get("/classes/{class_id}/documents/{document_id}/versions/{version}/content")
def class_content(
    class_id: UUID,
    document_id: UUID,
    version: int,
    request: Request,
    db: DB,
    access: Access,
    cursor: int = Query(default=0, ge=0, le=5000),
    limit: Limit = 20,
):
    filters(request, {"cursor", "limit"})
    service = Documents(db, access)
    doc, _, _ = service.class_source(class_id, document_id)
    return data(service.content(doc, service.version(doc, version, ready=True), cursor, limit))


@router.get("/classes/{class_id}/documents/{document_id}/versions/{version}/file")
def class_file(class_id: UUID, document_id: UUID, version: int, db: DB, access: Access):
    service = Documents(db, access)
    doc, _, _ = service.class_source(class_id, document_id)
    return source_file(service.version(doc, version, ready=True))


def personal_list(model, request, db, access, cursor, limit, class_id, document_id):
    filters(request, {"cursor", "limit", "class_id", "document_id"})
    query = (
        select(model)
        .join(Document, Document.id == model.document_id)
        .where(
            model.user_id == access.actor.id,
            Document.school_id == access.actor.school_id,
        )
    )
    if class_id:
        query = query.where(model.class_id == class_id)
    if document_id:
        query = query.where(model.document_id == document_id)
    rows, next_cursor = page(db, model, query, cursor, limit)
    service = Personal(db, access)
    return data([service.dto(row) for row in rows], next_cursor)


@router.get("/notes")
def list_notes(
    request: Request,
    db: DB,
    access: Access,
    cursor: Cursor = None,
    limit: Limit = 20,
    class_id: UUID | None = None,
    document_id: UUID | None = None,
):
    return personal_list(Note, request, db, access, cursor, limit, class_id, document_id)


@router.post("/classes/{class_id}/documents/{document_id}/notes", status_code=201)
def create_note(class_id: UUID, document_id: UUID, body: NewNote, db: DB, access: Access):
    return data(Personal(db, access).create_note(class_id, document_id, body))


@router.patch("/notes/{note_id}")
def edit_note(note_id: UUID, body: EditNote, db: DB, access: Access):
    return data(Personal(db, access).edit_note(note_id, body))


@router.delete("/notes/{note_id}")
def delete_note(note_id: UUID, body: Revision, db: DB, access: Access):
    service = Personal(db, access)
    note = service.own(Note, note_id, lock=True)
    if note.revision != body.expected_revision:
        conflict()
    revision = note.revision
    db.delete(note)
    db.commit()
    return data({"id": note_id, "revision": revision, "deleted": True})


@router.get("/bookmarks")
def list_bookmarks(
    request: Request,
    db: DB,
    access: Access,
    cursor: Cursor = None,
    limit: Limit = 20,
    class_id: UUID | None = None,
    document_id: UUID | None = None,
):
    return personal_list(Bookmark, request, db, access, cursor, limit, class_id, document_id)


@router.put("/classes/{class_id}/documents/{document_id}/bookmarks/{version}/{locator_id}")
def put_bookmark(
    class_id: UUID,
    document_id: UUID,
    version: int,
    locator_id: str,
    body: BookmarkState,
    db: DB,
    access: Access,
):
    if (
        version <= 0
        or not locator_id.isascii()
        or not locator_id.isdigit()
        or not 0 < int(locator_id) <= 5000
    ):
        raise DocumentError(422, "INVALID_LOCATOR", "Vị trí không hợp lệ.")
    return data(
        Personal(db, access).bookmark(class_id, document_id, version, locator_id, body.bookmarked)
    )


@router.delete("/bookmarks/{bookmark_id}")
def delete_bookmark(bookmark_id: UUID, db: DB, access: Access):
    item = db.scalar(
        select(Bookmark)
        .where(Bookmark.id == bookmark_id, Bookmark.user_id == access.actor.id)
        .with_for_update()
    )
    if item is not None:
        db.delete(item)
    db.commit()
    return data({"id": bookmark_id, "revision": None, "deleted": True})


@router.get("/uploads/{request_id}")
def get_receipt(request_id: UUID, db: DB, access: Access):
    row = db.scalar(
        select(UploadReceipt).where(
            UploadReceipt.request_id == request_id,
            UploadReceipt.user_id == access.actor.id,
        )
    )
    if row is None:
        missing()
    service = Documents(db, access)
    service.lecturer()
    doc = db.get(Document, row.document_id)
    if doc is None or doc.owner_id != access.actor.id or doc.school_id != access.actor.school_id:
        missing()
    return data(service.receipt(row))


@internal.get("/classes/{class_id}/documents/active-grants")
def active_grants(
    class_id: UUID,
    request: Request,
    db: DB,
    access: Access,
    cursor: Cursor = None,
    limit: Limit = 20,
    purpose: str = "tutor",
):
    require_service(request)
    filters(request, {"cursor", "limit", "purpose"})
    if purpose != "tutor" or not access.class_access(class_id, "use_ai_tutor")["allowed"]:
        denied()
    if not access.class_access(class_id)["allowed"]:
        denied()
    query = (
        select(Grant)
        .join(Document, Grant.document_id == Document.id)
        .where(
            Grant.class_id == class_id,
            Grant.active.is_(True),
            Document.deleted.is_(False),
            Grant.school_id == access.actor.school_id,
            Document.school_id == access.actor.school_id,
            Document.serving_version.is_not(None),
        )
    )
    rows, next_cursor = page(db, Grant, query, cursor, limit)
    return data(
        [
            {
                "document_id": row.document_id,
                "serving_version": db.get(Document, row.document_id).serving_version,
                "grant_id": row.id,
                "grant_revision": row.revision,
            }
            for row in rows
        ],
        next_cursor,
    )


@internal.get("/classes/{class_id}/documents/{document_id}/versions/{version}/content")
def internal_content(
    class_id: UUID,
    document_id: UUID,
    version: int,
    request: Request,
    db: DB,
    access: Access,
    expected_grant_revision: Positive,
    cursor: int = Query(default=0, ge=0, le=5000),
    limit: Limit = 20,
):
    require_service(request)
    filters(request, {"cursor", "limit", "expected_grant_revision"})
    if not access.class_access(class_id, "use_ai_tutor")["allowed"]:
        denied()
    service = Documents(db, access)
    doc, grant, _ = service.class_source(class_id, document_id)
    if grant.revision != expected_grant_revision or doc.serving_version != version:
        conflict("Quyền nguồn đã thay đổi; cần kiểm tra lại retrieval.")
    return data(service.content(doc, service.version(doc, version, ready=True), cursor, limit))


@internal.get("/events")
def event_journal(
    request: Request, db: DB, cursor: int = Query(default=0, ge=0), limit: Limit = 20
):
    require_service(request, event_reader=True)
    filters(request, {"cursor", "limit"})
    rows = list(
        db.scalars(
            select(Outbox)
            .where(Outbox.sequence > cursor)
            .order_by(Outbox.sequence)
            .limit(limit + 1)
        )
    )
    return data(
        [{**row.envelope, "cursor": str(row.sequence)} for row in rows[:limit]],
        str(rows[limit - 1].sequence) if len(rows) > limit else None,
    )
