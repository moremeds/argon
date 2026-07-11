# Technicals Price Pane → lightweight-charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the SVG price/anchor pane on `/stock/[ticker]` Technicals with a lightweight-charts candlestick pane (volume overlay, filled ±1.5σ band, click-to-anchor VWAP persisted one-per-ticker), per the approved spec `docs/superpowers/specs/2026-07-10-technicals-price-pane-lightweight-charts-design.md`.

**Architecture:** Two idempotent migrations widen `technical_daily` with OHLCV (already fetched nightly from apex, currently dropped at `cards/technicals.py:609`) and add a `technical_vwap_anchor` table. A pure `anchored_vwap` deriver + standalone `TechnicalVwapAnchorRepository` + two sanctioned write endpoints on the stock router deliver the VWAP contract; the technicals GET grows `open/high/low/volume` per series row and a `vwap_anchor` field. The frontend swaps `TechnicalsAnchorChart` (SVG) for a new `TechnicalsPriceChart` client component wrapping lightweight-charts v5.2.0, with an adapted vendored bands-indicator primitive for the filled σ-band.

**Tech Stack:** Python 3.13 / FastAPI / psycopg 3 / pandas (backend); Next.js 16 + React 19 + TypeScript + `lightweight-charts@5.2.0` (frontend); pytest + pytest-postgresql, vitest.

## Global Constraints

- **uv only**: `uv run pytest`, never bare `pytest`/`python`/`pip`.
- **Branch**: `feat/technicals-lwc-price-pane`, worktree at `.worktrees/technicals-lwc-price-pane/` (project-root `.worktrees/` is the only canonical location).
- **Commits**: milestone commit per task on the feature branch. NO `Co-Authored-By` or any AI-attribution trailers. Never push to `main`; PR before merge; never merge before CI green.
- **Migrations idempotent** (`IF NOT EXISTS`), header `SET search_path TO uw_scan, public;`. New prefixes `105`/`106` (verified unused as of 2026-07-10 — re-verify at execution time, step 1.2).
- **Module budget**: target <500 lines per Python file. New persistence domain gets its own `storage/technical_vwap_anchor_repository.py` — never append to `repository.py`.
- **Exception handlers** (CI Guardrail 2, `scripts/_lint_except.py` AST check): any new `except` block must use `log.exception(...)`, `repr(exc)`, `traceback`, or `raise`.
- **New temporal table = 2 CI gates**: `technical_vwap_anchor` has `anchor_date DATE` + `computed_at TIMESTAMPTZ`, so it trips `list_unregistered_time_tables()`. It MUST get a `DatasetRegistryEntry` in `reports/data_gap_healer.py` AND the policy doc must be regenerated (Task 5), or `test_zero_unregistered_after_full_registry` and `test_committed_policy_doc_is_in_sync_with_registry` go red.
- **OpenAPI snapshot**: regenerate `tests/integration/api/openapi.snapshot.json` with EXACTLY `sort_keys=True, ensure_ascii=True, indent=2` (Task 6). If `git diff --stat` shows more than the intended additions, STOP and reconcile.
- **`web/lib/types.ts` is generated**: regenerate via openapi-typescript against the NEW app's schema (offline spec dump — Task 7), never hand-edit with the Edit tool (a prettier hook reflows it). Diff must be additive-only.
- **Frontend dep**: `lightweight-charts@5.2.0` exactly (Apache-2.0, verified latest stable). No other new deps.
- **CHANGELOG rides this PR**: `[Unreleased]` entry added in Task 11, before merge.
- **No synthetic market data presented as real**: unit-test fixtures below are hand-computable arithmetic verification vectors following existing repo convention (`_ramp_bars`, `_row(...)` in the existing technicals tests), not purported market observations.
- **MacBook test env gotcha**: if `.env.local` points at the Mac mini, integration tests fail with `InsufficientPrivilege` on DROP SCHEMA. Override in-shell: `UW_SCAN_DB_HOST=127.0.0.1 uv run pytest ...` (shell env wins over `.env.local`).
- **Style stays the same**: all chart colors come from the existing CSS variables, resolved at mount via `getComputedStyle` (canvas cannot read `var(--…)`). Dark-theme values for reference: `--positive #05ad98`, `--negative #e85d6c`, `--accent-warm #f5a623`, `--accent-vol #8b5cf6`, `--accent-vivid #d946a8`, `--text-primary #e2e8f0`, `--text-muted #475569`, `--border-dim #1e293b`.

---

### Task 1: Worktree + dependencies

**Files:** none created in-repo (worktree setup only).

**Interfaces:**
- Consumes: `main` branch HEAD.
- Produces: worktree `.worktrees/technicals-lwc-price-pane/` on branch `feat/technicals-lwc-price-pane` with Python + node deps installed. All later tasks run inside this worktree.

- [ ] **Step 1.1: Create the worktree**

```bash
cd /Users/chenxi/projects/argon
git worktree add .worktrees/technicals-lwc-price-pane -b feat/technicals-lwc-price-pane main
cd .worktrees/technicals-lwc-price-pane
```

- [ ] **Step 1.2: Verify migration prefixes 105/106 are still free** (another branch may have claimed them since planning)

```bash
ls src/uw_scan/storage/migrations/ | grep -E "^10[56]" || echo "105/106 FREE"
git branch -a --contains | cat   # awareness only
```
Expected: `105/106 FREE`. If taken, renumber to the next free prefixes and use those numbers everywhere below.

- [ ] **Step 1.3: Install deps**

```bash
uv sync --extra postgres
cd web && npm ci && cd ..
```
Expected: both succeed. (If `uv run pytest --version` throws `ModuleNotFoundError` later, nuke `.venv` and re-run `uv sync` — stale-shebang gotcha after worktree creation.)

- [ ] **Step 1.4: Baseline check**

```bash
uv run pytest tests/unit/ -q
```
Expected: PASS (green baseline before any change).

---

### Task 2: Migrations 105 + 106

**Files:**
- Create: `src/uw_scan/storage/migrations/105_technical_daily_ohlcv.sql`
- Create: `src/uw_scan/storage/migrations/106_technical_vwap_anchor.sql`

**Interfaces:**
- Consumes: existing `uw_scan.technical_daily` table (migration 101).
- Produces: `technical_daily.open/high/low` (DOUBLE PRECISION), `technical_daily.volume` (BIGINT); table `uw_scan.technical_vwap_anchor(ticker TEXT PK, anchor_date DATE NOT NULL, vwap_snapshot JSONB NOT NULL, computed_at TIMESTAMPTZ NOT NULL DEFAULT now())`. Tasks 3–6 depend on these columns/table. Integration-test DBs pick them up automatically (the `_migrated_settings` fixture applies all migrations).

- [ ] **Step 2.1: Write `105_technical_daily_ohlcv.sql`**

```sql
-- 105_technical_daily_ohlcv.sql
--
-- Carry full OHLCV onto technical_daily (previously close-only) so the
-- Technicals price pane can render candlesticks + volume and anchor VWAP.
-- Values ride the existing nightly full-recompute from apex bars — history
-- self-backfills on each ticker's next refresh; no dedicated backfill.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

ALTER TABLE uw_scan.technical_daily
    ADD COLUMN IF NOT EXISTS open   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS high   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS low    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS volume BIGINT;

COMMIT;
```

- [ ] **Step 2.2: Write `106_technical_vwap_anchor.sql`**

```sql
-- 106_technical_vwap_anchor.sql
--
-- User-set anchored-VWAP state for the Technicals price pane: one anchor per
-- ticker plus the computed [{as_of, vwap}] snapshot (durable record; reads
-- recompute from technical_daily OHLCV when available and fall back to the
-- snapshot). Written only on user click — no scheduled writer. Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.technical_vwap_anchor (
    ticker        TEXT PRIMARY KEY,
    anchor_date   DATE NOT NULL,
    vwap_snapshot JSONB NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
```

- [ ] **Step 2.3: Run the prefix guard and apply locally**

```bash
uv run python scripts/check_migration_prefixes.py
bash scripts/migrate.sh
```
Expected: guard clean; migrate.sh applies both (re-run is a no-op).

- [ ] **Step 2.4: Verify columns/table exist**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "\d uw_scan.technical_daily" -c "\d uw_scan.technical_vwap_anchor"
```
Expected: `open`, `high`, `low`, `volume` on `technical_daily`; `technical_vwap_anchor` exists with the 4 columns.

- [ ] **Step 2.5: Commit**

```bash
git add src/uw_scan/storage/migrations/105_technical_daily_ohlcv.sql \
        src/uw_scan/storage/migrations/106_technical_vwap_anchor.sql
git commit -m "feat(technicals): migrations 105/106 — technical_daily OHLCV columns + technical_vwap_anchor table"
```

---

### Task 3: OHLCV carry-through (cards → storage → worker)

**Files:**
- Modify: `src/uw_scan/cards/technicals.py` (~line 609 in `build_technical_series`, plus the empty-frame column list ~line 591)
- Modify: `src/uw_scan/storage/technicals_repository.py` (`_CORE_COLS` lines 13-26, `upsert_series` SQL lines 94-118, `fetch_series` SELECT lines 144-146, `fetch_latest` SELECT lines 160-162)
- Test: `tests/unit/test_technicals.py` (add one test)
- Test: `tests/integration/storage/test_technicals_repository.py` (add one test)
- Test: `tests/integration/worker/test_technicals_job.py` (add one test)

**Interfaces:**
- Consumes: `bars_frame()` output columns `["as_of","open","high","low","close","volume"]` (already present in the dataframe).
- Produces: `build_technical_series(bars, spy_bars) -> pd.DataFrame` now carries `open/high/low/volume` columns; `series_records(df)` includes them automatically (it filters `_CORE_COLS ∩ df.columns`); `TechnicalsRepository.upsert_series` persists them; `fetch_series`/`fetch_latest` return them as dict keys `open/high/low/volume` (volume is `int | None`). Tasks 4 and 6 read these keys.

- [ ] **Step 3.1: Write the failing unit test** — append to `tests/unit/test_technicals.py` (reuse the file's existing bar-builder helper if one exists; otherwise this local one):

```python
def test_build_technical_series_carries_ohlcv():
    from uw_scan.cards.technicals import build_technical_series

    bars = [
        {
            "time": f"2026-01-{d:02d}T00:00:00Z",
            "open": 100.0 + d,
            "high": 101.0 + d,
            "low": 99.0 + d,
            "close": 100.5 + d,
            "volume": 1_000 * d,
        }
        for d in range(1, 11)
    ]
    out = build_technical_series(bars)
    for col in ("open", "high", "low", "volume"):
        assert col in out.columns, f"{col} missing from series frame"
    assert out["open"].iloc[0] == 101.0
    assert out["high"].iloc[-1] == 111.0
    assert out["volume"].iloc[-1] == 10_000
```

- [ ] **Step 3.2: Run it — must fail**

```bash
uv run pytest tests/unit/test_technicals.py::test_build_technical_series_carries_ohlcv -v
```
Expected: FAIL (`open missing from series frame`).

- [ ] **Step 3.3: Implement the cards change** — in `build_technical_series`:

Line ~609, change:
```python
out = df[["as_of", "close"]].copy()
```
to:
```python
out = df[["as_of", "open", "high", "low", "close", "volume"]].copy()
```

And in the empty-frame early return (~line 591), the columns list becomes (full literal — only `open/high/low/volume` are new, everything else is the existing list verbatim):
```python
            columns=[
                "as_of",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "sma20",
                "sma50",
                "sma200",
                "z_vs_200dma",
                "z_band",
                "sma200_slope_ann",
                "slope_regime",
                "rsi14",
                "macd_hist_atr",
                *SERIES_METRIC_COLS,
                "rs_ratio",
            ]
```

- [ ] **Step 3.4: Run the unit test — must pass**

```bash
uv run pytest tests/unit/test_technicals.py::test_build_technical_series_carries_ohlcv -v
```
Expected: PASS.

- [ ] **Step 3.5: Write the failing repository test** — append to `tests/integration/storage/test_technicals_repository.py`:

```python
def test_upsert_and_fetch_ohlcv_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    trepo = TechnicalsRepository(repo.conn)
    rows = [
        {
            "as_of": date(2026, 7, 6),
            "open": 99.5,
            "high": 101.0,
            "low": 98.0,
            "close": 100.0,
            "volume": 1_234_567.0,  # float in, int out (BIGINT column)
        },
        {
            "as_of": date(2026, 7, 7),
            "open": 100.2,
            "high": 103.0,
            "low": 100.0,
            "close": 102.5,
            "volume": 2_000_000,
        },
    ]
    assert trepo.upsert_series("NVDA", rows) == 2
    got = trepo.fetch_series("NVDA")
    assert got[0]["open"] == 99.5
    assert got[0]["volume"] == 1_234_567
    assert isinstance(got[0]["volume"], int)
    assert got[1]["high"] == 103.0
    latest = trepo.fetch_latest("NVDA")
    assert latest["low"] == 100.0
    assert latest["volume"] == 2_000_000
    # re-upsert with changed OHLCV must overwrite (ON CONFLICT set-list)
    rows[1]["high"] = 104.0
    trepo.upsert_series("NVDA", rows)
    assert trepo.fetch_series("NVDA")[1]["high"] == 104.0
```

- [ ] **Step 3.6: Run it — must fail**

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/storage/test_technicals_repository.py::test_upsert_and_fetch_ohlcv_roundtrip -v
```
Expected: FAIL (`KeyError: 'open'` or column-count mismatch).

- [ ] **Step 3.7: Implement the repository change** — `src/uw_scan/storage/technicals_repository.py`:

`_CORE_COLS` becomes:
```python
_CORE_COLS = (
    "as_of",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "sma20",
    "sma50",
    "sma200",
    "z_vs_200dma",
    "z_band",
    "sma200_slope_ann",
    "slope_regime",
    "rsi14",
    "macd_hist_atr",
    "rs_ratio",
)
```

In `upsert_series`, after `core = {k: r.get(k) for k in _CORE_COLS}` add the BIGINT coercion (pandas emits float64 volume):
```python
            if core.get("volume") is not None:
                core["volume"] = int(round(core["volume"]))
```

The SQL becomes:
```python
        sql = """
            INSERT INTO technical_daily
                (ticker, as_of, open, high, low, close, volume, sma20, sma50,
                 sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime,
                 rsi14, macd_hist_atr, rs_ratio, metrics)
            VALUES
                (%(ticker)s, %(as_of)s, %(open)s, %(high)s, %(low)s, %(close)s,
                 %(volume)s, %(sma20)s, %(sma50)s, %(sma200)s, %(z_vs_200dma)s,
                 %(z_band)s, %(sma200_slope_ann)s, %(slope_regime)s, %(rsi14)s,
                 %(macd_hist_atr)s, %(rs_ratio)s, %(metrics)s)
            ON CONFLICT (ticker, as_of) DO UPDATE SET
                open             = EXCLUDED.open,
                high             = EXCLUDED.high,
                low              = EXCLUDED.low,
                close            = EXCLUDED.close,
                volume           = EXCLUDED.volume,
                sma20            = EXCLUDED.sma20,
                sma50            = EXCLUDED.sma50,
                sma200           = EXCLUDED.sma200,
                z_vs_200dma      = EXCLUDED.z_vs_200dma,
                z_band           = EXCLUDED.z_band,
                sma200_slope_ann = EXCLUDED.sma200_slope_ann,
                slope_regime     = EXCLUDED.slope_regime,
                rsi14            = EXCLUDED.rsi14,
                macd_hist_atr    = EXCLUDED.macd_hist_atr,
                rs_ratio         = EXCLUDED.rs_ratio,
                metrics          = EXCLUDED.metrics,
                inserted_at      = now()
        """
```

`fetch_series` inner SELECT column list becomes:
```sql
                SELECT as_of, open, high, low, close, volume, sma20, sma50,
                       sma200, z_vs_200dma, z_band, sma200_slope_ann,
                       slope_regime, rsi14, macd_hist_atr, rs_ratio, metrics,
                       detail, forward_returns
```

`fetch_latest` SELECT column list becomes:
```sql
            SELECT ticker, as_of, open, high, low, close, volume, sma20, sma50,
                   sma200, z_vs_200dma, z_band, sma200_slope_ann, slope_regime,
                   rsi14, macd_hist_atr, rs_ratio, bars_n, detail,
                   forward_returns
```

- [ ] **Step 3.8: Run repository test — must pass**

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/storage/test_technicals_repository.py -v
```
Expected: new test PASS, all pre-existing tests in the file still PASS.

- [ ] **Step 3.9: Write the worker end-to-end test** — append to `tests/integration/worker/test_technicals_job.py` (reuse its existing `_fake_bars` / `_settings` helpers; confirm `_fake_bars` emits `open/high/low/volume` keys — if it only emits `close`, extend the helper to emit all five fields, keeping existing assertions green):

```python
def test_refresh_persists_ohlcv(seeded_db_empty_cards, monkeypatch):
    repo = seeded_db_empty_cards
    bars = _fake_bars(400)
    monkeypatch.setattr(
        "uw_scan.worker.jobs.technical_daily_refresh.fetch_daily_bars",
        lambda t, **kw: bars,
    )
    technical_daily_refresh(repo=repo, settings=_settings(), ticker_filter=["NVDA"])
    trepo = TechnicalsRepository(repo.conn)
    series = trepo.fetch_series("NVDA")
    assert len(series) == 400
    last = series[-1]
    for k in ("open", "high", "low", "volume"):
        assert last[k] is not None, f"{k} not persisted by the refresh job"
```

- [ ] **Step 3.10: Run it — must pass** (no worker-code change should be needed: the job already flows `build_technical_series` → `series_records` → `upsert_series`)

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/worker/test_technicals_job.py -v
```
Expected: PASS. If it fails because `_fake_bars` lacks OHLCV keys, fix the helper (Step 3.9 note), not the job.

- [ ] **Step 3.11: Run lint + the full unit suite**

```bash
uv run ruff check src/ tests/ scripts/
uv run pytest tests/unit/ -q
```
Expected: clean.

- [ ] **Step 3.12: Commit**

```bash
git add src/uw_scan/cards/technicals.py src/uw_scan/storage/technicals_repository.py \
        tests/unit/test_technicals.py tests/integration/storage/test_technicals_repository.py \
        tests/integration/worker/test_technicals_job.py
git commit -m "feat(technicals): persist OHLCV through the daily series write path"
```

---

### Task 4: `anchored_vwap` pure deriver

**Files:**
- Modify: `src/uw_scan/cards/technicals.py` (append one function at module end)
- Test: `tests/unit/cards/test_anchored_vwap.py` (new)

**Interfaces:**
- Consumes: series-row dicts with keys `as_of: date`, `high/low/close: float|None`, `volume: int|None` (the exact shape `TechnicalsRepository.fetch_series` returns after Task 3).
- Produces: `anchored_vwap(rows: list[Mapping[str, Any]], anchor_date: date) -> list[dict]` returning `[{"as_of": date, "vwap": float}]` for bars at/after the anchor. Tasks 6 (router + report) import it as `from uw_scan.cards.technicals import anchored_vwap`.
- **Note (spec amendment, Task 11):** float math, not `Decimal`. The spec's "Decimal (matches the derivers convention)" premise was wrong — `cards/technicals.py`'s own docstring declares float-only ("chart-grade series, not money math"). VWAP here is chart-grade.

- [ ] **Step 4.1: Write the failing tests** — `tests/unit/cards/test_anchored_vwap.py`:

```python
"""Arithmetic verification vectors for the anchored-VWAP deriver (hand-computed
cumulative sums, repo test convention — not market observations)."""

from datetime import date

import pytest

from uw_scan.cards.technicals import anchored_vwap


def test_cumulative_math_and_null_volume_carry():
    rows = [
        {"as_of": date(2026, 7, 6), "high": 10.0, "low": 8.0, "close": 9.0, "volume": 100},
        {"as_of": date(2026, 7, 7), "high": 12.0, "low": 10.0, "close": 11.0, "volume": 300},
        {"as_of": date(2026, 7, 8), "high": 13.0, "low": 11.0, "close": 12.0, "volume": None},
    ]
    pts = anchored_vwap(rows, date(2026, 7, 6))
    assert [p["as_of"] for p in pts] == [date(2026, 7, 6), date(2026, 7, 7), date(2026, 7, 8)]
    assert pts[0]["vwap"] == pytest.approx(9.0)  # tp=(10+8+9)/3=9
    assert pts[1]["vwap"] == pytest.approx(10.5)  # (9*100 + 11*300) / 400
    assert pts[2]["vwap"] == pytest.approx(10.5)  # null volume carries prior forward


def test_anchor_excludes_earlier_bars_and_skips_no_volume_head():
    rows = [
        {"as_of": date(2026, 7, 3), "high": 9.0, "low": 7.0, "close": 8.0, "volume": 500},
        {"as_of": date(2026, 7, 6), "high": None, "low": None, "close": 9.0, "volume": None},
        {"as_of": date(2026, 7, 7), "high": 12.0, "low": 10.0, "close": 11.0, "volume": 300},
    ]
    pts = anchored_vwap(rows, date(2026, 7, 6))
    # bar before the anchor contributes nothing; anchor bar has no volume ->
    # no VWAP until the first volume-bearing bar
    assert [p["as_of"] for p in pts] == [date(2026, 7, 7)]
    assert pts[0]["vwap"] == pytest.approx(11.0)


def test_empty_and_out_of_range_anchor():
    assert anchored_vwap([], date(2026, 7, 6)) == []
    rows = [{"as_of": date(2026, 7, 6), "high": 10.0, "low": 8.0, "close": 9.0, "volume": 100}]
    assert anchored_vwap(rows, date(2026, 7, 7)) == []
```

- [ ] **Step 4.2: Run — must fail** (`ImportError: cannot import name 'anchored_vwap'`)

```bash
uv run pytest tests/unit/cards/test_anchored_vwap.py -v
```

- [ ] **Step 4.3: Implement** — append to `src/uw_scan/cards/technicals.py`:

```python
def anchored_vwap(rows: list[Mapping[str, Any]], anchor_date: date) -> list[dict]:
    """Anchored VWAP over per-session OHLCV rows (sorted ascending by as_of).

    typical = (H+L+C)/3; vwap_i = Σ(typical·volume)/Σ(volume) over bars at or
    after ``anchor_date``. Bars missing H/L/C or volume (or volume == 0) add
    nothing to the sums — the prior VWAP carries forward; bars before the
    first volume-bearing bar emit nothing.
    """
    pv = 0.0
    vol = 0.0
    out: list[dict] = []
    for r in rows:
        as_of = r.get("as_of")
        if as_of is None or as_of < anchor_date:
            continue
        h, lo, c, v = r.get("high"), r.get("low"), r.get("close"), r.get("volume")
        if h is not None and lo is not None and c is not None and v:
            pv += (float(h) + float(lo) + float(c)) / 3.0 * float(v)
            vol += float(v)
        if vol > 0:
            out.append({"as_of": as_of, "vwap": pv / vol})
    return out
```
(`Mapping`, `Any`, and `date` are already imported at the top of the module.)

- [ ] **Step 4.4: Run — must pass**

```bash
uv run pytest tests/unit/cards/test_anchored_vwap.py -v
```

- [ ] **Step 4.5: Commit**

```bash
git add src/uw_scan/cards/technicals.py tests/unit/cards/test_anchored_vwap.py
git commit -m "feat(technicals): anchored_vwap deriver"
```

---

### Task 5: VWAP anchor repository + data-gap registry gates

**Files:**
- Create: `src/uw_scan/storage/technical_vwap_anchor_repository.py`
- Modify: `src/uw_scan/reports/data_gap_healer.py` (REGISTRY — add one entry near the `technical_live` entry, ~line 197)
- Modify (regenerated): `docs/runbooks/data-gap-dataset-policy.md`
- Test: `tests/integration/storage/test_technical_vwap_anchor_repository.py` (new)

**Interfaces:**
- Consumes: table `technical_vwap_anchor` (Task 2); `Repository.conn` at call sites.
- Produces: `TechnicalVwapAnchorRepository(conn, schema="uw_scan")` with `upsert(ticker: str, anchor_date: date, snapshot: list[dict]) -> None` (snapshot items must be JSON-safe — ISO date strings, NOT `date` objects: `Jsonb` uses `json.dumps`, which cannot serialize `date`), `get(ticker) -> dict | None` (keys `ticker, anchor_date, vwap_snapshot, computed_at`), `delete(ticker) -> None`. Task 6 constructs it inline per call: `TechnicalVwapAnchorRepository(repo.conn, schema=settings.db_schema)`.

- [ ] **Step 5.1: Write the failing test** — `tests/integration/storage/test_technical_vwap_anchor_repository.py`:

```python
from datetime import date

from uw_scan.storage.technical_vwap_anchor_repository import (
    TechnicalVwapAnchorRepository,
)


def test_upsert_get_delete_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    vrepo = TechnicalVwapAnchorRepository(repo.conn, schema=repo._schema)

    assert vrepo.get("NVDA") is None

    snap = [{"as_of": "2026-07-06", "vwap": 9.0}, {"as_of": "2026-07-07", "vwap": 10.5}]
    vrepo.upsert("nvda", date(2026, 7, 6), snap)
    got = vrepo.get("NVDA")
    assert got["ticker"] == "NVDA"  # uppercased on write
    assert got["anchor_date"] == date(2026, 7, 6)
    assert got["vwap_snapshot"] == snap
    assert got["computed_at"] is not None

    # re-anchor replaces (one anchor per ticker)
    vrepo.upsert("NVDA", date(2026, 7, 7), snap[1:])
    got2 = vrepo.get("NVDA")
    assert got2["anchor_date"] == date(2026, 7, 7)
    assert got2["vwap_snapshot"] == snap[1:]

    vrepo.delete("NVDA")
    assert vrepo.get("NVDA") is None
    vrepo.delete("NVDA")  # idempotent
```

- [ ] **Step 5.2: Run — must fail** (`ModuleNotFoundError`)

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/storage/test_technical_vwap_anchor_repository.py -v
```

- [ ] **Step 5.3: Implement** — `src/uw_scan/storage/technical_vwap_anchor_repository.py` (full file, mirrors `TechnicalLiveRepository`):

```python
"""Standalone repository for the user-set technical VWAP anchor (one per ticker)."""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class TechnicalVwapAnchorRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert(self, ticker: str, anchor_date: date, snapshot: list[dict]) -> None:
        """snapshot items must already be JSON-safe (ISO date strings)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO technical_vwap_anchor
                    (ticker, anchor_date, vwap_snapshot)
                VALUES (%s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE SET
                    anchor_date   = EXCLUDED.anchor_date,
                    vwap_snapshot = EXCLUDED.vwap_snapshot,
                    computed_at   = now()
                """,
                (ticker.upper(), anchor_date, Jsonb(snapshot)),
            )
        self._conn.commit()

    def get(self, ticker: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT ticker, anchor_date, vwap_snapshot, computed_at "
                "FROM technical_vwap_anchor WHERE ticker = %s",
                (ticker.upper(),),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {
            "ticker": row[0],
            "anchor_date": row[1],
            "vwap_snapshot": row[2],
            "computed_at": row[3],
        }

    def delete(self, ticker: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "DELETE FROM technical_vwap_anchor WHERE ticker = %s",
                (ticker.upper(),),
            )
        self._conn.commit()
```

- [ ] **Step 5.4: Run — must pass**

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/storage/test_technical_vwap_anchor_repository.py -v
```

- [ ] **Step 5.5: Register the table with the data-gap healer** — in `src/uw_scan/reports/data_gap_healer.py`, add to `REGISTRY` immediately after the `technical_live` entry (~line 205):

```python
    DatasetRegistryEntry(
        # User-set VWAP anchor for the Technicals price pane (one row per
        # ticker, written only on user click). No cadence to audit.
        "technical_vwap_anchor",
        "core_watchlist",
        "excluded",
        ticker_col="ticker",
        expected_frequency="none",
        reason="user-triggered anchor state; written only on click, no expected cadence",
    ),
```
(If `audit_mode="excluded"` fails validation at test time, fall back to `"freshness_only"` with `expected_frequency="none"` and drop `reason` — check the `AuditMode` literal in the same file and match it. The dataclass comment "required when audit_mode == 'excluded'" indicates `excluded` is legal.)

- [ ] **Step 5.6: Regenerate the policy doc** (exact command the sync test prints):

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
```

- [ ] **Step 5.7: Run BOTH CI gates — must pass**

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest \
  tests/integration/worker/test_data_gap_full_coverage.py \
  tests/unit/reports/test_data_gap_dataset_policy.py -v
```
Expected: PASS (this is the gate `technical_daily` (#257) ate two red CI runs for missing).

- [ ] **Step 5.8: Commit**

```bash
git add src/uw_scan/storage/technical_vwap_anchor_repository.py \
        tests/integration/storage/test_technical_vwap_anchor_repository.py \
        src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md
git commit -m "feat(technicals): technical_vwap_anchor repository + data-gap registry entry"
```

---

### Task 6: API contract — models, report assembly, endpoints, OpenAPI snapshot

**Files:**
- Modify: `src/uw_scan/models/technicals.py` (OHLCV fields on `TechnicalsSeriesRow`; new `VwapPoint`, `TechnicalsVwapAnchor`, `VwapAnchorRequest`; `vwap_anchor` on `TechnicalsResponse`; `_preserve_public_module` call)
- Modify: `src/uw_scan/models/__init__.py` (import block ~line 142 + `__all__` ~line 319)
- Modify: `src/uw_scan/reports/technicals.py` (pass OHLCV through; attach `vwap_anchor`)
- Modify: `src/uw_scan/api/routers/stock.py` (POST/DELETE `/stock/{ticker}/vwap-anchor` after `refresh_stock_technicals`, ~line 285)
- Modify (regenerated): `tests/integration/api/openapi.snapshot.json`
- Test: `tests/integration/api/test_vwap_anchor_endpoint.py` (new)

**Interfaces:**
- Consumes: `anchored_vwap` (Task 4), `TechnicalVwapAnchorRepository` (Task 5), `TechnicalsRepository.fetch_series` OHLCV keys (Task 3).
- Produces (the frontend contract, Task 7 regenerates types from it):
  - `TechnicalsSeriesRow` gains `open/high/low: float | None`, `volume: int | None`.
  - `TechnicalsResponse` gains `vwap_anchor: TechnicalsVwapAnchor | None`.
  - `VwapPoint {as_of: date, vwap: float}`; `TechnicalsVwapAnchor {anchor_date: date, series: list[VwapPoint]}`; `VwapAnchorRequest {anchor_date: date}`.
  - `POST /api/stock/{ticker}/vwap-anchor` body `{"anchor_date": "YYYY-MM-DD"}` → 200 `TechnicalsVwapAnchor` | 400 (not a stored bar / no OHLCV at-or-after anchor).
  - `DELETE /api/stock/{ticker}/vwap-anchor` → 204, idempotent.
  - GET technicals: `vwap_anchor` is recomputed at read time over the live series when OHLCV present (line extends to the newest bar); stored snapshot is the durable record and read fallback.

- [ ] **Step 6.1: Write the failing endpoint tests** — `tests/integration/api/test_vwap_anchor_endpoint.py`:

```python
from datetime import date

import pytest

from uw_scan.storage.technicals_repository import TechnicalsRepository


def _seed(repo):
    trepo = TechnicalsRepository(repo.conn)
    trepo.upsert_series(
        "NVDA",
        [
            {"as_of": date(2026, 7, 6), "open": 9.0, "high": 10.0, "low": 8.0,
             "close": 9.0, "volume": 100},
            {"as_of": date(2026, 7, 7), "open": 10.5, "high": 12.0, "low": 10.0,
             "close": 11.0, "volume": 300},
        ],
    )


def test_post_computes_persists_and_get_returns(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    resp = client.post("/api/stock/NVDA/vwap-anchor", json={"anchor_date": "2026-07-06"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["anchor_date"] == "2026-07-06"
    assert [p["as_of"] for p in body["series"]] == ["2026-07-06", "2026-07-07"]
    assert body["series"][0]["vwap"] == pytest.approx(9.0)
    assert body["series"][1]["vwap"] == pytest.approx(10.5)

    # technicals GET now carries OHLCV per row and the persisted anchor
    got = client.get("/api/stock/NVDA/technicals").json()
    assert got["series"][0]["open"] == 9.0
    assert got["series"][0]["volume"] == 100
    assert got["vwap_anchor"]["anchor_date"] == "2026-07-06"
    assert len(got["vwap_anchor"]["series"]) == 2


def test_post_rejects_non_bar_anchor(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    resp = client.post("/api/stock/NVDA/vwap-anchor", json={"anchor_date": "2026-07-05"})
    assert resp.status_code == 400


def test_delete_clears_anchor(client, seeded_db_empty_cards):
    _seed(seeded_db_empty_cards)
    client.post("/api/stock/NVDA/vwap-anchor", json={"anchor_date": "2026-07-06"})
    assert client.delete("/api/stock/NVDA/vwap-anchor").status_code == 204
    assert client.get("/api/stock/NVDA/technicals").json()["vwap_anchor"] is None
    assert client.delete("/api/stock/NVDA/vwap-anchor").status_code == 204  # idempotent


def test_vwap_model_exports():
    from uw_scan.models import (  # noqa: F401
        TechnicalsVwapAnchor,
        VwapAnchorRequest,
        VwapPoint,
    )

    assert TechnicalsVwapAnchor.__module__ == "uw_scan.models"
```

- [ ] **Step 6.2: Run — must fail**

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/api/test_vwap_anchor_endpoint.py -v
```
Expected: FAIL (404s / ImportError).

- [ ] **Step 6.3: Models** — `src/uw_scan/models/technicals.py`:

`TechnicalsSeriesRow`: insert after `as_of: date`:
```python
    open: float | None = None
    high: float | None = None
    low: float | None = None
```
and after `close: float | None = None`:
```python
    volume: int | None = None
```

Append after `ForwardReturnBandRow` (before `TechnicalsResponse`):
```python
class VwapPoint(_UwBase):
    as_of: date
    vwap: float


class TechnicalsVwapAnchor(_UwBase):
    """User-set anchored VWAP: the anchor bar + the series from it forward."""

    anchor_date: date
    series: list[VwapPoint] = []


class VwapAnchorRequest(_UwBase):
    anchor_date: date
```

`TechnicalsResponse`: append field:
```python
    vwap_anchor: TechnicalsVwapAnchor | None = None
```

Extend the `_preserve_public_module(...)` call with `VwapPoint, TechnicalsVwapAnchor, VwapAnchorRequest`.

- [ ] **Step 6.4: Exports** — `src/uw_scan/models/__init__.py`: extend the `.technicals` import block (~line 142) and `__all__` (~line 319) with the three new names (`TechnicalsVwapAnchor`, `VwapAnchorRequest`, `VwapPoint`), keeping each list's existing ordering style.

- [ ] **Step 6.5: Report assembly** — `src/uw_scan/reports/technicals.py`:

Top-of-file imports: add `anchored_vwap` and the new models:
```python
from uw_scan.cards.technicals import anchored_vwap
from uw_scan.models import (
    ForwardReturnBandRow,
    TechnicalsHeader,
    TechnicalsResponse,
    TechnicalsSeriesRow,
    TechnicalsVwapAnchor,
    VwapPoint,
)
from uw_scan.storage.technical_vwap_anchor_repository import (
    TechnicalVwapAnchorRepository,
)
```

In the `TechnicalsSeriesRow(...)` construction inside `assemble_technicals`, add after `as_of=r["as_of"],`:
```python
            open=r["open"],
            high=r["high"],
            low=r["low"],
            volume=r["volume"],
```

In `assemble_technicals`, before the final `return`, load the anchor and add `vwap_anchor=vwap_anchor` to the `TechnicalsResponse(...)` kwargs:
```python
    vwap_anchor = _load_vwap_anchor(t, repo, schema=schema, series=series)
```

Append the helper at module end:
```python
def _load_vwap_anchor(
    ticker: str,
    repo: Repository,
    *,
    schema: str,
    series: list[TechnicalsSeriesRow],
) -> TechnicalsVwapAnchor | None:
    row = TechnicalVwapAnchorRepository(repo.conn, schema=schema).get(ticker)
    if row is None:
        return None
    anchor = row["anchor_date"]
    # Recompute over the live series when OHLCV is present so the line extends
    # to the newest bar; fall back to the stored snapshot otherwise.
    rows = [
        {"as_of": r.as_of, "high": r.high, "low": r.low, "close": r.close,
         "volume": r.volume}
        for r in series
    ]
    points = anchored_vwap(rows, anchor)
    if points:
        return TechnicalsVwapAnchor(
            anchor_date=anchor,
            series=[VwapPoint(as_of=p["as_of"], vwap=p["vwap"]) for p in points],
        )
    snap = row["vwap_snapshot"] or []
    return TechnicalsVwapAnchor(
        anchor_date=anchor,
        series=[VwapPoint(as_of=p["as_of"], vwap=p["vwap"]) for p in snap],
    )
```

- [ ] **Step 6.6: Endpoints** — `src/uw_scan/api/routers/stock.py`. Extend the top `from uw_scan.models import (...)` block with `TechnicalsVwapAnchor, VwapAnchorRequest, VwapPoint`. Insert after `refresh_stock_technicals` (~line 285):

```python
@router.post("/stock/{ticker}/vwap-anchor", response_model=TechnicalsVwapAnchor)
def set_vwap_anchor(
    ticker: str,
    body: VwapAnchorRequest,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> TechnicalsVwapAnchor:
    """Persist a user-clicked VWAP anchor and return the computed series.

    A sanctioned write on this otherwise read-only router (precedent:
    /technicals/refresh). Pure DB read + O(n) math + one upsert — no external
    fetch, so no single-flight lock is needed.
    """
    from uw_scan.cards.technicals import anchored_vwap
    from uw_scan.storage.technicals_repository import TechnicalsRepository
    from uw_scan.storage.technical_vwap_anchor_repository import (
        TechnicalVwapAnchorRepository,
    )

    t = ticker.upper()
    rows = TechnicalsRepository(repo.conn, schema=settings.db_schema).fetch_series(t)
    if not any(r["as_of"] == body.anchor_date for r in rows):
        raise HTTPException(400, f"{body.anchor_date} is not a stored bar for {t}")
    points = anchored_vwap(rows, body.anchor_date)
    if not points:
        raise HTTPException(400, f"no OHLCV at/after {body.anchor_date} for {t}")
    snapshot = [{"as_of": p["as_of"].isoformat(), "vwap": p["vwap"]} for p in points]
    TechnicalVwapAnchorRepository(repo.conn, schema=settings.db_schema).upsert(
        t, body.anchor_date, snapshot
    )
    return TechnicalsVwapAnchor(
        anchor_date=body.anchor_date,
        series=[VwapPoint(as_of=p["as_of"], vwap=p["vwap"]) for p in points],
    )


@router.delete("/stock/{ticker}/vwap-anchor", status_code=204)
def clear_vwap_anchor(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> None:
    """Clear the persisted VWAP anchor (idempotent)."""
    from uw_scan.storage.technical_vwap_anchor_repository import (
        TechnicalVwapAnchorRepository,
    )

    TechnicalVwapAnchorRepository(repo.conn, schema=settings.db_schema).delete(
        ticker.upper()
    )
```
(Function-local repo imports match the file's existing style — see `get_stock_technicals_live`.)

- [ ] **Step 6.7: Run the endpoint tests — must pass**

```bash
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/api/test_vwap_anchor_endpoint.py -v
```

- [ ] **Step 6.8: Regenerate the OpenAPI snapshot** (exact serialization args are load-bearing):

```bash
uv run python -c "
import json
from pathlib import Path
from uw_scan.api.server import create_app
spec = create_app().openapi()
p = Path('tests/integration/api/openapi.snapshot.json')
p.write_text(json.dumps(spec, sort_keys=True, ensure_ascii=True, indent=2))
print('snapshot regenerated')
"
git diff --stat tests/integration/api/openapi.snapshot.json
```
Expected: diff shows ONLY the new vwap-anchor paths + the three new schemas + the widened `TechnicalsSeriesRow`/`TechnicalsResponse`. If thousands of lines reorder, STOP — the serialization args were wrong; revert and redo.

- [ ] **Step 6.9: Run the full API + technicals test set + lint**

```bash
uv run ruff check src/ tests/
uv run python scripts/_lint_except.py src
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest tests/integration/api/ tests/unit/ -q
```
Expected: all green, including `test_openapi_paths_match_snapshot` and the pre-existing `test_technicals_endpoint.py`.

- [ ] **Step 6.10: Commit**

```bash
git add src/uw_scan/models/technicals.py src/uw_scan/models/__init__.py \
        src/uw_scan/reports/technicals.py src/uw_scan/api/routers/stock.py \
        tests/integration/api/test_vwap_anchor_endpoint.py \
        tests/integration/api/openapi.snapshot.json
git commit -m "feat(technicals): OHLCV + vwap_anchor API contract, POST/DELETE vwap-anchor endpoints"
```

---

### Task 7: Web dependency + regenerated types

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (add `lightweight-charts@5.2.0`)
- Modify (regenerated): `web/lib/types.ts`

**Interfaces:**
- Consumes: the Task 6 OpenAPI schema.
- Produces: `lightweight-charts` importable in `web/`; `web/lib/types.ts` carries `open/high/low/volume` on `TechnicalsSeriesRow`, `vwap_anchor` on `TechnicalsResponse`, schemas `TechnicalsVwapAnchor`/`VwapPoint`/`VwapAnchorRequest`, and the `/api/stock/{ticker}/vwap-anchor` paths. Tasks 8–10 consume both.

- [ ] **Step 7.1: Install the dependency (exact version)**

```bash
cd web && npm install lightweight-charts@5.2.0
grep '"lightweight-charts"' package.json
```
Expected: `"lightweight-charts": "^5.2.0"` (pin note: caret is fine — 5.2.0 is the verified floor).

- [ ] **Step 7.2: Regenerate `lib/types.ts` offline** (do NOT hit a running dev server on :8400 — it may serve stale code; dump the spec from the worktree's app instead, same approach as the snapshot):

```bash
cd /Users/chenxi/projects/argon/.worktrees/technicals-lwc-price-pane
uv run python -c "
import json
from uw_scan.api.server import create_app
open('/tmp/argon-openapi-lwc.json', 'w').write(json.dumps(create_app().openapi()))
print('spec dumped')
"
cd web && npx openapi-typescript /tmp/argon-openapi-lwc.json -o lib/types.ts
```

- [ ] **Step 7.3: Verify the diff is additive-only**

```bash
git diff --stat web/lib/types.ts
git diff web/lib/types.ts | head -100
```
Expected: a few dozen changed lines — the new series-row fields, `vwap_anchor`, the three schemas (alphabetical slots: `TechnicalsVwapAnchor` after `TechnicalsSeriesRow`; `VwapAnchorRequest`/`VwapPoint` in the V-range), and the new path block. If instead thousands of lines reorder (tooling drift), run `git checkout -- lib/types.ts` and insert the same blocks surgically with a python script (`Bash` + a here-doc script doing exact-string insertion — NOT the Edit tool, a prettier hook reflows this file), mirroring the shapes shown in the diff attempt.

- [ ] **Step 7.4: Typecheck (types compile, nothing else consumes them yet)**

```bash
cd web && npm run typecheck
```
Expected: clean.

- [ ] **Step 7.5: Commit**

```bash
git add web/package.json web/package-lock.json web/lib/types.ts
git commit -m "feat(web): add lightweight-charts 5.2.0 + regen API types"
```

---

### Task 8: Vendored bands primitive + pure client libs (`vwap`, `priceChartData`)

**Files:**
- Create: `web/lib/lwc/bandsIndicator.ts` (vendored + adapted, Apache-2.0 attribution)
- Create: `web/lib/vwap.ts`
- Create: `web/lib/priceChartData.ts`
- Test: `web/tests/unit/vwap.test.ts`, `web/tests/unit/priceChartData.test.ts`

**Interfaces:**
- Consumes: `lightweight-charts` types; `TechnicalsResponse["series"]` rows (Task 7 types).
- Produces (Task 9 consumes exactly these):
  - `BandsIndicator` class: `new BandsIndicator({lineColor, fillColor, lineWidth})`, `setBandData(bands: BandPoint[])`, attached via `series.attachPrimitive(indicator)`. `BandPoint = {time: Time, upper: number, lower: number}`.
  - `anchoredVwap(rows: VwapBar[], anchorDate: string) -> {time: string, value: number}[]` — client mirror of the Python deriver for instant redraw.
  - `priceChartData.ts`: `SeriesRow` type alias, `hasOhlcv(rows)`, `toCandleData(rows)`, `toCloseLineData(rows)`, `toSmaLineData(rows, key)`, `toVolumeData(rows, upColor, downColor)`, `toBandData(rows)`.
- **Upstream deviation notes (deliberate):** the official `bands-indicator` computes a demo ±10% envelope from the attached series' own data and has NO external setter. This vendored copy replaces that with `setBandData()` (argon feeds the ±1.5σ envelope recovered from stored `z`), drops the now-unneeded `dataUpdated`/series-data cloning, converts times to epoch seconds for the autoscale binary search (upstream assumed numeric times; ours are `'yyyy-mm-dd'`), and guards empty band arrays (upstream crashes on `points[0]`).

- [ ] **Step 8.1: Write the failing lib tests**

`web/tests/unit/vwap.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import { anchoredVwap } from "@/lib/vwap";

// Same arithmetic verification vector as the Python test — the two impls
// must agree (server is the record of truth; client is the instant redraw).
const rows = [
  { as_of: "2026-07-06", high: 10, low: 8, close: 9, volume: 100 },
  { as_of: "2026-07-07", high: 12, low: 10, close: 11, volume: 300 },
  { as_of: "2026-07-08", high: 13, low: 11, close: 12, volume: null },
];

describe("anchoredVwap", () => {
  it("matches the server-side cumulative math incl. null-volume carry", () => {
    const pts = anchoredVwap(rows, "2026-07-06");
    expect(pts.map((p) => p.time)).toEqual(["2026-07-06", "2026-07-07", "2026-07-08"]);
    expect(pts[0].value).toBeCloseTo(9.0, 10);
    expect(pts[1].value).toBeCloseTo(10.5, 10);
    expect(pts[2].value).toBeCloseTo(10.5, 10);
  });

  it("excludes bars before the anchor and emits nothing before first volume", () => {
    expect(anchoredVwap(rows, "2026-07-07").map((p) => p.time)).toEqual([
      "2026-07-07",
      "2026-07-08",
    ]);
    expect(anchoredVwap(rows, "2026-07-09")).toEqual([]);
    expect(anchoredVwap([], "2026-07-06")).toEqual([]);
  });
});
```

`web/tests/unit/priceChartData.test.ts`:
```ts
import { describe, expect, it } from "vitest";
import {
  hasOhlcv,
  toBandData,
  toCandleData,
  toVolumeData,
} from "@/lib/priceChartData";

const full = { as_of: "2026-07-06", open: 9, high: 10, low: 8, close: 9.5, volume: 100 };
const closeOnly = { as_of: "2026-07-07", close: 9.8 };
const empty = { as_of: "2026-07-08" };

describe("priceChartData", () => {
  it("hasOhlcv detects any OHLC-bearing row", () => {
    expect(hasOhlcv([full, closeOnly])).toBe(true);
    expect(hasOhlcv([closeOnly, empty])).toBe(false);
  });

  it("toCandleData: full candle / flat tick for close-only / whitespace", () => {
    const [a, b, c] = toCandleData([full, closeOnly, empty] as never[]);
    expect(a).toEqual({ time: "2026-07-06", open: 9, high: 10, low: 8, close: 9.5 });
    expect(b).toEqual({ time: "2026-07-07", open: 9.8, high: 9.8, low: 9.8, close: 9.8 });
    expect(c).toEqual({ time: "2026-07-08" });
  });

  it("toVolumeData colors by candle direction, whitespace when null", () => {
    const down = { ...full, as_of: "2026-07-09", open: 10, close: 9 };
    const [a, b, c] = toVolumeData([full, down, closeOnly] as never[], "UP", "DN");
    expect(a).toEqual({ time: "2026-07-06", value: 100, color: "UP" });
    expect(b).toEqual({ time: "2026-07-09", value: 100, color: "DN" });
    expect(c).toEqual({ time: "2026-07-07" }); // no volume -> whitespace
  });

  it("toBandData recovers the ±1.5σ envelope from stored z (half = 1.5·(c−m)/z)", () => {
    const r = { as_of: "2026-07-06", close: 110, sma200: 100, z: 2 };
    // sigma = (c-m)/z = 5 -> half = 7.5
    expect(toBandData([r] as never[])).toEqual([
      { time: "2026-07-06", upper: 107.5, lower: 92.5 },
    ]);
    expect(toBandData([{ as_of: "x", close: 110, sma200: 100, z: 0 }] as never[])).toEqual([]);
  });
});
```

- [ ] **Step 8.2: Run — must fail** (modules don't exist)

```bash
cd web && npx vitest run tests/unit/vwap.test.ts tests/unit/priceChartData.test.ts
```

- [ ] **Step 8.3: Implement `web/lib/vwap.ts`** (full file):

```ts
export type VwapBar = {
  as_of?: string | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  volume?: number | null;
};

// Client-side mirror of cards/technicals.anchored_vwap — instant redraw on
// click; the server recompute remains the record of truth.
export function anchoredVwap(
  rows: readonly VwapBar[],
  anchorDate: string,
): { time: string; value: number }[] {
  let pv = 0;
  let vol = 0;
  const out: { time: string; value: number }[] = [];
  for (const r of rows) {
    const t = r.as_of;
    if (!t || t < anchorDate) continue;
    const { high, low, close, volume } = r;
    if (high != null && low != null && close != null && volume) {
      pv += ((high + low + close) / 3) * volume;
      vol += volume;
    }
    if (vol > 0) out.push({ time: t, value: pv / vol });
  }
  return out;
}
```

- [ ] **Step 8.4: Implement `web/lib/priceChartData.ts`** (full file):

```ts
import type {
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  WhitespaceData,
} from "lightweight-charts";
import type { TechnicalsResponse } from "@/lib/api";
import type { BandPoint } from "@/lib/lwc/bandsIndicator";

export type SeriesRow = TechnicalsResponse["series"][number];

export function hasOhlcv(rows: readonly SeriesRow[]): boolean {
  return rows.some((r) => r.open != null && r.high != null && r.low != null);
}

export function toCandleData(
  rows: readonly SeriesRow[],
): (CandlestickData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) => {
    const t = r.as_of as Time;
    if (r.close == null) return { time: t };
    if (r.open != null && r.high != null && r.low != null) {
      return { time: t, open: r.open, high: r.high, low: r.low, close: r.close };
    }
    // OHLC-less row in candle mode (e.g. a live head appended for a new
    // session): flat tick at the close.
    return { time: t, open: r.close, high: r.close, low: r.close, close: r.close };
  });
}

export function toCloseLineData(
  rows: readonly SeriesRow[],
): (LineData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) =>
    r.close == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: r.close },
  );
}

export function toSmaLineData(
  rows: readonly SeriesRow[],
  key: "sma20" | "sma50" | "sma200",
): (LineData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) => {
    const v = r[key];
    return v == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: v };
  });
}

export function toVolumeData(
  rows: readonly SeriesRow[],
  upColor: string,
  downColor: string,
): (HistogramData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) => {
    const t = r.as_of as Time;
    if (r.volume == null) return { time: t };
    const up = r.open == null || r.close == null || r.close >= r.open;
    return { time: t, value: r.volume, color: up ? upColor : downColor };
  });
}

// ±1.5σ envelope recovered from stored z exactly as the retired SVG pane did:
// half = 1.5 * (close - sma200) / z, where z = (close - sma200) / sigma.
export function toBandData(rows: readonly SeriesRow[]): BandPoint[] {
  const out: BandPoint[] = [];
  for (const r of rows) {
    const c = r.close;
    const m = r.sma200;
    const z = r.z;
    if (c != null && m != null && z != null && z !== 0 && Number.isFinite(z)) {
      const half = 1.5 * ((c - m) / z);
      out.push({ time: r.as_of as Time, upper: m + half, lower: m - half });
    }
  }
  return out;
}
```

- [ ] **Step 8.5: Implement `web/lib/lwc/bandsIndicator.ts`** (full file — vendored + adapted):

```ts
/**
 * Vendored + adapted from tradingview/lightweight-charts plugin-examples
 * (plugin-examples/src/plugins/bands-indicator + its helpers), Apache-2.0,
 * (c) TradingView, Inc. — https://github.com/tradingview/lightweight-charts
 *
 * Adaptations for argon:
 * - Upstream computed a demo ±10% envelope from the attached series' own
 *   data; this version renders EXPLICIT band values fed via setBandData()
 *   (the ±1.5σ envelope recovered from the stored z-score).
 * - Times converted to epoch seconds for the autoscale binary search
 *   (upstream assumed numeric times; ours are 'yyyy-mm-dd' strings).
 * - Empty-data guards added (upstream crashed on points[0]).
 */
import { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  AutoscaleInfo,
  Coordinate,
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesOptionsMap,
  Time,
} from "lightweight-charts";

export interface BandPoint {
  time: Time; // same representation as the attached series' data ('yyyy-mm-dd')
  upper: number;
  lower: number;
}

export interface BandsIndicatorOptions {
  lineColor?: string;
  fillColor?: string;
  lineWidth?: number;
}

const defaults: Required<BandsIndicatorOptions> = {
  lineColor: "rgb(25, 200, 100)",
  fillColor: "rgba(25, 200, 100, 0.25)",
  lineWidth: 1,
};

function ensureDefined<T>(value: T | undefined): T {
  if (value === undefined) throw new Error("Value is undefined");
  return value;
}

// 'yyyy-mm-dd' | BusinessDay | UTCTimestamp -> epoch seconds (autoscale
// binary search only; rendering never converts).
function toEpochSec(t: Time | null | undefined, fallback: number): number {
  if (t == null) return fallback;
  if (typeof t === "number") return t;
  if (typeof t === "string") return Date.parse(t) / 1000;
  return Date.UTC(t.year, t.month - 1, t.day) / 1000;
}

type SearchDirection = "left" | "right";

class ClosestTimeIndexFinder<T extends { time: number }> {
  private numbers: T[];
  private cache: Map<string, number>;

  constructor(sortedNumbers: T[]) {
    this.numbers = sortedNumbers;
    this.cache = new Map();
  }

  public findClosestIndex(target: number, direction: SearchDirection): number {
    const cacheKey = `${target}:${direction}`;
    if (this.cache.has(cacheKey)) {
      return this.cache.get(cacheKey) as number;
    }
    const closestIndex = this._performSearch(target, direction);
    this.cache.set(cacheKey, closestIndex);
    return closestIndex;
  }

  private _performSearch(target: number, direction: SearchDirection): number {
    let low = 0;
    let high = this.numbers.length - 1;
    if (high < 0) return 0;
    if (target <= this.numbers[0].time) return 0;
    if (target >= this.numbers[high].time) return high;
    while (low <= high) {
      const mid = Math.floor((low + high) / 2);
      const num = this.numbers[mid].time;
      if (num === target) {
        return mid;
      } else if (num > target) {
        high = mid - 1;
      } else {
        low = mid + 1;
      }
    }
    return direction === "left" ? low : high;
  }
}

interface UpperLowerData {
  upper: number;
  lower: number;
}

class UpperLowerInRange<T extends UpperLowerData> {
  private _arr: T[];
  private _chunkSize: number;
  private _cache: Map<string, UpperLowerData>;

  constructor(arr: T[], chunkSize = 10) {
    this._arr = arr;
    this._chunkSize = chunkSize;
    this._cache = new Map();
  }

  public getMinMax(startIndex: number, endIndex: number): UpperLowerData {
    const cacheKey = `${startIndex}:${endIndex}`;
    const hit = this._cache.get(cacheKey);
    if (hit) return hit;
    const result: UpperLowerData = { lower: Infinity, upper: -Infinity };
    const startChunkIndex = Math.floor(startIndex / this._chunkSize);
    const endChunkIndex = Math.floor(endIndex / this._chunkSize);
    for (let chunkIndex = startChunkIndex; chunkIndex <= endChunkIndex; chunkIndex++) {
      const chunkStart = chunkIndex * this._chunkSize;
      const chunkEnd = Math.min(
        (chunkIndex + 1) * this._chunkSize - 1,
        this._arr.length - 1,
      );
      const chunkCacheKey = `${chunkStart}:${chunkEnd}`;
      const chunkHit = this._cache.get(chunkCacheKey);
      if (chunkHit) {
        this._check(chunkHit, result);
      } else {
        const chunkResult: UpperLowerData = { lower: Infinity, upper: -Infinity };
        for (let i = chunkStart; i <= chunkEnd; i++) {
          const item = this._arr[i];
          if (item) this._check(item, chunkResult);
        }
        this._cache.set(chunkCacheKey, chunkResult);
        this._check(chunkResult, result);
      }
    }
    this._cache.set(cacheKey, result);
    return result;
  }

  private _check(item: UpperLowerData, state: UpperLowerData) {
    if (item.lower < state.lower) state.lower = item.lower;
    if (item.upper > state.upper) state.upper = item.upper;
  }
}

abstract class PluginBase implements ISeriesPrimitive<Time> {
  private _chart: IChartApi | undefined = undefined;
  private _series: ISeriesApi<keyof SeriesOptionsMap> | undefined = undefined;
  private _requestUpdate?: () => void;

  protected requestUpdate(): void {
    if (this._requestUpdate) this._requestUpdate();
  }

  public attached({ chart, series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this._chart = chart;
    this._series = series;
    this._requestUpdate = requestUpdate;
    this.requestUpdate();
  }

  public detached() {
    this._chart = undefined;
    this._series = undefined;
    this._requestUpdate = undefined;
  }

  public get chart(): IChartApi {
    return ensureDefined(this._chart);
  }

  public get series(): ISeriesApi<keyof SeriesOptionsMap> {
    return ensureDefined(this._series);
  }
}

interface BandRendererData {
  x: Coordinate | number;
  upper: Coordinate | number;
  lower: Coordinate | number;
}

interface BandViewData {
  data: BandRendererData[];
  options: Required<BandsIndicatorOptions>;
}

class BandsIndicatorPaneRenderer implements IPrimitivePaneRenderer {
  _viewData: BandViewData;
  constructor(data: BandViewData) {
    this._viewData = data;
  }
  draw() {}
  drawBackground(target: CanvasRenderingTarget2D) {
    const points: BandRendererData[] = this._viewData.data;
    if (points.length < 2) return; // adaptation: upstream crashed on empty data
    target.useBitmapCoordinateSpace((scope) => {
      const ctx = scope.context;
      ctx.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);

      ctx.strokeStyle = this._viewData.options.lineColor;
      ctx.lineWidth = this._viewData.options.lineWidth;
      ctx.beginPath();
      const region = new Path2D();
      const lines = new Path2D();
      region.moveTo(points[0].x, points[0].upper);
      lines.moveTo(points[0].x, points[0].upper);
      for (const point of points) {
        region.lineTo(point.x, point.upper);
        lines.lineTo(point.x, point.upper);
      }
      const end = points.length - 1;
      region.lineTo(points[end].x, points[end].lower);
      lines.moveTo(points[end].x, points[end].lower);
      for (let i = points.length - 2; i >= 0; i--) {
        region.lineTo(points[i].x, points[i].lower);
        lines.lineTo(points[i].x, points[i].lower);
      }
      region.lineTo(points[0].x, points[0].upper);
      region.closePath();
      ctx.stroke(lines);
      ctx.fillStyle = this._viewData.options.fillColor;
      ctx.fill(region);
    });
  }
}

class BandsIndicatorPaneView implements IPrimitivePaneView {
  _source: BandsIndicator;
  _data: BandViewData;

  constructor(source: BandsIndicator) {
    this._source = source;
    this._data = { data: [], options: this._source._options };
  }

  update() {
    const series = this._source.series;
    const timeScale = this._source.chart.timeScale();
    this._data.data = this._source._bandsData.map((d) => ({
      x: timeScale.timeToCoordinate(d.time) ?? -100,
      upper: series.priceToCoordinate(d.upper) ?? -100,
      lower: series.priceToCoordinate(d.lower) ?? -100,
    }));
  }

  renderer() {
    return new BandsIndicatorPaneRenderer(this._data);
  }
}

export class BandsIndicator extends PluginBase implements ISeriesPrimitive<Time> {
  _paneViews: BandsIndicatorPaneView[];
  _bandsData: BandPoint[] = [];
  _options: Required<BandsIndicatorOptions>;
  _timeIndices: ClosestTimeIndexFinder<{ time: number }>;
  _upperLower: UpperLowerInRange<BandPoint>;

  constructor(options: BandsIndicatorOptions = {}) {
    super();
    this._options = { ...defaults, ...options };
    this._paneViews = [new BandsIndicatorPaneView(this)];
    this._timeIndices = new ClosestTimeIndexFinder([]);
    this._upperLower = new UpperLowerInRange([]);
  }

  /** Adaptation: explicit band values replace upstream's from-series demo. */
  setBandData(bands: BandPoint[]) {
    this._bandsData = bands;
    this._timeIndices = new ClosestTimeIndexFinder(
      bands.map((b) => ({ time: toEpochSec(b.time, 0) })),
    );
    this._upperLower = new UpperLowerInRange(bands, 4);
    this.requestUpdate();
  }

  updateAllViews() {
    this._paneViews.forEach((pw) => pw.update());
  }

  paneViews() {
    return this._paneViews;
  }

  autoscaleInfo(startTimePoint: Logical, endTimePoint: Logical): AutoscaleInfo | null {
    if (this._bandsData.length === 0) return null;
    const ts = this.chart.timeScale();
    const startTime = toEpochSec(
      ts.coordinateToTime(ts.logicalToCoordinate(startTimePoint) ?? 0),
      0,
    );
    const endTime = toEpochSec(
      ts.coordinateToTime(ts.logicalToCoordinate(endTimePoint) ?? 0),
      5_000_000_000,
    );
    const startIndex = this._timeIndices.findClosestIndex(startTime, "left");
    const endIndex = this._timeIndices.findClosestIndex(endTime, "right");
    const range = this._upperLower.getMinMax(startIndex, endIndex);
    if (!Number.isFinite(range.lower) || !Number.isFinite(range.upper)) return null;
    return { priceRange: { minValue: range.lower, maxValue: range.upper } };
  }
}
```

- [ ] **Step 8.6: Run the lib tests — must pass**

```bash
cd web && npx vitest run tests/unit/vwap.test.ts tests/unit/priceChartData.test.ts
```

- [ ] **Step 8.7: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: clean (`fancy-canvas` types resolve — it is a dependency of lightweight-charts).

- [ ] **Step 8.8: Commit**

```bash
git add web/lib/lwc/bandsIndicator.ts web/lib/vwap.ts web/lib/priceChartData.ts \
        web/tests/unit/vwap.test.ts web/tests/unit/priceChartData.test.ts
git commit -m "feat(web): vendored bands-indicator primitive + vwap/priceChartData libs"
```

---

### Task 9: `TechnicalsPriceChart` component

**Files:**
- Create: `web/components/stock/panels/TechnicalsPriceChart.tsx`
- Modify: `web/lib/api.ts` (two new calls + one exported type)

**Interfaces:**
- Consumes: `lightweight-charts` (Task 7), `BandsIndicator`/`anchoredVwap`/`priceChartData` (Task 8), `api.vwapAnchorSet`/`api.vwapAnchorClear` (this task), `data.vwap_anchor` from the technicals GET (Task 6).
- Produces: `<TechnicalsPriceChart data={TechnicalsResponse} control={ReactNode} />` — drop-in replacement for `TechnicalsAnchorChart`'s props. Task 10 swaps it into `TechnicalsTab`.
- Behavior contract: candle mode iff any row has OHLC (`hasOhlcv`); otherwise close-line mode (today's look) — VWAP anchoring enabled only in candle mode. Chart is rebuilt on ticker/mode change; `setData` on data change otherwise; `fitContent` only when ticker or window start changes (a live-poll head append must NOT reset zoom). Click a bar → optimistic local VWAP → POST persists → server series reconciles. Chip `VWAP ⚓ <date> ✕` clears via DELETE.

- [ ] **Step 9.1: Add the api calls** — `web/lib/api.ts`. Next to the `technicals*` group (~line 145), insert:

```ts
  vwapAnchorSet: (
    ticker: string,
    body: { anchor_date: string },
  ): Promise<VwapAnchorResponse> =>
    _fetch<VwapAnchorResponse>(`/api/stock/${ticker}/vwap-anchor`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  vwapAnchorClear: (ticker: string): Promise<void> =>
    _fetch(`/api/stock/${ticker}/vwap-anchor`, { method: "DELETE" }),
```

Next to the other type aliases (~line 61):
```ts
export type VwapAnchorResponse = Json<"/api/stock/{ticker}/vwap-anchor", "post">;
```
(The 204 DELETE path is already handled by `_fetch`'s empty-body special case.)

- [ ] **Step 9.2: Write the component** — `web/components/stock/panels/TechnicalsPriceChart.tsx` (full file):

```tsx
"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { api, type TechnicalsResponse } from "@/lib/api";
import { anchoredVwap } from "@/lib/vwap";
import {
  hasOhlcv,
  toBandData,
  toCandleData,
  toCloseLineData,
  toSmaLineData,
  toVolumeData,
  type SeriesRow,
} from "@/lib/priceChartData";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

const H = 320;

// Canvas needs concrete colors — resolve the Argon CSS variables at mount.
function cssVar(name: string): string {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || "#888888";
}

type Anchor = {
  anchorDate: string;
  series: { time: string; value: number }[];
};

function anchorFromServer(
  va: TechnicalsResponse["vwap_anchor"],
): Anchor | null {
  if (!va) return null;
  return {
    anchorDate: va.anchor_date,
    series: (va.series ?? []).map((p) => ({ time: p.as_of, value: p.vwap })),
  };
}

type ChartHandles = {
  chart: IChartApi;
  price: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
  volume: ISeriesApi<"Histogram"> | null;
  smas: Record<"sma20" | "sma50" | "sma200", ISeriesApi<"Line">>;
  vwap: ISeriesApi<"Line">;
  bands: BandsIndicator;
};

export function TechnicalsPriceChart({
  data,
  control,
}: {
  data: TechnicalsResponse;
  control?: ReactNode;
}) {
  const rows = (data.series ?? []) as SeriesRow[];
  const ticker = data.ticker;
  const candleMode = hasOhlcv(rows);

  const containerRef = useRef<HTMLDivElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const handlesRef = useRef<ChartHandles | null>(null);
  const rowsRef = useRef<SeriesRow[]>(rows);
  const tickerRef = useRef(ticker);
  const candleModeRef = useRef(candleMode);
  const fitKeyRef = useRef("");
  const [anchor, setAnchor] = useState<Anchor | null>(() =>
    anchorFromServer(data.vwap_anchor),
  );
  const [err, setErr] = useState<string | null>(null);
  rowsRef.current = rows;
  tickerRef.current = ticker;
  candleModeRef.current = candleMode;

  // Server anchor is the record of truth on (re)load / ticker switch.
  useEffect(() => {
    setAnchor(anchorFromServer(data.vwap_anchor));
    setErr(null);
  }, [ticker, data.vwap_anchor]);

  // Build the chart once per ticker+mode; dispose on change/unmount.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const positive = cssVar("--positive");
    const negative = cssVar("--negative");
    const muted = cssVar("--text-muted");
    const borderDim = cssVar("--border-dim");
    const chart = createChart(el, {
      autoSize: true,
      height: H,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: muted,
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: borderDim, style: LineStyle.Dotted },
        horzLines: { color: borderDim, style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: muted, labelBackgroundColor: borderDim },
        horzLine: { color: muted, labelBackgroundColor: borderDim },
      },
      timeScale: { borderColor: borderDim, timeVisible: false },
      rightPriceScale: { borderColor: borderDim },
    });

    const lineOpts = {
      lineWidth: 1 as const,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    };
    const price = candleModeRef.current
      ? chart.addSeries(CandlestickSeries, {
          upColor: positive,
          downColor: negative,
          borderVisible: false,
          wickUpColor: positive,
          wickDownColor: negative,
        })
      : chart.addSeries(LineSeries, {
          color: cssVar("--text-primary"),
          lineWidth: 2,
          priceLineVisible: false,
          crosshairMarkerVisible: true,
        });
    // Keep candles clear of the volume band at the bottom.
    price.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.25 } });

    let volume: ISeriesApi<"Histogram"> | null = null;
    if (candleModeRef.current) {
      volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "", // overlay: no left/right axis
        priceLineVisible: false,
        lastValueVisible: false,
      });
      volume.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    }

    const smas = {
      sma20: chart.addSeries(LineSeries, { color: cssVar("--accent-warm"), ...lineOpts }),
      sma50: chart.addSeries(LineSeries, { color: cssVar("--accent-vol"), ...lineOpts }),
      sma200: chart.addSeries(LineSeries, { color: cssVar("--accent-vivid"), ...lineOpts }),
    };
    const vwap = chart.addSeries(LineSeries, {
      color: cssVar("--text-primary"),
      lineStyle: LineStyle.Dashed,
      ...lineOpts,
    });
    const bands = new BandsIndicator({
      lineColor: "transparent",
      fillColor: `${cssVar("--accent-bg")}1a`, // ~10% alpha, matches the SVG envelope
      lineWidth: 1,
    });
    price.attachPrimitive(bands);

    handlesRef.current = { chart, price, volume, smas, vwap, bands };
    fitKeyRef.current = ""; // force a fitContent on the first data pass

    // Click-to-anchor VWAP (candle mode only — needs H/L/C + volume).
    const onClick = (param: MouseEventParams<Time>) => {
      if (!candleModeRef.current) return;
      if (!param.point || param.time === undefined) return;
      const t = String(param.time);
      const local = anchoredVwap(rowsRef.current, t);
      if (local.length === 0) return;
      setErr(null);
      setAnchor({ anchorDate: t, series: local }); // optimistic
      api
        .vwapAnchorSet(tickerRef.current, { anchor_date: t })
        .then((resp) =>
          setAnchor({
            anchorDate: resp.anchor_date,
            series: (resp.series ?? []).map((p) => ({ time: p.as_of, value: p.vwap })),
          }),
        )
        .catch((e) => setErr(`VWAP anchor not saved: ${String(e)}`));
    };
    chart.subscribeClick(onClick);

    // Hover readout (date · OHLC · volume) — direct DOM write, no re-render.
    const onMove = (param: MouseEventParams<Time>) => {
      const out = readoutRef.current;
      if (!out) return;
      if (!param.point || param.time === undefined) {
        out.textContent = "";
        return;
      }
      const bar = param.seriesData.get(price) as
        | { open?: number; high?: number; low?: number; close?: number; value?: number }
        | undefined;
      const vol = volume
        ? (param.seriesData.get(volume) as { value?: number } | undefined)
        : undefined;
      if (!bar) {
        out.textContent = "";
        return;
      }
      const f = (x?: number) => (x == null ? "–" : x.toFixed(2));
      out.textContent =
        bar.open != null
          ? `${param.time}  O ${f(bar.open)} H ${f(bar.high)} L ${f(bar.low)} C ${f(bar.close)}` +
            (vol?.value != null ? `  V ${Intl.NumberFormat("en-US").format(vol.value)}` : "")
          : `${param.time}  C ${f(bar.value)}`;
    };
    chart.subscribeCrosshairMove(onMove);

    return () => {
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      handlesRef.current = null;
    };
  }, [ticker, candleMode]);

  // Data pass: setData on every change; fit only when the window/ticker moves.
  useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    const positive = cssVar("--positive");
    const negative = cssVar("--negative");
    if (candleMode) {
      (h.price as ISeriesApi<"Candlestick">).setData(toCandleData(rows));
      h.volume?.setData(toVolumeData(rows, `${positive}59`, `${negative}59`));
    } else {
      (h.price as ISeriesApi<"Line">).setData(toCloseLineData(rows));
    }
    h.smas.sma20.setData(toSmaLineData(rows, "sma20"));
    h.smas.sma50.setData(toSmaLineData(rows, "sma50"));
    h.smas.sma200.setData(toSmaLineData(rows, "sma200"));
    h.bands.setBandData(toBandData(rows));
    const firstAsOf = rows[0]?.as_of ?? "";
    const visVwap = anchor
      ? anchor.series.filter((p) => p.time >= firstAsOf)
      : [];
    h.vwap.setData(visVwap.map((p) => ({ time: p.time as Time, value: p.value })));
    // Fit on ticker or window-start change only — a live head append (length
    // change, same first bar) must not reset the user's zoom.
    const fitKey = `${ticker}:${candleMode}:${firstAsOf}`;
    if (fitKey !== fitKeyRef.current) {
      fitKeyRef.current = fitKey;
      h.chart.timeScale().fitContent();
    }
  }, [rows, ticker, candleMode, anchor]);

  const clearAnchor = () => {
    setAnchor(null);
    setErr(null);
    api.vwapAnchorClear(ticker).catch((e) => setErr(`VWAP clear failed: ${String(e)}`));
  };

  const header: ReactNode = (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
      {anchor && (
        <button
          type="button"
          onClick={clearAnchor}
          title="Clear anchored VWAP"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1,
            color: "var(--text-secondary)",
            background: "var(--bg-panel-raised)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: "2px 7px",
            cursor: "pointer",
          }}
        >
          VWAP ⚓ {anchor.anchorDate} ✕
        </button>
      )}
      {control}
      <span>{data.as_of ?? ""}</span>
    </span>
  );

  if (rows.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="Price, Moving Averages & ±1.5σ Band"
        subtitle="anchor"
        headline={header}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough history.
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  return (
    <AnalyticalSeriesPanel
      title="Price, Moving Averages & ±1.5σ Band"
      subtitle={
        candleMode
          ? "candles · volume · click a bar to anchor VWAP"
          : "close line · candles arrive after the next refresh"
      }
      headline={header}
    >
      <div style={{ position: "relative" }}>
        <div ref={containerRef} style={{ width: "100%", height: H }} />
        <div
          ref={readoutRef}
          style={{
            position: "absolute",
            top: 4,
            left: 8,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-secondary)",
            pointerEvents: "none",
            whiteSpace: "pre",
          }}
        />
      </div>
      {err && (
        <div style={{ color: "var(--negative)", fontSize: 11, marginTop: 6 }}>{err}</div>
      )}
      <Legend showVwap={anchor != null} />
    </AnalyticalSeriesPanel>
  );
}

function Legend({ showVwap }: { showVwap: boolean }) {
  const item = (color: string, label: string) => (
    <span
      key={label}
      style={{ display: "inline-flex", alignItems: "center", gap: 4, marginRight: 12 }}
    >
      <span style={{ width: 12, height: 2, background: color, display: "inline-block" }} />
      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{label}</span>
    </span>
  );
  return (
    <div style={{ marginTop: 6 }}>
      {item("var(--text-primary)", "PRICE")}
      {item("var(--accent-warm)", "SMA20")}
      {item("var(--accent-vol)", "SMA50")}
      {item("var(--accent-vivid)", "SMA200")}
      {showVwap && item("var(--text-primary)", "VWAP ⚓")}
    </div>
  );
}
```

Notes for the implementer:
- `attributionLogo` stays at its default (`true`) — the small TradingView mark is the Apache-2.0-friendly attribution; do not disable it.
- The optimistic click computes over the WINDOWED rows, which is correct: the clicked anchor is inside the window, so cumulative sums from the anchor forward are identical to the server's full-history compute.
- Colors like `` `${positive}59` `` append hex alpha (~35%) to the resolved `#rrggbb` — keeps volume bars muted under the candles.

- [ ] **Step 9.3: Typecheck + lint**

```bash
cd web && npm run typecheck && npm run lint
```
Expected: clean. (No vitest for the component itself — jsdom has no canvas; the pure logic was tested in Task 8, interaction is covered by the Task 12 smoke.)

- [ ] **Step 9.4: Commit**

```bash
git add web/components/stock/panels/TechnicalsPriceChart.tsx web/lib/api.ts
git commit -m "feat(web): TechnicalsPriceChart — lightweight-charts price pane with volume, σ-band, anchored VWAP"
```

---

### Task 10: Tab swap, auto-fill-on-open, retire the SVG pane

**Files:**
- Modify: `web/components/stock/tabs/TechnicalsTab.tsx`
- Delete: `web/components/stock/panels/TechnicalsAnchorChart.tsx`
- Test: `web/tests/unit/technicalsTabAutofill.test.tsx` (new)

**Interfaces:**
- Consumes: `TechnicalsPriceChart` (Task 9), `api.technicalsRefresh` (existing).
- Produces: the Technicals tab renders the lightweight-charts pane pinned at top (still carrying `TimeframeSelect`); when the latest EOD row lacks OHLCV it fires the per-ticker refresh ONCE per mount+ticker and swaps in the fresh payload. `TechnicalsAnchorChart` is gone.

- [ ] **Step 10.1: Write the failing auto-fill test** — `web/tests/unit/technicalsTabAutofill.test.tsx`:

```tsx
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const noOhlcv = {
  ticker: "NVDA",
  backfill_status: "ready",
  as_of: "2026-07-09",
  header: {},
  series: [
    { as_of: "2026-07-08", close: 100 },
    { as_of: "2026-07-09", close: 101 },
  ],
  detail: {},
  forward_returns: [],
  vwap_anchor: null,
};
const withOhlcv = {
  ...noOhlcv,
  series: noOhlcv.series.map((r) => ({ ...r, open: 99, high: 102, low: 98, volume: 5 })),
};

vi.mock("@/lib/api", () => ({
  api: {
    technicals: vi.fn(),
    technicalsLive: vi.fn().mockResolvedValue({ ticker: "NVDA", available: false }),
    technicalsRefresh: vi.fn(),
  },
}));
// The chart needs a real canvas — stub it out; its logic is covered in Task 8 tests.
vi.mock("@/components/stock/panels/TechnicalsPriceChart", () => ({
  TechnicalsPriceChart: () => <div data-testid="price-chart" />,
}));

import { api } from "@/lib/api";
import { TechnicalsTab } from "@/components/stock/tabs/TechnicalsTab";

describe("TechnicalsTab auto-fill on open", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fires the per-ticker refresh once when the latest row lacks OHLCV", async () => {
    vi.mocked(api.technicals).mockResolvedValue(noOhlcv as never);
    vi.mocked(api.technicalsRefresh).mockResolvedValue(withOhlcv as never);
    render(<TechnicalsTab ticker="NVDA" />);
    await waitFor(() => expect(api.technicalsRefresh).toHaveBeenCalledTimes(1));
    // never re-fires after the fresh (OHLCV-bearing) payload lands
    await waitFor(() => expect(api.technicalsRefresh).toHaveBeenCalledTimes(1));
  });

  it("does not fire when OHLCV is already present", async () => {
    vi.mocked(api.technicals).mockResolvedValue(withOhlcv as never);
    const { findByTestId } = render(<TechnicalsTab ticker="NVDA" />);
    await findByTestId("price-chart");
    expect(api.technicalsRefresh).not.toHaveBeenCalled();
  });
});
```

(If an unrelated sibling panel throws on this minimal fixture — e.g. a detail tile assuming a populated `detail` — extend the fixture minimally or `vi.mock` that panel the same way; the assertion under test is only the `technicalsRefresh` call count.)

- [ ] **Step 10.2: Run — must fail** (import of `TechnicalsPriceChart` from the tab doesn't exist yet / refresh never called)

```bash
cd web && npx vitest run tests/unit/technicalsTabAutofill.test.tsx
```

- [ ] **Step 10.3: Edit `TechnicalsTab.tsx`**

1. Replace the import:
```tsx
import { TechnicalsAnchorChart } from "../panels/TechnicalsAnchorChart";
```
with:
```tsx
import { TechnicalsPriceChart } from "../panels/TechnicalsPriceChart";
```

2. In `TechnicalsTab`, add a `useRef` guard + auto-fill effect after the existing live-poll effect (the base payload — NOT the live-merged one — decides; the live head never carries OHLCV):
```tsx
  // Auto-fill once per mount+ticker: old rows predating migration 105 have
  // null OHLCV; the per-ticker refresh rewrites the ticker's full history.
  const autoFilled = useRef<string | null>(null);
  useEffect(() => {
    const base = state.ticker === ticker ? state.data : null;
    if (!base || base.backfill_status !== "ready") return;
    const s = base.series ?? [];
    const last = s[s.length - 1];
    if (!last || last.open != null) return;
    if (autoFilled.current === ticker) return;
    autoFilled.current = ticker;
    api
      .technicalsRefresh(ticker)
      .then((fresh) => {
        setState((cur) =>
          cur.ticker === ticker ? { ticker, data: fresh, error: null } : cur,
        );
      })
      .catch(() => {
        // Non-fatal: the pane degrades to the close line until the next
        // nightly refresh fills OHLCV.
      });
  }, [state, ticker]);
```

3. Swap the render:
```tsx
      <TechnicalsAnchorChart
        data={view}
        control={<TimeframeSelect value={timeframe} onChange={setTimeframe} />}
      />
```
becomes:
```tsx
      <TechnicalsPriceChart
        data={view}
        control={<TimeframeSelect value={timeframe} onChange={setTimeframe} />}
      />
```

- [ ] **Step 10.4: Retire the SVG pane**

```bash
cd web
grep -rn "TechnicalsAnchorChart" --include="*.ts*" . | grep -v node_modules
```
Expected: zero references outside the file itself (if a test references it, port or delete that test). Then:
```bash
git rm web/components/stock/panels/TechnicalsAnchorChart.tsx
```

- [ ] **Step 10.5: Run the new test + full web suite — must pass**

```bash
cd web && npx vitest run tests/unit/technicalsTabAutofill.test.tsx && npm run test && npm run typecheck && npm run lint
```

- [ ] **Step 10.6: Commit**

```bash
git add web/components/stock/tabs/TechnicalsTab.tsx web/tests/unit/technicalsTabAutofill.test.tsx
git commit -m "feat(web): swap price pane to TechnicalsPriceChart + one-shot OHLCV auto-fill; retire SVG anchor chart"
```
(`git rm` already staged the deletion.)

---

### Task 11: Docs — CLAUDE.md exception, CHANGELOG, spec amendment

**Files:**
- Modify: `web/CLAUDE.md`, `web/components/CLAUDE.md`
- Modify: `CHANGELOG.md` (`[Unreleased]`)
- Modify: `docs/superpowers/specs/2026-07-10-technicals-price-pane-lightweight-charts-design.md` (Decimal→float correction)

- [ ] **Step 11.1: `web/CLAUDE.md`** — change the Conventions line:

```
- **Hand-rolled SVG.** Helpers live in `lib/svgChart.ts` (`linearScale`, `finiteDomain`, `pathFromPoints`). Don't pull in `recharts` / `d3` / `visx`.
```
to:
```
- **Hand-rolled SVG.** Helpers live in `lib/svgChart.ts` (`linearScale`, `finiteDomain`, `pathFromPoints`). Don't pull in `recharts` / `d3` / `visx`. **One documented exception (2026-07-10):** `lightweight-charts` powers the Technicals **price pane only** (`components/stock/panels/TechnicalsPriceChart.tsx` + `lib/lwc/`); every other chart stays hand-rolled SVG.
```
Also update the top summary line "hand-rolled SVG charts (no chart library)" to "hand-rolled SVG charts (no chart library, except lightweight-charts on the Technicals price pane)".

- [ ] **Step 11.2: `web/components/CLAUDE.md`** — change:

```
- **No charting library.** Hand-rolled SVG using `lib/svgChart.ts` helpers.
```
to:
```
- **No charting library.** Hand-rolled SVG using `lib/svgChart.ts` helpers. **One documented exception (2026-07-10):** the Technicals price pane (`panels/TechnicalsPriceChart.tsx`) uses `lightweight-charts` (tiny imperative canvas lib) for candles/zoom/crosshair; do not extend it to other panels without a spec.
```

- [ ] **Step 11.3: CHANGELOG** — read `CHANGELOG.md`, add under `[Unreleased]` (create the section if absent, matching the file's existing heading style):

```markdown
- Technicals price pane migrated to lightweight-charts: candlesticks + volume overlay + filled ±1.5σ band + click-to-anchor VWAP persisted per ticker. `technical_daily` now stores OHLCV (rides the nightly full-recompute; per-ticker auto-fill on first page open), new `technical_vwap_anchor` table, `POST/DELETE /api/stock/{ticker}/vwap-anchor`. (#256)
```

- [ ] **Step 11.4: Spec amendment** — in the spec file, fix the two `Decimal` claims to match the real deriver convention (float): the series-row model line ("all `Decimal | None` / `int | None`" → "`float | None` for O/H/L, `int | None` for volume") and the compute line ("`Decimal` math (matches the derivers convention)" → "float math (matches `cards/technicals.py`'s stated float-only convention; chart-grade series, not money math)").

- [ ] **Step 11.5: Commit**

```bash
git add web/CLAUDE.md web/components/CLAUDE.md CHANGELOG.md \
        docs/superpowers/specs/2026-07-10-technicals-price-pane-lightweight-charts-design.md \
        docs/superpowers/plans/2026-07-10-technicals-lwc-price-pane.md
git commit -m "docs(technicals): lightweight-charts exception, changelog, spec float correction"
```
(Include this plan file itself in the same commit so spec+plan land with the feature, per repo convention.)

---

### Task 12: Full verification + smoke (real worker path)

**Files:** none (verification only; screenshots under `output/playwright/`).

- [ ] **Step 12.1: Full Python suite + the exact CI lint battery**

```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_no_yahoo.py
uv run python scripts/check_migration_prefixes.py
python3 scripts/release/version_sync_check.py
UW_SCAN_DB_HOST=127.0.0.1 uv run pytest -q
```
Expected: all green (reproduce the FULL `lint + unit` job locally — merging over a red one forced fix-forward #164).

- [ ] **Step 12.2: Full web battery**

```bash
cd web && npm run typecheck && npm run test && npm run lint && npm run build
```
Expected: all green.

- [ ] **Step 12.3: Smoke through the real stack** (from the worktree):

```bash
bash scripts/migrate.sh
bash scripts/dev.sh   # web :3001, api :8400, workers
```
Then in a browser (or Playwright MCP), on `http://localhost:3001/stock/NVDA` → Technicals:
1. **Transition gap:** if NVDA's rows predate the change, the pane first shows the close line, the auto-fill fires once (network tab: one `POST .../technicals/refresh`), and after the re-fetch candles + volume render.
2. **Candles + band + SMAs:** candle colors match the Argon palette; the ±1.5σ envelope renders as a filled cloud; SMA20/50/200 colors match the oscillators' legend.
3. **VWAP:** click a bar → dashed VWAP line draws instantly; `POST .../vwap-anchor` returns 200; reload the page → the line is restored from the GET payload; click another bar → re-anchors; the `VWAP ⚓ <date> ✕` chip clears it (`DELETE` → 204) and it stays gone on reload.
4. **No re-fire:** revisit the tab — the network tab shows NO second auto-fill refresh.
5. **Zoom/pan:** scroll-zoom and drag-pan work; the live 25s poll does not reset the zoom.
6. Screenshot the pane states to `output/playwright/technicals-lwc-price-pane-{line,candles,vwap}.png`.

- [ ] **Step 12.4: DB spot-checks**

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "SELECT as_of, open, high, low, close, volume FROM uw_scan.technical_daily WHERE ticker='NVDA' ORDER BY as_of DESC LIMIT 3;" \
  -c "SELECT ticker, anchor_date, jsonb_array_length(vwap_snapshot), computed_at FROM uw_scan.technical_vwap_anchor;"
```
Expected: OHLCV populated on recent rows; one anchor row for the clicked ticker.

- [ ] **Step 12.5: STOP — user validates via the web page.** Do not open a PR until the user has seen the pane and approved. PR body references issue #256; CHANGELOG already rides the branch.

---

## Execution notes

- **Order is strict through Task 7** (each task consumes the previous one's interface). Tasks 8–9 could interleave, but run them in order for clean commits.
- **The horizontal-alignment tradeoff is accepted by design**: the lightweight-charts pane will not be pixel-column-aligned with the SVG oscillators below. Build it, eyeball it in Step 12.3, iterate on margins only if it reads badly. Not a blocker.
- **Deploy note (post-merge, not part of this plan):** the mini picks the feature up via the normal release flow (`cut.sh prepare` → merge → `tag`); migrations 105/106 apply via the profile-gated migrator. First nightly `technical_daily_refresh` bulk-fills OHLCV for the whole watchlist; until then, per-ticker auto-fill covers whatever page the user opens.




