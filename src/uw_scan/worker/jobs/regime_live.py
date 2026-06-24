"""Regime live scan — 5-min basis='live' CRI/VCG snapshots off WS quotes.

Also home of the nightly live-vs-lake validation: after the parquet lake
syncs (03:15/03:20 ET), compare the close each symbol's last live snapshot
captured against the lake's official close. Divergence > threshold is
logged loudly — the lake stays the canonical EOD source; live rows are the
intraday record.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_signal import WINNER, current_macro_signal_live
from uw_scan.scanners import cri as cri_scanner
from uw_scan.scanners import vcg as vcg_scanner
from uw_scan.scanners.live_quotes import load_live_quotes
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

DIVERGENCE_THRESHOLD_PCT = 0.5


def regime_live_scan_once(
    repo: Repository, settings: Settings, *, now: datetime | None = None
) -> dict:
    """One live tick: load fresh quotes → run CRI + VCG live → persist."""
    quotes = load_live_quotes(
        repo,
        settings.regime_ws_symbols,
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
        now=now,
    )
    if not quotes:
        return {"status": "skipped_no_fresh_quotes"}

    cri_payload = None
    vcg_payload = None
    try:
        cri_payload = cri_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("regime_live_cri_failed err=%s", repr(exc))
        repo.conn.rollback()
    # Same proxy choice as the EOD _regime_vcg_scan — live and EOD VCG
    # histories must describe the same credit instrument (Codex P2).
    proxy = settings.credit_etf_symbols[0] if settings.credit_etf_symbols else "HYG"
    try:
        vcg_payload = vcg_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, proxy=proxy, persist=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("regime_live_vcg_failed err=%s", repr(exc))
        repo.conn.rollback()

    # VRP macro short-vol live (SPX only — VIX + SPX are the macro inputs in
    # regime_ws_symbols). Isolated: a vol-data gap here never blocks cri/vcg.
    # upsert_vrp_macro_signal does not self-commit, so commit the leg explicitly.
    vrp_status = "skipped"
    spx_q = quotes.get("SPX")
    vix_q = quotes.get("VIX")
    if spx_q is not None and vix_q is not None:
        try:
            sig = current_macro_signal_live(
                repo,
                settings,
                "SPX",
                WINNER,
                live_spot=float(spx_q.price),
                live_iv=float(vix_q.price) / 100.0,
            )
            repo.upsert_vrp_macro_signal(
                name="SPX",
                snapshot_date=datetime.now(ZoneInfo(settings.rth_tz)).date(),
                as_of=sig.as_of,
                spot=sig.spot,
                iv=sig.iv,
                rv20=sig.rv20,
                vrp=sig.vrp,
                vrp_z=sig.vrp_z,
                weight=sig.weight,
                action=sig.action,
                short_put=sig.short_put,
                long_put=sig.long_put,
                put_width=sig.put_width,
                credit=sig.credit,
                max_loss=sig.max_loss,
                hold_days=sig.hold_days,
                short_delta=sig.short_delta,
                wing_delta=sig.wing_delta,
                bt_n=None,
                bt_sharpe=None,
                bt_maxdd=None,
                bt_annror=None,
                bt_calmar=None,
                config=None,
                basis="live",
            )
            repo.conn.commit()
            vrp_status = "ok"
        except Exception as exc:  # noqa: BLE001 — per-leg isolation
            repo.conn.rollback()
            logger.warning("regime_live_vrp_failed err=%s", repr(exc))
            vrp_status = "failed"

    return {
        "status": "ok",
        "live_symbols": sorted(quotes),
        "cri": cri_payload is not None,
        "vcg": vcg_payload is not None,
        "vrp": vrp_status,
    }


def validate_live_close_vs_lake(
    repo: Repository,
    settings: Settings,
    *,
    threshold_pct: float = DIVERGENCE_THRESHOLD_PCT,
) -> list[dict]:
    """Per symbol: lake close vs the price the last live snapshot of that
    trade date captured. Returns the rows it compared; logs WARN on
    divergence above ``threshold_pct`` percent.

    Reads BOTH snapshot tables: during a massive failover only HYG ticks,
    so a VCG live row can exist for a day with no CRI live row — reading
    cri_snapshots alone would silently skip HYG on exactly those days.
    """
    sql = f"""
        SELECT DISTINCT ON (v.symbol)
               v.symbol,
               v.trade_date,
               v.close::float8 AS lake_close,
               (c.payload->'live_quotes'->v.symbol->>'price')::float8 AS live_close
          FROM {repo._schema}.vol_index_daily v
          JOIN (
                SELECT data_date, scanned_at, payload
                  FROM {repo._schema}.cri_snapshots WHERE basis = 'live'
                UNION ALL
                SELECT data_date, scanned_at, payload
                  FROM {repo._schema}.vcg_snapshots WHERE basis = 'live'
               ) c
            ON c.data_date = v.trade_date
           AND c.payload->'live_quotes' ? v.symbol
         WHERE v.symbol = ANY(%s)
           AND v.trade_date >= CURRENT_DATE - 7
         ORDER BY v.symbol, v.trade_date DESC, c.scanned_at DESC
    """
    with repo.conn.cursor() as cur:
        cur.execute(sql, ([s.upper() for s in settings.regime_ws_symbols],))
        rows = [
            {
                "symbol": r[0],
                "trade_date": r[1],
                "lake_close": r[2],
                "live_close": r[3],
            }
            for r in cur.fetchall()
        ]
    for row in rows:
        if not row["lake_close"] or row["live_close"] is None:
            continue
        div = abs(row["live_close"] - row["lake_close"]) / row["lake_close"] * 100.0
        row["divergence_pct"] = round(div, 3)
        if div > threshold_pct:
            logger.warning(
                "regime_live_lake_divergence symbol=%s date=%s live=%.4f "
                "lake=%.4f pct=%.2f",
                row["symbol"],
                row["trade_date"],
                row["live_close"],
                row["lake_close"],
                div,
            )
    return rows
