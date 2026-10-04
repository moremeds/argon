"""Which process owns a job (I-51). Shared by every job family."""

from __future__ import annotations

import zlib
from collections.abc import Callable
from typing import Literal

from uw_scan.config import Settings
from uw_scan.sources.lake_resolver import _r2_fully_configured

WorkerGroup = Literal["uw", "massive", "ai", "ai-deepseek"]


def _pinned(settings: Settings, role: str) -> bool:
    """True on exactly one process: the single-scheduler ``all`` shape, or index 0
    of ``role``. The predicate every single-owner job uses (I-51)."""
    current = settings.worker_role.lower()
    return current == "all" or (current == role and settings.worker_index == 0)


def _owns_global_daily_jobs(settings: Settings) -> bool:
    """Exactly one process owns the role-agnostic daily jobs (gold, regime
    EOD scans, vol/credit lake syncs, macro).

    These used to sit under `_is_primary_worker`, which is true for index-0 of
    EVERY role, so the prod stack (uw-0, massive-0, ai-deepseek-0) ran each of
    them three times: tripled UW spend for the gold options ingest and three
    gold_posture rows per night. Pin to massive-0, the macro-evidence owner.
    """
    return _pinned(settings, "massive")


def _worker_groups(settings: Settings) -> set[WorkerGroup]:
    role = settings.worker_role.lower()
    if role == "all":
        return {"uw", "massive", "ai"}
    if role == "uw":
        return {"uw"}
    if role == "massive":
        return {"massive"}
    if role == "ai":
        return {"ai"}
    if role == "ai-deepseek":
        return {"ai-deepseek"}
    raise RuntimeError(
        "UW_SCAN_WORKER_ROLE must be one of: all, uw, massive, ai, "
        "ai-deepseek "
        f"(got {settings.worker_role!r})"
    )


def _is_primary_worker(settings: Settings) -> bool:
    return settings.worker_role.lower() == "all" or settings.worker_index == 0


WORKER_ROLES: set[str] = {
    "all",
    "uw",
    "massive",
    "ai",
    "ai-deepseek",
}


def _validate_worker_settings(settings: Settings) -> None:
    role = settings.worker_role.lower()
    if role not in WORKER_ROLES:
        raise RuntimeError(
            "UW_SCAN_WORKER_ROLE must be one of: all, uw, massive, ai, "
            "ai-deepseek "
            f"(got {settings.worker_role!r})"
        )
    if settings.worker_count < 1:
        raise RuntimeError("UW_SCAN_WORKER_COUNT must be >= 1")
    if settings.worker_index < 0 or settings.worker_index >= settings.worker_count:
        raise RuntimeError(
            "UW_SCAN_WORKER_INDEX must be between 0 and "
            f"{settings.worker_count - 1} (got {settings.worker_index})"
        )
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


def _worker_owns_ticker(ticker: str, *, index: int, count: int) -> bool:
    if count <= 1:
        return True
    normalized = ticker.strip().upper().encode("utf-8")
    return zlib.crc32(normalized) % count == index


def _ticker_shard_filter(settings: Settings) -> Callable[[str], bool]:
    _validate_worker_settings(settings)
    return lambda ticker: _worker_owns_ticker(
        ticker, index=settings.worker_index, count=settings.worker_count
    )
