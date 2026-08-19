"""Every registered dataset has a disposition. No silent gaps. (Task 10)"""

from __future__ import annotations

from uw_scan.reports.data_gap_healer import BY_DESIGN_AUDIT_MODES, REGISTRY


def test_every_dataset_is_dispositioned() -> None:
    """One of exactly three states, for all 143 entries:
      - by-design existence-only, or
      - has a heal adapter, or
      - carries a dated, measured refusal.
    Anything else is a dataset nobody decided about.
    """
    undecided = sorted(
        e.table_name
        for e in REGISTRY
        if e.audit_mode not in BY_DESIGN_AUDIT_MODES
        and not e.healer_adapter
        and e.reason_verified_on is None
    )
    assert not undecided, f"no recorded decision for: {undecided}"


def test_the_coverage_ledger_numbers_are_still_true() -> None:
    """The plan's ledger table is a claim; this is the claim as an assertion.

    Deliberately brittle: a new daily dataset fails this and points at the
    ledger. A silently-growing registry is how the healer reached 45
    undocumented refusals in the first place.
    """
    scoped = [
        e
        for e in REGISTRY
        if e.audit_mode not in BY_DESIGN_AUDIT_MODES
        and e.expected_frequency in ("equity_session", "daily")
    ]
    assert len(scoped) == 59, (
        f"the daily/equity_session scope moved to {len(scoped)}; update the "
        "Coverage Ledger in docs/superpowers/plans/"
        "2026-08-16-healer-coverage-hardening.md"
    )
    unwired = [e for e in scoped if not e.healer_adapter and not e.reason_verified_on]
    assert not unwired, [e.table_name for e in unwired]
