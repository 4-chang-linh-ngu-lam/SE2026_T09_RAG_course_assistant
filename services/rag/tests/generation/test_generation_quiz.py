import pytest
from rag.generation import registry
from rag.generation.contracts.evidence import evidence_items
from rag.generation.contracts.schema_subset import SchemaViolation, check
from rag.generation.eval.metrics import qa_report, quiz_report
from rag.generation.grounding.lexical import unsupported_numbers
from rag.generation.grounding.safe_math import MathError, evaluate, parse_number
from rag.generation.pipeline import GroundedTaskPipeline
from rag.generation.tasks.qa import step as step_mod
from rag.generation.tasks.qa.explain import explain_mistake
from rag.generation.tasks.quiz import review
from rag.generation.tasks.quiz.assemble import assemble, near_duplicates, parallel_forms
from rag.generation.tasks.quiz.blueprint import parse_quiz_spec
from rag.generation.tasks.quiz.items import build_schema as item_schema
from rag.generation.tasks.quiz.job import regenerate, run_job
from rag.generation.tasks.quiz.knowledge_units import build_knowledge_units

PHYS = ("Vận tốc cho biết mức độ nhanh hay chậm của chuyển động. "
        "Công thức tính vận tốc là v = s / t, trong đó s là quãng đường và t là thời gian. "
        "Đơn vị vận tốc thường dùng là m/s và km/h. "
        "Một ô tô đi quãng đường 120 km trong 2 giờ thì có vận tốc 60 km/h.")
EXERCISE = "Bài 1. Một người đi xe đạp 15 km trong 1 giờ. Tính vận tốc."


def tokens(text):
    return len(text) // 4 + 1


def quotes_in(schema):
    """All quote enum values offered anywhere in a schema."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if "enum" in node and node.get("maxLength") == 160:
                found.extend(node["enum"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(schema)
    return found


def pick(schema, fragment):
    return next(q for q in quotes_in(schema) if fragment in q)


def quiz_responder(distractor_entailed=False):
    def respond(task, payload, schema, call):
        if task == "quiz.fact_extract":
            return {"facts": [
                {"statement": "Công thức tính vận tốc là v = s / t.", "kind": "definition", "level_hint": "biet",
                 "quotes": [{"id": "S1", "quote": pick(schema, "Công thức tính vận tốc")}]},
                {"statement": "Đơn vị vận tốc thường dùng là m/s và km/h.", "kind": "property", "level_hint": "biet",
                 "quotes": [{"id": "S1", "quote": pick(schema, "Đơn vị vận tốc")}]},
                {"statement": "Ô tô đi 120 km trong 2 giờ có vận tốc 60 km/h.", "kind": "example",
                 "level_hint": "van_dung", "quotes": [{"id": "S1", "quote": pick(schema, "120 km")}]},
                {"statement": "Ô tô đi 120 km trong 3 giờ.", "kind": "example", "level_hint": "biet",
                 "quotes": [{"id": "S1", "quote": pick(schema, "Đơn vị vận tốc")}]},   # invented number
            ]}
        if task == "quiz.item.single_choice":
            return {"stem": "Đơn vị nào sau đây là đơn vị của vận tốc?", "correct_answer": "km/h",
                    "distractors": [{"text": "km", "misconception": "nhầm với đơn vị quãng đường"},
                                    {"text": "giờ", "misconception": "nhầm với đơn vị thời gian"},
                                    {"text": "N", "misconception": "nhầm với đơn vị lực"}],
                    "explanation": "Vận tốc đo bằng quãng đường chia thời gian nên có đơn vị km/h.",
                    "evidence": [{"id": "S1", "quote": pick(schema, "Đơn vị vận tốc")}]}
        if task == "quiz.item.true_false_4":
            return {"context": "Xét chuyển động của một ô tô.", "explanation": "Dựa vào công thức v = s / t.",
                    "statements": [
                        {"text": "Công thức tính vận tốc là v = s / t.", "truth": True,
                         "evidence": [{"id": "S1", "quote": pick(schema, "Công thức tính vận tốc")}]},
                        {"text": "Ô tô đi 120 km trong 2 giờ có vận tốc 60 km/h.", "truth": True,
                         "evidence": [{"id": "S1", "quote": pick(schema, "120 km")}]},
                        {"text": "Công thức tính vận tốc là v = s × t.", "truth": False,
                         "perturbation": "relation_reverse",
                         "evidence": [{"id": "S1", "quote": pick(schema, "Công thức tính vận tốc")}]},
                        {"text": "Ô tô đi 120 km trong 2 giờ có vận tốc 40 km/h.", "truth": False,
                         "perturbation": "number_change",
                         "evidence": [{"id": "S1", "quote": pick(schema, "120 km")}]}]}
        if task == "quiz.item.short_answer":
            return {"stem": "Ô tô đi 120 km trong 2 giờ. Vận tốc của ô tô là bao nhiêu km/h?",
                    "answer": {"kind": "number", "value": "60", "unit": "km/h", "tolerance": 0,
                               "computation": "120 / 2"},
                    "explanation": "v = s / t = 120 / 2 = 60 km/h.",
                    "evidence": [{"id": "S1", "quote": pick(schema, "120 km")}]}
        if task == "judge.entailment":
            statement = payload["statement"]
            if "v = s × t" in statement or "40 km/h" in statement:
                return {"verdict": "contradicted"}
            if statement in ("km", "giờ", "N"):
                return {"verdict": "entailed" if distractor_entailed and statement == "km" else "contradicted"}
            return {"verdict": "entailed"}
        if task == "quiz.solver":
            question = payload["question"]
            if question["type"] == "single_choice":
                return {"choice": next(o["label"] for o in question["options"] if o["text"] == "km/h")}
            if question["type"] == "true_false_4":
                return {"answers": [True, True, False, False]}
            return {"answer": "60 km/h"}
        raise AssertionError(task)
    return respond


def spec_data(**overrides):
    data = {"class_id": "class-1", "purpose": "PRACTICE", "grade": 8, "subject": "Vật lí",
            "scope": [{"document_version_id": "doc-v1", "section_paths": [["Chương 1"]]}],
            "matrix": [{"section": "Bài 2", "type": "single_choice", "level": "biet", "count": 1},
                       {"section": "Bài 2", "type": "true_false_4", "level": "hieu", "count": 1},
                       {"section": "Bài 2", "type": "short_answer", "level": "van_dung", "count": 1}]}
    data.update(overrides)
    return data


def units(record):
    return build_knowledge_units(
        [record(PHYS, section_path=("Chương 1", "Bài 2"), record_id="a"),
         record(EXERCISE, section_path=("Chương 1", "Bài 2"), record_id="b", offset=500)],
        count_tokens=tokens, max_tokens=400, is_exercise=lambda r: r["text"].startswith("Bài 1."))


@pytest.mark.unit
def test_quiz_job_end_to_end(fake_generator, record):
    generator = fake_generator(quiz_responder())
    pipeline = GroundedTaskPipeline(generator)
    spec = parse_quiz_spec(spec_data())
    kus = units(record)
    assert [u.exercise for u in kus] == [False, True]
    cache, events = {}, []
    job = run_job(pipeline, spec, kus, job_id="job-1", fact_cache=cache, progress=events.append)

    assert job["shortages"] == [] and job["status_counts"] == {"PASSED": 3}
    by_type = {d["type"]: d for d in job["drafts"]}
    single = by_type["single_choice"]["item"]
    assert single["correct_answer"] == "km/h" and single["evidence"][0]["source_spans"]
    assert by_type["short_answer"]["item"]["answer"]["computation_verified"] is True
    layout = next(l for l in job["layouts"] if l["type"] == "single_choice")
    assert [o["text"] for o in layout["options"] if o["correct"]] == ["km/h"]
    assert layout["key"] == [o["label"] for o in layout["options"] if o["correct"]]
    # invented-number fact was dropped by the lexical verifier, exercise unit never sent
    facts = next(iter(cache.values()))
    assert len(facts) == 3
    fact_calls = [c for c in generator.calls if c["task"] == "quiz.fact_extract"]
    assert len(fact_calls) == 1 and "Bài 1." not in str(fact_calls[0]["payload"])
    item_calls = [c for c in generator.calls if c["task"].startswith("quiz.item")]
    assert {c["profile"] for c in item_calls} == {"item_generation"}
    assert max(c["max_new_tokens"] for c in item_calls) == 768
    assert events[0]["kind"] == "facts_ready" and events[-1]["done"] == 3

    # Resume: completed drafts are not regenerated, cached facts are reused.
    before = len(generator.calls)
    again = run_job(pipeline, spec, kus, job_id="job-1", fact_cache=cache,
                    completed={d["slot_id"]: d for d in job["drafts"]})
    assert len(generator.calls) == before and again["status_counts"] == {"PASSED": 3}


@pytest.mark.unit
def test_entailed_distractor_rejects_after_retries(fake_generator, record):
    spec = parse_quiz_spec(spec_data(matrix=[{"section": "Bài 2", "type": "single_choice",
                                              "level": "biet", "count": 1}]))
    generator = fake_generator(quiz_responder(distractor_entailed=True))
    job = run_job(GroundedTaskPipeline(generator), spec, units(record), job_id="job-2")
    draft = job["drafts"][0]
    assert draft["status"] == "REJECTED_AUTO" and draft["error_code"] == "distractor_entailed"
    assert draft["attempts"] == 3 and len({r["sampling"]["seed"] for r in draft["generation_records"]}) == 3
    assert job["layouts"] == []


@pytest.mark.unit
def test_item_grammar_enforces_structure(record):
    kus = units(record)
    evidence = [kus[0].evidence()]
    tf = item_schema({"type": "true_false_4", "level": "hieu"}, evidence)
    quote = quotes_in(tf)[0]
    stmt = {"text": "Một mệnh đề bất kỳ", "truth": False, "evidence": [{"id": "S1", "quote": quote}]}
    with pytest.raises(SchemaViolation):   # false statement must name its perturbation
        check({"context": "c", "explanation": "e", "statements": [stmt] * 4}, tf)
    mc = item_schema({"type": "multiple_choice", "level": "biet", "option_count": 4}, evidence)
    base = {"stem": "Chọn các phát biểu đúng", "explanation": "e",
            "evidence": [{"id": "S1", "quote": quote}]}
    d = {"text": "x", "misconception": "m"}
    check({**base, "correct_answers": ["a", "b"], "distractors": [d, d]}, mc)
    with pytest.raises(SchemaViolation):   # 3 correct + 2 distractors = 5 options != 4
        check({**base, "correct_answers": ["a", "b", "c"], "distractors": [d, d]}, mc)


@pytest.mark.unit
def test_review_lifecycle_and_export(fake_generator, record):
    spec = parse_quiz_spec(spec_data(matrix=[{"section": "Bài 2", "type": "single_choice",
                                              "level": "biet", "count": 1}]))
    pipeline = GroundedTaskPipeline(fake_generator(quiz_responder()))
    kus = units(record)
    job = run_job(pipeline, spec, kus, job_id="job-3")
    draft = job["drafts"][0]
    with pytest.raises(ValueError):
        review.export_payload(draft, job={"id": "job-3"}, approved_by="t1")
    with pytest.raises(ValueError):
        review.review(draft, "reject", reviewer_id="t1", reason="free text")
    edited = {**draft["item"], "correct_answer": "m/s"}
    accepted = review.review(draft, "edit", reviewer_id="t1", edited_item=edited)
    payload = review.export_payload(accepted, job={"id": "job-3"}, approved_by="t1")
    assert payload["idempotency_key"] == draft["id"] and payload["edited_after_generation"] is True
    assert payload["generated_by"] == "AI" and payload["sources"][0]["source_id"] == "doc-v1"
    assert "evidence" not in payload["item"]

    marked = review.review(draft, "regenerate", reviewer_id="t1")
    fresh = regenerate(pipeline, spec, marked, kus[0], [], verify="basic")
    assert fresh["regenerations"] == 1 and fresh["seed"] != draft["seed"]


@pytest.mark.unit
def test_assemble_balances_key_positions():
    item = {"type": "single_choice", "stem": "s", "correct_answer": "K", "explanation": "e",
            "distractors": [{"text": t, "misconception": "m"} for t in "xyz"]}
    layouts = assemble([{"slot_id": str(i), "item": item} for i in range(40)], seed=7)
    positions = [l["key"][0] for l in layouts]
    assert {positions.count(p) for p in "ABCD"} == {10}
    assert all(l["options"]["ABCD".index(l["key"][0])]["text"] == "K" for l in layouts)


@pytest.mark.unit
def test_dedup_and_parallel_forms():
    dups = near_duplicates([("a", "Vận tốc là gì?"), ("b", "Vận tốc là gì ?"), ("c", "Lực là gì?")])
    assert dups and dups[0][:2] == ("b", "a")
    bank = [{"item_id": f"i{n}", "type": "single_choice", "level": "biet", "section": "Bài 2"} for n in range(5)]
    forms = parallel_forms(bank, [{"section": "Bài 2", "type": "single_choice", "level": "biet", "count": 2}],
                           forms=2, seed=1)
    assert not set(forms["forms"][0]) & set(forms["forms"][1]) and forms["shortages"] == []


@pytest.mark.unit
def test_quiz_spec_validation():
    with pytest.raises(ValueError):
        parse_quiz_spec(spec_data(grade=5))
    with pytest.raises(ValueError):
        parse_quiz_spec(spec_data(matrix=[{"section": "x", "type": "essay", "level": "biet", "count": 1}]))
    with pytest.raises(ValueError):
        parse_quiz_spec({**spec_data(), "system_prompt": "x"})


@pytest.mark.unit
def test_safe_math_and_numbers():
    assert evaluate("120 / 2") == 60 and evaluate("2^3 + sqrt(16)") == 12
    assert evaluate("3,5 × 2") == 7
    for bad in ("__import__('os')", "(1).__class__", "9**9**9", "a + 1", "[1, 2]"):
        with pytest.raises(MathError):
            evaluate(bad)
    assert parse_number("1.000.000,5") == 1000000.5 and parse_number("3,5") == 3.5
    assert unsupported_numbers("Có 25 °C và 3,5 kg", "nhiệt độ 25 °C, khối lượng 3.5 kg") == []
    assert unsupported_numbers("năm 1945", "năm 1954") == ["1945"]


@pytest.mark.unit
def test_step_by_step_session(fake_generator, record):
    evidence = evidence_items([record(PHYS)])

    def responder(task, payload, schema, call):
        if task == "qa.step_plan":
            return {"status": "planned", "problem": payload["problem"], "final_answer": "15 km/h", "steps": [
                {"goal": "Chọn công thức", "hint": "Vận tốc liên hệ với quãng đường và thời gian thế nào?",
                 "hint_more": "Nhớ lại công thức trong bài", "expected": "v = s / t",
                 "evidence": [{"id": "S1", "quote": pick(schema, "Công thức tính vận tốc")}]},
                {"goal": "Thay số", "hint": "Quãng đường và thời gian là bao nhiêu?",
                 "hint_more": "Chia quãng đường cho thời gian", "expected": "15",
                 "evidence": [{"id": "S1", "quote": pick(schema, "Công thức tính vận tốc")}]}]}
        if task == "qa.step_check":
            return {"verdict": "correct", "feedback": "Đúng rồi!"}
        raise AssertionError(task)

    pipeline = GroundedTaskPipeline(fake_generator(responder))
    started = step_mod.start_session(pipeline, problem="Đi 15 km trong 1 giờ. Tính vận tốc.",
                                     evidence=evidence, config={"hint_reveal_after": 2})
    session = started["session"]
    assert started["first_hint"]["level"] == 1
    assert "expected" not in str(session.public_view()) and "15 km/h" not in str(session.public_view())
    event = step_mod.check_step(pipeline, session, "v bằng s chia t")
    assert event["kind"] == "step_correct" and event["method"] == "model"
    wrong = step_mod.check_step(pipeline, session, "20")         # numeric: no model call
    assert wrong["kind"] == "step_incorrect" and wrong["method"] == "deterministic"
    assert wrong["hint"]["level"] == 2
    revealed = step_mod.check_step(pipeline, session, "30")
    assert revealed["kind"] == "step_revealed" and revealed["summary"]["final_answer"] == "15 km/h"
    restored = step_mod.StepSession.from_dict(session.to_dict())
    assert restored.state == "SOLVED"
    locked = step_mod.StepSession(plan=session.plan, config={**session.config, "allow_solution_reveal": False})
    with pytest.raises(PermissionError):
        locked.reveal_solution()


@pytest.mark.unit
def test_explain_mistake_falls_back_to_approved_explanation(fake_generator, record):
    evidence = evidence_items([record(PHYS)])
    pipeline = GroundedTaskPipeline(fake_generator(lambda *a: ("{", "length")))
    out = explain_mistake(pipeline, question="Đơn vị vận tốc?", student_choice="km", correct_answer="km/h",
                          pinned_evidence=evidence, approved_explanation="Vận tốc = quãng đường / thời gian.")
    assert out["fallback"] and out["explanation"].startswith("Vận tốc")


@pytest.mark.unit
def test_registry_and_metrics():
    names = {s["name"] for s in registry.catalog()}
    assert {"qa.quick", "qa.condense", "qa.step_plan", "quiz.fact_extract", "quiz.item.true_false_4",
            "quiz.solver", "judge.entailment"} <= names
    assert registry.get("qa.quick").version == "qa-quick-1"
    report = qa_report([{"answerable": False, "status": "insufficient_evidence"},
                        {"answerable": True, "status": "answered",
                         "citations": [{"supports": True, "class_ok": True}],
                         "claims": [{"basis": "source", "grounded": True}]}])
    assert report["correct_refusal_rate"] == 1.0 and report["cross_class_leaks"] == 0
    gate = quiz_report([{"id": "d1", "status": "ACCEPTED", "flags": []}], [{"draft_id": "d1", "key_correct": False}])
    assert gate["release_gate_ok"] is True   # ACCEPTED (not PASSED) -> not counted as unflagged PASSED
