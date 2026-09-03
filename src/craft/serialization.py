"""Deterministic serialization and SM3 digests for CRAFT protocol objects."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, TypeAlias, cast

from gmssl import func, sm3  # type: ignore[import-untyped]
from pydantic import BaseModel

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _format_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def to_jsonable(value: Any) -> JsonValue:
    """Convert supported Python values into a deterministic JSON tree."""
    if isinstance(value, BaseModel):
        return cast(JsonValue, value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, set | frozenset):
        items = [to_jsonable(item) for item in value]
        return sorted(items, key=canonical_json)
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return cast(JsonScalar, value.value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bool | str) or value is None:
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float values cannot be canonicalized.")
        return value

    raise TypeError(f"Unsupported value for canonical JSON: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Serialize a value as stable JSON suitable for hashing and signing."""
    return json.dumps(
        to_jsonable(value),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_json_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sm3_digest_hex(payload: bytes | str) -> str:
    """Return an SM3 hex digest for raw bytes or UTF-8 text."""
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return sm3.sm3_hash(func.bytes_to_list(data))


def canonical_digest_hex(value: Any) -> str:
    """Return the SM3 digest of a canonical JSON representation."""
    return sm3_digest_hex(canonical_json_bytes(value))
