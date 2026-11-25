"""Bounded lexical/date recovery for the opt-in Vietnamese MRC path.

This stage only searches source texts the caller has already authorized.  It
does not invent facts, call a generator, or bypass the normal source-span
contract.  Recovery is attempted only after the primary MRC reader abstains.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence


MRC_RECOVERY_VERSION = "idp-vi-mrc-recovery-1"
_STOP = set("là gì nào tại của đã đang như thế những ở một vào trong có cho được từ sau vì sao mà thì các và với".split())
_YEAR = re.compile(r"\b(?:1[0-9]{3}|20[0-9]{2})\b")
_RELATIVE = re.compile(r"\b(một|hai|ba|bốn|năm|sáu|bảy|tám|chín|mười|\d{1,2}) năm sau\b", re.I)
_VALUES = dict(zip("một hai ba bốn năm sáu bảy tám chín mười".split(), range(1, 11)))


def _terms(text: str) -> list[str]:
    return re.findall(r"\w+", text.casefold(), flags=re.UNICODE)


def _dates(text: str) -> tuple[set[int], set[int]]:
    entries = sorted(
        [(match.start(), int(match[0]), False) for match in _YEAR.finditer(text)]
        + [
            (match.start(), int(match[1]) if match[1].isdigit() else _VALUES[match[1].casefold()], True)
            for match in _RELATIVE.finditer(text)
        ]
    )
    mentioned, derived, anchor = set(), set(), None
    for _, value, relative in entries:
        if relative and anchor is not None:
            derived.add(anchor + value)
        if not relative:
            anchor = value
            mentioned.add(value)
    return mentioned, derived


def _query_features(question: str) -> tuple[list[str], set[int], set[tuple[int, str]]]:
    years = {int(match[0]) for match in _YEAR.finditer(question)}
    words = [word for word in _terms(question) if word not in _STOP]
    centuries = (
        "", "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi",
        "xii", "xiii", "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi",
    )
    decades = set()
    if "thập niên" in question.casefold():
        for year in years:
            century = (year - 1) // 100 + 1
            if 0 < century < len(centuries):
                decades.add((year % 100, centuries[century]))
    return words, years, decades


class LexicalDateRecovery:
    """Recover omitted source passages without widening the authorization scope."""

    def __init__(self, sources: Mapping[str, str], *, limit: int = 3, margin_floor: float = 0.0):
        if not isinstance(sources, Mapping) or any(
            not isinstance(key, str) or not key or not isinstance(value, str)
            for key, value in sources.items()
        ):
            raise ValueError("MRC recovery requires source_id to text mapping")
        if type(limit) is not int or not 1 <= limit <= 10:
            raise ValueError("MRC recovery limit must be in 1..10")
        if type(margin_floor) not in (int, float) or not math.isfinite(float(margin_floor)):
            raise ValueError("MRC recovery margin floor must be finite")
        self.sources = dict(sources)
        self.limit = limit
        self.margin_floor = float(margin_floor)
        doc_frequency = Counter()
        self._docs = {}
        for source_id, text in self.sources.items():
            counts = Counter(_terms(text))
            doc_frequency.update(counts.keys())
            mentioned, derived = _dates(text)
            self._docs[source_id] = {
                "text": text,
                "counts": counts,
                "mentioned": mentioned,
                "derived": derived,
            }
        total = len(self._docs)
        self._idf = {
            term: math.log1p((total - count + 0.5) / (count + 0.5))
            for term, count in doc_frequency.items()
        }
        self.identity = {
            "version": MRC_RECOVERY_VERSION,
            "source_count": total,
            "limit": limit,
            "margin_floor": self.margin_floor,
        }

    def rank_sources(
        self,
        question: str,
        *,
        original_source_ids: Sequence[str],
        eligible_source_ids: Sequence[str],
    ) -> list[str]:
        words, years, decades = _query_features(question)
        original = set(original_source_ids)
        titles = {}
        scored = []
        for source_id in eligible_source_ids:
            if source_id in original or source_id not in self._docs:
                continue
            doc = self._docs[source_id]
            counts = doc["counts"]
            lexical = sum(
                self._idf.get(word, 0.0) * counts[word] / (counts[word] + 1.0)
                for word in set(words)
                if counts[word]
            )
            decade_bonus = 0
            for value, century in decades:
                if re.search(rf"thập niên\s+{value}\b[^.]*thế kỷ\s+{century}\b", doc["text"], re.I):
                    decade_bonus = 8
            date_score = 4 * len(years & doc["mentioned"]) + 7 * len(years & doc["derived"])
            title_score = 2 / math.sqrt(titles[source_id]) if source_id in titles else 0
            scored.append((lexical + date_score + decade_bonus + title_score, source_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [source_id for _, source_id in scored[: self.limit]]

    def evidence(self, source_ids: Sequence[str]) -> list[dict]:
        records = []
        for index, source_id in enumerate(source_ids, 1):
            text = self.sources.get(source_id)
            if text is None:
                continue
            records.append({
                "id": f"R{index}",
                "source_id": source_id,
                "section_path": [],
                "text": text,
                "record": {
                    "source_id": source_id,
                    "text": text,
                    "source_spans": [{"start": 0, "end": len(text),
                                      "source_start": 0, "source_end": len(text)}],
                },
            })
        return records


def relative_event_candidate(question: str, reader_result: Mapping,
                             evidence: Sequence[Mapping]) -> dict | None:
    """Accept a strong span attached to a local explicit relative-year fact."""
    if not re.match(r"\s*(vào\s+)?năm\s+\d{4}\b", question, re.I) or "thập niên" in question.casefold():
        return None
    years = _YEAR.findall(question)
    if len(years) != 1:
        return None
    target = int(years[0])
    candidates = reader_result.get("candidates", []) if isinstance(reader_result, Mapping) else []
    source_by_id = {item.get("id"): item for item in evidence if isinstance(item, Mapping)}
    matches = {}
    for candidate in candidates[:3]:
        if not isinstance(candidate, Mapping) or candidate.get("null_margin", -math.inf) < 15:
            continue
        item = source_by_id.get(candidate.get("source"))
        answer, start, end = candidate.get("answer"), candidate.get("start"), candidate.get("end")
        if item is None or not isinstance(answer, str) or not isinstance(start, int) or not isinstance(end, int):
            continue
        text = item.get("text", "")
        if not isinstance(text, str) or text[start:end] != answer:
            continue
        sentence_start = max(text.rfind(mark, 0, start) for mark in ".!?\n") + 1
        relations = list(_RELATIVE.finditer(text, sentence_start, start))
        if len(relations) != 1:
            continue
        relation = relations[0]
        if not re.fullmatch(r"[\s,:;\-–—]*", text[relation.end():start]):
            continue
        previous = list(_YEAR.finditer(text, max(0, relation.start() - 600), relation.start()))
        if not previous:
            continue
        number = relation[1].casefold()
        offset = int(number) if number.isdigit() else _VALUES[number]
        if int(previous[-1][0]) + offset != target:
            continue
        matches.setdefault(" ".join(answer.casefold().split()), candidate)
    if not matches:
        return None
    longest = max(matches, key=len)
    if any(not (other in longest or longest in other) for other in matches):
        return None
    return matches[longest]
