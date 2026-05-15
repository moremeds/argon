# Dimension 02 — Charm (重力 · "Gravity")

> "Charm 是重力。OPEX 那天 max-OI strike 像磁铁。"

**Role in the matrix**: very short-horizon (1–5 days) path indicator. Reads the *magnet pull* of large open-interest concentrations as expiry approaches.

---

## 1. Definition

### Formal

$$\text{Charm} \;=\; -\frac{\partial \Delta}{\partial t} \;=\; \frac{\partial \Delta}{\partial \tau} \;=\; -\frac{\partial^2 V}{\partial S \,\partial t}$$

For a European call under Black–Scholes (zero rates / dividends, time-to-expiry τ):

$$\text{Charm}_{BS} \;=\; -\frac{\phi(d_1)\,d_2}{2\,\tau}$$

(The full Black-Scholes charm formula with non-zero rates and dividends includes additional `q · e^{−qT} · N(d1)` and `(r−q)`-dependent terms; the simplified form above is the one used in the framework's intuition.)

Sign convention varies — some references quote charm as `+∂Δ/∂t` (delta decay per unit *forward* time) and some as `−∂Δ/∂t` (delta decay per unit *τ*-shrinkage). The framework reads charm as **the rate at which Δ collapses as expiry approaches**, treating "magnitude of charm flow" as the actionable quantity.

### Intuition

For ATM options, charm magnitude **accelerates** as τ → 0 — the Δ of a near-expiry ATM option swings violently from 50% to 0% or 100% in the final session. For deep-OTM options, charm **decelerates** — Δ has already collapsed to ~0 and there is nothing left to decay.

The framework's "gravity" metaphor: large-OI strikes near spot become *magnetic* in the final days because the *aggregate* charm of dealer-hedged positions creates a self-reinforcing drift toward the strike. This is the formal mechanism for OPEX pinning.

---

## 2. The framework's reading (slide IMG_4619 — left column)

| Trigger | Reading |
|---|---|
| T-2 → T-0, large OI clustered near spot | **Pin** — spot pulled toward max-OI strike |
| Far-month large OI | **Negligible** effect on near-term path (don't confuse cross-expiry OI for current-week magnet) |
| Monday open + accumulated weekend theta | Charm-driven gap effect at re-open (weekend Δ-decay realized at 09:30 Monday) |
| Common misread | "Far-month OI = magnet" — **noise ≫ signal** at non-near expiries |

**Role in the matrix**: 1–5 day path indicator — not a primary decision driver, but a **pin-vs-no-pin classifier** at expiry, and a near-term Δ-flow generator for Monday opens.

---

## 3. Academic and practitioner literature

### Canonical OPEX pinning paper

> **Ni, S. X., Pearson, N. D. & Poteshman, A. M. (2005)** — *Stock Price Clustering on Option Expiration Dates* — Journal of Financial Economics 78(1): 49–87.

The seminal empirical paper. Quote: "on each expiration date, the returns of optionable stocks are altered by an average of at least 16.5 basis points" (Abstract; Tables 2–3). Identifies the mechanism as delta-hedging-induced clustering and shows the effect is concentrated near max-OI strikes — direct evidence for the framework's "max-OI strike = magnet" reading.

URL: https://www.sciencedirect.com/science/article/abs/pii/S0304405X05000577

### The pinning SDE — analytical derivation

> **Avellaneda, M. & Lipkin, M. D. (2003)** — *A Market-Induced Mechanism for Stock Pinning* — Quantitative Finance 3(6): 417–425.

The canonical analytical proof. Derives a stochastic differential equation with a singular drift that produces pinning, driven by aggregate dealer delta-hedging demand. Quote: "delta-hedging in aggregate by floor market-makers can impact the stock price and drive it to the strike price of the option" (§2, model setup).

URL: https://math.nyu.edu/inmemoriam/avellaneda//qf3601.pdf

This is the theoretical sister to Ni-Pearson-Poteshman's empirical work and the formal mathematical basis for the "Charm = gravity" metaphor: a singular drift toward a strike is — *literally* — gravity.

### Intraday charm — closing-hour delta rebalancing

> **Baltussen, G., Da, Z., Lammers, S. & Martens, M. (2021)** — *Hedging Demand and Market Intraday Momentum* — Journal of Financial Economics 142(1): 377–403.

Documents end-of-day return continuation driven by *charm-style* delta-rebalancing in the closing hour, across 60+ futures markets. Quote: "the return during the last 30 minutes before the market close is positively predicted by the return during the rest of the day" (§3, main result).

URL: https://www3.nd.edu/~zda/intramom.pdf

Relevance to the framework's "Monday open + weekend theta" reading: Baltussen et al. is the intraday analog of the daily/weekend charm-accumulation effect. The same delta-rebalancing pressure that creates last-30-min momentum creates Monday-open gaps for index ETFs.

### Textbook reference

> **Natenberg, S. (2015)** — *Option Volatility & Pricing: Advanced Trading Strategies and Techniques*, 2nd ed., McGraw-Hill. ISBN 978-0071818773.

Practitioner-standard. Chapter 9 ("Risk Measurement II") and the Greek-sensitivities appendix cover charm/color/speed. The framework's two main facts — ATM delta-decay accelerates near expiry; far-OTM delta-decay decelerates — are textbook results; Natenberg presents the geometric intuition.

### Practitioner sources

> **SqueezeMetrics (2017)** — *The Implied Order Book* / GEX whitepaper. https://squeezemetrics.com/monitor/download/pdf/white_paper.pdf

Practitioner; not peer-reviewed. Useful for desk-level OPEX commentary; "GEX" is a related (gamma) construct that the framework treats as substrate beneath both charm and vanna.

> **Marko Kolanovic (JPM) / Charlie McElligott (Nomura) OPEX flow notes** — circulated via financial press. **Not citeable academically** (no stable archival URL). Useful for triangulation but not for primary citation.

### 0DTE caveat — pinning regime change

> **Dim, C., Eraker, B. & Vilkov, G. (2024)** — *0DTEs: Trading, Gamma Risk and Volatility Propagation* — SSRN working paper. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190

> **Brogaard, J., Han, J. & Won, P. Y. (2024)** — *Does 0DTE Options Trading Increase Volatility?* — SSRN working paper. https://papers.ssrn.com/sol3/Papers.cfm?abstract_id=4426358

Recent academic treatment of 0DTE dealer-gamma dynamics. Relevant to the framework's Limitation #7 ("0DTE intraday hijacking" — see [`07-limitations.md`](07-limitations.md)). In a 0DTE-heavy regime, *intraday* charm dynamics may overwhelm weekly OPEX pinning — the magnet metaphor still holds, but the magnet *moves* during the session.

---

## 4. Single-dimension misreadings (from slide IMG_4619)

> "误读: 远月 OI 当近期 magnet (噪音 ≫ 信号)"

**Named misreading**: reading far-month large OI as a near-term magnet. Far-month OI has near-zero charm-per-day; only OI within the operative time window (1–5 days) carries actionable magnetic pull.

**Two further failure modes** the framework names:
1. Charm in high-vol regimes is **dominated by vol-driven path** — gamma + vol > charm. Scenario C ("all instruments red") explicitly notes "high-vol 状态 vol-driven 路径压住 magnet · 几乎失效" — the pin breaks under stress.
2. Charm + Vanna in **opposite directions** ≠ grind-up. The framework reads Scenario B post-event grind-up as requiring "Vanna + Charm 同方向时 grind 才立得住" — both must agree.

---

## 5. Single-name caveats

1. **OI density**. Single-name option chains have far lower OI per strike than SPX. The Ni–Pearson–Poteshman 16.5bp average effect was estimated across thousands of single-names — *individual* names with very high OI (typically liquid mega-caps near OPEX) can produce much larger pin effects, while low-OI names produce essentially none.
2. **Earnings overrides**. A near-expiry single-name with an upcoming earnings release ignores OPEX magnets in favor of the binary-event mechanic — see [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md).
3. **Multi-leg trade artifacts**. Per Savickas-Wilson (2003) — see [`05-implied-move-and-flow.md`](05-implied-move-and-flow.md) on aggressor classification — multi-leg trades on single-names disproportionately corrupt charm-flow attribution. UW's intent labels are noisier on illiquid names.

---

## 6. Mapping to current `uw_scan` data

### What we have

| Layer | Status | Location |
|---|---|---|
| UW endpoint | ✅ | `/api/stock/{T}/greeks` (per-contract), `/api/stock/{T}/greek-exposure/strike-expiry` (aggregated), `/api/stock/{T}/oi-per-strike` (OI distribution), `/api/stock/{T}/oi-change` (OI delta) |
| Fetcher | ✅ | `fetch_greeks`, `fetch_greek_exposure`, `fetch_oi_per_strike`, `fetch_oi_change` (src/uw_scan/sources/uw.py) |
| Persistence | ✅ | `greeks_by_expiry_strike.call_charm/put_charm` (per-contract), `exposures_by_expiry_strike.call_charm/put_charm` (aggregate), `oi_per_strike_history` (OI distribution), `oi_changes` (deltas) |

### What's missing

| Layer | Gap | Effort |
|---|---|---|
| Repository reads | No `fetch_charm_*_for_ticker` | small |
| Pin classifier | No "is there a pin candidate this expiry" derivation. Needs: top-OI strike(s), distance from spot in σ-units, charm magnitude. | small–medium |
| Magnet-strike picker | The framework's "max-OI strike → magnet" requires identifying the *operative* OI cluster within τ ≤ 5d windows, not far-month. | small |
| Stress detector | "High-vol regime breaks charm pin" requires a regime classifier (cross-reference with [`04-term-structure.md`](04-term-structure.md)) | medium |
| API + UI | Nothing surfaces charm | small (after repo + derivation) |
| AI report blacklist | `reports/trade_insights_ai.py:965` rejects `"charm"` in `source_path` — **stays in place** for stock-detail AI; charm surfaces via separate `reports/cockpit_ai.py` (indexes only) | n/a |

Full implementation plan in [`08-implementation-gaps.md`](08-implementation-gaps.md).

---

## 7. Concrete derivations the matrix needs

| Metric | Formula | Lookup window | Purpose |
|---|---|---|---|
| `pin_candidate_strike` | argmax over strikes (call_oi + put_oi) within τ ≤ 5d expiries | next 1-week expiries | Identifies the magnet |
| `pin_distance_sigma` | (spot − pin_candidate_strike) / (spot × IV_30d × √(τ/365)) | t | Distance to pin, σ-normalized |
| `dealer_net_charm_proxy` | Σ over strikes of (call_charm × call_oi − put_charm × put_oi) × shares-per-contract | t (near-month only, τ ≤ 5d) | Sign + magnitude of dealer charm pressure |
| `pin_regime_flag` | (IV_30d < median(IV_30d, 90d)) AND (\|pin_distance_sigma\| < 1.0) AND (τ ≤ 5d) | rolling | TRUE only when the pin is operative; FALSE in high-vol regimes per Scenario C |

These metrics feed the *very short-horizon* layer of the decision tree's Step 3 (time-window check), and the Scenario B post-event grind-up requires `dealer_net_charm_proxy` × `dealer_net_vanna_proxy` to be same-sign (Vanna+Charm consistency check).

---

## 8. Cross-references

- Vanna — sibling cross-greek; same dealer-hedging machinery — [`01-vanna.md`](01-vanna.md)
- OI per strike + changes — substrate for pin classifier — see [`08-implementation-gaps.md`](08-implementation-gaps.md)
- Scenario B (post-event vol crush requires Vanna+Charm same-direction) — [`00-overview.md`](00-overview.md)
- Scenario C (high-vol regime breaks the pin) — [`00-overview.md`](00-overview.md)
- Limitation #7 (0DTE intraday hijacking) — directly affects the magnet's stability — [`07-limitations.md`](07-limitations.md)
