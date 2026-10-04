"""The one way a worker opens a repository for a job (I-54).

Replaces the copies in ``scheduler.py``, ``jobs/pipeline_benchmark.py`` and
``jobs/record_health_snapshot.py``. Each module still binds it as ``_repo``, so
tests that monkeypatch ``<module>._repo`` keep working.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.uw_budget import limits_from_settings, may_spend, read_snapshot
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository


@contextmanager
def repo_session(settings: Settings) -> Iterator[Repository]:
    """A repository whose writes are still there after the job returns.

    ``with psycopg.connect(...)`` rather than ``connect()`` plus ``close()`` in a
    ``finally``: closing a psycopg connection does not commit, it discards.  That is
    invisible for the many repository methods that call ``self._conn.commit()``
    themselves, and silently fatal for the ones that rely on ``self._conn.transaction()``
    -- because ``transaction()`` only emits ``COMMIT`` when it opened the transaction
    (``psycopg.Transaction._push_savepoint`` sets ``_outer_transaction`` from
    ``transaction_status == IDLE``).  A job that reads before it writes -- every domain
    state job does, it loads observations and its own prior answer first -- leaves the
    connection in a transaction, so the write block degrades to a savepoint and the
    ``close()`` threw the night's work away.  Measured in production before this fix:
    ``macro_domain_states`` at 8 rows inserted, 2 alive, 0 deleted, while the job logged
    ``ok`` every night.

    The block also rolls back on an exception, which the old form did too -- what it adds
    is the commit on the way out.

    """
    with psycopg.connect(settings.db_dsn()) as conn:
        yield Repository(conn, schema=settings.db_schema)


@contextmanager
def external_api_recorder(settings: Settings) -> Iterator[ExternalApiRequestRecorder]:
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    try:
        yield recorder
    finally:
        recorder.close()


def uw_client(
    settings: Settings,
    *,
    telemetry_recorder: ExternalApiRequestRecorder | None = None,
    job_name: str | None = None,
) -> UwClient:
    return UwClient(
        api_key=settings.api_key.get_secret_value(),
        base_url=settings.base_url,
        timeout=settings.request_timeout_seconds,
        telemetry_recorder=telemetry_recorder,
        job_name=job_name,
    )


def research_budget_ok(settings: Settings, repo) -> bool:
    """True if a research-pool job may still spend UW budget this tick.

    Deliberately NOT applied to two classes of research job:
    - ``rescan_tick`` — explicit user-requested rescans keep priority (silently
      no-op'ing a click is bad UX); they're low-volume and self-limit via UW's
      429 past the hard account cap anyway.
    - the post-RTH durable nightly captures (``option_surface_capture``,
      ``greek_exposure_daily_refresh``, discovery) — they run at 18:30-19:00 ET,
      after the live RTH scans are done and near the 20:00 ET budget reset, so
      they don't contend with live; gating them on the shared research ceiling
      would risk starving high-value durable data. Among the recurring *intraday*
      research spenders, only ``regime_gex_scan`` (the dominant one, ~4k
      calls/day) gates here, so RTH research is effectively bounded.
      ``regime_market_tide_scan`` is deliberately NOT gated: at ~78 calls/day
      it's too cheap to be worth freezing the whole Market Tide tab when the
      shared UW key crosses the guard (matches ``regime_top_net_impact_scan``).
    """
    if not settings.uw_budget_governor_enabled:
        return True
    snap = read_snapshot(repo.conn, settings.db_schema)
    return may_spend("research", snap, limits_from_settings(settings))
