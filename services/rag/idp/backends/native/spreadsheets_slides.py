"""Level 0 native CSV, XLSX spreadsheet, and PPTX presentation backends."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from idp.backends.native.pdf import make_block, make_page
from idp.backends.native.text_formats import decode_txt
from idp.input.validation import InputError
from idp.processing.table import rows_to_html


def csv_pages(path: Path, assets: Path, profile: str) -> list[dict]:
    del assets, profile
    raw, _ = decode_txt(path)
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    rows = []
    flags = []
    for row in csv.reader(io.StringIO(raw), delimiter=delimiter):
        rows.append([str(cell) for cell in row])
        if len(rows) >= 2001:
            flags.append({"code": "TABLE_TRUNCATED", "severity": "warning", "reason": "row limit 2000"})
            break
    if not rows:
        raise InputError("EMPTY_DOCUMENT", "CSV has no rows")
    width = max(len(row) for row in rows)
    if width > 100:
        flags.append({"code": "TABLE_TRUNCATED", "severity": "warning", "reason": "column limit 100"})
        rows = [row[:100] for row in rows]
    table_html = rows_to_html(rows)
    table_text = " ".join(" ".join(row) for row in rows)
    block = make_block("p0001_b000", "Table", None, table_text, table_html, review_flags=flags, section_path=[path.stem])
    block["table_html"] = table_html
    return [make_page(1, [block], None, page_number=1)]


def xlsx_pages(path: Path, assets: Path, profile: str) -> list[dict]:
    del assets, profile
    try:
        import openpyxl
    except ImportError as exc:
        raise RuntimeError("xlsx ingestion requires openpyxl (`pip install openpyxl`)") from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    pages = []
    try:
        for sheet_index, sheet in enumerate(workbook.worksheets, 1):
            rows = []
            truncated = False
            for values in sheet.iter_rows(values_only=True):
                if len(rows) >= 2000:
                    truncated = True
                    break
                row = ["" if value is None else str(value) for value in values[:100]]
                if len(values) > 100:
                    truncated = True
                rows.append(row)
            blocks = [make_block(f"p{sheet_index:04d}_b000", "SectionHeader", None, sheet.title, f"# {sheet.title}", section_path=[sheet.title])]
            if rows:
                table_html = rows_to_html(rows)
                block = make_block(
                    f"p{sheet_index:04d}_b001", "Table", None,
                    " ".join(" ".join(row) for row in rows), table_html,
                    review_flags=[{"code": "TABLE_TRUNCATED", "severity": "warning", "reason": "row limit 2000"}] if truncated else [],
                    section_path=[sheet.title],
                )
                block["table_html"] = table_html
                blocks.append(block)
            else:
                blocks.append(
                    make_block(f"p{sheet_index:04d}_b001", "Text", None, "", "", review_flags=[{"code": "SHEET_EMPTY", "severity": "warning"}], section_path=[sheet.title])
                )
            pages.append(make_page(sheet_index, blocks, None, page_number=sheet_index))
    finally:
        workbook.close()
    if not pages:
        raise InputError("EMPTY_DOCUMENT", "workbook has no sheets")
    return pages


def pptx_pages(path: Path, assets: Path, profile: str) -> list[dict]:
    del profile
    try:
        from pptx import Presentation
        from pptx.enum.shapes import MSO_SHAPE_TYPE
    except ImportError as exc:
        raise RuntimeError("pptx ingestion requires python-pptx (`pip install python-pptx`)") from exc
    presentation = Presentation(path)
    pages = []
    slide_size = [presentation.slide_width, presentation.slide_height]
    for slide_index, slide in enumerate(presentation.slides, 1):
        blocks = []
        title_shape = slide.shapes.title

        def collect(shape):
            if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                for child in shape.shapes:
                    collect(child)
                return
            bbox = [
                shape.left or 0, shape.top or 0,
                (shape.left or 0) + (shape.width or 0),
                (shape.top or 0) + (shape.height or 0),
            ]
            if shape.has_text_frame:
                text = "\n".join(p.text for p in shape.text_frame.paragraphs if p.text.strip()).strip()
                if text:
                    is_title = shape is title_shape
                    blocks.append(make_block(
                        f"p{slide_index:04d}_b{len(blocks):03d}",
                        "SectionHeader" if is_title else "Text",
                        bbox, text, f"# {text}" if is_title else text,
                        section_path=[title_shape.text] if title_shape else [],
                    ))
            if shape.has_table:
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                table_html = rows_to_html(rows)
                block = make_block(
                    f"p{slide_index:04d}_b{len(blocks):03d}", "Table", bbox,
                    " ".join(" ".join(row) for row in rows), table_html,
                    section_path=[title_shape.text] if title_shape else [],
                )
                block["table_html"] = table_html
                blocks.append(block)
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                suffix = Path(shape.image.filename or "image.png").suffix or ".png"
                target = assets / f"pptx_{slide_index:03d}_{len(blocks):03d}{suffix}"
                target.write_bytes(shape.image.blob)
                blocks.append(make_block(
                    f"p{slide_index:04d}_b{len(blocks):03d}",
                    "Picture", bbox, shape.name, f"![{shape.name}]({target.as_posix()})",
                    asset_paths=[str(target)], section_path=[title_shape.text] if title_shape else [],
                ))
            if shape.has_chart:
                blocks.append(make_block(
                    f"p{slide_index:04d}_b{len(blocks):03d}",
                    "Text", bbox, f"[Chart: {shape.name}]", f"[Chart: {shape.name}]",
                    review_flags=[{"code": "CHART_NOT_EXTRACTED", "severity": "warning"}],
                    section_path=[title_shape.text] if title_shape else [],
                ))

        for shape in slide.shapes:
            collect(shape)
        if not blocks:
            blocks.append(make_block(
                f"p{slide_index:04d}_b000", "Text", None, "", "",
                review_flags=[{"code": "SLIDE_EMPTY", "severity": "warning"}],
            ))
        pages.append(make_page(slide_index, blocks, slide_size, page_number=slide_index))
    if not pages:
        raise InputError("EMPTY_DOCUMENT", "presentation has no slides")
    return pages
