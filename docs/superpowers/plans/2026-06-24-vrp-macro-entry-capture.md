# VRP Macro Short-Vol — Forward Entry-Capture & Markout Recorder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the real forward NBBO + greeks of the SPX bull-put-spread entry the Macro Short-Vol signal would place — a daily-born, tracked-to-expiry markout dataset — plus a one-click "capture this entry now" button on the regime card.

**Architecture:** A new tracked-entry table pair (`vrp_macro_entry` header + `vrp_macro_entry_quote` time-series). Every trading day an "auto" cohort is born for SPX (the 4 put contracts bracketing the 0.25Δ short and 0.125Δ wing at the ~43-calendar-DTE expiry), resolved against the **UW** option chain. A worker job snapshots every open cohort's 4 legs at **8 marks/day** (10:00–15:00 hourly + 15:55 EOD + 16:10 post-close ET), tapering to EOD-only after 30 calendar days held, until expiry. Each leg is quoted **IB-primary** (xenon `/options/greeks`, true NBBO + greeks), **UW fallback** (delayed NBBO + IV), with greeks **BS-computed** (`vrp_structure`) whenever the source omits them. The regime card gains a right-side strike/ETD preview panel (**served from today's persisted cohort snapshot, no IB, no new UW calls**) and a Capture button (IB, persists a one-shot "button" cohort).

**Tech Stack:** Python 3.13 (`uv`), FastAPI + Pydantic v2, psycopg 3, APScheduler 3 (ET crons), `statistics.NormalDist` BS (no scipy), Next.js 16 + React 19 + Vitest, pytest + pytest-postgresql.

## Global Constraints

- **Data source priority IB → UW** for quotes; **greeks are BS-computed for one-model consistency** (UW's *chains* endpoint does return greeks, but we recompute from the marked IV so IB/UW/preview share one model). **Yahoo is banned.** SPX options are European → BS greeks from the marked IV are exact, not an approximation. **NBBO** (bid/ask) comes from IB; UW's per-strike NBBO is best-effort (chains lacks it; option-contracts is volume-capped).
- **No naked shorts** — the recorded structure is a defined-risk bull put spread (sell 0.25Δ put, buy 0.125Δ wing). This feature records contracts; it never places orders.
- **Preview makes ZERO IB calls and ZERO new persisting UW calls** — it is browser-polled, so it reads today's already-persisted cohort snapshot (+ BS-indicative pre-birth), never a live UW fetch (every `sources/uw.py` call writes an audit row per poll).
- **Snapshot loop is serial** (≤1 in-flight xenon line) with a short per-call timeout → UW fallback. This is the live-gateway guardrail.
- **Persist every quote to Postgres** — the markout series is the durable research artifact (standing rule). Record the reproduce command in the research README.
- **uv only** — `uv run pytest`, never bare `pytest`. **Migrations idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`). **No tracking table.**
- **Exception handlers log `repr(exc)`** (CI Guardrail 2). **Decimal for prices/IV** at the storage boundary (NBBO/IV arrive as decimal strings); BS-computed greeks stay float → NUMERIC (psycopg adapts) — don't manufacture Decimal precision on a float.
- **Module budget < 500 lines/file.** New domain storage goes in its own module (`storage/vrp_macro_entry.py`), never appended to `repository.py` (which is assembly/re-export only).
- **API contract change** → regenerate `web/lib/types.ts` via `cd web && npm run gen:types`; types.ts is alphabetically frozen — let the generator write it, never hand-edit.
- **Never commit without explicit user request.** This plan executes on the existing branch `feat/vrp-macro-signal-live` (PR #169) — additional commits, not a new branch/PR.

## Test harness — real fixtures (no synthetic data)

- BS unit tests assert against **hand-computed** expected values (frozen in the test, tagged in comments), not network calls.
- Storage/worker integration tests use **pytest-postgresql** (`db` fixture) — real schema, `DROP SCHEMA CASCADE` per fixture. No mocked cursors.
  - **MacBook gotcha:** `.env.local` may point pytest at the mini as `argon_app` → `InsufficientPrivilege` on `DROP SCHEMA`. Run integration tests with the forced-local override (`UW_SCAN_DB_HOST=127.0.0.1` + `UW_SCAN_DB_USER`/`UW_SCAN_TEST_DB_NAME` per memory `reference_macbook_integration_tests_need_local_db_env`) so the test DB is `option_wizard_test` locally; shell env wins over `.env.local`.
- Quote-orchestration unit tests **monkeypatch the source fetchers** (xenon / UW) with canned dict payloads shaped like the real responses (`docs/uw-samples/option_contracts.json`) — mocking the transport is expected; feeding fabricated *market values* through a "live" path is not. Use a real SPX strike/expiry shape (e.g. expiry `20260731`, strike `6000`).
- Web: `vi.mock` the preview hook with a realistic payload; assert the rendered strikes/ETD.

## File Structure

```
src/uw_scan/
├── reports/vrp_structure.py            # MODIFY: add bs_gamma / bs_vega / bs_theta
├── reports/vrp_macro_entry.py          # CREATE: resolve_entry_contracts (pure) + quote_leg (source-aware) + preview builder
├── sources/xenon_query.py              # MODIFY: add fetch_ib_option_quote (NBBO + IV + und_spot; greeks are BS-computed)
├── storage/vrp_macro_entry.py          # CREATE: _VrpMacroEntryMixin (insert entry / fetch open / insert quotes / list)
├── storage/repository.py               # MODIFY: mix in _VrpMacroEntryMixin (assembly only)
├── storage/migrations/085_vrp_macro_entry.sql   # CREATE: two tables
├── models/vrp_macro_entry.py           # CREATE: Pydantic contracts (leg / preview / capture / summary)
├── models/__init__.py                  # MODIFY: re-export the new models
├── worker/jobs/vrp_macro_entry.py      # CREATE: vrp_macro_entry_snapshot_once (birth + snapshot, taper)
├── worker/scheduler.py                 # MODIFY: register 8 marks + gate; config flags
├── config.py                           # MODIFY: vrp_macro_entry_* settings
└── api/routers/regime.py               # MODIFY: GET /entry/preview, POST /entry/capture
web/
├── lib/regime/useVrpMacroEntryPreview.ts   # CREATE: preview hook
├── components/regime/MacroShortVolCard.tsx # MODIFY: remove "(gate at 0)"/"stand aside"; add panel + button
└── tests/unit/MacroShortVolCard.test.tsx   # MODIFY: panel + button assertions
docs/
├── research/vrp/README.md              # MODIFY: §entry-capture dataset + reproduce command
└── ... CHANGELOG.md / root CLAUDE.md row
```

Data sourcing (**live-confirmed 2026-06-24**, SPX spot ≈ 7336):
- **Strike discovery + IV + greeks** (auto-birth & preview): UW `get_chains_for_expiry` (`/api/stock/{ticker}/option-chains?expiry=`) returns the **full uncapped chain** — for SPX `2026-08-07` that is 134 put strikes **K=3000..9800** with per-strike **IV + full greeks (delta/gamma/theta/vega/vanna/charm) + last_price + theo**, but **NO bid/ask**. The 0.25Δ short (≈ K7100, iv 0.196) and the 0.125Δ wing (≈ K6800, iv 0.231 — note the put skew, so flat-vol `resolve_entry_contracts` will misplace the wing slightly; record the **realized** delta) are both present. ⚠️ This endpoint is **not yet wired** in `sources/uw.py` — add `fetch_chains_for_expiry` (audit-first, one-fetcher-per-endpoint). `resolve_entry_contracts` snaps the BS target to these listed strikes. OCC format confirmed: `SPXW{YYMMDD}{P|C}{strike*1000:08d}` (e.g. `SPXW260807P07100000`); **SPXW is PM-settled** → the 16:10 post-close mark is valid.
- **Per-leg NBBO (bid/ask) is the scarce field**: UW chains lacks it; `/option-contracts` carries it but is ~500-volume-capped (the low-volume deep wing may fall outside — memory `project_eod_surface_pr145_path_b_fix`). So **xenon/IB is the NBBO source of record**. For the UW NBBO of the **4 chosen legs**, `fetch_option_contracts_by_symbol([the 4 OCC])` is a *by-symbol* lookup — uncapped for known symbols (the 500-cap only bites the ticker-level list), so it returns real bid/ask per leg when UW has quotes, null when it doesn't (deep wing). This is the correct use of by-symbol (it can't *discover* strikes — codex ISSUE-1 — but it *can* quote the 4 known legs). The job assembles each `uw_row` from chains (iv/greeks/last_price) + this by-symbol NBBO; accept null bid/ask, tag it, preview shows last_price/theo when NBBO is absent.
- **Authoritative per-leg quote** (capture & auto snapshots): **xenon `/options/greeks`** primary (true NBBO + greeks) → **UW** fallback (chains: IV + greeks + last_price; NBBO best-effort) → **BS-fill** greeks from the marked IV (one-model consistency; exact for European SPX).
- **Preview indicative quote**: served from today's **already-persisted** auto-cohort snapshot (zero new UW calls, zero writes — a browser-polled `sources/uw.py` fetcher would write an audit+raw row per poll, see Task 7); pre-birth it computes BS-indicative legs off the live signal. **Zero IB.**

---

### Task 1: BS greeks — `bs_gamma` / `bs_vega` / `bs_theta`

**Files:**
- Modify: `src/uw_scan/reports/vrp_structure.py` (after `bs_delta`, ~line 48)
- Test: `tests/unit/test_vrp_structure_greeks.py` (create)

**Interfaces:**
- Consumes: existing `_d1`, `_N` (`NormalDist`) in `vrp_structure.py`.
- Produces:
  - `bs_gamma(S, K, T, r, sigma) -> float` (call==put)
  - `bs_vega(S, K, T, r, sigma) -> float` (per 1.00 vol; call==put)
  - `bs_theta(S, K, T, r, sigma, *, is_call) -> float` (per **year**)
  - All return `0.0` on degenerate `T<=0` or `sigma<=0` (mirrors `bs_delta`).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_vrp_structure_greeks.py
import math
from uw_scan.reports.vrp_structure import bs_gamma, bs_vega, bs_theta

# Frozen reference: S=K=100, T=1, r=0, sigma=0.2 → d1=0.1, N.pdf(0.1)=0.396953  [COMPUTED]
def test_bs_gamma_reference():
    assert math.isclose(bs_gamma(100, 100, 1.0, 0.0, 0.2), 0.0198477, abs_tol=1e-5)

def test_bs_vega_reference():
    assert math.isclose(bs_vega(100, 100, 1.0, 0.0, 0.2), 39.6953, abs_tol=1e-3)

def test_bs_theta_reference():
    # r=0 → call theta == put theta == -(S·pdf·σ)/(2√T) = -3.96953 per year
    assert math.isclose(bs_theta(100, 100, 1.0, 0.0, 0.2, is_call=True), -3.96953, abs_tol=1e-3)
    assert math.isclose(bs_theta(100, 100, 1.0, 0.0, 0.2, is_call=False), -3.96953, abs_tol=1e-3)

def test_degenerate_returns_zero():
    assert bs_gamma(100, 100, 0.0, 0.0, 0.2) == 0.0
    assert bs_vega(100, 100, 1.0, 0.0, 0.0) == 0.0
    assert bs_theta(100, 100, -1.0, 0.0, 0.2, is_call=True) == 0.0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_vrp_structure_greeks.py -q`
Expected: FAIL — `ImportError: cannot import name 'bs_gamma'`.

- [ ] **Step 3: Implement** (insert after `bs_delta`, before `strike_for_delta`)

```python
def bs_gamma(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """d²price/dS² (call==put). Degenerate (T<=0 or sigma<=0) → 0."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return _N.pdf(d1) / (S * sigma * math.sqrt(T))


def bs_vega(S: float, K: float, T: float, r: float, sigma: float) -> float:
    """dprice/dsigma per 1.00 vol (call==put). Divide by 100 for per-1%."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    return S * _N.pdf(d1) * math.sqrt(T)


def bs_theta(S: float, K: float, T: float, r: float, sigma: float, *, is_call: bool) -> float:
    """dprice/dt per YEAR (negative for long options). Divide by 365 for per-day."""
    if T <= 0 or sigma <= 0 or S <= 0:
        return 0.0
    d1 = _d1(S, K, T, r, sigma)
    d2 = d1 - sigma * math.sqrt(T)
    term1 = -(S * _N.pdf(d1) * sigma) / (2.0 * math.sqrt(T))
    disc = math.exp(-r * T)
    if is_call:
        return term1 - r * K * disc * _N.cdf(d2)
    return term1 + r * K * disc * _N.cdf(-d2)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_vrp_structure_greeks.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_structure.py tests/unit/test_vrp_structure_greeks.py
git commit -m "feat(vrp-entry): bs_gamma/vega/theta — BS greeks from IV for entry markout"
```

---

### Task 2: Migration 085 + storage module `vrp_macro_entry.py`

**Files:**
- Create: `src/uw_scan/storage/migrations/085_vrp_macro_entry.sql`
- Create: `src/uw_scan/storage/vrp_macro_entry.py`
- Modify: `src/uw_scan/storage/repository.py` (mix in `_VrpMacroEntryMixin`)
- Test: `tests/integration/test_vrp_macro_entry_storage.py` (create)

**Interfaces:**
- Produces (on `Repository`):
  - `insert_vrp_macro_entry(*, name, birth_date, born_at, origin, expiry, hold_days, spot_at_birth, iv_at_birth, vrp_z_at_birth, weight_at_birth, action_at_birth, short_delta, wing_delta, short_above, short_below, wing_above, wing_below) -> int` — returns `entry_id`. **Auto** is idempotent per (name, birth_date): `INSERT ... ON CONFLICT (name, birth_date) WHERE origin='auto' DO UPDATE SET name = EXCLUDED.name RETURNING entry_id` — a re-fire **reuses** the row and preserves the original `born_at`/strikes (the no-op `SET name` only fires RETURNING on the partial-index conflict). **Button** uses a plain `INSERT ... RETURNING entry_id` (each click is its own one-shot capture, never deduped).
  - `fetch_open_vrp_macro_entries(name, on_date) -> list[dict]` — **auto** cohorts with `expiry >= on_date` (`WHERE origin='auto'` — button cohorts are one-shot, never re-snapshotted), each dict carries the 4 strikes + birth_date.
  - `insert_vrp_macro_entry_quotes(rows: list[dict]) -> None` — batch upsert on `(entry_id, as_of, leg)`.
  - `list_vrp_macro_entries(name, limit) -> list[dict]` — newest-first headers (history).

- [ ] **Step 1: Write the migration**

```sql
-- src/uw_scan/storage/migrations/085_vrp_macro_entry.sql
-- Forward entry-capture: the SPX bull-put-spread the macro signal would place,
-- tracked to expiry. One "auto" cohort/day + on-demand "button" cohorts.
CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_entry (
    entry_id         BIGGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             TEXT        NOT NULL DEFAULT 'SPX',
    birth_date       DATE        NOT NULL,
    born_at          TIMESTAMPTZ NOT NULL,
    origin           TEXT        NOT NULL,          -- 'auto' | 'button'
    expiry           DATE        NOT NULL,
    hold_days        INTEGER     NOT NULL,
    spot_at_birth    NUMERIC,
    iv_at_birth      NUMERIC,
    vrp_z_at_birth   NUMERIC,
    weight_at_birth  NUMERIC,
    action_at_birth  TEXT,                          -- TRADE/SKIP (recorded anyway)
    short_delta      NUMERIC     NOT NULL,          -- target 0.25
    wing_delta       NUMERIC     NOT NULL,          -- target 0.125
    short_strike_above NUMERIC   NOT NULL,
    short_strike_below NUMERIC   NOT NULL,
    wing_strike_above  NUMERIC   NOT NULL,
    wing_strike_below  NUMERIC   NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Auto cohorts: one per (name, birth_date) — a restart double-fire reuses the row.
-- Button cohorts are NOT constrained here: each click is its own point-in-time
-- capture (never silently mapped onto an earlier click's stale strikes) AND
-- one-shot — fetch_open_vrp_macro_entries returns origin='auto' only, so a button
-- click is captured once and never re-snapshotted. This bounds the 8×/day load to
-- the auto stride set (the auto cohort already tracks the same structure to expiry).
CREATE UNIQUE INDEX IF NOT EXISTS vrp_macro_entry_auto_uniq
    ON uw_scan.vrp_macro_entry (name, birth_date) WHERE origin = 'auto';
CREATE INDEX IF NOT EXISTS vrp_macro_entry_open_idx
    ON uw_scan.vrp_macro_entry (name, expiry);

CREATE TABLE IF NOT EXISTS uw_scan.vrp_macro_entry_quote (
    entry_id      BIGINT      NOT NULL REFERENCES uw_scan.vrp_macro_entry(entry_id) ON DELETE CASCADE,
    as_of         TIMESTAMPTZ NOT NULL,
    session       TEXT        NOT NULL,             -- 'rth' | 'eod' | 'postclose'
    leg           TEXT        NOT NULL,             -- 'short_above'|'short_below'|'wing_above'|'wing_below'
    strike        NUMERIC     NOT NULL,
    opt_right     CHAR(1)     NOT NULL DEFAULT 'P',
    nbbo_bid      NUMERIC,
    nbbo_ask      NUMERIC,
    iv            NUMERIC,
    delta         NUMERIC,
    gamma         NUMERIC,
    vega          NUMERIC,
    theta         NUMERIC,
    und_spot      NUMERIC,
    source        TEXT        NOT NULL,             -- 'xenon_ib' | 'uw'
    greeks_source TEXT        NOT NULL,             -- 'bs' | 'none'  (bs=BS from marked IV; none=IV absent→0 greeks)
    source_asof   TIMESTAMPTZ,                      -- provider's own ts (UW delay)
    captured_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (entry_id, as_of, leg)
);
CREATE INDEX IF NOT EXISTS vrp_macro_entry_quote_entry_idx
    ON uw_scan.vrp_macro_entry_quote (entry_id, as_of DESC);
```

> NOTE for the implementer: `BIGGER` above is a deliberate typo to force you to read this — use `BIGINT GENERATED ALWAYS AS IDENTITY`. (Remove this note and fix the keyword before running.)

- [ ] **Step 2: Apply against the local DB, twice (idempotency)**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: both runs succeed, second is a no-op (no error on existing objects).

- [ ] **Step 3: Write the failing integration test**

```python
# tests/integration/test_vrp_macro_entry_storage.py
from datetime import date, datetime, timezone
from uw_scan.storage.repository import Repository

def test_insert_entry_idempotent_and_fetch_open(db):  # db = pytest-postgresql repo fixture
    repo = Repository(db)
    kw = dict(
        name="SPX", birth_date=date(2026, 6, 24),
        born_at=datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc), origin="auto",
        expiry=date(2026, 8, 7), hold_days=30, spot_at_birth=6000, iv_at_birth=0.16,
        vrp_z_at_birth=0.6, weight_at_birth=1.0, action_at_birth="TRADE",
        short_delta=0.25, wing_delta=0.125,
        short_above=5800, short_below=5790, wing_above=5600, wing_below=5590,
    )
    eid1 = repo.insert_vrp_macro_entry(**kw)
    eid2 = repo.insert_vrp_macro_entry(**kw)          # same day, auto → idempotent
    assert eid1 == eid2
    rows = repo.fetch_open_vrp_macro_entries("SPX", date(2026, 6, 25))
    assert len(rows) == 1 and rows[0]["entry_id"] == eid1
    assert repo.fetch_open_vrp_macro_entries("SPX", date(2026, 8, 8)) == []  # expired

def test_insert_quotes_upsert(db):
    repo = Repository(db)
    eid = repo.insert_vrp_macro_entry(**_min_entry_kwargs())
    q = dict(entry_id=eid, as_of=datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc),
             session="rth", leg="short_above", strike=5800, opt_right="P",
             nbbo_bid=12.0, nbbo_ask=12.4, iv=0.17, delta=-0.26, gamma=0.001,
             vega=8.0, theta=-1.2, und_spot=6000, source="xenon_ib",
             greeks_source="bs", source_asof=None)
    repo.insert_vrp_macro_entry_quotes([q])
    repo.insert_vrp_macro_entry_quotes([{**q, "nbbo_bid": 11.5}])  # same PK → update
    got = repo.fetch_vrp_macro_entry_quotes(eid)
    assert len(got) == 1 and float(got[0]["nbbo_bid"]) == 11.5
```

(Add `_min_entry_kwargs()` / a `fetch_vrp_macro_entry_quotes` read helper; the `db` fixture mirrors the existing integration suite — copy its setup.)

- [ ] **Step 4: Implement `storage/vrp_macro_entry.py`** — `_VrpMacroEntryMixin` with the four methods + the `fetch_vrp_macro_entry_quotes` read helper. Use psycopg `executemany`/`execute_values` for the batch upsert. Idempotent insert **branches on origin**: **auto** → `INSERT ... ON CONFLICT (name, birth_date) WHERE origin='auto' DO UPDATE SET name = EXCLUDED.name RETURNING entry_id` (DO UPDATE on a key column is a deliberate no-op that fires RETURNING on the partial-index conflict, leaving `born_at`/strikes untouched); **button** → plain `INSERT ... RETURNING entry_id`. `fetch_open_vrp_macro_entries` filters `WHERE origin='auto'` so button cohorts are captured once and never re-snapshotted. **All 4 legs of one snapshot share one `as_of`** (frozen by the caller at mark start) so `(entry_id, as_of, leg)` groups them — the storage layer accepts the caller's `as_of`, never `now()` per row. Mix into `Repository` by appending `_VrpMacroEntryMixin` to the bases tuple **before `_BaseMixin`** (stays last in the MRO — it owns `__init__`/`conn`); no method bodies in `repository.py`.

- [ ] **Step 5: Run**

Run: `uv run pytest tests/integration/test_vrp_macro_entry_storage.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/085_vrp_macro_entry.sql src/uw_scan/storage/vrp_macro_entry.py src/uw_scan/storage/repository.py tests/integration/test_vrp_macro_entry_storage.py
git commit -m "feat(vrp-entry): migration 085 + vrp_macro_entry storage (header + quote series)"
```

---

### Task 3: Bracket-finder — `resolve_entry_contracts` (pure)

**Files:**
- Create: `src/uw_scan/reports/vrp_macro_entry.py`
- Test: `tests/unit/test_vrp_macro_entry_finder.py` (create)

**Interfaces:**
- Consumes: `strike_for_delta` from `vrp_structure`.
- Produces:
  - `@dataclass EntryContracts(short_above, short_below, wing_above, wing_below: float)`
  - `resolve_entry_contracts(*, spot, sigma, T, r, listed_strikes: list[float], short_delta=0.25, wing_delta=0.125) -> EntryContracts` — BS target strike for each delta, then the nearest listed strike **above** and **below** each target. Raises `ValueError` if `listed_strikes` lacks a strike on either side of a target.

- [ ] **Step 1: Failing test**

```python
# tests/unit/test_vrp_macro_entry_finder.py
import pytest
from uw_scan.reports.vrp_macro_entry import resolve_entry_contracts

def test_brackets_each_target_above_and_below():
    # SPX-like: spot 6000, IV 0.16, ~43 cal DTE, 5-pt grid
    listed = [5500 + 5 * i for i in range(120)]  # 5500..6095
    ec = resolve_entry_contracts(spot=6000, sigma=0.16, T=43/365, r=0.04,
                                 listed_strikes=listed, short_delta=0.25, wing_delta=0.125)
    assert ec.short_below < ec.short_above
    assert ec.wing_below < ec.wing_above
    assert ec.wing_above < ec.short_below           # wing strictly below short (deeper OTM put)
    assert all(k in listed for k in (ec.short_above, ec.short_below, ec.wing_above, ec.wing_below))

def test_raises_when_no_bracket():
    with pytest.raises(ValueError):
        resolve_entry_contracts(spot=6000, sigma=0.16, T=43/365, r=0.04,
                                listed_strikes=[6000], short_delta=0.25, wing_delta=0.125)
```

- [ ] **Step 2: Run → FAIL** (`uv run pytest tests/unit/test_vrp_macro_entry_finder.py -q`).

- [ ] **Step 3: Implement** `resolve_entry_contracts` (pure; `strike_for_delta(..., is_call=False)` per target → scan sorted `listed_strikes` for nearest below/above). Add the `EntryContracts` dataclass.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_macro_entry.py tests/unit/test_vrp_macro_entry_finder.py
git commit -m "feat(vrp-entry): resolve_entry_contracts — bracket 0.25/0.125 delta to listed strikes"
```

---

### Task 4: Source-aware leg quoter — xenon primary, UW fallback, BS-fill

**Files:**
- Modify: `src/uw_scan/sources/xenon_query.py` (add `fetch_ib_option_quote`)
- Modify: `src/uw_scan/reports/vrp_macro_entry.py` (add `quote_leg` + `LegQuote`)
- Test: `tests/unit/test_vrp_macro_entry_quoter.py` (create)

**Interfaces:**
- Produces:
  - `fetch_ib_option_quote(*, base_url, api_key, symbol, expiry, strike, right, timeout_s=8.0, client=None) -> dict | None` — `{"bid","ask","iv","und_spot"}` (NBBO + marked IV + underlying spot ONLY — **not** the greek bundle; greeks are always BS-computed downstream). `bid`/`ask` read from the **top-level** `body["bid"]`/`body["ask"]`; `iv` from `body["greeks"]["impliedVol"]`; `und_spot` from `body["greeks"]["undPrice"]` — with `body["greeks"]` possibly the JSON `null` (illiquid contract → still HTTP 200). Any key `None` when IB omitted it. Returns `None` only on transport failure (mirrors `fetch_ib_option_iv`'s never-raise contract).
  - `@dataclass LegQuote(strike, nbbo_bid, nbbo_ask, iv, delta, gamma, vega, theta, und_spot, source, greeks_source, source_asof)`
  - `quote_leg(*, strike, expiry, as_of, underlying_spot, r, settings, xenon_client=None, uw_row=None) -> LegQuote` — try xenon (`fetch_ib_option_quote`); on `None`/missing-NBBO fall back to `uw_row`. ⚠️ `uw_row` is an `OptionContractRow`-shaped dict (`option_symbol`, `nbbo_bid`, `nbbo_ask`, `implied_volatility`, vol/OI) — it carries **no `strike`, `expiry`, or `und_spot`** (verified `models/options.py:67`); strike/expiry are parsed from `option_symbol` upstream, and the **underlying spot comes from the caller** (`underlying_spot`, the live SPX spot the birth job already fetched). `T` is computed from `expiry` vs the **`as_of` ET date** (never wall-clock `today`) so replays/late-night marks are deterministic. **Greeks: ALWAYS BS-compute** from `(iv, underlying_spot, strike, T, r)` — xenon/UW native greeks are **never stored**. This is the line-13 one-model rule, and it is load-bearing: IB's `theta` is **per-day** (≈ −0.23 on a ~30-DTE leg — confirmed below) while `bs_theta` is **per-year** (≈ −3.97 at T=1), and IB/UW vega·gamma bump conventions differ from BS — storing source greeks would flip a leg's `theta` between unit systems from mark to mark (xenon-up vs BS-fill) and corrupt the markout series. So `greeks_source='bs'` whenever a real IV is present (the normal case), and `'none'` when IV itself is absent (BS hits the `sigma<=0` guard → greeks `0.0`; tagged in-band so degenerate-zero greeks are filterable — see Production safety). `source` (`xenon_ib`/`uw`/`modeled`) tags only the NBBO+IV+und_spot provenance. The marked `iv` IS taken from source (xenon `greeks.impliedVol` → UW `implied_volatility`); recorded `und_spot` = xenon's `undPrice` if present, else `underlying_spot`; `source_asof` = `uw_row` provider ts if present else `None`.

> ✅ **VERIFY — residual #1 CLOSED (2026-06-24).** xenon `/options/greeks` success-shape confirmed authoritatively from `~/projects/xenon/docs/reference/readonly-query-api.md` (the mini's query API is localhost-only / not Tailscale-exposed, and there is no local IB Gateway, so a live call from the MacBook is impossible — but the reference + route handler are the source of record). Shape: top-level `symbol/conId/secType/expiry/strike/right/asOf`, **top-level `bid` and `ask` (both nullable pre-market)**, and a nested `greeks` object `{impliedVol, delta, gamma, vega, theta, undPrice}` that **may itself be `null` with `"note":"no greeks returned"` — still HTTP 200**. Errors: `422` (missing leg / bad `right`), `502` (`{"detail":...}` unqualifiable contract or IB unreachable). Two consequences already baked into the code above: (1) we consume only `bid`/`ask`/`greeks.impliedVol`/`greeks.undPrice` and BS-compute every greek, so the `delta/gamma/vega/theta` keys in the bundle are intentionally ignored (IB theta is per-day — wrong units to store); (2) the quoter must null-guard `body["greeks"] is None`. Write it defensively anyway (`body.get(...)`, `(greeks or {}).get(...)`). (**Live failure-path probe 2026-06-24:** local `127.0.0.1:8421` needs **no API key**; with IB down it returns the non-200 `{"detail": "IB Gateway is not accepting connections…"}` and the never-raise clone catches it → UW fallback. Task 9's smoke confirms the IB-up success path on the mini post-deploy, where localhost:8421 has live IB.)

- [ ] **Step 1: Failing test** (monkeypatch the two fetchers)

```python
# tests/unit/test_vrp_macro_entry_quoter.py
from uw_scan.reports import vrp_macro_entry as M

def test_uses_ib_when_available(monkeypatch, settings):
    # xenon supplies NBBO + IV + und_spot only — NOT greeks (those are always BS-computed)
    monkeypatch.setattr(M, "fetch_ib_option_quote", lambda **k: {
        "bid": 12.0, "ask": 12.4, "iv": 0.17, "und_spot": 6000})
    q = M.quote_leg(strike=5800, expiry="20260807", as_of=_et(2026, 6, 24, 11, 0),
                    underlying_spot=6000, r=0.04, settings=settings)
    assert q.source == "xenon_ib" and float(q.nbbo_bid) == 12.0
    assert q.greeks_source == "bs"                          # never "ib"
    assert q.delta is not None and -0.5 < float(q.delta) < 0.0   # BS put delta, not echoed

def test_falls_back_to_uw_and_bs_fills_greeks(monkeypatch, settings):
    monkeypatch.setattr(M, "fetch_ib_option_quote", lambda **k: None)  # IB down
    # OptionContractRow shape: no strike/expiry/und_spot on the row itself
    uw_row = {"option_symbol": "SPXW260807P05800000",
              "nbbo_bid": 12.1, "nbbo_ask": 12.5, "implied_volatility": 0.17}
    q = M.quote_leg(strike=5800, expiry="20260807", as_of=_et(2026, 6, 24, 11, 0),
                    underlying_spot=6000, r=0.04, settings=settings, uw_row=uw_row)
    assert q.source == "uw" and q.greeks_source == "bs"
    assert q.delta is not None and -0.5 < float(q.delta) < 0.0   # BS put delta
    # _et(...) builds an America/New_York tz datetime (helper shared across these tests)
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** `fetch_ib_option_quote` (clone `fetch_ib_option_iv`'s structure; read top-level `body["bid"]`/`body["ask"]` + `body["greeks"]["impliedVol"]` + `body["greeks"]["undPrice"]`, null-guarding `body["greeks"] is None`; return `{"bid","ask","iv","und_spot"}` — no delta/gamma/vega/theta) and `quote_leg` (T from `expiry` vs the **`as_of` ET date** in years; `bs_delta/gamma/vega/theta` compute **all** greeks from the marked IV, fed the caller's `underlying_spot`). Import the BS fns + `fetch_ib_option_quote` at module top so `monkeypatch.setattr(M, "fetch_ib_option_quote", ...)` works.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/xenon_query.py src/uw_scan/reports/vrp_macro_entry.py tests/unit/test_vrp_macro_entry_quoter.py
git commit -m "feat(vrp-entry): quote_leg — xenon-primary/UW-fallback with BS greek fill + lineage tag"
```

---

### Task 5: Worker job — birth + 8-mark snapshot with taper

**Files:**
- Create: `src/uw_scan/worker/jobs/vrp_macro_entry.py`
- Modify: `src/uw_scan/sources/uw.py` + `src/uw_scan/api/endpoints.py` (+ `normalize.py`) — add `fetch_chains_for_expiry` (Step 0)
- Test: `tests/integration/test_vrp_macro_entry_job.py` (create)

**Interfaces:**
- Consumes: `current_macro_signal_live`, `WINNER`, `resolve_entry_contracts`, `quote_leg`, UW chain fetch, repo methods.
- Produces:
  - `vrp_macro_entry_snapshot_once(repo, settings, *, session: str, now=None, birth: bool=False) -> dict` — when `birth=True` and no auto cohort exists for today, create one (resolve expiry+strikes from the **UW** chain + fresh live signal — skip-and-retry if no fresh quote, per Step 3); then snapshot every open **auto** cohort's 4 legs at this mark. **Taper:** a cohort more than `settings.vrp_macro_entry_taper_calendar_days` calendar days old is snapshotted only when `session == 'eod'`. **Per-mark budget:** serial loop, `quote_leg` per leg; once wall-clock in this mark exceeds `settings.vrp_macro_entry_mark_budget_s`, stop attempting xenon and quote remaining legs UW-only. Batch `insert_vrp_macro_entry_quotes`. **Resilience:** per-**leg** try/except around the (network) quote — a dead leg records nulls and never drops the cohort's other 3; per-**cohort** try/except around the batch insert logs `repr(exc)` + `repo.conn.rollback()` so one cohort's DB error never blocks the rest. Returns `{"births": n, "cohorts": m, "quotes": k}`.
  - `capture_entry_now(repo, settings, *, now=None) -> int` — birth a `button` cohort + one immediate snapshot; returns `entry_id`. (Reused by the API POST.)

- [ ] **Step 0: Wire `fetch_chains_for_expiry`** (strike/IV/greeks source — endpoint **confirmed live 2026-06-24**, no spike needed). Add `fetch_chains_for_expiry(client, repo, run_id, ticker, expiry)` to `sources/uw.py` (new slug `OPTION_CHAINS` → `/api/stock/{ticker}/option-chains?expiry=`, audit-first like the siblings) + a normalizer returning per-strike `{option_symbol, strike, iv, delta/gamma/theta/vega, last_price, theo}` (**no bid/ask**). `_uw_chain_strikes` calls it, parses strike from `option_symbol` (`cards/option_chain.py._parse_occ`), and picks the expiry nearest `birth+43cal`. Confirmed: 134 SPX puts K=3000..9800 for 2026-08-07; OCC `SPXW{YYMMDD}P{strike*1000:08d}`; spot ≈ 7336 → 0.25Δ≈K7100, 0.125Δ≈K6800. **NBBO is not in this endpoint** — IB is the NBBO of record; UW NBBO (via `/option-contracts`, capped) is best-effort, null-for-wing tolerated.

- [ ] **Step 1: Failing integration test** (stub `quote_leg` + UW chain so no network)

```python
# tests/integration/test_vrp_macro_entry_job.py
from datetime import date
from uw_scan.worker.jobs import vrp_macro_entry as J

def test_birth_then_snapshot_and_taper(db, settings, monkeypatch):
    repo = _repo_with_spx_vol_fixture(db)            # seed vol_index_daily so the live signal resolves
    monkeypatch.setattr(J, "_uw_chain_strikes", lambda *a, **k: ([5500 + 5*i for i in range(140)], _uw_rows()))
    monkeypatch.setattr(J, "quote_leg", _fake_quote_leg)   # deterministic LegQuote
    out = J.vrp_macro_entry_snapshot_once(repo, settings, session="rth", birth=True,
                                          now=_et(2026, 6, 24, 10, 0))
    assert out["births"] == 1 and out["cohorts"] == 1 and out["quotes"] == 4
    # second mark, same day, birth=False → no new cohort, 4 more quotes
    out2 = J.vrp_macro_entry_snapshot_once(repo, settings, session="rth", birth=False,
                                           now=_et(2026, 6, 24, 11, 0))
    assert out2["births"] == 0 and out2["quotes"] == 4
    # an aged cohort is skipped on an rth mark, captured on eod  → assert via a seeded old entry
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** the job.
  - **Birth live quote (required, must be fresh):** `current_macro_signal_live` takes `live_spot`/`live_iv` as kwargs — it does NOT fetch them. Reuse `regime_live_scan_once`'s pattern: `load_live_quotes(...)` (`uw_scan.scanners.live_quotes`) → fresh SPX spot + VIX, then `current_macro_signal_live(repo, settings, "SPX", live_spot=float(spx.price), live_iv=float(vix.price)/100.0)`. **Birth requires fresh same-session quotes** — if SPX or VIX is absent/stale (`load_live_quotes` freshness-filters), **skip birth this mark and let the next RTH/EOD mark retry**. Do NOT fall back to EOD spot/iv for birth: on a US holiday or WS-gap day that would birth a cohort off yesterday's close and pollute the stride dataset (codex-review ISSUE-3). The 6 RTH + 1 EOD birth-eligible marks give ample retry; the EOD-signal fallback is for **preview only** (Task 7), never birth.
  - **Strike source:** `_uw_chain_strikes(repo, settings, symbol, target_dte)` → (sorted candidate strikes for the chosen expiry, `{strike: uw_row}`) using the endpoint **pinned in Step 0 above**. ⚠️ `OptionContractRow` has no strike/expiry column (`models/options.py:67`) — **parse strike + expiry from each row's `option_symbol` (OCC)**; reuse the existing parser in `cards/option_chain.py` rather than re-rolling it. Pick the listed expiry nearest `birth_date + ~43 calendar days`.
  - **One `as_of` + one underlying spot per mark:** freeze `as_of = now` once AND fetch the current SPX spot once per mark (`load_live_quotes`), passing both into all 4 `quote_leg` calls (never `now()`/re-fetch per leg) so `(entry_id, as_of, leg)` reconstructs the mark and the 4 BS-fill greeks share one consistent spot + mark date.
  - `action_at_birth` records TRADE/SKIP regardless. `_repo` opens its own conn per the worker rule; per-cohort try/except logs `repr(exc)` + `repo.conn.rollback()` so one bad cohort never blocks the rest.

- [ ] **Step 4: Run → PASS.**

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/vrp_macro_entry.py tests/integration/test_vrp_macro_entry_job.py
git commit -m "feat(vrp-entry): snapshot job — daily birth + 8-mark markout with 30d EOD taper"
```

---

### Task 6: Scheduler wiring (8 marks) + config flags

**Files:**
- Modify: `src/uw_scan/config.py` (settings + env parse)
- Modify: `src/uw_scan/worker/scheduler.py` (gate + 3 `add_job` crons)
- Test: `tests/unit/test_vrp_macro_entry_schedule.py` (create)

**Interfaces:**
- Config (defaults): `vrp_macro_entry_capture_enabled: bool = True`, `vrp_macro_entry_taper_calendar_days: int = 30`, `vrp_macro_entry_quote_timeout_s: float = 8.0`, `vrp_macro_entry_mark_budget_s: float = 600.0` (per-mark wall-clock budget; once a mark exceeds it, remaining legs quote UW-only — caps IB load on the gateway that also feeds xenon's live WS).
- Scheduler: gate `_should_schedule_vrp_macro_entry(settings)` (role `massive`/`all` index-0, enabled flag). Three ET crons (`mon-fri`). **`birth=True` on every RTH + EOD mark** (not gated to a single 10:00 fire): the job's "birth only if today's auto cohort is absent" guard (the `ON CONFLICT` idempotent insert) makes a repeat birth a no-op, so a 10:00 worker outage still births the cohort at 11:00 (the recorded `born_at` shows which mark won). Strictly more robust than a single-fire birth, and collapses the RTH window to one cron:
  - `0 10-15 * * 0-4` → `session='rth', birth=True` (job id `vrp_macro_entry_rth`).
  - `55 15 * * 0-4` → `session='eod', birth=True` (job id `vrp_macro_entry_eod`; last-resort birth if the whole RTH window was missed).
  - `10 16 * * 0-4` → `session='postclose', birth=False` (job id `vrp_macro_entry_postclose`; never births — a post-close-only cohort can't be marked intraday and would skew the stride dataset).

- [ ] **Step 1: Failing test** — assert the gate returns False when disabled, and that building the scheduler registers job ids `vrp_macro_entry_rth`, `vrp_macro_entry_eod`, `vrp_macro_entry_postclose` when enabled, each with `max_instances == 1` and `coalesce is True` (mirror the existing scheduler test pattern; inspect `sched.get_jobs()`).

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** config fields (+ `_env_bool`/`float` parse like the surrounding settings) and the `add_job` calls with `CronTrigger.from_crontab(..., timezone=settings.rth_tz)`, **`max_instances=1, coalesce=True`** (match the existing jobs at `scheduler.py:834+`; this job can overrun an hour, so a slow mark must not stack or backlog). Each job wrapper opens `_repo(settings)` in try/finally and calls `vrp_macro_entry_snapshot_once(..., session=..., birth=...)`.

- [ ] **Step 4: Run → PASS** (+ `uv run pytest tests/unit/test_vrp_macro_entry_schedule.py -q`).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/worker/scheduler.py tests/unit/test_vrp_macro_entry_schedule.py
git commit -m "feat(vrp-entry): schedule 8 daily marks (rth 10-15 birth-idempotent, eod 15:55, postclose 16:10) + gate"
```

---

### Task 7: API — preview (UW, no IB) + capture (IB) + models

**Files:**
- Create: `src/uw_scan/models/vrp_macro_entry.py`; Modify: `src/uw_scan/models/__init__.py`
- Modify: `src/uw_scan/api/routers/regime.py`
- Test: `tests/integration/test_regime_entry_api.py` (create); then `cd web && npm run gen:types`

**Interfaces:**
- Models (re-exported from `models/__init__.py`): `VrpMacroEntryLeg{leg,strike,nbbo_bid,nbbo_ask,iv,delta,...,source,greeks_source}`, `VrpMacroEntryPreview{name,as_of,spot,expiry,hold_days,action,vrp_z,weight,modeled_credit,legs:list[VrpMacroEntryLeg]}`, `VrpMacroEntryCaptureResponse{entry_id,preview:VrpMacroEntryPreview}`.
- Endpoints (on the existing regime router):
  - `GET /vrp-macro-signal/entry/preview` → `VrpMacroEntryPreview`. **Zero IB, zero new UW calls, zero writes** — it is browser-polled ~30s, and every `sources/uw.py` fetcher writes an audit + raw-payload row per call via `_fetch_json` (codex-review ISSUE-2). Serve from **already-persisted state**: today's auto-cohort header + its latest snapshot legs (`fetch_open_vrp_macro_entries` + `fetch_vrp_macro_entry_quotes`) — strikes, expiry, indicative NBBO/IV/greeks are already stored from the day's marks. Overlay live `action`/`vrp_z` from `current_macro_signal_live` (→ `current_macro_signal` EOD if no live quote; in-memory, no persist). **Pre-birth (before the day's first mark)**: compute strikes via `resolve_entry_contracts` off the computed SPX grid + BS-indicative leg prices (zero UW; tag legs `source='modeled'`, `greeks_source='bs'`) so the panel still renders. If even the live signal won't resolve (no SPX vol history), return 200 with `action=null` + empty `legs` — degrade, never 500. `modeled_credit` = **short-leg mid − wing-leg mid from the displayed legs** (consistent bracket), NOT `MacroSignal.credit` (the continuous-strike flat-vol credit won't match the snapped legs).
  - `POST /vrp-macro-signal/entry/capture` → `VrpMacroEntryCaptureResponse`. Calls `capture_entry_now(...) -> entry_id` (IB-primary; persists a one-shot `button` cohort + its 4 legs), then assembles the response by reading them back via `fetch_vrp_macro_entry_quotes(entry_id)` (codex-review ISSUE-5 — `capture_entry_now` returns only the id; the endpoint builds `preview.legs` from the persisted rows).

- [ ] **Step 1: Failing integration test** — seed today's auto cohort + 4 quote rows, then `TestClient` GET preview returns 200 with those 4 legs + the `expiry` **and makes no UW/IB call** (don't stub any fetcher — a network attempt should fail the test). Add a **pre-birth** case (no cohort seeded) asserting 200 with BS-indicative `modeled` legs. POST capture returns an `entry_id` and persists one `button` cohort + 4 quote rows (stub `quote_leg` for the capture path so no network).

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** models + endpoints. Preview must call **no** `sources/uw.py` fetcher and **no** xenon (both persist / hit IB) — it reads persisted cohort state and computes BS-indicative legs pre-birth. Persist nothing on preview; capture persists (the analytical-result write). Add `'modeled'` to the leg `source` enum (preview-only BS-indicative; never persisted in `vrp_macro_entry_quote`, whose `source` stays `xenon_ib|uw`).

- [ ] **Step 4: Run → PASS**, then regenerate types:

Run: `uv run pytest tests/integration/test_regime_entry_api.py -q && cd web && npm run gen:types && git diff --stat web/lib/types.ts`
Expected: tests pass; `types.ts` gains the new component types only (no unrelated reordering — add surgically if the generator churns).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/models/vrp_macro_entry.py src/uw_scan/models/__init__.py src/uw_scan/api/routers/regime.py tests/integration/test_regime_entry_api.py web/lib/types.ts web/lib/openapi.snapshot.json
git commit -m "feat(vrp-entry): /entry/preview (persisted read, no IB) + /entry/capture (IB) endpoints + models"
```

---

### Task 8: Card UI — remove text, add strike/ETD panel + Capture button

**Files:**
- Create: `web/lib/regime/useVrpMacroEntryPreview.ts`
- Modify: `web/components/regime/MacroShortVolCard.tsx`
- Modify: `web/tests/unit/MacroShortVolCard.test.tsx`

**Interfaces:**
- `useVrpMacroEntryPreview() -> { preview, loading, error }` — polls `GET /api/regime/vrp-macro-signal/entry/preview` (~30s, like `useVrpMacroLive`).
- Card: delete the `"(gate at 0)"` suffix and the `"Vol not rich enough — stand aside"` bullet. Add a right-side panel (the card becomes a 2-column flex): **ETD** = `preview.expiry`, and the 4 legs as `0.25↑/↓`, `0.125↑/↓` with strike + indicative mid + delta. A **Capture entry** button → `POST .../entry/capture`; on success show an inline `Captured #<id>` badge.

- [ ] **Step 1: Update the failing test** — assert "(gate at 0)" and "stand aside" are **absent**; assert the panel renders `preview.expiry` and the 4 strikes; assert clicking Capture calls the POST (mock `fetch`).

- [ ] **Step 2: Run → FAIL** (`cd web && npm run test -- MacroShortVolCard`).

- [ ] **Step 3: Implement** the hook + card changes. Label each leg `indicative` and show its actual `source` (`xenon_ib` / `uw ~15m` / `modeled`) so provenance is honest — preview now serves today's persisted cohort legs (which may be IB- or UW-sourced) or BS-`modeled` pre-birth; the authoritative record is the captured snapshot. **Debounce the Capture button** (disable on click until the POST resolves) — capture is one-shot/non-idempotent, so prevent accidental double-writes.

- [ ] **Step 4: Run → PASS** + `cd web && npm run typecheck`.

- [ ] **Step 5: Commit**

```bash
git add web/lib/regime/useVrpMacroEntryPreview.ts web/components/regime/MacroShortVolCard.tsx web/tests/unit/MacroShortVolCard.test.tsx
git commit -m "feat(vrp-entry): card strike/ETD preview panel + capture button; drop gate/stand-aside copy"
```

---

### Task 9: Docs + full-suite verification + live smoke

**Files:**
- Modify: `docs/research/vrp/README.md` (entry-capture dataset section + reproduce command)
- Modify: `CLAUDE.md` + `AGENTS.md` (the vrp-macro "Where to look first" row → add entry-capture files)
- Modify: `CHANGELOG.md` (`[Unreleased]` entry)

- [ ] **Step 1: Document** the dataset: table pair, the 8 marks, the taper, the source/greeks-lineage columns, and the **reproduce command** (`uv run python -m ...` or the job entrypoint). State the IB-vs-UW provenance so a researcher filters on `source`/`greeks_source`.

- [ ] **Step 2: Full Python suite** — `uv run pytest -q` (expect green; capture the tail).

- [ ] **Step 3: Full web suite** — `cd web && npm run test && npm run typecheck` (expect green).

- [ ] **Step 4: Migration idempotency** — `bash scripts/migrate.sh` twice; second run no-op.

- [ ] **Step 5: Live smoke (the real worker path, not a side-channel)** — with `XENON_WS`/xenon reachable, run one `vrp_macro_entry_snapshot_once(session='rth', birth=True)` against the local DB; confirm 1 cohort + 4 quote rows, and that at least one row has `source='xenon_ib'` (validates the xenon response keys from Task 4's VERIFY note). If xenon is down, confirm the UW fallback wrote `source='uw', greeks_source='bs'`. Record the row dump as evidence.

- [ ] **Step 6: Commit**

```bash
git add docs/research/vrp/README.md CLAUDE.md AGENTS.md CHANGELOG.md
git commit -m "docs(vrp-entry): document the forward entry-capture markout dataset + reproduce"
```

---

## Production-safety notes (adversarial review)

- **Preview never touches IB and issues no UW fetcher call** — it is browser-polled. Any code path that makes preview call xenon or a `sources/uw.py` fetcher is a regression; the integration test asserts the preview path makes no IB/UW network call (it reads persisted cohort state, computing BS-indicative legs only pre-birth).
- **Snapshot is serial + short timeout + per-mark budget → UW fallback.** Open auto cohorts in the 30-cal RTH window ≈ 22 → ≈ 88 legs/mark; at the 8s xenon timeout the worst case (xenon slow on every leg) is ≈ 12 min, past comfortable hourly spacing (codex-review ISSUE-7). Guard: `vrp_macro_entry_mark_budget_s` (default 600s) forces remaining legs UW-only once a mark overruns; `max_instances=1, coalesce=True` stop a slow mark from stacking; the birth-guard + `ON CONFLICT` keep a re-fire idempotent. **Decision (user, 2026-06-24): keep IB/xenon-primary on all 8 marks** (locked decision 3 unchanged) — a xenon/IB outage is treated as transient, and the budget + `max_instances` guards already bound the worst case; the "UW-only on the 6 intraday marks" refinement was considered and **declined**. `# ponytail: thread-pool the leg loop only if the 600s budget proves too tight in practice.`
- **Per-leg, not per-cohort, error isolation** (adversarial Pass 3): wrap each leg's quote so one dead leg records nulls without dropping the cohort's other 3 legs.
- **iv-null from UW** → BS greeks hit the degenerate `sigma<=0` guard and return `0.0` (no crash); the leg still records NBBO. Tag the row `greeks_source='none'` (not `'bs'`) so a researcher filters degenerate-zero greeks in-band — distinguishing "0 greek (no IV)" from a real near-zero greek without grepping logs.
- **OCC parse failures skip the row, never abort birth** — a malformed `option_symbol` from UW drops that strike candidate; birth proceeds on the rest.
- **Expiry settlement style at the 16:10 post-close mark:** an AM-settled standard SPX monthly is already settled by 16:10 → the legs quote null/garbage. Prefer **PM-settled SPXW** expiries when picking the ~43-DTE listed expiry (Step 0), or document that expiry-day post-close marks on AM-settled expiries are noise to filter.
- **Holidays:** crons fire mon-fri with no holiday calendar (matches every other repo job). The fresh-quote birth guard prevents holiday *births*; existing open cohorts still get a stale snapshot row on a holiday — filterable via `source_asof`. Acceptable; not worth a holiday-calendar dependency.
- **Button double-click:** capture is non-idempotent by design (one-shot point-in-time). Debounce the UI button (disable on click until the POST resolves) so an accidental double-click doesn't write two near-identical captures.
- **Birth idempotency** — the partial unique index `(name, birth_date) WHERE origin='auto'` means a double-fire (restart) re-uses the cohort; quotes upsert on `(entry_id, as_of, leg)`.
- **SKIP days still record** (user requirement) — birth happens regardless of `action`; `action_at_birth` preserves TRADE/SKIP for research.
- **Worker env frozen at fork** — toggling `vrp_macro_entry_capture_enabled` / rotating `XENON_QUERY_API_KEY` needs a worker restart (standing gotcha).
- **No naked shorts / no orders** — this records contracts; the short put is always wing-covered in the recorded structure.
- **DB isolation** — runs against `option_wizard_local` on the MacBook; do not point the snapshot job at the mini DB from dev.

## Self-Review

- **Spec coverage:** daily birth ✅ (Task 5), 8 marks ✅ (Task 6), taper-to-EOD-after-30d ✅ (Tasks 5/6), IB-primary/UW-fallback/BS-fill ✅ (Task 4), persist greeks+IV+NBBO ✅ (Task 2), 4 bracketing puts ✅ (Task 3), button records-anyway ✅ (Tasks 5/7), remove "(gate at 0)"/"stand aside" ✅ (Task 8), preview off IB ✅ (Tasks 7/8).
- **Type consistency:** leg keys `short_above|short_below|wing_above|wing_below` identical across migration, storage, finder, quoter, models, UI. `greeks_source ∈ {bs,none}`, `session ∈ {rth,eod,postclose}` consistent. **Persisted** `source ∈ {xenon_ib,uw}`; the **API preview leg** `source` additionally allows `modeled` (transient BS-indicative, never written to the quote table).
- **Placeholders:** none — the two `NOTE`/`VERIFY` blocks are deliberate (a forced-read typo to fix, and a real "confirm xenon keys against a live response" step), not TBDs.
- **Deferred (YAGNI):** history list/detail API endpoints — the markout series is consumed via SQL/notebook (the durable artifact); add a research-UI endpoint only when a screen needs it.
