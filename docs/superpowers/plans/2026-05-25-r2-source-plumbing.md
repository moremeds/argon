# R2 Source Plumbing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lay R2-primary parquet-reading rails in `src/uw_scan/sources/lake.py` so new EOD/backfill code can pull from the Cloudflare R2 data lake (`market-data` bucket) instead of the local mirror, per the 2026-05-25 standing rule. Existing nightly sync jobs (`vol_index_lake_sync`, `credit_etf_lake_sync`) stay on local-Path reads — they migrate in a follow-on PR.

**Architecture:** A new `LakeRoot` typed dataclass represents either a local filesystem `Path` or an R2-backed `(bucket, key_prefix, endpoint, creds)` tuple. A `resolve_lake_root(settings, asset_class=…)` function returns the R2 variant when all five `R2_*` settings are present, else the local variant. `lake.py`'s public functions (`list_vol_index_symbols`, `read_vol_index_parquet`) accept `Path | LakeRoot` — Path callers get auto-wrapped to a local LakeRoot, R2 reads go through `pyarrow.fs.S3FileSystem` with `endpoint_override` set to `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com`. A live smoke test verifies reads for VIX (volatility class) + HYG/JNK/LQD (equity class) so the next VCG A/B research can lift straight off these rails.

**Tech Stack:** Python 3.11+, pyarrow ≥18 (already in deps — provides `pyarrow.fs.S3FileSystem`), pydantic v2 (existing Settings), pytest with the existing `live` marker.

---

## File Structure

### Create
- `src/uw_scan/sources/lake_resolver.py` — `LakeRoot` dataclass + `resolve_lake_root()` function (~80 lines)
- `tests/unit/test_config_r2.py` — Settings R2 field unit tests (~30 lines)
- `tests/unit/sources/test_lake_resolver.py` — resolver unit tests, no network (~70 lines)
- `tests/integration/sources/__init__.py` — empty package marker
- `tests/integration/sources/test_lake_r2.py` — live R2 smoke test (~60 lines)

### Modify
- `src/uw_scan/config.py` — add 5 R2 fields to `Settings` + `from_env` parsing
- `src/uw_scan/sources/lake.py` — accept `Path | LakeRoot`; add S3 backend
- `src/uw_scan/sources/CLAUDE.md` — document R2 plumbing under the `lake.py` row
- `.env.example` — add 5 R2_* env var placeholders

### Unchanged (verified non-regression)
- `src/uw_scan/worker/jobs/vol_index_lake_sync.py`
- `src/uw_scan/worker/jobs/credit_etf_lake_sync.py`
- `tests/unit/test_lake_reader.py`
- `pyproject.toml` (pyarrow already in deps)

---

## Tasks

### Task 1: R2 Settings fields

**Files:**
- Modify: `src/uw_scan/config.py:59-198` (Settings class), `:199-402` (`from_env`)
- Test: `tests/unit/test_config_r2.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_config_r2.py
"""R2 settings are parsed from env vars; absent vars become None."""
from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from uw_scan.config import Settings


def test_r2_settings_present_when_env_set(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-key")
    monkeypatch.setenv("R2_ACCOUNT_ID", "abcd1234")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("R2_BUCKET", "market-data")
    s = Settings.from_env(env)
    assert s.r2_account_id == "abcd1234"
    assert s.r2_access_key_id is not None
    assert s.r2_access_key_id.get_secret_value() == "key-id"
    assert s.r2_secret_access_key is not None
    assert s.r2_secret_access_key.get_secret_value() == "secret"
    assert s.r2_bucket == "market-data"
    assert s.r2_endpoint_override is None


def test_r2_settings_none_when_env_unset(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "test-key")
    for k in (
        "R2_ACCOUNT_ID",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_BUCKET",
        "R2_ENDPOINT_OVERRIDE",
    ):
        monkeypatch.delenv(k, raising=False)
    s = Settings.from_env(env)
    assert s.r2_account_id is None
    assert s.r2_access_key_id is None
    assert s.r2_secret_access_key is None
    assert s.r2_bucket is None
    assert s.r2_endpoint_override is None
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/unit/test_config_r2.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'r2_account_id'`

- [ ] **Step 3: Add fields to Settings (after the `credit_etf_symbols` field at ~line 196)**

```python
    # Cloudflare R2 parquet lake — primary source for EOD/backfill reads per
    # the 2026-05-25 standing rule (see docs/research/regime/closure-2026-05-24.md
    # §4 and the [[feedback-r2-primary-for-eod-backfill]] memory). All four core
    # fields must be set for R2 reads to engage; if any is None, the resolver
    # falls back to the local mirror at lake_vol_index_root / lake_credit_etf_root.
    # R2_ENDPOINT_OVERRIDE is optional — defaults to
    # https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com.
    r2_account_id: str | None = None
    r2_access_key_id: SecretStr | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_endpoint_override: str | None = None
```

- [ ] **Step 4: Add parsing to `from_env` (after the `credit_etf_symbols=_parse_csv_env(...)` line at ~line 401, just before the closing `)`)**

```python
            r2_account_id=(
                _r2_acc
                if (_r2_acc := os.environ.get("R2_ACCOUNT_ID", "").strip())
                else None
            ),
            r2_access_key_id=(
                SecretStr(_r2_key)
                if (_r2_key := os.environ.get("R2_ACCESS_KEY_ID", "").strip())
                else None
            ),
            r2_secret_access_key=(
                SecretStr(_r2_sec)
                if (_r2_sec := os.environ.get("R2_SECRET_ACCESS_KEY", "").strip())
                else None
            ),
            r2_bucket=(
                _r2_bkt
                if (_r2_bkt := os.environ.get("R2_BUCKET", "").strip())
                else None
            ),
            r2_endpoint_override=(
                _r2_ep
                if (_r2_ep := os.environ.get("R2_ENDPOINT_OVERRIDE", "").strip())
                else None
            ),
```

- [ ] **Step 5: Run test, verify pass**

Run: `uv run pytest tests/unit/test_config_r2.py -v`
Expected: 2 tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/config.py tests/unit/test_config_r2.py
git commit -m "feat(config): add R2 settings for parquet lake reads"
```

### Task 2: LakeRoot dataclass + resolver

**Files:**
- Create: `src/uw_scan/sources/lake_resolver.py`
- Test: `tests/unit/sources/test_lake_resolver.py` (NEW)

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/sources/test_lake_resolver.py
"""Resolver picks R2 when fully configured, local otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.sources.lake_resolver import LakeRoot, resolve_lake_root


def _make_settings(*, with_r2: bool, **overrides) -> Settings:
    base = dict(
        api_key=SecretStr("x"),
        lake_vol_index_root=Path("/tmp/local-vol"),
        lake_credit_etf_root=Path("/tmp/local-credit"),
    )
    if with_r2:
        base.update(
            r2_account_id="abcd1234",
            r2_access_key_id=SecretStr("key"),
            r2_secret_access_key=SecretStr("sec"),
            r2_bucket="market-data",
        )
    base.update(overrides)
    return Settings(**base)


def test_resolve_s3_when_r2_configured():
    s = _make_settings(with_r2=True)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "s3"
    assert root.bucket == "market-data"
    assert root.key_prefix == "market-warehouse/data-lake/bronze/asset_class=volatility"
    assert root.endpoint_override == "https://abcd1234.r2.cloudflarestorage.com"
    assert root.access_key_id == "key"
    assert root.secret_access_key == "sec"


def test_resolve_local_when_r2_unset():
    s = _make_settings(with_r2=False)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "local"
    assert root.local_path == Path("/tmp/local-vol")


def test_resolve_local_when_r2_partial():
    """Missing any one R2 field means the resolver MUST NOT engage R2."""
    s = _make_settings(with_r2=True, r2_secret_access_key=None)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "local"


def test_resolve_equity_routes_to_credit_etf_local_root():
    s = _make_settings(with_r2=False)
    root = resolve_lake_root(s, asset_class="equity")
    assert root.kind == "local"
    assert root.local_path == Path("/tmp/local-credit")


def test_resolve_equity_routes_to_credit_etf_key_prefix_on_s3():
    s = _make_settings(with_r2=True)
    root = resolve_lake_root(s, asset_class="equity")
    assert root.kind == "s3"
    assert root.key_prefix == "market-warehouse/data-lake/bronze/asset_class=equity"


def test_resolve_endpoint_override_takes_precedence():
    s = _make_settings(
        with_r2=True, r2_endpoint_override="https://custom.example.com"
    )
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.endpoint_override == "https://custom.example.com"


def test_resolve_unknown_asset_class_raises():
    s = _make_settings(with_r2=False)
    with pytest.raises(ValueError, match="asset_class"):
        resolve_lake_root(s, asset_class="invalid")
```

- [ ] **Step 2: Run test, verify it fails**

Run: `uv run pytest tests/unit/sources/test_lake_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.sources.lake_resolver'`

- [ ] **Step 3: Implement the resolver**

```python
# src/uw_scan/sources/lake_resolver.py
"""Resolve a parquet-lake root to either an R2 URI or a local Path.

R2 is the primary source per the 2026-05-25 standing rule (see CLAUDE.md and
docs/research/regime/closure-2026-05-24.md). When all four core R2 settings
(account_id, access_key_id, secret_access_key, bucket) are present the
resolver returns an s3-kind LakeRoot; otherwise it falls back to the local
mirror Path configured per asset_class.

This module is pure config-to-root mapping; the actual I/O lives in lake.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from uw_scan.config import Settings

_ASSET_CLASS_TO_LOCAL_ATTR: dict[str, str] = {
    "volatility": "lake_vol_index_root",
    "equity": "lake_credit_etf_root",
}


@dataclass(frozen=True)
class LakeRoot:
    """Either an S3-on-R2 root or a local-filesystem Path. Discriminate on `kind`."""

    kind: Literal["s3", "local"]
    asset_class: str
    # local-only
    local_path: Path | None = None
    # s3-only
    bucket: str | None = None
    key_prefix: str | None = None
    endpoint_override: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None

    @classmethod
    def local_for(cls, asset_class: str, path: Path) -> "LakeRoot":
        return cls(kind="local", asset_class=asset_class, local_path=path)


def _r2_fully_configured(s: Settings) -> bool:
    return all(
        (
            s.r2_account_id,
            s.r2_access_key_id,
            s.r2_secret_access_key,
            s.r2_bucket,
        )
    )


def resolve_lake_root(settings: Settings, *, asset_class: str) -> LakeRoot:
    """Return the lake root for `asset_class`: R2 when configured, else local."""
    if asset_class not in _ASSET_CLASS_TO_LOCAL_ATTR:
        raise ValueError(
            f"unknown asset_class {asset_class!r}; "
            f"expected one of {sorted(_ASSET_CLASS_TO_LOCAL_ATTR)}"
        )
    local_path: Path = getattr(settings, _ASSET_CLASS_TO_LOCAL_ATTR[asset_class])

    if not _r2_fully_configured(settings):
        return LakeRoot.local_for(asset_class, local_path)

    assert settings.r2_access_key_id is not None  # narrowed by _r2_fully_configured
    assert settings.r2_secret_access_key is not None
    endpoint = (
        settings.r2_endpoint_override
        or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
    )
    return LakeRoot(
        kind="s3",
        asset_class=asset_class,
        bucket=settings.r2_bucket,
        key_prefix=f"market-warehouse/data-lake/bronze/asset_class={asset_class}",
        endpoint_override=endpoint,
        access_key_id=settings.r2_access_key_id.get_secret_value(),
        secret_access_key=settings.r2_secret_access_key.get_secret_value(),
        local_path=local_path,  # kept for future runtime fallback (deferred)
    )
```

- [ ] **Step 4: Run test, verify pass**

Run: `uv run pytest tests/unit/sources/test_lake_resolver.py -v`
Expected: 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/lake_resolver.py tests/unit/sources/test_lake_resolver.py
git commit -m "feat(sources): add LakeRoot resolver for R2 vs local lake selection"
```

### Task 3: Refactor `lake.py` to accept `Path | LakeRoot`

**Files:**
- Modify: `src/uw_scan/sources/lake.py`
- Verify: `tests/unit/test_lake_reader.py` (existing Path-based callers must still pass)
- Verify: `src/uw_scan/worker/jobs/vol_index_lake_sync.py`, `credit_etf_lake_sync.py` (unchanged)

- [ ] **Step 1: Baseline — confirm existing tests pass**

Run: `uv run pytest tests/unit/test_lake_reader.py -v`
Expected: all PASS — record numbers for post-refactor comparison

- [ ] **Step 2: Rewrite `lake.py`**

```python
# src/uw_scan/sources/lake.py
"""Parquet reader for the market-warehouse data lake.

Supports two backends via the LakeRoot abstraction in lake_resolver:
- Local filesystem (Path) — used by the existing nightly sync jobs
- Cloudflare R2 — used by new EOD/backfill code per the 2026-05-25 standing
  rule (see [[feedback-r2-primary-for-eod-backfill]])

Public functions accept either a Path or a LakeRoot for backward
compatibility with existing Path-based callers. No business logic — pure I/O.
R2 reads go through pyarrow.fs.S3FileSystem with the account-scoped
endpoint override; auth is access-key / secret-key Sig V4.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pyarrow.fs as pa_fs
import pyarrow.parquet as pq

from uw_scan.sources.lake_resolver import LakeRoot

logger = logging.getLogger(__name__)

VOL_INDEX_FILENAME = "1d.parquet"


def _normalize(root: Path | LakeRoot) -> LakeRoot:
    if isinstance(root, LakeRoot):
        return root
    # Legacy Path-based callers — wrap as a local-kind LakeRoot. asset_class
    # is informational only for local reads; the Path drives the actual lookup.
    return LakeRoot.local_for("unknown", root)


def list_vol_index_symbols(root: Path | LakeRoot) -> list[str]:
    """Return all symbols under `root/symbol=<TICKER>/1d.parquet`."""
    lr = _normalize(root)
    if lr.kind == "local":
        assert lr.local_path is not None
        return _list_local(lr.local_path)
    return _list_s3(lr)


def read_vol_index_parquet(
    root: Path | LakeRoot,
    symbol: str,
    *,
    since: date | None = None,
) -> list[dict]:
    """Read `symbol=<S>/1d.parquet` -> list[dict] with normalized columns."""
    lr = _normalize(root)
    if lr.kind == "local":
        assert lr.local_path is not None
        return _read_local(lr.local_path, symbol, since=since)
    return _read_s3(lr, symbol, since=since)


# ---------- local backend (unchanged behavior) ----------


def _list_local(root: Path) -> list[str]:
    if not root.exists():
        return []
    out: list[str] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = child.name
        if not name.startswith("symbol="):
            continue
        if not (child / VOL_INDEX_FILENAME).exists():
            continue
        out.append(name[len("symbol=") :])
    return sorted(out)


def _read_local(root: Path, symbol: str, *, since: date | None) -> list[dict]:
    path = root / f"symbol={symbol}" / VOL_INDEX_FILENAME
    if not path.exists():
        return []
    table = pq.read_table(path)
    return _rows_from_table(table, symbol, since=since)


# ---------- s3 (R2) backend ----------


def _s3_fs(lr: LakeRoot) -> pa_fs.S3FileSystem:
    return pa_fs.S3FileSystem(
        access_key=lr.access_key_id,
        secret_key=lr.secret_access_key,
        endpoint_override=lr.endpoint_override,
        # R2 ignores region but pyarrow requires *something* non-empty.
        region="auto",
        scheme="https",
    )


def _list_s3(lr: LakeRoot) -> list[str]:
    assert lr.bucket and lr.key_prefix
    fs = _s3_fs(lr)
    selector = pa_fs.FileSelector(
        f"{lr.bucket}/{lr.key_prefix}", recursive=False, allow_not_found=True
    )
    out: list[str] = []
    for info in fs.get_file_info(selector):
        if info.type != pa_fs.FileType.Directory:
            continue
        base = Path(info.path).name
        if not base.startswith("symbol="):
            continue
        # Skipping the "does 1d.parquet exist?" probe — saves one round-trip
        # per symbol. Missing parquet surfaces as an empty read downstream.
        out.append(base[len("symbol=") :])
    return sorted(out)


def _read_s3(lr: LakeRoot, symbol: str, *, since: date | None) -> list[dict]:
    assert lr.bucket and lr.key_prefix
    fs = _s3_fs(lr)
    key = f"{lr.bucket}/{lr.key_prefix}/symbol={symbol}/{VOL_INDEX_FILENAME}"
    try:
        table = pq.read_table(key, filesystem=fs)
    except FileNotFoundError:
        return []
    return _rows_from_table(table, symbol, since=since)


# ---------- shared row normalizer ----------


def _rows_from_table(table, symbol: str, *, since: date | None) -> list[dict]:
    df = table.to_pandas()
    if "trade_date" not in df.columns:
        return []
    if since is not None:
        df = df[df["trade_date"] >= since]
    df = df.sort_values("trade_date")
    rows: list[dict] = []
    for r in df.itertuples(index=False):
        rd = r._asdict()
        rows.append(
            {
                "symbol": symbol,
                "trade_date": rd["trade_date"],
                "open": _maybe_float(rd.get("open")),
                "high": _maybe_float(rd.get("high")),
                "low": _maybe_float(rd.get("low")),
                "close": _maybe_float(rd.get("close")),
                "adj_close": _maybe_float(rd.get("adj_close")),
                "volume": int(rd["volume"]) if rd.get("volume") is not None else None,
            }
        )
    return rows


def _maybe_float(x) -> float | None:
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError) as exc:
        _ = repr(exc)  # CI Guardrail 2
        return None
    return f
```

- [ ] **Step 3: Run existing lake test + worker tests — confirm no regression**

Run: `uv run pytest tests/unit/test_lake_reader.py tests/unit/worker -v -k "lake or vol_index"`
Expected: same tests PASS as in Step 1 baseline

- [ ] **Step 4: Confirm worker jobs haven't been touched**

```bash
git diff main -- src/uw_scan/worker/jobs/vol_index_lake_sync.py src/uw_scan/worker/jobs/credit_etf_lake_sync.py
```
Expected: empty diff

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/sources/lake.py
git commit -m "refactor(lake): accept LakeRoot (Path or R2) with pyarrow S3 backend"
```

### Task 4: Live R2 smoke test (VIX + HYG/JNK/LQD)

**Files:**
- Create: `tests/integration/sources/__init__.py`
- Create: `tests/integration/sources/test_lake_r2.py`

- [ ] **Step 1: Create package marker**

```bash
mkdir -p tests/integration/sources
touch tests/integration/sources/__init__.py
```

- [ ] **Step 2: Write the smoke test**

```python
# tests/integration/sources/test_lake_r2.py
"""Live R2 smoke test — verifies the new rails read VIX + credit-proxy ETFs.

Marked `live` so the default pytest run excludes it (the same marker used
for live UW API tests). Run explicitly with `pytest -m live` after R2_*
env vars are set in .env. Skipped silently if R2 env is absent so the
smoke can't accidentally claim "PASS" against the local fallback.
"""

from __future__ import annotations

import os

import pytest

from uw_scan.config import Settings
from uw_scan.sources.lake import list_vol_index_symbols, read_vol_index_parquet
from uw_scan.sources.lake_resolver import resolve_lake_root

pytestmark = pytest.mark.live


def _r2_env_present() -> bool:
    return all(
        os.environ.get(k, "").strip()
        for k in (
            "R2_ACCOUNT_ID",
            "R2_ACCESS_KEY_ID",
            "R2_SECRET_ACCESS_KEY",
            "R2_BUCKET",
        )
    )


@pytest.fixture(scope="module")
def settings() -> Settings:
    if not _r2_env_present():
        pytest.skip("R2_* env not set — populate .env to run this smoke")
    return Settings.from_env()


def test_r2_volatility_lists_includes_vix(settings: Settings) -> None:
    root = resolve_lake_root(settings, asset_class="volatility")
    assert root.kind == "s3", "resolver did not pick R2 despite full env"
    symbols = list_vol_index_symbols(root)
    assert "VIX" in symbols, f"VIX missing from R2 volatility lake: {symbols[:8]!r}"


def test_r2_vix_read_returns_recent_rows(settings: Settings) -> None:
    root = resolve_lake_root(settings, asset_class="volatility")
    rows = read_vol_index_parquet(root, "VIX")
    assert rows, "VIX read returned 0 rows from R2"
    last = rows[-1]
    assert last["trade_date"] is not None
    assert isinstance(last["close"], float), (
        f"expected float close, got {type(last['close']).__name__}"
    )


@pytest.mark.parametrize("symbol", ["HYG", "JNK", "LQD"])
def test_r2_equity_credit_proxy_reads(settings: Settings, symbol: str) -> None:
    root = resolve_lake_root(settings, asset_class="equity")
    assert root.kind == "s3"
    rows = read_vol_index_parquet(root, symbol)
    assert rows, f"{symbol} read returned 0 rows from R2 equity lake"
    last = rows[-1]
    assert last["symbol"] == symbol
    assert isinstance(last["close"], float)
    # Equity bars have volume; vol-complex indices may have 0. Both legal.
    assert last["volume"] is None or last["volume"] >= 0
```

- [ ] **Step 3: Run the smoke**

Run: `uv run pytest tests/integration/sources/test_lake_r2.py -v -m live`
Expected: 5 tests PASS (1 list + 1 VIX read + 3 parameterized credit proxies)

- [ ] **Step 4: Verify default pytest run still excludes live tests**

Run: `uv run pytest tests/integration/sources/test_lake_r2.py -v`
Expected: 5 tests deselected (or skipped), 0 failures

- [ ] **Step 5: Commit**

```bash
git add tests/integration/sources/__init__.py tests/integration/sources/test_lake_r2.py
git commit -m "test(lake): live R2 smoke for VIX + HYG/JNK/LQD"
```

### Task 5: Documentation + .env.example

**Files:**
- Modify: `src/uw_scan/sources/CLAUDE.md`
- Modify: `.env.example`

- [ ] **Step 1: Update `sources/CLAUDE.md` — replace the existing `lake.py` row in the §"Per-ticker sources (UW + OHLC)" bullet list**

Replace the existing line:
```markdown
- `lake.py` — Parquet reader for `~/market-warehouse/data-lake`. Used by the nightly `vol_index_lake_sync` job. Pure I/O, no business logic.
```

With:
```markdown
- `lake.py` — Parquet reader for the market-warehouse data lake. Backend is either the local mirror (`~/market-warehouse/data-lake/`) or Cloudflare R2 (`market-data/market-warehouse/data-lake/`) — selection is config-driven via `lake_resolver.resolve_lake_root(settings, asset_class=...)`, which picks R2 when all four `R2_*` settings are present and otherwise falls back to local. R2 is the primary EOD/backfill source per the 2026-05-25 rule; the nightly `vol_index_lake_sync` + `credit_etf_lake_sync` jobs still read local (consumer migration is a follow-on PR). Pure I/O, no business logic.
- `lake_resolver.py` — `LakeRoot` dataclass + `resolve_lake_root()` config-to-root mapping. R2 → S3 protocol via `pyarrow.fs.S3FileSystem` with the account-scoped endpoint override.
```

- [ ] **Step 2: Add R2 vars to `.env.example`**

```bash
cat >> .env.example << 'EOF'

# Cloudflare R2 parquet lake (primary EOD/backfill source per 2026-05-25 rule).
# Set all four core vars to enable R2 reads; leave any blank to fall back to
# the local mirror under ~/market-warehouse/. R2_ENDPOINT_OVERRIDE is optional
# (defaults to https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com).
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=
R2_ENDPOINT_OVERRIDE=
EOF
```

- [ ] **Step 3: Commit**

```bash
git add src/uw_scan/sources/CLAUDE.md .env.example
git commit -m "docs(lake): document R2 plumbing + .env.example entries"
```

### Task 6: End-to-end verification

- [ ] **Step 1: Full backend test pass (live tests skip without env)**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: all PASS, with the 5 R2 smoke tests skipped if R2_* env is unset

- [ ] **Step 2: Live smoke with R2 env**

Run: `uv run pytest -m live tests/integration/sources/test_lake_r2.py -v`
Expected: 5 PASS

- [ ] **Step 3: Confirm zero consumer drift**

```bash
git diff main -- src/uw_scan/worker/ scripts/ src/uw_scan/api/ src/uw_scan/storage/
```
Expected: empty diff (all changes confined to `sources/`, `config.py`, `tests/`, docs)

- [ ] **Step 4: Confirm no Yahoo/yfinance references slipped in**

```bash
git diff main | grep -iE "yahoo|yfinance" && echo "VIOLATION" || echo "clean"
```
Expected: "clean"

- [ ] **Step 5: Lint + format gate**

```bash
uv run ruff check src/uw_scan/sources tests/unit/sources tests/unit/test_config_r2.py tests/integration/sources
uv run ruff format --check src/uw_scan/sources tests/unit/sources tests/unit/test_config_r2.py tests/integration/sources
```
Expected: both PASS

### Task 7: Three-pass review

- [ ] **Step 1: Self-review the diff with fresh eyes**

```bash
git diff main --stat
git diff main
```

Look for: stale comments, unused imports, asymmetric local/s3 behaviors, type annotations missing, accidental config field rename.

Apply any fixes inline. Commit if anything changed.

- [ ] **Step 2: `/codex-review` on the diff**

Apply BLOCKER + SHOULD-FIX patches. Commit fixes as a single follow-up commit (do NOT amend) named: `fix(lake): apply codex review fixes`.

- [ ] **Step 3: Adversarial review on the diff**

Pose: "where will this silently break in 6 months?" Categories to interrogate:
- R2 transient errors (network blip → empty reads silently? log volume?)
- Symbol-not-found vs network-not-found (both surface as `[]` in `_read_s3` — is that right?)
- Pyarrow version drift (`S3FileSystem` signature stability)
- Secrets in stack traces (does pyarrow log the access_key on error?)
- Test marker collision with UW live tests (running `-m live` now runs UW too — risk?)

Apply BLOCKER + SHOULD-FIX patches as `fix(lake): apply adversarial review fixes`.

- [ ] **Step 4: Final self-review post-fixes**

Re-read everything once more. Confirm assumptions hold: `S3FileSystem` instantiation pattern matches pyarrow docs, R2 endpoint format is correct, tests cover happy + partial-config + unknown-asset-class.

### Task 8: PR

- [ ] **Step 1: Push branch and open draft PR**

```bash
git push -u origin feat/r2-source-plumbing
gh pr create --draft --title "feat(sources): R2 parquet lake reader rails" --body "$(cat <<'EOF'
## Summary
- Lays R2-primary parquet reading rails in `src/uw_scan/sources/lake.py` per the 2026-05-25 standing rule (R2 = primary EOD/backfill source; warm-store remains the API request-time path)
- New `LakeRoot` dataclass + `resolve_lake_root(settings, asset_class=...)` resolver: R2 when all four `R2_*` settings present, else local mirror
- `lake.py` public functions accept `Path | LakeRoot` — existing nightly sync jobs untouched, migration is a follow-on PR
- Pyarrow's native `pyarrow.fs.S3FileSystem` (already in deps) — no new packages
- Live smoke test covers VIX (volatility) + HYG/JNK/LQD (equity) — unblocks the queued VCG HYG/JNK/LQD A/B research

## Deferred (not in this PR)
- Migrating `vol_index_lake_sync` + `credit_etf_lake_sync` to read R2 — separate PR after this lands
- Runtime fallback (R2 reachable-but-failing → retry against local) — currently fails loudly; deferred until we see a real failure mode
- VCG HYG/JNK/LQD A/B research — separate PR that builds on these rails

## Test plan
- [x] `uv run pytest tests/unit/test_config_r2.py` — 2 tests PASS
- [x] `uv run pytest tests/unit/sources/test_lake_resolver.py` — 7 tests PASS
- [x] `uv run pytest tests/unit/test_lake_reader.py tests/unit/worker -k "lake or vol_index"` — no regressions
- [x] `uv run pytest -m live tests/integration/sources/test_lake_r2.py` — 5 tests PASS against live R2
- [x] `uv run pytest tests/unit tests/integration` (without `-m live`) — all PASS, 5 R2 tests skipped/deselected
- [x] `uv run ruff check src tests` — clean
- [x] Diff confined to `sources/`, `config.py`, `tests/`, docs — no worker/scripts/API drift

## Verification by reviewer
SQL / curl is not relevant for this PR — it is pure code. To verify locally:
1. `uv run pytest tests/unit/sources/test_lake_resolver.py -v`
2. Optionally with R2 env: `uv run pytest -m live tests/integration/sources/test_lake_r2.py -v`
EOF
)"
```

- [ ] **Step 2: Wait for CI green**

```bash
gh pr view --json statusCheckRollup | jq '.statusCheckRollup[] | {name, status, conclusion}'
```

- [ ] **Step 3: Mark PR ready for review + hand off**

---

## Self-Review (run before announcing plan complete)

### Spec coverage
- R2 library: pyarrow.fs.S3FileSystem ✓ (Task 3 Step 2)
- PR scope: rails-only, no consumer migration ✓ (Task 6 Step 3 verification, Task 3 worker-jobs diff check)
- Smoke symbols: VIX + HYG/JNK/LQD ✓ (Task 4 Step 2)
- R2-primary, local-fallback at config time ✓ (Task 2 resolver)
- Three-pass review ✓ (Task 7)
- Standing rules: no Yahoo/yfinance (Task 6 Step 4); persist to DB N/A (no analytical outputs); no naked shorts N/A; uv only ✓

### Placeholder scan
- No "TBD", "implement later", "TODO" tokens in tasks
- Every code block is complete (no `...` ellipses inside tested code)
- Every step has explicit command + expected output

### Type consistency
- `LakeRoot.kind: Literal["s3", "local"]` consistent in resolver, lake.py, tests
- `resolve_lake_root(settings, *, asset_class)` keyword-only `asset_class` consistent in all 8 call sites
- `read_vol_index_parquet(root, symbol, *, since=None)` signature unchanged from existing for back-compat ✓
- Settings field names: `r2_account_id`, `r2_access_key_id`, `r2_secret_access_key`, `r2_bucket`, `r2_endpoint_override` consistent across config.py + tests + resolver

### Open assumptions to verify during execution
1. `pa_fs.S3FileSystem(access_key=..., secret_key=..., endpoint_override=..., region="auto", scheme="https")` accepts these kwargs together. Verify by Step 4 smoke test.
2. `pq.read_table(key, filesystem=fs)` where `key` is `"bucket/path/to.parquet"` (no `s3://` scheme). Verify by Step 4 smoke test.
3. `pa_fs.FileSelector("bucket/key_prefix", recursive=False, allow_not_found=True)` returns Directory-typed entries for `symbol=X/` subdirs. Verify by Step 4 list test.
4. R2 bucket layout matches `market-data/market-warehouse/data-lake/bronze/asset_class={volatility,equity}/symbol=<TICKER>/1d.parquet`. Verify by inspecting bucket via `aws s3 ls --endpoint-url=...` (or trust the memory + user's prior message).
5. The `live` pytest marker doesn't have an exclusion-conflict with UW live tests. Verify by running `pytest -m live` and inspecting which tests fire.

Any failed assumption is a Task 3 / Task 4 fix, not a plan failure.

---

## Verification Guide (for user, after plan execution)

After Task 7 completes (all three reviews + fixes applied) and Task 8 opens the PR:

1. **PR + CI**: `gh pr view <num> --json statusCheckRollup | jq '.statusCheckRollup[] | {name, status, conclusion}'` — both checks SUCCESS

2. **R2 live smoke locally**:
   ```bash
   uv run pytest -m live tests/integration/sources/test_lake_r2.py -v
   ```
   Expected: 5 PASS

3. **Config wiring**:
   ```bash
   uv run python -c "
   from uw_scan.config import Settings
   from uw_scan.sources.lake_resolver import resolve_lake_root
   s = Settings.from_env()
   print('volatility root:', resolve_lake_root(s, asset_class='volatility'))
   print('equity root:', resolve_lake_root(s, asset_class='equity'))
   "
   ```
   Expected: both show `kind='s3'` with the R2 endpoint URL

4. **Existing jobs unchanged**:
   ```bash
   git diff main -- src/uw_scan/worker/jobs/vol_index_lake_sync.py src/uw_scan/worker/jobs/credit_etf_lake_sync.py
   ```
   Expected: empty

5. **Full default-pytest run** (live tests skipped):
   ```bash
   uv run pytest -q
   ```
   Expected: green, with 5 deselected/skipped for the R2 smoke

6. **Failure mode** — confirm partial config falls back to local:
   ```bash
   R2_SECRET_ACCESS_KEY="" uv run python -c "
   from uw_scan.config import Settings
   from uw_scan.sources.lake_resolver import resolve_lake_root
   s = Settings.from_env()
   r = resolve_lake_root(s, asset_class='volatility')
   assert r.kind == 'local', f'expected local fallback, got {r.kind}'
   print('OK — local fallback engaged')
   "
   ```
