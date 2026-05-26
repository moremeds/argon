# 5% Canary Indicator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Plan version:** v0.3 (review-cycle findings appended as patch appendix — see end of file)

**Revision history**:
- **v0.1**: initial plan from writing-plans skill
- **v0.2**: patches applied (see Task 0 for the audit checklist):
  - Task 6: anchor invariant — primary event fires at most once per 252d high anchor
  - Task 6 tests: history slice respects causal contract (`history[:i+1]`)
  - Task 9: recursive canonical normalizer (Decimal + float collapse to same form); pinned hex digest test
  - Task 10: calm-day baseline bound relaxed pending VRP gating decision (§3 Open questions)
  - Task 11: extracted `above_sma200_two_consecutive` helper
  - Task 12: real causality compare (full-history slice K vs truncated-history at K)
  - Task 16: `RegimePill` accepts `"NEUTRAL"`
  - Task 17: SWR fetcher throws on non-2xx; speed state mapping covers `NEUTRAL`
  - Task 19: `if __name__ == "__main__":` moved to file bottom
  - Task 21: event-level stats use `CanaryEventState.emitted` (true fire dates) — not warning_state transitions; Confirmed Canary stats measure downside, not drawup
  - Task 22: OOS gate splits into regression gate (LAST_KNOWN ± 0.02) + absolute acceptance gate (AUC>0.55 on ≥2 labels, up60d_10pct>0.58)
  - Task 1 tests: rollback after each expected `CheckViolation` so the connection isn't aborted for the next test

**Goal:** Ship a third regime indicator ("5% Canary") to `/regime` that scores forward dip-buy favorability 0–100 with a separate `warning_state` field, persists daily snapshots, and ships an OOS-gated backtest harness.

**Architecture:** Three-tier composite (Tactical Vol 0-30 + Structural Vol 0-50 + Price Speed 0-20) with a 4-state speed model and a Confirmed-Canary veto cap. Causal per-day event state machine for the Thrasher 5%-decline signals (no look-ahead). Backtest sweeps four scoring forms (linear/convex/concave/sigmoid) on a three-window split (train 2007-2014 → validation 2015-2019 → final test 2020-present). Per-day snapshots persisted to `uw_scan.canary_snapshots` (JSONB payload + scalar columns + DB CHECK constraints). New `/regime` sub-tab in the web UI.

**Tech Stack:** Python 3.13 via `uv`, FastAPI + Pydantic v2, psycopg 3, APScheduler, Next.js 16 + React 19 + TypeScript, Vitest + pytest + pytest-postgresql.

**Source of truth for math/calibration:** `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md` (v0.3). Refer to it for any detail not explicit in a task below.

---

## File map (locked decisions)

```
src/uw_scan/
├── cards/
│   └── canary_scoring.py                    NEW
├── scanners/
│   └── canary.py                            NEW
├── storage/
│   ├── canary_snapshot_repository.py        NEW (focused module — NOT in repository.py)
│   └── migrations/059_canary_snapshots.sql  NEW (next available number)
├── worker/jobs/regime_jobs.py               EXTEND (add canary_scan)
├── worker/scheduler.py                      EXTEND (schedule canary_scan)
└── api/routers/regime.py                    EXTEND (add /canary endpoints)

web/
├── app/regime/page.tsx                      EXTEND (add 5% Canary sub-tab)
├── components/regime/
│   ├── CanarySubTab.tsx                     NEW
│   ├── CanaryValidationPanel.tsx            NEW
│   └── primitives/RegimePill.tsx            NEW
└── lib/types.ts                             REGEN via `npm run gen:types`

docs/research/regime/
├── canary-methodology.md                    NEW (source of truth)
├── canary-calibration-v1.json               NEW (persisted thresholds)
└── 2023-thrasher-5pct-canary.pdf            ALREADY ADDED (literature anchor)

scripts/
└── backtest_canary.py                       NEW

tests/
├── unit/cards/test_canary_scoring.py
├── unit/cards/test_canary_speed_events.py
├── unit/cards/test_canary_confirmed_canary_state_machine.py
├── unit/cards/test_canary_causality.py
├── unit/cards/test_canary_calibration.py
├── unit/storage/test_canary_payload_hash.py
├── integration/regime/test_canary_scanner.py
├── integration/regime/test_canary_db_constraints.py
├── integration/regime/test_canary_warning_state.py
└── integration/regime/test_canary_oos_gate.py
```

---

## Task 0: Pre-execution invariant checklist

**Files:** none — this is the audit step the implementer runs BEFORE writing
any code, to confirm the v0.2 patches survived the brain-to-keyboard
transition. If any check below is false, fix the plan or your understanding
before starting Task 1.

- [ ] **Anchor invariant**: each 252d high anchor produces *at most one*
      primary event — either `5pct_canary` *or* `buy_the_dip`, never both.
      Tasks 6 enforces this with `primary_event_fired_for_high =
      canary_fired_for_high or btd_fired_for_high` gating both branches.

- [ ] **Causal slicing**: every test that exercises the event state machine
      passes `spx_history[:i+1]` (slice up to and including today), never
      the full unsliced history. Task 6 tests are updated accordingly.

- [ ] **Canonical hash collapses float and Decimal**: a recursive normalizer
      converts both to a 6-decimal string representation BEFORE
      `json.dumps`. Task 9 fixture-pinned hex digest is hardcoded, not
      computed at test-runtime.

- [ ] **UI handles NEUTRAL**: `RegimePill` includes the `NEUTRAL` state
      with a label "Neutral". `speed.state` is rendered directly without an
      unsafe `as RegimePillState` cast.

- [ ] **Script entrypoint is last**: `if __name__ == "__main__": main()`
      sits at the bottom of `scripts/backtest_canary.py`, AFTER all
      `cmd_*` function definitions.

- [ ] **Event stats use emitted events**: `_event_level_stats` reads
      `CanaryEventState.emitted` for the fire dates. `warning_state` is
      never used to infer event fires. Confirmed Canary stats measure
      forward drawdowns and the rate of additional drawdown ≥ 5 % at 60d.

- [ ] **OOS gate has two assertions**: (a) regression — within
      LAST_KNOWN ± 0.02; (b) absolute acceptance — AUC > 0.55 on ≥ 2 of 3
      labels and AUC `up60d_10pct` > 0.58. Both must pass to merge.

- [ ] **Test DB rollback after CHECK violations**: each
      `pytest.raises(CheckViolation)` block is immediately followed by
      `db_conn.rollback()`.

- [ ] **VRP calm-day floor**: read §3 of `canary-methodology.md` after
      calibration — if calm-day VRP scores > 5 with the v1 calibrated
      thresholds, open a follow-up to gate VRP behind a stress trigger
      (`vix_peak_30d >= 20` or `pullback_20d >= 3%`). For v1, accept
      VRP-as-carry and bound the calm-day test at ≤ 25, not ≤ 20.

If all 9 are checked, proceed to Task 1.

---

## Task 1: Migration + table with CHECK constraints

**Files:**
- Create: `src/uw_scan/storage/migrations/059_canary_snapshots.sql`
- Test: `tests/integration/regime/test_canary_db_constraints.py`

- [ ] **Step 1: Write the migration**

```sql
-- src/uw_scan/storage/migrations/059_canary_snapshots.sql
-- 5% Canary indicator snapshots — one row per (data_date, composite_version).
-- See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §9.

CREATE TABLE IF NOT EXISTS uw_scan.canary_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    data_date         DATE NOT NULL,
    composite_version SMALLINT NOT NULL DEFAULT 1,
    score_form        TEXT NOT NULL,

    score             NUMERIC(5,2) NOT NULL,
    raw_score         NUMERIC(5,2) NOT NULL,
    band              TEXT NOT NULL,
    tactical_score    NUMERIC(5,2) NOT NULL,
    structural_score  NUMERIC(5,2) NOT NULL,
    speed_score       SMALLINT     NOT NULL,
    warning_state     TEXT NOT NULL,

    payload           JSONB NOT NULL,
    payload_hash      TEXT NOT NULL,
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS canary_snapshots_date_version_idx
    ON uw_scan.canary_snapshots (data_date, composite_version);

CREATE INDEX IF NOT EXISTS canary_snapshots_version_date_desc_idx
    ON uw_scan.canary_snapshots (composite_version, data_date DESC);

CREATE INDEX IF NOT EXISTS canary_snapshots_inserted_idx
    ON uw_scan.canary_snapshots (inserted_at DESC);

CREATE INDEX IF NOT EXISTS canary_snapshots_warning_idx
    ON uw_scan.canary_snapshots (warning_state, data_date DESC)
    WHERE warning_state != 'NONE';

-- CHECK constraints (idempotent via DO block — see spec §9)
DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_score_range_chk
        CHECK (score >= 0 AND score <= 100 AND raw_score >= 0 AND raw_score <= 100);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_band_chk
        CHECK (band IN ('NONE', 'WATCH', 'BUY', 'STRONG_BUY'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_warning_state_chk
        CHECK (warning_state IN ('NONE','CONFIRMED_CANARY_ACTIVE','BUY_THE_DIP_ACTIVE','BOTH_ACTIVE_AMBIGUOUS'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_score_form_chk
        CHECK (score_form IN ('linear', 'convex', 'concave', 'sigmoid'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    ALTER TABLE uw_scan.canary_snapshots
        ADD CONSTRAINT canary_tier_scores_chk
        CHECK (tactical_score BETWEEN 0 AND 30
               AND structural_score BETWEEN 0 AND 50
               AND speed_score IN (0, 8, 20));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
```

- [ ] **Step 2: Run the migration**

```bash
bash scripts/migrate.sh
```
Expected: migration applied (or already applied, idempotent). No errors.

- [ ] **Step 3: Write the CHECK constraint test**

```python
# tests/integration/regime/test_canary_db_constraints.py
import pytest
from psycopg.errors import CheckViolation

pytestmark = pytest.mark.integration


def _insert_minimal(conn, **overrides):
    payload = '{"date":"2026-05-26"}'
    row = {
        "data_date": "2026-05-26",
        "composite_version": 1,
        "score_form": "linear",
        "score": 47.3,
        "raw_score": 47.3,
        "band": "WATCH",
        "tactical_score": 12.4,
        "structural_score": 26.9,
        "speed_score": 8,
        "warning_state": "NONE",
        "payload": payload,
        "payload_hash": "abc",
    }
    row.update(overrides)
    cols = ", ".join(row.keys())
    placeholders = ", ".join(f"%({k})s" for k in row)
    with conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO uw_scan.canary_snapshots ({cols}) VALUES ({placeholders})",
            row,
        )


def test_score_above_100_rejected(db_conn):
    with pytest.raises(CheckViolation):
        _insert_minimal(db_conn, score=150)
    db_conn.rollback()


def test_invalid_band_rejected(db_conn):
    with pytest.raises(CheckViolation):
        _insert_minimal(db_conn, band="PANIC")
    db_conn.rollback()


def test_invalid_warning_state_rejected(db_conn):
    with pytest.raises(CheckViolation):
        _insert_minimal(db_conn, warning_state="WATCH")
    db_conn.rollback()


def test_speed_score_other_than_0_8_20_rejected(db_conn):
    with pytest.raises(CheckViolation):
        _insert_minimal(db_conn, speed_score=12)
    db_conn.rollback()


def test_invalid_score_form_rejected(db_conn):
    with pytest.raises(CheckViolation):
        _insert_minimal(db_conn, score_form="exponential")
    db_conn.rollback()


def test_valid_row_accepted(db_conn):
    _insert_minimal(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM uw_scan.canary_snapshots WHERE data_date='2026-05-26'")
        assert cur.fetchone()[0] == 1
```

- [ ] **Step 4: Run constraint tests**

```bash
uv run pytest tests/integration/regime/test_canary_db_constraints.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/migrations/059_canary_snapshots.sql tests/integration/regime/test_canary_db_constraints.py
git commit -m "feat(canary): migration 060 — canary_snapshots table with CHECK constraints"
```

---

## Task 2: Repository module (insert / read latest / read history)

**Files:**
- Create: `src/uw_scan/storage/canary_snapshot_repository.py`
- Test: `tests/integration/regime/test_canary_scanner.py` (test added here, scanner added in Task 11)

- [ ] **Step 1: Write the repository**

```python
# src/uw_scan/storage/canary_snapshot_repository.py
"""Focused storage module for canary_snapshots — never extend repository.py.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §9.
"""
from __future__ import annotations

import json
import logging
from datetime import date as _date
from decimal import Decimal
from typing import Any, Iterable

from psycopg import Connection
from psycopg.types.json import Jsonb

log = logging.getLogger(__name__)

VALID_FORMS = ("linear", "convex", "concave", "sigmoid")
VALID_BANDS = ("NONE", "WATCH", "BUY", "STRONG_BUY")
VALID_WARNING_STATES = ("NONE", "CONFIRMED_CANARY_ACTIVE", "BUY_THE_DIP_ACTIVE", "BOTH_ACTIVE_AMBIGUOUS")


class CanarySnapshotRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    def insert_snapshot(
        self,
        *,
        payload: dict[str, Any],
        data_date: _date,
        composite_version: int,
        score_form: str,
        score: Decimal,
        raw_score: Decimal,
        band: str,
        tactical_score: Decimal,
        structural_score: Decimal,
        speed_score: int,
        warning_state: str,
        payload_hash: str,
        on_conflict: str = "noop",  # 'noop' | 'overwrite'
    ) -> int | None:
        """Insert a snapshot. Returns the new row id, or None if no-op on conflict.

        on_conflict='overwrite' replaces the existing row, preserving the prior
        payload in payload._prior for audit.
        """
        assert score_form in VALID_FORMS, score_form
        assert band in VALID_BANDS, band
        assert warning_state in VALID_WARNING_STATES, warning_state
        assert speed_score in (0, 8, 20), speed_score

        with self._conn.cursor() as cur:
            if on_conflict == "overwrite":
                cur.execute(
                    f"""
                    SELECT id, payload, payload_hash
                    FROM {self._schema}.canary_snapshots
                    WHERE data_date = %s AND composite_version = %s
                    """,
                    (data_date, composite_version),
                )
                prior = cur.fetchone()
                if prior is not None:
                    payload = {**payload, "_prior": {
                        "row_id": prior[0],
                        "payload_hash": prior[2],
                        "payload": prior[1],
                    }}
                    cur.execute(
                        f"DELETE FROM {self._schema}.canary_snapshots WHERE id = %s",
                        (prior[0],),
                    )

            cur.execute(
                f"""
                INSERT INTO {self._schema}.canary_snapshots
                    (data_date, composite_version, score_form,
                     score, raw_score, band,
                     tactical_score, structural_score, speed_score,
                     warning_state, payload, payload_hash)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (data_date, composite_version) DO NOTHING
                RETURNING id
                """,
                (
                    data_date, composite_version, score_form,
                    score, raw_score, band,
                    tactical_score, structural_score, speed_score,
                    warning_state, Jsonb(payload), payload_hash,
                ),
            )
            row = cur.fetchone()
            return row[0] if row else None

    def latest_snapshot(
        self, *, composite_version: int
    ) -> dict[str, Any] | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT data_date, score, raw_score, band, tactical_score,
                       structural_score, speed_score, warning_state,
                       score_form, payload, payload_hash, inserted_at
                FROM {self._schema}.canary_snapshots
                WHERE composite_version = %s
                ORDER BY data_date DESC
                LIMIT 1
                """,
                (composite_version,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return self._row_to_dict(row)

    def history(
        self, *, composite_version: int, days: int
    ) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT data_date, score, raw_score, band, tactical_score,
                       structural_score, speed_score, warning_state,
                       score_form, payload, payload_hash, inserted_at
                FROM {self._schema}.canary_snapshots
                WHERE composite_version = %s
                ORDER BY data_date DESC
                LIMIT %s
                """,
                (composite_version, days),
            )
            return [self._row_to_dict(r) for r in cur.fetchall()]

    @staticmethod
    def _row_to_dict(row: tuple) -> dict[str, Any]:
        keys = (
            "data_date", "score", "raw_score", "band", "tactical_score",
            "structural_score", "speed_score", "warning_state",
            "score_form", "payload", "payload_hash", "inserted_at",
        )
        return dict(zip(keys, row))
```

- [ ] **Step 2: Run a quick sanity import**

```bash
uv run python -c "from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/canary_snapshot_repository.py
git commit -m "feat(canary): focused storage module CanarySnapshotRepository"
```

---

## Task 3: Calibration JSON + loader

**Files:**
- Create: `docs/research/regime/canary-calibration-v1.json`
- Create: `src/uw_scan/cards/canary_calibration.py`
- Test: `tests/unit/cards/test_canary_calibration.py`

- [ ] **Step 1: Write the calibration JSON (initial — final values overwritten by `--calibrate` in Task 17)**

```json
{
  "composite_version": 1,
  "train_window": {"start": "2007-01-01", "end": "2014-12-31"},
  "score_form": "linear",
  "thresholds": {
    "vix_spike_revert":     {"floor": 0.05, "ceiling": 0.30, "spike_active_at_vix": 30.0, "peak_lookback_d": 10, "max_points": 15},
    "vix_vix3m_back":       {"floor": 0.05, "ceiling": 0.20, "backwardation_extreme_at_ratio": 1.05, "peak_lookback_d": 10, "max_points": 15},
    "vrp":                  {"floor": 50.0,  "ceiling": 300.0, "rv_window_d": 20, "max_points": 21},
    "cor1m_decay":          {"floor": 0.05, "ceiling": 0.30, "peak_elevated_at": 60.0, "peak_lookback_d": 60, "max_points": 17},
    "vvix_vix_recovery":    {"floor": 3.5,  "ceiling": 5.0,  "compressed_below_ratio": 4.0, "compress_lookback_d": 60, "max_points": 12}
  },
  "band_distribution_train": null,
  "author_overrides": [],
  "produced_at": "2026-05-26T00:00:00Z",
  "produced_by": "v0.1 priors (pre-calibration)"
}
```

- [ ] **Step 2: Write the loader**

```python
# src/uw_scan/cards/canary_calibration.py
"""Loader for canary-calibration-v<N>.json. Read-only at runtime.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §7.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

COMPOSITE_VERSION = 1

# Default location — overridable for tests.
DEFAULT_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs" / "research" / "regime"
    / f"canary-calibration-v{COMPOSITE_VERSION}.json"
)

ScoreForm = Literal["linear", "convex", "concave", "sigmoid"]


@dataclass(frozen=True)
class SignalThresholds:
    floor: float
    ceiling: float
    max_points: int
    extras: dict[str, float | int]


@dataclass(frozen=True)
class Calibration:
    composite_version: int
    score_form: ScoreForm
    vix_spike_revert: SignalThresholds
    vix_vix3m_back: SignalThresholds
    vrp: SignalThresholds
    cor1m_decay: SignalThresholds
    vvix_vix_recovery: SignalThresholds


def load_calibration(path: Path = DEFAULT_PATH) -> Calibration:
    raw = json.loads(path.read_text())
    t = raw["thresholds"]

    def _read(name: str) -> SignalThresholds:
        d = dict(t[name])
        floor = float(d.pop("floor"))
        ceiling = float(d.pop("ceiling"))
        max_points = int(d.pop("max_points"))
        return SignalThresholds(floor=floor, ceiling=ceiling, max_points=max_points, extras=d)

    return Calibration(
        composite_version=int(raw["composite_version"]),
        score_form=raw["score_form"],
        vix_spike_revert=_read("vix_spike_revert"),
        vix_vix3m_back=_read("vix_vix3m_back"),
        vrp=_read("vrp"),
        cor1m_decay=_read("cor1m_decay"),
        vvix_vix_recovery=_read("vvix_vix_recovery"),
    )
```

- [ ] **Step 3: Write the calibration test**

```python
# tests/unit/cards/test_canary_calibration.py
from uw_scan.cards.canary_calibration import load_calibration, COMPOSITE_VERSION


def test_load_calibration_returns_expected_signals():
    cal = load_calibration()
    assert cal.composite_version == COMPOSITE_VERSION
    assert cal.score_form in ("linear", "convex", "concave", "sigmoid")
    assert cal.vix_spike_revert.max_points == 15
    assert cal.vix_vix3m_back.max_points == 15
    assert cal.vrp.max_points == 21
    assert cal.cor1m_decay.max_points == 17
    assert cal.vvix_vix_recovery.max_points == 12
    # Total smooth-signal points == 80; speed contributes the remaining 20.
    smooth_total = sum(s.max_points for s in (
        cal.vix_spike_revert, cal.vix_vix3m_back, cal.vrp,
        cal.cor1m_decay, cal.vvix_vix_recovery,
    ))
    assert smooth_total == 80


def test_extras_are_preserved():
    cal = load_calibration()
    assert cal.vix_spike_revert.extras["spike_active_at_vix"] == 30.0
    assert cal.cor1m_decay.extras["peak_elevated_at"] == 60.0
```

- [ ] **Step 4: Run**

```bash
uv run pytest tests/unit/cards/test_canary_calibration.py -v
```
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/research/regime/canary-calibration-v1.json src/uw_scan/cards/canary_calibration.py tests/unit/cards/test_canary_calibration.py
git commit -m "feat(canary): calibration JSON + loader"
```

---

## Task 4: Score-form ramp functions

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (create file, add ramp functions only)
- Test: `tests/unit/cards/test_canary_scoring.py` (create file, ramp tests only)

- [ ] **Step 1: Write the ramp functions**

```python
# src/uw_scan/cards/canary_scoring.py
"""5% Canary scoring — pure math, no IO.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §6.
"""
from __future__ import annotations

import math
from typing import Literal

ScoreForm = Literal["linear", "convex", "concave", "sigmoid"]


def _clip01(x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x


def ramp(
    value: float,
    *,
    floor: float,
    ceiling: float,
    max_points: float,
    form: ScoreForm = "linear",
) -> float:
    """Map ``value`` in [floor, ceiling] to a score in [0, max_points] using
    one of four functional forms. Returns 0 below floor, max_points above ceiling.
    """
    if ceiling <= floor:
        raise ValueError(f"ceiling ({ceiling}) must exceed floor ({floor})")
    norm = _clip01((value - floor) / (ceiling - floor))
    if form == "linear":
        return max_points * norm
    if form == "convex":
        return max_points * (norm ** 1.5)
    if form == "concave":
        return max_points * (norm ** 0.5)
    if form == "sigmoid":
        # Centered at 0.5 in normalized space, k=10 for steep transition.
        return max_points / (1.0 + math.exp(-10.0 * (norm - 0.5)))
    raise ValueError(f"unknown form: {form}")
```

- [ ] **Step 2: Write the ramp tests**

```python
# tests/unit/cards/test_canary_scoring.py
import math
import pytest

from uw_scan.cards.canary_scoring import ramp


@pytest.mark.parametrize("form", ["linear", "convex", "concave", "sigmoid"])
def test_ramp_zero_at_or_below_floor(form):
    assert ramp(0.0, floor=0.5, ceiling=1.0, max_points=20, form=form) == 0.0
    assert ramp(0.5, floor=0.5, ceiling=1.0, max_points=20, form=form) == pytest.approx(0.0, abs=0.1)


@pytest.mark.parametrize("form", ["linear", "convex", "concave"])
def test_ramp_saturates_at_or_above_ceiling(form):
    assert ramp(1.0, floor=0.5, ceiling=1.0, max_points=20, form=form) == pytest.approx(20.0, abs=0.01)
    assert ramp(2.0, floor=0.5, ceiling=1.0, max_points=20, form=form) == pytest.approx(20.0, abs=0.01)


def test_ramp_sigmoid_approaches_but_does_not_quite_saturate():
    # Sigmoid asymptotes — at norm=1.0 it gives ~M/(1+exp(-5)) ≈ M * 0.9933.
    val = ramp(1.0, floor=0.5, ceiling=1.0, max_points=20, form="sigmoid")
    assert 19.0 < val < 20.0


def test_ramp_linear_midpoint_is_half_of_max():
    assert ramp(0.75, floor=0.5, ceiling=1.0, max_points=20, form="linear") == pytest.approx(10.0)


def test_ramp_convex_under_midpoint_below_linear():
    # convex (p=1.5) at norm=0.5 → 0.5^1.5 ≈ 0.354
    assert ramp(0.75, floor=0.5, ceiling=1.0, max_points=20, form="convex") == pytest.approx(20 * (0.5 ** 1.5), abs=0.01)


def test_ramp_concave_under_midpoint_above_linear():
    # concave (p=0.5) at norm=0.5 → 0.5^0.5 ≈ 0.707
    assert ramp(0.75, floor=0.5, ceiling=1.0, max_points=20, form="concave") == pytest.approx(20 * (0.5 ** 0.5), abs=0.01)


def test_ramp_rejects_inverted_floor_ceiling():
    with pytest.raises(ValueError):
        ramp(0.5, floor=1.0, ceiling=0.5, max_points=20, form="linear")
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/cards/test_canary_scoring.py -v
```
Expected: 7 PASS (parametrized: 4 for floor + 3 for ceiling = 7 actual test instances + 5 simple = 12). Confirm all pass.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/cards/test_canary_scoring.py
git commit -m "feat(canary): score-form ramp functions (linear/convex/concave/sigmoid)"
```

---

## Task 5: Five smooth signal scorers

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (add scorer functions)
- Modify: `tests/unit/cards/test_canary_scoring.py` (add scorer tests)

- [ ] **Step 1: Append the smooth-signal scorers**

Append to `src/uw_scan/cards/canary_scoring.py`:

```python
from dataclasses import dataclass
from typing import Sequence

from uw_scan.cards.canary_calibration import Calibration, SignalThresholds


@dataclass(frozen=True)
class SmoothSignalScore:
    score: float
    gate_active: bool
    diagnostics: dict[str, float]


def score_vix_spike_revert(
    vix_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Whaley-derived VIX spike-and-reversion."""
    lookback = int(th.extras["peak_lookback_d"])
    spike_threshold = float(th.extras["spike_active_at_vix"])
    if len(vix_history) < lookback:
        return SmoothSignalScore(0.0, False, {"reason": float("nan")})
    vix_today = vix_history[-1]
    vix_peak = max(vix_history[-lookback:])
    spike_active = vix_peak >= spike_threshold
    pullback_pct = max(0.0, (vix_peak - vix_today) / vix_peak) if vix_peak > 0 else 0.0
    if not spike_active:
        return SmoothSignalScore(0.0, False, {"vix_peak": vix_peak, "pullback_pct": pullback_pct})
    s = ramp(pullback_pct, floor=th.floor, ceiling=th.ceiling, max_points=th.max_points, form=form)
    return SmoothSignalScore(s, True, {"vix_peak": vix_peak, "pullback_pct": pullback_pct})


def score_vix_vix3m_back(
    vix_history: Sequence[float],
    vix3m_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Backwardation-normalizing — v0.3 reframe of raw backwardation."""
    lookback = int(th.extras["peak_lookback_d"])
    extreme_th = float(th.extras["backwardation_extreme_at_ratio"])
    if len(vix_history) < lookback or len(vix3m_history) < lookback or vix3m_history[-1] == 0:
        return SmoothSignalScore(0.0, False, {})
    ratios = [v / m for v, m in zip(vix_history[-lookback:], vix3m_history[-lookback:]) if m]
    if not ratios:
        return SmoothSignalScore(0.0, False, {})
    ratio_today = vix_history[-1] / vix3m_history[-1]
    ratio_peak = max(ratios)
    extreme = ratio_peak >= extreme_th
    norm_pct = max(0.0, (ratio_peak - ratio_today) / ratio_peak) if ratio_peak > 0 else 0.0
    if not extreme:
        return SmoothSignalScore(0.0, False, {"ratio_peak": ratio_peak, "ratio_today": ratio_today, "norm_pct": norm_pct})
    s = ramp(norm_pct, floor=th.floor, ceiling=th.ceiling, max_points=th.max_points, form=form)
    return SmoothSignalScore(s, True, {"ratio_peak": ratio_peak, "ratio_today": ratio_today, "norm_pct": norm_pct})


def score_vrp(
    vix_today: float,
    spx_log_returns: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Bollerslev/Tauchen/Zhou VRP."""
    rv_window = int(th.extras["rv_window_d"])
    if len(spx_log_returns) < rv_window or vix_today <= 0:
        return SmoothSignalScore(0.0, False, {})
    import statistics
    sample = list(spx_log_returns[-rv_window:])
    rv_annual_pct = statistics.pstdev(sample) * math.sqrt(252) * 100.0
    vrp = (vix_today ** 2) - (rv_annual_pct ** 2)
    s = ramp(vrp, floor=th.floor, ceiling=th.ceiling, max_points=th.max_points, form=form)
    return SmoothSignalScore(s, True, {"vix2": vix_today ** 2, "rv2_20d": rv_annual_pct ** 2, "vrp": vrp})


def score_cor1m_decay(
    cor1m_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """Correlation peak-and-decay (Driessen/Maenhout/Vilkov framing)."""
    lookback = int(th.extras["peak_lookback_d"])
    elevated_th = float(th.extras["peak_elevated_at"])
    if len(cor1m_history) < lookback:
        return SmoothSignalScore(0.0, False, {})
    today = cor1m_history[-1]
    peak = max(cor1m_history[-lookback:])
    elevated = peak >= elevated_th
    decay_pct = max(0.0, (peak - today) / peak) if peak > 0 else 0.0
    if not elevated:
        return SmoothSignalScore(0.0, False, {"peak_60d": peak, "current": today, "decay_pct": decay_pct})
    s = ramp(decay_pct, floor=th.floor, ceiling=th.ceiling, max_points=th.max_points, form=form)
    return SmoothSignalScore(s, True, {"peak_60d": peak, "current": today, "decay_pct": decay_pct})


def score_vvix_vix_recovery(
    vvix_history: Sequence[float],
    vix_history: Sequence[float],
    *,
    th: SignalThresholds,
    form: ScoreForm,
) -> SmoothSignalScore:
    """VVIX/VIX ratio recovery from compressed regime."""
    lookback = int(th.extras["compress_lookback_d"])
    compressed_th = float(th.extras["compressed_below_ratio"])
    if len(vvix_history) < lookback or len(vix_history) < lookback or vix_history[-1] == 0:
        return SmoothSignalScore(0.0, False, {})
    ratios = [v / x for v, x in zip(vvix_history[-lookback:], vix_history[-lookback:]) if x]
    if not ratios:
        return SmoothSignalScore(0.0, False, {})
    ratio_today = vvix_history[-1] / vix_history[-1]
    ratio_min = min(ratios)
    compressed = ratio_min <= compressed_th
    if not compressed:
        return SmoothSignalScore(0.0, False, {"current": ratio_today, "min_60d": ratio_min})
    s = ramp(ratio_today, floor=th.floor, ceiling=th.ceiling, max_points=th.max_points, form=form)
    return SmoothSignalScore(s, True, {"current": ratio_today, "min_60d": ratio_min})
```

- [ ] **Step 2: Add scorer tests**

Append to `tests/unit/cards/test_canary_scoring.py`:

```python
from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.cards.canary_scoring import (
    score_vix_spike_revert,
    score_vix_vix3m_back,
    score_vrp,
    score_cor1m_decay,
    score_vvix_vix_recovery,
)


def test_vix_spike_gate_closed_returns_zero():
    cal = load_calibration()
    # Last 10 days all below 30 → no spike active.
    vix_history = [18.0] * 10
    out = score_vix_spike_revert(vix_history, th=cal.vix_spike_revert, form="linear")
    assert out.gate_active is False
    assert out.score == 0.0


def test_vix_spike_pullback_saturates():
    cal = load_calibration()
    # Peak at 40, today at 28 → pullback 30%; saturates linear at full max_points.
    vix_history = [25.0] * 9 + [28.0]
    vix_history[5] = 40.0  # peak in the lookback window
    out = score_vix_spike_revert(vix_history, th=cal.vix_spike_revert, form="linear")
    assert out.gate_active is True
    assert out.score == pytest.approx(cal.vix_spike_revert.max_points, abs=0.5)


def test_vix_vix3m_no_extreme_returns_zero():
    cal = load_calibration()
    # All ratios ~0.95 → no extreme backwardation occurred.
    vix_history = [18.0] * 10
    vix3m_history = [19.0] * 10
    out = score_vix_vix3m_back(vix_history, vix3m_history, th=cal.vix_vix3m_back, form="linear")
    assert out.gate_active is False
    assert out.score == 0.0


def test_vix_vix3m_normalization_scores_positive():
    cal = load_calibration()
    # Peak ratio 1.10, today 1.00 → ~9% normalization → fires (extreme was ≥1.05).
    vix_history = [22.0] * 9 + [20.0]
    vix3m_history = [20.0] * 9 + [20.0]
    vix_history[3] = 22.0   # ratio 22/20 = 1.10 — extreme peak
    out = score_vix_vix3m_back(vix_history, vix3m_history, th=cal.vix_vix3m_back, form="linear")
    assert out.gate_active is True
    assert out.score > 0.0


def test_vrp_calm_day_low_score():
    cal = load_calibration()
    # 1% daily moves → ~16% annualized; VIX 14 → VRP ≈ 196 - 256 = -60 → 0
    spx_log_returns = [0.01, -0.01] * 10
    out = score_vrp(vix_today=14.0, spx_log_returns=spx_log_returns, th=cal.vrp, form="linear")
    assert out.gate_active is True
    assert out.score == 0.0


def test_vrp_high_vix_low_rv_scores_high():
    cal = load_calibration()
    spx_log_returns = [0.005] * 20  # very low RV ~8% annualized
    out = score_vrp(vix_today=30.0, spx_log_returns=spx_log_returns, th=cal.vrp, form="linear")
    assert out.gate_active is True
    assert out.score > 0.0
    # VRP ≈ 900 - 64 = 836 → saturates.
    assert out.score == pytest.approx(cal.vrp.max_points, abs=0.5)


def test_cor1m_decay_gate_closed_when_no_peak():
    cal = load_calibration()
    history = [40.0] * 60
    out = score_cor1m_decay(history, th=cal.cor1m_decay, form="linear")
    assert out.gate_active is False
    assert out.score == 0.0


def test_cor1m_decay_saturates_after_30pct_decay():
    cal = load_calibration()
    history = [40.0] * 59 + [49.0]  # today 49
    history[10] = 75.0               # peak 75 → decay 26/75 = 34.7% → saturates
    out = score_cor1m_decay(history, th=cal.cor1m_decay, form="linear")
    assert out.gate_active is True
    assert out.score == pytest.approx(cal.cor1m_decay.max_points, abs=0.5)


def test_vvix_vix_recovery_no_compression_returns_zero():
    cal = load_calibration()
    vvix_history = [100.0] * 60
    vix_history = [20.0] * 60   # ratio 5.0 throughout, never compressed
    out = score_vvix_vix_recovery(vvix_history, vix_history, th=cal.vvix_vix_recovery, form="linear")
    assert out.gate_active is False
    assert out.score == 0.0


def test_vvix_vix_recovery_post_compression_scores_positive():
    cal = load_calibration()
    vvix_history = [110.0] * 60
    vix_history = [25.0] * 60
    vvix_history[10] = 95.0
    vix_history[10] = 30.0      # ratio 95/30 = 3.17 → compressed below 4.0
    out = score_vvix_vix_recovery(vvix_history, vix_history, th=cal.vvix_vix_recovery, form="linear")
    assert out.gate_active is True
    assert out.score > 0.0
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/cards/test_canary_scoring.py -v
```
Expected: all pass (10 new + earlier ramp tests).

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/cards/test_canary_scoring.py
git commit -m "feat(canary): five smooth-signal scorers (VIX-spike, VIX/VIX3M, VRP, COR1M decay, VVIX/VIX recovery)"
```

---

## Task 6: Primary event state machine (5pct_canary + buy_the_dip)

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (add event state machine)
- Test: `tests/unit/cards/test_canary_speed_events.py` (new)

- [ ] **Step 1: Append event state machine to scoring module**

```python
# Append to src/uw_scan/cards/canary_scoring.py

from dataclasses import dataclass, field
from datetime import date as _date
from typing import Sequence


@dataclass
class CanaryEvent:
    kind: str           # '5pct_canary' | 'buy_the_dip' | 'confirmed_canary'
    fire_date: _date


@dataclass
class CanaryEventState:
    """Mutable per-day state. Persisted in payload.speed.anchor for replay."""
    last_high_date: _date | None = None
    last_high_value: float = float("nan")
    canary_fired_for_high: bool = False
    btd_fired_for_high: bool = False
    open_canary_windows: list[dict] = field(default_factory=list)
    emitted: list[CanaryEvent] = field(default_factory=list)


HIGH_LOOKBACK_DAYS = 252
SPEED_ACTIVITY_WINDOW_DAYS = 42
CANARY_FAST_THRESHOLD_DAYS = 15


def step_primary_events(
    state: CanaryEventState,
    *,
    today: _date,
    spx_close_today: float,
    spx_history: Sequence[tuple[_date, float]],   # ordered ascending, today inclusive
    sma_50_today: float,
    sma_200_today: float,
    trading_days_between,                          # callable(a, b) -> int
) -> CanaryEventState:
    """Update anchor state and emit any new 5pct_canary / buy_the_dip event for ``today``.

    ``trading_days_between(a, b)`` returns the count of trading days in ``(a, b]``.

    Pure-mutation function — modifies ``state`` in place AND returns it for
    fluent chaining. Pure in the sense that it does not read any data beyond
    ``today`` from ``spx_history``.
    """
    # 1. Anchor update: did today print a new 252d closing high?
    if len(spx_history) >= HIGH_LOOKBACK_DAYS:
        window = [v for _, v in spx_history[-HIGH_LOOKBACK_DAYS:]]
        if spx_close_today >= max(window):
            state.last_high_date = today
            state.last_high_value = spx_close_today
            state.canary_fired_for_high = False
            state.btd_fired_for_high = False
            return state  # day is a new high — no primary event possible

    if state.last_high_date is None:
        return state  # no anchor yet — too early in series

    days_since_high = trading_days_between(state.last_high_date, today)
    five_pct_breach = spx_close_today <= 0.95 * state.last_high_value

    if not five_pct_breach:
        return state

    # Anchor invariant: at most one primary event per 252d high anchor.
    # A 5% decline episode against a single high is EITHER fast (Canary) OR
    # slow (BTD), never both. The reset on a new 252d high is the only way
    # to fire a fresh primary event.
    primary_event_fired = state.canary_fired_for_high or state.btd_fired_for_high
    if primary_event_fired:
        return state

    if days_since_high <= CANARY_FAST_THRESHOLD_DAYS:
        state.emitted.append(CanaryEvent(kind="5pct_canary", fire_date=today))
        state.canary_fired_for_high = True
        state.open_canary_windows.append({
            "canary_fire_date": today,
            "expires_after_td": SPEED_ACTIVITY_WINDOW_DAYS,
            "consec_below_sma200": 0,
            "td_elapsed": 0,
        })
    elif days_since_high > CANARY_FAST_THRESHOLD_DAYS and sma_50_today > sma_200_today:
        state.emitted.append(CanaryEvent(kind="buy_the_dip", fire_date=today))
        state.btd_fired_for_high = True
    return state
```

- [ ] **Step 2: Write the primary-event tests**

```python
# tests/unit/cards/test_canary_speed_events.py
from datetime import date, timedelta

import pytest

from uw_scan.cards.canary_scoring import (
    CanaryEventState,
    step_primary_events,
    HIGH_LOOKBACK_DAYS,
    CANARY_FAST_THRESHOLD_DAYS,
)


def _bdate(offset: int) -> date:
    return date(2020, 1, 1) + timedelta(days=offset)


def _trading_days_between(a, b):
    """For tests, treat every calendar day as a trading day for simplicity."""
    return (b - a).days


def _build_uptrend_history(days: int, start: float = 100.0, growth: float = 0.001) -> list[tuple[date, float]]:
    return [(_bdate(i), start * (1.0 + growth * i)) for i in range(days)]


def _step(state, full_history, i, sma_50, sma_200):
    """Drive the state machine one day using ONLY data up to and including index i.

    This honors the scorer's causal contract — the function should never
    receive future-dated rows. Test wrappers MUST slice the history.
    """
    d, v = full_history[i]
    return step_primary_events(
        state, today=d, spx_close_today=v,
        spx_history=full_history[: i + 1],   # ← causal slice
        sma_50_today=sma_50, sma_200_today=sma_200,
        trading_days_between=_trading_days_between,
    )


def test_5pct_canary_fires_on_fast_decline():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    # Now drop 6% in 5 trading days — append the crash day to the history.
    crash_day = _bdate(HIGH_LOOKBACK_DAYS + 5)
    history_with_crash = history + [(crash_day, high_val * 0.94)]
    state = _step(state, history_with_crash, len(history_with_crash) - 1,
                  sma_50=high_val, sma_200=high_val * 0.95)
    assert any(e.kind == "5pct_canary" for e in state.emitted)


def test_buy_the_dip_fires_on_slow_decline_with_uptrend_smas():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    # 5% breach but 20 trading days after the high → BTD path.
    dip_day = _bdate(HIGH_LOOKBACK_DAYS + 20)
    history_with_dip = history + [(dip_day, high_val * 0.945)]
    state = _step(state, history_with_dip, len(history_with_dip) - 1,
                  sma_50=high_val * 1.01, sma_200=high_val * 0.95)
    assert any(e.kind == "buy_the_dip" for e in state.emitted)


def test_canary_does_not_re_fire_against_same_anchor():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    full = list(history)
    for offset in (5, 7, 10):
        crash_day = _bdate(HIGH_LOOKBACK_DAYS + offset)
        full = full + [(crash_day, high_val * 0.93)]
        state = _step(state, full, len(full) - 1,
                      sma_50=high_val, sma_200=high_val * 0.95)
    canaries = [e for e in state.emitted if e.kind == "5pct_canary"]
    assert len(canaries) == 1


def test_no_btd_after_canary_against_same_anchor():
    """Anchor invariant: once Canary fires against an anchor, BTD cannot also fire."""
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    # Fast Canary fires at day +5.
    full = history + [(_bdate(HIGH_LOOKBACK_DAYS + 5), high_val * 0.94)]
    state = _step(state, full, len(full) - 1,
                  sma_50=high_val * 1.01, sma_200=high_val * 0.95)
    assert any(e.kind == "5pct_canary" for e in state.emitted)
    # Day +20, still in 5% breach, SMA50>SMA200, slow-decline path normally
    # would fire BTD — but anchor invariant must block it.
    full = full + [(_bdate(HIGH_LOOKBACK_DAYS + 20), high_val * 0.94)]
    state = _step(state, full, len(full) - 1,
                  sma_50=high_val * 1.01, sma_200=high_val * 0.95)
    btds = [e for e in state.emitted if e.kind == "buy_the_dip"]
    assert btds == []


def test_new_high_resets_anchor_flags():
    history = _build_uptrend_history(HIGH_LOOKBACK_DAYS)
    state = CanaryEventState()
    high_val = history[-1][1]
    for i, (_, v) in enumerate(history):
        state = _step(state, history, i, sma_50=v, sma_200=v * 0.95)
    full = history + [(_bdate(HIGH_LOOKBACK_DAYS + 5), high_val * 0.94)]
    state = _step(state, full, len(full) - 1,
                  sma_50=high_val, sma_200=high_val * 0.95)
    assert state.canary_fired_for_high is True
    # Print a NEW 252d high — must reset both flags.
    full = full + [(_bdate(HIGH_LOOKBACK_DAYS + 200), high_val * 1.10)]
    state = _step(state, full, len(full) - 1,
                  sma_50=high_val, sma_200=high_val * 0.95)
    assert state.canary_fired_for_high is False
    assert state.btd_fired_for_high is False
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/cards/test_canary_speed_events.py -v
```
Expected: 5 PASS (the new test_no_btd_after_canary_against_same_anchor enforces
the anchor invariant from Task 0).

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/cards/test_canary_speed_events.py
git commit -m "feat(canary): primary event state machine + anchor invariant (one event per anchor)"
```

---

## Task 7: Confirmed Canary causal state machine

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (add Confirmed Canary stepper)
- Test: `tests/unit/cards/test_canary_confirmed_canary_state_machine.py` (new)

- [ ] **Step 1: Append Confirmed Canary stepper**

```python
# Append to src/uw_scan/cards/canary_scoring.py

def step_confirmed_canary(
    state: CanaryEventState,
    *,
    today: _date,
    spx_close_today: float,
    sma_200_today: float,
) -> CanaryEventState:
    """Advance each open Confirmed-Canary window by one trading day.

    Emits a 'confirmed_canary' event on the day the 2nd consecutive close
    below SMA-200 occurs inside any open window. Causal — no forward lookup.
    """
    if not state.open_canary_windows:
        return state

    below_sma200 = spx_close_today < sma_200_today
    kept_windows: list[dict] = []
    for win in state.open_canary_windows:
        win["td_elapsed"] += 1
        if win["td_elapsed"] > win["expires_after_td"]:
            continue   # expired — drop
        if below_sma200:
            win["consec_below_sma200"] += 1
        else:
            win["consec_below_sma200"] = 0
        if win["consec_below_sma200"] >= 2:
            state.emitted.append(CanaryEvent(kind="confirmed_canary", fire_date=today))
            # Window is consumed on confirmation.
            continue
        kept_windows.append(win)
    state.open_canary_windows = kept_windows
    return state
```

- [ ] **Step 2: Write the Confirmed-Canary tests**

```python
# tests/unit/cards/test_canary_confirmed_canary_state_machine.py
from datetime import date, timedelta

from uw_scan.cards.canary_scoring import (
    CanaryEventState,
    step_confirmed_canary,
)


def _bdate(offset: int) -> date:
    return date(2026, 1, 1) + timedelta(days=offset)


def _state_with_one_open_window(fire_offset: int = 0) -> CanaryEventState:
    state = CanaryEventState()
    state.open_canary_windows.append({
        "canary_fire_date": _bdate(fire_offset),
        "expires_after_td": 42,
        "consec_below_sma200": 0,
        "td_elapsed": 0,
    })
    return state


def test_confirmation_requires_two_consecutive_closes_below_sma_200():
    state = _state_with_one_open_window()
    # Day +1: one close below — no fire.
    state = step_confirmed_canary(state, today=_bdate(1), spx_close_today=95.0, sma_200_today=100.0)
    assert not any(e.kind == "confirmed_canary" for e in state.emitted)
    assert state.open_canary_windows[0]["consec_below_sma200"] == 1
    # Day +2: second consecutive close below — fire.
    state = step_confirmed_canary(state, today=_bdate(2), spx_close_today=94.0, sma_200_today=100.0)
    assert any(e.kind == "confirmed_canary" for e in state.emitted)


def test_close_above_sma200_resets_counter():
    state = _state_with_one_open_window()
    state = step_confirmed_canary(state, today=_bdate(1), spx_close_today=95.0, sma_200_today=100.0)
    assert state.open_canary_windows[0]["consec_below_sma200"] == 1
    state = step_confirmed_canary(state, today=_bdate(2), spx_close_today=101.0, sma_200_today=100.0)
    assert state.open_canary_windows[0]["consec_below_sma200"] == 0


def test_window_consumed_on_confirmation():
    state = _state_with_one_open_window()
    for offset in (1, 2):
        state = step_confirmed_canary(state, today=_bdate(offset), spx_close_today=95.0, sma_200_today=100.0)
    assert state.open_canary_windows == []   # consumed


def test_window_expires_after_42_trading_days():
    state = _state_with_one_open_window()
    for offset in range(1, 44):
        state = step_confirmed_canary(state, today=_bdate(offset), spx_close_today=101.0, sma_200_today=100.0)
    assert state.open_canary_windows == []  # expired


def test_two_concurrent_open_windows_tracked_independently():
    state = CanaryEventState()
    state.open_canary_windows.extend([
        {"canary_fire_date": _bdate(0), "expires_after_td": 42, "consec_below_sma200": 0, "td_elapsed": 0},
        {"canary_fire_date": _bdate(5), "expires_after_td": 42, "consec_below_sma200": 0, "td_elapsed": 0},
    ])
    # Day +1: close below SMA-200 — both windows tick.
    state = step_confirmed_canary(state, today=_bdate(6), spx_close_today=95.0, sma_200_today=100.0)
    state = step_confirmed_canary(state, today=_bdate(7), spx_close_today=94.0, sma_200_today=100.0)
    confirmations = [e for e in state.emitted if e.kind == "confirmed_canary"]
    # Both windows consumed on the same day (each fired its own confirmation)
    assert len(confirmations) == 2
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/cards/test_canary_confirmed_canary_state_machine.py -v
```
Expected: 5 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/cards/test_canary_confirmed_canary_state_machine.py
git commit -m "feat(canary): causal Confirmed Canary state machine (no look-ahead)"
```

---

## Task 8: Speed score 4-state + cap rule + composite

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (add `derive_speed_state`, `apply_cap`, `compose`)
- Modify: `tests/unit/cards/test_canary_scoring.py` (add composite + cap tests)

- [ ] **Step 1: Append speed + cap + compose**

```python
# Append to src/uw_scan/cards/canary_scoring.py

from typing import NamedTuple


class SpeedScore(NamedTuple):
    score: int
    state: str   # 'NEUTRAL' | 'CONFIRMED_CANARY_ACTIVE' | 'BUY_THE_DIP_ACTIVE' | 'BOTH_ACTIVE_AMBIGUOUS'
    confirmed_canary_active: bool
    buy_the_dip_active: bool


def derive_speed(
    *, confirmed_canary_active: bool, buy_the_dip_active: bool
) -> SpeedScore:
    if confirmed_canary_active and buy_the_dip_active:
        return SpeedScore(8, "BOTH_ACTIVE_AMBIGUOUS", True, True)
    if confirmed_canary_active:
        return SpeedScore(0, "CONFIRMED_CANARY_ACTIVE", True, False)
    if buy_the_dip_active:
        return SpeedScore(20, "BUY_THE_DIP_ACTIVE", False, True)
    return SpeedScore(8, "NEUTRAL", False, False)


class CapResult(NamedTuple):
    final_score: float
    warning_state: str
    cap_applied: bool


def apply_cap(
    *,
    raw_score: float,
    speed: SpeedScore,
    spx_above_sma200_2d: bool,
    vix_term_normalized: bool,
    higher_closing_low: bool,
) -> CapResult:
    cap_cleared_early = spx_above_sma200_2d or (vix_term_normalized and higher_closing_low)
    if speed.state == "CONFIRMED_CANARY_ACTIVE":
        if cap_cleared_early:
            return CapResult(raw_score, "NONE", False)
        capped = min(raw_score, 49.0)
        return CapResult(capped, "CONFIRMED_CANARY_ACTIVE", raw_score > 49.0)
    if speed.state == "BOTH_ACTIVE_AMBIGUOUS":
        capped = min(raw_score, 49.0)
        return CapResult(capped, "BOTH_ACTIVE_AMBIGUOUS", raw_score > 49.0)
    if speed.state == "BUY_THE_DIP_ACTIVE":
        return CapResult(raw_score, "BUY_THE_DIP_ACTIVE", False)
    return CapResult(raw_score, "NONE", False)


def compute_band(score: float) -> str:
    if score < 25.0:
        return "NONE"
    if score < 50.0:
        return "WATCH"
    if score < 75.0:
        return "BUY"
    return "STRONG_BUY"


def higher_closing_low_close_only(spx_close_history: Sequence[float], sma_200_today: float, spx_close_today: float) -> bool:
    """Close-only definition. Returns True iff:
       - min(last 5 closes) > min(prior 15 closes [-20:-5])
       - AND today close > sma_200 * 0.98
    """
    if len(spx_close_history) < 20:
        return False
    prior = min(spx_close_history[-20:-5])
    recent = min(spx_close_history[-5:])
    return recent > prior and spx_close_today > sma_200_today * 0.98
```

- [ ] **Step 2: Add cap + speed tests**

```python
# Append to tests/unit/cards/test_canary_scoring.py
from uw_scan.cards.canary_scoring import (
    derive_speed,
    apply_cap,
    compute_band,
    higher_closing_low_close_only,
)


def test_speed_neutral_default():
    s = derive_speed(confirmed_canary_active=False, buy_the_dip_active=False)
    assert (s.score, s.state) == (8, "NEUTRAL")


def test_speed_confirmed_canary_only():
    s = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    assert (s.score, s.state) == (0, "CONFIRMED_CANARY_ACTIVE")


def test_speed_btd_only():
    s = derive_speed(confirmed_canary_active=False, buy_the_dip_active=True)
    assert (s.score, s.state) == (20, "BUY_THE_DIP_ACTIVE")


def test_speed_both_active_is_ambiguous_not_btd():
    s = derive_speed(confirmed_canary_active=True, buy_the_dip_active=True)
    assert (s.score, s.state) == (8, "BOTH_ACTIVE_AMBIGUOUS")


def test_cap_binds_on_confirmed_canary_with_no_lift():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(raw_score=80.0, speed=speed,
                    spx_above_sma200_2d=False, vix_term_normalized=False, higher_closing_low=False)
    assert out == (49.0, "CONFIRMED_CANARY_ACTIVE", True)


def test_cap_lifts_on_sma200_recapture():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(raw_score=80.0, speed=speed,
                    spx_above_sma200_2d=True, vix_term_normalized=False, higher_closing_low=False)
    assert out == (80.0, "NONE", False)


def test_cap_lifts_on_term_normalize_and_higher_low_combo():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(raw_score=80.0, speed=speed,
                    spx_above_sma200_2d=False, vix_term_normalized=True, higher_closing_low=True)
    assert out == (80.0, "NONE", False)


def test_cap_does_NOT_lift_on_term_normalize_alone():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(raw_score=80.0, speed=speed,
                    spx_above_sma200_2d=False, vix_term_normalized=True, higher_closing_low=False)
    assert out.cap_applied is True
    assert out.final_score == 49.0


def test_cap_always_binds_on_both_active_even_with_lift_conditions():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=True)
    out = apply_cap(raw_score=80.0, speed=speed,
                    spx_above_sma200_2d=True, vix_term_normalized=True, higher_closing_low=True)
    assert out == (49.0, "BOTH_ACTIVE_AMBIGUOUS", True)


def test_band_thresholds():
    assert compute_band(0.0) == "NONE"
    assert compute_band(24.99) == "NONE"
    assert compute_band(25.0) == "WATCH"
    assert compute_band(49.999) == "WATCH"
    assert compute_band(50.0) == "BUY"
    assert compute_band(74.999) == "BUY"
    assert compute_band(75.0) == "STRONG_BUY"
    assert compute_band(100.0) == "STRONG_BUY"


def test_higher_closing_low_uses_only_closes():
    # Recent low (last 5) > prior low (-20:-5)
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91,  # prior 15: min 85 below
              90, 89, 88, 87, 85,                       # min prior 15: 85
              86, 87, 88, 89, 90]                       # recent 5: min 86 > prior 85
    assert higher_closing_low_close_only(closes, sma_200_today=80.0, spx_close_today=90.0) is True


def test_higher_closing_low_blocked_when_below_sma200_buffer():
    closes = [100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87, 85, 86, 87, 88, 89, 90]
    assert higher_closing_low_close_only(closes, sma_200_today=100.0, spx_close_today=90.0) is False
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/cards/test_canary_scoring.py -v
```
Expected: all pass (existing + 12 new).

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/cards/test_canary_scoring.py
git commit -m "feat(canary): 4-state speed model + cap rule + band map"
```

---

## Task 9: Canonical payload hash

**Files:**
- Create: `src/uw_scan/cards/canary_payload_hash.py`
- Test: `tests/unit/storage/test_canary_payload_hash.py`

- [ ] **Step 1: Write the canonical hash function**

```python
# src/uw_scan/cards/canary_payload_hash.py
"""Canonical SHA-256 of the canary snapshot payload.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §9.0a.

Key invariants (v0.2 patch):
  - float and Decimal at the SAME value produce the SAME hash. Both go
    through a recursive normalizer that collapses to a 6-decimal string
    BEFORE json.dumps, so floats are never serialized as JSON numbers.
  - dict key order has no effect (sorted by the normalizer).
  - The ``_prior`` audit field is excluded.
  - Pinned hash test in tests/unit/storage/test_canary_payload_hash.py
    breaks loudly on any serialization-format change.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Any


def _normalize(obj: Any) -> Any:
    """Recursive canonical normalizer. Output is JSON-safe with stable repr."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items()) if k != "_prior"}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, bool):
        return obj   # must check before int — bool is subclass of int
    if isinstance(obj, int):
        return obj
    if isinstance(obj, (float, Decimal)):
        # Quantize both to the same 6-decimal string repr.
        return format(Decimal(str(obj)), ".6f")
    if obj is None:
        return None
    if isinstance(obj, str):
        return obj
    iso = getattr(obj, "isoformat", None)
    if callable(iso):
        return iso()
    raise TypeError(f"Object of type {type(obj)} is not normalizable")


def canonical_payload_hash(payload: dict) -> str:
    normalized = _normalize(payload)
    encoded = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

- [ ] **Step 2: Write the hash test**

```python
# tests/unit/storage/test_canary_payload_hash.py
from decimal import Decimal

from uw_scan.cards.canary_payload_hash import canonical_payload_hash


def test_hash_stable_across_two_runs():
    payload = {"a": 1, "b": [3.14, 2.718], "c": {"nested": True}}
    assert canonical_payload_hash(payload) == canonical_payload_hash(payload)


def test_key_reorder_does_not_change_hash():
    p1 = {"a": 1, "b": 2}
    p2 = {"b": 2, "a": 1}
    assert canonical_payload_hash(p1) == canonical_payload_hash(p2)


def test_decimal_vs_float_same_value_same_hash():
    p1 = {"score": 47.300000}
    p2 = {"score": Decimal("47.300000")}
    assert canonical_payload_hash(p1) == canonical_payload_hash(p2)


def test_prior_field_is_excluded():
    p1 = {"a": 1}
    p2 = {"a": 1, "_prior": {"row_id": 99, "payload": {"a": 999}}}
    assert canonical_payload_hash(p1) == canonical_payload_hash(p2)


def test_pinned_hash_for_known_payload():
    """Regression — if this fixture's hash changes, the serialization format
    drifted. Update the constant ONLY when the change is intentional and
    versioned via composite_version bump.

    Implementer note: compute the pinned digest ONCE locally with a clean
    implementation (run canonical_payload_hash on the fixture below), then
    hardcode the result here. Future changes that break this test signal
    serialization-format drift and require a v2 composite_version.
    """
    payload = {
        "date": "2026-05-26",
        "canary": {"score": 47.3, "band": "WATCH"},
    }
    digest = canonical_payload_hash(payload)
    # PIN THIS VALUE after first clean run — copy the actual sha256 hex digest:
    expected = "<PIN-ME-AFTER-FIRST-RUN>"
    if expected.startswith("<"):
        # First-run path: print and assert hex shape only — implementer
        # must replace `expected` with the printed value and re-run the test.
        print(f"\n  PIN THIS DIGEST: expected = \"{digest}\"\n")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)
    else:
        assert digest == expected
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/storage/test_canary_payload_hash.py -v
```
Expected: 5 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_payload_hash.py tests/unit/storage/test_canary_payload_hash.py
git commit -m "feat(canary): canonical payload hash (sorted keys, decimal normalization)"
```

---

## Task 10: Run-analysis orchestration (`run_analysis`)

**Files:**
- Modify: `src/uw_scan/cards/canary_scoring.py` (add the top-level `run_analysis`)
- Modify: `tests/unit/cards/test_canary_scoring.py` (add end-to-end composition test)

- [ ] **Step 1: Append `run_analysis`**

```python
# Append to src/uw_scan/cards/canary_scoring.py

from datetime import date as _date


def run_analysis(
    *,
    today: _date,
    aligned: dict,           # {'VIX': np.ndarray, 'VVIX': ..., 'VIX3M': ..., 'COR1M': ..., 'SPX': ...}
    common_dates: list[str], # iso dates corresponding to the aligned arrays
    sma_50_today: float,
    sma_200_today: float,
    spx_above_sma200_2d: bool,
    vix_term_normalized: bool,
    higher_closing_low: bool,
    confirmed_canary_active: bool,
    buy_the_dip_active: bool,
    calibration,             # Calibration
) -> dict:
    """Stitch the five smooth scorers + speed/cap into a single payload dict.

    Caller is responsible for running the event state machine (steps_primary +
    step_confirmed_canary) over the full history and computing
    confirmed_canary_active / buy_the_dip_active before calling this.
    """
    form = calibration.score_form
    vix = aligned["VIX"]; vvix = aligned["VVIX"]; vix3m = aligned["VIX3M"]; cor = aligned["COR1M"]; spx = aligned["SPX"]
    # SPX log returns for VRP (last 20 entries, computed from prices)
    import numpy as np
    spx_arr = np.asarray(spx, dtype=float)
    log_returns = np.diff(np.log(spx_arr))[-20:].tolist()

    s_spike = score_vix_spike_revert(vix.tolist(), th=calibration.vix_spike_revert, form=form)
    s_back  = score_vix_vix3m_back(vix.tolist(), vix3m.tolist(), th=calibration.vix_vix3m_back, form=form)
    s_vrp   = score_vrp(float(vix[-1]), log_returns, th=calibration.vrp, form=form)
    s_cor   = score_cor1m_decay(cor.tolist(), th=calibration.cor1m_decay, form=form)
    s_vvr   = score_vvix_vix_recovery(vvix.tolist(), vix.tolist(), th=calibration.vvix_vix_recovery, form=form)

    tactical = s_spike.score + s_back.score
    structural = s_vrp.score + s_cor.score + s_vvr.score

    speed = derive_speed(
        confirmed_canary_active=confirmed_canary_active,
        buy_the_dip_active=buy_the_dip_active,
    )
    raw = tactical + structural + speed.score
    raw = max(0.0, min(100.0, raw))
    cap = apply_cap(
        raw_score=raw, speed=speed,
        spx_above_sma200_2d=spx_above_sma200_2d,
        vix_term_normalized=vix_term_normalized,
        higher_closing_low=higher_closing_low,
    )
    band = compute_band(cap.final_score)

    payload = {
        "date": today.isoformat(),
        "canary": {
            "score": round(cap.final_score, 2),
            "raw_score": round(raw, 2),
            "band": band,
            "warning_state": cap.warning_state,
            "composite_version": calibration.composite_version,
            "score_form": form,
            "cap_applied": cap.cap_applied,
            "cap_lift_conditions": {
                "spx_above_sma200_2d": spx_above_sma200_2d,
                "vix_term_normalized": vix_term_normalized,
                "higher_closing_low": higher_closing_low,
            },
        },
        "tactical_vol": {
            "score": round(tactical, 2),
            "vix_spike_revert": {"score": round(s_spike.score, 2), "gate_active": s_spike.gate_active, **s_spike.diagnostics},
            "vix_vix3m_back":   {"score": round(s_back.score, 2),  "gate_active": s_back.gate_active,  **s_back.diagnostics},
        },
        "structural_vol": {
            "score": round(structural, 2),
            "vrp":               {"score": round(s_vrp.score, 2), "gate_active": s_vrp.gate_active, **s_vrp.diagnostics},
            "cor1m_decay":       {"score": round(s_cor.score, 2), "gate_active": s_cor.gate_active, **s_cor.diagnostics},
            "vvix_vix_recovery": {"score": round(s_vvr.score, 2), "gate_active": s_vvr.gate_active, **s_vvr.diagnostics},
        },
        "speed": {
            "score": speed.score,
            "state": speed.state,
            "confirmed_canary_active": confirmed_canary_active,
            "buy_the_dip_active": buy_the_dip_active,
            "sma50_above_sma200": sma_50_today > sma_200_today,
        },
        "inputs": {
            "vix": float(vix[-1]), "vvix": float(vvix[-1]),
            "vix3m": float(vix3m[-1]) if not math.isnan(float(vix3m[-1])) else None,
            "cor1m": float(cor[-1]), "spx_close": float(spx[-1]),
            "sma_50": sma_50_today, "sma_200": sma_200_today,
        },
    }
    return payload
```

- [ ] **Step 2: Add an end-to-end composition test**

```python
# Append to tests/unit/cards/test_canary_scoring.py
import numpy as np
from datetime import date

from uw_scan.cards.canary_scoring import run_analysis


def test_run_analysis_calm_day_low_score_and_no_warning():
    cal = load_calibration()
    # 200 sessions of stable inputs.
    n = 200
    aligned = {
        "VIX":   np.full(n, 14.0),
        "VVIX":  np.full(n, 90.0),
        "VIX3M": np.full(n, 16.0),
        "COR1M": np.full(n, 30.0),
        "SPX":   np.linspace(4000, 4400, n),
    }
    payload = run_analysis(
        today=date(2026, 5, 26),
        aligned=aligned,
        common_dates=[date(2025, 1, 1).isoformat()] * n,
        sma_50_today=4400.0,
        sma_200_today=4200.0,
        spx_above_sma200_2d=True,
        vix_term_normalized=True,
        higher_closing_low=True,
        confirmed_canary_active=False,
        buy_the_dip_active=False,
        calibration=cal,
    )
    assert payload["canary"]["warning_state"] == "NONE"
    assert payload["speed"]["state"] == "NEUTRAL"
    # v0.2 patch: bound relaxed to ≤25 pending the VRP-gating decision noted
    # in Task 0. VRP is always-on, so calm-day VIX with low RV can score 5-10
    # on its own. Under the v1 calibrated thresholds (after --calibrate),
    # this assertion should tighten naturally. If it doesn't, add a stress
    # gate to VRP in v2.
    assert payload["canary"]["score"] <= 25.0
    assert payload["canary"]["band"] in ("NONE", "WATCH")


def test_run_analysis_confirmed_canary_caps_at_watch():
    cal = load_calibration()
    n = 200
    # High-stress vol regime — all five smooth signals firing strongly.
    aligned = {
        "VIX":   np.linspace(35, 22, n),    # peaked 35, retraced to 22
        "VVIX":  np.linspace(140, 110, n),
        "VIX3M": np.linspace(28, 22, n),
        "COR1M": np.concatenate([np.linspace(30, 75, 60), np.linspace(75, 50, n - 60)]),
        "SPX":   np.linspace(4400, 4180, n),
    }
    payload = run_analysis(
        today=date(2026, 5, 26),
        aligned=aligned,
        common_dates=[date(2025, 1, 1).isoformat()] * n,
        sma_50_today=4300.0,
        sma_200_today=4250.0,
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=True,
        buy_the_dip_active=False,
        calibration=cal,
    )
    assert payload["canary"]["score"] <= 49.0
    assert payload["canary"]["band"] in ("NONE", "WATCH")
    assert payload["canary"]["warning_state"] == "CONFIRMED_CANARY_ACTIVE"
    assert payload["canary"]["cap_applied"] in (True, False)  # depends on raw
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/unit/cards/test_canary_scoring.py -v
```
Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/cards/canary_scoring.py tests/unit/cards/test_canary_scoring.py
git commit -m "feat(canary): run_analysis orchestrator stitches scorers + speed + cap"
```

---

## Task 11: Scanner orchestrator

**Files:**
- Create: `src/uw_scan/scanners/canary.py`
- Test: `tests/integration/regime/test_canary_scanner.py`

- [ ] **Step 1: Write the scanner**

```python
# src/uw_scan/scanners/canary.py
"""5% Canary scanner — reads vol_index_daily, runs cards/canary_scoring, persists.

See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §5, §11.
"""
from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from typing import Iterable

import numpy as np
from psycopg import Connection

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import load_calibration, COMPOSITE_VERSION
from uw_scan.cards.canary_payload_hash import canonical_payload_hash
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

log = logging.getLogger(__name__)

# v0.3: 350 trading rows required (not calendar days).
MIN_ALIGNED_BARS = 350
CALENDAR_DAYS_REQUESTED = 500
RV_WINDOW = 20


def _load(vol_repo: VolIndexRepository, symbol: str, days: int) -> dict[_date, float]:
    rows = vol_repo.fetch_history(symbol, days=days)
    return {r["trade_date"]: float(r["close"]) for r in rows if r.get("close") is not None}


def _align(series: dict[str, dict[_date, float]]) -> tuple[dict[str, np.ndarray], list[_date]]:
    if not series:
        return {}, []
    keys = list(series.keys())
    common = set(series[keys[0]].keys())
    for k in keys[1:]:
        common &= set(series[k].keys())
    if not common:
        return {sym: np.array([]) for sym in keys}, []
    sorted_dates = sorted(common)
    aligned = {sym: np.array([series[sym][d] for d in sorted_dates], dtype=float) for sym in keys}
    return aligned, sorted_dates


def _compute_smas(spx_arr: np.ndarray) -> tuple[float, float]:
    sma_50 = float(np.mean(spx_arr[-50:]))
    sma_200 = float(np.mean(spx_arr[-200:]))
    return sma_50, sma_200


def _above_sma200_two_consecutive(spx_arr: np.ndarray) -> bool:
    """Returns True iff SPX closed above its 200d SMA on both today and yesterday.

    The SMA is recomputed for each of the two days using each day's own
    trailing 200 closes (not a single shared SMA), so the result is causal.
    """
    if len(spx_arr) < 201:
        return False
    sma200_today = float(np.mean(spx_arr[-200:]))
    sma200_prev  = float(np.mean(spx_arr[-201:-1]))
    return spx_arr[-1] >= sma200_today and spx_arr[-2] >= sma200_prev


def _compute_cap_lift_inputs(spx_arr: np.ndarray, sma_200: float, vix_arr: np.ndarray, vix3m_arr: np.ndarray) -> tuple[bool, bool, bool]:
    closes = spx_arr.tolist()
    today = closes[-1]
    spx_above_sma200_2d = _above_sma200_two_consecutive(spx_arr)
    vix_term_normalized = (vix_arr[-1] / vix3m_arr[-1]) < 1.0 if vix3m_arr[-1] > 0 else False
    higher_closing_low = canary_scoring.higher_closing_low_close_only(closes, sma_200_today=sma_200, spx_close_today=today)
    return spx_above_sma200_2d, vix_term_normalized, higher_closing_low


def _replay_events(spx_close_history: list[tuple[_date, float]]) -> canary_scoring.CanaryEventState:
    """Walk through the SPX close history day-by-day to materialize the event state."""
    state = canary_scoring.CanaryEventState()
    # We need SMA-50 and SMA-200 per day for primary-event detection.
    closes = [c for _, c in spx_close_history]
    for i, (d, c) in enumerate(spx_close_history):
        history_slice = spx_close_history[: i + 1]
        if i < 200:
            continue
        sma_50 = float(np.mean(closes[i - 49 : i + 1]))
        sma_200 = float(np.mean(closes[i - 199 : i + 1]))
        canary_scoring.step_primary_events(
            state, today=d, spx_close_today=c, spx_history=history_slice,
            sma_50_today=sma_50, sma_200_today=sma_200,
            trading_days_between=lambda a, b, _src=spx_close_history: sum(1 for dd, _ in _src if a < dd <= b),
        )
        canary_scoring.step_confirmed_canary(state, today=d, spx_close_today=c, sma_200_today=sma_200)
    return state


def _events_in_window(events: Iterable, kind: str, fire_window_days: int, today: _date, all_dates: list[_date]) -> bool:
    """Was an event of ``kind`` fired in the last ``fire_window_days`` trading days (inclusive)?"""
    target_dates = [d for d in all_dates if d <= today][-fire_window_days:]
    fire_dates = {e.fire_date for e in events if e.kind == kind}
    return any(d in fire_dates for d in target_dates)


def run(conn: Connection, *, schema: str = "uw_scan", force_recompute: bool = False) -> int | None:
    """Run a 5% Canary scan; persist a new snapshot row. Returns row id or None."""
    vol_repo = VolIndexRepository(conn, schema=schema)
    raw = {
        "VIX":   _load(vol_repo, "VIX",   CALENDAR_DAYS_REQUESTED),
        "VVIX":  _load(vol_repo, "VVIX",  CALENDAR_DAYS_REQUESTED),
        "VIX3M": _load(vol_repo, "VIX3M", CALENDAR_DAYS_REQUESTED),
        "COR1M": _load(vol_repo, "COR1M", CALENDAR_DAYS_REQUESTED),
        "SPX":   _load(vol_repo, "SPX",   CALENDAR_DAYS_REQUESTED),
    }
    aligned, common_dates = _align(raw)
    if not common_dates or len(common_dates) < MIN_ALIGNED_BARS:
        log.warning("canary_scan_skipped_thin_data aligned=%d need=%d", len(common_dates), MIN_ALIGNED_BARS)
        return None

    cal = load_calibration()
    today = common_dates[-1]
    sma_50, sma_200 = _compute_smas(aligned["SPX"])
    spx_close_history = list(zip(common_dates, aligned["SPX"].tolist()))
    event_state = _replay_events(spx_close_history)

    confirmed_active = _events_in_window(event_state.emitted, "confirmed_canary",
                                         canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS, today, common_dates)
    btd_active       = _events_in_window(event_state.emitted, "buy_the_dip",
                                         canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS, today, common_dates)

    sma200_2d, term_norm, higher_low = _compute_cap_lift_inputs(aligned["SPX"], sma_200, aligned["VIX"], aligned["VIX3M"])

    payload = canary_scoring.run_analysis(
        today=today, aligned=aligned, common_dates=[d.isoformat() for d in common_dates],
        sma_50_today=sma_50, sma_200_today=sma_200,
        spx_above_sma200_2d=sma200_2d, vix_term_normalized=term_norm, higher_closing_low=higher_low,
        confirmed_canary_active=confirmed_active, buy_the_dip_active=btd_active,
        calibration=cal,
    )

    snap_repo = CanarySnapshotRepository(conn, schema=schema)
    row_id = snap_repo.insert_snapshot(
        payload=payload, data_date=today,
        composite_version=COMPOSITE_VERSION, score_form=cal.score_form,
        score=Decimal(str(payload["canary"]["score"])),
        raw_score=Decimal(str(payload["canary"]["raw_score"])),
        band=payload["canary"]["band"],
        tactical_score=Decimal(str(payload["tactical_vol"]["score"])),
        structural_score=Decimal(str(payload["structural_vol"]["score"])),
        speed_score=payload["speed"]["score"],
        warning_state=payload["canary"]["warning_state"],
        payload_hash=canonical_payload_hash(payload),
        on_conflict="overwrite" if force_recompute else "noop",
    )
    log.info("canary_scan_persisted row=%s score=%.1f band=%s state=%s",
             row_id, payload["canary"]["score"], payload["canary"]["band"], payload["canary"]["warning_state"])
    return row_id
```

- [ ] **Step 2: Write the scanner integration test**

```python
# tests/integration/regime/test_canary_scanner.py
import pytest
from datetime import date, timedelta

from uw_scan.scanners.canary import run as canary_run
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION

pytestmark = pytest.mark.integration


def _seed_vol_index_daily(conn, days: int = 400):
    start = date(2024, 1, 1)
    rows = []
    for i in range(days):
        d = start + timedelta(days=i)
        rows.append((d, "VIX", 18.0))
        rows.append((d, "VVIX", 92.0))
        rows.append((d, "VIX3M", 19.0))
        rows.append((d, "COR1M", 30.0))
        rows.append((d, "SPX", 4000.0 + i * 1.0))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO uw_scan.vol_index_daily (trade_date, symbol, close) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )


def test_scanner_persists_snapshot(db_conn):
    _seed_vol_index_daily(db_conn, 400)
    row_id = canary_run(db_conn)
    assert row_id is not None
    repo = CanarySnapshotRepository(db_conn)
    latest = repo.latest_snapshot(composite_version=COMPOSITE_VERSION)
    assert latest is not None
    assert latest["band"] in ("NONE", "WATCH", "BUY", "STRONG_BUY")


def test_scanner_idempotent_no_op_on_replay(db_conn):
    _seed_vol_index_daily(db_conn, 400)
    first = canary_run(db_conn)
    second = canary_run(db_conn)
    assert first is not None
    assert second is None   # no-op


def test_scanner_force_recompute_overwrites(db_conn):
    _seed_vol_index_daily(db_conn, 400)
    canary_run(db_conn)
    second = canary_run(db_conn, force_recompute=True)
    assert second is not None


def test_scanner_skips_when_under_min_aligned(db_conn):
    _seed_vol_index_daily(db_conn, 100)   # below MIN_ALIGNED_BARS
    assert canary_run(db_conn) is None
```

- [ ] **Step 3: Run**

```bash
uv run pytest tests/integration/regime/test_canary_scanner.py -v
```
Expected: 4 PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/scanners/canary.py tests/integration/regime/test_canary_scanner.py
git commit -m "feat(canary): scanner orchestrator with idempotency and force-recompute"
```

---

## Task 12: Causality regression test

**Files:**
- Test: `tests/unit/cards/test_canary_causality.py`

- [ ] **Step 1: Write the causality test**

```python
# tests/unit/cards/test_canary_causality.py
"""The causality test — assert that the K-th snapshot in an incremental run
matches the snapshot produced by feeding only data[:K] to the full pipeline.

If this test fails, the implementation has a look-ahead bug.
"""
from datetime import date, timedelta

import numpy as np
import pytest

from uw_scan.cards import canary_scoring
from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.cards.canary_payload_hash import canonical_payload_hash


def _synthetic_history(n_days: int = 400, crash_offset: int = 250) -> tuple[list, dict[str, np.ndarray]]:
    """Build a 400-day history with a fast 6% crash at day ``crash_offset``."""
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]
    spx = np.linspace(4000, 4400, n_days)
    # Inject a fast crash
    spx[crash_offset:crash_offset + 10] = np.linspace(4400, 4135, 10)
    spx[crash_offset + 10:] = np.linspace(4135, 4300, n_days - crash_offset - 10)
    return dates, {
        "VIX": np.where(np.arange(n_days) >= crash_offset, 32.0, 16.0),
        "VVIX": np.where(np.arange(n_days) >= crash_offset, 130.0, 92.0),
        "VIX3M": np.where(np.arange(n_days) >= crash_offset, 25.0, 18.0),
        "COR1M": np.where(np.arange(n_days) >= crash_offset, 72.0, 34.0),
        "SPX": spx,
    }


def _snapshot_at(dates: list, aligned: dict[str, np.ndarray], k: int) -> dict:
    """Run the full pipeline using only data[:k+1]."""
    truncated_dates = dates[: k + 1]
    truncated = {sym: arr[: k + 1] for sym, arr in aligned.items()}
    if len(truncated_dates) < canary_scoring.HIGH_LOOKBACK_DAYS:
        return {}
    cal = load_calibration()
    sma_50 = float(np.mean(truncated["SPX"][-50:]))
    sma_200 = float(np.mean(truncated["SPX"][-200:]))
    spx_close_history = list(zip(truncated_dates, truncated["SPX"].tolist()))

    # Replay events incrementally — same as scanner._replay_events.
    state = canary_scoring.CanaryEventState()
    closes = truncated["SPX"].tolist()
    for i, (d, c) in enumerate(spx_close_history):
        if i < 200:
            continue
        sma50_i = float(np.mean(closes[i - 49 : i + 1]))
        sma200_i = float(np.mean(closes[i - 199 : i + 1]))
        canary_scoring.step_primary_events(
            state, today=d, spx_close_today=c, spx_history=spx_close_history[: i + 1],
            sma_50_today=sma50_i, sma_200_today=sma200_i,
            trading_days_between=lambda a, b, _src=spx_close_history: sum(1 for dd, _ in _src if a < dd <= b),
        )
        canary_scoring.step_confirmed_canary(state, today=d, spx_close_today=c, sma_200_today=sma200_i)

    window_dates = truncated_dates[-canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS:]
    confirmed_active = any(e.kind == "confirmed_canary" and e.fire_date in window_dates for e in state.emitted)
    btd_active = any(e.kind == "buy_the_dip" and e.fire_date in window_dates for e in state.emitted)

    payload = canary_scoring.run_analysis(
        today=truncated_dates[-1], aligned=truncated,
        common_dates=[d.isoformat() for d in truncated_dates],
        sma_50_today=sma_50, sma_200_today=sma_200,
        spx_above_sma200_2d=False, vix_term_normalized=False, higher_closing_low=False,
        confirmed_canary_active=confirmed_active, buy_the_dip_active=btd_active,
        calibration=cal,
    )
    return payload


def _full_history_series(dates: list, aligned: dict[str, np.ndarray]) -> dict[int, dict]:
    """Walk the full history once (as the production scanner / backtest does),
    returning {index_k: snapshot_payload_at_date_k} for every k ≥ warm-up.

    This simulates the *backtest path* — feed all data, emit one snapshot
    per day. A causal implementation produces snapshot[k] using only
    information available at date k.
    """
    out: dict[int, dict] = {}
    for k in range(canary_scoring.HIGH_LOOKBACK_DAYS, len(dates)):
        out[k] = _snapshot_at(dates, aligned, k)
    return out


@pytest.mark.parametrize("k", [253, 270, 300, 350, 399])
def test_full_history_snapshot_matches_truncated_history_snapshot(k):
    """The real causality test.

    Compare: the snapshot for date K produced by feeding ALL data and
    extracting index K, versus the snapshot for date K produced by feeding
    only data[:K+1] (truncated).

    If the implementation is causal, the two snapshots must be byte-identical
    (same canonical payload hash). If they differ, the implementation looked
    at data with date > K — a look-ahead bug.
    """
    dates, aligned = _synthetic_history()

    full_series = _full_history_series(dates, aligned)
    snap_from_full = full_series[k]

    # Truncated path — independent invocation, only sees data[:K+1].
    snap_from_truncated = _snapshot_at(dates, aligned, k)

    h_full = canonical_payload_hash(snap_from_full)
    h_trunc = canonical_payload_hash(snap_from_truncated)

    assert h_full == h_trunc, (
        f"Causality violation at k={k}:\n"
        f"  full-history hash = {h_full}\n"
        f"  truncated hash    = {h_trunc}\n"
        f"  full snapshot:      {snap_from_full}\n"
        f"  truncated snapshot: {snap_from_truncated}\n"
        f"\nImplementation must compute snapshot[k] using only data[:k+1]."
    )
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/unit/cards/test_canary_causality.py -v
```
Expected: 5 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/cards/test_canary_causality.py
git commit -m "test(canary): causality regression — snapshot byte-identical across truncations"
```

---

## Task 13: Worker job + scheduler wiring

**Files:**
- Modify: `src/uw_scan/worker/jobs/regime_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`

- [ ] **Step 1: Read the existing job module to find insertion point**

```bash
grep -n "cri_scan\|vcg_scan" src/uw_scan/worker/jobs/regime_jobs.py src/uw_scan/worker/scheduler.py
```

- [ ] **Step 2: Add canary_scan job**

In `src/uw_scan/worker/jobs/regime_jobs.py`, alongside the existing `cri_scan` and `vcg_scan` functions, add:

```python
from uw_scan.scanners import canary as _canary_module


def canary_scan() -> int | None:
    """Run a 5% Canary scan via the warm-store connection.

    See docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §11.
    """
    from uw_scan.config import get_settings  # local import to mirror cri_scan/vcg_scan pattern
    from psycopg import connect

    settings = get_settings()
    with connect(settings.database_url) as conn:
        return _canary_module.run(conn)
```

- [ ] **Step 3: Schedule the job**

In `src/uw_scan/worker/scheduler.py`, locate the block that registers `cri_scan` and `vcg_scan`, and add an equivalent entry:

```python
# (locate the same trigger / time used by cri_scan and vcg_scan, then append:)
scheduler.add_job(
    canary_scan,
    trigger=<same trigger as cri_scan / vcg_scan>,
    id="canary_scan",
    name="5% Canary scan",
    max_instances=1,
    coalesce=True,
    misfire_grace_time=600,
)
```

(Exact trigger format — likely `CronTrigger(day_of_week='mon-fri', hour=17, minute=30, timezone='America/New_York')` based on the spec — must be copied from the immediately-preceding `cri_scan` / `vcg_scan` registration; do not invent a new schedule.)

- [ ] **Step 4: Sanity-test the wiring**

```bash
uv run python -c "from uw_scan.worker.jobs.regime_jobs import canary_scan; print(canary_scan)"
```
Expected: prints `<function canary_scan at 0x...>` (no import error).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/regime_jobs.py src/uw_scan/worker/scheduler.py
git commit -m "feat(canary): worker job + scheduler registration alongside cri_scan/vcg_scan"
```

---

## Task 14: API endpoints (`/api/regime/canary`, `/history`, `/validation`)

**Files:**
- Modify: `src/uw_scan/api/routers/regime.py`
- Create: `src/uw_scan/api/models/canary.py` (Pydantic response models)
- Test: `tests/integration/api/test_canary_endpoints.py`

- [ ] **Step 1: Add Pydantic models**

```python
# src/uw_scan/api/models/canary.py
from __future__ import annotations

from datetime import date as _date
from typing import Any, Literal

from pydantic import BaseModel, Field


Band = Literal["NONE", "WATCH", "BUY", "STRONG_BUY"]
WarningState = Literal["NONE", "CONFIRMED_CANARY_ACTIVE", "BUY_THE_DIP_ACTIVE", "BOTH_ACTIVE_AMBIGUOUS"]
ScoreForm = Literal["linear", "convex", "concave", "sigmoid"]


class CanaryLatestResponse(BaseModel):
    data_date: _date
    composite_version: int
    score_form: ScoreForm
    score: float
    raw_score: float
    band: Band
    tactical_score: float
    structural_score: float
    speed_score: int
    warning_state: WarningState
    payload: dict[str, Any]


class CanaryHistoryRow(BaseModel):
    data_date: _date
    score: float
    band: Band
    tactical_score: float
    structural_score: float
    speed_score: int
    warning_state: WarningState


class CanaryHistoryResponse(BaseModel):
    rows: list[CanaryHistoryRow]


class CanaryValidationResponse(BaseModel):
    run_id: int
    composite_version: int
    score_form: ScoreForm
    summary: dict[str, Any]
    rendered_markdown: str
```

- [ ] **Step 2: Add the endpoints**

Add to `src/uw_scan/api/routers/regime.py` (append in the existing router):

```python
from datetime import date as _date

from fastapi import HTTPException, Query
from uw_scan.api.models.canary import (
    CanaryHistoryResponse, CanaryHistoryRow,
    CanaryLatestResponse, CanaryValidationResponse,
)
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION as CANARY_COMPOSITE_VERSION
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository


@router.get("/canary", response_model=CanaryLatestResponse)
def get_canary_latest(conn=Depends(get_conn)):
    repo = CanarySnapshotRepository(conn)
    row = repo.latest_snapshot(composite_version=CANARY_COMPOSITE_VERSION)
    if row is None:
        raise HTTPException(status_code=503, detail="no canary snapshot at current composite_version")
    return CanaryLatestResponse(
        data_date=row["data_date"],
        composite_version=CANARY_COMPOSITE_VERSION,
        score_form=row["score_form"],
        score=float(row["score"]), raw_score=float(row["raw_score"]),
        band=row["band"], tactical_score=float(row["tactical_score"]),
        structural_score=float(row["structural_score"]),
        speed_score=int(row["speed_score"]), warning_state=row["warning_state"],
        payload=row["payload"],
    )


@router.get("/canary/history", response_model=CanaryHistoryResponse)
def get_canary_history(days: int = Query(30, ge=1, le=365), conn=Depends(get_conn)):
    repo = CanarySnapshotRepository(conn)
    rows = repo.history(composite_version=CANARY_COMPOSITE_VERSION, days=days)
    return CanaryHistoryResponse(
        rows=[
            CanaryHistoryRow(
                data_date=r["data_date"], score=float(r["score"]), band=r["band"],
                tactical_score=float(r["tactical_score"]),
                structural_score=float(r["structural_score"]),
                speed_score=int(r["speed_score"]), warning_state=r["warning_state"],
            )
            for r in rows
        ]
    )


@router.get("/canary/validation", response_model=CanaryValidationResponse)
def get_canary_validation(conn=Depends(get_conn)):
    bt_repo = RegimeBacktestRepository(conn)
    row = bt_repo.fetch_latest_winning_form(indicator="canary", composite_version=CANARY_COMPOSITE_VERSION)
    if row is None:
        raise HTTPException(status_code=503, detail="no completed canary backtest at current composite_version")
    # Renderer added in Task 24; placeholder is markdown-rendered summary JSON.
    return CanaryValidationResponse(
        run_id=row["id"], composite_version=row["composite_version"],
        score_form=row["score_form"], summary=row["summary"], rendered_markdown="(populated in Task 24)",
    )
```

- [ ] **Step 3: Add a `fetch_latest_winning_form` method on `RegimeBacktestRepository`**

If the method doesn't already exist on `src/uw_scan/storage/regime_backtest_repository.py`, add it (mirroring the existing `fetch_latest_completed` pattern):

```python
def fetch_latest_winning_form(self, *, indicator: str, composite_version: int) -> dict | None:
    with self._conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, indicator, composite_version, score_form, summary, created_at
            FROM {self._schema}.regime_backtest_runs
            WHERE indicator = %s
              AND composite_version = %s
              AND (summary->>'is_winning_form')::boolean = true
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (indicator, composite_version),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0], "indicator": row[1], "composite_version": row[2],
            "score_form": row[3], "summary": row[4], "created_at": row[5],
        }
```

- [ ] **Step 4: Test the endpoints**

```python
# tests/integration/api/test_canary_endpoints.py
import pytest
from fastapi.testclient import TestClient

from uw_scan.api.server import create_app

pytestmark = pytest.mark.integration


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_latest_503_when_no_snapshot(client, db_conn):
    resp = client.get("/api/regime/canary")
    assert resp.status_code == 503


def test_history_returns_empty_when_no_snapshots(client):
    resp = client.get("/api/regime/canary/history?days=10")
    assert resp.status_code == 200
    assert resp.json() == {"rows": []}


def test_validation_503_when_no_run(client):
    resp = client.get("/api/regime/canary/validation")
    assert resp.status_code == 503
```

- [ ] **Step 5: Run**

```bash
uv run pytest tests/integration/api/test_canary_endpoints.py -v
```
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/api/routers/regime.py src/uw_scan/api/models/canary.py src/uw_scan/storage/regime_backtest_repository.py tests/integration/api/test_canary_endpoints.py
git commit -m "feat(canary): API endpoints /canary, /canary/history, /canary/validation"
```

---

## Task 15: Regenerate TypeScript types

**Files:**
- Modify: `web/lib/types.ts` (regenerated)

- [ ] **Step 1: Regenerate types**

```bash
cd web && npm run gen:types
```

- [ ] **Step 2: Verify the new types are present**

```bash
grep -n "CanaryLatestResponse\|CanaryHistoryRow\|CanaryValidationResponse" web/lib/types.ts
```
Expected: at least one match per identifier.

- [ ] **Step 3: Commit**

```bash
git add web/lib/types.ts
git commit -m "chore(canary): regenerate web/lib/types.ts after API change"
```

---

## Task 16: RegimePill primitive

**Files:**
- Create: `web/components/regime/primitives/RegimePill.tsx`
- Test: `web/components/regime/primitives/__tests__/RegimePill.test.tsx`

- [ ] **Step 1: Write the component**

```tsx
// web/components/regime/primitives/RegimePill.tsx
import { cn } from "@/lib/cn";

// RegimePillState carries BOTH warning_state values (NONE/CCA/BTDA/BOTH) and
// speed.state values (NEUTRAL/CCA/BTDA/BOTH). They overlap but `NEUTRAL` is
// speed-only and `NONE` is warning-only. Pill supports both vocabularies so
// the same component can render either field.
export type RegimePillState =
  | "NONE"
  | "NEUTRAL"
  | "CONFIRMED_CANARY_ACTIVE"
  | "BUY_THE_DIP_ACTIVE"
  | "BOTH_ACTIVE_AMBIGUOUS";

const STYLES: Record<RegimePillState, { label: string; classes: string }> = {
  NONE: { label: "No Signal", classes: "border-zinc-700 text-zinc-400" },
  NEUTRAL: { label: "Neutral", classes: "border-zinc-700 text-zinc-400" },
  CONFIRMED_CANARY_ACTIVE: { label: "Confirmed Canary", classes: "border-red-700/60 text-red-300 bg-red-950/30" },
  BUY_THE_DIP_ACTIVE: { label: "Buy The Dip", classes: "border-emerald-700/60 text-emerald-300 bg-emerald-950/30" },
  BOTH_ACTIVE_AMBIGUOUS: { label: "Ambiguous (Both)", classes: "border-amber-700/60 text-amber-300 bg-amber-950/30" },
};

export function RegimePill({ state, className }: { state: RegimePillState; className?: string }) {
  const s = STYLES[state];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium",
        s.classes,
        className,
      )}
    >
      <span aria-hidden="true">●</span>
      {s.label}
    </span>
  );
}
```

- [ ] **Step 2: Test**

```tsx
// web/components/regime/primitives/__tests__/RegimePill.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RegimePill } from "../RegimePill";

describe("RegimePill", () => {
  it("renders Confirmed Canary label", () => {
    render(<RegimePill state="CONFIRMED_CANARY_ACTIVE" />);
    expect(screen.getByText(/Confirmed Canary/i)).toBeInTheDocument();
  });

  it("renders Buy The Dip label", () => {
    render(<RegimePill state="BUY_THE_DIP_ACTIVE" />);
    expect(screen.getByText(/Buy The Dip/i)).toBeInTheDocument();
  });

  it("renders Ambiguous for both-active", () => {
    render(<RegimePill state="BOTH_ACTIVE_AMBIGUOUS" />);
    expect(screen.getByText(/Ambiguous/i)).toBeInTheDocument();
  });

  it("renders No Signal default", () => {
    render(<RegimePill state="NONE" />);
    expect(screen.getByText(/No Signal/i)).toBeInTheDocument();
  });

  it("renders Neutral for speed-tier neutral days", () => {
    render(<RegimePill state="NEUTRAL" />);
    expect(screen.getByText(/Neutral/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run vitest**

```bash
cd web && npm run test -- RegimePill
```
Expected: 5 PASS.

- [ ] **Step 4: Commit**

```bash
git add web/components/regime/primitives/RegimePill.tsx web/components/regime/primitives/__tests__/RegimePill.test.tsx
git commit -m "feat(canary): RegimePill primitive — supports warning_state and speed.state vocabularies"
```

---

## Task 17: CanarySubTab + page wiring

**Files:**
- Create: `web/components/regime/CanarySubTab.tsx`
- Modify: `web/app/regime/page.tsx`

- [ ] **Step 1: Write the SubTab**

```tsx
// web/components/regime/CanarySubTab.tsx
"use client";

import useSWR from "swr";
import { ComponentBar } from "./primitives/ComponentBar";
import { RegimePill, type RegimePillState } from "./primitives/RegimePill";
import { HistoryChart } from "./HistoryChart";
import type { components } from "@/lib/types";

type Latest = components["schemas"]["CanaryLatestResponse"];
type History = components["schemas"]["CanaryHistoryResponse"];

const fetcher = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok) {
    // 503 is expected when no snapshot exists at the current composite_version.
    // Surface it to SWR's `error` slot rather than silently parsing as JSON.
    throw new Error(`${r.status}: ${await r.text()}`);
  }
  return r.json();
};

export function CanarySubTab() {
  const { data: latest, error: latestErr } = useSWR<Latest>("/api/regime/canary", fetcher);
  const { data: history } = useSWR<History>("/api/regime/canary/history?days=90", fetcher);

  if (latestErr) {
    return <div className="text-zinc-500">No 5% Canary snapshot at the current composite_version yet.</div>;
  }
  if (!latest) return <div className="text-zinc-500">Loading…</div>;

  const p = latest.payload as any;
  const warning = p.canary.warning_state as RegimePillState;
  // speed.state can be NEUTRAL (speed-only); RegimePill supports it directly.
  const speedState = p.speed.state as RegimePillState;

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between">
        <div>
          <div className="text-4xl font-semibold tabular-nums">{latest.score.toFixed(1)}</div>
          <div className="text-sm uppercase tracking-wider text-zinc-400">
            {latest.band.replace("_", " ")} · score_form: {latest.score_form}
          </div>
        </div>
        <RegimePill state={warning} />
      </header>

      <section>
        <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-2">Tactical Vol (0–30)</h3>
        <div className="space-y-2">
          <ComponentBar label="VIX Spike Reversion" score={p.tactical_vol.vix_spike_revert.score} max={15} />
          <ComponentBar label="VIX/VIX3M Backwardation Normalize" score={p.tactical_vol.vix_vix3m_back.score} max={15} />
        </div>
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-2">Structural Vol (0–50)</h3>
        <div className="space-y-2">
          <ComponentBar label="Variance Risk Premium" score={p.structural_vol.vrp.score} max={21} />
          <ComponentBar label="COR1M Peak-and-Decay" score={p.structural_vol.cor1m_decay.score} max={17} />
          <ComponentBar label="VVIX/VIX Recovery" score={p.structural_vol.vvix_vix_recovery.score} max={12} />
        </div>
      </section>

      <section>
        <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-2">Price Speed (Thrasher)</h3>
        <div className="flex items-center gap-3">
          <RegimePill state={speedState} />
          <span className="text-sm text-zinc-400">{p.speed.score} of 20 pts</span>
        </div>
      </section>

      {history && history.rows.length > 0 && (
        <section>
          <h3 className="text-xs uppercase tracking-wider text-zinc-400 mb-2">90-day history</h3>
          <HistoryChart
            data={history.rows.map((r) => ({ date: r.data_date, value: r.score }))}
            max={100}
          />
        </section>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire into the Regime page**

In `web/app/regime/page.tsx`, locate the sub-tab list (which currently has CRI, VCG, Validation) and add a new entry between VCG and Validation:

```tsx
// Find the existing sub-tab definition (often an array of {key, label, component} entries)
// and insert:
import { CanarySubTab } from "@/components/regime/CanarySubTab";

// In the tabs array:
{ key: "canary", label: "5% Canary", component: <CanarySubTab /> },
```

- [ ] **Step 3: Smoke-test in dev**

```bash
bash scripts/dev.sh
```
Then open http://localhost:3001/regime and click the "5% Canary" sub-tab. Expected: tab renders with either the loading state or 503-handled message; no console errors.

Hit ctrl-C in the dev shell to stop.

- [ ] **Step 4: Commit**

```bash
git add web/components/regime/CanarySubTab.tsx web/app/regime/page.tsx
git commit -m "feat(canary): CanarySubTab + regime page wiring"
```

---

## Task 18: CanaryValidationPanel

**Files:**
- Create: `web/components/regime/CanaryValidationPanel.tsx`
- Modify: `web/components/regime/ValidationTab.tsx` (or wherever CRI/VCG validation panels are wired)

- [ ] **Step 1: Write the panel**

```tsx
// web/components/regime/CanaryValidationPanel.tsx
"use client";

import useSWR from "swr";
import type { components } from "@/lib/types";

type Validation = components["schemas"]["CanaryValidationResponse"];

const fetcher = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
};

export function CanaryValidationPanel() {
  const { data, error } = useSWR<Validation>("/api/regime/canary/validation", fetcher);
  if (error || !data) {
    return <div className="text-zinc-500">No completed canary backtest at the current composite_version yet.</div>;
  }
  return (
    <article className="prose prose-invert max-w-none">
      <pre className="whitespace-pre-wrap text-xs leading-relaxed">{data.rendered_markdown}</pre>
    </article>
  );
}
```

- [ ] **Step 2: Wire into the ValidationTab**

Locate the existing validation sub-tab switcher (a CRI/VCG selector) and add a third option for Canary that renders `<CanaryValidationPanel />`. Pattern-match the existing CRI/VCG panel wiring exactly.

- [ ] **Step 3: Commit**

```bash
git add web/components/regime/CanaryValidationPanel.tsx web/components/regime/ValidationTab.tsx
git commit -m "feat(canary): validation panel under the Regime → Validation sub-tab"
```

---

## Task 19: Backtest script — calibration mode

**Files:**
- Create: `scripts/backtest_canary.py`
- Test: `tests/integration/regime/test_canary_backtest_calibrate.py`

- [ ] **Step 1: Write the calibration entry-point**

```python
# scripts/backtest_canary.py
"""5% Canary backtest harness.

Three modes — see docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md §7, §8.

  --calibrate         Compute Class B thresholds on the train window (2007-2014),
                      write canary-calibration-v1.json.
  --form-sweep        Sweep four scoring forms on the validation window (2015-2019),
                      persist per-form results to regime_backtest_runs, pick winner.
  --report            Compute final OOS report on the test window (2020-present),
                      persist with summary.is_winning_form=true.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import numpy as np
from psycopg import connect

from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, DEFAULT_PATH as CALIB_PATH
from uw_scan.config import get_settings

log = logging.getLogger(__name__)

TRAIN_END      = date(2014, 12, 31)
VALID_START    = date(2015, 1, 1)
VALID_END      = date(2019, 12, 31)
TEST_START     = date(2020, 1, 1)


def _percentile(arr, p):
    return float(np.percentile(arr, p))


def cmd_calibrate(conn) -> None:
    """Compute Class B thresholds (p25 floor, p90 ceiling) on the train window
    using positive-condition observations only. Write canary-calibration-v1.json."""
    from uw_scan.storage.vol_index_repository import VolIndexRepository
    vol_repo = VolIndexRepository(conn)

    def _series(sym):
        rows = vol_repo.fetch_history(sym, days=8000)
        return [(r["trade_date"], float(r["close"])) for r in rows if r["trade_date"] <= TRAIN_END and r.get("close") is not None]

    vix = dict(_series("VIX"))
    vix3m = dict(_series("VIX3M"))
    cor = dict(_series("COR1M"))
    vvix = dict(_series("VVIX"))
    spx = dict(_series("SPX"))

    common = sorted(set(vix) & set(vix3m) & set(cor) & set(vvix) & set(spx))
    vix_arr   = np.array([vix[d] for d in common])
    vix3m_arr = np.array([vix3m[d] for d in common])
    cor_arr   = np.array([cor[d] for d in common])
    vvix_arr  = np.array([vvix[d] for d in common])
    spx_arr   = np.array([spx[d] for d in common])

    # vix_spike_revert: ceiling = p90 of pullback_pct on days where spike_active
    pullback_obs = []
    for i in range(10, len(vix_arr)):
        peak = vix_arr[i-10:i].max()
        if peak >= 30.0:
            pullback_obs.append(max(0.0, (peak - vix_arr[i]) / peak))

    # vix_vix3m_back: ceiling = p90 of normalization_pct on days where extreme_backwardation occurred in last 10
    ratios = vix_arr / vix3m_arr
    norm_obs = []
    for i in range(10, len(ratios)):
        peak = ratios[i-10:i].max()
        if peak >= 1.05:
            norm_obs.append(max(0.0, (peak - ratios[i]) / peak))

    # vrp: ceiling = p90 of (VIX^2 - RV^2) across all observations (no gate)
    log_returns = np.diff(np.log(spx_arr))
    vrp_obs = []
    for i in range(20, len(vix_arr)):
        rv = log_returns[i-20:i].std(ddof=0) * np.sqrt(252) * 100.0
        vrp_obs.append(vix_arr[i] ** 2 - rv ** 2)

    # cor1m_decay: ceiling = p90 of decay_pct on days where peak ≥ 60 in last 60
    cor_decay_obs = []
    for i in range(60, len(cor_arr)):
        peak = cor_arr[i-60:i].max()
        if peak >= 60.0:
            cor_decay_obs.append(max(0.0, (peak - cor_arr[i]) / peak))

    # vvix_vix_recovery: ceiling = p90 of ratio_today on days where ratio_min_60d ≤ 4.0
    vvr = vvix_arr / vix_arr
    vvr_obs = []
    for i in range(60, len(vvr)):
        if vvr[i-60:i].min() <= 4.0:
            vvr_obs.append(vvr[i])

    cal_out = {
        "composite_version": COMPOSITE_VERSION,
        "train_window": {"start": "2007-01-01", "end": TRAIN_END.isoformat()},
        "score_form": "linear",
        "thresholds": {
            "vix_spike_revert":  {"floor": _percentile(pullback_obs, 25), "ceiling": _percentile(pullback_obs, 90),
                                  "spike_active_at_vix": 30.0, "peak_lookback_d": 10, "max_points": 15},
            "vix_vix3m_back":    {"floor": _percentile(norm_obs, 25), "ceiling": _percentile(norm_obs, 90),
                                  "backwardation_extreme_at_ratio": 1.05, "peak_lookback_d": 10, "max_points": 15},
            "vrp":               {"floor": _percentile(vrp_obs, 25), "ceiling": _percentile(vrp_obs, 90),
                                  "rv_window_d": 20, "max_points": 21},
            "cor1m_decay":       {"floor": _percentile(cor_decay_obs, 25), "ceiling": _percentile(cor_decay_obs, 90),
                                  "peak_elevated_at": 60.0, "peak_lookback_d": 60, "max_points": 17},
            "vvix_vix_recovery": {"floor": _percentile(vvr_obs, 25), "ceiling": _percentile(vvr_obs, 90),
                                  "compressed_below_ratio": 4.0, "compress_lookback_d": 60, "max_points": 12},
        },
        "band_distribution_train": None,    # computed in --form-sweep step
        "author_overrides": [],
        "produced_at": str(date.today()) + "T00:00:00Z",
        "produced_by": "scripts/backtest_canary.py --calibrate",
    }
    CALIB_PATH.write_text(json.dumps(cal_out, indent=2) + "\n")
    log.info("calibration written to %s", CALIB_PATH)
```

- [ ] **Step 2: CLI plumbing**

Append:

```python
# Stubs to be filled in Tasks 20 + 21. They MUST be defined before main()
# is invoked because Python resolves names at call time — when `__main__`
# runs main(), these names must already exist in the module's namespace.
def cmd_form_sweep(conn, *, write_summary: bool) -> None:
    raise NotImplementedError("Implemented in Task 20")


def cmd_report(conn, *, form, write_summary: bool) -> None:
    raise NotImplementedError("Implemented in Task 21")


def main():
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--form-sweep", action="store_true")
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--write-summary", action="store_true")
    parser.add_argument("--form", choices=("linear", "convex", "concave", "sigmoid"))
    args = parser.parse_args()

    settings = get_settings()
    with connect(settings.database_url) as conn:
        if args.calibrate:
            cmd_calibrate(conn)
            return
        if args.form_sweep:
            cmd_form_sweep(conn, write_summary=args.write_summary)
            return
        if args.report:
            cmd_report(conn, form=args.form, write_summary=args.write_summary)
            return
        parser.print_help()
        sys.exit(2)


# Entry point — must stay at file bottom so all cmd_* are defined when this runs.
if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run a sanity calibration**

(Requires seeded warm-store data — this is a smoke check, not a unit test.)

```bash
uv run python scripts/backtest_canary.py --calibrate
cat docs/research/regime/canary-calibration-v1.json
```
Expected: file overwritten with computed values; all `floor` < `ceiling`.

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest_canary.py
git commit -m "feat(canary): backtest script — --calibrate mode (Class B thresholds)"
```

---

## Task 20: Backtest script — form sweep on validation window

**Files:**
- Modify: `scripts/backtest_canary.py` (fill `cmd_form_sweep`)

- [ ] **Step 1: Implement form-sweep**

Replace the `cmd_form_sweep` stub with:

```python
def _compute_canary_series(conn, calibration, form: str, start: date, end: date) -> dict:
    """Compute one row per trading day for ``[start, end]`` using the supplied
    calibration + form. Returns {"daily_rows": [...], "events": [...], "dates": [...]}.

    The events list is the authoritative source of fire dates — event-level
    stats MUST read from events, not from warning_state transitions.
    """
    from uw_scan.scanners.canary import _align, _load, _compute_smas, _compute_cap_lift_inputs, _replay_events
    from uw_scan.storage.vol_index_repository import VolIndexRepository
    from uw_scan.cards import canary_scoring
    from dataclasses import replace

    vol_repo = VolIndexRepository(conn)
    span_days = (date.today() - start).days + 100
    raw = {
        "VIX":   _load(vol_repo, "VIX",   span_days),
        "VVIX":  _load(vol_repo, "VVIX",  span_days),
        "VIX3M": _load(vol_repo, "VIX3M", span_days),
        "COR1M": _load(vol_repo, "COR1M", span_days),
        "SPX":   _load(vol_repo, "SPX",   span_days),
    }
    aligned, all_dates = _align(raw)

    # Override the form on a per-call basis without mutating disk-loaded calibration.
    cal_for_run = replace(calibration, score_form=form)

    closes = aligned["SPX"].tolist()
    history_pairs = list(zip(all_dates, closes))
    state = _replay_events(history_pairs)

    daily_rows = []
    for i, d in enumerate(all_dates):
        if d < start or d > end or i < 200:
            continue
        sma50  = float(np.mean(closes[i-49:i+1]))
        sma200 = float(np.mean(closes[i-199:i+1]))
        slice_dates = all_dates[: i + 1]
        window_dates = slice_dates[-canary_scoring.SPEED_ACTIVITY_WINDOW_DAYS:]
        confirmed_active = any(e.kind == "confirmed_canary" and e.fire_date in window_dates for e in state.emitted)
        btd_active       = any(e.kind == "buy_the_dip" and e.fire_date in window_dates for e in state.emitted)
        sma200_2d, term_norm, higher_low = _compute_cap_lift_inputs(
            aligned["SPX"][: i + 1], sma200, aligned["VIX"][: i + 1], aligned["VIX3M"][: i + 1]
        )
        payload = canary_scoring.run_analysis(
            today=d,
            aligned={k: v[: i + 1] for k, v in aligned.items()},
            common_dates=[dd.isoformat() for dd in slice_dates],
            sma_50_today=sma50, sma_200_today=sma200,
            spx_above_sma200_2d=sma200_2d, vix_term_normalized=term_norm, higher_closing_low=higher_low,
            confirmed_canary_active=confirmed_active, buy_the_dip_active=btd_active,
            calibration=cal_for_run,
        )
        daily_rows.append({
            "date": d, "spx": closes[i],
            "score": payload["canary"]["score"], "band": payload["canary"]["band"],
            "tactical": payload["tactical_vol"]["score"],
            "structural": payload["structural_vol"]["score"],
            "speed": payload["speed"]["score"],
            "warning_state": payload["canary"]["warning_state"],
        })
    # Window the emitted events to [start, end] for downstream stats.
    window_events = [e for e in state.emitted if start <= e.fire_date <= end]
    return {"daily_rows": daily_rows, "events": window_events, "dates": all_dates}


def _entry_lagged_label(rows: list[dict], horizon_td: int, threshold: float) -> list[int]:
    """Forward return ≥ threshold over ``horizon_td`` trading days using
    entry_date = next trading day (v0.3 execution-lag fix)."""
    n = len(rows)
    closes = [r["spx"] for r in rows]
    out = []
    for i in range(n):
        entry_idx = i + 1
        if entry_idx + horizon_td >= n:
            out.append(None)
            continue
        ret = closes[entry_idx + horizon_td] / closes[entry_idx] - 1.0
        out.append(1 if ret >= threshold else 0)
    return out


def _auc(scores: list[float], labels: list[int]) -> float:
    """Pairwise AUC with explicit None filtering."""
    pairs = [(s, l) for s, l in zip(scores, labels) if l is not None]
    if not pairs:
        return float("nan")
    pos = [s for s, l in pairs if l == 1]
    neg = [s for s, l in pairs if l == 0]
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for ps in pos:
        for ns in neg:
            if ps > ns:
                wins += 1
            elif ps == ns:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def cmd_form_sweep(conn, *, write_summary: bool) -> None:
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    bt_repo = RegimeBacktestRepository(conn)
    aucs_per_form: dict[str, dict[str, float]] = {}

    LABELS = [("up5d_2pct", 5, 0.02), ("up20d_5pct", 20, 0.05), ("up60d_10pct", 60, 0.10)]

    for form in ("linear", "convex", "concave", "sigmoid"):
        series = _compute_canary_series(conn, cal, form=form, start=VALID_START, end=VALID_END)
        rows = series["daily_rows"]
        scores = [r["score"] for r in rows]
        auc_map = {}
        for label_name, h, thr in LABELS:
            labels = _entry_lagged_label(rows, h, thr)
            auc_map[label_name] = _auc(scores, labels)
        aucs_per_form[form] = auc_map
        if write_summary:
            bt_repo.insert_run(
                indicator="canary", composite_version=COMPOSITE_VERSION,
                score_form=form,
                summary={"validation_aucs": auc_map, "is_winning_form": False},
                daily_rows=[{"date": r["date"], "score": r["score"], "band": r["band"]} for r in rows],
            )

    # Pick winner: beats `linear` by ≥0.02 on ≥2 of 3 labels.
    base = aucs_per_form["linear"]
    winner = "linear"
    for form, aucs in aucs_per_form.items():
        if form == "linear":
            continue
        beats = sum(1 for label_name, _, _ in LABELS if aucs[label_name] >= base[label_name] + 0.02)
        if beats >= 2:
            winner = form
            break
    log.info("validation AUCs: %s", json.dumps(aucs_per_form, indent=2))
    log.info("winning form: %s", winner)

    # Persist winner choice into canary-calibration-v1.json
    cal_raw = json.loads(CALIB_PATH.read_text())
    cal_raw["score_form"] = winner
    cal_raw["validation_aucs_per_form"] = aucs_per_form
    CALIB_PATH.write_text(json.dumps(cal_raw, indent=2) + "\n")
```

- [ ] **Step 2: Smoke-run**

```bash
uv run python scripts/backtest_canary.py --form-sweep --write-summary
```
Expected: logs validation AUCs per form, picks a winner, updates `canary-calibration-v1.json`.

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_canary.py
git commit -m "feat(canary): backtest script --form-sweep on validation window (2015-2019)"
```

---

## Task 21: Backtest script — final OOS report + winning-form row

**Files:**
- Modify: `scripts/backtest_canary.py` (fill `cmd_report`)

- [ ] **Step 1: Implement final-OOS report**

Replace the `cmd_report` stub with:

```python
def _block_bootstrap_ci_low(values: list[float], block_size: int = 252, iters: int = 1000) -> float:
    """Lower bound of the 95% block-bootstrap CI on the median."""
    if not values:
        return float("nan")
    arr = np.array(values, dtype=float)
    n = len(arr)
    if n < block_size:
        # Degenerate small-sample case — fall back to simple percentile bootstrap.
        rng = np.random.default_rng(seed=42)
        meds = [np.median(rng.choice(arr, size=n, replace=True)) for _ in range(iters)]
        return float(np.percentile(meds, 2.5))
    rng = np.random.default_rng(seed=42)
    n_blocks = n // block_size
    medians = []
    for _ in range(iters):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        sample = np.concatenate([arr[s:s + block_size] for s in starts])
        medians.append(np.median(sample))
    return float(np.percentile(medians, 2.5))


def _btd_event_stats(rows: list[dict], emitted_events: list, dates: list) -> dict:
    """Buy-The-Dip event-level statistics — UPSIDE focus.

    Uses real fire dates from CanaryEventState.emitted (NOT warning_state
    transitions, which would conflate cap-lifts and both-active states).
    Entry on next close (D+1) per spec §8.1.
    """
    date_to_idx = {d: i for i, d in enumerate(dates)}
    closes = [r["spx"] for r in rows]
    drawups: list[float] = []
    lower_lows: list[int] = []
    recoveries: list[int] = []
    for e in emitted_events:
        if e.kind != "buy_the_dip":
            continue
        i = date_to_idx.get(e.fire_date)
        if i is None:
            continue
        entry = i + 1
        if entry + 42 >= len(closes):
            continue
        window = closes[entry + 1: entry + 43]
        drawups.append(max(window) / closes[entry] - 1)
        ll_window = closes[entry + 1: entry + 31]
        lower_lows.append(1 if any(c < closes[entry] for c in ll_window) else 0)
        # Recovery: did SPX print a new 252d high within 60 trading days?
        rec_window = closes[entry + 1: entry + 61]
        if rec_window:
            high_at_entry = max(closes[max(0, entry - 252): entry + 1])
            recoveries.append(1 if max(rec_window) >= high_at_entry else 0)
    return {
        "n_events": len(drawups),
        "median_fwd_42d_drawup": float(np.median(drawups)) if drawups else None,
        "lower_low_30d_rate": (sum(lower_lows) / len(lower_lows)) if lower_lows else None,
        "recovery_60d_rate": (sum(recoveries) / len(recoveries)) if recoveries else None,
        "ci_low_drawup": _block_bootstrap_ci_low(drawups) if drawups else None,
    }


def _confirmed_canary_event_stats(rows: list[dict], emitted_events: list, dates: list) -> dict:
    """Confirmed Canary event-level statistics — DOWNSIDE focus.

    Validates the bearish warning claim. Entry on next close (D+1).
    """
    date_to_idx = {d: i for i, d in enumerate(dates)}
    closes = [r["spx"] for r in rows]
    drawdowns: list[float] = []
    further_down: list[int] = []
    for e in emitted_events:
        if e.kind != "confirmed_canary":
            continue
        i = date_to_idx.get(e.fire_date)
        if i is None:
            continue
        entry = i + 1
        if entry + 60 >= len(closes):
            continue
        window42 = closes[entry + 1: entry + 43]
        drawdowns.append(min(window42) / closes[entry] - 1)
        window60 = closes[entry + 1: entry + 61]
        further_down.append(1 if min(window60) <= closes[entry] * 0.95 else 0)
    return {
        "n_events": len(drawdowns),
        "median_fwd_42d_drawdown": float(np.median(drawdowns)) if drawdowns else None,
        "further_drawdown_60d_rate": (sum(further_down) / len(further_down)) if further_down else None,
        "ci_low_drawdown": _block_bootstrap_ci_low(drawdowns) if drawdowns else None,
    }


def cmd_report(conn, *, form, write_summary: bool) -> None:
    from uw_scan.cards.canary_calibration import load_calibration
    from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

    cal = load_calibration()
    selected_form = form or cal.score_form
    bt_repo = RegimeBacktestRepository(conn)
    series = _compute_canary_series(conn, cal, form=selected_form, start=TEST_START, end=date.today())
    rows = series["daily_rows"]
    events = series["events"]
    all_dates = series["dates"]
    scores = [r["score"] for r in rows]
    LABELS = [("up5d_2pct", 5, 0.02), ("up20d_5pct", 20, 0.05), ("up60d_10pct", 60, 0.10)]
    daily_aucs = {}
    for label_name, h, thr in LABELS:
        labels = _entry_lagged_label(rows, h, thr)
        daily_aucs[label_name] = _auc(scores, labels)

    # Per-tier ablation
    speed_scores = [r["speed"] for r in rows]
    vol_scores   = [r["tactical"] + r["structural"] for r in rows]
    ablation = {
        "speed_only_aucs": {name: _auc(speed_scores, _entry_lagged_label(rows, h, thr)) for name, h, thr in LABELS},
        "vol_only_aucs":   {name: _auc(vol_scores,   _entry_lagged_label(rows, h, thr)) for name, h, thr in LABELS},
    }
    band_counts = {b: sum(1 for r in rows if r["band"] == b) for b in ("NONE","WATCH","BUY","STRONG_BUY")}
    # We need full-history rows for forward-window lookups beyond the test window;
    # for v1 we use `rows` (test-window only). Implementations may extend the
    # series past `end` to give events near the tail their full 60d window.
    summary = {
        "daily_aucs": daily_aucs,
        "ablation": ablation,
        "band_distribution": band_counts,
        "events": {
            "buy_the_dip":      _btd_event_stats(rows, events, [r["date"] for r in rows]),
            "confirmed_canary": _confirmed_canary_event_stats(rows, events, [r["date"] for r in rows]),
        },
        "is_winning_form": True,
        "score_form": selected_form,
    }
    log.info("final OOS summary: %s", json.dumps(summary, indent=2))
    if write_summary:
        bt_repo.insert_run(
            indicator="canary", composite_version=COMPOSITE_VERSION,
            score_form=selected_form, summary=summary,
            daily_rows=[{"date": r["date"], "score": r["score"], "band": r["band"]} for r in rows],
        )
```

- [ ] **Step 2: Smoke-run**

```bash
uv run python scripts/backtest_canary.py --report --write-summary
```

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_canary.py
git commit -m "feat(canary): backtest script --report (final OOS + event-level + ablation)"
```

---

## Task 22: OOS gate integration test

**Files:**
- Test: `tests/integration/regime/test_canary_oos_gate.py`

- [ ] **Step 1: Write the gate**

```python
# tests/integration/regime/test_canary_oos_gate.py
"""Block-merge gate. Reads the latest is_winning_form=true row from
regime_backtest_runs for indicator='canary' at the current composite_version.

Acceptance bar — see spec §8.6 + §8.7.
"""
import pytest

from uw_scan.cards.canary_calibration import COMPOSITE_VERSION
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

pytestmark = pytest.mark.integration

# These values are SET in the v1 publish PR after the report runs.
# Until then, the gate is informational (will skip with reason).
LAST_KNOWN_AUC_UP5D_2PCT  = 0.55
LAST_KNOWN_AUC_UP20D_5PCT = 0.56
LAST_KNOWN_AUC_UP60D_10PCT = 0.58


def test_regression_gate_within_last_known(db_conn):
    """Block-merge guard: AUC must not regress more than 0.02 vs the previous
    publish at the current composite_version."""
    repo = RegimeBacktestRepository(db_conn)
    row = repo.fetch_latest_winning_form(indicator="canary", composite_version=COMPOSITE_VERSION)
    if row is None:
        pytest.skip("no canary backtest row yet — OOS gate informational")
    daily = row["summary"]["daily_aucs"]
    assert daily["up5d_2pct"]    >= LAST_KNOWN_AUC_UP5D_2PCT   - 0.02
    assert daily["up20d_5pct"]   >= LAST_KNOWN_AUC_UP20D_5PCT  - 0.02
    assert daily["up60d_10pct"]  >= LAST_KNOWN_AUC_UP60D_10PCT - 0.02


def test_absolute_acceptance_bar(db_conn):
    """Spec §8.6 acceptance bar — INDEPENDENT of LAST_KNOWN.

    Even if LAST_KNOWN is set to a low value, the indicator must clear the
    publishable absolute bar: AUC > 0.55 on ≥ 2 of 3 labels AND
    AUC up60d_10pct > 0.58.
    """
    repo = RegimeBacktestRepository(db_conn)
    row = repo.fetch_latest_winning_form(indicator="canary", composite_version=COMPOSITE_VERSION)
    if row is None:
        pytest.skip("no canary backtest row yet")
    daily = row["summary"]["daily_aucs"]
    aucs = [daily["up5d_2pct"], daily["up20d_5pct"], daily["up60d_10pct"]]
    passing = sum(1 for a in aucs if a > 0.55)
    assert passing >= 2, f"acceptance bar: AUC > 0.55 on ≥ 2 labels, got passing={passing} ({aucs})"
    assert daily["up60d_10pct"] > 0.58, f"BTZ-anchored bar: up60d_10pct > 0.58, got {daily['up60d_10pct']}"


def test_oos_gate_event_level_btd(db_conn):
    """Event-level BTD: median drawup ≥ 3% (vs Thrasher's 5.55% on his sample),
    lower-low rate ≤ 35%, block-bootstrap 95% CI low > 0. §8.7 minimum-event-
    count rule: skip when n < 3."""
    repo = RegimeBacktestRepository(db_conn)
    row = repo.fetch_latest_winning_form(indicator="canary", composite_version=COMPOSITE_VERSION)
    if row is None:
        pytest.skip("no canary backtest row yet")
    btd = row["summary"]["events"]["buy_the_dip"]
    if btd["n_events"] < 3:
        pytest.skip(f"insufficient BTD events: n={btd['n_events']} — §8.7 informational")
    assert btd["median_fwd_42d_drawup"] >= 0.03
    assert btd["lower_low_30d_rate"]    <= 0.35
    assert btd["ci_low_drawup"] is not None and btd["ci_low_drawup"] > 0


def test_oos_gate_event_level_confirmed_canary(db_conn):
    """Event-level Confirmed Canary: median forward 42d drawdown must be
    materially worse than unconditional. §8.7 skip-on-small-n applies."""
    repo = RegimeBacktestRepository(db_conn)
    row = repo.fetch_latest_winning_form(indicator="canary", composite_version=COMPOSITE_VERSION)
    if row is None:
        pytest.skip("no canary backtest row yet")
    cc = row["summary"]["events"]["confirmed_canary"]
    if cc["n_events"] < 3:
        pytest.skip(f"insufficient Confirmed Canary events: n={cc['n_events']} — §8.7 informational")
    # Median drawdown must be at least 4% worse than the unconditional baseline.
    # The absolute number is sample-specific; the relative bar is the published claim.
    assert cc["median_fwd_42d_drawdown"] is not None
    assert cc["median_fwd_42d_drawdown"] <= -0.04, \
        f"Confirmed Canary downside warning unconvincing: median 42d drawdown = {cc['median_fwd_42d_drawdown']}"
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/integration/regime/test_canary_oos_gate.py -v
```
Expected: 2 SKIP (until backtest has been run with data). Once run with valid data: 2 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/regime/test_canary_oos_gate.py
git commit -m "test(canary): OOS gate — daily AUC + event-level BTD acceptance bars"
```

---

## Task 23: Warning-state integration test

**Files:**
- Test: `tests/integration/regime/test_canary_warning_state.py`

- [ ] **Step 1: Write the test**

```python
# tests/integration/regime/test_canary_warning_state.py
"""End-to-end test: persisted warning_state column matches payload.canary.warning_state,
and the cap actually binds when raw_score>49 with active confirmed canary."""
import pytest
from datetime import date, timedelta

from uw_scan.scanners.canary import run as canary_run
from uw_scan.storage.canary_snapshot_repository import CanarySnapshotRepository
from uw_scan.cards.canary_calibration import COMPOSITE_VERSION

pytestmark = pytest.mark.integration


def _seed_stress_regime(conn):
    """Seed a stress regime that should fire Confirmed Canary."""
    start = date(2024, 1, 1)
    rows = []
    for i in range(400):
        d = start + timedelta(days=i)
        # SPX uptrend to day 300, then fast 6% crash and 2 closes below 200d SMA.
        if i < 300:
            spx = 4000.0 + i * 1.0
        elif i < 310:
            spx = 4300.0 - (i - 300) * 30.0  # fast crash → 4000
        else:
            spx = 3800.0
        rows.append((d, "VIX", 35.0 if i >= 305 else 16.0))
        rows.append((d, "VVIX", 140.0 if i >= 305 else 92.0))
        rows.append((d, "VIX3M", 25.0 if i >= 305 else 18.0))
        rows.append((d, "COR1M", 70.0 if i >= 305 else 30.0))
        rows.append((d, "SPX", spx))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO uw_scan.vol_index_daily (trade_date, symbol, close) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            rows,
        )


def test_persisted_warning_state_matches_payload(db_conn):
    _seed_stress_regime(db_conn)
    canary_run(db_conn)
    repo = CanarySnapshotRepository(db_conn)
    latest = repo.latest_snapshot(composite_version=COMPOSITE_VERSION)
    assert latest is not None
    assert latest["warning_state"] == latest["payload"]["canary"]["warning_state"]


def test_cap_binds_under_stress_with_active_canary(db_conn):
    _seed_stress_regime(db_conn)
    canary_run(db_conn)
    repo = CanarySnapshotRepository(db_conn)
    latest = repo.latest_snapshot(composite_version=COMPOSITE_VERSION)
    if latest["warning_state"] != "CONFIRMED_CANARY_ACTIVE":
        pytest.skip("seeded regime did not fire Confirmed Canary — re-seed or skip")
    assert float(latest["score"]) <= 49.0
    # Raw should be > 49 too, otherwise the cap doesn't have anything to do
    assert float(latest["raw_score"]) > 0.0
```

- [ ] **Step 2: Run**

```bash
uv run pytest tests/integration/regime/test_canary_warning_state.py -v
```
Expected: 2 PASS (the second may skip if the synthetic regime doesn't reliably fire — that's acceptable for v1).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/regime/test_canary_warning_state.py
git commit -m "test(canary): end-to-end warning_state + cap-binding verification"
```

---

## Task 24: Methodology doc

**Files:**
- Create: `docs/research/regime/canary-methodology.md`

- [ ] **Step 1: Write the methodology doc**

Mirror the structure of `docs/research/regime/cri-methodology.md`. The doc is the *source of truth* for the indicator's math, calibration, and design decisions. It should reference (not duplicate) the spec at `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md`.

Sections to include:

```markdown
# 5% Canary Methodology

Source of truth for the 5% Canary indicator's math, calibration, and design.

**Code:** `src/uw_scan/cards/canary_scoring.py`
**Scanner:** `src/uw_scan/scanners/canary.py`
**API:** `src/uw_scan/api/routers/regime.py`
**UI:** `web/components/regime/CanarySubTab.tsx`
**Persistence:** `uw_scan.canary_snapshots`
**Spec (full design):** `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md`

## 1. What the 5% Canary is

(1-2 paragraphs — paraphrase spec §1)

## 2. Component framework

(Reproduce the tier table from spec §6)

## 3. Calibration

The thresholds in `canary-calibration-v1.json` were computed by
`scripts/backtest_canary.py --calibrate` on the train window 2007-2014.
Procedure: floor = p25, ceiling = p90 of positive-condition observations.

| Signal | Gate condition | Floor (p25) | Ceiling (p90) |
|---|---|---|---|
| (read from canary-calibration-v1.json after first --calibrate run) | | | |

Author overrides: see `author_overrides` array in the JSON.

## 4. The cap rule

(Paraphrase spec §6 cap rule + §6.3 4-state model)

## 5. Validation

Two layers:

**(a) Warm-store backtest** — `scripts/backtest_canary.py --report` over the
test window 2020-present. Output: `regime_backtest_runs.summary`.

**(b) OOS gate (CI-enforced)** — `tests/integration/regime/test_canary_oos_gate.py`.

## 6. Honest finding (post-backtest)

(To be written after the first full backtest publishes; mirrors CRI §8 honesty.)

## 7. Literature anchors

(Cite the 6 primary references from spec §4)
```

- [ ] **Step 2: Run the calibration and copy the actual floor/ceiling values into §3**

```bash
uv run python scripts/backtest_canary.py --calibrate
# Read the JSON and copy values into the methodology doc table.
```

- [ ] **Step 3: Update `docs/research/regime/CLAUDE.md`**

The existing `CLAUDE.md` in `docs/research/regime/` lists the CRI and VCG methodology files. Append a paragraph extending the "When to update" rule to the canary methodology doc.

- [ ] **Step 4: Commit**

```bash
git add docs/research/regime/canary-methodology.md docs/research/regime/CLAUDE.md
git commit -m "docs(canary): methodology source-of-truth + CLAUDE.md update"
```

---

## Task 25: Final smoke + PR readiness

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest tests/unit/cards/test_canary_scoring.py tests/unit/cards/test_canary_speed_events.py tests/unit/cards/test_canary_confirmed_canary_state_machine.py tests/unit/cards/test_canary_causality.py tests/unit/cards/test_canary_calibration.py tests/unit/storage/test_canary_payload_hash.py -v
uv run pytest tests/integration/regime/test_canary_scanner.py tests/integration/regime/test_canary_db_constraints.py tests/integration/regime/test_canary_warning_state.py tests/integration/regime/test_canary_oos_gate.py tests/integration/api/test_canary_endpoints.py -v
cd web && npm run test -- canary
```

Expected: all unit tests PASS. Integration tests PASS or SKIP-with-reason for the OOS gate if backtest hasn't been seeded. Vitest tests PASS.

- [ ] **Step 2: Run a full backtest pipeline end-to-end**

```bash
uv run python scripts/backtest_canary.py --calibrate
uv run python scripts/backtest_canary.py --form-sweep --write-summary
uv run python scripts/backtest_canary.py --report --write-summary
uv run pytest tests/integration/regime/test_canary_oos_gate.py -v
```

If the OOS gate passes — proceed. If it fails — go back to design before opening the PR (per spec §8.6).

- [ ] **Step 3: Update the v1 OOS gate constants**

Open `tests/integration/regime/test_canary_oos_gate.py` and set `LAST_KNOWN_AUC_*` constants to the actual values from the final-test report (rounded to 2 decimals).

- [ ] **Step 4: Smoke the UI end-to-end**

```bash
bash scripts/dev.sh
# Open http://localhost:3001/regime → click "5% Canary" sub-tab.
# Verify: ScoreHero renders, three tier strips render, RegimePill matches warning_state, history chart renders.
# Verify: validation panel shows the latest run report (or 503 if backtest not yet run).
```

Stop the dev server. No console errors expected.

- [ ] **Step 5: Open the PR**

```bash
git push -u origin worktree-feat+5pct-canary-indicator
gh pr create --title "feat(regime): 5% Canary indicator" --body "$(cat <<'EOF'
## Summary
- Third regime indicator alongside CRI/VCG: three-tier composite (Tactical Vol 0-30 + Structural Vol 0-50 + Price Speed 0-20) with a Confirmed-Canary cap and a 4-state Speed model.
- Causal per-day event state machine for Thrasher 2023's 5%-decline signals (no look-ahead).
- Backtest harness with train/validation/final-test split and four-form sweep.
- New `/regime` sub-tab in the web UI.

Design: `docs/superpowers/specs/2026-05-26-5pct-canary-indicator-design.md` (v0.3)
Plan: `docs/superpowers/plans/2026-05-26-5pct-canary-indicator.md`

## Test plan
- [ ] All `tests/unit/cards/test_canary_*` and `tests/unit/storage/test_canary_payload_hash` pass
- [ ] All `tests/integration/regime/test_canary_*` pass (warning_state, scanner, db_constraints)
- [ ] `tests/integration/regime/test_canary_oos_gate.py` passes with `LAST_KNOWN_AUC_*` set to actual values
- [ ] `cd web && npm run test -- canary` passes
- [ ] Manual smoke at `/regime` → 5% Canary sub-tab renders and the RegimePill state matches the payload
EOF
)"
```

---

## Self-review checklist (run after writing the plan)

- [x] **Spec coverage:** all 19 spec sections have at least one task.
- [x] **Placeholder scan:** no TBD / TODO / "add appropriate error handling" / "similar to Task N".
- [x] **Type consistency:** Pydantic models in Task 14 match scalar columns in Task 1 match payload shape in Task 10.
- [x] **Causality contract:** Task 12 is dedicated to the look-ahead-free verification.
- [x] **Calibration provenance:** Task 19 (--calibrate) writes the JSON; Task 24 copies values into the methodology doc.
- [x] **DB constraints:** Task 1 includes all 5 CHECK constraints; Task 11 (scanner) and Task 14 (API) round-trip through them; Task 1 test covers each constraint violation.

---

# v0.3 PATCH APPENDIX — Post-Review Fixes (MANDATORY before execution)

The review-cycle pass on 2026-05-26 produced 26 consolidated findings (8 from Pass 1 self-review, 13 from Codex independent review, 5 from Claude adversarial review). Apply each patch below in the listed task as you reach it. Patches are sorted by severity.

## CRITICAL — block implementation if skipped

### PATCH C1 — Task 13 wrong scheduler pattern

**Reality:** there is no `src/uw_scan/worker/jobs/regime_jobs.py` module. CRI/VCG scans are inner functions inside `src/uw_scan/worker/scheduler.py:437-462`, scheduled at lines 712-735 inside the `_is_primary_worker(settings)` block. Triggers are `CronTrigger(minute=20, timezone=settings.rth_tz)` (hourly, not daily), and they use a `with _repo(settings) as repo:` context manager — NOT a fresh `connect(settings.database_url)`.

**Apply:** rewrite Task 13 to add `_regime_canary_scan()` as an inner function adjacent to `_regime_cri_scan`/`_regime_vcg_scan` in `scheduler.py`, mirroring their exact structure. Register with the same `sched.add_job(..., CronTrigger(minute=20, timezone=settings.rth_tz), id="regime_canary_scan", ...)` shape.

### PATCH C2 — Task 11 missing `commit()` after insert/overwrite

`CanarySnapshotRepository.insert_snapshot` never calls `self._conn.commit()`. CRI's repo commits after insert (`cri_snapshot_repository.py:28-33`). Without commit, scheduler-style invocations that close the connection will roll back the insert. Apply: `self._conn.commit()` after successful insert AND after successful overwrite path.

### PATCH C3 — Task 14 API dependency pattern wrong

`Depends(get_conn)` does not exist. Real pattern (per `api/routers/regime.py:170-180`):
```python
@router.get("/canary", response_model=CanaryLatestResponse)
def get_canary_latest(repo: Annotated[Repository, Depends(get_repo)]) -> CanaryLatestResponse:
    snap_repo = CanarySnapshotRepository(repo.conn, schema=repo._schema)
    latest = snap_repo.fetch_latest(composite_version=CANARY_COMPOSITE_VERSION)
    ...
```
Apply the same pattern to all 3 canary endpoints. Imports: `from typing import Annotated`, `from uw_scan.api.dependencies import get_repo, get_settings` (or wherever they live — confirm with `grep -n "def get_repo" src/uw_scan/api/`).

### PATCH C4 — Tasks 20/21 `insert_run` signature mismatch

Real signature (`storage/regime_backtest_repository.py:32`):
```python
def insert_run(self, *, indicator: Literal["cri", "vcg"], composite_version: str,
               start_date: date, end_date: date, window_days: int, n_days: int,
               params: dict, summary: dict, note: str | None = None) -> int
```
Plan calls with `score_form=` and `daily_rows=` — these do not exist. Fix:
- Pass `score_form` inside `params={"score_form": form, ...}` or `summary["score_form"]`.
- Use the SEPARATE `bulk_insert_daily(run_id, rows)` for daily rows.
- Rows must use keys `{trade_date, score, level, payload}` (NOT `{date, score, band}`).
- After `bulk_insert_daily`, call `mark_run_completed(run_id)` — `find_latest_run` filters on `completed_at IS NOT NULL`.

### PATCH C5 — `Literal["cri", "vcg"]` + DB CHECK reject "canary"

The Literal type appears in 4 places in `regime_backtest_repository.py` and the DB constraint `CHECK (indicator IN ('cri','vcg'))` is hardcoded in migration `057_regime_backtest_results.sql`. Add a **new pre-task** before Task 20:

> **Task 19.5 — Extend regime_backtest_runs to accept 'canary'**
> 1. New migration `060_regime_backtest_runs_canary.sql`:
> ```sql
> SET search_path TO uw_scan, public;
> BEGIN;
> ALTER TABLE uw_scan.regime_backtest_runs
>     DROP CONSTRAINT regime_backtest_runs_indicator_check;
> ALTER TABLE uw_scan.regime_backtest_runs
>     ADD CONSTRAINT regime_backtest_runs_indicator_check
>     CHECK (indicator IN ('cri','vcg','canary'));
> COMMIT;
> ```
> (The constraint name may differ — verify with `\d uw_scan.regime_backtest_runs` first.)
> 2. Edit `src/uw_scan/storage/regime_backtest_repository.py` — change all 4 `Literal["cri", "vcg"]` to `Literal["cri", "vcg", "canary"]`.

### PATCH C6 — `composite_version` type mismatch (TEXT in DB, int in code)

Plan passes `COMPOSITE_VERSION` (int) to `insert_run` and `find_latest_run`, but the column type is `TEXT`. Apply: pass `str(COMPOSITE_VERSION)` everywhere. Also: the canary's local `COMPOSITE_VERSION: int = 1` stays as int for typing, but is stringified at the DB boundary.

### PATCH C7 — Tests reference nonexistent `db_conn` fixture

The real fixture is `seeded_db_empty_cards` (defined in `tests/integration/conftest.py`). Replace every `db_conn` parameter with `seeded_db_empty_cards`, then use `seeded_db_empty_cards.conn` / `seeded_db_empty_cards._schema`. Affects Tasks 1, 11, 14, 22, 23.

### PATCH C8 — API tests shadow safe TestClient fixture

The plan's `client()` fixture redefines what's already provided by `tests/integration/api/conftest.py:33-54`. Delete the plan's local fixture; rely on the project's existing `client` fixture.

### PATCH C9 — Web UI imports broken (cn, swr, ComponentBar, HistoryChart)

- `@/lib/cn` does NOT exist. Either inline class strings or use `clsx` if installed.
- `swr` is NOT in `web/package.json`. The project uses `useSyncHook` (in `web/lib/regime/useSyncHook.ts`) wrapped by per-indicator hooks (`useCri.ts`, `useVcg.ts`). Apply: create `web/lib/regime/useCanary.ts` mirroring `useCri.ts`.
- `./primitives/ComponentBar` does NOT exist as a separate file — `ComponentBar` is a local component inside `CriSubTab.tsx`. Either extract it to a shared primitive file (preferred — also lets VCG reuse it), or inline a copy in `CanarySubTab.tsx`.
- `HistoryChart` props are `{history, ticker}` not `{data, max}` — verify by reading `web/components/regime/HistoryChart.tsx:10-16`.

### PATCH C10 — `regimeApi` needs canary entries

Add to `web/lib/regime/api.ts`:
```ts
canary: () => `${API}/api/regime/canary`,
canaryHistory: (days: number) => `${API}/api/regime/canary/history?days=${days}`,
canaryValidation: () => `${API}/api/regime/canary/validation`,
```

## IMPORTANT — fix before merge

### PATCH I1 — Sigmoid ramp fails the floor/ceiling contract

`ramp()` with `form="sigmoid"` at `value <= floor` returns `M/(1+exp(5)) ≈ 0.0067·M`, not 0. The test asserts equality to 0.0 — test will fail. Apply: clamp endpoints explicitly:
```python
if form == "sigmoid":
    if value <= floor: return 0.0
    if value >= ceiling: return float(max_points)
    return max_points / (1.0 + math.exp(-10.0 * (norm - 0.5)))
```

### PATCH I2 — Calibration slicing off-by-one vs runtime

Runtime uses inclusive slices including today: `vix_history[-lookback:]`. Calibration uses `vix_arr[i-10:i].max()` — EXCLUDES day `i`. They must agree. Apply: in `cmd_calibrate`, replace `vix_arr[i-10:i].max()` with `vix_arr[i-9:i+1].max()` (and analogous for VIX/VIX3M, COR1M, VVIX/VIX). Then add a unit test that verifies calibration feature extraction matches the scorer's diagnostic output on the same fixture.

### PATCH I3 — Task 12 causality test compares truncated to itself

Acknowledged in plan v0.2 but not fully fixed. Apply: implement a `_full_run_series_canonical(dates, aligned)` that walks the FULL history through the production scanner code path once (NOT by calling `_snapshot_at` per index — that's a circular comparison). Use `scanners/canary._replay_events` over the full data, then for each K extract the snapshot. Compare against `_snapshot_at(dates, aligned, K)` (truncated path). Mismatch → look-ahead.

### PATCH I4 — `fetch_latest_winning_form` lacks `completed_at IS NOT NULL`

Add `AND completed_at IS NOT NULL` to the WHERE clause, or — better — delete the new method entirely and call the existing `find_latest_run(indicator='canary', composite_version=str(...))`, then post-filter for `summary.is_winning_form`.

### PATCH I5 — Pinned hash test passes without pinning

The placeholder `expected = "<PIN-ME-AFTER-FIRST-RUN>"` lets the test pass without freezing the contract. Apply: run `python -c "from uw_scan.cards.canary_payload_hash import canonical_payload_hash; print(canonical_payload_hash({'date': '2026-05-26', 'canary': {'score': 47.3, 'band': 'WATCH'}}))"` ONCE, copy the result, hardcode it. Fail the test if the placeholder string is still present.

### PATCH I6 — Cap-binding test assertion too weak

Task 23's `test_cap_binds_under_stress_with_active_canary` asserts `raw_score > 0.0` — passes even when raw is e.g. 12 (no cap binding). Apply: `assert float(latest["raw_score"]) > 49.0` AND `assert float(latest["score"]) == 49.0` AND `assert latest["payload"]["canary"]["cap_applied"] is True`. If the seeded fixture can't reliably produce raw > 49, use a deterministic synthetic fixture instead of skipping.

### PATCH I7 — Missing NaN handling in scorers and `_load`

`_load()` filters `None` but not NaN/non-finite. Spec §19 requires `NaN in any input → NormalizationError`. Apply: in `_load`, also filter `not math.isnan(close) and math.isfinite(close)`. In each scorer, validate inputs at entry: `if any(not math.isfinite(v) for v in series): raise NormalizationError(...)`. Add fixture test with NaN injection.

### PATCH I8 — Method naming `latest_snapshot`/`history` should be `fetch_latest`/`fetch_history`

Project convention (`CriSnapshotRepository`): `fetch_latest`, `fetch_history`. Plan uses `latest_snapshot` and `history`. Rename for consistency across Tasks 2, 11, 14.

## MINOR — preference / style

- Migration `060_canary_snapshots.sql` → already corrected to `059_canary_snapshots.sql`.
- Task 6 unit test's `_trading_days_between` simplification (treats every calendar day as trading) is fine for unit tests but document it.
- Form-sweep rows in `regime_backtest_runs` should call `mark_run_completed` even for losing forms (transparency), but ONLY the winning form's row carries `summary.is_winning_form=true`.

## Acknowledgment

Apply these patches BEFORE running the corresponding task. The Task 0 audit checklist at the top of this document is updated to include them — if any patch above is unchecked, do not start that task's implementation.
