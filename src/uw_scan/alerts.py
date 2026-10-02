"""One-webhook ops alert sink (Discord/Pushover-compatible JSON POST).

ponytail: single POST, no notification framework. Add per-channel routing only
if a second sink is ever genuinely needed.
"""

from __future__ import annotations

import logging

import httpx

from uw_scan.config import Settings
from uw_scan.storage.mcp_events import emit_event
from uw_scan.storage.ops_health import _ops_conn

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    # NOTE: `get_settings()` lives in `api.deps`, not `config` — a worker-layer
    # module must not import the API layer. Load Settings via `from_env()`:
    # `Settings` is a plain BaseModel with a required `api_key`, so bare
    # `Settings()` ALWAYS raises ValidationError (it never reads env). Only
    # `from_env()` populates fields — including `ops_alert_webhook_url` — from
    # the environment.
    return (Settings.from_env().ops_alert_webhook_url or "").strip()


def _emit_ops_event(title: str, message: str) -> None:
    """Record the alert on the `mcp_event` stream (kind='ops', basis='ops').

    Own autocommit conn (`storage.ops_health._ops_conn` pattern): the emit must
    not ride the caller's transaction — a job's later rollback would retract an
    alert that already went out.
    """
    with _ops_conn() as conn, conn.transaction():
        # _ops_conn is autocommit: without an explicit transaction each statement
        # commits alone, the advisory lock drops before the INSERT, and an ops id
        # could commit ahead of a lower uncommitted one (get_events would skip it).
        emit_event(
            conn,
            kind="ops",
            subject=title,
            basis="ops",
            payload={"message": message},
        )


def send_alert(title: str, message: str) -> bool:
    # The event-stream emit is independent of webhook delivery — own conn, own
    # never-raise try, and BEFORE the empty-webhook early return so a caller
    # without a configured webhook still lands on the event stream.
    try:
        _emit_ops_event(title, message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ops alert event emit failed: %s", repr(exc), exc_info=True)
    # NOTE: `_webhook_url()` (i.e. `Settings.from_env()`) is inside the try too
    # — a caller like `may_spend()` (pure/env-agnostic by design) must never
    # see this raise, e.g. if UW_SCAN_API_KEY isn't set in its process.
    try:
        url = _webhook_url()
        if not url:
            return False
        resp = httpx.post(
            url, json={"content": f"**[argon] {title}**\n{message}"}, timeout=5.0
        )
        return 200 <= resp.status_code < 300
    except Exception as exc:  # alerting must never take down the caller
        logger.warning("ops alert POST failed: %s", repr(exc), exc_info=True)
        return False
