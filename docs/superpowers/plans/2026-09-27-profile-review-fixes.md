# Profile-Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (the user's `/execute-plan` runs this as one linear thread) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the eight verified defects and hot spots from the 2026-09-27 engineering-profile diagnostic, in the order the diagnostic recommended: narrow SQL → deterministic logic bugs → compute reuse → request-time persistence boundary.

**Architecture:** Every change is local to the file the diagnostic named. No new services, tables, migrations, caches, or frameworks. Each task ends with a test that fails on the current code and passes after the change; measured speedups are not re-asserted in tests (they were established once in `output/profile-review/`), only equivalence of output is.

**Tech Stack:** Python 3.13 via `uv`, psycopg 3, pytest (`tests/unit/` fakes, `tests/integration/` real Postgres); Next.js 16 / React 19, Vitest + Testing Library.

**Spec:** `docs/research/engineering-profile/README.md` (summary, Chinese) with per-area evidence in `db-api.md`, `jobs-research.md`, `frontend.md` in the same directory. Baseline `9f094d0c` (v0.13.12). Branch `chore/profile-review`, worktree `.worktrees/profile-review/`.

## Global Constraints

- `uv run` only: `uv run pytest`, `uv run ruff check src/ tests/ scripts/`. Never bare `python`/`pytest`.
- Integration tests need local `option_wizard_local` + `option_wizard_test`; on the MacBook force the local DB env per the memory note (`.env.local` may point at the mini).
- Never commit without the user's explicit request. This plan lists commit steps; execute them only if the user has asked for milestone commits on this branch.
- CHANGELOG `[Unreleased]` entry rides this branch (Task 9), never a separate PR.
- Do not touch `src/uw_scan/storage/repository.py`; `technicals_repository.py` is its own module and is fine to edit.
- Do not touch `scripts/profile_review/` or `output/profile-review/` except where Task 7 says to retire the repro test. They are the diagnostic record.
- Web tests must not import `lightweight-charts`; none of the touched components do.
- No naked-short / trading logic is touched by any task.

## Review Focus

Inputs the spec implies but no diagnostic exercised. Each line's test is added to the owning task.

1. **`fetch_latest_macd_all` with a ticker whose only rows have `macd_hist_atr IS NULL`** — the ticker must still appear (as `None`), exactly as `DISTINCT ON` returned it. Pinned in Task 1.
2. **`current_macro_signal(as_of=<old date>)`** — a bounded load must be bounded relative to `as_of`, not today, or a replay returns "no usable row". Pinned in Task 5.
3. **`gather_inputs` when the report's `run_id` differs from `latest_run_id`** — prefetched rows for a historical run must NOT be substituted into the "latest" dealer overlay. Pinned in Task 6.
4. **ScanAllButton when every status GET rejects for the whole 10 minutes** — must end in `failed`, never `done`, and must stop polling. Pinned in Task 2.
5. **`option_surface_backfill` when a date has _more_ tickers captured than the current card set** (a ticker later removed from the watchlist) — still "fully captured", must skip. Pinned in Task 3.

---

### Task 1: `fetch_latest_macd_all` — one PK lookup per ticker instead of a full-history `DISTINCT ON`

**Files:**

- Modify: `src/uw_scan/storage/technicals_repository.py:195-204`
- Test: `tests/integration/storage/test_technicals_repository.py:100-107`

**Interfaces:**

- Consumes: table `uw_scan.technical_daily`, `PRIMARY KEY (ticker, as_of)` (migration `101`).
- Produces: unchanged signature `fetch_latest_macd_all(self) -> list[dict]` with keys `ticker`, `macd_hist_atr`, ordered by ticker.

- [ ] **Step 1: Extend the existing integration test so it pins "latest row wins" and the NULL case**

Replace `test_fetch_latest_macd_all` at `tests/integration/storage/test_technicals_repository.py:100-107` with:

```python
def test_fetch_latest_macd_all(seeded_db_empty_cards):
    trepo = TechnicalsRepository(seeded_db_empty_cards.conn)
    trepo.upsert_series("AAA", [_row(date(2026, 7, 7), 100.0)])
    older = _row(date(2026, 7, 6), 100.0)
    older["macd_hist_atr"] = -9.0
    newer = _row(date(2026, 7, 7), 101.0)
    newer["macd_hist_atr"] = 0.25
    trepo.upsert_series("BBB", [older, newer])
    nul = _row(date(2026, 7, 7), 50.0)
    nul["macd_hist_atr"] = None
    trepo.upsert_series("CCC", [nul])

    rows = trepo.fetch_latest_macd_all()
    by_ticker = {r["ticker"]: r["macd_hist_atr"] for r in rows}

    assert by_ticker["AAA"] == 0.1  # _row default
    assert by_ticker["BBB"] == 0.25  # the 07-07 row, not the 07-06 row
    assert "CCC" in by_ticker and by_ticker["CCC"] is None
    assert [r["ticker"] for r in rows] == sorted(r["ticker"] for r in rows)
```

- [ ] **Step 2: Run it — it must already PASS on the old query (this is an equivalence pin, not a red test)**

Run: `uv run pytest tests/integration/storage/test_technicals_repository.py::test_fetch_latest_macd_all -v`
Expected: PASS. If it fails, the fixture `_row` changed; fix the test, not the query.

- [ ] **Step 3: Replace the SQL with the diagnostic's validated candidate**

In `src/uw_scan/storage/technicals_repository.py:196-200`:

```python
        # ponytail: DISTINCT ON walked all ~268k history rows (89 ms warm);
        # enumerate tickers, then one PK-ordered LIMIT 1 each (20 ms). Same rows.
        sql = """
            SELECT tickers.ticker, latest.macd_hist_atr
              FROM (SELECT DISTINCT ticker FROM technical_daily) tickers
              CROSS JOIN LATERAL (
                  SELECT macd_hist_atr FROM technical_daily d
                   WHERE d.ticker = tickers.ticker
                   ORDER BY d.as_of DESC
                   LIMIT 1
              ) latest
             ORDER BY tickers.ticker
        """
```

(The diagnostic's candidate is schema-qualified; this method runs after `SET search_path`, so keep it unqualified like the original.)

- [ ] **Step 4: Run the test again, then the whole file**

Run: `uv run pytest tests/integration/storage/test_technicals_repository.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit (only if the user asked for milestone commits)**

```bash
git add src/uw_scan/storage/technicals_repository.py tests/integration/storage/test_technicals_repository.py
git commit -m "perf(technicals): latest-MACD lookup via per-ticker PK probe, not full-history DISTINCT ON"
```

---

### Task 2: `ScanAllButton` — deadline in a ref, failed status reads stay pending, and `LiveSpotsProvider` in-flight guard

**Files:**

- Modify: `web/components/shared/ScanAllButton.tsx:15-46`
- Modify: `web/components/watchlist/LiveSpotsProvider.tsx:34-55`
- Create: `web/tests/unit/scanAllButton.test.tsx`
- Modify: `web/tests/unit/liveSpots.test.tsx` (add one case)

**Interfaces:**

- Consumes: `api.job(id)`, `api.rescanAll()`, `api.watchlistSpots()` from `@/lib/api`; `useRouter` from `next/navigation`.
- Produces: no signature changes. Behavior: (a) polling stops at 600 s wall time from the FIRST poll tick, (b) a rejected status GET keeps that id pending instead of counting it as finished, (c) at most one spots request in flight.

Root cause of (a): `startedAt` lives inside a `useEffect` whose deps include `pendingIds`, and every tick calls `setPendingIds(newArray)`, so the effect re-runs and the deadline resets every 2 s. Root cause of (b): `api.job(id).catch(() => null)` then `.filter((r) => r && ...)` drops the null, so a failed read looks like "no longer pending".

- [ ] **Step 1: Write the failing tests**

Create `web/tests/unit/scanAllButton.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ScanAllButton } from "@/components/shared/ScanAllButton";
import { api } from "@/lib/api";

const { router } = vi.hoisted(() => ({ router: { refresh: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api", () => ({
  api: { job: vi.fn(), rescanAll: vi.fn() },
}));

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.mocked(api.rescanAll).mockResolvedValue([{ job_id: "mock-job" }] as never);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function startScan() {
  render(<ScanAllButton />);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^scan all$/i }));
    fireEvent.click(screen.getByRole("button", { name: /confirm scan all/i }));
  });
}

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

it("gives up after 10 minutes of a job that never finishes", async () => {
  vi.mocked(api.job).mockResolvedValue({
    job_id: "mock-job",
    status: "running",
  } as never);
  await startScan();
  for (let i = 0; i < 301; i++) await tick(2000);
  // 300 polls fit inside 600 s; the 301st tick is past the deadline and must bail.
  expect(api.job.mock.calls.length).toBeLessThanOrEqual(300);
  expect(screen.getByRole("button", { name: /failed/i })).toBeTruthy();
  expect(router.refresh).toHaveBeenCalledOnce();
  const calls = api.job.mock.calls.length;
  await tick(10_000);
  expect(api.job.mock.calls.length).toBe(calls); // no polling after bail
});

it("keeps polling when the status GET fails instead of reporting success", async () => {
  vi.mocked(api.job).mockRejectedValue(
    new Error("mock status transport unavailable"),
  );
  await startScan();
  await tick(2000);
  expect(screen.queryByRole("button", { name: /scanned/ })).toBeNull();
  expect(screen.getByRole("button", { name: /scanning 0\/1/ })).toBeTruthy();
  expect(router.refresh).not.toHaveBeenCalled();
  await tick(2000);
  expect(api.job).toHaveBeenCalledTimes(2); // still polling the same id
});

it("ends failed, not done, when status GETs fail for the whole deadline", async () => {
  vi.mocked(api.job).mockRejectedValue(new Error("down"));
  await startScan();
  for (let i = 0; i < 301; i++) await tick(2000);
  expect(screen.getByRole("button", { name: /failed/i })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /scanned/ })).toBeNull();
});
```

Append to `web/tests/unit/liveSpots.test.tsx` inside the `describe("LiveSpotsProvider")` block:

```tsx
it("never overlaps spot requests when a response outlives the poll period", async () => {
  vi.useFakeTimers();
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  const pending: Array<(v: { spots: [] }) => void> = [];
  vi.mocked(api.watchlistSpots).mockImplementation(
    () => new Promise((resolve) => pending.push(resolve)) as never,
  );
  render(
    <LiveSpotsProvider>
      <span />
    </LiveSpotsProvider>,
  );
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(api.watchlistSpots).toHaveBeenCalledTimes(1);
  await act(async () => {
    pending[0]({ spots: [] });
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(2500);
  });
  expect(api.watchlistSpots).toHaveBeenCalledTimes(2);
  vi.useRealTimers();
});
```

(`liveSpots.test.tsx` mocks `api.watchlistSpots` with `mockResolvedValue` at module level; `mockImplementation` inside the test overrides it for that test only. Import `api` from `@/lib/api` at the top of that file if it is not already imported.)

- [ ] **Step 2: Run them — expect the three ScanAllButton tests and the new liveSpots test to FAIL**

Run: `cd web && npx vitest run tests/unit/scanAllButton.test.tsx tests/unit/liveSpots.test.tsx`
Expected: 4 failures (deadline: `failed` button not found / more than 300 calls; GET failure: `scanned` button present; whole-deadline: `scanned` present; overlap: 3 calls instead of 1).

- [ ] **Step 3: Fix `ScanAllButton.tsx`**

Replace lines 15-46 (the polling `useEffect`) with:

```tsx
// Wall-clock deadline for the whole scan. Lives in a ref because the
// effect below re-runs on every setPendingIds; a `const startedAt` inside
// it reset the 10-minute limit every 2 s, so a zombie job polled forever.
const deadlineAt = useRef<number | null>(null);

useEffect(() => {
  if (phase !== "polling" || pendingIds.length === 0) return;
  if (deadlineAt.current === null) deadlineAt.current = Date.now() + 600_000;
  const t = setInterval(async () => {
    if (Date.now() > (deadlineAt.current ?? 0)) {
      clearInterval(t);
      deadlineAt.current = null;
      setPhase("failed");
      router.refresh();
      return;
    }
    try {
      const results = await Promise.all(
        pendingIds.map((id) =>
          api.job(id).catch(() => ({ job_id: id, status: "unknown" as const })),
        ),
      );
      // A rejected status read is NOT a finished job: keep it pending and
      // retry next tick. Only "done"/"failed" retire an id.
      const stillPending = results
        .filter((r) => r.status !== "done" && r.status !== "failed")
        .map((r) => r.job_id);
      setPendingIds(stillPending);
      if (stillPending.length === 0) {
        clearInterval(t);
        deadlineAt.current = null;
        const anyFailed = results.some((r) => r.status === "failed");
        setPhase(anyFailed ? "failed" : "done");
        router.refresh();
      }
    } catch (e) {
      console.error(e);
    }
  }, 2000);
  return () => clearInterval(t);
}, [phase, pendingIds, router]);
```

If `api.job`'s return type does not admit `status: "unknown"`, widen the mapped element type locally: `type Polled = { job_id: string; status: string }` and annotate `results` as `Polled[]`. Do not change `web/lib/types.ts` (generated).

- [ ] **Step 4: Fix `LiveSpotsProvider.tsx`**

Replace lines 34-50 (`let cancelled` through `setInterval`) with:

```tsx
let cancelled = false;
let inFlight = false; // ponytail: one request at a time; a slow API must not stack polls
const fetchOnce = async () => {
  if (document.hidden || inFlight) return;
  inFlight = true;
  try {
    const res = await api.watchlistSpots();
    if (cancelled) return;
    setSpots(new Map((res.spots ?? []).map((s) => [s.ticker, s])));
  } catch {
    // Transient fetch failure: keep the last map (or the server-rendered
    // values); the next tick retries.
  } finally {
    inFlight = false;
  }
};
fetchOnce();
const t = setInterval(fetchOnce, POLL_MS);
```

- [ ] **Step 5: Run the tests, typecheck, lint**

Run: `cd web && npx vitest run tests/unit/scanAllButton.test.tsx tests/unit/liveSpots.test.tsx tests/unit/watchlistUi.test.tsx && npm run typecheck && npm run lint`
Expected: all PASS, tsc clean, eslint clean.

- [ ] **Step 6: Commit**

```bash
git add web/components/shared/ScanAllButton.tsx web/components/watchlist/LiveSpotsProvider.tsx web/tests/unit/scanAllButton.test.tsx web/tests/unit/liveSpots.test.tsx
git commit -m "fix(web): scan-all deadline no longer resets per tick; failed status reads stay pending; single in-flight spot poll"
```

---

### Task 3: `option_surface_backfill` — compare ticker sets, not counts

**Files:**

- Modify: `src/uw_scan/worker/jobs/option_surface_capture.py:166-185`
- Create: `tests/unit/worker/test_option_surface_backfill_membership.py`

**Interfaces:**

- Consumes: `option_surface_backfill(*, repo, client, days_back, end_date, quota_limit, max_dates) -> int` (unchanged).
- Produces: a date is skipped only when every ticker in `cards` already has a row; missing members are captured; extra captured tickers (no longer on the watchlist) do not un-skip a complete date.

- [ ] **Step 1: Confirm the loop shape**

`option_surface_backfill` reads `cards = repo.list_watchlist_cards()` (line 148), builds `done` as a set of tickers already in `option_surface_grid_daily` for the date (lines 166-171), decides per DATE with `if len(done) >= len(cards): continue` (line 172 — the bug), then loops `for card in cards:` and per TICKER skips `if ticker.upper() in done` (line 188). Each captured ticker goes through `repo.insert_scan_run` → `_build_ticker_rows(client=, repo=, run_id=, ticker=, market_date=, date_iso=)` → `repo.upsert_option_surface_grid` → `repo.finish_scan_run` → `repo.conn.commit()`. The test below intercepts `_build_ticker_rows`.

- [ ] **Step 2: Write the failing test**

Create `tests/unit/worker/test_option_surface_backfill_membership.py`:

```python
"""The backfill used `len(done) >= len(cards)` to decide a date was complete.
Equal counts with different members skipped the missing member forever."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from uw_scan.worker.jobs import option_surface_capture as mod


class _Cur:
    def __init__(self, done_tickers: list[str]):
        self._done = done_tickers

    def execute(self, *_a, **_k):
        return None

    def fetchall(self):
        return [(t,) for t in self._done]

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _Repo:
    def __init__(self, done: list[str], cards: list[str]):
        self._done = done
        self._cards = cards
        self._schema = "uw_scan"
        self.conn = SimpleNamespace(
            cursor=lambda: _Cur(self._done), commit=lambda: None, rollback=lambda: None
        )

    def list_watchlist_cards(self):
        return [SimpleNamespace(ticker=t) for t in self._cards]

    def insert_scan_run(self, _ticker, notes=""):
        return 1

    def upsert_option_surface_grid(self, _ticker, _d, _spot, rows):
        return len(rows)

    def finish_scan_run(self, _run_id, status=""):
        return None


def _run(done: list[str], cards: list[str]) -> list[str]:
    """Return the tickers the backfill tried to capture for one weekday."""
    captured: list[str] = []

    def fake_rows(*, ticker, **_k):
        captured.append(ticker)
        return [{"row": 1}]

    client = SimpleNamespace(rate_limit=SimpleNamespace(daily_count=0))
    with patch.object(mod, "_build_ticker_rows", side_effect=fake_rows):
        mod.option_surface_backfill(
            repo=_Repo(done, cards),
            client=client,
            days_back=1,  # exactly one weekday ending yesterday
            end_date=date.today() - timedelta(days=1),
        )
    return captured


def test_same_count_different_members_captures_the_missing_one():
    assert _run(done=["AAPL", "MSFT"], cards=["AAPL", "NVDA"]) == ["NVDA"]


def test_superset_of_cards_is_fully_captured_and_skipped():
    assert _run(done=["AAPL", "MSFT", "OLD"], cards=["AAPL", "MSFT"]) == []


def test_exact_match_is_skipped():
    assert _run(done=["AAPL", "MSFT"], cards=["AAPL", "MSFT"]) == []
```

- [ ] **Step 3: Run — expect the first test to FAIL (captured == [] because 2 >= 2)**

Run: `uv run pytest tests/unit/worker/test_option_surface_backfill_membership.py -v`
Expected: `test_same_count_different_members_captures_the_missing_one` FAILS; the other two PASS.

- [ ] **Step 4: Fix the membership check**

In `option_surface_capture.py` replace lines 172-184 (`if len(done) >= len(cards):` through the log call) with:

```python
        missing = [card for card in cards if card.ticker.upper() not in done]
        if not missing:
            log.info("backfill: %s fully captured — skipping", date_iso)
            continue
        if max_dates is not None and dates_filled >= max_dates:
            log.info("backfill: max_dates=%d reached — stopping", max_dates)
            return written
        dates_filled += 1
        log.info(
            "backfill: capturing %s (%d/%d tickers remaining)",
            date_iso,
            len(missing),
            len(cards),
        )
        for card in missing:
```

and delete the old `for card in cards:` line that followed (the loop now iterates `missing`). Remove the now-redundant `if ticker.upper() in done: continue` at the old line 188.

- [ ] **Step 5: Run the new tests and the existing option-surface tests**

Run: `uv run pytest tests/unit/worker/test_option_surface_backfill_membership.py tests/unit/test_settings_option_surface.py tests/unit/test_scheduler_option_surface_gate.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/jobs/option_surface_capture.py tests/unit/worker/test_option_surface_backfill_membership.py
git commit -m "fix(option-surface): backfill compares captured ticker set to cards, not row counts"
```

---

### Task 4: `technical_daily_refresh` — build the series once per ticker

**Files:**

- Modify: `src/uw_scan/cards/technicals.py:827-835`
- Modify: `src/uw_scan/worker/jobs/technical_daily_refresh.py:70-96`
- Create: `tests/unit/cards/test_technicals_snapshot_reuse.py`

**Interfaces:**

- Consumes: `build_technical_series(bars, spy_bars=None) -> pd.DataFrame`, `build_technical_snapshot(bars, spy_bars=None) -> dict | None`.
- Produces: `build_technical_snapshot(bars, spy_bars=None, *, series: pd.DataFrame | None = None) -> dict | None`. When `series` is given it is used instead of recomputing; output is identical.

`build_technical_snapshot` calls `build_technical_series` at line 835, and the job calls `build_technical_series` again at line 95 for the upsert. Two tickers → four series builds. The fix is a keyword to pass the already-built frame in.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/cards/test_technicals_snapshot_reuse.py`:

```python
"""build_technical_snapshot must accept a precomputed series and produce the
same snapshot as when it builds the series itself."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

from uw_scan.cards import technicals as mod


def _bars(n: int = 260) -> list[dict]:
    d0 = date(2025, 9, 1)
    out = []
    px = 100.0
    for i in range(n):
        px *= 1.0 + (0.004 if i % 3 else -0.003)
        out.append(
            {
                "time": f"{d0 + timedelta(days=i)}T00:00:00Z",
                "open": px,
                "high": px * 1.01,
                "low": px * 0.99,
                "close": px,
                "volume": 1_000_000 + i,
            }
        )
    return out


def test_snapshot_with_prebuilt_series_matches_and_skips_rebuild():
    bars = _bars()
    series = mod.build_technical_series(bars)
    baseline = mod.build_technical_snapshot(bars)
    assert baseline is not None

    with patch.object(mod, "build_technical_series", wraps=mod.build_technical_series) as spy:
        reused = mod.build_technical_snapshot(bars, series=series)
    assert spy.call_count == 0
    assert reused == baseline
```

`bars_frame` (`cards/technicals.py:111-125`) derives `as_of` from an ISO `time` string, which is why the fixture emits `time`.

- [ ] **Step 2: Run — expect FAIL with `TypeError: unexpected keyword argument 'series'`**

Run: `uv run pytest tests/unit/cards/test_technicals_snapshot_reuse.py -v`

- [ ] **Step 3: Add the keyword to `build_technical_snapshot`**

In `src/uw_scan/cards/technicals.py:827-835`:

```python
def build_technical_snapshot(
    bars: list[dict],
    spy_bars: list[dict] | None = None,
    *,
    series: pd.DataFrame | None = None,
) -> dict | None:
    """Latest-day rich snapshot. None when <210 bars (200 SMA + slack) —
    callers surface 'too thin' rather than a silently wrong z.
    `series`: a frame already produced by build_technical_series(bars, spy_bars)
    for these exact inputs; skips the rebuild (the nightly job persists the
    same frame, so it builds once and passes it here)."""
    df = bars_frame(bars)
    if len(df) < 210:
        return None
    if series is None:
        series = build_technical_series(bars, spy_bars)
```

- [ ] **Step 4: Build once in the job**

In `src/uw_scan/worker/jobs/technical_daily_refresh.py` change line 70 and lines 95-96:

```python
            series = build_technical_series(bars, bench)
            snap = build_technical_snapshot(bars, bench, series=series)
```

(line 70), and at the old line 95 delete `series = build_technical_series(bars, bench)` so the block reads:

```python
            trepo.upsert_series(t, series_records(series))
```

Note `build_technical_series` on <210 bars returns an empty/short frame and `build_technical_snapshot` still returns `None` from its own length check, so the thin-history and no-source branches are unchanged.

- [ ] **Step 5: Run the new test plus the technicals suites**

Run: `uv run pytest tests/unit/cards/test_technicals_snapshot_reuse.py tests/unit/cards/test_technicals_dual_wiring.py tests/unit/worker/test_technical_daily_freshness_enrolled.py -v && uv run ruff check src/ tests/`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/technicals.py src/uw_scan/worker/jobs/technical_daily_refresh.py tests/unit/cards/test_technicals_snapshot_reuse.py
git commit -m "perf(technicals): nightly refresh builds each ticker's series once"
```

---

### Task 5: `load_index_vol` — bounded window for the signal paths, full history for backtests

**Files:**

- Modify: `src/uw_scan/reports/vrp_macro_drawdown.py:178-198`
- Modify: `src/uw_scan/reports/vrp_macro_signal.py:304, 388`
- Create: `tests/unit/reports/test_vrp_macro_drawdown_window.py`

**Interfaces:**

- Consumes: `load_index_vol(repo, name, *, lake_root=None, rv_window=20, z_window=252) -> _Loaded`; `_build_loaded(spot, vol, *, rv_window, z_window)`.
- Produces: `load_index_vol(..., since: date | None = None)`. When `since` is set, every source read starts at `max(spec["start"], since)`. New module constant `SIGNAL_LOOKBACK_DAYS = 420` (calendar days; ≈290 sessions > the 20 + 252 + 1 rows the latest row's rv and 252-window z need).

Callers that need full history (`run_index_drawdown`, `backtest_laddered` via the worker job) keep calling without `since`. Only `current_macro_signal` and `current_macro_signal_live` pass `since=(as_of or today) - SIGNAL_LOOKBACK_DAYS`. The bound is relative to `as_of` so replays still work (Review Focus 2).

- [ ] **Step 1: Write the failing test**

Create `tests/unit/reports/test_vrp_macro_drawdown_window.py`:

```python
"""A window-bounded load must reproduce the full load's latest row exactly
(rv, vrp, z) and be bounded relative to the caller's `since`, not today."""

from __future__ import annotations

import math
from datetime import date, timedelta

from uw_scan.reports import vrp_macro_drawdown as mod

D0 = date(2020, 1, 1)


def _series(n: int) -> tuple[dict, dict]:
    spot, vol = {}, {}
    px = 3000.0
    for i in range(n):
        d = D0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        px *= 1.0 + 0.01 * math.sin(i / 7.0)
        spot[d] = px
        vol[d] = 15.0 + 8.0 * abs(math.sin(i / 11.0))
    return spot, vol


class _Repo:
    """Serves vol_index_daily rows for SPX/VIX from an in-memory series,
    honouring the `trade_date >= %s` bound the real query applies."""

    def __init__(self, spot, vol):
        self._by_symbol = {"SPX": spot, "VIX": vol}
        self.reads: list[tuple[str, date]] = []

        repo = self

        class _Cur:
            def __init__(self):
                self._rows = []

            def execute(self, _sql, params):
                symbol, start = params
                repo.reads.append((symbol, start))
                src = repo._by_symbol[symbol]
                self._rows = [(d, c) for d, c in sorted(src.items()) if d >= start]

            def fetchall(self):
                return self._rows

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        class _Conn:
            def cursor(self):
                return _Cur()

        self.conn = _Conn()


def test_bounded_load_matches_full_load_latest_row_and_bounds_reads():
    spot, vol = _series(1500)
    repo = _Repo(spot, vol)
    full = mod.load_index_vol(repo, "SPX")
    as_of = max(spot)
    since = as_of - timedelta(days=mod.SIGNAL_LOOKBACK_DAYS)
    bounded = mod.load_index_vol(repo, "SPX", since=since)

    assert bounded.rows[-1] == full.rows[-1]
    assert bounded.rows[-1]["vrp_z_20"] is not None
    assert len(bounded.rows) < len(full.rows)
    assert all(start >= since for _s, start in repo.reads[2:])


def test_since_before_spec_start_is_clamped_to_spec_start():
    spot, vol = _series(400)
    repo = _Repo(spot, vol)
    mod.load_index_vol(repo, "SPX", since=date(1990, 1, 1))
    spec_start = mod.INDEX_SPECS["SPX"]["start"]
    assert all(start == spec_start for _s, start in repo.reads)
```

If `INDEX_SPECS["SPX"]` has `spot_source != "vol_index"`, pick whichever spec name in `INDEX_SPECS` uses `vol_index` for both legs (the docstring at `vrp_macro_drawdown.py:20-30` says SPX/VIX do) and adjust the `_by_symbol` keys to that spec's `vol` and `spot_symbol`.

- [ ] **Step 2: Run — expect FAIL with `TypeError: unexpected keyword argument 'since'`**

Run: `uv run pytest tests/unit/reports/test_vrp_macro_drawdown_window.py -v`

- [ ] **Step 3: Add `since` and the constant to `load_index_vol`**

In `src/uw_scan/reports/vrp_macro_drawdown.py`, above `load_index_vol`:

```python
# Calendar-day lookback that still yields the latest row's rv (20 sessions) and
# its 252-value z-window with margin (~290 sessions). Signal paths read only this
# much; backtests/drawdown reports keep loading from the spec start.
SIGNAL_LOOKBACK_DAYS = 420
```

and change the function to:

```python
def load_index_vol(
    repo,
    name: str,
    *,
    lake_root: pathlib.Path | None = None,
    rv_window: int = 20,
    z_window: int = 252,
    since: _date | None = None,
) -> _Loaded:
    """Build a `_Loaded` for an index from its IV proxy + spot source (INDEX_SPECS).
    `since` bounds every source read to max(spec start, since); rows before the
    first rv_window/z_window sessions of the window carry rv/z = None, exactly
    as the first rows of a full load do."""
    spec = INDEX_SPECS[name]
    start = spec["start"]
    if since is not None and since > start:
        start = since
```

The remainder of the body is unchanged (it already threads `start` into every reader).

- [ ] **Step 4: Bound the two signal loaders**

In `src/uw_scan/reports/vrp_macro_signal.py` add to the import at line 38: `SIGNAL_LOOKBACK_DAYS` from `uw_scan.reports.vrp_macro_drawdown`, and add `from datetime import timedelta` if not present. Then at line 304 (`current_macro_signal`) and line 388 (`current_macro_signal_live`) replace

```python
    loaded = load_index_vol(repo, name, lake_root=lake_root)
```

with

```python
    since = (as_of or _date.today()) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
    loaded = load_index_vol(repo, name, lake_root=lake_root, since=since)
```

Do NOT touch `worker/jobs/vrp_macro_signal.py:61` (it feeds `backtest_laddered`, which needs full history) or `run_index_drawdown`.

- [ ] **Step 5: Run the new test and every VRP-macro suite**

Run: `uv run pytest tests/unit/reports/test_vrp_macro_drawdown_window.py tests/unit/reports/test_vrp_macro_drawdown.py tests/unit/test_vrp_macro_signal_strikes.py tests/unit/worker/test_vrp_macro_entry_schedule.py -v`
Expected: all PASS. `test_vrp_macro_signal_strikes.py` monkeypatches `load_index_vol` with a fake; confirm the fake at lines 120-125 and 193-197 accepts `**kwargs` (add `**_kw` to its signature if it does not, since it now receives `since=`).

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/reports/vrp_macro_drawdown.py src/uw_scan/reports/vrp_macro_signal.py tests/unit/reports/test_vrp_macro_drawdown_window.py tests/unit/test_vrp_macro_signal_strikes.py
git commit -m "perf(vrp-macro): signal paths load a bounded window; backtests keep full history"
```

---

### Task 6: `assemble_single_stock_report` — read each dealer primitive once

**Files:**

- Modify: `src/uw_scan/cards/dealer_regime.py:459-500`
- Modify: `src/uw_scan/reports/single_stock.py:129-150, 316, 330, 347, 375, 431`
- Modify: `tests/unit/test_report_assembly.py` (add one test)
- Create: `tests/unit/cards/test_dealer_regime_prefetched.py`

**Interfaces:**

- Consumes: `gather_inputs(repo, *, ticker, today=None) -> dict`; `_build_market_structure(repo, run_id, ticker, max_pain_rows) -> MarketStructure`.
- Produces: `gather_inputs(repo, *, ticker, today=None, prefetched: dict | None = None)`. `prefetched` carries `{"run_id": int, "strike_gex_curve": list, "exposures_summary": list, "realized_vol": dict | None, "exposures_aggregate": dict | None}` and is honoured only when `prefetched["run_id"] == repo.latest_run_id(ticker)` (Review Focus 3). `_build_market_structure(repo, run_id, ticker, max_pain_rows, *, exposures: dict, rv: dict | None)` takes the two rows it used to fetch itself.

The diagnostic measured five SQL+parameter pairs executed twice in one assembly: latest-run lookup, exposures aggregate, realized-vol latest, strike-GEX curve, exposures summary. Four are the report reading a primitive and then `gather_inputs` reading it again. The latest-run lookup stays (the dealer overlay is deliberately "latest", the report is "this run").

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/cards/test_dealer_regime_prefetched.py`:

```python
"""gather_inputs reuses rows the report already read — but only for the same run."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from uw_scan.cards import dealer_regime as mod


class _Repo:
    def __init__(self, latest: int):
        self.calls: list[str] = []
        self._latest = latest
        self.conn = SimpleNamespace()
        self._schema = "uw_scan"

    def latest_run_id(self, _t):
        self.calls.append("latest_run_id")
        return self._latest

    def get_strike_gex_curve(self, _run):
        self.calls.append("get_strike_gex_curve")
        return []

    def fetch_exposures_summary(self, _run, _t):
        self.calls.append("fetch_exposures_summary")
        return []

    def fetch_realized_vol_latest(self, _t):
        self.calls.append("fetch_realized_vol_latest")
        return {"price": 100.0}

    def fetch_exposures_aggregate(self, _run, _t):
        self.calls.append("fetch_exposures_aggregate")
        return {"total_call_gex": 1.0, "total_put_gex": -0.5}


PRE = {
    "run_id": 7,
    "strike_gex_curve": [],
    "exposures_summary": [],
    "realized_vol": {"price": 100.0},
    "exposures_aggregate": {"total_call_gex": 1.0, "total_put_gex": -0.5},
}


def _gather(repo, prefetched):
    fake_hist = SimpleNamespace(fetch_history=lambda _t, days: [])
    with patch.object(mod, "GreekExposureDailyRepository", lambda *_a, **_k: fake_hist):
        return mod.gather_inputs(repo, ticker="AAPL", today=date(2026, 9, 25), prefetched=prefetched)


def test_same_run_skips_the_four_reads():
    repo = _Repo(latest=7)
    out = _gather(repo, PRE)
    assert out["run_id"] == 7
    assert out["spot"] == 100.0 and out["net_gex"] == 0.5
    assert repo.calls == ["latest_run_id"]


def test_different_run_ignores_prefetched_rows():
    repo = _Repo(latest=8)
    _gather(repo, PRE)
    assert set(repo.calls) == {
        "latest_run_id",
        "get_strike_gex_curve",
        "fetch_exposures_summary",
        "fetch_realized_vol_latest",
        "fetch_exposures_aggregate",
    }


def test_no_prefetched_is_unchanged():
    repo = _Repo(latest=7)
    _gather(repo, None)
    assert repo.calls.count("get_strike_gex_curve") == 1
```

`GreekExposureDailyRepository` is imported inside `gather_inputs` (`dealer_regime.py:475`), so `patch.object(mod, ...)` cannot intercept it. Step 3 hoists that one import (`from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository`) to the module's import block; the module docstring says it is DB-free but the function already imports a repository, so the hoist changes nothing at runtime. If the hoist raises `ImportError` (circular), keep it local and instead patch `uw_scan.storage.greek_exposure_repository.GreekExposureDailyRepository`.

Append to `tests/unit/test_report_assembly.py`:

```python
def test_assembly_reads_each_dealer_primitive_once():
    repo = _StubRepo()
    counts: dict[str, int] = {}
    for name in (
        "get_strike_gex_curve",
        "fetch_exposures_summary",
        "fetch_realized_vol_latest",
        "fetch_exposures_aggregate",
    ):
        orig = getattr(repo, name)

        def counted(*a, _n=name, _o=orig, **k):
            counts[_n] = counts.get(_n, 0) + 1
            return _o(*a, **k)

        setattr(repo, name, counted)
    assemble_single_stock_report("AAPL", run_id=repo.latest_run_id("AAPL"), repo=repo)
    assert counts == {
        "get_strike_gex_curve": 1,
        "fetch_exposures_summary": 1,
        "fetch_realized_vol_latest": 1,
        "fetch_exposures_aggregate": 1,
    }
```

Read `_StubRepo` (lines 40-280) first: it must define all four methods plus `latest_run_id`; if `latest_run_id` is missing, add `def latest_run_id(self, _t): return 1` to the stub and pass `run_id=1`.

- [ ] **Step 2: Run — expect FAIL (`TypeError: unexpected keyword 'prefetched'`; assembly test counts 2 for each)**

Run: `uv run pytest tests/unit/cards/test_dealer_regime_prefetched.py tests/unit/test_report_assembly.py -v`

- [ ] **Step 3: Add `prefetched` to `gather_inputs`**

In `src/uw_scan/cards/dealer_regime.py:459` change the signature and the four reads (lines 493-500):

```python
def gather_inputs(
    repo: Any,
    *,
    ticker: str,
    today: _date | None = None,
    prefetched: dict | None = None,
) -> dict:
    """...(existing docstring)...

    `prefetched`: rows the report assembler already read for ITS run
    (`run_id`, `strike_gex_curve`, `exposures_summary`, `realized_vol`,
    `exposures_aggregate`). Used only when that run_id is also the latest run,
    so the dealer overlay keeps its "latest" semantics on a historical replay.
    """
```

and

```python
    pre = prefetched if prefetched and prefetched.get("run_id") == run_id else {}
    strike_curve_raw = (
        pre["strike_gex_curve"] if "strike_gex_curve" in pre
        else repo.get_strike_gex_curve(run_id)
    ) or []
    exposures = (
        pre["exposures_summary"] if "exposures_summary" in pre
        else repo.fetch_exposures_summary(run_id, t)
    ) or []

    rv_row = (
        pre["realized_vol"] if "realized_vol" in pre
        else repo.fetch_realized_vol_latest(t)
    ) or {}
    spot_raw = rv_row.get("price")
    spot_f = _to_float(spot_raw)

    exp_agg = (
        pre["exposures_aggregate"] if "exposures_aggregate" in pre
        else repo.fetch_exposures_aggregate(run_id, t)
    ) or {}
```

- [ ] **Step 4: Read once in `single_stock.py` and thread the rows through**

Change `_build_market_structure` (line 129-150) to take the rows:

```python
def _build_market_structure(
    repo: Repository,
    run_id: int,
    ticker: str,
    max_pain_rows: list[MaxPainRow],
    *,
    exposures: dict,
    rv: dict | None,
) -> MarketStructure:
    total_call_gex = _to_decimal(exposures.get("total_call_gex"))
```

deleting its own `exposures = repo.fetch_exposures_aggregate(run_id, ticker) or {}` (line 132) and its own `rv = repo.fetch_realized_vol_latest(ticker)` (line 149). Then in `assemble_single_stock_report`:

```python
    exposures_agg = repo.fetch_exposures_aggregate(run_id, ticker) or {}
    rv_latest = repo.fetch_realized_vol_latest(ticker)
    market_structure = _build_market_structure(
        repo, run_id, ticker, max_pain_rows, exposures=exposures_agg, rv=rv_latest
    )
```

(line 316), keep `curve_raw = repo.get_strike_gex_curve(run_id)` (330) and `summary_raw = repo.fetch_exposures_summary(run_id, ticker)` (375) as they are, and at line 431:

```python
    dr_inputs = gather_inputs(
        repo,
        ticker=ticker,
        prefetched={
            "run_id": run_id,
            "strike_gex_curve": curve_raw,
            "exposures_summary": summary_raw,
            "realized_vol": rv_latest,
            "exposures_aggregate": exposures_agg,
        },
    )
```

Grep `_build_market_structure(` across `src/` and `tests/` to confirm line 316 is the only caller; if a test calls it, update that call with the two new keywords.

- [ ] **Step 5: Run the dealer + report suites**

Run: `uv run pytest tests/unit/cards/test_dealer_regime_prefetched.py tests/unit/cards/test_dealer_regime.py tests/unit/test_report_assembly.py tests/unit/test_pipeline_replay.py tests/unit/api/test_stock_report_cache.py -v && uv run ruff check src/ tests/`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/dealer_regime.py src/uw_scan/reports/single_stock.py tests/unit/cards/test_dealer_regime_prefetched.py tests/unit/test_report_assembly.py
git commit -m "perf(report): single-stock assembly reads each dealer primitive once; overlay keeps latest-run semantics"
```

---

### Task 7: Stock `TabBar` — stop prefetching seven unvisited tabs

**Files:**

- Modify: `web/components/stock/TabBar.tsx:31-35`
- Create: `web/tests/unit/stockTabBar.test.tsx`
- Delete: `scripts/profile_review/frontend.test.tsx` (its three assertions pin the _defects_ and are now contradicted by Tasks 2 and 7; the diagnostic's browser evidence stays in `output/profile-review/frontend/`)

**Interfaces:**

- Consumes: `next/link` `Link` with `prefetch` prop.
- Produces: unchanged component API. Each tab `<Link>` renders with `prefetch={false}`; navigation still works on click (Next fetches on demand).

The diagnostic counted 7 unvisited-tab prefetches and 16 requests including 5 full stock reports on one visit. `web/tests/unit/macroTabBar.test.tsx` already shows the pattern for asserting the `prefetch` prop through a mocked `next/link`.

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/stockTabBar.test.tsx`, modelled on `macroTabBar.test.tsx:12-30` (read it first and reuse its exact `next/link` mock shape):

```tsx
/* @vitest-environment jsdom */
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TabBar } from "@/components/stock/TabBar";

const seen: Array<boolean | undefined> = [];
vi.mock("next/link", () => ({
  default: ({
    prefetch,
    href,
    children,
  }: {
    prefetch?: boolean;
    href: string;
    children: React.ReactNode;
  }) => {
    seen.push(prefetch);
    return <a href={href}>{children}</a>;
  },
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/stock/AAPL/overview",
}));

describe("stock TabBar", () => {
  it("does not prefetch any tab", () => {
    render(<TabBar ticker="AAPL" />);
    expect(seen.length).toBeGreaterThan(1);
    expect(seen.every((p) => p === false)).toBe(true);
  });
});
```

Read `TabBar.tsx:1-25` for its real props (it may take `path` instead of using `usePathname`) and fix the render call and the navigation mock accordingly. Check the exported name (`TabBar` vs default export).

- [ ] **Step 2: Run — expect FAIL (`seen.every(false)` is false because `prefetch` is `true`)**

Run: `cd web && npx vitest run tests/unit/stockTabBar.test.tsx`

- [ ] **Step 3: Change the prop**

In `web/components/stock/TabBar.tsx:34` replace the bare `prefetch` with:

```tsx
            prefetch={false}
```

- [ ] **Step 4: Retire the baseline-defect repro test**

```bash
git rm scripts/profile_review/frontend.test.tsx
```

and remove the `frontend.test.tsx` mention from `docs/research/engineering-profile/frontend.md`'s "Reproduce" section, replacing it with one line: "Component reproductions were converted into regression tests: `web/tests/unit/scanAllButton.test.tsx`, `liveSpots.test.tsx`, `stockTabBar.test.tsx`." Keep `frontend.config.mts`, `frontend-browser.mjs`, `frontend-stub.mjs` (they still reproduce the browser evidence).

- [ ] **Step 5: Run web tests, typecheck, lint**

Run: `cd web && npx vitest run tests/unit/stockTabBar.test.tsx tests/unit/macroTabBar.test.tsx && npm run typecheck && npm run lint`
Expected: PASS, clean.

- [ ] **Step 6: Commit**

```bash
git add web/components/stock/TabBar.tsx web/tests/unit/stockTabBar.test.tsx docs/research/engineering-profile/frontend.md
git rm --cached scripts/profile_review/frontend.test.tsx 2>/dev/null; git add -A scripts/profile_review
git commit -m "perf(web): stock tabs no longer prefetch seven unvisited reports"
```

---

### Task 8: `GET /volatility/{ticker}` — stop persisting derived series on read

**Files:**

- Modify: `src/uw_scan/api/routers/volatility.py:164`
- Create: `tests/unit/api/test_volatility_series_get_is_read_only.py`

**Interfaces:**

- Consumes: `assemble_volatility_series(*, ticker, repo, backfill_status="ready", persist_derived=True)` (flag already exists; `trade_insights.py:293` already passes `False`).
- Produces: the GET passes `persist_derived=False`. `nightly_vol_analytics_rollup` (`worker/volatility_jobs.py:60-87`) remains the sole writer of `vrp_daily` / `stock_analytics` for watchlist tickers.

**Stated trade-off (user decision, do not silently change):** a ticker that is NOT on the watchlist and has never been rolled up will no longer get `vrp_daily` rows populated by someone opening its page, so its short-vol card (which reads `vrp_daily`) stays empty until it is added to the watchlist and the nightly rollup runs. The diagnostic ranked this last and called it an architecture issue, not a measured bottleneck; this task implements the minimal boundary move. If the user wants page-open population for off-watchlist names, the alternative is a one-line `persist_derived=not repo.is_on_watchlist(ticker)`; do not add it unasked.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/api/test_volatility_series_get_is_read_only.py`:

```python
"""The read endpoint must not ask the assembler to persist derived series."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import BackgroundTasks

from uw_scan.api.routers import volatility as router_mod


class _Repo:
    """Fresh history, no persisted backfill row → status 'ready', no background task."""

    def count_realized_vol_history(self, _t, days):
        return days

    def get_volatility_backfill_status(self, _t):
        return None


def test_get_volatility_series_passes_persist_derived_false():
    captured: dict = {}

    def fake_assemble(**kwargs):
        captured.update(kwargs)
        return "sentinel"

    with patch.object(router_mod, "assemble_volatility_series", fake_assemble):
        result = router_mod.get_volatility_series(
            ticker="aapl", background_tasks=BackgroundTasks(), repo=_Repo()
        )
    assert result == "sentinel"
    assert captured["ticker"] == "AAPL"
    assert captured["backfill_status"] == "ready"
    assert captured["persist_derived"] is False
```

`get_volatility_series` (`volatility.py:136-164`) is a plain sync function taking `ticker`, `background_tasks`, `repo`; calling it directly bypasses `Depends`. `count_realized_vol_history` returning `days` keeps `history_fresh >= HISTORY_THRESHOLD_DAYS`, so no `_kick_backfill` task is queued.

- [ ] **Step 2: Run — expect FAIL (`KeyError: 'persist_derived'`)**

Run: `uv run pytest tests/unit/api/test_volatility_series_get_is_read_only.py -v`

- [ ] **Step 3: Pass the flag**

In `src/uw_scan/api/routers/volatility.py:164`:

```python
    # Read path is read-only: derived vrp_daily/stock_analytics rows are written
    # by nightly_vol_analytics_rollup, not by whoever opens the page (one GET
    # was issuing ~594 upserts + a commit).
    return assemble_volatility_series(
        ticker=t, repo=repo, backfill_status=status, persist_derived=False
    )
```

- [ ] **Step 4: Run the test plus the volatility router/report suites**

Run: `uv run pytest tests/unit/api/test_volatility_series_get_is_read_only.py tests/unit/api -k volatility -v && uv run ruff check src/ tests/`
Expected: PASS, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/api/routers/volatility.py tests/unit/api/test_volatility_series_get_is_read_only.py
git commit -m "fix(api): volatility series GET no longer upserts derived rows"
```

---

### Task 9: CHANGELOG + diagnostic README status + full gates

**Files:**

- Modify: `CHANGELOG.md` (`[Unreleased]`)
- Modify: `docs/research/engineering-profile/README.md` (last paragraph)

- [ ] **Step 1: CHANGELOG entry under `[Unreleased]`**

```markdown
### Fixed

- Scan-all button: 10-minute polling deadline reset on every tick (a zombie job polled forever); a failed status GET was counted as "scanned". Live-spot poller now keeps one request in flight.
- Option-surface backfill compared captured-row COUNT to the card count, so equal counts with different members skipped the missing ticker forever; now compares the ticker set.
- `GET /volatility/{ticker}` no longer upserts derived `vrp_daily`/`stock_analytics` rows (the nightly rollup owns them).

### Performance

- Latest-MACD watchlist lookup probes one PK row per ticker instead of scanning full history (89 → 20 ms warm, prod EXPLAIN).
- VRP macro signal paths load a 420-day window instead of full index history (492 → 6 ms offline); backtests keep full history.
- Nightly technicals refresh builds each ticker's series once (was twice).
- Single-stock report reads each dealer-regime primitive once (four duplicate SELECTs removed).
- Stock page tabs no longer prefetch seven unvisited reports on first paint.
```

- [ ] **Step 2: Mark the diagnostic README**

Replace the last sentence of `docs/research/engineering-profile/README.md` ("当前工作是诊断完成，不是修复完成。…") with:

```markdown
2026-09-27 起，上述八项均已在同一分支修复，计划见 `docs/superpowers/plans/2026-09-27-profile-review-fixes.md`；测量数字未重跑，只在测试中固定了输出等价性。
```

- [ ] **Step 3: Run the CI-equivalent gates**

```bash
uv run ruff check src/ tests/ scripts/
uv run pytest tests/unit/ -q
uv run pytest tests/integration/storage/test_technicals_repository.py -q
cd web && npm run typecheck && npm run lint && npm run test
```

Expected: every command exits 0. Paste the tail of each into the handoff. If a pre-existing unrelated test fails, report it by name; do not fix it in this branch.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/research/engineering-profile/README.md
git commit -m "docs: changelog + profile-review status for the eight fixes"
```

- [ ] **Step 5: Push and open the PR (only when the user says "push")**

Branch `chore/profile-review` → PR to `main` via `gh pr create`; title `perf/fix: apply the eight profile-review findings`; body summarises the table in `docs/research/engineering-profile/README.md` and links the plan. Wait for CI green before any merge.
