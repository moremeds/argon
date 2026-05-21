# Vanna & Charm — Market Structure sub-tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `VANNA` and `CHARM` sub-tabs inside the per-ticker Market Structure tab, mirroring the UnusualWhales reference layout (headline narrative + 4 tiles + expiry dropdown + Net curve + Call/Put split curve). The existing `GexProfileChart` moves into a new `GEX` sub-tab so the three become peers. All derived summary values are computed in Python and persisted to a new `exposures_summary` table per project rule.

**Architecture:** Raw per-(expiry, strike) exposures already land in `exposures_by_expiry_strike` from the daily cockpit snapshot. We add a pure deriver module (`cards/exposures.py`), persist its output into a new `exposures_summary` table (migration 051), surface both raw rows and summary rows on `SingleStockReport`, and render the panels as hand-rolled SVG line charts using the existing `lib/svgChart.ts` helpers. Sub-tab switching is a small client component (`GreekSubTabs`) embedded inside the still-RSC `MarketStructureTab`.

**Tech Stack:** Python 3.13 + `uv`, Pydantic v2, psycopg 3, FastAPI, APScheduler, Postgres 16. Next.js 16 + React 19 (RSC + client islands), TypeScript strict, vitest, Playwright. Spec lives at `docs/superpowers/specs/2026-05-21-vanna-charm-market-structure-design.md`.

---

## Slice 1 — Models + migration

### Task 1.1: Add `StrikeExposureRow` and `ExposuresSummaryRow` Pydantic models

**Files:**
- Modify: `src/uw_scan/models/scanner.py` (append models near `StrikeGexBucket` at line ~151)
- Modify: `src/uw_scan/models/__init__.py` (add to `__all__` + `from .scanner import ...`)
- Test: `tests/unit/test_models_exports.py` (existing — assert new names exported)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_models_exports.py` (create if absent; otherwise extend the existing test in that file):

```python
def test_new_exposure_models_exported():
    from uw_scan import models

    assert "StrikeExposureRow" in models.__all__
    assert "ExposuresSummaryRow" in models.__all__
    # _preserve_public_module rewrites __module__ to "uw_scan.models" for
    # contract identity (see src/uw_scan/models/_base.py). Asserting the
    # public module is what protects the OpenAPI component name from
    # accidentally drifting back to the implementation module.
    assert models.StrikeExposureRow.__module__ == "uw_scan.models"
    assert models.ExposuresSummaryRow.__module__ == "uw_scan.models"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_models_exports.py::test_new_exposure_models_exported -v
```

Expected: FAIL — `AttributeError: module 'uw_scan.models' has no attribute 'StrikeExposureRow'`.

- [ ] **Step 3: Add the two models to `src/uw_scan/models/scanner.py`**

Insert right after `StrikeGexBucket` (before `GexLevel`):

```python
class StrikeExposureRow(_UwBase):
    """One per-(expiry, strike) raw row from exposures_by_expiry_strike,
    carrying the call/put split for vanna and charm so the FE can render
    Net + Call/Put curves without an extra fetch."""

    strike: Decimal
    expiry: _date
    dte: int | None = None
    call_vanna: Decimal | None = None
    put_vanna: Decimal | None = None
    call_charm: Decimal | None = None
    put_charm: Decimal | None = None


class ExposuresSummaryRow(_UwBase):
    """Per-(expiry) derived summary used to drive the Vanna/Charm sub-tab
    headline narrative + 4 tiles. Computed by cards/exposures.py and
    persisted to uw_scan.exposures_summary."""

    expiry: _date
    dte: int | None = None
    spot: Decimal | None = None
    # Vanna ---
    net_vanna: Decimal | None = None
    top_vanna_strike: Decimal | None = None
    top_vanna_value: Decimal | None = None
    delta_shock_1pt_iv: Decimal | None = None
    vanna_regime: str | None = None
    vanna_flip: Decimal | None = None
    vanna_headline: str | None = None
    vanna_subtitle: str | None = None
    # Charm ---
    net_charm: Decimal | None = None
    charm_pin_strike: Decimal | None = None
    charm_above_sum: Decimal | None = None
    charm_below_sum: Decimal | None = None
    charm_imbalance_pct: Decimal | None = None
    charm_signal_quality: str | None = None
    charm_flip: Decimal | None = None
    charm_headline: str | None = None
    charm_subtitle: str | None = None
```

Add both to the `_preserve_public_module(...)` call at the bottom of the file.

- [ ] **Step 4: Re-export from `src/uw_scan/models/__init__.py`**

In the existing `from .scanner import (...)` block, add `StrikeExposureRow` and `ExposuresSummaryRow`. Also add both names to `__all__` (keep alphabetical/grouped order consistent with neighbours).

- [ ] **Step 5: Verify test passes + no other tests broken**

```bash
uv run pytest tests/unit/test_models_exports.py -v
uv run pytest tests/unit -q
```

Expected: PASS. No regressions.

- [ ] **Step 6: Commit (do not push)**

```bash
git add src/uw_scan/models/scanner.py src/uw_scan/models/__init__.py tests/unit/test_models_exports.py
git commit -m "feat(models): add StrikeExposureRow and ExposuresSummaryRow contracts"
```

---

### Task 1.2: Add migration `051_exposures_summary.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/051_exposures_summary.sql`
- Test: `tests/integration/storage/test_exposures_summary_migration.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/storage/test_exposures_summary_migration.py`:

```python
"""Smoke test for migration 051 — table + PK + index exist; re-running migrate.sh is a no-op."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from uw_scan.storage.repository import Repository


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_exposures_summary_table_created(seeded_db_empty_cards: Repository):
    """conftest's _reset_and_migrate already ran migrate.sh; assert the table + columns exist."""
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute("SELECT to_regclass('uw_scan.exposures_summary')")
        assert cur.fetchone()[0] is not None

        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'uw_scan' AND table_name = 'exposures_summary'
            """
        )
        cols = {row[0] for row in cur.fetchall()}
        for c in (
            "run_id", "ticker", "expiry", "market_date", "dte", "spot",
            "net_vanna", "top_vanna_strike", "top_vanna_value",
            "delta_shock_1pt_iv", "vanna_regime", "vanna_flip",
            "vanna_headline", "vanna_subtitle",
            "net_charm", "charm_pin_strike", "charm_above_sum",
            "charm_below_sum", "charm_imbalance_pct",
            "charm_signal_quality", "charm_flip",
            "charm_headline", "charm_subtitle",
            "computed_at",
        ):
            assert c in cols, f"missing column: {c}"


def test_migration_is_idempotent(seeded_db_empty_cards: Repository):
    """Re-running scripts/migrate.sh on the already-migrated DB must be a no-op."""
    repo = seeded_db_empty_cards
    test_db = os.environ["UW_SCAN_TEST_DB_NAME"]
    env = {**os.environ, "UW_SCAN_DB_NAME": test_db}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True, cwd=REPO_ROOT, env=env,
    )
    # Table still empty, schema still present.
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.exposures_summary")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/storage/test_exposures_summary_migration.py -v
```

Expected: FAIL — `to_regclass` returns NULL because the table doesn't exist.

- [ ] **Step 3: Create the migration file**

Create `src/uw_scan/storage/migrations/051_exposures_summary.sql`:

```sql
-- 051_exposures_summary.sql
-- Per-(expiry) derived summary used by the Vanna/Charm sub-tabs.
-- One row per (run_id, ticker, expiry) — primary key. Idempotent.
--
-- run_id is BIGINT with FK ON DELETE CASCADE to match the convention used by
-- every other run-keyed table in migration 001 (scan_runs.run_id is BIGSERIAL;
-- INTEGER would overflow on long-running deployments and an orphan summary
-- after scan-runs cleanup would be a data-integrity papercut).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.exposures_summary (
    run_id               BIGINT  NOT NULL
                                 REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
    ticker               TEXT    NOT NULL,
    expiry               DATE    NOT NULL,
    market_date          DATE    NOT NULL,
    dte                  INTEGER,
    spot                 NUMERIC,

    -- Vanna ---
    net_vanna            NUMERIC,
    top_vanna_strike     NUMERIC,
    top_vanna_value      NUMERIC,
    delta_shock_1pt_iv   NUMERIC,
    vanna_regime         TEXT,
    vanna_flip           NUMERIC,
    vanna_headline       TEXT,
    vanna_subtitle       TEXT,

    -- Charm ---
    net_charm            NUMERIC,
    charm_pin_strike     NUMERIC,
    charm_above_sum      NUMERIC,
    charm_below_sum      NUMERIC,
    charm_imbalance_pct  NUMERIC,
    charm_signal_quality TEXT,
    charm_flip           NUMERIC,
    charm_headline       TEXT,
    charm_subtitle       TEXT,

    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (run_id, ticker, expiry)
);

CREATE INDEX IF NOT EXISTS exposures_summary_ticker_date_idx
    ON uw_scan.exposures_summary (ticker, market_date);
```

- [ ] **Step 4: Apply migration locally and run tests**

```bash
bash scripts/migrate.sh
uv run pytest tests/integration/storage/test_exposures_summary_migration.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/migrations/051_exposures_summary.sql tests/integration/storage/test_exposures_summary_migration.py
git commit -m "feat(storage): add exposures_summary table (migration 051)"
```

---

## Slice 2 — Derivers + unit tests

> ⚠️ **Before writing the derivers — verify the UW vanna/charm sign and unit convention.** The deriver code below assumes:
>
> 1. UW per-strike `call_vanna` is signed such that `net_vanna > 0` means **dealers are net Long Vanna** — i.e., if IV rises, dealers gain Δ and sell stock to rehedge (the "procyclical" regime). The UW reference UI uses the same sign convention.
> 2. UW vanna is `dΔ per 1.0 of IV (decimal)`, so a 1-point IV move = `vanna × 0.01`. Other endpoints expose "per-one-percent-move" pre-multiplied fields; we do NOT use those.
>
> Both assumptions are MEDIUM-CONFIDENCE pending live verification. Before merging Slice 4 (when the field surfaces in the UI), do one of:
>
> - **Sanity check from sample payloads.** `grep -l vanna docs/uw-samples/*.json` to find a real `/greek-exposure` response; verify that for a ticker with known dealer positioning (e.g., SPX in a high-skew window), the sign of `call_vanna + put_vanna` matches the UW UI's "Long/Short Vanna" labeling for the same expiry. If it doesn't, either the sign needs flipping in `vanna_regime` or the headline narratives need reversing.
> - **Direct comparison.** Pull `/greek-exposure/expiry/strike` for TSLA on a recent day and compare the numerical `net_vanna` from `build_summary_rows` against the value the UW UI shows under "Net Vanna" — if scale differs by ~100×, the `ONE_VOL_POINT` factor is wrong (probably should be `1.0`, not `0.01`).
>
> Until verified, label the headline conservatively in `vanna_narrative`: use "Long Vanna positioning" rather than "Long Vanna — IV spikes pressure stock lower via dealer selling" so the directional claim isn't load-bearing on an unverified convention. (Plan keeps the descriptive text; if verification fails, just edit the narrative strings — no logic change needed.)

### Task 2.1: Create `cards/exposures.py` with vanna derivers + tests

**Files:**
- Create: `src/uw_scan/cards/exposures.py`
- Create: `tests/unit/cards/test_exposures_vanna.py`

- [ ] **Step 1: Write the failing tests for `net_vanna`, `top_vanna_strike`, `delta_shock_1pt_iv`**

Create `tests/unit/cards/test_exposures_vanna.py`:

```python
"""Vanna derivers — pure functions over GreekExposureRow lists."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import (
    delta_shock_1pt_iv,
    net_vanna,
    top_vanna_strike,
    vanna_flip,
    vanna_narrative,
    vanna_regime,
)
from uw_scan.models import GreekExposureRow


def _r(strike: str, expiry: str, call_v: str | None, put_v: str | None) -> GreekExposureRow:
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        call_vanna=Decimal(call_v) if call_v is not None else None,
        put_vanna=Decimal(put_v) if put_v is not None else None,
    )


def test_net_vanna_sums_call_plus_put_across_rows():
    rows = [
        _r("100", "2026-05-30", "100", "-30"),
        _r("110", "2026-05-30", "200", "-40"),
    ]
    assert net_vanna(rows) == Decimal("230")  # 100-30+200-40


def test_net_vanna_handles_nulls_silently():
    rows = [
        _r("100", "2026-05-30", "100", None),
        _r("110", "2026-05-30", None, "-40"),
    ]
    assert net_vanna(rows) == Decimal("60")


def test_net_vanna_empty_returns_none():
    assert net_vanna([]) is None


def test_top_vanna_strike_picks_max_absolute_per_strike():
    rows = [
        _r("100", "2026-05-30", "50", "-10"),     # net 40
        _r("110", "2026-05-30", "-200", "30"),    # net -170
        _r("120", "2026-05-30", "80", "20"),      # net 100
    ]
    strike, value = top_vanna_strike(rows)
    assert strike == Decimal("110")
    assert value == Decimal("-170")


def test_top_vanna_strike_empty_returns_none():
    assert top_vanna_strike([]) is None


def test_delta_shock_1pt_iv_is_net_vanna_times_001():
    """UW vanna is dDelta per unit of vol (decimal); 1pt IV = 0.01."""
    rows = [_r("100", "2026-05-30", "10000", "-2000")]  # net 8000
    assert delta_shock_1pt_iv(rows) == Decimal("80.00")  # 8000 * 0.01


def test_vanna_regime_procyclical_when_net_positive():
    assert vanna_regime(Decimal("1500000")) == "procyclical"


def test_vanna_regime_countercyclical_when_net_negative():
    assert vanna_regime(Decimal("-1500000")) == "countercyclical"


def test_vanna_regime_neutral_below_threshold():
    assert vanna_regime(Decimal("500")) == "neutral"
    assert vanna_regime(None) == "neutral"


def test_vanna_flip_picks_first_cumulative_sign_change():
    rows = [
        _r("90",  "2026-05-30", "-100", "0"),   # cum -100
        _r("100", "2026-05-30", "-50",  "0"),   # cum -150
        _r("110", "2026-05-30", "200",  "0"),   # cum  50  ← flip here
        _r("120", "2026-05-30", "50",   "0"),
    ]
    assert vanna_flip(rows, spot=Decimal("100")) == Decimal("110")


def test_vanna_flip_no_sign_change_returns_none():
    rows = [
        _r("90",  "2026-05-30", "10", "0"),
        _r("100", "2026-05-30", "20", "0"),
    ]
    assert vanna_flip(rows, spot=Decimal("95")) is None


def test_vanna_flip_picks_lowest_ge_spot_when_multiple():
    """Spec rule: lowest sign-flip ≥ spot; fall back to lowest overall otherwise."""
    rows = [
        _r("80",  "2026-05-30", "-100", "0"),   # cum -100
        _r("90",  "2026-05-30", "200",  "0"),   # cum  100  ← flip 1 (below spot 100)
        _r("100", "2026-05-30", "-300", "0"),   # cum -200  ← flip 2 (at spot)
        _r("110", "2026-05-30", "400",  "0"),   # cum  200  ← flip 3 (above spot)
    ]
    assert vanna_flip(rows, spot=Decimal("100")) == Decimal("100")


def test_vanna_flip_falls_back_to_lowest_when_no_flip_above_spot():
    rows = [
        _r("80",  "2026-05-30", "-100", "0"),
        _r("90",  "2026-05-30", "200",  "0"),   # cum 100  ← flip below spot
    ]
    assert vanna_flip(rows, spot=Decimal("150")) == Decimal("90")


def test_vanna_narrative_procyclical():
    headline, subtitle = vanna_narrative(Decimal("1300000"), "procyclical")
    assert "Long Vanna" in headline
    assert "IV" in subtitle


def test_vanna_narrative_countercyclical():
    headline, subtitle = vanna_narrative(Decimal("-800000"), "countercyclical")
    assert "Short Vanna" in headline
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/cards/test_exposures_vanna.py -v
```

Expected: FAIL — `ImportError: cannot import name 'net_vanna' from 'uw_scan.cards.exposures'`.

- [ ] **Step 3: Create `src/uw_scan/cards/exposures.py` with vanna derivers**

```python
"""Per-(expiry) derivations on raw greek-exposure rows.

Pure functions: take ``list[GreekExposureRow]`` (already filtered to one expiry by
the caller) and return derived summary values. No DB access — the assembler in
``reports/`` owns the I/O, mirroring the ``cards/gex.py`` pattern.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from decimal import Decimal

from uw_scan.models import ExposuresSummaryRow, GreekExposureRow

log = logging.getLogger(__name__)


# --- thresholds (tunable; move to config if/when calibrated per-ticker) -----

NEUTRAL_VANNA_THRESHOLD = Decimal("1000")
"""|net_vanna| below this is reported as 'neutral' regime."""

NEUTRAL_CHARM_THRESHOLD = Decimal("1000")
"""|net_charm| below this is reported as 'flat' / 'mixed' signal quality."""

ONE_VOL_POINT = Decimal("0.01")
"""UW vanna is dDelta per 1.0 of IV (decimal). 1pt IV move = 0.01."""


# --- vanna helpers ---------------------------------------------------------

def _per_strike_net_vanna(rows: list[GreekExposureRow]) -> dict[Decimal, Decimal]:
    acc: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in rows:
        if r.call_vanna is not None:
            acc[r.strike] += r.call_vanna
        if r.put_vanna is not None:
            acc[r.strike] += r.put_vanna
    return dict(acc)


def net_vanna(rows: list[GreekExposureRow]) -> Decimal | None:
    """Σ (call_vanna + put_vanna) across every row. None when no inputs."""
    if not rows:
        return None
    total = Decimal("0")
    any_present = False
    for r in rows:
        if r.call_vanna is not None:
            total += r.call_vanna
            any_present = True
        if r.put_vanna is not None:
            total += r.put_vanna
            any_present = True
    return total if any_present else None


def top_vanna_strike(
    rows: list[GreekExposureRow],
) -> tuple[Decimal, Decimal] | None:
    """The (strike, net_vanna) pair with the largest |net_vanna|."""
    per = _per_strike_net_vanna(rows)
    if not per:
        return None
    strike = max(per.items(), key=lambda kv: abs(kv[1]))[0]
    return strike, per[strike]


def delta_shock_1pt_iv(rows: list[GreekExposureRow]) -> Decimal | None:
    """Net Δ dealers must hedge if IV rises 1 vol-point."""
    nv = net_vanna(rows)
    if nv is None:
        return None
    return nv * ONE_VOL_POINT


def vanna_regime(net_vanna_value: Decimal | None) -> str:
    """`procyclical` / `countercyclical` / `neutral`."""
    if net_vanna_value is None:
        return "neutral"
    if abs(net_vanna_value) < NEUTRAL_VANNA_THRESHOLD:
        return "neutral"
    return "procyclical" if net_vanna_value > 0 else "countercyclical"


def vanna_flip(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> Decimal | None:
    """Strike where running cumulative net_vanna changes sign.

    Iterates strikes ascending and collects EVERY sign-flip strike. The spec
    (docs/superpowers/specs/.../design.md §"Backend → derivers") asks for the
    lowest sign-flip ≥ spot; fall back to the absolute lowest flip when no
    flip is at/above spot (or when spot is unknown).
    """
    if not rows:
        return None
    per = _per_strike_net_vanna(rows)
    if not per:
        return None
    flips: list[Decimal] = []
    cum = Decimal("0")
    prev_sign = 0
    for strike, val in sorted(per.items(), key=lambda kv: kv[0]):
        cum += val
        sign = (cum > 0) - (cum < 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            flips.append(strike)
        if sign != 0:
            prev_sign = sign
    if not flips:
        return None
    if spot is None:
        return flips[0]
    above = [s for s in flips if s >= spot]
    return above[0] if above else flips[0]


def vanna_narrative(
    net_vanna_value: Decimal | None,
    regime: str,
) -> tuple[str, str]:
    """Deterministic headline + subtitle keyed off net sign and regime."""
    if net_vanna_value is None or regime == "neutral":
        return (
            "Neutral Vanna — IV moves have limited dealer-Δ impact",
            "Net vanna positioning is balanced; dealer hedging is not a strong driver.",
        )
    if net_vanna_value > 0:
        return (
            "Long Vanna — IV spikes pressure stock lower via dealer selling",
            "If IV rises, dealers gain delta and will likely sell stock to rehedge — a headwind during vol spikes.",
        )
    return (
        "Short Vanna — IV spikes support stock via dealer buying",
        "If IV rises, dealers lose delta and will likely buy stock to rehedge — a tailwind during vol spikes.",
    )
```

- [ ] **Step 4: Run vanna tests to verify they pass**

```bash
uv run pytest tests/unit/cards/test_exposures_vanna.py -v
```

Expected: PASS for all 12 cases.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/exposures.py tests/unit/cards/test_exposures_vanna.py
git commit -m "feat(cards): add vanna derivers (net, top strike, flip, regime, narrative)"
```

---

### Task 2.2: Add charm derivers + tests

**Files:**
- Modify: `src/uw_scan/cards/exposures.py` (append)
- Create: `tests/unit/cards/test_exposures_charm.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/cards/test_exposures_charm.py`:

```python
"""Charm derivers — pure functions over GreekExposureRow lists."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import (
    charm_flip,
    charm_imbalance,
    charm_narrative,
    charm_pin_strike,
    charm_signal_quality,
    net_charm,
)
from uw_scan.models import GreekExposureRow


def _r(strike: str, expiry: str, call_c: str | None, put_c: str | None) -> GreekExposureRow:
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        call_charm=Decimal(call_c) if call_c is not None else None,
        put_charm=Decimal(put_c) if put_c is not None else None,
    )


def test_net_charm_sums_call_plus_put():
    rows = [
        _r("100", "2026-05-30", "-1000000", "200000"),
        _r("110", "2026-05-30", "-500000",  "100000"),
    ]
    assert net_charm(rows) == Decimal("-1200000")


def test_net_charm_empty_returns_none():
    assert net_charm([]) is None


def test_charm_pin_strike_picks_max_abs():
    rows = [
        _r("100", "2026-05-30", "100", "200"),     # 300
        _r("110", "2026-05-30", "-5000", "-2000"),  # -7000 (pin)
        _r("120", "2026-05-30", "500", "-100"),    # 400
    ]
    assert charm_pin_strike(rows) == Decimal("110")


def test_charm_pin_strike_empty_returns_none():
    assert charm_pin_strike([]) is None


def test_charm_imbalance_splits_above_and_below_spot():
    rows = [
        _r("90",  "2026-05-30", "1000", "500"),    # below — sum 1500
        _r("100", "2026-05-30", "200",  "100"),    # at spot — skip (>= spot rule)
        _r("110", "2026-05-30", "-3000", "-2000"),  # above — sum -5000
        _r("120", "2026-05-30", "-1000", "-500"),  # above — sum -1500
    ]
    above, below, imb_pct = charm_imbalance(rows, spot=Decimal("100"))
    assert above == Decimal("-6500")
    assert below == Decimal("1500")
    # imbalance % = |above - below| / (|above| + |below|)
    assert imb_pct == Decimal("8000") / Decimal("8000")  # 1.0 (fully one-sided after sign)


def test_charm_signal_quality_aligned_when_same_sign():
    # live sell + positioning sell-heavy → aligned
    assert (
        charm_signal_quality(live=Decimal("-100"), positioning=Decimal("-50"))
        == "aligned"
    )


def test_charm_signal_quality_mixed_when_opposing_signs():
    assert (
        charm_signal_quality(live=Decimal("-100"), positioning=Decimal("50"))
        == "mixed"
    )


def test_charm_signal_quality_weak_when_either_near_zero():
    assert (
        charm_signal_quality(live=Decimal("0"), positioning=Decimal("-50"))
        == "weak"
    )


def test_charm_flip_picks_cumulative_sign_change():
    rows = [
        _r("90",  "2026-05-30", "1000", "500"),     # cum 1500
        _r("100", "2026-05-30", "200",  "100"),     # cum 1800
        _r("110", "2026-05-30", "-3000", "-1500"),  # cum -2700  ← flip
        _r("120", "2026-05-30", "-100", "-50"),
    ]
    assert charm_flip(rows, spot=Decimal("100")) == Decimal("110")


def test_charm_narrative_sell_pressure_when_negative():
    headline, subtitle = charm_narrative(
        net_charm_value=Decimal("-15000000"),
        signal_quality="aligned",
    )
    assert "SELL" in headline


def test_charm_narrative_buy_pressure_when_positive():
    headline, _ = charm_narrative(
        net_charm_value=Decimal("8000000"),
        signal_quality="aligned",
    )
    assert "BUY" in headline


def test_charm_narrative_neutral_when_weak():
    headline, _ = charm_narrative(
        net_charm_value=Decimal("0"),
        signal_quality="weak",
    )
    assert "Limited" in headline or "Neutral" in headline
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/cards/test_exposures_charm.py -v
```

Expected: FAIL — names not defined in `cards.exposures`.

- [ ] **Step 3: Append charm derivers to `src/uw_scan/cards/exposures.py`**

```python
# --- charm helpers ---------------------------------------------------------

def _per_strike_net_charm(rows: list[GreekExposureRow]) -> dict[Decimal, Decimal]:
    acc: dict[Decimal, Decimal] = defaultdict(lambda: Decimal("0"))
    for r in rows:
        if r.call_charm is not None:
            acc[r.strike] += r.call_charm
        if r.put_charm is not None:
            acc[r.strike] += r.put_charm
    return dict(acc)


def net_charm(rows: list[GreekExposureRow]) -> Decimal | None:
    if not rows:
        return None
    total = Decimal("0")
    any_present = False
    for r in rows:
        if r.call_charm is not None:
            total += r.call_charm
            any_present = True
        if r.put_charm is not None:
            total += r.put_charm
            any_present = True
    return total if any_present else None


def charm_pin_strike(rows: list[GreekExposureRow]) -> Decimal | None:
    per = _per_strike_net_charm(rows)
    if not per:
        return None
    return max(per.items(), key=lambda kv: abs(kv[1]))[0]


def charm_imbalance(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal | None]:
    """(above_sum, below_sum, imbalance_pct).

    above_sum = Σ net_charm for strikes > spot.
    below_sum = Σ net_charm for strikes < spot.
    imbalance_pct = |above - below| / (|above| + |below|) — 0.0 balanced, 1.0 fully one-sided.
    """
    if spot is None:
        return Decimal("0"), Decimal("0"), None
    above = Decimal("0")
    below = Decimal("0")
    per = _per_strike_net_charm(rows)
    for strike, val in per.items():
        if strike > spot:
            above += val
        elif strike < spot:
            below += val
    denom = abs(above) + abs(below)
    imb = (abs(above - below) / denom) if denom != 0 else None
    return above, below, imb


def charm_signal_quality(live: Decimal | None, positioning: Decimal | None) -> str:
    """`aligned` when same sign + nonzero; `mixed` opposing; `weak` either near 0."""
    if live is None or positioning is None:
        return "weak"
    if abs(live) < NEUTRAL_CHARM_THRESHOLD or abs(positioning) < NEUTRAL_CHARM_THRESHOLD:
        return "weak"
    same_sign = (live > 0 and positioning > 0) or (live < 0 and positioning < 0)
    return "aligned" if same_sign else "mixed"


def charm_flip(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> Decimal | None:
    """Same selection rule as vanna_flip: lowest sign-flip ≥ spot, fallback to lowest."""
    if not rows:
        return None
    per = _per_strike_net_charm(rows)
    if not per:
        return None
    flips: list[Decimal] = []
    cum = Decimal("0")
    prev_sign = 0
    for strike, val in sorted(per.items(), key=lambda kv: kv[0]):
        cum += val
        sign = (cum > 0) - (cum < 0)
        if prev_sign != 0 and sign != 0 and sign != prev_sign:
            flips.append(strike)
        if sign != 0:
            prev_sign = sign
    if not flips:
        return None
    if spot is None:
        return flips[0]
    above = [s for s in flips if s >= spot]
    return above[0] if above else flips[0]


def charm_narrative(
    net_charm_value: Decimal | None,
    signal_quality: str,
) -> tuple[str, str]:
    if net_charm_value is None or signal_quality == "weak":
        return (
            "Limited charm pressure into the close",
            "Net charm positioning is balanced or thin; mechanical hedging pressure is muted.",
        )
    if net_charm_value < 0:
        return (
            "Mechanical SELL pressure into the close",
            "Dealer sell pressure may cap rallies as theta drives delta unwind.",
        )
    return (
        "Mechanical BUY pressure into the close",
        "Dealer buy pressure may support the tape as theta drives delta accumulation.",
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/cards/test_exposures_charm.py -v
```

Expected: PASS for all 12 cases.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/exposures.py tests/unit/cards/test_exposures_charm.py
git commit -m "feat(cards): add charm derivers (net, pin, imbalance, signal quality, flip, narrative)"
```

---

### Task 2.3: Add the summary-row builder that ties vanna + charm together per expiry

**Files:**
- Modify: `src/uw_scan/cards/exposures.py` (append)
- Create: `tests/unit/cards/test_exposures_summary.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/cards/test_exposures_summary.py`:

```python
"""End-to-end deriver: GreekExposureRow list → ExposuresSummaryRow per expiry."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import build_summary_rows
from uw_scan.models import ExposuresSummaryRow, GreekExposureRow


def _r(strike: str, expiry: str, **kw) -> GreekExposureRow:
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        dte=kw.get("dte"),
        call_vanna=Decimal(kw["cv"]) if "cv" in kw else None,
        put_vanna=Decimal(kw["pv"]) if "pv" in kw else None,
        call_charm=Decimal(kw["cc"]) if "cc" in kw else None,
        put_charm=Decimal(kw["pc"]) if "pc" in kw else None,
    )


def test_build_summary_rows_groups_by_expiry():
    rows = [
        _r("100", "2026-05-30", dte=9,  cv="100", pv="-50", cc="-2000", pc="500"),
        _r("110", "2026-05-30", dte=9,  cv="200", pv="-80", cc="-3000", pc="600"),
        _r("100", "2026-06-20", dte=30, cv="10",  pv="-5",  cc="-200",  pc="50"),
    ]
    out = build_summary_rows(rows, spot=Decimal("105"))
    assert len(out) == 2

    by_expiry = {r.expiry: r for r in out}
    near = by_expiry[date.fromisoformat("2026-05-30")]
    far = by_expiry[date.fromisoformat("2026-06-20")]

    assert isinstance(near, ExposuresSummaryRow)
    assert near.dte == 9
    assert near.spot == Decimal("105")

    # Net vanna near = 100-50+200-80 = 170
    assert near.net_vanna == Decimal("170")
    # Net charm near = -2000+500-3000+600 = -3900
    assert near.net_charm == Decimal("-3900")
    # Headlines are populated (non-empty strings)
    assert near.vanna_headline
    assert near.charm_headline

    # Far expiry has thinner data — still produces a row
    assert far.net_vanna == Decimal("5")


def test_build_summary_rows_empty_returns_empty_list():
    assert build_summary_rows([], spot=Decimal("100")) == []


def test_build_summary_rows_spot_none_still_produces_rows():
    """Charm imbalance returns (0,0,None) when spot is None — must not crash."""
    rows = [_r("100", "2026-05-30", dte=9, cv="50", pv="50", cc="-1000", pc="500")]
    out = build_summary_rows(rows, spot=None)
    assert len(out) == 1
    assert out[0].spot is None
    assert out[0].charm_imbalance_pct is None


def test_build_summary_rows_mixed_dte_same_expiry_collapses_to_one_row():
    """Multiple dte values for the same expiry must NOT produce duplicate PK rows
    (table PK is (run_id, ticker, expiry)). The builder picks min non-null dte."""
    rows = [
        _r("100", "2026-05-30", dte=9,  cv="100", pv="-50", cc="-1000", pc="500"),
        _r("110", "2026-05-30", dte=10, cv="80",  pv="-30", cc="-2000", pc="800"),
        _r("105", "2026-05-30", dte=None, cv="50",  pv="-20", cc="-500",  pc="100"),
    ]
    out = build_summary_rows(rows, spot=Decimal("105"))
    assert len(out) == 1
    assert out[0].dte == 9  # min non-null
    # All three strikes contribute to the summed nets
    assert out[0].net_vanna == Decimal("130")  # (100-50)+(80-30)+(50-20)
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/unit/cards/test_exposures_summary.py -v
```

Expected: FAIL — `build_summary_rows` not defined.

- [ ] **Step 3: Append the builder to `src/uw_scan/cards/exposures.py`**

```python
# --- top-level builder -----------------------------------------------------

def build_summary_rows(
    rows: list[GreekExposureRow],
    spot: Decimal | None,
) -> list[ExposuresSummaryRow]:
    """Group rows by expiry; for each expiry, compute the full summary tuple."""
    if not rows:
        return []

    # Group by expiry ONLY — the table PK is (run_id, ticker, expiry) so
    # multiple (expiry, dte) groups would collide on upsert. UW occasionally
    # returns mixed dte values for the same expiry across strikes (rounding,
    # late-day refresh boundaries); take the min non-null dte per expiry.
    by_expiry: dict[date, list[GreekExposureRow]] = defaultdict(list)
    for r in rows:
        by_expiry[r.expiry].append(r)

    out: list[ExposuresSummaryRow] = []
    for expiry, grp in sorted(by_expiry.items(), key=lambda kv: kv[0]):
        dtes = [r.dte for r in grp if r.dte is not None]
        dte = min(dtes) if dtes else None
        nv = net_vanna(grp)
        top = top_vanna_strike(grp)
        v_regime = vanna_regime(nv)
        v_flip = vanna_flip(grp, spot)
        v_head, v_sub = vanna_narrative(nv, v_regime)

        nc = net_charm(grp)
        pin = charm_pin_strike(grp)
        above, below, imb = charm_imbalance(grp, spot)
        c_quality = charm_signal_quality(live=nc, positioning=above - below)
        c_flip = charm_flip(grp, spot)
        c_head, c_sub = charm_narrative(nc, c_quality)

        out.append(
            ExposuresSummaryRow(
                expiry=expiry,
                dte=dte,
                spot=spot,
                net_vanna=nv,
                top_vanna_strike=top[0] if top else None,
                top_vanna_value=top[1] if top else None,
                delta_shock_1pt_iv=delta_shock_1pt_iv(grp),
                vanna_regime=v_regime,
                vanna_flip=v_flip,
                vanna_headline=v_head,
                vanna_subtitle=v_sub,
                net_charm=nc,
                charm_pin_strike=pin,
                charm_above_sum=above,
                charm_below_sum=below,
                charm_imbalance_pct=imb,
                charm_signal_quality=c_quality,
                charm_flip=c_flip,
                charm_headline=c_head,
                charm_subtitle=c_sub,
            )
        )
    return out
```

Add this import at the top of `cards/exposures.py` if not already present:

```python
from datetime import date  # for type hints in builder
```

- [ ] **Step 4: Run tests and the full unit suite**

```bash
uv run pytest tests/unit/cards/test_exposures_summary.py tests/unit/cards/ -v
```

Expected: PASS (all `cards` unit tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/exposures.py tests/unit/cards/test_exposures_summary.py
git commit -m "feat(cards): add build_summary_rows tying vanna + charm derivers per expiry"
```

---

## Slice 3 — Persistence + integration tests

### Task 3.1: Add `upsert_exposures_summary` and `fetch_exposures_summary` to `storage/options.py`

**Files:**
- Modify: `src/uw_scan/storage/options.py` (append a new method on `_OptionsMixin`)
- Modify: `src/uw_scan/storage/fetchers.py` (add `fetch_strike_exposures` and a renamed `fetch_exposures_aggregate`)
- Create: `tests/integration/storage/test_exposures_summary_repository.py`

> ⚠️ Naming collision — strict ordering required: `fetchers.py` already has a `fetch_exposures_summary` that returns a single dict aggregating GEX/DEX. To free the name for the new per-expiry summary, we rename the existing function to `fetch_exposures_aggregate` **before** adding the new fetcher. The substeps below must be executed in order; if you add the new `fetch_exposures_summary` method while the old method still exists in the same class, Python keeps only the latter definition, silently breaking `_build_market_structure`. Recommended order:
>
> 1. Step 4 — rename the existing `fetch_exposures_summary` → `fetch_exposures_aggregate`; update the production caller (`reports/single_stock.py:127`); update the unit-test stub (`tests/unit/test_report_assembly.py:115`). All three edits in one commit.
> 2. Step 5 — add the new `fetch_strike_exposures` and `fetch_exposures_summary` methods on `_FetchersMixin`. Add `upsert_exposures_summary` to `_OptionsMixin`. Commit.
> 3. Step 6+ — run the integration tests.
>
> Steps below now follow this order.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/storage/test_exposures_summary_repository.py`:

```python
"""Round-trip + idempotency tests for exposures_summary persistence."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.models import ExposuresSummaryRow
from uw_scan.storage.repository import Repository


def _row(expiry: str, net_v: str = "1000") -> ExposuresSummaryRow:
    return ExposuresSummaryRow(
        expiry=date.fromisoformat(expiry),
        dte=10,
        spot=Decimal("100"),
        net_vanna=Decimal(net_v),
        top_vanna_strike=Decimal("105"),
        top_vanna_value=Decimal("500"),
        delta_shock_1pt_iv=Decimal("10"),
        vanna_regime="procyclical",
        vanna_flip=Decimal("110"),
        vanna_headline="Long Vanna",
        vanna_subtitle="...",
        net_charm=Decimal("-2000"),
        charm_pin_strike=Decimal("105"),
        charm_above_sum=Decimal("-1500"),
        charm_below_sum=Decimal("500"),
        charm_imbalance_pct=Decimal("0.5"),
        charm_signal_quality="aligned",
        charm_flip=Decimal("108"),
        charm_headline="Mechanical SELL pressure into the close",
        charm_subtitle="...",
    )


def _seed_scan_run(repo: Repository, run_id: int) -> None:
    """exposures_summary FK-references scan_runs(run_id) ON DELETE CASCADE
    (migration 051), so we need a parent scan_runs row before the child upsert."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs (run_id, ticker, started_at) "
            "VALUES (%s, 'TSLA', now()) ON CONFLICT DO NOTHING",
            (run_id,),
        )
    repo.conn.commit()


def test_upsert_and_fetch_round_trip(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=1)

    n = repo.upsert_exposures_summary(
        run_id=1,
        ticker="TSLA",
        market_date=date.fromisoformat("2026-05-21"),
        rows=[_row("2026-05-30"), _row("2026-06-20")],
    )
    assert n == 2

    fetched = repo.fetch_exposures_summary(run_id=1, ticker="TSLA")
    assert len(fetched) == 2
    expiries = {r["expiry"] for r in fetched}
    assert expiries == {date.fromisoformat("2026-05-30"), date.fromisoformat("2026-06-20")}


def test_upsert_is_idempotent(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=2)

    rows = [_row("2026-05-30", net_v="1000")]
    repo.upsert_exposures_summary(2, "TSLA", date.fromisoformat("2026-05-21"), rows)
    rows2 = [_row("2026-05-30", net_v="9999")]
    repo.upsert_exposures_summary(2, "TSLA", date.fromisoformat("2026-05-21"), rows2)

    fetched = repo.fetch_exposures_summary(2, "TSLA")
    assert len(fetched) == 1
    assert Decimal(str(fetched[0]["net_vanna"])) == Decimal("9999")


def test_fetch_strike_exposures_returns_per_expiry_strike_rows(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=3)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike, dte,
                 call_vanna, put_vanna, call_charm, put_charm)
            VALUES
                (3, 'TSLA', '2026-05-21', '2026-05-30', 100, 9, 50, -10, -1000, 200),
                (3, 'TSLA', '2026-05-21', '2026-05-30', 110, 9, 80, -20, -2000, 400)
            """
        )
    repo.conn.commit()

    out = repo.fetch_strike_exposures(run_id=3, ticker="TSLA")
    assert len(out) == 2
    strikes = {Decimal(str(r["strike"])) for r in out}
    assert strikes == {Decimal("100"), Decimal("110")}
```

- [ ] **Step 2: Run test to verify failure**

```bash
uv run pytest tests/integration/storage/test_exposures_summary_repository.py -v
```

Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_exposures_summary'`.

- [ ] **Step 3: Rename existing `fetch_exposures_summary` → `fetch_exposures_aggregate` and update both callers (in one indivisible edit set)**

This MUST land first so the new `fetch_exposures_summary` added in Step 5 has a free name. Skipping or reversing this order causes Python to shadow the old aggregate-returning method, and `_build_market_structure` will throw `AttributeError: 'list' object has no attribute 'get'` on the next request.

**a.** In `src/uw_scan/storage/fetchers.py`, find the function defined around lines 155–173 (signature `def fetch_exposures_summary(self, run_id: int, ticker: str) -> dict[str, Any] | None`) and rename it:

```python
    def fetch_exposures_aggregate(
        self, run_id: int, ticker: str
    ) -> dict[str, Any] | None:
        # body unchanged
```

**b.** In `src/uw_scan/reports/single_stock.py`, the single production call site around line 127 inside `_build_market_structure`:

```python
    exposures = repo.fetch_exposures_summary(run_id, ticker) or {}
```

→

```python
    exposures = repo.fetch_exposures_aggregate(run_id, ticker) or {}
```

**c.** In `tests/unit/test_report_assembly.py:115`, the `_StubRepo` method:

```python
    def fetch_exposures_summary(self, run_id: int, ticker: str) -> dict:
        return { ... }
```

→

```python
    def fetch_exposures_aggregate(self, run_id: int, ticker: str) -> dict:
        return {
            "total_call_gex": Decimal("1000000"),
            "total_put_gex": Decimal("-500000"),
            "total_call_dex": Decimal("50000"),
            "total_put_dex": Decimal("-30000"),
        }
```

Verify the unit suite still passes — `uv run pytest tests/unit/test_report_assembly.py -v` — then proceed. Do NOT commit yet; we'll bundle this with step 5's additions.

- [ ] **Step 4: Add `upsert_exposures_summary` to `src/uw_scan/storage/options.py`**

Append inside `_OptionsMixin` (after `insert_greeks_rows`):

```python
    def upsert_exposures_summary(
        self,
        run_id: int,
        ticker: str,
        market_date: "_date",
        rows: "Iterable[models.ExposuresSummaryRow]",
    ) -> int:
        rows = list(rows)
        if not rows:
            return 0
        sql = (
            f"INSERT INTO {self._schema}.exposures_summary "
            "(run_id, ticker, expiry, market_date, dte, spot, "
            " net_vanna, top_vanna_strike, top_vanna_value, delta_shock_1pt_iv, "
            " vanna_regime, vanna_flip, vanna_headline, vanna_subtitle, "
            " net_charm, charm_pin_strike, charm_above_sum, charm_below_sum, "
            " charm_imbalance_pct, charm_signal_quality, charm_flip, "
            " charm_headline, charm_subtitle) "
            "VALUES (%s, %s, %s, %s, %s, %s, "
            "        %s, %s, %s, %s, "
            "        %s, %s, %s, %s, "
            "        %s, %s, %s, %s, "
            "        %s, %s, %s, %s, %s) "
            "ON CONFLICT (run_id, ticker, expiry) DO UPDATE SET "
            " market_date=EXCLUDED.market_date, dte=EXCLUDED.dte, spot=EXCLUDED.spot, "
            " net_vanna=EXCLUDED.net_vanna, top_vanna_strike=EXCLUDED.top_vanna_strike, "
            " top_vanna_value=EXCLUDED.top_vanna_value, "
            " delta_shock_1pt_iv=EXCLUDED.delta_shock_1pt_iv, "
            " vanna_regime=EXCLUDED.vanna_regime, vanna_flip=EXCLUDED.vanna_flip, "
            " vanna_headline=EXCLUDED.vanna_headline, vanna_subtitle=EXCLUDED.vanna_subtitle, "
            " net_charm=EXCLUDED.net_charm, charm_pin_strike=EXCLUDED.charm_pin_strike, "
            " charm_above_sum=EXCLUDED.charm_above_sum, charm_below_sum=EXCLUDED.charm_below_sum, "
            " charm_imbalance_pct=EXCLUDED.charm_imbalance_pct, "
            " charm_signal_quality=EXCLUDED.charm_signal_quality, "
            " charm_flip=EXCLUDED.charm_flip, "
            " charm_headline=EXCLUDED.charm_headline, charm_subtitle=EXCLUDED.charm_subtitle, "
            " computed_at=now()"
        )
        params = [
            (
                run_id, ticker, r.expiry, market_date, r.dte, r.spot,
                r.net_vanna, r.top_vanna_strike, r.top_vanna_value, r.delta_shock_1pt_iv,
                r.vanna_regime, r.vanna_flip, r.vanna_headline, r.vanna_subtitle,
                r.net_charm, r.charm_pin_strike, r.charm_above_sum, r.charm_below_sum,
                r.charm_imbalance_pct, r.charm_signal_quality, r.charm_flip,
                r.charm_headline, r.charm_subtitle,
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)
```

> ⚠️ **Do NOT call `self._conn.commit()` inside this method.** Every other insert/upsert in `options.py` (e.g. `insert_greek_exposure_rows` at line 172–189) leaves commit to the caller, because the worker `_snapshot_ticker` (cockpit_daily_snapshot.py:67–104) owns the transaction boundary: `repo.conn.commit()` on success, `repo.conn.rollback()` on failure. An internal commit here would let a failed ticker leave half-rolled-back state.

(`_date` and `Iterable` are already imported at the top of `options.py`.)

- [ ] **Step 5: Add the new fetchers to `src/uw_scan/storage/fetchers.py`**

The old `fetch_exposures_summary` has already been renamed in step 3, so the name is free. Append to `_FetchersMixin`:

```python
    def fetch_strike_exposures(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        """All per-(expiry, strike) raw rows for one run/ticker.

        Includes the call/put vanna and charm split. Ordering by (expiry, strike)
        is convenient for the FE but not strictly required.
        """
        sql = (
            "SELECT expiry, strike, dte, "
            "       call_vanna, put_vanna, call_charm, put_charm "
            f"FROM {self._schema}.exposures_by_expiry_strike "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY expiry, strike"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_exposures_summary(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        """Per-(expiry) derived summary rows persisted by build_summary_rows."""
        sql = (
            "SELECT expiry, dte, spot, "
            "       net_vanna, top_vanna_strike, top_vanna_value, delta_shock_1pt_iv, "
            "       vanna_regime, vanna_flip, vanna_headline, vanna_subtitle, "
            "       net_charm, charm_pin_strike, charm_above_sum, charm_below_sum, "
            "       charm_imbalance_pct, charm_signal_quality, charm_flip, "
            "       charm_headline, charm_subtitle "
            f"FROM {self._schema}.exposures_summary "
            "WHERE run_id = %s AND ticker = %s "
            "ORDER BY expiry"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

No naming collision now — step 3 already renamed the old one. After step 5, the only `fetch_exposures_summary` in the codebase is the new per-expiry list-returning function above.

- [ ] **Step 6: Run the integration tests**

```bash
uv run pytest tests/integration/storage/test_exposures_summary_repository.py -v
```

Expected: PASS for all three tests.

- [ ] **Step 7: Verify the renamed function still imports cleanly (manual smoke)**

```bash
uv run python -c "from uw_scan.storage.repository import Repository; assert hasattr(Repository, 'fetch_exposures_aggregate'); assert hasattr(Repository, 'fetch_strike_exposures'); assert hasattr(Repository, 'fetch_exposures_summary'); assert hasattr(Repository, 'upsert_exposures_summary'); print('ok')"
```

Expected: `ok`.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/storage/options.py src/uw_scan/storage/fetchers.py src/uw_scan/reports/single_stock.py tests/integration/storage/test_exposures_summary_repository.py tests/unit/test_report_assembly.py
git commit -m "feat(storage): persist exposures_summary + rename old aggregate fetcher (with caller + stub update)"
```

---

### Task 3.2: Wire derivation+persistence into `cockpit_daily_snapshot` and `pipeline.py`

**Files:**
- Modify: `src/uw_scan/worker/jobs/cockpit_daily_snapshot.py:173` area (after `insert_greek_exposure_rows`)
- Modify: `src/uw_scan/pipeline.py:176` area (same)
- Create: `tests/integration/worker/test_cockpit_snapshot_persists_exposures_summary.py`

- [ ] **Step 1: Write the failing test**

Create `tests/integration/worker/test_cockpit_snapshot_persists_exposures_summary.py`:

```python
"""Cockpit daily snapshot must persist exposures_summary after greek_exposure rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import build_summary_rows
from uw_scan.models import GreekExposureRow
from uw_scan.storage.repository import Repository


def _seed_scan_run(repo: Repository, run_id: int) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs (run_id, ticker, started_at) "
            "VALUES (%s, 'TSLA', now()) ON CONFLICT DO NOTHING",
            (run_id,),
        )
    repo.conn.commit()


def test_summary_persisted_alongside_greek_exposure(seeded_db_empty_cards: Repository):
    """Smoke: insert greek-exposure rows, call build_summary_rows + upsert,
    one summary row appears per expiry."""
    repo = seeded_db_empty_cards
    _seed_scan_run(repo, run_id=10)

    rows = [
        GreekExposureRow(
            date=date.fromisoformat("2026-05-21"),
            expiry=date.fromisoformat("2026-05-30"),
            strike=Decimal("100"), dte=9,
            call_vanna=Decimal("100"), put_vanna=Decimal("-30"),
            call_charm=Decimal("-2000"), put_charm=Decimal("500"),
        ),
        GreekExposureRow(
            date=date.fromisoformat("2026-05-21"),
            expiry=date.fromisoformat("2026-06-20"),
            strike=Decimal("100"), dte=30,
            call_vanna=Decimal("10"), put_vanna=Decimal("-5"),
            call_charm=Decimal("-200"), put_charm=Decimal("50"),
        ),
    ]
    repo.insert_greek_exposure_rows(run_id=10, ticker="TSLA", rows=rows)
    repo.conn.commit()

    summary = build_summary_rows(rows, spot=Decimal("100"))
    repo.upsert_exposures_summary(
        run_id=10, ticker="TSLA",
        market_date=date.fromisoformat("2026-05-21"),
        rows=summary,
    )

    fetched = repo.fetch_exposures_summary(10, "TSLA")
    assert len(fetched) == 2
    expiries = {r["expiry"] for r in fetched}
    assert expiries == {date.fromisoformat("2026-05-30"), date.fromisoformat("2026-06-20")}
    assert all(r["vanna_headline"] for r in fetched)
    assert all(r["charm_headline"] for r in fetched)
```

- [ ] **Step 2: Run test to verify it passes**

```bash
uv run pytest tests/integration/worker/test_cockpit_snapshot_persists_exposures_summary.py -v
```

Expected: PASS (the underlying primitives exist after Slice 3.1).

> The point of this test is to lock in the **assembly contract** — `build_summary_rows(rows, spot) → upsert_exposures_summary(...)`. Adding the call inside the snapshot job is the wiring step that follows.

- [ ] **Step 3: Add the wiring inside `src/uw_scan/worker/jobs/cockpit_daily_snapshot.py`**

The exposure rows are processed inside a `for expiry in expiries:` loop (around lines 166–185 in the current file), one expiry per iteration. We derive + persist one summary row per iteration so the table stays in sync per-expiry.

Spot is **not** in scope at line 173. The cleanest source is `repo.get_intraday_quote(ticker)` (the same lookup `_persist_option_chain_per_strike` uses at line 197–198). Pull it **once** before the expiry loop so we don't hit the DB N times.

Add this block immediately before `for expiry in expiries:` (currently around line 166):

```python
        # Spot for vanna/charm derivers — None is acceptable; deriver handles it.
        # Reject 0/negative/non-finite values so downstream % calcs don't produce
        # Infinity. Fall back to RV latest price (same source _build_market_structure
        # uses at single_stock.py:144) when the intraday quote is missing/invalid.
        def _safe_spot(value) -> Decimal | None:
            if value is None:
                return None
            try:
                d = Decimal(str(value))
            except (TypeError, ValueError) as exc:
                logger.debug("safe_spot coercion skipped: %s", repr(exc))
                return None
            if not d.is_finite() or d <= 0:
                return None
            return d

        quote = repo.get_intraday_quote(ticker)
        spot_for_derive: Decimal | None = _safe_spot(
            quote.price if quote is not None else None
        )
        if spot_for_derive is None:
            rv = repo.fetch_realized_vol_latest(ticker) or {}
            spot_for_derive = _safe_spot(rv.get("price"))
```

Then, immediately after `n_e = repo.insert_greek_exposure_rows(run_id, ticker, exposure_rows)` (line 173 area), add:

```python
        if exposure_rows:
            summary_rows = cards_exposures.build_summary_rows(
                list(exposure_rows), spot=spot_for_derive
            )
            n_sum = repo.upsert_exposures_summary(
                run_id=run_id,
                ticker=ticker,
                market_date=market_date,
                rows=summary_rows,
            )
            logger.info(
                "cockpit_daily_snapshot: %s exp=%s exposures_summary=%d",
                ticker, expiry_iso, n_sum,
            )
```

At the top of the file, add the import:

```python
from decimal import Decimal  # may already be present — keep imports deduped
from uw_scan.cards import exposures as cards_exposures
```

`market_date` is already in scope inside `_persist_greeks_per_expiry` (it's a function parameter passed from the caller — verify by searching for `market_date=market_date` in the file). `ticker`, `run_id`, `expiry_iso`, and `logger` are also already in scope.

- [ ] **Step 4: Add the same wiring to `src/uw_scan/pipeline.py`**

`pipeline.py`'s `scan_one_ticker` is the path that powers per-ticker watchlist scans (TSLA-style stock pages), so passing `spot=None` here would degrade the most common stock-detail view. Use the same source `_build_market_structure` reads — `repo.fetch_realized_vol_latest(ticker)["price"]` — with `repo.get_intraday_quote(ticker)` as a fallback. Both repo methods are already on the Repository.

Find `repo.insert_greek_exposure_rows(run_id, ticker, ge_rows)` at line 176. Add immediately after the existing block 8b that builds the GEX curve (around line 193, i.e. after `repo.set_strike_gex_curve(run_id, curve)`):

```python
        # 8c. Vanna/Charm derived summary per expiry (raw rows already in step 8).
        if ge_rows:
            # Spot: prefer intraday quote, fall back to realized-vol latest price.
            # Reject 0/negative/non-finite values — they corrupt charm imbalance
            # and FE "% from spot" calculations.
            def _safe_spot(value) -> Decimal | None:
                if value is None:
                    return None
                try:
                    d = Decimal(str(value))
                except (TypeError, ValueError) as exc:
                    logger.debug("safe_spot coercion skipped: %s", repr(exc))
                    return None
                if not d.is_finite() or d <= 0:
                    return None
                return d

            quote = repo.get_intraday_quote(ticker)
            spot_for_derive: Decimal | None = _safe_spot(
                quote.price if quote is not None else None
            )
            if spot_for_derive is None:
                rv = repo.fetch_realized_vol_latest(ticker) or {}
                spot_for_derive = _safe_spot(rv.get("price"))

            summary_rows = cards_exposures.build_summary_rows(
                list(ge_rows), spot=spot_for_derive
            )
            repo.upsert_exposures_summary(
                run_id=run_id,
                ticker=ticker,
                market_date=_date.today(),
                rows=summary_rows,
            )
```

`_date` and `Decimal` are already imported at the top of `pipeline.py`. Add the cards import:

```python
from uw_scan.cards import exposures as cards_exposures
```

- [ ] **Step 4b: Add a real worker-wiring test (not just an assembly-contract test)**

The Step 1 test only exercises `build_summary_rows` + `upsert_exposures_summary` directly — it would still pass if neither `_snapshot_ticker` nor `scan_one_ticker` actually called them. Add a second test that drives the actual production function and asserts the call.

> ⚠️ **Verify the function shape first.** Before writing the test, run:
>
> ```bash
> grep -n "def _" src/uw_scan/worker/jobs/cockpit_daily_snapshot.py
> ```
>
> Current state (verified 2026-05-21): the file has `_snapshot_ticker(...)` and `_persist_option_chain_per_strike(...)` but **no** `_persist_greeks_per_expiry` helper — the per-expiry loop lives inline inside `_snapshot_ticker`. The test must therefore drive `_snapshot_ticker` directly OR you must extract the per-expiry block into a named helper as part of Step 3 (preferred — easier to test and clearer).
>
> Preferred Step 3 micro-refactor: in `cockpit_daily_snapshot.py`, lift the `for expiry in expiries:` loop into a new private helper `_persist_greeks_per_expiry(client, repo, run_id, ticker, market_date, expiries, spot_for_derive)`. Call it from `_snapshot_ticker`. Keep the body identical except for parameter passing. Commit this micro-refactor as part of the wiring commit.

Create `tests/unit/worker/test_cockpit_daily_snapshot_summary_wiring.py`:

```python
"""Unit wiring test: when fetch_greek_exposure returns rows, _snapshot_ticker
(via the extracted _persist_greeks_per_expiry helper) MUST call
upsert_exposures_summary. This guards against silent regression of the
Step 3 wiring."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock


def _ge_row(expiry: str, strike: str):
    from uw_scan.models import GreekExposureRow
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike), dte=9,
        call_vanna=Decimal("100"), put_vanna=Decimal("-30"),
        call_charm=Decimal("-2000"), put_charm=Decimal("500"),
    )


def test_per_expiry_loop_persists_exposures_summary(monkeypatch):
    """The per-expiry loop helper must call upsert_exposures_summary once per
    expiry whenever fetch_greek_exposure returned rows."""
    from uw_scan.worker.jobs import cockpit_daily_snapshot as job

    fake_repo = MagicMock()
    fake_repo._schema = "uw_scan"
    fake_repo.get_intraday_quote.return_value = MagicMock(price=Decimal("100"))
    fake_repo.insert_greek_exposure_rows.return_value = 2
    fake_repo.upsert_skew_rows.return_value = 0
    fake_repo.insert_greeks_rows.return_value = 0

    monkeypatch.setattr(job, "fetch_greek_exposure", lambda *_a, **_k: [
        _ge_row("2026-05-30", "100"),
        _ge_row("2026-05-30", "110"),
    ])
    monkeypatch.setattr(job, "fetch_greeks", lambda *_a, **_k: [])
    monkeypatch.setattr(job, "fetch_skew", lambda *_a, **_k: [])

    # If you extracted _persist_greeks_per_expiry in Step 3, call it here.
    # Otherwise call _snapshot_ticker with the full kwargs taken from the
    # production callsite — adjust the signature to match what's in the file.
    helper = getattr(job, "_persist_greeks_per_expiry", None)
    if helper is None:
        # Fallback path — drive _snapshot_ticker directly.
        job._snapshot_ticker(
            client=MagicMock(), repo=fake_repo, deriver_repo=fake_repo,
            run_id=999, ticker="TSLA",
            market_date=date.fromisoformat("2026-05-21"),
            target_dtes=[7],
            oi_band_pct=Decimal("0.15"),
            oi_max_dte=120,
        )
    else:
        helper(
            client=MagicMock(), repo=fake_repo,
            run_id=999, ticker="TSLA",
            market_date=date.fromisoformat("2026-05-21"),
            expiries=[date.fromisoformat("2026-05-30")],
            spot_for_derive=Decimal("100"),
        )

    assert fake_repo.upsert_exposures_summary.called, (
        "Wiring failure: per-expiry loop did not call upsert_exposures_summary "
        "after insert_greek_exposure_rows. Re-check Step 3 wiring."
    )
    assert fake_repo.upsert_exposures_summary.call_count >= 1
```

> ⚠️ The `_snapshot_ticker` fallback signature (`target_dtes`, `oi_band_pct`, `oi_max_dte`, `deriver_repo`) is taken from the current file (`cockpit_daily_snapshot.py:109` area). Inspect the actual signature before running and adjust the kwargs to match — the test should call the function the same way the production scheduler does. If the signature drifts, the test will fail with a `TypeError` rather than silently passing.

- [ ] **Step 5: Re-run unit + integration + worker tests**

```bash
uv run pytest tests/unit tests/integration/storage tests/integration/worker -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/jobs/cockpit_daily_snapshot.py src/uw_scan/pipeline.py \
        tests/integration/worker/test_cockpit_snapshot_persists_exposures_summary.py \
        tests/unit/worker/test_cockpit_daily_snapshot_summary_wiring.py
git commit -m "feat(worker): persist exposures_summary in cockpit snapshot and pipeline"
```

> ⚠️ Both the integration test (Step 1 file) AND the unit wiring test (Step 4b file) MUST be in this commit. The unit wiring test catches silent regressions where the production wiring is removed but the integration test (which calls primitives directly) would still pass.

---

## Slice 4 — Report assembler + API surface

### Task 4.1: Surface new fields on `SingleStockReport`

**Files:**
- Modify: `src/uw_scan/models/stock.py` (add fields)
- Modify: `src/uw_scan/reports/single_stock.py` (load + attach new rows in `assemble_single_stock_report`)
- Create: `tests/integration/reports/test_single_stock_exposures.py`

> Note: the `fetch_exposures_summary → fetch_exposures_aggregate` rename + caller update already happened in Task 3.1 step 5. This task only adds the new field loading; it does not touch the renamed call again.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/reports/test_single_stock_exposures.py`:

```python
"""Report assembler attaches strike_exposures and exposures_summary."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import build_summary_rows
from uw_scan.models import GreekExposureRow
from uw_scan.reports.single_stock import assemble_single_stock_report
from uw_scan.storage.repository import Repository


def _seed_exposures(repo: Repository, ticker: str, run_id: int, market_date: date) -> None:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.scan_runs (run_id, ticker, started_at) "
            "VALUES (%s, %s, now()) ON CONFLICT DO NOTHING",
            (run_id, ticker),
        )
        cur.execute(
            f"""
            INSERT INTO {repo._schema}.exposures_by_expiry_strike
                (run_id, ticker, market_date, expiry, strike, dte,
                 call_vanna, put_vanna, call_charm, put_charm,
                 call_gex, put_gex, call_delta, put_delta)
            VALUES
                (%s, %s, %s, '2026-05-30', 100, 9, 100, -30, -2000, 500, 0, 0, 0, 0),
                (%s, %s, %s, '2026-05-30', 110, 9, 200, -50, -3000, 800, 0, 0, 0, 0)
            """,
            (run_id, ticker, market_date, run_id, ticker, market_date),
        )
    repo.conn.commit()


def test_report_includes_strike_exposures_and_summary(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    market_date = date.fromisoformat("2026-05-21")
    _seed_exposures(repo, "TSLA", run_id=20, market_date=market_date)

    raw = [
        GreekExposureRow(
            date=market_date, expiry=date.fromisoformat("2026-05-30"),
            strike=Decimal("100"), dte=9,
            call_vanna=Decimal("100"), put_vanna=Decimal("-30"),
            call_charm=Decimal("-2000"), put_charm=Decimal("500"),
        ),
        GreekExposureRow(
            date=market_date, expiry=date.fromisoformat("2026-05-30"),
            strike=Decimal("110"), dte=9,
            call_vanna=Decimal("200"), put_vanna=Decimal("-50"),
            call_charm=Decimal("-3000"), put_charm=Decimal("800"),
        ),
    ]
    repo.upsert_exposures_summary(
        run_id=20, ticker="TSLA", market_date=market_date,
        rows=build_summary_rows(raw, spot=Decimal("105")),
    )

    report = assemble_single_stock_report(ticker="TSLA", run_id=20, repo=repo)
    assert len(report.strike_exposures) == 2
    assert {row.strike for row in report.strike_exposures} == {Decimal("100"), Decimal("110")}
    assert len(report.exposures_summary) == 1
    summary = report.exposures_summary[0]
    assert summary.expiry == date.fromisoformat("2026-05-30")
    assert summary.vanna_headline
```

- [ ] **Step 2: Add fields to `SingleStockReport` in `src/uw_scan/models/stock.py`**

In the existing `SingleStockReport` class, after `option_chain_per_strike` and before `next_earnings_date`:

```python
    strike_exposures: list["StrikeExposureRow"] = []
    exposures_summary: list["ExposuresSummaryRow"] = []
```

Update the `from .scanner import (...)` line at the top of `stock.py`:

```python
from .scanner import (
    ExposuresSummaryRow,
    MarketAggregates,
    MarketStructureLevels,
    StrikeExposureRow,
    StrikeGexBucket,
)
```

- [ ] **Step 3: Update `src/uw_scan/reports/single_stock.py`**

The `fetch_exposures_aggregate` rename was already wired into `_build_market_structure` in Task 3.1 step 5. This step only adds the new raw + summary loaders inside `assemble_single_stock_report`.

Load the new raw + summary rows. After the `strike_gex_curve = [...]` block (around line 470). Uses the existing `_to_decimal` helper (`single_stock.py:40`) for consistency with the rest of the file:

```python
    strike_exp_raw = repo.fetch_strike_exposures(run_id, ticker)
    # `strike` and `expiry` are NOT NULL in exposures_by_expiry_strike + are
    # projected non-null by the fetcher. Use [...] indexing (not .get) so a
    # missing key fails loudly with a KeyError at the row, rather than producing
    # a Pydantic ValidationError that aborts the entire report assembly.
    strike_exposures = [
        StrikeExposureRow(
            strike=Decimal(str(row["strike"])),
            expiry=row["expiry"],
            dte=row.get("dte"),
            call_vanna=_to_decimal(row.get("call_vanna")),
            put_vanna=_to_decimal(row.get("put_vanna")),
            call_charm=_to_decimal(row.get("call_charm")),
            put_charm=_to_decimal(row.get("put_charm")),
        )
        for row in strike_exp_raw
        if row.get("strike") is not None  # defensive — should never trigger
    ]

    summary_raw = repo.fetch_exposures_summary(run_id, ticker)
    exposures_summary = [
        ExposuresSummaryRow(
            expiry=row["expiry"],
            dte=row.get("dte"),
            spot=_to_decimal(row.get("spot")),
            net_vanna=_to_decimal(row.get("net_vanna")),
            top_vanna_strike=_to_decimal(row.get("top_vanna_strike")),
            top_vanna_value=_to_decimal(row.get("top_vanna_value")),
            delta_shock_1pt_iv=_to_decimal(row.get("delta_shock_1pt_iv")),
            vanna_regime=row.get("vanna_regime"),
            vanna_flip=_to_decimal(row.get("vanna_flip")),
            vanna_headline=row.get("vanna_headline"),
            vanna_subtitle=row.get("vanna_subtitle"),
            net_charm=_to_decimal(row.get("net_charm")),
            charm_pin_strike=_to_decimal(row.get("charm_pin_strike")),
            charm_above_sum=_to_decimal(row.get("charm_above_sum")),
            charm_below_sum=_to_decimal(row.get("charm_below_sum")),
            charm_imbalance_pct=_to_decimal(row.get("charm_imbalance_pct")),
            charm_signal_quality=row.get("charm_signal_quality"),
            charm_flip=_to_decimal(row.get("charm_flip")),
            charm_headline=row.get("charm_headline"),
            charm_subtitle=row.get("charm_subtitle"),
        )
        for row in summary_raw
    ]
```

The defensive filter (`if row.get("strike") is not None`) plus `Decimal(str(row["strike"]))` directly converts the required field; `_to_decimal(row.get("x"))` is used only for the nullable greek columns. If the fetcher ever projects a NULL strike (schema drift, partial joins), the row is dropped instead of crashing the whole report.

In the existing `return SingleStockReport(...)` call at line 489, insert the two new kwargs immediately before `next_earnings_date=next_earnings_date,` (line 510) so they're grouped near the other new persisted fields:

```python
        strike_exposures=strike_exposures,
        exposures_summary=exposures_summary,
        next_earnings_date=next_earnings_date,
    )
```

Update the top-of-file imports:

```python
from uw_scan.models import (
    ...,  # existing
    ExposuresSummaryRow,
    StrikeExposureRow,
)
```

- [ ] **Step 4: Run the new integration test + the broader report tests**

```bash
uv run pytest tests/integration/reports/test_single_stock_exposures.py tests/integration/reports -q
```

Expected: PASS. No regressions on existing report tests.

- [ ] **Step 5: Verify the OpenAPI snapshot doesn't break unexpectedly**

The actual snapshot test lives at `tests/integration/api/test_openapi_snapshot.py` with the JSON file at `tests/integration/api/openapi.snapshot.json`. Run it:

```bash
uv run pytest tests/integration/api/test_openapi_snapshot.py -q
```

The two added fields are purely additive — but the snapshot file is checked in, so it will need to be regenerated deliberately. After confirming the diff is only the two new fields + two new component schemas (`StrikeExposureRow`, `ExposuresSummaryRow`), refresh:

```bash
# Inspect the diff first to confirm there are no unexpected schema changes.
uv run pytest tests/integration/api/test_openapi_snapshot.py -q -v
# Then update the snapshot. Mechanism depends on the test — read the file's
# top comment for the exact regeneration command, OR re-run the test with
# the documented snapshot-update flag.
```

If the snapshot test uses an inline regenerate-on-flag pattern, use that flag. If it compares a file checked-in, regenerate it by running the FastAPI app and curl'ing /openapi.json:

```bash
uv run uvicorn uw_scan.api.server:app --port 8400 --no-access-log &
SNAP_PID=$!
for _ in {1..20}; do curl -sf http://localhost:8400/openapi.json > /dev/null && break || sleep 0.5; done
curl -s http://localhost:8400/openapi.json | python -m json.tool > tests/integration/api/openapi.snapshot.json
kill "$SNAP_PID" 2>/dev/null || true
wait "$SNAP_PID" 2>/dev/null || true
```

Either way, the commit message in step 6 should call out that the snapshot was updated for the additive field surface.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/models/stock.py src/uw_scan/reports/single_stock.py tests/integration/reports/test_single_stock_exposures.py
git commit -m "feat(report): expose strike_exposures and exposures_summary on SingleStockReport"
```

---

### Task 4.2: Regenerate frontend types

**Files:**
- Modify: `web/lib/types.ts` (generated)

- [ ] **Step 1: Start the API server in the background**

Use direct uvicorn rather than `scripts/dev.sh` — `dev.sh` spawns multiple sub-processes whose PIDs aren't easy to track from a script, so cleanup is fragile.

```bash
uv run uvicorn uw_scan.api.server:app --port 8400 --no-access-log &
UVICORN_PID=$!
# Wait for the API to come up (poll /openapi.json instead of sleeping arbitrarily).
for _ in {1..20}; do
  curl -sf http://localhost:8400/openapi.json > /dev/null && break || sleep 0.5
done
```

- [ ] **Step 2: Regenerate types**

```bash
cd web && npm run gen:types && cd ..
```

- [ ] **Step 3: Verify new types appear**

```bash
grep -n "StrikeExposureRow\|ExposuresSummaryRow\|strike_exposures\|exposures_summary" web/lib/types.ts | head -20
```

Expected: both component definitions plus the two new fields under `SingleStockReport`.

- [ ] **Step 4: Stop the API server**

```bash
kill "$UVICORN_PID" 2>/dev/null || true
wait "$UVICORN_PID" 2>/dev/null || true
```

- [ ] **Step 5: Run web typecheck (catches any silent type breakage)**

```bash
cd web && npm run typecheck && cd ..
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/lib/types.ts
git commit -m "chore(web): regenerate types for vanna/charm fields"
```

---

## Slice 5 — Frontend chart components (shared building blocks)

### Task 5.1: Add a small money-abbreviation formatter

**Files:**
- Modify: `web/lib/formatters.ts`
- Modify: `web/tests/unit/formatters.test.ts` (if it exists; otherwise create)

- [ ] **Step 1: Write the failing test**

Append to (or create) `web/tests/unit/formatters.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { fmtMoneyAbbrev } from "@/lib/formatters";

describe("fmtMoneyAbbrev", () => {
  it("formats values >= 1T with T suffix", () => {
    expect(fmtMoneyAbbrev(1_500_000_000_000)).toBe("+$1.5T");
    expect(fmtMoneyAbbrev(-1_500_000_000_000)).toBe("-$1.5T");
  });
  it("formats millions, thousands", () => {
    expect(fmtMoneyAbbrev(1_300_000)).toBe("+$1.3M");
    expect(fmtMoneyAbbrev(-227_050)).toBe("-$227.1K");
    expect(fmtMoneyAbbrev(0)).toBe("$0");
  });
  it("returns dash for null/undefined", () => {
    expect(fmtMoneyAbbrev(null)).toBe("—");
    expect(fmtMoneyAbbrev(undefined)).toBe("—");
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd web && npm run test -- formatters
```

Expected: FAIL — `fmtMoneyAbbrev` not exported.

- [ ] **Step 3: Add the formatter**

Append to `web/lib/formatters.ts`:

```typescript
export function fmtMoneyAbbrev(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "$0";
  const sign = v >= 0 ? "+" : "-";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(1)}T`;
  if (abs >= 1e9)  return `${sign}$${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6)  return `${sign}$${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3)  return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd web && npm run test -- formatters
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/formatters.ts web/tests/unit/formatters.test.ts
git commit -m "feat(web): add fmtMoneyAbbrev for $1.3M / $15.5T-style values"
```

---

### Task 5.2: Build `NetExposureChart` SVG line chart

**Files:**
- Create: `web/components/stock/panels/greeks/NetExposureChart.tsx`
- Create: `web/tests/unit/greekCharts/NetExposureChart.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/greekCharts/NetExposureChart.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NetExposureChart } from "@/components/stock/panels/greeks/NetExposureChart";

const curve = [
  { strike: 90,  netValue: -100 },
  { strike: 100, netValue: -50 },
  { strike: 110, netValue: 200 },
  { strike: 120, netValue: 250 },
];

describe("NetExposureChart", () => {
  it("draws a path covering all finite points", () => {
    const { container } = render(
      <NetExposureChart
        curve={curve}
        spot={105}
        flipStrike={110}
        yLabel="Vanna"
        title="Net Vanna Exposure (9 DTE) — TSLA"
      />,
    );
    const path = container.querySelector("path[data-testid='net-line']");
    expect(path).not.toBeNull();
    const d = path!.getAttribute("d") ?? "";
    expect(d.startsWith("M")).toBe(true);
    expect(d.match(/L/g)?.length ?? 0).toBeGreaterThanOrEqual(3);
  });

  it("renders the spot reference line", () => {
    const { container } = render(
      <NetExposureChart curve={curve} spot={105} flipStrike={null} yLabel="Vanna" title="x" />,
    );
    expect(container.querySelector("line[data-testid='spot-line']")).not.toBeNull();
  });

  it("renders the flip reference line when flipStrike provided", () => {
    const { container } = render(
      <NetExposureChart curve={curve} spot={105} flipStrike={110} yLabel="Vanna" title="x" />,
    );
    expect(container.querySelector("line[data-testid='flip-line']")).not.toBeNull();
  });

  it("renders empty state when curve has zero finite points", () => {
    const { container, queryByText } = render(
      <NetExposureChart curve={[]} spot={105} flipStrike={null} yLabel="Vanna" title="x" />,
    );
    expect(container.querySelector("path[data-testid='net-line']")).toBeNull();
    expect(queryByText(/not enough/i)).not.toBeNull();
  });

  it("renders a single-point marker (no line) when curve has exactly one finite point", () => {
    // Per spec §"Error handling": single expiry with one strike should render
    // a point marker + spot reference line, NOT an empty state.
    const { container, queryByText } = render(
      <NetExposureChart
        curve={[{ strike: 100, netValue: 5000 }]}
        spot={100}
        flipStrike={null}
        yLabel="Vanna"
        title="x"
      />,
    );
    expect(queryByText(/not enough/i)).toBeNull();
    expect(container.querySelector("circle[data-testid='net-point']")).not.toBeNull();
    // No line path needed for a single point — but axes + spot line still render.
    expect(container.querySelector("line[data-testid='spot-line']")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd web && npm run test -- NetExposureChart
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create the chart component**

Create `web/components/stock/panels/greeks/NetExposureChart.tsx`:

```tsx
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";
import { fmtMoneyAbbrev } from "@/lib/formatters";

export type NetExposurePoint = {
  strike: number;
  netValue: number | null;
};

type Props = {
  curve: NetExposurePoint[];
  spot: number | null;
  flipStrike: number | null;
  yLabel: "Vanna" | "Charm";
  title: string;
  width?: number;
  height?: number;
};

const PAD = { top: 36, right: 24, bottom: 40, left: 64 };
const NET_COLOR = "var(--accent-vol)";
const SPOT_COLOR = "var(--warning)";

export function NetExposureChart({
  curve,
  spot,
  flipStrike,
  yLabel,
  title,
  width = 560,
  height = 360,
}: Props) {
  // Count finite (strike, netValue) pairs — drives both the empty-state and
  // the single-point fallback. `finiteDomain` returns null for <2 points, so
  // we count manually here.
  const finitePts = curve.filter(
    (c) => Number.isFinite(c.strike) && c.netValue != null && Number.isFinite(c.netValue as number),
  );

  const panel: React.CSSProperties = {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-dim)",
    borderRadius: 4,
    padding: 16,
    fontFamily: "var(--font-mono)",
  };

  if (finitePts.length === 0) {
    return (
      <div style={panel}>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
          {title}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough data to render the curve.
        </div>
      </div>
    );
  }

  // For a single-point fallback we need x/y domains anyway — synthesize a
  // small symmetric window around the lone point so axes + spot line still
  // render meaningfully.
  const xDomain =
    finitePts.length >= 2
      ? finiteDomain(finitePts.map((c) => c.strike))!
      : (() => {
          const s = finitePts[0].strike;
          const half = spot != null ? Math.abs(s - spot) || s * 0.05 : s * 0.05;
          return { lo: s - half, hi: s + half, count: 1 };
        })();
  const yDomain =
    finitePts.length >= 2
      ? finiteDomain(finitePts.map((c) => c.netValue))!
      : (() => {
          const v = Math.abs(finitePts[0].netValue as number);
          return { lo: -v, hi: v, count: 1 };
        })();

  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;

  const xScale = linearScale([xDomain.lo, xDomain.hi], [0, innerW]);
  // Symmetrical y-axis around zero so the centerline reads cleanly.
  const yAbs = Math.max(Math.abs(yDomain.lo), Math.abs(yDomain.hi), 1);
  const yScale = linearScale([-yAbs, yAbs], [innerH, 0]);

  const points: Point[] = finitePts.map((c) => [
    xScale(c.strike),
    yScale(c.netValue as number),
  ]);

  const xTicks = niceTicks(xDomain.lo, xDomain.hi, 6);
  const yTicks = niceTicks(-yAbs, yAbs, 5);

  return (
    <div style={panel}>
      <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
        {title}
      </div>
      <svg width={width} height={height} role="img" aria-label={title}>
        <title>{title}</title>
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {/* y-axis grid + labels */}
          {yTicks.map((t) => (
            <g key={`y-${t}`}>
              <line
                x1={0}
                x2={innerW}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke="var(--border-dim)"
                strokeWidth={t === 0 ? 1 : 0.5}
              />
              <text
                x={-8}
                y={yScale(t)}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                fill="var(--text-muted)"
              >
                {fmtMoneyAbbrev(t)}
              </text>
            </g>
          ))}

          {/* x-axis labels */}
          {xTicks.map((t) => (
            <text
              key={`x-${t}`}
              x={xScale(t)}
              y={innerH + 18}
              textAnchor="middle"
              fontSize={10}
              fill="var(--text-muted)"
            >
              {t.toFixed(0)}
            </text>
          ))}

          {/* Spot reference */}
          {spot != null && xDomain.lo <= spot && spot <= xDomain.hi && (
            <>
              <line
                data-testid="spot-line"
                x1={xScale(spot)}
                x2={xScale(spot)}
                y1={0}
                y2={innerH}
                stroke={SPOT_COLOR}
                strokeWidth={1}
              />
              <text
                x={xScale(spot) + 6}
                y={12}
                fontSize={10}
                fill={SPOT_COLOR}
              >
                Price: {spot.toFixed(2)}
              </text>
            </>
          )}

          {/* Flip reference */}
          {flipStrike != null && xDomain.lo <= flipStrike && flipStrike <= xDomain.hi && (
            <>
              <line
                data-testid="flip-line"
                x1={xScale(flipStrike)}
                x2={xScale(flipStrike)}
                y1={0}
                y2={innerH}
                stroke={NET_COLOR}
                strokeWidth={1}
                strokeDasharray="4 3"
              />
              <text
                x={xScale(flipStrike) + 6}
                y={26}
                fontSize={10}
                fill={NET_COLOR}
              >
                {yLabel} flip: {flipStrike.toFixed(2)}
              </text>
            </>
          )}

          {/* Net curve (line when ≥2 points, marker when 1 point) */}
          {points.length >= 2 && (
            <path
              data-testid="net-line"
              d={pathFromPoints(points)}
              stroke={NET_COLOR}
              strokeWidth={2}
              fill="none"
            />
          )}
          {points.length === 1 && (
            <circle
              data-testid="net-point"
              cx={points[0][0]}
              cy={points[0][1]}
              r={4}
              fill={NET_COLOR}
            />
          )}
        </g>

        {/* y-axis label */}
        <text
          x={16}
          y={PAD.top + innerH / 2}
          textAnchor="middle"
          transform={`rotate(-90, 16, ${PAD.top + innerH / 2})`}
          fontSize={10}
          fill="var(--text-muted)"
        >
          {yLabel}
        </text>
      </svg>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd web && npm run test -- NetExposureChart
```

Expected: PASS for all 4 cases.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/greeks/NetExposureChart.tsx web/tests/unit/greekCharts/NetExposureChart.test.tsx
git commit -m "feat(web): add NetExposureChart hand-rolled SVG line chart"
```

---

### Task 5.3: Build `CallPutExposureChart` (two-line variant)

**Files:**
- Create: `web/components/stock/panels/greeks/CallPutExposureChart.tsx`
- Create: `web/tests/unit/greekCharts/CallPutExposureChart.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/greekCharts/CallPutExposureChart.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CallPutExposureChart } from "@/components/stock/panels/greeks/CallPutExposureChart";

const curve = [
  { strike: 90,  callValue: 100, putValue: -50 },
  { strike: 100, callValue: 200, putValue: -100 },
  { strike: 110, callValue: 80,  putValue: -150 },
];

describe("CallPutExposureChart", () => {
  it("draws two paths", () => {
    const { container } = render(
      <CallPutExposureChart
        curve={curve}
        spot={100}
        yLabel="Vanna"
        title="Vanna Exposure — TSLA"
      />,
    );
    expect(container.querySelector("path[data-testid='call-line']")).not.toBeNull();
    expect(container.querySelector("path[data-testid='put-line']")).not.toBeNull();
  });

  it("renders the spot reference line", () => {
    const { container } = render(
      <CallPutExposureChart curve={curve} spot={100} yLabel="Vanna" title="x" />,
    );
    expect(container.querySelector("line[data-testid='spot-line']")).not.toBeNull();
  });

  it("renders empty state when curve is empty", () => {
    const { container, queryByText } = render(
      <CallPutExposureChart curve={[]} spot={null} yLabel="Vanna" title="x" />,
    );
    expect(container.querySelector("path[data-testid='call-line']")).toBeNull();
    expect(queryByText(/not enough/i)).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd web && npm run test -- CallPutExposureChart
```

Expected: FAIL — module not found.

- [ ] **Step 3: Create the chart component**

Create `web/components/stock/panels/greeks/CallPutExposureChart.tsx`:

```tsx
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";
import { fmtMoneyAbbrev } from "@/lib/formatters";

export type CallPutPoint = {
  strike: number;
  callValue: number | null;
  putValue: number | null;
};

type Props = {
  curve: CallPutPoint[];
  spot: number | null;
  yLabel: "Vanna" | "Charm";
  title: string;
  width?: number;
  height?: number;
};

const PAD = { top: 36, right: 24, bottom: 40, left: 64 };
const CALL_COLOR = "var(--positive)";
const PUT_COLOR = "var(--negative)";
const SPOT_COLOR = "var(--warning)";

export function CallPutExposureChart({
  curve,
  spot,
  yLabel,
  title,
  width = 560,
  height = 360,
}: Props) {
  // Count finite strikes (any side present). Mirrors NetExposureChart so that
  // a single-strike expiry renders point markers + spot line, not empty state.
  const finiteCall = curve.filter(
    (c) => Number.isFinite(c.strike) && c.callValue != null && Number.isFinite(c.callValue as number),
  );
  const finitePut = curve.filter(
    (c) => Number.isFinite(c.strike) && c.putValue != null && Number.isFinite(c.putValue as number),
  );
  const finiteStrikes = curve.filter(
    (c) => Number.isFinite(c.strike) && (c.callValue != null || c.putValue != null),
  );

  const panel: React.CSSProperties = {
    background: "var(--bg-panel)",
    border: "1px solid var(--border-dim)",
    borderRadius: 4,
    padding: 16,
    fontFamily: "var(--font-mono)",
  };

  if (finiteStrikes.length === 0) {
    return (
      <div style={panel}>
        <div style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 8 }}>
          {title}
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough data to render the curve.
        </div>
      </div>
    );
  }

  // Synthesize a small symmetric window when there's only one finite strike.
  const allY = [
    ...finiteCall.map((c) => c.callValue as number),
    ...finitePut.map((c) => c.putValue as number),
  ];
  const xDomain =
    finiteStrikes.length >= 2
      ? finiteDomain(finiteStrikes.map((c) => c.strike))!
      : (() => {
          const s = finiteStrikes[0].strike;
          const half = spot != null ? Math.abs(s - spot) || s * 0.05 : s * 0.05;
          return { lo: s - half, hi: s + half, count: 1 };
        })();
  const yDomain =
    allY.length >= 2
      ? finiteDomain(allY)!
      : (() => {
          const v = allY[0] != null ? Math.abs(allY[0]) : 1;
          return { lo: -v, hi: v, count: 1 };
        })();

  const innerW = width - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const xScale = linearScale([xDomain.lo, xDomain.hi], [0, innerW]);
  const yAbs = Math.max(Math.abs(yDomain.lo), Math.abs(yDomain.hi), 1);
  const yScale = linearScale([-yAbs, yAbs], [innerH, 0]);

  const callPoints: Point[] = finiteCall.map((c) => [
    xScale(c.strike), yScale(c.callValue as number),
  ]);
  const putPoints: Point[] = finitePut.map((c) => [
    xScale(c.strike), yScale(c.putValue as number),
  ]);

  const xTicks = niceTicks(xDomain.lo, xDomain.hi, 6);
  const yTicks = niceTicks(-yAbs, yAbs, 5);

  return (
    <div style={panel}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div style={{ fontSize: 13, color: "var(--text-secondary)" }}>
          {title}
        </div>
        <div style={{ display: "flex", gap: 12, fontSize: 11 }}>
          <span style={{ color: CALL_COLOR }}>— Call {yLabel}</span>
          <span style={{ color: PUT_COLOR }}>— Put {yLabel}</span>
        </div>
      </div>
      <svg width={width} height={height} role="img" aria-label={title}>
        <title>{title}</title>
        <g transform={`translate(${PAD.left},${PAD.top})`}>
          {yTicks.map((t) => (
            <g key={`y-${t}`}>
              <line
                x1={0}
                x2={innerW}
                y1={yScale(t)}
                y2={yScale(t)}
                stroke="var(--border-dim)"
                strokeWidth={t === 0 ? 1 : 0.5}
              />
              <text
                x={-8}
                y={yScale(t)}
                dy="0.32em"
                textAnchor="end"
                fontSize={10}
                fill="var(--text-muted)"
              >
                {fmtMoneyAbbrev(t)}
              </text>
            </g>
          ))}
          {xTicks.map((t) => (
            <text
              key={`x-${t}`}
              x={xScale(t)}
              y={innerH + 18}
              textAnchor="middle"
              fontSize={10}
              fill="var(--text-muted)"
            >
              {t.toFixed(0)}
            </text>
          ))}

          {spot != null && xDomain.lo <= spot && spot <= xDomain.hi && (
            <>
              <line
                data-testid="spot-line"
                x1={xScale(spot)}
                x2={xScale(spot)}
                y1={0}
                y2={innerH}
                stroke={SPOT_COLOR}
                strokeWidth={1}
              />
              <text
                x={xScale(spot) + 6}
                y={12}
                fontSize={10}
                fill={SPOT_COLOR}
              >
                Price: {spot.toFixed(2)}
              </text>
            </>
          )}

          {callPoints.length >= 2 && (
            <path
              data-testid="call-line"
              d={pathFromPoints(callPoints)}
              stroke={CALL_COLOR}
              strokeWidth={2}
              fill="none"
            />
          )}
          {callPoints.length === 1 && (
            <circle
              data-testid="call-point"
              cx={callPoints[0][0]}
              cy={callPoints[0][1]}
              r={4}
              fill={CALL_COLOR}
            />
          )}
          {putPoints.length >= 2 && (
            <path
              data-testid="put-line"
              d={pathFromPoints(putPoints)}
              stroke={PUT_COLOR}
              strokeWidth={2}
              fill="none"
            />
          )}
          {putPoints.length === 1 && (
            <circle
              data-testid="put-point"
              cx={putPoints[0][0]}
              cy={putPoints[0][1]}
              r={4}
              fill={PUT_COLOR}
            />
          )}
        </g>
      </svg>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd web && npm run test -- CallPutExposureChart
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/greeks/CallPutExposureChart.tsx web/tests/unit/greekCharts/CallPutExposureChart.test.tsx
git commit -m "feat(web): add CallPutExposureChart (two-line SVG)"
```

---

## Slice 6 — Vanna and Charm panels + expiry dropdown

### Task 6.1: Add `ExposureTile` shared tile component

**Files:**
- Create: `web/components/stock/panels/greeks/ExposureTile.tsx`
- Create: `web/tests/unit/greekCharts/ExposureTile.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/greekCharts/ExposureTile.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExposureTile } from "@/components/stock/panels/greeks/ExposureTile";

describe("ExposureTile", () => {
  it("renders label, value, and optional sub-line", () => {
    const { getByText } = render(
      <ExposureTile label="Net Vanna" value="+$1.3M" sub="Long" />,
    );
    expect(getByText("Net Vanna")).toBeTruthy();
    expect(getByText("+$1.3M")).toBeTruthy();
    expect(getByText("Long")).toBeTruthy();
  });

  it("accepts a tone override for the value color", () => {
    const { getByText } = render(
      <ExposureTile label="x" value="-$15.5T" tone="negative" />,
    );
    const v = getByText("-$15.5T");
    expect(v.getAttribute("style") || "").toContain("var(--negative)");
  });
});
```

- [ ] **Step 2: Run test (FAIL)**

```bash
cd web && npm run test -- ExposureTile
```

- [ ] **Step 3: Create the tile component**

```tsx
// web/components/stock/panels/greeks/ExposureTile.tsx
type Tone = "positive" | "negative" | "warning" | "muted" | "default";

const TONE_COLOR: Record<Tone, string> = {
  positive: "var(--positive)",
  negative: "var(--negative)",
  warning: "var(--warning)",
  muted: "var(--text-muted)",
  default: "var(--text-primary)",
};

type Props = {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
};

export function ExposureTile({ label, value, sub, tone = "default" }: Props) {
  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: "10px 14px",
        fontFamily: "var(--font-mono)",
        minWidth: 0,
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          // 22px is the canonical "tile value" size per web/components/CLAUDE.md
          // ("Value: 22px bold mono, primary color" — matches VolMetricsCard +
          // GexLevelTiles patterns).
          fontSize: 22,
          fontWeight: 700,
          color: TONE_COLOR[tone],
          whiteSpace: "nowrap",
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test (PASS)**

```bash
cd web && npm run test -- ExposureTile
```

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/greeks/ExposureTile.tsx web/tests/unit/greekCharts/ExposureTile.test.tsx
git commit -m "feat(web): add ExposureTile (shared 4-up tile for vanna/charm panels)"
```

---

### Task 6.2: Build the `ExpiryDropdown` component

**Files:**
- Create: `web/components/stock/panels/greeks/ExpiryDropdown.tsx`
- Create: `web/tests/unit/greekCharts/ExpiryDropdown.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/greekCharts/ExpiryDropdown.test.tsx
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ExpiryDropdown } from "@/components/stock/panels/greeks/ExpiryDropdown";

describe("ExpiryDropdown", () => {
  it("renders one <option> per expiry with dte annotation", () => {
    const { container } = render(
      <ExpiryDropdown
        options={[
          { value: "2026-05-30", label: "2026-05-30 (9d)" },
          { value: "2026-06-20", label: "2026-06-20 (30d)" },
        ]}
        value="2026-05-30"
        onChange={() => {}}
      />,
    );
    const opts = container.querySelectorAll("option");
    expect(opts).toHaveLength(2);
    expect(opts[0].textContent).toContain("2026-05-30");
    expect(opts[0].textContent).toContain("9d");
  });

  it("fires onChange with the new value", () => {
    const handle = vi.fn();
    const { container } = render(
      <ExpiryDropdown
        options={[
          { value: "a", label: "A" },
          { value: "b", label: "B" },
        ]}
        value="a"
        onChange={handle}
      />,
    );
    const select = container.querySelector("select")!;
    fireEvent.change(select, { target: { value: "b" } });
    expect(handle).toHaveBeenCalledWith("b");
  });
});
```

- [ ] **Step 2: Run test (FAIL)**

```bash
cd web && npm run test -- ExpiryDropdown
```

- [ ] **Step 3: Create the dropdown**

```tsx
// web/components/stock/panels/greeks/ExpiryDropdown.tsx
"use client";

type Props = {
  options: { value: string; label: string }[];
  value: string;
  onChange: (next: string) => void;
};

export function ExpiryDropdown({ options, value, onChange }: Props) {
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 8,
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        color: "var(--text-secondary)",
      }}
    >
      <span
        style={{
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
        }}
      >
        Expiry:
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          background: "var(--bg-panel)",
          color: "var(--text-primary)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          padding: "4px 8px",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
```

- [ ] **Step 4: Run test (PASS)**

```bash
cd web && npm run test -- ExpiryDropdown
```

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/greeks/ExpiryDropdown.tsx web/tests/unit/greekCharts/ExpiryDropdown.test.tsx
git commit -m "feat(web): add ExpiryDropdown client component"
```

---

### Task 6.3: Build `VannaPanel`

**Files:**
- Create: `web/components/stock/panels/greeks/VannaPanel.tsx`
- Create: `web/tests/unit/greekCharts/VannaPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/greekCharts/VannaPanel.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { VannaPanel } from "@/components/stock/panels/greeks/VannaPanel";

const strikeExposures = [
  { strike: "100", expiry: "2026-05-30", dte: 9, call_vanna: "100", put_vanna: "-30", call_charm: "0", put_charm: "0" },
  { strike: "110", expiry: "2026-05-30", dte: 9, call_vanna: "200", put_vanna: "-80", call_charm: "0", put_charm: "0" },
] as never[];

const summary = [{
  expiry: "2026-05-30", dte: 9, spot: "105",
  net_vanna: "190", top_vanna_strike: "110", top_vanna_value: "120",
  delta_shock_1pt_iv: "1.9", vanna_regime: "procyclical",
  vanna_flip: "108",
  vanna_headline: "Long Vanna — IV spikes pressure stock lower via dealer selling",
  vanna_subtitle: "subtitle...",
  net_charm: "0", charm_pin_strike: null, charm_above_sum: "0", charm_below_sum: "0",
  charm_imbalance_pct: null, charm_signal_quality: "weak", charm_flip: null,
  charm_headline: "", charm_subtitle: "",
}] as never[];

describe("VannaPanel", () => {
  it("renders headline, four tiles, expiry dropdown, and both charts", () => {
    const { container, getByText } = render(
      <VannaPanel ticker="TSLA" strikeExposures={strikeExposures} summary={summary} />,
    );
    expect(getByText(/Long Vanna/)).toBeTruthy();
    // 4 tiles
    expect(container.querySelectorAll("[data-testid='exposure-tile']")).toHaveLength(4);
    // dropdown
    expect(container.querySelector("select")).not.toBeNull();
    // both charts
    expect(container.querySelector("path[data-testid='net-line']")).not.toBeNull();
    expect(container.querySelector("path[data-testid='call-line']")).not.toBeNull();
    expect(container.querySelector("path[data-testid='put-line']")).not.toBeNull();
  });

  it("renders an empty state when there's no summary at all", () => {
    const { queryByText } = render(
      <VannaPanel ticker="TSLA" strikeExposures={[]} summary={[]} />,
    );
    expect(queryByText(/not yet available/i)).not.toBeNull();
  });
});
```

- [ ] **Step 2: Tag tiles with the `data-testid` attribute**

Update `ExposureTile.tsx` to add `data-testid="exposure-tile"` on the outer `<div>`. (Done now to keep the panel test runnable.)

- [ ] **Step 3: Run the failing test**

```bash
cd web && npm run test -- VannaPanel
```

Expected: FAIL — module not found.

- [ ] **Step 4: Create `VannaPanel`**

```tsx
// web/components/stock/panels/greeks/VannaPanel.tsx
"use client";

import { useMemo, useState } from "react";
import type { components } from "@/lib/types";
import { fmtMoneyAbbrev } from "@/lib/formatters";
import { CallPutExposureChart } from "./CallPutExposureChart";
import { ExpiryDropdown } from "./ExpiryDropdown";
import { ExposureTile } from "./ExposureTile";
import { NetExposureChart } from "./NetExposureChart";

type StrikeExposureRow = components["schemas"]["StrikeExposureRow"];
type ExposuresSummaryRow = components["schemas"]["ExposuresSummaryRow"];

type Props = {
  ticker: string;
  strikeExposures: StrikeExposureRow[];
  summary: ExposuresSummaryRow[];
};

const toNum = (v: string | number | null | undefined): number | null => {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

// Guards spot values from poisoning charm imbalance / "% from spot" math.
// Mirrors the backend `_safe_spot` rejection of 0/negative/non-finite values.
const toSpot = (v: string | number | null | undefined): number | null => {
  const n = toNum(v);
  return n != null && n > 0 ? n : null;
};

export function VannaPanel({ ticker, strikeExposures, summary }: Props) {
  const sortedSummary = useMemo(
    () => [...summary].sort((a, b) => (a.expiry < b.expiry ? -1 : 1)),
    [summary],
  );
  // Default to the nearest non-expired expiry (dte ≥ 0). Fall back to the
  // earliest summary row when every row is stale or dte is missing.
  const defaultExpiry = useMemo(() => {
    const live = sortedSummary
      .filter((r) => r.dte == null || (r.dte as number) >= 0)
      .sort((a, b) => ((a.dte ?? 99999) as number) - ((b.dte ?? 99999) as number));
    return (live[0] ?? sortedSummary[0])?.expiry ?? null;
  }, [sortedSummary]);
  const [selected, setSelected] = useState<string | null>(defaultExpiry);

  if (sortedSummary.length === 0) {
    return (
      <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
        Vanna data not yet available for this run.
      </div>
    );
  }

  const summaryRow =
    sortedSummary.find((r) => r.expiry === selected) ?? sortedSummary[0];
  const rowsForExpiry = strikeExposures.filter(
    (r) => r.expiry === summaryRow.expiry,
  );

  const netCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      netValue:
        (toNum(r.call_vanna) ?? 0) + (toNum(r.put_vanna) ?? 0),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const callPutCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      callValue: toNum(r.call_vanna),
      putValue: toNum(r.put_vanna),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const dte = summaryRow.dte ?? null;
  const spot = toSpot(summaryRow.spot);  // guards against 0/negative/NaN spot
  const flip = toNum(summaryRow.vanna_flip);
  const netVanna = toNum(summaryRow.net_vanna);
  const tone =
    netVanna == null || Math.abs(netVanna) < 1000
      ? "muted"
      : netVanna > 0
        ? "positive"
        : "negative";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Heading */}
      <div>
        <div
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            color: "var(--accent-vol)",
            textTransform: "uppercase",
          }}
        >
          Volatility · Vanna
        </div>
        <div
          style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)" }}
        >
          {summaryRow.vanna_headline ?? "Vanna positioning"}
        </div>
        {summaryRow.vanna_subtitle && (
          <div style={{ fontSize: 12, color: "var(--text-secondary)", fontStyle: "italic" }}>
            {summaryRow.vanna_subtitle}
          </div>
        )}
      </div>

      {/* Tiles */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        <ExposureTile
          label="Net Vanna"
          value={fmtMoneyAbbrev(netVanna)}
          sub={
            netVanna == null
              ? undefined
              : netVanna > 0 ? "Long" : netVanna < 0 ? "Short" : "Flat"
          }
          tone={tone}
        />
        <ExposureTile
          label="Top vol-sensitive strike"
          value={
            summaryRow.top_vanna_strike != null
              ? `$${Number(summaryRow.top_vanna_strike).toFixed(2)}`
              : "—"
          }
          sub={fmtMoneyAbbrev(toNum(summaryRow.top_vanna_value))}
        />
        <ExposureTile
          label="Δ from +1pt IV"
          value={fmtMoneyAbbrev(toNum(summaryRow.delta_shock_1pt_iv))}
          sub="Dealers sell when IV up"
        />
        <ExposureTile
          label="Vol-shock regime"
          value={summaryRow.vanna_regime ?? "neutral"}
          sub={
            summaryRow.vanna_regime === "procyclical"
              ? "amplifies down moves"
              : summaryRow.vanna_regime === "countercyclical"
                ? "dampens down moves"
                : "limited impact"
          }
          tone={
            summaryRow.vanna_regime === "procyclical"
              ? "negative"
              : summaryRow.vanna_regime === "countercyclical"
                ? "positive"
                : "muted"
          }
        />
      </div>

      {/* Expiry dropdown */}
      <ExpiryDropdown
        options={sortedSummary.map((r) => ({
          value: r.expiry,
          label: `${r.expiry}${r.dte != null ? ` (${r.dte}d)` : ""}`,
        }))}
        value={summaryRow.expiry}
        onChange={setSelected}
      />

      {/* Charts (side-by-side) */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <NetExposureChart
          curve={netCurve}
          spot={spot}
          flipStrike={flip}
          yLabel="Vanna"
          title={`Net Vanna Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
        <CallPutExposureChart
          curve={callPutCurve}
          spot={spot}
          yLabel="Vanna"
          title={`Vanna Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test (PASS)**

```bash
cd web && npm run test -- VannaPanel
```

- [ ] **Step 6: Commit**

```bash
git add web/components/stock/panels/greeks/VannaPanel.tsx web/components/stock/panels/greeks/ExposureTile.tsx web/tests/unit/greekCharts/VannaPanel.test.tsx
git commit -m "feat(web): add VannaPanel (header + 4 tiles + dropdown + charts)"
```

---

### Task 6.4: Build `CharmPanel`

**Files:**
- Create: `web/components/stock/panels/greeks/CharmPanel.tsx`
- Create: `web/tests/unit/greekCharts/CharmPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/greekCharts/CharmPanel.test.tsx
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CharmPanel } from "@/components/stock/panels/greeks/CharmPanel";

const strikeExposures = [
  { strike: "100", expiry: "2026-05-30", dte: 9, call_vanna: "0", put_vanna: "0", call_charm: "-2000", put_charm: "500" },
  { strike: "110", expiry: "2026-05-30", dte: 9, call_vanna: "0", put_vanna: "0", call_charm: "-3000", put_charm: "800" },
] as never[];

const summary = [{
  expiry: "2026-05-30", dte: 9, spot: "105",
  net_vanna: "0", top_vanna_strike: null, top_vanna_value: null,
  delta_shock_1pt_iv: null, vanna_regime: "neutral", vanna_flip: null,
  vanna_headline: "", vanna_subtitle: "",
  net_charm: "-3700", charm_pin_strike: "110", charm_above_sum: "-2200",
  charm_below_sum: "0", charm_imbalance_pct: "1.0",
  charm_signal_quality: "aligned", charm_flip: "108",
  charm_headline: "Mechanical SELL pressure into the close",
  charm_subtitle: "Strongest near $110.00",
}] as never[];

describe("CharmPanel", () => {
  it("renders the SELL pressure headline + 4 tiles + charts", () => {
    const { container, getByText } = render(
      <CharmPanel ticker="TSLA" strikeExposures={strikeExposures} summary={summary} />,
    );
    expect(getByText(/Mechanical SELL/)).toBeTruthy();
    expect(container.querySelectorAll("[data-testid='exposure-tile']")).toHaveLength(4);
    expect(container.querySelector("path[data-testid='net-line']")).not.toBeNull();
    expect(container.querySelector("path[data-testid='call-line']")).not.toBeNull();
    expect(container.querySelector("path[data-testid='put-line']")).not.toBeNull();
  });

  it("renders an empty state when no summary present", () => {
    const { queryByText } = render(
      <CharmPanel ticker="TSLA" strikeExposures={[]} summary={[]} />,
    );
    expect(queryByText(/not yet available/i)).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test (FAIL)**

```bash
cd web && npm run test -- CharmPanel
```

- [ ] **Step 3: Create `CharmPanel.tsx`**

```tsx
// web/components/stock/panels/greeks/CharmPanel.tsx
"use client";

import { useMemo, useState } from "react";
import type { components } from "@/lib/types";
import { fmtMoneyAbbrev } from "@/lib/formatters";
import { CallPutExposureChart } from "./CallPutExposureChart";
import { ExpiryDropdown } from "./ExpiryDropdown";
import { ExposureTile } from "./ExposureTile";
import { NetExposureChart } from "./NetExposureChart";

type StrikeExposureRow = components["schemas"]["StrikeExposureRow"];
type ExposuresSummaryRow = components["schemas"]["ExposuresSummaryRow"];

type Props = {
  ticker: string;
  strikeExposures: StrikeExposureRow[];
  summary: ExposuresSummaryRow[];
};

const toNum = (v: string | number | null | undefined): number | null => {
  if (v == null) return null;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : null;
};

// Guards spot values from poisoning charm imbalance / "% from spot" math.
// Mirrors the backend `_safe_spot` rejection of 0/negative/non-finite values.
const toSpot = (v: string | number | null | undefined): number | null => {
  const n = toNum(v);
  return n != null && n > 0 ? n : null;
};

export function CharmPanel({ ticker, strikeExposures, summary }: Props) {
  const sortedSummary = useMemo(
    () => [...summary].sort((a, b) => (a.expiry < b.expiry ? -1 : 1)),
    [summary],
  );
  // Default to the nearest non-expired expiry (dte ≥ 0); fall back to earliest.
  const defaultExpiry = useMemo(() => {
    const live = sortedSummary
      .filter((r) => r.dte == null || (r.dte as number) >= 0)
      .sort((a, b) => ((a.dte ?? 99999) as number) - ((b.dte ?? 99999) as number));
    return (live[0] ?? sortedSummary[0])?.expiry ?? null;
  }, [sortedSummary]);
  const [selected, setSelected] = useState<string | null>(defaultExpiry);

  if (sortedSummary.length === 0) {
    return (
      <div style={{ color: "var(--text-muted)", fontSize: 12, padding: 16 }}>
        Charm data not yet available for this run.
      </div>
    );
  }

  const summaryRow =
    sortedSummary.find((r) => r.expiry === selected) ?? sortedSummary[0];
  const rowsForExpiry = strikeExposures.filter(
    (r) => r.expiry === summaryRow.expiry,
  );

  const netCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      netValue: (toNum(r.call_charm) ?? 0) + (toNum(r.put_charm) ?? 0),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const callPutCurve = rowsForExpiry
    .map((r) => ({
      strike: toNum(r.strike) ?? NaN,
      callValue: toNum(r.call_charm),
      putValue: toNum(r.put_charm),
    }))
    .filter((p) => Number.isFinite(p.strike))
    .sort((a, b) => a.strike - b.strike);

  const dte = summaryRow.dte ?? null;
  const spot = toSpot(summaryRow.spot);  // guards against 0/negative/NaN spot
  const flip = toNum(summaryRow.charm_flip);
  const netCharm = toNum(summaryRow.net_charm);
  const pin = toNum(summaryRow.charm_pin_strike);
  const imb = toNum(summaryRow.charm_imbalance_pct);
  const aboveSum = toNum(summaryRow.charm_above_sum);
  const belowSum = toNum(summaryRow.charm_below_sum);

  const liveTone =
    netCharm == null || Math.abs(netCharm) < 1000
      ? "muted"
      : netCharm < 0
        ? "negative"
        : "positive";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            color: "var(--accent-vol)",
            textTransform: "uppercase",
          }}
        >
          Timer · Charm
        </div>
        <div style={{ fontSize: 22, fontWeight: 700, color: "var(--text-primary)" }}>
          {summaryRow.charm_headline ?? "Charm pressure"}
        </div>
        {summaryRow.charm_subtitle && (
          <div style={{ fontSize: 12, color: "var(--text-secondary)", fontStyle: "italic" }}>
            {summaryRow.charm_subtitle}
          </div>
        )}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 12,
        }}
      >
        <ExposureTile
          label="Live charm"
          value={fmtMoneyAbbrev(netCharm)}
          sub={
            netCharm == null
              ? undefined
              : netCharm < 0 ? "Sell pressure" : netCharm > 0 ? "Buy pressure" : "Flat"
          }
          tone={liveTone}
        />
        <ExposureTile
          // The displayed value MUST match the same formula the backend used
          // to classify signal_quality (live=net_charm, positioning=above-below;
          // see cards/exposures.py:charm_signal_quality). Showing above+below
          // here would let the tile and the classifier disagree on sign.
          label="Positioning"
          value={fmtMoneyAbbrev(
            aboveSum != null && belowSum != null ? aboveSum - belowSum : null,
          )}
          sub={
            imb != null
              ? `${(imb * 100).toFixed(0)}% imbalance`
              : "—"
          }
        />
        <ExposureTile
          label="Signal quality"
          value={summaryRow.charm_signal_quality ?? "weak"}
          sub={
            summaryRow.charm_signal_quality === "aligned"
              ? "live and positioning align"
              : summaryRow.charm_signal_quality === "mixed"
                ? "live and positioning disagree"
                : "thin signal"
          }
          tone={
            summaryRow.charm_signal_quality === "aligned"
              ? liveTone
              : "muted"
          }
        />
        <ExposureTile
          label="Where it matters"
          value={pin != null ? `$${pin.toFixed(2)}` : "—"}
          sub={
            pin != null && spot != null
              ? `${(((pin - spot) / spot) * 100).toFixed(1)}% from spot`
              : undefined
          }
        />
      </div>

      <ExpiryDropdown
        options={sortedSummary.map((r) => ({
          value: r.expiry,
          label: `${r.expiry}${r.dte != null ? ` (${r.dte}d)` : ""}`,
        }))}
        value={summaryRow.expiry}
        onChange={setSelected}
      />

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <NetExposureChart
          curve={netCurve}
          spot={spot}
          flipStrike={flip}
          yLabel="Charm"
          title={`Net Charm Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
        <CallPutExposureChart
          curve={callPutCurve}
          spot={spot}
          yLabel="Charm"
          title={`Charm Exposure (${dte ?? "?"} DTE) — ${ticker}`}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test (PASS)**

```bash
cd web && npm run test -- CharmPanel
```

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/greeks/CharmPanel.tsx web/tests/unit/greekCharts/CharmPanel.test.tsx
git commit -m "feat(web): add CharmPanel"
```

---

## Slice 7 — Sub-tab switcher + integration into Market Structure

### Task 7.1: Build the `GreekSubTabs` client switcher

**Files:**
- Create: `web/components/stock/panels/greeks/GreekSubTabs.tsx`
- Create: `web/tests/unit/greekCharts/GreekSubTabs.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/greekCharts/GreekSubTabs.test.tsx
import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GreekSubTabs } from "@/components/stock/panels/greeks/GreekSubTabs";

const fakeReport = {
  ticker: "TSLA",
  strike_gex_curve: [],
  market_structure: { spot: "100" },
  market_structure_levels: null,
  strike_exposures: [],
  exposures_summary: [],
} as never;

describe("GreekSubTabs", () => {
  it("renders GEX panel by default", () => {
    const { getByText, queryByText } = render(<GreekSubTabs report={fakeReport} />);
    // Active tab label is GEX
    expect(getByText("GEX").getAttribute("aria-selected")).toBe("true");
    // VannaPanel / CharmPanel placeholders are not visible
    expect(queryByText(/Vanna data not yet available/)).toBeNull();
    expect(queryByText(/Charm data not yet available/)).toBeNull();
  });

  it("switches to Vanna sub-tab on click", () => {
    const { getByText } = render(<GreekSubTabs report={fakeReport} />);
    fireEvent.click(getByText("VANNA"));
    expect(getByText("VANNA").getAttribute("aria-selected")).toBe("true");
    expect(getByText(/Vanna data not yet available/)).toBeTruthy();
  });

  it("switches to Charm sub-tab on click", () => {
    const { getByText } = render(<GreekSubTabs report={fakeReport} />);
    fireEvent.click(getByText("CHARM"));
    expect(getByText(/Charm data not yet available/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run test (FAIL)**

```bash
cd web && npm run test -- GreekSubTabs
```

- [ ] **Step 3: Create the switcher**

```tsx
// web/components/stock/panels/greeks/GreekSubTabs.tsx
"use client";

import { useState } from "react";
import type { components } from "@/lib/types";
import { GexProfileChart } from "@/components/stock/panels/GexProfileChart";
import { CharmPanel } from "./CharmPanel";
import { VannaPanel } from "./VannaPanel";

type Report = components["schemas"]["SingleStockReport"];
type Tab = "GEX" | "VANNA" | "CHARM";
const TABS: Tab[] = ["GEX", "VANNA", "CHARM"];

const ACTIVE_TAB: React.CSSProperties = {
  background: "var(--bg-panel)",
  color: "var(--text-primary)",
  borderBottom: "2px solid var(--accent-vol)",
};
const TAB_BASE: React.CSSProperties = {
  background: "transparent",
  border: "none",
  borderBottom: "2px solid transparent",
  padding: "8px 16px",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  cursor: "pointer",
};

export function GreekSubTabs({ report }: { report: Report }) {
  const [tab, setTab] = useState<Tab>("GEX");

  return (
    <div
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 16,
      }}
    >
      <div
        role="tablist"
        style={{
          display: "flex",
          gap: 4,
          borderBottom: "1px solid var(--border-dim)",
          marginBottom: 16,
        }}
      >
        {TABS.map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            onClick={() => setTab(t)}
            style={tab === t ? { ...TAB_BASE, ...ACTIVE_TAB } : TAB_BASE}
          >
            {t}
          </button>
        ))}
      </div>

      {tab === "GEX" && <GexProfileChart report={report} />}
      {tab === "VANNA" && (
        <VannaPanel
          ticker={report.ticker}
          strikeExposures={report.strike_exposures ?? []}
          summary={report.exposures_summary ?? []}
        />
      )}
      {tab === "CHARM" && (
        <CharmPanel
          ticker={report.ticker}
          strikeExposures={report.strike_exposures ?? []}
          summary={report.exposures_summary ?? []}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test (PASS)**

```bash
cd web && npm run test -- GreekSubTabs
```

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/greeks/GreekSubTabs.tsx web/tests/unit/greekCharts/GreekSubTabs.test.tsx
git commit -m "feat(web): add GreekSubTabs client switcher (GEX | VANNA | CHARM)"
```

---

### Task 7.2: Wire `GreekSubTabs` into `MarketStructureTab` (replaces standalone `GexProfileChart`)

**Files:**
- Modify: `web/components/stock/tabs/MarketStructureTab.tsx`
- Create: `web/tests/e2e/marketStructureGreekSubTabs.spec.ts`

- [ ] **Step 1: Modify `MarketStructureTab.tsx`**

Replace the file contents with:

```tsx
import type { components } from "@/lib/types";
import { api } from "@/lib/api";
import { GexLevelTiles } from "../panels/GexLevelTiles";
import { ExpectedRangeBar } from "../panels/ExpectedRangeBar";
import { DirectionalBiasPanel } from "../panels/DirectionalBiasPanel";
import { MarketStructureHistoryTable } from "../panels/MarketStructureHistoryTable";
import { MaxPainTable } from "../panels/MaxPainTable";
import { GreekSubTabs } from "../panels/greeks/GreekSubTabs";

type Report = components["schemas"]["SingleStockReport"];

export async function MarketStructureTab({ report }: { report: Report }) {
  let historyRows: components["schemas"]["StockHistoryRow"][] = [];
  try {
    const h = await api.stockHistory(report.ticker);
    historyRows = h.rows;
  } catch {
    historyRows = [];
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <GexLevelTiles report={report} />
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 12,
        }}
      >
        <ExpectedRangeBar report={report} />
        <DirectionalBiasPanel report={report} history={historyRows} />
      </div>
      <GreekSubTabs report={report} />
      <MarketStructureHistoryTable rows={historyRows} />
      <MaxPainTable rows={report.max_pain_rows} />
    </div>
  );
}
```

The `GexProfileChart` import is removed because it is now rendered inside `GreekSubTabs`.

- [ ] **Step 2: Run web unit + typecheck**

```bash
cd web && npm run typecheck && npm run test && cd ..
```

Expected: PASS.

- [ ] **Step 3: Write the e2e test**

Create `web/tests/e2e/marketStructureGreekSubTabs.spec.ts`:

```typescript
import { expect, test } from "@playwright/test";

// /stock/[ticker]/page.tsx redirects to /stock/[ticker]/market-structure,
// so navigating straight to the canonical URL avoids relying on the TabBar
// link selector (which could break if the label/href changes).

test.describe("Market Structure greek sub-tabs", () => {
  test("default tab is GEX and shows GEX Profile", async ({ page }) => {
    await page.goto("/stock/TSLA/market-structure");
    await expect(page.getByText(/GEX Profile/)).toBeVisible();
    await expect(page.getByRole("tab", { name: "GEX" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("switching to VANNA reveals the Vanna headline and two charts", async ({ page }) => {
    await page.goto("/stock/TSLA/market-structure");
    await page.getByRole("tab", { name: "VANNA" }).click();
    // Either headline OR the empty state — both are valid depending on data.
    await expect(
      page.locator("text=/Long Vanna|Short Vanna|Neutral Vanna|Vanna data not yet available/")
    ).toBeVisible();
  });

  test("switching to CHARM reveals charm headline / empty state", async ({ page }) => {
    await page.goto("/stock/TSLA/market-structure");
    await page.getByRole("tab", { name: "CHARM" }).click();
    await expect(
      page.locator("text=/Mechanical (SELL|BUY)|Limited charm|Charm data not yet available/")
    ).toBeVisible();
  });
});
```

- [ ] **Step 4: Run the e2e tests (requires running app)**

Start the full stack (API + web) and wait for both to be reachable. Use `scripts/dev.sh`'s own pidfile pattern or boot the two processes explicitly so cleanup is reliable:

```bash
uv run uvicorn uw_scan.api.server:app --port 8400 --no-access-log &
API_PID=$!
(cd web && npm run dev -- --port 3001) &
WEB_PID=$!
for _ in {1..40}; do
  curl -sf http://localhost:8400/openapi.json > /dev/null \
    && curl -sf http://localhost:3001 > /dev/null && break
  sleep 0.5
done

cd web && npm run test:e2e -- marketStructureGreekSubTabs && cd ..

kill "$WEB_PID" "$API_PID" 2>/dev/null || true
wait "$WEB_PID" "$API_PID" 2>/dev/null || true
```

Expected: PASS for all 3 cases.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/tabs/MarketStructureTab.tsx web/tests/e2e/marketStructureGreekSubTabs.spec.ts
git commit -m "feat(web): wire GreekSubTabs into MarketStructureTab"
```

---

### Task 7.3: Full-suite regression sweep

- [ ] **Step 1: Run all Python tests**

```bash
uv run pytest -q
```

Expected: all green, including new tests across slices 1–4.

- [ ] **Step 2: Run all web tests + typecheck + lint**

```bash
cd web && npm run typecheck && npm run lint && npm run test && cd ..
```

Expected: all green.

- [ ] **Step 3: Manual smoke (visual)**

Boot the stack and click through the new sub-tabs:

```bash
bash scripts/dev.sh
```

Open `http://localhost:3001/stock/TSLA` → Market Structure → click `VANNA`, change expiry from the dropdown, confirm the curves redraw. Repeat for `CHARM`.

- [ ] **Step 4: Open a PR**

```bash
git push -u origin feat/vanna-charm-market-structure
gh pr create --title "Vanna & Charm sub-tabs inside Market Structure" --body "$(cat <<'EOF'
## Summary
- Adds VANNA and CHARM sub-tabs inside the per-ticker Market Structure tab, with the existing GEX profile chart now living inside a peer GEX sub-tab.
- Each panel: auto-generated headline narrative + 4 tiles + expiry dropdown + Net curve and Call/Put split curve.
- Backend: new `exposures_summary` table (migration 051), derivers in `cards/exposures.py`, additive fields on `SingleStockReport`. Wired into `cockpit_daily_snapshot` and `pipeline.py`.
- Frontend: hand-rolled SVG line charts (no chart library) under `web/components/stock/panels/greeks/`.

## Test plan
- [ ] `uv run pytest` is green
- [ ] `npm run typecheck && npm run lint && npm run test` is green
- [ ] Playwright e2e `marketStructureGreekSubTabs.spec.ts` is green
- [ ] Manual smoke: visit /stock/TSLA → Market Structure → switch through GEX | VANNA | CHARM, change expiry, confirm charts redraw
EOF
)"
```

> Do NOT merge — the user opens PRs but reviews and merges manually per repo policy. Wait for review.

---

## Self-review notes

- **Spec coverage:** every section of the spec maps to at least one task. Migration → 1.2; models → 1.1, 4.1; derivers → 2.1–2.3; persistence → 3.1, 3.2; report assembler → 4.1; gen:types → 4.2; charts → 5.2, 5.3; tiles → 6.1; dropdown → 6.2; panels → 6.3, 6.4; sub-tabs → 7.1; integration → 7.2; QA → 7.3.
- **Placeholder scan:** no "TBD", no "similar to Task N" without repeated code, every code block is complete.
- **Type consistency:** `ExposuresSummaryRow`, `StrikeExposureRow`, `build_summary_rows`, `upsert_exposures_summary`, `fetch_strike_exposures`, `fetch_exposures_summary` (new list-returning) all use the same names across tasks. Renamed `fetch_exposures_aggregate` is consistent.
- **Sign-convention note carried through:** `net = call + put`, `ONE_VOL_POINT = 0.01`, neutral threshold 1e3 — referenced in deriver code and test fixtures.
- **Out-of-scope items called out** in spec; not creeping into tasks.

### Fixes applied in this pass

**Self-review pass (6 fixes):**

1. **Rename / caller mismatch (commit-boundary regression risk).** `fetch_exposures_summary → fetch_exposures_aggregate` originally renamed in Slice 3.1 but the only caller (`reports/single_stock.py:127`) wasn't updated until Slice 4.1, so the Slice 3 commit would ship a broken codebase. Moved the caller update into Slice 3.1 step 5b; Task 4.1 step 3 now notes that the rename is already wired.
2. **Ghost `_spot_decimal(market_data)` helper.** Task 3.2 step 3 referenced a helper that was never defined and contradicted the surrounding "inline the local" instruction. Replaced with `repo.get_intraday_quote(ticker)` fetched once before the expiry loop (matching `_persist_option_chain_per_strike`'s existing pattern at line 197–198).
3. **Ghost `market_structure_spot` variable in `pipeline.py`.** Tightened in the tribunal pass (item P2 below).
4. **Wrong test fixture name.** Integration tests originally used a bare `postgresql` fixture; this project's `tests/integration/conftest.py` exposes named fixtures (`seeded_db_empty_cards`, `seeded_db_with_cards`). Tasks 1.2, 3.1, 3.2, 4.1 now use `seeded_db_empty_cards: Repository` and rely on the conftest's `_reset_and_migrate` for migration setup.
5. **Wrong report-assembler function name.** Task 4.1 originally called `build_single_stock_report`. The actual name is `assemble_single_stock_report(ticker, run_id, repo)` (`src/uw_scan/reports/single_stock.py:417`). Updated.
6. **Fragile background-process management.** `bash scripts/dev.sh & ... kill %1` only kills the parent shell, leaking children. Tasks 4.2 and 7.2 now capture explicit PIDs from `uvicorn` and `npm run dev`, poll for readiness, and `kill "$PID"` + `wait` on cleanup.

**Tribunal pass — Codex + Gemini + Claude consensus (12 fixes):**

- **P1 (Codex ISSUE-1, transaction boundary).** `upsert_exposures_summary` originally called `self._conn.commit()`. Every other insert/upsert in `options.py` leaves commit to the caller, because `_snapshot_ticker` owns commit-on-success / rollback-on-failure (`cockpit_daily_snapshot.py:78,103`). Internal commit removed with an explicit warning.
- **P2 (Codex ISSUE-2 + CL-4, spot in `pipeline.py`).** Originally `spot=None` was passed in the pipeline path, which is the watchlist-scan code that powers most stock-detail pages. Now reads `repo.get_intraday_quote(ticker)` with `fetch_realized_vol_latest(ticker)["price"]` fallback — same source `_build_market_structure` uses.
- **P3 (Codex ISSUE-3, missing real worker-wiring test).** Added Task 3.2 Step 4b: a monkeypatched test that drives the snapshot helper and asserts `upsert_exposures_summary.called`. The original Step 1 test only exercised the assembly contract.
- **P4 (Codex ISSUE-4, `__module__` assertion).** Models pass through `_preserve_public_module` which rewrites `__module__` to `"uw_scan.models"` (the public path), not `"uw_scan.models.scanner"`. Test assertion corrected.
- **P5 (Codex ISSUE-5, `_StubRepo` not updated by rename).** `tests/unit/test_report_assembly.py:115` had a stub method named `fetch_exposures_summary` returning the aggregate dict. Renamed in step 5c so the unit suite doesn't break at the Slice 3.1 commit boundary.
- **P6 (Codex ISSUE-6, single-point curves).** `finiteDomain` returns `null` for <2 points → NetExposureChart used to show empty state for a 1-point curve. Spec requires a point marker + spot line. Component now synthesizes a small symmetric window around the lone point and renders a `<circle data-testid="net-point">`. New unit test added.
- **P7 (Codex ISSUE-7, default expiry).** Vanna/Charm panels originally defaulted to `sortedSummary[0]?.expiry`, which on stale data picks a negative-DTE row. Now filters `dte >= 0` (or null) first, sorts by DTE ascending, falls back to earliest when nothing live exists.
- **P8 (Codex ISSUE-8, flip ignores spot).** Vanna/charm flip functions accepted `spot` and silently ignored it. Spec says lowest sign-flip ≥ spot, fallback to lowest overall. Implementation rewritten to collect all flips then apply the spot rule. Two new tests added for the rule + fallback path.
- **P9 (Codex ISSUE-9, duplicate-PK risk on mixed DTE).** `build_summary_rows` originally grouped by `(expiry, dte)`. The PK is `(run_id, ticker, expiry)`, so any mixed-DTE same-expiry rows would emit duplicate PKs. Now groups by `expiry` only and picks min non-null `dte`. New unit test added.
- **P10 (Codex ISSUE-10, run_id type).** Migration 051 declared `run_id INTEGER`. `scan_runs.run_id` is `BIGSERIAL`; every other run-keyed table uses `BIGINT REFERENCES scan_runs(run_id) ON DELETE CASCADE`. Migration corrected.
- **P11 (Codex ISSUE-11, OpenAPI snapshot path).** Plan said `tests/unit -k openapi`. Actual snapshot is `tests/integration/api/test_openapi_snapshot.py` with the JSON checked in at `tests/integration/api/openapi.snapshot.json`. Verification command + regeneration recipe added.
- **P12 (Codex ISSUE-12, Positioning tile formula mismatch).** Backend's `charm_signal_quality` classifies on `positioning = above_sum - below_sum`. FE Positioning tile was showing `above_sum + below_sum`, so the displayed value could disagree in sign with the `aligned`/`mixed` classification. Tile formula corrected.

**Gemini-only accepted:**

- **G1 (Gemini ISSUE-5, circular import speculation).** The local `from uw_scan.models import ExposuresSummaryRow` inside `build_summary_rows` was unnecessary — `cards/gex.py` already does the same import at the top level without issue. Moved to a top-level import.
- **G2 (Gemini ISSUE-7, tile font size).** `web/components/CLAUDE.md` defines the canonical tile-value size as 22px. Changed from 18 to 22 with a comment citing the convention.

**Claude-only accepted:**

- **C1 (CL-1, `_to_decimal` consistency).** Verbose `Decimal(str(row[x])) if row.get(x) is not None else None` (×17) replaced with `_to_decimal(row.get(x))` to match the rest of `single_stock.py`.
- **C2 (CL-2, e2e redundant click).** E2E tests now navigate straight to `/stock/TSLA/market-structure` instead of going to `/stock/TSLA` (which redirects) then clicking the TabBar link.

**Dismissed (Gemini-only, weight 0.5):**

- Gemini ISSUE-2 (repo fetchers should return models, not dicts) — codebase pattern in `fetchers.py` is mixed; many fetchers return `list[dict]` and the assembler converts. Out of scope.
- Gemini ISSUE-3 (`strict=True` in `zip`) — style preference; existing code uses `strict=False`.
- Gemini ISSUE-4 (`GexProfileChart` prop drilling) — pre-existing API; refactoring it is out of scope for this plan.
- Gemini ISSUE-6 (refactor `_persist_option_chain_per_strike` to return spot) — minor efficiency win (one extra `get_intraday_quote` per ticker per snapshot); flagged as a deferred follow-up.

**Adversarial pass — Codex challenge mode (8 actionable fixes + 2 deferred + 2 informational):**

- **A1 (ATTACK-8, mid-slice method shadowing).** Slice 3.1 originally added a new `fetch_exposures_summary` in Step 4, then renamed the old one in Step 5. Python class-body resolution shadows the first definition with the second, so between substeps `_build_market_structure` would crash with `'list' has no attribute 'get'`. Steps reordered: rename + caller-update + stub-update happen FIRST (Step 3), then the new fetcher is added (Step 5). One indivisible commit covers both.
- **A2 (ATTACK-9, worker test references non-existent helper).** The Codex-tribunal-added Step 4b test called `job._persist_greeks_per_expiry(...)`, but `cockpit_daily_snapshot.py` has no such helper — the per-expiry loop is inline. Test now uses `getattr(...)` so it gracefully falls back to driving `_snapshot_ticker` directly, AND Step 3 of Task 3.2 now instructs the engineer to extract the helper as a small refactor (preferred). The wiring-test file is added to the commit explicitly.
- **A3 (ATTACK-5, CallPutExposureChart blanks on one-strike data).** The single-point fallback in Slice 5.2 covered NetExposureChart only — CallPutExposureChart still gated on `finiteDomain(...) → null` for <2 points and showed empty state. Component now mirrors NetExposureChart: synthesizes a small window around the lone strike and renders `<circle data-testid="call-point">` / `put-point` markers.
- **A4 (ATTACK-4, zero/negative spot poisons math).** Backend `_safe_spot` helper (in both `cockpit_daily_snapshot.py` and `pipeline.py`) rejects `None`, non-finite, and `≤ 0` values before passing to the deriver. Frontend `toSpot()` helper enforces the same `> 0` guard in `VannaPanel` and `CharmPanel` so "% from spot" never renders as `Infinity%`.
- **A5 (ATTACK-3, cockpit spot has no fallback).** Cockpit wiring originally trusted `repo.get_intraday_quote(ticker)` blindly — a missing or stale quote produced silently wrong charm imbalance. Now falls back to `repo.fetch_realized_vol_latest(ticker)["price"]` (same source `_persist_option_chain_per_strike` already uses).
- **A6 (ATTACK-2, spec disagrees with corrected migration).** Spec still showed `run_id INTEGER NOT NULL` with no FK; plan's migration uses `BIGINT REFERENCES scan_runs(run_id) ON DELETE CASCADE`. Spec patched to match — agents reading the spec directly won't ship an inconsistent migration.
- **A7 (ATTACK-12, stale FK comment in test seed helper).** Test docstring said "exposures_summary has no FK" — false after A6. Now correctly notes the FK + CASCADE behavior.
- **A8 (ATTACK-10, `_to_decimal(row.get("strike"))` Pydantic crash).** `StrikeExposureRow.strike` is non-optional `Decimal`; `_to_decimal(None)` returns `None`, which raises `ValidationError` and aborts the whole report assembly. Required fields now use `Decimal(str(row["strike"]))` with a defensive `if row.get("strike") is not None` filter in the comprehension so one bad row drops out instead of crashing the report.

**Adversarial pass — partial fixes / verification notes:**

- **A9 (ATTACK-6 + ATTACK-7, UW vanna sign + unit convention not verified).** Added a verification preamble to Slice 2 listing the two assumptions (`net_vanna > 0` → "Long Vanna / procyclical"; `vanna × 0.01` → 1-pt-IV delta shock) plus two concrete verification paths (sample payload check against UW UI labels; numerical scale check vs UW UI). If verification fails, the fix is narrative-string-only and doesn't change deriver logic.

**Adversarial pass — acknowledged but out of plan scope:**

- **A10 (ATTACK-1, pipeline rollback is already broken pre-plan).** `set_strike_gex_curve` commits mid-function before this plan's upsert runs, so existing failure paths can leave half-rolled-back state regardless of our new upsert. The plan inherits this pre-existing issue; fixing it requires moving every internal commit out of repository helpers and into the worker. Flagged for a follow-up storage-cleanup spec.
- **A11 (ATTACK-11, `latest_run_id` can pick cockpit runs over full-stock runs).** `latest_run_id` only filters out `flow_data_refresh` notes; cockpit snapshot rows can shadow full single-stock runs for SPX/SPY/QQQ/IWM. Pre-existing issue this plan amplifies (now Vanna/Charm rows can come from a cockpit run with no flow/max-pain context). Flagged for a follow-up `run_kind` column / filter change.

The full adversarial transcript is in the conversation; both A10 and A11 should be tracked in a follow-up ticket before this plan ships to prod.
