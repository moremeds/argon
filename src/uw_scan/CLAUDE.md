# src/uw_scan — Python package

Single namespace `uw_scan`. Everything publishable runs from here.

## Layout

```
uw_scan/
├── config.py            # Settings (pydantic-settings) — env → typed config
├── models.py            # Pydantic v2 row/response models (the API contract)
├── normalize.py         # raw UW JSON → typed models (NormalizationError on miss)
├── pipeline.py          # legacy scan pipeline (still used by full_scan job)
├── scan_universe.py     # watchlist → ticker list for the scanner
├── scoring.py           # numerical scoring used by the scan/cards
├── api/                 # FastAPI app + routers + UW HTTP client
├── cards/               # per-ticker analytical derivers (pure functions on rows)
├── reports/             # report assemblers (stitch DB rows → response models)
├── sources/             # external clients (uw.py, ohlc.py)
├── storage/             # Repository + SQL migrations
└── worker/              # APScheduler + job functions
```

## Conventions

- **Models** in `models.py` are the contract — FastAPI serializes them, frontend consumes them via generated types. Any new field surfaces in `web/lib/types.ts` after `npm run gen:types`.
- **`Decimal` over float** for prices, IV, RV, Greeks, scoring — see `_dec()` helpers in derivers.
- **Logging:** `logger = logging.getLogger(__name__)` per module. Exception handlers log with `repr(exc)` or `.exception(...)` (CI Guardrail 2 enforces this — `if any(...): raise` is also fine).
- **No fake cursors / mocked DB** in integration tests. Use `pytest-postgresql`.
- **NormalizationError** is raised loudly — no silent skipping of malformed UW payloads.

## When adding a new endpoint

1. Add the slug to `api/endpoints.py`
2. Add the typed model to `models.py`
3. Add the fetcher to `sources/uw.py` (writes audit + raw payload, returns model)
4. Add the persistence method to `storage/repository.py`
5. Wire into the relevant report assembler (`reports/*`) and/or scheduler job
6. Add unit test under `tests/unit/` and integration test under `tests/integration/`
