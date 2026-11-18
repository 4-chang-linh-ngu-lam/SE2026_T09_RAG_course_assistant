"""Structured model acquisition via isolated runtimes, sharing Phase 2 contracts."""

import hashlib
import html
import json
import math
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic

from idp.evidence.contracts import (
    DeepDocDiagnostic,
    DeepDocProducer,
    _freeze_json_object,
)
from idp.ocr.backends.tesseract import BackendUnavailable, OCRTimeout
from idp.pdf.acquire import AcquisitionResult, OcrBlock
from idp.pdf.render import digest

from .latex_check import VERSION as LATEX_CHECK_VERSION
from .latex_check import check_latex
from .legacy import legacy_confidence
from .model_worker import FORMULA_MODELS

CONVERSION_VERSION = "advanced-blocks:2+" + LATEX_CHECK_VERSION
# Transports built without an explicit model keep the historical recognizer.
DEFAULT_FORMULA_MODEL = "PP-FormulaNet_plus-S"


@dataclass(frozen=True, slots=True)
class StructuredAcquisitionResult(AcquisitionResult):
    proposals: tuple = ()

    def __post_init__(self):
        super(StructuredAcquisitionResult, self).__post_init__()
        object.__setattr__(
            self, "proposals", tuple(_freeze_json_object(p) for p in self.proposals)
        )


class DockerModelTransport:
    """Opt-in container execution; only the request directory and model cache mount.

    Never mount the Docker socket or repository in the model container. Timeout
    and cancellation force-remove the named container, not only its client.
    """

    def __init__(
        self,
        image,
        backend,
        *,
        timeout_seconds=600,
        memory="5g",
        cpus=2,
        device="cpu",
        model=None,
    ):
        if device != "cpu" and not re.fullmatch(r"gpu:[0-9]+", device):
            raise ValueError("invalid device")
        self.device = device
        self.container_device = "cpu" if device == "cpu" else "gpu:0"
        if backend not in {"marker", "paddle-vl", "paddle-layout", "paddle-formula"}:
            raise ValueError("unsupported model runtime")
        self.image, self.backend = image, backend
        self.timeout_seconds, self.memory, self.cpus = timeout_seconds, memory, cpus
        try:
            result = subprocess.run(
                ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
                capture_output=True,
                text=True,
                check=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BackendUnavailable(
                f"Model runtime image unavailable: {backend}"
            ) from error
        self.cache_family = "marker" if backend == "marker" else "paddle"
        self.identity = {
            "image_id": result.stdout.strip(),
            "backend": backend,
            "worker": "deepdoc-model-result:1",
        }
        if device != "cpu":
            self.identity["device"] = device
        # Formula recognizer choice is part of the producer identity; other
        # backends keep their single pinned model.
        if backend == "paddle-formula":
            model = model or DEFAULT_FORMULA_MODEL
            if model not in FORMULA_MODELS:
                raise ValueError("unsupported formula model")
            self.identity["model"] = model
        elif model is not None:
            raise ValueError("model selection is only supported for paddle-formula")
        self.model = model

    def model_env(self):
        model = getattr(self, "model", None)
        return ["--env", "DEEPDOC_MODEL=" + model] if model else []

    def execute(self, image_bytes, *, deadline):
        seconds = min(self.timeout_seconds, deadline - monotonic())
        if seconds <= 0:
            raise OCRTimeout("model deadline exhausted")
        name = "deepdoc-model-" + uuid.uuid4().hex
        with TemporaryDirectory(prefix="deepdoc-model-") as directory:
            root = Path(directory)
            (root / "input.png").write_bytes(image_bytes)
            command = [
                "docker",
                "run",
                "--name",
                name,
                "--memory",
                self.memory,
                "--cpus",
                str(self.cpus),
                "--mount",
                f"type=bind,source={root},target=/request",
                "--mount",
                f"type=volume,source=deepdoc-{self.cache_family}-{'models' if self.cache_family == 'marker' else 'cache'},target=/root/.cache",
                "--mount",
                f"type=volume,source=deepdoc-{self.cache_family}-{'paddlex' if self.cache_family == 'marker' else 'models'},target=/root/.paddlex",
                self.identity["image_id"],
                "--backend",
                self.backend,
                "--input",
                "/request/input.png",
                "--output",
                "/request/result.json",
            ]
            token = os.environ.get("DEEPDOC_JOB_TOKEN")
            if self.device != "cpu":
                position = command.index(self.identity["image_id"])
                command[position:position] = [
                    "--gpus",
                    "device=" + self.device.split(":")[1],
                    "--env",
                    "DEEPDOC_DEVICE=" + self.container_device,
                ]
            if token and re.fullmatch("[0-9a-f]{32}", token):
                position = command.index(self.identity["image_id"])
                command[position:position] = ["--label", "deepdoc.job=" + token]
            position = command.index(self.identity["image_id"])
            command[position:position] = self.model_env()
            try:
                process = subprocess.run(
                    command, capture_output=True, timeout=seconds, check=False
                )
                if process.returncode:
                    reason = ""
                    try:
                        state = subprocess.run(
                            [
                                "docker",
                                "inspect",
                                name,
                                "--format",
                                "{{.State.OOMKilled}}",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=10,
                            check=False,
                        )
                        if state.returncode == 0 and state.stdout.strip() == "true":
                            reason = "; memory limit exceeded"
                    except (OSError, subprocess.SubprocessError):
                        reason = "; runtime state unavailable"
                    raise BackendUnavailable(
                        f"{self.backend} inference failed (exit {process.returncode}{reason}); no output accepted"
                    )
                output = root / "result.json"
                if not output.is_file() or output.stat().st_size > 32_000_000:
                    raise ValueError("missing/oversized model output")
                return json.loads(output.read_text(encoding="utf-8"))
            except subprocess.TimeoutExpired as error:
                raise OCRTimeout(
                    f"{self.backend} container exceeded deadline"
                ) from error
            finally:
                try:
                    subprocess.run(
                        ["docker", "rm", "-f", name],
                        capture_output=True,
                        timeout=30,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    # Preserve the inference failure if Docker itself is down.
                    # The generated container name is retained in the exception.
                    import warnings

                    warnings.warn(
                        f"Docker cleanup unavailable for {name}",
                        RuntimeWarning,
                        stacklevel=2,
                    )

    def model_identity(self):
        """Inspect installed versions and cached weight bytes without loading models."""
        packages = (
            ("marker-pdf", "surya-ocr", "indra-ocr", "torch")
            if self.backend == "marker"
            else (
                "paddleocr",
                "paddlex",
                getattr(self, "paddle_distribution", "paddlepaddle"),
            )
        )
        code = (
            "import json; from importlib.metadata import version; from model_worker import fingerprint_weights; "
            f"packages={{p:version(p) for p in {packages!r}}}; "
            + (
                f"packages['execution_device']={self.container_device!r}; "
                if hasattr(self, "paddle_distribution")
                else ""
            )
            + f"print(json.dumps(dict(packages=packages,weights=fingerprint_weights({self.backend!r}))))"
        )
        name = "deepdoc-identity-" + uuid.uuid4().hex
        token = os.environ.get("DEEPDOC_JOB_TOKEN", "")
        labels = (
            ["--label", "deepdoc.job=" + token]
            if re.fullmatch("[0-9a-f]{32}", token)
            else []
        )
        try:
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--name",
                    name,
                    *labels,
                    "--memory",
                    "512m",
                    "--cpus",
                    "1",
                    "--mount",
                    f"type=volume,source=deepdoc-{self.cache_family}-{'models' if self.cache_family == 'marker' else 'cache'},target=/root/.cache",
                    "--mount",
                    f"type=volume,source=deepdoc-{self.cache_family}-{'paddlex' if self.cache_family == 'marker' else 'models'},target=/root/.paddlex",
                    "--entrypoint",
                    "python",
                    self.identity["image_id"],
                    "-c",
                    code,
                ],
                capture_output=True,
                text=True,
                timeout=45,
                check=True,
            )
            value = json.loads(result.stdout)
            return {**value, "transport": self.identity} if value["weights"] else None
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            return None
        finally:
            try:
                subprocess.run(
                    ["docker", "rm", "-f", name],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                pass


def marker_blocks(raw):
    pages = raw.get("children", ())
    if len(pages) != 1:
        raise ValueError("one Marker page required for one ImageFrame")
    page = pages[0]

    def walk(node):
        children = node.get("children") or ()
        if children:
            for child in children:
                yield from walk(child)
        else:
            yield node

    return list(walk(page)), page["bbox"]


def paddle_blocks(raw, size):
    data = raw.get("res", raw)
    if "parsing_res_list" in data:
        # Existing adapter preserves Paddle labels/table/formula HTML and does
        # not confuse layout detection score with recognition confidence.
        from idp.documents.paddle import _block_type, _table_html

        blocks = []
        for i, block in enumerate(data["parsing_res_list"]):
            label = _block_type(block.get("block_label", ""))
            content = block.get("block_content", "")
            markup = (
                _table_html(content)
                if label == "Table"
                else "<math>" + html.escape(content.strip("$")) + "</math>"
                if label == "Equation"
                else html.escape(content)
            )
            blocks.append(
                {
                    "id": str(i),
                    "block_type": label,
                    "bbox": block["block_bbox"],
                    "html": markup,
                    "raw": block,
                }
            )
        return blocks, (0, 0, data.get("width", size[0]), data.get("height", size[1]))
    if "rec_formula" in data:
        return [
            {
                "id": "formula:0",
                "block_type": "Equation",
                "bbox": (0, 0, *size),
                "html": "<math>" + html.escape(data["rec_formula"]) + "</math>",
                "raw": data,
            }
        ], (0, 0, *size)
    return [
        {
            "id": str(i),
            "block_type": "LayoutRegion",
            "bbox": b["coordinate"],
            "html": "",
            "raw": b,
        }
        for i, b in enumerate(data.get("boxes", ()))
    ], (0, 0, *size)


class AdvancedBackend:
    @property
    def parallel_safe(self):
        # Docker model containers reserve GBs each; only local transports
        # that declare themselves safe run concurrently.
        return bool(getattr(self.transport, "parallel_safe", False))

    def __init__(self, artifact_dir, transport):
        self.transport, self.artifact_dir = transport, Path(artifact_dir)
        # The block conversion (incl. the LaTeX check) is part of the cached
        # acquisition identity: results converted by older code are not reused.
        self.config_sha256 = digest(
            {"transport": transport.identity, "conversion": CONVERSION_VERSION}
        )
        self._cache_identity = None

    @property
    def cache_identity(self):
        if self._cache_identity is None:
            inspect = getattr(self.transport, "model_identity", None)
            identity = inspect() if inspect else None
            self._cache_identity = digest(identity) if identity else False
        return self._cache_identity or None

    def read(self, image_bytes, source, page, plan, *, deadline, target_region_id=None):
        if (
            hashlib.sha256(image_bytes).hexdigest()
            != plan.frame.steps[-1].output_sha256
        ):
            raise ValueError("advanced input image provenance mismatch")
        if getattr(self.transport, "accepts_dpi", False):
            from .tesseract import frame_dpi

            result = self.transport.execute(
                image_bytes, deadline=deadline, dpi=frame_dpi(plan.frame)
            )
        else:
            result = self.transport.execute(image_bytes, deadline=deadline)
        if (
            result.get("schema") != "deepdoc-model-result:1"
            or result.get("backend") != self.transport.backend
        ):
            raise ValueError("model result identity mismatch")
        if result.get("input_sha256") != hashlib.sha256(image_bytes).hexdigest():
            raise ValueError("model input SHA mismatch")
        expected = getattr(self.transport, "model", None)
        if expected is not None and result.get("model_name", DEFAULT_FORMULA_MODEL) != expected:
            # A worker baked into an older image ignores the model request and
            # loads the historical recognizer; never label its output otherwise.
            raise ValueError("model result does not come from the requested model")
        identity = {
            "packages": result["packages"],
            "weights": result["weights_sha256"],
            "transport": self.transport.identity,
        }
        producer = DeepDocProducer(
            self.transport.backend, digest(result["packages"]), model=digest(identity)
        )
        self._cache_identity = producer.model
        data = json.dumps(result, ensure_ascii=False, sort_keys=True).encode()
        sha = hashlib.sha256(data).hexdigest()
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact = self.artifact_dir / (sha + ".json")
        artifact.write_bytes(data)
        size = plan.frame.steps[-1].output_size
        legacy = self.transport.backend == "legacy-hybrid"
        nodes, page_box = (
            marker_blocks(result["raw"])
            if self.transport.backend in {"marker", "legacy-hybrid"}
            else paddle_blocks(result["raw"], size)
        )
        px, py, right, bottom = page_box
        if right <= px or bottom <= py:
            raise ValueError("invalid model coordinate frame")
        blocks, proposals, diagnostics = [], [], []
        for i, node in enumerate(nodes):
            bbox = tuple(node["bbox"])
            x0, y0, x1, y1 = bbox
            converted = (
                (x0 - px) * size[0] / (right - px),
                (y0 - py) * size[1] / (bottom - py),
                (x1 - px) * size[0] / (right - px),
                (y1 - py) * size[1] / (bottom - py),
            )
            if not all(math.isfinite(v) for v in converted) or not (
                0 <= converted[0] < converted[2] <= size[0]
                and 0 <= converted[1] < converted[3] <= size[1]
            ):
                raise ValueError("model bbox outside image")
            markup = node.get("html", "")
            text = html.unescape(re.sub(r"<[^>]+>", " ", markup)).strip()
            label = node.get("block_type", "Text").split(".")[-1]
            # Only the in-process legacy OCR reports a real recognition score
            # (Tesseract hOCR); model transports never self-certify one.
            score = legacy_confidence(node) if legacy else None
            payload = {
                "kind": label,
                "raw_block": node,
                "pixel_bbox": converted,
                "recognition_confidence_available": score is not None,
                "origin": "model_transcription",
                "order": i,
                "source_sha256": source.report.source_sha256,
                "page": page,
                "render_id": plan.frame.render_id,
                "artifact_sha256": sha,
            }
            if label == "Table":
                payload["table_html"] = markup
            if label in {"Equation", "Formula", "TextInlineMath"}:
                payload["latex"] = (
                    html.unescape(
                        " ".join(
                            re.findall(
                                r"<math[^>]*>(.*?)</math>", markup, flags=re.DOTALL
                            )
                        )
                    )
                    or text
                )
                # Syntax/loop check only: a passing formula is still
                # structure_unverified and never retrieval eligible here.
                payload["latex_check"] = check_latex(payload["latex"])
                if payload["latex_check"]["status"] != "syntax_ok":
                    diagnostics.append(
                        DeepDocDiagnostic(
                            "FORMULA_LATEX_REVIEW",
                            "Model LaTeX failed syntax/repetition checks; kept for review",
                            metadata={
                                "page": page,
                                "block": str(node.get("id", i)),
                                "reasons": list(payload["latex_check"]["reasons"]),
                            },
                        )
                    )
            if label in {"Picture", "Figure", "Diagram", "Chart"}:
                payload["origin"] = "model_inference"
                payload["model_description"] = text
            proposals.append(payload)
            if text and label not in {
                "Picture",
                "Figure",
                "Diagram",
                "Chart",
                "LayoutRegion",
            }:
                # Unknown recognition confidence is conservatively 0. Layout
                # confidence is never substituted; native good pages bypass OCR.
                blocks.append(
                    OcrBlock(
                        str(node.get("id", i)),
                        text,
                        converted,
                        score if score is not None else 0,
                        "FORMULA" if label == "Equation" else "PARAGRAPH",
                        target_region_id,
                        payload,
                    )
                )
        return StructuredAcquisitionResult(
            plan.frame,
            producer,
            self.transport.backend,
            self.config_sha256,
            str(artifact),
            sha,
            tuple(blocks),
            tuple(diagnostics),
            attempt=plan.key,
            proposals=tuple(proposals),
        )


def acquisition_verifier(result, *, capabilities):
    """Admit a completed source-bound reread through the verification runtime.

    Acquisition already paid for inference/rendering through BackendAcquirer.
    This only appends alternatives from that result; it cannot certify lexical
    correctness, change native topology or promote a model description to text.
    """
    from dataclasses import replace

    from idp.evidence.contracts import (
        DeepDocCandidate,
        DeepDocContentOrigin,
        DeepDocEvidence,
    )
    from idp.pdf.merge import overlap
    from idp.pdf.native.engine import PdfWorkResponse
    from idp.pdf.verify_runtime import VerificationBackend

    def execute(request, trace, *, timeout_seconds):
        if timeout_seconds <= 0:
            raise OCRTimeout("verification deadline exhausted")
        if (
            request.source_sha256 != result.frame.source_sha256
            or trace.region.locations[0].page != result.frame.page
        ):
            raise ValueError("verification acquisition source/page mismatch")
        location = trace.region.locations[0]
        if location.bbox is None:
            return PdfWorkResponse(request.id, request.input_sha256)
        box = location.bbox
        native_box = (box.x0, box.y0, box.x1, box.y1)
        evidence, candidates = [], []
        for block in result.blocks:
            if (
                block.target_region_id is not None
                and block.target_region_id != trace.region.id
            ):
                continue
            if overlap(native_box, result.frame.to_pdf_pt(block.bbox_px))[1] < 0.8:
                continue
            if block.payload.get("origin") == "model_inference":
                continue
            identity = digest([request.id, result.artifact_sha256, block.key])
            ev = DeepDocEvidence(
                "evidence:reread:" + identity,
                trace.region.id,
                DeepDocContentOrigin.SOURCE_TRANSCRIPTION,
                result.producer,
                result.artifact_sha256,
                result.frame.source_sha256,
                independence_family=result.family,
            )
            evidence.append(ev)
            candidates.append(
                DeepDocCandidate(
                    "candidate:reread:" + identity,
                    trace.region.id,
                    ev.origin,
                    result.producer,
                    (ev.id,),
                    block.text,
                )
            )
        if not candidates:
            return PdfWorkResponse(request.id, request.input_sha256)
        if len(evidence) > 32 or len(candidates) > 16:
            raise ValueError("verification alternatives exceed bounded response")
        updated = replace(
            trace,
            evidence=(*trace.evidence, *evidence),
            candidates=(*trace.candidates, *candidates),
        )
        return PdfWorkResponse(request.id, request.input_sha256, trace=updated)

    return VerificationBackend(
        result.producer, result.family, tuple(capabilities), execute
    )
