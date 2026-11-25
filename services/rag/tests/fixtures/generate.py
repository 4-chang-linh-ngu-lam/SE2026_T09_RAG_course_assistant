"""Reproducible synthetic documents. Geometry is specified independently of extraction."""

import hashlib
from pathlib import Path

import fitz


def generate(directory):
    directory.mkdir(parents=True, exist_ok=True)
    manifest = []
    categories = [
        "native",
        "scan",
        "mixed",
        "columns",
        "table",
        "formula",
        "figure",
        "vietnamese",
        "encoding",
        "rotated_cropbox",
        "multipage",
    ]
    for category in categories:
        doc = fitz.open()
        for index in range(
            20 if category == "multipage" else 2 if category == "mixed" else 1
        ):
            page = doc.new_page(width=400, height=600)
            page.insert_text(
                (40, 80),
                "Phase zero document. Native source evidence for regression.",
                fontsize=9,
            )
            page.insert_text(
                (40, 110),
                f"Independent expected text. Page number {index + 1}.",
                fontsize=9,
            )
            if category in {"columns", "table"}:
                for row in range(8):
                    page.insert_text(
                        (30, 150 + row * 18), f"Left column {row}", fontsize=9
                    )
                    page.insert_text(
                        (240, 150 + row * 18), f"Right column {row}", fontsize=9
                    )
                if category == "table":
                    for y in (330, 350, 370):
                        page.draw_line((30, y), (370, y))
                    for x in (30, 140, 260, 370):
                        page.draw_line((x, 330), (x, 370))
                    page.insert_text(
                        (40, 345), "Name      Value       Grade", fontsize=9
                    )
            if category == "formula":
                page.insert_text((40, 180), "x^2 + y^2 = z^2", fontsize=12)
            if category == "figure":
                page.draw_rect(fitz.Rect(80, 180, 220, 260), fill=(1, 0, 0))
            if category == "encoding":
                page.insert_text((40, 200), "\ue001\ufffd", fontsize=12)
            if category == "vietnamese":
                font = next(
                    (
                        p
                        for p in [
                            Path("C:/Windows/Fonts/arial.ttf"),
                            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
                        ]
                        if p.exists()
                    ),
                    None,
                )
                if font is None:
                    raise RuntimeError("Set up a Unicode fixture font")
                page.insert_font(fontname="unicode", fontfile=str(font))
                page.insert_text(
                    (40, 210),
                    "Tiếng Việt: phương trình và hình học",
                    fontname="unicode",
                    fontsize=12,
                )
            if category == "rotated_cropbox":
                page.set_cropbox(fitz.Rect(20, 20, 380, 580))
                page.set_rotation(90)
        if category in {"scan", "mixed"}:
            old = doc
            doc = fitz.open()
            for index, page in enumerate(old):
                if category == "mixed" and index == 0:
                    doc.insert_pdf(old, from_page=0, to_page=0)
                else:
                    pix = page.get_pixmap()
                    doc.new_page(width=400, height=600).insert_image(
                        fitz.Rect(0, 0, 400, 600), stream=pix.tobytes("png")
                    )
            old.close()
        target = directory / (category + ".pdf")
        doc.save(target, no_new_id=True)
        pages = len(doc)
        doc.close()
        manifest.append(
            {
                "id": category,
                "filename": target.name,
                "category": category,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "generator": "tests/fixtures/generate.py",
                "license": "Project synthetic test fixture",
                "pages": pages,
                "expected_properties": {
                    "page_size_pt": [560, 360]
                    if category == "rotated_cropbox"
                    else [400, 600]
                },
                "ground_truth": None,
            }
        )
    for name, content in [
        ("plain.txt", "Phase zero plain text.\nIndependent expected text.\n"),
        ("plain.md", "# Phase zero\n\nIndependent expected text.\n"),
        ("broken.pdf", "%PDF-1.7\ninvalid"),
    ]:
        path = directory / name
        path.write_text(content, encoding="utf-8")
        manifest.append(
            {
                "id": name,
                "filename": name,
                "category": "non_pdf" if not name.endswith("pdf") else "corrupt",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "generator": "tests/fixtures/generate.py",
                "license": "Project synthetic test fixture",
                "pages": None,
                "expected_properties": {},
                "ground_truth": None,
            }
        )
    return manifest
