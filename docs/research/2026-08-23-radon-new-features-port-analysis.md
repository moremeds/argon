# Radon's new features (2026-07-01 → 2026-08-22) — alpha read and argon port shortlist

**Date:** 2026-08-23
**Source repo:** `/Users/chenxi/projects/radon` @ `c0e7e4f5` (read-only recon, nothing modified)
**Target:** argon @ `0e1f5d44` (v0.12.11)
**Supersedes/extends:** `docs/research/2026-07-28-radon-scanner-port-backlog.md` — that doc covered radon's four *scanner* tabs; this one covers the ~8 weeks of work radon has shipped since.
**Method:** `git log --since=2026-06-01` feature commits, `docs/indicators/*.md` (12 owner specs), `scripts/clients/`, `docs/operations.md`, `.claude/skills/`. No DB reads, no provider calls.

---

## 1. What radon actually shipped

### 1.1 The indicator wave — 12 regime tabs in 7 weeks

Radon's `docs/indicators/README.md` is a live registry. Everything below is new since 2026-07-01.

| Tab | What it is | Source | Shipped |
|---|---|---|---|
| **BREADTH** | NYSE advance/decline line | IB generated-index snapshots, StockCharts `$NYAD` fallback, 5-min RTH | 07-02 |
| **MARGIN** | FINRA margin debt, dual-axis | FINRA | 07-03 |
| **RV Ratio** | Asset vs SPY realized-vol regime | derived | 07-20 |
| **BPI** | Bullish Percent Index — Point & Figure signal engine over index constituents | computed | 07-25 |
| **CURVE** | 10Y−2Y spread + live 10Y−3M estimate cell | FRED | 08-03 |
| **SKEW** | UW greeks skew | UW | 08-05 |
| **STRADDLE** | Cboe implied straddle + LIVE intraday cell (SPX tick vs latest close) | Cboe CDN | 08-05 |
| **SKEW2D** | 2-day skew | UW | 08-09 |
| **COR** | **Cboe SPX implied correlation, COR1M/3M/6M/1Y** | Cboe CDN | 08-09 |
| **VOL CONE** | Cheap 10% OTM wing IV scanner, per (ticker, monthly expiry) 90/10 cone + intraday re-rank + order-builder deep link | UW greeks | 08-12→18 |
| **VIXCOR** | VIX vs COR3M, 20-day rolling correlation breakdown | derived from COR | 08-15 |
| **CREDIT** | HYG vs SPX 168-session divergence | HYG/SPX closes | 08-20 |
| **IEI/HYG** | Treasury/HY price ratio, 52-week extremes | IEI/HYG closes | 08-22 |
| **IV RANK** | SPY 30d ATM IV rank over trailing 252 sessions | IB `OPTION_IMPLIED_VOLATILITY`, UW cross-check | 08-22 |
| **TRIN** | NYSE Arms Index, 60-min bars, MA(10) zones | IB + StockCharts | 08-22 |

Plus a grouped indicator rail replacing the flat tab strip (08-16), and a shared UW daily-cap breaker (`scripts/utils/uw_embargo.py`) every UW-backed writer registers against.

### 1.2 New data acquisition

| Thing | Detail |
|---|---|
| **Cboe CDN client** (`scripts/clients/cboe_client.py`, 4.0K) | `cdn.cboe.com/api/global/us_indices/daily_prices/<SYM>_History.csv`, conditional GET → 304. Backs STRADDLE + COR. COR depth **2006-01-03 → present, ~5,181 rows per tenor**, Cboe-backfilled (no ICJ/JCJ/KCJ splice needed) |
| **Equibles client** (29.4K) | Five market-structure feeds on systemd timers: 13F, **ATS venue share**, COT positioning, filing forensics, short crowding |
| **Earnings-date service** | Standalone, feeds every scanner (08-05) |
| **Polymarket client** | Event-odds overlay |
| Knowledge base | 4-phase build: connectors → distillation/embeddings → search endpoints → `radon-kb` MCP server for Claude Code (07-18/19) |

### 1.3 Platform, ops, and the agentic layer

| Thing | Detail |
|---|---|
| **Reliability weekend loop** | Sat delta-audit since last audited SHA → Sun red/green remediation on a PR branch, unattended on an always-on runner |
| **Testing weekend loop** | Same shape for test-suite health |
| **Incident responder** | Auto-triage + human-gated ship; `/incident` playbook; incident watchdog on a 5-min systemd prober |
| **Grok P1 auto-diagnose** | iPhone P1 pages auto-diagnosed; dedicated VPS clone; heartbeat so a stalled auto-fixer itself pages |
| **Kill switch + order limits + order audit trail** | REL-004 trading-halt flag + global cancel-all; REL-005 qty/notional/rate caps; REL-019 `order_events` |
| **`/preferences`** | Operator-tunable runtime limits |
| **Agent UI primitives** | `ApprovalGate` / `AskComposer` / `EngineTrace` / `AnalysisSources` / `TaskRuns` / `ProposalCard` |
| **CMD+J assistant** | Routed through xAI Grok, with live quote / chain / backend tools |
| GIPS daily TWR · catalyst dates + forecast/actual prints · offline mode · collapsible sidebar rail · self-serve systemd unit installs from deploy | |

---

## 2. The alpha read — blunt

**The plumbing is real. The alpha is almost entirely unmeasured.**

Grepping all 12 indicator specs for forward-return / validation-study / backtest content:

| Spec | Validation content |
|---|---|
| `vixcor.md` | **A real study — and it REFUTED the premise.** 5,152 sessions, 31 episodes. Forward VIX drawup after a breakdown is *below* the all-session mean at every horizon; medians indistinguishable (Mann-Whitney p=0.683); VIX-level-matched paired deltas −5.02 to −10.79pp; a 5,000-iteration block permutation says post-event drawup is **significantly LOWER than random** at h=5 (p=0.023) and h=10 (p=0.016). Shipped anyway, with the refutation written into the tab copy |
| `ivrank.md` | Source-validation only (IB vs UW formula cross-check, rank 10.5598 vs 10.58). Spec states outright: *"no validation study was run, so no predictive framing is permitted"* |
| **the other 10** | **zero** |

So COR, VOL CONE, CREDIT, IEI/HYG, TRIN, CURVE, SKEW, SKEW2D, STRADDLE, BREADTH, MARGIN, BPI are **descriptive regime reads**, most of them reconstructed from a chart the operator saw (CREDIT: "the tweet's warning"; IEI/HYG: "the TrendLabs chart 2026-08-21"; TRIN: "the StockCharts chart's red line at 0.60"). The specs are honest about what they compute. None claims measured edge, and none has one.

**This is the opposite of argon's posture** — argon has 10+ documented kills (flow-vs-RV−IV, SVI residual, GEX persistence, GARCH VRP leg, Chanlun Phase-B, within-ticker fundamentals) and exactly one validated edge (VRP macro short-vol). Radon acquires; argon falsifies.

**Consequence for the port: take radon's data, never radon's verdict.** Every candidate below is a *data acquisition* port whose signal claim must go through argon's own falsification before it reaches a surface that implies tradability.

---

## 3. Port shortlist for argon — **corrected 2026-08-23 after checking argon's own kill record**

> **Correction.** A first pass of this doc ranked COR ingestion, VOL CONE and CREDIT as the top
> three ports. All three were wrong, and each was already answered inside argon. The corrected
> table below leads with those checks. The lesson generalises: **check `docs/research/` before
> ranking any radon idea** — the candidate master menu (`2026-07-07-candidate-master-menu.md`)
> is stale and still lists C5 as `GATED` on the same day the falsification landed.

### 3.1 Already tested here — do not port the signal

| Radon feature | Argon's own test | Result |
|---|---|---|
| **COR** (implied correlation) as a gate on the VRP edge | `2026-07-07-implied-corr-gate.md` (#226), n=244 non-overlapping trades, 2007→2026 | **NEGATIVE.** Short-vol P&L is inverted-U in COR-z, not monotone (Spearman p=0.285); COR-z is **0.80 collinear with VIX-z** and its marginal effect is **t=1.45 (ns)** once vrp-z and VIX-z are controlled; the gate lifts Sharpe 0.732→0.748 while **halving annual return**; the sign **inverts in 2020**. Same failure mode as #228 (GEX) and #219 (SVI) — a plausible axis that dies on a regime confound |
| **COR** as a directional/warning read | `2026-07-19-dispersion-signals-eval.md` | **Claim rejected.** The deepest forward drawdowns follow **HIGH** correlation, not low (h21 max-DD −4.21% at Q5 vs −2.07% at Q1). High correlation as the danger marker is already encoded in CRI's `crash_trigger` (COR1M > 60) |
| **VOL CONE** (cheap IV / cheap wings ⇒ long-vega alpha) | `leap-vega-alpha/` Stage 1 → Stage 2 | **NO tradable vega edge.** Stage 1 passed (Fama-MacBeth IC 0.34/0.43, survives LOO) — then Stage 2's P&L decomposition found it is **82–88% delta**: a directional bet on high-vol names in an up-market. The isolated, delta-hedged, theta-net vega edge is **0.6–0.7 vol points, below the ATM-LEAP round-trip spread.** "A market/beta bet dressed as vol-alpha" |
| **CREDIT** (HYG as the credit proxy) | `scanners/vcg.py` | **Already in production.** `DEFAULT_PROXY = "HYG"`, with distribution-adjusted closes (credit ETFs distribute monthly; raw `close` would print phantom gaps). Argon has been reading this exact series the whole time |
| **Equibles / ATS venue share** (flow-family) | `2026-07-07-flow-vs-rviv-verdict` (#227) | Option-flow siblings (aggressor imbalance, net vanna, net charm) are **subsumed by RV−IV**. ATS *equity* venue share is not literally the same measurement, so it is untested rather than killed — but the family prior is poor |
| **VIXCOR** | radon's own 5,152-session study | Refuted by its author: post-event VIX drawup **significantly LOWER than random** at h=5 (p=0.023) and h=10 (p=0.016) |

**Also already held:** argon's `vol_index_daily` carries **COR1M back to 2006-01-03** (~20 years, cross-checked at Pearson 0.91 against an independently-built component-IV proxy). The "radon has 20 years of implied correlation that argon lacks" framing was false.

### 3.2 The two narrow things that survive

**N1 — COR term structure (COR6M − COR1M).** #226's verdict names exactly one re-test condition:
*"Re-test only with a genuinely orthogonalized measure (e.g. COR residual after regressing out VIX
term structure) and more non-crisis-clustered history."* Argon holds **COR1M only**. Radon's
`scripts/clients/cboe_client.py` (4.0K, conditional GET → 304) pulls **COR1M/3M/6M/1Y, 2006-01-03 →
present, ~5,181 rows per tenor, Cboe-backfilled**. A COR term slope is a candidate orthogonalized
measure argon cannot compute today.

This is the **only place radon's new data is a genuine capability gain.** It is also the cleanest
possible setup: the falsification criteria are pre-registered in #226 (monotonicity in the
orthogonalized measure; marginal significance controlling vrp-z and VIX-z; Sharpe gain that does not
come out of return). Prior that it works: **LOW** — the base rate on "the same axis, measured
slightly better" is bad, and #226's effect inverted in the one regime where it would matter.

**N2 — power up the VIX/COR1M ratio (argon's own parked thread, not a port).** The 2026-07-19 doc
established that `ratio_z` is **orthogonal to VIX (Pearson 0.063)** — a real dispersion axis rather
than a VIX proxy — and that its sign is **consistently negative across h10/h21/h42** (high
VIX/COR1M → high-beta underperforms). It is never significant, because n = 29–124: SPHB/SPLV only
begin 2021-06 in the lake. The doc names the fix: an external SPHB/SPLV feed (UW MCP has it) extends
the test to ~15 years. Note the ceiling the doc itself sets — this is *"a sound risk-management
posture, not a validated timing signal"*, so the realistic payoff is a **sizing rule**, not alpha.

### 3.3 Worth taking for reasons that are not alpha

| Item | Why |
|---|---|
| **Alert pipeline** (radon F6 rules engine + `/alerts`) | Argon's `alerts.py` is **43 lines**, two callers, no rules table. Still the explicitly named Stage-1 minimal deliverable of the whole five-repo desk. The stage gate |
| **Weekend audit/remediation loops + incident responder** | `option_surface_grid_daily` accrues **forward-only — every uncaptured night is permanently lost.** Radon's Sat delta-audit → Sun PR-only remediation on an always-on runner, plus a 5-min incident prober and a heartbeat on the auto-fixer itself, is uptime insurance on the one asset argon cannot backfill. Not alpha; **not losing** alpha |
| **Earnings-date service** | Argon's fundamentals IC is measured on rows carrying a real `filing_date`. A point-in-time event-date source is a data-quality input, not a signal |
| **`.claude/skills/new-indicator` vertical-slice checklist** | Process, not signal. Speeds the plumbing without touching the promotion bar |

### 3.4 Do not port

TRIN · BREADTH · MARGIN · BPI · CURVE · IVRANK · SKEW · SKEW2D · STRADDLE · VIXCOR · knowledge base ·
assistant · newsfeed · marketing site · order surfaces. Crowded daily equity technicals (the exact
space where 14 signal-lab studies died), already-held series, measured nulls, or xenon's lane.

## 4. On the delivery-rate gap

Radon shipped 12 indicators in 7 weeks; argon ships a lane a month. The mechanism is visible: `.claude/skills/new-indicator/SKILL.md` defines an indicator as a 7-part vertical slice with named reference implementations, and `/indicator` fans it out to a parallel worktree swarm (ingestion / API / chart tab).

That is real leverage and argon could adopt the vertical-slice checklist. But the two rates are not comparable on their own terms: radon's 7 weeks produced **one** validation study and it was negative, while argon's slower lanes produced a kill record that is the reason its surfaces can be trusted. Speed up the *plumbing*, not the promotion bar.

The honest synthesis: **radon is a good acquisition front-end for argon.** Let it find and wire sources fast; make every signal claim earn its way through argon's falsification before it reaches a surface.

---

## 5. Order of attack

1. **Alert pipeline v1.** The stage gate. Independent of everything above.
2. **#163 — does a kill switch improve the VRP short-vol winner's tail?** Not a port. This is work on
   the **one thing that pays**, with three gate designs already specified. Higher expected value than
   any item on this page.
3. **N1 — port the Cboe client for the COR term structure**, and run #226's pre-registered re-test on
   the orthogonalized measure. One day. Prior LOW; the falsification criteria are already written, so
   a null closes the correlation axis permanently instead of leaving it to be re-proposed a third time.
4. **N2 — wire an external SPHB/SPLV history and re-run the 2026-07-19 Claim-1 test at power.** Outcome
   is a sizing posture, not a signal.
5. **Weekend audit/remediation loops.** Uptime insurance on the forward-only surface grid.
6. Everything else: no.

## 6. The honest summary

Radon shipped 15 features in 8 weeks and **not one of them is a validated alpha source.** Ten of its
twelve indicator specs contain zero forward-return work; the one real study refuted its own premise;
the one other spec states outright that no study was run. Three of the four ideas that looked most
promising from the radon side map onto tests argon has **already run and killed**, and a fourth
(HYG credit) argon has been running in production the whole time.

That is not a failure of radon — it is what an acquisition front-end looks like. But it means the
port's value is **infrastructure and uptime, not edge**. The one narrow capability gain is the COR
term structure, and it exists only because #226 pre-registered it as the single condition under which
the correlation axis may be re-opened.
