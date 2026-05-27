"""Daily/backfill canary snapshot producer.

Two entry points:
  - main() — argparse + Settings.from_env() + connect + delegate to cmd_backfill.
    Used by the daily APScheduler job (no UI change).
  - cmd_backfill(conn, *, schema, args) — pure unit; in-process integration
    tests target this directly without subprocess / env-var plumbing.

Walks aligned trading days from vol_index_daily, computes one snapshot per
day using causal slicing (history[:i+1]), and persists via
CanarySnapshotRepository. Idempotent via canonical payload-hash compare:
re-running on a date whose existing row has the same hash is a no-op;
mismatch raises unless --overwrite-on-hash-mismatch is passed.

The script enforces the same warm-up gate as the live scanner
(`MIN_ALIGNED_BARS = 350`): no snapshot is computed at index < 349.

Typical invocations:
  uv run python scripts/canary_backfill.py --days 252
  uv run python scripts/canary_backfill.py --composite-version 2 \
      --start-date 2011-02-08 --end-date 2026-05-21
  uv run python scripts/canary_backfill.py --composite-version 2 \
      --start-date 2020-01-02 --end-date 2020-12-30 \
      --overwrite-on-hash-mismatch

Requires UW_SCAN_API_KEY + UW_SCAN_DB_NAME in env (only DB creds used).
"""

from __future__ import annotations

import argparse
import logging
from datetime import date as _date
from decimal import Decimal
from pathlib import Path

import numpy as np
import psycopg

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import Calibration, load_calibration
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

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"


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


def _load_calibration_for_version(version: int) -> Calibration:
    if version == 2:
        cal = load_calibration(path=V2_CAL_PATH)
        if cal.composite_version != 2:
            raise RuntimeError(
                f"canary-calibration-v2.json has composite_version="
                f"{cal.composite_version}; expected 2"
            )
        return cal
    cal = load_calibration()
    if cal.composite_version != 1:
        raise RuntimeError("default load_calibration() returned non-v1 — investigate")
    return cal


def _derive_load_span(args: argparse.Namespace) -> int:
    """Pick the data-load span large enough to cover [start_date, end_date] +
    the scanner's MIN_ALIGNED_BARS warmup. The pre-v2A path defaulted to
    max(800, days + 500), which silently capped a multi-year backfill at
    ~800 calendar days when --start-date was set to a distant past date."""
    if args.start_date and args.end_date:
        sd = _date.fromisoformat(args.start_date)
        ed = _date.fromisoformat(args.end_date)
        return max(800, (ed - sd).days + 500)
    return max(800, args.days + 500)


def cmd_backfill(conn, *, schema: str, args: argparse.Namespace) -> None:
    """Backfill canary_snapshots for [start_date, end_date] at composite_version.

    Pure unit — does not call Settings.from_env() or psycopg.connect().
    """
    cal = _load_calibration_for_version(args.composite_version)
    vol_repo = VolIndexRepository(conn, schema=schema)
    span = _derive_load_span(args)
    raw = {
        sym: _load(vol_repo, sym, span)
        for sym in ("VIX", "VVIX", "VIX3M", "COR1M", "SPX")
    }
    aligned, all_dates = _align(raw)
    if len(all_dates) < MIN_ALIGNED_BARS:
        raise RuntimeError(
            f"not enough aligned bars: have {len(all_dates)} need >= {MIN_ALIGNED_BARS}"
        )

    if args.start_date and args.end_date:
        sd = _date.fromisoformat(args.start_date)
        ed = _date.fromisoformat(args.end_date)
        dates_to_backfill = {d for d in all_dates if sd <= d <= ed}
    else:
        first_idx = max(MIN_ALIGNED_BARS - 1, len(all_dates) - args.days)
        dates_to_backfill = set(all_dates[first_idx:])

    if not dates_to_backfill:
        log.warning("no dates to backfill for the requested range")
        return

    closes = aligned["SPX"].tolist()
    history_pairs = list(zip(all_dates, closes))
    state = _replay_events(history_pairs)
    snap_repo = CanarySnapshotRepository(conn, schema=schema)

    wrote = skipped = overwrote = 0
    sorted_backfill_dates: list[_date] = []
    for i, d in enumerate(all_dates):
        if d not in dates_to_backfill:
            continue
        if i < MIN_ALIGNED_BARS - 1:
            continue
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
            cal_for_run=cal,
        )
        new_hash = canonical_payload_hash(payload)

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT payload_hash FROM {schema}.canary_snapshots "
                f"WHERE data_date = %s AND composite_version = %s",
                (d, cal.composite_version),
            )
            existing = cur.fetchone()

        if existing is not None:
            if existing[0] == new_hash:
                skipped += 1
                sorted_backfill_dates.append(d)
                continue
            if not args.overwrite_on_hash_mismatch:
                raise RuntimeError(
                    f"hash mismatch at data_date={d} composite_version="
                    f"{cal.composite_version}: existing={existing[0]!r} "
                    f"new={new_hash!r}. Pass --overwrite-on-hash-mismatch to "
                    f"replace, or DELETE the row manually if you know it's stale."
                )
            with conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {schema}.canary_snapshots "
                    f"WHERE data_date = %s AND composite_version = %s",
                    (d, cal.composite_version),
                )
            overwrote += 1

        snap_repo.insert_snapshot(
            payload=payload,
            data_date=d,
            composite_version=cal.composite_version,
            score_form=cal.score_form,
            score=Decimal(str(payload["canary"]["score"])),
            raw_score=Decimal(str(payload["canary"]["raw_score"])),
            band=payload["canary"]["band"],
            tactical_score=Decimal(str(payload["tactical_vol"]["score"])),
            structural_score=Decimal(str(payload["structural_vol"]["score"])),
            speed_score=payload["speed"]["score"],
            warning_state=payload["canary"]["warning_state"],
            payload_hash=new_hash,
            on_conflict="noop",
        )
        wrote += 1
        sorted_backfill_dates.append(d)

    conn.commit()
    if sorted_backfill_dates:
        log.info(
            "backfill complete: wrote=%d skipped=%d overwrote=%d range=[%s..%s]",
            wrote,
            skipped,
            overwrote,
            sorted_backfill_dates[0],
            sorted_backfill_dates[-1],
        )
    else:
        log.info(
            "backfill complete: wrote=0 skipped=0 overwrote=0 (no dates after gate)"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--days",
        type=int,
        default=252,
        help="how many of the most-recent aligned trading days to write "
        "(default 252 ≈ 1 trading year; use 4000+ for full lookback). "
        "Ignored when --start-date is given.",
    )
    ap.add_argument(
        "--composite-version",
        type=int,
        choices=(1, 2),
        default=1,
        help="which calibration to load (default 1, the production version). "
        "Pass 2 for v2-A research backfill (loads canary-calibration-v2.json, "
        "writes composite_version=2 rows, invisible to production reads).",
    )
    ap.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="ISO date (YYYY-MM-DD) for the first day to backfill. "
        "Overrides --days if set.",
    )
    ap.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="ISO date (YYYY-MM-DD) for the last day to backfill. "
        "Defaults to today if --start-date is given but --end-date isn't.",
    )
    ap.add_argument(
        "--overwrite-on-hash-mismatch",
        action="store_true",
        help="if an existing row's payload_hash differs from the freshly "
        "computed payload, overwrite instead of raising. Use for one-off "
        "recompute after a known formula change (e.g., re-running v2 after "
        "an in-flight v2 patch).",
    )
    args = ap.parse_args()

    if args.start_date and not args.end_date:
        args.end_date = _date.today().isoformat()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn(), autocommit=False) as conn:
        cmd_backfill(conn, schema=settings.db_schema, args=args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
