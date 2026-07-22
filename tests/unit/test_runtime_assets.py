"""Runtime assets must resolve from the installed package, not the repo tree.

Regression guard for the 2026-07-08 Docker cutover: `docs/` is not copied into
the image, so anything read from there at runtime vanished in the container
while every checkout-based test stayed green.
"""

from __future__ import annotations

from uw_scan.cards.canary_calibration import (
    COMPOSITE_VERSION,
    DEFAULT_PATH,
    load_calibration,
)


def test_calibration_default_path_is_inside_the_package() -> None:
    resolved = str(DEFAULT_PATH)
    assert "/docs/" not in resolved, (
        f"calibration still resolves through docs/: {resolved}"
    )
    assert resolved.endswith(
        f"uw_scan/cards/data/canary-calibration-v{COMPOSITE_VERSION}.json"
    ), resolved


def test_calibration_loads_from_package_data() -> None:
    cal = load_calibration()
    assert cal.composite_version == COMPOSITE_VERSION
    assert cal.score_form == "linear"
    assert cal.vix_spike_revert.max_points > 0


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
