"""External runtime and Python dependency compatibility probing."""

from __future__ import annotations

import argparse
import copy
import importlib.metadata as importlib_metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

try:
    from packaging.version import Version
except ImportError:  # pragma: no cover - fallback when packaging is absent
    Version = None  # type: ignore[assignment]

RUNTIME_COMPATIBILITY_SPEC: dict[str, Any] = {
    "schema_version": "idp-runtime-compat-1",
    "python": {"min": "3.12", "max_exclusive": "3.14"},
    "packages": {
        "pymupdf": {
            "aliases": ("pymupdf", "PyMuPDF"),
            "min": "1.25",
            "max_exclusive": "3.0",
            "required": True,
        },
        "pdfplumber": {
            "aliases": ("pdfplumber",),
            "min": "0.11",
            "max_exclusive": "1.0",
            "required": True,
        },
        "opencv-python-headless": {
            "aliases": ("opencv-python-headless", "opencv-python"),
            "min": "4.10",
            "max_exclusive": "6.0",
            "required": True,
        },
        "pillow": {
            "aliases": ("pillow", "Pillow"),
            "min": "11.0",
            "max_exclusive": "14.0",
            "required": True,
        },
        "numpy": {
            "aliases": ("numpy",),
            "min": "2.0",
            "max_exclusive": "3.0",
            "required": True,
        },
        "python-docx": {
            "aliases": ("python-docx",),
            "min": "1.1",
            "max_exclusive": "2.0",
            "required": False,
        },
        "python-pptx": {
            "aliases": ("python-pptx",),
            "min": "1.0",
            "max_exclusive": "2.0",
            "required": False,
        },
        "openpyxl": {
            "aliases": ("openpyxl",),
            "min": "3.1",
            "max_exclusive": "4.0",
            "required": False,
        },
        "pypandoc-binary": {
            "aliases": ("pypandoc-binary", "pypandoc"),
            "min": "1.13",
            "max_exclusive": "2.0",
            "required": False,
        },
    },
    "binaries": {
        "tesseract": {"min": "4.0", "required": False},
        "pandoc": {"min": "2.11", "required": False},
        "pdftoppm": {"min": "0.80", "required": False},
    },
}

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)+)")
_CACHE_LOCK = threading.Lock()
_CACHED_REPORTS: dict[tuple[bool, tuple[str, ...]], dict[str, Any]] = {}


def _parse_version(raw: str) -> Any:
    cleaned = raw.strip().lstrip("vV")
    if Version is not None:
        try:
            return Version(cleaned)
        except Exception:
            pass
    match = _VERSION_RE.search(cleaned)
    if not match:
        return None
    parts = [int(p) for p in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:4])


def _version_in_bounds(raw: str, min_ver: str | None, max_excl: str | None) -> bool | None:
    parsed = _parse_version(raw)
    if parsed is None:
        return None
    if min_ver is not None:
        low = _parse_version(min_ver)
        if low is not None and parsed < low:
            return False
    if max_excl is not None:
        high = _parse_version(max_excl)
        if high is not None and parsed >= high:
            return False
    return True


def _dist_version(aliases: tuple[str, ...]) -> tuple[str | None, str | None]:
    for name in aliases:
        try:
            return name, importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            continue
    return None, None


def _probe_tesseract(required_langs: tuple[str, ...]) -> dict[str, Any]:
    path = shutil.which("tesseract")
    tessdata_prefix = os.environ.get("TESSDATA_PREFIX")
    warnings: list[str] = []
    if tessdata_prefix:
        try:
            if not Path(tessdata_prefix).exists():
                warnings.append(f"TESSDATA_PREFIX points to nonexistent path: {tessdata_prefix}")
        except OSError as exc:
            warnings.append(
                f"TESSDATA_PREFIX is inaccessible ({type(exc).__name__}): {tessdata_prefix}"
            )

    if not path:
        return {
            "available": False,
            "path": None,
            "version": None,
            "compatible": False,
            "languages": [],
            "missing_required_languages": list(required_langs),
            "tessdata_prefix": tessdata_prefix,
            "warnings": warnings,
        }

    version_str: str | None = None
    try:
        proc = subprocess.run(
            [path, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        match = _VERSION_RE.search(combined)
        if match:
            version_str = match.group(1)
    except Exception as exc:
        warnings.append(f"tesseract --version failed: {type(exc).__name__}")

    langs: list[str] = []
    list_failed = False
    try:
        proc = subprocess.run(
            [path, "--list-langs"], capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        if proc.returncode != 0:
            list_failed = True
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            if detail:
                warnings.append(f"tesseract --list-langs failed: {detail[-1][:160]}")
        else:
            langs = [
                line.strip()
                for line in proc.stdout.splitlines()[1:]
                if line.strip() and not line.startswith("List of")
            ]
    except Exception as exc:
        list_failed = True
        warnings.append(f"tesseract --list-langs failed: {type(exc).__name__}")

    missing_langs = [lang for lang in required_langs if lang and lang not in langs]
    if missing_langs and not list_failed:
        warnings.append(f"missing tesseract languages: {', '.join(missing_langs)}")

    min_ver = RUNTIME_COMPATIBILITY_SPEC["binaries"]["tesseract"]["min"]
    compatible = bool(
        version_str
        and _version_in_bounds(version_str, min_ver, None) is not False
        and not list_failed
        and not warnings
    )
    return {
        "available": True,
        "path": path,
        "version": version_str,
        "compatible": compatible,
        "languages": langs,
        "missing_required_languages": missing_langs,
        "tessdata_prefix": tessdata_prefix,
        "warnings": warnings,
    }


def _probe_pandoc() -> dict[str, Any]:
    path = shutil.which("pandoc")
    version_str: str | None = None
    warnings: list[str] = []
    if path:
        try:
            proc = subprocess.run(
                [path, "--version"], capture_output=True, text=True, encoding="utf-8", timeout=10
            )
            match = _VERSION_RE.search(proc.stdout or "")
            if match:
                version_str = match.group(1)
        except Exception as exc:
            warnings.append(f"pandoc --version failed: {type(exc).__name__}")
    if not path or version_str is None:
        try:
            import pypandoc

            path = path or str(pypandoc.get_pandoc_path())
            version_str = str(pypandoc.get_pandoc_version())
        except Exception:
            pass
    if not path:
        return {"available": False, "path": None, "version": None, "compatible": False, "warnings": warnings}
    min_ver = RUNTIME_COMPATIBILITY_SPEC["binaries"]["pandoc"]["min"]
    compatible = bool(version_str and _version_in_bounds(version_str, min_ver, None) is not False)
    return {
        "available": True,
        "path": path,
        "version": version_str,
        "compatible": compatible,
        "warnings": warnings,
    }


def _probe_pdftoppm() -> dict[str, Any]:
    path = shutil.which("pdftoppm")
    if not path:
        return {"available": False, "path": None, "version": None, "compatible": False, "warnings": []}
    version_str: str | None = None
    warnings: list[str] = []
    try:
        proc = subprocess.run(
            [path, "-v"], capture_output=True, text=True, encoding="utf-8", timeout=10
        )
        combined = f"{proc.stdout}\n{proc.stderr}"
        match = _VERSION_RE.search(combined)
        if match:
            version_str = match.group(1)
    except Exception as exc:
        warnings.append(f"pdftoppm -v failed: {type(exc).__name__}")
    min_ver = RUNTIME_COMPATIBILITY_SPEC["binaries"]["pdftoppm"]["min"]
    compatible = bool(version_str is None or _version_in_bounds(version_str, min_ver, None) is not False)
    return {
        "available": True,
        "path": path,
        "version": version_str,
        "compatible": compatible,
        "warnings": warnings,
    }


def probe_runtime(
    *,
    include_external_binaries: bool = True,
    required_ocr_langs: tuple[str, ...] = (),
    force_refresh: bool = False,
) -> dict[str, Any]:
    """Inspect Python package bounds and external OCR/document binary compatibility."""
    cache_key = (bool(include_external_binaries), tuple(required_ocr_langs))
    if not force_refresh:
        with _CACHE_LOCK:
            cached = _CACHED_REPORTS.get(cache_key)
            if cached is not None:
                return copy.deepcopy(cached)

    warnings: list[str] = []
    errors: list[str] = []
    py_ver = platform.python_version()
    py_spec = RUNTIME_COMPATIBILITY_SPEC["python"]
    py_ok = _version_in_bounds(py_ver, py_spec["min"], py_spec["max_exclusive"])
    if py_ok is False:
        errors.append(
            f"python {py_ver} outside supported range [{py_spec['min']}, {py_spec['max_exclusive']})"
        )

    packages: dict[str, Any] = {}
    for canonical_name, spec in RUNTIME_COMPATIBILITY_SPEC["packages"].items():
        dist_name, installed = _dist_version(tuple(spec["aliases"]))
        if installed is None:
            packages[canonical_name] = {
                "installed": False,
                "distribution": None,
                "version": None,
                "compatible": False,
                "min": spec["min"],
                "max_exclusive": spec["max_exclusive"],
                "required": spec["required"],
            }
            msg = f"missing package {canonical_name}"
            if spec["required"]:
                errors.append(msg)
            else:
                warnings.append(msg)
            continue

        in_bounds = _version_in_bounds(installed, spec["min"], spec["max_exclusive"])
        if in_bounds is False:
            msg = (
                f"{canonical_name}=={installed} outside tested range "
                f"[{spec['min']}, {spec['max_exclusive']})"
            )
            if spec["required"]:
                errors.append(msg)
            else:
                warnings.append(msg)
        packages[canonical_name] = {
            "installed": True,
            "distribution": dist_name,
            "version": installed,
            "compatible": in_bounds is not False,
            "min": spec["min"],
            "max_exclusive": spec["max_exclusive"],
            "required": spec["required"],
        }

    binaries: dict[str, Any] = {}
    if include_external_binaries:
        tess = _probe_tesseract(tuple(required_ocr_langs))
        pandoc = _probe_pandoc()
        pdftoppm = _probe_pdftoppm()
        binaries = {"tesseract": tess, "pandoc": pandoc, "pdftoppm": pdftoppm}
        for name, info in binaries.items():
            for w in info.get("warnings") or []:
                warnings.append(f"{name}: {w}")
            if not info.get("available"):
                warnings.append(f"optional external binary '{name}' not found on PATH")
            elif not info.get("compatible"):
                warnings.append(
                    f"external binary '{name}' ({info.get('version')}) has compatibility warning"
                )

    status = "incompatible" if errors else ("degraded" if warnings else "ok")
    report: dict[str, Any] = {
        "schema_version": RUNTIME_COMPATIBILITY_SPEC["schema_version"],
        "status": status,
        "python": {
            "version": py_ver,
            "executable": Path(sys.executable).name,
            "compatible": py_ok is not False,
        },
        "platform": platform.platform(),
        "packages": packages,
        "binaries": binaries,
        "warnings": warnings,
        "errors": errors,
    }
    with _CACHE_LOCK:
        _CACHED_REPORTS[cache_key] = copy.deepcopy(report)
    return report


def runtime_manifest(*, include_external_binaries: bool = True) -> dict[str, Any]:
    """Compact deterministic runtime version snapshot for Canonical and report provenance."""
    probe = probe_runtime(include_external_binaries=include_external_binaries)
    return {
        "schema_version": probe["schema_version"],
        "status": probe["status"],
        "python": probe["python"]["version"],
        "packages": {
            name: info["version"]
            for name, info in probe["packages"].items()
            if info.get("installed")
        },
        "binaries": {
            name: info["version"]
            for name, info in probe["binaries"].items()
            if info.get("available")
        },
        "warning_count": len(probe["warnings"]),
        "error_count": len(probe["errors"]),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe IDP Python and external runtime dependencies")
    parser.add_argument("--strict", action="store_true", help="Exit 1 if incompatible or degraded")
    parser.add_argument("--skip-binaries", action="store_true", help="Skip external CLI probes")
    parser.add_argument("--lang", action="append", default=[], help="Required Tesseract language")
    args = parser.parse_args(argv)
    report = probe_runtime(
        include_external_binaries=not args.skip_binaries,
        required_ocr_langs=tuple(args.lang),
        force_refresh=True,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["errors"]:
        return 1
    if args.strict and report["status"] != "ok":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
