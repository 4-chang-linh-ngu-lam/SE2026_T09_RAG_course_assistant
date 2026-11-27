"""Lazy, render-once PDF page rasterizer and bounded crop cache."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

from idp.config import RenderConfig
from idp.input.validation import open_fitz_doc


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class RenderedPage:
    page_id: int
    path: Path
    width: int
    height: int
    dpi: int
    sha256: str


def render_pdf_page(
    pdf_path: str | Path,
    page_id: int,
    target: str | Path,
    dpi: int = 220,
    *,
    max_pixels: int = 4_000_000,
    max_longest_dim: int | None = None,
) -> Path:
    """Standalone single-page PyMuPDF render bounded by pixel and dimension caps."""
    import pymupdf as fitz

    target = Path(target)
    with open_fitz_doc(pdf_path) as doc:
        page = doc[page_id - 1]
        return _render_fitz_page(
            page, target, dpi, fitz=fitz,
            max_pixels=max_pixels, max_longest_dim=max_longest_dim,
        )


def _render_fitz_page(
    page,
    target: Path,
    dpi: int,
    *,
    fitz,
    max_pixels: int = 4_000_000,
    max_longest_dim: int | None = None,
) -> Path:
    width, height = float(page.rect.width), float(page.rect.height)
    area = max(1.0, width * height)
    if not math.isfinite(area):
        raise ValueError("invalid source page geometry")
    scale = dpi / 72.0
    if max_pixels:
        scale = min(scale, math.sqrt(max_pixels / area) * 0.999)
    if max_longest_dim:
        scale = min(scale, max_longest_dim / max(1.0, width, height))
    scale = max(0.1, scale)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    effective = max(1, round(scale * 72))
    pix.set_dpi(effective, effective)
    target.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(target))
    return target


class PageRenderCache:
    """Thread-safe, lazy, render-once PDF rasterizer with batch PIL eviction."""

    def __init__(
        self,
        pdf_path: str | Path | None,
        work_dir: str | Path,
        config: RenderConfig | None = None,
        *,
        precomputed_images: dict[int, str | Path] | None = None,
    ):
        self.pdf_path = Path(pdf_path).resolve() if pdf_path is not None else None
        self.work_dir = Path(work_dir)
        self.config = config or RenderConfig()
        self.precomputed = {
            int(k): Path(v) for k, v in (precomputed_images or {}).items()
        }
        self._source_sha: str | None = None
        self._lock = threading.RLock()
        self._local = threading.local()
        self._docs: list = []
        self._rendered: dict[int, RenderedPage] = {}
        self._pil_cache: dict[int, Image.Image] = {}
        self.render_count = 0
        self.rerender_count = 0

    def _source_digest(self) -> str:
        if self._source_sha is None:
            with self._lock:
                if self._source_sha is None:
                    self._source_sha = sha256_file(self.pdf_path) if self.pdf_path else ""
        return self._source_sha

    def _fitz_doc(self):
        doc = getattr(self._local, "doc", None)
        if doc is None:
            if self.pdf_path is None:
                raise RuntimeError("PageRenderCache has no PDF path for lazy rendering")
            doc = open_fitz_doc(self.pdf_path)
            self._local.doc = doc
            with self._lock:
                self._docs.append(doc)
        return doc

    def get_page_image(
        self,
        page_id: int,
        *,
        dpi: int | None = None,
        max_pixels: int | None = None,
        force_rerender: bool = False,
    ) -> RenderedPage:
        """Return rendered page PNG, rendering lazily only once per requested DPI tier."""
        target_dpi = dpi or self.config.base_dpi
        pixel_cap = max_pixels or self.config.max_page_pixels
        with self._lock:
            existing = self._rendered.get(page_id)
            if existing is not None and not force_rerender and existing.dpi >= target_dpi:
                return existing
            pre = self.precomputed.get(page_id)
            if pre is not None and pre.is_file():
                with Image.open(pre) as opened:
                    w, h = opened.size
                    info_dpi = opened.info.get("dpi")
                    eff = round(float(info_dpi[0])) if info_dpi else target_dpi
                entry = RenderedPage(page_id, pre, w, h, eff, sha256_file(pre))
                self._rendered[page_id] = entry
                return entry

        render_dir = self.work_dir / "renders"
        suffix = f"_d{target_dpi}" if force_rerender else ""
        target = render_dir / f"p{page_id:04d}{suffix}.png"
        sidecar = target.with_name(target.name + ".source.json")
        source_sha = self._source_digest()
        provenance = {
            "source_sha256": source_sha,
            "page_id": page_id,
            "dpi": target_dpi,
            "max_pixels": pixel_cap,
        }
        if not force_rerender and target.is_file() and sidecar.is_file():
            try:
                if json.loads(sidecar.read_text(encoding="utf-8")) == provenance:
                    with Image.open(target) as opened:
                        w, h = opened.size
                    entry = RenderedPage(page_id, target, w, h, target_dpi, sha256_file(target))
                    with self._lock:
                        self._rendered[page_id] = entry
                    return entry
            except (OSError, ValueError):
                pass

        import pymupdf as fitz

        doc = self._fitz_doc()
        page = doc[page_id - 1]
        _render_fitz_page(
            page,
            target,
            target_dpi,
            fitz=fitz,
            max_pixels=pixel_cap,
        )
        atomic_write_text(sidecar, json.dumps(provenance))
        with Image.open(target) as opened:
            w, h = opened.size
        entry = RenderedPage(page_id, target, w, h, target_dpi, sha256_file(target))
        with self._lock:
            had_before = page_id in self._rendered
            self._rendered[page_id] = entry
            if had_before:
                self.rerender_count += 1
            else:
                self.render_count += 1
            old_pil = self._pil_cache.pop(page_id, None)
            if old_pil is not None:
                old_pil.close()
        return entry

    def register_external_image(self, page_id: int, image_path: str | Path, *, dpi: int | None = None) -> RenderedPage:
        """Register an externally supplied/preprocessed image as the active render for ``page_id``."""
        path = Path(image_path)
        with Image.open(path) as opened:
            w, h = opened.size
            info_dpi = opened.info.get("dpi")
            eff = dpi or (round(float(info_dpi[0])) if info_dpi else self.config.base_dpi)
        entry = RenderedPage(page_id, path, w, h, eff, sha256_file(path))
        with self._lock:
            self._rendered[page_id] = entry
            old_pil = self._pil_cache.pop(page_id, None)
            if old_pil is not None:
                old_pil.close()
        return entry

    def open_pil(self, page_id: int, *, dpi: int | None = None) -> Image.Image:
        """Return a loaded RGB PIL image for ``page_id`` (cached per active batch)."""
        with self._lock:
            cached = self._pil_cache.get(page_id)
            if cached is not None:
                return cached
        rendered = self.get_page_image(page_id, dpi=dpi)
        with Image.open(rendered.path) as opened:
            img = opened.convert("RGB")
            img.load()
        with self._lock:
            self._pil_cache[page_id] = img
        return img

    def crop_region(
        self,
        page_id: int,
        bbox: list[float] | tuple[float, float, float, float],
        page_size: list[float] | tuple[float, float],
        *,
        pad: int | None = None,
        max_pixels: int | None = None,
        save_path: str | Path | None = None,
    ) -> tuple[Image.Image, list[int]]:
        """Crop a region from the cached page image, scaling page coords -> image pixels."""
        padding = self.config.crop_padding if pad is None else pad
        cap = max_pixels or self.config.max_crop_pixels
        with self._lock:
            img = self.open_pil(page_id)
            pw, ph = float(page_size[0] or img.width), float(page_size[1] or img.height)
            sx, sy = img.width / pw, img.height / ph
            x0 = max(0, math.floor(float(bbox[0]) * sx) - padding)
            y0 = max(0, math.floor(float(bbox[1]) * sy) - padding)
            x1 = min(img.width, math.ceil(float(bbox[2]) * sx) + padding)
            y1 = min(img.height, math.ceil(float(bbox[3]) * sy) + padding)
            if x1 <= x0 or y1 <= y0:
                raise ValueError("empty crop bounds")
            crop = img.crop((x0, y0, x1, y1))
        if save_path is not None:
            target = Path(save_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            crop.save(target)
        area = crop.width * crop.height
        if cap and area > cap:
            scale = math.sqrt(cap / area)
            crop = crop.resize(
                (max(1, int(crop.width * scale)), max(1, int(crop.height * scale))),
                Image.Resampling.LANCZOS,
            )
        return crop, [x0, y0, x1, y1]

    def evict_pages(self, page_ids: Iterable[int]) -> None:
        """Free in-memory PIL images after a batch finishes (streaming RAM bound)."""
        with self._lock:
            for pid in page_ids:
                img = self._pil_cache.pop(pid, None)
                if img is not None:
                    img.close()

    def close(self) -> None:
        with self._lock:
            for img in self._pil_cache.values():
                img.close()
            self._pil_cache.clear()
            for doc in self._docs:
                try:
                    doc.close()
                except Exception:
                    pass
            self._docs.clear()

    def __enter__(self) -> "PageRenderCache":
        return self

    def __exit__(self, *args) -> None:
        self.close()
