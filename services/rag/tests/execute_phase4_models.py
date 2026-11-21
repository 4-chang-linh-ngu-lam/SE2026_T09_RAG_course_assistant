"""Explicit opt-in real model execution; never collected as a core/mock test.

Build Dockerfile.phase4-models first. Models use local Docker named volumes.
Independent draw commands supply ground truth, never OCR output itself.
"""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from time import monotonic

import fitz
from idp.evidence.contracts import DeepDocCapability, DeepDocWorkRequest
from idp.ocr.backends.advanced import (
    AdvancedBackend,
    DockerModelTransport,
    acquisition_verifier,
)
from idp.pdf.acquire import AcquisitionRequest, BackendAcquirer
from idp.pdf.merge import EvidenceMerger
from idp.pdf.native.engine import PdfParsingEngine
from idp.pdf.native.evidence import input_fingerprint
from idp.pdf.native.preflight import PdfAdmissionPolicy, PdfSource
from idp.pdf.native.quality import PdfQualityPolicy
from idp.pdf.profiling import profile_pages
from idp.pdf.publication import assess_publication
from idp.pdf.render import digest, render_page
from idp.pdf.resource import ResourceLedger
from idp.pdf.router import PdfRouter
from idp.publish import iter_retrievable_blocks, project_v2, to_v1


def fixture():
    with fitz.open() as pdf:
        page = pdf.new_page(width=400, height=400)
        page.insert_text(
            (25, 40),
            "Synthetic source table for independent OCR evaluation",
            fontsize=12,
        )
        for y in (80, 120, 160):
            page.draw_line((30, y), (350, y))
        for x in (30, 190, 350):
            page.draw_line((x, 80), (x, 160))
        for row, values in enumerate(
            (("Element", "Reagent"), ("Cerium", "Nitrate"))
        ):
            for column, text in enumerate(values):
                page.insert_text(
                    (40 + column * 160, 105 + row * 40), text, fontsize=18
                )
        image = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
        with fitz.open() as scan:
            scan.new_page(width=page.rect.width, height=page.rect.height).insert_image(
                page.rect, stream=image
            )
            return scan.tobytes()


def execute(out, backends, timeout):
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    for name in backends:
        directory = out / name
        directory.mkdir(exist_ok=True)
        started = monotonic()
        try:
            data = fixture()
            (directory / "source.pdf").write_bytes(data)
            with PdfSource(
                data, PdfAdmissionPolicy(timeout_seconds=timeout + 60)
            ) as source:
                engine = PdfParsingEngine()
                native = engine.extract_native(data, source=source)
                ledger = ResourceLedger(
                    monotonic() + timeout, max_calls=4, max_pixels=4_000_000
                )
                # Precharge the bounded render before allocating pixels.
                ledger.reserve_render("model-fixture", 800 * 800)
                image, frame = render_page(source, 1, dpi=144, max_pixels=1_000_000)
                (directory / "input.png").write_bytes(image)
                image_tag = (
                    "lumi-rag-marker:phase4"
                    if name == "marker"
                    else "lumi-rag-paddle:phase4"
                )
                transport = DockerModelTransport(
                    image_tag, name, timeout_seconds=timeout, memory="5g", cpus=2
                )
                backend = AdvancedBackend(directory / "raw", transport)
                acquirer = BackendAcquirer(
                    lambda s, p, plan, deadline, backend=backend, image=image: (
                        backend.read(image, s, p, plan, deadline=deadline)
                    ),
                    ledger,
                    render_precharged=True,
                )
                result = acquirer.acquire_page(
                    source,
                    1,
                    AcquisitionRequest("real-model-execution", frame),
                    deadline=ledger.deadline,
                )
                assert result.proposals, "no structured model output"
                raw = json.loads(Path(result.artifact_ref).read_text(encoding="utf-8"))
                assert raw["weights_sha256"], "active model weight identity missing"
                prepared = EvidenceMerger().merge(native, (result,))
                record = engine.finalize(
                    native,
                    source=source,
                    prepared=prepared,
                    quality_policy=PdfQualityPolicy(version="pdf-quality-gate:2"),
                )
                plan = PdfRouter().route(
                    native.admission.source_sha256, profile_pages(native)
                )
                canonical = project_v2(
                    record,
                    native,
                    plan,
                    assess_publication(record, plan),
                    directory / "source.pdf",
                    document_version="synthetic-model:1",
                )
                (directory / "canonical.json").write_text(
                    json.dumps(canonical, ensure_ascii=False), encoding="utf-8"
                )
                assert not list(iter_retrievable_blocks(canonical)), (
                    "unknown-confidence model transcription leaked"
                )
                assert not any(p["blocks"] for p in to_v1(canonical)["pages"])
                verification = "NO_TEXT_BLOCKS"
                if result.blocks:
                    trace = native.figures[0].extraction
                    candidate = next(
                        c for c in trace.candidates if c.id == trace.source_candidate_id
                    )
                    fingerprint = input_fingerprint(
                        trace,
                        candidate,
                        result.config_sha256,
                        PdfQualityPolicy(version="pdf-quality-gate:2").fingerprint,
                    )
                    identity = {
                        "source": source.report.source_sha256,
                        "input": fingerprint,
                        "capability": DeepDocCapability.TEXT,
                        "operation": "VERIFY",
                        "producer": asdict(result.producer),
                        "family": result.family,
                        "resource": "CPU",
                        "ordinal": 1,
                    }
                    request = DeepDocWorkRequest(
                        "work:" + digest(identity),
                        identity["source"],
                        fingerprint,
                        trace.region.id,
                        trace.region.id,
                        candidate.id,
                        DeepDocCapability.TEXT,
                        "VERIFY",
                        "CPU",
                        result.producer,
                        result.family,
                        1,
                        len(trace.candidates),
                        len(trace.evidence),
                        len(trace.decisions),
                    )
                    from idp.pdf.verify_runtime import (
                        BackendRegistry,
                        IdpVerificationRuntime,
                    )

                    adapter = acquisition_verifier(
                        result, capabilities=(DeepDocCapability.TEXT,)
                    )
                    response = IdpVerificationRuntime(
                        BackendRegistry((adapter,)), ledger
                    ).execute(request, trace, timeout_seconds=10)
                    assert response.trace is not None
                    assert (
                        response.trace.source_candidate_id == trace.source_candidate_id
                    )
                    assert (
                        response.trace.candidates[: len(trace.candidates)]
                        == trace.candidates
                    )
                    verified_prepared = EvidenceMerger().merge(
                        native, verifications=(response,)
                    )
                    verified_record = engine.finalize(
                        native, prepared=verified_prepared
                    )
                    assert verified_record.observations
                    verification = "APPEND_ONLY_PASS_NO_LEXICAL_PROOF"
                results[name] = {
                    "status": "PASS",
                    "packages": raw["packages"],
                    "weights_sha256": raw["weights_sha256"],
                    "image": transport.identity,
                    "input_sha256": raw["input_sha256"],
                    "model_seconds": raw["seconds"],
                    "blocks": len(result.blocks),
                    "proposals": len(result.proposals),
                    "structures": len(canonical["structures"]["regions"]),
                    "published_blocks": 0,
                    "verification_runtime": verification,
                    "raw_artifact_sha256": result.artifact_sha256,
                    "seconds": monotonic() - started,
                }
        except Exception as error:  # noqa: BLE001 - report real failure; never substitute another backend.
            results[name] = {
                "status": "FAILED",
                "error": type(error).__name__,
                "detail": str(error),
                "seconds": monotonic() - started,
            }
        (out / "model-execution.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "backend": name,
                    **{
                        k: v
                        for k, v in results[name].items()
                        if k
                        in {
                            "status",
                            "error",
                            "detail",
                            "seconds",
                        }
                    },
                }
            ),
            flush=True,
        )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--backends",
        nargs="+",
        choices=("marker", "paddle-vl"),
        required=True,
    )
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    results = execute(args.out, args.backends, args.timeout)
    raise SystemExit(any(r["status"] != "PASS" for r in results.values()))
