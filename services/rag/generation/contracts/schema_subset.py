"""Strict checker for the JSON-Schema subset the generation grammars use.

llama.cpp turns the same schema into a grammar; this checker re-applies it to
the parsed output so a server that silently ignored ``response_format`` (or a
grammar feature that was not enforced, such as ``uniqueItems``) still fails
closed. Unsupported keywords raise ``TypeError`` — a programming error, not a
model error — so the subset cannot drift silently.
"""
from __future__ import annotations

import json

_KNOWN = {"type", "enum", "const", "oneOf", "anyOf", "properties", "required",
          "additionalProperties", "items", "minItems", "maxItems", "minLength",
          "maxLength", "minimum", "maximum", "uniqueItems", "description", "title"}


class SchemaViolation(ValueError):
    def __init__(self, path: str, reason: str):
        super().__init__(f"{path}: {reason}")
        self.path, self.reason = path, reason


def _type_ok(value, expected):
    return {"object": isinstance(value, dict), "array": isinstance(value, list),
            "string": isinstance(value, str), "boolean": isinstance(value, bool),
            "integer": type(value) is int,
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": value is None}[expected]


def check(value, schema: dict, path: str = "$") -> None:
    if not isinstance(schema, dict):
        raise TypeError("schema must be an object")
    unknown = set(schema) - _KNOWN
    if unknown:
        raise TypeError(f"unsupported schema keywords: {sorted(unknown)}")
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            try:
                check(value, branch, path)
                matches += 1
            except SchemaViolation:
                pass
        if matches != 1:
            raise SchemaViolation(path, f"oneOf matched {matches} branches")
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                check(value, branch, path)
                break
            except SchemaViolation:
                pass
        else:
            raise SchemaViolation(path, "anyOf matched no branch")
    if "type" in schema:
        types = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_type_ok(value, t) for t in types):
            raise SchemaViolation(path, f"expected {schema['type']}")
    if "const" in schema and not _same(value, schema["const"]):
        raise SchemaViolation(path, "const mismatch")
    if "enum" in schema and not any(_same(value, option) for option in schema["enum"]):
        raise SchemaViolation(path, "not in enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise SchemaViolation(path, "string length")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaViolation(path, "below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaViolation(path, "above maximum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise SchemaViolation(path, "array length")
        if schema.get("uniqueItems"):
            keys = [json.dumps(v, sort_keys=True, ensure_ascii=False) for v in value]
            if len(set(keys)) != len(keys):
                raise SchemaViolation(path, "items not unique")
        if "items" in schema:
            for index, item in enumerate(value):
                check(item, schema["items"], f"{path}[{index}]")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaViolation(path, f"missing {key}")
        if schema.get("additionalProperties", True) is False:
            extra = set(value) - set(properties)
            if extra:
                raise SchemaViolation(path, f"unexpected {sorted(extra)}")
        for key, sub in properties.items():
            if key in value:
                check(value[key], sub, f"{path}.{key}")


def _same(a, b):
    return type(a) is type(b) and a == b or (
        isinstance(a, (int, float)) and isinstance(b, (int, float))
        and not isinstance(a, bool) and not isinstance(b, bool) and a == b)
