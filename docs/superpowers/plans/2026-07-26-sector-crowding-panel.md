# Sector Crowding Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a ranked sector-crowding panel to the `/regime` Market Tide tab that scores ~14 sector ETFs on three conjunctive legs (relative return, fund flow intensity, option-premium richness) and drills down into a two-panel SVG chart for the selected ETF.

**Architecture:** A nightly worker job extends the existing UW `/api/etfs/{t}/in-outflow` capture (already built for gold) to the sector-ETF universe, writing into the existing `uw_scan.etf_flows_daily` table. A pure report module computes the crowding score at API read time from that table plus `etf_aum_cache` and `watchlist_card`. No new tables, no new migrations. A blocking prerequisite is normalizing the mixed-unit `aum` values, or the flow leg is wrong by 1e9 for the 12 SPDR sector ETFs.

**Tech Stack:** Python 3.13 via `uv`, FastAPI + Pydantic v2, psycopg 3, APScheduler 3, Next.js 16 + React 19, hand-rolled SVG, pytest, vitest.

## Source

Framework adapted from https://x.com/bitfool1/status/2079479920162734401 (板块拥挤度, 2026-07-21). Legs 1 and 2 are the tweet's; leg 3 substitutes IV-rank spread for the tweet's NTM P/E, which has no data source on our UW/massive tier.

## Global Constants

Copy these exact values; every task depends on them.

```python
RETURN_WINDOW = 63          # OBSERVATIONS, ~3 months where UW coverage is
                            # complete; ~4.5 months for SOXX/IGV, which are
                            # missing sessions. See the research note.
FLOW_WINDOW = 21            # trading days ~= 1 month
MIN_SESSIONS = 84           # RETURN_WINDOW + FLOW_WINDOW; below this, no raw values
MIN_HISTORY_POINTS = 60     # below this, leg 1 percentile is None
LOOKBACK_DAYS = 400         # calendar days requested from UW per ticker
AUM_BILLIONS_THRESHOLD = 1e6

BENCHMARK = "SPY"
SECTOR_CROWDING_TICKERS = (
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP",
    "XLRE", "XLU", "XLV", "XLY", "SOXX", "SMH", "IGV",
)

FLOW_BREAKPOINTS = (
    (-5.0, 0.0), (0.0, 20.0), (2.0, 40.0),
    (5.0, 70.0), (10.0, 90.0), (25.0, 100.0),
)
IVR_SPREAD_CAP = 60.0

BAND_CROWDED = 75.0
BAND_WARM = 50.0
BAND_NORMAL = 25.0
```

Band names are exactly `"CROWDED" | "WARM" | "NORMAL" | "COLD"`. Leg names are exactly `"price" | "flow" | "premium"`.

## Global Constraints

- **uv only.** Every Python command is `uv run …`. Never bare `pytest`/`python`/`pip`.
- **Line length 88** (ruff default; there is no ruff config in `pyproject.toml`).
- **No new tables, no new migrations.** If a task seems to need one, stop and re-read the plan.
- **Read-time compute is deliberate and does not breach "persist analytical results to Postgres."** That rule exists so a result cannot evaporate with the process. Here every *input* is persisted — `etf_flows_daily` (this plan's new capture job), `etf_aum_cache`, `watchlist_card` — and the score is a pure, deterministic function of them, so any past day's ranking is reproducible from the warm store. Nothing is stdout-only. If the score ever gains state the inputs do not carry (a hysteresis band, a decay, a hand override), that reasoning collapses and it needs its own table.
- **No Yahoo.** Enforced in CI by `scripts/check_no_yahoo.py`.
- **Hand-rolled SVG only** on the web side, using `web/lib/svgChart.ts`. Do not add a chart library.
- **`web/lib/types.ts` and `tests/integration/api/openapi.snapshot.json` are frozen in an older generated format.** Never run a full regen (no `npm run gen:types`) — the recipes are Task 5 Step 6 for the OpenAPI snapshot and Task 6 Step 5 for `types.ts`.
- **Never commit without the user asking.** A plan cannot authorize its own commits. Each task ends with a commit step because `CLAUDE.md` asks for milestone commits on large tasks — but they only run if the user has said to commit. If they have not, do the `git add` and stop there. Pushing or opening a PR always needs a separate explicit request.
- **CHANGELOG rides this branch** (Task 7), not a follow-up PR.

## Setup

- [ ] **Create the worktree**

```bash
cd /Users/chenxi/projects/argon
git worktree add .worktrees/sector-crowding -b feat/sector-crowding main
cp docs/superpowers/plans/2026-07-26-sector-crowding-panel.md \
   .worktrees/sector-crowding/docs/superpowers/plans/
cd .worktrees/sector-crowding
uv sync --extra postgres
```

The `cp` is load-bearing. This plan is **untracked** in `main`, so `git worktree add` — which checks out `main`'s commit — produces a worktree that does not contain it. Without the copy the executing agent lands in a directory with no plan to execute, and Task 7's `git add docs/superpowers/plans/…` has nothing to stage.

The web side needs a real install, not a symlink — Turbopack panics on a symlinked `web/node_modules`:

```bash
cd web && npm ci && cd ..
```

## File Structure

| File | Responsibility |
|---|---|
| `src/uw_scan/storage/market_data.py` (modify) | `normalize_etf_aum()` + apply it at the `etf_aum_cache` read/write chokepoints |
| `src/uw_scan/pipeline.py` (modify) | Normalize `_get_or_fetch_etf_aum`'s cache-miss return so it matches the cache-hit return |
| `src/uw_scan/reports/sector_crowding.py` (create) | Pure scoring: leg mappers, percentile, bands, min-band state, assembly from repo rows |
| `src/uw_scan/storage/watchlist.py` (modify) | `fetch_iv_ranks()` — one bulk query over `watchlist_card` |
| `src/uw_scan/worker/jobs/sector_crowding_capture.py` (create) | Nightly UW in-outflow + AUM capture for the sector universe |
| `src/uw_scan/worker/scheduler.py` (modify) | Job wrapper + cron registration under the `uw` group |
| `src/uw_scan/reports/data_freshness.py` (modify) | Widen the `etf_flows_daily` monitored subset so a silent capture freeze is caught |
| `src/uw_scan/api/models/sector_crowding.py` (create) | Pydantic response contract |
| `src/uw_scan/api/routers/regime.py` (modify) | `GET /api/regime/sector-crowding` |
| `web/lib/regime/api.ts` (modify) | Endpoint URL |
| `web/lib/regime/useSectorCrowding.ts` (create) | Polling hook |
| `web/components/regime/SectorCrowdingPanel.tsx` (create) | Ranked table + expand-on-click |
| `web/components/regime/SectorCrowdingCharts.tsx` (create) | Two hand-rolled SVG drill-down panels |
| `web/components/regime/MarketTideSubTab.tsx` (modify) | Mount the panel |
| `docs/research/2026-07-26-sector-crowding-probe.md` (create) | Research trace + reproduce command |
| `scripts/research/sector_crowding_probe.py` (create) | The probe script itself |

---

### Task 1: Normalize the mixed-unit ETF AUM

UW returns `aum` in **billions** for the 12 SPDR sector ETFs (`XLK` → `180.775642`) and in **raw dollars** for everything else (`SOXX` → `45064294868`). Both land unconverted in `uw_scan.etf_aum_cache`, and leg 2 divides 1M net flow by that number — so for the 12 SPDRs the ratio comes out 1e9 too small. Fix it before anything reads it.

**Scope, stated precisely.** This task fixes `etf_aum_cache` (the crowding divisor) and the value `pipeline._get_or_fetch_etf_aum` hands back. It does **not** fix the watchlist card sort. The card's `aum` comes from `COALESCE(sr.aggregates->>'aum', lea.aum)` (`storage/watchlist.py:366` / `:478`) — `scan_runs.aggregates` first, then a lateral over the raw `etf_info` payload in `raw_payloads` (`:392-403` / `:506-516`). Neither touches `etf_aum_cache`, so `web/components/watchlist/CardGrid.tsx sizeValue()` still sorts the SPDRs as ~$180 companies against stock `market_cap` in dollars. That is a real, separate bug in a different read path; fixing it means normalizing at the `MarketAggregates`/payload boundary and is explicitly out of scope here. Do not claim it in the commit message.

**Files:**
- Modify: `src/uw_scan/storage/market_data.py:202-229`
- Test: `tests/unit/test_etf_aum_normalization.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `normalize_etf_aum(raw: Decimal | float | None) -> Decimal | None`, importable as
  `from uw_scan.storage.market_data import normalize_etf_aum`. Idempotent.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_etf_aum_normalization.py`:

```python
"""AUM unit normalization.

UW returns `aum` in billions for the 12 SPDR sector ETFs and in raw dollars for
everything else. Real values below are frozen from a live UW probe on
2026-07-24 (docs/research/2026-07-26-sector-crowding-probe.md).
"""

from decimal import Decimal

import pytest

from uw_scan.storage.market_data import normalize_etf_aum


def test_billions_scaled_to_dollars():
    # XLK, live UW /api/etfs/XLK/info on 2026-07-24 -> 180.775642 (billions)
    assert normalize_etf_aum(Decimal("180.775642")) == Decimal("180775642000")


def test_raw_dollars_passed_through():
    # SOXX, same probe -> already raw dollars
    assert normalize_etf_aum(Decimal("45064294868")) == Decimal("45064294868")


def test_idempotent():
    once = normalize_etf_aum(Decimal("180.775642"))
    assert normalize_etf_aum(once) == once


def test_none_passes_through():
    assert normalize_etf_aum(None) is None


@pytest.mark.parametrize(
    "raw,expected",
    [
        (Decimal("743.252024"), Decimal("743252024000")),   # SPY, billions
        (Decimal("465904858198"), Decimal("465904858198")),  # QQQ, dollars
        (Decimal("11700000000"), Decimal("11700000000")),    # IGV, dollars
    ],
)
def test_probe_universe(raw, expected):
    assert normalize_etf_aum(raw) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_etf_aum_normalization.py -v`
Expected: FAIL with `ImportError: cannot import name 'normalize_etf_aum'`

- [ ] **Step 3: Add the normalizer**

In `src/uw_scan/storage/market_data.py`, add at module level (after the imports, before the mixin class):

```python
# UW's /api/etfs/{ticker}/info returns `aum` in BILLIONS for the 12 SPDR sector
# ETFs (XLK -> 180.775642) and in RAW DOLLARS for everything else
# (SOXX -> 45064294868). Both used to land unconverted in etf_aum_cache, making
# any flow/AUM ratio wrong by 1e9 for the SPDRs. The watchlist card reads its
# `aum` from scan_runs.aggregates / the raw etf_info payload, NOT from this
# cache -- that path is still unnormalized and is not fixed here.
#
# ponytail: a genuine sub-$1M-AUM ETF would be mis-scaled by this heuristic.
# None exist in SECTOR_CROWDING_TICKERS (funds that small get liquidated), and
# the real gap is enormous -- largest billions value seen is SPY at 743, the
# smallest dollar value is IGV at 1.4e10. If UW ever publishes a unit field,
# switch to it and delete this.
AUM_BILLIONS_THRESHOLD = Decimal("1e6")


def normalize_etf_aum(raw: Decimal | float | int | None) -> Decimal | None:
    """Coerce UW's mixed-unit ETF AUM to raw dollars. Idempotent."""
    if raw is None:
        return None
    value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    if value <= 0:
        return value
    return value * Decimal("1e9") if value < AUM_BILLIONS_THRESHOLD else value
```

Confirm `Decimal` is already imported in that file; if not, add `from decimal import Decimal`.

- [ ] **Step 4: Apply it at both cache boundaries**

Normalizing on **read as well as write** makes the ~11 already-corrupt rows correct immediately, with no backfill script and no migration — the function is idempotent, so a row written pre-fix and a row written post-fix both come out right.

In `src/uw_scan/storage/market_data.py`, change the return of `get_recent_etf_aum` (currently `return row[0] if row else None`) to:

```python
        return normalize_etf_aum(row[0]) if row else None
```

and change the body of `upsert_etf_aum` to normalize before writing. Replace `(ticker, aum),` in its `cur.execute` call with:

```python
                (ticker, normalize_etf_aum(aum)),
```

- [ ] **Step 5: Close the cache-miss leak in the pipeline**

`pipeline._get_or_fetch_etf_aum` (`src/uw_scan/pipeline.py:76-102`) returns the **cache** value on a hit and the **raw UW** value on a miss. After Step 4 the hit path is normalized and the miss path is not, so the same ticker would return `180775642000` or `180.775642` depending only on cache age. Normalize the miss path too.

In `src/uw_scan/pipeline.py`, add to the import block:

```python
from uw_scan.storage.market_data import normalize_etf_aum
```

and change the tail of `_get_or_fetch_etf_aum` (currently `return aum`) to:

```python
    aum = etf_info.aum
    if aum is not None:
        repo.upsert_etf_aum(ticker, aum)
    # upsert_etf_aum normalizes on write; normalize here too so the cache-miss
    # return matches the cache-hit return. Idempotent, so double-calling is safe.
    return normalize_etf_aum(aum)
```

- [ ] **Step 6: Repair the three existing assertions this breaks**

Three existing tests hardcode toy AUM values below `AUM_BILLIONS_THRESHOLD`, so Step 4 multiplies them by 1e9 and the equality assertions fail. This is the fix working as designed, not a regression — but the plan is not done until they are green. Exactly three assertions break (the other two `etf_aum` tests already use `Decimal("500000000000")`, which is above the threshold and passes through untouched):

In `tests/integration/storage/test_repository_etf_aum.py`, replace `test_upsert_etf_aum_updates_fetched_at_and_value` and `test_etf_aum_cache_normalizes_case` with:

```python
def test_upsert_etf_aum_updates_fetched_at_and_value(repo: Repository) -> None:
    """A second upsert must bump fetched_at AND overwrite aum.

    Both values are real UW AUMs frozen from the 2026-07-24 probe, in UW's
    billions form: XLK 180.775642 then SPY 743.252024. Writing SPY's number
    into XLK's row is deliberate — this test exercises overwrite mechanics,
    not fund size — and both land normalized to raw dollars.
    """
    repo.upsert_etf_aum("XLK", Decimal("180.775642"))
    repo.upsert_etf_aum("XLK", Decimal("743.252024"))
    cached = repo.get_recent_etf_aum("XLK", max_age=timedelta(days=7))
    assert cached == Decimal("743252024000")


def test_etf_aum_cache_normalizes_case(repo: Repository) -> None:
    """Codex review ISSUE-8: mixed-case input must hit the same logical row.

    SOXX's real 2026-07-24 AUM is already raw dollars and above
    AUM_BILLIONS_THRESHOLD, so the normalizer passes it through and this test
    stays about case folding only.
    """
    repo.upsert_etf_aum("soxx", Decimal("45064294868"))  # lowercase upsert
    cached = repo.get_recent_etf_aum("SOXX", max_age=timedelta(days=7))
    assert cached == Decimal("45064294868")
```

In `tests/integration/test_pipeline_etf_caching.py::test_get_or_fetch_etf_aum_fetches_and_upserts_on_miss`, replace the three `Decimal("123")` occurrences (the stub's return on line 59 and the assertions on lines 64, 69, 75) with QQQ's real raw-dollar AUM from the same probe:

```python
    def _fake_fetch(*args: Any, **kwargs: Any) -> _StubEtfInfo:
        call_count["n"] += 1
        return _StubEtfInfo(aum=Decimal("465904858198"))  # QQQ, 2026-07-24 probe
```

and every `assert … == Decimal("123")` in that test becomes `assert … == Decimal("465904858198")`.

- [ ] **Step 7: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_etf_aum_normalization.py -v
uv run pytest tests/integration/storage/test_repository_etf_aum.py \
              tests/integration/test_pipeline_etf_caching.py -v
uv run ruff check src/uw_scan/storage/market_data.py src/uw_scan/pipeline.py
```
Expected: 7 passed on the unit file, 9 passed across the two integration files, ruff clean.

- [ ] **Step 8: Commit**

```bash
git add tests/unit/test_etf_aum_normalization.py \
        tests/integration/storage/test_repository_etf_aum.py \
        tests/integration/test_pipeline_etf_caching.py \
        src/uw_scan/storage/market_data.py src/uw_scan/pipeline.py
git commit -m "fix(etf): normalize mixed-unit UW AUM to raw dollars

UW returns aum in billions for the 12 SPDR sector ETFs and raw dollars
for everything else. Both landed unconverted in etf_aum_cache, making
any flow/AUM ratio 1e9 too small for the SPDRs. Normalizing on read as
well as write repairs the existing rows without a backfill; the pipeline
cache-miss path normalizes too so hit and miss agree.

The watchlist card sort reads aum from scan_runs.aggregates / the raw
etf_info payload, not from this cache — that path is still unnormalized
and is out of scope here."
```

---

### Task 2: Pure crowding scoring functions

**Files:**
- Create: `src/uw_scan/reports/sector_crowding.py`
- Test: `tests/unit/reports/test_sector_crowding_scoring.py`

**Interfaces:**
- Consumes: `normalize_etf_aum` from Task 1 (imported but not exercised until Task 3).
- Produces, all importable from `uw_scan.reports.sector_crowding`:
  - the Global Constants block above, as module-level names
  - `pct_rank(history: Sequence[float], value: float) -> float | None`
  - `flow_score(flow_aum_pct: float) -> float`
  - `premium_score(ivr_spread: float) -> float`
  - `band_of(score: float | None) -> str | None`
  - `CrowdingLeg` frozen dataclass: `name: str`, `raw: float | None`, `score: float | None`, `band: str | None`
  - `combine(legs: Sequence[CrowdingLeg]) -> tuple[float | None, str | None, str | None]`
    returning `(score, state, binding_leg)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/reports/test_sector_crowding_scoring.py`:

```python
"""Crowding leg mappers and the min-band state rule.

Raw inputs are frozen from a live UW probe on 2026-07-24 plus warm-store
iv_rank on 2026-07-25. Reproduce with
`uv run python scripts/research/sector_crowding_probe.py`; full trace in
docs/research/2026-07-26-sector-crowding-probe.md.
"""

import pytest

from uw_scan.reports.sector_crowding import (
    CrowdingLeg,
    band_of,
    combine,
    flow_score,
    pct_rank,
    premium_score,
)


def test_pct_rank_counts_strictly_below():
    assert pct_rank([1.0, 2.0, 3.0, 4.0], 3.5) == 75.0
    assert pct_rank([1.0, 2.0, 3.0, 4.0], 0.5) == 0.0


def test_pct_rank_empty_history_is_none():
    assert pct_rank([], 1.0) is None


@pytest.mark.parametrize(
    "flow_aum_pct,expected",
    [
        (21.46, 97.64),  # SOXX -- interpolated between 10%->90 and 25%->100
        (4.98, 69.8),    # XLF  -- interpolated between 2%->40 and 5%->70
        (1.91, 39.1),    # SMH  -- between 0%->20 and 2%->40
        (0.28, 22.8),    # XLK  -- same segment, near the bottom
        (-8.27, 0.0),    # IGV  -- heavy outflow, clamps at the floor
        (30.0, 100.0),   # past the 25% breakpoint, clamps (boundary, not a
                         # ticker observation -- nothing in the universe is
                         # there today and the ceiling still needs a test)
    ],
)
def test_flow_score_uses_tweet_breakpoints(flow_aum_pct, expected):
    assert flow_score(flow_aum_pct) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize(
    "spread,expected",
    [
        (64.23, 100.0),  # SOXX 93.93 - SPY 29.70, clamps at the 60pt cap
        (56.75, 94.58),  # XLK  86.45 - SPY 29.70
        (0.0, 0.0),
        (-10.0, 0.0),    # below the benchmark is not crowding
    ],
)
def test_premium_score_caps_at_60_points(spread, expected):
    assert premium_score(spread) == pytest.approx(expected, abs=0.05)


@pytest.mark.parametrize(
    "score,band",
    [(100.0, "CROWDED"), (75.0, "CROWDED"), (74.9, "WARM"),
     (50.0, "WARM"), (49.9, "NORMAL"), (25.0, "NORMAL"),
     (24.9, "COLD"), (0.0, "COLD"), (None, None)],
)
def test_band_of(score, band):
    assert band_of(score) == band


def test_soxx_all_legs_fire_so_state_is_crowded():
    """Real SOXX legs, 2026-07-24 probe, date-joined against SPY."""
    legs = [
        CrowdingLeg("price", 53.69, 97.0, "CROWDED"),
        CrowdingLeg("flow", 21.46, 97.64, "CROWDED"),
        CrowdingLeg("premium", 64.23, 100.0, "CROWDED"),
    ]
    score, state, binding = combine(legs)
    assert score == pytest.approx(98.21, abs=0.01)
    assert state == "CROWDED"
    assert binding == "price"  # the lowest-scoring leg inside the weakest band


def test_smh_is_demoted_by_its_two_normal_legs():
    """SMH's +17.88% is the second-loudest spread on the table and still not
    crowded: it is only its own 46th percentile, and its 1M flow is a modest
    1.91% of AUM. Only the premium leg is hot. The min-band rule is what stops
    that one extreme leg from manufacturing a CROWDED badge -- the tweet's
    conjunctive requirement, 三者同时出现，才算真正拥挤.

    Real SMH legs, 2026-07-24 probe, date-joined against SPY.
    """
    legs = [
        CrowdingLeg("price", 17.88, 46.0, "NORMAL"),
        CrowdingLeg("flow", 1.91, 39.1, "NORMAL"),
        CrowdingLeg("premium", 63.48, 100.0, "CROWDED"),
    ]
    score, state, binding = combine(legs)
    assert score == pytest.approx(61.70, abs=0.01)
    assert state == "NORMAL"
    # Weakest band is NORMAL; flow is the lower-scoring leg inside it.
    assert binding == "flow"


def test_missing_leg_is_skipped():
    legs = [
        CrowdingLeg("price", 9.09, 70.0, "WARM"),
        CrowdingLeg("flow", 0.28, 22.8, "COLD"),
        CrowdingLeg("premium", None, None, None),
    ]
    score, state, binding = combine(legs)
    assert score == pytest.approx(46.4, abs=0.01)
    assert state == "COLD"
    assert binding == "flow"


def test_fewer_than_two_legs_yields_nothing():
    legs = [
        CrowdingLeg("price", 1.0, 50.0, "WARM"),
        CrowdingLeg("flow", None, None, None),
        CrowdingLeg("premium", None, None, None),
    ]
    assert combine(legs) == (None, None, None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_sector_crowding_scoring.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.reports.sector_crowding'`

- [ ] **Step 3: Write the module**

Create `src/uw_scan/reports/sector_crowding.py`:

```python
"""Sector-ETF crowding score (板块拥挤度).

Three conjunctive legs, adapted from
https://x.com/bitfool1/status/2079479920162734401 (2026-07-21):

  price    3M return minus the benchmark's, expressed as that ETF's OWN
           trailing percentile. Absolute spread is not comparable across the
           universe -- the trailing SD of the 3M spread ranges from 3.1 (XLY)
           to 16.5 (XLE), so ranking on raw spread ranks volatility, not
           crowding. XLF at +3.14% is its 99th percentile; SMH at +17.88% is
           its 46th.
  flow     21-session net premium flow / AUM, scored on the tweet's published
           2% / 5% / 10% bands. Dividing by AUM already removes the size
           effect, so absolute bands ARE comparable here and are kept.
  premium  iv_rank minus the benchmark's iv_rank. Substitutes for the tweet's
           NTM P/E, which needs constituent forward EPS that neither UW nor
           massive expose on our tier. Same question -- is the crowd paying up
           -- asked about convexity instead of earnings.

STATE is the weakest leg's band, not the mean's. The tweet is explicit that
the legs are conjunctive (三者同时出现，才算真正拥挤); a mean would let one
extreme leg manufacture a CROWDED badge on its own. SCORE stays the mean so
rows sort with some granularity inside a state, and `binding_leg` names which
leg is holding the state down so a demotion is always explainable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

RETURN_WINDOW = 63
FLOW_WINDOW = 21
MIN_SESSIONS = RETURN_WINDOW + FLOW_WINDOW
MIN_HISTORY_POINTS = 60
LOOKBACK_DAYS = 400

BENCHMARK = "SPY"
SECTOR_CROWDING_TICKERS = (
    "XLB", "XLC", "XLE", "XLF", "XLI", "XLK", "XLP",
    "XLRE", "XLU", "XLV", "XLY", "SOXX", "SMH", "IGV",
)
# ARKK is deliberately absent: UW's /api/etfs/ARKK/in-outflow returns 0 rows.
# Verified 2026-07-24. Re-add if UW starts publishing it.

# (flow_pct, score) anchors for piecewise-linear interpolation, clamped
# outside the ends. Derived from the tweet's bands: <2% normal, 2-5% warm,
# 5%+ crowded, 10%+ extreme.
FLOW_BREAKPOINTS: tuple[tuple[float, float], ...] = (
    (-5.0, 0.0), (0.0, 20.0), (2.0, 40.0),
    (5.0, 70.0), (10.0, 90.0), (25.0, 100.0),
)
IVR_SPREAD_CAP = 60.0

BAND_CROWDED = 75.0
BAND_WARM = 50.0
BAND_NORMAL = 25.0

_BAND_RANK = {"COLD": 0, "NORMAL": 1, "WARM": 2, "CROWDED": 3}


@dataclass(frozen=True)
class CrowdingLeg:
    name: str
    raw: float | None
    score: float | None
    band: str | None


def pct_rank(history: Sequence[float], value: float) -> float | None:
    """Percentile of `value` within `history`, 0-100. None if no history."""
    if not history:
        return None
    below = sum(1 for h in history if h < value)
    return 100.0 * below / len(history)


def flow_score(flow_aum_pct: float) -> float:
    """Map 1M-flow/AUM percent onto 0-100 via the tweet's bands."""
    lo_x, lo_y = FLOW_BREAKPOINTS[0]
    if flow_aum_pct <= lo_x:
        return lo_y
    for (x0, y0), (x1, y1) in zip(
        FLOW_BREAKPOINTS, FLOW_BREAKPOINTS[1:], strict=False
    ):
        if flow_aum_pct <= x1:
            span = x1 - x0
            return y0 + (flow_aum_pct - x0) / span * (y1 - y0)
    return FLOW_BREAKPOINTS[-1][1]


def premium_score(ivr_spread: float) -> float:
    """Map an iv_rank spread (percentage points vs benchmark) onto 0-100."""
    if ivr_spread <= 0.0:
        return 0.0
    return min(ivr_spread, IVR_SPREAD_CAP) / IVR_SPREAD_CAP * 100.0


def band_of(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= BAND_CROWDED:
        return "CROWDED"
    if score >= BAND_WARM:
        return "WARM"
    if score >= BAND_NORMAL:
        return "NORMAL"
    return "COLD"


def combine(
    legs: Sequence[CrowdingLeg],
) -> tuple[float | None, str | None, str | None]:
    """(mean score, weakest-leg band, name of the leg pinning that band).

    Needs at least two present legs -- a single leg is a reading, not a
    conjunction, and badging it would overstate what we know.
    """
    present = [leg for leg in legs if leg.score is not None and leg.band is not None]
    if len(present) < 2:
        return (None, None, None)
    score = sum(leg.score for leg in present) / len(present)
    weakest = min(_BAND_RANK[leg.band] for leg in present)
    in_band = [leg for leg in present if _BAND_RANK[leg.band] == weakest]
    binding = min(in_band, key=lambda leg: leg.score)
    return (score, binding.band, binding.name)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/reports/test_sector_crowding_scoring.py -v
uv run ruff check src/uw_scan/reports/sector_crowding.py
```
Expected: 25 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/sector_crowding.py \
        tests/unit/reports/test_sector_crowding_scoring.py
git commit -m "feat(regime): sector crowding leg mappers and min-band state"
```

---

### Task 3: Bulk iv_rank read + crowding assembly

**Files:**
- Modify: `src/uw_scan/storage/watchlist.py` (add one method to the existing mixin)
- Modify: `src/uw_scan/reports/sector_crowding.py` (append the assembly layer)
- Test: `tests/unit/reports/test_sector_crowding_build.py`

**Interfaces:**
- Consumes: `CrowdingLeg`, `combine`, `flow_score`, `premium_score`, `pct_rank`, and the constants from Task 2; `normalize_etf_aum` from Task 1.
- Produces:
  - `Repository.fetch_iv_ranks(tickers: Sequence[str], *, max_age: timedelta | None = None) -> dict[str, float]` — uppercased keys; tickers with a NULL `iv_rank`, no card, or a `scanned_at` older than `max_age` are omitted.
  - `CrowdingSeriesPoint` frozen dataclass: `obs_date: date`, `etf_cum_return: float`, `bench_cum_return: float`, `flow_aum_pct: float | None`
  - `CrowdingRow` frozen dataclass: `ticker: str`, `price: CrowdingLeg`, `flow: CrowdingLeg`, `premium: CrowdingLeg`, `score: float | None`, `state: str | None`, `binding_leg: str | None`, `series: list[CrowdingSeriesPoint]`
  - `build_sector_crowding(*, repo, tickers=SECTOR_CROWDING_TICKERS, benchmark=BENCHMARK) -> tuple[date | None, list[CrowdingRow]]` — rows sorted by `(band rank desc, score desc, ticker asc)`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/reports/test_sector_crowding_build.py`. It uses a hand-rolled fake repo rather than a DB fixture — the assembly logic is pure given rows, and a fake keeps the test fast and deterministic.

```python
"""Assembly of crowding rows from repo reads, with a fake repo.

Shapes mirror Repository.fetch_etf_flows_daily (storage/gold_etf.py:80),
Repository.get_recent_etf_aum (storage/market_data.py:202) and the
fetch_iv_ranks method added in this task.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from uw_scan.reports.sector_crowding import RETURN_WINDOW, build_sector_crowding


def _flows(
    *,
    n: int,
    start_close: float,
    end_close: float,
    flow_per_day: float,
    late_boost: float = 1.0,
):
    """n sessions of geometric drift with a constant daily flow.

    `late_boost` adds an extra multiplier spread across the final 63 sessions.
    Without it the drift is perfectly constant, so EVERY trailing 63-session
    return is identical and pct_rank collapses to 0 -- the percentile leg needs
    today to actually stand out from its own history to be exercised.
    """
    rows = []
    day = date(2025, 7, 1)
    step = (end_close / start_close) ** (1.0 / max(n - 1, 1))
    boost = late_boost ** (1.0 / 63)
    close = start_close
    for i in range(n):
        rows.append(
            {
                "obs_date": day + timedelta(days=i),
                "share_change": Decimal("0"),
                "premium_change_usd": Decimal(str(flow_per_day)),
                "close": Decimal(str(round(close, 4))),
                "volume": Decimal("1000"),
            }
        )
        close *= step * (boost if i >= n - 63 else 1.0)
    return rows


class FakeRepo:
    def __init__(self, flows, aums, iv_ranks):
        self._flows = flows
        self._aums = aums
        self._iv_ranks = iv_ranks

    def fetch_etf_flows_daily(self, ticker, **kwargs):
        return self._flows.get(ticker.upper(), [])

    def get_recent_etf_aum(self, ticker, *, max_age):
        return self._aums.get(ticker.upper())

    def fetch_iv_ranks(self, tickers, *, max_age=None):
        return {t: self._iv_ranks[t] for t in tickers if t in self._iv_ranks}


def test_builds_a_row_per_ticker_with_all_three_legs():
    n = 200
    repo = FakeRepo(
        flows={
            "SOXX": _flows(
                n=n,
                start_close=300.0,
                end_close=527.0,
                flow_per_day=1e9,
                late_boost=1.4,
            ),
            "SPY": _flows(n=n, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"SOXX": Decimal("45064294868"), "SPY": Decimal("743252024000")},
        iv_ranks={"SOXX": 93.93, "SPY": 29.70},
    )
    as_of, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))

    assert as_of == date(2025, 7, 1) + timedelta(days=n - 1)
    assert len(rows) == 1
    row = rows[0]
    assert row.ticker == "SOXX"
    # Steady outperformance + steady inflow + a 64pt iv_rank spread.
    assert row.price.score is not None and row.price.score > 50.0
    assert row.flow.score == 100.0
    assert row.premium.score == pytest.approx(100.0)
    assert row.state == "CROWDED"


def test_short_history_yields_no_price_leg_but_keeps_flow():
    repo = FakeRepo(
        flows={
            "XLE": _flows(n=90, start_close=90.0, end_close=95.0, flow_per_day=1e6),
            "SPY": _flows(n=90, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"XLE": Decimal("59.4"), "SPY": Decimal("743.252024")},
        iv_ranks={"XLE": 65.16, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("XLE",))
    row = rows[0]
    # 90 sessions clears MIN_SESSIONS (84) but not the percentile floor.
    assert row.price.raw is not None
    assert row.price.score is None
    assert row.flow.score is not None
    assert row.premium.score is not None
    assert row.state is not None  # two legs is still a verdict


def test_aum_in_billions_is_normalized_before_dividing():
    """XLE's AUM arrives as 59.4 (billions). Without normalization the flow
    ratio is off by 1e9 and every SPDR sector ETF pins at 100."""
    repo = FakeRepo(
        flows={
            "XLE": _flows(n=200, start_close=90.0, end_close=95.0, flow_per_day=1e6),
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9, flow_per_day=1e7),
        },
        aums={"XLE": Decimal("59.4"), "SPY": Decimal("743.252024")},
        iv_ranks={"XLE": 65.16, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("XLE",))
    # 21 sessions x $1M = $21M against $59.4B -> ~0.035%, nowhere near a band.
    assert rows[0].flow.raw == pytest.approx(0.035, abs=0.005)


def test_missing_flow_data_drops_the_ticker():
    repo = FakeRepo(
        flows={"SPY": _flows(n=200, start_close=700.0, end_close=738.9,
                             flow_per_day=1e7)},
        aums={"SPY": Decimal("743252024000")},
        iv_ranks={"SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("ARKK",))
    assert rows == []


def test_no_benchmark_data_yields_no_rows():
    repo = FakeRepo(flows={}, aums={}, iv_ranks={})
    as_of, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))
    assert as_of is None
    assert rows == []


def test_series_is_rebased_to_zero_at_the_window_start():
    repo = FakeRepo(
        flows={
            "SOXX": _flows(n=200, start_close=300.0, end_close=527.0,
                           flow_per_day=1e9, late_boost=1.4),
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9,
                          flow_per_day=1e7),
        },
        aums={"SOXX": Decimal("45064294868"), "SPY": Decimal("743252024000")},
        iv_ranks={"SOXX": 93.93, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))
    row = rows[0]
    series = row.series
    # RETURN_WINDOW intervals == RETURN_WINDOW + 1 observations.
    assert len(series) == RETURN_WINDOW + 1
    assert series[0].etf_cum_return == pytest.approx(0.0, abs=1e-9)
    assert series[0].bench_cum_return == pytest.approx(0.0, abs=1e-9)
    assert series[-1].etf_cum_return > series[-1].bench_cum_return


def test_chart_endpoint_equals_the_scored_price_leg():
    """The drill-down must visualize the number in the price cell.

    Rebasing the chart one session later than _window_return scores is
    invisible by eye -- it shifts the endpoint by a fraction of a percent --
    so pin it.
    """
    repo = FakeRepo(
        flows={
            "SOXX": _flows(n=200, start_close=300.0, end_close=527.0,
                           flow_per_day=1e9, late_boost=1.4),
            "SPY": _flows(n=200, start_close=700.0, end_close=738.9,
                          flow_per_day=1e7),
        },
        aums={"SOXX": Decimal("45064294868"), "SPY": Decimal("743252024000")},
        iv_ranks={"SOXX": 93.93, "SPY": 29.70},
    )
    _, rows = build_sector_crowding(repo=repo, tickers=("SOXX",))
    row = rows[0]
    last = row.series[-1]
    assert last.etf_cum_return - last.bench_cum_return == pytest.approx(
        row.price.raw, abs=1e-9
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/reports/test_sector_crowding_build.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_sector_crowding'`

- [ ] **Step 3: Add the bulk iv_rank read**

In `src/uw_scan/storage/watchlist.py`, add this method to the same mixin class that holds the other `watchlist_card` reads (place it immediately before the `# etf_aum_cache methods moved to _MarketDataMixin` comment near line 566):

```python
    def fetch_iv_ranks(
        self, tickers: Sequence[str], *, max_age: timedelta | None = None
    ) -> dict[str, float]:
        """iv_rank per ticker from the warm store. Tickers with no card, a
        NULL iv_rank, or a card older than `max_age` are omitted rather than
        returned as None -- the caller treats absence as 'no premium leg'.

        The freshness bound matters: watchlist_card is a warm store that is
        only refreshed when a ticker actually scans. A ticker that drops out of
        the scan (the SPX 17-day silent gap in 2026-05 is the precedent) keeps
        its last iv_rank forever, and an unbounded read would score the premium
        leg on a month-old number while every other leg is current.
        """
        wanted = [t.upper() for t in tickers]
        if not wanted:
            return {}
        clauses = ["ticker = ANY(%s)", "iv_rank IS NOT NULL"]
        params: list[Any] = [wanted]
        if max_age is not None:
            clauses.append("scanned_at >= NOW() - %s")
            params.append(max_age)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, iv_rank
                FROM {self._schema}.watchlist_card
                WHERE {" AND ".join(clauses)}
                """,
                params,
            )
            return {row[0]: float(row[1]) for row in cur.fetchall()}
```

Confirm `Sequence`, `timedelta`, and `Any` are imported in that file; add whichever are missing (`from collections.abc import Sequence`, `from datetime import timedelta`, `from typing import Any`).

- [ ] **Step 4: Append the assembly layer**

Add to the end of `src/uw_scan/reports/sector_crowding.py`. Extend the existing `from __future__` block's imports at the top of the file with:

```python
from datetime import date as _date
from datetime import timedelta
from typing import Any, Protocol

from uw_scan.storage.market_data import normalize_etf_aum
```

Then append:

```python
_AUM_MAX_AGE = timedelta(days=30)

# watchlist_card only refreshes when a ticker scans, so an unbounded iv_rank
# read scores the premium leg on whatever the last successful scan left behind.
# Five days clears a long weekend plus one holiday; anything older means the
# ticker stopped scanning and the leg should go absent, not stale.
_IVR_MAX_AGE = timedelta(days=5)


class _CrowdingRepo(Protocol):
    """The three reads build_sector_crowding needs. Declared structurally so
    the unit tests can pass a fake without touching Postgres."""

    def fetch_etf_flows_daily(
        self, ticker: str, **kwargs: Any
    ) -> list[dict[str, Any]]: ...

    def get_recent_etf_aum(self, ticker: str, *, max_age: timedelta) -> Any: ...

    def fetch_iv_ranks(
        self, tickers: Sequence[str], *, max_age: timedelta
    ) -> dict[str, float]: ...


@dataclass(frozen=True)
class CrowdingSeriesPoint:
    obs_date: _date
    etf_cum_return: float
    bench_cum_return: float
    flow_aum_pct: float | None


@dataclass(frozen=True)
class CrowdingRow:
    ticker: str
    price: CrowdingLeg
    flow: CrowdingLeg
    premium: CrowdingLeg
    score: float | None
    state: str | None
    binding_leg: str | None
    series: list[CrowdingSeriesPoint]


def _valid(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows carrying a usable close, in date order.

    Returns the ROWS, not the closes. Filtering a parallel list of closes and
    leaving `rows` untouched desynchronizes them: rows[i] would no longer be
    the row closes[i] came from, so flow windows and chart dates would silently
    describe different observations than the returns.
    """
    return [
        r for r in rows if r.get("close") is not None and float(r["close"]) > 0
    ]


def _window_return(closes: Sequence[float], end: int, window: int) -> float | None:
    """Percent return over `window` sessions ending at index `end`."""
    start = end - window
    if start < 0 or closes[start] == 0:
        return None
    return (closes[end] / closes[start] - 1.0) * 100.0


def _flow_ratio(
    rows: list[dict[str, Any]], end: int, aum: float | None
) -> float | None:
    start = end - FLOW_WINDOW + 1
    if start < 0 or not aum:
        return None
    total = sum(
        float(r["premium_change_usd"])
        for r in rows[start : end + 1]
        if r.get("premium_change_usd") is not None
    )
    return 100.0 * total / aum


def build_sector_crowding(
    *,
    repo: _CrowdingRepo,
    tickers: Sequence[str] = SECTOR_CROWDING_TICKERS,
    benchmark: str = BENCHMARK,
) -> tuple[_date | None, list[CrowdingRow]]:
    """Rank `tickers` by crowding against `benchmark`.

    Read-time compute over etf_flows_daily + etf_aum_cache + watchlist_card.
    Every input is already persisted; nothing here is the only copy of
    anything, which is why the score itself needs no table.
    """
    # Bound the read. Unbounded, the percentile leg silently changes meaning as
    # the table accrues -- in year three it would rank today against three years
    # of history, which is not the statistic the probe validated. Same window as
    # the capture, so the read never asks for rows the job does not maintain.
    since = _date.today() - timedelta(days=LOOKBACK_DAYS)

    bench_rows = repo.fetch_etf_flows_daily(benchmark, from_date=since)
    bench_by_date = {r["obs_date"]: float(r["close"]) for r in _valid(bench_rows)}
    if len(bench_by_date) < MIN_SESSIONS:
        return (None, [])

    iv_ranks = repo.fetch_iv_ranks([*tickers, benchmark], max_age=_IVR_MAX_AGE)
    bench_ivr = iv_ranks.get(benchmark.upper())

    out: list[CrowdingRow] = []
    as_of: _date | None = None

    for ticker in tickers:
        # Inner-join on obs_date. Aligning by POSITION -- truncating both lists
        # to the shorter length -- silently compares different sessions the
        # first time either series is missing a day: one dropped UW row, or a
        # holiday one venue observes. Every subsequent index is then shifted,
        # and nothing about the output looks wrong.
        paired = [
            (r, float(r["close"]), bench_by_date[r["obs_date"]])
            for r in _valid(repo.fetch_etf_flows_daily(ticker, from_date=since))
            if r["obs_date"] in bench_by_date
        ]
        if len(paired) < MIN_SESSIONS:
            continue

        rows = [p[0] for p in paired]
        closes = [p[1] for p in paired]
        bench = [p[2] for p in paired]
        n = len(paired)
        last = n - 1

        row_date = rows[last]["obs_date"]
        as_of = row_date if as_of is None else max(as_of, row_date)

        etf_r = _window_return(closes, last, RETURN_WINDOW)
        bench_r = _window_return(bench, last, RETURN_WINDOW)
        rel = None if etf_r is None or bench_r is None else etf_r - bench_r

        # Trailing history of the SAME relative-return metric, so the
        # percentile answers "extreme for this ETF", not "extreme vs XLU".
        #
        # `history` deliberately INCLUDES today's own value: the loop runs to
        # n-1. pct_rank counts strictly-below, so today can never print 100 --
        # the ceiling is (len-1)/len, about 99.1 over a year. That matches the
        # probe that produced every frozen fixture. Excluding today would look
        # tidier and would silently shift every expected percentile in the
        # tests. Do not "fix" it.
        history: list[float] = []
        for i in range(RETURN_WINDOW + FLOW_WINDOW, n):
            a = _window_return(closes, i, RETURN_WINDOW)
            b = _window_return(bench, i, RETURN_WINDOW)
            if a is not None and b is not None:
                history.append(a - b)
        price_score = (
            pct_rank(history, rel)
            if rel is not None and len(history) >= MIN_HISTORY_POINTS
            else None
        )
        price = CrowdingLeg("price", rel, price_score, band_of(price_score))

        aum_raw = repo.get_recent_etf_aum(ticker, max_age=_AUM_MAX_AGE)
        aum = normalize_etf_aum(aum_raw)
        ratio = _flow_ratio(rows, last, float(aum) if aum else None)
        f_score = None if ratio is None else flow_score(ratio)
        flow = CrowdingLeg("flow", ratio, f_score, band_of(f_score))

        etf_ivr = iv_ranks.get(ticker.upper())
        spread = (
            None if etf_ivr is None or bench_ivr is None else etf_ivr - bench_ivr
        )
        p_score = None if spread is None else premium_score(spread)
        premium = CrowdingLeg("premium", spread, p_score, band_of(p_score))

        score, state, binding = combine([price, flow, premium])

        # Every historical bar divides by TODAY's AUM -- etf_aum_cache keeps
        # one row per ticker, so there is no AUM history to divide by. If a
        # fund grew 40% over the window, its older bars read ~40% low. The
        # bars are a shape cue, not a measurement; the scored leg only ever
        # uses the newest point, where the AUM is current. Same simplification
        # the probe made. Storing an AUM series would fix it, and needs a table.
        series = []
        # RETURN_WINDOW counts INTERVALS, so the scored window spans
        # RETURN_WINDOW+1 observations -- _window_return divides closes[end] by
        # closes[end - RETURN_WINDOW]. Starting the chart at n - RETURN_WINDOW
        # would rebase one session late and the chart's final ETF-minus-bench
        # value would not equal price.raw (measured on the Task 3 fixture:
        # 64.27603 charted vs 64.71898 scored). Locked by an assertion in the
        # test below.
        window_start = max(0, n - 1 - RETURN_WINDOW)
        base_etf, base_bench = closes[window_start], bench[window_start]
        for i in range(window_start, n):
            series.append(
                CrowdingSeriesPoint(
                    obs_date=rows[i]["obs_date"],
                    etf_cum_return=(closes[i] / base_etf - 1.0) * 100.0,
                    bench_cum_return=(bench[i] / base_bench - 1.0) * 100.0,
                    flow_aum_pct=_flow_ratio(
                        rows, i, float(aum) if aum else None
                    ),
                )
            )

        out.append(
            CrowdingRow(
                ticker=ticker.upper(),
                price=price,
                flow=flow,
                premium=premium,
                score=score,
                state=state,
                binding_leg=binding,
                series=series,
            )
        )

    # Group by verdict first so CROWDED rows sit together, then by score
    # inside a band. Sorting on score alone would interleave states, which
    # reads as a broken table.
    # Negated numerics rather than reverse=True, which would also flip the
    # ticker tiebreak to Z->A.
    out.sort(
        key=lambda r: (
            -_BAND_RANK.get(r.state or "COLD", -1),
            -(r.score if r.score is not None else -1.0),
            r.ticker,
        )
    )
    return (as_of, out)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
uv run pytest tests/unit/reports/test_sector_crowding_build.py -v
uv run ruff check src/uw_scan/reports/sector_crowding.py src/uw_scan/storage/watchlist.py
                          src/uw_scan/storage/watchlist.py
```
Expected: 7 passed, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/sector_crowding.py src/uw_scan/storage/watchlist.py \
        tests/unit/reports/test_sector_crowding_build.py
git commit -m "feat(regime): assemble sector crowding rows from warm store"
```

---

### Task 4: Nightly capture job

Mirrors `worker/jobs/gold_jobs.py:271-310`, which already loops `GOLD_ETF_FLOW_TICKERS` through `fetch_etf_in_outflow` into `insert_etf_flows_daily_rows`. Same fetcher, same table, different ticker constant.

**Files:**
- Create: `src/uw_scan/worker/jobs/sector_crowding_capture.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/reports/data_freshness.py:108-112`
- Test: `tests/unit/test_sector_crowding_capture.py`

**Interfaces:**
- Consumes: `SECTOR_CROWDING_TICKERS`, `BENCHMARK`, `LOOKBACK_DAYS` from Task 2.
- Produces: `sector_crowding_capture(*, repo, client, settings) -> int` returning the number of rows inserted.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sector_crowding_capture.py`:

```python
"""Capture job: one UW in-outflow call plus one AUM refresh per ticker."""

from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from uw_scan.reports.sector_crowding import LOOKBACK_DAYS
from uw_scan.worker.jobs.sector_crowding_capture import (
    CAPTURE_TAIL_DAYS,
    sector_crowding_capture,
)


def _row(ticker: str, day: date):
    return SimpleNamespace(
        ticker=ticker,
        date=day,
        change=Decimal("1000"),
        change_prem=Decimal("2018212065"),
        close=Decimal("527.01"),
        volume=Decimal("10306265"),
    )


def test_captures_every_ticker_plus_the_benchmark():
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")

    with patch(
        "uw_scan.worker.jobs.sector_crowding_capture.uw_sources"
    ) as sources:
        sources.fetch_etf_in_outflow.side_effect = lambda **kw: [
            _row(kw["ticker"], date(2026, 7, 24))
        ]
        sources.fetch_etf_info.return_value = SimpleNamespace(
            aum=Decimal("45064294868")
        )
        sector_crowding_capture(repo=repo, client=client, settings=settings)

    called = {
        c.kwargs["ticker"] for c in sources.fetch_etf_in_outflow.call_args_list
    }
    assert "SPY" in called          # benchmark is required for every leg
    assert "SOXX" in called
    assert "XLK" in called
    assert "ARKK" not in called     # UW returns 0 rows for it
    assert len(called) == 15        # 14 sector ETFs + SPY


def test_one_bad_ticker_does_not_abort_the_run():
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")

    def flaky(**kw):
        if kw["ticker"] == "XLE":
            raise RuntimeError("UW 429")
        return [_row(kw["ticker"], date(2026, 7, 24))]

    with patch(
        "uw_scan.worker.jobs.sector_crowding_capture.uw_sources"
    ) as sources:
        sources.fetch_etf_in_outflow.side_effect = flaky
        sources.fetch_etf_info.return_value = SimpleNamespace(
            aum=Decimal("45064294868")
        )
        inserted = sector_crowding_capture(
            repo=repo, client=client, settings=settings
        )

    assert inserted == 14  # 15 attempted, XLE dropped
    # repo.conn.commit(), NOT repo.commit() -- Repository has no commit method;
    # every worker job commits through the connection. Asserting the wrong name
    # on a MagicMock passes silently, so this line is load-bearing.
    assert repo.conn.commit.called


def _spans(sources) -> set[int]:
    """Requested window width per ticker, in days."""
    return {
        (
            date.fromisoformat(c.kwargs["end_date"])
            - date.fromisoformat(c.kwargs["start_date"])
        ).days
        for c in sources.fetch_etf_in_outflow.call_args_list
    }


def _run(repo):
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")
    with patch(
        "uw_scan.worker.jobs.sector_crowding_capture.uw_sources"
    ) as sources:
        sources.fetch_etf_in_outflow.side_effect = lambda **kw: [
            _row(kw["ticker"], date(2026, 7, 24))
        ]
        sources.fetch_etf_info.return_value = SimpleNamespace(aum=Decimal("1"))
        sector_crowding_capture(repo=repo, client=client, settings=settings)
        return _spans(sources)


def test_populated_tail_pulls_only_the_short_window():
    """Steady state. Every run re-inserts its whole window under a fresh
    as_of, so the window width is a direct multiplier on table growth."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    repo.fetch_etf_flows_daily.return_value = [{"obs_date": date(2026, 7, 23)}]

    assert _run(repo) == {CAPTURE_TAIL_DAYS}


def test_empty_tail_widens_to_full_history():
    """First run for a ticker, or recovery from an outage longer than the
    tail. Without the widen the percentile leg never accumulates the 60
    history points it needs and the price leg stays permanently None."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    repo.fetch_etf_flows_daily.return_value = []

    assert _run(repo) == {LOOKBACK_DAYS}


def test_as_of_is_the_market_date_so_a_rerun_is_a_noop():
    """etf_flows_daily's conflict target is (ticker, obs_date, as_of). A
    wall-clock as_of makes every re-run a fresh key, so ON CONFLICT DO NOTHING
    never fires and worker/CLAUDE.md's run-twice-same-state rule is violated.
    Pin the stamp to midnight UTC of the capture date."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.insert_etf_flows_daily_rows.return_value = 1
    repo.fetch_etf_flows_daily.return_value = [{"obs_date": date(2026, 7, 23)}]

    _run(repo)

    stamps = {
        c.kwargs["as_of"] for c in repo.insert_etf_flows_daily_rows.call_args_list
    }
    assert len(stamps) == 1
    (as_of,) = stamps
    assert as_of.tzinfo is not None
    assert (as_of.hour, as_of.minute, as_of.second, as_of.microsecond) == (0, 0, 0, 0)
    assert as_of.date() == datetime.now(ZoneInfo("America/New_York")).date()


def test_scan_run_is_always_closed():
    """A raise from outside the per-ticker guards must not leave the run row at
    status='running' forever."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 42
    repo.fetch_etf_flows_daily.side_effect = RuntimeError("DB gone")
    client = MagicMock()
    settings = SimpleNamespace(rth_tz="America/New_York")

    with patch("uw_scan.worker.jobs.sector_crowding_capture.uw_sources"):
        # fetch_etf_flows_daily is inside the per-ticker try, so the sweep
        # survives it and returns 0 -> status 'fail', run still closed.
        sector_crowding_capture(repo=repo, client=client, settings=settings)

    repo.finish_scan_run.assert_called_once_with(42, status="fail")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_sector_crowding_capture.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.worker.jobs.sector_crowding_capture'`

- [ ] **Step 3: Write the job**

Create `src/uw_scan/worker/jobs/sector_crowding_capture.py`:

```python
"""Nightly UW in-outflow + AUM capture for the sector-crowding universe.

Same fetcher and same table as the gold ETF flow ingest
(worker/jobs/gold_jobs.py:271-310) -- only the ticker constant differs. One
/api/etfs/{t}/in-outflow call plus one /api/etfs/{t}/info call per ticker,
15 tickers, so ~30 UW calls a night against a 120k/day budget.

ponytail: no kill-switch setting. 30 calls is inside the noise floor and each
ticker is already wrapped in its own try/except, so a UW outage degrades to a
warn-and-continue rather than a stuck job. Add a flag if this ever grows a
per-constituent fan-out.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from uw_scan.reports.sector_crowding import (
    BENCHMARK,
    LOOKBACK_DAYS,
    SECTOR_CROWDING_TICKERS,
)
from uw_scan.sources import uw as uw_sources

logger = logging.getLogger(__name__)

# Nightly re-fetch window. Matches gold_jobs' 45-day default, which exists to
# absorb UW revising recent flow figures. See the sizing note in the loop below
# for why this is not simply LOOKBACK_DAYS.
CAPTURE_TAIL_DAYS = 45


def sector_crowding_capture(*, repo, client, settings) -> int:
    """Fetch and persist in-outflow history + AUM for the sector universe.

    Returns the number of flow rows inserted.
    """
    today = datetime.now(ZoneInfo(settings.rth_tz)).date()
    end = today.isoformat()

    # as_of is part of etf_flows_daily's conflict target
    # (ticker, obs_date, as_of), so a wall-clock stamp would make every re-run
    # a fresh key and ON CONFLICT DO NOTHING would never fire. worker/CLAUDE.md
    # requires a job that runs twice in a minute to produce the same DB state,
    # so stamp the market DATE instead: a same-day re-run (manual kick, crash
    # retry, both shards racing) collides and no-ops. Distinct capture dates
    # still get distinct as_of rows, which is what the column is for.
    captured_at = datetime(today.year, today.month, today.day, tzinfo=UTC)

    run_id = repo.insert_scan_run(
        ticker="SECTOR",
        notes=f"sector_crowding_capture:{end}",
    )

    inserted = 0
    try:
        inserted = _capture_all(repo, client, run_id, today, end, captured_at)
    finally:
        # Without this the row sits at status='running' forever and any
        # scan_runs-based freshness check reads the job as hung. In `finally`
        # because a repo-level failure outside the per-ticker guards must still
        # close the run -- and finish_scan_run self-commits (scan_runs.py:78),
        # so on that path the partial flow inserts land too. Partial beats
        # nothing here: the per-ticker guards already make partial the normal
        # outcome of a UW hiccup.
        repo.finish_scan_run(run_id, status="ok" if inserted else "fail")

    # repo.conn.commit(), not repo.commit() -- Repository exposes the psycopg
    # connection and has no commit of its own, and scheduler._repo closes the
    # connection without committing. finish_scan_run above already committed,
    # so on the happy path this is a no-op; it stays because every other worker
    # job ends this way and the guarantee should not depend on a storage
    # method's private commit behaviour.
    repo.conn.commit()
    logger.info("sector_crowding_capture: inserted %d flow rows", inserted)
    return inserted


def _capture_all(repo, client, run_id, today, end, captured_at) -> int:
    """One in-outflow pull plus one AUM refresh per ticker.

    Split out only so `sector_crowding_capture` can wrap the whole sweep in a
    try/finally without a 90-line try body. Never raises for a single bad
    ticker; returns the number of flow rows inserted.
    """
    inserted = 0
    for ticker in (*SECTOR_CROWDING_TICKERS, BENCHMARK):
        try:
            # Window sizing, not cosmetics. as_of is per capture DATE, so a
            # same-day re-run no-ops -- but each new day still re-inserts the
            # whole window under a new as_of. Measured on the live DB
            # 2026-07-26: GLD holds 621 rows for 73 distinct obs_dates (8.5x)
            # from gold_jobs' 45-day window over 3 tickers. A flat 400-day
            # window over 15 tickers would add ~4,100 rows a night -- about a
            # million rows a year to store ~4,100 facts. Reads are unaffected
            # (fetch_etf_flows_daily is DISTINCT ON (obs_date) ORDER BY as_of
            # DESC); this is purely a storage bound.
            #
            # So: pull a short tail nightly, and widen to the full history only
            # when the tail comes back empty. That is the first run for a
            # ticker, or recovery after an outage longer than the tail. Self
            # healing, so no separate backfill script is needed.
            has_recent = bool(
                repo.fetch_etf_flows_daily(
                    ticker, from_date=today - timedelta(days=CAPTURE_TAIL_DAYS)
                )
            )
            days = CAPTURE_TAIL_DAYS if has_recent else LOOKBACK_DAYS
            start = (today - timedelta(days=days)).isoformat()

            rows = [
                {
                    "ticker": row.ticker,
                    "obs_date": row.date,
                    "share_change": row.change,
                    "premium_change_usd": row.change_prem,
                    "close": row.close,
                    "volume": row.volume,
                }
                for row in uw_sources.fetch_etf_in_outflow(
                    client=client,
                    repo=repo,
                    run_id=run_id,
                    ticker=ticker,
                    start_date=start,
                    end_date=end,
                )
            ]
            if not rows:
                logger.warning(
                    "sector_crowding_capture: %s returned 0 rows", ticker
                )
                continue
            inserted += repo.insert_etf_flows_daily_rows(
                rows, as_of=captured_at, source="UW"
            )
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not abort
            logger.warning(
                "sector_crowding_capture: %s flows skipped (%s)",
                ticker,
                repr(exc)[:200],
            )
            continue

        # Refresh AUM in the same pass; the crowding flow leg divides by it and
        # a stale cache silently skews the ratio.
        try:
            info = uw_sources.fetch_etf_info(client, repo, run_id, ticker)
            if info.aum is not None:
                repo.upsert_etf_aum(ticker, info.aum)
        except Exception as exc:  # noqa: BLE001 - AUM is a nice-to-have here
            logger.warning(
                "sector_crowding_capture: %s aum skipped (%s)",
                ticker,
                repr(exc)[:200],
            )
    return inserted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_sector_crowding_capture.py -v`
Expected: 6 passed.

- [ ] **Step 5: Register the cron**

In `src/uw_scan/worker/scheduler.py`, add the import alongside the other job imports (keep alphabetical position among the `uw_scan.worker.jobs.*` imports):

```python
from uw_scan.worker.jobs.sector_crowding_capture import sector_crowding_capture
```

Add the wrapper next to `_cockpit_daily_snapshot` (around line 907):

```python
    def _sector_crowding_capture() -> None:
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="sector_crowding_capture",
            ) as uw:
                with _repo(settings) as repo:
                    sector_crowding_capture(
                        repo=repo, client=uw, settings=settings
                    )
```

Register it inside the `if "uw" in groups:` block, guarded by `_is_primary_worker(settings)` so shards don't duplicate the UW spend. Place it next to the other primary-only UW jobs:

```python
        if _is_primary_worker(settings):
            # 18:45 ET -- after UW has published the session's ETF flow and
            # after the 18:30 single-name GEX refresh (uw group, :1526),
            # before the 19:00 option-surface capture (uw group, :1609).
            # skew_markout_refresh also fires at 18:45 but lives in the
            # MASSIVE group, i.e. a different worker process -- not a
            # conflict, do not "fix" it by moving this job.
            # "0-4" is Mon-Fri: APScheduler's day_of_week is 0=Monday, NOT
            # cron's 0=Sunday, and every other evening job here uses 0-4.
            sched.add_job(
                _sector_crowding_capture,
                CronTrigger.from_crontab("45 18 * * 0-4", timezone=settings.rth_tz),
                id="sector_crowding_capture",
                name="Sector crowding ETF flow capture",
                max_instances=1,
                coalesce=True,
            )
```

- [ ] **Step 6: Widen the freshness monitor's scope**

`src/uw_scan/reports/data_freshness.py:108-112` currently scopes `etf_flows_daily` to the three gold tickers, so a silent freeze in the new capture would go unnoticed — exactly what that monitor exists to prevent. Replace that `MonitoredTable` entry with:

```python
    MonitoredTable(
        "etf_flows_daily",
        "subset",
        # gold_jobs.GOLD_ETF_FLOW_TICKERS + sector_crowding.SECTOR_CROWDING_TICKERS
        # + its SPY benchmark. Both jobs write this table; scoping to only the
        # gold three would leave a frozen sector capture invisible.
        frozenset(
            {"GLD", "IAU", "GLDM"}
            | set(_SECTOR_CROWDING_TICKERS)
            | {"SPY"}
        ),
    ),
```

and add this import near the top of the same file, next to the existing `_GAP_HEALER_REGISTRY` import:

```python
from uw_scan.reports.sector_crowding import (
    SECTOR_CROWDING_TICKERS as _SECTOR_CROWDING_TICKERS,
)
```

No `DatasetRegistryEntry` or policy-doc regeneration is needed — that gate applies to *new* temporal tables, and `etf_flows_daily` is already registered at `reports/data_gap_healer.py:682`.

- [ ] **Step 7: Pin the cron wiring with a registration test**

The Task 7 manual run invokes the job function directly; it proves the job works but proves nothing about whether the cron registered, under which worker group, or whether the crontab string parses. `tests/unit/worker/test_scheduler_registration.py` already solves this: it boots the real `scheduler.main()` with a fake `BlockingScheduler` that records job ids and raises at `start()`, so registration runs but no DB or network does. Reuse the harness.

Create `tests/unit/worker/test_sector_crowding_scheduler_registration.py`:

```python
"""sector_crowding_capture cron wiring.

Locks the scheduler side: registers on a primary uw worker, and nowhere else.
A wrong group, a stale _is_primary_worker guard, or an unparseable crontab
string fails here rather than at 18:45 ET in production.
"""

from __future__ import annotations

import pytest

import uw_scan.worker.scheduler as scheduler

JOB_ID = "sector_crowding_capture"


class _StopStart(Exception):
    """Raised by the fake scheduler's start() to unwind main() after wiring."""


class _FakeSignal:
    SIGTERM = 15
    SIGINT = 2

    def signal(self, *_a, **_k) -> None:  # don't mutate the pytest process
        return None


def _registered_job_ids(monkeypatch, **env) -> set[str]:
    ids: list[str] = []

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *_a, **kwargs) -> None:
            ids.append(kwargs.get("id"))

        def start(self) -> None:
            raise _StopStart

        def shutdown(self, *_a, **_k) -> None:
            pass

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    with pytest.raises(_StopStart):
        scheduler.main()
    return {i for i in ids if i is not None}


def test_registered_on_primary_uw_worker(monkeypatch):
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert JOB_ID in ids


def test_not_registered_on_a_secondary_uw_shard(monkeypatch):
    """Two shards both firing would double the UW spend on the same 30 calls."""
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="uw",
        UW_SCAN_WORKER_INDEX="1",
        UW_SCAN_WORKER_COUNT="2",
    )
    assert JOB_ID not in ids


def test_not_registered_on_the_massive_worker(monkeypatch):
    """_is_primary_worker only checks role=='all' or index==0 -- it does NOT
    look at the group. The `if "uw" in groups:` block is what keeps this off
    the massive process, so index 0 here must still not register."""
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert JOB_ID not in ids
```

The three env names above are copied from `tests/unit/worker/test_scheduler_registration.py:62-64` — `_is_primary_worker` (`scheduler.py:263`) reads `settings.worker_role` and `settings.worker_index`. Getting a name wrong makes the two negative tests pass vacuously (an unrecognised role registers nothing), so treat `test_registered_on_primary_uw_worker` as the load-bearing one: if it fails, suspect the env names before the wiring.

- [ ] **Step 8: Verify the scheduler still imports and the policy test passes**

```bash
uv run python -c "import uw_scan.worker.scheduler; print('scheduler imports OK')"
uv run pytest tests/unit/test_data_gap_dataset_policy.py \
              tests/unit/test_sector_crowding_capture.py \
              tests/unit/worker/test_sector_crowding_scheduler_registration.py -v
uv run ruff check src/uw_scan/worker/ src/uw_scan/reports/data_freshness.py
                           src/uw_scan/worker/scheduler.py \
                           src/uw_scan/reports/data_freshness.py
```
Expected: import OK, all tests pass, ruff clean.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/worker/jobs/sector_crowding_capture.py \
        src/uw_scan/worker/scheduler.py \
        src/uw_scan/reports/data_freshness.py \
        tests/unit/test_sector_crowding_capture.py \
        tests/unit/worker/test_sector_crowding_scheduler_registration.py
git commit -m "feat(worker): nightly sector-ETF flow capture at 18:45 ET"
```

---

### Task 5: API contract and endpoint

**Files:**
- Create: `src/uw_scan/api/models/sector_crowding.py`
- Modify: `src/uw_scan/api/routers/regime.py`
- Modify: `tests/integration/api/openapi.snapshot.json`
- Test: `tests/unit/test_sector_crowding_api.py`

**Interfaces:**
- Consumes: `build_sector_crowding`, `CrowdingRow`, `CrowdingLeg`, `CrowdingSeriesPoint` from Task 3.
- Produces: `GET /api/regime/sector-crowding` returning `SectorCrowdingResponse`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sector_crowding_api.py`:

```python
"""Endpoint shape for /api/regime/sector-crowding."""

from datetime import date

from uw_scan.api.models.sector_crowding import (
    SectorCrowdingLeg,
    SectorCrowdingResponse,
    SectorCrowdingRow,
    SectorCrowdingSeriesPoint,
)


def test_response_serializes_a_full_row():
    resp = SectorCrowdingResponse(
        as_of=date(2026, 7, 24),
        benchmark="SPY",
        rows=[
            SectorCrowdingRow(
                ticker="SOXX",
                price=SectorCrowdingLeg(
                    name="price", raw=53.69, score=97.0, band="CROWDED"
                ),
                flow=SectorCrowdingLeg(
                    name="flow", raw=26.47, score=100.0, band="CROWDED"
                ),
                premium=SectorCrowdingLeg(
                    name="premium", raw=64.23, score=100.0, band="CROWDED"
                ),
                score=98.33,
                state="CROWDED",
                binding_leg="price",
                series=[
                    SectorCrowdingSeriesPoint(
                        obs_date=date(2026, 7, 24),
                        etf_cum_return=25.59,
                        bench_cum_return=4.98,
                        flow_aum_pct=26.47,
                    )
                ],
            )
        ],
    )
    dumped = resp.model_dump(mode="json")
    assert dumped["rows"][0]["state"] == "CROWDED"
    assert dumped["rows"][0]["binding_leg"] == "price"
    assert dumped["rows"][0]["series"][0]["obs_date"] == "2026-07-24"


def test_empty_response_is_valid():
    resp = SectorCrowdingResponse(as_of=None, benchmark="SPY", rows=[])
    assert resp.model_dump(mode="json")["rows"] == []


def test_absent_leg_serializes_as_nulls():
    leg = SectorCrowdingLeg(name="premium", raw=None, score=None, band=None)
    assert leg.model_dump(mode="json") == {
        "name": "premium",
        "raw": None,
        "score": None,
        "band": None,
    }


def test_route_maps_build_output_onto_the_response():
    """The three model tests above never execute the route body, so a typo in
    the `_leg` mapping (swapping `raw` and `score`, dropping `binding_leg`)
    ships green. Drive the real route with `build_sector_crowding` patched --
    a fake repo, no Postgres -- and assert the JSON the browser would get.
    """
    from unittest.mock import patch

    from fastapi.testclient import TestClient

    from uw_scan.api.deps import get_repo
    from uw_scan.api.server import create_app
    from uw_scan.reports.sector_crowding import (
        CrowdingLeg,
        CrowdingRow,
        CrowdingSeriesPoint,
    )

    row = CrowdingRow(
        ticker="SOXX",
        price=CrowdingLeg("price", 53.69, 97.0, "CROWDED"),
        flow=CrowdingLeg("flow", 26.47, 100.0, "CROWDED"),
        premium=CrowdingLeg("premium", 64.23, 100.0, "CROWDED"),
        score=98.33,
        state="CROWDED",
        binding_leg="price",
        series=[
            CrowdingSeriesPoint(
                obs_date=date(2026, 7, 24),
                etf_cum_return=25.59,
                bench_cum_return=4.98,
                flow_aum_pct=26.47,
            )
        ],
    )

    app = create_app()
    app.dependency_overrides[get_repo] = lambda: object()
    try:
        with patch(
            "uw_scan.reports.sector_crowding.build_sector_crowding",
            return_value=(date(2026, 7, 24), [row]),
        ):
            body = TestClient(app).get("/api/regime/sector-crowding").json()
    finally:
        app.dependency_overrides.clear()

    assert body["as_of"] == "2026-07-24"
    assert body["benchmark"] == "SPY"
    (got,) = body["rows"]
    assert got["ticker"] == "SOXX"
    assert got["state"] == "CROWDED"
    assert got["binding_leg"] == "price"
    # raw and score are both floats on every leg, so a swap is invisible
    # unless the values differ. They do.
    assert got["price"] == {
        "name": "price",
        "raw": 53.69,
        "score": 97.0,
        "band": "CROWDED",
    }
    assert got["series"][0]["flow_aum_pct"] == 26.47
```

Patching at `uw_scan.reports.sector_crowding.build_sector_crowding` rather than at the router is deliberate — the route imports the symbol *inside the function body*, so it resolves through the source module on every call and the patch takes effect. If Step 4's route is ever changed to a module-level import, this patch target must move to `uw_scan.api.routers.regime.build_sector_crowding`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_sector_crowding_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.api.models.sector_crowding'`

- [ ] **Step 3: Write the models**

Create `src/uw_scan/api/models/sector_crowding.py`:

```python
"""Pydantic response schemas for GET /regime/sector-crowding.

See docs/superpowers/plans/2026-07-26-sector-crowding-panel.md (Task 5).
"""

from __future__ import annotations

from datetime import date as _date
from typing import Literal

from pydantic import BaseModel

LegName = Literal["price", "flow", "premium"]
CrowdingBand = Literal["CROWDED", "WARM", "NORMAL", "COLD"]


class SectorCrowdingLeg(BaseModel):
    name: LegName
    raw: float | None = None
    score: float | None = None
    band: CrowdingBand | None = None


class SectorCrowdingSeriesPoint(BaseModel):
    obs_date: _date
    etf_cum_return: float
    bench_cum_return: float
    flow_aum_pct: float | None = None


class SectorCrowdingRow(BaseModel):
    ticker: str
    price: SectorCrowdingLeg
    flow: SectorCrowdingLeg
    premium: SectorCrowdingLeg
    score: float | None = None
    # Weakest leg's band, not the mean's -- the legs are conjunctive.
    state: CrowdingBand | None = None
    binding_leg: LegName | None = None
    series: list[SectorCrowdingSeriesPoint] = []


class SectorCrowdingResponse(BaseModel):
    as_of: _date | None = None
    benchmark: str
    rows: list[SectorCrowdingRow] = []
```

- [ ] **Step 4: Add the endpoint**

In `src/uw_scan/api/routers/regime.py`, add to the import block (alongside the existing `uw_scan.api.models.*` imports near line 20):

```python
from uw_scan.api.models.sector_crowding import (
    SectorCrowdingLeg,
    SectorCrowdingResponse,
    SectorCrowdingRow,
    SectorCrowdingSeriesPoint,
)
```

Add the route immediately after `get_dispersion` (which ends around line 341):

```python
@router.get("/sector-crowding", response_model=SectorCrowdingResponse)
def get_sector_crowding(
    repo: Annotated[Repository, Depends(get_repo)],
) -> SectorCrowdingResponse:
    """Sector-ETF crowding ranking (板块拥挤度).

    Three conjunctive legs -- relative return as a self-percentile, 1M
    flow/AUM on published bands, iv_rank spread vs SPY. STATE is the weakest
    leg's band; `binding_leg` names which leg is holding it down. Read-only,
    computed in-process over etf_flows_daily + etf_aum_cache + watchlist_card
    (all persisted by the 18:45 ET sector_crowding_capture job)."""
    from uw_scan.reports.sector_crowding import BENCHMARK, build_sector_crowding

    as_of, rows = build_sector_crowding(repo=repo)

    def _leg(leg) -> SectorCrowdingLeg:
        return SectorCrowdingLeg(
            name=leg.name, raw=leg.raw, score=leg.score, band=leg.band
        )

    return SectorCrowdingResponse(
        as_of=as_of,
        benchmark=BENCHMARK,
        rows=[
            SectorCrowdingRow(
                ticker=r.ticker,
                price=_leg(r.price),
                flow=_leg(r.flow),
                premium=_leg(r.premium),
                score=r.score,
                state=r.state,
                binding_leg=r.binding_leg,
                series=[
                    SectorCrowdingSeriesPoint(
                        obs_date=p.obs_date,
                        etf_cum_return=p.etf_cum_return,
                        bench_cum_return=p.bench_cum_return,
                        flow_aum_pct=p.flow_aum_pct,
                    )
                    for p in r.series
                ],
            )
            for r in rows
        ],
    )
```

- [ ] **Step 5: Run the API tests**

```bash
uv run pytest tests/unit/test_sector_crowding_api.py -v
uv run python -c "
from uw_scan.api.server import create_app
paths = create_app().openapi()['paths']
assert '/api/regime/sector-crowding' in paths, sorted(paths)[:5]
print('route registered OK')
"
```
Expected: 4 passed, route registered.

- [ ] **Step 6: Update the OpenAPI snapshot surgically**

`tests/integration/api/openapi.snapshot.json` is frozen in an older dump format. A full regen reorders keys and unescapes unicode across ~9.6k lines, burying the real change. Add only what is new.

`test_openapi_snapshot.py` asserts on **`paths` as well as `components.schemas`** (`sorted(current["paths"]) == sorted(expected["paths"])`), so adding the four schemas alone leaves the next step failing with "OpenAPI paths changed". Add the route entry too:

```bash
uv run python - <<'PY'
import json, pathlib
from uw_scan.api.server import create_app

ROUTE = "/api/regime/sector-crowding"
sp = pathlib.Path("tests/integration/api/openapi.snapshot.json")
snap = json.loads(sp.read_text())
live = create_app().openapi()

snap["paths"][ROUTE] = live["paths"][ROUTE]
for name in (
    "SectorCrowdingLeg",
    "SectorCrowdingSeriesPoint",
    "SectorCrowdingRow",
    "SectorCrowdingResponse",
):
    snap["components"]["schemas"][name] = live["components"]["schemas"][name]
sp.write_text(json.dumps(snap, indent=2, ensure_ascii=True, sort_keys=True) + "\n")
print("snapshot updated: 1 path + 4 schemas")
PY

git diff --stat tests/integration/api/openapi.snapshot.json
```

Expected: the diff touches only the added schema blocks. **If the diff is thousands of lines, discard it (`git checkout tests/integration/api/openapi.snapshot.json`) and retry** — a whole-file reorder means the dump args drifted.

- [ ] **Step 7: Run the snapshot test**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/api/models/sector_crowding.py \
        src/uw_scan/api/routers/regime.py \
        tests/unit/test_sector_crowding_api.py \
        tests/integration/api/openapi.snapshot.json
git commit -m "feat(api): GET /regime/sector-crowding"
```

---

### Task 6: Web panel

**Files:**
- Modify: `web/lib/regime/api.ts`
- Modify: `web/lib/types.ts` (surgical — see Step 5)
- Create: `web/lib/regime/useSectorCrowding.ts`
- Create: `web/components/regime/SectorCrowdingPanel.tsx`
- Create: `web/components/regime/SectorCrowdingCharts.tsx`
- Modify: `web/components/regime/MarketTideSubTab.tsx`
- Test: `web/tests/unit/sectorCrowding.test.tsx`

**Interfaces:**
- Consumes: the `GET /api/regime/sector-crowding` contract from Task 5.
- Produces: `useSectorCrowding()` hook and a default-exported `SectorCrowdingPanel`.

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/sectorCrowding.test.tsx`:

```tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SectorCrowdingPanel } from "@/components/regime/SectorCrowdingPanel";
import type { SectorCrowdingData } from "@/lib/regime/useSectorCrowding";

// Frozen from a live UW probe on 2026-07-24 plus warm-store iv_rank
// on 2026-07-25. See docs/research/2026-07-26-sector-crowding-probe.md.
const DATA: SectorCrowdingData = {
  as_of: "2026-07-24",
  benchmark: "SPY",
  rows: [
    {
      ticker: "SOXX",
      price: { name: "price", raw: 53.69, score: 97.0, band: "CROWDED" },
      flow: { name: "flow", raw: 26.47, score: 100.0, band: "CROWDED" },
      premium: { name: "premium", raw: 64.23, score: 100.0, band: "CROWDED" },
      score: 98.33,
      state: "CROWDED",
      binding_leg: "price",
      series: [
        { obs_date: "2026-07-23", etf_cum_return: 0, bench_cum_return: 0,
          flow_aum_pct: 20.1 },
        { obs_date: "2026-07-24", etf_cum_return: 25.59, bench_cum_return: 4.98,
          flow_aum_pct: 26.47 },
      ],
    },
    {
      ticker: "SMH",
      price: { name: "price", raw: 17.88, score: 46.0, band: "NORMAL" },
      flow: { name: "flow", raw: 1.91, score: 39.1, band: "NORMAL" },
      premium: { name: "premium", raw: 63.48, score: 100.0, band: "CROWDED" },
      score: 61.7,
      state: "NORMAL",
      // Weakest band is NORMAL (price 46.0 and flow 39.1 both sit there);
      // flow is the lower of the two, so it is the binding leg.
      binding_leg: "flow",
      series: [
        { obs_date: "2026-07-23", etf_cum_return: 0, bench_cum_return: 0,
          flow_aum_pct: 3.1 },
        { obs_date: "2026-07-24", etf_cum_return: 17.88, bench_cum_return: 4.98,
          flow_aum_pct: 1.91 },
      ],
    },
  ],
};

describe("SectorCrowdingPanel", () => {
  it("renders a row per ETF with its state", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    expect(screen.getByTestId("sector-crowding-row-SOXX")).toBeTruthy();
    expect(screen.getByTestId("sector-crowding-row-SMH")).toBeTruthy();
    expect(
      screen.getByTestId("sector-crowding-state-SOXX").textContent,
    ).toContain("CROWDED");
  });

  it("names the binding leg so a demotion is explainable", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    // SMH's premium leg is pinned at 100, but price (46th) and flow (39th)
    // are both only NORMAL -- the min-band rule demotes the row, and the UI
    // must name flow, the weaker of the two, as the constraint.
    const state = screen.getByTestId("sector-crowding-state-SMH");
    expect(state.textContent).toContain("NORMAL");
    expect(state.textContent).toContain("flow");
  });

  it("shows the raw value alongside its percentile", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    const cell = screen.getByTestId("sector-crowding-price-SOXX");
    expect(cell.textContent).toContain("53.7");
    expect(cell.textContent).toContain("97");
  });

  it("expands the drill-down charts on row click", () => {
    render(<SectorCrowdingPanel data={DATA} />);
    expect(screen.queryByTestId("sector-crowding-charts")).toBeNull();
    fireEvent.click(screen.getByTestId("sector-crowding-row-SOXX"));
    expect(screen.getByTestId("sector-crowding-charts")).toBeTruthy();
  });

  it("renders an empty state when there are no rows", () => {
    render(
      <SectorCrowdingPanel
        data={{ as_of: null, benchmark: "SPY", rows: [] }}
      />,
    );
    expect(screen.getByTestId("sector-crowding-empty")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run tests/unit/sectorCrowding.test.tsx`
Expected: FAIL — cannot resolve `@/components/regime/SectorCrowdingPanel`.

- [ ] **Step 3: Add the endpoint URL and the hook**

In `web/lib/regime/api.ts`, add to the `regimeApi` object (after the `dispersion` line):

```ts
  sector_crowding: () => `${API}/api/regime/sector-crowding`,
```

Create `web/lib/regime/useSectorCrowding.ts`. It aliases the generated schema names, which Step 5 inserts into `lib/types.ts` — so `npm run typecheck` will not pass until Step 5 lands. That is expected; vitest (Step 2) strips types without checking them, and Step 7 is the first gate that type-checks.

```ts
"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { MarketState } from "./useMarketHours";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

// Aliased from the generated contract, never hand-declared -- the convention
// every other regime hook follows (useCri.ts:7-12). Hand-writing a parallel
// shape here would silently drift from the API the first time a field changes,
// which is exactly the bug web/CLAUDE.md warns about.
export type SectorCrowdingLeg = components["schemas"]["SectorCrowdingLeg"];
export type SectorCrowdingSeriesPoint =
  components["schemas"]["SectorCrowdingSeriesPoint"];
export type SectorCrowdingRow = components["schemas"]["SectorCrowdingRow"];
export type SectorCrowdingData = components["schemas"]["SectorCrowdingResponse"];
export type CrowdingBand = NonNullable<SectorCrowdingRow["state"]>;
export type LegName = NonNullable<SectorCrowdingRow["binding_leg"]>;

const _extractTs = (d: SectorCrowdingData) => d.as_of ?? null;
const _noRetry = () => false;

export function useSectorCrowding(
  marketState: MarketState | null = null,
): UseSyncReturn<SectorCrowdingData> {
  // Captured once nightly at 18:45 ET; nothing moves intraday. Poll slowly
  // just to pick up the new session after the job runs.
  const config = {
    endpoint: regimeApi.sector_crowding(),
    interval: 900_000,
    hasPost: false,
    extractTimestamp: _extractTs,
    shouldRetry: _noRetry,
    retryIntervalMs: 5000,
    retryMethod: "GET" as const,
  };

  return useSyncHook<SectorCrowdingData>(config, marketState !== null);
}
```

- [ ] **Step 4: Write the panel and the charts**

Create `web/components/regime/SectorCrowdingCharts.tsx`:

```tsx
"use client";

import { linearScale, pathFromPoints, niceTicks } from "@/lib/svgChart";
import type { SectorCrowdingRow } from "@/lib/regime/useSectorCrowding";

const W = 520;
const H = 130;
const PAD = { top: 12, right: 44, bottom: 20, left: 8 };

const C = {
  etf: "var(--accent-vivid, #60a5fa)",
  bench: "var(--accent-vol, #a78bfa)",
  grid: "rgba(148,163,184,0.10)",
  zero: "var(--border-dim)",
  muted: "var(--text-muted)",
  warn: "var(--warning, #f59e0b)",
  neg: "var(--negative, #ef4444)",
};

/** Total-return panel: ETF vs benchmark, both rebased to 0% at window start. */
function ReturnPanel({
  row,
  benchmark,
}: {
  row: SectorCrowdingRow;
  benchmark: string;
}) {
  // `series` is optional in the generated contract (it defaults to [] server
  // side, so OpenAPI marks it not-required) -- hence the ?? []. And the length
  // guard is the same one FlowPanel has: build_sector_crowding never emits an
  // empty series today, but if it ever did, `last` below would be undefined
  // and the .toFixed() would take the whole tab down.
  const pts = row.series ?? [];
  if (!pts.length) return null;

  const values = pts.flatMap((p) => [p.etf_cum_return, p.bench_cum_return]);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  // linearScale takes two TUPLES -- (domain, range) -- not four scalars.
  const x = linearScale([0, pts.length - 1], [PAD.left, W - PAD.right]);
  const y = linearScale([lo, hi], [H - PAD.bottom, PAD.top]);

  const etfPath = pathFromPoints(
    pts.map((p, i) => [x(i), y(p.etf_cum_return)] as [number, number]),
  );
  const benchPath = pathFromPoints(
    pts.map((p, i) => [x(i), y(p.bench_cum_return)] as [number, number]),
  );
  const last = pts[pts.length - 1];

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      data-testid="sector-crowding-return-chart"
    >
      <title>{`${row.ticker} vs ${benchmark} total return, last 63 sessions`}</title>
      {niceTicks(lo, hi, 4).map((t) => (
        <g key={t}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            stroke={t === 0 ? C.zero : C.grid}
          />
          <text
            x={W - PAD.right + 4}
            y={y(t) + 3}
            fill={C.muted}
            fontSize={9}
            fontFamily="var(--font-mono)"
          >
            {t.toFixed(0)}%
          </text>
        </g>
      ))}
      <path d={benchPath} fill="none" stroke={C.bench} strokeWidth={1.25} />
      <path d={etfPath} fill="none" stroke={C.etf} strokeWidth={1.5} />
      <text x={PAD.left} y={10} fontSize={9} fontFamily="var(--font-mono)">
        <tspan fill={C.etf}>
          {row.ticker} {last.etf_cum_return.toFixed(1)}%
        </tspan>
        <tspan fill={C.bench}>
          {"   "}
          {benchmark} {last.bench_cum_return.toFixed(1)}%
        </tspan>
      </text>
    </svg>
  );
}

/** Flow/AUM bars with the tweet's 2% / 5% / 10% threshold lines. */
function FlowPanel({ row }: { row: SectorCrowdingRow }) {
  const pts = (row.series ?? []).filter((p) => p.flow_aum_pct != null);
  if (!pts.length) return null;

  const values = pts.map((p) => p.flow_aum_pct as number);
  const lo = Math.min(0, ...values);
  const hi = Math.max(10, ...values);
  const x = linearScale([0, pts.length - 1], [PAD.left, W - PAD.right]);
  const y = linearScale([lo, hi], [H - PAD.bottom, PAD.top]);
  const barW = Math.max(1, (W - PAD.right - PAD.left) / pts.length - 1);

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      data-testid="sector-crowding-flow-chart"
    >
      <title>{`${row.ticker} one-month net flow as a percent of AUM`}</title>
      {[2, 5, 10].map((t) => (
        <g key={t}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            stroke={t >= 10 ? C.neg : C.warn}
            strokeWidth={0.75}
            strokeDasharray="3 3"
          />
          <text
            x={W - PAD.right + 4}
            y={y(t) + 3}
            fill={C.muted}
            fontSize={9}
            fontFamily="var(--font-mono)"
          >
            {t}%
          </text>
        </g>
      ))}
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={y(0)}
        y2={y(0)}
        stroke={C.zero}
      />
      {pts.map((p, i) => {
        const v = p.flow_aum_pct as number;
        const top = Math.min(y(v), y(0));
        return (
          <rect
            key={p.obs_date}
            x={x(i) - barW / 2}
            y={top}
            width={barW}
            height={Math.abs(y(v) - y(0))}
            fill={v >= 0 ? C.etf : C.muted}
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

export function SectorCrowdingCharts({
  row,
  benchmark,
}: {
  row: SectorCrowdingRow;
  benchmark: string;
}) {
  return (
    <div
      data-testid="sector-crowding-charts"
      style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8 }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        Total return 3M
      </div>
      <ReturnPanel row={row} benchmark={benchmark} />
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        1M net flow / AUM
      </div>
      <FlowPanel row={row} />
    </div>
  );
}
```

Create `web/components/regime/SectorCrowdingPanel.tsx`:

```tsx
"use client";

// Fragment, not <>...</>: the map returns a fragment wrapping two <tr>s, and
// the key belongs on the returned element. React's jsx-key lint rule fails the
// shorthand, which cannot take a key.
import { Fragment, useState } from "react";
import { Layers } from "lucide-react";

import type {
  CrowdingBand,
  SectorCrowdingData,
  SectorCrowdingLeg,
  SectorCrowdingRow,
} from "@/lib/regime/useSectorCrowding";
import InfoTooltip from "./InfoTooltip";
import { SectorCrowdingCharts } from "./SectorCrowdingCharts";

const GUIDE =
  "Sector crowding (板块拥挤度), three conjunctive legs. PRICE = 63-session " +
  "return minus SPY's over the same sessions, shown raw with its own " +
  "trailing percentile. Absolute spread is not comparable across sectors — " +
  "the trailing SD of that spread runs from 3.1 (XLY) to 16.5 (XLE), so " +
  "ranking on it ranks volatility — and 63 sessions is ~3 months only where " +
  "UW's coverage is complete (~4.5 months for SOXX and IGV). " +
  "FLOW = 1M net flow / AUM on published bands (2% warm, 5% crowded, 10% " +
  "extreme); dividing by AUM already removes the size effect, so absolute " +
  "bands hold here. PREMIUM = iv_rank minus SPY's, standing in for the " +
  "source framework's NTM P/E, which needs constituent forward EPS we cannot " +
  "source. STATE is the WEAKEST leg's band, not the average — every leg we " +
  "have must fire for a row to read as crowded — and the arrow names the leg " +
  "holding it down. Two present legs is the minimum; below that the row is " +
  "blank rather than badged on a single reading.";

const BAND_COLOR: Record<CrowdingBand, string> = {
  CROWDED: "var(--negative, #ef4444)",
  WARM: "var(--warning, #f59e0b)",
  NORMAL: "var(--text-secondary, #94a3b8)",
  COLD: "var(--text-muted)",
};

const MONO = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
} as const;

// NOT lib/formatters.fmtSignedPct. That one takes a FRACTION and multiplies by
// 100 (formatters.ts:57), while every value on this panel is already in
// percentage points -- SOXX's price leg is 53.69, meaning 53.69%. Routing it
// through the shared helper renders "+5369.0%". Deliberately named differently
// so nobody "consolidates" the two. This is the scale trap web/CLAUDE.md
// flags: never trust scale, re-check the contract per tile.
function fmtPctPoints(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
}

function LegCell({
  leg,
  testId,
  showPercentile,
  suffix,
}: {
  leg: SectorCrowdingLeg;
  testId: string;
  showPercentile?: boolean;
  suffix?: string;
}) {
  const raw =
    leg.raw == null
      ? "—"
      : suffix === "pt"
        ? `${leg.raw >= 0 ? "+" : ""}${leg.raw.toFixed(0)}`
        : fmtPctPoints(leg.raw);
  return (
    <td style={{ ...MONO, textAlign: "right", padding: "3px 8px" }}>
      <span
        data-testid={testId}
        style={{ color: leg.band ? BAND_COLOR[leg.band] : "var(--text-muted)" }}
      >
        {raw}
        {showPercentile && leg.score != null && (
          <span style={{ color: "var(--text-muted)", fontSize: 9 }}>
            {` (${leg.score.toFixed(0)}ᵗʰ)`}
          </span>
        )}
      </span>
    </td>
  );
}

export function SectorCrowdingPanel({
  data,
}: {
  data: SectorCrowdingData | null;
}) {
  const [open, setOpen] = useState<string | null>(null);
  const rows = data?.rows ?? [];
  const benchmark = data?.benchmark ?? "SPY";

  if (!rows.length) {
    return (
      <div className="section" data-testid="sector-crowding-empty">
        <div className="section-header">
          <div className="section-title">
            <Layers size={14} />
            Sector Crowding
          </div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            ...MONO,
          }}
        >
          No sector crowding data — the 18:45 ET capture has not run yet.
        </div>
      </div>
    );
  }

  const th = {
    ...MONO,
    fontSize: 10,
    letterSpacing: 1.5,
    textTransform: "uppercase" as const,
    color: "var(--text-muted)",
    textAlign: "right" as const,
    padding: "3px 8px",
    fontWeight: 400,
  };

  return (
    <div className="section" data-testid="sector-crowding-panel">
      <div className="section-header">
        <div className="section-title">
          <Layers size={14} />
          Sector Crowding{data?.as_of ? ` — ${data.as_of}` : ""}
          <InfoTooltip
            text={GUIDE}
            triggerTestId="sector-crowding-tooltip-trigger"
            contentTestId="sector-crowding-tooltip-content"
          />
        </div>
      </div>
      <div className="section-body">
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ ...th, textAlign: "left" }}>ETF</th>
              <th style={th}>{`63d vs ${benchmark}`}</th>
              <th style={th}>1M Flow/AUM</th>
              <th style={th}>{`IVR Δ vs ${benchmark}`}</th>
              <th style={th}>Score</th>
              <th style={{ ...th, textAlign: "left" }}>State</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r: SectorCrowdingRow) => (
              <Fragment key={r.ticker}>
                <tr
                  data-testid={`sector-crowding-row-${r.ticker}`}
                  onClick={() =>
                    setOpen((cur) => (cur === r.ticker ? null : r.ticker))
                  }
                  style={{
                    cursor: "pointer",
                    borderTop: "1px solid var(--border-dim)",
                    background:
                      open === r.ticker ? "var(--bg-panel)" : "transparent",
                  }}
                >
                  <td style={{ ...MONO, padding: "3px 8px", fontWeight: 600 }}>
                    {r.ticker}
                  </td>
                  <LegCell
                    leg={r.price}
                    testId={`sector-crowding-price-${r.ticker}`}
                    showPercentile
                  />
                  <LegCell
                    leg={r.flow}
                    testId={`sector-crowding-flow-${r.ticker}`}
                  />
                  <LegCell
                    leg={r.premium}
                    testId={`sector-crowding-premium-${r.ticker}`}
                    suffix="pt"
                  />
                  <td
                    style={{ ...MONO, textAlign: "right", padding: "3px 8px" }}
                  >
                    {r.score == null ? "—" : r.score.toFixed(0)}
                  </td>
                  <td style={{ ...MONO, padding: "3px 8px" }}>
                    <span
                      data-testid={`sector-crowding-state-${r.ticker}`}
                      style={{
                        color: r.state
                          ? BAND_COLOR[r.state]
                          : "var(--text-muted)",
                      }}
                    >
                      {r.state ?? "—"}
                      {r.binding_leg && (
                        <span
                          style={{ color: "var(--text-muted)", fontSize: 9 }}
                        >
                          {` ← ${r.binding_leg}`}
                        </span>
                      )}
                    </span>
                  </td>
                </tr>
                {open === r.ticker && (
                  <tr>
                    <td colSpan={6} style={{ padding: 0 }}>
                      <SectorCrowdingCharts row={r} benchmark={benchmark} />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default SectorCrowdingPanel;
```

- [ ] **Step 5: Add the generated types surgically**

`web/lib/types.ts` is committed in 4-space-indent alphabetical order that the pinned `openapi-typescript` (7.13.0) no longer reproduces — `npm run gen:types` reorders all ~9.6k lines. **Do not run it.** Insert the four schemas in their alphabetical slot instead, and write via a script rather than the Edit tool (the Edit PostToolUse prettier hook reflows the 4-space generated file to 2-space):

```bash
cd web && python3 - <<'PY'
import pathlib, re

p = pathlib.Path("lib/types.ts")
src = p.read_text()

block = '''        SectorCrowdingLeg: {
            name: "price" | "flow" | "premium";
            raw?: number | null;
            score?: number | null;
            band?: "CROWDED" | "WARM" | "NORMAL" | "COLD" | null;
        };
        SectorCrowdingResponse: {
            as_of?: string | null;
            benchmark: string;
            rows?: components["schemas"]["SectorCrowdingRow"][];
        };
        SectorCrowdingRow: {
            ticker: string;
            price: components["schemas"]["SectorCrowdingLeg"];
            flow: components["schemas"]["SectorCrowdingLeg"];
            premium: components["schemas"]["SectorCrowdingLeg"];
            score?: number | null;
            state?: "CROWDED" | "WARM" | "NORMAL" | "COLD" | null;
            binding_leg?: "price" | "flow" | "premium" | null;
            series?: components["schemas"]["SectorCrowdingSeriesPoint"][];
        };
        SectorCrowdingSeriesPoint: {
            obs_date: string;
            etf_cum_return: number;
            bench_cum_return: number;
            flow_aum_pct?: number | null;
        };
'''

# Alphabetical slot: SectorCrowding* sorts after ScannerSignalHit and before
# SetupBlock (Sca < Sec < Set). Verified against lib/types.ts on 2026-07-26,
# where ScannerSignalHit is at :5891 and SetupBlock at :5915.
anchor = "        SetupBlock: {\n"
assert src.count(anchor) == 1, "SetupBlock anchor moved -- re-check the slot"
src = src.replace(anchor, block + anchor)
p.write_text(src)
print("inserted before SetupBlock")
PY

git diff --stat lib/types.ts
```

Expected: `lib/types.ts | 27 +++++++++++++` — a pure insertion, no deletions. **If the diff shows deletions or thousands of changed lines, discard it (`git checkout lib/types.ts`) and retry** — that means a full regen slipped in.

- [ ] **Step 6: Mount the panel**

In `web/components/regime/MarketTideSubTab.tsx`, add the imports:

```tsx
import { useSectorCrowding } from "@/lib/regime/useSectorCrowding";
import { SectorCrowdingPanel } from "./SectorCrowdingPanel";
```

Add the hook call next to the existing ones (after the `useTopNetImpact` line):

```tsx
  const { data: crowding } = useSectorCrowding(marketState ?? null);
```

and render it after the `{priorData && …}` block, still inside the `<>…</>` fragment:

```tsx
            <SectorCrowdingPanel data={crowding} />
```

- [ ] **Step 7: Run the web checks**

```bash
cd web
npx vitest run tests/unit/sectorCrowding.test.tsx
npm run typecheck
npm run lint
```
Expected: 5 vitest tests pass, typecheck clean, lint clean.

- [ ] **Step 8: Commit**

```bash
git add web/lib/regime/api.ts web/lib/regime/useSectorCrowding.ts \
        web/lib/types.ts \
        web/components/regime/SectorCrowdingPanel.tsx \
        web/components/regime/SectorCrowdingCharts.tsx \
        web/components/regime/MarketTideSubTab.tsx \
        web/tests/unit/sectorCrowding.test.tsx
git commit -m "feat(web): sector crowding panel on the Market Tide tab"
```

---

### Task 7: Research trace, end-to-end verification, changelog

The standing rule is that no research number counts unless it is reproducible from a saved trace. The probe that produced every frozen fixture in Tasks 1–6 has to land in the repo with its exact reproduce command.

**Files:**
- Create: `scripts/research/sector_crowding_probe.py`
- Create: `docs/research/2026-07-26-sector-crowding-probe.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `SECTOR_CROWDING_TICKERS`, `BENCHMARK` from Task 2; `normalize_etf_aum` from Task 1.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the probe script**

Create `scripts/research/sector_crowding_probe.py`. It hits UW directly rather than the warm store, so it stays runnable as an independent check on the pipeline:

```python
"""Sector-crowding probe: absolute vs per-ETF-percentile ranking.

Answers the question that set the scoring design: does the source framework's
absolute 3M-relative-return ranking measure crowding, or does it just measure
beta? Prints both rankings side by side plus the trailing SD of each ETF's
3M spread, and writes the full result set to JSON.

Reproduce:
    uv run python scripts/research/sector_crowding_probe.py

Writes: docs/research/2026-07-26-sector-crowding-probe.json
"""

from __future__ import annotations

import json
import pathlib
import statistics

import httpx

from uw_scan.config import Settings
from uw_scan.reports.sector_crowding import (
    BENCHMARK,
    FLOW_WINDOW,
    RETURN_WINDOW,
    SECTOR_CROWDING_TICKERS,
)
from uw_scan.storage.market_data import normalize_etf_aum

BASE = "https://api.unusualwhales.com"
OUT = pathlib.Path("docs/research/2026-07-26-sector-crowding-probe.json")


def _fetch_flows(client: httpx.Client, ticker: str) -> list[dict]:
    r = client.get(
        f"{BASE}/api/etfs/{ticker}/in-outflow",
        params={"start_date": "2025-07-01", "end_date": "2026-07-24"},
    )
    r.raise_for_status()
    # UW returns newest-first; flip to chronological.
    return sorted(r.json().get("data", []), key=lambda x: x["date"])


def _fetch_aum(client: httpx.Client, ticker: str) -> float:
    r = client.get(f"{BASE}/api/etfs/{ticker}/info")
    r.raise_for_status()
    return float(normalize_etf_aum(r.json()["data"]["aum"]))


def _ret(rows: list[dict], end: int, window: int) -> float | None:
    start = end - window
    if start < 0:
        return None
    a, b = float(rows[start]["close"]), float(rows[end]["close"])
    return (b / a - 1.0) * 100.0 if a else None


def _pct_rank(series: list[float], value: float) -> float:
    if not series:
        return float("nan")
    return 100.0 * sum(1 for s in series if s < value) / len(series)


def main() -> None:
    settings = Settings.from_env()
    headers = {
        "Authorization": f"Bearer {settings.api_key.get_secret_value()}",
        "Accept": "application/json",
    }
    out = []
    dropped_total = 0
    with httpx.Client(timeout=40, headers=headers) as client:
        bench_rows = _fetch_flows(client, BENCHMARK)
        bench_by_date = {r["date"]: r for r in bench_rows}
        bench_3m = _ret(bench_rows, len(bench_rows) - 1, RETURN_WINDOW)

        for ticker in SECTOR_CROWDING_TICKERS:
            try:
                raw = _fetch_flows(client, ticker)
                aum = _fetch_aum(client, ticker)
            except Exception as exc:  # noqa: BLE001 - probe script
                print(f"{ticker}: FAILED {exc}")
                continue

            # Inner-join on date, same as reports/sector_crowding.py. Indexing
            # `rows` and `bench` at the same position assumes both series carry
            # identical sessions; one dropped UW row shifts every later index
            # and silently compares different days. `dropped` should be 0 --
            # if it is not, the fixtures frozen from an earlier position-aligned
            # run are stale and must be re-derived from this output.
            rows = [r for r in raw if r["date"] in bench_by_date]
            bench = [bench_by_date[r["date"]] for r in rows]
            dropped = len(raw) - len(rows)
            dropped_total += dropped
            if dropped:
                print(f"{ticker}: dropped {dropped} unmatched session(s)")

            if len(rows) < RETURN_WINDOW + FLOW_WINDOW:
                print(f"{ticker}: only {len(rows)} sessions, skipping")
                continue

            last = len(rows) - 1
            rel = _ret(rows, last, RETURN_WINDOW) - bench_3m
            flow_1m = sum(
                float(r["change_prem"]) for r in rows[-FLOW_WINDOW:]
            )
            flow_aum = 100.0 * flow_1m / aum

            rel_hist = []
            for i in range(RETURN_WINDOW + FLOW_WINDOW, len(rows)):
                a, b = _ret(rows, i, RETURN_WINDOW), _ret(bench, i, RETURN_WINDOW)
                if a is not None and b is not None:
                    rel_hist.append(a - b)

            out.append(
                {
                    "ticker": ticker,
                    "aum_b": aum / 1e9,
                    "rel_3m": rel,
                    "rel_pctile": _pct_rank(rel_hist, rel),
                    "flow_aum": flow_aum,
                    "rel_hist_sd": statistics.pstdev(rel_hist) if rel_hist else 0.0,
                    "n_hist": len(rel_hist),
                    "dropped_sessions": dropped,
                }
            )

    print(f"\n{BENCHMARK} 3M return: {bench_3m:+.2f}%")
    print(f"unmatched sessions dropped across the universe: {dropped_total}\n")
    hdr = (
        f"{'ETF':<6}{'AUM$B':>8}{'3M vs SPY':>11}{'  pctile':>9}"
        f"{'1M flow/AUM':>13}{'  relSD':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in sorted(out, key=lambda x: -x["rel_3m"]):
        print(
            f"{r['ticker']:<6}{r['aum_b']:>8.1f}{r['rel_3m']:>+10.2f}%"
            f"{r['rel_pctile']:>8.0f}%{r['flow_aum']:>+12.2f}%"
            f"{r['rel_hist_sd']:>8.1f}"
        )

    print("\nABSOLUTE ranking:  ", " > ".join(
        r["ticker"] for r in sorted(out, key=lambda x: -x["rel_3m"])))
    print("PERCENTILE ranking:", " > ".join(
        r["ticker"] for r in sorted(out, key=lambda x: -x["rel_pctile"])))

    OUT.write_text(json.dumps(out, indent=2) + "\n")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the probe and save its output**

```bash
uv run python scripts/research/sector_crowding_probe.py \
  | tee /tmp/sector_crowding_probe.txt
```
Expected: a 14-row table and `saved -> docs/research/2026-07-26-sector-crowding-probe.json`.

Check the `unmatched sessions dropped across the universe:` line first. Every fixture quoted in Task 2 and Task 3 came from an earlier run of this probe that aligned by position, which is only equivalent to the date join above when that count is **0**. If it is non-zero, the frozen fixture values are stale — re-derive them from this run's JSON before continuing, and say so in the research note.

- [ ] **Step 3: Write the research note**

Create `docs/research/2026-07-26-sector-crowding-probe.md` with exactly this content. The only thing to fill in is the fenced table, pasted verbatim from `/tmp/sector_crowding_probe.txt` — **do not retype the numbers**, and if the live run disagrees with a figure quoted in the prose below, correct the prose to match the run and say so.

````markdown
# Sector crowding probe — absolute vs per-ETF percentile

**Date:** 2026-07-26 · **Data as of:** 2026-07-24 (UW), iv_rank 2026-07-25
**Source framework:** https://x.com/bitfool1/status/2079479920162734401 (板块拥挤度, 2026-07-21)

**Reproduce:**

```bash
uv run python scripts/research/sector_crowding_probe.py
```

Writes the full result set to `docs/research/2026-07-26-sector-crowding-probe.json`.

## The framework as stated

Three legs, conjunctive — 三者同时出现，才算真正拥挤:

1. 3-month return relative to SPY
2. 1-month net flow ÷ AUM, banded `<2%` normal / `2–5%` warm / `>5%` crowded / `>10%` extreme
3. NTM P/E level and expansion

## Result

```
<paste /tmp/sector_crowding_probe.txt verbatim>
```

## Finding: leg 1 cannot use the absolute spread

The trailing SD of the 3M SPY-relative spread ranges from 3.1 (XLY) to 16.5
(XLE). Ranking the universe on the raw spread therefore ranks volatility, not
crowding — a high-beta sector tops the table in any up-tape.

The two rankings genuinely disagree:

- absolute: `SOXX > SMH > XLK`
- self-percentile: `XLF > SOXX > XLV`

XLF at +3.14% is its own 99th percentile and the absolute method buries it at
rank 5. SMH at +17.88% is only its own 46th and the absolute method promotes it
to rank 2.

So leg 1 scores on the ETF's own trailing percentile. Leg 2 keeps the source
framework's absolute bands, because dividing by AUM already removes the size
effect — that normalization is what makes those thresholds comparable across
funds in the first place.

## Data limitations found

- **UW `aum` is mixed-unit.** Billions for the 12 SPDR sector ETFs
  (`XLK` → `180.775642`), raw dollars for everything else
  (`SOXX` → `45064294868`). Both landed unconverted in `etf_aum_cache`.
  Fixed in this change by `normalize_etf_aum`, applied on read and write.
  The watchlist card's `aum` is a different read path
  (`scan_runs.aggregates` → raw `etf_info` payload) and is still unnormalized.
- **ARKK has no flow data.** `/api/etfs/ARKK/in-outflow` returns 0 rows
  (verified 2026-07-24), so it is excluded from the universe.
- **UW in-outflow coverage is uneven, and position-alignment is unsafe.**
  Over 2025-07-01 → 2026-07-24 the 11 SPDR sector ETFs and SPY each return
  267 sessions, but `SOXX`/`IGV` return 238 and `SMH` returns 204 — and each
  of the three carries one session SPY does not have. An earlier draft of this
  probe aligned the ETF and benchmark series **by list position**, which for
  those three compares different dates at every index. Date-joining moves the
  numbers materially:

  | ETF | 3M rel (position) | 3M rel (date-join) | pctile (position) | pctile (date-join) |
  |---|---|---|---|---|
  | SOXX | +50.26% | **+53.69%** | 96% | **97%** |
  | SMH | +12.67% | **+17.88%** | 18% | **46%** |
  | IGV | −1.18% | **−7.32%** | 86% | **69%** |

  The 11 SPDRs are unaffected (identical to 2 dp). `reports/sector_crowding.py`
  and this probe both inner-join on `obs_date`; the probe prints the dropped
  count so a future regression is visible.
- **A 63-row window is not 3 calendar months for every ETF.** Because of those
  same coverage gaps, the last 63 observations span 92 calendar days for SPY,
  XLK, XLY and SMH but **135 days for SOXX and IGV** (measured 2026-07-26). The
  date join makes each ETF's spread an honest ETF-minus-SPY comparison over its
  own available sessions, and leg 1 is scored against that ETF's own trailing
  history, so the *score* is self-consistent. The *raw* number labelled "3M" is
  not directly comparable across tickers. Moving leg 1 to a calendar-anchored
  window would fix the label; it is deliberately out of scope here and is
  flagged as an open question.

## Leg 3: substituted, not implemented as stated

ETF NTM P/E needs Σ(weight × constituent forward EPS). UW exposes no forward
estimates and massive/Polygon fundamentals are trailing. The source framework's
own screenshot shows SOXX NTM P/E behind a "🔒 Upgrade" gate, so it is not
sourceable on our tier at any effort.

Substituted: **iv_rank spread vs SPY**. Free from `watchlist_card`, and it asks
the same question — is the crowd paying up — about convexity instead of
earnings.

## Deferred: trailing P/E from holdings

Buildable, not built. It would need a constituent-weights table, a fundamentals
sweep over ~500 names against the 86 currently in `massive_fundamentals`, and a
nightly job to keep both fresh.

Worse than the cost, it would be **trailing**, not forward. Trailing P/E *falls*
while a sector gets more crowded during an earnings upcycle — the precise case
the source framework uses the forward measure to catch. A trailing proxy would
read "cheapening" exactly when the leg is supposed to fire, which is worse than
having no third leg. Revisit only with a real forward-estimates source.
````

- [ ] **Step 4: Verify end to end**

Be precise about what this does and does not prove. `CLAUDE.md` asks that smoke tests run the real worker path rather than a side-channel script — but this feature has **no API enqueue leg**: the capture is a cron, and the endpoint is a read. There is nothing to enqueue. So the end-to-end evidence is split in two, and neither half is optional:

- **Cron wiring** is covered by the registration test from Task 4 Step 7, not by anything below. The command in this step calls the job function directly through the scheduler's own `_repo` / `_uw_client` / `_external_api_recorder` helpers. That exercises the real DB, the real UW client, and the real telemetry recorder — but it does **not** go through APScheduler, so on its own it says nothing about whether the job would ever fire.
- **Data → API → UI** is what the rest of this step checks: real job writes real rows, the running API reads them, the running page renders them.

Start the stack, run the job, then look at the page:

```bash
bash scripts/migrate.sh          # no-op; migrations are idempotent
bash scripts/dev.sh              # web :3001, API :8400, workers
```

In a second shell, run the capture job through the worker's own entry point:

```bash
uv run python -c "
from uw_scan.config import Settings
from uw_scan.worker.scheduler import _repo, _uw_client, _external_api_recorder
from uw_scan.worker.jobs.sector_crowding_capture import sector_crowding_capture
s = Settings.from_env()
with _external_api_recorder(s) as rec:
    with _uw_client(s, telemetry_recorder=rec, job_name='sector_crowding_capture') as uw:
        with _repo(s) as repo:
            print('inserted', sector_crowding_capture(repo=repo, client=uw, settings=s))
"
```

Confirm the rows landed:

```bash
psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" \
  -c "SELECT ticker, count(*), max(obs_date) FROM uw_scan.etf_flows_daily
      WHERE ticker NOT IN ('GLD','IAU','GLDM') GROUP BY 1 ORDER BY 1"
```
Expected: 15 tickers, ~275 rows each.

Then check the endpoint and the page:

```bash
curl -s http://127.0.0.1:8400/api/regime/sector-crowding | head -c 600
```

Open http://localhost:3001/regime/tide, confirm the Sector Crowding table renders with states and `← leg` annotations, and click a row to confirm both SVG panels appear. Screenshot to `output/playwright/sector-crowding-tide-tab.png`.

- [ ] **Step 5: Run the full local gate**

Reproduce what CI's `lint + unit` job runs — it is eight steps, not two, and a green `ruff check` alone has passed a red CI before. Copied from `.github/workflows/ci.yml:26-70`; run them in this order and stop at the first red:

```bash
python3 scripts/release/version_sync_check.py
uv run ruff check src/ tests/ scripts/          # NOT `ruff check .`
uv run python scripts/_lint_except.py src       # Guardrail 2: except handlers
uv run python scripts/check_no_yahoo.py
uv run python scripts/check_runtime_assets.py
! grep -rE 'class _Fake(Cursor|Connection)' tests/integration/
! grep -rE '"\|".join\(' src/
! grep -rE 'from tests' src/
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -n auto
```

Then the web job (`ci.yml:82-119`) — note it includes `build`, which catches RSC/client-boundary errors that `typecheck` does not:

```bash
cd web && npm run typecheck && npm run test && npm run lint && npm run build && cd ..
```

Expected: everything green. Do not proceed with anything red.

**`ruff format` is deliberately absent.** It is not in CI, the Makefile, any script, or a pre-commit hook, and several existing `src/` files do not satisfy it. Running it would reformat code to a style the rest of the repo does not follow. `ruff check` is the real gate.

- [ ] **Step 6: Add the changelog entry**

The changelog rides this branch; it does not get a follow-up PR. Under `## [Unreleased]` in `CHANGELOG.md`:

```markdown
### Added
- **Sector crowding panel** on the `/regime` Market Tide tab — ranks 14 sector
  ETFs on three conjunctive legs (3M relative return as a self-percentile, 1M
  flow/AUM on published bands, iv_rank spread vs SPY), with a drill-down to
  total-return and flow/AUM charts. State is the weakest present leg's band,
  so every leg must fire for a row to read as crowded (two legs minimum, else
  the row is unscored), and the binding leg is named. New
  nightly `sector_crowding_capture` job at 18:45 ET extends the existing
  `etf_flows_daily` capture to the sector universe; the score is computed at
  read time, so there is no new table. Framework adapted from
  https://x.com/bitfool1/status/2079479920162734401 — its third leg (NTM P/E)
  is not sourceable on our tier and is replaced by the IV-rank spread.

### Fixed
- **ETF AUM unit normalization.** UW returns `aum` in billions for the 12 SPDR
  sector ETFs and raw dollars for everything else; both landed unconverted in
  `etf_aum_cache`, making every flow/AUM ratio 1e9 too small for the SPDRs.
  Normalized on read as well as write, which repairs the existing rows with no
  backfill, and on the `pipeline` cache-miss return so hit and miss agree.
  Known and untouched: the watchlist card's `aum` comes from
  `scan_runs.aggregates` / the raw `etf_info` payload rather than this cache,
  so `CardGrid.sizeValue()` still mis-sorts the SPDR sector ETFs.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/research/sector_crowding_probe.py \
        docs/research/2026-07-26-sector-crowding-probe.md \
        docs/research/2026-07-26-sector-crowding-probe.json \
        docs/superpowers/plans/2026-07-26-sector-crowding-panel.md \
        CHANGELOG.md
git commit -m "docs(regime): sector crowding research trace and changelog"
```

---

## Done When

- Every command in Task 7 Step 5 is green — the whole CI `lint + unit` sequence, not just ruff and pytest.
- `sector_crowding_capture` is asserted into the scheduler by Task 4 Step 7's registration test, and a real run inserts ~15 tickers into `etf_flows_daily`.
- Re-running the capture job the same day inserts 0 new rows (deterministic `as_of`), and the `scan_runs` row ends at `ok`/`fail`, never `running`.
- `GET /api/regime/sector-crowding` returns ranked rows with states and binding legs.
- The panel renders on `/regime/tide` and expands both SVG charts on click.
- `etf_aum_cache` reads come back in raw dollars for every ticker.
- The probe reports `unmatched sessions dropped: 0`, or the fixtures were re-derived from a run that did not.
- The research trace and its reproduce command are committed.

## Notes for the Implementer

- **The panel measures positioning crowding, not option-flow tide.** It sits on the Market Tide tab because that is where it was asked for, not because it is the same family as net premium. If it reads wrong there once visible, moving it to its own regime subtab is a small change — the panel takes only `data`.
- **Do not add a kill-switch setting** for the capture job unless asked. 30 UW calls a night against a 120k budget does not warrant one, and each ticker already fails independently.
- **Do not persist the score.** It is a pure function of already-persisted inputs; nothing is lost by recomputing. If the drill-down ever feels slow, cache at the API layer before reaching for a table.
