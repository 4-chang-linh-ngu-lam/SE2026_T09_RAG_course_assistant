"""LlamaGenerator request shape without a server: legacy calls stay byte-identical."""
import json

import pytest
from services.rag.generation.rag_generation import LlamaGenerator, LlamaTokenCounter
from services.rag.generation.runtime.sampling import (
    GROUNDED_QA,
    ITEM_GENERATION,
    SamplingProfile,
    derive_seed,
)

LEGACY_KEYS = ["model", "messages", "max_tokens", "temperature", "top_p", "top_k", "min_p",
               "presence_penalty", "seed", "stream", "cache_prompt", "chat_template_kwargs", "response_format"]


def adapter(output_ceiling=768):
    generator = LlamaGenerator.__new__(LlamaGenerator)
    generator.model, generator.context_tokens = "local", 4096
    generator.max_new_tokens, generator.output_ceiling = 512, output_ceiling
    generator.identity = {"build_info": "b1"}
    sent = []

    def request(route, payload=None):
        if route == "/props":
            return {"model_alias": "local", "build_info": "b1"}
        if route == "/apply-template":
            return {"prompt": "p"}
        if route == "/tokenize":
            return {"tokens": [1, 2, 3]}
        sent.append(payload)
        return {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}}

    generator._props = lambda: request("/props")
    generator._request = request
    generator.counter = LlamaTokenCounter.__new__(LlamaTokenCounter)
    generator.counter.generator = generator
    return generator, sent


@pytest.mark.contract
def test_legacy_request_unchanged():
    generator, sent = adapter()
    generator.generate([{"role": "user", "content": "x"}], {"type": "object"})
    payload = sent[0]
    assert list(payload) == LEGACY_KEYS
    assert (payload["max_tokens"], payload["temperature"], payload["top_p"], payload["top_k"],
            payload["presence_penalty"], payload["seed"], payload["cache_prompt"]) == (512, .7, .8, 20, 1.5, 42, False)


@pytest.mark.contract
def test_per_call_profile_and_ceiling():
    generator, sent = adapter()
    out = generator.generate([{"role": "user", "content": "x"}], {}, profile=ITEM_GENERATION,
                             max_new_tokens=768, seed=1234)
    payload = sent[0]
    assert list(payload) == LEGACY_KEYS
    assert payload["max_tokens"] == 768 and payload["seed"] == 1234 and payload["cache_prompt"] is True
    assert out["sampling"]["presence_penalty"] == ITEM_GENERATION.presence_penalty
    generator.generate([{"role": "user", "content": "x"}], {}, profile=GROUNDED_QA)
    assert sent[1]["temperature"] == 0.2 and sent[1]["presence_penalty"] == 0
    with pytest.raises(ValueError):
        generator.generate([], {}, profile=GROUNDED_QA, max_new_tokens=1024)
    with pytest.raises(ValueError):
        generator.generate([], {}, seed=5)          # a seed without a profile is ambiguous


@pytest.mark.unit
def test_profiles_validate_and_seed_is_deterministic():
    with pytest.raises(ValueError):
        SamplingProfile("bad", temperature=3, top_p=1, top_k=1)
    assert derive_seed("a", 1) == derive_seed("a", 1) != derive_seed("a", 2)
    assert 0 <= derive_seed({"x": [1, 2]}) < 2**31
    json.dumps(GROUNDED_QA.describe(1))


@pytest.mark.unit
def test_pipeline_refuses_spec_above_adapter_ceiling():
    from services.rag.generation.pipeline import GroundedTaskPipeline
    from services.rag.generation.tasks.quiz.verify import ITEM_SPECS

    generator, sent = adapter(output_ceiling=512)
    generator.count_messages = lambda messages: 10
    with pytest.raises(ValueError, match="adapter ceiling"):
        GroundedTaskPipeline(generator).run(ITEM_SPECS["true_false_4"], {}, [{"id": "S1"}])
    assert sent == []
