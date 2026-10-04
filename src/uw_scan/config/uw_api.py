"""Unusual Whales API client settings (D6 concern group: uw_api)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, Field, SecretStr

from uw_scan.config._env import EnvVar


class UwApiSettings(BaseModel):
    api_key: SecretStr = Field(...)
    max_requests_per_minute: Annotated[
        int, EnvVar("UW_SCAN_MAX_REQUESTS_PER_MINUTE")
    ] = 110
    request_timeout_seconds: Annotated[
        float, EnvVar("UW_SCAN_REQUEST_TIMEOUT_SECONDS")
    ] = 30.0
    base_url: Annotated[str, EnvVar("UW_SCAN_BASE_URL")] = (
        "https://api.unusualwhales.com"
    )
