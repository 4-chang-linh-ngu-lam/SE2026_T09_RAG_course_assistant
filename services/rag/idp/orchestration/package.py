"""Build the source-only package uploaded by the Colab notebooks."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


def build_archive(destination: str | Path) -> Path:
    root = Path(__file__).resolve().parents[1]  # idp/, not idp/orchestration/
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            excluded = {
                "chunk.py", "export_audit.py", "table_evidence.py", "region_eval.py",
                "audit.py", "evaluate.py", "review_report.py", "structure_eval.py",
            }
            for source in sorted(root.rglob("*")):
                if (not source.is_file() or source.suffix not in {".py", ".md", ".txt"}
                        or source.name in excluded or "__pycache__" in source.parts):
                    continue
                relative = source.relative_to(root)
                entry = zipfile.ZipInfo(f"idp/{relative.as_posix()}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, source.read_bytes())
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("idp_tools.zip"))
    args = parser.parse_args()
    print(build_archive(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
