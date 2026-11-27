"""Offline unit tests for tools/eval_rag_qas06.py."""

import json
from typing import ClassVar

from rag.generation.pipeline import GroundedTaskPipeline

from tools.eval_rag_qas06 import build_canonical_retriever, run_evaluation


class _MockGenerator:
    context_tokens = 4096
    output_ceiling = 768
    identity: ClassVar[dict[str, str]] = {"adapter": "mock-eval"}

    def __init__(self, responses: list[str]):
        self._responses = list(responses)

    def count_messages(self, messages) -> int:
        return sum(len(json.dumps(m, ensure_ascii=False)) // 3 for m in messages) + 8

    def generate(self, messages, schema, **_kwargs):
        return {
            "text": self._responses.pop(0),
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
        }


def test_eval_rag_qas06_runs_end_to_end_with_mocked_generator(tmp_path):
    canonical_path = tmp_path / "canonical.json"
    canonical = {
        "schema_version": "idp-canonical-1",
        "pages": [
            {
                "page_number": 1,
                "blocks": [
                    {"type": "SectionHeader", "text": "Chương 1. Độ phân tán"},
                    {
                        "type": "Text",
                        "text": "Khoảng biến thiên, kí hiệu là R, là hiệu số giữa giá trị lớn nhất và giá trị nhỏ nhất.",
                    },
                ],
            }
        ],
    }
    canonical_path.write_text(json.dumps(canonical, ensure_ascii=False), encoding="utf-8")

    retrieve_fn = build_canonical_retriever(canonical_path)
    generator = _MockGenerator(
        [
            json.dumps(
                {
                    "status": "answered",
                    "claims": [
                        {
                            "text": "Khoảng biến thiên R là hiệu giữa giá trị lớn nhất và nhỏ nhất.",
                            "basis": "source",
                            "evidence": [
                                {
                                    "id": "S1",
                                    "quote": "Khoảng biến thiên, kí hiệu là R, là hiệu số giữa giá trị lớn nhất và giá trị nhỏ nhất.",
                                }
                            ],
                        }
                    ],
                    "missing_parts": [],
                },
                ensure_ascii=False,
            )
        ]
    )
    pipeline = GroundedTaskPipeline(generator)
    cases = [
        {
            "question": "Khoảng biến thiên là gì?",
            "answerable": True,
            "expected_substrings": ["hiệu", "lớn nhất"],
        },
        {
            "question": "Thời tiết hôm nay ở Hà Nội thế nào?",
            "answerable": False,
        },
    ]
    report = run_evaluation(cases, retrieve_fn, pipeline, metadata={"mode": "mock"})
    assert report["cases_count"] == 2
    assert report["manual_audit_required"] is True
    assert report["certifies_qas06"] is False
    assert report["qa_report"]["citation_accuracy"] == 1.0
    assert report["qa_report"]["correct_refusal_rate"] == 1.0
    assert report["p50_latency_ms"] is not None
    assert report["p95_latency_ms"] is not None
