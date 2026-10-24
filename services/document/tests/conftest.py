import io
import os
from urllib.parse import parse_qs, urlsplit
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.config import settings
from app.db import Base, SessionLocal
from app.errors import DocumentError
from app.main import app

SCHOOL = "00000000-0000-4000-8000-000000000001"
OTHER_SCHOOL = "00000000-0000-4000-8000-000000000002"
CLASS = "00000000-0000-4000-8000-000000000101"
OTHER_CLASS = "00000000-0000-4000-8000-000000000102"
TEACHER = "00000000-0000-4000-8000-000000000011"
ASSISTANT = "00000000-0000-4000-8000-000000000012"
STUDENT = "00000000-0000-4000-8000-000000000013"
OTHER_STUDENT = "00000000-0000-4000-8000-000000000014"
ADMIN = "00000000-0000-4000-8000-000000000015"
OUTSIDER = "00000000-0000-4000-8000-000000000016"


class CoreFixture:
    def __init__(self):
        self.available, self.archived, self.member = True, False, True
        self.teacher_assigned = True
        self.users = {
            TEACHER: (SCHOOL, ["LECTURER"]),
            ASSISTANT: (SCHOOL, ["LECTURER"]),
            STUDENT: (SCHOOL, ["STUDENT"]),
            OTHER_STUDENT: (SCHOOL, ["STUDENT"]),
            ADMIN: (SCHOOL, ["ADMIN"]),
            OUTSIDER: (OTHER_SCHOOL, ["STUDENT"]),
        }

    def request(self, path, *, bearer=None, body=None, event=False):
        if not self.available:
            raise DocumentError(503, "CORE_UNAVAILABLE", "Synthetic outage")
        if event:
            return {"accepted": True, "event_id": body["event_id"]}
        if path == "/health/ready":
            return {"status": "ready"}
        identity = (bearer or "").removeprefix("Bearer ")
        if identity not in self.users:
            raise DocumentError(401, "UNAUTHENTICATED", "Synthetic rejection")
        school, roles = self.users[identity]
        if path == "/api/v1/users/me":
            return {
                "id": identity,
                "school_id": school,
                "roles": roles,
                "status": "ACTIVE",
                "display_name": "Synthetic User",
            }
        if path.startswith("/api/v1/classes?"):
            return {"items": [{"id": CLASS, "name": "Synthetic class"}], "next_cursor": None}
        if path == f"/api/v1/classes/{CLASS}":
            return {"id": CLASS, "school_id": school, "name": "Synthetic class"}
        parts = urlsplit(path)
        action = parse_qs(parts.query)["action"][0]
        class_id = parts.path.split("/")[4]
        teacher = identity in {TEACHER, ASSISTANT} and self.teacher_assigned
        student = identity in {STUDENT, OTHER_STUDENT} and self.member
        allowed = class_id == CLASS and school == SCHOOL and (teacher or student)
        if action == "participate_current_class":
            allowed = allowed and not self.archived
        if action == "use_ai_tutor":
            allowed = allowed and student and not self.archived
        return {
            "user_id": identity,
            "action": action,
            "class_id": class_id,
            "allowed": allowed,
            "school_id": school if allowed else None,
            "class_status": "ARCHIVED" if self.archived else "ACTIVE",
            "teaching_role": ("PRIMARY" if identity == TEACHER else "ASSISTING")
            if teacher
            else None,
        }


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    if (
        os.environ.get("DOCUMENT_TEST_MODE") != "synthetic"
        or "lumi_doc_test_" not in settings.database_url
    ):
        pytest.fail("Tests require the isolated synthetic PostgreSQL fixture")
    with SessionLocal() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    monkeypatch.setattr(settings, "document_internal_service_secret", None)
    monkeypatch.setattr(settings, "document_event_reader_secret", None)
    app.state.core = CoreFixture()
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as value:
        yield value


def auth(user=TEACHER):
    return {"Authorization": "Bearer " + user}


def office_bytes(format_):
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        )
        if format_ == "DOCX":
            archive.writestr(
                "word/document.xml",
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello source</w:t></w:r></w:p></w:body></w:document>',
            )
        else:
            archive.writestr(
                "ppt/presentation.xml",
                '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId2"/><p:sldId id="257" r:id="rId1"/></p:sldIdLst></p:presentation>',
            )
            archive.writestr(
                "ppt/_rels/presentation.xml.rels",
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="slides/slide1.xml"/><Relationship Id="rId2" Target="slides/slide2.xml"/></Relationships>',
            )
            for number, value in ((1, "Second slide"), (2, "Hello source")):
                archive.writestr(
                    f"ppt/slides/slide{number}.xml",
                    f'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><a:t>{value}</a:t></p:cSld></p:sld>',
                )
    return output.getvalue()


def pdf_bytes():
    writer = PdfWriter()
    page = writer.add_blank_page(300, 300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 250 Td (Hello source) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
