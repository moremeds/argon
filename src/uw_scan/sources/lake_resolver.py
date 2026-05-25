"""Resolve a parquet-lake root to either an R2 URI or a local Path.

R2 is the primary source per the 2026-05-25 standing rule (see CLAUDE.md and
docs/research/regime/closure-2026-05-24.md). When all four core R2 settings
(account_id, access_key_id, secret_access_key, bucket) are present the
resolver returns an s3-kind LakeRoot; otherwise it falls back to the local
mirror Path configured per asset_class.

This module is pure config-to-root mapping; the actual I/O lives in lake.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from uw_scan.config import Settings

_ASSET_CLASS_TO_LOCAL_ATTR: dict[str, str] = {
    "volatility": "lake_vol_index_root",
    "equity": "lake_credit_etf_root",
}


@dataclass(frozen=True)
class LakeRoot:
    """Either an S3-on-R2 root or a local-filesystem Path. Discriminate on `kind`.

    `access_key_id` and `secret_access_key` are excluded from repr() so they
    don't leak into log lines, stack traces, or error-tracker payloads when
    the dataclass is printed (e.g. logger.exception with the object as arg).
    """

    kind: Literal["s3", "local"]
    asset_class: str
    # local-only
    local_path: Path | None = None
    # s3-only
    bucket: str | None = None
    key_prefix: str | None = None
    endpoint_override: str | None = None
    access_key_id: str | None = field(default=None, repr=False)
    secret_access_key: str | None = field(default=None, repr=False)

    @classmethod
    def local_for(cls, asset_class: str, path: Path) -> "LakeRoot":
        return cls(kind="local", asset_class=asset_class, local_path=path)


def _r2_fully_configured(s: Settings) -> bool:
    """All four core R2 fields must hold non-empty values.

    Checks `.get_secret_value()` on the SecretStr wrappers explicitly —
    `bool(SecretStr(""))` is True because SecretStr is a non-empty wrapper
    object, so `all((..., r2_access_key_id, r2_secret_access_key, ...))`
    would falsely report 'configured' for empty secrets and engage R2 with
    garbage creds → 403 on every read.
    """
    if not s.r2_account_id or not s.r2_bucket:
        return False
    if s.r2_access_key_id is None or not s.r2_access_key_id.get_secret_value():
        return False
    if s.r2_secret_access_key is None or not s.r2_secret_access_key.get_secret_value():
        return False
    return True


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
    )
