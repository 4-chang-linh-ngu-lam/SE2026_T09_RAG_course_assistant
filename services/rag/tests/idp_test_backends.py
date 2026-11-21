"""Backend fixtures for Unified PDF tests and fault-injection child processes."""


def fixture_backend_registry(factory, name="paddle-vl"):
    from idp.evidence.contracts import DeepDocCapability
    from idp.pdf.verify_runtime import AcquisitionBackendSpec, BackendRegistry

    return BackendRegistry(
        acquisitions=(
            AcquisitionBackendSpec(name, factory, (DeepDocCapability.TEXT,), 1),
        )
    )


def use_ocr_backend(monkeypatch, factory):
    from idp.pdf.service import DeepDocService

    registry = fixture_backend_registry(factory)
    monkeypatch.setattr(DeepDocService, "_default_registry", lambda self: registry)


class FixtureOcr:
    """Controlled acquisition for real render, cache and projection tests."""

    config_sha256 = "e" * 64
    confidence = 0.95
    cache_identity = "a" * 64

    def __init__(self, out):
        self.out = out

    def read(self, image, source, page, plan, *, deadline, target_region_id=None):
        from hashlib import sha256

        from idp.evidence.contracts import DeepDocProducer
        from idp.pdf.acquire import AcquisitionResult, OcrBlock

        w, h = plan.frame.steps[-1].output_size
        self.out.mkdir(parents=True, exist_ok=True)
        artifact = self.out / (sha256(image).hexdigest() + ".fixture")
        artifact.write_bytes(image)
        return AcquisitionResult(
            plan.frame,
            DeepDocProducer("fixture-ocr", "1", model=self.cache_identity),
            "fixture-ocr",
            self.config_sha256,
            str(artifact),
            sha256(image).hexdigest(),
            (
                OcrBlock(
                    "line",
                    "Independent expected test text",
                    (0, 0, w / 2, h / 2),
                    self.confidence,
                    target_region_id=target_region_id,
                ),
            ),
        )
