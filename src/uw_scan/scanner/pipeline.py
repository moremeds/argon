"""Scanner orchestrator - runs detectors against a freshly-completed
per-ticker scan, persists hits/flags/gate, and returns the optional
ScanCandidate. Called from pipeline.run_single_stock as the final
stage before finish_scan_run.

Per the standing rule (MEMORY.md feedback_repository_split_threshold),
inline reads stay here rather than being appended to repository.py.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner.context import pcr_sentiment
from uw_scan.scanner.gates import earnings_gate, liquidity_gate
from uw_scan.scanner.models import ContextFlag, ScanCandidate, SignalHit
from uw_scan.scanner.ranking import build_candidate
from uw_scan.scanner.signals import (
    dark_pool_accumulation,
    deep_conviction_flow,
    earnings_iv_crush,
    gex_pinning,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

logger = logging.getLogger(__name__)


def _fetch_flow_alerts_for_run(
    repo: Repository | Any, run_id: int, ticker: str
) -> list[FlowAlert]:
    """Read this run's persisted FlowAlerts back out for detector input."""
    if hasattr(repo, "fetch_flow_events_for_run"):
        return list(repo.fetch_flow_events_for_run(run_id, ticker))

    sql = """
        SELECT alert_id AS id, ticker, option_chain, expiry, strike,
               option_type AS type, price, underlying_price,
               total_size, total_premium,
               total_ask_side_prem, total_bid_side_prem,
               volume, open_interest, volume_oi_ratio,
               has_sweep, has_floor, has_multileg, all_opening_trades,
               iv_start, iv_end, alert_rule, rule_id, sector, issue_type,
               next_earnings_date, created_at
        FROM uw_scan.flow_events
        WHERE run_id = %s AND ticker = %s
    """
    with repo.conn.cursor() as cur:
        cur.execute(sql, (run_id, ticker.upper()))
        rows = cur.fetchall()
        cols = [c.name for c in cur.description]
    return [FlowAlert.model_validate(dict(zip(cols, r, strict=True))) for r in rows]


def _fetch_latest_iv_rank(repo: Repository | Any, ticker: str) -> Decimal | None:
    if hasattr(repo, "fetch_latest_iv_rank"):
        return repo.fetch_latest_iv_rank(ticker)
    with repo.conn.cursor() as cur:
        cur.execute(
            """SELECT iv_rank FROM uw_scan.volatility_stats_history
               WHERE ticker = %s AND iv_rank IS NOT NULL
               ORDER BY market_date DESC LIMIT 1""",
            (ticker.upper(),),
        )
        row = cur.fetchone()
        return Decimal(str(row[0])) if row and row[0] is not None else None


def _fetch_strike_gex_curve(repo: Repository | Any, run_id: int) -> list[dict]:
    if hasattr(repo, "fetch_strike_gex_curve"):
        return list(repo.fetch_strike_gex_curve(run_id))
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT strike_gex_curve FROM uw_scan.scan_runs WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return []
        return list(row[0])


def _fetch_spot_for_ticker(repo: Repository | Any, ticker: str) -> Decimal | None:
    if hasattr(repo, "fetch_spot_for_ticker"):
        return repo.fetch_spot_for_ticker(ticker)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT spot FROM uw_scan.watchlist_card WHERE ticker = %s",
            (ticker.upper(),),
        )
        row = cur.fetchone()
        return Decimal(str(row[0])) if row and row[0] is not None else None


def _next_earnings_for_run(alerts: list[FlowAlert]) -> date | None:
    """Take the soonest known next_earnings_date from this run's alerts."""
    dates = [a.next_earnings_date for a in alerts if a.next_earnings_date]
    return min(dates) if dates else None


def run_detectors(
    *,
    repo: Repository | Any,
    signals_repo: SignalsRepository | Any,
    settings: Settings,
    run_id: int,
    ticker: str,
    today: date,
) -> ScanCandidate | None:
    """Run all detectors for one ticker, persist results, return candidate."""
    ticker = ticker.upper()
    # GOLD posture is market-wide context, not a hard scanner veto.
    regime = "pass"

    alerts = _fetch_flow_alerts_for_run(repo, run_id, ticker)
    next_earn = _next_earnings_for_run(alerts)
    earnings = earnings_gate(
        next_earnings_date=next_earn,
        today=today,
        window_days=settings.scanner_earnings_window_days,
    )

    total_volume = sum((a.volume or 0) for a in alerts)
    liquidity = liquidity_gate(
        option_volume=total_volume,
        min_volume=settings.scanner_liquidity_min_option_volume,
    )

    signals_repo.upsert_gate(
        run_id=run_id,
        ticker=ticker,
        earnings=earnings,
        liquidity=liquidity,
        regime=regime,
    )

    hits: list[SignalHit] = []

    dcf = deep_conviction_flow.detect(
        ticker=ticker,
        alerts=alerts,
        today=today,
        min_premium_usd=settings.scanner_dcf_min_premium_usd,
        min_ask_side=settings.scanner_dcf_min_ask_side,
        max_moneyness=settings.scanner_dcf_max_moneyness,
        min_dte=settings.scanner_dcf_min_dte,
        earnings_window_days=settings.scanner_earnings_window_days,
    )
    if dcf is not None:
        hits.append(dcf)

    spot = _fetch_spot_for_ticker(repo, ticker)

    dp_window = signals_repo.fetch_dark_pool_window(
        ticker, lookback_days=settings.scanner_dp_lookback_days
    )
    dp = dark_pool_accumulation.detect(
        ticker=ticker,
        dark_pool_prints=dp_window,
        min_print_premium=settings.scanner_dp_min_print_premium_usd,
        min_cluster_size=settings.scanner_dp_min_cluster_size,
        price_spread_pct=settings.scanner_dp_price_spread_pct,
        spot=spot,
    )
    if dp is not None:
        hits.append(dp)

    iv_rank = _fetch_latest_iv_rank(repo, ticker)
    eic = earnings_iv_crush.detect(
        ticker=ticker,
        iv_rank=iv_rank,
        next_earnings_date=next_earn,
        today=today,
        min_iv_rank=settings.scanner_eic_min_iv_rank,
        earnings_window_days=settings.scanner_earnings_window_days,
    )
    if eic is not None:
        hits.append(eic)

    curve = _fetch_strike_gex_curve(repo, run_id)
    gex = gex_pinning.detect(
        ticker=ticker,
        strike_gex_curve=curve,
        spot=spot,
        today=today,
        min_gamma=settings.scanner_gex_pin_min_gamma,
    )
    if gex is not None:
        hits.append(gex)

    pcr_flag = pcr_sentiment.flag(
        ticker=ticker,
        alerts=alerts,
        today=today,
        earnings_window_days=settings.scanner_earnings_window_days,
    )

    for h in hits:
        signals_repo.upsert_signal_hit(
            run_id=run_id,
            ticker=ticker,
            signal_type=h.signal_type,
            tier=h.tier,
            score=h.score,
            evidence=h.evidence,
            freshness=h.freshness,
        )
    flags: list[ContextFlag] = []
    if pcr_flag is not None:
        flags.append(pcr_flag)
        signals_repo.upsert_context_flag(
            run_id=run_id,
            ticker=ticker,
            layer=pcr_flag.layer,
            label=pcr_flag.label,
            value=pcr_flag.value,
        )

    return build_candidate(
        ticker=ticker,
        hits=hits,
        context_flags=flags,
        gates={"earnings": earnings, "liquidity": liquidity, "regime": regime},
    )
