import ast
import base64
import io
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pydantic import ValidationError

from app.common.auth_dependencies import CurrentUser, get_current_user
from app.common.errors import AppError
from app.main import app
from app.modules.administration.import_parser import parse_students
from app.modules.administration.schemas import (
    AdminCreateUserRequest,
    AdminDataRequestResolve,
    AdminUserRolesRequest,
    ImportPreviewRequest,
)


def csv_request(value, **kwargs):
    return ImportPreviewRequest(
        format="CSV", content_base64=base64.b64encode(value.encode()).decode(), **kwargs
    )


def xlsx_request(rows):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    data = io.BytesIO()
    workbook.save(data)
    workbook.close()
    return ImportPreviewRequest(
        format="XLSX", content_base64=base64.b64encode(data.getvalue()).decode()
    )


def test_parser_normalizes_csv_and_xlsx_identically():
    rows = [["username", "display_name"], [" STUDENT.9 ", "Học sinh tổng hợp"]]
    expected, errors = parse_students(
        csv_request("username,display_name\n STUDENT.9 ,Học sinh tổng hợp\n")
    )
    assert not errors and expected[0]["values"]["username"] == "student.9"
    actual, errors = parse_students(xlsx_request(rows))
    assert not errors and actual == expected


def test_parser_accepts_selected_headers_and_ignores_unmapped_cells():
    rows, errors = parse_students(
        csv_request(
            "Student code,Full name,Private note\nstudent.9,Học sinh tổng hợp,không xuất ra response\n",
            username_header="Student code",
            display_name_header="Full name",
            user_id_header=None,
        )
    )
    assert not errors
    assert rows[0]["values"] == {
        "username": "student.9",
        "display_name": "Học sinh tổng hợp",
        "user_id": None,
    }


def test_parser_normalizes_header_whitespace_like_the_frontend_mapping():
    rows, errors = parse_students(
        csv_request(
            " Student code , Full name \nstudent.9,Học sinh tổng hợp\n",
            username_header="Student code",
            display_name_header="Full name",
            user_id_header=None,
        )
    )
    assert not errors and rows[0]["values"]["username"] == "student.9"


def test_parser_does_not_use_legacy_user_ids_without_explicit_selection():
    rows, errors = parse_students(csv_request("username,user_id\nstudent.9,ignored-id\n"))
    assert not errors and rows[0]["values"] == {
        "username": "student.9",
        "display_name": None,
        "user_id": None,
    }


def test_duplicate_and_invalid_rows_do_not_echo_input():
    rows, errors = parse_students(
        csv_request(
            "username,display_name\nstudent,Name\n STUDENT ,Other\ncontains@secret,private input\n"
        )
    )
    assert len(rows) == 2
    assert [(error.row, error.code) for error in errors] == [
        (3, "DUPLICATE_ROW"),
        (4, "INVALID_ROW"),
    ]
    assert "secret" not in str(errors) and "private input" not in str(errors)


def test_csv_error_rows_match_physical_lines_after_quoted_newlines():
    rows, errors = parse_students(
        csv_request('username,display_name\nsame,"First\ncontinued"\nsame,Second\n')
    )
    assert [item["number"] for item in rows] == [2, 4]
    assert [(error.row, error.code) for error in errors] == [(4, "DUPLICATE_ROW")]


@pytest.mark.parametrize(
    "value",
    [
        "",
        "email\nstudent@example.com\n",
        "username,username\na,b\n",
        "username\n" + "\n".join(f"s{i}" for i in range(101)),
    ],
)
def test_csv_rejects_wrong_shape_or_oversized_batch(value):
    with pytest.raises((AppError, ValidationError)) as invalid:
        parse_students(csv_request(value))
    if isinstance(invalid.value, AppError):
        assert invalid.value.status_code == 422


@pytest.mark.parametrize("rows", [[["username"], ["=1+1"]], [["username"], [5]]])
def test_xlsx_rejects_formulas_and_numeric_identifiers(rows):
    try:
        values, errors = parse_students(xlsx_request(rows))
        assert errors and not values
    except AppError as invalid:
        assert invalid.status_code == 422


def test_xlsx_ignores_unselected_columns():
    rows, errors = parse_students(
        xlsx_request([["username", "private_note"], ["student.9", "private"]])
    )
    assert not errors and rows[0]["values"] == {
        "username": "student.9",
        "display_name": None,
        "user_id": None,
    }


def test_xlsx_rejects_archive_bomb_before_loading():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"x" * 10_000_001)
    with pytest.raises(AppError):
        parse_students(
            ImportPreviewRequest(
                format="XLSX", content_base64=base64.b64encode(data.getvalue()).decode()
            )
        )


def test_xlsx_rejects_xml_entities():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("xl/workbook.xml", '<!DOCTYPE foo [<!ENTITY x "private">]>')
    with pytest.raises(AppError):
        parse_students(
            ImportPreviewRequest(
                format="XLSX", content_base64=base64.b64encode(data.getvalue()).decode()
            )
        )


@pytest.mark.parametrize("roles", [[], ["ADMIN", "ADMIN"], ["UNKNOWN"]])
def test_roles_reject_empty_duplicates_or_unknown_values(roles):
    with pytest.raises(ValidationError):
        AdminUserRolesRequest(roles=roles)


def test_staff_onboarding_and_resolution_do_not_accept_student_email_or_arbitrary_text():
    with pytest.raises(ValidationError):
        AdminCreateUserRequest(email="student@example.com", roles=["STUDENT"])
    with pytest.raises(ValidationError):
        AdminDataRequestResolve(
            status="COMPLETED", resolution_note="private raw chat text", identity_verified=True
        )
    with pytest.raises(ValidationError):
        AdminDataRequestResolve(
            status="REJECTED", resolution_note="REQUEST_REJECTED", identity_verified="true"
        )


def test_administration_routes_are_authenticated_admin_only():
    id = str(uuid4())
    requests = [
        ("post", "/users", {"email": "staff@example.com", "roles": ["LECTURER"]}),
        ("patch", f"/users/{id}/status", {"status": "LOCKED"}),
        ("put", f"/users/{id}/roles", {"roles": ["LECTURER"]}),
        ("get", "/audit-events", None),
        ("get", "/data-requests", None),
        ("get", f"/data-requests/{id}", None),
        (
            "patch",
            f"/data-requests/{id}",
            {"status": "IN_REVIEW", "resolution_note": "POLICY_PENDING"},
        ),
        ("post", "/students/imports/preview", csv_request("username\nstudent\n").model_dump()),
        ("post", "/students/imports/confirm", {"preview_id": id}),
        ("get", f"/students/imports/{id}", None),
    ]
    previous = app.dependency_overrides.copy()
    try:
        with TestClient(app) as client:
            for roles, expected in ((None, 401), (["STUDENT"], 403), (["LECTURER"], 403)):
                if roles is not None:
                    app.dependency_overrides[get_current_user] = lambda roles=roles: CurrentUser(
                        id=uuid4(), status="ACTIVE", roles=roles, session_version=1
                    )
                for method, path, body in requests:
                    kwargs = {"json": body} if body is not None else {}
                    response = getattr(client, method)(
                        "/api/v1/admin" + path,
                        headers={"X-Admin-Reason": "ADMIN_INTERVENTION"},
                        **kwargs,
                    )
                    assert response.status_code == expected, (path, response.text)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_administration_only_calls_other_modules_public_interfaces():
    root = Path(__file__).resolve().parents[2] / "app/modules/administration"
    for source in root.glob("*.py"):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("app.modules.")
            ):
                assert (
                    node.module.startswith("app.modules.administration.")
                    or node.module.endswith(".public")
                    or (
                        node.module in {"app.modules.identity", "app.modules.classroom"}
                        and all(alias.name == "public" for alias in node.names)
                    )
                ), source
