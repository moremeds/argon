"""Unit tests for the gap-healer specs/registry (pure logic, no DB)."""

from __future__ import annotations

import typing
from datetime import date

from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    SEED_CAVEATS,
    AuditMode,
    DatasetRegistryEntry,
    eligible_tickers_for_date,
    registered_table_names,
    unregistered,
)

_ACTIVE = ["AAPL", "NVDA", "SPCX", "qqq"]  # mixed case on purpose


def test_spcx_excluded_before_listing_included_after() -> None:
    before = eligible_tickers_for_date(_ACTIVE, date(2026, 6, 16), SEED_CAVEATS)
    on_listing = eligible_tickers_for_date(_ACTIVE, date(2026, 6, 17), SEED_CAVEATS)
    assert "SPCX" not in before
    assert "SPCX" in on_listing
    # the SPCX caveat must not touch other tickers
    assert {"AAPL", "NVDA", "QQQ"} <= before


def test_eligibility_uppercases_and_passes_through_without_caveats() -> None:
    got = eligible_tickers_for_date(["aapl", "Nvda"], date(2026, 1, 2), ())
    assert got == {"AAPL", "NVDA"}


def test_every_registry_entry_has_valid_audit_mode() -> None:
    valid = set(typing.get_args(AuditMode))
    for e in REGISTRY:
        assert e.audit_mode in valid, f"{e.table_name}: {e.audit_mode}"


def test_excluded_entries_require_a_reason() -> None:
    for e in REGISTRY:
        if e.audit_mode == "excluded":
            assert e.reason, f"{e.table_name} is excluded without a reason"


def test_healable_entries_name_an_adapter_others_do_not_dispatch() -> None:
    for e in REGISTRY:
        if e.granularity != "none":
            # a dispatchable dataset must name a heal adapter and a provider
            assert e.healer_adapter, f"{e.table_name} has granularity but no adapter"
            assert e.provider != "none", f"{e.table_name} dispatches but provider=none"
        else:
            # non-dispatchable -> audit-only modes only
            assert e.audit_mode in {
                "freshness_only",
                "operational_state",
                "provenance",
                "research_artifact",
                "excluded",
                "strict_session",  # may be healable later; none today is fine
                "strict_ticker_date",
            }


def test_registry_table_names_are_unique() -> None:
    names = [e.table_name for e in REGISTRY]
    assert len(names) == len(set(names)), "duplicate table_name in REGISTRY"


def test_unregistered_finds_only_unknown_temporal_tables() -> None:
    registered = registered_table_names(REGISTRY)
    synthetic = {next(iter(registered)), "a_brand_new_table_with_created_at"}
    missing = unregistered(synthetic, REGISTRY)
    assert missing == ["a_brand_new_table_with_created_at"]


def test_unregistered_empty_when_all_present() -> None:
    sample = DatasetRegistryEntry("only_table", "g", "provenance")
    assert unregistered({"only_table"}, [sample]) == []


def test_every_healable_entry_has_a_wired_spec() -> None:
    # importing HEAL_SPECS is cheap: prod-job imports are lazy inside run fns
    from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS

    for e in REGISTRY:
        if e.granularity != "none":
            assert e.healer_adapter in HEAL_SPECS, (
                f"{e.table_name} dispatches via {e.healer_adapter!r} "
                "but no HealSpec is registered"
            )
