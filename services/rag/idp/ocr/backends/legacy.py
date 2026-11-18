"""Legacy IDP page OCR as an acquisition backend for the unified PDF engine.

The legacy lane reads a scanned page with Tesseract hOCR, then region recovery
(optionally driven by a layout detector such as PP-DocLayout through
``idp.ocr.recovery``) and emits a Marker-shaped page. This transport runs that
same code on the unified engine's rendered ``ImageFrame`` and returns the
``deepdoc-model-result:1`` envelope, so ``AdvancedBackend`` converts it into a
``StructuredAcquisitionResult`` exactly like Marker/Paddle output: paragraph
level blocks with real Tesseract confidence, provenance-hashed raw output and
no second pipeline. Question grouping then runs on the merged record in
``idp.pdf.understanding`` as for any other source.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from .tesseract import BackendUnavailable

BACKEND = "legacy-hybrid"


class LegacyHybridTransport:
    backend = BACKEND
    # Local Tesseract subprocesses on per-call temporary folders.
    parallel_safe = True
    input_tone = True
    accepts_dpi = True

    def __init__(
        self,
        *,
        language="vie+eng",
        psm=3,
        profile="general",
        recover_regions=True,
        layout_detector=None,
        executable=None,
    ):
        self.executable = executable or shutil.which("tesseract")
        if not self.executable:
            raise BackendUnavailable("legacy-hybrid requires the tesseract executable")
        try:
            raw = subprocess.run(
                [self.executable, "--version"],
                capture_output=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BackendUnavailable("tesseract is not runnable") from error
        version = (raw.stdout or raw.stderr).decode("utf-8", "replace").splitlines()
        self.language, self.psm, self.profile = language, psm, profile
        self.recover_regions, self.layout_detector = recover_regions, layout_detector
        self.identity = {
            "backend": BACKEND,
            "engine": "idp-legacy-tesseract-hocr:1",
            "tesseract": version[0] if version else "unknown",
            "language": language,
            "psm": psm,
            "profile": profile,
            "recover_regions": recover_regions,
            "layout_detector": getattr(layout_detector, "identity", None)
            or (type(layout_detector).__name__ if layout_detector else None),
        }

    def execute(self, image_bytes, *, deadline, dpi=None):
        from io import BytesIO

        from PIL import Image

        from idp.ocr.fallback import tesseract_marker

        if monotonic() >= deadline:
            raise TimeoutError("legacy-hybrid deadline exceeded before OCR")
        with TemporaryDirectory(prefix="idp-legacy-hybrid-") as work:
            image = Path(work) / "page.png"
            if dpi:
                # The legacy reader passes no --dpi; Tesseract reads pHYs.
                with Image.open(BytesIO(image_bytes)) as source:
                    source.save(image, format="PNG", dpi=(dpi, dpi))
            else:
                image.write_bytes(image_bytes)
            marker = tesseract_marker(
                image,
                1,
                Path(work) / "marker",
                lang=self.language,
                psm=self.psm,
                profile=self.profile,
                recover_regions=self.recover_regions,
                layout_detector=self.layout_detector,
            )
            raw = json.loads(marker.read_text(encoding="utf-8"))
        if monotonic() >= deadline:
            # Late output is not admitted, mirroring BackendAcquirer.
            raise TimeoutError("legacy-hybrid exceeded its deadline")
        return {
            "schema": "deepdoc-model-result:1",
            "backend": BACKEND,
            "packages": {"idp-legacy-ocr": self.identity["engine"], "tesseract": self.identity["tesseract"]},
            "weights_sha256": {},
            "input_sha256": hashlib.sha256(image_bytes).hexdigest(),
            "raw": raw,
        }


def legacy_confidence(node):
    """Tesseract hOCR line confidence (0..100 in ``parse_hocr_lines``) as 0..1."""
    value = node.get("_idp_confidence")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if value != value or value < 0 or value > 100:
        return None
    return value / 100
