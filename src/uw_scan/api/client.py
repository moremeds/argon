"""HTTP client for the UW API.

Honors UW's published rate-limit headers proactively (sleeps when the per-minute
remaining counter drops below a small threshold) and retries 429/5xx with
exponential backoff. Never logs the bearer token.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from .endpoints import REGISTRY, Endpoint, EndpointSlug, build_path

logger = logging.getLogger(__name__)


class UwHTTPError(Exception):
    """Raised for non-2xx responses we can't recover from."""

    def __init__(self, status_code: int, slug: str, body_excerpt: str) -> None:
        super().__init__(f"UW HTTP {status_code} on {slug}: {body_excerpt[:300]}")
        self.status_code = status_code
        self.slug = slug
        self.body_excerpt = body_excerpt


class LiveDataUnavailable(Exception):
    """Raised when network or auth is unrecoverable."""


@dataclass
class RateLimitState:
    daily_count: int | None = None
    minute_remaining: int | None = None
    minute_reset: str | None = None
    daily_limit: int | None = None


class UwClient:
    """Synchronous UW client. One instance per pipeline run is the intended usage."""

    PROACTIVE_THRESHOLD = 5  # if minute_remaining < this, sleep before next request

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.unusualwhales.com",
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise LiveDataUnavailable("UW API key is empty")
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=timeout)
        self.rate_limit = RateLimitState()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "UwClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(
        self,
        slug: EndpointSlug,
        ticker: str | None = None,
        params: dict[str, object] | None = None,
    ) -> tuple[httpx.Response, dict[str, str]]:
        """Make a GET request; returns (response, header_snapshot)."""
        ep: Endpoint = REGISTRY[slug]
        params = dict(params or {})
        missing = [p for p in ep.required_params if p not in params]
        if missing:
            raise ValueError(f"{slug}: missing required params: {missing}")

        path = build_path(slug, ticker)
        url = f"{self.base_url}{path}"
        self._proactive_sleep()

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.exception(
                    "transport error on %s attempt %d: %s", slug, attempt, repr(exc)
                )
                self._backoff(attempt)
                continue

            self._absorb_headers(resp)

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                logger.warning(
                    "UW %s returned %d (attempt %d); reset_hdr=%r",
                    slug,
                    resp.status_code,
                    attempt,
                    self.rate_limit.minute_reset,
                )
                if attempt < self.max_retries:
                    self._backoff(attempt)
                    continue
                raise UwHTTPError(resp.status_code, str(slug), resp.text)

            if resp.status_code >= 400:
                raise UwHTTPError(resp.status_code, str(slug), resp.text)

            return resp, {k.lower(): v for k, v in resp.headers.items()}

        # Exhausted retries without a response
        raise LiveDataUnavailable(
            f"could not reach UW for {slug}: {repr(last_exc) if last_exc else 'unknown'}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _absorb_headers(self, resp: httpx.Response) -> None:
        h = resp.headers
        try:
            if (v := h.get("x-uw-daily-req-count")) is not None:
                self.rate_limit.daily_count = int(v)
            if (v := h.get("x-uw-req-per-minute-remaining")) is not None:
                self.rate_limit.minute_remaining = int(v)
            if (v := h.get("x-uw-token-req-limit")) is not None:
                self.rate_limit.daily_limit = int(v)
            self.rate_limit.minute_reset = h.get("x-uw-req-per-minute-reset")
            logger.info(
                "uw rate state: daily=%s/%s minute_rem=%s reset=%s",
                self.rate_limit.daily_count,
                self.rate_limit.daily_limit,
                self.rate_limit.minute_remaining,
                self.rate_limit.minute_reset,
            )
        except (ValueError, TypeError) as exc:
            logger.exception("failed to parse UW rate headers: %s", repr(exc))

    def _proactive_sleep(self) -> None:
        rem = self.rate_limit.minute_remaining
        if rem is None or rem >= self.PROACTIVE_THRESHOLD:
            return
        # Reset unit unconfirmed (S0 finding); treat as seconds, cap at 65s.
        wait_s = 10.0
        reset_raw = self.rate_limit.minute_reset
        if reset_raw is not None:
            try:
                wait_s = min(65.0, max(1.0, float(reset_raw)))
            except ValueError as exc:
                logger.debug("failed to parse reset_raw=%r: %s", reset_raw, repr(exc))
        logger.warning(
            "uw minute_remaining=%s under threshold %s, sleeping %.1fs",
            rem,
            self.PROACTIVE_THRESHOLD,
            wait_s,
        )
        time.sleep(wait_s)

    def _backoff(self, attempt: int) -> None:
        delay = min(30.0, 0.5 * (2**attempt))
        logger.info("retrying after %.1fs (attempt %d)", delay, attempt)
        time.sleep(delay)
