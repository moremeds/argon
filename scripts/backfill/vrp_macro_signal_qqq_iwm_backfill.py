"""One-shot QQQ/IWM vrp_macro_signal_daily backfill (2026-07-22).

`_lake_spot` (src/uw_scan/reports/vrp_macro_drawdown.py) pointed pyarrow's
directory-dataset reader at the whole lake symbol directory instead of the
explicit 1d.parquet file, so every QQQ/IWM read crashed on a sibling
1d.parquet.lock zero-byte file (fixed in PR #296, shipped v0.10.12). The
nightly vrp_macro_signal_refresh job has no gap-recovery (unlike
CRI/VCG/canary) — it only computes "today", so QQQ (stalled since
2026-06-24) and IWM (since 2026-07-08) need this one-off walk-back.

Local-only: no external API calls, pure DB + lake reads. Idempotent —
upsert_vrp_macro_signal is keyed on (name, snapshot_date, basis='eod'),
safe to re-run.

Reproduce (must run where the lake is mounted, i.e. inside an argon
container on the mini):
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python \
      scripts/backfill/vrp_macro_signal_qqq_iwm_backfill.py --confirm
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import asdict
from math import isfinite

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    backtest_laddered,
    current_macro_signal,
)
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vrp_macro_signal_qqq_iwm_backfill")

NAMES = ("QQQ", "IWM")


def _finite(x: float | None) -> float | None:
    return x if (x is not None and isfinite(x)) else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually write rows")
    args = ap.parse_args()

    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    config = asdict(WINNER)

    with conn.cursor() as cur:
        # The table only starts when this feature went live (~2026-06-22 for
        # SPX) — it is a forward-accumulating daily log, not a full-history
        # backtest. QQQ/IWM's lake data goes back to 2009 (VXN/RVX inception),
        # so an unbounded "aligned - existing" diff would try to backfill 16
        # years of rows nobody wants. Cap the walk-back at when the feature
        # actually started logging, across any name.
        cur.execute(
            f"SELECT MIN(snapshot_date) FROM {settings.db_schema}.vrp_macro_signal_daily "
            "WHERE basis = 'eod'"
        )
        feature_start = cur.fetchone()[0]
    logger.info(
        "feature_start (earliest snapshot_date across all names) = %s", feature_start
    )

    for name in NAMES:
        loaded = load_index_vol(repo, name)
        aligned_dates = {
            row["market_date"]
            for row in loaded.rows
            if row["market_date"] >= feature_start
        }
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT snapshot_date FROM {settings.db_schema}.vrp_macro_signal_daily "
                "WHERE name = %s AND basis = 'eod'",
                (name,),
            )
            existing = {r[0] for r in cur.fetchall()}
        missing = sorted(aligned_dates - existing)
        logger.info(
            "%s: %d aligned lake days, %d already persisted, %d missing",
            name,
            len(aligned_dates),
            len(existing),
            len(missing),
        )
        if not missing:
            continue
        if not args.confirm:
            logger.info(
                "DRY RUN — pass --confirm to write. %s missing dates: %s..%s",
                name,
                missing[0],
                missing[-1],
            )
            continue

        bt = backtest_laddered(loaded, settings, WINNER)
        filled = 0
        for d in missing:
            try:
                sig = current_macro_signal(repo, settings, name, WINNER, as_of=d)
            except ValueError as exc:
                logger.warning("%s %s: skipped — %s", name, d, exc)
                continue
            repo.upsert_vrp_macro_signal(
                name=name,
                snapshot_date=d,
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
                bt_n=bt.get("n"),
                bt_sharpe=_finite(bt.get("sharpe")),
                bt_maxdd=_finite(bt.get("maxdd")),
                bt_annror=_finite(bt.get("annror")),
                bt_calmar=_finite(bt.get("calmar")),
                config=config,
            )
            filled += 1
        conn.commit()
        logger.info("%s: backfilled %d/%d missing days", name, filled, len(missing))

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
