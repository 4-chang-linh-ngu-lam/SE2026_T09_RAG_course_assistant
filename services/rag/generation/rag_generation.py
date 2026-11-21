"""Bounded llama.cpp loopback text generation. No downloads or external APIs."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time
import urllib.parse
import urllib.request

from ..embedding.bge_embedding import file_sha256


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError("local generation does not follow redirects")


class LlamaTokenCounter:
    def __init__(self, generator):
        self.generator = generator
        self.identity = {"kind": "local_llama_tokenize", "unit": "tokens",
            "model_sha256": generator.identity["model_sha256"], "add_special": False,
            "parse_special": True, "build_info": generator.identity["build_info"]}

    def count(self, text):
        response = self.generator._request("/tokenize", {"content": text,
            "add_special": False, "parse_special": True})
        ids = response.get("tokens")
        if not isinstance(ids, list) or any(type(x) is not int for x in ids):
            raise ValueError("invalid local tokenizer response")
        return len(ids)


class LlamaGenerator:
    def __init__(self, origin, *, model_path, server_path, provenance,
                 context_tokens=4096, max_new_tokens=512, timeout=180, output_ceiling=None):
        parsed = urllib.parse.urlsplit(origin)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment or not parsed.port):
            raise ValueError("explicit loopback HTTP origin/port required")
        if (type(context_tokens) is not int or not 512 <= context_tokens <= 32768
                or type(max_new_tokens) is not int or not 16 <= max_new_tokens <= 2048
                or max_new_tokens + 64 >= context_tokens):
            raise ValueError("invalid generator context/output budget")
        # Per-call max_new_tokens may not exceed this adapter-level ceiling.
        output_ceiling = max_new_tokens if output_ceiling is None else output_ceiling
        if (type(output_ceiling) is not int or not max_new_tokens <= output_ceiling <= 2048
                or output_ceiling + 64 >= context_tokens):
            raise ValueError("invalid generator output ceiling")
        self.output_ceiling = output_ceiling
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 600:
            raise ValueError("timeout must be in (0, 600]")
        if not isinstance(provenance, dict) or any(not isinstance(provenance.get(k), str)
                or not provenance[k] for k in ("repo", "revision", "variant")):
            raise ValueError("pinned generator artifact provenance required")
        self.origin, self.timeout = origin.rstrip("/"), timeout
        self.model_path = Path(model_path).resolve(strict=True)
        self.context_tokens, self.max_new_tokens = context_tokens, max_new_tokens
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
        props = self._props()
        digest = file_sha256(self.model_path)
        if provenance.get("sha256") is not None and provenance["sha256"] != digest:
            raise ValueError("generator model SHA256 mismatch")
        self.model = props["model_alias"]
        self.identity = {"adapter": "idp-local-llama-generator-1", "model_sha256": digest,
            "server_executable_sha256": file_sha256(server_path), "build_info": props["build_info"],
            "artifact_provenance": {k: provenance[k] for k in ("repo", "revision", "variant")},
            "context_tokens": context_tokens, "max_new_tokens": max_new_tokens,
            "output_ceiling": output_ceiling,
            "sampling": {"temperature": .7, "top_p": .8, "top_k": 20, "min_p": 0,
                         "presence_penalty": 1.5, "seed": 42, "thinking": False},
            "external_inference": False, "verifies_cpu_offload": False}
        self.counter = LlamaTokenCounter(self)

    def _request(self, route, payload=None):
        if route not in {"/props", "/tokenize", "/apply-template", "/v1/chat/completions"}:
            raise ValueError("unsupported local inference route")
        data = None if payload is None else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        if data is not None and len(data) > 1_000_000:
            raise ValueError("generation request byte limit")
        request = urllib.request.Request(self.origin + route, data=data,
            headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=self.timeout) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("generation response byte limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("expected local server JSON object")
        return value

    def _props(self):
        props = self._request("/props")
        actual = Path(props.get("model_path", "")).resolve()
        settings = props.get("default_generation_settings", {})
        if (actual != self.model_path or settings.get("n_ctx") != self.context_tokens
                or props.get("total_slots") != 1 or not isinstance(props.get("model_alias"), str)
                or not isinstance(props.get("build_info"), (str, dict)) or not props["build_info"]):
            raise ValueError("server model/context/single-slot contract differs")
        return props

    def count_messages(self, messages):
        prompt = self._request("/apply-template", {"messages": messages,
            "chat_template_kwargs": {"enable_thinking": False}}).get("prompt")
        if not isinstance(prompt, str):
            raise ValueError("chat template did not return a prompt")
        return self.counter.count(prompt)

    def generate(self, messages, schema, *, profile=None, max_new_tokens=None, seed=None):
        """Generate one grammar-constrained completion.

        Without keyword arguments the request is byte-identical to the original
        adapter (legacy sampling, seed 42, ``self.max_new_tokens``). ``profile``
        is a ``runtime.sampling.SamplingProfile``; ``max_new_tokens`` may not
        exceed ``self.output_ceiling``.
        """
        max_new = self.max_new_tokens if max_new_tokens is None else max_new_tokens
        if type(max_new) is not int or not 16 <= max_new <= self.output_ceiling:
            raise ValueError("per-call max_new_tokens outside adapter ceiling")
        if profile is None:
            if seed is not None:
                raise ValueError("seed requires an explicit sampling profile")
            sampling = {"temperature": .7, "top_p": .8, "top_k": 20, "min_p": 0,
                        "presence_penalty": 1.5, "seed": 42}
            cache_prompt = False
        else:
            fields = profile.request_fields(42 if seed is None else seed)
            cache_prompt = fields.pop("cache_prompt")
            sampling = fields
        props = self._props()
        if props["model_alias"] != self.model or props["build_info"] != self.identity["build_info"]:
            raise ValueError("generator runtime changed after binding")
        tokens = self.count_messages(messages)
        if tokens + max_new + 64 > self.context_tokens:
            raise ValueError("complete chat prompt exceeds budget; truncation forbidden")
        started = time.perf_counter()
        response = self._request("/v1/chat/completions", {"model": self.model, "messages": messages,
            "max_tokens": max_new, **sampling, "stream": False,
            "cache_prompt": cache_prompt, "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object", "schema": schema}})
        choices = response.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("expected one generator choice")
        choice = choices[0]
        message = choice.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise ValueError("generator returned no text")
        return {"text": text, "finish_reason": choice.get("finish_reason"),
            "usage": response.get("usage", {}), "server_timings": response.get("timings", {}),
            "prompt_tokens_preflight": tokens, "seconds": time.perf_counter() - started,
            "max_new_tokens": max_new, "sampling": {**sampling, "cache_prompt": cache_prompt}}
