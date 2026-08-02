"""Which sessions the SPX density backfill is allowed to (re)write.

`origin` is not a recomputable field: it decides whether a cone counts toward the
prospective (out-of-sample) tally or the reconstructed (in-sample) one, and
`upsert_rows` overwrites it on conflict. So the selection rule is an integrity rule,
not a convenience — it gets a test of its own.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "spx_density_backfill",
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "backfill"
    / "spx_density_backfill.py",
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
select_sessions = _MOD.select_sessions

D = [date(2026, 7, d) for d in (24, 27, 28, 29, 30)]


def test_plain_run_skips_anything_already_written() -> None:
    assert select_sessions(D, existing={D[0], D[1]}, prospective=set()) == D[2:]


def test_force_reruns_reconstructed_sessions() -> None:
    """--force passes an empty `existing` — that is the whole point of the flag."""
    assert select_sessions(D, existing=set(), prospective=set()) == D


def test_force_still_refuses_to_touch_a_prospective_session() -> None:
    """The nightly job issued D[3] forward. Recomputing it would rewrite origin to
    'reconstructed' and move a real out-of-sample result into the in-sample tally."""
    got = select_sessions(D, existing=set(), prospective={D[3]})
    assert D[3] not in got
    assert got == [D[0], D[1], D[2], D[4]]


def test_prospective_wins_even_when_also_listed_as_existing() -> None:
    got = select_sessions(D, existing={D[0]}, prospective={D[0], D[4]})
    assert got == [D[1], D[2], D[3]]


def test_empty_candidates_is_not_an_error() -> None:
    assert select_sessions([], existing=set(), prospective=set()) == []
