"""Diagnostic native-only spike. Does not dispatch OCR or production ingestion."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from idp.pdf.native.engine import PdfParsingEngine
from idp.pdf.native.preflight import PdfAdmissionError, PdfAdmissionPolicy, PdfSource


def run_native_spike(
    data: bytes,
    *,
    policy: PdfAdmissionPolicy | None = None,
    finalize_native: bool = True,
) -> dict[str, object]:
    """Keep one owned session across admission, native extraction and finalize.

    Page previews are advisory signals, not the future production router. A
    text-bearing page with an embedded image still needs Phase 2 region review.
    """
    engine = PdfParsingEngine()
    with PdfSource(data, policy) as source:
        native = engine.extract_native(data, source=source)
        pages = []
        for geometry, facts in zip(native.geometry, native.pages, strict=True):
            if facts.native_text_char_count:
                preview, reason = "NATIVE_CANDIDATE", "NATIVE_TEXT_PRESENT"
            elif facts.image_resource_count:
                preview, reason = "OCR_REQUIRED", "IMAGE_RESOURCES_WITHOUT_NATIVE_TEXT"
            else:
                preview, reason = (
                    "NO_NATIVE_CONTENT_REVIEW",
                    "NO_NATIVE_TEXT_NOT_PROOF_OF_BLANK",
                )
            pages.append(
                {
                    "geometry": asdict(geometry),
                    "facts": asdict(facts),
                    "preview": preview,
                    "reason": reason,
                }
            )
        finalized = (
            engine.finalize(native, source=source)
            if finalize_native and not native.empty
            else None
        )
        return {
            "source_sha256": native.admission.source_sha256,
            "admission": asdict(native.admission),
            "page_count": native.page_count,
            "empty": native.empty,
            "native_text_count": len(native.observations),
            "native_figure_count": len(native.figures),
            "figure_status": native.figure_status,
            "pages": pages,
            "diagnostics": [item.code for item in native.diagnostics],
            "ocr_used": False,
            "finalized": finalized is not None,
            "observation_ids": [o.source_id for o in finalized.observations]
            if finalized
            else [],
            "gate_actions": [
                str(a.action) for a in finalized.manifest.quality_gate.assessments
            ]
            if finalized
            else [],
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--no-finalize", action="store_true")
    args = parser.parse_args()
    try:
        summary = run_native_spike(
            args.pdf.read_bytes(), finalize_native=not args.no_finalize
        )
    except PdfAdmissionError as error:
        print(
            json.dumps({"error": error.diagnostic.code, "message": str(error)}),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
