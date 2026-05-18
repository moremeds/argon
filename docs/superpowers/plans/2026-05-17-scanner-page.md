# Scanner Page Implementation Plan

> **For agentic workers (Codex):** Execute milestones in order, top-to-bottom. Each milestone is a single commit landed at the end of that milestone. Steps use checkbox (`- [ ]`) syntax. Inside a milestone, follow each step in order: write failing test → run → minimal impl → run → next step. At end of milestone, run the full suite for the milestone, then commit with the message shown.

**Goal:** Replace the `/scanner` route stub with a working multi-signal scanner that ranks watchlist tickers by confluence and links each candidate to `/stock/[ticker]/trade-plan` for deep evaluation.

**Architecture:** Per-ticker detectors run as the final stage of `pipeline.run_single_stock()` against already-persisted UW data; results land in three new tables (`signal_hits`, `signal_context_flags`, `signal_gates`) keyed by `run_id`; `GET /api/scanner` joins those tables with `watchlist_cards` for the page; the page is an RSC tile-stack with client-side filter chips.

**Tech Stack:** Python 3.13 + `uv`, FastAPI, Pydantic v2, psycopg 3, Postgres `uw_scan` schema, APScheduler (worker), Next.js 16 RSC + React 19, Vitest + Playwright, pytest + pytest-postgresql.

**Reference spec:** `docs/superpowers/specs/2026-05-17-scanner-page-design.md` — every "spec §N" reference below points to that file. Read it before starting.

**Reference source (port):** `/Users/chenxi/projects/xenon/src/xenon/scanners/uw/` — the algorithmic reference, especially `signals/*.py`, `ranking.py`, `confluence.py`, `analysis/gex.py:50,122` for `detect_pinning` and `is_opex_week`. Differences from xenon are documented in spec §3 and respected below.

**Standing rules from `CLAUDE.md` you must honor without being reminded:**
- `uv run pytest`, never bare `pytest`. `uv sync --extra postgres` if dependencies look off.
- New persistence domain → **own module** (`storage/signals_repository.py`), never appended to `repository.py`. The standing rule is in `MEMORY.md`.
- Migrations are idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`). Re-running `bash scripts/migrate.sh` must be a no-op.
- `Decimal` over `float` for prices, scores, premiums. Use `psycopg.types.json.Jsonb` for jsonb columns.
- `from __future__ import annotations` at top of every new Python file.
- Frontend types come from `npm run gen:types` — never hand-edit `web/lib/types.ts`.
- **Commit messages: no `Co-Authored-By: Claude` trailers.** Write as if the human authored.

---

## File map

| Layer | Path | Action |
|---|---|---|
| Migration | `src/uw_scan/storage/migrations/045_scanner_signals.sql` | CREATE |
| Storage | `src/uw_scan/storage/signals_repository.py` | CREATE — `SignalsRepository(conn, schema)`, NOT a `Repository` mixin |
| Config | `src/uw_scan/config.py` | MODIFY — add 13 `SCANNER_*` fields + `from_env` overrides |
| Package | `src/uw_scan/scanner/__init__.py` | CREATE (empty) |
| Models | `src/uw_scan/scanner/models.py` | CREATE — `SignalHit`, `ContextFlag`, `ScanCandidate`, `GateResult` dataclasses |
| Calendars | `src/uw_scan/scanner/calendars.py` | CREATE — `is_opex_week` (port from `xenon/src/xenon/analysis/gex.py:122`) |
| Gates | `src/uw_scan/scanner/gates.py` | CREATE — `earnings_gate`, `liquidity_gate`, `regime_gate` |
| Ranking | `src/uw_scan/scanner/ranking.py` | CREATE — `build_candidate`, `rank_candidates` |
| Detectors | `src/uw_scan/scanner/signals/{__init__,deep_conviction_flow,dark_pool_accumulation,earnings_iv_crush,gex_pinning}.py` | CREATE |
| Context | `src/uw_scan/scanner/context/{__init__,pcr_sentiment}.py` | CREATE |
| Orchestrator | `src/uw_scan/scanner/pipeline.py` | CREATE — `run_detectors(repo, signals_repo, settings, run_id, ticker)` |
| Wire-in | `src/uw_scan/pipeline.py` | MODIFY at line 343 — call `run_detectors` before `finish_scan_run` |
| API model | `src/uw_scan/api/models/__init__.py`, `src/uw_scan/api/models/scanner.py` | CREATE — Pydantic v2 response models |
| API router | `src/uw_scan/api/routers/scanner.py` | CREATE — `GET /api/scanner` |
| Server reg | `src/uw_scan/api/server.py:19,44` | MODIFY — import + include router |
| Unit tests | `tests/unit/scanner/test_*.py` (7 files) | CREATE |
| Integration | `tests/integration/scanner/test_*.py` (3 files) | CREATE |
| Web page | `web/app/scanner/page.tsx` | MODIFY (replaces stub) |
| Web loading | `web/app/scanner/loading.tsx` | CREATE |
| Web API client | `web/lib/api.ts` | MODIFY — add `api.scanner` method + `ScannerResponse` type alias |
| Web components | `web/components/scanner/{CandidateTile,SignalBadge,ContextFlagBadge,GatesIndicator,GatedList,ScannerFilters}.tsx` | CREATE |
| Web types | `web/lib/types.ts` | REGENERATE via `npm run gen:types` |
| Vitest | `web/tests/unit/scannerPage.test.tsx` | CREATE — placed under `unit/` per project convention (verified `web/tests/unit/cardGrid.test.tsx`). `vitest.config.ts` glob is `tests/**/*.test.{ts,tsx}`. |
| Playwright | `web/tests/e2e/scanner-page.spec.ts` | CREATE — placed under `e2e/` per project convention (verified `web/tests/e2e/gold-page.spec.ts`) |

---

## Sanity baseline (before Milestone 1)

- [ ] **Confirm env vars.** Integration tests refuse to run if `UW_SCAN_TEST_DB_NAME` is unset (`tests/integration/conftest.py:27` calls `pytest.fail` to prevent pointing tests at the dev DB). Set it to a dedicated test database the developer has provisioned, e.g. `export UW_SCAN_TEST_DB_NAME=option_wizard_test`. Also confirm `UW_SCAN_API_KEY` is set (any non-empty value works for the worker code paths reachable from these tests — the conftest seeds a dummy when absent, but `Settings.from_env()` calls outside fixtures still require it).

- [ ] **Confirm clean baseline.** Run `uv run pytest -x -q` and `cd web && npm test -- --run && cd ..`. Both must pass green. If anything fails, STOP and report — do not start the plan on a red baseline.

---

## Milestone 1 — Persistence layer

**Files:**
- Create: `src/uw_scan/storage/migrations/045_scanner_signals.sql`
- Create: `src/uw_scan/storage/signals_repository.py`
- Create: `tests/integration/scanner/__init__.py`
- Create: `tests/integration/scanner/test_signals_repository.py`

**Why this first:** schema + writer is the foundation everything else writes against. Integration test (pytest-postgresql) verifies idempotent upsert and the read-window query before any detector cares.

- [ ] **1.1 Write the migration.** Create `src/uw_scan/storage/migrations/045_scanner_signals.sql` with exactly this content:

```sql
-- 045_scanner_signals.sql — idempotent. Spec §6.
-- Three tables for the scanner detector framework: positive hits,
-- zero-weight context flags (colored badges), and gate audit
-- (one row per (run, ticker) explaining why the ticker passed or
-- was suppressed). All FKs cascade on scan_runs deletion.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.signal_hits (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  signal_type     TEXT NOT NULL,
  tier            SMALLINT NOT NULL CHECK (tier IN (1, 2)),
  score           NUMERIC(6,3) NOT NULL CHECK (score >= 0.0 AND score <= 1.0),
  evidence        JSONB NOT NULL,
  freshness       TEXT NOT NULL CHECK (freshness IN ('live', 'stale', 'unavailable')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker, signal_type)
);
CREATE INDEX IF NOT EXISTS idx_signal_hits_ticker_signal_recent
  ON uw_scan.signal_hits (ticker, signal_type, inserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_hits_run
  ON uw_scan.signal_hits (run_id);

CREATE TABLE IF NOT EXISTS uw_scan.signal_context_flags (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  layer           TEXT NOT NULL,
  label           TEXT NOT NULL,
  value           NUMERIC(10,4),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker, layer)
);

CREATE TABLE IF NOT EXISTS uw_scan.signal_gates (
  run_id          BIGINT NOT NULL REFERENCES uw_scan.scan_runs(run_id) ON DELETE CASCADE,
  ticker          TEXT NOT NULL,
  earnings        TEXT NOT NULL CHECK (earnings IN ('pass', 'block')),
  liquidity       TEXT NOT NULL CHECK (liquidity IN ('pass', 'block')),
  regime          TEXT NOT NULL CHECK (regime IN ('pass', 'block')),
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (run_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_signal_gates_ticker_recent
  ON uw_scan.signal_gates (ticker, inserted_at DESC);

COMMENT ON TABLE uw_scan.signal_hits IS
  'One row per (run, ticker, signal) emission. Composite PK; ON CONFLICT DO UPDATE on retry.';
COMMENT ON TABLE uw_scan.signal_context_flags IS
  'Zero-weight badges (e.g., PCR sentiment).';
COMMENT ON TABLE uw_scan.signal_gates IS
  'Gate audit — enables the "why is this ticker missing" UX and identifies scanner-producing runs.';
```

- [ ] **1.2 Apply the migration.**

Run: `bash scripts/migrate.sh`
Expected: exits 0, prints applied filenames (or "no changes" if previously applied). Re-running it MUST also exit 0 (idempotency check).

Verify schema:

```bash
psql -h 127.0.0.1 -U chenxi -d option_wizard -c "\d uw_scan.signal_hits"
psql -h 127.0.0.1 -U chenxi -d option_wizard -c "\d uw_scan.signal_context_flags"
psql -h 127.0.0.1 -U chenxi -d option_wizard -c "\d uw_scan.signal_gates"
```

Expected: each shows the columns and PK from the migration.

- [ ] **1.3 Write the failing integration test.**

**Project fixture convention (verified):** Integration tests use the `seeded_db_empty_cards` (yields a `Repository`) and `seeded_db_with_cards` fixtures defined in `tests/integration/conftest.py`. They DROP+CREATE the `uw_scan` schema and re-run all migrations against a dedicated test DB pointed to by `UW_SCAN_TEST_DB_NAME`. **Codex: ensure `UW_SCAN_TEST_DB_NAME` is set in your shell before running any integration test — the conftest fails fast if it isn't.** There is no `pytest-postgresql` adapter despite what the CLAUDE.md mentions; the actual pattern is the one in `tests/integration/conftest.py`.

**Conftest is auto-visible to the new sub-package.** Pytest discovers `conftest.py` upward from the test file, so `tests/integration/conftest.py` fixtures are visible to `tests/integration/scanner/test_*.py` and to `tests/integration/api/test_scanner_endpoint.py` automatically — no copy or import needed. This is the same wiring `tests/integration/api/test_watchlist_endpoint.py` relies on today.

We still create `tests/integration/scanner/__init__.py` (empty) to match the convention of sibling sub-packages (`api/__init__.py`, `storage/__init__.py`).

Create `tests/integration/scanner/__init__.py` (empty file) and `tests/integration/scanner/test_signals_repository.py`:

```python
"""Integration tests for SignalsRepository."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_upsert_signal_hit_idempotent(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    # The fixture's seed includes a watchlist; pick any seeded ticker
    # (AAPL is in the standard 54-ticker seed).
    run_id = repo.insert_scan_run("AAPL", notes="signals test")

    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="AAPL",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.85"),
        evidence={"qualifying_alerts": 3, "total_premium": "1500000"},
        freshness="live",
    )
    sigs.upsert_signal_hit(
        run_id=run_id,
        ticker="AAPL",
        signal_type="deep_conviction_flow",
        tier=1,
        score=Decimal("0.90"),
        evidence={"qualifying_alerts": 4, "total_premium": "1800000"},
        freshness="live",
    )
    repo.conn.commit()

    hits = sigs.fetch_hits_for_run(run_id, "AAPL")
    assert len(hits) == 1
    assert hits[0]["score"] == Decimal("0.900")
    assert hits[0]["evidence"]["qualifying_alerts"] == 4


def test_upsert_context_flag_and_gate(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("TSLA", notes="signals test")

    sigs.upsert_context_flag(
        run_id=run_id,
        ticker="TSLA",
        layer="pcr_sentiment",
        label="Extreme Fear",
        value=Decimal("1.7500"),
    )
    sigs.upsert_gate(
        run_id=run_id,
        ticker="TSLA",
        earnings="pass",
        liquidity="block",
        regime="pass",
    )
    repo.conn.commit()

    flags = sigs.fetch_context_flags_for_run(run_id, "TSLA")
    assert flags == [
        {"layer": "pcr_sentiment", "label": "Extreme Fear", "value": Decimal("1.7500")}
    ]
    gate = sigs.fetch_gate_for_run(run_id, "TSLA")
    assert gate == {"earnings": "pass", "liquidity": "block", "regime": "pass"}


def test_fetch_dark_pool_window_filters_age_and_canceled(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("AAPL", notes="dp window test")

    now = datetime.now(timezone.utc)
    rows = [
        # Inside window, valid
        ("AAPL", 1, now - timedelta(days=1), Decimal("185.00"), 5000,
         Decimal("925000"), False),
        # Inside window, canceled — must be filtered
        ("AAPL", 2, now - timedelta(days=2), Decimal("185.10"), 5000,
         Decimal("925500"), True),
        # Outside 5-day window — must be filtered
        ("AAPL", 3, now - timedelta(days=10), Decimal("180.00"), 5000,
         Decimal("900000"), False),
        # Inside window, NULL premium — must be filtered
        ("AAPL", 4, now - timedelta(hours=2), Decimal("186.00"), 5000,
         None, False),
    ]
    with repo.conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO uw_scan.dark_pool_events
               (run_id, ticker, tracking_id, executed_at, price, size,
                premium, canceled)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            [(run_id, *r) for r in rows],
        )
    repo.conn.commit()

    prints = sigs.fetch_dark_pool_window("AAPL", lookback_days=5)
    assert len(prints) == 1
    assert prints[0]["tracking_id"] == 1
    assert prints[0]["premium"] == Decimal("925000")
```

- [ ] **1.4 Run the test, confirm it fails.**

Run: `uv run pytest tests/integration/scanner/test_signals_repository.py -v`
Expected: `ImportError` or `ModuleNotFoundError` for `uw_scan.storage.signals_repository`.

- [ ] **1.5 Implement `SignalsRepository`.** Create `src/uw_scan/storage/signals_repository.py`:

```python
"""Persistence for scanner detector outputs.

Standalone module — not a Repository mixin. Modelled on
provider_usage.py: takes its own psycopg connection (or shares one),
owns only scanner-related read/write methods, never appended to the
5,000+ line repository.py. See spec §7 and the standing rule in
MEMORY.md ("feedback_repository_split_threshold").

Read queries consumed by the API live here too — both halves of the
scanner persistence boundary stay in one file.
"""

from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

logger = logging.getLogger(__name__)


class SignalsRepository:
    """Read/write for signal_hits, signal_context_flags, signal_gates.

    The connection is provided by the caller (typically reusing the same
    psycopg.Connection that the main Repository uses inside
    pipeline.run_single_stock, so writes participate in the existing
    scan transaction).
    """

    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    # ------------------------------------------------------------------
    # Write API (called from scanner.pipeline.run_detectors)
    # ------------------------------------------------------------------

    def upsert_signal_hit(
        self,
        *,
        run_id: int,
        ticker: str,
        signal_type: str,
        tier: int,
        score: Decimal,
        evidence: dict[str, Any],
        freshness: str,
    ) -> None:
        sql = f"""
            INSERT INTO {self._schema}.signal_hits
              (run_id, ticker, signal_type, tier, score, evidence, freshness)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, ticker, signal_type) DO UPDATE SET
              tier = EXCLUDED.tier,
              score = EXCLUDED.score,
              evidence = EXCLUDED.evidence,
              freshness = EXCLUDED.freshness,
              inserted_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (run_id, ticker.upper(), signal_type, tier, score,
                 Jsonb(evidence), freshness),
            )

    def upsert_context_flag(
        self,
        *,
        run_id: int,
        ticker: str,
        layer: str,
        label: str,
        value: Decimal | None,
    ) -> None:
        sql = f"""
            INSERT INTO {self._schema}.signal_context_flags
              (run_id, ticker, layer, label, value)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id, ticker, layer) DO UPDATE SET
              label = EXCLUDED.label,
              value = EXCLUDED.value,
              inserted_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (run_id, ticker.upper(), layer, label, value))

    def upsert_gate(
        self,
        *,
        run_id: int,
        ticker: str,
        earnings: str,
        liquidity: str,
        regime: str,
    ) -> None:
        sql = f"""
            INSERT INTO {self._schema}.signal_gates
              (run_id, ticker, earnings, liquidity, regime)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (run_id, ticker) DO UPDATE SET
              earnings = EXCLUDED.earnings,
              liquidity = EXCLUDED.liquidity,
              regime = EXCLUDED.regime,
              inserted_at = NOW()
        """
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (run_id, ticker.upper(), earnings, liquidity, regime),
            )

    # ------------------------------------------------------------------
    # Read API (called from scanner.pipeline & api/routers/scanner)
    # ------------------------------------------------------------------

    def fetch_hits_for_run(self, run_id: int, ticker: str) -> list[dict[str, Any]]:
        sql = f"""
            SELECT signal_type, tier, score, evidence, freshness, inserted_at
            FROM {self._schema}.signal_hits
            WHERE run_id = %s AND ticker = %s
            ORDER BY tier ASC, signal_type ASC
        """
        return self._select_dicts(sql, (run_id, ticker.upper()))

    def fetch_context_flags_for_run(
        self, run_id: int, ticker: str
    ) -> list[dict[str, Any]]:
        sql = f"""
            SELECT layer, label, value
            FROM {self._schema}.signal_context_flags
            WHERE run_id = %s AND ticker = %s
            ORDER BY layer ASC
        """
        return self._select_dicts(sql, (run_id, ticker.upper()))

    def fetch_gate_for_run(self, run_id: int, ticker: str) -> dict[str, str] | None:
        sql = f"""
            SELECT earnings, liquidity, regime
            FROM {self._schema}.signal_gates
            WHERE run_id = %s AND ticker = %s
        """
        rows = self._select_dicts(sql, (run_id, ticker.upper()))
        return rows[0] if rows else None

    def fetch_dark_pool_window(
        self, ticker: str, *, lookback_days: int = 5
    ) -> list[dict[str, Any]]:
        """5-day rolling window of dark pool prints for a ticker.

        Matches xenon's 5-day aggregation (`xenon/analysis/ticker_data.py:321`)
        but reads from the already-persisted DB instead of re-fetching UW.
        Filters out canceled prints and rows with missing premium/price.
        """
        sql = f"""
            SELECT tracking_id, executed_at, price, size, premium,
                   nbbo_bid, nbbo_ask, market_center
            FROM {self._schema}.dark_pool_events
            WHERE ticker = %s
              AND executed_at >= NOW() - %s::interval
              AND COALESCE(canceled, FALSE) = FALSE
              AND premium IS NOT NULL
              AND price IS NOT NULL
            ORDER BY executed_at DESC
        """
        return self._select_dicts(
            sql, (ticker.upper(), f"{lookback_days} days")
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _select_dicts(
        self, sql: str, params: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
            if not rows:
                return []
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in rows]
```

- [ ] **1.6 Run the test, confirm it passes.**

Run: `uv run pytest tests/integration/scanner/test_signals_repository.py -v`
Expected: 3 passed.

- [ ] **1.7 Run full suite, no regression.**

Run: `uv run pytest -x -q`
Expected: all green.

- [ ] **1.8 Commit milestone.**

```bash
git add src/uw_scan/storage/migrations/045_scanner_signals.sql \
        src/uw_scan/storage/signals_repository.py \
        tests/integration/scanner/__init__.py \
        tests/integration/scanner/test_signals_repository.py
git commit -m "feat(scanner): add signal_hits/context_flags/gates schema + SignalsRepository

Migration 045 creates the three scanner tables keyed on
(run_id, ticker[, signal_type|layer]) with composite PKs for
idempotent ON CONFLICT DO UPDATE writes from the worker.

SignalsRepository is a standalone module (modeled on
provider_usage.py) — never appended to repository.py per the
standing 5k-line rule. Read API includes fetch_dark_pool_window
which the dark_pool_accumulation detector uses for its 5-day
rolling window (replacing xenon's re-fetch path).

Spec §6 + §7."
```

---

## Milestone 2 — Scanner framework (models + calendars + config + gates + ranking)

**Files:**
- Create: `src/uw_scan/scanner/__init__.py`
- Create: `src/uw_scan/scanner/models.py`
- Create: `src/uw_scan/scanner/calendars.py`
- Create: `src/uw_scan/scanner/gates.py`
- Create: `src/uw_scan/scanner/ranking.py`
- Modify: `src/uw_scan/config.py` (add `SCANNER_*` settings)
- Create: `tests/unit/scanner/__init__.py`
- Create: `tests/unit/scanner/test_calendars.py`
- Create: `tests/unit/scanner/test_gates.py`
- Create: `tests/unit/scanner/test_ranking.py`

**Why bundled:** these are five small, tightly-coupled pure-Python modules with no external I/O. Bundling lets us land the entire framework as one commit and the detectors then have a stable substrate to compose against.

- [ ] **2.1 Create the package directory and add scanner config fields to `Settings`.**

Create `src/uw_scan/scanner/__init__.py` as an empty file.

Open `src/uw_scan/config.py`. Inside `class Settings(BaseModel):` (currently ends around line 96 with `cockpit_oi_max_dte: int = 7`), append after the cockpit block:

```python
    # Scanner (spec §10). Hits older than this fall to GATED reason=stale_scan;
    # default matches bucketFreshness "stale" threshold (180min) in
    # web/lib/freshness.ts so API window and UI label agree.
    scanner_freshness_hours: int = 3
    scanner_dp_lookback_days: int = 5
    scanner_dcf_min_premium_usd: Decimal = Decimal("500000")
    scanner_dcf_min_ask_side: Decimal = Decimal("0.80")
    scanner_dcf_max_moneyness: Decimal = Decimal("0.12")
    scanner_dcf_min_dte: int = 6
    scanner_dp_min_print_premium_usd: Decimal = Decimal("1000000")
    scanner_dp_min_cluster_size: int = 3
    scanner_dp_price_spread_pct: Decimal = Decimal("0.5")
    scanner_eic_min_iv_rank: Decimal = Decimal("75.0")
    scanner_gex_pin_min_gamma: Decimal = Decimal("1.0")
    scanner_liquidity_min_option_volume: int = 1000
    scanner_regime_block_chips: list[str] = ["SUSPENDED", "DEGRADED"]
    scanner_earnings_window_days: int = 14
```

Inside `from_env(...)`, add the env-override mappings just before the `return cls(...)` ends. Find the final field in the `return cls(...)` call (the trade_insights / cockpit block) and append the scanner overrides (use the same Decimal-from-string and CSV-list-parsing patterns the existing code uses; if you see a comma-list helper for cockpit, reuse it — otherwise inline `os.environ.get("SCANNER_REGIME_BLOCK_CHIPS", "SUSPENDED,DEGRADED").split(",")` stripped of whitespace).

Exact additions to `return cls(...)`:

```python
            scanner_freshness_hours=int(
                os.environ.get("SCANNER_FRESHNESS_HOURS", "3")
            ),
            scanner_dp_lookback_days=int(
                os.environ.get("SCANNER_DP_LOOKBACK_DAYS", "5")
            ),
            scanner_dcf_min_premium_usd=Decimal(
                os.environ.get("SCANNER_DCF_MIN_PREMIUM_USD", "500000")
            ),
            scanner_dcf_min_ask_side=Decimal(
                os.environ.get("SCANNER_DCF_MIN_ASK_SIDE", "0.80")
            ),
            scanner_dcf_max_moneyness=Decimal(
                os.environ.get("SCANNER_DCF_MAX_MONEYNESS", "0.12")
            ),
            scanner_dcf_min_dte=int(
                os.environ.get("SCANNER_DCF_MIN_DTE", "6")
            ),
            scanner_dp_min_print_premium_usd=Decimal(
                os.environ.get("SCANNER_DP_MIN_PRINT_PREMIUM_USD", "1000000")
            ),
            scanner_dp_min_cluster_size=int(
                os.environ.get("SCANNER_DP_MIN_CLUSTER_SIZE", "3")
            ),
            scanner_dp_price_spread_pct=Decimal(
                os.environ.get("SCANNER_DP_PRICE_SPREAD_PCT", "0.5")
            ),
            scanner_eic_min_iv_rank=Decimal(
                os.environ.get("SCANNER_EIC_MIN_IV_RANK", "75.0")
            ),
            scanner_gex_pin_min_gamma=Decimal(
                os.environ.get("SCANNER_GEX_PIN_MIN_GAMMA", "1.0")
            ),
            scanner_liquidity_min_option_volume=int(
                os.environ.get("SCANNER_LIQUIDITY_MIN_OPTION_VOLUME", "1000")
            ),
            scanner_regime_block_chips=[
                s.strip()
                for s in os.environ.get(
                    "SCANNER_REGIME_BLOCK_CHIPS", "SUSPENDED,DEGRADED"
                ).split(",")
                if s.strip()
            ],
            scanner_earnings_window_days=int(
                os.environ.get("SCANNER_EARNINGS_WINDOW_DAYS", "14")
            ),
```

Run: `uv run python -c "from uw_scan.config import Settings; print(Settings.from_env().scanner_dcf_min_premium_usd)"`
Expected: `500000`. If you get a `RuntimeError` about `UW_SCAN_API_KEY`, that's the existing required-field guard — set it in `.env` or temporarily `UW_SCAN_API_KEY=x uv run python -c "..."`.

- [ ] **2.2 Write the failing tests for calendars + gates + ranking.**

Create `tests/unit/scanner/__init__.py` (empty).

Create `tests/unit/scanner/test_calendars.py`:

```python
"""is_opex_week port — verifies 3rd-Friday-of-month detection."""

from __future__ import annotations

from datetime import date

from uw_scan.scanner.calendars import is_opex_week


def test_opex_week_third_friday_returns_true():
    # 2025-12-19 was the 3rd Friday of Dec 2025
    assert is_opex_week(date(2025, 12, 19)) is True


def test_three_days_before_third_friday_is_opex_week():
    # 2025-12-16 is Tuesday — 3 days before 3rd-Friday Dec 19
    assert is_opex_week(date(2025, 12, 16)) is True


def test_more_than_three_days_before_third_friday_is_not_opex_week():
    # 2025-12-15 is Monday — 4 days before; outside window
    assert is_opex_week(date(2025, 12, 15)) is False


def test_day_after_third_friday_not_opex_week():
    assert is_opex_week(date(2025, 12, 20)) is False


def test_january_2026_third_friday():
    # 2026-01-16 is 3rd Friday of January
    assert is_opex_week(date(2026, 1, 16)) is True
    assert is_opex_week(date(2026, 1, 13)) is True   # Tuesday, 3 days before
    assert is_opex_week(date(2026, 1, 12)) is False
```

Create `tests/unit/scanner/test_gates.py`:

```python
"""Gate logic — earnings (advisory), liquidity (advisory), regime (hard)."""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.scanner.gates import (
    earnings_gate,
    liquidity_gate,
    regime_gate,
)


TODAY = date(2026, 5, 17)


def test_earnings_gate_passes_when_earnings_more_than_14_days_away():
    assert earnings_gate(
        next_earnings_date=TODAY + timedelta(days=20),
        today=TODAY,
        window_days=14,
    ) == "pass"


def test_earnings_gate_blocks_when_earnings_within_14_days():
    assert earnings_gate(
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        window_days=14,
    ) == "block"


def test_earnings_gate_blocks_when_earnings_unknown():
    # Conservative-block per xenon _parse_next_earnings.
    assert earnings_gate(
        next_earnings_date=None, today=TODAY, window_days=14
    ) == "block"


def test_liquidity_gate_passes_at_threshold():
    assert liquidity_gate(option_volume=1000, min_volume=1000) == "pass"


def test_liquidity_gate_blocks_below_threshold():
    assert liquidity_gate(option_volume=999, min_volume=1000) == "block"


def test_liquidity_gate_blocks_on_none():
    assert liquidity_gate(option_volume=None, min_volume=1000) == "block"


def test_regime_gate_passes_on_favorable():
    assert regime_gate(
        structural_posture_chip="FAVORABLE",
        block_chips=("SUSPENDED", "DEGRADED"),
    ) == "pass"


def test_regime_gate_blocks_on_suspended():
    assert regime_gate(
        structural_posture_chip="SUSPENDED",
        block_chips=("SUSPENDED", "DEGRADED"),
    ) == "block"


def test_regime_gate_blocks_on_degraded():
    assert regime_gate(
        structural_posture_chip="DEGRADED",
        block_chips=("SUSPENDED", "DEGRADED"),
    ) == "block"


def test_regime_gate_fails_open_on_missing_posture():
    # Per spec §4: missing posture → treat as NEUTRAL (pass). The
    # scanner must not freeze just because GOLD hasn't run yet.
    assert regime_gate(
        structural_posture_chip=None,
        block_chips=("SUSPENDED", "DEGRADED"),
    ) == "pass"


def test_regime_gate_respects_custom_block_chips():
    # Allow operator to widen blocking via env override.
    assert regime_gate(
        structural_posture_chip="STRETCHED",
        block_chips=("STRETCHED", "SUSPENDED", "DEGRADED"),
    ) == "block"
```

Create `tests/unit/scanner/test_ranking.py`:

```python
"""build_candidate and rank_candidates — DP-only suppression + ordering."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.scanner.models import ContextFlag, ScanCandidate, SignalHit
from uw_scan.scanner.ranking import build_candidate, rank_candidates


def _hit(signal_type: str, tier: int, score: str) -> SignalHit:
    return SignalHit(
        ticker="AAPL",
        signal_type=signal_type,
        tier=tier,
        score=Decimal(score),
        evidence={},
        freshness="live",
    )


def test_dp_only_ticker_produces_no_candidate():
    cand = build_candidate(
        ticker="AAPL",
        hits=[_hit("dark_pool_accumulation", 2, "0.50")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is None


def test_dcf_only_ticker_produces_candidate_not_type_f():
    cand = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.70")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is not None
    assert cand.is_type_f is False
    # raw = 0.70 * 3.0 = 2.10; confluence = 3.0; final = 5.10
    assert cand.raw_score == Decimal("2.10")
    assert cand.confluence_score == Decimal("3.0")
    assert cand.final_score == Decimal("5.10")


def test_dcf_plus_eic_is_type_f_with_correct_score():
    cand = build_candidate(
        ticker="AAPL",
        hits=[
            _hit("deep_conviction_flow", 1, "0.85"),
            _hit("dark_pool_accumulation", 2, "0.40"),
            _hit("earnings_iv_crush", 1, "0.72"),
        ],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand is not None
    assert cand.is_type_f is True
    # raw = 0.85*3 + 0.72*3 = 4.71; conf = 3 + 1.5 + 3 = 7.5; final = 12.21
    assert cand.raw_score == Decimal("4.71")
    assert cand.confluence_score == Decimal("7.5")
    assert cand.final_score == Decimal("12.21")


def test_rank_candidates_orders_type_f_first_then_score_then_ticker():
    type_f = build_candidate(
        ticker="AAPL",
        hits=[
            _hit("deep_conviction_flow", 1, "0.85"),
            _hit("earnings_iv_crush", 1, "0.72"),
        ],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    big_single = build_candidate(
        ticker="MSFT",
        hits=[_hit("deep_conviction_flow", 1, "1.0")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    small_single = build_candidate(
        ticker="ZZZZ",
        hits=[_hit("deep_conviction_flow", 1, "0.50")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert type_f is not None and big_single is not None and small_single is not None
    ranked = rank_candidates([small_single, big_single, type_f])
    assert [c.ticker for c in ranked] == ["AAPL", "MSFT", "ZZZZ"]


def test_context_flags_passthrough_does_not_affect_score():
    flag = ContextFlag(
        ticker="AAPL", layer="pcr_sentiment",
        label="Extreme Fear", value=Decimal("1.7"),
    )
    cand_with = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.85")],
        context_flags=[flag],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    cand_without = build_candidate(
        ticker="AAPL",
        hits=[_hit("deep_conviction_flow", 1, "0.85")],
        context_flags=[],
        gates={"earnings": "pass", "liquidity": "pass", "regime": "pass"},
    )
    assert cand_with is not None and cand_without is not None
    assert cand_with.final_score == cand_without.final_score
    assert cand_with.context_flags == [flag]
```

- [ ] **2.3 Run the tests, confirm they fail.**

Run: `uv run pytest tests/unit/scanner -v`
Expected: `ModuleNotFoundError` for `uw_scan.scanner.calendars`, `uw_scan.scanner.gates`, `uw_scan.scanner.ranking`, `uw_scan.scanner.models`.

- [ ] **2.4 Implement `scanner/models.py`.**

```python
"""Scanner domain models — Decimal-based dataclasses.

Mirrors xenon/scanners/uw/models.py shape but uses Decimal for monetary
and scoring fields per project convention. ScanCandidate carries gates
so the API can surface advisory pass/block on the candidate tile
(spec §8 ScannerGatesStatus).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


@dataclass(frozen=True)
class SignalHit:
    ticker: str
    signal_type: str
    tier: Literal[1, 2]
    score: Decimal
    evidence: dict[str, Any]
    freshness: Literal["live", "stale", "unavailable"] = "live"


@dataclass(frozen=True)
class ContextFlag:
    ticker: str
    layer: str
    label: str
    value: Decimal | None


@dataclass(frozen=True)
class ScanCandidate:
    ticker: str
    hits: list[SignalHit]
    context_flags: list[ContextFlag]
    raw_score: Decimal
    confluence_score: Decimal
    final_score: Decimal
    is_type_f: bool
    gates: dict[str, str] = field(default_factory=dict)
```

- [ ] **2.5 Implement `scanner/calendars.py`.**

```python
"""Port of xenon/src/xenon/analysis/gex.py:122 — is_opex_week."""

from __future__ import annotations

from datetime import date, timedelta


def is_opex_week(today: date) -> bool:
    """True if `today` is within 3 calendar days before the 3rd Friday."""
    first_day = today.replace(day=1)
    first_friday_offset = (4 - first_day.weekday()) % 7
    third_friday = first_day + timedelta(days=first_friday_offset + 14)
    delta = (third_friday - today).days
    return 0 <= delta <= 3
```

- [ ] **2.6 Implement `scanner/gates.py`.**

```python
"""Gates — pre-detection filters.

Only regime_gate is a hard block. earnings_gate and liquidity_gate are
ADVISORY: their pass/block status is recorded per (run, ticker) and
returned to the UI as a colored indicator, but they do NOT suppress
the candidate. Reason: earnings_iv_crush REQUIRES earnings within 14d
to fire — a hard earnings block would prevent EIC from ever emitting.
(Spec §4.)
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Literal

GateStatus = Literal["pass", "block"]


def earnings_gate(
    *,
    next_earnings_date: date | None,
    today: date,
    window_days: int = 14,
) -> GateStatus:
    """Advisory. Pass when earnings is known AND > window_days away.

    Conservative-block on unknown (matches xenon `_parse_next_earnings`
    returning `(None, True)` — better to advise caution than to assert
    safety the data can't prove).
    """
    if next_earnings_date is None:
        return "block"
    return "pass" if (next_earnings_date - today).days > window_days else "block"


def liquidity_gate(
    *,
    option_volume: int | None,
    min_volume: int = 1000,
) -> GateStatus:
    """Advisory. Pass when the run's total FlowAlert.volume ≥ min_volume."""
    if option_volume is None:
        return "block"
    return "pass" if option_volume >= min_volume else "block"


def regime_gate(
    *,
    structural_posture_chip: str | None,
    block_chips: Sequence[str] = ("SUSPENDED", "DEGRADED"),
) -> GateStatus:
    """Hard. Block when GOLD COMPASS structural posture is in block_chips.

    Fail-OPEN on missing posture — the scanner must not freeze just
    because GOLD hasn't run yet today. (Spec §4 fail-open rule.)
    """
    if structural_posture_chip is None:
        return "pass"
    return "block" if structural_posture_chip in block_chips else "pass"
```

- [ ] **2.7 Implement `scanner/ranking.py`.**

```python
"""Ranking — build_candidate, rank_candidates.

Port of xenon/scanners/uw/ranking.py + confluence.py, with Decimal
arithmetic and a candidate-suppression invariant when a ticker has
ONLY a dark_pool_accumulation hit (spec §5; xenon's `build_candidate`
returns None when non_dp_hits is empty).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal

from uw_scan.scanner.models import ContextFlag, ScanCandidate, SignalHit

# Tier weights — lower tier number = higher weight (xenon convention).
RANKING_TIER_WEIGHTS: dict[int, Decimal] = {1: Decimal("3.0"), 2: Decimal("1.5")}

# Signals that contribute to confluence but NOT to raw_score. Keeps a
# DP-only ticker from emitting a candidate at all (handled below).
RAW_RANKING_EXCLUDE: frozenset[str] = frozenset({"dark_pool_accumulation"})


def _confluence(hits: Iterable[SignalHit]) -> Decimal:
    return sum(
        (RANKING_TIER_WEIGHTS.get(h.tier, Decimal("0")) for h in hits),
        Decimal("0"),
    )


def _is_type_f(hits: Iterable[SignalHit]) -> bool:
    non_dp_types = {
        h.signal_type for h in hits if h.signal_type not in RAW_RANKING_EXCLUDE
    }
    return len(non_dp_types) >= 2


def build_candidate(
    *,
    ticker: str,
    hits: list[SignalHit],
    context_flags: list[ContextFlag],
    gates: dict[str, str],
) -> ScanCandidate | None:
    """Build a candidate or return None if no non-DP hits.

    The None-return guarantees a ticker whose ONLY hit is
    dark_pool_accumulation never appears as a candidate
    (matches xenon ranking.py:18-19).
    """
    non_dp_hits = [h for h in hits if h.signal_type not in RAW_RANKING_EXCLUDE]
    if not non_dp_hits:
        return None

    raw_score = sum(
        (h.score * RANKING_TIER_WEIGHTS.get(h.tier, Decimal("0"))
         for h in non_dp_hits),
        Decimal("0"),
    )
    confluence = _confluence(hits)
    final_score = raw_score + confluence
    return ScanCandidate(
        ticker=ticker.upper(),
        hits=list(hits),
        context_flags=list(context_flags),
        raw_score=raw_score,
        confluence_score=confluence,
        final_score=final_score,
        is_type_f=_is_type_f(hits),
        gates=dict(gates),
    )


def rank_candidates(candidates: Iterable[ScanCandidate]) -> list[ScanCandidate]:
    """Sort: is_type_f desc, final_score desc, ticker asc (deterministic)."""
    return sorted(
        candidates,
        key=lambda c: (not c.is_type_f, -c.final_score, c.ticker),
    )
```

- [ ] **2.8 Run all milestone tests, confirm green.**

Run: `uv run pytest tests/unit/scanner -v`
Expected: `test_calendars`, `test_gates`, `test_ranking` all pass.

Run: `uv run pytest -x -q`
Expected: full suite green.

- [ ] **2.9 Commit milestone.**

```bash
git add src/uw_scan/scanner/__init__.py \
        src/uw_scan/scanner/models.py \
        src/uw_scan/scanner/calendars.py \
        src/uw_scan/scanner/gates.py \
        src/uw_scan/scanner/ranking.py \
        src/uw_scan/config.py \
        tests/unit/scanner/__init__.py \
        tests/unit/scanner/test_calendars.py \
        tests/unit/scanner/test_gates.py \
        tests/unit/scanner/test_ranking.py
git commit -m "feat(scanner): models, calendars, gates, ranking + Settings env knobs

Pure-Python framework substrate. Models use Decimal throughout.
Gates: earnings/liquidity advisory; regime hard with fail-open on
missing GOLD posture. Ranking suppresses DP-only candidates per
xenon ranking.py invariant. 13 SCANNER_* env vars added to Settings
with sane defaults — operator can retune without code changes
during initial production tuning.

Spec §3-5, §10."
```

---

## Milestone 3 — Detectors: deep_conviction_flow + dark_pool_accumulation + pcr_sentiment

**Files:**
- Create: `src/uw_scan/scanner/signals/__init__.py`
- Create: `src/uw_scan/scanner/signals/deep_conviction_flow.py`
- Create: `src/uw_scan/scanner/signals/dark_pool_accumulation.py`
- Create: `src/uw_scan/scanner/context/__init__.py`
- Create: `src/uw_scan/scanner/context/pcr_sentiment.py`
- Create: `tests/unit/scanner/test_deep_conviction_flow.py`
- Create: `tests/unit/scanner/test_dark_pool_accumulation.py`
- Create: `tests/unit/scanner/test_pcr_sentiment.py`

**Why grouped:** these three all consume the same `flow_events` rows for this run (DCF and PCR) or the SignalsRepository's `fetch_dark_pool_window` (DP). Landing them together gives us the walking-skeleton signal coverage.

- [ ] **3.1 Write failing tests.**

`tests/unit/scanner/test_deep_conviction_flow.py`:

```python
"""DCF detector — derived ask_side_ratio, moneyness, dte from FlowAlert."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.signals.deep_conviction_flow import detect


TODAY = date(2026, 5, 17)


def _alert(
    *,
    volume=2000,
    open_interest=1000,
    total_premium="800000",
    total_ask_side_prem="700000",
    total_bid_side_prem="100000",
    has_multileg=False,
    strike="100",
    underlying_price="100",
    expiry_days=30,
    next_earnings_days: int | None = 60,
) -> FlowAlert:
    return FlowAlert(
        id="x",
        ticker="AAPL",
        type="call",
        strike=Decimal(strike),
        underlying_price=Decimal(underlying_price),
        total_premium=Decimal(total_premium),
        total_ask_side_prem=Decimal(total_ask_side_prem),
        total_bid_side_prem=Decimal(total_bid_side_prem),
        volume=volume,
        open_interest=open_interest,
        has_multileg=has_multileg,
        expiry=TODAY + timedelta(days=expiry_days),
        next_earnings_date=(
            TODAY + timedelta(days=next_earnings_days)
            if next_earnings_days is not None
            else None
        ),
    )


def test_qualifying_single_alert_emits_hit():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert()],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.signal_type == "deep_conviction_flow"
    assert hit.tier == 1
    assert hit.freshness == "live"
    # 0.5 + 0.5 * min(800000 / 2000000, 1.0) = 0.5 + 0.2 = 0.7
    assert hit.score == Decimal("0.7")
    assert hit.evidence["qualifying_alerts"] == 1


def test_blocks_when_earnings_within_window():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(next_earnings_days=10)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_blocks_when_earnings_unknown():
    # Conservative-block — matches xenon _parse_next_earnings(None) → True.
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(next_earnings_days=None)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_when_volume_not_greater_than_oi():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(volume=1000, open_interest=1000)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_on_multileg():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(has_multileg=True)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_when_ask_side_ratio_below_threshold():
    # ask 400k / (ask 400k + bid 600k) = 0.4 — below 0.80
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(total_ask_side_prem="400000",
                       total_bid_side_prem="600000",
                       total_premium="1000000")],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_on_excessive_moneyness():
    # strike 130 vs spot 100 → |moneyness| = 0.30 > 0.12
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(strike="130")],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_when_dte_below_floor():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(expiry_days=3)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_score_caps_at_one_with_huge_premium():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(total_premium="5000000",
                       total_ask_side_prem="4500000",
                       total_bid_side_prem="500000")],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.score == Decimal("1.0")
```

`tests/unit/scanner/test_dark_pool_accumulation.py`:

```python
"""DP cluster detector — anchor-price clustering with USD thresholds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.scanner.signals.dark_pool_accumulation import detect


NOW = datetime(2026, 5, 17, 16, 0, tzinfo=timezone.utc)


def _print(price, premium, hours_ago=1):
    return {
        "tracking_id": int(price * 1000),
        "executed_at": NOW - timedelta(hours=hours_ago),
        "price": Decimal(str(price)),
        "size": 1000,
        "premium": Decimal(str(premium)),
    }


def test_three_prints_in_band_above_threshold_fires():
    prints = [
        _print(185.00, 1_200_000),
        _print(185.50, 1_300_000),  # within 0.5% band
        _print(184.80, 1_500_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is not None
    assert hit.tier == 2
    assert hit.freshness == "stale"
    assert hit.evidence["cluster_size"] >= 3
    assert hit.evidence["direction_neutral"] is True


def test_returns_none_when_no_print_above_threshold():
    prints = [
        _print(185.00, 500_000),
        _print(185.10, 700_000),
        _print(185.20, 800_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is None


def test_returns_none_when_prints_too_spread():
    prints = [
        _print(180.00, 1_100_000),
        _print(190.00, 1_100_000),  # ~5.5% away — outside 0.5% band
        _print(200.00, 1_100_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is None


def test_score_grows_with_total_premium_capped_at_one():
    prints = [_print(100 + i * 0.1, 5_000_000, hours_ago=i)
              for i in range(3)]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is not None
    assert hit.score == Decimal("1.0")
```

`tests/unit/scanner/test_pcr_sentiment.py`:

```python
"""PCR context flag — count-based from this run's FlowAlerts."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.context.pcr_sentiment import flag


TODAY = date(2026, 5, 17)


def _alert(call_or_put: str, next_earnings_days: int | None = 60) -> FlowAlert:
    return FlowAlert(
        id="x", ticker="AAPL", type=call_or_put,
        next_earnings_date=(
            TODAY + timedelta(days=next_earnings_days)
            if next_earnings_days is not None else None
        ),
    )


def test_extreme_fear_when_pcr_above_1_5():
    # 6 puts / 3 calls = 2.0 > 1.5
    alerts = [_alert("put")] * 6 + [_alert("call")] * 3
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Extreme Fear"
    assert fl.value == Decimal("2.0")


def test_elevated_fear_when_pcr_between_1_2_and_1_5():
    # 7 puts / 5 calls = 1.4
    alerts = [_alert("put")] * 7 + [_alert("call")] * 5
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Elevated Fear"


def test_complacent_when_pcr_below_0_5():
    # 2 puts / 10 calls = 0.2
    alerts = [_alert("put")] * 2 + [_alert("call")] * 10
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Complacent"


def test_no_flag_when_pcr_in_neutral_band():
    # 5 puts / 5 calls = 1.0
    alerts = [_alert("put")] * 5 + [_alert("call")] * 5
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is None


def test_suppressed_when_earnings_within_window():
    alerts = [_alert("put", next_earnings_days=10)] * 6 + \
             [_alert("call", next_earnings_days=10)] * 3
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is None


def test_emits_when_earnings_unknown_per_spec():
    # Spec §3.5: PCR is informational, so unknown earnings does NOT suppress.
    alerts = [_alert("put", next_earnings_days=None)] * 6 + \
             [_alert("call", next_earnings_days=None)] * 3
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Extreme Fear"


def test_no_calls_returns_none():
    alerts = [_alert("put")] * 5
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY,
              earnings_window_days=14)
    assert fl is None
```

- [ ] **3.2 Run, confirm failures.**

Run: `uv run pytest tests/unit/scanner/test_deep_conviction_flow.py tests/unit/scanner/test_dark_pool_accumulation.py tests/unit/scanner/test_pcr_sentiment.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **3.3 Implement `scanner/signals/__init__.py` and `scanner/context/__init__.py`** (both empty).

- [ ] **3.4 Implement `scanner/signals/deep_conviction_flow.py`.**

```python
"""Deep Conviction Flow detector (Tier 1).

Spec §3.1: derives ask_side_ratio / moneyness / dte from fields already
on FlowAlert rather than expanding the schema. Conservative-block on
unknown next_earnings_date — DCF must never emit during the earnings
window (this redundancy with the advisory earnings_gate is intentional).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable

from uw_scan.models import FlowAlert
from uw_scan.scanner.models import SignalHit


def _alert_qualifies(
    alert: FlowAlert,
    *,
    today: date,
    min_premium_usd: Decimal,
    min_ask_side: Decimal,
    max_moneyness: Decimal,
    min_dte: int,
    earnings_window_days: int,
) -> bool:
    # Earnings — conservative-block on unknown (xenon parity).
    if alert.next_earnings_date is None:
        return False
    if (alert.next_earnings_date - today).days <= earnings_window_days:
        return False

    if alert.volume is None or alert.open_interest is None:
        return False
    if alert.volume <= alert.open_interest:
        return False

    ask = alert.total_ask_side_prem
    bid = alert.total_bid_side_prem
    if ask is None or bid is None or (ask + bid) <= 0:
        return False
    ask_side_ratio = ask / (ask + bid)
    if ask_side_ratio < min_ask_side:
        return False

    if alert.total_premium is None or alert.total_premium < min_premium_usd:
        return False
    if alert.has_multileg is True:
        return False

    if alert.strike is None or alert.underlying_price is None \
            or alert.underlying_price <= 0:
        return False
    moneyness = (alert.strike - alert.underlying_price) / alert.underlying_price
    if abs(moneyness) > max_moneyness:
        return False

    if alert.expiry is None:
        return False
    dte = (alert.expiry - today).days
    if dte < min_dte:
        return False

    return True


def detect(
    *,
    ticker: str,
    alerts: Iterable[FlowAlert],
    today: date,
    min_premium_usd: Decimal,
    min_ask_side: Decimal,
    max_moneyness: Decimal,
    min_dte: int,
    earnings_window_days: int,
) -> SignalHit | None:
    qualifying = [
        a for a in alerts
        if _alert_qualifies(
            a,
            today=today,
            min_premium_usd=min_premium_usd,
            min_ask_side=min_ask_side,
            max_moneyness=max_moneyness,
            min_dte=min_dte,
            earnings_window_days=earnings_window_days,
        )
    ]
    if not qualifying:
        return None

    total_premium = sum(
        (a.total_premium or Decimal("0") for a in qualifying), Decimal("0")
    )
    top = max(qualifying, key=lambda a: a.total_premium or Decimal("0"))
    premium_scale = min(total_premium / Decimal("2000000"), Decimal("1.0"))
    score = Decimal("0.5") + Decimal("0.5") * premium_scale

    top_ask = top.total_ask_side_prem or Decimal("0")
    top_bid = top.total_bid_side_prem or Decimal("0")
    top_ratio = (top_ask / (top_ask + top_bid)) if (top_ask + top_bid) > 0 \
        else Decimal("0")
    top_dte = (top.expiry - today).days if top.expiry else None

    return SignalHit(
        ticker=ticker.upper(),
        signal_type="deep_conviction_flow",
        tier=1,
        score=score,
        evidence={
            "qualifying_alerts": len(qualifying),
            "total_premium": str(total_premium),
            "top_strike": str(top.strike) if top.strike else None,
            "top_expiry": top.expiry.isoformat() if top.expiry else None,
            "top_ask_side_ratio": str(top_ratio),
            "top_dte": top_dte,
        },
        freshness="live",
    )
```

- [ ] **3.5 Implement `scanner/signals/dark_pool_accumulation.py`.**

```python
"""Dark Pool Accumulation detector (Tier 2, confirmation-only).

Reads the 5-day rolling window from signals_repository.fetch_dark_pool_window
rather than refetching UW. Direction-neutral: signal asserts size moved at
this level, not who initiated. Excluded from raw_score via
RAW_RANKING_EXCLUDE in scanner/ranking.py.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from uw_scan.scanner.models import SignalHit


def detect(
    *,
    ticker: str,
    dark_pool_prints: Iterable[dict[str, Any]],
    min_print_premium: Decimal,
    min_cluster_size: int,
    price_spread_pct: Decimal,
) -> SignalHit | None:
    large = [
        p for p in dark_pool_prints
        if p.get("premium") is not None
        and Decimal(str(p["premium"])) >= min_print_premium
        and p.get("price") is not None
        and Decimal(str(p["price"])) > 0
    ]
    if len(large) < min_cluster_size:
        return None

    window_start = min((p["executed_at"] for p in large), default=None)
    window_end = max((p["executed_at"] for p in large), default=None)

    for anchor in large:
        anchor_price = Decimal(str(anchor["price"]))
        cluster = [
            p for p in large
            if abs(Decimal(str(p["price"])) - anchor_price)
                / anchor_price * Decimal("100") <= price_spread_pct
        ]
        if len(cluster) >= min_cluster_size:
            total_premium = sum(
                (Decimal(str(p["premium"])) for p in cluster), Decimal("0")
            )
            score = min(
                Decimal("1.0"), total_premium / Decimal("10000000")
            )
            return SignalHit(
                ticker=ticker.upper(),
                signal_type="dark_pool_accumulation",
                tier=2,
                score=score,
                evidence={
                    "cluster_size": len(cluster),
                    "anchor_price": str(anchor_price),
                    "total_premium": str(total_premium),
                    "window_start": (
                        window_start.isoformat() if window_start else None
                    ),
                    "window_end": (
                        window_end.isoformat() if window_end else None
                    ),
                    "direction_neutral": True,
                },
                freshness="stale",
            )
    return None
```

- [ ] **3.6 Implement `scanner/context/pcr_sentiment.py`.**

```python
"""PCR Sentiment context flag — count-based PCR from this run's FlowAlerts.

NOTE: Does NOT use cards/pcr.py — that file computes 30-day deltas on
OI/volume PCR history, a different metric. Per xenon parity (analysis/
ticker_data.py:424-432), this counts call vs put alerts in the current
flow snapshot. Suppressed when ANY alert reports earnings within the
window (PCR is noisy around earnings); unknown earnings does NOT
suppress (flag is informational per spec §3.5).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.models import ContextFlag


def flag(
    *,
    ticker: str,
    alerts: Iterable[FlowAlert],
    today: date,
    earnings_window_days: int,
) -> ContextFlag | None:
    alerts_list = list(alerts)

    # Suppress when any alert has earnings within the window. Unknown
    # earnings does NOT suppress — spec §3.5.
    for a in alerts_list:
        if a.next_earnings_date is not None and (
            a.next_earnings_date - today
        ).days <= earnings_window_days:
            return None

    calls = sum(1 for a in alerts_list if (a.type or "").lower() == "call")
    puts = sum(1 for a in alerts_list if (a.type or "").lower() == "put")
    if calls == 0:
        return None

    pcr = Decimal(puts) / Decimal(calls)
    if pcr > Decimal("1.5"):
        label = "Extreme Fear"
    elif pcr > Decimal("1.2"):
        label = "Elevated Fear"
    elif pcr < Decimal("0.5"):
        label = "Complacent"
    else:
        return None

    return ContextFlag(
        ticker=ticker.upper(),
        layer="pcr_sentiment",
        label=label,
        value=pcr,
    )
```

- [ ] **3.7 Run milestone tests, confirm green.**

Run: `uv run pytest tests/unit/scanner -v`
Expected: all unit tests for scanner pass.

Run: `uv run pytest -x -q`
Expected: full suite green.

- [ ] **3.8 Commit milestone.**

```bash
git add src/uw_scan/scanner/signals/__init__.py \
        src/uw_scan/scanner/signals/deep_conviction_flow.py \
        src/uw_scan/scanner/signals/dark_pool_accumulation.py \
        src/uw_scan/scanner/context/__init__.py \
        src/uw_scan/scanner/context/pcr_sentiment.py \
        tests/unit/scanner/test_deep_conviction_flow.py \
        tests/unit/scanner/test_dark_pool_accumulation.py \
        tests/unit/scanner/test_pcr_sentiment.py
git commit -m "feat(scanner): DCF + DP + PCR detectors (walking-skeleton signal set)

DCF derives ask_side_ratio / moneyness / dte from persisted FlowAlert
fields (no schema expansion) and conservative-blocks on unknown
next_earnings_date.

DP reads a 5-day rolling window from SignalsRepository instead of
refetching UW, and is direction-neutral (xenon parity).

PCR is count-based from current-run alerts (not from cards/pcr.py
which is a different OI-delta metric).

Spec §3.1, §3.2, §3.5."
```

---

## Milestone 4 — Detectors: earnings_iv_crush + gex_pinning

**Files:**
- Create: `src/uw_scan/scanner/signals/earnings_iv_crush.py`
- Create: `src/uw_scan/scanner/signals/gex_pinning.py`
- Create: `tests/unit/scanner/test_earnings_iv_crush.py`
- Create: `tests/unit/scanner/test_gex_pinning.py`

- [ ] **4.1 Write failing tests.**

`tests/unit/scanner/test_earnings_iv_crush.py`:

```python
"""EIC detector — needs iv_rank ≥ 75 AND earnings within window."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.scanner.signals.earnings_iv_crush import detect


TODAY = date(2026, 5, 17)


def test_fires_when_iv_rank_high_and_earnings_imminent():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("85"),
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.tier == 1
    assert hit.freshness == "live"
    # (85-75)/25 + 0.5 = 0.4 + 0.5 = 0.9
    assert hit.score == Decimal("0.9")


def test_no_fire_when_iv_rank_below_threshold():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("70"),
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_no_fire_when_no_earnings_in_window():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("90"),
        next_earnings_date=TODAY + timedelta(days=30),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_no_fire_when_earnings_unknown():
    # Per spec §3.3: unknown → no fire (conservative, matches DCF stance).
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("90"),
        next_earnings_date=None,
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_no_fire_when_iv_rank_missing():
    hit = detect(
        ticker="AAPL",
        iv_rank=None,
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_score_caps_at_one():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("100"),
        next_earnings_date=TODAY + timedelta(days=5),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.score == Decimal("1.0")
```

`tests/unit/scanner/test_gex_pinning.py`:

```python
"""GEX pinning — mega-caps + opex week + distance/gamma scoring."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.scanner.signals.gex_pinning import MEGA_CAPS, detect


# 3rd Friday of December 2025
OPEX_DAY = date(2025, 12, 19)
NON_OPEX_DAY = date(2025, 12, 1)


def _curve(strikes: list[tuple[float, float]]) -> list[dict]:
    """Build a strike_gex_curve payload — list of {strike, net_gex} dicts."""
    return [
        {"strike": str(strike), "net_gex": str(gamma), "expiry": "2025-12-19"}
        for strike, gamma in strikes
    ]


def test_no_fire_for_non_mega_cap():
    hit = detect(
        ticker="AMD",
        strike_gex_curve=_curve([(150.0, 5.0)]),
        spot=Decimal("150"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_no_fire_outside_opex_week():
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(500.0, 5.0)]),
        spot=Decimal("500"),
        today=NON_OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_fires_when_mega_cap_opex_and_pinning_strike_nearby():
    # SPY at $500.40, pin strike $500.00 (distance 0.08%), gamma 5.0
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(500.0, 5.0)]),
        spot=Decimal("500.40"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is not None
    assert hit.tier == 1
    # distance_pct = |500 - 500.40| / 500 * 100 = 0.08
    # distance_score = max(0, 1 - 0.08) = 0.92
    # gamma_score = min(5/10, 1.0) = 0.5
    # score = 0.5 * 0.92 + 0.5 * 0.5 = 0.71
    assert hit.score == Decimal("0.71")


def test_clamps_distance_score_at_zero_when_pin_far():
    # Distance 1.5% — distance_score would be -0.5 without the clamp.
    # detect_pinning's max_distance_pct=1.0 means the pin wouldn't be
    # returned in the first place, so the test asserts None here.
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(508.0, 5.0)]),
        spot=Decimal("500"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_no_fire_when_gamma_below_threshold():
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(500.0, 0.5)]),
        spot=Decimal("500"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_mega_caps_set_contains_required_tickers():
    for t in ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA"):
        assert t in MEGA_CAPS
```

- [ ] **4.2 Run, confirm failures.**

Run: `uv run pytest tests/unit/scanner/test_earnings_iv_crush.py tests/unit/scanner/test_gex_pinning.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **4.3 Implement `scanner/signals/earnings_iv_crush.py`.**

```python
"""Earnings IV Crush detector (Tier 1).

Reads iv_rank directly (0-100 scale) — NOT iv_percentile_30d from
interpolated_iv_snapshots, which is a different metric. (Spec §3.3.)
Earnings unknown → no fire (matches DCF conservative-block).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.scanner.models import SignalHit


def detect(
    *,
    ticker: str,
    iv_rank: Decimal | None,
    next_earnings_date: date | None,
    today: date,
    min_iv_rank: Decimal,
    earnings_window_days: int,
) -> SignalHit | None:
    if iv_rank is None or iv_rank < min_iv_rank:
        return None
    if next_earnings_date is None:
        return None
    days = (next_earnings_date - today).days
    if days <= 0 or days > earnings_window_days:
        return None

    delta = (iv_rank - min_iv_rank) / Decimal("25") + Decimal("0.5")
    score = min(Decimal("1.0"), delta)

    return SignalHit(
        ticker=ticker.upper(),
        signal_type="earnings_iv_crush",
        tier=1,
        score=score,
        evidence={
            "iv_rank": str(iv_rank),
            "earnings_date": next_earnings_date.isoformat(),
            "earnings_within_days": days,
        },
        freshness="live",
    )
```

- [ ] **4.4 Implement `scanner/signals/gex_pinning.py`.**

```python
"""GEX Pinning detector (Tier 1, mega-caps during opex week only).

Port of xenon/scanners/uw/signals/gex_pinning.py + the detect_pinning
helper from xenon/analysis/gex.py:50. Reads this run's strike_gex_curve
(per-strike for the nearest expiry — during opex week the nearest IS
the opex expiry, so this is functionally equivalent to xenon's
greek_exposure_by_strike for this detector). Spec §3.4.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.scanner.calendars import is_opex_week
from uw_scan.scanner.models import SignalHit

MEGA_CAPS: frozenset[str] = frozenset({
    "SPY", "QQQ", "IWM", "DIA",
    "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "AMZN", "META", "TSLA",
})

MAX_DISTANCE_PCT = Decimal("1.0")  # xenon detect_pinning default


def _gamma(wall: dict[str, Any]) -> Decimal | None:
    raw = wall.get("net_gex") if "net_gex" in wall else wall.get("gamma")
    if raw is None:
        return None
    try:
        return Decimal(str(raw))
    except (ArithmeticError, ValueError):
        return None


def _rank_walls(strikes: list[dict[str, Any]], top_n: int = 5) -> list[dict]:
    scored: list[tuple[Decimal, dict[str, Any]]] = []
    for s in strikes:
        g = _gamma(s)
        if g is None or s.get("strike") is None:
            continue
        scored.append((abs(g), s))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [s for _, s in scored[:top_n]]


def _detect_pinning(
    strikes: list[dict[str, Any]],
    *,
    price: Decimal,
    min_gamma: Decimal,
    max_distance_pct: Decimal = MAX_DISTANCE_PCT,
) -> dict[str, Any] | None:
    if price <= 0:
        return None
    for wall in _rank_walls(strikes, top_n=5):
        strike = Decimal(str(wall["strike"]))
        gamma = _gamma(wall) or Decimal("0")
        if abs(gamma) < min_gamma:
            continue
        distance_pct = abs(strike - price) / price * Decimal("100")
        if distance_pct <= max_distance_pct:
            return {
                "strike": str(strike),
                "gamma": str(gamma),
                "distance_pct": str(distance_pct),
            }
    return None


def detect(
    *,
    ticker: str,
    strike_gex_curve: list[dict[str, Any]] | None,
    spot: Decimal | None,
    today: date,
    min_gamma: Decimal,
) -> SignalHit | None:
    if ticker.upper() not in MEGA_CAPS:
        return None
    if not is_opex_week(today):
        return None
    if not strike_gex_curve or spot is None:
        return None

    pin = _detect_pinning(strike_gex_curve, price=spot, min_gamma=min_gamma)
    if pin is None:
        return None

    distance_pct = Decimal(pin["distance_pct"])
    gamma = Decimal(pin["gamma"])
    distance_score = max(Decimal("0"), Decimal("1") - distance_pct)
    gamma_score = min(Decimal("1.0"), abs(gamma) / Decimal("10"))
    score = Decimal("0.5") * distance_score + Decimal("0.5") * gamma_score

    return SignalHit(
        ticker=ticker.upper(),
        signal_type="gex_pinning",
        tier=1,
        score=score,
        evidence={
            "strike": pin["strike"],
            "distance_pct": pin["distance_pct"],
            "gamma": pin["gamma"],
        },
        freshness="live",
    )
```

- [ ] **4.5 Run tests, confirm green.**

Run: `uv run pytest tests/unit/scanner -v`
Expected: all 8 scanner unit test files pass.

Run: `uv run pytest -x -q`
Expected: full suite green.

- [ ] **4.6 Commit milestone.**

```bash
git add src/uw_scan/scanner/signals/earnings_iv_crush.py \
        src/uw_scan/scanner/signals/gex_pinning.py \
        tests/unit/scanner/test_earnings_iv_crush.py \
        tests/unit/scanner/test_gex_pinning.py
git commit -m "feat(scanner): EIC + GEX pinning detectors (xenon parity)

EIC reads iv_rank (0-100) directly, NOT iv_percentile_30d.
Conservative-block on unknown earnings (xenon parity with DCF).

GEX pinning is mega-caps + opex week only. Ported detect_pinning
from xenon/analysis/gex.py:50 with Decimal arithmetic and the
max(0, ...) clamp on distance_score per spec §3.4.

Spec §3.3, §3.4."
```

---

## Milestone 5 — Orchestrator: scanner.pipeline.run_detectors

**Files:**
- Create: `src/uw_scan/scanner/pipeline.py`
- Create: `tests/unit/scanner/test_pipeline.py`

The orchestrator is the single entry point pipeline.py:343 will call. It owns: building the gate inputs from `repo` reads, running each detector, persisting via `signals_repo`, and returning the (optional) `ScanCandidate` so the caller can log it.

- [ ] **5.1 Write the failing test.**

`tests/unit/scanner/test_pipeline.py`:

```python
"""Orchestrator unit test — uses an in-memory fake SignalsRepository
and a small stub Repository to verify the detector wiring without
hitting Postgres. Integration coverage of the wiring happens in
Milestone 6."""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner.pipeline import run_detectors


TODAY = date(2026, 5, 17)


# Match the project's integration-conftest pattern: Settings.from_env
# raises if UW_SCAN_API_KEY is missing, so seed a dummy value before
# constructing. The dummy is never used because the orchestrator
# never makes outbound HTTP calls.
os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-unused")


class FakeRepo:
    def __init__(self, **kwargs):
        self._flow_alerts = kwargs.get("flow_alerts", [])
        self._iv_rank = kwargs.get("iv_rank")
        self._strike_gex_curve = kwargs.get("strike_gex_curve", [])
        self._spot = kwargs.get("spot")
        self._posture = kwargs.get("posture")
        self._total_volume = kwargs.get("total_volume", 5000)

    def fetch_flow_events_for_run(self, run_id, ticker):
        return list(self._flow_alerts)

    def fetch_latest_iv_rank(self, ticker):
        return self._iv_rank

    def fetch_strike_gex_curve(self, run_id):
        return list(self._strike_gex_curve)

    def fetch_spot_for_ticker(self, ticker):
        return self._spot

    def fetch_gold_posture_latest(self):
        return self._posture

    def fetch_total_option_volume_for_run(self, run_id, ticker):
        return self._total_volume


class FakeSignalsRepo:
    def __init__(self):
        self.hits, self.flags, self.gates = [], [], []
        self.dp_window = []

    def upsert_signal_hit(self, **kw):
        self.hits.append(kw)

    def upsert_context_flag(self, **kw):
        self.flags.append(kw)

    def upsert_gate(self, **kw):
        self.gates.append(kw)

    def fetch_dark_pool_window(self, ticker, *, lookback_days):
        return list(self.dp_window)


def _settings() -> Settings:
    return Settings.from_env()


def _qualifying_dcf_alert() -> FlowAlert:
    return FlowAlert(
        id="x", ticker="AAPL", type="call",
        strike=Decimal("100"), underlying_price=Decimal("100"),
        total_premium=Decimal("800000"),
        total_ask_side_prem=Decimal("700000"),
        total_bid_side_prem=Decimal("100000"),
        volume=2000, open_interest=1000,
        has_multileg=False,
        expiry=TODAY + timedelta(days=30),
        next_earnings_date=TODAY + timedelta(days=60),
    )


def test_regime_block_writes_gate_and_returns_none():
    repo = FakeRepo(
        posture={"structural_posture_chip": "SUSPENDED"},
        flow_alerts=[_qualifying_dcf_alert()],
    )
    sigs = FakeSignalsRepo()
    out = run_detectors(
        repo=repo, signals_repo=sigs, settings=_settings(),
        run_id=1, ticker="AAPL", today=TODAY,
    )
    assert out is None
    assert len(sigs.gates) == 1
    assert sigs.gates[0]["regime"] == "block"
    # No hits emitted when regime blocks.
    assert sigs.hits == []
    assert sigs.flags == []


def test_dcf_only_run_emits_hit_and_gate():
    repo = FakeRepo(
        posture={"structural_posture_chip": "NEUTRAL"},
        flow_alerts=[_qualifying_dcf_alert()],
        iv_rank=Decimal("40"),
        spot=Decimal("100"),
    )
    sigs = FakeSignalsRepo()
    out = run_detectors(
        repo=repo, signals_repo=sigs, settings=_settings(),
        run_id=1, ticker="AAPL", today=TODAY,
    )
    assert out is not None
    assert out.ticker == "AAPL"
    assert out.is_type_f is False
    assert any(h["signal_type"] == "deep_conviction_flow" for h in sigs.hits)
    assert len(sigs.gates) == 1
    assert sigs.gates[0]["regime"] == "pass"


def test_dp_only_run_emits_no_candidate_but_writes_hit_and_gate():
    # DP fires but DCF does not → no candidate returned, but the DP hit
    # is still persisted (the read query is responsible for filtering).
    repo = FakeRepo(
        posture={"structural_posture_chip": "NEUTRAL"},
        flow_alerts=[],
    )
    sigs = FakeSignalsRepo()
    sigs.dp_window = [
        {"executed_at": datetime(2026, 5, 16, 14, 0, tzinfo=timezone.utc),
         "tracking_id": i, "price": Decimal("100.0"),
         "premium": Decimal("1500000")}
        for i in range(3)
    ]
    out = run_detectors(
        repo=repo, signals_repo=sigs, settings=_settings(),
        run_id=1, ticker="AAPL", today=TODAY,
    )
    assert out is None
    assert any(h["signal_type"] == "dark_pool_accumulation" for h in sigs.hits)
    assert len(sigs.gates) == 1


def test_failing_gold_posture_fetch_does_not_crash_orchestrator(monkeypatch):
    class BrokenRepo(FakeRepo):
        def fetch_gold_posture_latest(self):
            raise RuntimeError("DB hiccup")

    repo = BrokenRepo(flow_alerts=[_qualifying_dcf_alert()], spot=Decimal("100"))
    sigs = FakeSignalsRepo()
    # Fail-open: orchestrator must catch and treat as NEUTRAL.
    out = run_detectors(
        repo=repo, signals_repo=sigs, settings=_settings(),
        run_id=1, ticker="AAPL", today=TODAY,
    )
    assert out is not None
    assert sigs.gates[0]["regime"] == "pass"
```

- [ ] **5.2 Run, confirm failure.**

Run: `uv run pytest tests/unit/scanner/test_pipeline.py -v`
Expected: `ModuleNotFoundError: No module named 'uw_scan.scanner.pipeline'`.

- [ ] **5.3 Implement `scanner/pipeline.py`.**

The orchestrator depends on a handful of read methods that may not yet exist on `Repository`. Where a Repository method is missing, the orchestrator calls a helper local to `scanner/pipeline.py` that runs the SQL inline (so we don't grow `repository.py`). Concretely, this milestone needs:

- `repo.fetch_gold_posture_latest()` — already exists (`repository.py:4792`)
- Per-ticker latest `iv_rank` — query `volatility_stats_history` directly inline
- Per-run `strike_gex_curve` — query `scan_runs` directly inline
- Per-ticker spot — read from `watchlist_card` directly inline
- Per-run flow events — query `flow_events` directly inline
- Per-run total option volume — sum from same query

All inline SQL stays in `scanner/pipeline.py` (not appended to `repository.py`).

Implementation:

```python
"""Scanner orchestrator — runs detectors against a freshly-completed
per-ticker scan, persists hits/flags/gate, and returns the optional
ScanCandidate. Called from pipeline.run_single_stock as the final
stage before finish_scan_run.

Per the standing rule (MEMORY.md feedback_repository_split_threshold),
inline reads stay here rather than being appended to repository.py.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner.context import pcr_sentiment
from uw_scan.scanner.gates import earnings_gate, liquidity_gate, regime_gate
from uw_scan.scanner.models import ContextFlag, ScanCandidate, SignalHit
from uw_scan.scanner.ranking import build_candidate
from uw_scan.scanner.signals import (
    dark_pool_accumulation,
    deep_conviction_flow,
    earnings_iv_crush,
    gex_pinning,
)
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

logger = logging.getLogger(__name__)


def _fetch_structural_posture(repo: Repository | Any) -> str | None:
    """Fail-open helper — returns None on any error so regime_gate
    treats the situation as NEUTRAL/pass."""
    try:
        row = repo.fetch_gold_posture_latest()
    except Exception as exc:  # noqa: BLE001
        logger.warning("scanner: gold posture fetch failed (%s); regime fails open",
                       repr(exc))
        return None
    if row is None:
        return None
    return row.get("structural_posture_chip")


def _fetch_flow_alerts_for_run(
    repo: Repository | Any, run_id: int, ticker: str
) -> list[FlowAlert]:
    """Read this run's persisted FlowAlerts back out for detector input.

    On the real Repository, this opens a cursor. On the test FakeRepo,
    a fetch_flow_events_for_run method is provided directly.
    """
    if hasattr(repo, "fetch_flow_events_for_run"):
        return list(repo.fetch_flow_events_for_run(run_id, ticker))
    # Real Repository path — inline SQL.
    # Columns aliased to match FlowAlert field names. FlowAlert's
    # _UwBase.model_config = ConfigDict(extra="ignore"), so we can
    # ignore unrelated columns. See 001_s1_core_tables.sql:59.
    sql = """
        SELECT alert_id AS id, ticker, option_chain, expiry, strike,
               option_type AS type, price, underlying_price,
               total_size, total_premium,
               total_ask_side_prem, total_bid_side_prem,
               volume, open_interest, volume_oi_ratio,
               has_sweep, has_floor, has_multileg, all_opening_trades,
               iv_start, iv_end, alert_rule, rule_id, sector, issue_type,
               next_earnings_date, created_at
        FROM uw_scan.flow_events
        WHERE run_id = %s AND ticker = %s
    """
    with repo.conn.cursor() as cur:
        cur.execute(sql, (run_id, ticker.upper()))
        rows = cur.fetchall()
        cols = [c.name for c in cur.description]
    return [
        FlowAlert.model_validate(dict(zip(cols, r, strict=True)))
        for r in rows
    ]


def _fetch_latest_iv_rank(repo: Repository | Any, ticker: str) -> Decimal | None:
    # Table is `volatility_stats_history` (verified
    # 001_s1_core_tables.sql:119). repo.upsert_volatility_stats_rows
    # writes into it from sources/uw.fetch_volatility_stats earlier
    # in the same run.
    if hasattr(repo, "fetch_latest_iv_rank"):
        return repo.fetch_latest_iv_rank(ticker)
    with repo.conn.cursor() as cur:
        cur.execute(
            """SELECT iv_rank FROM uw_scan.volatility_stats_history
               WHERE ticker = %s AND iv_rank IS NOT NULL
               ORDER BY date DESC LIMIT 1""",
            (ticker.upper(),),
        )
        row = cur.fetchone()
        return Decimal(str(row[0])) if row and row[0] is not None else None


def _fetch_strike_gex_curve(repo: Repository | Any, run_id: int) -> list[dict]:
    if hasattr(repo, "fetch_strike_gex_curve"):
        return list(repo.fetch_strike_gex_curve(run_id))
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT strike_gex_curve FROM uw_scan.scan_runs WHERE run_id = %s",
            (run_id,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            return []
        return list(row[0])


def _fetch_spot_for_ticker(repo: Repository | Any, ticker: str) -> Decimal | None:
    if hasattr(repo, "fetch_spot_for_ticker"):
        return repo.fetch_spot_for_ticker(ticker)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT spot FROM uw_scan.watchlist_card WHERE ticker = %s",
            (ticker.upper(),),
        )
        row = cur.fetchone()
        return Decimal(str(row[0])) if row and row[0] is not None else None


def _next_earnings_for_run(alerts: list[FlowAlert]) -> "date | None":
    """Take the soonest known next_earnings_date from this run's alerts."""
    dates = [a.next_earnings_date for a in alerts if a.next_earnings_date]
    return min(dates) if dates else None


def run_detectors(
    *,
    repo: Repository | Any,
    signals_repo: SignalsRepository | Any,
    settings: Settings,
    run_id: int,
    ticker: str,
    today: date,
) -> ScanCandidate | None:
    """Run all detectors for one ticker, persist results, return candidate.

    Returns None when regime blocks OR when no non-DP hit was produced.
    A signal_gates row is ALWAYS written so the read-side EXISTS()
    filter can identify this as a scanner-producing run (spec §8).
    """
    ticker = ticker.upper()

    # --- Gate inputs --------------------------------------------------
    structural = _fetch_structural_posture(repo)
    regime = regime_gate(
        structural_posture_chip=structural,
        block_chips=tuple(settings.scanner_regime_block_chips),
    )

    alerts = _fetch_flow_alerts_for_run(repo, run_id, ticker)
    next_earn = _next_earnings_for_run(alerts)
    earnings = earnings_gate(
        next_earnings_date=next_earn,
        today=today,
        window_days=settings.scanner_earnings_window_days,
    )

    total_volume = sum((a.volume or 0) for a in alerts)
    liquidity = liquidity_gate(
        option_volume=total_volume,
        min_volume=settings.scanner_liquidity_min_option_volume,
    )

    # ALWAYS persist the gate row first — the read-side EXISTS filter
    # depends on it to identify scanner-producing runs (spec §8).
    signals_repo.upsert_gate(
        run_id=run_id, ticker=ticker,
        earnings=earnings, liquidity=liquidity, regime=regime,
    )

    if regime == "block":
        return None

    # --- Detectors ---------------------------------------------------
    hits: list[SignalHit] = []

    dcf = deep_conviction_flow.detect(
        ticker=ticker,
        alerts=alerts,
        today=today,
        min_premium_usd=settings.scanner_dcf_min_premium_usd,
        min_ask_side=settings.scanner_dcf_min_ask_side,
        max_moneyness=settings.scanner_dcf_max_moneyness,
        min_dte=settings.scanner_dcf_min_dte,
        earnings_window_days=settings.scanner_earnings_window_days,
    )
    if dcf is not None:
        hits.append(dcf)

    dp_window = signals_repo.fetch_dark_pool_window(
        ticker, lookback_days=settings.scanner_dp_lookback_days
    )
    dp = dark_pool_accumulation.detect(
        ticker=ticker,
        dark_pool_prints=dp_window,
        min_print_premium=settings.scanner_dp_min_print_premium_usd,
        min_cluster_size=settings.scanner_dp_min_cluster_size,
        price_spread_pct=settings.scanner_dp_price_spread_pct,
    )
    if dp is not None:
        hits.append(dp)

    iv_rank = _fetch_latest_iv_rank(repo, ticker)
    eic = earnings_iv_crush.detect(
        ticker=ticker,
        iv_rank=iv_rank,
        next_earnings_date=next_earn,
        today=today,
        min_iv_rank=settings.scanner_eic_min_iv_rank,
        earnings_window_days=settings.scanner_earnings_window_days,
    )
    if eic is not None:
        hits.append(eic)

    spot = _fetch_spot_for_ticker(repo, ticker)
    curve = _fetch_strike_gex_curve(repo, run_id)
    gex = gex_pinning.detect(
        ticker=ticker,
        strike_gex_curve=curve,
        spot=spot,
        today=today,
        min_gamma=settings.scanner_gex_pin_min_gamma,
    )
    if gex is not None:
        hits.append(gex)

    # --- Context flag ------------------------------------------------
    pcr_flag = pcr_sentiment.flag(
        ticker=ticker,
        alerts=alerts,
        today=today,
        earnings_window_days=settings.scanner_earnings_window_days,
    )

    # --- Persist hits / flags ----------------------------------------
    for h in hits:
        signals_repo.upsert_signal_hit(
            run_id=run_id, ticker=ticker,
            signal_type=h.signal_type, tier=h.tier, score=h.score,
            evidence=h.evidence, freshness=h.freshness,
        )
    flags: list[ContextFlag] = []
    if pcr_flag is not None:
        flags.append(pcr_flag)
        signals_repo.upsert_context_flag(
            run_id=run_id, ticker=ticker,
            layer=pcr_flag.layer, label=pcr_flag.label, value=pcr_flag.value,
        )

    # --- Build candidate (None on DP-only) ---------------------------
    return build_candidate(
        ticker=ticker,
        hits=hits,
        context_flags=flags,
        gates={"earnings": earnings, "liquidity": liquidity, "regime": regime},
    )
```

- [ ] **5.4 Run tests, confirm green.**

Run: `uv run pytest tests/unit/scanner -v`
Expected: all unit tests pass including the four new orchestrator tests.

Run: `uv run pytest -x -q`
Expected: full suite green.

- [ ] **5.5 Commit milestone.**

```bash
git add src/uw_scan/scanner/pipeline.py tests/unit/scanner/test_pipeline.py
git commit -m "feat(scanner): orchestrator wires gates + detectors + persistence

run_detectors is the single entry point for scanner work inside the
per-ticker scan pipeline. Inline SQL reads stay here rather than
extending repository.py (5k-line rule). Regime fail-open is enforced
in the orchestrator, not deferred to callers. signal_gates is always
written so the read-side EXISTS() filter (spec §8) can identify
scanner-producing runs without notes-tagging.

Spec §2, §4."
```

---

## Milestone 6 — Wire orchestrator into run_single_stock + DB integration test

**Files:**
- Modify: `src/uw_scan/pipeline.py` (one line of imports + ~8 lines at L343)
- Create: `tests/integration/scanner/test_scanner_orchestrator_e2e.py` (basename intentionally NOT `test_pipeline_e2e.py` — that name already exists at `tests/integration/test_pipeline_e2e.py` and pytest can flake on duplicate basenames even in separate sub-packages)

- [ ] **6.1 Modify `pipeline.py`.**

Open `src/uw_scan/pipeline.py`. Add the new imports after the existing import block (around line 32, after `from .storage.repository import Repository`):

```python
from functools import lru_cache

from .scanner.pipeline import run_detectors as run_scanner_detectors
from .storage.signals_repository import SignalsRepository


@lru_cache(maxsize=1)
def _cached_scanner_settings() -> Settings:
    """Cache Settings for the worker process so the scanner stage
    pays Settings.from_env() exactly once. lru_cache doesn't cache
    exceptions, so a transient .env problem self-heals on retry."""
    return Settings.from_env()
```

Locate the block starting at line 334:

```python
        try:
            _persist_trade_insights_for_run(repo=repo, report=report)
        except Exception as exc:  # noqa: BLE001 — research-log only; never block a scan
            logger.warning(
                "trade_insights persistence failed for %s run_id=%s: %s",
                report.ticker,
                report.run_id,
                repr(exc),
            )

        repo.finish_scan_run(run_id, status="ok")
```

Insert the scanner stage between the trade_insights block and `repo.finish_scan_run`:

```python
        try:
            _persist_trade_insights_for_run(repo=repo, report=report)
        except Exception as exc:  # noqa: BLE001 — research-log only; never block a scan
            logger.warning(
                "trade_insights persistence failed for %s run_id=%s: %s",
                report.ticker,
                report.run_id,
                repr(exc),
            )

        # Scanner detectors — runs AFTER all UW data is persisted so it
        # reads from the warm store. The orchestrator catches its own
        # exceptions for non-critical detector failures; a hard crash
        # here would mean the scan can't finish, which is correct
        # behaviour (we want to know if persistence broke).
        try:
            settings = _cached_scanner_settings()
            signals_repo = SignalsRepository(repo.conn, schema=settings.db_schema)
            candidate = run_scanner_detectors(
                repo=repo,
                signals_repo=signals_repo,
                settings=settings,
                run_id=run_id,
                ticker=ticker,
                today=_date.today(),
            )
            if candidate is not None:
                logger.info(
                    "scanner: %s run_id=%d emitted candidate (type_f=%s, final=%s)",
                    ticker, run_id, candidate.is_type_f, candidate.final_score,
                )
        except Exception as exc:  # noqa: BLE001 — never block the scan on scanner work
            logger.exception(
                "scanner detectors failed for %s run_id=%s: %s",
                ticker, run_id, repr(exc),
            )

        repo.finish_scan_run(run_id, status="ok")
```

Verify the `Settings` symbol is in scope. Open the import block at the top of `pipeline.py` — `from .config import Settings` should already be there (line 17). If not, add it.

- [ ] **6.2 Write the integration test.**

Create `tests/integration/scanner/test_scanner_orchestrator_e2e.py`:

```python
"""End-to-end orchestrator: insert synthetic flow_events + a posture
row into the test DB, call scanner.run_detectors directly against the
real Repository, verify all three target tables are populated."""

from __future__ import annotations

import os
from datetime import date, timedelta
from decimal import Decimal

from uw_scan.config import Settings
from uw_scan.scanner.pipeline import run_detectors
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

# UW_SCAN_API_KEY is required by Settings.from_env. The orchestrator
# never reaches out to UW (everything reads from the test DB), so a
# dummy value is fine.
os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-unused")

TODAY = date(2026, 5, 17)


def _settings() -> Settings:
    return Settings.from_env()


def _insert_qualifying_dcf_alert(conn, run_id: int, ticker: str) -> None:
    """Insert a single FlowAlert row that DCF will qualify."""
    sql = """
        INSERT INTO uw_scan.flow_events
          (run_id, alert_id, ticker, option_type, strike, underlying_price,
           total_premium, total_ask_side_prem, total_bid_side_prem,
           volume, open_interest, has_multileg, expiry, next_earnings_date)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (run_id, "alert-1", ticker.upper(), "call",
             Decimal("100"), Decimal("100"),
             Decimal("800000"), Decimal("700000"), Decimal("100000"),
             2000, 1000, False,
             TODAY + timedelta(days=30),
             TODAY + timedelta(days=60)),
        )


def _insert_posture(conn, chip: str) -> None:
    """Minimal gold_posture_daily row so fetch_gold_posture_latest()
    returns something. The seeded_db_empty_cards fixture re-runs
    every migration, so 043_gold_posture has already been applied."""
    sql = """
        INSERT INTO uw_scan.gold_posture_daily (obs_date, computed_at,
                                                 structural_posture_chip)
        VALUES (%s, NOW(), %s)
    """
    with conn.cursor() as cur:
        cur.execute(sql, (TODAY, chip))


def test_e2e_dcf_only_writes_hit_and_gate(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    _insert_posture(repo.conn, "NEUTRAL")
    run_id = repo.insert_scan_run("AAPL")
    _insert_qualifying_dcf_alert(repo.conn, run_id, "AAPL")
    repo.conn.commit()

    cand = run_detectors(
        repo=repo, signals_repo=sigs, settings=_settings(),
        run_id=run_id, ticker="AAPL", today=TODAY,
    )
    repo.conn.commit()

    assert cand is not None
    assert cand.is_type_f is False
    hits = sigs.fetch_hits_for_run(run_id, "AAPL")
    assert any(h["signal_type"] == "deep_conviction_flow" for h in hits)
    gate = sigs.fetch_gate_for_run(run_id, "AAPL")
    assert gate == {"earnings": "pass", "liquidity": "pass", "regime": "pass"}


def test_e2e_suspended_posture_blocks_with_gate_recorded(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    _insert_posture(repo.conn, "SUSPENDED")
    run_id = repo.insert_scan_run("AAPL")
    _insert_qualifying_dcf_alert(repo.conn, run_id, "AAPL")
    repo.conn.commit()

    cand = run_detectors(
        repo=repo, signals_repo=sigs, settings=_settings(),
        run_id=run_id, ticker="AAPL", today=TODAY,
    )
    repo.conn.commit()

    assert cand is None
    gate = sigs.fetch_gate_for_run(run_id, "AAPL")
    assert gate is not None and gate["regime"] == "block"
    hits = sigs.fetch_hits_for_run(run_id, "AAPL")
    assert hits == []
```

- [ ] **6.3 Run the integration test, confirm green.**

Run: `uv run pytest tests/integration/scanner/test_scanner_orchestrator_e2e.py -v`
Expected: 2 passed.

Run full suite: `uv run pytest -x -q`
Expected: green.

- [ ] **6.4 Commit milestone.**

```bash
git add src/uw_scan/pipeline.py tests/integration/scanner/test_scanner_orchestrator_e2e.py
git commit -m "feat(scanner): wire run_detectors into pipeline.run_single_stock

Calls run_scanner_detectors as the final stage before
finish_scan_run, with a guarded try/except so scanner failures
never block the scan itself (similar to trade_insights). An
integration test exercises the wiring end-to-end with a real
Postgres connection: posture row, flow_events insert, repo +
signals_repo, then verifies hit + gate were persisted.

Spec §2, §15 step 5."
```

---

## Milestone 7 — API: models, router, server registration, web type regen

**Files:**
- Create: `src/uw_scan/api/models/__init__.py`
- Create: `src/uw_scan/api/models/scanner.py`
- Create: `src/uw_scan/api/routers/scanner.py`
- Modify: `src/uw_scan/api/server.py` (2 lines)
- Create: `tests/integration/api/test_scanner_endpoint.py` (placed under `api/` so it inherits the existing `client` fixture from `tests/integration/api/conftest.py`)
- Modify: `web/lib/types.ts` (regenerated)

- [ ] **7.1 Write the failing integration test.**

Create `tests/integration/api/test_scanner_endpoint.py`. This file inherits the `client` fixture from `tests/integration/api/conftest.py` (wires `app.dependency_overrides` against the test DB) AND the `seeded_db_empty_cards` fixture from `tests/integration/conftest.py` (drops/migrates the test schema and seeds the standard 54-ticker watchlist).

```python
"""GET /api/scanner — shape, empty state, type-F filter."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_empty_response_when_no_recent_scans(client, seeded_db_empty_cards):
    # 54 tickers seeded into watchlist, zero scan_runs → empty candidates
    # AND empty gated (GATED is regime-only per spec §9; tickers with no
    # recent scanner-producing run are silently dropped).
    r = client.get("/api/scanner")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"] == []
    assert body["gated"] == []
    assert body["candidates_with_hits"] == 0
    assert body["scanned_universe_size"] >= 1


def test_dcf_candidate_appears_with_hits_and_gates(
    client, seeded_db_with_cards
):
    """seeded_db_with_cards already inserts one scan_run + one
    watchlist_card for TSLA. We add the scanner outputs on top."""
    repo: Repository = seeded_db_with_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    # Use the run_id created by seeded_db_with_cards (TSLA's latest run)
    run_id = repo.latest_run_id("TSLA")
    sigs.upsert_signal_hit(
        run_id=run_id, ticker="TSLA",
        signal_type="deep_conviction_flow", tier=1, score=Decimal("0.85"),
        evidence={"qualifying_alerts": 2}, freshness="live",
    )
    sigs.upsert_gate(
        run_id=run_id, ticker="TSLA",
        earnings="pass", liquidity="pass", regime="pass",
    )
    repo.conn.commit()

    r = client.get("/api/scanner")
    assert r.status_code == 200
    body = r.json()
    candidates = body["candidates"]
    tsla = next((c for c in candidates if c["ticker"] == "TSLA"), None)
    assert tsla is not None
    assert any(h["signal_type"] == "deep_conviction_flow"
               for h in tsla["hits"])
    assert tsla["gates"]["regime"] == "pass"
    # spot is whatever seeded_db_with_cards inserted (445.12)
    assert Decimal(tsla["spot"]) == Decimal("445.12")


def test_type_f_only_filter_excludes_single_signal_candidate(
    client, seeded_db_with_cards
):
    repo: Repository = seeded_db_with_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.latest_run_id("TSLA")
    sigs.upsert_signal_hit(
        run_id=run_id, ticker="TSLA",
        signal_type="deep_conviction_flow", tier=1, score=Decimal("0.85"),
        evidence={}, freshness="live",
    )
    sigs.upsert_gate(
        run_id=run_id, ticker="TSLA",
        earnings="pass", liquidity="pass", regime="pass",
    )
    repo.conn.commit()

    r = client.get("/api/scanner?type_f_only=true")
    assert r.status_code == 200
    candidates = r.json()["candidates"]
    assert all(c["ticker"] != "TSLA" for c in candidates)
```

Note on `repo.latest_run_id("TSLA")` — verified to exist (`repository.py` exposes it; `tests/integration/conftest.py:84` already uses it). If the method name is different in your codebase, query directly: `SELECT MAX(run_id) FROM uw_scan.scan_runs WHERE ticker='TSLA' AND status='ok'`.

- [ ] **7.2 Run the test, confirm failure.**

Run: `uv run pytest tests/integration/api/test_scanner_endpoint.py -v`
Expected: `404 Not Found` for `/api/scanner` (router not registered).

- [ ] **7.3 Create response models.**

`src/uw_scan/api/models/__init__.py` — empty file.

`src/uw_scan/api/models/scanner.py`:

```python
"""Scanner API response models (spec §8)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel


SignalType = Literal[
    "deep_conviction_flow",
    "dark_pool_accumulation",
    "earnings_iv_crush",
    "gex_pinning",
]


class ScannerSignalHit(BaseModel):
    signal_type: SignalType
    tier: Literal[1, 2]
    score: Decimal
    evidence: dict[str, Any]
    freshness: Literal["live", "stale", "unavailable"]


class ScannerContextFlag(BaseModel):
    layer: Literal["pcr_sentiment"]
    label: str
    value: Decimal | None


class ScannerGatesStatus(BaseModel):
    earnings: Literal["pass", "block"]
    liquidity: Literal["pass", "block"]
    regime: Literal["pass", "block"]


class ScannerCandidate(BaseModel):
    ticker: str
    spot: Decimal | None
    is_type_f: bool
    raw_score: Decimal
    confluence_score: Decimal
    final_score: Decimal
    hits: list[ScannerSignalHit]
    context_flags: list[ScannerContextFlag]
    gates: ScannerGatesStatus
    scanned_at: datetime


class ScannerGatedTicker(BaseModel):
    ticker: str
    reason: Literal["regime_block", "stale_scan"]
    blocking_chip: Literal["SUSPENDED", "DEGRADED"] | None = None
    scanned_at: datetime | None


class ScannerResponse(BaseModel):
    scanned_universe_size: int
    candidates_with_hits: int
    candidates: list[ScannerCandidate]
    gated: list[ScannerGatedTicker]
    generated_at: datetime
```

- [ ] **7.4 Create the router.**

`src/uw_scan/api/routers/scanner.py`:

```python
"""GET /api/scanner — read-only assembler over warm store.

Selects the latest 'ok' scan_runs row per watchlist ticker within
SCANNER_FRESHNESS_HOURS, filtered to scanner-producing runs via
EXISTS(signal_gates). Joins signal_hits + signal_context_flags +
signal_gates + watchlist_cards (for spot). Builds ScanCandidates,
ranks, and returns. Tickers gated by regime go into the `gated`
section with the blocking GOLD posture chip name.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.models.scanner import (
    ScannerCandidate,
    ScannerContextFlag,
    ScannerGatedTicker,
    ScannerGatesStatus,
    ScannerResponse,
    ScannerSignalHit,
)
from uw_scan.config import Settings
from uw_scan.scanner.ranking import (
    RANKING_TIER_WEIGHTS,
    RAW_RANKING_EXCLUDE,
    rank_candidates,
)
from uw_scan.scanner.models import (
    ContextFlag as DCContextFlag,
    ScanCandidate as DCScanCandidate,
    SignalHit as DCSignalHit,
)
from uw_scan.scanner.ranking import build_candidate
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["scanner"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _latest_scanner_runs_per_ticker(
    repo: Repository, *, freshness_hours: int
) -> list[dict[str, Any]]:
    """One row per watchlist ticker for the latest scanner-producing
    run within the freshness window. EXISTS(signal_gates) filters out
    flow_data_refresh / cockpit_daily_snapshot runs (spec §8)."""
    sql = """
        SELECT DISTINCT ON (w.ticker)
          w.ticker,
          r.run_id,
          r.finished_at AS scanned_at,
          c.spot
        FROM uw_scan.watchlist w
        LEFT JOIN uw_scan.scan_runs r
          ON r.ticker = w.ticker
         AND r.status = 'ok'
         AND r.finished_at >= NOW() - %s::interval
         AND EXISTS (
           SELECT 1 FROM uw_scan.signal_gates g
           WHERE g.run_id = r.run_id
         )
        LEFT JOIN uw_scan.watchlist_card c ON c.ticker = w.ticker
        WHERE w.removed_at IS NULL
        ORDER BY w.ticker, r.finished_at DESC NULLS LAST
    """
    with repo.conn.cursor() as cur:
        cur.execute(sql, (f"{freshness_hours} hours",))
        rows = cur.fetchall()
        cols = [c.name for c in cur.description]
    return [dict(zip(cols, r, strict=True)) for r in rows]


def _hits_to_dc(rows: list[dict[str, Any]], ticker: str) -> list[DCSignalHit]:
    return [
        DCSignalHit(
            ticker=ticker,
            signal_type=r["signal_type"],
            tier=int(r["tier"]),
            score=Decimal(str(r["score"])),
            evidence=dict(r["evidence"]) if r["evidence"] else {},
            freshness=r["freshness"],
        )
        for r in rows
    ]


def _flags_to_dc(rows: list[dict[str, Any]], ticker: str) -> list[DCContextFlag]:
    return [
        DCContextFlag(
            ticker=ticker, layer=r["layer"], label=r["label"],
            value=Decimal(str(r["value"])) if r["value"] is not None else None,
        )
        for r in rows
    ]


def _dc_to_response_hit(h: DCSignalHit) -> ScannerSignalHit:
    return ScannerSignalHit(
        signal_type=h.signal_type,  # type: ignore[arg-type]
        tier=h.tier,
        score=h.score,
        evidence=h.evidence,
        freshness=h.freshness,
    )


def _dc_to_response_flag(f: DCContextFlag) -> ScannerContextFlag:
    return ScannerContextFlag(
        layer=f.layer,  # type: ignore[arg-type]
        label=f.label,
        value=f.value,
    )


@router.get("", response_model=ScannerResponse)
def get_scanner(
    tier_1_only: bool = Query(False),
    type_f_only: bool = Query(False),
    sector: str | None = Query(None),
    freshness_hours: int | None = Query(None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ScannerResponse:
    sigs = SignalsRepository(repo.conn, schema=settings.db_schema)
    fh = freshness_hours if freshness_hours is not None \
        else settings.scanner_freshness_hours

    latest = _latest_scanner_runs_per_ticker(repo, freshness_hours=fh)

    # Universe size (active watchlist count regardless of scan freshness).
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM uw_scan.watchlist WHERE removed_at IS NULL"
        )
        scanned_universe_size = int(cur.fetchone()[0])

    candidates: list[DCScanCandidate] = []
    gated: list[ScannerGatedTicker] = []

    # Pull current GOLD posture once; used for the blocking_chip annotation
    # on regime-blocked tickers in the GATED section.
    try:
        posture_row = repo.fetch_gold_posture_latest()
    except Exception:  # noqa: BLE001
        posture_row = None
    current_chip = (
        posture_row.get("structural_posture_chip") if posture_row else None
    )

    for row in latest:
        ticker = row["ticker"]
        run_id = row.get("run_id")
        if run_id is None:
            # No recent scanner-producing run for this ticker — silently
            # drop in V1. Spec §9: GATED shows ONLY regime-blocked
            # tickers. The `stale_scan` reason is kept in the model for
            # future use (emit + UI render together in a follow-up).
            continue

        gate = sigs.fetch_gate_for_run(run_id, ticker) or {
            "earnings": "pass", "liquidity": "pass", "regime": "pass",
        }
        if gate["regime"] == "block":
            chip: Literal["SUSPENDED", "DEGRADED"] | None = None
            if current_chip in ("SUSPENDED", "DEGRADED"):
                chip = current_chip  # type: ignore[assignment]
            gated.append(ScannerGatedTicker(
                ticker=ticker, reason="regime_block",
                blocking_chip=chip, scanned_at=row.get("scanned_at"),
            ))
            continue

        hit_rows = sigs.fetch_hits_for_run(run_id, ticker)
        flag_rows = sigs.fetch_context_flags_for_run(run_id, ticker)
        dc_hits = _hits_to_dc(hit_rows, ticker)
        dc_flags = _flags_to_dc(flag_rows, ticker)
        cand = build_candidate(
            ticker=ticker, hits=dc_hits, context_flags=dc_flags, gates=gate,
        )
        if cand is None:
            continue
        candidates.append(cand)

    ranked = rank_candidates(candidates)

    # Filters
    def _has_tier_1(c: DCScanCandidate) -> bool:
        return any(h.tier == 1 for h in c.hits)

    if tier_1_only:
        ranked = [c for c in ranked if _has_tier_1(c)]
    if type_f_only:
        ranked = [c for c in ranked if c.is_type_f]

    # Sector filter — query watchlist for ticker→sector
    if sector:
        with repo.conn.cursor() as cur:
            cur.execute(
                "SELECT ticker FROM uw_scan.watchlist WHERE sector = %s",
                (sector,),
            )
            ok = {row[0] for row in cur.fetchall()}
        ranked = [c for c in ranked if c.ticker in ok]

    # Spot lookup table from the latest_scanner_runs query
    spot_map = {row["ticker"]: row.get("spot") for row in latest}
    scanned_at_map = {row["ticker"]: row.get("scanned_at") for row in latest}

    response_candidates = [
        ScannerCandidate(
            ticker=c.ticker,
            spot=spot_map.get(c.ticker),
            is_type_f=c.is_type_f,
            raw_score=c.raw_score,
            confluence_score=c.confluence_score,
            final_score=c.final_score,
            hits=[_dc_to_response_hit(h) for h in c.hits],
            context_flags=[_dc_to_response_flag(f) for f in c.context_flags],
            gates=ScannerGatesStatus(
                earnings=c.gates["earnings"],  # type: ignore[arg-type]
                liquidity=c.gates["liquidity"],  # type: ignore[arg-type]
                regime=c.gates["regime"],  # type: ignore[arg-type]
            ),
            scanned_at=scanned_at_map.get(c.ticker) or _now_utc(),
        )
        for c in ranked
    ]

    return ScannerResponse(
        scanned_universe_size=scanned_universe_size,
        candidates_with_hits=len(response_candidates),
        candidates=response_candidates,
        gated=gated,
        generated_at=_now_utc(),
    )
```

- [ ] **7.5 Register the router in `server.py`.**

In `src/uw_scan/api/server.py` line 8, add `scanner` to the import list:

```python
from uw_scan.api.routers import (
    cockpit,
    gold,
    health,
    jobs,
    ohlc,
    provider_usage,
    scanner,
    stock,
    trade_insights,
    volatility,
    watchlist,
)
```

After the `gold` registration on line 44, add:

```python
    app.include_router(scanner.router, prefix="/api", tags=["scanner"])
```

- [ ] **7.6 Run the integration test, confirm green.**

Run: `uv run pytest tests/integration/api/test_scanner_endpoint.py -v`
Expected: 3 passed.

Run full suite: `uv run pytest -x -q`
Expected: green.

- [ ] **7.7 Regenerate web types.**

Run: `cd web && npm run gen:types && cd ..`
Expected: `web/lib/types.ts` updated with `ScannerResponse`, `ScannerCandidate`, etc. Inspect:

```bash
grep -c "ScannerCandidate\|ScannerResponse\|ScannerSignalHit\|ScannerGatedTicker" web/lib/types.ts
```

Expected: ≥ 4.

- [ ] **7.8 Commit milestone.**

```bash
git add src/uw_scan/api/models/__init__.py \
        src/uw_scan/api/models/scanner.py \
        src/uw_scan/api/routers/scanner.py \
        src/uw_scan/api/server.py \
        tests/integration/api/test_scanner_endpoint.py \
        web/lib/types.ts
git commit -m "feat(scanner): GET /api/scanner endpoint + regenerated web types

Read-only assembler over warm store. EXISTS(signal_gates) filter
restricts to scanner-producing runs. tier_1_only and type_f_only
boolean filters keep the query semantics unambiguous. Regime-blocked
tickers surface in the GATED section with the blocking GOLD posture
chip name (SUSPENDED|DEGRADED) for the human-readable UI message.

Spec §8."
```

---

## Milestone 8 — Frontend: scanner page + components + tests

**Files:**
- Modify: `web/lib/api.ts` (add `api.scanner` method following the existing `_fetch<T>` + typed-`paths`-via-Json pattern)
- Modify: `web/app/scanner/page.tsx`
- Create: `web/app/scanner/loading.tsx`
- Create: `web/components/scanner/CandidateTile.tsx`
- Create: `web/components/scanner/SignalBadge.tsx`
- Create: `web/components/scanner/ContextFlagBadge.tsx`
- Create: `web/components/scanner/GatesIndicator.tsx`
- Create: `web/components/scanner/GatedList.tsx`
- Create: `web/components/scanner/ScannerFilters.tsx`
- Create: `web/tests/unit/scannerPage.test.tsx`
- Create: `web/tests/e2e/scanner-page.spec.ts`

**Verified setup (no install needed):** `web/package.json` already has `@testing-library/react ^16.3.2`, `@testing-library/dom ^10.4.1`, `jsdom ^25.0.1`, `vitest ^4.0.18`, and `@playwright/test ^1.58.2` in `devDependencies`. The vitest config (`web/vitest.config.ts`) sets `environment: "jsdom"` globally and globs `tests/**/*.test.{ts,tsx}`. The existing test convention (verified in `web/tests/unit/cardGrid.test.tsx:1`) prepends `/* @vitest-environment jsdom */` as a per-file safety directive — follow it.

**Project convention (verified):** All HTTP from the frontend goes through `web/lib/api.ts`, which exports an `api` object with typed methods (e.g. `api.watchlist(...)`, `api.stock(ticker)`). The base URL is `process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400"` set as `const API` at the top of `api.ts`. Use this convention — do NOT inline raw `fetch(...)` in the page.

- [ ] **8.1 Add `api.scanner` to `web/lib/api.ts`.**

Add a new typed alias to the type section near the top (around lines 40-45, after the cockpit aliases):

```ts
type ScannerResponse = Json<"/api/scanner", "get">;
```

Add the method to the exported `api` object (place near the other GET methods, e.g. after `cockpitVrp`):

```ts
  scanner: (params: URLSearchParams = new URLSearchParams()):
    Promise<ScannerResponse> => {
    const q = params.toString();
    return _fetch<ScannerResponse>(`/api/scanner${q ? `?${q}` : ""}`);
  },
```

- [ ] **8.2 Implement `SignalBadge.tsx`.**

```tsx
import type { components } from "@/lib/types";

type Hit = components["schemas"]["ScannerSignalHit"];

const TIER_BG: Record<1 | 2, string> = {
  1: "var(--accent-warm)",
  2: "var(--accent-bg)",
};

function describeEvidence(h: Hit): string {
  switch (h.signal_type) {
    case "deep_conviction_flow": {
      const tp = h.evidence?.total_premium;
      const dte = h.evidence?.top_dte;
      const prem = tp ? `$${formatShortUsd(Number(tp))}` : "";
      return [prem, dte != null ? `${dte} DTE` : null]
        .filter(Boolean)
        .join(" · ");
    }
    case "dark_pool_accumulation": {
      const size = h.evidence?.cluster_size;
      const price = h.evidence?.anchor_price;
      return `cluster of ${size}${price ? ` @ $${price}` : ""}`;
    }
    case "earnings_iv_crush": {
      const iv = h.evidence?.iv_rank;
      const dte = h.evidence?.earnings_within_days;
      return [iv ? `iv_rank ${iv}` : null, dte != null ? `earn in ${dte}d` : null]
        .filter(Boolean)
        .join(" · ");
    }
    case "gex_pinning": {
      const pin = h.evidence?.strike;
      const dist = h.evidence?.distance_pct;
      return `pin ${pin}${dist ? ` (${Number(dist).toFixed(2)}%)` : ""}`;
    }
    default:
      return "";
  }
}

function formatShortUsd(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toFixed(0);
}

const LABEL_BY_TYPE: Record<Hit["signal_type"], string> = {
  deep_conviction_flow: "DCF",
  dark_pool_accumulation: "DP",
  earnings_iv_crush: "EIC",
  gex_pinning: "GEX",
};

export function SignalBadge({ hit }: { hit: Hit }) {
  const tier = hit.tier === 1 ? 1 : 2;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        marginRight: 8,
        borderRadius: 3,
        backgroundColor: TIER_BG[tier],
        color: "var(--text-primary)",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
      }}
    >
      {LABEL_BY_TYPE[hit.signal_type]} · tier {hit.tier} · {describeEvidence(hit)}
    </span>
  );
}
```

- [ ] **8.3 Implement `ContextFlagBadge.tsx`.**

```tsx
import type { components } from "@/lib/types";

type Flag = components["schemas"]["ScannerContextFlag"];

const COLOR_BY_LABEL: Record<string, string> = {
  "Extreme Fear": "var(--negative)",
  "Elevated Fear": "var(--negative)",
  "Complacent": "var(--positive)",
};

export function ContextFlagBadge({ flag }: { flag: Flag }) {
  const color = COLOR_BY_LABEL[flag.label] ?? "var(--warning)";
  return (
    <span
      style={{
        color,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
        marginRight: 12,
      }}
    >
      flag: {flag.label}
    </span>
  );
}
```

- [ ] **8.4 Implement `GatesIndicator.tsx`.**

```tsx
import type { components } from "@/lib/types";

type Gates = components["schemas"]["ScannerGatesStatus"];

function dot(status: "pass" | "block") {
  return status === "pass" ? "✓" : "✗";
}
function color(status: "pass" | "block") {
  return status === "pass" ? "var(--positive)" : "var(--negative)";
}

export function GatesIndicator({ gates }: { gates: Gates }) {
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
        color: "var(--text-muted)",
      }}
    >
      gates:{" "}
      <span style={{ color: color(gates.earnings) }}>
        earnings {dot(gates.earnings)}
      </span>{" "}
      <span style={{ color: color(gates.liquidity) }}>
        liq {dot(gates.liquidity)}
      </span>{" "}
      <span style={{ color: color(gates.regime) }}>
        regime {dot(gates.regime)}
      </span>
    </span>
  );
}
```

- [ ] **8.5 Implement `CandidateTile.tsx`.**

```tsx
import Link from "next/link";

import { RescanButton } from "@/components/shared/RescanButton";
import { bucketFreshness } from "@/lib/freshness";
import type { components } from "@/lib/types";

import { ContextFlagBadge } from "./ContextFlagBadge";
import { GatesIndicator } from "./GatesIndicator";
import { SignalBadge } from "./SignalBadge";

type Candidate = components["schemas"]["ScannerCandidate"];

const DOT_COLOR: Record<"fresh" | "stale" | "dead", string> = {
  fresh: "var(--positive)",
  stale: "var(--warning)",
  dead: "var(--negative)",
};

function freshnessLabel(scannedAt: string): string {
  const minutes = Math.max(
    0,
    Math.round((Date.now() - new Date(scannedAt).getTime()) / 60_000),
  );
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

export function CandidateTile({ candidate }: { candidate: Candidate }) {
  const freshness = bucketFreshness(candidate.scanned_at);
  return (
    <div
      style={{
        padding: 16,
        marginBottom: 8,
        backgroundColor: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          {candidate.is_type_f ? (
            <span style={{ color: "var(--accent-warm)" }}>*</span>
          ) : null}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 18,
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {candidate.ticker}
          </span>
          {candidate.spot ? (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 14,
                color: "var(--text-muted)",
              }}
            >
              ${candidate.spot}
            </span>
          ) : null}
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 22,
            fontWeight: 700,
            color: "var(--text-primary)",
          }}
        >
          {Number(candidate.final_score).toFixed(2)}
        </span>
      </div>
      <div style={{ marginBottom: 6 }}>
        {candidate.hits.map((h) => (
          <SignalBadge key={h.signal_type} hit={h} />
        ))}
      </div>
      <div style={{ marginBottom: 8 }}>
        {candidate.context_flags.map((f) => (
          <ContextFlagBadge key={f.layer} flag={f} />
        ))}
        <GatesIndicator gates={candidate.gates} />
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--text-muted)",
        }}
      >
        <span>
          <span
            style={{
              display: "inline-block",
              width: 6,
              height: 6,
              borderRadius: "50%",
              backgroundColor: DOT_COLOR[freshness],
              marginRight: 6,
            }}
          />
          scanned {freshnessLabel(candidate.scanned_at)}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <RescanButton ticker={candidate.ticker} initialJob={null} />
          <Link
            href={`/stock/${candidate.ticker}/trade-plan`}
            style={{
              color: "var(--accent-warm)",
              textDecoration: "none",
            }}
          >
            Evaluate →
          </Link>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **8.6 Implement `GatedList.tsx`.**

```tsx
import type { components } from "@/lib/types";

type Gated = components["schemas"]["ScannerGatedTicker"];

function reasonText(g: Gated): string {
  if (g.reason === "stale_scan") return "stale scan (older than freshness window)";
  if (g.reason === "regime_block") {
    return g.blocking_chip
      ? `regime block (structural posture: ${g.blocking_chip})`
      : "regime block";
  }
  return g.reason;
}

export function GatedList({ gated }: { gated: Gated[] }) {
  if (gated.length === 0) return null;
  return (
    <div style={{ marginTop: 24 }}>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          color: "var(--text-muted)",
          textTransform: "uppercase",
          marginBottom: 8,
        }}
      >
        GATED ({gated.length} watchlist ticker
        {gated.length === 1 ? "" : "s"} excluded)
      </div>
      <div
        style={{
          padding: 16,
          backgroundColor: "var(--bg-panel)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
        }}
      >
        {gated.map((g) => (
          <div
            key={g.ticker}
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text-muted)",
              padding: "4px 0",
            }}
          >
            <span style={{ color: "var(--text-primary)" }}>{g.ticker}</span>
            <span>{reasonText(g)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **8.7 Implement `ScannerFilters.tsx`.**

```tsx
"use client";
import { useRouter, useSearchParams } from "next/navigation";

export function ScannerFilters() {
  const router = useRouter();
  const params = useSearchParams();
  const typeFOnly = params.get("type_f_only") === "true";
  const tier1Only = params.get("tier_1_only") === "true";

  function toggle(key: string, value: boolean) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(key, "true");
    else next.delete(key);
    router.push(`/scanner?${next.toString()}`);
  }

  const checkboxStyle: React.CSSProperties = {
    fontFamily: "var(--font-mono)",
    fontSize: 11,
    color: "var(--text-muted)",
    letterSpacing: 0.5,
    marginRight: 24,
    cursor: "pointer",
  };

  return (
    <div style={{ marginBottom: 16 }}>
      <label style={checkboxStyle}>
        <input
          type="checkbox"
          checked={typeFOnly}
          onChange={(e) => toggle("type_f_only", e.target.checked)}
          style={{ marginRight: 6 }}
        />
        Type F only
      </label>
      <label style={checkboxStyle}>
        <input
          type="checkbox"
          checked={tier1Only}
          onChange={(e) => toggle("tier_1_only", e.target.checked)}
          style={{ marginRight: 6 }}
        />
        Tier 1 only
      </label>
    </div>
  );
}
```

- [ ] **8.8 Implement `loading.tsx`.**

```tsx
export default function ScannerLoading() {
  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <h1
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 24,
          letterSpacing: 1,
          marginBottom: 16,
        }}
      >
        SCANNER
      </h1>
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          style={{
            height: 96,
            marginBottom: 8,
            backgroundColor: "var(--bg-panel)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            opacity: 0.5,
          }}
        />
      ))}
    </div>
  );
}
```

- [ ] **8.9 Implement the page.**

Replace `web/app/scanner/page.tsx` with:

```tsx
import { CandidateTile } from "@/components/scanner/CandidateTile";
import { GatedList } from "@/components/scanner/GatedList";
import { ScannerFilters } from "@/components/scanner/ScannerFilters";
import { api } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ScannerPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const qs = new URLSearchParams();
  if (params.type_f_only === "true") qs.set("type_f_only", "true");
  if (params.tier_1_only === "true") qs.set("tier_1_only", "true");
  if (typeof params.sector === "string") qs.set("sector", params.sector);
  const data = await api.scanner(qs);

  return (
    <div style={{ padding: 24, maxWidth: 1600, margin: "0 auto" }}>
      <h1
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 24,
          letterSpacing: 1,
          marginBottom: 16,
        }}
      >
        SCANNER
      </h1>
      <ScannerFilters />
      {data.candidates.length === 0 ? (
        <div
          style={{
            padding: 24,
            border: "1px dashed var(--border-dim)",
            borderRadius: 4,
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            textAlign: "center",
          }}
        >
          no candidates — {data.scanned_universe_size} ticker
          {data.scanned_universe_size === 1 ? "" : "s"} on watchlist, none with
          recent scanner-producing scans
        </div>
      ) : (
        data.candidates.map((c) => (
          <CandidateTile key={c.ticker} candidate={c} />
        ))
      )}
      <GatedList gated={data.gated} />
    </div>
  );
}
```

- [ ] **8.10 Write Vitest test.**

`web/tests/unit/scannerPage.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CandidateTile } from "@/components/scanner/CandidateTile";
import { GatedList } from "@/components/scanner/GatedList";
import { SignalBadge } from "@/components/scanner/SignalBadge";
import type { components } from "@/lib/types";

type Candidate = components["schemas"]["ScannerCandidate"];
type Gated = components["schemas"]["ScannerGatedTicker"];

function makeCandidate(overrides: Partial<Candidate> = {}): Candidate {
  return {
    ticker: "AAPL",
    spot: "185.20" as unknown as Candidate["spot"],
    is_type_f: false,
    raw_score: "5.10" as unknown as Candidate["raw_score"],
    confluence_score: "3.0" as unknown as Candidate["confluence_score"],
    final_score: "8.10" as unknown as Candidate["final_score"],
    hits: [
      {
        signal_type: "deep_conviction_flow",
        tier: 1,
        score: "0.85" as unknown as Candidate["hits"][number]["score"],
        evidence: { total_premium: "1500000", top_dte: 30 },
        freshness: "live",
      },
    ],
    context_flags: [],
    gates: { earnings: "pass", liquidity: "pass", regime: "pass" },
    scanned_at: new Date().toISOString(),
    ...overrides,
  };
}

describe("CandidateTile", () => {
  it("renders ticker, spot, score and Evaluate link", () => {
    render(<CandidateTile candidate={makeCandidate()} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText(/\$185\.20/)).toBeInTheDocument();
    expect(screen.getByText("8.10")).toBeInTheDocument();
    expect(screen.getByText("Evaluate →")).toBeInTheDocument();
  });

  it("shows the type-F marker only when is_type_f is true", () => {
    const { rerender } = render(<CandidateTile candidate={makeCandidate()} />);
    expect(screen.queryByText("*")).not.toBeInTheDocument();
    rerender(<CandidateTile candidate={makeCandidate({ is_type_f: true })} />);
    expect(screen.getByText("*")).toBeInTheDocument();
  });
});

describe("SignalBadge", () => {
  it("renders DCF with premium and DTE", () => {
    const candidate = makeCandidate();
    render(<SignalBadge hit={candidate.hits[0]} />);
    expect(screen.getByText(/DCF/)).toBeInTheDocument();
    expect(screen.getByText(/1\.5M/)).toBeInTheDocument();
    expect(screen.getByText(/30 DTE/)).toBeInTheDocument();
  });
});

describe("GatedList", () => {
  it("renders nothing when no gated tickers", () => {
    const { container } = render(<GatedList gated={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("shows blocking chip in the reason text", () => {
    const gated: Gated[] = [
      {
        ticker: "AMD",
        reason: "regime_block",
        blocking_chip: "SUSPENDED",
        scanned_at: new Date().toISOString(),
      },
    ];
    render(<GatedList gated={gated} />);
    expect(screen.getByText("AMD")).toBeInTheDocument();
    expect(
      screen.getByText(/regime block \(structural posture: SUSPENDED\)/),
    ).toBeInTheDocument();
  });
});
```


- [ ] **8.11 Write Playwright smoke test.**

`web/tests/e2e/scanner-page.spec.ts`:

```ts
import { expect, test } from "@playwright/test";

test.describe("/scanner page", () => {
  test("loads and renders the header", async ({ page }) => {
    await page.goto("/scanner");
    await expect(page.getByRole("heading", { name: "SCANNER" })).toBeVisible();
  });

  test("filter chip toggles URL search param", async ({ page }) => {
    await page.goto("/scanner");
    const typeFCheckbox = page.getByLabel("Type F only");
    if (await typeFCheckbox.isVisible()) {
      await typeFCheckbox.check();
      await expect(page).toHaveURL(/type_f_only=true/);
    }
  });
});
```

- [ ] **8.12 Run web tests.**

Run: `cd web && npm test -- --run scannerPage && cd ..`
Expected: 3 Vitest test groups pass (CandidateTile, SignalBadge, GatedList).

Playwright smoke is gated on the dev server. Skip running Playwright unless `bash scripts/dev.sh` is already running locally; if not, mark the spec as written but defer execution to first dev-server run.

Run typecheck and lint:

```bash
cd web && npm run typecheck && cd ..
cd web && npm run lint && cd ..
```

Expected: both green.

- [ ] **8.13 Browser sanity (only if dev server is up).**

Start dev (`bash scripts/dev.sh`) if it isn't already, then in a browser open `http://127.0.0.1:3001/scanner`. The page should render either the empty-state message OR a tile-stack of candidates depending on real DB state. The "Evaluate →" link should route to `/stock/[ticker]/trade-plan`. The "Type F only" toggle should update the URL with `?type_f_only=true`.

If something's off, fix and re-test. Do NOT mark this milestone done with a known UI regression.

- [ ] **8.14 Final full backend suite.**

Run: `uv run pytest -x -q`
Expected: green.

- [ ] **8.15 Commit milestone.**

```bash
git add web/lib/api.ts web/app/scanner/page.tsx web/app/scanner/loading.tsx \
        web/components/scanner/ \
        web/tests/unit/scannerPage.test.tsx \
        web/tests/e2e/scanner-page.spec.ts
git commit -m "feat(scanner): /scanner page replaces stub with ranked tile-stack

RSC fetches GET /api/scanner; client island ScannerFilters drives
URL params for Type-F / Tier-1 filters. CandidateTile reuses the
existing RescanButton and bucketFreshness util. GATED list shows
regime-blocked tickers with the GOLD posture chip name. Empty
state renders when no scanner-producing runs are within the
freshness window. Vitest covers tile + badge + gated-list;
Playwright smoke covers page-load + filter URL toggling.

Spec §9."
```

---

## End-of-plan checklist (after Milestone 8)

- [ ] **Confirm spec success criteria.** Walk spec §13 and verify each:
  1. `/scanner` renders ranked tile-stack ✓ (Milestone 8)
  2. Evaluate → routes to `/stock/[ticker]/trade-plan` ✓ (Milestone 8)
  3. GATED block lists regime-blocked tickers with reason ✓ (Milestones 7+8)
  4. Per-row rescan button enqueues a job ✓ (reuses RescanButton — Milestone 8)
  5. All four detectors have unit tests covering qualifying/non-qualifying inputs ✓ (Milestones 3+4)
  6. Tables populate as expected, integration tested ✓ (Milestones 1+6+7)
  7. `npm run gen:types` clean diff for ScannerResponse ✓ (Milestone 7)
  8. No regression in existing watchlist landing / stock detail ✓ (full suite green after every milestone)

- [ ] **Open the PR.** Push the branch and open a PR — never `git push origin main`:

```bash
git push -u origin <branch-name>
gh pr create --title "Scanner page — ported xenon detectors with GOLD regime gate" \
  --body "$(cat <<'EOF'
## Summary
- New /scanner page ranks watchlist tickers by multi-signal confluence
- Four detectors (DCF, DP, EIC, GEX pinning) + pcr_sentiment context flag
- Three new tables (signal_hits, signal_context_flags, signal_gates) keyed on (run_id, ticker)
- Detectors run inside pipeline.run_single_stock as a final stage — no new scheduler entry
- Regime gate uses GOLD COMPASS structural_posture_chip (deliberate market-wide simplification vs xenon per-ticker)
- Standalone SignalsRepository module — never appended to repository.py

## Test plan
- [ ] uv run pytest -x -q passes
- [ ] cd web && npm test -- --run passes
- [ ] cd web && npm run typecheck passes
- [ ] /scanner renders ranked candidates against real DB
- [ ] Evaluate → routes to /stock/[ticker]/trade-plan
- [ ] Tile rescan button enqueues a job and refreshes after
EOF
)"
```

---

## Tuning notes (post-merge, not part of the plan)

Per spec §15 step 11: after deployment, watch:

- DCF surface rate vs `SCANNER_DCF_MIN_ASK_SIDE` and `SCANNER_DCF_MIN_PREMIUM_USD` — if too noisy, raise; if too quiet, lower.
- Whether `SCANNER_REGIME_BLOCK_CHIPS` defaults are too aggressive — env-overridable to `DEGRADED` only, or empty (disable hard gate) during initial production.
- Whether `dark_pool_events.premium` is stored as dollars (assumed) vs cents — if you see DP firing on nothing or never firing, recheck the column units.

These are operational knobs, not code changes.
