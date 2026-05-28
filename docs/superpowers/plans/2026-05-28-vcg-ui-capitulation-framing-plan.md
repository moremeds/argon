# VCG UI Capitulation-Framing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reframe VCG stress states in the regime UI from implicit "warning" framing to data-grounded "capitulation marker" framing, by surfacing realized forward SPX returns alongside each PANIC / RISK_OFF / EDR day.

**Architecture:** Backend-additive only — extend `/api/regime/vcg-validation` response with three forward-return columns per stress day (`fwd_5d_pct`, `fwd_20d_pct`, `fwd_60d_pct`) plus an aggregate summary keyed by interpretation. Frontend-additive only — three small surface changes (table columns, summary line above table, Signal-Detail context row when current state is stress) plus one tooltip update. No changes to VCG signal math, classifier, or `COMPOSITE_VERSION`.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, Pydantic v2, FastAPI; Next.js 16, React 19, TypeScript, Vitest.

> **Standing-rule reminder (CLAUDE.md):** "Never commit without an explicit user request." The `Commit (milestone)` steps in this plan assume the user has already authorized milestone commits for this work. **If the user has not explicitly said "commit each milestone" for this plan, pause at the first commit step and ask** — staging-only is fine until then. Drafted-then-paused is the default; do not auto-commit.

---

## Design Context (read before starting)

This plan implements the recommendation from the 2026-05-28 VCG forward-return probe series. The probe writeup lives in session-private research and is **not committed to `main`** as of this plan's authoring; the headline numbers and methodology are summarized inline below so the plan is self-contained. If the engineer wants the full probe note, ask the user — do not chase a dangling reference.

**Empirical findings driving the UI change** (from `run_id=31`, 4,710 days, 18.5yr):

| Interpretation | n | mean fwd 5d % | mean fwd 20d % | mean fwd 60d % | win% 20d |
|---|---|---|---|---|---|
| PANIC | 83 | +0.2 | **+2.88** | +2.29 | 53.0 |
| RISK_OFF | 133 | +0.2 | +0.15 | **+3.04** | 67.7 |
| NORMAL | 2,070 | — | +0.80 | +2.51 | 66.1 |

**Implication:** VCG's stress states mark capitulation, not impending downside. Current UI red-pill framing implies "warning" — empirically false. The fix is **information addition** (add forward-return data so users see what historically happened), not redesign (no pill-color or layout change).

**Why this is safe to ship:**
- No change to VCG math, no `COMPOSITE_VERSION` bump.
- Contract change is purely additive (optional fields), no breaking change for any existing client.
- All new data is derived from already-persisted `regime_backtest_daily` and `vol_index_daily` rows — no new ingestion.

**BOUNCE is out of scope** (n=5, dominated by 2008 GFC; including it would mislead). Current `stress_history` `Literal` excludes BOUNCE — keep it that way.

---

## File Structure

**Architecture clarification (post-Pass-1):** the existing handler at `src/uw_scan/api/routers/regime_validation.py:288-348` does **Python-side iteration**, not SQL aggregation. The `regime_backtest_daily` table stores stress fields inside a JSONB `payload` column (see `migrations/057_regime_backtest_results.sql`); they are NOT first-class columns. SPX close lives in `vol_index_daily` with `WHERE symbol = 'SPX'` (column `close`, not `spx_close`). Forward-return computation therefore goes in a pure-function card util consumed by the handler — not into a new storage aggregate query.

| File | Action | Responsibility |
|---|---|---|
| `src/uw_scan/api/models/regime_validation.py` | Modify | Add 3 optional fwd-return fields to `VcgStressHistoryEntry`; add `VcgStressHistorySummary` + `VcgStressHistorySummaryRow` models; add `stress_history_summary` field to `VcgValidationResponse` |
| `src/uw_scan/cards/regime_forward_returns.py` | **Create** | Pure functions: `attach_forward_returns(entries, spx_series)` + `summarize_stress_returns(entries)`. No DB access. |
| `src/uw_scan/api/routers/regime_validation.py` | Modify | Load SPX series via `VolIndexRepository`, pass through card util, attach to response. Existing Python iteration over `daily` is preserved. |
| `src/uw_scan/storage/vol_index_repository.py` | Modify (only if needed) | Add `fetch_close_series(symbol)` returning the full date-ordered list, if `fetch_multi_history` proves insufficient |
| `tests/unit/api/test_regime_validation_models.py` | Modify/Create | Test new optional fields default to None; test summary contract |
| `tests/unit/cards/test_regime_forward_returns.py` | Create | Unit-test the pure card functions with synthetic SPX series + entries |
| `tests/integration/api/test_regime_validation_endpoint.py` | Modify | Endpoint includes `stress_history_summary`; stress rows include the three fwd fields |
| `tests/snapshots/openapi/vcg-validation.json` *(actual path found at exec time)* | Regenerate | After model change |
| `web/lib/types.ts` | Regenerate | After OpenAPI change via `npm run gen:types` |
| `web/components/regime/vcg/VcgStressHistoryTable.tsx` | Modify | Add 3 columns: `+5d %`, `+20d %`, `+60d %` with sign-based coloring; render `—` for null |
| `web/components/regime/vcg/VcgStressHistorySection.tsx` | Modify | Add summary line above the foldable section header showing aggregate stats |
| `web/components/regime/VcgSubTab.tsx` | Modify | Add "Historical (5d / 20d / 60d)" row to Signal Detail card when current `interpretation` is PANIC/RISK_OFF/EDR |
| `web/components/regime/vcg/InterpretationPill.tsx` *(or wherever the pill lives — confirm at exec time)* | Modify | Add hover tooltip with one-line forward-return context per interpretation |
| `web/tests/unit/VcgStressHistoryTable.test.tsx` | Modify | Add tests for new columns + null handling |
| `web/tests/unit/VcgStressHistorySection.test.tsx` | Modify/Create | Test summary line rendering |
| `web/tests/unit/VcgSubTab.test.tsx` | Modify/Create | Test Signal Detail historical row appears only in stress states |

---

## Tasks

### Task 0: Set up worktree and branch

**Files:** none yet.

- [ ] **Step 1: Create worktree**

Run from `/Users/chenxi/projects/unusual-whales`:
```bash
git fetch origin
git worktree add -b feat/vcg-ui-capitulation-framing .worktrees/vcg-ui-capitulation-framing origin/main
cd .worktrees/vcg-ui-capitulation-framing
```
Expected: new directory `.worktrees/vcg-ui-capitulation-framing/`; `git branch --show-current` prints `feat/vcg-ui-capitulation-framing`.

- [ ] **Step 2: Verify environment**

```bash
uv sync --extra postgres
cd web && npm install && cd ..
```
Expected: both succeed without errors. **All subsequent tasks run from inside the worktree.**

- [ ] **Step 3: Confirm baseline tests pass before changing anything**

```bash
uv run pytest tests/unit -q 2>&1 | tail -5
cd web && npm run typecheck && npm run test -- --run 2>&1 | tail -10 ; cd ..
```
Expected: green. If anything is red on origin/main, stop and surface it — do not start implementation on a red baseline.

---

### Task 1: Extend Pydantic models (additive only)

**Files:**
- Modify: `src/uw_scan/api/models/regime_validation.py`
- Test: `tests/unit/api/test_regime_validation_models.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create or extend `tests/unit/api/test_regime_validation_models.py`:
```python
"""Contract tests for the regime-validation Pydantic models."""
from uw_scan.api.models.regime_validation import (
    VcgStressHistoryEntry,
    VcgStressHistorySummary,
    VcgStressHistorySummaryRow,
    VcgValidationResponse,
)


def test_stress_history_entry_forward_return_fields_default_none() -> None:
    entry = VcgStressHistoryEntry(date="2020-03-16", interpretation="PANIC")
    assert entry.fwd_5d_pct is None
    assert entry.fwd_20d_pct is None
    assert entry.fwd_60d_pct is None


def test_stress_history_summary_row_shape() -> None:
    row = VcgStressHistorySummaryRow(
        interpretation="PANIC",
        n=83,
        mean_fwd_5d_pct=0.20,
        mean_fwd_20d_pct=2.88,
        mean_fwd_60d_pct=2.29,
        winrate_20d_pct=53.0,
        winrate_60d_pct=41.0,
    )
    assert row.n == 83
    assert row.mean_fwd_20d_pct == 2.88


def test_validation_response_summary_optional() -> None:
    """stress_history_summary must default to None so we don't break
    existing clients before backfill."""
    resp = VcgValidationResponse(
        backtest_md="",
        n_days=0,
        composite_version="2",
        credit_proxy="HY_OAS",
        interpretation_distribution=[],
        named_crash_window=[],
    )
    assert resp.stress_history_summary is None
```

- [ ] **Step 2: Run test — verify it fails**

```bash
uv run pytest tests/unit/api/test_regime_validation_models.py -v
```
Expected: ImportError on `VcgStressHistorySummary` / `VcgStressHistorySummaryRow`.

- [ ] **Step 3: Implement model additions**

Edit `src/uw_scan/api/models/regime_validation.py`:

a) Extend `VcgStressHistoryEntry` (after line 84 `vvix_percentile_rank`):
```python
    fwd_5d_pct: float | None = None
    fwd_20d_pct: float | None = None
    fwd_60d_pct: float | None = None
```

b) Add new types **before** `VcgValidationResponse`:
```python
class VcgStressHistorySummaryRow(BaseModel):
    """Per-interpretation aggregate of realized forward SPX returns
    across all stress days in the backtest run."""

    interpretation: Literal["PANIC", "RISK_OFF", "EDR"]
    n: int
    mean_fwd_5d_pct: float | None = None
    mean_fwd_20d_pct: float | None = None
    mean_fwd_60d_pct: float | None = None
    winrate_20d_pct: float | None = None  # % of fwd_20d_pct > 0
    winrate_60d_pct: float | None = None


class VcgStressHistorySummary(BaseModel):
    """Aggregate forward-return stats for the stress_history table."""

    by_interpretation: list[VcgStressHistorySummaryRow]
```

c) Add to `VcgValidationResponse` (after `stress_history` line 96):
```python
    stress_history_summary: VcgStressHistorySummary | None = None
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run pytest tests/unit/api/test_regime_validation_models.py -v
```
Expected: PASS.

- [ ] **Step 5: Sanity-check existing tests still pass**

```bash
uv run pytest tests/unit -q 2>&1 | tail -3
```
Expected: green.

- [ ] **Step 6: Commit (milestone)**

```bash
git add src/uw_scan/api/models/regime_validation.py tests/unit/api/test_regime_validation_models.py
git commit -m "feat(vcg-ui): add forward-return fields + summary contract"
```

---

### Task 2: Pure-function card util for forward returns + summary

**Why a card util, not a storage aggregate (verified 2026-05-28 against the real code):**

The existing `/api/regime/vcg-validation` handler at `src/uw_scan/api/routers/regime_validation.py:288-348` does **Python-side iteration** over the daily rows returned by `RegimeBacktestRepository.fetch_daily_for_run(run_id)`. The `regime_backtest_daily` table (per `migrations/057_regime_backtest_results.sql`) has columns `(run_id, trade_date, score, level, payload JSONB)` — fields like `pi_panic`, `vix`, `vvix`, `vix_percentile_rank`, `vvix_percentile_rank` live **inside the `payload` JSONB**, not as first-class columns. The `level` column holds the interpretation string. SPX close lives in `vol_index_daily` filtered by `WHERE symbol = 'SPX'`, column `close`. There is no `spx_close` column.

So forward-return computation goes in a pure-function card util at `src/uw_scan/cards/regime_forward_returns.py` (matching the project's "share util via cards/" feedback rule). The handler loads SPX series once via `VolIndexRepository.fetch_multi_history(["SPX"], 9000)`, passes the daily list + SPX series to the card util, and gets enriched entries + a summary back. No new SQL; no new storage module.

**Files:**
- Create: `src/uw_scan/cards/regime_forward_returns.py`
- Test: `tests/unit/cards/test_regime_forward_returns.py`

- [ ] **Step 1: Sanity-check the SPX data exists**

```bash
uv run python -c "from uw_scan.config import get_settings; from psycopg import connect; s = get_settings(); c = connect(s.postgres_dsn); cur = c.cursor(); cur.execute(\"SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM uw_scan.vol_index_daily WHERE symbol='SPX'\"); print(cur.fetchone())"
```
Expected: a tuple like `(4710, datetime.date(2007, 11, 26), datetime.date(2026, 5, 27))` — i.e., SPX history spans the backtest period. If the count is implausibly small or the dates don't cover `run_id=31`'s span, **stop and surface to the user before continuing**.

- [ ] **Step 2: Write the failing unit test**

Create `tests/unit/cards/test_regime_forward_returns.py`:
```python
"""Pure-function tests for regime_forward_returns.

Verifies the date-aligned LEAD-by-index logic on synthetic data (no DB).
"""
from __future__ import annotations

from datetime import date

from uw_scan.cards.regime_forward_returns import (
    attach_forward_returns,
    summarize_stress_returns,
)


def _spx_series(rows: list[tuple[str, float]]) -> list[tuple[date, float]]:
    return [(date.fromisoformat(d), c) for d, c in rows]


def test_attach_forward_returns_basic_lead_logic() -> None:
    spx = _spx_series(
        [
            ("2026-01-02", 100.0),  # entry
            ("2026-01-03", 101.0),
            ("2026-01-04", 102.0),
            ("2026-01-05", 103.0),
            ("2026-01-06", 104.0),
            ("2026-01-07", 105.0),  # +5d from entry
        ]
    )
    entries = [{"date": "2026-01-02", "interpretation": "PANIC"}]

    enriched = attach_forward_returns(entries, spx, horizons=(5,))

    assert enriched[0]["fwd_5d_pct"] == 5.0  # (105 - 100) / 100 * 100


def test_attach_forward_returns_null_at_tail() -> None:
    """When entry date is within `horizon` of series tail, fwd return is None."""
    spx = _spx_series([("2026-05-25", 100.0), ("2026-05-26", 101.0), ("2026-05-27", 102.0)])
    entries = [{"date": "2026-05-27", "interpretation": "PANIC"}]

    enriched = attach_forward_returns(entries, spx, horizons=(5,))

    assert enriched[0]["fwd_5d_pct"] is None


def test_attach_forward_returns_handles_missing_spx_date() -> None:
    """If the entry date isn't in the SPX series (holiday alignment), return None."""
    spx = _spx_series([("2026-01-02", 100.0), ("2026-01-09", 101.0)])
    entries = [{"date": "2026-01-05", "interpretation": "PANIC"}]  # holiday

    enriched = attach_forward_returns(entries, spx, horizons=(5,))

    assert enriched[0]["fwd_5d_pct"] is None


def test_summarize_stress_returns_groups_by_interpretation() -> None:
    enriched = [
        {"interpretation": "PANIC", "fwd_20d_pct": 5.0, "fwd_60d_pct": 8.0},
        {"interpretation": "PANIC", "fwd_20d_pct": -3.0, "fwd_60d_pct": 2.0},
        {"interpretation": "PANIC", "fwd_20d_pct": None, "fwd_60d_pct": None},
        {"interpretation": "RISK_OFF", "fwd_20d_pct": 1.0, "fwd_60d_pct": 4.0},
    ]
    summary = summarize_stress_returns(enriched)
    by = {row["interpretation"]: row for row in summary}

    # PANIC: n=3 total, but means / winrates skip None
    assert by["PANIC"]["n"] == 3
    assert by["PANIC"]["mean_fwd_20d_pct"] == 1.0  # (5 + -3) / 2
    assert by["PANIC"]["winrate_20d_pct"] == 50.0  # 1 of 2 non-null positive
    # RISK_OFF: n=1
    assert by["RISK_OFF"]["n"] == 1
    assert by["RISK_OFF"]["mean_fwd_60d_pct"] == 4.0


def test_summarize_stress_returns_handles_all_null_horizon() -> None:
    """If every entry has None for a horizon, mean is None (not 0, not NaN)."""
    enriched = [
        {"interpretation": "PANIC", "fwd_20d_pct": None, "fwd_60d_pct": None},
    ]
    summary = summarize_stress_returns(enriched)
    assert summary[0]["mean_fwd_20d_pct"] is None
    assert summary[0]["winrate_20d_pct"] is None


def test_attach_forward_returns_rejects_unsorted_spx_series() -> None:
    """Defensive — silent wrong fwd returns from a refactored SQL
    dropping ORDER BY is worse than a loud crash."""
    import pytest

    unsorted = _spx_series(
        [("2026-01-03", 101.0), ("2026-01-02", 100.0)]  # out of order
    )
    with pytest.raises(ValueError, match="sorted ascending"):
        attach_forward_returns([{"date": "2026-01-02", "interpretation": "PANIC"}], unsorted)


def test_attach_forward_returns_empty_entries() -> None:
    """Empty entry list returns empty list (no error)."""
    spx = _spx_series([("2026-01-02", 100.0)])
    assert attach_forward_returns([], spx) == []
```

- [ ] **Step 3: Run — verify failure**

```bash
uv run pytest tests/unit/cards/test_regime_forward_returns.py -v
```
Expected: ImportError (module doesn't exist yet).

- [ ] **Step 4: Implement the card util**

Create `src/uw_scan/cards/regime_forward_returns.py`:
```python
"""Pure helpers for projecting realized forward SPX returns onto VCG
stress-history entries, and aggregating the result by interpretation.

No DB access. The handler at api/routers/regime_validation.py loads the
SPX series and the daily entries; this module enriches and summarizes.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Iterable

# Default horizons match the UI columns (+5d, +20d, +60d).
DEFAULT_HORIZONS: tuple[int, ...] = (5, 20, 60)


def attach_forward_returns(
    entries: list[dict[str, Any]],
    spx_series: list[tuple[date, float]],
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[dict[str, Any]]:
    """Return a new list of entry dicts, each with `fwd_{H}d_pct` keys.

    spx_series must be sorted ascending by trade_date. Each entry's date
    is matched against the series; the close N trading days later is
    looked up by index. Missing dates or tail-overhangs produce None.

    Returns a shallow-copied list of dicts so the input is not mutated.

    Raises ValueError if spx_series is not sorted ascending — defensive
    check against a future SQL refactor dropping the ORDER BY in
    VolIndexRepository.fetch_multi_history. Silent wrong fwd returns
    are worse than a loud crash.
    """
    for i in range(len(spx_series) - 1):
        if spx_series[i][0] > spx_series[i + 1][0]:
            raise ValueError(
                f"spx_series must be sorted ascending by date; "
                f"index {i} ({spx_series[i][0]}) > index {i+1} ({spx_series[i+1][0]})"
            )
    date_to_index = {d: i for i, (d, _) in enumerate(spx_series)}
    closes = [c for _, c in spx_series]
    horizons = tuple(horizons)

    out: list[dict[str, Any]] = []
    for entry in entries:
        enriched = dict(entry)  # shallow copy; do not mutate input
        entry_date = _parse_date(entry.get("date"))
        idx = date_to_index.get(entry_date) if entry_date else None
        for h in horizons:
            key = f"fwd_{h}d_pct"
            if idx is None:
                enriched[key] = None
                continue
            future_idx = idx + h
            if future_idx >= len(closes):
                enriched[key] = None
                continue
            base = closes[idx]
            future = closes[future_idx]
            if base is None or future is None or base == 0:
                enriched[key] = None
                continue
            enriched[key] = (future - base) / base * 100.0
        out.append(enriched)
    return out


def summarize_stress_returns(
    enriched_entries: list[dict[str, Any]],
    horizons: Iterable[int] = DEFAULT_HORIZONS,
) -> list[dict[str, Any]]:
    """Group entries by `interpretation`; for each group return
    {interpretation, n, mean_fwd_{H}d_pct, winrate_{H}d_pct} for
    H in horizons.

    `n` is the total entry count (including those with None fwd values).
    `mean_*` and `winrate_*` skip None values; if every value for a
    horizon is None, the aggregate is None (not 0, not NaN).
    """
    horizons = tuple(horizons)
    groups: dict[str, list[dict[str, Any]]] = {}
    for entry in enriched_entries:
        interp = entry.get("interpretation")
        if not interp:
            continue
        groups.setdefault(interp, []).append(entry)

    out: list[dict[str, Any]] = []
    for interp in sorted(groups):
        rows = groups[interp]
        row: dict[str, Any] = {"interpretation": interp, "n": len(rows)}
        for h in horizons:
            key = f"fwd_{h}d_pct"
            values = [r[key] for r in rows if r.get(key) is not None]
            row[f"mean_{key}"] = (
                sum(values) / len(values) if values else None
            )
            if values:
                wins = sum(1 for v in values if v > 0)
                row[f"winrate_{h}d_pct"] = wins / len(values) * 100.0
            else:
                row[f"winrate_{h}d_pct"] = None
        out.append(row)
    return out


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None
```

> **Important — interpretation Literal narrowness:** the existing `VcgStressHistoryEntry.interpretation` is `Literal["PANIC", "RISK_OFF", "EDR"]`. `summarize_stress_returns` accepts arbitrary string interpretations but in production the handler only ever passes these three (the handler at `regime_validation.py:327` filters `stress_levels = {"PANIC", "RISK_OFF", "EDR"}`). Do NOT change the Literal in Task 1 to include BOUNCE — that is explicitly out of scope per the design context.

- [ ] **Step 5: Verify tests pass**

```bash
uv run pytest tests/unit/cards/test_regime_forward_returns.py -v
```
Expected: green.

- [ ] **Step 6: Sanity-check the broader unit suite still passes**

```bash
uv run pytest tests/unit -q 2>&1 | tail -3
```
Expected: green. (No existing test should reference `regime_forward_returns` yet.)

- [ ] **Step 7: Commit (milestone — pending user authorization per top-of-plan note)**

```bash
git add src/uw_scan/cards/regime_forward_returns.py tests/unit/cards/test_regime_forward_returns.py
git commit -m "feat(vcg-ui): pure card util for forward-return projection + summary"
```

---

### Task 3: Wire the card util into the endpoint handler

**Files:**
- Modify: `src/uw_scan/api/routers/regime_validation.py` (handler at lines 288-348)
- Test: `tests/integration/api/test_regime_validation_endpoint.py` (or whatever the existing endpoint test file is — confirm at exec time)

- [ ] **Step 1: Read the existing handler and identify call sites**

```bash
grep -n "VcgValidationResponse\|stress_history\b\|fetch_daily_for_run" src/uw_scan/api/routers/regime_validation.py
```
Expected: confirms the handler structure — `rb.find_latest_run("vcg")` → `rb.fetch_daily_for_run(run["id"])` → Python-iter → `VcgValidationResponse(...)`.

- [ ] **Step 2: Write the failing endpoint integration test**

Add to the existing endpoint test file (or create `tests/integration/api/test_regime_validation_endpoint.py` if absent):
```python
def test_vcg_validation_includes_stress_history_summary(test_client) -> None:
    """The endpoint must expose stress_history_summary and per-entry
    forward-return fields. Values may be null (no SPX data, recent
    tail) — structural check only."""
    resp = test_client.get("/api/regime/vcg-validation")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Summary structure
    assert "stress_history_summary" in body
    summary = body["stress_history_summary"]
    assert summary is not None
    assert "by_interpretation" in summary

    # Per-entry structure
    sh = body["stress_history"]
    assert sh, "expected non-empty stress_history in seeded backtest"
    first = sh[0]
    for key in ("fwd_5d_pct", "fwd_20d_pct", "fwd_60d_pct"):
        assert key in first, f"missing {key} on stress_history entry"


def test_vcg_validation_summary_values_match_published_probes(test_client) -> None:
    """Numeric check against the published probe note values.
    Gated by env flag — only runs when the local DB has the production
    backtest (run_id=31, 4,710 days). CI seeds do not satisfy this."""
    import os
    if os.getenv("VCG_FULL_BACKTEST_AVAILABLE") != "1":
        import pytest
        pytest.skip("requires production backtest fixture (set VCG_FULL_BACKTEST_AVAILABLE=1 locally)")
    import math

    resp = test_client.get("/api/regime/vcg-validation")
    body = resp.json()
    by = {row["interpretation"]: row for row in body["stress_history_summary"]["by_interpretation"]}

    # Published probe values (docs/research/regime/vcg-forward-return-probes-2026-05-28.md):
    assert by["PANIC"]["n"] == 83
    assert math.isclose(by["PANIC"]["mean_fwd_20d_pct"], 2.88, abs_tol=0.05)
    assert by["RISK_OFF"]["n"] == 133
    assert math.isclose(by["RISK_OFF"]["mean_fwd_60d_pct"], 3.04, abs_tol=0.05)
```

> **Why split into two tests:** the structural test runs on any fixture (including CI-seeded small datasets); the numeric-match test is gated behind `VCG_FULL_BACKTEST_AVAILABLE=1` so the brittle probe values don't fail CI on small seeds. Local devs running against the production warm-store get the full check.

- [ ] **Step 3: Run — verify structural test fails**

```bash
uv run pytest tests/integration/api/test_regime_validation_endpoint.py -v -k stress_history_summary
```
Expected: KeyError or schema-validation failure (the response model doesn't have `stress_history_summary` populated yet, and entries lack fwd keys).

- [ ] **Step 4: Wire the card util into the handler**

Edit `src/uw_scan/api/routers/regime_validation.py`.

**Step 4a — add imports at module top** (NOT inside the function body):
```python
from uw_scan.api.models.regime_validation import (
    ...,  # existing imports
    VcgStressHistorySummary,
    VcgStressHistorySummaryRow,
)
from uw_scan.cards.regime_forward_returns import (
    attach_forward_returns,
    summarize_stress_returns,
)
from uw_scan.storage.vol_index_repository import VolIndexRepository
```

**Step 4b — add enrichment block** after the existing `stress_history` Python loop ends (around line 348) but before the `return VcgValidationResponse(...)` (line 349):

```python
# Forward-return enrichment. Skip the SPX load entirely if no stress
# days were emitted in this run — common for runs early in calibration
# work, no point spending the query.
stress_history_summary: VcgStressHistorySummary | None = None
if stress_history:
    # VolIndexRepository instantiation follows the existing pattern at
    # line 289 (`RegimeBacktestRepository(repo.conn, schema=repo._schema)`).
    # `repo._schema` is technically private but every router in this file
    # accesses it the same way; do not break the convention here.
    vix_repo = VolIndexRepository(repo.conn, schema=repo._schema)
    # 9000-day window covers the full 18.5yr backtest with headroom.
    spx_rows = vix_repo.fetch_multi_history(["SPX"], 9000).get("SPX", [])
    spx_series = [(r["trade_date"], r["close"]) for r in spx_rows]

    # Convert VcgStressHistoryEntry → plain dicts for the (intentionally
    # Pydantic-naive) card util, enrich, then rebind stress_history to
    # the typed-reconstructed list. Original entries get GC'd.
    entry_dicts = [e.model_dump() for e in stress_history]
    enriched_dicts = attach_forward_returns(entry_dicts, spx_series)
    stress_history = [VcgStressHistoryEntry(**d) for d in enriched_dicts]

    # summarize_stress_returns inherits the handler's stress filter
    # (PANIC/RISK_OFF/EDR) implicitly via VcgStressHistorySummaryRow's
    # `Literal["PANIC","RISK_OFF","EDR"]` — passing any other
    # interpretation here would raise Pydantic ValidationError, which
    # is the right behavior if the stress set ever expands.
    summary_rows = summarize_stress_returns(enriched_dicts)
    stress_history_summary = VcgStressHistorySummary(
        by_interpretation=[
            VcgStressHistorySummaryRow(
                interpretation=row["interpretation"],
                n=row["n"],
                mean_fwd_5d_pct=row.get("mean_fwd_5d_pct"),
                mean_fwd_20d_pct=row.get("mean_fwd_20d_pct"),
                mean_fwd_60d_pct=row.get("mean_fwd_60d_pct"),
                winrate_20d_pct=row.get("winrate_20d_pct"),
                winrate_60d_pct=row.get("winrate_60d_pct"),
            )
            for row in summary_rows
        ]
    )
```

**Step 4c — pass through to response:** Add `stress_history_summary=stress_history_summary` to the `VcgValidationResponse(...)` call. The field is `Optional` per Task 1; when `stress_history` is empty, it stays `None` and the frontend conditional renders nothing.

> **Why convert to dicts and back:** the card util is pure-Python on dicts for testability (no Pydantic dependency in `cards/`). The cost is two `model_dump()` + `VcgStressHistoryEntry(**d)` round-trips per request; on a stress_history of ~265 entries this is sub-millisecond. If profiling later shows this is hot, refactor the card util to take Pydantic models directly.

- [ ] **Step 5: Verify structural test passes**

```bash
uv run pytest tests/integration/api/test_regime_validation_endpoint.py -v -k stress_history_summary
```
Expected: PASS.

- [ ] **Step 6: Verify numeric-match test passes against production DB**

```bash
VCG_FULL_BACKTEST_AVAILABLE=1 uv run pytest tests/integration/api/test_regime_validation_endpoint.py -v -k summary_values_match
```
Expected: PASS if you're running against the warm-store with `run_id=31`. If you're on a CI-seeded small DB, the test will SKIP (which is intentional).

If the numeric check fails with mean_fwd_20d_pct deviating from 2.88 by more than 0.05, **stop**: re-derive the probe value from a direct SQL query before adjusting the test. Do not loosen the tolerance.

- [ ] **Step 7: Sanity-check broader integration suite still passes**

```bash
uv run pytest tests/integration -q -m "not live and not slow" 2>&1 | tail -3
```
Expected: green.

- [ ] **Step 8: Commit (milestone — pending user authorization)**

```bash
git add src/uw_scan/api/routers/regime_validation.py tests/integration/api/test_regime_validation_endpoint.py
git commit -m "feat(vcg-ui): expose stress_history_summary + fwd returns on /vcg-validation"
```

---

### Task 4: Regenerate OpenAPI snapshot + frontend types

**Files:**
- Regenerate: OpenAPI snapshot (path varies — see snapshot test)
- Regenerate: `web/lib/types.ts`

- [ ] **Step 1: Find snapshot test path**

```bash
grep -rn "openapi" tests/unit/ tests/integration/ 2>/dev/null | grep -i snapshot | head -5
```

- [ ] **Step 2: Run snapshot test in update mode**

If the project uses `pytest --snapshot-update`:
```bash
uv run pytest tests/<snapshot-path> --snapshot-update -v
```
Otherwise, run the regeneration script referenced by the existing snapshot test (look for a `regenerate` or `--update` flag).

- [ ] **Step 3: Regenerate web types**

```bash
cd web && npm run gen:types && cd ..
git diff --stat web/lib/types.ts
```
Expected: diff shows `VcgStressHistoryEntry` gained 3 fields and `VcgValidationResponse` gained `stress_history_summary`. Verify no unrelated drift.

- [ ] **Step 4: Verify frontend typecheck still passes**

```bash
cd web && npm run typecheck 2>&1 | tail -3
```
Expected: green (existing call sites are unaffected because the new fields are optional).

- [ ] **Step 5: Commit (milestone)**

```bash
git add tests/<snapshot-path>/* web/lib/types.ts
git commit -m "chore(openapi): regenerate snapshot + types for stress-history forward returns"
```

---

### Task 5: Add forward-return columns to `VcgStressHistoryTable`

**Files:**
- Modify: `web/components/regime/vcg/VcgStressHistoryTable.tsx`
- Modify: `web/tests/unit/VcgStressHistoryTable.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `web/tests/unit/VcgStressHistoryTable.test.tsx`:
```typescript
it("renders +5d / +20d / +60d forward-return cells with sign coloring", () => {
  const rows: Row[] = [
    {
      date: "2020-03-16",
      interpretation: "PANIC",
      score: -3.2, vcg_adj: -3.2, pi_panic: 1.5, sign_ok: true,
      vix: 80, vvix: 130,
      vix_percentile_rank: 0.99, vvix_percentile_rank: 0.99,
      fwd_5d_pct: -8.5,
      fwd_20d_pct: 15.3,
      fwd_60d_pct: 22.1,
    },
  ];
  const { container } = render(<VcgStressHistoryTable rows={rows} />);
  const row = container.querySelector('[data-testid="vcg-stress-row-2020-03-16"]');
  const cells = row?.querySelectorAll("td");
  // Columns 9, 10, 11 are +5d / +20d / +60d
  expect(cells?.[9]?.textContent).toMatch(/-8\.5/);
  expect(cells?.[10]?.textContent).toMatch(/\+15\.3/);
  expect(cells?.[11]?.textContent).toMatch(/\+22\.1/);
  // Negative fwd_5d should be red; positive should be green
  expect((cells?.[9] as HTMLElement).style.color).toContain("var(--fault");
  expect((cells?.[10] as HTMLElement).style.color).toContain("var(--ok");
});

it("renders '—' for null forward-return cells (recent days)", () => {
  const rows: Row[] = [
    {
      date: "2026-05-27",
      interpretation: "RISK_OFF",
      score: -1.9, vcg_adj: -1.9, pi_panic: 0, sign_ok: true,
      vix: 25, vvix: 110,
      vix_percentile_rank: 0.7, vvix_percentile_rank: 0.6,
      fwd_5d_pct: 0.5,
      fwd_20d_pct: null,
      fwd_60d_pct: null,
    },
  ];
  const { container } = render(<VcgStressHistoryTable rows={rows} />);
  const row = container.querySelector('[data-testid="vcg-stress-row-2026-05-27"]');
  const cells = row?.querySelectorAll("td");
  expect(cells?.[10]?.textContent).toBe("—");
  expect(cells?.[11]?.textContent).toBe("—");
});
```

- [ ] **Step 2: Run — verify fail**

```bash
cd web && npm run test -- --run VcgStressHistoryTable 2>&1 | tail -15 ; cd ..
```
Expected: assertions on cells[9..11] fail because the columns don't exist yet.

- [ ] **Step 3: Read existing component and add 3 columns**

Open `web/components/regime/vcg/VcgStressHistoryTable.tsx`. Locate the `<thead>` and add three columns at the end of the header row:
```tsx
<th
  scope="col"
  onClick={() => toggleSort("fwd_5d_pct")}
  style={{ cursor: "pointer", textAlign: "right" }}
>
  +5d %
</th>
<th
  scope="col"
  onClick={() => toggleSort("fwd_20d_pct")}
  style={{ cursor: "pointer", textAlign: "right" }}
>
  +20d %
</th>
<th
  scope="col"
  onClick={() => toggleSort("fwd_60d_pct")}
  style={{ cursor: "pointer", textAlign: "right" }}
>
  +60d %
</th>
```

Add a helper inside the component (or import from a shared util):
```tsx
function renderFwdCell(value: number | null | undefined) {
  if (value == null || Number.isNaN(value)) {
    return <td style={{ textAlign: "right", color: "var(--text-muted)" }}>—</td>;
  }
  const color = value > 0 ? "var(--ok-fg)" : value < 0 ? "var(--fault-fg)" : "var(--text-primary)";
  const sign = value > 0 ? "+" : "";
  return (
    <td style={{ textAlign: "right", color, fontFamily: "var(--font-mono)" }}>
      {sign}
      {value.toFixed(1)}
    </td>
  );
}
```

In the `<tbody>` row mapping, append after the existing cells:
```tsx
{renderFwdCell(row.fwd_5d_pct)}
{renderFwdCell(row.fwd_20d_pct)}
{renderFwdCell(row.fwd_60d_pct)}
```

> If the existing component uses different CSS-var names for green/red (e.g. `--text-positive` instead of `--ok-fg`), use the existing convention — `grep` the file for current sign-coloring before adding.

- [ ] **Step 4: Verify tests pass**

```bash
cd web && npm run test -- --run VcgStressHistoryTable 2>&1 | tail -5 ; cd ..
```
Expected: green.

- [ ] **Step 5: Commit (milestone)**

```bash
git add web/components/regime/vcg/VcgStressHistoryTable.tsx web/tests/unit/VcgStressHistoryTable.test.tsx
git commit -m "feat(vcg-ui): add forward-return columns to stress-history table"
```

---

### Task 6: Add summary line above the stress-history section

**Files:**
- Modify: `web/components/regime/vcg/VcgStressHistorySection.tsx`
- Create/modify: `web/tests/unit/VcgStressHistorySection.test.tsx`

- [ ] **Step 1: Write failing test**

Create `web/tests/unit/VcgStressHistorySection.test.tsx` (or extend if it exists):
```typescript
/* @vitest-environment jsdom */
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import VcgStressHistorySection from "@/components/regime/vcg/VcgStressHistorySection";

const FIXTURE = {
  backtest_md: "",
  n_days: 4710,
  composite_version: "2",
  credit_proxy: "HY_OAS",
  interpretation_distribution: [],
  named_crash_window: [],
  stress_history: [],
  stress_history_summary: {
    by_interpretation: [
      {
        interpretation: "PANIC",
        n: 83,
        mean_fwd_5d_pct: 0.2,
        mean_fwd_20d_pct: 2.88,
        mean_fwd_60d_pct: 2.29,
        winrate_20d_pct: 53.0,
        winrate_60d_pct: 41.0,
      },
      {
        interpretation: "RISK_OFF",
        n: 133,
        mean_fwd_5d_pct: 0.2,
        mean_fwd_20d_pct: 0.15,
        mean_fwd_60d_pct: 3.04,
        winrate_20d_pct: 67.7,
        winrate_60d_pct: 74.4,
      },
    ],
  },
};

beforeEach(() => {
  globalThis.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => FIXTURE,
  } as Response);
});

describe("VcgStressHistorySection summary line", () => {
  it("renders aggregate stats for PANIC and RISK_OFF", async () => {
    render(<VcgStressHistorySection />);
    await waitFor(() => {
      expect(screen.getByTestId("vcg-stress-summary")).toBeDefined();
    });
    const summary = screen.getByTestId("vcg-stress-summary");
    expect(summary.textContent).toMatch(/83 historical PANIC/);
    expect(summary.textContent).toMatch(/\+2\.88/);
    expect(summary.textContent).toMatch(/133 RISK_OFF/);
    expect(summary.textContent).toMatch(/\+3\.04/);
  });
});
```

- [ ] **Step 2: Run — verify fail**

```bash
cd web && npm run test -- --run VcgStressHistorySection 2>&1 | tail -10 ; cd ..
```
Expected: `vcg-stress-summary` testid not found.

- [ ] **Step 3: Add the summary line**

Edit `web/components/regime/vcg/VcgStressHistorySection.tsx`. Before the `<button ... section-header>` element (around line 58), add:

```tsx
{data?.stress_history_summary && (
  <div
    data-testid="vcg-stress-summary"
    style={{
      fontSize: "11px",
      fontFamily: "var(--font-mono)",
      color: "var(--text-secondary)",
      marginBottom: "8px",
      lineHeight: 1.5,
    }}
  >
    {data.stress_history_summary.by_interpretation.map((row) => (
      <div key={row.interpretation}>
        Across {row.n} historical {row.interpretation} events, mean 20d
        forward SPX return was{" "}
        <span
          style={{
            color:
              (row.mean_fwd_20d_pct ?? 0) > 0
                ? "var(--ok-fg)"
                : "var(--fault-fg)",
          }}
        >
          {(row.mean_fwd_20d_pct ?? 0) >= 0 ? "+" : ""}
          {row.mean_fwd_20d_pct?.toFixed(2)}%
        </span>{" "}
        ({row.winrate_20d_pct?.toFixed(0)}% positive).
      </div>
    ))}
  </div>
)}
```

> Filter out EDR from the rendered summary lines if it adds noise (the user's design called out PANIC + RISK_OFF specifically). Add `.filter(r => r.interpretation !== "EDR")` if so.

- [ ] **Step 4: Verify test passes**

```bash
cd web && npm run test -- --run VcgStressHistorySection 2>&1 | tail -5 ; cd ..
```
Expected: green.

- [ ] **Step 5: Commit (milestone)**

```bash
git add web/components/regime/vcg/VcgStressHistorySection.tsx web/tests/unit/VcgStressHistorySection.test.tsx
git commit -m "feat(vcg-ui): summary line above stress-history table"
```

---

### Task 7: Historical-context row in Signal Detail card

**Architecture discovery (Pass 6, 2026-05-28):** `VcgSubTab.tsx` uses `useVcg()` (hits `/api/regime/vcg` — current state) and renders `<VcgStressHistorySection />` (which independently fetches `/api/regime/vcg-validation`). The two components do NOT share the validation response. The "Signal Detail historical row" requires the validation summary, so we have three options:

- **Option A (faithful to original design):** VcgSubTab adds a second `useEffect` to fetch `/api/regime/vcg-validation`'s `stress_history_summary`. Cost: extra HTTP roundtrip per page load. Benefit: row appears in Signal Detail card next to current state — strongest UX signal when user is currently in stress.
- **Option B (lift state up):** Move VcgStressHistorySection's fetch into VcgSubTab and pass the response down. Cost: bigger refactor of an already-shipped component. Benefit: one fetch, one source of truth.
- **Option C (MVP — recommended):** **Skip the Signal Detail row.** The summary line in StressHistorySection (Task 6) already conveys the historical context. The row was an upsell for "you're in a stress state RIGHT NOW" — but the user can see the same data by scrolling to the stress-history section. Cost: weaker UX coupling. Benefit: zero architectural change, ships faster.

> **Recommendation:** Default to Option C for the first ship. Re-evaluate Option A in a follow-up PR if user testing shows people miss the historical context when in a stress state.

**If Option C is chosen, SKIP this entire task — proceed to Task 8.** If Option A is chosen, follow the steps below.

**Files (Option A only):**
- Modify: `web/components/regime/VcgSubTab.tsx`
- Create/modify: `web/tests/unit/VcgSubTab.test.tsx`

- [ ] **Step 1: Read existing Signal Detail layout**

```bash
grep -n "Signal Detail\|signal-detail\|interpretation" web/components/regime/VcgSubTab.tsx | head -20
```

Identify the current `interpretation` source. Per `useVcg.ts`, it lives in the `VcgResponse` from `/api/regime/vcg`. The new row should appear only when `currentInterpretation in {"PANIC", "RISK_OFF", "EDR"}`. The summary data needs a separate fetch — add a `useEffect` similar to the one in `VcgStressHistorySection.tsx:28-51` (fetch `regimeApi.vcgValidation()`, store in state).

- [ ] **Step 2: Write failing test**

Create `web/tests/unit/VcgSubTab.test.tsx`:
```typescript
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

// Import as default or named depending on file's actual export
import VcgSubTab from "@/components/regime/VcgSubTab";

const summaryFixture = {
  by_interpretation: [
    {
      interpretation: "PANIC",
      n: 83,
      mean_fwd_5d_pct: 0.2,
      mean_fwd_20d_pct: 2.88,
      mean_fwd_60d_pct: 2.29,
      winrate_20d_pct: 53.0,
      winrate_60d_pct: 41.0,
    },
  ],
};

describe("VcgSubTab Signal Detail historical context", () => {
  it("renders historical-fwd row when current interpretation is PANIC", () => {
    render(
      <VcgSubTab
        currentState={{ interpretation: "PANIC", /* other required props */ }}
        stressHistorySummary={summaryFixture}
      />
    );
    const row = screen.queryByTestId("vcg-signal-detail-historical");
    expect(row).not.toBeNull();
    expect(row?.textContent).toMatch(/\+0\.2.*\+2\.88.*\+2\.29/);
    expect(row?.textContent).toMatch(/n=83/);
  });

  it("does NOT render historical-fwd row when current interpretation is NORMAL", () => {
    render(
      <VcgSubTab
        currentState={{ interpretation: "NORMAL" }}
        stressHistorySummary={summaryFixture}
      />
    );
    expect(screen.queryByTestId("vcg-signal-detail-historical")).toBeNull();
  });
});
```

> **Calibrate the test props to the actual `VcgSubTab` prop shape during execution** — the component is a real page wiring, and the prop names will differ. The two behaviors that must hold are: (1) row appears for PANIC/RISK_OFF/EDR, (2) row hides for NORMAL/SUPPRESSED.

- [ ] **Step 3: Add the historical-context row**

In `VcgSubTab.tsx`, in the Signal Detail card JSX, find where current `interpretation` is rendered. Just below it, conditionally render:

```tsx
{(["PANIC", "RISK_OFF", "EDR"].includes(currentInterpretation) &&
  stressSummary?.by_interpretation.find(
    (r) => r.interpretation === currentInterpretation,
  )) && (() => {
  const row = stressSummary!.by_interpretation.find(
    (r) => r.interpretation === currentInterpretation,
  )!;
  const fmt = (v: number | null | undefined) =>
    v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
  return (
    <div
      data-testid="vcg-signal-detail-historical"
      style={{
        marginTop: "4px",
        fontSize: "11px",
        color: "var(--text-secondary)",
        fontFamily: "var(--font-mono)",
      }}
    >
      Historical fwd (5d / 20d / 60d): {fmt(row.mean_fwd_5d_pct)} /{" "}
      {fmt(row.mean_fwd_20d_pct)} / {fmt(row.mean_fwd_60d_pct)} (n={row.n},{" "}
      {row.winrate_20d_pct?.toFixed(0)}% pos 20d)
    </div>
  );
})()}
```

- [ ] **Step 4: Verify test passes**

```bash
cd web && npm run test -- --run VcgSubTab 2>&1 | tail -5 ; cd ..
```
Expected: green.

- [ ] **Step 5: Commit (milestone)**

```bash
git add web/components/regime/VcgSubTab.tsx web/tests/unit/VcgSubTab.test.tsx
git commit -m "feat(vcg-ui): historical-fwd row in Signal Detail card"
```

---

### Task 8: Interpretation-pill tooltip

**Files:**
- Locate: `grep -rn "interpretation\b.*PANIC\|pill" web/components/regime/ | head` to find the pill component
- Modify: that pill component
- Modify/Create: unit test for the pill

- [ ] **Step 1: Find the existing pill component**

```bash
grep -rln "PANIC\|RISK_OFF" web/components/regime/ | head -5
grep -n "interpretation" web/components/regime/vcg/VcgStressHistoryTable.tsx | head -5
```

The pill is rendered inline in the table; identify whether it's a dedicated component or inline JSX with a `getInterpretationStyle()` helper. If inline, factor a tiny `InterpretationPill.tsx` component **only if** the same JSX is duplicated in 3+ places. Otherwise, modify in place.

- [ ] **Step 2: Write failing test**

Add to the appropriate test file (or extend `VcgStressHistoryTable.test.tsx`):
```typescript
it("interpretation pill has tooltip with historical forward-return summary", () => {
  const rows: Row[] = [
    {
      date: "2020-03-16",
      interpretation: "PANIC",
      score: -3.2, vcg_adj: -3.2, pi_panic: 1.5, sign_ok: true,
      vix: 80, vvix: 130,
      vix_percentile_rank: 0.99, vvix_percentile_rank: 0.99,
      fwd_5d_pct: -8.5, fwd_20d_pct: 15.3, fwd_60d_pct: 22.1,
    },
  ];
  const { container } = render(<VcgStressHistoryTable rows={rows} />);
  const pill = container.querySelector('[data-testid="interpretation-pill-PANIC"]');
  expect(pill?.getAttribute("title")).toMatch(/capitulation/i);
  expect(pill?.getAttribute("title")).toMatch(/\+2\.88|forward 20d/);
});
```

- [ ] **Step 3: Run — verify fail**

```bash
cd web && npm run test -- --run interpretation-pill 2>&1 | tail -5 ; cd ..
```
Expected: testid missing or title attribute missing.

- [ ] **Step 4: Add tooltip + testid to pill**

Update the pill rendering. Replace the existing pill `<span>` with:
```tsx
<span
  data-testid={`interpretation-pill-${row.interpretation}`}
  title={
    row.interpretation === "PANIC"
      ? "PANIC — acute stress capitulation marker. Historical 20d forward SPX: +2.88% mean (n=83, 53% positive). Marks capitulation moments, not future drawdowns."
      : row.interpretation === "RISK_OFF"
      ? "RISK_OFF — sustained vol-complex stress. Historical 60d forward SPX: +3.04% mean (n=133, 74% positive). Indistinguishable from baseline drift at 60d."
      : row.interpretation === "EDR"
      ? "EDR — elevated daily risk. Subset of stress days that did not meet PANIC/RISK_OFF thresholds."
      : undefined
  }
  style={existingPillStyle}
>
  {label}
</span>
```

> Keep all existing styling unchanged. The tooltip is `title` for a no-dep solution. If the repo has a tooltip primitive (look for `Tooltip` in `web/components/ui/`), prefer that over `title` for a richer experience — but `title` is acceptable for v1.

- [ ] **Step 5: Verify test passes**

```bash
cd web && npm run test -- --run VcgStressHistoryTable 2>&1 | tail -5 ; cd ..
```
Expected: green, including the new tooltip test.

- [ ] **Step 6: Commit (milestone)**

```bash
git add web/components/regime/
git commit -m "feat(vcg-ui): tooltip on interpretation pills with historical context"
```

---

### Task 9: Browser verification

**Files:** none changed; this is verification only.

- [ ] **Step 1: Start dev stack**

```bash
bash scripts/dev.sh &
# Wait for web on :3001 and API on :8400
sleep 15
```

- [ ] **Step 2: Open `/regime` in browser**

```bash
open http://localhost:3001/regime
```
Manually confirm in the VCG sub-tab:
- The "PANIC / RISK-OFF / EDR History (all-time)" section header still works (still folds/unfolds).
- Above it, the summary line(s) render: "Across 83 historical PANIC events, mean 20d forward SPX return was +2.88% (53% positive)."
- Inside the table, three new columns appear at the right: `+5d %`, `+20d %`, `+60d %`. Positive values are green, negative are red, recent days show `—` for `+60d %`.
- Hovering a PANIC pill shows the tooltip text.
- If the Signal Detail card currently shows a stress state, the "Historical fwd" row appears underneath the interpretation.

- [ ] **Step 3: Take a "before/after" screenshot for the PR**

```bash
mkdir -p output/playwright
# Use Playwright or browser screenshot tooling
# Save to:
#   output/playwright/2026-05-28-vcg-stress-history-with-fwd-returns.png
```

- [ ] **Step 4: Sanity-check the API directly**

```bash
curl -s http://localhost:8400/api/regime/vcg-validation | jq '.stress_history_summary, .stress_history[0]'
```
Expected: `stress_history_summary` populated with 2-3 rows (PANIC/RISK_OFF/EDR); first stress_history row has `fwd_5d_pct`, `fwd_20d_pct`, `fwd_60d_pct` keys (may be null on recent days).

- [ ] **Step 5: Stop dev stack**

```bash
# Find and kill the dev.sh process group
ps aux | grep -E "dev\.sh|next dev|uvicorn" | grep -v grep
# kill <pids>
```

---

### Task 10: Final verification + PR

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/unit -q && uv run pytest tests/integration -q -m "not live and not slow"
cd web && npm run typecheck && npm run test -- --run ; cd ..
```
Expected: all green.

- [ ] **Step 2: Confirm OpenAPI snapshot, types, and frontend are in sync**

```bash
git status --short
git diff --stat origin/main...HEAD
```
Expected: no unstaged or untracked changes; diff stat shows the 10-15 files touched.

- [ ] **Step 3: Push branch and open PR**

```bash
git push -u origin feat/vcg-ui-capitulation-framing
gh pr create --title "feat(vcg-ui): forward-return columns + capitulation framing" --body "$(cat <<'EOF'
## Summary
- Reframes the VCG stress-history UI to show what historically happened *after* each PANIC / RISK_OFF / EDR day, instead of relying on red-pill framing that implies "warning."
- Backend-additive: `VcgStressHistoryEntry` gains `fwd_5d_pct`, `fwd_20d_pct`, `fwd_60d_pct`; `VcgValidationResponse` gains optional `stress_history_summary`. No `COMPOSITE_VERSION` bump.
- Frontend-additive: 3 columns on the stress-history table, 1 summary line above, 1 historical-fwd row in the Signal Detail card when current state is stress, 1 tooltip on the interpretation pill.
- Grounded in 13 forward-return probes documented at `docs/research/regime/vcg-forward-return-probes-2026-05-28.md` (PANIC mean 20d = +2.88%, RISK_OFF mean 60d = +3.04%).

## Test plan
- [ ] `uv run pytest tests/unit tests/integration -m "not live and not slow"` green
- [ ] `cd web && npm run typecheck && npm run test -- --run` green
- [ ] Manual: open `/regime` VCG sub-tab — new columns + summary + tooltip render correctly
- [ ] Manual: open `/regime` VCG sub-tab — Signal Detail card shows historical-fwd row only when current state is PANIC/RISK_OFF/EDR

## What this does NOT change
- VCG signal math, classifier, cascade logic, `COMPOSITE_VERSION`
- Stress state assignment for any historical day
- Other regime indicators (CRI, Canary, GEX cockpit)
EOF
)"
```

- [ ] **Step 4: Wait for CI to be green, then merge via `gh pr merge`**

Do **not** `git push origin main` directly — per project standing rule, always merge via PR.

---

## Standing-rule checklist (run before declaring done)

- [ ] **`uv` only** — no bare `python`/`pip`/`pytest` in any task command. ✅ (all backend commands use `uv run pytest`).
- [ ] **Persist analytical results to Postgres** — no in-memory caching introduced; results derive from already-persisted `regime_backtest_daily` + `vol_index_daily`.
- [ ] **No naked shorts** — N/A (UI-only).
- [ ] **Data source priority** — N/A (no new external data; SPX comes from existing `vol_index_daily`).
- [ ] **No secrets to Codex subprocesses** — N/A.
- [ ] **No commit without explicit user request** — every commit step is gated by user approval at the start of the work; do not auto-commit during subagent execution.
- [ ] **PR before merge to main** — Task 10 Step 3 opens a PR; never `git push origin main`.
- [ ] **Branch name** — `feat/vcg-ui-capitulation-framing` ✅.
- [ ] **No `Co-Authored-By: Claude`** trailer in any commit.
- [ ] **Migrations idempotent** — N/A (no migrations).
- [ ] **Module size budget <500 lines** — `regime_validation.py` model file currently 96 lines; +25 lines stays well under budget. Storage module: check at exec time (likely already large; if storage module is >1000 lines, propose splitting **before** appending).
- [ ] **API contract identity preserved** — change is purely additive (new optional fields), no rename/removal; existing OpenAPI component names unchanged.
- [ ] **`/api/regime/vcg-validation` 503 contract still honored** — when no completed VCG run exists, endpoint still returns 503 unchanged; `stress_history_summary` is only computed when the run exists.
- [ ] **Screenshots under `output/playwright/`** ✅ (Task 9 Step 3).
- [ ] **Worktree under `.worktrees/`** ✅ (Task 0 Step 1).
- [ ] **No code review skipped** — `/review-cycle` runs on this plan (per user request) and on the diff before merge.

---

## Out of scope (do NOT do in this PR)

- Adding BOUNCE to `stress_history` — n=5, dominated by 2008 GFC; would mislead.
- Changing pill colors — surface change only, no math implication.
- Materializing forward returns into `regime_backtest_daily` — query-time computation is cheap enough and reversible.
- Bumping `COMPOSITE_VERSION` — math is unchanged.
- Updating the methodology doc — already calls VCG "descriptive, not predictive"; UI is catching up to the doc, not the other way around.
- Adding forward-return-based filtering or sorting controls — wait for user demand.
