"""Map accepted evidence quotes back to immutable source spans."""
from __future__ import annotations


def quote_spans(evidence, quote):
    text, item = evidence["text"], evidence["record"]
    start = text.find(quote)
    if start < 0:
        raise ValueError("citation_quote_not_in_evidence")
    end, covered, mapped = start + len(quote), 0, []
    for span in item["source_spans"]:
        a, b = max(start, span["start"]), min(end, span["end"])
        if a < b:
            source_start = span["source_start"] + a - span["start"]
            mapped.append({"source_id": item["source_id"], "start": source_start,
                           "end": source_start + b - a})
            covered += sum(not ch.isspace() for ch in text[a:b])
    if not mapped or covered != sum(not ch.isspace() for ch in quote):
        raise ValueError("citation_quote_lacks_source_mapping")
    return mapped
