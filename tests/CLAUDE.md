# tests — pytest suite

## Layout

```
tests/
├── unit/           # pure-function tests, no DB, no network
├── integration/    # real Postgres via pytest-postgresql
│   ├── api/        # FastAPI endpoint tests
│   ├── cards/      # deriver integration
│   ├── reports/    # report assembly w/ DB
│   ├── sources/    # UW client w/ recorded fixtures
│   ├── storage/    # Repository against a real schema
│   └── worker/     # job runners end-to-end
└── live/           # hits the real UW API; needs UW_SCAN_API_KEY
    └── test_uw_smoke.py
```

Standalone module-level tests (`test_smile_trim.py`, `test_fill_rv_from_price.py`, etc.) live in the repo root next to `tests/` and are picked up via `pytest.ini_options.testpaths = ["tests"]` plus the `pythonpath = ["src", "."]` setting — but new tests should go inside the tree above.

## Rules

- **Run with `uv run pytest`.** Never bare `pytest`.
- **`live` tests are excluded by default.** Add the `@pytest.mark.live` marker; they only run when `UW_SCAN_API_KEY` is set and the marker is selected.
- **No mocked DB / fake cursors.** Integration tests use `pytest-postgresql` to spin up a real Postgres; the project policy explicitly bans `unittest.mock` of cursors.
- **Migrations run once per pytest session.** `tests/integration/conftest.py` applies every migration in-process via `uw_scan.storage.migrate_runner.apply_migrations` exactly once per session; the `seeded_db_empty_cards` fixture then restores the post-migration baseline per test by `TRUNCATE ... CASCADE` + `COPY`. Migrations must stay idempotent (covered in `src/uw_scan/storage/CLAUDE.md`).
- **`asyncio_mode = "auto"`** is enabled via `pytest-asyncio` — bare `async def test_…` works.
- **Fixture data** lives next to the test that uses it. Don't add a global fixtures dump.
- **CI Guardrail 2** scans every `except` block for `.exception(...)`, `repr(exc)`, `traceback`, or `raise`. If a test introduces a try/except handler in production code, satisfy the guardrail (usually `log.debug(..., repr(exc))`).

## Web tests

Frontend tests live under `web/tests/` (vitest unit + playwright e2e), not here.
