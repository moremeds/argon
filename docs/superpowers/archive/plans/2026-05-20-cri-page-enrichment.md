# CRI Page Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch CRI to use SPX (not SPY) for trend / realized-vol math, add a Validation sub-page under `/regime` that surfaces backtest + OOS findings, add three mean-reversion tiles (VRP, VIX z-score, VIX/VIX3M term structure), and add a regime-aware guidance panel whose copy lives in a config file the API serves.

**Architecture:** Data plumbing is small: the existing `vol_index_lake_sync` nightly already covers the whole `asset_class=volatility/` partition, so SPX (1975→) and VIX3M (2009→) just need a manual kick on first deploy. `cri_scoring.py` switches its SPX-proxy from `daily_ohlc[SPY]` to `vol_index_daily[SPX]` with a SPY fallback for transition safety. New math (VRP, z-score, term ratio) lands as pure functions next to the existing scorers. The API gains two endpoints — `/api/regime/validation` (reads `cri-backtest.md` + a hand-curated `oos-summary.json`) and `/api/regime/guidance` (selects an active rule from `guidance.md` based on CRI level + signals). The UI gains one new sub-tab (`/regime` already has CRI/GEX/VCG; this adds Validation), three tiles under the existing CRI hero, and a guidance panel below the ComponentBars.

**Tech Stack:** Python 3.13 / numpy / Pydantic v2 / FastAPI. React 19 / TypeScript / hand-rolled SVG. psycopg 3. pytest + vitest.

**Scope guard:** This plan covers the four items the user requested in one PR (SPX backfill, validation page, mean-reversion signals, regime guidance). It does **not** add put/call ratio (UW endpoint not yet wired), does **not** add VIX term-structure history charts (single tile only for V1), and does **not** add per-trade recommendations (guidance stays descriptive per the no-naked-shorts rule). A "Re-run backtest" trigger button is also out of scope — the backtest is a CLI today and stays a CLI.

**Non-goals:**
- Changing the CRI math or band thresholds (untouched from the previous PR).
- Replacing SPY in any other scanner (`/cockpit`, gold, watchlist all still use SPY/per-ticker as before).
- Building a notebook → API pipeline. OOS numbers ship as a checked-in JSON snapshot updated by hand when the notebook is re-run.
- Real-time vol signals — page stays end-of-day like the rest of `/regime`.

**Background:**
- Previous PR (`feat/cri-methodology-tune`) shipped re-calibrated scoring + a `cri-backtest.{md,csv}` warm-store report that's currently only ~6 months wide because SPY OHLC in `daily_ohlc` is short.
- The parquet lake at `~/market-warehouse/data-lake/bronze/asset_class=volatility/` has SPX (12,953 rows, 1975→2026) and VIX3M (4,192 rows, 2009→2026) ready to use.
- Existing `vol_index_lake_sync` job covers the whole volatility partition via `list_vol_index_symbols(root)` (verified at `src/uw_scan/worker/jobs/vol_index_lake_sync.py:26`) — so no new fetcher is needed; the job just needs a manual kick the first time.
- The validation notebook at `docs/research/regime/cri-validation.ipynb` Section 9 has the honest OOS framing ("regime monitor, not predictor"); the values land in `oos-summary.json` for API consumption.

---

## File map

**Create:**
- `docs/research/regime/oos-summary.json` — hand-curated OOS table extracted from `cri-validation.ipynb` Section 9 (AUC v1/v2/baseline, threshold-matched P/R)
- `docs/research/regime/guidance.md` — regime-state → guidance copy (markdown + YAML frontmatter per state)
- `src/uw_scan/cards/mean_reversion.py` — `compute_vrp`, `vix_zscore`, `vix_vix3m_ratio` (pure functions)
- `src/uw_scan/api/routers/regime_validation.py` — `GET /api/regime/validation` + `GET /api/regime/guidance`
- `src/uw_scan/api/models/regime_validation.py` — `ValidationResponse`, `GuidanceResponse` Pydantic models
- `web/components/regime/ValidationTab.tsx` — client component rendering backtest + OOS (mounted as a fourth sub-tab inside `RegimePanel.tsx`; no nested route — see Task 12 for the design rationale)
- `web/components/regime/MeanReversionTiles.tsx` — three-tile row
- `web/components/regime/GuidancePanel.tsx` — text panel driven by `/api/regime/guidance`
- `tests/unit/test_mean_reversion.py` — pure-function tests
- `tests/integration/api/test_regime_validation_endpoint.py` — endpoint contract test
- `tests/integration/api/test_regime_guidance_endpoint.py` — endpoint contract test
- `web/tests/unit/MeanReversionTiles.test.tsx`
- `web/tests/unit/GuidancePanel.test.tsx`
- `web/tests/unit/ValidationTab.test.tsx`

**Modify:**
- `src/uw_scan/cards/cri_scoring.py` — switch SPX-proxy source from SPY (daily_ohlc) to SPX (vol_index_daily) with SPY fallback; thread mean-reversion outputs into `run_analysis` payload
- `src/uw_scan/scanners/cri.py` — fetch SPX from `vol_index_daily` first, fall back to SPY from `daily_ohlc`; load VIX3M and pass through
- `src/uw_scan/api/schemas.py` — add `vrp`, `vix_zscore_30d`, `vix_vix3m_ratio`, `vix3m`, and `spx_source: "SPX"|"SPY"` to `CriResponse`
- `src/uw_scan/api/server.py` — mount the new router
- `web/components/regime/CriSubTab.tsx` — add `<MeanReversionTiles />` row + `<GuidancePanel />` block
- `web/components/regime/RegimePanel.tsx` — add fourth in-panel sub-tab "VALIDATION" (TABS array + conditional render)
- `web/lib/types.ts` — regenerated from OpenAPI
- `tests/integration/test_cri_scanner.py` — assert new payload fields + SPX/SPY source flag
- `docs/research/regime/cri-methodology.md` — replace the "using SPY as the SPX proxy" caveat in §3 with the new SPX-first + SPY-fallback wording

---

## Phase 0: Branch + data verification

### Task 0: Confirm branch state + data availability

**Files:**
- None (verification only)

**Branch policy:** this work extends the existing `feat/cri-methodology-tune` branch — the previous PR's commits plus this PR's commits land together as one bundle of CRI improvements. No new branch.

**Commit policy gate:** the repo's standing rule is "never commit without an explicit user request." The user opened this plan with "commit when there is a milestone achieved" (carry-over authorization from the methodology-tune session), so milestone commits are pre-authorized for this execution. If a fresh subagent is dispatched on a future session without that authorization in-context, **stop at each `git commit` step**, stage the changes, and report what would be committed instead. Do not assume authorization carries forward across sessions.

- [ ] **Step 1: Confirm we're on `feat/cri-methodology-tune` with a clean tree**

```bash
git branch --show-current   # expect: feat/cri-methodology-tune
git status                  # expect: only pre-existing unrelated noise (gold snapshots, etc.)
```
If the branch was somehow merged/deleted, recreate from the last commit on this branch (`fb2e28c` at time of plan writing).

- [ ] **Step 2: Confirm SPX and VIX3M are in the lake at the expected paths**

```bash
ls ~/market-warehouse/data-lake/bronze/asset_class=volatility/symbol=SPX/1d.parquet
ls ~/market-warehouse/data-lake/bronze/asset_class=volatility/symbol=VIX3M/1d.parquet
```
Expected: both files exist. If either is missing, stop and tell the user — the parquet lake is maintained by the peer `market-data-warehouse` project and is outside this repo.

- [ ] **Step 3: Confirm the existing sync job *would* pick them up (no new code needed)**

```bash
uv run python -c "
from pathlib import Path
from uw_scan.sources.lake import list_vol_index_symbols
syms = list_vol_index_symbols(Path.home() / 'market-warehouse/data-lake/bronze/asset_class=volatility')
print('lake symbols:', syms)
assert 'SPX' in syms, 'SPX missing from lake'
assert 'VIX3M' in syms, 'VIX3M missing from lake'
print('OK — sync job will cover both on next run')
"
```
Expected: prints all symbols including `SPX` and `VIX3M`, ends with `OK`.

---

## Phase 1: Data backfill (SPX + VIX3M into `vol_index_daily`)

### Task 1: Run the existing nightly sync once to populate SPX + VIX3M

**Files:**
- None (operational only — the existing job at `src/uw_scan/worker/jobs/vol_index_lake_sync.py` already does the work)

- [ ] **Step 1: Snapshot the current DB state for the affected symbols**

```bash
uv run python -c "
import psycopg
from uw_scan.config import Settings
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    for sym in ('VIX', 'VVIX', 'COR1M', 'SPX', 'VIX3M'):
        cur.execute(f'SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM {s.db_schema}.vol_index_daily WHERE symbol=%s', (sym,))
        n, mn, mx = cur.fetchone()
        print(f'{sym}: n={n}, {mn} → {mx}')
"
```
Expected: VIX/VVIX/COR1M populated; SPX and VIX3M likely show `n=0`. Record the numbers so the after-snapshot has a clear diff.

- [ ] **Step 2: Trigger the sync job manually**

```bash
uv run python -c "
from pathlib import Path
import psycopg
from uw_scan.config import Settings
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    summary = run_vol_index_lake_sync(conn, root=s.lake_vol_index_root)
    conn.commit()
    print('sync summary:', summary)
"
```
Expected: prints `{'symbols': N, 'rows': M}` with M in the thousands (full SPX history is ~13k rows; VIX3M ~4k).

- [ ] **Step 3: Confirm SPX + VIX3M now populate**

Repeat Step 1's query. SPX should show n≈12,953 with span 1975-01-02 → today. VIX3M should show n≈4,192 with span 2009-09-18 → today.

- [ ] **Step 4: Commit nothing (this is a data refresh, not a code change)**

Skip the commit; the next task does the code wiring.

---

### Task 2: Switch `cri_scoring.run_analysis` to prefer SPX, fall back to SPY

**Files:**
- Modify: `src/uw_scan/cards/cri_scoring.py` (`run_analysis` accepts `aligned["SPX"]` with `SPY` fallback)
- Test: `tests/unit/test_cri_scoring.py`

**Why fallback:** changing the scanner cleanly is Task 3; this task keeps `run_analysis` flexible so we can ship the math change and the scanner change as separate commits and not break the existing fixture.

- [ ] **Step 1: Write a failing test that proves SPX is preferred when present**

Add to `tests/unit/test_cri_scoring.py` near the existing `_make_aligned` helper:

```python
def test_run_analysis_prefers_spx_over_spy() -> None:
    """When both SPX and SPY are in aligned, SPX drives trend math."""
    n = 140
    aligned = {
        "VIX": np.full(n, 16.0),
        "VVIX": np.full(n, 95.0),
        "SPX": np.linspace(4500, 4800, n),  # SPX-scale levels
        "SPY": np.linspace(450, 480, n),    # SPY-scale levels (10x smaller)
        "COR1M": np.full(n, 20.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    # The "spy" field in the payload should reflect SPX when SPX is the source
    # — the field name stays "spy" for contract continuity, but the source
    # flag tells the truth.
    assert out["spy"] > 4000, f"expected SPX-scale value, got {out['spy']}"
    assert out["spx_source"] == "SPX"


def test_run_analysis_falls_back_to_spy_when_spx_absent() -> None:
    """Without SPX, run_analysis still works with SPY (transition safety)."""
    n = 140
    aligned = {
        "VIX": np.full(n, 16.0),
        "VVIX": np.full(n, 95.0),
        "SPY": np.linspace(450, 480, n),
        "COR1M": np.full(n, 20.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert out["spy"] < 600, f"expected SPY-scale value, got {out['spy']}"
    assert out["spx_source"] == "SPY"
```

- [ ] **Step 2: Run the tests — confirm they fail**

```bash
uv run pytest tests/unit/test_cri_scoring.py -k "spx_over_spy or falls_back" -v
```
Expected: FAIL — `aligned["SPX"]` is not handled; `spx_source` is not in the payload.

- [ ] **Step 3: Update `run_analysis` signature handling**

In `src/uw_scan/cards/cri_scoring.py`, find the top of `run_analysis`:

```python
    vix = aligned["VIX"]
    vvix = aligned["VVIX"]
    spy = aligned["SPY"]
    cor1m_values = aligned["COR1M"]
```

Replace with:

```python
    vix = aligned["VIX"]
    vvix = aligned["VVIX"]
    cor1m_values = aligned["COR1M"]

    # SPX is the right instrument for trend/RV math because the CBOE vol
    # indices (VIX/VVIX/COR1M) are computed against SPX. Fall back to SPY
    # for transition safety while the SPX backfill is rolling out.
    if "SPX" in aligned and len(aligned["SPX"]) > 0:
        spy = aligned["SPX"]
        spx_source = "SPX"
    else:
        spy = aligned["SPY"]
        spx_source = "SPY"
```

And in the return dict at the bottom, add `"spx_source": spx_source` next to the other scalar fields:

```python
        "spy": round(spy_now, 2),
        "spx_source": spx_source,
```

(The variable stays named `spy` everywhere downstream to minimise diff. Only the source label changes.)

- [ ] **Step 4: Run the new tests — confirm they pass**

```bash
uv run pytest tests/unit/test_cri_scoring.py -v
```
Expected: all 30+ tests pass, including the two new ones.

- [ ] **Step 5: Commit (milestone)**

```bash
git add src/uw_scan/cards/cri_scoring.py tests/unit/test_cri_scoring.py
git commit -m "feat(cri): prefer SPX over SPY in run_analysis, expose spx_source"
```

---

### Task 3: Update the CRI scanner to load SPX (with SPY fallback)

**Files:**
- Modify: `src/uw_scan/scanners/cri.py` (fetch SPX from `vol_index_daily` first)
- Test: `tests/integration/test_cri_scanner.py`

- [ ] **Step 1: Read the current scanner's data loading**

```bash
grep -n "SPY\|SPX\|daily_ohlc\|vol_index_daily" src/uw_scan/scanners/cri.py | head -20
```
Identify where it currently calls `repo.fetch_daily_ohlc(ticker="SPY", ...)` or similar.

- [ ] **Step 2: Add a failing integration test**

Add to `tests/integration/test_cri_scanner.py` (mirrors the existing `test_run_persists_snapshot_when_data_is_sufficient`):

```python
def test_run_uses_spx_when_available(seeded_db_empty_cards) -> None:
    """Scanner should load SPX from vol_index_daily when present."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    # Seed SPX (NOT SPY) — the scanner must find it
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None

    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["spx_source"] == "SPX"
    # spy field carries SPX-scale value
    assert snap["spy"] > 4000


def test_run_falls_back_to_spy_when_spx_missing(seeded_db_empty_cards) -> None:
    """Scanner should still work with SPY-only seed (back-compat)."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    # No SPX seeded; SPY is the only price source
    _seed_spy(repo, [450.0 + i * (150.0 / n) for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None

    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["spx_source"] == "SPY"
```

- [ ] **Step 3: Run the tests — confirm they fail**

```bash
uv run pytest tests/integration/test_cri_scanner.py -v
```
Expected: the new test_run_uses_spx_when_available FAILs (scanner doesn't read SPX yet).

- [ ] **Step 4: Update `scanners/cri.py` to load SPX first**

The current code (verified at `src/uw_scan/scanners/cri.py:43-46`) is:

```python
def _load_spy_series(repo: Repository, days: int) -> dict[_date, float]:
    rows = repo.list_daily_ohlc("SPY", limit=days)
    return {r.date: float(r.close) for r in rows}
```

…called at `src/uw_scan/scanners/cri.py:80`:

```python
    raw = {
        "VIX": _load_vol_series(vol_repo, "VIX", LOOKBACK_DAYS),
        "VVIX": _load_vol_series(vol_repo, "VVIX", LOOKBACK_DAYS),
        "COR1M": _load_vol_series(vol_repo, "COR1M", LOOKBACK_DAYS),
        "SPY": _load_spy_series(repo, LOOKBACK_DAYS),
    }
```

The scanner currently inner-joins on `_align(raw)` — every series in `raw` must have data at a given date or that date is dropped from the intersection. So we cannot just add `"SPX"` next to `"SPY"` — the intersection would collapse to dates where *both* exist. Instead, **try SPX first, and fall back to SPY if SPX is empty *or* its overlap is too thin to produce a valid snapshot**.

Add this helper alongside `_load_spy_series`:

```python
def _load_spx_series(vol_repo: VolIndexRepository, days: int) -> dict[_date, float]:
    """SPX closing levels from vol_index_daily (parquet-lake-backed)."""
    return _load_vol_series(vol_repo, "SPX", days)
```

Then replace the `raw` dict construction + alignment at line 80 with a two-attempt block:

```python
    mandatory_vol = {
        "VIX": _load_vol_series(vol_repo, "VIX", LOOKBACK_DAYS),
        "VVIX": _load_vol_series(vol_repo, "VVIX", LOOKBACK_DAYS),
        "COR1M": _load_vol_series(vol_repo, "COR1M", LOOKBACK_DAYS),
    }

    # Attempt 1: SPX from vol_index_daily.
    aligned: dict[str, np.ndarray] = {}
    common_dates: list[str] = []
    spx = _load_spx_series(vol_repo, LOOKBACK_DAYS)
    if spx:
        aligned, common_dates = _align({**mandatory_vol, "SPX": spx})

    # Attempt 2 (fallback): SPY from daily_ohlc. Triggers when SPX is
    # entirely absent OR has insufficient overlap with the mandatory vol
    # series to make MIN_ALIGNED_BARS. A partial SPX backfill must not
    # suppress the snapshot if SPY can still produce one.
    if len(common_dates) < MIN_ALIGNED_BARS:
        log.warning(
            "cri_scan_spx_alignment_thin spx_bars=%d need=%d — falling back to SPY",
            len(common_dates),
            MIN_ALIGNED_BARS,
        )
        spy = _load_spy_series(repo, LOOKBACK_DAYS)
        aligned, common_dates = _align({**mandatory_vol, "SPY": spy})
```

The downstream `if not common_dates or len(common_dates) < MIN_ALIGNED_BARS` guard (already present at lines 84-90) still runs — if even SPY can't make the bar, the scanner skips with the existing log line.

`run_analysis` (after Task 2) reads `aligned["SPX"]` when present and falls back to `aligned["SPY"]` otherwise — so the `spx_source` field on the snapshot correctly reflects whichever path succeeded.

Add an integration test that exercises the fallback explicitly:

```python
def test_run_falls_back_to_spy_when_spx_alignment_too_thin(
    seeded_db_empty_cards,
) -> None:
    """SPX present but only 5 overlapping bars — must retry SPY before skipping."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)
    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    # SPX has only 5 days at the END of the range — overlap is 5 bars,
    # well below MIN_ALIGNED_BARS.
    _seed_vol(vol_repo, "SPX", [4500.0] * 5, start=date(2026, 5, 16))
    # SPY has the full range — fallback should succeed.
    _seed_spy(repo, [450.0 + i * 0.1 for i in range(n)], start=start)

    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["spx_source"] == "SPY"
```

(VIX3M is loaded separately in Task 6 Step 6 — *not* added to the alignment join — keeping the data plumbing in the same task as the math that uses it. See Task 6 for why VIX3M intentionally lives outside the inner-join.)

- [ ] **Step 5: Run the integration tests**

```bash
uv run pytest tests/integration/test_cri_scanner.py -v
```
Expected: all PASS, including the new SPX + fallback tests.

- [ ] **Step 6: Commit (milestone)**

```bash
git add src/uw_scan/scanners/cri.py tests/integration/test_cri_scanner.py
git commit -m "feat(cri): scanner reads SPX from vol_index_daily, falls back to SPY"
```

- [ ] **Step 7: Re-run the production scanner once to update the live snapshot**

```bash
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.scanners.cri import run
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    rid = run(conn, schema=s.db_schema)
    conn.commit()
    print('refreshed snapshot row_id:', rid)
"
```
Expected: a new row_id. The CRI score may shift modestly versus the pre-PR snapshot — calibration didn't change but the trend math now reads the cash SPX rather than the dividend-adjusted SPY, so the 100d MA and 20d realized vol move slightly. A few points of drift is normal and expected; a band change (e.g., LOW → ELEVATED) on the same trading day would warrant investigation.

---

## Phase 2: Re-run the backtest with SPX

### Task 4: Regenerate `cri-backtest.{md,csv}` with the longer SPX history

**Files:**
- Modify: `scripts/backtest_cri.py` (fetch SPX from `vol_index_daily` like the scanner)
- Modify: `docs/research/regime/cri-backtest.{md,csv}` (regenerated)
- Modify: `docs/research/regime/cri-methodology.md` (update §3 caveat + §8 paragraph)

- [ ] **Step 1: Update `fetch_aligned_series` in the backtest script**

Open `scripts/backtest_cri.py`. Find the SPY query:

```python
        cur.execute(
            f"SELECT date, close FROM {schema}.daily_ohlc "
            "WHERE ticker = 'SPY' AND date BETWEEN %s AND %s "
            "AND close IS NOT NULL ORDER BY date",
            (start, end),
        )
        series["SPY"] = {r[0]: float(r[1]) for r in cur.fetchall()}
```

Add an SPX query above it; route SPX → the `SPY` key in the dict if SPX has data:

```python
        # Prefer SPX (CBOE-aligned, longer history) — fall back to SPY
        cur.execute(
            f"SELECT trade_date, close FROM {schema}.vol_index_daily "
            "WHERE symbol = 'SPX' AND trade_date BETWEEN %s AND %s "
            "AND close IS NOT NULL ORDER BY trade_date",
            (start, end),
        )
        spx = {r[0]: float(r[1]) for r in cur.fetchall()}
        if spx:
            series["SPY"] = spx  # downstream key stays "SPY" for back-compat
        else:
            cur.execute(
                f"SELECT date, close FROM {schema}.daily_ohlc "
                "WHERE ticker = 'SPY' AND date BETWEEN %s AND %s "
                "AND close IS NOT NULL ORDER BY date",
                (start, end),
            )
            series["SPY"] = {r[0]: float(r[1]) for r in cur.fetchall()}
```

- [ ] **Step 2: Run the backtest**

```bash
uv run python scripts/backtest_cri.py
```
Expected: log lines now show `aligned NNNN trading days` with NNNN in the thousands (was 274 with SPY-only). The new report writes to `docs/research/regime/cri-backtest.{md,csv}` and Named-crash-dates table will now contain Lehman, COVID, etc.

- [ ] **Step 3: Spot-check the report**

```bash
head -50 docs/research/regime/cri-backtest.md
```
Verify:
- N days now in the thousands.
- Date range starts ≥2006 (intersection lower bound = VVIX's 2006-03-06).
- Named crash dates table is no longer "no aligned data" — Lehman, COVID, etc. should appear with scores.

- [ ] **Step 4: Update `cri-methodology.md` §3 to remove the stale "SPY proxy" comment**

Open `docs/research/regime/cri-methodology.md`. In §3 → Trend Break section, find any mention of "using SPY as the SPX proxy". The actual code now reads SPX with SPY as fallback. Update the paragraph to:

```markdown
Trend distance is computed against **SPX** (closing level from `vol_index_daily`, sourced from the parquet lake). SPY remains as a fallback if SPX is unavailable for the requested window. The `spx_source` field in the API response flags which series fed the day's score.
```

Also update §8 to remove the "warm-store backtest is short because SPY OHLC is short" caveat — that constraint no longer applies after this task.

- [ ] **Step 5: Commit (milestone)**

```bash
git add scripts/backtest_cri.py docs/research/regime/cri-backtest.md docs/research/regime/cri-backtest.csv docs/research/regime/cri-methodology.md
git commit -m "feat(cri): backtest now uses SPX history; methodology doc updated"
```

---

## Phase 3: Mean-reversion math (Python, TDD)

### Task 5: Add `mean_reversion.py` with VRP / z-score / term-structure helpers

**Files:**
- Create: `src/uw_scan/cards/mean_reversion.py`
- Test: `tests/unit/test_mean_reversion.py`

**Why a separate module:** `cri_scoring.py` is already 360 lines and these helpers don't share state with the CRI composite. Keep them isolated so the per-tile UI can call them without dragging the whole composite path.

- [ ] **Step 1: Write failing tests**

Create `tests/unit/test_mean_reversion.py`:

```python
"""Unit tests for VRP / z-score / term-structure helpers."""

import math

import numpy as np
import pytest

from uw_scan.cards.mean_reversion import (
    compute_vrp,
    vix_vix3m_ratio,
    vix_zscore_30d,
)


def test_compute_vrp_positive_when_iv_exceeds_rv() -> None:
    # VIX 20, RV 12 → VRP = +8
    assert compute_vrp(vix=20.0, realized_vol=12.0) == pytest.approx(8.0)


def test_compute_vrp_negative_when_rv_exceeds_iv() -> None:
    # VIX 15, RV 22 → VRP = -7 (rare but happens after a sudden spike)
    assert compute_vrp(vix=15.0, realized_vol=22.0) == pytest.approx(-7.0)


def test_compute_vrp_nan_inputs_return_nan() -> None:
    assert math.isnan(compute_vrp(vix=float("nan"), realized_vol=10.0))
    assert math.isnan(compute_vrp(vix=20.0, realized_vol=float("nan")))


def test_vix_zscore_returns_zero_for_flat_history() -> None:
    arr = np.full(60, 18.0)
    assert vix_zscore_30d(arr) == pytest.approx(0.0)


def test_vix_zscore_returns_nan_when_trailing_std_is_zero_and_today_differs() -> None:
    # 30 trailing days at 15 + today at 25. ZSCORE_WINDOW=30 requires
    # ZSCORE_WINDOW+1 = 31 observations total (30 trailing + 1 today). The
    # trailing window has zero std (all 15s) so the function returns NaN
    # per its degenerate-input contract — there is no scale to normalize
    # the (today − mean) gap against.
    arr = np.concatenate([np.full(30, 15.0), np.array([25.0])])
    assert math.isnan(vix_zscore_30d(arr))


def test_vix_zscore_positive_when_today_above_noisy_mean() -> None:
    # 30 trailing days drawn from mean≈15 std≈1 (so the std is non-zero),
    # then today at 25 → z ≈ 10. Use a fixed seed so the test is deterministic.
    rng = np.random.default_rng(seed=42)
    trailing = rng.normal(loc=15.0, scale=1.0, size=30)
    arr = np.concatenate([trailing, np.array([25.0])])
    z = vix_zscore_30d(arr)
    assert z > 2.0


def test_vix_zscore_nan_for_short_series() -> None:
    # Exactly ZSCORE_WINDOW observations is still insufficient — we need
    # ZSCORE_WINDOW + 1 (trailing window + today).
    arr = np.full(30, 18.0)
    assert math.isnan(vix_zscore_30d(arr))


def test_vix_vix3m_ratio_contango_below_1() -> None:
    # Normal day: VIX 15, VIX3M 17 → ratio 0.88 (contango — vol curve upward)
    assert vix_vix3m_ratio(vix=15.0, vix3m=17.0) == pytest.approx(15.0 / 17.0)


def test_vix_vix3m_ratio_backwardation_above_1() -> None:
    # Stress day: VIX 30, VIX3M 25 → ratio 1.2 (backwardation — front-end stress)
    assert vix_vix3m_ratio(vix=30.0, vix3m=25.0) == pytest.approx(1.2)


def test_vix_vix3m_ratio_nan_on_missing_vix3m() -> None:
    assert math.isnan(vix_vix3m_ratio(vix=18.0, vix3m=float("nan")))
    assert math.isnan(vix_vix3m_ratio(vix=18.0, vix3m=0.0))  # divide-by-zero guard
```

- [ ] **Step 2: Run tests — confirm they fail**

```bash
uv run pytest tests/unit/test_mean_reversion.py -v
```
Expected: FAIL (module doesn't exist).

- [ ] **Step 3: Write the module**

Create `src/uw_scan/cards/mean_reversion.py`:

```python
"""Mean-reversion signals derived from CBOE vol-complex series.

Pure functions; no DB, no network. Inputs are floats / numpy arrays.

References & calibration:

- VRP (Variance Risk Premium). **Vol-unit form**: IV − RV (both annualized
  in % points). We use the vol-unit form for practitioner readability on
  the tile. The canonical academic form (Bollerslev/Tauchen/Zhou 2009,
  "Expected Stock Returns and Variance Risk Premia", RFS 22(11)) is
  **variance-unit**: VIX² − RV². The two carry the same sign and similar
  semantics for the dashboard; we surface vol-units so the value reads in
  the same scale as VIX itself. Positive VRP (the usual case) means
  implied vol exceeds realized — compression toward zero or going negative
  often precedes vol mean-reversion. Realized vol must be annualized in %
  points (matches the units of VIX) and uses the same window as
  cri_scoring.VOL_WINDOW (currently 20 trading days).

- VIX z-score (30d). Today's VIX vs the trailing 30 closes (mean, std).
  ±2σ is the conventional mean-reversion trigger threshold per the
  rolling-z-score literature (QuantStock, iPresage). 30d is the common
  short-window lookback for daily charts.

- VIX/VIX3M ratio. Front-end vs 3-month VIX. Conventional regime bands
  (Macrosynergy "VIX term structure as a trading signal"; volradar.com):
    - < 0.85  → deep contango       (calm, premium-selling friendly)
    - 0.85–0.95 → normal contango   (the modal regime — ~85% of days)
    - 0.95–1.00 → warning / flat    (curve about to flip)
    - 1.00–1.10 → backwardation     (front-end stress, vol expansion)
    - > 1.10  → deep backwardation  (panic / dislocation)
  The cross above 1.0 from below has historically preceded every major
  drawdown in the 1990–2025 window.

See docs/research/regime/cri-methodology.md §6 for how these surface in
the UI.
"""

from __future__ import annotations

import math

import numpy as np

ZSCORE_WINDOW = 30


def compute_vrp(*, vix: float, realized_vol: float) -> float:
    """VRP = VIX (implied) − realized vol. Both in % annualized points."""
    if math.isnan(vix) or math.isnan(realized_vol):
        return float("nan")
    return float(vix - realized_vol)


def vix_zscore_30d(vix_history: np.ndarray) -> float:
    """Z-score of the latest VIX value against the trailing 30 closes.

    Returns NaN if fewer than ZSCORE_WINDOW + 1 observations are provided,
    or if the trailing std is zero (degenerate flat input).
    """
    if vix_history is None or len(vix_history) < ZSCORE_WINDOW + 1:
        return float("nan")
    window = vix_history[-(ZSCORE_WINDOW + 1) : -1]  # trailing N, exclude today
    mu = float(np.mean(window))
    sigma = float(np.std(window, ddof=1))
    if sigma == 0.0:
        # All-flat history → z = 0 only if today equals the mean; else
        # NaN (no scale to normalize against).
        return 0.0 if float(vix_history[-1]) == mu else float("nan")
    return (float(vix_history[-1]) - mu) / sigma


def vix_vix3m_ratio(*, vix: float, vix3m: float) -> float:
    """Front-end / 3-month VIX ratio. <1 contango; >1 backwardation."""
    if math.isnan(vix) or math.isnan(vix3m) or vix3m <= 0:
        return float("nan")
    return float(vix / vix3m)
```

- [ ] **Step 4: Run tests — confirm they pass**

```bash
uv run pytest tests/unit/test_mean_reversion.py -v
```
Expected: 8 PASS.

- [ ] **Step 5: Commit (milestone)**

```bash
git add src/uw_scan/cards/mean_reversion.py tests/unit/test_mean_reversion.py
git commit -m "feat(regime): add VRP / VIX z-score / VIX-VIX3M ratio helpers"
```

---

### Task 6: Wire mean-reversion outputs into `run_analysis` payload

**Files:**
- Modify: `src/uw_scan/cards/cri_scoring.py` (`run_analysis` adds `vrp`, `vix_zscore_30d`, `vix_vix3m_ratio`, `vix3m`)
- Modify: `src/uw_scan/scanners/cri.py` (load VIX3M from `vol_index_daily`, pass through)
- Test: `tests/unit/test_cri_scoring.py`

- [ ] **Step 1: Write a failing test**

Add to `tests/unit/test_cri_scoring.py`:

```python
def test_run_analysis_exposes_mean_reversion_fields() -> None:
    """run_analysis must surface vrp, vix_zscore_30d, vix_vix3m_ratio, vix3m."""
    n = 140
    aligned = {
        "VIX": np.full(n, 20.0),
        "VVIX": np.full(n, 95.0),
        "SPX": np.linspace(4500, 4800, n),
        "VIX3M": np.full(n, 22.0),
        "COR1M": np.full(n, 30.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert "vrp" in out
    assert "vix_zscore_30d" in out
    assert "vix_vix3m_ratio" in out
    assert "vix3m" in out
    # VIX 20, VIX3M 22 → ratio ≈ 0.909 (contango)
    assert 0.8 < out["vix_vix3m_ratio"] < 1.0
    # Flat 20-VIX history → z-score = 0
    assert out["vix_zscore_30d"] == 0.0


def test_run_analysis_vrp_matches_vix_minus_realized_vol_exactly() -> None:
    """Pin the integrated VRP to the exact convention: VIX − annualized 20d SPX RV.

    Flat SPX → realized_vol = 0 → vrp = vix_now. This catches:
    - wrong series (e.g., reading SPY when SPX is present)
    - wrong window (something other than VOL_WINDOW=20)
    - wrong unit convention (using log of prices vs simple, missing sqrt(252), etc.)
    """
    from uw_scan.cards.cri_scoring import VOL_WINDOW

    n = max(140, VOL_WINDOW + 50)
    aligned = {
        "VIX": np.full(n, 18.0),
        "VVIX": np.full(n, 95.0),
        "SPX": np.full(n, 4500.0),  # FLAT — realized vol is exactly 0
        "VIX3M": np.full(n, 19.0),
        "COR1M": np.full(n, 20.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert out["realized_vol"] == pytest.approx(0.0, abs=1e-9)
    # VRP = VIX − 0 = 18.0
    assert out["vrp"] == pytest.approx(18.0, abs=0.01)
    # vix3m_now = 19.0, so ratio = 18/19 ≈ 0.947
    assert out["vix_vix3m_ratio"] == pytest.approx(18.0 / 19.0, abs=1e-3)
```

- [ ] **Step 2: Run — confirm it fails**

```bash
uv run pytest tests/unit/test_cri_scoring.py -k mean_reversion -v
```
Expected: FAIL (`vrp` not in payload).

- [ ] **Step 3: Import the helpers in `cri_scoring.py`**

Add near the existing imports:

```python
from uw_scan.cards.mean_reversion import (
    compute_vrp,
    vix_vix3m_ratio,
    vix_zscore_30d,
)
```

- [ ] **Step 4: Compute and expose the three fields in `run_analysis`**

After the `realized_vol = compute_realized_vol(spy, VOL_WINDOW)` line, add:

```python
    vix3m_arr = aligned.get("VIX3M")
    vix3m_now = (
        float(vix3m_arr[-1])
        if vix3m_arr is not None and len(vix3m_arr) > 0
        else float("nan")
    )
    vrp = compute_vrp(vix=vix_now, realized_vol=realized_vol)
    vix_z = vix_zscore_30d(vix)
    vix_ts_ratio = vix_vix3m_ratio(vix=vix_now, vix3m=vix3m_now)
```

In the return dict at the bottom of `run_analysis`, add these alongside the existing scalars:

```python
        "vix3m": round(vix3m_now, 2) if not math.isnan(vix3m_now) else None,
        "vrp": round(vrp, 2) if not math.isnan(vrp) else None,
        "vix_zscore_30d": round(vix_z, 2) if not math.isnan(vix_z) else None,
        "vix_vix3m_ratio": round(vix_ts_ratio, 3) if not math.isnan(vix_ts_ratio) else None,
```

- [ ] **Step 5: Run test — confirm it passes**

```bash
uv run pytest tests/unit/test_cri_scoring.py -v
```
Expected: all PASS.

- [ ] **Step 6: Wire VIX3M as a sidecar lookup (NOT in the alignment join)**

VIX3M is needed only for today's term-structure tile — a single scalar `vix3m_now`. It must NOT go into the inner-join `raw` dict from Task 3 Step 4: doing so would make a stale/disjoint VIX3M sync collapse the entire CRI snapshot, since `_align` (lines 48-65 of `scanners/cri.py`) drops every date that any keyed series is missing. A lagging VIX3M lake sync would then suppress the snapshot instead of just rendering "—" in the term-structure tile.

In `src/uw_scan/scanners/cri.py`, after the SPX-or-SPY fallback block from Task 3 Step 4 and before the `if not common_dates ...` guard, load VIX3M independently:

```python
    # VIX3M is optional and intentionally OUTSIDE the alignment join. We
    # want today's value (or the latest available close on the same date
    # as the CRI snapshot) for the term-structure tile; we do NOT want a
    # stale VIX3M sync to suppress the whole snapshot.
    vix3m_series = _load_vol_series(vol_repo, "VIX3M", LOOKBACK_DAYS)
```

Then in the `run_analysis` call (around line 92), build the aligned VIX3M array (or empty) and pass it in:

```python
    if vix3m_series and common_dates:
        # Convert ISO date strings back to date objects to look up matching VIX3M closes.
        vix3m_aligned = np.array(
            [vix3m_series.get(_date.fromisoformat(d), float("nan")) for d in common_dates],
            dtype=float,
        )
        aligned["VIX3M"] = vix3m_aligned

    payload = cri_scoring.run_analysis(aligned, common_dates)
```

`run_analysis` (Step 4 above) already handles `aligned.get("VIX3M")` returning None or an array — missing/NaN propagates to `vix_vix3m_ratio = None` in the payload, which the guidance rule `low_missing_term_structure` (Task 9 Step 1) then catches with explicit fallback copy.

**Test coverage** — verify both presence and absence of VIX3M don't break the snapshot:

```python
def test_run_persists_snapshot_when_vix3m_is_completely_missing(
    seeded_db_empty_cards,
) -> None:
    """No VIX3M at all → snapshot still writes, vix3m/vrp/ratio fields are null."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)
    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)
    # Deliberately no VIX3M seed.
    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["vix3m"] is None
    assert snap["vix_vix3m_ratio"] is None
    # VRP doesn't depend on VIX3M, so it should still be populated.
    assert snap["vrp"] is not None


def test_run_persists_snapshot_when_vix3m_is_stale(seeded_db_empty_cards) -> None:
    """VIX3M ends a week before CRI snapshot date → vix3m_now=None, scan still succeeds."""
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)
    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [16.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)
    # VIX3M only for the first 100 days — stale by the time we scan.
    _seed_vol(vol_repo, "VIX3M", [21.0] * 100, start=start)
    row_id = cri_scanner.run(conn, schema=repo._schema)
    assert row_id is not None
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    # The "today" date is the latest aligned date (day 140-ish); VIX3M
    # has no entry there, so the field reads null.
    assert snap["vix3m"] is None
```

The backtest script (`scripts/backtest_cri.py`) does NOT load VIX3M either — its job is the historical CRI composite, not the mean-reversion enrichment.

- [ ] **Step 7: Update the integration test**

Add to `tests/integration/test_cri_scanner.py`:

```python
def test_run_persists_mean_reversion_fields(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    conn = repo.conn
    vol_repo = VolIndexRepository(conn, schema=repo._schema)

    n = 140
    start = date(2026, 1, 1)
    _seed_vol(vol_repo, "VIX", [18.0] * n, start=start)
    _seed_vol(vol_repo, "VVIX", [95.0] * n, start=start)
    _seed_vol(vol_repo, "COR1M", [20.0] * n, start=start)
    _seed_vol(vol_repo, "VIX3M", [21.0] * n, start=start)  # contango
    _seed_vol(vol_repo, "SPX", [4500.0 + i for i in range(n)], start=start)

    cri_scanner.run(conn, schema=repo._schema)
    snap = CriSnapshotRepository(conn, schema=repo._schema).fetch_latest()
    assert snap["vix3m"] == 21.0
    assert snap["vrp"] is not None
    assert snap["vix_vix3m_ratio"] is not None
    assert snap["vix_vix3m_ratio"] < 1.0  # 18/21 = 0.857 → contango
```

- [ ] **Step 8: Run integration tests**

```bash
uv run pytest tests/integration/test_cri_scanner.py -v
```
Expected: PASS.

- [ ] **Step 9: Commit (milestone)**

```bash
git add src/uw_scan/cards/cri_scoring.py src/uw_scan/scanners/cri.py tests/unit/test_cri_scoring.py tests/integration/test_cri_scanner.py
git commit -m "feat(cri): expose VRP / VIX z-score / VIX-VIX3M ratio in snapshot"
```

---

## Phase 4: API contract — Pydantic + routers + types

### Task 7: Extend `CriResponse` with mean-reversion fields

**Files:**
- Modify: `src/uw_scan/api/schemas.py` (`CriResponse`)
- Regenerate: `tests/integration/api/openapi.snapshot.json`
- Regenerate: `web/lib/types.ts`

- [ ] **Step 1: Add the new fields to `CriResponse`**

Open `src/uw_scan/api/schemas.py`. In `CriResponse` (after the existing `vvix_5d_roc`/`vvix_vix_ratio` block from the previous PR), add:

```python
    vix3m: float | None = None
    vrp: float | None = None
    vix_zscore_30d: float | None = None
    vix_vix3m_ratio: float | None = None
    spx_source: Literal["SPX", "SPY"] | None = None
```

- [ ] **Step 2: Regenerate the openapi snapshot**

```bash
uv run python -c "
import json
from pathlib import Path
from fastapi.testclient import TestClient
from uw_scan.api.server import create_app
app = create_app()
client = TestClient(app)
spec = client.get('/openapi.json').json()
Path('tests/integration/api/openapi.snapshot.json').write_text(json.dumps(spec, indent=2, sort_keys=True))
print('snapshot regenerated')
"
```

- [ ] **Step 3: Verify the snapshot test passes**

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```

- [ ] **Step 4: Regenerate `web/lib/types.ts`**

The two steps must run sequentially in one shell — `/tmp/uw_openapi.json` is the input to `openapi-typescript` and must exist + be current. Don't re-use a leftover file from a prior session:

```bash
uv run python -c "
import json
from pathlib import Path
from fastapi.testclient import TestClient
from uw_scan.api.server import create_app
Path('/tmp/uw_openapi.json').write_text(json.dumps(TestClient(create_app()).get('/openapi.json').json()))
print('wrote /tmp/uw_openapi.json')
" && npx --prefix web openapi-typescript /tmp/uw_openapi.json -o web/lib/types.ts
grep -E "vrp|vix_zscore|vix_vix3m_ratio|spx_source" web/lib/types.ts | head
```
Expected: `wrote /tmp/uw_openapi.json` log line, then `openapi-typescript` runs against the freshly-written file, then `grep` shows all four fields in `CriResponse`.

---

### Task 8: Build `/api/regime/validation` endpoint

**Files:**
- Create: `src/uw_scan/api/models/regime_validation.py`
- Create: `src/uw_scan/api/routers/regime_validation.py`
- Create: `docs/research/regime/oos-summary.json`
- Modify: `src/uw_scan/api/server.py`
- Test: `tests/integration/api/test_regime_validation_endpoint.py`

- [ ] **Step 1: Extract real OOS numbers from the notebook and write the JSON snapshot**

`docs/research/regime/cri-validation.ipynb` Section 9 ("OOS Validation — final scoreboard") contains the authoritative numbers. Open the notebook, copy the final scoreboard table values, and write them into `docs/research/regime/oos-summary.json`. Use the schema below; **replace every numeric value with the actual notebook output** before committing. Do not ship placeholder numbers — the validation page renders these as live data and a placeholder is a lie at the API surface.

If the notebook hasn't been executed end-to-end recently (kernel state lost), re-run it first: `cd docs/research/regime && uv run jupyter nbconvert --to notebook --execute cri-validation.ipynb --output cri-validation.ipynb` then re-read Section 9.

If Section 9 has fewer than 3 model rows or fewer than the 3 labels below, edit the JSON to match what the notebook actually reports; do not invent rows. If a column is missing for a model (e.g., the v1 baseline wasn't scored on `label_dd10`), leave that field `null` — the React table renders `—` for nulls.

Schema:

```json
{
  "as_of": "<YYYY-MM-DD when the notebook was last executed>",
  "notebook": "docs/research/regime/cri-validation.ipynb",
  "method": "<one-line description from notebook Section 9>",
  "labels": [
    {"name": "label_dd5", "definition": "SPX -5% drawdown within 20 trading days"},
    {"name": "label_vix30", "definition": "VIX >= 30 within 10 trading days"},
    {"name": "label_dd10", "definition": "SPX -10% drawdown within 60 trading days"}
  ],
  "scores": [
    {"model": "CRI v1 (pre-PR)",  "auc_dd5": <from notebook>, "auc_vix30": <from notebook or null>, "auc_dd10": <from notebook or null>},
    {"model": "CRI v2 (post-PR)", "auc_dd5": <from notebook>, "auc_vix30": <from notebook or null>, "auc_dd10": <from notebook or null>},
    {"model": "Naive VIX p80",    "auc_dd5": <from notebook>, "auc_vix30": <from notebook or null>, "auc_dd10": <from notebook or null>}
  ],
  "interpretation": "<one-paragraph honest framing from notebook Section 9 conclusion>"
}
```

Verify the file with `python -c "import json; json.load(open('docs/research/regime/oos-summary.json'))"` — must parse cleanly.

- [ ] **Step 2: Define Pydantic models**

Create `src/uw_scan/api/models/regime_validation.py`:

```python
"""Response models for the /api/regime/validation endpoint."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OosLabel(BaseModel):
    name: str
    definition: str


class OosScore(BaseModel):
    model: str
    auc_dd5: float | None = None
    auc_vix30: float | None = None
    auc_dd10: float | None = None


class OosSummary(BaseModel):
    as_of: str
    notebook: str
    method: str
    labels: list[OosLabel]
    scores: list[OosScore]
    interpretation: str


class ValidationResponse(BaseModel):
    """Combined warm-store backtest + OOS notebook summary."""

    backtest_md: str  # raw markdown body
    backtest_csv_rows: int  # row count of the companion CSV
    oos: OosSummary | None = None
```

Add it to `src/uw_scan/api/models/__init__.py` exports.

- [ ] **Step 3: Write a failing endpoint test**

Create `tests/integration/api/test_regime_validation_endpoint.py`:

```python
"""Endpoint contract test for GET /api/regime/validation."""

from __future__ import annotations


def test_validation_endpoint_returns_backtest_md(client) -> None:
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 200
    body = resp.json()
    assert "backtest_md" in body
    assert body["backtest_md"].startswith("# CRI Backtest")
    assert "backtest_csv_rows" in body
    assert body["backtest_csv_rows"] > 0


def test_validation_endpoint_includes_oos_summary(client) -> None:
    resp = client.get("/api/regime/validation")
    body = resp.json()
    assert body["oos"] is not None
    assert body["oos"]["interpretation"]
    assert len(body["oos"]["scores"]) >= 2


# --- Failure-mode tests (the riskiest behaviour in this endpoint) -----

def test_validation_404_when_backtest_md_missing(client, monkeypatch, tmp_path) -> None:
    """If cri-backtest.md is missing, return 404 with an actionable message."""
    from uw_scan.api.routers import regime_validation
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 404
    assert "cri-backtest.md" in resp.json()["detail"]


def test_validation_500_when_oos_summary_malformed(client, monkeypatch, tmp_path) -> None:
    """A corrupt oos-summary.json should 500 with the parse error visible, not silently null."""
    from uw_scan.api.routers import regime_validation
    (tmp_path / "cri-backtest.md").write_text("# CRI Backtest\n")
    (tmp_path / "cri-backtest.csv").write_text("date,score\n2026-01-01,5\n")
    (tmp_path / "oos-summary.json").write_text("{not valid json")
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 500
    assert "malformed" in resp.json()["detail"]


def test_validation_rejects_symlink_under_docs_dir(client, monkeypatch, tmp_path) -> None:
    """A symlink in the docs dir must not let the API serve arbitrary file content."""
    from uw_scan.api.routers import regime_validation
    secret = tmp_path / "secret.md"
    secret.write_text("SECRET DO NOT LEAK")
    (tmp_path / "cri-backtest.md").symlink_to(secret)
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 404
    assert "regular file" in resp.json()["detail"]
```

- [ ] **Step 4: Run — confirm it fails**

```bash
uv run pytest tests/integration/api/test_regime_validation_endpoint.py -v
```
Expected: 404 (endpoint not mounted).

- [ ] **Step 5: Implement the router**

Create `src/uw_scan/api/routers/regime_validation.py`:

```python
"""Read-only endpoints for the /regime/validation sub-page.

GET /api/regime/validation — returns the warm-store backtest markdown +
  CSV row count + a hand-curated OOS summary loaded from
  docs/research/regime/oos-summary.json.

GET /api/regime/guidance — returns the active regime-state guidance rule
  selected from docs/research/regime/guidance.md based on the current CRI
  snapshot (level + signals).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from uw_scan.api.models.regime_validation import (
    OosSummary,
    ValidationResponse,
)

router = APIRouter(prefix="/api/regime", tags=["regime"])

_DOCS_REGIME = (Path(__file__).resolve().parents[3].parent / "docs" / "research" / "regime").resolve()


def _safe_doc_path(filename: str) -> Path:
    """Resolve a docs/research/regime/<filename> path with four guards:

    1. No directory components in `filename` (no `..`, no `/`).
    2. The literal `_DOCS_REGIME/<filename>` path must NOT be a symlink.
       Check this BEFORE `.resolve()` — once resolved, the symlink-ness
       is gone (you see the target). Even a symlink whose target is
       inside `_DOCS_REGIME` is rejected: only directly-checked-in
       files are servable.
    3. Resolved target must stay within `_DOCS_REGIME` (defense in
       depth, in case point 2 misses a weird filesystem trick).
    4. Resolved target must be a regular file (not a directory).

    Threat model: a committed or deployed symlink under
    `docs/research/regime/` could otherwise let the API serve arbitrary
    readable local file content. The plan's stated threat model treats
    the docs dir as "editable by anyone with repo write access," so we
    don't trust path resolution to stay there.
    """
    if "/" in filename or filename.startswith("."):
        raise HTTPException(400, f"invalid filename: {filename!r}")
    raw = _DOCS_REGIME / filename
    if raw.is_symlink():
        raise HTTPException(404, f"{filename}: not a regular file (symlink)")
    if not raw.exists():
        raise HTTPException(404, f"{filename}: not found")
    candidate = raw.resolve()
    if not candidate.is_relative_to(_DOCS_REGIME):
        raise HTTPException(400, "path escapes docs/research/regime/")
    if not candidate.is_file():
        raise HTTPException(404, f"{filename}: not a regular file")
    return candidate


def _read_oos_summary() -> OosSummary | None:
    try:
        path = _safe_doc_path("oos-summary.json")
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    try:
        return OosSummary.model_validate_json(path.read_text())
    except Exception as exc:
        raise HTTPException(500, f"oos-summary.json malformed: {exc!r}") from exc


def _count_csv_rows(filename: str) -> int:
    try:
        path = _safe_doc_path(filename)
    except HTTPException as exc:
        if exc.status_code == 404:
            return 0
        raise
    with path.open() as f:
        return sum(1 for _ in csv.DictReader(f))


@router.get("/validation", response_model=ValidationResponse)
def get_validation() -> ValidationResponse:
    # _safe_doc_path raises 404 with a precise reason (not-found vs symlink vs
    # not-regular-file) — let it propagate rather than masking everything as
    # "missing." Operators benefit from seeing the actual rejection cause.
    md_path = _safe_doc_path("cri-backtest.md")
    return ValidationResponse(
        backtest_md=md_path.read_text(),
        backtest_csv_rows=_count_csv_rows("cri-backtest.csv"),
        oos=_read_oos_summary(),
    )
```

- [ ] **Step 6: Mount the router in `server.py`**

In `src/uw_scan/api/server.py`, add to the router imports and `create_app()`:

```python
from uw_scan.api.routers import regime_validation
...
app.include_router(regime_validation.router)
```

- [ ] **Step 7: Re-run the endpoint test**

```bash
uv run pytest tests/integration/api/test_regime_validation_endpoint.py -v
```
Expected: 2 PASS.

- [ ] **Step 8: Regenerate the OpenAPI snapshot + types**

Both writes happen in one Python block (snapshot + `/tmp/uw_openapi.json`), then `openapi-typescript` consumes the fresh file. Chain with `&&` so a snapshot-write failure aborts before typegen:

```bash
uv run python -c "
import json
from pathlib import Path
from fastapi.testclient import TestClient
from uw_scan.api.server import create_app
spec = TestClient(create_app()).get('/openapi.json').json()
Path('tests/integration/api/openapi.snapshot.json').write_text(json.dumps(spec, indent=2, sort_keys=True))
Path('/tmp/uw_openapi.json').write_text(json.dumps(spec))
print('wrote snapshot + /tmp/uw_openapi.json')
" && npx --prefix web openapi-typescript /tmp/uw_openapi.json -o web/lib/types.ts
```

- [ ] **Step 9: Commit (milestone)**

```bash
git add docs/research/regime/oos-summary.json src/uw_scan/api/models/regime_validation.py src/uw_scan/api/routers/regime_validation.py src/uw_scan/api/server.py tests/integration/api/test_regime_validation_endpoint.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(regime): /api/regime/validation endpoint + OOS summary snapshot"
```

---

### Task 9: Build `/api/regime/guidance` endpoint + config

**Files:**
- Create: `docs/research/regime/guidance.md`
- Modify: `pyproject.toml` (declare `pyyaml` as a direct dep — `import yaml` shouldn't ride on a transitive)
- Modify: `src/uw_scan/api/models/regime_validation.py` (add `GuidanceResponse`)
- Modify: `src/uw_scan/api/routers/regime_validation.py` (add the route)
- Test: `tests/integration/api/test_regime_guidance_endpoint.py`, `tests/unit/test_guidance_condition_evaluator.py`

- [ ] **Step 0: Add `pyyaml` as a direct dependency**

The guidance parser uses `import yaml`. PyYAML is currently only pulled transitively (verify with `uv tree | grep -i pyyaml`), so a future dependency cleanup could break the API at import time. Declare it directly:

In `pyproject.toml` (lines 10–23, the `dependencies = [...]` list), append:

```toml
  "pyyaml>=6.0",
```

Then `uv sync --extra postgres` to refresh the lock. Confirm import works:

```bash
uv run python -c "import yaml; print(yaml.__version__)"
```

- [ ] **Step 1: Write the guidance config**

Create `docs/research/regime/guidance.md`. Each section is a regime state with YAML frontmatter and prose:

```markdown
---
state: low_contango
condition: "level == 'LOW' and vix_vix3m_ratio < 0.95"
posture: opportunistic
---

**LOW + contango.** Vol is cheap. Term structure is upward-sloping. Defined-risk *long-vol* setups become attractive: long puts, long VIX calls, long-vega vertical debit spreads. Mean-reversion in vol is dormant — don't expect vol compression as a tailwind. No short-vol exposure beyond defined-risk credit spreads with hard stops.

---
state: low_neutral
condition: "level == 'LOW' and 0.95 <= vix_vix3m_ratio < 1.0"
posture: neutral
---

**LOW + flat curve.** No directional vol edge. Premium selling (defined-risk only — iron condors, credit verticals, cash-secured puts) is consistent with the regime, but size small and respect the no-naked-shorts rule. Watch for vix_vix3m_ratio crossing 1.0 — that's the regime-flip signal.

---
state: low_missing_term_structure
condition: "level == 'LOW' and vix_vix3m_ratio is None"
posture: neutral
---

**LOW + term structure unavailable.** CRI is in the LOW band but VIX3M data is missing today, so we can't read the curve shape (contango vs backwardation). Treat as a flat/unknown regime: no directional vol edge to lean on. Defined-risk strategies (iron condors, credit verticals — never naked) are still consistent with the LOW level, but size small until the term-structure tile is back. Check the data sync job (`vol_index_lake_sync`) if this persists into a second session.

---
state: elevated_contango
condition: "level == 'ELEVATED' and vix_vix3m_ratio < 1.0"
posture: cautious
---

**ELEVATED + contango.** Stress is brewing but the curve hasn't flipped yet. Trim short-vol exposure; consider rolling defined-risk credit positions out in time to reduce gamma. Don't initiate new short-vol. Long-vol can still work as a hedge but is less cheap than in LOW.

---
state: elevated_backwardation
condition: "level == 'ELEVATED' and vix_vix3m_ratio >= 1.0"
posture: defensive
---

**ELEVATED + backwardation.** The vol curve has inverted — historically the leading edge of a stress regime. Defensive posture: no new short-vol of any kind. Existing short-vol positions should be reduced or fully hedged. Long-vol is no longer cheap but is the regime's natural friend.

---
state: elevated_missing_term_structure
condition: "level == 'ELEVATED' and vix_vix3m_ratio is None"
posture: cautious
---

**ELEVATED + term structure unavailable.** Stress signals are firing but the curve-shape input is missing today, so we can't tell whether the front-end has flipped into backwardation. Default to cautious without commitments either way: trim existing short-vol exposure as if the curve might be inverting, but don't add new long-vol bets that depend on a confirmed flip. Investigate the `vol_index_lake_sync` job before next session.

---
state: high
condition: "level == 'HIGH'"
posture: defensive
---

**HIGH.** Multiple stress dimensions are firing. Capital preservation first. Defined-risk short-vol is high-edge but high-noise — only if you can stomach the variance. Long-vol is expensive; better to use SPX/SPY put spreads than naked VIX calls.

---
state: critical
condition: "level == 'CRITICAL'"
posture: defensive
---

**CRITICAL.** Consistent with the worst historical drawdowns. The crash trigger may or may not have fired separately. Position sizing should be at minimum. Avoid initiating new positions of any flavor; the variance on every greek is at multi-year highs.
```

**Note on the condition expression language.** Each `condition` value is a single Python-expression string evaluated against a context dict containing `level: str`, `vix_vix3m_ratio: float | None`, `vrp: float | None`, `vix_zscore_30d: float | None`. The expression is evaluated by a hand-rolled AST-whitelist evaluator (Step 3 below) — **not** Python's built-in `eval`. Allowed nodes: `Expression`, `BoolOp`, `Compare`, `UnaryOp`, `Name`, `Constant`. Allowed ops: `==`, `!=`, `<`, `<=`, `>`, `>=`, `is`, `is not`, `and`, `or`, `not`. String literals must be quoted (`'LOW'`, not `LOW`). Use `is None` / `is not None` for the missing-data check — when VIX3M is absent from the snapshot, the field is `None` rather than 0.0 (a 0.0 sentinel would falsely match `< 0.95` and serve the wrong guidance). Anything else raises a parse or type error at startup and the rule is skipped with a warning — no silent fallthrough.

- [ ] **Step 2: Add `GuidanceResponse` model**

In `src/uw_scan/api/models/regime_validation.py`, append:

```python
class GuidanceResponse(BaseModel):
    state: str
    # Literal so openapi-typescript emits a tight union on the client and the
    # React tile's switch is exhaustively type-checked.
    posture: Literal["opportunistic", "neutral", "cautious", "defensive"]
    body_md: str  # the prose section as raw markdown
    matched_condition: str  # the condition string, for transparency
```

- [ ] **Step 3: Implement the AST-whitelist evaluator + selection logic**

In `src/uw_scan/api/routers/regime_validation.py`, add the endpoint. **No `eval`** — we use a hand-rolled AST evaluator that walks only a whitelisted set of node and operator types. This is the security boundary: even though `guidance.md` is checked-in (not external input), the file is editable by anyone with repo write access, and a typo in a `condition` line shouldn't be able to execute arbitrary code. Empty-builtins `eval` is bypassable via attribute walks like `().__class__.__bases__[0].__subclasses__()`; the AST whitelist is bypass-resistant by construction.

The frontmatter file is parsed by splitting on the YAML `---` document separator and feeding each section to `yaml.safe_load` (Step 0 above made `pyyaml` a direct dep, so the import is guaranteed). We deliberately don't pull in `python-frontmatter` — same parsing surface, extra dependency.

```python
"""Guidance endpoint with AST-whitelist condition evaluator.

Why the AST whitelist (not eval): eval with empty __builtins__ is
sandbox-escapable (subclass-walk attacks are well-documented). The
conditions live in a checked-in markdown file, but that file is
editable by anyone with repo write access — a typo or a malicious
PR shouldn't be able to RCE. The whitelist parses one Python
expression and rejects every node type that isn't in the allowed
set, so the worst a bad condition can do is raise ValueError.
"""

from __future__ import annotations

import ast
import logging
import operator as _op
from typing import Annotated, Any

import yaml
from fastapi import Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

# Allowed Compare ops and BoolOp/UnaryOp ops. Only these can appear in
# a guidance condition; anything else raises ValueError below.
_CMP_OPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: _op.eq, ast.NotEq: _op.ne,
    ast.Lt: _op.lt, ast.LtE: _op.le,
    ast.Gt: _op.gt, ast.GtE: _op.ge,
    ast.Is: _op.is_, ast.IsNot: _op.is_not,
}
_BOOL_OPS: dict[type[ast.boolop], Any] = {
    ast.And: lambda values: all(values),
    ast.Or: lambda values: any(values),
}
_UNARY_OPS: dict[type[ast.unaryop], Any] = {ast.Not: _op.not_}


def _eval_node(node: ast.AST, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, ctx)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise ValueError(f"constant type {type(node.value).__name__} forbidden")
    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        raise ValueError(f"unknown name {node.id!r}")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, ctx)
        result = True
        for op_node, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval_node(comparator, ctx)
            fn = _CMP_OPS.get(type(op_node))
            if fn is None:
                raise ValueError(f"forbidden compare op {type(op_node).__name__}")
            result = result and fn(left, right)
            left = right  # chained comparison: a < b < c reads (a<b) and (b<c)
        return result
    if isinstance(node, ast.BoolOp):
        fn = _BOOL_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"forbidden bool op {type(node.op).__name__}")
        return fn(_eval_node(v, ctx) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"forbidden unary op {type(node.op).__name__}")
        return fn(_eval_node(node.operand, ctx))
    raise ValueError(f"forbidden node {type(node).__name__}")


def _evaluate_condition(expr: str, ctx: dict[str, Any]) -> bool:
    """Parse + evaluate a guidance condition. Raises ValueError on bad input."""
    tree = ast.parse(expr, mode="eval")
    return bool(_eval_node(tree, ctx))


def _parse_guidance_md() -> list[dict[str, Any]]:
    """Split guidance.md on `---` separators; load YAML frontmatter + body."""
    try:
        path = _safe_doc_path("guidance.md")
    except HTTPException as exc:
        if exc.status_code == 404:
            return []
        raise
    text = path.read_text()
    # Split on lines that are exactly '---'. The file starts with '---',
    # so the first chunk is empty; alternating chunks are frontmatter/body.
    chunks = [c.strip() for c in text.split("\n---\n")]
    # Re-pair: with leading '---', chunks come as ['', front0, body0, front1, body1, ...]
    if chunks and chunks[0].startswith("---"):
        chunks[0] = chunks[0].lstrip("-").strip()
    rules: list[dict[str, Any]] = []
    i = 0
    while i + 1 < len(chunks):
        front_raw, body = chunks[i], chunks[i + 1]
        if not front_raw or not body:
            i += 2
            continue
        try:
            meta = yaml.safe_load(front_raw) or {}
        except yaml.YAMLError as exc:
            logger.warning("guidance_yaml_skipped chunk=%d err=%r", i, exc)
            i += 2
            continue
        if isinstance(meta, dict) and {"state", "condition", "posture"} <= meta.keys():
            meta["body_md"] = body
            rules.append(meta)
        i += 2
    return rules


def _select_rule(
    rules: list[dict[str, Any]], snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    """Pick the first rule whose condition evaluates True against the snapshot.

    Important: missing optional fields stay None, not 0.0. Coercing
    `vix_vix3m_ratio` to 0.0 when VIX3M is absent would falsely match
    `vix_vix3m_ratio < 0.95` (the low_contango rule) and serve a confident
    "calm, premium-selling friendly" guidance for a snapshot whose term
    structure is literally unknown. None propagates through comparisons
    as TypeError, which the catch above turns into a skip — so the rule
    fall-through correctly lands on a level-only rule (low_missing_term
    or one of the high/critical level-only rules).
    """
    ctx: dict[str, Any] = {
        "level": snapshot.get("cri", {}).get("level", "LOW"),
        "vix_vix3m_ratio": snapshot.get("vix_vix3m_ratio"),  # None if VIX3M missing
        "vrp": snapshot.get("vrp"),
        "vix_zscore_30d": snapshot.get("vix_zscore_30d"),
    }
    for rule in rules:
        try:
            ok = _evaluate_condition(rule["condition"], ctx)
        except (ValueError, SyntaxError, TypeError) as exc:
            # TypeError: a well-formed expression like `level < 1` is a valid
            # AST but blows up at op time when the operator runs on
            # incompatible types (str < int). Catching it here keeps one
            # bad rule from 500'ing the whole endpoint — we log and move on.
            logger.warning(
                "guidance_condition_skipped state=%s err=%r",
                rule.get("state"),
                exc,
            )
            continue
        if ok:
            return rule
    return None


@router.get("/guidance", response_model=GuidanceResponse)
def get_guidance(
    repo: Annotated[Repository, Depends(get_repo)],
) -> GuidanceResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo._schema)
    snap = snap_repo.fetch_latest()
    if snap is None:
        raise HTTPException(404, "no CRI snapshot — run the scanner first")
    rules = _parse_guidance_md()
    if not rules:
        raise HTTPException(500, "guidance.md missing or has no parseable rules")
    rule = _select_rule(rules, snap)
    if rule is None:
        raise HTTPException(500, "no guidance rule matched the current snapshot")
    return GuidanceResponse(
        state=rule["state"],
        posture=rule["posture"],
        body_md=rule["body_md"],
        matched_condition=rule["condition"],
    )
```

- [ ] **Step 3a: Add unit tests for the AST evaluator (security boundary)**

Create `tests/unit/test_guidance_condition_evaluator.py`. These tests are the security contract — any failure means the whitelist has a hole:

```python
"""Unit tests for the AST-whitelist condition evaluator.

The evaluator is a security boundary. Tests cover:
1. Valid conditions evaluate correctly.
2. Every common eval-sandbox-escape pattern raises ValueError.
"""
from __future__ import annotations

import pytest

from uw_scan.api.routers.regime_validation import _evaluate_condition


CTX = {
    "level": "LOW",
    "vix_vix3m_ratio": 0.92,
    "vrp": 5.2,
    "vix_zscore_30d": 1.1,
}


def test_simple_compare_true() -> None:
    assert _evaluate_condition("level == 'LOW'", CTX) is True


def test_chained_compare() -> None:
    assert _evaluate_condition("0.9 <= vix_vix3m_ratio < 1.0", CTX) is True


def test_and_or_not() -> None:
    assert _evaluate_condition(
        "level == 'LOW' and (vrp > 0 or vix_zscore_30d > 3)", CTX
    ) is True
    assert _evaluate_condition("not (level == 'HIGH')", CTX) is True


def test_subscript_attribute_call_all_rejected() -> None:
    # Each of these is a known eval-sandbox-escape vector.
    for expr in (
        "().__class__.__bases__[0].__subclasses__()",
        "level.upper()",
        "[1, 2, 3][0]",
        "lambda: 1",
        "__import__('os')",
    ):
        with pytest.raises((ValueError, SyntaxError)):
            _evaluate_condition(expr, CTX)


def test_unknown_name_rejected() -> None:
    with pytest.raises(ValueError, match="unknown name"):
        _evaluate_condition("foo == 1", CTX)


def test_arithmetic_op_rejected() -> None:
    # We intentionally don't allow + - * / — comparisons only.
    with pytest.raises(ValueError):
        _evaluate_condition("vrp + 1 > 0", CTX)


def test_type_mismatched_compare_raises_typeerror() -> None:
    # A well-formed AST (`level < 1`) but the op blows up at runtime
    # because "LOW" < 1 isn't defined. We assert TypeError here; the
    # endpoint catches it and logs a warning rather than 500'ing.
    with pytest.raises(TypeError):
        _evaluate_condition("level < 1", CTX)
```

Run: `uv run pytest tests/unit/test_guidance_condition_evaluator.py -v` → all PASS, including each escape pattern raising.

- [ ] **Step 4: Write the failing endpoint test**

```python
"""Endpoint contract test for GET /api/regime/guidance."""

from __future__ import annotations

import pytest


@pytest.mark.usefixtures("seeded_cri_snapshot")
def test_guidance_returns_a_rule(client) -> None:
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"]
    assert body["posture"] in {"opportunistic", "neutral", "cautious", "defensive"}
    assert body["body_md"]


@pytest.mark.usefixtures("seeded_cri_snapshot")
def test_guidance_selects_low_contango_for_calm_market(client) -> None:
    resp = client.get("/api/regime/guidance")
    body = resp.json()
    # The seeded snapshot is a calm market (LOW level, VIX/VIX3M < 1)
    assert body["state"] in {"low_contango", "low_neutral"}


# --- Failure-mode tests -----------------------------------------------

def test_guidance_404_when_no_snapshot(client) -> None:
    """Empty cri_snapshots → 404 with actionable message, not silent 500."""
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 404
    assert "snapshot" in resp.json()["detail"]


@pytest.mark.usefixtures("seeded_cri_snapshot")
def test_guidance_500_when_guidance_md_missing(client, monkeypatch, tmp_path) -> None:
    from uw_scan.api.routers import regime_validation
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 500
    assert "guidance.md" in resp.json()["detail"]


@pytest.mark.usefixtures("seeded_cri_snapshot")
def test_guidance_skips_malformed_rule_and_falls_through(
    client, monkeypatch, tmp_path
) -> None:
    """A typo'd condition is skipped (warning logged), not propagated as 500."""
    from uw_scan.api.routers import regime_validation
    (tmp_path / "guidance.md").write_text(
        "---\nstate: bad\ncondition: \"level == NOTAQUOTE\"\nposture: neutral\n---\n"
        "body for bad rule\n"
        "---\nstate: low_neutral\ncondition: \"level == 'LOW'\"\nposture: neutral\n---\n"
        "body for low_neutral\n"
    )
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 200
    assert resp.json()["state"] == "low_neutral"


@pytest.mark.usefixtures("seeded_cri_snapshot_with_missing_vix3m")
def test_guidance_falls_back_to_missing_term_structure(client) -> None:
    """Missing VIX3M must NOT auto-match 'low_contango' (the < 0.95 trap)."""
    resp = client.get("/api/regime/guidance")
    body = resp.json()
    assert body["state"] == "low_missing_term_structure"
    assert body["posture"] == "neutral"
```

The `seeded_cri_snapshot_with_missing_vix3m` fixture writes a CRI snapshot whose `vix_vix3m_ratio` field is `None` (not present in the JSONB payload). Add it to the same `conftest.py` next to `seeded_cri_snapshot`.

The `seeded_cri_snapshot` fixture writes one CRI snapshot row with controllable level + ratio. If a fixture like this doesn't already exist in `tests/integration/api/conftest.py`, add it.

- [ ] **Step 5: Run — confirm pass**

```bash
uv run pytest tests/integration/api/test_regime_guidance_endpoint.py -v
```
Expected: 2 PASS.

- [ ] **Step 6: Regenerate snapshot + types**

Same regen sequence as Task 7 Steps 2 + 4.

- [ ] **Step 7: Commit (milestone)**

```bash
git add docs/research/regime/guidance.md src/uw_scan/api/models/regime_validation.py src/uw_scan/api/routers/regime_validation.py tests/integration/api/test_regime_guidance_endpoint.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(regime): /api/regime/guidance endpoint + markdown-driven rules"
```

---

## Phase 5: UI

### Task 10: Mean-reversion tiles under the CRI hero

**Files:**
- Create: `web/components/regime/MeanReversionTiles.tsx`
- Modify: `web/components/regime/CriSubTab.tsx`
- Test: `web/tests/unit/MeanReversionTiles.test.tsx`

- [ ] **Step 1: Write the component**

Create `web/components/regime/MeanReversionTiles.tsx`:

```tsx
"use client";

import InfoTooltip from "./InfoTooltip";

interface Props {
  vrp: number | null | undefined;
  vixZscore: number | null | undefined;
  vixVix3mRatio: number | null | undefined;
}

const TOOLTIPS = {
  VRP: "Variance Risk Premium (vol-unit form) = VIX − 20d realized vol of SPX. Positive (the modal case): implied > realized; potential vol compression. Negative: realized exceeded implied (post-spike). Academic VRP uses variance units (VIX² − RV²); we surface vol units for readability — same sign, same semantics.",
  "VIX Z (30d)":
    "Today's VIX in standard deviations from the trailing-30d mean. |z| > 2 = stretched (mean-reversion trigger threshold per the rolling-z-score convention).",
  "VIX / VIX3M":
    "Front-end vs 3-month VIX (CBOE term-structure ratio). < 0.85 deep contango; 0.85–0.95 normal contango; 0.95–1.0 warning (curve flattening); 1.0–1.1 backwardation (front-end stress); > 1.1 deep backwardation (panic). Contango dominates ~85% of days; the cross above 1.0 has historically preceded every major drawdown 1990–2025.",
};

function tileColor(label: string, v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  if (label === "VRP") return v > 0 ? "var(--positive)" : "var(--negative)";
  if (label === "VIX Z (30d)") return Math.abs(v) > 2 ? "var(--warning)" : "var(--text-primary)";
  if (label === "VIX / VIX3M") {
    // 4-band per Macrosynergy / VolRadar term-structure convention.
    if (v >= 1.1) return "var(--negative)";  // deep backwardation — panic
    if (v >= 1.0) return "var(--warning)";   // backwardation — stress
    if (v >= 0.95) return "var(--text-primary)";  // flat / warning
    return "var(--positive)";                 // contango
  }
  return "var(--text-primary)";
}

function Tile({ label, value, dec = 2 }: { label: string; value: number | null | undefined; dec?: number }) {
  const display = value != null && Number.isFinite(value) ? value.toFixed(dec) : "—";
  return (
    <div className="regime-tile" data-testid={`meanrev-tile-${label}`}>
      <div className="regime-tile-label">
        {label} <InfoTooltip text={TOOLTIPS[label as keyof typeof TOOLTIPS] ?? ""} />
      </div>
      <div className="regime-tile-value" style={{ color: tileColor(label, value) }}>
        {display}
      </div>
    </div>
  );
}

export function MeanReversionTiles({ vrp, vixZscore, vixVix3mRatio }: Props) {
  return (
    <div className="regime-meanrev-row" data-testid="meanrev-row">
      <Tile label="VRP" value={vrp} />
      <Tile label="VIX Z (30d)" value={vixZscore} />
      <Tile label="VIX / VIX3M" value={vixVix3mRatio} dec={3} />
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `CriSubTab.tsx` + relabel SPY → SPX when SPX is the source**

In `web/components/regime/CriSubTab.tsx`, add the import:

```tsx
import { MeanReversionTiles } from "./MeanReversionTiles";
```

After the existing `<RegimeStrip>...</RegimeStrip>` block (just before the `<div className="regime-detail-grid">`), insert:

```tsx
<MeanReversionTiles
  vrp={data.vrp ?? null}
  vixZscore={data.vix_zscore_30d ?? null}
  vixVix3mRatio={data.vix_vix3m_ratio ?? null}
/>
```

**Also fix the SPY label drift.** The strip cell at `web/components/regime/CriSubTab.tsx:591-600` hard-codes the label `SPY`. After Task 2/3, the `data.spy` field carries an SPX-scale value (4500-ish) when `data.spx_source === "SPX"`, so the existing label would show "$6000" labelled SPY and look broken. Update the label JSX:

```tsx
<RegimeStripCell
  testId="strip-spy"
  label={
    <>
      {data.spx_source === "SPY" ? "SPY" : "SPX"} <LiveBadge live={live} />
    </>
  }
  value={`$${fmt(spy)}`}
  ...
/>
```

Add `spx_source` to the destructured `data` fields at the top of the component (alongside `vrp`, `vix_zscore_30d`, etc.).

**Heads-up for existing tests:** any vitest that asserts on the literal text "SPY" in `CriSubTab` (e.g., `expect(...).toContain("SPY")`) will fail after this change for an SPX-sourced snapshot. Grep before running tests:

```bash
grep -rn '"SPY"\|>SPY<' web/tests/unit/CriSubTab.test.tsx 2>/dev/null
```

If any matches surface, update them to assert on the actual rendered label — either by mocking `data.spx_source` to `"SPY"` (fallback regime) or accepting both `"SPY"` and `"SPX"` depending on the fixture.

- [ ] **Step 3: Add minimal CSS for the tile row**

Append to `web/app/globals.css`:

```css
.regime-meanrev-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}
.regime-tile {
  padding: 8px 12px;
  border: 1px solid var(--border-dim);
  background: var(--bg-panel-raised, var(--bg-panel));
}
.regime-tile-label {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.15em;
  text-transform: uppercase;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.regime-tile-value {
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 600;
  margin-top: 4px;
}
```

- [ ] **Step 4: Write the vitest**

Create `web/tests/unit/MeanReversionTiles.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MeanReversionTiles } from "@/components/regime/MeanReversionTiles";

describe("MeanReversionTiles", () => {
  it("renders three tiles with values", () => {
    render(<MeanReversionTiles vrp={5.2} vixZscore={1.1} vixVix3mRatio={0.92} />);
    expect(screen.getByTestId("meanrev-row")).not.toBeNull();
    expect(screen.getByTestId("meanrev-tile-VRP").textContent).toContain("5.20");
    expect(screen.getByTestId("meanrev-tile-VIX Z (30d)").textContent).toContain("1.10");
    expect(screen.getByTestId("meanrev-tile-VIX / VIX3M").textContent).toContain("0.920");
  });

  it("renders em-dash for null inputs", () => {
    render(<MeanReversionTiles vrp={null} vixZscore={null} vixVix3mRatio={null} />);
    expect(screen.getByTestId("meanrev-tile-VRP").textContent).toContain("—");
  });
});
```

- [ ] **Step 5: Run vitest + typecheck**

```bash
cd web && npm run typecheck && npm run test -- --run MeanReversionTiles
```
Expected: PASS.

- [ ] **Step 6: Commit (milestone)**

```bash
git add web/components/regime/MeanReversionTiles.tsx web/components/regime/CriSubTab.tsx web/app/globals.css web/tests/unit/MeanReversionTiles.test.tsx
git commit -m "feat(regime): mean-reversion tiles (VRP / VIX Z / VIX-VIX3M) under hero"
```

---

### Task 11: Guidance panel below the components

**Files:**
- Create: `web/components/regime/GuidancePanel.tsx`
- Modify: `web/lib/regime/api.ts` (add `guidance()` URL builder)
- Modify: `web/components/regime/CriSubTab.tsx`
- Test: `web/tests/unit/GuidancePanel.test.tsx`

- [ ] **Step 0: Add the URL builder to `web/lib/regime/api.ts`**

The existing `regimeApi` (verified at `web/lib/regime/api.ts:1-13`) emits absolute FastAPI URLs (default `http://127.0.0.1:8400`, overridable via `NEXT_PUBLIC_API_BASE_URL`). A bare `fetch("/api/regime/guidance")` would hit Next.js on port 3001, which has no rewrite, and silently 404. Add the entry alongside `cri`, `vcg`, `gex`:

```ts
  guidance: () => `${API}/api/regime/guidance`,
  validation: () => `${API}/api/regime/validation`,
```

- [ ] **Step 1: Write the component**

Create `web/components/regime/GuidancePanel.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";

type GuidanceResponse = components["schemas"]["GuidanceResponse"];

function postureColor(posture: string): string {
  switch (posture) {
    case "opportunistic": return "var(--positive)";
    case "neutral": return "var(--text-muted)";
    case "cautious": return "var(--warning)";
    case "defensive": return "var(--negative)";
    default: return "var(--text-primary)";
  }
}

export function GuidancePanel() {
  const [guidance, setGuidance] = useState<GuidanceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(regimeApi.guidance())
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => { if (!cancelled) setGuidance(data); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, []);

  if (error) return null; // Stay quiet on failure — page is still useful.
  if (!guidance) return null;

  return (
    <div className="regime-guidance-panel" data-testid="guidance-panel">
      <div className="regime-guidance-header">
        <span className="regime-guidance-state">{guidance.state.replace(/_/g, " ").toUpperCase()}</span>
        <span
          className="regime-guidance-posture"
          style={{ color: postureColor(guidance.posture) }}
          data-testid="guidance-posture"
        >
          {guidance.posture.toUpperCase()}
        </span>
      </div>
      <div
        className="regime-guidance-body"
        // Body is markdown from a checked-in file — render as preformatted
        // text rather than dangerouslySetInnerHTML. Bold/italic won't render
        // but the prose is short and that's an acceptable V1 trade.
      >
        {guidance.body_md}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire it into `CriSubTab.tsx`**

After the `<div className="regime-detail-grid">...</div>` block (which contains components + crash trigger), add:

```tsx
<GuidancePanel />
```

- [ ] **Step 3: Add CSS**

Append to `web/app/globals.css`:

```css
.regime-guidance-panel {
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--border-dim);
  background: var(--bg-panel);
}
.regime-guidance-header {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}
.regime-guidance-state {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.15em;
  color: var(--text-muted);
}
.regime-guidance-posture {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.15em;
}
.regime-guidance-body {
  font-size: 13px;
  line-height: 1.5;
  color: var(--text-primary);
  white-space: pre-wrap;
}
```

- [ ] **Step 4: Vitest**

Create `web/tests/unit/GuidancePanel.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GuidancePanel } from "@/components/regime/GuidancePanel";

const FAKE = {
  state: "low_contango",
  posture: "opportunistic",
  body_md: "**LOW + contango.** Vol is cheap.",
  matched_condition: "level == LOW and vix_vix3m_ratio < 0.95",
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => FAKE })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("GuidancePanel", () => {
  it("renders the active rule's state and posture", async () => {
    render(<GuidancePanel />);
    await waitFor(() => expect(screen.getByTestId("guidance-panel")).not.toBeNull());
    expect(screen.getByTestId("guidance-posture").textContent).toBe("OPPORTUNISTIC");
  });

  it("stays silent on fetch failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 500 })));
    const { container } = render(<GuidancePanel />);
    await new Promise((r) => setTimeout(r, 50));
    expect(container.querySelector('[data-testid="guidance-panel"]')).toBeNull();
  });
});
```

- [ ] **Step 5: Run vitest + typecheck**

```bash
cd web && npm run typecheck && npm run test -- --run GuidancePanel
```
Expected: PASS.

- [ ] **Step 6: Commit (milestone)**

```bash
git add web/components/regime/GuidancePanel.tsx web/components/regime/CriSubTab.tsx web/app/globals.css web/tests/unit/GuidancePanel.test.tsx
git commit -m "feat(regime): guidance panel driven by /api/regime/guidance"
```

---

### Task 12: Validation sub-tab on `/regime`

**Files:**
- Create: `web/components/regime/ValidationTab.tsx`
- Modify: `web/components/regime/RegimePanel.tsx` (the `TABS` array at lines 11–15 and the conditional render block at lines 39–41 — verified at plan-write time)
- Test: `web/tests/unit/ValidationTab.test.tsx`

**Design choice — sub-tab vs route.** The existing CRI/GEX/VCG sub-tabs live inside `RegimePanel.tsx` and switch via local React state — *not* nested Next.js routes. To stay consistent with the existing UX (single `/regime` URL, sub-tabs swap content without a route change), add Validation as a fourth in-panel tab rather than a `/regime/validation` route. If the user prefers a deep-linkable URL later, we can promote it then.

- [ ] **Step 1: Confirm the current sub-tab shape (sanity check; should already match the plan)**

```bash
sed -n '9,42p' web/components/regime/RegimePanel.tsx
```
Expected: `type RegimeTab = "cri" | "vcg" | "gex"`, the `TABS` array, and three conditional `<XxxSubTab />` renders. If the shape has changed since the plan was written, adjust Steps 2 & 4 accordingly.

- [ ] **Step 2: Build the client component**

Create `web/components/regime/ValidationTab.tsx`. Use a default export to match the convention of the other sub-tabs (`CriSubTab`, `GexSubTab`, `VcgSubTab` — all default exports per `RegimePanel.tsx:5-7`):

```tsx
"use client";

import { useEffect, useState } from "react";
import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";

type ValidationResponse = components["schemas"]["ValidationResponse"];

export default function ValidationTab() {
  const [data, setData] = useState<ValidationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(regimeApi.validation())
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    return () => { cancelled = true; };
  }, []);

  if (error) return <div className="regime-panel">Validation data unavailable: {error}</div>;
  if (!data) return <div className="regime-panel">Loading…</div>;

  return (
    <div className="regime-panel" data-testid="validation-tab">
      <div className="regime-panel-title">WARM-STORE BACKTEST</div>
      <pre
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: "12px",
          whiteSpace: "pre-wrap",
          color: "var(--text-primary)",
        }}
      >
        {data.backtest_md}
      </pre>
      <div className="regime-panel-title" style={{ marginTop: 16 }}>
        OUT-OF-SAMPLE VALIDATION
      </div>
      {data.oos ? (
        <div data-testid="oos-block">
          <p style={{ fontSize: 13 }}>
            <strong>Method:</strong> {data.oos.method}
          </p>
          <p style={{ fontSize: 13 }}>
            <strong>As of:</strong> {data.oos.as_of}
          </p>
          <table className="gex-history-table" style={{ marginTop: 8 }}>
            <thead>
              <tr>
                <th className="text-left">Model</th>
                <th className="text-right">AUC (dd5)</th>
                <th className="text-right">AUC (vix30)</th>
                <th className="text-right">AUC (dd10)</th>
              </tr>
            </thead>
            <tbody>
              {data.oos.scores.map((s) => (
                <tr key={s.model}>
                  <td>{s.model}</td>
                  <td className="text-right">{s.auc_dd5 != null ? s.auc_dd5.toFixed(3) : "—"}</td>
                  <td className="text-right">{s.auc_vix30 != null ? s.auc_vix30.toFixed(3) : "—"}</td>
                  <td className="text-right">{s.auc_dd10 != null ? s.auc_dd10.toFixed(3) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p
            style={{
              fontSize: 13,
              marginTop: 12,
              padding: 8,
              borderLeft: "2px solid var(--text-muted)",
              color: "var(--text-secondary)",
            }}
          >
            {data.oos.interpretation}
          </p>
        </div>
      ) : (
        <p>OOS summary not available.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Wire ValidationTab into `RegimePanel.tsx`**

Edit `web/components/regime/RegimePanel.tsx` three places:

1. Add the import:
```tsx
import ValidationTab from "./ValidationTab";
```

2. Extend the union and the `TABS` array (lines 9 + 11–15):
```tsx
type RegimeTab = "cri" | "vcg" | "gex" | "validation";

const TABS: { id: RegimeTab; label: string }[] = [
  { id: "gex", label: "GEX" },
  { id: "cri", label: "CRI" },
  { id: "vcg", label: "VCG" },
  { id: "validation", label: "VALIDATION" },
];
```

3. Add the conditional render alongside the existing three (after line 41):
```tsx
{activeTab === "validation" && <ValidationTab />}
```

`ValidationTab` is a default export (per Step 2), matching the existing sub-tabs.

- [ ] **Step 4: Vitest**

Create `web/tests/unit/ValidationTab.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ValidationTab from "@/components/regime/ValidationTab";

const FAKE = {
  backtest_md: "# CRI Backtest\nMean: 8.5",
  backtest_csv_rows: 124,
  oos: {
    as_of: "2026-05-19",
    notebook: "...",
    method: "walk-forward",
    labels: [],
    scores: [
      { model: "CRI v2", auc_dd5: 0.621, auc_vix30: null, auc_dd10: null },
      { model: "Naive VIX p80", auc_dd5: 0.637, auc_vix30: null, auc_dd10: null },
    ],
    interpretation: "VIX alone captures most of the signal.",
  },
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => FAKE })));
});

afterEach(() => vi.unstubAllGlobals());

describe("ValidationTab", () => {
  it("renders the backtest md + OOS table", async () => {
    render(<ValidationTab />);
    await waitFor(() => expect(screen.getByTestId("validation-tab")).not.toBeNull());
    expect(screen.getByText("WARM-STORE BACKTEST")).not.toBeNull();
    expect(screen.getByTestId("oos-block")).not.toBeNull();
    expect(screen.getByText("CRI v2")).not.toBeNull();
    expect(screen.getByText("0.621")).not.toBeNull();
  });
});
```

- [ ] **Step 5: Run vitest + typecheck + lint**

```bash
cd web && npm run typecheck && npm run test -- --run ValidationTab
```

- [ ] **Step 6: Commit (milestone)**

```bash
git add web/components/regime/ValidationTab.tsx web/components/regime/RegimePanel.tsx web/tests/unit/ValidationTab.test.tsx
git commit -m "feat(regime): Validation sub-tab rendering backtest + OOS summary"
```

---

## Phase 6: End-to-end verification

### Task 13: Manual browser walk-through

**Files:**
- None (verification only)

- [ ] **Step 1: Full test suite**

```bash
uv run pytest
cd web && npm run typecheck && npm run test
```
Expected: all PASS (frontend lint may still report the same pre-existing `react-hooks/rules-of-hooks` warning from the previous PR — that's not a regression).

- [ ] **Step 2: Re-run the scanner once with the new code**

```bash
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.scanners.cri import run
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    rid = run(conn, schema=s.db_schema)
    conn.commit()
    print('row_id:', rid)
"
```

- [ ] **Step 3: Inspect the live payload**

```bash
curl -s http://localhost:8400/api/regime/cri | python -m json.tool | grep -E "vrp|vix_zscore|vix_vix3m_ratio|vix3m|spx_source"
curl -s http://localhost:8400/api/regime/validation | python -m json.tool | head -20
curl -s http://localhost:8400/api/regime/guidance | python -m json.tool
```
Expected: all three endpoints respond; mean-reversion fields populated; guidance picks a `low_*` rule for today's calm market.

- [ ] **Step 4: Browser checks on `http://localhost:3001/regime`**

- [ ] Three mean-reversion tiles render under the hero (VRP / VIX Z / VIX / VIX3M)
- [ ] Guidance panel appears under the components with state label + colored posture badge + prose
- [ ] Tooltip on each tile says the right thing
- [ ] Click the "VALIDATION" sub-tab on `/regime` — backtest markdown + OOS table render
- [ ] Hero CRI score is within a few points of the pre-PR snapshot. A band change (LOW → ELEVATED) on the same trading day is a red flag and warrants comparing component-by-component before merging.

- [ ] **Step 5: Verify SPX is now actually the source**

```bash
curl -s http://localhost:8400/api/regime/cri | python -c "import sys, json; d=json.load(sys.stdin); print('spx_source:', d.get('spx_source'))"
```
Expected: `SPX`.

---

## Phase 7: Open the PR

### Task 14: Push + PR

- [ ] **Step 1: Push**

```bash
git push -u origin feat/cri-methodology-tune
```

- [ ] **Step 2: Open PR (bundled with the previous methodology-tune work)**

```bash
gh pr create --title "feat(regime): CRI methodology tune + SPX backfill + validation + signals + guidance" --body "$(cat <<'EOF'
## Summary

One bundled PR covering all CRI work from the past two sessions.

**Part 1 — methodology tune (earlier commits on the branch):**
- VVIX scoring re-calibration (floor 85, ceiling 130, level/ratio/RoC = 12/7/6)
- New API fields: `vvix_5d_roc`, `cor1m_5d_change`
- UI: reference markers + prior-day dots on each component bar; "Momentum" → "Trend Break"
- Methodology source-of-truth doc + warm-store backtest script + OOS validation notebook

**Part 2 — page enrichment (this plan):**

1. **SPX backfill** — scanner + backtest now read SPX from `vol_index_daily` (12,953 rows from 1975) instead of SPY from `daily_ohlc` (was ~6 months only). `spx_source: "SPX"|"SPY"` field flags which series fed the snapshot. SPY fallback preserved.
2. **Validation sub-tab** — fourth in-panel sub-tab on `/regime` (alongside GEX/CRI/VCG); renders `cri-backtest.md` + a hand-curated OOS summary table (`oos-summary.json`) extracted from `cri-validation.ipynb` Section 9. Updateable without code by re-running the notebook and editing the JSON.
3. **Mean-reversion tiles** — three tiles under the CRI hero: VRP (IV−RV), VIX z-score vs trailing 30d, and VIX/VIX3M term-structure ratio.
4. **Regime guidance panel** — markdown-driven rules in `docs/research/regime/guidance.md` selected by `/api/regime/guidance` based on the current snapshot. Six initial states (LOW/ELEVATED × contango/backwardation/etc.) with posture badges. Editorial copy lives in a config file so non-engineers can iterate.

## Test plan

- [ ] `uv run pytest` — all green
- [ ] `cd web && npm run typecheck && npm run test` — all green
- [ ] `curl http://localhost:8400/api/regime/cri | grep spx_source` returns `SPX`
- [ ] Manual: `/regime` CRI tab shows three tiles + guidance panel; clicking the new VALIDATION tab renders backtest + OOS table
- [ ] Backtest report (`docs/research/regime/cri-backtest.md`) now spans 2006→today (not 6 months)

## Notes for reviewers

- **Guidance condition evaluator is a hand-rolled AST whitelist**, not `eval` (see `src/uw_scan/api/routers/regime_validation.py`). The whitelist permits only `Expression`/`Compare`/`BoolOp`/`UnaryOp`/`Name`/`Constant` nodes and `== != < <= > >= and or not` operators — every common eval-sandbox-escape pattern (`().__class__.__bases__`, attribute access, function calls, subscripting, imports) raises `ValueError`. Security boundary tested in `tests/unit/test_guidance_condition_evaluator.py`.
- **VRP is the vol-unit form** (VIX − 20d realized vol). The academic variance-unit form (Bollerslev/Tauchen/Zhou 2009 RFS 22(11)) is documented as an alternative in the module docstring; we chose vol-units for readability on the tile. Same sign, similar semantics.
- **VIX3M data dependency** — first deploy needs the manual `vol_index_lake_sync` kick from Phase 1 Task 1. Without it, the term-structure tile renders `—` (NaN propagates cleanly through the helpers).
- Pre-existing `react-hooks/rules-of-hooks` warning in `CriSubTab.tsx` remains; not a regression from this PR (see prior PR notes).
EOF
)"
```

- [ ] **Step 3: Verify CI runs and address any failures inline**

---

## Summary of deliverables

| Deliverable | Path |
|---|---|
| OOS snapshot (hand-curated) | `docs/research/regime/oos-summary.json` |
| Regime guidance config | `docs/research/regime/guidance.md` |
| Updated methodology doc | `docs/research/regime/cri-methodology.md` |
| Regenerated backtest (SPX) | `docs/research/regime/cri-backtest.{md,csv}` |
| Mean-reversion helpers | `src/uw_scan/cards/mean_reversion.py` |
| Scoring updates | `src/uw_scan/cards/cri_scoring.py`, `src/uw_scan/scanners/cri.py` |
| API contract | `src/uw_scan/api/schemas.py`, `models/regime_validation.py` |
| API endpoints | `src/uw_scan/api/routers/regime_validation.py` |
| OpenAPI snapshot + types | `tests/integration/api/openapi.snapshot.json`, `web/lib/types.ts` |
| UI: tiles | `web/components/regime/MeanReversionTiles.tsx` |
| UI: guidance | `web/components/regime/GuidancePanel.tsx` |
| UI: validation sub-tab | `web/components/regime/ValidationTab.tsx`, `web/components/regime/RegimePanel.tsx` |
| Python tests | `tests/unit/test_mean_reversion.py`, `tests/integration/api/test_regime_validation_endpoint.py`, `tests/integration/api/test_regime_guidance_endpoint.py` |
| Web tests | `web/tests/unit/{MeanReversionTiles,GuidancePanel,ValidationTab}.test.tsx` |
