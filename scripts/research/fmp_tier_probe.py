"""Is FMP's Starter tier worth buying? Map current entitlements endpoint x symbol.

The decisive question the earlier NTM probe left open: when /analyst-estimates
returns 402 "This value set for 'symbol' is not available under your current
subscription", is the restriction

  (a) ACCOUNT-WIDE on the symbol -- AVGO is outside the free tier's symbol
      universe, so it fails on every endpoint; or
  (b) PER-ENDPOINT -- AVGO is fine generally, but analyst estimates are a gated
      product?

(a) means Starter's advertised "US Coverage" plausibly fixes it. (b) means the
gate is a product tier that Starter's feature list does not mention, so buying
Starter would not restore the NTM leg. The two readings point opposite ways on a
purchase decision, so the probe crosses a blocked symbol with every endpoint
either repo uses.

Symbols: NVDA (known 200 on analyst-estimates) vs AVGO / MU / AMAT (known 402).
Endpoints: everything argon+apex call, plus one representative per category the
Starter tier advertises, plus known-gated controls.

Cost: ~1 call per (endpoint, symbol) pair, against a 250/day quota. Prints the
running total; STOPS at BUDGET.

Reproduce:
    uv run --with pyyaml python scripts/research/fmp_tier_probe.py

Writes docs/research/2026-07-26-fmp-tier-probe.json.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import yaml

FMP = "https://financialmodelingprep.com/stable"
SECRETS = pathlib.Path("/Users/chenxi/projects/apex/config/secrets.yaml")
OUT = pathlib.Path("docs/research/2026-07-26-fmp-tier-probe.json")
BUDGET = 120  # hard stop; ~82 of today's 250 already spent elsewhere

# One known-good symbol and three known-402 (on analyst-estimates) symbols.
GOOD = "NVDA"
BLOCKED = ["AVGO", "MU", "AMAT"]

# (label, path, extra params, category as advertised on the pricing page)
# "symbol" is injected per-probe. Categories map to Starter's feature bullets so
# the delta can be read off directly.
ENDPOINTS = [
    # --- Starter: "Profile and Reference Data"
    ("profile", "/profile", {}, "profile+reference"),
    ("shares-float", "/shares-float", {}, "profile+reference"),
    # --- Starter: "Annual Fundamentals and Ratios"
    ("income-statement", "/income-statement", {"limit": 2}, "annual fundamentals"),
    ("balance-sheet", "/balance-sheet-statement", {"limit": 2}, "annual fundamentals"),
    ("ratios", "/ratios", {"limit": 2}, "annual fundamentals"),
    ("key-metrics", "/key-metrics", {"limit": 2}, "annual fundamentals"),
    # quarterly is the classic paid upgrade -- is it gated for us?
    (
        "income-stmt QUARTER",
        "/income-statement",
        {"limit": 2, "period": "quarter"},
        "quarterly (higher tier?)",
    ),
    # --- Starter: "Historical Stock Price Data"
    ("hist-price-eod/full", "/historical-price-eod/full", {}, "historical prices"),
    ("historical-chart 1day", "/historical-chart/1day", {}, "historical prices"),
    ("quote", "/quote", {}, "historical prices"),
    # --- Starter: "Financial Market News"
    ("news/stock", "/news/stock", {"limit": 2}, "news"),
    # --- the NTM leg (argon issue #302)
    (
        "analyst-estimates",
        "/analyst-estimates",
        {"period": "annual", "limit": 10},
        "ANALYST ESTIMATES",
    ),
    ("price-target-summary", "/price-target-summary", {}, "analyst (gated?)"),
    ("grades", "/grades", {"limit": 2}, "analyst (apex uses)"),
    # --- apex's other calls
    ("earnings", "/earnings", {"limit": 2}, "earnings (apex uses)"),
    # --- known-gated controls: confirm 402 still reads as buyable
    ("etf/holdings", "/etf/holdings", {}, "ETF holdings (known 402)"),
    (
        "institutional-ownership",
        "/institutional-ownership/symbol-positions-summary",
        {"year": 2026, "quarter": 1},
        "13F (gated?)",
    ),
]

# Symbol-free endpoints -- apex calls these; tier gating is account-level only.
GLOBAL_ENDPOINTS = [
    ("sp500-constituent", "/sp500-constituent", {}, "index constituents"),
    ("nasdaq-constituent", "/nasdaq-constituent", {}, "index constituents"),
    (
        "hist sp500-constituent",
        "/historical/sp500-constituent",
        {},
        "index constituents",
    ),
    ("shares-float-all", "/shares-float-all", {"limit": 2}, "bulk (gated?)"),
    ("company-screener", "/company-screener", {"limit": 2}, "screener"),
    ("earnings-calendar", "/earnings-calendar", {"limit": 2}, "calendar"),
]


def main() -> None:
    key = yaml.safe_load(SECRETS.read_text())["fmp"]["api_key"]
    # A macOS system proxy fronts this host and drops TLS every ~60 sequential
    # calls; retry at the transport so one drop does not abort the probe.
    cli = httpx.Client(timeout=30, transport=httpx.HTTPTransport(retries=3))
    spent = 0
    results: list[dict] = []

    def probe(label: str, path: str, params: dict, cat: str, sym: str | None):
        nonlocal spent
        if spent >= BUDGET:
            return None
        spent += 1
        q = dict(params, apikey=key)
        if sym:
            q["symbol"] = sym
        r = cli.get(FMP + path, params=q)
        try:
            j = r.json()
        except ValueError:
            j = {"raw": r.text[:120]}
        n = len(j) if isinstance(j, list) else 0
        # FMP signals "no data" as an empty 200 as readily as a 402 -- record both
        err = ""
        if isinstance(j, dict):
            err = str(j.get("Error Message") or j.get("message") or j.get("raw") or "")
        rec = {
            "endpoint": label,
            "category": cat,
            "symbol": sym,
            "http": r.status_code,
            "rows": n,
            "error": err[:110],
        }
        results.append(rec)
        return rec

    def fmt(rec: dict | None) -> str:
        if rec is None:
            return "  (budget exhausted)"
        ok = rec["http"] == 200 and rec["rows"] > 0
        mark = "OK " if ok else ("EMPTY" if rec["http"] == 200 else "GATE")
        tail = f"rows={rec['rows']}" if rec["http"] == 200 else rec["error"]
        return f"{mark:<5} {rec['http']} {tail[:76]}"

    print("=== 1. THE DECISIVE TEST: is the 402 per-symbol or per-endpoint? ===")
    print("    If AVGO is 200 on profile/income-statement but 402 on")
    print("    analyst-estimates, the gate is a PRODUCT tier, not symbol coverage.\n")
    for sym in [GOOD, *BLOCKED]:
        print(f"  --- {sym}")
        for label, path, params, cat in ENDPOINTS:
            rec = probe(label, path, params, cat, sym)
            print(f"      {label:<24} {fmt(rec)}")
        print()

    print("=== 2. SYMBOL-FREE ENDPOINTS (account-level gating only) ===")
    for label, path, params, cat in GLOBAL_ENDPOINTS:
        rec = probe(label, path, params, cat, None)
        print(f"  {label:<24} {fmt(rec)}")

    print("\n=== 3. HISTORY DEPTH (Starter advertises 'up to 5 years') ===")
    for label, path, params in (
        ("income-statement", "/income-statement", {"limit": 40}),
        ("hist-price-eod/full", "/historical-price-eod/full", {}),
    ):
        rec = probe(f"{label} depth", path, params, "history depth", GOOD)
        if rec and rec["http"] == 200:
            r = cli.get(FMP + path, params=dict(params, symbol=GOOD, apikey=key))
            spent += 1
            j = r.json()
            ds = sorted(x.get("date", "") for x in j if isinstance(x, dict))
            span = f"{ds[0]}..{ds[-1]}" if ds else "-"
            print(f"  {label:<24} n={len(j):<5} {span}")
            rec["span"] = span
        else:
            print(f"  {label:<24} {fmt(rec)}")

    print(f"\nFMP calls spent this run: {spent} (budget {BUDGET})")

    # Verdict rollup: which categories are fully open vs gated, per symbol class.
    print("\n=== 4. ROLLUP: gated pairs (what money would have to buy) ===")
    gated = [r for r in results if r["http"] != 200 or r["rows"] == 0]
    by_cat: dict[str, list[str]] = {}
    for r in gated:
        by_cat.setdefault(r["category"], []).append(
            f"{r['endpoint']}/{r['symbol'] or '-'}({r['http']})"
        )
    for cat, items in sorted(by_cat.items()):
        print(f"  {cat:<26} {len(items):>2}  {', '.join(items[:6])}")
    if not gated:
        print("  none -- every probed pair returned data")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"calls_spent": spent, "results": results}, indent=2) + "\n"
    )
    print(f"\n  -> {OUT}")


if __name__ == "__main__":
    main()
