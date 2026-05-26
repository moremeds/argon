"""Canonical SHA-256 of the canary snapshot payload.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §9.0a.

Key invariants (v0.2 patch):
  - float and Decimal at the SAME value produce the SAME hash. Both go
    through a recursive normalizer that collapses to a 6-decimal string
    BEFORE json.dumps, so floats are never serialized as JSON numbers.
  - dict key order has no effect (sorted by the normalizer).
  - The ``_prior`` audit field is excluded.
  - Pinned hash test in tests/unit/storage/test_canary_payload_hash.py
    breaks loudly on any serialization-format change.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def _normalize(obj: Any) -> Any:
    """Recursive canonical normalizer. Output is JSON-safe with stable repr."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items()) if k != "_prior"}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, bool):
        return obj  # must check before int — bool is subclass of int
    if isinstance(obj, int):
        return obj
    if isinstance(obj, (float, Decimal)):
        # Quantize both to the same 6-decimal string repr.
        return format(Decimal(str(obj)), ".6f")
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    iso = getattr(obj, "isoformat", None)
    if callable(iso):
        return iso()
    raise TypeError(f"Object of type {type(obj)} is not normalizable")


def canonical_payload_hash(payload: dict) -> str:
    normalized = _normalize(payload)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
