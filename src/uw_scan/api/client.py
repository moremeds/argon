from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx


def normalize_params(params: Mapping[str, Any]) -> str:
    parts: list[str] = []
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(f"{key}={value}")
        elif isinstance(value, Sequence) and not isinstance(value, bytes):
            parts.append(f"{key}={','.join(sorted(str(item) for item in value if item is not None))}")
        else:
            parts.append(f"{key}={value}")
    return "&".join(parts)


def build_request_fingerprint(*, endpoint: str, params: Mapping[str, Any], market_date: str, api_base_url: str) -> str:
    raw = f"{api_base_url}|{endpoint}|{market_date}|{normalize_params(params)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UwApiResponse:
    endpoint: str
    params: dict[str, Any]
    status_code: int
    json_payload: Any
    latency_ms: int
    request_fingerprint: str


class UwApiClient:
    def __init__(self, *, api_key: str, base_url: str = "https://api.unusualwhales.com", timeout: float = 30.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, *, endpoint: str, params: Mapping[str, Any], market_date: str) -> UwApiResponse:
        fingerprint = build_request_fingerprint(
            endpoint=endpoint,
            params=params,
            market_date=market_date,
            api_base_url=self.base_url,
        )
        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(
                f"{self.base_url}{endpoint}",
                params={key: value for key, value in params.items() if value is not None},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        response.raise_for_status()
        return UwApiResponse(
            endpoint=endpoint,
            params=dict(params),
            status_code=response.status_code,
            json_payload=response.json(),
            latency_ms=int(response.elapsed.total_seconds() * 1000),
            request_fingerprint=fingerprint,
        )
