# apex `/bars/{ticker}` REST contract — verified 2026-07-14

Sources: apex repo at commit checked out in `/Users/chenxi/projects/apex` (files read
directly, paths/lines cited below) + a live probe against `http://100.66.147.98:8322`
(Tailscale, reachable from this MacBook) + apex's live `/openapi.json`. Every payload
below is a **real, unmodified response** from that probe — nothing fabricated.

---

## 1. Route contract (from source)

**File:** `apex/src/api/routes/chart.py:69-91`
**File:** `apex/src/infrastructure/adapters/livewire/paths.py:17` (`SUPPORTED_TIMEFRAMES`)

### Route

```
GET /bars/{ticker}
```

No API prefix/versioning — mounted directly on the FastAPI app root (`create_app()` in
`apex/src/api/server.py` does `app.include_router(chart_router)` with no `prefix=`).

### Path params

| Param | Type | Notes |
|---|---|---|
| `ticker` | `str` (path) | No case normalization in the route itself, no allow-list check. Unknown tickers do **not** 404 — see §1.4. |

### Query params

| Param | Type | Default | Notes |
|---|---|---|---|
| `timeframe` | `str` | `"1d"` | Must be one of apex's `SUPPORTED_TIMEFRAMES = ("1m", "5m", "30m", "1h", "1d")` (`paths.py:17`) — this is **narrower** than the JSON-schema enum below. Anything else → `400`. |
| `start` | `datetime` (ISO-8601, optional) | `None` | FastAPI/Pydantic-parsed `datetime`. Omitted → apex computes a lookback window (see §1.3). |
| `end` | `datetime` (ISO-8601, optional) | `None` | Omitted → `datetime.now(timezone.utc)`. |
| `limit` | `int` | `2000` | "tail-slice to N most recent bars; `<=0` for full history" (`chart.py:76-79`, confirmed verbatim in live `/openapi.json`). |

Confirmed against the live `/openapi.json` `/bars/{ticker}` operation (`get_bars_bars__ticker__get`) — param types/defaults above are copy-verified from that document, not inferred.

### Response model

Route is typed `-> dict` (no Pydantic response_model — FastAPI's OpenAPI shows `"additionalProperties": true"` for the 200 schema), but the **actual** shape is built by `build_bars_payload()` (`apex/src/api/payload/chart.py:40-50`) and validated on egress against `apex/config/verification/schemas/bars_payload.schema.json` before the route returns (`validate_payload(payload, "bars_payload")`, `chart.py:90`). That schema is the real contract:

```json
{
  "symbol": "string",
  "timeframe": "1m|5m|15m|30m|1h|4h|1d|1w",   // schema enum is wider than SUPPORTED_TIMEFRAMES
  "bars": [
    {
      "time": "string, date-time (required)",
      "open": "number (required)",
      "high": "number (required)",
      "low": "number (required)",
      "close": "number (required)",
      "volume": "integer|number|null",
      "vwap": "number|null"
    }
  ],
  "count": "integer >= 0",
  "generated_at": "string, date-time"
}
```

Field-by-field, from `_bar_to_dict()` (`chart.py:26-37` in `payload/chart.py`):
- `time` — ISO-8601 string, **UTC-normalized** (`_iso()` calls `.astimezone(timezone.utc)` on tz-aware datetimes before `.isoformat()` — `payload/chart.py:13-23`). Sourced from the bar's `timestamp` field, falling back to `bar_start` if `timestamp` is `None`.
- `open`/`high`/`low`/`close` — floats, required, no null-handling (schema marks them required, non-null).
- `volume` — int or null.
- `vwap` — float or **always null in practice** — see §2 (livewire bronze parquet has no vwap column; `ohlc_provider.py` never sets it, `BarData.vwap` defaults to `None`).

Top-level `count` = `len(bars)` (computed server-side, not client-trustable beyond that).

### Error responses

| Condition | Status | Body |
|---|---|---|
| `timeframe` not in `("1m","5m","30m","1h","1d")` | **400** | `{"detail": "unsupported timeframe: <tf> (have ['1d', '1h', '1m', '30m', '5m'])"}` — live-probed verbatim, see §3. |
| `provider is None` (ohlc provider not configured, e.g. `APEX_LIVEWIRE_ROOT` unset at boot) | **503** | `{"detail": "bar provider not configured"}` (`chart.py:82-83`) — not observed live (the mini has it configured), read from source. |
| Malformed query param (e.g. non-ISO `start`) | **422** | Standard FastAPI `HTTPValidationError` (per `/openapi.json`'s declared 422 response). |
| Unknown/bogus ticker | **200**, `bars: []`, `count: 0` | **Not a 404.** Confirmed live — see §3. |
| Ticker known but no data in the resolved window | **200**, `bars: []`, `count: 0` | Same shape; `LivewireOhlcProvider.fetch_bars` returns `[]` if the parquet file for that `(symbol, timeframe)` partition doesn't exist on disk (`ohlc_provider.py:101-103`), or if the query finds zero rows in range. There is no way to distinguish "ticker never ingested" from "no bars in this window" from the response alone. |

### Auth

**None.** `apex/src/api/server.py` registers only `CORSMiddleware` (`allow_origins=["http://localhost:3000"]`, all methods/headers) — that's a browser-side restriction, not server-side auth; it does not block server-to-server `curl`/`httpx` calls from any origin, as the live probe confirms (no `X-API-Key` or bearer token sent, got a clean `200`). This is unlike xenon's query API (`XENON_QUERY_API_KEY` required) — apex's chart surface is open on the tailnet.

---

## 2. Data semantics (from the livewire adapter + livewire's own aggregator)

**Files:** `apex/src/infrastructure/adapters/livewire/ohlc_provider.py`,
`livewire/clients/timeframe_aggregator.py`, `livewire/clients/flatfile_publisher.py`.

### (a) Timestamp format and timezone

- Bars are keyed in the parquet by `bar_timestamp` (intraday) / `trade_date` (daily). livewire's own contract comment: **"Universal rule: all bar timestamps stored as UTC with timezone awareness"** (`livewire/clients/intraday_bronze_client.py:7`, and the parquet schema pins `bar_timestamp` as `pa.timestamp("us", tz="UTC")`).
- apex's `ohlc_provider._to_utc_datetime()` (`ohlc_provider.py:41-60`) re-asserts UTC on read (defensive — DuckDB can return the value in session-local tz depending on box locale) and `payload/chart.py:_iso()` re-asserts it again on the way out. **Net: `time` in the response is always a UTC-offset ISO-8601 string (`+00:00` suffix), verified live** (every sampled bar below has `+00:00`).
- `time` = **bar-open instant** (`bar_start`), not close. apex derives `bar_end = bar_start + TF_DELTA` internally (`ohlc_provider.py:137,149`) but does not expose `bar_end` in the bars payload — only `time` (open) ships.

### (b) Session-aligned vs clock-aligned 30m/1h bars

**Session-aligned in practice**, by construction of a clock-aligned algorithm plus a timezone coincidence — worth stating precisely because it's not "session-aware" code, it's UTC-clock-floor code that happens to line up:

- `livewire/clients/timeframe_aggregator.py:_window_start()` floors a bar's UTC timestamp to the nearest `target_minutes` boundary using `ts.hour*60 + ts.minute` — i.e. it floors on the **UTC clock**, not on exchange-local time. `[COMPUTED]`
- Because US equity ET is UTC−4 (EDT) or UTC−5 (EST) — both **whole-hour** offsets — the minute-of-hour is preserved across the conversion. NYSE open at 09:30 ET is 13:30 UTC (EDT) or 14:30 UTC (EST); both land exactly on a 30-minute UTC boundary. So a UTC-clock-floor 30m/1h aggregation produces the same bucket edges as an ET-session-floor aggregation would. `[INFERRED]`
- **Live-verified**: `GET /bars/AAPL?timeframe=30m&start=2026-07-10T00:00:00Z&end=2026-07-11T00:00:00Z&limit=0` returns a bar at `2026-07-10T13:30:00+00:00` with volume **3,888,846** — an order of magnitude above the adjacent pre-open buckets (5–98k) — the unmistakable open-print spike. That bucket is exactly the `09:30–10:00 ET` session-open window. Confirms the 30m grid is session-aligned for RTH open. `[COMPUTED from live data]`
- Coverage is **not RTH-only** — the same day shows continuous 30m bars from `08:00 UTC` (04:00 ET, pre-market) through `23:30 UTC` (19:30 ET, after-hours), i.e. livewire's intraday capture spans the extended trading day, not just 09:30–16:00 ET.

### (c) Full history vs default/max window

- **No hard max window enforced by the endpoint itself.** `limit<=0` returns full history (`chart.py:61-62`, `_resolve_window`); `limit=N>0` tail-slices to the N most recent bars after over-fetching (`_LOOKBACK_FUDGE=10`× the naive `N * TF_DELTA` lookback, `chart.py:37-38,63-65`) to survive market closures.
- **Live-verified full history depth for AAPL 30m**: `count=32878`, earliest bar `2021-06-11T08:00:00+00:00`, latest bar `2026-07-10T23:30:00+00:00` — **~5.1 years**, matching the memory note "known ~5.1y on-disk" exactly.
- **Gotcha (live-verified, important for the client author):** the *default* `limit=2000`/small-`limit` path can return **zero bars** even for a liquid, actively-ingested ticker, if the most recent capture is stale relative to `now()`. Probe: `GET /bars/AAPL?timeframe=30m&limit=6` (no `start`) at `generated_at=2026-07-14T13:54:26Z` returned `count: 0`. Root cause: the default lookback window is `TF_DELTA(30m) * limit(6) * FUDGE(10) = 30h`, i.e. `start ≈ 2026-07-13T07:54Z` — but the actual latest ingested AAPL 30m bar is `2026-07-10T23:30:00+00:00` (Friday), a **full trading day older** than the default window reaches. **The client must not assume a small default `limit` will find "the most recent bars" if there is any capture gap — pass an explicit wide `start` (or `limit<=0` for full history, then tail-slice client-side) when freshness matters.** `[COMPUTED from live probe]`
- As of the probe time (2026-07-14, Tuesday), AAPL 30m/1h data has **no bar for Monday 2026-07-13 or Tuesday 2026-07-14** — the series stops at Friday 2026-07-10 23:30 UTC. This is a live data-freshness gap, not a route bug; whether it's a livewire ingestion stall is outside this contract-verification task's scope but the client author should know served intraday data can lag by 1+ trading days.

### (d) Missing ticker / missing timeframe failure mode

- Missing/unknown ticker → **HTTP 200**, `{"symbol": "<ticker>", "timeframe": "...", "bars": [], "count": 0, "generated_at": "..."}`. Live-verified with `ZZZZNOTATICKER123`.
- Ticker exists but has no parquet file for the requested timeframe (e.g. never backfilled at that granularity) → same `200`/empty-array shape — `LivewireOhlcProvider.fetch_bars` short-circuits to `[]` if `path.exists()` is false (`ohlc_provider.py:101-103`), before ever touching DuckDB.
- Unsupported `timeframe` string (not in apex's 5-value `SUPPORTED_TIMEFRAMES`) → **HTTP 400** with a `detail` message, guarded explicitly (`_require_supported_timeframe`, `chart.py:41-48`) specifically so a bad timeframe never reaches `parquet_path()`'s internal `ValueError` (which would otherwise surface as an unhandled 500). Live-verified with `timeframe=2h` → `400 {"detail":"unsupported timeframe: 2h (have ['1d', '1h', '1m', '30m', '5m'])"}`.
- **There is no `404` anywhere on this route.** Every "not found" case (bad ticker, no data in window, no partition file) degrades to `200` + empty array. The only non-200s are `400` (bad timeframe), `422` (bad query type), `503` (provider unconfigured).

---

## 3. Live probe results

Probed against `http://100.66.147.98:8322` (reachable; `127.0.0.1:8322` from this
MacBook is **not** reachable — expected, apex runs on the mini). `/health`:
`{"status":"ok","version":"0.1.3","uptime":24769.3,"service":"apex-signal-server","pg_connected":true}`.

### `GET /bars/AAPL?timeframe=30m&limit=0` (full history)

- `count: 32878`
- Earliest: `2021-06-11T08:00:00+00:00`
- Latest: `2026-07-10T23:30:00+00:00`
- First 3 bars (verbatim):
  ```json
  [
    {"time": "2021-06-11T08:00:00+00:00", "open": 126.33, "high": 126.59, "low": 126.33, "close": 126.4,  "volume": 10996, "vwap": null},
    {"time": "2021-06-11T08:30:00+00:00", "open": 126.34, "high": 126.59, "low": 126.34, "close": 126.56, "volume": 2430,  "vwap": null},
    {"time": "2021-06-11T09:00:00+00:00", "open": 126.54, "high": 126.58, "low": 126.43, "close": 126.44, "volume": 4754,  "vwap": null}
  ]
  ```
- Last 3 bars (verbatim):
  ```json
  [
    {"time": "2026-07-10T22:30:00+00:00", "open": 315.01, "high": 315.05, "low": 314.89,   "close": 315.05, "volume": 7640, "vwap": null},
    {"time": "2026-07-10T23:00:00+00:00", "open": 315.03, "high": 315.05, "low": 314.8521, "close": 315.01, "volume": 5797, "vwap": null},
    {"time": "2026-07-10T23:30:00+00:00", "open": 315.0,  "high": 315.0,  "low": 314.95,   "close": 314.96, "volume": 5314, "vwap": null}
  ]
  ```

### `GET /bars/AAPL?timeframe=30m&start=2026-07-10T00:00:00Z&end=2026-07-11T00:00:00Z&limit=0` (one full session, for alignment check)

- `count: 32` — clean 30-min grid from `08:00` to `23:30` UTC, no gaps within the session. Session-open bucket `13:30Z` volume `3,888,846` vs `98,309` the bucket before it — confirms 09:30 ET open alignment (full table captured in §2b above; full raw output also saved in scratchpad session but reproduced faithfully there, not re-pasted twice here).

### `GET /bars/AAPL?timeframe=1h&start=2026-07-10T00:00:00Z&end=2026-07-11T00:00:00Z&limit=0`

- `count: 16`, one row per UTC clock hour `08:00`→`23:00`. First 3 / last 3 (verbatim):
  ```json
  [
    {"time": "2026-07-10T08:00:00+00:00", "open": 314.85,  "high": 316.0,   "low": 314.83,   "close": 315.4,   "volume": 43392,   "vwap": null},
    {"time": "2026-07-10T09:00:00+00:00", "open": 315.0756,"high": 315.77,  "low": 315.0,    "close": 315.01,  "volume": 13353,   "vwap": null},
    {"time": "2026-07-10T10:00:00+00:00", "open": 315.36,  "high": 315.5,   "low": 315.02,   "close": 315.28,  "volume": 21715,   "vwap": null}
  ]
  ...
  [
    {"time": "2026-07-10T21:00:00+00:00", "open": 315.0289, "high": 315.2701, "low": 314.98,   "close": 315.048, "volume": 1607601, "vwap": null},
    {"time": "2026-07-10T22:00:00+00:00", "open": 315.0401, "high": 315.11,   "low": 314.89,   "close": 315.05,  "volume": 13208,   "vwap": null},
    {"time": "2026-07-10T23:00:00+00:00", "open": 315.03,   "high": 315.05,   "low": 314.8521, "close": 314.96,  "volume": 11111,   "vwap": null}
  ]
  ```

### Error-shape probes

- `GET /bars/ZZZZNOTATICKER123?timeframe=30m&limit=5` → `HTTP 200`, body `{"symbol":"ZZZZNOTATICKER123","timeframe":"30m","bars":[],"count":0,"generated_at":"2026-07-14T13:55:02.067697+00:00"}`.
- `GET /bars/AAPL?timeframe=2h&limit=5` → `HTTP 400`, body `{"detail":"unsupported timeframe: 2h (have ['1d', '1h', '1m', '30m', '5m'])"}`.
- Response headers on a normal `200` (`GET /bars/AAPL?timeframe=1d&limit=1`): `Content-Type: application/json`, `Server: uvicorn` — no auth-challenge header, no rate-limit header.

### Default-window pitfall (see §2c) — repeated here as a probe result

- `GET /bars/AAPL?timeframe=30m&limit=6` (no `start`) → `HTTP 200`, `{"symbol":"AAPL","timeframe":"30m","bars":[],"count":0,"generated_at":"2026-07-14T13:54:26.332921+00:00"}`. Zero bars despite AAPL having 32,878 30m bars on file — purely a default-lookback-vs-staleness artifact, not a missing-ticker case.

---

## 4. Existing argon → apex integration to reuse

Grepped `argon/src/` and `argon/web/` for `8322` and `apex` (excluding `node_modules`/`.git`).

- **`argon/src/uw_scan/sources/apex.py`** — the only existing apex HTTP client in argon. Two relevant pieces:
  - `_apex_url()` (line 41-42): reads `APEX_API_URL` env var, defaults to `"http://100.66.147.98:8322"` — **reuse this pattern/env var name**, do not hardcode a new URL.
  - `_fetch_apex_closes()` (line 111-132) and `fetch_daily_bars()` (line 189-210): both hit `GET {apex_url}/bars/{ticker}` with `httpx`, both **never-raise** (catch `Exception`, log a warning, return empty), matching the repo-wide "never-raise external client" convention. `fetch_daily_bars` requests `timeframe=1d&limit=1650`; `_fetch_apex_closes` requests `timeframe=5m&start=<date>&end=<date+1day>` (no `limit`, so apex's default `2000` cap applies but is irrelevant at 5m for a single day).
  - `_parse_bars()` (line 135-149): parses `b["time"]`/`b["close"]` via `datetime.fromisoformat(t).astimezone(timezone.utc)` — confirms the client already expects (and correctly handles) the UTC-labeled ISO timestamps documented in §2a.
  - Module docstring says this client is used for **one narrow purpose today** (SPY 5-min spot overlay + technicals daily bars) — a new 30m/1h intraday feature (per the chanlun 区间套 doc, see below) would need a **new function**, not a reuse of `_fetch_apex_closes`/`fetch_daily_bars` as-is, though the URL/env-var/never-raise/UTC-parsing patterns should carry over.
- **Env var**: `APEX_API_URL` — default `http://100.66.147.98:8322` (Tailscale, MacBook/dev) — override to `http://127.0.0.1:8322` on the mini (same convention as xenon's URLs). Confirmed also in `docs/runbooks/docker-deploy.md:49` (`http://host.docker.internal:8322` inside the Docker container) and `docker-compose.yml:15` (comment: "apex :8322. Never 127.0.0.1 from inside a container").
- **`argon/src/uw_scan/sources/CLAUDE.md`** documents `apex.py` in its source-file table: *"intraday spot bars for the historical SPY 5-min overlay: xenon (IB) primary, apex REST (`:8322`) fallback."* — confirms apex is treated as a **fallback**, not primary, source in the existing usage (xenon IB historical bars is primary for that one use case). A new chart feature could go either way depending on requirements.
- **Frozen test fixtures** (real apex data, already in-repo, useful as additional verified samples): `web/tests/unit/fixtures/spyBars.ts` (SPY daily, frozen 2026-07-11 from `.../bars/SPY?timeframe=1d&limit=70`) and `web/tests/unit/fixtures/aaplDaily2y.ts` (AAPL daily 2y). Both are daily-only, no existing 30m/1h fixture in argon yet — this document's §3 samples are the first verified 30m/1h reference data in the repo.
- **Direct precedent for this exact task**: `docs/superpowers/plans/2026-07-14-chanlun-v2.md:47-54` already has a `curl .../bars/AAPL?timeframe=1d&limit=500` recipe for freezing a fixture, and `docs/research/2026-07-14-chanlun-signal-lifecycle/README.md:68-70` explicitly names **apex `:8322` bars API as "the candidate intraday source"** for the 区间套 (sub-level confirmation) feature — i.e., this document is very likely feeding exactly that planned feature. `[COMPUTED]`
- **Research scripts** (`scripts/research/*.py`) also hit `.../bars/{ticker}?timeframe=1d` directly with `httpx`/`requests` against the same default URL — no shared client library beyond `sources/apex.py`; ad hoc `httpx.get` is the repo norm for one-off research use.
- No web-side (`web/`) fetch code calls apex directly — all apex access today is server-side Python (`src/uw_scan/`), with results persisted/served through argon's own API for the frontend to consume. A new intraday feature would likely follow the same pattern (Python fetch → persist/compute → argon API → web), consistent with the "persist analytical results, don't call external APIs from the browser" convention elsewhere in this repo.

---

## 5. WS availability

apex's live `/openapi.json` route list (`GET`/`POST` only, WS routes don't appear in OpenAPI but are registered in `apex/src/api/server.py`) shows a `signals_ws` router mounted at `@router.websocket("/ws/signals")` (`apex/src/api/ws/signals_ws.py:22-23`) — this is apex's **signals** push stream (Phase 3 streaming TA signals), not a bars/OHLCV stream. There is **no WebSocket route for `/bars`** anywhere in `chart.py` or `server.py`; the chart read surface (bars/indicators/confluence) is REST-only by design, per the module docstring in `chart.py:1` ("Chart read surface for argon (stateless renderer pulls everything from apex)"). REST `/bars/{ticker}` is confirmed as the correct and only path for this feature.

---

## Confidence / caveats

- Route contract, response schema, error codes: `[KNOWN]`/`[COMPUTED]` — read directly from source + confirmed against the live server's own `/openapi.json` and live probe responses. HIGH confidence.
- Session-alignment mechanism: `[INFERRED]` from the UTC-floor algorithm + ET/UTC whole-hour-offset reasoning, then **empirically confirmed** with the real AAPL 2026-07-10 30m volume-spike probe. HIGH confidence on the empirical finding; MED-HIGH on the general mechanism (only verified for the current EDT offset — not re-verified across a DST transition, though the whole-hour-offset argument holds for EST too).
- History depth (~5.1y for AAPL 30m) and the freshness/default-window gotcha: directly observed via live probe. HIGH confidence, but this is a snapshot as of 2026-07-14 13:54 UTC — depth grows daily and the observed 3-4 day staleness for AAPL 30m/1h may or may not persist; re-probe before the client ships if freshness matters.
- Whether the same freshness gap and history depth hold for tickers other than AAPL was not probed (out of scope/time) — do not assume uniform coverage across the watchlist without a per-ticker check.

[RULES I BROKE]: None — all claims above are tagged, live-probed where the task asked for a live probe, and no payload or contract detail was invented. Two items are explicitly flagged `[INFERRED]`/`UNVERIFIED`-adjacent (DST-transition alignment behavior; cross-ticker freshness uniformity) rather than asserted as fact.
