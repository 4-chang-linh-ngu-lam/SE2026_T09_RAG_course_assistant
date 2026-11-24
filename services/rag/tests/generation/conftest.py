"""Offline fixtures for the generation engine: no model, no network.

The engine package uses relative imports rooted at ``services/rag`` as the
``rag`` namespace package, so ``services`` must be importable.
"""
import json
import sys
from pathlib import Path

import pytest

SERVICES = Path(__file__).resolve().parents[3]
if str(SERVICES) not in sys.path:
    sys.path.insert(0, str(SERVICES))


class FakeGenerator:
    """Scripted stand-in for ``LlamaGenerator``.

    ``responder(task, payload, schema, call)`` returns a dict (serialised to JSON),
    a raw string, or a ``(text, finish_reason)`` tuple. ``task`` comes from the
    ``"task"`` field every engine prompt carries in its user payload.
    """

    context_tokens = 4096
    identity = {"model_sha256": "f" * 64, "build_info": "fake-build"}

    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def count_messages(self, messages):
        return sum(len(m["content"]) for m in messages) // 4 + 16

    def generate(self, messages, schema, *, profile, max_new_tokens, seed):
        payload = json.loads(messages[-1]["content"])
        call = {"task": payload.get("task"), "payload": payload, "schema": schema,
                "profile": profile.name, "max_new_tokens": max_new_tokens, "seed": seed,
                "system": messages[0]["content"]}
        self.calls.append(call)
        out = self.responder(call["task"], payload, schema, call)
        finish = "stop"
        if isinstance(out, tuple):
            out, finish = out
        text = out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)
        return {"text": text, "finish_reason": finish,
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}, "seconds": 0.01}


def make_record(text, *, source_id="doc-v1", section_path=("Chương 1", "Bài 1"), offset=0,
                record_id="r1", warnings=None):
    record = {"id": record_id, "source_id": source_id, "section_path": list(section_path), "text": text,
              "source_spans": [{"start": 0, "end": len(text), "source_start": offset,
                                "source_end": offset + len(text), "block_id": f"b-{record_id}",
                                "section_id": "s1"}]}
    if warnings:
        record["source_quality_warnings"] = list(warnings)
    return record


@pytest.fixture
def fake_generator():
    return FakeGenerator


@pytest.fixture
def record():
    return make_record
