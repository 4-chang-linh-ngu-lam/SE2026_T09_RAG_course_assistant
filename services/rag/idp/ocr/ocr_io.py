"""Short, fresh native Tesseract I/O for Windows and other batch workers."""
from pathlib import Path
import os
import subprocess
import tempfile

from PIL import Image, ImageOps

from idp.input.filetypes import assert_tesseract_languages_loaded

# Resolution metadata is trusted only in the range our own renders write;
# 72/96 are common unset defaults on uploads and would mislead Tesseract.
TRUSTED_DPI = (100, 1200)


def _prepare(image: Path, target: Path) -> int | None:
    """Grayscale + autocontrast copy for Tesseract; return a trusted dpi.

    Measured on hand-checked SGK pages (2026-11-20): word recall 0.915 for
    an RGB render without --dpi, 0.939 for grayscale/autocontrast with the
    real --dpi. Geometry is unchanged, so block coordinates are unaffected.
    """
    with Image.open(image) as opened:
        dpi = opened.info.get("dpi")
        ImageOps.autocontrast(ImageOps.grayscale(opened)).save(target)
    if dpi and TRUSTED_DPI[0] <= round(float(dpi[0])) <= TRUSTED_DPI[1]:
        return round(float(dpi[0]))
    return None


def read_tesseract(image, base, language, psm, *, output_format, timeout=120):
    if output_format not in {"hocr", "tsv", "text"}:
        raise ValueError("unsupported Tesseract output format")
    image, base = Path(image), Path(base)
    with tempfile.TemporaryDirectory(prefix="idp-tess-") as directory:
        staged = Path(directory)
        source, target = staged / "input.png", staged / "output"
        if os.name == "nt" and len(str(target.with_suffix(".hocr"))) >= 240:
            raise RuntimeError("configure a shorter TEMP directory for Tesseract")
        dpi = _prepare(image, source)
        command = ["tesseract", str(source), "stdout" if output_format == "text" else str(target),
            "-l", language, "--psm", str(psm)]
        if dpi:
            command += ["--dpi", str(dpi)]
        if output_format != "text":
            command += ["-c", f"tessedit_create_{output_format}=1"]
        try:
            proc = subprocess.run(command, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"tesseract timed out after {timeout}s") from exc
        assert_tesseract_languages_loaded(proc)
        if proc.returncode:
            raise RuntimeError("tesseract process failed")
        if output_format == "text":
            raw = proc.stdout
            if len(raw) > 32_000_000:
                raise RuntimeError("tesseract text output byte limit")
            return raw
        generated = target.with_suffix("." + output_format)
        if not generated.is_file() or not 0 < generated.stat().st_size <= 32_000_000:
            raise RuntimeError(f"tesseract produced no bounded fresh {output_format} output")
        raw = generated.read_bytes()
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix("." + output_format).write_bytes(raw)
        return raw
