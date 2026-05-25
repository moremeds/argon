# VCG Validation UI Surface — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the VCG backtest evidence (persisted to `uw_scan.regime_backtest_runs` by #73) visible in the Regime → Validation tab, at parity with the CRI evidence already there.

**Architecture:** New read-only API endpoint `/api/regime/vcg-validation` that serves the latest completed VCG run from the DB, with a paired markdown renderer for the existing `<pre>`-block rendering pattern. UI extends the current `ValidationTab` with a CRI/VCG selector so both sit under one top-level tab.

**Tech Stack:** Python 3.13 (FastAPI + Pydantic v2 + psycopg 3), TypeScript (Next.js 16 + React 19), hand-rolled markdown rendering. No new deps (`@testing-library/react@^16.3.2` already in `web/package.json`).

## Persisted JSON shape (verified against `scripts/backtest_vcg.py:222`)

The implementer should NOT guess at the `summary.extras` structure — verify it before writing endpoint code. Actual shape:

```json
{
  "summary": {
    "oos": null,
    "extras": {
      "credit_proxy": "HYG",
      "use_adj_close": true,
      "named_crash_window": {
        "2008-09-15": [
          {"offset_d": -5, "vcg": -0.42, "vcg_adj": -0.42, "beta1": -0.02, "beta2": -0.04, "sign_ok": true, "interpretation": "NORMAL", "vix": 25.3},
          {"offset_d": -3, ...},
          {"offset_d": -1, ...},
          {"offset_d": 0,  ...},
          {"offset_d": 1,  ...},
          {"offset_d": 3,  ...},
          {"offset_d": 5,  ...}
        ],
        "2020-03-16": [...]
      },
      "interpretation_distribution": {"NORMAL": 2160, "SUPPRESSED": 2450, "EDR": 50, "RISK_OFF": 30, "PANIC": 18, "BOUNCE": 0, "WATCH": 0},
      "ro_count": 30,
      "edr_count": 50,
      "bounce_count": 0
    }
  }
}
```

Critical detail: `named_crash_window[iso_date]` is a **list[dict]** (one entry per offset), NOT a `dict[offset_key, row]`. The event label is NOT persisted — it lives in the `NAMED_CRASH_DATES` constant at `src/uw_scan/reports/regime_backtest_report.py:25` and must be looked up there. Each entry's offset key is `"offset_d"` (singular `d`), not `"offset_days"`.

---

## Context: what already exists vs. what's missing

| Concern | CRI today | VCG today | Gap |
|---|---|---|---|
| Live snapshot UI | `CriSubTab.tsx` | `VcgSubTab.tsx` | — at parity |
| Backtest persisted to DB | ✓ (run_id=4, n=4873) | ✓ (run_id=5, n=4708, named-crash ±5d window) | — at parity |
| Validation API endpoint | `/api/regime/validation` | none | **this plan** |
| Validation UI | `ValidationTab.tsx` | none | **this plan** |

The VCG data **is** persisted — including the `summary.extras.named_crash_window` (±5d offsets) and `summary.extras.interpretation_distribution`. No one reads it.

## Design choice: extend vs. split the validation tab

Two options. **Recommendation: extend** — adds a CRI/VCG selector inside the existing `VALIDATION` tab. The honest tradeoffs:

**Reasons to extend (this plan's choice):**
- The "VALIDATION" label remains a coherent top-level concept ("evidence about indicator quality"), independent of which indicator.
- The closure memo (`docs/research/regime/closure-2026-05-24.md`) frames CRI + VCG as a paired indicator framework — a paired UI matches the research framing.
- One shared error-state / loading-state shell instead of two.

**Reasons a 5th top-level tab `VCG-VALIDATION` would be better (acknowledged, not adopted):**
- **Deep-linkability** — `/regime?tab=vcg-validation` is one URL; the sub-selector requires nested state in URL/query (not added by this plan; default-CRI on every visit).
- **Tab-switching cost** — the top-level tab system unmounts `ValidationTab` on every switch, so the CRI fetch re-fires anyway; nesting a second fetch lifecycle inside doubles perceived latency on re-entry.
- **Structural divergence** — VCG's named-crash window + interpretation distribution have **no CRI analog**; only the markdown `<pre>` block is genuinely shared (5 lines). The "shared structure" argument is weaker than it sounds.

**Why extend wins for THIS PR:** mechanical work, no URL/query-param plumbing required, and the design is reversible — if the structural divergence proves painful in 2–3 follow-ons, splitting to a 5th tab is a 30-minute refactor (lift sub-tab content into a sibling route component).

## Standing-rule checks before starting

- **No extending `repository.py`** — VCG queries reuse `RegimeBacktestRepository` (already its own module). ✓
- **No on-disk artifacts** — DB-only, no markdown/csv/json files written. ✓
- **API contract preservation** — adds a new endpoint, does not change `/api/regime/validation`. Run `npm run gen:types` after API change. ✓
- **Persist analytical results** — already persisted by #73; this PR only adds the read path. ✓

---

## File structure

### Backend
- Modify: `src/uw_scan/api/models/regime_validation.py` — add `VcgValidationResponse`, `VcgNamedCrashOffset`, `VcgNamedCrashEvent`, `VcgInterpretationCount`.
- Create: `src/uw_scan/reports/regime_vcg_backtest_report.py` — `render_vcg_backtest_markdown(run, daily) -> str`. Pure function over `run` + `daily` rows; no I/O. Mirrors `regime_backtest_report.py`.
- Modify: `src/uw_scan/api/routers/regime_validation.py` — add `@router.get("/vcg-validation")` next to `get_validation`. DB-first via `RegimeBacktestRepository.find_latest_run("vcg")`; 503 when no completed run.

### Backend tests
- Modify: `tests/integration/conftest.py` — add `seed_vcg_backtest_run` fixture next to `seed_cri_backtest_run`; insert one completed VCG run with `summary.extras.named_crash_window` populated in the shape verified above.
- Create: `tests/unit/reports/test_regime_vcg_backtest_report.py` — self-contained snapshot test (synthetic fixture, no on-disk dependency).
- Create: `tests/integration/api/test_regime_vcg_validation_endpoint.py` — happy path + 503-when-empty.

### Frontend
- Modify: `web/lib/types.ts` — regenerated via `npm run gen:types`.
- Modify: `web/lib/regime/api.ts` — add `vcgValidation()` URL builder next to `validation()`.
- Modify: `web/components/regime/ValidationTab.tsx` — pure switcher with CRI/VCG sub-selector.
- Create: `web/components/regime/CriValidationPanel.tsx` — receives `ValidationResponse`; lifted from the current `ValidationTab` body so the tab becomes a router.
- Create: `web/components/regime/VcgValidationPanel.tsx` — receives `VcgValidationResponse` and renders: (a) `<pre>` markdown body; (b) interpretation-distribution table; (c) named-crash window with **one sub-table per event, rows = offsets** (`-5,-3,-1,0,+1,+3,+5`). NB: original sketch said "row-per-event, columns at offsets" — the simpler row-per-offset layout matches the renderer's data flow; if a pivoted table is later wanted, it's a separate refactor.

### Frontend tests
- Create: `web/tests/unit/VcgValidationPanel.test.tsx` — render with a fixture, assert key UI elements (flat path matches existing `web/tests/unit/` siblings).
- Create: `web/tests/unit/ValidationTabSwitcher.test.tsx` — covers the sub-selector: CRI→VCG switch fires the new endpoint; fetch failure on VCG shows an error; switching back to CRI clears the stale error.

### OpenAPI snapshot
- Modify: `tests/integration/api/openapi.snapshot.json` — regenerate after the new endpoint + response models land. Adding `/api/regime/vcg-validation` and 4 new schemas (`VcgValidationResponse`, `VcgNamedCrashEvent`, `VcgNamedCrashOffset`, `VcgInterpretationCount`) WILL fail `tests/integration/api/test_openapi_snapshot.py` until this regenerates.

---

## Task 1: Backend response model

**Files:**
- Modify: `src/uw_scan/api/models/regime_validation.py`

- [ ] **Step 1: Add VCG response types**

Append to the file (preserving existing exports):

```python
class VcgInterpretationCount(BaseModel):
    interpretation: str
    n: int
    pct: float


class VcgNamedCrashOffset(BaseModel):
    """One row of the ±5d named-crash window for a single event."""

    offset_days: int  # -5, -3, -1, 0, 1, 3, 5
    vcg: float | None
    vcg_adj: float | None
    beta1: float | None
    beta2: float | None
    sign_ok: bool | None
    interpretation: str | None


class VcgNamedCrashEvent(BaseModel):
    date: str  # "2008-09-15"
    label: str  # "Lehman bankruptcy"
    offsets: list[VcgNamedCrashOffset]


class VcgValidationResponse(BaseModel):
    backtest_md: str
    n_days: int
    composite_version: str
    credit_proxy: str  # "HYG" | "JNK" | "LQD"
    interpretation_distribution: list[VcgInterpretationCount]
    named_crash_window: list[VcgNamedCrashEvent]
```

- [ ] **Step 2: Direct-import smoke for the existing surface**

`tests/unit/test_models_exports.py` protects `uw_scan.models`, NOT `uw_scan.api.models.regime_validation`, so it's the wrong gate here. Instead, verify the new types coexist with the existing exports:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run python -c "
from uw_scan.api.models.regime_validation import (
    ValidationResponse, OosSummary, GuidanceResponse,        # existing — must still import
    VcgValidationResponse, VcgNamedCrashEvent,
    VcgNamedCrashOffset, VcgInterpretationCount,             # new
)
print('ok')
"
```
Expected: `ok`. The OpenAPI snapshot (Task 5b) is the contract-stability gate.

- [ ] **Step 3: Commit (only with explicit user approval — repo rule "never commit without explicit user request")**

```bash
git add src/uw_scan/api/models/regime_validation.py
git commit -m "feat(api): add VcgValidationResponse model"
```

## Task 2: Backend renderer

**Files:**
- Create: `src/uw_scan/reports/regime_vcg_backtest_report.py`
- Create: `tests/unit/reports/test_regime_vcg_backtest_report.py`

- [ ] **Step 1: Write the failing snapshot test**

Self-contained — no on-disk dependency. Build a 5-row synthetic VCG `run` + `daily` covering each interpretation level (NORMAL, SUPPRESSED, EDR, RISK_OFF, PANIC). Expected markdown built via string-concatenation (the formatter strips trailing whitespace; build hard-line-breaks as `"  \n"` inside quoted segments).

```python
"""Self-contained snapshot test for the VCG markdown renderer."""
from __future__ import annotations
from datetime import date

from uw_scan.reports.regime_vcg_backtest_report import render_vcg_backtest_markdown


def _make_daily() -> list[dict]:
    # 5 sequential trading days, one per interpretation level the renderer prints.
    base = [
        ("NORMAL", -0.50, -0.50, -0.02, -0.04, True),
        ("SUPPRESSED", 0.80, 0.80, 0.03, -0.05, False),
        ("EDR", -1.20, -1.20, -0.08, -0.02, True),
        ("RISK_OFF", -2.10, -2.10, -0.09, -0.06, True),
        ("PANIC", -3.40, -0.00, -0.05, -0.08, True),
    ]
    return [
        {
            "trade_date": date(2024, 1, 2 + i),
            "score": row[1],
            "level": row[0],
            "payload": {
                "vcg": row[1], "vcg_adj": row[2],
                "beta1": row[3], "beta2": row[4],
                "sign_ok": row[5], "interpretation": row[0],
            },
        }
        for i, row in enumerate(base)
    ]


def test_render_vcg_produces_expected_markdown_substrings() -> None:
    daily = _make_daily()
    run = {
        "indicator": "vcg",
        "composite_version": "1",
        "start_date": date(2007, 1, 3),
        "end_date": daily[-1]["trade_date"],
        "window_days": 21,
        "n_days": len(daily),
        "summary": {"oos": None, "extras": {
            "credit_proxy": "HYG",
            "interpretation_distribution": {
                "NORMAL": 1, "SUPPRESSED": 1, "EDR": 1, "RISK_OFF": 1, "PANIC": 1,
            },
            "ro_count": 1, "edr_count": 1, "bounce_count": 0,
        }},
    }
    actual = render_vcg_backtest_markdown(run, daily)
    # Substring assertions rather than byte-for-byte — the renderer's exact
    # format is allowed to evolve. Lock the structural promises only.
    assert "VCG Backtest" in actual
    assert "**Credit proxy:** HYG" in actual
    assert "**Date range:** 2024-01-02 → 2024-01-06" in actual
    for level in ("NORMAL", "SUPPRESSED", "EDR", "RISK_OFF", "PANIC"):
        assert f"| {level} |" in actual, f"missing {level} row in distribution table"


def test_render_vcg_empty_daily_returns_placeholder() -> None:
    run = {"indicator": "vcg", "composite_version": "1", "start_date": date(2024, 1, 1),
           "end_date": date(2024, 1, 1), "window_days": 21, "n_days": 0,
           "summary": {"oos": None, "extras": {}}}
    assert render_vcg_backtest_markdown(run, []) == "# VCG Backtest\n\n_No daily rows available._\n"
```

- [ ] **Step 2: Run, verify it fails**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/unit/reports/test_regime_vcg_backtest_report.py -v`
Expected: FAIL with `ModuleNotFoundError: uw_scan.reports.regime_vcg_backtest_report`.

- [ ] **Step 3: Implement the renderer**

```python
"""Pure renderer: VCG regime_backtest_runs row + daily rows -> markdown."""
from __future__ import annotations
from io import StringIO
from typing import Any


def render_vcg_backtest_markdown(run: dict, daily: list[dict]) -> str:
    if not daily:
        return "# VCG Backtest\n\n_No daily rows available._\n"
    extras = (run.get("summary") or {}).get("extras") or {}
    proxy = extras.get("credit_proxy", "—")
    dist = extras.get("interpretation_distribution") or {}
    total = sum(dist.values()) or 1
    out = StringIO()
    out.write("# VCG Backtest — Credit Proxy + Vol Compression\n\n")
    out.write(f"**N days:** {len(daily)}\n")
    out.write(f"**Credit proxy:** {proxy}\n")
    out.write(f"**Date range:** {daily[0]['trade_date'].isoformat()} → {daily[-1]['trade_date'].isoformat()}\n\n")
    out.write("## Interpretation distribution\n\n| Interpretation | Count | % |\n|---|---|---|\n")
    for k in ("NORMAL", "SUPPRESSED", "EDR", "BOUNCE", "RISK_OFF", "PANIC", "WATCH"):
        n = dist.get(k, 0)
        if n == 0: continue
        out.write(f"| {k} | {n} | {n/total*100:.1f}% |\n")
    return out.getvalue()
```

- [ ] **Step 4: Re-run snapshot test**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/unit/reports/test_regime_vcg_backtest_report.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/regime_vcg_backtest_report.py tests/unit/reports/test_regime_vcg_backtest_report.py
git commit -m "feat(reports): add VCG backtest markdown renderer"
```

## Task 3: Backend endpoint

**Files:**
- Modify: `src/uw_scan/api/routers/regime_validation.py`

- [ ] **Step 1: Add the endpoint handler**

Append after `get_validation`:

```python
@router.get("/vcg-validation", response_model=VcgValidationResponse)
def get_vcg_validation(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VcgValidationResponse:
    """Latest completed VCG backtest run, rendered to markdown."""
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    run = rb.find_latest_run("vcg")
    if run is None:
        raise HTTPException(
            503,
            "no completed VCG backtest run at the current COMPOSITE_VERSION; "
            "run scripts/backtest_vcg.py to seed uw_scan.regime_backtest_runs",
        )
    daily = rb.fetch_daily_for_run(run["id"])
    extras = (run.get("summary") or {}).get("extras") or {}
    dist = extras.get("interpretation_distribution") or {}
    total = sum(dist.values()) or 1
    # Persisted shape: dict[iso_date, list[dict]] where each dict has
    # offset_d (NOT offset_days) plus vcg/vcg_adj/beta1/beta2/sign_ok/interpretation/vix.
    # Event labels live in NAMED_CRASH_DATES, not in the persisted JSON.
    crash_window = extras.get("named_crash_window") or {}
    events = []
    for iso_date, rows in sorted(crash_window.items()):
        events.append(VcgNamedCrashEvent(
            date=iso_date,
            label=NAMED_CRASH_DATES.get(iso_date, ""),
            offsets=[
                VcgNamedCrashOffset(
                    offset_days=int(entry["offset_d"]),
                    vcg=entry.get("vcg"),
                    vcg_adj=entry.get("vcg_adj"),
                    beta1=entry.get("beta1"),
                    beta2=entry.get("beta2"),
                    sign_ok=entry.get("sign_ok"),
                    interpretation=entry.get("interpretation"),
                )
                for entry in sorted(rows, key=lambda r: int(r["offset_d"]))
            ],
        ))
    return VcgValidationResponse(
        backtest_md=render_vcg_backtest_markdown(run, daily),
        n_days=len(daily),
        composite_version=str(run["composite_version"]),
        credit_proxy=extras.get("credit_proxy", "HYG"),
        interpretation_distribution=[
            VcgInterpretationCount(interpretation=k, n=int(v), pct=round(100 * v / total, 1))
            for k, v in sorted(dist.items(), key=lambda kv: -kv[1])
        ],
        named_crash_window=events,
    )
```

Add imports at top of `regime_validation.py`:

```python
from uw_scan.api.models.regime_validation import (
    VcgValidationResponse,
    VcgInterpretationCount,
    VcgNamedCrashOffset,
    VcgNamedCrashEvent,
)
from uw_scan.reports.regime_backtest_report import NAMED_CRASH_DATES
from uw_scan.reports.regime_vcg_backtest_report import render_vcg_backtest_markdown
```

(`NAMED_CRASH_DATES` is the existing constant at `src/uw_scan/reports/regime_backtest_report.py:25` — same labels CRI uses, no duplication.)

- [ ] **Step 2: Quick smoke test against the running stack**

```bash
curl -s http://127.0.0.1:8400/api/regime/vcg-validation | jq '{n_days, credit_proxy, interp_count: (.interpretation_distribution | length), events: (.named_crash_window | length)}'
```
Expected: `n_days=4708`, `credit_proxy="HYG"`, `interp_count>=4`, `events>=8`.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/api/routers/regime_validation.py
git commit -m "feat(api): /regime/vcg-validation serves latest VCG run from DB"
```

## Task 4: VCG fixture + endpoint integration test

**Files:**
- Modify: `tests/integration/conftest.py`
- Create: `tests/integration/api/test_regime_vcg_validation_endpoint.py`

- [ ] **Step 1: Add `seed_vcg_backtest_run` fixture in `tests/integration/conftest.py`**

Mirror `seed_cri_backtest_run`. Critical: the `named_crash_window` value must be a `dict[iso_str, list[dict]]` with `offset_d` keys to match what `scripts/backtest_vcg.py` actually persists. Lifted-shape fixture below:

```python
@pytest.fixture
def seed_vcg_backtest_run(seeded_db_empty_cards) -> int:
    """Insert one completed VCG run + minimal daily row into the test DB."""
    from datetime import date as _date
    from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION as VCG_COMPOSITE_VERSION
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    existing = rb.find_latest_run("vcg", composite_version=str(VCG_COMPOSITE_VERSION))
    if existing is not None:
        return int(existing["id"])

    # Synthetic crash-window entry (one event, all 7 offsets) — matches the
    # shape backtest_vcg.py persists at scripts/backtest_vcg.py:222.
    def _row(off: int, interp: str, vcg: float) -> dict:
        return {
            "offset_d": off, "vcg": vcg, "vcg_adj": vcg,
            "beta1": -0.02, "beta2": -0.04, "sign_ok": True,
            "interpretation": interp, "vix": 25.0,
        }

    run_id = rb.insert_run(
        indicator="vcg",
        composite_version=str(VCG_COMPOSITE_VERSION),
        start_date=_date(2007, 1, 3),
        end_date=_date(2026, 5, 15),
        window_days=21,
        n_days=4708,
        params={"window": 21, "proxy": "HYG", "source": "seed_vcg_backtest_run"},
        summary={
            "oos": None,
            "extras": {
                "credit_proxy": "HYG",
                "use_adj_close": True,
                "named_crash_window": {
                    "2008-09-15": [
                        _row(-5, "NORMAL", -0.50),
                        _row(-3, "NORMAL", -0.40),
                        _row(-1, "SUPPRESSED", 0.20),
                        _row(0,  "BOUNCE", 0.30),
                        _row(1,  "SUPPRESSED", 0.10),
                        _row(3,  "RISK_OFF", -2.10),
                        _row(5,  "NORMAL", -0.30),
                    ],
                },
                "interpretation_distribution": {
                    "NORMAL": 2160, "SUPPRESSED": 2450, "EDR": 50, "RISK_OFF": 30, "PANIC": 18,
                },
                "ro_count": 30, "edr_count": 50, "bounce_count": 0,
            },
        },
        note="seed_vcg_backtest_run fixture",
    )
    rb.bulk_insert_daily(
        run_id,
        [{"trade_date": _date(2026, 5, 15), "score": -0.5, "level": "NORMAL", "payload": {}}],
    )
    rb.mark_run_completed(run_id)
    return run_id
```

- [ ] **Step 2: Write the endpoint tests**

```python
def test_vcg_validation_endpoint_returns_payload(seed_vcg_backtest_run, client) -> None:
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["credit_proxy"] == "HYG"
    assert body["n_days"] >= 1
    assert body["composite_version"] == "1"
    assert len(body["interpretation_distribution"]) >= 1


def test_vcg_validation_named_crash_window_shape(seed_vcg_backtest_run, client) -> None:
    """Locks the named_crash_window contract that Task 3's endpoint code asserts.

    The persisted JSON uses `offset_d` keys; the response must (a) translate
    these to `offset_days`, (b) look up event labels via NAMED_CRASH_DATES,
    (c) emit offsets in ascending order, and (d) preserve all 7 entries the
    seed fixture inserts.
    """
    resp = client.get("/api/regime/vcg-validation")
    body = resp.json()
    events = body["named_crash_window"]
    assert len(events) == 1, "fixture seeds exactly one event"
    ev = events[0]
    assert ev["date"] == "2008-09-15"
    assert ev["label"] == "Lehman bankruptcy", "label must come from NAMED_CRASH_DATES"
    offsets = ev["offsets"]
    assert [o["offset_days"] for o in offsets] == [-5, -3, -1, 0, 1, 3, 5]
    assert all(isinstance(o["offset_days"], int) for o in offsets)


def test_vcg_validation_503_when_no_completed_run(seeded_db_empty_cards, client) -> None:
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 503
    assert "scripts/backtest_vcg.py" in resp.json()["detail"]


def test_vcg_validation_handles_missing_extras(seeded_db_empty_cards, client) -> None:
    """Endpoint must not crash when summary.extras lacks distribution or window."""
    from datetime import date as _date

    from uw_scan.cards.vcg_scoring import COMPOSITE_VERSION as V
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    run_id = rb.insert_run(
        indicator="vcg",
        composite_version=str(V),
        start_date=_date(2024, 1, 1),
        end_date=_date(2024, 1, 2),
        window_days=21,
        n_days=1,
        params={},
        summary={"oos": None, "extras": {"credit_proxy": "HYG"}},  # no distribution, no window
        note="edge-case test",
    )
    rb.bulk_insert_daily(
        run_id,
        [{"trade_date": _date(2024, 1, 2), "score": 0.0, "level": "NORMAL", "payload": {}}],
    )
    rb.mark_run_completed(run_id)
    resp = client.get("/api/regime/vcg-validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["interpretation_distribution"] == []
    assert body["named_crash_window"] == []
```

- [ ] **Step 3: Run and verify**

Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_regime_vcg_validation_endpoint.py -v`
Expected: 4 passed (happy path, named-crash contract, 503-when-empty, missing-extras-edge-case).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/conftest.py tests/integration/api/test_regime_vcg_validation_endpoint.py
git commit -m "test(api): cover /regime/vcg-validation happy path + 503"
```

## Task 5: Regenerate frontend types

**Files:**
- Modify: `web/lib/types.ts`

**Prereq:** `npm run gen:types` runs `openapi-typescript http://127.0.0.1:8400/openapi.json` — the FastAPI dev server must be listening on port 8400 with the Task 3 router loaded. uvicorn `--reload` should pick the change up automatically; if `scripts/dev.sh` was killed and not restarted, gen:types fails with connection-refused.

- [ ] **Step 1: Verify the API is reachable AND exposes the new path**

```bash
curl -s http://127.0.0.1:8400/openapi.json | jq -r '.paths | keys[]' | grep "vcg-validation"
```
Expected: prints `/api/regime/vcg-validation`. If empty: uvicorn isn't running the new router code; restart it or run `bash scripts/dev.sh` and re-check.

- [ ] **Step 2: Regenerate**

```bash
cd web && npm run gen:types
```

- [ ] **Step 3: Verify new types are present**

```bash
grep -c "VcgValidationResponse" web/lib/types.ts
```
Expected: ≥1. (openapi-typescript generates one schema entry per response model; the count depends on how often the type is referenced — `>=1` is the load-bearing assertion.)

- [ ] **Step 4: Commit (with user approval)**

```bash
git add web/lib/types.ts
git commit -m "chore(web): regen types for VCG validation response"
```

## Task 5b: Regenerate OpenAPI snapshot

**Files:**
- Modify: `tests/integration/api/openapi.snapshot.json`

The snapshot test (`tests/integration/api/test_openapi_snapshot.py`) asserts both `current.paths.keys() == expected.paths.keys()` AND `current.components.schemas == expected.components.schemas`. Adding `/api/regime/vcg-validation` plus 4 new component schemas breaks both — must regenerate.

- [ ] **Step 1: Regenerate via TestClient (no running server needed)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run python -c "
import json, os
os.environ.setdefault('UW_SCAN_API_KEY', 'test-dummy')
from fastapi.testclient import TestClient
from uw_scan.api.server import create_app
spec = TestClient(create_app()).get('/openapi.json').json()
with open('tests/integration/api/openapi.snapshot.json', 'w') as f:
    json.dump(spec, f, indent=2, sort_keys=True)
print('wrote', len(json.dumps(spec)), 'bytes')
"
```

- [ ] **Step 2: Run the snapshot test to confirm green**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```
Expected: PASS.

- [ ] **Step 3: Sanity check the diff before commit**

```bash
git diff --stat tests/integration/api/openapi.snapshot.json
git diff tests/integration/api/openapi.snapshot.json | grep -E '^\+' | grep -E 'vcg-validation|VcgValidation|VcgNamedCrash|VcgInterpretation' | head -20
```
Expected: only additions related to the new endpoint + 4 new schemas; nothing else changes.

- [ ] **Step 4: Commit (with user approval)**

```bash
git add tests/integration/api/openapi.snapshot.json
git commit -m "chore(api): regen OpenAPI snapshot for /regime/vcg-validation"
```

## Task 6: Frontend API URL builder

**Files:**
- Modify: `web/lib/regime/api.ts`

- [ ] **Step 1: Add `vcgValidation()` next to `validation()`**

`web/lib/regime/api.ts` exports `regimeApi` as a `const` object literal. The existing `validation` entry is the last property before `} as const`. Add a sibling using the same `API` base var:

```typescript
  validation: () => `${API}/api/regime/validation`,
  vcgValidation: () => `${API}/api/regime/vcg-validation`,
} as const;
```

(NB: the file uses local var `API`, not `API_BASE` — verify the diff matches the existing convention.)

- [ ] **Step 2: Commit**

```bash
git add web/lib/regime/api.ts
git commit -m "feat(web): add vcgValidation() URL builder"
```

## Task 7: Frontend VCG validation panel

**Files:**
- Create: `web/components/regime/VcgValidationPanel.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";
import type { components } from "@/lib/types";

type VcgValidationResponse = components["schemas"]["VcgValidationResponse"];

export default function VcgValidationPanel({ data }: { data: VcgValidationResponse }) {
  return (
    <div data-testid="vcg-validation-panel">
      <div className="regime-panel-title">VCG BACKTEST ({data.credit_proxy})</div>
      <pre style={{ fontFamily: "var(--font-mono)", fontSize: 12, whiteSpace: "pre-wrap", color: "var(--text-primary)" }}>
        {data.backtest_md}
      </pre>
      <div className="regime-panel-title" style={{ marginTop: 16 }}>INTERPRETATION DISTRIBUTION</div>
      <table className="gex-history-table">
        <thead><tr><th className="text-left">Interpretation</th><th className="text-right">N</th><th className="text-right">%</th></tr></thead>
        <tbody>
          {data.interpretation_distribution.map((row) => (
            <tr key={row.interpretation}>
              <td>{row.interpretation}</td>
              <td className="text-right">{row.n}</td>
              <td className="text-right">{row.pct.toFixed(1)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="regime-panel-title" style={{ marginTop: 16 }}>NAMED-CRASH ±5d WINDOW</div>
      {data.named_crash_window.map((ev) => (
        <div key={ev.date} style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{ev.date} — {ev.label}</div>
          <table className="gex-history-table">
            <thead><tr><th className="text-right">offset</th><th className="text-right">vcg</th><th className="text-right">vcg_adj</th><th className="text-left">interp</th></tr></thead>
            <tbody>
              {ev.offsets.map((o) => (
                <tr key={o.offset_days}>
                  <td className="text-right">{o.offset_days >= 0 ? `+${o.offset_days}` : o.offset_days}</td>
                  <td className="text-right">{o.vcg?.toFixed(2) ?? "—"}</td>
                  <td className="text-right">{o.vcg_adj?.toFixed(2) ?? "—"}</td>
                  <td>{o.interpretation ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/components/regime/VcgValidationPanel.tsx
git commit -m "feat(web): VcgValidationPanel renders backtest evidence"
```

## Task 8: Wire the panel into ValidationTab

**Files:**
- Create: `web/components/regime/CriValidationPanel.tsx` (sub-step 1a)
- Modify: `web/components/regime/ValidationTab.tsx` (sub-step 1b)

- [ ] **Step 1: Add the CRI/VCG sub-selector + fetch routing**

Replace the `useEffect` data loading with state for both indicators:

First, extract the existing CRI render block into its own component so `ValidationTab` becomes a pure switcher.

**Sub-step 1a: Create `web/components/regime/CriValidationPanel.tsx`** (lift the current rendering from `ValidationTab.tsx` lines 37–103, the `<div className="regime-panel" data-testid="validation-tab">…</div>` block) but as a component receiving `{ data: ValidationResponse }`:

```tsx
"use client";
import type { components } from "@/lib/types";

type ValidationResponse = components["schemas"]["ValidationResponse"];

export default function CriValidationPanel({ data }: { data: ValidationResponse }) {
  return (
    <div data-testid="cri-validation-panel">
      <div className="regime-panel-title">WARM-STORE BACKTEST</div>
      <pre style={{ fontFamily: "var(--font-mono)", fontSize: "12px", whiteSpace: "pre-wrap", color: "var(--text-primary)" }}>
        {data.backtest_md}
      </pre>
      <div className="regime-panel-title" style={{ marginTop: 16 }}>OUT-OF-SAMPLE VALIDATION</div>
      {data.oos ? (
        <div data-testid="oos-block">
          <p style={{ fontSize: 13 }}><strong>Method:</strong> {data.oos.method}</p>
          <p style={{ fontSize: 13 }}><strong>As of:</strong> {data.oos.as_of}</p>
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
          <p style={{ fontSize: 13, marginTop: 12, padding: 8, borderLeft: "2px solid var(--text-muted)", color: "var(--text-secondary)" }}>
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

**Sub-step 1b: Rewrite `ValidationTab.tsx` as a switcher:**

The `useRef<number>(0)` request token defends against rapid CRI→VCG→CRI clicks landing responses out of order: each fetch captures the current token; on resolve, if the token doesn't match the latest, the result is dropped. The `cancelled` flag handles unmount; the token handles re-entry while mounted.

```tsx
"use client";
import { useEffect, useRef, useState } from "react";
import type { components } from "@/lib/types";
import { regimeApi } from "@/lib/regime/api";
import CriValidationPanel from "./CriValidationPanel";
import VcgValidationPanel from "./VcgValidationPanel";

type CriResp = components["schemas"]["ValidationResponse"];
type VcgResp = components["schemas"]["VcgValidationResponse"];
type SubTab = "cri" | "vcg";

export default function ValidationTab() {
  const [sub, setSub] = useState<SubTab>("cri");
  const [cri, setCri] = useState<CriResp | null>(null);
  const [vcg, setVcg] = useState<VcgResp | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const reqToken = useRef(0);

  useEffect(() => {
    let cancelled = false;
    setErr(null);
    const token = ++reqToken.current;
    const url = sub === "cri" ? regimeApi.validation() : regimeApi.vcgValidation();
    fetch(url)
      .then(async (r) => {
        if (r.ok) return r.json();
        // Surface the API detail string when available — better UX than "HTTP 503".
        const body = await r.json().catch(() => null);
        const detail = (body && typeof body.detail === "string") ? body.detail : `HTTP ${r.status}`;
        throw new Error(detail);
      })
      .then((d) => {
        if (cancelled || token !== reqToken.current) return;
        if (sub === "cri") setCri(d); else setVcg(d);
      })
      .catch((e) => {
        if (cancelled || token !== reqToken.current) return;
        setErr(String(e.message ?? e));
      });
    return () => { cancelled = true; };
  }, [sub]);

  const loading = (sub === "cri" && !cri) || (sub === "vcg" && !vcg);

  return (
    <div className="regime-panel" data-testid="validation-tab">
      <div className="ticker-tabs" style={{ marginBottom: 16 }} data-testid="validation-sub-tabs">
        <button className={`ticker-tab ${sub === "cri" ? "active" : ""}`} onClick={() => setSub("cri")} data-testid="validation-sub-cri">CRI</button>
        <button className={`ticker-tab ${sub === "vcg" ? "active" : ""}`} onClick={() => setSub("vcg")} data-testid="validation-sub-vcg">VCG</button>
      </div>
      {err && <div data-testid="validation-error">Validation data unavailable: {err}</div>}
      {!err && loading && <div>Loading…</div>}
      {!err && !loading && sub === "cri" && cri && <CriValidationPanel data={cri} />}
      {!err && !loading && sub === "vcg" && vcg && <VcgValidationPanel data={vcg} />}
    </div>
  );
}
```

Notes:
- `setErr(null)` at the start of the effect clears stale errors when switching sub-tabs after a failure.
- The thrown `Error(detail)` uses the API's detail message (e.g., `"no completed VCG backtest run … run scripts/backtest_vcg.py …"`), which is operator-facing. Acceptable for internal use; if this UI later reaches end-users, swap the message at the catch site.

**Sub-step 1c: Migrate `web/tests/unit/ValidationTab.test.tsx` to match the new shell.**

The existing test asserts on `getByTestId("validation-tab")` as a post-fetch race-gate, but after this refactor that node renders **immediately** (it's the new shell wrapping the sub-tab buttons). The `waitFor` becomes meaningless. Change the race-gate to wait for the lifted CRI panel's `data-testid="cri-validation-panel"` or for the `"WARM-STORE BACKTEST"` text:

```tsx
// Replace this line:
//   await waitFor(() => expect(screen.getByTestId("validation-tab")).not.toBeNull());
// with:
await waitFor(() => expect(screen.queryByText("WARM-STORE BACKTEST")).not.toBeNull());
```

Everything else in the existing test stays valid (default sub="cri" + fetch stub → CriValidationPanel renders the same content). This is the only edit; the file is not deleted.

- [ ] **Step 2: Typecheck + dev-server smoke**

```bash
cd web && npm run typecheck
npm run dev
```
Open `http://localhost:3001/regime` → click VALIDATION → click VCG sub-tab → verify the panel renders.

- [ ] **Step 3: Commit (with user approval) — three files**

```bash
git add web/components/regime/CriValidationPanel.tsx \
        web/components/regime/ValidationTab.tsx \
        web/tests/unit/ValidationTab.test.tsx
git commit -m "feat(web): ValidationTab adds CRI/VCG sub-selector"
```

## Task 9: Frontend unit test

**Files:**
- Create: `web/tests/unit/VcgValidationPanel.test.tsx` (the existing `web/tests/unit/` contains flat files like `tradeInsightsTab.test.tsx`; create a `regime/` subdir only if other regime tests already live there — `find web/tests/unit -type d` shows none today, so a flat file matches the current pattern).

- [ ] **Step 1: Write the test**

`@testing-library/jest-dom` is NOT installed in `web/package.json` (verified via `grep -E "@testing-library/jest-dom" web/package.json` — no match). Existing vitest tests use truthy / equality assertions on DOM properties directly, not `toBeInTheDocument()`. Match that pattern:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import VcgValidationPanel from "@/components/regime/VcgValidationPanel";

describe("VcgValidationPanel", () => {
  it("renders the credit proxy and distribution", () => {
    const { container } = render(<VcgValidationPanel data={{
      backtest_md: "# VCG Backtest\n",
      n_days: 100,
      composite_version: "1",
      credit_proxy: "HYG",
      interpretation_distribution: [{ interpretation: "NORMAL", n: 60, pct: 60.0 }],
      named_crash_window: [],
    } as any} />);
    expect(screen.queryByText(/VCG BACKTEST \(HYG\)/)).not.toBeNull();
    expect(screen.queryByText("NORMAL")).not.toBeNull();
    expect(container.querySelector('[data-testid="vcg-validation-panel"]')).not.toBeNull();
  });

  it("renders one sub-table per named-crash event", () => {
    const { container } = render(<VcgValidationPanel data={{
      backtest_md: "# VCG Backtest\n",
      n_days: 4708,
      composite_version: "1",
      credit_proxy: "HYG",
      interpretation_distribution: [{ interpretation: "NORMAL", n: 1, pct: 100.0 }],
      named_crash_window: [{
        date: "2008-09-15",
        label: "Lehman bankruptcy",
        offsets: [-5, -3, -1, 0, 1, 3, 5].map((off) => ({
          offset_days: off, vcg: -0.5, vcg_adj: -0.5,
          beta1: -0.02, beta2: -0.04, sign_ok: true, interpretation: "NORMAL",
        })),
      }],
    } as any} />);
    expect(screen.queryByText(/Lehman bankruptcy/)).not.toBeNull();
    // 7 offset rows in the inner table
    const rows = container.querySelectorAll("tbody tr");
    expect(rows.length).toBeGreaterThanOrEqual(7);
  });
});
```

- [ ] **Step 2: Run vitest**

```bash
cd web && npm run test -- VcgValidationPanel
```
Expected: PASS.

- [ ] **Step 3: Switcher test — covers the failure-mode UX**

Create `web/tests/unit/ValidationTabSwitcher.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ValidationTab from "@/components/regime/ValidationTab";

describe("ValidationTab", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("switches from CRI to VCG and shows error on 503", async () => {
    const cri = {
      backtest_md: "# CRI Backtest\n", backtest_csv_rows: 100,
      oos: { interpretation: "x", method: "y", as_of: "2026-05-25",
             labels: [], scores: [], versions: [] },
    };
    const fetchMock = vi.spyOn(global, "fetch").mockImplementation((url) => {
      const u = String(url);
      if (u.endsWith("/regime/validation")) {
        return Promise.resolve(new Response(JSON.stringify(cri), { status: 200 }));
      }
      return Promise.resolve(new Response(JSON.stringify({ detail: "no run" }), { status: 503 }));
    });
    render(<ValidationTab />);
    await waitFor(() => expect(screen.queryByText(/WARM-STORE BACKTEST/)).not.toBeNull());
    fireEvent.click(screen.getByTestId("validation-sub-vcg"));
    await waitFor(() => expect(screen.queryByText(/Validation data unavailable/)).not.toBeNull());
    // Switch back to CRI — stale error must clear once new fetch succeeds
    fireEvent.click(screen.getByTestId("validation-sub-cri"));
    await waitFor(() => expect(screen.queryByText(/Validation data unavailable/)).toBeNull());
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
```

- [ ] **Step 4: Commit (with user approval) — both test files**

```bash
git add web/tests/unit/VcgValidationPanel.test.tsx web/tests/unit/ValidationTabSwitcher.test.tsx
git commit -m "test(web): cover VcgValidationPanel + ValidationTab sub-tab switching"
```

## Task 10: Open the PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/regime-vcg-validation-ui
```

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(regime): surface VCG backtest evidence in Validation tab" --body "..."
```

PR body should reference this plan and the closure memo item, and include a screenshot of the rendered tab.

---

## Verification gates

After the PR is open:

1. **API contract**: `curl /api/regime/vcg-validation | jq` returns the structured payload; `curl /api/regime/validation | jq` is unchanged.
2. **Type generation**: `web/lib/types.ts` shows the new schemas after `npm run gen:types`.
3. **UI smoke**: open `http://localhost:3001/regime`, click `VALIDATION`, click `VCG`; the panel renders without errors.
4. **Failure mode**: drop the VCG run via SQL (`UPDATE ... SET completed_at = NULL`); UI shows the error path gracefully.
5. **Existing CRI path**: clicking `CRI` sub-tab still works (verifies the refactor didn't break the existing rendering).

## Out of scope (deferred — explicitly listed in closure memo §4)

- VCG v2 recalibration — needs a separate spec under `docs/superpowers/specs/`.
- VCG OOS validation notebook (`vcg-validation.ipynb`) — blocked on choosing a defensible Y-label (forward 5d/20d RV regime? intraday-range expansion?).
- Generic `/api/regime/backtest/{indicator}/runs` listing — only worth adding when a UI consumer needs to compare runs across calibration versions. This PR serves only the latest run, matching the current CRI pattern.

## Why this is highest-ROI

The closure memo §4 explicitly says of the listing endpoint: *"No UI consumer today. Trivially addable when one exists."* This PR creates the first UI consumer for VCG backtest data — turning the backend-only persistence work from #73 into a user-visible feature. Every subsequent VCG research deliverable (v2 calibration, OOS validation, cross-indicator co-firing studies) benefits from having the validation view already wired.

Approx. effort: 1 day (4–5 hours backend including tests, 2–3 hours frontend including tests).
