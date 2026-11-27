"""OpenAI-compatible / DeepSeek chat completions adapter for GroundedTaskPipeline."""

from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from typing import Any

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            newurl, code, f"redirect blocked ({code})", headers, fp
        )


def _compact_schema_for_prompt(node: Any) -> Any:
    """Replace huge citation quote enums with concise length/verbatim constraints for prompts."""
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            id_spec = props.get("id")
            quote_spec = props.get("quote")
            if (
                isinstance(id_spec, dict)
                and isinstance(id_spec.get("const"), str)
                and isinstance(quote_spec, dict)
                and isinstance(quote_spec.get("enum"), list)
            ):
                compact_props = {
                    k: (
                        {
                            "type": "string",
                            "minLength": quote_spec.get("minLength", 3),
                            "maxLength": quote_spec.get("maxLength", 160),
                            "description": (
                                "Exact verbatim sentence or clause copied from this source's "
                                "text in evidence"
                            ),
                        }
                        if k == "quote"
                        else _compact_schema_for_prompt(v)
                    )
                    for k, v in props.items()
                }
                return {**node, "properties": compact_props}
        return {k: _compact_schema_for_prompt(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_compact_schema_for_prompt(item) for item in node]
    return node


def _schema_instruction(schema: dict[str, Any]) -> str:
    compact = json.dumps(
        _compact_schema_for_prompt(schema),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return (
        "You MUST respond with a single valid JSON object (no markdown fences, no extra prose) "
        'that strictly conforms to this JSON Schema. Whenever a field specifies "enum" or '
        '"const", copy an exact value verbatim. For citation "quote" fields, copy an exact '
        "verbatim sentence or clause (3-160 chars) directly from the referenced source's text "
        f"in the evidence without altering wording:\n{compact}"
    )


def _extract_quote_enums(node: Any, out: dict[str, list[str]]) -> None:
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            id_spec = props.get("id")
            quote_spec = props.get("quote")
            if (
                isinstance(id_spec, dict)
                and isinstance(id_spec.get("const"), str)
                and isinstance(quote_spec, dict)
                and isinstance(quote_spec.get("enum"), list)
            ):
                snippets = [s for s in quote_spec["enum"] if isinstance(s, str)]
                if snippets:
                    out.setdefault(id_spec["const"], []).extend(snippets)
        for value in node.values():
            _extract_quote_enums(value, out)
    elif isinstance(node, list):
        for item in node:
            _extract_quote_enums(item, out)


def _match_quote_enums(quote: str, snippets: list[str], *, max_snippets: int = 1) -> list[str]:
    if not snippets:
        return []
    if quote in snippets:
        return [quote]
    q_norm = " ".join(quote.split()).lower()
    if not q_norm:
        return []
    ordered = sorted(snippets, key=lambda s: (len(s.strip()) < 15, len(s)))
    for snippet in ordered:
        if " ".join(snippet.split()).lower() == q_norm:
            return [snippet]
    for snippet in ordered:
        s_norm = " ".join(snippet.split()).lower()
        if len(q_norm) >= 16 and q_norm in s_norm:
            return [snippet]
        if len(s_norm) >= 15 and s_norm in q_norm and len(s_norm) / len(q_norm) >= 0.75:
            return [snippet]

    if len(q_norm) < 16:
        return []

    # Multiline/composite verbatim quote spanning two adjacent source snippets
    # (e.g. a lead-in line followed by a formula or wrapped line): only snap
    # when verified enum snippets cover >= 75% of the non-space quote text.
    covered = [False] * len(q_norm)
    matched: list[tuple[int, int, str]] = []
    by_longest = sorted(snippets, key=len, reverse=True)
    for snippet in by_longest:
        s_norm = " ".join(snippet.split()).lower()
        s_core = s_norm.lstrip("•-*–— ").rstrip(".,;:")
        if len(s_core) < 8:
            continue
        pos = q_norm.find(s_core)
        if pos != -1:
            end = pos + len(s_core)
            if not all(covered[pos:end]):
                for i in range(pos, end):
                    covered[i] = True
                matched.append((pos, end - pos, snippet))
    if not matched:
        return []
    # Also allow an uncovered tail/head fragment (>= 10 chars) that is an exact
    # verbatim substring of an offered snippet (e.g. truncated formula line).
    idx = 0
    while idx < len(q_norm):
        if covered[idx] or q_norm[idx].isspace():
            idx += 1
            continue
        end = idx
        while end < len(q_norm) and not covered[end]:
            end += 1
        frag = q_norm[idx:end].strip(" \t\r\n.,;:-•")
        if len(frag) >= 10:
            for snippet in ordered:
                s_norm = " ".join(snippet.split()).lower()
                if frag in s_norm:
                    for i in range(idx, end):
                        covered[i] = True
                    matched.append((idx, len(frag), snippet))
                    break
        idx = end

    nonspace = [i for i, ch in enumerate(q_norm) if not ch.isspace()]
    if not nonspace:
        return []
    coverage = sum(1 for i in nonspace if covered[i]) / len(nonspace)
    if coverage < 0.75:
        return []
    matched.sort(key=lambda item: (-item[1], item[0]))
    selected = []
    for _, _, snip in matched:
        if snip not in selected:
            selected.append(snip)
            if len(selected) >= max(1, max_snippets):
                break
    return selected


def _match_quote_enum(quote: str, snippets: list[str]) -> str | None:
    hits = _match_quote_enums(quote, snippets, max_snippets=1)
    return hits[0] if hits else None


def _snap_quote_enums(node: Any, enums_by_id: dict[str, list[str]]) -> Any:
    if isinstance(node, dict):
        if (
            isinstance(node.get("id"), str)
            and isinstance(node.get("quote"), str)
            and node["id"] in enums_by_id
        ):
            matched = _match_quote_enum(node["quote"], enums_by_id[node["id"]])
            if matched is not None:
                node["quote"] = matched
            return node
        for key, value in node.items():
            if key in ("evidence", "quotes") and isinstance(value, list):
                expanded = []
                max_expand = 2 if len(value) == 1 else 1
                for item in value:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("id"), str)
                        and isinstance(item.get("quote"), str)
                        and item["id"] in enums_by_id
                    ):
                        hits = _match_quote_enums(
                            item["quote"], enums_by_id[item["id"]], max_snippets=max_expand
                        )
                        if hits:
                            for hit in hits:
                                expanded.append({**item, "quote": hit})
                            continue
                    expanded.append(_snap_quote_enums(item, enums_by_id))
                deduped = []
                seen: set[tuple[str, str]] = set()
                for item in expanded:
                    if (
                        isinstance(item, dict)
                        and isinstance(item.get("id"), str)
                        and isinstance(item.get("quote"), str)
                    ):
                        pair = (item["id"], item["quote"])
                        if pair in seen:
                            continue
                        seen.add(pair)
                    deduped.append(item)
                node[key] = deduped
            else:
                node[key] = _snap_quote_enums(value, enums_by_id)
        return node
    if isinstance(node, list):
        return [_snap_quote_enums(item, enums_by_id) for item in node]
    return node


def _strip_code_fence(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2 and lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _fill_empty_arrays(value: Any, schema: dict[str, Any]) -> Any:
    """Add required array fields an API model omitted, only where empty is valid.

    JSON mode does not enforce the schema; models often drop an empty list
    such as ``missing_parts`` of an ``answered`` result. The branch is chosen
    by its ``status`` const when present; fields with ``minItems`` >= 1 are
    never filled, so a genuinely incomplete answer still fails the schema.
    """
    if not isinstance(value, dict):
        return value
    for branch in schema.get("oneOf") or [schema]:
        if not isinstance(branch, dict):
            continue
        props = branch.get("properties") or {}
        status = (props.get("status") or {}).get("const")
        if status is not None and value.get("status") != status:
            continue
        for key in branch.get("required") or []:
            prop = props.get(key) or {}
            if key not in value and prop.get("type") == "array" and not prop.get("minItems"):
                value[key] = []
        break
    return value


def _normalize_response_json(content: str, schema: dict[str, Any]) -> str:
    try:
        parsed = json.loads(_strip_code_fence(content))
    except ValueError:
        return content
    parsed = _fill_empty_arrays(parsed, schema)
    enums_by_id: dict[str, list[str]] = {}
    _extract_quote_enums(schema, enums_by_id)
    if enums_by_id:
        parsed = _snap_quote_enums(parsed, enums_by_id)
    return json.dumps(parsed, ensure_ascii=False)


def _inject_schema_prompt(
    messages: list[dict[str, str]], schema: dict[str, Any]
) -> list[dict[str, str]]:
    instruction = _schema_instruction(schema)
    copied = [dict(m) for m in messages]
    if copied and copied[0].get("role") == "system":
        copied[0]["content"] = (
            f"{copied[0].get('content', '').rstrip()}\n\n{instruction}".strip()
        )
        return copied
    return [{"role": "system", "content": instruction}, *copied]


class _ApproxTokenCounter:
    """Character-based token counter matching count_messages for external API models."""

    identity = {"unit": "approx_tokens", "adapter": "openai-compatible-generator-1"}

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, (len(text) + 1) // 2)


class OpenAICompatibleGenerator:
    """Adapter matching LlamaGenerator's contract against an OpenAI-compatible HTTP API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        model: str = "deepseek-chat",
        context_tokens: int = 8192,
        max_new_tokens: int = 1024,
        output_ceiling: int = 1024,
        timeout: float = 60.0,
        disable_reasoning: bool | None = None,
    ) -> None:
        clean_base = str(base_url).strip().rstrip("/")
        if not clean_base.startswith(("https://", "http://")):
            raise ValueError("base_url must be http or https")
        clean_base = clean_base.removesuffix("/chat/completions")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("api_key is required")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model is required")
        if (
            type(context_tokens) is not int
            or type(max_new_tokens) is not int
            or context_tokens < 833
            or max_new_tokens < 64
            or max_new_tokens + 64 >= context_tokens
        ):
            raise ValueError("invalid generator context/output budget")
        if (
            type(output_ceiling) is not int
            or not max_new_tokens <= output_ceiling <= 4096
            or output_ceiling + 64 >= context_tokens
        ):
            raise ValueError("invalid generator output ceiling")
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 600
        ):
            raise ValueError("timeout must be in (0, 600]")

        self.base_url = clean_base
        self._api_key = api_key.strip()
        self.model = model.strip()
        self.context_tokens = context_tokens
        self.max_new_tokens = max_new_tokens
        self.output_ceiling = output_ceiling
        self.timeout = float(timeout)
        self.disable_reasoning = (
            ("openrouter.ai" in clean_base.lower())
            if disable_reasoning is None
            else bool(disable_reasoning)
        )
        self.counter = _ApproxTokenCounter()
        self._default_opener = urllib.request.build_opener(_NoRedirect())
        self.opener = self._default_opener
        self._http_client = (
            httpx.Client(
                follow_redirects=False,
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
            )
            if httpx is not None
            else None
        )
        self.identity = {
            "adapter": "openai-compatible-generator-1",
            "model": self.model,
            "base_url": self.base_url,
            "context_tokens": context_tokens,
            "max_new_tokens": max_new_tokens,
            "output_ceiling": output_ceiling,
            "external_inference": True,
        }

    def close(self) -> None:
        client = getattr(self, "_http_client", None)
        if client is not None:
            client.close()
            self._http_client = None

    def count_messages(self, messages: list[dict[str, str]]) -> int:
        total = 4
        for message in messages:
            serialized = json.dumps(message, ensure_ascii=False)
            total += max(4, (len(serialized) + 1) // 2)
        return total

    def count_request_tokens(
        self, messages: list[dict[str, str]], schema: dict[str, Any]
    ) -> int:
        return self.count_messages(_inject_schema_prompt(messages, schema))

    def generate(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        profile: dict[str, Any] | Any = None,
        max_new_tokens: int | None = None,
        seed: int | None = None,
    ) -> dict[str, Any]:
        budget = self.max_new_tokens if max_new_tokens is None else max_new_tokens
        if type(budget) is not int or not 1 <= budget <= self.output_ceiling:
            raise ValueError("invalid max_new_tokens")
        if seed is not None and type(seed) is not int:
            raise ValueError("invalid seed")

        temperature = 0.2
        top_p: float | None = None
        presence_penalty: float | None = None
        if isinstance(profile, dict):
            prof_temp = profile.get("temperature")
            prof_top_p = profile.get("top_p")
            prof_penalty = profile.get("presence_penalty")
        elif profile is not None:
            prof_temp = getattr(profile, "temperature", None)
            prof_top_p = getattr(profile, "top_p", None)
            prof_penalty = getattr(profile, "presence_penalty", None)
        else:
            prof_temp = prof_top_p = prof_penalty = None

        if isinstance(prof_temp, (int, float)) and not isinstance(prof_temp, bool):
            temperature = float(prof_temp)
        if isinstance(prof_top_p, (int, float)) and not isinstance(prof_top_p, bool):
            top_p = float(prof_top_p)
        if isinstance(prof_penalty, (int, float)) and not isinstance(prof_penalty, bool):
            presence_penalty = float(prof_penalty)

        effective_budget = (
            budget if budget <= 256 else min(budget * 2, max(budget, self.output_ceiling))
        )
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": _inject_schema_prompt(messages, schema),
            "max_tokens": effective_budget,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        if self.disable_reasoning:
            payload["reasoning"] = {"enabled": False}
        if top_p is not None and 0 < top_p <= 1:
            payload["top_p"] = top_p
        if presence_penalty is not None and presence_penalty != 0:
            payload["presence_penalty"] = presence_penalty
        if seed is not None:
            payload["seed"] = seed

        data = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        started = time.perf_counter()
        if (
            self.opener is self._default_opener
            and self._http_client is not None
            and httpx is not None
        ):
            try:
                resp = self._http_client.post(
                    f"{self.base_url}/chat/completions",
                    content=data,
                    headers=headers,
                )
            except httpx.TimeoutException as exc:
                raise TimeoutError(str(exc)) from exc
            except httpx.HTTPError as exc:
                raise OSError(str(exc)) from exc
            if 300 <= resp.status_code < 400:
                raise OSError(f"redirect blocked ({resp.status_code})")
            if resp.status_code >= 400:
                raise OSError(f"HTTP {resp.status_code}")
            raw = resp.content
        else:
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=data,
                headers=headers,
                method="POST",
            )
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
        seconds = time.perf_counter() - started
        if len(raw) > 2_000_000:
            raise ValueError("generation response byte limit")
        body = json.loads(raw)
        choices = body.get("choices") if isinstance(body, dict) else None
        if not isinstance(choices, list) or not choices:
            raise ValueError("missing choices in completion response")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise (
                ValueError("missing message content in completion response")
                if content is None
                else TypeError("invalid message content type")
            )
        return {
            "text": _normalize_response_json(content, schema),
            "finish_reason": first.get("finish_reason"),
            "usage": body.get("usage"),
            "seconds": seconds,
            "max_new_tokens": budget,
        }
