"""Canonical content identities for immutable macro evidence."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any


def macro_artifact_content_identity(
    *,
    raw_json: dict[str, Any] | list[Any] | None = None,
    raw_text: str | None = None,
    raw_bytes: bytes | None = None,
) -> tuple[str, int]:
    """Return the SHA-256 and byte length of one exact payload representation."""
    payload = canonical_macro_artifact_bytes(
        raw_json=raw_json,
        raw_text=raw_text,
        raw_bytes=raw_bytes,
    )
    return hashlib.sha256(payload).hexdigest(), len(payload)


def canonical_macro_artifact_bytes(
    *,
    raw_json: dict[str, Any] | list[Any] | None = None,
    raw_text: str | None = None,
    raw_bytes: bytes | None = None,
) -> bytes:
    """Serialize exactly one artifact representation to its hashed bytes."""
    candidates = (raw_json, raw_text, raw_bytes)
    if sum(value is not None for value in candidates) != 1:
        raise ValueError("exactly one raw payload representation is required")
    if raw_json is not None:
        return _canonical_json_bytes(raw_json)
    if raw_text is not None:
        return raw_text.encode("utf-8")
    assert raw_bytes is not None
    return raw_bytes


def macro_observation_content_hash(row: dict[str, Any]) -> str:
    """Hash the normalized fields that define one immutable observation."""
    value = _typed_value(row)
    record = {
        "artifact_id": int(row["artifact_id"]),
        "available_at": _canonical_instant(row["available_at"]),
        "domain": row["domain"],
        "frequency": row["frequency"],
        "parser_version": row["parser_version"],
        "period_end": _canonical_date(row["period_end"]),
        "published_at": _canonical_optional_instant(row.get("published_at")),
        "series_id": row["series_id"],
        "source": row["source"],
        "source_record_id": row["source_record_id"],
        "unit": row["unit"],
        "value": value,
    }
    return hashlib.sha256(_canonical_json_bytes(record)).hexdigest()


def macro_policy_semantic_hash(row: dict[str, Any]) -> str:
    """Identify a published policy fact independently of the bytes carrying it.

    Deliberately omits ``artifact_id`` and ``available_at``, which
    :func:`macro_observation_content_hash` includes.  Both are properties of our
    fetch, not of the publisher: re-fetching an unchanged release produces a new
    artifact row and, when the publisher declares no instant, a new availability
    clock -- neither of which makes it a new fact.  The stable release key, the
    publisher's own release instant, the normalized value, and the SEMANTIC
    parser version do define one, so a corrected reparse earns a new identity.

    ``release_key`` is required and is NOT ``source_record_id``: migration 115
    ties the latter to one artifact by composite foreign key, so a release
    served as both HTML and PDF has two of them and would otherwise split one
    committee decision into two facts.

    Must stay byte-identical to ``uw_scan.macro_policy_semantic_hash`` in SQL.
    """
    record = {
        "domain": row["domain"],
        "frequency": row["frequency"],
        "parser_version": row["parser_version"],
        "period_end": _canonical_date(row["period_end"]),
        "published_at": _canonical_optional_instant(row.get("published_at")),
        "release_key": row["release_key"],
        "series_id": row["series_id"],
        "source": row["source"],
        "unit": row["unit"],
        "value": _typed_value(row),
    }
    return hashlib.sha256(_canonical_json_bytes(record)).hexdigest()


def _typed_value(row: dict[str, Any]) -> dict[str, Any]:
    numeric = row.get("value_numeric")
    text = row.get("value_text")
    json_value = row.get("value_json")
    candidates = (numeric, text, json_value)
    if sum(value is not None for value in candidates) != 1:
        raise ValueError("exactly one typed observation value is required")
    if numeric is not None:
        return {"type": "numeric", "value": _canonical_decimal(numeric)}
    if text is not None:
        return {"type": "text", "value": text}
    return {"type": "json", "value": json_value}


def _canonical_decimal(value: Any) -> str:
    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal_value.is_finite():
        raise ValueError("numeric observation value must be finite")
    rendered = format(decimal_value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"-0", ""}:
        return "0"
    return rendered


def _canonical_optional_instant(value: Any) -> str | None:
    return None if value is None else _canonical_instant(value)


def _canonical_instant(value: Any) -> str:
    if not isinstance(value, datetime):
        raise ValueError("observation instant must be a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observation instant must be timezone-aware")
    return (
        value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
    )


def _canonical_date(value: Any) -> str:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError("period_end must be a date")
    return value.isoformat()


def _canonical_json_bytes(value: Any) -> bytes:
    return _canonical_json_text(value).encode("utf-8")


def _canonical_json_text(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return _canonical_decimal(Decimal(str(value)))
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_canonical_json_text(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return (
            "{"
            + ",".join(
                f"{_canonical_json_text(key)}:{_canonical_json_text(value[key])}"
                for key in sorted(value)
            )
            + "}"
        )
    raise ValueError(f"unsupported JSON value type: {type(value).__name__}")
