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
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
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


def _harvest_obs(rows: list[dict], *, earnings: set[_date]) -> list[dict]:
    """Build realized-VRP observations for one ticker.

    rows: vrp_daily rows [{market_date, iv, rv, vrp_z_20}], any order. There is
    one row per trading day, so the EXACT 20th trading day forward is the row at
    position i + HORIZON in the date-sorted list (positional — NOT a non-null-RV
    skip; an interior null RV must not shift the target).
    realized_VRP(t) = iv(t) - rv(t+20). Drops an anchor when: its signal or iv is
    null, there is no i+HORIZON row yet (recent tail), the exact t+20 row's rv is
    null, or an earnings date falls in (t, t+20]. Values may be Decimal — coerced
    to float."""
    ordered = sorted(rows, key=lambda r: r["market_date"])
    n = len(ordered)
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
        j = i + HORIZON
        if j >= n:
            continue  # no forward target yet
        fwd = ordered[j]
        if fwd["rv"] is None:
            continue  # exact t+20 RV missing → cannot score this anchor
        if _earnings_in_window(t, fwd["market_date"], earnings):
            continue
        obs.append(
            {
                "market_date": t,
                "deviation_class": dev,
                "realized_vrp": float(r["iv"]) - float(fwd["rv"]),
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
        earnings = repo.fetch_known_earnings_dates(ticker)
        # AC2 safeguard (design-decision note 1): a single_name with no
        # reconstructed earnings calendar cannot have its (t, t+20] earnings
        # windows excluded → it must NOT contribute (an unexcluded earnings
        # window inflates the harvest and would manufacture a false SELLABLE).
        # index_macro / sector_etf / credit legitimately have no earnings.
        if asset_class == "single_name" and not earnings:
            log.warning(
                "vrp_markout: skipping single_name %s — no earnings coverage "
                "to honor the (t, t+20] exclusion",
                ticker,
            )
            continue
        scored_tickers += 1
        for o in _harvest_obs(rows, earnings=earnings):
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
