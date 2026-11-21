"""Source-declared shared reading dependencies; no subject/query classifier."""
from __future__ import annotations

import re
import unicodedata

RELATIONS_VERSION = "idp-chunk-relations-1"
_READ = re.compile(r"^(?:>[ \t]*)*(?:đọc\s+(?:kĩ\s+)?(?:đoạn\s+(?:văn|trích)|văn bản|bài thơ|ngữ liệu)\s+(?:sau|dưới đây)|read\s+the\s+following\s+(?:passage|text|poem))\b", re.I)


def shared_passages(parents, nodes):
    """Link explicitly introduced prose to subsequent tasks in its heading scope.

    A new prose unit after tasks or leaving the original section closes the
    group. No links are guessed from a pronoun alone or a subject/book title.
    """
    tree = {n["id"]: n for n in nodes}

    def inside(section, owner):
        while section:
            if section == owner:
                return True
            section = tree[section]["parent_id"]
        return False

    active, owner, questions, output = [], None, False, {}
    for parent in parents:
        if active and not inside(parent["section_id"], owner):
            active, owner, questions = [], None, False
        value = unicodedata.normalize("NFC", parent["text"].lstrip())
        if parent["unit_kind"] in {"prose", "callout"} and _READ.match(value):
            active, owner, questions = [parent], parent["section_id"], False
        elif active and parent["unit_kind"] == "exercise":
            output[parent["id"]] = [p["id"] for p in active]
            questions = True
        elif active and not questions:
            active.append(parent)
        elif active:
            active, owner, questions = [], None, False
    return output


def child_refs(parent, start, *, shared, parents, table):
    refs = []
    if table and table["valid"] and table["columns"] > 1 and start >= table["header_end"]:
        refs.append({"parent_id": parent["id"], "start": 0, "end": table["header_end"],
                     "role": "table_header", "index": True})
    for pid in shared.get(parent["id"], []):
        refs.append({"parent_id": pid, "start": 0, "end": len(parents[pid]["text"]),
                     "role": "shared_passage", "index": False})
    return refs
