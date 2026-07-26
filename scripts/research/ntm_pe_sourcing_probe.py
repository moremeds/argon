"""Can argon source NTM (forward) P/E for sector ETFs? Live entitlement probe.

Motivation: the proposed "valuation heat" factor needs
    ValuationHeat = z(PE_level) + z(PE_expansion_3m) - z(NTM_EPS_revision_3m)
where PE is NTM (next-twelve-months). No vendor publishes NTM P/E for an ETF,
so it must be built bottom-up: sum(weight_i * price_i) / sum(weight_i * NTM_EPS_i).
That needs (a) holdings weights, (b) per-constituent forward EPS, (c) point-in-time
history of both. This probe checks each independently against live entitlements.

Answer: the NTM *level* IS sourceable -- FMP serves a forward FY curve, UW the
weights, massive the prices. The NTM *history* is not, from any of the three.
See docs/research/2026-07-26-ntm-pe-sourcing-probe.md.

Reproduce:
    uv run python scripts/research/ntm_pe_sourcing_probe.py

Read-only: issues GETs against UW, massive and FMP. Writes nothing.
Section H spends ~5 calls of FMP's 250/day quota; it self-skips if the apex
secrets file holding the FMP key is absent.
"""

from __future__ import annotations

import datetime as dt
import pathlib
from collections import Counter

import httpx

from uw_scan.config import Settings

UW = "https://api.unusualwhales.com"
MASSIVE = "https://api.massive.com"
FMP = "https://financialmodelingprep.com/stable"
# FMP key lives in the sibling apex repo; argon has no FMP config of its own.
FMP_SECRETS = pathlib.Path("/Users/chenxi/projects/apex/config/secrets.yaml")

# reports.sector_crowding.SECTOR_CROWDING_TICKERS + MAGS
ETFS = [
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP",
    "XLRE", "XLU", "XLV", "XLY", "SOXX", "SMH", "IGV", "MAGS",
]  # fmt: skip

# Polygon-shaped Benzinga suite — where consensus/forward EPS would live.
BENZINGA = ["earnings", "guidance", "analyst-insights", "ratings", "firms"]


def main() -> None:
    s = Settings.from_env()
    uw = {"Authorization": f"Bearer {s.api_key.get_secret_value()}"}
    mk = s.massive_api_key
    mk = mk.get_secret_value() if hasattr(mk, "get_secret_value") else mk

    # A macOS system proxy sits in front of these hosts and drops TLS
    # intermittently; ~60 sequential calls reliably hit one. Retry at transport.
    cli = httpx.Client(timeout=30, transport=httpx.HTTPTransport(retries=3))

    def uget(path: str, **q):
        return cli.get(UW + path, headers=uw, params=q)

    def mget(path: str, **q):
        return cli.get(MASSIVE + path, params={**q, "apiKey": mk})

    print("=== A. FORWARD EPS ENTITLEMENT (the blocker) ===")
    r = uget("/api/companies/NVDA/earnings-estimates")
    print(
        f"  UW   /companies/NVDA/earnings-estimates  {r.status_code} "
        f"{r.json().get('code', '')}"
    )
    for ep in BENZINGA:
        r = mget(f"/benzinga/v1/{ep}", ticker="NVDA", limit=1)
        msg = r.json().get("error", "") if r.status_code != 404 else "(no such path)"
        print(f"  MSSV /benzinga/v1/{ep:<16} {r.status_code} {str(msg)[:52]}")

    print("\n=== B. ETF HOLDINGS: weights present, valuation absent ===")
    row = (uget("/api/etfs/SOXX/holdings").json().get("data") or [{}])[0]
    fields = sorted(row)
    val = [f for f in fields if any(k in f for k in ("pe", "eps", "earn", "cap"))]
    print(f"  SOXX holdings fields ({len(fields)}): {fields}")
    print(f"  valuation-ish fields: {val or 'NONE'}")
    info = uget("/api/etfs/SOXX/info").json().get("data") or {}
    print(f"  /info keys: {sorted(info)}")

    print("\n=== C. HOLDINGS COVERAGE (weight_sum is the honest check) ===")
    print(f"  {'etf':<6}{'rows':>6}{'weight_sum':>12}{'declared':>10}  note")
    union: set[str] = set()
    for t in [*ETFS, "SPY"]:
        rows = uget(f"/api/etfs/{t}/holdings").json().get("data") or []
        declared = (uget(f"/api/etfs/{t}/info").json().get("data") or {}).get(
            "holdings_count"
        )
        ws = sum(float(x["weight"]) for x in rows if x.get("weight"))
        union |= {x["ticker"] for x in rows if x.get("ticker")}
        note = (
            "EMPTY — unusable"
            if not rows
            else "TRUNCATED at 250"
            if len(rows) >= 250
            else "ok"
            if ws > 95
            else "PARTIAL"
        )
        print(f"  {t:<6}{len(rows):>6}{ws:>11.2f}%{str(declared):>10}  {note}")
    print(f"  union of distinct constituents (excl. SPY tail) = {len(union)}")

    print("\n=== D. TRAILING EPS: available, and point-in-time safe? ===")
    res = (
        mget(
            "/vX/reference/financials", ticker="NVDA", timeframe="quarterly", limit=100
        )
        .json()
        .get("results", [])
    )
    ends = sorted(x.get("end_date") or "" for x in res)
    nofile = sum(1 for x in res if not x.get("filing_date"))
    inc = res[0]["financials"]["income_statement"] if res else {}
    print(f"  quarters={len(res)}  {ends[0]}..{ends[-1]}")
    print(f"  diluted_eps present: {'diluted_earnings_per_share' in inc}")
    print(
        f"  filing_date present: {len(res) - nofile}/{len(res)}  "
        f"(missing {nofile} -> lookahead risk if unhandled)"
    )

    print("\n=== E. PRICE PATH for a ~600-ticker universe ===")
    r = mget("/v2/aggs/grouped/locale/us/market/stocks/2026-07-24", adjusted="true")
    j = r.json()
    print(
        f"  grouped-daily {r.status_code}  tickers in ONE call: "
        f"{len(j.get('results') or [])}"
    )
    r = mget("/v3/reference/tickers/NVDA")
    got = r.json().get("results") or {}
    print(f"  /v3/reference/tickers market_cap: {got.get('market_cap')}")

    # The endpoint the first pass missed. UW DOES serve a forward estimate on our
    # tier -- via /stock/, not the gated /companies/. Horizon, depth, PIT honesty:
    print("\n=== F. UW /api/stock/{t}/earnings -- accessible forward estimate ===")
    today = dt.date.today().isoformat()
    for t in ("NVDA", "AMD", "MU", "AVGO", "AAPL", "XLK", "SOXX"):
        rows = uget(f"/api/stock/{t}/earnings", limit=500).json().get("data") or []
        qtr = [r for r in rows if r.get("report_type") == "quarterly"]
        fwd = [r for r in rows if str(r.get("report_date") or "") > today]
        ds = sorted(str(r.get("report_date") or "") for r in qtr)
        print(
            f"  {t:<6} quarterly={len(qtr):<4} forward_quarters={len(fwd)} "
            f"span={ds[0] if ds else '-'}..{ds[-1] if ds else '-'}"
        )

    print("\n  PIT honesty -- was the history captured contemporaneously?")
    rows = uget("/api/stock/NVDA/earnings", limit=500).json().get("data") or []
    done = [
        r for r in rows if r.get("report_type") == "quarterly" and r.get("reported_eps")
    ]
    years = Counter(str(r.get("updated_at") or "")[:4] for r in done)
    print(
        f"    reported quarters={len(done)}  updated_at years={dict(sorted(years.items()))}"
    )
    for r in sorted(done, key=lambda x: str(x.get("report_date")))[:2]:
        print(
            f"    {r['report_date']} est={r['estimated_eps']} rep={r['reported_eps']} "
            f"inserted={str(r.get('inserted_at'))[:10]} "
            f"updated={str(r.get('updated_at'))[:10]}"
        )

    print("\n  forward-estimate coverage, first 15 XLK constituents:")
    holds = uget("/api/etfs/XLK/holdings").json().get("data") or []
    miss = [
        t
        for t in [r["ticker"] for r in holds[:15]]
        if not [
            r
            for r in (
                uget(f"/api/stock/{t}/earnings", limit=500).json().get("data") or []
            )
            if not r.get("reported_eps") and r.get("estimated_eps")
        ]
    ]
    print(f"    missing a forward estimate: {miss or 'none'}")

    print("\n=== G. massive TTM aggregate (convenient, but unfiled) ===")
    for x in (
        mget("/vX/reference/financials", ticker="NVDA", timeframe="ttm", limit=1)
        .json()
        .get("results")
        or []
    ):
        inc = x.get("financials", {}).get("income_statement", {})
        print(
            f"  {x.get('fiscal_period')} {x.get('start_date')}..{x.get('end_date')} "
            f"filing_date={x.get('filing_date')} "
            f"diluted_eps={(inc.get('diluted_earnings_per_share') or {}).get('value')}"
        )

    print("\n=== H. FMP — the only real forward CURVE (quota 250/day) ===")
    if not FMP_SECRETS.exists():
        print(f"  skipped: {FMP_SECRETS} not found")
        return
    import yaml  # noqa: PLC0415 -- optional dep, only this section needs it

    fk = yaml.safe_load(FMP_SECRETS.read_text())["fmp"]["api_key"]

    def fget(path: str, **q):
        r = cli.get(FMP + path, params={**q, "apikey": fk})
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:90]}

    # Rows come back DESCENDING from the furthest-out year, so a small `limit`
    # returns ONLY far-future years and silently omits the near ones NTM needs.
    # limit=10 is the smallest that reaches FY1/FY2; limit=20 is 402.
    for lim in (3, 10, 20):
        c, j = fget("/analyst-estimates", symbol="NVDA", period="annual", limit=lim)
        ds = sorted(x.get("date", "") for x in j) if isinstance(j, list) else []
        print(
            f"  limit={lim:<3} {c} n={len(ds):<3} "
            f"{(ds[0] + '..' + ds[-1]) if ds else str(j)[:58]}"
        )

    _, j = fget("/analyst-estimates", symbol="NVDA", period="annual", limit=10)
    print("  FY curve (the NTM inputs):")
    for x in sorted(j, key=lambda r: r.get("date", ""))[-4:]:
        print(
            f"    {x.get('date')} epsAvg={x.get('epsAvg')} "
            f"analysts={x.get('numAnalystsEps')}"
        )

    for label, path, q in (
        (
            "quarterly estimates",
            "/analyst-estimates",
            {"symbol": "NVDA", "period": "quarter", "limit": 8},
        ),
        ("etf/holdings SMH", "/etf/holdings", {"symbol": "SMH"}),
    ):
        c, j = fget(path, **q)
        n = len(j) if isinstance(j, list) else 0
        msg = str(j.get("raw") or j)[:66] if isinstance(j, dict) else ""
        print(f"  {c} {label:<20} n={n}  {msg}")

    print("\n  budget: tickers needed for X% of aggregate ETF weight")
    for target in (0.80, 0.90, 1.00):
        need: set[str] = set()
        for t in [e for e in ETFS if e not in ("SMH", "MAGS")]:
            rows = sorted(
                uget(f"/api/etfs/{t}/holdings").json().get("data") or [],
                key=lambda x: -float(x.get("weight") or 0),
            )
            tot = sum(float(x.get("weight") or 0) for x in rows) or 1.0
            cum = 0.0
            for x in rows:
                need.add(x["ticker"])
                cum += float(x.get("weight") or 0)
                if cum / tot >= target:
                    break
        print(
            f"    {int(target * 100):>3}% weight -> {len(need):>3} tickers "
            f"-> {-(-len(need) // 250)} day(s) per full refresh at 250/day"
        )


if __name__ == "__main__":
    main()
