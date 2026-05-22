"""Validate the WS spot pipeline during a live trading session.

One-off operational tool, intentionally NOT committed as long-term code.
The plan calls for one full trading-session pass with this script tailing
the live database, then sign-off + removal.

Snapshots the active watchlist every INTERVAL_SECONDS and emits one CSV row
per snapshot with:
  - snapshot_at: UTC iso timestamp
  - watchlist_size: number of cards
  - ws_healthy: whether last_tick_at is recent enough
  - ws_ticks_received / ws_ticks_received_delta: total received counter +
    delta since last snapshot (signals raw feed pressure)
  - ws_last_tick_age_seconds: seconds since the most recent WS tick
  - sources_distribution: per-card spot_source histogram (the key signal —
    should converge to ~100% "massive.com_ws" within minutes of starting)
  - spot_age_median_seconds / spot_age_max_seconds: watchlist-wide
    quoted_at age (the cross-ticker sync metric the project was opened to fix)
  - rows_with_null_spot: cards with no spot at all (initial-load anomaly)

Usage:
    MASSIVE_WS_ENABLED=true uv run python scripts/validate_ws.py \\
        | tee /tmp/ws_validation_$(date +%Y%m%d).csv

Stop with Ctrl-C; SIGTERM also fires a graceful shutdown.
"""

from __future__ import annotations

import csv
import logging
import signal
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from statistics import median

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("validate_ws")

INTERVAL_SECONDS = 60
FIELDS = [
    "snapshot_at",
    "watchlist_size",
    "ws_healthy",
    "ws_ticks_received",
    "ws_ticks_received_delta",
    "ws_last_tick_age_seconds",
    "sources_distribution",
    "spot_age_median_seconds",
    "spot_age_max_seconds",
    "rows_with_null_spot",
]


def _snapshot(repo: Repository, prev_ticks: int) -> dict:
    now = datetime.now(timezone.utc)
    cards = repo.list_watchlist_cards()
    size = len(cards)
    sources = Counter(c.spot_source or "none" for c in cards)
    ages = [
        (now - c.spot_quoted_at).total_seconds()
        for c in cards
        if c.spot_quoted_at is not None
    ]
    null_spots = sum(1 for c in cards if c.spot is None)
    state = repo.get_ws_consumer_state()
    if state is None or state.last_tick_at is None:
        ws_healthy, ws_ticks, ws_age = False, 0, None
    else:
        ws_age = (now - state.last_tick_at).total_seconds()
        ws_ticks = state.ticks_received
        # 120s threshold mirrors the API health check's default
        # massive_ws_heartbeat_stale_after_seconds.
        ws_healthy = ws_age < 120.0
    return {
        "snapshot_at": now.isoformat(),
        "watchlist_size": size,
        "ws_healthy": ws_healthy,
        "ws_ticks_received": ws_ticks,
        "ws_ticks_received_delta": ws_ticks - prev_ticks,
        "ws_last_tick_age_seconds": ws_age,
        "sources_distribution": ";".join(f"{k}={v}" for k, v in sources.most_common()),
        "spot_age_median_seconds": median(ages) if ages else None,
        "spot_age_max_seconds": max(ages) if ages else None,
        "rows_with_null_spot": null_spots,
    }


def main() -> int:
    settings = Settings.from_env()
    writer = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    writer.writeheader()
    sys.stdout.flush()

    stop = False

    def _on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    prev_ticks = 0
    while not stop:
        # Open a fresh connection per snapshot — the script runs for hours
        # and we'd rather take a small reconnect cost each minute than risk
        # a stale conn drifting through a Postgres restart.
        conn = psycopg.connect(settings.db_dsn())
        try:
            repo = Repository(conn, schema=settings.db_schema)
            row = _snapshot(repo, prev_ticks)
            prev_ticks = row["ws_ticks_received"]
        finally:
            conn.close()
        writer.writerow(row)
        sys.stdout.flush()
        log.info(
            "snapshot: healthy=%s ticks_delta=%s sources=%s median_age=%.1fs max_age=%.1fs null=%d",
            row["ws_healthy"],
            row["ws_ticks_received_delta"],
            row["sources_distribution"],
            row["spot_age_median_seconds"] or -1,
            row["spot_age_max_seconds"] or -1,
            row["rows_with_null_spot"],
        )
        for _ in range(INTERVAL_SECONDS):
            if stop:
                break
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
