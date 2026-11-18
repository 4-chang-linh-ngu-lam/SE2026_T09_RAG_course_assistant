"""Real book layout/formula benchmark. Output is unverified, never indexed."""

import argparse
import json
import math
import subprocess
import threading
import time
from io import BytesIO
from pathlib import Path

import pymupdf as fitz
from idp.pdf.formula_regions import formula_boxes
from idp.runtime.paddle_pool import PaddleSessionTransport
from PIL import Image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", type=int, nargs="+", default=[87])
    parser.add_argument("--device", choices=["cpu", "gpu:0"], default="cpu")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--layout-only", action="store_true")
    parser.add_argument("--render-max-pixels", type=int, default=1000000)
    args = parser.parse_args()
    if not 1 <= args.render_max_pixels <= 4000000:
        raise ValueError("render budget must be between 1 and4M pixels")
    args.out.mkdir(parents=True, exist_ok=True)
    layout = PaddleSessionTransport(
        "paddle-layout",
        image="lumi-rag-paddle:gpu"
        if args.layout_only and args.device != "cpu"
        else "lumi-rag-paddle:phase4",
        device=args.device if args.layout_only else "cpu",
        timeout_seconds=300,
        max_pixels=args.render_max_pixels,
    )
    formula = PaddleSessionTransport(
        "paddle-formula",
        image="lumi-rag-paddle:gpu"
        if args.device != "cpu"
        else "lumi-rag-paddle:phase4",
        device=args.device,
        max_pixels=262144,
        timeout_seconds=300,
        cpu_fallback=False,
    )
    samples = []
    done = threading.Event()

    def monitor():
        while not done.wait(0.5):
            row = {"time": time.time()}
            for name, session in [("layout", layout), ("formula", formula)]:
                if session.name:
                    r = subprocess.run(
                        [
                            "docker",
                            "stats",
                            "--no-stream",
                            "--format",
                            "{{.MemUsage}}",
                            session.name,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=8,
                        check=False,
                    )
                    row[name + "_memory"] = r.stdout.strip()
            gpu = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            row["gpu_global_mib_util"] = gpu.stdout.strip()
            samples.append(row)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    rows = []
    try:
        with fitz.open(args.pdf) as pdf:
            for page_number in args.pages:
                page = pdf[page_number - 1]
                scale = min(
                    4,
                    0.99
                    * math.sqrt(
                        args.render_max_pixels / (page.rect.width * page.rect.height)
                    ),
                )
                data = page.get_pixmap(
                    matrix=fitz.Matrix(scale, scale), alpha=False
                ).tobytes("png")
                with Image.open(BytesIO(data)) as im:
                    start = time.monotonic()
                    detection = layout.execute(data, deadline=start + 300)
                    (args.out / f"page-{page_number}-layout.json").write_text(
                        json.dumps(detection, ensure_ascii=False), encoding="utf-8"
                    )
                    boxes = formula_boxes(detection["raw"], im.size, limit=8)
                    rows.append(
                        {
                            "page": page_number,
                            "stage": "layout",
                            "seconds": time.monotonic() - start,
                            "formula_regions": len(boxes),
                        }
                    )
                    for n, box in enumerate([] if args.layout_only else boxes):
                        with im.crop(box) as crop:
                            if crop.width * crop.height > 262144:
                                ratio = math.sqrt(262144 / (crop.width * crop.height))
                                crop.thumbnail(
                                    (
                                        max(1, int(crop.width * ratio)),
                                        max(1, int(crop.height * ratio)),
                                    )
                                )
                            buffer = BytesIO()
                            crop.save(buffer, format="PNG")
                            image = buffer.getvalue()
                            (args.out / f"page-{page_number}-crop-{n}.png").write_bytes(
                                image
                            )
                            start = time.monotonic()
                            result = formula.execute(image, deadline=start + 300)
                            (
                                args.out / f"page-{page_number}-formula-{n}.json"
                            ).write_text(
                                json.dumps(result, ensure_ascii=False), encoding="utf-8"
                            )
                            rows.append(
                                {
                                    "page": page_number,
                                    "stage": "formula",
                                    "region": n,
                                    "pixels": crop.width * crop.height,
                                    "bbox_page_pixels": box,
                                    "seconds": time.monotonic() - start,
                                    "device": result.get("execution_device"),
                                    "raw": result["raw"],
                                }
                            )
                (args.out / "measurements.json").write_text(
                    json.dumps(
                        {
                            "device": args.device,
                            "rows": rows,
                            "layout_model_loads": layout.model_loads,
                            "formula_model_loads": formula.model_loads,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
    finally:
        done.set()
        thread.join(timeout=20)
        layout.close()
        formula.close()
        (args.out / "resource-samples.json").write_text(
            json.dumps(samples, indent=2), encoding="utf-8"
        )
    print(
        json.dumps(
            {
                "rows": len(rows),
                "layout_model_loads": layout.model_loads,
                "formula_model_loads": formula.model_loads,
            }
        )
    )


if __name__ == "__main__":
    main()
