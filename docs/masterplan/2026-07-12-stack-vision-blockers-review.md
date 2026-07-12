# Stack review: end-state vision, blockers, and directions (2026-07-12)

Cross-repo review of the trading stack — **livewire, apex, argon, xenon, signal-lab** —
run 2026-07-12. Method: Fable orchestrator + 4 parallel Sonnet explorers per pass
(one per sibling repo; argon covered from in-repo context + `gh issue list`).
Pass 1 mapped each repo's stated end-state; pass 2 hunted blockers
(TODO backlogs, audit docs, open decisions, verdict files, live code checks).

Reproduce: re-run the two explorer prompts per repo (vision pass, blocker pass) —
they read only committed docs/code, no network state beyond `gh issue list`.

---

## 1. The end-state: a one-person, self-hosted quant desk

The five repos converge on an institutional pipeline decomposed into
single-responsibility services, all on the Mac mini, human-in-the-loop:

```
                 ┌─────────────┐
  ideas/arXiv ──▶│  signal-lab │  research lab: PIT datasets, walk-forward,
                 │  (research) │  Monte-Carlo gates → promote or kill
                 └──┬───────┬──┘
        promote:    │       │    promote: display-only verdicts
        exec-grade  ▼       ▼
┌──────────┐   ┌───────┐  ┌───────┐   ┌───────────┐
│ livewire │──▶│ apex  │─▶│ argon │   │   xenon   │
│ (data    │bars│(signal│WS │(options│  │ (broker   │
│  lake)   │   │engine)│   │cockpit)│  │ terminal) │
└──────────┘   └───▲───┘  └───▲────┘  └─────┬─────┘
                   │ live ticks│  greeks/spot │
                   └───────────┴──────────────┘
                                              ▲
                            operator decides & clicks the trade
```

- **livewire** — durable historical substrate. Declared end-state: bronze→silver→gold
  Parquet tiering, multi-asset, options-chain capture (Sub-E), ClickHouse publishing.
  Today: bronze only.
- **xenon** — pure broker terminal post the 2026-05-22 "pure-portfolio pivot"
  ("no signal generation — bring your own thesis"). Old signal ambitions deliberately
  deleted, displaced onto apex/argon.
- **apex** — streaming TA signal service (pivoted from a 148K-LOC risk/backtest
  monolith). livewire bars + xenon ticks in → indicators/rules/regime out to argon.
  Remaining roadmap is subtraction (Phase 6 strip-down).
- **argon** — options/flow analytics cockpit: UW-driven per-ticker analytics, regime
  indicators (CRI/VCG/GEX), VRP signals, AI trade insights.
- **signal-lab** — gated research engine: idea → falsifiable hypothesis → PIT backtest
  → permutation/PBO gates → verdict. Survivors promote as PR'd bundles to apex
  (tradeable, ±20% Sharpe parity gate) or argon (display-only).

**Two defining design decisions:**

1. **The signal→order wire is deliberately not connected.** The apex→xenon
   auto-execution design (signals outbox → Four Gates) was fully designed then
   archived unimplemented; the pivot deleted the gate logic it needed. End-state is
   a human-in-the-loop desk, not an autonomous bot. Whether that wire ever connects
   is the biggest open fork (survives only as xenon `docs/todo-backlog.md` §3).
2. **Evolution is consistently toward narrower, sharper tools.** xenon and apex both
   went through major subtraction pivots; signal-lab kills most of its own research.
   Five small services with hard contracts, not a monolith. (Radon's status is NOT
   "superseded" as first written — see §4.1: 50 commits in the week to 2026-07-11,
   active infra cutover. Whether it is a parallel live system or winding down needs
   an operator ruling.)

One-sentence answer: machines own the data lake, research validation, live signal
computation, and options analytics; the operator owns the thesis and the trigger —
automation stops, by explicit design, one step short of order placement.
(Refined 2026-07-12 by §4.2: the end-state also includes a thin agent harness —
machines patrol, groom, and may *stage* proposals; the operator still disposes.)

---

## 2. Main blockers, ranked (stack-wide)

### #1 — Data substrate integrity: `adj_close` is a lie (livewire)

Every row-construction path sets `adj_close = close` verbatim
(`clients/ingestion_common.py:124`, Massive flat-file publisher, CBOE fetcher).
Massive REST client hardcodes `adjusted=False`, never overridden. **No
split/dividend ingestion anywhere**; no silver layer to catch it, so apex and
signal-lab consume raw bronze directly. Poisons every multi-year backtest that
crosses a split — manufactures fake edges AND destroys real ones, so **the
signal-lab kill record is itself partially untrustworthy in both directions**.
Cheapest fix relative to impact: one corporate-actions feed + adjustment pass.
Related bronze defects: ticker-rename map incomplete (VSCO→VSXY etc.; ~10 tickers
fail daily union publish), orphaned temp files from killed writers.

### #2 — The desk is options-shaped but options can't be backtested

- livewire Sub-E (options chain capture): 0% built, deferred in every spec
- UW per-strike history: ~180-day API window (per-strike history beyond ~30
  days 403s; the launch backfill captured the full window once)
- argon surface grid (`option_surface_grid_daily`): **2025-12-26 → present,
  ~6.5 months, 17.8M rows** — verified by live DB query 2026-07-12 (earlier
  "from 2026-06 only" claim in signal-lab's data-map was WRONG; PR #145's
  launch backfill pulled UW's full ~180-day window). Structurally capped:
  cannot extend backward past the UW window, accrues forward nightly.
- Aggregate vol history is much deeper and often confused with the grid:
  `vol_index_daily` 1975→ (51y), `options_volume_daily` 2021→ (~5y),
  `vrp_daily`/`realized_volatility_history` ~14 months, IV smile/term
  snapshots ~2 months.
- signal-lab `promotion-contract.md` lists "claim a multi-year options backtest"
  under **"Never"** — still correct for per-strike work, but ~6.5 months
  already permits short-horizon options studies (weeklies, VRP harvest
  markouts, skew dynamics) earlier than the stale claim implied.

Structural mismatch: research firepower points at equities (deep data, scarce
edge) while the traded asset class (options) can only be validated on weeks of
history. Delay is the cost — every week without capture is unbuildable history.

**Decision 2026-07-12 (operator):** IB-based chain capture is effectively
infeasible for us ("we literally can't do it"). New direction: **evaluate
massive.com's historical options data** as the Sub-E substitute.
Availability/tier/pricing unverified as of this writing — needs a probe before
planning. If viable, this converts #2 from a time-gated blocker into a
purchase/integration task.

### #3 — Zero promoted signals in 14 studies; cost-fragility is the dominant killer (signal-lab)

Five weeks of gated research: **9 KILL, 4 ITERATE, 2 DISPLAY-ONLY, 0 PROMOTE**;
`research/promotions/` does not exist. Recurring death: edges statistically real
gross (permutation p≈0.000) collapse at 2–10 bps costs or a 1-bar execution
delay (quantstrat-replication, overnight-regime-lab, dualmacd, cvd, ripster,
trendpulse). The pipeline is working as designed — tightened stats (Newey-West,
placebo graphs) correctly flipped semi-leadlag from ITERATE→KILL. But the stack's
core deliverable has never shipped. The closest validated edge lives outside
signal-lab: argon's VRP macro short-vol (Sharpe ~1.65 in-harness, PR #150) — an
options signal, reinforcing #2. Secondary contributors: survivorship bias in most
S&P500 studies (no PIT constituents feed), massive/FRED clients unwired
(signal-lab Direction §1), hmmlearn missing from primary checkout env.

Not attacked directly — it is the dependent variable of #1 and #2.

### #4 — xenon order path: least-protected code where real money moves

- **OP-1 (Critical, audit-confirmed live):** 15s subprocess timeout after IB may
  have accepted → recorded terminal FAILED, no IB ids persisted → operator retry
  doubles a live position. Remediation plans exist (`docs/superpowers/plans/
  2026-07-05-fable-*`), unexecuted.
- **SEC-1 (verified live in code):** Next.js `/api/(.*)` public by middleware
  design; `xenonFetch` attaches `X-Internal-Token` which FastAPI accepts as full
  Clerk bypass → unauthenticated order placement for anyone reaching the web
  port. Same bug class already burned prod once (incident #23).
- **Root enabler:** order-path integration tests known-broken and excluded from
  CI (xenon #39/#41, open since 2026-04); real place path has zero route
  coverage.
- **OP-6:** combo modify is cancel-then-place in the frontend; failure after the
  cancel leaves a naked position — in a system whose one hard rule is no naked
  shorts.

Inverse coverage gradient across the stack: livewire (no money) has a 95-100%
coverage gate; xenon (live orders) has its riskiest path excluded from CI.

### #5 — Single-host operational ceiling + hard vendor caps

Everything on Mac mini hardware, no failover; lake on spinning exFAT HDD
(~88-min floor per daily intraday publish; 5-25× slower than APFS on cold wide
scans — exactly signal-lab's SSH+DuckDB pattern); IB Gateway 2FA is manual, any
session drop stalls IB-sourced ingestion until a human taps a phone.

Vendor caps (operator ruling 2026-07-12):

| Cap | Status |
|---|---|
| UW daily budget | **Raised 40k → 120k/day.** Alpha-probe-era "budget fully eaten by 08:00 ET" finding needs re-measurement under the new ceiling; the always-on stack's burn should now leave a research slice. |
| IB ~100 market-data lines | **Hard gate — accepted as permanent constraint.** Design around it (serial per-mark budgets, no bulk polling), don't plan against it. |
| Massive intraday history | Rolling 5-year window (403 outside it); IB non-equity intraday even shorter (1y for 5m). Vendor-imposed. |

---

## 3. Secondary debt log (confirmed mostly true by operator, 2026-07-12)

Logged so it doesn't evaporate; none are stack-blocking today.

| # | Repo | Item | Ref |
|---|---|---|---|
| S1 | apex | Phase 6 strip-down never ran: ~30K LOC dormant pre-pivot code (`src/backtest/` 21.9K, IB/Futu adapters, risk services, CF frontend). Blocked on open decision D5 (keep IB historical adapter for backtest vs let it go dormant). | adaptation design §6 |
| S2 | apex | `make install` broken: references nonexistent `server` extra + deleted `web/`; CI sidesteps so it's invisible. Package still named `apex-risk`. | `Makefile:87` |
| S3 | apex | livewire read contract returns silent empty on missing parquet — never an error; already caused one prod incident (0.1.2, #141). | `docs/livewire-apex-integration.md` §2 |
| S4 | apex | Signal lifecycle not persisted (no status/invalidated tracking) — argon cannot distinguish stale from active signals. No live WS for bars/indicators (REST-poll only); indicators compute-on-read uncached. | `docs/argon-apex-api.md` §7 |
| S5 | apex | Orphan tests outside CI scope fail locally (`tests/partial/`, `test_vix_alert.py`); coverage gate quietly lowered 85→40. | `pyproject.toml:119` |
| S6 | apex | `tasks/todo.md` says prod cutover "parked" but apex deployed via Docker/GHCR 0.1.3 on 2026-07-08 — todo file likely stale [INFERRED, MED]. Verify and update. | `tasks/todo.md` |
| S7 | argon | AI analysis workers (Codex/Claude) sacrificed in Docker phase 1; rewrite as API-based runners pending. | #248, #240 |
| S8 | argon | `option_intraday_buckets` mega-cap coverage gap: TSLA/NVDA/MSFT/GOOGL/META/AVGO never fetched. | #180 |
| S9 | argon | Skew rr_25d rides 0-DTE tenor noise; move to ~30d constant-maturity. | #207 |
| S10 | xenon | ~500+ lines dead client-side scanner/regime code post-pivot; `docs/architecture/architecture.md` stale (describes deleted scanner architecture). | fable audit CX-3 |
| S11 | xenon | External-fill visibility unproven: TWS/mobile-placed fills may never reach the blotter (non-master clientIds). Untested; P1.4 in backlog exists to test it. | fable audit OP-10 |
| S12 | xenon | Realtime relay (2,256 lines): zero CI-enforced behavioral tests, no backpressure on client sends; reconciliation sweep runs only at boot. | fable audit QS-1/2, OP-3 |
| S13 | livewire | Silver/gold layers unstarted (only naming decided: F=silver, G=gold); DuckDB retirement deferred; row-count anomaly detector still `NotImplementedError`. | `.codex/project-memory.md` |
| S14 | signal-lab | massive.com + FRED clients unwired (Direction priority #1); qlib leverage still baseline-only; GPU box re-clones qlib per job (~2 min tax); ideas ledger lives in GH issues, not the repo's own audit trail. | signal-lab CLAUDE.md |

---

## 4. Open direction: agentic orchestration of the stack

Operator intent (2026-07-12): introduce an agentic layer to orchestrate the
stack. Idea capture only — not yet designed or scoped.

**Prior art already in the workspace:** signal-lab is already agent-shaped (a
Claude Code skill whose HANDOVER doc literally specifies "Fable orchestrates;
sonnet/opus subagents do exploratory work"); `dexter/` (autonomous research
agent with task planning); `nofx/` (agentic trading OS, multi-agent self-play).
Claude Code provides scheduled cloud agents / cron routines as runtime.

**Candidate shapes, roughly in ascending risk:**

1. **Ops/health agent** — scheduled sweep over `/api/health` (argon), freshness
   monitor, gap-healer output, apex CI, livewire incident JSONL; triage + file
   issues / heal. Read-only against prod, write via GH issues. Lowest risk,
   attacks real pain (silent staleness incidents recur across repos).
2. **Research-loop agent** — scheduled signal-lab idea triage + study execution;
   the gates already provide the safety rail (agents can't promote past the
   statistical gates). Natural extension of what signal-lab is.
3. **Cross-repo maintenance agent** — grooms the secondary-debt table above,
   opens PRs for mechanical items (S2, S5, S10). PR-only writes, CI as gate.
4. **Execution-adjacent orchestration** — explicitly OUT for now: contradicts the
   deliberate human-in-the-loop design decision (§1). Revisit only if the
   apex→xenon wire decision is ever re-opened, and only after #4 (order-path
   safety) is fixed.

**Open questions before any build:** where it runs (mini cron vs claude.ai
scheduled agents — mini has all the network access, cloud has none of the
tailnet); guardrail model (read-only vs PR-only vs job-enqueue); token budget;
which repo owns the orchestrator (a sixth repo vs a skill like signal-lab).

### 4.1 Reference repos assessed (2026-07-12, three Sonnet explorers + prior context)

Operator named dexter (agentic example), nautilus (execution engine example),
qlib (research example), plus radon and OpenAlice. Verdicts:

| Repo | Provenance | Verdict | What to take |
|---|---|---|---|
| **dexter** | virattt OSS clone, active (commits to 2026-07-10), never run locally | **Steal patterns, don't adopt.** Single-agent ReAct CLI, not an orchestration framework; "task planning / self-validation" in its README is marketing — no planner object, guardrails are soft warnings. | Heartbeat patrol with suppression (`HEARTBEAT_OK` sentinel, dedup window, error backoff, auto-disable) — the single most transferable piece for the ops/health agent; typed depth-1 subagent delegation with per-type tool allow-lists; LLM compaction over truncation; append-only JSONL scratchpad audit trail; allow/ask/deny bash permission engine with non-overridable deny floor. |
| **OpenAlice** | TraderAlice OSS clone (AGPL-3.0, 0.75-beta), pulled 2026-07-12, built but never launched | **Pattern reference only** (AGPL forbids vendoring; full Electron product would collide with xenon/argon roles). Architecturally the closest existing answer to "what does the sixth repo look like." | Its two core moves: (1) **don't build an agent loop — wrap native CLIs** (`claude`, `codex`) and own only credentials/context injection; (2) **markdown-file-as-task** with cron frontmatter + a 60s ScheduleScanner + Inbox delivery — a scheduler with no DB. Plus "trading-as-git" (stage → review → approve → push) as the approval-gate shape for anything money-adjacent, and the Guardian single-writer process-supervision pattern. |
| **radon** | Own code. **NOT frozen** — 50 commits in the week to 2026-07-11, active radon-cloud monorepo fold-in + reliability cutover | **Best internal reference architecture for the orchestration layer — and a live project needing a status ruling.** Both port-ideas backlogs (xenon 16/17, argon 4/5) remain unmined, but the higher-leverage asset is unlisted in both docs. | The trio that pre-answers the §4 open questions: `scripts/watchdog/` (cadence buckets, 2-failure hysteresis, per-(service,severity) cooldown, alert grouping, auto-heal) ≈ **ops/health agent v1 already built**; `scripts/workflow/executor.py` (topo-sorted DAG with gate-blocking nodes); `web/lib/assistant/loop.ts` (tool loop that halts on destructive calls and returns a confirm-proposal — the guardrail-model answer). Read these before designing from scratch. Also: xenon port item #1 (`_wait_for_perm_id` into single-leg path) is still not done — it targets exactly the OP-1 order-ack weakness in §2 #4. |
| **nautilus_trader** | OSS study clone | **Not an execution engine to adopt today** — auto-execution is deliberately out (§1 decision). Its near-term value is different: **execution-realism modeling**. signal-lab's #3 blocker is signals dying at 2–10 bps / 1-bar delay with naive fill models; nautilus's event-driven backtest engine with realistic fill/latency simulation is a candidate high-fidelity validation layer for exactly those cost-sensitive edges. Engine role revisit only if the apex→xenon wire reopens, and only after xenon order-path safety (§2 #4) is fixed. | Fill/latency simulation concepts for the cost-sensitivity lane; event-driven architecture patterns. |
| **qlib** | OSS study clone | **Already in the right relationship — a consumed component, not a platform.** signal-lab's qlib_bridge + GPU runner run Alpha158+LightGBM today. Don't re-platform (qlib's data layer would fight livewire + the PIT discipline). | Deepen per signal-lab Direction §2: custom factor expressions, qlib's own walk-forward as an alternate validation engine. |

Cross-cutting read: the three external repos (dexter, OpenAlice, nautilus) all
converge on the same guardrail philosophy radon implemented independently —
**agents propose, a gate disposes** (dexter's ask-by-default permissions,
OpenAlice's trading-as-git, radon's confirm-proposal halt). That should be the
non-negotiable spine of the orchestration layer: every mutating action routes
through a staged approval surface; read-only patrol needs none.

**Open question for the operator (blocking the "predecessor" framing):** is
radon still a live/parallel execution venue, or winding down? If winding down,
extract `watchdog/` + `workflow/executor.py` + `assistant/loop.ts` patterns
before they go stale; if live, it's not a predecessor at all and deserves
first-class status in the stack map (§1).

### 4.2 Lessons, and whether they adjust the ultimate goal (2026-07-12)

**Five lessons, one per repo:**

1. **OpenAlice — the harness is the product, not the brain.** It ships zero
   agent-loop code: it wraps native CLIs and owns only credentials, context,
   scheduling (markdown + cron frontmatter, no DB), and delivery (inbox). Our
   orchestrator should be equally thin — Claude Code is the brain; build the
   substrate agents coordinate through.
2. **dexter — the hard part of unattended agents is silence discipline, not
   intelligence.** Its real engineering went into suppression sentinels, dedup
   windows, error backoff, auto-disable, result-size budgets, audit JSONL — not
   the (flat) reasoning loop. An unattended agent's dominant failure mode is
   noise and cost, not wrong answers. Corollary: its "task planning /
   self-validation" README claims are marketing over a plain ReAct loop —
   don't over-architect a planner; ship a loop with hard rails.
3. **radon — ops maturity is accreted from incidents, not designed.** The
   watchdog's cooldown tables, alert grouping, and hysteresis are scar tissue
   from real pages. Design-by-adaptation from radon beats design-from-scratch;
   and the same person's ideas got rebuilt across siloed repos — the
   orchestration layer is also a knowledge-reuse mechanism.
4. **nautilus — the fill model is part of the signal's truth.** Our #3 blocker
   (every edge dies at 2–10 bps / 1-bar delay) means the execution simulator is
   the actual gating instrument of the research pipeline, deserving
   engine-grade treatment — not a scalar bps haircut in a backtest loop.
5. **qlib — consume components, never adopt platforms.** The one integration
   that went smoothly (qlib via a bridge, its data layer ignored) is the model
   for how nautilus/OpenAlice/dexter should be treated. Platform gravity kills
   local discipline (PIT, livewire contracts); bridges preserve it.

**Does this adjust the ultimate goal? Destination no, shape yes — three
refinements adopted into the vision:**

- **R1 — the agentic layer is promoted from "open direction" to part of the
  end-state.** The desk's ultimate form is six components, not five: data,
  research, signals, analytics, execution, **plus a thin agent harness that
  patrols, grooms, and schedules** — machines own the babysitting too. (§1
  one-liner amended accordingly.)
- **R2 — the human-in-the-loop line moves from "human initiates" to "agents
  may stage, human disposes."** Trading-as-git (OpenAlice) + confirm-proposal
  (radon) show automation can advance one step — staging a fully-formed order
  for one-click approval — without violating the no-auto-execution decision.
  This reopens the apex→xenon wire question in a weaker, safer form:
  *proposal* wire, not *execution* wire. HARD PRECONDITION: §2 #4 (xenon
  OP-1/SEC-1/CI gap) fixed first; a staged-order surface on today's order path
  would amplify, not contain, those risks.
- **R3 — signal-lab's promotion gate grows an execution-realism stage.** The
  end-state research pipeline validates against a realistic fill/latency
  simulation (nautilus-grade, possibly nautilus-the-component via a bridge per
  lesson 5), because cost-fragility — not statistics — is what kills
  everything today. "Statistically real" was never the bar; "survives a
  truthful execution model" is.

Not adjusted: edge scarcity is still the binding constraint no architecture
fixes; the five-service decomposition stands; subtraction-over-addition stands.

Next step when picked up: a proper brainstorming/design session scoped to ONE of
the shapes above (recommend starting with the ops/health agent — smallest, and
it directly patrols the blockers in §2/§3).

---

## 5. Order of attack (recommendation, 2026-07-12)

1. **livewire corporate-action adjustment** (#1) — small fix, restores trust in
   every downstream result.
2. **xenon OP-1 + SEC-1** (#4) — capital safety; remediation plans already
   written, just unexecuted.
3. **Probe massive.com historical options data** (#2, per operator decision) —
   verify tier/coverage/pricing; if viable, plan Sub-E-via-massive.
4. **Re-measure UW burn under the 120k budget** — confirm a research slice now
   exists; unblocks the parked alpha-probe class of work.
5. **Agentic ops/health agent brainstorm** (§4) — once 1–2 are moving.

#3 (zero promotions) is not attacked directly; it is the dependent variable.

---

## 6. Goal ladder: Stage 1 → 2 → 3 → 4 (adopted 2026-07-12)

Enhancement of the §1 end-state into a staged progression. Each stage has a
theme (what the machine newly owns), entry conditions, and falsifiable exit
criteria. **Invariants at every stage:** defined-risk only / no naked shorts;
every mutating agent action routes through a gate; all results persist to
durable storage; subtraction over addition.

### Stage 1 — Trustworthy foundation ("the desk you thought you already had")

*Machine newly owns: telling the truth.*

- Fix the data substrate: corporate-action adjustment in livewire (real
  `adj_close`), rename map, splits/dividends feed (§2 #1).
- Fix capital safety: xenon OP-1 (UNCERTAIN state + reconciliation), SEC-1
  (auth on order routes), order-path tests back into CI (§2 #4).
- Start options history accrual for real: probe massive.com options data; if
  viable, wire it as Sub-E-substitute; keep argon surface recorder running.
- First harness element: **ops/health patrol agent v1** — read-only sweep
  (argon `/api/health` + freshness, apex CI, livewire incident JSONL, xenon
  order-path canaries), GH-issue writes only. Design by adaptation from radon
  `scripts/watchdog/` + dexter heartbeat/suppression.
- Re-measure UW burn under the 120k budget; carve the research slice.

**Exit criteria:** a multi-year backtest is trustworthy end-to-end (adjusted
prices, PIT, survivorship-aware); an order cannot silently double; a silent
staleness incident is caught by machine before operator; options chains are
accruing from a durable source. **No new features until these hold.**

### Stage 2 — The self-tending desk ("machines own the babysitting and the throughput")

*Machine newly owns: running the research program and maintaining itself.*

- Full agent harness (R1): patrol agent matured; **maintenance agent**
  (PR-only writes — grooms §3 debt table, dead code, stale docs);
  **research-loop agent** (scheduled signal-lab idea triage + study execution;
  statistical gates are the safety rail).
- Execution-realism gate lands in signal-lab's promotion contract (R3):
  truthful fill/latency model — nautilus-as-component via a bridge, or a
  purpose-built simulator validated against xenon's real fills.
- Re-run the study classes that data gaps blocked (options premia, macro
  regime via FRED/massive clients, PIT constituents for survivorship).
- **The first PROMOTE happens** — at least one signal reaches apex or argon
  through the full gated path and accrues a live (paper or shadow) record.

**Exit criteria:** the stack runs unattended for a week (agents file/triage
issues, operator only reviews); research studies execute without operator
initiation; ≥1 promoted signal with a live shadow track record; promotion
contract includes the execution-realism gate. *Honest caveat: the first
PROMOTE cannot be scheduled — edge is found, not built. The stage-2 machinery
maximizes shots on goal; it does not guarantee a goal.*

### Stage 3 — The proposal desk ("agents stage, human disposes" — R2 realized)

*Machine newly owns: composing trades. Human retains: authorizing them.*

- HARD ENTRY CONDITION: Stage 1 xenon safety complete + ≥1 promoted signal
  with months of live shadow record. Not before.
- The apex→xenon **proposal wire** (not execution wire): promoted signals
  auto-compose fully-formed, sized, defined-risk order proposals
  (trading-as-git: staged → reviewed → one-click approved → submitted),
  portfolio-aware (risk budget, existing positions, no-naked-shorts by
  construction).
- Full audit chain: every live trade traces signal → study → promotion →
  proposal → explicit human approval → fill → markout, and markouts feed back
  into the research loop automatically.
- Operator's trade-time role shrinks to review + approve (minutes/day).

**Exit criteria:** ≥90% of trades enter through staged proposals; zero
manual-composition errors class; markout feedback loop closes without manual
steps.

### Stage 4 — Mandate-based autonomy ("the highest coherent direction")

*Machine newly owns: execution within explicit, size-capped mandates. Human
retains: capital allocation, risk appetite, mandates, and taste.*

The honest ceiling is NOT full autonomy — edge scarcity, one-operator scale,
and the entire reference-repo record argue against it. The highest coherent
form is a **mandate system**: after a strategy accrues a long live proposal
track record (Stage 3), the operator may grant it a standing mandate — a
whitelisted structure class, hard size/loss caps, auto-suspend on drawdown or
regime triggers — within which proposals auto-execute; everything outside any
mandate stays proposal-gated forever. Like giving a junior PM a small book:
revocable, bounded, audited. The operator's remaining roles are the ones that
cannot be delegated: how much capital, how much risk, which mandates, and
which new ideas enter the research queue. The desk compounds knowledge
structurally: every fill improves the execution model, every incident hardens
the watchdog, every killed study sharpens triage.

**Exit criteria (deliberately conservative):** ≥1 mandate running ≥6 months
with zero gate breaches and live performance inside its backtested confidence
band; operator time on execution ≈ 0, on mandates/allocation ≈ hours/month.

### Operator calibration (2026-07-12, after ladder review)

- **Execution stages (3–4) are an AIM, not a commitment.** Operator confidence
  in execution automation is low; keep the direction, do not front-load any
  Stage-3/4 work beyond harmless schema prep. Re-evaluate at each stage exit.
- **Stage 1 minimal deliverable = "alert me with signal."** The floor for the
  whole effort: a signal→alert pipeline that pushes to the operator. This is
  buildable now — it does NOT wait for a signal-lab PROMOTE, because the
  **alert bar is lower than the trade bar**: alerts are decision support for a
  human who disposes, so display-only and contextual signals qualify.
  Candidate first alerts, in order:
  1. **VRP macro short-vol state flip** (`/api/regime/vrp-macro-signal` +
     `/live`) — the closest-to-validated signal in the stack (Sharpe ~1.65
     in-harness, PR #150); alert on entry-state transitions.
  2. **Regime transitions** — CRI/VCG state changes (esp. VCG PANIC/dip-buy
     trigger, documented as descriptive-not-predictive → fine for an alert).
  3. **Ops/staleness** (the patrol agent's output — same channel).
  4. signal-lab display-only verdict landings (e.g. SEPA-class findings).
  Channel: argon already has `UW_SCAN_OPS_ALERT_WEBHOOK_URL` plumbing; radon's
  `scripts/alerts/evaluate.py` (Pushover/Discord rules engine) is the R3
  port-idea and the natural shape for user-configurable rules.
- **Acknowledged: the signal is really difficult to find.** Consistent with
  the 0-promotion record (§2 #3). Consequences for search strategy: (a) the
  execution-realism gate makes the search *honest*, not easier; (b) tilt
  research toward the structural-advantage surface (options/vol/flow — UW +
  GEX + VRP — thinner crowd, proprietary-ish data) and away from daily equity
  technicals, where 14 studies died on well-trodden ground; (c) accept that
  alert-grade signals (regime, VRP-z context) deliver operator value while
  trade-grade edge is hunted.

### Stage mapping of current work

| Current item | Stage |
|---|---|
| adj_close fix, xenon OP-1/SEC-1, massive options probe, ops agent v1, UW re-measure | 1 |
| FRED/massive clients, PIT constituents, execution-realism gate, maintenance+research agents, AI-worker rebuild (#248) | 2 |
| apex→xenon proposal wire, trading-as-git surface, portfolio-aware sizing | 3 |
| Mandate framework, auto-suspend machinery | 4 |

Sequencing rule: a stage's exit criteria gate the next stage's *risk-bearing*
items; harmless prep (e.g. designing the proposal schema during Stage 2) may
run ahead.
