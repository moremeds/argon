"""Row construction for the revenue-breakdown capture.

Rows are REAL UW `rev_breakdown` payloads, fetched 2026-08-18 and frozen — the
same fixtures the derivation tests read. Nothing here touches the network.

What is under test is the boundary between what the provider said and what the
immutable table is allowed to hold: a row that cannot be attributed to a period,
or that carries no figure, must be dropped rather than defaulted, and a payload
that repeats itself must not be able to conflict with itself inside one batch.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from uw_scan.fundamentals.statements import FIELD_MAP_VERSION
from uw_scan.worker.jobs.fundamental_concentration_capture import build_rows

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "fundamentals"


def _fixture_rows(ticker: str) -> list[dict]:
    return json.loads((FIXTURES / f"rev_breakdown_{ticker}.json").read_text())["rows"]


def test_real_payload_builds_one_row_per_distinct_assertion():
    raw = _fixture_rows("nvda")
    rows = build_rows("NVDA", raw)

    # Nothing invented and nothing silently duplicated: every built row traces to
    # a fixture row, and the count can only shrink (drops + dedupe), never grow.
    assert 0 < len(rows) <= len(raw)
    assert {r["ticker"] for r in rows} == {"NVDA"}
    assert {r["source"] for r in rows} == {"uw"}
    assert {r["payload_version"] for r in rows} == {FIELD_MAP_VERSION}
    assert all(isinstance(r["report_date"], date) for r in rows)
    assert all(isinstance(r["axis"], list) for r in rows)


def test_identity_is_unique_within_one_payload():
    """The table's UNIQUE key must not be violable by a single capture.

    `ON CONFLICT DO UPDATE` cannot touch the same row twice inside one command,
    so a provider repeating an assertion must collapse before it reaches the DB.
    """
    rows = build_rows("NVDA", _fixture_rows("nvda"))
    keys = {(r["report_date"], r["rev_group"], r["content_hash"]) for r in rows}
    assert len(keys) == len(rows)


def test_repeated_assertion_collapses_to_one_row():
    raw = _fixture_rows("avgo")
    doubled = build_rows("AVGO", raw + raw)
    assert len(doubled) == len(build_rows("AVGO", raw))


def test_row_without_a_period_or_a_figure_is_dropped():
    """NOT NULL columns, and a fabricated default in an observation table is
    worse than an absent row — it asserts a figure the filer never reported."""
    assert build_rows("NVDA", [{"value": "1", "rev_group": "segment"}]) == []
    assert build_rows("NVDA", [{"report_date": "2026-01-25", "value": None}]) == []
    assert build_rows("NVDA", [{"report_date": "not-a-date", "value": "1"}]) == []
    assert build_rows("NVDA", [{"report_date": "2026-01-25", "value": "x"}]) == []


def test_envelope_fields_do_not_change_identity():
    """The tier-1 bug, re-tested here: a refetch that only re-stamps the
    provider's own bookkeeping timestamps must hash the same."""
    base = {
        "report_date": "2026-01-25",
        "rev_group": "segment",
        "field": "us-gaap:Revenues",
        "axis": ["us-gaap:StatementBusinessSegmentsAxis"],
        "members": ["nvda:ComputeAndNetworkingMember"],
        "value": "39100000000",
    }
    refetched = {
        **base,
        "inserted_at": "2026-05-21T06:58:08Z",
        "updated_at": "2026-08-11T03:58:32Z",
    }
    assert (
        build_rows("NVDA", [base])[0]["content_hash"]
        == (build_rows("NVDA", [refetched])[0]["content_hash"])
    )


def test_a_changed_figure_does_change_identity():
    base = {
        "report_date": "2026-01-25",
        "rev_group": "segment",
        "axis": ["us-gaap:StatementBusinessSegmentsAxis"],
        "members": ["nvda:ComputeAndNetworkingMember"],
        "value": "39100000000",
    }
    restated = {**base, "value": "39200000000"}
    assert (
        build_rows("NVDA", [base])[0]["content_hash"]
        != (build_rows("NVDA", [restated])[0]["content_hash"])
    )
