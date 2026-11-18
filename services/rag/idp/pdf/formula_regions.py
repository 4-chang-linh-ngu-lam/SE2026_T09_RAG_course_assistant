"""Supplement text acquisition with bounded, source-bound formula crops."""

import math
import os
import tempfile
from pathlib import Path

from idp.ocr.backends.advanced import AdvancedBackend
from idp.runtime.paddle_pool import PaddleSessionTransport
from idp.runtime.resources import HeavyModelLease

from .acquire import AcquisitionRequest, BackendAcquirer
from .geometry import Affine
from .render import digest, transform_image


def formula_boxes(raw, size, *, limit):
    data = raw.get("res", raw)
    found = []
    for box in data.get("boxes", ()):
        if (
            str(box.get("label", "")).lower()
            not in {"formula", "display_formula", "inline_formula", "equation"}
            or box.get("score", 0) < 0.5
        ):
            continue
        coords = box.get("coordinate", ())
        if len(coords) != 4 or not all(
            isinstance(v, (float, int)) and math.isfinite(v) for v in coords
        ):
            continue
        x0, y0, x1, y1 = coords
        x0, y0 = max(0, math.floor(x0) - 4), max(0, math.floor(y0) - 4)
        x1, y1 = min(size[0], math.ceil(x1) + 4), min(size[1], math.ceil(y1) + 4)
        if x1 <= x0 or y1 <= y0 or (x1 - x0) * (y1 - y0) > size[0] * size[1] * 0.35:
            continue
        rect = (x0, y0, x1, y1)
        if rect not in found:
            found.append(rect)
        if len(found) >= limit:
            break
    return found


class FormulaRegions:
    def __init__(self, config):
        self.config = config
        self.layout = PaddleSessionTransport(
            "paddle-layout",
            device=config.formula_layout_device,
            max_pixels=config.max_pixels,
            timeout_seconds=config.ocr_timeout_seconds,
        )
        self.formula = None
        self.memory_lease = None
        self.gpu_lease = None

    def close(self):
        try:
            self.layout.close()
        finally:
            try:
                if self.formula is not None:
                    self.formula.close()
            finally:
                for name in ("gpu_lease", "memory_lease"):
                    lease = getattr(self, name)
                    if lease is not None:
                        lease.__exit__(None, None, None)
                        setattr(self, name, None)

    def acquire(self, data, frame, source, page, ledger, out):
        root = Path(
            os.environ.get(
                "DEEPDOC_GPU_LOCK_DIR",
                Path(tempfile.gettempdir()) / "deepdoc-gpu-locks",
            )
        )
        if self.memory_lease is None:
            lease = HeavyModelLease(
                root / "paddle-regions-memory.lock", ledger.deadline
            )
            lease.__enter__()
            self.memory_lease = lease
        if (
            self.config.formula_layout_device != "cpu"
            and self.gpu_lease is None
        ):
            if self.config.formula_layout_device != self.config.paddle_device:
                raise ValueError("GPU layout and formula must use the same GPU")
            lease = HeavyModelLease(
                root / (self.config.paddle_device.replace(":", "-") + ".lock"),
                ledger.deadline,
            )
            lease.__enter__()
            self.gpu_lease = lease
            self.layout.shared_lease = lease
        key = "formula-layout-" + digest([frame.render_id, self.layout.identity])
        ledger.reserve(key, resource=self.layout.resource, page=page)
        ok = False
        try:
            layout = self.layout.execute(data, deadline=ledger.deadline)
            ok = True
        finally:
            ledger.settle(key, ok)
        size = frame.steps[-1].output_size
        crops = formula_boxes(
            layout["raw"], size, limit=self.config.formula_max_regions
        )
        results = []
        for index, (x0, y0, x1, y1) in enumerate(crops):
            pixels = (x1 - x0) * (y1 - y0)
            ledger.reserve_render(key + ":crop:" + str(index), pixels)
            image, crop_frame = transform_image(
                data,
                frame,
                kind="crop",
                matrix=Affine(e=-x0, f=-y0),
                output_size=(x1 - x0, y1 - y0),
                params={"left": x0, "top": y0},
            )
            if pixels > self.config.formula_max_pixels:
                ratio = math.sqrt(self.config.formula_max_pixels / pixels)
                width, height = (
                    max(1, int((x1 - x0) * ratio)),
                    max(1, int((y1 - y0) * ratio)),
                )
                ledger.reserve_render(key + ":resize:" + str(index), width * height)
                image, crop_frame = transform_image(
                    image,
                    crop_frame,
                    kind="resize",
                    matrix=Affine(a=width / (x1 - x0), d=height / (y1 - y0)),
                    output_size=(width, height),
                    params={},
                )
            if self.formula is None:
                self.formula = PaddleSessionTransport(
                    "paddle-formula",
                    device=self.config.paddle_device,
                    max_pixels=self.config.formula_max_pixels,
                    timeout_seconds=self.config.ocr_timeout_seconds,
                    shared_lease=self.gpu_lease,
                    model=self.config.formula_model,
                )
            self.formula.ledger, self.formula.page = ledger, page
            backend = AdvancedBackend(out / "formula_raw", self.formula)
            request = AcquisitionRequest(
                digest([crop_frame.render_id, backend.config_sha256]),
                crop_frame,
                ((0, 0, *crop_frame.steps[-1].output_size),),
            )
            executor = BackendAcquirer(
                lambda s, p, plan, deadline, backend=backend, image=image: backend.read(
                    image, s, p, plan, deadline=deadline
                ),
                ledger,
                render_precharged=True,
                resource=self.formula.resource,
            )
            results.append(
                executor.acquire_regions(
                    source, page, request, deadline=ledger.deadline
                )
            )
        return results
