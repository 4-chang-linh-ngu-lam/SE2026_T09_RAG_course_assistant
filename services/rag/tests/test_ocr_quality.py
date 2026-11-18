"""OCR quality fixes: column splitting/reading order and formula recognition.

Book measurements (hand-transcribed ground truth, real Tesseract/Paddle) are in
docs/deepdoc/ocr-quality/; these tests pin the behaviour on synthetic inputs
and on outputs recorded from the real models.
"""

import hashlib
import json
import shutil
import time
from collections import Counter
from io import BytesIO
from pathlib import Path

import fitz
import pytest
from PIL import Image, ImageDraw, ImageFont

from idp.evidence.contracts import DeepDocProducer
from idp.ocr.backends.latex_check import check_latex
from idp.pdf import service as service_module
from idp.pdf.acquire import AcquisitionResult, OcrBlock, group_paragraphs
from idp.pdf.columns import split_columns
from idp.pdf.service import DeepDocConfig, DeepDocService
from idp.publish import iter_retrievable_blocks, load_canonical

ROOT = Path(__file__).parents[1]
W, H = 1000, 1400
WORD_H = 30


def blank_scan(path, size=(W, H)):
    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    with fitz.open() as pdf:
        page = pdf.new_page(width=size[0] * 72 / 200, height=size[1] * 72 / 200)
        page.insert_image(page.rect, stream=buffer.getvalue())
        pdf.save(path)


def line(key, y, *segments, conf=0.95):
    """``segments``: (x0, "words ...") placed left to right; ``|`` is a rule glyph."""
    words = []
    for x, text in segments:
        for token in text.split():
            width = 5 if token in {"|", "¡", "j"} else 16 * len(token)
            words.append(
                {"text": token, "bbox_px": (x, y, x + width, y + WORD_H), "confidence": conf}
            )
            x += width + 12
    box = (
        min(w["bbox_px"][0] for w in words),
        y,
        max(w["bbox_px"][2] for w in words),
        y + WORD_H,
    )
    return OcrBlock(key, " ".join(w["text"] for w in words), box, conf, payload={"words": tuple(words)})


def frame_for():
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page

    path = Path(__file__).parent / "fixtures/generated/scan.pdf"
    with PdfSource(path.read_bytes()) as source:
        _, frame = render_page(source, 1)
    return frame


def result(blocks, frame=None):
    frame = frame or frame_for()
    return AcquisitionResult(
        frame, DeepDocProducer("t", "1"), "t", "0" * 64, "r", "1" * 64, tuple(blocks)
    )


# A framed box like SGK "THUẬT NGỮ | KIẾN THỨC, KĨ NĂNG": Tesseract read each
# row across both columns; the dashed rule became thin glyphs.
BOX = [
    ("1:5:1:1", 40, (40, "TERMS"), (400, "|"), (430, "KNOWLEDGE AND SKILLS")),
    ("1:5:1:2", 80, (40, "first term alpha"), (400, "|"), (430, "recognise linear inequality")),
    ("1:6:1:1", 120, (40, "second term beta"), (400, "|"), (430, "draw the solution region")),
    ("1:6:1:2", 160, (40, "third term"), (400, "|"), (430, "on the coordinate plane")),
    ("1:7:1:1", 200, (430, "apply to real problems")),
]


def box_blocks(offset=0):
    return [line(k, y + offset, *segs) for k, y, *segs in BOX]


def test_split_columns_regroups_same_words_per_column():
    original = result(box_blocks())
    split = split_columns(original, page_width_px=1000)
    assert split is not original

    def words(r):
        return Counter(
            (w["text"], tuple(w["bbox_px"]), w["confidence"])
            for b in r.blocks
            for w in b.payload["words"]
        )

    # No word lost, duplicated, moved or re-scored.
    assert words(split) == words(original)
    texts = {b.key: b.text for b in split.blocks}
    left = [t for k, t in texts.items() if "c0" in k]
    right = [t for k, t in texts.items() if "c1" in k]
    assert left and right
    assert not any("KNOWLEDGE" in t or "recognise" in t for t in left)
    assert not any("alpha" in t or "beta" in t for t in right)
    hints = {b.payload["column_run"]["run"] for b in split.blocks}
    assert hints == {"r0"}
    for block in split.blocks:
        run = block.payload["column_run"]
        assert run["version"] == "word-gutter:1" and run["source_line"] in {k for k, *_ in BOX}
        # Recognition confidence stays Tesseract's, never a layout score.
        ws = block.payload["words"]
        assert block.confidence == pytest.approx(
            sum(w["confidence"] * len(w["text"]) for w in ws) / sum(len(w["text"]) for w in ws)
        )
    grouped = group_paragraphs(split)
    for block in grouped.blocks:
        assert block.payload["column_run"]["path"] in ([0], [1], (0,), (1,))
        assert "source_line" not in block.payload["column_run"]


@pytest.mark.parametrize(
    "rows",
    [
        # 2x2 answer grid: read row by row (A, B, C, D), two rows only.
        [
            ("1:1:1:1", 40, (40, "A. connect with friends"), (500, "B. entertainment")),
            ("1:1:1:2", 80, (40, "C. collect information"), (500, "D. explore the world")),
        ],
        # Data table split down the middle: cells on both sides.
        [
            (f"1:2:1:{i}", 40 + 40 * i, (40, f"{i}1      {i}2"), (500, f"{i}3      {i}4"))
            for i in range(1, 5)
        ],
        # Two-column table, every row paired and no rule: keep rows.
        [
            (f"1:3:1:{i}", 40 + 40 * i, (40, f"statement number {i}"), (500, f"negation number {i}"))
            for i in range(1, 5)
        ],
        # Prose spanning the page: nothing to split.
        [
            (f"1:4:1:{i}", 40 + 40 * i, (40, "plain prose line that spans the whole width of the page"))
            for i in range(1, 5)
        ],
    ],
)
def test_row_major_structures_are_not_split(rows):
    original = result([line(k, y, *segs) for k, y, *segs in rows])
    assert split_columns(original, page_width_px=1000) is original


def test_split_skips_non_tesseract_results():
    marker = result([OcrBlock("marker-7", "x", (1, 1, 5, 5), 0.9)])
    assert split_columns(marker) is marker


class ColumnOcr:
    """Recorded Tesseract-shaped lines: the box rows run across the gutter."""

    config_sha256 = "c" * 64
    parallel_safe = False

    def __init__(self, out=None, config=None):
        self.producer = DeepDocProducer("tesseract", "unit-recorded")

    def read(self, image, source, page, plan, *, deadline, target_region_id=None):
        blocks = [line("1:1:1:1", 0, (40, "Chapter heading spans the page width here"))]
        blocks += box_blocks(offset=40)
        blocks.append(line("1:9:1:1", 320, (40, "After the box a paragraph spans the full page width")))
        return AcquisitionResult(
            plan.frame,
            self.producer,
            "tesseract",
            self.config_sha256,
            "unit:raw",
            hashlib.sha256(image).hexdigest(),
            tuple(blocks),
        )


def test_two_column_box_is_published_column_by_column(tmp_path, monkeypatch):
    """Whole pipeline (split, paragraphs, merge, layout, publication)."""
    monkeypatch.setattr(service_module, "TesseractBackend", ColumnOcr)
    path = tmp_path / "box.pdf"
    blank_scan(path)
    out = tmp_path / "out"
    DeepDocService(
        DeepDocConfig(engine="unified", canonical_version=2, language="eng", ocr_workers=1)
    ).process_pdf(path, out)
    doc = load_canonical(out / "canonical.json")
    text = "\n".join(b["text"] for b in iter_retrievable_blocks(doc))
    order = [
        "Chapter heading",
        "TERMS",
        "alpha",
        "beta",
        "third term",
        "KNOWLEDGE",
        "recognise",
        "solution region",
        "coordinate plane",
        "real problems",
        "After the box",
    ]
    positions = [text.find(p) for p in order]
    assert -1 not in positions, text
    assert positions == sorted(positions), text
    for published in text.splitlines():
        assert not ("alpha" in published and "recognise" in published)
    # Citations still resolve: every published block maps to its source words.
    record = json.loads((out / "extraction.json").read_text(encoding="utf-8"))
    assert "column_run" in json.dumps(record)


def _font(size):
    for candidate in (
        "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    pytest.skip("no TrueType font for the synthetic scan")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="real Tesseract required")
def test_real_tesseract_box_reading_order(tmp_path):
    """Real Tesseract on a drawn two-column box; truth is the drawing script."""
    font = _font(34)
    left = ["TERMS", "Linear inequality", "Solution region of", "an inequality"]
    right = [
        "KNOWLEDGE AND SKILLS",
        "Recognise a linear inequality.",
        "Draw the solution region on the",
        "coordinate plane of two variables.",
        "Apply it to practical problems.",
    ]
    image = Image.new("RGB", (1700, 1100), "white")
    draw = ImageDraw.Draw(image)
    draw.text((120, 80), "Lesson three introduces inequalities in two variables.", font=font, fill="black")
    draw.rectangle((100, 180, 1600, 490), outline=(80, 160, 220), width=4)
    # Book-like line spacing (about 1.5 line heights). Runs do not bridge
    # gaps over 1.3 word heights, so separate column areas stay separate.
    for i, text in enumerate(left):
        draw.text((140, 210 + 52 * i), text, font=font, fill="black")
    for i, text in enumerate(right):
        draw.text((720, 210 + 52 * i), text, font=font, fill="black")
    for y in range(200, 470, 18):
        draw.line((690, y, 690, y + 9), fill=(80, 160, 220), width=3)
    draw.text((120, 560), "After the box the lesson continues in a single column.", font=font, fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    path = tmp_path / "box.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=1700 * 72 / 200, height=1100 * 72 / 200)
        page.insert_image(page.rect, stream=buffer.getvalue())
        pdf.save(path)
    out = tmp_path / "out"
    DeepDocService(
        DeepDocConfig(engine="unified", canonical_version=2, language="eng")
    ).process_pdf(path, out)
    record = (out / "extraction.json").read_text(encoding="utf-8")
    text = "\n".join(
        b["text"] for p in load_canonical(out / "canonical.json")["pages"] for b in p["blocks"]
        if b["index_role"] == "primary"
    )
    for row in text.splitlines():
        assert not (any(w in row for w in ("Linear", "Solution", "TERMS")) and any(
            w in row for w in ("Recognise", "Draw", "KNOWLEDGE")
        )), text
    assert text.find("an inequality") < text.find("KNOWLEDGE") < text.find("After the box"), text
    assert "Lesson three" in text and record


# Formula recognition ------------------------------------------------------

RECORDED = Path(__file__).parent / "fixtures/recorded/formulanet-s-variance-loop.json"


def test_latex_check_flags_recorded_decoder_loop():
    # Real PP-FormulaNet_plus-S output for the SGK sample-variance crop.
    latex = json.loads(RECORDED.read_text(encoding="utf-8"))["rec_formula"]
    check = check_latex(latex)
    assert check["status"] == "review"
    assert "repetition" in check["reasons"]


@pytest.mark.parametrize(
    "latex,reasons",
    [
        # Real plus-S outputs measured on hand-labelled crops.
        (r"\Delta_{}}=19,5-9,5=10.", {"unbalanced_braces"}),
        (r" left\{\begin{cases}{x\geq0}\\ {y\geq0}\\ {x+y\leq150.}\\ \end{cases}\right.", {"unbalanced_left_right"}),
        (r"a{}}{^}{=}b{}^^2+c{}^{2}-2b c\operatorname{c o s}A,", {"unbalanced_braces"}),
        (r"s^{2}=\frac{(x)}{n}{}^{n}{}^{n}{}^{n}{}^{n}{}^{n}", {"repetition"}),
        (r"\frac12", {"frac_without_group"}),
        ("", {"empty"}),
    ],
)
def test_latex_check_reasons(latex, reasons):
    check = check_latex(latex)
    assert check["status"] == "review" and reasons <= set(check["reasons"])


@pytest.mark.parametrize(
    "latex",
    [
        # Real plus-M outputs on the same crops (syntax fine; correctness is
        # a separate question answered only against ground truth).
        r"\begin{cases}x\geq0\\y\geq0\\x+y\leq150.\end{cases}",
        r"\hat{S}^{2}=\frac{\left(X_{1}-\overline{X}\right)^{2}+\left(X_{2}-\overline{X}\right)^{2}+\cdots+\left(X_{n}-\overline{X}\right)^{2}}{n-1},",
        r"\frac{a}{\sin A}=\frac{b}{\sin B}=\frac{c}{\sin C}=2R.",
        r"x=1000000000",
    ],
)
def test_latex_check_accepts_well_formed_output(latex):
    assert check_latex(latex) == {"version": "latex-check:1", "status": "syntax_ok", "reasons": []}


def _formula_result(transport, data, latex, **extra):
    return {
        "schema": "deepdoc-model-result:1",
        "backend": "paddle-formula",
        "packages": {"unit": "recorded"},
        "weights_sha256": {},
        "input_sha256": hashlib.sha256(data).hexdigest(),
        "raw": {"rec_formula": latex},
        **extra,
    }


def _formula_backend(tmp_path, latex, model, **extra):
    from idp.ocr.backends.advanced import AdvancedBackend
    from idp.pdf.acquire import AcquisitionRequest
    from idp.pdf.native.preflight import PdfSource
    from idp.pdf.render import render_page

    class Recorded:
        backend = "paddle-formula"

        def __init__(self):
            self.model = model
            self.identity = {"backend": "paddle-formula", "model": model}

        def execute(self, image_bytes, *, deadline):
            return _formula_result(self, image_bytes, latex, **extra)

    source = PdfSource((Path(__file__).parent / "fixtures/generated/scan.pdf").read_bytes())
    image, frame = render_page(source, 1)
    backend = AdvancedBackend(tmp_path, Recorded())
    plan = AcquisitionRequest("k", frame, ((0, 0, *frame.steps[-1].output_size),))
    return source, backend, image, plan


def test_malformed_formula_is_flagged_and_never_confident(tmp_path):
    latex = json.loads(RECORDED.read_text(encoding="utf-8"))["rec_formula"]
    source, backend, image, plan = _formula_backend(tmp_path, latex, "PP-FormulaNet_plus-S")
    with source:
        result = backend.read(image, source, 1, plan, deadline=time.monotonic() + 30)
    block = result.blocks[0]
    assert block.label == "FORMULA" and block.confidence == 0
    assert block.payload["latex_check"]["status"] == "review"
    assert [d.code for d in result.diagnostics] == ["FORMULA_LATEX_REVIEW"]
    assert block.text  # raw model output is retained for audit, not rewritten


def test_formula_result_must_come_from_requested_model(tmp_path):
    # An older image ignores DEEPDOC_MODEL and loads plus-S without saying so.
    source, backend, image, plan = _formula_backend(tmp_path, "x=1", "PP-FormulaNet_plus-M")
    with source, pytest.raises(ValueError, match="requested model"):
        backend.read(image, source, 1, plan, deadline=time.monotonic() + 30)
    source, backend, image, plan = _formula_backend(
        tmp_path, "x=1", "PP-FormulaNet_plus-M", model_name="PP-FormulaNet_plus-M"
    )
    with source:
        assert backend.read(image, source, 1, plan, deadline=time.monotonic() + 30).blocks
    # The historical model needs no new worker field.
    source, backend, image, plan = _formula_backend(tmp_path, "x=1", "PP-FormulaNet_plus-S")
    with source:
        assert backend.read(image, source, 1, plan, deadline=time.monotonic() + 30).blocks


def test_formula_model_config_and_transport_identity(monkeypatch):
    import subprocess

    from idp.ocr.backends.advanced import DockerModelTransport
    from idp.runtime.lanes import configuration

    assert DeepDocConfig().formula_model == "PP-FormulaNet_plus-M"
    with pytest.raises(ValueError):
        DeepDocConfig(formula_model="PP-FormulaNet_plus-XL")
    assert configuration(limits={"formula_model": "PP-FormulaNet_plus-L"}).formula_model == "PP-FormulaNet_plus-L"

    class Inspect:
        stdout = "sha256:unit\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Inspect())
    m = DockerModelTransport("img", "paddle-formula", model="PP-FormulaNet_plus-M")
    s = DockerModelTransport("img", "paddle-formula")
    assert m.identity["model"] == "PP-FormulaNet_plus-M"
    assert s.identity["model"] == "PP-FormulaNet_plus-S"
    assert m.identity != s.identity
    assert m.model_env() == ["--env", "DEEPDOC_MODEL=PP-FormulaNet_plus-M"]
    with pytest.raises(ValueError):
        DockerModelTransport("img", "paddle-formula", model="other")
    with pytest.raises(ValueError):
        DockerModelTransport("img", "paddle-layout", model="PP-FormulaNet_plus-M")


def test_weight_fingerprint_covers_only_the_loaded_model(tmp_path, monkeypatch):
    from idp.ocr.backends import model_worker

    monkeypatch.setattr(model_worker.Path, "home", staticmethod(lambda: tmp_path))
    for name in ("PP-FormulaNet_plus-S", "PP-FormulaNet_plus-M"):
        folder = tmp_path / ".paddlex/official_models" / name
        folder.mkdir(parents=True)
        (folder / "inference.pdiparams").write_bytes(name.encode())
    only_m = model_worker.fingerprint_weights("paddle-formula", "PP-FormulaNet_plus-M")
    assert [Path(k) for k in only_m] == [
        Path("official_models/PP-FormulaNet_plus-M/inference.pdiparams")
    ]
    assert len(model_worker.fingerprint_weights("paddle-formula")) == 2


def test_gpu_oom_fallback_uses_cpu_image(monkeypatch, tmp_path):
    from idp.ocr.backends.advanced import DockerModelTransport
    from idp.ocr.backends.tesseract import BackendUnavailable
    from idp.pdf.resource import ResourceLedger
    from idp.runtime import paddle_pool
    from idp.runtime.model_pool import JobMarkerTransport

    def fake_init(self, image, backend, **kw):
        self.image, self.backend = image, backend
        self.device = kw.get("device", "cpu")
        self.container_device = "cpu" if self.device == "cpu" else "gpu:0"
        self.timeout_seconds, self.memory, self.cpus = 30, "4g", 2
        self.cache_family = "paddle"
        self.model = kw.get("model")
        self.identity = {"image_id": "sha256:" + image, "backend": backend}

    images = []

    def execute(self, data, **kw):
        images.append((self.image, self.device, self.model))
        if self.device != "cpu":
            raise BackendUnavailable("PADDLE_GPU_OOM")
        return {"unit": "cpu"}

    monkeypatch.setenv("DEEPDOC_GPU_LOCK_DIR", str(tmp_path))
    monkeypatch.setattr(DockerModelTransport, "__init__", fake_init)
    monkeypatch.setattr(JobMarkerTransport, "execute", execute)
    monkeypatch.setattr(JobMarkerTransport, "close", lambda self: None)
    transport = paddle_pool.PaddleSessionTransport(
        "paddle-formula", device="gpu:0", model="PP-FormulaNet_plus-M"
    )
    transport.ledger = ResourceLedger(time.monotonic() + 30, max_calls=5)
    transport.page = 1
    buffer = BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, format="PNG")
    transport.execute(buffer.getvalue(), deadline=time.monotonic() + 10)
    assert images == [
        (paddle_pool.GPU_IMAGE, "gpu:0", "PP-FormulaNet_plus-M"),
        (paddle_pool.CPU_IMAGE, "cpu", "PP-FormulaNet_plus-M"),
    ]
    transport.close()
