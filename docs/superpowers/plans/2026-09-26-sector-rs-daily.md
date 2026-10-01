# Sector RS daily Implementation Plan

> **For agentic workers:** execute with the user's `/execute-plan` skill (one linear thread, milestone commits). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Persist nightly sector relative strength (RS) and breadth for the 11 GICS sectors (SPDR ETF vs SPY, breadth over current S&P 500 members) and for every `watchlist_chain` chain (equal-weighted), backfill it from 1998-12-22 (the SPDR funds' first bar after livewire #157), and ship the pre-registered §6 breadth probe script. No UI, no router.

**Architecture:** One pure compute module (`reports/sector_rs.py`) is called by one job core (`worker/jobs/sector_rs_daily.run_sector_rs`), which is shared by the nightly massive-0 job and the resumable backfill script. Bars come from apex's bulk route `GET /v1/equity/bars` (≤200 symbols per call, adjusted, `listing=any`; delisted names land in `missing` and stay unpriced), with a `daily_ohlc` fallback for SPY and the 11 ETFs only. S&P 500 membership is a vendored current list (`src/uw_scan/sources/data/sp500_members.json`, copied from livewire `presets/sp500.json` by `scripts/research/sync_sp500_members.py`); argon never calls apex's membership route. The list is applied to every session, nightly and backfill alike, so breadth history is survivorship-biased by construction. Rows land in `uw_scan.sector_rs_daily` (migration 152) through a standalone repository module.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, httpx, APScheduler 3, pytest + pytest-postgresql.

**Spec:** docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md

## Global Constraints

- `uv` only: `uv run pytest`, `uv run python`, `uv run ruff`. No bare `python`, `pip`, or activated venvs.
- Migrations are idempotent (`CREATE TABLE IF NOT EXISTS`) and start with `SET search_path TO uw_scan, public;` (`src/uw_scan/storage/migrations/README.md`).
- Never extend `storage/repository.py` with query methods. New persistence goes in its own module (`storage/sector_rs.py`). Like `CompanySectorRepository` and `WatchlistChainRepository`, it is standalone and needs no assembly into `Repository`.
- No Yahoo anywhere. `scripts/check_no_yahoo.py` runs in CI.
- Tests use frozen REAL closes with the as-of date in the fixture name. No network at test time: apex is reached only through `httpx.MockTransport` or injected stub fetchers.
- Module size target is under 500 lines per Python file. `sources/apex.py` goes from 349 to about 430 lines.
- The CHANGELOG `[Unreleased]` entry rides this PR (Task 9).
- Branch name: `feat/sector-rs-daily`, in the worktree `.worktrees/feat-sector-rs-daily/`.
- Never commit without an explicit request. The commit steps below run only because the user invokes `/execute-plan`, which commits milestones. No `Co-Authored-By` trailer.
- Persist every research result before the process exits. The probe writes `VERDICT.md`, `results.csv` and `observations.csv`. The backfill writes to the table itself.
- Defined-risk only: nothing here is a trade signal (spec §1), so no order path is touched.

## Review Focus

Five failure modes the spec implies. Tests on the happy path would miss each of them, so each is pinned to a named test:

1. **A member delisted mid-window must not be priced on a stale window.** Windows are anchored on SPY's session dates, not on each member's own last N+1 closes. A member without a close on the as-of session is unpriced for every window. Test: Task 2 `test_member_delisted_mid_window_is_not_priced_on_a_stale_window`.
2. **An ETF missing from both apex and `daily_ohlc` produces NULL RS and `degraded=true`, never 0.** Breadth is still computed and written. Tests: Task 2 `test_missing_etf_gives_null_rs_and_degraded_but_keeps_breadth`. Task 6 `test_other_ten_sectors_write_null_rs_rows_when_their_etf_is_absent` covers the fallback returning nothing.
3. **A 1-member chain is legal.** Breadth is 0 or 1, and the row is not degraded when the member is priced. Test: Task 2 `test_single_member_group`.
4. **SPY missing (apex and `daily_ohlc` both) aborts the whole run before any write.** The same holds for SPY too short for the 12m window on the earliest requested session. Tests: Task 2 `test_missing_or_short_benchmark_raises`, Task 6 `test_spy_missing_everywhere_aborts_without_writing` and `test_spy_too_short_for_earliest_session_aborts_without_writing`.
5. **An `as_of` on a non-trading day writes rows labelled with the last SPY session, not the calendar date.** A Saturday run must not create a duplicate row next to Friday's. Tests: Task 2 `test_non_trading_as_of_uses_the_last_session`, Task 6 `test_saturday_as_of_writes_friday_rows`.

Three more, from the code or the apex contract rather than the spec:

6. **A vendored S&P 500 list that fails validation aborts the `gics` kind with a logged error; it never writes 11 rows with `n_members=0`.** Failing validation means duplicates, fewer than 450 names, or an unreadable file. Chain rows still write. Tests: Task 6 `test_invalid_vendored_list_aborts_gics_with_error_and_chain_still_writes`; for the validator itself, Task 4 `test_validate_rejects_duplicates_and_short_lists`.
7. **Widening `company_sector_refresh` must not change the existing tests' universe.** The list is static and needs no network, but the widening stays opt-in (`include_sp500=False` by default). With it on, 503 extra names sorting ahead of the `ZZ*` test tickers would push those tickers out of capped runs. Only the scheduler passes `True`. Tests: Task 5 `test_default_does_not_widen`, plus the unchanged `tests/integration/worker/test_company_type_routing.py`.
8. **A delisted member in apex's `missing` map reduces `n_priced`, never becomes a zero return.** It is still counted in `n_members` when membership lists it, and it is not re-fetched raw. Tests: Task 4 `test_nested_shape_parses_and_missing_symbols_are_absent` (the client drops it) and Task 2 `test_member_absent_from_closes_is_unpriced_not_zero` (the compute counts it as unpriced).

## Verified facts this plan relies on (2026-09-26)

- **ETF history (livewire #157, corrected 2026-09-27, spec §4).** Silver as served by apex adjusted bars (rev 81): XLV, XLI, XLP first_date 1998-12-22 and clean; XLRE 2015-10-08 and XLC 2018-06-19 clean; XLF from 1998-12-22 but WRONG before 2016-09-19 (XLRE spin-off double-booked, false +31% jump on 2016-09-19); XLK, XLY, XLB, XLU, XLE still start 2021-06-11 (seam check cut the IB bars; fix in progress). SPY starts 1993-01-29. The five cut funds need no code (no bars → NULL rs → degraded; `--force` re-run later). XLF needs `GroupSpec.rs_valid_from` (Task 2) with the single entry in Task 6's `ETF_RS_VALID_FROM`; the backfill's pre-flight (Task 7) checks all nine 1998 funds. The full default backfill is about 7,000 sessions (1998-12-22 → present).
- **apex REST bulk bars.** The route exists in apex ≥ 0.1.12. I read it at apex `origin/master` (0.1.13) and probed it live on the mini on 2026-09-26. `GET /v1/equity/bars?symbols=A,B,C&timeframe=1d&start=&end=&limit=&price_mode=&listing=&silver_revision=` (`src/api/routes/bulk_bars.py` → `src/application/lake/bulk.py::query_bulk_bars`):
  - Equity only, with no `{asset_class}` segment.
  - `symbols` is comma-separated, 1–200 after upper-case dedupe (`BULK_MAX_SYMBOLS = 200`); more is a 400 `invalid_parameter`.
  - `start`/`end` must carry a UTC offset. A bare date or naive timestamp is a 400; reproduced live: `"start must carry a UTC offset (got '2026-09-10T00:00:00'); use e.g. 2026-09-10T00:00:00Z"`.
  - An explicit `start` is honoured as-is and switches the tail-slice off (`guards.resolve_window` returns `tail=None`), so `limit=0` returns every row in the window and `truncated` is false.
  - `listing=delisted&price_mode=adjusted` fails the whole call with a 400 `adjusted_not_supported`.
  - Response: `{price_mode, basis, adjustment_revision, silver_revision, timeframe, window, generated_at, symbols: {SYM: {listing_status, truncated, bars: [{time, open, high, low, close, volume}]}}, missing: {SYM: reason}}`. `symbols` is a nested dict and `missing` a dict.
  - A per-symbol failure (no artifact, no Silver, query timeout) goes to `missing`, and the call still returns 200. Request-level faults fail the call.
  - One Silver revision is pinned per call. Measured by the apex session: 200 symbols × 1 year adjusted took 4.0 s and returned 49,281 rows.
  - The first draft of this plan said this route did not exist. My local apex checkout (`/Users/chenxi/projects/apex`, `master` at 0.1.8, 2026-09-16) predates it.
- **Delisted names are unpriced (ruling, spec §4).** livewire adjusts only listed names. `listing=any&price_mode=adjusted` files a delisted symbol under `missing`, e.g. live 2026-09-26: `"TWTR": "no Silver for delisted names; use price_mode=raw"`. The plan does NOT fetch raw for them. They count in `n_members` if membership lists them, never in `n_priced`, and never as a zero return.
- **Membership is a vendored list; argon does not call apex's membership route (ruling, spec §4).** On 2026-09-26 (coordinator-verified), `GET /v1/membership/sp500` returned 485 rows: about 35 with `symbol: null`, dead tickers (BHGE, SBC, PKI, FISV, Q, FDXF, HONA, MRSH, VMRK), and META, XOM, AVGO, LIN, MDT and ETN missing. Before 2026-09-17 it also returns about half the index. livewire's `presets/sp500.json` is clean: 503 unique tickers including META, XOM, AVGO, BRK.B and BF.B, at local livewire HEAD `471e963aac82f6b3590f721160c70b99100d670b`. Its own `source` field reads "S&P 500 GICS classification (Wikipedia, March 2026)". It is not in the lake mount the argon container sees, so it is copied into `src/uw_scan/sources/data/sp500_members.json` and shipped as package data. The per-package `data/` layout follows the existing `"uw_scan.cards" = ["data/*.json", ...]` entry (`pyproject.toml:76-81`), which is read through `importlib.resources.files` (`cards/canary_calibration.py:13-14`). The app image runs `uv sync` over a copied `src/` (`docker/app.Dockerfile:28,32,47`). The current list is applied to every session, so breadth history is survivorship-biased by construction.
- **All 11 vendor labels exist in `company_sector.sector`** (queried against `option_wizard_local` 2026-09-26): Technology, Industrials, Healthcare, Financial Services, Communication Services, Consumer Cyclical, Utilities, Real Estate, Consumer Defensive, Energy, Basic Materials. There were also 26 NULL rows.
- **Real closes for the fixture window** (apex adjusted, `adjustment_revision` 80): 260 sessions from 2025-09-08 to 2026-09-18, with identical date lists for SPY, XLK, AAPL, MSFT and NVDA. Measured returns to 2026-09-18:

  | series        | 1m (%) | 3m (%) | 12m (%) |
  | ------------- | ------ | ------ | ------- |
  | SPY           | -0.712 | 2.255  | 17.122  |
  | XLK           | 3.245  | -0.843 | 40.437  |
  | MSFT          | 2.147  | —      | -2.388  |
  | XLK RS vs SPY | 3.958  | -3.098 | 23.315  |
  | AAPL/MSFT/NVDA equal-weight RS | — | — | ≈ 6.083 |

- **Registry gate:** `tests/integration/worker/test_data_gap_full_coverage.py::test_zero_unregistered_after_full_registry` fails as soon as a new DATE-keyed table exists without a `REGISTRY` row. For that reason the registry, policy-doc and freshness enrolment ride Task 1 with the migration, not a later task. `audit_mode="excluded"` (a member of `BY_DESIGN_AUDIT_MODES`, `data_gap_healer.py:42`) is used because the spec says the table is not healer-enrolled. `freshness_only` would change the coverage-ledger count asserted at `tests/unit/reports/test_full_coverage.py` (59) and require an adapter or a dated refusal.

---

### Task 1: Migration 152 + dataset registry + policy doc + freshness enrolment

**Files**
- Create: `src/uw_scan/storage/migrations/152_sector_rs_daily.sql`
- Modify: `src/uw_scan/reports/data_gap_healer.py`. Insert a `DatasetRegistryEntry` directly after the `macro_release_calendar` entry, which closes at line 312 with `),`.
- Modify: `src/uw_scan/reports/data_freshness.py`. Insert a `MonitoredTable` before the closing `]` of `MONITORED_TABLES` at line 288.
- Modify: `docs/runbooks/data-gap-dataset-policy.md`. It is regenerated, never hand-edited.
- Create: `tests/unit/reports/test_sector_rs_freshness_enrolled.py`

**Interfaces**
- Consumes: `DatasetRegistryEntry` (`data_gap_healer.py:84`), `MonitoredTable` (`data_freshness.py:62`), `render_dataset_policy_markdown`.
- Produces: table `uw_scan.sector_rs_daily`; `REGISTRY` row `sector_rs_daily`; `MONITORED_TABLES` row `sector_rs_daily`.

- [ ] **Step 1: Write the failing test** at `tests/unit/reports/test_sector_rs_freshness_enrolled.py`

```python
"""sector_rs_daily (migration 152) must be visible to both table gates.

A new DATE-keyed table needs a REGISTRY row, or
tests/integration/worker/test_data_gap_full_coverage.py fails on it as
unregistered. It also needs a MONITORED_TABLES row, or /api/health never
measures its data date. Its date column is `as_of`, which is absent from
_DATE_COL_PREFERENCE, so the override is mandatory.
"""

from uw_scan.reports.data_freshness import MONITORED_TABLES
from uw_scan.reports.data_gap_healer import REGISTRY


def test_sector_rs_daily_is_monitored():
    entry = next((m for m in MONITORED_TABLES if m.name == "sector_rs_daily"), None)
    assert entry is not None, "sector_rs_daily missing from MONITORED_TABLES"
    assert entry.date_col_override == "as_of"


def test_sector_rs_daily_is_registered_and_not_healer_enrolled():
    entry = next((e for e in REGISTRY if e.table_name == "sector_rs_daily"), None)
    assert entry is not None, "sector_rs_daily missing from REGISTRY"
    # spec §5: the backfill script is the heal; the healer never dispatches it
    assert entry.audit_mode == "excluded"
    assert entry.healer_adapter is None
    assert entry.date_col == "as_of"
    assert entry.ticker_col is None
    assert "sector_rs_backfill.py" in (entry.reason or "")
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/unit/reports/test_sector_rs_freshness_enrolled.py -q
```
Expected: 2 failed, with `AssertionError: sector_rs_daily missing from MONITORED_TABLES` and `... missing from REGISTRY`.

- [ ] **Step 3: Create the migration** `src/uw_scan/storage/migrations/152_sector_rs_daily.sql`. The DDL is copied verbatim from spec §3.

```sql
-- 152_sector_rs_daily.sql — sector relative strength + breadth, one row per
-- (as_of, group_kind, group_key).
-- Spec: docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md §3.
--
-- Two group kinds share the table and are never joined:
--   gics  — the 11 SPDR sector ETFs. RS = the ETF's adjusted close return minus
--           SPY's; breadth over CURRENT S&P 500 members (applied to every
--           session: survivorship-biased, spec §4) mapped through
--           company_sector (vendor vocabulary).
--   chain — every watchlist_chain chain, equal-weighted member return minus SPY.
-- The vendor `Energy` (oil and gas) and argon's chain `Energy` (power infra)
-- are different groups for exactly that reason — see migration 123's header.
--
-- Units: rs_* are percentage points (group return − SPY return, not a ratio);
-- breadth_* are fractions in [0, 1] (members beating SPY / members priced for
-- that window). n_priced is the 12m count only. A `degraded` row is still
-- written — it is the coverage statement (n_priced < 0.8 × n_members, no
-- members, or the 12m RS input missing).
--
-- Writers: worker/jobs/sector_rs_daily.py (nightly 21:30 ET Mon–Fri,
-- massive-0, flag UW_SCAN_SECTOR_RS_ENABLED) and
-- scripts/backfill/sector_rs_backfill.py, both through
-- storage/sector_rs.SectorRsRepository.upsert_rows (ON CONFLICT DO UPDATE on
-- every column, so re-runs and backfills converge on the same row).
--
-- Idempotent: IF NOT EXISTS.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.sector_rs_daily (
    as_of          DATE NOT NULL,
    group_kind     TEXT NOT NULL CHECK (group_kind IN ('gics','chain')),
    group_key      TEXT NOT NULL,          -- 'Technology' | 'Semi-Logic' ...
    weighting      TEXT NOT NULL CHECK (weighting IN ('etf','equal')),
    rs_symbol      TEXT,                   -- 'XLK' for etf rows, NULL for equal
    n_members      INTEGER NOT NULL,       -- constituents in the group at as_of
    n_classified   INTEGER NOT NULL,       -- == n_members for both kinds today (a member with a NULL sector belongs to no group; the index-level unclassified count is a job counter, acceptance §9.3). Kept so a future multi-source label can report partial coverage per row
    n_priced       INTEGER NOT NULL,       -- members with a full 252-bar window
    rs_1m  DOUBLE PRECISION, rs_3m  DOUBLE PRECISION, rs_6m  DOUBLE PRECISION, rs_12m DOUBLE PRECISION,
    breadth_1m DOUBLE PRECISION, breadth_3m DOUBLE PRECISION, breadth_6m DOUBLE PRECISION, breadth_12m DOUBLE PRECISION,
    degraded       BOOLEAN NOT NULL DEFAULT FALSE,  -- n_priced < 0.8 * n_members, or an RS input missing
    source         TEXT NOT NULL,          -- 'apex' | 'daily_ohlc'
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, group_kind, group_key)
);
```

- [ ] **Step 4: Add the registry row** in `src/uw_scan/reports/data_gap_healer.py`, right after the `macro_release_calendar` entry (after line 312):

```python
    DatasetRegistryEntry(
        # Sector RS + breadth (migration 152). Derived from apex adjusted bars at
        # zero provider cost. Not healer-enrolled by design (spec 2026-09-26 §5):
        # the resumable backfill script shares the nightly job's compute core
        # and IS the heal.
        "sector_rs_daily",
        "regime_marketwide",
        "excluded",
        date_col="as_of",
        ticker_col=None,
        expected_frequency="none",
        reason=(
            "derived from apex bars; the heal is scripts/backfill/"
            "sector_rs_backfill.py (resumable, same compute core as the nightly "
            "job), not a healer adapter; freshness is watched via MONITORED_TABLES"
        ),
    ),
```

- [ ] **Step 5: Add the freshness row** in `src/uw_scan/reports/data_freshness.py`, before the closing `]` at line 288:

```python
    # Sector RS + breadth (migration 152): nightly 21:30 ET Mon–Fri, gated
    # UW_SCAN_SECTOR_RS_ENABLED (default off, so this row reads stale until
    # the flag flips on the mini after the backfill). Ticker-less, keyed
    # as_of + group; `as_of` is absent from _DATE_COL_PREFERENCE.
    MonitoredTable(
        "sector_rs_daily",
        "watchlist",  # ticker-less
        None,
        date_col_override="as_of",
    ),
```

- [ ] **Step 6: Regenerate the policy doc.** The command is copied from `tests/unit/reports/test_data_gap_dataset_policy.py:36`.

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
git diff --stat docs/runbooks/data-gap-dataset-policy.md   # expect a small diff: the new sector_rs_daily row
```

- [ ] **Step 7: Run the unit gates, then apply the migration and run the integration gates**

```bash
uv run pytest tests/unit/reports/test_sector_rs_freshness_enrolled.py tests/unit/reports/test_data_gap_dataset_policy.py tests/unit/reports/test_full_coverage.py tests/unit/reports/test_data_gap_reasons.py tests/unit/reports/test_data_gap_healer_specs.py -q
bash scripts/migrate.sh
uv run pytest tests/integration/worker/test_data_gap_full_coverage.py tests/integration/reports/test_monitored_tables_resolve_date_col.py -q
```
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/storage/migrations/152_sector_rs_daily.sql src/uw_scan/reports/data_gap_healer.py src/uw_scan/reports/data_freshness.py docs/runbooks/data-gap-dataset-policy.md tests/unit/reports/test_sector_rs_freshness_enrolled.py
git commit -m "feat(sector-rs): migration 152 sector_rs_daily + registry/freshness enrolment"
```

---

### Task 2: Pure compute `reports/sector_rs.py` + frozen real-close fixture

**Files**
- Create: `tests/unit/reports/fixtures/sector_rs_closes_2026-09-18.json` (frozen with the command in Step 1)
- Create: `src/uw_scan/reports/sector_rs.py`
- Create: `tests/unit/reports/test_sector_rs.py`

**Interfaces**
- Consumes: nothing (pure).
- Produces:
```python
WINDOWS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
COVERAGE_FLOOR = 0.8
@dataclass(frozen=True)
class GroupSpec: kind: str; key: str; weighting: str; rs_symbol: str | None; members: tuple[str, ...]; rs_valid_from: date | None = None
@dataclass(frozen=True)
class SectorRsRow: as_of: date; group_kind: str; group_key: str; weighting: str; rs_symbol: str | None; n_members: int; n_classified: int; n_priced: int; rs: dict[str, float | None]; breadth: dict[str, float | None]; degraded: bool; source: str
def window_return(closes: list[float], n: int) -> float | None
def compute_group_rows(as_of: date, groups: list[GroupSpec], closes: dict[str, list[tuple[date, float]]], benchmark: str = "SPY", source: str = "apex") -> list[SectorRsRow]
```

This contract has one deliberate refinement of spec §3's "members with ≥253 closes". A member counts as priced for window `w` when it has a close on **both** of SPY's anchor sessions for `w`: the session ≤ as_of, and the session `w` bars earlier. Counting a member's own closes would price a name delisted mid-window over a stale window that ended weeks before as_of (Review Focus 1). `n_priced` stays the 12m count, as the spec says.

- [ ] **Step 1: Freeze the fixture (network, run once at implementation time)**

```bash
mkdir -p tests/unit/reports/fixtures
uv run python - <<'PY'
import json, os
from datetime import date
from pathlib import Path
import httpx

apex = os.environ.get("APEX_API_URL", "http://100.66.147.98:8322").rstrip("/")  # default from sources/apex.py
symbols = ["SPY", "XLK", "AAPL", "MSFT", "NVDA"]
r = httpx.get(
    f"{apex}/v1/equity/bars",
    params={
        "symbols": ",".join(symbols),
        "timeframe": "1d",
        "start": "2025-08-01T00:00:00Z",
        "end": "2026-09-18T23:59:59Z",
        "limit": 0,
        "price_mode": "adjusted",
        "listing": "any",
    },
    timeout=60,
)
r.raise_for_status()
body = r.json()
assert not body["missing"], body["missing"]
out = {
    "as_of": "2026-09-18",
    "fetched_on": date.today().isoformat(),
    "source": "apex GET /v1/equity/bars (bulk) timeframe=1d price_mode=adjusted listing=any limit=0",
    "adjustment_revision": body["adjustment_revision"],
    "closes": {
        s: [[b["time"][:10], b["close"]] for b in body["symbols"][s]["bars"]][-260:]
        for s in symbols
    },
}
dates = [d for d, _ in out["closes"]["SPY"]]
assert len(dates) == 260 and dates[-1] == "2026-09-18", (len(dates), dates[-1])
for s in symbols:
    assert [d for d, _ in out["closes"][s]] == dates, s
Path("tests/unit/reports/fixtures/sector_rs_closes_2026-09-18.json").write_text(json.dumps(out, indent=1) + "\n")

def ret(s, n):
    c = [x for _, x in out["closes"][s]]
    return c[-1] / c[-1 - n] - 1
spy = {n: ret("SPY", n) for n in (21, 63, 252)}
print("adjustment_revision", out["adjustment_revision"])
print("XLK rs 3m", round((ret("XLK", 63) - spy[63]) * 100, 3), "rs 12m", round((ret("XLK", 252) - spy[252]) * 100, 3))
print("equal rs 12m", round((sum(ret(m, 252) for m in ("AAPL", "MSFT", "NVDA")) / 3 - spy[252]) * 100, 3))
print("MSFT rs 12m", round((ret("MSFT", 252) - spy[252]) * 100, 3))
PY
```
Expected output at `adjustment_revision 80` (measured 2026-09-26): `XLK rs 3m -3.098 rs 12m 23.315`, `equal rs 12m 6.083`, `MSFT rs 12m -19.509`. **If the printed revision is not 80, replace the four literal values in Step 2's tests with the printed ones.** The index-based assertions next to them stay authoritative either way.

- [ ] **Step 2: Write the failing tests** at `tests/unit/reports/test_sector_rs.py`

```python
"""sector_rs compute against frozen REAL closes (fixture as-of 2026-09-18).

Fixture: tests/unit/reports/fixtures/sector_rs_closes_2026-09-18.json — apex
bulk GET /v1/equity/bars, 1d, price_mode=adjusted, listing=any; the 260 sessions
2025-09-08 → 2026-09-18 for SPY, XLK, AAPL, MSFT, NVDA. No network.

Numeric checks are made twice: once against an index-based recomputation from
the fixture (authoritative), and once against the literal measured when the
fixture was frozen (adjustment_revision 80). A silent formula change fails the
first; a silent fixture swap fails the second.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from uw_scan.reports.sector_rs import (
    WINDOWS,
    GroupSpec,
    compute_group_rows,
    window_return,
)

_FIXTURE = Path(__file__).parent / "fixtures" / "sector_rs_closes_2026-09-18.json"
AS_OF = date(2026, 9, 18)
TECH = ("AAPL", "MSFT", "NVDA")
ETF_TECH = GroupSpec("gics", "Technology", "etf", "XLK", TECH)
EQUAL_TECH = GroupSpec("chain", "Tech-Trio", "equal", None, TECH)


def _closes() -> dict[str, list[tuple[date, float]]]:
    raw = json.loads(_FIXTURE.read_text())
    return {
        s: [(date.fromisoformat(d), float(c)) for d, c in rows]
        for s, rows in raw["closes"].items()
    }


def _ret(series: list[tuple[date, float]], n: int) -> float:
    c = [x for _, x in series]
    return c[-1] / c[-1 - n] - 1.0


def test_fixture_is_the_frozen_window():
    closes = _closes()
    spy_dates = [d for d, _ in closes["SPY"]]
    assert len(spy_dates) == 260 and spy_dates[-1] == AS_OF
    for s in ("XLK", *TECH):
        assert [d for d, _ in closes[s]] == spy_dates, s


def test_window_return_needs_n_plus_one_closes():
    spy = [c for _, c in _closes()["SPY"]]
    assert window_return(spy[:21], 21) is None
    assert window_return(spy[:22], 21) == pytest.approx(spy[21] / spy[0] - 1.0)
    assert window_return(spy, 0) is None


def test_etf_rs_is_etf_return_minus_spy_in_points():
    closes = _closes()
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    for label, n in WINDOWS.items():
        expected = (_ret(closes["XLK"], n) - _ret(closes["SPY"], n)) * 100.0
        assert row.rs[label] == pytest.approx(expected, abs=1e-9), label
    # literals at adjustment_revision 80: XLK lagged SPY over 3m, led over 12m
    assert row.rs["3m"] == pytest.approx(-3.098, abs=0.01)
    assert row.rs["12m"] == pytest.approx(23.315, abs=0.01)
    assert row.rs_symbol == "XLK" and row.weighting == "etf"
    assert row.as_of == AS_OF and row.source == "apex"


def test_equal_weighting_uses_the_member_mean_not_the_etf():
    closes = _closes()
    (row,) = compute_group_rows(AS_OF, [EQUAL_TECH], closes)
    n = WINDOWS["12m"]
    mean = sum(_ret(closes[m], n) for m in TECH) / len(TECH)
    assert row.rs["12m"] == pytest.approx((mean - _ret(closes["SPY"], n)) * 100.0, abs=1e-9)
    assert row.rs["12m"] == pytest.approx(6.083, abs=0.02)
    assert row.rs_symbol is None and row.weighting == "equal"


def test_breadth_counts_members_beating_spy():
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], _closes())
    # 12m: MSFT −2.39% vs SPY +17.12%; AAPL and NVDA beat it
    assert row.breadth["12m"] == pytest.approx(2 / 3)
    assert row.breadth["1m"] == pytest.approx(1.0)
    assert (row.n_members, row.n_classified, row.n_priced) == (3, 3, 3)
    assert row.degraded is False


def test_member_short_a_window_is_unpriced_and_degrades():
    closes = _closes()
    closes["NVDA"] = closes["NVDA"][-200:]  # starts after the 12m anchor
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert row.n_priced == 2  # the 12m count
    assert row.breadth["12m"] == pytest.approx(1 / 2)  # AAPL beats, MSFT does not
    assert row.breadth["1m"] == pytest.approx(1.0)  # all three priced over 1m
    assert row.degraded is True  # 2 < 0.8 * 3


def test_member_delisted_mid_window_is_not_priced_on_a_stale_window():
    closes = _closes()
    closes["NVDA"] = closes["NVDA"][:-10]  # bars stop 10 sessions before as_of
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert row.n_priced == 2
    # 2 of 2 priced members beat SPY over 1m; NVDA is absent, not stale-priced
    assert row.breadth["1m"] == pytest.approx(1.0)
    assert row.degraded is True


def test_member_absent_from_closes_is_unpriced_not_zero():
    # A delisted former member lands in apex's bulk `missing` map (no Silver for
    # delisted names), so it is absent from `closes`: counted in n_members,
    # never in n_priced, and never a 0% return.
    closes = _closes()
    del closes["MSFT"]
    (row,) = compute_group_rows(AS_OF, [EQUAL_TECH], closes)
    assert (row.n_members, row.n_priced) == (3, 2)
    assert row.breadth["12m"] == pytest.approx(1.0)  # AAPL and NVDA both beat SPY
    n = WINDOWS["12m"]
    mean = (_ret(closes["AAPL"], n) + _ret(closes["NVDA"], n)) / 2
    assert row.rs["12m"] == pytest.approx((mean - _ret(closes["SPY"], n)) * 100.0, abs=1e-9)
    assert row.degraded is True  # 2 < 0.8 * 3


def test_missing_etf_gives_null_rs_and_degraded_but_keeps_breadth():
    closes = _closes()
    del closes["XLK"]
    (row,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert all(v is None for v in row.rs.values())
    assert row.degraded is True
    assert row.breadth["12m"] == pytest.approx(2 / 3)


def test_rs_valid_from_nulls_only_the_windows_that_start_before_it():
    # 1m starts 21 sessions before 2026-09-18 (late August); 12m starts in 2025-09.
    g = GroupSpec("gics", "Technology", "etf", "XLK", TECH, rs_valid_from=date(2026, 8, 1))
    (row,) = compute_group_rows(AS_OF, [g], _closes())
    assert row.rs["1m"] is not None
    assert row.rs["3m"] is None and row.rs["6m"] is None and row.rs["12m"] is None
    assert row.degraded is True  # 12m RS input missing
    assert row.breadth["12m"] == pytest.approx(2 / 3)  # breadth ignores the ETF


def test_single_member_group():
    (row,) = compute_group_rows(
        AS_OF, [GroupSpec("chain", "Solo", "equal", None, ("MSFT",))], _closes()
    )
    assert row.breadth["12m"] == 0.0
    assert row.rs["12m"] == pytest.approx(-19.509, abs=0.01)
    assert row.n_priced == 1 and row.degraded is False


def test_empty_group_is_degraded_with_null_breadth():
    (row,) = compute_group_rows(
        AS_OF, [GroupSpec("gics", "Energy", "etf", "XLK", ())], _closes()
    )
    assert row.n_members == 0 and row.n_priced == 0
    assert row.degraded is True
    assert all(v is None for v in row.breadth.values())


def test_missing_or_short_benchmark_raises():
    closes = _closes()
    del closes["SPY"]
    with pytest.raises(ValueError):
        compute_group_rows(AS_OF, [ETF_TECH], closes)
    closes = _closes()
    closes["SPY"] = closes["SPY"][-100:]
    with pytest.raises(ValueError, match="12m"):
        compute_group_rows(AS_OF, [ETF_TECH], closes)


def test_bars_after_as_of_are_ignored():
    closes = _closes()
    earlier = date(2026, 9, 11)
    (row,) = compute_group_rows(earlier, [ETF_TECH], closes)
    cut = {s: [(d, c) for d, c in v if d <= earlier] for s, v in closes.items()}
    n = WINDOWS["1m"]
    expected = (_ret(cut["XLK"], n) - _ret(cut["SPY"], n)) * 100.0
    assert row.rs["1m"] == pytest.approx(expected, abs=1e-9)
    assert row.as_of == earlier


def test_non_trading_as_of_uses_the_last_session():
    closes = _closes()
    (sat,) = compute_group_rows(date(2026, 9, 19), [ETF_TECH], closes)
    (fri,) = compute_group_rows(AS_OF, [ETF_TECH], closes)
    assert sat.rs == fri.rs and sat.breadth == fri.breadth


def test_unknown_weighting_is_refused():
    with pytest.raises(ValueError, match="weighting"):
        compute_group_rows(
            AS_OF, [GroupSpec("chain", "X", "cap", None, TECH)], _closes()
        )
```

- [ ] **Step 3: Run it and confirm it fails**

```bash
uv run pytest tests/unit/reports/test_sector_rs.py -q
```
Expected: collection error, `ModuleNotFoundError: No module named 'uw_scan.reports.sector_rs'`.

- [ ] **Step 4: Implement** `src/uw_scan/reports/sector_rs.py`

```python
"""Sector relative strength + breadth — pure compute.

Spec: docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md §2–§3.
No I/O and no DB. The nightly job (worker/jobs/sector_rs_daily.py) and the
backfill (scripts/backfill/sector_rs_backfill.py) both call
`compute_group_rows`, so every number has one definition.

Windows are anchored on the BENCHMARK's sessions, not on each series' own bar
count. A member's window-w return is close(end)/close(start) − 1, where `end`
is SPY's last session ≤ as_of and `start` is SPY's session w bars earlier. A
member missing either anchor is unpriced for w. Counting a member's own last
w+1 closes instead would price a name delisted mid-window over a stale window
that ended weeks before as_of, and report it as current.

RS is in percentage points (group return − SPY return, not a ratio). Breadth is
the fraction of members priced for w whose return beats SPY's.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date
from statistics import fmean

WINDOWS: dict[str, int] = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
_LONGEST = "12m"
#: Below this share of members priced over 12m the row is `degraded` (spec §3).
COVERAGE_FLOOR = 0.8

Series = list[tuple[date, float]]


@dataclass(frozen=True)
class GroupSpec:
    kind: str  # 'gics' | 'chain'
    key: str  # 'Technology' | 'Semi-Logic' ...
    weighting: str  # 'etf' | 'equal'
    rs_symbol: str | None  # 'XLK' for etf rows; None for equal
    members: tuple[str, ...]
    #: First session the rs_symbol's adjusted history is trustworthy. An RS
    #: window whose start anchor is earlier is NULL (spec §4: XLF's seam).
    rs_valid_from: date | None = None


@dataclass(frozen=True)
class SectorRsRow:
    as_of: date
    group_kind: str
    group_key: str
    weighting: str
    rs_symbol: str | None
    n_members: int
    n_classified: int
    n_priced: int
    rs: dict[str, float | None]  # percentage points, keyed by WINDOWS label
    breadth: dict[str, float | None]  # fraction in [0, 1], keyed by WINDOWS label
    degraded: bool
    source: str  # 'apex' | 'daily_ohlc'


def window_return(closes: list[float], n: int) -> float | None:
    """Plain price return over the last `n` bars: closes[-1] / closes[-1-n] − 1.

    `closes` ascending, last element = the as_of session. None when fewer than
    n+1 closes exist, n is not positive, or the base close is not positive.
    """
    if n <= 0 or len(closes) < n + 1:
        return None
    base = closes[-1 - n]
    if base <= 0:
        return None
    return closes[-1] / base - 1.0


def _close_on(series: Series | None, day: date) -> float | None:
    """The close dated exactly `day`. Bisect on (date,) — series ascending."""
    if not series:
        return None
    i = bisect_left(series, (day,))
    if i < len(series) and series[i][0] == day:
        return series[i][1]
    return None


def _anchored_return(series: Series | None, start: date, end: date) -> float | None:
    base = _close_on(series, start)
    last = _close_on(series, end)
    if base is None or last is None or base <= 0:
        return None
    return last / base - 1.0


def compute_group_rows(
    as_of: date,
    groups: list[GroupSpec],
    closes: dict[str, Series],
    benchmark: str = "SPY",
    source: str = "apex",
) -> list[SectorRsRow]:
    """One SectorRsRow per group, for the session ending at the last close ≤ as_of.

    `closes[symbol]` is ascending (date, adjusted close). Bars after `as_of`
    are ignored. Raises ValueError when the benchmark cannot cover every window:
    a row without a benchmark is not a row with zero RS, and the caller must not
    write anything.
    """
    bench_all = closes.get(benchmark) or []
    bench = bench_all[: bisect_right(bench_all, (as_of, float("inf")))]
    bench_closes = [c for _, c in bench]
    bench_ret: dict[str, float] = {}
    anchors: dict[str, tuple[date, date]] = {}
    for label, n in WINDOWS.items():
        r = window_return(bench_closes, n)
        if r is None:
            raise ValueError(
                f"{benchmark} has {len(bench_closes)} closes <= {as_of}; "
                f"window {label} needs {n + 1}"
            )
        bench_ret[label] = r
        anchors[label] = (bench[-1 - n][0], bench[-1][0])

    rows: list[SectorRsRow] = []
    for g in groups:
        member_ret: dict[str, dict[str, float]] = {}
        for label in WINDOWS:
            start, end = anchors[label]
            priced: dict[str, float] = {}
            for m in g.members:
                r = _anchored_return(closes.get(m), start, end)
                if r is not None:
                    priced[m] = r
            member_ret[label] = priced
        breadth: dict[str, float | None] = {
            label: (
                sum(1 for r in rets.values() if r > bench_ret[label]) / len(rets)
                if rets
                else None
            )
            for label, rets in member_ret.items()
        }
        if g.weighting == "etf":
            group_ret: dict[str, float | None] = {
                label: (
                    None
                    if g.rs_valid_from is not None and anchors[label][0] < g.rs_valid_from
                    else _anchored_return(closes.get(g.rs_symbol or ""), *anchors[label])
                )
                for label in WINDOWS
            }
        elif g.weighting == "equal":
            group_ret = {
                label: fmean(rets.values()) if rets else None
                for label, rets in member_ret.items()
            }
        else:
            raise ValueError(f"unknown weighting {g.weighting!r} for {g.kind}/{g.key}")
        rs: dict[str, float | None] = {}
        for label in WINDOWS:
            gr = group_ret[label]
            rs[label] = None if gr is None else (gr - bench_ret[label]) * 100.0
        n_members = len(g.members)
        n_priced = len(member_ret[_LONGEST])
        degraded = (
            n_members == 0
            or n_priced < COVERAGE_FLOOR * n_members
            or rs[_LONGEST] is None
        )
        rows.append(
            SectorRsRow(
                as_of=as_of,
                group_kind=g.kind,
                group_key=g.key,
                weighting=g.weighting,
                rs_symbol=g.rs_symbol,
                n_members=n_members,
                n_classified=n_members,
                n_priced=n_priced,
                rs=rs,
                breadth=breadth,
                degraded=degraded,
                source=source,
            )
        )
    return rows
```

- [ ] **Step 5: Run the tests and confirm they pass**

```bash
uv run pytest tests/unit/reports/test_sector_rs.py -q
uv run ruff check src/uw_scan/reports/sector_rs.py tests/unit/reports/test_sector_rs.py
```
Expected: 15 passed, and ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/sector_rs.py tests/unit/reports/test_sector_rs.py tests/unit/reports/fixtures/sector_rs_closes_2026-09-18.json
git commit -m "feat(sector-rs): pure RS/breadth compute with frozen real-close fixture"
```

---

### Task 3: `storage/sector_rs.py` repository + integration test

**Files**
- Create: `src/uw_scan/storage/sector_rs.py`
- Create: `tests/integration/storage/test_sector_rs_repository.py`

**Interfaces**
- Consumes: `SectorRsRow`, `WINDOWS` (Task 2); table from Task 1.
- Produces:
```python
class SectorRsRepository:
    def __init__(self, conn: psycopg.Connection, *, schema: str = "uw_scan") -> None
    def upsert_rows(self, rows: Sequence[SectorRsRow]) -> int
    def latest(self, as_of: date, group_kind: str) -> list[SectorRsRow]
    def history(self, group_kind: str, group_key: str, since: date) -> list[SectorRsRow]
    def dates_present(self, group_kind: str, start: date, end: date) -> set[date]
```

- [ ] **Step 1: Write the failing test** at `tests/integration/storage/test_sector_rs_repository.py`

```python
"""sector_rs_daily persistence: idempotent upsert, ordering, latest-as-of.

Row values are the real XLK-vs-SPY numbers measured to 2026-09-18
(apex adjusted, adjustment_revision 80; see Task 2's fixture).
"""

from __future__ import annotations

from datetime import date

from uw_scan.reports.sector_rs import SectorRsRow
from uw_scan.storage.sector_rs import SectorRsRepository


def _repo(seeded) -> SectorRsRepository:
    return SectorRsRepository(seeded.conn, schema=seeded._schema)


def _row(as_of: date, *, key: str = "Technology", rs12: float = 23.315,
         degraded: bool = False, source: str = "apex") -> SectorRsRow:
    return SectorRsRow(
        as_of=as_of, group_kind="gics", group_key=key, weighting="etf",
        rs_symbol="XLK", n_members=3, n_classified=3, n_priced=3,
        rs={"1m": 3.958, "3m": -3.098, "6m": 20.954, "12m": rs12},
        breadth={"1m": 1.0, "3m": 1.0, "6m": 1.0, "12m": 2 / 3},
        degraded=degraded, source=source,
    )


def test_upsert_is_idempotent_and_last_write_wins(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    d = date(2026, 9, 18)
    assert r.upsert_rows([_row(d)]) == 1
    assert r.upsert_rows([_row(d, rs12=-1.5, degraded=True, source="daily_ohlc")]) == 1
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            f"SELECT count(*) FROM {seeded_db_empty_cards._schema}.sector_rs_daily"
        )
        assert cur.fetchone()[0] == 1
    (got,) = r.history("gics", "Technology", d)
    assert got == _row(d, rs12=-1.5, degraded=True, source="daily_ohlc")


def test_empty_upsert_writes_nothing(seeded_db_empty_cards):
    assert _repo(seeded_db_empty_cards).upsert_rows([]) == 0


def test_history_is_ascending_and_bounded_by_since(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    days = [date(2026, 9, 18), date(2026, 9, 11), date(2026, 9, 14)]
    r.upsert_rows([_row(d) for d in days])
    r.upsert_rows([_row(date(2026, 9, 14), key="Energy")])
    assert [x.as_of for x in r.history("gics", "Technology", date(2026, 9, 1))] == sorted(days)
    assert [x.as_of for x in r.history("gics", "Technology", date(2026, 9, 14))] == [
        date(2026, 9, 14), date(2026, 9, 18)
    ]


def test_latest_returns_the_last_session_at_or_before_as_of(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.upsert_rows([_row(date(2026, 9, 11)), _row(date(2026, 9, 18)),
                   _row(date(2026, 9, 18), key="Energy")])
    sat = r.latest(date(2026, 9, 19), "gics")
    assert [(x.as_of, x.group_key) for x in sat] == [
        (date(2026, 9, 18), "Energy"), (date(2026, 9, 18), "Technology")
    ]
    assert [x.as_of for x in r.latest(date(2026, 9, 12), "gics")] == [date(2026, 9, 11)]
    assert r.latest(date(2026, 9, 19), "chain") == []


def test_dates_present_per_kind(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    r.upsert_rows([_row(date(2026, 9, 11)), _row(date(2026, 9, 18))])
    assert r.dates_present("gics", date(2026, 9, 1), date(2026, 9, 15)) == {date(2026, 9, 11)}
    assert r.dates_present("chain", date(2026, 9, 1), date(2026, 9, 30)) == set()
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/integration/storage/test_sector_rs_repository.py -q
```
Expected: collection error, `ModuleNotFoundError: No module named 'uw_scan.storage.sector_rs'`.

- [ ] **Step 3: Implement** `src/uw_scan/storage/sector_rs.py`

```python
"""sector_rs_daily persistence (migration 152).

Its own module and not a `Repository` mixin: repository.py is closed to new
query methods (root CLAUDE.md module-size rule). The shape follows
storage/company_sector.py: a standalone class over one connection that
commits its own writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.reports.sector_rs import WINDOWS, SectorRsRow

_LABELS = tuple(WINDOWS)  # ('1m', '3m', '6m', '12m')
_KEY = ("as_of", "group_kind", "group_key")
_COLS = (
    *_KEY,
    "weighting",
    "rs_symbol",
    "n_members",
    "n_classified",
    "n_priced",
    *(f"rs_{w}" for w in _LABELS),
    *(f"breadth_{w}" for w in _LABELS),
    "degraded",
    "source",
)


def _params(r: SectorRsRow) -> tuple[Any, ...]:
    return (
        r.as_of,
        r.group_kind,
        r.group_key,
        r.weighting,
        r.rs_symbol,
        r.n_members,
        r.n_classified,
        r.n_priced,
        *(r.rs.get(w) for w in _LABELS),
        *(r.breadth.get(w) for w in _LABELS),
        r.degraded,
        r.source,
    )


def _row(t: Sequence[Any]) -> SectorRsRow:
    k = len(_LABELS)
    rs_vals = t[8 : 8 + k]
    breadth_vals = t[8 + k : 8 + 2 * k]
    return SectorRsRow(
        as_of=t[0],
        group_kind=t[1],
        group_key=t[2],
        weighting=t[3],
        rs_symbol=t[4],
        n_members=t[5],
        n_classified=t[6],
        n_priced=t[7],
        rs=dict(zip(_LABELS, rs_vals, strict=True)),
        breadth=dict(zip(_LABELS, breadth_vals, strict=True)),
        degraded=t[8 + 2 * k],
        source=t[9 + 2 * k],
    )


class SectorRsRepository:
    def __init__(self, conn: psycopg.Connection, *, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[SectorRsRow]) -> int:
        """Insert or overwrite every column, keyed (as_of, group_kind, group_key).

        DO UPDATE on every column, not DO NOTHING: a nightly re-run after a
        late bar, or a backfill with --force, must converge on the recomputed
        row. `computed_at` is bumped so the table says when a row was last derived.
        """
        if not rows:
            return 0
        updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLS if c not in _KEY)
        sql = (
            f"INSERT INTO {self._schema}.sector_rs_daily ({', '.join(_COLS)}) "
            f"VALUES ({', '.join(['%s'] * len(_COLS))}) "
            f"ON CONFLICT ({', '.join(_KEY)}) DO UPDATE SET {updates}, computed_at = now()"
        )
        with self.conn.cursor() as cur:
            cur.executemany(sql, [_params(r) for r in rows])
        self.conn.commit()
        return len(rows)

    def latest(self, as_of: date, group_kind: str) -> list[SectorRsRow]:
        """Every group's row on the last as_of ≤ `as_of` for this kind."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT {', '.join(_COLS)} FROM {self._schema}.sector_rs_daily
                     WHERE group_kind = %s
                       AND as_of = (SELECT max(as_of) FROM {self._schema}.sector_rs_daily
                                     WHERE group_kind = %s AND as_of <= %s)
                     ORDER BY group_key""",
                (group_kind, group_kind, as_of),
            )
            return [_row(t) for t in cur.fetchall()]

    def history(self, group_kind: str, group_key: str, since: date) -> list[SectorRsRow]:
        """One group's rows from `since`, ascending by as_of."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT {', '.join(_COLS)} FROM {self._schema}.sector_rs_daily
                     WHERE group_kind = %s AND group_key = %s AND as_of >= %s
                     ORDER BY as_of""",
                (group_kind, group_key, since),
            )
            return [_row(t) for t in cur.fetchall()]

    def dates_present(self, group_kind: str, start: date, end: date) -> set[date]:
        """Sessions already holding at least one row of this kind (backfill resume)."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT as_of FROM {self._schema}.sector_rs_daily
                     WHERE group_kind = %s AND as_of BETWEEN %s AND %s""",
                (group_kind, start, end),
            )
            return {r[0] for r in cur.fetchall()}
```

- [ ] **Step 4: Run the tests and confirm they pass**

```bash
uv run pytest tests/integration/storage/test_sector_rs_repository.py -q
uv run ruff check src/uw_scan/storage/sector_rs.py tests/integration/storage/test_sector_rs_repository.py
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/storage/sector_rs.py tests/integration/storage/test_sector_rs_repository.py
git commit -m "feat(sector-rs): SectorRsRepository (upsert/latest/history/dates_present)"
```

---

### Task 4: apex `fetch_bulk_daily_closes` (bulk route) + vendored S&P 500 list

**Files**
- Modify: `src/uw_scan/sources/apex.py`. Add `from collections.abc import Iterable` to the imports at lines 19–25, and append the new functions after `fetch_bars`, which ends the file at line 349. `fetch_bars` itself is unchanged.
- Create: `tests/unit/sources/test_apex_bulk.py`
- Create: `src/uw_scan/sources/sp500_members.py`, `src/uw_scan/sources/data/sp500_members.json` (generated in Step 8), `scripts/research/sync_sp500_members.py`
- Create: `tests/unit/sources/test_sp500_members.py`, `tests/unit/scripts/test_sync_sp500_members.py`
- Modify: `pyproject.toml` `[tool.setuptools.package-data]` (lines 76–81)

**Interfaces**
- Consumes: `_apex_url`, `_err_code` (both in `sources/apex.py`); apex `GET /v1/equity/bars` (see "Verified facts"); the sync script alone reads a local livewire checkout's `presets/sp500.json`. argon never calls apex's membership route.
- Produces:
```python
# sources/apex.py
BULK_MAX_SYMBOLS = 200
def fetch_bulk_daily_closes(symbols: Iterable[str], *, start: date, end: date, timeout: float = 30.0, client: httpx.Client | None = None) -> dict[str, dict[date, float]]
# sources/sp500_members.py
MIN_MEMBERS = 450
class Sp500ListInvalid(ValueError)
def validate_tickers(tickers: object) -> tuple[str, ...]
def sp500_members() -> tuple[str, ...]            # cached; raises Sp500ListInvalid
# scripts/research/sync_sp500_members.py
def build(livewire: Path, as_of: date) -> dict[str, object]
def main(argv: list[str] | None = None) -> int     # --livewire --out --as-of
```
`listing_status` and `truncated` from the response are recorded nowhere, because nothing downstream needs them. `truncated` is always false here: an explicit `start` turns apex's tail-slice off (`resolve_window` returns `tail=None`).

- [ ] **Step 1: Write the failing test** at `tests/unit/sources/test_apex_bulk.py`

```python
"""fetch_bulk_daily_closes: request shape, parser, never-raise.

_BULK is a REAL response of apex GET /v1/equity/bars captured 2026-09-26:
XLK adjusted closes at adjustment_revision 80, and TWTR filed under `missing`
with apex's own reason. _SP500_FIRST_200 is the first 200 tickers, sorted,
of livewire presets/sp500.json (the list vendored in this task); only their
count matters to the chunking test. No network: httpx.MockTransport.
"""

from __future__ import annotations

from datetime import date

import httpx

from uw_scan.sources.apex import fetch_bulk_daily_closes

_START, _END = date(2026, 9, 10), date(2026, 9, 11)
_XLK_BARS = [
    {"time": "2026-09-10T00:00:00+00:00", "open": 185.02438884683545,
     "high": 186.3028989835443, "low": 184.35017451693037,
     "close": 185.00441212594936, "volume": 5571344},
    {"time": "2026-09-11T00:00:00+00:00", "open": 187.13193290031646,
     "high": 188.42043139746835, "low": 186.66247995949368,
     "close": 187.45156043449367, "volume": 6535157},
]
_BULK = {
    "price_mode": "adjusted", "basis": "split+dividend", "adjustment_revision": 80,
    "silver_revision": None, "timeframe": "1d",
    "window": {"start": "2026-09-10T00:00:00+00:00", "end": "2026-09-11T23:59:59+00:00"},
    "symbols": {"XLK": {"listing_status": "listed", "truncated": False, "bars": _XLK_BARS}},
    "missing": {"TWTR": "no Silver for delisted names; use price_mode=raw"},
    "generated_at": "2026-09-26T15:18:06.083800+00:00",
}
_XLK_CLOSES = {date(2026, 9, 10): 185.00441212594936, date(2026, 9, 11): 187.45156043449367}
_SP500_FIRST_200 = tuple(
    "A,AAPL,ABBV,ABNB,ABT,ACGL,ACN,ADBE,ADI,ADM,ADP,ADSK,AEE,AEP,AES,AFL,AIG,AIZ,AJG,AKAM"
    ",ALB,ALGN,ALL,ALLE,AMAT,AMCR,AMD,AME,AMGN,AMP,AMT,AMZN,ANET,AON,AOS,APA,APD,APH,APO,"
    "APP,APTV,ARE,ARES,ATO,AVGO,AVY,AWK,AXON,AXP,AZO,BA,BAC,BALL,BAX,BBY,BDX,BEN,BF.B,BG,"
    "BIIB,BKNG,BKR,BLDR,BLK,BMY,BNY,BR,BRK.B,BRO,BSX,BX,BXP,C,CAH,CARR,CASY,CAT,CB,CBOE,C"
    "BRE,CCI,CCL,CDNS,CDW,CEG,CF,CFG,CHD,CHRW,CHTR,CI,CIEN,CINF,CL,CLX,CMCSA,CME,CMG,CMI,"
    "CMS,CNC,CNP,COF,COHR,COIN,COO,COP,COR,COST,CPAY,CPRT,CPT,CRH,CRL,CRM,CRWD,CSCO,CSGP,"
    "CSX,CTAS,CTSH,CTVA,CVNA,CVS,CVX,D,DAL,DASH,DD,DDOG,DE,DECK,DELL,DG,DGX,DHI,DHR,DIS,D"
    "LR,DLTR,DOC,DOV,DOW,DPZ,DRI,DTE,DUK,DVA,DVN,DXCM,EBAY,ECHO,ECL,ED,EFX,EG,EIX,EL,ELV,"
    "EME,EMR,EOG,EQIX,EQT,ERIE,ES,ESS,ETN,ETR,EVRG,EW,EXC,EXE,EXPD,EXPE,EXR,F,FANG,FAST,F"
    "CX,FDS,FDX,FDXF,FE,FERG,FFIV,FICO,FIS,FISV,FITB,FIX,FLEX,FOX,FOXA,FRT,FSLR,FTNT,FTV,"
    "GD,GDDY".split(",")
)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_nested_shape_parses_and_missing_symbols_are_absent():
    out = fetch_bulk_daily_closes(
        ["XLK", "TWTR"], start=_START, end=_END,
        client=_client(lambda req: httpx.Response(200, json=_BULK)),
    )
    # TWTR is in `missing` (delisted: no Silver) → absent, never an empty or zero series
    assert out == {"XLK": _XLK_CLOSES}


def test_request_is_one_tz_aware_adjusted_full_window_call():
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_BULK)

    fetch_bulk_daily_closes(["xlk", "XLK", "TWTR"], start=_START, end=_END, client=_client(handler))
    assert len(seen) == 1
    q = seen[0].url.params
    assert seen[0].url.path == "/v1/equity/bars"
    assert q["symbols"] == "XLK,TWTR"  # upper-cased, deduped, order kept
    assert q["timeframe"] == "1d"
    assert q["price_mode"] == "adjusted"
    assert q["listing"] == "any"
    assert q["limit"] == "0"
    # apex answers 400 invalid_parameter for a bare date or naive timestamp
    # ("start must carry a UTC offset"), so the client must send an explicit Z
    assert q["start"] == "2026-09-10T00:00:00Z"
    assert q["end"] == "2026-09-11T23:59:59Z"


def test_201_symbols_are_two_calls_of_200_and_1():
    seen: list[list[str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params["symbols"].split(","))
        return httpx.Response(200, json={**_BULK, "symbols": {}, "missing": {}})

    fetch_bulk_daily_closes([*_SP500_FIRST_200, "XLK"], start=_START, end=_END, client=_client(handler))
    assert [len(s) for s in seen] == [200, 1]
    assert seen[1] == ["XLK"]


def test_a_failed_chunk_costs_only_that_chunk():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["symbols"] == "XLK":
            return httpx.Response(200, json=_BULK)
        return httpx.Response(503, json={"error": {"code": "adjusted_unavailable", "message": "mocked"}})

    out = fetch_bulk_daily_closes([*_SP500_FIRST_200, "XLK"], start=_START, end=_END, client=_client(handler))
    assert out == {"XLK": _XLK_CLOSES}


def test_transport_error_and_garbage_never_raise():
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    def html(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>proxy page</html>")

    def wrong_shape(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbols": ["XLK"], "missing": []})

    def bad_request(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"code": "invalid_parameter", "message": "mocked"}})

    for h in (boom, html, wrong_shape, bad_request):
        assert fetch_bulk_daily_closes(["XLK"], start=_START, end=_END, client=_client(h)) == {}
    assert fetch_bulk_daily_closes([], start=_START, end=_END, client=_client(boom)) == {}

```

- [ ] **Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/unit/sources/test_apex_bulk.py -q
```
Expected: `ImportError: cannot import name 'fetch_bulk_daily_closes'`.

- [ ] **Step 3: Implement.** In `src/uw_scan/sources/apex.py`:

(a) Add `from collections.abc import Iterable` to the import block (lines 19–25).

(b) Append at the end of the file:

```python
# ---------------------------------------------------------------------------
# Many-symbol daily closes (sector RS)
# ---------------------------------------------------------------------------

#: apex GET /v1/equity/bars accepts at most 200 symbols per call (400 above).
BULK_MAX_SYMBOLS = 200


def _utc_bound(d: date, *, end: bool) -> str:
    """Explicit-Z day bound. apex answers 400 invalid_parameter for a bare date
    or a naive timestamp ("start must carry a UTC offset"). `end` runs to
    23:59:59, so the end session's bar (stamped at UTC midnight) is included."""
    return f"{d.isoformat()}T23:59:59Z" if end else f"{d.isoformat()}T00:00:00Z"


def _parse_daily_closes(bars: object) -> dict[date, float]:
    """{session_date: close} from apex daily bar dicts (time = UTC midnight)."""
    out: dict[date, float] = {}
    if not isinstance(bars, list):
        return out
    for b in bars:
        if not isinstance(b, dict):
            continue
        t = b.get("time")
        c = b.get("close")
        if t is None or c is None:
            continue
        try:
            out[datetime.fromisoformat(t).date()] = float(c)
        except (ValueError, TypeError) as exc:
            logger.debug("apex daily bar parse skip: %s", repr(exc))
    return out


def fetch_bulk_daily_closes(
    symbols: Iterable[str],
    *,
    start: date,
    end: date,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> dict[str, dict[date, float]]:
    """Adjusted daily closes for many equity symbols over apex's bulk route.

    GET /v1/equity/bars in chunks of BULK_MAX_SYMBOLS. One Silver revision is
    pinned per call. `limit=0` with an explicit start returns every row in the
    window. `listing=any` is sent, but under price_mode=adjusted apex files a
    delisted name under `missing` ("no Silver for delisted names"): livewire
    adjusts only listed names. Such a name is ABSENT from the result. The
    caller counts it as unpriced, never as a zero return, and it is not
    re-fetched raw (spec §4 ruling).

    Never-raise: a transport error, a non-200 answer or a malformed body costs
    only that chunk.
    """
    wanted = list(dict.fromkeys(s.strip().upper() for s in symbols if s and s.strip()))
    out: dict[str, dict[date, float]] = {}
    if not wanted:
        return out
    own = client is None
    c = client or httpx.Client(timeout=timeout)
    missing_total = 0
    try:
        for i in range(0, len(wanted), BULK_MAX_SYMBOLS):
            chunk = wanted[i : i + BULK_MAX_SYMBOLS]
            try:
                resp = c.get(
                    f"{_apex_url()}/v1/equity/bars",
                    params={
                        "symbols": ",".join(chunk),
                        "timeframe": "1d",
                        "start": _utc_bound(start, end=False),
                        "end": _utc_bound(end, end=True),
                        "limit": 0,
                        "price_mode": "adjusted",
                        "listing": "any",
                    },
                )
                resp.raise_for_status()
                body = resp.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "apex bulk bars failed for %d symbols from %s: %s (apex code=%s)",
                    len(chunk),
                    chunk[0],
                    repr(exc),
                    _err_code(exc),
                )
                continue
            series = body.get("symbols") if isinstance(body, dict) else None
            if not isinstance(series, dict):
                logger.warning("apex bulk bars malformed for chunk from %s", chunk[0])
                continue
            for sym, entry in series.items():
                closes = _parse_daily_closes(entry.get("bars") if isinstance(entry, dict) else None)
                if closes:
                    out[str(sym).upper()] = closes
            missing = body.get("missing")
            if isinstance(missing, dict):
                missing_total += len(missing)
                for sym, reason in missing.items():
                    logger.debug("apex bulk bars missing %s: %s", sym, reason)
    finally:
        if own:
            c.close()
    if missing_total:
        logger.info(
            "apex bulk bars: %d of %d symbols in `missing` (unpriced, not zero)",
            missing_total,
            len(wanted),
        )
    return out
```

- [ ] **Step 4: Run the tests, plus the existing apex tests to check nothing else moved**

```bash
uv run pytest tests/unit/sources/test_apex_bulk.py tests/unit/sources/test_apex_fetch_bars.py tests/unit/sources/test_apex_bars_limit.py tests/unit/test_apex_source.py tests/unit/test_apex_daily_bars.py -q
uv run ruff check src/uw_scan/sources/apex.py tests/unit/sources/test_apex_bulk.py
wc -l src/uw_scan/sources/apex.py   # expect < 500 (about 430)
```
Expected: all pass.

- [ ] **Step 5: Write the failing tests for the vendored S&P 500 list and its sync script.**

`tests/unit/sources/test_sp500_members.py`:

```python
"""The vendored S&P 500 list ships with the package and passes its own validation.

The file is copied from livewire presets/sp500.json (real constituents) by
scripts/research/sync_sp500_members.py. No network.
"""

from __future__ import annotations

import json
from importlib.resources import files

import pytest

from uw_scan.sources.sp500_members import (
    MIN_MEMBERS,
    Sp500ListInvalid,
    sp500_members,
    validate_tickers,
)


def test_vendored_list_is_large_unique_upper_case_and_current():
    tickers = sp500_members()
    assert len(tickers) >= MIN_MEMBERS
    assert len(set(tickers)) == len(tickers)
    assert all(t == t.upper() and t.strip() == t for t in tickers)
    # two of the names apex's membership route dropped on 2026-09-26
    assert {"META", "XOM"} <= set(tickers)


def test_vendored_file_records_its_provenance():
    body = json.loads((files("uw_scan.sources") / "data" / "sp500_members.json").read_text())
    assert body["source"].startswith("livewire presets/sp500.json @ ")
    assert len(body["source"].rsplit(" ", 1)[-1]) == 40  # full git commit hash
    assert body["as_of"]


def test_validate_rejects_duplicates_and_short_lists():
    good = list(sp500_members())
    assert validate_tickers(good) == tuple(sorted(good))
    with pytest.raises(Sp500ListInvalid, match="duplicate"):
        validate_tickers(good + [good[0].lower()])
    with pytest.raises(Sp500ListInvalid, match="450"):
        validate_tickers(good[:449])
    with pytest.raises(Sp500ListInvalid):
        validate_tickers(None)
```

`tests/unit/scripts/test_sync_sp500_members.py`:

```python
"""sync_sp500_members.py against a throwaway livewire checkout in tmp_path.

The fake preset holds the real vendored tickers, so the happy path runs on
real constituents. The two failure cases mutate that list (a duplicate, and a
truncation to 449).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from uw_scan.sources.sp500_members import sp500_members

_PATH = Path(__file__).resolve().parents[3] / "scripts/research/sync_sp500_members.py"
_spec = importlib.util.spec_from_file_location("sync_sp500_members", _PATH)
sync = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sync
_spec.loader.exec_module(sync)


def _livewire(tmp_path: Path, tickers: list[str]) -> Path:
    root = tmp_path / "livewire"
    (root / "presets").mkdir(parents=True)
    (root / "presets" / "sp500.json").write_text(
        json.dumps({"name": "sp500", "source": "test preset", "tickers": tickers})
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "commit", "-q", "--allow-empty", "-m", "fixture"],
        check=True,
    )
    return root


def test_sync_writes_the_sorted_list_with_the_commit_hash(tmp_path):
    tickers = list(sp500_members())
    root = _livewire(tmp_path, tickers)
    out = tmp_path / "sp500_members.json"
    assert sync.main(["--livewire", str(root), "--out", str(out), "--as-of", "2026-09-26"]) == 0
    body = json.loads(out.read_text())
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    assert body["source"] == f"livewire presets/sp500.json @ {head}"
    assert body["as_of"] == "2026-09-26"
    assert body["tickers"] == sorted(tickers)


def test_a_duplicate_is_refused_and_nothing_is_written(tmp_path):
    tickers = list(sp500_members())
    root = _livewire(tmp_path, tickers + [tickers[0]])
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit):
        sync.main(["--livewire", str(root), "--out", str(out)])
    assert not out.exists()


def test_a_short_list_is_refused_and_nothing_is_written(tmp_path):
    root = _livewire(tmp_path, list(sp500_members())[:449])
    out = tmp_path / "out.json"
    with pytest.raises(SystemExit):
        sync.main(["--livewire", str(root), "--out", str(out)])
    assert not out.exists()
```

- [ ] **Step 6: Run them and confirm they fail**

```bash
uv run pytest tests/unit/sources/test_sp500_members.py tests/unit/scripts/test_sync_sp500_members.py -q
```
Expected: `ModuleNotFoundError: No module named 'uw_scan.sources.sp500_members'`.

- [ ] **Step 7: Implement the reader, the sync script and the package-data entry.**

`src/uw_scan/sources/sp500_members.py`:

```python
"""S&P 500 membership for sector RS breadth: a VENDORED list, not an apex call.

Ruling 2026-09-26 (spec §4). On 2026-09-26, apex GET /v1/membership/sp500
returned about 35 rows with a null symbol and dead tickers (BHGE, SBC, PKI,
FISV, Q, FDXF, HONA, MRSH, VMRK), and it was missing META, XOM, AVGO, LIN,
MDT and ETN. A point-in-time read before 2026-09-17 returns about half the
index. livewire's presets/sp500.json is clean, but it is outside the lake
mount the argon container sees, so scripts/research/sync_sp500_members.py
copies it into sources/data/ and it ships as package data
(pyproject [tool.setuptools.package-data], same convention as
uw_scan.cards/data).

This is the CURRENT list, applied to every session by the nightly job and the
backfill alike. Breadth history is therefore survivorship-biased by
construction.
"""

from __future__ import annotations

import json
from collections import Counter
from functools import cache
from importlib.resources import files

#: Fewer names than this means a truncated or broken source, not an index.
MIN_MEMBERS = 450


class Sp500ListInvalid(ValueError):
    """The vendored list is unreadable or failed validation. Write no gics rows from it."""


def validate_tickers(tickers: object) -> tuple[str, ...]:
    """Upper-cased, sorted, distinct tickers, or Sp500ListInvalid.

    Shared by the runtime reader and the sync script, so the file cannot be
    written in a shape the reader would then refuse.
    """
    if not isinstance(tickers, list) or not all(isinstance(t, str) and t.strip() for t in tickers):
        raise Sp500ListInvalid("tickers must be a list of non-empty strings")
    norm = [t.strip().upper() for t in tickers]
    dupes = sorted(t for t, n in Counter(norm).items() if n > 1)
    if dupes:
        raise Sp500ListInvalid(f"duplicate tickers: {dupes[:10]}")
    if len(norm) < MIN_MEMBERS:
        raise Sp500ListInvalid(f"{len(norm)} tickers < {MIN_MEMBERS}")
    return tuple(sorted(norm))


@cache
def sp500_members() -> tuple[str, ...]:
    """The vendored current S&P 500 tickers. Raises Sp500ListInvalid."""
    try:
        body = json.loads(
            (files("uw_scan.sources") / "data" / "sp500_members.json").read_text()
        )
    except (OSError, ValueError) as exc:
        raise Sp500ListInvalid(f"cannot read vendored sp500 list: {exc!r}") from exc
    return validate_tickers(body.get("tickers") if isinstance(body, dict) else None)
```

`scripts/research/sync_sp500_members.py`:

```python
#!/usr/bin/env python
"""Vendor livewire's S&P 500 list into argon for sector RS breadth.

Why it is vendored (ruling 2026-09-26, spec §4): apex's membership route is
defective (null symbols, dead tickers, META/XOM missing), and livewire's
presets/sp500.json, which is clean, is not in the lake mount the argon
container sees. Re-run this whenever livewire updates the preset, then commit
the result.

It refuses with SystemExit, writing nothing, on duplicates or fewer than 450
names. It uses the same validator the runtime reader applies.

Reproduce:
    uv run python scripts/research/sync_sp500_members.py --livewire ~/projects/livewire
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

from uw_scan.sources.sp500_members import Sp500ListInvalid, validate_tickers

DEFAULT_OUT = (
    Path(__file__).resolve().parents[2] / "src/uw_scan/sources/data/sp500_members.json"
)


def build(livewire: Path, as_of: date) -> dict[str, object]:
    preset = json.loads((livewire / "presets" / "sp500.json").read_text())
    try:
        tickers = validate_tickers(preset.get("tickers") if isinstance(preset, dict) else None)
    except Sp500ListInvalid as exc:
        raise SystemExit(f"refusing to vendor {livewire}/presets/sp500.json: {exc}") from exc
    commit = subprocess.run(
        ["git", "-C", str(livewire), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "as_of": as_of.isoformat(),
        "source": f"livewire presets/sp500.json @ {commit}",
        "source_note": preset.get("source"),
        "tickers": list(tickers),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vendor livewire presets/sp500.json into argon")
    p.add_argument("--livewire", type=Path, default=Path.home() / "projects" / "livewire")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    args = p.parse_args(argv)
    body = build(args.livewire.expanduser(), args.as_of)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(body, indent=1) + "\n")
    print(f"wrote {args.out}: {len(body['tickers'])} tickers from {body['source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`pyproject.toml`: under `[tool.setuptools.package-data]` (lines 76–81), add this after the `"uw_scan.cards" = ["data/*.json", "data/*.md"]` line (line 77). It follows the existing per-package `data/` convention; `cards/canary_calibration.py:13-14` reads its file the same way, through `importlib.resources.files`.

```toml
# Vendored S&P 500 list for sector RS breadth, read at RUNTIME by
# sources/sp500_members.py; must ship in the wheel.
"uw_scan.sources" = ["data/*.json"]
```

- [ ] **Step 8: Generate the vendored file** (reads the local livewire checkout; no network)

```bash
uv run python scripts/research/sync_sp500_members.py --livewire ~/projects/livewire
```
Expected: `wrote …/src/uw_scan/sources/data/sp500_members.json: 503 tickers from livewire presets/sp500.json @ <HEAD>`. On 2026-09-26 the local livewire HEAD was `471e963aac82f6b3590f721160c70b99100d670b`, and the preset held 503 unique tickers including META, XOM, AVGO, BRK.B and BF.B. The preset's own `source` field reads "S&P 500 GICS classification (Wikipedia, March 2026)"; the script keeps it as `source_note`.

- [ ] **Step 9: Run the tests, and check the file ships in the wheel**

```bash
uv run pytest tests/unit/sources/test_sp500_members.py tests/unit/scripts/test_sync_sp500_members.py tests/unit/sources/test_apex_bulk.py -q
uv run ruff check src/uw_scan/sources/sp500_members.py scripts/research/sync_sp500_members.py tests/unit/sources/test_sp500_members.py tests/unit/scripts/test_sync_sp500_members.py
d=$(mktemp -d) && uv build --wheel --out-dir "$d" -q && unzip -l "$d"/*.whl | grep sources/data/sp500_members.json
```
Expected: all tests pass, and the `unzip` line lists `uw_scan/sources/data/sp500_members.json`. The Docker image runs `uv sync` over a copied `src/` (`docker/app.Dockerfile:28,32,47`), so the file is present there either way. The package-data entry is what keeps it in a built wheel.

- [ ] **Step 10: Commit**

```bash
git add src/uw_scan/sources/apex.py src/uw_scan/sources/sp500_members.py src/uw_scan/sources/data/sp500_members.json scripts/research/sync_sp500_members.py pyproject.toml tests/unit/sources/test_apex_bulk.py tests/unit/sources/test_sp500_members.py tests/unit/scripts/test_sync_sp500_members.py
git commit -m "feat(sector-rs): apex bulk daily closes + vendored S&P 500 list with sync script"
```

---

### Task 5: `company_sector`: `sectors_for` + widen the refresh universe to S&P 500 members

**Files**
- Modify: `src/uw_scan/storage/company_sector.py`. Replace `tickers_needing_fetch` (lines 45–71) and add `sectors_for` after it.
- Modify: `src/uw_scan/worker/jobs/company_sector_refresh.py`. Update the module docstring's COST section (lines 21–35), the imports (lines 45–54), and `company_sector_refresh` (lines 90–102).
- Modify: `src/uw_scan/worker/scheduler.py`. Change the `_company_sector_refresh` wrapper (lines 1053–1066) to pass the real fetcher.
- Create: `tests/integration/storage/test_company_sector_sp500.py`
- Create: `tests/unit/worker/test_company_sector_refresh_universe.py`

**Interfaces**
- Consumes: `sp500_members`, `Sp500ListInvalid` (Task 4).
- Produces:
```python
CompanySectorRepository.tickers_needing_fetch(self, limit: int, extra: Sequence[str] = ()) -> list[str]
CompanySectorRepository.sectors_for(self, tickers: Sequence[str]) -> dict[str, str | None]
company_sector_refresh(*, conn, client, schema="uw_scan", max_calls=DEFAULT_MAX_CALLS, include_sp500: bool = False) -> dict[str, int]
```
`include_sp500=False` (the default) means no widening. Only the scheduler wrapper passes `True`. The list is static, so this is not about network access. It is opt-in because the existing integration tests in `tests/integration/worker/test_company_type_routing.py` (lines 210, 229, 346, 352) size `max_calls` for their `ZZ*` universe, and 503 S&P names sorting ahead of those tickers would push them out of the capped run. With the flag off, those tests stay unchanged.

- [ ] **Step 1: Write the failing tests**

`tests/integration/storage/test_company_sector_sp500.py`:

```python
"""The sector-fill universe widens to S&P 500 members; sectors_for reads the cache.

GE's NULL is a labelled test double for "asked and the vendor had no sector".
It makes no claim about GE's real classification.
"""

from __future__ import annotations

from uw_scan.storage.company_sector import CompanySectorRepository


def _repo(seeded) -> CompanySectorRepository:
    return CompanySectorRepository(seeded.conn, schema=seeded._schema)


def test_extra_names_are_asked_once_uppercased_and_skip_known_rows(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert("AAPL", "Technology")
    out = repo.tickers_needing_fetch(5000, extra=["GE", "pkg", "AAPL", "GE"])
    assert "GE" in out and "PKG" in out
    assert "AAPL" not in out
    assert out == sorted(set(out))  # UNION dedupes; ordering kept


def test_sectors_for_separates_never_asked_from_asked_null(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert("AAPL", "Technology")
    repo.upsert("GE", None)
    assert repo.sectors_for(["aapl", "GE", "PKG"]) == {"AAPL": "Technology", "GE": None}
    assert repo.sectors_for([]) == {}
```

`tests/unit/worker/test_company_sector_refresh_universe.py`:

```python
"""company_sector_refresh unions the vendored S&P 500 list into its universe only when asked."""

from __future__ import annotations

import logging

import uw_scan.worker.jobs.company_sector_refresh as job
from uw_scan.sources.sp500_members import Sp500ListInvalid


class _FakeRepo:
    last: "_FakeRepo | None" = None

    def __init__(self, conn, *, schema: str = "uw_scan") -> None:
        self.extra_seen: tuple[str, ...] | None = None
        _FakeRepo.last = self

    def tickers_needing_fetch(self, limit: int, extra=()) -> list[str]:
        self.extra_seen = tuple(extra)
        return []

    def coverage(self) -> dict[str, int]:
        return {"universe": 0, "fetched": 0, "classified": 0}


def test_sp500_members_are_unioned_when_asked(monkeypatch):
    monkeypatch.setattr(job, "CompanySectorRepository", _FakeRepo)
    monkeypatch.setattr(job, "sp500_members", lambda: ("GE", "GOOGL", "PKG"))
    job.company_sector_refresh(conn=None, client=None, include_sp500=True)
    assert _FakeRepo.last.extra_seen == ("GE", "GOOGL", "PKG")


def test_invalid_vendored_list_falls_back_to_the_universe_and_says_so(monkeypatch, caplog):
    def invalid():
        raise Sp500ListInvalid("449 tickers < 450")

    monkeypatch.setattr(job, "CompanySectorRepository", _FakeRepo)
    monkeypatch.setattr(job, "sp500_members", invalid)
    with caplog.at_level(logging.ERROR):
        job.company_sector_refresh(conn=None, client=None, include_sp500=True)
    assert _FakeRepo.last.extra_seen == ()
    assert "vendored sp500 list invalid" in caplog.text


def test_default_does_not_widen(monkeypatch):
    def must_not_read():
        raise AssertionError("the list must not be read when include_sp500 is False")

    monkeypatch.setattr(job, "CompanySectorRepository", _FakeRepo)
    monkeypatch.setattr(job, "sp500_members", must_not_read)
    job.company_sector_refresh(conn=None, client=None)
    assert _FakeRepo.last.extra_seen == ()
```

- [ ] **Step 2: Run them and confirm they fail**

```bash
uv run pytest tests/unit/worker/test_company_sector_refresh_universe.py tests/integration/storage/test_company_sector_sp500.py -q
```
Expected: `TypeError: company_sector_refresh() got an unexpected keyword argument 'include_sp500'`, and `TypeError: ... unexpected keyword argument 'extra'` / `AttributeError: ... 'sectors_for'`.

- [ ] **Step 3: Implement the storage change.** Replace `tickers_needing_fetch` in `src/uw_scan/storage/company_sector.py` (lines 45–71). Add `from collections.abc import Sequence` next to `from typing import Any`.

```python
    def tickers_needing_fetch(self, limit: int, extra: Sequence[str] = ()) -> list[str]:
        """Universe names with no sector row yet, plus `extra` names with none.

        `extra` is how current S&P 500 members join the universe (sector RS
        breadth, spec 2026-09-26 §4). It is a UNION, so a name in both is asked
        once. Both legs are uppercased because `upsert` stores the uppercase
        form. A lowercase ticker would otherwise be asked, written uppercase,
        then fail this join and be asked again every run, one UW call per name,
        silently.

        Only names absent from the table: a recorded NULL means the vendor was
        asked and had no sector. Re-asking it every run would spend the budget
        on the one answer that cannot change the routing. A periodic re-ask
        belongs in a separate refresh pass keyed on `fetched_at`. It is not
        built, and not indexed for, until something needs it.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT u.ticker
                      FROM (SELECT upper(f.ticker) AS ticker
                              FROM {self._schema}.fundamental_universe f
                             WHERE f.removed_at IS NULL
                            UNION
                            SELECT upper(x) FROM unnest(%s::text[]) AS x) u
                      LEFT JOIN {self._schema}.company_sector c ON c.ticker = u.ticker
                     WHERE c.ticker IS NULL
                     ORDER BY u.ticker
                     LIMIT %s""",
                (list(extra), limit),
            )
            return [r[0] for r in cur.fetchall()]

    def sectors_for(self, tickers: Sequence[str]) -> dict[str, str | None]:
        """{TICKER: sector} for names that have a row. An absent key means never
        asked; a None value means asked, and the vendor had no sector."""
        if not tickers:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, sector FROM {self._schema}.company_sector
                     WHERE ticker = ANY(%s)""",
                ([t.upper() for t in tickers],),
            )
            return {t: s for t, s in cur.fetchall()}
```

- [ ] **Step 4: Implement the job change** in `src/uw_scan/worker/jobs/company_sector_refresh.py`.

Append to the COST section of the docstring (after line 35):

```text
S&P 500 WIDENING (sector RS breadth, spec 2026-09-26 §4)
--------------------------------------------------------
When the scheduler passes `include_sp500=True`, the vendored current S&P 500
list (sources/sp500_members.py, 503 names) is unioned into the universe.
That costs an estimated ~330 calls on the first run after deploy (members
minus the overlap), inside DEFAULT_MAX_CALLS, and zero afterwards. A list
that fails validation logs an error, and the run falls back to the
fundamental universe. A
ticker UW answers non-200 for (for example a class-share symbol spelled
differently at UW) is `failed`, not recorded, and is re-asked each run, as
for any other failure.
```

Replace the imports (lines 45–54) and the head of `company_sector_refresh` (lines 90–102):

```python
from __future__ import annotations

import logging
from typing import Any

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources.sp500_members import Sp500ListInvalid, sp500_members
from uw_scan.storage.company_sector import CompanySectorRepository
```

```python
def company_sector_refresh(
    *,
    conn: psycopg.Connection,
    client: UwClient,
    schema: str = "uw_scan",
    max_calls: int = DEFAULT_MAX_CALLS,
    include_sp500: bool = False,
) -> dict[str, int]:
    """Fill missing vendor sectors. Returns counters.

    `include_sp500=True` (the scheduler passes it) unions the vendored current
    S&P 500 list into the universe. It stays opt-in even though the list is
    static: the existing tests size `max_calls` for the fundamental universe
    alone.
    """
    repo = CompanySectorRepository(conn, schema=schema)
    extra: tuple[str, ...] = ()
    if include_sp500:
        try:
            extra = sp500_members()
        except Sp500ListInvalid as exc:
            log.error(
                "company_sector_refresh: vendored sp500 list invalid (%s); "
                "asking the fundamental universe only this run",
                exc,
            )
        else:
            log.info("company_sector_refresh: +%d sp500 members in universe", len(extra))
    # One over the cap, so "there was more" is observable rather than inferred
    # from `len(names) == max_calls` — which is also what a universe of exactly
    # `max_calls` looks like.
    names = repo.tickers_needing_fetch(max_calls + 1, extra=extra)
```
(The rest of the function, from `totals = {...}` on line 103 onward, is unchanged.)

- [ ] **Step 5: Wire the scheduler.** In `src/uw_scan/worker/scheduler.py`, change the `_company_sector_refresh` wrapper (lines 1053–1066) to:

```python
    def _company_sector_refresh() -> None:
        from uw_scan.worker.jobs.company_sector_refresh import company_sector_refresh

        with _external_api_recorder(settings) as recorder:
            with _uw_client(
                settings,
                telemetry_recorder=recorder,
                job_name="company_sector_refresh",
            ) as uw:
                with _repo(settings) as repo:
                    counters = company_sector_refresh(
                        conn=repo.conn,
                        client=uw,
                        schema=settings.db_schema,
                        include_sp500=True,
                    )
        logger.info("company_sector_refresh %s", counters)
```

- [ ] **Step 6: Run the new and existing tests**

```bash
uv run pytest tests/unit/worker/test_company_sector_refresh_universe.py tests/unit/worker/test_company_sector_routing.py -q
uv run pytest tests/integration/storage/test_company_sector_sp500.py tests/integration/worker/test_company_type_routing.py -q
uv run ruff check src/uw_scan/storage/company_sector.py src/uw_scan/worker/jobs/company_sector_refresh.py src/uw_scan/worker/scheduler.py
```
Expected: all pass. The existing routing tests are unchanged, which is the hermeticity proof for Review Focus 7.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/storage/company_sector.py src/uw_scan/worker/jobs/company_sector_refresh.py src/uw_scan/worker/scheduler.py tests/integration/storage/test_company_sector_sp500.py tests/unit/worker/test_company_sector_refresh_universe.py
git commit -m "feat(company-sector): widen sector fill to S&P 500 members; add sectors_for"
```

---

### Task 6: Nightly job `worker/jobs/sector_rs_daily.py` + config flag + scheduler registration

**Files**
- Create: `src/uw_scan/worker/jobs/sector_rs_daily.py`
- Modify: `src/uw_scan/config.py`. Add a field after `theta_harvester_enabled` (line 445), and a `from_env` kwarg after line 1121.
- Modify: `src/uw_scan/worker/scheduler.py`:
  - add predicate `_should_schedule_sector_rs_daily` after `_should_schedule_fundamentals_desk_rollup` (ends line 575);
  - add wrapper `_sector_rs_daily` after `_theta_harvester_markout` (lines 1072–1074);
  - add `sched.add_job` after the `earnings_reactions_compute` block (its `add_job` closes at line 2466), before `if _should_schedule_implied_move(settings):` (line 2468).
- Create: `tests/unit/worker/test_sector_rs_daily.py`
- Modify: `tests/unit/worker/test_scheduler_registration.py` (append tests)

**Interfaces**
- Consumes: `compute_group_rows`, `GroupSpec`, `SectorRsRow` (Task 2); `SectorRsRepository` (Task 3); `fetch_bulk_daily_closes`, `sp500_members`, `Sp500ListInvalid` (Task 4); `CompanySectorRepository.sectors_for` (Task 5); `WatchlistChainRepository.counts_by_chain` / `tickers_in_chain` (`storage/watchlist_chain.py:212,229`); `Repository.list_daily_ohlc(ticker, *, limit)` (`storage/market_data.py:46`, newest-first, returns `DailyOhlcRow` with `close: Decimal`).
- Produces:
```python
BENCHMARK = "SPY"
SPDR_SECTOR_ETFS: dict[str, str]
FALLBACK_SYMBOLS: frozenset[str]
GROUP_KINDS: tuple[str, ...] = ("gics", "chain")
LOOKBACK_CALENDAR_DAYS = 400
def build_gics_groups(members: Iterable[str], sector_of: dict[str, str | None]) -> tuple[list[GroupSpec], int]
def chain_groups(conn: psycopg.Connection, schema: str) -> list[GroupSpec]
def load_closes(repo: Repository, symbols: Iterable[str], *, start: date, end: date, fetch_closes: ClosesFetcher = fetch_bulk_daily_closes, today: date | None = None) -> tuple[dict[str, list[tuple[date, float]]], set[str]]
def snap_sessions(spy: list[tuple[date, float]], dates: Iterable[date]) -> list[date]
def run_sector_rs(*, repo: Repository, schema: str, dates: Sequence[date], group_kinds: Sequence[str] = GROUP_KINDS, fetch_closes: ClosesFetcher = fetch_bulk_daily_closes) -> dict[str, int]
def sector_rs_daily(*, repo: Repository, schema: str, as_of: date, fetch_closes: ClosesFetcher = fetch_bulk_daily_closes) -> dict[str, int]
Settings.sector_rs_enabled: bool = False   # env UW_SCAN_SECTOR_RS_ENABLED
scheduler job id "sector_rs_daily", CronTrigger(hour=21, minute=30, day_of_week="mon-fri", timezone=settings.rth_tz), massive-0 / all
```

- [ ] **Step 1: Write the failing job test** at `tests/unit/worker/test_sector_rs_daily.py`

```python
"""sector_rs_daily job: membership, sources, refusals. All I/O is stubbed.

Closes come from Task 2's frozen REAL fixture (apex adjusted, as-of
2026-09-18). The S&P list (monkeypatched `sp500_members`), the sector map and
the chain map are stubs. GE's missing sector is a labelled test double for an
unclassified member.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

import uw_scan.worker.jobs.sector_rs_daily as job
from uw_scan.reports import sector_rs
from uw_scan.sources.sp500_members import Sp500ListInvalid
from uw_scan.storage.rows import DailyOhlcRow

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "reports" / "fixtures"
    / "sector_rs_closes_2026-09-18.json"
)
FRI = date(2026, 9, 18)


def _fixture() -> dict[str, dict[date, float]]:
    raw = json.loads(_FIXTURE.read_text())
    return {s: {date.fromisoformat(d): float(c) for d, c in rows} for s, rows in raw["closes"].items()}


def _fetch_closes(omit: tuple[str, ...] = ()):
    data = _fixture()

    def fetch(symbols, *, start, end):
        return {
            s: {d: c for d, c in data[s].items() if start <= d <= end}
            for s in symbols if s in data and s not in omit
        }
    return fetch


class _Store:
    rows: list = []

    def __init__(self, conn, *, schema="uw_scan"):
        pass

    def upsert_rows(self, rows):
        _Store.rows.extend(rows)
        return len(rows)


class _Sectors:
    def __init__(self, conn, *, schema="uw_scan"):
        pass

    def sectors_for(self, tickers):
        known = {"AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "GE": None}
        return {t: known[t] for t in tickers if t in known}


def _chains(mapping: dict[str, list[str]]):
    class _Chains:
        def __init__(self, conn, schema="uw_scan"):
            pass

        def counts_by_chain(self):
            return {k: len(v) for k, v in mapping.items()}

        def tickers_in_chain(self, chain):
            return mapping[chain]
    return _Chains


class _Repo:
    conn = None

    def __init__(self, ohlc: dict[str, dict[date, float]] | None = None):
        self._ohlc = ohlc or {}

    def list_daily_ohlc(self, ticker, *, limit=30):
        series = self._ohlc.get(ticker, {})
        stamp = datetime(2026, 9, 26, tzinfo=timezone.utc)
        return [
            DailyOhlcRow(ticker, d, None, None, None, Decimal(str(c)), None, "massive.com", stamp)
            for d, c in sorted(series.items(), reverse=True)[:limit]
        ]


@pytest.fixture
def wired(monkeypatch):
    _Store.rows = []
    monkeypatch.setattr(job, "SectorRsRepository", _Store)
    monkeypatch.setattr(job, "CompanySectorRepository", _Sectors)
    monkeypatch.setattr(job, "WatchlistChainRepository", _chains({}))
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL", "MSFT", "NVDA"))
    calls: list[str] = []
    real = sector_rs.compute_group_rows

    def spy_compute(as_of, groups, closes, **kw):
        calls.append(groups[0].kind)
        return real(as_of, groups, closes, **kw)
    monkeypatch.setattr(job, "compute_group_rows", spy_compute)
    return calls


def _run(as_of=FRI, **kw):
    kw.setdefault("repo", _Repo())
    kw.setdefault("fetch_closes", _fetch_closes())
    return job.sector_rs_daily(schema="uw_scan", as_of=as_of, **kw)


def test_writes_11_gics_rows_and_zero_chain_rows_on_empty_watchlist_chain(wired, monkeypatch):
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL", "GE", "MSFT", "NVDA"))
    c = _run()
    assert c["gics_rows"] == 11 and c["chain_rows"] == 0 and c["rows"] == 11
    assert c["unclassified"] == 1  # GE: asked, no sector
    assert wired == ["gics"]  # compute once for gics; the empty chain kind is not computed
    tech = next(r for r in _Store.rows if r.group_key == "Technology")
    assert (tech.rs_symbol, tech.n_members, tech.degraded, tech.source) == ("XLK", 3, False, "apex")


def test_other_ten_sectors_write_null_rs_rows_when_their_etf_is_absent(wired):
    _run()
    others = [r for r in _Store.rows if r.group_key != "Technology"]
    assert len(others) == 10
    assert all(r.degraded and r.n_members == 0 for r in others)
    assert all(v is None for r in others for v in r.rs.values())


def test_compute_runs_once_per_group_kind(wired, monkeypatch):
    monkeypatch.setattr(job, "WatchlistChainRepository", _chains({"Semi-Logic": ["NVDA"]}))
    c = _run()
    assert wired == ["gics", "chain"]
    assert c["chain_rows"] == 1
    (chain,) = [r for r in _Store.rows if r.group_kind == "chain"]
    assert (chain.weighting, chain.rs_symbol, chain.n_priced) == ("equal", None, 1)


def test_saturday_as_of_writes_friday_rows(wired):
    _run(as_of=date(2026, 9, 19))
    assert {r.as_of for r in _Store.rows} == {FRI}


def test_spy_missing_everywhere_aborts_without_writing(wired):
    with pytest.raises(RuntimeError, match="SPY"):
        _run(fetch_closes=_fetch_closes(omit=("SPY",)))
    assert _Store.rows == []


def test_spy_too_short_for_earliest_session_aborts_without_writing(wired):
    with pytest.raises(ValueError, match="12m"):
        job.run_sector_rs(
            repo=_Repo(), schema="uw_scan", dates=[date(2025, 10, 1), FRI],
            fetch_closes=_fetch_closes(),
        )
    assert _Store.rows == []


def test_spy_from_daily_ohlc_tags_every_row(wired):
    c = _run(repo=_Repo(ohlc={"SPY": _fixture()["SPY"]}), fetch_closes=_fetch_closes(omit=("SPY",)))
    assert c["daily_ohlc_rows"] == 11
    assert {r.source for r in _Store.rows} == {"daily_ohlc"}


def test_invalid_vendored_list_aborts_gics_with_error_and_chain_still_writes(wired, monkeypatch, caplog):
    def invalid():
        raise Sp500ListInvalid("449 tickers < 450")

    monkeypatch.setattr(job, "sp500_members", invalid)
    monkeypatch.setattr(job, "WatchlistChainRepository", _chains({"Semi-Logic": ["NVDA"]}))
    with caplog.at_level(logging.ERROR, logger=job.__name__):
        c = _run()
    assert c["membership_invalid"] == 1
    assert c["gics_rows"] == 0 and c["chain_rows"] == 1
    assert {r.group_kind for r in _Store.rows} == {"chain"}
    assert "vendored sp500 list invalid" in caplog.text


def test_counters_are_logged(wired, monkeypatch, caplog):
    monkeypatch.setattr(job, "sp500_members", lambda: ("AAPL",))
    with caplog.at_level(logging.INFO, logger=job.__name__):
        _run()
    assert "sector_rs {" in caplog.text and "'gics_rows': 11" in caplog.text
    assert "n_priced 1 / n_members 1" in caplog.text
    assert "survivorship" in caplog.text


def test_build_gics_groups_keeps_the_eleven_and_counts_the_rest():
    groups, unclassified = job.build_gics_groups(
        ["aapl", "GE", "PKG"], {"AAPL": "Technology", "GE": None}
    )
    assert [g.key for g in groups] == list(job.SPDR_SECTOR_ETFS)
    assert next(g for g in groups if g.key == "Technology").members == ("AAPL",)
    assert unclassified == 2  # GE NULL sector, PKG never asked
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/unit/worker/test_sector_rs_daily.py -q
```
Expected: `ModuleNotFoundError: No module named 'uw_scan.worker.jobs.sector_rs_daily'`.

- [ ] **Step 3: Implement** `src/uw_scan/worker/jobs/sector_rs_daily.py`

```python
"""Nightly sector RS + breadth (`sector_rs_daily`, migration 152).

Spec: docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md §2–§5.
Zero UW spend: apex adjusted daily bars (listing=any), with a daily_ohlc
fallback for SPY and the 11 SPDR ETFs only. `run_sector_rs` is the ONE core.
The nightly wrapper below and scripts/backfill/sector_rs_backfill.py both call
it, so a backfilled row and a nightly row for one session are the same row.

Membership:
- gics  — the vendored CURRENT S&P 500 list (sources/sp500_members.py,
          copied from livewire presets/sp500.json; apex's membership route is
          not used, see that module), applied to every session, nightly and
          backfill alike. Mapped ticker → vendor sector through
          company_sector. A member with no row, a NULL sector, or a label
          outside the 11 belongs to no group and is counted as `unclassified`.
          Classification is also current over the whole window (spec §4).
          SURVIVORSHIP: former members are absent from n_members, and a
          delisted name has no adjusted bars (apex files it under `missing`),
          so it is unpriced. Breadth history describes today's index, and the
          run's log line says so.
- chain — watchlist_chain as it is TODAY. argon keeps no chain-membership
          history, so backfilled chain rows carry today's membership. That
          look-ahead is one reason the §6 probe reads gics rows only.

Refusals (never write a misleading row):
- SPY unavailable from apex and daily_ohlc → RuntimeError, nothing written.
- SPY too short for the 12m window on the earliest session → ValueError,
  nothing written (checked before the first upsert).
- the vendored sp500 list fails validation → the run's gics rows are
  skipped with a logged error (`membership_invalid` = 1); chain rows still write.

A requested date that is not a session snaps to the last SPY session on or
before it, so a Saturday run rewrites Friday's rows instead of adding a
duplicate row labelled Saturday.
"""

from __future__ import annotations

import logging
from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import date, timedelta

import psycopg

from uw_scan.reports.sector_rs import (
    WINDOWS,
    GroupSpec,
    SectorRsRow,
    compute_group_rows,
)
from uw_scan.sources.apex import fetch_bulk_daily_closes
from uw_scan.sources.sp500_members import Sp500ListInvalid, sp500_members
from uw_scan.storage.company_sector import CompanySectorRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.sector_rs import SectorRsRepository
from uw_scan.storage.watchlist_chain import WatchlistChainRepository

log = logging.getLogger(__name__)

BENCHMARK = "SPY"
#: Vendor sector label (company_sector.sector; all 11 present in
#: option_wizard_local on 2026-09-26) → SPDR sector ETF. Fixed, spec §2.
SPDR_SECTOR_ETFS: dict[str, str] = {
    "Technology": "XLK",
    "Communication Services": "XLC",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Basic Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}
#: First trustworthy session of an ETF's adjusted history (spec §4). XLF's
#: XLRE spin-off is double-booked in livewire Silver (false +31% jump on
#: 2016-09-19); drop the entry and re-run the backfill with --force for XLF
#: once livewire #157 fixes the seam.
ETF_RS_VALID_FROM: dict[str, date] = {"XLF": date(2016, 9, 19)}
#: The only symbols allowed to fall back to daily_ohlc (spec §4).
FALLBACK_SYMBOLS: frozenset[str] = frozenset({BENCHMARK, *SPDR_SECTOR_ETFS.values()})
GROUP_KINDS: tuple[str, ...] = ("gics", "chain")
#: 253 sessions is about 367 calendar days; 400 clears the holidays with margin.
LOOKBACK_CALENDAR_DAYS = 400
_MIN_BENCH_CLOSES = max(WINDOWS.values()) + 1

Closes = dict[str, list[tuple[date, float]]]
ClosesFetcher = Callable[..., dict[str, dict[date, float]]]


def build_gics_groups(
    members: Iterable[str], sector_of: dict[str, str | None]
) -> tuple[list[GroupSpec], int]:
    """The 11 etf-weighted groups, plus the count of members in none of them."""
    by_sector: dict[str, list[str]] = {s: [] for s in SPDR_SECTOR_ETFS}
    unclassified = 0
    for m in sorted({t.upper() for t in members}):
        sector = sector_of.get(m)
        if sector is not None and sector in by_sector:
            by_sector[sector].append(m)
        else:
            unclassified += 1
    groups = [
        GroupSpec(
            "gics", sector, "etf", etf, tuple(by_sector[sector]),
            rs_valid_from=ETF_RS_VALID_FROM.get(etf),
        )
        for sector, etf in SPDR_SECTOR_ETFS.items()
    ]
    return groups, unclassified


def chain_groups(conn: psycopg.Connection, schema: str) -> list[GroupSpec]:
    """Every chain with an active member, equal-weighted (no chain ETF exists)."""
    repo = WatchlistChainRepository(conn, schema=schema)
    return [
        GroupSpec("chain", chain, "equal", None, tuple(repo.tickers_in_chain(chain)))
        for chain in sorted(repo.counts_by_chain())
    ]


def load_closes(
    repo: Repository,
    symbols: Iterable[str],
    *,
    start: date,
    end: date,
    fetch_closes: ClosesFetcher = fetch_bulk_daily_closes,
    today: date | None = None,
) -> tuple[Closes, set[str]]:
    """Ascending closes per symbol, plus the set that came from daily_ohlc.

    apex first. daily_ohlc only for FALLBACK_SYMBOLS that apex did not serve.
    `list_daily_ohlc` returns the newest `limit` rows, so the limit is the
    calendar-day distance from today back to `start`, which always reaches it.
    """
    wanted = sorted({s.upper() for s in symbols})
    got = dict(fetch_closes(wanted, start=start, end=end))
    fell_back: set[str] = set()
    limit = max(1, ((today or date.today()) - start).days + 1)
    for sym in sorted(FALLBACK_SYMBOLS.intersection(wanted) - set(got)):
        rows = repo.list_daily_ohlc(sym, limit=limit)
        series = {r.date: float(r.close) for r in rows if start <= r.date <= end}
        if series:
            got[sym] = series
            fell_back.add(sym)
    return {s: sorted(v.items()) for s, v in got.items()}, fell_back


def snap_sessions(spy: list[tuple[date, float]], dates: Iterable[date]) -> list[date]:
    """Each requested date → the last SPY session ≤ it; deduped, ascending."""
    out: set[date] = set()
    for d in dates:
        i = bisect_right(spy, (d, float("inf")))
        if i:
            out.add(spy[i - 1][0])
    return sorted(out)


def _tag_source(row: SectorRsRow, fell_back: set[str]) -> SectorRsRow:
    """'daily_ohlc' when the row's benchmark or RS numerator came from the fallback."""
    if BENCHMARK in fell_back or (row.rs_symbol is not None and row.rs_symbol in fell_back):
        return replace(row, source="daily_ohlc")
    return row


def run_sector_rs(
    *,
    repo: Repository,
    schema: str,
    dates: Sequence[date],
    group_kinds: Sequence[str] = GROUP_KINDS,
    fetch_closes: ClosesFetcher = fetch_bulk_daily_closes,
) -> dict[str, int]:
    """Compute and upsert sector_rs_daily for each requested date. Returns counters."""
    counters = dict.fromkeys(
        (
            "sessions", "rows", "gics_rows", "chain_rows", "degraded",
            "daily_ohlc_rows", "unclassified", "membership_invalid",
            "gics_n_members", "gics_n_priced",
        ),
        0,
    )
    unknown = set(group_kinds) - set(GROUP_KINDS)
    if unknown:
        raise ValueError(f"unknown group_kind {sorted(unknown)}")
    if not dates:
        return counters
    start = min(dates) - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    end = max(dates)

    spy_closes, spy_fell_back = load_closes(
        repo, [BENCHMARK], start=start, end=end, fetch_closes=fetch_closes
    )
    spy = spy_closes.get(BENCHMARK)
    if not spy:
        raise RuntimeError(
            "SPY closes unavailable from apex and daily_ohlc; refusing to write sector_rs_daily"
        )
    sessions = snap_sessions(spy, dates)
    if not sessions:
        return counters
    first_bench = bisect_right(spy, (sessions[0], float("inf")))
    if first_bench < _MIN_BENCH_CLOSES:
        raise ValueError(
            f"{BENCHMARK} has {first_bench} closes <= {sessions[0]}; window 12m needs "
            f"{_MIN_BENCH_CLOSES}; nothing written"
        )

    groups_by_kind: dict[str, dict[date, list[GroupSpec]]] = {}
    symbols: set[str] = set()
    if "chain" in group_kinds:
        chains = chain_groups(repo.conn, schema)
        groups_by_kind["chain"] = {s: chains for s in sessions}
        symbols.update(m for g in chains for m in g.members)
    if "gics" in group_kinds:
        # The vendored CURRENT list, applied to every session (spec §4 ruling).
        try:
            members = sp500_members()
        except Sp500ListInvalid as exc:
            counters["membership_invalid"] = 1
            log.error(
                "sector_rs: vendored sp500 list invalid (%s); gics rows skipped for %d sessions",
                exc,
                len(sessions),
            )
        else:
            sector_of = CompanySectorRepository(repo.conn, schema=schema).sectors_for(list(members))
            gics_groups, counters["unclassified"] = build_gics_groups(members, sector_of)
            groups_by_kind["gics"] = {s: gics_groups for s in sessions}
            symbols.update(members)
            symbols.update(SPDR_SECTOR_ETFS.values())
    symbols.discard(BENCHMARK)
    closes, fell_back = load_closes(
        repo, symbols, start=start, end=end, fetch_closes=fetch_closes
    )
    closes[BENCHMARK] = spy
    fell_back |= spy_fell_back

    store = SectorRsRepository(repo.conn, schema=schema)
    for s in sessions:
        for kind in GROUP_KINDS:
            groups = groups_by_kind.get(kind, {}).get(s)
            if not groups:
                continue
            rows = [
                _tag_source(r, fell_back)
                for r in compute_group_rows(s, groups, closes, benchmark=BENCHMARK)
            ]
            store.upsert_rows(rows)
            counters[f"{kind}_rows"] += len(rows)
            counters["rows"] += len(rows)
            counters["degraded"] += sum(r.degraded for r in rows)
            counters["daily_ohlc_rows"] += sum(r.source == "daily_ohlc" for r in rows)
            if kind == "gics":  # last session's totals, for the survivorship log line
                counters["gics_n_members"] = sum(r.n_members for r in rows)
                counters["gics_n_priced"] = sum(r.n_priced for r in rows)
        counters["sessions"] += 1
    log.info(
        "sector_rs %s | gics n_priced %d / n_members %d on the last session; "
        "membership is TODAY's sp500 applied to every session and delisted names "
        "are unpriced, so breadth is survivorship-biased",
        counters,
        counters["gics_n_priced"],
        counters["gics_n_members"],
    )
    return counters


def sector_rs_daily(
    *,
    repo: Repository,
    schema: str,
    as_of: date,
    fetch_closes: ClosesFetcher = fetch_bulk_daily_closes,
) -> dict[str, int]:
    """Nightly entry point: one session's rows, both group kinds."""
    return run_sector_rs(
        repo=repo,
        schema=schema,
        dates=[as_of],
        fetch_closes=fetch_closes,
    )
```

- [ ] **Step 4: Run the job tests and confirm they pass**

```bash
uv run pytest tests/unit/worker/test_sector_rs_daily.py -q
uv run ruff check src/uw_scan/worker/jobs/sector_rs_daily.py tests/unit/worker/test_sector_rs_daily.py
```
Expected: 10 passed.

- [ ] **Step 5: Write the failing scheduler tests.** Append to `tests/unit/worker/test_scheduler_registration.py`:

```python
def test_sector_rs_daily_registered_on_primary_massive_when_enabled(monkeypatch):
    jobs = _registered_jobs(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
        UW_SCAN_SECTOR_RS_ENABLED="true",
    )
    assert "sector_rs_daily" in jobs
    trig = str(jobs["sector_rs_daily"])
    assert "day_of_week='mon-fri'" in trig
    assert "hour='21'" in trig and "minute='30'" in trig


def test_sector_rs_daily_absent_by_default(monkeypatch):
    monkeypatch.delenv("UW_SCAN_SECTOR_RS_ENABLED", raising=False)
    ids = _registered_job_ids(
        monkeypatch,
        UW_SCAN_WORKER_ROLE="massive",
        UW_SCAN_WORKER_INDEX="0",
        UW_SCAN_WORKER_COUNT="1",
    )
    assert "sector_rs_daily" not in ids
    assert "fundamental_refresh" in ids  # harness sanity: a massive-0 sibling still wires


def test_sector_rs_daily_absent_off_massive_0(monkeypatch):
    for role, index, count in (("massive", "1", "2"), ("uw", "0", "1")):
        ids = _registered_job_ids(
            monkeypatch,
            UW_SCAN_WORKER_ROLE=role,
            UW_SCAN_WORKER_INDEX=index,
            UW_SCAN_WORKER_COUNT=count,
            UW_SCAN_SECTOR_RS_ENABLED="true",
        )
        assert "sector_rs_daily" not in ids, (role, index)
```

```bash
uv run pytest tests/unit/worker/test_scheduler_registration.py -q -k sector_rs
```
Expected: `test_sector_rs_daily_registered_on_primary_massive_when_enabled` fails (`assert 'sector_rs_daily' in {...}`).

- [ ] **Step 6: Add the config flag.** In `src/uw_scan/config.py`, after line 445 (`theta_harvester_enabled: bool = True`):

```python
    # Sector RS + breadth (nightly 21:30 ET Mon–Fri, massive-0). Zero UW spend:
    # apex bars plus a daily_ohlc fallback for SPY and the 11 SPDR ETFs.
    # Default OFF: flip on the mini after scripts/backfill/sector_rs_backfill.py
    # lands (spec 2026-09-26 §5).
    sector_rs_enabled: bool = False
```

In `from_env`, after line 1121 (`theta_harvester_enabled=_env_bool(...)`):

```python
            sector_rs_enabled=_env_bool("UW_SCAN_SECTOR_RS_ENABLED", False),
```

- [ ] **Step 7: Register the job.** In `src/uw_scan/worker/scheduler.py`:

(a) After `_should_schedule_fundamentals_desk_rollup` (ends line 575):

```python
def _should_schedule_sector_rs_daily(settings: Settings) -> bool:
    """Single owner for the nightly sector RS + breadth upserts. apex bars plus
    a daily_ohlc fallback, no UW/IB spend → pin to massive-0, same as
    earnings_reactions / chanlun_lifecycle. Gated on `sector_rs_enabled`
    (default off until the backfill lands on the mini)."""
    if not settings.sector_rs_enabled:
        return False
    role = settings.worker_role.lower()
    return role == "all" or (role == "massive" and settings.worker_index == 0)
```

(b) After the `_theta_harvester_markout` wrapper (lines 1072–1074):

```python
    def _sector_rs_daily() -> None:
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo

        from uw_scan.worker.jobs.sector_rs_daily import sector_rs_daily

        as_of = _dt.now(ZoneInfo(settings.rth_tz)).date()
        with _repo(settings) as repo:
            counters = sector_rs_daily(repo=repo, schema=settings.db_schema, as_of=as_of)
        logger.info("sector_rs_daily %s", counters)
```

(c) After the `earnings_reactions_compute` `add_job` block (after line 2466), at the same 4-space indentation as `if _should_schedule_earnings_reactions(settings):`:

```python
    if _should_schedule_sector_rs_daily(settings):
        # Sector RS + breadth at 21:30 ET Mon–Fri: after ohlc_pull (17:30), so
        # the daily_ohlc fallback holds tonight's SPY/ETF closes, and after the
        # 21:00 freshness monitor. Zero UW spend → massive-0.
        sched.add_job(
            _sector_rs_daily,
            CronTrigger(hour=21, minute=30, day_of_week="mon-fri", timezone=settings.rth_tz),
            id="sector_rs_daily",
            name="Sector RS + breadth (gics ETFs + watchlist chains)",
            max_instances=1,
            coalesce=True,
        )
```

- [ ] **Step 8: Run the tests and confirm they pass**

```bash
uv run pytest tests/unit/worker/test_scheduler_registration.py tests/unit/worker/test_sector_rs_daily.py tests/unit/test_config.py -q
uv run ruff check src/uw_scan/config.py src/uw_scan/worker/scheduler.py
```
Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/worker/jobs/sector_rs_daily.py src/uw_scan/config.py src/uw_scan/worker/scheduler.py tests/unit/worker/test_sector_rs_daily.py tests/unit/worker/test_scheduler_registration.py
git commit -m "feat(sector-rs): nightly sector_rs_daily job (massive-0, 21:30 ET, flag off)"
```

---

### Task 7: Resumable backfill `scripts/backfill/sector_rs_backfill.py`

**Files**
- Create: `scripts/backfill/sector_rs_backfill.py` (argparse, `Settings.from_env()` and `psycopg.connect(settings.db_dsn())`, following `scripts/backfill/theta_harvester_backfill.py:82-111`)
- Create: `tests/unit/scripts/test_sector_rs_backfill.py`

**Interfaces**
- Consumes: `run_sector_rs`, `load_closes`, `BENCHMARK`, `GROUP_KINDS` (Task 6); `SectorRsRepository.dates_present` (Task 3).
- Produces: CLI `--start --end [--group-kind gics|chain ...] [--force] [--chunk-sessions N]`; pure helpers `pending_sessions(sessions: list[date], present: set[date], force: bool) -> list[date]` and `chunked(items: list[date], size: int) -> list[list[date]]`; pre-flight `preflight_etf_history(client: httpx.Client | None = None) -> None` (raises SystemExit when apex's Silver does not yet serve the #157 history).

- [ ] **Step 1: Write the failing test** at `tests/unit/scripts/test_sector_rs_backfill.py`

```python
"""Resume/chunk helpers and the #157 pre-flight of scripts/backfill/sector_rs_backfill.py.

Loaded by file path because scripts/ is not a package (same as
test_chanlun_probe_smoke.py). The session dates are real NYSE sessions of
September 2026.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import httpx
import pytest

_PATH = Path(__file__).resolve().parents[3] / "scripts/backfill/sector_rs_backfill.py"
_spec = importlib.util.spec_from_file_location("sector_rs_backfill", _PATH)
bf = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = bf
_spec.loader.exec_module(bf)

SESSIONS = [date(2026, 9, d) for d in (14, 15, 16, 17, 18)]


def test_pending_skips_present_unless_forced():
    present = {date(2026, 9, 15), date(2026, 9, 17)}
    assert bf.pending_sessions(SESSIONS, present, force=False) == [
        date(2026, 9, 14), date(2026, 9, 16), date(2026, 9, 18)
    ]
    assert bf.pending_sessions(SESSIONS, present, force=True) == SESSIONS


def test_chunked_preserves_order_and_rejects_nonpositive():
    assert bf.chunked(SESSIONS, 2) == [SESSIONS[0:2], SESSIONS[2:4], SESSIONS[4:5]]
    assert bf.chunked([], 3) == []
    with pytest.raises(ValueError):
        bf.chunked(SESSIONS, 0)


# The bar below is the REAL XLK adjusted bar of 2026-09-10 (apex, revision 80).
# Only its presence matters to the pre-flight, not its date.
_XLK_BAR = {"time": "2026-09-10T00:00:00+00:00", "open": 185.02438884683545,
            "high": 186.3028989835443, "low": 184.35017451693037,
            "close": 185.00441212594936, "volume": 5571344}


def _client(bars_for):
    """bars_for: symbol -> bars; a symbol not in it gets [] (Silver has not published it)."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        sym = req.url.path.split("/")[3]
        bars = bars_for.get(sym, [])
        return httpx.Response(200, json={"symbol": sym, "bars": bars, "count": len(bars)})
    return httpx.Client(transport=httpx.MockTransport(handler)), seen


_ALL_NINE = {s: [_XLK_BAR] for s in bf._FUNDS_1998}


def test_preflight_aborts_naming_the_funds_silver_has_not_published():
    published = dict(_ALL_NINE)
    for s in ("XLK", "XLY", "XLB", "XLU", "XLE"):  # the 2026-09-27 state
        del published[s]
    client, seen = _client(published)
    with pytest.raises(SystemExit, match="for XLB XLE XLK XLU XLY"):
        bf.preflight_etf_history(client=client)
    assert [r.url.path for r in seen] == [f"/v1/equity/{s}/bars" for s in bf._FUNDS_1998]
    q = seen[0].url.params
    assert q["price_mode"] == "adjusted" and q["timeframe"] == "1d"
    assert q["start"] == "1999-01-04T00:00:00+00:00"
    assert q["end"] == "1999-01-08T23:59:59+00:00"


def test_preflight_passes_when_all_nine_have_bars():
    client, _ = _client(_ALL_NINE)
    assert bf.preflight_etf_history(client=client) is None
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/unit/scripts/test_sector_rs_backfill.py -q
```
Expected: `FileNotFoundError` for `scripts/backfill/sector_rs_backfill.py`.

- [ ] **Step 3: Implement** `scripts/backfill/sector_rs_backfill.py`

```python
#!/usr/bin/env python
"""Backfill sector_rs_daily over a date range.

This is the §6 research trace, and the heal for this table: the table is not
healer-enrolled (spec 2026-09-26 §5). It uses the same core as the nightly job
(worker/jobs/sector_rs_daily.run_sector_rs), so a backfilled row and a nightly
row for one session are the same row.

Resumable: sessions already holding rows of a group_kind are skipped unless
--force. Work is chunked (--chunk-sessions, default 125, about 6 months) and
every chunk commits, so an interrupted run resumes at the first missing chunk.
Cost: the full default range is about 7,000 sessions (1998-12-22 → present).
Each chunk makes one bulk call for SPY plus three for the ~514 other symbols
(503 S&P names + 11 ETFs, 200 per call), so about 56 chunks × 4 calls at the
default --chunk-sessions 125. Each call spans the chunk plus a 400-day
lookback; the apex session measured about 4 s per 200 symbols over a year.
Zero UW spend.

SURVIVORSHIP, by ruling (spec §4): gics membership is the vendored CURRENT
S&P 500 list (src/uw_scan/sources/data/sp500_members.json, copied from
livewire presets/sp500.json) applied to every historical session. apex's
point-in-time membership is defective and not used. Former members are
therefore absent from n_members, and a delisted name has no adjusted bars
(apex files it under `missing`), so it is unpriced. Breadth history describes
today's index, not the index of the day. Chain rows likewise carry TODAY's
watchlist_chain membership (no history exists). The run's log line repeats
this next to its n_priced / n_members totals.

ETF history (livewire #157, 2026-09-27): the nine 1998 funds start
1998-12-22, XLRE 2015-10-08, XLC 2018-06-19. rs_12m is NULL and the row
degraded for each fund's first 252 sessions, by construction. Breadth on the
current list also thins going back (survivorship); the §6 probe's
effective-start rule handles that.

PRE-FLIGHT: when the range reaches back before the 2021-05-18 seed and the
gics kind is requested, the script first asks apex for adjusted bars for
1999-01-04..08 for each of the nine 1998 funds. It aborts naming the funds
with none, because Silver has not yet published their #157 history (on
2026-09-27 that was XLK XLY XLB XLU XLE; livewire is fixing the seam cut).

Reproduce (on the mini, after migration 152 and the nightly Silver rebuild):
    uv run python scripts/backfill/sector_rs_backfill.py --start 1998-12-22 --end 2026-09-25
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timezone

import httpx
import psycopg

from uw_scan.config import Settings
from uw_scan.sources.apex import fetch_bars
from uw_scan.storage.repository import Repository
from uw_scan.storage.sector_rs import SectorRsRepository
from uw_scan.worker.jobs.sector_rs_daily import (
    BENCHMARK,
    GROUP_KINDS,
    load_closes,
    run_sector_rs,
)

log = logging.getLogger("sector_rs_backfill")

#: First bronze bar of the nine 1998 SPDR funds after livewire #157 (spec §4).
DEFAULT_START = date(1998, 12, 22)
#: The ETF seed before #157 (XLF 2021-05-18). A range starting on or after it
#: does not need the pre-flight.
PRE_157_SEED = date(2021, 5, 18)
_PREFLIGHT_START = date(1999, 1, 4)
_PREFLIGHT_END = datetime(1999, 1, 8, 23, 59, 59, tzinfo=timezone.utc)
#: The nine funds launched 1998-12-16; XLRE and XLC start later and are not checked.
_FUNDS_1998: tuple[str, ...] = ("XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY")


def pending_sessions(sessions: list[date], present: set[date], force: bool) -> list[date]:
    """Sessions still to compute: all of them with --force, else the absent ones."""
    return list(sessions) if force else [s for s in sessions if s not in present]


def chunked(items: list[date], size: int) -> list[list[date]]:
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [items[i : i + size] for i in range(0, len(items), size)]


def preflight_etf_history(client: httpx.Client | None = None) -> None:
    """Abort unless apex serves ADJUSTED bars for the first week of 1999 for
    every 1998 fund.

    Silver, which price_mode=adjusted reads, cut five of the nine funds back to
    2021-06-11 on its first #157 rebuild (spec §4). Before the fix lands, a
    backfill would write about 5,600 gics sessions with NULL rs and
    degraded=true for those sectors, and they would look like data. fetch_bars
    sends price_mode=adjusted for equity and never raises ([] on any failure),
    so an apex outage also aborts here.
    """
    missing = [
        s for s in _FUNDS_1998
        if not fetch_bars(s, "1d", _PREFLIGHT_START, end=_PREFLIGHT_END, client=client)
    ]
    if missing:
        raise SystemExit(
            "Silver has not published the #157 history yet (apex returned no adjusted "
            f"bars for 1999-01-04..08 for {' '.join(missing)}); run after livewire's fix"
        )


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(description="Backfill uw_scan.sector_rs_daily")
    p.add_argument("--start", type=date.fromisoformat, default=DEFAULT_START)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--group-kind", choices=GROUP_KINDS, action="append", dest="kinds")
    p.add_argument("--force", action="store_true", help="recompute sessions already present")
    p.add_argument("--chunk-sessions", type=int, default=125)
    args = p.parse_args()
    kinds = tuple(args.kinds or GROUP_KINDS)

    if "gics" in kinds and args.start < PRE_157_SEED:
        preflight_etf_history()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        spy, _ = load_closes(repo, [BENCHMARK], start=args.start, end=args.end)
        sessions = [d for d, _ in spy.get(BENCHMARK, []) if args.start <= d <= args.end]
        if not sessions:
            log.error("no %s sessions in %s..%s; nothing to do", BENCHMARK, args.start, args.end)
            return 1
        store = SectorRsRepository(conn, schema=settings.db_schema)
        for kind in kinds:
            todo = pending_sessions(
                sessions, store.dates_present(kind, args.start, args.end), args.force
            )
            log.info("%s: %d of %d sessions to compute", kind, len(todo), len(sessions))
            for chunk in chunked(todo, args.chunk_sessions):
                counters = run_sector_rs(
                    repo=repo, schema=settings.db_schema, dates=chunk, group_kinds=(kind,)
                )
                log.info("%s %s..%s %s", kind, chunk[0], chunk[-1], counters)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test, then smoke-run the script on the local DB** (dev-owned `option_wizard_local`; this checks the wiring only, not the research)

```bash
uv run pytest tests/unit/scripts/test_sector_rs_backfill.py -q
uv run ruff check scripts/backfill/sector_rs_backfill.py tests/unit/scripts/test_sector_rs_backfill.py
uv run python scripts/backfill/sector_rs_backfill.py --start 2026-09-14 --end 2026-09-18
psql -h 127.0.0.1 -U argon_app -d option_wizard_local -c "SELECT group_kind, count(*), count(*) FILTER (WHERE degraded) AS degraded, min(as_of), max(as_of) FROM uw_scan.sector_rs_daily GROUP BY 1"
uv run python scripts/backfill/sector_rs_backfill.py --start 2026-09-14 --end 2026-09-18   # resume: expect "0 of 5 sessions to compute"
```
Expected: 4 passed. The smoke range starts after 2021-05-18, so it skips the pre-flight. `gics` shows 55 rows (5 sessions × 11), and `chain` shows 5 × the number of active chains. The second run logs `0 of 5 sessions to compute` for both kinds. `degraded` on local reflects local `company_sector` coverage and is not an acceptance number.

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill/sector_rs_backfill.py tests/unit/scripts/test_sector_rs_backfill.py
git commit -m "feat(sector-rs): resumable sector_rs_backfill script"
```

---

### Task 8: Research probe `scripts/research/sector_rs_breadth_probe.py` (spec §6)

This task writes and tests the script. **Running it on real history is out of scope.** It runs on the mini after the Task 7 backfill covers the ETF history, and its output is committed then.

**Files**
- Create: `scripts/research/sector_rs_breadth_probe.py`
- Create: `tests/unit/scripts/test_sector_rs_breadth_probe.py`

**Interfaces**
- Consumes: table `uw_scan.sector_rs_daily` (gics rows only), `Settings.from_env()`.
- Produces:
```python
HOLDOUT = date(2019, 1, 1); STEP = 21; MIN_HISTORY = 63; BOOT_B = 5000; SEED = 20260926
COVERAGE_WINDOW = 252; COVERAGE_FLOOR = 0.95
VARIANTS = ("breadth_1m", "breadth_3m")
@dataclass(frozen=True) class DailyRow: group_key: str; as_of: date; rs_1m: float | None; breadth_1m: float | None; breadth_3m: float | None; degraded: bool
@dataclass(frozen=True) class Pair: group_key: str; as_of: date; variant: str; breadth: float; cut: float; cond: bool; outcome_neg: bool
@dataclass(frozen=True) class Result: variant: str; split: str; group: str; n: int; n_c: int; p_c: float | None; p_base: float | None; diff: float | None; ci_lo: float | None; ci_hi: float | None; effective_start: date | None = None
def effective_start(rows: list[DailyRow]) -> date | None
def monthly_pairs(rows: list[DailyRow], variant: str) -> list[Pair]
def stats(pairs: list[Pair]) -> tuple[int, int, float | None, float | None, float | None]
def bootstrap_ci(pairs: list[Pair], *, b: int = BOOT_B, seed: int = SEED) -> tuple[float | None, float | None]
def evaluate(pairs_by_group: dict[str, list[Pair]], variant: str, *, starts: dict[str, date | None] | None = None, b: int = BOOT_B) -> list[Result]
def gate(results: list[Result], variant: str) -> tuple[bool, list[str]]
def render_verdict(results: list[Result], gates: dict[str, tuple[bool, list[str]]], *, coverage: dict[str, tuple[date, date | None, int]], db_label: str, n_rows: int, reproduce: str) -> str
```
Outputs: `docs/research/<run-date>-sector-rs-breadth/{VERDICT.md, results.csv, observations.csv}`, plus the reproduce command on stdout.

Pre-registered readings, fixed here before any data is seen. The spec leaves these implicit:
- The tercile history is the group's non-degraded **daily** breadth values strictly before *t*, not only past monthly observations. An observation needs at least `MIN_HISTORY = 63` of them.
- The baseline is computed over the same eligible observations as C.
- The per-group catastrophic check uses each group's own OOS bootstrap CI half-width.
- The PASS/FAIL verdict is keyed on `breadth_1m`. `breadth_3m` gets its own reported gate line and does not change the verdict.
- **Effective sample start (spec §6 coverage exclusion).** Per group, it is the first row that is itself non-degraded and from which every full 252-session window has at least 95% non-degraded rows. Rows before it are dropped before the grid and the tercile history are built, and it is reported per group in VERDICT.md and in results.csv (`effective_start`). A group whose last full window is below 95% has no start and is excluded, and the report says so. The "row itself non-degraded" clause is what puts the start exactly at row 300 in the unit test. Without it, the 95%-of-252 rule alone would already admit row 288.
- **Holdout 2019-01-01.** In-sample runs from each group's effective start to 2018-12, out-of-sample from 2019-01 to the present. XLC (first bar 2018-06-19) has no in-sample and is marked OOS-only; XLRE has about 3 years in-sample.
- **Expected size (spec §6).** About 3,000 pooled monthly observations before the coverage exclusion: nine groups × up to ~320 months, plus XLRE and XLC. VERDICT.md reports the n that survives, per group and pooled.

- [ ] **Step 1: Write the failing test** at `tests/unit/scripts/test_sector_rs_breadth_probe.py`

```python
"""Tercile / conditioning / gate logic of the sector RS breadth probe.

Every series here is a labelled TEST DOUBLE: hand-built breadth fractions and
RS signs with no market meaning, on consecutive calendar days. They exercise
indexing and arithmetic only. No prices are involved.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

_PATH = Path(__file__).resolve().parents[3] / "scripts/research/sector_rs_breadth_probe.py"
_spec = importlib.util.spec_from_file_location("sector_rs_breadth_probe", _PATH)
probe = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = probe
_spec.loader.exec_module(probe)

D0 = date(1998, 12, 22)


def _rows(breadths, rs=None, degraded=()):
    rs = rs or [1.0] * len(breadths)
    return [
        probe.DailyRow("Technology", D0 + timedelta(days=i), rs[i], b, b, i in degraded)
        for i, b in enumerate(breadths)
    ]


def test_grid_is_non_overlapping_and_starts_after_min_history():
    rows = _rows([0.5] * 200)
    pairs = probe.monthly_pairs(rows, "breadth_1m")
    # grid 0, 21, ...; i + 21 < 200; eligible once 63 past values exist
    assert [p.as_of for p in pairs] == [rows[i].as_of for i in (63, 84, 105, 126, 147, 168)]


def test_tercile_uses_only_past_values():
    rising = _rows([i / 200 for i in range(200)])
    assert not any(p.cond for p in probe.monthly_pairs(rising, "breadth_1m"))
    falling = _rows([1 - i / 200 for i in range(200)])
    assert all(p.cond for p in probe.monthly_pairs(falling, "breadth_1m"))
    # A future collapse cannot change an earlier observation's cut
    changed = _rows([i / 200 for i in range(199)] + [0.0])
    before = {p.as_of: p.cut for p in probe.monthly_pairs(rising, "breadth_1m")}
    after = {p.as_of: p.cut for p in probe.monthly_pairs(changed, "breadth_1m")}
    assert before == after


def test_condition_requires_positive_rs_and_outcome_reads_t_plus_21():
    b = [1 - i / 200 for i in range(200)]
    rs = [(-1.0 if i == 84 else 1.0) for i in range(200)]
    rs[105] = -2.0  # the outcome of the observation at 84
    pairs = {p.as_of: p for p in probe.monthly_pairs(_rows(b, rs=rs), "breadth_1m")}
    assert pairs[D0 + timedelta(days=84)].cond is False  # rs_1m(t) <= 0
    assert pairs[D0 + timedelta(days=84)].outcome_neg is True
    assert pairs[D0 + timedelta(days=63)].outcome_neg is True  # rs at 84 < 0


def test_degraded_rows_drop_their_pairs():
    pairs = probe.monthly_pairs(_rows([0.5] * 200, degraded={84}), "breadth_1m")
    kept = {p.as_of for p in pairs}
    assert D0 + timedelta(days=84) not in kept  # t degraded
    assert D0 + timedelta(days=63) not in kept  # t+21 degraded


def test_effective_start_is_the_first_clean_row_after_the_thin_years():
    # labelled test double: 300 rows at coverage 0.5 (below the 0.8 floor, so
    # degraded), then 400 rows at coverage 0.9 (clean)
    rows = _rows([0.5] * 700, degraded=set(range(300)))
    assert probe.effective_start(rows) == rows[300].as_of


def test_effective_start_moves_past_a_later_dip_and_can_be_none():
    # 20 degraded rows inside any 252-window → 92% < 95%: the start moves past them
    rows = _rows([0.5] * 700, degraded=set(range(400, 420)))
    assert probe.effective_start(rows) == rows[420].as_of
    # every 10th row degraded → 90% everywhere → never qualifies
    assert probe.effective_start(_rows([0.5] * 700, degraded=set(range(0, 700, 10)))) is None
    assert probe.effective_start(_rows([0.5] * 100)) is None  # shorter than one window


def _pair(cond, neg, day=0):
    return probe.Pair("Technology", D0 + timedelta(days=day), "breadth_1m", 0.1, 0.2, cond, neg)


def test_stats_math():
    ps = [_pair(True, True), _pair(True, False), _pair(False, True),
          _pair(False, False), _pair(False, False), _pair(False, False)]
    n, n_c, p_c, p_base, diff = probe.stats(ps)
    assert (n, n_c) == (6, 2)
    assert p_c == 0.5 and abs(p_base - 2 / 6) < 1e-12 and abs(diff - 1 / 6) < 1e-12
    assert probe.stats([_pair(False, True)])[2] is None  # C never fired


def test_bootstrap_is_seeded_and_brackets_the_point_estimate():
    ps = [_pair(i % 3 == 0, i % 2 == 0, i) for i in range(60)]
    a = probe.bootstrap_ci(ps, b=500)
    assert a == probe.bootstrap_ci(ps, b=500)
    assert a[0] <= probe.stats(ps)[4] <= a[1]


def _res(group, diff, lo, hi, split="oos"):
    return probe.Result("breadth_1m", split, group, 100, 30, 0.5, 0.5 - diff, diff, lo, hi)


def test_gate_passes_and_fails_on_the_right_reasons():
    ok = [_res("POOLED", 0.10, 0.02, 0.18), _res("Technology", 0.05, -0.05, 0.15)]
    assert probe.gate(ok, "breadth_1m") == (True, [])
    ci_spans_zero = [_res("POOLED", 0.10, -0.01, 0.21), _res("Technology", 0.05, -0.05, 0.15)]
    passed, why = probe.gate(ci_spans_zero, "breadth_1m")
    assert not passed and "pooled OOS" in why[0]
    catastrophic = [_res("POOLED", 0.10, 0.02, 0.18), _res("Energy", -0.20, -0.30, -0.10)]
    passed, why = probe.gate(catastrophic, "breadth_1m")
    assert not passed and why[0].startswith("Energy")
```

- [ ] **Step 2: Run it and confirm it fails**

```bash
uv run pytest tests/unit/scripts/test_sector_rs_breadth_probe.py -q
```
Expected: `FileNotFoundError` for `scripts/research/sector_rs_breadth_probe.py`.

- [ ] **Step 3: Implement** `scripts/research/sector_rs_breadth_probe.py`

```python
#!/usr/bin/env python
"""Sector RS breadth probe — spec 2026-09-26 §6, pre-registered.

H1. For a gics group on date t, C = rs_1m(t) > 0 AND breadth_1m(t) in the
bottom tercile of that group's own history. Then P(rs_1m(t+21) < 0 | C)
exceeds the unconditional P(rs_1m(t+21) < 0) for that group.

Method, fixed before any data is read:
- Observations: per group, every STEP-th (21st) row of its session series.
  They do not overlap, and t+21 is the next observation on the same grid.
  A pair is dropped when t or t+21 is degraded, or when rs_1m(t), rs_1m(t+21)
  or the conditioning breadth is NULL.
- Tercile: expanding. The cut at t is the 1/3 quantile (inclusive method) of
  the group's non-degraded DAILY breadth values strictly before t. An
  observation with fewer than MIN_HISTORY past values is not eligible for C
  or for the baseline.
- Baseline: P(rs_1m(t+21) < 0) over the same eligible observations.
- Bootstrap: 95% CI on (p_C − p_base), resampling eligible pairs with
  replacement (BOOT_B, SEED). The pooled resample pools pairs across groups
  and ignores group clustering; that is stated in VERDICT.md.
- Effective start: per group, the first non-degraded row from which every
  full COVERAGE_WINDOW (252-session) window is >= COVERAGE_FLOOR (95%)
  non-degraded. Earlier rows are dropped; groups that never qualify are
  excluded and reported.
- Holdout: in_sample as_of < 2019-01-01; oos as_of >= 2019-01-01. XLC
  (Communication Services, first bar 2018-06-19) is OOS-only.
- Variants: breadth_1m (primary: it decides PASS/FAIL) and breadth_3m
  (pre-registered in the spec, reported with its own gate line).
- Gate, primary variant, OOS: pooled diff > 0 with CI low > 0, AND no group
  whose diff is below −(its own CI half-width).

Reads gics rows only (spec §6). Both kinds carry TODAY's membership over
history (survivorship-biased); VERDICT.md states it.

Writes docs/research/<run-date>-sector-rs-breadth/{VERDICT.md, results.csv,
observations.csv} and prints the reproduce command.

Reproduce:
    uv run python scripts/research/sector_rs_breadth_probe.py
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import psycopg

HOLDOUT = date(2019, 1, 1)
COVERAGE_WINDOW = 252
COVERAGE_FLOOR = 0.95
STEP = 21
MIN_HISTORY = 63
BOOT_B = 5000
SEED = 20260926
VARIANTS = ("breadth_1m", "breadth_3m")
PRIMARY = "breadth_1m"


@dataclass(frozen=True)
class DailyRow:
    group_key: str
    as_of: date
    rs_1m: float | None
    breadth_1m: float | None
    breadth_3m: float | None
    degraded: bool


@dataclass(frozen=True)
class Pair:
    group_key: str
    as_of: date
    variant: str
    breadth: float
    cut: float
    cond: bool
    outcome_neg: bool


@dataclass(frozen=True)
class Result:
    variant: str
    split: str
    group: str
    n: int
    n_c: int
    p_c: float | None
    p_base: float | None
    diff: float | None
    ci_lo: float | None
    ci_hi: float | None
    effective_start: date | None = None


def effective_start(rows: list[DailyRow]) -> date | None:
    """First non-degraded row from which every full 252-session window is >= 95% clean.

    `rows`: one group, ascending by as_of. None when the group is shorter than
    one window or its last full window already fails, i.e. it never qualifies.
    Walks backward from the last full window and stops at the first failing
    one, so the O(n) prefix sum is the whole cost.
    """
    n = len(rows)
    if n < COVERAGE_WINDOW:
        return None
    clean = [0] * (n + 1)
    for i, r in enumerate(rows):
        clean[i + 1] = clean[i] + (not r.degraded)
    start: int | None = None
    for i in range(n - COVERAGE_WINDOW, -1, -1):
        if (clean[i + COVERAGE_WINDOW] - clean[i]) / COVERAGE_WINDOW < COVERAGE_FLOOR:
            break
        if not rows[i].degraded:
            start = i
    return None if start is None else rows[start].as_of


def monthly_pairs(rows: list[DailyRow], variant: str) -> list[Pair]:
    """One group's rows, ascending by as_of → its eligible (t, t+21) pairs."""
    out: list[Pair] = []
    past: list[float] = []
    for i, t in enumerate(rows):
        if i % STEP == 0 and i + STEP < len(rows) and len(past) >= MIN_HISTORY:
            nxt = rows[i + STEP]
            b = getattr(t, variant)
            if (
                not t.degraded
                and not nxt.degraded
                and b is not None
                and t.rs_1m is not None
                and nxt.rs_1m is not None
            ):
                cut = statistics.quantiles(past, n=3, method="inclusive")[0]
                out.append(
                    Pair(
                        t.group_key, t.as_of, variant, b, cut,
                        cond=t.rs_1m > 0 and b <= cut,
                        outcome_neg=nxt.rs_1m < 0,
                    )
                )
        v = getattr(t, variant)
        if not t.degraded and v is not None:
            past.append(v)
    return out


def stats(pairs: list[Pair]) -> tuple[int, int, float | None, float | None, float | None]:
    """(n, n_C, p_C, p_base, p_C − p_base). p_C/diff are None when C never fired."""
    n = len(pairs)
    cond = [p for p in pairs if p.cond]
    p_base = sum(p.outcome_neg for p in pairs) / n if n else None
    if not cond or p_base is None:
        return n, len(cond), None, p_base, None
    p_c = sum(p.outcome_neg for p in cond) / len(cond)
    return n, len(cond), p_c, p_base, p_c - p_base


def bootstrap_ci(
    pairs: list[Pair], *, b: int = BOOT_B, seed: int = SEED
) -> tuple[float | None, float | None]:
    """Percentile 95% CI of p_C − p_base; (None, None) when C is too rare to resample."""
    if not pairs:
        return None, None
    rng = random.Random(seed)
    diffs: list[float] = []
    n = len(pairs)
    for _ in range(b):
        d = stats([pairs[rng.randrange(n)] for _ in range(n)])[4]
        if d is not None:
            diffs.append(d)
    if len(diffs) < b // 2:
        return None, None
    diffs.sort()
    return diffs[int(0.025 * (len(diffs) - 1))], diffs[int(0.975 * (len(diffs) - 1))]


def _result(
    variant: str, split: str, group: str, pairs: list[Pair], b: int, start: date | None = None
) -> Result:
    n, n_c, p_c, p_base, diff = stats(pairs)
    lo, hi = bootstrap_ci(pairs, b=b)
    return Result(variant, split, group, n, n_c, p_c, p_base, diff, lo, hi, start)


def evaluate(
    pairs_by_group: dict[str, list[Pair]],
    variant: str,
    *,
    starts: dict[str, date | None] | None = None,
    b: int = BOOT_B,
) -> list[Result]:
    starts = starts or {}
    splits = (
        ("all", lambda d: True),
        ("in_sample", lambda d: d < HOLDOUT),
        ("oos", lambda d: d >= HOLDOUT),
    )
    out: list[Result] = []
    for split, keep in splits:
        pooled: list[Pair] = []
        for g in sorted(pairs_by_group):
            ps = [p for p in pairs_by_group[g] if keep(p.as_of)]
            pooled.extend(ps)
            out.append(_result(variant, split, g, ps, b, starts.get(g)))
        out.append(_result(variant, split, "POOLED", pooled, b))
    return out


def gate(results: list[Result], variant: str) -> tuple[bool, list[str]]:
    oos = [r for r in results if r.variant == variant and r.split == "oos"]
    pooled = next((r for r in oos if r.group == "POOLED"), None)
    reasons: list[str] = []
    if pooled is None or pooled.diff is None or pooled.ci_lo is None or pooled.ci_hi is None:
        reasons.append("pooled OOS: C never fired or too rare to bootstrap")
    elif not (pooled.diff > 0 and pooled.ci_lo > 0):
        reasons.append(
            f"pooled OOS diff {pooled.diff:+.3f}, CI [{pooled.ci_lo:+.3f}, "
            f"{pooled.ci_hi:+.3f}] does not exclude zero on the positive side"
        )
    for r in oos:
        if r.group == "POOLED" or r.diff is None or r.ci_lo is None or r.ci_hi is None:
            continue
        half = (r.ci_hi - r.ci_lo) / 2
        if r.diff < -half:
            reasons.append(f"{r.group}: OOS diff {r.diff:+.3f} below −half-width {half:.3f}")
    return (not reasons), reasons


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:+.3f}"


def render_verdict(
    results: list[Result],
    gates: dict[str, tuple[bool, list[str]]],
    *,
    coverage: dict[str, tuple[date, date | None, int]],
    db_label: str,
    n_rows: int,
    reproduce: str,
) -> str:
    primary_pass, primary_why = gates[PRIMARY]
    lines = [
        "# Sector RS breadth probe — VERDICT",
        "",
        f"**Verdict: {'PASS' if primary_pass else 'FAIL'}** (primary variant `{PRIMARY}`, "
        "gate of spec 2026-09-26 §6).",
        "",
        f"- Source: `uw_scan.sector_rs_daily` gics rows on {db_label} ({n_rows} rows read).",
        f"- Reproduce: `{reproduce}`",
        f"- Grid: every {STEP}th session per group; tercile expanding over past daily "
        f"breadth (min {MIN_HISTORY}); bootstrap B={BOOT_B}, seed {SEED}; holdout {HOLDOUT}.",
        "- The pooled bootstrap resamples pairs across groups and ignores group clustering.",
        "- Breadth uses TODAY's S&P 500 membership over every session, and delisted names "
        "have no adjusted bars, so former members are absent: survivorship-biased by construction.",
        "",
        "## Effective sample start per group",
        "",
        f"First non-degraded row from which every {COVERAGE_WINDOW}-session window is "
        f">= {COVERAGE_FLOOR:.0%} non-degraded; earlier rows are excluded.",
        "",
        "| group | first row | effective start | rows excluded | note |",
        "|---|---|---|---|---|",
    ]
    for g, (first, start, excluded) in sorted(coverage.items()):
        if start is None:
            note = "excluded: never reaches the coverage floor"
        elif start >= HOLDOUT:
            note = "OOS-only (no in-sample)"
        else:
            note = ""
        lines.append(f"| {g} | {first} | {start or '—'} | {excluded} | {note} |")
    lines.append("")
    for variant in VARIANTS:
        ok, why = gates[variant]
        lines += [
            f"## `{variant}` — gate {'PASS' if ok else 'FAIL'}"
            + (" (pre-registered secondary; does not change the verdict)" if variant != PRIMARY else ""),
            "",
            *(f"- {w}" for w in why),
            "",
            "| split | group | n | n_C | p_C | p_base | diff | CI 95% |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in results:
            if r.variant != variant:
                continue
            lines.append(
                f"| {r.split} | {r.group} | {r.n} | {r.n_c} | {_fmt(r.p_c)} | "
                f"{_fmt(r.p_base)} | {_fmt(r.diff)} | [{_fmt(r.ci_lo)}, {_fmt(r.ci_hi)}] |"
            )
        lines.append("")
    return "\n".join(lines)


def _load(conn: psycopg.Connection, schema: str) -> dict[str, list[DailyRow]]:
    by_group: dict[str, list[DailyRow]] = {}
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT group_key, as_of, rs_1m, breadth_1m, breadth_3m, degraded
                  FROM {schema}.sector_rs_daily
                 WHERE group_kind = 'gics'
                 ORDER BY group_key, as_of"""
        )
        for row in cur.fetchall():
            by_group.setdefault(row[0], []).append(DailyRow(*row))
    return by_group


def main() -> int:
    from uw_scan.config import Settings

    ap = argparse.ArgumentParser(description="Sector RS breadth probe (spec §6)")
    ap.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out-root", default="docs/research")
    ap.add_argument("--boot", type=int, default=BOOT_B)
    args = ap.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        rows = _load(conn, settings.db_schema)
    n_rows = sum(len(v) for v in rows.values())
    db_label = f"{settings.db_host}/{settings.db_name}"
    coverage: dict[str, tuple[date, date | None, int]] = {}
    kept: dict[str, list[DailyRow]] = {}
    for g, rs in rows.items():
        start = effective_start(rs)
        kept[g] = [r for r in rs if start is not None and r.as_of >= start]
        coverage[g] = (rs[0].as_of, start, len(rs) - len(kept[g]))
    starts = {g: c[1] for g, c in coverage.items()}

    results: list[Result] = []
    gates: dict[str, tuple[bool, list[str]]] = {}
    all_pairs: list[Pair] = []
    for variant in VARIANTS:
        pairs = {g: monthly_pairs(rs, variant) for g, rs in kept.items()}
        all_pairs.extend(p for ps in pairs.values() for p in ps)
        res = evaluate(pairs, variant, starts=starts, b=args.boot)
        results.extend(res)
        gates[variant] = gate(res, variant)

    out = Path(args.out_root) / f"{args.run_date.isoformat()}-sector-rs-breadth"
    out.mkdir(parents=True, exist_ok=True)
    reproduce = (
        "uv run python scripts/research/sector_rs_breadth_probe.py "
        f"--run-date {args.run_date.isoformat()} --boot {args.boot}"
    )
    with (out / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(Result.__dataclass_fields__))
        w.writeheader()
        w.writerows(asdict(r) for r in results)
    with (out / "observations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(Pair.__dataclass_fields__))
        w.writeheader()
        w.writerows(asdict(p) for p in all_pairs)
    (out / "VERDICT.md").write_text(
        render_verdict(
            results, gates, coverage=coverage, db_label=db_label, n_rows=n_rows, reproduce=reproduce
        )
        + "\n"
    )
    print(f"wrote {out}/VERDICT.md, results.csv, observations.csv")
    print(f"reproduce: {reproduce}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
`settings.db_host` / `settings.db_name` are real `Settings` fields (`config.py:116,118`). VERDICT.md names the DB it read because analyses run on the dev DB are fiction (memory rule).

- [ ] **Step 4: Run the test and confirm it passes**

```bash
uv run pytest tests/unit/scripts/test_sector_rs_breadth_probe.py -q
uv run ruff check scripts/research/sector_rs_breadth_probe.py tests/unit/scripts/test_sector_rs_breadth_probe.py
```
Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/sector_rs_breadth_probe.py tests/unit/scripts/test_sector_rs_breadth_probe.py
git commit -m "feat(sector-rs): pre-registered §6 breadth probe script"
```

---

### Task 9: CHANGELOG + CLAUDE.md row + full verification

**Files**
- Modify: `CHANGELOG.md`. Add under `## [Unreleased]` (line 8).
- Modify: `CLAUDE.md`. Add a "Where to look first" table row directly after the row that begins `| Regime indicators (CRI / GEX / VCG)`.

- [ ] **Step 1: CHANGELOG.** Insert under `## [Unreleased]`:

```markdown
### Added

- **`sector_rs_daily`: sector relative strength and breadth, research-first (migration 152).** One row per session for each of the 11 GICS sectors (SPDR ETF return minus SPY, in percentage points; breadth = share of current S&P 500 members beating SPY, applied to every session, so it is survivorship-biased by construction) and each `watchlist_chain` chain (equal-weighted), over 1m/3m/6m/12m. The new massive-0 job `sector_rs_daily` runs at 21:30 ET Mon–Fri. It is gated by `UW_SCAN_SECTOR_RS_ENABLED`, default **off**; flip it on the mini after `scripts/backfill/sector_rs_backfill.py --start 1998-12-22` lands (after the nightly Silver rebuild publishes the livewire #157 ETF history). It costs no UW calls: apex's bulk adjusted-bars route `GET /v1/equity/bars` (delisted names have no Silver and stay unpriced), and a `daily_ohlc` fallback for SPY and the ETFs only. Rows whose 12m coverage falls below 80% are written and flagged `degraded`. `company_sector_refresh` now also fills sectors for current S&P 500 members (about 330 UW calls, once). `scripts/research/sector_rs_breadth_probe.py` implements the pre-registered §6 test. S&P 500 membership is a vendored list (`src/uw_scan/sources/data/sp500_members.json`, refreshed from livewire `presets/sp500.json` by `scripts/research/sync_sp500_members.py`). The reason: apex's membership route returned null symbols and dead tickers, and was missing META and XOM, on 2026-09-26. No UI ships until that probe passes. Spec: `docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md`.
```

- [ ] **Step 2: CLAUDE.md row** (insert after the `| Regime indicators (CRI / GEX / VCG)` row):

```markdown
| Sector RS + breadth (gics ETFs vs SPY, chain equal-weight; research-first, no UI) | `reports/sector_rs.py` (pure compute, SPY-anchored windows) + `worker/jobs/sector_rs_daily.py` (`run_sector_rs` core; 21:30 ET Mon–Fri massive-0, gated `UW_SCAN_SECTOR_RS_ENABLED` default off) + `storage/sector_rs.py` + `sources/apex.py` (`fetch_bulk_daily_closes` → apex bulk `GET /v1/equity/bars`, ≤200 symbols per call, tz-aware bounds or it 400s, delisted names land in `missing` and stay unpriced) + `sources/sp500_members.py` (the vendored current S&P 500 list in `sources/data/sp500_members.json`; refresh it with `scripts/research/sync_sp500_members.py --livewire ~/projects/livewire`; apex's membership route is NOT used: null symbols, dead tickers, and META/XOM missing on 2026-09-26) + migration `152` + backfill `scripts/backfill/sector_rs_backfill.py` (the heal; not healer-enrolled) + probe `scripts/research/sector_rs_breadth_probe.py`. ETF bars start 1998-12-22 (XLRE 2015-10-08, XLC 2018-06-19) after livewire #157, so each fund's `rs_12m` is NULL/degraded for its first 252 sessions; the backfill pre-flights that Silver serves the 1999 history. Both gics and chain rows use today's membership over history (survivorship-biased). Spec `docs/superpowers/specs/2026-09-26-sector-rs-daily-design.md` |
```

- [ ] **Step 3: Full verification.** Run the CI's exact lint invocation, the touched unit and integration suites, the no-Yahoo check, and a module-size check.

```bash
uv run ruff check src/ tests/ scripts/
uv run python scripts/check_no_yahoo.py
uv run pytest tests/unit/ -q -x
uv run pytest tests/integration/storage/test_sector_rs_repository.py tests/integration/storage/test_company_sector_sp500.py tests/integration/worker/test_company_type_routing.py tests/integration/worker/test_data_gap_full_coverage.py tests/integration/reports/test_monitored_tables_resolve_date_col.py -q
wc -l src/uw_scan/reports/sector_rs.py src/uw_scan/storage/sector_rs.py src/uw_scan/worker/jobs/sector_rs_daily.py src/uw_scan/sources/apex.py scripts/research/sector_rs_breadth_probe.py
```
Expected: ruff clean, no Yahoo hits, all tests pass, and every file under 500 lines.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md CLAUDE.md
git commit -m "docs(sector-rs): CHANGELOG [Unreleased] entry + CLAUDE.md where-to-look row"
```

- [ ] **Step 5: Deliver.** `/execute-plan` handles delivery: push `feat/sector-rs-daily`, open the PR with `gh pr create`, and wait for CI to be green before any merge.

---

## Post-merge runbook (mini; not part of this PR's execution)

1. Deploy through the normal release. `api` self-migrates, which applies 152.
2. The next 04:40 ET `company_sector_refresh` fills S&P 500 sectors. Check acceptance §9.3 with `SELECT count(*) FILTER (WHERE c.ticker IS NOT NULL)::float / count(*) FROM unnest(<sp500 list>) m LEFT JOIN uw_scan.company_sector c ON c.ticker = m`. The list is `src/uw_scan/sources/data/sp500_members.json`.
3. After the nightly `--full` Silver rebuild, run `uv run python scripts/backfill/sector_rs_backfill.py --start 1998-12-22 --end <last close>`. It pre-flights that Silver serves the 1999 XLK bars, and it is resumable, so re-run it if interrupted. Then check acceptance §9.1. It has two parts.

   **Gate (the ETF leg).** `rs_12m IS NOT NULL` on at least 95% of gics rows from each fund's first_date + 252 sessions: about 2000-01 for the nine 1998 funds, 2016-10 for XLRE and 2019-07 for XLC. Every row of this query must show `rs12_share >= 0.95`:
   ```sql
   WITH first_bar(group_key, first_date) AS (
            VALUES ('Real Estate', DATE '2015-10-08'),
                   ('Communication Services', DATE '2018-06-19')),
        g AS (
            SELECT d.group_key, d.as_of, d.rs_12m,
                   COALESCE(f.first_date, DATE '1998-12-22') AS first_date
              FROM uw_scan.sector_rs_daily d
              LEFT JOIN first_bar f USING (group_key)
             WHERE d.group_kind = 'gics'),
        k AS (
            SELECT g.*, row_number() OVER (PARTITION BY group_key ORDER BY as_of) AS nth
              FROM g
             WHERE as_of >= first_date)
   SELECT group_key, min(as_of) AS gate_from,
          round(avg((rs_12m IS NOT NULL)::int), 4) AS rs12_share, count(*) AS n
     FROM k
    WHERE nth > 252            -- from first_date + 252 sessions
    GROUP BY 1 ORDER BY 1;
   ```
   **Report (the breadth leg; not gated).** This is the `degraded` share per group per year. Its early years are thin by construction, and the §6 effective start is where breadth becomes usable. Paste the output into the PR or the VERDICT follow-up:
   ```sql
   SELECT group_key, extract(year FROM as_of)::int AS year,
          round(avg((NOT degraded)::int), 3) AS non_degraded_share,
          round(avg(n_priced::float / NULLIF(n_members, 0))::numeric, 3) AS mean_priced_share,
          count(*) AS n
     FROM uw_scan.sector_rs_daily
    WHERE group_kind = 'gics'
    GROUP BY 1, 2 ORDER BY 1, 2;
   ```
4. Set `UW_SCAN_SECTOR_RS_ENABLED=true` in `/opt/argon/.env` and recreate the worker container. Watchtower does not re-read `env_file`.
5. Run `uv run python scripts/research/sector_rs_breadth_probe.py` against the mini DB. Commit `docs/research/<run-date>-sector-rs-breadth/` in a follow-up PR.

## Self-review against the spec

| Spec § | Covered by |
| ------ | ---------- |
| §2 group kinds, ETF map, SPY benchmark, 21/63/126/252 windows, RS in points | Task 2 (compute), Task 6 (`SPDR_SECTOR_ETFS`, `build_gics_groups`, `chain_groups`) |
| §3 table DDL verbatim, breadth definition, n_priced 12m, degraded still written, DO UPDATE every column | Task 1 (migration), Task 2, Task 3 |
| §4 apex adjusted `listing=any`, ≤200/call claim, daily_ohlc fallback for 12 symbols, classification fill ~330 calls, current classification over window | Task 4 (bulk route in chunks of 200; delisted names in `missing` stay unpriced; vendored S&P 500 list + sync script), Task 5, Task 6 (`load_closes`) |
| §5 code shape, 21:30 ET Mon–Fri massive-0, `max_instances=1`, `coalesce=True`, default off, backfill `--start --end --group-kind --force`, freshness enrolment, not healer-enrolled | Tasks 1, 3, 4, 6, 7 |
| §6 probe: non-overlapping monthly, expanding tercile, degraded excluded, per-group and pooled, bootstrap CI, effective sample start, holdout 2019-01-01 (XLC OOS-only), breadth_3m variant, gate | Task 8 |
| §7 tests | Task 2 (`test_sector_rs.py`), Task 4 (`test_apex_bulk.py`), Task 3 (`test_sector_rs_repository.py`), Task 6 (job test) |
| §9 acceptance | §9.1–9.4 are verified on the mini (post-merge runbook). §9.1 as rewritten: rows from 1998-12-22. The gate is `rs_12m IS NOT NULL` on at least 95% of gics rows from each fund's first_date + 252 sessions (about 2000-01 for the nine funds, 2016-10 XLRE, 2019-07 XLC); the runbook's first query checks it. The `degraded` share is reported per group per year by the second query and is not gated. |

Deviations from the spec's literal text, each deliberate:
- **Membership is a vendored current list, not apex.** Following the ruling above, argon never calls `/v1/membership/sp500`. The spec §2 table names the vendored file as the membership source, and breadth history is survivorship-biased. The list itself is livewire's preset, which labels its source "Wikipedia, March 2026".
- **The vendored file lives at `src/uw_scan/sources/data/`, not `src/uw_scan/data/`.** That follows the repo's per-package `data/` package-data convention (`uw_scan.cards/data`, `uw_scan.density/data`), next to its reader `sources/sp500_members.py`.
- **Delisted former members are unpriced.** No raw fallback is fetched for them. Under current membership they mostly do not appear at all.
- **`n_priced` is anchor-based.** A member needs a close on both of SPY's anchor sessions, instead of "≥253 closes". Rationale: Review Focus 1.
- **`degraded` is also true when `n_members == 0`.** An empty gics sector before the sector fill must not read as trustworthy.
- **§5 names `compute_group_rows(as_of, groups, closes, spy_closes)`.** This plan uses the caller's locked contract `(as_of, groups, closes, benchmark="SPY", source="apex")`, with SPY inside `closes`.
- **§9.1 now gates only the ETF leg.** The first draft's conflict (95% non-degraded, which the old 2021 ETF history made impossible) is resolved by livewire #157 and the rewritten §9.1. The gate is `rs_12m IS NOT NULL` on at least 95% of gics rows from each fund's first_date + 252 sessions. Breadth coverage (`degraded`) is thin in early years by construction (current list, survivorship), so it is reported per group per year and not gated; the §6 effective start is where it becomes usable. Nothing in code enforces either; the runbook's two queries check them after the backfill.
