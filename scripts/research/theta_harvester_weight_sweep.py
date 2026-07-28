#!/usr/bin/env python
"""Re-score persisted theta-harvester candidates under a grid of ScoreWeights.

Pure re-scoring: no rescan, no UW call, no IB call. The score is a function of
three persisted columns, so every config is a pass over rows already in
Postgres.

Reproduce:
    uv run python scripts/research/theta_harvester_weight_sweep.py

Reads:  uw_scan.theta_harvester_candidates JOIN theta_harvester_markouts
        (horizon_days = -1, the at-expiry settlement mark)
Writes: uw_scan.backtest_sweep_runs / _results, strategy='theta_harvester_weights'

INTERPRETATION CONSTRAINTS — read before quoting any number from this:

* Entry is same-close. The candidate is built from a session's closing surface
  and entered at that same close, which is a lookahead no live trade has.
* P&L carries no bid-ask. Every mark is Black-Scholes from the grid's IV, so
  the result is a model P&L, not a fill.
* Effective N is months, not rows. 100 candidates in a month are ~100 views of
  one market, not 100 independent bets, so rows are equal-weighted by month
  before any Sharpe.
* The universe is today's watchlist. argon stores no watchlist membership
  history, so names dropped mid-window are absent — a survivorship bias that
  runs optimistic.

Two metrics, and only one decides anything:

`session_ic` is PRIMARY — per-session Spearman between score and terminal P&L,
averaged over sessions. Ranking inside a session cancels the market-wide
short-vol factor, so a positive IC is a real ordering claim rather than a
restatement of "short vol pays". It has ~145 observations rather than ~6.

`sharpe` is SECONDARY and underpowered by construction (a handful of
independent 30-day windows inside one regime). Reported so the magnitude is
visible; never the go/no-go. Do not promote anything on it.

If `default` does not beat `unconditional`, the score adds nothing and that is
the finding. Write it down rather than re-sweeping until it looks better.
"""

from __future__ import annotations

import argparse
import itertools
import logging
import math
import subprocess
from dataclasses import dataclass
from datetime import date

import psycopg

from uw_scan.backtest import monthly_summary, run_sweep, walkforward_gate
from uw_scan.config import Settings
from uw_scan.scanners.theta_harvester import (
    DEFAULT_WEIGHTS,
    NEAR_ZERO_DELTA,
    RADON_WEIGHTS,
    ScoreWeights,
    score_from_components,
)
from uw_scan.storage.backtest_repository import BacktestRepository

log = logging.getLogger("theta_sweep")

STRATEGY = "theta_harvester_weights"
REPRODUCE = "uv run python scripts/research/theta_harvester_weight_sweep.py"

# The construction gates, shared by selection and by the IC. Kept as constants
# so the two paths can never drift apart.
_IV_EDGE_FLOOR = 5.0
_IV_RATIO_FLOOR = 1.10

_SQL = """
    SELECT c.ticker, c.as_of, c.iv_rv_edge, c.iv_rv_ratio, c.net_delta,
           c.range_score, c.dealer_support, c.gate_theta_positive,
           m.pnl / NULLIF(c.underlying_spot, 0) AS ret
      FROM {schema}.theta_harvester_candidates c
      JOIN {schema}.theta_harvester_markouts m
        ON m.ticker = c.ticker AND m.as_of = c.as_of AND m.horizon_days = -1
     WHERE c.iv_rv_edge IS NOT NULL
       AND c.range_score IS NOT NULL
       AND m.pnl IS NOT NULL
       AND c.underlying_spot > 0
     ORDER BY c.as_of, c.ticker
"""


@dataclass(frozen=True)
class Row:
    ticker: str
    as_of: date
    iv_rv_edge: float
    iv_rv_ratio: float
    net_delta: float
    range_score: float
    dealer_support: str
    theta_positive: bool
    ret: float


def load_rows(conn: psycopg.Connection, schema: str = "uw_scan") -> list[Row]:
    return [
        Row(
            ticker=r[0],
            as_of=r[1],
            iv_rv_edge=float(r[2]),
            iv_rv_ratio=float(r[3]),
            net_delta=float(r[4]),
            range_score=float(r[5]),
            dealer_support=r[6],
            theta_positive=bool(r[7]),
            ret=float(r[8]),
        )
        for r in conn.execute(_SQL.format(schema=schema)).fetchall()
    ]


def build_grid() -> list[dict]:
    """Predeclared and coarse — a handful of independent windows cannot support
    a fine grid. The three named configs come first so a crash never loses them.
    """
    grid: list[dict] = [
        {"kind": "unconditional", "name": "unconditional"},
        {"kind": "weights", "name": "radon", **RADON_WEIGHTS.__dict__},
        {"kind": "weights", "name": "default", **DEFAULT_WEIGHTS.__dict__},
    ]
    axes = itertools.product(
        (25.0, 40.0, 55.0, 70.0),  # vol_edge
        (15.0, 25.0),  # delta_neutrality
        (10.0, 20.0),  # range_bound
        (10.0, 15.0, 20.0),  # edge_saturation_pts
        (50.0, 60.0, 70.0),  # threshold
        (False, True),  # dealer_gate_critical
    )
    for vol, dn, rb, sat, thr, dealer in axes:
        grid.append(
            {
                "kind": "weights",
                "name": None,
                **ScoreWeights(
                    vol_edge=vol,
                    delta_neutrality=dn,
                    range_bound=rb,
                    edge_saturation_pts=sat,
                    threshold=thr,
                    dealer_gate_critical=dealer,
                ).__dict__,
            }
        )
    return grid


def _weights(config: dict) -> ScoreWeights:
    return ScoreWeights(**{k: config[k] for k in ScoreWeights.__dataclass_fields__})


def _passes_construction_gates(r: Row, w: ScoreWeights) -> bool:
    """Gates that decide whether the structure is a short strangle at all.

    Deliberately excludes the score threshold — see cross_sectional_ic.
    """
    if abs(r.net_delta) > NEAR_ZERO_DELTA or not r.theta_positive:
        return False
    return not (w.dealer_gate_critical and r.dealer_support != "SUPPORT")


def selected_rows(rows: list[Row], *, config: dict) -> list[Row]:
    if config["kind"] == "unconditional":
        return list(rows)
    w = _weights(config)
    out: list[Row] = []
    for r in rows:
        if not _passes_construction_gates(r, w):
            continue
        if not (r.iv_rv_edge >= _IV_EDGE_FLOOR or r.iv_rv_ratio >= _IV_RATIO_FLOOR):
            continue
        score = score_from_components(
            iv_rv_edge=r.iv_rv_edge,
            net_delta=r.net_delta,
            range_score=r.range_score,
            weights=w,
        )
        if score >= w.threshold:
            out.append(r)
    return out


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation, no scipy. None when either side has no dispersion."""
    n = len(xs)
    if n < 5:
        return None

    def ranks(vs: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vs[i])
        out = [0.0] * n
        i = 0
        while i < n:  # average ranks within ties
            j = i
            while j + 1 < n and vs[order[j + 1]] == vs[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if dx == 0 or dy == 0:
        return None
    return num / (dx * dy)


def cross_sectional_ic(rows: list[Row], *, config: dict) -> dict:
    """Per-session Spearman(score, terminal P&L), averaged over sessions.

    THE PRIMARY METRIC. Scores every row clearing the CONSTRUCTION gates —
    deliberately not the threshold, because a threshold turns a ranking
    question into a selection question and discards the bottom of the
    cross-section, which is exactly the part that reveals whether the score
    orders anything.
    """
    if config["kind"] == "unconditional":
        # No score to rank by — the control arm has no ordering hypothesis.
        return {"session_ic": None, "ic_t_stat": None, "ic_sessions": 0}
    w = _weights(config)

    by_session: dict[date, list[Row]] = {}
    for r in rows:
        if _passes_construction_gates(r, w):
            by_session.setdefault(r.as_of, []).append(r)

    ics: list[float] = []
    for session_rows in by_session.values():
        scores = [
            score_from_components(
                iv_rv_edge=r.iv_rv_edge,
                net_delta=r.net_delta,
                range_score=r.range_score,
                weights=w,
            )
            for r in session_rows
        ]
        ic = _spearman(scores, [r.ret for r in session_rows])
        if ic is not None:
            ics.append(ic)

    if len(ics) < 3:
        return {"session_ic": None, "ic_t_stat": None, "ic_sessions": len(ics)}
    mean = sum(ics) / len(ics)
    sd = math.sqrt(sum((v - mean) ** 2 for v in ics) / (len(ics) - 1))
    # Sessions overlap (a 30-day hold spans ~21 of them), so this t-stat is
    # still optimistic — a screen, not a p-value. Treat |t| < 2 as noise and
    # |t| >= 2 as "worth a real overlapping-window correction".
    t = mean / (sd / math.sqrt(len(ics))) if sd > 0 else None
    return {"session_ic": mean, "ic_t_stat": t, "ic_sessions": len(ics)}


def evaluate_config(rows: list[Row], *, config: dict) -> dict:
    kept = selected_rows(rows, config=config)
    ic = cross_sectional_ic(rows, config=config)
    if not kept:
        return {
            "n_trades": 0,
            "metrics": {
                "sharpe": None,
                "effective_n_months": 0,
                "mean_ret": None,
                **ic,
            },
            "gates": None,
        }

    totals: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for r in kept:
        key = (r.as_of.year, r.as_of.month)
        totals[key] = totals.get(key, 0.0) + r.ret
        counts[key] = counts.get(key, 0) + 1
    # Equal-weight the month, not the row: 60 candidates in one month is one
    # observation of one market, not 60 independent bets.
    monthly = {k: v / counts[k] for k, v in totals.items()}

    ordered = [monthly[k] for k in sorted(monthly)]
    return {
        "n_trades": len(kept),
        "metrics": {
            **monthly_summary(monthly),  # supplies sharpe / maxdd / annror
            "effective_n_months": len(monthly),
            "mean_ret": sum(ordered) / len(ordered),
            "n_tickers": len({r.ticker for r in kept}),
            **ic,  # primary metric; the sharpe above is the underpowered one
        },
        # Holdout on the month series. Thresholds are 0.0 — the bar is only "is
        # the mean still positive out of sample", because with ~7 months
        # anything stricter is theatre. Below min_n the helper reports
        # survives_* False with descriptive means, which is what we want
        # surfaced rather than suppressed.
        # walkforward_gate time-orders on a 'market_date' key; the month's first
        # day stands in for the month so the holdout cut stays chronological.
        "gates": walkforward_gate(
            [
                {"ret": monthly[k], "market_date": date(k[0], k[1], 1)}
                for k in sorted(monthly)
            ],
            value_key="ret",
            min_n=4,
            threshold=0.0,
            holdout_threshold=0.0,
            holdout_frac=0.3,
        ),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument(
        "--named-only",
        action="store_true",
        help="run just unconditional/radon/default (skip the 288-config grid)",
    )
    args = p.parse_args()

    settings = Settings.from_env()
    sha = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or None
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        rows = load_rows(conn, schema=settings.db_schema)
        if not rows:
            raise SystemExit(
                "No candidate/terminal-markout pairs. Run the Task 8 backfill first: "
                "uv run python scripts/backfill/theta_harvester_backfill.py"
            )
        log.info(
            "loaded %d rows, %s..%s, %d tickers, %d sessions",
            len(rows),
            rows[0].as_of,
            rows[-1].as_of,
            len({r.ticker for r in rows}),
            len({r.as_of for r in rows}),
        )
        grid = build_grid()
        if args.named_only:
            grid = [c for c in grid if c.get("name")]
        out = run_sweep(
            grid,
            lambda cfg: evaluate_config(rows, config=cfg),
            repo=BacktestRepository(conn),
            strategy=STRATEGY,
            reproduce_cmd=REPRODUCE,
            git_sha=sha,
            data_start=rows[0].as_of,
            data_end=rows[-1].as_of,
            notes=(
                "Same-close entry (lookahead). Spot-normalised model P&L, no "
                "bid-ask. Monthly equal-weight. session_ic is the primary "
                "metric; sharpe is underpowered. Compare every config against "
                "the 'unconditional' control before claiming the score works."
            ),
        )

    named = {
        r["config"].get("name"): r for r in out["results"] if r["config"].get("name")
    }
    for key in ("unconditional", "radon", "default"):
        r = named.get(key)
        if not r:
            continue
        m = r["metrics"]
        log.info(
            "%-14s IC=%s t=%s sessions=%s | sharpe=%s mean_ret=%s months=%s trades=%s",
            key,
            _fmt(m.get("session_ic"), 4),
            _fmt(m.get("ic_t_stat"), 2),
            m.get("ic_sessions"),
            _fmt(m.get("sharpe"), 2),
            _fmt(m.get("mean_ret"), 5),
            m.get("effective_n_months"),
            r.get("n_trades"),
        )
    log.info("run_id=%s ok=%s error=%s", out["run_id"], out["n_ok"], out["n_error"])
    return 0


def _fmt(v, places: int) -> str:
    return "None" if v is None else f"{v:.{places}f}"


if __name__ == "__main__":
    raise SystemExit(main())
