"""Fault injection subprocess; markers contain no source text."""

import argparse
import json
import time
from pathlib import Path

from idp_test_backends import FixtureOcr, fixture_backend_registry
from idp.pdf.native.engine import PdfParsingEngine
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.runtime.cache import StageCache


def main():
    parser = argparse.ArgumentParser()
    for name in ("input", "out", "cache", "marker", "moment"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()

    def pause():
        Path(args.marker).write_text("READY")
        while True:
            time.sleep(0.1)

    if args.moment == "after-ocr":
        original = PdfParsingEngine.finalize

        def finalize(*a, **kw):
            pause()
            return original(*a, **kw)

        PdfParsingEngine.finalize = finalize
    elif args.moment == "mid-page":
        original = FixtureOcr.read

        def read(self, image, source, page, *a, **kw):
            if page == 2:
                pause()
            return original(self, image, source, page, *a, **kw)

        FixtureOcr.read = read
    elif args.moment == "output":
        import idp.pdf.service as module

        original = module.write_json

        def write(path, value):
            if Path(path).name == "canonical.json":
                Path(str(path) + ".tmp").write_text("{partial")
                pause()
            return original(path, value)

        module.write_json = write
    # Serial OCR: the test interrupts at a precise page boundary ("page 1
    # finished, page 2 in flight"), which concurrent pages would blur.
    cfg = DeepDocConfig(
        engine="unified", canonical_version=2, dpi=144, ocr_workers=1
    )
    cache = StageCache(args.cache)
    doc = DeepDocService(
        cfg, stage_cache=cache, backend_registry=fixture_backend_registry(FixtureOcr)
    ).process_pdf(args.input, args.out)
    print(json.dumps({"cache": cache.stats, "schema": doc["schema_version"]}))


if __name__ == "__main__":
    main()
