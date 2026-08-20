# What the valuation band refuses, and why — 2026-08-19

Read-only probe of `uw_scan.valuation_anchors` on the mini (`option_wizard`) at
`as_of = 2026-08-17`, the first full panel after the universe widening.

Reproduce (from a worktree, over Tailscale, read-only):

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
UW_SCAN_ALLOW_DB_MISMATCH=1 UW_SCAN_DB_USER=argon_app \
UW_SCAN_DB_PASSWORD=<from /opt/argon/.env on the mini> \
  uv run python docs/research/2026-08-19-valuation-refusal-anatomy/refusal_probe.py
```

`refusal_probe.py` (families) · `refusal_names.py` (members) ·
`financials_check.py` (the finding below) · `ctype_dist.py` (routing shape).

## Headline

`423` rows, `342` usable bands, `81` refusals — **19.1%**.

| binding refusal reason | n |
|---|---:|
| own range too wide (regime change) | 35 |
| net-debt band collapse ("no price at this net debt") | 15 |
| statements in a non-USD currency, no FX series | 12 |
| under 12 usable quarters | 12 |
| non-positive numerator | 6 |
| non-positive EV | 1 |

## The finding: `unclassified` is not a residual bucket, and its default is not neutral

`unclassified` is **317 of 423 names (75%)** — 279 banded, 38 refused. Every one
routes to `sales_to_ev` by the default at `fundamentals/valuation.py:116`.

`worker/jobs/fundamental_anchors.py:230` already records that Banks land here,
and argues the default beats inventing a type. What was not measured until now is
that for **deposit-funded financials the default's outcome is arbitrary**:

| banded, `medium` confidence | refused |
|---|---|
| AXP, BLK, COF, MS, SOFI | BAC, GS, JPM, WFC, HOOD, FLG |

Same business model, both outcomes, decided by which side of a numeric guard the
name lands on. The mechanism is in the refusal string itself — *"the cheap end of
the band has no price at this net debt"*. The band solves
`price = (EV_target - net_debt) / shares`; for a bank `net_debt` is the raw
material (deposits, repo, funding), not a claim on operating assets, so it swamps
EV. Revenue/EV is then not a cheapness measure, and inverting it for a price
either explodes or lands somewhere unfalsifiable.

The pooled 2026-08-12 result that licensed the default (`sales_to_ev` best over
247 tickers) is a **mean over a set that contains these names**. It can be
positive overall while being meaningless on the subset — the pooling never
partitioned by whether EV is a coherent denominator.

**A `medium`-confidence band on AXP/BLK/COF/MS/SOFI is currently rendered.** None
sit inside their buy zone as of 2026-08-17 (AXP 336.21 vs 268.92; MS 218.21 vs
151.51; COF 221.45 vs 161.69; BLK 1147.11 vs 926.52; SOFI 18.31 vs 16.43), so
nothing wrong is on the Value tab today — but nothing prevents it tomorrow.

## Second class: FX

12 names refuse solely because no USD/XXX series exists — and they are not a
tail: **ASML, ASX, BABA, CCEP, CCJ, NOK, NVO, SONY, SPOT, TSM, UMC, WIT**
(EUR 4, TWD 3, CNY/CAD/DKK/JPY/INR 1 each). This is the ADR currency-mismatch
guard doing its job; the guard is correct, the missing input is a rate series.

## Third class: time, not work

12 names are under the 12-quarter floor (CRCL 3q, BMNR 5q, GLXY 5q, CRWV 6q,
FLY/SNDK 7q, FIG/TEM/TLN 9q, GEV/ALAB/RDDT 10q). Recent listings. The monthly
ingest resolves these without code.

## Not a bug

The 35 "range too wide" refusals are the guard working (ASTS 176.7x, NRG 150.4x,
NBIS 72.3x, RGTI 46.2x; median 6.4x against a 4x limit). Hypergrowth and
turnarounds genuinely have no single valuation regime across 20 quarters.

## What the fix does, measured before shipping

`routing_dryrun.py`, read-only against the mini, importing the real routing maps
rather than re-implementing the precedence:

```
universe=450  would change=9  -> financials=9
any OTHER routing change: 0
```

Eight names flip from `unclassified` to `financials` on the chain taxonomy alone
(BAC, BLK, GS, HOOD, JPM, MS, SOFI, WFC). One more moves, PYPL, and it moves the
other way — see below. **Nothing else moves at all**, which is the invariant that
keeps this a bank fix rather than a re-rating of the panel wearing a bank fix's
name.

AXP, COF and FLG carry no watchlist row, so no chain rule reaches them. UW
reports `Financial Services` for all three (verified 2026-08-19), so the monthly
`company_sector_refresh` picks them up.

### PYPL: the cost, and why it turned out not to be one

**PYPL was inside its buy zone** (spot 60.47 against `buy_below` 75.74) and
leaves the Value tab. `Fintech` is a heterogeneous chain label — HOOD is a
broker, SOFI a lender, PYPL a payment processor — and the vendor vocabulary is no
finer, calling all three `Financial Services`.

No asset-light allow-list was invented to save it. PayPal holds custodial
customer balances and runs a BNPL/credit book, so "its EV yield is obviously
coherent" is not a claim this repo can measure, and forcing a name into a type on
a guess is the exact failure mode the routing comments already warn about.

**Resolved 2026-08-19 by a different route, after the question was put again.**
The framing above assumes the only way out is an exemption from the refusal. It
is not. Every method that breaks for a financial is EV-denominated; `fcf_yield`
divides by market cap and never reads `net_debt` (`EV_DENOMINATED` names exactly
two methods, and `fcf_yield` is not one of them). So a name routed to
`platform_scale` is priced by something the refusal never covered — no exemption
required, and PayPal's custodial balances stay irrelevant to its band because
they were never in the denominator.

Measured on the mini against the deployed engine (`pypl_route_probe.py`):

| routing | method | history | confidence | buy_below | caveats |
|---|---|---|---|---|---|
| `unclassified` (before) | sales_to_ev | 45q | medium | 75.74 | "no sector on file … pooled default" |
| `platform_scale` (now) | **fcf_yield** | 45q | **high** | **79.40** | none |

Spot 60.43 as of 2026-08-18, inside the zone under both. **0 of the trailing 20
quarters carry non-positive TTM free cash flow** — the constraint that left
TSLA's band with three of five levels missing, and the one that would have made
this route unusable. So the resolution is not a rescue of the status quo: PYPL's
band is better-founded after this change than before it.

What is *not* claimed: that `fcf_yield` was validated on PYPL specifically. It
was measured pooled (+0.0457, t 3.64). Calling PayPal a platform is a judgement
about the business and is recorded as one, in `TICKER_TO_TYPE`.

The escape is deliberately narrow. A unit test asserts every `TICKER_TO_TYPE`
entry routes to a market-cap-denominated method; an entry pointing at an
EV-denominated type would look every bit as deliberate while its entire
justification had quietly evaporated — this bug, re-created one ticker at a time.
The override writes `source='seeded'`, so `assign(source="manual")` still
overrules it.
