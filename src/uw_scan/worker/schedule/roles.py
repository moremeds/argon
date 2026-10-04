"""Which process owns a job (I-51). Shared by every job family."""

from __future__ import annotations

from uw_scan.config import Settings


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
