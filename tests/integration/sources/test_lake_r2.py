"""Live R2 smoke test — verifies the new rails read VIX + credit-proxy ETFs.

GATING CONVENTION (matches tests/live/test_uw_smoke.py): two marks at module
level — pytest.mark.live for the marker registration, and pytest.mark.skipif
for the actual env-absent skip. The project convention is "live tests
self-skip via skipif when their required env is unset"; this repo does NOT
load .env from conftest, so the developer must export R2_* before running:

    set -a; source .env; set +a
    uv run pytest -m live tests/integration/sources/test_lake_r2.py -v

A run with the R2 env unset SKIPS (not "passes silently against fallback"):
the module-level skipif sets reason="R2_* env not set" so a misread of the
report is harder. A run with R2 env present runs the tests for real, and
schema/cred/network problems surface as assertion failures or pyarrow errors.
"""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.sources.lake import list_vol_index_symbols, read_vol_index_parquet
from uw_scan.sources.lake_resolver import resolve_lake_root

_REQUIRED_R2_ENV = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)


def _r2_env_missing() -> bool:
    return any(not os.environ.get(k, "").strip() for k in _REQUIRED_R2_ENV)


pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        _r2_env_missing(),
        reason="R2_* env not set — export R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / "
        "R2_SECRET_ACCESS_KEY / R2_BUCKET (e.g. set -a; source .env; set +a) "
        "before running this live smoke",
    ),
]


@pytest.fixture(scope="module")
def settings() -> Settings:
    # Construct Settings directly from R2 env only — Settings.from_env() would
    # require UW_SCAN_API_KEY, which has no business gating an R2 smoke. The
    # module-level skipif above guarantees these env vars exist when this
    # fixture is reached.
    endpoint_override = os.environ.get("R2_ENDPOINT_OVERRIDE", "").strip() or None
    return Settings(
        api_key=SecretStr("dummy-not-used-by-r2-smoke"),
        r2_account_id=os.environ["R2_ACCOUNT_ID"].strip(),
        r2_access_key_id=SecretStr(os.environ["R2_ACCESS_KEY_ID"].strip()),
        r2_secret_access_key=SecretStr(os.environ["R2_SECRET_ACCESS_KEY"].strip()),
        r2_bucket=os.environ["R2_BUCKET"].strip(),
        r2_endpoint_override=endpoint_override,
    )


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
