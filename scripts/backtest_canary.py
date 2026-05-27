"""5% Canary backtest harness.

Five modes — see docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §7, §8
and docs/research/regime/canary-5yr-executive-summary.md §6, §7.

  --calibrate         Compute Class B thresholds on the train window (2007-2014),
                      write canary-calibration-v1.json.
  --form-sweep        Sweep four scoring forms on the validation window (2015-2019),
                      persist per-form results to regime_backtest_runs, pick winner.
  --report            Compute final OOS report on the test window (2020-present),
                      persist with summary.is_winning_form=true.
  --walk-forward      6-window expanding-train walk-forward (frozen v1 calibration).
                      Persists one row per window with params.phase='walk_forward'.
  --robustness        Full-dataset robustness report — composite vs vol-only across
                      exclusion regimes (no 2020-Q4, no 2026 live), AUC-by-year,
                      AUC-by-band, true event-fire stats, block-bootstrap AUC CI.
                      Persists one row with params.phase='robustness'.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
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

REPO_ROOT = Path(__file__).resolve().parents[1]
V2_CAL_PATH = REPO_ROOT / "docs" / "research" / "regime" / "canary-calibration-v2.json"

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


def cmd_calibrate(conn, *, schema: str) -> None:
    """Compute Class B thresholds (p25 floor, p90 ceiling) on the train window
    using positive-condition observations only. Write canary-calibration-v1.json.
    """
    from uw_scan.storage.vol_index_repository import VolIndexRepository

    vol_repo = VolIndexRepository(conn, schema=schema)

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
    conn,
    calibration,
    form: str,
    start: date,
    end: date,
    *,
    schema: str,
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

    vol_repo = VolIndexRepository(conn, schema=schema)
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
    pairs = [(s, lbl) for s, lbl in zip(scores, labels) if lbl is not None]
    if not pairs:
        return float("nan")
    pos = [s for s, lbl in pairs if lbl == 1]
    neg = [s for s, lbl in pairs if lbl == 0]
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


def cmd_form_sweep(conn, *, write_summary: bool, schema: str) -> None:
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    aucs_per_form: dict[str, dict[str, float]] = {}

    LABELS = [
        ("up5d_2pct", 5, 0.02),
        ("up20d_5pct", 20, 0.05),
        ("up60d_10pct", 60, 0.10),
    ]

    for form in ("linear", "convex", "concave", "sigmoid"):
        series = _compute_canary_series(
            conn,
            cal,
            form=form,
            start=VALID_START,
            end=VALID_END,
            schema=schema,
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


def cmd_form_sweep_full(conn, *, schema: str) -> None:
    """Full-history candidate-discovery sweep across all 4 score forms.

    Thin wrapper — delegates to
    `uw_scan.reports.regime_canary_form_sweep_full.run_form_sweep_full`.
    Passes existing helpers through a dependency container so the
    package module does not import this script.
    """
    from uw_scan.reports.regime_canary_form_sweep_full import (
        CanaryFormSweepDeps,
        run_form_sweep_full,
    )

    deps = CanaryFormSweepDeps(
        compute_canary_series=_compute_canary_series,
        aucs_for_rows=_aucs_for_rows,
        band_counts=_band_counts,
        block_bootstrap_auc_ci=_block_bootstrap_auc_ci,
        clean_nans=_clean_nans,
        entry_lagged_label=_entry_lagged_label,
        auc=_auc,
        label_specs=LABEL_SPECS,
        composite_version=COMPOSITE_VERSION,
    )
    run_form_sweep_full(conn, schema=schema, deps=deps)


def cmd_report(conn, *, form, write_summary: bool, schema: str) -> None:
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    selected_form = form or cal.score_form
    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    series = _compute_canary_series(
        conn,
        cal,
        form=selected_form,
        start=TEST_START,
        end=date.today(),
        schema=schema,
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


# ---------------------------------------------------------------------------
# Walk-forward + robustness (added 2026-05-27 per exec-summary §6, §7)
# ---------------------------------------------------------------------------

# 6 expanding-window OOS panes against the full 2011-02-08 → today backfill.
# Train ranges are informational only — v1 calibration is reused across all
# windows. True per-window recalibration is a deferred follow-up (see §9 of
# the exec summary).
WALK_FORWARD_WINDOWS: list[dict] = [
    {
        "id": "WF-1",
        "train_end": date(2014, 12, 31),
        "oos_start": date(2015, 1, 1),
        "oos_end": date(2016, 12, 31),
        "label": "China devaluation, Brexit",
    },
    {
        "id": "WF-2",
        "train_end": date(2016, 12, 31),
        "oos_start": date(2017, 1, 1),
        "oos_end": date(2018, 12, 31),
        "label": "Volmageddon, Q4-18 selloff",
    },
    {
        "id": "WF-3",
        "train_end": date(2018, 12, 31),
        "oos_start": date(2019, 1, 1),
        "oos_end": date(2020, 9, 30),
        "label": "Repo crisis, COVID crash",
    },
    {
        "id": "WF-4",
        "train_end": date(2020, 9, 30),
        "oos_start": date(2020, 10, 1),
        "oos_end": date(2022, 12, 31),
        "label": "Post-COVID, 2022 inflation",
    },
    {
        "id": "WF-5",
        "train_end": date(2022, 12, 31),
        "oos_start": date(2023, 1, 1),
        "oos_end": date(2024, 12, 31),
        "label": "Bond-yield selloff, 2024 quiet",
    },
    {
        "id": "WF-6",
        "train_end": date(2024, 12, 31),
        "oos_start": date(2025, 1, 1),
        "oos_end": date.today(),
        "label": "2025 tariff, 2026 dip (live)",
    },
]

LABEL_SPECS: list[tuple[str, int, float]] = [
    ("up5d_2pct", 5, 0.02),
    ("up20d_5pct", 20, 0.05),
    ("up60d_10pct", 60, 0.10),
]


def _clean_nans(obj):
    """Recursively replace NaN floats with None so Postgres JSONB accepts.

    Postgres rejects 'NaN' tokens inside json columns; by-band AUCs can be
    NaN when the labels in a subset are all 0 or all 1.
    """
    if isinstance(obj, dict):
        return {k: _clean_nans(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean_nans(v) for v in obj]
    if isinstance(obj, float) and obj != obj:  # NaN check
        return None
    return obj


def _aucs_for_rows(rows: list[dict]) -> dict[str, dict[str, float]]:
    """Composite / speed-only / vol-only AUCs at 3 horizons over `rows`."""
    if not rows:
        return {"composite": {}, "speed_only": {}, "vol_only": {}}
    composite_scores = [r["score"] for r in rows]
    speed_scores = [r["speed"] for r in rows]
    vol_scores = [r["tactical"] + r["structural"] for r in rows]
    out = {"composite": {}, "speed_only": {}, "vol_only": {}}
    for name, h, thr in LABEL_SPECS:
        labels = _entry_lagged_label(rows, h, thr)
        out["composite"][name] = _auc(composite_scores, labels)
        out["speed_only"][name] = _auc(speed_scores, labels)
        out["vol_only"][name] = _auc(vol_scores, labels)
    return out


def _band_counts(rows: list[dict]) -> dict[str, int]:
    return {
        b: sum(1 for r in rows if r["band"] == b)
        for b in ("NONE", "WATCH", "BUY", "STRONG_BUY")
    }


def _block_bootstrap_auc_ci(
    scores: list[float],
    labels: list,
    *,
    block_size: int = 20,
    iters: int = 1000,
) -> tuple[float, float]:
    """Block-bootstrap 95% CI on AUC.

    Sampling preserves daily autocorrelation by drawing contiguous blocks of
    (score, label) tuples. Returns (lo, hi) at the 2.5 / 97.5 percentiles.
    Returns (nan, nan) when AUC isn't computable.
    """
    pairs = [(s, lbl) for s, lbl in zip(scores, labels) if lbl is not None]
    n = len(pairs)
    if n < block_size * 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed=42)
    n_blocks = n // block_size
    aucs: list[float] = []
    for _ in range(iters):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        sample_scores: list[float] = []
        sample_labels: list = []
        for s in starts:
            for j in range(block_size):
                sample_scores.append(pairs[s + j][0])
                sample_labels.append(pairs[s + j][1])
        a = _auc(sample_scores, sample_labels)
        if a == a:  # filter NaN
            aucs.append(a)
    if not aucs:
        return (float("nan"), float("nan"))
    return (float(np.percentile(aucs, 2.5)), float(np.percentile(aucs, 97.5)))


def _summarize_window(
    window_id: str,
    eval_rows: list[dict],
    all_rows: list[dict],
    events: list,
    *,
    score_form: str,
) -> dict:
    aucs = _aucs_for_rows(eval_rows)
    composite_scores = [r["score"] for r in eval_rows]
    btd_n = sum(1 for e in events if e.kind == "buy_the_dip")
    cca_n = sum(1 for e in events if e.kind == "confirmed_canary")
    auc_cis: dict[str, list[float]] = {}
    for name, h, thr in LABEL_SPECS:
        labels = _entry_lagged_label(eval_rows, h, thr)
        lo, hi = _block_bootstrap_auc_ci(composite_scores, labels)
        auc_cis[name] = [lo, hi]
    return {
        "window_id": window_id,
        "score_form": score_form,
        "aucs": aucs,
        "auc_ci95": auc_cis,
        "band_distribution": _band_counts(eval_rows),
        "events": {
            "buy_the_dip": _btd_event_stats(all_rows, events),
            "confirmed_canary": _confirmed_canary_event_stats(all_rows, events),
        },
        "event_fire_counts": {"btd": btd_n, "cca": cca_n},
        "n_days": len(eval_rows),
    }


def cmd_walk_forward(conn, *, schema: str, args=None) -> None:
    """6-window expanding-train walk-forward with frozen calibration.

    Writes one regime_backtest_runs row per window so each window's summary
    can be inspected independently. v2 invocation (when
    args.composite_version == 2) loads canary-calibration-v2.json, forces
    run_scope='research', persists composite_version=str(cal.composite_version),
    and tags every params dict with a batch_id (generated once per call).

    The batch_id is printed to stdout so callers can chain --robustness
    with --batch-id.
    """
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    if args is None:
        args = argparse.Namespace(composite_version=1, batch_id=None)

    if args.composite_version == 2:
        cal = load_calibration(path=V2_CAL_PATH)
        run_scope = "research"
    else:
        cal = load_calibration()
        run_scope = "production"

    batch_id = args.batch_id or str(uuid.uuid4())
    print(f"walk-forward batch_id={batch_id}")

    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    score_form = cal.score_form

    window_summaries = []
    for win in WALK_FORWARD_WINDOWS:
        log.info(
            "walk-forward: %s OOS %s → %s (%s)",
            win["id"],
            win["oos_start"],
            win["oos_end"],
            win["label"],
        )
        series = _compute_canary_series(
            conn,
            cal,
            form=score_form,
            start=win["oos_start"],
            end=win["oos_end"],
            schema=schema,
        )
        eval_rows = series["eval_rows"]
        all_rows = series["all_rows"]
        events = series["events"]
        if not eval_rows:
            log.warning("walk-forward: %s has zero eval rows — skipping", win["id"])
            continue
        summary = _summarize_window(
            win["id"],
            eval_rows,
            all_rows,
            events,
            score_form=score_form,
        )
        summary["macro_label"] = win["label"]
        summary["train_end"] = win["train_end"].isoformat()
        run_id = bt_repo.insert_run(
            indicator="canary",
            composite_version=str(cal.composite_version),
            start_date=eval_rows[0]["date"],
            end_date=eval_rows[-1]["date"],
            window_days=350,
            n_days=len(eval_rows),
            params={
                "score_form": score_form,
                "phase": "walk_forward",
                "window_id": win["id"],
                "train_end": win["train_end"].isoformat(),
                "batch_id": batch_id,
            },
            summary=_clean_nans(summary),
            run_scope=run_scope,
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
        log.info(
            "  → run_id=%d composite_AUC=%.3f/%.3f/%.3f vol_only=%.3f/%.3f/%.3f n_btd=%d n_cca=%d",
            run_id,
            summary["aucs"]["composite"]["up5d_2pct"],
            summary["aucs"]["composite"]["up20d_5pct"],
            summary["aucs"]["composite"]["up60d_10pct"],
            summary["aucs"]["vol_only"]["up5d_2pct"],
            summary["aucs"]["vol_only"]["up20d_5pct"],
            summary["aucs"]["vol_only"]["up60d_10pct"],
            summary["event_fire_counts"]["btd"],
            summary["event_fire_counts"]["cca"],
        )
        window_summaries.append(summary)

    # Aggregate pass/fail per revised criteria
    PASS_60D = 0.58
    PASS_20D = 0.55
    log.info("=" * 78)
    log.info("WALK-FORWARD SUMMARY (frozen v1 calibration, score_form=%s)", score_form)
    log.info("=" * 78)
    log.info(
        "%-6s %-32s %7s %7s %7s %5s %5s %s",
        "Win",
        "Macro",
        "AUC5d",
        "AUC20d",
        "AUC60d",
        "BTDn",
        "CCAn",
        "Verdict",
    )
    primary_passes = 0
    secondary_passes = 0
    for s in window_summaries:
        a = s["aucs"]["composite"]
        prim = a["up60d_10pct"] >= PASS_60D
        sec = a["up20d_5pct"] >= PASS_20D
        if prim:
            primary_passes += 1
        if sec:
            secondary_passes += 1
        verdict = "✓" if prim and sec else ("PARTIAL" if (prim or sec) else "FAIL")
        log.info(
            "%-6s %-32s %7.3f %7.3f %7.3f %5d %5d %s",
            s["window_id"],
            s["macro_label"][:32],
            a["up5d_2pct"],
            a["up20d_5pct"],
            a["up60d_10pct"],
            s["event_fire_counts"]["btd"],
            s["event_fire_counts"]["cca"],
            verdict,
        )
    log.info("-" * 78)
    log.info(
        "Primary (60d ≥ %.2f): %d / %d windows pass",
        PASS_60D,
        primary_passes,
        len(window_summaries),
    )
    log.info(
        "Secondary (20d ≥ %.2f): %d / %d windows pass",
        PASS_20D,
        secondary_passes,
        len(window_summaries),
    )
    log.info(
        "Regime-robust = primary passes majority (%d / %d)",
        primary_passes,
        len(window_summaries),
    )


def cmd_robustness(conn, *, schema: str, args=None) -> None:
    """Robustness report against the full backfilled dataset.

    Produces a single regime_backtest_runs row whose summary has nested
    subsections for full / no-2020Q4 / no-2026 exclusion subsets, plus
    AUC-by-year and AUC-by-band breakdowns and bootstrap CIs.

    v2 invocation (args.composite_version == 2) loads v2 calibration,
    forces run_scope='research', persists composite_version=2, and tags
    params.batch_id with args.batch_id (or a freshly-generated UUID4).
    """
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    if args is None:
        args = argparse.Namespace(composite_version=1, batch_id=None)

    if args.composite_version == 2:
        cal = load_calibration(path=V2_CAL_PATH)
        run_scope = "research"
    else:
        cal = load_calibration()
        run_scope = "production"

    batch_id = args.batch_id or str(uuid.uuid4())
    print(f"robustness batch_id={batch_id}")

    bt_repo = RegimeBacktestRepository(conn, schema=schema)
    score_form = cal.score_form

    # Run scoring against the full window once, then slice subsets in-memory.
    series = _compute_canary_series(
        conn,
        cal,
        form=score_form,
        start=date(2011, 2, 8),
        end=date.today(),
        schema=schema,
    )
    all_rows = series["eval_rows"]
    events = series["events"]
    if not all_rows:
        raise RuntimeError("robustness: no eval rows produced")

    def _subset(
        start: date | None,
        end: date | None,
        exclude_start: date | None = None,
        exclude_end: date | None = None,
    ) -> list[dict]:
        out = []
        for r in all_rows:
            d = r["date"]
            if start and d < start:
                continue
            if end and d > end:
                continue
            if exclude_start and exclude_end and exclude_start <= d <= exclude_end:
                continue
            out.append(r)
        return out

    full = all_rows
    no_2020q4 = _subset(
        None, None, exclude_start=date(2020, 10, 1), exclude_end=date(2020, 12, 31)
    )
    no_2026_live = _subset(None, date(2025, 12, 31))

    def _section(rows: list[dict], label: str) -> dict:
        aucs = _aucs_for_rows(rows)
        composite = [r["score"] for r in rows]
        cis = {}
        for name, h, thr in LABEL_SPECS:
            lab = _entry_lagged_label(rows, h, thr)
            cis[name] = list(_block_bootstrap_auc_ci(composite, lab))
        return {
            "label": label,
            "n_days": len(rows),
            "aucs": aucs,
            "auc_ci95": cis,
            "band_distribution": _band_counts(rows),
        }

    # Compute labels once over the FULL series so subset AUCs (by-year, by-
    # band) don't lose the last `horizon_td` days of each subset to None.
    full_labels: dict[str, list] = {
        name: _entry_lagged_label(all_rows, h, thr) for name, h, thr in LABEL_SPECS
    }

    def _auc_for_indices(idxs: list[int]) -> dict[str, float]:
        scores = [all_rows[i]["score"] for i in idxs]
        out: dict[str, float] = {}
        for name in (sp[0] for sp in LABEL_SPECS):
            labels_sub = [full_labels[name][i] for i in idxs]
            out[name] = _auc(scores, labels_sub)
        return out

    # AUC by year — labels evaluated over the full series, then filtered by year
    by_year: dict[str, dict] = {}
    years = sorted({r["date"].year for r in all_rows})
    for yr in years:
        idxs = [i for i, r in enumerate(all_rows) if r["date"].year == yr]
        if len(idxs) < 60:
            continue
        rows_y = [all_rows[i] for i in idxs]
        by_year[str(yr)] = {
            "n_days": len(idxs),
            "aucs": _auc_for_indices(idxs),
            "band_distribution": _band_counts(rows_y),
        }

    # AUC by band — same correction
    by_band: dict[str, dict] = {}
    for band in ("NONE", "WATCH", "BUY"):
        idxs = [i for i, r in enumerate(all_rows) if r["band"] == band]
        if len(idxs) < 60:
            continue
        by_band[band] = {"n_days": len(idxs), "aucs": _auc_for_indices(idxs)}

    # True event-fire stats from state.emitted directly
    btd_fires = [e for e in events if e.kind == "buy_the_dip"]
    cca_fires = [e for e in events if e.kind == "confirmed_canary"]

    summary = {
        "phase": "robustness",
        "score_form": score_form,
        "subsets": {
            "full": _section(full, "Full 2011-02-08 → today"),
            "no_2020q4": _section(no_2020q4, "Excluding 2020-Q4 (anomalous vol-crush)"),
            "no_2026_live": _section(no_2026_live, "Excluding 2026 live period"),
        },
        "aucs_by_year": by_year,
        "aucs_by_band": by_band,
        "event_fires": {
            "buy_the_dip": {
                "n_fires": len(btd_fires),
                "stats": _btd_event_stats(all_rows, events),
                "fire_dates": [e.fire_date.isoformat() for e in btd_fires],
            },
            "confirmed_canary": {
                "n_fires": len(cca_fires),
                "stats": _confirmed_canary_event_stats(all_rows, events),
                "fire_dates": [e.fire_date.isoformat() for e in cca_fires],
            },
        },
    }

    run_id = bt_repo.insert_run(
        indicator="canary",
        composite_version=str(cal.composite_version),
        start_date=all_rows[0]["date"],
        end_date=all_rows[-1]["date"],
        window_days=350,
        n_days=len(all_rows),
        params={
            "score_form": score_form,
            "phase": "robustness",
            "batch_id": batch_id,
        },
        summary=_clean_nans(summary),
        run_scope=run_scope,
    )
    bt_repo.mark_run_completed(run_id)
    log.info("persisted robustness report run_id=%d", run_id)
    log.info("=" * 78)
    log.info("ROBUSTNESS SUMMARY (frozen v1 calibration, score_form=%s)", score_form)
    log.info("=" * 78)
    for key, sec in summary["subsets"].items():
        log.info("%s (n=%d):", sec["label"], sec["n_days"])
        log.info(
            "  composite AUC: 5d=%.3f 20d=%.3f 60d=%.3f",
            sec["aucs"]["composite"]["up5d_2pct"],
            sec["aucs"]["composite"]["up20d_5pct"],
            sec["aucs"]["composite"]["up60d_10pct"],
        )
        log.info(
            "  vol-only  AUC: 5d=%.3f 20d=%.3f 60d=%.3f",
            sec["aucs"]["vol_only"]["up5d_2pct"],
            sec["aucs"]["vol_only"]["up20d_5pct"],
            sec["aucs"]["vol_only"]["up60d_10pct"],
        )
        log.info("  bands: %s", sec["band_distribution"])
    log.info("event fires: btd=%d cca=%d", len(btd_fires), len(cca_fires))


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--form-sweep", action="store_true")
    parser.add_argument(
        "--form-sweep-full",
        action="store_true",
        help="candidate discovery: sweep all 4 forms against full canary_snapshots range",
    )
    parser.add_argument("--report", action="store_true")
    parser.add_argument(
        "--walk-forward",
        action="store_true",
        help="6-window expanding-train walk-forward (frozen v1 calibration)",
    )
    parser.add_argument(
        "--robustness",
        action="store_true",
        help="full-dataset robustness report (exclusion regimes, by-year, by-band)",
    )
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--form", choices=("linear", "convex", "concave", "sigmoid"))
    parser.add_argument(
        "--composite-version",
        type=int,
        choices=(1, 2),
        default=1,
        help="1 (v1, production, default) or 2 (v2-A, research, loads "
        "canary-calibration-v2.json). Plumbs through walk-forward + "
        "robustness + v1-v2-compare. Spec §5.5.",
    )
    parser.add_argument(
        "--batch-id",
        type=str,
        default=None,
        help="Optional batch_id. If omitted, walk-forward generates a UUID4 "
        "(printed to stdout for chaining); robustness/v1-v2-compare require "
        "this to match an existing batch.",
    )
    args = parser.parse_args()

    # CLI-level mutual exclusion (G-1) — argparse doesn't use a group here.
    mode_flags = [
        args.calibrate,
        args.form_sweep,
        args.form_sweep_full,
        args.report,
        args.walk_forward,
        args.robustness,
    ]
    if sum(bool(f) for f in mode_flags) > 1:
        parser.error(
            "only one of --calibrate/--form-sweep/--form-sweep-full/--report/"
            "--walk-forward/--robustness may be specified"
        )

    if args.form_sweep_full and args.form is not None:
        log.warning(
            "--form is ignored under --form-sweep-full (sweep iterates all 4 forms)"
        )

    settings = Settings.from_env()
    schema = settings.db_schema
    with connect(settings.db_dsn()) as conn:
        if args.calibrate:
            cmd_calibrate(conn, schema=schema)
            return
        if args.form_sweep:
            cmd_form_sweep(conn, write_summary=args.write_summary, schema=schema)
            return
        if args.form_sweep_full:
            cmd_form_sweep_full(conn, schema=schema)
            return
        if args.report:
            cmd_report(
                conn,
                form=args.form,
                write_summary=args.write_summary,
                schema=schema,
            )
            return
        if args.walk_forward:
            cmd_walk_forward(conn, schema=schema, args=args)
            return
        if args.robustness:
            cmd_robustness(conn, schema=schema, args=args)
            return
        parser.print_help()
        sys.exit(2)


# Entry point — must stay at file bottom so all cmd_* are defined when this runs.
if __name__ == "__main__":
    main()
