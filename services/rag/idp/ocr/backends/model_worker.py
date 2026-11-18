"""Isolated model runner. Only local model inference; no hosted OCR/LLM APIs.

Run in the dedicated model image or interpreter with --backend and --input.
The parent owns source/frame contracts, deadlines and the shared ledger.
"""

import argparse
import hashlib
import json
import os
import time
from importlib.metadata import version
from pathlib import Path

# Formula recognizers the workers may load; checked on both sides of the
# container boundary. Measured trade-offs: docs/deepdoc/ocr-quality/README.md.
FORMULA_MODELS = (
    "PP-FormulaNet_plus-S",
    "PP-FormulaNet_plus-M",
    "PP-FormulaNet_plus-L",
)


def formula_model():
    model = os.environ.get("DEEPDOC_MODEL", "PP-FormulaNet_plus-S")
    if model not in FORMULA_MODELS:
        raise ValueError("unsupported formula model")
    return model


def fingerprint_weights(backend, model=None):
    """SHA-256 of cached weight files; ``model`` limits it to that model's files.

    Without ``model`` every cached file of the backend's family is hashed, so
    adding another model to the shared cache would change the identity of the
    one actually loaded.
    """
    records = {}
    for directory in (
        Path.home() / ".cache",
        Path.home() / ".paddlex",
        Path.home() / ".paddleocr",
    ):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if model is not None and model not in path.parts:
                continue
            if backend == "paddle-layout" and "PP-DocLayoutV3" not in str(path):
                continue
            if backend == "paddle-formula" and "PP-FormulaNet" not in str(path):
                continue
            if backend == "paddle-vl" and not any(
                name in str(path) for name in ("PaddleOCR-VL", "PP-DocLayout")
            ):
                continue
            if path.is_file() and path.suffix in {
                ".onnx",
                ".safetensors",
                ".pdiparams",
                ".gguf",
                ".bin",
            }:
                digest = hashlib.sha256()
                with path.open("rb") as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(chunk)
                records[str(path.relative_to(directory))] = digest.hexdigest()
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        choices=("marker", "paddle-vl", "paddle-layout", "paddle-formula"),
        required=True,
    )
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    started = time.monotonic()
    if args.backend == "marker":
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict, shutdown_models

        models = create_model_dict(device="cpu", no_server=True)
        try:
            converter = PdfConverter(
                artifact_dict=models,
                renderer="marker.renderers.json.JSONRenderer",
                config={
                    "mode": "fast",
                    "use_llm": False,
                    "pdftext_workers": 1,
                    "force_ocr": True,
                },
            )
            raw = converter(args.input).model_dump(mode="json")
        finally:
            shutdown_models(models)
        packages = {
            p: version(p) for p in ("marker-pdf", "surya-ocr", "indra-ocr", "torch")
        }
    else:
        os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
        device = os.environ.get("DEEPDOC_DEVICE", "cpu")
        from paddleocr import FormulaRecognition, LayoutDetection, PaddleOCRVL

        if args.backend == "paddle-vl":
            pipeline = PaddleOCRVL(
                device=device,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
            )
        elif args.backend == "paddle-layout":
            pipeline = LayoutDetection(
                model_name="PP-DocLayoutV3", device=device, enable_mkldnn=False
            )
        else:
            pipeline = FormulaRecognition(
                model_name=formula_model(), device=device, enable_mkldnn=False
            )
        try:
            options = (
                {"max_pixels": 262144, "max_new_tokens": 256, "use_queues": False}
                if args.backend == "paddle-vl"
                else {}
            )
            outputs = list(pipeline.predict(args.input, **options))
            if len(outputs) != 1:
                raise ValueError("one image result required")
            raw = outputs[0].json
            if isinstance(raw, str):
                raw = json.loads(raw)
        finally:
            if hasattr(pipeline, "close"):
                pipeline.close()
        import paddle

        packages = {
            p: version(p)
            for p in (
                "paddleocr",
                "paddlex",
                "paddlepaddle-gpu"
                if paddle.is_compiled_with_cuda()
                else "paddlepaddle",
            )
        }
    weights = fingerprint_weights(
        args.backend, formula_model() if args.backend == "paddle-formula" else None
    )
    output = {
        "schema": "deepdoc-model-result:1",
        "backend": args.backend,
        "packages": packages,
        "weights_sha256": weights,
        "input_sha256": hashlib.sha256(Path(args.input).read_bytes()).hexdigest(),
        "seconds": time.monotonic() - started,
        "raw": raw,
    }
    if args.backend == "paddle-formula":
        output["model_name"] = formula_model()
    Path(args.output).write_text(
        json.dumps(output, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
