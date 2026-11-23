import json

from services.rag.pipeline import RagPipeline
from services.rag.retrieval.multihop import (
    CallableMultiHopPlanner,
    GeneratorMultiHopPlanner,
    MultiHopDecision,
)
from services.rag.search.retrieval_plan import SearchRequest


class Counter:
    identity = {"unit": "tokens", "name": "test-counter", "version": "1"}

    def count(self, text):
        return len(text.split())


def _item(child_id, text):
    return {
        "id": child_id,
        "source_id": child_id,
        "section_path": ["test"],
        "text": text,
        "source_spans": [{"start": 0, "end": len(text), "source_start": 0, "source_end": len(text)}],
    }


class Retriever:
    counter = Counter()
    identity = {"version": "test-retriever"}
    children = {"child-1": {}, "child-2": {}}

    def __init__(self):
        self.queries = []

    def retrieve(self, request, *, authorize):
        authorize()
        self.queries.append(request.query)
        if request.query.startswith("Clark Gable"):
            item = _item("child-2", "Clark Gable nổi tiếng với vai Rhett Butler.")
        else:
            item = _item("child-1", "Clark Gable là chồng của Carole Lombard.")
        return {
            "status": "retrieved_unverified",
            "ranked_child_ids": [item["id"]],
            "context": {"items": [item], "skipped_budget_child_ids": [], "context": item["text"]},
            "flags": [],
            "trace": {"total_ms": 1.0, "query_embeddings_computed": 1, "passes": []},
        }


class Generator:
    counter = Counter()
    identity = {"version": "test-generator"}
    context_tokens = 4096
    max_new_tokens = 128

    def count_messages(self, messages):
        return sum(self.counter.count(message["content"]) for message in messages)

    def generate(self, messages, _schema):
        payload = json.loads(messages[1]["content"])
        evidence_id = payload["evidence"][0]["id"]
        return {"finish_reason": "stop", "text": json.dumps({
            "status": "answered",
            "claims": [{"text": "Rhett Butler", "evidence": [{"id": evidence_id}]}],
        }, ensure_ascii=False)}


class PlannerGenerator:
    identity = {"version": "test-planner-generator"}

    def __init__(self):
        self.calls = []

    def generate(self, messages, _schema):
        self.calls.append(messages)
        return {"finish_reason": "stop", "text": json.dumps({
            "mode": "decompose",
            "rewrite": None,
            "subqueries": ["A là gì?", "B là gì?"],
        }, ensure_ascii=False)}


def test_generator_planner_is_gated_and_validates_bounded_json():
    generator = PlannerGenerator()
    planner = GeneratorMultiHopPlanner(generator)

    assert planner.plan(SearchRequest("được biết đến với vai nào?")) == MultiHopDecision()
    decision = planner.plan(SearchRequest("So sánh A và B"))

    assert decision == MultiHopDecision(mode="decompose", queries=("A là gì?", "B là gì?"))
    assert len(generator.calls) == 1


def test_pipeline_runs_planner_queries_and_merges_evidence():
    retriever = Retriever()
    planner = CallableMultiHopPlanner(
        lambda _request: MultiHopDecision(
            mode="decompose", queries=("Clark Gable nổi tiếng với vai nào?",)
        ),
        identity={"version": "test-planner"},
    )
    pipeline = RagPipeline(retriever, generator=Generator(),
                           multihop_planner=planner)

    result = pipeline.answer(
        SearchRequest("Chồng của Carole Lombard nổi tiếng với vai nào?"),
        authorize=lambda: {"child-1", "child-2"},
    )

    assert retriever.queries == [
        "Chồng của Carole Lombard nổi tiếng với vai nào?",
        "Clark Gable nổi tiếng với vai nào?",
    ]
    assert result["status"] == "answered"
    assert result["trace"]["multi_hop"]["hops"] == 2
    assert {item["record"]["source_id"] for item in result["evidence"]} == {"child-1", "child-2"}


def test_pipeline_falls_back_to_direct_retrieval_when_planner_fails():
    retriever = Retriever()
    planner = CallableMultiHopPlanner(
        lambda _request: (_ for _ in ()).throw(ValueError("bad plan")),
        identity={"version": "test-planner"},
    )
    pipeline = RagPipeline(retriever, generator=Generator(),
                           multihop_planner=planner)

    result = pipeline.answer(SearchRequest("Một câu hỏi trực tiếp?"),
                             authorize=lambda: {"child-1", "child-2"})

    assert retriever.queries == ["Một câu hỏi trực tiếp?"]
    assert result["trace"]["multi_hop"]["status"] == "planner_failed"


def test_pipeline_uses_rewrite_instead_of_retrieving_the_same_question_twice():
    retriever = Retriever()
    planner = CallableMultiHopPlanner(
        lambda _request: MultiHopDecision(
            mode="rewrite", queries=("Clark Gable nổi tiếng với vai nào?",)
        ),
        identity={"version": "test-planner"},
    )
    pipeline = RagPipeline(retriever, generator=Generator(),
                           multihop_planner=planner)

    result = pipeline.answer(
        SearchRequest("vai nổi tiếng của ông ấy?", context_hint="Carole Lombard"),
        authorize=lambda: {"child-1", "child-2"},
    )

    assert retriever.queries == ["Clark Gable nổi tiếng với vai nào?"]
    assert result["trace"]["multi_hop"]["mode"] == "rewrite"
    assert result["trace"]["multi_hop"]["hops"] == 1
