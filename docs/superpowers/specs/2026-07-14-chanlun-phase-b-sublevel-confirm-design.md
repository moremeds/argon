# Chanlun Phase B — 区间套 sub-level fast-confirm (server-side lifecycle engine)

**Date:** 2026-07-14 · **Status:** approved design (user sign-off 2026-07-14)
**Prereqs:** Chanlun v2 merged (PR #279 @7a7fb72). Research basis:
`docs/research/2026-07-14-chanlun-signal-lifecycle/` (README + probes + the four
phase-B supporting docs `phaseb_*.md`). Port requirements:
`docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md` (1,646 lines).

## Problem

Daily chanlun marks (笔 vertices, 买卖点, 背离) confirm natively only when the next
opposite stroke endpoint forms — median **8 daily bars** after the marked extreme.
Too slow for alerting. The measured daily-only shortcuts are inadequate: survival
to final confirmation at k=1 bar standing is 19–35%. The only honest fast path is
区间套: confirm the daily turn from completed **30m sub-level structure**.

## Decisions locked (user, 2026-07-14)

1. **Sub-level timeframe: 30m** (textbook 次级别 of daily; ~13 RTH bars/day; apex
   serves ~5.1y history).
2. **Scope: backend + validation probe only.** No UI, no alert emission. The
   Postgres event log is the future alert pipeline's input.
3. **Acceptance gate: ≥70% survival** (sub-level-confirmed → eventually
   native-confirmed), per category — plus breach ≤15% and median latency ≤2
   trading days (see §Validation).

## Architecture

Five new pieces inside argon, all following the patterns inventoried in
`phaseb_backend_patterns.md`:

```
apex REST :8322 (1d + 30m bars, single source)
        │  sources/apex.py (extended: fetch_bars)
        ▼
src/uw_scan/chanlun/          ← Python port of web/lib/chanlun.ts (+ chanlunSeg.ts)
        │  computeChanlunFull parity with TS golden fixture
        ▼
src/uw_scan/chanlun/lifecycle.py   ← state machine + S1 predicate (pure functions)
        │
        ▼
worker job chanlun_lifecycle_scan (nightly)
        │  storage/chanlun_signal_repository.py → uw_scan.chanlun_signal_events (migration 107)
        ▼
GET /api/stock/{ticker}/chanlun/lifecycle   (read-only)

scripts/research/chanlun_sublevel_probe.py  ← walk-forward validation (gates promotion)
```

## Data source: apex, single-source for BOTH timeframes

- The engine fetches **1d and 30m bars from apex** (`GET /bars/{ticker}?timeframe=`,
  contract verbatim in `phaseb_apex_bars_contract.md`). It does **not** use argon's
  `daily_ohlc` warm store. Rationale: exact-extreme anchoring (below) requires the
  daily low to literally be a 30m low of the same session — guaranteed only when
  both series share one store and adjustment basis (livewire bronze).
- Client: extend the existing `src/uw_scan/sources/apex.py` (never-raise httpx,
  `APEX_API_URL` env; mini default `http://127.0.0.1:8322`, MacBook dev
  `http://100.66.147.98:8322` over Tailscale).
- **Known gotcha (live-verified):** the endpoint's default `limit` window can
  return `count: 0` for a valid ticker whose latest bar predates the default
  lookback. The client must always pass an explicit `start` (and generous
  `limit`) — never rely on defaults. Unknown ticker → HTTP 200 with empty
  `bars: []`, never 404: empty must be handled as "no data", not success-with-zero.
- Bar timestamps are bar-open, ISO-8601 UTC. 30m bars are session-aligned in
  practice (09:30 ET open lands on a 30m UTC boundary).
- **Consequence accepted:** the web chart overlay computes from argon's massive
  daily bars; the engine computes from apex/livewire daily bars. Marginal
  divergence between the cosmetic overlay and the canonical event log is
  possible and acceptable — the event log is the source of truth for lifecycle
  state and (later) alerts.

## Python port: `src/uw_scan/chanlun/`

- Requirements source: `2026-07-14-chanlun-py-port-contract.md` — every type,
  constant, pipeline stage (16), deliberate textbook deviation (9), numeric
  semantic, and JS→Python trap (12) is specified there with file:line citations
  into `web/lib/chanlun.ts` / `web/lib/chanlunSeg.ts`.
- Module split (each <500 lines per the repo budget): `types.py` (dataclasses),
  `core.py` (inclusion merge → fractals → endpoints → MACD → legs → pivots →
  中枢 + merging), `points.py` (markPoints, markDivergences, markResonance),
  `segments.py` (chanlunSeg.ts port), `full.py` (computeChanlun,
  computeChanlunFull), `lifecycle.py` (Phase B state machine, below).
- **Parity protocol:**
  1. A TS exporter (vitest script committed to `web/`) runs `computeChanlunFull`
     on the existing frozen real-AAPL fixture and writes one golden JSON: the
     input bars + the complete output (vertices, zhongshus, points, divergences,
     segments, all fields), deterministically sorted.
  2. The Python parity test loads the same JSON, runs the port, and asserts
     **field-by-field deep equality** — exact for ints/strings/bools/floats that
     are copies of input values (the contract establishes no arithmetic reaches
     emitted price fields — only max/min/copy), and `abs diff ≤ 1e-9` for the
     secondary MACD-histogram oracle. Byte-level JSON diffing is explicitly
     rejected (JS renders `196` where Python renders `196.0`).
  3. Staged per-stage parity tests (merged candles → fractals → endpoints → …)
     so a divergence localizes to one stage instead of failing only at the end.
- The port is compute-only: no I/O, no Postgres, no network in `chanlun/` except
  `lifecycle.py`'s callers.

## Lifecycle state machine

Mark identity (stable key):
`mark_id = (ticker, category, kind, extreme_date, extreme_price)`. Endpoint
migration to a more-extreme fractal creates a **new** mark_id; the old one is
observably absent from the recompute (probe-verified: identities never
flip-flop in place).

States and transitions (full rationale in `phaseb_confirm_rule_options.md` §A):

| From | Trigger | To |
|---|---|---|
| — | daily fractal complete at daily close, applicable category | PENDING |
| PENDING | S1 predicate satisfied over anchor window | CONFIRMED_SUBLEVEL |
| PENDING | daily `confirmed=true` fires first | CONFIRMED_NATIVE (terminal) |
| PENDING | mark_id absent from recompute, or a later daily bar prints a more-extreme same-direction extreme | INVALIDATED (terminal) |
| PENDING | staleness: >20 sessions without any confirm | INVALIDATED (terminal) |
| CONFIRMED_SUBLEVEL | daily `confirmed=true` fires later | CONFIRMED_NATIVE (terminal) |
| CONFIRMED_SUBLEVEL | later daily bar breaches `extreme_price` (low<P bottom / high>P top) | INVALIDATED — **the one non-monotone edge** |

Positions taken:
- **CONFIRMED_SUBLEVEL is revocable.** The dominant mark-killer (a later
  more-extreme same-direction fractal) is a future daily price event no
  sub-level test can foresee; the breach guard is the honest defense.
  CONFIRMED_NATIVE is terminal (100% retention, 268/268 in the research).
- **Staleness cap = 20 sessions,** price-distance clause dropped (YAGNI; the
  absent-from-recompute trigger already catches endpoint migration).
- **Alert tier deferred** (out of scope). Recommendation recorded for the alert
  pipeline: CONFIRMED_SUBLEVEL = provisional tier (badge), first-class alerts
  reserved for CONFIRMED_NATIVE, revisit after live breach-rate data.

## Confirm rule S1 (v1)

Anchor window `W(mark)`: from the previous confirmed daily vertex of the
opposite kind (start of the leg into the extreme; fallback `extreme_date − 40
sessions`) through the last available 30m close. Mirror image of the shipped
`markResonance` weekly×daily window logic, one level down.

Predicate — upgrade PENDING → CONFIRMED_SUBLEVEL when `computeChanlun(bars_30m
in W)` contains a 30m vertex `v30` with:
1. `v30.confirmed == True` (30m stroke off it earned its opposite endpoint), and
2. `v30.kind == mark.kind` (same side), and
3. `v30` reconciles to the daily extreme: `v30.price == extreme_price` exactly
   (single-source guarantee), with a config tolerance `chanlun_anchor_tol`
   defaulting to 0.0 kept as an escape hatch, and `v30.time ∈ session(extreme_date)`, and
4. no later 30m fractal in W beats `v30.price` on its side.

Evaluation cadence: nightly batch (one windowed 30m compute per ticker,
reused across that ticker's pending marks). The predicate is cadence-independent;
an intraday upgrade later only advances "last available 30m close".

S2 (require a same-side 30m 背驰 at `v30` in addition) is the designed
escalation — a strict tightening of S1, to be enabled per-category if the probe
shows S1's breach rate above gate. Not built in v1 beyond keeping the predicate
factored so the extra conjunct is a flag.

**Category scope v1:** vertices, 背离, 3B/3S get sub-level promotion (all 100%
natively reliable). **1B/1S** (native retraction 71.4%) and **2B/2S** (0/20
native — daily-level defect): event rows are still recorded but their lifecycle
is PENDING → {CONFIRMED_NATIVE | INVALIDATED} only, never sub-level-promoted.

**Split-boundary guard:** livewire bars are not reliably corporate-action
adjusted (known stack blocker). The engine flags a boundary when
`|ln(open_d / close_{d-1})| > ln(1.5)` on the daily series; any mark whose
anchor window or breach evaluation crosses a flagged date is terminally
INVALIDATED with `reason='split_boundary'` (conservative; rare). The probe
excludes these from metrics and reports their count. Revisit when livewire
ships trustworthy adjusted bars.

## Storage: `uw_scan.chanlun_signal_events` (migration 107)

Append-mostly event log, one row per (mark_id, state) transition:

- Columns: `id bigserial PK`, `ticker text`, `category text` (vertex | point |
  divergence), `kind text` (top/bottom for vertices and divergences; 1B/1S/2B/2S/3B/3S for points — exact
  values per the port contract's type inventory),
  `extreme_date date`, `extreme_price double precision`, `state text`
  (pending | confirmed_sublevel | confirmed_native | invalidated),
  `reason text NULL` (breach | superseded | stale | split_boundary — for
  invalidated), `first_entered_at timestamptz` (never overwritten on re-run),
  `as_of date` (the session the transition was derived from),
  `details_jsonb jsonb` (v30 anchor info, window bounds).
- `UNIQUE (ticker, category, kind, extreme_date, extreme_price, state)` —
  upserts are `ON CONFLICT DO NOTHING`, making the nightly batch idempotent
  (state is a pure function of the bar series; re-runs are no-ops).
- Current state of a mark = its row with the latest state precedence
  (terminal > sublevel > pending); exposed via repository query, not a DB view.
- New standalone module `storage/chanlun_signal_repository.py` — never extends
  `repository.py`.
- **CI gates (required in the same PR):** a `DatasetRegistryEntry` for the new
  temporal table (`audit_mode="provenance"`, following `watchlist_ticker_events`)
  plus the regenerated `docs/runbooks/data-gap-dataset-policy.md`.

## Worker job: `chanlun_lifecycle_scan`

- Nightly, **03:10 ET Tue–Sat**, pinned to the massive-0 worker (zero UW-budget
  usage; apex is the only upstream). Rationale: livewire's intraday catch-up
  runs 05:00 UTC (= 00:00/01:00 ET), so session *d*'s 30m bars are on disk
  before the job runs, and results are ready well before the 09:30 ET open.
- Per watchlist ticker: fetch 1d (1,300 sessions — the research replay basis) +
  30m (anchor windows only) from apex → daily `computeChanlunFull` → derive
  every live mark's state → upsert transitions. Per-ticker try/except with
  rollback; returns a summary dict (jobs framework logs it; global APScheduler
  listener already records failures to `job_failures`).
- Config (all via `Settings.from_env()` — bare `Settings()` is env-blind):
  `chanlun_lifecycle_enabled` (default **false**), `chanlun_anchor_tol`
  (default 0.0), `chanlun_stale_sessions` (default 20). Worker env freezes at
  fork — rotating any of these needs a worker restart.

## API

`GET /api/stock/{ticker}/chanlun/lifecycle` — read-only, returns every recorded
mark's current state for the ticker (mark_id fields + state + reason +
`first_entered_at` + `as_of`), excluding marks whose current state is
`invalidated` with `reason='stale'` (noise). Full per-state history stays in the
event log; the API surfaces current state only in v1. Pydantic response models in `src/uw_scan/models/`
(with `_preserve_public_module()`), router in `api/routers/stock.py`, and the
web types updated **surgically** (`web/lib/types.ts` and the OpenAPI snapshot
are frozen-format generated files — never full `gen:types` regen).

## Validation probe (ships in the same PR; gates promotion)

`scripts/research/chanlun_sublevel_probe.py` (uv run), walk-forward prefix
replay over two timeframes, per the protocol in
`phaseb_confirm_rule_options.md` §D:

- **Data:** ≥10 liquid names — AAPL, NVDA, MSFT, AMZN, META, GOOGL, TSLA, AMD,
  SPY, QQQ — full ~5.1y of 30m + 1d bars from apex. No synthetic bars.
- **Metrics, per category and pooled:** (1) sub-level survival → native;
  (2) breach rate; (3) median confirm latency (sessions from PENDING);
  (4) median lead over native confirmation.
- **Gates (per category, per ticker-half — AC-F4-style catastrophic gate; a
  category failing in EITHER half is excluded, never pooled-averaged):**
  survival ≥ **70%**, breach ≤ **15%**, median latency ≤ **2** sessions.
- **Outcome wiring:** categories passing the gate are listed in the shipped
  default of `chanlun_promotable_categories` (config); failing categories stay
  recorded-but-never-promoted. The engine merges either way — the gate governs
  the signal's trust tier, not the code.
- **Persistence (standing rule):** the full per-mark_id trace (every mark ×
  every prefix transition) is written as a committed artifact under
  `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/` (parquet or
  csv + summary markdown) including the exact reproduce command. stdout-only is
  data loss.

## Verification regime (implementer is a non-Fable model)

- TDD everywhere; every plan task carries exact commands + expected output.
- Golden-fixture parity (above) with staged per-stage localization.
- **Non-vacuity is mandatory on every real-data test**: any test asserting over
  marks/vertices/events must first assert the collection is non-empty (the v2
  lesson: oracles that pass on zero marks are worthless).
- Each of the port contract's 12 JS→Python traps gets a dedicated regression
  test (worst: `getUTCDay()` Sun=0 vs Python `weekday()` Mon=0).
- State-machine tests: one synthetic bar-series fixture per transition edge
  (including the breach demotion and split_boundary), plus a frozen real-ticker
  fixture (real prices, as-of dated) exercising the full nightly path
  API→DB→worker→DB per the smoke-test rule.
- Integration tests use the existing pytest-postgresql fixtures
  (migrate-once + per-test truncate).
- CI must stay green on the two dataset-registry gates (registry entry +
  regenerated policy doc).

## Non-goals (v1)

UI lifecycle badges, alert emission, intraday (30m-close) evaluation cadence,
S2/S3 predicates (flag-factored only), the 2B/2S daily-definition fix, Phase A
client-side lifecycle, 60m cascade.

## Risks / accepted limitations

- **Unadjusted bars:** split boundaries invalidate marks conservatively rather
  than being handled correctly; bounded by the guard + probe exclusion count.
- **Revocable confirmed tier:** by design; the probe's breach-rate gate bounds
  it, and alert policy (future) must respect the tier split.
- **Engine-vs-overlay divergence:** apex daily bars vs massive daily bars may
  disagree on rare bars; the event log is canonical.
- **apex availability:** the never-raise client degrades to "no data → job
  no-ops for that ticker and reports it"; the job must count and log skipped
  tickers so silent staleness is visible.
