"""Map accepted evidence quotes back to immutable source spans."""
from __future__ import annotations


def quote_spans(evidence, quote):
    text, item = evidence["text"], evidence["record"]
    if not isinstance(quote, str) or not quote.strip() or quote not in text:
        raise ValueError("citation_quote_not_in_evidence")
    spans = item.get("source_spans")
    if not isinstance(spans, (list, tuple)) or not isinstance(item.get("source_id"), str) or not item["source_id"]:
        raise ValueError("invalid_evidence_source_spans")
    previous_end = 0
    for span in spans:
        a, b, sa, sb = (span.get(k) if isinstance(span, dict) else None
                        for k in ("start", "end", "source_start", "source_end"))
        if (any(type(v) is not int for v in (a, b, sa, sb))
                or not previous_end <= a < b <= len(text) or not 0 <= sa < sb or b - a != sb - sa):
            raise ValueError("invalid_evidence_source_spans")
        previous_end = b

    # A synthetic or partial first occurrence must not hide a later real one.
    start = text.find(quote)
    while start >= 0:
        end, cursor, mapped = start + len(quote), start, []
        for span in spans:
            a, b = max(start, span["start"]), min(end, span["end"])
            if a >= b:
                continue
            if text[cursor:a].strip():
                break
            source_start = span["source_start"] + a - span["start"]
            entry = {"source_id": item["source_id"], "start": source_start,
                     "end": source_start + b - a}
            if isinstance(span.get("page"), int) and span["page"] >= 1:
                entry["page"] = span["page"]
            mapped.append(entry)
            cursor = b
        else:
            if mapped and not text[cursor:end].strip():
                return mapped
        start = text.find(quote, start + 1)
    raise ValueError("citation_quote_lacks_source_mapping")
