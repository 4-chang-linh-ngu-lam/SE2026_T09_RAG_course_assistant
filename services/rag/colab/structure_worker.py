"""Persistent Colab GPU worker; stdin requests, atomic file responses, no VLM."""

import argparse
import hashlib
import importlib.util
import json
import sys
import time
import traceback
from importlib.metadata import version
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--helper", required=True)
    args = parser.parse_args()
    pipeline = None
    weights = None
    spec = importlib.util.spec_from_file_location("weight_inventory", args.helper)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            target = Path(request["output"])
            try:
                started = time.monotonic()
                if pipeline is None:
                    import paddle
                    from paddleocr import PPStructureV3

                    if (
                        not paddle.is_compiled_with_cuda()
                        or paddle.device.cuda.device_count() < 1
                    ):
                        raise RuntimeError("GPU CUDA unavailable")
                    pipeline = PPStructureV3(
                        device="gpu:0",
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                        use_textline_orientation=False,
                        use_table_recognition=True,
                        use_formula_recognition=True,
                        formula_recognition_model_name="PP-FormulaNet_plus-S",
                        use_seal_recognition=False,
                        use_chart_recognition=False,
                    )
                    weights = helper.fingerprint_weights("paddle-structure")
                    if not weights:
                        raise RuntimeError("Model weight inventory missing")
                outputs = list(pipeline.predict(request["input"]))
                if len(outputs) != 1:
                    raise ValueError("one rendered frame required")
                raw = outputs[0].json
                if isinstance(raw, str):
                    raw = json.loads(raw)
                result = {
                    "schema": "deepdoc-model-result:1",
                    "backend": "paddle-structure",
                    "input_sha256": hashlib.sha256(
                        Path(request["input"]).read_bytes()
                    ).hexdigest(),
                    "packages": {
                        p: version(p)
                        for p in ("paddleocr", "paddlex", "paddlepaddle-gpu")
                    },
                    "weights_sha256": weights,
                    "seconds": time.monotonic() - started,
                    "raw": raw,
                }
            except Exception as error:  # noqa: BLE001 - return diagnostic without accepting output.
                traceback.print_exc()
                result = {"error": f"{type(error).__name__}: {error}"}
            temporary = target.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            temporary.replace(target)
    finally:
        if pipeline is not None and hasattr(pipeline, "close"):
            pipeline.close()


if __name__ == "__main__":
    main()
