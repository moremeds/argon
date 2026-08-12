#!/usr/bin/env python
"""Does a name's own valuation, against its own history, time that name?

    uv run python scripts/research/fundamental_valuation_timeseries.py

THE QUESTION, AND WHY IT BLOCKS THE ANCHOR BAND
-----------------------------------------------
§7 of the spec puts a five-level anchor band on the card —
`buy_below / observe_low / observe_mid / observe_high / risk_above` — with spot
marked against it. Read the labels literally: `buy_below` asserts that when this
name is cheap versus its own norm, its own forward return is better. That is a
time-series claim about one ticker, and nothing measured so far tests it.

Two neighbouring results make the question urgent rather than academic:

- CROSS-SECTIONALLY, VALUE IS INVERTED IN THIS UNIVERSE. The 245-name control
  (2026-08-11) measured `book_to_price` at IC **-0.0365 (t -2.32)** and
  `earnings_yield` at -0.0194: the names that looked cheap went on to
  underperform. Only `fcf_yield` carried the conventional sign, at +0.0285
  (t +2.84). A `buy_below` built on book or earnings would point at the wrong
  half of the panel.
- WITHIN-TICKER, THE COMPOSITE IS NULL. The time-series test (2026-08-12) found
  a name's own fundamental level carries nothing about its own forward return
  once de-marketed (IC -0.0047, t -0.41), and it was powered to detect the
  effect the same composite shows cross-sectionally.

Neither of those IS this test. The first ranks names against each other; the
second uses fundamental quality, not price. This one asks the anchor band's own
question: within one name, across its own history, does cheapness precede
strength? Answering it decides whether the band ships with PRESCRIPTIVE labels
(`buy_below`) or DESCRIPTIVE ones ("spot sits at the 88th percentile of its own
10-year range") — the same fork the subscore trajectories already took.

EVERY RATIO IS A YIELD
----------------------
`fundamental/EV`, never `EV/fundamental`. An EV/EBITDA flips sign through zero
EBITDA and ranks the worst business on the board as the cheapest name; the yield
form stays monotone across the whole range. That also makes every signal here
point the same way: HIGH = CHEAP, so the anchor band needs a POSITIVE IC from
all five. One direction to check, not five.

METHOD — imported, not reimplemented
------------------------------------
Statements, expanding within-ticker z-scores, forward outcomes, de-marketing and
the Spearman all come from `fundamental_timeseries_test`, which is the harness
the null result above was measured with. Raw (unadjusted) closes come from
`fundamental_valuation_control`, whose header records why: `adj_close` is
retroactively split-adjusted while `common_stock_shares_outstanding` is
as-reported, and multiplying the two mixes reference frames across every split.
Only the ratio construction is new here. A probe that rewrites its metric tests
the rewrite.

READING THE T-STATS
-------------------
The unit of observation is the TICKER: each contributes one time-series IC.
Raw-outcome ICs share a macro driver and their t-stat is inflated, so it is
directional only; lead with the de-marketed column. Same convention as the
sibling test, deliberately, so the two verdicts can be read side by side.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

#: Captured before the imports below. `fundamental_valuation_control` rewrites
#: `sys.argv` at import time to bind the validation module to its 245-name cache,
#: which discards our own flags.
_ARGV = list(sys.argv)

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fundamental_timeseries_test as T  # noqa: E402
import fundamental_valuation_control as VC  # noqa: E402

V = T.V

OUT_DIR = Path("docs/research/2026-08-12-fundamental-valuation-timeseries")

#: Every signal is a yield, so HIGH = CHEAP for all of them and the anchor band
#: needs a POSITIVE IC from each. The mapping to the spec's methods (§5.3) is
#: what makes each one worth measuring rather than a fishing expedition.
SIGNALS = {
    "fcf_yield": "platform_scale — FCF multiple",
    "earnings_yield": "generic P/E anchor; measured INVERTED cross-sectionally",
    "book_to_price": "generic book anchor; measured INVERTED cross-sectionally",
    "sales_to_ev": "chips_cyclical / software_growth / high_risk_growth — EV/Sales",
    "ebitda_to_ev": "power_infra — EV/EBITDA",
}

#: THE CONTROL, and the reason this probe is not just the table above.
#:
#: Every signal is fundamental/price with a TTM numerator that moves once a
#: quarter and a denominator that moves every day. Most of the within-ticker
#: variation in a "valuation" z-score is therefore PRICE variation: the stock
#: falls, the yield rises, the name reads cheap. If prices mean-revert at all,
#: that construction predicts forward returns mechanically, with the fundamental
#: contributing nothing. Short-horizon reversal is one of the best-documented
#: effects in equities, so this is the default explanation, not a remote risk.
#:
#: `neg_past_ret` is that explanation as a signal: pure trailing return, negated,
#: no fundamental input at all, pushed through the identical pipeline. Read two
#: ways — its own IC says how much reversal alone earns here, and the partial ICs
#: say what survives in each valuation signal once it is held constant.
CONTROL = "neg_past_ret"

#: Standardization windows to compare, in quarters. `None` is the EXPANDING
#: window the 2026-08-12 verdict measured.
#:
#: WHY THIS IS NOW ASKED. The expanding window validated an ORDERING, and the
#: anchor band then inverted its percentiles into PRICE levels — a step the IC
#: never licensed. Measured on the same panel: ASML's `sales_to_ev` median fell
#: from 0.5089 in its oldest quarter-quartile to 0.0926 in its newest, a 5.5x
#: structural re-rating, so the full-history 80th percentile (0.4414) is a
#: 2006-era multiple. Inverted to a price it puts `buy_below` at roughly a sixth
#: of spot — a level the stock would not reach in a 2008-scale crisis, which is
#: not a conservative band but an empty one. NVDA shows the same at 2.8x.
#:
#: The question this run answers: does a trailing window keep the IC? If it does,
#: the band can be rebuilt on a reachable range with the signal still measured.
#: If it does not, the price levels come off the card and only the percentile
#: stays.
WINDOWS = (None, 40, 20, 12)


def rolling_z(values, window):
    """Z-score each point against the trailing `window` observations.

    `window=None` delegates to the expanding version the verdict was measured
    with, so the two paths cannot drift apart.
    """
    if window is None:
        return T.expanding_z(values)
    out = []
    seen = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        seen.append(v)
        tail = seen[-window:]
        if len(tail) < T.MIN_HISTORY:
            out.append(None)
            continue
        mu = sum(tail) / len(tail)
        sd = (sum((x - mu) ** 2 for x in tail) / len(tail)) ** 0.5
        out.append(((v - mu) / sd) if sd else 0.0)
    return out


def trailing_return(px: list, know, horizon: int) -> float | None:
    """Return over the `horizon` sessions ENDING at the knowledge date.

    Uses the same `_entry_index` as the forward leg, so the two windows abut at
    the identical bar and cannot overlap — an overlap would let the outcome leak
    into the control and understate the confound this exists to measure.
    """
    i = T._entry_index(px, know)
    if i is None or i - horizon < 0:
        return None
    p0 = px[i - horizon][1]
    return (px[i][1] / p0 - 1) if p0 > 0 else None


def ratios(
    uw: dict, t: str, periods: list[str], i: int, mktcap: float
) -> dict[str, float | None]:
    """The five valuation yields for one ticker-quarter.

    Enterprise value is guarded to strictly positive: a net-cash name can carry
    EV <= 0, which would flip every EV-denominated yield's sign and rank it as
    infinitely cheap. Those quarters emit None rather than a number that would
    have to be explained away later.
    """
    p = periods[i]
    inc, bs, cf = (
        uw[t]["income-statements"],
        uw[t]["balance-sheets"],
        uw[t]["cash-flows"],
    )
    ni = V._ttm(inc, periods, i, "net_income")
    rev = V._ttm(inc, periods, i, "total_revenue")
    ebitda = V._ttm(inc, periods, i, "ebitda")
    ocf = V._ttm(cf, periods, i, "operating_cashflow")
    capex = V._ttm(cf, periods, i, "capital_expenditures")
    eq = V._f(bs.get(p), "total_shareholder_equity")
    debt = V._f(bs.get(p), "short_long_term_debt_total")
    cash = V._f(bs.get(p), "cash_and_cash_equivalents")
    fcf = (ocf - abs(capex)) if None not in (ocf, capex) else None

    ev = mktcap + (debt or 0.0) - (cash or 0.0)
    ev_ok = ev > 0

    return {
        "fcf_yield": fcf / mktcap if fcf is not None else None,
        "earnings_yield": ni / mktcap if ni is not None else None,
        "book_to_price": eq / mktcap if eq is not None else None,
        "sales_to_ev": rev / ev if (rev is not None and ev_ok) else None,
        "ebitda_to_ev": ebitda / ev if (ebitda is not None and ev_ok) else None,
    }


def main() -> int:
    print("1. loading statements from Postgres ...", flush=True)
    uw = T.load_from_db()
    print(f"   {len(uw)} tickers")

    tickers = sorted(uw)
    adj = V.load_prices(tickers)
    raw = VC.load_raw_close(tickers)
    print(f"   prices: {len(adj)} adjusted (outcomes), {len(raw)} raw (market cap)")

    print("2. building within-ticker valuation z-scores ...", flush=True)
    rows: dict[str, list[dict[str, Any]]] = {}
    dropped_shares = 0
    for t in tickers:
        if t not in adj or t not in raw:
            continue
        bs = uw[t]["balance-sheets"]
        periods = sorted(uw[t]["income-statements"])
        raw_vals: list[dict[str, float | None]] = []
        keep: list[tuple[int, Any]] = []
        for i, p in enumerate(periods):
            know = T.knowledge_date(uw, t, p)
            shares = V._f(bs.get(p), "common_stock_shares_outstanding")
            px = VC.close_on_or_before(raw[t], know)
            if not shares or shares <= 0 or not px:
                dropped_shares += 1
                continue
            raw_vals.append(ratios(uw, t, periods, i, px * shares))
            keep.append((i, know))

        # Expanding z per signal, over this ticker's kept quarters only.
        # The control gets the IDENTICAL expanding-z treatment. Spearman is
        # rank-invariant but expanding z is not a monotone transform across time
        # (each point is scaled by a different running sd), so leaving the
        # control raw would compare two differently-shaped signals.
        raw_past = [trailing_return(adj[t], know, T.HORIZONS["2q"]) for _, know in keep]
        # One z-series per (signal, window). The window is the thing under test:
        # the expanding one validated an ORDERING that the anchor band then
        # inverted into price levels it never licensed.
        zs = {
            f"{s}|w{w}": rolling_z([r[s] for r in raw_vals], w)
            for s in SIGNALS
            for w in WINDOWS
        }
        zs[CONTROL] = T.expanding_z([(-r if r is not None else None) for r in raw_past])

        obs: list[dict[str, Any]] = []
        for j, (_, know) in enumerate(keep):
            entry: dict[str, Any] = {
                "know": know,
                "bucket": f"{know.year}Q{(know.month - 1) // 3 + 1}",
            }
            for key in zs:
                entry[key] = zs[key][j]
            if all(entry[f"{s}|w{WINDOWS[0]}"] is None for s in SIGNALS):
                continue
            for h, days in T.HORIZONS.items():
                ret, dd = T.forward_outcomes(adj[t], know, days)
                entry[f"ret_{h}"], entry[f"dd_{h}"] = ret, dd
            obs.append(entry)
        if len(obs) >= T.MIN_OBS:
            rows[t] = obs
    print(f"   {len(rows)} tickers with >= {T.MIN_OBS} observations")
    print(f"   dropped for missing shares/price: {dropped_shares}")

    print("3. de-marketing by knowledge quarter ...", flush=True)
    by_bucket: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for obs in rows.values():
        for e in obs:
            for h in T.HORIZONS:
                for kind in ("ret", "dd"):
                    v = e[f"{kind}_{h}"]
                    if v is not None:
                        by_bucket[e["bucket"]][f"{kind}_{h}"].append(v)
    means = {
        b: {k: sum(v) / len(v) for k, v in d.items() if v} for b, d in by_bucket.items()
    }
    for obs in rows.values():
        for e in obs:
            for h in T.HORIZONS:
                for kind in ("ret", "dd"):
                    v = e[f"{kind}_{h}"]
                    mu = means.get(e["bucket"], {}).get(f"{kind}_{h}")
                    e[f"{kind}_{h}_dm"] = (v - mu) if None not in (v, mu) else None

    print("4. per-ticker time-series IC ...", flush=True)
    results: dict[str, Any] = {}
    signal_keys = [f"{s}|w{w}" for s in SIGNALS for w in WINDOWS] + [CONTROL]
    for signal in signal_keys:
        for h in T.HORIZONS:
            for outcome in (f"ret_{h}", f"ret_{h}_dm", f"dd_{h}", f"dd_{h}_dm"):
                ics = []
                for obs in rows.values():
                    xs = [
                        (e[signal], e[outcome])
                        for e in obs
                        if e.get(signal) is not None and e.get(outcome) is not None
                    ]
                    if len(xs) < T.MIN_OBS:
                        continue
                    ic = V.spearman([a for a, _ in xs], [b for _, b in xs])
                    if ic is not None:
                        ics.append(ic)
                if ics:
                    summary = V.summarize(ics)
                    summary["n_tickers"] = summary.pop("n_quarters")
                    results[f"{signal}|{outcome}"] = summary

    print("5. partial IC, holding reversal constant ...", flush=True)
    partials: dict[str, Any] = {}
    for signal in [f"{s}|w{w}" for s in SIGNALS for w in WINDOWS]:
        for outcome in ("ret_2q_dm", "ret_2q"):
            ics = []
            for obs in rows.values():
                trio = [
                    (e[signal], e[outcome], e[CONTROL])
                    for e in obs
                    if None not in (e.get(signal), e.get(outcome), e.get(CONTROL))
                ]
                if len(trio) < T.MIN_OBS:
                    continue
                ic = VC.partial_spearman(
                    [a for a, _, _ in trio],
                    [b for _, b, _ in trio],
                    [c for _, _, c in trio],
                )
                if ic is not None:
                    ics.append(ic)
            if ics:
                summary = V.summarize(ics)
                summary["n_tickers"] = summary.pop("n_quarters")
                partials[f"{signal}|{outcome}"] = summary

    payload = {
        "question": (
            "within one ticker, does its own valuation vs its own history "
            "precede its own forward return?"
        ),
        "anchor_band_needs": "positive IC — every signal is a yield, so high = cheap",
        "universe": {
            "tickers_loaded": len(uw),
            "tickers_scored": len(rows),
            "min_obs_per_ticker": T.MIN_OBS,
            "min_history_before_z": T.MIN_HISTORY,
            "observations": sum(len(o) for o in rows.values()),
        },
        "signals": SIGNALS,
        "control": CONTROL,
        "results": results,
        "partial_holding_reversal": partials,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "valuation_timeseries.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n"
    )
    (OUT_DIR / "results.md").write_text(_render(payload))
    print(f"\nwrote {OUT_DIR}/valuation_timeseries.json + results.md")

    print("\n== de-marketed 2q IC by standardization window")
    header = "   signal".ljust(20) + "".join(
        f"{'expanding' if w is None else str(w) + 'q':>18}" for w in WINDOWS
    )
    print(header)
    for s in SIGNALS:
        cells = ""
        for w in WINDOWS:
            r = results.get(f"{s}|w{w}|ret_2q_dm")
            cells += f"{r['mean_ic']:+.4f} (t{r['t_stat']:>5}) " if r else f"{'na':>18}"
        print(f"   {s:<17}{cells}")
    ctrl = results.get(f"{CONTROL}|ret_2q_dm")
    if ctrl:
        print(f"\n   {CONTROL} (control): {ctrl['mean_ic']:+.4f} (t {ctrl['t_stat']})")
    return 0


def _render(p: dict[str, Any]) -> str:
    u = p["universe"]
    out = [
        "# Own-history valuation — does cheapness time a name against itself?",
        "",
        "*REGENERATED on every run · numbers come from `valuation_timeseries.json`*",
        "",
        "```bash",
        "uv run python scripts/research/fundamental_valuation_timeseries.py",
        "```",
        "",
        f"{u['tickers_scored']} tickers scored of {u['tickers_loaded']} loaded · "
        f"{u['observations']} observations · z-scores expanding, "
        f"{u['min_history_before_z']}-quarter warmup.",
        "",
        "Every signal is a **yield**, so high = cheap and the anchor band's",
        "`buy_below` needs a **positive** IC. Lead with the `_dm` (de-marketed)",
        "columns — the raw ones share a macro driver and their t-stats are inflated.",
        "",
        "| signal | maps to | 2q IC (dm) | t | holding reversal | t | tickers |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for s, desc in p["signals"].items():
        r2 = p["results"].get(f"{s}|ret_2q_dm", {})
        pt = p["partial_holding_reversal"].get(f"{s}|ret_2q_dm", {})
        out.append(
            f"| `{s}` | {desc} | {r2.get('mean_ic', 'na')} | {r2.get('t_stat', 'na')} "
            f"| {pt.get('mean_ic', 'na')} | {pt.get('t_stat', 'na')} "
            f"| {r2.get('n_tickers', 'na')} |"
        )
    ctrl = p["results"].get(f"{p['control']}|ret_2q_dm", {})
    out += [
        f"| **`{p['control']}`** | **the control — pure trailing return, negated, "
        f"no fundamental input** | **{ctrl.get('mean_ic', 'na')}** "
        f"| **{ctrl.get('t_stat', 'na')}** | — | — "
        f"| {ctrl.get('n_tickers', 'na')} |",
        "",
        "The last row is the whole test. Each valuation signal is",
        "fundamental/price with a numerator that moves quarterly and a denominator",
        "that moves daily, so a falling price alone makes a name read cheap. If the",
        "control earns what the signals earn, these are reversal wearing a",
        "fundamental label; the `holding reversal` column is what is left of each",
        "signal once that is held constant.",
    ]
    out += [
        "",
        "## Raw (macro-confounded, directional only)",
        "",
        "| signal | 2q IC | t | 2q drawdown IC | t |",
        "|---|---:|---:|---:|---:|",
    ]
    for s in p["signals"]:
        r = p["results"].get(f"{s}|ret_2q", {})
        d = p["results"].get(f"{s}|dd_2q", {})
        out.append(
            f"| `{s}` | {r.get('mean_ic', 'na')} | {r.get('t_stat', 'na')} "
            f"| {d.get('mean_ic', 'na')} | {d.get('t_stat', 'na')} |"
        )
    return "\n".join(out) + "\n"


def _self_check() -> None:
    """Guards the one piece of new math: the EV sign guard and the yield form."""
    uw = {
        "X": {
            "income-statements": {
                p: {"total_revenue": "100", "ebitda": "20", "net_income": "10"}
                for p in ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31")
            },
            "balance-sheets": {
                "2025-12-31": {
                    "total_shareholder_equity": "500",
                    "short_long_term_debt_total": "200",
                    "cash_and_cash_equivalents": "100",
                }
            },
            "cash-flows": {
                p: {"operating_cashflow": "30", "capital_expenditures": "-5"}
                for p in ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31")
            },
        }
    }
    periods = sorted(uw["X"]["income-statements"])
    r = ratios(uw, "X", periods, 3, 1000.0)
    # EV = 1000 + 200 - 100 = 1100; TTM revenue = 400, TTM ebitda = 80.
    assert abs(r["sales_to_ev"] - 400 / 1100) < 1e-9, r["sales_to_ev"]
    assert abs(r["ebitda_to_ev"] - 80 / 1100) < 1e-9, r["ebitda_to_ev"]
    assert abs(r["fcf_yield"] - 100 / 1000) < 1e-9, r["fcf_yield"]

    # Net cash big enough to drive EV negative must suppress, not flip sign.
    uw["X"]["balance-sheets"]["2025-12-31"]["cash_and_cash_equivalents"] = "5000"
    neg = ratios(uw, "X", periods, 3, 1000.0)
    assert neg["sales_to_ev"] is None and neg["ebitda_to_ev"] is None, neg
    assert neg["fcf_yield"] is not None, "market-cap yields are unaffected by EV"
    print("self-check ok")


if __name__ == "__main__":
    if "--self-check" in _ARGV:
        _self_check()
        raise SystemExit(0)
    raise SystemExit(main())
