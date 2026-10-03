"""Guard: every FastAPI GET route that has a side effect must be in the MCP
denylist (``DENYLIST`` in ``web/mcp/lib/endpoints.ts``).

Side effects detected: a ``BackgroundTasks`` parameter on the endpoint
signature (the route schedules work that writes/uses upstream spend), plus a
hand-maintained list of known writers (GETs that commit). Adding a new
side-effecting GET without denylisting it fails this test.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI
from fastapi.routing import APIRoute

from uw_scan.api.server import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
ENDPOINTS_TS = REPO_ROOT / "web" / "mcp" / "lib" / "endpoints.ts"

# GET handlers that write WITHOUT a BackgroundTasks param (e.g. they upsert +
# commit inline). Kept deliberately short — signature detection covers the
# BackgroundTasks family; anything else must be named here AND in the
# TypeScript denylist.
# trade-insights left this set when its GET stopped writing (I-21; the write
# moved to POST /stock/{ticker}/trade-insights/refresh).
KNOWN_WRITING_GETS = {
    # Upserts a 'queued' volatility_backfill_status row the uw-0 worker turns
    # into UW spend (was a BackgroundTasks backfill before I-22).
    "/stock/{ticker}/volatility/series",
}


def _mcp_denylist() -> set[str]:
    """Parse the DENYLIST literal out of endpoints.ts (avoids a TS runtime)."""
    src = ENDPOINTS_TS.read_text()
    m = re.search(r"DENYLIST[^=]*=\s*new Set<string>\(\[(.*?)\]\)", src, re.S)
    assert m, "DENYLIST literal not found in endpoints.ts"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _side_effecting_get_paths(app=None) -> set[str]:
    """GET routes (``/api``-stripped) whose handler takes a BackgroundTasks."""
    app = app or create_app()
    out: set[str] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute) or "GET" not in route.methods:
            continue
        # FastAPI's resolved dependant, not inspect.signature: every router uses
        # `from __future__ import annotations`, so a raw signature carries the
        # STRING "BackgroundTasks" and an identity check never matches.
        if route.dependant.background_tasks_param_name:
            out.add(route.path.removeprefix("/api"))
    return out


def test_detector_finds_a_background_task_get() -> None:
    """Keeps the guard below from passing vacuously. No real GET takes a
    BackgroundTasks today (the volatility backfill moved to a durable queue),
    so prove the detector on a toy app that has one."""
    toy = FastAPI()

    @toy.get("/api/spends")
    def spends(background_tasks: BackgroundTasks) -> dict:
        return {}

    @toy.get("/api/reads")
    def reads() -> dict:
        return {}

    assert _side_effecting_get_paths(toy) == {"/spends"}


def test_side_effecting_gets_are_denylisted() -> None:
    denylist = _mcp_denylist()
    must_deny = _side_effecting_get_paths() | KNOWN_WRITING_GETS
    missing = sorted(must_deny - denylist)
    assert not missing, (
        "side-effecting GET routes missing from web/mcp/lib/endpoints.ts "
        f"DENYLIST: {missing} — add them or the MCP exposes writes via GET"
    )


def test_denylist_entries_are_real_paths() -> None:
    """A typo'd denylist entry silently fails to deny — pin every entry to a
    route the app actually serves."""
    app = create_app()
    served = {
        route.path.removeprefix("/api")
        for route in app.routes
        if isinstance(route, APIRoute) and "GET" in route.methods
    }
    bogus = sorted(_mcp_denylist() - served)
    assert not bogus, f"DENYLIST names no real GET route: {bogus}"
