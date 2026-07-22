# Runtime Asset Durability (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make argon's container carry every asset it reads at runtime, and make a configured-but-absent data source crash instead of silently returning empty.

**Architecture:** Move the two runtime files out of `docs/` into the Python package (loaded via `importlib.resources`), mirror the mini's lake mount into the committed compose file, convert silent empty-returns into raises at the lake boundary, and add a CI guard so the class of bug cannot come back. No new services, no schema changes.

**Tech Stack:** Python 3.13 / uv, setuptools packaging, FastAPI, pytest, Docker Compose (colima), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md`

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`.
- **Never commit without an explicit user request** (`CLAUDE.md`). Plan approval is **not** commit authorisation. The `git commit` steps below are written out so the executor knows exactly what to stage and what the message should say — but each still requires the user to ask. Draft, show, wait.
- **Branch is `fix/runtime-asset-durability`**, already created, already holding the spec commit `3df422f`. Do not create another branch. Do not push to `main`.
- **No `Co-Authored-By` trailers, and no AI/tool attribution of any kind** — not in commit messages, not in the PR body. The user's `CLAUDE.md` bans these outright and overrides the tooling default that appends a "Generated with Claude Code" line.
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
| `pyproject.toml` | modify | Declare the above as package data (wheel correctness — see Task 1 Step 4 for why this is *not* what fixes prod) |
| `src/uw_scan/cards/canary_calibration.py:16-22` | modify | Resolve calibration via `importlib.resources` |
| `src/uw_scan/api/routers/regime_validation.py:60-88,158-166` | modify | Read guidance from package data; delete `_safe_doc_path` + `_DOCS_REGIME` |
| `src/uw_scan/reports/regime_canary_v1_v2_compare.py:36-38` | modify | Repoint research paths |
| `src/uw_scan/sources/lake.py:88-109` | modify | Absent lake **root** raises; absent **symbol** still returns `[]` |
| `src/uw_scan/worker/jobs/vol_index_lake_sync.py:38-41` | modify | Mounted-but-empty lake raises instead of returning a success summary |
| `src/uw_scan/worker/scheduler.py:186-200` | modify | Refuse to boot when retired R2 settings are present |
| `scripts/backtest_canary.py:44`, `scripts/canary_backfill.py:58` | modify | Repoint calibration paths (shipped in the image) |
| `tests/unit/test_canary_v2_formula.py`, `tests/integration/regime/test_canary_form_sweep_full.py` | modify | Repoint calibration paths |
| `tests/integration/api/test_regime_guidance_endpoint.py:73,94` | modify | Patch `_GUIDANCE_MD` instead of the deleted `_DOCS_REGIME` |
| `src/uw_scan/config.py` | modify | New `market_warehouse_lake_root` setting (owns the last home-dir default) |
| `src/uw_scan/reports/vrp_macro_drawdown.py:67-73` | modify | Read the root from `Settings` instead of a bare `os.environ` + home default |
| `scripts/check_runtime_assets.py` | create | CI guard: no `Path.home()` outside `config.py`, no runtime reads under `docs/` |
| `.github/workflows/ci.yml:45-47` | modify | Wire the guard in |
| `docker-compose.yml:31-37` | modify | Lake mount on `x-common` |
| `.env.example` | modify | Document `LAKE_*` + `MARKET_WAREHOUSE_LAKE` |
| `src/uw_scan/worker/scheduler.py:158-164` | modify | Recovery lookback 7 → 30 |
| `tests/unit/test_runtime_assets.py` | create | Package-data resolution tests |
| `tests/unit/test_lake_reader.py` | modify | Absent-root-raises test |
| `tests/unit/sources/test_lake_resolver.py` | **unchanged — verify still green** | 15 tests, 8 of which require R2→s3 resolution; Task 4 must not break them |
| `scripts/smoke_container_assets.sh` | create | Built-image asset smoke — the only check reproducing the real failure |
| `docs/research/regime/README.md` | modify | Pointer to the moved files |
| `CHANGELOG.md` | modify | `[Unreleased]` entry |

**Deliberately NOT touched:** `src/uw_scan/reports/data_gap_healer.py` and
`docs/runbooks/data-gap-dataset-policy.md`. `vol_index_daily` is *already* in
`REGISTRY` (line 501, `freshness_only`); adding it again would fail
`test_registry_table_names_are_unique`. See the spec's §4.1 item D.

---

### Task 1: Ship the canary calibration as package data

This task is first because it carries the `pyproject.toml` packaging config that every later asset move depends on.

**Files:**
- Create: `src/uw_scan/cards/data/canary-calibration-v1.json` (git mv)
- Create: `src/uw_scan/cards/data/canary-calibration-v2.json` (git mv)
- Modify: `pyproject.toml`
- Modify: `src/uw_scan/cards/canary_calibration.py:16-22`
- Modify: `src/uw_scan/reports/regime_canary_v1_v2_compare.py:37-38`
- Modify: `scripts/backtest_canary.py:44`
- Modify: `scripts/canary_backfill.py:58`
- Modify: `tests/unit/test_canary_v2_formula.py:20-33`
- Modify: `tests/integration/regime/test_canary_form_sweep_full.py:416-420,564-568`
- Test: `tests/unit/test_runtime_assets.py`

**⚠ Six consumers, not one.** `git mv` breaks every hardcoded
`docs/research/regime/canary-calibration-*.json` path in the repo. All of them
are listed above and verified present. Miss any and Step 7's `-k canary` run
fails — `tests/unit/test_canary_v2_formula.py` is in that selection.

**Design note the spec did not call out.** These JSON files are *written* by
research scripts (`scripts/backtest_canary.py` regenerates v1) and *read* by the
app. Moving them into the package means a research script now writes into
`src/`. That is acceptable — they are frozen, rarely regenerated calibrations,
and the runtime read is the constraint that matters — but it is a real coupling.
If regeneration ever becomes routine, the right shape is: script writes to
`docs/research/`, and a promotion step copies the blessed file into the package.
Not needed today; do not build it.

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

Add immediately after the `[tool.setuptools.packages.find]` block in `pyproject.toml`:

```toml
[tool.setuptools.package-data]
"uw_scan.cards" = ["data/*.json", "data/*.md"]
```

**Know what this does and does not buy.** Non-`.py` files under `src/` do not ship in a *wheel* by default, so this block is required for `uv build --wheel` (the release artifact) to be correct. It is **not** what makes the container work: `docker/app.Dockerfile` does `COPY src/ ./src/` then `uv sync`, producing an **editable** install pointing at `/app/src`, so the container imports from the copied tree. The proof already in the repo is `src/uw_scan/storage/migrations/` — 148 `.sql` files under `src/`, read at runtime, working in prod with no `package-data` declaration.

Consequence for verification: Step 8's wheel inspection is the only check that catches this block being wrong. The container smoke in Task 9 will pass either way — do not treat it as coverage for this step.

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

Add `from importlib.resources import files` to that module's imports.

**Keep `REPO_ROOT`** — it is still used at line 303 (`sys.path.insert` for the script-invocation path). Only lines 37-38 change; line 36 stays.

- [ ] **Step 6b: Repoint the two research scripts**

Both build the path off their own `REPO_ROOT`. In each, replace the `V*_CAL_PATH` assignment with the package-data resolution and add `from importlib.resources import files`:

`scripts/backtest_canary.py:44` —
```python
V2_CAL_PATH = files("uw_scan.cards") / "data" / "canary-calibration-v2.json"
```

`scripts/canary_backfill.py:57-58` — same for whichever of `V1_CAL_PATH` / `V2_CAL_PATH` it defines. Check both lines; only repoint the ones pointing into `docs/`.

Keep each file's `REPO_ROOT` if it is used for anything else (both use it for `sys.path`); ruff will flag it if not.

- [ ] **Step 6c: Repoint the three test consumers**

```bash
grep -rn 'canary-calibration' tests/
```
Expected hits, all to repoint at `files("uw_scan.cards") / "data" / ...`:
- `tests/unit/test_canary_v2_formula.py:20-33` (both v1 and v2 paths)
- `tests/integration/regime/test_canary_form_sweep_full.py:416-420`
- `tests/integration/regime/test_canary_form_sweep_full.py:564-568` — this one asserts the v1 file's **byte content is unchanged after a run**, so it must resolve to the same file the sweep writes. Repoint, do not delete.

Re-run the grep afterwards; it must return no `docs/research/regime` hits.

- [ ] **Step 7: Run the tests — unit AND the affected integration tests**

```bash
uv run pytest tests/unit/test_runtime_assets.py tests/unit/ -k "canary" -v
uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v
```
Expected: PASS. The second command needs local Postgres; if unavailable, say so explicitly and make sure Task 10 Step 1 runs it before the PR opens — CI runs integration tests (`.github/workflows/ci.yml:121-135`) and will catch it either way, but not before you have pushed a red branch.

- [ ] **Step 8: Confirm the wheel actually contains the files**

The only check that proves Step 4 worked — nothing else in this plan does:

Build into a **clean** directory and assert the **exact** members — a stale wheel in `dist/` or a truthy-but-incomplete list would otherwise let this pass while broken:

```bash
set -o pipefail
rm -rf /tmp/argon-wheel && uv build --wheel --out-dir /tmp/argon-wheel || { echo "BUILD FAILED"; exit 1; }
python3 - <<'EOF'
import glob, zipfile
whls = glob.glob('/tmp/argon-wheel/*.whl')
assert len(whls) == 1, f"expected exactly one wheel, got {whls}"
names = {n for n in zipfile.ZipFile(whls[0]).namelist() if '/cards/data/' in n}
want = {
    'uw_scan/cards/data/canary-calibration-v1.json',
    'uw_scan/cards/data/canary-calibration-v2.json',
}
missing = want - names
assert not missing, f"package-data is wrong; missing from wheel: {sorted(missing)}"
print("wheel OK:", sorted(names))
EOF
```
Expected: `wheel OK: [...]` listing both JSON files.

**Note the ordering limitation:** `guidance.md` moves in Task 2, *after* this check. Task 2 Step 7b re-runs this same block with `guidance.md` added to `want` — do not consider the packaging verified until then.

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

- [ ] **Step 4b: Fix the module docstring — it is a Rule-3 violation, not cosmetics**

`regime_validation.py:12-15` currently reads:

> `GET /api/regime/guidance` — returns the active regime-state guidance rule
> selected from **docs/research/regime/guidance.md** based on the current CRI
> snapshot. (**guidance.md is still on disk**; only the backtest artifacts moved
> to Postgres.)

That sentence is now false, and Task 6's Rule 3 judges files *whole* — a runtime-asset filename plus any `docs/` token anywhere in the file trips it. Leaving the docstring alone keeps this file failing CI even after Step 4. Replace with:

```
GET /api/regime/guidance — returns the active regime-state guidance rule
  selected from the packaged guidance.md (uw_scan/cards/data/) based on the
  current CRI snapshot. It moved out of docs/ on 2026-07-20 because the image
  does not carry docs/; see the runtime-asset-durability spec.
```

- [ ] **Step 5: Simplify the parser**

Replace the head of `_parse_guidance_md` (lines 158-166) so it reads:

```python
def _parse_guidance_md() -> list[dict[str, Any]]:
    """Split guidance.md on `---` separators; load YAML frontmatter + body."""
    try:
        text = _GUIDANCE_MD.read_text()
    except FileNotFoundError:
        logger.error(
            "guidance.md unreadable at %s — is it shipping as package data?",
            _GUIDANCE_MD,
        )
        return []
    chunks = [c.strip() for c in text.split("\n---\n")]
```

The rest of the function body is unchanged; only the `try/except HTTPException` head is replaced.

**Keep the empty return — do not "fix" it into a raise.** This looks like a violation of the spec's *never return empty* invariant. It is not: `get_guidance` at line 232-234 already does

```python
rules = _parse_guidance_md()
if not rules:
    raise HTTPException(500, "guidance.md missing or has no parseable rules")
```

so the `[]` travels exactly one line before becoming a loud 500 with a useful message — plus, now, an ERROR log naming the resolved path. Letting `FileNotFoundError` propagate instead would produce an *opaque* 500, lose that message, and break `test_guidance_500_when_guidance_md_missing`, which asserts `"guidance.md" in resp.json()["detail"]`. The invariant is satisfied by the endpoint, which is where it belongs.

- [ ] **Step 6: Update the two integration tests that monkeypatch `_DOCS_REGIME`**

`tests/integration/api/test_regime_guidance_endpoint.py` patches the deleted constant at **lines 73 and 94**. `monkeypatch.setattr` raises `AttributeError` on a name that no longer exists, so both tests fail hard — and Task 2's unit-only test run will not notice. CI will (`.github/workflows/ci.yml:121-135`).

`_DOCS_REGIME` was a **directory**; `_GUIDANCE_MD` is a **file**. Change both patch targets accordingly:

```python
# line 73 — test_guidance_500_when_guidance_md_missing
# tmp_path is empty, so this path does not exist -> _parse_guidance_md returns []
# -> the endpoint raises HTTPException(500, "guidance.md missing ...") as before.
monkeypatch.setattr(regime_validation, "_GUIDANCE_MD", tmp_path / "guidance.md")

# line 94 — test_guidance_skips_malformed_rule_and_falls_through
# the test already writes tmp_path/"guidance.md"; point straight at it.
monkeypatch.setattr(regime_validation, "_GUIDANCE_MD", tmp_path / "guidance.md")
```

Both assertions stay valid unchanged — that is the point of keeping the `[]` return in Step 5.

- [ ] **Step 7: Clean up now-unused imports**

Run: `uv run ruff check src/uw_scan/api/routers/regime_validation.py`
`Path` is imported at line 23 and used **only** at lines 63 and 67, both of which Step 4 deletes — so it will be flagged. Delete it. `HTTPException` stays (12 other uses). Re-run until clean.

- [ ] **Step 7b: Re-run the wheel check, now with `guidance.md`**

Re-run the Task 1 Step 8 block with `guidance.md` added to `want`:

```python
want = {
    'uw_scan/cards/data/canary-calibration-v1.json',
    'uw_scan/cards/data/canary-calibration-v2.json',
    'uw_scan/cards/data/guidance.md',
}
```
Expected: all three listed. **Packaging is not verified until this passes** — Task 1's run could only see two of the three.

- [ ] **Step 7c: Run the tests — unit AND the guidance integration suite**

```bash
uv run pytest tests/unit/test_runtime_assets.py -v
uv run pytest tests/unit/ -k regime_validation -v
uv run pytest tests/integration/api/test_regime_guidance_endpoint.py -v
```
Expected: PASS. If local Postgres is unavailable for the third, say so explicitly rather than skipping silently — it is the command that proves Step 6 landed.

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

Then fix the **three** stale references in that file's body, verified present:

| Line | Current text | Fix |
|---|---|---|
| ~15-16 | "Why files stayed in place (not all archived): `guidance.md` is **read live by the API**… `canary-calibration-v{1,2}.json` are **loaded at runtime**" | They no longer stay in place — say they moved to `src/uw_scan/cards/data/` *because* they are read at runtime |
| ~41 | "is the `guidance.md` lookup the API serves" | point at the new path |
| ~116 | table row: `\| Runtime calibration (loaded by app) \| canary-calibration-v{1,2}.json \|` | point at the new path |

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

**What the raise actually does — it is not a crash.** The caller is
`worker/jobs/vol_index_lake_sync.py:38`, dispatched by
`scheduler.py:939 _vol_index_lake_sync`. APScheduler catches job exceptions, so
the raise routes to the `EVENT_JOB_ERROR` listener at `scheduler.py:580`:
recorded via `JobFailuresRepository.record_failure`, surfaced in `/api/health`
as a `job_failures[]` streak, and escalated to `send_alert` at streak 3 and 10
(a no-op today — `OPS_ALERT_WEBHOOK_URL` is unset). The worker keeps running.

The value is the *state change*: today `list_vol_index_symbols` returns `[]`,
the job logs `logger.info("no symbols at …")` and is recorded as a **success**.
After this task the same condition is recorded as a **failure** with a streak.
Verify accordingly — check `job_failures`, not container restarts.

**Known residual gap — a present-but-empty root.** `_require_root` tests
`root.exists()`, so it catches an absent mount but not a mounted-yet-empty one.
That case is real: `/Volumes/DATA_LAKE` is an *external* volume, and Docker
auto-creates a bind-mount source that is missing, yielding an empty `/lake`.

Two reasons it is nevertheless covered in practice, and one reason to close it
anyway in Step 3b:

1. The configured roots are `/lake/bronze/asset_class=volatility` and
   `…=equity` — **subpaths**, which do not exist under an empty `/lake`. So
   `_require_root` does fire. The check is load-bearing precisely because it
   tests the asset-class subpath, not `/lake` itself.
2. A genuinely present-but-empty asset-class dir (upstream deleted everything)
   is not a scenario that has occurred.

But "zero symbols" is still a silent success path at
`vol_index_lake_sync.py:38-41`, and that is the shape of the original bug. Close
it cheaply.

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

- [ ] **Step 3b: Make "zero symbols" a failure at the sync boundary**

`_require_root` cannot catch a *mounted but empty* lake. The sync job can, and it is where the meaning lives — a volatility lake with no symbols at all is never a legitimate state. In `src/uw_scan/worker/jobs/vol_index_lake_sync.py`, replace the early return at lines 38-41:

```python
    symbols = list_vol_index_symbols(root)
    if not symbols:
        # An empty lake is a broken mount, not "no new data". Returning a
        # success summary here is what let the 2026-07-08 freeze look healthy
        # for 13 days; raising records a job failure + /api/health streak.
        raise RuntimeError(
            f"vol_index_lake_sync: no symbols under {root} — the lake is "
            f"mounted but empty. Check the volume and LAKE_VOL_INDEX_ROOT."
        )
```

Add a test to `tests/unit/test_lake_reader.py`:

```python
def test_sync_raises_on_present_but_empty_lake(tmp_path: Path) -> None:
    """A mounted-but-empty lake is a broken mount, not 'no new rows'."""
    from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

    with pytest.raises(RuntimeError, match="mounted but empty"):
        run_vol_index_lake_sync(None, root=tmp_path)
```

`tmp_path` exists, so `_require_root` passes and `list_vol_index_symbols` returns `[]` — exactly the uncovered case. The `conn=None` never gets used because the raise happens first; if that reads as too clever, pass a stub connection instead.

**Leave `credit_etf_lake_sync` alone.** Its per-symbol "missing or mid-write, skipping" warning at lines 51-59 is a *different* situation — HYG/JNK/LQD are individually optional and a partial read is tolerable there. Do not generalise this change into it without evidence.

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

### Task 4: Guard against silent R2 resurrection — at startup, not in the resolver

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py:186-200` (`_validate_worker_settings`)
- Test: `tests/unit/test_runtime_assets.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `_validate_worker_settings(settings)` raises `RuntimeError` when all four `r2_*` settings are populated. `resolve_lake_root` is **unchanged**.

**Context — and why this is NOT implemented where the spec first proposed.**

R2's producer push died 2026-05-21 and the backend is retired, but the s3 branch
is still selectable: any `.env` carrying `R2_*` silently reroutes every lake read
to a dead bucket. That is the mechanism behind this incident and it is worth
closing.

The spec's original idea — raise inside `resolve_lake_root` — is wrong, and
cheaply so. `tests/unit/sources/test_lake_resolver.py` (note the path: the plan
previously named a non-existent `tests/unit/test_lake_resolver.py`) has **15
tests, 8 of which assert that R2 config resolves to an s3 root**:
`test_resolve_s3_when_r2_configured`,
`test_resolve_equity_routes_to_credit_etf_key_prefix_on_s3`,
`test_resolve_endpoint_override_takes_precedence`,
`test_resolve_uses_r2_when_r2_is_at_or_ahead_of_local`,
`test_resolve_uses_r2_when_local_is_empty`,
`test_resolve_uses_r2_when_both_backends_empty`,
`test_resolve_prefers_local_when_local_strictly_ahead_of_r2`,
`test_resolve_freshness_check_skipped_when_r2_unconfigured`. Two integration
suites depend on it too (`tests/integration/sources/test_lake_r2.py`,
`tests/integration/worker/test_lake_sync_r2.py`), as do
`src/uw_scan/sources/CLAUDE.md:12-15` and both lake-sync module docstrings.

So the "three-line guard" was really: three lines plus retiring ten tests plus
rewriting three docs — in the PR that has a deploy clock on it.

**A startup assertion buys the same protection for less.** R2 config is a
*deployment* mistake, so reject it when the process boots rather than on every
read. `_validate_worker_settings` already exists for exactly this, has no
existing tests to disturb, and runs before any job is scheduled
(`scheduler.py:576`). `resolve_lake_root` and its whole test suite stay green and
untouched — and get deleted wholesale by the apex migration, as the spec intended.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_runtime_assets.py`:

```python
def test_r2_settings_are_rejected_at_worker_startup() -> None:
    """R2 is retired; booting with its config must fail loudly, not reroute."""
    import pytest
    from pydantic import SecretStr

    from uw_scan.config import Settings
    from uw_scan.worker.scheduler import _validate_worker_settings

    ok = Settings.model_construct(worker_role="massive", worker_count=1, worker_index=0)
    _validate_worker_settings(ok)  # no R2 -> fine

    with_r2 = Settings.model_construct(
        worker_role="massive",
        worker_count=1,
        worker_index=0,
        r2_account_id="acct",
        r2_bucket="market-data",
        r2_access_key_id=SecretStr("k"),
        r2_secret_access_key=SecretStr("s"),
    )
    with pytest.raises(RuntimeError, match="R2.*retired"):
        _validate_worker_settings(with_r2)
```

`Settings.model_construct` skips validation but **does** apply field defaults, and all five `r2_*` fields default to `None` (`config.py:364-368`, verified) — so the first case genuinely has no R2 config.

- [ ] **Step 2: Run to confirm failure**

Run: `uv run pytest tests/unit/test_runtime_assets.py -k r2 -v`
Expected: FAIL — no `RuntimeError` raised; `_validate_worker_settings` returns `None`.

- [ ] **Step 3: Implement**

In `src/uw_scan/worker/scheduler.py`, append to `_validate_worker_settings` (after the `worker_index` check at line 196-200):

```python
    # R2 is retired: its producer push died 2026-05-21, so resolve_lake_root
    # would hand every lake read to a bucket frozen at that date — silently,
    # which is exactly how the 2026-07-08 outage stayed invisible for 13 days.
    # Reject at boot; the resolver's s3 branch stays intact for its own tests
    # and is removed wholesale by the apex migration.
    if _r2_fully_configured(settings):
        raise RuntimeError(
            "R2 lake settings are present, but R2 is retired — its producer "
            "push has been dead since 2026-05-21 and reading it silently "
            "serves stale data. Remove R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / "
            "R2_SECRET_ACCESS_KEY / R2_BUCKET from the environment; the "
            "mounted local lake is the only supported source."
        )
```

Import the existing predicate rather than re-deriving it — add to the imports at the top of `scheduler.py`:

```python
from uw_scan.sources.lake_resolver import _r2_fully_configured
```

If ruff objects to importing a private name across modules, rename it to
`r2_fully_configured` in `lake_resolver.py` and update its call sites there
(there are two) plus any test references — check with
`grep -rn '_r2_fully_configured' src/ tests/` first.

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_runtime_assets.py -k r2 -v
uv run pytest tests/unit/sources/test_lake_resolver.py -v
uv run pytest tests/unit/ -k lake -v
```
Expected: all PASS. The middle command is the important one — **all 15 resolver tests must still pass**, because this task deliberately does not touch `resolve_lake_root`. If any fail, the guard was put in the wrong place; move it back to `_validate_worker_settings`.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/scheduler.py tests/unit/test_runtime_assets.py
git commit -m "fix(worker): refuse to boot when retired R2 settings are present

R2's producer died 2026-05-21. While the s3 branch is selectable, any .env
carrying R2_* silently reroutes every lake read to a dead bucket. Rejecting
at worker startup catches the deployment mistake without disturbing
resolve_lake_root or its 15 tests, which the apex migration retires anyway."
```

### Task 5: Move the last home-dir default into Settings

**Files:**
- Modify: `src/uw_scan/config.py`
- Modify: `src/uw_scan/reports/vrp_macro_drawdown.py:67-73`
- Test: `tests/unit/test_runtime_assets.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.market_warehouse_lake_root: Path` (env `MARKET_WAREHOUSE_LAKE`, default `Path.home() / "market-warehouse" / "data-lake"`). `vrp_macro_drawdown._default_lake_root() -> Path` now reads it. This is the last `Path.home()` outside `config.py`, which Task 6's guard depends on.

**Context:** `_default_lake_root` reads `MARKET_WAREHOUSE_LAKE` with a bare `os.environ.get` and its own home-dir fallback. In the container that resolves to `/root/market-warehouse/data-lake`, which does not exist. `load_index_vol` is imported by `worker/jobs/vrp_macro_signal.py` — a scheduled job — so this has been logging `vrp_macro_signal QQQ: skipped — FileNotFoundError(...)` every run since the cutover.

**Be clear about what this task does and does not fix.** It is a *structural*
change, not a functional one. The existing `os.environ.get("MARKET_WAREHOUSE_LAKE", …)`
already honours the env var, and the new `Settings` field defaults to the same
`Path.home() / "market-warehouse" / "data-lake"` — so with the var still unset,
behaviour is byte-for-byte identical and `vrp_macro_signal` keeps skipping
QQQ/IWM. **What actually fixes prod is setting `MARKET_WAREHOUSE_LAKE=/lake` on
the mini (Task 10 Step 7).**

This task earns its place by making Task 6's guard rule — *exactly one home-dir
default in the codebase, in `config.py`* — true and enforceable. Do not write a
commit message or CHANGELOG line claiming it resolves the `FileNotFoundError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_runtime_assets.py`:

```python
def test_drawdown_lake_root_honours_env(monkeypatch) -> None:
    """Env override must survive the move of the default into Settings."""
    from uw_scan.reports import vrp_macro_drawdown

    monkeypatch.setenv("MARKET_WAREHOUSE_LAKE", "/lake")
    assert str(vrp_macro_drawdown._default_lake_root()) == "/lake"


def test_drawdown_module_has_no_home_default() -> None:
    """The home-dir fallback must live in config.py, not here."""
    import inspect

    from uw_scan.reports import vrp_macro_drawdown

    src = inspect.getsource(vrp_macro_drawdown._default_lake_root)
    assert "Path.home()" not in src, "home-dir fallback still inline in the consumer"
```

The subprocess-based guard check that previously lived here has moved to Task 6, where the script it invokes actually exists. Leaving it here would commit a red test at Step 6 and leave the tree failing between tasks.

- [ ] **Step 2: Run to confirm the second test fails**

Run: `uv run pytest tests/unit/test_runtime_assets.py -k drawdown -v`
Expected: `test_drawdown_module_has_no_home_default` **FAILS** (line 71 still has `pathlib.Path.home()`); `test_drawdown_lake_root_honours_env` **PASSES** already — the current `os.environ.get` honours the env var, and that test exists to stop Step 4 regressing it.

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
    # Path defaults live in config.py so there is exactly one home-dir fallback
    # in the codebase (enforced by scripts/check_runtime_assets.py). Read the
    # FIELD DEFAULT, not Settings.from_env(): from_env() requires
    # UW_SCAN_API_KEY and raises without it (config.py:490-494), which would
    # turn a path lookup into a hard dependency on a credential this function
    # has no business needing — and would fail outright in the unit CI job.
    from uw_scan.config import Settings  # noqa: PLC0415

    env = os.environ.get("MARKET_WAREHOUSE_LAKE", "").strip()
    if env:
        return pathlib.Path(env)
    return pathlib.Path(Settings.model_fields["market_warehouse_lake_root"].default)
```

**Do not replace this with `Settings.from_env()`.** It is the obvious-looking simplification and it is a live grenade: `from_env()` raises `RuntimeError("UW_SCAN_API_KEY is not set")` in any process without the key — including `pytest tests/unit/` in CI, which supplies none (`.github/workflows/ci.yml:17-65`). `model_fields[...].default` is a plain class-attribute read: no env, no validation, no credential. Verified working.

Keep the `os` import — it is still used here.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_runtime_assets.py -v && uv run ruff check src/`
Expected: PASS (all of them — the whole file, not just `-k drawdown`) + clean ruff.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py src/uw_scan/reports/vrp_macro_drawdown.py tests/unit/test_runtime_assets.py
git commit -m "refactor(config): move the market-warehouse lake root into Settings

vrp_macro_drawdown read MARKET_WAREHOUSE_LAKE with a bare os.environ.get and
its own ~/market-warehouse fallback. Behaviour is unchanged — the default is
the same path — but path defaults now live only in config.py, which is what
makes the check_runtime_assets guard enforceable.

Does NOT by itself fix the vrp_macro_signal QQQ/IWM FileNotFoundError in the
container; that needs MARKET_WAREHOUSE_LAKE=/lake set on the mini."
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

Create `scripts/check_runtime_assets.py`. **This design was empirically tested against the current tree** (see Step 3 for the exact expected output) — do not "improve" the rules without re-running that check:

```python
#!/usr/bin/env python3
"""CI guard: runtime assets must ship inside the package.

The 2026-07-08 Docker cutover silently broke two runtime code paths because
docker/app.Dockerfile does not COPY docs/. Nothing caught it: every test runs
from a checkout, where docs/ exists. This guard encodes the rules that would.

Rule 1 — no `Path.home()` in src/ outside config.py. Path defaults belong in
         Settings, which is env-overridable and documented. A home-dir default
         resolves to /root inside the container, where nothing is mounted.
Rule 2 — no docs/ path construction in src/. docs/ is not in the image.
Rule 3 — no named RUNTIME ASSET may be reached through a docs/ path, in src/
         OR scripts/. scripts/ is COPYied into the image
         (docker/app.Dockerfile:50), but it also holds research tooling that
         legitimately reads and writes docs/ — 38 such lines today. Blanket-
         scanning scripts/ would therefore be pure noise. Rule 3 is the
         precise version: only files that touch a real runtime asset are
         judged, and they are judged file-wide so a path split across several
         lines is still caught.

Run locally:
    uv run python scripts/check_runtime_assets.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
SCRIPTS = REPO_ROOT / "scripts"

# Matches `pathlib.Path.home()` too — same substring.
HOME_DEFAULT = re.compile(r"Path\.home\(\)")

# Both quote styles plus the two other ways to build the same path.
DOCS_PATH = re.compile(
    r"""(/\s*['"]docs['"])"""            # Path(...) / "docs"
    r"""|(['"]docs/)"""                  # Path("docs/research/...")
    r"""|(joinpath\(\s*['"]docs['"])"""  # .joinpath("docs", ...)
)

# Files the app reads at runtime. Add to this list when a new one appears.
RUNTIME_ASSETS = (
    "canary-calibration-v1.json",
    "canary-calibration-v2.json",
    "guidance.md",
)

# config.py is the ONE place a home-dir default is allowed: it is the single
# env-overridable source of path configuration for the whole app.
HOME_ALLOWLIST = {SRC / "uw_scan" / "config.py"}

# data_gap_healer embeds its own regeneration command as help text, which
# WRITES docs/runbooks/... It never reads a doc at runtime.
DOCS_ALLOWLIST = {SRC / "uw_scan" / "reports" / "data_gap_healer.py"}

SELF = Path(__file__).resolve()
EXCLUDE_DIRS = {"__pycache__", ".venv", "node_modules"}


def _py_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [
        p
        for p in root.rglob("*.py")
        if not any(part in EXCLUDE_DIRS for part in p.parts)
        and p.resolve() != SELF
    ]


def main() -> int:
    violations: list[str] = []

    for path in _py_files(SRC):
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
            if DOCS_PATH.search(line) and path not in DOCS_ALLOWLIST:
                violations.append(
                    f"  {rel}:{lineno}: runtime path into docs/ — docs/ is not "
                    f"shipped in the image: {line.strip()[:100]}"
                )

    for path in _py_files(SRC) + _py_files(SCRIPTS):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if any(asset in text for asset in RUNTIME_ASSETS) and DOCS_PATH.search(text):
            violations.append(
                f"  {path.relative_to(REPO_ROOT)}: references a runtime asset "
                f"({', '.join(a for a in RUNTIME_ASSETS if a in text)}) and "
                f"builds a docs/ path — resolve it via importlib.resources"
            )

    if not violations:
        print("OK: runtime assets resolve from the package, not from docs/.")
        return 0

    print("FAIL: runtime assets must ship inside the package.")
    print("      See docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md")
    print("\n".join(sorted(set(violations))))
    return 1


if __name__ == "__main__":
    sys.exit(main())
```
- [ ] **Step 2: Add the pytest wrapper so CI-parity is checked locally too**

Append to `tests/unit/test_runtime_assets.py`:

```python
def test_runtime_asset_guard_passes() -> None:
    """The CI guard must be green on the tree it ships with."""
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "scripts/check_runtime_assets.py"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, out.stdout + out.stderr
```

Uses `sys.executable`, not `["uv", "run", ...]` — the test already runs inside the project venv, and shelling out to `uv` breaks in the container (uv is a build-only tool, absent from the runtime image by design).

- [ ] **Step 3: Run it — it must pass now that Tasks 1, 2, 5 are done**

Run: `uv run python scripts/check_runtime_assets.py`
Expected: `OK: runtime assets resolve from the package, not from docs/.`

**Baseline measured against the pre-change tree** — this exact rule set produced
**10 violations**, and Tasks 1, 2 and 5 clear every one:

| Rule | Violation | Cleared by |
|---|---|---|
| 1 | `reports/vrp_macro_drawdown.py:71` | Task 5 Step 4 |
| 2 | `cards/canary_calibration.py:18` | Task 1 Step 5 |
| 2 | `api/routers/regime_validation.py:63` | Task 2 Step 4 |
| 2 | `reports/regime_canary_v1_v2_compare.py:37` | Task 1 Step 6 |
| 2 | `reports/regime_canary_v1_v2_compare.py:38` | Task 1 Step 6 |
| 2 | `reports/data_gap_healer.py:973` | **allowlisted** — writes a doc, never reads one |
| 3 | `scripts/backtest_canary.py` | Task 1 Step 6b |
| 3 | `scripts/canary_backfill.py` | Task 1 Step 6b |
| 3 | `api/routers/regime_validation.py` | Task 2 Steps 4 **and 4b** (module docstring) |
| 3 | `reports/regime_canary_v1_v2_compare.py` | Task 1 Step 6 |

If the run is not clean, compare against this table before touching an
allowlist. A violation *not* in it is a genuine new leftover — fix the code. A
violation still in it means the named task step was not applied.

- [ ] **Step 4: Prove the guard actually catches the bug — both spellings**

The offender that started this used `pathlib.Path.home()`, not the bare form, so inject that one:

```bash
printf '\n_BAD = pathlib.Path.home() / "market-warehouse"\n' >> src/uw_scan/reports/vrp_macro_drawdown.py
uv run python scripts/check_runtime_assets.py; echo "rule1 exit=$?"
git checkout src/uw_scan/reports/vrp_macro_drawdown.py

printf '\n_BAD2 = REPO_ROOT / "docs" / "research" / "regime" / "guidance.md"\n' >> src/uw_scan/reports/regime_canary_v1_v2_compare.py
uv run python scripts/check_runtime_assets.py; echo "rule3 exit=$?"
git checkout src/uw_scan/reports/regime_canary_v1_v2_compare.py
```
Expected: `rule1 exit=1` and `rule3 exit=1`, each naming the injected line/file. A guard never observed failing is not a guard — and Rule 1 in particular must be seen catching the `pathlib.`-prefixed spelling, since that is the only spelling the real bug ever used.

- [ ] **Step 5: Wire into CI**

In `.github/workflows/ci.yml`, immediately after the `No Yahoo Finance (CLAUDE.md standing rule)` step:

```yaml
      - name: Runtime assets ship in the package
        run: uv run python scripts/check_runtime_assets.py
```

- [ ] **Step 6: Run the full unit suite**

Run: `uv run pytest tests/unit/ -q`
Expected: PASS, including `test_runtime_asset_guard_passes` from Step 2.

- [ ] **Step 7: Commit**

```bash
git add scripts/check_runtime_assets.py .github/workflows/ci.yml tests/unit/test_runtime_assets.py
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

**Context:** These changes are already live on the mini (`/opt/argon/compose.yml`, `/opt/argon/.env`, backups `*.bak-20260720`).

**This task deploys nothing.** The mini runs from `/opt/argon/compose.yml`, a
separate file; Watchtower pulls new *images* and does not apply compose changes.
Committing `docker-compose.yml` makes the repo the record of what the mini
should look like, so the next manual sync or rebuild does not silently drop the
mount. Treat it as documentation-of-record with teeth, not as a deploy step —
and note the ordering it implies: **the mount must already be present on the
mini before Task 3's fail-loud reaches prod.** It is (applied 2026-07-20), which
is why these can ship together; verify it in Task 10 Step 6 regardless. Two environment facts drive the exact value: `~/market-warehouse/data-lake` is a **symlink** to `/Volumes/DATA_LAKE/livewire/data-lake`, and the runtime is **colima**, which mounts only that volume and **not `$HOME`**. Mounting the symlink path yields an empty directory.

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
  # Overridable so this file stays usable for local smoke on a host that has
  # no /Volumes/DATA_LAKE: export ARGON_LAKE_HOST_PATH=/some/local/lake.
  volumes:
    - ${ARGON_LAKE_HOST_PATH:-/Volumes/DATA_LAKE/livewire/data-lake}:/lake:ro
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

**`docker-compose -f docker-compose.yml config` cannot succeed on a dev machine** — the committed file declares `env_file: [/opt/argon/.env]`, a mini-only absolute path, so it exits 1 with `env file /opt/argon/.env not found` regardless of your change. Do not read that as a broken edit. (`python3 -c "import yaml…"` is also not a fallback: pyyaml is not in the system interpreter.)

Validate against a copy with a stubbed env file:

```bash
T=$(mktemp -d) && : > "$T/.env"
sed 's#env_file: \[/opt/argon/.env\]#env_file: ['"$T"'/.env]#' docker-compose.yml > "$T/dc.yml"

docker-compose -f "$T/dc.yml" config | grep -A2 'source: /Volumes/DATA_LAKE'
ARGON_LAKE_HOST_PATH=/tmp/fake-lake docker-compose -f "$T/dc.yml" config | grep -c 'source: /tmp/fake-lake'
rm -rf "$T"
```
Expected (verified at plan time against the real file): the first prints
`source: /Volumes/DATA_LAKE/livewire/data-lake` / `target: /lake` /
`read_only: true`; the second prints a non-zero count, proving the override
works.

**Every service inherits the mount, including `web` and `migrator`, and that is
fine.** It is read-only and costs nothing; splitting `x-common` into
lake-consuming and non-consuming anchors would add a second anchor and a per-
service decision to maintain, to save nothing measurable. Noted so a reviewer
does not mistake it for an oversight.

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

### Task 8: Widen the regime recovery window

**Files:**
- Modify: `src/uw_scan/worker/scheduler.py:158-164`

**Interfaces:**
- Consumes: nothing.
- Produces: `REGIME_RECOVERY_LOOKBACK_DAYS = 30`.

**Context — read this before adding anything to the healer.** An earlier draft of
this task added `vol_index_daily` to the `data_gap_healer` REGISTRY. **Do not.**
It is already there — `data_gap_healer.py:501`, inside the T7 bulk
`_entries([...], "options_chain", "freshness_only", ...)` block, and it already
appears in the generated policy doc at line 106. So are `cri_snapshots`,
`vcg_snapshots`, and `canary_snapshots`. Adding a second entry would trip
`tests/unit/reports/test_data_gap_healer_specs.py::test_registry_table_names_are_unique`.

Registration was never the gap. `freshness_only` tracks age and never heals, and
that is the *correct* mode for a lake-sourced table — there is no fetch to retry.
Detection already worked via `data_freshness.MONITORED_TABLES`; delivery is what
did not exist, which PR2 addresses. The one real defect is cosmetic (the entry is
grouped under `options_chain` with a "UW-retention" reason string, but the table
is lake-sourced) and is not worth a registry reshuffle plus a policy-doc
regeneration in a PR with a deploy clock on it.

That leaves this task with exactly one change.

- [ ] **Step 1: Widen the recovery window**

In `src/uw_scan/worker/scheduler.py`, replace the comment block and constant at lines 158-164:

```python
# Each regime scan tick checks the last N CALENDAR days for missing snapshots
# and fills them (the scanners compute `latest - timedelta(days=N)` and then
# intersect with the trading days actually present — see scanners/cri.py:337,
# vcg.py:274, canary.py:321). At 30 calendar days that is ~21 trading days.
# The window must exceed realistic TIME-TO-DETECT, not typical outage length:
# the 2026-07-08 lake outage ran 13 days, so at the previous value of 7 the
# 07-08..07-13 span would never have healed even after the mount was repaired
# — leaving a permanent hole mid-series while the recent tail looked correct.
# Per-tick cost is a set-membership check per candidate date and a scanner run
# only for dates genuinely missing a snapshot (normally zero).
REGIME_RECOVERY_LOOKBACK_DAYS = 30
```

- [ ] **Step 2: Confirm no registry or policy-doc change crept in**

```bash
git status --porcelain src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md
```
Expected: **empty output.** Both files must be untouched by this task. If either is modified, an earlier draft's registry step was applied — revert it, or CI fails on the duplicate-name test.

- [ ] **Step 3: Assert the constant — the existing selection does not exercise it**

`-k "gap_healer or registry or scheduler"` passes whether the constant is 7 or 30; nothing asserts it. Append a real check to `tests/unit/test_runtime_assets.py`:

```python
def test_regime_recovery_window_exceeds_time_to_detect() -> None:
    """A recovery window must outlast realistic time-to-detect, not the
    typical outage. The 2026-07-08 lake freeze ran 13 days; at the old value
    of 7 the first half could never have healed even after repair."""
    from uw_scan.worker.scheduler import REGIME_RECOVERY_LOOKBACK_DAYS

    assert REGIME_RECOVERY_LOOKBACK_DAYS >= 21, (
        "lookback is in CALENDAR days; keep >= 21 so a two-week undetected "
        "freeze is still healable once the input recovers"
    )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/unit/test_runtime_assets.py -k recovery -v
uv run pytest tests/unit/ -k "gap_healer or registry or scheduler" -v
```
Expected: PASS. The second command must be **unchanged from before this task** — nothing here alters the registry.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/worker/scheduler.py tests/unit/test_runtime_assets.py
git commit -m "fix(regime): widen recovery lookback 7 -> 30 calendar days

The per-scanner recover_recent_gaps enumerates candidate dates FROM
vol_index_daily, so a frozen lake looked healthy to it for 13 days. Once the
mount was repaired, a 7-day window could not have healed the 07-08..07-13
span — leaving a permanent hole mid-series while the recent tail looked
correct. A recovery window must exceed time-to-detect, not outage length."
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

**Why it needs no `--env-file`** (verified statically at plan time): the script imports `load_calibration` and `_parse_guidance_md`, and neither module reads `os.environ` at import; nor does any module in `src/` construct `Settings` at module scope. So a bare `docker run --rm "$IMAGE" python -c …` works with no DB and no credentials. `python` resolves without a `uv run` prefix because the runtime image puts `/app/.venv/bin` first on `PATH` (`docker/app.Dockerfile:55`).

If either `docker run` fails with `RuntimeError: UW_SCAN_API_KEY is not set`, someone has introduced an import-time `Settings.from_env()` — fix *that*, do not paper over it by passing an env file into the smoke.

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

# ALWAYS rebuild. Reusing an existing tag lets a stale known-good image pass
# after the source has regressed — which is the one thing this script exists
# to prevent.
echo "building $IMAGE ..."
docker build -f docker/app.Dockerfile -t "$IMAGE" .

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

If either `docker run` raises `FileNotFoundError`, the asset did not reach the image — the `git mv` landed somewhere the `COPY src/ ./src/` does not cover, or a loader was not repointed.

**It will _not_ tell you the `package-data` block is missing.** The image installs `/app/src` editable, so the assets are present whether or not `pyproject.toml` declares them. Only Task 2 Step 7b's wheel inspection catches that. Two checks, two distinct failures — do not treat either as covering the other.

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
  they also ship in release wheels.
- **`GET /api/regime/guidance` no longer degrades to an empty rule list** when
  `guidance.md` cannot be read. It was returning `[]` on a 404 from the old path
  guard; a missing runtime asset is now a loud failure.
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
  `os.environ` lookup with a home-dir fallback. Behaviour is unchanged; this
  consolidates path defaults into `config.py` so the new CI guard can enforce
  one home-dir default. (The container's recurring
  `vrp_macro_signal QQQ/IWM: skipped — FileNotFoundError` is fixed by setting
  `MARKET_WAREHOUSE_LAKE=/lake` on the deploy host, not by this change.)

### Added

- `scripts/check_runtime_assets.py` CI guard: no `Path.home()` outside
  `config.py`, no runtime path joins into `docs/`.
- `scripts/smoke_container_assets.sh`: verifies the built image can load both
  runtime assets — the only check that reproduces the cutover failure.

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

- [ ] **Step 1b: Run the integration tests this PR actually touches**

The unit job is not sufficient here — **three of this PR's edits are only exercised by integration tests**, and CI runs them (`.github/workflows/ci.yml:121-135`). Skipping this step means finding out on a pushed red branch:

```bash
uv run pytest tests/integration/api/test_regime_guidance_endpoint.py -v      # Task 2 Step 6
uv run pytest tests/integration/regime/test_canary_form_sweep_full.py -v     # Task 1 Step 6c
uv run pytest tests/unit/sources/test_lake_resolver.py -v                    # Task 4 must NOT break these
```
Expected: PASS. Needs local Postgres (`option_wizard_test`). If it is genuinely unavailable, say so explicitly in the PR description rather than implying the suite was run — do not mark this step done on an assumption.

- [ ] **Step 2: Run the container smoke**

Run: `bash scripts/smoke_container_assets.sh`
Expected: `PASS`.

- [ ] **Step 3: (removed — it duplicated Step 1)**

An earlier draft re-implemented the guard's two rules as ad-hoc greps here.
`scripts/check_runtime_assets.py`, already run in Step 1, *is* those two rules.
Two implementations of one check is one too many: they drift, and the grep
version has no allowlist so it needs a fragile `| grep -v config.py` that
inverts its own exit status. Nothing to do — proceed to Step 4.

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
- worker refuses to boot with retired R2 settings present
- CI guard + container smoke so the class of bug cannot return
- regime recovery window 7 → 30 days

Deliberately **not** here: no change to the data-gap healer REGISTRY —
`vol_index_daily` is already registered (`data_gap_healer.py:501`,
`freshness_only`), and a second entry would fail
`test_registry_table_names_are_unique`.

Spec: `docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md`
Plan: `docs/superpowers/plans/2026-07-20-runtime-asset-durability-pr1.md`

**Post-deploy verification:** `GET /api/regime/guidance` returns HTTP 500 in
prod right now. If it returns 200 after this deploys, the PR worked.

**Follow-up (separate PR):** inline per-panel staleness badges on regime and
gold/macro. The Gold page currently serves 108-day-old WGC/CB reserves data
with no indication.
BODY
)"
```

- [ ] **Step 5: Wait for CI to go green before merging**

Run: `gh pr checks --watch`
Expected: all checks pass. **Never merge on a non-green or UNSTABLE result.**

- [ ] **Step 6: After merge and deploy, verify in prod**

```bash
# 1. The falsifiable one: 500 before, 200 after.
ssh macmini 'curl -s -o /dev/null -w "guidance=%{http_code}\n" http://127.0.0.1:8400/api/regime/guidance'

# 2. Calibration loads from the IMAGE, with no docker cp keeping it alive.
ssh macmini '/opt/homebrew/bin/docker exec argon-worker-massive-0-1 python -c "
from uw_scan.cards.canary_calibration import load_calibration; load_calibration(); print(\"calibration OK from image\")"'

# 3. The mount survived the deploy (Task 3 fail-loud depends on it).
ssh macmini '/opt/homebrew/bin/docker exec argon-worker-massive-0-1 ls /lake/bronze/asset_class=volatility | head -3'

# 4. No job-failure streak from the fail-loud change.
ssh macmini 'curl -s http://127.0.0.1:8400/api/health | python3 -c "
import json,sys; d=json.load(sys.stdin)
print(\"job_failures:\", [f for f in d.get(\"job_failures\",[]) if \"lake\" in f.get(\"job_name\",\"\")] or \"none\")"'
```
Expected: `guidance=200`; `calibration OK from image` **without any `docker cp`**, proving the ephemeral workaround is no longer load-bearing; symbol dirs listed under `/lake`; and `job_failures: none` for the lake jobs.

- [ ] **Step 6b: Confirm the data actually flows — the business outcome**

The checks above prove the assets ship. This proves the outage is over. Run **after the next 03:15 ET `vol_index_lake_sync` tick**:

```bash
ssh macmini 'psql -U argon_app -d option_wizard -c "
SELECT max(trade_date) AS max_date, count(DISTINCT symbol) AS symbols
FROM uw_scan.vol_index_daily;"'
```
Expected: `max_date` equal to the most recent completed trading day and `symbols` = 18. A `max_date` still pinned to the last backfilled date means the sync is not running even though the assets load — a different bug, and this plan has not fixed it.

- [ ] **Step 7: Remove the temporary env override note**

Set `MARKET_WAREHOUSE_LAKE=/lake` in `/opt/argon/.env` (it is currently unset) and restart the workers so `vrp_macro_signal` stops skipping QQQ/IWM:

A bare `grep -q MARKET_WAREHOUSE_LAKE || echo >>` is **not safe here**: it treats a commented-out line or an existing *wrong* value as "already set" and silently leaves the outage in place. Match an active assignment, and replace rather than append:

```bash
# Back up, then set exactly one active assignment.
ssh macmini 'cp /opt/argon/.env /opt/argon/.env.bak-$(date +%Y%m%d-%H%M%S)'
ssh macmini 'sed -i "" "/^MARKET_WAREHOUSE_LAKE=/d" /opt/argon/.env && echo "MARKET_WAREHOUSE_LAKE=/lake" >> /opt/argon/.env'
ssh macmini 'grep -n "^MARKET_WAREHOUSE_LAKE=" /opt/argon/.env'
```
Expected: exactly one line, `MARKET_WAREHOUSE_LAKE=/lake`.

Then recreate and verify the value reached the **process**, not just the file — workers freeze env at fork:

```bash
ssh macmini 'cd /opt/argon && /opt/homebrew/bin/docker-compose up -d --force-recreate'
ssh macmini '/opt/homebrew/bin/docker exec argon-worker-massive-0-1 sh -c "echo MARKET_WAREHOUSE_LAKE=\$MARKET_WAREHOUSE_LAKE; ls /lake/bronze | head -3"'
```
Expected: `MARKET_WAREHOUSE_LAKE=/lake` and the bronze partitions listed.

- [ ] **Step 8: Confirm `vrp_macro_signal` actually stops skipping**

A log grep over the last 10 minutes proves nothing unless the job ran in that window — `vrp_macro_signal` is a **daily 03:45 ET cron**. Either wait for the real tick and check the following morning, or invoke the job path directly:

```bash
# After the next 03:45 ET run:
ssh macmini '/opt/homebrew/bin/docker logs --since 24h argon-worker-massive-0-1 2>&1 \
  | grep "vrp_macro_signal" | grep -c "FileNotFoundError" || echo "0 — clean"'
```
Expected: `0 — clean`, **and** at least one positive `vrp_macro_signal` line for QQQ/IWM in the same window — a zero count with no job output at all means the job did not run, not that it succeeded.

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
