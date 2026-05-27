"""One-shot 5% Canary backfill.

Walks the most-recent N aligned trading days from vol_index_daily, computes
one snapshot per day using causal slicing (history[:i+1]), and persists via
CanarySnapshotRepository(on_conflict='noop' | 'overwrite'). Idempotent — safe
to re-run.

Use cases:
  - First-time backfill for a fresh schema / scratch DB
  - Top-up after extending the window
  - Recomputing the full history after a COMPOSITE_VERSION bump (use
    --overwrite so prior rows are replaced under the new version)

The script enforces the same warm-up gate as the live scanner
(`MIN_ALIGNED_BARS = 350`): no snapshot is computed at index < 349 (zero-
indexed). That avoids writing rows the scanner would skip in production.

Typical invocations:
  uv run python scripts/canary_backfill.py --days 252
  uv run python scripts/canary_backfill.py --days 4000          # full lookback
  uv run python scripts/canary_backfill.py --days 252 --overwrite

Requires UW_SCAN_API_KEY + UW_SCAN_DB_NAME in env (only DB creds are used —
no UW API calls).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace as _replace
from datetime import date as _date
from decimal import Decimal

import numpy as np
import psycopg

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, load_calibration
from uw_scan.cards.canary_payload_hash import canonical_payload_hash
from uw_scan.config import Settings
from uw_scan.scanners.canary import (
    MIN_ALIGNED_BARS,
    _align,
    _compute_cap_lift_inputs,
    _load,
    _replay_events,
)
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("canary_backfill")


def _build_snapshot_payload(
    *,
    today: _date,
    aligned_slice: dict,
    slice_dates: list[_date],
    sma50: float,
    sma200: float,
    cap_lift_inputs: tuple[bool, bool, bool],
    confirmed_active: bool,
    btd_active: bool,
    cal_for_run,
) -> dict:
    sma200_2d, term_norm, higher_low = cap_lift_inputs
    return canary_scoring.run_analysis(
        today=today,
        aligned=aligned_slice,
        common_dates=[dd.isoformat() for dd in slice_dates],
        sma_50_today=sma50,
        sma_200_today=sma200,
        spx_above_sma200_2d=sma200_2d,
        vix_term_normalized=term_norm,
        higher_closing_low=higher_low,
        confirmed_canary_active=confirmed_active,
        buy_the_dip_active=btd_active,
        calibration=cal_for_run,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--days",
        type=int,
        default=252,
        help="how many of the most-recent aligned trading days to write "
        "(default 252 ≈ 1 trading year; use 4000+ for full lookback)",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        help="replace existing rows instead of ON CONFLICT DO NOTHING "
        "(use after a COMPOSITE_VERSION bump)",
    )
    args = ap.parse_args()

    s = Settings.from_env()
    cal = load_calibration()
    on_conflict = "overwrite" if args.overwrite else "noop"

    with psycopg.connect(s.db_dsn(), autocommit=False) as conn:
        vol_repo = VolIndexRepository(conn, schema=s.db_schema)
        # Load enough history to cover (args.days back) + the scanner's
        # MIN_ALIGNED_BARS warm-up plus a buffer. 800 cal days ≈ 550 trading
        # days, comfortably more than 350.
        span = max(800, args.days + 500)
        raw = {
            sym: _load(vol_repo, sym, span)
            for sym in ("VIX", "VVIX", "VIX3M", "COR1M", "SPX")
        }
        aligned, all_dates = _align(raw)
        if len(all_dates) < MIN_ALIGNED_BARS:
            log.error(
                "not enough aligned bars: have %d need >= %d",
                len(all_dates),
                MIN_ALIGNED_BARS,
            )
            return 1

        closes = aligned["SPX"].tolist()
        history_pairs = list(zip(all_dates, closes))
        state = _replay_events(history_pairs)

        cal_for_run = _replace(cal, score_form=cal.score_form)
        snap_repo = CanarySnapshotRepository(conn, schema=s.db_schema)

        # Backfill the most recent args.days aligned dates, respecting the
        # scanner's MIN_ALIGNED_BARS gate (first computable snapshot is at
        # zero-indexed 349, the 350th aligned bar).
        first_idx = max(MIN_ALIGNED_BARS - 1, len(all_dates) - args.days)
        wrote = skipped = 0
        for i in range(first_idx, len(all_dates)):
            d = all_dates[i]
            sma50 = float(np.mean(closes[i - 49 : i + 1]))
            sma200 = float(np.mean(closes[i - 199 : i + 1]))
            slice_dates = all_dates[: i + 1]
            date_to_idx = {dd: idx for idx, dd in enumerate(slice_dates)}
            window = canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
            confirmed_active = any(
                e.kind == "confirmed_canary"
                and e.fire_date in date_to_idx
                and 0 <= i - date_to_idx[e.fire_date] <= window
                for e in state.emitted
            )
            btd_active = any(
                e.kind == "buy_the_dip"
                and e.fire_date in date_to_idx
                and 0 <= i - date_to_idx[e.fire_date] <= window
                for e in state.emitted
            )
            cap_lift = _compute_cap_lift_inputs(
                aligned["SPX"][: i + 1],
                sma200,
                aligned["VIX"][: i + 1],
                aligned["VIX3M"][: i + 1],
            )
            payload = _build_snapshot_payload(
                today=d,
                aligned_slice={k: v[: i + 1] for k, v in aligned.items()},
                slice_dates=slice_dates,
                sma50=sma50,
                sma200=sma200,
                cap_lift_inputs=cap_lift,
                confirmed_active=confirmed_active,
                btd_active=btd_active,
                cal_for_run=cal_for_run,
            )
            row_id = snap_repo.insert_snapshot(
                payload=payload,
                data_date=d,
                composite_version=COMPOSITE_VERSION,
                score_form=cal_for_run.score_form,
                score=Decimal(str(payload["canary"]["score"])),
                raw_score=Decimal(str(payload["canary"]["raw_score"])),
                band=payload["canary"]["band"],
                tactical_score=Decimal(str(payload["tactical_vol"]["score"])),
                structural_score=Decimal(str(payload["structural_vol"]["score"])),
                speed_score=payload["speed"]["score"],
                warning_state=payload["canary"]["warning_state"],
                payload_hash=canonical_payload_hash(payload),
                on_conflict=on_conflict,
            )
            if row_id is None:
                skipped += 1
            else:
                wrote += 1

        log.info(
            "backfill complete: wrote=%d skipped=%d range=[%s..%s]",
            wrote,
            skipped,
            all_dates[first_idx],
            all_dates[-1],
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
