import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path
from time import monotonic

import pytest
from idp.evidence.contracts import DeepDocProducer
from idp.evidence.serde import dump, load
from idp.pdf.acquire import (
    AcquisitionRequest,
    AcquisitionResult,
    BackendAcquirer,
    OcrBlock,
)
from idp.pdf.geometry import Affine, corners
from idp.pdf.merge import ContractViolation, EvidenceMerger
from idp.pdf.native.engine import PdfParsingEngine
from idp.pdf.native.preflight import PdfSource
from idp.pdf.render import TransformStep, render_page
from idp.pdf.resource import BudgetExceeded, ResourceLedger

FIX = Path(__file__).parent / "fixtures/generated"


@pytest.mark.parametrize("angle", [0, 3, -3, 90, 180, 270])
def test_affine_roundtrip(angle):
    r = math.radians(angle)
    a = Affine(math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 20, 30) @ Affine(
        a=2, d=3
    )
    for p in corners((1, 2, 40, 60)):
        assert a.inverse().apply(*a.apply(*p)) == pytest.approx(p, abs=1e-9)
    with pytest.raises(ValueError):
        Affine(a=0, d=0)
    with pytest.raises(ValueError):
        a.apply(float("nan"), 0)


@pytest.mark.parametrize("name", ["native.pdf", "rotated_cropbox.pdf"])
def test_real_render_frame(name):
    with PdfSource((FIX / name).read_bytes()) as source:
        data, frame = render_page(source, 1, dpi=144, max_pixels=200000)
        assert hashlib.sha256(data).hexdigest() == frame.steps[0].output_sha256
        box = (30, 40, 100, 120)
        assert frame.to_pdf_pt(frame.from_pdf_pt(box)) == pytest.approx(box, abs=1)
        assert (
            render_page(source, 1, dpi=144, max_pixels=200000)[1].render_id
            == frame.render_id
        )
        step = TransformStep("crop", Affine(e=-10, f=-20), {}, (100, 100), "0" * 64)
        assert frame.append(step).render_id != frame.render_id


@pytest.mark.parametrize("name", ["native.pdf", "scan.pdf", "mixed.pdf"])
def test_prepared_integration(name):
    engine = PdfParsingEngine()
    data = (FIX / name).read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        page = native.page_count
        _, frame = render_page(source, page)
        block = OcrBlock(
            "line:1",
            "Controlled OCR test content",
            (40, 400, 200, 440),
            0.9,
            payload={
                "table_html": "<table><tr><td>A</td></tr></table>",
                "latex": "x^2",
            },
        )
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test-ocr", "1"),
            "test",
            "0" * 64,
            "fixture:raw",
            "1" * 64,
            (block,),
        )
        prepared = EvidenceMerger().merge(native, (result, result))
        assert len(prepared.acquisitions) == 1
        final = engine.finalize(native, source=source, prepared=prepared)
        assert any(o.text == block.text for o in final.observations)
        assert load(dump(final)) == final
        assert load(dump(prepared)) == prepared
        assert (
            final.attributes["ocr_proposals"][0]["blocks"][0]["payload"]["latex"]
            == "x^2"
        )
        with pytest.raises(ContractViolation):
            EvidenceMerger().merge(
                native, (replace(result, frame=replace(frame, source_sha256="f" * 64)),)
            )


def test_reread_preserves_native():
    engine = PdfParsingEngine()
    data = (FIX / "native.pdf").read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        target = native.observations[0]
        _, frame = render_page(source, 1)
        loc = target.locations[0]
        b = loc.bbox
        box = frame.from_pdf_pt((b.x0, b.y0, b.x1, b.y1))
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test-ocr", "1"),
            "test",
            "0" * 64,
            "raw:test",
            "1" * 64,
            (
                OcrBlock(
                    "line",
                    "Different OCR alternative",
                    box,
                    0.8,
                    target_region_id=target.extraction.region.id,
                ),
            ),
        )
        prepared = EvidenceMerger().merge(native, (result,))
        updated = prepared.observations[0]
        assert updated.text == target.text
        assert updated.extraction.raw_candidate_id == target.extraction.raw_candidate_id
        assert (
            updated.extraction.source_candidate_id
            == target.extraction.source_candidate_id
        )
        assert updated.extraction.evidence[:-1] == target.extraction.evidence
        assert (
            len(updated.extraction.candidates) == len(target.extraction.candidates) + 1
        )
        final = engine.finalize(native, prepared=prepared, source=source)
        assert load(dump(final)) == final


def test_budget_and_serde_fail_closed():
    ledger = ResourceLedger(monotonic() + 10, max_calls=1)
    ledger.reserve("first")
    ledger.settle("first", False)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("second")
    with pytest.raises(BudgetExceeded):
        ledger.reserve("first")
    with pytest.raises(ValueError):
        load('{"format":"unknown"}')
    with pytest.raises(ValueError):
        load("{bad")
    with pytest.raises(TypeError):
        dump(object())


def test_empty_scan_acquisition(monkeypatch):
    from idp.pdf.native import engine as module

    monkeypatch.setattr(module, "extract_pdf_figures", lambda *a, **k: ((), ()))
    engine = PdfParsingEngine()
    data = (FIX / "scan.pdf").read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        assert native.empty
        _, frame = render_page(source, 1)
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test-ocr", "1"),
            "test",
            "0" * 64,
            "raw:test",
            "1" * 64,
            (OcrBlock("one", "Acquired scan content", (10, 10, 100, 30), 0.9),),
        )
        ledger = ResourceLedger(monotonic() + 10)
        acquirer = BackendAcquirer(lambda *a, **k: result, ledger)
        actual = acquirer.acquire_page(
            source, 1, AcquisitionRequest("first", frame), deadline=monotonic() + 5
        )
        prepared = EvidenceMerger().merge(native, (actual,))
        final = engine.finalize(native, prepared=prepared, source=source)
        assert final.observations[0].text == "Acquired scan content"
        assert load(dump(final)) == final


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_render_actual_colored_region(rotation):
    from io import BytesIO

    import fitz
    from PIL import Image

    with fitz.open() as doc:
        page = doc.new_page(width=400, height=600)
        page.draw_rect(fitz.Rect(100, 150, 200, 250), color=(1, 0, 0), fill=(1, 0, 0))
        page.set_cropbox(fitz.Rect(20, 30, 380, 570))
        page.set_rotation(rotation)
        # Independent PDF geometry calculation in PyMuPDF.
        expected = fitz.Rect(80, 120, 180, 220) * page.rotation_matrix
        data = doc.tobytes()
    with PdfSource(data) as source:
        png, frame = render_page(source, 1, dpi=144)
        with Image.open(BytesIO(png)) as image:
            point = frame.matrix.apply(
                (expected.x0 + expected.x1) / 2, (expected.y0 + expected.y1) / 2
            )
            color = image.convert("RGB").getpixel(tuple(round(v) for v in point))
            assert color[0] > 240 and color[1] < 20 and color[2] < 20
            import numpy as np

            pixels = np.asarray(image.convert("RGB"))
            ys, xs = np.where(
                (pixels[:, :, 0] > 240)
                & (pixels[:, :, 1] < 20)
                & (pixels[:, :, 2] < 20)
            )
            measured = frame.to_pdf_pt(
                (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
            )
            assert measured == pytest.approx(tuple(expected), abs=1)

        assert frame.to_pdf_pt(frame.from_pdf_pt(tuple(expected))) == pytest.approx(
            tuple(expected), abs=1
        )


def verification_fixture():
    from idp.evidence.contracts import DeepDocCapability, DeepDocWorkRequest
    from idp.pdf.native.contracts import _fingerprint

    trace = (
        PdfParsingEngine()
        .extract_native((FIX / "native.pdf").read_bytes())
        .observations[0]
        .extraction
    )
    producer = DeepDocProducer("verification-test", "1")
    identity = {
        "source": trace.evidence[0].source_sha256,
        "input": "0" * 64,
        "capability": DeepDocCapability.TEXT,
        "operation": "VERIFY",
        "producer": {
            "name": producer.name,
            "version": producer.version,
            "model": None,
            "prompt_sha256": None,
        },
        "family": "test",
        "resource": "CPU",
        "ordinal": 1,
    }
    request = DeepDocWorkRequest(
        "work:" + _fingerprint(identity),
        identity["source"],
        identity["input"],
        trace.region.id,
        trace.region.id,
        trace.source_candidate_id,
        DeepDocCapability.TEXT,
        "VERIFY",
        "CPU",
        producer,
        "test",
        1,
        len(trace.candidates),
        len(trace.evidence),
        len(trace.decisions),
    )
    return request, trace, producer


def test_verification_shared_ledger_and_failure():
    from idp.pdf.native.engine import PdfWorkResponse
    from idp.pdf.verify_runtime import (
        BackendRegistry,
        IdpVerificationRuntime,
        VerificationBackend,
    )

    request, trace, producer = verification_fixture()
    ledger = ResourceLedger(monotonic() + 10, max_calls=2)
    ledger.reserve("acquisition")
    ledger.settle("acquisition", True)
    backend = VerificationBackend(
        producer,
        "test",
        (request.capability,),
        lambda req, tr, **kw: PdfWorkResponse(
            req.id, req.input_sha256, reroute_to=req.capability
        ),
    )
    runtime = IdpVerificationRuntime(BackendRegistry((backend,)), ledger)
    assert runtime.execute(request, trace, timeout_seconds=1).request_id == request.id
    with pytest.raises(BudgetExceeded):
        runtime.execute(request, trace, timeout_seconds=1)
    with pytest.raises(TypeError):
        runtime.execute(request, None, timeout_seconds=1)
    with pytest.raises(LookupError):
        IdpVerificationRuntime(
            BackendRegistry(), ResourceLedger(monotonic() + 1)
        ).execute(request, trace, timeout_seconds=1)


def test_zero_failed_duplicate_and_invalid_merge():
    engine = PdfParsingEngine()
    data = (FIX / "native.pdf").read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        _, frame = render_page(source, 1)
        zero = AcquisitionResult(
            frame,
            DeepDocProducer("test", "1"),
            "test",
            "0" * 64,
            "artifact:test",
            "1" * 64,
        )
        no_op = EvidenceMerger().merge(native)
        assert engine.finalize(native, prepared=no_op) == engine.finalize(native)
        assert (
            EvidenceMerger().merge(native, (zero,)).observations == no_op.observations
        )
        failed = replace(zero, success=False)
        assert (
            EvidenceMerger().merge(native, (failed,)).observations == no_op.observations
        )
        with pytest.raises(ContractViolation):
            EvidenceMerger().merge(
                native, (zero, replace(zero, artifact_sha256="2" * 64))
            )
        invalid = replace(
            zero, blocks=(OcrBlock("bad", "text", (-10, 0, 100, 20), 0.8),)
        )
        with pytest.raises(ContractViolation):
            EvidenceMerger().merge(native, (invalid,))
        target = replace(
            zero,
            blocks=(
                OcrBlock(
                    "bad",
                    "text",
                    (10, 10, 100, 20),
                    0.8,
                    target_region_id="region:missing",
                ),
            ),
        )
        with pytest.raises(ContractViolation):
            EvidenceMerger().merge(native, (target,))
        wire = json.loads(dump(no_op))
        wire["contract"] = "999"
        with pytest.raises(ValueError):
            load(json.dumps(wire))


def test_acquisition_timeout_and_failed_settlement():
    data = (FIX / "scan.pdf").read_bytes()
    with PdfSource(data) as source:
        _, frame = render_page(source, 1)
        plan = AcquisitionRequest("deadline", frame)
        ledger = ResourceLedger(monotonic() + 1)

        def fail(*a, **kw):
            raise RuntimeError("backend failure")

        acquirer = BackendAcquirer(fail, ledger)
        with pytest.raises(RuntimeError):
            acquirer.acquire_page(source, 1, plan, deadline=monotonic() + 1)
        assert ledger.calls == 1 and ledger._items["deadline"] == "failed"
        with pytest.raises(TimeoutError):
            acquirer.acquire_page(
                source, 1, replace(plan, key="expired"), deadline=monotonic() - 1
            )


@pytest.mark.parametrize(
    "kind,matrix,size",
    [
        ("crop", Affine(e=-20, f=-30), (400, 500)),
        ("resize", Affine(a=0.5, d=0.5), (400, 600)),
        ("padding", Affine(e=20, f=30), (840, 1260)),
        ("orientation", Affine(0, 1, -1, 0, 1200, 0), (1200, 800)),
        ("exif", Affine(-1, 0, 0, 1, 800, 0), (800, 1200)),
        (
            "deskew",
            Affine(
                math.cos(0.05), math.sin(0.05), -math.sin(0.05), math.cos(0.05), 60, 0
            ),
            (900, 1300),
        ),
    ],
)
def test_real_preprocessing_provenance(kind, matrix, size):
    from idp.pdf.render import transform_image

    with PdfSource((FIX / "native.pdf").read_bytes()) as source:
        data, frame = render_page(source, 1)
        output, processed = transform_image(
            data, frame, kind=kind, matrix=matrix, output_size=size
        )
        assert processed.steps[-1].output_sha256 == hashlib.sha256(output).hexdigest()
        for point in ((50, 80), (100, 120)):
            assert processed.matrix.inverse().apply(
                *processed.matrix.apply(*point)
            ) == pytest.approx(point, abs=1)
        assert processed.render_id != frame.render_id
        with pytest.raises(ValueError):
            transform_image(b"wrong", frame, kind=kind, matrix=matrix, output_size=size)


def test_ambiguous_native_matching_retains_review():
    engine = PdfParsingEngine()
    data = (FIX / "native.pdf").read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        _, frame = render_page(source, 1)
        bbox = frame.from_pdf_pt((20, 20, 380, 160))
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test", "1"),
            "test",
            "0" * 64,
            "raw:test",
            "1" * 64,
            (OcrBlock("multi", "OCR grouped native lines", bbox, 0.7),),
        )
        prepared = EvidenceMerger().merge(native, (result,))
        assert prepared.observations[: len(native.observations)] == native.observations
        assert prepared.observations[-1].attributes["matching_review"] is True
        assert any(d.code == "OCR_MATCH_AMBIGUOUS" for d in prepared.diagnostics)


@pytest.mark.parametrize("resource", ["GPU", "REMOTE", "UNKNOWN"])
def test_resource_failure_is_closed(resource):
    ledger = ResourceLedger(monotonic() + 1)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("unavailable", resource=resource)
    assert ledger.calls == 0


def test_verification_evidence_is_admitted_append_only():
    from idp.evidence.contracts import (
        DeepDocCandidate,
        DeepDocContentOrigin,
        DeepDocEvidence,
    )
    from idp.pdf.native.engine import PdfWorkResponse
    from idp.pdf.verify_runtime import (
        BackendRegistry,
        IdpVerificationRuntime,
        VerificationBackend,
    )

    request, trace, producer = verification_fixture()
    evidence = DeepDocEvidence(
        "evidence:verify",
        trace.region.id,
        DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
        producer,
        request.input_sha256,
        request.source_sha256,
        independence_family="test",
    )
    candidate = DeepDocCandidate(
        "candidate:verify",
        trace.region.id,
        evidence.origin,
        producer,
        (evidence.id,),
        "Verified backend alternative",
    )
    updated = replace(
        trace,
        evidence=(*trace.evidence, evidence),
        candidates=(*trace.candidates, candidate),
    )
    response = PdfWorkResponse(request.id, request.input_sha256, trace=updated)
    backend = VerificationBackend(
        producer, "test", (request.capability,), lambda *a, **kw: response
    )
    runtime = IdpVerificationRuntime(
        BackendRegistry((backend,)), ResourceLedger(monotonic() + 5)
    )
    assert runtime.execute(request, trace, timeout_seconds=1) == response
    native = PdfParsingEngine().extract_native((FIX / "native.pdf").read_bytes())
    prepared = EvidenceMerger().merge(native, verifications=(response,))
    assert prepared.observations[0].extraction == updated
    assert load(dump(prepared)) == prepared


@pytest.mark.parametrize("tamper", ["missing", "enum", "source", "duplicate", "bbox"])
def test_hostile_serialization_rejected(tamper):
    record = PdfParsingEngine().extract_source((FIX / "native.pdf").read_bytes())
    wire = json.loads(dump(record))

    def find(value, predicate):
        if isinstance(value, dict):
            if predicate(value):
                return value
            for nested in value.values():
                found = find(nested, predicate)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for nested in value:
                found = find(nested, predicate)
                if found is not None:
                    return found
        return None

    if tamper == "missing":
        wire["record"]["fields"].pop("observations")
    elif tamper == "enum":
        find(wire, lambda d: "enum" in d)["value"] = "UNKNOWN"
    elif tamper == "source":
        find(wire, lambda d: d.get("type", "").endswith("DeepDocEvidence"))["fields"][
            "source_sha256"
        ] = "f" * 64
    elif tamper == "bbox":
        find(wire, lambda d: d.get("type", "").endswith("DeepDocBoundingBox"))[
            "fields"
        ]["x1"] = -1
    else:
        observations = wire["record"]["fields"]["observations"]["tuple"]
        observations.append(observations[0])
    with pytest.raises((ValueError, TypeError)):
        load(json.dumps(wire))


def test_shared_page_budget():
    ledger = ResourceLedger(monotonic() + 1, max_calls_per_page=1)
    ledger.reserve("acquire", page=1)
    ledger.settle("acquire", True)
    with pytest.raises(BudgetExceeded):
        ledger.reserve("verify", page=1)
    ledger.reserve("other-page", page=2)
    assert ledger.calls == 2


@pytest.mark.parametrize(
    "fixture,label",
    [("columns.pdf", "PARAGRAPH"), ("table.pdf", "TABLE"), ("formula.pdf", "FORMULA")],
)
def test_structural_context_matching_and_payload(fixture, label):
    engine = PdfParsingEngine()
    data = (FIX / fixture).read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        target = native.observations[0]
        _, frame = render_page(source, 1)
        loc = target.locations[0]
        b = loc.bbox
        small = (b.x0 + 1, b.y0 + 1, (b.x0 + b.x1) / 2, b.y1 - 1)
        block = OcrBlock(
            "small",
            "Controlled sub-line",
            frame.from_pdf_pt(small),
            0.8,
            label=label,
            payload={"html": "<table/>", "latex": "x^2"},
        )
        result = AcquisitionResult(
            frame,
            DeepDocProducer("test", "1"),
            "test",
            "0" * 64,
            "raw:structured",
            "1" * 64,
            (block,),
        )
        prepared = EvidenceMerger().merge(native, (result,))
        assert prepared.observations[0].text == target.text
        assert len(prepared.observations[0].extraction.candidates) > len(
            target.extraction.candidates
        )
        final = engine.finalize(native, prepared=prepared, source=source)
        acquisition = load(final.attributes["ocr_proposals"][0]["record_json"])
        assert acquisition.blocks[0].payload["latex"] == "x^2"
        assert acquisition.blocks[0].label == label


def test_backend_post_return_timeout_is_failed(monkeypatch):
    import idp.pdf.verify_runtime as module
    from idp.pdf.native.engine import PdfWorkResponse

    request, trace, producer = verification_fixture()

    def expired(*args, **kwargs):
        monkeypatch.setattr(module, "monotonic", lambda: 1e20)
        return PdfWorkResponse(
            request.id, request.input_sha256, reroute_to=request.capability
        )

    backend = module.VerificationBackend(
        producer, "test", (request.capability,), expired
    )
    ledger = ResourceLedger(monotonic() + 5)
    runtime = module.IdpVerificationRuntime(module.BackendRegistry((backend,)), ledger)
    with pytest.raises(TimeoutError):
        runtime.execute(request, trace, timeout_seconds=1)
    assert ledger._items[request.id] == "failed"
