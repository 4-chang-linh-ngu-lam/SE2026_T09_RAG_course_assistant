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


@pytest.mark.golden
@pytest.mark.parametrize(
    "case",
    json.loads(GOLDEN.read_text(encoding="utf-8"))
    if GOLDEN.exists()
    else [],
)
def test_frozen_output(case, tmp_path):
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    kind, filename = case.split(":")
    assert (
        snapshot(ROOT / "fixtures/generated" / filename, tmp_path, kind)
        == expected[case]
    )


@pytest.mark.contract
def test_public_signatures():
    assert GOLDEN.is_file(), 'Missing original-source baseline for this platform'
    from idp.canonical import audit_canonical, build_canonical
    from idp.orchestration.worker import IngestionWorker, JobRequest
    from parser.pdf.engine import PdfParsingEngine

    functions = [
        ingest_file,
        digital.process,
        pipeline.run_pipeline,
        pipeline.run_ingestion,
        build_canonical,
        audit_canonical,
        IngestionWorker.__init__,
        JobRequest.from_dict,
        PdfParsingEngine.extract_source,
    ]
    expected = json.loads((ROOT / "golden/signatures.json").read_text())
    assert {
        f"{f.__module__}.{f.__qualname__}": str(inspect.signature(f)) for f in functions
    } == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "dpi,limit,rotation,displayed_boxes",
    [(144, 2000, 0, False), (600, 800, 0, False),
     (300, 2000, 90, False), (300, 2000, 90, True)]
)
def test_bad_block_crop_targets_actual_render(
    tmp_path, monkeypatch, dpi, limit, rotation, displayed_boxes
):
    from idp.input import filetypes
    from idp.ocr import fallback

    path = tmp_path / "target.pdf"
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    box = fitz.Rect(100, 200, 200, 280)
    page.draw_rect(box, fill=(1, 0, 0), color=(1, 0, 0))
    page.set_rotation(rotation)
    reported_box = box * page.rotation_matrix if displayed_boxes else box
    doc.save(path)
    doc.close()
    image = digital._render_pdf_page(
        path, 1, tmp_path / "page.png", dpi, max_longest_dim=limit
    )
    page_data = {
        "page_id": 1,
        "page_size": [600, 400] if rotation else [400, 600],
        "blocks": [
            {
                "block_id": "bad",
                "block_type": "Text",
                "bbox": list(reported_box),
                "text": "\ue001",
                "review_flags": [],
            }
        ],
    }
    seen = []

    def ocr(crop, *args, **kwargs):
        seen.append(crop.getpixel((crop.width // 2, crop.height // 2)))
        return "Recovered independent expected text.", 0.99, 0

    monkeypatch.setattr(fallback, "crop_text_with_orientation", ocr)
    monkeypatch.setattr(filetypes, "choose_ocr_language", lambda value: ("eng", False))
    kwargs = (
        {"pdf_path": path, "displayed_boxes": displayed_boxes}
        if "pdf_path" in inspect.signature(digital._recover_bad_blocks).parameters
        else {}
    )
    assert (
        digital._recover_bad_blocks(
            page_data, image, "general", "eng", tmp_path / "crops", **kwargs
        )
        == 1
    )
    assert seen and seen[0][0] > 240 and seen[0][1] < 20


def test_verifier_resume_preserves_correction_and_page_review(tmp_path, monkeypatch):
    from idp.validation.corrections import apply_corrections

    source = ROOT / "fixtures/generated/native.pdf"
    image = tmp_path / "page.png"
    Image.new("RGB", (400, 400), "white").save(image)
    marker = tmp_path / "source.json"
    marker.write_text(json.dumps({"children": [{
        "block_type": "Page", "bbox": [0, 0, 400, 400],
        "children": [{"block_type": "Text", "bbox": [10, 10, 300, 50],
                      "html": "<p>Independent expected text for the first reading.</p>"}],
    }]}), encoding="utf-8")
    calls = []

    def verify(command, number, page_image, original, directory, *, timeout):
        calls.append(number)
        directory.mkdir(parents=True)
        path = directory / f"p{number:04d}.json"
        payload = json.loads(marker.read_text(encoding="utf-8"))
        payload["metadata"] = {"engine": "test-verifier"}
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path, payload["metadata"]

    monkeypatch.setattr(pipeline, "verify_page", verify)
    out = tmp_path / "out"
    options = dict(
        verify_cmd="test-verifier", skip_text_candidate_pages={1},
        page_review_by_page={1: [{"code": "FAST_MODE_REVIEW", "severity": "warning"}]},
    )
    first = pipeline.run_pipeline(source, [1], {1: marker}, {1: image}, out, **options)
    assert calls == [1]
    page_json = out / "pages/p0001.json"
    block_id = first["pages"][0]["blocks"][0]["block_id"]
    apply_corrections(page_json, [{"block_id": block_id, "text": "Human correction kept."}])
    resumed = pipeline.run_pipeline(source, [1], {1: marker}, {1: image}, out, resume=True, **options)
    page = resumed["pages"][0]
    assert calls == [1]
    assert page["blocks"][0]["text"] == "Human correction kept."
    assert any(flag["code"] == "FAST_MODE_REVIEW" for flag in page["review"])


@pytest.mark.unit
def test_page_image_hash_job_reuse_and_legacy(tmp_path, monkeypatch):
    source = tmp_path / "input.pdf"
    source.write_bytes(b"first PDF generation")
    original = pipeline.sha256_file
    calls = []

    def counted(path):
        calls.append(Path(path))
        return original(path)

    monkeypatch.setattr(pipeline, "sha256_file", counted)
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *args, **kwargs: None)
    digest = counted(source)
    for i in range(5):
        kwargs = (
            {"source_sha256": digest}
            if "source_sha256"
            in inspect.signature(pipeline.ensure_page_image).parameters
            else {}
        )
        pipeline.ensure_page_image(source, i + 1, tmp_path / f"p{i}.png", **kwargs)
    assert len(calls) == 1
    source.write_bytes(b"changed PDF generation")
    pipeline.ensure_page_image(source, 1, tmp_path / "new.png")
    assert (
        json.loads((tmp_path / "new.png.source.json").read_text())["source_sha256"]
        == hashlib.sha256(source.read_bytes()).hexdigest()
    )


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


@pytest.mark.integration
def test_optional_fast_ocr(tmp_path):
    import shutil

    if not shutil.which("tesseract"):
        pytest.skip("Tesseract executable and traineddata unavailable")
    from idp.ocr.fast import run_fast

    result = run_fast(
        ROOT / "fixtures/generated/scan.pdf",
        [1],
        tmp_path,
        lang="eng",
        region_recovery=False,
    )
    assert result
    canonical = json.loads((tmp_path / 'canonical.json').read_text(encoding='utf-8'))
    recognized = ' '.join(block['text'] for page in canonical['pages'] for block in page['blocks'])
    assert 'Independent expected text' in recognized


@pytest.mark.integration
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="PARSER-W1: spanning-table reading order baseline, deferred by Phase 0 scope",
)
def test_spanning_table_precedes_following_body(tmp_path):
    from parser.pdf.engine import PdfParsingEngine

    document = fitz.open()
    page = document.new_page(width=600, height=800)
    for row in range(4):
        page.insert_text((40, 80 + row * 20), f"LEFT INTRO {row}")
        page.insert_text((340, 80 + row * 20), f"RIGHT INTRO {row}")
    for y in (190, 220, 250):
        page.draw_line((40, y), (560, y))
    for x in (40, 210, 390, 560):
        page.draw_line((x, 190), (x, 250))
    for x, text in [(50, "Name"), (220, "Value"), (400, "Grade")]:
        page.insert_text((x, 210), text)
    page.insert_text((40, 350), "AFTERLEFT")
    page.insert_text((340, 350), "AFTERRIGHT")
    result = PdfParsingEngine().extract_source(document.tobytes())
    text = "\n".join(item.text for item in result.observations)
    assert text.index("Grade") < text.index("AFTERLEFT")


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
