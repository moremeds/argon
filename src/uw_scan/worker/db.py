"""The one way a worker opens a repository for a job (I-54).

Replaces the copies in ``scheduler.py``, ``jobs/pipeline_benchmark.py`` and
``jobs/record_health_snapshot.py``. Each module still binds it as ``_repo``, so
tests that monkeypatch ``<module>._repo`` keep working.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from uw_scan.config import Settings
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
