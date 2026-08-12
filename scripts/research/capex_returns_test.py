"""Does anything in the capex demand ledger predict RETURNS? The deciding test.

    uv run python scripts/research/capex_returns_test.py

Every earlier round related fundamentals to fundamentals. Even a perfect
capex -> supplier-revenue link is worth nothing if the market already prices it,
and the `9 CTRL buyers-self` control says it very likely does: hyperscaler capex
FOLLOWS hyperscaler revenue by 2-3 quarters, so by the time `capital_expenditures`
appears in a cash-flow statement it is a twice-stale variable.

Two shocks compete on the same machinery, which is the whole point:

* **A -- buyer residual return.** Cohen & Frazzini (JF 2008) found that buying a
  supplier after a positive shock to its customer earns predictable returns,
  surviving the three-factor model, liquidity, own-firm and industry momentum.
  Their shock is the customer's STOCK RETURN, which is forward-looking.
* **B -- buyer capex growth surprise.** Ours, and backward-looking.

If A works and B does not, the link is real but capex is the wrong instrument
for it. If neither works, the ledger closes.

DESIGN NOTES, each load-bearing:

* Cohen & Frazzini get cross-sectional dispersion because different suppliers
  have different customers. This chain has ONE buyer basket, so a common shock
  hands every supplier the same number and there is no cross-section at all.
  The cross-sectional variable therefore has to be each supplier's own
  SENSITIVITY to the shock, estimated on a trailing window that ends strictly
  before the month being traded.
* EVERYTHING IS RESIDUALISED AGAINST THE MARKET, on both legs, with a trailing
  market beta. Without it this degenerates into a bet on market beta and would
  rediscover beta rather than any supply-chain link -- the exact failure mode
  that ended the dark-pool lead-lag study ("mostly beta after neutralisation").
* Capex growth is lagged UNIFORMLY to `period_end + 90 days`, not to
  `filing_published_at`. That column is present on only 51% of rows, so using it
  where available would hand half the sample a timing advantage the other half
  does not get. 90 days clears the p95 filing lag of 59 days.
* Capex growth is Z-SCORED against its own trailing history before use. Raw
  capex growth was positive in nearly every quarter of this sample, so a raw
  signal is a permanent long-high-sensitivity tilt -- a static bet dressed as a
  timing signal. The surprise is the part that can time anything.
* Two null controls run beside the real signals: a shuffled-signal portfolio and
  a sensitivity-only portfolio with no shock. A real result has to beat both.

WINDOW LIMITATION, stated up front: massive caps daily history at ~5 years on
our tier, so the sample starts 2021-08 no matter what start date is requested.
That is ~60 months, of which the trailing-estimation window consumes the first
18. The remaining out-of-sample period sits ENTIRELY inside the AI capex boom,
so this test cannot distinguish "works" from "worked during one expansion".

CONSEQUENCE FOR HOW A NEGATIVE READS: it is provisional, not a kill. Deeper
history is expected once the mini is back online, and every part of this script
keys off whatever `daily_ohlc` holds -- re-running against a longer table needs
no code change, only a longer table. A negative here retires the CURRENT
evidence, not the question.

Nothing is written to Postgres: this decides whether a feature should exist.
Trace lands in docs/research/2026-08-13-ai-capex-demand-ledger/.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from datetime import date as _date
from datetime import timedelta
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from uw_scan.backtest import (  # noqa: E402
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
    quarter_gate,
)
from uw_scan.config import Settings  # noqa: E402

OUT = Path("docs/research/2026-08-13-ai-capex-demand-ledger")

MARKET = "SPY"
BUYER_CHAINS = ["Cloud/Hyperscaler", "AI-Cloud/NeoCloud"]
#: Excluded from the supplier universe: the buyers themselves, the market proxy,
#: and index/sector ETFs, which are baskets rather than firms.
NON_SUPPLIER_CHAINS = set(BUYER_CHAINS) | {"Beta", "Sector-ETF", "Macro", "M7"}

TRAIL_MONTHS = 18
MIN_TRAIL = 12
QUANTILE = 5  # long top 1/5, short bottom 1/5
CAPEX_LAG_DAYS = 90


def monthly_returns(conn, schema: str) -> dict[str, dict[str, float]]:
    """{ticker: {YYYY-MM: simple return}} from month-end closes."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            with m as (
              select ticker, to_char(date,'YYYY-MM') ym, date, close,
                     row_number() over (partition by ticker, to_char(date,'YYYY-MM')
                                        order by date desc) rn
              from {schema}.daily_ohlc
            )
            select ticker, ym, close from m where rn = 1 order by ticker, ym
            """
        )
        closes: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for tkr, ym, close in cur.fetchall():
            closes[tkr].append((ym, float(close)))
    out: dict[str, dict[str, float]] = {}
    for tkr, rows in closes.items():
        rets = {}
        for i in range(1, len(rows)):
            prev, cur_ = rows[i - 1][1], rows[i][1]
            if prev > 0:
                rets[rows[i][0]] = cur_ / prev - 1.0
        if rets:
            out[tkr] = rets
    return out


def chain_members(conn, schema: str) -> dict[str, set[str]]:
    with conn.cursor() as cur:
        cur.execute(f"select chain, ticker from {schema}.watchlist_chain")
        out: dict[str, set[str]] = defaultdict(set)
        for chain, tkr in cur.fetchall():
            out[chain].add(tkr)
        return dict(out)


def buyer_capex_surprise(conn, schema: str) -> dict[str, float]:
    """{YYYY-MM: z-scored buyer capex YoY growth KNOWN by that month}.

    Matched-sample growth (tickers present in both t and t-4), the construction
    established in ROUND2-matched-growth.md, then lagged 90 days and z-scored
    against its own expanding history so the series can change sign.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            with q as (
              select date_trunc('quarter', o.period_end - interval '1 month')::date cq,
                     o.ticker, o.period_end,
                     abs((o.raw_jsonb->>'capital_expenditures')::numeric) v,
                     row_number() over (
                       partition by o.ticker,
                         date_trunc('quarter', o.period_end - interval '1 month')
                       order by o.period_end desc) rn
              from {schema}.fundamental_statement_obs o
              join (select distinct ticker from {schema}.watchlist_chain
                    where chain = any(%s)) w using (ticker)
              where o.period_type='quarterly' and o.statement='cash_flow'
                and o.raw_jsonb->>'capital_expenditures' is not null
            )
            select cq, ticker, v, period_end from q where rn = 1 order by cq
            """,
            (BUYER_CHAINS,),
        )
        rows = cur.fetchall()

    per_q: dict[Any, dict[str, float]] = defaultdict(dict)
    end_of: dict[Any, Any] = {}
    for cq, tkr, v, pend in rows:
        per_q[cq][tkr] = float(v)
        end_of[cq] = max(end_of.get(cq, pend), pend)

    quarters = sorted(per_q)
    growth: list[tuple[Any, float]] = []
    for i, q in enumerate(quarters):
        if i < 4:
            continue
        base = quarters[i - 4]
        if (q.year - base.year) * 4 + (q.month - base.month) // 3 != 4:
            continue
        both = set(per_q[q]) & set(per_q[base])
        now = sum(per_q[q][t] for t in both)
        then = sum(per_q[base][t] for t in both)
        if both and then > 0:
            growth.append((q, now / then - 1.0))

    # Expanding z-score: at each quarter use only its own past, never the future.
    out: dict[str, float] = {}
    for i, (q, g) in enumerate(growth):
        hist = [x for _, x in growth[:i]]
        if len(hist) < 4:
            continue
        sd = statistics.pstdev(hist)
        z = 0.0 if sd == 0 else (g - statistics.fmean(hist)) / sd
        known = end_of[q] + timedelta(days=CAPEX_LAG_DAYS)
        out[known.strftime("%Y-%m")] = z

    # Forward-fill: a quarter's surprise stays the live reading until the next.
    months = sorted(out)
    if not months:
        return {}
    filled: dict[str, float] = {}
    cur_val = None
    y0, m0 = (int(x) for x in months[0].split("-"))
    y1, m1 = 2027, 1
    y, m = y0, m0
    while (y, m) < (y1, m1):
        key = f"{y:04d}-{m:02d}"
        if key in out:
            cur_val = out[key]
        if cur_val is not None:
            filled[key] = cur_val
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return filled


def ols_slope(xs: list[float], ys: list[float]) -> float | None:
    """Slope of y on x. None when x has no dispersion to regress against."""
    if len(xs) < MIN_TRAIL:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / var


def long_short(
    months: list[str],
    signal: dict[str, dict[str, float]],
    resid: dict[str, dict[str, float]],
    skip: int = 0,
) -> list[tuple[str, float]]:
    """Equal-weight top-quintile minus bottom-quintile residual return, held 1m.

    Signal at month t; the return earned is month t+1+skip, so nothing in the
    holding period informs the sort.

    `skip` is a DIAGNOSTIC, not a second specification to choose from. Monthly
    short-term reversal is one of the most robust effects in the cross-section,
    and a sort on "moved with an outperforming basket" is exactly the kind of
    sort it contaminates. Inserting a gap month is how you tell "this signal is
    wrong" apart from "reversal is sitting on top of it". The pre-registered
    result is skip=0; anything else is reported as post-hoc.
    """
    out: list[tuple[str, float]] = []
    for i in range(len(months) - 1 - skip):
        t, nxt = months[i], months[i + 1 + skip]
        ranked = sorted(
            (
                (s, tkr)
                for tkr, per_m in signal.items()
                if (s := per_m.get(t)) is not None and nxt in resid.get(tkr, {})
            ),
        )
        k = len(ranked) // QUANTILE
        if k < 3:
            continue
        top = statistics.fmean(resid[tkr][nxt] for _, tkr in ranked[-k:])
        bot = statistics.fmean(resid[tkr][nxt] for _, tkr in ranked[:k])
        out.append((nxt, top - bot))
    return out


def summarise(name: str, series: list[tuple[str, float]]) -> dict[str, Any]:
    """Metrics + the standing per-quarter catastrophic-degradation gate.

    `quarter_gate` is the house rule from `feedback_per_regime_catastrophic_gate`
    and it needs the calendar, so the holding month is carried alongside each
    return rather than being thrown away in `long_short`.
    """
    if len(series) < 12:
        return {"name": name, "n_months": len(series), "status": "too_short"}
    rets = [r for _, r in series]
    mean = statistics.fmean(rets)
    obs = [
        {"market_date": _date(int(m[:4]), int(m[5:7]), 1), "ret": r} for m, r in series
    ]
    return {
        "name": name,
        "n_months": len(rets),
        "mean_monthly_pct": round(100 * mean, 3),
        "sharpe_annualised": round(annualized_sharpe(rets, periods_per_year=12), 3),
        "max_drawdown_pct": round(100 * additive_max_drawdown(rets), 2),
        "hit_rate": round(hit_rate(rets), 3),
        "quarter_gate_passed": quarter_gate(obs, mean, "ret"),
    }


def main() -> int:
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        schema = settings.db_schema
        rets = monthly_returns(conn, schema)
        chains = chain_members(conn, schema)
        capex_z = buyer_capex_surprise(conn, schema)

    if MARKET not in rets:
        print(f"no {MARKET} price history — cannot residualise; aborting")
        return 1

    buyers = sorted({t for c in BUYER_CHAINS for t in chains.get(c, set())} & set(rets))
    suppliers = sorted(
        {t for c, m in chains.items() if c not in NON_SUPPLIER_CHAINS for t in m}
        & set(rets) - set(buyers)
    )
    mkt = rets[MARKET]
    months = sorted(set(mkt) & {m for t in suppliers for m in rets[t]})
    print(
        f"{len(months)} months {months[0]}..{months[-1]}  "
        f"buyers={len(buyers)} suppliers={len(suppliers)}  "
        f"capex-surprise months={len(capex_z)}"
    )

    # Buyer basket, then residualise it against the market on a trailing window.
    basket = {
        m: statistics.fmean([rets[b][m] for b in buyers if m in rets[b]])
        for m in months
        if any(m in rets[b] for b in buyers)
    }

    def residualise(series: dict[str, float]) -> dict[str, float]:
        out = {}
        for i, m in enumerate(months):
            if m not in series:
                continue
            win = [
                x
                for x in months[max(0, i - TRAIL_MONTHS) : i]
                if x in series and x in mkt
            ]
            if len(win) < MIN_TRAIL:
                continue
            beta = ols_slope([mkt[x] for x in win], [series[x] for x in win])
            if beta is None:
                continue
            out[m] = series[m] - beta * mkt.get(m, 0.0)
        return out

    basket_resid = residualise(basket)
    supplier_resid = {t: residualise(rets[t]) for t in suppliers}
    supplier_resid = {t: v for t, v in supplier_resid.items() if len(v) >= MIN_TRAIL}
    print(f"{len(supplier_resid)} suppliers survive residualisation")

    # Trailing sensitivity of each supplier's residual to the buyer's residual.
    gamma: dict[str, dict[str, float]] = defaultdict(dict)
    for tkr, res in supplier_resid.items():
        for i, m in enumerate(months):
            win = [
                x
                for x in months[max(0, i - TRAIL_MONTHS) : i]
                if x in res and x in basket_resid
            ]
            if len(win) < MIN_TRAIL:
                continue
            g = ols_slope([basket_resid[x] for x in win], [res[x] for x in win])
            if g is not None:
                gamma[tkr][m] = g

    sig_a: dict[str, dict[str, float]] = defaultdict(dict)
    sig_b: dict[str, dict[str, float]] = defaultdict(dict)
    sig_gamma_only: dict[str, dict[str, float]] = defaultdict(dict)
    sig_shuffled: dict[str, dict[str, float]] = defaultdict(dict)
    ordered = sorted(gamma)
    for idx, tkr in enumerate(ordered):
        for m, g in gamma[tkr].items():
            if m in basket_resid:
                sig_a[tkr][m] = g * basket_resid[m]
            if m in capex_z:
                sig_b[tkr][m] = g * capex_z[m]
            sig_gamma_only[tkr][m] = g
            # Deterministic derangement: same gammas, wrong owners. No RNG, so
            # the control is reproducible.
            donor = ordered[(idx + 7) % len(ordered)]
            if m in gamma[donor] and m in basket_resid:
                sig_shuffled[tkr][m] = gamma[donor][m] * basket_resid[m]

    results = [
        summarise("A_buyer_return_shock", long_short(months, sig_a, supplier_resid)),
        summarise("B_capex_surprise_shock", long_short(months, sig_b, supplier_resid)),
        summarise(
            "CTRL_sensitivity_only", long_short(months, sig_gamma_only, supplier_resid)
        ),
        summarise(
            "CTRL_shuffled_owners", long_short(months, sig_shuffled, supplier_resid)
        ),
        # post-hoc reversal diagnostic -- see long_short's docstring
        summarise("DIAG_A_skip1", long_short(months, sig_a, supplier_resid, skip=1)),
        summarise("DIAG_B_skip1", long_short(months, sig_b, supplier_resid, skip=1)),
    ]
    print()
    for r in results:
        if r.get("status") == "too_short":
            print(f"  {r['name']:24s} n={r['n_months']} — too short")
            continue
        print(
            f"  {r['name']:24s} n={r['n_months']:3d}  "
            f"Sharpe {r['sharpe_annualised']:+.2f}  "
            f"mean {r['mean_monthly_pct']:+.3f}%/m  "
            f"maxDD {r['max_drawdown_pct']:.1f}%  "
            f"hit {r['hit_rate']:.2f}  quarter-gate {'PASS' if r['quarter_gate_passed'] else 'FAIL'}"
        )

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "returns_test.json").write_text(
        json.dumps(
            {
                "probe": "does the capex demand ledger predict returns",
                "reproduce": "uv run python scripts/research/capex_returns_test.py",
                "window": {
                    "first": months[0],
                    "last": months[-1],
                    "n_months": len(months),
                },
                "limitation": (
                    "massive caps daily history at ~5y on our tier, so the sample "
                    "starts 2021-08 and sits entirely inside the AI capex boom. "
                    "This cannot distinguish 'works' from 'worked in one expansion'."
                ),
                "capex_lag_days": CAPEX_LAG_DAYS,
                "trail_months": TRAIL_MONTHS,
                "buyers": buyers,
                "n_suppliers": len(supplier_resid),
                "portfolios": results,
            },
            indent=1,
            sort_keys=True,
        )
        + "\n"
    )
    print(f"\nwrote {OUT / 'returns_test.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
