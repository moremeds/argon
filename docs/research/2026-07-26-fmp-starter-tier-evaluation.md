# Is FMP's Starter tier worth $22/mo?

**Date:** 2026-07-26 · **Method:** 77-call live entitlement probe on the current key,
cross-read against the published tier matrix · **Verdict: yes — but for apex, not for
the NTM P/E factor that prompted the question.**

**Reproduce:**

```bash
uv run --with pyyaml python scripts/research/fmp_tier_probe.py
```

Read-only. Spends ~77 of FMP's 250/day. Writes
`docs/research/2026-07-26-fmp-tier-probe.json`.

## The question that decided it

Issue #302 tabled the valuation-heat factor partly because
`/stable/analyst-estimates` returned **402** for 26 of 30 SOXX constituents:
`"This value set for 'symbol' is not available under your current subscription"`. The
open question was whether that gate is

- **(a) account-wide on the symbol** — the name is outside our tier's universe, so it
  fails on *every* endpoint; or
- **(b) per-endpoint** — the name is fine generally, but analyst estimates are a gated
  product.

(a) means Starter's advertised "US Coverage" fixes it. (b) means the gate is a product
tier Starter's feature list never mentions, and buying Starter changes nothing. The two
readings point opposite ways, and the earlier probe never distinguished them because it
only ever called one endpoint.

**It is (a).** Crossing three known-blocked symbols with every endpoint either repo
calls:

```
                    NVDA (whitelisted)   AVGO / MU / AMAT
profile                  200                  200
shares-float             200                  200
income-statement         200                  402
balance-sheet            200                  402
ratios                   200                  402
key-metrics              200                  402
income-stmt (quarter)    200                  402
historical-price-eod     200 (1254 rows)      402
quote                    200                  402
analyst-estimates        200 (10 rows)        402
price-target-summary     200                  402
grades                   200 (1131 rows)      402
earnings                 200                  402
```

AVGO/MU/AMAT fail on **everything symbol-scoped**, not just estimates. Only `profile`
and `shares-float` survive. The restriction is a symbol universe.

The pricing page confirms it outright — the tier matrix encodes coverage as icons whose
alt-text reads, for the Basic column:

> **`Symbol Limited to AAPL, TSLA, AMZN and 84 more`**

**The free tier is an 87-symbol sample.** That single fact explains every 402 in the NTM
work, and it means the earlier finding — "the blocked names are systematically the
high-multiple semis cohort" — was reading a *sampling artifact* as a sector pattern. The
87 names skew mega-cap, so what looked like semis being singled out was just SOXX being
mostly non-mega-cap. The conclusion that the residual was biased still holds; the
proposed mechanism was wrong.

## Three distinct 402 classes

Worth separating, because only the first is coverage:

| Error text | Count | Meaning | Fixed by |
|---|---|---|---|
| `Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is not available…` | 33 | Symbol outside the 87-name sample | **Starter (US coverage)** |
| `Restricted Endpoint: This endpoint is not available under your current subscription` | 15 | Endpoint not in the tier at all | Depends on the endpoint's tier |
| `Premium Query Parameter: 'Special Parameters : The values for 'limit' must be between 0 and 5…` | 1 | Parameter ceiling | Higher tier |

Endpoint-restricted on the current key, *even for whitelisted NVDA*:
`news/stock`, `etf/holdings`, `institutional-ownership/*`, `sp500-constituent`,
`nasdaq-constituent`, `company-screener`.

## Published tier ladder

Verbatim from the pricing page (prices are the billed-annually rate):

| Tier | Price | Rate | History | Coverage | Notable additions |
|---|---|---|---|---|---|
| Basic | **Free** | 250 / **day** | End-of-day | **87-symbol sample** | 150+ endpoints |
| **Starter** | **$22/mo** | 300 / **min** | Up to 5y | **US** | Annual fundamentals + ratios, historical prices, profile + reference, **financial news**, crypto + forex |
| Premium | $59/mo | 750 / min | Up to 30y | +UK, Canada | **Full** fundamentals + ratios, intraday charts, technical indicators, corporate calendars, DCF |
| Ultimate | $149/mo | 3,000 / min | Full | Global | Earnings-call transcripts, **ETF & mutual-fund holdings**, **13F**, 1-min intraday, bulk/batch |

The page also carries a per-endpoint × tier grid. It is **not** cited here: extracted to
markdown, its sparse cells collapse and the column counts come out inconsistent (3, 4, 1
and 2 columns for different sections, with the News block reading all-empty while Starter
explicitly advertises news). The legend is reliable; the row alignment is not.

## What Starter buys

**1. The symbol universe — 87 names to all US exchanges.** This is the whole ballgame.
Every symbol-scoped endpoint is currently unusable for anything but a mega-cap handful.

**2. Rate: 250/day → 300/min.** On a per-day basis that is a ~1,700× increase. It
collapses the NTM refresh design from a 3-day rotation over 599 constituents to a single
~2-minute run, and it removes the quota arithmetic from every future FMP decision.
*Caveat: the bullets advertise only a per-minute figure; whether Starter also carries a
daily cap is not stated and I could not verify it.*

**3. Financial news endpoints**, currently 402 Restricted.

## What Starter does not buy

| Need | Requires | Cost |
|---|---|---|
| ETF & fund holdings (the SMH/MAGS gap, defect #4) | **Ultimate** | $149/mo |
| 13F / institutional ownership | **Ultimate** | $149/mo |
| History beyond 5 years | Premium | $59/mo |
| "Full" (vs annual) fundamentals | Premium | $59/mo |

And two things **no** tier fixes:

- **Issue #302 blocker ②** — estimates arrive in issuer reporting currency with no
  currency field among the 22 returned (TSM: TWD EPS 323.34 against a USD ADR → P/E
  0.65). A schema gap, not an entitlement.
- **Issue #302 blocker ③** — point-in-time estimate history. FMP returns the *current*
  estimate per period at every tier. This is an I/B/E/S / Refinitiv / FactSet product
  and is not on FMP's menu at any price.

**So Starter clears 1 of the 3 NTM blockers** — the buyable one. The factor stays dead
on ② and ③, independent of spend, and dead again on the empirical finding in
`2026-07-26-sector-crowding-lifecycle.md`.

## The actual reason to buy: apex is silently degraded

argon does not use FMP in production at all — no `FMP_*` config, no fetcher; the key
lives in `apex/config/secrets.yaml` and only research scripts here touch it.

apex uses it as a **primary** source:

```
apex/config/base.yaml:288        source_priority: ["fmp", "yahoo"]
apex/config/momentum_screener.yaml:11   source: "fmp"
apex/config/pead_screener.yaml:5        primary: "fmp"
```

Note the fallback is **Yahoo**, which argon bans outright and CI enforces.

`src/infrastructure/adapters/fmp/index_constituents.py` already anticipates 402s — its
docstrings say constituent endpoints "return 402 on FMP Starter plans" and fall back to
`company-screener`. On the current key **that fallback is also 402**:

```
sp500-constituent    402 Restricted
nasdaq-constituent   402 Restricted
company-screener     402 Restricted
```

`_fmp_get` turns every 402 into `logger.warning(...)` + `return []`, never an exception.
So `fetch_universe()` walks:

```
fetch_sp500()      -> 402 -> []
fetch_nasdaq()     -> 402 -> []
constituent_count == 0  -> fetch_us_stocks() -> company-screener -> 402 -> []
russell_proxy      -> company-screener -> 402 -> []
=> returns [] , silently
```

**apex's momentum universe resolves to zero symbols on the current key, and degrades to
a log warning.** `momentum_screener.yaml` has `enabled: true`; whether the runner is on a
schedule (vs invoked by hand) I did not verify, so treat "currently running broken" as
unconfirmed and "would return nothing if run" as confirmed.

This is a correctness argument rather than a feature wish, and it is the strongest one in
the file.

## Recommendation

**Buy Starter if apex's momentum / PEAD screeners are meant to work — it is the cheapest
fix for a silent-empty universe, and $264/yr is not worth deliberating over.** Do not buy
it expecting to revive the NTM P/E factor; that needs ② and ③, which no tier sells.

Verify immediately after purchase, since three things are genuinely uncertain and one
contradicts apex's own comments:

1. `sp500-constituent` / `nasdaq-constituent` — apex's docstrings claim these stay 402 on
   Starter. If true, the constituent path still needs the screener fallback to work.
2. `company-screener` — the fallback's own dependency.
3. Whether Starter carries a daily cap alongside the 300/min.

Re-run `scripts/research/fmp_tier_probe.py` on the new key; the rollup section prints the
gated pairs directly, so the before/after diff is the whole verification.

If the answer is instead "apex's FMP paths are dormant," then **skip it** — nothing in
argon needs FMP today, and the NTM factor it was meant to unlock is blocked for reasons
money cannot reach.
