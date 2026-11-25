"""Build a real text index and answer only from currently authorized sources."""

import hashlib
import json
import re

import numpy as np

from services.rag.generation.pipeline import GroundedTaskPipeline
from services.rag.indexing.rag_corpus import TextDocument, build_corpus
from services.rag.retrieval.corpus import load_retriever
from services.rag.retrieval.text_pipeline import TextRagPipeline
from services.rag.search.retrieval_plan import SearchRequest


class Counter:
    identity = {"kind": "fixture_words", "unit": "tokens", "version": 1}

    def count(self, text):
        return len(re.findall(r"\w+|[^\w\s]", text)) + 2


class Encoder:
    counter = Counter()
    identity = {"adapter": "fixture_bow", "dimension": 32, "passage_prefix": ""}

    def encode(self, texts, **_kwargs):
        vectors = np.zeros((len(texts), 32), dtype=np.float32)
        vectors[:, 0] = 1e-3
        for index, text in enumerate(texts):
            for word in re.findall(r"\w+", text.casefold()):
                vectors[index, hashlib.sha256(word.encode()).digest()[0] % 32] += 1
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors, {"items": len(texts)}


class Generator:
    identity = {"kind": "fixture_generator"}
    context_tokens = 4096

    def count_messages(self, messages):
        return sum(len(message["content"].split()) for message in messages)

    def generate(self, _messages, schema, **_kwargs):
        branch = schema["oneOf"][0]["properties"]["claims"]["items"]
        options = branch["properties"]["evidence"]["items"]["oneOf"]
        citation = options[0]["properties"]
        quote = citation["quote"]["enum"][0]
        return {"finish_reason": "stop", "text": json.dumps({
            "status": "answered", "claims": [{"text": quote, "evidence": [
                {"id": citation["id"]["const"], "quote": quote}
            ]}]
        })}


def test_index_retrieve_answer_excludes_ungranted_document(tmp_path):
    visible = "# Bài học\n\nCoban là tên ví dụ trong bài học.\n"
    denied = "# Bài học khác\n\nBí mật lavender chỉ ở tài liệu riêng.\n"
    encoder = Encoder()
    build_corpus([TextDocument("visible", visible), TextDocument("denied", denied)],
                 tmp_path / "corpus", encoder=encoder, max_tokens=48)
    retriever = load_retriever(tmp_path / "corpus", encoder=encoder)[0]
    allowed = {cid for cid, row in retriever.children.items()
               if row["source_id"] == "visible"}
    pipeline = TextRagPipeline(retriever, GroundedTaskPipeline(Generator()))

    result = pipeline.answer(SearchRequest("Coban là gì?"), authorize=lambda: allowed.copy())

    assert result["status"] == "answered"
    assert result["evidence"]
    assert {item["record"]["source_id"] for item in result["evidence"]} == {"visible"}
    assert "lavender" not in json.dumps(result, ensure_ascii=False).lower()
