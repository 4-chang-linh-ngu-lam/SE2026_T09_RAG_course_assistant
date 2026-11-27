"""Tests for compact schema prompting and quote snapping in OpenAICompatibleGenerator."""

import io
import json

from rag.generation.contracts.evidence import evidence_items
from rag.generation.openai_compatible import (
    OpenAICompatibleGenerator,
    _compact_schema_for_prompt,
    _schema_instruction,
)
from rag.generation.pipeline import GroundedTaskPipeline
from rag.generation.policy.config import TutorConfig
from rag.generation.tasks.qa.quick import QUICK, answer_quick


def _sample_evidence():
    records = [
        {
            "source_id": "doc-1",
            "section_path": ["Chương 1", "Bài 1"],
            "text": (
                "Khoảng biến thiên, kí hiệu là R, là hiệu số giữa giá trị lớn nhất "
                "và giá trị nhỏ nhất trong mẫu số liệu. "
                "Khoảng biến thiên rất dễ bị ảnh hưởng bởi giá trị bất thường. "
                "Khi các giá trị trong mẫu số liệu tập trung gần nhau thì khoảng biến thiên nhỏ. "
                "Ngược lại, chỉ cần một giá trị ngoại lệ rất lớn hoặc rất nhỏ cũng làm R tăng mạnh."
            ),
            "source_spans": [{"start": 0, "end": 329, "source_start": 0, "source_end": 329}],
        },
        {
            "source_id": "doc-2",
            "section_path": ["Chương 1", "Bài 2"],
            "text": (
                "Khoảng tứ phân vị là hiệu số giữa tứ phân vị thứ ba và tứ phân vị thứ nhất. "
                "Đại lượng này đo độ phân tán của nửa giữa mẫu số liệu và ít bị ảnh hưởng bởi ngoại lệ. "
                "Để tính khoảng tứ phân vị ta cần sắp xếp mẫu số liệu theo thứ tự không giảm. "
                "Sau đó xác định trung vị của nửa dưới và nửa trên để tính hiệu Q3 trừ Q1."
            ),
            "source_spans": [{"start": 0, "end": 313, "source_start": 0, "source_end": 313}],
        },
        {
            "source_id": "doc-3",
            "section_path": ["Chương 1", "Bài 3"],
            "text": (
                "Phương sai và độ lệch chuẩn đo mức độ phân tán quanh số trung bình cộng. "
                "Giá trị phương sai càng nhỏ thì các số liệu càng tập trung gần giá trị trung bình. "
                "Độ lệch chuẩn là căn bậc hai số học của phương sai và có cùng đơn vị đo với mẫu số liệu. "
                "Hai số đặc trưng này thường được dùng khi phân phối số liệu tương đối đối xứng."
            ),
            "source_spans": [{"start": 0, "end": 324, "source_start": 0, "source_end": 324}],
        },
    ]
    return evidence_items(records)


def test_compact_schema_prompt_omits_giant_quote_enums():
    ev = _sample_evidence()
    schema = QUICK.build_schema({"config": TutorConfig().to_dict()}, ev)
    raw_len = len(json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
    compact_len = len(
        json.dumps(_compact_schema_for_prompt(schema), ensure_ascii=False, separators=(",", ":"))
    )
    instruction = _schema_instruction(schema)
    assert "Khoảng biến thiên, kí hiệu là R" not in instruction
    assert "Phương sai và độ lệch chuẩn" not in instruction
    assert compact_len < raw_len
    assert len(instruction) < raw_len


def test_openai_compatible_snaps_valid_quotes_and_rejects_fabricated_quotes():
    ev = _sample_evidence()
    responses: list[str] = []
    sent_bodies: list[dict] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeOpener:
        def open(self, request, timeout=None):
            sent_bodies.append(json.loads(request.data.decode("utf-8")))
            content = responses.pop(0)
            payload = {
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            }
            return FakeResponse(json.dumps(payload).encode("utf-8"))

    gen = OpenAICompatibleGenerator("https://api.example.com", "sk-test", model="deepseek-chat")
    gen.opener = FakeOpener()
    pipeline = GroundedTaskPipeline(gen)

    # 1. Valid quote with minor whitespace difference snaps cleanly to schema enum.
    responses.append(
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
                                "quote": (
                                    "Khoảng biến thiên,  kí hiệu là R, là hiệu số giữa giá trị "
                                    "lớn nhất và giá trị nhỏ nhất trong mẫu số liệu."
                                ),
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    ok_res = answer_quick(pipeline, question="Khoảng biến thiên là gì?", evidence=ev)
    assert ok_res["status"] == "answered"
    assert len(ok_res["claims"]) == 1
    assert "Khoảng biến thiên, kí hiệu là R" not in sent_bodies[0]["messages"][0]["content"]

    # 2. Fabricated quote is NOT snapped and gets rejected cleanly across attempts.
    bad_payload = json.dumps(
        {
            "status": "answered",
            "claims": [
                {
                    "text": "Đây là câu bịa đặt.",
                    "basis": "source",
                    "evidence": [{"id": "S1", "quote": "Câu này hoàn toàn không tồn tại trong tài liệu."}],
                }
            ],
            "missing_parts": [],
        },
        ensure_ascii=False,
    )
    responses.extend([bad_payload, bad_payload])
    bad_res = answer_quick(pipeline, question="Khoảng biến thiên là gì?", evidence=ev)
    assert bad_res["status"] == "insufficient_evidence"
    assert bad_res["refusal_reason"] == "schema_violation"


def test_openai_compatible_httpx_keepalive_security_and_close():
    import httpx
    import pytest

    gen = OpenAICompatibleGenerator("https://api.example.com", "sk-test", model="deepseek-chat")
    assert gen._http_client is not None

    mode = {"case": "ok"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/chat/completions"
        if mode["case"] == "redirect":
            return httpx.Response(302, headers={"Location": "https://evil.example.com"})
        if mode["case"] == "oversized":
            return httpx.Response(200, content=b"x" * 2_000_005)
        if mode["case"] == "timeout":
            raise httpx.ReadTimeout("timed out")
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": '{"status":"ok"}'}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2},
            },
        )

    gen._http_client.close()
    gen._http_client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        timeout=gen.timeout,
    )
    try:
        out = gen.generate([{"role": "user", "content": "hi"}], {"type": "object"})
        assert out["finish_reason"] == "stop"

        mode["case"] = "redirect"
        with pytest.raises(OSError, match="redirect blocked"):
            gen.generate([{"role": "user", "content": "hi"}], {"type": "object"})

        mode["case"] = "oversized"
        with pytest.raises(ValueError, match="byte limit"):
            gen.generate([{"role": "user", "content": "hi"}], {"type": "object"})

        mode["case"] = "timeout"
        with pytest.raises(TimeoutError):
            gen.generate([{"role": "user", "content": "hi"}], {"type": "object"})
    finally:
        gen.close()
    assert gen._http_client is None


def test_source_quote_enums_preserves_coordinate_semicolon_and_snaps_multiline_quotes():
    from rag.citations.source_quotes import source_quote_enums

    h12_text = (
        "• Người ta chứng minh được rằng đường thẳng d có phương trình ax + by = c "
        "chia mặt phẳng toạ độ Oxy thành hai nửa mặt phẳng bờ d:\n\n"
        "- Một nửa mặt phẳng (không kể bờ d) gồm các điểm có toạ độ (x; y) thoả mãn ax + by > c;\n\n"
        "- Nửa mặt phẳng còn lại (không kể bờ d) gồm các điểm có toạ độ (x; y) thoả mãn\n\n"
        "ax + by < c."
    )
    h03_text = (
        "Theo định luật Kirchhoff, ta có\n\n"
        "I_{2} + I_{C1} = I_{1} ⇔ \\frac{V_{1} − V_{2}}{R_{2}} + C_{1}\\frac{dV_{1}}{dt} = "
        "\\frac{V_{s} − V_{1}}{R_{1}},\n"
    )
    ev = evidence_items(
        [
            {
                "source_id": "scan",
                "section_path": ["Trang 25"],
                "text": h12_text,
                "source_spans": [{"start": 0, "end": len(h12_text), "source_start": 0, "source_end": len(h12_text)}],
            },
            {
                "source_id": "native",
                "section_path": ["Trang 19"],
                "text": h03_text,
                "source_spans": [{"start": 0, "end": len(h03_text), "source_start": 0, "source_end": len(h03_text)}],
            },
        ]
    )
    enums = source_quote_enums(ev)
    assert any("(x; y) thoả mãn ax + by > c;" in s for s in enums["S1"])

    responses: list[str] = []

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeOpener:
        def open(self, request, timeout=None):
            content = responses.pop(0)
            payload = {
                "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            }
            return FakeResponse(json.dumps(payload).encode("utf-8"))

    gen = OpenAICompatibleGenerator("https://api.example.com", "sk-test", model="deepseek-chat")
    gen.opener = FakeOpener()
    pipeline = GroundedTaskPipeline(gen)

    # Multiline wrapped quote in H12 + coordinate (x; y) snaps cleanly and passes schema + lexical checks.
    responses.append(
        json.dumps(
            {
                "status": "answered",
                "claims": [
                    {
                        "text": "Một nửa mặt phẳng gồm các điểm (x; y) thỏa mãn ax + by > c.",
                        "basis": "source",
                        "evidence": [
                            {
                                "id": "S1",
                                "quote": "Một nửa mặt phẳng (không kể bờ d) gồm các điểm có toạ độ (x; y) thoả mãn ax + by > c",
                            }
                        ],
                    },
                    {
                        "text": "Nửa mặt phẳng còn lại gồm các điểm (x; y) thỏa mãn ax + by < c.",
                        "basis": "source",
                        "evidence": [
                            {
                                "id": "S1",
                                "quote": "Nửa mặt phẳng còn lại (không kể bờ d) gồm các điểm có toạ độ (x; y) thoả mãn ax + by < c",
                            }
                        ],
                    },
                ],
                "missing_parts": [],
            },
            ensure_ascii=False,
        )
    )
    res_h12 = answer_quick(pipeline, question="Đường thẳng ax + by = c chia mặt phẳng thành mấy phần?", evidence=ev)
    assert res_h12["status"] == "answered"
    assert len(res_h12["claims"]) == 2

    # Lead-in + formula quote in H03 snaps cleanly to both snippets and passes lexical_gaps.
    responses.append(
        json.dumps(
            {
                "status": "answered",
                "claims": [
                    {
                        "text": "Theo định luật Kirchhoff, tổng dòng I₂ + I_C1 bằng I₁.",
                        "basis": "source",
                        "evidence": [
                            {
                                "id": "S2",
                                "quote": "Theo định luật Kirchhoff, ta có\n\nI_{2} + I_{C1} = I_{1}",
                            }
                        ],
                    }
                ],
                "missing_parts": [],
            },
            ensure_ascii=False,
        )
    )
    res_h03 = answer_quick(pipeline, question="Theo định luật Kirchhoff, I₂ + I_C1 bằng gì?", evidence=ev)
    assert res_h03["status"] == "answered"
    assert len(res_h03["claims"]) == 1
