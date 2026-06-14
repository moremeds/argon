# Regime GRG (Gamma Rotation Gap) Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a 5th regime sub-tab — GRG (Gamma Rotation Gap), a SPY-vs-TLT cross-asset dealer-gamma divergence indicator ported from radon — deep-linkable at `/regime/grg`, backed by a new scanner + snapshot table + API endpoint, with an honest "descriptive, not predictive" research note.

**Architecture:** A UW-bound scanner (`scanners/grg.py`) fetches the SPY & TLT greek-exposure _time-series_ from Unusual Whales (instant 90-day history), reads SPY/TLT gamma-flip + spot from the existing `gex_snapshots` warm store, computes the GRG residual via a pure `cards/grg_scoring.py` (ported verbatim from radon), and persists one self-contained snapshot (full embedded history) to `grg_snapshots`. A single `GET /api/regime/grg` reads the latest snapshot; a worker job re-scans every 15 min RTH + post-close (gamma isn't in the WS feed, so no WS run_live). TLT is added to `gex_scan_tickers` so its flip/spot accrue. The regime page gains a path route `/regime/[[...tab]]` so every sub-tab deep-links.

**Tech Stack:** Python 3.13 (`uv`), FastAPI + Pydantic v2, psycopg 3, APScheduler, NumPy; Next.js 16 + React 19 + TypeScript, hand-rolled SVG (`lib/svgChart.ts`); pytest + pytest-postgresql, Vitest + Playwright.

---

## Reference: radon source (the design being mirrored)

- `/Users/chenxi/projects/radon/scripts/gamma_rotation_gap.py` — the canonical computation. The **math** in Task 3 (`grg_scoring.py`: z-score, spread, classify, gates, `spot_vs_flip` sign) is ported **verbatim** (lines cited inline). The one intentional deviation is the **flip source**: radon recomputes a last-neg→pos-crossing-at/below-spot flip from by-strike rows; argon feeds `grg_scoring` its own canonical persisted flip (`gex_snapshots` `levels.gex_flip.strike`, same as the GEX tab) for one flip definition app-wide. The flip is resolved in the scanner (Task 4), not in `grg_scoring`, so the scoring functions themselves remain verbatim.
- Constants: `HISTORY_DAYS=90`, `Z_WINDOW=63`, `MIN_OBSERVATIONS=70`.
- Key mapping for argon: radon's per-day `net_gamma = call_gamma + put_gamma` (from UW `/greek-exposure`) === argon's `net_gex` from `parse_greek_exposure_history()` (which coalesces `call_gamma`/`call_gex`). We use the UW **history** series for the z-score series AND each asset's latest net gamma; SPY/TLT **flip + spot** come from `gex_snapshots` (radon recomputed the flip from by-strike rows — argon already has it persisted).

## File structure

**Backend (new):**

- `src/uw_scan/storage/migrations/071_grg_snapshots.sql` — snapshot table
- `src/uw_scan/storage/grg_snapshot_repository.py` — `GrgSnapshotRepository` (clone of cri repo, trimmed)
- `src/uw_scan/cards/grg_scoring.py` — pure computation (ported from radon)
- `src/uw_scan/scanners/grg.py` — orchestrator (UW fetch + warm-store flip/spot + persist)

**Backend (modify):**

- `src/uw_scan/api/schemas.py` — add `Grg*` models + `EMPTY_GRG_RESPONSE`
- `src/uw_scan/api/routers/regime.py` — add `GET /grg` + `POST /grg/scan`
- `src/uw_scan/config.py` — add `"TLT"` to `gex_scan_tickers` (field + env default)
- `src/uw_scan/worker/scheduler.py` — add `_regime_grg_scan` job + registration

**Frontend (new):**

- `web/app/regime/[[...tab]]/page.tsx` — optional-catch-all route (replaces `regime/page.tsx`)
- `web/lib/regime/useGrgLive.ts` — `useSyncHook` wrapper
- `web/components/regime/GrgSubTab.tsx` — the tab
- `web/components/regime/GrgDivergenceChart.tsx` — 3-series SVG divergence chart

**Frontend (modify / delete):**

- `web/app/regime/page.tsx` — **delete** (replaced by the catch-all)
- `web/components/regime/RegimePanel.tsx` — accept `initialTab`, sync tab ↔ URL, add `grg`
- `web/lib/regime/api.ts` — add `grg` + `grg_scan`
- `web/lib/types.ts` — regenerate via `npm run gen:types`

**Docs (new):**

- `docs/research/grg-gamma-rotation-gap/CLAUDE.md` — evidence check + verdict

**Tests (new):**

- `tests/unit/test_grg_scoring.py`
- `tests/integration/storage/test_grg_snapshot_repository.py`
- `tests/integration/api/test_regime_grg.py`
- `web/tests/unit/grgFormat.test.ts`
- `web/tests/e2e/regime-grg.spec.ts`

---

## Task 1: Migration — `grg_snapshots` table

**Files:**

- Create: `src/uw_scan/storage/migrations/071_grg_snapshots.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 071_grg_snapshots.sql
--
-- Gamma Rotation Gap (GRG) scanner snapshots. Append-only — every scan
-- inserts a new row. Latest-wins via ORDER BY scanned_at DESC LIMIT 1.
-- Each row's JSONB payload is SELF-CONTAINED: it embeds the full 90-session
-- history array (recomputed from the UW greek-exposure series each scan),
-- so the API serves one row per request — no multi-row history assembly.
-- Indexable scalars are generated columns over the payload (cri/vcg pattern).
-- `basis` mirrors 070: 'eod' is the only writer today (no WS-spliced live
-- path — dealer gamma isn't in the WS feed), but the column keeps the
-- regime-snapshot contract uniform.
-- Source scanner: src/uw_scan/scanners/grg.py
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.grg_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    scanned_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    data_date       DATE,
    payload         JSONB NOT NULL,
    basis           TEXT NOT NULL DEFAULT 'eod',

    grg_z           NUMERIC(10,4) GENERATED ALWAYS AS (((payload->'signal')->>'grg_z')::numeric) STORED,
    interpretation  TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'interpretation') STORED,
    pair_state      TEXT          GENERATED ALWAYS AS ((payload->'signal')->>'state') STORED,
    tier            INTEGER       GENERATED ALWAYS AS (((payload->'signal')->>'tier')::int) STORED,
    spy_net_gamma   NUMERIC(18,4) GENERATED ALWAYS AS (((payload->'assets'->'SPY')->>'net_gamma')::numeric) STORED,
    tlt_net_gamma   NUMERIC(18,4) GENERATED ALWAYS AS (((payload->'assets'->'TLT')->>'net_gamma')::numeric) STORED
);

CREATE INDEX IF NOT EXISTS ix_grg_scanned_at      ON uw_scan.grg_snapshots (scanned_at DESC);
CREATE INDEX IF NOT EXISTS ix_grg_data_date       ON uw_scan.grg_snapshots (data_date DESC);
CREATE INDEX IF NOT EXISTS ix_grg_basis_scanned_at ON uw_scan.grg_snapshots (basis, scanned_at DESC);

COMMIT;
```

- [ ] **Step 2: Apply and verify idempotency**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: both runs succeed; second run is a no-op (no errors). The table exists:
`psql "$(uv run python -c 'from uw_scan.config import Settings; print(Settings.from_env().db_dsn())')" -c '\d uw_scan.grg_snapshots'`
Expected: shows the 5 base columns (id, scanned_at, data_date, payload, basis) + 6 generated columns (grg_z, interpretation, pair_state, tier, spy_net_gamma, tlt_net_gamma) + 3 indexes.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/migrations/071_grg_snapshots.sql
git commit -m "feat(regime): grg_snapshots migration"
```

---

## Task 2: `GrgSnapshotRepository`

GRG snapshots are self-contained (full history embedded), so this repo only needs `insert_snapshot` + `fetch_latest` — no intraday/daily multi-row reads (unlike CRI). Standalone class, not a `Repository` mixin (mirrors `CriSnapshotRepository`).

**Files:**

- Create: `src/uw_scan/storage/grg_snapshot_repository.py`
- Test: `tests/integration/storage/test_grg_snapshot_repository.py`

- [ ] **Step 1: Write the failing integration test**

```python
"""Round-trip tests for GrgSnapshotRepository (pytest-postgresql)."""

from __future__ import annotations

from datetime import date

from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository


def test_insert_and_fetch_latest(seeded_db_empty_cards):
    repo = GrgSnapshotRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    payload = {
        "scan_time": "2026-06-12T19:37:41Z",
        "data_date": "2026-06-12",
        "signal": {"grg_z": -0.79, "interpretation": "RISK_OFF", "state": "RISK_OFF_DIVERGENCE", "tier": 3},
        "assets": {"SPY": {"net_gamma": -702100.0}, "TLT": {"net_gamma": 7700000.0}},
        "history": [{"date": "2026-06-11", "grg_z": -0.5}],
    }
    row_id = repo.insert_snapshot(payload=payload, data_date=date(2026, 6, 12))
    assert isinstance(row_id, int)

    latest = repo.fetch_latest()
    assert latest is not None
    assert latest["signal"]["grg_z"] == -0.79
    assert latest["assets"]["SPY"]["net_gamma"] == -702100.0
    assert latest["scan_time"] == "2026-06-12T19:37:41Z"


def test_fetch_latest_empty_returns_none(seeded_db_empty_cards):
    repo = GrgSnapshotRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert repo.fetch_latest() is None
```

> **Fixture (verified):** `seeded_db_empty_cards` is the storage integration fixture used by `tests/integration/storage/test_cri_snapshot_repository.py:40-45` — it exposes `.conn` and `._schema`. (Defined in `tests/integration/conftest.py:135`.)

- [ ] **Step 2: Run the test — expect failure (module missing)**

Run: `uv run pytest tests/integration/storage/test_grg_snapshot_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.storage.grg_snapshot_repository'`

- [ ] **Step 3: Write the repository**

```python
"""Persistence for Gamma Rotation Gap (GRG) snapshots.

New domain — own file rather than extending repository.py. Append-only;
latest-wins on read. Payloads are self-contained (embed the full 90-session
history), so this repo exposes only insert + fetch_latest.
"""

from __future__ import annotations

from datetime import date

from psycopg import Connection
from psycopg.types.json import Jsonb


class GrgSnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def insert_snapshot(
        self, *, payload: dict, data_date: date | None = None, basis: str = "eod"
    ) -> int:
        sql = """
            INSERT INTO grg_snapshots (data_date, payload, basis)
            VALUES (%s, %s, %s)
            RETURNING id
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (data_date, Jsonb(payload), basis))
            row = cur.fetchone()
        assert row is not None
        self._conn.commit()
        return int(row[0])

    def fetch_latest(self, *, basis: str = "eod") -> dict | None:
        """Most-recent payload for ``basis`` (full self-contained snapshot)."""
        sql = """
            SELECT payload, scanned_at
              FROM grg_snapshots
             WHERE basis = %s
             ORDER BY scanned_at DESC
             LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (basis,))
            row = cur.fetchone()
        if row is None:
            return None
        payload, scanned_at = row
        out = dict(payload or {})
        if scanned_at is not None and not out.get("scan_time"):
            out["scan_time"] = scanned_at.isoformat()
        return out
```

- [ ] **Step 4: Run the test — expect pass**

Run: `uv run pytest tests/integration/storage/test_grg_snapshot_repository.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/grg_snapshot_repository.py tests/integration/storage/test_grg_snapshot_repository.py
git commit -m "feat(regime): GrgSnapshotRepository + round-trip test"
```

---

## Task 3: `cards/grg_scoring.py` — pure computation (ported from radon)

Pure functions, no DB/network. Determinism: takes pre-resolved spot/flip + history rows; no `datetime.now()` inside. Functions ported verbatim from `radon/scripts/gamma_rotation_gap.py` (cited inline).

**Files:**

- Create: `src/uw_scan/cards/grg_scoring.py`
- Test: `tests/unit/test_grg_scoring.py`

- [ ] **Step 1: Write the failing unit tests**

```python
"""Unit tests for GRG scoring (ported from radon gamma_rotation_gap.py)."""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np

from uw_scan.cards import grg_scoring as g


def test_asset_state():
    assert g._asset_state(1.0) == "CUSHION"
    assert g._asset_state(-1.0) == "WHIP"
    assert g._asset_state(0.0) == "NEUTRAL"


def test_pair_state_all_quadrants():
    assert g._pair_state(1.0, -1.0) == "RISK_ON_DIVERGENCE"
    assert g._pair_state(-1.0, 1.0) == "RISK_OFF_DIVERGENCE"
    assert g._pair_state(1.0, 1.0) == "DUAL_CUSHION"
    assert g._pair_state(-1.0, -1.0) == "DUAL_WHIP"
    assert g._pair_state(0.0, 0.0) == "NEUTRAL"


def test_zscore_series_last_point():
    # Constant series then a jump → last z-score is large & positive.
    vals = [1.0] * 30 + [5.0]
    z = g._zscore_series(vals)
    assert z[-1] > 2.0
    # First 9 points lack the 10-obs minimum → NaN.
    assert math.isnan(z[0])


def test_gate_rows_risk_off_polarity_watch():
    # SPY negative, TLT positive (risk-off): polarity gate WATCHes, spy_cushion FAILs.
    rows = g._gate_rows(-2.6, spy_gamma=-1.0, tlt_gamma=1.0, spy_slope_3d=0.5, spy_flip_gap_pct=-0.2)
    by_id = {r["id"]: r for r in rows}
    assert by_id["polarity"]["status"] == "WATCH"
    assert by_id["spy_cushion"]["status"] == "FAIL"
    assert by_id["duration_whip"]["status"] == "WATCH"  # TLT positive → not whipping
    assert by_id["magnitude"]["status"] == "PASS"       # |z| >= 2
    assert by_id["flip"]["status"] == "WATCH"           # spot below flip


def test_classify_bottom_watch():
    res = g._classify_signal(
        grg_z=-2.7, spy_gamma=-1.0, tlt_gamma=1.0, spy_slope_3d=0.5, spy_flip_gap_pct=0.3
    )
    assert res["state"] == "RISK_OFF_DIVERGENCE"
    assert res["interpretation"] == "BOTTOM_WATCH"
    assert res["bottom_score"] >= 4


def _mk_rows(values: list[float], start: date) -> list[dict]:
    return [
        {"date": start + timedelta(days=i), "net_gex": v}
        for i, v in enumerate(values)
    ]


def test_run_analysis_payload_shape():
    # 80 aligned sessions: SPY trending negative, TLT trending positive.
    n = 80
    spy = _mk_rows([1000.0 - 30.0 * i for i in range(n)], date(2026, 1, 1))
    tlt = _mk_rows([1000.0 + 40.0 * i for i in range(n)], date(2026, 1, 1))
    payload = g.run_analysis(
        spy, tlt,
        spy_spot=740.0, spy_flip=735.0, tlt_spot=85.0, tlt_flip=None,
        scan_time="2026-06-12T19:37:41Z", market_open=False,
    )
    assert payload["data_date"] == (date(2026, 1, 1) + timedelta(days=n - 1)).isoformat()
    assert payload["lookback_days"] == n
    assert payload["z_window"] == 63
    assert payload["signal"]["state"] == "RISK_OFF_DIVERGENCE"
    assert payload["assets"]["SPY"]["state"] == "WHIP"
    assert payload["assets"]["TLT"]["state"] == "CUSHION"
    # SPY above its flip → spot_vs_flip positive.
    assert payload["assets"]["SPY"]["spot_vs_flip_pct"] > 0
    assert payload["assets"]["TLT"]["flip"] is None
    assert len(payload["gates"]) == 6
    assert len(payload["history"]) <= g.HISTORY_DAYS
    assert payload["history"][-1]["state"] == "RISK_OFF_DIVERGENCE"


def test_run_analysis_insufficient_observations():
    spy = _mk_rows([1.0] * 10, date(2026, 1, 1))
    tlt = _mk_rows([1.0] * 10, date(2026, 1, 1))
    try:
        g.run_analysis(spy, tlt, spy_spot=1.0, spy_flip=1.0, tlt_spot=1.0, tlt_flip=1.0,
                       scan_time="t", market_open=False)
        assert False, "expected ValueError"
    except ValueError:
        pass
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/unit/test_grg_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.cards.grg_scoring'`

- [ ] **Step 3: Write the scoring module**

```python
"""Pure GRG (Gamma Rotation Gap) scoring — ported from
radon/scripts/gamma_rotation_gap.py.

SPY-vs-TLT cross-asset dealer-gamma divergence. No DB, no network: takes
the UW greek-exposure history rows (date + net_gex per asset) plus
pre-resolved spot/flip, returns the snapshot payload dict.

DESCRIPTIVE indicator — see docs/research/grg-gamma-rotation-gap/CLAUDE.md.
Not validated as predictive.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

HISTORY_DAYS = 90
Z_WINDOW = 63
MIN_OBSERVATIONS = 70


def _f(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(float(value), digits)


def _zscore_series(values: Iterable[float], window: int = Z_WINDOW) -> np.ndarray:
    # radon gamma_rotation_gap.py:65-78 (verbatim)
    arr = np.array(list(values), dtype=float)
    out = np.full(len(arr), np.nan)
    for idx in range(len(arr)):
        start = max(0, idx - window + 1)
        chunk = arr[start : idx + 1]
        valid = chunk[np.isfinite(chunk)]
        if len(valid) < 10:
            continue
        sigma = float(np.std(valid, ddof=1))
        if sigma < 1e-12:
            continue
        out[idx] = (arr[idx] - float(np.mean(valid))) / sigma
    return out


def _slope(values: list[float], length: int = 3) -> float | None:
    # radon :81-85
    valid = [v for v in values if math.isfinite(v)]
    if len(valid) < length + 1:
        return None
    return valid[-1] - valid[-1 - length]


def _asset_state(net_gamma: float) -> str:
    # radon :102-107
    if net_gamma > 0:
        return "CUSHION"
    if net_gamma < 0:
        return "WHIP"
    return "NEUTRAL"


def _pair_state(spy_gamma: float, tlt_gamma: float) -> str:
    # radon :110-119
    if spy_gamma > 0 and tlt_gamma < 0:
        return "RISK_ON_DIVERGENCE"
    if spy_gamma < 0 and tlt_gamma > 0:
        return "RISK_OFF_DIVERGENCE"
    if spy_gamma > 0 and tlt_gamma > 0:
        return "DUAL_CUSHION"
    if spy_gamma < 0 and tlt_gamma < 0:
        return "DUAL_WHIP"
    return "NEUTRAL"


def _state_label(state: str) -> str:
    # radon :122-129
    return {
        "RISK_ON_DIVERGENCE": "Risk-on divergence",
        "RISK_OFF_DIVERGENCE": "Risk-off divergence",
        "DUAL_CUSHION": "Dual cushion",
        "DUAL_WHIP": "Dual whip",
        "NEUTRAL": "Neutral",
    }.get(state, state)


def _classify_signal(
    grg_z: float | None,
    spy_gamma: float,
    tlt_gamma: float,
    spy_slope_3d: float | None,
    spy_flip_gap_pct: float | None,
) -> dict[str, Any]:
    # radon :132-190
    state = _pair_state(spy_gamma, tlt_gamma)
    z = grg_z if grg_z is not None and math.isfinite(grg_z) else 0.0

    top_gates = [
        z >= 2.0,
        spy_gamma > 0,
        spy_slope_3d is not None and spy_slope_3d < 0,
        state == "RISK_ON_DIVERGENCE",
        spy_flip_gap_pct is not None and spy_flip_gap_pct > 0,
    ]
    bottom_gates = [
        z <= -2.0,
        spy_gamma < 0,
        spy_slope_3d is not None and spy_slope_3d > 0,
        state == "RISK_OFF_DIVERGENCE",
        spy_flip_gap_pct is not None and spy_flip_gap_pct > 0,
    ]
    top_score = sum(1 for gate in top_gates if gate)
    bottom_score = sum(1 for gate in bottom_gates if gate)

    if state == "DUAL_WHIP":
        interpretation = "DUAL_WHIP"
        tier: int | None = 2 if abs(z) >= 2 else 3
    elif state == "RISK_ON_DIVERGENCE" and z >= 2.5:
        interpretation = "TOP_WATCH"
        tier = 1 if top_score >= 4 else 2
    elif state == "RISK_ON_DIVERGENCE":
        interpretation = "RISK_ON"
        tier = 3
    elif state == "RISK_OFF_DIVERGENCE" and z <= -2.5:
        interpretation = "BOTTOM_WATCH"
        tier = 1 if bottom_score >= 4 else 2
    elif state == "RISK_OFF_DIVERGENCE":
        interpretation = "RISK_OFF"
        tier = 3
    elif state == "DUAL_CUSHION":
        interpretation = "CUSHION"
        tier = None
    else:
        interpretation = "NORMAL"
        tier = None

    return {
        "state": state,
        "state_label": _state_label(state),
        "interpretation": interpretation,
        "tier": tier,
        "top_watch": interpretation == "TOP_WATCH" or top_score >= 4,
        "bottom_watch": interpretation == "BOTTOM_WATCH" or bottom_score >= 4,
        "top_score": top_score,
        "bottom_score": bottom_score,
    }


def _gate_rows(
    z: float | None,
    spy_gamma: float,
    tlt_gamma: float,
    spy_slope_3d: float | None,
    spy_flip_gap_pct: float | None,
) -> list[dict[str, str]]:
    # radon :193-238
    z_val = z if z is not None and math.isfinite(z) else 0.0
    return [
        {
            "id": "polarity",
            "label": "Polarity",
            "status": "PASS" if spy_gamma > 0 and tlt_gamma < 0 else "WATCH",
            "copy": "SPY positive and TLT negative identifies the clean risk-on divergence.",
        },
        {
            "id": "magnitude",
            "label": "Magnitude",
            "status": "PASS" if abs(z_val) >= 2 else "WATCH",
            "copy": "Absolute GRG above 2σ means the cross-asset gamma spread is statistically stretched.",
        },
        {
            "id": "spy_cushion",
            "label": "SPY cushion",
            "status": "PASS" if spy_gamma > 0 else "FAIL",
            "copy": "Positive SPY gamma means dealer hedging is mechanically dampening equity moves.",
        },
        {
            "id": "duration_whip",
            "label": "TLT whip",
            "status": "PASS" if tlt_gamma < 0 else "WATCH",
            "copy": "Negative TLT gamma means duration moves are mechanically amplified.",
        },
        {
            "id": "decay",
            "label": "Decay",
            "status": "PASS" if spy_slope_3d is not None and spy_slope_3d < 0 else "WATCH",
            "copy": "A negative 3-session SPY gamma slope marks possible equity cushion decay.",
        },
        {
            "id": "flip",
            "label": "Flip",
            "status": "PASS" if spy_flip_gap_pct is not None and spy_flip_gap_pct > 0 else "WATCH",
            "copy": "Spot above the SPY gamma flip keeps the equity cushion valid.",
        },
    ]


def _summary_copy(interpretation: str, state: str) -> str:
    # radon :452-465
    if interpretation == "TOP_WATCH":
        return (
            "SPY gamma support is stretched while TLT gamma remains mechanically "
            "fragile. Treat upside chase as late-cycle until SPY support refreshes."
        )
    if interpretation == "BOTTOM_WATCH":
        return (
            "SPY gamma stress is stretched and repair conditions are forming. Watch "
            "for spot recapturing the gamma flip before calling a bottom."
        )
    if state == "RISK_ON_DIVERGENCE":
        return "SPY gamma is cushioning equities while TLT gamma is amplifying duration moves."
    if state == "RISK_OFF_DIVERGENCE":
        return "SPY gamma is amplifying equity moves while TLT gamma is cushioning duration."
    if state == "DUAL_WHIP":
        return "Both SPY and TLT are short gamma. Cross-asset moves can gap because dealers amplify both sides."
    if state == "DUAL_CUSHION":
        return "Both SPY and TLT are positive gamma. Dealer hedging is dampening both equity and duration moves."
    return "Cross-asset gamma is near neutral."


def _flip_gap_pct(spot: float | None, flip: float | None) -> float | None:
    """Positive when spot is ABOVE the gamma flip (cushion valid).

    radon negates UW's (flip-spot)/spot → (spot-flip)/spot*100.
    """
    if spot is None or flip is None or spot == 0:
        return None
    return (spot - flip) / spot * 100.0


def run_analysis(
    spy_rows: list[dict],
    tlt_rows: list[dict],
    *,
    spy_spot: float | None,
    spy_flip: float | None,
    tlt_spot: float | None,
    tlt_flip: float | None,
    scan_time: str,
    market_open: bool,
) -> dict[str, Any]:
    """Build the GRG snapshot payload from UW greek-exposure history rows.

    ``spy_rows`` / ``tlt_rows`` are ``parse_greek_exposure_history`` output:
    each carries a ``date`` (date obj) and ``net_gex`` (call_gex+put_gex).
    Mirrors radon ``compute_gamma_rotation`` (:333-449).
    """
    spy_history = {
        r["date"].isoformat(): _f(r.get("net_gex"))
        for r in spy_rows
        if r.get("date") is not None
    }
    tlt_history = {
        r["date"].isoformat(): _f(r.get("net_gex"))
        for r in tlt_rows
        if r.get("date") is not None
    }
    dates = sorted(set(spy_history) & set(tlt_history))
    if len(dates) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Only {len(dates)} aligned observations; need {MIN_OBSERVATIONS}"
        )

    spy_values = [spy_history[d] for d in dates]
    tlt_values = [tlt_history[d] for d in dates]
    spy_z = _zscore_series(spy_values)
    tlt_z = _zscore_series(tlt_values)
    spread = spy_z - tlt_z
    grg_z = _zscore_series(spread)

    history: list[dict[str, Any]] = []
    for idx, d in enumerate(dates):
        spy_gamma = spy_values[idx]
        tlt_gamma = tlt_values[idx]
        history.append(
            {
                "date": d,
                "spy_net_gamma": _round(spy_gamma, 4),
                "tlt_net_gamma": _round(tlt_gamma, 4),
                "spy_gamma_z": _round(float(spy_z[idx])) if math.isfinite(float(spy_z[idx])) else None,
                "tlt_gamma_z": _round(float(tlt_z[idx])) if math.isfinite(float(tlt_z[idx])) else None,
                "grg_z": _round(float(grg_z[idx])) if math.isfinite(float(grg_z[idx])) else None,
                "raw_spread": _round(float(spread[idx])) if math.isfinite(float(spread[idx])) else None,
                "state": _pair_state(spy_gamma, tlt_gamma),
            }
        )

    latest_idx = len(dates) - 1
    latest_date = dates[-1]
    spy_cur = spy_values[-1]
    tlt_cur = tlt_values[-1]
    latest_grg = float(grg_z[latest_idx]) if math.isfinite(float(grg_z[latest_idx])) else None
    latest_spread = float(spread[latest_idx]) if math.isfinite(float(spread[latest_idx])) else None
    spy_slope_3d = _slope(spy_values, 3)
    tlt_slope_3d = _slope(tlt_values, 3)
    spy_flip_gap_pct = _flip_gap_pct(spy_spot, spy_flip)
    tlt_flip_gap_pct = _flip_gap_pct(tlt_spot, tlt_flip)

    classification = _classify_signal(latest_grg, spy_cur, tlt_cur, spy_slope_3d, spy_flip_gap_pct)
    gates = _gate_rows(latest_grg, spy_cur, tlt_cur, spy_slope_3d, spy_flip_gap_pct)

    def _asset(
        ticker: str,
        spot: float | None,
        flip: float | None,
        flip_gap_pct: float | None,
        values: list[float],
        z_values: np.ndarray,
        slope_3d: float | None,
    ) -> dict[str, Any]:
        latest_gamma = values[-1]
        one_d = values[-1] - values[-2] if len(values) >= 2 else None
        return {
            "ticker": ticker,
            "spot": _round(spot, 4),
            "data_date": latest_date,
            "net_gamma": _round(latest_gamma, 4),
            "net_gex": _round(latest_gamma, 4),
            "gamma_z": _round(float(z_values[-1])) if math.isfinite(float(z_values[-1])) else None,
            "gamma_1d_change": _round(one_d, 4),
            "gamma_3d_change": _round(slope_3d, 4),
            "state": _asset_state(latest_gamma),
            "flip": _round(flip, 4),
            "spot_vs_flip_pct": _round(flip_gap_pct, 4),
        }

    signal = {
        **classification,
        "grg_z": _round(latest_grg, 4),
        "raw_spread": _round(latest_spread, 4),
        "spy_gamma_z": _round(float(spy_z[-1])) if math.isfinite(float(spy_z[-1])) else None,
        "tlt_gamma_z": _round(float(tlt_z[-1])) if math.isfinite(float(tlt_z[-1])) else None,
        "spy_3d_gamma_change": _round(spy_slope_3d, 4),
        "tlt_3d_gamma_change": _round(tlt_slope_3d, 4),
        "summary": _summary_copy(classification["interpretation"], classification["state"]),
    }

    return {
        "scan_time": scan_time,
        "market_open": market_open,
        "data_date": latest_date,
        "source": "Unusual Whales",
        "lookback_days": len(dates),
        "z_window": Z_WINDOW,
        "basis": "eod",
        "signal": signal,
        "assets": {
            "SPY": _asset("SPY", spy_spot, spy_flip, spy_flip_gap_pct, spy_values, spy_z, spy_slope_3d),
            "TLT": _asset("TLT", tlt_spot, tlt_flip, tlt_flip_gap_pct, tlt_values, tlt_z, tlt_slope_3d),
        },
        "gates": gates,
        "history": history[-HISTORY_DAYS:],
        "top_bottom": {
            "top": {
                "active": bool(signal["top_watch"]),
                "copy": "Potential top: stretched positive GRG, positive SPY gamma, equity cushion decay, and duration gamma stress.",
            },
            "bottom": {
                "active": bool(signal["bottom_watch"]),
                "copy": "Potential bottom: stretched negative GRG, SPY gamma repair, and recapture of the SPY gamma flip after stress.",
            },
        },
    }
```

> **Note on dates (no `date` objects leak into the payload):** `spy_history`/`tlt_history` are keyed by **ISO strings** (`r["date"].isoformat()`). Therefore `dates = sorted(set(...) & set(...))` is a list of ISO strings, so `latest_date` (= `dates[-1]`) and each history row's `"date": d` are plain strings. `payload["data_date"]` is an ISO string, which is why the scanner (Task 4) does `date.fromisoformat(payload["data_date"])` for the `data_date` DB column, and the unit test asserts against `.isoformat()`. The payload is JSON-clean as-is — `Jsonb(...)` never sees a `date` object.

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run pytest tests/unit/test_grg_scoring.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/grg_scoring.py tests/unit/test_grg_scoring.py
git commit -m "feat(regime): grg_scoring pure compute (ported from radon) + unit tests"
```

---

## Task 4: `scanners/grg.py` — orchestrator

UW-bound (fetches SPY+TLT greek-exposure history) + warm-store reads (SPY/TLT flip+spot) + persist. Mirrors the GEX scanner's `run(client, repo, ...)` signature + scan_run audit bracket.

**Files:**

- Create: `src/uw_scan/scanners/grg.py`

- [ ] **Step 1: Write the scanner**

```python
"""GRG (Gamma Rotation Gap) scanner — orchestrator on cards/grg_scoring.

UW-bound: fetches the SPY & TLT greek-exposure time-series from Unusual
Whales (instant 90-session history). Reads SPY/TLT gamma-flip + spot from
the warm-store ``gex_snapshots`` (TLT flip/spot are None until TLT lands in
``gex_scan_tickers`` — GRG still computes from the UW series). Persists one
self-contained snapshot to ``grg_snapshots``.

No WS run_live: dealer gamma is not in the live WS feed, so freshness comes
from the worker re-running this scan (15-min RTH + post-close).
"""

from __future__ import annotations

import logging
from datetime import date as _date
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.cards import grg_scoring
from uw_scan.cards.greek_exposure_history import parse_greek_exposure_history
from uw_scan.sources import uw as uw_source
from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def _is_market_open() -> bool:
    now = datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


def _spot_flip_from_gex(repo: Repository, ticker: str) -> tuple[float | None, float | None]:
    """Spot + gamma-flip read ATOMICALLY from one ``gex_snapshots`` payload.

    Both come from the SAME ``fetch_latest_gex`` row (same ``scanned_at``), so
    they can't be sourced from two different scans (Codex P2#5). Uses argon's
    CANONICAL persisted flip — ``levels.gex_flip.strike``, exactly what the GEX
    tab shows — for one flip definition app-wide. This is an INTENTIONAL
    deviation from radon, which recomputes a last-neg→pos-crossing-at/below-spot
    flip from by-strike rows; see docs/research/grg-gamma-rotation-gap/CLAUDE.md
    "How GRG is presented". Returns ``(None, None)`` when no snapshot exists
    (e.g. TLT before its first GEX scan → flip renders ``---``, matching radon).
    """
    raw = repo.fetch_latest_gex(ticker=ticker)
    if not raw:
        return None, None

    def _num(v: object) -> float | None:
        try:
            return float(v) if v is not None else None  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            log.debug("grg gex coerce skipped %s: %s", ticker, repr(exc))
            return None

    spot = _num(raw.get("spot"))
    flip = None
    levels = raw.get("levels")
    gex_flip = levels.get("gex_flip") if isinstance(levels, dict) else None
    if isinstance(gex_flip, dict):
        flip = _num(gex_flip.get("strike"))
    return spot, flip


def run(
    client: UwClient,
    repo: Repository,
    schema: str = "uw_scan",
    *,
    scan_time: str | None = None,
) -> int | None:
    """Fetch SPY/TLT greek-exposure history, compute GRG, persist a snapshot.

    Returns the inserted row id, or None if there isn't enough aligned data.

    Audit ticker is the synthetic ``GRG`` (NOT ``SPY``): a successful
    ``scan_runs`` row for SPY with ``notes='grg_scan'`` would otherwise be
    picked up by ``latest_run_id('SPY')`` and shadow SPY's real full-scan
    (Codex P1#3). ``grg_scan`` is also added to the ``latest_run_id`` exclusion
    list in Task 7b as defense-in-depth + metric hygiene.
    """
    run_id = repo.insert_scan_run("GRG", notes="grg_scan")
    try:
        spy_rows = parse_greek_exposure_history(
            uw_source.fetch_greek_exposure_history(client, repo, run_id, "SPY")
        )
        tlt_rows = parse_greek_exposure_history(
            uw_source.fetch_greek_exposure_history(client, repo, run_id, "TLT")
        )
        spy_spot, spy_flip = _spot_flip_from_gex(repo, "SPY")
        tlt_spot, tlt_flip = _spot_flip_from_gex(repo, "TLT")
        payload = grg_scoring.run_analysis(
            spy_rows,
            tlt_rows,
            spy_spot=spy_spot,
            spy_flip=spy_flip,
            tlt_spot=tlt_spot,
            tlt_flip=tlt_flip,
            scan_time=scan_time
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            market_open=_is_market_open(),
        )
        # Persist BEFORE marking the run ok (Codex P2#6): a DB failure here
        # must NOT leave an 'ok' audit row with no GRG snapshot. Mirrors gex.py.
        snap_repo = GrgSnapshotRepository(repo.conn, schema=schema)
        data_date = _date.fromisoformat(payload["data_date"])
        row_id = snap_repo.insert_snapshot(payload=payload, data_date=data_date)
    except ValueError as exc:
        log.warning("grg_scan_skipped_thin_data err=%s", repr(exc))
        repo.finish_scan_run(run_id, status="error")
        return None
    except Exception:
        repo.finish_scan_run(run_id, status="error")
        raise

    repo.finish_scan_run(run_id, status="ok")
    log.info(
        "grg_scan_persisted row_id=%d data_date=%s grg_z=%s state=%s",
        row_id,
        data_date,
        payload["signal"]["grg_z"],
        payload["signal"]["state"],
    )
    return row_id
```

> **Verified** (Pass-1/2 review): `insert_scan_run(ticker, notes="")` + `finish_scan_run(run_id, status="ok")` exist (`storage/scan_runs.py:56,68`); `fetch_latest_gex(ticker=...)` returns the full payload with `spot` (`GexResponse.spot`) + `levels.gex_flip.strike` (`scanners/gex.py:511-517`); `UwClient` is `uw_scan.api.client.UwClient`. The flip is argon's persisted canonical flip (one definition app-wide) — a documented, intentional deviation from radon's at/below-spot variant.

- [ ] **Step 2: Smoke-import the module**

Run: `uv run python -c "from uw_scan.scanners import grg; print(grg.run.__doc__[:40])"`
Expected: prints the first line of the docstring (no ImportError).

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/scanners/grg.py
git commit -m "feat(regime): grg scanner (UW history + warm-store flip/spot + persist)"
```

---

## Task 5: API response models in `schemas.py`

**Files:**

- Modify: `src/uw_scan/api/schemas.py` (append after the VCG / regime-live section, near line 541)

- [ ] **Step 1: Add the GRG models**

Append this block (after `VcgLiveResponse`, before any later sections — keep the regime models grouped):

```python
# ─── GRG (Gamma Rotation Gap) ────────────────────────────────────


class GrgGate(BaseModel):
    id: str
    label: str
    status: Literal["PASS", "WATCH", "FAIL"] = "WATCH"
    copy: str = ""


class GrgAsset(BaseModel):
    ticker: str
    spot: float | None = None
    data_date: str | None = None
    net_gamma: float | None = None
    net_gex: float | None = None
    gamma_z: float | None = None
    gamma_1d_change: float | None = None
    gamma_3d_change: float | None = None
    state: Literal["CUSHION", "WHIP", "NEUTRAL"] = "NEUTRAL"
    flip: float | None = None
    spot_vs_flip_pct: float | None = None


class GrgAssets(BaseModel):
    SPY: GrgAsset
    TLT: GrgAsset


class GrgSignal(BaseModel):
    state: Literal[
        "RISK_ON_DIVERGENCE",
        "RISK_OFF_DIVERGENCE",
        "DUAL_CUSHION",
        "DUAL_WHIP",
        "NEUTRAL",
    ] = "NEUTRAL"
    state_label: str = "Neutral"
    interpretation: Literal[
        "TOP_WATCH",
        "BOTTOM_WATCH",
        "RISK_ON",
        "RISK_OFF",
        "DUAL_WHIP",
        "CUSHION",
        "NORMAL",
    ] = "NORMAL"
    tier: int | None = None
    top_watch: bool = False
    bottom_watch: bool = False
    top_score: int = 0
    bottom_score: int = 0
    grg_z: float | None = None
    raw_spread: float | None = None
    spy_gamma_z: float | None = None
    tlt_gamma_z: float | None = None
    spy_3d_gamma_change: float | None = None
    tlt_3d_gamma_change: float | None = None
    summary: str = ""


class GrgHistoryEntry(BaseModel):
    date: str
    spy_net_gamma: float | None = None
    tlt_net_gamma: float | None = None
    spy_gamma_z: float | None = None
    tlt_gamma_z: float | None = None
    grg_z: float | None = None
    raw_spread: float | None = None
    state: str | None = None


class GrgTopBottomSide(BaseModel):
    active: bool = False
    copy: str = ""


class GrgTopBottom(BaseModel):
    top: GrgTopBottomSide = Field(default_factory=GrgTopBottomSide)
    bottom: GrgTopBottomSide = Field(default_factory=GrgTopBottomSide)


class GrgResponse(BaseModel):
    """Gamma Rotation Gap snapshot (latest scan). Self-contained: embeds the
    full 90-session history."""

    status: Literal["ok", "empty"] = "empty"
    scan_time: str = ""
    market_open: bool = False
    data_date: str | None = None
    source: str = "Unusual Whales"
    lookback_days: int = 0
    z_window: int = 63
    basis: Literal["live", "eod"] = "eod"
    signal: GrgSignal = Field(default_factory=GrgSignal)
    assets: GrgAssets | None = None
    gates: list[GrgGate] = Field(default_factory=list)
    history: list[GrgHistoryEntry] = Field(default_factory=list)
    top_bottom: GrgTopBottom = Field(default_factory=GrgTopBottom)


EMPTY_GRG_RESPONSE = GrgResponse()


class GrgScanResponse(BaseModel):
    """Response body for POST /api/regime/grg/scan."""

    status: Literal["ok", "skipped"] = "ok"
    scanner: Literal["grg"] = "grg"
    row_id: int | None = None
    reason: str | None = None
```

- [ ] **Step 2: Verify the models import and an empty instance validates**

Run: `uv run python -c "from uw_scan.api.schemas import GrgResponse, EMPTY_GRG_RESPONSE; print(EMPTY_GRG_RESPONSE.status, EMPTY_GRG_RESPONSE.assets)"`
Expected: `empty None`

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/api/schemas.py
git commit -m "feat(regime): GRG response models"
```

---

## Task 6: API router — `GET /grg` + `POST /grg/scan`

**Files:**

- Modify: `src/uw_scan/api/routers/regime.py`
- Test: `tests/integration/api/test_regime_grg.py`

- [ ] **Step 1: Write the failing API test**

```python
"""GRG regime endpoint contract tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_grg_empty_when_no_snapshot(client: TestClient):
    resp = client.get("/api/regime/grg")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "empty"
    assert body["assets"] is None
    assert body["gates"] == []
    assert body["basis"] == "eod"
```

> **Fixture (verified):** the FastAPI `TestClient` fixture is `client` (`tests/integration/api/conftest.py:34`), not `api_client`. The `test_openapi_snapshot.py` guard also injects `client`.

- [ ] **Step 2: Run — expect failure (404)**

Run: `uv run pytest tests/integration/api/test_regime_grg.py -v`
Expected: FAIL — 404 (route not registered yet)

- [ ] **Step 3: Add the imports**

In `src/uw_scan/api/routers/regime.py`, add to the `from uw_scan.api.schemas import (...)` block:

```python
    EMPTY_GRG_RESPONSE,
    GrgResponse,
    GrgScanResponse,
```

Add to the scanner imports:

```python
from uw_scan.scanners import grg as grg_scanner
```

Add to the storage imports:

```python
from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
```

- [ ] **Step 4: Add the endpoints**

Append after the VCG endpoints (after `/vcg/history`, before `/quotes` is fine):

```python
# ─── GRG (Gamma Rotation Gap) ────────────────────────────────────


@router.get("/grg", response_model=GrgResponse)
def get_grg(
    repo: Annotated[Repository, Depends(get_repo)],
) -> GrgResponse:
    """Latest GRG snapshot (self-contained: embeds 90-session history).

    GRG is EOD/periodic-rescan — the worker owns UW fetches; this read is
    cheap (one snapshot row). No per-request UW spend."""
    snap_repo = GrgSnapshotRepository(repo.conn, schema=repo._schema)
    latest = snap_repo.fetch_latest()
    if latest is None:
        return EMPTY_GRG_RESPONSE.model_copy(deep=True)
    return GrgResponse.model_validate({"status": "ok", **latest})


@router.post("/grg/scan", status_code=202, response_model=GrgScanResponse)
def trigger_grg_scan(
    repo: Annotated[Repository, Depends(get_repo)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> GrgScanResponse:
    """Run a GRG scan synchronously against UW and persist a snapshot."""
    uw_client = UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
    )
    try:
        row_id = grg_scanner.run(uw_client, repo, schema=repo._schema)
    finally:
        uw_client.close()
    if row_id is None:
        return GrgScanResponse(status="skipped", reason="thin_data")
    return GrgScanResponse(status="ok", row_id=row_id)
```

> **Verify** the `UwClient(...)` constructor kwargs match `trigger_gex_scan` in the same file (it uses `api_key=settings.api_key.get_secret_value(), base_url=settings.base_url, timeout=settings.request_timeout_seconds`). Copy that call verbatim if the field names differ.

- [ ] **Step 5: Run the test — expect pass**

Run: `uv run pytest tests/integration/api/test_regime_grg.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/api/routers/regime.py tests/integration/api/test_regime_grg.py
git commit -m "feat(regime): GET /grg + POST /grg/scan endpoints"
```

---

## Task 7: Config (TLT in GEX pipeline) + scheduler job

**Files:**

- Modify: `src/uw_scan/config.py`
- Modify: `src/uw_scan/worker/scheduler.py`

- [ ] **Step 1: Add TLT to `gex_scan_tickers` (field default)**

In `src/uw_scan/config.py` (~line 230):

```python
    gex_scan_tickers: list[str] = ["SPX", "SPY", "TLT"]
```

- [ ] **Step 2: Add TLT to the env-parse default (~line 520)**

```python
            gex_scan_tickers=_parse_csv_env("GEX_SCAN_TICKERS", default=["SPX", "SPY", "TLT"]),
```

- [ ] **Step 3: Add the scheduler job function**

In `src/uw_scan/worker/scheduler.py`, add this nested closure immediately AFTER `_regime_gex_scan` (defined ~line 581) so it shares the same `settings`/`logger` closure scope:

```python
    def _regime_grg_scan() -> None:
        # Gamma Rotation Gap. UW-bound: fetches SPY/TLT greek-exposure history,
        # reads SPY/TLT flip+spot from gex_snapshots, persists grg_snapshots.
        # Mirrors _regime_gex_scan's external-API bracket.
        from uw_scan.scanners import grg as grg_scanner

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="regime_grg_scan"
            ) as uw:
                with _repo(settings) as repo:
                    try:
                        row_id = grg_scanner.run(uw, repo, schema=settings.db_schema)
                        logger.info("regime_grg_scan_tick row_id=%s", row_id)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("regime_grg_scan_failed err=%s", repr(exc))
                        repo.conn.rollback()
```

> **Verified:** `_external_api_recorder`, `_uw_client`, `_repo` all exist (`scheduler.py:226,234,217`). Copy the bracket from `_regime_gex_scan` verbatim.

- [ ] **Step 4: Register the job — INSIDE the `"uw" in groups` + primary-worker guard**

**CRITICAL (Codex P1#2):** GRG is UW-bound, so it must NOT go under the generic `if _is_primary_worker(settings):` block (~line 871). `_is_primary_worker` is true for index-0 of EVERY role (`scheduler.py:156-157`), so that block runs on `uw-0`, `massive-0`, and every `ai-*-0` worker → the GRG UW scan would fire ~5× per tick. The existing `_regime_gex_scan` is correctly registered inside `if "uw" in groups:` (line 723) → `if _is_primary_worker(settings):` (line 756), at line 781. Register GRG right after it, in that SAME guarded block:

```python
        # (immediately after the existing `sched.add_job(_regime_gex_scan, ...)`
        #  at scheduler.py:781, still inside `if "uw" in groups:` →
        #  `if _is_primary_worker(settings):`)

        # GRG scan — SPY/TLT cross-asset gamma divergence. UW-bound; runs every
        # 15 min through RTH + post-close settlement (UW greek-exposure updates
        # after the close). Append-only; safe to re-run.
        sched.add_job(
            _regime_grg_scan,
            CronTrigger(minute="*/15", hour="9-18", day_of_week="mon-fri", timezone=settings.rth_tz),
            id="regime_grg_scan",
            name="Regime GRG scan",
            max_instances=1,
            coalesce=True,
        )
```

> **Deployment note (env/scheduler freeze):** APScheduler workers freeze env at fork and don't hot-reload. The new `regime_grg_scan` job AND the `gex_scan_tickers` TLT addition only take effect after the `uw` worker restarts (`bash scripts/dev.sh` locally; the launchd stack on the mini). **Also (Codex P2#9):** changing the *default* in `config.py` does nothing if the deploy env sets `GEX_SCAN_TICKERS=SPX,SPY` explicitly — check the mini's `.env`/launchd env and add `TLT` there. Local e2e (Task 16) restarts the stack and uses the default, so it's covered locally — flag both for the mini deploy in the PR body.

- [ ] **Step 5: Verify config + scheduler import**

Run: `uv run python -c "from uw_scan.config import Settings; print('TLT' in Settings().gex_scan_tickers)"`
Expected: `True`
Run: `uv run python -c "import uw_scan.worker.scheduler"`
Expected: no error.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/worker/scheduler.py
git commit -m "feat(regime): TLT in gex_scan_tickers + regime_grg_scan job (uw-group guarded)"
```

---

## Task 7b: Exclude `grg_scan` from `latest_run_id` (prevent shadowing SPY)

**Why (Codex P1#3):** the GRG audit row uses the synthetic ticker `GRG` (Task 4), so `latest_run_id('SPY')` already won't see it. This task is defense-in-depth + metric hygiene: any code that filters `gex_scan_%` should also skip `grg_scan`.

**Files:**
- Modify: `src/uw_scan/storage/scan_runs.py`

- [ ] **Step 1: Find every `gex_scan_` exclusion site**

Run: `grep -rn "gex_scan_\|cockpit_daily_snapshot" src/uw_scan/storage/`
Expected: at least `scan_runs.py` `latest_run_id` (line ~49). Note any others (provider/duration metrics).

- [ ] **Step 2: Add the `grg_scan` exclusion to `latest_run_id`**

In `src/uw_scan/storage/scan_runs.py`, in `latest_run_id`'s WHERE clause, after the `gex_scan_%` line (line ~49), add:

```python
                "  AND (notes IS DISTINCT FROM 'grg_scan') "
```

Also add `- ``grg_scan`` (SPY/TLT gamma-rotation gap, grg_snapshots only)` to the docstring's excluded-jobs list. Apply the same `grg_scan` exclusion to any other site Step 1 surfaced.

- [ ] **Step 3: Regression test**

Add to `tests/integration/storage/` (e.g. `test_scan_runs_grg_exclusion.py`):

```python
def test_latest_run_id_ignores_grg_scan(seeded_db_empty_cards):
    db = seeded_db_empty_cards
    # A real SPY full-scan, then a later GRG audit row (synthetic ticker).
    full = db.insert_scan_run("SPY", notes="")
    db.finish_scan_run(full, status="ok")
    grg = db.insert_scan_run("GRG", notes="grg_scan")
    db.finish_scan_run(grg, status="ok")
    # SPY resolves to the real full-scan, not the GRG row.
    assert db.latest_run_id("SPY") == full
```

> `seeded_db_empty_cards` exposes the `Repository` directly (it has `insert_scan_run`/`finish_scan_run`/`latest_run_id` via mixins). If those live only on the bare repo, use `db` as the repo handle (mirror how other `scan_runs` tests call it).

Run: `uv run pytest tests/integration/storage/test_scan_runs_grg_exclusion.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/scan_runs.py tests/integration/storage/test_scan_runs_grg_exclusion.py
git commit -m "fix(storage): exclude grg_scan from latest_run_id"
```

---

## Task 8: Regenerate frontend types

**Files:**

- Modify: `web/lib/types.ts` (generated)

- [ ] **Step 1: Start the API (if not running) and regenerate**

Run (in repo root): `bash scripts/dev.sh` in one shell (or ensure FastAPI is up on 8400), then:
`cd web && npm run gen:types`
Expected: `lib/types.ts` updates; `git diff web/lib/types.ts` shows new `GrgResponse`, `GrgSignal`, `GrgAsset`, `GrgAssets`, `GrgGate`, `GrgHistoryEntry`, `GrgTopBottom`, `GrgTopBottomSide`, `GrgScanResponse` schemas.

- [ ] **Step 2: Verify the type is present**

Run: `grep -c "GrgResponse" web/lib/types.ts`
Expected: ≥ 1

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "chore(types): regen for GRG schemas"
```

---

## Task 9: Frontend API helper + hook

**Files:**

- Modify: `web/lib/regime/api.ts`
- Create: `web/lib/regime/useGrgLive.ts`

- [ ] **Step 1: Add the GRG endpoints to `api.ts`**

In `web/lib/regime/api.ts`, inside the `regimeApi` object (after the `vcg_history` line):

```typescript
  grg: () => `${API}/api/regime/grg`,
  grg_scan: () => `${API}/api/regime/grg/scan`,
```

- [ ] **Step 2: Create the hook**

`web/lib/regime/useGrgLive.ts`:

```typescript
"use client";

import type { components } from "../types";
import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type GrgResponse = components["schemas"]["GrgResponse"];
export type GrgAsset = components["schemas"]["GrgAsset"];
export type GrgGate = components["schemas"]["GrgGate"];
export type GrgHistoryEntry = components["schemas"]["GrgHistoryEntry"];

export function useGrgLive(): UseSyncReturn<GrgResponse> {
  return useSyncHook<GrgResponse>(
    {
      // GET-only. hasPost MUST stay false: the worker owns UW fetches
      // (15-min RTH job). With hasPost the 60s auto-interval would POST
      // /grg/scan every tick → a synchronous UW rescan PER BROWSER TAB
      // every 60s (the exact failure useCriLive's comment warns about).
      // The page just reads the latest persisted snapshot.
      endpoint: regimeApi.grg(),
      interval: 60_000,
      hasPost: false,
      extractTimestamp: (d) => d.scan_time || null,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npm run typecheck`
Expected: no errors referencing `useGrgLive`/`api.ts`. (`GrgSubTab` doesn't exist yet — that's fine; nothing imports the hook until Task 11.)

- [ ] **Step 4: Commit**

```bash
git add web/lib/regime/api.ts web/lib/regime/useGrgLive.ts
git commit -m "feat(regime): grg api helper + useGrgLive hook"
```

---

## Task 10: `GrgDivergenceChart.tsx` — 3-series SVG

The "90-SESSION DIVERGENCE FIELD": GRG / SPY-gamma-z / TLT-gamma-z over the embedded history, fixed ±3σ band. Mirrors `HistoryChart.tsx` (svgChart helpers, LegendSwatch, date ticks).

**Files:**

- Create: `web/components/regime/GrgDivergenceChart.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import type { GrgHistoryEntry } from "@/lib/regime/useGrgLive";

const WIDTH = 880;
const HEIGHT = 260;
const PAD = { top: 16, right: 28, bottom: 36, left: 28 };

// Match the radon palette: GRG amber, SPY teal, TLT pink.
const COLORS = {
  grg: "var(--accent-warm, #F5A623)",
  spy: "var(--accent-bg, #05AD98)",
  tlt: "var(--negative, #FB5E7B)",
  zero: "var(--border-dim)",
  grid: "rgba(148,163,184,0.08)",
};

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: "0.06em",
        color: "var(--text-secondary)",
      }}
    >
      <svg width="12" height="12" aria-hidden="true">
        <circle cx="6" cy="6" r="4" fill={color} />
      </svg>
      {label}
    </span>
  );
}

function dateTickIndices(n: number, count = 5): number[] {
  if (n <= count) return Array.from({ length: n }, (_, i) => i);
  const step = (n - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round(i * step));
}

function shortDate(iso: string): string {
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso;
}

export default function GrgDivergenceChart({
  history,
}: {
  history: GrgHistoryEntry[];
}) {
  if (!history.length) {
    return (
      <div className="section" data-testid="grg-divergence-empty">
        <div className="section-header">
          <div className="section-title">90-Session Divergence Field</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          No history available
        </div>
      </div>
    );
  }

  const xScale = linearScale(
    [0, Math.max(history.length - 1, 1)],
    [PAD.left, WIDTH - PAD.right],
  );

  // Shared z-axis. Anchor to ±3σ but widen if the data exceeds it.
  const zDomain = finiteDomain(
    history.flatMap((h) => [h.grg_z, h.spy_gamma_z, h.tlt_gamma_z]),
  );
  const hi = Math.max(
    3,
    zDomain ? Math.abs(zDomain.hi) : 3,
    zDomain ? Math.abs(zDomain.lo) : 3,
  );
  const yScale = linearScale([-hi, hi], [HEIGHT - PAD.bottom, PAD.top]);

  const seriesPath = (key: "grg_z" | "spy_gamma_z" | "tlt_gamma_z") =>
    pathFromNullablePoints(
      history.map((h, i): [number, number] | null => {
        const v = h[key];
        return v == null ? null : [xScale(i), yScale(v)];
      }),
    );

  const grgPath = seriesPath("grg_z");
  const spyPath = seriesPath("spy_gamma_z");
  const tltPath = seriesPath("tlt_gamma_z");
  const xTickIdx = dateTickIndices(history.length, 5);
  const sigmaTicks = [-3, 0, 3];

  return (
    <div className="section" data-testid="grg-divergence-chart">
      <div className="section-header">
        <div className="section-title">90-Session Divergence Field</div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <LegendSwatch color={COLORS.grg} label="GRG" />
          <LegendSwatch color={COLORS.spy} label="SPY" />
          <LegendSwatch color={COLORS.tlt} label="TLT" />
        </div>
      </div>
      <div className="section-body" style={{ padding: "8px 12px 12px" }}>
        <svg
          role="img"
          aria-label="90-session GRG divergence field"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: HEIGHT, display: "block" }}
        >
          <title>GRG, SPY gamma-z, TLT gamma-z over 90 sessions</title>

          {sigmaTicks.map((s) => {
            const y = yScale(s);
            return (
              <g key={`sig${s}`}>
                <line
                  x1={PAD.left}
                  x2={WIDTH - PAD.right}
                  y1={y}
                  y2={y}
                  stroke={s === 0 ? COLORS.zero : COLORS.grid}
                  strokeDasharray={s === 0 ? "2 3" : undefined}
                />
                <text
                  x={PAD.left}
                  y={y - 3}
                  fontSize={9}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-muted)"
                >
                  {s > 0 ? `+${s}σ` : `${s}σ`}
                </text>
              </g>
            );
          })}

          {xTickIdx.map((i) => {
            const x = xScale(i);
            const entry = history[i];
            if (!entry?.date) return null;
            return (
              <text
                key={`X${i}`}
                x={x}
                y={HEIGHT - PAD.bottom + 16}
                textAnchor="middle"
                fontSize={10}
                fontFamily="var(--font-mono)"
                fill="var(--text-secondary)"
              >
                {shortDate(entry.date)}
              </text>
            );
          })}

          <path
            d={tltPath}
            fill="none"
            stroke={COLORS.tlt}
            strokeWidth={1.2}
            strokeLinecap="round"
            opacity={0.85}
          />
          <path
            d={spyPath}
            fill="none"
            stroke={COLORS.spy}
            strokeWidth={1.2}
            strokeLinecap="round"
            opacity={0.85}
          />
          <path
            d={grgPath}
            fill="none"
            stroke={COLORS.grg}
            strokeWidth={1.8}
            strokeLinecap="round"
          />
        </svg>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npm run typecheck`
Expected: no errors in `GrgDivergenceChart.tsx`.

- [ ] **Step 3: Commit**

```bash
git add web/components/regime/GrgDivergenceChart.tsx
git commit -m "feat(regime): GRG divergence SVG chart"
```

---

## Task 11: `GrgSubTab.tsx` — the tab

Mirrors the radon layout (hero residual + tiles → SPY/TLT cards → divergence chart → top/bottom → gates) in argon's style (inline styles + CSS vars + `formatters`). `data-testid`s throughout for Playwright.

**Files:**

- Create: `web/components/regime/GrgSubTab.tsx`

- [ ] **Step 1: Write the component**

```tsx
"use client";

import GrgDivergenceChart from "./GrgDivergenceChart";
import InfoTooltip from "./InfoTooltip";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "./primitives/format";
import {
  useGrgLive,
  type GrgAsset,
  type GrgGate,
  type GrgResponse,
} from "@/lib/regime/useGrgLive";

const METHODOLOGY =
  "GRG = z-score of (SPY gamma-z − TLT gamma-z) over a 63-session window. " +
  "Positive dealer gamma cushions moves; negative gamma whips them. A SPY/TLT " +
  "divergence flags a cross-asset risk rotation. DESCRIPTIVE indicator — the " +
  "gamma→vol mechanic is peer-reviewed, but the cross-asset gap signal is an " +
  "unvalidated hypothesis (no forward-return backtest). See " +
  "docs/research/grg-gamma-rotation-gap.";

function fmtGex(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "---";
  // radon shows a signed magnitude ("-702.1K", "+7.7M").
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

function gexColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

function gateColor(status: string): string {
  switch (status) {
    case "PASS":
      return "var(--positive)";
    case "FAIL":
      return "var(--negative)";
    default:
      return "var(--warning)";
  }
}

function residualColor(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "var(--text-primary)";
  if (z <= -1) return "var(--negative)";
  if (z >= 1) return "var(--positive)";
  return "var(--text-primary)";
}

function Tile({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      style={{
        padding: "10px 12px",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "1.5px",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 20,
          fontWeight: 700,
          fontFamily: "var(--font-mono)",
          marginTop: 4,
        }}
      >
        {value}
      </div>
      {sub ? (
        <div
          style={{
            fontSize: 10,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            marginTop: 2,
          }}
        >
          {sub}
        </div>
      ) : null}
    </div>
  );
}

function AssetCard({ asset }: { asset: GrgAsset }) {
  const pill =
    asset.state === "CUSHION"
      ? "CUSHION"
      : asset.state === "WHIP"
        ? "WHIP"
        : "NEUTRAL";
  const pillColor =
    asset.state === "CUSHION"
      ? "var(--positive)"
      : asset.state === "WHIP"
        ? "var(--negative)"
        : "var(--text-muted)";
  return (
    <div className="section" data-testid={`grg-asset-${asset.ticker}`}>
      <div className="section-header">
        <div className="section-title">{asset.ticker}</div>
        <span
          style={{
            border: `1px solid ${pillColor}`,
            color: pillColor,
            borderRadius: 999,
            padding: "2px 10px",
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            letterSpacing: "1px",
          }}
        >
          {pill}
        </span>
      </div>
      <div className="section-body" style={{ padding: "12px" }}>
        <div
          style={{
            fontSize: 30,
            fontWeight: 700,
            fontFamily: "var(--font-mono)",
            color: gexColor(asset.net_gamma),
          }}
        >
          {fmtGex(asset.net_gamma)}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto",
            gap: "6px 12px",
            marginTop: 12,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
          }}
        >
          <span style={{ color: "var(--text-muted)" }}>GAMMA Z</span>
          <span style={{ textAlign: "right" }}>
            {formatSignedNumber(asset.gamma_z)}
            {asset.gamma_z != null ? "σ" : ""}
          </span>
          <span style={{ color: "var(--text-muted)" }}>SPOT</span>
          <span style={{ textAlign: "right" }}>{formatNumber(asset.spot)}</span>
          <span style={{ color: "var(--text-muted)" }}>FLIP</span>
          <span style={{ textAlign: "right" }}>{formatNumber(asset.flip)}</span>
          <span style={{ color: "var(--text-muted)" }}>SPOT VS FLIP</span>
          <span style={{ textAlign: "right" }}>
            {formatPercent(asset.spot_vs_flip_pct)}
          </span>
        </div>
      </div>
    </div>
  );
}

function GatesPanel({ gates }: { gates: GrgGate[] }) {
  return (
    <div className="section" data-testid="grg-gates">
      <div className="section-header">
        <div className="section-title">Signal Gates</div>
      </div>
      <div
        className="section-body"
        style={{
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {gates.map((gate) => (
          <div
            key={gate.id}
            data-testid={`grg-gate-${gate.id}`}
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                letterSpacing: "1px",
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {gate.label}
            </span>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              {gate.copy}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                fontWeight: 700,
                color: gateColor(gate.status),
              }}
            >
              {gate.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function GrgSubTabView({ data }: { data: GrgResponse | null }) {
  if (!data || data.status === "empty" || !data.assets) {
    return (
      <div className="regime-empty" data-testid="grg-empty">
        No GRG snapshot yet. The scanner runs every 15 min (market hours + post-close settlement).
      </div>
    );
  }

  const { signal, gates, history, top_bottom } = data;
  const assets = data.assets; // non-null: guarded by the early return above
  const stateColor =
    signal.state === "RISK_OFF_DIVERGENCE" || signal.state === "DUAL_WHIP"
      ? "var(--negative)"
      : signal.state === "RISK_ON_DIVERGENCE" || signal.state === "DUAL_CUSHION"
        ? "var(--positive)"
        : "var(--text-muted)";

  return (
    <div className="gex-panel" data-testid="grg-panel">
      {/* Hero */}
      <div className="section" data-testid="grg-hero">
        <div className="section-header">
          <div
            className="section-title"
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            Gamma Rotation Gap
            <InfoTooltip
              text={METHODOLOGY}
              ariaLabel="GRG methodology"
              triggerTestId="grg-info"
            />
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <span
              data-testid="grg-state-badge"
              style={{
                border: `1px solid ${stateColor}`,
                color: stateColor,
                borderRadius: 999,
                padding: "2px 10px",
                fontSize: 10,
                fontFamily: "var(--font-mono)",
                letterSpacing: "1px",
              }}
            >
              {signal.state_label.toUpperCase()}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--text-muted)",
              }}
            >
              {data.data_date ?? ""}
            </span>
          </div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 16,
            display: "grid",
            gridTemplateColumns: "minmax(220px, 1fr) 2fr",
            gap: 16,
            alignItems: "center",
          }}
        >
          <div>
            <div
              style={{
                fontSize: 10,
                letterSpacing: "1.5px",
                textTransform: "uppercase",
                color: "var(--text-muted)",
                fontFamily: "var(--font-mono)",
              }}
            >
              GRG Residual
            </div>
            <div
              data-testid="grg-residual"
              style={{
                fontSize: 56,
                fontWeight: 700,
                fontFamily: "var(--font-mono)",
                lineHeight: 1.05,
                color: residualColor(signal.grg_z),
              }}
            >
              {formatSignedNumber(signal.grg_z)}
              {signal.grg_z != null ? "σ" : ""}
            </div>
            <div style={{ fontSize: 16, fontWeight: 600, marginTop: 6 }}>
              {signal.state_label}
            </div>
            <div
              style={{
                fontSize: 12,
                color: "var(--text-secondary)",
                marginTop: 6,
                maxWidth: 380,
              }}
            >
              {signal.summary}
            </div>
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 10,
            }}
          >
            <Tile
              label="SPY GEX"
              value={fmtGex(assets.SPY.net_gamma)}
              sub={`${formatSignedNumber(assets.SPY.gamma_z)}σ`}
            />
            <Tile
              label="TLT GEX"
              value={fmtGex(assets.TLT.net_gamma)}
              sub={`${formatSignedNumber(assets.TLT.gamma_z)}σ`}
            />
            <Tile
              label="Top Gate"
              value={`${signal.top_score}/5`}
              sub={signal.top_watch ? "active" : "inactive"}
            />
            <Tile
              label="Bottom Gate"
              value={`${signal.bottom_score}/5`}
              sub={signal.bottom_watch ? "active" : "inactive"}
            />
          </div>
        </div>
      </div>

      {/* Asset cards + chart */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1fr) 2fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <AssetCard asset={assets.SPY} />
          <AssetCard asset={assets.TLT} />
        </div>
        <GrgDivergenceChart history={history} />
      </div>

      {/* Top / Bottom identification */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 16,
          marginTop: 16,
        }}
      >
        <div className="section" data-testid="grg-top">
          <div className="section-header">
            <div className="section-title">Top Identification</div>
          </div>
          <div
            className="section-body"
            style={{
              padding: 12,
              fontSize: 12,
              color: "var(--text-secondary)",
            }}
          >
            {top_bottom.top.copy}
            <div
              style={{
                marginTop: 8,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: top_bottom.top.active
                  ? "var(--warning)"
                  : "var(--text-muted)",
              }}
            >
              {top_bottom.top.active
                ? "TOP WATCH ACTIVE"
                : "NO CONFIRMED TOP WATCH"}
            </div>
          </div>
        </div>
        <div className="section" data-testid="grg-bottom">
          <div className="section-header">
            <div className="section-title">Bottom Identification</div>
          </div>
          <div
            className="section-body"
            style={{
              padding: 12,
              fontSize: 12,
              color: "var(--text-secondary)",
            }}
          >
            {top_bottom.bottom.copy}
            <div
              style={{
                marginTop: 8,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: top_bottom.bottom.active
                  ? "var(--warning)"
                  : "var(--text-muted)",
              }}
            >
              {top_bottom.bottom.active
                ? "BOTTOM WATCH ACTIVE"
                : "NO CONFIRMED BOTTOM WATCH"}
            </div>
          </div>
        </div>
      </div>

      {/* Gates */}
      <div style={{ marginTop: 16 }}>
        <GatesPanel gates={gates} />
      </div>
    </div>
  );
}

export default function GrgSubTab() {
  const { data } = useGrgLive();
  return <GrgSubTabView data={data} />;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npm run typecheck`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add web/components/regime/GrgSubTab.tsx
git commit -m "feat(regime): GrgSubTab UI"
```

---

## Task 12: Routing — `/regime/[[...tab]]` + RegimePanel URL sync

Convert the regime page to an optional-catch-all so `/regime/grg` (and every other sub-tab) deep-links and is Playwright-addressable. The optional catch-all `[[...tab]]` ALSO matches `/regime`, so the flat `regime/page.tsx` must be deleted (two routes can't match the same path).

**Files:**

- Delete: `web/app/regime/page.tsx`
- Create: `web/app/regime/[[...tab]]/page.tsx`
- Modify: `web/components/regime/RegimePanel.tsx`

- [ ] **Step 1: Delete the old flat page**

```bash
git rm web/app/regime/page.tsx
```

- [ ] **Step 2: Create the catch-all page**

`web/app/regime/[[...tab]]/page.tsx`:

```tsx
import RegimePanel from "@/components/regime/RegimePanel";
import VolBackdropStrip from "@/components/regime/VolBackdropStrip";

export const metadata = {
  title: "Regime — Unusual Whales",
  description: "Market-wide regime indicators: GEX, CRI, VCG, GRG",
};

const VALID_TABS = new Set([
  "gex",
  "cri",
  "vcg",
  "grg",
  "canary",
  "validation",
]);

export default async function RegimePage({
  params,
}: {
  params: Promise<{ tab?: string[] }>;
}) {
  const { tab } = await params;
  const first = tab?.[0];
  const initialTab = first && VALID_TABS.has(first) ? first : "gex";
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">
          Crash Risk Indicator · Vol-Curve Gauge · Gamma Exposure · Gamma
          Rotation Gap
        </p>
      </header>
      <VolBackdropStrip />
      <RegimePanel initialTab={initialTab} />
    </main>
  );
}
```

> **Note:** Next.js 16 / React 19 — `params` is a Promise (async dynamic API). `await params` is correct here. If the project's Next minor still types `params` as a plain object, drop the `Promise<>` wrapper + `await` to match the other dynamic routes (check `web/app/stock/[ticker]/page.tsx` for the in-repo convention and mirror it exactly).

- [ ] **Step 3: Update RegimePanel — accept `initialTab`, add GRG, sync URL**

Replace `web/components/regime/RegimePanel.tsx` with:

```tsx
"use client";

import { usePathname, useRouter } from "next/navigation";
import { useMarketHours } from "@/lib/regime/useMarketHours";
import CanarySubTab from "./CanarySubTab";
import CriSubTab from "./CriSubTab";
import GexSubTab from "./GexSubTab";
import GrgSubTab from "./GrgSubTab";
import ValidationTab from "./ValidationTab";
import VcgSubTab from "./VcgSubTab";

type RegimeTab = "cri" | "vcg" | "grg" | "canary" | "gex" | "validation";

const TABS: { id: RegimeTab; label: string }[] = [
  { id: "gex", label: "GEX" },
  { id: "cri", label: "CRI" },
  { id: "vcg", label: "VCG" },
  { id: "grg", label: "GRG" },
  { id: "canary", label: "5% CANARY" },
  { id: "validation", label: "VALIDATION" },
];

const VALID = new Set<RegimeTab>(TABS.map((t) => t.id));

function coerce(tab: string | undefined): RegimeTab {
  return tab && VALID.has(tab as RegimeTab) ? (tab as RegimeTab) : "gex";
}

export default function RegimePanel({ initialTab }: { initialTab?: string }) {
  const pathname = usePathname();
  const router = useRouter();
  const marketState = useMarketHours();

  // usePathname() is the single source of truth — robust to <Link>,
  // router.push, AND browser back/forward (all update the pathname), which the
  // old popstate-only listener missed (Codex P2#8). `initialTab` is the
  // server-rendered first-paint fallback. URL shape /regime/<tab>; bare
  // /regime → segment undefined → coerce → "gex".
  const seg = pathname?.split("/")[2];
  const activeTab = coerce(seg ?? initialTab);

  function selectTab(id: RegimeTab) {
    // router.push keeps usePathname in sync. Navigating within the SAME
    // [[...tab]] segment re-renders (does NOT unmount) RegimePanel, and the
    // per-endpoint module cache in useSyncHook repaints data instantly, so
    // poll state effectively survives. scroll:false avoids a jump to top.
    router.push(`/regime/${id}`, { scroll: false });
  }

  return (
    <div className="regime-panel" data-testid="regime-panel">
      <div
        className="ticker-tabs"
        style={{ marginBottom: "16px" }}
        data-testid="regime-tabs"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            className={`ticker-tab ${activeTab === tab.id ? "active" : ""}`}
            onClick={() => selectTab(tab.id)}
            data-testid={`regime-tab-${tab.id}`}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {activeTab === "gex" && <GexSubTab marketState={marketState} />}
      {activeTab === "cri" && <CriSubTab />}
      {activeTab === "vcg" && <VcgSubTab />}
      {activeTab === "grg" && <GrgSubTab />}
      {activeTab === "canary" && <CanarySubTab />}
      {activeTab === "validation" && <ValidationTab />}
    </div>
  );
}
```

- [ ] **Step 4: Typecheck + lint**

Run: `cd web && npm run typecheck && npm run lint`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add web/app/regime web/components/regime/RegimePanel.tsx
git commit -m "feat(regime): /regime/[[...tab]] deep-link routing + GRG tab wired"
```

---

## Task 13: Research note — thesis verification

**Files:**

- Create: `docs/research/grg-gamma-rotation-gap/CLAUDE.md`

- [ ] **Step 1: Write the note**

```markdown
# GRG — Gamma Rotation Gap: evidence check

> SPY-vs-TLT cross-asset dealer-gamma divergence. Ported from radon
> (`scripts/gamma_rotation_gap.py`). This note records what the academic /
> practitioner literature actually supports, so the indicator is presented
> honestly: **descriptive, not predictive.** (Mirrors the VCG precedent —
> see docs memory `project_vcg_forward_returns_descriptive`.)

## The thesis, in four claims

1. Dealer net gamma (GEX) in equity index ETFs (SPY) mechanically
   dampens/amplifies realized vol (positive = cushion, negative = whip).
2. The same mechanic applies to bond ETFs (TLT) for duration vol.
3. A SPY-vs-TLT gamma divergence signals a cross-asset risk-off rotation.
4. The gap has tradeable / forward-predictive content.

## Verdict

| Claim                                              | Grounding                                                                      | Verdict                                                                     |
| -------------------------------------------------- | ------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| 1. Gamma → realized vol (equity index)             | Peer-reviewed                                                                  | **Established mechanic.**                                                   |
| 2. Same mechanic in bonds (TLT)                    | Peer-reviewed for MBS/swaption **convexity hedging**, NOT TLT option gamma     | **Mechanism real; TLT-GEX application is an analogy, not a tested result.** |
| 3. SPY-vs-TLT gamma divergence = risk-off rotation | Vendor/blog only; flight-to-safety regimes exist but not identified from gamma | **Practitioner folklore + novel untested combination.**                     |
| 4. Gap is tradeable / forward-predictive           | No peer-reviewed support; one quasi-academic source shows post-2020 decay      | **Speculative. Not presented as established.**                              |

## Sources (verified)

**Claim 1 — gamma → vol (supports):**

- Barbon & Buraschi, "Gamma Fragility" (2021), SSRN 3725454 — negative dealer gamma → amplification, positive → suppression. (Working paper.)
- Baltussen, Da, Lammers & Martens, "Hedging Demand and Market Intraday Momentum," JFE 142(1) (2021) — option-MM + leveraged-ETF gamma hedging drives intraday momentum across equities, bonds, commodities, FX. (Peer-reviewed; also seeds claim 2.)
- Soebhag, "Option Gamma and Stock Returns," J. Empirical Finance 74 (2023) — net gamma predicts future realized vol (hedging channel).
- Dim, Eraker & Vilkov, "0DTEs: Trading, Gamma Risk and Volatility Propagation" (2023), SSRN 4692190 — higher dealer net gamma → lower intraday RV.
- Ni, Pearson & Poteshman, "Stock Price Clustering on Option Expiration Dates," JFE 78(1) (2005) — MM hedge rebalancing mechanically moves the underlying.
- Gârleanu, Pedersen & Poteshman, "Demand-Based Option Pricing," RFS 22(10) (2009) — dealers net short options bear hedging demand (structural premise).
- SqueezeMetrics GEX white paper (c. 2017) — practitioner origin of the GEX vocabulary; **not peer-reviewed, no verifiable author.**

**Claim 2 — bond/rates convexity hedging (supports the mechanism, NOT TLT options):**

- Hanson, "Mortgage Convexity," JFE 113(2) (2014).
- Malkhozov, Mueller, Vedolin & Venter, "Mortgage Risk and the Yield Curve," RFS 29(5) (2016).
- Perli & Sack, "Does Mortgage Hedging Amplify Movements in Long-Term Interest Rates?" Fed FEDS 2003-49 (2003).
- **Caveat:** these are MBS/swaption convexity-hedging flows — much larger and structurally different from TLT-listed-option dealer gamma. The TLT-GEX lens is a reasonable analogy, not what these papers tested.

**Claims 3 & 4 — the gap signal (no peer-reviewed support):**

- Flight-to-safety regimes are real: Baele & Bekaert et al., "Flights to Safety," NBER w19095 (RFS) — but FTS is identified from returns/correlation/VIX, **not** gamma.
- The cross-asset gamma-gap-as-rotation-signal appears only in vendor material (SpotGamma, Barchart, blogs). No peer-reviewed test of its forward-return content; the one quasi-academic GEX-predictiveness source (a DiVA student thesis) reports the effect weakening post-2020.

## How GRG is presented in argon

- The UI labels GRG a **descriptive cross-asset gamma-state indicator** (InfoTooltip in `GrgSubTab.tsx`), explicitly noting the gap-signal is an unvalidated hypothesis with no forward-return backtest.
- **Flip definition (intentional deviation from radon):** the flip gate + `spot_vs_flip` use argon's **canonical persisted gamma flip** (`gex_snapshots` `levels.gex_flip.strike`, the same flip the GEX tab shows) — one flip definition app-wide. radon instead recomputes a last-negative→positive-crossing-at/below-spot flip from by-strike rows. Consequence: when argon's flip sits above spot, GRG's flip gate / `spot_vs_flip` can differ in sign from radon. The headline GRG residual, pair state, and summary are flip-independent, so this only affects one of six gates.
- A forward-return / per-regime catastrophic-degradation backtest (the VCG-style validation gate) is the **next** gate before any predictive claim — deliberately out of scope for this PR.
```

- [ ] **Step 2: Commit**

```bash
git add docs/research/grg-gamma-rotation-gap/CLAUDE.md
git commit -m "docs(regime): GRG thesis evidence check (descriptive, not predictive)"
```

---

## Task 14: Frontend unit test (vitest)

Test the pure formatting/color helpers without mounting the network hook. Extract nothing — re-implement the trivial expectations against the component's exported helpers if they're exported; otherwise test a tiny local copy. Simplest: test the gauge-independent helpers by importing the format primitives already used.

**Files:**

- Create: `web/tests/unit/grgFormat.test.ts`

- [ ] **Step 1: Write the test**

```typescript
import { describe, expect, it } from "vitest";
import {
  formatNumber,
  formatPercent,
  formatSignedNumber,
} from "@/components/regime/primitives/format";

describe("regime format primitives (used by GRG)", () => {
  it("formats null as ---", () => {
    expect(formatNumber(null)).toBe("---");
    expect(formatPercent(undefined)).toBe("---");
    expect(formatSignedNumber(null)).toBe("---");
  });

  it("signs positive numbers", () => {
    expect(formatSignedNumber(0.04)).toBe("+0.04");
    expect(formatPercent(0.24)).toBe("+0.24%");
  });

  it("keeps negative sign", () => {
    expect(formatSignedNumber(-0.79)).toBe("-0.79");
  });
});
```

> If you want coverage of GRG-specific logic, additionally export `fmtGex`/`gateColor` from `GrgSubTab.tsx` and assert `fmtGex(-702100) === "-702.1K"`, `gateColor("FAIL") === "var(--negative)"`. Keep the export minimal (named exports alongside the default).

- [ ] **Step 2: Run**

Run: `cd web && npm run test -- grgFormat`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add web/tests/unit/grgFormat.test.ts
git commit -m "test(regime): GRG format helper unit tests"
```

---

## Task 15: Playwright e2e

Validates the end goal: `/regime/grg` deep-links, the GRG tab is active, and the panel renders.

**Files:**

- Create: `web/tests/e2e/regime-grg.spec.ts`

- [ ] **Step 1: Write the spec**

```typescript
import { expect, test } from "@playwright/test";

test.describe("Regime GRG tab", () => {
  test("deep-links to /regime/grg with the GRG tab active", async ({
    page,
  }) => {
    await page.goto("/regime/grg");
    // Tab strip rendered and GRG is the active tab.
    await expect(page.getByTestId("regime-tabs")).toBeVisible();
    await expect(page.getByTestId("regime-tab-grg")).toHaveClass(/active/);
    // Either the populated panel or the empty-state renders (both are valid
    // depending on whether a snapshot exists locally).
    const panel = page.getByTestId("grg-panel");
    const empty = page.getByTestId("grg-empty");
    await expect(panel.or(empty)).toBeVisible();
  });

  test("clicking the GRG tab updates the URL", async ({ page }) => {
    await page.goto("/regime/gex");
    await page.getByTestId("regime-tab-grg").click();
    await expect(page).toHaveURL(/\/regime\/grg$/);
    await expect(page.getByTestId("regime-tab-grg")).toHaveClass(/active/);
  });
});
```

> **Note:** the Playwright `baseURL` is set in `web/playwright.config.ts` (the dev server port — argon web is **3001**, not 3000). Use the project's existing config; do not hardcode a port in the spec.

- [ ] **Step 2: Run (requires the dev stack up)**

Run: `cd web && npm run test:e2e -- regime-grg`
Expected: PASS (2 tests). If the API has no snapshot, the empty-state branch satisfies the assertion.

- [ ] **Step 3: Commit**

```bash
git add web/tests/e2e/regime-grg.spec.ts
git commit -m "test(regime): GRG deep-link + tab-switch e2e"
```

---

## Task 16: Full verification gate

- [ ] **Step 1: Migrations idempotent**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: both succeed, second is a no-op.

- [ ] **Step 2: Regenerate the OpenAPI snapshot (CI guard — Codex P1#4)**

New routes (`/grg`, `/grg/scan`) + schemas (`Grg*`) change the OpenAPI doc, and `tests/integration/api/test_openapi_snapshot.py` compares `paths` keys + `components.schemas` against `tests/integration/api/openapi.snapshot.json`. With the API running on 8400:

Run: `curl -s http://127.0.0.1:8400/openapi.json | jq . > tests/integration/api/openapi.snapshot.json`
Then verify the guard passes:
Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: PASS. `git diff` shows the snapshot gained the GRG paths + schemas (and nothing unrelated).

> If formatting matters, mirror whatever the committed snapshot uses (the test only compares parsed dicts, so `jq .` is safe). If there's a repo helper to regenerate it, prefer that.

- [ ] **Step 3: Python tests + lint (full suite — not just GRG)**

Run the targeted GRG tests first, then the FULL suite (the snapshot/contract guards live outside the GRG test files):
`uv run pytest tests/unit/test_grg_scoring.py tests/integration/storage/test_grg_snapshot_repository.py tests/integration/storage/test_scan_runs_grg_exclusion.py tests/integration/api/test_regime_grg.py -v`
Then: `uv run pytest -q` (full suite — confirms the OpenAPI snapshot + models-export guards pass).
Expected: all PASS.
Run: `uv run ruff check src/uw_scan/cards/grg_scoring.py src/uw_scan/scanners/grg.py src/uw_scan/storage/grg_snapshot_repository.py src/uw_scan/storage/scan_runs.py`
Expected: clean.

- [ ] **Step 4: Frontend gates**

Run: `cd web && npm run typecheck && npm run lint && npm run test`
Expected: all pass (gen:types already committed in Task 8).

- [ ] **Step 5: Real worker-path smoke (UW spend) — produce a live snapshot**

Per the "deliver results through the real worker path" rule, do NOT hand-insert a snapshot. Either:

- trigger the real endpoint: `curl -XPOST http://127.0.0.1:8400/api/regime/grg/scan` (needs `UW_SCAN_API_KEY` in the API env), then `curl http://127.0.0.1:8400/api/regime/grg | jq '.status, .signal.grg_z, .assets.SPY.state, .assets.TLT.state'`
- or let the scheduled `regime_grg_scan` job run.
  Expected: `status="ok"`, a finite `grg_z`, SPY/TLT states. If TLT GEX hasn't scanned yet, `assets.TLT.flip` is null (`---` in UI) — acceptable.

- [ ] **Step 6: Playwright e2e against the running stack**

Run: `cd web && npm run test:e2e -- regime-grg`
Expected: PASS. Capture a screenshot to `output/playwright/regime-grg.png` for PR evidence:
`cd web && npx playwright test regime-grg --reporter=line` then save a screenshot via the spec or a one-off `page.screenshot`.

- [ ] **Step 7: Final commit (scoped — Codex P3#11)**

The worktree already has unrelated untracked files (other plans, screenshots). Do NOT `git add -A`. Stage only GRG paths and the regenerated snapshot:

```bash
git add src/uw_scan tests web docs/research/grg-gamma-rotation-gap \
        tests/integration/api/openapi.snapshot.json
git commit -m "chore(regime): GRG verification fixups"
```

(Adjust to whatever actually changed; verify with `git status` before committing.)

---

## Self-review notes (spec coverage)

- **Both data-source decision** → Task 3/4 (UW history series for net gamma) + Task 7 (TLT added to `gex_scan_tickers`). ✓
- **EOD + RTH rescan** → Task 7 cron `*/15 9-18 mon-fri`; no WS run_live (documented in Task 4 docstring). ✓
- **Path route /regime/grg** → Task 12 optional-catch-all + RegimePanel URL sync. ✓
- **Research note + honest UI framing** → Task 13 doc + Task 11 `METHODOLOGY` InfoTooltip. ✓
- **Module budget** — every new file < 500 lines (grg_scoring ~330, grg ~110, GrgSubTab ~300). ✓
- **Persist to Postgres** — grg_snapshots. ✓
- **Resolved in review (Pass 1/2):** fixtures are `seeded_db_empty_cards` (storage) + `client` (API); `UwClient` ctor kwargs, `_uw_client`/`_external_api_recorder`/`_repo`, `insert_scan_run`/`finish_scan_run`, `GexResponse.spot` + `levels.gex_flip.strike`, and Next 16 `params: Promise` all verified to exist. Scheduler now under the `"uw" in groups` guard (Task 7); `grg_scan` excluded from `latest_run_id` (Task 7b); OpenAPI snapshot regenerated (Task 16); hook is GET-only.
- **Residual risk:** whether the UW tier serves TLT *by-strike* GEX for the gex pipeline — low-risk; GRG degrades to `flip=null` (`---`) and still computes from the UW history series. Confirm in Task 16 Step 5.

---

## Execution handoff

End goal (per user): `/review-cycle` this plan → `/execute-plan` if confidence is high → local Playwright e2e → push PR when e2e is green.
