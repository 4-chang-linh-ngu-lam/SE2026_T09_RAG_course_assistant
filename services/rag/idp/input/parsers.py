"""Parser provenance for ingestion.

The canonical document records which parser produced each page/block. This
keeps OCR/layout providers interchangeable and makes fallback auditable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ParserSpec:
    name: str
    version: str = "unknown"
    kind: str = "ocr"
    backend: str | None = None
    confidence_available: bool = False
    layout_confidence_available: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


def detect_parser(marker_path: str | Path, fallback_meta: dict | None = None) -> ParserSpec:
    if fallback_meta:
        return ParserSpec(
            name=str(fallback_meta.get("engine") or "fallback"),
            version=str(fallback_meta.get("version") or "unknown"),
            kind="fallback",
            backend=str(fallback_meta.get("backend") or "unknown"),
            confidence_available=bool(fallback_meta.get("confidence_available")),
            layout_confidence_available=bool(fallback_meta.get("layout_confidence_available")),
        )
    try:
        data = json.loads(Path(marker_path).read_text(encoding="utf-8"))
    except Exception:
        return ParserSpec(name="unknown")
    metadata = data.get("metadata") or {}
    name = metadata.get("engine") or data.get("engine") or "marker"
    return ParserSpec(
        name=str(name),
        version=str(metadata.get("version") or "unknown"),
        kind=str(metadata.get("kind") or ("ocr" if "marker" in str(name) else "external")),
        backend=metadata.get("backend"),
        confidence_available=bool(metadata.get("confidence_available")),
        layout_confidence_available=bool(metadata.get("layout_confidence_available")),
    )


def merge_parser_specs(specs: list[ParserSpec]) -> dict:
    names = sorted({spec.name for spec in specs}) or ["unknown"]
    sources = {}
    for spec in specs:
        entry = spec.as_dict()
        previous = sources.get(spec.name)
        if previous:
            entry["confidence_available"] &= previous["confidence_available"]
            entry["layout_confidence_available"] &= previous["layout_confidence_available"]
        sources[spec.name] = entry
    return {
        "name": names[0] if len(names) == 1 else "mixed",
        "sources": sources,
        "confidence_available": bool(specs) and all(spec.confidence_available for spec in specs),
        "layout_confidence_available": any(spec.layout_confidence_available for spec in specs),
    }
