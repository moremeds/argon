#!/usr/bin/env python
"""Does capping the tail with wings turn the theta-harvester strangle positive?

The 2026-07-28 weight sweep found the score ORDERS candidates (IC +0.075) while
the selected set still lost money held to expiry. The terminal distribution says
why, and it is not a grind:

    n = 13,890   win rate 74.7%   median +1.42%   p05 -16.6%   p01 -52.2%

Three quarters of these trades win. The mean is negative purely because of the
left tail: the 7.9% of trades losing more than 10% of spot account for 225% of
the total P&L sum. That is the payoff shape wings exist for, and capping the
loss (with FREE wings) flips the sign at roughly a 10%-wide cap.

This script prices the wings for real and subtracts them, which is the only
version of the question that decides anything. It also resolves the standing
defined-risk conflict: a condor is a defined-risk structure, the naked strangle
is not.

Reproduce:
    uv run python scripts/research/theta_harvester_condor_sweep.py

Reads:  uw_scan.theta_harvester_candidates JOIN theta_harvester_markouts
        (horizon_days = -1) JOIN option_surface_grid_daily (wing IV at entry)
Writes: uw_scan.backtest_sweep_runs / _results, strategy='theta_harvester_condor'

DESIGNED AGAINST THE RADON TRAP
-------------------------------
The prior sweep's most attractive number was radon's Sharpe of 2.23, produced
by a gate that silently truncated the sample to 34 sessions inside the one
regime where selling strangles paid, sitting on top of a score whose IC was
NEGATIVE. Four rules follow from that, and this script enforces all four:

1. MATCHED SAMPLES. Wing availability is not random — a chain deep enough to
   quote a 20%-out wing belongs to a liquid name. Comparing a condor built on
   the 65% of rows that HAVE wings against a strangle built on all 100% would
   re-run exactly radon's mistake in a new costume. Every width therefore
   evaluates BOTH arms on the identical row set. `naked_full` is reported for
   context and is explicitly labelled as a different sample.
2. SHARPE CARRIES ITS STANDARD ERROR. Every Sharpe in the prior study was
   within ~1.3 SE of zero while being read as if it ranked anything. Here
   `sharpe_se` sits in the same metrics dict so the ratio can never be quoted
   without it.
3. THE SAMPLE WINDOW IS A REPORTED METRIC. `first_month` / `last_month` /
   `ic_sessions` are emitted per config, so a gate that doubles as a date
   filter is visible in the results table instead of being inferred later.
4. THE GRID IS SMALL AND PREDECLARED. 3 weight configs x 3 widths x 2
   structures. No 288-config grid, because the top of one is where selection
   bias lives and reporting it invites the reader to promote it.

INTERPRETATION CONSTRAINTS — carried over, still binding:

* Entry is same-close (lookahead no live trade has).
* No bid-ask. A condor crosses FOUR spreads, not two, and the wings are the
  least liquid strikes in the chain. This is the single largest unmodelled
  cost and it works against the condor specifically.
* Effective N is months, not rows.
* Universe is today's watchlist — survivorship, runs optimistic.
* European settlement on American options — early assignment would usually be
  worse, so terminal P&L is an optimistic bound on the loss.
"""

from __future__ import annotations

import logging
import math
import subprocess
from dataclasses import dataclass
from datetime import date

import psycopg

from uw_scan.backtest import monthly_summary, run_sweep, walkforward_gate
from uw_scan.config import Settings
from uw_scan.reports.vrp_structure import bs_price
from uw_scan.scanners.theta_harvester import (
    DEFAULT_WEIGHTS,
    NEAR_ZERO_DELTA,
    RADON_WEIGHTS,
    ScoreWeights,
    score_from_components,
)
from uw_scan.storage.backtest_repository import BacktestRepository

log = logging.getLogger("theta_condor")

STRATEGY = "theta_harvester_condor"
REPRODUCE = "uv run python scripts/research/theta_harvester_condor_sweep.py"

# Same construction gates as the weight sweep, kept identical so the two
# studies describe the same population.
_IV_EDGE_FLOOR = 5.0
_IV_RATIO_FLOOR = 1.10

# Wing offsets as a fraction of entry spot. Coarse and predeclared: 5% is about
# the tightest a real chain quotes reliably, 20% is where wing coverage falls to
# 65% and the censoring starts to dominate the answer.
WIDTHS: tuple[float, ...] = (0.05, 0.10, 0.20)

# The wing is the nearest LISTED strike at or beyond the target offset, so the
# realised width differs per row. Max loss must use the realised width, never
# the requested one.
_SQL = """
    SELECT c.ticker, c.as_of, c.iv_rv_edge, c.iv_rv_ratio, c.net_delta,
           c.range_score, c.dealer_support, c.gate_theta_positive,
           c.underlying_spot, c.dte, c.risk_free_rate,
           c.put_strike, c.call_strike, c.put_mark, c.call_mark,
           m.spot AS settle, m.pnl AS stored_pnl,
           pw.strike AS put_wing_k, pw.put_iv AS put_wing_iv,
           cw.strike AS call_wing_k, cw.call_iv AS call_wing_iv
      FROM {schema}.theta_harvester_candidates c
      JOIN {schema}.theta_harvester_markouts m
        ON m.ticker = c.ticker AND m.as_of = c.as_of AND m.horizon_days = -1
      LEFT JOIN LATERAL (
            SELECT g.strike, g.put_iv
              FROM {schema}.option_surface_grid_daily g
             WHERE g.ticker = c.ticker AND g.market_date = c.as_of
               AND g.expiry = c.expiry AND g.put_iv IS NOT NULL
               AND g.strike <= c.put_strike - %(width)s * c.underlying_spot
             ORDER BY g.strike DESC LIMIT 1
      ) pw ON TRUE
      LEFT JOIN LATERAL (
            SELECT g.strike, g.call_iv
              FROM {schema}.option_surface_grid_daily g
             WHERE g.ticker = c.ticker AND g.market_date = c.as_of
               AND g.expiry = c.expiry AND g.call_iv IS NOT NULL
               AND g.strike >= c.call_strike + %(width)s * c.underlying_spot
             ORDER BY g.strike ASC LIMIT 1
      ) cw ON TRUE
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
    spot: float
    dte: int
    rate: float
    put_strike: float
    call_strike: float
    put_mark: float
    call_mark: float
    settle: float
    stored_pnl: float
    put_wing_k: float | None
    put_wing_iv: float | None
    call_wing_k: float | None
    call_wing_iv: float | None

    @property
    def has_wings(self) -> bool:
        return self.put_wing_k is not None and self.call_wing_k is not None


def _short_leg_loss(r: Row) -> float:
    """Intrinsic owed on the two SHORT legs at settlement, per share."""
    return max(0.0, r.put_strike - r.settle) + max(0.0, r.settle - r.call_strike)


def naked_return(r: Row) -> float:
    """Short strangle P&L per share, normalised by entry spot.

    Recomputed rather than read from m.pnl so the condor below shares one
    payoff path with a number the production markout already validated. The
    agreement is asserted in validate_against_stored().
    """
    return (r.put_mark + r.call_mark - _short_leg_loss(r)) / r.spot


def condor_return(r: Row) -> float | None:
    """Iron condor P&L per share, normalised by entry spot. None without wings.

    Long wings are priced Black-Scholes off the SAME grid IV surface that
    priced the short legs, so the credit is internally consistent — an entry
    edge cannot be manufactured by pricing the two sides off different sources.
    """
    if not r.has_wings:
        return None
    t_years = max(r.dte, 0) / 365.0
    long_put = bs_price(
        r.spot, r.put_wing_k, t_years, r.rate, r.put_wing_iv, is_call=False
    )
    long_call = bs_price(
        r.spot, r.call_wing_k, t_years, r.rate, r.call_wing_iv, is_call=True
    )
    credit = r.put_mark + r.call_mark - long_put - long_call
    # The long wings refund everything beyond themselves — this is the entire
    # point of the structure and the only line that differs from naked.
    recovered = max(0.0, r.put_wing_k - r.settle) + max(0.0, r.settle - r.call_wing_k)
    return (credit - _short_leg_loss(r) + recovered) / r.spot


def load_rows(conn: psycopg.Connection, *, schema: str, width: float) -> list[Row]:
    sql = _SQL.format(schema=schema)
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
            spot=float(r[8]),
            dte=int(r[9]),
            rate=float(r[10]),
            put_strike=float(r[11]),
            call_strike=float(r[12]),
            put_mark=float(r[13]),
            call_mark=float(r[14]),
            settle=float(r[15]),
            stored_pnl=float(r[16]),
            put_wing_k=None if r[17] is None else float(r[17]),
            put_wing_iv=None if r[18] is None else float(r[18]),
            call_wing_k=None if r[19] is None else float(r[19]),
            call_wing_iv=None if r[20] is None else float(r[20]),
        )
        for r in conn.execute(sql, {"width": width}).fetchall()
    ]


def validate_against_stored(rows: list[Row], *, tol: float = 0.01) -> None:
    """Assert the recomputed naked payoff reproduces the production markout.

    This is the load-bearing check for the whole script. The condor differs
    from the naked strangle by exactly one term (`recovered`), so if the naked
    path matches a number the shipped markout job produced independently, the
    condor payoff is right by construction too.
    """
    worst = 0.0
    for r in rows:
        recomputed = r.put_mark + r.call_mark - _short_leg_loss(r)
        worst = max(worst, abs(recomputed - r.stored_pnl))
    if worst > tol:
        raise SystemExit(
            f"payoff mismatch vs stored markout: max |diff| = {worst:.6f} > {tol}. "
            "Refusing to run — the condor P&L would inherit the same error."
        )
    log.info("payoff self-check ok: max |recomputed - stored| = %.8f", worst)


def build_grid() -> list[dict]:
    """Predeclared and deliberately small — see rule 4 in the module docstring."""
    named = [
        {"kind": "unconditional", "name": "unconditional"},
        {"kind": "weights", "name": "radon", **RADON_WEIGHTS.__dict__},
        {"kind": "weights", "name": "default", **DEFAULT_WEIGHTS.__dict__},
    ]
    grid: list[dict] = []
    # Unmatched full-sample naked baseline: reproduces the prior study's number
    # so this run can be tied back to it. Labelled so it is never compared
    # like-for-like against a condor arm.
    for base in named:
        grid.append(
            {
                **base,
                "structure": "naked_full",
                "width": None,
                "name": f"{base['name']}/naked_full",
            }
        )
    for width in WIDTHS:
        for base in named:
            for structure in ("naked", "condor"):
                grid.append(
                    {
                        **base,
                        "structure": structure,
                        "width": width,
                        "name": f"{base['name']}/{structure}@{int(width * 100)}pct",
                    }
                )
    return grid


def _weights(config: dict) -> ScoreWeights:
    return ScoreWeights(**{k: config[k] for k in ScoreWeights.__dataclass_fields__})


def _passes_construction_gates(r: Row, w: ScoreWeights) -> bool:
    if abs(r.net_delta) > NEAR_ZERO_DELTA or not r.theta_positive:
        return False
    return not (w.dealer_gate_critical and r.dealer_support != "SUPPORT")


def _ret(r: Row, structure: str) -> float | None:
    return naked_return(r) if structure != "condor" else condor_return(r)


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
    """Per-session Spearman(score, structure P&L), averaged over sessions.

    THE PRIMARY METRIC, unchanged from the weight sweep except that the P&L it
    ranks against is the structure's. Scores every row clearing the CONSTRUCTION
    gates, not the threshold — a threshold turns a ranking question into a
    selection question and discards the part of the cross-section that reveals
    whether the score orders anything.
    """
    if config["kind"] == "unconditional":
        return {"session_ic": None, "ic_t_stat": None, "ic_sessions": 0}
    w = _weights(config)
    structure = config["structure"]

    by_session: dict[date, list[Row]] = {}
    for r in rows:
        if _passes_construction_gates(r, w):
            by_session.setdefault(r.as_of, []).append(r)

    ics: list[float] = []
    for session_rows in by_session.values():
        pairs = [(r, _ret(r, structure)) for r in session_rows]
        pairs = [(r, v) for r, v in pairs if v is not None]
        if len(pairs) < 5:
            continue
        scores = [
            score_from_components(
                iv_rv_edge=r.iv_rv_edge,
                net_delta=r.net_delta,
                range_score=r.range_score,
                weights=w,
            )
            for r, _ in pairs
        ]
        ic = _spearman(scores, [v for _, v in pairs])
        if ic is not None:
            ics.append(ic)

    if len(ics) < 3:
        return {"session_ic": None, "ic_t_stat": None, "ic_sessions": len(ics)}
    mean = sum(ics) / len(ics)
    sd = math.sqrt(sum((v - mean) ** 2 for v in ics) / (len(ics) - 1))
    # Sessions overlap (a 30-day hold spans ~21 of them), so this t-stat is
    # optimistic — a screen, not a p-value.
    t = mean / (sd / math.sqrt(len(ics))) if sd > 0 else None
    return {"session_ic": mean, "ic_t_stat": t, "ic_sessions": len(ics)}


def sharpe_standard_error(sharpe_ann: float | None, n_months: int) -> float | None:
    """SE of an annualised Sharpe from n monthly points.

    Rule 2 of the anti-trap design. Lo (2002): SE(S) ~ sqrt((1 + S^2/2)/n) on
    the per-period ratio. Overlapping 30-day holds violate the iid assumption
    behind it, so this is a FLOOR on the true uncertainty, not an estimate of
    it. Reported because a Sharpe of 2.23 +/- 2.20 and a Sharpe of 2.23 are
    different claims, and the prior study only ever printed the second.
    """
    if sharpe_ann is None or n_months < 2:
        return None
    monthly = sharpe_ann / math.sqrt(12.0)
    return math.sqrt((1.0 + monthly**2 / 2.0) / n_months) * math.sqrt(12.0)


def evaluate_config(rows: list[Row], *, config: dict) -> dict:
    structure = config["structure"]
    kept = selected_rows(rows, config=config)
    priced = [(r, _ret(r, structure)) for r in kept]
    priced = [(r, v) for r, v in priced if v is not None]
    ic = cross_sectional_ic(rows, config=config)

    if not priced:
        return {
            "n_trades": 0,
            "metrics": {
                "sharpe": None,
                "effective_n_months": 0,
                "mean_ret": None,
                "structure": structure,
                "width": config["width"],
                **ic,
            },
            "gates": None,
        }

    totals: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for r, v in priced:
        key = (r.as_of.year, r.as_of.month)
        totals[key] = totals.get(key, 0.0) + v
        counts[key] = counts.get(key, 0) + 1
    # Equal-weight the month, not the row.
    monthly = {k: v / counts[k] for k, v in totals.items()}
    ordered = [monthly[k] for k in sorted(monthly)]
    summary = monthly_summary(monthly)
    months = sorted(monthly)

    return {
        "n_trades": len(priced),
        "metrics": {
            **summary,
            "sharpe_se": sharpe_standard_error(summary.get("sharpe"), len(monthly)),
            "effective_n_months": len(monthly),
            "mean_ret": sum(ordered) / len(ordered),
            "win_rate": sum(1 for _, v in priced if v > 0) / len(priced),
            "worst_ret": min(v for _, v in priced),
            "n_tickers": len({r.ticker for r, _ in priced}),
            "structure": structure,
            "width": config["width"],
            # Rule 3: the sample window is a metric, so a gate that doubles as
            # a date filter shows up here instead of being discovered later.
            "first_month": f"{months[0][0]}-{months[0][1]:02d}",
            "last_month": f"{months[-1][0]}-{months[-1][1]:02d}",
            **ic,
        },
        "gates": walkforward_gate(
            [{"ret": monthly[k], "market_date": date(k[0], k[1], 1)} for k in months],
            value_key="ret",
            min_n=4,
            threshold=0.0,
            holdout_threshold=0.0,
            holdout_frac=0.3,
        ),
    }


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    settings = Settings.from_env()
    sha = (
        subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
        or None
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        # One load per width; the wing columns are width-dependent.
        by_width: dict[float, list[Row]] = {}
        for width in WIDTHS:
            rows = load_rows(conn, schema=settings.db_schema, width=width)
            if not rows:
                raise SystemExit(
                    "No candidate/terminal-markout pairs. Run the backfill first: "
                    "uv run python scripts/backfill/theta_harvester_backfill.py"
                )
            by_width[width] = rows
            n_wings = sum(1 for r in rows if r.has_wings)
            log.info(
                "width=%.0f%% loaded %d rows, %d with both wings (%.1f%%)",
                width * 100,
                len(rows),
                n_wings,
                100.0 * n_wings / len(rows),
            )

        validate_against_stored(by_width[WIDTHS[0]])

        def rows_for(config: dict) -> list[Row]:
            """Rule 1: matched samples.

            Every width restricts BOTH arms to the rows that HAVE wings at that
            width. Letting the naked arm keep the wingless rows would compare
            two different universes and reproduce the radon trap exactly.
            """
            if config["structure"] == "naked_full":
                return by_width[WIDTHS[0]]
            return [r for r in by_width[config["width"]] if r.has_wings]

        out = run_sweep(
            build_grid(),
            lambda cfg: evaluate_config(rows_for(cfg), config=cfg),
            repo=BacktestRepository(conn),
            strategy=STRATEGY,
            reproduce_cmd=REPRODUCE,
            git_sha=sha,
            data_start=min(r.as_of for r in by_width[WIDTHS[0]]),
            data_end=max(r.as_of for r in by_width[WIDTHS[0]]),
            notes=(
                "Naked strangle vs iron condor on MATCHED rows at 3 wing widths. "
                "Wings are the nearest listed strike at/beyond the offset, priced "
                "BS off the same grid IV as the short legs. Same-close entry "
                "(lookahead), no bid-ask — and a condor crosses FOUR spreads on "
                "the least liquid strikes, so the unmodelled cost works against "
                "the condor arm specifically. session_ic is primary; sharpe is "
                "underpowered and ships with sharpe_se."
            ),
        )

    for r in sorted(out["results"], key=lambda x: x["config"].get("name") or ""):
        m, name = r["metrics"], r["config"].get("name")
        log.info(
            "%-34s mean=%s sharpe=%s+/-%s IC=%s t=%s months=%s trades=%s win=%s",
            name,
            _fmt(m.get("mean_ret"), 5),
            _fmt(m.get("sharpe"), 2),
            _fmt(m.get("sharpe_se"), 2),
            _fmt(m.get("session_ic"), 4),
            _fmt(m.get("ic_t_stat"), 2),
            m.get("effective_n_months"),
            r.get("n_trades"),
            _fmt(m.get("win_rate"), 3),
        )
    log.info("run_id=%s ok=%s error=%s", out["run_id"], out["n_ok"], out["n_error"])
    return 0


def _fmt(v, places: int) -> str:
    return "None" if v is None else f"{v:.{places}f}"


if __name__ == "__main__":
    raise SystemExit(main())
