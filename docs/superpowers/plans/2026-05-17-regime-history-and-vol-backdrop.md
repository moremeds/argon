# Regime History + Vol Backdrop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 90-day GEX history to the regime page (per-ticker, including SPX) and a global vol-backdrop strip (VIX / VIX3M / VVIX / COR1M), backed by two new Postgres persistence domains.

**Architecture:**
- Local parquet lake (`~/market-warehouse/data-lake/bronze/asset_class=volatility/`) is the source of truth for SPX daily OHLC and the CBOE vol indices. UW `/ohlc/1d` is tier-blocked for SPX and we don't want to fall back to Yahoo, so the lake closes the SPX gap.
- A nightly APScheduler job (`vol_index_lake_sync_job`) upserts the lake's parquet tail into `uw_scan.vol_index_daily`. Idempotent: same row twice = no-op.
- The GEX scanner already calls `/greek-exposure` for today's snapshot — that payload also carries ~250 daily history rows. We persist the tail to `uw_scan.greek_exposure_daily` (one row per ticker × date) during each scan.
- `/api/regime/gex` is extended to return a `history` array (90 daily entries) sourced from `greek_exposure_daily` joined with `daily_ohlc` (ETFs) or `vol_index_daily` (SPX).
- A new `/api/regime/vol-backdrop` returns the global vol complex time series (VIX/VIX3M/VVIX/COR1M).
- Frontend gains `<HistoryChart>` (inside `GexSubTab`) and `<VolBackdropStrip>` (top of the regime page).

**Tech Stack:** Python 3.13 (uv), pyarrow (new dep), psycopg 3, APScheduler 3, FastAPI, Pydantic v2, Next.js 16, React 19, hand-rolled SVG.

---

## Verified Facts (2026-05-17)

These are the facts the plan rests on, confirmed by direct file inspection. The plan was revised after the initial draft to incorporate them.

| Fact | Location | Implication |
|---|---|---|
| `fetch_greek_exposure_history(client, repo, run_id, ticker)` already exists, returns raw dict body | `src/uw_scan/sources/uw.py:210` | Don't write a new fetcher. Reuse. Audit-write happens inside `_fetch_json`. |
| `fetch_aggregate_gex` parser already exists, returns `[{date, call_gex, put_gex, call_delta, put_delta}, ...]` | `src/uw_scan/scanners/gex.py:290-310` | This is the **shared util** the user asked for. Promote it to `cards/greek_exposure_history.py` so persistence + scanner both consume it. |
| `Repository.conn` is already a public property | `src/uw_scan/storage/repository.py:586-588` | Sub-domain repos can do `Repository(repo.conn, schema=repo._schema)`. No new property needed. |
| Schema attribute access: `repo._schema` is the established pattern | `tests/integration/conftest.py:99` uses `repo._schema` directly | Mirror this — don't add a public property just for new code. |
| `seeded_db_empty_cards` fixture yields a `Repository` (not a bare `Connection`) | `tests/integration/conftest.py:50-59` | All integration tests use this fixture, not `pg_conn`. Reset+migrate happens inside. |
| `finiteDomain(values)` returns `{lo, hi, count} \| null` (NOT a tuple) | `web/lib/svgChart.ts` (verified) | `linearScale([d.lo, d.hi], range)` and null-guard for the empty case. |
| `regimeApi` is an object literal at `web/lib/regime/api.ts` with snake_case methods (`gex`, `gex_scan`, `cri_scan`, `vcg_scan`) | `web/lib/regime/api.ts` | New method must be `vol_backdrop`, not `volBackdrop`. |
| Regime page is `web/app/regime/page.tsx`, mounts `<RegimePanel />` from `web/components/regime/RegimePanel.tsx` | both verified | `<VolBackdropStrip>` mounts inside `page.tsx`, above `<RegimePanel />` — survives tab switches. |
| `_stub_minimal_chain(monkeypatch)` helper exists | `tests/integration/test_gex_scanner.py:127` | Reuse for new tests. |
| UW `/greek-exposure` history payload row keys: `date, call_gex, put_gex, call_delta, put_delta` (no `gex_flip`, no `price`, no `net_gex`) | scanner parsing at `gex.py:290` | `gex_flip` and `atm_iv` columns in history chart will be NULL until our own daily `gex_snapshots` build up. Plan reflects this honestly — UI degrades gracefully. |
| Integration tests need `UW_SCAN_TEST_DB_NAME` env var | `tests/integration/conftest.py:25-31` | Executor must set this before running pytest. |

### API call separation (user requirement)

The user asked: regime greek-exposure API should be **distinct** from stock-page greek-exposure, but **share util functions** where possible.

Current state already satisfies this at the UW client layer:

| Path | Fetcher | UW endpoint | Persistence | Consumer |
|---|---|---|---|---|
| Stock / Cockpit | `fetch_greek_exposure(..., expiry)` | `/api/stock/{t}/greek-exposure?expiry=X` | `greek_exposure_rows` table | `pipeline.py`, `cockpit_daily_snapshot.py` |
| Regime | `fetch_greek_exposure_history(..., NO expiry)` | `/api/stock/{t}/greek-exposure` | `greek_exposure_daily` (this plan, new) | `scanners/gex.py`, `routers/regime.py` |

Different fetchers → different endpoints → different normalizers → different tables. The shared piece is the *pure parser util* (Task B2.5 below) — a function `parse_greek_exposure_history(body) -> list[dict]` that anyone can call without needing a UW client. Scanner uses it, persistence uses it, and any future consumer can use it.

---

## File Structure

**Create:**
- `src/uw_scan/storage/migrations/038_vol_index_daily.sql`
- `src/uw_scan/storage/migrations/039_greek_exposure_daily.sql`
- `src/uw_scan/sources/lake.py` — parquet reader
- `src/uw_scan/cards/greek_exposure_history.py` — **shared parser util** (consumed by scanner + persistence)
- `src/uw_scan/storage/vol_index_repository.py` — new domain (memory: never extend `repository.py`)
- `src/uw_scan/storage/greek_exposure_repository.py` — new domain
- `src/uw_scan/worker/jobs/vol_index_lake_sync.py` — nightly sync job
- `tests/unit/test_lake_reader.py`
- `tests/unit/test_greek_exposure_history_parser.py`
- `tests/integration/storage/test_vol_index_repository.py`
- `tests/integration/storage/test_greek_exposure_repository.py`
- `tests/integration/test_vol_index_lake_sync.py`
- `tests/integration/test_regime_history_endpoint.py`
- `tests/integration/test_regime_vol_backdrop.py`
- `web/components/regime/HistoryChart.tsx`
- `web/components/regime/VolBackdropStrip.tsx`
- `web/lib/regime/useVolBackdrop.ts`
- `web/tests/unit/historyChart.test.tsx`
- `web/tests/unit/volBackdropStrip.test.tsx`

**Modify:**
- `pyproject.toml` — add `pyarrow>=18.0` to main deps
- `src/uw_scan/config.py` — add `lake_vol_index_root` setting
- `src/uw_scan/scanners/gex.py` — `fetch_aggregate_gex` body delegates to the new shared parser util; persist the same parsed rows via `GreekExposureDailyRepository`
- `src/uw_scan/api/routers/regime.py` — extend `/gex` (add `history`); add `/vol-backdrop`
- `src/uw_scan/api/schemas.py` — add `RegimeHistoryEntry`, `VolBackdropResponse`; extend `GexResponse.history`
- `src/uw_scan/worker/scheduler.py` — register `vol_index_lake_sync_job` (cron: nightly 03:15 ET)
- `src/uw_scan/storage/repository.py` — possibly add `fetch_daily_ohlc_history` / `fetch_flip_strike_history` read methods (verify existence first — these are reads against existing tables, not new domains, so they belong in `repository.py`)
- `web/components/regime/GexSubTab.tsx` — mount `<HistoryChart>`
- `web/lib/regime/api.ts` — add `vol_backdrop` URL builder
- `web/lib/regime/useGex.ts` — already exposes `history` field (verified); nothing to change there
- `web/app/regime/page.tsx` — mount `<VolBackdropStrip>` above `<RegimePanel />`
- `web/lib/types.ts` — regenerated via `npm run gen:types`

---

## Phase A: Lake Sync Infrastructure

### Task A1: Add pyarrow dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add pyarrow to main deps**

Open `pyproject.toml`, find the `dependencies = [` list under `[project]`, add `"pyarrow>=18.0",` in alphabetical position.

- [ ] **Step 2: Sync**

Run: `uv sync --extra postgres`
Expected: pyarrow installed, lock file updated.

- [ ] **Step 3: Smoke check**

Run: `uv run python -c "import pyarrow.parquet as pq; print(pq.__name__)"`
Expected: `pyarrow.parquet`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add pyarrow for parquet lake reader"
```

---

### Task A2: Config setting for lake root

**Files:**
- Modify: `src/uw_scan/config.py`

- [ ] **Step 1: Add setting**

In `config.py`, find the `Settings` class and add (after the existing path-like settings):

```python
lake_vol_index_root: Path = Field(
    default=Path.home()
    / "market-warehouse/data-lake/bronze/asset_class=volatility",
    description=(
        "Local parquet lake root for CBOE vol indices and SPX daily OHLC. "
        "Symbol subdirs are named symbol=<TICKER>."
    ),
)
```

If `Path` and `Field` are not yet imported, add `from pathlib import Path` and `from pydantic import Field` as needed.

- [ ] **Step 2: Verify**

Run: `uv run python -c "from uw_scan.config import Settings; s = Settings(); print(s.lake_vol_index_root)"`
Expected: `/Users/chenxi/market-warehouse/data-lake/bronze/asset_class=volatility`

---

### Task A3: Migration 038 — vol_index_daily

**Files:**
- Create: `src/uw_scan/storage/migrations/038_vol_index_daily.sql`

- [ ] **Step 1: Write migration**

```sql
-- 038_vol_index_daily.sql
--
-- CBOE volatility index daily OHLC, sourced from the local parquet lake.
-- Covers SPX (filling the UW /ohlc/1d gap for indices) and the vol complex
-- (VIX, VIX3M, VVIX, COR1M, COR3M, OVX, RVX, VXN, VXEEM, etc.).
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vol_index_daily (
    symbol      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open        NUMERIC(14,4),
    high        NUMERIC(14,4),
    low         NUMERIC(14,4),
    close       NUMERIC(14,4),
    adj_close   NUMERIC(14,4),
    volume      BIGINT,
    PRIMARY KEY (symbol, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_vol_index_symbol_date
    ON uw_scan.vol_index_daily (symbol, trade_date DESC);

COMMIT;
```

- [ ] **Step 2: Apply**

Run: `bash scripts/migrate.sh`
Expected: migration 038 applied; re-running yields no-op.

- [ ] **Step 3: Verify table**

Run: `uv run python -c "
from uw_scan.api.deps import _conn
import os
conn = _conn()
with conn.cursor() as c:
    c.execute(\"SELECT to_regclass('uw_scan.vol_index_daily')\")
    print(c.fetchone())
"`
Expected: `('uw_scan.vol_index_daily',)`

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/storage/migrations/038_vol_index_daily.sql
git commit -m "feat(db): vol_index_daily for SPX OHLC and CBOE vol complex"
```

---

### Task A4: Lake reader

**Files:**
- Create: `src/uw_scan/sources/lake.py`
- Test: `tests/unit/test_lake_reader.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_lake_reader.py
"""Lake reader: parquet → list[dict] for vol_index_daily upserts."""

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from uw_scan.sources.lake import read_vol_index_parquet, list_vol_index_symbols


def _write_fixture(root: Path, symbol: str, rows: list[dict]) -> None:
    d = root / f"symbol={symbol}"
    d.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, d / "1d.parquet")


def test_read_vol_index_parquet_returns_rows(tmp_path: Path) -> None:
    _write_fixture(tmp_path, "VIX", [
        {"trade_date": date(2026, 5, 14), "open": 17.5, "high": 18.0,
         "low": 17.2, "close": 17.8, "adj_close": 17.8, "volume": 0},
        {"trade_date": date(2026, 5, 15), "open": 18.07, "high": 19.27,
         "low": 17.8, "close": 18.43, "adj_close": 18.43, "volume": 0},
    ])
    rows = read_vol_index_parquet(tmp_path, "VIX")
    assert len(rows) == 2
    assert rows[0]["symbol"] == "VIX"
    assert rows[0]["trade_date"] == date(2026, 5, 14)
    assert rows[1]["close"] == pytest.approx(18.43)


def test_read_vol_index_parquet_since(tmp_path: Path) -> None:
    _write_fixture(tmp_path, "VIX", [
        {"trade_date": date(2026, 5, 1), "open": 1, "high": 1, "low": 1,
         "close": 1, "adj_close": 1, "volume": 0},
        {"trade_date": date(2026, 5, 15), "open": 2, "high": 2, "low": 2,
         "close": 2, "adj_close": 2, "volume": 0},
    ])
    rows = read_vol_index_parquet(tmp_path, "VIX", since=date(2026, 5, 10))
    assert len(rows) == 1
    assert rows[0]["trade_date"] == date(2026, 5, 15)


def test_list_vol_index_symbols(tmp_path: Path) -> None:
    for sym in ["VIX", "VVIX", "SPX"]:
        (tmp_path / f"symbol={sym}").mkdir(parents=True)
        (tmp_path / f"symbol={sym}" / "1d.parquet").touch()
    syms = list_vol_index_symbols(tmp_path)
    assert set(syms) == {"VIX", "VVIX", "SPX"}


def test_read_missing_symbol_returns_empty(tmp_path: Path) -> None:
    assert read_vol_index_parquet(tmp_path, "NONEXISTENT") == []
```

- [ ] **Step 2: Run, verify fails**

Run: `uv run pytest tests/unit/test_lake_reader.py -v`
Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Implement**

```python
# src/uw_scan/sources/lake.py
"""Parquet reader for ~/market-warehouse/data-lake.

Used by the nightly vol_index_lake_sync job. No business logic — pure I/O.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

VOL_INDEX_FILENAME = "1d.parquet"


def list_vol_index_symbols(root: Path) -> list[str]:
    """Return all symbols under root/symbol=<TICKER>/1d.parquet."""
    if not root.exists():
        return []
    out: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not name.startswith("symbol="):
            continue
        if not (child / VOL_INDEX_FILENAME).exists():
            continue
        out.append(name[len("symbol=") :])
    return sorted(out)


def read_vol_index_parquet(
    root: Path,
    symbol: str,
    *,
    since: date | None = None,
) -> list[dict]:
    """Read symbol=<S>/1d.parquet → list[dict] with normalized columns.

    Output dicts contain: symbol, trade_date, open, high, low, close,
    adj_close, volume. Rows are sorted by trade_date ascending.
    """
    path = root / f"symbol={symbol}" / VOL_INDEX_FILENAME
    if not path.exists():
        return []
    table = pq.read_table(path)
    df = table.to_pandas()
    if "trade_date" not in df.columns:
        return []
    if since is not None:
        df = df[df["trade_date"] >= since]
    df = df.sort_values("trade_date")
    rows: list[dict] = []
    for r in df.itertuples(index=False):
        rd = r._asdict()
        rows.append(
            {
                "symbol": symbol,
                "trade_date": rd["trade_date"],
                "open": _maybe_float(rd.get("open")),
                "high": _maybe_float(rd.get("high")),
                "low": _maybe_float(rd.get("low")),
                "close": _maybe_float(rd.get("close")),
                "adj_close": _maybe_float(rd.get("adj_close")),
                "volume": int(rd["volume"]) if rd.get("volume") is not None else None,
            }
        )
    return rows


def _maybe_float(x) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f
```

- [ ] **Step 4: Run, verify passes**

Run: `uv run pytest tests/unit/test_lake_reader.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/lake.py tests/unit/test_lake_reader.py
git commit -m "feat(sources): parquet lake reader for vol_index_daily sync"
```

---

### Task A5: vol_index_repository

**Files:**
- Create: `src/uw_scan/storage/vol_index_repository.py`
- Test: `tests/integration/storage/test_vol_index_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/storage/test_vol_index_repository.py
from datetime import date

import pytest

from uw_scan.storage.vol_index_repository import VolIndexRepository


def test_upsert_inserts_then_updates(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.upsert_rows(
        [
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 15),
                "open": 18.07, "high": 19.27, "low": 17.8, "close": 18.43,
                "adj_close": 18.43, "volume": 0,
            }
        ]
    )
    repo.upsert_rows(
        [
            {
                "symbol": "VIX",
                "trade_date": date(2026, 5, 15),
                "open": 18.07, "high": 19.50, "low": 17.8, "close": 18.50,
                "adj_close": 18.50, "volume": 0,
            }
        ]
    )
    rows = repo.fetch_history("VIX", days=5)
    assert len(rows) == 1
    assert rows[0]["close"] == pytest.approx(18.50)
    assert rows[0]["high"] == pytest.approx(19.50)


def test_fetch_history_window(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema,
    )
    rows = [
        {"symbol": "VIX", "trade_date": date(2026, 5, d), "open": d, "high": d,
         "low": d, "close": d, "adj_close": d, "volume": 0}
        for d in range(1, 16)
    ]
    repo.upsert_rows(rows)
    out = repo.fetch_history("VIX", days=7)
    assert len(out) == 7
    # Sorted ascending by trade_date
    assert out[0]["trade_date"] < out[-1]["trade_date"]


def test_fetch_history_for_missing_symbol(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema,
    )
    assert repo.fetch_history("DOESNOTEXIST", days=30) == []
```

> **Note:** Integration tests require `UW_SCAN_TEST_DB_NAME` env var. Set it before running pytest (the existing conftest fails loudly without it).

- [ ] **Step 2: Run, verify fails**

Run: `uv run pytest tests/integration/storage/test_vol_index_repository.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/uw_scan/storage/vol_index_repository.py
"""Persistence for CBOE vol-complex and SPX daily OHLC sourced from the lake.

New domain — kept in its own file rather than extending the 5,000-line
repository.py.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date

from psycopg import Connection


class VolIndexRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_rows(self, rows: Iterable[dict]) -> int:
        """Insert or update vol_index_daily rows. Returns count."""
        rows = list(rows)
        if not rows:
            return 0
        sql = """
            INSERT INTO vol_index_daily
                (symbol, trade_date, open, high, low, close, adj_close, volume)
            VALUES
                (%(symbol)s, %(trade_date)s, %(open)s, %(high)s, %(low)s,
                 %(close)s, %(adj_close)s, %(volume)s)
            ON CONFLICT (symbol, trade_date) DO UPDATE SET
                open      = EXCLUDED.open,
                high      = EXCLUDED.high,
                low       = EXCLUDED.low,
                close     = EXCLUDED.close,
                adj_close = EXCLUDED.adj_close,
                volume    = EXCLUDED.volume
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
        self._conn.commit()
        return len(rows)

    def fetch_history(self, symbol: str, days: int) -> list[dict]:
        """Return up to `days` most-recent rows for symbol, ascending."""
        sql = """
            SELECT symbol, trade_date,
                   open::float8, high::float8, low::float8,
                   close::float8, adj_close::float8, volume
              FROM vol_index_daily
             WHERE symbol = %s
             ORDER BY trade_date DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (symbol, days))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows

    def latest_date_for(self, symbol: str) -> date | None:
        """Return latest trade_date stored, or None."""
        sql = "SELECT MAX(trade_date) FROM vol_index_daily WHERE symbol = %s"
        with self._conn.cursor() as cur:
            cur.execute(sql, (symbol,))
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    def fetch_multi_history(
        self, symbols: Sequence[str], days: int
    ) -> dict[str, list[dict]]:
        """Bulk variant — returns symbol → rows."""
        if not symbols:
            return {}
        sql = """
            SELECT symbol, trade_date, close::float8
              FROM vol_index_daily
             WHERE symbol = ANY(%s)
               AND trade_date >= (CURRENT_DATE - %s::int)
             ORDER BY symbol, trade_date
        """
        out: dict[str, list[dict]] = {s: [] for s in symbols}
        with self._conn.cursor() as cur:
            cur.execute(sql, (list(symbols), days))
            for sym, td, close in cur.fetchall():
                out[sym].append({"trade_date": td, "close": close})
        return out
```

- [ ] **Step 4: Run, verify passes**

Run: `uv run pytest tests/integration/storage/test_vol_index_repository.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/vol_index_repository.py \
        tests/integration/storage/test_vol_index_repository.py
git commit -m "feat(storage): VolIndexRepository — upsert + history reads"
```

---

### Task A6: Nightly sync job

**Files:**
- Create: `src/uw_scan/worker/jobs/vol_index_lake_sync.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Test: `tests/integration/test_vol_index_lake_sync.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_vol_index_lake_sync.py
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync


def _seed(root: Path, symbol: str, rows: list[dict]) -> None:
    d = root / f"symbol={symbol}"
    d.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), d / "1d.parquet")


def test_run_sync_inserts_all_symbols(
    tmp_path: Path, seeded_db_empty_cards
) -> None:
    pg_conn = seeded_db_empty_cards.conn
    _seed(tmp_path, "VIX", [
        {"trade_date": date(2026, 5, 14), "open": 17.5, "high": 18.0,
         "low": 17.2, "close": 17.8, "adj_close": 17.8, "volume": 0},
    ])
    _seed(tmp_path, "SPX", [
        {"trade_date": date(2026, 5, 14), "open": 7400, "high": 7450,
         "low": 7390, "close": 7430, "adj_close": 7430, "volume": 0},
    ])
    summary = run_vol_index_lake_sync(pg_conn, root=tmp_path)
    assert summary["symbols"] == 2
    assert summary["rows"] == 2
    repo = VolIndexRepository(pg_conn, schema="uw_scan")
    assert len(repo.fetch_history("VIX", days=5)) == 1
    assert len(repo.fetch_history("SPX", days=5)) == 1


def test_run_sync_incremental_refreshes_tail(
    tmp_path: Path, seeded_db_empty_cards
) -> None:
    """Incremental mode: re-upsert the latest row (in case its close changed
    intra-session) AND pull any strictly newer rows.

    Two-row return is the desired behavior — re-upsert is idempotent."""
    pg_conn = seeded_db_empty_cards.conn
    _seed(tmp_path, "VIX", [
        {"trade_date": date(2026, 5, 14), "open": 17.5, "high": 18.0,
         "low": 17.2, "close": 17.8, "adj_close": 17.8, "volume": 0},
    ])
    run_vol_index_lake_sync(pg_conn, root=tmp_path)
    # Append a newer row plus same-day refresh
    _seed(tmp_path, "VIX", [
        {"trade_date": date(2026, 5, 14), "open": 17.5, "high": 18.0,
         "low": 17.2, "close": 17.9, "adj_close": 17.9, "volume": 0},
        {"trade_date": date(2026, 5, 15), "open": 18.07, "high": 19.27,
         "low": 17.8, "close": 18.43, "adj_close": 18.43, "volume": 0},
    ])
    summary = run_vol_index_lake_sync(pg_conn, root=tmp_path)
    assert summary["rows"] == 2  # latest re-upsert + new row
    repo = VolIndexRepository(pg_conn, schema="uw_scan")
    rows = repo.fetch_history("VIX", days=5)
    assert len(rows) == 2
    # Refreshed close took effect
    assert rows[0]["close"] == pytest.approx(17.9)


def test_run_sync_empty_root_is_noop(
    tmp_path: Path, seeded_db_empty_cards
) -> None:
    summary = run_vol_index_lake_sync(
        seeded_db_empty_cards.conn, root=tmp_path,
    )
    assert summary == {"symbols": 0, "rows": 0}
```

- [ ] **Step 2: Run, verify fails**

Run: `uv run pytest tests/integration/test_vol_index_lake_sync.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement job**

```python
# src/uw_scan/worker/jobs/vol_index_lake_sync.py
"""Nightly: parquet lake → uw_scan.vol_index_daily.

Incremental: each symbol's max(trade_date) in the DB sets the lower bound for
the next read. First run backfills the entire history.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from psycopg import Connection

from uw_scan.sources.lake import (
    list_vol_index_symbols,
    read_vol_index_parquet,
)
from uw_scan.storage.vol_index_repository import VolIndexRepository

logger = logging.getLogger(__name__)


def run_vol_index_lake_sync(
    conn: Connection, *, root: Path
) -> dict:
    """Sync all symbols under root into uw_scan.vol_index_daily.

    Returns a summary dict: {symbols: int, rows: int}.
    """
    symbols = list_vol_index_symbols(root)
    if not symbols:
        logger.info("vol_index_lake_sync: no symbols at %s", root)
        return {"symbols": 0, "rows": 0}

    repo = VolIndexRepository(conn, schema="uw_scan")
    total = 0
    for symbol in symbols:
        latest = repo.latest_date_for(symbol)
        # Read from one day before latest (so we re-upsert the most recent
        # row in case it was a same-day snapshot that closed differently).
        since = (latest - timedelta(days=1)) if latest else None
        rows = read_vol_index_parquet(root, symbol, since=since)
        if rows:
            n = repo.upsert_rows(rows)
            total += n
            logger.info(
                "vol_index_lake_sync: %s — %d rows since %s", symbol, n, since
            )
    return {"symbols": len(symbols), "rows": total}
```

- [ ] **Step 4: Run, verify passes**

Run: `uv run pytest tests/integration/test_vol_index_lake_sync.py -v`
Expected: 3 passed.

- [ ] **Step 5: Register in scheduler**

In `src/uw_scan/worker/scheduler.py`, find the section where other cron jobs are registered. Add (near other nightly jobs):

```python
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

def _vol_index_sync_tick() -> None:
    settings = get_settings()
    with _conn_factory() as conn:
        run_vol_index_lake_sync(conn, root=settings.lake_vol_index_root)

scheduler.add_job(
    _vol_index_sync_tick,
    trigger=CronTrigger(hour=3, minute=15, timezone="America/New_York"),
    id="vol_index_lake_sync",
    name="vol_index_lake_sync",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
```

Adjust to match existing patterns in `scheduler.py` — use the same `_conn_factory()` / `get_settings()` helpers as adjacent jobs. If `CronTrigger` isn't already imported, add `from apscheduler.triggers.cron import CronTrigger`.

- [ ] **Step 6: Verify scheduler still imports cleanly**

Run: `uv run python -c "from uw_scan.worker.scheduler import build_scheduler; build_scheduler()"`
Expected: no traceback.

- [ ] **Step 7: One-time backfill (manual smoke)**

```bash
uv run python -c "
from pathlib import Path
from uw_scan.api.deps import _conn
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync
print(run_vol_index_lake_sync(_conn(), root=Path.home() / 'market-warehouse/data-lake/bronze/asset_class=volatility'))
"
```

Expected output approximately: `{'symbols': 14, 'rows': ~60000}` on first run (full backfill). Re-run = `~14` rows (just yesterday).

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/worker/jobs/vol_index_lake_sync.py \
        src/uw_scan/worker/scheduler.py \
        tests/integration/test_vol_index_lake_sync.py
git commit -m "feat(worker): nightly vol_index_daily sync from parquet lake"
```

---

## Phase B: GEX History Wiring

### Task B1: Migration 039 — greek_exposure_daily

**Files:**
- Create: `src/uw_scan/storage/migrations/039_greek_exposure_daily.sql`

- [ ] **Step 1: Write migration**

```sql
-- 039_greek_exposure_daily.sql
--
-- Daily history of UW's /greek-exposure for each watchlist ticker. The endpoint
-- returns ~250 trailing daily rows in every call; we persist the tail so the
-- regime page can render a 90-day history chart without re-fetching.
-- Idempotent.

SET search_path TO uw_scan, public;

BEGIN;

-- Columns mirror UW's /greek-exposure (history) payload exactly:
--   date, call_gex, put_gex, call_delta, put_delta
-- Computed convenience columns: net_gex, net_dex.
--
-- NOT stored here (UW doesn't return them in this payload):
--   - gex_flip (per-day): computed from per-strike GEX; we only have
--     today's via /greek-exposure/strike. Historical flip values come
--     from gex_snapshots over time (forward-only).
--   - price/spot: comes from daily_ohlc (ETFs) or vol_index_daily (SPX).
CREATE TABLE IF NOT EXISTS uw_scan.greek_exposure_daily (
    ticker         TEXT NOT NULL,
    trade_date     DATE NOT NULL,
    call_gex       NUMERIC(20,4),
    put_gex        NUMERIC(20,4),
    call_delta     NUMERIC(20,4),
    put_delta      NUMERIC(20,4),
    net_gex        NUMERIC(20,4) GENERATED ALWAYS AS (call_gex + put_gex) STORED,
    net_dex        NUMERIC(20,4) GENERATED ALWAYS AS (call_delta + put_delta) STORED,
    payload        JSONB,           -- raw row, for forward compatibility
    PRIMARY KEY (ticker, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_greek_exposure_daily_ticker_date
    ON uw_scan.greek_exposure_daily (ticker, trade_date DESC);

COMMIT;
```

- [ ] **Step 2: Apply**

Run: `bash scripts/migrate.sh`
Expected: 039 applied; re-running = no-op.

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/migrations/039_greek_exposure_daily.sql
git commit -m "feat(db): greek_exposure_daily — UW per-day GEX history"
```

---

### Task B1.5: Extract shared parser util (`cards/greek_exposure_history.py`)

**Why:** `fetch_aggregate_gex` currently lives inline at `scanners/gex.py:290-310`, parsing the UW `/greek-exposure` history payload into typed rows. The scanner uses it for `net_dex` computation; persistence will use it for daily history. Per user requirement, the **parse logic is shared, the fetcher stays distinct**.

**Files:**
- Create: `src/uw_scan/cards/greek_exposure_history.py`
- Modify: `src/uw_scan/scanners/gex.py` — replace the inline `fetch_aggregate_gex` body with a call to the new util
- Test: `tests/unit/test_greek_exposure_history_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_greek_exposure_history_parser.py
"""Pure parser tests — no DB, no network."""

from datetime import date

import pytest

from uw_scan.cards.greek_exposure_history import (
    parse_greek_exposure_history,
)


def test_parses_well_formed_payload() -> None:
    body = {
        "data": [
            {"date": "2026-05-14", "call_gex": "1000000000",
             "put_gex": "-500000000", "call_delta": "10000000",
             "put_delta": "-5000000"},
            {"date": "2026-05-15", "call_gex": "1100000000",
             "put_gex": "-550000000", "call_delta": "11000000",
             "put_delta": "-5500000"},
        ]
    }
    rows = parse_greek_exposure_history(body)
    assert len(rows) == 2
    assert rows[0]["date"] == date(2026, 5, 14)
    assert rows[0]["call_gex"] == pytest.approx(1e9)
    assert rows[0]["net_gex"] == pytest.approx(5e8)   # 1e9 + -5e8
    assert rows[0]["net_dex"] == pytest.approx(5e6)   # 1e7 + -5e6


def test_skips_malformed_rows() -> None:
    body = {
        "data": [
            {"date": "2026-05-14", "call_gex": "ok-string-not-number",
             "put_gex": "0", "call_delta": "0", "put_delta": "0"},
            {"date": "2026-05-15", "call_gex": "1", "put_gex": "1",
             "call_delta": "1", "put_delta": "1"},
        ]
    }
    rows = parse_greek_exposure_history(body)
    assert len(rows) == 1
    assert rows[0]["date"] == date(2026, 5, 15)


def test_handles_empty_or_missing_data() -> None:
    assert parse_greek_exposure_history({}) == []
    assert parse_greek_exposure_history({"data": None}) == []
    assert parse_greek_exposure_history({"data": []}) == []


def test_accepts_iso_date_strings_or_date_objects() -> None:
    body = {"data": [
        {"date": "2026-05-15", "call_gex": "1", "put_gex": "1",
         "call_delta": "1", "put_delta": "1"},
        {"date": date(2026, 5, 16), "call_gex": "1", "put_gex": "1",
         "call_delta": "1", "put_delta": "1"},
    ]}
    rows = parse_greek_exposure_history(body)
    assert rows[0]["date"] == date(2026, 5, 15)
    assert rows[1]["date"] == date(2026, 5, 16)
```

- [ ] **Step 2: Run, verify fails**

```bash
UW_SCAN_TEST_DB_NAME=skip uv run pytest tests/unit/test_greek_exposure_history_parser.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement util**

```python
# src/uw_scan/cards/greek_exposure_history.py
"""Pure parser for UW /greek-exposure (history aggregate) payload.

Used by:
- ``scanners/gex.py``   — to compute net_dex from the daily tail.
- ``scanners/gex.py``   — to feed ``greek_exposure_daily`` for the regime
                          history chart (via GreekExposureDailyRepository).

No DB, no network. Pure dict → list[dict] transformation.

Note: UW returns ``call_gex / put_gex / call_delta / put_delta`` per day
(aggregated across all strikes). It does NOT return historical gex_flip
or historical price — those have to come from other sources (our own
``gex_snapshots`` for flip, ``daily_ohlc`` / ``vol_index_daily`` for spot).
"""

from __future__ import annotations

from datetime import date
from typing import Any


def parse_greek_exposure_history(body: dict | None) -> list[dict]:
    """Body envelope → list of typed daily rows.

    Each output row carries:
        date, call_gex, put_gex, call_delta, put_delta,
        net_gex (call_gex + put_gex), net_dex (call_delta + put_delta).

    Malformed individual rows are dropped (logged downstream by caller),
    not raised — partial data is more useful than nothing for a history chart.
    """
    if not body or not isinstance(body, dict):
        return []
    raw = body.get("data") or []
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    for r in raw:
        try:
            d = _coerce_date(r.get("date"))
            if d is None:
                continue
            call_gex = float(r.get("call_gex", 0) or 0)
            put_gex = float(r.get("put_gex", 0) or 0)
            call_delta = float(r.get("call_delta", 0) or 0)
            put_delta = float(r.get("put_delta", 0) or 0)
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "date": d,
                "call_gex": call_gex,
                "put_gex": put_gex,
                "call_delta": call_delta,
                "put_delta": put_delta,
                "net_gex": call_gex + put_gex,
                "net_dex": call_delta + put_delta,
            }
        )
    out.sort(key=lambda r: r["date"])
    return out


def _coerce_date(v: Any) -> date | None:
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        try:
            return date.fromisoformat(v)
        except ValueError:
            return None
    return None
```

- [ ] **Step 4: Run, verify passes**

Run: `UW_SCAN_TEST_DB_NAME=skip uv run pytest tests/unit/test_greek_exposure_history_parser.py -v`
Expected: 4 passed.

- [ ] **Step 5: Refactor scanner to use the util**

In `src/uw_scan/scanners/gex.py`, find `fetch_aggregate_gex` (around line 290) and replace its body. The function is still the scanner's entry point for the parsed history, but it now delegates:

```python
def fetch_aggregate_gex(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[dict[str, Any]]:
    """Aggregate GEX time series (used for net_dex calculation + history persistence)."""
    from uw_scan.cards.greek_exposure_history import parse_greek_exposure_history
    body = uw_source.fetch_greek_exposure_history(client, repo, run_id, ticker)
    return parse_greek_exposure_history(body)
```

- [ ] **Step 6: Run all scanner tests**

Run: `uv run pytest tests/integration/test_gex_scanner.py -v`
Expected: all pass (no behavior change — util produces a superset of the old shape, with additional `net_gex` / `net_dex` keys callers can ignore).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/cards/greek_exposure_history.py \
        src/uw_scan/scanners/gex.py \
        tests/unit/test_greek_exposure_history_parser.py
git commit -m "refactor(cards): extract greek_exposure_history parser as shared util"
```

---

### Task B2: greek_exposure_repository

**Files:**
- Create: `src/uw_scan/storage/greek_exposure_repository.py`
- Test: `tests/integration/storage/test_greek_exposure_repository.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/storage/test_greek_exposure_repository.py
from datetime import date

import pytest

from uw_scan.storage.greek_exposure_repository import (
    GreekExposureDailyRepository,
)


def test_upsert_then_fetch(seeded_db_empty_cards) -> None:
    repo = GreekExposureDailyRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.upsert_rows(
        "SPY",
        [
            {
                "trade_date": date(2026, 5, 14),
                "call_gex": 2.1e9, "put_gex": -0.9e9,
                "call_delta": 7.0e7, "put_delta": -1.5e7,
                "payload": {"raw": "ok"},
            },
            {
                "trade_date": date(2026, 5, 15),
                "call_gex": 2.0e9, "put_gex": -1.0e9,
                "call_delta": 6.5e7, "put_delta": -1.5e7,
                "payload": {"raw": "ok"},
            },
        ],
    )
    rows = repo.fetch_history("SPY", days=10)
    assert len(rows) == 2
    # net_gex is a generated column = call_gex + put_gex
    assert rows[-1]["net_gex"] == pytest.approx(1.0e9)
    assert rows[-1]["net_dex"] == pytest.approx(5.0e7)


def test_upsert_overwrites_on_conflict(seeded_db_empty_cards) -> None:
    repo = GreekExposureDailyRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    base = {
        "trade_date": date(2026, 5, 15),
        "call_gex": 1.0, "put_gex": -1.0,
        "call_delta": 1.0, "put_delta": -1.0,
        "payload": {},
    }
    repo.upsert_rows("SPY", [base])
    repo.upsert_rows("SPY", [{**base, "call_gex": 99.0}])
    rows = repo.fetch_history("SPY", days=2)
    assert rows[0]["call_gex"] == pytest.approx(99.0)
    # Generated net_gex reflects the new call_gex
    assert rows[0]["net_gex"] == pytest.approx(98.0)
```

- [ ] **Step 2: Run, verify fails**

Run: `uv run pytest tests/integration/storage/test_greek_exposure_repository.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/uw_scan/storage/greek_exposure_repository.py
"""Persistence for UW /greek-exposure daily history. New domain — own file."""

from __future__ import annotations

from collections.abc import Iterable

from psycopg import Connection
from psycopg.types.json import Jsonb


class GreekExposureDailyRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_rows(self, ticker: str, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        params = [
            {
                "ticker": ticker,
                "trade_date": r["trade_date"],
                "call_gex": r.get("call_gex"),
                "put_gex": r.get("put_gex"),
                "call_delta": r.get("call_delta"),
                "put_delta": r.get("put_delta"),
                "payload": Jsonb(r.get("payload") or {}),
            }
            for r in rows
        ]
        sql = """
            INSERT INTO greek_exposure_daily
                (ticker, trade_date, call_gex, put_gex,
                 call_delta, put_delta, payload)
            VALUES
                (%(ticker)s, %(trade_date)s, %(call_gex)s, %(put_gex)s,
                 %(call_delta)s, %(put_delta)s, %(payload)s)
            ON CONFLICT (ticker, trade_date) DO UPDATE SET
                call_gex   = EXCLUDED.call_gex,
                put_gex    = EXCLUDED.put_gex,
                call_delta = EXCLUDED.call_delta,
                put_delta  = EXCLUDED.put_delta,
                payload    = EXCLUDED.payload
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def fetch_history(self, ticker: str, days: int) -> list[dict]:
        """Return up to `days` most-recent rows, ascending by trade_date."""
        sql = """
            SELECT ticker, trade_date,
                   call_gex::float8,   put_gex::float8,
                   call_delta::float8, put_delta::float8,
                   net_gex::float8,    net_dex::float8
              FROM greek_exposure_daily
             WHERE ticker = %s
             ORDER BY trade_date DESC
             LIMIT %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker, days))
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        rows.reverse()
        return rows
```

- [ ] **Step 4: Run, verify passes**

Run: `uv run pytest tests/integration/storage/test_greek_exposure_repository.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/greek_exposure_repository.py \
        tests/integration/storage/test_greek_exposure_repository.py
git commit -m "feat(storage): GreekExposureDailyRepository"
```

---

### Task B3: Scanner persists /greek-exposure tail

The shared parser is already in place (Task B1.5). Now the scanner calls it once for `net_dex` (existing path) AND feeds the parsed rows to `GreekExposureDailyRepository`.

**Files:**
- Modify: `src/uw_scan/scanners/gex.py`
- Test: `tests/integration/test_gex_scanner.py` (extend existing)

- [ ] **Step 1: Locate insertion point**

Read `src/uw_scan/scanners/gex.py` and find where `fetch_aggregate_gex` is called inside `run()` (the call point that consumes daily history for `net_dex`). Persistence will happen right after that call — we already have the parsed list at no extra cost.

- [ ] **Step 2: Write the failing test (extend existing scanner test file)**

Append to `tests/integration/test_gex_scanner.py`:

```python
def test_run_persists_greek_exposure_daily_tail(
    seeded_db_empty_cards: Repository,
    mock_client: UwClient,
    monkeypatch,
) -> None:
    """After a scan, the /greek-exposure history rows land in
    uw_scan.greek_exposure_daily — via the shared parser util.

    Uses the same `mock_client` + `seeded_db_empty_cards` fixtures as the
    other scanner tests in this file (see test_run_uses_stock_state_*
    above for the established pattern)."""
    from datetime import date

    from uw_scan.storage.greek_exposure_repository import (
        GreekExposureDailyRepository,
    )

    _stub_minimal_chain(monkeypatch)  # existing helper (line 127)
    monkeypatch.setattr(
        gex_scanner, "fetch_stock_state_snapshot",
        lambda c, r, rid, t: None,
    )

    # Override fetch_aggregate_gex (whose body now delegates to the shared
    # parser util — see Task B1.5) to return rows the scanner will both use
    # for net_dex AND persist into greek_exposure_daily.
    fake_rows = [
        {"date": date(2026, 5, 13), "call_gex": 2e9, "put_gex": -1e9,
         "call_delta": 1e7, "put_delta": -1e6,
         "net_gex": 1e9, "net_dex": 9e6},
        {"date": date(2026, 5, 14), "call_gex": 2.1e9, "put_gex": -1.0e9,
         "call_delta": 1.1e7, "put_delta": -1.1e6,
         "net_gex": 1.1e9, "net_dex": 9.9e6},
        {"date": date(2026, 5, 15), "call_gex": 1.9e9, "put_gex": -1.0e9,
         "call_delta": 0.9e7, "put_delta": -0.9e6,
         "net_gex": 0.9e9, "net_dex": 8.1e6},
    ]
    monkeypatch.setattr(
        gex_scanner, "fetch_aggregate_gex",
        lambda c, r, rid, t: fake_rows,
    )

    gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")

    daily_repo = GreekExposureDailyRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    rows = daily_repo.fetch_history("SPX", days=10)
    assert len(rows) == 3
    assert rows[-1]["call_gex"] == pytest.approx(1.9e9)
    assert rows[-1]["net_gex"] == pytest.approx(0.9e9)  # generated col
```

- [ ] **Step 3: Run, verify fails**

```bash
UW_SCAN_TEST_DB_NAME=uw_scan_test \
  uv run pytest tests/integration/test_gex_scanner.py::test_run_persists_greek_exposure_daily_tail -v
```
Expected: AssertionError (0 rows).

- [ ] **Step 4: Implement in scanner**

In `src/uw_scan/scanners/gex.py`, find where `fetch_aggregate_gex(client, repo, run_id, ticker)` is called inside `run()`. Right after that call, insert:

```python
# Persist the daily tail for the regime history chart. We already have
# the parsed rows in `gex_history` (or whatever the local name is from
# fetch_aggregate_gex above) — no extra UW call. Failures here are
# non-fatal: the scan's primary outcome is the snapshot row.
try:
    from uw_scan.storage.greek_exposure_repository import (
        GreekExposureDailyRepository,
    )
    GreekExposureDailyRepository(
        repo.conn, schema=repo._schema,
    ).upsert_rows(
        ticker,
        [
            {
                "trade_date": h["date"],
                "call_gex": h["call_gex"],
                "put_gex": h["put_gex"],
                "call_delta": h["call_delta"],
                "put_delta": h["put_delta"],
                "payload": h,
            }
            for h in gex_history
        ],
    )
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "greek_exposure_daily upsert failed for %s: %r", ticker, exc
    )
```

(Adjust `gex_history` to the local variable name from the existing `fetch_aggregate_gex` call.)

- [ ] **Step 5: Run all GEX scanner tests**

Run: `UW_SCAN_TEST_DB_NAME=uw_scan_test uv run pytest tests/integration/test_gex_scanner.py -v`
Expected: existing tests + new test all pass.

- [ ] **Step 6: Live smoke**

```bash
curl -s -X POST 'http://localhost:8400/api/regime/gex/scan?ticker=SPY' | jq .
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
s = Settings.from_env()
conn = psycopg.connect(s.db_dsn())
repo = GreekExposureDailyRepository(conn, schema=s.db_schema)
rows = repo.fetch_history('SPY', days=5)
print(f'{len(rows)} rows; latest: {rows[-1] if rows else None}')
"
```

Expected: ≥1 row for SPY.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/scanners/gex.py tests/integration/test_gex_scanner.py
git commit -m "feat(gex): persist /greek-exposure daily tail on every scan"
```

---

### Task B4: Extend GexResponse with history

**Files:**
- Modify: `src/uw_scan/api/schemas.py`
- Modify: `src/uw_scan/api/routers/regime.py`
- Test: `tests/integration/test_regime_history_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_regime_history_endpoint.py
from datetime import date

from fastapi.testclient import TestClient

from uw_scan.api.server import app
from uw_scan.storage.greek_exposure_repository import (
    GreekExposureDailyRepository,
)
from uw_scan.storage.vol_index_repository import VolIndexRepository


def _seed_history(repo_obj) -> None:
    schema = repo_obj._schema
    conn = repo_obj.conn
    g = GreekExposureDailyRepository(conn, schema=schema)
    g.upsert_rows("SPX", [
        {
            "trade_date": date(2026, 5, d),
            "call_gex": 2e9, "put_gex": -1e9,
            "call_delta": 1e7, "put_delta": -1e6,
            "payload": {},
        }
        for d in range(1, 16)
    ])
    v = VolIndexRepository(conn, schema=schema)
    v.upsert_rows([
        {"symbol": "SPX", "trade_date": date(2026, 5, d),
         "open": 7400 + d, "high": 7410 + d, "low": 7390 + d,
         "close": 7405 + d, "adj_close": 7405 + d, "volume": 0}
        for d in range(1, 16)
    ])


def test_gex_endpoint_returns_history_for_spx(seeded_db_empty_cards) -> None:
    _seed_history(seeded_db_empty_cards)
    client = TestClient(app)
    res = client.get("/api/regime/gex?ticker=SPX")
    assert res.status_code == 200
    body = res.json()
    assert "history" in body
    assert isinstance(body["history"], list)
    assert len(body["history"]) > 0
    entry = body["history"][-1]
    for k in ("date", "net_gex", "spot"):
        assert k in entry
    # net_gex is non-null (call_gex + put_gex = 1e9 from seed)
    assert entry["net_gex"] is not None
    # spot from vol_index_daily for SPX
    assert entry["spot"] is not None
```

- [ ] **Step 2: Run, verify fails**

Run: `uv run pytest tests/integration/test_regime_history_endpoint.py -v`
Expected: KeyError or 0-length history.

- [ ] **Step 3: Add schema**

In `src/uw_scan/api/schemas.py`, add (alongside `GexResponse`):

```python
class RegimeHistoryEntry(BaseModel):
    date: date
    net_gex: float | None = None
    net_dex: float | None = None
    gex_flip: float | None = None  # NULL pre-deployment; populated from gex_snapshots forward
    spot: float | None = None      # underlying close that day
```

> **gex_flip caveat:** UW's `/greek-exposure` history payload does NOT carry a per-day flip strike (only aggregated call_gex/put_gex). Per-day flip comes from our own `gex_snapshots` rows as they accumulate. The frontend should render `gex_flip` as a sparse line (gaps for pre-deployment dates).

Extend `GexResponse`:

```python
class GexResponse(BaseModel):
    # ... existing fields ...
    history: list[RegimeHistoryEntry] = Field(default_factory=list)
```

Update `EMPTY_GEX_RESPONSE` to include `history=[]`.

- [ ] **Step 4: Add assembler in router**

`Repository.conn` is already a public property (verified — line 586). `_schema` is accessed via the private attribute (matching the project's conftest pattern at line 99). No property additions needed.

In `src/uw_scan/api/routers/regime.py`, factor out a helper above `get_gex`:

```python
from uw_scan.storage.greek_exposure_repository import (
    GreekExposureDailyRepository,
)
from uw_scan.storage.vol_index_repository import VolIndexRepository

# Tickers whose spot history we source from the parquet lake (UW's
# /ohlc/1d is tier-blocked for indices; massive doesn't quote indices).
_SPOT_FROM_LAKE = {"SPX"}


def _assemble_history(repo: Repository, ticker: str, days: int = 90) -> list[dict]:
    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    gex_rows = g.fetch_history(ticker, days=days)
    if not gex_rows:
        return []

    if ticker in _SPOT_FROM_LAKE:
        v = VolIndexRepository(repo.conn, schema=repo._schema)
        spot_rows = v.fetch_history(ticker, days=days)
        spot_by_date = {r["trade_date"]: r["close"] for r in spot_rows}
    else:
        # ETFs: use daily_ohlc.close (massive). repo.fetch_daily_ohlc_history
        # returns rows ordered ascending by market_date.
        ohlc = repo.fetch_daily_ohlc_history(ticker=ticker, limit=days)
        spot_by_date = {r["market_date"]: float(r["close"]) for r in ohlc}

    # gex_snapshots flip migration — sparse, forward-only.
    flip_by_date = repo.fetch_flip_strike_history(ticker=ticker, limit=days)

    return [
        {
            "date": row["trade_date"],
            "net_gex": row["net_gex"],
            "net_dex": row["net_dex"],
            "gex_flip": flip_by_date.get(row["trade_date"]),
            "spot": spot_by_date.get(row["trade_date"]),
        }
        for row in gex_rows
    ]
```

> **Note:** `repo.fetch_daily_ohlc_history` and `repo.fetch_flip_strike_history` are not assumed to exist yet — they may or may not. **Before implementing this step**, run:
>
> ```bash
> rg "def fetch_daily_ohlc|def fetch.*flip|def.*gex_snapshots" src/uw_scan/storage/repository.py | head
> ```
>
> If absent, add them as small read methods in `repository.py` (these belong with the existing read API for `daily_ohlc` and `gex_snapshots` — they're not new domains, so the "no extending repository.py" rule doesn't apply). If `daily_ohlc.market_date` isn't the column name, adjust. Either way, the test in Step 2 will catch shape mismatches.

Modify `get_gex`:

```python
@router.get("/gex", response_model=GexResponse)
def get_gex(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query("SPX"),
) -> GexResponse:
    t = ticker.upper()
    raw = repo.fetch_latest_gex(ticker=t)
    history = _assemble_history(repo, t, days=90)
    if raw is None:
        empty = EMPTY_GEX_RESPONSE.model_copy(deep=True)
        empty.market_open = _is_market_open_now()
        empty.ticker = t
        empty.history = history
        return empty
    raw["market_open"] = _is_market_open_now()
    raw["history"] = history
    return GexResponse.model_validate(raw)
```

- [ ] **Step 5: Run, verify passes**

Run: `uv run pytest tests/integration/test_regime_history_endpoint.py -v`
Expected: 1 passed.

- [ ] **Step 6: Regen types**

```bash
cd web && npm run gen:types
```

Verify `web/lib/types.ts` has `history` array on the `GexResponse` interface.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/api/schemas.py src/uw_scan/api/routers/regime.py \
        src/uw_scan/storage/repository.py web/lib/types.ts \
        tests/integration/test_regime_history_endpoint.py
git commit -m "feat(api): /regime/gex returns 90-day history with SPX spot from lake"
```

---

### Task B5: Frontend HistoryChart component

**Files:**
- Create: `web/components/regime/HistoryChart.tsx`
- Create: `web/tests/unit/historyChart.test.tsx`
- Modify: `web/components/regime/GexSubTab.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/historyChart.test.tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { HistoryChart } from "@/components/regime/HistoryChart";

const sample = [
  { date: "2026-05-01", net_gex: 1e9, net_dex: 1e8, gex_flip: 7395, spot: 7400 },
  { date: "2026-05-02", net_gex: 1.1e9, net_dex: 1.1e8, gex_flip: 7398, spot: 7430 },
  { date: "2026-05-03", net_gex: 0.9e9, net_dex: 0.9e8, gex_flip: 7402, spot: 7408 },
];

describe("HistoryChart", () => {
  it("renders an SVG with the right title", () => {
    render(<HistoryChart history={sample} ticker="SPX" />);
    expect(screen.getByRole("img", { name: /history/i })).toBeTruthy();
  });

  it("renders empty state for no history", () => {
    render(<HistoryChart history={[]} ticker="SPX" />);
    expect(screen.getByText(/no history/i)).toBeTruthy();
  });

  it("plots net_gex line and gex_flip line", () => {
    const { container } = render(
      <HistoryChart history={sample} ticker="SPX" />,
    );
    const paths = container.querySelectorAll("path");
    // At least one path for net_gex and one for gex_flip migration
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });
});
```

- [ ] **Step 2: Run, verify fails**

Run: `cd web && npm run test -- historyChart`
Expected: file not found / import error.

- [ ] **Step 3: Implement component**

```tsx
// web/components/regime/HistoryChart.tsx
"use client";

import { linearScale, finiteDomain, pathFromPoints } from "@/lib/svgChart";
import type { GexHistoryEntry } from "@/lib/regime/useGex";

const WIDTH = 760;
const HEIGHT = 220;
const PAD = { top: 12, right: 56, bottom: 28, left: 56 };

export function HistoryChart({
  history,
  ticker,
}: {
  history: GexHistoryEntry[];
  ticker: string;
}) {
  if (!history.length) {
    return (
      <div
        style={{
          padding: "24px",
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}
      >
        No history available
      </div>
    );
  }

  const xScale = linearScale(
    [0, Math.max(history.length - 1, 1)],
    [PAD.left, WIDTH - PAD.right],
  );

  // finiteDomain returns {lo, hi, count} | null — null on <2 finite values
  const netGexD = finiteDomain(history.map((h) => h.net_gex));
  const priceD = finiteDomain(
    history.flatMap((h) => [h.spot, h.gex_flip]),
  );

  const yGex = netGexD
    ? linearScale([netGexD.lo, netGexD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;
  const yPrice = priceD
    ? linearScale([priceD.lo, priceD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;

  const netGexPath =
    yGex == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.net_gex == null ? null : [xScale(i), yGex(h.net_gex)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const flipPath =
    yPrice == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.gex_flip == null ? null : [xScale(i), yPrice(h.gex_flip)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const spotPath =
    yPrice == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.spot == null ? null : [xScale(i), yPrice(h.spot)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  return (
    <svg
      role="img"
      aria-label={`${ticker} 90-day GEX history`}
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      style={{ width: "100%", height: HEIGHT, display: "block" }}
    >
      <title>{`${ticker} — net GEX, flip migration, spot`}</title>

      {/* zero line for net GEX (only when scale exists and crosses zero) */}
      {yGex != null && netGexD != null && netGexD.lo <= 0 && netGexD.hi >= 0 && (
        <line
          x1={PAD.left}
          x2={WIDTH - PAD.right}
          y1={yGex(0)}
          y2={yGex(0)}
          stroke="var(--border-dim)"
          strokeDasharray="2 3"
        />
      )}

      {/* net_gex (left axis) */}
      <path
        d={netGexPath}
        fill="none"
        stroke="var(--accent-bg)"
        strokeWidth={1.5}
      />

      {/* gex_flip (right axis) */}
      <path
        d={flipPath}
        fill="none"
        stroke="var(--accent-warm)"
        strokeWidth={1.2}
        strokeDasharray="3 2"
      />

      {/* spot (right axis) */}
      <path
        d={spotPath}
        fill="none"
        stroke="var(--text-primary)"
        strokeWidth={1.2}
      />
    </svg>
  );
}
```

- [ ] **Step 4: Run, verify passes**

Run: `cd web && npm run test -- historyChart`
Expected: 3 passed.

- [ ] **Step 5: Mount in GexSubTab**

In `web/components/regime/GexSubTab.tsx`, find the spot below the metrics row (where the gamma profile chart sits) and add `<HistoryChart history={data.history} ticker={data.ticker} />` in an appropriate position (likely below the gamma profile, above the bias panel). Match surrounding section styling — section title, border-top spacing, etc.

- [ ] **Step 6: Typecheck**

Run: `cd web && npm run typecheck`
Expected: clean.

- [ ] **Step 7: Visual smoke (browser)**

If the dev stack is up on `3001`, open `http://localhost:3001/regime?ticker=SPX` and visually confirm:
- History chart renders with 3 series (net_gex green, gex_flip dashed warm, spot white)
- For SPX: spot line is non-flat (sourced from lake)
- For SPY: similar shape, sourced from in-row UW price

If the dev stack is not up, note it and skip — the test passes on data, not pixels.

- [ ] **Step 8: Commit**

```bash
git add web/components/regime/HistoryChart.tsx \
        web/components/regime/GexSubTab.tsx \
        web/tests/unit/historyChart.test.tsx
git commit -m "feat(regime): 90-day history chart with net_gex / flip / spot"
```

---

## Phase C: Vol Backdrop Endpoint + UI

### Task C1: /api/regime/vol-backdrop endpoint

**Files:**
- Modify: `src/uw_scan/api/schemas.py`
- Modify: `src/uw_scan/api/routers/regime.py`
- Test: `tests/integration/test_regime_vol_backdrop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/integration/test_regime_vol_backdrop.py
from datetime import date

import pytest
from fastapi.testclient import TestClient

from uw_scan.api.server import app
from uw_scan.storage.vol_index_repository import VolIndexRepository


def test_vol_backdrop_returns_four_series(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    for sym, base in [("VIX", 18), ("VIX3M", 21), ("VVIX", 90), ("COR1M", 11)]:
        repo.upsert_rows([
            {"symbol": sym, "trade_date": date(2026, 5, d),
             "open": base + d * 0.1, "high": base + d * 0.1,
             "low": base + d * 0.1, "close": base + d * 0.1,
             "adj_close": base + d * 0.1, "volume": 0}
            for d in range(1, 16)
        ])

    client = TestClient(app)
    res = client.get("/api/regime/vol-backdrop?days=10")
    assert res.status_code == 200
    body = res.json()
    assert set(body["series"].keys()) == {"VIX", "VIX3M", "VVIX", "COR1M"}
    assert len(body["series"]["VIX"]) <= 10
    assert body["series"]["VIX"][-1]["close"] > 0
    assert "term_structure_ratio" in body


def test_vol_backdrop_term_structure_ratio(seeded_db_empty_cards) -> None:
    repo = VolIndexRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    repo.upsert_rows([
        {"symbol": "VIX", "trade_date": date(2026, 5, 15),
         "open": 20, "high": 20, "low": 20, "close": 20,
         "adj_close": 20, "volume": 0},
        {"symbol": "VIX3M", "trade_date": date(2026, 5, 15),
         "open": 25, "high": 25, "low": 25, "close": 25,
         "adj_close": 25, "volume": 0},
    ])
    client = TestClient(app)
    res = client.get("/api/regime/vol-backdrop?days=5")
    body = res.json()
    # 20 / 25 = 0.80, contango
    assert body["term_structure_ratio"] == pytest.approx(0.80, rel=1e-2)
    assert body["term_structure_state"] == "contango"
```

- [ ] **Step 2: Run, verify fails**

Run: `uv run pytest tests/integration/test_regime_vol_backdrop.py -v`
Expected: 404.

- [ ] **Step 3: Add schemas**

In `src/uw_scan/api/schemas.py`:

```python
class VolBackdropPoint(BaseModel):
    date: date
    close: float

class VolBackdropResponse(BaseModel):
    series: dict[str, list[VolBackdropPoint]]
    term_structure_ratio: float | None = None  # VIX / VIX3M
    term_structure_state: str | None = None    # "contango" | "backwardation"
    as_of: date | None = None
```

- [ ] **Step 4: Add route**

In `src/uw_scan/api/routers/regime.py`:

```python
from uw_scan.api.schemas import VolBackdropResponse

_VOL_BACKDROP_SYMBOLS = ("VIX", "VIX3M", "VVIX", "COR1M")

@router.get("/vol-backdrop", response_model=VolBackdropResponse)
def get_vol_backdrop(
    repo: Annotated[Repository, Depends(get_repo)],
    days: int = Query(90, ge=5, le=365),
) -> VolBackdropResponse:
    v = VolIndexRepository(repo.conn, schema=repo._schema)
    multi = v.fetch_multi_history(_VOL_BACKDROP_SYMBOLS, days=days)

    series = {
        sym: [{"date": r["trade_date"], "close": r["close"]} for r in rows]
        for sym, rows in multi.items()
    }

    # Term structure: latest VIX / latest VIX3M
    latest_vix = series["VIX"][-1]["close"] if series.get("VIX") else None
    latest_vix3m = series["VIX3M"][-1]["close"] if series.get("VIX3M") else None
    ratio = None
    state = None
    as_of = None
    if latest_vix is not None and latest_vix3m:
        ratio = latest_vix / latest_vix3m
        state = "contango" if ratio < 1 else "backwardation"
        as_of = series["VIX"][-1]["date"]

    return VolBackdropResponse(
        series=series,
        term_structure_ratio=ratio,
        term_structure_state=state,
        as_of=as_of,
    )
```

- [ ] **Step 5: Run, verify passes**

Run: `uv run pytest tests/integration/test_regime_vol_backdrop.py -v`
Expected: 2 passed.

- [ ] **Step 6: Regen types**

```bash
cd web && npm run gen:types
```

Verify `VolBackdropResponse` shows up.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/api/schemas.py src/uw_scan/api/routers/regime.py \
        web/lib/types.ts tests/integration/test_regime_vol_backdrop.py
git commit -m "feat(api): /regime/vol-backdrop with VIX term-structure ratio"
```

---

### Task C2: useVolBackdrop hook

**Files:**
- Create: `web/lib/regime/useVolBackdrop.ts`

- [ ] **Step 1: Implement**

```typescript
// web/lib/regime/useVolBackdrop.ts
"use client";

import { regimeApi } from "./api";
import { useSyncHook, type UseSyncReturn } from "./useSyncHook";

export type VolBackdropPoint = { date: string; close: number };

export type VolBackdropData = {
  series: Record<"VIX" | "VIX3M" | "VVIX" | "COR1M", VolBackdropPoint[]>;
  term_structure_ratio: number | null;
  term_structure_state: "contango" | "backwardation" | null;
  as_of: string | null;
};

export function useVolBackdrop(): UseSyncReturn<VolBackdropData> {
  return useSyncHook<VolBackdropData>(
    {
      endpoint: regimeApi.vol_backdrop(),
      interval: 3_600_000, // 1h — slow data
      hasPost: false,
      extractTimestamp: (d) => d.as_of,
      shouldRetry: () => false,
      retryIntervalMs: 60_000,
      retryMethod: "GET",
    },
    true,
  );
}
```

Add `vol_backdrop` to `web/lib/regime/api.ts`. The file is an object literal — verified shape:

```typescript
// web/lib/regime/api.ts (add inside the regimeApi object, alongside gex/gex_scan)
vol_backdrop: () => `${API}/api/regime/vol-backdrop`,
```

Note the snake_case naming matches the existing convention (`gex_scan`, `cri_scan`, `vcg_scan`).

- [ ] **Step 2: Typecheck**

Run: `cd web && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add web/lib/regime/useVolBackdrop.ts web/lib/regime/api.ts
git commit -m "feat(regime): useVolBackdrop hook + api binding"
```

---

### Task C3: VolBackdropStrip component

**Files:**
- Create: `web/components/regime/VolBackdropStrip.tsx`
- Create: `web/tests/unit/volBackdropStrip.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/unit/volBackdropStrip.test.tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VolBackdropStripView } from "@/components/regime/VolBackdropStrip";

const sample = {
  series: {
    VIX: [
      { date: "2026-05-14", close: 18.1 },
      { date: "2026-05-15", close: 18.4 },
    ],
    VIX3M: [
      { date: "2026-05-14", close: 21.0 },
      { date: "2026-05-15", close: 21.4 },
    ],
    VVIX: [
      { date: "2026-05-14", close: 92.1 },
      { date: "2026-05-15", close: 92.9 },
    ],
    COR1M: [
      { date: "2026-05-14", close: 10.5 },
      { date: "2026-05-15", close: 10.8 },
    ],
  },
  term_structure_ratio: 0.86,
  term_structure_state: "contango" as const,
  as_of: "2026-05-15",
};

describe("VolBackdropStripView", () => {
  it("renders all four tiles", () => {
    render(<VolBackdropStripView data={sample} />);
    expect(screen.getByText("VIX")).toBeTruthy();
    expect(screen.getByText("VIX3M")).toBeTruthy();
    expect(screen.getByText("VVIX")).toBeTruthy();
    expect(screen.getByText("COR1M")).toBeTruthy();
  });

  it("shows term-structure state badge", () => {
    render(<VolBackdropStripView data={sample} />);
    expect(screen.getByText(/contango/i)).toBeTruthy();
  });

  it("renders nothing when data is null", () => {
    const { container } = render(<VolBackdropStripView data={null} />);
    expect(container.firstChild).toBeNull();
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// web/components/regime/VolBackdropStrip.tsx
"use client";

import { useVolBackdrop, type VolBackdropData } from "@/lib/regime/useVolBackdrop";
import { fmtDecimal } from "@/lib/formatters";

const SYMBOLS = ["VIX", "VIX3M", "VVIX", "COR1M"] as const;

const labels: Record<(typeof SYMBOLS)[number], string> = {
  VIX: "VIX",
  VIX3M: "VIX3M",
  VVIX: "VVIX",
  COR1M: "COR1M",
};

const tooltips: Record<(typeof SYMBOLS)[number], string> = {
  VIX: "S&P 500 30-day implied vol",
  VIX3M: "S&P 500 3-month implied vol",
  VVIX: "Vol-of-vol (VIX of VIX)",
  COR1M: "1-month implied correlation among S&P components",
};

function lastClose(points: { close: number }[] | undefined): number | null {
  if (!points || !points.length) return null;
  return points[points.length - 1].close;
}

function pctChange(points: { close: number }[] | undefined): number | null {
  if (!points || points.length < 2) return null;
  const prev = points[points.length - 2].close;
  const last = points[points.length - 1].close;
  if (!prev) return null;
  return ((last - prev) / prev) * 100;
}

export function VolBackdropStripView({ data }: { data: VolBackdropData | null }) {
  if (!data) return null;

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${SYMBOLS.length + 1}, 1fr)`,
        gap: 8,
        padding: "12px 16px",
        borderTop: "1px solid var(--border-dim)",
        borderBottom: "1px solid var(--border-dim)",
        background: "var(--bg-panel)",
      }}
    >
      {SYMBOLS.map((s) => {
        const close = lastClose(data.series[s]);
        const chg = pctChange(data.series[s]);
        return (
          <div key={s} title={tooltips[s]}>
            <div
              style={{
                fontSize: 10,
                letterSpacing: "0.15em",
                color: "var(--text-muted)",
                textTransform: "uppercase",
              }}
            >
              {labels[s]}
            </div>
            <div
              style={{
                fontSize: 18,
                fontWeight: 600,
                color: "var(--text-primary)",
                fontFamily: "var(--font-mono)",
              }}
            >
              {close != null ? fmtDecimal(close, 2) : "—"}
            </div>
            <div
              style={{
                fontSize: 11,
                color:
                  chg == null
                    ? "var(--text-muted)"
                    : chg >= 0
                      ? "var(--positive)"
                      : "var(--negative)",
              }}
            >
              {chg != null
                ? `${chg >= 0 ? "+" : ""}${fmtDecimal(chg, 2)}%`
                : "—"}
            </div>
          </div>
        );
      })}

      <div>
        <div
          style={{
            fontSize: 10,
            letterSpacing: "0.15em",
            color: "var(--text-muted)",
            textTransform: "uppercase",
          }}
        >
          Term Structure
        </div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 600,
            fontFamily: "var(--font-mono)",
            color:
              data.term_structure_state === "backwardation"
                ? "var(--warning)"
                : "var(--text-primary)",
          }}
        >
          {data.term_structure_ratio != null
            ? fmtDecimal(data.term_structure_ratio, 3)
            : "—"}
        </div>
        <div
          style={{
            fontSize: 11,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
            color:
              data.term_structure_state === "backwardation"
                ? "var(--warning)"
                : "var(--text-secondary)",
          }}
        >
          {data.term_structure_state ?? "—"}
        </div>
      </div>
    </div>
  );
}

export default function VolBackdropStrip() {
  const { data } = useVolBackdrop();
  return <VolBackdropStripView data={data ?? null} />;
}
```

- [ ] **Step 3: Run tests**

Run: `cd web && npm run test -- volBackdropStrip`
Expected: 3 passed.

- [ ] **Step 4: Commit**

```bash
git add web/components/regime/VolBackdropStrip.tsx \
        web/tests/unit/volBackdropStrip.test.tsx
git commit -m "feat(regime): vol backdrop strip — VIX/VIX3M/VVIX/COR1M + term structure"
```

---

### Task C4: Mount VolBackdropStrip on the regime page

Verified: `web/app/regime/page.tsx` exists and renders `<RegimePanel />`. The strip mounts in `page.tsx` above the panel so it stays visible across tab switches.

**Files:**
- Modify: `web/app/regime/page.tsx`

- [ ] **Step 1: Edit the regime page**

Current content (verified):

```tsx
import RegimePanel from "@/components/regime/RegimePanel";

export const metadata = { title: "Regime — Unusual Whales", ... };

export default function RegimePage() {
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">…</p>
      </header>
      <RegimePanel />
    </main>
  );
}
```

Add `VolBackdropStrip` between the header and `<RegimePanel />`:

```tsx
import RegimePanel from "@/components/regime/RegimePanel";
import VolBackdropStrip from "@/components/regime/VolBackdropStrip";

export default function RegimePage() {
  return (
    <main className="regime-page">
      <header className="regime-page-header">
        <h1>Regime</h1>
        <p className="regime-page-subtitle">…</p>
      </header>
      <VolBackdropStrip />
      <RegimePanel />
    </main>
  );
}
```

> **RSC note:** `page.tsx` is a Server Component. `VolBackdropStrip` is `"use client"` (it consumes `useVolBackdrop`), so it imports cleanly into the server page — Next.js handles the boundary.

- [ ] **Step 2: Typecheck**

Run: `cd web && npm run typecheck`
Expected: clean.

- [ ] **Step 3: Browser smoke**

If the dev stack is up, open the regime page and confirm:
- Four vol tiles render with values from the lake (VIX ~18, VVIX ~93, COR1M ~11)
- Term structure shows "CONTANGO" at a ratio around 0.86
- Strip stays mounted across ticker / tab switches

- [ ] **Step 4: Commit**

```bash
git add web/app/regime/page.tsx
git commit -m "feat(regime): mount VolBackdropStrip on regime page"
```

---

## Phase D: Final Verification

### Task D1: End-to-end smoke

- [ ] **Step 1: Full backend test suite**

Run: `UW_SCAN_TEST_DB_NAME=uw_scan_test uv run pytest`
Expected: all pass, no new warnings. (Integration tests refuse to run without the env var.)

- [ ] **Step 2: Full frontend test suite**

Run: `cd web && npm run test`
Expected: all pass.

- [ ] **Step 3: Typecheck**

Run: `cd web && npm run typecheck`
Expected: clean.

- [ ] **Step 4: One-time historical backfill**

```bash
uv run python -c "
import psycopg
from pathlib import Path
from uw_scan.config import Settings
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

s = Settings.from_env()
conn = psycopg.connect(s.db_dsn())
print(run_vol_index_lake_sync(conn,
      root=Path.home() / 'market-warehouse/data-lake/bronze/asset_class=volatility'))
"
```

Expected: ~60,000+ rows across ~14 symbols on first run. Re-running produces a near-zero count (just the most-recent rows refreshed).

- [ ] **Step 5: Force a GEX rescan for each watchlist ticker**

```bash
for t in SPX SPY QQQ IWM; do
  curl -s -X POST "http://localhost:8400/api/regime/gex/scan?ticker=$t" | jq .
done
```

Expected: 4 scans queued; greek_exposure_daily populated.

- [ ] **Step 6: Verify each API surface**

```bash
curl -s 'http://localhost:8400/api/regime/gex?ticker=SPX' | jq '{has_history: (.history | length > 0), latest: .history[-1]}'
curl -s 'http://localhost:8400/api/regime/vol-backdrop?days=30' | jq '.series | keys'
```

Expected:
- `has_history: true`, latest entry has non-null `spot` and `gex_flip`
- Keys: `["COR1M", "VIX", "VIX3M", "VVIX"]`

- [ ] **Step 7: Codex tribunal review**

Invoke the `codex-review` skill on the merged change set (uncommitted diff or PR).

- [ ] **Step 8: Open PR**

```bash
git push -u origin HEAD
gh pr create --title "feat(regime): 90-day history + vol-complex backdrop" \
  --body "$(cat <<'EOF'
## Summary
- Lake-sourced SPX OHLC closes the index-data gap (UW /ohlc/1d is tier-blocked)
- `vol_index_daily` table + nightly APScheduler sync from `~/market-warehouse/.../volatility/`
- `greek_exposure_daily` populated on every GEX scan from the existing `/greek-exposure` payload tail (no new UW calls)
- `/api/regime/gex` extended with a 90-day `history` array (net_gex / gex_flip / spot)
- New `/api/regime/vol-backdrop` returns VIX / VIX3M / VVIX / COR1M time series plus VIX-term-structure ratio
- Frontend: HistoryChart inside GexSubTab + VolBackdropStrip mounted on regime page

## Test plan
- [x] `uv run pytest` — full backend
- [x] `cd web && npm run test` — full vitest
- [x] `cd web && npm run typecheck`
- [x] Visual: regime page renders both new components for SPX/SPY/QQQ/IWM
- [x] Idempotency: re-running `vol_index_lake_sync` is a no-op
- [x] Codex tribunal review
EOF
)"
```

---

## Self-Review Notes

**Spec coverage:**
- SPX history gap → Tasks A3 + B4 (lake source wired)
- GEX 90-day chart → Tasks B1–B5
- Vol-complex backdrop → Tasks C1–C4
- "Different API call, shared util" → Task B1.5 extracts the parser; sources/uw.py fetchers stay distinct (history vs per-expiry)
- Persistence rule (results to Postgres) → all writes go through the new repositories

**Memory compliance:**
- ✅ No extension of `repository.py` for new persistence domains — `VolIndexRepository` and `GreekExposureDailyRepository` get their own files
- ✅ Yahoo not touched
- ✅ No IB dependency added
- ✅ uv only — all commands use `uv run`
- ✅ Migrations idempotent (`IF NOT EXISTS`, `ON CONFLICT`)

**Verification artifacts (raise confidence ~70% → ~90%):**
- ✅ `fetch_greek_exposure_history` exists at `sources/uw.py:210`
- ✅ `fetch_aggregate_gex` parser exists at `scanners/gex.py:290` (promoting to shared util)
- ✅ `Repository.conn` already public; `_schema` accessed directly per project convention
- ✅ `seeded_db_empty_cards` fixture is the integration-test entry point
- ✅ `finiteDomain` returns object (not tuple); HistoryChart code corrected
- ✅ `regimeApi` is an object literal with snake_case methods; `vol_backdrop` follows
- ✅ Regime page is `web/app/regime/page.tsx`; mount happens above `<RegimePanel />`
- ✅ Lake has 14 symbols, ~60K rows, updated through 2026-05-15

**Remaining unknowns (~8% risk):**
- `repo.fetch_daily_ohlc_history` / `repo.fetch_flip_strike_history` — Task B4 says "verify first, add if missing". Reads against existing tables (`daily_ohlc`, `gex_snapshots`); not a new domain. If missing, ~10 lines of SQL each.
- ✅ B3 test fixtures verified: `mock_client` is local to `test_gex_scanner.py:10`; `seeded_db_empty_cards` is in `tests/integration/conftest.py`. Both already in scope for the new test.

**Out of scope (deliberately deferred):**
- Backfilling `greek_exposure_daily` from historical scans pre-deployment — forward-only persistence. If older history is needed, a one-shot script walking `/greek-exposure` per ticker can fill the gap; the UW endpoint already returns ~250 trailing days per call.
- A "VIX vs flip" overlay on the `HistoryChart` — interesting but extra wiring.
- Per-day `gex_flip` historical column — UW doesn't expose it. Frontend renders it sparse, populated forward from our own `gex_snapshots`.

---

## Design Rationale & Data Flow

Captured from the design discussion before execution. Executors should read this section before starting Phase A — it explains *why* the plan is shaped the way it is, which informs how to handle edge cases that the per-task instructions don't anticipate.

### Two parallel pipelines

The plan has two independent data pipelines that only converge inside the React layer. They never share a fetcher, never share a table, never share an API endpoint.

**Pipeline 1 — Parquet lake → `vol_index_daily`**

```
~/market-warehouse/.../symbol=*/1d.parquet
    │
    ▼  (nightly 3:15 AM ET, also one-time backfill on first run)
sources/lake.py::read_vol_index_parquet
    │
    ▼  pure I/O, no math
worker/jobs/vol_index_lake_sync.py
    │
    ▼  upsert with since = latest_in_db - 1 day
uw_scan.vol_index_daily  (PK: symbol, trade_date)
    │
    ▼  read at request time
/api/regime/vol-backdrop  AND  /api/regime/gex (SPX spot column only)
    │
    ▼
useVolBackdrop / useGex hooks
    │
    ▼
<VolBackdropStrip /> AND <HistoryChart />
```

**Pipeline 2 — UW `/greek-exposure` → `greek_exposure_daily`**

```
UW: GET /api/stock/{ticker}/greek-exposure
    │
    ▼  fired on every GEX scan (manual /gex/scan, scheduled rescan-poll)
sources/uw.py::fetch_greek_exposure_history  (audit-first: writes api_request_audit + raw_payloads)
    │
    ▼
cards/greek_exposure_history.py::parse_greek_exposure_history  (pure parser — shared util)
    │
    ▼  same parsed rows consumed by TWO callers:
scanners/gex.py::run                                  GreekExposureDailyRepository.upsert_rows
    │ (existing net_dex calculation)                   │ (NEW)
    │                                                  ▼
    │                                       uw_scan.greek_exposure_daily
    │                                       (PK: ticker, trade_date; net_gex/net_dex are
    │                                        GENERATED ALWAYS AS (call_gex + put_gex / call_delta + put_delta))
    │                                                  │
    │                                                  ▼
    │                                       read at request time
    │                                       /api/regime/gex  (history array)
    │                                                  │
    │                                                  ▼
    │                                       useGex hook → <HistoryChart /> net_gex line
    ▼
(existing snapshot insert, unchanged)
```

### The three places "compute" happens

Math is intentionally tiny in this plan. Three places, no more:

1. **Parser** (`cards/greek_exposure_history.py`): `net_gex = call_gex + put_gex`, `net_dex = call_delta + put_delta`. Lets in-memory consumers skip a DB roundtrip.
2. **Postgres generated columns** (`greek_exposure_daily.net_gex`, `.net_dex`): same formula, recomputed by the DB. Guarantees parser-result and stored-result can never drift. Insurance against future bypass.
3. **API assembler** (`routers/regime.py`):
   - `_assemble_history()` — joins `greek_exposure_daily` × (`vol_index_daily` for SPX | `daily_ohlc` for ETFs) × `gex_snapshots.level_gex_flip_strike` into the response's `history[]`.
   - `term_structure_ratio = latest_VIX_close / latest_VIX3M_close`, `state = "contango" if ratio < 1 else "backwardation"`.

No model fitting, no rolling windows, no statistical work. Everything heavy was already done by the lake maintainer and by UW.

### Cadence table

| Step | When | Cost | Notes |
|---|---|---|---|
| Parquet read | Nightly 3:15 AM ET | ~14 symbols × ~7 row delta = sub-second | First run backfills ~60K rows in ~5 seconds |
| UW `/greek-exposure` fetch | Every GEX scan | ~250 rows parsed + upserted per scan | Already happens today; we're just persisting the tail |
| `/api/regime/gex` request | Dashboard load + 60s poll | One indexed read per source table | ~5ms typical |
| `/api/regime/vol-backdrop` request | Dashboard load + 1h poll | One indexed read per symbol | ~5ms typical |

### Reasoning behind major choices

**Why two pipelines instead of one?** Different upstream owners, different failure modes, different latencies. The lake is maintained by the `market-data-warehouse` peer project; UW is an external API. Coupling them via a unified fetcher means a parquet outage breaks UW persistence and vice versa.

**Why Postgres in the middle instead of reading parquet at request time?** Three reasons: (1) project rule — analytical results to Postgres; (2) parquet is great for batch reads but poor for "last 90 rows for one symbol" — has to read the whole file; (3) the API server already has Postgres connection pooling, adding a filesystem dependency per request is regression.

**Why a generated column for `net_gex` when the parser already computes it?** Guarantees the stored value is always `call_gex + put_gex`, even if a future code path bypasses the parser (manual backfill via SQL, downstream tool that writes directly). Cheap insurance.

**Why mount `VolBackdropStrip` at page level, not inside `RegimePanel`?** Vol regime is a *global* state — VIX doesn't change when you switch tickers or sub-tabs. Mounting once at the top means the data persists across tab switches and the hourly poll only fires once per session.

**Why is the gex_flip column NULL for pre-deployment dates?** UW does not expose historical per-day flip strikes — flip is computed from per-strike GEX, which they only give us for *today*. Our own `gex_snapshots` table captures flip going forward. Accepting this gap honestly beats faking it with interpolation.

### Risks in plain English (top 5)

1. **Nightly job silently skipping.** If the worker is down at 3:15 AM, the sync gets skipped without alarm. Mitigation deferred: add row count to `/health` endpoint as a follow-up. For v1, manual inspection.

2. **Parquet read race.** If the lake maintainer is writing during our sync window, we could see torn data. The lake writes atomically (write-temp-then-rename, standard pattern) so risk is low — but nonzero if the maintainer's tooling changes.

3. **UW payload shape change.** A renamed key (e.g., `call_gex` → `callGex`) would silently produce empty rows. Mitigation: parser's `float(r.get("call_gex"))` raises on type errors, which the loop catches and skips; integration tests assert specific keys exist on returned rows.

4. **Stale SPX history if lake stops updating.** Sync keeps running, but `vol_index_daily` stops gaining new dates. The history chart's spot line goes flat on the right edge. No surface alert. Worth surfacing via the `as_of` field on the response.

5. **Sparse flip line at launch.** `gex_flip` historical values populate forward-only from our scans. For the first few weeks, the flip line will be very thin and users may think it's a bug. Plan calls for graceful empty state; doesn't add explanatory UI copy. Worth a small annotation.
