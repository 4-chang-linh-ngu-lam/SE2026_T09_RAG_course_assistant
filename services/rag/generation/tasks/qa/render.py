"""Render validated answers for display, and mask revoked sources in history.

The model only ever emits ``S{i}`` ids and exact quotes. Document names and
page/slide/section locations come from the service's ``locate`` callback, which
maps immutable source spans to the document version the class may read (C2).
History is re-checked against current grants at read time (H4).
"""
from __future__ import annotations

GENERAL_LABEL = "Kiến thức chung (không trích từ tài liệu lớp)"
STATUS_NOTICE = {
    "answered": None,
    "partially_answered": "Tài liệu của lớp chỉ trả lời được một phần câu hỏi.",
    "insufficient_evidence": "Tài liệu của lớp không có đủ căn cứ để trả lời câu hỏi này.",
}


def render_answer(answer: dict, locate) -> dict:
    """``locate(source_id, source_spans) -> dict | None`` supplies document and page.

    A citation whose location cannot be resolved keeps its quote but gets
    ``location: None``; the UI must not invent a page for it.
    """
    claims = []
    for claim in answer["claims"]:
        rendered = {"text": claim["text"], "basis": claim["basis"], "citations": []}
        if claim["basis"] == "general":
            rendered["label"] = GENERAL_LABEL
        for cite in claim["evidence"]:
            rendered["citations"].append({"source_id": cite["source_id"], "quote": cite["quote"],
                                          "source_spans": cite["source_spans"],
                                          "location": locate(cite["source_id"], cite["source_spans"])})
        claims.append(rendered)
    return {"status": answer["status"], "notice": STATUS_NOTICE[answer["status"]],
            "claims": claims, "missing_parts": list(answer.get("missing_parts", []))}


def mask_revoked(rendered: dict, allowed_source_ids) -> dict:
    """Hide quotes and locations from sources the reader can no longer access.

    Claim text written in the conversation itself is kept; whether it should
    also be hidden is an open product decision (architecture §4.5).
    """
    allowed = set(allowed_source_ids)
    out = {**rendered, "claims": []}
    for claim in rendered["claims"]:
        citations = []
        for cite in claim["citations"]:
            if cite["source_id"] in allowed:
                citations.append(cite)
            else:
                citations.append({"masked": True, "reason": "source_access_revoked"})
        out["claims"].append({**claim, "citations": citations})
    return out
