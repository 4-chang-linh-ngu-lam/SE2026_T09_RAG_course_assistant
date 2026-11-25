import hashlib
import inspect
import json
import sys
from pathlib import Path

import fitz
import pytest
from idp.documents import digital
from idp.ingest import ingest_file
from idp.input.filetypes import InputError
from idp.orchestration import pipeline
from PIL import Image

ROOT = Path(__file__).parent
GOLDEN = ROOT / 'golden' / ('linux-original.json' if sys.platform == 'linux' else 'expected.json')


def normalized(value):
    if isinstance(value, dict):
        return {
            k: normalized(v)
            for k, v in value.items()
            if k
            not in {
                "started_at",
                "finished_at",
                "created_at",
                "updated_at",
                "run_id",
                "duration_seconds",
                "elapsed_seconds",
                "timings",
            }
        }
    if isinstance(value, list):
        return [normalized(v) for v in value]
    return value


def snapshot(path, out, kind):
    try:
        if kind == "parser":
            from collections.abc import Mapping
            from dataclasses import fields, is_dataclass
            from enum import Enum

            from parser.pdf.engine import PdfParsingEngine

            def plain(item):
                if is_dataclass(item):
                    return {f.name: plain(getattr(item, f.name)) for f in fields(item)}
                if isinstance(item, Mapping):
                    return {k: plain(v) for k, v in item.items()}
                if isinstance(item, (tuple, list)):
                    return [plain(v) for v in item]
                if isinstance(item, Enum):
                    return item.value
                return item

            return normalized(
                plain(PdfParsingEngine().extract_source(path.read_bytes()))
            )
        if kind == 'fast':
            from idp.ocr.fast import run_fast
            run_fast(path, [1], out, lang='vie+eng', region_recovery=False)
        elif kind == 'fallback':
            from idp.ocr.fallback import tesseract_marker
            image = digital._render_pdf_page(path, 1, out / 'render.png', 300)
            marker = tesseract_marker(image, 1, out / 'markers', lang='vie+eng', recover_regions=False)
            pipeline.run_ingestion(path, [1], {1: marker}, {1: image}, out, language='vie+eng')
        elif kind == "digital":
            digital.process(
                path, out, tables="off", ocr_fallback=False, region_recovery=False
            )
        else:
            ingest_file(path, out, tables="off")
        raw = (out / "canonical.json").read_text(encoding="utf-8")
        # Replace only machine-dependent path prefixes, retaining asset identity.
        value = json.loads(raw)

        def paths(item):
            if isinstance(item, str):
                return item.replace(str(out), "<OUTPUT>").replace(str(ROOT), "<TESTS>")
            if isinstance(item, list):
                return [paths(v) for v in item]
            if isinstance(item, dict):
                return {k: paths(v) for k, v in item.items()}
            return item

        return normalized(paths(value))
    except (RuntimeError, ValueError, InputError) as error:
        return {
            "error_type": type(error).__name__,
            "code": getattr(error, "code", None),
        }


@pytest.mark.integration
def test_real_render_resume_and_independent_documents(tmp_path, monkeypatch):
    import shutil

    if not shutil.which("pdftoppm"):
        pytest.skip("Poppler pdftoppm unavailable")
    source = ROOT / "fixtures/generated/multipage.pdf"
    original = pipeline.sha256_file
    calls = []

    def counted(path):
        calls.append(Path(path))
        return original(path)

    monkeypatch.setattr(pipeline, "sha256_file", counted)
    digest = counted(source)
    images = []
    for page in (1, 2, 3):
        target = tmp_path / f"{page}.png"
        pipeline.ensure_page_image(source, page, target, dpi=72, source_sha256=digest)
        before = target.read_bytes()
        pipeline.ensure_page_image(source, page, target, dpi=72, source_sha256=digest)
        assert before == target.read_bytes()
        images.append(Image.open(target).size)
    assert len(calls) == 1
    assert images == [(400, 600)] * 3
    other = ROOT / "fixtures/generated/native.pdf"
    pipeline.ensure_page_image(other, 1, tmp_path / "other.png", dpi=72)
    assert len(calls) == 2
    assert (
        digest
        != json.loads((tmp_path / "other.png.source.json").read_text())["source_sha256"]
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "bbox,text,expected_calls",
    [
        ([-300, -300, -200, -200], "\ue001", 0),
        ([300, 300, 100, 100], "\ue001", 0),
        ([0, 0, 20, 20], "Normal source text", 0),
        ([0, 0, 20, 20], "\ue001", 1),
    ],
)
def test_recovery_edges_and_normal_blocks(
    tmp_path, monkeypatch, bbox, text, expected_calls
):
    from idp.input import filetypes
    from idp.ocr import fallback

    image = tmp_path / "image.png"
    Image.new("RGB", (800, 1200), "red").save(image)
    seen = []

    def ocr(crop, *args, **kwargs):
        assert crop.width > 0 and crop.height > 0
        seen.append(crop.size)
        return "Recovered independent expected text.", 0.99, 0

    monkeypatch.setattr(fallback, "crop_text_with_orientation", ocr)
    monkeypatch.setattr(filetypes, "choose_ocr_language", lambda value: ("eng", False))
    page = {
        "page_size": [400, 600],
        "blocks": [
            {
                "block_id": "block",
                "block_type": "Text",
                "bbox": bbox,
                "text": text,
                "review_flags": [],
            }
        ],
    }
    digital._recover_bad_blocks(page, image, "general", "eng", tmp_path / "crops")
    assert len(seen) == expected_calls


@pytest.mark.contract
@pytest.mark.parametrize(
    "module",
    [
        "idp.ingest",
        "idp.documents.digital",
        "idp.orchestration.cli",
        "idp.orchestration.batch",
        "idp.orchestration.worker",
    ],
)
def test_cli_help(module):
    import os
    import subprocess
    import sys

    env = dict(os.environ, PYTHONPATH=str(ROOT.parent))
    result = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        env=env,
        check=False,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")


@pytest.mark.unit
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="IDP-B2: native point and OCR pixel bbox units differ; deferred",
)
def test_native_and_ocr_bbox_unit_baseline(tmp_path):
    from idp.ocr import fast

    image = tmp_path / "render.png"
    Image.new("RGB", (800, 1200), "white").save(image)
    native = digital._page(
        1,
        [
            digital._block(
                "native",
                "Text",
                [40, 80, 100, 110],
                "Expected content",
                "Expected content",
            )
        ],
        [400, 600],
    )
    ocr = fast._page(
        1,
        image,
        [{"bbox": [80, 160, 200, 220], "text": "Expected content", "confidence": 99}],
        tmp_path,
        False,
    )
    assert native["blocks"][0]["bbox"] == ocr["blocks"][0]["bbox"]
