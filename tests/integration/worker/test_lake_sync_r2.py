"""Live R2 smoke for the lake-sync jobs (post-migration).

Proves the scheduler-side wire — resolve_lake_root → LakeRoot(kind='s3') →
run_vol_index_lake_sync / run_credit_etf_lake_sync → DB upsert — works
end-to-end against the real R2 bucket and a real Postgres.

GATING: matches tests/integration/sources/test_lake_r2.py — module-level
pytestmark with pytest.mark.live + pytest.mark.skipif on R2_* env. Default
pytest runs skip these; the developer must export R2_* explicitly:

    set -a; source .env; set +a
    uv run pytest -m live tests/integration/worker/test_lake_sync_r2.py -v

Note: also requires the seeded_db_empty_cards fixture, which transitively
needs UW_SCAN_TEST_DB_NAME pointing at an isolated Postgres database. The
fixture drops + remigrates the schema on each test invocation.
"""

from __future__ import annotations

import os

import pytest
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.sources.lake_resolver import resolve_lake_root
from uw_scan.storage.vol_index_repository import VolIndexRepository
from uw_scan.worker.jobs.credit_etf_lake_sync import run_credit_etf_lake_sync
from uw_scan.worker.jobs.vol_index_lake_sync import run_vol_index_lake_sync

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
        "before running this live sync test",
    ),
]


def _r2_settings() -> Settings:
    """Build a Settings with R2 fields populated from the live env.

    Skips Settings.from_env() because that requires UW_SCAN_API_KEY which is
    unrelated to the R2 path. Locally-resolved lake roots stay at their
    Settings defaults — irrelevant because all four R2_* are set so
    resolve_lake_root returns an s3-kind LakeRoot.
    """
    endpoint_override = os.environ.get("R2_ENDPOINT_OVERRIDE", "").strip() or None
    return Settings(
        api_key=SecretStr("dummy-not-used-by-r2-sync-smoke"),
        r2_account_id=os.environ["R2_ACCOUNT_ID"].strip(),
        r2_access_key_id=SecretStr(os.environ["R2_ACCESS_KEY_ID"].strip()),
        r2_secret_access_key=SecretStr(os.environ["R2_SECRET_ACCESS_KEY"].strip()),
        r2_bucket=os.environ["R2_BUCKET"].strip(),
        r2_endpoint_override=endpoint_override,
    )


def test_vol_index_lake_sync_pulls_from_r2(seeded_db_empty_cards) -> None:
    """run_vol_index_lake_sync against R2 inserts at least VIX into vol_index_daily.

    Proves the end-to-end wire: scheduler-style resolve_lake_root call →
    LakeRoot(kind='s3') → _read_s3 path in lake.py → repository upsert.
    """
    settings = _r2_settings()
    root = resolve_lake_root(settings, asset_class="volatility")
    assert root.kind == "s3", "resolver did not pick R2 despite full env"

    summary = run_vol_index_lake_sync(seeded_db_empty_cards.conn, root=root)
    assert summary["symbols"] > 0, "expected R2 volatility lake to have symbols"
    assert summary["rows"] > 0, "expected R2 volatility lake to yield rows"

    repo = VolIndexRepository(seeded_db_empty_cards.conn, schema="uw_scan")
    vix_history = repo.fetch_history("VIX", days=30)
    assert vix_history, "VIX rows did not land in vol_index_daily after R2 sync"


def test_credit_etf_lake_sync_pulls_from_r2(seeded_db_empty_cards) -> None:
    """run_credit_etf_lake_sync against R2 inserts HYG/JNK/LQD rows.

    Mirrors the volatility smoke but for the equity asset_class path,
    proving the per-asset_class routing in resolve_lake_root works.
    """
    settings = _r2_settings()
    root = resolve_lake_root(settings, asset_class="equity")
    assert root.kind == "s3"

    summary = run_credit_etf_lake_sync(
        seeded_db_empty_cards.conn,
        root=root,
        symbols=["HYG", "JNK", "LQD"],
    )
    assert summary["symbols"] == 3, (
        f"expected all 3 credit proxies, got {summary['symbols']}"
    )
    assert summary["rows"] > 0

    repo = VolIndexRepository(seeded_db_empty_cards.conn, schema="uw_scan")
    for sym in ("HYG", "JNK", "LQD"):
        history = repo.fetch_history(sym, days=30)
        assert history, f"{sym} rows did not land in vol_index_daily after R2 sync"
