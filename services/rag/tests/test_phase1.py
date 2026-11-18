"""Native integration: compare complete records, not just extracted text counts."""

import ast
import hashlib
import importlib
import inspect
import json
import os
import pkgutil
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from enum import Enum
from pathlib import Path

import pytest
from idp.pdf.native.engine import PdfParsingEngine
if (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file():
    from parser.pdf.engine import PdfParsingEngine as OriginalEngine

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/generated"


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    return value


@pytest.mark.contract
def test_native_import_graph():
    from idp.pdf import native

    for module in pkgutil.walk_packages(native.__path__, native.__name__ + "."):
        importlib.import_module(module.name)
    for path in (ROOT / "idp/pdf/native").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                names = [node.module or ""]
            assert not any(
                n.split(".")[0] in {"rag", "api", "parser", "deepdoc", "common"}
                for n in names
            )


@pytest.mark.contract
@pytest.mark.parametrize(
    "cwd", [ROOT, next((p for p in ROOT.parents if (p / ".git").is_dir()), ROOT.parent)]
)
def test_import_in_service_and_repository(cwd):
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from idp.pdf.native.engine import PdfParsingEngine; assert not any(n == 'parser' or n.startswith(('parser.', 'rag.', 'api.', 'deepdoc.')) for n in sys.modules)",
        ],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.contract
def test_parser_source_and_idp_production_unchanged():
    frozen = json.loads((ROOT / "tests/golden/source.json").read_text())
    for path, digest in frozen.items():
        if path.startswith("parser/"):
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    # Old IDP files include the B1/P2 fixes, captured immediately before Phase 1.
    inventory = ROOT / "tests/phase1-idp-source.json"
    for path, digest in json.loads(inventory.read_text()).items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.contract
def test_legacy_signature():
    assert str(inspect.signature(PdfParsingEngine.extract_source)) == str(
        inspect.signature(OriginalEngine.extract_source)
    )


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.golden
@pytest.mark.parametrize(
    "name",
    [
        "native.pdf",
        "multipage.pdf",
        "columns.pdf",
        "table.pdf",
        "formula.pdf",
        "figure.pdf",
        "scan.pdf",
        "mixed.pdf",
        "vietnamese.pdf",
        "encoding.pdf",
        "rotated_cropbox.pdf",
    ],
)
def test_original_parser_equivalence(name):
    data = (FIXTURES / name).read_bytes()
    expected = OriginalEngine().extract_source(data)
    actual = PdfParsingEngine().extract_source(data)
    # Includes observation IDs/text/locations/traces, manifest, structures,
    # diagnostics, page facts, layout, reconciliation and quality gate.
    assert plain(actual) == plain(expected)


@pytest.mark.contract
def test_evidence_stays_immutable_and_validated():
    result = PdfParsingEngine().extract_source((FIXTURES / "native.pdf").read_bytes())
    item = result.observations[0]
    with pytest.raises((TypeError, AttributeError)):
        item.attributes["fake"] = True
    with pytest.raises(ValueError):
        replace(item, text="This is not the source candidate")
    with pytest.raises(ValueError):
        replace(result, observations=(*result.observations, item))


@pytest.fixture(scope="module")
def extra_documents():
    from fixtures.phase1 import documents

    return documents()


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.integration
@pytest.mark.parametrize(
    "name",
    [
        "native.pdf",
        "multipage.pdf",
        "columns.pdf",
        "table.pdf",
        "formula.pdf",
        "figure.pdf",
        "scan.pdf",
        "mixed.pdf",
        "rotated_cropbox.pdf",
    ],
)
def test_split_equals_original(name):
    from idp.pdf.native.preflight import PdfSource

    data = (FIXTURES / name).read_bytes()
    engine = PdfParsingEngine()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        assert len(native.geometry) == len(native.pages) == native.page_count
        if name == "rotated_cropbox.pdf":
            assert (
                native.geometry[0].width,
                native.geometry[0].height,
                native.geometry[0].rotation,
            ) == (560, 360, 90)
            assert native.geometry[0].crop_box == (20, 20, 380, 580)
        assert plain(engine.finalize(native, source=source)) == plain(
            OriginalEngine().extract_source(data)
        )


@pytest.mark.unit
def test_empty_scan_without_figures(monkeypatch):
    import idp.pdf.native.engine as engine_module
    from idp.evidence.contracts import DeepDocPageReason

    monkeypatch.setattr(engine_module, "extract_pdf_figures", lambda *a, **k: ((), ()))
    data = (FIXTURES / "scan.pdf").read_bytes()
    engine = PdfParsingEngine()
    native = engine.extract_native(data)
    assert native.empty and native.observations == native.figures == ()
    assert native.page_count == 1
    assert native.pages[0].image_resource_count > 0
    assert DeepDocPageReason.NO_NATIVE_TEXT in native.pages[0].layout_reasons
    assert native.admission.source_sha256 == hashlib.sha256(data).hexdigest()
    with pytest.raises(ValueError, match="acquisition/merge"):
        engine.finalize(native)
    with pytest.raises(ValueError, match="no extractable native text or figures"):
        engine.extract_source(data)


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.unit
def test_blank_is_valid_intermediate(extra_documents):
    from idp.evidence.contracts import DeepDocPageReason

    engine = PdfParsingEngine()
    native = engine.extract_native(extra_documents["blank"])
    assert native.empty and native.page_count == 1
    assert native.pages[0].native_text_assessed
    assert native.pages[0].image_resource_count == 0
    assert DeepDocPageReason.NO_NATIVE_TEXT in native.pages[0].layout_reasons
    for engine_type in (PdfParsingEngine, OriginalEngine):
        with pytest.raises(ValueError, match="no extractable native text or figures"):
            engine_type().extract_source(extra_documents["blank"])


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.integration
def test_figure_only_and_mixed(extra_documents):
    engine = PdfParsingEngine()
    figure_only = engine.extract_native((FIXTURES / "scan.pdf").read_bytes())
    assert (
        not figure_only.observations and figure_only.figures and not figure_only.empty
    )
    mixed = engine.extract_native(extra_documents["mixed4"])
    assert mixed.page_count == 4
    assert [bool(p.native_text_char_count) for p in mixed.pages] == [
        True,
        False,
        True,
        False,
    ]
    assert [bool(p.image_resource_count) for p in mixed.pages] == [
        False,
        True,
        True,
        False,
    ]
    assert len({o.source_id for o in (*mixed.observations, *mixed.figures)}) == len(
        mixed.observations
    ) + len(mixed.figures)
    assert plain(engine.finalize(mixed)) == plain(
        OriginalEngine().extract_source(extra_documents["mixed4"])
    )


@pytest.mark.unit
def test_native_result_validation(extra_documents):
    native = PdfParsingEngine().extract_native(extra_documents["blank"])
    with pytest.raises(ValueError, match="every admitted page"):
        replace(native, pages=())
    with pytest.raises(ValueError, match="exact admitted source bytes"):
        replace(native, data=b"changed")
    with pytest.raises((TypeError, AttributeError)):
        native.admission.source_sha256 = "fake"
    with pytest.raises((TypeError, AttributeError)):
        native.page_count = 10


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.unit
@pytest.mark.parametrize(
    "case,code",
    [
        ("corrupt", "PDF_INVALID"),
        ("bytes", "PDF_SOURCE_TOO_LARGE"),
        ("pages", "PDF_PAGE_LIMIT"),
        ("deadline", "PDF_DEADLINE_EXCEEDED"),
    ],
)
def test_admission_errors(case, code, monkeypatch):
    from idp.pdf.native.preflight import PdfAdmissionError, PdfAdmissionPolicy

    if case == "deadline":
        import itertools
        import time

        clock = itertools.count()
        monkeypatch.setattr(time, "monotonic", lambda: next(clock))
    data = (
        FIXTURES / ("broken.pdf" if case == "corrupt" else "multipage.pdf")
    ).read_bytes()
    policy = PdfAdmissionPolicy(
        **{
            "corrupt": {},
            "bytes": {"max_source_bytes": 10},
            "pages": {"max_pages": 1},
            "deadline": {"timeout_seconds": 1e-12},
        }[case]
    )
    with pytest.raises(PdfAdmissionError) as caught:
        PdfParsingEngine().extract_native(data, policy=policy)
    assert caught.value.diagnostic.code == code
    from parser.pdf.preflight import PdfAdmissionError as OriginalError
    from parser.pdf.preflight import PdfAdmissionPolicy as OriginalPolicy

    with pytest.raises(OriginalError) as original:
        OriginalEngine().extract_source(data, policy=OriginalPolicy(**plain(policy)))
    assert original.value.diagnostic.code == code


@pytest.mark.unit
def test_single_pass_and_borrowed_source(monkeypatch):
    import idp.pdf.native.engine as module
    from idp.pdf.native.preflight import PdfSource

    counts = {}
    for name in (
        "extract_native_text",
        "collect_page_facts",
        "attach_native_structures",
        "apply_pdf_layout",
        "reconcile_pages",
    ):
        original = getattr(module, name)

        def wrapped(*args, _name=name, _original=original, **kwargs):
            counts[_name] = counts.get(_name, 0) + 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapped)
    engine = PdfParsingEngine()
    data = (FIXTURES / "native.pdf").read_bytes()
    with PdfSource(data) as source:
        native = engine.extract_native(data, source=source)
        assert counts == {"extract_native_text": 1, "collect_page_facts": 1}
        before = plain(native)
        result = engine.finalize(native, source=source)
        assert all(value == 1 for value in counts.values()) and len(counts) == 5
        assert source.reader is not None
        assert plain(native) == before
        assert plain(engine.finalize(native, source=source)) == plain(result)
    assert source.reader is None and source._pdfium is None


@pytest.mark.unit
def test_wrong_or_closed_session_rejected():
    from idp.pdf.native.preflight import PdfSource

    engine = PdfParsingEngine()
    native = engine.extract_native((FIXTURES / "native.pdf").read_bytes())
    with (
        PdfSource((FIXTURES / "scan.pdf").read_bytes()) as source,
        pytest.raises(ValueError, match="does not match"),
    ):
        engine.finalize(native, source=source)
    with pytest.raises(ValueError, match="does not match"):
        engine.extract_native(source.data, source=source)


@pytest.mark.integration
@pytest.mark.parametrize(
    "failure", ["none", "extract", "finalize", "deadline", "cancel", "admission_cancel"]
)
def test_source_cleanup(monkeypatch, failure):
    import idp.pdf.native.engine as module
    from idp.pdf.native import preflight

    opened, closed_sources, pdfium_handles = [], [], []
    original_reader = preflight.PdfReader
    original_close = preflight.PdfSource.close

    def close(source):
        if source._pdfium is not None:
            pdfium_handles.append(source._pdfium)
        original_close(source)
        closed_sources.append(source)

    def reader(*a, **kw):
        result = original_reader(*a, **kw)
        opened.append(result)
        return result

    monkeypatch.setattr(preflight, "PdfReader", reader)
    monkeypatch.setattr(preflight.PdfSource, "close", close)
    if failure == "admission_cancel":
        monkeypatch.setattr(
            preflight.PdfSource,
            "_resources",
            lambda *a: (_ for _ in ()).throw(KeyboardInterrupt()),
        )
    elif failure != "none":

        def fail(source, *a, **kw):
            # Allocate the real lazy PDFium owner before triggering cleanup.
            source = kw.get("source", source)
            assert source.pdfium is not None
            if failure == "cancel":
                raise KeyboardInterrupt()
            if failure == "deadline":
                source._deadline = 0
                source.check_deadline()
            raise RuntimeError("controlled stage failure")

        if failure == "finalize":
            monkeypatch.setattr(
                module,
                "attach_native_structures",
                lambda parsed, source, *a, **k: fail(source),
            )
        else:
            monkeypatch.setattr(module, "extract_native_text", fail)
    data = (FIXTURES / "native.pdf").read_bytes()
    if failure == "none":
        for _ in range(3):
            PdfParsingEngine().extract_source(data)
        assert len(opened) == 3
    else:
        with pytest.raises((RuntimeError, ValueError, KeyboardInterrupt)):
            PdfParsingEngine().extract_source(data)
        assert len(opened) == 1
    assert all(item.stream.closed for item in opened)
    assert len(closed_sources) == len(opened)
    assert all(
        s.reader is None and s._pdfium is None and s._stream is None
        for s in closed_sources
    )
    assert all(not handle.raw for handle in pdfium_handles)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["timeout", "overflow", "cancel"])
def test_poppler_process_boundary_cleanup(monkeypatch, mode):
    import idp.pdf.native.preflight as module

    processes, temporary = [], []
    original_popen, original_temp = module.subprocess.Popen, module.TemporaryFile

    def popen(*a, **kw):
        process = original_popen(*a, **kw)
        processes.append(process)
        if mode == "cancel":
            original_wait = process.wait
            first = True

            def wait(*a, **kw):
                nonlocal first
                if first:
                    first = False
                    raise KeyboardInterrupt()
                return original_wait(*a, **kw)

            process.wait = wait
        return process

    def temporary_file(*a, **kw):
        handle = original_temp(*a, **kw)
        temporary.append(handle)
        return handle

    monkeypatch.setattr(module.subprocess, "Popen", popen)
    monkeypatch.setattr(module, "TemporaryFile", temporary_file)
    code = (
        "print('x'*8192, flush=True)"
        if mode == "overflow"
        else "import time; time.sleep(10)"
    )
    with pytest.raises(
        (subprocess.TimeoutExpired, module.PdfAdmissionError, KeyboardInterrupt)
    ):
        module.run_bounded_process(
            [sys.executable, "-c", code], timeout=0.15, output_limit=100
        )
    assert len(processes) == len(temporary) == 1
    assert processes[0].poll() is not None
    assert processes[0].stdout.closed and processes[0].stderr.closed
    assert temporary[0].closed


@pytest.mark.skipif(not (Path(__file__).resolve().parents[1] / "parser" / "pdf" / "engine.py").is_file(), reason="External reference parser unavailable")
@pytest.mark.integration
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_and_rotation_geometry(rotation):
    import fitz

    with fitz.open() as pdf:
        page = pdf.new_page(width=400, height=600)
        page.insert_text((100, 140), "Admitted native geometry", fontsize=12)
        page.set_cropbox(fitz.Rect(20, 30, 380, 570))
        page.set_rotation(rotation)
        data = pdf.tobytes(no_new_id=True)
    engine = PdfParsingEngine()
    native = engine.extract_native(data)
    expected = (540, 360) if rotation in (90, 270) else (360, 540)
    assert (native.geometry[0].width, native.geometry[0].height) == expected
    assert native.geometry[0].crop_box == (20, 30, 380, 570)
    assert native.pages[0].rotation == rotation
    assert native.observations
    assert plain(engine.finalize(native)) == plain(
        OriginalEngine().extract_source(data)
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    "name,previews",
    [
        ("native.pdf", ["NATIVE_CANDIDATE"]),
        ("scan.pdf", ["OCR_REQUIRED"]),
        ("mixed.pdf", ["NATIVE_CANDIDATE", "OCR_REQUIRED"]),
        ("blank", ["NO_NATIVE_CONTENT_REVIEW"]),
        (
            "mixed4",
            [
                "NATIVE_CANDIDATE",
                "OCR_REQUIRED",
                "NATIVE_CANDIDATE",
                "NO_NATIVE_CONTENT_REVIEW",
            ],
        ),
    ],
)
def test_integration_spike(name, previews, extra_documents, monkeypatch):
    from idp.pdf.native import preflight
    from tools.native_spike import run_native_spike

    data = (
        extra_documents[name]
        if name in extra_documents
        else (FIXTURES / name).read_bytes()
    )
    original_init, original_close = (
        preflight.PdfSource.__init__,
        preflight.PdfSource.close,
    )
    opened, closed = [], []

    def init(source, *a, **kw):
        original_init(source, *a, **kw)
        opened.append(source)

    def close(source):
        original_close(source)
        closed.append(source)

    monkeypatch.setattr(preflight.PdfSource, "__init__", init)
    monkeypatch.setattr(preflight.PdfSource, "close", close)
    result = run_native_spike(data)
    assert [p["preview"] for p in result["pages"]] == previews
    assert result["page_count"] == len(previews)
    assert result["ocr_used"] is False
    assert result["finalized"] is (name != "blank")
    assert len(opened) == len(closed) == 1 and opened == closed
    assert closed[0].reader is None and closed[0]._pdfium is None
    assert len(result["observation_ids"]) == len(set(result["observation_ids"]))


@pytest.mark.integration
def test_spike_empty_scan_and_failed_optional_figure(monkeypatch):
    import idp.pdf.native.engine as module
    from tools.native_spike import run_native_spike

    def unavailable(*a, **kw):
        raise RuntimeError("controlled optional figure failure")

    monkeypatch.setattr(module, "extract_pdf_figures", unavailable)
    summary = run_native_spike((FIXTURES / "scan.pdf").read_bytes())
    assert summary["empty"] and not summary["finalized"]
    assert summary["pages"][0]["preview"] == "OCR_REQUIRED"
    assert "PDF_FIGURE_EXTRACTION_UNAVAILABLE" in summary["diagnostics"]
    assert summary["figure_status"] == "unavailable"


@pytest.mark.integration
def test_spike_cli_and_no_ocr_imports():
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    code = """
import sys
from pathlib import Path
from tools.native_spike import run_native_spike
summary = run_native_spike(Path(sys.argv[1]).read_bytes())
assert not summary['ocr_used']
assert not any(n.startswith(('idp.ocr', 'paddle', 'torch', 'rag.', 'deepdoc.', 'parser.')) for n in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(FIXTURES / "scan.pdf")],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "tools.native_spike", str(FIXTURES / "native.pdf")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["pages"][0]["preview"] == "NATIVE_CANDIDATE"
    failed = subprocess.run(
        [sys.executable, "-m", "tools.native_spike", str(FIXTURES / "broken.pdf")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert failed.returncode == 2
    assert json.loads(failed.stderr.splitlines()[-1])["error"] == "PDF_INVALID"
