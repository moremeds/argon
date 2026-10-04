"""Fundamentals tier-1 observations and evidence lineage.

One contiguous slice of ``REGISTRY``; ``data_gap_registry`` concatenates the parts in the original build order.
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.data_gap_types import DatasetRegistryEntry


FUNDAMENTALS: list[DatasetRegistryEntry] = []


# Fundamentals tier-1 observations (migration 114). Spelled out rather than
# folded into an _entries list so the reasoning survives beside each entry.
FUNDAMENTALS.extend(
    [
        DatasetRegistryEntry(
            "fundamental_statement_obs",
            "fundamentals",
            # freshness_only, NOT strict_ticker_date. The strict denominator is
            # (eligible watchlist tickers x SESSIONS); this table's grain is
            # (ticker x fiscal QUARTER) over a universe that is deliberately not
            # the watchlist, so a strict audit would invent a ~250x gap that no
            # filing will ever fill.
            "freshness_only",
            date_col="period_end",
            ticker_col="ticker",
            # A statement row appears when a filing appears. There is no daily
            # expectation to be behind on.
            expected_frequency="event",
            provider="uw",
            # No adapter: healing is re-running the ingest job, which is
            # idempotent by content hash and cheap enough to run whole.
            granularity="none",
            healer_adapter=None,
            source_system="uw",
            retention_days=None,
            reason=(
                "quarterly filings over the fundamental universe (450 tickers as "
                "of 2026-08-18; it moves when the seeder runs), "
                "not the watchlist. Deliberately NOT wired to the healer: unlike "
                "scores/anchors this is a provider INGEST, and "
                "worker/jobs/fundamental_refresh explicitly does not ingest. "
                "Heal by running scripts/backfill/fundamental_ingest_backfill.py "
                "(insert-or-touch, safe to repeat) as a budgeted operator "
                "action, not on the nightly cron."
            ),
            reason_verified_on=date(2026, 8, 16),
        ),
        DatasetRegistryEntry(
            "fundamental_obs_availability",
            "fundamentals",
            # `provenance`, not freshness or strict. Its rows are DERIVED claims
            # about statement versions Argon already holds: there is no provider
            # to re-fetch from, no calendar spine to be short of, and nothing
            # arrives on a cadence. Its parent `fundamental_statement_obs` IS
            # provider-fed and carries its own entry; the child inherits none of
            # that, and a freshness reading here would only ever measure when the
            # last backfill ran.
            "provenance",
            date_col="recorded_at",
            ticker_col=None,
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="argon",
            retention_days=None,
            reason=(
                "derived availability evidence for statement content versions "
                "(migration 132). Append-only, never rewritten: a rule replay "
                "collides on (obs_id, claim_key) and writes nothing. A missing "
                "claim is repaired by re-running "
                "scripts/backfill/fundamental_observation_availability.py, which "
                "spends zero provider budget and is idempotent — an operator "
                "action, not a healer adapter. Runbook: "
                "docs/runbooks/fundamental-observation-availability.md"
            ),
            reason_verified_on=date(2026, 8, 24),
        ),
        DatasetRegistryEntry(
            "sec_filing_index",
            "fundamentals",
            # `provenance`. This mirrors SEC's own immutable filing record so a
            # `true_pit` claim stays falsifiable: the accession that licensed the
            # claim must be inspectable locally, not re-fetched from a host that
            # may be down. Not `strict`: filings arrive when companies file, and
            # a session spine would invent a gap for every non-filing day.
            "provenance",
            date_col="recorded_at",
            ticker_col="ticker",
            expected_frequency="event",
            # SEC is free and keyless. This must never enter the UW governor.
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="sec",
            retention_days=None,
            reason=(
                "SEC EDGAR periodic filings (migration 134), accession-keyed and "
                "immutable — a correction is a NEW accession, never an edit, so "
                "a replay collides and writes nothing. Repaired by re-running "
                "scripts/backfill/sec_publication_evidence.py --index, which "
                "spends zero provider budget. Not a healer adapter: there is no "
                "calendar spine to be short of. Runbook: "
                "docs/runbooks/fundamental-observation-availability.md"
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "sec_cik_map",
            "fundamentals",
            # `provenance` and deliberately mutable — unlike everything else in
            # this neighbourhood. It is current-state (which CIK does this ticker
            # mean TODAY), not evidence, so `DO UPDATE` is correct and a
            # freshness reading would only measure when the map was last pulled.
            "provenance",
            date_col="refreshed_at",
            ticker_col="ticker",
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="sec",
            retention_days=None,
            reason=(
                "ticker -> CIK from SEC company_tickers.json (migration 134). "
                "Rebuilt wholesale by the index refresh; a stale row costs one "
                "issuer's filings, not correctness, because sec_filing_index "
                "stores the ticker it was fetched under."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "fundamental_result_provenance",
            "fundamentals",
            # `provenance` — it IS the provenance. Derived links between results
            # and the observations they used or withheld; nothing arrives on a
            # cadence and there is no provider to be short of.
            "provenance",
            date_col="recorded_at",
            ticker_col=None,
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            retention_days=None,
            reason=(
                "typed provenance for fundamental_scores (migration 135). Written "
                "by the scoring job under engines whose validity policy is not "
                "'off'; v1 rows are deliberately NOT backfilled so their absence "
                "reads as 'legacy' rather than 'cited nothing'. Repaired by "
                "re-running the scoring job at zero provider spend."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "company_identity",
            "fundamentals",
            # `provenance`. Validity intervals, not a series: a row appears when
            # a classification CHANGES, so freshness would measure how often
            # names get reclassified, which is not a health signal.
            "provenance",
            date_col="recorded_at",
            ticker_col="ticker",
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            retention_days=None,
            reason=(
                "historized issuer identity — company_type/sector/CIK as validity "
                "intervals (migration 136). fundamental_company_type stays the "
                "current-state cache; this is the history behind it. Rebuilt by "
                "worker/jobs/fundamental_anchors.seed_company_types, which is "
                "idempotent (an unchanged reassignment writes no interval) and "
                "spends zero provider budget."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "fundamental_runs",
            "fundamentals",
            # `provenance` — the control plane. A run row records the QUESTION
            # asked of the engine; nothing arrives on a cadence and there is no
            # provider to be short of.
            "provenance",
            date_col="requested_at",
            ticker_col=None,
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="argon",
            retention_days=None,
            reason=(
                "fundamental run ledger (migration 137): scope, as-of, evidence "
                "policy, engine version, mode and counters for each engine run. "
                "Not healable — a missing run is a run that never happened, and "
                "inventing one would fabricate the provenance the report product "
                "reads. Wedged rows are cleared by cancel_stale(), not backfilled."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "fundamental_run_stages",
            "fundamentals",
            "provenance",
            date_col="started_at",
            ticker_col=None,
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="argon",
            retention_days=None,
            reason=(
                "per-stage state for a fundamental run (migration 137). Child of "
                "fundamental_runs and healed the same way it is: not at all."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "fundamental_dimensions",
            "fundamentals",
            # freshness_only for the same reason as fundamental_scores: the grain
            # is (ticker x knowledge QUARTER) over a non-watchlist universe, so a
            # session spine would invent a gap no filing will ever fill.
            "freshness_only",
            date_col="as_of",
            ticker_col="ticker",
            expected_frequency="event",
            provider="db",
            granularity="run_once",
            healer_adapter="fundamental_refresh",
            source_system="derived",
            reason=(
                "research-priority dimensions per score result (migration 138), "
                "each carrying its own spec-6.4 authority. Derived from "
                "fundamental_scores in the same pass; re-running the scoring job "
                "rebuilds them at zero provider spend."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "research_events",
            "fundamentals",
            # `provenance`. Derived from evidence Argon already holds; a missing
            # event is a derivation that has not run, not a provider gap.
            "provenance",
            date_col="first_known_at",
            ticker_col="ticker",
            expected_frequency="event",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            retention_days=None,
            reason=(
                "typed event ledger (migration 142), derived from "
                "sec_filing_index and fundamental_obs_violations by "
                "worker/jobs/research_events_derive. Idempotent on its identity "
                "key; re-run to repair, at zero provider spend."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "research_risk_facts",
            "fundamentals",
            "provenance",
            date_col="as_of",
            ticker_col="ticker",
            expected_frequency="event",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            retention_days=None,
            reason=(
                "deterministic risk facts (migration 142): an observed value "
                "against a threshold plus what a breach invalidates. Recomputed "
                "by research_events_derive; nothing to heal from a provider."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "research_reports",
            "fundamentals",
            # `provenance`. A report is an ANSWER, not observed data. A key with
            # no version is a question nobody asked; there is no provider from
            # which a missing report could be re-fetched.
            "provenance",
            date_col="created_at",
            ticker_col=None,
            expected_frequency="event",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            retention_days=None,
            reason=(
                "versioned research reports (migration 143). Append-only: a "
                "refresh publishes version N+1 beside N and nothing is ever "
                "rewritten, which is what makes an old version replayable. "
                "Re-assemble to produce a new version; a predecessor is never "
                "healed, only superseded."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "research_report_blocks",
            "fundamentals",
            "provenance",
            # No date column of its own: a block's clock is its report's
            # `created_at`, and giving it a second one would let a block read
            # fresh while the version it belongs to reads stale.
            date_col=None,
            ticker_col=None,
            expected_frequency="event",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="derived",
            retention_days=None,
            reason=(
                "report sections (migration 143), CASCADE children of "
                "research_reports. Each names its evidence or its derivation; "
                "a missing block is a report that was never assembled."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
        DatasetRegistryEntry(
            "research_event_classes",
            "fundamentals",
            "provenance",
            date_col="measured_on",
            ticker_col=None,
            expected_frequency="none",
            provider="none",
            granularity="none",
            healer_adapter=None,
            source_system="argon",
            retention_days=None,
            reason=(
                "the discovery gate, persisted (migration 142). One row per "
                "candidate event class with its live/killed verdict and the row "
                "count that decided it."
            ),
            reason_verified_on=date(2026, 8, 25),
        ),
    ]
)
