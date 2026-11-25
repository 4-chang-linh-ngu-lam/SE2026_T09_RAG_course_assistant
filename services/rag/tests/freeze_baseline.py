"""Explicit pre-fix capture. Refuses to replace a frozen baseline."""

import hashlib
import importlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tests/fixtures")]
from generate import generate
from test_phase0 import snapshot


def main():
    target = ROOT / "tests/golden"
    completing = "--complete-environment" in sys.argv
    if (target / "source.json").exists() and not completing:
        raise SystemExit("Baseline already frozen")
    target.mkdir(parents=True, exist_ok=True)
    files = [p for package in ("idp", "parser") for p in (ROOT / package).rglob("*.py")]
    sources = {
        str(p.relative_to(ROOT)).replace("\\", "/"): hashlib.sha256(
            p.read_bytes()
        ).hexdigest()
        for p in files
    }
    if completing:
        assert sources == json.loads((target / "source.json").read_text()), (
            "Source changed after freeze"
        )
    else:
        (target / "source.json").write_text(json.dumps(sources, indent=2))
    fixture_dir = ROOT / "tests/fixtures/generated"
    manifest = (
        json.loads((ROOT / "tests/fixtures/manifest.json").read_text())
        if completing
        else generate(fixture_dir)
    )
    (ROOT / "tests/fixtures/manifest.json").write_text(json.dumps(manifest, indent=2))
    signatures = {}
    for module, attributes in {
        "idp.ingest": ["ingest_file"],
        "idp.documents.digital": ["process"],
        "idp.orchestration.pipeline": ["run_pipeline", "run_ingestion"],
        "idp.canonical": ["build_canonical", "audit_canonical"],
        "idp.orchestration.worker": [
            "IngestionWorker.__init__",
            "JobRequest.from_dict",
        ],
        "parser.pdf.engine": ["PdfParsingEngine.extract_source"],
    }.items():
        imported = importlib.import_module(module)
        for attribute in attributes:
            value = imported
            for part in attribute.split("."):
                value = getattr(value, part)
            signatures[f"{value.__module__}.{value.__qualname__}"] = str(
                inspect.signature(value)
            )
    (target / "signatures.json").write_text(json.dumps(signatures, indent=2))
    import tempfile

    expected = {}
    for item in manifest:
        for kind in ["digital", "ingest", "parser"]:
            if kind == "parser" and not item["filename"].endswith(".pdf"):
                continue
            # Scan ingestion needs an external OCR engine; capture its native/error behavior only.
            if kind == "ingest" and item["id"] in ["scan", "mixed"]:
                continue
            with tempfile.TemporaryDirectory() as out:
                expected[kind + ":" + item["filename"]] = snapshot(
                    fixture_dir / item["filename"], Path(out), kind
                )
    (target / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Frozen", len(sources), "source hashes and", len(expected), "golden cases")


if __name__ == "__main__":
    main()
