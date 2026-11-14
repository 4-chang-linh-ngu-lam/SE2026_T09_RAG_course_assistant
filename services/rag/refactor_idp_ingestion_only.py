#!/usr/bin/env python3
"""Refactor the uploaded IDP version to canonical-only ingestion.

Run from services/rag/: python refactor_idp_ingestion_only.py
Supports modules already moved to idp/{orchestration,input,documents,ocr,structured,validation}.
Fail-closed on unknown code versions; never stage/commit files automatically.
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path

GROUPS = {
    'pipeline.py': 'orchestration', 'batch.py': 'orchestration',
    'cli.py': 'orchestration', 'worker.py': 'orchestration',
    'digital.py': 'documents', 'fast.py': 'ocr', 'quality.py': 'ocr',
    'quality_runtime.py': 'ocr', 'hybrid_runtime.py': 'ocr',
    'validate_output.py': 'validation', 'package.py': 'orchestration',
}


def replace_one(s: str, before: str, after: str, name: str) -> str:
    count = s.count(before)
    if count != 1:
        raise ValueError(f'{name}: expected 1 occurrence, found {count}: {before[:85]!r}')
    return s.replace(before, after, 1)


def replace_span(s: str, start: str, end: str, replacement: str, name: str) -> str:
    i = s.find(start)
    if i < 0 or s.find(start, i+1) >= 0:
        raise ValueError(f'{name}: start marker missing/ambiguous: {start[:85]!r}')
    j = s.find(end, i + len(start))
    if j < 0:
        raise ValueError(f'{name}: end marker missing: {end[:85]!r}')
    return s[:i] + replacement + s[j:]


def remove_import(s: str, module: str, name: str) -> str:
    # Handles original relative imports and absolute imports after package migration.
    variants = [
        rf'^from \.{module} import [^\n]*\n',
        rf'^from idp\.{module} import [^\n]*\n',
        rf'^from idp\.[a-z_]+\.{module} import [^\n]*\n',
    ]
    for pattern in variants:
        s, count = re.subn(pattern, '', s, count=1, flags=re.M)
        if count:
            return s
    raise ValueError(f'{name}: expected import for {module} not found')


def pdf_pipeline(s: str) -> str:
    name='pipeline.py'
    for module in ('chunk', 'review_report', 'export_audit'):
        s = remove_import(s,module,name)
    s=replace_one(s,'    ingestion_only: bool = False,','    ingestion_only: bool = True,',name)
    s=replace_one(s,'    pdf_path = Path(pdf_path)\n    out_dir = Path(out_dir)',
        '    if not ingestion_only:\n        raise ValueError("Chunking was removed from IDP; use the downstream indexing service")\n'
        '    pdf_path = Path(pdf_path)\n    out_dir = Path(out_dir)',name)
    s=replace_span(s,'    if ingestion_only:\n        chunks = []\n',
        '    review = collect_review(pages, ingestion_report["quality"]["page_quality"])', '',name)
    s=replace_span(s,'    text_chunks = [c for c in chunks if c.get("content_kind") == "text"]',
        '    formula_semantic_flags = sum(', '',name)
    s=replace_span(s,'        "chunks": len(chunks),',
        '        "formula_semantic_flags": formula_semantic_flags,','',name)
    s=replace_span(s,'    report["output_validation_errors"] = validate_outputs(out_dir, pages, chunks)',
        '    _atomic_write(out_dir / "manifest.json"',
        '    report["output_validation_errors"] = validate_outputs(out_dir, pages)\n\n',name)
    s=replace_span(s,'    if not ingestion_only:\n        _atomic_write(out_dir / "document.json"',
        '    _atomic_write(\n        out_dir / "review_queue.jsonl",', '',name)
    s=replace_one(s,'    write_review_html(out_dir, review)\n','',name)
    s=replace_one(s,'        "chunks": chunks,\n','',name)
    s=replace_one(s,'        "publishable_chunks": sum(1 for c in chunks if c["publishable"]),\n','',name)
    s=replace_one(s,'        "review_required_chunks": sum(1 for c in chunks if c["review_required"]),\n','',name)
    return s


def digital(s: str) -> str:
    name='digital.py'
    s=remove_import(s,'chunk',name)
    s=replace_one(s,'    ingestion_only: bool = False,','    ingestion_only: bool = True,',name)
    s=replace_span(s,'def _document(pages, chunks):\n', 'def _docx_source_audit(', '',name)
    s=replace_one(s,'    chunks: list[dict],\n','',name)
    s=replace_span(s,'    chunk_issues = []\n    for chunk in chunks:', '    checks = {', '',name)
    s=replace_span(s,'        "chunks_review_consistent": {', '        "no_content_loss": {','',name)
    s=replace_span(s,'    publishable_pages = (\n', '    pages_dir = out / "pages"', '',name)
    s=replace_span(s,'    if not ingestion_only:\n        (out / "chunks.jsonl").write_text(', '    if chunks:\n        review = [', '',name)
    s=replace_span(s,'    if chunks:\n        review = [', '    for item in ingestion["quality"]["page_quality"]:',
        '''    review = []
    for page in pages:
        for block in page["blocks"]:
            flags = [
                flag for flag in block.get("review_flags") or []
                if flag.get("severity") in {"warning", "error"}
            ]
            if flags:
                review.append({
                    "page": page["page_id"],
                    "block_id": block["block_id"],
                    "block_type": block["block_type"],
                    "bbox": block.get("bbox"),
                    "block_crop_path": block.get("block_crop_path"),
                    "flags": flags,
                })
''',name)
    s=replace_one(s,'        out, pages, chunks, require_bbox=source_type == "pdf_text"',
        '        out, pages, require_bbox=source_type == "pdf_text"',name)
    s=replace_one(s,'        pages, chunks, content_loss, source_type, output_errors',
        '        pages, content_loss, source_type, output_errors',name)
    s=replace_one(s,'        "chunks": len(chunks),\n','',name)
    s=replace_one(s,'        "review_chunks": len(review),','        "review_items": len(review),',name)
    # Reject intentionally requesting downstream features.
    s=replace_one(s,'    source = Path(input_path).resolve()\n',
        '    if not ingestion_only:\n        raise ValueError("Chunking was removed from IDP; use the downstream indexing service")\n    source = Path(input_path).resolve()\n',name)
    return s


def fast(s: str) -> str:
    name='fast.py'
    s=remove_import(s,'chunk',name)
    # canonical.py remains at idp package root in either layout.
    m=re.search(r'^from (?:\.|idp\.[a-z_]+\.)?normalize import\s+normalize_text$',s,re.M)
    if not m: raise ValueError('fast.py: normalize import missing')
    s=s[:m.start()]+ 'from idp.canonical import build_canonical, audit_canonical\n' + s[m.start():]
    s=replace_span(s,'    chunks = build_chunks(pages)', '    report = {', '''    canonical = build_canonical(
        pages=pages,
        source_path=pdf_path,
        source_sha256=source_sha256,
        pipeline_version=FAST_VERSION,
        parser={"name": "tesseract_fast", "version": FAST_VERSION,
                "kind": "ocr", "confidence_available": True,
                "sources": {"tesseract_fast": len(pages)}},
        expected_pages=page_ids,
        profile=profile,
    )
    ingestion_report = audit_canonical(canonical, trusted_parsers=set(), profile=profile)
    review = collect_review(pages, ingestion_report["quality"]["page_quality"])
    validation = validate_outputs(out, pages)
''',name)
    s=replace_span(s,'        "chunks": len(chunks),','        "pages_without_content": sum(', '',name)
    s=replace_span(s,'    (out / "document.json").write_text(',
        '    (out / "manifest.json").write_text(',
        '''    (out / "canonical.json").write_text(
        json.dumps(canonical, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "ingestion_report.json").write_text(
        json.dumps(ingestion_report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
''',name)
    s=replace_one(s,'        "chunks": report["chunks"],\n','',name)
    s=replace_one(s,'        "publishable_chunks": report["publishable_chunks"],\n','',name)
    s=replace_one(s,'    report = {\n        "mode": "fast_preview",\n',
        '    report = {\n        "mode": "fast_preview",\n        "ingestion_pass": ingestion_report["pass"],\n        "ingestion_quality": ingestion_report["quality"],\n',name)
    return s


def quality(s: str) -> str:
    name='quality.py'
    return replace_one(s, '"chunks": len(result["chunks"]),\n        ', '', name)


def validation(s: str) -> str:
    name='validate_output.py'
    s=replace_one(s,'import hashlib\n','',name)
    s=replace_one(s,'    chunks: list[dict],\n','',name)
    s=replace_span(s,'    chunk_by_id={c.get(\'id\'):c for c in chunks}', '    return errors', '',name)
    return s


def cli(s: str) -> str:
    name='cli.py'
    s=remove_import(s,'evaluate',name)
    s=replace_one(s,'    parser.add_argument("--ingestion-only", action="store_true",',
        '    parser.add_argument("--ingestion-only", action="store_true", default=True,',name)
    s=replace_span(s,'    if args.gold:\n        gate = evaluate(out, args.gold)',
        '    return 0\n\n\nif __name__ == "__main__":', '',name)
    s=replace_one(s,'    args = parser.parse_args()\n',
        '    args = parser.parse_args()\n    if args.gold:\n        parser.error("--gold evaluation was moved out of ingestion")\n',name)
    return s


def batch(s: str) -> str:
    name='batch.py'
    s=remove_import(s,'audit',name)
    s=replace_one(s,'    args = parser.parse_args()\n',
        '    args = parser.parse_args()\n    if args.gold:\n        parser.error("--gold evaluation was moved out of ingestion")\n',name)
    s=replace_one(s,'    if args.gold:\n        final_cmd.extend(["--gold", args.gold])\n','',name)
    s=replace_span(s,'    if args.audit and final.returncode == 0:\n        audit_result = audit(args.out, pages)',
        '    print(json.dumps(summary, ensure_ascii=False, indent=1))',
        '''    if args.audit and final.returncode == 0:
        audit_result = check_ingestion_artifacts(args.out, expected_pages=pages)
        summary["audit_pass"] = audit_result["pass"]
        summary["audit_errors"] = audit_result["errors"]
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
        )
''',name)
    s='from idp.validation.ingestion_checks import check_ingestion_artifacts\n'+s
    s=s.replace('python -m idp.digital','python -m idp.documents.digital')
    s=s.replace('"idp.cli"','"idp.orchestration.cli"')
    return s


def quality_runtime(s: str) -> str:
    name='quality_runtime.py'
    s,count=re.subn(r'^\s{8}from (?:\.|idp\.)audit import\s+audit\n','',s,count=1,flags=re.M)
    if count!=1: raise ValueError('quality_runtime.py: obsolete audit import missing')
    s=replace_span(s,'        audit_result = audit(out, expected_pages=list(range(1, info["pages"] + 1)))',
        '        return result',
        '''        audit_result = check_ingestion_artifacts(out, expected_pages=list(range(1, info["pages"] + 1)))
        _write(out / "batch_summary.json", json_bytes({
            "engine": QUALITY_RUNTIME_VERSION,
            "pipeline_version": result["report"]["pipeline_version"],
            "audit_pass": audit_result["pass"], "audit_errors": audit_result["errors"],
            "ingestion_pass": result["ingestion"]["pass"],
            "failed": result["failed_pages"], "pages": info["pages"],
            "source_sha256": source_hash,
        }))
''',name)
    s=replace_span(s,'    print(json.dumps({"pages": len(result["pages"]), "chunks": len(result["chunks"]),',
        '    summary = json.loads((args.out / "batch_summary.json").read_bytes())',
        '''    print(json.dumps({"pages": len(result["pages"]),
        "ingestion_pass": result["ingestion"]["pass"],
        "canonical_version": result["canonical"]["schema_version"]}))
''',name)
    s=replace_one(s,'from __future__ import annotations\n',
                  'from __future__ import annotations\n\nfrom idp.validation.ingestion_checks import check_ingestion_artifacts\n',name)
    return s


def hybrid_runtime(s: str) -> str:
    name='hybrid_runtime.py'
    s,count=re.subn(r'^\s{4}from (?:\.|idp\.)audit import\s+audit\n','',s,count=1,flags=re.M)
    if count!=1: raise ValueError('hybrid_runtime.py: obsolete audit import missing')
    s=replace_span(s,'            audit_result = audit(out, expected_pages=expected)',
        '            return result',
        '''            audit_result = check_ingestion_artifacts(out, expected_pages=expected)
            _write(out / "batch_summary.json", json_bytes({
                "engine": HYBRID_VERSION, "pipeline_version": PIPELINE_VERSION,
                "audit_pass": audit_result["pass"], "audit_errors": audit_result["errors"],
                "ingestion_pass": result["ingestion"]["pass"],
                "failed": result["failed_pages"], "pages": info["pages"],
                "source_sha256": source_hash,
                "resume": "fresh_attempt_no_cached_recognition_reuse",
            }))
''',name)
    s=replace_one(s,'    print(json.dumps({"pages": len(result["pages"]), "chunks": len(result["chunks"]),\n        "audit_pass": summary["audit_pass"], "publishable_chunks": summary["publishable_chunks"]}))',
        '    print(json.dumps({"pages": len(result["pages"]),\n        "audit_pass": summary["audit_pass"], "ingestion_pass": summary["ingestion_pass"]}))',name)
    s=replace_one(s,'from __future__ import annotations\n',
                  'from __future__ import annotations\n\nfrom idp.validation.ingestion_checks import check_ingestion_artifacts\n',name)
    return s


def worker(s: str) -> str:
    name='worker.py'
    s=s.replace('"idp.hybrid_runtime"','"idp.ocr.hybrid_runtime"')
    s=s.replace('"idp.quality_runtime"','"idp.ocr.quality_runtime"')
    s=s.replace('"idp.fast"','"idp.ocr.fast"')
    s=s.replace('"idp.batch"','"idp.orchestration.batch"')
    s=replace_one(s,'        if job.gold_path:\n            command.extend(["--gold", str(job.gold_path)])\n', '',name)
    s=replace_one(s,'        gold_path = _optional_input(data.get("gold_path"), input_roots, "gold_path")',
        '        if data.get("gold_path") is not None:\n            raise ValueError("gold_path evaluation moved out of ingestion")\n        gold_path = None',name)
    s=replace_one(s,'            "publishable_chunks": report.get("publishable_chunks"),',
        '            "ingestion_auto_publish_pass": report.get("ingestion_auto_publish_pass"),',name)
    return s


def package(s: str) -> str:
    name='package.py'
    s=replace_one(s,'    root = Path(__file__).resolve().parent',
        '    root = Path(__file__).resolve().parents[1]  # idp/, not idp/orchestration/',name)
    s=replace_span(s,'            for source in sorted(root.iterdir()):',
        '        temporary.replace(destination)',
        '''            excluded = {
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
''',name)
    return s

TRANSFORMS = {
    'pipeline.py': pdf_pipeline, 'digital.py': digital, 'fast.py': fast, 'quality.py': quality,
    'validate_output.py': validation, 'cli.py': cli, 'batch.py': batch,
    'quality_runtime.py': quality_runtime, 'hybrid_runtime.py': hybrid_runtime,
    'worker.py': worker, 'package.py': package,
}


def locate(root: Path, name: str) -> Path:
    folder=GROUPS[name]
    nested=root/folder/name
    flat=root/name
    if nested.is_file(): return nested
    if flat.is_file(): return flat
    raise FileNotFoundError(f'{name} not found under {root}')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--idp',type=Path,default=Path('idp'),help='IDP source directory; defaults to ./idp when run from services/rag')
    args=parser.parse_args()
    root=args.idp.resolve()
    if not root.is_dir():
        parser.error(f'not an IDP directory: {root}')

    changes={}
    for name,transform in TRANSFORMS.items():
        path=locate(root,name)
        old=path.read_text(encoding='utf-8-sig')
        new=transform(old)
        ast.parse(new,filename=str(path))
        changes[path]=new

    checks=root/'validation'/'ingestion_checks.py'
    if not checks.parent.is_dir():
        raise ValueError('validation/ package not found; run the folder migration first')
    if checks.exists():
        raise FileExistsError(f'Existing file must be reviewed before overwriting: {checks}')

    checks_src = '''"""Verify canonical-only ingestion artifacts without downstream chunk/audit modules."""
from __future__ import annotations
import json
from pathlib import Path


def check_ingestion_artifacts(out_dir: str | Path, expected_pages: list[int] | None = None) -> dict:
    out = Path(out_dir)
    errors = []
    try:
        canonical = json.loads((out / "canonical.json").read_text(encoding="utf-8"))
        ingestion = json.loads((out / "ingestion_report.json").read_text(encoding="utf-8"))
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"pass": False, "errors": [f"missing/invalid ingestion artifacts: {exc}"]}
    if not isinstance(canonical, dict) or not isinstance(ingestion, dict) or not isinstance(report, dict):
        return {"pass": False, "errors": ["ingestion artifacts must be JSON objects"]}
    if not canonical.get("schema_version") or not canonical.get("source_sha256"):
        errors.append("canonical schema or source hash missing")
    pages = canonical.get("pages")
    if not isinstance(pages, list):
        errors.append("canonical pages must be a list")
        pages = []
    seen = set()
    for page in pages:
        if not isinstance(page, dict) or type(page.get("page_id")) is not int:
            errors.append("invalid canonical page entry")
            continue
        pid = page["page_id"]
        if pid in seen:
            errors.append(f"duplicate canonical page {pid}")
        seen.add(pid)
        page_file = out / "pages" / f"p{pid:04d}.json"
        if not page_file.is_file():
            errors.append(f"missing parsed page JSON: {pid}")
    if expected_pages is not None and set(expected_pages) != seen:
        errors.append(f"page coverage mismatch: expected {sorted(set(expected_pages))}, got {sorted(seen)}")
    for message in report.get("output_validation_errors") or []:
        errors.append(f"output validation: {message}")
    if canonical.get("failed_pages") or report.get("failed_pages"):
        errors.append("one or more pages failed ingestion")
    if not isinstance(ingestion.get("checks"), dict) or not isinstance(ingestion.get("pass"), bool):
        errors.append("missing canonical ingestion quality checks")
    return {"pass": not errors, "errors": errors, "checked_pages": len(seen),
            "ingestion_pass": ingestion.get("pass")}
'''
    ast.parse(checks_src,filename=str(checks))
    # Only write if every source transformation parses successfully.
    for path,new in changes.items():
        path.write_text(new, encoding='utf-8')
        print('Refactored:',path.relative_to(root))
    checks.write_text(checks_src,encoding='utf-8')
    print('Added:',checks.relative_to(root))
    print('Done: run compileall and import/smoke tests; do not commit if tests fail.')

if __name__ == '__main__':
    main()
