"""Scanner state, operational provenance, and macro-evidence datasets.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


STATE_PROVENANCE: list[DatasetRegistryEntry] = [
    # --- scanner / page state (freshness) ---
    DatasetRegistryEntry(
        "watchlist_card",
        "scanner_state",
        "freshness_only",
        ticker_col="ticker",
        expected_frequency="liveness",
        reason=(
            "live state, not a time series: a row asserts what is true NOW "
            "and is rewritten in place. A missing row means the condition does "
            "not hold, not that history was lost — there is nothing to "
            "backfill."
        ),
        reason_verified_on=date(2026, 8, 16),
    ),
    # --- operational / provenance (audit only, never healed) ---
    DatasetRegistryEntry(
        "pipeline_benchmark_snapshots",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_freshness_snapshots",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "agent_runs",
        "operational_provenance",
        "provenance",
        date_col="run_day",
        ticker_col=None,
        expected_frequency="event",
        provider="none",
        granularity="none",
        healer_adapter=None,
        source_system="helium",
        reason=(
            "agent run ledger (migration 148), pushed by helium over "
            "POST /api/agent-runs and append-only: a re-push of the same run "
            "is a no-op and a re-run lands as version N+1 beside N. Argon "
            "never fetches these; a missing (tenant, kind, run_day) is a run "
            "that never happened, and fabricating one would forge the record "
            "the Flash page replays. Re-push from helium's transcript store."
        ),
        reason_verified_on=date(2026, 9, 4),
    ),
    # Immutable macro evidence substrate (migration 115). These rows preserve
    # exact source payloads and publication-time observations for PIT replay;
    # gap healing must never rewrite or synthesize their history.
    DatasetRegistryEntry(
        "macro_source_artifacts",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="multi-source",
    ),
    DatasetRegistryEntry(
        "macro_observations",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="multi-source",
    ),
    DatasetRegistryEntry(
        "company_sector",
        "fundamentals",
        "operational_state",
        expected_frequency="liveness",
        provider="uw",
        source_system="uw",
        reason=(
            "a per-ticker cache of the vendor's current sector, used only to route "
            "company_type. `fetched_at` records when we last ASKED, not when a fact "
            "was true, so there is no per-date series to be missing and nothing to "
            "backfill; a stale row self-heals on the next monthly fill and a name "
            "absent from it simply routes to the pooled default, exactly as before "
            "the table existed"
        ),
    ),
    DatasetRegistryEntry(
        "macro_source_status",
        "macro_evidence",
        "operational_state",
        expected_frequency="liveness",
        source_system="multi-source",
        reason=(
            "current per-source ingestion health; not immutable release history and "
            "not backfillable"
        ),
    ),
    DatasetRegistryEntry(
        "macro_release_ingest_status",
        "macro_evidence",
        "operational_state",
        expected_frequency="liveness",
        source_system="multi-source",
        reason=(
            "latest ingest outcome per individual release; describes our attempts, "
            "never what the publisher said, so it is not a substitute for immutable "
            "release evidence and must not be backfilled"
        ),
    ),
    DatasetRegistryEntry(
        "macro_observation_artifacts",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="multi-source",
        reason=(
            "immutable lineage linking an observation to the exact artifacts that "
            "witness it; synthesizing a link would fabricate evidence"
        ),
    ),
    # Domain states and their evidence (migration 125). A state records what we
    # concluded at an instant and which observations we concluded it from. Recomputing
    # one is a job, never a heal: the database refuses rewrites outright, and a healer
    # that invented a missing state would be asserting a past decision nobody made.
    DatasetRegistryEntry(
        "macro_domain_states",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="derived",
        reason=(
            "immutable record of a decision at an instant; recomputation belongs to the "
            "state job, which stamps its own computed_at, and the write guard rejects "
            "any edit to a stored answer"
        ),
    ),
    # The context snapshot and its domain edges (migration 130). A snapshot is the same
    # kind of object as the states it holds -- an immutable record of what we concluded at
    # an instant -- so it heals the same way they do, which is not at all. Worse: a healer
    # that invented a missing snapshot would be asserting that four domains once agreed,
    # which is precisely the claim this table exists to be able to REFUSE.
    DatasetRegistryEntry(
        "macro_context_snapshots",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="derived",
        reason=(
            "immutable record of a four-domain composition at an instant; reassembly "
            "belongs to the snapshot job, and inventing one would assert a coherence "
            "that was never observed"
        ),
    ),
    DatasetRegistryEntry(
        "macro_context_snapshot_domains",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="derived",
        reason=(
            "edges of an immutable snapshot; they are written once with their parent and "
            "have no independent existence to heal"
        ),
    ),
    # The evidence-invalidation overlay (migration 131). It is the record that a HUMAN
    # reviewed accepted evidence and condemned it. A healer that invented a row here would
    # be asserting a review nobody performed -- and unlike most fabrications this one
    # SUBTRACTS: an invented invalidation silently removes real evidence from every state.
    DatasetRegistryEntry(
        "macro_evidence_invalidations",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="derived",
        reason=(
            "a reviewer's judgement that accepted evidence was later found bad; there is "
            "no source to re-fetch it from, and an invented row would remove real "
            "observations from every point-in-time read after its instant"
        ),
    ),
    DatasetRegistryEntry(
        "macro_domain_state_evidence",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="derived",
        reason=(
            "immutable observation-level lineage for a state; a synthesized row would "
            "claim a state stood on evidence it never saw"
        ),
    ),
    DatasetRegistryEntry(
        "macro_domain_state_dependencies",
        "macro_evidence",
        "provenance",
        expected_frequency="none",
        source_system="derived",
        reason=(
            "immutable state-level lineage (migration 128); a synthesized edge would "
            "claim one domain consulted another's answer when it never did, which is a "
            "worse failure than a missing edge because it reads as provenance"
        ),
    ),
    DatasetRegistryEntry(
        "ws_consumer_state",
        "operational_provenance",
        "operational_state",
        expected_frequency="liveness",
    ),
    # the healer's own bookkeeping tables (registered so discovery stays honest)
    DatasetRegistryEntry(
        "data_gap_runs",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_gap_items",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_gap_caveats",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "data_gap_dataset_registry",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "watchlist_ticker_events",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    DatasetRegistryEntry(
        "chanlun_signal_events",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
    # Ephemeral same-day UW fetch dedupe cache (#225): rows live one trading day
    # and are pruned; there is nothing to backfill or heal.
    DatasetRegistryEntry(
        "uw_fetch_memo",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="ephemeral same-day fetch dedupe cache; pruned daily, nothing to backfill/heal",
    ),
    # Ops-hardening job-failure streaks (#C12): per-job consecutive-failure
    # counters maintained live by the scheduler listener — not a time series,
    # nothing to backfill or heal.
    DatasetRegistryEntry(
        "job_failures",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="live per-job failure-streak state; scheduler-maintained, nothing to backfill/heal",
    ),
    # Schema-ready marker (migration 158, I-05): one row written by migrate_runner
    # after a full apply; workers gate on it. Not a time series.
    DatasetRegistryEntry(
        "schema_version",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="one-row schema-ready marker written by migrate_runner after a full apply; nothing to backfill/heal",
    ),
    DatasetRegistryEntry(
        "record_health_snapshot",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="latest per-table record-health counts, overwritten every 15 min by the record_health_snapshot job; no history to backfill/heal",
    ),
    # Research cohort membership (migration 110). Caught by the temporal-table
    # heuristic only because `selected_on` is a date column, but there is no
    # series here: one row per (cohort, ticker) recording when that ticker was
    # selected. The cohort's actual time series is option_surface_grid_daily,
    # which is registered above and healed on its own terms.
    DatasetRegistryEntry(
        "research_universe",
        "operational_provenance",
        "excluded",
        ticker_col="ticker",
        expected_frequency="none",
        reason="cohort membership, not a time series; selected_on is a point-in-time tag, not a cadence",
    ),
    # Industry-chain membership (migration 113). Same shape as research_universe
    # above: a dimension, not a series. One row per (ticker, chain); `added_at`
    # is an audit stamp of when the membership was seeded, not an observation
    # date, so there is no cadence to be late for and no date to backfill. It is
    # caught by the temporal-table heuristic purely on the `%_at` column-name
    # match. The chains' actual time series are the per-ticker tables the
    # members already appear in, each registered on its own terms.
    DatasetRegistryEntry(
        "watchlist_chain",
        "operational_provenance",
        "excluded",
        ticker_col="ticker",
        expected_frequency="none",
        reason="chain membership, not a time series; added_at is a seed stamp, not a cadence",
    ),
    # Agent MCP tables (migrations 153/154): auth tokens, an access audit log,
    # and the agent-facing event stream + replay cursor. All are argon's own
    # operational records — none is a market-data series, so there is nothing
    # to backfill or heal.
    DatasetRegistryEntry(
        "mcp_token",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="bearer-token registry for the agent MCP server; auth state, not a time series",
    ),
    DatasetRegistryEntry(
        "mcp_access_log",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="per-call MCP audit log; append-only operational provenance, nothing to backfill/heal",
    ),
    DatasetRegistryEntry(
        "mcp_event",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="append-only agent event stream with its own 30-day retention job; not market data",
    ),
    DatasetRegistryEntry(
        "mcp_event_cursor",
        "operational_provenance",
        "excluded",
        expected_frequency="none",
        reason="per-token replay cursor for get_events; consumer state, not a time series",
    ),
]
