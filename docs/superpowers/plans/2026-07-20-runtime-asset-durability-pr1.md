# Runtime Asset Durability (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make argon's container carry every asset it reads at runtime, and make a configured-but-absent data source crash instead of silently returning empty.

**Architecture:** Move the two runtime files out of `docs/` into the Python package (loaded via `importlib.resources`), mirror the mini's lake mount into the committed compose file, convert silent empty-returns into raises at the lake boundary, and add a CI guard so the class of bug cannot come back. No new services, no schema changes.

**Tech Stack:** Python 3.13 / uv, setuptools packaging, FastAPI, pytest, Docker Compose (colima), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md`

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`.
- **Never commit without an explicit user request.** This plan's commit steps are pre-authorised by plan approval; nothing else is.
- **Branch is `fix/runtime-asset-durability`**, already created, already holding the spec commit `3df422f`. Do not create another branch. Do not push to `main`.
- **No `Co-Authored-By` trailers** in any commit message.
- **CHANGELOG rides this PR** — the `[Unreleased]` entry is Task 9, before the PR opens.
- **Module size budget** — target <500 lines per Python file.
- **Exception handlers must log with `repr(exc)` / `.exception(...)` or re-raise** (CI Guardrail 2, `scripts/_lint_except.py`).
- **PR2 (frontend staleness badges) is NOT in this plan.** It gets its own plan file. Do not add `web/` changes here.

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `src/uw_scan/cards/data/canary-calibration-v1.json` | move from `docs/research/regime/` | Frozen canary thresholds, loaded at runtime |
| `src/uw_scan/cards/data/canary-calibration-v2.json` | move from `docs/research/regime/` | v2 thresholds (research comparison only) |
| `src/uw_scan/cards/data/guidance.md` | move from `docs/research/regime/` | CRI guidance rules, parsed at runtime |
| `pyproject.toml` | modify | **Declare the above as package data — without this the move is a no-op** |
| `src/uw_scan/cards/canary_calibration.py:16-22` | modify | Resolve calibration via `importlib.resources` |
| `src/uw_scan/api/routers/regime_validation.py:60-88,158-166` | modify | Read guidance from package data; delete `_safe_doc_path` + `_DOCS_REGIME` |
| `src/uw_scan/reports/regime_canary_v1_v2_compare.py:36-38` | modify | Repoint research paths |
| `src/uw_scan/sources/lake.py:88-109` | modify | Absent lake **root** raises; absent **symbol** still returns `[]` |
| `src/uw_scan/sources/lake_resolver.py:104-131` | modify | Raise if R2 config is present (retired backend) |
| `src/uw_scan/config.py` | modify | New `market_warehouse_lake_root` setting (owns the last home-dir default) |
| `src/uw_scan/reports/vrp_macro_drawdown.py:67-73` | modify | Read the root from `Settings` instead of a bare `os.environ` + home default |
| `scripts/check_runtime_assets.py` | create | CI guard: no `Path.home()` outside `config.py`, no runtime reads under `docs/` |
| `.github/workflows/ci.yml:45-47` | modify | Wire the guard in |
| `docker-compose.yml:31-37` | modify | Lake mount on `x-common` |
| `.env.example` | modify | Document `LAKE_*` + `MARKET_WAREHOUSE_LAKE` |
| `src/uw_scan/reports/data_gap_healer.py` | modify | `vol_index_daily` registry entry |
| `src/uw_scan/worker/scheduler.py:164` | modify | Recovery lookback 7 → 30 |
| `tests/unit/test_runtime_assets.py` | create | Package-data resolution tests |
| `tests/unit/test_lake_reader.py` | modify | Absent-root-raises test |
| `docs/research/regime/README.md` | modify | Pointer to the moved files |
| `CHANGELOG.md` | modify | `[Unreleased]` entry |

---

### Task 1: Ship the canary calibration as package data

This task is first because it carries the `pyproject.toml` packaging config that every later asset move depends on.

**Files:**
- Create: `src/uw_scan/cards/data/canary-calibration-v1.json` (git mv)
- Create: `src/uw_scan/cards/data/canary-calibration-v2.json` (git mv)
- Modify: `pyproject.toml`
- Modify: `src/uw_scan/cards/canary_calibration.py:16-22`
- Modify: `src/uw_scan/reports/regime_canary_v1_v2_compare.py:36-38`
- Test: `tests/unit/test_runtime_assets.py`

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `uw_scan.cards.canary_calibration.DEFAULT_PATH` (a `Traversable`), and the `[tool.setuptools.package-data]` block that Task 2 also relies on. `load_calibration(path: Traversable | Path = DEFAULT_PATH) -> Calibration` keeps its existing signature shape so test call sites are unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_runtime_assets.py`:

```python
"""Runtime assets must resolve from the installed package, not the repo tree.

Regression guard for the 2026-07-08 Docker cutover: `docs/` is not copied into
the image, so anything read from there at runtime vanished in the container
while every checkout-based test stayed green.
"""

from __future__ import annotations

from uw_scan.cards.canary_calibration import COMPOSITE_VERSION, DEFAULT_PATH, load_calibration


def test_calibration_default_path_is_inside_the_package() -> None:
    resolved = str(DEFAULT_PATH)
    assert "/docs/" not in resolved, f"calibration still resolves through docs/: {resolved}"
    assert resolved.endswith(
        f"uw_scan/cards/data/canary-calibration-v{COMPOSITE_VERSION}.json"
    ), resolved


def test_calibration_loads_from_package_data() -> None:
    cal = load_calibration()
    assert cal.composite_version == COMPOSITE_VERSION
    assert cal.score_form == "linear"
    assert cal.vix_spike_revert.max_points > 0
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/unit/test_runtime_assets.py -v`
Expected: FAIL — `test_calibration_default_path_is_inside_the_package` asserts on a path still containing `docs`.

- [ ] **Step 3: Move the files**

```bash
mkdir -p src/uw_scan/cards/data
git mv docs/research/regime/canary-calibration-v1.json src/uw_scan/cards/data/
git mv docs/research/regime/canary-calibration-v2.json src/uw_scan/cards/data/
```

- [ ] **Step 4: Declare the package data**

The build backend is `setuptools.build_meta` and the only packaging config is `[tool.setuptools.packages.find] where = ["src"]`. **Non-`.py` files under `src/` do not ship by default.** Add immediately after the `[tool.setuptools.packages.find]` block in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"uw_scan.cards" = ["data/*.json", "data/*.md"]
```

Skipping this reproduces the original bug one layer deeper: the files are in `src/`, tests pass from the checkout, and the wheel still ships without them.

- [ ] **Step 5: Repoint the loader**

In `src/uw_scan/cards/canary_calibration.py`, replace lines 6-22 (the imports and `DEFAULT_PATH`) with:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Literal

COMPOSITE_VERSION = 1

# Package data — ships inside the wheel/image. Do NOT move this back under
# docs/: docker/app.Dockerfile does not COPY docs/, which silently broke the
# canary for 13 days after the 2026-07-08 cutover.
DEFAULT_PATH: Traversable = (
    files("uw_scan.cards") / "data" / f"canary-calibration-v{COMPOSITE_VERSION}.json"
)
```

Then widen the loader signature (currently `def load_calibration(path: Path = DEFAULT_PATH) -> Calibration:`):

```python
def load_calibration(path: Traversable | Path = DEFAULT_PATH) -> Calibration:
```

The body is unchanged — `Traversable` and `Path` both provide `.read_text()`, so existing tests that pass a `tmp_path` file keep working.

- [ ] **Step 6: Repoint the research comparison module**

In `src/uw_scan/reports/regime_canary_v1_v2_compare.py`, replace lines 36-38:

```python
_CAL_DIR = files("uw_scan.cards") / "data"
V1_CAL_PATH = _CAL_DIR / "canary-calibration-v1.json"
V2_CAL_PATH = _CAL_DIR / "canary-calibration-v2.json"
```

Add `from importlib.resources import files` to that module's imports. If `REPO_ROOT` becomes unused, delete it and let ruff confirm.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_runtime_assets.py tests/unit/ -k "canary" -v`
Expected: PASS.

- [ ] **Step 8: Confirm the wheel actually contains the files**

This is the step that proves Step 4 worked:

```bash
uv build --wheel 2>&1 | tail -2
python3 -c "
import zipfile, glob
w = sorted(glob.glob('dist/*.whl'))[-1]
names = [n for n in zipfile.ZipFile(w).namelist() if 'cards/data' in n]
print('\n'.join(names) or 'MISSING — package-data config is wrong')
assert names, 'calibration JSON not in wheel'
"
```
Expected: both `canary-calibration-v{1,2}.json` listed under `uw_scan/cards/data/`.

- [ ] **Step 9: Commit**

```bash
rm -rf dist/
git add pyproject.toml src/uw_scan/cards/ src/uw_scan/reports/regime_canary_v1_v2_compare.py tests/unit/test_runtime_assets.py
git commit -m "fix(canary): ship calibration JSON as package data

docker/app.Dockerfile never COPYs docs/, so load_calibration() raised
FileNotFoundError on every canary run in the container from the 2026-07-08
cutover onward. Moves the frozen thresholds into uw_scan.cards.data and
resolves them via importlib.resources.

Adds [tool.setuptools.package-data] — without it non-.py files under src/
do not ship in the wheel and the move is a silent no-op."
```

---

### Task 2: Ship guidance.md as package data and delete the traversal guards

**Files:**
- Create: `src/uw_scan/cards/data/guidance.md` (git mv)
- Modify: `src/uw_scan/api/routers/regime_validation.py:60-88,158-166`
- Test: `tests/unit/test_runtime_assets.py` (append)

**Interfaces:**
- Consumes: the `[tool.setuptools.package-data]` block from Task 1 (its `data/*.md` glob already covers this file).
- Produces: `_parse_guidance_md() -> list[dict[str, Any]]`, unchanged signature. `_safe_doc_path` and `_DOCS_REGIME` cease to exist — no other module may reference them.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_runtime_assets.py`:

```python
def test_guidance_rules_parse_from_package_data() -> None:
    from uw_scan.api.routers.regime_validation import _parse_guidance_md

    rules = _parse_guidance_md()
    assert rules, "guidance.md produced no rules — is it shipping as package data?"
    for rule in rules:
        assert rule["state"]
        assert rule["condition"]


def test_regime_validation_has_no_docs_path() -> None:
    import uw_scan.api.routers.regime_validation as mod

    assert not hasattr(mod, "_DOCS_REGIME"), "docs/-relative path still present"
    assert not hasattr(mod, "_safe_doc_path"), "traversal guard should be deleted"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/unit/test_runtime_assets.py -k guidance -v`
Expected: FAIL on `test_regime_validation_has_no_docs_path` (`_DOCS_REGIME` still exists).

- [ ] **Step 3: Move the file**

```bash
git mv docs/research/regime/guidance.md src/uw_scan/cards/data/
```

- [ ] **Step 4: Replace the path machinery**

In `src/uw_scan/api/routers/regime_validation.py`, **delete lines 60-88 entirely** (the `_DOCS_REGIME` constant and the whole `_safe_doc_path` function — four path-traversal guards whose only call site is `_safe_doc_path("guidance.md")`). Replace with:

```python
# Package data — ships inside the wheel/image. See
# docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md.
_GUIDANCE_MD = files("uw_scan.cards") / "data" / "guidance.md"
```

Add `from importlib.resources import files` to the imports.

- [ ] **Step 5: Simplify the parser**

Replace the head of `_parse_guidance_md` (lines 158-166) so it reads:

```python
def _parse_guidance_md() -> list[dict[str, Any]]:
    """Split guidance.md on `---` separators; load YAML frontmatter + body."""
    text = _GUIDANCE_MD.read_text()
    chunks = [c.strip() for c in text.split("\n---\n")]
```

The `try/except HTTPException` wrapper goes away with `_safe_doc_path`. The rest of the function body is unchanged.

- [ ] **Step 6: Clean up now-unused imports**

Run: `uv run ruff check src/uw_scan/api/routers/regime_validation.py`
If `Path` (line 23) is now unused, delete that import. Re-run until clean.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/unit/test_runtime_assets.py -v && uv run pytest tests/unit/ -k regime_validation -v`
Expected: PASS.

- [ ] **Step 8: Leave a pointer so the research trail survives the move**

Both asset moves are now complete, so `docs/research/regime/` no longer holds
the files its own README describes. Add to `docs/research/regime/README.md`,
directly under the heading:

```markdown
> **Moved 2026-07-20.** `canary-calibration-v{1,2}.json` and `guidance.md` are
> loaded at runtime and now live in `src/uw_scan/cards/data/`. They were moved
> out of `docs/` because `docker/app.Dockerfile` does not copy `docs/`, so they
> vanished from the container after the 2026-07-08 Docker cutover — breaking the
> canary and `GET /api/regime/guidance` for 12 days. Do not move them back; see
> `docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md`.
```

Then fix the two stale references in that file's body (line ~16 and the
"Runtime calibration (loaded by app)" table row at line ~116) to point at the
new location.

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/cards/data/guidance.md src/uw_scan/api/routers/regime_validation.py tests/unit/test_runtime_assets.py docs/research/regime/README.md
git commit -m "fix(regime): ship guidance.md as package data

GET /api/regime/guidance has returned HTTP 500 in prod since the 2026-07-08
cutover because docs/ is not in the image. Moves the file into
uw_scan.cards.data and deletes _safe_doc_path/_DOCS_REGIME — 25 lines of
path-traversal guards that existed to serve one hardcoded filename."
```

---

### Task 3: An absent lake root raises instead of returning empty

**Files:**
- Modify: `src/uw_scan/sources/lake.py:88-109`
- Test: `tests/unit/test_lake_reader.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `_list_local` / `_read_local` raise `FileNotFoundError` when `root` does not exist. `read_vol_index_parquet(root, symbol)` still returns `[]` when the **root exists** but the symbol is absent — `tests/unit/test_lake_reader.py:90` depends on this and must stay green.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_lake_reader.py`:

```python
def test_missing_lake_root_raises(tmp_path: Path) -> None:
    """A configured-but-absent root is a misconfiguration, not 'no data'.

    Returning [] here is what turned the 2026-07-08 missing container mount
    into 13 days of silent staleness instead of a first-run crash.
    """
    absent = tmp_path / "not-mounted"
    with pytest.raises(FileNotFoundError, match="lake root does not exist"):
        read_vol_index_parquet(absent, "VIX")
    with pytest.raises(FileNotFoundError, match="lake root does not exist"):
        list_vol_index_symbols(absent)


def test_present_root_missing_symbol_still_returns_empty(tmp_path: Path) -> None:
    """A symbol may legitimately not exist under a healthy root."""
    assert read_vol_index_parquet(tmp_path, "NONEXISTENT") == []
```

Ensure `import pytest` is present at the top of that file.

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_lake_reader.py -v`
Expected: FAIL — `test_missing_lake_root_raises` gets `[]` instead of an exception.

- [ ] **Step 3: Implement**

In `src/uw_scan/sources/lake.py`, add above `_list_local`:

```python
def _require_root(root: Path) -> None:
    """Absent root = misconfiguration. Raise; never degrade to an empty read.

    Returning [] for a missing root makes a dropped container mount
    indistinguishable from "the upstream produced no new rows" — the exact
    ambiguity that hid the 2026-07-08 lake outage for 13 days.
    """
    if not root.exists():
        raise FileNotFoundError(
            f"lake root does not exist: {root}. Check the container volume "
            f"mount and LAKE_VOL_INDEX_ROOT / LAKE_CREDIT_ETF_ROOT."
        )
```

Then replace the guard in `_list_local` (lines 89-90):

```python
def _list_local(root: Path) -> list[str]:
    _require_root(root)
    out: list[str] = []
```

And add to the top of `_read_local` (before line 105):

```python
def _read_local(root: Path, symbol: str, *, since: date | None) -> list[dict]:
    _require_root(root)
    path = root / f"symbol={symbol}" / VOL_INDEX_FILENAME
    if not path.exists():
        return []
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_lake_reader.py -v`
Expected: PASS, including the pre-existing `test_list_vol_index_symbols` and the `"NONEXISTENT"` assertion at line 90 (which passes `tmp_path`, an existing directory).

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/lake.py tests/unit/test_lake_reader.py
git commit -m "fix(lake): raise on an absent lake root instead of returning []

A missing root was indistinguishable from 'no new rows', which is why the
severed container mount produced 13 days of silent staleness rather than a
first-run crash. Absent symbols under a healthy root still return []."
```

---

### Task 4: Guard against silent R2 resurrection

**Files:**
- Modify: `src/uw_scan/sources/lake_resolver.py:104-131`
- Test: `tests/unit/test_lake_resolver.py` (create if absent)

**Interfaces:**
- Consumes: nothing.
- Produces: `resolve_lake_root(settings, asset_class=...) -> LakeRoot` now always returns a `kind="local"` root, or raises `RuntimeError` when R2 settings are present.

**Context:** R2's producer push died 2026-05-21 and the backend is retired. While the s3 branch can still be selected, any `.env` carrying `R2_*` silently reroutes every lake read to a dead bucket — the exact mechanism behind this incident. Per the spec we are **not** deleting the ~150-line s3 branch, because the planned apex migration is expected to delete `lake_resolver.py` wholesale.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_lake_resolver.py`:

```python
"""R2 is retired; resolving to it must be loud, not silent."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.sources.lake_resolver import resolve_lake_root


def _settings(tmp_path: Path, **overrides: object) -> Settings:
    base: dict[str, object] = {
        "lake_vol_index_root": tmp_path / "volatility",
        "lake_credit_etf_root": tmp_path / "equity",
    }
    base.update(overrides)
    return Settings.model_construct(**base)


def test_resolves_local_when_no_r2_configured(tmp_path: Path) -> None:
    root = resolve_lake_root(_settings(tmp_path), asset_class="volatility")
    assert root.kind == "local"
    assert root.local_path == tmp_path / "volatility"


def test_r2_configuration_raises(tmp_path: Path) -> None:
    s = _settings(
        tmp_path,
        r2_account_id="acct",
        r2_bucket="market-data",
        r2_access_key_id=SecretStr("k"),
        r2_secret_access_key=SecretStr("s"),
    )
    with pytest.raises(RuntimeError, match="R2 .* retired"):
        resolve_lake_root(s, asset_class="volatility")
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_lake_resolver.py -v`
Expected: FAIL — `test_r2_configuration_raises` gets an s3 `LakeRoot` back instead of a raise.

- [ ] **Step 3: Implement**

In `src/uw_scan/sources/lake_resolver.py`, replace lines 112-131 (from `if not _r2_fully_configured(settings):` through `return r2_root`) with:

```python
    if _r2_fully_configured(settings):
        raise RuntimeError(
            "R2 lake settings are present, but R2 is retired — its producer "
            "push has been dead since 2026-05-21 and reading it silently "
            "serves stale data. Remove R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / "
            "R2_SECRET_ACCESS_KEY / R2_BUCKET from the environment; the "
            "mounted local lake is the only supported source."
        )
    return local_root
```

`_build_r2_root` and `_probe_max_trade_date` become unreachable. Leave them — the apex migration deletes this module wholesale, so removing them now is churn on code already scheduled to die. Add a one-line comment above `_build_r2_root`:

```python
# Unreachable since the 2026-07-20 R2 guard above. Retained deliberately —
# the planned apex migration removes this module entirely.
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_lake_resolver.py -v && uv run pytest tests/unit/ -k lake -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/lake_resolver.py tests/unit/test_lake_resolver.py
git commit -m "fix(lake): raise when retired R2 settings are present

R2's producer died 2026-05-21. While the s3 branch was selectable, any .env
carrying R2_* silently rerouted every lake read to a dead bucket. The s3
code stays (the apex migration deletes this module) but is now unreachable."
```

---

### Task 5: Move the last home-dir default into Settings

**Files:**
- Modify: `src/uw_scan/config.py`
- Modify: `src/uw_scan/reports/vrp_macro_drawdown.py:67-73`
- Test: `tests/unit/test_runtime_assets.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.market_warehouse_lake_root: Path` (env `MARKET_WAREHOUSE_LAKE`, default `Path.home() / "market-warehouse" / "data-lake"`). `vrp_macro_drawdown._default_lake_root() -> Path` now reads it. This is the last `Path.home()` outside `config.py`, which Task 6's guard depends on.

**Context:** `_default_lake_root` reads `MARKET_WAREHOUSE_LAKE` with a bare `os.environ.get` and its own home-dir fallback. In the container that resolves to `/root/market-warehouse/data-lake`, which does not exist. `load_index_vol` is imported by `worker/jobs/vrp_macro_signal.py` — a scheduled job — so this has been logging `vrp_macro_signal QQQ: skipped — FileNotFoundError(...)` every run since the cutover.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_runtime_assets.py`:

```python
def test_drawdown_lake_root_comes_from_settings(monkeypatch) -> None:
    """The last home-dir default must live in config.py, not a bare os.environ."""
    from uw_scan.reports import vrp_macro_drawdown

    monkeypatch.setenv("MARKET_WAREHOUSE_LAKE", "/lake")
    assert str(vrp_macro_drawdown._default_lake_root()) == "/lake"


def test_no_home_dir_defaults_outside_config() -> None:
    import subprocess

    out = subprocess.run(
        ["uv", "run", "python", "scripts/check_runtime_assets.py"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
```

The second test will fail until Task 6 creates the script — that is expected and intentional; it is the handoff between the two tasks.

- [ ] **Step 2: Run to confirm the first test fails**

Run: `uv run pytest tests/unit/test_runtime_assets.py -k drawdown -v`
Expected: PASS — the current `os.environ.get("MARKET_WAREHOUSE_LAKE", ...)` already honours the env var, so this test passes before the change and guards against regressing it during Step 4. The behaviour that must change is the **fallback**, which Step 3 moves into `Settings`; the guard in Task 6 is what actually enforces it.

- [ ] **Step 3: Add the setting**

In `src/uw_scan/config.py`, immediately after the `lake_credit_etf_root` field (around line 347), add:

```python
    # Root of the whole market-warehouse lake (parent of bronze/silver/gold).
    # Distinct from the two asset-class roots above, which point at specific
    # bronze partitions. Read by reports/vrp_macro_drawdown.py.
    market_warehouse_lake_root: Path = Field(
        default=Path.home() / "market-warehouse" / "data-lake",
        description=(
            "Root of the market-warehouse parquet lake (contains bronze/). "
            "Set MARKET_WAREHOUSE_LAKE=/lake in containers."
        ),
    )
```

And in `Settings.from_env()`, alongside the existing `lake_vol_index_root` / `lake_credit_etf_root` wiring (around line 813-820):

```python
            market_warehouse_lake_root=(
                Path(_mw_lake)
                if (_mw_lake := os.environ.get("MARKET_WAREHOUSE_LAKE", "").strip())
                else Path.home() / "market-warehouse" / "data-lake"
            ),
```

- [ ] **Step 4: Repoint the consumer**

In `src/uw_scan/reports/vrp_macro_drawdown.py`, replace `_default_lake_root` (lines 67-73):

```python
def _default_lake_root() -> pathlib.Path:
    # Path defaults live in config.py so there is exactly one home-dir
    # fallback in the codebase (enforced by scripts/check_runtime_assets.py).
    from uw_scan.config import Settings  # noqa: PLC0415

    return Settings.from_env().market_warehouse_lake_root
```

Remove the now-unused `os` import if ruff flags it.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_runtime_assets.py -k drawdown -v && uv run ruff check src/`
Expected: PASS + clean ruff.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/reports/vrp_macro_drawdown.py tests/unit/test_runtime_assets.py
git commit -m "fix(config): move the market-warehouse lake root into Settings

vrp_macro_drawdown read MARKET_WAREHOUSE_LAKE with a bare os.environ.get and
its own ~/market-warehouse fallback, so vrp_macro_signal has been skipping
QQQ/IWM with FileNotFoundError in the container since 2026-07-08. Path
defaults now live only in config.py."
```

---

### Task 6: CI guard so the class of bug cannot return

**Files:**
- Create: `scripts/check_runtime_assets.py`
- Modify: `.github/workflows/ci.yml` (after the `No Yahoo Finance` step, ~line 47)

**Interfaces:**
- Consumes: Task 1, 2 and 5 must be complete — the guard fails while any of their violations remain.
- Produces: `uv run python scripts/check_runtime_assets.py` → exit 0 clean, exit 1 with violation list.

- [ ] **Step 1: Write the guard**

Create `scripts/check_runtime_assets.py`:

```python
#!/usr/bin/env python3
"""CI guard: runtime assets must ship inside the package.

The 2026-07-08 Docker cutover silently broke two runtime code paths because
docker/app.Dockerfile does not COPY docs/. Nothing caught it: every test runs
from a checkout, where docs/ exists. This guard encodes the two rules that
would have.

Rule 1 — no `Path.home()` outside config.py. Path defaults belong in Settings,
         which is env-overridable and documented. A home-dir default resolves
         to /root inside the container, where nothing is mounted.
Rule 2 — no runtime path joins into docs/. `docs/` is not shipped; anything
         read at runtime belongs in package data or Postgres.

Run locally:
    uv run python scripts/check_runtime_assets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

HOME_DEFAULT = re.compile(r"Path\.home\(\)")
DOCS_PATH_JOIN = re.compile(r'/\s*"docs"')

# config.py is the ONE place a home-dir default is allowed: it is the single
# env-overridable source of path configuration for the whole app.
HOME_ALLOWLIST = {SRC / "uw_scan" / "config.py"}

EXCLUDE_DIRS = {"__pycache__", ".venv"}


def main() -> int:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), 1):
            if HOME_DEFAULT.search(line) and path not in HOME_ALLOWLIST:
                violations.append(
                    f"  {rel}:{lineno}: Path.home() outside config.py — "
                    f"put the default in Settings: {line.strip()[:100]}"
                )
            if DOCS_PATH_JOIN.search(line):
                violations.append(
                    f"  {rel}:{lineno}: runtime path into docs/ — docs/ is not "
                    f"shipped in the image: {line.strip()[:100]}"
                )

    if not violations:
        print("OK: no home-dir defaults outside config.py, no runtime docs/ reads.")
        return 0

    print("FAIL: runtime assets must ship inside the package.")
    print("      See docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md")
    print("\n".join(violations))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Run it — it must pass now that Tasks 1, 2, 5 are done**

Run: `uv run python scripts/check_runtime_assets.py`
Expected: `OK: no home-dir defaults outside config.py, no runtime docs/ reads.`

If it fails, the reported line is a genuine leftover from Tasks 1/2/5 — fix it rather than widening the allowlist.

- [ ] **Step 3: Prove the guard actually catches the bug**

```bash
printf '\nfrom pathlib import Path\n_BAD = Path.home() / "market-warehouse"\n' >> src/uw_scan/reports/vrp_macro_drawdown.py
uv run python scripts/check_runtime_assets.py; echo "exit=$?"
git checkout src/uw_scan/reports/vrp_macro_drawdown.py
```
Expected: `exit=1` with the injected line reported. A guard never observed failing is not a guard.

- [ ] **Step 4: Wire into CI**

In `.github/workflows/ci.yml`, immediately after the `No Yahoo Finance (CLAUDE.md standing rule)` step:

```yaml
      - name: Runtime assets ship in the package
        run: uv run python scripts/check_runtime_assets.py
```

- [ ] **Step 5: Run the full unit suite**

Run: `uv run pytest tests/unit/ -q`
Expected: PASS, including `test_no_home_dir_defaults_outside_config` from Task 5.

- [ ] **Step 6: Commit**

```bash
git add scripts/check_runtime_assets.py .github/workflows/ci.yml
git commit -m "ci: guard that runtime assets ship inside the package

Two rules that would have caught the 2026-07-08 cutover breakage: no
Path.home() outside config.py, and no runtime path joins into docs/."
```

---

### Task 7: Mirror the lake mount and env into the repo

**Files:**
- Modify: `docker-compose.yml:31-37`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `MARKET_WAREHOUSE_LAKE` from Task 5.
- Produces: no code interface. This is the config half of the fix; without it the next mirror-sync reverts the mini and the outage returns.

**Context:** These changes are already live on the mini (`/opt/argon/compose.yml`, `/opt/argon/.env`, backups `*.bak-20260720`). The committed file is the source of truth for that mirror, so it must match. Two environment facts drive the exact value: `~/market-warehouse/data-lake` is a **symlink** to `/Volumes/DATA_LAKE/livewire/data-lake`, and the runtime is **colima**, which mounts only that volume and **not `$HOME`**. Mounting the symlink path yields an empty directory.

- [ ] **Step 1: Add the volume to `x-common`**

In `docker-compose.yml`, `x-common: &common` becomes:

```yaml
x-common: &common
  env_file: [/opt/argon/.env]
  restart: unless-stopped
  # Parquet data lake, read-only. MUST be the real volume path, NOT
  # ~/market-warehouse/data-lake — that is a symlink into /Volumes, and colima
  # mounts only /Volumes/DATA_LAKE/livewire/data-lake ($HOME is NOT mounted),
  # so the symlink path yields an empty directory inside the container.
  # Without this mount resolve_lake_root has no local mirror, which froze
  # vol_index_daily at 2026-07-07 for 13 days after the Docker cutover.
  volumes:
    - /Volumes/DATA_LAKE/livewire/data-lake:/lake:ro
  extra_hosts:
    - "host.docker.internal:host-gateway"
  labels:
    com.centurylinklabs.watchtower.enable: "true"
```

- [ ] **Step 2: Document the env vars**

Append to `.env.example`:

```bash
# ── Parquet data lake (local mount; see docker-compose.yml x-common) ──
# In containers these MUST be set — the field defaults are home-dir paths
# that resolve to /root inside the image, where nothing is mounted.
LAKE_VOL_INDEX_ROOT=/lake/bronze/asset_class=volatility
LAKE_CREDIT_ETF_ROOT=/lake/bronze/asset_class=equity
MARKET_WAREHOUSE_LAKE=/lake
```

- [ ] **Step 3: Validate the compose file parses**

Run: `docker-compose -f docker-compose.yml config >/dev/null && echo "compose valid"`
Expected: `compose valid`. (If docker is unavailable locally, run `python3 -c "import yaml,sys; yaml.safe_load(open('docker-compose.yml')); print('yaml valid')"`.)

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "fix(docker): mount the parquet lake into every service

The committed compose file had no volumes, so containers had no local lake
mirror and resolve_lake_root fell through to a dead R2 bucket. Mounts the
real volume path (the ~/market-warehouse symlink is invisible to colima,
which does not mount \$HOME) and documents the three lake env vars."
```

---

### Task 8: Register the freeze and widen the recovery window

**Files:**
- Modify: `src/uw_scan/reports/data_gap_healer.py` (REGISTRY, `core market data` group)
- Modify: `src/uw_scan/worker/scheduler.py:158-164`
- Modify: `docs/runbooks/data-gap-dataset-policy.md` (regenerated)

**Interfaces:**
- Consumes: nothing.
- Produces: a `DatasetRegistryEntry("vol_index_daily", "core_watchlist", "freshness_only", ...)` in `REGISTRY`; `REGIME_RECOVERY_LOOKBACK_DAYS = 30`.

**Context:** `vol_index_daily` is already in `data_freshness.MONITORED_TABLES` (that is why the freeze showed in `/api/health`), but it is **not** in the healer's `REGISTRY` — a separate structure. Neither are `cri/vcg/canary_snapshots`. Adding `vol_index_daily` as `freshness_only` makes the freeze a tracked item; the healer cannot backfill a lake sync, which is why the mode is `freshness_only` rather than a healer adapter.

- [ ] **Step 1: Add the registry entry**

In `src/uw_scan/reports/data_gap_healer.py`, inside `REGISTRY`, at the end of the `# --- core market data ---` group:

```python
    DatasetRegistryEntry(
        # Lake-sourced, not API-sourced: rows arrive via vol_index_lake_sync
        # reading mounted parquet, so there is no fetch to retry and no healer
        # adapter. Registered for freshness tracking only — a frozen lake mount
        # (2026-07-08 → 2026-07-20) is invisible to the per-scanner
        # recover_recent_gaps, which enumerates candidate dates FROM this table
        # and therefore sees nothing missing when it stops advancing.
        "vol_index_daily",
        "core_watchlist",
        "freshness_only",
        date_col="trade_date",
        ticker_col="symbol",
        source_system="lake",
        expected_frequency="equity_session",
    ),
```

- [ ] **Step 2: Widen the recovery window**

In `src/uw_scan/worker/scheduler.py`, replace the comment block and constant at lines 158-164:

```python
# Each regime scan tick checks the last N trading days for missing snapshots
# and fills them. The window must exceed realistic TIME-TO-DETECT, not typical
# outage length: the 2026-07-08 lake outage ran 13 days, so at the previous
# value of 7 the 07-08..07-13 span would never have healed even after the mount
# was repaired — leaving a permanent hole mid-series while the recent tail
# looked correct. Per-tick cost is a set-membership check per candidate date
# and a scanner run only for dates genuinely missing a snapshot (normally zero).
REGIME_RECOVERY_LOOKBACK_DAYS = 30
```

- [ ] **Step 3: Regenerate the dataset-policy doc**

The repo requires a new temporal-table registry entry to ship with its regenerated policy doc in the same PR. The generator is `render_dataset_policy_markdown` (`src/uw_scan/reports/data_gap_healer.py:954`) and the doc embeds its own regeneration command:

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
git diff --stat docs/runbooks/data-gap-dataset-policy.md
```
Expected: the diff shows a new `vol_index_daily` row under `core_watchlist`, and the header dataset count increments by one.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/ -k "gap_healer or registry or scheduler" -v`
Expected: PASS. If a test asserts the registry length or a full dataset list, update it to include `vol_index_daily`.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/data_gap_healer.py src/uw_scan/worker/scheduler.py docs/runbooks/data-gap-dataset-policy.md
git commit -m "fix(healer): register vol_index_daily; widen regime recovery to 30d

vol_index_daily was absent from the healer REGISTRY, and the per-scanner
recover_recent_gaps enumerates candidate dates from that very table — so a
frozen lake looked healthy to both. The 7-day window also could not have
healed this 13-day outage even after repair."
```

---

### Task 9: Container smoke test — the only check that reproduces the real failure

**Files:**
- Create: `scripts/smoke_container_assets.sh`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: every prior task.
- Produces: `bash scripts/smoke_container_assets.sh` → exit 0 when the built image can load both runtime assets.

**Context:** No checkout-based test can catch this class of bug, because `docs/` exists in a checkout. Only the built artifact reveals it. This script is the honest verification.

- [ ] **Step 1: Write the smoke script**

Create `scripts/smoke_container_assets.sh`:

```bash
#!/usr/bin/env bash
# Verify the BUILT IMAGE carries its runtime assets.
#
# No checkout-based test can catch a missing package-data declaration: docs/
# and src/ data files both exist in a working tree. They only vanish in the
# image. This is the check that would have caught the 2026-07-08 cutover.
#
# Usage: bash scripts/smoke_container_assets.sh [image-tag]
set -euo pipefail

IMAGE="${1:-argon-app:smoke}"

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "building $IMAGE ..."
  docker build -f docker/app.Dockerfile -t "$IMAGE" .
fi

echo "--- canary calibration ---"
docker run --rm "$IMAGE" python -c "
from uw_scan.cards.canary_calibration import load_calibration, DEFAULT_PATH
cal = load_calibration()
print('OK', DEFAULT_PATH)
assert cal.composite_version == 1
"

echo "--- guidance rules ---"
docker run --rm "$IMAGE" python -c "
from uw_scan.api.routers.regime_validation import _parse_guidance_md
rules = _parse_guidance_md()
print('OK', len(rules), 'rules')
assert rules, 'guidance.md did not ship'
"

echo "PASS: runtime assets present in $IMAGE"
```

- [ ] **Step 2: Run it**

Run: `bash scripts/smoke_container_assets.sh`
Expected: `PASS: runtime assets present in argon-app:smoke`

If either `docker run` raises `FileNotFoundError`, the `[tool.setuptools.package-data]` block from Task 1 Step 4 is wrong or missing. That is exactly the failure this script exists to surface — fix the packaging, do not skip the check.

- [ ] **Step 3: Add the CHANGELOG entry**

Under `## [Unreleased]` in `CHANGELOG.md`:

```markdown
### Fixed

- **Runtime assets now ship inside the Python package.** `docker/app.Dockerfile`
  never copied `docs/`, so `canary-calibration-v1.json` and `guidance.md`
  vanished in the container after the 2026-07-08 Docker cutover: every canary
  run raised `FileNotFoundError` and `GET /api/regime/guidance` returned HTTP
  500 for 12 days. Both files moved to `uw_scan.cards.data` and are loaded via
  `importlib.resources`, with a `[tool.setuptools.package-data]` declaration so
  they actually ship in the wheel.
- **A missing parquet-lake root now raises instead of returning `[]`.** The
  containers had no lake mount, so `resolve_lake_root` fell through to a
  Cloudflare R2 bucket whose producer died 2026-05-21. `vol_index_lake_sync`
  read the frozen bucket, inserted nothing, and logged nothing — freezing
  `vol_index_daily` and all EOD CRI/VCG/canary snapshots at 2026-07-07 for 13
  days while `basis='live'` rows stayed current and masked it.
- **`docker-compose.yml` mounts the lake** at `/lake` (the real
  `/Volumes/DATA_LAKE/...` path — `~/market-warehouse/data-lake` is a symlink
  and colima does not mount `$HOME`).
- **`resolve_lake_root` raises when retired R2 settings are present**, so a
  stale bucket can never silently take over again.
- **`vrp_macro_drawdown` reads its lake root from `Settings`** instead of a bare
  `os.environ` lookup with a home-dir fallback, fixing the recurring
  `vrp_macro_signal QQQ/IWM: skipped — FileNotFoundError` in the container.

### Added

- `scripts/check_runtime_assets.py` CI guard: no `Path.home()` outside
  `config.py`, no runtime path joins into `docs/`.
- `scripts/smoke_container_assets.sh`: verifies the built image can load both
  runtime assets — the only check that reproduces the cutover failure.
- `vol_index_daily` registered in the data-gap healer as `freshness_only`.

### Changed

- `REGIME_RECOVERY_LOOKBACK_DAYS` 7 → 30. A recovery window must exceed
  time-to-detect, not typical outage length.
```

- [ ] **Step 4: Commit**

```bash
chmod +x scripts/smoke_container_assets.sh
git add scripts/smoke_container_assets.sh CHANGELOG.md
git commit -m "test: container smoke for runtime assets + CHANGELOG"
```

---

### Task 10: Full verification and open the PR

**Files:** none modified.

**Interfaces:**
- Consumes: Tasks 1-9.
- Produces: an open PR against `main`.

- [ ] **Step 1: Reproduce the full CI `lint + unit` job locally**

Running only ruff and pytest is not enough — the CI job runs more:

```bash
uv sync --extra postgres
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_no_yahoo.py
uv run python scripts/check_runtime_assets.py
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -q
```
Expected: every command exits 0.

- [ ] **Step 2: Run the container smoke**

Run: `bash scripts/smoke_container_assets.sh`
Expected: `PASS`.

- [ ] **Step 3: Confirm nothing still reads from `docs/` at runtime**

```bash
grep -rn '/ *"docs"' src/ || echo "clean: no runtime docs/ joins"
grep -rn 'Path.home()' src/ | grep -v 'config.py' || echo "clean: no home defaults outside config.py"
```
Expected: both `clean:` lines.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin fix/runtime-asset-durability
gh pr create --base main --title "fix: runtime asset durability after the Docker cutover" --body "$(cat <<'BODY'
Fixes the 13-day silent regime-data outage (2026-07-08 → 2026-07-20).

The Docker cutover severed lake access and dropped `docs/` from the image.
`vol_index_daily` and all EOD CRI/VCG/canary snapshots froze at 2026-07-07;
`GET /api/regime/guidance` has returned HTTP 500 for 12 days. `basis='live'`
CRI/VCG rows stayed current the whole time, which is why it looked healthy.

Establishes one invariant: **anything read at runtime ships in the package,
comes from Postgres, or comes from an explicitly-mounted path — and a
configured-but-absent source raises rather than returning empty.**

- runtime assets → `uw_scan.cards.data` via `importlib.resources`, with the
  `package-data` declaration that makes them actually ship
- absent lake root raises; absent symbol under a healthy root still returns `[]`
- retired R2 settings raise instead of silently serving a dead bucket
- `docker-compose.yml` mounts the lake (real volume path, not the symlink)
- last home-dir default moved into `Settings`
- CI guard + container smoke so the class of bug cannot return
- `vol_index_daily` registered with the healer; recovery window 7 → 30 days

Spec: `docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md`
Plan: `docs/superpowers/plans/2026-07-20-runtime-asset-durability-pr1.md`

**Post-deploy verification:** `GET /api/regime/guidance` returns HTTP 500 in
prod right now. If it returns 200 after this deploys, the PR worked.

**Follow-up (separate PR):** inline per-panel staleness badges on regime and
gold/macro. The Gold page currently serves 108-day-old WGC/CB reserves data
with no indication.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

- [ ] **Step 5: Wait for CI to go green before merging**

Run: `gh pr checks --watch`
Expected: all checks pass. **Never merge on a non-green or UNSTABLE result.**

- [ ] **Step 6: After merge and deploy, verify in prod**

```bash
ssh macmini 'curl -s -o /dev/null -w "guidance=%{http_code}\n" http://127.0.0.1:8400/api/regime/guidance'
ssh macmini '/opt/homebrew/bin/docker exec argon-worker-massive-0-1 python -c "
from uw_scan.cards.canary_calibration import load_calibration; load_calibration(); print(\"calibration OK from image\")"'
```
Expected: `guidance=200` and `calibration OK from image` **without any `docker cp`** — proving the ephemeral workaround is no longer load-bearing.

- [ ] **Step 7: Remove the temporary env override note**

Set `MARKET_WAREHOUSE_LAKE=/lake` in `/opt/argon/.env` (it is currently unset) and restart the workers so `vrp_macro_signal` stops skipping QQQ/IWM:

```bash
ssh macmini 'grep -q MARKET_WAREHOUSE_LAKE /opt/argon/.env || echo "MARKET_WAREHOUSE_LAKE=/lake" >> /opt/argon/.env'
ssh macmini 'cd /opt/argon && /opt/homebrew/bin/docker-compose up -d --force-recreate'
ssh macmini '/opt/homebrew/bin/docker logs --since 10m argon-worker-massive-0-1 2>&1 | grep -c "vrp_macro_signal.*FileNotFoundError" || echo "0 — clean"'
```
Expected: `0 — clean`.

---

## Deferred to a separate plan

**PR2 — inline staleness badges (frontend only).** `/api/health` already returns
the per-table freshness block and it is already typed at `web/lib/types.ts:3974`,
so PR2 needs zero backend, zero API, and zero `types.ts` changes — which matters
because those generated files are alphabetically frozen and must never be fully
regenerated. Scope: `web/lib/useFreshness.ts`, `web/components/ui/StaleBadge.tsx`
(patterned on `web/components/regime/ui/RegimePill.tsx`), wired into
`CriSubTab`, `VcgSubTab`, `CanarySubTab` and the gold/macro panels, rendering
when `frozen` or `days_stale >= 2`. Known ceiling to carry a `ponytail:` comment:
the freshness monitor runs nightly at 21:00 ET, so the badge lags reality by up
to 24h.

**Not in scope at all** (recorded in the spec's §5): the apex bar-source
migration (blocked — apex serves adjusted bars from `silver/`, which has no
`asset_class=volatility`; owner is the operator) and the livewire
`intraday_catchup` outage (different repo, failing since 2026-07-14).
