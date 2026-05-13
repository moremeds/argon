"""FastAPI app factory + ASGI entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from uw_scan.api.routers import health, jobs, ohlc, stock, watchlist


def create_app() -> FastAPI:
    app = FastAPI(title="UW Watchlist API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3001",
            "http://localhost:3001",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(watchlist.router, prefix="/api", tags=["watchlist"])
    app.include_router(stock.router, prefix="/api", tags=["stock"])
    app.include_router(ohlc.router, prefix="/api", tags=["ohlc"])
    app.include_router(jobs.router, prefix="/api", tags=["jobs"])
    return app


app = create_app()
