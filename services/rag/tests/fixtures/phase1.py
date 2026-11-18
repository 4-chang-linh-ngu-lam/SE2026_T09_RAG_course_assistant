"""Supplemental synthetic cases; never rewrites Phase 0 fixture files."""

from pathlib import Path

import fitz


def documents():
    base = Path(__file__).parent / "generated"
    with fitz.open() as blank:
        blank.new_page(width=400, height=600)
        blank_bytes = blank.tobytes(no_new_id=True)
    with (
        fitz.open(base / "native.pdf") as native,
        fitz.open(base / "scan.pdf") as scan,
        fitz.open() as mixed,
    ):
        mixed.insert_pdf(native)
        mixed.insert_pdf(scan)
        mixed.insert_pdf(native)
        image = scan[0].get_pixmap().tobytes("png")
        mixed[2].insert_image(fitz.Rect(40, 220, 360, 540), stream=image)
        mixed.new_page(width=400, height=600)
        mixed_bytes = mixed.tobytes(no_new_id=True)
    return {"blank": blank_bytes, "mixed4": mixed_bytes}
