"""Long-lived WebSocket consumer for api.massive.com.

Runs as a separate ``massive_ws`` worker process (started in ``scripts/dev.sh``).
Holds one WS connection, subscribes to the active watchlist, buffers ticks,
and flushes every ``MASSIVE_WS_FLUSH_INTERVAL_SECONDS`` to Postgres as a
single atomic batch.

Lifecycle (per session, inside ``asyncio.TaskGroup``):
1. ``_ws_reader``       — drain frames, populate ``TickBuffer``, increment A12
                          raw counter via ``writer.note_received``
2. ``_flush_loop``      — every N seconds, ``writer.flush_once()``
3. ``_subscription_loop`` — every M seconds, diff against the watchlist and
                          (un)subscribe via the active client

On task crash the TaskGroup cancels the session, propagates up to
``run_consumer_forever`` which classifies the error (A8) and reconnects with
exponential backoff.

Two Repository instances per session (A1 — psycopg3 conns are NOT thread-safe
across ``asyncio.to_thread`` call sites):
- writer-repo owned by the flush_loop's to_thread worker
- reader-repo owned by the subscription_loop's to_thread worker

Both connections must be opened with ``autocommit=True`` (A7) so that
``with self._repo._conn.transaction()`` in ``WsDbWriter`` issues explicit
BEGIN/COMMIT and we never leave a hanging implicit txn.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

import psycopg

from uw_scan.config import Settings
from uw_scan.sources.massive_ws import MassiveWsClient
from uw_scan.storage.repository import Repository
from uw_scan.worker.ws_db_writer import WsDbWriter
from uw_scan.worker.ws_tick_buffer import TickBuffer

logger = logging.getLogger(__name__)


def compute_subscription_diff(
    *,
    current: set[str],
    desired: set[str],
    channel: str,
) -> tuple[set[str], set[str]]:
    """Return ``(channels_to_add, channels_to_drop)``.

    ``current`` is the set of fully-qualified channels already subscribed
    (e.g. ``{"A.AAPL"}``). ``desired`` is the set of *tickers* the consumer
    should be tracking. ``channel`` is the prefix (``"A"`` / ``"AM"`` / ``"T"``).
    """
    desired_channels = {f"{channel}.{t}" for t in desired}
    return (desired_channels - current, current - desired_channels)


class _ReaderDone(Exception):
    """Sentinel: the WS reader's ``async for`` exited cleanly (server closed
    the connection). The reader is the "session driver" — when it ends, the
    flush + subscription loops have nothing left to do, so the TaskGroup
    should unwind. Raising forces TaskGroup cancellation; ``run_consumer_once``
    catches this case in its ``except*`` clause and returns normally.
    """


async def _ws_reader(
    client: MassiveWsClient, buffer: TickBuffer, writer: WsDbWriter
) -> None:
    async for tick in client.ticks():
        writer.note_received(1)  # A12: raw feed pressure
        buffer.add(tick)
    # Connection closed by the server (or remote end). Signal siblings to stop.
    raise _ReaderDone("ws connection closed cleanly")


async def _flush_loop(writer: WsDbWriter, interval_seconds: float) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            # R1: offload sync psycopg I/O so the WS reader keeps draining frames.
            await asyncio.to_thread(writer.flush_once)
        except Exception:
            logger.exception("flush_loop: writer.flush_once failed; continuing")


async def _subscription_loop(
    *,
    client: MassiveWsClient,
    repo: Repository,
    channel: str,
    current_subs: set[str],
    poll_interval_seconds: float,
) -> None:
    while True:
        try:
            desired = await asyncio.to_thread(
                lambda: {w.ticker for w in repo.list_active_watchlist()}
            )
            to_add, to_drop = compute_subscription_diff(
                current=current_subs, desired=desired, channel=channel
            )
            if to_add:
                await client.subscribe(to_add)
                current_subs.update(to_add)
                logger.info("ws subscribed: %s", sorted(to_add))
            if to_drop:
                await client.unsubscribe(to_drop)
                current_subs.difference_update(to_drop)
                logger.info("ws unsubscribed: %s", sorted(to_drop))
        except Exception:
            logger.exception("subscription_loop: refresh failed; continuing")
        await asyncio.sleep(poll_interval_seconds)


@contextlib.asynccontextmanager
async def _null_ctx():
    yield


async def run_consumer_once(
    *,
    ws_url: str,
    api_key: str,
    channel: str,
    tickers: set[str],
    writer_repo: Repository,
    reader_repo: Repository,
    flush_interval_seconds: float = 1.0,
    subscription_poll_interval_seconds: float = 30.0,
    run_for_seconds: float | None = None,
    buffer: TickBuffer | None = None,
    final_flush_timeout_seconds: float = 5.0,
) -> bool:
    """One full WS session: connect → subscribe → reader/flusher/subscriber
    → final flush on exit.

    Two Repository args because psycopg3 connections aren't safe to share
    across ``asyncio.to_thread`` call sites (A1). The writer owns the
    canonical flush path; the reader owns the watchlist-diff path.

    ``buffer`` is owned by the caller so ticks merged back into it by a
    failed final flush survive into the next session (tribunal ISSUE-1:
    when allocated locally, the final-flush failure path silently
    discards the merge-back). When ``None``, a fresh buffer is allocated
    — this preserves the pre-tribunal call sites (tests + manual one-off
    invocations) at the cost of no cross-session recovery.

    ``run_for_seconds`` bounds the session for tests. In production the
    consumer runs until the WS closes (``async for`` in ``client.ticks()``
    exits cleanly on ``ConnectionClosed``).

    Returns ``True`` iff the final flush succeeded — ``run_consumer_forever``
    uses this to gate the reconnect backoff reset (tribunal adversarial-4).
    A clean WS close with a failed DB write must NOT reset backoff or the
    consumer will spam-reconnect under persistent DB write failures.

    ``final_flush_timeout_seconds`` bounds the finally-clause flush
    (tribunal adversarial-3). A periodic flush stuck inside Postgres
    while holding ``writer._flush_lock`` would otherwise hang shutdown
    indefinitely; the timeout lets the process exit even if DB I/O is
    wedged.
    """
    if buffer is None:
        buffer = TickBuffer()
    writer = WsDbWriter(repo=writer_repo, buffer=buffer)
    current_subs: set[str] = set()
    final_flush_ok = False

    async with MassiveWsClient(ws_url, api_key) as client:
        await asyncio.to_thread(
            writer_repo.record_ws_connection_started, datetime.now(timezone.utc)
        )
        initial = {f"{channel}.{t}" for t in tickers}
        if initial:
            await client.subscribe(initial)
            current_subs.update(initial)

        timeout_ctx = (
            asyncio.timeout(run_for_seconds)
            if run_for_seconds is not None
            else _null_ctx()
        )
        try:
            async with timeout_ctx:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(_ws_reader(client, buffer, writer), name="ws_reader")
                    tg.create_task(
                        _flush_loop(writer, flush_interval_seconds),
                        name="ws_flusher",
                    )
                    tg.create_task(
                        _subscription_loop(
                            client=client,
                            repo=reader_repo,
                            channel=channel,
                            current_subs=current_subs,
                            poll_interval_seconds=subscription_poll_interval_seconds,
                        ),
                        name="ws_subscriber",
                    )
        except* asyncio.TimeoutError:
            pass  # bounded-session shutdown (tests use run_for_seconds)
        except* _ReaderDone:
            pass  # WS closed normally — sibling tasks were cancelled by TaskGroup
        # CancelledError is intentionally NOT caught: swallowing it inside an
        # `except*` clause de-arms the outer task cancellation (Python 3.11
        # PEP 654 semantics), which would make ``consumer_task.cancel()`` in
        # tests + production silently fail to stop the loop.
        finally:
            # Final-flush limitations (adversarial-1 / adversarial-3):
            # - On SIGTERM the outer task is cancelled mid-await. The await
            #   below would itself re-raise CancelledError immediately so
            #   ticks accumulated since the last periodic flush MAY be lost.
            #   ``Task.uncancel()`` worked around this but interfered with
            #   normal ``TaskGroup`` cleanup — sibling cancellations bump
            #   the parent's ``cancelling()`` count even on clean shutdown,
            #   so an unconditional uncancel/recancel dance would leave
            #   ``MassiveWsClient.__aexit__`` running in a cancelled state.
            # - The shared ``TickBuffer`` lifted into ``run_consumer_forever``
            #   means ticks survive across reconnects on transient DB write
            #   failures (the primary ISSUE-1 win), so the SIGTERM gap is
            #   bounded to ~``flush_interval_seconds`` of ticks.
            # - ``wait_for`` bounds the flush so a wedged periodic flush
            #   thread holding the writer lock can't block exit
            #   indefinitely (adversarial-3).
            try:
                await asyncio.wait_for(
                    asyncio.to_thread(writer.flush_once),
                    timeout=final_flush_timeout_seconds,
                )
                final_flush_ok = True
            except asyncio.TimeoutError:
                logger.warning(
                    "run_consumer_once: final flush exceeded %.1fs",
                    final_flush_timeout_seconds,
                )
            except Exception:
                logger.exception("run_consumer_once: final flush failed")
    return final_flush_ok


async def run_consumer_forever(settings: Settings, repo_factory) -> None:
    """Reconnect with exponential backoff.

    ``repo_factory(role)`` is a sync context manager yielding a Repository
    on a fresh autocommit connection. We open two per session — ``"writer"``
    and ``"reader"`` (A1).

    A8 classification: if the failure is ``psycopg.OperationalError`` the
    DB is the failure mode itself; skip the secondary record-error attempt
    to avoid amplifying a DB outage with extra failed connections.

    The ``TickBuffer`` is allocated ONCE and shared across all sessions
    (tribunal ISSUE-1). If a session's final flush fails (DB hiccup at
    shutdown / reconnect), ``WsDbWriter.flush_once`` merges the pending
    ticks back into this shared buffer; the next session's writer drains
    them on its first flush. Without this, ticks held by ``_pending`` at
    a failed final flush would be lost when ``run_consumer_once``'s local
    buffer/writer went out of scope.
    """
    buffer = TickBuffer()
    backoff = settings.massive_ws_reconnect_backoff_initial_seconds
    while True:
        try:
            with (
                repo_factory("writer") as writer_repo,
                repo_factory("reader") as reader_repo,
            ):
                desired = await asyncio.to_thread(
                    lambda: {w.ticker for w in reader_repo.list_active_watchlist()}
                )
                final_ok = await run_consumer_once(
                    ws_url=settings.massive_ws_url,
                    api_key=settings.massive_api_key.get_secret_value(),
                    channel=settings.massive_ws_channel,
                    tickers=desired,
                    writer_repo=writer_repo,
                    reader_repo=reader_repo,
                    flush_interval_seconds=settings.massive_ws_flush_interval_seconds,
                    subscription_poll_interval_seconds=settings.massive_ws_watchlist_poll_interval_seconds,
                    buffer=buffer,
                )
            # Only reset backoff when the final flush actually committed
            # (tribunal adversarial-4). A clean WS close with a failed DB
            # write must keep backing off — otherwise persistent DB write
            # failures spam-reconnect.
            if final_ok:
                backoff = settings.massive_ws_reconnect_backoff_initial_seconds
            await asyncio.sleep(backoff)  # smooth between reconnects
            if not final_ok:
                # Persistent-failure path: grow backoff before retrying.
                backoff = min(
                    backoff * 2.0,
                    settings.massive_ws_reconnect_backoff_max_seconds,
                )
            continue
        except psycopg.OperationalError:
            # A8: DB unreachable when opening conns (before TaskGroup).
            # Skip the secondary record-error attempt — it would just fail.
            logger.exception("ws consumer: DB unreachable; backoff=%.1fs", backoff)
        except BaseExceptionGroup as eg:
            # TaskGroup wraps task crashes in BaseExceptionGroup. Pull out
            # OperationalErrors (A8) so a DB outage mid-session doesn't trigger
            # the secondary error-record path.
            op_errs, _rest = eg.split(psycopg.OperationalError)
            if op_errs is not None:
                logger.exception(
                    "ws consumer: DB error mid-session; backoff=%.1fs", backoff
                )
            else:
                logger.exception(
                    "ws consumer crashed: %s; backoff=%.1fs", repr(eg), backoff
                )
                try:
                    with repo_factory("writer") as err_repo:
                        err_repo.record_ws_error(repr(eg), datetime.now(timezone.utc))
                except Exception:
                    logger.exception(
                        "ws consumer: failed to record error to DB (ignored)"
                    )
        except Exception as exc:
            logger.exception(
                "ws consumer crashed: %s; backoff=%.1fs", repr(exc), backoff
            )
            try:
                with repo_factory("writer") as err_repo:
                    err_repo.record_ws_error(repr(exc), datetime.now(timezone.utc))
            except Exception:
                logger.exception("ws consumer: failed to record error to DB (ignored)")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, settings.massive_ws_reconnect_backoff_max_seconds)


def main() -> int:
    import signal
    from contextlib import contextmanager

    settings = Settings.from_env()
    if not settings.massive_ws_enabled:
        logger.warning("MASSIVE_WS_ENABLED is false; exiting")
        return 0
    if settings.massive_api_key is None:
        logger.error("MASSIVE_API_KEY is not set; cannot start WS consumer")
        return 1

    @contextmanager
    def _repo_factory(role: str):
        # A7: autocommit set at connect time so no implicit txn is opened
        # before the WS writer's ``with conn.transaction()`` block.
        conn = psycopg.connect(
            settings.db_dsn(),
            autocommit=True,
            application_name=f"massive_ws_consumer:{role}",
        )
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    async def _run() -> None:
        """Wrap run_consumer_forever in a cancellable task so SIGTERM /
        SIGINT triggers graceful shutdown (tribunal adversarial-1).

        Bare ``asyncio.run(run_consumer_forever(...))`` would terminate
        on SIGTERM without ever reaching ``run_consumer_once``'s finally
        clause — every tick in the buffer or in ``_pending`` would be
        lost. Cancelling the task instead unwinds the TaskGroup and
        fires the bounded final flush.
        """
        consumer_task = asyncio.create_task(
            run_consumer_forever(settings, _repo_factory)
        )
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, consumer_task.cancel)
        try:
            await consumer_task
        except asyncio.CancelledError:
            logger.info("ws consumer cancelled by signal — graceful shutdown")

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
