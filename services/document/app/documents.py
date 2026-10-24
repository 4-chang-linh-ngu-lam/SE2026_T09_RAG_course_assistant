import hashlib
import json
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import AccessContext
from app.errors import DocumentError, conflict, denied, missing
from app.events import append_event, grant_event
from app.models import Document, Grant, UploadReceipt, Version
from app.storage import filename_format, path_for, save_file

ERROR_MESSAGES = {
    "INVALID_FORMAT": "Tệp không đúng cấu trúc hoặc mã hóa hỗ trợ.",
    "NO_EXTRACTABLE_TEXT": "Không tìm thấy văn bản. PDF ảnh quét cần OCR bên ngoài trước khi tải lên.",
    "ENCRYPTED_PDF": "PDF được mã hóa. Hãy tải bản không có mật khẩu.",
    "CONTENT_LIMIT": "Nội dung vượt giới hạn xử lý.",
    "EXPANSION_LIMIT": "Tệp nén chứa quá nhiều dữ liệu.",
    "INVALID_ARCHIVE": "Cấu trúc tệp nén không hợp lệ.",
    "RESOURCE_LIMIT": "Xử lý vượt giới hạn bộ nhớ hoặc thời gian. Hãy thử tệp nhỏ hơn.",
    "STORAGE_UNAVAILABLE": "Chưa đọc được tệp gốc. Vui lòng kiểm tra lưu trữ rồi thử lại.",
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def advisory(session: Session, value: str):
    key = int.from_bytes(hashlib.sha256(value.encode()).digest()[:8], "big", signed=True)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def version_dto(version: Version, doc: Document) -> dict:
    return {
        "version_number": version.number,
        "filename": version.filename,
        "file_size_bytes": version.size,
        "uploaded_at": version.created_at,
        "status": version.status,
        "error_code": version.error_code,
        "error_message": ERROR_MESSAGES.get(version.error_code, "Không thể xử lý tệp.")
        if version.error_code
        else None,
        "is_serving": doc.serving_version == version.number,
        "locator_count": len(version.content) if version.content is not None else None,
        "locator_kind": locator_kind(version.format) if version.content is not None else None,
        "generation": version.generation,
    }


def locator_kind(format_: str) -> str:
    return "PAGE" if format_ == "PDF" else "SLIDE" if format_ == "PPTX" else "SECTION"


def grant_dto(grant: Grant) -> dict:
    return {
        "id": grant.id,
        "document_id": grant.document_id,
        "class_id": grant.class_id,
        "school_id": grant.school_id,
        "is_active": grant.active,
        "revision": grant.revision,
        "granted_by": grant.granted_by,
        "granted_at": grant.created_at,
        "updated_at": grant.updated_at,
    }


class Documents:
    def __init__(self, session: Session, access: AccessContext):
        self.session, self.access, self.actor = session, access, access.actor

    def lecturer(self):
        if "LECTURER" not in self.actor.roles:
            denied()

    def owned(self, document_id: UUID, *, lock=False) -> Document:
        self.lecturer()
        query = (
            select(Document)
            .where(
                Document.id == document_id,
                Document.owner_id == self.actor.id,
                Document.school_id == self.actor.school_id,
                Document.deleted.is_(False),
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        doc = self.session.scalar(query)
        if doc is None:
            missing()
        return doc

    def version(self, doc: Document, number: int, *, ready=False, lock=False) -> Version:
        query = (
            select(Version)
            .where(Version.document_id == doc.id, Version.number == number)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        version = self.session.scalar(query)
        if version is None:
            missing()
        if ready and (version.status != "READY" or version.content is None):
            conflict("Phiên bản chưa xử lý thành công.")
        return version

    def summary(self, doc: Document) -> dict:
        latest = self.session.scalar(
            select(Version)
            .where(Version.document_id == doc.id)
            .order_by(Version.number.desc())
            .limit(1)
        )
        return {
            "id": doc.id,
            "title": doc.title,
            "description": doc.description,
            "format": doc.format,
            "owner_id": doc.owner_id,
            "owner_name": doc.owner_name,
            "latest_version": latest.number,
            "latest_status": latest.status,
            "processing_error": ERROR_MESSAGES.get(latest.error_code)
            if latest.error_code
            else None,
            "serving_version": doc.serving_version,
            "shared_class_count": self.session.scalar(
                select(func.count())
                .select_from(Grant)
                .where(Grant.document_id == doc.id, Grant.active.is_(True))
            ),
            "revision": doc.revision,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "can_manage_source": doc.owner_id == self.actor.id,
        }

    def detail(self, doc: Document) -> dict:
        versions = list(
            self.session.scalars(
                select(Version)
                .where(Version.document_id == doc.id)
                .order_by(Version.number.desc())
                .limit(21)
            )
        )
        return {
            **self.summary(doc),
            "grant_revision": doc.revision,
            "versions": [version_dto(v, doc) for v in versions[:20]],
            "versions_next_cursor": str(versions[19].number) if len(versions) > 20 else None,
        }

    def upload(
        self,
        file,
        request_id: UUID,
        title: str | None = None,
        description="",
        document_id: UUID | None = None,
    ) -> dict:
        self.lecturer()
        filename, format_ = filename_format(file.filename)
        if document_id is None and (not title or not title.strip() or len(title.strip()) > 200):
            raise DocumentError(422, "VALIDATION_ERROR", "Tiêu đề phải có từ 1 đến 200 ký tự.")
        if len(description) > 4000:
            raise DocumentError(422, "VALIDATION_ERROR", "Mô tả tối đa 4.000 ký tự.")
        doc = self.owned(document_id, lock=True) if document_id else None
        if doc is not None and format_ != doc.format:
            raise DocumentError(422, "FORMAT_MISMATCH", "Phiên bản mới cần cùng định dạng nguồn.")
        key, size, digest = save_file(file.file)
        operation = f"version:{document_id}" if document_id else "document"
        payload_hash = fingerprint([operation, filename, size, digest, title, description])
        advisory(self.session, f"upload:{self.actor.id}:{request_id}")
        previous = self.session.scalar(
            select(UploadReceipt).where(
                UploadReceipt.user_id == self.actor.id, UploadReceipt.request_id == request_id
            )
        )
        if previous is not None:
            # This new staging copy has never been referenced by a transaction.
            path_for(key).unlink(missing_ok=True)
            if previous.request_hash != payload_hash or previous.operation != operation:
                conflict("Mã upload đã được dùng cho nội dung khác.")
            self.owned(previous.document_id)
            return self.receipt(previous)
        if doc is None:
            doc = Document(
                id=uuid4(),
                owner_id=self.actor.id,
                school_id=self.actor.school_id,
                owner_name=self.actor.display_name,
                title=title.strip(),
                description=description,
                format=format_,
                revision=1,
                deleted=False,
            )
            self.session.add(doc)
            self.session.flush()
            number = 1
        else:
            number = 1 + (
                self.session.scalar(
                    select(func.max(Version.number)).where(Version.document_id == doc.id)
                )
                or 0
            )
            doc.revision += 1
        self.session.add(
            Version(
                document_id=doc.id,
                number=number,
                filename=filename,
                format=format_,
                size=size,
                sha256=digest,
                storage_key=key,
                status="PENDING",
                generation=0,
            )
        )
        receipt = UploadReceipt(
            user_id=self.actor.id,
            request_id=request_id,
            operation=operation,
            request_hash=payload_hash,
            document_id=doc.id,
            version=number,
        )
        self.session.add(receipt)
        # Do not delete the original on an ambiguous DB commit error. An unreferenced
        # blob is safer than removing a blob whose transaction may have committed.
        self.session.commit()
        return self.receipt(receipt)

    def receipt(self, receipt: UploadReceipt) -> dict:
        version = self.session.scalar(
            select(Version).where(
                Version.document_id == receipt.document_id, Version.number == receipt.version
            )
        )
        return {
            "request_id": receipt.request_id,
            "document_id": receipt.document_id,
            "version_number": receipt.version,
            "status": version.status,
            "created_at": receipt.created_at,
        }

    def retry(self, doc: Document, number: int, expected: int):
        version = self.version(doc, number, lock=True)
        now = self.session.scalar(select(func.clock_timestamp()))
        stale = (
            version.status == "PROCESSING"
            and version.lease_until is not None
            and version.lease_until < now
        )
        if version.generation != expected or not (version.status == "FAILED" or stale):
            conflict("Phiên bản đã đổi trạng thái. Hãy tải lại trước khi thử lại.")
        version.generation += 1
        version.status, version.lease_until, version.error_code = "PENDING", None, None
        self.session.commit()
        return version_dto(version, doc)

    def teaching(self, class_id: UUID):
        self.lecturer()
        access = self.access.class_access(class_id, "participate_current_class", fresh=True)
        if (
            not access["allowed"]
            or access.get("class_status") != "ACTIVE"
            or access.get("teaching_role") not in {"PRIMARY", "ASSISTING"}
        ):
            denied()
        return access

    def class_source(self, class_id: UUID, document_id: UUID, *, lock=False):
        current = self.access.class_access(class_id)
        if not current["allowed"]:
            denied()
        query = (
            select(Document)
            .where(
                Document.id == document_id,
                Document.school_id == self.actor.school_id,
                Document.deleted.is_(False),
            )
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        doc = self.session.scalar(query)
        grant = self.session.scalar(
            select(Grant)
            .where(
                Grant.document_id == document_id,
                Grant.class_id == class_id,
                Grant.school_id == self.actor.school_id,
                Grant.active.is_(True),
            )
            .execution_options(populate_existing=True)
        )
        if doc is None or grant is None:
            denied()
        return doc, grant, current

    def class_dto(self, doc: Document, grant: Grant, current: dict):
        latest = self.session.scalar(
            select(Version)
            .where(Version.document_id == doc.id)
            .order_by(Version.number.desc())
            .limit(1)
        )
        serving = (
            self.version(doc, doc.serving_version, ready=True) if doc.serving_version else None
        )
        return {
            "id": doc.id,
            "title": doc.title,
            "description": doc.description,
            "format": doc.format,
            "owner_id": doc.owner_id,
            "owner_name": doc.owner_name,
            "serving_version": doc.serving_version,
            "latest_status": latest.status,
            "created_at": doc.created_at,
            "updated_at": doc.updated_at,
            "grant_id": grant.id,
            "class_id": grant.class_id,
            "grant_revision": grant.revision,
            "class_status": current["class_status"],
            "can_manage_source": doc.owner_id == self.actor.id and "LECTURER" in self.actor.roles,
            "can_revoke_grant": current["class_status"] == "ACTIVE"
            and current.get("teaching_role") in {"PRIMARY", "ASSISTING"}
            and "LECTURER" in self.actor.roles,
            "locator_count": len(serving.content) if serving else None,
            "locator_kind": locator_kind(doc.format) if serving else None,
        }

    def set_grant(
        self, doc: Document, class_id: UUID, active: bool, expected: int, *, check_revision=True
    ) -> Grant:
        self.teaching(class_id)
        if active and doc.owner_id != self.actor.id:
            denied()
        grant = self.session.scalar(
            select(Grant)
            .where(Grant.document_id == doc.id, Grant.class_id == class_id)
            .with_for_update()
        )
        if grant is not None and grant.active == active:
            return grant
        if check_revision and expected != (grant.revision if grant else 0):
            conflict()
        if grant is None:
            if not active:
                missing()
            grant = Grant(
                id=uuid4(),
                document_id=doc.id,
                class_id=class_id,
                school_id=doc.school_id,
                active=True,
                granted_by=self.actor.id,
                revision=1,
            )
            self.session.add(grant)
        else:
            grant.active, grant.granted_by = active, self.actor.id
            grant.revision += 1
        doc.revision += 1
        self.session.flush()
        grant_event(self.session, doc, grant, self.actor.id)
        return grant

    def delete(self, doc: Document, revision: int, count: int):
        grants = list(
            self.session.scalars(
                select(Grant)
                .where(Grant.document_id == doc.id, Grant.active.is_(True))
                .with_for_update()
            )
        )
        if revision != doc.revision or count != len(grants):
            conflict("Phạm vi chia sẻ đã thay đổi. Hãy xem và xác nhận lại các lớp bị ảnh hưởng.")
        doc.deleted, doc.revision = True, doc.revision + 1
        for grant in grants:
            grant.active, grant.revision = False, grant.revision + 1
            grant_event(self.session, doc, grant, self.actor.id)
        append_event(
            self.session,
            doc,
            "document.source.deleted.v1",
            {
                "document_id": str(doc.id),
                "owner_user_id": str(doc.owner_id),
                "actor_user_id": str(self.actor.id),
            },
        )
        self.session.commit()
        return {"id": doc.id, "revision": doc.revision, "deleted": True}

    def content(self, doc: Document, version: Version, cursor: int, limit: int):
        if version.status != "READY" or version.content is None:
            conflict("Phiên bản chưa xử lý thành công.")
        rows = version.content[cursor : cursor + limit]
        next_cursor = str(cursor + len(rows)) if cursor + len(rows) < len(version.content) else None
        return {
            "document_id": doc.id,
            "version": version.number,
            "format": version.format,
            "locator_kind": locator_kind(version.format),
            "total_locators": len(version.content),
            "locators": rows,
            "next_cursor": next_cursor,
        }
