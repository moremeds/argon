# UW Scan Opportunity Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the opportunity-side v1 gaps after the foundation and data-ingestion plans: scoring, structure ideas, conservative OI tracking reconciliation, snapshot pipeline boundary, and Streamlit live/snapshot wiring.

**Architecture:** Keep opportunity logic in pure services so it can be tested without Streamlit. Streamlit calls a pipeline boundary that can serve fixture, live, or snapshot modes. Tracking and scoring consume normalized rows and return typed view models.

**Tech Stack:** Python 3.11+, pydantic, pandas, Streamlit, pytest.

---

## Prerequisites

Complete:

- `docs/superpowers/plans/2026-05-11-uw-scan-foundation-layout.md`
- `docs/superpowers/plans/2026-05-11-uw-scan-data-ingestion.md`

## Files

- Create: `src/uw_scan/scoring.py`
- Create: `src/uw_scan/structures.py`
- Create: `src/uw_scan/tracking.py`
- Create: `src/uw_scan/ingest/pipeline.py`
- Modify: `app/streamlit_app.py`
- Modify: `README.md`
- Test: `tests/test_scoring.py`
- Test: `tests/test_structures.py`
- Test: `tests/test_tracking.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_streamlit_live_wiring.py`

## Task 1: Scoring And Structure Rules

**Files:**
- Create: `src/uw_scan/scoring.py`
- Create: `src/uw_scan/structures.py`
- Test: `tests/test_scoring.py`
- Test: `tests/test_structures.py`

- [ ] **Step 1: Write tests**

Create `tests/test_scoring.py`:

```python
from uw_scan.scoring import score_flow_candidate


def test_score_flow_candidate_deep_conviction_call():
    score = score_flow_candidate(
        volume=2400,
        open_interest=900,
        ask_side_pct=0.88,
        premium=1_250_000,
        is_single_leg=True,
        moneyness_pct=0.04,
        dte=39,
    )
    assert score.score == 5
    assert "Volume > OI" in score.confirmations


def test_score_flow_candidate_warns_on_low_dte():
    score = score_flow_candidate(
        volume=2400,
        open_interest=900,
        ask_side_pct=0.88,
        premium=1_250_000,
        is_single_leg=True,
        moneyness_pct=0.04,
        dte=1,
    )
    assert score.score == 4
    assert "DTE below minimum" in score.warnings
```

Create `tests/test_structures.py`:

```python
from uw_scan.models import SignalDirection
from uw_scan.structures import suggest_structure


def test_suggest_call_debit_spread_for_bullish_deep_conviction():
    idea = suggest_structure(direction=SignalDirection.BULLISH, setup_types=["Deep Conviction Directional"], iv_rank=45)
    assert idea.structure_type == "Call debit spread candidate"
    assert idea.max_risk_note == "Sizing deferred"


def test_suggest_iron_condor_for_high_iv_earnings():
    idea = suggest_structure(direction=SignalDirection.NEUTRAL, setup_types=["Earnings IV Crush"], iv_rank=82)
    assert idea.structure_type == "Defined-risk iron condor candidate"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_scoring.py tests/test_structures.py -v`

Expected: FAIL with missing modules.

- [ ] **Step 3: Implement scoring**

Create `src/uw_scan/scoring.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoreResult:
    score: int
    confirmations: list[str]
    warnings: list[str]


def score_flow_candidate(*, volume: int, open_interest: int | None, ask_side_pct: float, premium: float, is_single_leg: bool, moneyness_pct: float, dte: int) -> ScoreResult:
    score = 0
    confirmations: list[str] = []
    warnings: list[str] = []
    if open_interest is not None and volume > open_interest:
        score += 1
        confirmations.append("Volume > OI")
    if ask_side_pct >= 0.80:
        score += 1
        confirmations.append("Ask-side aggression")
    if premium >= 500_000:
        score += 1
        confirmations.append("Premium >= $500K")
    if is_single_leg:
        score += 1
        confirmations.append("Single-leg flow")
    if moneyness_pct <= 0.12:
        score += 1
        confirmations.append("Near the money")
    if dte < 6:
        score = max(0, score - 1)
        warnings.append("DTE below minimum")
    return ScoreResult(score=score, confirmations=confirmations, warnings=warnings)
```

- [ ] **Step 4: Implement structure mapping**

Create `src/uw_scan/structures.py`:

```python
from __future__ import annotations

from uw_scan.models import SignalDirection, StructureIdea


def suggest_structure(*, direction: SignalDirection, setup_types: list[str], iv_rank: float | None) -> StructureIdea:
    if "Earnings IV Crush" in setup_types and iv_rank is not None and iv_rank >= 75:
        return StructureIdea(
            structure_type="Defined-risk iron condor candidate",
            rationale="High IV earnings setup favors defined-risk premium sale candidate.",
            invalidation="Avoid if liquidity is poor or event risk is binary and unpriceable.",
        )
    if direction == SignalDirection.BULLISH and "Deep Conviction Directional" in setup_types:
        return StructureIdea(
            structure_type="Call debit spread candidate",
            rationale="Bullish high-conviction flow with defined-risk directional expression.",
            invalidation="Downgrade if OI follow-through fails or skew warns against calls.",
        )
    if direction == SignalDirection.BEARISH and "Deep Conviction Directional" in setup_types:
        return StructureIdea(
            structure_type="Put debit spread candidate",
            rationale="Bearish high-conviction flow with defined-risk directional expression.",
            invalidation="Downgrade if OI follow-through fails or put skew is already extreme.",
        )
    return StructureIdea(
        structure_type="Watchlist only",
        rationale="Signal is interesting but does not meet a stronger structure rule.",
        invalidation="Wait for stronger flow, OI, IV, or liquidity confirmation.",
    )
```

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_scoring.py tests/test_structures.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/scoring.py src/uw_scan/structures.py tests/test_scoring.py tests/test_structures.py
git commit -m "Add scoring and structure rules"
```

## Task 2: Conservative Tracking Reconciliation

**Files:**
- Create: `src/uw_scan/tracking.py`
- Test: `tests/test_tracking.py`

- [ ] **Step 1: Write tests**

Create `tests/test_tracking.py`:

```python
from uw_scan.tracking import ReconciliationConfig, reconcile_oi_change


def test_reconcile_likely_opening_when_oi_follow_through_is_strong():
    assert reconcile_oi_change(flow_volume=1000, previous_oi=500, current_oi=900, side_consistent=True, config=ReconciliationConfig()) == "likely_opening"


def test_reconcile_fading_when_volume_has_no_oi_follow_through():
    assert reconcile_oi_change(flow_volume=1000, previous_oi=500, current_oi=530, side_consistent=True, config=ReconciliationConfig()) == "fading"


def test_reconcile_unknown_on_conflict():
    assert reconcile_oi_change(flow_volume=1000, previous_oi=500, current_oi=900, side_consistent=False, config=ReconciliationConfig()) == "unknown"
```

- [ ] **Step 2: Run test to verify failure**

Run: `pytest tests/test_tracking.py -v`

Expected: FAIL with missing tracking module.

- [ ] **Step 3: Implement reconciliation**

Create `src/uw_scan/tracking.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReconciliationConfig:
    min_abs_oi_change: int = 100
    min_oi_change_pct_of_flow_volume: float = 0.25
    unknown_on_conflict: bool = True


def reconcile_oi_change(*, flow_volume: int, previous_oi: int | None, current_oi: int | None, side_consistent: bool, config: ReconciliationConfig) -> str:
    if previous_oi is None or current_oi is None or flow_volume <= 0:
        return "unknown"
    if config.unknown_on_conflict and not side_consistent:
        return "unknown"
    oi_change = current_oi - previous_oi
    threshold = max(config.min_abs_oi_change, int(flow_volume * config.min_oi_change_pct_of_flow_volume))
    if oi_change >= threshold:
        return "likely_opening"
    if oi_change <= -threshold:
        return "likely_closing"
    return "fading"
```

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_tracking.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/tracking.py tests/test_tracking.py
git commit -m "Add conservative OI reconciliation"
```

## Task 3: Pipeline Boundary And Streamlit Wiring

**Files:**
- Create: `src/uw_scan/ingest/pipeline.py`
- Modify: `app/streamlit_app.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_streamlit_live_wiring.py`

- [ ] **Step 1: Write pipeline tests**

Create `tests/test_pipeline.py`:

```python
from uw_scan.config import UwScanConfig
from uw_scan.ingest.pipeline import run_fixture_pipeline


def test_fixture_pipeline_returns_dashboard_and_budget():
    dashboard = run_fixture_pipeline(UwScanConfig())
    assert dashboard.opportunities
    assert dashboard.request_budget.total_estimated_requests > 0
```

Create `tests/test_streamlit_live_wiring.py`:

```python
import inspect

from app import streamlit_app


def test_streamlit_app_uses_pipeline_boundary():
    source = inspect.getsource(streamlit_app)
    assert "run_fixture_pipeline" in source
    assert "demo_dashboard()" not in source
```

- [ ] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_pipeline.py tests/test_streamlit_live_wiring.py -v`

Expected: FAIL with missing pipeline boundary or direct fixture call in app.

- [ ] **Step 3: Implement pipeline boundary**

Create `src/uw_scan/ingest/pipeline.py`:

```python
from __future__ import annotations

from uw_scan.config import UwScanConfig
from uw_scan.fixtures import demo_dashboard
from uw_scan.models import DashboardViewModel
from uw_scan.request_budget import estimate_request_budget


def run_fixture_pipeline(config: UwScanConfig) -> DashboardViewModel:
    dashboard = demo_dashboard()
    budget = estimate_request_budget(
        flow_rows=len(dashboard.flow_rows),
        watchlist_symbols=sum(len(source.imported_symbols) for source in dashboard.watchlist_sources),
        deep_surface_tickers=min(len(dashboard.surface_metrics), config.max_deep_surface_tickers),
        important_expiries_per_ticker=1,
        config=config,
    )
    return dashboard.model_copy(update={"request_budget": budget})
```

- [ ] **Step 4: Modify Streamlit app**

In `app/streamlit_app.py`, replace:

```python
from uw_scan.fixtures import demo_dashboard
```

with:

```python
from uw_scan.ingest.pipeline import run_fixture_pipeline
```

Then replace:

```python
dashboard = demo_dashboard()
```

with:

```python
dashboard = run_fixture_pipeline(config)
```

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_pipeline.py tests/test_streamlit_live_wiring.py -v`

Expected: PASS.

Commit:

```bash
git add src/uw_scan/ingest/pipeline.py app/streamlit_app.py tests/test_pipeline.py tests/test_streamlit_live_wiring.py
git commit -m "Wire UI through ingest pipeline boundary"
```

## Task 4: Phase Coverage Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Append:

```markdown
## V1 Implementation Phases

| Phase | Coverage |
|---|---|
| Foundation layout | View models, fixture UI, request budget, TradingView parser contract, schema foundation |
| Data ingestion | UW endpoint registry, audit, normalization, schema expansion, request planner |
| Opportunity layer | Scoring, structure ideas, tracking reconciliation, pipeline boundary, Streamlit mode wiring |
| Production hardening | Real Postgres integration test execution, live UW smoke tests, browser-rendered TradingView fallback if static parsing fails |
```

- [ ] **Step 2: Run safety checks**

Run a local secret scan for the actual UW token value supplied at runtime. Do not paste the token into this plan or any committed file.

Expected: no output.

Run: `pytest -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "Document UW scan v1 phase coverage"
```

## Plan Self-Review Checklist

- Spec coverage: Covers opportunity-side gaps from the design: scoring, structures, tracking reconciliation, and UI pipeline boundary.
- Known remaining gaps: Real Postgres integration test execution, live UW API smoke tests, and browser-rendered TradingView fallback are production hardening after these v1 slices.
- Red-flag scan: No secret token is included. The plan uses `UW_SCAN_API_KEY` only as an environment variable name.
- Execution gate: Run only after foundation and data-ingestion plans pass.
