"""Scheduled market-wide discovery scan (Approach A).

Pulls market-wide flow alerts, scores non-watchlist tickers with the
edge_quality 5-factor model (premium is a filter, never a score input), enriches
the top-N with live dark-pool data (cached into dark_pool_events for reuse), and
persists candidate snapshots + a scan_runs row (notes='discovery_scan'). The
/api/scanner/discover endpoint reads the latest snapshot — no inline compute.

Single-flight via pg_try_advisory_lock; Stage-2 DP fetches are sequential
(shared psycopg connection is not thread-safe; the top-N cap bounds latency).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner import edge_quality as eq
from uw_scan.sources.uw import fetch_darkpool_ticker, fetch_market_flow_alerts
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

logger = logging.getLogger(__name__)

DISCOVERY_SCAN_LOCK = 92401  # single-flight; distinct from 91501/91601/92201
_INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "RUT", "VIX", "DJX", "OEX", "XSP"}


def _group_alerts(
    alerts: list[FlowAlert],
    *,
    watchlist: set[str],
    today,
    min_premium: Decimal,
    earnings_window_days: int,
) -> tuple[dict[str, list[FlowAlert]], int]:
    """Group non-watchlist alerts by ticker. Drop unknown earnings + in-window
    earnings (discovery.py:77-79 parity). Premium is a per-alert FILTER."""
    by_ticker: dict[str, list[FlowAlert]] = defaultdict(list)
    earnings_unknown_dropped = 0
    for a in alerts:
        if not a.ticker:
            continue
        ticker = a.ticker.upper()
        if ticker in watchlist or ticker in _INDEX_SYMBOLS:
            continue
        if a.next_earnings_date is None:
            earnings_unknown_dropped += 1
            continue
        if (a.next_earnings_date - today).days <= earnings_window_days:
            continue
        if a.total_premium is None or a.total_premium < min_premium:
            continue
        by_ticker[ticker].append(a)
    return dict(by_ticker), earnings_unknown_dropped


def _aggregate_flow(group: list[FlowAlert]) -> dict:
    calls = sum(1 for a in group if (a.type or "").lower() == "call")
    puts = sum(1 for a in group if (a.type or "").lower() == "put")
    sweeps = sum(1 for a in group if a.has_sweep)
    vol_ois = [
        a.volume_oi_ratio for a in group if a.volume_oi_ratio and a.volume_oi_ratio > 0
    ]
    avg_vol_oi = (
        (sum(vol_ois, Decimal("0")) / Decimal(len(vol_ois)))
        if vol_ois
        else Decimal("0")
    )
    underlying = next((a.underlying_price for a in group if a.underlying_price), None)
    sector = next((a.sector for a in group if a.sector), None)
    latest = max((a.created_at for a in group if a.created_at), default=None)
    return {
        "alert_count": len(group),
        "calls": calls,
        "puts": puts,
        "sweeps": sweeps,
        "avg_vol_oi": avg_vol_oi,
        "underlying_price": underlying,
        "sector": sector,
        "latest_alert_at": latest,
    }


def _stage1_score(agg: dict, weights: dict[str, Decimal]) -> Decimal:
    """Flow-only sub-score for ranking before DP enrichment (vol/OI + sweeps)."""
    partial = eq.calculate_score(
        dp_strength=Decimal("0"),
        dp_sustained=0,
        has_confluence=False,
        vol_oi_ratio=agg["avg_vol_oi"],
        sweep_count=agg["sweeps"],
        weights=weights,
    )
    return partial["total"]


def discovery_scan_once(
    *,
    repo: Repository,
    client: UwClient,
    settings: Settings,
    now: datetime | None = None,
) -> dict:
    """One discovery scan. Returns a summary dict."""
    if not repo.try_advisory_lock(DISCOVERY_SCAN_LOCK):
        logger.info("discovery_scan: lock held; skipping this tick")
        return {"status": "skipped_locked"}

    sigs = SignalsRepository(repo.conn, schema=settings.db_schema)
    weights = settings.scanner_edge_quality_weights()
    now = now or datetime.now(timezone.utc)
    # Derive the ET trading date from `now` so an injected clock (tests) drives
    # the earnings-window filter deterministically; in prod now == real UTC.
    today = now.astimezone(ZoneInfo(settings.rth_tz)).date()
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")

    try:
        try:
            alerts = fetch_market_flow_alerts(
                client, repo, run_id, limit=settings.scanner_discover_alerts_limit
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("discovery_scan: alerts fetch failed: %r", exc)
            repo.conn.rollback()
            repo.finish_scan_run(run_id, status="fail")
            repo.conn.commit()
            return {"status": "fetch_failed"}

        watchlist = {r.ticker.upper() for r in repo.list_active_watchlist()}
        by_ticker, earnings_dropped = _group_alerts(
            alerts,
            watchlist=watchlist,
            today=today,
            min_premium=settings.scanner_discover_min_premium_usd,
            earnings_window_days=settings.scanner_earnings_window_days,
        )

        aggs = {t: _aggregate_flow(g) for t, g in by_ticker.items()}
        ranked = sorted(
            aggs.items(),
            key=lambda kv: (-_stage1_score(kv[1], weights), kv[0]),
        )
        top_n = settings.scanner_discover_dp_top_n
        dp_truncated = max(0, len(ranked) - top_n)
        if dp_truncated:
            logger.info(
                "discovery_scan: %d candidates exceed top_n=%d; %d dropped from DP enrichment",
                len(ranked),
                top_n,
                dp_truncated,
            )
        ranked = ranked[:top_n]

        run_meta = {
            "alerts_pulled": len(alerts),
            "earnings_unknown_dropped": earnings_dropped,
            "candidates_found": len(ranked),
            "dp_truncated_dropped": dp_truncated,
        }

        snapshot_rows: list[dict] = []
        dp_enriched = 0
        for idx, (ticker, agg) in enumerate(ranked):
            if idx > 0 and settings.scanner_discover_dp_sleep_ms > 0:
                # Rate guard: space out DP fetches so a 50-ticker run can't burst
                # UW alongside the watchlist full_scan. Default 0 (off).
                time.sleep(settings.scanner_discover_dp_sleep_ms / 1000.0)

            dp_status = "ok"
            try:
                # Savepoint per ticker: a failed DP fetch rolls back ONLY this
                # ticker's audit/print writes, never the scan_run row or prior
                # tickers' cached prints. A bare repo.conn.rollback() here would
                # nuke the whole run. psycopg3 conn.transaction() opens a
                # SAVEPOINT when a tx is active, else a tx it commits on exit.
                with repo.conn.transaction():
                    prints = fetch_darkpool_ticker(client, repo, run_id, ticker)
                    if prints:
                        repo.insert_dark_pool_rows(run_id, prints)
                dp_enriched += 1
            except Exception as exc:  # noqa: BLE001
                # repr(exc), not %r: graceful per-ticker degrade stays at WARNING
                # (a DP-fetch miss is expected, not an error worth a traceback),
                # and the literal repr(exc) call satisfies CI Guardrail 2.
                logger.warning(
                    "discovery_scan: DP fetch failed for %s: %s", ticker, repr(exc)
                )
                dp_status = "degraded"

            # Graceful degrade: when TODAY's DP fetch failed, score on the flow
            # factors only — do NOT fall back to stale warm DP. Otherwise read
            # the deduped warm window.
            dp_window_price = None
            if dp_status == "degraded":
                dp = {
                    "aggregate": {
                        "direction": "NO_DATA",
                        "strength": Decimal("0"),
                        "buy_ratio": None,
                    },
                    "sustained_days": 0,
                    "total_prints": 0,
                }
            else:
                window = sigs.fetch_dark_pool_window(
                    ticker, lookback_days=settings.scanner_discover_dp_lookback_days
                )
                dp = eq.directional_darkpool(window)
                if window:
                    dp_window_price = window[0].get("price")
                if dp["aggregate"]["direction"] == "NO_DATA":
                    dp_status = "no_data"
            dp_agg = dp["aggregate"]

            bias = eq.options_bias(calls=agg["calls"], puts=agg["puts"])
            confl = eq.has_confluence(bias, dp_agg["direction"])
            score = eq.calculate_score(
                dp_strength=dp_agg["strength"],
                dp_sustained=dp["sustained_days"],
                has_confluence=confl,
                vol_oi_ratio=agg["avg_vol_oi"],
                sweep_count=agg["sweeps"],
                weights=weights,
            )
            direction = (
                "long" if bias == "bullish" else "short" if bias == "bearish" else None
            )
            spot = (
                agg["underlying_price"]
                if agg["underlying_price"] is not None
                else dp_window_price
            )

            snapshot_rows.append(
                {
                    "ticker": ticker,
                    "scored_at": now,
                    "bias": bias,
                    "direction": direction,
                    "score": score["total"],
                    "score_model": "edge_quality_v1",
                    "score_breakdown": {
                        k: float(v) for k, v in score["weighted"].items()
                    },
                    "spot_at_signal": spot,
                    "is_type_f": None,
                    "evidence": {
                        "alert_count": agg["alert_count"],
                        "calls": agg["calls"],
                        "puts": agg["puts"],
                        "sweeps": agg["sweeps"],
                        "vol_oi": str(agg["avg_vol_oi"]),
                        "dp_direction": dp_agg["direction"],
                        "dp_strength": str(dp_agg["strength"]),
                        "dp_sustained_days": dp["sustained_days"],
                        "confluence": confl,
                        "dp_status": dp_status,
                        "sector": agg["sector"],
                        "latest_alert_at": agg["latest_alert_at"].isoformat()
                        if agg["latest_alert_at"]
                        else None,
                    },
                }
            )

        # Run-level metadata persisted to the scan_runs row (NOT into candidate
        # evidence) so a non-empty feed fully filtered to zero candidates still
        # records alerts_pulled / earnings_unknown_dropped.
        run_meta["dp_enriched"] = dp_enriched
        sigs.upsert_discovery_run_meta(run_id, run_meta)
        sigs.insert_candidate_snapshots_bulk(
            run_id=run_id, section="discovery", rows=snapshot_rows
        )
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        logger.info(
            "discovery_scan: ok candidates=%d dp_enriched=%d alerts=%d dropped=%d",
            len(snapshot_rows),
            dp_enriched,
            len(alerts),
            earnings_dropped,
        )
        return {"status": "ok", **run_meta}
    except Exception as exc:  # noqa: BLE001
        logger.exception("discovery_scan failed: %r", exc)
        repo.conn.rollback()
        repo.finish_scan_run(run_id, status="fail")
        repo.conn.commit()
        return {"status": "error"}
    finally:
        repo.release_advisory_lock(DISCOVERY_SCAN_LOCK)
