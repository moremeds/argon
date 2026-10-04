"""apex REST client and the agent-ingest token (D6 concern group: apex)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr

from uw_scan.config._env import EnvVar, _rstrip_slash

#: apex REST default (Tailscale); the mini sets APEX_API_URL=http://127.0.0.1:8322.
DEFAULT_APEX_API_URL = "http://100.66.147.98:8322"


class ApexSettings(BaseModel):
    # apex REST API (bars / bulk closes). Same env name and default the client
    # used to read from os.environ itself; the mini sets APEX_API_URL.
    apex_api_url: Annotated[str, EnvVar("APEX_API_URL", parse=_rstrip_slash)] = (
        DEFAULT_APEX_API_URL
    )
    #: Shared bearer token for POST /api/agent-runs. UNSET MEANS DISABLED
    #: (503), never open — the one write surface whose failure mode is a
    #: document a person reads as a briefing.
    agent_ingest_token: Annotated[
        SecretStr | None,
        EnvVar("UW_SCAN_AGENT_INGEST_TOKEN", strip=True, blank_is_default=True),
    ] = None
