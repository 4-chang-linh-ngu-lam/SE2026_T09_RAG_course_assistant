from uuid import uuid4

from sqlalchemy import select

from app.documents import Documents, advisory, fingerprint, locator_kind
from app.errors import DocumentError, conflict, denied, missing
from app.models import Bookmark, Document, Note


class Personal(Documents):
    def source_state(self, class_id, document_id):
        try:
            self.class_source(class_id, document_id)
            return "ALLOWED"
        except DocumentError as error:
            if error.status == 401:
                raise
            return "UNAVAILABLE" if error.status >= 500 else "REVOKED"

    def own(self, model, id_, lock=False):
        query = select(model).where(model.id == id_, model.user_id == self.actor.id)
        if lock:
            query = query.with_for_update()
        row = self.session.scalar(query)
        if row is None:
            missing()
        return row

    def dto(self, row):
        doc = self.session.get(Document, row.document_id)
        if doc.school_id != self.actor.school_id:
            denied()
        state = self.source_state(row.class_id, row.document_id)
        label = {"PAGE": "Trang", "SLIDE": "Slide", "SECTION": "Mục"}[locator_kind(doc.format)]
        data = {
            "id": row.id,
            "document_id": row.document_id,
            "document_title": doc.title if state == "ALLOWED" else row.document_title,
            "document_format": doc.format,
            "version": row.version,
            "class_id": row.class_id,
            "class_name": row.class_name,
            "locator_id": row.locator_id,
            "locator_label": f"{label} {row.locator_id}",
            "source_access": state,
        }
        if isinstance(row, Note):
            data.update(
                note_text=row.note_text,
                source_quote=row.source_quote if state == "ALLOWED" else None,
                revision=row.revision,
                client_request_id=str(row.client_request_id),
                updated_at=row.updated_at,
            )
        else:
            data["created_at"] = row.created_at
        return data

    def valid_locator(self, doc, version, locator_id):
        item = self.version(doc, version, ready=True)
        locator = next((page for page in item.content if page["id"] == locator_id), None)
        if locator is None:
            raise DocumentError(422, "INVALID_LOCATOR", "Vị trí không có trong phiên bản tài liệu.")
        return locator

    def create_note(self, class_id, document_id, body):
        doc, _, _ = self.class_source(class_id, document_id, lock=True)
        locator = self.valid_locator(doc, body.version, body.locator_id)
        if body.source_quote and body.source_quote not in locator["text"]:
            raise DocumentError(422, "INVALID_QUOTE", "Trích dẫn không thuộc vị trí nguồn đã chọn.")
        request_hash = fingerprint([class_id, document_id, body.model_dump()])
        advisory(self.session, f"note:{self.actor.id}:{body.client_request_id}")
        note = self.session.scalar(
            select(Note).where(
                Note.user_id == self.actor.id, Note.client_request_id == body.client_request_id
            )
        )
        if note is not None:
            if note.request_hash != request_hash:
                conflict("Mã lưu ghi chú đã được dùng cho nội dung khác.")
            return self.dto(note)
        note = Note(
            id=uuid4(),
            user_id=self.actor.id,
            document_id=doc.id,
            version=body.version,
            class_id=class_id,
            document_title=doc.title,
            class_name=self.access.class_name(class_id),
            locator_id=body.locator_id,
            note_text=body.note_text,
            source_quote=body.source_quote,
            revision=1,
            client_request_id=body.client_request_id,
            request_hash=request_hash,
        )
        self.session.add(note)
        self.session.commit()
        return self.dto(note)

    def edit_note(self, note_id, body):
        # Document lock precedes note lock everywhere to avoid grant/delete deadlocks.
        current = self.own(Note, note_id)
        self.class_source(current.class_id, current.document_id, lock=True)
        note = self.own(Note, note_id, lock=True)
        if note.revision != body.expected_revision:
            conflict()
        note.note_text, note.revision = body.note_text, note.revision + 1
        self.session.commit()
        return self.dto(note)

    def bookmark(self, class_id, document_id, version, locator_id, bookmarked):
        advisory(
            self.session,
            f"bookmark:{self.actor.id}:{class_id}:{document_id}:{version}:{locator_id}",
        )
        if bookmarked:
            doc, _, _ = self.class_source(class_id, document_id, lock=True)
            self.valid_locator(doc, version, locator_id)
        item = self.session.scalar(
            select(Bookmark)
            .where(
                Bookmark.user_id == self.actor.id,
                Bookmark.document_id == document_id,
                Bookmark.class_id == class_id,
                Bookmark.version == version,
                Bookmark.locator_id == locator_id,
            )
            .with_for_update()
        )
        if not bookmarked:
            if item is not None:
                self.session.delete(item)
            self.session.commit()
            return {"bookmarked": False, "bookmark": None}
        if item is None:
            item = Bookmark(
                user_id=self.actor.id,
                document_id=document_id,
                class_id=class_id,
                document_title=doc.title,
                class_name=self.access.class_name(class_id),
                version=version,
                locator_id=locator_id,
            )
            self.session.add(item)
        self.session.commit()
        return {"bookmarked": True, "bookmark": self.dto(item)}
