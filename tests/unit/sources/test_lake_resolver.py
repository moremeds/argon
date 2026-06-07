"""Resolver picks R2 when fully configured AND fresh, else local."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pydantic import SecretStr
from uw_scan.sources import lake_resolver
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


def _patch_probe(
    monkeypatch: pytest.MonkeyPatch,
    by_kind: dict[str, date | None],
) -> list[tuple[str, str]]:
    """Force _probe_max_trade_date to return per-kind dates without I/O.

    Returns a list that captures each (kind, asset_class) pair the resolver
    probed during the test, so we can assert the probe was hit on the
    expected backends.
    """
    calls: list[tuple[str, str]] = []

    def fake_probe(root: LakeRoot, asset_class: str):
        calls.append((root.kind, asset_class))
        return by_kind.get(root.kind)

    monkeypatch.setattr(lake_resolver, "_probe_max_trade_date", fake_probe)
    return calls


def test_resolve_prefers_local_when_local_strictly_ahead_of_r2(monkeypatch, caplog):
    """Reproduces the 2026-06-06 outage: R2 stuck at 2026-05-21, local fresh.

    Resolver MUST pick local and log WARN — otherwise scanner ingests stale
    R2 silently for days.
    """
    calls = _patch_probe(
        monkeypatch,
        {"s3": date(2026, 5, 21), "local": date(2026, 6, 5)},
    )
    s = _make_settings(with_r2=True)
    with caplog.at_level("WARNING", logger="uw_scan.sources.lake_resolver"):
        root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "local"
    assert root.local_path == Path("/tmp/local-vol")
    # Both backends probed (R2 first, local second — order matters for the
    # caller to read both before deciding).
    assert ("s3", "volatility") in calls
    assert ("local", "volatility") in calls
    # The log must mention the divergence so an oncall reading the worker
    # log sees the smoking gun rather than guessing why R2 was bypassed.
    msg = caplog.text
    assert "local mirror ahead of R2" in msg
    assert "2026-06-05" in msg
    assert "2026-05-21" in msg


def test_resolve_uses_r2_when_r2_is_at_or_ahead_of_local(monkeypatch):
    """Normal case — R2 caught up overnight; resolver MUST return R2."""
    _patch_probe(
        monkeypatch,
        {"s3": date(2026, 6, 5), "local": date(2026, 6, 5)},
    )
    s = _make_settings(with_r2=True)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "s3"


def test_resolve_uses_r2_when_local_is_empty(monkeypatch):
    """No local mirror present (e.g. CI runners) — R2 still wins."""
    _patch_probe(
        monkeypatch,
        {"s3": date(2026, 6, 5), "local": None},
    )
    s = _make_settings(with_r2=True)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "s3"


def test_resolve_uses_local_when_r2_empty_and_local_has_data(monkeypatch, caplog):
    """R2 bucket exists but has no canary parquet (cold bucket). Local has
    data → use local with a WARN."""
    _patch_probe(
        monkeypatch,
        {"s3": None, "local": date(2026, 6, 5)},
    )
    s = _make_settings(with_r2=True)
    with caplog.at_level("WARNING", logger="uw_scan.sources.lake_resolver"):
        root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "local"
    assert "local mirror ahead of R2" in caplog.text


def test_resolve_uses_r2_when_both_backends_empty(monkeypatch):
    """Both probes blind (fresh deploy, cold cache, ToS error, etc.) —
    preserve the pre-2026-06-07 default of returning R2, since the lake-sync
    job will produce the same "0 gaps filled" no-op regardless.
    """
    _patch_probe(monkeypatch, {"s3": None, "local": None})
    s = _make_settings(with_r2=True)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "s3"


def test_resolve_freshness_check_skipped_when_r2_unconfigured(monkeypatch):
    """No R2 settings → return local immediately, never probe.

    Skipping the probe matters: without R2 credentials, the s3-side probe
    would crash, and even the local probe is wasted I/O when there's only
    one backend.
    """
    calls = _patch_probe(monkeypatch, {"local": date(2026, 6, 5)})
    s = _make_settings(with_r2=False)
    root = resolve_lake_root(s, asset_class="volatility")
    assert root.kind == "local"
    assert calls == [], "resolver probed despite R2 being unconfigured"


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
