"""Resolve a parquet-lake root to either an R2 URI or a local Path.

R2 is the canonical archive per the 2026-05-25 standing rule (see CLAUDE.md
and docs/research/regime/closure-2026-05-24.md). When all four core R2
settings (account_id, access_key_id, secret_access_key, bucket) are present
the resolver returns an s3-kind LakeRoot; otherwise it falls back to the
local mirror Path configured per asset_class.

**Freshness override** (2026-06-07): R2 is canonical only when it's actually
current. The 2026-06-06 outage exposed a silent stall: an external
producer→R2 push died on 2026-05-21 and argon kept ingesting the stale R2
copy for 16 days even though the local mirror on disk had fresh rows the
whole time. The resolver now probes the canary symbol's `max(trade_date)`
on both backends and falls back to the local mirror when local is strictly
ahead. This is a defensive guard — the right long-term fix is to bring the
producer→R2 push inside argon — but it prevents a silent stale-source
ingest the next time the push falls behind.

This module is config-to-root mapping plus a thin freshness probe; the
actual parquet I/O lives in lake.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from uw_scan.config import Settings

logger = logging.getLogger(__name__)

_ASSET_CLASS_TO_LOCAL_ATTR: dict[str, str] = {
    "volatility": "lake_vol_index_root",
    "equity": "lake_credit_etf_root",
}

# Canary symbol per asset_class — read its `max(trade_date)` to probe lake
# freshness. The symbol MUST be present in every healthy lake (VIX has the
# longest vol-complex history; SPY is the canonical equity ticker). Adding
# a new asset_class requires picking a canary here.
_ASSET_CLASS_CANARY: dict[str, str] = {
    "volatility": "VIX",
    "equity": "SPY",
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
    """Return the lake root for `asset_class`.

    Selection rules, in order:
    1. R2 not configured → local mirror.
    2. R2 configured AND local mirror is strictly ahead of R2 → local mirror,
       with a WARN log. This is the freshness override; covers the case where
       the producer→R2 push has fallen behind but local on disk is still
       being written.
    3. Otherwise → R2 (canonical archive per the 2026-05-25 rule).
    """
    if asset_class not in _ASSET_CLASS_TO_LOCAL_ATTR:
        raise ValueError(
            f"unknown asset_class {asset_class!r}; "
            f"expected one of {sorted(_ASSET_CLASS_TO_LOCAL_ATTR)}"
        )
    local_path: Path = getattr(settings, _ASSET_CLASS_TO_LOCAL_ATTR[asset_class])
    local_root = LakeRoot.local_for(asset_class, local_path)

    if not _r2_fully_configured(settings):
        return local_root

    r2_root = _build_r2_root(settings, asset_class)

    r2_latest = _probe_max_trade_date(r2_root, asset_class)
    local_latest = _probe_max_trade_date(local_root, asset_class)
    if local_latest is not None and (
        r2_latest is None or local_latest > r2_latest
    ):
        logger.warning(
            "lake resolver: local mirror ahead of R2 for asset_class=%s "
            "(local=%s, r2=%s) — using local. Repair producer→R2 push to "
            "restore canonical-archive semantics.",
            asset_class,
            local_latest,
            r2_latest,
        )
        return local_root
    return r2_root


def _build_r2_root(settings: Settings, asset_class: str) -> LakeRoot:
    """Build an s3-kind LakeRoot from R2 settings. Assumes `_r2_fully_configured`."""
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


def _probe_max_trade_date(root: LakeRoot, asset_class: str) -> date | None:
    """Read max(trade_date) from the canary symbol's parquet.

    Returns None if the canary is missing, unreadable, or the asset_class has
    no canary registered. Callers MUST treat None as "no data here" rather
    than an error — the probe is best-effort.

    Cost: one parquet read per call. Acceptable because `resolve_lake_root`
    fires at the start of each lake-sync tick (a few times per day).
    """
    canary = _ASSET_CLASS_CANARY.get(asset_class)
    if canary is None:
        return None
    # Local import to avoid a top-level cycle (lake.py imports LakeRoot from
    # this module). The probe only runs when both backends are reachable.
    from uw_scan.sources.lake import read_vol_index_parquet  # noqa: PLC0415

    try:
        rows = read_vol_index_parquet(root, canary)
    except Exception as exc:
        # repr(exc) (not %r formatting) satisfies the CI Guardrail 2 AST check
        # in scripts/_lint_except.py — same rendered output, lint-visible.
        logger.warning(
            "lake freshness probe failed for %s in %s lake (kind=%s): %s",
            canary,
            asset_class,
            root.kind,
            repr(exc),
        )
        return None
    if not rows:
        return None
    return max(r["trade_date"] for r in rows)
