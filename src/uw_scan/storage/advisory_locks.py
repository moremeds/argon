"""Advisory locks: one registry of keys and one ``single_flight`` (I-53/I-54).

Two jobs that pick the same key silently skip each other -- the second logs "lock
held; skipping" and does nothing -- so every key lives here, and importing this
module asserts that no two names can ever resolve to the same key. That includes
every slot of a per-worker range and every fixed-name hashed key. Per-ticker hashed
namespaces cannot be enumerated; their prefixes are asserted distinct instead.

``single_flight`` replaces the hand-rolled ``pg_try_advisory_lock`` /
``pg_advisory_unlock`` pairs. Session-scoped, like every copy it replaced: the lock
survives a ROLLBACK, so release first rolls back an ABORTED transaction (a bare
unlock would itself fail with InFailedSqlTransaction and leave the lock held on a
pooled connection), and a release failure never masks the body's own exception.

``storage/mcp_events.py`` uses ``pg_advisory_xact_lock`` (blocking, released at
commit) on purpose; its key is registered here for the overlap check only.
"""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg import pq

logger = logging.getLogger(__name__)

#: Fixed keys. The mnemonics in the old modules: 915xx = migration 015/049 slots,
#: 108xx = migration 108 slots.
FIXED: dict[str, int] = {
    "intraday_refresh": 91502,
    "greek_daily_refresh": 91503,
    "intraday_backfill": 91504,
    "pipeline_benchmark": 91601,
    "data_gap_healer": 92010,
    "cockpit_snapshot": 92201,
    "discovery_scan": 92401,
    "uw_alpha_gex_levels": 10801,
    "uw_alpha_volatility": 10802,
    "uw_alpha_short_pressure": 10803,
    "uw_alpha_intraday_flow": 10804,
    "uw_alpha_dark_lit": 10805,
    "mcp_event": 727_000_154,
}

#: Per-worker ranges: name -> base; worker i holds base + i.
#: flow_data_refresh moved off 91501 + i in 2026-10: that range ran into the fixed
#: 91502/91503/91504, so uw-1's flow refresh held INTRADAY_REFRESH_LOCK.
PER_WORKER: dict[str, int] = {"flow_data_refresh": 91701}
#: Slots asserted per range. Far above any fleet we run (uw workers: 2).
WORKER_SPAN = 17

#: Global locks keyed by the md5 of a fixed name (API single-flights).
HASHED_GLOBAL = ("theta_harvester_scan", "theta_harvester_quote")
#: Per-ticker locks keyed by the md5 of ``prefix + ticker``.
HASHED_PREFIXES = ("vol_backfill:", "technicals_refresh:")

#: Known overlaps, each with its reason. Empty is the goal.
KNOWN_OVERLAPS: dict[tuple[str, str], str] = {}


def hashed_key(text: str) -> int:
    """Python twin of ``('x' || substr(md5(text), 1, 16))::bit(64)::bigint``."""
    head = hashlib.md5(text.encode()).hexdigest()[:16]
    return int.from_bytes(bytes.fromhex(head), "big", signed=True)


def fixed_key(name: str) -> int:
    return FIXED[name]


def worker_key(name: str, worker_index: int) -> int:
    if not 0 <= worker_index < WORKER_SPAN:
        raise ValueError(f"worker_index {worker_index} outside the asserted span")
    return PER_WORKER[name] + worker_index


def ticker_key(prefix: str, ticker: str) -> int:
    if prefix not in HASHED_PREFIXES:
        raise KeyError(prefix)
    return hashed_key(prefix + ticker)


def all_keys() -> dict[str, int]:
    """Every enumerable key by name."""
    out = dict(FIXED)
    for name, base in PER_WORKER.items():
        out.update({f"{name}[{i}]": base + i for i in range(WORKER_SPAN)})
    out.update({name: hashed_key(name) for name in HASHED_GLOBAL})
    return out


def overlaps() -> set[tuple[str, str]]:
    keys = all_keys()
    by_key: dict[int, list[str]] = {}
    for name, value in keys.items():
        by_key.setdefault(value, []).append(name)
    pairs: set[tuple[str, str]] = set()
    for names in by_key.values():
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                pairs.add(tuple(sorted((a, b))))  # type: ignore[arg-type]
    return pairs


def _assert_registry() -> None:
    unknown = overlaps() - {tuple(sorted(p)) for p in KNOWN_OVERLAPS}
    if unknown:
        raise RuntimeError(f"advisory-lock keys collide: {sorted(unknown)}")
    dup = [p for p, n in Counter(HASHED_PREFIXES).items() if n > 1]
    nested = [
        (a, b)
        for a in HASHED_PREFIXES
        for b in HASHED_PREFIXES
        if a != b and b.startswith(a)
    ]
    if dup or nested:
        raise RuntimeError(f"hashed lock prefixes overlap: {dup or nested}")


_assert_registry()


def _release(conn: psycopg.Connection, lock_key: int) -> None:
    if conn.info.transaction_status == pq.TransactionStatus.INERROR:
        conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))


@contextmanager
def single_flight(conn: psycopg.Connection, lock_key: int) -> Iterator[bool]:
    """Try the session lock; yield whether it was acquired; release if it was.

    The caller decides what "not acquired" means (skip and return, or raise).
    Re-entrant on one connection, as Postgres session locks are.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,))
        row = cur.fetchone()
    acquired = bool(row and row[0])
    try:
        yield acquired
    except BaseException:
        if acquired:
            try:
                _release(conn, lock_key)
            except Exception as exc:  # never mask the body's own failure
                logger.warning("advisory unlock of %s failed: %s", lock_key, repr(exc))
        raise
    else:
        if acquired:
            _release(conn, lock_key)
