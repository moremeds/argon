# Dimension 01 — Vanna (风 · "Wind")

> "Vanna 是风。风往哪吹由之前 flow 颜色决定。"

**Role in the matrix**: short-horizon (1–3 days) path indicator. Reads the dealer's *next forced action* when IV changes, conditional on the dealer's existing inventory.

---

## 1. Definition

### Formal

$$\text{Vanna} \;=\; \frac{\partial \Delta}{\partial \sigma} \;=\; \frac{\partial^2 V}{\partial S\,\partial \sigma} \;=\; \frac{\partial \mathcal{V}}{\partial S}$$

For a European call under Black–Scholes:

$$\text{Vanna}_{BS} \;=\; -e^{-qT}\,\phi(d_1)\,\frac{d_2}{\sigma}$$

The sign is symmetric in calls and puts: for both, vanna ≈ 0 near ATM (where `d2 ≈ 0`), is **positive** for OTM strikes (where `d2 < 0` gives `−d2 > 0`), and approaches zero again at deep OTM (where `φ(d1)` becomes vanishingly small). Magnitude peaks at moderately OTM strikes — the regime where `φ(d1) · d2` is largest in absolute value.

### Intuition

Vanna says: *"when implied vol moves, how much does my hedge ratio Δ have to move?"* For a dealer running a book, the *aggregate* vanna over the book tells them how much spot they have to buy or sell when IV moves a percentage point.

The framework's "wind" metaphor: vanna determines the *direction the dealer must lean* when vol changes — it doesn't blow on its own, it is set in motion by the IV move and steered by the existing book.

---

## 2. The framework's 4 conditional readings (slide IMG_4618)

Vanna in isolation is **not** a signal. The framework prescribes four conditional readings that combine **(a) IV direction, (b) prior flow color, (c) dealer net-gamma sign**:

| # | Trigger | Reading | Path |
|---|---|---|---|
| 1 | IV↓ + prior put-heavy hedge flow + dealer pre-sold to hedge | Dealer must repurchase stock as IV crush reduces |Δ| of puts | **Grind up** |
| 2 | IV↓ + prior upside call chase + dealer pre-bought to hedge | Dealer must sell long stock as IV crush reduces |Δ| of calls | **Reverse sell-off** |
| 3 | IV↑ + spot↓ + dealer net short gamma | Increasing vol expands |Δ| of OTM puts dealer is short → dealer must sell more stock | **Self-reinforcing sell pressure (reflexivity)** |
| 4 | IV minor jitter + spot range-bound | Vanna signal too weak; **do not use as primary driver** | (do nothing) |

**Author's stance**: "Don't read every IV decline as a dealer-induced grind-up — that's the most common mistake." Three conditions must align simultaneously for vanna to have actionable meaning: (i) net gamma sign, (ii) put-vs-call flow color, (iii) whether dealer has already pre-hedged.

---

## 3. Academic and practitioner literature

### Origin of the term — FX vol-surface fitting

Vanna entered the vol literature through FX market-making, where the smile is parameterized by three pillar greeks: vega (level), vanna (skew), volga (curvature). Castagna and Mercurio (2007) is the canonical reference.

> **Castagna, A. & Mercurio, F. (2007)** — *The Vanna-Volga Method for Implied Volatilities* — Risk Magazine (January 2007). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=873788

The vanna-volga construction "determines portfolio weights by equating the vega, vanna and volga of the target option and the portfolio of the three pillar options" (§3). This is the source of the "vanna flow" terminology now ubiquitous in equity options discourse.

### Cross-asset extension — currency options stochastic skew

> **Carr, P. & Wu, L. (2007)** — *Stochastic Skew in Currency Options* — Journal of Financial Economics 86(1): 213–247.

Empirically decomposes vega/vanna/volga risk in FX. Establishes that dealer cross-greek hedging demand is a measurable driver of price dynamics when the skew shifts — the theoretical antecedent of equity-index vanna-flow analysis.

### The mechanism: demand-based pricing

The dealer-as-residual-buyer mechanism that makes vanna a path indicator is formalized in:

> **Gârleanu, N., Pedersen, L. H. & Poteshman, A. M. (2009)** — *Demand-Based Option Pricing* — Review of Financial Studies 22(10): 4259–4299. DOI: 10.1093/rfs/hhp005

Key result: "demand pressure in one option contract increases its price by an amount proportional to the variance of the unhedgeable part of the position" (Proposition 1). Translated to vanna: **dealer book vanna becomes path-relevant precisely when the dealer cannot perfectly delta-hedge** — which is most of the time for index options carrying non-trivial gamma.

This gives the framework's conditional-reading rules their theoretical grounding: vanna only matters when the dealer is *forced* to move spot, and forcing requires (i) inventory + (ii) imperfect hedging.

### Volatility-information flow

> **Ni, S. X., Pan, J. & Poteshman, A. M. (2008)** — *Volatility Information Trading in the Option Market* — Journal of Finance 63(3): 1059–1091.

Non-market-maker net vol demand predicts subsequent realized vol — the cleanest empirical link from dealer-side residual position (the receptor of vanna flow) to spot/vol dynamics. Quote: "price impact increases by 40% as informational asymmetry about stock volatility intensifies in the days leading up to earnings announcements" (Abstract; §V).

This paper underwrites the framework's *time-window* assignment of vanna to "1–3 day path indicator" — that's the horizon at which vol-information-driven dealer rebalancing has been shown empirically to translate to price.

### Intraday gamma fragility

> **Barbon, A. & Buraschi, A. (2021)** — *Gamma Fragility* — SSRN working paper (March 2021). https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3725454

Direct empirical test of the dealer-gamma regime predicting intraday momentum (short gamma) vs reversal (long gamma) at the index level. Quote: "intra-day momentum (reversal) is explained by the interaction of negative (positive) ex-ante gamma imbalance and illiquidity" (Abstract; §4).

Relevance to vanna: gamma and vanna are second-order siblings — same dealer-hedging machinery, different trigger (Δ-of-vol vs Δ-of-spot). The Barbon-Buraschi result is the closest empirical analog to a "vanna fragility" test and supports the framework's reflexivity claim in conditional reading #3.

### Practitioner sources

> **SqueezeMetrics (2017)** — *The Implied Order Book* / GEX whitepaper. https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf

Practitioner; not peer-reviewed. Frames dealer net-gamma and vanna as drivers of post-event spot drift. Useful for desk-level vocabulary and as a public reference point for industry consensus. Cite with disclosure that it is a vendor-published note.

> **Charlie McElligott (Nomura) / Marko Kolanovic (JPM) dealer notes** — circulated via Bloomberg, ZeroHedge, etc. **Not citeable academically** — no stable archival URLs.

### Textbook reference

> **Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018)** — *Trades, Quotes and Prices: Financial Markets Under the Microscope* — Cambridge University Press. Parts V (Price Impact) and VII (Adverse Selection and Liquidity Provision).

For the microstructure foundation underlying all dealer-flow narratives — including the role of vanna as a second-order cross-greek that shifts dealer inventory at non-trivial speeds.

---

## 4. Single-dimension misreadings (from slide IMG_4618)

> "把任何 IV 下降都解读成 dealer-induced grind up · 错。"

The framework's named misreading: reading *every* IV decline as a vanna-driven dealer grind-up. The exceptions are conditional reading #2 (call-heavy pre-event) and conditional reading #4 (range-bound noise).

**Three conditions must align for vanna to be tradable**:
1. Net gamma sign (positive vs negative)
2. Put / call flow color (which side dealer pre-hedged)
3. Whether the dealer has already pre-hedged or is still building inventory

If any of the three is ambiguous → vanna signal is too weak; **do not use as the primary decision driver**.

---

## 5. Single-name caveats

The matrix's primary context (Limitation #4 — see [`07-limitations.md`](07-limitations.md)) is SPX / SPY / QQQ. Single-name vanna deviates from index vanna in three ways:

1. **Lower OI density and dealer concentration**. Single-name vanna books are often *one or two* dealers' positions, not a market-wide aggregate. Idiosyncratic dealer behavior dominates.
2. **Different skew regime**. Per Bakshi-Kapadia-Madan (2003 RFS — see [`03-skew.md`](03-skew.md)), single-name risk-neutral distributions are *far less negatively skewed* than the index's. Vanna concentration peaks at different strikes.
3. **Earnings discontinuities**. The IV-crush mechanism vanna trades on collapses to a discrete event: pre-earnings IV expansion is reversed at open the next morning, regardless of dealer inventory — the framework's "post-event" reading #1 / #2 is *amplified*, but the mechanism is largely jump-driven rather than smoothly-hedged.

---

## 6. Mapping to current `uw_scan` data

### What we have

| Layer | Status | Location |
|---|---|---|
| UW endpoint | ✅ | `/api/stock/{T}/greeks` (per-contract), `/api/stock/{T}/greek-exposure/strike-expiry` (aggregated), `/api/stock/{T}/spot-exposures/expiry-strike` (intent-split) |
| Fetcher | ✅ | `fetch_greeks` (src/uw_scan/sources/uw.py:206), `fetch_greek_exposure` (uw.py:170), `fetch_spot_exposures` (uw.py:188) |
| Persistence | ✅ | `greeks_by_expiry_strike.call_vanna/put_vanna` (per-contract), `exposures_by_expiry_strike.call_vanna/put_vanna` (GEX-style aggregate). Intent-split (`call_vanna_ask`/`call_vanna_oi`/etc.) is **dropped** at `pipeline.py:144` — raw payload still in `uw_scan.raw_payloads`. |

### What's missing

| Layer | Gap | Effort |
|---|---|---|
| Repository read methods | No `fetch_vanna_*_for_ticker` exists | small |
| Report assembler | Nothing reads vanna columns | small–medium |
| API router | `/stock/{T}` returns nothing vanna-related | small |
| Conditional-reading classifier | The four conditional readings from the framework require joining vanna with: (a) recent flow color from `flow_alerts`, (b) net-gamma sign from `exposures_by_expiry_strike.call_gex/put_gex`, (c) IV direction from `interpolated_iv` time series | medium |
| AI report blacklist | `reports/trade_insights_ai.py:965` rejects `"vanna"` in `source_path` references — **stays in place** for stock-detail AI; vanna surfaces via separate `reports/cockpit_ai.py` (indexes only) | n/a |
| Intent-split (ask/bid/vol/oi) | Currently in `raw_payloads` JSONB only; would need typed table to surface flow-conditional vanna | medium |

Full implementation plan in [`08-implementation-gaps.md`](08-implementation-gaps.md). Build-out sequence proposed in [`09-backtest-plan.md`](09-backtest-plan.md).

---

## 7. Concrete derivations the matrix needs

To support the framework's conditional readings, three derived metrics must be computed and persisted:

| Metric | Formula | Lookup window | Purpose |
|---|---|---|---|
| `dealer_net_vanna_proxy` | Σ over strikes of (call_vanna × call_oi − put_vanna × put_oi) × shares-per-contract | t (current) | Sign + magnitude of dealer book vanna |
| `flow_color_lookback_3d` | sgn(Σ put-side premium − Σ call-side premium) over last 3 trading days | t−3d → t | Prior flow color (drives conditional reading) |
| `iv_30d_delta_5d` | IV_atm_30d(t) − IV_atm_30d(t−5d) | 5d | IV direction with sufficient lag for vanna response |

Optional but powerful (requires intent-split recovery from `raw_payloads`):

| Metric | Formula | Purpose |
|---|---|---|
| `vanna_intent_imbalance` | (call_vanna_ask − call_vanna_bid) − (put_vanna_ask − put_vanna_bid), summed across strikes | Distinguishes dealer-buying-vanna vs dealer-selling-vanna in real time |

These metrics feed Step 1 (consistency check) of the decision tree.

---

## 8. Cross-references

- Charm (∂Δ/∂t) — sibling dealer-hedging greek — [`02-charm.md`](02-charm.md)
- Dealer-net-gamma regime — foundation for vanna conditional readings — see [`02-charm.md`](02-charm.md) and [`08-implementation-gaps.md`](08-implementation-gaps.md)
- Flow color identification — [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md)
- Limitation #1 (collinearity with skew/VRP/term via IV) — [`07-limitations.md`](07-limitations.md)
- Limitation #6 ("you are not the dealer") — most binding for vanna trades — [`07-limitations.md`](07-limitations.md)
