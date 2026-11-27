"""Regressions for retrieval, search, ranking, and packing fixes."""

from pathlib import Path
from typing import ClassVar

import numpy as np
import pytest
from rag.chunking import chunk_text
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.packing.continuation_context import extend_continuations
from rag.packing.retrieval_context import expand_context
from rag.retrieval.corpus import load_retriever
from rag.retrieval.retrieval import RetrievalConfig
from rag.search.retrieval_bridge import bridge_terms
from rag.search.retrieval_lexical import FieldedBM25, normalize_vi_orthography
from rag.search.retrieval_plan import SearchRequest, terms
from rag.search.text_reranking import OnnxCrossEncoder, PairBudgetError

from test_rag_core import FakeEncoder, WordCounter


def test_context_hint_with_accents_does_not_disable_accent_fallback(tmp_path):
    doc = (
        "# Chương 1. Tam giác vuông\n\n"
        "Định lý Pytago phát biểu bình phương cạnh huyền bằng tổng bình phương hai cạnh góc vuông.\n\n"
        "# Chương 2. Hàm số\n\n"
        "Đồ thị hàm số bậc nhất là một đường thẳng.\n"
    )
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", doc)], tmp_path, encoder=encoder, max_tokens=64)
    retriever = load_retriever(
        tmp_path,
        encoder=encoder,
        config=RetrievalConfig(arms=("lexical", "section"), enable_recovery=False),
    )[0]
    res = retriever.retrieve(
        SearchRequest("dinh ly pytago canh huyen", context_hint="Chương 1: Hình học"),
        authorize=lambda: set(retriever.children),
    )
    accent_info = res["trace"]["passes"][0]["accent_fallback"][0]
    assert accent_info["applied"] is True
    assert "Pytago" in retriever.children[res["ranked_child_ids"][0]]["text"]


def test_mixed_accent_query_triggers_fallback_without_false_folding(tmp_path):
    doc = (
        "# Hình học\n\n"
        "Tam giác vuông có một góc bằng 90 độ.\n\n"
        "# Từ vựng\n\n"
        "Hãy tìm cách giải ngắn gọn nhất cho bài toán.\n"
    )
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", doc)], tmp_path, encoder=encoder, max_tokens=64)
    retriever = load_retriever(
        tmp_path,
        encoder=encoder,
        config=RetrievalConfig(arms=("lexical",), enable_recovery=False),
    )[0]
    mixed = retriever.retrieve(
        SearchRequest("Định lý về tam giac vuong"),
        authorize=lambda: set(retriever.children),
    )
    assert mixed["trace"]["passes"][0]["accent_fallback"][0]["applied"] is True
    assert "Tam giác vuông" in retriever.children[mixed["ranked_child_ids"][0]]["text"]

    # Explicitly accented OOV token ("tím") must NOT falsely fold to "tìm".
    explicit_accented = retriever.retrieve(
        SearchRequest("màu tím"),
        authorize=lambda: set(retriever.children),
    )
    assert explicit_accented["trace"]["passes"][0]["accent_fallback"] == []
    assert explicit_accented["ranked_child_ids"] == []


def test_fielded_bm25_body_bigrams_boost_exact_phrase_without_polluting_fields():
    rows = [
        {
            "id": "scattered",
            "index_body": "Phương pháp giải bài tập tổng hợp và quá trình ôn tập chương.",
            "text": "Phương pháp giải bài tập tổng hợp và quá trình ôn tập chương.",
            "section_path": [],
        },
        {
            "id": "phrase",
            "index_body": "Giải phương trình bậc hai một ẩn theo công thức nghiệm.",
            "text": "Giải phương trình bậc hai một ẩn theo công thức nghiệm.",
            "section_path": [],
        },
    ]
    bm25 = FieldedBM25(rows)
    ranked = bm25.rank("phương trình")
    assert ranked[0][0] == "phrase"
    # Pure unigram contract in fields["body"] stays intact for bridge/probe callers.
    assert not any("\u241f" in term for term in bm25.fields["body"][2])
    assert isinstance(bridge_terms(bm25, rows[1]["index_body"], "phương trình", limit=3), list)


def test_smart_recovery_skips_redundant_pass2_for_absent_anchor_or_small_pool(tmp_path):
    class CountingReranker:
        identity: ClassVar = {"kind": "counting_reranker"}

        def __init__(self):
            self.calls = 0

        def score(self, _query, texts):
            self.calls += 1
            return np.linspace(1.0, 0.1, num=len(texts), dtype=np.float32), {"items": len(texts)}

    doc = "\n\n".join(
        f"# Luyện tập\n\n{i}. Nội dung bài tập số {i} về phương trình bậc nhất."
        for i in range(1, 6)
    )
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", doc)], tmp_path, encoder=encoder, max_tokens=48)
    reranker = CountingReranker()
    retriever = load_retriever(
        tmp_path,
        encoder=encoder,
        reranker=reranker,
        config=RetrievalConfig(recall_per_arm=20, fusion_limit=20, rerank_limit=20, seed_limit=5),
    )[0]
    # Absent anchor ("bài 99") cannot be found by widening depth when structure searched all eligible.
    res = retriever.retrieve(
        SearchRequest("bài 99"),
        authorize=lambda: set(retriever.children),
    )
    assert len(res["trace"]["passes"]) == 1
    assert reranker.calls == 1

    # Large pool with missing facet & saturated arm still triggers recovery pass 2.
    big_doc = "# Tổng hợp\n\n" + "\n\n".join(
        f"Đoạn {i} trình bày khái niệm cơ bản về hàm số và đồ thị." for i in range(40)
    ) + "\n\nĐoạn cuối nhắc tới định lý Vi-ét đặc biệt.\n"
    big_dir = tmp_path / "big"
    build_corpus([TextDocument("big", big_doc)], big_dir, encoder=encoder, max_tokens=24)
    big_ret = load_retriever(
        big_dir,
        encoder=encoder,
        config=RetrievalConfig(
            recall_per_arm=2,
            fusion_limit=4,
            rerank_limit=4,
            seed_limit=1,
            neighbor_radius=0,
        ),
    )[0]
    big_res = big_ret.retrieve(
        SearchRequest("hàm số", facets=("hàm số", "Vi-ét")),
        authorize=lambda: set(big_ret.children),
    )
    assert len(big_res["trace"]["passes"]) == 2


def test_reranker_retries_raw_query_on_pair_budget_and_cross_encoder_accepts_8192(tmp_path):
    class BudgetReranker:
        identity: ClassVar = {"kind": "budget_reranker"}

        def __init__(self, limit_chars: int):
            self.limit_chars = limit_chars
            self.queries = []

        def score(self, query, texts):
            self.queries.append(query)
            if any(len(query) + len(t) > self.limit_chars for t in texts):
                raise PairBudgetError("pair exceeds budget")
            return np.arange(len(texts), 0, -1, dtype=np.float32), {"items": len(texts)}

    doc = "# Mục 1\n\nQuang hợp chuyển hóa năng lượng ánh sáng thành năng lượng hóa học.\n"
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", doc)], tmp_path, encoder=encoder, max_tokens=64)

    # 1) context_hint pushes pair over limit -> retries cleanly with raw_query.
    reranker = BudgetReranker(limit_chars=120)
    retriever = load_retriever(
        tmp_path,
        encoder=encoder,
        reranker=reranker,
        config=RetrievalConfig(enable_recovery=False),
    )[0]
    res = retriever.retrieve(
        SearchRequest("quang hợp là gì", context_hint="Ghi chú ngữ cảnh rất dài " * 8),
        authorize=lambda: set(retriever.children),
    )
    rerank_trace = res["trace"]["passes"][0]["rerank"]
    assert rerank_trace["status"] == "applied"
    assert rerank_trace["used_raw_query"] is True
    assert len(reranker.queries) == 2

    # 2) Even raw_query overflows -> falls back cleanly to RRF.
    strict_reranker = BudgetReranker(limit_chars=10)
    strict_ret = load_retriever(
        tmp_path,
        encoder=encoder,
        reranker=strict_reranker,
        config=RetrievalConfig(enable_recovery=False),
    )[0]
    strict_res = strict_ret.retrieve(
        SearchRequest("quang hợp là gì"),
        authorize=lambda: set(strict_ret.children),
    )
    assert strict_res["trace"]["passes"][0]["rerank"]["status"] == "failed_fallback_rrf"

    # 3) OnnxCrossEncoder validates max_tokens up to 8192 (and rejects > 8192).
    with pytest.raises(ValueError, match="8..8192"):
        OnnxCrossEncoder(
            Path("missing.onnx"),
            Path("missing.json"),
            provenance={"repo": "r", "revision": "1", "variant": "fp32"},
            max_tokens=8193,
        )


def test_shared_query_vector_cache_encodes_once_across_retrievers(tmp_path):
    class QueryCountingEncoder(FakeEncoder):
        def __init__(self):
            self.query_encode_calls = 0

        def encode(self, texts, **kwargs):
            if kwargs.get("role") == "query":
                self.query_encode_calls += 1
            return super().encode(texts, **kwargs)

    enc = QueryCountingEncoder()
    d1, d2 = tmp_path / "d1", tmp_path / "d2"
    build_corpus([TextDocument("a", "# A\n\nNội dung toán học về ma trận.\n")], d1, encoder=enc, max_tokens=64)
    build_corpus([TextDocument("b", "# B\n\nNội dung vật lý về dao động.\n")], d2, encoder=enc, max_tokens=64)

    r1 = load_retriever(d1, encoder=enc, config=RetrievalConfig(enable_recovery=False))[0]
    r2 = load_retriever(d2, encoder=enc, config=RetrievalConfig(enable_recovery=False))[0]

    shared_cache = {}
    out1 = r1.retrieve(SearchRequest("ma trận"), authorize=lambda: set(r1.children), query_vector_cache=shared_cache)
    out2 = r2.retrieve(SearchRequest("ma trận"), authorize=lambda: set(r2.children), query_vector_cache=shared_cache)
    assert enc.query_encode_calls == 1
    assert out1["trace"]["query_embeddings_computed"] == 1
    assert out2["trace"]["query_embeddings_computed"] == 0

    # include_trace=False preserves identical ranking & packed items.
    fast_out = r1.retrieve(
        SearchRequest("ma trận"),
        authorize=lambda: set(r1.children),
        query_vector_cache=shared_cache,
        include_trace=False,
    )
    assert fast_out["ranked_child_ids"] == out1["ranked_child_ids"]
    assert fast_out["context"]["items"] == out1["context"]["items"]


def test_extend_continuations_accepts_context_eligible_atom(tmp_path):
    formula = "$$\n" + " + ".join(f"x_{i}" for i in range(40)) + "\n$$"
    # Unfinished prose leading into the rest of the sentence before an oversized formula atom.
    text = (
        "# Mục\n\n"
        "Ta xét biểu thức chưa kết thúc là "
        + "giá trị đại số liên quan đến " * 4
        + "tổng cuối cùng.\n\n"
        + formula
        + "\n"
    )
    bundle = chunk_text(text, source_id="s", counter=WordCounter(), max_tokens=28)
    assert bundle["report"]["pass"], bundle["report"]["errors"]
    eligible = [c for c in bundle["children"] if c["retrieval_eligible"]]
    held = [c for c in bundle["children"] if c["context_eligible"]]
    assert held
    every = {c["id"] for c in bundle["children"]}
    base = expand_context(bundle, [eligible[0]["id"]], allowed_child_ids=every, counter=WordCounter(), max_tokens=400, mode="child")
    extended = extend_continuations(bundle, base, allowed_child_ids=every, counter=WordCounter(), max_tokens=400)
    assert extended["continuation_extension"]["applied_count"] >= 1
    assert "tổng cuối cùng." in extended["context"]

    # End-to-end through TextRetriever with extend_continuations=True and packing_allowed.
    enc = FakeEncoder()
    build_corpus([TextDocument("doc", text)], tmp_path, encoder=enc, max_tokens=28)
    retriever = load_retriever(
        tmp_path,
        encoder=enc,
        config=RetrievalConfig(
            extend_continuations=True,
            seed_limit=1,
            neighbor_radius=0,
            enable_recovery=False,
        ),
    )[0]
    out = retriever.retrieve(
        SearchRequest("biểu thức chưa kết thúc"),
        authorize=lambda: set(retriever.children),
    )
    assert out["context"]["continuation_extension"]["applied_count"] >= 1


def test_normalize_vi_orthography_and_fielded_bm25_and_section_arm(tmp_path):
    equivalent_pairs = [
        ("toạ", "tọa"),
        ("hoá", "hóa"),
        ("hoà", "hòa"),
        ("thoả", "thỏa"),
        ("thuỷ", "thủy"),
        ("luỹ", "lũy"),
        ("tuỳ", "tùy"),
        ("oà", "òa"),
        ("oè", "òe"),
        ("uý", "úy"),
        ("TOẠ", "TỌA"),
        ("lí", "lý"),
        ("kĩ", "kỹ"),
        ("tỉ", "tỷ"),
        ("kí", "ký"),
        ("kì", "kỳ"),
        ("mĩ", "mỹ"),
        ("qui", "quy"),
        ("quí", "quý"),
        ("quĩ", "quỹ"),
        ("sĩ", "sỹ"),
    ]
    for old_form, new_form in equivalent_pairs:
        assert normalize_vi_orthography(old_form) == normalize_vi_orthography(new_form)

    distinct_pairs = [
        ("tòa", "tọa"),
        ("hòa", "hóa"),
        ("hòa", "họa"),
        ("kì", "kí"),
        ("kĩ", "kỉ"),
    ]
    for a, b in distinct_pairs:
        assert normalize_vi_orthography(a) != normalize_vi_orthography(b)

    assert normalize_vi_orthography("café") == "café"
    assert normalize_vi_orthography("y1/y2") == "y1/y2"
    assert normalize_vi_orthography("x2") == "x2"
    # Cross-service contract: retrieval_plan.terms() must stay unmodified.
    assert terms("tọa độ định lý") == ["tọa", "độ", "định", "lý"]

    rows = [
        {
            "id": "sgk_old",
            "index_body": "Hệ trục toạ độ Oxyz và định lí cộng góc, kĩ thuật tính tỉ số hai đoạn thẳng.",
            "text": "Hệ trục toạ độ Oxyz và định lí cộng góc, kĩ thuật tính tỉ số hai đoạn thẳng.",
            "section_path": ["Hệ trục toạ độ và định lí"],
        },
        {
            "id": "other",
            "index_body": "Phương trình bậc nhất một ẩn và đồ thị đường thẳng.",
            "text": "Phương trình bậc nhất một ẩn và đồ thị đường thẳng.",
            "section_path": ["Hàm số bậc nhất"],
        },
    ]
    bm25 = FieldedBM25(rows)
    ranked = bm25.rank("tọa độ định lý kỹ thuật tỷ số")
    assert ranked[0][0] == "sgk_old"
    assert bm25.matched_term_count("tọa độ định lý kỹ thuật tỷ số") == 8
    folded_bm25 = FieldedBM25(rows, fold_accents=True)
    assert folded_bm25.matched_term_count("dinh ly ky thuat ty so qui tac") >= 5

    doc = (
        "# Hệ trục toạ độ và định lí\n\n"
        "Kĩ thuật tính tỉ số đoạn thẳng và bài toán hoá học liên quan thuỷ lực.\n\n"
        "# Hàm số bậc nhất\n\n"
        "Đồ thị hàm số bậc nhất là đường thẳng.\n"
    )
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", doc)], tmp_path, encoder=encoder, max_tokens=64)

    for arms in (("lexical",), ("section",), ("lexical", "section")):
        retriever = load_retriever(
            tmp_path,
            encoder=encoder,
            config=RetrievalConfig(arms=arms, enable_recovery=False),
        )[0]
        res = retriever.retrieve(
            SearchRequest("tọa độ định lý kỹ thuật tỷ số hóa học thủy lực"),
            authorize=lambda r=retriever: set(r.children),
        )
        assert res["ranked_child_ids"]
        top_child = retriever.children[res["ranked_child_ids"][0]]
        assert "toạ độ" in top_child["search_text"]
        assert "Kĩ thuật tính tỉ số" in top_child["text"]
        assert res["trace"]["passes"][0]["accent_fallback"] == []


def test_opt_in_lexical_folded_boost_default_off_and_ocr_rescue(tmp_path):
    assert RetrievalConfig().lexical_folded_boost == 0.0
    for bad in (-0.1, 1.1, True, float("nan")):
        with pytest.raises(ValueError, match="lexical_folded_boost"):
            RetrievalConfig(lexical_folded_boost=bad)

    doc = (
        "# Thiết bị phần cứng\n\n"
        "Hệ thống két nói các thiết bị trong phòng thí nghiệm.\n\n"
        "# Tổng quan hệ thống\n\n"
        "Tổng quan kiến trúc lưu trữ dữ liệu.\n"
    )
    encoder = FakeEncoder()
    build_corpus([TextDocument("doc", doc)], tmp_path, encoder=encoder, max_tokens=64)

    off_retriever = load_retriever(
        tmp_path,
        encoder=encoder,
        config=RetrievalConfig(arms=("lexical",), enable_recovery=False),
    )[0]
    off_res = off_retriever.retrieve(
        SearchRequest("kết nối"),
        authorize=lambda: set(off_retriever.children),
    )
    assert off_res["ranked_child_ids"] == []
    assert off_res["trace"]["passes"][0]["accent_fallback"] == []

    on_retriever = load_retriever(
        tmp_path,
        encoder=encoder,
        config=RetrievalConfig(arms=("lexical",), enable_recovery=False, lexical_folded_boost=0.25),
    )[0]
    on_res = on_retriever.retrieve(
        SearchRequest("kết nối"),
        authorize=lambda: set(on_retriever.children),
    )
    assert len(on_res["ranked_child_ids"]) == 1
    assert "két nói" in on_retriever.children[on_res["ranked_child_ids"][0]]["text"]

    # When accent_fallback is False, lexical_folded_boost must not trigger accent_fallback.
    no_fallback_ret = load_retriever(
        tmp_path,
        encoder=encoder,
        config=RetrievalConfig(
            arms=("lexical",), enable_recovery=False, accent_fallback=False, lexical_folded_boost=0.25
        ),
    )[0]
    no_fallback_res = no_fallback_ret.retrieve(
        SearchRequest("ket noi"),
        authorize=lambda: set(no_fallback_ret.children),
    )
    assert no_fallback_res["trace"]["passes"][0]["accent_fallback"] == []
    assert no_fallback_res["ranked_child_ids"]

    # Equal-length exact accent match outranks OCR typo even with boost enabled.
    tie_dir = tmp_path / "tie"
    tie_doc = (
        "# Kênh 1\n\nHệ thống két nói thiết bị đo.\n\n"
        "# Kênh 2\n\nHệ thống kết nối thiết bị đo.\n"
    )
    build_corpus([TextDocument("tie", tie_doc)], tie_dir, encoder=encoder, max_tokens=64)
    tie_ret = load_retriever(
        tie_dir,
        encoder=encoder,
        config=RetrievalConfig(arms=("lexical",), enable_recovery=False, lexical_folded_boost=0.25),
    )[0]
    tie_res = tie_ret.retrieve(
        SearchRequest("kết nối thiết bị đo"),
        authorize=lambda: set(tie_ret.children),
    )
    assert len(tie_res["ranked_child_ids"]) == 2
    assert "kết nối" in tie_ret.children[tie_res["ranked_child_ids"][0]]["text"]


def test_source_quote_enums_duplicate_quote_span_fallback():
    from rag.citations.source_quotes import source_quote_enums

    prefix = "Định nghĩa cơ bản. "
    body = "Hàm số đồng biến trên khoảng đang xét."
    text = prefix + body + "\n\n" + body
    # Second occurrence has valid source_spans; first occurrence lies outside spans.
    first_end = len(prefix) + len(body)
    second_start = len(prefix) + len(body) + 2
    ev = [
        {
            "id": "S1",
            "text": text,
            "record": {
                "source_id": "doc",
                "text": text,
                "source_spans": [
                    {"start": 0, "end": len(prefix.strip()), "source_start": 0, "source_end": len(prefix.strip())},
                    {"start": second_start, "end": len(text), "source_start": first_end, "source_end": first_end + len(body)},
                ],
            },
        }
    ]
    enums = source_quote_enums(ev)
    assert body in enums["S1"]


def test_neighbor_context_fast_bounds_matches_exact_local_tokenizer(tmp_path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel
    from tokenizers.pre_tokenizers import Whitespace
    from rag.chunking.token_budget import LocalTokenizer
    from rag.packing.neighbor_context import neighbor_context

    vocab = {"<unk>": 0, "<pad>": 1}
    words = [
        "toán", "học", "lớp", "10", "phương", "trình", "đồ", "thị", "hàm", "số",
        "nghiệm", "bài", "tập", "ví", "dụ", "đoạn", "văn", "mẫu", "s1", "child",
    ]
    for idx, w in enumerate(words, 2):
        vocab[w] = idx
    tok = Tokenizer(WordLevel(vocab=vocab, unk_token="<unk>"))
    tok.pre_tokenizer = Whitespace()
    tok_path = tmp_path / "tok.json"
    tok.save(str(tok_path))

    real_counter = LocalTokenizer(tok_path)

    class ReferenceCounter:
        identity = {"kind": "reference_exact", "unit": "tokens"}

        def count(self, text: str) -> int:
            return real_counter.count(text)

    children = {}
    child_ids = []
    for i in range(6):
        cid = f"child_{i}"
        child_ids.append(cid)
        text = " ".join(words[2 + (i % 6) : 12 + (i % 4)])
        children[cid] = {
            "id": cid,
            "source_id": "s1",
            "section_path": [],
            "text": text,
            "search_text": text,
            "parent_id": "p1",
            "parent_start": i * 50,
            "parent_end": (i + 1) * 50,
            "source_spans": [{"start": 0, "end": len(text), "source_start": i * 50, "source_end": i * 50 + len(text)}],
            "retrieval_eligible": True,
        }
    parent_text = "".join(children[cid]["text"] for cid in child_ids)
    parents = {"p1": {"id": "p1", "source_id": "s1", "section_path": [], "text": parent_text, "source_spans": [], "child_ids": child_ids}}
    eligible = set(child_ids)
    token_map = {cid: real_counter.count(children[cid]["search_text"]) for cid in child_ids}

    for budget in (35, 65, 120):
        fast = neighbor_context(
            children, parents, [child_ids[1], child_ids[4]], eligible,
            counter=real_counter, max_tokens=budget, radius=1, child_token_counts=token_map,
        )
        exact = neighbor_context(
            children, parents, [child_ids[1], child_ids[4]], eligible,
            counter=ReferenceCounter(), max_tokens=budget, radius=1,
        )
        assert [it["id"] for it in fast["items"]] == [it["id"] for it in exact["items"]]
        assert [it["text"] for it in fast["items"]] == [it["text"] for it in exact["items"]]
        assert fast["budget_count"] == exact["budget_count"]
