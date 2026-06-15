"""Tier-1 skew markout: bucket snapshots, score forward returns, write verdicts.

Two hypotheses (spec §7 step 2):
  PRIMARY   — RV mean-reversion: does extreme RR (RICH/CHEAP) revert? Measured as
              mean forward dRR per (asset_class, deviation_class); REPORTED in the
              return dict for the research note, not gated into a verdict.
  SECONDARY — directional, borrow-conditioned: do buckets separate forward STOCK
              returns on the borrow-clean subset? Gated into TRADABLE_* verdicts.

A bucket (asset_class, deviation_class, drive_class, regime) earns TRADABLE_BULL/
TRADABLE_BEAR only if mean T+20 forward return on the borrow-clean subset is
material (|mean| >= sep_threshold), n >= min_n, and survives the per-TIME-WINDOW
catastrophic-degradation gate. Otherwise NONE. NONE/absent => NEUTRAL lean.

Forward horizons are TRADING-day offsets (the nth row after the anchor in the
per-ticker trading series), NOT calendar days.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from typing import Any

from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

HORIZON = 20  # trading days for the canonical separation horizon


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
    if n >= 60 and abs(sep) >= 0.02:
        return "high"
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

    buckets: dict[tuple, list[dict]] = defaultdict(list)  # directional (gated)
    meanrev: dict[tuple, list[float]] = defaultdict(list)  # primary (reported)
    for s in snaps:
        spot = s.get("spot")
        if spot is not None and float(spot) != 0:
            fwd_px = _forward_value_at(
                price_by_ticker.get(s["ticker"], []), s["market_date"], HORIZON
            )
            if fwd_px is not None:
                key = (
                    s["asset_class"],
                    s["deviation_class"],
                    s["drive_class"],
                    s["regime"],
                )
                buckets[key].append(
                    {
                        "fwd": fwd_px / float(spot) - 1.0,
                        "clean": s.get("borrow_flag") != "hard_to_borrow",
                        "market_date": s["market_date"],
                    }
                )
        rr0 = s.get("rr_25d")
        if rr0 is not None:
            fwd_rr = _forward_value_at(
                rr_by_ticker.get(s["ticker"], []), s["market_date"], HORIZON
            )
            if fwd_rr is not None:
                meanrev[(s["asset_class"], s["deviation_class"])].append(
                    fwd_rr - float(rr0)
                )

    today = _date.today()
    written = 0
    for key, obs in buckets.items():
        asset_class, deviation_class, drive_class, regime = key
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
            regime=regime,
            verdict=verdict,
            confidence=_confidence(n, sep) if verdict != "NONE" else "low",
            forward_sep=sep,
            n=n,
            borrow_clean=True,
            survives_gate=survives,
            as_of=today,
        )
        written += 1

    mean_reversion = {
        f"{a}/{d}": {"mean_dRR": (sum(v) / len(v) if v else None), "n": len(v)}
        for (a, d), v in meanrev.items()
    }
    repo.conn.commit()
    log.info(
        "run_skew_markout wrote %d verdicts over %d snapshots", written, len(snaps)
    )
    return {
        "verdicts_written": written,
        "snapshots": len(snaps),
        "mean_reversion": mean_reversion,  # PRIMARY hypothesis, descriptive
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
