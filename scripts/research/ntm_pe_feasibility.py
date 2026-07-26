"""Build a real bottom-up NTM P/E for one sector ETF from current sources.

Feasibility proof, not a production path. Answers: can argon compute forward P/E
for a sector ETF today, with the entitlements it already has?

Method -- three vendors, one call each per input:
  weights   UW      /api/etfs/{etf}/holdings          (ticker + weight)
  prices    massive /v2/aggs/grouped/...              (ONE call, whole market)
  fwd EPS   FMP     /stable/analyst-estimates         (1 call per constituent)

NTM EPS per name is the standard calendar interpolation between the two fiscal
years straddling the next 12 months:

    w = days_until(FY1_end) / 365,  clamped to [0, 1]
    NTM_EPS = w * EPS_FY1 + (1 - w) * EPS_FY2

Aggregation is the WEIGHTED HARMONIC MEAN, computed as an earnings yield sum:

    ETF_PE = sum(w_i) / sum(w_i * EPS_i / P_i)

Not the arithmetic mean of P/E. The arithmetic mean overweights expensive names
without bound and blows up entirely on a negative-EPS constituent. Summing
earnings YIELDS is what index providers do and it handles negative earnings
correctly -- a loss-making name reduces aggregate earnings, which is the
economically right answer rather than a sign flip.

VERDICT (run 2026-07-26, SOXX): NOT implementable on the current FMP plan.

  1. SYMBOL WHITELIST. /analyst-estimates is entitled per-symbol, not per-plan:
     26 of 30 SOXX constituents return HTTP 402 "This value set for 'symbol' is
     not available under your current subscription". Only AMD, NVDA, INTC, TSM
     resolve -> 26.59% of the fund's 99.90% weight. XLK's top ten fares better
     (6/10, 42.80% of its 59.24%) but is still short.
     The gaps are NOT random: in XLK, MU / AVGO / AMAT / LRCX are blocked while
     NVDA / AAPL / MSFT / AMD / INTC / CSCO pass -- the blocked cohort is semis
     and semicap, systematically the highest-multiple names. Dropping them
     biases an aggregate P/E DOWNWARD, by a sector-dependent amount that also
     drifts over time. Worse than no number.

  2. CURRENCY, WITH NO FIELD TO DETECT IT. Estimates arrive in the issuer's
     REPORTING currency while prices are USD. TSM returns
     revenueAvg=3.81e12 and epsAvg=323.34 -- TWD (USD revenue is ~1.2e11) --
     against a USD 403 ADR, printing a P/E of 0.65. The response carries 22
     fields and none of them is a currency. Any bottom-up aggregate silently
     mixes units for every foreign constituent (TSM, ASML, ASX, ARM), and needs
     both an FX rate and the ADR-to-ordinary ratio from a separate source.

  3. Even with 1 and 2 fixed, there is no point-in-time estimate history from
     any vendor, so the `PE_level` percentile term stays unbuildable.

Single-name NTM P/E for a whitelisted ticker DOES work today. The ETF-level
aggregate does not.

FMP CAVEAT: /analyst-estimates rows come back DESCENDING from the furthest-out
fiscal year, so a small `limit` returns only far-future years and silently omits
FY1/FY2. limit=10 is the smallest that reaches them; limit>=20 is HTTP 402.
Note 402 (plan lacks it, buyable) vs 403 (endpoint retired) are different.

Cost: 1 UW + 1 massive + N_constituents FMP calls (FMP quota is 250/day).

Reproduce:
    uv run --with pyyaml python scripts/research/ntm_pe_feasibility.py [ETF]

Writes docs/research/2026-07-26-ntm-pe-feasibility.json.
"""

from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import httpx
import yaml

from uw_scan.config import Settings

FMP = "https://financialmodelingprep.com/stable"
FMP_SECRETS = pathlib.Path("/Users/chenxi/projects/apex/config/secrets.yaml")
OUT = pathlib.Path("docs/research/2026-07-26-ntm-pe-feasibility.json")

ETF = (sys.argv[1] if len(sys.argv) > 1 else "SOXX").upper()
# Most recent completed session. Grouped-daily returns [] on weekends/holidays,
# so walk back until it does not.
PRICE_PROBE_DAYS = 6


def ntm_eps(rows: list[dict], today: dt.date) -> tuple[float | None, dict]:
    """Interpolate NTM EPS from annual fiscal-year estimates."""
    fys = sorted(
        (dt.date.fromisoformat(r["date"][:10]), r)
        for r in rows
        if r.get("date") and r.get("epsAvg") is not None
    )
    future = [(d, r) for d, r in fys if d > today]
    if len(future) < 2:
        return None, {"reason": f"only {len(future)} future FY rows"}
    (d1, r1), (d2, r2) = future[0], future[1]
    w = max(0.0, min(1.0, (d1 - today).days / 365.0))
    eps = w * float(r1["epsAvg"]) + (1.0 - w) * float(r2["epsAvg"])
    return eps, {
        "fy1_end": d1.isoformat(),
        "fy1_eps": float(r1["epsAvg"]),
        "fy2_end": d2.isoformat(),
        "fy2_eps": float(r2["epsAvg"]),
        "weight_fy1": round(w, 4),
        "analysts_fy1": r1.get("numAnalystsEps"),
    }


def main() -> None:
    s = Settings.from_env()
    uw = {"Authorization": f"Bearer {s.api_key.get_secret_value()}"}
    mk = s.massive_api_key
    mk = mk.get_secret_value() if hasattr(mk, "get_secret_value") else mk
    fk = yaml.safe_load(FMP_SECRETS.read_text())["fmp"]["api_key"]
    cli = httpx.Client(timeout=30, transport=httpx.HTTPTransport(retries=3))
    today = dt.date.today()

    # --- 1. weights (UW) -------------------------------------------------
    holds = (
        cli.get(f"https://api.unusualwhales.com/api/etfs/{ETF}/holdings", headers=uw)
        .json()
        .get("data")
        or []
    )
    weights = {
        h["ticker"]: float(h["weight"])
        for h in holds
        if h.get("ticker") and h.get("weight")
    }
    wsum = sum(weights.values())
    print(f"{ETF}: {len(weights)} constituents, weight_sum={wsum:.2f}%")
    if not weights:
        print("  UW serves no holdings for this ETF -- bottom-up impossible.")
        return

    # --- 2. prices (massive, ONE call for the whole market) ---------------
    prices: dict[str, float] = {}
    for back in range(1, PRICE_PROBE_DAYS):
        d = (today - dt.timedelta(days=back)).isoformat()
        res = (
            cli.get(
                f"https://api.massive.com/v2/aggs/grouped/locale/us/market/stocks/{d}",
                params={"adjusted": "true", "apiKey": mk},
            )
            .json()
            .get("results")
            or []
        )
        if res:
            prices = {r["T"]: float(r["c"]) for r in res if r.get("c")}
            print(f"  prices: {len(prices)} tickers from grouped-daily {d} (1 call)")
            break

    # --- 3. forward EPS (FMP, 1 call per constituent) ---------------------
    detail, calls = {}, 0
    for t in sorted(weights):
        calls += 1
        r = cli.get(
            f"{FMP}/analyst-estimates",
            params={"symbol": t, "period": "annual", "limit": 10, "apikey": fk},
        )
        try:
            rows = r.json()
        except ValueError:
            rows = []
        eps, meta = ntm_eps(rows, today) if isinstance(rows, list) else (None, {})
        detail[t] = {
            "weight": weights[t],
            "price": prices.get(t),
            "ntm_eps": eps,
            "http": r.status_code,
            **meta,
        }
    print(f"  FMP calls spent: {calls}")

    # --- 4. aggregate: weighted harmonic mean via earnings-yield sum -----
    cov_w = yield_w = 0.0
    missing = []
    for t, d in detail.items():
        if d["ntm_eps"] is None or not d["price"]:
            missing.append(t)
            continue
        cov_w += d["weight"]
        yield_w += d["weight"] * (d["ntm_eps"] / d["price"])
        d["ntm_pe"] = round(d["price"] / d["ntm_eps"], 2) if d["ntm_eps"] else None

    if yield_w <= 0:
        print("  aggregate earnings yield <= 0 -- no meaningful P/E")
        return
    etf_ntm_pe = cov_w / yield_w
    print(
        f"\n  weight covered      : {cov_w:.2f}% of {wsum:.2f}% "
        f"({cov_w / wsum * 100:.1f}%)"
    )
    print(f"  missing estimates   : {len(missing)} -> {missing[:12]}")
    print(f"  aggregate NTM yield : {yield_w / cov_w * 100:.3f}%")
    print(f"  >>> {ETF} NTM P/E   : {etf_ntm_pe:.2f}")

    print("\n  top 10 by weight:")
    print(f"    {'tkr':<6}{'wt%':>7}{'price':>9}{'ntmEPS':>9}{'ntmPE':>8}  fy1_end")
    for t in sorted(detail, key=lambda x: -detail[x]["weight"])[:10]:
        d = detail[t]
        print(
            f"    {t:<6}{d['weight']:>7.2f}"
            f"{(d['price'] or 0):>9.2f}"
            f"{(d['ntm_eps'] or 0):>9.2f}"
            f"{str(d.get('ntm_pe') or '-'):>8}  {d.get('fy1_end', '-')}"
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {
                "etf": ETF,
                "as_of": today.isoformat(),
                "ntm_pe": etf_ntm_pe,
                "weight_covered_pct": cov_w,
                "weight_total_pct": wsum,
                "missing": missing,
                "fmp_calls": calls,
                "constituents": detail,
            },
            indent=2,
            default=str,
        )
        + "\n"
    )
    print(f"\n  -> {OUT}")


if __name__ == "__main__":
    main()
