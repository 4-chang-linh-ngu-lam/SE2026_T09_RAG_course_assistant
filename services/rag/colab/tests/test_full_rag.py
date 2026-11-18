"""Real PDF/core/Tesseract/RAG integration; GPU responses below are unit records."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
import full_rag

FIX = Path(__file__).parents[2] / "tests/fixtures/generated"


def configuration(tmp_path, name):
    return {
        "input": str(FIX / name),
        "output": str(tmp_path / "output"),
        "work": str(tmp_path),
        "gpu_worker": str(Path(__file__).parents[1] / "structure_worker.py"),
        "model_python": "MUST_NOT_START_ON_NATIVE",
        "source_worker": str(
            Path(__file__).parents[2] / "idp/ocr/backends/model_worker.py"
        ),
        "model_env": {},
        "dpi": 144,
        "max_pixels": 1_000_000,
        "document_timeout": 120,
        "page_timeout": 30,
        "query": "Independent expected text",
    }


def test_native_full_pipeline_no_model(tmp_path):
    config = configuration(tmp_path, "native.pdf")
    full_rag.run(config)
    output = Path(config["output"])
    summary = json.loads((output / "summary.json").read_text())
    assert summary["gpu_structure_calls"] == 0
    assert summary["indexed_chunks"] > 0 and summary["hits"] > 0
    assert all(
        item["citations"]
        for item in json.loads((output / "retrieval.json").read_text())
    )


@pytest.mark.parametrize("failure", [False, True])
def test_scan_real_tesseract_and_recorded_structure(tmp_path, monkeypatch, failure):
    class RecordedTransport:
        backend = "paddle-structure"

        def __init__(self, *args):
            self.identity = {"unit_only": "recorded-structure-schema-not-real-gpu"}
            self.calls = 0

        def execute(self, image_bytes, *, deadline):
            self.ledger.reserve("unit-gpu", resource="GPU")
            self.ledger.settle("unit-gpu", not failure)
            if failure:
                raise RuntimeError("controlled GPU failure")
            self.calls += 1
            return {
                "schema": "deepdoc-model-result:1",
                "backend": self.backend,
                "packages": {"unit_schema": "1"},
                "weights_sha256": {"unit": "1" * 64},
                "input_sha256": hashlib.sha256(image_bytes).hexdigest(),
                "raw": {
                    "res": {
                        "parsing_res_list": [
                            {
                                "block_label": "formula",
                                "block_bbox": [10, 10, 100, 40],
                                "block_content": "x+y=z",
                            }
                        ]
                    }
                },
            }

        def close(self):
            pass

    monkeypatch.setattr(full_rag, "StructureTransport", RecordedTransport)
    config = configuration(tmp_path, "scan.pdf")
    if failure:
        with pytest.raises(RuntimeError, match="controlled GPU failure"):
            full_rag.run(config)
        assert not (Path(config["output"]) / "rag.sqlite3").exists()
        return
    full_rag.run(config)
    output = Path(config["output"])
    canonical = json.loads((output / "deepdoc/canonical.json").read_text())
    assert any(r["kind"] == "formula" for r in canonical["structures"]["regions"])
    assert "x+y=z" not in (output / "chunks.json").read_text()
    assert json.loads((output / "summary.json").read_text())["gpu_structure_calls"] == 1
