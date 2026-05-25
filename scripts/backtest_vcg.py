#!/usr/bin/env python3
"""Backtest VCG (Volatility-Credit Gap) across the full available history.

Reads:
  - vol_index_daily for VIX, VVIX, and the credit proxy (HYG default)

Recomputes VCG for every aligned trading day. The aligned window is bounded
by the shortest series — usually the credit proxy. Uses adj_close for the
credit ETF (HYG/JNK/LQD distribute monthly; raw close would surface every
ex-dividend drop as a log-return spike).

Persists:
  - uw_scan.regime_backtest_runs (one row per invocation)
  - uw_scan.regime_backtest_daily (one row per aligned trading day post-burn-in)

Usage:
  uv run python scripts/backtest_vcg.py
  uv run python scripts/backtest_vcg.py --proxy LQD --note "LQD proxy A/B"
  uv run python scripts/backtest_vcg.py --start 2007-04-11 --end 2026-05-15
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from collections import Counter
from datetime import date as _date
from pathlib import Path

import numpy as np
import psycopg

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards import vcg_scoring  # noqa: E402
from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION, MIN_BARS  # noqa: E402
from uw_scan.config import Settings  # noqa: E402
from uw_scan.storage.regime_backtest_repository import (  # noqa: E402
    RegimeBacktestRepository,
)

log = logging.getLogger("backtest_vcg")

# Same named events as the CRI backtest — symmetry across indicators.
NAMED_CRASH_DATES = {
    "2008-09-15": "Lehman bankruptcy",
    "2008-10-10": "GFC bottom area",
    "2010-05-06": "Flash crash",
    "2011-08-08": "US credit downgrade",
    "2015-08-24": "Black Monday (China)",
    "2018-02-05": "Volmageddon",
    "2018-12-24": "Q4 selloff trough",
    "2020-02-28": "COVID early break",
    "2020-03-16": "COVID circuit breaker",
    "2022-06-13": "Rate-hike vol",
    "2024-08-05": "Yen-carry unwind",
}

_VALID_PROXIES = ("HYG", "JNK", "LQD")


def _detect_adj_close(conn: psycopg.Connection, schema: str) -> bool:
    """Return True if vol_index_daily has an adj_close column."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
              FROM information_schema.columns
             WHERE table_schema = %s
               AND table_name = 'vol_index_daily'
               AND column_name = 'adj_close'
            """,
            (schema,),
        )
        return cur.fetchone() is not None


def fetch_aligned_series(
    conn: psycopg.Connection,
    schema: str,
    start: _date,
    end: _date,
    proxy: str,
    use_adj_close: bool,
) -> tuple[dict[str, np.ndarray], list[str]]:
    """Fetch and align VIX, VVIX, <proxy> on shared dates."""
    series: dict[str, dict[_date, float]] = {}
    with conn.cursor() as cur:
        for sym in ("VIX", "VVIX"):
            cur.execute(
                f"SELECT trade_date, close FROM {schema}.vol_index_daily "
                "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
                "AND close IS NOT NULL ORDER BY trade_date",
                (sym, start, end),
            )
            series[sym] = {r[0]: float(r[1]) for r in cur.fetchall()}

        credit_col = "COALESCE(adj_close, close)" if use_adj_close else "close"
        cur.execute(
            f"SELECT trade_date, {credit_col} FROM {schema}.vol_index_daily "
            "WHERE symbol = %s AND trade_date BETWEEN %s AND %s "
            f"AND {credit_col} IS NOT NULL ORDER BY trade_date",
            (proxy, start, end),
        )
        series[proxy] = {r[0]: float(r[1]) for r in cur.fetchall()}

    common = (
        set(series["VIX"].keys())
        & set(series["VVIX"].keys())
        & set(series[proxy].keys())
    )
    sorted_dates = sorted(common)
    aligned = {
        sym: np.array([series[sym][d] for d in sorted_dates], dtype=float)
        for sym in series
    }
    return aligned, [d.isoformat() for d in sorted_dates]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2007-01-01")
    p.add_argument("--end", default=_date.today().isoformat())
    p.add_argument("--proxy", default="HYG", choices=_VALID_PROXIES)
    p.add_argument("--note", default=None)
    args = p.parse_args()

    start = _date.fromisoformat(args.start)
    end = _date.fromisoformat(args.end)

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        use_adj_close = _detect_adj_close(conn, settings.db_schema)
        if not use_adj_close:
            log.warning(
                "vol_index_daily lacks adj_close column — falling back to raw "
                "close for %s; expect dividend-noise spikes in residuals.",
                args.proxy,
            )
        aligned, dates = fetch_aligned_series(
            conn,
            settings.db_schema,
            start,
            end,
            args.proxy,
            use_adj_close,
        )

    n = len(dates)
    log.info("aligned %d trading days for proxy=%s", n, args.proxy)
    if n < MIN_BARS + 10:
        log.error("not enough data: %d days, need at least %d", n, MIN_BARS + 10)
        return 1

    model = vcg_scoring.compute_vcg(
        aligned["VIX"], aligned["VVIX"], aligned[args.proxy]
    )

    # Walk every aligned bar from MIN_BARS onward; assemble daily rows.
    # Model arrays are length N-1 (log_returns drops one bar); per-day date
    # is dates[i+1] (matches run_analysis history convention).
    daily_rows: list[dict] = []
    interp_counter: Counter[str] = Counter()
    ro_count = edr_count = bounce_count = 0
    for i in range(MIN_BARS, len(model["residuals"])):
        date_idx = i + 1
        if date_idx >= len(dates):
            break
        day = vcg_scoring._interpretation_for_index(model, i)
        interp = day["interpretation"]
        interp_counter[interp] += 1
        if day["ro"]:
            ro_count += 1
        if day["edr"]:
            edr_count += 1
        if day["bounce"]:
            bounce_count += 1
        raw_score = day.get("vcg_adj")
        score = (
            float(raw_score)
            if raw_score is not None and not math.isnan(float(raw_score))
            else 0.0
        )
        daily_rows.append(
            {
                "trade_date": _date.fromisoformat(dates[date_idx]),
                "score": score,
                "level": interp,
                "payload": {
                    "vcg": day["vcg"],
                    "vcg_adj": day["vcg_adj"],
                    "residual": day["residual"],
                    "beta1_vvix": day["beta1_vvix"],
                    "beta2_vix": day["beta2_vix"],
                    "alpha": day["alpha"],
                    "vix": day["vix"],
                    "vvix": day["vvix"],
                    "credit_price": day["credit_price"],
                    "sign_ok": day["sign_ok"],
                    "ro": day["ro"],
                    "edr": day["edr"],
                    "tier": day["tier"],
                    "bounce": day["bounce"],
                    "pi_panic": day["pi_panic"],
                    "regime": day["regime"],
                },
            }
        )

    if not daily_rows:
        log.error("no rows after burn-in (MIN_BARS=%d)", MIN_BARS)
        return 1

    # Named-crash window: ±5 sessions around each event, with raw vcg + vcg_adj.
    iso_to_date_idx = {d: idx for idx, d in enumerate(dates)}
    named_crash_window: dict[str, list[dict]] = {}
    for iso, _name in NAMED_CRASH_DATES.items():
        if iso not in iso_to_date_idx:
            continue
        date_idx = iso_to_date_idx[iso]
        model_idx = date_idx - 1  # model arrays are length N-1
        window: list[dict] = []
        for offset in (-5, -3, -1, 0, 1, 3, 5):
            mi = model_idx + offset
            if mi < MIN_BARS or mi >= len(model["residuals"]):
                continue
            d = vcg_scoring._interpretation_for_index(model, mi)
            window.append(
                {
                    "offset_d": offset,
                    "vcg": d["vcg"],
                    "vcg_adj": d["vcg_adj"],
                    "beta1": d["beta1_vvix"],
                    "beta2": d["beta2_vix"],
                    "sign_ok": d["sign_ok"],
                    "interpretation": d["interpretation"],
                    "vix": d["vix"],
                }
            )
        if window:
            named_crash_window[iso] = window

    summary = {
        "oos": None,  # No defensible Y-label in V1 — see vcg-methodology.md §6.
        "extras": {
            "credit_proxy": args.proxy,
            "use_adj_close": bool(use_adj_close),
            "named_crash_window": named_crash_window,
            "interpretation_distribution": dict(interp_counter),
            "ro_count": ro_count,
            "edr_count": edr_count,
            "bounce_count": bounce_count,
        },
    }

    with psycopg.connect(settings.db_dsn()) as conn:
        rb = RegimeBacktestRepository(conn, schema=settings.db_schema)
        run_id = rb.insert_run(
            indicator="vcg",
            composite_version=str(COMPOSITE_VERSION),
            start_date=daily_rows[0]["trade_date"],
            end_date=daily_rows[-1]["trade_date"],
            window_days=vcg_scoring.OLS_WINDOW,
            n_days=len(daily_rows),
            params={
                "proxy": args.proxy,
                "ols_window": vcg_scoring.OLS_WINDOW,
                "z_window": vcg_scoring.Z_WINDOW,
                "use_adj_close": bool(use_adj_close),
            },
            summary=summary,
            note=args.note,
        )
        rb.bulk_insert_daily(run_id, daily_rows)
        rb.mark_run_completed(run_id)

    log.info(
        "VCG backtest persisted: run_id=%d n=%d proxy=%s composite_version=%s",
        run_id,
        len(daily_rows),
        args.proxy,
        COMPOSITE_VERSION,
    )

    log.info("=== VCG ±5d named-crash window (proxy=%s) ===", args.proxy)
    for iso, window in named_crash_window.items():
        log.info("--- %s %s ---", iso, NAMED_CRASH_DATES[iso])
        log.info("  offset  vcg     vcg_adj  beta1   beta2   sign_ok  interp")
        for w in window:
            vcg_s = f"{w['vcg']:+.2f}" if w["vcg"] is not None else "  nan"
            adj_s = f"{w['vcg_adj']:+.2f}" if w["vcg_adj"] is not None else "  nan"
            b1_s = f"{w['beta1']:+.2f}" if w["beta1"] is not None else "  nan"
            b2_s = f"{w['beta2']:+.2f}" if w["beta2"] is not None else "  nan"
            log.info(
                "  %+d      %s    %s    %s   %s   %s    %s",
                w["offset_d"],
                vcg_s,
                adj_s,
                b1_s,
                b2_s,
                str(w["sign_ok"]).lower(),
                w["interpretation"],
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
