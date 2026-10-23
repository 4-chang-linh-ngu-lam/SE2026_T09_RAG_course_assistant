"""Bounded CSV/XLSX parsing: no raw uploads or validation input in logs/results."""

import base64
import binascii
import csv
import io
import zipfile
from xml.etree.ElementTree import ParseError

from defusedxml.common import DefusedXmlException
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import ValidationError

from app.common.errors import AppError
from app.modules.administration.schemas import ImportErrorResponse, ImportPreviewRequest
from app.modules.identity.public import StudentImportRow

MAX_FILE_BYTES = 2_000_000
MAX_XML_BYTES = 10_000_000
MAX_ROWS = 100
COLUMNS = {"username", "display_name", "user_id"}


def parse_students(request: ImportPreviewRequest) -> tuple[list[dict], list[ImportErrorResponse]]:
    try:
        content = base64.b64decode(request.content_base64, validate=True)
        if len(content) > MAX_FILE_BYTES:
            raise ValueError("File too large")
        if request.format == "CSV":
            matrix = []
            for values in csv.reader(io.StringIO(content.decode("utf-8-sig"))):
                matrix.append(values)
                if len(matrix) > MAX_ROWS + 1:
                    raise ValueError("Too many rows")
        else:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                infos = archive.infolist()
                if len(infos) > 100 or sum(info.file_size for info in infos) > MAX_XML_BYTES:
                    raise ValueError("Archive limits exceeded")
                for info in infos:
                    if info.filename.endswith(".xml"):
                        xml = archive.read(info).upper()
                        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                            raise ValueError("Unsafe XML")
            workbook = load_workbook(
                io.BytesIO(content), read_only=True, data_only=False, keep_links=False
            )
            try:
                if len(workbook.worksheets) != 1:
                    raise ValueError("Exactly one worksheet required")
                sheet = workbook.worksheets[0]
                if (sheet.max_row or 0) > MAX_ROWS + 1 or (sheet.max_column or 0) > len(COLUMNS):
                    raise ValueError("Worksheet limits exceeded")
                matrix = []
                for cells in sheet.iter_rows():
                    if any(cell.data_type == "f" for cell in cells):
                        raise ValueError("Formula cells are not accepted")
                    matrix.append([cell.value for cell in cells])
                    if len(matrix) > MAX_ROWS + 1:
                        raise ValueError("Too many rows")
            finally:
                workbook.close()
        if not matrix or len(matrix) < 2:
            raise ValueError("Missing rows")
        header = matrix[0]
        if not all(isinstance(value, str) for value in header):
            raise ValueError("Invalid columns")
        if len(set(header)) != len(header) or set(header) - COLUMNS or "username" not in header:
            raise ValueError("Invalid columns")
        rows, errors, names, user_ids = [], [], set(), set()
        for number, values in enumerate(matrix[1:], start=2):
            if not any(value is not None and value != "" for value in values):
                continue
            try:
                if len(values) != len(header) or any(
                    value is not None and (not isinstance(value, str) or len(value) > 500)
                    for value in values
                ):
                    raise ValueError("Invalid row")
                data = {
                    key: value
                    for key, value in zip(header, values, strict=True)
                    if value not in (None, "")
                }
                row = StudentImportRow.model_validate(data)
                if row.username in names or (row.user_id is not None and row.user_id in user_ids):
                    errors.append(ImportErrorResponse(row=number, code="DUPLICATE_ROW"))
                names.add(row.username)
                if row.user_id is not None:
                    user_ids.add(row.user_id)
                rows.append({"number": number, "values": row.model_dump(mode="json")})
            except (ValueError, ValidationError):
                errors.append(ImportErrorResponse(row=number, code="INVALID_ROW"))
        if not rows and not errors:
            raise ValueError("Missing rows")
        return rows, errors
    except (
        ParseError,
        DefusedXmlException,
        InvalidFileException,
        RuntimeError,
        ValueError,
        binascii.Error,
        csv.Error,
        UnicodeError,
        zipfile.BadZipFile,
        KeyError,
        OSError,
    ) as exc:
        raise AppError(422, "Invalid or oversized student import file") from exc
