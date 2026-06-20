# Option Surface Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forward-accumulate a durable, full-chain per-strike IV/greeks grid for every watchlist ticker (UW `/greeks`), plus a daily ATM IB-vs-UW IV canary (xenon), so future SVI/dislocation/curvature experiments become possible.

**Architecture:** A new durable table `option_surface_grid_daily` (PK `(ticker, market_date, expiry, strike)`, **no `run_id` FK** — the fix for the cascade-delete trap that keeps `greeks_by_expiry_strike` shallow). A nightly capture job loops `fetch_greeks` over all expiries per ticker and upserts the grid. A separate, independently-gated canary job diffs IB's `impliedVol` (via xenon's read-only query API) against UW's IV at the ATM strike and warns on divergence.

**Tech Stack:** Python 3.13 (`uv`), psycopg 3, APScheduler, Pydantic v2 (`GreeksRow`), httpx (canary), pytest + pytest-postgresql.

Spec: `docs/superpowers/specs/2026-06-19-option-surface-capture-design.md`.

## Global Constraints

- **uv only** — every command is `uv run …`; never bare `python`/`pytest`.
- **`Decimal`** for all IV/greeks/spot — pass `Decimal`, get `Decimal`; never `float()` at the boundary.
- **Idempotent migrations** — `CREATE TABLE IF NOT EXISTS`, header `SET search_path TO uw_scan, public;`, next lexical number, never renumber. Re-running is a no-op.
- **The durable grid table carries NO `run_id` and NO foreign key.** `run_id` exists only for UW call accounting inside `fetch_greeks`; it is never stored. This is the load-bearing design point.
- **Upsert, never delete-then-insert, on the grid** — a partial re-run must only add/refresh, never erase already-captured strikes. (This differs from `skew_swing_greeks`, which deletes-then-inserts.)
- **Per-ticker failure isolation** — one bad ticker logs `repr(exc)` and continues; never kills the job.
- **ET market date** — the scheduler passes `datetime.now(ZoneInfo(settings.rth_tz)).date()`; jobs accept `today`.
- **Mixin pattern** — new storage methods go in a new `_OptionSurfaceMixin` (`storage/option_surface.py`), added to `repository.py`'s inheritance list above `_BaseMixin`; never appended to `repository.py` itself.
- **CI Guardrail 2** — every `except` block calls `repr(exc)` / `.exception(...)` / `raise`.
- **Branch** `feat/option-surface-capture`; commit per task; **do not** push or open a PR until the user asks.

---

## Setup

- [ ] **Create the feature branch**

```bash
git checkout -b feat/option-surface-capture
```

---

### Task 1: Durable grid table migration

**Files:**
- Create: `src/uw_scan/storage/migrations/077_option_surface_grid.sql`
- Test: `tests/integration/storage/test_option_surface_grid_migration.py`

**Interfaces:**
- Produces: table `uw_scan.option_surface_grid_daily` with PK `(ticker, market_date, expiry, strike)` and **zero** foreign keys.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/storage/test_option_surface_grid_migration.py
"""Migration 077 — the durable grid must exist AND carry no cascading FK.

The whole point of this table is to outlive scan_runs: greeks_by_expiry_strike
stays ~30 days deep only because it cascade-deletes with its run. This test is the
regression guard against re-introducing that trap.
"""
from __future__ import annotations


def test_option_surface_grid_exists_with_no_foreign_key(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    with repo.conn.cursor() as cur:
        cur.execute("SELECT to_regclass('uw_scan.option_surface_grid_daily')")
        assert cur.fetchone()[0] is not None, "grid table missing"
        cur.execute(
            "SELECT count(*) FROM information_schema.table_constraints "
            "WHERE table_schema='uw_scan' "
            "  AND table_name='option_surface_grid_daily' "
            "  AND constraint_type='FOREIGN KEY'"
        )
        assert cur.fetchone()[0] == 0, "grid table must have NO foreign key (no cascade trap)"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_option_surface_grid_migration.py -v`
Expected: FAIL — `to_regclass(...)` returns `None` (table not yet created).

- [ ] **Step 3: Write the migration**

```sql
-- src/uw_scan/storage/migrations/077_option_surface_grid.sql
-- Durable full-chain per-strike IV/greeks grid, forward-accumulated nightly from UW
-- /greeks. UNLIKE greeks_by_expiry_strike, this table has NO run_id FK and is NEVER
-- cascade-deleted — it is the permanent archive that makes future SVI/dislocation/
-- curvature work possible (UW returns 403 for per-strike history beyond ~30 days, so the
-- surface can only be accumulated going forward — every uncaptured night is lost).
-- Idempotent. One snapshot per (ticker, market_date, expiry, strike).

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.option_surface_grid_daily (
  ticker          TEXT NOT NULL,
  market_date     DATE NOT NULL,
  expiry          DATE NOT NULL,
  strike          NUMERIC NOT NULL,
  call_iv         NUMERIC,
  put_iv          NUMERIC,
  call_delta      NUMERIC,
  put_delta       NUMERIC,
  call_gamma      NUMERIC,
  put_gamma       NUMERIC,
  call_vega       NUMERIC,
  put_vega        NUMERIC,
  call_theta      NUMERIC,
  put_theta       NUMERIC,
  call_vanna      NUMERIC,
  put_vanna       NUMERIC,
  call_charm      NUMERIC,
  put_charm       NUMERIC,
  underlying_spot NUMERIC,
  source          TEXT NOT NULL DEFAULT 'uw_greeks',
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, expiry, strike)
);

CREATE INDEX IF NOT EXISTS ix_option_surface_grid_ticker_date
  ON uw_scan.option_surface_grid_daily (ticker, market_date DESC);

COMMENT ON TABLE uw_scan.option_surface_grid_daily
  IS 'Durable full-chain per-strike IV/greeks grid, forward-accumulated nightly from UW /greeks by worker/jobs/option_surface_capture. NO run_id FK by design — permanent archive (UW blocks per-strike history beyond ~30 days). One row per (ticker, market_date, expiry, strike).';
```

- [ ] **Step 4: Apply the migration locally and run the test**

Run: `bash scripts/migrate.sh && uv run pytest tests/integration/storage/test_option_surface_grid_migration.py -v`
Expected: PASS. (The integration conftest applies all migrations in-session, so the test sees the new table.)

- [ ] **Step 5: Verify idempotency**

Run: `bash scripts/migrate.sh`
Expected: re-run is a clean no-op (no errors).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/migrations/077_option_surface_grid.sql tests/integration/storage/test_option_surface_grid_migration.py
git commit -m "feat(storage): durable option_surface_grid_daily table (no cascade FK)"
```

---

### Task 2: Grid storage mixin (upsert + ATM read)

**Files:**
- Create: `src/uw_scan/storage/option_surface.py`
- Modify: `src/uw_scan/storage/repository.py` (import + inheritance)
- Test: `tests/integration/storage/test_option_surface_storage.py`

**Interfaces:**
- Produces:
  - `Repository.upsert_option_surface_grid(ticker: str, market_date: date, underlying_spot: Decimal | None, rows: Iterable[dict]) -> int` — rows carry `expiry`, `strike`, and any of the 14 greek/iv keys (`call_iv,put_iv,call_delta,put_delta,call_gamma,put_gamma,call_vega,put_vega,call_theta,put_theta,call_vanna,put_vanna,call_charm,put_charm`). Plain upsert (never delete).
  - `Repository.fetch_option_surface_atm_strike(ticker: str, market_date: date, expiry: date, spot: Decimal) -> dict | None` — `{strike, call_iv, put_iv}` for the strike nearest `spot`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/storage/test_option_surface_storage.py
from __future__ import annotations

from datetime import date
from decimal import Decimal


def _row(strike: str, civ: str, piv: str) -> dict:
    return {
        "expiry": date(2026, 7, 17),
        "strike": Decimal(strike),
        "call_iv": Decimal(civ),
        "put_iv": Decimal(piv),
    }


def test_grid_upsert_accumulates_across_days_and_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d1, d2 = date(2026, 6, 18), date(2026, 6, 19)

    assert repo.upsert_option_surface_grid("TSLA", d1, Decimal("250"), [_row("250", "0.50", "0.52")]) == 1
    assert repo.upsert_option_surface_grid("TSLA", d2, Decimal("255"), [_row("255", "0.48", "0.50")]) == 1
    # Re-run day 1 with an updated IV — must update in place, not duplicate.
    repo.upsert_option_surface_grid("TSLA", d1, Decimal("250"), [_row("250", "0.49", "0.52")])
    repo.conn.commit()

    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*), count(distinct market_date) "
                    "FROM uw_scan.option_surface_grid_daily WHERE ticker='TSLA'")
        assert cur.fetchone() == (2, 2)  # day-1 survived day-2 write; no dup on re-run
        cur.execute("SELECT call_iv FROM uw_scan.option_surface_grid_daily "
                    "WHERE ticker='TSLA' AND market_date=%s", (d1,))
        assert cur.fetchone()[0] == Decimal("0.49")  # updated in place


def test_fetch_atm_strike_returns_nearest(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    d = date(2026, 6, 19)
    repo.upsert_option_surface_grid("TSLA", d, Decimal("252"), [
        _row("245", "0.55", "0.57"), _row("250", "0.50", "0.52"), _row("260", "0.45", "0.47"),
    ])
    repo.conn.commit()
    atm = repo.fetch_option_surface_atm_strike("TSLA", d, date(2026, 7, 17), Decimal("252"))
    assert atm is not None and atm["strike"] == Decimal("250")
    assert atm["call_iv"] == Decimal("0.50")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_option_surface_storage.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_option_surface_grid'`.

- [ ] **Step 3: Write the mixin**

```python
# src/uw_scan/storage/option_surface.py
"""Persistence for the durable option-surface grid (and the IB-vs-UW IV canary)."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal
from typing import Any, Iterable

import psycopg

# Greek/IV keys carried per row, in column order. Spot/source are passed separately.
_GRID_COLS: tuple[str, ...] = (
    "call_iv", "put_iv",
    "call_delta", "put_delta",
    "call_gamma", "put_gamma",
    "call_vega", "put_vega",
    "call_theta", "put_theta",
    "call_vanna", "put_vanna",
    "call_charm", "put_charm",
)


class _OptionSurfaceMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_option_surface_grid(
        self,
        ticker: str,
        market_date: _date,
        underlying_spot: Decimal | None,
        rows: Iterable[dict[str, Any]],
    ) -> int:
        """Upsert a full-chain per-strike IV/greeks snapshot for (ticker, market_date).

        Plain upsert (NOT delete-then-insert): a partial re-run must only add/refresh,
        never erase already-captured strikes — the archive only grows. Returns rows seen.
        """
        t = ticker.upper()
        rows = list(rows)
        if not rows:
            return 0
        col_list = ", ".join(("ticker", "market_date", "expiry", "strike", *_GRID_COLS,
                              "underlying_spot", "source"))
        n_values = 4 + len(_GRID_COLS) + 2  # ticker..strike + greeks + spot + source
        placeholders = ", ".join(["%s"] * n_values)
        set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in (*_GRID_COLS, "underlying_spot", "source"))
        sql = (
            f"INSERT INTO {self._schema}.option_surface_grid_daily ({col_list}) "
            f"VALUES ({placeholders}) "
            "ON CONFLICT (ticker, market_date, expiry, strike) DO UPDATE SET "
            f"{set_clause}, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    (
                        t, market_date, r["expiry"], r["strike"],
                        *(r.get(c) for c in _GRID_COLS),
                        underlying_spot, r.get("source", "uw_greeks"),
                    )
                    for r in rows
                ],
            )
        return len(rows)

    def fetch_option_surface_atm_strike(
        self, ticker: str, market_date: _date, expiry: _date, spot: Decimal
    ) -> dict[str, Any] | None:
        """Strike nearest `spot` for (ticker, market_date, expiry) with its call/put IV.
        Source for the IB-vs-UW canary. None if no rows."""
        sql = (
            "SELECT strike, call_iv, put_iv "
            f"FROM {self._schema}.option_surface_grid_daily "
            "WHERE ticker=%s AND market_date=%s AND expiry=%s "
            "ORDER BY abs(strike - %s) ASC LIMIT 1"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(), market_date, expiry, spot))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))
```

- [ ] **Step 4: Wire the mixin into `Repository`**

In `src/uw_scan/storage/repository.py`, add the import alongside the other storage-mixin imports:

```python
from uw_scan.storage.option_surface import _OptionSurfaceMixin
```

and add `_OptionSurfaceMixin` to the `class Repository(...)` inheritance list, immediately above `_BaseMixin` (which must remain last). For example:

```python
class Repository(
    # ... existing mixins ...
    _OptionSurfaceMixin,
    _BaseMixin,  # MUST be last — owns __init__ and the conn property
):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/integration/storage/test_option_surface_storage.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/storage/option_surface.py src/uw_scan/storage/repository.py tests/integration/storage/test_option_surface_storage.py
git commit -m "feat(storage): _OptionSurfaceMixin — grid upsert + ATM read"
```

---

### Task 3: Full-chain expiry enumeration helper

**Files:**
- Modify: `src/uw_scan/cards/option_chain.py`
- Test: `tests/unit/test_list_all_expiries.py`

**Interfaces:**
- Produces: `list_all_expiries(contracts: Iterable[OptionContractRow], *, today: date) -> list[date]` — every distinct expiry `>= today` parsed from the contracts' OCC `option_symbol`, sorted ASC, deduplicated. Full-chain analogue of `pick_target_expiries`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_list_all_expiries.py
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from uw_scan.cards.option_chain import list_all_expiries


def _c(sym: str):
    # The function only reads `.option_symbol`; SimpleNamespace duck-types OptionContractRow.
    return SimpleNamespace(option_symbol=sym)


def test_list_all_expiries_returns_all_future_sorted_dedup():
    contracts = [
        _c("TSLA  260717C00250000"),
        _c("TSLA  260717P00250000"),  # duplicate expiry, different right
        _c("TSLA  260620C00250000"),  # earlier expiry
        _c("TSLA  240101C00250000"),  # past -> excluded
    ]
    assert list_all_expiries(contracts, today=date(2026, 6, 19)) == [
        date(2026, 6, 20),
        date(2026, 7, 17),
    ]


def test_list_all_expiries_empty_when_no_parseable_contracts():
    assert list_all_expiries([_c("not-an-occ-symbol")], today=date(2026, 6, 19)) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_list_all_expiries.py -v`
Expected: FAIL — `ImportError: cannot import name 'list_all_expiries'`.

- [ ] **Step 3: Add the helper** (in `src/uw_scan/cards/option_chain.py`, directly after `pick_target_expiries`)

```python
def list_all_expiries(
    contracts: Iterable[OptionContractRow], *, today: date
) -> list[date]:
    """Every distinct expiry >= today present in the contracts list, sorted ASC.

    Full-chain analogue of ``pick_target_expiries`` (which collapses to the nearest
    expiry per target DTE). Used by the option-surface capture job to walk the whole
    chain. Reuses the same OCC parsing.
    """
    return sorted(
        {
            parsed[0]
            for c in contracts
            if (parsed := _parse_occ(c.option_symbol)) is not None and parsed[0] >= today
        }
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_list_all_expiries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/option_chain.py tests/unit/test_list_all_expiries.py
git commit -m "feat(cards): list_all_expiries — full-chain expiry enumeration"
```

---

### Task 4: Capture job

**Files:**
- Create: `src/uw_scan/worker/jobs/option_surface_capture.py`
- Test: `tests/integration/worker/test_option_surface_capture.py`

**Interfaces:**
- Consumes: `Repository.list_watchlist_cards()` (→ `card.ticker`, `card.spot`), `Repository.insert_scan_run/finish_scan_run`, `fetch_option_contracts`, `fetch_greeks`, `list_all_expiries`, `Repository.upsert_option_surface_grid`.
- Produces: `option_surface_capture(*, repo: Repository, client: UwClient, today: date | None = None) -> int` — total rows written.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/worker/test_option_surface_capture.py
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from uw_scan.models import GreeksRow
import uw_scan.worker.jobs.option_surface_capture as job


def _stub_sources(monkeypatch, *, raise_for: str | None = None):
    def fake_contracts(client, repo, run_id, ticker, limit):
        return [
            SimpleNamespace(option_symbol=f"{ticker:<6}260717C00250000"),
            SimpleNamespace(option_symbol=f"{ticker:<6}260821C00250000"),
        ]

    def fake_greeks(client, repo, run_id, ticker, expiry_iso):
        if raise_for is not None and ticker == raise_for:
            raise RuntimeError("boom")
        e = date.fromisoformat(expiry_iso)
        return [
            GreeksRow(
                date=date(2026, 6, 19), expiry=e, strike=Decimal("250"),
                call_volatility=Decimal("0.50"), put_volatility=Decimal("0.52"),
                call_delta=Decimal("0.5"), put_delta=Decimal("-0.5"),
            )
        ]

    monkeypatch.setattr(job, "fetch_option_contracts", fake_contracts)
    monkeypatch.setattr(job, "fetch_greeks", fake_greeks)


def test_capture_writes_full_chain_with_spot(seeded_db_with_cards, monkeypatch):
    repo = seeded_db_with_cards  # has a TSLA watchlist card
    _stub_sources(monkeypatch)
    card = next(c for c in repo.list_watchlist_cards() if c.ticker == "TSLA")

    n = job.option_surface_capture(repo=repo, client=None, today=date(2026, 6, 19))

    assert n >= 2  # one strike x two expiries for TSLA (plus any other seeded cards)
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*), count(distinct expiry) "
                    "FROM uw_scan.option_surface_grid_daily WHERE ticker='TSLA'")
        assert cur.fetchone() == (2, 2)
        cur.execute("SELECT call_iv, underlying_spot FROM uw_scan.option_surface_grid_daily "
                    "WHERE ticker='TSLA' AND expiry=%s", (date(2026, 7, 17),))
        iv, spot = cur.fetchone()
        assert iv == Decimal("0.50")
        assert spot == card.spot  # stamped from the watchlist card


def test_capture_isolates_a_failing_ticker(seeded_db_with_cards, monkeypatch):
    repo = seeded_db_with_cards
    _stub_sources(monkeypatch, raise_for="TSLA")  # TSLA explodes
    # Must not raise; TSLA simply contributes no rows.
    job.option_surface_capture(repo=repo, client=None, today=date(2026, 6, 19))
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.option_surface_grid_daily WHERE ticker='TSLA'")
        assert cur.fetchone()[0] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_option_surface_capture.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.worker.jobs.option_surface_capture'`.

- [ ] **Step 3: Write the job**

```python
# src/uw_scan/worker/jobs/option_surface_capture.py
"""Full-chain option-surface capture.

Forward-accumulates a durable per-strike IV/greeks grid for every watchlist ticker into
option_surface_grid_daily. UW returns 403 for per-strike history beyond ~30 days, so this
nightly capture is the only way the surface ever exists for future SVI/dislocation/
curvature work — every uncaptured night is permanently lost. Full chain: ALL expiries,
ALL strikes, no clip.

One UW /greeks call per (ticker, expiry). Idempotent upsert (never delete) so a partial
re-run only adds. Per-ticker failure is isolated.
"""

from __future__ import annotations

import logging
from datetime import date as _date

from uw_scan.api.client import UwClient
from uw_scan.cards.option_chain import list_all_expiries
from uw_scan.sources.uw import fetch_greeks, fetch_option_contracts
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

_CONTRACTS_LIMIT = 2000  # full chain — wider than the swing job's 500


def option_surface_capture(
    *, repo: Repository, client: UwClient, today: _date | None = None
) -> int:
    """Capture the full option-chain IV/greeks grid for every watchlist ticker.

    Returns total rows written. ``today`` is the ET market date (the scheduler passes
    ``datetime.now(rth_tz).date()`` so a non-ET host does not stamp the next day).
    """
    cards = repo.list_watchlist_cards()
    if today is None:
        today = _date.today()
    written = 0
    for card in cards:
        ticker = card.ticker
        try:
            run_id = repo.insert_scan_run(ticker, notes="option_surface_capture")
            contracts = fetch_option_contracts(
                client, repo, run_id, ticker, limit=_CONTRACTS_LIMIT
            )
            expiries = list_all_expiries(contracts, today=today)
            rows: list[dict] = []
            for expiry in expiries:
                for r in fetch_greeks(client, repo, run_id, ticker, expiry.isoformat()):
                    rows.append(
                        {
                            "expiry": r.expiry,
                            "strike": r.strike,
                            "call_iv": r.call_volatility,
                            "put_iv": r.put_volatility,
                            "call_delta": r.call_delta,
                            "put_delta": r.put_delta,
                            "call_gamma": r.call_gamma,
                            "put_gamma": r.put_gamma,
                            "call_vega": r.call_vega,
                            "put_vega": r.put_vega,
                            "call_theta": r.call_theta,
                            "put_theta": r.put_theta,
                            "call_vanna": r.call_vanna,
                            "put_vanna": r.put_vanna,
                            "call_charm": r.call_charm,
                            "put_charm": r.put_charm,
                        }
                    )
            n = repo.upsert_option_surface_grid(ticker, today, card.spot, rows)
            repo.finish_scan_run(run_id, status="ok")
            repo.conn.commit()
            written += n
        except Exception as exc:  # noqa: BLE001 — one bad ticker must not kill the job
            repo.conn.rollback()
            log.warning("option_surface_capture: %s skipped: %s", ticker, repr(exc))
    log.info("option_surface_capture wrote %d surface-grid rows", written)
    return written
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/integration/worker/test_option_surface_capture.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/option_surface_capture.py tests/integration/worker/test_option_surface_capture.py
git commit -m "feat(worker): option_surface_capture — full-chain nightly UW grid capture"
```

---

### Task 5: Config flags

**Files:**
- Modify: `src/uw_scan/config.py` (Settings fields + `from_env`)
- Test: `tests/unit/test_settings_option_surface.py`

**Interfaces:**
- Produces on `Settings`: `option_surface_capture_enabled: bool = True`, `option_surface_iv_canary_enabled: bool = True`, `option_surface_iv_canary_warn_threshold: float = 0.02`, `xenon_query_api_url: str = "http://127.0.0.1:8421"`, `xenon_query_api_key: SecretStr | None = None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_settings_option_surface.py
from __future__ import annotations

from uw_scan.config import Settings


def test_settings_reads_option_surface_flags(monkeypatch, tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "x")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")
    monkeypatch.setenv("OPTION_SURFACE_CAPTURE_ENABLED", "false")
    monkeypatch.setenv("OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD", "0.05")

    s = Settings.from_env(env_path=env)

    assert s.option_surface_capture_enabled is False
    assert s.option_surface_iv_canary_enabled is True          # default
    assert s.option_surface_iv_canary_warn_threshold == 0.05
    assert s.xenon_query_api_url == "http://127.0.0.1:8421"    # default
    assert s.xenon_query_api_key is None                        # unset -> None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_settings_option_surface.py -v`
Expected: FAIL — `AttributeError`/validation error: no `option_surface_capture_enabled`.

- [ ] **Step 3: Add the fields** (in the `Settings` class body, near the other scheduler flags)

```python
    # Option surface capture (durable full-chain IV/greeks grid) + IB-vs-UW IV canary
    option_surface_capture_enabled: bool = True
    option_surface_iv_canary_enabled: bool = True
    option_surface_iv_canary_warn_threshold: float = 0.02
    xenon_query_api_url: str = "http://127.0.0.1:8421"
    xenon_query_api_key: SecretStr | None = None
```

- [ ] **Step 4: Read them in `from_env`** (inside the `return cls(...)` call)

```python
            option_surface_capture_enabled=_env_bool("OPTION_SURFACE_CAPTURE_ENABLED", True),
            option_surface_iv_canary_enabled=_env_bool("OPTION_SURFACE_IV_CANARY_ENABLED", True),
            option_surface_iv_canary_warn_threshold=float(
                os.environ.get("OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD", "0.02")
            ),
            xenon_query_api_url=os.environ.get(
                "XENON_QUERY_API_URL", "http://127.0.0.1:8421"
            ),
            xenon_query_api_key=(
                SecretStr(v)
                if (v := os.environ.get("XENON_QUERY_API_KEY", "").strip())
                else None
            ),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_settings_option_surface.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py tests/unit/test_settings_option_surface.py
git commit -m "feat(config): option-surface capture + canary flags"
```

---

### Task 6: Scheduler wiring — capture job

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/unit/test_scheduler_option_surface_gate.py`

**Interfaces:**
- Consumes: `option_surface_capture`, `settings.option_surface_capture_enabled`, `_repo`, `_uw_client`, `_external_api_recorder`.
- Produces: `_should_schedule_option_surface_capture(settings) -> bool` (True for `all` or `uw`-index-0); a registered cron job `id="option_surface_capture"` at `0 19 * * 0-4`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_scheduler_option_surface_gate.py
from __future__ import annotations

from types import SimpleNamespace

from uw_scan.worker.scheduler import _should_schedule_option_surface_capture


def _s(role: str, idx: int):
    return SimpleNamespace(worker_role=role, worker_index=idx)


def test_capture_pinned_to_uw_zero_or_all():
    assert _should_schedule_option_surface_capture(_s("all", 0)) is True
    assert _should_schedule_option_surface_capture(_s("uw", 0)) is True
    assert _should_schedule_option_surface_capture(_s("uw", 1)) is False
    assert _should_schedule_option_surface_capture(_s("massive", 0)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_scheduler_option_surface_gate.py -v`
Expected: FAIL — `ImportError: cannot import name '_should_schedule_option_surface_capture'`.

- [ ] **Step 3: Add the import** (with the other `worker.jobs` imports near line 56)

```python
from uw_scan.worker.jobs.option_surface_capture import option_surface_capture
```

- [ ] **Step 4: Add the gate predicate** (next to `_should_schedule_skew_swing_greeks`)

```python
def _should_schedule_option_surface_capture(settings: Settings) -> bool:
    """Exactly one process owns the nightly full-chain surface capture.

    A UW-bound watchlist loop with no advisory lock; scheduling it on every role's
    index-0 would multiply UW /greeks spend (429 risk) and race upserts. Pin to uw-0,
    following the skew_swing / rates-FRED precedent.
    """
    role = settings.worker_role.lower()
    return role == "all" or (role == "uw" and settings.worker_index == 0)
```

- [ ] **Step 5: Add the wrapper** (next to `_skew_swing_greeks_refresh`, ~line 478)

```python
    def _option_surface_capture() -> None:
        if not settings.option_surface_capture_enabled:
            return
        # ET market date (not host-local) so a non-ET host doesn't stamp +1 day.
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="option_surface_capture"
            ) as uw:
                with _repo(settings) as repo:
                    option_surface_capture(repo=repo, client=uw, today=market_date)
```

- [ ] **Step 6: Register the job** (next to the `skew_swing_greeks_refresh` `add_job`, ~line 884)

```python
            if _should_schedule_option_surface_capture(settings):
                sched.add_job(
                    _option_surface_capture,
                    CronTrigger.from_crontab("0 19 * * 0-4", timezone=settings.rth_tz),
                    id="option_surface_capture",
                    name="Option surface full-chain capture",
                    max_instances=1,
                    coalesce=True,
                )
```

- [ ] **Step 7: Run the test + import smoke check**

Run: `uv run pytest tests/unit/test_scheduler_option_surface_gate.py -v && uv run python -c "import uw_scan.worker.scheduler"`
Expected: PASS, and the import prints nothing (no crash) — confirms the wrapper/registration parse and the job id is wired.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/worker/scheduler.py tests/unit/test_scheduler_option_surface_gate.py
git commit -m "feat(worker): schedule option_surface_capture (uw-0, 19:00 ET)"
```

---

### Task 7: xenon query-API client (canary source)

**Files:**
- Create: `src/uw_scan/sources/xenon_query.py`
- Test: `tests/unit/test_xenon_query.py`

**Interfaces:**
- Produces: `fetch_ib_option_iv(*, base_url: str, api_key: str | None, symbol: str, expiry: str, strike: float, right: str, timeout_s: float = 15.0, client: httpx.Client | None = None) -> Decimal | None` — IB `impliedVol` for one contract via `GET /options/greeks`; `None` on no-greeks or any failure (never raises into the job).

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_xenon_query.py
from __future__ import annotations

from decimal import Decimal

import httpx

from uw_scan.sources.xenon_query import fetch_ib_option_iv


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_returns_implied_vol_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/options/greeks"
        assert request.url.params["symbol"] == "QQQ"
        return httpx.Response(200, json={"greeks": {"impliedVol": 0.4071, "delta": 0.95}})

    iv = fetch_ib_option_iv(
        base_url="http://x:8421", api_key=None, symbol="QQQ",
        expiry="20260717", strike=600.0, right="C", client=_client(handler),
    )
    assert iv == Decimal("0.4071")


def test_returns_none_when_greeks_null():
    def handler(request): return httpx.Response(200, json={"greeks": None, "note": "no greeks returned"})
    assert fetch_ib_option_iv(
        base_url="http://x:8421", api_key=None, symbol="QQQ",
        expiry="20260717", strike=600.0, right="C", client=_client(handler),
    ) is None


def test_returns_none_on_http_error():
    def handler(request): return httpx.Response(502, json={"detail": "could not qualify"})
    assert fetch_ib_option_iv(
        base_url="http://x:8421", api_key=None, symbol="ZZZ",
        expiry="20260717", strike=600.0, right="C", client=_client(handler),
    ) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_xenon_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.sources.xenon_query'`.

- [ ] **Step 3: Write the client**

```python
# src/uw_scan/sources/xenon_query.py
"""Read-only client for xenon's query API — IB-native option greeks for the surface canary.

See xenon/docs/reference/readonly-query-api.md. Used ONLY for targeted single-contract
lookups (the daily IB-vs-UW IV cross-check); never for bulk chain capture, because the
endpoint is per-contract (one IB snapshot subprocess per call).
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

import httpx

log = logging.getLogger(__name__)


def fetch_ib_option_iv(
    *,
    base_url: str,
    api_key: str | None,
    symbol: str,
    expiry: str,
    strike: float,
    right: str,
    timeout_s: float = 15.0,
    client: httpx.Client | None = None,
) -> Decimal | None:
    """IB modelGreeks impliedVol for one option contract via GET /options/greeks.

    ``expiry`` is YYYYMMDD. Returns the IV as Decimal, or None when IB computed no greeks
    or the call failed — the canary must never raise into the job.
    """
    headers = {"X-API-Key": api_key} if api_key else {}
    params = {"symbol": symbol.upper(), "expiry": expiry, "strike": strike, "right": right.upper()}
    own = client is None
    c = client or httpx.Client(timeout=timeout_s)
    try:
        resp = c.get(f"{base_url}/options/greeks", params=params, headers=headers)
        resp.raise_for_status()
        greeks = (resp.json() or {}).get("greeks")
        if not greeks or greeks.get("impliedVol") is None:
            return None
        return Decimal(str(greeks["impliedVol"]))
    except (httpx.HTTPError, ValueError, KeyError, InvalidOperation) as exc:
        log.warning(
            "xenon canary fetch failed for %s %s %s%s: %s",
            symbol, expiry, strike, right, repr(exc),
        )
        return None
    finally:
        if own:
            c.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_xenon_query.py -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/xenon_query.py tests/unit/test_xenon_query.py
git commit -m "feat(sources): xenon_query.fetch_ib_option_iv — canary source"
```

---

### Task 8: Canary table + storage + job

**Files:**
- Create: `src/uw_scan/storage/migrations/078_iv_source_validation.sql`
- Modify: `src/uw_scan/storage/option_surface.py` (add canary upsert)
- Create: `src/uw_scan/worker/jobs/option_surface_iv_canary.py`
- Test: `tests/integration/worker/test_option_surface_iv_canary.py`

**Interfaces:**
- Produces:
  - table `uw_scan.iv_source_validation` (PK `(ticker, market_date, expiry, strike, right)`).
  - `Repository.upsert_iv_source_validation(ticker, market_date, expiry, strike, right, uw_iv, ib_iv) -> None`.
  - `option_surface_iv_canary(*, repo, settings, today=None) -> float | None` — median abs IB-vs-UW IV diff across the watchlist's ATM call strikes (front 2 expiries); WARNs when above `settings.option_surface_iv_canary_warn_threshold`.

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/worker/test_option_surface_iv_canary.py
from __future__ import annotations

from datetime import date
from decimal import Decimal

import uw_scan.worker.jobs.option_surface_iv_canary as canary


def _seed_grid(repo, ticker, d, spot):
    for expiry in (date(2026, 7, 17), date(2026, 8, 21)):
        repo.upsert_option_surface_grid(ticker, d, spot, [
            {"expiry": expiry, "strike": Decimal("250"),
             "call_iv": Decimal("0.50"), "put_iv": Decimal("0.52")},
        ])
    repo.conn.commit()


def test_canary_persists_diffs_and_returns_median(seeded_db_with_cards, monkeypatch):
    repo = seeded_db_with_cards
    d = date(2026, 6, 19)
    card = next(c for c in repo.list_watchlist_cards() if c.ticker == "TSLA")
    _seed_grid(repo, "TSLA", d, card.spot or Decimal("250"))

    # IB reports 0.55 vs UW 0.50 -> abs_diff 0.05 on every contract.
    monkeypatch.setattr(canary, "fetch_ib_option_iv", lambda **k: Decimal("0.55"))

    median = canary.option_surface_iv_canary(repo=repo, settings=_FakeSettings(), today=d)

    assert median == Decimal("0.05")
    with repo.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.iv_source_validation WHERE ticker='TSLA'")
        assert cur.fetchone()[0] == 2  # front 2 expiries


class _FakeSettings:
    xenon_query_api_url = "http://x:8421"
    xenon_query_api_key = None
    option_surface_iv_canary_warn_threshold = 0.02
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/worker/test_option_surface_iv_canary.py -v`
Expected: FAIL — module `option_surface_iv_canary` does not exist.

- [ ] **Step 3: Write the migration**

```sql
-- src/uw_scan/storage/migrations/078_iv_source_validation.sql
-- Daily ATM IB-vs-UW IV cross-check (data-quality canary). One row per
-- (ticker, market_date, expiry, strike, right). Written by
-- worker/jobs/option_surface_iv_canary. Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.iv_source_validation (
  ticker      TEXT NOT NULL,
  market_date DATE NOT NULL,
  expiry      DATE NOT NULL,
  strike      NUMERIC NOT NULL,
  "right"     TEXT NOT NULL,
  uw_iv       NUMERIC,
  ib_iv       NUMERIC,
  abs_diff    NUMERIC,
  inserted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, market_date, expiry, strike, "right")
);

COMMENT ON TABLE uw_scan.iv_source_validation
  IS 'Daily ATM IB-vs-UW IV cross-check (data-quality canary) written by worker/jobs/option_surface_iv_canary.';
```

- [ ] **Step 4: Add the canary upsert** to `_OptionSurfaceMixin` in `src/uw_scan/storage/option_surface.py`

```python
    def upsert_iv_source_validation(
        self,
        ticker: str,
        market_date: _date,
        expiry: _date,
        strike: Decimal,
        right: str,
        uw_iv: Decimal | None,
        ib_iv: Decimal | None,
    ) -> None:
        """Persist one IB-vs-UW IV comparison row. abs_diff is computed when both present."""
        abs_diff = abs(uw_iv - ib_iv) if (uw_iv is not None and ib_iv is not None) else None
        with self._conn.cursor() as cur:
            cur.execute(
                f'INSERT INTO {self._schema}.iv_source_validation '
                '(ticker, market_date, expiry, strike, "right", uw_iv, ib_iv, abs_diff, inserted_at) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) "
                'ON CONFLICT (ticker, market_date, expiry, strike, "right") DO UPDATE SET '
                "uw_iv=EXCLUDED.uw_iv, ib_iv=EXCLUDED.ib_iv, abs_diff=EXCLUDED.abs_diff, inserted_at=now()",
                (ticker.upper(), market_date, expiry, strike, right.upper(), uw_iv, ib_iv, abs_diff),
            )
```

- [ ] **Step 5: Write the canary job**

```python
# src/uw_scan/worker/jobs/option_surface_iv_canary.py
"""IB-vs-UW IV canary.

For each watchlist ticker, compare IB's modelGreeks impliedVol (via xenon's read-only
query API) against UW's captured IV at the ATM call strike for the front 2 expiries.
Persists every comparison to iv_source_validation and WARNs when the watchlist-wide
median abs diff exceeds the configured threshold — an early signal that the UW-sourced
surface can't be trusted. Targeted (per-contract) calls only; never bulk.
"""

from __future__ import annotations

import logging
from datetime import date as _date
from decimal import Decimal
from statistics import median as _median

from uw_scan.sources.xenon_query import fetch_ib_option_iv
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

_FRONT_EXPIRIES = 2


def _front_expiries(repo: Repository, ticker: str, market_date: _date) -> list[_date]:
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT expiry FROM uw_scan.option_surface_grid_daily "
            "WHERE ticker=%s AND market_date=%s ORDER BY expiry ASC LIMIT %s",
            (ticker.upper(), market_date, _FRONT_EXPIRIES),
        )
        return [r[0] for r in cur.fetchall()]


def option_surface_iv_canary(*, repo: Repository, settings, today: _date | None = None) -> Decimal | None:
    """Diff IB vs UW IV at the ATM call strike for the front 2 expiries, per ticker.
    Returns the watchlist-wide median abs_diff (None if no comparisons)."""
    if today is None:
        today = _date.today()
    api_key = (
        settings.xenon_query_api_key.get_secret_value()
        if settings.xenon_query_api_key is not None
        else None
    )
    diffs: list[Decimal] = []
    for card in repo.list_watchlist_cards():
        ticker, spot = card.ticker, card.spot
        if spot is None:
            continue
        for expiry in _front_expiries(repo, ticker, today):
            atm = repo.fetch_option_surface_atm_strike(ticker, today, expiry, spot)
            if atm is None:
                continue
            ib_iv = fetch_ib_option_iv(
                base_url=settings.xenon_query_api_url,
                api_key=api_key,
                symbol=ticker,
                expiry=expiry.strftime("%Y%m%d"),
                strike=float(atm["strike"]),
                right="C",
            )
            uw_iv = atm.get("call_iv")
            repo.upsert_iv_source_validation(ticker, today, expiry, atm["strike"], "C", uw_iv, ib_iv)
            if uw_iv is not None and ib_iv is not None:
                diffs.append(abs(uw_iv - ib_iv))
        repo.conn.commit()

    if not diffs:
        log.info("option_surface_iv_canary: no comparisons available")
        return None
    med = _median(diffs)
    threshold = Decimal(str(settings.option_surface_iv_canary_warn_threshold))
    if med > threshold:
        log.warning(
            "option_surface_iv_canary: median IB-vs-UW IV diff %.4f exceeds %.4f over %d contracts",
            med, threshold, len(diffs),
        )
    else:
        log.info("option_surface_iv_canary: median IB-vs-UW IV diff %.4f (%d contracts)", med, len(diffs))
    return med
```

- [ ] **Step 6: Apply migration + run tests**

Run: `bash scripts/migrate.sh && uv run pytest tests/integration/worker/test_option_surface_iv_canary.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/migrations/078_iv_source_validation.sql src/uw_scan/storage/option_surface.py src/uw_scan/worker/jobs/option_surface_iv_canary.py tests/integration/worker/test_option_surface_iv_canary.py
git commit -m "feat(worker): IB-vs-UW IV canary (iv_source_validation)"
```

---

### Task 9: Scheduler wiring — canary job

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: extend `tests/unit/test_scheduler_option_surface_gate.py`

**Interfaces:**
- Produces: a registered cron job `id="option_surface_iv_canary"` at `30 19 * * 0-4` (after capture, same uw-0 gate), gated by `settings.option_surface_iv_canary_enabled`.

- [ ] **Step 1: Add the failing test** (append to `tests/unit/test_scheduler_option_surface_gate.py`)

```python
def test_canary_import_and_wrapper_present():
    # The canary shares the capture gate (uw-0) — assert the job function imports cleanly.
    from uw_scan.worker.jobs.option_surface_iv_canary import option_surface_iv_canary
    assert callable(option_surface_iv_canary)
```

- [ ] **Step 2: Run it to verify current state**

Run: `uv run pytest tests/unit/test_scheduler_option_surface_gate.py::test_canary_import_and_wrapper_present -v`
Expected: PASS already (the job exists from Task 8) — this guards the wiring imports stay intact.

- [ ] **Step 3: Add the import** (with the other job imports)

```python
from uw_scan.worker.jobs.option_surface_iv_canary import option_surface_iv_canary
```

- [ ] **Step 4: Add the wrapper** (next to `_option_surface_capture`)

```python
    def _option_surface_iv_canary() -> None:
        if not settings.option_surface_iv_canary_enabled:
            return
        market_date = datetime.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            option_surface_iv_canary(repo=repo, settings=settings, today=market_date)
```

- [ ] **Step 5: Register the job** (immediately after the capture `add_job`, reusing the capture gate so it only runs where the grid was written)

```python
            if _should_schedule_option_surface_capture(settings):
                sched.add_job(
                    _option_surface_iv_canary,
                    CronTrigger.from_crontab("30 19 * * 0-4", timezone=settings.rth_tz),
                    id="option_surface_iv_canary",
                    name="Option surface IB-vs-UW IV canary",
                    max_instances=1,
                    coalesce=True,
                )
```

- [ ] **Step 6: Run the test + import smoke check**

Run: `uv run pytest tests/unit/test_scheduler_option_surface_gate.py -v && uv run python -c "import uw_scan.worker.scheduler"`
Expected: PASS, clean import.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/worker/scheduler.py tests/unit/test_scheduler_option_surface_gate.py
git commit -m "feat(worker): schedule IB-vs-UW IV canary (30 min after capture)"
```

---

### Task 10: Docs — pointers + schedule + env

**Files:**
- Modify: `CLAUDE.md` (root — "Where to look first" table)
- Modify: `src/uw_scan/worker/CLAUDE.md` (schedule table)
- Modify: `.env.example` (new env vars)

**Interfaces:** none (documentation).

- [ ] **Step 1: Add a "Where to look first" row** to root `CLAUDE.md`

```markdown
| Option surface capture (durable full-chain IV grid) + IB canary | `worker/jobs/option_surface_capture.py` + `worker/jobs/option_surface_iv_canary.py` + `storage/option_surface.py` + `sources/xenon_query.py` + migrations `077`/`078`; spec `docs/superpowers/specs/2026-06-19-option-surface-capture-design.md` |
```

- [ ] **Step 2: Add the schedule rows** to `src/uw_scan/worker/CLAUDE.md` (Schedule table)

```markdown
| `option_surface_capture` | cron | `0 19 * * 0-4` (uw-0; full-chain UW /greeks → durable grid) |
| `option_surface_iv_canary` | cron | `30 19 * * 0-4` (uw-0; ATM IB-vs-UW IV diff, WARN on drift) |
```

- [ ] **Step 3: Document the env vars** in `.env.example`

```bash
# Option surface capture (durable full-chain IV/greeks grid) + IB-vs-UW IV canary
OPTION_SURFACE_CAPTURE_ENABLED=true
OPTION_SURFACE_IV_CANARY_ENABLED=true
OPTION_SURFACE_IV_CANARY_WARN_THRESHOLD=0.02
# xenon read-only query API (canary only; localhost-bypass on the mini where xenon runs)
XENON_QUERY_API_URL=http://127.0.0.1:8421
# XENON_QUERY_API_KEY=   # required only for non-localhost callers
```

- [ ] **Step 4: Run the full suite once**

Run: `uv run pytest tests/unit/test_list_all_expiries.py tests/unit/test_settings_option_surface.py tests/unit/test_xenon_query.py tests/unit/test_scheduler_option_surface_gate.py tests/integration/storage/test_option_surface_grid_migration.py tests/integration/storage/test_option_surface_storage.py tests/integration/worker/test_option_surface_capture.py tests/integration/worker/test_option_surface_iv_canary.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md src/uw_scan/worker/CLAUDE.md .env.example
git commit -m "docs: option-surface capture pointers, schedule, env"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** durable table §1 → Task 1; storage §2 → Task 2; capture job §2 → Tasks 3–4; config §4 → Task 5; scheduling → Tasks 6, 9; canary §3 → Tasks 7–8; docs/future-reference → Task 10 + spec. ✅
- **Spec deviations (intentional, reflected in spec):** no `*_oi` columns and `underlying_spot` from `card.spot` (`/greeks` carries neither — confirmed against `models/greeks.py:GreeksRow`); `rho` omitted (never consumed). ✅
- **Type consistency:** `upsert_option_surface_grid(ticker, market_date, underlying_spot, rows)`, `fetch_option_surface_atm_strike(...) -> {strike, call_iv, put_iv}`, `list_all_expiries(contracts, *, today)`, `option_surface_capture(*, repo, client, today)`, `fetch_ib_option_iv(*, base_url, api_key, symbol, expiry, strike, right, client=None)`, `option_surface_iv_canary(*, repo, settings, today)` — names/signatures match across tasks. ✅
- **Placeholder scan:** none — every code/test step is complete. ✅

## Out of scope (this plan)

Per the spec: no SVI/SABR fit, no dislocation residual, no curvature signal, no table partitioning, no xenon leg-pricing/intraday/WS integration. Spec B (`2026-06-19-vrp-harvest-markout-design.md`) is a separate plan, authored after this one is underway.
