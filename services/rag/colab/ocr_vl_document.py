"""Colab document runner: one GPU model, incremental pages, resumable evidence."""

import argparse
import hashlib
import importlib.util
import json
import math
import time
import traceback
from importlib.metadata import version
from pathlib import Path


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def run(config):
    import pymupdf as fitz
    from PIL import Image

    source = Path(config["input"])
    root = Path(config["output_root"])
    packages = {
        p: version(p)
        for p in (
            "paddleocr",
            "paddlex",
            "paddlepaddle-gpu",
            "sentencepiece",
            "protobuf",
            "pymupdf",
        )
    }
    policy = {
        k: config[k]
        for k in ("pages", "dpi", "max_render_pixels", "max_pixels", "max_new_tokens")
    }
    policy.update(
        packages=packages,
        runner_sha256=digest(Path(__file__).read_bytes()),
        source_worker_sha256=digest(Path(config["source_worker"]).read_bytes()),
    )
    source_sha = digest(source.read_bytes())
    profile_sha = digest(json.dumps(policy, sort_keys=True).encode())
    output = root / (source_sha[:20] + "-" + profile_sha[:12])
    output.mkdir(parents=True, exist_ok=True)
    progress = Path(config["progress"])
    started = time.monotonic()
    completed = []
    pipeline = None
    weights = None

    def status(stage, **fields):
        value = {
            "stage": stage,
            "updated": time.time(),
            "output": str(output),
            "completed": completed.copy(),
            "seconds": time.monotonic() - started,
            **fields,
        }
        write(progress, value)
        write(output / "status.json", value)
        print(json.dumps(value, ensure_ascii=False), flush=True)

    try:
        pdf = fitz.open(source) if source.suffix.lower() == ".pdf" else None
        try:
            if pdf is not None:
                if pdf.needs_pass:
                    raise ValueError("PDF có mật khẩu")
                pages = (
                    config["pages"]
                    if config["pages"] is not None
                    else list(range(1, len(pdf) + 1))
                )
                if not pages or any(
                    type(p) is not int or not 1 <= p <= len(pdf) for p in pages
                ):
                    raise ValueError(f"Trang không hợp lệ; PDF có {len(pdf)} trang")
            else:
                if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                    raise ValueError("Input phải là PDF hoặc ảnh PNG/JPG/WEBP")
                if config["pages"] not in (None, [1]):
                    raise ValueError("Input ảnh chỉ có một trang")
                pages = [1]
            write(
                output / "document.json",
                {
                    "source_sha256": source_sha,
                    "profile_sha256": profile_sha,
                    "policy": policy,
                    "pages": pages,
                    "publication": "raw evidence; not automatically retrieval eligible",
                },
            )
            for page_number in pages:
                status("RENDERING", page=page_number, total=len(pages))
                image_path = Path(config["local_work"]) / "current-page.png"
                geometry = None
                if pdf is not None:
                    page = pdf[page_number - 1]
                    scale = min(
                        config["dpi"] / 72,
                        math.sqrt(
                            config["max_render_pixels"]
                            / (page.rect.width * page.rect.height)
                        ),
                    )
                    page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).save(
                        image_path
                    )
                    geometry = {"rect": list(page.rect), "rotation": page.rotation}
                else:
                    with Image.open(source) as image:
                        scale = min(
                            1,
                            math.sqrt(
                                config["max_render_pixels"]
                                / (image.width * image.height)
                            ),
                        )
                        image = image.convert("RGB")
                        image = image.resize(
                            (
                                max(1, int(image.width * scale)),
                                max(1, int(image.height * scale)),
                            )
                        )
                        image.save(image_path)
                image_sha = digest(image_path.read_bytes())
                target = output / f"page-{page_number:04d}.json"
                if config["resume"] and target.is_file():
                    try:
                        previous = json.loads(target.read_text(encoding="utf-8"))
                        valid = (
                            previous["schema"] == "deepdoc-model-result:1"
                            and previous["backend"] == "paddle-vl"
                            and previous["source_sha256"] == source_sha
                            and previous["profile_sha256"] == profile_sha
                            and previous["input_sha256"] == image_sha
                            and previous["page"] == page_number
                            and previous["weights_sha256"]
                            and "raw" in previous
                        )
                    except (ValueError, KeyError):
                        valid = False
                    if valid:
                        completed.append(page_number)
                        status("RESUMED", page=page_number, total=len(pages))
                        continue
                if pipeline is None:
                    status("LOADING_MODEL", page=page_number, total=len(pages))
                    import paddle
                    from paddleocr import PaddleOCRVL

                    if (
                        not paddle.is_compiled_with_cuda()
                        or paddle.device.cuda.device_count() < 1
                    ):
                        raise RuntimeError(
                            "Không có Paddle CUDA/GPU; chọn Colab GPU runtime"
                        )
                    paddle.set_device("gpu:0")
                    pipeline = PaddleOCRVL(
                        device="gpu:0",
                        use_doc_orientation_classify=False,
                        use_doc_unwarping=False,
                    )
                    spec = importlib.util.spec_from_file_location(
                        "deepdoc_fingerprints", config["source_worker"]
                    )
                    helper = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(helper)
                    weights = helper.fingerprint_weights("paddle-vl")
                    if not weights:
                        raise RuntimeError("Không tìm thấy weight fingerprints")
                status("INFERENCE", page=page_number, total=len(pages))
                tick = time.monotonic()
                outputs = list(
                    pipeline.predict(
                        str(image_path),
                        max_pixels=config["max_pixels"],
                        max_new_tokens=config["max_new_tokens"],
                        use_queues=False,
                    )
                )
                if len(outputs) != 1:
                    raise ValueError("Mỗi input phải trả đúng một page result")
                raw = outputs[0].json
                if isinstance(raw, str):
                    raw = json.loads(raw)
                write(
                    target,
                    {
                        "schema": "deepdoc-model-result:1",
                        "backend": "paddle-vl",
                        "source_sha256": source_sha,
                        "profile_sha256": profile_sha,
                        "page": page_number,
                        "input_sha256": image_sha,
                        "geometry": geometry,
                        "packages": packages,
                        "weights_sha256": weights,
                        "seconds": time.monotonic() - tick,
                        "raw": raw,
                        "review": "unverified model output; generation limit may truncate content",
                    },
                )
                completed.append(page_number)
                status("PAGE_SUCCESS", page=page_number, total=len(pages))
                del outputs
            status("SUCCESS", total=len(pages))
        finally:
            if pdf is not None:
                pdf.close()
    except BaseException as error:
        status("FAILED", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        if pipeline is not None and hasattr(pipeline, "close"):
            pipeline.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        run(json.loads(Path(args.config).read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001 - CLI failures must print their traceback and return nonzero.
        traceback.print_exc()
        raise SystemExit(1)
