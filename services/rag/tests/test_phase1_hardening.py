"""Phase 1 contract boundaries; no OCR merger is exercised."""
from dataclasses import replace, fields, is_dataclass
from collections.abc import Mapping
from pathlib import Path
import pytest
from idp.pdf.native.engine import PdfParsingEngine
from idp.pdf.native.result import EmptyNativeError, NativeContentStatus
from parser.pdf.engine import PdfParsingEngine as OriginalEngine

DATA = Path(__file__).parent / "fixtures/generated/native.pdf"


def walk(value):
    yield value
    if is_dataclass(value):
        for field in fields(value):
            yield from walk(getattr(value, field.name))
    elif isinstance(value, Mapping):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from walk(item)


def test_nested_identity_and_foreign_rejection():
    engine = PdfParsingEngine()
    native = engine.extract_native(DATA.read_bytes())
    original = OriginalEngine().extract_source(DATA.read_bytes())
    assert type(original.observations[0]).__module__ == "parser.source_observation"
    assert not any(type(v).__module__.startswith("parser.") for v in walk(native))
    assert native.content_status == NativeContentStatus.CONTENT_PRESENT
    for changes in ({"observations": original.observations}, {"diagnostics": original.diagnostics, "admission": original.manifest.admission}, {"pages": original.manifest.pages}):
        with pytest.raises(TypeError, match="foreign Parser"):
            replace(native, **changes)
    with pytest.raises(TypeError, match="foreign Parser"):
        engine.evaluate(original)
    with pytest.raises(TypeError):
        engine.finalize(original)


def test_empty_outcome_preserves_intermediate():
    from fixtures.phase1 import documents
    engine = PdfParsingEngine()
    native = engine.extract_native(documents()["blank"])
    before = (native.admission, native.geometry, native.pages, native.diagnostics)
    assert native.content_status == NativeContentStatus.NO_NATIVE_CONTENT
    with pytest.raises(EmptyNativeError, match="acquisition/merge"):
        engine.finalize(native)
    assert before == (native.admission, native.geometry, native.pages, native.diagnostics)
    assert native.empty and not native.observations and not native.figures
    with pytest.raises(ValueError, match="no extractable native") as caught:
        engine.extract_source(native.data)
    assert type(caught.value) is ValueError


def test_no_external_private_completion_dependency():
    import ast
    root = DATA.parents[3] / "idp"
    for path in root.rglob("*.py"):
        if path.name in {"engine.py", "result.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(n, ast.Attribute) and n.attr in {"_completion", "_text"} for n in ast.walk(tree))


def test_unsupported_merge_input_is_explicit():
    engine = PdfParsingEngine()
    native = engine.extract_native(DATA.read_bytes())
    with pytest.raises(TypeError, match="prepared_input"):
        engine.finalize(native, prepared_input=())
