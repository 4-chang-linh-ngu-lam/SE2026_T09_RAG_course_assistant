import json
import threading
import time

import pytest
from rag.generation.contracts.evidence import evidence_items
from rag.generation.contracts.schema_subset import SchemaViolation, check
from rag.generation.pipeline import GroundedTaskPipeline
from rag.generation.policy.config import TutorConfig
from rag.generation.runtime.budget import TRIM_SENTENCES, BudgetError, BudgetPlanner
from rag.generation.runtime.scheduler import (
    P0_INTERACTIVE,
    P2_BACKGROUND,
    SchedulerBusy,
    SlotScheduler,
)
from rag.generation.tasks.qa import condense as condense_mod
from rag.generation.tasks.qa.quick import QUICK, answer_quick, build_schema
from rag.generation.tasks.qa.render import mask_revoked, render_answer

TEXT = ("Quang hợp là quá trình cây xanh sử dụng năng lượng ánh sáng để tổng hợp chất hữu cơ. "
        "Quá trình này diễn ra chủ yếu ở lá, trong lục lạp. Nhiệt độ thích hợp khoảng 25 °C.")


@pytest.mark.unit
def test_quick_answer_maps_quotes_to_source_spans(fake_generator, record):
    evidence = evidence_items([record(TEXT, offset=1000)])

    def responder(task, payload, schema, call):
        assert task == "qa.quick" and call["profile"] == "grounded_qa"
        return {"status": "answered", "missing_parts": [], "claims": [
            {"text": "Quang hợp diễn ra chủ yếu ở lá, trong lục lạp.", "basis": "source",
             "evidence": [{"id": "S1", "quote": "Quá trình này diễn ra chủ yếu ở lá, trong lục lạp."}]}]}

    pipeline = GroundedTaskPipeline(fake_generator(responder))
    answer = answer_quick(pipeline, question="Quang hợp diễn ra ở đâu?", evidence=evidence, grade=7)
    assert answer["status"] == "answered"
    cite = answer["claims"][0]["evidence"][0]
    start = TEXT.index("Quá trình này")
    assert cite["source_spans"] == [{"source_id": "doc-v1", "start": 1000 + start,
                                     "end": 1000 + start + len(cite["quote"])}]
    assert answer["provenance"][0]["raw_response_sha256"] and "text" not in answer["provenance"][0]


@pytest.mark.unit
def test_grammar_rejects_invented_quote_and_general_when_disabled(record):
    evidence = evidence_items([record(TEXT)])
    schema = build_schema({"question": "q", "config": None}, evidence)
    good = {"status": "insufficient_evidence", "claims": [], "missing_parts": []}
    check(good, schema)
    for bad in (
        {"status": "answered", "missing_parts": [], "claims": [
            {"text": "x", "basis": "source", "evidence": [{"id": "S1", "quote": "bịa ra hoàn toàn"}]}]},
        {"status": "answered", "missing_parts": [], "claims": [{"text": "x", "basis": "general"}]},
        {"status": "answered", "missing_parts": ["thiếu"], "claims": [
            {"text": "x", "basis": "source", "evidence": [{"id": "S1", "quote": "Quá trình này diễn ra chủ yếu ở lá, trong lục lạp."}]}]},
    ):
        with pytest.raises(SchemaViolation):
            check(bad, schema)


@pytest.mark.unit
def test_general_knowledge_branch_only_when_teacher_enables_it(fake_generator, record):
    evidence = evidence_items([record(TEXT)])
    config = TutorConfig(allow_general_knowledge=True)

    def responder(task, payload, schema, call):
        return {"status": "partially_answered", "missing_parts": ["Công thức hoá học"], "claims": [
            {"text": "Quang hợp dùng năng lượng ánh sáng.", "basis": "source",
             "evidence": [{"id": "S1", "quote": "Quang hợp là quá trình cây xanh sử dụng năng lượng ánh sáng để tổng hợp chất hữu cơ."}]},
            {"text": "Sản phẩm phụ của quang hợp là khí oxi.", "basis": "general"}]}

    answer = answer_quick(GroundedTaskPipeline(fake_generator(responder)), question="Quang hợp là gì?",
                          evidence=evidence, config=config)
    assert [c["basis"] for c in answer["claims"]] == ["source", "general"]
    rendered = render_answer(answer, lambda source_id, spans: {"document": "Sinh 7", "page": 12})
    assert rendered["claims"][1]["label"].startswith("Kiến thức chung")
    assert rendered["claims"][0]["citations"][0]["location"] == {"document": "Sinh 7", "page": 12}
    assert rendered["notice"]
    masked = mask_revoked(rendered, allowed_source_ids=[])
    assert masked["claims"][0]["citations"] == [{"masked": True, "reason": "source_access_revoked"}]


@pytest.mark.unit
def test_lexical_verifier_drops_invented_number_and_downgrades(fake_generator, record):
    evidence = evidence_items([record(TEXT)])

    def responder(task, payload, schema, call):
        return {"status": "answered", "missing_parts": [], "claims": [
            {"text": "Nhiệt độ thích hợp khoảng 35 °C.", "basis": "source",
             "evidence": [{"id": "S1", "quote": "Nhiệt độ thích hợp khoảng 25 °C."}]},
            {"text": "Quá trình diễn ra ở lục lạp.", "basis": "source",
             "evidence": [{"id": "S1", "quote": "Quá trình này diễn ra chủ yếu ở lá, trong lục lạp."}]}]}

    answer = answer_quick(GroundedTaskPipeline(fake_generator(responder)), question="?", evidence=evidence)
    assert answer["status"] == "partially_answered"
    assert len(answer["claims"]) == 1
    assert {"claim_dropped_lexical_gap", "downgraded_to_partial"} <= set(answer["flags"])


@pytest.mark.unit
def test_lexical_verifier_accepts_numbers_and_names_from_the_question(fake_generator, record):
    evidence = evidence_items([record(TEXT)])

    def responder(task, payload, schema, call):
        return {"status": "answered", "missing_parts": [], "claims": [
            {"text": "Theo Bảng 1, nhiệt độ thích hợp khoảng 25 °C.", "basis": "source",
             "evidence": [{"id": "S1", "quote": "Nhiệt độ thích hợp khoảng 25 °C."}]}]}

    answer = answer_quick(GroundedTaskPipeline(fake_generator(responder)),
                          question="Theo Bảng 1, nhiệt độ thích hợp là bao nhiêu?", evidence=evidence)
    assert answer["status"] == "answered"
    assert answer["flags"] == []
    # The same claim is still dropped when the question did not supply them.
    plain = answer_quick(GroundedTaskPipeline(fake_generator(responder)),
                         question="Nhiệt độ thích hợp là bao nhiêu?", evidence=evidence)
    assert plain["status"] == "insufficient_evidence"


@pytest.mark.unit
def test_hyphenated_and_wrapped_names_match_their_source():
    from rag.generation.grounding.lexical import lexical_gaps

    support = "mô hình Malthus, mô hình Lotka–Volterra và Pierre–Simon\nLaplace."
    assert lexical_gaps("Sách nhắc mô hình Lotka–Volterra và Pierre-Simon Laplace.", support) == {}
    assert lexical_gaps("Sách nhắc mô hình của Gauss.", support) == {"names": ["Gauss"]}


@pytest.mark.unit
def test_openai_compatible_fills_only_optional_empty_arrays(record):
    from rag.generation.openai_compatible import _normalize_response_json

    evidence = evidence_items([record(TEXT)])
    schema = build_schema({"question": "?", "config": TutorConfig().to_dict()}, evidence)
    quote = "Quang hợp là quá trình cây xanh sử dụng năng lượng ánh sáng để tổng hợp chất hữu cơ."
    answered = {"status": "answered", "claims": [
        {"text": "Quang hợp tạo chất hữu cơ.", "basis": "source", "evidence": [{"id": "S1", "quote": quote}]}]}
    check(json.loads(_normalize_response_json(json.dumps(answered), schema)), schema)
    partial = {**answered, "status": "partially_answered"}
    with pytest.raises(SchemaViolation):
        check(json.loads(_normalize_response_json(json.dumps(partial), schema)), schema)


@pytest.mark.unit
def test_no_evidence_refuses_without_model_call(fake_generator):
    generator = fake_generator(lambda *a: pytest.fail("model must not be called"))
    answer = answer_quick(GroundedTaskPipeline(generator), question="Hỏi gì đó", evidence=[])
    assert answer["status"] == "insufficient_evidence" and answer["refusal_reason"] == "no_evidence"


@pytest.mark.unit
def test_contract_failure_becomes_honest_refusal(fake_generator, record):
    evidence = evidence_items([record(TEXT)])
    generator = fake_generator(lambda *a: ('{"status": "answered", "claims": [', "length"))
    answer = answer_quick(GroundedTaskPipeline(generator), question="?", evidence=evidence)
    assert answer["status"] == "insufficient_evidence"
    assert answer["refusal_reason"] == "generation_not_complete"


@pytest.mark.unit
def test_judge_mode_drops_claims_the_judge_rejects(fake_generator, record):
    evidence = evidence_items([record(TEXT)])

    def responder(task, payload, schema, call):
        if task == "judge.entailment":
            assert call["profile"] == "judge"
            return {"verdict": "not_mentioned"}
        return {"status": "answered", "missing_parts": [], "claims": [
            {"text": "Quang hợp diễn ra ở rễ.", "basis": "source",
             "evidence": [{"id": "S1", "quote": "Quá trình này diễn ra chủ yếu ở lá, trong lục lạp."}]}]}

    answer = answer_quick(GroundedTaskPipeline(fake_generator(responder)), question="?",
                          evidence=evidence, judge=True)
    assert answer["status"] == "insufficient_evidence"
    assert "claim_dropped_by_judge" in answer["flags"]


@pytest.mark.unit
def test_budget_planner_drops_tail_then_cuts_sentences(record):
    evidence = evidence_items([record(TEXT * 20, record_id="a"), record(TEXT, record_id="b")])
    planner = BudgetPlanner(lambda messages: len(messages[0]["content"]) // 4, 1024)

    def build(ev):
        return [{"role": "user", "content": json.dumps([e["text"] for e in ev], ensure_ascii=False)}]

    packed = planner.pack(build, evidence, 512, trim=TRIM_SENTENCES)
    assert packed.dropped_ids == ("S2",) and packed.truncated_ids == ("S1",)
    item = packed.evidence[0]
    assert item["text"] == item["record"]["text"] and TEXT.startswith(item["text"][:40])
    assert item["record"]["source_spans"][0]["end"] == len(item["text"])
    with pytest.raises(BudgetError):
        planner.pack(build, evidence, 512, trim="none")


@pytest.mark.unit
def test_scheduler_admits_interactive_before_queued_background():
    scheduler, order = SlotScheduler(1), []
    hold = threading.Event()

    def worker(priority, name):
        with scheduler.slot(priority):
            order.append(name)
            if name == "first":
                hold.wait(2)

    first = threading.Thread(target=worker, args=(P2_BACKGROUND, "first"))
    first.start()
    time.sleep(0.05)
    background = threading.Thread(target=worker, args=(P2_BACKGROUND, "background"))
    background.start()
    time.sleep(0.05)
    interactive = threading.Thread(target=worker, args=(P0_INTERACTIVE, "interactive"))
    interactive.start()
    time.sleep(0.05)
    with pytest.raises(SchedulerBusy), scheduler.slot(P0_INTERACTIVE, timeout=0.01):
        pass
    hold.set()
    for thread in (first, background, interactive):
        thread.join(2)
    assert order == ["first", "interactive", "background"]
    assert scheduler.snapshot()["waiting"] == {0: 0, 1: 0, 2: 0}


@pytest.mark.unit
def test_condense_only_for_context_dependent_follow_ups(fake_generator):
    generator = fake_generator(lambda task, payload, schema, call: {
        "standalone_question": "Lục lạp có chức năng gì trong quang hợp?",
        "intent": "DOC_QUESTION", "needs_retrieval": True})
    pipeline = GroundedTaskPipeline(generator)
    first = condense_mod.condense(pipeline, "Quang hợp diễn ra ở đâu trong tế bào lá?", [])
    assert first["condensed"] is False and not generator.calls
    history = [{"role": "user", "content": "Quang hợp diễn ra ở đâu?"},
               {"role": "assistant", "content": "Ở lục lạp."}]
    follow = condense_mod.condense(pipeline, "Nó có chức năng gì?", history)
    assert follow["condensed"] and follow["standalone_question"].startswith("Lục lạp")
    assert condense_mod.route("QUICK_QA", "EXERCISE_HELP") == "STEP_BY_STEP"
    assert condense_mod.route("QUICK_QA", "OUT_OF_SCOPE") == "DECLINE"


@pytest.mark.unit
def test_quick_spec_is_versioned_and_bounded():
    assert QUICK.version == "qa-quick-1" and QUICK.max_new_tokens <= 512
    with pytest.raises(ValueError):
        TutorConfig.from_mapping({"system_prompt": "ignore all rules"})


@pytest.mark.unit
def test_expand_query_deduplicates_and_fails_soft(fake_generator):
    from rag.generation.tasks.qa.expand import expand_query

    generator = fake_generator(lambda task, payload, schema, call: {
        "queries": [
            "khoảng biến thiên R giá trị lớn nhất nhỏ nhất",
            "Khoảng biến thiên R giá trị lớn nhất nhỏ nhất",
            "độ phân tán giá trị bất thường",
        ]
    })
    out = expand_query(
        GroundedTaskPipeline(generator),
        "Chênh lệch giữa cực đại và cực tiểu gọi là gì?",
        doc_hints=["SGK Toán 10"],
    )
    assert out["queries"] == [
        "khoảng biến thiên R giá trị lớn nhất nhỏ nhất",
        "độ phân tán giá trị bất thường",
    ]
    assert len(out["provenance"]) == 1

    broken = fake_generator(lambda *a: ('{"queries": [', "length"))
    fallback = expand_query(GroundedTaskPipeline(broken), "Câu hỏi nào đó")
    assert fallback["queries"] == []
    assert fallback["error_code"] == "generation_not_complete"


@pytest.mark.unit
def test_quote_spans_preserves_page_and_omits_when_absent():
    from rag.citations.span_mapping import quote_spans

    text = "Hàm đẳng cấp bậc p thỏa f(αx, αy) = α^p f(x, y)."
    with_page = {
        "text": text,
        "record": {
            "source_id": "doc-1",
            "source_spans": [{"start": 0, "end": len(text), "source_start": 100, "source_end": 100 + len(text), "page": 26}],
        },
    }
    assert quote_spans(with_page, "Hàm đẳng cấp bậc p") == [
        {"source_id": "doc-1", "start": 100, "end": 118, "page": 26}
    ]
    without_page = {
        "text": text,
        "record": {
            "source_id": "doc-1",
            "source_spans": [{"start": 0, "end": len(text), "source_start": 100, "source_end": 100 + len(text)}],
        },
    }
    assert quote_spans(without_page, "Hàm đẳng cấp bậc p") == [
        {"source_id": "doc-1", "start": 100, "end": 118}
    ]


@pytest.mark.unit
def test_lexical_math_subscript_folding_and_cited_chunk_support(fake_generator, record):
    from rag.generation.grounding.lexical import lexical_gaps

    assert lexical_gaps("Nghiệm là x₀ = 2", "Với x_{0} = 2 ta có nghiệm.") == {}
    assert lexical_gaps("Nghiệm là x₀ = 5", "Với x_{0} = 2 ta có nghiệm.") == {"numbers": ["5"]}

    wrapped_record = record("Nghiệm dao động là x(t) = x_{0} cos(3t)\nvà biên độ ban đầu bằng x_{0}.", offset=0)
    evidence = evidence_items([wrapped_record])

    def responder(task, payload, schema, call):
        return {
            "status": "answered",
            "missing_parts": [],
            "claims": [
                {
                    "text": "Nghiệm dao động là x(t) = x₀ cos(3t) với biên độ ban đầu là x₀.",
                    "basis": "source",
                    "evidence": [{"id": "S1", "quote": "và biên độ ban đầu bằng x_{0}."}],
                }
            ],
        }

    answer = answer_quick(GroundedTaskPipeline(fake_generator(responder)), question="Nghiệm là gì?", evidence=evidence)
    assert answer["status"] == "answered"
    assert answer["flags"] == []


@pytest.mark.unit
def test_openai_compatible_normalization_and_registry_expand():
    from rag.generation import registry
    from rag.generation.openai_compatible import _normalize_response_json

    assert "qa.expand_query" in {s["name"] for s in registry.catalog()}
    schema = {
        "type": "object",
        "properties": {
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "evidence": {
                            "type": "array",
                            "items": {
                                "oneOf": [
                                    {
                                        "type": "object",
                                        "properties": {
                                            "id": {"const": "S1"},
                                            "quote": {
                                                "type": "string",
                                                "enum": [
                                                    "2.4",
                                                    "2.4\nPhương trình đẳng cấp bậc p thỏa f(αx, αy) = α^p f(x, y).",
                                                ],
                                            },
                                        },
                                    }
                                ]
                            },
                        }
                    },
                },
            }
        },
    }
    fenced = '```json\n{"claims":[{"evidence":[{"id":"S1","quote":"2.4 Phương trình đẳng cấp bậc p"}]}]}\n```'
    parsed = json.loads(_normalize_response_json(fenced, schema))
    assert parsed["claims"][0]["evidence"][0]["quote"] == "2.4\nPhương trình đẳng cấp bậc p thỏa f(αx, αy) = α^p f(x, y)."


@pytest.mark.unit
def test_openai_compatible_does_not_fabricate_empty_or_loose_quotes():
    from rag.generation.openai_compatible import _match_quote_enum

    snippets = [
        "Phương trình vi phân cấp hai có hai nghiệm độc lập tuyến tính.",
        "Nghiệm tổng quát của phương trình là y = C1 y1(x) + C2 y2(x).",
    ]
    assert _match_quote_enum("", snippets) is None
    assert _match_quote_enum("   ", snippets) is None
    assert _match_quote_enum("Nội dung bịa đặt có từ phương trình và nghiệm", snippets) is None
    assert _match_quote_enum("Phương trình", snippets) is None  # too short (< 12 chars)


@pytest.mark.unit
def test_openai_compatible_forwards_sampling_profile_budget_and_schema_trimming(monkeypatch, record):
    import io
    from rag.generation.openai_compatible import OpenAICompatibleGenerator
    from rag.generation.runtime.sampling import ITEM_GENERATION, JUDGE
    from rag.generation.tasks.qa.quick import QUICK

    captured_bodies = []

    class FakeResp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    gen = OpenAICompatibleGenerator(
        "https://api.example.com",
        "sk-key",
        model="m1",
        context_tokens=900,
        max_new_tokens=256,
        output_ceiling=768,
    )

    class FakeOpener:
        def open(self, req, timeout=None):
            body = json.loads(req.data.decode("utf-8"))
            captured_bodies.append(body)
            raw_content = body["messages"][-1]["content"]
            try:
                task_payload = json.loads(raw_content)
            except ValueError:
                task_payload = {}
            if task_payload.get("task") == "judge.entailment":
                content = json.dumps({"verdict": "entailed"})
            else:
                content = json.dumps(
                    {
                        "status": "answered",
                        "missing_parts": [],
                        "claims": [
                            {
                                "text": "Quang hợp là quá trình tổng hợp chất hữu cơ.",
                                "basis": "source",
                                "evidence": [
                                    {
                                        "id": "S1",
                                        "quote": "Quang hợp là quá trình cây xanh sử dụng năng lượng ánh sáng để tổng hợp chất hữu cơ.",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
            return FakeResp(
                json.dumps(
                    {
                        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
                        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
                    }
                ).encode("utf-8")
            )

    gen.opener = FakeOpener()
    pipe = GroundedTaskPipeline(gen)

    # 1) Profile + exact budget forwarded (not output_ceiling)
    from rag.generation.grounding.judge import ENTAILMENT
    res_judge = pipe.run(
        ENTAILMENT,
        {"statement": "Quang hợp cần ánh sáng", "question": "Quang hợp cần gì?"},
        evidence_items([record(TEXT)]),
        seed=77,
    )
    assert res_judge.ok is True
    assert captured_bodies[0]["max_tokens"] == ENTAILMENT.max_new_tokens == 24
    assert captured_bodies[0]["temperature"] == JUDGE.temperature == 0.0
    assert captured_bodies[0]["seed"] == 77

    # ITEM_GENERATION forwards temperature + presence_penalty + seed
    gen.generate(
        [{"role": "user", "content": "hi"}],
        {"type": "object"},
        profile=ITEM_GENERATION,
        max_new_tokens=512,
        seed=99,
    )
    assert captured_bodies[1]["max_tokens"] == 768
    assert captured_bodies[1]["temperature"] == ITEM_GENERATION.temperature
    assert captured_bodies[1]["presence_penalty"] == ITEM_GENERATION.presence_penalty
    assert captured_bodies[1]["seed"] == 99

    # 2) Schema-aware trimming drops S2 when combined prompt + schema enum exceeds context budget
    #    (while messages without injected schema still fit BudgetPlanner alone).
    gen_schema = OpenAICompatibleGenerator(
        "https://api.example.com",
        "sk-key",
        model="m1",
        context_tokens=3500,
        max_new_tokens=512,
        output_ceiling=768,
    )
    gen_schema.opener = FakeOpener()
    pipe_schema = GroundedTaskPipeline(gen_schema)
    long_filler = " ".join(f"Câu phụ {i} không liên quan." for i in range(28))
    ev = evidence_items([record(TEXT, record_id="a"), record(long_filler, record_id="b")])
    res_quick = pipe_schema.run(QUICK, {"question": "Quang hợp là gì?", "config": None}, ev)
    assert res_quick.ok is True
    assert "S2" in res_quick.dropped_evidence_ids
    assert res_quick.provenance[0]["prompt_tokens"] <= 3500 - QUICK.max_new_tokens - 64


@pytest.mark.unit
def test_render_answer_distinguishes_model_failures_from_no_evidence():
    from rag.generation.tasks.qa.quick import refusal
    from rag.generation.tasks.qa.render import MODEL_ERROR_NOTICE, render_answer

    no_ev = render_answer(refusal("no_evidence"), lambda *_: None)
    assert "không có đủ căn cứ" in (no_ev["notice"] or "")
    assert no_ev["refusal_reason"] == "no_evidence"

    schema_err = render_answer(refusal("schema_violation"), lambda *_: None)
    assert schema_err["notice"] == MODEL_ERROR_NOTICE
    assert schema_err["refusal_reason"] == "schema_violation"

    doc_err = render_answer(refusal("document_unavailable"), lambda *_: None)
    assert "Không thể tải nội dung tài liệu" in (doc_err["notice"] or "")
    assert doc_err["refusal_reason"] == "document_unavailable"


@pytest.mark.unit
def test_lexical_strict_numbers_and_vietnamese_headings():
    from rag.generation.grounding.lexical import lexical_gaps, unsupported_numbers

    assert unsupported_numbers("Giá trị là 35", "Hệ số là 3,5") == ["35"]
    assert unsupported_numbers("Kết quả bằng 0", "Điều này không có tác dụng") == ["0"]
    assert unsupported_numbers("Có 5 nghiệm", "Năm 1954 diễn ra sự kiện") == ["5"]
    assert unsupported_numbers("Có 4 cách", "Rèn luyện tư duy phản biện") == ["4"]
    assert lexical_gaps(
        "Theo Định lý 2 và Phương trình trên, nhiệt độ là 25 °C.",
        "định lý 2 trong bài nêu nhiệt độ 25 °C.",
    ) == {}


@pytest.mark.unit
def test_step_rejects_meta_toc_plan_and_handles_partially_correct(fake_generator, record):
    from rag.generation.tasks.qa import step as step_mod

    evidence = evidence_items([record("Chương 3 trình bày về phương trình vi phân cấp hai.")])

    def bad_plan(_task, payload, _schema, _call):
        return {
            "status": "planned",
            "problem": payload["problem"],
            "final_answer": "Chương 3",
            "steps": [
                {
                    "goal": "Tìm xem chương nào trình bày về phương trình vi phân",
                    "hint": "Xem trong mục lục xem chương nào nói về nội dung này?",
                    "hint_more": "Đọc kỹ tiêu đề chương.",
                    "expected": "Chương 3",
                    "evidence": [{"id": "S1", "quote": "Chương 3 trình bày về phương trình vi phân cấp hai."}],
                }
            ],
        }

    res = step_mod.start_session(
        GroundedTaskPipeline(fake_generator(bad_plan)),
        problem="Học phương trình vi phân",
        evidence=evidence,
    )
    assert res["session"] is None
    assert res["error_code"] == "meta_step_rejected"

    # partially_correct should give next hint without counting a wrong attempt on hint_level < 2
    good_ev = evidence_items([record(TEXT)])

    def partial_check(task, payload, schema, _call):
        if task == "qa.step_plan":
            return {
                "status": "planned",
                "problem": payload["problem"],
                "final_answer": "lá, lục lạp",
                "steps": [
                    {
                        "goal": "Nêu nơi diễn ra quang hợp",
                        "hint": "Bộ phận nào của cây?",
                        "hint_more": "Diễn ra ở bào quan nào trong lá?",
                        "expected": "lá và lục lạp",
                        "evidence": [{"id": "S1", "quote": "Quá trình này diễn ra chủ yếu ở lá, trong lục lạp."}],
                    }
                ],
            }
        return {"verdict": "partially_correct", "feedback": "Gần đúng rồi, em bổ sung thêm bào quan nhé."}

    pipe = GroundedTaskPipeline(fake_generator(partial_check))
    session = step_mod.start_session(pipe, problem="Quang hợp diễn ra ở đâu?", evidence=good_ev)["session"]
    event = step_mod.check_step(pipe, session, "ở lá")
    assert event["kind"] == "step_partially_correct"
    assert session.wrong_attempts == 0
    assert event["hint"]["level"] == 2


@pytest.mark.unit
def test_condense_recognizes_nhu_nao():
    assert condense_mod.should_condense(
        "tiếp theo làm như nào vậy ạ",
        [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
    )
