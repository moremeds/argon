#!/usr/bin/env python
"""Does the fundamental method's score predict anything? First-pass test.

Spec: docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md (§5.2, §13).

Deliberately run BEFORE P1b builds the ingest pipeline. The whole dataset is
~1,673 rows behind ~100 API calls, so it is cheaper to test the method than to
build storage for a method that may not work. P1b is a week of schema, ingest,
integrity gate, PIT join and backfill — all wasted if the answer here is no.

TWO UNIVERSES — `--wide` IS THE ONE THAT CAN ANSWER THE QUESTION
----------------------------------------------------------------
Default: the 25-name AI cohort. `--wide`: 245 names with deep price history and
>=40 quarters of UW statements (see fundamental_universe_breadth_probe.py).

The cohort run is underpowered BY CONSTRUCTION, which the first run of this
script established the hard way. Per-quarter IC noise runs sigma ~ 1/sqrt(N-1);
at the cohort's median 11 names that is 0.32, so over 77 quarters the smallest
detectable |IC| is 0.072 — while a realistic equity factor runs 0.02-0.05. A
true IC of 0.03 and a true IC of zero produce indistinguishable output. The
honest reading of the cohort run is therefore "untestable", NOT "does not work",
and the original conclusion had to be retracted on exactly this point.

At N=245 the floor drops to 0.018 and 18 quarters suffice; we have ~52.

  * a NEGATIVE result on `--wide` is informative — it bounds the effect below
    ~0.018 and kills a ranked composite on evidence;
  * a POSITIVE result is evidence the ordering is real, but still NOT evidence
    of tradability: no costs, no capacity, no shorting constraints here.
  * ANY result on the default cohort is uninformative about effects under 0.072.

SURVIVORSHIP IS NOT FIXED BY WIDENING
-------------------------------------
Both sources carry live tickers only — ATVI, XLNX, TWTR, SIVB, FRC and VMW are
absent from the lake and return HTTP 200 with an empty array from UW. Breadth
buys statistical power; it cannot buy back the names that failed. Every result
here describes companies that survived to 2026.

Reported alongside every IC: the number of quarters, the cross-section width per
quarter, and a t-stat computed on the quarterly IC series (which is the honest
unit of observation — not the ticker-quarter, since names move together).

POINT-IN-TIME
-------------
Scores are stamped with a KNOWLEDGE DATE, never the period end. `filing_date`
from UW's fundamental-breakdown where it joins (45.2% of quarters, §3.3), else
`period_end + FALLBACK_LAG_DAYS`. Forward returns start the trading day AFTER
the knowledge date. Using period_end would leak roughly six weeks of hindsight
into every observation and manufacture a signal.

Reproduce:

    UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py
    UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py --wide

Writes `validation{,_wide}.json` + `results{,_wide}.md` under
`docs/research/2026-08-11-fundamental-signal-validation/`. The two runs never
overwrite each other — they are meant to be read side by side. The hand-written
interpretation lives in `VERDICT.md`, which this script must never overwrite.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import pyarrow.parquet as pq

OUT_DIR = Path("docs/research/2026-08-11-fundamental-signal-validation")
COVERAGE = Path("docs/research/2026-08-10-fundamental-source-coverage/coverage.json")
BREADTH = OUT_DIR / "universe_breadth.json"
LAKE = Path.home() / "market-warehouse/data-lake/bronze/asset_class=equity"

# `--wide` runs the same method over the 245-name universe from
# fundamental_universe_breadth_probe.py instead of the 25-name AI cohort. The
# cohort run is underpowered by construction (detection floor |IC| ~ 0.072
# against a realistic factor of 0.02-0.05); the wide run's floor is ~0.018.
#
# Separate cache AND separate outputs, deliberately: the two runs must be
# comparable side by side, so neither may overwrite the other.
WIDE = "--wide" in sys.argv
SUFFIX = "_wide" if WIDE else ""
CACHE = OUT_DIR / f"_uw_cache{SUFFIX}.json"

UW_BASE = "https://api.unusualwhales.com"
STATEMENTS = ("income-statements", "balance-sheets", "cash-flows")

# Conservative: US filers must file a 10-Q within 40-45 days of quarter end.
# Erring LATE cannot manufacture signal; erring early would.
FALLBACK_LAG_DAYS = 45

# Forward windows in trading days.
HORIZONS = {"1q": 63, "2q": 126}

# A cross-section thinner than this cannot produce a meaningful rank correlation.
MIN_CROSS_SECTION = 8


# ---------- data ----------


def _get(c: httpx.Client, url: str, tries: int = 4):
    """Retry transient network failures. A ReadTimeout here would otherwise
    abort a ~100-call fetch partway and leave no cache to resume from."""
    for attempt in range(tries):
        try:
            return c.get(url)
        except (
            httpx.ReadTimeout,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
        ) as exc:
            if attempt == tries - 1:
                raise
            wait = 2**attempt
            print(f"    {type(exc).__name__} on {url} — retry in {wait}s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def fetch_uw(tickers: list[str], key: str) -> dict[str, Any]:
    """All statements + filing metadata, cached — iterating shouldn't re-bill."""
    if CACHE.exists():
        print(f"  using cache {CACHE}")
        return json.loads(CACHE.read_text())
    out: dict[str, Any] = {}
    with httpx.Client(
        base_url=UW_BASE,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
        timeout=90.0,
    ) as c:
        for t in tickers:
            per: dict[str, Any] = {}
            for ep in STATEMENTS:
                r = _get(c, f"/api/stock/{t}/{ep}")
                rows = r.json().get("data") or [] if r.status_code == 200 else []
                per[ep] = {
                    x["fiscal_date_ending"]: x
                    for x in rows
                    if x.get("report_type") == "quarterly"
                    and x.get("fiscal_date_ending")
                }
            r = _get(c, f"/api/stock/{t}/fundamental-breakdown")
            gen = (
                (r.json().get("data") or {}).get("general") or []
                if r.status_code == 200
                else []
            )
            per["filing_dates"] = {
                g["report_period_end_date"]: g["filing_date"]
                for g in gen
                if g.get("report_period_end_date") and g.get("filing_date")
            }
            out[t] = per
            print(
                f"  {t:6} {len(per['income-statements']):3}q  "
                f"{len(per['filing_dates']):3} filing dates",
                flush=True,
            )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(out))
    return out


def load_prices(tickers: list[str]) -> dict[str, list[tuple[date, float]]]:
    """Daily adjusted closes from the local lake mirror."""
    out: dict[str, list[tuple[date, float]]] = {}
    for t in tickers:
        f = LAKE / f"symbol={t}" / "1d.parquet"
        if not f.exists():
            continue
        df = pq.read_table(f, columns=["trade_date", "adj_close"]).to_pandas()
        df = df.dropna().sort_values("trade_date")
        out[t] = list(
            zip(df["trade_date"].tolist(), df["adj_close"].astype(float).tolist())
        )
    return out


# ---------- derive ----------


def _f(row: dict | None, key: str) -> float | None:
    if not row:
        return None
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ttm(series: dict[str, dict], periods: list[str], i: int, key: str) -> float | None:
    """Trailing four quarters. None unless all four are present — a 3-quarter
    'TTM' silently understates by ~25% and would be indistinguishable from a
    genuine decline."""
    if i < 3:
        return None
    vals = [_f(series.get(p), key) for p in periods[i - 3 : i + 1]]
    return sum(vals) if all(v is not None for v in vals) else None


def build_features(uw: dict[str, Any]) -> dict[str, dict[str, dict[str, float | None]]]:
    """Per ticker, per period: the raw inputs behind §5.2's subscores."""
    feats: dict[str, dict[str, dict[str, float | None]]] = {}
    for t, per in uw.items():
        inc, bs, cf = per["income-statements"], per["balance-sheets"], per["cash-flows"]
        periods = sorted(inc)
        pf: dict[str, dict[str, float | None]] = {}
        for i, p in enumerate(periods):
            rev_ttm = _ttm(inc, periods, i, "total_revenue")
            rev_ttm_prev = (
                _ttm(inc, periods, i - 4, "total_revenue") if i >= 7 else None
            )
            ocf_ttm = _ttm(cf, periods, i, "operating_cashflow")
            capex_ttm = _ttm(cf, periods, i, "capital_expenditures")
            ebitda_ttm = _ttm(inc, periods, i, "ebitda")
            ni_ttm = _ttm(inc, periods, i, "net_income")
            b = bs.get(p)

            gp, rev_q = _f(inc.get(p), "gross_profit"), _f(inc.get(p), "total_revenue")
            oi = _f(inc.get(p), "operating_income")
            cash, debt = (
                _f(b, "cash_and_cash_equivalents"),
                _f(b, "short_long_term_debt_total"),
            )
            equity, assets = _f(b, "total_shareholder_equity"), _f(b, "total_assets")

            fcf = (
                (ocf_ttm - abs(capex_ttm)) if None not in (ocf_ttm, capex_ttm) else None
            )
            pf[p] = {
                # growth
                "rev_growth": (rev_ttm / rev_ttm_prev - 1)
                if rev_ttm and rev_ttm_prev and rev_ttm_prev > 0
                else None,
                # profitability
                "gross_margin": (gp / rev_q) if gp is not None and rev_q else None,
                "op_margin": (oi / rev_q) if oi is not None and rev_q else None,
                # capital efficiency
                "fcf_margin": (fcf / rev_ttm) if fcf is not None and rev_ttm else None,
                "roe": (ni_ttm / equity)
                if ni_ttm is not None and equity and equity > 0
                else None,
                # balance sheet (sign flipped so higher is always better)
                "neg_net_debt_ebitda": (-((debt - cash) / ebitda_ttm))
                if None not in (debt, cash, ebitda_ttm)
                and ebitda_ttm
                and ebitda_ttm > 0
                else None,
                "asset_turnover": (rev_ttm / assets) if rev_ttm and assets else None,
            }
        feats[t] = pf
    return feats


FEATURES = [
    "rev_growth",
    "gross_margin",
    "op_margin",
    "fcf_margin",
    "roe",
    "neg_net_debt_ebitda",
    "asset_turnover",
]


def knowledge_date(uw: dict, t: str, period: str) -> date:
    fd = uw[t]["filing_dates"].get(period)
    if fd:
        return date.fromisoformat(fd[:10])
    return date.fromisoformat(period[:10]) + timedelta(days=FALLBACK_LAG_DAYS)


def forward_return(
    px: list[tuple[date, float]], know: date, horizon: int
) -> float | None:
    """Return from the first close STRICTLY after the knowledge date."""
    lo, hi = 0, len(px)
    while lo < hi:  # first index with trade_date > know
        mid = (lo + hi) // 2
        if px[mid][0] > know:
            hi = mid
        else:
            lo = mid + 1
    if lo >= len(px) or lo + horizon >= len(px):
        return None
    p0, p1 = px[lo][1], px[lo + horizon][1]
    return (p1 / p0 - 1) if p0 > 0 else None


# ---------- stats ----------


def spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None

    def rank(v: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:  # average ties, or repeated values distort the correlation
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return (num / den) if den else None


def zscore(vals: dict[str, float]) -> dict[str, float]:
    v = list(vals.values())
    n = len(v)
    mu = sum(v) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in v) / n) if n > 1 else 0.0
    return {k: ((x - mu) / sd if sd else 0.0) for k, x in vals.items()}


def quarterly_ics(
    panel: dict[str, dict[str, dict[str, Any]]],
    buckets: list[str],
    horizon: str,
    keep: Any = None,
) -> tuple[dict[str, list[float]], list[float]]:
    """Quarterly rank-IC series: (per-feature, composite).

    `keep(bucket, ticker, row) -> bool` subsets the panel. Every robustness
    check routes through this one implementation on purpose — a robustness
    check that reimplements the metric tests the reimplementation, not the
    claim.
    """
    per_feature: dict[str, list[float]] = defaultdict(list)
    composite: list[float] = []
    for p in buckets:
        rows = panel[p]
        if keep is not None:
            rows = {t: d for t, d in rows.items() if keep(p, t, d)}
        rets = {
            t: d["fwd"][horizon]
            for t, d in rows.items()
            if d["fwd"][horizon] is not None
        }
        if len(rets) < MIN_CROSS_SECTION:
            continue
        zs: dict[str, dict[str, float]] = {}
        for feat in FEATURES:
            vals = {
                t: rows[t]["features"][feat]
                for t in rets
                if rows[t]["features"].get(feat) is not None
            }
            if len(vals) >= MIN_CROSS_SECTION:
                ic = spearman([vals[t] for t in vals], [rets[t] for t in vals])
                if ic is not None:
                    per_feature[feat].append(ic)
                zs[feat] = zscore(vals)
        # composite = mean of available z-scores, renormalized by presence
        comp = {}
        for t in rets:
            got = [zs[f][t] for f in zs if t in zs[f]]
            if len(got) >= 4:  # refuse to score a name on <4 of 7 features
                comp[t] = sum(got) / len(got)
        if len(comp) >= MIN_CROSS_SECTION:
            ic = spearman([comp[t] for t in comp], [rets[t] for t in comp])
            if ic is not None:
                composite.append(ic)
    return per_feature, composite


def summarize(ics: list[float]) -> dict[str, Any]:
    """Mean IC with a t-stat on the QUARTERLY series.

    The quarter is the unit of observation, not the ticker-quarter: these names
    move together, so treating 20 correlated tickers as 20 observations would
    inflate the t-stat by roughly sqrt(20).
    """
    n = len(ics)
    if n < 2:
        return {"n_quarters": n, "mean_ic": ics[0] if ics else None, "t_stat": None}
    mu = sum(ics) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in ics) / (n - 1))
    return {
        "n_quarters": n,
        "mean_ic": round(mu, 4),
        "ic_stdev": round(sd, 4),
        "t_stat": round(mu / (sd / math.sqrt(n)), 3) if sd else None,
        "hit_rate": round(sum(1 for x in ics if x > 0) / n, 3),
    }


def main() -> int:
    key = os.environ.get("UW_SCAN_API_KEY", "").strip()
    if not key:
        print("UW_SCAN_API_KEY is not set", file=sys.stderr)
        return 2
    if WIDE:
        if not BREADTH.exists():
            print(
                f"{BREADTH} missing — run fundamental_universe_breadth_probe.py first",
                file=sys.stderr,
            )
            return 2
        breadth = json.loads(BREADTH.read_text())
        gate = breadth["gates"]["min_quarters"]
        tickers = sorted(
            r["ticker"] for r in breadth["names"] if (r.get("quarters") or 0) >= gate
        )
    else:
        tickers = list(json.loads(COVERAGE.read_text())["tickers"])

    print(f"== fetching UW statements for {len(tickers)} tickers")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    uw = fetch_uw(tickers, key)

    print("\n== loading prices from the local lake mirror")
    prices = load_prices(tickers)
    missing_px = [t for t in tickers if t not in prices]
    print(
        f"  {len(prices)}/{len(tickers)} tickers have price data; missing: {missing_px or 'none'}"
    )

    feats = build_features(uw)

    # (bucket -> ticker -> feature/return), the cross-sections we score within.
    #
    # Bucket on the KNOWLEDGE-DATE quarter, NOT on `fiscal_date_ending`. Filers
    # do not share a fiscal calendar — NVDA's quarter ends 01-31, MSFT's 12-31,
    # AAPL's 12-28 — so keying on the raw period end shatters one economic
    # cross-section into many thin ones, each of which then fails
    # MIN_CROSS_SECTION and is dropped without a word. Measured on the 245-name
    # universe, period-end keying gave 268 "periods" with a MEDIAN WIDTH OF 23
    # against a max of 206: most of the purchased breadth was being discarded,
    # and a thin cross-section reads as "no signal".
    #
    # Knowledge-date bucketing is also the more correct construction. A rank IC
    # is only meaningful among names whose information was available at the same
    # time — which is what the knowledge date, and nothing else, encodes.
    panel: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for t, pf in feats.items():
        if t not in prices:
            continue
        for period, row in pf.items():
            know = knowledge_date(uw, t, period)
            fwd = {h: forward_return(prices[t], know, d) for h, d in HORIZONS.items()}
            if all(v is None for v in fwd.values()):
                continue
            bucket = f"{know.year}Q{(know.month - 1) // 3 + 1}"
            # A late 10-K and an on-time 10-Q can both land in one bucket. One
            # name gets one vote per cross-section; keep the fresher period.
            prior = panel[bucket].get(t)
            if prior and prior["period"] >= period:
                continue
            panel[bucket][t] = {
                "features": row,
                "fwd": fwd,
                "period": period,
                "knowledge_date": know.isoformat(),
                "had_filing_date": period in uw[t]["filing_dates"],
            }

    periods = sorted(panel)
    usable = [p for p in periods if len(panel[p]) >= MIN_CROSS_SECTION]
    print(
        f"\n== panel: {len(periods)} periods, {len(usable)} with >= {MIN_CROSS_SECTION} names"
    )
    if usable:
        widths = [len(panel[p]) for p in usable]
        print(
            f"   cross-section width: min {min(widths)} median "
            f"{sorted(widths)[len(widths) // 2]} max {max(widths)}"
        )
        print(f"   span: {usable[0]} .. {usable[-1]}")
        # The bucketing bug this guard exists for did not crash — it silently
        # dropped ~90% of the cross-section (median width 23 of 245 available)
        # and returned a confident, well-formatted, wrong number. A realised
        # width far below the universe is the symptom; nothing else surfaces it.
        med = sorted(widths)[len(widths) // 2]
        if med < 0.5 * len(tickers):
            print(
                f"   !! median width {med} is under half the {len(tickers)}-name "
                "universe — cross-sections are being fragmented, not measured"
            )
    pit = [d for p in usable for d in panel[p].values()]
    print(
        f"   observations: {len(pit)}, of which {sum(1 for d in pit if d['had_filing_date'])} "
        f"have a real filing_date (rest use period_end + {FALLBACK_LAG_DAYS}d)"
    )

    # per-feature and composite IC, per horizon
    results: dict[str, Any] = {}
    for horizon in HORIZONS:
        per_feature, composite = quarterly_ics(panel, usable, horizon)
        results[horizon] = {
            "composite": summarize(composite),
            "per_feature": {f: summarize(v) for f, v in sorted(per_feature.items())},
        }
        c = results[horizon]["composite"]
        print(f"\n== {horizon} forward return")
        print(
            f"   COMPOSITE  mean IC {c['mean_ic']}  t {c['t_stat']}  "
            f"hit {c.get('hit_rate')}  over {c['n_quarters']} quarters"
        )
        for f, s in results[horizon]["per_feature"].items():
            print(
                f"     {f:22} IC {str(s['mean_ic']):>8}  t {str(s['t_stat']):>7}  "
                f"n {s['n_quarters']}"
            )

    # ---- robustness: the two ways a positive result here is most likely fake --
    #
    # 1. PIT LEAKAGE. Roughly 45% of observations have no real `filing_date` and
    #    fall back to period_end + 45d. That fallback errs EARLY for any filer
    #    that took longer — and scoring on data before it was public is the
    #    classic way to manufacture an IC out of nothing. If the effect is real
    #    it must survive on the filing_date-only subset, which has no fallback.
    # 2. ONE-REGIME ARTIFACT. An effect present in only half the sample
    #    describes an era, not a relationship. The cohort run's `asset_turnover`
    #    result was exactly this, and flipped sign once the universe widened.
    #
    # Neither check can prove the result; both can kill it.
    print("\n== robustness (2q composite)")
    checks: dict[str, Any] = {
        "full sample": None,
        "real filing_date only": lambda p, t, d: d["had_filing_date"],
        "first half (<=2015)": lambda p, t, d: p <= "2015Q4",
        "second half (>=2016)": lambda p, t, d: p >= "2016Q1",
    }
    robustness: dict[str, Any] = {}
    for label, keep in checks.items():
        _, ics = quarterly_ics(panel, usable, "2q", keep)
        robustness[label] = summarize(ics)
        s = robustness[label]
        print(
            f"   {label:24} IC {str(s['mean_ic']):>8}  t {str(s['t_stat']):>7}  "
            f"n {s['n_quarters']}"
        )

    payload = {
        "probed_at": "2026-08-11",
        "reproduce": (
            "UW_SCAN_API_KEY=... uv run python "
            "scripts/research/fundamental_signal_validation.py"
            + (" --wide" if WIDE else "")
        ),
        "universe": "wide-245" if WIDE else "ai-cohort-25",
        "robustness_2q": robustness,
        "caveat": (
            "Survivorship-selected: both the lake and UW carry live tickers only "
            "(ATVI/XLNX/TWTR/SIVB/FRC/VMW return zero rows), so these are "
            "companies that survived to 2026. No costs, capacity or shorting "
            "constraints are modelled — an IC is not a strategy."
            if WIDE
            else "25 highly correlated AI/semi/cloud names; effective breadth is "
            "~2-4 independent bets. Detection floor |IC| ~0.072 against a "
            "realistic factor of 0.02-0.05, so this run is underpowered by "
            "construction and cannot support any conclusion about the composite."
        ),
        "config": {
            "horizons_trading_days": HORIZONS,
            "fallback_lag_days": FALLBACK_LAG_DAYS,
            "min_cross_section": MIN_CROSS_SECTION,
            "features": FEATURES,
        },
        "coverage": {
            "tickers_with_prices": sorted(prices),
            "tickers_missing_prices": missing_px,
            "periods_total": len(periods),
            "periods_usable": len(usable),
            "span": [usable[0], usable[-1]] if usable else None,
            "observations": len(pit),
            "observations_with_real_filing_date": sum(
                1 for d in pit if d["had_filing_date"]
            ),
        },
        "results": results,
    }
    (OUT_DIR / f"validation{SUFFIX}.json").write_text(
        json.dumps(payload, indent=2) + "\n"
    )
    (OUT_DIR / f"results{SUFFIX}.md").write_text(_render(payload))
    print(f"\nwrote {OUT_DIR}/validation{SUFFIX}.json and results{SUFFIX}.md")
    return 0


def _render(p: dict[str, Any]) -> str:
    c = p["coverage"]
    lines = [
        "# Fundamental signal validation — measured results",
        "",
        f"*{p['probed_at']} · REGENERATED on every run — interpretation is in `VERDICT.md` · spec §5.2, §13*",
        "",
        "```bash",
        p["reproduce"],
        "```",
        "",
        f"> **{p['caveat']}**",
        "",
        "## Coverage",
        "",
        f"- {len(c['tickers_with_prices'])} tickers with prices"
        f"{'; missing ' + ', '.join(c['tickers_missing_prices']) if c['tickers_missing_prices'] else ''}",
        f"- {c['periods_usable']} usable quarters of {c['periods_total']}"
        f"{' spanning ' + c['span'][0] + ' .. ' + c['span'][1] if c['span'] else ''}",
        f"- {c['observations']} observations, {c['observations_with_real_filing_date']} with a real"
        f" `filing_date` (rest lagged {p['config']['fallback_lag_days']}d from period end)",
        "",
        "## Results",
        "",
        "Rank IC of each signal against forward return, averaged across quarters."
        " The t-stat is computed on the **quarterly IC series**, not on"
        " ticker-quarters — these names move together, so pooling would inflate it"
        " by roughly sqrt(cross-section).",
        "",
    ]
    for horizon, r in p["results"].items():
        comp = r["composite"]
        lines += [
            f"### {horizon} forward return",
            "",
            "| Signal | mean IC | t-stat | hit rate | quarters |",
            "|---|---:|---:|---:|---:|",
            f"| **composite** | **{comp['mean_ic']}** | **{comp['t_stat']}** |"
            f" {comp.get('hit_rate')} | {comp['n_quarters']} |",
        ]
        for f, s in r["per_feature"].items():
            lines.append(
                f"| `{f}` | {s['mean_ic']} | {s['t_stat']} | {s.get('hit_rate')} |"
                f" {s['n_quarters']} |"
            )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
