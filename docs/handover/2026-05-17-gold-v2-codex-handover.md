# Handover: GOLD v2 — research & deferred-source re-wires

**To:** Codex CLI (next agent on the gold workstream).
**From:** Claude Code, end of Phase A1 (2026-05-17).
**Goal:** Pick up GOLD where A1 left off — re-wire the five deferred ingest sources and start the deferred research items, without re-discovering the failure modes A1 already documented.

---

## What you're inheriting

A **shipped** Phase A1 of the GOLD COMPASS five-tier cockpit:

- 7 schema tables + 1 extension migration (`src/uw_scan/storage/migrations/037_*.sql` … `044_*.sql`)
- 8 ingestion clients in `src/uw_scan/sources/{fred,gpr,lbma,etf_holdings,comex,cftc_cot,wgc_cb,uw_gold_options}.py`
- 3 lens computers + correlation gauge (`src/uw_scan/cards/{structural_flow,cyclical_zones,valuation,regime_gauge}.py`)
- Orchestrator (`src/uw_scan/reports/gold_posture.py`) → persists `gold_posture_daily` row per day
- API: 5 read-only endpoints under `/api/gold/*` (`src/uw_scan/api/routers/gold.py`)
- Worker: 10 APScheduler jobs in `src/uw_scan/worker/jobs/gold_jobs.py`; one-shot warmup CLI at `src/uw_scan/worker/gold_warmup.py`
- Web: five-tier cockpit at `/gold` (`web/app/gold/page.tsx` + `web/components/gold/**`)
- Sidebar nav entry; Playwright e2e; posture-language lint

**It runs end-to-end against live data.** Today's payload at `GET /api/gold/state` returns real values for spot, gauge (PARTIAL), Lens 2 cyclical (DXY, GPR, DFII10, T5YIFR, CPI YoY all populated), Lens 3 valuation (real-price + Gold/M2 percentiles). Lens 1 structural is partial — see deferred sources below.

**It also documents what's broken and why.** That's the most important thing you're inheriting. Five of the eight anonymous-CSV sources moved or paywalled between the catalog (April 2026) and the implementation (May 2026). Each failure mode has a concrete re-wire path. Read them before writing any code.

**2026-05-18 update:** read `docs/research/gold-sdf-framework/14-data-quality-remediation.md` before executing this handoff literally. GLD daily holdings, the WGC monthly ETF corpus, WGC canonicalization, current + 400-day COT ingestion, WGC/IFS CB reserve workbook ingestion, freshness missing-source status, effective-market-date targeting, and replay invalidation have since landed. COMEX remains unresolved.

### Required reading order

1. `CLAUDE.md` and `AGENTS.md` at the repo root — standing rules. The most important ones are restated below but the source of truth lives there.
2. `docs/research/gold-sdf-framework/README.md` — the design brief.
3. `docs/research/gold-sdf-framework/11-deferred-sources-phase-a1.md` — **start here for re-wire work**. Five sources, each with a concrete option list sorted by signal-to-effort.
4. `docs/research/gold-sdf-framework/14-data-quality-remediation.md` — current live data-quality gaps and closure sequence.
5. `docs/research/gold-sdf-framework/10-open-research-questions.md` — open questions Q1–Q29 from the design pass. Several are blocking v2 model work (post-2022 regime statistic replication; embargo calibration; deflated-Sharpe gates).
6. `src/uw_scan/CLAUDE.md`, `src/uw_scan/storage/CLAUDE.md`, `src/uw_scan/worker/CLAUDE.md`, `src/uw_scan/api/CLAUDE.md`, `src/uw_scan/reports/CLAUDE.md`, `src/uw_scan/cards/CLAUDE.md`, `src/uw_scan/sources/CLAUDE.md` — layer-specific rules.

---

## Standing rules you MUST follow

These come from `CLAUDE.md` + `AGENTS.md`. Non-negotiable.

- **uv only.** `uv run pytest`, `uv run ruff`, `uv add <pkg>`. Never bare `python` / `pip` / activated venv.
- **No Yahoo Finance.** Data source priority is IB → UW → FMP → massive (OHLC). Yahoo is banned project-wide.
- **No naked shorts** in any strategy / trade-plan code. Defined-risk only.
- **Persist analytical results to Postgres.** Vol/scan/regime/posture outputs land in tables, never in-memory-only. If you compute it, write it.
- **No secrets to local Codex subprocesses.** Don't pass `UW_SCAN_API_KEY`, `MASSIVE_API_KEY`, DB credentials, or unrelated app secrets to `codex exec`. (Trade Insights AI worker is the canonical example of how to do this safely.)
- **Migrations are idempotent.** `IF NOT EXISTS`, `ON CONFLICT DO NOTHING`, `ADD COLUMN IF NOT EXISTS`. No tracking table — re-running is a no-op.
- **Never commit without an explicit user request.** Draft first, wait.
- **Always open a PR before merging to main.** `git push origin main` is forbidden. Push branch → `gh pr create` → let CI run → merge.
- **Never add `Co-Authored-By: Claude` / `Generated-By:` / `Assisted-By:` trailers** to commit messages.
- **Module size budget**: target <500 lines per Python file; at 1000+ lines stop adding methods and propose a split first. `repository.py` already 4,840 lines — **do not extend it** for new gold work. New persistence domains go in `src/uw_scan/storage/gold_<domain>_repository.py` or as a `_GoldXxxMixin` per the PR-1 split pattern (see `src/uw_scan/storage/CLAUDE.md`'s Mixin section).
- **Posture language is locked.** No "buy" / "sell" / "position size" / "predicted return" in any gold-page user-facing text. `web/lib/posture-lint.ts` and the Playwright check enforce this. v1 uses **posture / risk / scenario** language only.
- **AGENTS.md must stay in sync with CLAUDE.md** when policy changes.

---

## Re-wire deferred sources (prioritised, with concrete next-actions)

Full context lives in `docs/research/gold-sdf-framework/11-deferred-sources-phase-a1.md`. The order below is **strict** — D4 first, D3 last. The signal-to-effort math is in the research note.

### D4 — CFTC COT (Commitments of Traders)

**Status:** Closed in the 2026-05-18 remediation. The provider now uses the CFTC current disaggregated futures-only file for current fallback and the official Socrata dataset for 400-day history; the local DB has 57 distinct observations and the latest posture row writes `cot_mm_4w_change_sigma`.

**Why it was first:** Highest signal-to-effort. Codex's own 2026-05-16 review (`docs/reviews/2026-05-16-gold-research-codex-review.md` finding #8) called this out as the largest single factor class missing from the design.

**Path:** Switch to the official Socrata API at `publicreporting.cftc.gov`. Commodity code for gold is **088691** (verify against the Socrata schema). The JSON shape maps directly to the existing `CotRow` dataclass.

**Closed tasks:**
1. `src/uw_scan/sources/cftc_cot.py` fetches Socrata JSON when `start=` is supplied and keeps the existing `CotRow` shape.
2. `tests/unit/sources/test_cftc_cot.py` covers Socrata history, current flat-file parsing, and non-gold filtering.
3. Live `gold_cftc_cot_ingest_job` populated COT rows for gold, not rates/equities.
4. Orchestrator now computes and persists `cot_mm_4w_change_sigma`.

**Success criteria:** Lens 1 `cot_mm_net_pct` is non-null on `/api/gold/state`; integration test passes against the fresh DB; `gold_posture_daily.cot_mm_4w_change_sigma` is written.

---

### D1 — WGC CB reserves (Central Bank holdings)

**Why second:** The largest physical-flow contributor to Lens 1, dominant in the post-2022 regime-break thesis. The anonymous Goldhub CSV endpoint moved behind login on 2026-05-17.

**2026-05-18 status:** resolved via WGC Goldhub authenticated workbook parsing. `src/uw_scan/sources/wgc_cb.py` now parses `Quarterly_gold_and_FX_Reserves_Q1_2026.xlsx`; `gold_wgc_cb_ingest_job` accepts `WGC_CB_RESERVES_WORKBOOK_PATH` or `WGC_GOLDHUB_COOKIE`; local `cb_gold_reserves_monthly` has 2,827 rows for 27 mapped bucket countries.

**Remaining optional task:** evaluate direct IMF IFS later if Goldhub auth becomes operationally fragile.

**Success criteria:** Lens 1 `cb_strategic_12m_sum_t` is non-null on `/api/gold/state`. Russia post-2022 estimation + China under-reporting caveats remain documented per `09-data-sources-catalog.md`.

---

### D2 — ETF holdings and WGC canonicalization

**Why third:** Half of the Lens 1 dual-axis chart plus the new WGC global breadth corpus. GLD daily holdings now populate, but WGC monthly rows are revision-preserving and need a canonical consumer view before they become production factors.

**Path:** Keep SPDR historical archive as canonical GLD daily holdings. Add a canonical WGC latest-revision query/view for monthly global/regional ETF breadth. Keep SEC N-PORT as the open-data fallback for non-GLD funds if Goldhub auth/export becomes brittle.

**Concrete tasks:**
1. Add a canonical WGC query/view: latest revision per `(ticker, obs_date)`.
2. Build global/regional ETF breadth metrics only from that canonical surface.
3. Keep SPDR GLD daily holdings as the daily high-frequency proxy.
4. Add SEC N-PORT fallback for non-GLD funds only if authenticated WGC operations fail.

**Success criteria:** Lens 1 `gld_holdings_t` remains non-null; WGC monthly consumers use canonical month counts rather than raw revision counts; global/regional breadth fields can be reproduced deterministically.

---

### D5 — XAU spot (LBMA fix or equivalent)

**Why fourth:** Display-only. The KPI tile currently shows GLD ETF (~$417) labelled honestly as "GLD ETF · USD". Nothing downstream depends on raw XAU — GLD close feeds the correlation gauge, valuation, and chart. This is purely a label-honesty upgrade.

**Path:** Try massive feed for `XAU=` synthetic first (cheapest if it works). Second choice: derive XAU from GLD using the trust ratio (~0.0931 oz/share, drifts slowly with trust expenses). Last resort: OANDA / fxcm forex feed.

**Concrete tasks:**
1. Test whether `MassiveOhlcProvider` (`src/uw_scan/sources/ohlc.py`) returns data for ticker `XAU=` or `GC=F`.
2. If yes, add a `gold_xau_spot_ingest_job` that writes to `macro_series_daily` under a new `series_id="XAU_USD_OZ"`.
3. Update `src/uw_scan/reports/gold_posture.py` `_spot_from_gold_rows` to prefer XAU over GLD when both are present.
4. Update `web/components/gold/kpi/SpotPriceCard.tsx` label back to "XAU / USD" once the orchestrator actually emits XAU.

**Success criteria:** KPI tile shows real LBMA fix or near-equivalent at ~$3,500–$4,000 range; tile label matches the data.

---

### D3 — COMEX vault inventory

**Why fifth:** Only re-wire if calibration shows it materially moves Lens 1 R² (>2% delta). Non-blocking.

**Path:** Playwright against the CME page (the 403 is likely a UA + JS-challenge wall, not a paywall). If that's operationally too heavy, drop COMEX from the Lens 1 composite entirely — the lens still works without it.

**Concrete tasks (conditional):**
1. First: run a Lens 1 calibration with COMEX field omitted. If R² impact < 2%, skip the re-wire.
2. If R² impact ≥ 2%: replace `src/uw_scan/sources/comex.py`'s `httpx.get` with Playwright headless invocation. Existing parsing logic is fine.

**Success criteria:** Either Lens 1 R² calibration shows COMEX is non-load-bearing (and the source is officially dropped), or a Playwright path lands and `comex_registered_oz` populates.

---

### D6 — Remaining ETFs (IAU / GLDM / PHYS)

**Why last:** Diminishing returns after GLD. Useful for cross-checking GLD signal robustness, not for new information.

**Path:** SEC N-PORT only (monthly cadence). Reuse the N-PORT parser from D2a.

---

## Open research questions (separate from re-wire work)

`docs/research/gold-sdf-framework/10-open-research-questions.md` has 24 open questions. The ones blocking v2 model work:

- **Q20** — Internal replication of the post-2022 regime-break correlation statistic. Currently a directional claim; v2 sizing logic cannot use it as a measurement until replicated. The data is in the DB now (5y FRED backfill landed in Phase A1) — this is a notebook-able analysis.
- **Q23** — Variance accounting across the three lenses. They share variance (CB flow overlaps with GPR + DXY; valuation is endogenous to flow). v1 acknowledges this; v2 sizing logic needs the actual covariance matrix.
- **Q18** — Embargo calibration for backtests. Currently `max(10, 0.25 × horizon)` as a default; needs empirical tuning.
- **Q14** — Validation basket (deflated Sharpe, PBO, regime-conditional, benchmark-relative, turnover-adjusted, calibration). Need concrete thresholds before any backtest result is publishable.
- **Q11** — Point-in-time CPI vintages (FRED ALFRED). If the regime classifier triggers on CPI, backtests need PIT not current-revised CPI.
- **Q15 / R5** — XGBoost as a challenger model behind state-space (Codex finding #4 corrected the multi-task claim).

**Concrete tasks:**
- Pick Q20 first — it's data-ready, it's foundational to the design narrative, and the answer informs which lenses get position weight in v2.
- Treat each Q as a research note under `docs/research/gold-sdf-framework/` (next free chapter number after 11). One Q per chapter — don't bundle.

---

## Repository hygiene follow-ups

### Repository.py split (PR-2 / PR-3)

A worktree at `~/projects/unusual-whales/.claude/worktrees/refactor+repo-split-pr2` is already set up for the next split chunk. PR #38 landed PR-1 (leaf modules: audit, flow, health, jobs, market_data, scan_outputs). The 23 gold methods Phase A1 added live in the legacy section of `repository.py` and are flagged for migration into a `_GoldMixin` (or split per domain — gold_macro / gold_etf / gold_inventory / gold_cb / gold_cot / gold_uw_options / gold_posture).

When you migrate gold methods, follow `src/uw_scan/storage/CLAUDE.md`'s mixin pattern:

- One mixin class per file
- `from __future__ import annotations` at top
- No `__init__` on domain mixins — `_BaseMixin` owns it
- Type hints for `self._conn` and `self._schema` as class-level annotations
- Backward-compat: existing callers' `from uw_scan.storage.repository import X` paths MUST keep working — re-export from `repository.py`

### Orchestrator field mapping

The 044 migration added 11 columns that are currently populated by the orchestrator. If you add new lens fields, follow the same flow:

1. Add column in a new migration (`045_*.sql`, `ADD COLUMN IF NOT EXISTS`).
2. Extend `Repository.insert_gold_posture_daily` signature (until gold methods move out of `repository.py`).
3. Compute in `src/uw_scan/reports/gold_posture.py`; pass to insert.
4. Read in `src/uw_scan/api/routers/gold.py` `_state_from_row`; map to the appropriate Pydantic model field.
5. Regenerate types: `cd web && npm run gen:types` (FastAPI must be running at `127.0.0.1:8400`).
6. Surface in the relevant `web/components/gold/**` tile.

### Lookback knobs

`gold_fred_ingest_job` and `gold_gpr_ingest_job` now take `lookback_days` (default 45 for daily refresh). Warmup CLI overrides to 1825 for 5y backfill. If you add a new daily-cadence ingest job, mirror this convention so warmup can pull deep history without bloating daily ingest cost.

---

## Tools, commands, gotchas

```bash
# Sync deps (run once after pulling)
uv sync --extra postgres

# Apply migrations (idempotent — re-running is a no-op)
bash scripts/migrate.sh

# One-shot warmup (runs all ingest jobs + posture compute against live data)
uv run python -m uw_scan.worker.gold_warmup

# Tests
uv run pytest                           # full suite (~3.5 min)
uv run pytest tests/unit/cards/         # unit only
uv run pytest -m live                   # live API tests (needs UW_SCAN_API_KEY)

# Lint
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src

# Web
cd web && npm install
cd web && npm run dev                   # next dev on :3001
cd web && npm run gen:types             # regen lib/types.ts (API must be at :8400)
cd web && npx playwright test           # e2e

# Local dev (all three processes)
bash scripts/dev.sh                     # web + api + workers
```

**CI gotchas (learned in PR #40):**
- Ruff's F401 catches unused imports — `uv run ruff check src/ tests/ scripts/ --fix` before pushing.
- `scripts/_lint_except.py` (Guardrail 2) requires every `except` block to either `logging.exception(...)`, reference `repr(exc)`, reference `traceback`, or `raise`. Pattern: `except (X, Y) as exc:` → `logger.debug("…: %s", repr(exc))`. Established pattern lives in `src/uw_scan/cards/vol_series.py`.
- Two extra CI grep guardrails: no `_FakeCursor/_FakeConnection` in `tests/integration/`; no `from tests` imports in `src/`.

**Worktree hygiene:** Work in a fresh worktree per major task. The base repo at `~/projects/unusual-whales` is on `main` — don't develop there directly. Create a worktree: `git worktree add .claude/worktrees/<task-name> -b <branch-name>`.

---

## Success criteria for the v2 milestone

By the time GOLD v2 ships, the following should be true:

1. **All required Lens 1 fields populated or explicitly waived** (CB reserves, ETF holdings, COT, UW skew semantics; COMEX either populated or formally dropped from the required gate after calibration).
2. **Correlation gauge state and structural chip are honest**: gauge state reflects the measured GLD/DFII10 regime; structural chip no longer degrades solely because optional COMEX is absent. D4 + D1 are required for the structural anchor, not necessarily for the gauge math.
3. **Q20 replicated** with a published numeric result + dated reference range. Replaces the "directional claim from RBC" placeholder.
4. **Backtest validation basket** (Q14) has concrete thresholds documented; first backtest run lands with all metrics computed.
5. **Repository split PR-2/PR-3 merged** — `repository.py` back under 1000 lines; new gold methods live in `storage/gold_*_repository.py` or `_GoldMixin`s.
6. **No posture-language regressions.** Playwright + posture-lint stay green.

---

## What NOT to do

- **Don't extend `src/uw_scan/storage/repository.py`.** That's already over budget. New gold persistence methods → new module per the mixin pattern.
- **Don't add new "posture sizing" language** anywhere in the UI. v1 is intentionally informational. v2 sizing is gated on Q14/Q23 being resolved.
- **Don't bundle re-wire work with model work.** D4/D1/D2a are infrastructure; Q20/Q14 are research. Separate PRs.
- **Don't reuse the WGC code path for IMF IFS.** Different schema, different auth story, different cadence — give it a clean module.
- **Don't merge to main with anonymous fallbacks for sources that are documented as moved.** If WGC anonymous is gone, the v2 fix is IMF IFS — not a Wayback Machine scrape, not a third-party aggregator.
- **Don't add a Yahoo Finance fallback.** Project rule — also surfaced in `CLAUDE.md`. There is no situation in this project where Yahoo is correct.
- **Don't commit `Co-Authored-By: Claude/Codex` trailers.** Write commit messages as if the user authored them.

---

## Quick orientation map

| If you need… | Look at |
|---|---|
| What's deferred + how to re-wire | `docs/research/gold-sdf-framework/11-deferred-sources-phase-a1.md` |
| What's still unresolved (research) | `docs/research/gold-sdf-framework/10-open-research-questions.md` |
| Design intent | `docs/research/gold-sdf-framework/README.md` + chapters 01–09 |
| API surface | `src/uw_scan/api/routers/gold.py` |
| Orchestrator (where new fields land) | `src/uw_scan/reports/gold_posture.py` |
| Persistence (current location of gold methods) | `src/uw_scan/storage/repository.py` (will move during PR-2/3) |
| Ingest jobs | `src/uw_scan/worker/jobs/gold_jobs.py` |
| Warmup CLI | `src/uw_scan/worker/gold_warmup.py` |
| Lens computers | `src/uw_scan/cards/{structural_flow,cyclical_zones,valuation,regime_gauge}.py` |
| UI tiles | `web/components/gold/{kpi,lens1,lens2,lens3,decomposition,correlation,chips}/` |
| Schema | `src/uw_scan/storage/migrations/037_*.sql` … `044_*.sql` |
| Project rules | `CLAUDE.md`, `AGENTS.md` (must stay in sync), per-layer `CLAUDE.md` files |

---

## First-day suggested actions

1. Read everything in the "Required reading order" above (60–90 min).
2. Run `bash scripts/migrate.sh` then `uv run python -m uw_scan.worker.gold_warmup` against your local DB — confirm `/api/gold/state` returns populated data exactly as A1 left it.
3. Pick D1 (central-bank reserves via IMF IFS) or COMEX depending on signal priority; D4 CFTC COT is already closed.
4. After D1/COMEX source decisions, do Q20 (post-2022 regime statistic replication) as a notebook + research note. That's the smallest research item with the highest leverage on the rest of the work.

Good luck. The infrastructure is solid — the failures are external, documented, and have concrete fixes.
