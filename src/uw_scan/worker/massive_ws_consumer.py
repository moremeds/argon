"""Long-lived spot WebSocket consumer — xenon primary, massive fallback.

Runs as a separate ``massive_ws`` worker process (started in ``scripts/dev.sh``;
module name retained for dev.sh/launchd compat). Holds one WS connection —
to xenon's IB realtime server when ``XENON_WS_ENABLED`` (primary), else to
api.massive.com — subscribes to the active watchlist, buffers ticks, and
flushes every ``MASSIVE_WS_FLUSH_INTERVAL_SECONDS`` to Postgres as a single
atomic batch.

Failover: a xenon connect failure / connect-time IB outage / in-session
quiet period blocks xenon for ``XENON_WS_RETRY_PRIMARY_SECONDS`` and runs
massive sessions instead; each massive fallback session races a xenon probe
and unwinds (shared TickBuffer carries pending ticks) when xenon recovers.
Xenon streams 24h whenever IB Gateway is up; massive only delivers frames
Mon-Fri 04:00-20:00 ET, so the quiet watchdog is armed only inside that
window — failing over outside it buys nothing.

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
import time
from collections.abc import Iterable
from datetime import datetime, timezone

import psycopg
from websockets.exceptions import WebSocketException

from uw_scan.config import Settings
from uw_scan.sources.massive_ws import MassiveWsClient
from uw_scan.sources.xenon_ws import (
    XenonFeedUnavailable,
    XenonWsClient,
    discover_xenon_ws_url,
)
from uw_scan.storage.repository import Repository
from uw_scan.worker.market_session import current_market_date
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


def desired_subscription_tickers(watchlist: set[str], extra: Iterable[str]) -> set[str]:
    """Watchlist tickers ∪ the always-on regime set, upper-cased.

    The regime symbols (VIX/VVIX/VIX3M/COR1M/SPX/HYG by default) feed the
    live CRI/VCG compute and are subscribed regardless of watchlist state.
    intraday_quote accepts them since migration 052 dropped the watchlist
    FK; watchlist_card writes are UPDATE-only and skip them silently.
    """
    return {t.upper() for t in watchlist} | {t.upper() for t in extra}


class _ReaderDone(Exception):
    """Sentinel: the WS reader's ``async for`` exited cleanly (server closed
    the connection). The reader is the "session driver" — when it ends, the
    flush + subscription loops have nothing left to do, so the TaskGroup
    should unwind. Raising forces TaskGroup cancellation; ``run_consumer_once``
    catches this case in its ``except*`` clause and returns normally.
    """


class _FeedQuiet(Exception):
    """Sentinel: the active feed delivered no ticks for quiet_failover_seconds
    during a market session while subscriptions exist. Deliberately NOT caught
    by run_consumer_once's ``except*`` clauses — it propagates (after the
    final flush) so run_consumer_forever can classify it as a primary-feed
    failure and fall back to massive.
    """


async def _ws_reader(
    client: MassiveWsClient | XenonWsClient,
    buffer: TickBuffer,
    writer: WsDbWriter,
    last_rx_monotonic: list[float],
    tick_received: asyncio.Event,
) -> None:
    async for tick in client.ticks():
        last_rx_monotonic[0] = time.monotonic()
        writer.note_received(1)  # A12: raw feed pressure
        buffer.add(tick)
        if not tick_received.is_set():
            tick_received.set()  # Codex P1: track first-tick-of-session.
    # Connection closed by the server (or remote end). Signal siblings to stop.
    raise _ReaderDone("ws connection closed cleanly")


async def _quiet_watchdog(
    *,
    last_rx_monotonic: list[float],
    current_subs: set[str],
    quiet_seconds: float,
    rth_tz: str,
) -> None:
    """Raise _FeedQuiet on sustained in-session tick silence.

    Outside the feed-active window (mon-fri 04:00-20:00 ET) or with nothing
    subscribed, the timer is re-armed rather than evaluated — a session
    opening at 03:00 ET must not insta-trip at 09:30, and an empty watchlist
    is not a feed failure. Ticks are the signal (not raw frames): a feed
    sending only heartbeats is still not delivering prices.
    """
    while True:
        await asyncio.sleep(max(min(quiet_seconds / 4.0, 15.0), 0.05))
        if (
            current_market_date(datetime.now(timezone.utc), rth_tz) is None
            or not current_subs
        ):
            last_rx_monotonic[0] = time.monotonic()
            continue
        if time.monotonic() - last_rx_monotonic[0] >= quiet_seconds:
            raise _FeedQuiet(
                f"no WS ticks for {quiet_seconds:.0f}s during market session"
            )


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
    client: MassiveWsClient | XenonWsClient,
    repo: Repository,
    channel: str,
    current_subs: set[str],
    poll_interval_seconds: float,
    extra_tickers: frozenset[str] = frozenset(),
) -> None:
    while True:
        try:
            desired = await asyncio.to_thread(
                lambda: desired_subscription_tickers(
                    {w.ticker for w in repo.list_active_watchlist()}, extra_tickers
                )
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
    client: MassiveWsClient | XenonWsClient | None = None,
    source_tag: str = "massive.com_ws",
    quiet_failover_seconds: float = 0.0,
    rth_tz: str = "America/New_York",
    extra_tickers: frozenset[str] = frozenset(),
) -> bool:
    """One full WS session: connect → subscribe → reader/flusher/subscriber
    → final flush on exit.

    ``client`` injects a not-yet-entered WS client (XenonWsClient for the
    primary feed); ``None`` builds the historical MassiveWsClient from
    ``ws_url``/``api_key``. ``source_tag`` flows to ``WsDbWriter`` (so
    ``spot_source``/``intraday_quote.source`` identify the feed) and to
    ``record_ws_connection_started`` (``ws_consumer_state.active_source``).
    ``quiet_failover_seconds > 0`` arms a watchdog that raises ``_FeedQuiet``
    (propagated AFTER the final flush — no tick loss) on sustained in-session
    silence; ``rth_tz`` scopes its market-session gate.

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
    writer = WsDbWriter(repo=writer_repo, buffer=buffer, source_tag=source_tag)
    current_subs: set[str] = set()
    last_rx_monotonic = [time.monotonic()]
    # Codex P1: a xenon session that connects, completes handshake, then
    # closes without delivering any ticks must be treated as a feed failure
    # (otherwise the loop retries xenon immediately and a flapping server
    # freezes spots indefinitely). Tracked here, evaluated post-session.
    tick_received = asyncio.Event()
    final_flush_ok = False
    if client is None:
        client = MassiveWsClient(ws_url, api_key)

    async with client:
        await asyncio.to_thread(
            writer_repo.record_ws_connection_started,
            datetime.now(timezone.utc),
            source_tag,
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
                    tg.create_task(
                        _ws_reader(
                            client,
                            buffer,
                            writer,
                            last_rx_monotonic,
                            tick_received,
                        ),
                        name="ws_reader",
                    )
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
                            extra_tickers=extra_tickers,
                        ),
                        name="ws_subscriber",
                    )
                    if quiet_failover_seconds > 0:
                        tg.create_task(
                            _quiet_watchdog(
                                last_rx_monotonic=last_rx_monotonic,
                                current_subs=current_subs,
                                quiet_seconds=quiet_failover_seconds,
                                rth_tz=rth_tz,
                            ),
                            name="ws_quiet_watchdog",
                        )
        except* asyncio.TimeoutError as eg:
            # Bounded-session shutdown (tests use run_for_seconds). Logged at
            # debug because the sentinel is expected; ``repr(eg)`` satisfies
            # CI Guardrail 2 without escalating to logger.exception (which
            # would emit a full traceback at ERROR level for an expected
            # control-flow signal).
            logger.debug("ws session timed out (bounded): %s", repr(eg))
        except* _ReaderDone as eg:
            # WS closed normally — sibling tasks were cancelled by TaskGroup.
            # Same debug-level rationale as the TimeoutError branch.
            logger.debug("ws session ended via reader-done: %s", repr(eg))
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
            except asyncio.TimeoutError as exc:
                logger.warning(
                    "run_consumer_once: final flush exceeded %.1fs (%s)",
                    final_flush_timeout_seconds,
                    repr(exc),
                )
            except Exception:
                logger.exception("run_consumer_once: final flush failed")
        # Codex P1 (post-session evaluation): if the session ran to a clean
        # close but never delivered a tick during a market session, raise
        # XenonFeedUnavailable so run_consumer_forever blocks xenon for the
        # retry window instead of immediately re-trying it. Gated by
        # quiet_failover_seconds > 0 (the same flag that means "failover
        # semantics apply to this session" — today only the xenon path
        # sets it).
        if (
            quiet_failover_seconds > 0
            and not tick_received.is_set()
            and current_market_date(datetime.now(timezone.utc), rth_tz) is not None
        ):
            raise XenonFeedUnavailable(
                "session ended without delivering ticks during market session"
            )
    return final_flush_ok


async def _xenon_probe_loop(settings: Settings) -> None:
    """Block until xenon accepts a connection AND reports ib_connected.

    Runs inside a massive fallback session (raced via ``asyncio.wait``).
    The first probe waits a full retry interval — we just failed xenon,
    don't hammer it. Completes only on success; probe errors loop forever.
    """
    while True:
        await asyncio.sleep(settings.xenon_ws_retry_primary_seconds)
        url = discover_xenon_ws_url(settings.xenon_ws_url, settings.xenon_ws_port_file)
        try:
            async with XenonWsClient(url, open_timeout=5.0):
                pass  # handshake (status with ib_connected) IS the success test
            logger.info("xenon ws probe succeeded at %s", url)
            return
        except (
            XenonFeedUnavailable,
            OSError,
            asyncio.TimeoutError,
            WebSocketException,
        ) as exc:
            logger.debug("xenon ws probe failed: %s", repr(exc))


def _record_ws_error_best_effort(repo_factory, message: str) -> None:
    try:
        with repo_factory("writer") as err_repo:
            err_repo.record_ws_error(message, datetime.now(timezone.utc))
    except Exception:
        logger.exception("ws consumer: failed to record error to DB (ignored)")


async def run_consumer_forever(settings: Settings, repo_factory) -> None:
    """Reconnect with exponential backoff; xenon primary, massive fallback.

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

    Provider selection: when ``xenon_ws_enabled``, each session attempts
    xenon first unless a recent xenon failure (connect error, connect-time
    IB outage, in-session quiet) blocked it for
    ``xenon_ws_retry_primary_seconds``. Massive fallback sessions race
    ``_xenon_probe_loop``; on xenon recovery the massive session is
    cancelled — the shared TickBuffer carries merged-back pending ticks
    across the switch, so loss is bounded to the same ~flush-interval
    window as the documented SIGTERM path — and the next session is xenon.
    """
    buffer = TickBuffer()
    backoff = settings.massive_ws_reconnect_backoff_initial_seconds
    massive_available = (
        settings.massive_ws_enabled and settings.massive_api_key is not None
    )
    xenon_blocked_until = 0.0  # time.monotonic() deadline; 0 = try now
    extra_tickers = frozenset(t.upper() for t in settings.regime_ws_symbols)
    while True:
        use_xenon = settings.xenon_ws_enabled and (
            time.monotonic() >= xenon_blocked_until
        )
        if not use_xenon and not massive_available:
            # Xenon-only deployment inside its retry-block window: nothing
            # else to run, so wait out the window instead of dead-exiting.
            wait = max(xenon_blocked_until - time.monotonic(), backoff)
            logger.warning(
                "no WS feed available (xenon blocked, massive disabled); "
                "retrying xenon in %.0fs",
                wait,
            )
            await asyncio.sleep(wait)
            xenon_blocked_until = 0.0
            continue
        try:
            with (
                repo_factory("writer") as writer_repo,
                repo_factory("reader") as reader_repo,
            ):
                desired = await asyncio.to_thread(
                    lambda: desired_subscription_tickers(
                        {w.ticker for w in reader_repo.list_active_watchlist()},
                        extra_tickers,
                    )
                )
                if use_xenon:
                    url = discover_xenon_ws_url(
                        settings.xenon_ws_url, settings.xenon_ws_port_file
                    )
                    final_ok = await run_consumer_once(
                        ws_url=url,
                        api_key="",
                        channel=settings.massive_ws_channel,
                        tickers=desired,
                        writer_repo=writer_repo,
                        reader_repo=reader_repo,
                        flush_interval_seconds=settings.massive_ws_flush_interval_seconds,
                        subscription_poll_interval_seconds=settings.massive_ws_watchlist_poll_interval_seconds,
                        buffer=buffer,
                        client=XenonWsClient(url),
                        source_tag="xenon_ws",
                        quiet_failover_seconds=settings.xenon_ws_quiet_failover_seconds,
                        rth_tz=settings.rth_tz,
                        extra_tickers=extra_tickers,
                    )
                else:
                    session = asyncio.create_task(
                        run_consumer_once(
                            ws_url=settings.massive_ws_url,
                            api_key=settings.massive_api_key.get_secret_value(),
                            channel=settings.massive_ws_channel,
                            tickers=desired,
                            writer_repo=writer_repo,
                            reader_repo=reader_repo,
                            flush_interval_seconds=settings.massive_ws_flush_interval_seconds,
                            subscription_poll_interval_seconds=settings.massive_ws_watchlist_poll_interval_seconds,
                            buffer=buffer,
                            extra_tickers=extra_tickers,
                        ),
                        name="massive_fallback_session",
                    )
                    if settings.xenon_ws_enabled:
                        probe = asyncio.create_task(
                            _xenon_probe_loop(settings), name="xenon_probe"
                        )
                        try:
                            done, _pending = await asyncio.wait(
                                {session, probe},
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                        except asyncio.CancelledError:
                            # Outer cancellation (SIGTERM): unwind both so the
                            # session's bounded final flush still fires.
                            session.cancel()
                            probe.cancel()
                            with contextlib.suppress(BaseException):
                                await session
                            with contextlib.suppress(BaseException):
                                await probe
                            raise
                        if session in done:
                            probe.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await probe
                            final_ok = session.result()  # re-raises session errors
                        else:
                            # Xenon recovered: unwind the massive session.
                            # Cancellation here is the documented SIGTERM-shaped
                            # path — pending ticks merge back into the shared
                            # buffer; loss bounded to ~1 flush interval.
                            session.cancel()
                            with contextlib.suppress(asyncio.CancelledError, Exception):
                                await session
                            xenon_blocked_until = 0.0
                            logger.info(
                                "xenon primary recovered; leaving massive fallback"
                            )
                            continue
                    else:
                        final_ok = await session
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
        except (
            XenonFeedUnavailable,
            OSError,
            asyncio.TimeoutError,
            WebSocketException,
        ) as exc:
            if use_xenon:
                # Primary-feed failure: block xenon for the retry window and
                # go straight to massive — no backoff growth, the fallback
                # deserves an immediate clean attempt.
                xenon_blocked_until = (
                    time.monotonic() + settings.xenon_ws_retry_primary_seconds
                )
                logger.warning(
                    "xenon ws unavailable (%s); falling back to massive for %.0fs",
                    repr(exc),
                    settings.xenon_ws_retry_primary_seconds,
                )
                continue
            logger.exception(
                "ws consumer crashed: %s; backoff=%.1fs", repr(exc), backoff
            )
            _record_ws_error_best_effort(repo_factory, repr(exc))
        except psycopg.OperationalError:
            # A8: DB unreachable when opening conns (before TaskGroup).
            # Skip the secondary record-error attempt — it would just fail.
            logger.exception("ws consumer: DB unreachable; backoff=%.1fs", backoff)
        except BaseExceptionGroup as eg:
            # TaskGroup wraps task crashes in BaseExceptionGroup. A pure
            # _FeedQuiet group on a xenon session is a primary-feed failure,
            # not a crash — block xenon and go straight to massive (the
            # session's final flush already ran, so no ticks were lost).
            quiet, rest = eg.split(_FeedQuiet)
            if quiet is not None and rest is None and use_xenon:
                xenon_blocked_until = (
                    time.monotonic() + settings.xenon_ws_retry_primary_seconds
                )
                logger.warning(
                    "xenon ws went quiet (%s); falling back to massive for %.0fs",
                    repr(quiet),
                    settings.xenon_ws_retry_primary_seconds,
                )
                continue
            # Pull out OperationalErrors (A8) so a DB outage mid-session
            # doesn't trigger the secondary error-record path.
            op_errs, _rest = eg.split(psycopg.OperationalError)
            if op_errs is not None:
                logger.exception(
                    "ws consumer: DB error mid-session; backoff=%.1fs", backoff
                )
            else:
                logger.exception(
                    "ws consumer crashed: %s; backoff=%.1fs", repr(eg), backoff
                )
                _record_ws_error_best_effort(repo_factory, repr(eg))
        except Exception as exc:
            logger.exception(
                "ws consumer crashed: %s; backoff=%.1fs", repr(exc), backoff
            )
            _record_ws_error_best_effort(repo_factory, repr(exc))
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, settings.massive_ws_reconnect_backoff_max_seconds)


def main() -> int:
    import signal
    from contextlib import contextmanager

    settings = Settings.from_env()
    if not (settings.massive_ws_enabled or settings.xenon_ws_enabled):
        logger.warning(
            "neither MASSIVE_WS_ENABLED nor XENON_WS_ENABLED is true; exiting"
        )
        return 0
    if settings.massive_ws_enabled and settings.massive_api_key is None:
        if settings.xenon_ws_enabled:
            logger.warning(
                "MASSIVE_API_KEY missing — running xenon-only (no massive fallback)"
            )
        else:
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
        except asyncio.CancelledError as exc:
            logger.info(
                "ws consumer cancelled by signal — graceful shutdown (%s)",
                repr(exc),
            )

    asyncio.run(_run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
