"""Offline source-region and lexical-retrieval diagnostics on saved chunk text.

No OCR calls, model judges, service indexing or authorization decisions. Geometry
selects source blocks; prediction wording never selects the best-matching region.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import math
import re

from .evaluate import _evaluation_text, _lev, _words

REGION_EVAL_VERSION = "idp-region-eval-3"
TEXT_KINDS = {"Text", "SectionHeader", "Caption", "Code", "Equation", "Formula", "ListItem", "ListGroup"}


def _box(value):
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in value)
            or value[0] >= value[2] or value[1] >= value[3]):
        raise ValueError("invalid region geometry")
    return value


def region_export(page, chunks, bbox, *, source_size=None, eligible_only=False, include_visual=False, selection="center", include_supplements=False):
    if selection not in {"center", "overlap"}:
        raise ValueError("invalid region selection")
    bbox = list(_box(bbox))
    if source_size is not None:
        if (len(source_size) != 2 or any(type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in source_size)):
            raise ValueError("invalid region source size")
        pw, ph = page["page_size"]
        bbox = [bbox[0]*pw/source_size[0], bbox[1]*ph/source_size[1], bbox[2]*pw/source_size[0], bbox[3]*ph/source_size[1]]
    parts, ids, missing, ambiguous, references = [], [], [], [], []
    for block in page["blocks"]:
        evidence=block.get("source_evidence") or {}
        if not include_supplements and (evidence.get("inline_formula_supplement") or evidence.get("reading_role") == "contextual_alternative"):
            continue
        if block.get("excluded_from_content") or (not include_visual and block.get("block_type") not in TEXT_KINDS):
            continue
        if not block.get("bbox"):
            continue
        b = _box(block["bbox"])
        inter = max(0, min(b[2],bbox[2])-max(b[0],bbox[0])) * max(0, min(b[3],bbox[3])-max(b[1],bbox[1]))
        block_area = (b[2]-b[0])*(b[3]-b[1])
        region_area = (bbox[2]-bbox[0])*(bbox[3]-bbox[1])
        selected = (bbox[0] <= (b[0]+b[2])/2 <= bbox[2] and bbox[1] <= (b[1]+b[3])/2 <= bbox[3]) if selection == "center" else inter / min(block_area, region_area) >= .5
        # A containing block can have its center outside a partial annotation.
        # Report that mismatch even when it is not selected for transcription.
        if inter / min(block_area, region_area) >= .5 and inter / block_area < .8:
            ambiguous.append(block["block_id"])
        if not selected:
            continue
        bid = block["block_id"]
        ids.append(bid)
        if inter / block_area < .8 and bid not in ambiguous:
            ambiguous.append(bid)
        found = []
        for chunk in chunks:
            if eligible_only and not chunk.get("publishable"):
                continue
            if bid not in chunk.get("block_ids", []) or page["page_id"] not in chunk.get("pages", []):
                continue
            for span in chunk.get("source_spans", []):
                if span.get("block_id") != bid or span.get("page") != page["page_id"]:
                    continue
                start, end = span.get("start"), span.get("end")
                if type(start) is not int or type(end) is not int or not 0 <= start <= end <= len(chunk["text"]):
                    raise ValueError("invalid exported source span")
                text = chunk["text"][start:end]
                if hashlib.sha256(text.encode("utf-8")).hexdigest() != span.get("text_sha256"):
                    raise ValueError("stale exported source span")
                found.append(text)
                references.append({"chunk_id": chunk["id"], "block_id": bid, "page": page["page_id"], "start": start, "end": end})
        if not found:
            missing.append(bid)
        parts.extend(found)
    text = "\n".join(parts)
    if len(text) > 32768:
        raise ValueError("region export exceeds evaluation size limit")
    return {"text": text, "source_block_ids": ids, "missing_export_blocks": missing,
        "boundary_ambiguous_blocks": ambiguous, "references": references, "bbox": bbox,
        "eligible_only": eligible_only, "has_prediction": bool(text.strip()), "selection": selection,
        "ocr_alignment_qualified": selection == "center" and not ambiguous,
        "scope": "exported_region_text_not_fine_grained_spatial_association"}


def text_metrics(prediction, gold):
    p, g = _evaluation_text(prediction), _evaluation_text(gold)
    if not g or len(g) > 8192 or len(p) > 32768:
        raise ValueError("empty or oversized region gold/prediction")
    gp, pp = _words(g), _words(p)
    char_edits, word_edits = _lev(p, g), _lev(pp, gp)
    return {"char_edits": char_edits, "gold_chars": len(g), "cer": char_edits/len(g),
        "word_edits": word_edits, "gold_words": len(gp), "wer": word_edits/len(gp), "exact": p == g}


def scientific_present(text, alternatives):
    """Predeclared literal/representation variants, not algebraic equivalence.

    Only layout whitespace and explicit LaTeX spacing tokens vary. Signs, unit
    letters, exponent digits/braces and case stay literal. Numeric/unit token
    boundaries prevent a short correct-looking substring hiding a wrong value.
    """
    text = re.sub(r"\\[,;:! ]|~", " ", _evaluation_text(text))
    if not alternatives or any(not isinstance(s, str) or not s.strip() or len(s) > 256 for s in alternatives):
        raise ValueError("invalid scientific alternatives")
    for alternative in alternatives:
        value = re.sub(r"\\[,;:! ]|~", " ", _evaluation_text(alternative))
        pattern = r"(?<!\w)" + r"\s*".join(re.escape(c) for c in value if not c.isspace()) + r"(?!\w|\.\d|\s*\^)"
        if re.search(pattern, text):
            return True
    return False


def _terms(text):
    return re.findall(r"\w+", _evaluation_text(text).casefold(), re.UNICODE)


class LexicalIndex:
    """Fixed BM25 baseline for ingestion diagnostics, not the AI-service index."""
    def __init__(self, documents):
        self.documents = list(documents)
        self.tokens = [Counter(_terms(d["text"])) for d in self.documents]
        self.lengths = [sum(t.values()) for t in self.tokens]
        self.average = sum(self.lengths)/max(1,len(self.lengths))
        self.df = Counter(t for row in self.tokens for t in row)

    def search(self, query, k=3):
        if type(k) is not int or k < 1:
            raise ValueError("invalid lexical top-k")
        terms, n = set(_terms(query)), len(self.documents)
        ranked = []
        for index, frequencies in enumerate(self.tokens):
            score = 0.0
            for token in terms:
                tf = frequencies[token]
                if tf:
                    df = self.df[token]
                    idf = math.log(1+(n-df+.5)/(df+.5))
                    score += idf*tf*2.2/(tf+1.2*(.25+.75*self.lengths[index]/max(1,self.average)))
            if score > 0:
                ranked.append((index,score))
        ranked.sort(key=lambda row:(-row[1],row[0]))
        return [{**self.documents[i], "score": score} for i,score in ranked[:k]]


def retrieval_diagnostic(index, *, query, source_id, source_block_ids, required_evidence, k=3):
    if not required_evidence or not all(isinstance(s,str) and s.strip() for s in required_evidence):
        raise ValueError("retrieval evidence must be declared before ranking")
    hits = index.search(query,k)
    relevant = [h for h in hits if h.get("source_id") == source_id and set(h.get("block_ids",[])) & set(source_block_ids)]
    evidence_text = _evaluation_text("\n".join(h["text"] for h in relevant))
    evidence = [s for s in required_evidence if _evaluation_text(s) in evidence_text]
    return {"k": k, "source_hit": bool(relevant), "all_required_evidence": len(evidence)==len(required_evidence),
        "required_evidence_found": len(evidence), "required_evidence_total": len(required_evidence),
        "hits": [{"id":h["id"], "source_id":h.get("source_id"), "score":h["score"]} for h in hits],
        "scope":"offline_lexical_source_and_literal_evidence_not_answer_accuracy_or_authorization"}
