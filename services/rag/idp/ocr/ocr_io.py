"""Short, fresh native Tesseract I/O for Windows and other batch workers."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from idp.input.filetypes import assert_tesseract_languages_loaded


def read_tesseract(image, base, language, psm, *, output_format, timeout=120):
    if output_format not in {"hocr", "tsv", "text"}:
        raise ValueError("unsupported Tesseract output format")
    image, base = Path(image), Path(base)
    with tempfile.TemporaryDirectory(prefix="idp-tess-") as directory:
        staged = Path(directory)
        source, target = staged / "input.png", staged / "output"
        if os.name == "nt" and len(str(target.with_suffix(".hocr"))) >= 240:
            raise RuntimeError("configure a shorter TEMP directory for Tesseract")
        shutil.copyfile(image, source)
        command = ["tesseract", str(source), "stdout" if output_format == "text" else str(target),
            "-l", language, "--psm", str(psm)]
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
