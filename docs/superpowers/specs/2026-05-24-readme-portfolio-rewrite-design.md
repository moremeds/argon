# README portfolio rewrite — design

**Date:** 2026-05-24
**Status:** Design — awaiting user review before implementation plan
**Scope:** Rewrite `README.md` from internal-docs voice into a portfolio-showcase landing page that leads with the Trade Insights AI work landed in [PR #68](https://github.com/moremeds/unusual-whales/pull/68) and the rates dashboard fix in [PR #69](https://github.com/moremeds/unusual-whales/pull/69).

---

## Goals

1. **Portfolio-mode framing.** Reader is a recruiter, peer engineer, or casual viewer landing on the repo. The README is the landing page, not the operations manual.
2. **Story-driven walkthrough.** Follow a single ticker (NVDA) top-to-bottom: dashboard → stock-page tabs → AI panel → outcome ledger. Screenshots inline as the story unfolds.
3. **Trade Insights AI is the headline feature.** Two LLMs (Codex + Claude) reading the same evidence and committing to a falsifiable, scored swing thesis is the distinctive thing this repo does. It needs to be the climax of the walkthrough, not a footnote.
4. **Setup stays compact but complete.** Prereqs → env → commands → verify. ~25 lines. No troubleshooting section.
5. **Voice has personality.** Opinionated where it earns it ("chart libraries always lie about gamma", "by the time you've stitched five tabs into one mental picture, the setup has either fired or invalidated"). Portfolio mode rewards distinctive voice over corporate-neutral.

## Non-goals

- Full contributor onboarding (CLAUDE.md files own that).
- Per-source data-quality docs (`src/uw_scan/sources/CLAUDE.md` owns that).
- Per-layer architecture docs (subdirectory CLAUDE.md files own that).
- Troubleshooting / common gotchas.
- Mention of predecessor projects (radon).

## Structure (final, 8 sections)

| # | Section | Length | Screenshots |
|---|---|---|---|
| 1 | Hero — title, tagline, full-width banner, tech-stack chips | ~10 lines | 1 existing (`dashboard.png`) |
| 2 | The problem — 2-paragraph narrative hook | ~10 lines | 0 |
| 3 | The system, in one breath — 3-layer table + paragraph | ~15 lines | 0 |
| 4 | A walk through NVDA — 7 beats | ~60 lines | 4 existing + **3 NEW** |
| 4.5 | More surfaces — breadth gallery | ~10 lines | **5 NEW** |
| 5 | Under the hood — ASCII pipe + 1 paragraph | ~25 lines | 0 |
| 6 | Run it — compact setup | ~30 lines | 0 |
| 7 | Status & provenance — closer | ~15 lines | 0 |

**Total target length:** ~175 lines (up from 140).
**New screenshots required: 8.**

---

## Section 1 — Hero

```markdown
# Unusual Whales Opportunity Scanner

> A per-ticker options research workstation. Pulls dealer gamma, IV surface,
> dark-pool flow, and macro/rates into Postgres — then has two LLMs read the
> same evidence and write a falsifiable, scored 1-2 week swing thesis.

![dashboard](docs/screenshots/dashboard.png)

`Python 3.13` · `Next.js 16` · `Postgres` · `uv` · `FastAPI` · `APScheduler`
```

**Decisions:**
- Hero image: single full-width (`dashboard.png` reused; the AI panel gets its own dramatic reveal in Section 4 beat 6).
- Tagline does the hook: "two LLMs read the same evidence and write a falsifiable, scored thesis." This is the bait that keeps a reader past the data sections.
- Tech-stack chips are a single line of monospace badges — readable in plain markdown, no shields.io dependency.

## Section 2 — The problem

```markdown
## The problem

Reading raw options flow is a part-time job with full-time stakes. UW prints
land in a firehose. IV surfaces shift intraday. Dealer gamma flips and you
don't notice until price is on the other side of the wall. Macro rates move
and the whole vol complex re-prices. By the time you've stitched five tabs
into one mental picture, the setup has either fired or invalidated.

This is the workstation that does the stitching for you — and then asks two
different LLMs to read the stitched view and commit to a thesis with strikes,
triggers, and an invalidation level. Every thesis is scored against forward
price the next morning, so the system keeps its own report card.
```

**Decisions:**
- Aggressive insider tone approved over neutral.
- Plants two payoffs the AI section cashes: *two LLMs* and *report card*.

## Section 3 — The system, in one breath

```markdown
## The system, in one breath

Three layers, one Postgres, one watchlist:

| Layer | What it does | Where it lives |
|---|---|---|
| **Triage** | Card grid across the watchlist — *is this name worth opening today?* | `/` |
| **Diagnosis** | Per-ticker page with dealer gamma, IV surface, flow, regime tabs | `/stock/<TICKER>` |
| **Thesis & score** | Two LLMs commit to a directional trade. The next morning it's graded against forward price. | `/stock/<TICKER>` → AI panel |

Underneath: sharded APScheduler workers pull UW + massive.com + macro/rates
into `option_wizard.uw_scan`; FastAPI serves it read-only; the web layer is
hand-rolled SVG charts because chart libraries always lie about gamma.
```

**Decisions:**
- Cheeky line ("chart libraries always lie about gamma") kept.
- Three layers map 1:1 to the walkthrough arc (triage → diagnosis → thesis).

## Section 4 — A walk through NVDA (7 beats)

NVDA chosen as the spine because PR #68's smoke test already validated both Codex + Claude converging on it (`thesis_trigger=220, entry_trigger=215, invalidation=220`), so screenshots will look real and the prose can quote real numbers.

Each beat: heading + screenshot reference + 2-4 sentences. Numbered, all under one `## A walk through NVDA` heading.

```markdown
## A walk through NVDA

### 1. The dashboard catches a name
![dashboard](docs/screenshots/dashboard.png)
8:55 AM ET. The grid loads. Most cards look quiet; NVDA's IVR is 78 and the
flow aggression dial is pegged. The setup badge says MOMENTUM.

### 2. The card tells you to keep going
![dashboard card](docs/screenshots/dashboard-card.png)
GEX flip is 30 points above spot. Net DEX is negative. 25Δ skew has flipped
puts-bid. Put/call OI ratio just crossed 1. That's enough signal to open
the page.

### 3. Market Structure — where dealers want price
![market structure](docs/screenshots/stock-market-structure.png)
Spot below flip. Dealers are short gamma. Magnet at 215, put wall at 210,
acceleration zone in between. If price ticks under 215, hedging accelerates
the move down. This is the dealer-flow physics.

### 4. Volatility — is this regime stable?
![volatility](docs/screenshots/stock-volatility.png)
IV is rich vs realized (VRP +6). IV-of-IV is climbing. The regime quadrant
puts today in the "high-IV, low-corr" cell — idiosyncratic, not systematic.
That argues for an NVDA-specific structure rather than a SPY hedge.

### 5. Flow — what's actually printing
![flow tab](docs/screenshots/stock-flow.png)
Three opening prints in the 215P weekly inside the last hour, all at the
ask. That's directional intent, not hedging.

### 6. Trade Insights AI — two models read the evidence
![ai panel](docs/screenshots/stock-ai-panel.png)
Both models picked support_breakdown / SHORT_DELTA / CONDITIONAL. Both
converged on thesis_trigger=220, entry_trigger=215, invalidation=220.
Codex picked a 215/210 bear put spread; Claude picked 215/205. The
disagreement is now bounded — same thesis, different risk appetite.

### 7. The outcome ledger — the report card
![outcome row](docs/screenshots/outcome-row.png)
Tomorrow at 17:00 ET the nightly worker grades this row. It captures
snapshot close + 1d/3d/5d/10d forward closes. If price prints below 215
within the window, entry_trigger.fired flips true. If it tags 220 first,
invalidation fires and the thesis is scored as invalidated. The priors
view aggregates by (provider, archetype, bias) so eventually you'll know
"Claude is +60bps on support_breakdown setups, Codex is flat."
```

**Decisions:**
- All 7 beats kept (no Flow drop).
- Beat 7 screenshot target: outcome row on stock page if UI exists; **must verify during implementation** because PR #68 explicitly defers the *priors* UI. The per-analysis outcome may already render under the AI panel. Fallback: `curl /api/trade-insights/priors` output in a code block.
- Numbers in the prose (IVR 78, GEX flip +30, VRP +6, thesis 220/215/220) are illustrative — they should match whatever the live NVDA screenshots show on capture day, **not** be invented. The implementation plan should call out re-tuning the prose to the actual captured screenshots.

## Section 4.5 — More surfaces

```markdown
## More surfaces

The NVDA walkthrough is one path through one ticker. The system covers more:

| Route | What it is | Screenshot |
|---|---|---|
| `/scanner` | Detector-driven candidate list (DCF / Dark Pool / EIC / GEX). Splits into **watchlist candidates** (full detector suite) and **discovered** tickers from the market-wide flow-alerts feed. | `docs/screenshots/scanner.png` |
| `/regime` | Market-wide indicators — CRI (Crash Risk), VCG (Vol-Curve Gauge), SPX GEX with profile chart, vol-backdrop strip. | `docs/screenshots/regime.png` |
| `/gold` | **GOLD COMPASS** — five-tier cockpit on the gold complex. WGC + ETF flow + dealer positioning. Has `/gold/replay/<YYYY-MM-DD>` for historical days. | `docs/screenshots/gold.png` |
| `/rates` | **US Rates Factor Desk** — live FRED Treasury curve, Cleveland Fed 10Y decomposition, policy path, Treasury supply, CFTC TFF positioning, source freshness. | `docs/screenshots/rates.png` |
| `/cockpit/<TICKER>` | Index-only dealer-state view (SPX / SPY / QQQ / IWM). Tabs: state, dealer, surface, flow-IM, VRP. Optional `?asof=YYYY-MM-DD`. | `docs/screenshots/cockpit.png` |
| `/admin` | Health + scheduler controls. | — |
```

**Decision:** Inline screenshot path in the table is intentional — a follow-on can swap the path for an actual inline image if a screenshot is captured for that surface.

## Section 5 — Under the hood

```markdown
## Under the hood

```
  Unusual Whales API ──┐
  massive.com OHLC ────┤
  FRED / Cleveland Fed ┤
  TreasuryDirect, CFTC ├──→ sharded APScheduler workers
  WGC, LBMA, GPR, ETFs ┤    (UW workers, massive workers, primary worker)
  Fed FOMC, FedWatch ──┘            │
                                    ▼
                          Postgres  option_wizard.uw_scan
                                    │
                                    ▼
                          FastAPI  read-only  :8400
                                    │
                                    ▼
                          Next.js 16  +  React 19  :3001
                                    │
                                    ▼
                          Trade Insights AI workers
                          (ai-codex, ai-claude — provider-pinned)
```

Six dev processes, one database, one schema. Workers are the only writers;
the API is read-only; UI mutations cross through `/api/jobs` and are drained
by the workers' 1-second rescan loop. Per-ticker work uses stable shard
ownership and DB claiming, so two workers never duplicate provider calls.
The AI workers sit on the same Postgres but are provider-pinned —
`TRADE_INSIGHTS_AI_CLAUDE_*` env vars never reach the Codex runner, and
neither runner ever sees `ANTHROPIC_API_KEY` (subscription auth only).
```

**Decisions:**
- ASCII pipe chosen over Mermaid (consistent rendering across GitHub themes + IDE previews + terminals).
- Architecture paragraph leads with engineering invariants (single-writer, stable-shard, provider-pinned) rather than feature lists — these are the things that took the most thought.

## Section 6 — Run it

```markdown
## Run it

**Prereqs:** Postgres 16+, Node 20+, [uv](https://docs.astral.sh/uv/), and
API keys for Unusual Whales, massive.com, and FRED. Optional: Codex CLI
and Claude CLI for Trade Insights AI.

```bash
# 1. install
uv sync --extra postgres
cd web && npm install && cd ..

# 2. configure
cp .env.example .env
# Required: UW_SCAN_API_KEY, MASSIVE_API_KEY, FRED_API_KEY,
#           UW_SCAN_DB_*  (host, port, name, user, password)
# Optional: TRADE_INSIGHTS_AI_*, TRADE_INSIGHTS_AI_CLAUDE_*

# 3. migrate (idempotent — safe to re-run)
bash scripts/migrate.sh

# 4. run the full stack
bash scripts/dev.sh
#   → web      :3001
#   → api      :8400
#   → 2× UW worker, 2× massive worker, 1× primary worker, AI workers
```

Once it's up:

| URL | What it is |
|---|---|
| <http://127.0.0.1:3001> | Web (start at `/`) |
| <http://127.0.0.1:8400/openapi.json> | API contract |
| <http://127.0.0.1:8400/api/health> | Liveness |

**Trade Insights AI auth:** the Claude runner uses your local Claude CLI's
OAuth keychain — the env allow-list strips `ANTHROPIC_API_KEY` so
subscription auth wins. Codex uses your local Codex CLI's signed-in session.
Neither runner sees UW/FMP/massive keys.

**One-shot warmups (optional):**

```bash
uv run python scripts/rates_backfill_once.py --lookback-days 180
uv run python -m uw_scan.worker.gold_warmup
```
```

**Decisions:**
- Postgres / Node version floors are minimums known to work; the implementation plan should verify against `pyproject.toml` / `package.json` / CI before committing the numbers.
- AI auth paragraph kept because subscription-auth-via-OS-keychain is unusual and explaining it earns trust.

## Section 7 — Status & provenance

```markdown
## Status

Active rework (2026-05-12 → present). The current sprint landed the
directional Trade Insights AI contract (v5.3) and the outcome ledger
([PR #68](https://github.com/moremeds/unusual-whales/pull/68)) plus the
rates dashboard freshness fix ([PR #69](https://github.com/moremeds/unusual-whales/pull/69)).

What's deferred:
- Priors aggregation UI (the `/api/trade-insights/priors` endpoint ships
  in PR #68; the dashboard for it is the next follow-on).
- A handful of gold sources (CME COMEX intraday, full LBMA history) are
  best-effort with documented failure modes — see
  `src/uw_scan/sources/CLAUDE.md`.

Specs, plans, and reviews live under [`docs/superpowers/`](docs/superpowers/)
and [`docs/reviews/`](docs/reviews/). Per-layer doctrine
(uv-only, never extend `repository.py`, defined-risk only, no Yahoo fallback)
lives in the `CLAUDE.md` files under each subdirectory.

---

Built with `Python 3.13` · `FastAPI` · `Pydantic v2` · `psycopg 3` ·
`APScheduler` · `Next.js 16` · `React 19` · `TypeScript` · `Vitest` ·
`Playwright` · `pytest` · `uv`.
```

**Decisions:**
- PR #68 and #69 hyperlinked to give the reader a one-click path to the actual work.
- Predecessor project (radon) intentionally not mentioned.
- "What's deferred" section is honest about gaps — counter-signal that this is a real working system, not a demo.

---

## Screenshot capture list

| Filename | Surface | Priority | Notes |
|---|---|---|---|
| `dashboard.png` | `/` (full grid) | exists | reused for hero + beat 1 |
| `dashboard-card.png` | NVDA card zoomed | exists | beat 2 |
| `stock-market-structure.png` | `/stock/NVDA` market-structure tab | exists | beat 3 |
| `stock-volatility.png` | `/stock/NVDA` volatility tab | exists | beat 4 |
| `stock-flow.png` | `/stock/NVDA` flow tab | **NEW — low** | beat 5 |
| `stock-ai-panel.png` | `/stock/NVDA` AI panel, both tabs | **NEW — highest** | beat 6, hero of walkthrough |
| `outcome-row.png` | outcome row on stock page (verify UI exists) | **NEW — high** | beat 7; fallback to priors curl block if UI deferred |
| `rates.png` | `/rates` | **NEW — high** | post-PR #69 |
| `gold.png` | `/gold` | **NEW — medium** | gallery |
| `regime.png` | `/regime` | **NEW — medium** | gallery |
| `cockpit.png` | `/cockpit/SPY` | **NEW — medium** | gallery |
| `scanner.png` | `/scanner` | **NEW — medium** | gallery |

User captures these against real data on a day when the watchlist is active. NVDA is the spine ticker.

## Open items the implementation plan must address

1. **Outcome row UI verification.** Confirm whether `/stock/<TICKER>` actually renders the outcome row from `uw_scan.trade_insight_outcomes` today. If not, beat 7 falls back to a `curl /api/trade-insights/priors` JSON code block.
2. **Re-tune NVDA prose to captured screenshot values.** The illustrative numbers in beats 2-6 (IVR 78, flip +30, VRP +6, 220/215/220) must be replaced with whatever the captured NVDA screenshots actually show. Pure-fiction numbers are off-limits per the no-fabrication rule.
3. **Verify Postgres / Node version floors.** Read `pyproject.toml` and `web/package.json` (and CI configs) before committing "Postgres 16+ / Node 20+" in the prereqs section.
4. **Confirm worker process count in `scripts/dev.sh`.** The "6 dev processes" framing assumes 2 UW + 2 massive + 1 primary + AI workers. Verify the actual script and adjust the count if dev.sh launches a different shape.
5. **Verify the env-var allow-list claim.** "Neither runner sees UW/FMP/massive keys" must be checked against `_runner_child_env` in `src/uw_scan/worker/jobs/trade_insights_ai_runners.py`.

## Implementation surface (not the plan — for context)

Only files touched:
- `README.md` (full rewrite)
- `docs/screenshots/` (8 new PNGs added by user out-of-band)

No code, no config, no schema. This is a docs-only change.
