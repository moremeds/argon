"""Tier-1 skew markout: bucket snapshots, score forward returns, write verdicts.

Two hypotheses (spec §7 step 2):
  PRIMARY   — RV mean-reversion: does extreme RR (RICH/CHEAP) revert? Measured as
              mean forward dRR per (asset_class, deviation_class); REPORTED in the
              return dict for the research note, not gated into a verdict.
  SECONDARY — directional, borrow-conditioned: do buckets separate forward STOCK
              returns on the borrow-clean subset? Gated into TRADABLE_* verdicts.

A bucket (asset_class, deviation_class, drive_class) earns TRADABLE_BULL/
TRADABLE_BEAR only if mean T+20 forward return on the borrow-clean subset is
material (|mean| >= sep_threshold), n >= min_n, and survives the per-TIME-WINDOW
catastrophic-degradation gate. Otherwise NONE. NONE/absent => NEUTRAL lean.

Regime left the bucket key (migration 076): with ~13mo of data it fragmented the
sample so no bucket cleared n>=min_n. Regime robustness now rests entirely on the
quarterly catastrophic-degradation gate; the canonical CRI level is the live regime
tag, not a backtest slicer. See docs/superpowers/plans/2026-06-16-skew-hardening.md.

Forward horizons are TRADING-day offsets (the nth row after the anchor in the
per-ticker trading series), NOT calendar days.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from typing import Any

from uw_scan.backtest.gates import walkforward_gate
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

HORIZON = 20  # trading days for the canonical separation horizon

RV_HOLDOUT_FRAC = 0.40  # time-ordered tail fraction held out for the OOS check
RV_MIN_N = 30  # min obs to even consider an RV verdict
RV_SEP_THRESHOLD = 0.005  # |mean ΔRR| floor (full sample)
RV_HOLDOUT_THRESHOLD = 0.003  # |mean ΔRR| floor on the holdout


def _expected_drr_sign(deviation_class: str) -> int:
    """CHEAP re-richens (+), RICH flattens (-), else no directional reversion claim."""
    if deviation_class == "CHEAP":
        return 1
    if deviation_class == "RICH":
        return -1
    return 0


def _rv_walkforward(obs: list[dict], expected_sign: int) -> dict:
    """obs: [{'drr': float, 'market_date': date}], any order. Returns the verdict dict.
    REVERTS requires expected sign + magnitude (full & holdout) AND the quarterly
    catastrophic-degradation gate. Delegates to uw_scan.backtest.gates; this
    adapter only maps key names and the verdict string."""
    n = len(obs)
    if n < RV_MIN_N or expected_sign == 0:
        return {
            "verdict": "NONE",
            "mean_drr": None,
            "mean_drr_holdout": None,
            "n": n,
            "n_holdout": 0,
            "survives_walkforward": False,
            "survives_window_gate": False,
        }
    wf = walkforward_gate(
        obs,
        value_key="drr",
        min_n=RV_MIN_N,
        threshold=RV_SEP_THRESHOLD,
        holdout_threshold=RV_HOLDOUT_THRESHOLD,
        holdout_frac=RV_HOLDOUT_FRAC,
        expected_sign=expected_sign,
    )
    reverts = wf["survives_walkforward"] and wf["survives_window_gate"]
    return {
        "verdict": "REVERTS" if reverts else "NONE",
        "mean_drr": wf["mean"],
        "mean_drr_holdout": wf["mean_holdout"],
        "n": wf["n"],
        "n_holdout": wf["n_holdout"],
        "survives_walkforward": wf["survives_walkforward"],
        "survives_window_gate": wf["survives_window_gate"],
    }


def _forward_value_at(
    series: list[tuple[_date, float]], anchor: _date, n: int
) -> float | None:
    """nth TRADING-day-ahead value: the (n-1)th element strictly after `anchor`
    in the ASC per-ticker trading series. None if fewer than n forward rows."""
    fwd = [v for (d, v) in series if d > anchor]
    if len(fwd) < n:
        return None
    return fwd[n - 1]


def _confidence(n: int, sep: float) -> str:
    """Capped at 'med' on purpose. The borrow-clean subset is filtered on the
    snapshot's borrow_flag, which for backfilled dates is CURRENT borrow applied to
    historical anchors (point-in-time borrow history is unavailable — spec §11). So
    "edge is not a borrow artifact" is an approximation, not a clean point-in-time
    claim, and the borrow fee is the dominant confound for option-signal return
    predictability (Muravyev-Pearson-Pollet 2025). A directional skew lean is a tilt,
    not a high-conviction forecast (design §11 'lean over-trust'); never emit 'high'."""
    if n >= 25 and abs(sep) >= 0.01:
        return "med"
    return "low"


def run_skew_markout(
    *, repo: Repository, min_n: int = 20, sep_threshold: float = 0.01
) -> dict[str, Any]:
    """Score all snapshots and (re)write the verdict store. Idempotent."""
    snaps = _all_snapshots(repo)
    tickers = {s["ticker"] for s in snaps}
    price_by_ticker = {t: _price_series(repo, t) for t in tickers}
    rr_by_ticker = {t: _rr_series(repo, t) for t in tickers}

    # CROSS-SECTIONAL neutralization. We measure each name's forward return in
    # EXCESS of the universe average forward return ON THE SAME DATE. This removes
    # both market beta AND the common high-beta drift of this growth-heavy universe
    # — a verdict then reflects skew SEPARATION vs peers, not "everything rose in a
    # bull-market backfill window." (Subtracting SPY alone leaves the beta>1 drift.)
    # Pass 1: raw forward return per obs + accumulate the daily cross-section.
    raw_obs: list[dict] = []
    by_date_returns: dict[_date, list[float]] = defaultdict(list)
    meanrev: dict[tuple, list[dict]] = defaultdict(list)  # primary (RV; tail-split)
    for s in snaps:
        spot = s.get("spot")
        if spot is not None and float(spot) != 0:
            fwd_px = _forward_value_at(
                price_by_ticker.get(s["ticker"], []), s["market_date"], HORIZON
            )
            if fwd_px is not None:
                raw = fwd_px / float(spot) - 1.0
                raw_obs.append(
                    {
                        "raw": raw,
                        "market_date": s["market_date"],
                        "key": (
                            s["asset_class"],
                            s["deviation_class"],
                            s["drive_class"],
                        ),
                        "clean": s.get("borrow_flag") != "hard_to_borrow",
                    }
                )
                by_date_returns[s["market_date"]].append(raw)
        rr0 = s.get("rr_25d")
        if rr0 is not None:
            fwd_rr = _forward_value_at(
                rr_by_ticker.get(s["ticker"], []), s["market_date"], HORIZON
            )
            if fwd_rr is not None:
                tail = (
                    "put_skew"
                    if float(rr0) > 0
                    else ("call_skew" if float(rr0) < 0 else "flat")
                )
                meanrev[(s["asset_class"], s["deviation_class"], tail)].append(
                    {"drr": fwd_rr - float(rr0), "market_date": s["market_date"]}
                )

    # Pass 2: cross-sectional demean — excess = raw - mean(all raw on that date).
    daily_mean = {
        d: (sum(v) / len(v) if v else 0.0) for d, v in by_date_returns.items()
    }
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for o in raw_obs:
        buckets[o["key"]].append(
            {
                "fwd": o["raw"] - daily_mean[o["market_date"]],
                "clean": o["clean"],
                "market_date": o["market_date"],
            }
        )

    today = _date.today()
    written = 0
    for key, obs in buckets.items():
        asset_class, deviation_class, drive_class = key
        clean = [o for o in obs if o["clean"]]
        n = len(clean)
        sep = sum(o["fwd"] for o in clean) / n if n else 0.0
        survives = _survives_window_gate(clean, sep)
        material = n >= min_n and abs(sep) >= sep_threshold and survives
        if material and sep < 0:
            verdict = "TRADABLE_BEAR"
        elif material and sep > 0:
            verdict = "TRADABLE_BULL"
        else:
            verdict = "NONE"
        repo.upsert_skew_directional_verdict(
            asset_class=asset_class,
            deviation_class=deviation_class,
            drive_class=drive_class,
            verdict=verdict,
            confidence=_confidence(n, sep) if verdict != "NONE" else "low",
            forward_sep=sep,
            n=n,
            borrow_clean=True,
            survives_gate=survives,
            as_of=today,
        )
        written += 1

    # RV mean-reversion (primary hypothesis), now GATED into a persisted verdict per
    # (asset_class, deviation_class, tail) with the walk-forward + catastrophic gate.
    rv_written = 0
    rv_report: dict[str, dict] = {}
    for (asset_class, deviation_class, tail), drr_obs in meanrev.items():
        wf = _rv_walkforward(drr_obs, _expected_drr_sign(deviation_class))
        repo.upsert_skew_rv_reversion_verdict(
            asset_class=asset_class,
            deviation_class=deviation_class,
            tail=tail,
            verdict=wf["verdict"],
            mean_drr=wf["mean_drr"],
            mean_drr_holdout=wf["mean_drr_holdout"],
            n=wf["n"],
            n_holdout=wf["n_holdout"],
            survives_walkforward=wf["survives_walkforward"],
            survives_window_gate=wf["survives_window_gate"],
            as_of=today,
        )
        rv_written += 1
        rv_report[f"{asset_class}/{deviation_class}/{tail}"] = wf

    mean_reversion = {
        f"{a}/{d}/{t}": {
            "mean_dRR": (sum(o["drr"] for o in v) / len(v) if v else None),
            "n": len(v),
        }
        for (a, d, t), v in meanrev.items()
    }
    repo.conn.commit()
    log.info(
        "run_skew_markout wrote %d directional + %d rv verdicts over %d snapshots",
        written,
        rv_written,
        len(snaps),
    )
    return {
        "verdicts_written": written,
        "rv_verdicts_written": rv_written,
        "snapshots": len(snaps),
        "mean_reversion": mean_reversion,  # PRIMARY hypothesis, descriptive
        "rv_reversion": rv_report,  # PRIMARY hypothesis, now gated + walk-forward
    }


def _survives_window_gate(clean: list[dict], overall_sep: float) -> bool:
    """Per-TIME-WINDOW catastrophic-degradation gate (memory:
    feedback_per_regime_catastrophic_gate). Partition the bucket's borrow-clean
    obs by CALENDAR QUARTER; fail if any quarter reverses the aggregate sign with
    LARGER magnitude — i.e. the aggregate is hiding a sub-window blowup. (Keying
    by regime would be a no-op since the bucket is already single-regime.)"""
    if abs(overall_sep) < 1e-9:
        return False
    by_q: dict[tuple, list[float]] = defaultdict(list)
    for o in clean:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o["fwd"])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_sep < 0 and abs(m) > abs(overall_sep):
            return False
    return True


def _all_snapshots(repo: Repository) -> list[dict[str, Any]]:
    sql = (
        "SELECT ticker, market_date, spot, rr_25d, asset_class, deviation_class, "
        "drive_class, regime, borrow_flag "
        f"FROM {repo._schema}.skew_analytics_snapshot WHERE basis='eod'"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def _price_series(repo: Repository, ticker: str) -> list[tuple[_date, float]]:
    sql = (
        "SELECT market_date, price "
        f"FROM {repo._schema}.realized_volatility_history "
        "WHERE ticker=%s AND price IS NOT NULL ORDER BY market_date ASC"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        return [(r[0], float(r[1])) for r in cur.fetchall()]


def _rr_series(repo: Repository, ticker: str) -> list[tuple[_date, float]]:
    """Front-expiry RR series (DISTINCT ON market_date) for forward-dRR mean-reversion."""
    sql = (
        "SELECT DISTINCT ON (market_date) market_date, risk_reversal "
        f"FROM {repo._schema}.risk_reversal_skew_history "
        "WHERE ticker=%s AND delta=25 AND risk_reversal IS NOT NULL "
        "ORDER BY market_date ASC, expiry ASC NULLS LAST"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        return [(r[0], float(r[1])) for r in cur.fetchall()]
