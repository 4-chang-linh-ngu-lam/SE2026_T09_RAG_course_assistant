"""Allowlisted constructor-based evidence JSON; no import names supplied by input."""

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import lru_cache
from types import MappingProxyType

from . import contracts


@lru_cache(maxsize=1)
def registry():
    from idp.ocr.backends import advanced
    from idp.pdf import acquire, geometry, merge, render

    types = {}
    for module in (contracts, geometry, render, acquire, merge, advanced):
        for value in vars(module).values():
            if isinstance(value, type) and (
                is_dataclass(value) or issubclass(value, Enum)
            ):
                types[value.__module__ + "." + value.__name__] = value
    return MappingProxyType(types)


def encode(value):
    types = registry()
    key = type(value).__module__ + "." + type(value).__name__
    if isinstance(value, Enum):
        if key not in types:
            raise TypeError("unsupported enum")
        return {"enum": key, "value": value.value}
    if is_dataclass(value):
        if key not in types:
            raise TypeError("unsupported record")
        return {
            "type": key,
            "fields": {f.name: encode(getattr(value, f.name)) for f in fields(value)},
        }
    if isinstance(value, Mapping):
        return {"mapping": [[encode(k), encode(v)] for k, v in value.items()]}
    if isinstance(value, (tuple, list)):
        return {"tuple": [encode(v) for v in value]}
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise TypeError("unsupported evidence value")


def decode(value, types):
    if not isinstance(value, dict):
        return value
    if set(value) == {"enum", "value"}:
        cls = types.get(value["enum"])
        if cls is None or not issubclass(cls, Enum):
            raise ValueError("unsupported enum")
        return cls(value["value"])
    if set(value) == {"type", "fields"}:
        cls = types.get(value["type"])
        if cls is None or not is_dataclass(cls):
            raise ValueError("unsupported record")
        if set(value["fields"]) != {f.name for f in fields(cls)}:
            raise ValueError("missing/unknown contract fields")
        return cls(**{k: decode(v, types) for k, v in value["fields"].items()})
    if set(value) == {"tuple"}:
        return tuple(decode(v, types) for v in value["tuple"])
    if set(value) == {"mapping"}:
        return {decode(k, types): decode(v, types) for k, v in value["mapping"]}
    raise ValueError("invalid serialization tag")


def dump(record):
    return json.dumps(
        {"format": "idp-evidence-json:1", "contract": "11", "record": encode(record)},
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def load(payload):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("duplicate JSON key")
            result[k] = v
        return result

    envelope = json.loads(
        payload,
        object_pairs_hook=unique,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError("nonfinite JSON")
        ),
    )
    if (
        set(envelope) != {"format", "contract", "record"}
        or envelope["format"] != "idp-evidence-json:1"
        or envelope["contract"] != "11"
    ):
        raise ValueError("unsupported contract version")
    result = decode(envelope["record"], registry())
    if not is_dataclass(result):
        raise ValueError("evidence root must be an allowlisted record")
    return result
