"""Per-block helpers of the /api/health assembly (moved from
``api/routers/health.py``, I-36). ``build_health`` in ``health_assembly`` is
the only caller outside tests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal


from uw_scan.config import Settings
from uw_scan.models.health import (
    JobDegraded,
    RecordHealthCheck,
    TradeInsightsAiProviderHealth,
    WorkerHealth,
)
from uw_scan.storage.health import apply_record_health_thresholds
from uw_scan.storage.repository import Repository

#: ``expected_market_cron_fires_between(crons, tz, *, start_utc, end_utc)``.
ExpectedFires = Callable[..., list[datetime]]


# /api/health reads the record-health counts the uw-0 `record_health_snapshot`
# job persists every 15 min (migration 151) — it never sweeps the tables itself.
# A snapshot older than 3 job intervals (or none at all) means the job is not
# running; the check then reads UNKNOWN (record_health_ok=None), not a PASS
# computed from frozen counts.
_RECORD_HEALTH_SNAPSHOT_MAX_AGE = timedelta(minutes=45)


class UnknownRecordTables(ValueError):
    """``record_tables`` named a table the snapshot does not hold. The router
    answers it as a 400 with this message as ``detail``, so this module stays
    free of the web framework."""


def _snapshot_record_health(
    repo: Repository,
    *,
    now_utc: datetime,
    watchlist_size: int,
    selected_tables: list[str] | None,
    min_coverage: float,
) -> tuple[dict, str | None, str | None]:
    """Record-health response fields from the persisted snapshot.

    Returns ``(fields, reason, note)``: ``reason`` is set when coverage fails
    (flips the top-level ok), ``note`` when the snapshot is stale or missing
    (informational only — a missing snapshot must not read as a false ALERT,
    and must not read as a PASS either, so the record check is UNKNOWN)."""
    snapshot = repo.list_record_health_snapshot(selected_tables)
    if selected_tables is not None and snapshot:
        unknown = sorted(set(selected_tables) - {row.table for row in snapshot})
        if unknown:
            raise UnknownRecordTables(
                f"unknown record health table(s): {', '.join(unknown)}"
            )
    computed = [row.computed_at for row in snapshot if row.computed_at is not None]
    newest = max(computed, default=None)
    if newest is None or now_utc - newest > _RECORD_HEALTH_SNAPSHOT_MAX_AGE:
        return (
            {
                "record_health_ok": None,
                "record_health": [],
                "record_health_computed_at": min(computed, default=None),
            },
            None,
            "record health snapshot stale/missing",
        )
    record_health = [
        RecordHealthCheck(
            table=row.table,
            window_start=row.window_start,
            expected_tickers=row.expected_tickers,
            expected_min_tickers=row.expected_min_tickers,
            actual_tickers=row.actual_tickers,
            expected_min_rows=row.expected_min_rows,
            actual_rows=row.actual_rows,
            latest_at=row.latest_at,
            ok=row.ok,
        )
        for row in apply_record_health_thresholds(
            snapshot, expected_tickers=watchlist_size, min_coverage=min_coverage
        )
    ]
    record_ok = all(check.ok for check in record_health)
    reason = None
    if not record_ok:
        failing = ", ".join(check.table for check in record_health if not check.ok)
        reason = f"record coverage below expected: {failing}"
    return (
        {
            "record_health_ok": record_ok,
            "record_health": record_health,
            "record_health_computed_at": min(computed),
        },
        reason,
        None,
    )


def _record_window_scans_expected(
    settings: Settings,
    *,
    now_utc: datetime,
    record_window_hours: float | None,
    expected_fires: ExpectedFires,
) -> bool:
    """True when >=1 full-scan cron was scheduled to fire within the record
    window. When False (weekend / holiday / overnight) no fresh coverage is
    expected, so record health should read healthy rather than ALERT. Extracted
    from the handler so tests can force the market session deterministically,
    independent of the wall-clock a CI run happens to land on.

    ``expected_fires`` is ``worker.schedule_expectations.
    expected_market_cron_fires_between``, passed in by the router so this
    module does not import ``worker``."""
    if record_window_hours is None:
        return False
    fires = expected_fires(
        settings.full_scan_crons,
        settings.rth_tz,
        start_utc=now_utc - timedelta(hours=record_window_hours),
        end_utc=now_utc,
    )
    return bool(fires)


def _parse_record_tables(record_tables: str | None) -> list[str] | None:
    if record_tables is None:
        return None
    selected = [item.strip() for item in record_tables.split(",") if item.strip()]
    return selected or None


def _provider_ai_health(
    *,
    repo: Repository,
    now_utc: datetime,
    provider: str,
    enabled: bool,
    expected_count: int,
    fresh_window: timedelta,
) -> "TradeInsightsAiProviderHealth":
    """Per-provider Trade Insights AI worker health.

    Looks up the provider-pinned heartbeat key (e.g. trade_insights_ai_tick_codex);
    falls back to the legacy key when the provider-pinned worker hasn't started
    yet. Healthiness is binary per pool — exact worker count isn't tracked yet.

    A provider whose kill switch is off expects ZERO workers. The worker-count
    setting describes pool width when the provider runs; it is not a claim that
    the provider runs at all. Reading it unconditionally reported codex/claude as
    0-of-2 healthy from the 2026-07-08 Docker cutover onward, because the
    containerized deployment deliberately runs neither (only DeepSeek survives —
    the CLI runners need subprocess + keychain OAuth) while
    TRADE_INSIGHTS_AI_{,CLAUDE_}ENABLED=false in /opt/argon/.env already said so.
    A health block that is permanently wrong trains the reader to ignore it.
    """
    pinned_key = f"trade_insights_ai_tick_{provider}"
    legacy_key = "trade_insights_ai_tick"
    heartbeats = repo.get_heartbeats([pinned_key, legacy_key])
    beat = heartbeats.get(pinned_key) or heartbeats.get(legacy_key)
    pool_alive = beat is not None and (now_utc - beat) < fresh_window
    depth = repo.count_queued_trade_insight_ai_analyses_by_provider(provider)
    expected = expected_count if enabled else 0
    return TradeInsightsAiProviderHealth(
        workers_expected=expected,
        workers_healthy=expected if pool_alive else 0,
        queued_depth=depth,
        last_beat_at=beat,
    )


def _worker_health_rows(
    *,
    repo: Repository,
    now_utc: datetime,
    uw_count: int,
    massive_count: int,
    ai_count: int,
) -> list[WorkerHealth]:
    expected_workers: list[tuple[str, Literal["uw", "massive"], int, str]] = []
    for role, count, label_prefix in (
        ("uw", uw_count, "UW"),
        ("massive", massive_count, "Massive"),
        ("ai", ai_count, "AI"),
    ):
        for index in range(max(0, count)):
            expected_workers.append(
                (f"{label_prefix} {index + 1}", role, index, f"worker:{role}:{index}")
            )

    heartbeats = repo.get_heartbeats(
        heartbeat_name for _, _, _, heartbeat_name in expected_workers
    )

    rows: list[WorkerHealth] = []
    for label, role, index, heartbeat_name in expected_workers:
        last_beat_at = heartbeats.get(heartbeat_name)
        rows.append(
            WorkerHealth(
                label=label,
                role=role,
                index=index,
                heartbeat_name=heartbeat_name,
                last_beat_at=last_beat_at,
                lag_seconds=(
                    (now_utc - last_beat_at).total_seconds()
                    if last_beat_at is not None
                    else None
                ),
            )
        )
    return rows


def _job_degraded(repo: Repository) -> list[JobDegraded]:
    """The 'succeeded but degraded' block: jobs whose latest run returned
    normally with part of its work missing.

    INFORMATIONAL ONLY — an entry here never flips ``ok``, never sets
    ``reason`` and never alerts. It also self-clears: a scan-run entry reads
    only the LATEST run, so the next clean run removes it, and a macro entry
    clears when the source's next successful upsert writes ``ok``.

    No new writes are made: every entry is read from a record the job already
    persists — ``scan_runs`` for the sentinel-ticker side-channel jobs
    (GRG thin data → ``status='degraded'``; discovery partial-DP → an 'ok'
    run whose run meta counts enriched candidates) and
    ``macro_source_status`` for the macro ingests.
    """
    out: list[JobDegraded] = []

    grg = repo.latest_scan_run_state("GRG")
    if grg is not None and grg["status"] == "degraded":
        out.append(
            JobDegraded(
                job_name="regime_grg_scan",
                record="scan_run",
                since=grg["finished_at"],
            )
        )

    discovery = repo.latest_scan_run_state("_DISCOVER")
    if discovery is not None and discovery["status"] == "ok":
        meta = (discovery["aggregates"] or {}).get("discovery") or {}
        candidates = meta.get("candidates_found") or 0
        enriched = meta.get("dp_enriched")
        # candidates_found counts post-top_n candidates, the same list the
        # enrichment loop attempts — enriched < candidates means at least one
        # DP fetch raised (a 'no_data' fetch still counts as enriched).
        if candidates and enriched is not None and enriched < candidates:
            out.append(
                JobDegraded(
                    job_name="discovery_scan",
                    record="scan_run",
                    since=discovery["finished_at"],
                    detail=f"dp {enriched}/{candidates} enriched",
                )
            )

    for row in repo.list_degraded_macro_sources():
        err = row["error_type"] or "degraded"
        msg = row["error_message"]
        out.append(
            JobDegraded(
                job_name=row["source"],
                record="macro_source",
                since=row["last_attempt_at"] or row["updated_at"],
                detail=err if not msg else f"{err}: {msg[:200]}",
                consecutive=row["consecutive_failures"],
            )
        )
    return out
