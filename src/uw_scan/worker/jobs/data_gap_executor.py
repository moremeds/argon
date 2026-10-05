"""Gap-item executor for the data gap healer.

`execute_run` claims a run's resumable items, dispatches each dataset on its
spec's granularity, and verifies every item against the dataset's own table
before marking it healed; an unverified item is recorded as no_data.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date

from psycopg import sql as psql

from uw_scan.reports.data_gap_healer import detect_col
from uw_scan.reports.data_gap_types import (
    _DATE_COL_PREFERENCE,
    _TICKER_COL_PREFERENCE,
    Caveat,
    DatasetRegistryEntry,
)
from uw_scan.worker.jobs.data_gap_adapters import HEAL_SPECS
from uw_scan.worker.jobs.data_gap_heal_context import HealContext, HealSpec, _beat
from uw_scan.worker.jobs.data_gap_telemetry import (
    STAGE_ADAPTER,
    STAGE_CLAIMED,
    STAGE_MARKED,
    STAGE_PROVIDER_RETURNED,
    HealHeartbeat,
)

logger = logging.getLogger(__name__)


# --- generic verifier ------------------------------------------------------


def _verify_covered(
    ctx: HealContext, entry: DatasetRegistryEntry, ticker: str | None, data_date: date
) -> bool:
    table = entry.table_name
    date_col = entry.date_col or detect_col(
        ctx.repo.conn, ctx.schema, table, _DATE_COL_PREFERENCE
    )
    if date_col is None:
        return False
    tcol = None
    if ticker:
        tcol = entry.ticker_col or detect_col(
            ctx.repo.conn, ctx.schema, table, _TICKER_COL_PREFERENCE
        )
    parts = [
        psql.SQL("SELECT 1 FROM {tbl} WHERE {dcol} = %s").format(
            tbl=psql.Identifier(ctx.schema, table),
            dcol=psql.Identifier(date_col),
        )
    ]
    args: list[object] = [data_date]
    if tcol and ticker:
        parts.append(
            psql.SQL("AND UPPER({tcol}) = %s").format(tcol=psql.Identifier(tcol))
        )
        args.append(ticker.upper())
    parts.append(psql.SQL("LIMIT 1"))
    query = psql.SQL(" ").join(parts)
    with ctx.repo.conn.cursor() as cur:
        cur.execute(query, args)
        return cur.fetchone() is not None


# --- executor --------------------------------------------------------------


def _dispatch_per_ticker_date(ctx, entry, spec, items, outcome) -> None:
    exhausted = False
    for it in items:
        if exhausted or not ctx.budget.can_spend(spec.provider, spec.est_per_item):
            ctx.gap.mark_item_skipped_budget(it["id"])
            outcome["skipped_budget"] += 1
            exhausted = True
            continue
        _beat(ctx, STAGE_ADAPTER, entry, it)
        try:
            spec.run(ctx, it["ticker"], it["data_date"])
            ctx.budget.record(spec.provider, spec.est_per_item)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "heal failed %s %s: %s", entry.table_name, it["scope_key"], repr(exc)
            )
            ctx.gap.mark_item_failed(it["id"], last_error=repr(exc)[:500])
            outcome["failed"] += 1
            continue
        _beat(ctx, STAGE_PROVIDER_RETURNED, entry, it)
        _verify_and_mark(ctx, entry, spec, it, outcome)
        _beat(ctx, STAGE_MARKED, entry, it)


def _dispatch_per_ticker_range(ctx, entry, spec, items, outcome) -> None:
    by_ticker: dict[str, list[dict]] = defaultdict(list)
    for it in items:
        by_ticker[it["ticker"]].append(it)
    for ticker, tk_items in by_ticker.items():
        dates = [it["data_date"] for it in tk_items if it["data_date"]]
        if not dates or not ctx.budget.can_spend(spec.provider, spec.est_per_item):
            for it in tk_items:
                ctx.gap.mark_item_skipped_budget(it["id"])
                outcome["skipped_budget"] += 1
            continue
        _beat(ctx, STAGE_ADAPTER, entry, tk_items[0], span=len(tk_items))
        try:
            spec.run(ctx, ticker, min(dates), max(dates))
            ctx.budget.record(spec.provider, spec.est_per_item)
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "heal failed %s %s: %s", entry.table_name, ticker, repr(exc)
            )
            for it in tk_items:
                ctx.gap.mark_item_failed(it["id"], last_error=repr(exc)[:500])
                outcome["failed"] += 1
            continue
        _beat(ctx, STAGE_PROVIDER_RETURNED, entry, tk_items[0], span=len(tk_items))
        for it in tk_items:
            _verify_and_mark(ctx, entry, spec, it, outcome)
            _beat(ctx, STAGE_MARKED, entry, it)


def _dispatch_run_once(ctx, entry, spec, items, outcome) -> None:
    dates = [it["data_date"] for it in items if it["data_date"]]
    _beat(ctx, STAGE_ADAPTER, entry, items[0] if items else None, span=len(items))
    try:
        if spec.granularity == "run_once_lookback":
            lookback = max(1, (ctx.today - min(dates)).days + 2) if dates else 45
            spec.run(ctx, lookback)
        else:
            spec.run(ctx)
        ctx.budget.record(spec.provider, spec.est_per_item)
    except Exception as exc:  # noqa: BLE001
        logger.exception("heal failed %s (run_once): %s", entry.table_name, repr(exc))
        for it in items:
            ctx.gap.mark_item_failed(it["id"], last_error=repr(exc)[:500])
            outcome["failed"] += 1
        return
    _beat(ctx, STAGE_PROVIDER_RETURNED, entry, items[0] if items else None)
    for it in items:
        _verify_and_mark(ctx, entry, spec, it, outcome, no_data_reason="not_recomputed")
        _beat(ctx, STAGE_MARKED, entry, it)


def _verify_and_mark(
    ctx, entry, spec, it, outcome, *, no_data_reason: str = "provider_no_data"
) -> None:
    if _verify_covered(ctx, entry, it["ticker"], it["data_date"]):
        ctx.gap.mark_item_healed(it["id"], actual_requests=spec.est_per_item)
        outcome["healed"] += 1
    else:
        ctx.gap.mark_item_no_data(
            it["id"], reason=no_data_reason, actual_requests=spec.est_per_item
        )
        outcome["no_data"] += 1
        # Only `provider_no_data` qualifies — NEVER no_adapter /
        # unsupported_granularity / not_recomputed, which are OUR bugs, not the
        # provider's answer. Caveating those would hide exactly the class of
        # silent no-op this plan exists to surface.
        after = getattr(ctx.settings, "data_gap_healer_no_data_caveat_after", 0)
        if after and no_data_reason == "provider_no_data" and it["data_date"]:
            # The caveat is an OPTIMISATION — it stops us re-trying a scope the
            # provider keeps refusing. It must never cost repair work. On
            # 2026-08-16 an un-guarded call here raised AttributeError out of a
            # heal run and killed ~27,000 queued items on their first no_data,
            # because the deployed repository lacked count_recent_no_data. A
            # bookkeeping nicety taking down the actual healing is never an
            # acceptable trade, whatever the cause.
            try:
                prior = ctx.gap.count_recent_no_data(
                    entry.table_name, it["ticker"], it["data_date"], runs=after
                )
                if prior >= after:
                    ctx.gap.upsert_caveat(
                        Caveat(
                            dataset=entry.table_name,
                            ticker=it["ticker"],
                            start_date=it["data_date"],
                            end_date=it["data_date"],
                            reason=f"provider returned no data {prior}x consecutively",
                            source="auto",
                        )
                    )
                    outcome["auto_caveated"] += 1
            except Exception as exc:  # noqa: BLE001 — never abort a heal for this
                logger.warning(
                    "auto-caveat bookkeeping failed for %s %s %s: %s "
                    "(item still recorded; healing continues)",
                    entry.table_name,
                    it["ticker"],
                    it["data_date"],
                    repr(exc),
                )


_DISPATCH = {
    "per_ticker_date": _dispatch_per_ticker_date,
    "per_ticker_range": _dispatch_per_ticker_range,
    "run_once": _dispatch_run_once,
    "run_once_lookback": _dispatch_run_once,
}


def execute_run(
    ctx: HealContext,
    run_id: int,
    *,
    datasets: list[str] | None = None,
    max_items: int | None = None,
    specs: dict[str, HealSpec] | None = None,
) -> dict[str, int]:
    """Claim resumable items for a run and heal them. Returns an outcome counter.

    Items the healer cannot map to an adapter, or whose provider verify still
    fails, are recorded (no_data) rather than silently dropped.
    """
    specs = specs if specs is not None else HEAL_SPECS
    ctx.run_id = run_id
    if ctx.heartbeat is None:
        ctx.heartbeat = HealHeartbeat(ctx.gap, run_id, recorder=ctx.recorder)
    claimed = ctx.gap.claim_next_items(
        run_id,
        limit=max_items if max_items is not None else 10_000_000,
        datasets=datasets,
    )
    groups: dict[str, list[dict]] = defaultdict(list)
    for it in claimed:
        groups[it["dataset"]].append(it)
    # One beat before any dataset is entered. Its ABSENCE is diagnostic too: a run
    # that never reaches this stalled inside claim_next_items, which on a 175k-item
    # backlog is a single unbounded query, not the provider.
    ctx.heartbeat.stage(
        STAGE_CLAIMED,
        dataset="*",
        claimed=len(claimed),
        datasets_pending=len(groups),
    )

    outcome: Counter[str] = Counter()
    for dataset, items in groups.items():
        # Reset the per-dataset slice BEFORE the entry/spec lookups, so a
        # dataset that falls through to no_data still gets its own budget.
        ctx.budget.begin_dataset(dataset)
        entry = ctx.registry_by_table.get(dataset)
        spec = (
            specs.get(entry.healer_adapter) if entry and entry.healer_adapter else None
        )
        if entry is None or spec is None:
            for it in items:
                ctx.gap.mark_item_no_data(it["id"], reason="no_adapter")
                outcome["no_data"] += 1
            continue
        dispatcher = _DISPATCH.get(spec.granularity)
        if dispatcher is None:
            for it in items:
                ctx.gap.mark_item_no_data(it["id"], reason="unsupported_granularity")
                outcome["no_data"] += 1
            continue
        dispatcher(ctx, entry, spec, items, outcome)
    return dict(outcome)
