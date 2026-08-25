"""FastAPI app factory + ASGI entrypoint."""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from uw_scan.api.routers import (
    benchmark,
    cockpit,
    gold,
    health,
    jobs,
    macro,
    ohlc,
    positioning,
    positions,
    provider_usage,
    rates,
    regime,
    regime_validation,
    radar,
    research_evidence,
    research_reports,
    scanner,
    skew,
    stock,
    trade_insights,
    volatility,
    vrp,
    watchlist,
)
from uw_scan.version import app_version

logger = logging.getLogger(__name__)

# Request-timing monitor for our own endpoints (distinct from api/client.py's
# outbound UW latency). Log-only: every response carries X-Response-Time-ms;
# requests slower than the threshold log a WARN. Set the threshold to 0 to
# silence the warnings (the header is always added).
# ponytail: perf_counter + one log line, no deps/tables. Surface a rolling p95
# on /health only if we actually need dashboards.
_SLOW_REQUEST_MS = float(os.getenv("API_SLOW_REQUEST_MS", "500"))


async def _timing_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Response-Time-ms"] = str(int(elapsed_ms))
    if _SLOW_REQUEST_MS > 0 and elapsed_ms >= _SLOW_REQUEST_MS:
        logger.warning(
            "slow request %s %s %.0fms", request.method, request.url.path, elapsed_ms
        )
    return response


def create_app() -> FastAPI:
    app = FastAPI(title="UW Watchlist API", version=app_version())
    app.middleware("http")(_timing_middleware)
    app.add_middleware(
        CORSMiddleware,
        # CORS is URL-agnostic by design: the real trust boundary is the
        # network layer (the private Tailnet — only Tailnet peers can reach
        # this socket). Anyone who can reach the API is already authorized;
        # filtering by origin string adds no security and breaks legitimate
        # access patterns (MagicDNS hostnames, CGNAT IPs, alternate tailnets,
        # localhost dev). Permissive regex matches any origin and Starlette
        # echoes it back, which preserves compatibility with credentialed
        # requests if we ever introduce them.
        allow_origin_regex=r".*",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(benchmark.router, prefix="/api", tags=["health"])
    app.include_router(watchlist.router, prefix="/api", tags=["watchlist"])
    app.include_router(stock.router, prefix="/api", tags=["stock"])
    app.include_router(ohlc.router, prefix="/api", tags=["ohlc"])
    app.include_router(cockpit.router, prefix="/api", tags=["cockpit"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    app.include_router(volatility.router, prefix="/api", tags=["volatility"])
    app.include_router(skew.router, prefix="/api", tags=["skew"])
    app.include_router(provider_usage.router, prefix="/api", tags=["provider-usage"])
    app.include_router(trade_insights.router, prefix="/api", tags=["trade-insights"])
    app.include_router(regime.router, prefix="/api", tags=["regime"])
    app.include_router(regime_validation.router, prefix="/api", tags=["regime"])
    app.include_router(gold.router, prefix="/api", tags=["gold"])
    app.include_router(rates.router, prefix="/api", tags=["rates"])
    app.include_router(macro.router, prefix="/api", tags=["macro"])
    app.include_router(scanner.router, prefix="/api", tags=["scanner"])
    app.include_router(radar.router, prefix="/api", tags=["radar"])
    app.include_router(
        research_evidence.router, prefix="/api", tags=["research-evidence"]
    )
    app.include_router(
        research_reports.router, prefix="/api", tags=["research-reports"]
    )
    app.include_router(positioning.router, prefix="/api", tags=["positioning"])
    app.include_router(vrp.router, prefix="/api", tags=["vrp"])
    app.include_router(positions.router, prefix="/api", tags=["positions"])
    return app


app = create_app()
