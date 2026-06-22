# VRP Harvest Markout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score the realized variance-risk-premium (VRP) harvest per `(asset_class, deviation_class)` bucket with out-of-sample discipline, and persist a `HARVEST_SELLABLE` / `NONE` verdict per bucket consumable via `GET /api/regime/vrp-harvest`.

**Architecture:** A new read-only markout (`reports/vrp_markout.py`) runs nightly over the existing `vrp_daily` panel: it classifies each daily observation by `vrp_z_20` extremity (RICH/NORMAL/CHEAP), computes the realized harvest `IV(t) − RV(t+20)` from `vrp_daily` alone (units-consistent by construction), drops earnings-spanning windows, buckets by asset class, then applies a walk-forward holdout and a per-quarter catastrophic-degradation gate before writing a verdict per bucket. It mirrors the skew markout's OOS discipline but tests the **absolute** harvest level, not a cross-sectionally demeaned reversion.

**Tech Stack:** Python 3.13 (`uv`), psycopg 3, FastAPI + Pydantic v2, APScheduler, pytest + pytest-postgresql, `openapi-typescript` for `web/lib/types.ts`.

## Global Constraints

These apply to every task. Values copied verbatim from the spec (`docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md`) and the repo's standing rules (`CLAUDE.md`).

- **uv only** — run tests with `uv run pytest`, never bare `pytest`.
- **Persist analytical results to Postgres** — the markout writes `vrp_harvest_verdicts`; returning data without persisting is a regression.
- **Do NOT modify `src/uw_scan/reports/skew_markout.py`** — its orchestration is welded to risk-reversal (spec §Components 1). The generic helpers it holds are module-private and have **no** existing cross-module consumer; reuse the *logic* by reimplementing the one shared primitive (a 9-line trading-day forward read) inside `vrp_markout.py`. Do not import `skew_markout`'s underscore-prefixed functions.
- **New persistence domain gets its own storage module** — `storage/vrp_markout.py` with `_VrpMarkoutMixin`; never append query methods to `repository.py` (it stays a thin assembly shell).
- **Migrations are idempotent** — `CREATE TABLE IF NOT EXISTS`, header `SET search_path TO uw_scan, public;`, no `GRANT` lines (privileges handled at the role/deploy level, not per-migration). Applied in lexical order; no tracking table.
- **`Decimal` round-trips at the storage boundary** (NUMERIC columns); markout math uses `float` internally, matching the established skew_markout pattern. Convert `Decimal → float` when reading `vrp_daily` rows.
- **No naked shorts** — this is analytics only (no trade-construction code); the verdict feeds a defined-risk "is vol rich enough to sell" decision elsewhere.
- **Module size budget** — target <500 lines per file. `reports/vrp_markout.py` is the largest new file; keep it well under.
- **ET timezone crons, Monday=0** — scheduler crons use `CronTrigger.from_crontab(..., timezone=settings.rth_tz)` with `0-4` for Mon–Fri.
- **Determinism** — pass `as_of`/`today` in; the markout reads `_date.today()` once at the top of `run_vrp_markout` and threads it (mirrors `assemble_skew_analysis`).
- **No fabrication** — every signature in this plan was verified against current source; if reality differs at execution time, stop and reconcile.

### Verdict semantics (spec §Verdict, §Scoring) — the contract every task implements

- `deviation_class`: **RICH** when `vrp_z_20 ≥ +1.0`; **CHEAP** when `vrp_z_20 ≤ −1.0`; **NORMAL** otherwise.
- `realized_VRP(t) = iv(t) − rv(t+20)`, where `iv(t)` is `vrp_daily.iv` at the signal date and `rv(t+20)` is `vrp_daily.rv` (trailing-21d RV) read **20 trading days forward** ≈ realized vol over `[t, t+20]`.
- **Primary metric:** the **absolute** mean `realized_VRP` per bucket (NOT cross-sectionally demeaned). A positive, stable mean in the RICH bucket is the sellable edge.
- **Conditioning evidence:** `rich_cheap_spread` per asset class = mean(RICH) − mean(CHEAP).
- `HARVEST_SELLABLE` requires ALL of: `n ≥ min_n` (default 20), mean `realized_VRP > 0.02` (2 vol points, decimal vols), survives walk-forward (full **and** holdout means positive, full clears the magnitude floor), survives the per-quarter catastrophic gate. Otherwise `NONE`. Confidence capped at `"med"` (never `"high"` — mirrors skew).
- **Kill criteria:** if RICH isn't reliably positive / spread ~zero / nothing survives the quarter gate, record `NONE` and stop. Do NOT loosen thresholds to manufacture a signal.

---

## File Structure

| File | Responsibility | New/Modify |
|---|---|---|
| `src/uw_scan/storage/migrations/079_vrp_harvest_verdicts.sql` | Create the `vrp_harvest_verdicts` table | **New** |
| `src/uw_scan/storage/vrp_markout.py` | `_VrpMarkoutMixin`: verdict upsert/fetch + earnings-date reconstruction | **New** |
| `src/uw_scan/storage/repository.py` | Wire `_VrpMarkoutMixin` into `Repository` | Modify |
| `src/uw_scan/reports/vrp_markout.py` | The markout: classify → harvest → bucket → OOS gates → persist | **New** |
| `src/uw_scan/worker/jobs/vrp_markout.py` | Thin scheduler wrapper `vrp_markout_refresh` | **New** |
| `src/uw_scan/worker/scheduler.py` | Register the nightly job | Modify |
| `src/uw_scan/api/schemas.py` | `VrpHarvestVerdict` + `VrpHarvestResponse` response models | Modify |
| `src/uw_scan/api/routers/regime.py` | `GET /regime/vrp-harvest` endpoint | Modify |
| `tests/integration/api/openapi.snapshot.json` | Regenerate after the API change | Modify (generated) |
| `web/lib/types.ts` | Regenerate after the API change | Modify (generated) |
| `docs/...` / `CLAUDE.md` / `AGENTS.md` | Pointers + schedule row | Modify |

> **Migration numbering:** migrations `077`/`078` are reserved by the in-flight option-surface PR #145 on a sibling branch; this branch (off `main`) currently tops out at `076`. Using `079` avoids a duplicate-number filename on `main` regardless of merge order. Gaps are harmless — migrations apply by lexical order with no tracking table.

---

## Design decisions flagged for review (read before the review-cycle)

These are the two spec/reality reconciliations the implementer must NOT silently "fix". They are deliberate and documented; the review-cycle should evaluate them against the design.

1. **Earnings exclusion source (spec §Earnings exclusion).** The spec says "reuse the earnings-date source the skew lean already consumes." That source (`repo.fetch_latest_next_earnings_date`) returns only the **single latest upcoming** date — insufficient for the spec's **per-historical-observation** `(t, t+20]` exclusion across a 13-month panel. argon has **no** historical earnings-calendar table. The viable reconstruction is the **distinct set of `flow_events.next_earnings_date`** recorded over time (each row stored the next-earnings date as known at insert; the distinct set ≈ the actual earnings calendar for that ticker over the window). **Known limitations (and the v1 safeguard):** `flow_events.next_earnings_date` is "next earnings as known at insert", not a settled historical calendar — it can (a) **miss** earnings for a ticker with little/no flow history, and (b) retain **stale pre-revision** dates around rescheduled prints. Because an unexcluded earnings window *inflates* the realized harvest (IV ramps pre-print, RV crushes after) and would manufacture a false `HARVEST_SELLABLE`, the v1 safeguard is: **`run_vrp_markout` skips any `single_name` ticker whose reconstructed earnings set is empty** (it cannot honor the exclusion → it must not contribute) and logs a coverage warning. `index_macro` / `sector_etf` / `credit` legitimately have no earnings, so an empty set there is correct and NOT skipped. This honors AC2 ("earnings-spanning observations are provably excluded") by only scoring tickers where the exclusion is verifiable. Do not invent a `fetch_earnings_history`-backed table.

2. **Single-source harvest (spec §Forward target).** `vrp_daily.iv`/`.rv` are derived from `realized_volatility_history.implied_volatility`/`.realized_volatility` (see `cards/vol_series.py:compute_vrp_series`). **Provenance caveat:** `vrp_daily.rv` is *mostly* the UW realized-vol value, but endpoint-driven writes (`reports/volatility_series.py:assemble_volatility_series`) run `_fill_rv_from_price(...)` first, so a row's `rv` may be a price-derived fill, while the nightly rollup (`worker/volatility_jobs.py`) writes the raw value — i.e. `vrp_daily.rv` is **mixed-provenance**. This does NOT break the harvest: the `iv` leg is always the UW implied vol (`_fill_rv_from_price` only fills RV, never IV), and a price-derived RV fill is still **annualized realized vol in the same units** as the UW RV — so `iv(t) − rv(t+20)` is units-consistent whether or not `rv(t+20)` was filled. Treat `vrp_daily` as the **authoritative v1 source** for the harvest (do not claim byte-for-byte equivalence to `realized_volatility_history`). The spec's `realized_volatility_history` price-series fallback (exact forward RV via `_price_series`) is **deferred (YAGNI v1)** — the trailing-21d-read-forward approximation is the documented v1 path. Do not add the price fallback in this plan.

---

### Task 1: Storage layer — verdict table, mixin, earnings reconstruction

**Files:**
- Create: `src/uw_scan/storage/migrations/079_vrp_harvest_verdicts.sql`
- Create: `src/uw_scan/storage/vrp_markout.py`
- Modify: `src/uw_scan/storage/repository.py` (import block ~line 72 area; inheritance list ~lines 100-128)
- Test: `tests/integration/storage/test_vrp_markout_storage.py`

**Interfaces:**
- Consumes: nothing from earlier tasks. Reads existing `flow_events.next_earnings_date` (migration 001).
- Produces (later tasks rely on these exact signatures):
  - `Repository.upsert_vrp_harvest_verdict(*, asset_class: str, deviation_class: str, verdict: str, mean_realized_vrp: float | None, mean_holdout: float | None, rich_cheap_spread: float | None, n: int, n_holdout: int, survives_walkforward: bool, survives_window_gate: bool, confidence: str | None, as_of: date | None) -> None`
  - `Repository.fetch_vrp_harvest_verdicts() -> list[dict[str, Any]]` (keys = column names)
  - `Repository.fetch_known_earnings_dates(ticker: str) -> set[date]`

- [ ] **Step 1: Write the migration**

Create `src/uw_scan/storage/migrations/079_vrp_harvest_verdicts.sql`:

```sql
-- 079_vrp_harvest_verdicts.sql
-- VRP harvest markout verdict store (Spec B: 2026-06-19-vrp-harvest-markout-design).
-- One row per (asset_class, deviation_class) bucket; idempotent; never wiped.
-- Numbered 079 to leapfrog the in-flight option-surface PR's 077/078 on a
-- sibling branch (avoids a same-number filename on main). Gaps are harmless:
-- migrations apply by lexical order with no tracking table.
SET search_path TO uw_scan, public;

BEGIN;

CREATE TABLE IF NOT EXISTS uw_scan.vrp_harvest_verdicts (
    asset_class           TEXT NOT NULL,
    deviation_class       TEXT NOT NULL,
    verdict               TEXT NOT NULL,
    mean_realized_vrp     NUMERIC,
    mean_holdout          NUMERIC,
    rich_cheap_spread     NUMERIC,
    n                     INTEGER NOT NULL DEFAULT 0,
    n_holdout             INTEGER NOT NULL DEFAULT 0,
    survives_walkforward  BOOLEAN NOT NULL DEFAULT FALSE,
    survives_window_gate  BOOLEAN NOT NULL DEFAULT FALSE,
    confidence            TEXT,
    as_of                 DATE,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_class, deviation_class)
);

COMMENT ON TABLE uw_scan.vrp_harvest_verdicts
    IS 'Per-bucket VRP harvest markout conclusions (Spec B). verdict HARVEST_SELLABLE only when mean realized VRP clears threshold AND survives walk-forward AND the per-quarter catastrophic gate.';

COMMIT;
```

- [ ] **Step 2: Write the failing storage test**

Create `tests/integration/storage/test_vrp_markout_storage.py`:

```python
from __future__ import annotations

from datetime import date


def test_upsert_and_fetch_vrp_harvest_verdict(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_harvest_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.031,
        mean_holdout=0.028,
        rich_cheap_spread=0.015,
        n=42,
        n_holdout=17,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 6, 21),
    )
    repo.conn.commit()
    rows = repo.fetch_vrp_harvest_verdicts()
    assert len(rows) == 1
    r = rows[0]
    assert r["asset_class"] == "single_name"
    assert r["deviation_class"] == "RICH"
    assert r["verdict"] == "HARVEST_SELLABLE"
    assert float(r["mean_realized_vrp"]) == 0.031
    assert r["n"] == 42
    assert r["survives_walkforward"] is True


def test_upsert_vrp_harvest_verdict_is_idempotent(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    for verdict in ("NONE", "HARVEST_SELLABLE"):
        repo.upsert_vrp_harvest_verdict(
            asset_class="index_macro",
            deviation_class="RICH",
            verdict=verdict,
            mean_realized_vrp=0.05,
            mean_holdout=0.04,
            rich_cheap_spread=0.02,
            n=30,
            n_holdout=12,
            survives_walkforward=True,
            survives_window_gate=True,
            confidence="med",
            as_of=date(2026, 6, 21),
        )
    repo.conn.commit()
    rows = repo.fetch_vrp_harvest_verdicts()
    assert len(rows) == 1  # same PK overwrites
    assert rows[0]["verdict"] == "HARVEST_SELLABLE"


def test_fetch_known_earnings_dates_distinct_set(seeded_db_empty_cards) -> None:
    repo = seeded_db_empty_cards
    # flow_events requires run_id (FK -> scan_runs) + alert_id (NOT NULL),
    # UNIQUE(run_id, alert_id). Seed rows recording the "next earnings" as it
    # rolled forward over time (proven pattern: test_skew_storage.py:101).
    run_id = repo.insert_scan_run(ticker="TESTX")
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.flow_events "
            "(run_id, alert_id, ticker, next_earnings_date) VALUES "
            "(%s, 'a1', 'TESTX', %s), "
            "(%s, 'a2', 'TESTX', %s), "
            "(%s, 'a3', 'TESTX', %s), "
            "(%s, 'a4', 'TESTX', %s)",
            (
                run_id, date(2026, 1, 28),
                run_id, date(2026, 1, 28),  # duplicate date, distinct alert_id
                run_id, date(2026, 4, 29),
                run_id, None,               # null earnings → excluded by the query
            ),
        )
    repo.conn.commit()
    got = repo.fetch_known_earnings_dates("testx")  # case-insensitive
    assert got == {date(2026, 1, 28), date(2026, 4, 29)}
    assert repo.fetch_known_earnings_dates("NOPE") == set()
```

> `insert_scan_run(ticker: str, notes: str = "") -> int` (verified `storage/scan_runs.py:57`). The `FlowEventRow` import in the test header is unused — drop it; seed via raw SQL as above.

- [ ] **Step 3: Run the test to verify it fails**

Run (MacBook recipe — `.env.local` points at the prod mini, so override to the local test DB):
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/storage/test_vrp_markout_storage.py -v
```
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_vrp_harvest_verdict'` (and the migration/table won't exist until the test DB re-applies migrations; the session-scoped conftest applies all `migrations/*.sql` once — the new `079` file is picked up automatically).

- [ ] **Step 4: Write the storage mixin**

Create `src/uw_scan/storage/vrp_markout.py`:

```python
"""VRP harvest markout verdict persistence + earnings-date reconstruction (Spec B)."""

from __future__ import annotations

from datetime import date as _date
from typing import Any

import psycopg


class _VrpMarkoutMixin:
    _conn: psycopg.Connection
    _schema: str

    def upsert_vrp_harvest_verdict(
        self,
        *,
        asset_class: str,
        deviation_class: str,
        verdict: str,
        mean_realized_vrp: float | None,
        mean_holdout: float | None,
        rich_cheap_spread: float | None,
        n: int,
        n_holdout: int,
        survives_walkforward: bool,
        survives_window_gate: bool,
        confidence: str | None,
        as_of: _date | None,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.vrp_harvest_verdicts "
            "(asset_class, deviation_class, verdict, mean_realized_vrp, mean_holdout, "
            "rich_cheap_spread, n, n_holdout, survives_walkforward, "
            "survives_window_gate, confidence, as_of) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (asset_class, deviation_class) DO UPDATE SET "
            "verdict = EXCLUDED.verdict, "
            "mean_realized_vrp = EXCLUDED.mean_realized_vrp, "
            "mean_holdout = EXCLUDED.mean_holdout, "
            "rich_cheap_spread = EXCLUDED.rich_cheap_spread, "
            "n = EXCLUDED.n, n_holdout = EXCLUDED.n_holdout, "
            "survives_walkforward = EXCLUDED.survives_walkforward, "
            "survives_window_gate = EXCLUDED.survives_window_gate, "
            "confidence = EXCLUDED.confidence, as_of = EXCLUDED.as_of, "
            "inserted_at = now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    asset_class,
                    deviation_class,
                    verdict,
                    mean_realized_vrp,
                    mean_holdout,
                    rich_cheap_spread,
                    n,
                    n_holdout,
                    survives_walkforward,
                    survives_window_gate,
                    confidence,
                    as_of,
                ),
            )

    def fetch_vrp_harvest_verdicts(self) -> list[dict[str, Any]]:
        sql = (
            "SELECT asset_class, deviation_class, verdict, mean_realized_vrp, "
            "mean_holdout, rich_cheap_spread, n, n_holdout, survives_walkforward, "
            "survives_window_gate, confidence, as_of "
            f"FROM {self._schema}.vrp_harvest_verdicts "
            "ORDER BY asset_class, deviation_class"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql)
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]

    def fetch_known_earnings_dates(self, ticker: str) -> set[_date]:
        """Reconstruct the ticker's earnings calendar from the DISTINCT
        next_earnings_date values flow_events recorded over time. argon has no
        dedicated historical earnings table; each flow_events row carried the
        next-earnings date as known at insert, so the distinct set approximates
        the actual earnings dates seen over the panel window. Coverage is limited
        to tickers that appeared in flow_events; indices return an empty set."""
        sql = (
            f"SELECT DISTINCT next_earnings_date FROM {self._schema}.flow_events "
            "WHERE ticker = %s AND next_earnings_date IS NOT NULL"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (ticker.upper(),))
            return {row[0] for row in cur.fetchall()}
```

- [ ] **Step 5: Wire the mixin into `Repository`**

In `src/uw_scan/storage/repository.py`, add the import alongside the other domain mixin imports (near `from .volatility_v2 import _VolatilityV2Mixin`):

```python
from .vrp_markout import _VrpMarkoutMixin
```

And add `_VrpMarkoutMixin,` to the `class Repository(...)` inheritance list, immediately before `_BaseMixin` (which MUST stay last). Place it after `_VolatilityV2Mixin,`:

```python
    _VolatilityV2Mixin,
    _VrpMarkoutMixin,
    _WatchlistMixin,
    _WsConsumerStateMixin,
    _BaseMixin,
):
```

- [ ] **Step 6: Run the test to verify it passes**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/storage/test_vrp_markout_storage.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/migrations/079_vrp_harvest_verdicts.sql \
        src/uw_scan/storage/vrp_markout.py \
        src/uw_scan/storage/repository.py \
        tests/integration/storage/test_vrp_markout_storage.py
git commit -m "feat(vrp): verdict table + storage mixin + earnings reconstruction"
```

---

### Task 2: Signal + target helpers (classification, forward read, harvest builder)

**Files:**
- Create: `src/uw_scan/reports/vrp_markout.py` (helpers only this task; orchestration in Task 4)
- Test: `tests/unit/test_vrp_markout_helpers.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `RICH_Z = 1.0`, `CHEAP_Z = -1.0`, `HORIZON = 20` (module constants)
  - `_deviation_class(vrp_z: float | None) -> str | None` → `"RICH" | "CHEAP" | "NORMAL" | None`
  - `_earnings_in_window(t: date, end: date, earnings: set[date]) -> bool`
  - `_harvest_obs(rows: list[dict], *, earnings: set[date]) -> list[dict]` where each obs = `{"market_date": date, "deviation_class": str, "realized_vrp": float}`. **Reads the EXACT 20th-trading-day-forward row by position** over the full ordered series (one `vrp_daily` row per trading day), NOT the 20th non-null-RV row — interior null RV must not shift the target.

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_vrp_markout_helpers.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports import vrp_markout as vm

_BASE = date(2026, 1, 5)  # Monday; calendar-day spacing is fine for unit logic


def _panel(n, *, iv=0.30, rv=0.20, z=1.2):
    """n consecutive daily vrp_daily-shaped rows (one row per trading day)."""
    return [
        {"market_date": _BASE + timedelta(days=i), "iv": iv, "rv": rv, "vrp_z_20": z}
        for i in range(n)
    ]


def test_deviation_class_thresholds():
    assert vm._deviation_class(1.0) == "RICH"
    assert vm._deviation_class(1.5) == "RICH"
    assert vm._deviation_class(-1.0) == "CHEAP"
    assert vm._deviation_class(-1.5) == "CHEAP"
    assert vm._deviation_class(0.0) == "NORMAL"
    assert vm._deviation_class(0.99) == "NORMAL"
    assert vm._deviation_class(None) is None


def test_earnings_in_window_is_left_open_right_closed():
    earn = {date(2026, 1, 15)}
    # window (t, end]; t itself excluded, end included
    assert vm._earnings_in_window(date(2026, 1, 1), date(2026, 1, 20), earn) is True
    assert vm._earnings_in_window(date(2026, 1, 15), date(2026, 1, 20), earn) is False  # t == earn, open lower bound
    assert vm._earnings_in_window(date(2026, 1, 1), date(2026, 1, 15), earn) is True   # end == earn, closed upper
    assert vm._earnings_in_window(date(2026, 1, 16), date(2026, 1, 30), earn) is False
    assert vm._earnings_in_window(date(2026, 1, 1), date(2026, 1, 20), set()) is False


def test_harvest_obs_computes_iv_minus_forward_rv():
    # 25 daily rows; constant iv=0.30, rv=0.20 → realized_vrp = 0.10.
    obs = vm._harvest_obs(_panel(25), earnings=set())
    # anchors i with i+HORIZON(20) < 25 → i in 0..4 → 5 obs.
    assert len(obs) == 5
    assert all(o["deviation_class"] == "RICH" for o in obs)
    assert all(abs(o["realized_vrp"] - 0.10) < 1e-9 for o in obs)
    assert obs[0]["market_date"] == _BASE


def test_harvest_obs_reads_exact_t20_row_not_skipping_nulls():
    # ISSUE-1 regression: the forward read must be the EXACT 20th trading-day
    # row by position, NOT the 20th non-null-RV row. Null RV at index 20 means
    # anchor 0 (whose exact t+20 IS index 20) must be DROPPED — a skip-nulls
    # impl would instead grab index 21 and wrongly keep anchor 0.
    rows = _panel(30)
    rows[20]["rv"] = None
    obs = vm._harvest_obs(rows, earnings=set())
    dates = {o["market_date"] for o in obs}
    assert _BASE not in dates                      # anchor 0 dropped (exact t+20 null)
    assert (_BASE + timedelta(days=1)) in dates    # anchor 1 (t+20=index 21) kept
    assert len(obs) == 9                           # scorable 0..9, minus anchor 0


def test_harvest_obs_drops_null_signal_and_iv_in_scorable_region():
    # ISSUE-8: nulls placed in the SCORABLE region (not the unscorable tail) so
    # the test fails if the guards are removed. Compare against a clean control.
    control = vm._harvest_obs(_panel(30), earnings=set())
    assert len(control) == 10                       # anchors 0..9
    rows = _panel(30)
    rows[2]["iv"] = None
    rows[5]["vrp_z_20"] = None
    obs = vm._harvest_obs(rows, earnings=set())
    dates = {o["market_date"] for o in obs}
    assert len(obs) == 8                            # 10 control - 2 nulled anchors
    assert (_BASE + timedelta(days=2)) not in dates
    assert (_BASE + timedelta(days=5)) not in dates


def test_harvest_obs_count_at_min_n_boundary():
    # ISSUE-9: pin the off-by-one. 40 rows → 20 scorable obs (== MIN_N);
    # 39 rows → 19 (< MIN_N).
    assert len(vm._harvest_obs(_panel(40), earnings=set())) == 20
    assert len(vm._harvest_obs(_panel(39), earnings=set())) == 19


def test_harvest_obs_excludes_earnings_spanning_windows():
    # earnings at index 10; for anchor i the window is (t_i, t_{i+20}]. All
    # scorable anchors (i in 0..4 for a 25-row panel) span index 10 → all dropped.
    obs = vm._harvest_obs(_panel(25), earnings={_BASE + timedelta(days=10)})
    assert obs == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
uv run pytest tests/unit/test_vrp_markout_helpers.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.vrp_markout'`.

- [ ] **Step 3: Write the helpers**

Create `src/uw_scan/reports/vrp_markout.py`:

```python
"""VRP harvest markout (Spec B) — does selling rich vol earn a reliable premium?

Read-only over vrp_daily (+ flow_events earnings reconstruction); writes
vrp_harvest_verdicts. Mirrors the skew markout's OOS discipline (walk-forward
holdout + per-quarter catastrophic gate) but tests the ABSOLUTE harvest level,
not a cross-sectionally demeaned reversion.

Deliberately does NOT import skew_markout's private helpers: no cross-module
consumer of those underscore-prefixed functions exists in this repo, and the
spec forbids modifying skew_markout.py. The one shared primitive — the
trading-day forward read — is reimplemented here (small, pure, self-contained).
"""

from __future__ import annotations

from datetime import date as _date

# (Tasks 3 and 4 append more imports — defaultdict, logging, typing.Any, and the
# asset-class/Repository imports — each in the task that first uses them, so every
# task's commit stays lint-clean.)

# --- Signal thresholds (spec §Signal) -------------------------------------
RICH_Z = 1.0
CHEAP_Z = -1.0

# Forward horizon for the harvest read (spec §Forward target): trailing-21d RV
# read 20 trading days forward ≈ realized vol over [t, t+20]. The earnings
# exclusion window uses the ACTUAL forward trading date (the 20th forward row),
# not a calendar offset — so no separate window-days constant is needed.
HORIZON = 20


def _deviation_class(vrp_z: float | None) -> str | None:
    """RICH/NORMAL/CHEAP from the 20d VRP z-score; None when the signal is null."""
    if vrp_z is None:
        return None
    if vrp_z >= RICH_Z:
        return "RICH"
    if vrp_z <= CHEAP_Z:
        return "CHEAP"
    return "NORMAL"


def _earnings_in_window(t: _date, end: _date, earnings: set[_date]) -> bool:
    """True if any earnings date falls in (t, end] — the forward markout window
    straddles a known earnings event (the short-vol trap we exclude)."""
    return any(t < e <= end for e in earnings)


def _harvest_obs(rows: list[dict], *, earnings: set[_date]) -> list[dict]:
    """Build realized-VRP observations for one ticker.

    rows: vrp_daily rows [{market_date, iv, rv, vrp_z_20}], any order. There is
    one row per trading day, so the EXACT 20th trading day forward is the row at
    position i + HORIZON in the date-sorted list (positional — NOT a non-null-RV
    skip; an interior null RV must not shift the target).
    realized_VRP(t) = iv(t) - rv(t+20). Drops an anchor when: its signal or iv is
    null, there is no i+HORIZON row yet (recent tail), the exact t+20 row's rv is
    null, or an earnings date falls in (t, t+20]. Values may be Decimal — coerced
    to float."""
    ordered = sorted(rows, key=lambda r: r["market_date"])
    n = len(ordered)
    obs: list[dict] = []
    for i, r in enumerate(ordered):
        t = r["market_date"]
        # vrp_z_20 is NULL (never NaN) when undefined — the first ~19 rows per
        # ticker, before the 20d rolling z-score is defined. persist_vrp_daily's
        # _dec converts NaN→None (volatility_series.py), so None is the only
        # "missing" sentinel here and _deviation_class(None) → None → skipped.
        dev = _deviation_class(None if r["vrp_z_20"] is None else float(r["vrp_z_20"]))
        if dev is None or r["iv"] is None:
            continue
        j = i + HORIZON
        if j >= n:
            continue  # no forward target yet
        fwd = ordered[j]
        if fwd["rv"] is None:
            continue  # exact t+20 RV missing → cannot score this anchor
        if _earnings_in_window(t, fwd["market_date"], earnings):
            continue
        obs.append(
            {
                "market_date": t,
                "deviation_class": dev,
                "realized_vrp": float(r["iv"]) - float(fwd["rv"]),
            }
        )
    return obs
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
uv run pytest tests/unit/test_vrp_markout_helpers.py -v
```
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_markout.py tests/unit/test_vrp_markout_helpers.py
git commit -m "feat(vrp): signal classification + realized-harvest builder"
```

---

### Task 3: OOS gate helpers (walk-forward holdout + per-quarter gate)

**Files:**
- Modify: `src/uw_scan/reports/vrp_markout.py` (append helpers)
- Test: `tests/unit/test_vrp_markout_gates.py`

**Interfaces:**
- Consumes: nothing from Task 2 (operates on obs dicts with `market_date` + `realized_vrp`).
- Produces:
  - `MIN_N = 20`, `HOLDOUT_FRAC = 0.40`, `HARVEST_THRESHOLD = 0.02`, `HOLDOUT_THRESHOLD = 0.01` (module constants)
  - `_survives_quarter_gate(obs: list[dict], overall_mean: float) -> bool`
  - `_walkforward_harvest(obs: list[dict], *, min_n: int = MIN_N, threshold: float = HARVEST_THRESHOLD, holdout_threshold: float = HOLDOUT_THRESHOLD) -> dict` returning keys `mean_realized_vrp, mean_holdout, n, n_holdout, survives_walkforward, survives_window_gate`. **Descriptive means (`mean_realized_vrp`, `mean_holdout`) are computed whenever `n ≥ 1`** (conditioning evidence is exposed even for sub-`min_n` buckets per AC3); only the gate booleans depend on `min_n`. `survives_walkforward` requires `n ≥ min_n` AND full mean ≥ `threshold` AND holdout mean ≥ `holdout_threshold` AND both means positive.

- [ ] **Step 1: Write the failing unit test**

Create `tests/unit/test_vrp_markout_gates.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports import vrp_markout as vm


def _obs(values, start=date(2026, 1, 1)):
    """Build obs spaced 1 day apart so the quarter bucketing is well-defined."""
    return [
        {"market_date": start + timedelta(days=i), "realized_vrp": v}
        for i, v in enumerate(values)
    ]


def test_quarter_gate_passes_when_all_quarters_agree():
    obs = _obs([0.05] * 30)
    assert vm._survives_quarter_gate(obs, 0.05) is True


def test_quarter_gate_fails_on_larger_opposite_quarter():
    # Aggregate stays POSITIVE while Q1 reverses sign with LARGER magnitude.
    # (5*-0.10 + 30*0.05)/35 = +0.0286; Q1 mean -0.10 → |Q1| > |overall| → fail.
    q1 = _obs([-0.10] * 5, start=date(2026, 1, 1))    # Q1, mean -0.10
    q2 = _obs([0.05] * 30, start=date(2026, 4, 1))     # Q2, mean +0.05
    obs = q1 + q2
    overall = sum(o["realized_vrp"] for o in obs) / len(obs)
    assert overall > 0  # aggregate positive (the gate must still fail)
    assert vm._survives_quarter_gate(obs, overall) is False


def test_quarter_gate_fails_on_near_zero_aggregate():
    assert vm._survives_quarter_gate(_obs([0.0] * 10), 0.0) is False


def test_walkforward_below_min_n_still_reports_descriptive_mean():
    # AC3 / ISSUE-7: descriptive mean is computed even below min_n (conditioning
    # evidence stays legible); only the verdict gate is False.
    res = vm._walkforward_harvest(_obs([0.05] * 5))
    assert res["n"] == 5
    assert res["mean_realized_vrp"] == 0.05  # NOT None
    assert res["survives_walkforward"] is False  # n < min_n
    assert res["survives_window_gate"] is False


def test_walkforward_passes_positive_stable_harvest():
    res = vm._walkforward_harvest(_obs([0.05] * 40))
    assert res["n"] == 40
    assert res["n_holdout"] == 16  # round(40 * 0.40)
    assert res["mean_realized_vrp"] > 0
    assert res["mean_holdout"] > 0
    assert res["survives_walkforward"] is True
    assert res["survives_window_gate"] is True


def test_walkforward_fails_below_full_threshold():
    # positive but tiny (< 0.02) → full-sample magnitude floor fails
    res = vm._walkforward_harvest(_obs([0.005] * 40))
    assert res["mean_realized_vrp"] == 0.005  # still reported descriptively
    assert res["survives_walkforward"] is False


def test_walkforward_fails_when_holdout_below_floor():
    # ISSUE-3: full mean clears 0.02 but the holdout is positive yet immaterial
    # (< HOLDOUT_THRESHOLD 0.01). Without a holdout floor this would wrongly pass.
    vals = [0.05] * 24 + [0.005] * 16  # full=(1.2+0.08)/40=0.032; holdout=0.005
    res = vm._walkforward_harvest(_obs(vals))
    assert res["mean_realized_vrp"] > 0.02
    assert 0 < res["mean_holdout"] < 0.01
    assert res["survives_walkforward"] is False


def test_walkforward_fails_when_holdout_turns_negative():
    # full mean positive, but the latest 40% is negative → sign disagreement
    vals = [0.10] * 24 + [-0.05] * 16
    res = vm._walkforward_harvest(_obs(vals))
    assert res["mean_realized_vrp"] > 0
    assert res["mean_holdout"] < 0
    assert res["survives_walkforward"] is False


def test_walkforward_min_n_boundary():
    # ISSUE-9: verdict eligibility flips exactly at n == MIN_N (20).
    assert vm._walkforward_harvest(_obs([0.05] * 19))["survives_walkforward"] is False
    assert vm._walkforward_harvest(_obs([0.05] * 20))["survives_walkforward"] is True
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
uv run pytest tests/unit/test_vrp_markout_gates.py -v
```
Expected: FAIL — `AttributeError: module 'uw_scan.reports.vrp_markout' has no attribute '_survives_quarter_gate'`.

- [ ] **Step 3: Append the gate helpers**

First add the `defaultdict` import to the file's import block (first used here, by the quarter gate):

```python
from collections import defaultdict
```

Then append to `src/uw_scan/reports/vrp_markout.py` (after `_harvest_obs`, before any orchestration). Add the constants near the top with the other constants if you prefer — keep them grouped:

```python
# --- OOS hygiene (spec §Out-of-sample hygiene) ----------------------------
MIN_N = 20
HOLDOUT_FRAC = 0.40
HARVEST_THRESHOLD = 0.02   # full-sample floor: 2 vol points; decimal vols (iv/rv ~0.20).
HOLDOUT_THRESHOLD = 0.01   # relaxed holdout floor (~half), mirrors skew's 0.003/0.005 ratio.


def _survives_quarter_gate(obs: list[dict], overall_mean: float) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (standing rule:
    feedback_per_regime_catastrophic_gate; mirrors skew_markout's window gate).
    Fail if ANY quarter's mean realized_VRP reverses the aggregate sign with
    LARGER magnitude — the aggregate is hiding a sub-window blowup. A near-zero
    aggregate auto-fails (no stable edge to defend)."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple[int, int], list[float]] = defaultdict(list)
    for o in obs:
        d = o["market_date"]
        by_q[(d.year, (d.month - 1) // 3)].append(o["realized_vrp"])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def _walkforward_harvest(
    obs: list[dict],
    *,
    min_n: int = MIN_N,
    threshold: float = HARVEST_THRESHOLD,
    holdout_threshold: float = HOLDOUT_THRESHOLD,
) -> dict:
    """Walk-forward holdout on the ABSOLUTE harvest mean. The harvest claim is
    that mean realized_VRP is POSITIVE (selling rich vol earns premium).

    Descriptive means (mean_realized_vrp, mean_holdout) are ALWAYS computed when
    n >= 1 so a sub-min_n bucket still exposes conditioning evidence (AC3); only
    the gate booleans depend on min_n. survives_walkforward requires: n >= min_n,
    full mean >= threshold, holdout mean >= holdout_threshold, AND full and
    holdout means both positive (spec §OOS 'agree in sign and clear a magnitude
    floor'). survives_window_gate is the per-quarter gate on the full sample.
    Holdout = latest HOLDOUT_FRAC of obs by market_date (time-ordered, no leak).
    obs: [{'realized_vrp': float, 'market_date': date}]."""
    n = len(obs)
    if n == 0:
        return {
            "mean_realized_vrp": None,
            "mean_holdout": None,
            "n": 0,
            "n_holdout": 0,
            "survives_walkforward": False,
            "survives_window_gate": False,
        }
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o["realized_vrp"] for o in ordered) / n
    mean_hold = (
        sum(o["realized_vrp"] for o in holdout) / len(holdout) if holdout else None
    )
    if n < min_n:
        survives_wf = False
        survives_window = False
    else:
        sign_ok = mean_full > 0 and mean_hold is not None and mean_hold > 0
        mag_ok = mean_full >= threshold and (
            mean_hold is not None and mean_hold >= holdout_threshold
        )
        survives_wf = bool(sign_ok and mag_ok)
        survives_window = _survives_quarter_gate(ordered, mean_full)
    return {
        "mean_realized_vrp": mean_full,
        "mean_holdout": mean_hold,
        "n": n,
        "n_holdout": len(holdout),
        "survives_walkforward": survives_wf,
        "survives_window_gate": survives_window,
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
uv run pytest tests/unit/test_vrp_markout_gates.py -v
```
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/vrp_markout.py tests/unit/test_vrp_markout_gates.py
git commit -m "feat(vrp): walk-forward holdout + per-quarter catastrophic gate"
```

---

### Task 4: Orchestration — `run_vrp_markout`

**Files:**
- Modify: `src/uw_scan/reports/vrp_markout.py` (append orchestration + DB loaders)
- Test: `tests/integration/reports/test_vrp_markout.py`

**Interfaces:**
- Consumes: Task 1 (`repo.upsert_vrp_harvest_verdict`, `repo.fetch_known_earnings_dates`, `repo.fetch_watchlist_sector`), Task 2 (`_harvest_obs`), Task 3 (`_walkforward_harvest`), and `cards.skew_first_principles.asset_class_baseline`.
- Produces: `run_vrp_markout(*, repo: Repository, min_n: int = MIN_N) -> dict[str, Any]` returning `{"buckets_written": int, "tickers": int}` (`tickers` = the count actually scored, i.e. excluding single-names skipped for missing earnings coverage). Also `_all_vrp_tickers(repo) -> list[str]` and `_load_vrp_series(repo, ticker) -> list[dict]`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/reports/test_vrp_markout.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.reports.vrp_markout import run_vrp_markout


def _seed_vrp_daily(repo, ticker, rows):
    """rows: list of (market_date, iv, rv, vrp_z_20)."""
    repo.upsert_vrp_daily_rows(
        [
            {
                "ticker": ticker,
                "market_date": d,
                "iv": iv,
                "rv": rv,
                "vrp": (iv - rv),
                "vrp_z_20": z,
            }
            for (d, iv, rv, z) in rows
        ]
    )
    repo.conn.commit()


def _seed_macro(repo, ticker):
    """Tag the ticker 'Macro' so asset_class_baseline → index_macro — no earnings
    coverage needed, and the single_name earnings safeguard does not apply."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) VALUES (%s, 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL",
            (ticker,),
        )
    repo.conn.commit()


def _seed_earnings(repo, ticker, dates):
    """Seed flow_events earnings coverage (run_id FK + unique alert_id required)."""
    run_id = repo.insert_scan_run(ticker=ticker)
    with repo.conn.cursor() as cur:
        for i, d in enumerate(dates):
            cur.execute(
                f"INSERT INTO {repo._schema}.flow_events "
                "(run_id, alert_id, ticker, next_earnings_date) VALUES (%s, %s, %s, %s)",
                (run_id, f"a{i}", ticker, d),
            )
    repo.conn.commit()


def test_run_vrp_markout_marks_rich_bucket_sellable(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")  # index_macro → no earnings coverage required
    # 80 daily rows; RICH signal; iv 0.30, rv 0.20 → realized_VRP +0.10 (over the
    # 0.02 threshold). Scorable obs = anchors 0..59 (i+20 < 80) = 60.
    rows = [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)]
    _seed_vrp_daily(repo, "MACX", rows)

    out = run_vrp_markout(repo=repo)
    assert out["tickers"] >= 1

    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    rich = verdicts[("index_macro", "RICH")]
    assert rich["verdict"] == "HARVEST_SELLABLE"
    assert float(rich["mean_realized_vrp"]) > 0.02
    assert rich["survives_walkforward"] is True
    assert rich["survives_window_gate"] is True
    assert rich["confidence"] == "med"
    assert rich["n"] >= 20


def test_run_vrp_markout_flat_signal_is_none(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")
    # RICH signal but ZERO harvest (iv == rv) → mean 0 → NONE.
    rows = [(start + timedelta(days=i), 0.20, 0.20, 1.5) for i in range(80)]
    _seed_vrp_daily(repo, "MACX", rows)

    run_vrp_markout(repo=repo)
    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    assert verdicts[("index_macro", "RICH")]["verdict"] == "NONE"


def test_run_vrp_markout_excludes_earnings_windows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    panel = [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)]
    # Both single_name → SAME bucket. Both need earnings COVERAGE so the
    # safeguard does not skip them. CLEAN's earnings is far-future (no window
    # straddles it → 60 obs); ERN's is mid-series at index 10 (anchors 0..9
    # straddle it → 10 dropped → 50 obs).
    _seed_vrp_daily(repo, "CLEAN", panel)
    _seed_earnings(repo, "CLEAN", [date(2030, 1, 1)])
    _seed_vrp_daily(repo, "ERN", panel)
    _seed_earnings(repo, "ERN", [start + timedelta(days=10)])

    out = run_vrp_markout(repo=repo)
    assert out["tickers"] == 2
    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    # 60 (CLEAN, no drops) + 50 (ERN, 10 dropped) = 110, not 120.
    assert verdicts[("single_name", "RICH")]["n"] == 110


def test_run_vrp_markout_skips_single_name_without_earnings_coverage(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    rows = [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)]
    _seed_vrp_daily(repo, "NOFLOW", rows)  # single_name, NO flow_events earnings

    out = run_vrp_markout(repo=repo)
    # AC2 safeguard: cannot honor the earnings exclusion → skipped entirely.
    assert out["tickers"] == 0
    assert repo.fetch_vrp_harvest_verdicts() == []


def test_run_vrp_markout_exposes_rich_cheap_spread(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")  # index_macro (no earnings needed)
    # rv constant 0.20. RICH days (z=1.5) iv=0.30 → harvest 0.10; CHEAP days
    # (z=-1.5) iv=0.25 → harvest 0.05. spread = 0.10 - 0.05 = 0.05.
    rows = []
    for i in range(100):
        if i < 50:
            rows.append((start + timedelta(days=i), 0.30, 0.20, 1.5))
        else:
            rows.append((start + timedelta(days=i), 0.25, 0.20, -1.5))
    _seed_vrp_daily(repo, "MACX", rows)

    run_vrp_markout(repo=repo)
    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    rich = verdicts[("index_macro", "RICH")]
    cheap = verdicts[("index_macro", "CHEAP")]
    assert float(rich["mean_realized_vrp"]) == pytest.approx(0.10, abs=1e-9)
    assert float(cheap["mean_realized_vrp"]) == pytest.approx(0.05, abs=1e-9)
    # AC3: the RICH-CHEAP spread is exposed on every bucket row of the asset class.
    assert float(rich["rich_cheap_spread"]) == pytest.approx(0.05, abs=1e-9)
    assert float(cheap["rich_cheap_spread"]) == pytest.approx(0.05, abs=1e-9)


def test_run_vrp_markout_clears_stale_verdicts(seeded_db_empty_cards):
    # Full-rewrite guarantee: a bucket the current run does NOT produce must not
    # keep serving a stale prior verdict (the DELETE-then-insert in one txn).
    repo = seeded_db_empty_cards
    repo.upsert_vrp_harvest_verdict(
        asset_class="sector_etf",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.09,
        mean_holdout=0.08,
        rich_cheap_spread=0.04,
        n=99,
        n_holdout=40,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 1, 1),
    )
    repo.conn.commit()
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")  # current run only produces index_macro buckets
    _seed_vrp_daily(
        repo, "MACX",
        [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)],
    )

    run_vrp_markout(repo=repo)
    classes = {v["asset_class"] for v in repo.fetch_vrp_harvest_verdicts()}
    assert "sector_etf" not in classes  # stale row cleared by the full rewrite
    assert "index_macro" in classes
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/reports/test_vrp_markout.py -v
```
Expected: FAIL — `ImportError: cannot import name 'run_vrp_markout'`.

- [ ] **Step 3: Append the orchestration + DB loaders**

Append to `src/uw_scan/reports/vrp_markout.py`. Add the imports first used here to the top import block, and define the module logger. Final import block (stdlib grouped first, then local):

```python
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date as _date
from typing import Any

from uw_scan.cards.skew_first_principles import asset_class_baseline
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)
```

(That is the complete final import block for the module — `logging`, `typing.Any`, and the two local imports are new in this task; `_date` and `defaultdict` were added in Tasks 2/3. Place `log = logging.getLogger(__name__)` directly under the imports.) Then append the loaders + orchestration:

```python
def _all_vrp_tickers(repo: Repository) -> list[str]:
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT DISTINCT ticker FROM {repo._schema}.vrp_daily ORDER BY ticker"
        )
        return [r[0] for r in cur.fetchall()]


def _load_vrp_series(repo: Repository, ticker: str) -> list[dict]:
    sql = (
        "SELECT market_date, iv, rv, vrp_z_20 "
        f"FROM {repo._schema}.vrp_daily WHERE ticker = %s ORDER BY market_date ASC"
    )
    with repo.conn.cursor() as cur:
        cur.execute(sql, (ticker,))
        cols = [d.name for d in cur.description or []]
        return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]


def run_vrp_markout(*, repo: Repository, min_n: int = MIN_N) -> dict[str, Any]:
    """Score the realized VRP harvest per (asset_class, deviation_class) bucket
    and FULLY REWRITE vrp_harvest_verdicts (prior rows are cleared in the same
    transaction, so a bucket that loses all data never keeps serving a stale
    verdict). Idempotent. Read-only over vrp_daily + flow_events; writes verdicts.
    The decision consumer keys on the RICH bucket, but all buckets are scored and
    recorded so a flat (no-edge) result stays legible via mean_realized_vrp /
    rich_cheap_spread (spec §Verdict, kill criteria)."""
    today = _date.today()
    tickers = _all_vrp_tickers(repo)

    by_bucket: dict[tuple[str, str], list[dict]] = defaultdict(list)
    scored_tickers = 0
    for ticker in tickers:
        rows = _load_vrp_series(repo, ticker)
        if not rows:
            continue
        sector = repo.fetch_watchlist_sector(ticker)
        asset_class = asset_class_baseline(ticker, sector=sector)["asset_class"]
        earnings = repo.fetch_known_earnings_dates(ticker)
        # AC2 safeguard (design-decision note 1): a single_name with no
        # reconstructed earnings calendar cannot have its (t, t+20] earnings
        # windows excluded → it must NOT contribute (an unexcluded earnings
        # window inflates the harvest and would manufacture a false SELLABLE).
        # index_macro / sector_etf / credit legitimately have no earnings.
        if asset_class == "single_name" and not earnings:
            log.warning(
                "vrp_markout: skipping single_name %s — no earnings coverage "
                "to honor the (t, t+20] exclusion",
                ticker,
            )
            continue
        scored_tickers += 1
        for o in _harvest_obs(rows, earnings=earnings):
            by_bucket[(asset_class, o["deviation_class"])].append(o)

    scored: dict[tuple[str, str], dict] = {
        key: _walkforward_harvest(obs, min_n=min_n) for key, obs in by_bucket.items()
    }

    # rich_cheap_spread per asset class = mean(RICH) - mean(CHEAP); None if either
    # bucket is absent. Means are descriptive (computed for any n >= 1), so the
    # spread stays legible even for sub-min_n buckets. Attached to every bucket
    # row of the asset class.
    spread_by_ac: dict[str, float | None] = {}
    for ac in {ac for (ac, _dev) in by_bucket}:
        rich = scored.get((ac, "RICH"), {}).get("mean_realized_vrp")
        cheap = scored.get((ac, "CHEAP"), {}).get("mean_realized_vrp")
        spread_by_ac[ac] = (
            rich - cheap if rich is not None and cheap is not None else None
        )

    written = 0
    # Full rewrite: clear prior verdicts first, atomically with the re-inserts
    # (single commit at the end) so readers never see a partial set.
    with repo.conn.cursor() as cur:
        cur.execute(f"DELETE FROM {repo._schema}.vrp_harvest_verdicts")
    for (ac, dev), s in scored.items():
        survives_wf = bool(s["survives_walkforward"])
        survives_gate = bool(s["survives_window_gate"])
        verdict = "HARVEST_SELLABLE" if (survives_wf and survives_gate) else "NONE"
        repo.upsert_vrp_harvest_verdict(
            asset_class=ac,
            deviation_class=dev,
            verdict=verdict,
            mean_realized_vrp=s["mean_realized_vrp"],
            mean_holdout=s["mean_holdout"],
            rich_cheap_spread=spread_by_ac.get(ac),
            n=s["n"],
            n_holdout=s["n_holdout"],
            survives_walkforward=survives_wf,
            survives_window_gate=survives_gate,
            confidence="med" if verdict == "HARVEST_SELLABLE" else None,
            as_of=today,
        )
        written += 1
    repo.conn.commit()
    return {"buckets_written": written, "tickers": scored_tickers}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/reports/test_vrp_markout.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full new suite so far + lint guardrail**

Run:
```bash
uv run pytest tests/unit/test_vrp_markout_helpers.py tests/unit/test_vrp_markout_gates.py -v
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/storage/test_vrp_markout_storage.py tests/integration/reports/test_vrp_markout.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/vrp_markout.py tests/integration/reports/test_vrp_markout.py
git commit -m "feat(vrp): markout orchestration over vrp_daily panel"
```

---

### Task 5: Worker job + scheduler registration

**Files:**
- Create: `src/uw_scan/worker/jobs/vrp_markout.py`
- Modify: `src/uw_scan/worker/scheduler.py` (import near line 54; wrapper near the skew markout wrapper ~line 428; registration after the skew markout block ~line 809)
- Test: `tests/integration/worker/test_vrp_markout_job.py`

**Interfaces:**
- Consumes: Task 4 (`run_vrp_markout`).
- Produces: `vrp_markout_refresh(*, repo: Repository) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing job test**

Create `tests/integration/worker/test_vrp_markout_job.py`:

```python
from __future__ import annotations

from datetime import date, timedelta

from uw_scan.worker.jobs.vrp_markout import vrp_markout_refresh


def test_vrp_markout_refresh_writes_verdicts(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    # Tag MACX 'Macro' → index_macro (the single_name earnings safeguard skips
    # single-names with no flow_events coverage; index_macro needs none).
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) "
            "VALUES ('MACX', 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
    repo.upsert_vrp_daily_rows(
        [
            {
                "ticker": "MACX",
                "market_date": start + timedelta(days=i),
                "iv": 0.30,
                "rv": 0.20,
                "vrp": 0.10,
                "vrp_z_20": 1.5,
            }
            for i in range(80)
        ]
    )
    repo.conn.commit()

    out = vrp_markout_refresh(repo=repo)
    assert out["buckets_written"] >= 1
    assert out["tickers"] >= 1
    verdicts = repo.fetch_vrp_harvest_verdicts()
    assert any(v["verdict"] == "HARVEST_SELLABLE" for v in verdicts)
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/worker/test_vrp_markout_job.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.worker.jobs.vrp_markout'`.

- [ ] **Step 3: Write the job wrapper**

Create `src/uw_scan/worker/jobs/vrp_markout.py`:

```python
"""VRP harvest markout job (Spec B) — thin scheduler wrapper."""

from __future__ import annotations

import logging
from typing import Any

from uw_scan.reports.vrp_markout import run_vrp_markout
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)


def vrp_markout_refresh(*, repo: Repository) -> dict[str, Any]:
    """Re-score the realized VRP harvest per bucket and (re)write
    vrp_harvest_verdicts. Pure compute over the warm store; idempotent."""
    counts = run_vrp_markout(repo=repo)
    log.info(
        "vrp_markout_refresh: %d buckets over %d tickers",
        counts.get("buckets_written", 0),
        counts.get("tickers", 0),
    )
    return counts
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/worker/test_vrp_markout_job.py -v
```
Expected: PASS.

- [ ] **Step 5: Register the job in the scheduler**

In `src/uw_scan/worker/scheduler.py`:

(a) Add the import next to the skew markout job import (the file imports `skew_markout_refresh` around line 54):
```python
from uw_scan.worker.jobs.vrp_markout import vrp_markout_refresh
```

(b) Add the wrapper next to `_skew_markout_refresh` (around line 428):
```python
    def _vrp_markout_refresh() -> None:
        with _repo(settings) as repo:
            vrp_markout_refresh(repo=repo)
```

(c) Register it immediately AFTER the existing skew markout `sched.add_job(...)` block (around line 809) — it sits inside the same `if "massive" in groups:` → `if _is_primary_worker(settings):` scope as skew markout. Run it 5 minutes after skew markout (18:45 → 18:50) so the nightly compute jobs stay ordered:
```python
            # VRP harvest markout at 18:50 ET — aligned with the skew markout
            # (18:45). Pure compute over vrp_daily; idempotent. Scores whether
            # selling rich vol earns a reliable premium per bucket (Spec B).
            sched.add_job(
                _vrp_markout_refresh,
                CronTrigger.from_crontab("50 18 * * 0-4", timezone=settings.rth_tz),
                id="vrp_markout_refresh",
                name="VRP harvest markout verdict refresh",
                max_instances=1,
                coalesce=True,
            )
```

- [ ] **Step 6: Verify the scheduler still imports cleanly**

Run:
```bash
uv run python -c "import uw_scan.worker.scheduler as s; print('scheduler imports OK')"
```
Expected: `scheduler imports OK` (no ImportError).

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/worker/jobs/vrp_markout.py src/uw_scan/worker/scheduler.py \
        tests/integration/worker/test_vrp_markout_job.py
git commit -m "feat(vrp): nightly markout job + scheduler wiring (18:50 ET, massive-0)"
```

---

### Task 6: API endpoint + response models + generated-file regen

**Files:**
- Modify: `src/uw_scan/api/schemas.py` (add models near the other regime responses)
- Modify: `src/uw_scan/api/routers/regime.py` (import + endpoint)
- Modify: `tests/integration/api/openapi.snapshot.json` (regenerate)
- Modify: `web/lib/types.ts` (regenerate)
- Test: `tests/integration/api/test_vrp_harvest_endpoint.py`

**Interfaces:**
- Consumes: Task 1 (`repo.fetch_vrp_harvest_verdicts`).
- Produces: `GET /api/regime/vrp-harvest` → `VrpHarvestResponse`.

- [ ] **Step 1: Write the failing endpoint test**

Create `tests/integration/api/test_vrp_harvest_endpoint.py`:

```python
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


def test_vrp_harvest_endpoint_returns_seeded_verdicts(
    client: TestClient, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_vrp_harvest_verdict(
        asset_class="single_name",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.031,
        mean_holdout=0.028,
        rich_cheap_spread=0.015,
        n=42,
        n_holdout=17,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 6, 21),
    )
    repo.conn.commit()

    res = client.get("/api/regime/vrp-harvest")
    assert res.status_code == 200
    body = res.json()
    assert "verdicts" in body
    assert len(body["verdicts"]) == 1
    v = body["verdicts"][0]
    assert v["asset_class"] == "single_name"
    assert v["deviation_class"] == "RICH"
    assert v["verdict"] == "HARVEST_SELLABLE"
    assert v["mean_realized_vrp"] == 0.031
    assert v["n"] == 42


def test_vrp_harvest_endpoint_empty_is_ok(client: TestClient, seeded_db_empty_cards):
    res = client.get("/api/regime/vrp-harvest")
    assert res.status_code == 200
    assert res.json() == {"verdicts": []}
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/api/test_vrp_harvest_endpoint.py -v
```
Expected: FAIL — 404 (route not registered).

- [ ] **Step 3: Add the response models**

In `src/uw_scan/api/schemas.py`, add near the other regime response models (e.g. after `VolBackdropResponse`):

```python
class VrpHarvestVerdict(BaseModel):
    """One (asset_class, deviation_class) VRP harvest bucket verdict (Spec B)."""

    asset_class: str
    deviation_class: str
    verdict: str  # "HARVEST_SELLABLE" | "NONE"
    mean_realized_vrp: float | None = None
    mean_holdout: float | None = None
    rich_cheap_spread: float | None = None
    n: int = 0
    n_holdout: int = 0
    survives_walkforward: bool = False
    survives_window_gate: bool = False
    confidence: str | None = None
    as_of: date | None = None


class VrpHarvestResponse(BaseModel):
    """VRP harvest markout verdicts — is rich vol sellable, by bucket (Spec B)."""

    verdicts: list[VrpHarvestVerdict] = Field(default_factory=list)
```

(`date` and `Field` are already imported at the top of `schemas.py`.)

- [ ] **Step 4: Add the endpoint**

In `src/uw_scan/api/routers/regime.py`, extend the `from uw_scan.api.schemas import (...)` block to include the two new names:

```python
    VrpHarvestResponse,
    VrpHarvestVerdict,
```

Then add the endpoint (place it near the other simple GET endpoints):

```python
@router.get("/vrp-harvest", response_model=VrpHarvestResponse)
def get_vrp_harvest(
    repo: Annotated[Repository, Depends(get_repo)],
) -> VrpHarvestResponse:
    """Per-bucket VRP harvest verdicts (Spec B). Read-only over the verdict
    store written by the nightly vrp_markout job."""
    rows = repo.fetch_vrp_harvest_verdicts()
    return VrpHarvestResponse(verdicts=[VrpHarvestVerdict(**r) for r in rows])
```

- [ ] **Step 5: Run the endpoint test to verify it passes**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/api/test_vrp_harvest_endpoint.py -v
```
Expected: PASS (2 tests).

- [ ] **Step 6: Regenerate the OpenAPI snapshot**

The snapshot test (`tests/integration/api/test_openapi_snapshot.py`) now fails because a new path + two new component schemas exist. Regenerate the snapshot (the existing file is `indent=2`, `sort_keys=True`, `ensure_ascii=True`, no trailing newline):

```bash
uv run python -c "
import json
from pathlib import Path
from uw_scan.api.server import create_app
spec = create_app().openapi()
p = Path('tests/integration/api/openapi.snapshot.json')
p.write_text(json.dumps(spec, sort_keys=True, ensure_ascii=True, indent=2))
print('snapshot regenerated')
"
```

Then verify ONLY the intended additions changed (new `VrpHarvestResponse`/`VrpHarvestVerdict` schemas + the `/api/regime/vrp-harvest` path):
```bash
git diff --stat tests/integration/api/openapi.snapshot.json
git diff tests/integration/api/openapi.snapshot.json | grep -i "vrp\|vrp-harvest" | head
```
Expected: the diff touches only VRP-related schema/path lines (sorted into place). If the diff reorders thousands of unrelated lines, STOP — the serialization settings don't match the existing file; reconcile before continuing.

- [ ] **Step 7: Run the snapshot test**

Run:
```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```
Expected: PASS.

- [ ] **Step 8: Regenerate the frontend types**

`npm run gen:types` is `openapi-typescript http://127.0.0.1:8400/openapi.json -o lib/types.ts` — it needs the API server running on :8400. If the dev stack (`bash scripts/dev.sh`) is already up, just run `gen:types`. Otherwise start a throwaway API first:

```bash
# Start a throwaway API on :8400 (only if the dev stack isn't already running)
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_local \
  uv run uvicorn "uw_scan.api.server:create_app" --factory --port 8400 &
API_PID=$!
# wait for it to answer, then regenerate types
until curl -sf http://127.0.0.1:8400/openapi.json >/dev/null; do sleep 0.5; done
cd web && npm run gen:types && cd ..
kill "$API_PID" 2>/dev/null
git diff --stat web/lib/types.ts
```
Expected: `web/lib/types.ts` gains `VrpHarvestResponse` / `VrpHarvestVerdict` types and the new path. Per the generated-files memory, add fields surgically — if `gen:types` reorders the whole file, do not hand-fix; the script output is canonical, but confirm the diff is scoped to the new types.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/api/schemas.py src/uw_scan/api/routers/regime.py \
        tests/integration/api/test_vrp_harvest_endpoint.py \
        tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(vrp): GET /api/regime/vrp-harvest endpoint + response models"
```

---

### Task 7: Documentation + AGENTS.md sync

**Files:**
- Modify: `CLAUDE.md` (the "Where to look first" table + a one-line mention)
- Modify: `src/uw_scan/worker/CLAUDE.md` (the Schedule table)
- Modify: `AGENTS.md` (keep in sync with `CLAUDE.md` per standing rule)

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a "Where to look first" row in `CLAUDE.md`**

Add a row to the table (near the skew / regime rows):

```markdown
| VRP harvest markout (is rich vol sellable) | `src/uw_scan/reports/vrp_markout.py` + `storage/vrp_markout.py` + `worker/jobs/vrp_markout.py` + `api/routers/regime.py` (`/vrp-harvest`) + migration `079`; nightly 18:50 ET (massive-0); spec `docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md` |
```

- [ ] **Step 2: Add the schedule row in `src/uw_scan/worker/CLAUDE.md`**

Add to the Schedule table (after the `option_surface_*` rows / near `skew` jobs):

```markdown
| `vrp_markout_refresh` | cron | `50 18 * * 0-4` (massive-0; VRP harvest verdicts over vrp_daily) |
```

- [ ] **Step 3: Mirror the `CLAUDE.md` change into `AGENTS.md`**

Apply the same "Where to look first" row addition to `AGENTS.md` so the two stay in sync (standing rule). If `AGENTS.md` does not carry that table, add an equivalent one-line pointer in the closest matching section.

- [ ] **Step 4: Verify docs reference only real paths**

Run:
```bash
for p in src/uw_scan/reports/vrp_markout.py src/uw_scan/storage/vrp_markout.py \
         src/uw_scan/worker/jobs/vrp_markout.py \
         src/uw_scan/storage/migrations/079_vrp_harvest_verdicts.sql \
         docs/superpowers/specs/2026-06-19-vrp-harvest-markout-design.md; do
  test -e "$p" && echo "OK  $p" || echo "MISSING  $p"
done
```
Expected: all `OK`.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md src/uw_scan/worker/CLAUDE.md AGENTS.md
git commit -m "docs(vrp): CLAUDE.md/AGENTS.md pointers + worker schedule row"
```

---

## Final verification (run after all tasks)

- [ ] **Full new-feature suite:**

```bash
uv run pytest tests/unit/test_vrp_markout_helpers.py tests/unit/test_vrp_markout_gates.py -v
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_test UW_SCAN_TEST_DB_NAME=option_wizard_test \
  uv run pytest \
    tests/integration/storage/test_vrp_markout_storage.py \
    tests/integration/reports/test_vrp_markout.py \
    tests/integration/worker/test_vrp_markout_job.py \
    tests/integration/api/test_vrp_harvest_endpoint.py \
    tests/integration/api/test_openapi_snapshot.py -v
```
Expected: all PASS.

- [ ] **Models-export guard** (only relevant if the `models/` route was taken; we used `api/schemas.py`, so this should be unaffected — run to confirm no regression):

```bash
uv run pytest tests/unit/test_models_exports.py -v
```

- [ ] **Migration idempotency** — re-running migrations is a no-op:

```bash
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_local bash scripts/migrate.sh
# run twice; second run must not error
UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi UW_SCAN_DB_NAME=option_wizard_local bash scripts/migrate.sh
```

> **Deployment note (not a code task):** verdicts only populate once the nightly `vrp_markout_refresh` runs on the mini (18:50 ET, massive-0) — OR after a one-off manual `run_vrp_markout(repo=...)` against the warm store. Unlike the EOD surface recorder, there is no forward-accrual wait: the markout produces a full verdict set on its first run from the existing ~13-month `vrp_daily` panel.

---

## Self-Review (completed during plan authoring)

**1. Spec coverage:**
- §Signal (RICH/NORMAL/CHEAP) → Task 2 `_deviation_class`. ✓
- §Forward target (`IV(t) − RV(t+20)`, trailing-21d approximation) → Task 2 `_harvest_obs`; fallback explicitly deferred (design-decision note 2). ✓
- §Earnings exclusion → Task 1 `fetch_known_earnings_dates` + Task 2 `_earnings_in_window`/`_harvest_obs`; source reconciliation in design-decision note 1. ✓
- §Bucketing `(asset_class, deviation_class)` → Task 4 (reuses `asset_class_baseline`). ✓
- §Scoring (absolute mean + RICH−CHEAP spread) → Task 4. ✓
- §OOS hygiene (walk-forward holdout 40% + per-quarter gate) → Task 3. ✓
- §Verdict (`HARVEST_SELLABLE`/`NONE`, n≥20, >0.02, WF, gate, conf capped "med") → Task 3 + Task 4. ✓
- §Components 1–4 (report module, verdict table + mixin, nightly job, API endpoint) → Tasks 2-4 / 1 / 5 / 6. ✓
- §Testing (unit: realized_VRP, earnings boundary, bucket thresholds, WF + gate; integration: positive RICH → SELLABLE, flatten → NONE) → Tasks 2,3,4,6. ✓
- §Acceptance criteria 1–4 → covered by Task 4 (writes a verdict per bucket), Task 2/4 (earnings exclusion test-verified), Task 3/4 (full gate chain + spread exposed), Task 6 (endpoint). ✓
- §Non-goals respected: no UI card, no directional/ΔVRP test, no per-strike dependency, no price fallback. ✓

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code. ✓

**3. Type consistency:** `upsert_vrp_harvest_verdict` kwargs (Task 1) match the call site (Task 4), the response model fields (Task 6), and the table columns (Task 1 migration). `_harvest_obs` obs keys (`market_date`/`deviation_class`/`realized_vrp`) are consumed unchanged by `_walkforward_harvest`/`_survives_quarter_gate` (Task 3) and `run_vrp_markout` (Task 4). `_harvest_obs` reads the forward RV by positional index (`ordered[i + HORIZON]`) over the full per-ticker series — no `_forward_row_at` helper (removed in review; an interior null RV must not shift the exact `t+20` target). `_walkforward_harvest` returns descriptive means for any `n ≥ 1`; `mean_realized_vrp`/`mean_holdout` may be `None` only when the bucket/holdout is empty, and the storage column is nullable NUMERIC + the response field is `float | None`. ✓
