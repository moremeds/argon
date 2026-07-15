"""Shared parity infrastructure for the chanlun TS->Python port.

Loads the committed TS golden fixture and provides a field-by-field comparator
that reports the FIRST divergent path (localizes a failure instead of dumping
the whole structure). Optional keys (level/resonant) treat "absent" == None.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uw_scan.chanlun.types import ChanlunBar

# tests/unit/chanlun/parity_helpers.py -> parents[3] == repo root
_GOLDEN_PATH = (
    Path(__file__).resolve().parents[3]
    / "web/tests/lib/fixtures/chanlunGoldenAapl.json"
)
GOLDEN: dict[str, Any] = json.loads(_GOLDEN_PATH.read_text())


def bars_from_golden() -> list[ChanlunBar]:
    return [
        ChanlunBar(time=b["time"], high=b["high"], low=b["low"], close=b["close"])
        for b in GOLDEN["bars"]
    ]


def assert_records_equal(
    golden: list[dict], actual: list[Any], fields: list[str], label: str
) -> None:
    """Field-by-field equality; raises naming the first divergent path.

    Non-vacuity first: the golden slice must be non-empty (a comparator that
    passes on two empty lists is worthless).
    """
    assert golden, f"{label}: golden slice is empty (non-vacuity violated)"
    assert len(actual) == len(golden), (
        f"{label}: length {len(actual)} != golden {len(golden)}"
    )
    for i, (g, a) in enumerate(zip(golden, actual)):
        for f in fields:
            gv = g.get(f, None)
            av = getattr(a, f, None)
            assert av == gv, (
                f"{label}[{i}].{f}: got {av!r} != golden {gv!r} "
                f"(record got={a!r} golden={g!r})"
            )
