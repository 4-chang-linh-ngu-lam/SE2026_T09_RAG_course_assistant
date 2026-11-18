"""Resource/geometry/failure contracts; fake transports are not inference proof."""

import hashlib
import time
from io import BytesIO
from pathlib import Path

import pytest
from idp.ocr.backends.advanced import DockerModelTransport
from idp.ocr.backends.tesseract import BackendUnavailable
from idp.pdf.formula_regions import FormulaRegions, formula_boxes
from idp.pdf.native.preflight import PdfSource
from idp.pdf.render import render_page
from idp.pdf.resource import ResourceLedger
from idp.pdf.service import DeepDocConfig
from idp.runtime.model_pool import JobMarkerTransport
from idp.runtime.paddle_pool import PaddleSessionTransport
from PIL import Image

FIX = Path(__file__).parent / "fixtures/generated"


def test_gpu_needs_explicit_budget():
    assert DeepDocConfig().max_gpu_calls == 0
    with pytest.raises(ValueError):
        DeepDocConfig(paddle_device="gpu:0")
    with pytest.raises(ValueError):
        DeepDocConfig(paddle_device="gpu:0 --privileged", max_gpu_calls=2)
    assert DeepDocConfig(paddle_device="gpu:0", max_gpu_calls=2).max_gpu_calls == 2


def test_formula_boxes_bounded():
    boxes = [
        {"label": "formula", "score": 0.9, "coordinate": c}
        for c in [
            (0, 0, 1000, 1000),
            (10, 20, 60, 40),
            (10, 20, 60, 40),
            (float("nan"), 0, 50, 40),
            (80, 50, 150, 80),
        ]
    ]
    assert formula_boxes({"res": {"boxes": boxes}}, (1000, 1000), limit=1) == [
        (6, 16, 64, 44)
    ]
    assert (
        formula_boxes(
            {"boxes": [{"label": "text", "score": 1, "coordinate": [10, 20, 50, 40]}]},
            (100, 100),
            limit=3,
        )
        == []
    )


def test_formula_crops_are_small_and_source_bound(tmp_path, monkeypatch):
    import idp.pdf.formula_regions as module

    created = []

    class Recorded:
        def __init__(self, backend, **kw):
            self.backend = backend
            self.identity = {"unit": backend}
            self.calls = []
            self.resource = "GPU" if backend == "paddle-formula" else "CPU"
            created.append(self)

        def close(self):
            pass

        def execute(self, data, **kw):
            with Image.open(BytesIO(data)) as im:
                self.calls.append(im.size)
            raw = (
                {
                    "boxes": [
                        {
                            "label": "formula",
                            "score": 0.9,
                            "coordinate": [20, 30, 300, 120],
                        }
                    ]
                }
                if self.backend == "paddle-layout"
                else {"rec_formula": "x+y=z"}
            )
            return {
                "schema": "deepdoc-model-result:1",
                "backend": self.backend,
                "packages": {"unit": "recorded-not-real"},
                "weights_sha256": {"unit": "1" * 64},
                "input_sha256": hashlib.sha256(data).hexdigest(),
                "raw": raw,
            }

    monkeypatch.setattr(module, "PaddleSessionTransport", Recorded)
    pipeline = FormulaRegions(
        DeepDocConfig(
            formula_regions=True,
            formula_max_pixels=1024,
            paddle_device="gpu:0",
            max_gpu_calls=3,
        )
    )
    ledger = ResourceLedger(
        time.monotonic() + 30, max_calls=10, resource_limits={"CPU": 5, "GPU": 3}
    )
    with PdfSource((FIX / "native.pdf").read_bytes()) as source:
        data, frame = render_page(source, 1, dpi=72, max_pixels=4000000)
        result = pipeline.acquire(data, frame, source, 1, ledger, tmp_path)[0]
    assert result.frame.source_sha256 == frame.source_sha256
    assert result.frame.page == 1
    assert result.blocks[0].confidence == 0
    assert created[1].calls[0][0] * created[1].calls[0][1] <= 1024
    assert result.frame.to_pdf_pt((0, 0, 1, 1))[:2] == pytest.approx((16, 26))
    assert ledger._resource_calls == {"CPU": 1, "GPU": 1}
    pipeline.close()


def fake_init(self, image, backend, **kw):
    self.image = image
    self.backend = backend
    self.device = kw.get("device", "cpu")
    self.container_device = "cpu" if self.device == "cpu" else "gpu:0"
    self.timeout_seconds = 30
    self.memory = "4g"
    self.cpus = 2
    self.cache_family = "paddle"
    self.identity = {
        "image_id": "sha256:unit",
        "backend": backend,
        "device": self.device,
    }


def test_oom_retries_cpu_once_and_charges_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("DEEPDOC_GPU_LOCK_DIR", str(tmp_path))
    monkeypatch.setattr(DockerModelTransport, "__init__", fake_init)
    calls = []

    def execute(self, data, **kw):
        calls.append(self.device)
        if self.device != "cpu":
            raise BackendUnavailable("PADDLE_GPU_OOM")
        return {"unit": "cpu"}

    monkeypatch.setattr(JobMarkerTransport, "execute", execute)
    monkeypatch.setattr(JobMarkerTransport, "close", lambda self: None)
    transport = PaddleSessionTransport("paddle-formula", device="gpu:0")
    transport.ledger = ResourceLedger(time.monotonic() + 30, max_calls=5)
    transport.page = 1
    buffer = BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="PNG")
    assert transport.execute(buffer.getvalue(), deadline=time.monotonic() + 10) == {
        "unit": "cpu"
    }
    transport.execute(buffer.getvalue(), deadline=time.monotonic() + 10)
    assert calls == ["gpu:0", "cpu", "cpu"]
    assert (
        transport.fallback_count == 1
        and transport.resource == "CPU"
        and transport.lease is None
    )
    assert transport.ledger._resource_calls["CPU"] == 1
    transport.close()


def test_session_rejects_large_input_before_docker(monkeypatch):
    monkeypatch.setattr(DockerModelTransport, "__init__", fake_init)
    transport = PaddleSessionTransport("paddle-formula", max_pixels=100)
    buffer = BytesIO()
    Image.new("RGB", (11, 11)).save(buffer, format="PNG")
    with pytest.raises(ValueError, match="pixel limit"):
        transport.execute(buffer.getvalue(), deadline=time.monotonic() + 10)
    assert transport.directory is None


@pytest.mark.parametrize("failed", [False, True])
def test_formula_supplement_keeps_real_text_and_never_self_publishes(
    tmp_path, monkeypatch, failed
):
    import json
    import shutil
    from dataclasses import replace

    import idp.pdf.formula_regions as module
    from idp.evidence import serde
    from idp.pdf.service import DeepDocService
    from idp.publish import iter_retrievable_blocks, load_canonical

    if shutil.which("tesseract") is None:
        pytest.skip("real Tesseract verified in Docker")

    class Recorded:
        def __init__(self, backend, **kwargs):
            self.backend = backend
            self.identity = {"unit": backend}
            self.resource = "GPU" if backend == "paddle-formula" else "CPU"
            self.stats = {"model_loads": 1, "unit_only": True}

        def close(self):
            pass

        def execute(self, data, **kwargs):
            if self.backend == "paddle-formula" and failed:
                raise BackendUnavailable("controlled supplemental failure")
            raw = (
                {
                    "boxes": [
                        {
                            "label": "formula",
                            "score": 0.9,
                            "coordinate": [20, 20, 180, 70],
                        }
                    ]
                }
                if self.backend == "paddle-layout"
                else {"rec_formula": "DO_NOT_PUBLISH_MODEL"}
            )
            return {
                "schema": "deepdoc-model-result:1",
                "backend": self.backend,
                "packages": {"unit": "recorded-not-real"},
                "weights_sha256": {"unit": "1" * 64},
                "input_sha256": hashlib.sha256(data).hexdigest(),
                "raw": raw,
            }

    monkeypatch.setattr(module, "PaddleSessionTransport", Recorded)
    cfg = DeepDocConfig(
        engine="unified",
        canonical_version=2,
        language="eng",
        dpi=216,
        formula_regions=True,
        paddle_device="gpu:0",
        max_gpu_calls=3,
    )
    baseline = tmp_path / "baseline"
    DeepDocService(replace(cfg, formula_regions=False)).process_pdf(
        FIX / "scan.pdf", baseline
    )
    before = serde.load((baseline / "extraction.json").read_text())
    baseline_text = " ".join(o.text or "" for o in before.observations)
    assert "Independent expected text" in baseline_text
    DeepDocService(cfg).process_pdf(FIX / "scan.pdf", tmp_path)
    doc = load_canonical(tmp_path / "canonical.json")
    text = " ".join(b["text"] for b in iter_retrievable_blocks(doc))
    # Retention and publication are separate: low-confidence real OCR can
    # legitimately have no eligible blocks, even without the supplement.
    after = serde.load((tmp_path / "extraction.json").read_text())
    assert all(
        any(
            o.text == old.text and o.source_id == old.source_id
            for o in after.observations
        )
        for old in before.observations
    )
    before_eligible = {
        b["text"]
        for b in iter_retrievable_blocks(load_canonical(baseline / "canonical.json"))
    }
    assert before_eligible <= {b["text"] for b in iter_retrievable_blocks(doc)}
    assert "DO_NOT_PUBLISH_MODEL" not in text
    if failed:
        assert any(
            row.get("stage") == "formula_regions" and row["status"] == "review"
            for row in json.loads((tmp_path / "ocr_attempts.json").read_text())
        )


def test_session_accepts_renderer_rounding_but_not_real_oversize(monkeypatch):
    """Clamped renders round up (1687x2371 = 4,000,177 px on a 787x1106 pt page)."""
    monkeypatch.setattr(DockerModelTransport, "__init__", fake_init)
    monkeypatch.setattr(JobMarkerTransport, "execute", lambda self, data, **kw: {"ok": 1})
    transport = PaddleSessionTransport("paddle-layout", max_pixels=4_000_000)

    def png(size):
        buffer = BytesIO()
        Image.new("L", size).save(buffer, format="PNG")
        return buffer.getvalue()

    assert transport.execute(png((1687, 2371)), deadline=time.monotonic() + 10) == {"ok": 1}
    with pytest.raises(ValueError, match="pixel limit"):
        transport.execute(png((1800, 2400)), deadline=time.monotonic() + 10)


def test_gpu_layout_needs_gpu_formula_device():
    with pytest.raises(ValueError):
        DeepDocConfig(formula_layout_device="gpu:0")  # no GPU Paddle device
    with pytest.raises(ValueError):
        DeepDocConfig(
            paddle_device="gpu:0", max_gpu_calls=2, formula_layout_device="gpu:0 --x"
        )
    cfg = DeepDocConfig(
        paddle_device="gpu:0", max_gpu_calls=2, formula_layout_device="gpu:0"
    )
    assert cfg.formula_layout_device == "gpu:0"
    assert DeepDocConfig().formula_layout_device == "cpu"


def test_job_shares_one_gpu_lease_between_its_sessions(monkeypatch, tmp_path):
    """Two resident models of one job must not wait on each other's lock."""
    monkeypatch.setenv("DEEPDOC_GPU_LOCK_DIR", str(tmp_path))
    monkeypatch.setattr(DockerModelTransport, "__init__", fake_init)
    monkeypatch.setattr(JobMarkerTransport, "execute", lambda self, data, **kw: {"ok": 1})
    held = object()  # owned and released by the caller
    layout = PaddleSessionTransport("paddle-layout", device="gpu:0", shared_lease=held)
    formula = PaddleSessionTransport("paddle-formula", device="gpu:0", shared_lease=held)
    buffer = BytesIO()
    Image.new("L", (10, 10)).save(buffer, format="PNG")
    for transport in (layout, formula):
        transport.execute(buffer.getvalue(), deadline=time.monotonic() + 5)
        assert transport.lease is None  # neither took a second lock
    assert list(tmp_path.iterdir()) == []
