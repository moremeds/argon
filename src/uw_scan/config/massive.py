"""massive.com REST and WebSocket settings (D6 concern group: massive)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr

from uw_scan.config._env import EnvVar, _true_only


class MassiveSettings(BaseModel):
    # OHLC provider (massive.com)

    # SecretStr("") is truthy and not None — would silently allow the
    # scheduler to instantiate a Massive client with a blank bearer and
    # generate a stream of 401s. Coerce blank to None before wrapping.
    massive_api_key: Annotated[
        SecretStr | None, EnvVar("MASSIVE_API_KEY", strip=True, blank_is_default=True)
    ] = None
    massive_base_url: Annotated[str, EnvVar("MASSIVE_BASE_URL")] = (
        "https://api.massive.com"
    )
    # massive.com WebSocket consumer (replaces REST per-ticker spot polling).
    # Default URL points at the DELAYED tier (matches the dev plan and the
    # current massive subscription). Real-time tier upgrade: set
    # MASSIVE_WS_URL=wss://socket.massive.com/stocks in the environment.
    massive_ws_enabled: Annotated[
        bool, EnvVar("MASSIVE_WS_ENABLED", parse=_true_only)
    ] = False
    massive_ws_url: Annotated[str, EnvVar("MASSIVE_WS_URL")] = (
        "wss://delayed.massive.com/stocks"
    )
    massive_ws_channel: Annotated[str, EnvVar("MASSIVE_WS_CHANNEL")] = (
        "A"  # A=per-second, AM=per-minute, T=trades
    )
    massive_ws_flush_interval_seconds: Annotated[
        float, EnvVar("MASSIVE_WS_FLUSH_INTERVAL_SECONDS")
    ] = 1.0
    massive_ws_watchlist_poll_interval_seconds: Annotated[
        float, EnvVar("MASSIVE_WS_WATCHLIST_POLL_INTERVAL_SECONDS")
    ] = 30.0
    massive_ws_reconnect_backoff_initial_seconds: Annotated[
        float, EnvVar("MASSIVE_WS_RECONNECT_BACKOFF_INITIAL_SECONDS")
    ] = 1.0
    massive_ws_reconnect_backoff_max_seconds: Annotated[
        float, EnvVar("MASSIVE_WS_RECONNECT_BACKOFF_MAX_SECONDS")
    ] = 60.0
    massive_ws_heartbeat_stale_after_seconds: Annotated[
        float, EnvVar("MASSIVE_WS_HEARTBEAT_STALE_AFTER_SECONDS")
    ] = 120.0
