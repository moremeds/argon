"""Refusals must be measured, not assumed (E5).

28 options_chain tables carried one copy-pasted reason string that was never
probed. Round 1 proved it false for 13 of them. reason_verified_on makes the
distinction structural: a refusal either carries the date somebody actually
probed the provider, or it is an untested assumption and says so.
"""

from __future__ import annotations

from uw_scan.reports.data_gap_healer import BY_DESIGN_AUDIT_MODES, REGISTRY

# Every table round 1 healed by hand, plus every one whose entrypoint was
# already date-aware. None may still claim "no auto-backfill".
PROVEN_HEALABLE = {
    "index_ohlc_daily",  # -> index_ohlc (Task 6)
    "vol_index_daily",  # -> vol_index_lake
    "uw_dark_lit_flow_prints",  # -> uw_alpha_dark_lit
    "uw_intraday_option_flow_bars",  # -> uw_alpha_intraday_flow
    "cri_snapshots",  # -> cri_recover           (Task 4)
    "vcg_snapshots",  # -> vcg_recover           (Task 4)
    "canary_snapshots",  # -> canary_recover     (Task 4)
    "market_tide_snapshots",  # -> market_tide   (Task 4)
    "top_net_impact_snapshots",  # -> top_net_impact (Task 4)
    "technical_daily",  # -> technical_daily     (Task 4)
    "corporate_actions",  # -> corporate_actions (Task 4)
    "massive_fundamentals",  # -> massive_fundamentals (Task 4)
    "grg_snapshots",  # -> grg_as_of             (Task 5)
}

STALE_ASSUMPTION = "UW-retention/event-log shaped"


def test_proven_healable_tables_have_an_adapter() -> None:
    by_name = {e.table_name: e for e in REGISTRY}
    missing = sorted(t for t in PROVEN_HEALABLE if by_name[t].healer_adapter is None)
    assert not missing, f"healed by hand in round 1 but still refused: {missing}"


def test_no_proven_table_still_carries_the_stale_assumption() -> None:
    offenders = sorted(
        e.table_name
        for e in REGISTRY
        if e.table_name in PROVEN_HEALABLE and STALE_ASSUMPTION in (e.reason or "")
    )
    assert not offenders


def test_every_refusal_is_dated() -> None:
    """A provider='none' dataset must say WHEN the refusal was measured.

    Cadence-independent on purpose: the daily scope was the coverage ledger's
    boundary, not a statement that weekly/monthly/liveness entries may carry
    undocumented assumptions. All 13 liveness entries had EMPTY reasons.
    """
    undated = sorted(
        e.table_name
        for e in REGISTRY
        if e.provider == "none"
        and e.audit_mode not in BY_DESIGN_AUDIT_MODES
        and e.reason_verified_on is None
    )
    assert not undated, (
        "undated refusals are assumptions; probe the provider and stamp the "
        f"date, or wire an adapter: {undated}"
    )
