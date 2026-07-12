# Stack master plan — goals, stages, gaps per component (2026-07-12)

High-level master plan for the six-component desk. Derived from the 2026-07-12
cross-repo review (`docs/masterplan/2026-07-12-stack-vision-blockers-review.md`)
— read that for evidence, file citations, and rationale; this doc is the
actionable outline. Argon `CLAUDE.md` "Mission" carries the condensed version.

## The ladder (recap)

| Stage | Theme | Exit criteria (falsifiable) |
|---|---|---|
| 1 — Trustworthy foundation *(current)* | Machine tells the truth | Multi-year backtests trustworthy; orders can't silently double; staleness machine-caught; options history accruing durably; **signal→alert pipeline live (minimal deliverable)** |
| 2 — Self-tending desk | Machine owns babysitting + research throughput | One week unattended; scheduled research runs; ≥1 PROMOTE with live shadow record; execution-realism gate in promotion contract |
| 3 — Proposal desk *(aim, not commitment)* | Machine composes, human disposes | ≥90% of trades enter as staged one-click proposals; markout feedback closes automatically |
| 4 — Mandate autonomy *(ceiling)* | Machine executes inside explicit mandates | ≥1 mandate 6+ months, zero gate breaches, performance inside backtested band |

**Invariants at every stage:** defined-risk only / no naked shorts; every
mutating agent action routes through a gate; persist everything durable;
subtraction over addition. Exit criteria gate only the next stage's
risk-bearing items — harmless prep may run ahead.

---

## livewire — the data substrate

**Role:** durable historical warehouse; everything downstream inherits its honesty.
**End goal:** bronze→silver→gold multi-asset Parquet lake with an options data
domain; reliability-hardened; consumers never touch a known-dirty layer.

| Stage | Objectives |
|---|---|
| 1 | **Corporate-action adjustment** (splits/dividends feed; real `adj_close` — today it is `close` verbatim, Massive fetched `adjusted=False`). Complete the ticker-rename map (~10 names failing daily publish). **Probe massive.com historical options data** → go/no-go on Sub-E-via-massive. |
| 2 | Silver layer (cleaned/adjusted canonical) so consumers stop reading raw bronze. Options ingestion (Sub-E) if the probe is a go. Publish-cost fixes (per-month partitioning or hot/cold tiering — current floor ~88 min/day on the HDD). |
| 3+ | Gold layer (factors) only when research demands it; ClickHouse publishing optional. |

**Gaps (verified):** `adj_close = close` everywhere; no splits/dividends
ingestion; silver/gold 0%; Sub-E 0%; rename map incomplete; HDD/exFAT publish
ceiling; IB Gateway 2FA manual (human-in-the-loop outages); Massive intraday
capped at rolling 5y (vendor, accepted).

---

## signal-lab — the research engine

**Role:** turn ideas into promoted signals or honest kills.
**End goal:** a pipeline whose PROMOTE verdict means "survives a truthful
execution model on trustworthy data" — and that actually promotes.

| Stage | Objectives |
|---|---|
| 1 | Wire massive.com + FRED clients (its own Direction §1). Point-in-time constituents source (kills the survivorship caveat stamped on nearly every study). Fix env (hmmlearn missing in primary checkout). **Start short-horizon options studies now** — argon's surface grid has ~6.5 months (2025-12-26→present, 17.8M rows), enough for weekly-structure / VRP-markout / skew-dynamics work. |
| 2 | **Execution-realism gate in the promotion contract** — truthful fill/latency model (nautilus-as-component via bridge, or purpose-built validated against xenon real fills). Research-loop agent runs scheduled idea triage + studies. Target: first PROMOTE (cannot be scheduled — maximize shots on goal). Re-run the study classes that data gaps blocked (options premia, macro regime, PIT-corrected equity). |
| 3 | Promotion bundles carry proposal-composer metadata (sizing rule, structure class, risk caps). |

**Gaps:** 0 promotions in 14 studies (cost-fragility is the dominant killer);
survivorship bias unfixed; massive/FRED unwired; kill record itself tainted by
livewire's unadjusted prices (re-check key kills after the Stage-1 data fix).
**Research aim:** tilt toward the options/vol/flow structural-advantage
surface; 14 studies died on crowded daily equity technicals.

---

## apex — the signal engine

**Role:** streaming TA/indicator/rule service between the lake and the surfaces.
**End goal:** the focused post-pivot service, stripped of the dead monolith,
with signals argon and the alert pipe can trust end-to-end.

| Stage | Objectives |
|---|---|
| 1 | Decide D5 (keep one IB historical adapter vs let backtest go dormant) → execute Phase 6 strip-down (~30K LOC dormant: `src/backtest/`, IB/Futu adapters, risk services, CF frontend). Fix `make install` (nonexistent `server` extra, deleted `web/`; rename `apex-risk`). Make missing-parquet reads loud (silent-empty already caused prod incident #141) — at minimum a freshness/emptiness signal the patrol agent can alarm on. |
| 2 | **Persist signal lifecycle** (status / invalidated_at) so argon and alerts can distinguish active from stale — currently append-only-forever. Reconcile `tasks/todo.md` vs actual Docker deploy state (stale doc). Optional: WS push for indicators if argon polling grows. |
| 3 | Signal metadata sufficient for proposal composition (direction, horizon, confidence, invalidation trigger). |

**Gaps:** Phase 6 unexecuted (blocked on D5); broken onboarding; silent-empty
contract; no signal lifecycle; orphan tests outside CI; coverage gate lowered
85→40 instead of deleting dead code.

---

## argon — the analytics cockpit + alert surface

**Role:** the decision surface; Stage 1's minimal deliverable lives here.
**End goal:** the place the operator looks — and the place that *calls* the
operator when something is worth seeing.

| Stage | Objectives |
|---|---|
| 1 | **Alert pipeline v1** (THE minimal deliverable): rules engine (adapt radon `scripts/alerts/evaluate.py` — port-idea R3) + channel (existing `UW_SCAN_OPS_ALERT_WEBHOOK_URL` plumbing → Pushover/Discord). First subscriptions: VRP macro state flips (`/api/regime/vrp-macro-signal`), CRI/VCG regime transitions, ops/staleness from the patrol agent, display-only verdict landings. Keep surface capture healthy (forward-only — every uncaptured night is lost). Re-measure UW burn under the 120k/day budget; carve the research slice. |
| 2 | Rebuild AI analysis workers as API-based runners (#248/#240). Close the mega-cap intraday gap (#180) and skew tenor fix (#207). Serve the surface grid to signal-lab's short-horizon options studies. Landing surface for display-only promotions. |
| 3 | Proposal *context* rendering (the decision support beside xenon's approve button — xenon owns the staging surface itself). |

**Gaps:** no alert pipeline yet; AI workers sacrificed in Docker cutover;
#180/#207 open; UW slice unmeasured at new budget.

---

## xenon — the broker terminal / the gate

**Role:** where money moves; the human's disposal point at every stage.
**End goal:** an order path safe enough to *earn* Stages 3–4.

| Stage | Objectives |
|---|---|
| 1 | **OP-1**: `UNCERTAIN` order state + IB-id correlation + reconciliation sweep (kills the timeout→retry→double-position path). **SEC-1**: real auth on the Next.js order routes (X-Internal-Token bypass). **Re-enable order-path integration tests in CI** (#39/#41 — the root enabler of everything else). OP-6: move combo replace server-side (no naked-position window). |
| 2 | External-fill visibility test (P1.4 — do TWS/mobile fills reach the blotter?). Runtime reconciliation (not boot-only). Relay backpressure + CI behavioral tests. OP-4 modify persistence. |
| 3 | Trading-as-git staging surface: proposal inbox → review → one-click approve → submit, portfolio-aware (risk budget, existing positions, no-naked-shorts by construction), full audit chain to markout. |
| 4 | Mandate engine: per-strategy caps, structure whitelist, drawdown/regime auto-suspend, revocation. |

**Gaps:** the stack's least-protected real-money code (audit Critical OP-1 +
live-verified SEC-1); tests excluded from CI; inverse coverage gradient vs the
no-money repos.

---

## agent harness — the sixth component (to be born)

**Role:** patrol, groom, schedule — machines own the babysitting (goal
refinement R1). **Design tenets (from dexter/OpenAlice/radon):** the harness is
the product, not the brain — wrap Claude Code CLIs, own only scheduling +
context + delivery; silence discipline first (suppression sentinels, dedup,
backoff, auto-disable, budgets); JSONL audit trail; **agents propose, a gate
disposes** — read-only patrol needs no gate, every mutation does.

| Stage | Objectives |
|---|---|
| 1 | **Ops/health patrol agent v1**: read-only sweep (argon `/api/health` + freshness + gap-healer, apex CI + emptiness signal, livewire incident JSONL, xenon order-path canaries); writes = GH issues + the alert channel. Design by adaptation: radon `scripts/watchdog/` (cadence buckets, hysteresis, cooldown, grouping) + dexter heartbeat/suppression. |
| 2 | Maintenance agent (PR-only writes; grooms the debt table, dead code, stale docs). Research-loop agent (scheduled signal-lab triage + studies; statistical gates are the rail). |
| 3 | Proposal-staging orchestration (composes from promoted signals, files into xenon's staging surface). |

**Gaps:** doesn't exist. Open: runtime home (mini cron has tailnet access;
cloud doesn't), owning repo (sixth repo vs skill), token budget. Prerequisite:
a brainstorming/design session before any build.

---

## Open decisions

| # | Decision | Owner | Blocks |
|---|---|---|---|
| D-A | **radon: live parallel venue or winding down?** | operator | If winding down → extract watchdog/DAG/tool-loop before stale; if live → stack map is six repos + first-class status |
| D-B | massive.com options data: tier/coverage/pricing probe verdict | probe task | livewire Sub-E path; long-sample options research |
| D-C | apex D5: keep IB historical adapter vs dormant backtest | operator | apex Phase 6 strip-down |
| D-D | Harness runtime + owning repo | design session | agent harness v1 |
| D-E | Proposal-wire go/no-go (re-priced at each stage exit; low confidence today) | operator | Stage 3 entirely |

## Sequencing (Stage-1 order of attack)

1. livewire corporate-action adjustment — restores trust in everything downstream
2. xenon OP-1 + SEC-1 + CI re-enable — capital safety; plans already written
3. argon alert pipeline v1 — the minimal deliverable, buildable now
4. massive.com options probe (D-B) — unlocks the structural-advantage research surface
5. UW 120k burn re-measure — unblocks the research slice
6. Harness design session → patrol agent v1
