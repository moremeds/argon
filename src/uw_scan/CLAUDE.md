# src/uw_scan — Python package

Single namespace `uw_scan`. Everything publishable runs from here.

## Layout

```
uw_scan/
├── config.py            # plain pydantic BaseModel Settings, populated via Settings.from_env() — env → typed config
├── models/              # Pydantic v2 row/response contracts, split by domain
├── normalize.py         # raw UW JSON → typed models (NormalizationError on miss)
├── pipeline.py          # legacy scan pipeline (still used by full_scan job)
├── scoring.py           # numerical scoring used only by the legacy pipeline.py scan path
├── alerts.py            # one-webhook ops alert sink (Discord/Pushover-compatible JSON POST)
├── macro_evidence.py    # canonical content identities for immutable macro evidence
├── pipeline_replay_policy.py  # which datasets may be re-fetched under a historical market_date
├── watchlist_taxonomy.py      # watchlist industry-chain taxonomy — the single source of truth
├── version.py           # single source of truth for the running release version
├── api/                 # FastAPI app + routers + UW HTTP client
├── backtest/            # walk-forward backtest harness (own CLAUDE.md)
├── benchmark/           # pipeline benchmark harness
├── cards/               # per-ticker analytical derivers (pure functions on rows)
├── chanlun/             # 缠论 (Chanlun) stroke/中枢/买卖点 port — field-for-field port of web/lib/chanlun.ts
├── density/             # GJR-GARCH bootstrap density cone, vendored verbatim from signal-lab
├── fundamentals/        # fundamental PM lane — statement normalization → scoring → valuation → card
├── macro/               # cross-domain point-in-time macro assemblers (MC0–MC3 domain states)
├── rates/               # US-rates domain (curve, policy, positioning, supply)
├── reports/             # report assemblers (stitch DB rows → response models)
├── scanner/             # detector/ranking/discovery pipeline (feeds /scanner)
├── scanners/            # market-wide indicator scanners (cri, vcg, gex, grg, canary, …)
├── sources/             # external clients (uw.py, ohlc.py, xenon_*, lake, gold, rates)
├── storage/             # Repository + standalone repositories + SQL migrations
└── worker/              # APScheduler + job functions
```

## Conventions

- **Models** in `models/` are the contract — FastAPI serializes them, frontend consumes them via generated types. Keep `models/__init__.py` as the public export surface and put implementations in domain modules. Any new field surfaces in `web/lib/types.ts` after `npm run gen:types`.
- **Model moves must be schema-neutral unless explicitly scoped otherwise.** Preserve `from uw_scan.models import X`, update `__all__`, avoid importing from `uw_scan.models` or `from . import X` inside domain modules, and preserve public Pydantic model `__module__` metadata so OpenAPI component names do not drift. Verify with `tests/unit/test_models_exports.py`, the OpenAPI snapshot, and a field-surface comparison for large moves.
- **`Decimal` over float** for prices, IV, RV, Greeks, scoring — see `_dec()` helpers in derivers.
- **Logging:** `logger = logging.getLogger(__name__)` per module. Exception handlers log with `repr(exc)` or `.exception(...)` (CI Guardrail 2 enforces this — `if any(...): raise` is also fine).
- **No fake cursors / mocked DB** in integration tests. Use `pytest-postgresql`.
- **NormalizationError** is raised loudly — no silent skipping of malformed UW payloads.

## When adding a new endpoint

1. Add the slug to `api/endpoints.py`
2. Add the typed model to the relevant `models/` domain module and re-export it from `models/__init__.py`
3. Add the fetcher to `sources/uw.py` (writes audit + raw payload, returns model)
4. Add the persistence method to the appropriate domain storage mixin or focused storage module; keep `storage/repository.py` as the aggregate compatibility shell
5. Wire into the relevant report assembler (`reports/*`) and/or scheduler job
6. Add unit test under `tests/unit/` and integration test under `tests/integration/`
