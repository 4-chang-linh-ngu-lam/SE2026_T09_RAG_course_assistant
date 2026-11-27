"""Offline RAG regressions through the same artifact and serving entrypoints."""

import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from rag.chunking.chunking import chunk_text, validate_chunking
from rag.chunking.token_budget import LocalTokenizer
from rag.citations.claim_verification import ClaimVerifier
from rag.citations.source_quotes import SourceBoundSchemaError, source_quote_enums
from rag.citations.span_mapping import quote_spans
from rag.generation.pipeline import GroundedTaskPipeline
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.retrieval.corpus import load_retriever
from rag.retrieval.retrieval import AccessChangedError, RetrievalConfig
from rag.retrieval.text_pipeline import TextRagPipeline
from rag.retrieval.verified_rag import VerifiedRagPipeline
from rag.search.retrieval_plan import SearchRequest
from rag.search.text_reranking import PairBudgetError


class WordCounter:
    identity: ClassVar = {"kind": "fixture_words", "unit": "tokens", "version": 1}

    def count(self, text):
        return len(re.findall(r"\w+|[^\w\s]", text)) + 2


class FakeEncoder:
    counter = WordCounter()
    identity: ClassVar = {
        "adapter": "fixture-bow",
        "dimension": 32,
        "passage_prefix": "",
    }

    def encode(self, texts, **_kwargs):
        vectors = np.zeros((len(texts), 32), dtype=np.float32)
        vectors[:, 0] = 1e-3
        for index, text in enumerate(texts):
            for word in re.findall(r"\w+", text.casefold()):
                column = hashlib.sha256(word.encode()).digest()[0] % 32
                vectors[index, column] += 1
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors, {"items": len(texts)}


def test_service_root_and_library_harness_import():
    script = (
        "from rag.retrieval.retrieval import TextRetriever; "
        "from rag.retrieval.canonical_harness import LocalRagIndex; "
        "from retrieval.canonical_harness import LocalRagIndex"
    )
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-c", "import sys;sys.path.insert(0, '..');" + script],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=30,
    )


@pytest.mark.parametrize("label", ["1.", "1.2.", "A.", "iv.", "Câu 2."])
@pytest.mark.parametrize("style", ["greedy", "cost"])
def test_long_single_sentence_keeps_leading_label(label, style):
    source = label + " " + "cần xác định dấu của biểu thức " * 30 + "."
    bundle = chunk_text(
        source,
        source_id="labels",
        counter=WordCounter(),
        max_tokens=30,
        split_strategy=style,
    )
    assert bundle["report"]["pass"]
    children = [row for row in bundle["children"] if row["retrieval_eligible"]]
    assert children and children[0]["text"].startswith(label)
    assert all(row["text"].strip() != label for row in children)
    for row in children:
        for span in row["source_spans"]:
            assert (
                row["text"][span["start"] : span["end"]]
                == source[span["source_start"] : span["source_end"]]
            )


def span(a, b, start):
    return {"start": a, "end": b, "source_start": start, "source_end": start + b - a}


def evidence(item_id, text, spans):
    return {
        "id": item_id,
        "text": text,
        "record": {"text": text, "source_id": "doc", "source_spans": spans},
    }


def test_short_quotes_do_not_poison_real_evidence():
    short = evidence("S1", "x", [span(0, 1, 100)])
    formula = evidence("S2", "$x\n+y", [span(0, 5, 12)])
    assert source_quote_enums([short, formula]) == {"S2": ["$x\n+y"]}
    assert quote_spans(formula, "$x\n+y") == [
        {"source_id": "doc", "start": 12, "end": 17}
    ]
    with pytest.raises(SourceBoundSchemaError, match="no_eligible_quote_snippet"):
        source_quote_enums([short])


def test_wrapped_sentence_is_one_quote_and_lines_stay_available():
    text = "y = 1 cũng thỏa mãn nhưng không nhận được từ nghiệm\ntổng quát nào.\n\nMục mới"
    quotes = source_quote_enums([evidence("S1", text, [span(0, len(text), 0)])])["S1"]
    assert "y = 1 cũng thỏa mãn nhưng không nhận được từ nghiệm\ntổng quát nào." in quotes
    assert "y = 1 cũng thỏa mãn nhưng không nhận được từ nghiệm" in quotes
    assert "Mục mới" in quotes
    assert not any("\n\n" in quote for quote in quotes)


def test_unbroken_overlong_token_leaves_neighbor_quotes_available():
    text = "Căn cứ trước " + "x" * 180 + " căn cứ sau"
    item = evidence("S1", text, [span(0, len(text), 25)])
    assert source_quote_enums([item]) == {"S1": ["Căn cứ trước", "căn cứ sau"]}


def test_quote_maps_later_occurrence_and_rejects_overlapping_geometry():
    repeated = evidence("S1", "abc abc", [span(4, 7, 40)])
    assert quote_spans(repeated, "abc") == [
        {"source_id": "doc", "start": 40, "end": 43}
    ]
    assert source_quote_enums(
        [repeated, evidence("S2", "known value", [span(0, 11, 0)])]
    ) == {"S2": ["known value"]}
    with pytest.raises(ValueError, match="invalid_evidence_source_spans"):
        quote_spans(evidence("S1", "abcdef", [span(0, 2, 0), span(1, 3, 1)]), "abcd")


LESSON = """# Chương 1. Mệnh đề

## Bài 1.2. Tên bài cùng số

Đoạn giới thiệu về chủ đề, không phải bài tập.

### Luyện tập

1.2. Xác định tập hợp phần tử của ví dụ coban.
2. Giải thích định nghĩa quang hợp trong lá cây.

| Chất | Ký hiệu |
| --- | --- |
| Cobalt | Co |
"""
DENIED = "# Luyện tập\n\n1.2. secret-lavender chỉ tồn tại trong tài liệu khác.\n"


@pytest.fixture(scope="module")
def corpus(tmp_path_factory):
    root = tmp_path_factory.mktemp("rag-corpus")
    encoder = FakeEncoder()
    build_corpus(
        [TextDocument("visible", LESSON), TextDocument("denied", DENIED)],
        root,
        encoder=encoder,
        max_tokens=48,
    )
    return root, encoder


def load(corpus, **kwargs):
    path, encoder = corpus
    return load_retriever(path, encoder=encoder, **kwargs)[0]


def permitted(retriever, source="visible"):
    return {
        cid for cid, row in retriever.children.items() if row["source_id"] == source
    }


@pytest.mark.parametrize(
    ("question", "label"), [("bài 1.2", "1.2"), ("câu 2", "2"), ("bai 1.2", "1.2")]
)
def test_numbered_practice_wins_over_lesson_anchor(corpus, question, label):
    retriever = load(corpus)
    result = retriever.retrieve(
        SearchRequest(question, context_hint="trang 99"),
        authorize=lambda: permitted(retriever),
    )
    winner = retriever.children[result["ranked_child_ids"][0]]
    assert winner["unit_label"] == label and winner["unit_kind"] == "exercise"
    assert result["trace"]["passes"][0]["primary_seeds"][0] == winner["id"]


def test_accent_fallback_and_cache_follow_current_scope(corpus):
    retriever = load(corpus, config=RetrievalConfig(arms=("lexical",)))
    request = SearchRequest("quang hop")
    one = retriever.retrieve(request, authorize=lambda: permitted(retriever))
    assert one["trace"]["passes"][0]["accent_fallback"][0]["applied"]
    warm = retriever.retrieve(request, authorize=lambda: permitted(retriever))
    assert warm["ranked_child_ids"] == one["ranked_child_ids"]
    assert retriever._lexical_index.cache_info().hits == 2
    denied_now = retriever.retrieve(
        request, authorize=lambda: permitted(retriever, "denied")
    )
    assert not denied_now["ranked_child_ids"]
    scoped = retriever.retrieve(
        SearchRequest("secret lavender", scope_source_ids=frozenset({"visible"})),
        authorize=lambda: set(retriever.children),
    )
    assert "secret-lavender" not in scoped["context"]["context"]
    assert retriever._lexical_index.cache_info().currsize <= 4


class Reranker:
    identity: ClassVar = {"kind": "fixture_reranker"}

    def __init__(self, fail):
        self.fail = fail

    def score(self, _query, texts):
        assert all("secret-lavender" not in value for value in texts)
        if self.fail:
            raise PairBudgetError("fixture overflow")
        return np.arange(len(texts), dtype=np.float32), {"items": len(texts)}


@pytest.mark.parametrize("mode", ["chunks", "passages"])
@pytest.mark.parametrize("fail", [False, True])
def test_rerank_packing_and_offsets(corpus, mode, fail):
    config = RetrievalConfig(
        context_selection=mode, context_tokens=120, extend_continuations=True
    )
    retriever = load(corpus, config=config, reranker=Reranker(fail))
    allowed = permitted(retriever)
    result = retriever.retrieve(SearchRequest("coban"), authorize=lambda: allowed)
    context = result["context"]
    assert (
        context["items"]
        and retriever.counter.count(context["context"])
        == context["budget_count"]
        <= 120
    )
    assert result["trace"]["passes"][0]["rerank"]["status"] == (
        "failed_fallback_rrf" if fail else "applied"
    )
    assert set(result["ranked_child_ids"]) <= allowed
    for item in context["items"]:
        assert item["source_id"] == "visible"
        assert set(item["child_ids"]) <= allowed
        for bounds in item["source_spans"]:
            assert (
                item["text"][bounds["start"] : bounds["end"]]
                == LESSON[bounds["source_start"] : bounds["source_end"]]
            )


def test_revocation_discards_retrieval_even_with_warm_cache(corpus):
    retriever = load(corpus)
    allowed = permitted(retriever)
    retriever.retrieve(SearchRequest("coban"), authorize=lambda: allowed)
    snapshots = iter([allowed, set()])
    with pytest.raises(AccessChangedError):
        retriever.retrieve(SearchRequest("coban"), authorize=lambda: next(snapshots))


class ScriptedGenerator:
    identity: ClassVar = {"kind": "fixture_generator"}
    context_tokens = 4096

    def __init__(self, *, revoke=lambda: None):
        self.revoke = revoke

    def count_messages(self, messages):
        return sum(len(m["content"].split()) for m in messages)

    def generate(self, messages, schema, **_kwargs):
        payload = json.loads(messages[-1]["content"])
        if "evidence_catalog" in payload:
            item = payload["evidence_catalog"][0]
            quote = item["text"].strip().splitlines()[0]
            response = {
                "decisions": [
                    {
                        "claim_id": "C1",
                        "verdict": "supported",
                        "question_match": "yes",
                        "evidence_id": item["evidence_id"],
                        "quote": quote,
                    }
                ]
            }
        else:
            branches = schema["oneOf"][0]["properties"]["claims"]["items"][
                "properties"
            ]["evidence"]["items"]["oneOf"]
            claim = next(b["properties"] for b in branches if "coban" in str(b))
            quote = next(q for q in claim["quote"]["enum"] if "coban" in q)
            response = {
                "status": "answered",
                "claims": [
                    {
                        "text": quote,
                        "evidence": [{"id": claim["id"]["const"], "quote": quote}],
                    }
                ],
            }
        self.revoke()
        return {"text": json.dumps(response), "finish_reason": "stop"}


def test_verified_pipeline_uses_real_retrieval_and_exact_citations(corpus):
    retriever = load(corpus)
    base = TextRagPipeline(retriever, GroundedTaskPipeline(ScriptedGenerator()))
    verified = VerifiedRagPipeline(base, ClaimVerifier(ScriptedGenerator()))
    result = verified.answer(
        SearchRequest("bài 1.2 coban"), authorize=lambda: permitted(retriever)
    )
    assert result["status"] == "answered"
    cite = result["claims"][0]["evidence"][0]
    assert all(s["source_id"] == "visible" for s in cite["source_spans"])
    assert (
        "".join(LESSON[s["start"] : s["end"]] for s in cite["source_spans"])
        == cite["quote"]
    )
    assert not result["certifies_answer_correctness"]


def test_pipeline_discards_answer_if_grant_changes_during_generation(corpus):
    retriever = load(corpus)
    allowed = permitted(retriever)
    base = TextRagPipeline(
        retriever, GroundedTaskPipeline(ScriptedGenerator(revoke=allowed.clear))
    )
    with pytest.raises(AccessChangedError):
        base.answer(SearchRequest("bài 1.2 coban"), authorize=lambda: allowed)


def test_pipeline_refuses_when_only_quotable_content_is_denied(tmp_path):
    encoder = FakeEncoder()
    build_corpus(
        [
            TextDocument("visible", "x\n"),
            TextDocument("denied", "Thông tin chính xác.\n"),
        ],
        tmp_path,
        encoder=encoder,
        max_tokens=48,
    )
    retriever = load_retriever(tmp_path, encoder=encoder)[0]
    generator = ScriptedGenerator(revoke=lambda: pytest.fail("unexpected generation"))
    pipeline = TextRagPipeline(retriever, GroundedTaskPipeline(generator))
    result = pipeline.answer(SearchRequest("x"), authorize=lambda: permitted(retriever))
    assert result["status"] == "insufficient_evidence"
    assert result["refusal_reason"] == "evidence_not_quotable"
    assert result["evidence"] == []


@pytest.mark.parametrize("newline, form", [("\n", "NFC"), ("\r\n", "NFD")])
def test_table_formula_and_numbered_text_keep_offsets(newline, form):
    text = unicodedata.normalize(
        form, (LESSON + "\n$$\nx^2 + y^2\n$$\n").replace("\n", newline)
    )
    budget = WordCounter()
    bundle = chunk_text(text, source_id="source", counter=budget, max_tokens=48)
    assert not validate_chunking(bundle, text, counter=budget)
    for child in bundle["children"]:
        for bounds in child["source_spans"]:
            assert (
                child["text"][bounds["start"] : bounds["end"]]
                == text[bounds["source_start"] : bounds["source_end"]]
            )


def test_real_tokenizer_loads_local_file(tmp_path):
    tokenizers = pytest.importorskip("tokenizers")
    model = tokenizers.models.WordLevel(
        {"[UNK]": 0, "quang": 1, "hợp": 2}, unk_token="[UNK]"
    )
    tokenizer = tokenizers.Tokenizer(model)
    tokenizer.pre_tokenizer = tokenizers.pre_tokenizers.Whitespace()
    path = tmp_path / "tokenizer.json"
    tokenizer.save(str(path))
    assert LocalTokenizer(path).count("quang hợp") == 2
