"""A per_ticker_* adapter only ever fires on a strict_* dataset."""

from __future__ import annotations

from uw_scan.reports.data_gap_healer import REGISTRY
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS


def test_every_registered_adapter_resolves() -> None:
    unknown = sorted(
        f"{e.table_name} -> {e.healer_adapter}"
        for e in REGISTRY
        if e.healer_adapter and e.healer_adapter not in HEAL_SPECS
    )
    assert not unknown, f"registry names adapters that do not exist: {unknown}"


def test_no_per_ticker_adapter_on_a_non_strict_dataset() -> None:
    """The healer has two channels and `granularity` picks one:

      run_once / run_once_lookback -> _refresh_targets -> run_refresh_adapters
        (fires regardless of audit_mode)
      per_ticker_date / per_ticker_range -> execute_run over GAP ITEMS
        (and only strict_* audit modes produce gap items)

    So a per_ticker_* adapter on a freshness_only dataset is never dispatched —
    silently, with no error, while the policy doc shows it as covered.
    """
    dead = []
    for e in REGISTRY:
        if not e.healer_adapter:
            continue
        spec = HEAL_SPECS.get(e.healer_adapter)
        if spec is None:
            continue  # covered by the test above
        if spec.granularity in ("per_ticker_date", "per_ticker_range"):
            if not e.audit_mode.startswith("strict"):
                dead.append(f"{e.table_name} ({e.audit_mode} + {spec.granularity})")
    assert not dead, (
        "these adapters can never run — promote the dataset to a strict audit "
        f"mode or give it a run_once* adapter: {dead}"
    )


def test_registry_granularity_matches_its_adapter() -> None:
    """The registry's own granularity must agree with the spec's, or
    _refresh_targets enrols (or skips) the wrong datasets."""
    mismatched = sorted(
        f"{e.table_name}: registry={e.granularity} "
        f"spec={HEAL_SPECS[e.healer_adapter].granularity}"
        for e in REGISTRY
        if e.healer_adapter
        and e.healer_adapter in HEAL_SPECS
        and e.granularity != HEAL_SPECS[e.healer_adapter].granularity
    )
    assert not mismatched, mismatched
