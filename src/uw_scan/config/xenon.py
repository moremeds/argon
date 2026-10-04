"""xenon IB realtime WS and read-only query API (D6 concern group: xenon)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr

from uw_scan.config._env import EnvVar, _true_only


class XenonSettings(BaseModel):
    # xenon IB realtime WS (primary live spot feed when enabled; the massive
    # WS above becomes the automatic fallback). Served by the sibling xenon
    # project's ib_realtime_server.js — streams 24h whenever IB Gateway is
    # connected, not just the massive 04:00-20:00 ET window. Port may drift
    # if 8765 is taken — the server writes the actual port to
    # xenon_ws_port_file; discovery only applies when the URL host is local.
    xenon_ws_enabled: Annotated[bool, EnvVar("XENON_WS_ENABLED", parse=_true_only)] = (
        False
    )
    xenon_ws_url: Annotated[str, EnvVar("XENON_WS_URL")] = "ws://127.0.0.1:8765"
    xenon_ws_port_file: Annotated[str, EnvVar("XENON_WS_PORT_FILE")] = (
        "/tmp/xenon-ib-realtime.json"
    )
    # After a xenon failure, stay on massive for this long before re-probing.
    xenon_ws_retry_primary_seconds: Annotated[
        float, EnvVar("XENON_WS_RETRY_PRIMARY_SECONDS")
    ] = 300.0
    # In-session silence threshold before failing over (0 disables watchdog).
    xenon_ws_quiet_failover_seconds: Annotated[
        float, EnvVar("XENON_WS_QUIET_FAILOVER_SECONDS")
    ] = 120.0
    # xenon read-only query API (IB option greeks via GET /options/greeks).
    # Default = the mini's authenticated localhost port (verified listening 2026-06-24;
    # the old :8421 was dead → the surface canary silently no-op'd). Key REQUIRED even
    # on localhost. MacBook dev points over Tailscale: http://100.66.147.98:8321.
    xenon_query_api_url: Annotated[str, EnvVar("XENON_QUERY_API_URL")] = (
        "http://127.0.0.1:8321"
    )
    xenon_query_api_key: Annotated[
        SecretStr | None,
        EnvVar("XENON_QUERY_API_KEY", strip=True, blank_is_default=True),
    ] = None
