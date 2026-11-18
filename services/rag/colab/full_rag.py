"""Run repository DeepDoc -> publication -> chunking/SQLite/BM25 on Colab.

Core and Paddle run in separate Python environments. Protected acquisition hook
adds typed structured acquisitions before the existing merger/finalizer.
"""

import argparse
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from idp.ocr.backends.advanced import AdvancedBackend
from idp.pdf.acquire import AcquisitionRequest, BackendAcquirer
from idp.pdf.service import DeepDocConfig, DeepDocService, write_json
from idp.publish import iter_retrievable_blocks, to_v1
from retrieval.canonical_harness import LocalRagIndex, build_chunks, resolve_citation


class StructureTransport:
    backend = "paddle-structure"

    def __init__(self, config, output):
        self.config = config
        self.output = output
        self.process = None
        self.log = None
        self.ledger = None
        self.identity = {
            "backend": self.backend,
            "runtime": "isolated-colab-gpu",
            "worker_sha256": hashlib.sha256(
                Path(config["gpu_worker"]).read_bytes()
            ).hexdigest(),
        }
        self.calls = 0

    def execute(self, image_bytes, *, deadline):
        # This reserve charges GPU work, in addition to the existing CPU admission.
        key = "structure:" + uuid.uuid4().hex
        self.ledger.reserve(key, resource="GPU")
        ok = False
        try:
            if self.process is None:
                self.log = (self.output / "structure-worker.log").open(
                    "w", encoding="utf-8"
                )
                env = {**os.environ, **self.config["model_env"]}
                self.process = subprocess.Popen(
                    [
                        self.config["model_python"],
                        self.config["gpu_worker"],
                        "--helper",
                        self.config["source_worker"],
                    ],
                    stdin=subprocess.PIPE,
                    stdout=self.log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    start_new_session=False,
                )
            folder = Path(self.config["work"]) / "rpc"
            folder.mkdir(exist_ok=True)
            image = folder / (key.replace(":", "-") + ".png")
            target = image.with_suffix(".json")
            image.write_bytes(image_bytes)
            self.process.stdin.write(
                json.dumps({"input": str(image), "output": str(target)}) + "\n"
            )
            self.process.stdin.flush()
            while not target.is_file():
                if self.process.poll() is not None:
                    raise RuntimeError("GPU worker exited; see structure-worker.log")
                if time.monotonic() >= deadline:
                    self.close()
                    raise TimeoutError("GPU structure acquisition deadline")
                time.sleep(0.2)
            result = json.loads(target.read_text(encoding="utf-8"))
            if "error" in result:
                raise RuntimeError(result["error"])
            self.calls += 1
            ok = True
            return result
        finally:
            self.ledger.settle(key, ok)

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.stdin.close()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None


class FullDocumentService(DeepDocService):
    def __init__(self, config, transport):
        super().__init__(config)
        self.transport = transport

    def _acquire(self, source, native, page_plan, out, ledger, backend):
        # Preserve the established rendering/cropping, budgets and Tesseract path.
        extra = []
        transport = self.transport
        transport.ledger = ledger
        advanced = AdvancedBackend(out / "structure_raw", transport)

        class Combined:
            config_sha256 = backend.config_sha256

            def read(self, image, s, p, plan, *, deadline, target_region_id=None):
                text = backend.read(
                    image,
                    s,
                    p,
                    plan,
                    deadline=deadline,
                    target_region_id=target_region_id,
                )
                executor = BackendAcquirer(
                    lambda ss, pp, request, deadline: advanced.read(
                        image,
                        ss,
                        pp,
                        request,
                        deadline=min(deadline, time.monotonic() + self_timeout),
                        target_region_id=target_region_id,
                    ),
                    ledger,
                    render_precharged=True,
                )
                extra.append(
                    executor.acquire_page(
                        s,
                        p,
                        AcquisitionRequest(plan.key + ":structure", plan.frame),
                        deadline=deadline,
                    )
                )
                return text

        self_timeout = self.config.ocr_timeout_seconds
        acquisitions, logs = super()._acquire(
            source, native, page_plan, out, ledger, Combined()
        )
        return acquisitions + extra, logs


def run(config):
    output = Path(config["output"])
    output.mkdir(parents=True, exist_ok=True)
    source = Path(config["input"])
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    transport = StructureTransport(config, output)
    from idp.pdf.native.preflight import PdfSource

    with PdfSource(source.read_bytes()) as opened:
        count = len(opened.geometry)
    settings = DeepDocConfig(
        engine="unified",
        canonical_version=2,
        language="vie+eng",
        ocr_backend="tesseract",
        document_version="sha256:" + source_sha,
        dpi=config["dpi"],
        max_pixels=config["max_pixels"],
        timeout_seconds=config["document_timeout"],
        ocr_timeout_seconds=config["page_timeout"],
        max_calls=max(100, count * 30),
        max_gpu_calls=max(10, count * 10),
        max_calls_per_page=30,
        max_regions=max(100, count * 10),
        max_total_pixels=max(100_000_000, count * config["max_pixels"] * 3),
    )
    print(
        "START DeepDoc",
        count,
        "pages; native/Tesseract + PP-Structure/FormulaNet-S",
        flush=True,
    )
    try:
        canonical = FullDocumentService(settings, transport).process_pdf(
            source, output / "deepdoc"
        )
    finally:
        transport.close()
    eligible = list(iter_retrievable_blocks(canonical))
    write_json(output / "canonical-v1-filtered.json", to_v1(canonical))
    chunks = build_chunks(canonical)
    write_json(output / "chunks.json", chunks)
    index = LocalRagIndex(output / "rag.sqlite3")
    indexed = index.index(canonical)

    # Explicit local-owner grant for ONLY the document supplied in this notebook.
    def local_owner(actor, sha, version):
        return (
            actor == "colab-local-owner"
            and sha == canonical["source_sha256"]
            and version == canonical["document_version"]
        )

    hits = index.retrieve(
        config["query"], actor="colab-local-owner", access_check=local_owner, top_k=5
    )
    resolved = [
        {"hit": hit, "citations": resolve_citation(hit, canonical)} for hit in hits
    ]
    write_json(output / "retrieval.json", resolved)
    summary = {
        "status": "SUCCESS",
        "pages": count,
        "eligible_blocks": len(eligible),
        "indexed_chunks": indexed,
        "gpu_structure_calls": transport.calls,
        "hits": len(hits),
        "citation_validation": "PASS for returned hits" if hits else "NO_HITS",
        "retrieval_backend": "existing LocalRagIndex SQLite + FieldedBM25; local integration harness",
        "model_policy": "unverified table/formula alternatives preserved; never auto-published",
        "output": str(output),
    }
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    run(json.loads(Path(args.config).read_text(encoding="utf-8")))
