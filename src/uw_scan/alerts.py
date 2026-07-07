"""One-webhook ops alert sink (Discord/Pushover-compatible JSON POST).

ponytail: single POST, no notification framework. Add per-channel routing only
if a second sink is ever genuinely needed.
"""

from __future__ import annotations

import logging

import httpx

from uw_scan.config import Settings

logger = logging.getLogger(__name__)


def _webhook_url() -> str:
    # NOTE: `get_settings()` lives in `api.deps`, not `config` — a worker-layer
    # module must not import the API layer. Read Settings directly.
    return (Settings().ops_alert_webhook_url or "").strip()


def send_alert(title: str, message: str) -> bool:
    # NOTE: `_webhook_url()` (i.e. `Settings()`) is inside the try too — a
    # caller like `may_spend()` (pure/env-agnostic by design) must never see
    # this raise, e.g. if required env vars aren't set in its process.
    try:
        url = _webhook_url()
        if not url:
            return False
        resp = httpx.post(
            url, json={"content": f"**[argon] {title}**\n{message}"}, timeout=5.0
        )
        return 200 <= resp.status_code < 300
    except Exception:  # alerting must never take down the caller
        logger.warning("ops alert POST failed", exc_info=True)
        return False
