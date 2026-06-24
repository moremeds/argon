# VRP Macro Short-Vol — Live Signal + Regime Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live (5-min) variant of the already-deployed EOD `vrp_macro_signal` slice and surface the weekly TRADE/SKIP readout as a single "Macro Short-Vol" card on the `/regime` page — no per-stock UI.

**Architecture:** The EOD half already exists (engine `reports/vrp_macro_signal.py::current_macro_signal`, table `vrp_macro_signal_daily`, worker `vrp_macro_signal_refresh` @03:45 ET, `GET /api/regime/vrp-macro-signal`, migration 083). We _extend_ it — not clone a new table — by (1) adding a `basis` column so `'live'` and `'eod'` rows coexist, (2) adding a pure `current_macro_signal_live()` that recomputes `vrp_z` from a live VIX tick against the EOD `rv20` + trailing-252d vrp distribution, (3) persisting `basis='live'` SPX rows from the existing `regime_live_scan` 5-min job, (4) a `GET /api/regime/vrp-macro-signal/live` endpoint (on-demand recompute, EOD fallback) mirroring `/cri/live`, and (5) one regime sub-tab card polling it. Live is **SPX-only** in v1 (VIX + SPX are the only macro inputs in `REGIME_WS_SYMBOLS`); QQQ/IWM stay EOD-only.

**Tech Stack:** Python 3.13 / `uv`, FastAPI + Pydantic v2, psycopg 3, APScheduler 3, pytest + pytest-postgresql; Next.js 16 + React 19 + TypeScript, Vitest; types flow API→client via `openapi-typescript` (`npm run gen:types`).

## Global Constraints

- **`uv` only** — `uv run pytest`, never bare `pytest`. (CI runs `uv run pytest` + ruff + Guardrail-2 `_lint_except.py` + version_sync_check.)
- **Migrations are idempotent** — `IF NOT EXISTS`; for the PK change, always `DROP CONSTRAINT IF EXISTS` before `ADD CONSTRAINT`. No tracking table.
- **API contract identity preserved** — do NOT change `VrpMacroSignalRow` / `VrpMacroSignalResponse` field/default surfaces or their OpenAPI component names. Only ADD a new `VrpMacroSignalLiveResponse` model + new endpoint.
- **Persist analytical results to Postgres** — the live signal is written to `vrp_macro_signal_daily` (basis='live'), never memory-only.
- **No naked shorts** — bull put spread is defined-risk; unchanged.
- **Decimal-in-DB, float-in-engine** — the engine returns floats; storage columns are NUMERIC (psycopg handles the cast). NaN/inf → NULL (existing `_finite` helper).
- **Exception handlers log with `repr(exc)` / `.exception(...)`** (CI Guardrail 2).
- **Generated files** — `web/lib/types.ts` and the OpenAPI snapshot are regenerated, never hand-edited; types.ts via `npm run gen:types`.
- **Live scope** — SPX only. `DEFAULT_LIVE_NAMES = ("SPX",)`. Do not attempt QQQ/IWM live (no VXN/QQQ in `REGIME_WS_SYMBOLS`).
- **AGENTS.md mirrors root CLAUDE.md** — keep both in sync when policy/where-to-look changes.

## Test harness — real fixtures (use these; the snippets below use placeholder names)

The test snippets in the tasks use short placeholder fixture names for readability. **Substitute the real ones** (verified in `tests/integration/conftest.py` + the existing EOD `vrp_macro_signal` tests):

| Placeholder in snippets                                 | Real fixture / helper                                                                                                                                                                   | Source                                 |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `repository`                                            | **`seeded_db_empty_cards`** (returns `Repository`; do `repo = seeded_db_empty_cards`)                                                                                                   | `tests/integration/conftest.py:136`    |
| `api_client`                                            | **`client`** (FastAPI `TestClient`)                                                                                                                                                     | `tests/integration/api/conftest.py:34` |
| `seed_spx_vol` (engine TRADE test needs ≥252 SPX rows)  | reuse the SPX `vol_index_daily` seeding in **`tests/integration/reports/test_vrp_macro_signal.py`** (already drives `current_macro_signal` end-to-end)                                  | existing                               |
| `live_settings` / `seed_fresh_quotes` (worker/API live) | reuse **`_seed`** + **`SESSION`** + `repo.bulk_upsert_intraday_quotes(...)` from **`tests/integration/test_regime_live_compute.py`** (seeds VIX/VVIX/SPX/VIX3M vol + the quote pattern) | existing                               |
| storage basis test row data                             | reuse the **`SPX_SKIP`** dict from **`tests/integration/storage/test_vrp_macro_signal_storage.py`**                                                                                     | existing                               |

**Cohesion note:** prefer adding cases to the existing `test_vrp_macro_signal_{storage,job}.py` / `test_vrp_macro_signal_endpoint.py` / `test_regime_live_job.py` files rather than parallel new files — but new files that _import_ the helpers above are acceptable. `_seed` seeds <252 vol rows → `vrp_z` is `None` → SKIP, which is fine for the worker/API "row persisted + basis correct" asserts; the **TRADE** assertion belongs only in the engine test backed by the ≥252-row reports seeder.

---

## File Structure

**Create:**

- `src/uw_scan/storage/migrations/084_vrp_macro_signal_basis.sql` — add `basis` column + PK change + index.
- `web/components/regime/MacroShortVolSubTab.tsx` — the regime card.
- `web/lib/regime/useVrpMacroLive.ts` — live-polling hook.
- `tests/integration/reports/test_vrp_macro_signal_live.py` — engine live-variant unit tests.
- `tests/integration/storage/test_vrp_macro_signal_basis.py` — basis round-trip.
- `tests/integration/worker/test_regime_live_vrp.py` — worker persists basis='live'.
- `tests/integration/api/test_vrp_macro_signal_live_api.py` — endpoint live + eod-fallback.
- `web/components/regime/__tests__/MacroShortVolSubTab.test.tsx` — card render (TRADE vs SKIP).

**Modify:**

- `src/uw_scan/storage/vrp_macro_signal.py` — `basis` param on upsert (PK + conflict target) and on `fetch_latest_vrp_macro_signals`.
- `src/uw_scan/reports/vrp_macro_signal.py` — add `current_macro_signal_live(...)`.
- `src/uw_scan/worker/jobs/regime_live.py` — persist `basis='live'` SPX row inside `regime_live_scan_once`.
- `src/uw_scan/api/schemas.py` — add `VrpMacroSignalLiveResponse`.
- `src/uw_scan/api/routers/regime.py` — add `GET /vrp-macro-signal/live`.
- `web/lib/regime/api.ts` — add `vrp_macro_signal` + `vrp_macro_signal_live` endpoint entries.
- `web/components/regime/RegimePanel.tsx` — add the tab.
- `web/app/regime/[[...tab]]/page.tsx` — add tab id to `VALID_TABS`.
- `web/lib/types.ts` — regenerate (do not hand-edit).
- `CLAUDE.md` (root) + `AGENTS.md` — "Where to look first" row + regime-live note.

---

### Task 1: DB — `basis` column + basis-aware storage

**Files:**

- Create: `src/uw_scan/storage/migrations/084_vrp_macro_signal_basis.sql`
- Modify: `src/uw_scan/storage/vrp_macro_signal.py` (`_COLUMNS`, `upsert_vrp_macro_signal`, `fetch_latest_vrp_macro_signals`)
- Test: `tests/integration/storage/test_vrp_macro_signal_basis.py`

**Interfaces:**

- Produces: `upsert_vrp_macro_signal(..., basis: str = "eod")`, `fetch_latest_vrp_macro_signals(names=None, *, basis: str = "eod")`. Table `vrp_macro_signal_daily` PK becomes `(name, snapshot_date, basis)`.

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/084_vrp_macro_signal_basis.sql`:

```sql
-- 084_vrp_macro_signal_basis.sql
-- Add a `basis` column to vrp_macro_signal_daily so live (5-min, intraday VIX) and
-- eod (nightly) signal rows coexist, mirroring the cri/vcg_snapshots `basis` pattern
-- (migration 070). Idempotent: column add is guarded; the PK is dropped-then-readded.
-- A live row is a single (name, snapshot_date, 'live') row OVERWRITTEN every 5 min —
-- we intentionally do NOT accumulate an intraday vrp_z series (the weekly signal barely
-- moves intraday). ponytail: single overwritten live row, add intraday history only if
-- a chart ever needs it.
SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.vrp_macro_signal_daily
    ADD COLUMN IF NOT EXISTS basis TEXT NOT NULL DEFAULT 'eod';

-- existing rows default to 'eod', so (name, snapshot_date, 'eod') stays unique →
-- the PK widening is safe. Always drop-then-add for idempotency.
ALTER TABLE uw_scan.vrp_macro_signal_daily
    DROP CONSTRAINT IF EXISTS vrp_macro_signal_daily_pkey;
ALTER TABLE uw_scan.vrp_macro_signal_daily
    ADD CONSTRAINT vrp_macro_signal_daily_pkey
    PRIMARY KEY (name, snapshot_date, basis);

CREATE INDEX IF NOT EXISTS ix_vrp_macro_signal_basis
    ON uw_scan.vrp_macro_signal_daily (basis, name, snapshot_date DESC);

COMMENT ON COLUMN uw_scan.vrp_macro_signal_daily.basis
    IS 'eod = nightly vrp_macro_signal_refresh; live = 5-min regime_live_scan (intraday VIX → live vrp_z, rv20/distribution from EOD).';

COMMIT;
```

- [ ] **Step 2: Apply migrations, verify the column exists**

Run: `bash scripts/migrate.sh` then
`uv run python -c "import psycopg,os; c=psycopg.connect(host=os.environ['UW_SCAN_DB_HOST'],dbname=os.environ['UW_SCAN_DB_NAME'],user=os.environ.get('UW_SCAN_DB_USER','argon_app')); print([r for r in c.execute(\"select column_name from information_schema.columns where table_name='vrp_macro_signal_daily' and column_name='basis'\")])"`
Expected: `[('basis',)]` (locally point at `option_wizard_local`; CI/tests use `option_wizard_test`).

- [ ] **Step 3: Write the failing storage test**

Create `tests/integration/storage/test_vrp_macro_signal_basis.py`:

```python
from datetime import date
from uw_scan.storage.repository import Repository


def _row(repo, *, name, basis, vrp_z, action):
    repo.upsert_vrp_macro_signal(
        name=name, snapshot_date=date(2026, 6, 24), as_of=date(2026, 6, 23),
        spot=7500.0, iv=0.16, rv20=0.12, vrp=0.04, vrp_z=vrp_z, weight=0.0 if action == "SKIP" else 1.0,
        action=action, short_put=None, long_put=None, put_width=None, credit=None, max_loss=None,
        hold_days=30, short_delta=0.25, wing_delta=0.125, bt_n=522, bt_sharpe=1.65,
        bt_maxdd=-0.8, bt_annror=0.53, bt_calmar=0.66, config={"k": "v"}, basis=basis,
    )


def test_live_and_eod_rows_coexist(repository: Repository):
    _row(repository, name="SPX", basis="eod", vrp_z=-1.95, action="SKIP")
    _row(repository, name="SPX", basis="live", vrp_z=0.8, action="TRADE")
    eod = repository.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
    live = repository.fetch_latest_vrp_macro_signals(["SPX"], basis="live")
    assert len(eod) == 1 and eod[0]["action"] == "SKIP"
    assert len(live) == 1 and live[0]["action"] == "TRADE"


def test_live_row_overwrites_in_place(repository: Repository):
    _row(repository, name="SPX", basis="live", vrp_z=0.8, action="TRADE")
    _row(repository, name="SPX", basis="live", vrp_z=-0.1, action="SKIP")
    live = repository.fetch_latest_vrp_macro_signals(["SPX"], basis="live")
    assert len(live) == 1 and live[0]["action"] == "SKIP"
```

(`repository` fixture is the existing pytest-postgresql Repository fixture — confirm its name in `tests/integration/conftest.py`; reuse whatever the other `tests/integration/storage/` tests use.)

- [ ] **Step 4: Run it, verify it fails**

Run: `uv run pytest tests/integration/storage/test_vrp_macro_signal_basis.py -v`
Expected: FAIL — `upsert_vrp_macro_signal() got an unexpected keyword argument 'basis'`.

- [ ] **Step 5: Add `basis` to storage**

In `src/uw_scan/storage/vrp_macro_signal.py`, add `"basis"` to `_COLUMNS` (append it after `"config_jsonb"`):

```python
_COLUMNS = (
    "name", "snapshot_date", "as_of", "spot", "iv", "rv20", "vrp", "vrp_z",
    "weight", "action", "short_put", "long_put", "put_width", "credit", "max_loss",
    "hold_days", "short_delta", "wing_delta", "bt_n", "bt_sharpe", "bt_maxdd",
    "bt_annror", "bt_calmar", "config_jsonb", "basis",
)
```

Add `basis: str = "eod"` as the final keyword param of `upsert_vrp_macro_signal`, change the conflict target and the values tuple:

```python
        sql = (
            f"INSERT INTO {self._schema}.vrp_macro_signal_daily ({cols}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (name, snapshot_date, basis) DO UPDATE SET "
            f"{updates}, created_at = now()"
        )
```

and append `basis` to the params tuple, right after the `Jsonb(config)...` entry. Also update the `updates` generator's exclusion set to skip the PK columns:

```python
        updates = ", ".join(
            f"{c} = EXCLUDED.{c}"
            for c in _COLUMNS
            if c not in ("name", "snapshot_date", "basis")
        )
```

In `fetch_latest_vrp_macro_signals`, add `*, basis: str = "eod"` and filter on it:

```python
    def fetch_latest_vrp_macro_signals(
        self, names: list[str] | None = None, *, basis: str = "eod"
    ) -> list[dict[str, Any]]:
        select_cols = ", ".join(_COLUMNS) + ", created_at"
        where = "WHERE basis = %s "
        params: tuple[Any, ...] = (basis,)
        if names:
            where += "AND name = ANY(%s) "
            params = (basis, [n.upper() for n in names])
        sql = (
            f"SELECT DISTINCT ON (name) {select_cols} "
            f"FROM {self._schema}.vrp_macro_signal_daily "
            f"{where}"
            "ORDER BY name, snapshot_date DESC"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            keys = [d.name for d in cur.description or []]
            return [dict(zip(keys, row, strict=False)) for row in cur.fetchall()]
```

- [ ] **Step 6: Run tests, verify pass**

Run: `uv run pytest tests/integration/storage/test_vrp_macro_signal_basis.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/migrations/084_vrp_macro_signal_basis.sql src/uw_scan/storage/vrp_macro_signal.py tests/integration/storage/test_vrp_macro_signal_basis.py
git commit -m "feat(vrp-signal): add basis column to vrp_macro_signal_daily (live/eod coexist)"
```

---

### Task 2: Engine — `current_macro_signal_live()`

**Files:**

- Modify: `src/uw_scan/reports/vrp_macro_signal.py` (add function after `current_macro_signal`)
- Test: `tests/integration/reports/test_vrp_macro_signal_live.py`

**Interfaces:**

- Consumes: `load_index_vol`, `size_weight`, `build_bull_put_spread`, `MacroSignal`, `MacroSignalConfig`, `WINNER` (all already in the module); `statistics.fmean, pstdev`.
- Produces: `current_macro_signal_live(repo, settings, name="SPX", cfg=WINNER, *, live_spot: float, live_iv: float, as_of=None, lake_root=None) -> MacroSignal`. Returns a `MacroSignal` whose `spot`/`iv` are the live inputs, `rv20`/`vrp`/`vrp_z` are recomputed against the EOD distribution, `as_of` is the EOD vol date used.

- [ ] **Step 1: Write the failing tests**

Create `tests/integration/reports/test_vrp_macro_signal_live.py`. The key correctness anchor: feeding the live function the _latest EOD spot/iv_ must reproduce the EOD `vrp_z` (within float tolerance) — same trailing-252d population z-score convention.

```python
import math
import pytest
from uw_scan.reports.vrp_macro_signal import (
    WINNER, MacroSignal, current_macro_signal, current_macro_signal_live,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol


class _FakeSettings:
    vrp_risk_free_rate = 0.04
    rth_tz = "America/New_York"


def test_live_matches_eod_when_fed_eod_inputs(repository):
    """Invariant: live(eod_spot, eod_iv) reproduces the EOD signal's vrp_z."""
    settings = _FakeSettings()
    eod = current_macro_signal(repository, settings, "SPX", WINNER)
    live = current_macro_signal_live(
        repository, settings, "SPX", WINNER, live_spot=eod.spot, live_iv=eod.iv,
    )
    assert live.vrp_z == pytest.approx(eod.vrp_z, abs=1e-9)
    assert live.action == eod.action


def test_high_live_iv_triggers_trade(repository):
    """A live IV well above the EOD distribution pushes vrp_z up → TRADE, w>0."""
    settings = _FakeSettings()
    eod = current_macro_signal(repository, settings, "SPX", WINNER)
    live = current_macro_signal_live(
        repository, settings, "SPX", WINNER, live_spot=eod.spot, live_iv=eod.iv + 0.10,
    )
    assert live.vrp_z > (eod.vrp_z or 0)
    assert live.action == "TRADE" and live.weight > 0
    assert live.short_put is not None and live.max_loss is not None


def test_bad_tick_raises(repository):
    """Zero/negative VIX (live_iv<=0) or spot must raise → endpoint/worker fall back."""
    import pytest as _pytest
    settings = _FakeSettings()
    with _pytest.raises(ValueError):
        current_macro_signal_live(repository, settings, "SPX", WINNER, live_spot=7500.0, live_iv=0.0)
    with _pytest.raises(ValueError):
        current_macro_signal_live(repository, settings, "SPX", WINNER, live_spot=0.0, live_iv=0.16)
```

(DB-backed: reuse the SPX `vol_index_daily` seeding in `tests/integration/reports/test_vrp_macro_signal.py` — it already drives `current_macro_signal` end-to-end with ≥252 rows — and the `seeded_db_empty_cards` fixture. `_FakeSettings` only needs `vrp_risk_free_rate` + `rth_tz`; or reuse that test's real `Settings` fixture.)

- [ ] **Step 2: Run, verify it fails**

Run: `uv run pytest tests/integration/reports/test_vrp_macro_signal_live.py -v`
Expected: FAIL — `cannot import name 'current_macro_signal_live'`.

- [ ] **Step 3: Implement `current_macro_signal_live`**

In `src/uw_scan/reports/vrp_macro_signal.py` (`fmean, pstdev` are **already imported** at module top, line 33), add after `current_macro_signal`:

```python
def current_macro_signal_live(
    repo,
    settings,
    name: str = "SPX",
    cfg: MacroSignalConfig = WINNER,
    *,
    live_spot: float,
    live_iv: float,
    as_of: _date | None = None,
    lake_root=None,
) -> MacroSignal:
    """Live variant of `current_macro_signal`: spot/iv come from an intraday quote
    (index spot + VIX/100), while rv20 and the trailing-252d vrp distribution are the
    latest EOD values. vrp_z is recomputed as the EOD path does — population z-score of
    `live_iv - rv20` against the trailing `z_window` EOD vrp values (matching
    vrp_macro_drawdown._build_loaded: fmean/pstdev, z_window=252)."""
    # Guard bad ticks (zero/negative VIX or spot). The EOD path skips rows with iv<=0;
    # do the same here. Raising ValueError lets the endpoint fall back to EOD and the
    # worker's per-leg try/except skip — never feed a garbage iv into build_bull_put_spread.
    if live_iv <= 0 or live_spot <= 0:
        raise ValueError(f"{name}: non-positive live quote (spot={live_spot}, iv={live_iv})")
    loaded = load_index_vol(repo, name, lake_root=lake_root)
    # latest EOD row with a usable rv (rv is None for the first rv_window days);
    # capture its index directly — do NOT use list.index() (rows are dicts → ambiguous).
    eod = None
    eod_idx = -1
    n = len(loaded.rows)
    for back, row in enumerate(reversed(loaded.rows)):
        if as_of is not None and row["market_date"] > as_of:
            continue
        if row.get("rv") is not None:
            eod = row
            eod_idx = n - 1 - back
            break
    if eod is None:
        raise ValueError(f"no usable {name} rv row on or before {as_of or 'latest'}")
    rv20 = float(eod["rv"])
    live_vrp = live_iv - rv20
    # trailing-252 EOD vrp values up to AND INCLUDING the chosen EOD row — matches
    # vrp_macro_drawdown._build_loaded (line 157 appends vrp before the window slice),
    # so feeding live_iv == eod_iv reproduces the EOD vrp_z exactly (the Step-1 invariant).
    hist = [r["vrp"] for r in loaded.rows[: eod_idx + 1] if r["vrp"] is not None]
    z: float | None = None
    if len(hist) >= 252:
        w_ = hist[-252:]
        sd = pstdev(w_)
        z = (live_vrp - fmean(w_)) / sd if sd > 0 else None
    weight = size_weight(z, cfg)  # size_weight returns 0.0 when z is None
    common = dict(
        name=name, as_of=eod["market_date"], spot=live_spot, iv=live_iv,
        rv20=rv20, vrp=live_vrp, vrp_z=z, hold_days=cfg.hold_days,
        short_delta=cfg.short_delta, wing_delta=cfg.wing_delta,
    )
    if weight <= 0:
        return MacroSignal(
            weight=0.0, action="SKIP", short_put=None, long_put=None,
            credit=None, max_loss=None, put_width=None, **common,
        )
    st = build_bull_put_spread(
        live_spot, live_iv, cfg.hold_days / 252.0, settings.vrp_risk_free_rate,
        short_delta=cfg.short_delta, wing_delta=cfg.wing_delta,
    )
    return MacroSignal(
        weight=weight, action="TRADE", short_put=st.short_put, long_put=st.long_put,
        credit=st.credit, max_loss=st.max_loss, put_width=st.put_width, **common,
    )
```

Note: `size_weight(z: float | None, cfg)` already maps `z is None → 0.0` (verified in the engine), so `weight = size_weight(z, cfg)` is safe with a None z and a `TRADE` never fires on insufficient history.

**vrp_z convention (deliberate, reviewed — codex-review ISSUE-1).** The live z measures today's `live_vrp` against the trailing-252 **EOD** vrp distribution (`hist[-252:]`, the 252 EOD values ending at the latest EOD row), _not_ including `live_vrp` itself. This (a) is the standard "z-score of a new observation vs a rolling reference distribution," (b) is well-defined whether or not today's EOD bar exists yet, and (c) **exactly reproduces the EOD `vrp_z`** when `live_iv == eod_iv` (the Step-1 invariant), because the window then equals the EOD path's own `vrp_hist[-252:]`. Codex proposed including `live_vrp` in the window via `(hist[:-1] + [live_vrp])[-252:]` for "parity" with `_build_loaded` (which appends the bar before slicing). That specific form is rejected: it **drops the latest EOD bar** (`hist[:-1]`), an off-by-one; the true "today is a new bar" window would be `(hist + [live_vrp])[-252:]`, which _breaks_ the invariant (when `live==eod` it duplicates the last bar and drops the oldest). The self-inclusion difference is O(1/252) on mean/std — negligible at the z=0/0.5 gate — so the invariant-preserving, cleaner exclusion is the chosen convention. Keep this comment in the code.

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/integration/reports/test_vrp_macro_signal_live.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_macro_signal.py tests/integration/reports/test_vrp_macro_signal_live.py
git commit -m "feat(vrp-signal): current_macro_signal_live — intraday VIX -> live vrp_z vs EOD distribution"
```

---

### Task 3: Worker — persist `basis='live'` SPX row in `regime_live_scan_once`

**Files:**

- Modify: `src/uw_scan/worker/jobs/regime_live.py`
- Test: `tests/integration/worker/test_regime_live_vrp.py`

**Interfaces:**

- Consumes: `current_macro_signal_live` (Task 2), `upsert_vrp_macro_signal(..., basis="live")` (Task 1), `load_live_quotes` (existing), `WINNER`.
- Produces: after `regime_live_scan_once` runs with fresh SPX+VIX quotes, a `vrp_macro_signal_daily` row with `basis='live'`, `name='SPX'`, `snapshot_date=today`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/worker/test_regime_live_vrp.py`. Seed SPX `vol_index_daily` (reuse the vrp test seeding helper) and an intraday quote for SPX + VIX fresh enough to pass `regime_live_quote_max_age_seconds`, then assert a live row lands.

```python
from uw_scan.worker.jobs.regime_live import regime_live_scan_once


def test_regime_live_persists_vrp_live_spx(repository, live_settings, seed_spx_vol, seed_fresh_quotes):
    # seed_spx_vol: inserts SPX vol_index_daily (>=252 rows so vrp_z is defined)
    # seed_fresh_quotes: inserts intraday_quote rows for SPX (spot) + VIX (level) within max_age
    result = regime_live_scan_once(repository, live_settings)
    assert result["status"] != "skipped_no_fresh_quotes"
    live = repository.fetch_latest_vrp_macro_signals(["SPX"], basis="live")
    assert len(live) == 1
    # the worker stamps ET date — assert against ET, not the host clock (Codex ISSUE-2)
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert live[0]["snapshot_date"] == datetime.now(ZoneInfo("America/New_York")).date()
    assert live[0]["action"] in ("TRADE", "SKIP")
```

(Define `live_settings`, `seed_spx_vol`, `seed_fresh_quotes` fixtures in the test file or local conftest, mirroring the existing `tests/integration/worker/` regime-live tests. If a `regime_live` integration test already exists, copy its fixture wiring verbatim.)

- [ ] **Step 2: Run, verify it fails**

Run: `uv run pytest tests/integration/worker/test_regime_live_vrp.py -v`
Expected: FAIL — no `basis='live'` SPX row (worker doesn't write one yet).

- [ ] **Step 3: Add the live VRP persist to `regime_live_scan_once`**

In `src/uw_scan/worker/jobs/regime_live.py`, import at top:

```python
from uw_scan.reports.vrp_macro_signal import WINNER, current_macro_signal_live
```

Inside `regime_live_scan_once`, after the existing cri/vcg `run_live` calls and before returning, add an isolated VRP block (SPX-only; quotes already loaded as `quotes`):

```python
    # VRP macro short-vol live (SPX only — VIX + SPX are the macro inputs in
    # regime_ws_symbols). Isolated: a vol-data gap here never blocks cri/vcg.
    vrp_status = "skipped"
    spx_q = quotes.get("SPX")
    vix_q = quotes.get("VIX")
    if spx_q is not None and vix_q is not None:
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            sig = current_macro_signal_live(
                repo, settings, "SPX", WINNER,
                live_spot=float(spx_q.price), live_iv=float(vix_q.price) / 100.0,
            )
            repo.upsert_vrp_macro_signal(
                name="SPX",
                snapshot_date=datetime.now(ZoneInfo(settings.rth_tz)).date(),
                as_of=sig.as_of, spot=sig.spot, iv=sig.iv, rv20=sig.rv20, vrp=sig.vrp,
                vrp_z=sig.vrp_z, weight=sig.weight, action=sig.action,
                short_put=sig.short_put, long_put=sig.long_put, put_width=sig.put_width,
                credit=sig.credit, max_loss=sig.max_loss, hold_days=sig.hold_days,
                short_delta=sig.short_delta, wing_delta=sig.wing_delta,
                bt_n=None, bt_sharpe=None, bt_maxdd=None, bt_annror=None, bt_calmar=None,
                config=None, basis="live",
            )
            repo.conn.commit()
            vrp_status = "ok"
        except Exception as exc:  # noqa: BLE001 — per-leg isolation
            repo.conn.rollback()
            log.warning("regime_live vrp leg failed: %r", exc)
            vrp_status = "failed"
```

Add `"vrp": vrp_status` to the returned status dict (find the existing `return {...}` and add the key).

- [ ] **Step 4: Run, verify pass**

Run: `uv run pytest tests/integration/worker/test_regime_live_vrp.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/regime_live.py tests/integration/worker/test_regime_live_vrp.py
git commit -m "feat(vrp-signal): regime_live_scan persists basis=live SPX signal every 5 min"
```

---

### Task 4: API — `GET /vrp-macro-signal/live` + schema

**Files:**

- Modify: `src/uw_scan/api/schemas.py` (add `VrpMacroSignalLiveResponse`)
- Modify: `src/uw_scan/api/routers/regime.py` (add handler + imports)
- Test: `tests/integration/api/test_vrp_macro_signal_live_api.py`

**Interfaces:**

- Consumes: `current_macro_signal_live` (Task 2), `fetch_latest_vrp_macro_signals(..., basis=...)` (Task 1), `load_live_quotes`, `_active_ws_source` (existing in regime.py), `RegimeLiveQuote` (existing schema).
- Produces: `GET /api/regime/vrp-macro-signal/live` → `VrpMacroSignalLiveResponse{status, basis, signal, live_quotes, active_source}`.

- [ ] **Step 1: Add the response schema**

In `src/uw_scan/api/schemas.py`, after `VrpMacroSignalResponse`, add (reusing the existing `RegimeLiveQuote` model and `Literal`):

```python
class VrpMacroSignalLiveResponse(BaseModel):
    """Live (intraday) VRP macro short-vol signal for SPX. `basis='live'` when computed
    from fresh quotes; `basis='eod'` when it falls back to the latest nightly snapshot.
    `signal` carries the same fields as the EOD row (bt_* may be NULL on the live path)."""

    status: str = "ok"
    basis: Literal["live", "eod"] = "eod"
    signal: VrpMacroSignalRow | None = None
    live_quotes: dict[str, RegimeLiveQuote] = Field(default_factory=dict)
    active_source: str | None = None
```

(`live_quotes` is a **dict keyed by symbol** — matches `CriLiveResponse.live_quotes: dict[str, RegimeLiveQuote]`; `RegimeLiveQuote` is `{price, quoted_at: datetime, source}` with **no symbol field**. `Literal` and `RegimeLiveQuote` are already imported/defined above in `schemas.py` — `CriLiveResponse` uses both.)

- [ ] **Step 2: Write the failing API test**

Create `tests/integration/api/test_vrp_macro_signal_live_api.py`:

```python
def test_live_returns_live_basis_with_fresh_quotes(api_client, seed_spx_vol, seed_fresh_quotes):
    r = api_client.get("/api/regime/vrp-macro-signal/live")
    assert r.status_code == 200
    body = r.json()
    assert body["basis"] == "live"
    assert body["signal"]["name"] == "SPX"
    assert body["signal"]["action"] in ("TRADE", "SKIP")


def test_live_falls_back_to_eod_when_no_fresh_quotes(api_client, seed_spx_vol, seed_eod_signal):
    # seed_eod_signal: one vrp_macro_signal_daily row basis='eod' name='SPX'; no fresh quotes
    r = api_client.get("/api/regime/vrp-macro-signal/live")
    assert r.status_code == 200
    body = r.json()
    assert body["basis"] == "eod"
    assert body["signal"]["name"] == "SPX"
```

(Reuse the existing FastAPI `api_client` fixture from `tests/integration/api/conftest.py` and the seeding fixtures from Task 3.)

- [ ] **Step 3: Run, verify it fails**

Run: `uv run pytest tests/integration/api/test_vrp_macro_signal_live_api.py -v`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 4: Add the handler**

In `src/uw_scan/api/routers/regime.py`, add `VrpMacroSignalLiveResponse` to the `from uw_scan.api.schemas import (...)` block and `current_macro_signal_live` to the reports import, then add after `get_vrp_macro_signal`:

```python
@router.get("/vrp-macro-signal/live", response_model=VrpMacroSignalLiveResponse)
def get_vrp_macro_signal_live(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VrpMacroSignalLiveResponse:
    """Live SPX VRP macro short-vol signal: intraday VIX → live vrp_z (rv20/distribution
    from EOD). Falls back to the latest nightly basis='eod' snapshot when quotes are
    stale. Mirrors /cri/live; does not persist (the 5-min job does that)."""
    today_et = datetime.now(ZoneInfo(settings.rth_tz)).date()  # match the worker's ET date
    quotes = load_live_quotes(
        repo, settings.regime_ws_symbols,
        max_age_seconds=settings.regime_live_quote_max_age_seconds,
    )
    spx_q, vix_q = quotes.get("SPX"), quotes.get("VIX")
    if spx_q is not None and vix_q is not None:
        try:
            sig = current_macro_signal_live(
                repo, settings, "SPX", WINNER,
                live_spot=float(spx_q.price), live_iv=float(vix_q.price) / 100.0,
            )
        except ValueError:
            sig = None
        if sig is not None:
            # merge static backtest headline from the latest EOD row, if present
            eod_rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
            bt = eod_rows[0] if eod_rows else {}
            row = VrpMacroSignalRow(
                name=sig.name, snapshot_date=today_et, as_of=sig.as_of,
                spot=sig.spot, iv=sig.iv, rv20=sig.rv20, vrp=sig.vrp, vrp_z=sig.vrp_z,
                weight=sig.weight, action=sig.action, short_put=sig.short_put,
                long_put=sig.long_put, put_width=sig.put_width, credit=sig.credit,
                max_loss=sig.max_loss, hold_days=sig.hold_days,
                short_delta=sig.short_delta, wing_delta=sig.wing_delta,
                bt_n=bt.get("bt_n"), bt_sharpe=bt.get("bt_sharpe"),
                bt_maxdd=bt.get("bt_maxdd"), bt_annror=bt.get("bt_annror"),
                bt_calmar=bt.get("bt_calmar"),
            )
            return VrpMacroSignalLiveResponse(
                basis="live", signal=row,
                live_quotes={
                    s: RegimeLiveQuote(price=float(q.price), quoted_at=q.quoted_at,
                                       source=q.source)
                    for s, q in (("SPX", spx_q), ("VIX", vix_q))
                },
                active_source=_active_ws_source(repo),
            )
    eod_rows = repo.fetch_latest_vrp_macro_signals(["SPX"], basis="eod")
    if not eod_rows:
        return VrpMacroSignalLiveResponse(basis="eod", signal=None)
    return VrpMacroSignalLiveResponse(basis="eod", signal=VrpMacroSignalRow(
        **{k: eod_rows[0].get(k) for k in VrpMacroSignalRow.model_fields}
    ))
```

(`RegimeLiveQuote(price: float, quoted_at: datetime, source: str | None)` — pass `q.quoted_at` as a datetime, not `.isoformat()`; the symbol is the dict key. Ensure regime.py imports `from datetime import datetime` and `from zoneinfo import ZoneInfo` — `today_et` uses the ET tz so the live row's `snapshot_date` matches the worker's, not the host clock.)

- [ ] **Step 5: Run, verify pass + OpenAPI snapshot**

Run: `uv run pytest tests/integration/api/test_vrp_macro_signal_live_api.py -v`
Expected: PASS.
Then regenerate the OpenAPI snapshot if the repo gates on it: `uv run python scripts/check_openapi_snapshot.py --update` (or the repo's documented command) and confirm only the _additive_ `VrpMacroSignalLiveResponse` component changed.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/api/schemas.py src/uw_scan/api/routers/regime.py tests/integration/api/test_vrp_macro_signal_live_api.py
git commit -m "feat(vrp-signal): GET /api/regime/vrp-macro-signal/live (live + eod fallback)"
```

---

### Task 5: Web — Macro Short-Vol regime card

**Files:**

- Modify: `web/lib/regime/api.ts`
- Create: `web/lib/regime/useVrpMacroLive.ts`
- Create: `web/components/regime/MacroShortVolSubTab.tsx`
- Modify: `web/components/regime/RegimePanel.tsx`
- Modify: `web/app/regime/[[...tab]]/page.tsx`
- Modify (generated): `web/lib/types.ts`
- Test: `web/components/regime/__tests__/MacroShortVolSubTab.test.tsx`

**Interfaces:**

- Consumes: `GET /api/regime/vrp-macro-signal/live` → `components["schemas"]["VrpMacroSignalLiveResponse"]`.
- Produces: a `macro-short-vol` regime tab rendering the live SPX signal.

- [ ] **Step 1: Regenerate types from the live API**

With the API importable, run: `cd web && npm run gen:types`
Expected: `web/lib/types.ts` now contains `VrpMacroSignalLiveResponse`. Verify: `grep -c VrpMacroSignalLiveResponse web/lib/types.ts` → ≥1. Do not hand-edit the file.

- [ ] **Step 2: Add the endpoint + hook**

In `web/lib/regime/api.ts`, add to the `regimeApi` object (the base const is `API`, and entries spell the **full** `/api/regime/...` path — mirror `cri_live`):

```ts
  vrp_macro_signal: () => `${API}/api/regime/vrp-macro-signal`,
  vrp_macro_signal_live: () => `${API}/api/regime/vrp-macro-signal/live`,
```

Create `web/lib/regime/useVrpMacroLive.ts` — mirror `useCriLive.ts` exactly (relative imports `../types` + `./api`, `UseSyncReturn` return type, and the **second positional `true`** arg to `useSyncHook`):

```ts
"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VrpMacroLive = components["schemas"]["VrpMacroSignalLiveResponse"];

export function useVrpMacroLive(): UseSyncReturn<VrpMacroLive> {
  // GET-only (hasPost:false): every poll is a server-side live recompute; the
  // 5-min worker owns persistence (mirrors useCriLive). Weekly signal → 30s poll.
  return useSyncHook<VrpMacroLive>(
    {
      endpoint: regimeApi.vrp_macro_signal_live(),
      interval: 30_000,
      hasPost: false,
    },
    true,
  );
}
```

(Our `VrpMacroSignalLiveResponse` has no `scan_time`, so omit `extractTimestamp`. Confirm `useSyncHook`'s optional fields have defaults by reading `useSyncHook.ts`; if `extractTimestamp` is required, pass `extractTimestamp: () => null`.)

- [ ] **Step 3: Write the failing card test**

Create `web/components/regime/__tests__/MacroShortVolSubTab.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import MacroShortVolSubTab from "../MacroShortVolSubTab";

vi.mock("@/lib/regime/useVrpMacroLive", () => ({
  useVrpMacroLive: () => ({
    data: {
      status: "ok",
      basis: "live",
      active_source: "xenon_ws",
      live_quotes: [],
      signal: {
        name: "SPX",
        snapshot_date: "2026-06-24",
        as_of: "2026-06-23",
        spot: 7500,
        iv: 0.16,
        rv20: 0.12,
        vrp: 0.04,
        vrp_z: -1.95,
        weight: 0,
        action: "SKIP",
        short_put: null,
        long_put: null,
        put_width: null,
        credit: null,
        max_loss: null,
        hold_days: 30,
        short_delta: 0.25,
        wing_delta: 0.125,
        bt_n: 522,
        bt_sharpe: 1.65,
        bt_maxdd: -0.8,
        bt_annror: 0.53,
        bt_calmar: 0.66,
      },
    },
    isLoading: false,
    error: null,
  }),
}));

describe("MacroShortVolSubTab", () => {
  it("renders SKIP when weight is 0", () => {
    render(<MacroShortVolSubTab />);
    expect(screen.getByText(/SKIP/i)).toBeInTheDocument();
    expect(screen.getByText(/-1\.95/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run, verify it fails**

Run: `cd web && npx vitest run components/regime/__tests__/MacroShortVolSubTab.test.tsx`
Expected: FAIL — cannot find `../MacroShortVolSubTab`.

- [ ] **Step 5: Build the card**

Create `web/components/regime/MacroShortVolSubTab.tsx` (a read-only card; match the Argon dark-theme styling of `CriSubTab.tsx` — copy its container/typography classes):

```tsx
"use client";
import { useVrpMacroLive } from "@/lib/regime/useVrpMacroLive";

export default function MacroShortVolSubTab() {
  const { data, isLoading } = useVrpMacroLive();
  if (isLoading)
    return <div className="p-4 text-sm text-neutral-400">Loading…</div>;
  if (!data?.signal)
    return (
      <div className="p-4 text-sm text-neutral-500">
        No macro short-vol signal yet (no live quote and no EOD snapshot).
      </div>
    );
  const s = data.signal;
  const trade = s.action === "TRADE";
  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-neutral-200">
          Macro Short-Vol · SPX
        </h3>
        <span className="text-xs text-neutral-500">
          {data.basis === "live"
            ? `live · ${data.active_source ?? ""}`
            : "EOD snapshot"}
        </span>
      </div>
      <div
        className={`text-2xl font-bold ${trade ? "text-emerald-400" : "text-neutral-400"}`}
      >
        {s.action}
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        <dt className="text-neutral-500">vrp_z</dt>
        <dd className="text-right tabular-nums">
          {s.vrp_z?.toFixed(2) ?? "—"}
        </dd>
        <dt className="text-neutral-500">weight</dt>
        <dd className="text-right tabular-nums">{s.weight.toFixed(2)}</dd>
        <dt className="text-neutral-500">IV / RV20</dt>
        <dd className="text-right tabular-nums">
          {(s.iv * 100).toFixed(1)}% /{" "}
          {s.rv20 != null ? (s.rv20 * 100).toFixed(1) + "%" : "—"}
        </dd>
        {trade && (
          <>
            <dt className="text-neutral-500">short / wing</dt>
            <dd className="text-right tabular-nums">
              {s.short_put?.toFixed(0)} / {s.long_put?.toFixed(0)}
            </dd>
            <dt className="text-neutral-500">credit / maxloss</dt>
            <dd className="text-right tabular-nums">
              {s.credit?.toFixed(2)} / {s.max_loss?.toFixed(2)}
            </dd>
          </>
        )}
        {s.bt_sharpe != null && (
          <>
            <dt className="text-neutral-500">backtest Sharpe</dt>
            <dd className="text-right tabular-nums">
              {s.bt_sharpe.toFixed(2)}
            </dd>
          </>
        )}
      </dl>
      <p className="text-xs text-neutral-500">
        Bull put spread, {s.short_delta}Δ / {s.wing_delta}Δ, ~{s.hold_days}-day
        hold, weekly, vrp-z gated. Flat-vol modeled credit (conservative floor).{" "}
        {trade ? "" : "Vol not rich enough — stand aside."}
      </p>
    </div>
  );
}
```

- [ ] **Step 6: Wire the tab**

In `web/components/regime/RegimePanel.tsx`: extend the `RegimeTab` union (`"cri" | "vcg" | "grg" | "canary" | "gex" | "validation"`) with `| "macro-short-vol"`, add `{ id: "macro-short-vol", label: "Macro Short-Vol" }` to the `TABS` array, import `MacroShortVolSubTab`, and add `{activeTab === "macro-short-vol" && <MacroShortVolSubTab />}` to the render switch. (The `VALID` set is auto-derived from `TABS.map`, so no separate edit there.)

In `web/app/regime/[[...tab]]/page.tsx`: add `"macro-short-vol"` to the manually-listed `VALID_TABS` set (line 9).

The component imports the hook as `import { useVrpMacroLive } from "@/lib/regime/useVrpMacroLive"` — the **same specifier the card test mocks**. This matches verified conventions: `CriSubTab.tsx` imports its hook via `@/lib/regime/useCriLive`, the hook file itself uses relative `../types`/`./api` (like `useCriLive.ts`), and `vi.mock("@/...")` is the established test pattern (`web/vitest.config.ts` wires the `@` alias). No deviation needed.

- [ ] **Step 7: Run card test + lint/typecheck**

Run: `cd web && npx vitest run components/regime/__tests__/MacroShortVolSubTab.test.tsx`
Expected: PASS.
Run: `cd web && npm run lint && npx tsc --noEmit`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add web/lib/regime/api.ts web/lib/regime/useVrpMacroLive.ts web/components/regime/MacroShortVolSubTab.tsx web/components/regime/RegimePanel.tsx "web/app/regime/[[...tab]]/page.tsx" web/components/regime/__tests__/MacroShortVolSubTab.test.tsx web/lib/types.ts
git commit -m "feat(vrp-signal): Macro Short-Vol regime card (live SPX TRADE/SKIP readout)"
```

---

### Task 6: Docs + full-suite verification

**Files:**

- Modify: `CLAUDE.md` (root), `AGENTS.md`

**Interfaces:** none (docs + verification only).

- [ ] **Step 1: Update the where-to-look table**

In `CLAUDE.md` (root), in the "Where to look first" table, extend the existing regime-live row (or add one) to mention the macro short-vol live slice, e.g.:

```
| VRP macro short-vol signal (EOD + live) | `reports/vrp_macro_signal.py` (`current_macro_signal`, `current_macro_signal_live`) + `storage/vrp_macro_signal.py` (basis col) + `worker/jobs/{vrp_macro_signal,regime_live}.py` + `api/routers/regime.py` (`/vrp-macro-signal`, `/vrp-macro-signal/live`) + `web/components/regime/MacroShortVolSubTab.tsx`; migrations 083/084. Live = SPX only |
```

Mirror the same line into `AGENTS.md` (keep both in sync — Global Constraints).

- [ ] **Step 2: Note the schedule (no new job)**

In the same CLAUDE.md regime-live paragraph, add one sentence: the live SPX VRP signal piggybacks the existing `regime_live_scan` 5-min job (no new scheduler entry); the EOD signal stays on `vrp_macro_signal_refresh` @03:45 ET. Confirm `scripts/release/version_sync_check.py` / any doc-lint passes.

- [ ] **Step 3: Run the full gate locally (the CI `lint + unit` job is more than ruff+pytest)**

```bash
uv run ruff check .
uv run python scripts/lint/_lint_except.py        # Guardrail 2
uv run python scripts/release/version_sync_check.py
uv run pytest tests/unit tests/integration -k "vrp_macro or regime_live or vrp_macro_signal_live" -v
cd web && npm run test && npx tsc --noEmit && npm run lint
```

Expected: all green. (On MacBook, integration tests need the forced-local DB env — set `UW_SCAN_DB_HOST=127.0.0.1`, `UW_SCAN_DB_NAME`/`UW_SCAN_TEST_DB_NAME=option_wizard_test`, `UW_SCAN_DB_USER` per `reference_macbook_integration_tests_need_local_db_env`.)

- [ ] **Step 4: Smoke through the real path (not a side-channel)**

Boot the stack (`bash scripts/dev.sh`), hit `GET /api/regime/vrp-macro-signal/live`, confirm a `basis` field + SPX `signal`; load `/regime`, click the **Macro Short-Vol** tab, confirm the card renders the live action. Screenshot to `output/playwright/` if capturing evidence.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md AGENTS.md
git commit -m "docs(vrp-signal): note macro short-vol live slice + schedule"
```

---

## Production-safety notes (adversarial review)

- **Concurrency / write races:** the `/live` endpoint recomputes only (no persist); the 5-min job is the sole live writer and runs `max_instances=1, coalesce=True`. The EOD job (`basis='eod'`) and the live job (`basis='live'`) write **different PK rows** for the same `(name, snapshot_date)` — no conflict. No advisory lock needed.
- **Migration atomicity:** 084 is wrapped in `BEGIN/COMMIT`, so the column-add + PK drop/re-add commit atomically; `DROP CONSTRAINT IF EXISTS` makes replay a no-op. Existing `(name, snapshot_date)` rows were already unique, so defaulting `basis='eod'` cannot create a duplicate PK.
- **Existing-endpoint contract (verify, no regression):** after 084, `get_vrp_macro_signal` calls `fetch_latest_vrp_macro_signals()` which now defaults `basis='eod'` → it keeps returning the EOD signal and correctly **excludes** the new live rows. Confirm `tests/integration/api/test_vrp_macro_signal_endpoint.py` stays green unchanged.
- **Bad ticks:** guarded in the engine (Task 2 — `live_iv<=0`/`live_spot<=0` → ValueError → EOD fallback / worker skip). A single missing leg (SPX present, VIX absent) → endpoint EOD-fallback via the `spx_q is not None and vix_q is not None` gate.
- **Stale-but-fresh quotes:** if quotes pass `max_age` but `vol_index` is days stale, the live signal computes off a stale `rv20`/distribution; the card surfaces `as_of` vs `snapshot_date` so the staleness is visible (this is the existing EOD concern, not new).
- **DST:** `datetime.now(ZoneInfo(settings.rth_tz)).date()` is DST-correct in both worker and endpoint.

## Self-Review

**Spec coverage** (vs the design decisions locked with the user):

- EOD slice reused, not cloned → Tasks 1,3,4 extend `vrp_macro_signal_daily` / engine / endpoint. ✓
- Live 5-min, basis='live', piggyback regime-live WS → Task 3 (worker) + Task 4 (endpoint). ✓
- Surfaced as ONE card on `/regime`, no per-stock UI → Task 5. ✓
- SPX-only live (VIX+SPX in `REGIME_WS_SYMBOLS`) → enforced in Tasks 3–5. ✓
- No captured-IV-surface dependency (correctly dropped) → nothing references it. ✓

**Placeholder scan:** every code step shows real code; the only deferred specifics are fixture _names_ (Tasks 1/3/4 tests) which must match the existing conftest — flagged inline, not invented.

**Type consistency:** `current_macro_signal_live(... , live_spot, live_iv, ...)` signature is identical across Tasks 2/3/4. `upsert_vrp_macro_signal(..., basis=...)` and `fetch_latest_vrp_macro_signals(..., basis=...)` identical across Tasks 1/3/4. `VrpMacroSignalLiveResponse{status,basis,signal,live_quotes,active_source}` identical across Tasks 4/5. `vrp_z` z-score convention (pstdev/fmean, 252-window) matches `vrp_macro_drawdown._build_loaded`.

**Verified in review (Pass 1, against the real repo):** `size_weight(z: float|None)` maps None→0.0 ✓; `RegimeLiveQuote` = `{price, quoted_at: datetime, source}`, `live_quotes` is `dict[str, RegimeLiveQuote]` ✓; `_build_loaded` includes the current vrp in the z-window (line 157) so the live↔eod invariant holds ✓; `084` is the next free migration number (highest is 083) ✓; `_active_ws_source`, `load_live_quotes`, `LiveQuote.{symbol,price,quoted_at,source}`, `regimeApi`/`API` base, `RegimeTab`/`TABS`/`VALID_TABS` all confirmed ✓.

**Also verified in review (Pass 6):** `useSyncHook` requires only `endpoint` (all else optional with defaults — `extractTimestamp` not required) ✓; `web/vitest.config.ts` exists and the `@` alias works (`CriSubTab` imports its hook via `@/lib/regime/useCriLive`; `vi.mock("@/…")` is the established pattern) ✓; the DB fixture is `seeded_db_empty_cards`, the API fixture is `client`, with `SPX_SKIP` / `_seed` / `SESSION` as the seeders ✓.

**Remaining open verifications for the executor (genuinely unconfirmed, cheap to settle at task start):** (a) that `tests/integration/reports/test_vrp_macro_signal.py`'s SPX seeding really provides ≥252 `vol_index_daily` rows and the spot source `load_index_vol` reads (lake vs DB) — needed for the engine **TRADE** test; the SKIP-tolerant worker/API tests don't need it. (d) the repo's exact OpenAPI-snapshot regen command — `tests/integration/api/openapi.snapshot.json` exists and the only expected delta is the additive `VrpMacroSignalLiveResponse` component.
