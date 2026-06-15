# Scanner Discovery Expansion + Markout-Ready Persistence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the DISCOVERED section's premium-ranked DCF-only scoring with radon's 5-factor edge-quality score (dark-pool included), move discovery compute into a scheduled job, and persist every scanner candidate (watchlist + discovery) in a markout-ready table.

**Architecture:** A new APScheduler job (`discovery_scan`) pulls market-wide flow alerts, scores each non-watchlist ticker with a new pure `edge_quality` module (live dark-pool enrichment cached into `dark_pool_events`), and persists rows into a new `scanner_candidate_snapshots` table. The `/api/scanner/discover` endpoint becomes a thin read of the latest persisted snapshot. The watchlist detector path additionally persists a markout-ready snapshot per candidate (additive, no scoring change).

**Tech Stack:** Python 3.13 (`uv`), FastAPI + Pydantic v2, psycopg 3, APScheduler, Postgres (`uw_scan` schema), Next.js 16 + React 19 / TypeScript, Vitest + Playwright, pytest + pytest-postgresql.

---

## Spec

Source spec: `docs/superpowers/specs/2026-06-15-scanner-discovery-expansion-design.md`. Read it before starting.

## Deviations from the spec (deliberate, made while writing this plan)

These refine the spec after reading the code in depth. They preserve the spec's intent.

1. **Persistence lives in the existing `SignalsRepository`** (`src/uw_scan/storage/signals_repository.py`), **not** a new `storage/scanner_snapshots.py` Repository mixin. `SignalsRepository` is already the dedicated scanner-persistence module (it satisfies the "never extend `repository.py`" rule — it is a focused standalone module), its own docstring says "both halves of the scanner persistence boundary stay in one file," `run_detectors` already holds a `signals_repo`, and this avoids `repository.py` assembler churn + `rows.py` coupling. Reads return `dict`s, consistent with the existing `_select_dicts` style.
2. **Stage-2 dark-pool fetches are sequential, not concurrent.** The single shared `psycopg` connection is not thread-safe and the UW fetch path writes audit/raw rows through it, so threading is unsafe without per-thread connections. At `top_n = 50` on a 30-minute cadence the sequential latency (~10–25 s) is fine, so the spec's `scanner_discover_dp_concurrency` knob is omitted (concurrency is trivially 1). **The spec's rate-guard intent is still honored** (codex review flagged it): (a) the cron is offset to `:15/:45` so discovery never fires at the top-of-hour alongside `full_scan` (`0 5-16`); (b) the `scanner_discover_dp_top_n` cap bounds total calls per run; (c) `scanner_discover_dp_sleep_ms` (default 0) is an operator-tunable inter-fetch throttle for the rare 429 case; (d) the job is primary-uw-worker-only + advisory single-flight.
3. **Run-level counts** (`alerts_pulled`, `earnings_unknown_dropped`, `candidates_found`, `dp_enriched`, `dp_truncated_dropped`) are persisted to the discovery `scan_runs` row via `upsert_discovery_run_meta` (namespaced under `aggregates->'discovery'`, sentinel ticker `_DISCOVER`, no collision with the real-ticker MarketAggregates readers). This is robust even when a non-empty feed is fully filtered to zero candidates — counts survive independent of candidate rows. Run identity/timestamp come from the same `scan_runs` row.
4. **The old `discover_from_alerts` (DCF discovery) is left intact but unwired** from the API (its unit tests still pass; it also keeps `scanner_discover_min_ask_side` from being dead config). Removing it is out of scope; flag as a follow-up cleanup in the PR description.
5. **`fetch_latest_watchlist_snapshot` (spec line 174) is deliberately not built in Phase 1** — there is no Phase-1 consumer (the watchlist page reads `signal_hits`, not snapshots; the watchlist snapshot is written purely for Phase-2 markout readiness). The Task-9 test verifies the watchlist write via direct SQL. Add the read in Phase 2 when markout consumes it (YAGNI).

## File Structure

**Create:**
- `src/uw_scan/scanner/edge_quality.py` — pure 5-factor 0–100 scorer + directional dark-pool helper (ported from radon `scripts/discover.py`).
- `src/uw_scan/worker/jobs/discovery_scan.py` — scheduled discovery job (Approach A).
- `src/uw_scan/storage/migrations/072_scanner_candidate_snapshots.sql` — table + indexes.
- `tests/unit/scanner/test_edge_quality.py` — unit tests for the scorer.
- `tests/unit/test_config_edge_quality_weights.py` — weight-sum validator test.
- `tests/integration/storage/test_scanner_candidate_snapshots.py` — repo write/read.
- `tests/integration/worker/test_discovery_scan_job.py` — job end-to-end with fakes.

**Replace (existing files whose contract changes):**
- `tests/integration/api/test_scanner_discover.py` — was the live-fetch contract; becomes the snapshot thin-read test.
- `web/tests/unit/discoveredCard.test.tsx` — was DCF-`hit` rendering; becomes 5-factor breakdown rendering.

**Modify:**
- `src/uw_scan/storage/signals_repository.py` — add snapshot write/read methods.
- `src/uw_scan/config.py` — add edge-quality + discovery knobs + weight-sum validator.
- `src/uw_scan/api/models/scanner.py` — enrich `DiscoveryCandidate` + `DiscoveryResponse`.
- `src/uw_scan/api/routers/scanner.py` — `/discover` becomes a thin snapshot read.
- `src/uw_scan/scanner/pipeline.py` (`run_detectors`) — additive watchlist snapshot persist.
- `src/uw_scan/worker/scheduler.py` — register the discovery cron.
- `web/components/scanner/DiscoveredCard.tsx` — render the 5-factor breakdown.
- `web/app/scanner/page.tsx` — header + sort by edge-quality score.
- `web/lib/api.ts` — (no signature change; type flows via `gen:types`).
- `tests/integration/api/openapi.snapshot.json` — regenerated.
- `web/lib/types.ts` — regenerated.

---

## Task 1: Migration — `scanner_candidate_snapshots` table

**Files:**
- Create: `src/uw_scan/storage/migrations/072_scanner_candidate_snapshots.sql`
- Test: `tests/integration/storage/test_scanner_candidate_snapshots.py` (created in Task 2; idempotency covered by the session migrate runner)

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/072_scanner_candidate_snapshots.sql`:

```sql
-- 072_scanner_candidate_snapshots.sql — markout-ready candidate snapshots for
-- BOTH scanner sections (watchlist + discovery). One row per candidate
-- emission. Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.scanner_candidate_snapshots (
  id              BIGSERIAL PRIMARY KEY,
  run_id          BIGINT,
  section         TEXT NOT NULL,            -- 'watchlist' | 'discovery'
  ticker          TEXT NOT NULL,
  scored_at       TIMESTAMPTZ NOT NULL,
  bias            TEXT,                     -- 'bullish'|'bearish'|'mixed'|'neutral'
  direction       TEXT,                     -- 'long'|'short'|NULL  (markout sign)
  score           NUMERIC(8,3),
  score_model     TEXT NOT NULL,            -- 'edge_quality_v1' | 'watchlist_tier_v1'
  score_breakdown JSONB,
  spot_at_signal  NUMERIC,
  is_type_f       BOOLEAN,                  -- watchlist multi-signal flag (NULL for discovery)
  evidence        JSONB,                    -- per-factor + run-level metadata
  inserted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_scs_ticker_scored
  ON uw_scan.scanner_candidate_snapshots (ticker, scored_at DESC);
CREATE INDEX IF NOT EXISTS ix_scs_section_scored
  ON uw_scan.scanner_candidate_snapshots (section, scored_at DESC);
CREATE INDEX IF NOT EXISTS ix_scs_run
  ON uw_scan.scanner_candidate_snapshots (run_id);
```

- [ ] **Step 2: Apply against a scratch DB and verify idempotency**

Run: `bash scripts/migrate.sh`
Expected: applies cleanly. Run it a **second** time — expected: no-op, no errors (every statement is `IF NOT EXISTS`).

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/storage/migrations/072_scanner_candidate_snapshots.sql
git commit -m "feat(scanner): migration 072 — scanner_candidate_snapshots table"
```

---

## Task 2: Snapshot persistence on `SignalsRepository`

**Files:**
- Modify: `src/uw_scan/storage/signals_repository.py`
- Test: `tests/integration/storage/test_scanner_candidate_snapshots.py`

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/storage/test_scanner_candidate_snapshots.py`:

```python
"""Integration tests for scanner_candidate_snapshots persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_insert_and_fetch_latest_discovery_snapshot(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    scored = datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc)

    sigs.insert_candidate_snapshots_bulk(
        run_id=run_id,
        section="discovery",
        rows=[
            {
                "ticker": "ZAAA",
                "scored_at": scored,
                "bias": "bullish",
                "direction": "long",
                "score": Decimal("78.500"),
                "score_model": "edge_quality_v1",
                "score_breakdown": {"dp_strength": 24.0, "sweeps": 15.0},
                "spot_at_signal": Decimal("5.20"),
                "is_type_f": None,
                "evidence": {"vol_oi": "2.4", "sweeps": 2},
            },
            {
                "ticker": "ZBBB",
                "scored_at": scored,
                "bias": "bearish",
                "direction": "short",
                "score": Decimal("55.000"),
                "score_model": "edge_quality_v1",
                "score_breakdown": {"dp_strength": 0.0},
                "spot_at_signal": Decimal("40.00"),
                "is_type_f": None,
                "evidence": {},
            },
        ],
    )
    sigs.upsert_discovery_run_meta(
        run_id, {"alerts_pulled": 180, "earnings_unknown_dropped": 12, "dp_enriched": 2}
    )
    repo.finish_scan_run(run_id, status="ok")  # fetch filters status='ok'
    repo.conn.commit()

    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["run_id"] == run_id
    assert snap["alerts_pulled"] == 180
    assert snap["earnings_unknown_dropped"] == 12
    # Ordered by score desc.
    assert [c["ticker"] for c in snap["candidates"]] == ["ZAAA", "ZBBB"]
    assert snap["candidates"][0]["score"] == Decimal("78.500")
    assert snap["candidates"][0]["score_breakdown"]["sweeps"] == 15.0


def test_run_meta_survives_zero_candidate_nonempty_feed(seeded_db_empty_cards):
    """A feed fully filtered to zero candidates still records run counts."""
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    sigs.upsert_discovery_run_meta(
        run_id, {"alerts_pulled": 200, "earnings_unknown_dropped": 200}
    )
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()

    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["candidates"] == []
    assert snap["alerts_pulled"] == 200
    assert snap["earnings_unknown_dropped"] == 200


def test_fetch_latest_discovery_snapshot_empty_run(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()

    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    assert snap["run_id"] == run_id
    assert snap["candidates"] == []
    assert snap["alerts_pulled"] == 0
    assert snap["earnings_unknown_dropped"] == 0


def test_fetch_latest_discovery_snapshot_none_when_no_runs(seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    assert sigs.fetch_latest_discovery_snapshot(limit=20) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/storage/test_scanner_candidate_snapshots.py -v`
Expected: FAIL with `AttributeError: 'SignalsRepository' object has no attribute 'insert_candidate_snapshots_bulk'`.

- [ ] **Step 3: Add the methods to `SignalsRepository`**

In `src/uw_scan/storage/signals_repository.py`, add `from datetime import datetime` to imports if missing, and insert these methods inside `class SignalsRepository` (after `upsert_gate`, before the Read API section):

```python
    def insert_candidate_snapshots_bulk(
        self,
        *,
        run_id: int | None,
        section: str,
        rows: list[dict[str, Any]],
    ) -> int:
        """Append candidate snapshots (markout-ready). One row per candidate.

        Each ``rows`` dict carries: ticker, scored_at, bias, direction, score,
        score_model, score_breakdown, spot_at_signal, is_type_f, evidence.
        Append-only (no upsert) — every run accrues a new batch so history is
        preserved for Phase-2 markout.
        """
        if not rows:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.scanner_candidate_snapshots
              (run_id, section, ticker, scored_at, bias, direction, score,
               score_model, score_breakdown, spot_at_signal, is_type_f, evidence)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = [
            (
                run_id,
                section,
                r["ticker"].upper(),
                r["scored_at"],
                r.get("bias"),
                r.get("direction"),
                r.get("score"),
                r["score_model"],
                Jsonb(r.get("score_breakdown")) if r.get("score_breakdown") is not None else None,
                r.get("spot_at_signal"),
                r.get("is_type_f"),
                Jsonb(r.get("evidence")) if r.get("evidence") is not None else None,
            )
            for r in rows
        ]
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        return len(rows)

    def upsert_discovery_run_meta(self, run_id: int, meta: dict[str, Any]) -> None:
        """Store discovery run-level counts on the scan_runs row, namespaced under
        the ``discovery`` key of the existing ``aggregates`` JSONB.

        Persisted independently of candidate rows so a non-empty feed filtered to
        zero candidates still records alerts_pulled / earnings_unknown_dropped.
        The ``_DISCOVER`` sentinel ticker guarantees no collision with the
        real-ticker MarketAggregates readers (health / watchlist), which filter
        by real ticker + status.
        """
        sql = f"""
            UPDATE {self._schema}.scan_runs
            SET aggregates = COALESCE(aggregates, '{{}}'::jsonb)
                             || jsonb_build_object('discovery', %s::jsonb)
            WHERE run_id = %s
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, (Jsonb(meta), run_id))

    def fetch_latest_discovery_snapshot(
        self, limit: int = 20
    ) -> dict[str, Any] | None:
        """Latest discovery run + its top-N candidate snapshots by score.

        Returns ``None`` if no discovery run has ever completed. Run-level counts
        come from ``scan_runs.aggregates->'discovery'`` (set by
        ``upsert_discovery_run_meta``), so they resolve even for empty / fully
        filtered runs. Run identity/timestamp come from the ``scan_runs`` row.
        """
        run_sql = f"""
            SELECT run_id, finished_at, aggregates
            FROM {self._schema}.scan_runs
            WHERE notes = 'discovery_scan' AND status = 'ok'
            ORDER BY finished_at DESC NULLS LAST, run_id DESC
            LIMIT 1
        """
        with self._conn.cursor() as cur:
            cur.execute(run_sql)
            run = cur.fetchone()
        if run is None:
            return None
        run_id, finished_at, aggregates = run[0], run[1], run[2]
        run_meta: dict[str, Any] = (aggregates or {}).get("discovery") or {}

        rows_sql = f"""
            SELECT ticker, scored_at, bias, direction, score, score_model,
                   score_breakdown, spot_at_signal, evidence
            FROM {self._schema}.scanner_candidate_snapshots
            WHERE run_id = %s AND section = 'discovery'
            ORDER BY score DESC NULLS LAST, ticker ASC
            LIMIT %s
        """
        candidates = self._select_dicts(rows_sql, (run_id, limit))
        return {
            "run_id": run_id,
            "scored_at": finished_at,
            "alerts_pulled": int(run_meta.get("alerts_pulled", 0) or 0),
            "earnings_unknown_dropped": int(
                run_meta.get("earnings_unknown_dropped", 0) or 0
            ),
            "candidates": candidates,
        }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/storage/test_scanner_candidate_snapshots.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/signals_repository.py tests/integration/storage/test_scanner_candidate_snapshots.py
git commit -m "feat(scanner): scanner_candidate_snapshots write/read on SignalsRepository"
```

---

## Task 3: `edge_quality.py` — pure 5-factor scorer

**Files:**
- Create: `src/uw_scan/scanner/edge_quality.py`
- Test: `tests/unit/scanner/test_edge_quality.py`

Port of radon `scripts/discover.py` (`analyze_darkpool_day`, `calculate_score`, the options-bias / confluence logic, the per-ticker aggregation), using `Decimal` and reading argon's warm dark-pool window dicts.

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/scanner/test_edge_quality.py`:

```python
"""Unit tests for the edge-quality scorer (radon parity, premium-free)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from uw_scan.scanner import edge_quality as eq


def _dp_row(d: datetime, price, bid, ask, size=1000):
    return {
        "executed_at": d,
        "price": Decimal(str(price)),
        "nbbo_bid": Decimal(str(bid)),
        "nbbo_ask": Decimal(str(ask)),
        "size": size,
    }


def test_analyze_darkpool_day_accumulation():
    # All prints above mid → buy-heavy → ACCUMULATION.
    trades = [_dp_row(None, 10.0, 9.0, 9.5) for _ in range(5)]
    out = eq.analyze_darkpool_day(trades)
    assert out["direction"] == "ACCUMULATION"
    assert out["strength"] == Decimal("100.0")  # ratio 1.0 → (1.0-0.5)*200=100


def test_analyze_darkpool_day_distribution():
    trades = [_dp_row(None, 8.5, 9.0, 10.0) for _ in range(5)]  # below mid (9.5)
    out = eq.analyze_darkpool_day(trades)
    assert out["direction"] == "DISTRIBUTION"


def test_analyze_darkpool_day_no_data():
    assert eq.analyze_darkpool_day([])["direction"] == "NO_DATA"


def test_directional_darkpool_sustained_counts_consecutive_days():
    d1 = datetime(2026, 6, 15, 14, tzinfo=timezone.utc)
    d2 = datetime(2026, 6, 12, 14, tzinfo=timezone.utc)
    d3 = datetime(2026, 6, 11, 14, tzinfo=timezone.utc)
    window = (
        [_dp_row(d1, 10.0, 9.0, 9.5)]   # ACC
        + [_dp_row(d2, 10.0, 9.0, 9.5)]  # ACC
        + [_dp_row(d3, 8.0, 9.0, 10.0)]  # DIST → breaks the streak
    )
    out = eq.directional_darkpool(window)
    assert out["sustained_days"] == 2
    assert out["aggregate"]["direction"] == "ACCUMULATION"


def test_directional_darkpool_dedups_repeated_tracking_ids():
    d1 = datetime(2026, 6, 15, 14, tzinfo=timezone.utc)
    row = {**_dp_row(d1, 10.0, 9.0, 9.5, size=1000), "tracking_id": 42}
    out = eq.directional_darkpool([row, dict(row), dict(row)])  # same tid x3
    assert out["aggregate"]["prints"] == 1  # counted once, not 3
    assert out["total_prints"] == 1


def test_calculate_score_excludes_premium():
    # Two candidates identical except premium: score must be equal.
    kwargs = dict(
        dp_strength=Decimal("60"),
        dp_sustained=2,
        has_confluence=True,
        vol_oi_ratio=Decimal("2.0"),
        sweep_count=2,
    )
    a = eq.calculate_score(**kwargs)
    assert a["total"] == pytest.approx(0)  # placeholder; replaced below
```

Replace the last test body with an explicit expected value derived from the weights (DP strength 30, sustained 20, confluence 20, vol/OI 15, sweeps 15):

```python
def test_calculate_score_excludes_premium():
    out = eq.calculate_score(
        dp_strength=Decimal("60"),
        dp_sustained=2,         # → 40 capped→ min(40,100)=40
        has_confluence=True,    # → 100
        vol_oi_ratio=Decimal("2.0"),  # → 50
        sweep_count=2,          # → 100
    )
    # weighted: 60*.30 + 40*.20 + 100*.20 + 50*.15 + 100*.15
    #         = 18 + 8 + 20 + 7.5 + 15 = 68.5
    assert out["total"] == Decimal("68.5")
    assert "premium" not in out["weighted"]
    assert "premium" not in out["components"]


def test_options_bias_and_confluence():
    assert eq.options_bias(calls=4, puts=1) == "bullish"
    assert eq.options_bias(calls=1, puts=4) == "bearish"
    assert eq.options_bias(calls=2, puts=2) == "mixed"
    assert eq.has_confluence("bullish", "ACCUMULATION") is True
    assert eq.has_confluence("bearish", "DISTRIBUTION") is True
    assert eq.has_confluence("bullish", "DISTRIBUTION") is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/scanner/test_edge_quality.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.scanner.edge_quality'`.

- [ ] **Step 3: Implement `edge_quality.py`**

Create `src/uw_scan/scanner/edge_quality.py`:

```python
"""Edge-quality scorer for scanner discovery (radon parity, premium-free).

Ports radon ``scripts/discover.py`` (analyze_darkpool_day / calculate_score /
options-bias / confluence) to Decimal arithmetic. Premium is a FILTER applied
upstream in the job — it is NEVER an input to this score.

The directional dark-pool helper here is distinct from
``signals/dark_pool_accumulation.py`` (which clusters prints near spot and is
direction-neutral). This one classifies each print buy/sell by
``price >= midpoint(nbbo_bid, nbbo_ask)`` and aggregates per day, matching
radon's accumulation/distribution model.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, Literal

Bias = Literal["bullish", "bearish", "neutral", "mixed"]
DpDirection = Literal["ACCUMULATION", "DISTRIBUTION", "NEUTRAL", "NO_DATA"]

# Must sum to 100. Mirrors radon WEIGHTS. The job overrides these from config.
DEFAULT_WEIGHTS: dict[str, Decimal] = {
    "dp_strength": Decimal("30"),
    "dp_sustained": Decimal("20"),
    "confluence": Decimal("20"),
    "vol_oi": Decimal("15"),
    "sweeps": Decimal("15"),
}

_ACC = Decimal("0.55")
_DIST = Decimal("0.45")
_HALF = Decimal("0.5")
_HUNDRED = Decimal("100")


def _mid(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / Decimal("2")


def analyze_darkpool_day(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Buy/sell split for a set of dark-pool prints (radon analyze_darkpool_day)."""
    trades = list(trades)
    if not trades:
        return {"buy_ratio": None, "direction": "NO_DATA", "strength": Decimal("0"), "prints": 0}

    buy_vol = Decimal("0")
    sell_vol = Decimal("0")
    for t in trades:
        size = Decimal(str(t.get("size") or 0))
        price = t.get("price")
        mid = _mid(t.get("nbbo_bid"), t.get("nbbo_ask"))
        if price is None or mid is None:
            continue
        if Decimal(str(price)) >= mid:
            buy_vol += size
        else:
            sell_vol += size

    total = buy_vol + sell_vol
    if total <= 0:
        return {"buy_ratio": None, "direction": "NO_DATA", "strength": Decimal("0"), "prints": len(trades)}

    ratio = buy_vol / total
    if ratio >= _ACC:
        direction: DpDirection = "ACCUMULATION"
        strength = (ratio - _HALF) * Decimal("200")
    elif ratio <= _DIST:
        direction = "DISTRIBUTION"
        strength = (_HALF - ratio) * Decimal("200")
    else:
        direction = "NEUTRAL"
        strength = Decimal("0")

    return {
        "buy_ratio": ratio,
        "direction": direction,
        "strength": min(strength, _HUNDRED),
        "prints": len(trades),
    }


def directional_darkpool(window: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate + sustained-direction analysis over a warm dark-pool window.

    ``window`` rows are SignalsRepository.fetch_dark_pool_window dicts
    (executed_at, price, size, nbbo_bid, nbbo_ask). Groups by execution date,
    counts consecutive most-recent days sharing the aggregate direction.
    """
    window = list(window)
    # Dedup by tracking_id. The warm table stores the SAME print under a new
    # run_id on every discovery tick (insert_dark_pool_rows conflicts on
    # (run_id, tracking_id), not tracking_id alone) and fetch_dark_pool_window
    # does NOT dedup — so today's prints would otherwise be counted ~N times
    # across the day, inflating buy/sell volume and DP strength. (Pre-existing
    # latent issue in the watchlist accumulation path; we fix it here for the
    # directional model.)
    seen_tids: set = set()
    deduped: list[dict[str, Any]] = []
    for row in window:
        tid = row.get("tracking_id")
        if tid is not None and tid in seen_tids:
            continue
        if tid is not None:
            seen_tids.add(tid)
        deduped.append(row)
    window = deduped
    aggregate = analyze_darkpool_day(window)

    by_day: dict[Any, list[dict[str, Any]]] = {}
    for row in window:
        ts = row.get("executed_at")
        if ts is None:
            continue  # rows without a timestamp can't be day-grouped/sustained
        day = ts.date() if hasattr(ts, "date") else ts
        by_day.setdefault(day, []).append(row)

    # Most-recent day first. Keys are all real dates now, so sorting is safe
    # (a None key here would raise TypeError comparing None to date).
    daily = [
        {"date": day, **analyze_darkpool_day(rows)}
        for day, rows in sorted(by_day.items(), key=lambda kv: kv[0], reverse=True)
    ]

    sustained = 0
    if daily:
        first_dir = daily[0]["direction"]
        if first_dir in ("ACCUMULATION", "DISTRIBUTION"):
            sustained = 1
            for d in daily[1:]:
                if d["direction"] == first_dir:
                    sustained += 1
                else:
                    break

    return {
        "aggregate": aggregate,
        "daily": daily,
        "sustained_days": sustained,
        "total_prints": sum(d["prints"] for d in daily),
    }


def options_bias(*, calls: int, puts: int) -> Bias:
    if calls > puts * 1.5:
        return "bullish"
    if puts > calls * 1.5:
        return "bearish"
    return "mixed"


def has_confluence(bias: Bias, dp_direction: str | None) -> bool:
    return (bias == "bullish" and dp_direction == "ACCUMULATION") or (
        bias == "bearish" and dp_direction == "DISTRIBUTION"
    )


def _vol_oi_score(ratio: Decimal) -> Decimal:
    if ratio <= Decimal("1.0"):
        return Decimal("0")
    if ratio <= Decimal("2.0"):
        return (ratio - Decimal("1.0")) * Decimal("50")
    if ratio <= Decimal("4.0"):
        return Decimal("50") + (ratio - Decimal("2.0")) * Decimal("25")
    return _HUNDRED


def _sweep_score(count: int) -> Decimal:
    if count <= 0:
        return Decimal("0")
    if count == 1:
        return Decimal("50")
    return _HUNDRED


def calculate_score(
    *,
    dp_strength: Decimal,
    dp_sustained: int,
    has_confluence: bool,
    vol_oi_ratio: Decimal,
    sweep_count: int,
    weights: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    """Normalized 0–100 edge-quality score. Premium is intentionally absent."""
    w = weights or DEFAULT_WEIGHTS
    components = {
        "dp_strength": min(dp_strength, _HUNDRED),
        "dp_sustained": min(Decimal(dp_sustained) * Decimal("20"), _HUNDRED),
        "confluence": _HUNDRED if has_confluence else Decimal("0"),
        "vol_oi": _vol_oi_score(vol_oi_ratio),
        "sweeps": _sweep_score(sweep_count),
    }
    weighted = {k: (components[k] * w[k] / _HUNDRED) for k in components}
    total = sum(weighted.values(), Decimal("0"))
    return {
        "total": total,
        "components": components,
        "weighted": weighted,
    }
```

- [ ] **Step 4: Run the unit tests to verify they pass**

Run: `uv run pytest tests/unit/scanner/test_edge_quality.py -v`
Expected: all passed. (Delete the placeholder first body from Step 1 — only the explicit `test_calculate_score_excludes_premium` version remains.)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/scanner/edge_quality.py tests/unit/scanner/test_edge_quality.py
git commit -m "feat(scanner): edge_quality 5-factor scorer (radon parity, premium-free)"
```

---

## Task 4: Config knobs + weight-sum validator

**Files:**
- Modify: `src/uw_scan/config.py`
- Test: `tests/unit/test_config_edge_quality_weights.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_config_edge_quality_weights.py`:

```python
"""Edge-quality weights must sum to 100 (radon WEIGHTS assert parity)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from uw_scan.config import Settings


def test_default_edge_quality_weights_sum_to_100():
    s = Settings.from_env()
    total = (
        s.scanner_edge_quality_weight_dp_strength
        + s.scanner_edge_quality_weight_dp_sustained
        + s.scanner_edge_quality_weight_confluence
        + s.scanner_edge_quality_weight_vol_oi
        + s.scanner_edge_quality_weight_sweeps
    )
    assert total == Decimal("100")


def test_edge_quality_weights_validator_rejects_non_100(monkeypatch):
    monkeypatch.setenv("SCANNER_EDGE_QUALITY_WEIGHT_SWEEPS", "99")
    with pytest.raises(ValueError, match="edge-quality weights"):
        Settings.from_env()


def test_edge_quality_weight_map_helper():
    s = Settings.from_env()
    w = s.scanner_edge_quality_weights()
    assert set(w) == {"dp_strength", "dp_sustained", "confluence", "vol_oi", "sweeps"}
    assert sum(w.values()) == Decimal("100")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_config_edge_quality_weights.py -v`
Expected: FAIL (`AttributeError` for the new fields).

- [ ] **Step 3: Add the knobs + validator + helper to `config.py`**

In `src/uw_scan/config.py`, in `class Settings` after the existing scanner block (after `scanner_earnings_window_days: int = 14`, ~line 228), add:

```python
    # Discovery edge-quality scoring (radon parity). Weights must sum to 100.
    scanner_edge_quality_weight_dp_strength: Decimal = Decimal("30")
    scanner_edge_quality_weight_dp_sustained: Decimal = Decimal("20")
    scanner_edge_quality_weight_confluence: Decimal = Decimal("20")
    scanner_edge_quality_weight_vol_oi: Decimal = Decimal("15")
    scanner_edge_quality_weight_sweeps: Decimal = Decimal("15")
    scanner_discover_dp_top_n: int = 50
    scanner_discover_dp_lookback_days: int = 3
    scanner_discover_dp_sleep_ms: int = 0  # optional inter-DP-fetch throttle (rate guard)
    scanner_discover_alerts_limit: int = 200
    scanner_discover_scan_enabled: bool = True
    # Offset off the top-of-hour so discovery doesn't contend with full_scan
    # (cron `0 5-16`). Covers ~09:15–16:45 ET (RTH + post-close settle).
    scanner_discover_scan_cron: str = "15,45 9-16 * * 0-4"
```

Add a helper method on `Settings` (near other small helpers in the class):

```python
    def scanner_edge_quality_weights(self) -> dict[str, Decimal]:
        return {
            "dp_strength": self.scanner_edge_quality_weight_dp_strength,
            "dp_sustained": self.scanner_edge_quality_weight_dp_sustained,
            "confluence": self.scanner_edge_quality_weight_confluence,
            "vol_oi": self.scanner_edge_quality_weight_vol_oi,
            "sweeps": self.scanner_edge_quality_weight_sweeps,
        }
```

In the `from_env` classmethod (the `os.environ.get` block ~line 489, alongside the other `scanner_*` lines), add:

```python
            scanner_edge_quality_weight_dp_strength=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_DP_STRENGTH", "30")
            ),
            scanner_edge_quality_weight_dp_sustained=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_DP_SUSTAINED", "20")
            ),
            scanner_edge_quality_weight_confluence=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_CONFLUENCE", "20")
            ),
            scanner_edge_quality_weight_vol_oi=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_VOL_OI", "15")
            ),
            scanner_edge_quality_weight_sweeps=Decimal(
                os.environ.get("SCANNER_EDGE_QUALITY_WEIGHT_SWEEPS", "15")
            ),
            scanner_discover_dp_top_n=int(
                os.environ.get("SCANNER_DISCOVER_DP_TOP_N", "50")
            ),
            scanner_discover_dp_lookback_days=int(
                os.environ.get("SCANNER_DISCOVER_DP_LOOKBACK_DAYS", "3")
            ),
            scanner_discover_dp_sleep_ms=int(
                os.environ.get("SCANNER_DISCOVER_DP_SLEEP_MS", "0")
            ),
            scanner_discover_alerts_limit=int(
                os.environ.get("SCANNER_DISCOVER_ALERTS_LIMIT", "200")
            ),
            scanner_discover_scan_enabled=os.environ.get(
                "SCANNER_DISCOVER_SCAN_ENABLED", "true"
            ).lower()
            in ("1", "true", "yes"),
            scanner_discover_scan_cron=os.environ.get(
                "SCANNER_DISCOVER_SCAN_CRON", "15,45 9-16 * * 0-4"
            ),
```

Add a Pydantic v2 model validator on `Settings` (the class uses `BaseModel`; add a `@model_validator(mode="after")`). Ensure `from pydantic import BaseModel, model_validator` at the top of the file (add `model_validator` to the existing import):

```python
    @model_validator(mode="after")
    def _check_edge_quality_weights(self) -> "Settings":
        total = (
            self.scanner_edge_quality_weight_dp_strength
            + self.scanner_edge_quality_weight_dp_sustained
            + self.scanner_edge_quality_weight_confluence
            + self.scanner_edge_quality_weight_vol_oi
            + self.scanner_edge_quality_weight_sweeps
        )
        if total != Decimal("100"):
            raise ValueError(
                f"scanner edge-quality weights must sum to 100, got {total}"
            )
        return self
```

> Note: confirm whether `Settings` already defines a `@model_validator`. If so, fold the weight check into the existing one rather than adding a second. The `_enforce_db_isolation` call lives in `from_env`, not a validator, so there is no conflict there.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/unit/test_config_edge_quality_weights.py -v`
Expected: 3 passed.

- [ ] **Step 5: Run the broader config + scanner tests for regressions**

Run: `uv run pytest tests/unit -k "config or scanner" -q`
Expected: green (no existing config test breaks from the new validator).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py tests/unit/test_config_edge_quality_weights.py
git commit -m "feat(scanner): edge-quality config knobs + weight-sum validator"
```

---

## Task 5: `discovery_scan.py` job

**Files:**
- Create: `src/uw_scan/worker/jobs/discovery_scan.py`
- Test: `tests/integration/worker/test_discovery_scan_job.py`

The job: pull market-wide alerts → group by ticker (drop watchlist + unknown-earnings + known-earnings-in-window) → filter alerts by `min_premium` (filter only) → aggregate flow factors → Stage-1 flow-only rank → cap to top-N (log truncation) → Stage-2 sequential DP enrichment (fetch today + read warm window) → full 5-factor score → persist snapshots + DP prints + scan_run.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/worker/test_discovery_scan_job.py`:

```python
"""End-to-end discovery_scan job with fake UW client + DP fixtures."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import DarkPoolPrint, FlowAlert
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository
from uw_scan.worker.jobs.discovery_scan import discovery_scan_once


class _FakeUw:
    """Stands in for UwClient — the job only passes it through to fetchers."""


def _alert(ticker, opt_type, premium, *, sweep=False, vol=2000, oi=500):
    return FlowAlert(
        id=f"{ticker}-{opt_type}-{premium}",
        ticker=ticker,
        type=opt_type,
        total_premium=Decimal(str(premium)),
        total_ask_side_prem=Decimal(str(premium)) * Decimal("0.9"),
        total_bid_side_prem=Decimal(str(premium)) * Decimal("0.1"),
        volume=vol,
        open_interest=oi,
        volume_oi_ratio=Decimal(str(vol)) / Decimal(str(oi)),
        has_sweep=sweep,
        underlying_price=Decimal("10.00"),
        next_earnings_date=date(2026, 12, 31),
        sector="Technology",
        created_at=datetime(2026, 6, 15, 14, 0, tzinfo=timezone.utc),
    )


def test_discovery_scan_persists_snapshots_and_dp(seeded_db_empty_cards, monkeypatch):
    repo: Repository = seeded_db_empty_cards
    from uw_scan.config import Settings

    settings = Settings.from_env()

    # Synthetic tickers guaranteed absent from the seeded watchlist (CRWV/WULF
    # etc. may be seeded → they'd be excluded before scoring).
    alerts = [
        _alert("ZAAA", "call", 300000, sweep=True),
        _alert("ZAAA", "call", 250000, sweep=True),
        _alert("ZBBB", "put", 200000),
    ]

    def fake_market_alerts(client, r, run_id, limit=200):
        return alerts

    def fake_darkpool(client, r, run_id, ticker):
        # Buy-heavy prints (price above mid) → ACCUMULATION.
        return [
            DarkPoolPrint(
                ticker=ticker,
                tracking_id=hash((ticker, i)) % 1_000_000,
                executed_at=datetime(2026, 6, 15, 13, i, tzinfo=timezone.utc),
                price=Decimal("10.00"),
                size=5000,
                premium=Decimal("50000"),
                nbbo_bid=Decimal("9.50"),
                nbbo_ask=Decimal("9.90"),
                canceled=False,
            )
            for i in range(3)
        ]

    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_market_flow_alerts",
        fake_market_alerts,
    )
    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_darkpool_ticker", fake_darkpool
    )

    summary = discovery_scan_once(repo=repo, client=_FakeUw(), settings=settings)
    repo.conn.commit()

    assert summary["status"] == "ok"
    assert summary["candidates_found"] >= 1

    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    tickers = {c["ticker"] for c in snap["candidates"]}
    assert "ZAAA" in tickers
    # ZAAA should outrank ZBBB (sweeps + confluence).
    assert snap["candidates"][0]["ticker"] == "ZAAA"
    assert snap["candidates"][0]["score_model"] == "edge_quality_v1"
    assert snap["alerts_pulled"] == 3  # from scan_runs.aggregates run-meta

    # DP prints landed in the warm table for reuse.
    zaaa_dp = sigs.fetch_dark_pool_window("ZAAA", lookback_days=5)
    assert len(zaaa_dp) == 3


def test_discovery_scan_degrades_when_dp_fetch_fails(seeded_db_empty_cards, monkeypatch):
    repo: Repository = seeded_db_empty_cards
    from uw_scan.config import Settings

    settings = Settings.from_env()

    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_market_flow_alerts",
        lambda c, r, run_id, limit=200: [_alert("ZAAA", "call", 300000, sweep=True)],
    )

    def boom(client, r, run_id, ticker):
        raise RuntimeError("UW darkpool 500")

    monkeypatch.setattr(
        "uw_scan.worker.jobs.discovery_scan.fetch_darkpool_ticker", boom
    )

    summary = discovery_scan_once(repo=repo, client=_FakeUw(), settings=settings)
    repo.conn.commit()
    assert summary["status"] == "ok"

    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    snap = sigs.fetch_latest_discovery_snapshot(limit=20)
    # Still scored on flow factors; DP marked degraded; DP factors zeroed.
    cand = next(c for c in snap["candidates"] if c["ticker"] == "ZAAA")
    assert cand["evidence"]["dp_status"] == "degraded"
    assert cand["evidence"]["dp_direction"] == "NO_DATA"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/worker/test_discovery_scan_job.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'uw_scan.worker.jobs.discovery_scan'`.

- [ ] **Step 3: Implement the job**

> Transaction model (verified): `repo.insert_scan_run` and `repo.finish_scan_run` each `commit()` internally. So the `scan_runs` row is durable the moment it's created (an unfinished row survives a later crash — correct, failures stay visible), and `finish_scan_run` flushes the snapshot inserts that precede it. The trailing `repo.conn.commit()` is therefore belt-and-suspenders. The per-ticker savepoint (below) keeps one bad DP fetch from poisoning the connection or discarding other tickers' cached prints. **Verified for the savepoint:** `_fetch_json`, `_persist_audit` (sources/uw.py), and `insert_dark_pool_rows` (storage/options.py) do **not** `commit()` internally — required, else `with repo.conn.transaction()` would conflict. Re-confirm if those change.

> Worker env caveat: the new `scanner_discover_*` knobs are read at fork time; rotating them (or the cron) requires restarting the primary-uw worker. The execution/e2e step restarts the worker so the new cron + job register.

> Filter divergence (intentional, radon parity): the new model is **radon-style** — the ONLY hard filters are **premium** (`scanner_discover_min_premium_usd`) and **earnings** (unknown-dropped + in-window-excluded). It deliberately does **not** apply the DCF per-alert conviction gates (`volume > open_interest`, ask-side ratio, multileg rejection, moneyness, min-DTE) that the old `discover_from_alerts` used — those are conviction filters; radon's Discover surfaces edge candidates and lets the 5-factor score + the top-N cap rank them. `scanner_discover_min_ask_side` is still referenced by the retained-but-unwired `discover_from_alerts`, so it is not dead config; it simply does not gate the new job. Ask-side intent is captured by the score's vol/OI + sweeps + DP-direction factors. Call this out in the PR body.

Create `src/uw_scan/worker/jobs/discovery_scan.py`:

```python
"""Scheduled market-wide discovery scan (Approach A).

Pulls market-wide flow alerts, scores non-watchlist tickers with the
edge_quality 5-factor model (premium is a filter, never a score input), enriches
the top-N with live dark-pool data (cached into dark_pool_events for reuse), and
persists candidate snapshots + a scan_runs row (notes='discovery_scan'). The
/api/scanner/discover endpoint reads the latest snapshot — no inline compute.

Single-flight via pg_try_advisory_lock; Stage-2 DP fetches are sequential
(shared psycopg connection is not thread-safe; the top-N cap bounds latency).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.models import FlowAlert
from uw_scan.scanner import edge_quality as eq
from uw_scan.sources.uw import fetch_darkpool_ticker, fetch_market_flow_alerts
from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository

logger = logging.getLogger(__name__)

DISCOVERY_SCAN_LOCK = 92401  # single-flight; distinct from 91501/91601/92201
_INDEX_SYMBOLS = {"SPX", "SPXW", "NDX", "RUT", "VIX", "DJX", "OEX", "XSP"}


def _group_alerts(
    alerts: list[FlowAlert],
    *,
    watchlist: set[str],
    today,
    min_premium: Decimal,
    earnings_window_days: int,
) -> tuple[dict[str, list[FlowAlert]], int]:
    """Group non-watchlist alerts by ticker. Drop unknown earnings + in-window
    earnings (discovery.py:77-79 parity). Premium is a per-alert FILTER."""
    by_ticker: dict[str, list[FlowAlert]] = defaultdict(list)
    earnings_unknown_dropped = 0
    for a in alerts:
        if not a.ticker:
            continue
        ticker = a.ticker.upper()
        if ticker in watchlist or ticker in _INDEX_SYMBOLS:
            continue
        if a.next_earnings_date is None:
            earnings_unknown_dropped += 1
            continue
        if (a.next_earnings_date - today).days <= earnings_window_days:
            continue
        if a.total_premium is None or a.total_premium < min_premium:
            continue
        by_ticker[ticker].append(a)
    return dict(by_ticker), earnings_unknown_dropped


def _aggregate_flow(group: list[FlowAlert]) -> dict:
    calls = sum(1 for a in group if (a.type or "").lower() == "call")
    puts = sum(1 for a in group if (a.type or "").lower() == "put")
    sweeps = sum(1 for a in group if a.has_sweep)
    vol_ois = [a.volume_oi_ratio for a in group if a.volume_oi_ratio and a.volume_oi_ratio > 0]
    avg_vol_oi = (sum(vol_ois, Decimal("0")) / Decimal(len(vol_ois))) if vol_ois else Decimal("0")
    underlying = next((a.underlying_price for a in group if a.underlying_price), None)
    sector = next((a.sector for a in group if a.sector), None)
    latest = max((a.created_at for a in group if a.created_at), default=None)
    return {
        "alert_count": len(group),
        "calls": calls,
        "puts": puts,
        "sweeps": sweeps,
        "avg_vol_oi": avg_vol_oi,
        "underlying_price": underlying,
        "sector": sector,
        "latest_alert_at": latest,
    }


def _stage1_score(agg: dict, weights: dict[str, Decimal]) -> Decimal:
    """Flow-only sub-score for ranking before DP enrichment (vol/OI + sweeps)."""
    partial = eq.calculate_score(
        dp_strength=Decimal("0"),
        dp_sustained=0,
        has_confluence=False,
        vol_oi_ratio=agg["avg_vol_oi"],
        sweep_count=agg["sweeps"],
        weights=weights,
    )
    return partial["total"]


def discovery_scan_once(
    *, repo: Repository, client: UwClient, settings: Settings, now: datetime | None = None
) -> dict:
    """One discovery scan. Returns a summary dict."""
    if not repo.try_advisory_lock(DISCOVERY_SCAN_LOCK):
        logger.info("discovery_scan: lock held; skipping this tick")
        return {"status": "skipped_locked"}

    sigs = SignalsRepository(repo.conn, schema=settings.db_schema)
    weights = settings.scanner_edge_quality_weights()
    now = now or datetime.now(timezone.utc)
    today = datetime.now(ZoneInfo(settings.rth_tz)).date()
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")

    try:
        try:
            alerts = fetch_market_flow_alerts(
                client, repo, run_id, limit=settings.scanner_discover_alerts_limit
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("discovery_scan: alerts fetch failed: %r", exc)
            repo.conn.rollback()
            repo.finish_scan_run(run_id, status="fail")
            repo.conn.commit()
            return {"status": "fetch_failed"}

        watchlist = {r.ticker.upper() for r in repo.list_active_watchlist()}
        by_ticker, earnings_dropped = _group_alerts(
            alerts,
            watchlist=watchlist,
            today=today,
            min_premium=settings.scanner_discover_min_premium_usd,
            earnings_window_days=settings.scanner_earnings_window_days,
        )

        aggs = {t: _aggregate_flow(g) for t, g in by_ticker.items()}
        ranked = sorted(
            aggs.items(),
            key=lambda kv: (-_stage1_score(kv[1], weights), kv[0]),
        )
        top_n = settings.scanner_discover_dp_top_n
        dp_truncated = max(0, len(ranked) - top_n)
        if dp_truncated:
            logger.info(
                "discovery_scan: %d candidates exceed top_n=%d; %d dropped from DP enrichment",
                len(ranked),
                top_n,
                dp_truncated,
            )
        ranked = ranked[:top_n]

        run_meta = {
            "alerts_pulled": len(alerts),
            "earnings_unknown_dropped": earnings_dropped,
            "candidates_found": len(ranked),
            "dp_truncated_dropped": dp_truncated,
        }

        snapshot_rows: list[dict] = []
        dp_enriched = 0
        for idx, (ticker, agg) in enumerate(ranked):
            if idx > 0 and settings.scanner_discover_dp_sleep_ms > 0:
                # Rate guard: space out DP fetches so a 50-ticker run can't
                # burst UW alongside the watchlist full_scan. Default 0 (off);
                # raise it if discovery 429s. Combined with the cron offset
                # (:15/:45, off the top-of-hour full_scan) + the top-N cap, this
                # is the spec's "concurrency cap + rate guard" — concurrency is
                # trivially 1 here (sequential).
                time.sleep(settings.scanner_discover_dp_sleep_ms / 1000.0)

            dp_status = "ok"
            try:
                # Savepoint per ticker: a failed DP fetch rolls back ONLY this
                # ticker's audit/print writes, never the scan_run row or prior
                # tickers' cached prints. A bare repo.conn.rollback() here would
                # nuke the whole run's accumulated work. psycopg3
                # conn.transaction() opens a SAVEPOINT when a tx is already
                # active, else a transaction it commits on clean exit.
                with repo.conn.transaction():
                    prints = fetch_darkpool_ticker(client, repo, run_id, ticker)
                    if prints:
                        repo.insert_dark_pool_rows(run_id, prints)
                dp_enriched += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("discovery_scan: DP fetch failed for %s: %r", ticker, exc)
                dp_status = "degraded"

            # Graceful degrade: when TODAY's DP fetch failed, score on the flow
            # factors only — do NOT fall back to stale warm DP (spec error
            # handling). Otherwise read the deduped warm window.
            dp_window_price = None
            if dp_status == "degraded":
                dp = {
                    "aggregate": {"direction": "NO_DATA", "strength": Decimal("0"), "buy_ratio": None},
                    "sustained_days": 0,
                    "total_prints": 0,
                }
            else:
                window = sigs.fetch_dark_pool_window(
                    ticker, lookback_days=settings.scanner_discover_dp_lookback_days
                )
                dp = eq.directional_darkpool(window)
                if window:
                    dp_window_price = window[0].get("price")
                if dp["aggregate"]["direction"] == "NO_DATA":
                    dp_status = "no_data"
            dp_agg = dp["aggregate"]

            bias = eq.options_bias(calls=agg["calls"], puts=agg["puts"])
            confl = eq.has_confluence(bias, dp_agg["direction"])
            score = eq.calculate_score(
                dp_strength=dp_agg["strength"],
                dp_sustained=dp["sustained_days"],
                has_confluence=confl,
                vol_oi_ratio=agg["avg_vol_oi"],
                sweep_count=agg["sweeps"],
                weights=weights,
            )
            direction = "long" if bias == "bullish" else "short" if bias == "bearish" else None
            spot = agg["underlying_price"] if agg["underlying_price"] is not None else dp_window_price

            snapshot_rows.append(
                {
                    "ticker": ticker,
                    "scored_at": now,
                    "bias": bias,
                    "direction": direction,
                    "score": score["total"],
                    "score_model": "edge_quality_v1",
                    "score_breakdown": {k: float(v) for k, v in score["weighted"].items()},
                    "spot_at_signal": spot,
                    "is_type_f": None,
                    "evidence": {
                        "alert_count": agg["alert_count"],
                        "calls": agg["calls"],
                        "puts": agg["puts"],
                        "sweeps": agg["sweeps"],
                        "vol_oi": str(agg["avg_vol_oi"]),
                        "dp_direction": dp_agg["direction"],
                        "dp_strength": str(dp_agg["strength"]),
                        "dp_sustained_days": dp["sustained_days"],
                        "confluence": confl,
                        "dp_status": dp_status,
                        "sector": agg["sector"],
                        "latest_alert_at": agg["latest_alert_at"].isoformat()
                        if agg["latest_alert_at"]
                        else None,
                    },
                }
            )

        # Run-level metadata persisted to the scan_runs row (NOT into candidate
        # evidence) so a non-empty feed fully filtered to zero candidates still
        # records alerts_pulled / earnings_unknown_dropped.
        run_meta["dp_enriched"] = dp_enriched
        sigs.upsert_discovery_run_meta(run_id, run_meta)
        sigs.insert_candidate_snapshots_bulk(
            run_id=run_id, section="discovery", rows=snapshot_rows
        )
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()
        logger.info(
            "discovery_scan: ok candidates=%d dp_enriched=%d alerts=%d dropped=%d",
            len(snapshot_rows),
            dp_enriched,
            len(alerts),
            earnings_dropped,
        )
        return {"status": "ok", **run_meta}
    except Exception as exc:  # noqa: BLE001
        logger.exception("discovery_scan failed: %r", exc)
        repo.conn.rollback()
        repo.finish_scan_run(run_id, status="fail")
        repo.conn.commit()
        return {"status": "error"}
    finally:
        repo.release_advisory_lock(DISCOVERY_SCAN_LOCK)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/worker/test_discovery_scan_job.py -v`
Expected: 2 passed.

> If the empty-feed path needs coverage, add a third test that monkeypatches `fetch_market_flow_alerts` to return `[]` and asserts `summary["status"] == "ok"` with `candidates_found == 0` and `fetch_latest_discovery_snapshot` returns a run with `candidates == []`.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/jobs/discovery_scan.py tests/integration/worker/test_discovery_scan_job.py
git commit -m "feat(scanner): discovery_scan job — edge-quality + live DP enrichment"
```

---

## Task 6: Scheduler registration

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py`

- [ ] **Step 1: Add the job runner function**

In `src/uw_scan/worker/scheduler.py`, inside `main()` near `_regime_grg_scan` (~line 603), add:

```python
    def _discovery_scan() -> None:
        # Market-wide discovery — UW-bound (flow alerts + per-ticker dark pool),
        # single-flight via advisory lock, primary-uw-only to avoid duplicate
        # UW spend across shards. Mirrors _regime_grg_scan's external-API bracket.
        from uw_scan.worker.jobs.discovery_scan import discovery_scan_once

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings, telemetry_recorder=recorder, job_name="discovery_scan"
            ) as uw:
                with _repo(settings) as repo:
                    try:
                        summary = discovery_scan_once(
                            repo=repo, client=uw, settings=settings
                        )
                        logger.info("discovery_scan_tick %s", summary)
                    except Exception as exc:  # noqa: BLE001
                        logger.exception("discovery_scan_failed err=%r", exc)
                        repo.conn.rollback()
```

- [ ] **Step 2: Register the cron**

In the `if "uw" in groups:` → `if _is_primary_worker(settings):` block (right after the `regime_grg_scan` `add_job`, ~line 822), add:

```python
            # Market-wide discovery scan — edge-quality candidates + DP enrichment.
            # Primary-uw-only; gated by the discovery kill switch.
            if settings.scanner_discover_scan_enabled:
                sched.add_job(
                    _discovery_scan,
                    CronTrigger.from_crontab(
                        settings.scanner_discover_scan_cron, timezone=settings.rth_tz
                    ),
                    id="discovery_scan",
                    name="Market-wide discovery scan (UW)",
                    max_instances=1,
                    coalesce=True,
                )
```

- [ ] **Step 3: Verify the scheduler imports + wiring compile**

Run: `uv run python -c "import uw_scan.worker.scheduler"`
Expected: no error (module imports cleanly).

- [ ] **Step 4: Confirm no scheduler test breaks**

Run: `uv run pytest tests -k "schedule or scheduler" -q`
Expected: green. (Verified: `schedule_expectations.py` is cron-timing helpers, not a job-id registry, and no test asserts the scheduled job-id set — no registry edit is needed.)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/scheduler.py
git commit -m "feat(scanner): register discovery_scan cron (:15/:45 RTH, primary-uw)"
```

---

## Task 7: API thin-read + enriched models

**Files:**
- Modify: `src/uw_scan/api/models/scanner.py`, `src/uw_scan/api/routers/scanner.py`
- Test: `tests/integration/api/test_scanner_discover.py`
- Regenerate: `tests/integration/api/openapi.snapshot.json`, `web/lib/types.ts`

- [ ] **Step 1: Replace the obsolete API test with the snapshot thin-read test**

The existing `tests/integration/api/test_scanner_discover.py` asserts the OLD live-fetch contract (stub UW client, `alerts_limit`, freshness cache, 502 on fetch failure, `source="market_wide_flow_alerts"`). The thin-read rewrite removes all of that, so those tests WILL fail. **Replace the entire contents** of `tests/integration/api/test_scanner_discover.py` with:

```python
"""GET /api/scanner/discover reads the latest persisted discovery snapshot."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository
from uw_scan.storage.signals_repository import SignalsRepository


def test_discover_reads_latest_snapshot(client, seeded_db_empty_cards):
    repo: Repository = seeded_db_empty_cards
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("_DISCOVER", notes="discovery_scan")
    sigs.insert_candidate_snapshots_bulk(
        run_id=run_id,
        section="discovery",
        rows=[
            {
                "ticker": "WULF",
                "scored_at": datetime(2026, 6, 15, 14, 30, tzinfo=timezone.utc),
                "bias": "bullish",
                "direction": "long",
                "score": Decimal("78.5"),
                "score_model": "edge_quality_v1",
                "score_breakdown": {"dp_strength": 24.0, "sweeps": 15.0},
                "spot_at_signal": Decimal("5.20"),
                "is_type_f": None,
                "evidence": {
                    "dp_direction": "ACCUMULATION",
                    "dp_strength": "80.0",
                    "dp_sustained_days": 2,
                    "confluence": True,
                    "vol_oi": "2.4",
                    "sweeps": 2,
                    "run": {"alerts_pulled": 180, "earnings_unknown_dropped": 5},
                },
            }
        ],
    )
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()

    resp = client.get("/api/scanner/discover?limit=20")
    assert resp.status_code == 200
    body = resp.json()
    assert body["alerts_pulled"] == 180
    assert body["earnings_unknown_dropped"] == 5
    assert len(body["candidates"]) == 1
    c = body["candidates"][0]
    assert c["ticker"] == "WULF"
    assert c["score_model"] == "edge_quality_v1"
    assert c["dp_direction"] == "ACCUMULATION"
    assert c["confluence"] is True
    assert c["sweeps"] == 2


def test_discover_empty_when_no_runs(client, seeded_db_empty_cards):
    resp = client.get("/api/scanner/discover")
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidates"] == []
    assert body["alerts_pulled"] == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/api/test_scanner_discover.py -v`
Expected: FAIL (response still has the old DCF `hit` shape / missing fields).

- [ ] **Step 3: Enrich the Pydantic models**

In `src/uw_scan/api/models/scanner.py`, **replace** the `DiscoveryCandidate` class (lines 73–86) with:

```python
class DiscoveryCandidate(BaseModel):
    """Non-watchlist ticker scored by the edge-quality model (premium-free).

    Replaces the prior DCF-only shape. Dark-pool direction/strength/sustained +
    options↔DP confluence are surfaced per card. EIC/GEX still need a deep scan
    (promote to the watchlist).
    """

    ticker: str
    bias: Literal["bullish", "bearish", "neutral", "mixed"]
    bias_strength: Literal["strong", "moderate", "weak"] | None = None
    direction: Literal["long", "short"] | None = None
    score: Decimal
    score_model: str
    score_breakdown: dict[str, Any] = {}
    dp_direction: (
        Literal["ACCUMULATION", "DISTRIBUTION", "NEUTRAL", "NO_DATA"] | None
    ) = None
    dp_strength: Decimal | None = None
    dp_sustained_days: int = 0
    confluence: bool = False
    vol_oi: Decimal | None = None
    sweeps: int = 0
    alert_count: int = 0
    spot: Decimal | None = None
    dp_status: str | None = None
    sector: str | None = None
    scored_at: datetime | None = None
    latest_alert_at: datetime | None = None
```

**Replace** `DiscoveryResponse` (lines 89–94) with:

```python
class DiscoveryResponse(BaseModel):
    candidates: list[DiscoveryCandidate]
    fetched_at: datetime
    scored_at: datetime | None = None
    source: Literal["scanner_candidate_snapshots"] = "scanner_candidate_snapshots"
    alerts_pulled: int
    earnings_unknown_dropped: int = 0
```

- [ ] **Step 4: Rewrite the `/discover` route as a thin read**

In `src/uw_scan/api/routers/scanner.py`:

Replace the entire `get_scanner_discover` function (lines 281–359), the `_recent_discover_payload` helper (lines 243–278), the `_build_discover_response` helper (lines 362–390), and `_DISCOVER_SENTINEL_TICKER` (line 240) with:

```python
def _coerce_decimal(v) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


@router.get("/discover", response_model=DiscoveryResponse)
def get_scanner_discover(
    limit: int = Query(20, ge=1, le=50),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> DiscoveryResponse:
    """Thin read of the latest persisted discovery snapshot (compute is the job)."""
    sigs = SignalsRepository(repo.conn, schema=settings.db_schema)
    snap = sigs.fetch_latest_discovery_snapshot(limit=limit)
    if snap is None:
        return DiscoveryResponse(
            candidates=[], fetched_at=_now_utc(), scored_at=None,
            alerts_pulled=0, earnings_unknown_dropped=0,
        )

    candidates: list[RespDiscoveryCandidate] = []
    for r in snap["candidates"]:
        ev = r.get("evidence") or {}
        latest = ev.get("latest_alert_at")
        candidates.append(
            RespDiscoveryCandidate(
                ticker=r["ticker"],
                bias=r.get("bias") or "neutral",
                bias_strength=None,
                direction=r.get("direction"),
                score=_coerce_decimal(r.get("score")) or Decimal("0"),
                score_model=r["score_model"],
                score_breakdown=r.get("score_breakdown") or {},
                dp_direction=ev.get("dp_direction"),
                dp_strength=_coerce_decimal(ev.get("dp_strength")),
                dp_sustained_days=int(ev.get("dp_sustained_days", 0) or 0),
                confluence=bool(ev.get("confluence", False)),
                vol_oi=_coerce_decimal(ev.get("vol_oi")),
                sweeps=int(ev.get("sweeps", 0) or 0),
                alert_count=int(ev.get("alert_count", 0) or 0),
                spot=_coerce_decimal(r.get("spot_at_signal")),
                dp_status=ev.get("dp_status"),
                sector=ev.get("sector"),
                scored_at=r.get("scored_at"),
                latest_alert_at=datetime.fromisoformat(latest) if latest else None,
            )
        )

    return DiscoveryResponse(
        candidates=candidates,
        fetched_at=_now_utc(),
        scored_at=snap["scored_at"],
        alerts_pulled=snap["alerts_pulled"],
        earnings_unknown_dropped=snap["earnings_unknown_dropped"],
    )
```

Update imports at the top of `scanner.py`: add `from uw_scan.storage.signals_repository import SignalsRepository` (already imported), and remove now-unused imports (`fetch_market_flow_alerts`, `normalize_flow_alerts`, `discover_from_alerts`, `get_uw_client`, `EndpointSlug`, `UwClient`) **only if** nothing else in the file uses them — grep first; `SignalsRepository` is already imported for `get_scanner`.

> Leave `src/uw_scan/scanner/discovery.py` (`discover_from_alerts`) in place — it is now unwired but its unit tests still pass. Note it as a follow-up cleanup in the PR body.

- [ ] **Step 5: Run the API test to verify it passes**

Run: `uv run pytest tests/integration/api/test_scanner_discover.py -v`
Expected: 2 passed.

- [ ] **Step 6: Regenerate the OpenAPI snapshot + run the contract test**

Run:
```bash
uv run python -c "from uw_scan.api.server import app; import json; from pathlib import Path; Path('tests/integration/api/openapi.snapshot.json').write_text(json.dumps(app.openapi(), indent=2, sort_keys=True))"
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```
Expected: snapshot regenerated, test green. (Verified: `src/uw_scan/api/server.py` exposes a module-level `app = create_app()` at line 61. The snapshot test compares parsed JSON, so formatting is irrelevant.)

- [ ] **Step 7: Regenerate web types**

Run: `cd web && npm run gen:types`
Expected: `web/lib/types.ts` updated with the new `DiscoveryCandidate` shape. (The web build in Task 8 will consume it.)

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/api/models/scanner.py src/uw_scan/api/routers/scanner.py tests/integration/api/test_scanner_discover.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(scanner): /discover thin-read of edge-quality snapshot + enriched model"
```

---

## Task 8: Web — DiscoveredCard breakdown + page header

**Files:**
- Modify: `web/components/scanner/DiscoveredCard.tsx`, `web/app/scanner/page.tsx`
- Replace: `web/tests/unit/discoveredCard.test.tsx` (exists — depends on the removed `hit` field; do NOT create a new case-only filename, which collides on macOS)

- [ ] **Step 1: Replace the failing vitest unit test**

The existing `web/tests/unit/discoveredCard.test.tsx` renders the old DCF `hit` shape and will fail to typecheck. **Replace its entire contents** with:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DiscoveredCard } from "@/components/scanner/DiscoveredCard";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const base = {
  ticker: "WULF",
  bias: "bullish" as const,
  bias_strength: null,
  direction: "long" as const,
  score: "78.5",
  score_model: "edge_quality_v1",
  score_breakdown: { dp_strength: 24.0, sweeps: 15.0 },
  dp_direction: "ACCUMULATION" as const,
  dp_strength: "80.0",
  dp_sustained_days: 2,
  confluence: true,
  vol_oi: "2.4",
  sweeps: 2,
  alert_count: 3,
  spot: "5.20",
  dp_status: "ok",
  sector: "Technology",
  scored_at: "2026-06-15T14:30:00Z",
  latest_alert_at: "2026-06-15T14:00:00Z",
};

describe("DiscoveredCard", () => {
  it("renders the edge-quality score and 5-factor breakdown", () => {
    render(<DiscoveredCard candidate={base} nowMs={Date.parse(base.scored_at)} />);
    expect(screen.getByText("WULF")).toBeInTheDocument();
    expect(screen.getByText("78.5")).toBeInTheDocument();
    expect(screen.getByText(/ACC/)).toBeInTheDocument();      // DP direction badge
    expect(screen.getByText(/80/)).toBeInTheDocument();       // DP strength (spec §196-198)
    expect(screen.getByText(/2d/)).toBeInTheDocument();       // sustained days
    expect(screen.getByText(/✓/)).toBeInTheDocument();        // confluence
  });

  it("shows DEGRADED when dp_status is degraded", () => {
    render(
      <DiscoveredCard
        candidate={{ ...base, dp_status: "degraded", dp_direction: "NO_DATA" }}
        nowMs={Date.parse(base.scored_at)}
      />,
    );
    expect(screen.getByText(/DP N\/A|degraded/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npm run test -- discoveredCard`
Expected: FAIL (component still renders the old DCF `hit` shape; new fields absent).

- [ ] **Step 3: Rewrite `DiscoveredCard.tsx`**

Replace `web/components/scanner/DiscoveredCard.tsx` with a version that drops the `SignalRow`/`hit` usage and renders the edge-quality breakdown. Keep the existing `BiasBadge`, `freshnessLabel`, `+ Watchlist`/`Evaluate` actions, container styling, and `BIAS_COLOR`/`BIAS_ARROW` maps. Key changes:

- `type Discovered = components["schemas"]["DiscoveryCandidate"];` (now the enriched shape).
- Replace `<SignalRow hit={candidate.hit} />` with a `<FactorRow candidate={candidate} />` block.
- Replace the footer score `{Number(candidate.hit.score).toFixed(2)}` with `{Number(candidate.score).toFixed(1)}`.
- Header badge text: keep `DISCOVERED`.

Add this `FactorRow` component inside the file (above `DiscoveredCard`):

```tsx
import { fmtDecimal, toNum } from "@/lib/formatters";

function FactorRow({ candidate }: { candidate: Discovered }) {
  const dp = candidate.dp_direction;
  const dpBadge =
    candidate.dp_status === "degraded"
      ? { label: "DP N/A", color: "var(--text-muted)" }
      : dp === "ACCUMULATION"
        ? { label: "ACC", color: "var(--positive)" }
        : dp === "DISTRIBUTION"
          ? { label: "DIST", color: "var(--negative)" }
          : { label: "NEUTRAL", color: "var(--text-muted)" };
  const cell = {
    display: "flex",
    flexDirection: "column" as const,
    gap: 2,
  };
  const label = {
    fontSize: 9,
    letterSpacing: 1,
    color: "var(--text-muted)",
    textTransform: "uppercase" as const,
  };
  const value = { fontSize: 12, fontWeight: 600 as const };
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 8,
        fontFamily: "var(--font-mono)",
      }}
    >
      <div style={cell}>
        <span style={label}>DARK POOL</span>
        <span style={{ ...value, color: dpBadge.color }}>
          {dpBadge.label}
          {candidate.dp_status !== "degraded" &&
          candidate.dp_strength != null &&
          (candidate.dp_direction === "ACCUMULATION" ||
            candidate.dp_direction === "DISTRIBUTION")
            ? ` ${fmtDecimal(toNum(candidate.dp_strength), 0)}`
            : ""}
          {candidate.dp_sustained_days > 0 ? ` · ${candidate.dp_sustained_days}d` : ""}
        </span>
      </div>
      <div style={cell}>
        <span style={label}>CONFLUENCE</span>
        <span
          style={{
            ...value,
            color: candidate.confluence ? "var(--positive)" : "var(--text-muted)",
          }}
        >
          {candidate.confluence ? "✓ aligned" : "—"}
        </span>
      </div>
      <div style={cell}>
        <span style={label}>VOL/OI</span>
        <span style={value}>{fmtDecimal(toNum(candidate.vol_oi), 1)}×</span>
      </div>
      <div style={cell}>
        <span style={label}>SWEEPS</span>
        <span style={value}>{candidate.sweeps}</span>
      </div>
    </div>
  );
}
```

Then in `DiscoveredCard` body: remove `import { SignalRow } from "./SignalRow";`, replace the `<SignalRow .../>` line (~line 163) with `<FactorRow candidate={candidate} />`, and change the footer score span (~line 203) to:

```tsx
        <span style={{ fontSize: 22, fontWeight: 700, color: tickerColor, letterSpacing: 0.5 }}>
          {Number(candidate.score).toFixed(1)}
        </span>
```

Keep `freshnessLabel(candidate.latest_alert_at, anchor)` and the `alert_count` line. The `onAdd` handler stays unchanged (`candidate.ticker`, `candidate.sector`).

- [ ] **Step 4: Update the page header + sort in `scanner/page.tsx`**

In `web/app/scanner/page.tsx`, the DISCOVERED `<h2>` decoration (lines 116–132) currently reads "outside your watchlist · DCF only · pulled from N alerts". Replace the inner `<span>` text with:

```tsx
            <span>
              DISCOVERED · {discover.candidates.length}{" "}
              <span style={{ color: "var(--text-muted)", fontSize: 9, letterSpacing: 1 }}>
                (edge-quality · DP-confirmed
                {discover.scored_at
                  ? ` · scored ${new Date(discover.scored_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
                  : ""}
                )
              </span>
            </span>
```

The API already returns candidates ordered by score; no client re-sort needed. (Optionally add `discover.candidates` is pre-sorted — leave the `.map` as-is.)

- [ ] **Step 5: Run vitest + typecheck**

Run:
```bash
cd web && npm run test -- discoveredCard && npm run typecheck
```
Expected: discoveredCard tests pass; `tsc --noEmit` clean (new fields resolve against regenerated `types.ts`).

- [ ] **Step 6: Lint + build**

Run: `cd web && npm run lint && npm run build`
Expected: clean. (Fix any unused-import lint from the removed `SignalRow`.)

- [ ] **Step 7: Add a Playwright e2e for the discovered cards (spec §240-242)**

Look at an existing scanner Playwright spec under `web/tests/e2e/` for the harness pattern (route-mocking of `/api/scanner/discover` is the norm so e2e doesn't depend on a live UW feed). Add `web/tests/e2e/scanner-discovered.spec.ts` that mocks `GET **/api/scanner/discover*` with a one-candidate edge-quality payload (the `base` shape from Step 1) and asserts the card shows the ticker, the edge-quality score, the `ACC` DP badge, and the `DISCOVERED` header. If no scanner e2e exists yet, mirror the closest page's spec.

Run: `cd web && npm run test:e2e -- scanner-discovered`
Expected: green (or document the harness gap if Playwright browsers aren't installed in this environment — the dedicated e2e task covers the live path).

- [ ] **Step 8: Commit**

```bash
git add web/components/scanner/DiscoveredCard.tsx web/app/scanner/page.tsx web/tests/unit/discoveredCard.test.tsx web/tests/e2e/scanner-discovered.spec.ts
git commit -m "feat(scanner): DiscoveredCard 5-factor edge-quality breakdown + header"
```

---

## Task 9: Watchlist markout-readiness snapshot (additive)

**Files:**
- Modify: `src/uw_scan/scanner/pipeline.py` (`run_detectors`)
- Test: `tests/integration/scanner/test_scanner_orchestrator_e2e.py` (extend) or a new focused test

- [ ] **Step 1: Write the failing test**

Add to `tests/integration/scanner/test_scanner_orchestrator_e2e.py` (or create `tests/integration/scanner/test_watchlist_snapshot.py`):

```python
def test_run_detectors_persists_watchlist_snapshot(seeded_db_empty_cards):
    """A watchlist candidate also writes a markout-ready snapshot row."""
    from datetime import date
    from decimal import Decimal

    from uw_scan.config import Settings
    from uw_scan.models import FlowAlert
    from uw_scan.scanner.pipeline import run_detectors
    from uw_scan.storage.repository import Repository
    from uw_scan.storage.signals_repository import SignalsRepository

    repo: Repository = seeded_db_empty_cards
    settings = Settings.from_env()
    sigs = SignalsRepository(repo.conn, schema="uw_scan")
    run_id = repo.insert_scan_run("AAPL", notes="")

    # Persist a qualifying flow alert so DCF emits a candidate.
    repo.insert_flow_events(  # use the repo's flow-event writer
        run_id,
        "AAPL",
        [
            FlowAlert(
                id="a1",
                ticker="AAPL",
                type="call",
                expiry=date(2026, 9, 18),
                strike=Decimal("200"),
                underlying_price=Decimal("190"),
                total_premium=Decimal("2000000"),
                total_ask_side_prem=Decimal("1900000"),
                total_bid_side_prem=Decimal("100000"),
                volume=5000,
                open_interest=1000,
                next_earnings_date=date(2026, 12, 31),
            )
        ],
    )
    repo.conn.commit()

    cand = run_detectors(
        repo=repo, signals_repo=sigs, settings=settings,
        run_id=run_id, ticker="AAPL", today=date(2026, 6, 15),
    )
    repo.conn.commit()
    assert cand is not None

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT section, score_model, is_type_f FROM uw_scan.scanner_candidate_snapshots "
            "WHERE run_id=%s AND ticker='AAPL'",
            (run_id,),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == "watchlist"
    assert row[1] == "watchlist_tier_v1"
```

> Confirm the flow-event writer name (`insert_flow_events` / `upsert_flow_events`) by grepping `src/uw_scan/storage/flow.py`; adjust the call. If a writer helper is awkward, insert the `flow_events` row via raw SQL matching the `_fetch_flow_alerts_for_run` columns.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/integration/scanner/test_watchlist_snapshot.py -v`
Expected: FAIL (no snapshot row written).

- [ ] **Step 3: Add the additive snapshot write to `run_detectors`**

In `src/uw_scan/scanner/pipeline.py`, change the tail of `run_detectors` (lines 225–230). Replace:

```python
    return build_candidate(
        ticker=ticker,
        hits=hits,
        context_flags=flags,
        gates={"earnings": earnings, "liquidity": liquidity, "regime": regime},
    )
```

with:

```python
    candidate = build_candidate(
        ticker=ticker,
        hits=hits,
        context_flags=flags,
        gates={"earnings": earnings, "liquidity": liquidity, "regime": regime},
    )

    # Markout-ready snapshot (additive — granular signal_hits stay the audit).
    if candidate is not None:
        try:
            from datetime import datetime, timezone

            top_dcf = next(
                (h for h in candidate.hits if h.signal_type == "deep_conviction_flow"),
                None,
            )
            direction = (
                top_dcf.evidence.get("direction") if top_dcf is not None else None
            )
            snapshot_row = {
                "ticker": ticker,
                "scored_at": datetime.now(timezone.utc),
                "bias": candidate.bias,
                "direction": direction,
                "score": candidate.final_score,
                "score_model": "watchlist_tier_v1",
                "score_breakdown": {
                    "raw_score": float(candidate.raw_score),
                    "confluence_score": float(candidate.confluence_score),
                    "final_score": float(candidate.final_score),
                },
                "spot_at_signal": spot,
                "is_type_f": candidate.is_type_f,
                "evidence": {
                    "hit_types": [h.signal_type for h in candidate.hits],
                    "setup": candidate.setup,
                },
            }
            # Savepoint so a snapshot-write error can't abort the shared scan
            # transaction (which would then break the caller's finish_scan_run).
            with repo.conn.transaction():
                signals_repo.insert_candidate_snapshots_bulk(
                    run_id=run_id, section="watchlist", rows=[snapshot_row]
                )
        except Exception as exc:  # noqa: BLE001 — never block the scan on snapshot persistence
            logger.exception(
                "scanner snapshot persist failed for %s run_id=%s: %r",
                ticker,
                run_id,
                exc,
            )

    return candidate
```

(`spot` is already in scope from line 158; `signals_repo` is a `run_detectors` param.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/scanner/test_watchlist_snapshot.py -v`
Expected: passed.

- [ ] **Step 5: Run the full scanner integration suite for regressions**

Run: `uv run pytest tests/integration/scanner -q`
Expected: green (the snapshot write is additive; existing assertions on `signal_hits` / candidates unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/scanner/pipeline.py tests/integration/scanner/test_watchlist_snapshot.py
git commit -m "feat(scanner): persist markout-ready watchlist candidate snapshots"
```

---

## Task 10: Full verification gates

**Files:** none (verification only)

- [ ] **Step 1: Python test suite**

Run: `uv run pytest -q`
Expected: all green. Capture the summary line (passed/failed counts).

- [ ] **Step 2: Migration idempotency (re-run = no-op)**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: second run reports no changes / no errors.

- [ ] **Step 3: OpenAPI snapshot is current**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: green (snapshot matches the live schema from Task 7).

- [ ] **Step 4: Web gates**

Run: `cd web && npm run gen:types && git diff --quiet web/lib/types.ts && echo "TYPES CLEAN" && npm run typecheck && npm run test && npm run lint && npm run build`
Expected: `TYPES CLEAN` printed (no drift), then typecheck/test/lint/build all green.

- [ ] **Step 5: Verify no Yahoo / naked-short / secrets-to-codex regressions**

Confirm by inspection: the discovery job uses only UW (`fetch_market_flow_alerts`, `fetch_darkpool_ticker`) — no Yahoo, no broker orders, no secrets passed to subprocesses. (Nothing in this plan touches those paths.)

- [ ] **Step 6: Final commit if any verification fixups were needed**

```bash
git add -p   # stage only verification fixups, never -A
git commit -m "chore(scanner): verification fixups for discovery expansion"
```

---

## Out of scope (Phase 2 — separate spec)

Markout / forward-return validation: a job joining each `scanner_candidate_snapshots` row to forward OHLC at +1/+5/+20 sessions, signed by `direction`, into a `markout_results` table, plus a UI markout column + aggregate hit-rate. This plan only guarantees the inputs (`spot_at_signal`, `direction`, `scored_at`, both sections) exist.

## Self-Review notes (completed while writing)

- **Spec coverage:** edge-quality scorer (Task 3), live DP on top-N (Task 5), `dark_pool_events` reuse (Task 5 reads warm window + writes today), RTH + close cadence (Task 6 cron `15,45 9-16`, offset off full_scan), unified snapshot table (Tasks 1–2), Approach A thin-read (Task 7), earnings drop preserved (Task 5 `_group_alerts`), watchlist markout-readiness (Task 9), no silent caps (Task 5 logs `dp_truncated`), graceful DP degrade → flow-only (Task 5 + test), empty-feed + zero-candidate-nonempty-feed metadata (Task 2/5 `upsert_discovery_run_meta` + tests). All present.
- **Type consistency:** `insert_candidate_snapshots_bulk` / `fetch_latest_discovery_snapshot` / `upsert_discovery_run_meta` signatures match across Tasks 2, 5, 7, 9. `score_model` strings `edge_quality_v1` / `watchlist_tier_v1` consistent. `directional_darkpool` / `analyze_darkpool_day` / `calculate_score` / `options_bias` / `has_confluence` names match between Task 3 impl and Task 5 caller.
- **radon parity divergences (intentional):** (a) canceled prints are excluded at the SQL layer by `fetch_dark_pool_window` (`COALESCE(canceled,FALSE)=FALSE`), so `analyze_darkpool_day` need not re-check; (b) the DP window uses a calendar-day lookback over a trading-day-only warm table (vs radon's trading-day calendar) — negligible for a 3-day window; (c) scores persist at full `NUMERIC(8,3)` precision and round only at display (radon rounded in-scorer); (d) discovery applies only premium + earnings hard filters (no DCF conviction gates) — see the Task-5 filter-divergence note. (e) cross-run print dedup by `tracking_id` in `directional_darkpool` (argon's warm table re-inserts today's prints under a fresh `run_id` each tick; radon cached to disk so never double-counted).
- **Deviations** from spec documented at top (SignalsRepository home; sequential Stage 2 + dropped concurrency knob, rate-guard via cron offset + cap + sleep knob; run-meta on the scan_runs row; `discover_from_alerts` left unwired; watchlist read deferred to Phase 2).
- **Codex Pass-2 review applied:** cross-run DP dedup (blocker), savepoint in both the job and watchlist snapshot writes (blockers), replace the obsolete `test_scanner_discover.py` + existing `discoveredCard.test.tsx` (blockers/major), degraded→flow-only, run-meta independent of candidate rows, render DP strength, non-watchlist test tickers, cron offset.
