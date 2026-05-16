# Repository.py Split — PR 1 of 3 (Leaf Modules)

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Each task is independently shippable.

**Goal:** Decompose the 5173-line `src/uw_scan/storage/repository.py` into focused per-domain mixin modules, starting with the 8 leaf domains. Pure code move + import update — no behavior changes.

**Architecture:** Mixin pattern — `repository.py` stays as the assembled shell (`class Repository(_AuditMixin, _FlowMixin, …, _BaseMixin): pass` — `_BaseMixin` LAST owns `__init__`/`conn`) so all 30+ caller import paths (`from uw_scan.storage.repository import Repository`) keep working unchanged. Each domain mixin contains a cohesive method set; no mixin defines `__init__`. Dataclass row types move to `storage/rows.py` and are re-exported from `repository.py` for backward compat.

**Tech Stack:** Python 3.13, no new dependencies. The split is purely structural; pytest is the verification gate (346+ tests must stay green).

## Plan revisions from `/codex-review`

Initial draft was reviewed by Codex + Claude before any code was written. 13 issues raised, all consensus or self-verified. Revisions applied:

1. **CRITICAL — Task 1 line ranges wrong.** Originally claimed `WatchlistRow` occupied lines 26-264 (because the file dividers visually run that long). Reality: WatchlistRow is 26-35; 37-264 are cockpit-domain module helpers that must stay per Decision 2. Plan rewritten to move dataclasses by class name, not by line range.
2. **CRITICAL — Task 2 missing `redact_params`/`status_family_for`.** Both are externally imported by `sources/ohlc.py`, `api/client.py`, `tests/unit/storage/test_provider_usage_helpers.py`. Added to `_helpers.py` move list with explicit re-export.
3. **CRITICAL — Task 2 `provider_day_bounds` crash.** Needs `_PROVIDER_DAY_TZ` constant (line 515) moved too, plus `ZoneInfo` + `timedelta` imports. Template fixed.
4. **CRITICAL — Task 6 hidden method.** `get_pcr_history_30d_ago` at line 4452 sits inside the `append_pcr_history` range. Added explicitly to the move table.
5. **CRITICAL — Task 8 health constants/imports.** `_RECORD_HEALTH_TIMESTAMP_COLUMNS`, `_RECORD_HEALTH_TICKER_COLUMNS` (388-389) + `math.ceil` + `psql.SQL` + `Iterable` added to the move/imports list.
6. **CRITICAL — Task 7 missing `logger`.** `mark_job_done`/`mark_job_failed` use `logger.warning`. Jobs mixin gets its own `logger = logging.getLogger(__name__)`.
7. **CRITICAL — Task 9 script breakage.** `scripts/backfill_flow_footprint.py` imports `_flow_footprint_label` + `_aggressor_label_confidence` from `uw_scan.storage.repository`. Re-export from repository.py required (NOT just internal move).
8. **CRITICAL — Task 9 flow.py imports.** Added `Iterable`, `Counter`, `Decimal`, `ZoneInfo`, `datetime`.
9. **IMPORTANT — bare `pytest`** in Tasks 5-9 changed to `uv run pytest` per project standing rule.
10. **IMPORTANT — Task 4 test path** changed from non-existent `tests/integration/sources/` to `tests/integration/test_repository_real_pg.py`.
11. **IMPORTANT — MRO examples** reorganized: `_BaseMixin` always LAST in inheritance (matches the actual MRO requirement that domain mixins shadow base resolution).
12. **MINOR — `_flow_alert_trade_date`** moved from `_FlowMixin` to module-level function in `flow.py` (doesn't use `self`).
13. **MINOR — WatchlistCardRow line range** corrected from 409-523 to 409-513.

## Why we're doing this now

Per the new "Module size budget" standing rule (`CLAUDE.md`/`AGENTS.md`, just committed): repository.py reached 5173 lines because the line was never drawn. The 3-PR plan from `docs/reviews/2026-05-16-backend-modularization-and-reuse.md` decomposes by domain seam.

**This PR (1 of 3):** extract the 8 leaf modules. ~32 methods + 12 row types + 2 utility functions moved. After PR-1 lands, `repository.py` shrinks from 5173 lines to ~4100 lines. PR-2 and PR-3 land the bigger domains (external_api, volatility, options, fetchers) in follow-up worktrees.

## Mixin pattern primer

Each domain module exports a single mixin class:

```python
# storage/audit.py
from __future__ import annotations
import psycopg
from typing import Any
from psycopg.types.json import Jsonb


class _AuditMixin:
    """Audit + raw payload writes. Mixed into Repository in repository.py."""

    # Type hints for attributes the mixin uses (set by _BaseMixin.__init__):
    _conn: psycopg.Connection
    _schema: str

    def insert_audit_row(self, ...) -> int:
        ...

    def insert_raw_payload(self, audit_id: int, payload: dict | list) -> int:
        ...
```

And the assembled shell:

```python
# storage/repository.py (post-split, ~100 lines)
from .rows import (
    WatchlistRow, DailyOhlcRow, IntradayQuoteRow, ...,  # re-export for callers
)
from ._base import _BaseMixin
from ._helpers import (
    _PROVIDER_DAY_TZ,
    _REDACTED_PARAM_KEYS,
    _d,
    _nullable_float,
    _nullable_int,
    provider_day_bounds,
    redact_params,
    status_family_for,
)
# External callers may import provider_day_bounds, redact_params, status_family_for
# from this module — they stay re-exported (see __all__ below).
from .audit import _AuditMixin
from .flow import _FlowMixin
from .scan_outputs import _ScanOutputsMixin
from .market_data import _MarketDataMixin
from .jobs import _JobsMixin
from .health import _HealthMixin


class Repository(
    _AuditMixin,
    _FlowMixin,
    _ScanOutputsMixin,
    _MarketDataMixin,
    _JobsMixin,
    _HealthMixin,
    _BaseMixin,  # MUST be last — owns __init__/conn; domain mixins shadow it
    # PR-2 will add: _ExternalApiMixin, _VolatilityRawMixin, _OptionsMixin,
    #                _ScanRunsMixin, _ScanResultsMixin, _WatchlistMixin
    # PR-3 will add: _FetchersMixin, _TradeInsightsAiMixin, _VolatilityV2Mixin
):
    """Per-domain methods are defined on mixins; this class just assembles them.
    See docs/superpowers/plans/2026-05-16-repository-split-pr1.md for the split
    plan and storage/CLAUDE.md for module conventions."""
    pass


# PR-2/PR-3 will move the remaining ~125 methods out of repository.py.
# Until then, the methods not yet extracted live directly on Repository above
# (between the imports and the class definition — they'll move to dedicated
# mixin files in subsequent PRs).
```

**MRO note:** `_BaseMixin` MUST be LAST in the inheritance order so domain mixins resolve their methods first via Python's left-to-right MRO. `_BaseMixin.__init__` is the ONLY `__init__` in the chain (domain mixins must not define their own); when `Repository(conn, schema=...)` is called, Python walks left-to-right past domain mixins (which have no `__init__`), reaches `_BaseMixin.__init__`, and calls it. Each mixin uses `self._conn` and `self._schema` set there. Domain mixins declare type hints (`_conn: psycopg.Connection`) for tooling but do not assign — assignment happens in `_BaseMixin.__init__`.

## Task order (low → high blast radius)

1. **rows.py** — no methods touched; pure dataclass relocation + re-exports
2. **_helpers.py** — 2 functions; trivial
3. **_base.py** — extract `__init__`, `conn` property; foundation for mixins
4. **audit.py** — 2 methods; simplest mixin
5. **scan_outputs.py** — 2 methods
6. **market_data.py** — 9 methods (includes new etf_aum methods)
7. **jobs.py** — 7 methods
8. **health.py** — 7 methods
9. **flow.py** — 3 methods + 2 module helpers

## File-level invariants (apply to every task)

- **One mixin class per file.** Name: `_<Domain>Mixin`.
- **`from __future__ import annotations`** at top of every new file (consistent with existing convention).
- **No business logic moves.** Methods are byte-identical except for `self` → leading whitespace adjustments.
- **Re-exports preserved.** Dataclasses imported from `repository.py` by any caller must still be importable from there post-split.
- **Run `uv run pytest tests/integration/storage/ tests/unit/storage/ -v` after each task.** Full green required before commit.
- **No `git add -A`.** Stage specific files only — avoids accidentally including unrelated state.

---

## Task 1 — rows.py: extract 12 dataclass row types + WatchlistCardRow

**Files:**
- Create: `src/uw_scan/storage/rows.py`
- Modify: `src/uw_scan/storage/repository.py` (delete moved classes, add import + re-export block)

**Why first:** Zero method moves. Easiest to verify. All later tasks reference these row types.

**Classes moved (current line ranges in repository.py — short, NOT contiguous):**

| Class | Current lines |
|---|---|
| `WatchlistRow` | 26-35 |
| `DailyOhlcRow` | 266-278 |
| `IntradayQuoteRow` | 279-286 |
| `PcrHistoryRow` | 287-294 |
| `JobRow` | 295-307 |
| `RescanQueueSummaryRow` | 308-315 |
| `ExternalApiUsageSummary` | 316-328 |
| `ExternalApiBreakdownRow` | 329-340 |
| `ThroughputSummaryRow` | 341-349 |
| `ExternalApiRequestRow` | 350-374 |
| `RecordHealthRow` | 375-407 |
| `WatchlistCardRow` | 409-513 (incl. `_LIST_FIELDS`, `from_db`, `from_list_row`, `__getattr__`, `to_dict`) |

**CRITICAL: do NOT delete by line range.** Lines 37-264 (between `WatchlistRow` and `DailyOhlcRow`) contain cockpit-domain module helpers (`_row_for_date`, `_iv_delta_5d`, `_pin_candidate`, `_pin_distance_sigma`, `_median`, `_sum_optional`, `_sign_label`, `_vanna_conditional_reading`, `_charm_regime`, `_oi_change_bias`, `_flow_footprint_label`, `_aggressor_label_confidence`, `_vrp_sign_flip_status_for_db`, `_vrp_sign_flip_status_from_db`) that must STAY in repository.py per Decision 2 (they'll move with their domain modules in PR-2/PR-3, except `_flow_footprint_label` and `_aggressor_label_confidence` which move in Task 9). Delete by class definition — find each `@dataclass(frozen=True)` / `class WatchlistCardRow:` and delete from there to the next blank line before the next top-level definition.

- [ ] **Step 1.1: Read current rows + their imports**

```bash
sed -n '1,25p' src/uw_scan/storage/repository.py  # see what imports the rows need
```

Capture the import list (`from __future__`, `from dataclasses import dataclass`, `from datetime import datetime`, `from decimal import Decimal`, `from typing import Any`, plus `models` if any row references it).

- [ ] **Step 1.2: Create `src/uw_scan/storage/rows.py`**

```python
"""Frozen dataclasses + WatchlistCardRow used by the Repository methods.

Moved from repository.py during the PR-1 split (see
docs/superpowers/plans/2026-05-16-repository-split-pr1.md). All row types
are re-exported from repository.py for backward compat with existing callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class WatchlistRow:
    # ... copied verbatim from repository.py ...


# ... all 11 other dataclasses + WatchlistCardRow ...
```

- [ ] **Step 1.3: Replace classes in repository.py with imports + re-exports**

In `repository.py`, delete each of the 12 class definitions individually (find each `@dataclass(frozen=True)` / `class WatchlistCardRow:` and remove that class only — DO NOT delete by line range, since the file has cockpit module helpers interleaved between dataclasses that must stay). At the top of the file (just after the existing imports), add:

```python
# All row types live in rows.py. Re-exported here so existing callers
# (`from uw_scan.storage.repository import JobRow`) keep working.
from .rows import (
    DailyOhlcRow,
    ExternalApiBreakdownRow,
    ExternalApiRequestRow,
    ExternalApiUsageSummary,
    IntradayQuoteRow,
    JobRow,
    PcrHistoryRow,
    RecordHealthRow,
    RescanQueueSummaryRow,
    ThroughputSummaryRow,
    WatchlistCardRow,
    WatchlistRow,
)

__all__ = [
    "Repository",
    "DailyOhlcRow",
    "ExternalApiBreakdownRow",
    "ExternalApiRequestRow",
    "ExternalApiUsageSummary",
    "IntradayQuoteRow",
    "JobRow",
    "PcrHistoryRow",
    "RecordHealthRow",
    "RescanQueueSummaryRow",
    "ThroughputSummaryRow",
    "WatchlistCardRow",
    "WatchlistRow",
]
```

- [ ] **Step 1.4: Run tests**

```bash
set -a; source ../../../.env; set +a
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/ tests/unit/storage/ -v 2>&1 | tail -10
```

Expected: full green. Any `ImportError` or `AttributeError` on a row type means a caller used a different name than my re-export list — add to `__all__`.

- [ ] **Step 1.5: Commit**

```bash
git add src/uw_scan/storage/rows.py src/uw_scan/storage/repository.py
git commit -m "refactor(storage): extract row dataclasses to rows.py

PR-1 of the 3-PR repository.py split (docs/reviews/2026-05-16-backend-
modularization-and-reuse.md). Pure move + re-export. All 12 dataclass row
types + WatchlistCardRow live in storage/rows.py; repository.py re-exports
them so 'from uw_scan.storage.repository import JobRow' still works."
```

---

## Task 2 — _helpers.py: extract pure utility helpers (REVISED per codex-review)

**Files:**
- Create: `src/uw_scan/storage/_helpers.py`
- Modify: `src/uw_scan/storage/repository.py` (delete the helpers + module constants they depend on, import them back at the top)

**Functions and constants moved:**

| Symbol | Current lines | External-facing? |
|---|---|---|
| `_PROVIDER_DAY_TZ` constant | 515 | (used by `provider_day_bounds`) |
| `_REDACTED_PARAM_KEYS` constant | 516-522 | (used by `redact_params`) |
| `_d` function | 525-528 | internal |
| `provider_day_bounds` function | 530-537 | YES — `api/routers/health.py`, `api/routers/provider_usage.py`, `tests/unit/storage/test_provider_usage_helpers.py` |
| `status_family_for` function | 539-553 | YES — `sources/ohlc.py`, `api/client.py`, `tests/unit/storage/test_provider_usage_helpers.py` |
| `redact_params` function | 555-565 | YES — `sources/ohlc.py`, `api/client.py`, `tests/unit/storage/test_provider_usage_helpers.py` |
| `_nullable_int` function | 567-571 | internal |
| `_nullable_float` function | 573-577 | internal |

**External re-export critical.** All 3 external-facing functions (`provider_day_bounds`, `status_family_for`, `redact_params`) must remain importable from `uw_scan.storage.repository` — break this and 5+ callers fail.

Cockpit-specific helpers (`_pin_candidate`, `_vanna_conditional_reading`, `_charm_regime`, `_oi_change_bias`, `_vrp_sign_flip_status_*`, etc., lines 37-264) stay in `repository.py`. They move with their domain modules in PR-2.

- [ ] **Step 2.1: Create `src/uw_scan/storage/_helpers.py`**

```python
"""Pure-utility helpers used by Repository methods.

Some of these are externally importable from `uw_scan.storage.repository`
(provider_day_bounds, status_family_for, redact_params) and stay re-exported
there for backward compat. Internal-only helpers (_d, _nullable_int,
_nullable_float) are also here for cohesion.

Moved from repository.py during the PR-1 split (docs/superpowers/plans/
2026-05-16-repository-split-pr1.md). Cockpit-specific helpers
(_pin_candidate, _vanna_conditional_reading, _charm_regime, etc.) stay in
repository.py for PR-1 and will move with their domain modules in PR-2.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo


_PROVIDER_DAY_TZ = ZoneInfo("America/New_York")

_REDACTED_PARAM_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "auth",
    "token",
}


def _d(value: Decimal | None) -> Any:
    """psycopg handles Decimal natively; keep this for symmetry with other casters."""
    return value


def provider_day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    # ... copied verbatim from repository.py:530-537 ...


def status_family_for(status_code: int | None, *, transport_error: bool = False) -> str:
    # ... copied verbatim from repository.py:539-553 ...


def redact_params(params: dict[str, object] | None) -> dict[str, object]:
    # ... copied verbatim from repository.py:555-565 ...


def _nullable_int(value: Any) -> int | None:
    # ... copied verbatim from repository.py:567-571 ...


def _nullable_float(value: Any) -> float | None:
    # ... copied verbatim from repository.py:573-577 ...
```

- [ ] **Step 2.2: Replace in repository.py**

Delete the 5 functions + 2 module constants (`_PROVIDER_DAY_TZ`, `_REDACTED_PARAM_KEYS`) listed above. Add to the imports block near the top:

```python
from ._helpers import (
    _PROVIDER_DAY_TZ,    # cockpit code may still reference it; keep importable
    _REDACTED_PARAM_KEYS,
    _d,
    _nullable_float,
    _nullable_int,
    provider_day_bounds,
    redact_params,
    status_family_for,
)
```

Add `provider_day_bounds`, `redact_params`, `status_family_for` to the existing `__all__` from Task 1.

**Verification grep:** `grep -rn "from uw_scan.storage.repository import" src/ tests/ | grep -E "redact_params|status_family_for|provider_day_bounds"` should show 5+ callers — they must continue to import successfully.

- [ ] **Step 2.3: Run tests (includes test_provider_usage_helpers)**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/ tests/unit/storage/test_provider_usage_helpers.py tests/unit/storage/test_watchlist_card_row.py -v 2>&1 | tail -10
```

`test_provider_usage_helpers.py` tests all three external helpers (`provider_day_bounds`, `status_family_for`, `redact_params`) — it's the smoke test for this task's re-export coverage.

- [ ] **Step 2.4: Commit**

```bash
git add src/uw_scan/storage/_helpers.py src/uw_scan/storage/repository.py
git commit -m "refactor(storage): extract pure helpers to _helpers.py

Moves 5 functions (_d, provider_day_bounds, status_family_for,
redact_params, _nullable_int, _nullable_float) and 2 module constants
(_PROVIDER_DAY_TZ, _REDACTED_PARAM_KEYS) to storage/_helpers.py.

External callers (sources/ohlc.py, api/client.py, api/routers/health.py,
api/routers/provider_usage.py, tests/unit/storage/test_provider_usage_helpers.py)
keep their 'from uw_scan.storage.repository import' paths working via
explicit re-export from repository.py."
```

---

## Task 3 — _base.py: extract the Repository base mixin

**Files:**
- Create: `src/uw_scan/storage/_base.py`
- Modify: `src/uw_scan/storage/repository.py` (Repository now inherits `_BaseMixin`)

**Why a base mixin:** each per-domain mixin will use `self._conn` and `self._schema`. Without a common base, every mixin would need to declare those attributes via type annotations alone, with no `__init__` to actually set them. `_BaseMixin` owns the constructor.

- [ ] **Step 3.1: Create `src/uw_scan/storage/_base.py`**

```python
"""Repository base mixin: owns __init__, conn property, and the _schema /
_conn attributes that every per-domain mixin reads.

Mixed in LAST in the Repository inheritance order so domain mixins can
shadow specific behavior if needed (none do today)."""

from __future__ import annotations

import psycopg


class _BaseMixin:
    """Owns the connection and schema. Other mixins reference self._conn
    and self._schema; this class is what makes them concrete."""

    def __init__(
        self, conn: psycopg.Connection, schema: str = "uw_scan"
    ) -> None:
        self._conn = conn
        self._schema = schema

    @property
    def conn(self) -> psycopg.Connection:
        return self._conn
```

- [ ] **Step 3.2: Update repository.py**

Delete the existing `__init__` (line 582) and `conn` property (line 587). Add `_BaseMixin` to the Repository inheritance list. At this point Repository looks like:

```python
class Repository(_BaseMixin):
    """Per-domain methods live below; PR-1 will move them to mixins."""
    # ... still ~5000 lines of methods until later tasks ...
```

- [ ] **Step 3.3: Run tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/ -v 2>&1 | tail -10
```

Note: this task tests broader scope because we're modifying the Repository constructor, which every test fixture uses.

- [ ] **Step 3.4: Commit**

```bash
git add src/uw_scan/storage/_base.py src/uw_scan/storage/repository.py
git commit -m "refactor(storage): extract _BaseMixin (Repository __init__ + conn)"
```

---

## Task 4 — audit.py: extract 2 audit methods

**Files:**
- Create: `src/uw_scan/storage/audit.py`
- Modify: `src/uw_scan/storage/repository.py`

**Methods moved:**

| Method | Current lines | Notes |
|---|---|---|
| `insert_audit_row` | 654-695 | |
| `insert_raw_payload` | 696-705 | uses `Jsonb` import |

- [ ] **Step 4.1: Create `src/uw_scan/storage/audit.py`**

```python
"""Audit + raw payload writes.

API/worker fetchers call insert_audit_row immediately before any UW HTTP
request (so even failures leave a row), then insert_raw_payload with the
response body. The two-step shape lets us trace any UW call back to its
HTTP request even when normalization fails."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


class _AuditMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_audit_row(
        self,
        # ... copied verbatim ...
    ) -> int:
        ...

    def insert_raw_payload(self, audit_id: int, payload: dict | list) -> int:
        ...
```

- [ ] **Step 4.2: Update repository.py**

- Delete `insert_audit_row` + `insert_raw_payload` (lines 654-705)
- Add `from .audit import _AuditMixin`
- Update inheritance: `class Repository(_AuditMixin, _BaseMixin):`

- [ ] **Step 4.3: Run tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/ tests/integration/test_repository_real_pg.py -v 2>&1 | tail -10
```

(`tests/integration/test_repository_real_pg.py` exercises audit writes via the UW client codepath.)

- [ ] **Step 4.4: Commit**

```bash
git add src/uw_scan/storage/audit.py src/uw_scan/storage/repository.py
git commit -m "refactor(storage): extract _AuditMixin (insert_audit_row + insert_raw_payload)"
```

---

## Task 5 — scan_outputs.py: extract 2 scan-output methods

**Files:**
- Create: `src/uw_scan/storage/scan_outputs.py`
- Modify: `src/uw_scan/storage/repository.py`

**Methods moved:**

| Method | Current lines |
|---|---|
| `insert_opportunity_score` | 3029-3063 |
| `insert_structure_idea` | 3064-3088 |

- [ ] **Step 5.1: Create file with `_ScanOutputsMixin`**
- [ ] **Step 5.2: Delete from repository.py + add import + add to inheritance**
- [ ] **Step 5.3: Run tests:** `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/ -v`
- [ ] **Step 5.4: Commit:** `refactor(storage): extract _ScanOutputsMixin`

---

## Task 6 — market_data.py: extract 9 market-data methods

**Files:**
- Create: `src/uw_scan/storage/market_data.py`
- Modify: `src/uw_scan/storage/repository.py`

**Methods moved (10 — REVISED per codex-review ISSUE-3 to add `get_pcr_history_30d_ago`):**

| Method | Current lines |
|---|---|
| `upsert_daily_ohlc` | 4350-4376 |
| `list_daily_ohlc` | 4377-4391 |
| `upsert_intraday_quote` | 4392-4406 |
| `get_intraday_quote` | 4407-4418 |
| `get_latest_intraday_quote_times` | 4419-4432 |
| `append_pcr_history` | 4433-4451 |
| `get_pcr_history_30d_ago` | 4452-4469 |
| `get_pcr_history_row` | 4650-4665 |
| `get_recent_etf_aum` | 4601-4615 |
| `upsert_etf_aum` | 4616-4630 |

- [ ] **Step 6.1: Create file with `_MarketDataMixin`**

Imports needed: `Iterable`, `_date`, `datetime`, `timedelta`, `Decimal`, `DailyOhlcRow`, `IntradayQuoteRow`, `PcrHistoryRow` (from `.rows`).

- [ ] **Step 6.2: Delete from repository.py + add import + add to inheritance**
- [ ] **Step 6.3: Run tests:** `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/ tests/integration/test_pipeline_etf_caching.py tests/integration/test_pcr_history_append.py -v`
- [ ] **Step 6.4: Commit:** `refactor(storage): extract _MarketDataMixin`

---

## Task 7 — jobs.py: extract 7 jobs queue methods

**Files:**
- Create: `src/uw_scan/storage/jobs.py`
- Modify: `src/uw_scan/storage/repository.py`

**Methods moved:**

| Method | Current lines |
|---|---|
| `enqueue_rescan_job` | 4470-4492 |
| `claim_next_queued_job` | 4493-4515 |
| `requeue_stale_running_jobs` | 4516-4536 |
| `mark_job_done` | 4537-4557 |
| `mark_job_failed` | 4558-4576 |
| `get_rescan_queue_summary` | 4577-4600 |
| `get_job` | 4872-4886 |

- [ ] **Step 7.1: Create file with `_JobsMixin` (REVISED per codex-review ISSUE-5: needs its own logger)**

Imports + module setup:
```python
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import psycopg

from .rows import JobRow, RescanQueueSummaryRow

logger = logging.getLogger(__name__)


class _JobsMixin:
    _conn: psycopg.Connection
    _schema: str

    # ... 7 methods ...
```

The `logger.warning(...)` calls inside `mark_job_done` (line 4551) and `mark_job_failed` (line 4570) require a module-level `logger` — repository.py had one at line 514; the mixin needs its own.

- [ ] **Step 7.2: Delete from repository.py + add import + add to inheritance**
- [ ] **Step 7.3: Run tests:** `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_repository_jobs.py tests/integration/worker/ -v`
- [ ] **Step 7.4: Commit:** `refactor(storage): extract _JobsMixin`

---

## Task 8 — health.py: extract 7 health/heartbeat methods

**Files:**
- Create: `src/uw_scan/storage/health.py`
- Modify: `src/uw_scan/storage/repository.py`

**Methods moved:**

| Method | Current lines |
|---|---|
| `fetch_stock_history_rollup` | 4666-4711 |
| `count_active_watchlist` | 4712-4719 |
| `_discover_record_health_rules` | 4720-4757 |
| `list_record_health` | 4758-4818 |
| `upsert_heartbeat` | 4819-4830 |
| `get_heartbeat` | 4831-4839 |
| `get_latest_heartbeat` | 4840-4853 |

- [ ] **Step 8.1: Create file with `_HealthMixin` (REVISED per codex-review ISSUE-4: also move 2 module constants + 3 imports)**

Also move these 3 module constants (verified via grep — all 3 are used ONLY by `_discover_record_health_rules`/`list_record_health`, so safe to move):
- `_RECORD_HEALTH_TIMESTAMP_COLUMNS` (line 388)
- `_RECORD_HEALTH_TICKER_COLUMNS` (line 389)
- `_RECORD_HEALTH_EXCLUDED_TABLES` (line 390, used only at line 4735 — confirmed via `grep -rn`)

Imports + module setup:
```python
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql as psql

from .rows import RecordHealthRow

_RECORD_HEALTH_TIMESTAMP_COLUMNS = ("updated_at", "inserted_at")
_RECORD_HEALTH_TICKER_COLUMNS = ("ticker", "underlying_symbol")
_RECORD_HEALTH_EXCLUDED_TABLES = {
    # ... copied verbatim from repository.py:390 ...
}


class _HealthMixin:
    _conn: psycopg.Connection
    _schema: str

    # ... 7 methods ...
```

- [ ] **Step 8.2: Delete from repository.py + add import + add to inheritance**

Also remove the moved constants from repository.py and (if `_RECORD_HEALTH_EXCLUDED_TABLES` was also moved) re-export them or just import them back if any non-health code still needs them.

- [ ] **Step 8.3: Run tests:** `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_health.py tests/integration/storage/ -v`
- [ ] **Step 8.4: Commit:** `refactor(storage): extract _HealthMixin`

---

## Task 9 — flow.py: extract 3 flow methods + 2 module helpers

**Files:**
- Create: `src/uw_scan/storage/flow.py`
- Modify: `src/uw_scan/storage/repository.py`

**Methods/helpers moved (REVISED per codex-review ISSUEs 6, 7, 11):**

| Symbol | Current lines | Visibility |
|---|---|---|
| `_flow_footprint_label` (module-level) | 220-235 | externally imported by `scripts/backfill_flow_footprint.py:21` — must re-export from repository.py |
| `_aggressor_label_confidence` (module-level) | 236-249 | externally imported by `scripts/backfill_flow_footprint.py:21` — must re-export |
| `insert_flow_events` (mixin method) | 1034-1093 | internal |
| `upsert_flow_alerts_daily_rollup` (mixin method) | 1094-1162 | internal |
| `_flow_alert_trade_date` (becomes module-level function in flow.py) | 1163-1172 | internal; codex ISSUE-11 confirmed it doesn't use `self` |

**Two visibility wrinkles:**
- The 2 module helpers (`_flow_footprint_label`, `_aggressor_label_confidence`) are used by `scripts/backfill_flow_footprint.py`. After the move, `scripts/backfill_flow_footprint.py` continues to do `from uw_scan.storage.repository import _flow_footprint_label, _aggressor_label_confidence` — we MUST re-export these from `repository.py` (similar to how `redact_params` is re-exported in Task 2).
- `_flow_alert_trade_date` becomes module-level (codex ISSUE-11); the call inside `upsert_flow_alerts_daily_rollup` changes from `self._flow_alert_trade_date(...)` to `_flow_alert_trade_date(...)`.

- [ ] **Step 9.1: Create `src/uw_scan/storage/flow.py`**

```python
"""Flow events + flow_alerts_daily_rollup writes.

Module-level helpers (_flow_footprint_label, _aggressor_label_confidence,
_flow_alert_trade_date) live here because they're either used by callers
outside this mixin (the first two are used by scripts/backfill_flow_footprint.py
and re-exported from repository.py) or don't need self (the last one)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import date as _date, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import psycopg

from uw_scan import models


def _flow_footprint_label(row: models.FlowAlert) -> str:
    ...  # copied verbatim from repository.py:220-235


def _aggressor_label_confidence(row: models.FlowAlert) -> Decimal | None:
    ...  # copied verbatim from repository.py:236-249


def _flow_alert_trade_date(rows: list[models.FlowAlert]) -> _date:
    """Now module-level — doesn't use self."""
    ...  # copied verbatim from repository.py:1163-1172, drop `self` param


class _FlowMixin:
    _conn: psycopg.Connection
    _schema: str

    def insert_flow_events(
        self, run_id: int, ticker: str, alerts: Iterable[models.FlowAlert]
    ) -> int:
        ...  # uses _flow_footprint_label, _aggressor_label_confidence

    def upsert_flow_alerts_daily_rollup(self, ...) -> int:
        ...  # uses _flow_alert_trade_date — call without self
```

- [ ] **Step 9.2: Delete from repository.py**

Delete `_flow_footprint_label` (220-235), `_aggressor_label_confidence` (236-249), `insert_flow_events` (1034-1093), `upsert_flow_alerts_daily_rollup` (1094-1162), `_flow_alert_trade_date` (1163-1172). At the top of repository.py, add the import + re-export:

```python
# Flow helpers re-exported because scripts/backfill_flow_footprint.py imports them
# directly from this module.
from .flow import _aggressor_label_confidence, _flow_footprint_label
```

Add `_flow_footprint_label` and `_aggressor_label_confidence` to `__all__` (and document why — both are leading-underscore "private" but treated as external API by the backfill script).

- [ ] **Step 9.3: Verify external import survives**

```bash
uv run python -c "from uw_scan.storage.repository import _flow_footprint_label, _aggressor_label_confidence; print('ok')"
```

- [ ] **Step 9.4: Run tests + backfill smoke**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/ tests/integration/test_repository_real_pg.py -v
uv run python -c "import scripts.backfill_flow_footprint; print('backfill script import: ok')"
```

- [ ] **Step 9.5: Commit:** `refactor(storage): extract _FlowMixin + module helpers`

---

## Task 10 — Final assembly verification + storage/CLAUDE.md update

**Files:**
- Modify: `src/uw_scan/storage/CLAUDE.md` (document the mixin pattern for the PR-1 modules)
- Verify: `src/uw_scan/storage/repository.py` is the assembled shell + remaining (~120) methods

- [ ] **Step 10.1: Verify final Repository signature**

```bash
grep -n "^class Repository" src/uw_scan/storage/repository.py
wc -l src/uw_scan/storage/repository.py
ls src/uw_scan/storage/*.py
```

Expected:
- `class Repository(_FlowMixin, _HealthMixin, _JobsMixin, _MarketDataMixin, _ScanOutputsMixin, _AuditMixin, _BaseMixin):`
- `repository.py` line count ~4000 (down from 5173)
- 9 new files in `storage/`

- [ ] **Step 10.2: Update `src/uw_scan/storage/CLAUDE.md`**

Add a "Mixin pattern" section explaining:
- repository.py is the assembled shell; do NOT add new methods directly to it
- New methods go in the appropriate per-domain mixin file
- New domains get a new `_<Domain>Mixin` in `<domain>.py`
- Row dataclasses go in `rows.py`
- Private utilities go in `_helpers.py`
- The PR-1 split covered audit/flow/health/jobs/market_data/scan_outputs; PR-2 and PR-3 will cover the remaining domains

- [ ] **Step 10.3: Run full test suite**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest 2>&1 | tail -5
```

Expect same pass/skip counts as pre-PR-1 baseline (346+ pass).

- [ ] **Step 10.4: Lint + idempotency rerun**

```bash
uv run python scripts/_lint_except.py src
set -a; source ../../../.env; set +a; bash scripts/migrate.sh 2>&1 | grep -cE "Applying"  # expect 36
```

- [ ] **Step 10.5: Commit**

```bash
git add src/uw_scan/storage/CLAUDE.md
git commit -m "docs(storage): document mixin pattern after PR-1 split"
```

---

## Final PR steps

- [ ] Push branch + open PR with title `refactor(storage): split repository.py PR 1/3 (leaf modules)`
- [ ] Watch CI
- [ ] Squash-merge on green

## Out of scope (deferred)

- **PR-2:** extract domains — `external_api.py`, `volatility_raw.py`, `options.py`, `scan_runs.py`, `scan_results.py`, `watchlist.py` (~1500 lines)
- **PR-3:** extract heavy — `trade_insights_ai.py`, `volatility_v2.py`, `fetchers.py` (~1300 lines)
- **Cockpit module helpers** (`_pin_candidate`, `_vanna_conditional_reading`, `_charm_regime`, etc.): stay in `repository.py` for PR-1; move to PR-2 with their domain modules
- **`__init__.py` re-export migration:** if we later want `from uw_scan.storage import Repository` to be the canonical import path, that's a separate breaking-change PR after PR-3 lands

## Risks

1. **Mixin MRO collision.** Two mixins defining the same method name would silently shadow each other. We hand-checked each method name is unique within its mixin set; pytest would catch a regression. Future drift is the risk.

2. **`__all__` drift.** A caller that imports a row type via `from uw_scan.storage.repository import SomeRow` would fail if I forget to add `SomeRow` to `__all__`. The integration tests cover most callers but not exhaustively — verify with `grep -rn "from uw_scan.storage.repository import" src/ tests/` after each task.

3. **The 2 cockpit-specific module helpers using `models`.** `_flow_footprint_label` and `_aggressor_label_confidence` use `from uw_scan import models`. The new `flow.py` needs this import. Confirmed in Step 9.1's template.

4. **Test fixture pattern**: integration tests use `Repository(conn, schema=...)`. The mixin pattern preserves this exact constructor signature via `_BaseMixin.__init__`. Verified by running each task's targeted test gate.
