# Repository Guidelines

## Project Structure & Module Organization

This repository currently contains planning and handover documentation for a Streamlit-based Unusual Whales opportunity scanner. Keep source work organized around the planned structure:

- `docs/`: handover, design specs, and implementation plans.
- `docs/superpowers/specs/`: validated product and architecture specs.
- `docs/superpowers/plans/`: step-by-step implementation plans.
- `src/uw_scan/`: future Python package code.
- `app/`: future Streamlit entrypoint, expected at `app/streamlit_app.py`.
- `tests/`: future unit and integration tests.

Do not add monolithic top-level scripts. New runtime code should live in package modules under `src/uw_scan/`.

## Build, Test, and Development Commands

Use `uv` for dependency management and execution.

- `uv sync --extra postgres`: install project dependencies, including Postgres support once `pyproject.toml` exists.
- `uv run pytest`: run the Python test suite.
- `uv run streamlit run app/streamlit_app.py`: start the local scanner UI.
- `uv run playwright install chromium`: install Chromium for browser-level UI verification.
- `git diff --check HEAD`: check staged and unstaged changes for whitespace errors.

If a command is not yet available, add the required project metadata or tests as part of the relevant implementation plan.

## Coding Style & Naming Conventions

Follow Python conventions with typed, focused modules. Use snake_case for files, functions, variables, and database table names; use PascalCase for classes and dataclasses. Keep configuration in environment variables, not hardcoded constants. Prefer small modules for API clients, persistence, scoring, and UI state rather than broad utility files.

## Testing Guidelines

Use `pytest` for unit and integration coverage. Place tests in `tests/` with names like `test_config.py` or `test_tradingview_adapter.py`. For UI work, run Streamlit locally and verify key flows with Browser Use or Playwright. Persistence changes should include tests for normalized relational writes against the `uw_scan` schema.

## Commit & Pull Request Guidelines

Recent commits use short imperative summaries, for example `Add UW scan handover` and `Require uv and browser UI verification`. Continue that style: concise, present-tense, and focused on one change.

Pull requests should include a summary, verification commands run, linked issue or plan document, and screenshots for Streamlit UI changes. Mention any skipped verification with the reason.

## Security & Configuration Tips

Never commit API tokens or secrets. Use `UW_SCAN_API_KEY=...` in the environment. Local Postgres work should target database `option_wizard` and schema `uw_scan`. Raw payload storage is only for compressed audit/replay data; queryable data should be normalized relational tables.
