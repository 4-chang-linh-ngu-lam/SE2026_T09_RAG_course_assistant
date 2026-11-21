"""Phase 4 safety, real chunker/index retrieval and structured data contracts."""

import copy
import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path
from time import monotonic
from typing import ClassVar

import fitz
import pytest
from idp.pdf.render import digest
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.publish import (
    PublishPolicy,
    from_v1,
    iter_retrievable_blocks,
    to_v1,
    validate_canonical,
)
from retrieval.canonical_harness import LocalRagIndex, build_chunks, resolve_citation

FIX = Path(__file__).parent / "fixtures/generated"


def canonical(tmp_path, name="native.pdf", **kwargs):
    return DeepDocService(
        DeepDocConfig(
            engine="unified",
            canonical_version=2,
            document_version="fixture-v1",
            **kwargs,
        )
    ).process_pdf(FIX / name, tmp_path)


def resign(value):
    value["integrity_sha256"] = digest(
        {k: v for k, v in value.items() if k != "integrity_sha256"}
    )
    return value


def test_real_native_v2_and_rag(tmp_path):
    doc = canonical(tmp_path / "out")
    assert doc["schema_version"] == "idp-canonical-2"
    eligible = list(iter_retrievable_blocks(doc))
    assert eligible and all(
        b["region_id"] and b["candidate_id"] and b["evidence_refs"] for b in eligible
    )
    assert all(b["verification_status"] == "source_preserved" for b in eligible)
    index = LocalRagIndex(tmp_path / "rag.sqlite3")
    count = index.index(doc)
    assert count > 0
    hits = index.retrieve(
        "Independent expected text",
        actor="student-a",
        access_check=lambda a, s, v: True,
    )
    assert hits and "Independent expected text" in hits[0]["text"]
    assert resolve_citation(hits[0], doc)
    assert hits[0]["document_version"] == "fixture-v1"
    assert index.index(doc) == count
    with sqlite3.connect(index.path) as connection:
        assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == count
    assert (
        index.retrieve(
            "Independent expected text", actor="denied", access_check=lambda *a: False
        )
        == []
    )
    assert (
        index.retrieve(
            "Independent expected text",
            actor="denied",
            access_check=lambda *a: False,
            scope_source_ids={doc["source_sha256"]},
        )
        == []
    )


@pytest.mark.parametrize(
    "attack",
    [
        "schema",
        "eligible",
        "role",
        "evidence",
        "source",
        "text",
        "status",
        "confidence",
        "origin",
        "page_authorized",
        "missing_candidate",
        "structured_content",
        "polygon",
        "coord_space",
        "unknown_field",
    ],
)
def test_publication_bypass_rejected(tmp_path, attack):
    doc = canonical(tmp_path)
    target = doc["pages"][0]["blocks"][0]
    if attack == "schema":
        doc["schema_version"] = "idp-canonical-999"
    elif attack == "eligible":
        target["retrieval_eligible"] = False
    elif attack == "role":
        target["index_role"] = "alternative"
    elif attack == "evidence":
        target["evidence_refs"] = []
    elif attack == "source":
        target["source_sha256"] = "f" * 64
    elif attack == "text":
        target["text"] = "Hallucinated secret answer"
    elif attack == "status":
        target["verification_status"] = "proof_verified"
    elif attack == "confidence":
        target["confidence"] = 1.0
    elif attack == "origin":
        target["origin"] = "OCR"
    elif attack == "page_authorized":
        target["page_authorized"] = False
    elif attack == "structured_content":
        target["structured_content"] = {"invented": "unsupported answer"}
    elif attack == "polygon":
        target["polygon"] = [[1, 1], [2, 2]]
    elif attack == "coord_space":
        target["coord_space"] = "pixels"
    elif attack == "unknown_field":
        target["markdown"] = "unsupported extra content"
    else:
        doc["pages"][0]["blocks"].pop()
    resign(doc)  # integrity alone is not treated as a policy authorization
    with pytest.raises(ValueError):
        list(iter_retrievable_blocks(doc))


def test_legacy_conversion_is_conservative(tmp_path):
    doc = canonical(tmp_path)
    v1 = to_v1(doc)
    assert v1["schema_version"] == "idp-canonical-1"
    imported = from_v1(v1)
    assert all(
        b["verification_status"] == "legacy_unknown"
        for p in imported["pages"]
        for b in p["blocks"]
    )
    assert imported["l1_payload"] is None
    assert list(iter_retrievable_blocks(imported)) == []
    assert all(not p["blocks"] for p in to_v1(imported)["pages"])


def test_current_permission_failure_closed(tmp_path):
    index = LocalRagIndex(tmp_path / "index.sqlite3")
    doc = canonical(tmp_path / "out")
    index.index(doc)

    def unavailable(*args):
        raise RuntimeError("permission provider unavailable")

    assert index.retrieve("native", actor="a", access_check=unavailable) == []
    assert index.retrieve("native", actor="a", access_check=lambda *a: "yes") == []
    with pytest.raises(ValueError):
        index.retrieve("native", actor=None, access_check=lambda *a: True)


def test_canonical_numbered_task_ranks_before_reference_with_fresh_access(tmp_path):
    path = tmp_path / "numbered.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((60, 75), "Bài 1. Lesson title")
        page.insert_text((60, 120), "Figure 1.2 shows the number line.")
        page.insert_text((60, 230), "1.2. Find the integers in this interval.")
        pdf.save(path)
    doc = DeepDocService(
        DeepDocConfig(engine="unified", canonical_version=2, document_version="test-v1")
    ).process_pdf(path, tmp_path / "out")
    index = LocalRagIndex(tmp_path / "index.sqlite3")
    index.index(doc)

    def allow(*args):
        return args == ("student", doc["source_sha256"], doc["document_version"])

    hit = index.retrieve("bai 1.2", actor="student", access_check=allow)[0]
    assert hit["text"].startswith("1.2. Find the integers")
    assert resolve_citation(hit, doc)
    hit["references"][0]["region_id"] = "mutated"
    cached = index._lexical_snapshot
    next_hit = index.retrieve("bài 1.2", actor="student", access_check=allow)[0]
    assert index._lexical_snapshot is cached
    assert resolve_citation(next_hit, doc)
    grants = iter((True, False))
    assert index.retrieve(
        "bai 1.2", actor="student", access_check=lambda *_: next(grants)
    ) == []
    index.path.unlink()


def test_citation_cannot_be_fabricated(tmp_path):
    doc = canonical(tmp_path / "out")
    index = LocalRagIndex(tmp_path / "index.sqlite3")
    index.index(doc)
    hit = index.retrieve("Independent", actor="a", access_check=lambda *a: True)[0]
    hit["references"][0]["region_id"] = "invented-region"
    with pytest.raises(ValueError):
        resolve_citation(hit, doc)


def test_native_structures_and_invalid_latex(tmp_path):
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.understanding import understand
    from idp.validation.validate import validate_latex
    from test_phase3 import spanning_table

    table = PdfParsingEngine().extract_source(spanning_table())
    output = understand(table)
    tables = [r for r in output["regions"] if r["kind"] == "table"]
    assert tables and tables[0]["content"]["rows"] >= 2
    assert tables[0]["content"]["cells"][0]["location"]["bbox"]
    assert tables[0]["status"] == "structure_unverified"
    assert validate_latex(r"\frac{1}{2").valid is False
    for latex in (
        r"\frac{1}{2}",
        r"\sqrt{x}",
        r"x^{2}",
        r"a_i",
        r"\int_0^1 x dx",
        r"\sum_{i=1}^n i",
        r"\begin{matrix}a&b\\c&d\end{matrix}",
    ):
        assert validate_latex(latex).valid


def test_backend_registry_selection():
    from idp.evidence.contracts import DeepDocCapability as C
    from idp.ocr.backends.errors import BackendUnavailable
    from idp.pdf.verify_runtime import AcquisitionBackendSpec, BackendRegistry

    specs = (
        AcquisitionBackendSpec("text", lambda out: None, (C.TEXT,), 1),
        AcquisitionBackendSpec("table", lambda out: None, (C.TEXT, C.TABLE), 3),
        AcquisitionBackendSpec(
            "offline", lambda out: None, (C.MATH,), 1, available=False
        ),
    )
    registry = BackendRegistry(acquisitions=specs)
    assert registry.select_acquisition("auto", (C.TEXT,)).name == "text"
    assert registry.select_acquisition("auto", (C.TABLE,)).name == "table"
    with pytest.raises(BackendUnavailable):
        registry.select_acquisition("offline", (C.MATH,))


def test_structured_adapter_preserves_unknown_confidence(tmp_path):
    from idp.evidence.serde import dump, load
    from idp.ocr.backends.advanced import AdvancedBackend, StructuredAcquisitionResult
    from idp.pdf.acquire import AcquisitionRequest
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page

    class RecordedTransport:
        backend = "marker"
        identity: ClassVar = {
            "backend": "marker",
            "unit_contract": "recorded-schema-not-real-inference",
        }

        def execute(self, image_bytes, *, deadline):
            return {
                "schema": "deepdoc-model-result:1",
                "backend": "marker",
                "packages": {"marker-pdf": "unit"},
                "weights_sha256": {},
                "input_sha256": hashlib.sha256(image_bytes).hexdigest(),
                "raw": {
                    "children": [
                        {
                            "bbox": [0, 0, 800, 1200],
                            "children": [
                                {
                                    "id": "t",
                                    "block_type": "Table",
                                    "bbox": [10, 10, 200, 100],
                                    "html": "<table><tr><th colspan='2'>Header</th></tr><tr><td>A</td><td>B</td></tr></table>",
                                },
                                {
                                    "id": "f",
                                    "block_type": "Equation",
                                    "bbox": [10, 120, 200, 160],
                                    "html": r"<math>\frac{1}{2}</math>",
                                },
                                {
                                    "id": "i",
                                    "block_type": "Picture",
                                    "bbox": [20, 200, 200, 300],
                                    "html": "HALLUCINATED model-only description",
                                },
                            ],
                        }
                    ]
                },
            }

    with PdfSource((FIX / "scan.pdf").read_bytes()) as source:
        image, frame = render_page(source, 1)
        result = AdvancedBackend(tmp_path, RecordedTransport()).read(
            image, source, 1, AcquisitionRequest("test", frame), deadline=1e20
        )
        assert isinstance(result, StructuredAcquisitionResult)
        assert len(result.proposals) == 3 and len(result.blocks) == 2
        assert all("HALLUCINATED" not in b.text for b in result.blocks)
        assert result.proposals[2]["origin"] == "model_inference"
        assert all(
            b.confidence == 0 and b.payload["recognition_confidence_available"] is False
            for b in result.blocks
        )
        assert load(dump(result)) == result


def test_models_unavailable_diagnostic(tmp_path):
    from idp.ocr.backends.advanced import DockerModelTransport
    from idp.ocr.backends.errors import BackendUnavailable

    with pytest.raises(BackendUnavailable):
        DockerModelTransport("deepdoc-deliberately-missing-image", "marker")


def test_v2_is_opt_in(tmp_path):
    v1 = DeepDocService(DeepDocConfig(engine="unified")).process_pdf(
        FIX / "native.pdf", tmp_path
    )
    assert v1["schema_version"] == "idp-canonical-1"
    assert DeepDocConfig().engine == "unified" and DeepDocConfig().canonical_version == 1


def test_question_context_survives_real_chunking(tmp_path):
    path = tmp_path / "questions.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=400)
        for y, text in (
            (70, "Question 1. What color is the synthetic cobalt crystal?"),
            (100, "A. Cobalt blue"),
            (130, "B. Orange"),
            (160, "C. Green"),
            (190, "D. White"),
        ):
            page.insert_text((30, y), text, fontsize=12)
        pdf.save(path)
    doc = DeepDocService(
        DeepDocConfig(engine="unified", canonical_version=2)
    ).process_pdf(path, tmp_path / "out")
    assert doc["structures"]["questions"]
    chunks = build_chunks(doc)
    question_chunks = [c for c in chunks if c["question_id"]]
    assert question_chunks
    assert (
        "Cobalt blue" in question_chunks[0]["text"]
        and "Orange" in question_chunks[0]["text"]
    )
    assert len(question_chunks[0]["references"]) >= 4


@pytest.mark.parametrize("status,released", [("needs_review", True), ("grouped_source", False)])
def test_incomplete_question_group_withholding(tmp_path, monkeypatch, status, released):
    """An unverified question guess must not hide publication-approved text.

    Regression for the DocVQA benchmark: a memo page was detected as a
    "lettered_question" (needs_review), publication dropped 11 of its 17
    blocks, and build_chunks then withheld the 6 approved blocks as well.
    """
    import retrieval.canonical_harness as harness

    path = tmp_path / "questions.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=400)
        for y, text in ((70, "Question 1. What color is the synthetic cobalt crystal?"),
                        (100, "A. Cobalt blue"), (130, "B. Orange")):
            page.insert_text((30, y), text, fontsize=12)
        pdf.save(path)
    doc = DeepDocService(
        DeepDocConfig(engine="unified", canonical_version=2)
    ).process_pdf(path, tmp_path / "out")
    blocks = list(iter_retrievable_blocks(doc))
    partial = copy.deepcopy(doc)
    group = partial["structures"]["questions"][0]
    group["status"] = status
    group["source_blocks"].append({"block_id": "ocr:withheld-by-publication"})
    monkeypatch.setattr(harness, "iter_retrievable_blocks",
                        lambda _: iter(copy.deepcopy(blocks)))
    chunks = build_chunks(partial)
    assert not any(c["question_id"] for c in chunks)
    text = "\n".join(c["text"] for c in chunks)
    assert ("Cobalt blue" in text) is released


@pytest.mark.parametrize("name,pages", [("scan.pdf", [1]), ("mixed.pdf", [2])])
def test_injected_ocr_v2_finalization_and_index(tmp_path, name, pages, monkeypatch):
    from idp_test_backends import FixtureOcr, use_ocr_backend

    use_ocr_backend(monkeypatch, FixtureOcr)
    doc = canonical(tmp_path / "out", name)
    report = json.loads((tmp_path / "out/run_report.json").read_text())
    assert report["ocr_pages"] == pages
    assert report["ocr_invocations"] == len(pages)
    assert all(
        b["verification_status"] != "proof_verified"
        for p in doc["pages"]
        for b in p["blocks"]
        if b["origin"] == "OCR"
    )
    index = LocalRagIndex(tmp_path / "index.sqlite3")
    index.index(doc)
    for hit in index.retrieve(
        "Native source evidence", actor="a", access_check=lambda *a: True
    ):
        assert resolve_citation(hit, doc)


def controlled_publication(tmp_path, confidence=0.95, *, duplicate=False, reread=False):
    from idp.evidence.contracts import DeepDocProducer
    from idp.pdf.acquire import AcquisitionResult, OcrBlock
    from idp.pdf.merge import EvidenceMerger
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.native.quality import PdfQualityPolicy
    from idp.pdf.profiling import profile_pages
    from idp.pdf.publication import assess_publication
    from idp.pdf.render import render_page
    from idp.pdf.router import PdfRouter
    from idp.publish import project_v2

    name = "native.pdf" if reread else "scan.pdf"
    with PdfSource((FIX / name).read_bytes()) as source:
        engine = PdfParsingEngine()
        native = engine.extract_native(source.data, source=source)
        _, frame = render_page(source, 1)
        box = (20, 20, 200, 50)
        target = None
        if reread:
            obs = native.observations[0]
            b = obs.locations[0].bbox
            box = frame.from_pdf_pt((b.x0, b.y0, b.x1, b.y1))
            target = obs.extraction.region.id
        blocks = [
            OcrBlock(
                "one",
                "SYNTHETIC withheld saffron sentence",
                box,
                confidence,
                target_region_id=target,
            )
        ]
        if duplicate:
            blocks.append(
                OcrBlock(
                    "two", "SYNTHETIC duplicate vermilion sentence", box, confidence
                )
            )
        result = AcquisitionResult(
            frame,
            DeepDocProducer("controlled-unit-ocr", "1"),
            "unit",
            "0" * 64,
            "unit:raw",
            "1" * 64,
            tuple(blocks),
        )
        prepared = EvidenceMerger().merge(native, (result,))
        record = engine.finalize(
            native,
            prepared=prepared,
            quality_policy=PdfQualityPolicy(version="pdf-quality-gate:2"),
        )
        plan = PdfRouter().route(native.admission.source_sha256, profile_pages(native))
        return project_v2(
            record, native, plan, assess_publication(record, plan), FIX / name
        )


@pytest.mark.parametrize("confidence", [0.59, 0.79])
def test_low_confidence_physically_absent_from_index_and_v1(tmp_path, confidence):
    doc = controlled_publication(tmp_path, confidence)
    assert "saffron" in json.dumps(doc)
    assert "saffron" not in json.dumps(to_v1(doc))
    index = LocalRagIndex(tmp_path / "rag.sqlite3")
    assert index.index(doc) == 0
    with sqlite3.connect(index.path) as con:
        assert con.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
    assert index.retrieve("saffron", actor="a", access_check=lambda *a: True) == []


def test_duplicate_and_disagreeing_ocr_never_replace_native(tmp_path):
    doc = controlled_publication(tmp_path, duplicate=True)
    text = " ".join(b["text"] for b in iter_retrievable_blocks(doc))
    assert "saffron" in text and "vermilion" not in text
    index = LocalRagIndex(tmp_path / "rag.sqlite3")
    index.index(doc)
    with sqlite3.connect(index.path) as con:
        assert "vermilion" not in str(
            con.execute("SELECT payload FROM chunks").fetchall()
        )
    reread = controlled_publication(tmp_path, reread=True)
    assert any(
        b["verification_status"] == "conflict_unresolved"
        for p in reread["pages"]
        for b in p["blocks"]
    )
    assert "saffron" not in json.dumps(to_v1(reread))
    assert "Independent expected text" in json.dumps(to_v1(reread))


def test_native_only_skips_every_backend_factory(tmp_path):
    from idp.evidence.contracts import DeepDocCapability
    from idp.pdf.verify_runtime import AcquisitionBackendSpec, BackendRegistry

    def forbidden(out):
        raise AssertionError("good native must not discover models")

    registry = BackendRegistry(
        acquisitions=(
            AcquisitionBackendSpec("marker", forbidden, (DeepDocCapability.TEXT,), 1),
        )
    )
    doc = DeepDocService(
        DeepDocConfig(engine="unified", canonical_version=2, ocr_backend="marker"),
        backend_registry=registry,
    ).process_pdf(FIX / "native.pdf", tmp_path)
    assert list(iter_retrievable_blocks(doc))


def test_container_timeout_forces_named_cleanup(tmp_path, monkeypatch):
    from idp.ocr.backends.advanced import DockerModelTransport
    from idp.ocr.backends.errors import OCRTimeout

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(command, 0, stdout="sha256:" + "1" * 64)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 1)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)
    transport = DockerModelTransport("unit:image", "marker", timeout_seconds=1)
    with pytest.raises(OCRTimeout):
        transport.execute(b"controlled-input", deadline=monotonic() + 5)
    started = next(c for c in calls if c[1] == "run")
    assert calls[-1] == ["docker", "rm", "-f", started[started.index("--name") + 1]]
    assert "--memory" in started and "--cpus" in started
    assert transport.identity["image_id"] in started
    assert not any("docker.sock" in arg for arg in started)


def test_quality_and_page_tamper_rejected(tmp_path):
    doc = controlled_publication(tmp_path, 0.59)
    block = doc["pages"][0]["blocks"][0]
    block["quality_reasons"] = []
    resign(doc)
    with pytest.raises(ValueError, match="quality reasons"):
        validate_canonical(doc)
    doc = canonical(tmp_path / "native")
    doc["pages"][0]["status"] = "review"
    resign(doc)
    with pytest.raises(ValueError, match="page routing"):
        validate_canonical(doc)
    with pytest.raises(ValueError):
        PublishPolicy(min_ocr_confidence=0.59)
    with pytest.raises(ValueError):
        DeepDocConfig(canonical_version=99)


def test_table_proposal_conflict_preserves_native_topology(tmp_path):
    from idp.evidence.contracts import DeepDocProducer
    from idp.ocr.backends.advanced import StructuredAcquisitionResult
    from idp.pdf.merge import EvidenceMerger
    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page
    from idp.pdf.understanding import understand
    from test_phase3 import spanning_table

    engine = PdfParsingEngine()
    with PdfSource(spanning_table()) as source:
        native = engine.extract_native(source.data, source=source)
        before = engine.finalize(native)
        table = next(r for r in understand(before)["regions"] if r["kind"] == "table")
        b = table["locations"][0]["bbox"]
        _, frame = render_page(source, 1)
        proposal = {
            "kind": "Table",
            "pixel_bbox": frame.from_pdf_pt([b[k] for k in ("x0", "y0", "x1", "y1")]),
            "table_html": "<table><tr><th colspan='2'>Wrong native shape</th></tr></table>",
        }
        result = StructuredAcquisitionResult(
            frame,
            DeepDocProducer("unit-proposal", "1"),
            "unit",
            "0" * 64,
            "unit:artifact",
            "1" * 64,
            proposals=(proposal,),
        )
        after = engine.finalize(
            native, prepared=EvidenceMerger().merge(native, (result,))
        )
        regions = understand(after)["regions"]
        assert next(r for r in regions if r["id"] == table["id"]) == table
        alternative = next(r for r in regions if r["origin"] == "ocr_proposal")
        assert alternative["status"] == "conflict_unresolved"
        assert table["id"] in alternative["alternative_to_native_regions"]
        assert alternative["table"]["cells"][0]["colspan"] == 2
        assert alternative["table"]["cell_geometry"] == "unavailable"


def test_completed_acquisition_verifier_is_append_only(tmp_path):
    from idp.ocr.backends.advanced import acquisition_verifier
    from idp.pdf.acquire import AcquisitionResult, OcrBlock
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page
    from idp.pdf.resource import ResourceLedger
    from idp.pdf.verify_runtime import BackendRegistry, IdpVerificationRuntime
    from test_phase2 import verification_fixture

    request, trace, producer = verification_fixture()
    with PdfSource((FIX / "native.pdf").read_bytes()) as source:
        _, frame = render_page(source, 1)
        b = trace.region.locations[0].bbox
        result = AcquisitionResult(
            frame,
            producer,
            "test",
            "0" * 64,
            "unit:artifact",
            "1" * 64,
            (
                OcrBlock(
                    "reread",
                    "Independent unit transcription",
                    frame.from_pdf_pt((b.x0, b.y0, b.x1, b.y1)),
                    0.9,
                ),
            ),
        )
        backend = acquisition_verifier(result, capabilities=(request.capability,))
        ledger = ResourceLedger(monotonic() + 10)
        response = IdpVerificationRuntime(BackendRegistry((backend,)), ledger).execute(
            request, trace, timeout_seconds=2
        )
        assert response.trace.candidates[:-1] == trace.candidates
        assert response.trace.evidence[:-1] == trace.evidence
        assert response.trace.source_candidate_id == trace.source_candidate_id
        assert response.trace.candidates[-1].text == "Independent unit transcription"
        assert ledger.calls == 1


def test_two_source_captions_and_missing_caption(tmp_path):
    from io import BytesIO

    from idp.pdf.native.engine import PdfParsingEngine
    from idp.pdf.understanding import understand
    from PIL import Image

    with fitz.open() as pdf:
        page = pdf.new_page(width=600, height=800)
        page.insert_text(
            (25, 40),
            "Independent source document with three figures for caption association.",
        )
        for i, y in enumerate((80, 300, 520), 1):
            stream = BytesIO()
            Image.new("RGB", (160, 100), (i * 60, 20, 30)).save(stream, format="PNG")
            page.insert_image(fitz.Rect(60, y, 220, y + 100), stream=stream.getvalue())
            if i < 3:
                page.insert_text(
                    (60, y + 118), f"Figure {i}. Source caption {i}.", fontsize=10
                )
        record = PdfParsingEngine().extract_source(pdf.tobytes())
    figures = [r for r in understand(record)["regions"] if r["kind"] == "figure"]
    assert len(figures) == 3
    texts = [r["text"] for f in figures for r in f["caption_references"]]
    assert texts == ["Figure 1. Source caption 1.", "Figure 2. Source caption 2."]
    assert figures[2]["caption_references"] == []


def test_citation_rejects_appended_hallucination_and_nested_version(tmp_path):
    doc = canonical(tmp_path / "out")
    index = LocalRagIndex(tmp_path / "index.sqlite3")
    index.index(doc)
    hit = index.retrieve("Independent", actor="a", access_check=lambda *a: True)[0]
    altered = copy.deepcopy(hit)
    altered["text"] += " invented unsupported answer"
    with pytest.raises(ValueError):
        resolve_citation(altered, doc)
    hit["references"][0]["document_version"] = "fake-version"
    with pytest.raises(ValueError):
        resolve_citation(hit, doc)


def test_auto_backend_skips_unusable_factory_without_explicit_fallback(tmp_path):
    from idp.evidence.contracts import DeepDocCapability
    from idp.ocr.backends.errors import BackendUnavailable
    from idp.pdf.verify_runtime import AcquisitionBackendSpec, BackendRegistry

    calls = []

    def unavailable(out):
        calls.append("unavailable")
        raise BackendUnavailable("unit runtime absent")

    def usable(out):
        calls.append("usable")
        return object()

    registry = BackendRegistry(
        acquisitions=(
            AcquisitionBackendSpec("cheap", unavailable, (DeepDocCapability.TEXT,), 1),
            AcquisitionBackendSpec("available", usable, (DeepDocCapability.TEXT,), 2),
        )
    )
    descriptor, _ = registry.create_acquisition(
        "auto", (DeepDocCapability.TEXT,), tmp_path
    )
    assert descriptor.name == "available" and calls == ["unavailable", "usable"]
    calls.clear()
    with pytest.raises(BackendUnavailable):
        registry.create_acquisition("cheap", (DeepDocCapability.TEXT,), tmp_path)
    assert calls == ["unavailable"]
