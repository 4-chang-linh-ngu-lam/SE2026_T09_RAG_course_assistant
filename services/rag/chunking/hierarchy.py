"""Section tree for structured text; independent of OCR/ingestion output."""
from __future__ import annotations

HIERARCHY_VERSION = "idp-text-hierarchy-1"


def build_hierarchy(blocks: list[dict], document_id: str) -> tuple[list[dict], dict[str, str]]:
    root = {"id": f"section_{document_id}_root", "parent_id": None,
        "title": "", "path": [], "level": 0, "child_ids": [], "basis": "document"}
    nodes, stack, assignments = [root], [root], {}
    for block in blocks:
        if block["kind"] == "heading":
            level = block["heading_level"]
            while stack[-1]["level"] >= level:
                stack.pop()
            parent = stack[-1]
            node = {"id": f"section_{document_id}_{block['id']}",
                "parent_id": parent["id"], "title": block["title"],
                "path": parent["path"] + [block["title"]], "level": level,
                "child_ids": [], "basis": "explicit_text_heading",
                "source_start": block["source_start"], "source_end": block["source_end"],
                "source_text": block["text"], "block_id": block["id"]}
            parent["child_ids"].append(node["id"])
            nodes.append(node)
            stack.append(node)
        assignments[block["id"]] = stack[-1]["id"]
    return nodes, assignments
