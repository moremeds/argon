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

from uw_scan.config import Settings
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
    try:
        vcg_payload = vcg_scanner.run_live(
            repo.conn, schema=repo._schema, quotes=quotes, persist=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("regime_live_vcg_failed err=%s", repr(exc))
        repo.conn.rollback()

    return {
        "status": "ok",
        "live_symbols": sorted(quotes),
        "cri": cri_payload is not None,
        "vcg": vcg_payload is not None,
    }


def validate_live_close_vs_lake(
    repo: Repository,
    settings: Settings,
    *,
    threshold_pct: float = DIVERGENCE_THRESHOLD_PCT,
) -> list[dict]:
    """Per symbol: lake close vs the price the last live CRI snapshot of
    that trade date captured. Returns the rows it compared; logs WARN on
    divergence above ``threshold_pct`` percent."""
    sql = f"""
        SELECT DISTINCT ON (v.symbol)
               v.symbol,
               v.trade_date,
               v.close::float8 AS lake_close,
               (c.payload->'live_quotes'->v.symbol->>'price')::float8 AS live_close
          FROM {repo._schema}.vol_index_daily v
          JOIN {repo._schema}.cri_snapshots c
            ON c.basis = 'live'
           AND c.data_date = v.trade_date
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
