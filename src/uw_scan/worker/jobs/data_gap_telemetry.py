"""Durable progress heartbeats for the nightly data gap healer.

WHY THIS IS A SEPARATE MODULE
-----------------------------
``data_gap_adapters.py`` is already 1,042 lines against this repo's 500-line
target and its "at 1000+ lines stop adding methods and propose a split first"
rule. New behaviour goes here instead of growing it. The full split proposed for
that file -- ``RequestBudget`` plus the budget governor into one module,
``HealContext`` plus provider construction into another, the ``_dispatch_*``
executors into a third -- is a mechanical move that would bury this behaviour
change inside a rename diff, so it is deliberately deferred. This module is its
first seam.

WHY THE HEARTBEAT LIVES IN POSTGRES, NOT ONLY THE LOG
-----------------------------------------------------
Four nightly runs in 2026-08 (103-106) stopped 50-88 minutes in having touched
1-2 of 23 datasets, with zero failures and their UW cap barely used. By the time
anyone looked, the worker container had been recreated and its logs were gone --
so "where did it stop" had no answer anywhere. A heartbeat that lives only in
stdout says nothing about a run whose container no longer exists, which is
precisely the run you need it for.

The heartbeat shares the healer's own connection rather than opening a second
one: ``DataGapHealerRepository._set_item_status`` already commits per item, so
each beat is durable at the same points the run's own progress is.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime

logger = logging.getLogger(__name__)

# The stages a single item passes through. Named rather than free-form so a
# stalled run's last beat is comparable across datasets and dispatchers: the
# whole diagnostic value is in knowing WHICH of these the run never left.
STAGE_CLAIMED = "claimed"
STAGE_ADAPTER = "adapter_entered"
STAGE_PROVIDER_RETURNED = "provider_returned"
STAGE_MARKED = "marked"


class HealHeartbeat:
    """Last-known progress of a heal run, in the log and in Postgres."""

    def __init__(
        self,
        gap: object,
        run_id: int,
        *,
        recorder: object | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._gap = gap
        self._run_id = run_id
        self._recorder = recorder
        self._now = now or (lambda: datetime.now(UTC))
        self._started = self._now()
        self._last = self._started
        self.items_done = 0
        self.write_failures = 0

    def stage(
        self,
        stage: str,
        *,
        dataset: str,
        item_id: int | None = None,
        ticker: str | None = None,
        data_date: date | None = None,
        **extra: object,
    ) -> None:
        if stage == STAGE_MARKED:
            self.items_done += 1
        now = self._now()
        beat = {
            "at": now.isoformat(),
            # In the payload as well as the row key: the row gives you the last
            # beat, the log gives you the sequence, and only the log is greppable.
            "run_id": self._run_id,
            "stage": stage,
            "dataset": dataset,
            "item_id": item_id,
            "ticker": ticker,
            "data_date": data_date.isoformat() if data_date else None,
            "items_done": self.items_done,
            "elapsed_s": round((now - self._started).total_seconds(), 1),
            # Time spent in the PREVIOUS stage. This is the field that names the
            # hang: a run frozen for an hour leaves its last beat's successor
            # missing, and the beat after a recovery carries the gap as a number
            # instead of a timestamp subtraction someone has to do by hand.
            "since_last_s": round((now - self._last).total_seconds(), 1),
            "telemetry_failures": getattr(self._recorder, "failures", None),
            **extra,
        }
        self._last = now
        # INFO, not DEBUG: the worker configures basicConfig(level=INFO), so a
        # DEBUG trace here would produce nothing at all in production.
        logger.info("gap_heal_progress %s", json.dumps(beat, default=str))
        self._persist(beat)

    def counters(self) -> dict[str, int]:
        """Run-level counters for ``data_gap_runs.summary_jsonb``."""
        return {
            "items_beaten": self.items_done,
            "heartbeat_write_failures": self.write_failures,
            "telemetry_write_failures": int(getattr(self._recorder, "failures", 0) or 0),
        }

    def _persist(self, beat: dict) -> None:
        try:
            with self._gap._conn.cursor() as cur:  # noqa: SLF001
                cur.execute(
                    "UPDATE data_gap_runs "
                    "SET summary_jsonb = summary_jsonb || %s::jsonb WHERE id = %s",
                    (json.dumps({"heartbeat": beat}, default=str), self._run_id),
                )
            self._gap._conn.commit()  # noqa: SLF001
        except Exception as exc:
            # A heartbeat that cannot be written must never abort the heal it is
            # only observing; count it so the run reports its own blind spot.
            self.write_failures += 1
            logger.warning("gap_heal heartbeat persist failed: %s", repr(exc))
