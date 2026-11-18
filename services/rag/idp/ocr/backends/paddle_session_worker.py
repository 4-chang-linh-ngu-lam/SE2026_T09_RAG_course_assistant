"""File RPC Paddle layout/formula session; one loaded model, bounded inputs."""

import gc
import hashlib
import json
import os
import time
from importlib.metadata import version
from pathlib import Path

try:
    from source_model_worker import fingerprint_weights, formula_model
except ModuleNotFoundError:
    from model_worker import fingerprint_weights, formula_model


def main():
    import paddle
    from paddleocr import FormulaRecognition, LayoutDetection
    from PIL import Image

    root = Path("/request")
    backend = os.environ["DEEPDOC_BACKEND"]
    device = os.environ.get("DEEPDOC_DEVICE", "cpu")
    if backend not in {"paddle-layout", "paddle-formula"}:
        raise ValueError("session supports layout/formula only")
    model = "PP-DocLayoutV3" if backend == "paddle-layout" else formula_model()
    if device != "cpu" and (
        not paddle.is_compiled_with_cuda() or not paddle.device.cuda.device_count()
    ):
        raise RuntimeError("GPU requested but CUDA unavailable")
    pipeline = None
    paddle.device.set_device(device)
    weights = None
    try:
        while not (root / "stop").exists():
            for path in sorted(root.glob("request-*.json")):
                request = json.loads(path.read_text())
                path.rename(path.with_name("handled-" + path.name))
                target = root / request["output"]
                try:
                    source = root / request["input"]
                    if source.parent != root or target.parent != root:
                        raise ValueError("invalid session path")
                    with Image.open(source) as image:
                        if image.width * image.height > int(
                            os.environ.get("DEEPDOC_MAX_PIXELS", "1000000")
                        ):
                            raise ValueError("Paddle image exceeds pixel budget")
                    loaded = pipeline is None
                    started = time.monotonic()
                    if loaded:
                        constructor = (
                            LayoutDetection
                            if backend == "paddle-layout"
                            else FormulaRecognition
                        )
                        pipeline = constructor(
                            model_name=model,
                            device=device,
                            enable_mkldnn=False,
                        )
                        weights = fingerprint_weights(backend, model)
                    load_seconds = time.monotonic() - started if loaded else 0
                    outputs = list(pipeline.predict(str(source)))
                    if len(outputs) != 1:
                        raise ValueError("one result required")
                    raw = outputs[0].json
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    result = {
                        "schema": "deepdoc-model-result:1",
                        "backend": backend,
                        "packages": {p: version(p) for p in ("paddleocr", "paddlex")},
                        "weights_sha256": weights,
                        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "raw": raw,
                        "model_name": model,
                        "model_loaded": loaded,
                        "model_load_seconds": load_seconds,
                        "execution_device": device,
                    }
                    result["packages"][
                        "paddlepaddle-gpu"
                        if paddle.is_compiled_with_cuda()
                        else "paddlepaddle"
                    ] = paddle.__version__
                    result["packages"]["execution_device"] = device
                    result['cuda_compiled'] = paddle.is_compiled_with_cuda()
                    result['active_device'] = paddle.device.get_device()
                except Exception as error:  # noqa: BLE001 - isolate one failed inference; return only safe error type.
                    oom = (
                        "out of memory" in str(error).lower()
                        or "resourceexhausted" in type(error).__name__.lower()
                    )
                    result = {
                        "error": "PADDLE_GPU_OOM"
                        if oom and device != "cpu"
                        else type(error).__name__
                    }
                    if pipeline is not None:
                        if hasattr(pipeline, "close"):
                            pipeline.close()
                        pipeline = None
                    gc.collect()
                    if device != "cpu":
                        paddle.device.cuda.empty_cache()
                temp = target.with_suffix(".tmp")
                temp.write_text(
                    json.dumps(result, ensure_ascii=False), encoding="utf-8"
                )
                temp.replace(target)
            time.sleep(0.03)
    finally:
        if pipeline is not None and hasattr(pipeline, "close"):
            pipeline.close()


if __name__ == "__main__":
    main()
