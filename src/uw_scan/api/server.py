"""FastAPI app factory + ASGI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uw_scan.api.routers import (
    benchmark,
    cockpit,
    gold,
    health,
    jobs,
    ohlc,
    provider_usage,
    rates,
    regime,
    regime_validation,
    scanner,
    skew,
    stock,
    trade_insights,
    volatility,
    watchlist,
)


def create_app() -> FastAPI:
    app = FastAPI(title="UW Watchlist API", version="0.1.0")
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
    app.include_router(scanner.router, prefix="/api", tags=["scanner"])
    return app


app = create_app()
