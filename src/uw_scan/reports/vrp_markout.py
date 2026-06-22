"""VRP harvest markout (Spec B) — does selling rich vol earn a reliable premium?

Read-only over vrp_daily (+ flow_events earnings reconstruction); writes
vrp_harvest_verdicts. Mirrors the skew markout's OOS discipline (walk-forward
holdout + per-quarter catastrophic gate) but tests the ABSOLUTE harvest level,
not a cross-sectionally demeaned reversion.

Deliberately does NOT import skew_markout's private helpers: no cross-module
consumer of those underscore-prefixed functions exists in this repo, and the
spec forbids modifying skew_markout.py. The one shared primitive — the
trading-day forward read — is reimplemented here (small, pure, self-contained).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from datetime import timedelta
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.reports.vrp_markout_core import (
    apply_split_adjustment,
    forward_realized_vol,
)
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

# --- Signal thresholds (spec §Signal) -------------------------------------
RICH_Z = 1.0
CHEAP_Z = -1.0

# Forward horizon for the harvest read (spec §Forward target): trailing-21d RV
# read 20 trading days forward ≈ realized vol over [t, t+20]. The earnings
# exclusion window uses the ACTUAL forward trading date (the 20th forward row),
# not a calendar offset — so no separate window-days constant is needed.
HORIZON = 20


def _deviation_class(vrp_z: float | None) -> str | None:
    """RICH/NORMAL/CHEAP from the 20d VRP z-score; None when the signal is null."""
    if vrp_z is None:
        return None
    if vrp_z >= RICH_Z:
        return "RICH"
    if vrp_z <= CHEAP_Z:
        return "CHEAP"
    return "NORMAL"


def _earnings_in_window(t: _date, end: _date, earnings: set[_date]) -> bool:
    """True if any earnings date falls in (t, end] — the forward markout window
    straddles a known earnings event (the short-vol trap we exclude)."""
    return any(t < e <= end for e in earnings)


def _events_overlap(t: _date, end: _date, events: list[tuple[_date, int]]) -> bool:
    """True if any earnings event's [e - buffer_days, e] interval overlaps the
    forward window (t, end] (research expansion item 3). The buffer covers the
    announcement that precedes a filing date; flow-sourced events carry buffer 0
    and reduce to the (t, end] test."""
    for e, buffer in events:
        if e > t and (e - timedelta(days=buffer)) <= end:
            return True
    return False


def _adjusted_forward_rv_fn(adj: list[tuple[_date, float]], horizon: int = HORIZON):
    """Build a forward_fn(ordered_rows, i) -> (end_date, exact_rv) | None for
    _harvest_obs, computing the EXACT corp-action-adjusted realized vol over the
    [t, t+horizon] holding window from the price series (research expansion item
    1). Maps each anchor's date to the price-series index (no positional
    assumption between vrp_daily and the price series); skips anchors whose date
    is absent from the price series."""
    idx = {d: k for k, (d, _v) in enumerate(adj)}

    def forward_fn(ordered_rows: list[dict], i: int):
        pi = idx.get(ordered_rows[i]["market_date"])
        if pi is None:
            return None
        rv = forward_realized_vol(adj, pi, horizon)
        if rv is None:
            return None
        return (adj[pi + horizon][0], rv)

    return forward_fn


def _default_forward_fn(ordered_rows: list[dict], i: int):
    """Default forward read: rv at the EXACT i+HORIZON row (positional). Returns
    (end_date, rv) | None. Preserves the original harvest behavior + its tests."""
    j = i + HORIZON
    if j >= len(ordered_rows):
        return None  # no forward target yet
    fwd = ordered_rows[j]
    if fwd["rv"] is None:
        return None  # exact t+20 RV missing → cannot score this anchor
    return (fwd["market_date"], float(fwd["rv"]))


def _harvest_obs(
    rows: list[dict],
    *,
    earnings: set[_date] | None = None,
    events: list[tuple[_date, int]] | None = None,
    forward_fn=None,
) -> list[dict]:
    """Build realized-VRP observations for one ticker.

    rows: vrp_daily rows [{market_date, iv, rv, vrp_z_20}], any order (one row
    per trading day). realized_VRP(t) = iv(t) - RV_forward(t).

    DEFAULT behavior (no injection): RV_forward(t) = rv at the EXACT i+HORIZON
    row (positional — an interior null RV must not shift the target), and the
    earnings exclusion uses the `earnings` set with (t, end] semantics. This
    preserves the original behavior and its unit tests.

    PRODUCTION injection (research expansion items 1 & 3):
      forward_fn(ordered_rows, i) -> (end_date, rv) | None — exact corp-action-
        adjusted forward RV from the price series (None drops the anchor).
      events: list of (event_date, buffer_days) — buffered earnings exclusion;
        takes precedence over `earnings` when provided.
    Values may be Decimal — coerced to float."""
    ordered = sorted(rows, key=lambda r: r["market_date"])
    fwd_read = forward_fn if forward_fn is not None else _default_forward_fn
    obs: list[dict] = []
    for i, r in enumerate(ordered):
        t = r["market_date"]
        # vrp_z_20 is NULL (never NaN) when undefined — the first ~19 rows per
        # ticker, before the 20d rolling z-score is defined. persist_vrp_daily's
        # _dec converts NaN→None (volatility_series.py), so None is the only
        # "missing" sentinel here and _deviation_class(None) → None → skipped.
        dev = _deviation_class(None if r["vrp_z_20"] is None else float(r["vrp_z_20"]))
        if dev is None or r["iv"] is None:
            continue
        fwd = fwd_read(ordered, i)
        if fwd is None:
            continue
        end_date, fwd_rv = fwd
        if events is not None:
            if _events_overlap(t, end_date, events):
                continue
        elif earnings is not None and _earnings_in_window(t, end_date, earnings):
            continue
        obs.append(
            {
                "market_date": t,
                "deviation_class": dev,
                "realized_vrp": float(r["iv"]) - fwd_rv,
            }
        )
    return obs


# --- OOS hygiene (spec §Out-of-sample hygiene) ----------------------------
MIN_N = 20
HOLDOUT_FRAC = 0.40
HARVEST_THRESHOLD = 0.02  # full-sample floor: 2 vol points; decimal vols (iv/rv ~0.20).
HOLDOUT_THRESHOLD = (
    0.01  # relaxed holdout floor (~half), mirrors skew's 0.003/0.005 ratio.
)


def _survives_quarter_gate(obs: list[dict], overall_mean: float) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (standing rule:
    feedback_per_regime_catastrophic_gate; mirrors skew_markout's window gate).
    Fail if ANY quarter's mean realized_VRP reverses the aggregate sign with
    LARGER magnitude — the aggregate is hiding a sub-window blowup. A near-zero
    aggregate auto-fails (no stable edge to defend)."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple[int, int], list[float]] = defaultdict(list)
    for o in obs:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o["realized_vrp"])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def _walkforward_harvest(
    obs: list[dict],
    *,
    min_n: int = MIN_N,
    threshold: float = HARVEST_THRESHOLD,
    holdout_threshold: float = HOLDOUT_THRESHOLD,
) -> dict:
    """Walk-forward holdout on the ABSOLUTE harvest mean. The harvest claim is
    that mean realized_VRP is POSITIVE (selling rich vol earns premium).

    Descriptive means (mean_realized_vrp, mean_holdout) are ALWAYS computed when
    n >= 1 so a sub-min_n bucket still exposes conditioning evidence (AC3); only
    the gate booleans depend on min_n. survives_walkforward requires: n >= min_n,
    full mean >= threshold, holdout mean >= holdout_threshold, AND full and
    holdout means both positive (spec §OOS 'agree in sign and clear a magnitude
    floor'). survives_window_gate is the per-quarter gate on the full sample.
    Holdout = latest HOLDOUT_FRAC of obs by market_date (time-ordered, no leak).
    obs: [{'realized_vrp': float, 'market_date': date}]."""
    n = len(obs)
    if n == 0:
        return {
            "mean_realized_vrp": None,
            "mean_holdout": None,
            "n": 0,
            "n_holdout": 0,
            "survives_walkforward": False,
            "survives_window_gate": False,
        }
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o["realized_vrp"] for o in ordered) / n
    mean_hold = (
        sum(o["realized_vrp"] for o in holdout) / len(holdout) if holdout else None
    )
    if n < min_n:
        survives_wf = False
        survives_window = False
    else:
        sign_ok = mean_full > 0 and mean_hold is not None and mean_hold > 0
        mag_ok = mean_full >= threshold and (
            mean_hold is not None and mean_hold >= holdout_threshold
        )
        survives_wf = bool(sign_ok and mag_ok)
        survives_window = _survives_quarter_gate(ordered, mean_full)
    return {
        "mean_realized_vrp": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": survives_wf,
        "survives_window_gate": survives_window,
    }


def _all_vrp_tickers(repo: Repository) -> list[str]:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT ticker FROM {repo._schema}.vrp_daily ORDER BY ticker"
        )
        return [r[0] for r in cur.fetchall()]


def _load_vrp_series(repo: Repository, ticker: str) -> list[dict]:
    sql = (
        "SELECT market_date, iv, rv, vrp_z_20 "
        f"FROM {repo._schema}.vrp_daily WHERE ticker = %s ORDER BY market_date ASC"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def run_vrp_markout(*, repo: Repository, min_n: int = MIN_N) -> dict[str, Any]:
    """Score the realized VRP harvest per (asset_class, deviation_class) bucket
    and FULLY REWRITE vrp_harvest_verdicts (prior rows are cleared in the same
    transaction, so a bucket that loses all data never keeps serving a stale
    verdict). Idempotent. Read-only over vrp_daily + flow_events; writes verdicts.
    The decision consumer keys on the RICH bucket, but all buckets are scored and
    recorded so a flat (no-edge) result stays legible via mean_realized_vrp /
    rich_cheap_spread (spec §Verdict, kill criteria)."""
    today = _date.today()
    tickers = _all_vrp_tickers(repo)

    by_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    scored_tickers = 0
    for ticker in tickers:
        rows = _load_vrp_series(repo, ticker)
        if not rows:
            continue
        sector = repo.fetch_watchlist_sector(ticker)
        asset_class = asset_class_baseline(ticker, sector=sector)["asset_class"]
        # item 3: historical earnings calendar (massive filing_date ∪ flow_events
        # next_earnings_date). The single_name no-earnings skip-guard keys on its
        # truthiness; the buffered events feed the actual (t, t+HORIZON] exclusion.
        # A single_name with no calendar cannot honor the exclusion → must NOT
        # contribute (an unexcluded earnings window would manufacture SELLABLE).
        # index_macro / sector_etf / credit legitimately have no earnings.
        earnings_cal = repo.fetch_historical_earnings_dates(ticker)
        if asset_class == "single_name" and not earnings_cal:
            log.warning(
                "vrp_markout: skipping single_name %s — no earnings coverage "
                "to honor the (t, t+HORIZON] exclusion",
                ticker,
            )
            continue
        scored_tickers += 1
        # item 1: exact corp-action-adjusted forward RV from the price series.
        # Falls back to the UW vrp_daily.rv read (forward_fn=None) when a ticker
        # has NO price coverage — a degraded, v1-equivalent path. In production
        # every vrp_daily ticker is derived from realized_volatility_history, so
        # the exact path is the one that runs; the fallback only guards edge
        # cases (and keeps the rv-seeded unit/integration fixtures meaningful).
        adj = apply_split_adjustment(
            repo.fetch_price_series(ticker), repo.fetch_corporate_actions(ticker)
        )
        forward_fn = _adjusted_forward_rv_fn(adj) if adj else None
        events = repo.fetch_earnings_events(ticker)
        for o in _harvest_obs(rows, events=events, forward_fn=forward_fn):
            by_bucket[(asset_class, o["deviation_class"])].append(o)

    scored: dict[tuple[str, str], dict] = {
        key: _walkforward_harvest(obs, min_n=min_n) for key, obs in by_bucket.items()
    }

    # rich_cheap_spread per asset class = mean(RICH) - mean(CHEAP); None if either
    # bucket is absent. Means are descriptive (computed for any n >= 1), so the
    # spread stays legible even for sub-min_n buckets. Attached to every bucket
    # row of the asset class.
    spread_by_ac: dict[str, float | None] = {}
    for ac in {ac for (ac, _dev) in by_bucket}:
        rich = scored.get((ac, "RICH"), {}).get("mean_realized_vrp")
        cheap = scored.get((ac, "CHEAP"), {}).get("mean_realized_vrp")
        spread_by_ac[ac] = (
            rich - cheap if rich is not None and cheap is not None else None
        )

    written = 0
    # Full rewrite: clear prior verdicts first, atomically with the re-inserts
    # (single commit at the end) so readers never see a partial set.
    with repo.conn.cursor() as cur:
        cur.execute(f"DELETE FROM {repo._schema}.vrp_harvest_verdicts")
    for (ac, dev), s in scored.items():
        survives_wf = bool(s["survives_walkforward"])
        survives_gate = bool(s["survives_window_gate"])
        verdict = "HARVEST_SELLABLE" if (survives_wf and survives_gate) else "NONE"
        repo.upsert_vrp_harvest_verdict(
            asset_class=ac,
            deviation_class=dev,
            verdict=verdict,
            mean_realized_vrp=s["mean_realized_vrp"],
            mean_holdout=s["mean_holdout"],
            rich_cheap_spread=spread_by_ac.get(ac),
            n=s["n"],
            n_holdout=s["n_holdout"],
            survives_walkforward=survives_wf,
            survives_window_gate=survives_gate,
            confidence="med" if verdict == "HARVEST_SELLABLE" else None,
            as_of=today,
        )
        written += 1
    repo.conn.commit()
    return {"buckets_written": written, "tickers": scored_tickers}
