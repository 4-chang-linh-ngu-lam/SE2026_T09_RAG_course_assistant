"""Opt-in PDFium rendering, immutable transform and byte provenance."""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from importlib.metadata import version
from io import BytesIO
from types import MappingProxyType

from .geometry import Affine, bounds, corners


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def sha(value):
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid SHA256")


@dataclass(frozen=True, slots=True)
class TransformStep:
    kind: str
    matrix: Affine
    params: Mapping[str, float]
    output_size: tuple[int, int]
    output_sha256: str

    def __post_init__(self):
        if self.kind not in {
            "render",
            "orientation",
            "deskew",
            "crop",
            "resize",
            "padding",
            "exif",
            "tone",
        }:
            raise ValueError("unsupported affine step")
        if not isinstance(self.matrix, Affine):
            raise TypeError("IDP affine required")
        if len(self.output_size) != 2 or any(
            type(v) is not int or v <= 0 for v in self.output_size
        ):
            raise ValueError("invalid output size")
        if not all(math.isfinite(v) for v in self.params.values()):
            raise ValueError("invalid parameters")
        sha(self.output_sha256)
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "output_size", tuple(self.output_size))


@dataclass(frozen=True, slots=True)
class ImageFrame:
    source_sha256: str
    page: int
    geometry: tuple[float, float, tuple[float, float, float, float], int]
    renderer: str
    steps: tuple[TransformStep, ...]

    def __post_init__(self):
        sha(self.source_sha256)
        if (
            len(self.geometry) != 4
            or self.geometry[0] <= 0
            or self.geometry[1] <= 0
            or self.geometry[3] not in (0, 90, 180, 270)
        ):
            raise ValueError("invalid PDF geometry")
        object.__setattr__(
            self,
            "geometry",
            (
                self.geometry[0],
                self.geometry[1],
                tuple(self.geometry[2]),
                self.geometry[3],
            ),
        )
        object.__setattr__(self, "steps", tuple(self.steps))
        if (
            type(self.page) is not int
            or self.page < 1
            or not self.steps
            or self.steps[0].kind != "render"
        ):
            raise ValueError("invalid frame")

    @property
    def render_id(self):
        steps = [
            {
                "kind": s.kind,
                "matrix": asdict(s.matrix),
                "params": dict(s.params),
                "size": s.output_size,
                "sha": s.output_sha256,
            }
            for s in self.steps
        ]
        return digest(
            [self.source_sha256, self.page, self.geometry, self.renderer, steps]
        )

    @property
    def matrix(self):
        value = Affine()
        for step in self.steps:
            value = step.matrix @ value
        return value

    def polygon_to_pdf(self, polygon):
        return tuple(self.matrix.inverse().apply(*p) for p in polygon)

    def to_pdf_pt(self, box):
        return bounds(self.polygon_to_pdf(corners(box)))

    def from_pdf_pt(self, box):
        return bounds(tuple(self.matrix.apply(*p) for p in corners(box)))

    def append(self, step):
        from dataclasses import replace

        return replace(self, steps=(*self.steps, step))


def render_page(source, page: int, *, dpi: float = 144, max_pixels: int = 4_000_000):
    if not math.isfinite(dpi) or dpi <= 0 or max_pixels <= 0:
        raise ValueError("invalid render settings")
    g = source.geometry[page]
    scale = min(dpi / 72, math.sqrt(max_pixels / (g.width * g.height)))
    source.check_render_window(page - 1, page, scale)
    pdfpage = source.pdfium[page - 1]
    try:
        bitmap = pdfpage.render(scale=scale)
        try:
            image = bitmap.to_pil()
            try:
                out = BytesIO()
                image.save(out, format="PNG")
                data = out.getvalue()
                size = image.size
            finally:
                image.close()
        finally:
            bitmap.close()
    finally:
        pdfpage.close()
    step = TransformStep(
        "render",
        Affine(a=size[0] / g.width, d=size[1] / g.height),
        {"dpi": dpi, "max_pixels": max_pixels},
        size,
        hashlib.sha256(data).hexdigest(),
    )
    return data, ImageFrame(
        source.report.source_sha256,
        page,
        (g.width, g.height, g.crop_box, g.rotation),
        "pdfium:" + version("pypdfium2"),
        (step,),
    )


# A raster covering at least this share of the page decides the OCR render.
DOMINANT_IMAGE_COVERAGE = 0.5


def dominant_image_scale(source, page: int):
    """Pixels per PDF point of the largest embedded raster, if it dominates.

    Returns ``None`` when no single image covers ``DOMINANT_IMAGE_COVERAGE``
    of the visible page (native text pages, figures inside text).
    """
    import pypdfium2.raw as raw

    g = source.geometry[page]
    pdfpage = source.pdfium[page - 1]
    best = None
    try:
        for item in pdfpage.get_objects(filter=[raw.FPDF_PAGEOBJ_IMAGE], max_depth=2):
            left, bottom, right, top = item.get_bounds()
            area = (right - left) * (top - bottom)
            width, height = item.get_px_size()
            if area <= 0 or width <= 0 or height <= 0:
                continue
            if best is None or area > best[0]:
                # Area-based so 90-degree placement does not matter.
                best = (area, math.sqrt(width * height / area))
    finally:
        pdfpage.close()
    if best is None or best[0] < DOMINANT_IMAGE_COVERAGE * g.width * g.height:
        return None
    return best[1]


def render_for_ocr(source, page: int, *, dpi: float, max_pixels: int):
    """Render a page for recognition without blocky upscaling of scans.

    PDFium enlarges a low-resolution embedded scan with hard pixel edges;
    Tesseract then misreads glyphs (measured: "Phase" -> "Phage" on a 72 dpi
    scan rendered at 216 dpi, while Poppler's smoothed render read it
    correctly). When a dominant raster is coarser than the target scale, the
    page is rendered at the raster's own resolution and enlarged by a bicubic
    ``resize`` step. Both steps are hashed in the frame like any transform,
    so OCR coordinates still map back to PDF points exactly.
    """
    g = source.geometry[page]
    target = min(dpi / 72, math.sqrt(max_pixels / (g.width * g.height)))
    native = dominant_image_scale(source, page)
    if native is None or native >= target * 0.95:
        return render_page(source, page, dpi=dpi, max_pixels=max_pixels)
    data, frame = render_page(source, page, dpi=native * 72, max_pixels=max_pixels)
    width, height = frame.steps[-1].output_size
    size = (
        max(1, round(g.width * target)),
        max(1, round(g.height * target)),
    )
    return transform_image(
        data,
        frame,
        kind="resize",
        matrix=Affine(a=size[0] / width, d=size[1] / height),
        output_size=size,
        params={"native_scale": native, "target_scale": target},
    )


TONE_CUTOFF = 1  # percent of darkest/lightest pixels clipped by auto-contrast


def tone_normalize(data: bytes, frame: ImageFrame):
    """Grayscale + auto-contrast for recognition, as a recorded frame step.

    Pixel values only: the step's matrix is the identity, so coordinates are
    unchanged. Measured on hand-transcribed SGK pages: word recall 0.929 ->
    0.944 with the same model and resolution (coloured boxes and tinted
    backgrounds stop competing with glyph edges).
    """
    from PIL import Image, ImageOps

    if hashlib.sha256(data).hexdigest() != frame.steps[-1].output_sha256:
        raise ValueError("input image bytes do not match frame provenance")
    with Image.open(BytesIO(data)) as image:
        if image.size != frame.steps[-1].output_size:
            raise ValueError("image dimensions mismatch")
        gray = ImageOps.autocontrast(image.convert("L"), cutoff=TONE_CUTOFF)
        try:
            out = BytesIO()
            gray.save(out, format="PNG")
            output = out.getvalue()
        finally:
            gray.close()
    step = TransformStep(
        "tone",
        Affine(),
        {"grayscale": 1, "autocontrast_cutoff_percent": TONE_CUTOFF},
        frame.steps[-1].output_size,
        hashlib.sha256(output).hexdigest(),
    )
    return output, frame.append(step)


def transform_image(
    data: bytes,
    frame: ImageFrame,
    *,
    kind: str,
    matrix: Affine,
    output_size: tuple[int, int],
    params=None,
):
    """Apply an explicitly specified affine preprocessing step with byte linkage.

    Caller supplies orientation/crop/deskew geometry including canvas translation.
    Non-affine warps are unsupported. Output pixels use the inverse sampling map.
    """
    from PIL import Image

    if hashlib.sha256(data).hexdigest() != frame.steps[-1].output_sha256:
        raise ValueError("input image bytes do not match frame provenance")
    # Validate before allocating output buffers.
    step = TransformStep(kind, matrix, params or {}, output_size, "0" * 64)
    if kind == "render":
        raise ValueError("preprocessing cannot replace initial render")
    inverse = matrix.inverse()
    with Image.open(BytesIO(data)) as image:
        if image.size != frame.steps[-1].output_size:
            raise ValueError("image dimensions mismatch")
        result = image.transform(
            output_size,
            Image.Transform.AFFINE,
            (inverse.a, inverse.c, inverse.e, inverse.b, inverse.d, inverse.f),
            resample=Image.Resampling.BICUBIC,
            fillcolor="white",
        )
        try:
            out = BytesIO()
            result.save(out, format="PNG")
            output = out.getvalue()
        finally:
            result.close()
    from dataclasses import replace

    return output, frame.append(
        replace(step, output_sha256=hashlib.sha256(output).hexdigest())
    )
