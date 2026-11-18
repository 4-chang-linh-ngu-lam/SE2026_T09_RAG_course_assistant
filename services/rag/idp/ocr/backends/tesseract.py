"""Real bounded Tesseract TSV acquisition through the Phase 2 contract."""

import csv
import hashlib
import math
import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from idp.evidence.contracts import DeepDocProducer
from idp.pdf.acquire import AcquisitionResult, OcrBlock
from idp.pdf.native.preflight import run_bounded_process
from idp.pdf.render import digest


class BackendUnavailable(RuntimeError):
    pass


class OCRTimeout(TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class TesseractConfig:
    language: str = "vie+eng"
    psm: int = 3
    oem: int = 1
    timeout_seconds: float = 60

    def __post_init__(self):
        if not self.language or not re.fullmatch(r"[A-Za-z0-9_+]+", self.language):
            raise ValueError("invalid OCR language")
        if (
            self.psm not in range(14)
            or self.oem not in range(4)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("invalid Tesseract config")


TSV_HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num"
# Bumped whenever the command line or parsing changes what a given image
# yields, so cached acquisitions from older invocations are not reused.
INVOCATION_VERSION = "tesseract-tsv:2"


def parse_tsv(raw: bytes, size, *, target_region_id=None):
    text = raw.decode("utf-8")
    if text.strip() and not text.startswith(TSV_HEADER):
        # Happens when TESSDATA_PREFIX points at a folder without configs/tsv:
        # Tesseract then prints plain text and every page would look empty.
        raise ValueError("Tesseract did not produce TSV output (missing configs/tsv?)")
    groups = {}
    # Tesseract's TSV never quotes fields. A word that is a lone '"' must not
    # open a csv quoted field that swallows the rest of the page.
    for row in csv.DictReader(StringIO(text), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not row.get("text", "").strip():
            continue
        score = float(row["conf"])
        if score < 0:
            continue
        if not math.isfinite(score) or score > 100:
            raise ValueError("invalid Tesseract confidence")
        x, y, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        if not (0 <= x < x + w <= size[0] and 0 <= y < y + h <= size[1]):
            raise ValueError("Tesseract bbox outside rendered frame")
        key = ":".join(row[k] for k in ("page_num", "block_num", "par_num", "line_num"))
        groups.setdefault(key, []).append(
            (row["text"].strip(), (x, y, x + w, y + h), score / 100)
        )
    blocks = []
    for key, words in groups.items():
        bbox = (
            min(w[1][0] for w in words),
            min(w[1][1] for w in words),
            max(w[1][2] for w in words),
            max(w[1][3] for w in words),
        )
        confidence = sum(w[2] * len(w[0]) for w in words) / sum(
            len(w[0]) for w in words
        )
        blocks.append(
            OcrBlock(
                key,
                " ".join(w[0] for w in words),
                bbox,
                confidence,
                target_region_id=target_region_id,
                payload={
                    "words": tuple(
                        {"text": w[0], "bbox_px": w[1], "confidence": w[2]}
                        for w in words
                    )
                },
            )
        )
    return tuple(blocks)


def frame_dpi(frame):
    """Pixels per inch of the frame's final image relative to the page.

    ``geometry`` holds the displayed page size (rotation already applied), and
    crops do not change resolution, so the frame's cumulative x scale is the
    resolution of every pixel Tesseract sees.
    """
    matrix = frame.matrix
    scale = (matrix.a * matrix.a + matrix.b * matrix.b) ** 0.5
    return max(1, round(scale * 72))


class TesseractBackend:
    def __init__(self, artifact_dir, config=None, *, executable=None):
        self.config = config or TesseractConfig()
        self.executable = shutil.which(executable or "tesseract")
        if self.executable is None:
            raise BackendUnavailable("Tesseract executable not found")
        # None: transient reads (the language probe) keep no raw artifact.
        self.artifact_dir = Path(artifact_dir) if artifact_dir is not None else None
        try:
            version = (
                subprocess.run(
                    [self.executable, "--version"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                .stdout.decode()
                .splitlines()[0]
            )
            languages = subprocess.run(
                [self.executable, "--list-langs"],
                capture_output=True,
                timeout=5,
                check=True,
            ).stdout.decode()
        except (OSError, subprocess.SubprocessError) as exc:
            raise BackendUnavailable("Cannot inspect Tesseract installation") from exc
        selected = self.config.language.split("+")
        self.languages = frozenset(languages.splitlines()[1:])
        if not set(selected) <= self.languages:
            raise BackendUnavailable("Requested Tesseract traineddata unavailable")
        directory = re.search(r'"([^"]+)"', languages)
        if directory is None:
            raise BackendUnavailable(
                "Cannot locate Tesseract traineddata for provenance"
            )
        traineddata = {}
        for name in selected:
            path = Path(directory.group(1)) / (name + ".traineddata")
            if not path.is_file():
                raise BackendUnavailable("Cannot fingerprint Tesseract traineddata")
            traineddata[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.producer = DeepDocProducer("tesseract", version, model=digest(traineddata))
        self.config_sha256 = digest(
            {
                "config": asdict(self.config),
                "traineddata": traineddata,
                "version": version,
                "invocation": INVOCATION_VERSION,
            }
        )

    # Grayscale + auto-contrast measurably improves LSTM recognition on
    # coloured textbook scans; the service records it as a frame step.
    input_tone = True
    # Each read is an independent subprocess on its own temporary files.
    parallel_safe = True

    def read(self, image_bytes, source, page, plan, *, deadline, target_region_id=None):
        if (
            hashlib.sha256(image_bytes).hexdigest()
            != plan.frame.steps[-1].output_sha256
        ):
            raise ValueError("Tesseract image provenance mismatch")
        timeout = min(
            deadline - monotonic(), source.check_deadline(), self.config.timeout_seconds
        )
        if timeout <= 0:
            raise OCRTimeout("Tesseract deadline exceeded before execution")
        with TemporaryDirectory(prefix="deepdoc-tess-") as temporary:
            path = Path(temporary) / "input.png"
            path.write_bytes(image_bytes)
            command = [
                self.executable,
                str(path),
                "stdout",
                "-l",
                self.config.language,
                "--psm",
                str(self.config.psm),
                "--oem",
                str(self.config.oem),
                # Real resolution: PNGs carry none and Tesseract would assume
                # 70 dpi, which degrades stacked Vietnamese diacritics.
                "--dpi",
                str(frame_dpi(plan.frame)),
                "tsv",
            ]
            try:
                raw = run_bounded_process(
                    command,
                    timeout=timeout,
                    output_limit=32_000_000,
                    # Pages run in parallel; one thread per process avoids
                    # OpenMP oversubscription and does not change results.
                    env={**os.environ, "OMP_THREAD_LIMIT": "1"},
                ).stdout
            except subprocess.TimeoutExpired as exc:
                raise OCRTimeout("Tesseract subprocess killed after timeout") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError("Tesseract exited unsuccessfully") from exc
        sha256 = hashlib.sha256(raw).hexdigest()
        identity = digest([plan.frame.render_id, self.config_sha256, plan.key, sha256])
        if self.artifact_dir is None:
            artifact = "transient:" + identity
        else:
            self.artifact_dir.mkdir(parents=True, exist_ok=True)
            artifact = self.artifact_dir / (identity + ".tsv")
            artifact.write_bytes(raw)
        blocks = parse_tsv(
            raw, plan.frame.steps[-1].output_size, target_region_id=target_region_id
        )
        return AcquisitionResult(
            plan.frame,
            self.producer,
            "tesseract",
            self.config_sha256,
            str(artifact),
            sha256,
            blocks,
            attempt=plan.key,
        )
