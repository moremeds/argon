"""Resolver picks R2 when fully configured, local otherwise."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from uw_scan.sources.lake_resolver import LakeRoot, resolve_lake_root

from uw_scan.config import Settings


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


def test_resolve_local_when_r2_secret_is_empty_string():
    """Empty SecretStr value MUST be treated as 'not configured'.

    Regression for the bug where `bool(SecretStr(""))` is True (the wrapper
    is a non-empty object) so `all((... r2_secret_access_key ...))` would
    incorrectly engage R2 with an empty credential.
    """
    s = _make_settings(with_r2=True, r2_secret_access_key=SecretStr(""))
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "local", "empty SecretStr should fall back, not engage R2"


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
    s = _make_settings(with_r2=True, r2_endpoint_override="https://custom.example.com")
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.endpoint_override == "https://custom.example.com"


def test_resolve_unknown_asset_class_raises():
    s = _make_settings(with_r2=False)
    with pytest.raises(ValueError, match="asset_class"):
        resolve_lake_root(s, asset_class="invalid")


def test_lake_root_repr_does_not_leak_credentials():
    """repr() must not include secret-field VALUES.

    @dataclass default repr lists every field; passing repr=False on the two
    secret fields hides BOTH the field-name token AND the value. Both checks
    are present so a future maintainer who removes repr=False on one field
    sees a failure here, not a quiet credential leak in production logs.
    """
    s = _make_settings(with_r2=True)
    root = resolve_lake_root(s, asset_class="volatility")
    rep = repr(root)
    assert "access_key_id" not in rep, f"access_key_id field leaked into repr: {rep!r}"
    assert "secret_access_key" not in rep, (
        f"secret_access_key field leaked into repr: {rep!r}"
    )
    # Values too (we set them to known sentinels in _make_settings)
    assert "'key'" not in rep, f"access-key value leaked: {rep!r}"
    assert "'sec'" not in rep, f"secret-key value leaked: {rep!r}"

    # Sanity: LakeRoot import retained at module level
    assert LakeRoot is not None
