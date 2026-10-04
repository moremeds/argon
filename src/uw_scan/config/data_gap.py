"""Nightly data gap healer and freshness autoheal (D6 concern group: data_gap)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from uw_scan.config._env import EnvVar


class DataGapSettings(BaseModel):
    # Nightly data gap healer (8pm ET, after UW quota reset). Only UW is capped.
    data_gap_healer_enabled: Annotated[bool, EnvVar("DATA_GAP_HEALER_ENABLED")] = False
    data_gap_healer_cron_et: Annotated[str, EnvVar("DATA_GAP_HEALER_CRON_ET")] = (
        "0 20 * * 0-5"  # 20:00 ET Mon-Sat (APScheduler Mon=0)
    )
    data_gap_healer_datasets: Annotated[str, EnvVar("DATA_GAP_HEALER_DATASETS")] = (
        ""  # empty = all healable datasets
    )
    data_gap_healer_start: Annotated[str, EnvVar("DATA_GAP_HEALER_START")] = (
        "2026-01-01"
    )
    data_gap_healer_max_uw_calls: Annotated[
        int, EnvVar("DATA_GAP_HEALER_MAX_UW_CALLS")
    ] = 20000
    # The UW budget day runs 20:00 ET -> 20:00 ET and the healer fires AT 20:00, so a
    # run bills the day that FOLLOWS it. Friday's and Saturday's runs therefore bill to
    # Saturday and Sunday -- no session, so the live pool needs nothing and the healer
    # can take most of the account. Sunday is deliberately NOT scheduled: that run would
    # bill Monday, a full trading day. Measured 2026-08 on UW's own counter: weekday
    # burn 64k-82k against a 105k guard, weekends ~1k.
    data_gap_healer_max_uw_calls_weekend: Annotated[
        int, EnvVar("DATA_GAP_HEALER_MAX_UW_CALLS_WEEKEND")
    ] = 90000
    # No single dataset may take more than this share of one night's UW cap.
    # execute_run groups items by dataset and runs each group to completion
    # against one shared budget, so the first big UW spender in REGISTRY drains
    # the whole night and every dataset behind it records skipped_budget. 0.4
    # lets a large backfill make real progress (~7 nights for a 4.2k-item
    # surface backlog at 12k/night) without blocking everything else for the
    # week. Set to 1.0 to restore the old drain-it-all behaviour.
    data_gap_healer_dataset_share: Annotated[
        float, EnvVar("DATA_GAP_HEALER_DATASET_SHARE")
    ] = 0.4
    # Consecutive nightly no_data verdicts before the scope is auto-caveated.
    # The audit is a set-difference against the real table, so a date the
    # provider genuinely cannot serve reappears as a fresh item and is
    # re-attempted at full cost every night, forever. 0 disables.
    data_gap_healer_no_data_caveat_after: Annotated[
        int, EnvVar("DATA_GAP_HEALER_NO_DATA_CAVEAT_AFTER")
    ] = 3
    # Freshness-monitor autoheal: a same-night "second chance" trigger for a
    # table the 20:00 ET gap-healer left frozen (budget exhaustion / a
    # transient failure) -- NOT a substitute for the nightly job, which
    # already audits+heals every registered dataset. Off by default; a
    # circuit breaker stops re-triggering a table frozen N nights running
    # (a real, unfixable block -- missing credential, licensed data source)
    # so it doesn't burn budget forever on something a heal can't solve.
    data_freshness_autoheal_enabled: Annotated[
        bool, EnvVar("DATA_FRESHNESS_AUTOHEAL_ENABLED")
    ] = False
    data_freshness_autoheal_circuit_breaker_nights: Annotated[
        int, EnvVar("DATA_FRESHNESS_AUTOHEAL_CIRCUIT_BREAKER_NIGHTS")
    ] = 3
    data_freshness_autoheal_max_uw_calls: Annotated[
        int, EnvVar("DATA_FRESHNESS_AUTOHEAL_MAX_UW_CALLS")
    ] = 500
