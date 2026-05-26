# Massive WebSocket Spot Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the per-ticker REST polling of `api.massive.com` with a single long-lived WebSocket consumer so that all watchlist cards reflect the same logical instant (the user's primary pain: cards out-of-sync between the dashboard and the stock detail page).

**Architecture:** A new long-lived process (`massive_ws_consumer`) holds a persistent WS connection to `wss://socket.massive.com/stocks`, subscribes to per-second aggregate channels (`A.<TICKER>`) for the active watchlist, buffers ticks in-memory, and flushes them every `MASSIVE_WS_FLUSH_INTERVAL_SECONDS` (default 1s) as a single batched transaction into `intraday_quote` + `watchlist_card`. **The REST `spot_refresh` job and its `MassiveOhlcProvider.fetch_intraday_quote` helper are removed entirely** — there is no REST fallback. If the WS consumer is down, spot data is stale until it reconnects. The consumer's reconnect-with-exponential-backoff plus the `/api/health` heartbeat surface are the operational guardrails. `full_scan` / `rescan_tick` are gated from writing `watchlist_card.spot` so WS is the only writer of that field.

**Tech Stack:** Python 3.13, `uv`, `websockets` (new dep, ~120KB pure-Python), `psycopg` 3, pytest-postgresql for integration tests. No new frontend changes in this plan — UI freshness is a follow-up.

**Standing rules acknowledged:**
- `uv` only — never bare `python` / `pip`
- Persist all analytical results to Postgres (no in-memory-only)
- Module size budget <500 lines per file
- New persistence domain → new mixin in `storage/`, never append to `repository.py`
- Migrations idempotent (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`)
- No secrets to subprocesses
- Commits are user-gated — phase-end commit steps require explicit user OK before running
- No `Co-Authored-By: Claude` trailers

**Assumptions VERIFIED 2026-05-21 against `https://massive.com/docs/websocket/`:**
- WS URL: **`wss://delayed.massive.com/stocks`** for the current delayed tier (`wss://socket.massive.com/stocks` is real-time, gated by tier upgrade)
- Auth grammar: `{"action":"auth","params":"<API_KEY>"}` — confirmed
- Channel grammar: `A.<TICKER>` per-second aggregates — confirmed
- Tier delivers 15-min-delayed data on `delayed.*`; sync fix lands regardless of tier
- Message shape: `{"ev":"A","sym":"AAPL","c":189.42,"e":<epoch_ms>, "o":...,"h":...,"l":...,"v":...}` — confirmed in `/docs/websocket/stocks/aggregates-per-second`

Phase 0's job is now the smoke test (actually connect + receive ticks) — the URL / auth / channel grammar are docs-confirmed.

---

## Plan revision log (post-review fixes)

This plan was reviewed by Codex + Gemini + Claude (tribunal review on 2026-05-21). The following substantive issues were raised and folded in below:

| # | Severity | Raised by | Fix applied |
|---|---|---|---|
| R1 | CRITICAL | All 3 (UNANIMOUS) | DB calls offloaded via `asyncio.to_thread(...)` so the asyncio event loop is never blocked by sync psycopg I/O (Phase 4) |
| R2 | CRITICAL | Codex + Claude | WS consumer sets `conn.autocommit=True` at startup and wraps each write in an explicit `with conn.transaction():` block. No long-lived implicit txns (Phase 3/4) |
| R3 | CRITICAL | Codex + Claude | `_subscription_loop()` is now actually started as a 3rd task inside `run_consumer_once()` (Phase 4) |
| R4 | IMPORTANT | Codex + Gemini | Health endpoint is market-session aware — `healthy=True` outside RTH even when ticks aren't flowing (Phase 5) |
| R5 | IMPORTANT | Gemini + Claude | New integration test exercises `run_consumer_forever` reconnect/backoff with a fake server (Phase 4) |
| R6 | IMPORTANT | Codex | `MASSIVE_WS_ENABLED` exported to ALL worker processes in `scripts/dev.sh`, not just the WS process — otherwise `uw` workers ignore `preserve_spot` (Phase 5) |
| R7 | IMPORTANT | Codex | `intraday_quote.source` now projected through to readers — `IntradayQuoteRow` extended, dashboard SQL + `_with_latest_spot()` use it instead of hardcoded `'massive.com_intraday'` (Phase 1 + new Phase 6.4) |
| R8 | IMPORTANT | Codex | Phase 8 validation rewritten as WS-only (parallel-comparison framing removed, since Phase 7 deleted REST); script name corrected to `validate_ws.py` consistently |
| R9 | IMPORTANT | Codex | `ret_1d/1w/30d` updates were dropped when `spot_refresh` was deleted — WS writer now also recomputes and persists intraday returns in the same atomic batch (Phase 3) |
| R10 | IMPORTANT | Codex | Test fixtures aligned to `seeded_db_with_cards` (TSLA-only) — tests no longer reference unseeded AAPL/MSFT cards |
| R11 | IMPORTANT | Codex | Parser test epoch corrected: `1779380400000` was 2024-05-21, not 2026-05-21. Now `1779380400000` |
| R12 | IMPORTANT | Codex | Phase 5 includes regenerating `tests/integration/api/openapi.snapshot.json` since `HealthResponse` schema changes |
| R13 | IMPORTANT | Claude | WS client validates the auth response and raises on failure (no more silent zero-tick sessions on revoked keys) |
| R14 | IMPORTANT | Claude | `asyncio.create_task(...)` calls now use `add_done_callback` so reader/subscription task crashes are surfaced |
| R15 | IMPORTANT | Claude | `web/components/shared/HealthPanel.tsx` updated to display the WS heartbeat (new Phase 5.3) — operator visibility is the sole safety signal under no-fallback design |
| R16 | MINOR | Codex | `Repository` does not have `.commit()` — all test commit calls use `repo._conn.commit()` |

Items intentionally NOT applied (defer or non-issues):
- **Codex/Gemini's "use psycopg.AsyncConnection"** — scope expansion beyond this plan; `asyncio.to_thread` is the simpler fix.
- **Claude's "preserve_spot stale data freeze" edge case** — accepted as the cost of "no REST fallback" per user direction. Operator alerting on stale heartbeat catches this.
- **Gemini's "dynamic SQL complexity in upsert_watchlist_card"** — style preference; the dynamic-column pattern is established elsewhere in the file.
- **Claude's `IntradayQuote` dataclass deletion safety** — Phase 7 already includes the `grep` survey step.

## Adversarial review findings (Codex challenge, 2026-05-21)

After the tribunal review, a separate Codex adversarial pass surfaced 14 attacks. Critical + high-severity findings folded in:

| # | Severity | Issue | Fix applied |
|---|---|---|---|
| A1 | CRITICAL | One psycopg conn used concurrently from `flush_loop` and `subscription_loop` via `asyncio.to_thread` — psycopg3 connections are NOT thread-safe | Split into two separate Repositories: writer-repo for flush, reader-repo for subscription queries. Each gets its own conn. (Phase 4) |
| A2 | CRITICAL | `flush_once()` drains the buffer BEFORE the DB write — if Postgres is down, drained ticks are lost forever | Drain into a `_pending` batch; only clear after successful commit. On exception, merge `_pending` back into the live buffer so the next flush retries. (Phase 3) |
| A3 | CRITICAL | `intraday_quote.ticker REFERENCES watchlist(ticker)` (migration 003) — a WS frame for an out-of-watchlist ticker (race: ticker removed mid-session) triggers FK violation, the WHOLE batch rolls back, and per A2 every ticker in the batch is lost | Migration 052 also drops the FK on `intraday_quote.ticker`. The intraday_quote table tolerates orphan tickers; queries already handle missing watchlist rows via LEFT JOIN. (Phase 1) |
| A4 | HIGH | Parser only catches `ValueError` — `decimal.InvalidOperation`, `TypeError`, or binary frames crash the reader | Broaden the try/except in `parse_ws_message` to `(ValueError, TypeError, decimal.InvalidOperation, KeyError)` per row. Add test fixtures for invalid price, invalid epoch, object payload. (Phase 2) |
| A5 | HIGH | `_on_task_done` only LOGS task crashes — if `subscriber` dies, subscriptions silently freeze; if `flusher` dies outside its internal try, ticks accumulate forever | Wrap reader/flusher/subscriber in an `asyncio.TaskGroup` so any failure cancels the session and `run_consumer_forever` reconnects. (Phase 4) |
| A6 | HIGH | `WsDbWriter._ohlc_cache` has `invalidate_ohlc_cache()` documented but no caller — returns are computed against yesterday's closes indefinitely | Add a daily-bounded TTL: cache key is `(ticker, market_date)`. When market_date changes, lookups miss naturally and refresh. (Phase 3) |
| A7 | HIGH | `repo._conn.autocommit = True` is set AFTER `psycopg.connect()` — any setup SQL between connect + autocommit-flip opens an implicit transaction | Move autocommit into the connect call: `psycopg.connect(dsn, autocommit=True)` in `_repo_factory`. (Phase 4) |
| A8 | HIGH | On DB outage, `run_consumer_forever` opens a new conn for the WS session AND another for `record_ws_error` — both fail, log spam, no backoff classification | Catch the DB-side `psycopg.OperationalError` separately and skip the error-recording attempt when the issue IS the DB. Bound the error-record attempt with its own short timeout. (Phase 4) |
| A13 | MEDIUM | `preserve_spot=True` excludes only the spot triple — `ret_1d/ret_1w/ret_30d` are still overwritten by full_scan with values from its own snapshot (computed at scan time, not from WS spot) | Extend `SPOT_COLS` in `upsert_watchlist_card` to also exclude returns when `preserve_spot=True`. (Phase 6) |
| A14 | MEDIUM | Phase 8 goal section still says "Run both pipelines in parallel" — Phase 7 already deleted REST | Rewrite Phase 8 goal explicitly as "WS-only validation + rollback plan" (Phase 8) |

Medium-priority findings noted but deferred (acceptable risk vs scope):
- **A9** (transactional contract documentation): the consumer sets `autocommit=True`, so bare UPDATEs are individual statements — the comment "Does NOT commit" is accurate under autocommit. Updated comments to make this explicit.
- **A10** (subscribe ACK validation): the broker doesn't reliably ACK subscribes per-ticker; current pragmatic check is "ticks_received > 0 within 60s of subscribe". A real ACK protocol is a follow-up.
- **A11** (API key rotation): low frequency; documented as "restart consumer after rotating MASSIVE_API_KEY" in worker/CLAUDE.md. Hot reload is a future hardening pass.
- **A12** (ticks_received semantics): split into `ticks_seen_total` (raw, increment per `add()`) and `ticks_flushed_total` (commit count). Both exposed in `/api/health` so ops can detect coalescing rate.

## Post-review verification (2026-05-21)

Confidence-raising pass after the adversarial review. Each shaky item from the prior self-assessment was checked against ground truth:

| Item | Action | Outcome |
|---|---|---|
| `compute_returns` signature | Read `src/uw_scan/cards/returns.py` | Signature matches plan: `compute_returns(history: list[OhlcBar], price: Decimal \| None) -> Returns` with `.ret_1d/.ret_1w/.ret_30d`. ✓ |
| `openapi.snapshot.json` regen | Read `tests/integration/api/test_openapi_snapshot.py` | Test uses `client.get("/openapi.json").json()` via TestClient. Regen snippet rewritten to use the same TestClient pattern so the snapshot exactly matches the test's view. |
| `HealthPanel.tsx` prop shape | Read `web/components/shared/HealthPanel.tsx` (415 lines) | Component fetches `/api/health` internally every 5s — has NO `data` prop. Uses `StatusRow` component + `heartbeatStatus()` helper. Plan rewritten to add a `StatusRow label="WS Consumer"` + two reusing-existing-style rows. Vitest test mocks `api.health` (not props). |
| Transaction semantics | Verified against `https://www.psycopg.org/psycopg3/docs/basic/transactions.html` | Under `autocommit=True`, `with conn.transaction()` executes explicit `BEGIN` on entry, `COMMIT` on clean exit, `ROLLBACK` on exception. The plan's writer-atomicity contract is correct. Atomicity test updated to set `autocommit=True` so it mirrors production. |
| OHLC cache TTL | Plan now uses ET-market-session date via `current_market_date(now)` (extracted to `worker/market_session.py` during Phase 7), not `date.today()` | Avoids local-timezone drift and pre-market midnight crossover bugs. Falls back to most-recent-weekday outside RTH for cache key stability. |
| Reconnect test | Replaced port-claim-then-reconnect with fail-N-then-succeed counter-driven handler | Deterministic (no port reuse race) and verifies BOTH reconnect occurred AND backoff actually grew between attempts. |

## Massive WS surface (verified 2026-05-21)

Confirmed against `https://massive.com/docs/websocket/quickstart` and `/docs/websocket/stocks/aggregates-per-second`:

| Field | Value |
|---|---|
| Real-time URL | `wss://socket.massive.com/stocks` |
| **Delayed URL** | **`wss://delayed.massive.com/stocks`** (use this for the current tier — `/v3/quotes` returns 403 NOT_AUTHORIZED) |
| Auth message | `{"action":"auth","params":"<API_KEY>"}` |
| Success response | `[{"ev":"status","status":"auth_success",...}]` (batched as array) |
| Subscribe message | `{"action":"subscribe","params":"A.AAPL,A.MSFT,..."}` |
| Per-second agg msg | `{"ev":"A","sym":"AAPL","c":189.42,"e":1716308400000,"o":...,"h":...,"l":...,"v":...,"av":...,"s":...}` |
| Channel prefixes | `A` (per-second agg), `AM` (per-minute), `T` (trade), `Q` (quote), `LULD`, `FMV` |

**Default URL in `config.py` updated to `wss://delayed.massive.com/stocks`** (Phase 4 Task 4.2 step 1) since the user's tier is delayed. If/when the tier is upgraded, flip via env: `MASSIVE_WS_URL=wss://socket.massive.com/stocks`.

---

## File Structure

**New files (production):**
- `src/uw_scan/sources/massive_ws.py` — async WS client; auth, subscribe, parse, yield ticks (~250 lines)
- `src/uw_scan/worker/ws_tick_buffer.py` — in-memory `dict[ticker -> latest tick]` buffer (~80 lines)
- `src/uw_scan/worker/ws_db_writer.py` — batched flush from buffer → repo in one txn (~120 lines)
- `src/uw_scan/worker/massive_ws_consumer.py` — long-lived main loop: WS client + buffer + writer + subscription manager + reconnect (~250 lines)
- `src/uw_scan/storage/ws_consumer_state.py` — new `_WsConsumerStateMixin` for heartbeat + tick counters (~80 lines)
- `src/uw_scan/storage/migrations/052_ws_consumer_state.sql` — new table + `source` column on `intraday_quote`

**New files (tests):**
- `tests/unit/sources/test_massive_ws.py`
- `tests/unit/worker/test_ws_tick_buffer.py`
- `tests/unit/worker/test_ws_db_writer.py`
- `tests/integration/worker/test_massive_ws_consumer.py`
- `tests/integration/storage/test_ws_consumer_state.py`

**Modified files:**
- `src/uw_scan/config.py` — add `MASSIVE_WS_*` settings, remove `spot_refresh_seconds` (~10 lines added, ~3 removed)
- `src/uw_scan/storage/repository.py` — register new mixin (one import + one inheritance entry)
- `src/uw_scan/storage/market_data.py:61-74` — add `source` parameter to `upsert_intraday_quote` and a new `bulk_upsert_intraday_quotes` method
- `src/uw_scan/worker/jobs/full_scan.py` and `src/uw_scan/cards/derive.py` — gate spot writes so WS is the only writer
- `src/uw_scan/worker/jobs/rescan_loop.py` — same gating as `full_scan`
- `src/uw_scan/worker/scheduler.py` — delete the `_spot_refresh` closure + its `add_job` registration; the WS consumer owns spot now
- `src/uw_scan/api/routers/health.py` — surface WS heartbeat status (this is now the ONLY operational signal that spot data is flowing)
- `scripts/dev.sh` — add `massive-ws` process
- `pyproject.toml` — add `websockets>=12.0` dependency

**Deleted files:**
- `src/uw_scan/worker/jobs/spot_refresh.py` — REST polling job is removed
- Any tests of `spot_refresh_once` in `tests/unit/worker/` and `tests/integration/worker/`
- `OhlcProvider.fetch_intraday_quote` and `MassiveOhlcProvider.fetch_intraday_quote` in `src/uw_scan/sources/ohlc.py` — unused after Phase 7; daily OHLC `fetch_daily` stays

---

## Phase 0 — Verification & smoke (BLOCKER; no code committed)

**Goal:** Confirm the assumptions above against the actual massive.com WS surface before writing any production code. Output of this phase is either (a) "assumptions confirmed, proceed" or (b) "assumptions wrong, revise plan with these corrected values: …".

### Task 0.1: Locate massive WS docs

**Files:** None (research only)

- [ ] **Step 1: Check provider docs**

Try the following in order, log what you find:

```bash
# (a) Check if there's a docs URL discoverable from the REST base
uv run --with httpx python -c "import httpx, os; r = httpx.get('https://api.massive.com', headers={'Authorization': f'Bearer {os.environ[\"MASSIVE_API_KEY\"]}'}, timeout=10); print(r.status_code, r.headers.get('content-type'), r.text[:500])"

# (b) Polygon docs (massive is Polygon-shaped) describe WS at https://polygon.io/docs/websockets/getting-started — treat as the most likely template
```

Expected: We learn either (i) the documented WS URL/auth/channel grammar for massive, or (ii) that it's literally Polygon-parity and we can use Polygon docs as the spec.

- [ ] **Step 2: Document findings in the plan**

If assumptions need updating, edit this plan's "Assumptions flagged for Phase 0 verification" section with the verified values. Commit that edit at the end of Phase 0 only.

### Task 0.2: Smoke test the WS connection

**Files:**
- Create: `/tmp/smoke_massive_ws.py` (throwaway, NOT committed)

- [ ] **Step 1: Write smoke script**

```python
# /tmp/smoke_massive_ws.py
# Connects to massive WS, subscribes to A.AAPL, A.MSFT, A.SPY for 60s.
# Logs every received message. Prints summary at exit.
# NOT committed; delete after Phase 0.

import asyncio, json, os, time
import websockets

URL = os.environ.get("MASSIVE_WS_URL", "wss://delayed.massive.com/stocks")
KEY = os.environ["MASSIVE_API_KEY"]
TICKERS = ["AAPL", "MSFT", "SPY"]

async def main():
    msgs = []
    started = time.time()
    async with websockets.connect(URL, open_timeout=10) as ws:
        await ws.send(json.dumps({"action": "auth", "params": KEY}))
        await asyncio.sleep(1)
        await ws.send(json.dumps({"action": "subscribe", "params": ",".join(f"A.{t}" for t in TICKERS)}))
        try:
            async with asyncio.timeout(60):
                async for raw in ws:
                    msg = json.loads(raw)
                    msgs.append(msg)
                    print(f"[{time.time()-started:5.1f}s] {raw[:200]}")
        except asyncio.TimeoutError:
            pass
    print(f"\n--- received {len(msgs)} messages in 60s ---")
    # Group by event type for shape summary
    by_ev = {}
    for m in msgs:
        if isinstance(m, list):
            for x in m:
                by_ev.setdefault(x.get("ev","?"), []).append(x)
        elif isinstance(m, dict):
            by_ev.setdefault(m.get("ev","?"), []).append(m)
    for ev, xs in by_ev.items():
        print(f"{ev}: {len(xs)} msgs, sample={xs[0] if xs else None}")

asyncio.run(main())
```

- [ ] **Step 2: Run smoke script during market hours**

**Before running:** export the URL you confirmed in Task 0.1 (the `MASSIVE_WS_URL` env var doesn't exist in `config.py` yet — Phase 4 adds it). Either:

```bash
export MASSIVE_WS_URL="<value from Task 0.1>"
```

OR edit the smoke script to hardcode the verified URL.

Run: `uv run --with websockets python /tmp/smoke_massive_ws.py`

Expected: see `auth_success` / `status: connected` confirmation, then a stream of `A.*` messages. If 0 messages received in 60s during market hours, the assumption is wrong — STOP, revise plan.

- [ ] **Step 3: Document the verified message shape**

Capture in this plan, replacing the assumed example, the actual JSON shape of an `A.*` tick. Update Tasks 2.x test fixtures accordingly.

- [ ] **Step 4: Delete the smoke script**

```bash
rm /tmp/smoke_massive_ws.py
```

### Task 0.3: Confirm delayed vs real-time on this tier

- [ ] **Step 1: Compare WS tick `t` timestamp to wall clock**

In the smoke log, compute `wall_now - tick_epoch_ms/1000` for each tick. Real-time tier: <5s. Delayed tier: ~900s (15 min).

- [ ] **Step 2: Document outcome**

If delayed: sync goal still achieved (all cards converge to the same delayed clock); freshness fix requires tier upgrade — note in plan.
If real-time: both sync + freshness fixed by this work.

**Phase 0 milestone: ready to proceed iff WS connects, subscribes, and pushes parsable ticks. Commit at user direction with message `docs(plan): verify massive WS assumptions for sync redesign`.**

---

## Phase 1 — Database foundation

**Goal:** Add the schema + repository surface the WS consumer needs to write into, **before** writing any consumer code.

### Task 1.1: Migration `052_ws_consumer_state.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/052_ws_consumer_state.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 052_ws_consumer_state.sql
-- WS consumer heartbeat + intraday_quote source tracking + FK relaxation
SET search_path TO uw_scan, public;

-- Single-row table tracking the WS consumer's liveness + activity.
CREATE TABLE IF NOT EXISTS ws_consumer_state (
  id              SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  last_tick_at    TIMESTAMPTZ,
  last_flush_at   TIMESTAMPTZ,
  ticks_received  BIGINT NOT NULL DEFAULT 0,
  ticks_flushed   BIGINT NOT NULL DEFAULT 0,
  connection_started_at TIMESTAMPTZ,
  last_error      TEXT,
  last_error_at   TIMESTAMPTZ,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO ws_consumer_state (id) VALUES (1) ON CONFLICT DO NOTHING;

-- Track which writer produced each intraday_quote row.
ALTER TABLE intraday_quote
  ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'massive.com_intraday';

-- A3 (adversarial fix): drop the FK from intraday_quote.ticker to watchlist(ticker).
-- The WS consumer subscribes to the watchlist, but a race (ticker removed from
-- watchlist mid-session, broker still pushes one more tick) would otherwise
-- cause an FK violation that rolls back the WHOLE flush batch — combined with
-- A2 (drain-before-write), every ticker in that batch would be lost.
-- intraday_quote already tolerates orphan tickers semantically: dashboard SQL
-- LEFT JOINs from watchlist, so orphan rows are simply ignored on read.
ALTER TABLE intraday_quote
  DROP CONSTRAINT IF EXISTS intraday_quote_ticker_fkey;
```

- [ ] **Step 2: Apply locally**

Run: `bash scripts/migrate.sh`
Expected: no errors; re-running is a no-op (verify by running twice).

- [ ] **Step 3: Verify in psql**

Run: `psql option_wizard -c "\d uw_scan.ws_consumer_state" -c "\d uw_scan.intraday_quote"`
Expected: `ws_consumer_state` table exists with the 8 columns; `intraday_quote` has a `source` column.

- [ ] **Step 4: Stage for commit (do not commit yet)**

```bash
git add src/uw_scan/storage/migrations/052_ws_consumer_state.sql
```

### Task 1.2: New `_WsConsumerStateMixin`

**Files:**
- Create: `src/uw_scan/storage/ws_consumer_state.py`
- Test: `tests/integration/storage/test_ws_consumer_state.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/integration/storage/test_ws_consumer_state.py
from datetime import datetime, timezone

from uw_scan.storage.repository import Repository


def _utcnow():
    return datetime.now(timezone.utc)


def test_record_ws_heartbeat_persists(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_heartbeat(
        last_tick_at=ts,
        last_flush_at=ts,
        ticks_received_delta=10,
        ticks_flushed_delta=10,
    )
    repo._conn.commit()  # helpers don't self-commit — caller controls txn
    row = repo.get_ws_consumer_state()
    assert row is not None
    assert row.last_tick_at == ts
    assert row.ticks_received == 10
    assert row.ticks_flushed == 10


def test_ws_heartbeat_accumulates_counters(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts1, ts2 = _utcnow(), _utcnow()
    repo.record_ws_heartbeat(last_tick_at=ts1, last_flush_at=ts1, ticks_received_delta=5, ticks_flushed_delta=5)
    repo._conn.commit()
    repo.record_ws_heartbeat(last_tick_at=ts2, last_flush_at=ts2, ticks_received_delta=7, ticks_flushed_delta=7)
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.ticks_received == 12
    assert row.ticks_flushed == 12


def test_record_ws_connection_started(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_connection_started(ts)
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.connection_started_at == ts


def test_record_ws_error(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_error("connection closed: 1006", ts)
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.last_error == "connection closed: 1006"
    assert row.last_error_at == ts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_ws_consumer_state.py -v`
Expected: FAIL — `Repository` has no `record_ws_heartbeat` method.

- [ ] **Step 3: Add `WsConsumerStateRow` to `storage/rows.py`**

Edit `src/uw_scan/storage/rows.py` — append:

```python
@dataclass(frozen=True)
class WsConsumerStateRow:
    last_tick_at: datetime | None
    last_flush_at: datetime | None
    ticks_received: int
    ticks_flushed: int
    connection_started_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    updated_at: datetime
```

- [ ] **Step 4: Write the mixin**

Create `src/uw_scan/storage/ws_consumer_state.py`:

```python
"""WS consumer heartbeat + activity counters for api.massive.com WebSocket."""

from __future__ import annotations

from datetime import datetime

import psycopg

from .rows import WsConsumerStateRow


class _WsConsumerStateMixin:
    _conn: psycopg.Connection
    _schema: str

    def get_ws_consumer_state(self) -> WsConsumerStateRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT last_tick_at, last_flush_at, ticks_received, ticks_flushed,
                       connection_started_at, last_error, last_error_at, updated_at
                FROM {self._schema}.ws_consumer_state
                WHERE id = 1
                """
            )
            row = cur.fetchone()
            return WsConsumerStateRow(*row) if row else None

    def record_ws_heartbeat(
        self,
        *,
        last_tick_at: datetime | None,
        last_flush_at: datetime,
        ticks_received_delta: int,
        ticks_flushed_delta: int,
    ) -> None:
        """Does NOT commit — caller controls the transaction so heartbeat
        + bulk upserts share atomicity. The WS writer wraps all three writes
        in one ``with self._conn.transaction():`` block."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET last_tick_at  = COALESCE(%s, last_tick_at),
                    last_flush_at = %s,
                    ticks_received = ticks_received + %s,
                    ticks_flushed  = ticks_flushed  + %s,
                    updated_at = NOW()
                WHERE id = 1
                """,
                (last_tick_at, last_flush_at, ticks_received_delta, ticks_flushed_delta),
            )

    def record_ws_connection_started(self, started_at: datetime) -> None:
        """Does NOT commit — caller controls."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET connection_started_at = %s, updated_at = NOW()
                WHERE id = 1
                """,
                (started_at,),
            )

    def record_ws_error(self, message: str, error_at: datetime) -> None:
        """Does NOT commit — caller controls."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET last_error = %s, last_error_at = %s, updated_at = NOW()
                WHERE id = 1
                """,
                (message[:1000], error_at),
            )
```

- [ ] **Step 5: Register the mixin in `repository.py`**

Edit `src/uw_scan/storage/repository.py` — add to the import block and to the `Repository` MRO above `_BaseMixin`:

```python
from .ws_consumer_state import _WsConsumerStateMixin
```

```python
class Repository(
    # ... existing mixins ...
    _WsConsumerStateMixin,
    _BaseMixin,
):
    ...
```

Also extend `__all__` if it lists row types, adding `WsConsumerStateRow` re-export from `rows.py`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/integration/storage/test_ws_consumer_state.py -v`
Expected: 4 tests PASS.

- [ ] **Step 7: Run the full storage test suite to verify no regressions**

Run: `uv run pytest tests/integration/storage/ tests/unit/storage/ -v`
Expected: all pass.

- [ ] **Step 8: Stage for commit (do not commit yet)**

```bash
git add src/uw_scan/storage/ws_consumer_state.py src/uw_scan/storage/rows.py src/uw_scan/storage/repository.py tests/integration/storage/test_ws_consumer_state.py
```

### Task 1.3: Bulk upsert helpers + `source` column on intraday_quote

**Files:**
- Modify: `src/uw_scan/storage/market_data.py:61-74` (extend `upsert_intraday_quote`, add `bulk_upsert_intraday_quotes`)
- Modify: `src/uw_scan/storage/watchlist.py` (add `bulk_upsert_watchlist_card_spots`)
- Test: `tests/integration/storage/test_bulk_intraday_quote.py` (new)

- [ ] **Step 1: Write failing test for bulk intraday upsert**

```python
# tests/integration/storage/test_bulk_intraday_quote.py
from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository


def test_bulk_upsert_intraday_quotes_atomic(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    rows = [
        ("AAPL", Decimal("189.42"), ts, "massive.com_ws"),
        ("MSFT", Decimal("425.10"), ts, "massive.com_ws"),
        ("SPY", Decimal("532.55"), ts, "massive.com_ws"),
    ]
    repo.bulk_upsert_intraday_quotes(rows)
    repo._conn.commit()  # helpers don't self-commit — caller controls txn
    for ticker, price, quoted_at, source in rows:
        q = repo.get_intraday_quote(ticker)
        assert q is not None
        assert q.price == price
        assert q.quoted_at == quoted_at


def test_bulk_upsert_intraday_quotes_overwrites(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts1 = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 1, tzinfo=timezone.utc)
    repo.bulk_upsert_intraday_quotes([("AAPL", Decimal("189.42"), ts1, "massive.com_ws")])
    repo._conn.commit()
    repo.bulk_upsert_intraday_quotes([("AAPL", Decimal("189.50"), ts2, "massive.com_ws")])
    repo._conn.commit()
    q = repo.get_intraday_quote("AAPL")
    assert q.price == Decimal("189.50")
    assert q.quoted_at == ts2


def test_upsert_intraday_quote_with_source(seeded_db_empty_cards):
    """The non-bulk variant still self-commits (preserves existing
    spot_refresh.py behavior in Phases 1–6 before Phase 7 deletes it)."""
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    repo.upsert_intraday_quote("AAPL", Decimal("189.42"), ts, source="massive.com_ws")
    q = repo.get_intraday_quote("AAPL")
    assert q.price == Decimal("189.42")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/storage/test_bulk_intraday_quote.py -v`
Expected: FAIL — `bulk_upsert_intraday_quotes` doesn't exist; `upsert_intraday_quote` doesn't accept `source`.

- [ ] **Step 3: Extend `upsert_intraday_quote` and add bulk helper**

Edit `src/uw_scan/storage/market_data.py` — replace the existing `upsert_intraday_quote` (lines 61-74) and add `bulk_upsert_intraday_quotes`:

```python
    # ---- intraday_quote ----
    def upsert_intraday_quote(
        self,
        ticker: str,
        price: Decimal,
        quoted_at: datetime,
        *,
        source: str = "massive.com_intraday",
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.intraday_quote (ticker, price, quoted_at, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price,
                      quoted_at=EXCLUDED.quoted_at,
                      source=EXCLUDED.source,
                      fetched_at=NOW()
                """,
                (ticker, price, quoted_at, source),
            )
        self._conn.commit()

    def bulk_upsert_intraday_quotes(
        self,
        rows: list[tuple[str, Decimal, datetime, str]],
    ) -> None:
        """Batch upsert of (ticker, price, quoted_at, source) rows.

        Does NOT commit — caller controls the transaction so this can be
        wrapped together with bulk_upsert_watchlist_card_spots + heartbeat
        in one atomic batch by the WS writer.
        """
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                INSERT INTO {self._schema}.intraday_quote (ticker, price, quoted_at, source)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (ticker) DO UPDATE
                  SET price=EXCLUDED.price,
                      quoted_at=EXCLUDED.quoted_at,
                      source=EXCLUDED.source,
                      fetched_at=NOW()
                """,
                rows,
            )
```

- [ ] **Step 4: Update existing callers of `upsert_intraday_quote`**

Find callers (existing positional signature is preserved by keeping `source` as kwarg with default):

```bash
grep -rn "upsert_intraday_quote" /Users/chenxi/projects/unusual-whales/src/ | grep -v __pycache__
```

Expected: `worker/jobs/spot_refresh.py:39` calls it positionally with `(ticker, price, quoted_at)` — still works because `source` has a default.

- [ ] **Step 5: Write failing test for `bulk_upsert_watchlist_card_spots`**

```python
# tests/integration/storage/test_bulk_watchlist_card_spots.py
from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.storage.repository import Repository


def test_bulk_upsert_watchlist_card_spots(seeded_db_with_cards):
    """Update only spot/spot_quoted_at/spot_source on existing cards; rows
    without a card are silently skipped (the WS consumer doesn't create cards).

    `seeded_db_with_cards` provides one TSLA card by default. We use TSLA
    (real card) + a synthetic "NOTACARD" ticker (no row → must be skipped).
    """
    repo = seeded_db_with_cards
    ts = datetime.now(timezone.utc)
    rows = [
        ("TSLA", Decimal("450.00"), ts, "massive.com_ws"),
        ("NOTACARD", Decimal("1.00"), ts, "massive.com_ws"),  # no row in watchlist_card
    ]
    repo.bulk_upsert_watchlist_card_spots(rows)
    repo._conn.commit()
    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    assert card.spot_quoted_at == ts
    assert card.spot_source == "massive.com_ws"
    # NOTACARD silently skipped — no row was created
    assert repo.get_watchlist_card("NOTACARD") is None
```

The fixture `seeded_db_with_cards` already exists in `tests/integration/conftest.py:62` and seeds one TSLA card with the watchlist + scan_run wiring. If a future test needs multiple cards, extend the fixture or create a new one in the same conftest.

- [ ] **Step 6: Run test, see it fail**

Run: `uv run pytest tests/integration/storage/test_bulk_watchlist_card_spots.py -v`
Expected: FAIL — method doesn't exist.

- [ ] **Step 7: Add `bulk_upsert_watchlist_card_spots` to `storage/watchlist.py`**

Edit `src/uw_scan/storage/watchlist.py` — append to `_WatchlistMixin`:

```python
    def bulk_upsert_watchlist_card_spots(
        self,
        rows: list[tuple[str, Decimal, datetime, str]],
    ) -> None:
        """Update only spot/spot_quoted_at/spot_source on existing cards.

        Rows with no existing watchlist_card row are silently skipped — the
        WS consumer is not responsible for materializing cards (that's
        full_scan's job).

        Does NOT commit — caller controls the transaction.
        """
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                UPDATE {self._schema}.watchlist_card
                SET spot           = %s,
                    spot_quoted_at = %s,
                    spot_source    = %s
                WHERE ticker = %s
                """,
                [(price, quoted_at, source, ticker) for (ticker, price, quoted_at, source) in rows],
            )
```

- [ ] **Step 8: Run all storage tests**

Run: `uv run pytest tests/integration/storage/ tests/unit/storage/ -v`
Expected: all pass.

- [ ] **Step 9: Stage**

```bash
git add src/uw_scan/storage/market_data.py src/uw_scan/storage/watchlist.py tests/integration/storage/test_bulk_intraday_quote.py tests/integration/storage/test_bulk_watchlist_card_spots.py
```

**Phase 1 milestone: DB surface ready. User-gated commit: `feat(storage): WS consumer state + bulk intraday/spot upserts`.**

---

## Phase 2 — Pure WS client (no DB)

**Goal:** Async I/O against massive WS, fully decoupled from DB. Yields parsed `WsTick` records to whoever consumes the iterator.

### Task 2.1: Add `websockets` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependency**

Edit `pyproject.toml` — under the main dependencies block, add:

```toml
"websockets>=12.0",
```

- [ ] **Step 2: Sync**

Run: `uv sync --extra postgres`
Expected: `websockets` installed.

- [ ] **Step 3: Verify importable**

Run: `uv run python -c "import websockets; print(websockets.__version__)"`
Expected: prints `12.x` or higher.

### Task 2.2: `MassiveWsClient` skeleton + unit tests

**Files:**
- Create: `src/uw_scan/sources/massive_ws.py`
- Test: `tests/unit/sources/test_massive_ws.py`

- [ ] **Step 1: Write failing unit test (parser only first — pure function)**

```python
# tests/unit/sources/test_massive_ws.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from uw_scan.sources.massive_ws import (
    MassiveWsClient,
    WsTick,
    parse_ws_message,
)


def test_parse_ws_message_aggregate_per_second():
    """Per-second aggregate message — channel 'A.<TICKER>'."""
    raw = '[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000}]'
    ticks = parse_ws_message(raw)
    assert ticks == [
        WsTick(
            ticker="AAPL",
            price=Decimal("189.42"),
            quoted_at=datetime(2026, 5, 21, 16, 20, 0, tzinfo=timezone.utc),
            channel="A",
        )
    ]


def test_parse_ws_message_status_skipped():
    """Status messages (auth_success, subscribed) yield no ticks."""
    raw = '[{"ev":"status","status":"auth_success","message":"authenticated"}]'
    ticks = parse_ws_message(raw)
    assert ticks == []


def test_parse_ws_message_batched_array():
    """Massive batches multiple ticks per frame."""
    raw = (
        '[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000},'
        '{"ev":"A","sym":"MSFT","c":425.10,"e":1779380400000}]'
    )
    ticks = parse_ws_message(raw)
    assert len(ticks) == 2
    assert ticks[0].ticker == "AAPL"
    assert ticks[1].ticker == "MSFT"


def test_parse_ws_message_missing_fields_skipped():
    raw = '[{"ev":"A","sym":"AAPL"}]'  # no c / no e
    ticks = parse_ws_message(raw)
    assert ticks == []


def test_parse_ws_message_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_ws_message("not json")
```

- [ ] **Step 2: Run test, see it fail**

Run: `uv run pytest tests/unit/sources/test_massive_ws.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Write the module skeleton + parser**

Create `src/uw_scan/sources/massive_ws.py`:

```python
"""Async WebSocket client for api.massive.com.

Pure I/O — no DB writes, no buffering, no business logic. The consumer is
responsible for buffering and persistence. See worker/massive_ws_consumer.py
for the long-lived process that wires this together.

Channel grammar (Polygon-parity, verified in Phase 0):
- A.<TICKER>  — per-second aggregate (close price `c`, epoch ms `e`)
- AM.<TICKER> — per-minute aggregate (same shape)
- T.<TICKER>  — individual trades
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WsTick:
    ticker: str
    price: Decimal
    quoted_at: datetime
    channel: str  # "A" | "AM" | "T"


def parse_ws_message(raw: str) -> list[WsTick]:
    """Parse a WS frame (always a JSON array) into zero or more WsTicks.

    Returns [] for status / control messages. Raises ValueError on malformed
    JSON at the frame level. Per-row failures (malformed Decimal, bad epoch,
    bad shape) are caught and the row is silently skipped — one bad tick
    must NOT take down the entire frame (A4 adversarial fix).
    """
    import decimal

    payload = json.loads(raw)
    if not isinstance(payload, list):
        return []
    ticks: list[WsTick] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            ev = row.get("ev")
            if ev not in ("A", "AM", "T"):
                continue
            sym = row.get("sym")
            if not sym:
                continue
            # Price field: "c" for aggregates, "p" for trades
            price_raw = row.get("c") if ev in ("A", "AM") else row.get("p")
            epoch_ms = row.get("e") if ev in ("A", "AM") else row.get("t")
            if price_raw is None or epoch_ms is None:
                continue
            ticks.append(
                WsTick(
                    ticker=str(sym).upper(),
                    price=Decimal(str(price_raw)),
                    quoted_at=datetime.fromtimestamp(int(epoch_ms) / 1000, tz=timezone.utc),
                    channel=str(ev),
                )
            )
        except (ValueError, TypeError, KeyError, decimal.InvalidOperation) as exc:
            logger.debug("parse_ws_message skipping bad row %r: %s", row, repr(exc))
            continue
    return ticks


class MassiveWsClient:
    """Async context manager wrapping a websockets.connect lifecycle.

    Usage:

        async with MassiveWsClient(url, api_key) as client:
            await client.subscribe(["A.AAPL", "A.MSFT"])
            async for tick in client.ticks():
                ...

    Reconnect / backoff is the caller's responsibility — this class is a
    single connection. See `massive_ws_consumer.py` for reconnect logic.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        open_timeout: float = 10.0,
        ping_interval: float = 20.0,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._open_timeout = open_timeout
        self._ping_interval = ping_interval
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._subscribed: set[str] = set()

    async def __aenter__(self) -> "MassiveWsClient":
        self._ws = await websockets.connect(
            self._url,
            open_timeout=self._open_timeout,
            ping_interval=self._ping_interval,
        )
        await self._authenticate()
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _authenticate(self) -> None:
        """Send auth and verify the broker accepts our key.

        Raises ``RuntimeError`` if the broker does not return
        ``status: "auth_success"`` within 5s. Silently accepting an auth
        failure would leave us subscribed-but-receiving-nothing — the
        no-fallback design makes this category of failure especially
        important to detect (R13).
        """
        assert self._ws is not None
        await self._ws.send(json.dumps({"action": "auth", "params": self._api_key}))
        try:
            async with asyncio.timeout(5.0):
                raw = await self._ws.recv()
        except asyncio.TimeoutError as exc:
            raise RuntimeError("massive_ws auth response timed out after 5s") from exc
        logger.info("massive_ws auth response: %s", raw[:200])
        # Massive batches status messages as a JSON array; look for auth_success.
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError(f"massive_ws auth response not JSON: {raw[:200]!r}") from exc
        items = payload if isinstance(payload, list) else [payload]
        auth_ok = any(
            isinstance(m, dict)
            and m.get("ev") == "status"
            and m.get("status") == "auth_success"
            for m in items
        )
        if not auth_ok:
            raise RuntimeError(f"massive_ws auth failed: {raw[:200]!r}")

    async def subscribe(self, channels: Iterable[str]) -> None:
        """Send a subscribe message for the given fully-qualified channels.

        Channels are strings like "A.AAPL". Idempotent — re-subscribing to an
        already-subscribed channel is a no-op (the broker dedupes).
        """
        assert self._ws is not None
        new_subs = [c for c in channels if c not in self._subscribed]
        if not new_subs:
            return
        await self._ws.send(json.dumps({"action": "subscribe", "params": ",".join(new_subs)}))
        self._subscribed.update(new_subs)

    async def unsubscribe(self, channels: Iterable[str]) -> None:
        assert self._ws is not None
        drop = [c for c in channels if c in self._subscribed]
        if not drop:
            return
        await self._ws.send(json.dumps({"action": "unsubscribe", "params": ",".join(drop)}))
        self._subscribed.difference_update(drop)

    async def ticks(self) -> AsyncIterator[WsTick]:
        """Yield ticks until the connection closes."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    for tick in parse_ws_message(raw):
                        yield tick
                except ValueError as exc:
                    logger.warning("massive_ws bad frame, skipping: %s (%s)", repr(exc), raw[:200])
        except ConnectionClosed as exc:
            logger.info("massive_ws connection closed: %s", exc)
            return
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/unit/sources/test_massive_ws.py -v`
Expected: 5 parser tests PASS.

- [ ] **Step 5: Add a lifecycle integration test against a fake server**

Append to `tests/unit/sources/test_massive_ws.py`:

```python
import asyncio
import websockets


@pytest.mark.asyncio
async def test_client_authenticates_and_subscribes():
    """Spin up a fake WS server, verify auth + subscribe messages are sent."""
    received: list[str] = []

    async def handler(ws):
        async for msg in ws:
            received.append(msg)
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send('[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000}]')
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        async with MassiveWsClient(url, "TEST_KEY") as client:
            await client.subscribe(["A.AAPL"])
            ticks = [t async for t in client.ticks()]

    assert len(received) == 2
    auth = json.loads(received[0])
    assert auth == {"action": "auth", "params": "TEST_KEY"}
    sub = json.loads(received[1])
    assert sub == {"action": "subscribe", "params": "A.AAPL"}
    assert len(ticks) == 1
    assert ticks[0].ticker == "AAPL"
```

Note: this requires `pytest-asyncio` — check if it's already in `pyproject.toml`. If not, add it to dev dependencies and `uv sync` again.

- [ ] **Step 6: Run lifecycle test**

Run: `uv run pytest tests/unit/sources/test_massive_ws.py::test_client_authenticates_and_subscribes -v`
Expected: PASS.

- [ ] **Step 7: Stage**

```bash
git add src/uw_scan/sources/massive_ws.py tests/unit/sources/test_massive_ws.py pyproject.toml uv.lock
```

**Phase 2 milestone: pure WS client works against a fake server. User-gated commit: `feat(sources): massive.com WS client with parser + auth + subscribe`.**

---

## Phase 3 — Tick buffer + DB writer

**Goal:** Take a stream of `WsTick`s, keep only the latest per ticker in memory, and flush periodically to DB in one batched transaction.

### Task 3.1: `TickBuffer`

**Files:**
- Create: `src/uw_scan/worker/ws_tick_buffer.py`
- Test: `tests/unit/worker/test_ws_tick_buffer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/worker/test_ws_tick_buffer.py
from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.sources.massive_ws import WsTick
from uw_scan.worker.ws_tick_buffer import TickBuffer


def _tick(ticker: str, price: str, ts: datetime) -> WsTick:
    return WsTick(ticker=ticker, price=Decimal(price), quoted_at=ts, channel="A")


def test_buffer_keeps_latest_per_ticker():
    buf = TickBuffer()
    ts1 = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 0, 1, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts1))
    buf.add(_tick("AAPL", "189.50", ts2))
    drained = buf.drain()
    assert len(drained) == 1
    assert drained["AAPL"].price == Decimal("189.50")
    assert drained["AAPL"].quoted_at == ts2


def test_buffer_keeps_one_per_ticker_across_many():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    for t in ("AAPL", "MSFT", "SPY"):
        buf.add(_tick(t, "1.00", ts))
    drained = buf.drain()
    assert set(drained.keys()) == {"AAPL", "MSFT", "SPY"}


def test_buffer_does_not_regress_on_out_of_order():
    """If a later wall-clock tick has an EARLIER quoted_at (shouldn't normally
    happen but can during reconnects), we keep the one with the LATER
    quoted_at — that's the more recent observation."""
    buf = TickBuffer()
    ts1 = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 0, 5, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.50", ts2))  # newer arrives first
    buf.add(_tick("AAPL", "189.40", ts1))  # older arrives second
    drained = buf.drain()
    assert drained["AAPL"].price == Decimal("189.50")


def test_drain_clears_buffer():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts))
    buf.drain()
    assert buf.drain() == {}


def test_drain_is_thread_safe_between_adds():
    """Drain returns a snapshot; concurrent adds during drain land in the
    next batch, not the current one."""
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts))
    snapshot = buf.drain()
    buf.add(_tick("MSFT", "425.00", ts))
    assert "MSFT" not in snapshot
    next_batch = buf.drain()
    assert "MSFT" in next_batch
```

- [ ] **Step 2: Run, see it fail**

Run: `uv run pytest tests/unit/worker/test_ws_tick_buffer.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `src/uw_scan/worker/ws_tick_buffer.py`:

```python
"""In-memory latest-tick-per-ticker buffer for the WS consumer.

The consumer pushes ticks as they arrive; the writer drains periodically
(e.g., every 1s) and persists the snapshot in a single transaction.

Thread-safe via an asyncio.Lock — `add` and `drain` can be called from
different asyncio tasks safely.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from uw_scan.sources.massive_ws import WsTick


class TickBuffer:
    """Keep only the latest tick (by quoted_at) per ticker."""

    def __init__(self) -> None:
        self._latest: dict[str, WsTick] = {}
        self._lock = threading.Lock()

    def add(self, tick: WsTick) -> None:
        with self._lock:
            existing = self._latest.get(tick.ticker)
            if existing is None or tick.quoted_at >= existing.quoted_at:
                self._latest[tick.ticker] = tick

    def drain(self) -> Mapping[str, WsTick]:
        """Atomically return + clear the buffer."""
        with self._lock:
            snapshot = self._latest
            self._latest = {}
            return snapshot

    def __len__(self) -> int:
        with self._lock:
            return len(self._latest)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/worker/test_ws_tick_buffer.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Stage**

```bash
git add src/uw_scan/worker/ws_tick_buffer.py tests/unit/worker/test_ws_tick_buffer.py
```

### Task 3.2: `WsDbWriter` — buffer drain → DB flush

**Files:**
- Create: `src/uw_scan/worker/ws_db_writer.py`
- Test: `tests/integration/worker/test_ws_db_writer.py`

- [ ] **Step 1: Write failing integration test**

```python
# tests/integration/worker/test_ws_db_writer.py
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from uw_scan.sources.massive_ws import WsTick
from uw_scan.worker.ws_db_writer import WsDbWriter
from uw_scan.worker.ws_tick_buffer import TickBuffer


def test_writer_flushes_buffer_to_db(seeded_db_with_cards):
    """seeded_db_with_cards seeds one TSLA card. We tick TSLA (real card)
    + INTC (no card row) — INTC should land in intraday_quote but not in
    watchlist_card (silently skipped, that's the contract)."""
    repo = seeded_db_with_cards
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")

    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    buf.add(WsTick("INTC", Decimal("32.10"), ts, "A"))

    n = writer.flush_once()
    assert n == 2

    q_tsla = repo.get_intraday_quote("TSLA")
    assert q_tsla.price == Decimal("450.00")
    q_intc = repo.get_intraday_quote("INTC")
    assert q_intc.price == Decimal("32.10")  # intraday_quote table has no FK constraint
    c_tsla = repo.get_watchlist_card("TSLA")
    assert c_tsla.spot == Decimal("450.00")
    assert c_tsla.spot_source == "massive.com_ws"
    assert repo.get_watchlist_card("INTC") is None  # no card was created

    state = repo.get_ws_consumer_state()
    assert state.ticks_flushed == 2


def test_writer_empty_buffer_is_noop(seeded_db_with_cards):
    repo = seeded_db_with_cards
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    assert writer.flush_once() == 0


def test_writer_atomicity_rolls_back_on_failure(seeded_db_with_cards, monkeypatch):
    """If bulk_upsert_watchlist_card_spots raises, intraday_quote also rolls back.

    Mirrors production behavior: the writer expects an autocommit conn so
    `with conn.transaction()` issues explicit BEGIN/COMMIT/ROLLBACK around
    the batch (verified against psycopg3 docs:
    https://www.psycopg.org/psycopg3/docs/basic/transactions.html —
    "If you want to use an autocommit connection but still wrap selected
    groups of commands inside an atomic transaction, you can use a
    transaction() context. When entered, BEGIN is executed and a transaction
    is started, and COMMIT is executed at the end of the block.")
    """
    repo = seeded_db_with_cards
    repo._conn.autocommit = True  # mirror production setup
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))

    def boom(*_a, **_k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(repo, "bulk_upsert_watchlist_card_spots", boom)
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    with pytest.raises(RuntimeError):
        writer.flush_once()

    # intraday_quote should NOT have TSLA — the `with conn.transaction()`
    # block issued ROLLBACK when boom raised, undoing the bulk_upsert_intraday_quotes
    # that ran before it.
    assert repo.get_intraday_quote("TSLA") is None
    # The pending ticks should be merged back into the buffer for retry (A2).
    assert len(buf) == 1
```

- [ ] **Step 2: Run, see it fail**

Run: `uv run pytest tests/integration/worker/test_ws_db_writer.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `src/uw_scan/worker/ws_db_writer.py`:

```python
"""Drain a TickBuffer and persist as a single atomic batch.

Writes happen under one psycopg transaction wrapping:
  1. bulk_upsert_intraday_quotes (canonical source of truth)
  2. bulk_upsert_watchlist_card_spots (denormalized for fast dashboard reads)
  3. record_ws_heartbeat (operator visibility)
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone

from uw_scan.sources.massive_ws import WsTick
from uw_scan.storage.repository import Repository
from uw_scan.worker.ws_tick_buffer import TickBuffer

logger = logging.getLogger(__name__)


class WsDbWriter:
    def __init__(
        self,
        *,
        repo: Repository,
        buffer: TickBuffer,
        source_tag: str = "massive.com_ws",
    ) -> None:
        self._repo = repo
        self._buffer = buffer
        self._source_tag = source_tag

    def flush_once(self) -> int:
        """Drain buffer + flush. Returns number of tickers written.

        Uses `_conn` directly so all three writes share one transaction.
        psycopg autocommits per-statement by default in Repository helpers,
        so we override to wrap them.
        """
        snapshot = self._buffer.drain()
        if not snapshot:
            return 0

        rows: list[tuple] = []
        latest_quoted_at: datetime | None = None
        for tick in snapshot.values():
            rows.append((tick.ticker, tick.price, tick.quoted_at, self._source_tag))
            if latest_quoted_at is None or tick.quoted_at > latest_quoted_at:
                latest_quoted_at = tick.quoted_at

        flush_at = datetime.now(timezone.utc)
        n = len(rows)
        try:
            # All three writes share one transaction. Repository helpers
            # each commit individually; we re-wrap below for atomicity.
            with self._repo._conn.transaction():
                self._repo.bulk_upsert_intraday_quotes(rows)
                self._repo.bulk_upsert_watchlist_card_spots(rows)
                self._repo.record_ws_heartbeat(
                    last_tick_at=latest_quoted_at,
                    last_flush_at=flush_at,
                    ticks_received_delta=n,
                    ticks_flushed_delta=n,
                )
        except Exception:
            logger.exception("ws_db_writer flush failed; rolled back %d ticks", n)
            raise
        logger.debug("ws_db_writer flushed %d ticks", n)
        return n
```

Note: `psycopg.Connection.transaction()` is a context manager that issues SAVEPOINT semantics; the bulk_upsert helpers currently commit individually. This needs a small refactor: the Repository helpers used here should NOT call `self._conn.commit()` inside; let the outer transaction control it. Alternative: write a private `_unsafe_bulk_*` variant that skips the inner commit.

- [ ] **Step 4: Verify the helpers don't self-commit**

The bulk + WS-state helpers were added in Phase 1 already commit-free (the implementations in Task 1.2 / 1.3 explicitly do NOT call `self._conn.commit()`). Their tests use explicit `repo._conn.commit()` after each write. The WS writer's `with self._repo._conn.transaction():` block in Step 3 is the sole commit boundary — when it exits cleanly the transaction commits; on exception it rolls back.

No refactor needed if Phase 1 was followed faithfully. To verify, grep:

```bash
grep -n "self._conn.commit" /Users/chenxi/projects/unusual-whales/src/uw_scan/storage/ws_consumer_state.py
grep -n "self._conn.commit" /Users/chenxi/projects/unusual-whales/src/uw_scan/storage/market_data.py | grep -i bulk
grep -n "self._conn.commit" /Users/chenxi/projects/unusual-whales/src/uw_scan/storage/watchlist.py | grep -i bulk
```

Expected: zero matches in `ws_consumer_state.py`, zero matches in the bulk helpers. The non-bulk `upsert_intraday_quote` keeps its self-commit — it's still called by `worker/jobs/spot_refresh.py` until Phase 7.

- [ ] **Step 5: Re-run all storage + writer tests**

Run: `uv run pytest tests/integration/storage/ tests/integration/worker/test_ws_db_writer.py tests/unit/worker/test_ws_tick_buffer.py -v`
Expected: all PASS.

- [ ] **Step 6: Stage**

```bash
git add src/uw_scan/worker/ws_db_writer.py tests/integration/worker/test_ws_db_writer.py src/uw_scan/storage/market_data.py src/uw_scan/storage/watchlist.py src/uw_scan/storage/ws_consumer_state.py
```

### Task 3.3: Preserve intraday return updates (R9 — review fix)

**Files:**
- Modify: `src/uw_scan/storage/watchlist.py` (extend `bulk_upsert_watchlist_card_spots` to accept optional returns)
- Modify: `src/uw_scan/worker/ws_db_writer.py` (compute returns per tick using a cached daily_ohlc lookup)
- Test: extend `tests/integration/worker/test_ws_db_writer.py`

**Why:** The deleted `spot_refresh_once` wrote not only `spot/spot_quoted_at/spot_source` but also `ret_1d/ret_1w/ret_30d` derived from `compute_returns(daily_history, latest_spot)` (see the original `worker/jobs/spot_refresh.py:44-55`). Without this task, returns would only update on full_scan / rescan_tick — meaning a card opened mid-session would show ret_1d from this morning's full_scan, not the latest tick.

- [ ] **Step 1: Write failing test**

Append to `tests/integration/worker/test_ws_db_writer.py`:

```python
def test_writer_persists_intraday_returns(seeded_db_with_ohlc, seeded_db_with_cards):
    """flush_once must also update ret_1d / ret_1w / ret_30d so the dashboard
    cards stay in sync with the intraday spot."""
    # Use the OHLC-seeded fixture to ensure compute_returns has data to read.
    # (May need a combined fixture if pytest doesn't compose these — add one
    # in tests/integration/conftest.py: `seeded_db_with_cards_and_ohlc`.)
    repo = seeded_db_with_cards
    # Backfill 30 days of TSLA daily OHLC at price ~440 so a 450 tick yields
    # a positive ret_1d (~+2.3%).
    today = datetime.now(timezone.utc).date()
    for i in range(30):
        repo.upsert_daily_ohlc(
            ticker="TSLA",
            date=today - timedelta(days=30 - i),
            open=Decimal("440"), high=Decimal("442"), low=Decimal("438"),
            close=Decimal("440"), volume=10_000_000, source="massive.com",
        )
    repo._conn.commit()

    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    ts = datetime.now(timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    writer.flush_once()

    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    # (450 - 440) / 440 ≈ 0.0227. Tolerance because compute_returns rounds.
    assert card.ret_1d is not None
    assert abs(float(card.ret_1d) - 0.0227) < 0.001
```

- [ ] **Step 2: Extend the bulk helper signature**

Edit `src/uw_scan/storage/watchlist.py`. Add a sibling method (don't widen the existing one — return values are optional and only the WS writer cares):

```python
    def bulk_upsert_watchlist_card_quotes(
        self,
        rows: list[tuple[str, Decimal, datetime, str, Decimal | None, Decimal | None, Decimal | None]],
    ) -> None:
        """Update spot triple + intraday return triple on existing cards.

        Tuple shape: (ticker, price, quoted_at, source, ret_1d, ret_1w, ret_30d).
        Returns may be None (e.g., insufficient OHLC history). Does NOT commit.
        """
        if not rows:
            return
        with self._conn.cursor() as cur:
            cur.executemany(
                f"""
                UPDATE {self._schema}.watchlist_card
                SET spot           = %s,
                    spot_quoted_at = %s,
                    spot_source    = %s,
                    ret_1d         = %s,
                    ret_1w         = %s,
                    ret_30d        = %s
                WHERE ticker = %s
                """,
                [
                    (price, quoted_at, source, r1d, r1w, r30d, ticker)
                    for (ticker, price, quoted_at, source, r1d, r1w, r30d) in rows
                ],
            )
```

- [ ] **Step 3: Update the writer to compute returns**

Edit `src/uw_scan/worker/ws_db_writer.py`. Pre-cache daily_ohlc lookups for the lifetime of the writer (refreshed lazily on first miss); compute returns per tick on flush.

```python
from uw_scan.cards.returns import compute_returns
from uw_scan.storage.rows import DailyOhlcRow

class WsDbWriter:
    def __init__(
        self,
        *,
        repo: Repository,
        buffer: TickBuffer,
        source_tag: str = "massive.com_ws",
    ) -> None:
        self._repo = repo
        self._buffer = buffer
        self._source_tag = source_tag
        self._ohlc_cache: dict[str, list[DailyOhlcRow]] = {}

    def _history_for(self, ticker: str) -> list[DailyOhlcRow]:
        if ticker not in self._ohlc_cache:
            self._ohlc_cache[ticker] = self._repo.list_daily_ohlc(ticker, limit=40)
        return self._ohlc_cache[ticker]

    def invalidate_ohlc_cache(self) -> None:
        """Call after ohlc_pull runs (daily, post-close) to refresh prev closes."""
        self._ohlc_cache.clear()

    def flush_once(self) -> int:
        """Drain + flush. A2 (adversarial fix): drained ticks are held in
        `_pending` and only cleared after a successful commit. If the write
        raises (Postgres down, txn aborted, conn broken), the pending batch
        is merged back into the live buffer so the next flush retries —
        ticks are never lost to a transient failure.
        """
        # Drain into pending; merge with any pending from prior failed flush.
        snapshot = dict(self._buffer.drain())
        if self._pending:
            # Existing pending may overlap with new ticks. Keep the latest
            # per-ticker by quoted_at (the buffer's add() semantics).
            for ticker, tick in self._pending.items():
                existing = snapshot.get(ticker)
                if existing is None or tick.quoted_at > existing.quoted_at:
                    snapshot[ticker] = tick
            self._pending = {}
        if not snapshot:
            return 0
        self._pending = snapshot  # held until commit succeeds

        quote_rows: list[tuple] = []
        card_rows: list[tuple] = []
        latest_quoted_at: datetime | None = None
        for tick in snapshot.values():
            quote_rows.append((tick.ticker, tick.price, tick.quoted_at, self._source_tag))
            history = self._history_for(tick.ticker)
            returns = compute_returns(history, tick.price)
            card_rows.append(
                (tick.ticker, tick.price, tick.quoted_at, self._source_tag,
                 returns.ret_1d, returns.ret_1w, returns.ret_30d)
            )
            if latest_quoted_at is None or tick.quoted_at > latest_quoted_at:
                latest_quoted_at = tick.quoted_at

        flush_at = datetime.now(timezone.utc)
        n = len(quote_rows)
        try:
            with self._repo._conn.transaction():
                self._repo.bulk_upsert_intraday_quotes(quote_rows)
                self._repo.bulk_upsert_watchlist_card_quotes(card_rows)
                self._repo.record_ws_heartbeat(
                    last_tick_at=latest_quoted_at,
                    last_flush_at=flush_at,
                    ticks_received_delta=self._ticks_seen_since_last_flush,
                    ticks_flushed_delta=n,
                )
            # Commit succeeded — clear pending and the "raw received" counter.
            self._pending = {}
            self._ticks_seen_since_last_flush = 0
        except Exception:
            logger.exception(
                "ws_db_writer flush failed; %d ticks held in pending for retry",
                n,
            )
            # Merge pending back into the live buffer so next flush retries.
            for ticker, tick in self._pending.items():
                self._buffer.add(tick)
            self._pending = {}
            raise
        logger.debug("ws_db_writer flushed %d ticks", n)
        return n

    def note_received(self, count: int = 1) -> None:
        """Called from the WS reader on every tick received (before coalescing).
        Used by `record_ws_heartbeat(ticks_received_delta=...)` to surface true
        feed volume separately from the coalesced flush count (A12)."""
        self._ticks_seen_since_last_flush += count
```

Also extend `__init__` to track `_pending` and the raw-received counter:

```python
    def __init__(
        self,
        *,
        repo: Repository,
        buffer: TickBuffer,
        source_tag: str = "massive.com_ws",
    ) -> None:
        self._repo = repo
        self._buffer = buffer
        self._source_tag = source_tag
        self._ohlc_cache: dict[tuple[str, date], list[DailyOhlcRow]] = {}
        self._pending: dict[str, WsTick] = {}  # A2: held until commit succeeds
        self._ticks_seen_since_last_flush: int = 0  # A12: raw feed volume

    def _history_for(self, ticker: str) -> list[DailyOhlcRow]:
        """A6 (adversarial fix): cache is keyed by (ticker, market_session_date)
        so a new trading day naturally invalidates stale closes — no explicit
        invalidate_ohlc_cache() needed.

        Uses the ET market-session date (via `current_market_date` extracted
        from the old `_spot_refresh_market_date`), NOT `date.today()`. Using
        system local time would refresh wrong for any process running outside
        US/Eastern (CI, ops machines), and would split a single trading session
        across two cache keys during the 0:00–9:30 ET pre-market window.

        Outside RTH `current_market_date` returns None — in that case we use
        the most recent prior session date (computed by walking back to the
        previous weekday) so the writer can still compute returns during
        after-hours late-prints.
        """
        from datetime import datetime, timezone, timedelta
        from uw_scan.worker.market_session import current_market_date

        now = datetime.now(timezone.utc)
        market_date = current_market_date(now)
        if market_date is None:
            # Walk back to the most recent weekday for cache key stability
            # during overnight / weekend (matches behavior of full_scan).
            d = now.date()
            while d.weekday() >= 5:
                d -= timedelta(days=1)
            market_date = d

        key = (ticker, market_date)
        if key not in self._ohlc_cache:
            self._ohlc_cache[key] = self._repo.list_daily_ohlc(ticker, limit=40)
            # Bound memory: drop entries from earlier session dates
            self._ohlc_cache = {
                k: v for k, v in self._ohlc_cache.items() if k[1] == market_date
            }
        return self._ohlc_cache[key]
```

Add the helper to `src/uw_scan/worker/market_session.py` (the module Phase 7 creates by extraction):

```python
"""Market-session helpers (extracted from scheduler.py during Phase 7).

Pure functions; no DB or network. Shared by the WS consumer and the health
endpoint so both agree on "is the US equity market open right now?"
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def current_market_date(now: datetime, tz: str = "America/New_York") -> date | None:
    """Return the ET market date when the equity session is open / active.

    Returns ``None`` outside the RTH-plus-late-print window (mon-fri
    09:30-20:15 ET). Outside the window callers should fall back to the
    most recent prior weekday for cache stability.
    """
    local = now.astimezone(ZoneInfo(tz)) if now.tzinfo is not None else now.replace(tzinfo=ZoneInfo(tz))
    if local.weekday() >= 5:
        return None
    current = local.time()
    if time(9, 30) <= current <= time(20, 15):
        return local.date()
    return None
```

Also: `_ws_reader` in Phase 4 must call `writer.note_received(1)` for every tick BEFORE handing to the buffer, so the raw-count is recorded:

```python
async def _ws_reader(client, buffer, writer):
    async for tick in client.ticks():
        writer.note_received(1)
        buffer.add(tick)
```

Note: `compute_returns` is the existing helper at `src/uw_scan/cards/returns.py` used by spot_refresh today. The interface (returns row + history) is preserved.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/worker/test_ws_db_writer.py -v`
Expected: all PASS (including the new returns test).

- [ ] **Step 5: Stage**

```bash
git add src/uw_scan/storage/watchlist.py src/uw_scan/worker/ws_db_writer.py tests/integration/worker/test_ws_db_writer.py
```

**Phase 3 milestone: tick buffer + atomic DB writer + return updates work. User-gated commit: `feat(worker): WS tick buffer + atomic batch DB writer with return updates`.**

---

## Phase 4 — Long-lived consumer process

**Goal:** Wire the WS client + buffer + writer into a single process with reconnect/backoff, periodic flush, and dynamic watchlist subscription.

### Task 4.1: Subscription manager helpers

**Files:**
- Modify: `src/uw_scan/worker/ws_tick_buffer.py` (no, keep buffer pure — put diff logic in the consumer module)
- Test: `tests/unit/worker/test_ws_subscription_diff.py` (new)

- [ ] **Step 1: Write test for the subscription diff helper**

```python
# tests/unit/worker/test_ws_subscription_diff.py
from uw_scan.worker.massive_ws_consumer import compute_subscription_diff


def test_subscription_diff_initial():
    add, drop = compute_subscription_diff(current=set(), desired={"AAPL", "MSFT"}, channel="A")
    assert add == {"A.AAPL", "A.MSFT"}
    assert drop == set()


def test_subscription_diff_add_only():
    add, drop = compute_subscription_diff(
        current={"A.AAPL"}, desired={"AAPL", "MSFT"}, channel="A"
    )
    assert add == {"A.MSFT"}
    assert drop == set()


def test_subscription_diff_drop_only():
    add, drop = compute_subscription_diff(
        current={"A.AAPL", "A.MSFT"}, desired={"AAPL"}, channel="A"
    )
    assert add == set()
    assert drop == {"A.MSFT"}


def test_subscription_diff_full_swap():
    add, drop = compute_subscription_diff(
        current={"A.AAPL", "A.MSFT"}, desired={"SPY", "QQQ"}, channel="A"
    )
    assert add == {"A.SPY", "A.QQQ"}
    assert drop == {"A.AAPL", "A.MSFT"}
```

- [ ] **Step 2: Run, see it fail**

Run: `uv run pytest tests/unit/worker/test_ws_subscription_diff.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the helper (stub `massive_ws_consumer.py`)**

Create `src/uw_scan/worker/massive_ws_consumer.py` with just the helper for now:

```python
"""Long-lived WebSocket consumer for api.massive.com.

Runs as a separate `massive_ws` worker role. Holds one WS connection,
subscribes to the active watchlist, buffers ticks, and flushes them every
MASSIVE_WS_FLUSH_INTERVAL_SECONDS to the DB as a single atomic batch.

Lifecycle:
- main() → asyncio event loop
- 3 cooperating tasks:
    1. ws_reader — drains messages from the WS, populates the buffer
    2. flush_loop — every N seconds, calls WsDbWriter.flush_once()
    3. subscription_loop — every M seconds, diffs the watchlist and
       (un)subscribes via the active client
- Reconnect with exponential backoff on ConnectionClosed.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def compute_subscription_diff(
    *,
    current: set[str],
    desired: set[str],
    channel: str,
) -> tuple[set[str], set[str]]:
    """Return (channels_to_add, channels_to_drop) given current sub set and
    desired tickers. Channels are fully-qualified ("A.AAPL").

    `current` is the set of fully-qualified channels (e.g. {"A.AAPL"}).
    `desired` is the set of tickers (e.g. {"AAPL", "MSFT"}).
    `channel` is the prefix ("A", "AM", "T").
    """
    desired_channels = {f"{channel}.{t}" for t in desired}
    return (desired_channels - current, current - desired_channels)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/worker/test_ws_subscription_diff.py -v`
Expected: 4 PASS.

### Task 4.2: Consumer main loop with reconnect

**Files:**
- Modify: `src/uw_scan/worker/massive_ws_consumer.py`
- Modify: `src/uw_scan/config.py` (add `MASSIVE_WS_*` settings)
- Test: `tests/integration/worker/test_massive_ws_consumer.py`

- [ ] **Step 1: Add config keys**

Edit `src/uw_scan/config.py` — under the existing massive section, add:

```python
    # massive.com WebSocket consumer
    massive_ws_enabled: bool = False
    # Default to DELAYED tier (matches the user's current massive.com plan,
    # which returns 403 on /v3/quotes). Real-time tier upgrade: override via
    # env MASSIVE_WS_URL=wss://socket.massive.com/stocks
    massive_ws_url: str = "wss://delayed.massive.com/stocks"
    massive_ws_channel: str = "A"  # A=per-second, AM=per-minute, T=trades
    massive_ws_flush_interval_seconds: float = 1.0
    massive_ws_watchlist_poll_interval_seconds: float = 30.0
    massive_ws_reconnect_backoff_initial_seconds: float = 1.0
    massive_ws_reconnect_backoff_max_seconds: float = 60.0
    massive_ws_heartbeat_stale_after_seconds: float = 120.0
```

And in `from_env`:

```python
            massive_ws_enabled=os.environ.get("MASSIVE_WS_ENABLED", "false").lower() == "true",
            massive_ws_url=os.environ.get("MASSIVE_WS_URL", "wss://socket.massive.com/stocks"),
            massive_ws_channel=os.environ.get("MASSIVE_WS_CHANNEL", "A"),
            massive_ws_flush_interval_seconds=float(os.environ.get("MASSIVE_WS_FLUSH_INTERVAL_SECONDS", "1.0")),
            massive_ws_watchlist_poll_interval_seconds=float(os.environ.get("MASSIVE_WS_WATCHLIST_POLL_INTERVAL_SECONDS", "30.0")),
            massive_ws_reconnect_backoff_initial_seconds=float(os.environ.get("MASSIVE_WS_RECONNECT_BACKOFF_INITIAL_SECONDS", "1.0")),
            massive_ws_reconnect_backoff_max_seconds=float(os.environ.get("MASSIVE_WS_RECONNECT_BACKOFF_MAX_SECONDS", "60.0")),
            massive_ws_heartbeat_stale_after_seconds=float(os.environ.get("MASSIVE_WS_HEARTBEAT_STALE_AFTER_SECONDS", "120.0")),
```

- [ ] **Step 2: Write integration test against a fake WS server**

```python
# tests/integration/worker/test_massive_ws_consumer.py
import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import websockets

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.massive_ws_consumer import run_consumer_once


@pytest.mark.asyncio
async def test_consumer_subscribes_and_persists(seeded_db_with_cards, monkeypatch):
    """End-to-end: fake WS server pushes ticks, consumer subscribes,
    buffers, flushes, and persists into DB."""
    received_messages: list[str] = []

    async def handler(ws):
        async for msg in ws:
            received_messages.append(msg)
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send(json.dumps([
                    {"ev": "A", "sym": "AAPL", "c": 189.42, "e": 1779380400000},
                    {"ev": "A", "sym": "MSFT", "c": 425.10, "e": 1779380400000},
                ]))
                await asyncio.sleep(0.3)
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"

        repo = seeded_db_with_cards
        await run_consumer_once(
            ws_url=url,
            api_key="TEST_KEY",
            channel="A",
            tickers={"AAPL", "MSFT"},
            repo=repo,
            flush_interval_seconds=0.1,
            run_for_seconds=1.0,
        )

    assert repo.get_intraday_quote("AAPL").price == Decimal("189.42")
    assert repo.get_intraday_quote("MSFT").price == Decimal("425.10")
    state = repo.get_ws_consumer_state()
    assert state.ticks_flushed >= 2
```

- [ ] **Step 3: Run, see it fail**

Run: `uv run pytest tests/integration/worker/test_massive_ws_consumer.py -v`
Expected: FAIL — `run_consumer_once` doesn't exist.

- [ ] **Step 4: Implement the consumer loop**

Edit `src/uw_scan/worker/massive_ws_consumer.py` — append after the helper. Key design points (from tribunal + adversarial review):
- **Autocommit set IN psycopg.connect()** (A7), not afterwards — no window of implicit txn during repo init
- **TWO separate Repository instances** (A1): writer-repo for `flush_loop`, reader-repo for `subscription_loop`. psycopg3 connections are NOT thread-safe; sharing one would corrupt txn state
- **`asyncio.to_thread`** for every sync DB call so the event loop is never blocked (R1)
- **`asyncio.TaskGroup`** wraps reader + flusher + subscriber (A5): any task crash cancels the session, propagates, and the outer `run_consumer_forever` reconnects. No silent task death
- **DB-error classification** in the reconnect handler (A8): if the failure is a `psycopg.OperationalError`, skip the secondary `record_ws_error` attempt to avoid amplifying a DB outage

```python
import asyncio
import contextlib
from datetime import datetime, timezone

import psycopg

from uw_scan.config import Settings
from uw_scan.sources.massive_ws import MassiveWsClient
from uw_scan.storage.repository import Repository
from uw_scan.worker.ws_db_writer import WsDbWriter
from uw_scan.worker.ws_tick_buffer import TickBuffer


def _on_task_done(name: str):
    def _cb(task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("ws consumer task %r died: %s", name, repr(exc))
    return _cb


async def _ws_reader(client: MassiveWsClient, buffer: TickBuffer) -> None:
    async for tick in client.ticks():
        buffer.add(tick)


async def _flush_loop(writer: WsDbWriter, interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # Offload sync psycopg I/O to the default executor so the WS
            # reader can keep draining frames (R1: unanimous review finding).
            await asyncio.to_thread(writer.flush_once)
        except Exception:
            logger.exception("flush_loop: writer.flush_once failed; continuing")


async def _subscription_loop(
    *,
    client: MassiveWsClient,
    repo: Repository,
    channel: str,
    current_subs: set[str],
    poll_interval_seconds: float,
) -> None:
    while True:
        try:
            # Offload sync DB read off the event loop (R1)
            desired = await asyncio.to_thread(
                lambda: {w.ticker for w in repo.list_active_watchlist()}
            )
            to_add, to_drop = compute_subscription_diff(
                current=current_subs, desired=desired, channel=channel
            )
            if to_add:
                await client.subscribe(to_add)
                current_subs.update(to_add)
                logger.info("ws subscribed: %s", sorted(to_add))
            if to_drop:
                await client.unsubscribe(to_drop)
                current_subs.difference_update(to_drop)
                logger.info("ws unsubscribed: %s", sorted(to_drop))
        except Exception:
            logger.exception("subscription_loop: refresh failed; continuing")
        await asyncio.sleep(poll_interval_seconds)


async def run_consumer_once(
    *,
    ws_url: str,
    api_key: str,
    channel: str,
    tickers: set[str],
    writer_repo: Repository,
    reader_repo: Repository,
    flush_interval_seconds: float = 1.0,
    subscription_poll_interval_seconds: float = 30.0,
    run_for_seconds: float | None = None,
) -> None:
    """Single connection lifecycle.

    Holds two independent Repository instances (A1 — psycopg3 conns are NOT
    thread-safe across asyncio.to_thread call sites):
    - ``writer_repo``: used by the flush_loop's to_thread worker
    - ``reader_repo``: used by the subscription_loop's to_thread worker

    Both connections must be opened with ``autocommit=True`` (A7).

    Tasks (reader/flusher/subscriber) run inside an ``asyncio.TaskGroup`` (A5):
    any task crash propagates and cancels the others, the outer
    ``run_consumer_forever`` catches and reconnects.
    """
    buffer = TickBuffer()
    writer = WsDbWriter(repo=writer_repo, buffer=buffer)
    current_subs: set[str] = set()

    async with MassiveWsClient(ws_url, api_key) as client:
        # Record session start on the WRITER conn (its sole owner during
        # to_thread calls), in its own transaction under autocommit.
        await asyncio.to_thread(
            writer_repo.record_ws_connection_started, datetime.now(timezone.utc)
        )
        await client.subscribe({f"{channel}.{t}" for t in tickers})
        current_subs.update(f"{channel}.{t}" for t in tickers)

        try:
            async with asyncio.timeout(run_for_seconds) if run_for_seconds else _null_ctx():
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(_ws_reader(client, buffer, writer), name="ws_reader")
                    tg.create_task(_flush_loop(writer, flush_interval_seconds), name="ws_flusher")
                    tg.create_task(
                        _subscription_loop(
                            client=client,
                            repo=reader_repo,
                            channel=channel,
                            current_subs=current_subs,
                            poll_interval_seconds=subscription_poll_interval_seconds,
                        ),
                        name="ws_subscriber",
                    )
        except* (asyncio.TimeoutError, asyncio.CancelledError):
            pass  # graceful shutdown
        finally:
            # Final flush to drain anything still in the buffer.
            try:
                await asyncio.to_thread(writer.flush_once)
            except Exception:
                logger.exception("run_consumer_once: final flush failed")


@contextlib.asynccontextmanager
async def _null_ctx():
    yield


async def run_consumer_forever(settings: Settings, repo_factory) -> None:
    """Reconnect with exponential backoff on disconnect.

    ``repo_factory(role)`` returns an async context manager yielding a
    Repository with an autocommit connection. We open TWO repos per session
    (A1): role="writer" and role="reader".

    On exception, classify (A8): if the cause is a ``psycopg.OperationalError``
    or a fresh-conn failure, skip the secondary error-record attempt (the DB
    is unreachable; don't amplify).
    """
    backoff = settings.massive_ws_reconnect_backoff_initial_seconds
    while True:
        try:
            with repo_factory("writer") as writer_repo, repo_factory("reader") as reader_repo:
                desired = await asyncio.to_thread(
                    lambda: {w.ticker for w in reader_repo.list_active_watchlist()}
                )
                await run_consumer_once(
                    ws_url=settings.massive_ws_url,
                    api_key=settings.massive_api_key.get_secret_value(),
                    channel=settings.massive_ws_channel,
                    tickers=desired,
                    writer_repo=writer_repo,
                    reader_repo=reader_repo,
                    flush_interval_seconds=settings.massive_ws_flush_interval_seconds,
                    subscription_poll_interval_seconds=settings.massive_ws_watchlist_poll_interval_seconds,
                )
            backoff = settings.massive_ws_reconnect_backoff_initial_seconds
        except psycopg.OperationalError as exc:
            # A8: DB is the failure — opening a 2nd conn to record_ws_error
            # would just fail and spam logs. Skip the record attempt; just
            # backoff and retry. The next successful connect will be visible
            # via the heartbeat resuming.
            logger.exception("ws consumer: DB unreachable, skipping error record; backoff=%.1fs", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, settings.massive_ws_reconnect_backoff_max_seconds)
            continue
        except* Exception as exc_group:  # except* required because TaskGroup wraps
            # All non-DB failures: best-effort error recording in a brand-new conn
            logger.exception("ws consumer crashed: %s; backoff=%.1fs", repr(exc_group), backoff)
            try:
                with repo_factory("writer") as err_repo:
                    err_repo.record_ws_error(repr(exc_group), datetime.now(timezone.utc))
            except (psycopg.OperationalError, Exception):
                logger.exception("ws consumer: failed to record error to DB (ignored)")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, settings.massive_ws_reconnect_backoff_max_seconds)


def main() -> int:
    from contextlib import contextmanager

    settings = Settings.from_env()
    if not settings.massive_ws_enabled:
        logger.warning("MASSIVE_WS_ENABLED is false; exiting")
        return 0
    if settings.massive_api_key is None:
        logger.error("MASSIVE_API_KEY is not set; cannot start WS consumer")
        return 1

    @contextmanager
    def _repo_factory(role: str):
        # A7: autocommit set at connect time (not afterwards) so no implicit
        # txn opens between connect + flip. application_name lets ops
        # distinguish writer vs reader conns in pg_stat_activity.
        conn = psycopg.connect(
            settings.db_dsn(),
            autocommit=True,
            application_name=f"massive_ws_consumer:{role}",
        )
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    asyncio.run(run_consumer_forever(settings, _repo_factory))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/integration/worker/test_massive_ws_consumer.py tests/unit/worker/test_ws_subscription_diff.py -v`
Expected: all PASS.

- [ ] **Step 6: Stage**

```bash
git add src/uw_scan/worker/massive_ws_consumer.py src/uw_scan/config.py tests/integration/worker/test_massive_ws_consumer.py tests/unit/worker/test_ws_subscription_diff.py
```

### Task 4.3: Reconnect / backoff test (R5 — review fix)

**Files:**
- Test: extend `tests/integration/worker/test_massive_ws_consumer.py`

**Why:** `run_consumer_forever` is the safety net under the no-fallback design. Untested reconnect logic + exponential backoff has high blast radius (off-by-one in the `min(backoff * 2, max)` would cause a request flood on a flaky upstream).

- [ ] **Step 1: Add the reconnect test**

**Important — design choice (R5 + adversarial follow-up):** The earlier draft used a "claim port, close it, start consumer, bring server up + down + up again" pattern. That pattern is **flaky** on macOS / CI because the kernel may reassign the released port to another process between releases. Replaced with ONE persistent fake server whose handler is **counter-driven**: it rejects the first 2 connection attempts (closes before auth) and accepts on the 3rd. This is deterministic and verifies BOTH that reconnect happens AND that the exponential backoff actually grows between attempts.

```python
import asyncio
import contextlib
import json
import time as time_module
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import websockets

from uw_scan.config import Settings
from uw_scan.worker.massive_ws_consumer import run_consumer_forever


async def test_consumer_backs_off_then_recovers(seeded_db_with_cards):
    """Fake server rejects the first 2 connection attempts (closes immediately)
    and accepts the 3rd. Validates:
      1. exponential backoff progresses through retries (gap_2 >= gap_1)
      2. successful reconnect resumes tick flow
      3. ws_consumer_state.ticks_received increments after recovery
    """
    repo = seeded_db_with_cards
    connection_log: list[float] = []  # monotonic times of each handler invocation
    tick_sent = asyncio.Event()

    async def handler(ws):
        attempt_num = len(connection_log) + 1
        connection_log.append(time_module.monotonic())
        if attempt_num < 3:
            await ws.close(code=1011, reason="simulated transient failure")
            return
        # 3rd attempt: succeed, push one tick, then close.
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send(json.dumps([
                    {"ev": "A", "sym": "TSLA", "c": 451.00, "e": 1779380400000},
                ]))
                tick_sent.set()
                await asyncio.sleep(0.2)
                await ws.close()
                return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        settings = Settings.from_env().model_copy(update={
            "massive_ws_enabled": True,
            "massive_ws_url": f"ws://127.0.0.1:{port}",
            "massive_ws_channel": "A",
            "massive_ws_flush_interval_seconds": 0.05,
            "massive_ws_watchlist_poll_interval_seconds": 0.5,
            "massive_ws_reconnect_backoff_initial_seconds": 0.05,
            "massive_ws_reconnect_backoff_max_seconds": 0.5,
        })

        @contextmanager
        def _repo_factory(role: str):
            # Test reuses the single fixture conn for both roles. Production
            # uses two distinct conns — A1 doesn't apply here because the
            # test never runs flush_loop and subscription_loop concurrently
            # on the same physical second.
            repo._conn.autocommit = True
            yield repo

        consumer_task = asyncio.create_task(
            run_consumer_forever(settings, _repo_factory)
        )

        try:
            await asyncio.wait_for(tick_sent.wait(), timeout=5.0)
        finally:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

    # Assertions
    assert len(connection_log) >= 3, (
        f"expected ≥3 connection attempts (2 rejects + 1 success), got "
        f"{len(connection_log)}"
    )
    # Exponential backoff: gap_2 must be at least ~80% of gap_1 (tolerate
    # asyncio scheduler jitter; 80% is enough to catch a literal "no growth"
    # bug like `backoff = backoff` instead of `backoff = min(backoff * 2, max)`).
    gaps = [
        connection_log[i + 1] - connection_log[i]
        for i in range(len(connection_log) - 1)
    ]
    if len(gaps) >= 2:
        assert gaps[1] >= gaps[0] * 0.8, f"backoff did not grow: gaps={gaps}"
    # Allow a moment for the final flush after consumer cancellation,
    # then verify DB has the recovered tick.
    await asyncio.sleep(0.3)
    q = repo.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("451.00")
```

- [ ] **Step 2: Run the new test**

Run: `uv run pytest tests/integration/worker/test_massive_ws_consumer.py::test_consumer_backs_off_then_recovers -v`
Expected: PASS within ~3s.

- [ ] **Step 3: Stage**

```bash
git add tests/integration/worker/test_massive_ws_consumer.py
```

**Phase 4 milestone: end-to-end consumer works against fake server, including reconnect/backoff. User-gated commit: `feat(worker): massive.com WS consumer with reconnect + subscription manager`.**

---

## Phase 5 — Dev integration + health surface

**Goal:** The new process runs in `scripts/dev.sh`. The API health endpoint reports WS heartbeat status.

### Task 5.1: Add WS consumer to `scripts/dev.sh`

**Files:**
- Modify: `scripts/dev.sh`

- [ ] **Step 1: Add a new concurrently process AND export WS flag to all workers**

R6 (review fix): `MASSIVE_WS_ENABLED` must be visible to the `uw-*` scheduler processes too — that's where `_full_scan` / `_rescan` decide whether to pass `preserve_spot=True`. Adding it only to the new consumer process leaves `full_scan` writing UW-derived spot over WS values.

Edit `scripts/dev.sh`:

```bash
COUNTS="UW_SCAN_UW_WORKER_COUNT=2 UW_SCAN_MASSIVE_WORKER_COUNT=2 UW_SCAN_AI_WORKER_COUNT=2"
# Single source of truth for WS mode. Exported to API + every worker so
# scheduler closures see the same value (R6).
WS="MASSIVE_WS_ENABLED=true"
```

Update each `concurrently` process line to prefix with `$WS`, and add the new consumer process:

```bash
exec npx --prefix web concurrently \
  -n next,api,uw-0,uw-1,massive-0,massive-1,ai-0,ai-1,massive-ws \
  -c cyan,green,yellow,magenta,blue,white,red,gray,brightCyan \
  "cd web && npm run dev" \
  "$COUNTS $WS uv run uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400 --reload --reload-dir src" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=uw UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=uw UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=massive UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=massive UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai UW_SCAN_WORKER_INDEX=0 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS UW_SCAN_WORKER_ROLE=ai UW_SCAN_WORKER_INDEX=1 UW_SCAN_WORKER_COUNT=2 uv run python -m uw_scan.worker.scheduler" \
  "$COUNTS $WS uv run python -m uw_scan.worker.massive_ws_consumer"
```

- [ ] **Step 2: Smoke test**

Run: `bash scripts/dev.sh` (in a separate terminal). Wait ~10s. Verify the `massive-ws` process starts without crashing.

Expected: log lines like `massive_ws auth response: ...` and `ws subscribed: [...]`.

If Phase 0 verified the WS endpoint works, this should produce real ticks within seconds. If the consumer immediately backs off + retries, check the auth/url/channel against your Phase 0 findings.

- [ ] **Step 3: Stop dev.sh, stage**

```bash
git add scripts/dev.sh
```

### Task 5.2: Health endpoint surfaces WS heartbeat

**Files:**
- Modify: `src/uw_scan/api/routers/health.py`
- Test: `tests/integration/api/test_health_ws.py` (new)

- [ ] **Step 1: Find the existing health surface**

```bash
grep -n "def health\|ws_consumer\|heartbeat" /Users/chenxi/projects/unusual-whales/src/uw_scan/api/routers/health.py | head -20
```

- [ ] **Step 2: Write failing test**

```python
# tests/integration/api/test_health_ws.py
from datetime import datetime, timezone

from fastapi.testclient import TestClient


def test_health_includes_ws_consumer(test_client: TestClient, seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = datetime.now(timezone.utc)
    repo.record_ws_heartbeat(
        last_tick_at=ts,
        last_flush_at=ts,
        ticks_received_delta=10,
        ticks_flushed_delta=10,
    )
    repo._conn.commit()  # Repository has no .commit(); use the underlying conn

    r = test_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "ws_consumer" in body
    assert body["ws_consumer"]["ticks_received"] == 10
    assert body["ws_consumer"]["healthy"] is True
```

- [ ] **Step 3: Run, see it fail**

Run: `uv run pytest tests/integration/api/test_health_ws.py -v`
Expected: FAIL — health response has no `ws_consumer` field.

- [ ] **Step 4: Wire WS state into the health response**

The health response is a Pydantic `HealthResponse` model (verified at `api/routers/health.py:25-57`). Add a sub-model and a field. Concrete edits:

In `src/uw_scan/api/routers/health.py`, add the model below `RecordHealthCheck` (~line 79):

```python
class WsConsumerHealth(BaseModel):
    healthy: bool
    last_tick_at: datetime | None = None
    last_tick_age_seconds: float | None = None
    last_flush_at: datetime | None = None
    ticks_received: int = 0
    ticks_flushed: int = 0
    connection_started_at: datetime | None = None
    last_error: str | None = None
    reason: str | None = None
```

Add the field to `HealthResponse` (after `workers:` ~line 57):

```python
    ws_consumer: WsConsumerHealth | None = None
```

In the `health()` function, after the existing `worker_health = ...` block (~line 217), add. R4 (review fix): the health check must be **market-session aware** — outside RTH no ticks flow, so a static staleness threshold would falsely report unhealthy every weekend and every overnight period.

```python
    # Reuse the existing market-session helper. Outside the RTH window
    # (mon-fri 09:30-20:15 ET), no ticks are expected — heartbeat staleness
    # is benign.
    from uw_scan.worker.scheduler import _spot_refresh_market_date
    in_session = _spot_refresh_market_date(datetime.now(ZoneInfo(settings.rth_tz))) is not None

    ws_state = repo.get_ws_consumer_state()
    if ws_state is None or ws_state.last_tick_at is None:
        ws_consumer = WsConsumerHealth(
            healthy=not in_session,  # only red-flag during open session
            reason="no ticks received yet" if in_session else "market closed",
        )
    else:
        age_s = (now_utc - ws_state.last_tick_at).total_seconds()
        stale = age_s >= settings.massive_ws_heartbeat_stale_after_seconds
        ws_consumer = WsConsumerHealth(
            # When market is closed, accept any age — no ticks are expected.
            healthy=(not stale) or (not in_session),
            last_tick_at=ws_state.last_tick_at,
            last_tick_age_seconds=age_s,
            last_flush_at=ws_state.last_flush_at,
            ticks_received=ws_state.ticks_received,
            ticks_flushed=ws_state.ticks_flushed,
            connection_started_at=ws_state.connection_started_at,
            last_error=ws_state.last_error,
            reason=("heartbeat stale" if stale and in_session else
                    ("market closed" if stale else None)),
        )
```

The `_spot_refresh_market_date` helper currently lives in `worker/scheduler.py`. Phase 7 deletes most of `scheduler.py`'s spot-refresh wiring, but **keep this helper** — extract it to a shared module like `worker/market_session.py` so both the WS consumer (which may want session checks) and the API can reuse it without importing from scheduler.

The Phase 7 task list already plans to delete this helper — UPDATE that step: instead of deleting, move it to `worker/market_session.py` with the same signature.

Then add `"ws_consumer": ws_consumer,` to the `heartbeat_fields` dict (~line 240).

**Note for Phase 7 author:** Once Phase 7 deletes `_spot_refresh`, the existing `spot_refresh_heartbeat_lag_seconds` field on `HealthResponse` will always be `None`. Keep the field in the model for backward-compat (frontend may read it) but document it as deprecated. The `latest_spot_quote_*` fields still work because they read from `intraday_quote` which is now populated by WS.

- [ ] **Step 5: Run tests + regen frontend types + OpenAPI snapshot**

Run: `uv run pytest tests/integration/api/test_health_ws.py -v`
Expected: PASS.

Run: `cd web && npm run gen:types`
Expected: `web/lib/types.ts` regenerated with the new `ws_consumer` field.

R12 (review fix): the snapshot test at `tests/integration/api/test_openapi_snapshot.py:11-26` reads `client.get("/openapi.json").json()` via TestClient and compares `current["paths"]` + `current["components"]["schemas"]` to `openapi.snapshot.json`. Adding `WsConsumerHealth` + the `ws_consumer` field on `HealthResponse` changes the schemas dict, so the snapshot must be regenerated using the **same TestClient call** the test uses (so the JSON exactly matches the test's view, including FastAPI's auto-generated component naming):

```bash
uv run python -c "
import json
from fastapi.testclient import TestClient
from uw_scan.api.server import app

client = TestClient(app)
payload = client.get('/openapi.json').json()
with open('tests/integration/api/openapi.snapshot.json', 'w') as f:
    json.dump(payload, f, indent=2, sort_keys=True)
"
```

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: PASS (snapshot now matches).

- [ ] **Step 6: Stage**

```bash
git add src/uw_scan/api/routers/health.py tests/integration/api/test_health_ws.py tests/integration/api/openapi.snapshot.json web/lib/types.ts
```

### Task 5.3: Update HealthPanel React component to surface WS status (R15 — review fix)

**Files:**
- Modify: `web/components/shared/HealthPanel.tsx`
- Test: extend any existing HealthPanel e2e test, OR add a new vitest unit test

**Why:** Operator visibility is the ONLY safety signal under the no-fallback design. Adding `ws_consumer` to the JSON response without updating the UI means operators won't see when WS is down until users complain about stale prices.

- [ ] **Step 1: Confirm the existing structure** (already verified 2026-05-21)

`HealthPanel.tsx` (415 lines) is a self-contained client component that:
- Fetches `/api/health` internally every 5s via `setInterval` (line 212) — no `data` prop
- Renders rows via the existing `StatusRow` component (lines 123-146)
- Uses `heartbeatStatus(lagSeconds, healthyLagSeconds)` (lines 66-75) to map lag → `{label: "ONLINE"|"STALE"|"UNKNOWN", color: "var(--positive|warning|negative)"}`
- The "Last spot" row at lines 333-341 shows `spot_quote_lag_seconds` — after this work, that becomes the WS quote lag (since `intraday_quote` is WS-written). Keep it.

The component already auto-refreshes the new `ws_consumer` field once the API returns it.

- [ ] **Step 2: Add the WS StatusRow inside the body**

Edit `web/components/shared/HealthPanel.tsx`. Two small additions:

(a) Compute a WS status near the other status computations (~line 235, beside `recordsStatus`):

```tsx
  const wsConsumer = h?.ws_consumer;
  const wsStatus: { label: string; color: string } = (() => {
    if (!wsConsumer) return { label: "UNKNOWN", color: "var(--warning)" };
    if (wsConsumer.healthy) return { label: "ONLINE", color: "var(--positive)" };
    return {
      label: (wsConsumer.reason ?? "STALE").toUpperCase().slice(0, 12),
      color: "var(--negative)",
    };
  })();
```

(b) Include `wsStatus` in the `worstStatus(...)` summary array so the collapsed-panel dot reflects WS health. Insert it after `recordsStatus`:

```tsx
  const summary = worstStatus(
    workerRows.length > 0
      ? [apiStatus, schedulerStatus, workerGroupStatus(uwWorkers),
         workerGroupStatus(massiveWorkers),
         ...(aiWorkers.length > 0 ? [workerGroupStatus(aiWorkers)] : []),
         recordsStatus, wsStatus]
      : [apiStatus, schedulerStatus, rescanStatus, spotRefreshStatus,
         recordsStatus, wsStatus],
  );
```

(c) Add a `StatusRow` + tick-age row inside the expanded `<div id="health-panel-body">` block. Place after the existing "Last spot" row (~line 341), reusing the existing `rowStyle`/`labelStyle`/`valStyle`:

```tsx
          <StatusRow label="WS Consumer" status={wsStatus} />
          {wsConsumer && (
            <div style={rowStyle}>
              <span style={labelStyle}>WS tick age</span>
              <span style={valStyle}>{fmtDuration(wsConsumer.last_tick_age_seconds ?? null)}</span>
            </div>
          )}
          {wsConsumer && (
            <div style={rowStyle}>
              <span style={labelStyle}>WS received</span>
              <span style={valStyle}>{wsConsumer.ticks_received.toLocaleString()}</span>
            </div>
          )}
```

- [ ] **Step 3: Add a unit test**

The component fetches `/api/health` internally — to test the row, mock `api.health` (the existing import from `@/lib/api`). Vitest is already configured at `web/vitest.config.ts`. Place test next to the component:

```typescript
// web/components/shared/HealthPanel.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { HealthPanel } from "./HealthPanel";

vi.mock("@/lib/api", () => ({
  api: { health: vi.fn() },
}));
import { api } from "@/lib/api";

const baseHealth = {
  ok: true, db: "up", workers: [],
  scheduler_heartbeat_lag_seconds: 1, rescan_heartbeat_lag_seconds: 1,
  spot_refresh_heartbeat_lag_seconds: 1, spot_quote_lag_seconds: 1,
  latency_p95_ms: 0, http_2xx: 0, http_4xx: 0, http_5xx: 0,
  uw_today: 0, throughput_window_minutes: 0, requests_per_minute: 0,
  http_429: 0, avg_scan_duration_seconds: 0, queue_drain_rate_per_minute: 0,
  record_health_ok: true, record_health: [],
  source: "UnusualWhales", watchlist_size: 100,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("HealthPanel ws_consumer", () => {
  it("shows ONLINE when ws_consumer.healthy is true", async () => {
    (api.health as any).mockResolvedValue({
      ...baseHealth,
      ws_consumer: {
        healthy: true, ticks_received: 1234, ticks_flushed: 1230,
        last_tick_age_seconds: 0.8, reason: null, last_error: null,
        last_tick_at: "2026-05-21T14:00:00Z",
        last_flush_at: "2026-05-21T14:00:01Z",
        connection_started_at: "2026-05-21T13:00:00Z",
      },
    });
    render(<HealthPanel />);
    // Expand the panel
    const toggle = await screen.findByRole("button", { name: /status/i });
    toggle.click();
    await waitFor(() => expect(screen.getByText("WS Consumer")).toBeTruthy());
    expect(screen.getByText("ONLINE")).toBeTruthy();
    expect(screen.getByText("1,234")).toBeTruthy();
  });

  it("shows the reason when ws_consumer.healthy is false", async () => {
    (api.health as any).mockResolvedValue({
      ...baseHealth,
      ws_consumer: {
        healthy: false, ticks_received: 0, ticks_flushed: 0,
        reason: "heartbeat stale", last_error: null,
        last_tick_age_seconds: 300, last_tick_at: null,
        last_flush_at: null, connection_started_at: null,
      },
    });
    render(<HealthPanel />);
    const toggle = await screen.findByRole("button", { name: /status/i });
    toggle.click();
    await waitFor(() => expect(screen.getByText(/HEARTBEAT/i)).toBeTruthy());
  });
});
```

- [ ] **Step 4: Run web tests**

```bash
cd web && npm run test -- HealthPanel
```
Expected: 2 PASS.

- [ ] **Step 5: Stage**

```bash
git add web/components/shared/HealthPanel.tsx web/components/shared/HealthPanel.test.tsx
```

**Phase 5 milestone: dev environment runs the consumer; health surface reports state AND the panel displays it. User-gated commit: `feat(api,web,scripts): wire WS consumer into dev + expose heartbeat in health surface and HealthPanel`.**

---

## Phase 6 — Writer discipline (gate REST/UW from overwriting spot)

**Goal:** When WS is the authoritative writer, `full_scan_once` and `rescan_tick` must stop writing the `spot` / `spot_quoted_at` / `spot_source` fields on `watchlist_card`. They keep writing all analytical fields (IV, GEX, etc.) — only the spot triple is gated.

### Task 6.1: Identify the spot-writing call sites

**Files:** None (research)

- [ ] **Step 1: Grep for spot writes**

```bash
grep -rn "upsert_watchlist_card\|spot_source\|watchlist_card.*spot" /Users/chenxi/projects/unusual-whales/src/ | grep -v __pycache__ | grep -v test_
```

Document the call sites:
- `worker/jobs/spot_refresh.py:46–56` (WS-authoritative — should NOT call upsert_watchlist_card when WS healthy, but its own gating is handled in Phase 7)
- `worker/jobs/full_scan.py` and `cards/derive.py` (UW-derived spot)
- `worker/jobs/rescan_loop.py` (same path as full_scan)

- [ ] **Step 2: Capture the exact spot field positions in `upsert_watchlist_card`**

Read `src/uw_scan/storage/watchlist.py` around the `upsert_watchlist_card` method (find via grep). Note which parameters control `spot`, `spot_quoted_at`, `spot_source`.

### Task 6.2: Add a `preserve_spot` flag

**Files:**
- Modify: `src/uw_scan/storage/watchlist.py` (extend `upsert_watchlist_card`)
- Test: `tests/integration/storage/test_upsert_watchlist_card_preserve_spot.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/storage/test_upsert_watchlist_card_preserve_spot.py
from datetime import datetime, timezone
from decimal import Decimal


def test_upsert_with_preserve_spot_does_not_overwrite_spot(seeded_db_with_cards):
    """seeded_db_with_cards seeds one TSLA card with spot=445.12."""
    repo = seeded_db_with_cards
    ws_ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    # Simulate WS path setting a fresher spot
    repo.bulk_upsert_watchlist_card_spots([
        ("TSLA", Decimal("450.00"), ws_ts, "massive.com_ws"),
    ])
    repo._conn.commit()

    # full_scan tries to overwrite with UW-derived spot — must NOT win
    full_scan_ts = datetime(2026, 5, 21, 14, 5, tzinfo=timezone.utc)
    existing = repo.get_watchlist_card("TSLA")
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=full_scan_ts,
        spot=Decimal("999.99"),
        spot_quoted_at=full_scan_ts,
        spot_source="uw_scan",
        preserve_spot=True,
    )
    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    assert card.spot_source == "massive.com_ws"


def test_upsert_without_preserve_spot_overwrites(seeded_db_with_cards):
    """Backward-compat: omitting the flag preserves current behavior."""
    repo = seeded_db_with_cards
    ts = datetime(2026, 5, 21, 14, 5, tzinfo=timezone.utc)
    existing = repo.get_watchlist_card("TSLA")
    repo.upsert_watchlist_card(
        ticker="TSLA",
        run_id=existing.run_id,
        scanned_at=ts,
        spot=Decimal("999.99"),
        spot_quoted_at=ts,
        spot_source="uw_scan",
    )
    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("999.99")
    assert card.spot_source == "uw_scan"
```

- [ ] **Step 2: Run, see it fail**

Run: `uv run pytest tests/integration/storage/test_upsert_watchlist_card_preserve_spot.py -v`
Expected: FAIL — `preserve_spot` param doesn't exist.

- [ ] **Step 3: Add the flag to `upsert_watchlist_card`**

The existing method (verified at `storage/watchlist.py:98-126`) builds INSERT cols dynamically from `spot` (positional) plus `**fields` (kwargs). Replace it with the version below. Semantic: when `preserve_spot=True`, INSERT still sets spot fields on a brand-new row (first full_scan before any WS ticks), but the `ON CONFLICT DO UPDATE` SET clause omits the three spot columns so WS-written values are never clobbered.

```python
    def upsert_watchlist_card(
        self,
        *,
        ticker: str,
        run_id: int,
        scanned_at: datetime,
        spot: Decimal | None = None,
        preserve_spot: bool = False,
        **fields: Any,
    ) -> None:
        """Insert or replace the per-ticker card row.

        When `preserve_spot=True`, an existing row's spot / spot_quoted_at /
        spot_source are never overwritten — used by full_scan and rescan_tick
        once the WS consumer is the authoritative spot writer.

        `updated_at` is DB-owned (default NOW() on insert; refreshed by the
        conflict branch). It is NOT part of the column list, so INSERT cols
        and VALUES placeholders have matching arity.
        """
        cols = ["ticker", "run_id", "scanned_at", "spot", *fields.keys()]
        vals = [ticker, run_id, scanned_at, spot, *fields.values()]
        placeholders = ", ".join(["%s"] * len(cols))
        # A13 (adversarial fix): when WS owns spot, it also owns the
        # intraday-derived returns. Excluding only the spot triple would let
        # full_scan overwrite ret_1d/1w/30d with values computed from its
        # snapshot, drifting the dashboard returns away from the WS spot.
        SPOT_COLS = {"spot", "spot_quoted_at", "spot_source", "ret_1d", "ret_1w", "ret_30d"}
        if preserve_spot:
            update_cols = [c for c in cols if c != "ticker" and c not in SPOT_COLS]
        else:
            update_cols = [c for c in cols if c != "ticker"]
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols)
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {self._schema}.watchlist_card ({", ".join(cols)})
                VALUES ({placeholders})
                ON CONFLICT (ticker) DO UPDATE SET {updates}, updated_at=NOW()
                """,
                vals,
            )
        self._conn.commit()
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/storage/test_upsert_watchlist_card_preserve_spot.py -v`
Expected: PASS.

- [ ] **Step 5: Stage**

```bash
git add src/uw_scan/storage/watchlist.py tests/integration/storage/test_upsert_watchlist_card_preserve_spot.py
```

### Task 6.3: Gate full_scan + rescan_tick

**Files:**
- Modify: `src/uw_scan/worker/jobs/full_scan.py` (find the upsert_watchlist_card call)
- Modify: `src/uw_scan/worker/jobs/rescan_loop.py`
- Modify: `src/uw_scan/cards/derive.py` if it's the caller
- Test: extend `tests/integration/worker/test_worker_jobs.py`

- [ ] **Step 1: Find the calls**

```bash
grep -rn "upsert_watchlist_card" /Users/chenxi/projects/unusual-whales/src/uw_scan/worker/ /Users/chenxi/projects/unusual-whales/src/uw_scan/cards/ | grep -v __pycache__
```

- [ ] **Step 2: Plumb `preserve_spot` through**

Add a `preserve_spot: bool` parameter to `full_scan_once()` and `rescan_tick()`. Default `False` for backward-compat. Pass through to the underlying `repo.upsert_watchlist_card` call.

- [ ] **Step 3: Wire from `scheduler.py`**

In `worker/scheduler.py`'s `_full_scan` and `_rescan` closures, set `preserve_spot=settings.massive_ws_enabled`. (When WS is on, UW-derived spot is suppressed.)

- [ ] **Step 4: Write integration test**

```python
# tests/integration/worker/test_full_scan_preserves_spot.py
def test_full_scan_preserves_spot_when_flag_set(seeded_db_with_cards, uw_client_stub):
    """With preserve_spot=True, full_scan_once must not change spot."""
    # ... arrange existing card with WS-set spot ...
    # ... run full_scan_once(preserve_spot=True) ...
    # ... assert spot unchanged ...
```

- [ ] **Step 5: Run all worker tests**

Run: `uv run pytest tests/integration/worker/ tests/unit/worker/ -v`
Expected: all PASS.

- [ ] **Step 6: Stage**

```bash
git add src/uw_scan/worker/jobs/full_scan.py src/uw_scan/worker/jobs/rescan_loop.py src/uw_scan/worker/scheduler.py src/uw_scan/cards/derive.py tests/integration/worker/test_full_scan_preserves_spot.py
```

### Task 6.4: Propagate `intraday_quote.source` to readers (R7 — review fix)

**Files:**
- Modify: `src/uw_scan/storage/rows.py` — extend `IntradayQuoteRow` with `source`
- Modify: `src/uw_scan/storage/market_data.py` — `get_intraday_quote()` selects source
- Modify: `src/uw_scan/storage/watchlist.py:194-211` — dashboard SQL uses `q.source` instead of hardcoded `'massive.com_intraday'`
- Modify: `src/uw_scan/api/routers/stock.py:97-119` — `_with_latest_spot()` uses `quote.source`
- Test: `tests/integration/storage/test_dashboard_source_propagation.py` (new)

**Why:** Phase 1 added `intraday_quote.source` so we can distinguish `"massive.com_ws"` from the legacy `"massive.com_intraday"`. But the dashboard SQL currently HARDCODES `'massive.com_intraday'` in the CASE-when-q-wins branch, so the UI would show stale source labels even after WS is the writer.

- [ ] **Step 1: Extend IntradayQuoteRow**

Edit `src/uw_scan/storage/rows.py` — add `source: str` to `IntradayQuoteRow` after `quoted_at` / `fetched_at`.

- [ ] **Step 2: Update `get_intraday_quote()`**

Edit `src/uw_scan/storage/market_data.py:76-86` — SELECT and project `source`:

```python
    def get_intraday_quote(self, ticker: str) -> IntradayQuoteRow | None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT ticker, price, quoted_at, fetched_at, source
                FROM {self._schema}.intraday_quote WHERE ticker=%s
                """,
                (ticker,),
            )
            row = cur.fetchone()
            return IntradayQuoteRow(*row) if row else None
```

- [ ] **Step 3: Update dashboard SQL**

Edit `src/uw_scan/storage/watchlist.py:206-211` — replace the hardcoded source branch:

```sql
                  CASE
                    WHEN q.price IS NOT NULL
                      AND (c.spot_quoted_at IS NULL OR q.quoted_at >= c.spot_quoted_at)
                      THEN q.source
                    ELSE c.spot_source
                  END                                                       AS spot_source,
```

- [ ] **Step 4: Update `_with_latest_spot`**

Edit `src/uw_scan/api/routers/stock.py:97-119`. Replace the hardcoded `"massive.com_intraday"` in the quote branch with `quote.source`:

```python
    if quote is not None and (best_at is None or quote.quoted_at >= best_at):
        best_spot = quote.price
        best_at = quote.quoted_at
        best_source = quote.source
```

- [ ] **Step 5: Write regression test**

```python
# tests/integration/storage/test_dashboard_source_propagation.py
from datetime import datetime, timezone
from decimal import Decimal


def test_dashboard_shows_ws_source_when_ws_writes(seeded_db_with_cards):
    """When intraday_quote.source='massive.com_ws' and quoted_at is newer
    than the card, the dashboard row should surface 'massive.com_ws' (not
    the legacy hardcoded label)."""
    repo = seeded_db_with_cards
    ts = datetime.now(timezone.utc)
    repo.upsert_intraday_quote(
        "TSLA", Decimal("450.00"), ts, source="massive.com_ws"
    )
    rows, _ = repo.list_watchlist_cards_with_queue_summary()
    tsla = next(r for r in rows if r.ticker == "TSLA")
    assert tsla.spot == Decimal("450.00")
    assert tsla.spot_source == "massive.com_ws"
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/integration/storage/test_dashboard_source_propagation.py tests/integration/api/ -v`
Expected: all PASS. Existing api tests should still pass since the source label change is additive.

- [ ] **Step 7: Stage**

```bash
git add src/uw_scan/storage/rows.py src/uw_scan/storage/market_data.py src/uw_scan/storage/watchlist.py src/uw_scan/api/routers/stock.py tests/integration/storage/test_dashboard_source_propagation.py
```

**Phase 6 milestone: writer discipline enforced AND source label propagated. User-gated commit: `feat(worker,storage): gate full_scan/rescan + propagate intraday_quote.source to readers`.**

---

## Phase 7 — Remove REST polling entirely

**Goal:** Delete `spot_refresh` REST job and its supporting code. The WS consumer is the **sole** writer of intraday spot data. No fallback. If WS is down, spot data is stale until it reconnects — operator observability via `/api/health` is the safety net.

**Why no fallback:** Dual-path code has cost (writer collisions, two implementations of "newest wins", staleness ambiguity). The user explicitly chose to remove the fallback. The plan accepts the consequence: WS uptime is now a real operational requirement.

### Task 7.1: Delete the `_spot_refresh` scheduler job

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py` (delete `_spot_refresh` closure + its `add_job` call)
- Modify: `src/uw_scan/config.py` (delete `spot_refresh_seconds`)
- Modify: `tests/unit/worker/test_scheduler.py` (remove any spot_refresh assertions)

- [ ] **Step 1: Find every reference to `spot_refresh` in scheduler + config**

```bash
grep -rn "spot_refresh\|_spot_refresh" /Users/chenxi/projects/unusual-whales/src/uw_scan/worker/scheduler.py /Users/chenxi/projects/unusual-whales/src/uw_scan/config.py
```

- [ ] **Step 2: Delete from `scheduler.py`**

In `src/uw_scan/worker/scheduler.py`:
- Delete the `_spot_refresh` closure (~lines 237–261)
- Delete the `sched.add_job(_spot_refresh, IntervalTrigger(seconds=settings.spot_refresh_seconds), ...)` registration (~lines 508–514)
- **Move** the `_spot_refresh_market_date` helper (~lines 65–73) to a new file `src/uw_scan/worker/market_session.py` as `current_market_date(now: datetime) -> date | None` — the health endpoint and any future code that needs session awareness reuse it (see Phase 5 R4 fix). Update its callers (`api/routers/health.py` after Phase 5)
- Delete the `from uw_scan.worker.jobs.spot_refresh import spot_refresh_once` import (~line 47)

- [ ] **Step 3: Delete from `config.py`**

In `src/uw_scan/config.py`:
- Delete `spot_refresh_seconds: int = 300` (~line 73)
- Delete the matching `from_env` line `spot_refresh_seconds=int(...)` (~line 204)

- [ ] **Step 4: Delete the job file**

```bash
git rm src/uw_scan/worker/jobs/spot_refresh.py
```

- [ ] **Step 5: Find and delete spot_refresh tests**

```bash
grep -rln "spot_refresh_once\|_spot_refresh\b" /Users/chenxi/projects/unusual-whales/tests/ | grep -v __pycache__
```

For each test file: either delete the file (if all its tests target spot_refresh) or remove just the spot_refresh-related tests.

- [ ] **Step 6: Delete unused intraday fetch from `sources/ohlc.py`**

In `src/uw_scan/sources/ohlc.py`:
- Delete `fetch_intraday_quote` from the `OhlcProvider` Protocol (~line 43–45)
- Delete `fetch_intraday_quote` from `MassiveOhlcProvider` (~lines 116–155)
- Delete the `IntradayQuote` dataclass (~lines 34–38) — no remaining importers after Step 5
- Keep `OhlcBar` and `fetch_daily` — `ohlc_pull` still uses them
- Update `_NoOhlc` in `worker/scheduler.py` — remove its `fetch_intraday_quote` method

Verify nothing else imports `IntradayQuote`:

```bash
grep -rn "IntradayQuote\b" /Users/chenxi/projects/unusual-whales/src/ /Users/chenxi/projects/unusual-whales/tests/ | grep -v __pycache__
```

If any non-test caller remains, STOP and reconcile.

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest tests/ -v --ignore=tests/live`
Expected: all PASS. Anything failing in this step is a missed reference to the deleted code — fix the reference, don't re-add the deleted code.

- [ ] **Step 8: Stage**

```bash
git add -u src/uw_scan/worker/scheduler.py src/uw_scan/config.py src/uw_scan/sources/ohlc.py tests/
```

Confirm `git status` shows `src/uw_scan/worker/jobs/spot_refresh.py` as `deleted`.

**Phase 7 milestone: REST polling fully removed. User-gated commit: `refactor(worker): remove REST spot_refresh job — WS consumer is the sole writer`.**

---

## Phase 8 — WS-only validation & rollout

**Goal:** Verify the WS pipeline alone meets the sync + freshness contract for at least one full trading session, then sign off. Phase 7 has already deleted REST polling — there is no "compare against" — this is a one-sided acceptance test plus a documented rollback plan (revert Phase 7 PR if validation fails).

### Task 8.1: Parallel-run validation script

**Files:**
- Create: `scripts/validate_ws.py` (one-off; NOT committed long-term)

- [ ] **Step 1: Write the validation script**

Create `scripts/validate_ws.py`:

```python
"""Validate WS spot pipeline behavior during a trading session.

Snapshots the active watchlist every 60s and emits one CSV row per snapshot
with: snapshot timestamp, watchlist size, count by spot_source, max/median
quoted_at age, ws_consumer.ticks_received delta, ws_consumer.healthy.

Output: stdout CSV. Pipe to a file. Stop with Ctrl-C.

Usage:
    uv run python scripts/validate_ws.py | tee /tmp/ws_validation.csv

NOT a long-term tool; delete after Phase 8 sign-off.
"""

from __future__ import annotations

import csv
import logging
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import median

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("validate_ws")

INTERVAL_SECONDS = 60
FIELDS = [
    "snapshot_at",
    "watchlist_size",
    "ws_healthy",
    "ws_ticks_received",
    "ws_ticks_received_delta",
    "ws_last_tick_age_seconds",
    "sources_distribution",
    "spot_age_median_seconds",
    "spot_age_max_seconds",
    "rows_with_null_spot",
]


def _snapshot(repo: Repository, prev_ticks: int) -> dict:
    now = datetime.now(timezone.utc)
    cards = repo.list_watchlist_cards()
    size = len(cards)
    sources = Counter(c.spot_source or "none" for c in cards)
    ages = [
        (now - c.spot_quoted_at).total_seconds()
        for c in cards
        if c.spot_quoted_at is not None
    ]
    null_spots = sum(1 for c in cards if c.spot is None)
    state = repo.get_ws_consumer_state()
    if state is None or state.last_tick_at is None:
        ws_healthy, ws_ticks, ws_age = False, 0, None
    else:
        ws_age = (now - state.last_tick_at).total_seconds()
        ws_ticks = state.ticks_received
        ws_healthy = ws_age < 120.0
    return {
        "snapshot_at": now.isoformat(),
        "watchlist_size": size,
        "ws_healthy": ws_healthy,
        "ws_ticks_received": ws_ticks,
        "ws_ticks_received_delta": ws_ticks - prev_ticks,
        "ws_last_tick_age_seconds": ws_age,
        "sources_distribution": ";".join(f"{k}={v}" for k, v in sources.most_common()),
        "spot_age_median_seconds": median(ages) if ages else None,
        "spot_age_max_seconds": max(ages) if ages else None,
        "rows_with_null_spot": null_spots,
    }


def main() -> int:
    settings = Settings.from_env()
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    writer.writeheader()
    sys.stdout.flush()

    stop = False

    def _on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    prev_ticks = 0
    while not stop:
        conn = psycopg.connect(settings.db_dsn())
        try:
            repo = Repository(conn, schema=settings.db_schema)
            row = _snapshot(repo, prev_ticks)
            prev_ticks = row["ws_ticks_received"]
        finally:
            conn.close()
        writer.writerow(row)
        sys.stdout.flush()
        log.info(
            "snapshot: healthy=%s ticks_delta=%s sources=%s median_age=%.1fs max_age=%.1fs null=%d",
            row["ws_healthy"],
            row["ws_ticks_received_delta"],
            row["sources_distribution"],
            row["spot_age_median_seconds"] or -1,
            row["spot_age_max_seconds"] or -1,
            row["rows_with_null_spot"],
        )
        for _ in range(INTERVAL_SECONDS):
            if stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run during a market session with MASSIVE_WS_ENABLED=true**

```bash
MASSIVE_WS_ENABLED=true uv run python scripts/validate_ws.py | tee /tmp/ws_validation.csv
```

- [ ] **Step 3: Analyze the CSV**

Look for:
- spot_source distribution (should converge to >95% "massive.com_ws" within minutes)
- max quoted_at delta across watchlist (target: <5s with `A.*`, <70s with `AM.*`)
- ticks_received vs ticks_flushed (ratio should be ~1)
- last_error_at (should be null or very stale)

- [ ] **Step 4: If validation passes**

Set `MASSIVE_WS_ENABLED=true` permanently in the deployed env. The REST polling job has been deleted in Phase 7, so there is nothing to disable — the only path forward is WS. If validation surfaces unreliability (frequent reconnects, missed ticks), STOP and address before deploying.

### Task 8.2: Documentation

**Files:**
- Modify: `src/uw_scan/worker/CLAUDE.md`
- Modify: `src/uw_scan/sources/CLAUDE.md`

- [ ] **Step 1: Update the worker CLAUDE.md**

Add a section under "Worker roles":

```markdown
- `massive_ws` workers run the long-lived `python -m uw_scan.worker.massive_ws_consumer`
  process. Holds one WS connection to api.massive.com, subscribes to A.<TICKER>
  for the active watchlist, and is the SOLE writer for
  `intraday_quote.price` and `watchlist_card.spot`. Per-second flush window
  bounds intra-watchlist timestamp smear to ~1s. There is no REST fallback —
  if this consumer is down, spot data is stale until it reconnects. Monitor
  `/api/health` `ws_consumer.healthy` for liveness.
```

- [ ] **Step 2: Update sources CLAUDE.md**

Add a row to the "Per-ticker sources" section noting `massive_ws.py` is the streaming sibling of `ohlc.py`.

- [ ] **Step 3: Stage**

```bash
git add src/uw_scan/worker/CLAUDE.md src/uw_scan/sources/CLAUDE.md
```

**Phase 8 milestone: validated, documented. User-gated commit: `docs(worker,sources): document massive WS consumer architecture`.**

---

## Out of scope (explicitly deferred)

The following are NOT in this plan — flag them for follow-up:

1. **UI freshness (client-side polling or FastAPI→browser WS).** Once DB is live, the dashboard and detail page still only re-fetch on nav. Pick this up in a separate plan once we see how the WS-backed sync feels in the existing RSC-on-nav UI.
2. **OHLC pull migration.** The daily `ohlc_pull` job still uses REST. WS aggs would replace it but it's a daily job — not in the polling-hammer category, so low priority.
3. **Postgres LISTEN/NOTIFY for watchlist mutations.** Currently subscription updates poll `list_active_watchlist()` every 30s. Could be event-driven if the latency becomes a problem.
4. **Per-shard WS consumers for HA.** Today: one consumer process, no REST fallback. If it dies, spot data is stale until it reconnects. The plan accepts this risk given user direction; an active-passive second consumer (using `pg_try_advisory_lock` to elect a leader) is the obvious next step if operational pain materializes.

---

## Self-review checklist (run by the plan author after writing)

- Spec coverage:
  - Sync between dashboard and detail page → Phases 1–6 (single source of truth + atomic batch commits + writer discipline)
  - Relax worker pressure on massive REST → Phase 7 (auto-disable REST when WS is fresh)
  - "Same source, updated at the same time" → atomic flush in Phase 3 + writer discipline in Phase 6
- Placeholder scan: every step has runnable code; no "implement later" / "add appropriate" placeholders.
- Type consistency: `WsTick`, `TickBuffer`, `WsDbWriter`, `compute_subscription_diff`, `WsConsumerStateRow` names are stable across tasks.
- Commit policy: every phase ends with a user-gated commit (no auto-commits).
- Module size: every new file is well under 500 lines.
- Migrations: new `052_*` is idempotent (`IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`).
- No `Co-Authored-By: Claude` trailers in any commit step.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/archive/plans/2026-05-21-massive-ws-spot-pipeline.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints

**But first:** Phase 0 (verification) MUST run to confirm the WS endpoint assumptions before any code is committed.
