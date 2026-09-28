"""Pin the divergent hash-exclusion policy between the two AI lanes.

Both lanes strip the same volatile bookkeeping keys before hashing, but
trade_blast additionally excludes the framework-view freshness fields
`age_days` and `stale` so its `analysis_input_hash` stays stable across
calendar days when the underlying data vintage is unchanged. The shared
`_strip_volatile_for_hash` traversal takes each lane's exclusion set as a
parameter — these tests guard against the two sets being unified.
"""

from __future__ import annotations

import copy

from uw_scan.reports import trade_blast, trade_insights_ai

_INPUT = {
    "prompt_version": "test",
    "nested": {
        "value": 1,
        "freshness": {"age_days": 3, "stale": False},
        "generated_at": "2026-01-01T00:00:00Z",
    },
    "rows": [{"strike": "100", "stale": False, "age_days": 3}],
}


def _mutated(input_: dict) -> dict:
    changed = copy.deepcopy(input_)
    changed["nested"]["freshness"]["age_days"] = 30
    changed["nested"]["freshness"]["stale"] = True
    changed["rows"][0]["stale"] = True
    changed["rows"][0]["age_days"] = 30
    return changed


def test_blast_hash_ignores_age_days_and_stale_at_any_depth():
    blast_hash = trade_blast.hash_trade_insights_ai_analysis_input
    assert blast_hash(_INPUT) == blast_hash(_mutated(_INPUT))


def test_insights_hash_observes_age_days_and_stale():
    insights_hash = trade_insights_ai.hash_trade_insights_ai_analysis_input
    assert insights_hash(_INPUT) != insights_hash(_mutated(_INPUT))


def test_both_lanes_ignore_common_volatile_keys():
    for hash_fn in (
        trade_blast.hash_trade_insights_ai_analysis_input,
        trade_insights_ai.hash_trade_insights_ai_analysis_input,
    ):
        changed = copy.deepcopy(_INPUT)
        changed["nested"]["generated_at"] = "2026-01-02T00:00:00Z"
        changed["analysis_input_hash"] = "self-referential"
        changed["nested"]["as_of"] = "2026-01-02"
        assert hash_fn(_INPUT) == hash_fn(changed)
