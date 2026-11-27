"""Regressions for the 2026-11-18 public-benchmark failure classes.

ViRE/RAGBench/ViDoRe themselves are not vendored; these fixtures reproduce the
mechanism of each miss with small, license-free text.
"""

import pytest
from rag.indexing.rag_corpus import TextDocument, build_corpus
from rag.retrieval.canonical_harness import LocalRagIndex, _fuse_page_evidence, _page_rows
from rag.retrieval.corpus import load_retriever
from rag.retrieval.retrieval import RetrievalConfig
from rag.search.retrieval_bridge import bridge_rank, bridge_terms
from rag.search.retrieval_lexical import FieldedBM25
from rag.search.retrieval_plan import SearchRequest

from test_rag_core import FakeEncoder

# Shape of RAGBench HotpotQA row 16: bands "formed in ... city" outrank the
# answer unit, which shares no rare term with the question; only the
# first-hop album unit names the band.
TWO_HOP = {
    "album": "Telos marks the first album from Forevermore. Solid State Records "
             "released Telos on July 22, 2014.",
    "band": "Forevermore is an American Christian metal band from Indianapolis, "
            "Indiana, formed in 2009.",
    "other_band": "Vampire Weekend is an American rock band from New York City.",
    "d1": "Arcade Fire is an indie band formed in the city of Montreal.",
    "d2": "The Strokes are a rock band formed in New York City.",
    "d3": "Muse is a rock band formed in the city of Teignmouth.",
    "f1": "Photosynthesis converts light into chemical energy.",
    "f2": "The Nile flows north through Egypt into the sea.",
}
QUESTION = "Telos album: the band who made it formed in what city?"


def bm25():
    rows = [{"id": key, "text": text, "section_path": []} for key, text in TWO_HOP.items()]
    return FieldedBM25(rows, fold_accents=True)


def test_bridge_terms_come_from_seed_and_skip_query_terms():
    index = bm25()
    extra = bridge_terms(index, TWO_HOP["album"], QUESTION, limit=5)
    assert "forevermore" in extra
    assert not {"telos", "album", "band"} & set(extra)
    with pytest.raises(ValueError):
        bridge_terms(index, TWO_HOP["album"], QUESTION, limit=0)


def test_bridge_hop_lifts_second_evidence_unit():
    index = bm25()
    first = index.rank(QUESTION)
    assert first[0][0] == "album"
    before = [cid for cid, _ in first].index("band")
    fused, trace = bridge_rank(index, QUESTION, first, TWO_HOP.__getitem__, seeds=1)
    order = [cid for cid, _ in fused]
    assert trace["applied"] and trace["seeds"][0]["id"] == "album"
    assert order[0] == "album"
    assert order.index("band") < before
    assert order.index("band") <= 2
    # Off means byte-identical first-hop order.
    same, off = bridge_rank(index, QUESTION, first, TWO_HOP.__getitem__, seeds=0)
    assert same == first and not off["applied"]


def test_text_retriever_bridge_arm_is_opt_in(tmp_path):
    encoder = FakeEncoder()
    build_corpus([TextDocument(key, text) for key, text in TWO_HOP.items()],
                 tmp_path, encoder=encoder, max_tokens=48)

    def run(seeds):
        retriever = load_retriever(tmp_path, encoder=encoder, config=RetrievalConfig(
            arms=("lexical",), bridge_seeds=seeds, enable_recovery=False))[0]
        result = retriever.retrieve(SearchRequest(QUESTION),
                                    authorize=lambda: set(retriever.children))
        sources = [retriever.children[cid]["source_id"] for cid in result["ranked_child_ids"]]
        arms = {a["arm"] for a in result["trace"]["passes"][0]["arms"]}
        return list(dict.fromkeys(sources)), arms

    off_sources, off_arms = run(0)
    on_sources, on_arms = run(1)
    assert "lexical_bridge" not in off_arms and "lexical_bridge" in on_arms
    assert on_sources[0] == off_sources[0] == "album"
    assert on_sources.index("band") < off_sources.index("band")
    with pytest.raises(ValueError, match="lexical arm"):
        RetrievalConfig(arms=("dense",), bridge_seeds=1)
    with pytest.raises(ValueError):
        RetrievalConfig(bridge_seeds=5)


def _chunk(cid, page, text):
    ref = {"source_sha256": "s", "document_version": "v", "page": page}
    return {"id": cid, "text": text, "references": [ref], "section_path": []}


def test_page_fusion_prefers_page_that_holds_all_cues():
    # Shape of TabFQuAD: a row label, a column header and a value are split
    # into separate OCR chunks of one table page.
    rows = [
        _chunk("a", 1, "Energy share energy share energy"),
        _chunk("b", 2, "Energy"),
        _chunk("c", 2, "2004 share"),
        _chunk("d", 2, "coal 41"),
    ]
    page_rows, page_of = _page_rows(rows)
    assert len(page_rows) == 2 and page_of["c"] == ["s\x1fv\x1f2"]
    query = "energy share 2004 coal"
    chunk_rank = FieldedBM25(rows).rank(query)
    page_rank = FieldedBM25(page_rows).rank(query)
    fused = _fuse_page_evidence(chunk_rank, page_rank, page_of)
    assert {cid for cid, _ in fused} == {cid for cid, _ in chunk_rank}
    assert page_rank[0][0].endswith("\x1f2")
    first_page = [r["page"] for cid, _ in fused for r in next(
        x for x in rows if x["id"] == cid)["references"]][0]
    assert first_page == 2


def test_local_index_rejects_invalid_switches(tmp_path):
    with pytest.raises(ValueError):
        LocalRagIndex(tmp_path / "x.sqlite3", page_fusion=1)


def test_text_retriever_section_arm_does_not_bury_strong_dense_lexical_match(tmp_path):
    """Reproduction of sgk_05 / sgk_06: section hits must not bury Dense#1+Lexical#1."""
    encoder = FakeEncoder()
    # 8 distractors whose section headers contain generic query words ("mệnh đề")
    # and appear verbatim in their bodies (dense + lexical top 2..9), while one target
    # chunk answers the rare named-entity question (dense#1 + lexical#1) in another section.
    sections = [
        "1. MỆNH ĐỀ",
        "2. MỆNH ĐỀ PHỦ ĐỊNH",
        "3. MỆNH ĐỀ KÉO THEO",
        "4. MỆNH ĐỀ ĐẢO",
        "5. MỆNH ĐỀ TƯƠNG ĐƯƠNG",
        "6. MỆNH ĐỀ CHỨA BIẾN",
        "7. MỆNH ĐỀ PHỦ ĐỊNH ĐÚNG",
        "8. MỆNH ĐỀ VÀ KÍ HIỆU",
    ]
    doc_text = "\n\n".join(
        f"## {sec}\n\nMệnh đề toán học {i} về phép suy luận và tính đúng sai trong chương {i}."
        for i, sec in enumerate(sections, 1)
    ) + (
        "\n\n## LỊCH SỬ LÔGIC\n\n"
        "Nhà toán học người Anh George Boole vào năm 1854 thảo luận lôgic mệnh đề trong cuốn sách The Laws of Think.\n"
    )
    query = "Nhà toán học người Anh nào thảo luận về lôgic mệnh đề năm 1854 và tên cuốn sách là gì?"
    build_corpus([TextDocument("sgk", doc_text)], tmp_path, encoder=encoder, max_tokens=64)

    heavy_section = load_retriever(
        tmp_path,
        encoder=encoder,
        config=RetrievalConfig(enable_recovery=False, section_fusion_weight=1.0),
    )[0]
    heavy_res = heavy_section.retrieve(SearchRequest(query), authorize=lambda: set(heavy_section.children))
    heavy_rank = next(
        idx for idx, cid in enumerate(heavy_res["ranked_child_ids"], 1)
        if "George Boole" in heavy_section.children[cid]["text"]
    )
    assert heavy_rank > 2  # reproduced bug when section weight is 1.0

    default_ret = load_retriever(
        tmp_path, encoder=encoder, config=RetrievalConfig(enable_recovery=False)
    )[0]
    assert default_ret.config.section_fusion_weight == 0.02
    result = default_ret.retrieve(SearchRequest(query), authorize=lambda: set(default_ret.children))
    top1_text = default_ret.children[result["ranked_child_ids"][0]]["text"]
    assert "George Boole" in top1_text and "1854" in top1_text, top1_text

    with pytest.raises(ValueError, match="section_fusion_weight"):
        RetrievalConfig(section_fusion_weight=0)
    with pytest.raises(ValueError, match="section_fusion_weight"):
        RetrievalConfig(section_fusion_weight=11.0)

    with pytest.raises(ValueError):
        LocalRagIndex(tmp_path / "x.sqlite3", bridge_seeds=9)
