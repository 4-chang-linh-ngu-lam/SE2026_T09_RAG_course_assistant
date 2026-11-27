import json

from idp.canonical import build_canonical
from rag.retrieval.canonical_harness import LocalRagIndex, resolve_citation


def test_legacy_index_requires_publication_and_current_access(tmp_path):
    def page(number, text, review=None):
        return {
            "page_id": number,
            "page_size": [300, 400],
            "processing_status": "ok",
            "review": review or [],
            "blocks": [{
                "block_id": f"b{number}", "block_type": "Text",
                "bbox": [10, 10, 200, 30], "text": text, "source": "pymupdf",
            }],
        }

    doc = build_canonical(
        [
            page(1, "Approved cobalt evidence."),
            page(2, "Unreviewed garnet evidence.", [
                {"code": "PAGE_TEXT_LAYER_UNUSABLE", "severity": "warning"},
            ]),
        ],
        "fixture.pdf", "a" * 64, "test", expected_pages=[1, 2],
        source_metadata={"document_version": "revision-2"},
    )
    doc = json.loads(json.dumps(doc))
    trust = ("pymupdf",)
    index = LocalRagIndex(tmp_path / "legacy.sqlite3")
    assert index.index(doc) == 0
    assert index.index(doc, trusted_parsers=trust) == 1
    allow = lambda actor, sha, version: (actor, sha, version) == ("student", "a" * 64, "revision-2")
    assert index.retrieve("garnet", actor="student", access_check=allow) == []
    assert index.retrieve("cobalt", actor="outsider", access_check=allow) == []
    hit, = index.retrieve("cobalt", actor="student", access_check=allow)
    citation, = resolve_citation(hit, doc, trusted_parsers=trust)
    assert citation["text"] == "Approved cobalt evidence."
    assert citation["page"] == 1 and citation["bbox"] == [10, 10, 200, 30]
    assert citation["region_id"] is None and citation["evidence_refs"] == []
    # Republishing with stricter trust clears the previous rows for this version.
    assert index.index(doc) == 0
    assert index.retrieve("cobalt", actor="student", access_check=allow) == []


def test_digital_page_summary_keeps_block_flag_owner():
    from idp.backends.native import pdf as digital

    flag = {"code": "TEXT_ENCODING_REVIEW", "severity": "warning"}
    block = digital._block("p0001_b000", "Text", [10, 10, 200, 30], "x", "x", review_flags=[flag])
    page = digital._page(1, [block], [300, 400])
    assert page["review"] == [{**flag, "block_id": "p0001_b000"}]
    assert "block_id" not in block["review_flags"][0]
    page.update(page_id=1, blocks=[{**block, "source": "pymupdf"}])
    doc = build_canonical([page], "fixture.pdf", "a" * 64, "test", expected_pages=[1])
    # The finding stays on its block; it is not duplicated as a page-scoped flag.
    assert doc["pages"][0]["review"] == []
    assert doc["pages"][0]["blocks"][0]["review_flags"] == [flag]


def _windowed_doc():
    def page(number, blocks):
        return {
            "page_id": number, "page_size": [300, 400], "processing_status": "ok",
            "review": [],
            "blocks": [
                {"block_id": f"p{number}_b{i}", "block_type": kind, "bbox": [10, 10 + 30 * i, 200, 30 + 30 * i],
                 "text": text, "source": "pymupdf", "section_path": path,
                 "review_flags": flags}
                for i, (kind, text, path, flags) in enumerate(blocks)
            ],
        }

    running = ("Text", "1.3. Running chapter head\n{}", [], [])
    formula = [{"code": "FORMULA_TEXT_LAYER_UNVERIFIED", "severity": "warning"}]
    pages = [
        page(n, [
            (running[0], running[1].format(n), [], []),
            ("SectionHeader", "Opening", ["Opening"], []),
            ("Text", f"Prose about cobalt on page {n}.", ["Opening"], []),
            ("Equation", "N(t) = N0 e-kt", ["Opening"], formula),
            ("Text", f"Garnet follows the formula {n}.", ["Opening"], []),
        ])
        for n in (1, 2, 3)
    ]
    doc = build_canonical(pages, "fixture.pdf", "b" * 64, "test", expected_pages=[1, 2, 3])
    return json.loads(json.dumps(doc))


def test_paragraph_windows_skip_running_heads_and_held_blocks():
    from rag.retrieval.canonical_harness import build_chunks

    from idp.canonical import audit_canonical

    doc = _windowed_doc()
    trust = ("pymupdf",)
    # The legacy page policy holds every page for one formula finding.
    strict = audit_canonical(doc, trusted_parsers=set(trust), policy="page")
    assert strict["quality"]["auto_publish_pages"] == []
    # Default block policy: one chunk per block, only the formula is held.
    chunks = build_chunks(doc, trusted_parsers=trust)
    assert len(chunks) == 12  # 4 retrievable blocks x 3 pages
    assert not any("N0" in c["text"] for c in chunks)
    windows = build_chunks(doc, trusted_parsers=trust, paragraph_windows=True)
    by_page = {}
    for chunk in windows:
        cited = [r["block_id"] for r in chunk["references"]]
        by_page.setdefault(chunk["references"][0]["page"], []).append(cited)
        assert "Running chapter head" not in chunk["text"]
        assert "N0" not in chunk["text"]
        assert chunk["section_path"] == ["Opening"]
    # Running head dropped, heading kept with its prose, and the held formula
    # splits the window: b2 and b4 are never joined as if adjacent.
    assert by_page == {p: [[f"p{p}_b1", f"p{p}_b2"], [f"p{p}_b4"]] for p in (1, 2, 3)}


def test_paragraph_windows_keep_block_citations(tmp_path):
    doc = _windowed_doc()
    trust = ("pymupdf",)
    scoped = {"FORMULA_TEXT_LAYER_UNVERIFIED"}
    index = LocalRagIndex(tmp_path / "w.sqlite3", paragraph_windows=True)
    # Two windows per page: the held formula between them is a gap.
    assert index.index(doc, trusted_parsers=trust, block_scoped_codes=scoped) == 6
    allow = lambda actor, sha, version: actor == "student"
    hit = index.retrieve("garnet formula", actor="student", access_check=allow)[0]
    cites = resolve_citation(hit, doc, trusted_parsers=trust, block_scoped_codes=scoped)
    assert cites[-1]["text"].startswith("Garnet follows the formula")


def test_text_layer_fragment_flags_formula_shards_not_prose():
    from idp.backends.native.pdf import _text_layer_fragment

    for shard in ("Z x", "y′", "dI(t)", "2N0e−kt.", "k .", "S\nk\n−−−→I ."):
        assert _text_layer_fragment(shard), shard
    for prose in ("Mở đầu", "Ví dụ 3.3.6.", "Chứng minh.", "Hình 1.5: Hệ ba lò xo", ""):
        assert not _text_layer_fragment(prose), prose
    assert not _text_layer_fragment("x " * 40)  # long lines are not shards


def test_running_line_entries_need_repetition_at_page_edges():
    from idp.backends.native.pdf import _running_line_entries

    def page(index, first, body, last):
        return {"index": index, "entries": [
            {"kind": "text", "text": first},
            {"kind": "image"},
            {"kind": "text", "text": body},
            {"kind": "text", "text": last},
        ]}

    pages = [
        page(0, "1.3. Chapter head\n9", "Body one.", "Closing one."),
        page(1, "1.3. Chapter head\n11", "1.3. Chapter head", "12"),
        page(2, "13 1.3. Chapter head", "Body three.", "Closing three."),
        page(3, "Unique opening", "Body four.", "Closing four."),
        page(4, "Chương 1", "Body five.", "Closing five."),
        page(5, "Chương 2", "Body six.", "Closing six."),
        page(6, "Chương 3", "Body seven.", "Closing seven."),
    ]
    # Heads recur at an edge on three pages; a bare number is a page number.
    # The same text in the body (page 1, entry 2) is not an edge line, and
    # chapter headings that differ only by number are not running heads.
    assert _running_line_entries(pages) == {(0, 0), (1, 0), (1, 3), (2, 0)}
    assert _running_line_entries(pages[:2]) == {(1, 3)}


def test_block_policy_holds_findings_where_they_are():
    from idp.canonical import audit_canonical

    def ocr(block_id, text, conf, flags=(), btype="Text"):
        return {"block_id": block_id, "block_type": btype, "bbox": [10, 10, 200, 30], "text": text,
                "source": "tesseract_fallback", "confidence": conf,
                "review_flags": [{"code": c, "severity": "warning" if c != "OCR_DUAL_READ_AGREED" else "info"}
                                 for c in flags]}

    def page(number, blocks, review=(), watermark=None):
        result = {"page_id": number, "page_size": [300, 400], "processing_status": "ok",
                  "review": [{"code": c, "severity": "warning"} for c in review], "blocks": blocks}
        if watermark:
            result["watermark_candidates"] = watermark
        return result

    pages = [
        # Lane/heuristic page codes are advisory; a low score holds one block.
        page(1, [ocr("a", "Clean prose line.", 0.91), ocr("b", "noise", 0.20, ["LOW_CONFIDENCE"])],
             review=["FALLBACK_ENGINE_REVIEW", "QUESTION_ORPHAN_OPTIONS"]),
        # Dual-read agreement authorizes a block below the score threshold
        # and supersedes its LOW_CONFIDENCE finding.
        page(2, [ocr("c", "Agreed line.", 0.40, ["LOW_CONFIDENCE", "OCR_DUAL_READ_AGREED"])]),
        # An unknown page-level code still fails closed.
        page(3, [ocr("d", "Prose.", 0.95)], review=["SOMETHING_NEW_REVIEW"]),
        # A picture finding never gates text; a watermark token is held alone.
        page(4, [ocr("e", "Prose.", 0.95), ocr("f", "", None, ["FIGURE_NO_CAPTION"], "Picture"),
                 ocr("g", "R", 0.99)], review=["WATERMARK_CANDIDATE_REVIEW"], watermark=["R"]),
    ]
    doc = build_canonical(pages, "f.pdf", "c" * 64, "t", expected_pages=[1, 2, 3, 4])
    quality = audit_canonical(doc)["quality"]
    assert quality["auto_publish_pages"] == [1, 2, 4]
    assert quality["held_blocks"] == ["b", "g"]
    reasons = {i["page_id"]: i["hold_reasons"] for i in quality["page_quality"]}
    assert reasons[1] == {"b": ["LOW_CONFIDENCE", "UNVERIFIED_SOURCE"]}
    assert reasons[4] == {"g": ["WATERMARK_CANDIDATE_TOKEN"]}
    assert quality["page_quality"][2]["page_gating_codes"] == ["SOMETHING_NEW_REVIEW"]
    # Certification keeps the strict page gate.
    assert audit_canonical(doc)["production_pass"] is False
    assert audit_canonical(doc, policy="page")["quality"]["auto_publish_pages"] == []


def test_dual_read_disagreement_holds_block_even_above_threshold():
    from idp.canonical import audit_canonical

    def ocr(block_id, text, conf, flags=()):
        return {"block_id": block_id, "block_type": "Text", "bbox": [10, 10, 200, 30], "text": text,
                "source": "tesseract_fallback", "confidence": conf,
                "review_flags": [{"code": c, "severity": "warning"} for c in flags]}

    # Primary reader scores 0.955 (above LOW_CONFIDENCE) but the second reader
    # disagreed: the block must be held, not auto-published as "scored".
    page = {"page_id": 1, "page_size": [300, 400], "processing_status": "ok", "review": [],
            "blocks": [ocr("x", "Tồn tại", 0.955, ["OCR_DUAL_READ_DISAGREE"]),
                       ocr("y", "Ổn định.", 0.955, ["OCR_DUAL_READ_FAILED"]),
                       ocr("z", "Đúng.", 0.955)]}
    doc = build_canonical([page], "f.pdf", "c" * 64, "t", expected_pages=[1])
    quality = audit_canonical(doc)["quality"]
    assert quality["held_blocks"] == ["x", "y"]
    reasons = quality["page_quality"][0]["hold_reasons"]
    assert reasons == {"x": ["OCR_DUAL_READ_DISAGREE"], "y": ["OCR_DUAL_READ_FAILED"]}
    assert quality["auto_publish_pages"] == [1]
