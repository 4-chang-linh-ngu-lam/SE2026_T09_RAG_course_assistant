"""Marker CPU session reused across frames; no hosted model calls."""

import hashlib
import json
import time
import traceback
from importlib.metadata import version
from pathlib import Path

from source_model_worker import fingerprint_weights


def main():
    root = Path("/request")
    models = None
    weights = None
    try:
        while not (root / "stop").exists():
            for request in sorted(root.glob("request-*.json")):
                data = json.loads(request.read_text())
                request.rename(request.with_name("handled-" + request.name))
                output = root / data["output"]
                try:
                    started = time.monotonic()
                    loaded = False
                    load_seconds = 0
                    if models is None:
                        from marker.models import create_model_dict

                        tick = time.monotonic()
                        models = create_model_dict(device="cpu", no_server=True)
                        weights = fingerprint_weights("marker")
                        loaded = True
                        load_seconds = time.monotonic() - tick
                    from marker.converters.pdf import PdfConverter

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
                    source = root / data["input"]
                    raw = converter(str(source)).model_dump(mode="json")
                    result = {
                        "schema": "deepdoc-model-result:1",
                        "backend": "marker",
                        "raw": raw,
                        "packages": {
                            p: version(p)
                            for p in ("marker-pdf", "surya-ocr", "indra-ocr", "torch")
                        },
                        "weights_sha256": weights,
                        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                        "seconds": time.monotonic() - started,
                        "model_loaded": loaded,
                        "model_load_seconds": load_seconds,
                    }
                except Exception as error:  # noqa: BLE001 - safe structured failure; traceback in local container log.
                    traceback.print_exc()
                    result = {
                        "error": "MODEL_EXECUTION_FAILED",
                        "error_type": type(error).__name__,
                    }
                tmp = output.with_suffix(".tmp")
                tmp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
                tmp.replace(output)
            time.sleep(0.1)
    finally:
        if models is not None:
            from marker.models import shutdown_models

            shutdown_models(models)


if __name__ == "__main__":
    main()
