"""5% Canary backtest harness.

Three modes — see docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §7, §8.

  --calibrate         Compute Class B thresholds on the train window (2007-2014),
                      write canary-calibration-v1.json.
  --form-sweep        Sweep four scoring forms on the validation window (2015-2019),
                      persist per-form results to regime_backtest_runs, pick winner.
  --report            Compute final OOS report on the test window (2020-present),
                      persist with summary.is_winning_form=true.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
from psycopg import connect

from uw_scan.cards.canary_calibration import (
    COMPOSITE_VERSION,
)
from uw_scan.cards.canary_calibration import (
    DEFAULT_PATH as CALIB_PATH,
)
from uw_scan.config import Settings

log = logging.getLogger(__name__)

TRAIN_END = date(2014, 12, 31)
VALID_START = date(2015, 1, 1)
VALID_END = date(2019, 12, 31)
TEST_START = date(2020, 1, 1)


def _percentile(arr, p, *, name: str):
    if not arr:
        raise RuntimeError(
            f"cannot calibrate canary: no positive observations for {name}"
        )
    return float(np.percentile(arr, p))


def cmd_calibrate(conn) -> None:
    """Compute Class B thresholds (p25 floor, p90 ceiling) on the train window
    using positive-condition observations only. Write canary-calibration-v1.json.
    """
    from uw_scan.storage.vol_index_repository import VolIndexRepository

    vol_repo = VolIndexRepository(conn)

    def _series(sym):
        rows = vol_repo.fetch_history(sym, days=8000)
        return [
            (r["trade_date"], float(r["close"]))
            for r in rows
            if r["trade_date"] <= TRAIN_END and r.get("close") is not None
        ]

    vix = dict(_series("VIX"))
    vix3m = dict(_series("VIX3M"))
    cor = dict(_series("COR1M"))
    vvix = dict(_series("VVIX"))
    spx = dict(_series("SPX"))

    common = sorted(set(vix) & set(vix3m) & set(cor) & set(vvix) & set(spx))
    if not common:
        raise RuntimeError(
            "no overlapping VIX/VIX3M/COR1M/VVIX/SPX bars on or before "
            f"{TRAIN_END}. Seed the warm store via the parquet lake sync first."
        )
    vix_arr = np.array([vix[d] for d in common])
    vix3m_arr = np.array([vix3m[d] for d in common])
    cor_arr = np.array([cor[d] for d in common])
    vvix_arr = np.array([vvix[d] for d in common])
    spx_arr = np.array([spx[d] for d in common])

    # v0.4 patch I2: calibration slices MUST match runtime scorer slices.
    # Runtime uses `vix_history[-lookback:]` (inclusive of today). The
    # calibration here uses `i - lookback + 1 : i + 1` (inclusive of index
    # `i`), so the empirical distribution matches the runtime feature.

    pullback_obs = []
    for i in range(9, len(vix_arr)):
        peak = vix_arr[i - 9 : i + 1].max()
        if peak >= 30.0:
            pullback_obs.append(max(0.0, (peak - vix_arr[i]) / peak))

    ratios = vix_arr / vix3m_arr
    norm_obs = []
    for i in range(9, len(ratios)):
        peak = ratios[i - 9 : i + 1].max()
        if peak >= 1.05:
            norm_obs.append(max(0.0, (peak - ratios[i]) / peak))

    log_returns = np.diff(np.log(spx_arr))
    vrp_obs = []
    for i in range(20, len(vix_arr)):
        rv = log_returns[i - 20 : i].std(ddof=0) * np.sqrt(252) * 100.0
        vrp_obs.append(vix_arr[i] ** 2 - rv**2)

    cor_decay_obs = []
    for i in range(59, len(cor_arr)):
        peak = cor_arr[i - 59 : i + 1].max()
        if peak >= 60.0:
            cor_decay_obs.append(max(0.0, (peak - cor_arr[i]) / peak))

    vvr = vvix_arr / vix_arr
    vvr_obs = []
    for i in range(59, len(vvr)):
        if vvr[i - 59 : i + 1].min() <= 4.0:
            vvr_obs.append(vvr[i])

    cal_out = {
        "composite_version": COMPOSITE_VERSION,
        "train_window": {"start": "2007-01-01", "end": TRAIN_END.isoformat()},
        "score_form": "linear",
        "thresholds": {
            "vix_spike_revert": {
                "floor": _percentile(pullback_obs, 25, name="vix_spike_revert"),
                "ceiling": _percentile(pullback_obs, 90, name="vix_spike_revert"),
                "spike_active_at_vix": 30.0,
                "peak_lookback_d": 10,
                "max_points": 15,
            },
            "vix_vix3m_back": {
                "floor": _percentile(norm_obs, 25, name="vix_vix3m_back"),
                "ceiling": _percentile(norm_obs, 90, name="vix_vix3m_back"),
                "backwardation_extreme_at_ratio": 1.05,
                "peak_lookback_d": 10,
                "max_points": 15,
            },
            "vrp": {
                "floor": _percentile(vrp_obs, 25, name="vrp"),
                "ceiling": _percentile(vrp_obs, 90, name="vrp"),
                "rv_window_d": 20,
                "max_points": 21,
            },
            "cor1m_decay": {
                "floor": _percentile(cor_decay_obs, 25, name="cor1m_decay"),
                "ceiling": _percentile(cor_decay_obs, 90, name="cor1m_decay"),
                "peak_elevated_at": 60.0,
                "peak_lookback_d": 60,
                "max_points": 17,
            },
            "vvix_vix_recovery": {
                "floor": _percentile(vvr_obs, 25, name="vvix_vix_recovery"),
                "ceiling": _percentile(vvr_obs, 90, name="vvix_vix_recovery"),
                "compressed_below_ratio": 4.0,
                "compress_lookback_d": 60,
                "max_points": 12,
            },
        },
        "band_distribution_train": None,
        "author_overrides": [],
        "produced_at": str(date.today()) + "T00:00:00Z",
        "produced_by": "scripts/backtest_canary.py --calibrate",
    }
    CALIB_PATH.write_text(json.dumps(cal_out, indent=2) + "\n")
    log.info("calibration written to %s", CALIB_PATH)


def _compute_canary_series(
    conn, calibration, form: str, start: date, end: date
) -> dict:
    """Compute one row per trading day for the eval window [start, end] PLUS
    retain the full backtest history for cross-window lookbacks.

    Returns {eval_rows, all_rows, events, date_to_all_index}.
    """
    from uw_scan.cards import canary_scoring
    from uw_scan.scanners.canary import (
        _align,
        _compute_cap_lift_inputs,
        _load,
        _replay_events,
    )
    from uw_scan.storage.vol_index_repository import VolIndexRepository

    vol_repo = VolIndexRepository(conn)
    span_days = (date.today() - start).days + 500
    raw = {
        "VIX": _load(vol_repo, "VIX", span_days),
        "VVIX": _load(vol_repo, "VVIX", span_days),
        "VIX3M": _load(vol_repo, "VIX3M", span_days),
        "COR1M": _load(vol_repo, "COR1M", span_days),
        "SPX": _load(vol_repo, "SPX", span_days),
    }
    aligned, all_dates = _align(raw)

    cal_for_run = replace(calibration, score_form=form)

    closes = aligned["SPX"].tolist()
    history_pairs = list(zip(all_dates, closes))
    state = _replay_events(history_pairs)

    all_rows = []
    eval_rows = []
    for i, d in enumerate(all_dates):
        if i < 200:
            continue
        sma50 = float(np.mean(closes[i - 49 : i + 1]))
        sma200 = float(np.mean(closes[i - 199 : i + 1]))
        slice_dates = all_dates[: i + 1]
        date_to_idx = {dd: idx for idx, dd in enumerate(slice_dates)}
        confirmed_active = any(
            e.kind == "confirmed_canary"
            and e.fire_date in date_to_idx
            and 0
            <= i - date_to_idx[e.fire_date]
            <= canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
            for e in state.emitted
        )
        btd_active = any(
            e.kind == "buy_the_dip"
            and e.fire_date in date_to_idx
            and 0
            <= i - date_to_idx[e.fire_date]
            <= canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS
            for e in state.emitted
        )
        sma200_2d, term_norm, higher_low = _compute_cap_lift_inputs(
            aligned["SPX"][: i + 1],
            sma200,
            aligned["VIX"][: i + 1],
            aligned["VIX3M"][: i + 1],
        )
        payload = canary_scoring.run_analysis(
            today=d,
            aligned={k: v[: i + 1] for k, v in aligned.items()},
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
        row = {
            "date": d,
            "spx": closes[i],
            "score": payload["canary"]["score"],
            "band": payload["canary"]["band"],
            "tactical": payload["tactical_vol"]["score"],
            "structural": payload["structural_vol"]["score"],
            "speed": payload["speed"]["score"],
            "warning_state": payload["canary"]["warning_state"],
        }
        all_rows.append(row)
        if start <= d <= end:
            eval_rows.append(row)
    window_events = [e for e in state.emitted if start <= e.fire_date <= end]
    date_to_all_index = {r["date"]: i for i, r in enumerate(all_rows)}
    return {
        "eval_rows": eval_rows,
        "all_rows": all_rows,
        "events": window_events,
        "date_to_all_index": date_to_all_index,
    }


def _entry_lagged_label(rows: list[dict], horizon_td: int, threshold: float) -> list:
    """Forward return ≥ threshold over horizon_td trading days using
    entry_date = next trading day (v0.3 execution-lag fix)."""
    n = len(rows)
    closes = [r["spx"] for r in rows]
    out = []
    for i in range(n):
        entry_idx = i + 1
        if entry_idx + horizon_td >= n:
            out.append(None)
            continue
        ret = closes[entry_idx + horizon_td] / closes[entry_idx] - 1.0
        out.append(1 if ret >= threshold else 0)
    return out


def _auc(scores: list[float], labels: list) -> float:
    """Pairwise AUC with explicit None filtering."""
    pairs = [(s, l) for s, l in zip(scores, labels) if l is not None]
    if not pairs:
        return float("nan")
    pos = [s for s, l in pairs if l == 1]
    neg = [s for s, l in pairs if l == 0]
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for ps in pos:
        for ns in neg:
            if ps > ns:
                wins += 1
            elif ps == ns:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def _block_bootstrap_ci_low(
    values: list[float], block_size: int = 252, iters: int = 1000
) -> float:
    """Lower bound of the 95% block-bootstrap CI on the median."""
    if not values:
        return float("nan")
    arr = np.array(values, dtype=float)
    n = len(arr)
    rng = np.random.default_rng(seed=42)
    if n < block_size:
        meds = [np.median(rng.choice(arr, size=n, replace=True)) for _ in range(iters)]
        return float(np.percentile(meds, 2.5))
    n_blocks = n // block_size
    medians = []
    for _ in range(iters):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        sample = np.concatenate([arr[s : s + block_size] for s in starts])
        medians.append(np.median(sample))
    return float(np.percentile(medians, 2.5))


def _btd_event_stats(all_rows: list[dict], emitted_events: list) -> dict:
    """Buy-The-Dip event-level statistics — UPSIDE focus.

    Uses real fire dates from CanaryEventState.emitted (NOT warning_state
    transitions). Entry on next close (D+1) per spec §8.1.
    """
    date_to_idx = {r["date"]: i for i, r in enumerate(all_rows)}
    closes = [r["spx"] for r in all_rows]
    drawups: list[float] = []
    lower_lows: list[int] = []
    recoveries: list[int] = []
    for e in emitted_events:
        if e.kind != "buy_the_dip":
            continue
        i = date_to_idx.get(e.fire_date)
        if i is None:
            continue
        entry = i + 1
        if entry + 42 >= len(closes):
            continue
        window = closes[entry + 1 : entry + 43]
        drawups.append(max(window) / closes[entry] - 1)
        ll_window = closes[entry + 1 : entry + 31]
        lower_lows.append(1 if any(c < closes[entry] for c in ll_window) else 0)
        rec_window = closes[entry + 1 : entry + 61]
        if rec_window:
            high_at_entry = max(closes[max(0, entry - 252) : entry + 1])
            recoveries.append(1 if max(rec_window) >= high_at_entry else 0)
    return {
        "n_events": len(drawups),
        "median_fwd_42d_drawup": float(np.median(drawups)) if drawups else None,
        "lower_low_30d_rate": (
            sum(lower_lows) / len(lower_lows) if lower_lows else None
        ),
        "recovery_60d_rate": (
            sum(recoveries) / len(recoveries) if recoveries else None
        ),
        "ci_low_drawup": _block_bootstrap_ci_low(drawups) if drawups else None,
    }


def _confirmed_canary_event_stats(all_rows: list[dict], emitted_events: list) -> dict:
    """Confirmed Canary event-level statistics — DOWNSIDE focus."""
    date_to_idx = {r["date"]: i for i, r in enumerate(all_rows)}
    closes = [r["spx"] for r in all_rows]
    drawdowns: list[float] = []
    further_down: list[int] = []
    for e in emitted_events:
        if e.kind != "confirmed_canary":
            continue
        i = date_to_idx.get(e.fire_date)
        if i is None:
            continue
        entry = i + 1
        if entry + 60 >= len(closes):
            continue
        window42 = closes[entry + 1 : entry + 43]
        drawdowns.append(min(window42) / closes[entry] - 1)
        window60 = closes[entry + 1 : entry + 61]
        further_down.append(1 if min(window60) <= closes[entry] * 0.95 else 0)
    return {
        "n_events": len(drawdowns),
        "median_fwd_42d_drawdown": (float(np.median(drawdowns)) if drawdowns else None),
        "further_drawdown_60d_rate": (
            sum(further_down) / len(further_down) if further_down else None
        ),
        "ci_low_drawdown": (_block_bootstrap_ci_low(drawdowns) if drawdowns else None),
    }


def cmd_form_sweep(conn, *, write_summary: bool) -> None:
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    bt_repo = RegimeBacktestRepository(conn)
    aucs_per_form: dict[str, dict[str, float]] = {}

    LABELS = [
        ("up5d_2pct", 5, 0.02),
        ("up20d_5pct", 20, 0.05),
        ("up60d_10pct", 60, 0.10),
    ]

    for form in ("linear", "convex", "concave", "sigmoid"):
        series = _compute_canary_series(
            conn, cal, form=form, start=VALID_START, end=VALID_END
        )
        rows = series["eval_rows"]
        scores = [r["score"] for r in rows]
        auc_map = {}
        for label_name, h, thr in LABELS:
            labels = _entry_lagged_label(rows, h, thr)
            auc_map[label_name] = _auc(scores, labels)
        aucs_per_form[form] = auc_map
        if write_summary and rows:
            run_id = bt_repo.insert_run(
                indicator="canary",
                composite_version=str(COMPOSITE_VERSION),
                start_date=rows[0]["date"],
                end_date=rows[-1]["date"],
                window_days=350,
                n_days=len(rows),
                params={"score_form": form, "phase": "form_sweep"},
                summary={
                    "validation_aucs": auc_map,
                    "is_winning_form": False,
                    "score_form": form,
                },
            )
            bt_repo.bulk_insert_daily(
                run_id,
                [
                    {
                        "trade_date": r["date"],
                        "score": r["score"],
                        "level": r["band"],
                        "payload": {
                            "raw_score": r["score"],
                            "tactical": r["tactical"],
                            "structural": r["structural"],
                            "speed": r["speed"],
                            "warning_state": r["warning_state"],
                        },
                    }
                    for r in rows
                ],
            )
            bt_repo.mark_run_completed(run_id)

    base = aucs_per_form["linear"]
    winner = "linear"
    for form, aucs in aucs_per_form.items():
        if form == "linear":
            continue
        beats = sum(
            1
            for label_name, _, _ in LABELS
            if aucs[label_name] >= base[label_name] + 0.02
        )
        if beats >= 2:
            winner = form
            break
    log.info("validation AUCs: %s", json.dumps(aucs_per_form, indent=2))
    log.info("winning form: %s", winner)

    cal_raw = json.loads(CALIB_PATH.read_text())
    cal_raw["score_form"] = winner
    cal_raw["validation_aucs_per_form"] = aucs_per_form
    CALIB_PATH.write_text(json.dumps(cal_raw, indent=2) + "\n")


def cmd_report(conn, *, form, write_summary: bool) -> None:
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    selected_form = form or cal.score_form
    bt_repo = RegimeBacktestRepository(conn)
    series = _compute_canary_series(
        conn, cal, form=selected_form, start=TEST_START, end=date.today()
    )
    eval_rows = series["eval_rows"]
    all_rows = series["all_rows"]
    events = series["events"]
    if not eval_rows:
        raise RuntimeError(
            "no eval rows produced — check that calibration window matches available data"
        )
    scores = [r["score"] for r in eval_rows]
    LABELS = [
        ("up5d_2pct", 5, 0.02),
        ("up20d_5pct", 20, 0.05),
        ("up60d_10pct", 60, 0.10),
    ]
    daily_aucs = {}
    for label_name, h, thr in LABELS:
        labels = _entry_lagged_label(eval_rows, h, thr)
        daily_aucs[label_name] = _auc(scores, labels)

    speed_scores = [r["speed"] for r in eval_rows]
    vol_scores = [r["tactical"] + r["structural"] for r in eval_rows]
    ablation = {
        "speed_only_aucs": {
            name: _auc(speed_scores, _entry_lagged_label(eval_rows, h, thr))
            for name, h, thr in LABELS
        },
        "vol_only_aucs": {
            name: _auc(vol_scores, _entry_lagged_label(eval_rows, h, thr))
            for name, h, thr in LABELS
        },
    }
    band_counts = {
        b: sum(1 for r in eval_rows if r["band"] == b)
        for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    }
    summary = {
        "daily_aucs": daily_aucs,
        "ablation": ablation,
        "band_distribution": band_counts,
        "events": {
            "buy_the_dip": _btd_event_stats(all_rows, events),
            "confirmed_canary": _confirmed_canary_event_stats(all_rows, events),
        },
        "is_winning_form": True,
        "score_form": selected_form,
    }
    run_id = bt_repo.insert_run(
        indicator="canary",
        composite_version=str(COMPOSITE_VERSION),
        start_date=eval_rows[0]["date"],
        end_date=eval_rows[-1]["date"],
        window_days=350,
        n_days=len(eval_rows),
        params={"score_form": selected_form, "phase": "final_oos_report"},
        summary=summary,
    )
    bt_repo.bulk_insert_daily(
        run_id,
        [
            {
                "trade_date": r["date"],
                "score": r["score"],
                "level": r["band"],
                "payload": {
                    "tactical": r["tactical"],
                    "structural": r["structural"],
                    "speed": r["speed"],
                    "warning_state": r["warning_state"],
                },
            }
            for r in eval_rows
        ],
    )
    bt_repo.mark_run_completed(run_id)
    log.info("persisted final OOS canary backtest run_id=%d", run_id)
    log.info("final OOS summary: %s", json.dumps(summary, indent=2))


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--form-sweep", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--form", choices=("linear", "convex", "concave", "sigmoid"))
    args = parser.parse_args()

    settings = Settings.from_env()
    with connect(settings.db_dsn()) as conn:
        if args.calibrate:
            cmd_calibrate(conn)
            return
        if args.form_sweep:
            cmd_form_sweep(conn, write_summary=args.write_summary)
            return
        if args.report:
            cmd_report(conn, form=args.form, write_summary=args.write_summary)
            return
        parser.print_help()
        sys.exit(2)


# Entry point — must stay at file bottom so all cmd_* are defined when this runs.
if __name__ == "__main__":
    main()
