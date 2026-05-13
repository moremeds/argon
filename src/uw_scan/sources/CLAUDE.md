# src/uw_scan/sources — external data clients

The only place that talks to the outside world.

## Files

- `uw.py` — Unusual Whales fetchers. Every fetcher: call UW → write audit row → persist raw compressed payload → normalize → return typed model.
- `ohlc.py` — `MassiveOhlcProvider` (Polygon-shaped REST). Daily bars + intraday quote.

## Rules

- **Audit-first.** Persist the raw payload + audit row BEFORE returning. Crashes mid-pipeline must still leave a trace.
- **Raise `NormalizationError`** on malformed payloads. Never silently skip rows — the scanner depends on knowing if UW changed shape.
- **One fetcher per endpoint.** No generic "call this slug" helper — explicit functions surface signature drift at import time.
- **Massive can be absent.** If `MASSIVE_API_KEY` is missing the worker uses `_NoOhlc` (null object). Don't crash the scheduler on a missing key.
- **No retry logic here.** Backoff/retry lives in `api/client.py` (UW) — sources stay thin.
- **Never add a Yahoo Finance source.** Project-wide rule — yfinance is for radon/other projects, not this one.
