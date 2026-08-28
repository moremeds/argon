"""The fundamentals industry desk — routing surface (spec §2–§4, Task 13).

Six read-only endpoints over the warm store. Nothing here writes, and nothing
here reaches a provider: every number was persisted by a job.

A SECTION IS A REGISTRY ROW, A NODE IS TAXONOMY ROWS
------------------------------------------------------
`SECTIONS` maps a URL section to the research domains it covers. Adding a
section is one entry here; adding a CHAIN inside a registered section is zero
code — `research_chains` + `chain_membership` rows and it appears (spec §2's
extension contract, pinned by
`test_rows_only_chain_reaches_both_endpoints`).

That domain filter only DISCRIMINATES because Task 19 gave chains a real
per-chain domain map. Before it every chain carried `ai_infrastructure` and
this tuple selected all 38 — putting Banks and Sector-ETF on the AI/semi
desk.

`chain` TRAVELS AS A QUERY PARAMETER, NEVER A PATH SEGMENT
------------------------------------------------------------
Most real chain names contain a slash (`Networking/Optical`,
`Semi-Logic/ASIC`, `Computer/GPU`, `Cooling/Thermal`, …: 20 of 38 measured).
A `%2F`-encoded slash in a FastAPI PATH parameter returns 404 — verified
empirically 2026-08-28 — while the same value in a query parameter returns
200. Do not reintroduce a chain path segment on any endpoint.

WHY UNKNOWN QUERY PARAMETERS ARE A 422
----------------------------------------
FastAPI ignores undeclared query params by default, so `?sort=median` would
return 200 and quietly do nothing — which reads to the caller as "the sort
was applied". This desk LISTS and must never RANK (cross-sectional value
measured INVERTED here, `book_to_price` IC -0.0365, t -2.32), so
"there is no sort parameter" has to be enforced structurally rather than by
silence. `_reject_unknown_query_params` derives the allowed set from the
route's OWN declared parameters, so it cannot drift from the signatures.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.models import (
    DeltaRailResponse,
    DeskCalendarResponse,
    DeskLimitsResponse,
    DeskMatrixResponse,
    NodeUnderwritingRow,
    ProfitPoolLayer,
)
from uw_scan.reports import fundamentals_desk as desk
from uw_scan.storage.repository import Repository

log = logging.getLogger(__name__)

#: URL section -> the research domains it covers. A new section is a row
#: here; a new chain inside one is not a code change at all.
SECTIONS: dict[str, tuple[str, ...]] = {
    "ai-semi": ("ai_infrastructure", "dc_buildout", "optical_communication"),
}

#: The delta rail's default window. Not a data property — it is how far back
#: "since you last looked" reaches when the caller does not say.
DEFAULT_DELTA_DAYS = 7


def _collect_declared(dependant) -> set[str]:
    """Every query-parameter alias this route declares, sub-dependencies
    included. Derived from the route rather than restated per endpoint, so a
    new parameter cannot be rejected by a guard that was not updated."""
    names = {p.alias for p in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _collect_declared(sub)
    return names


def _reject_unknown_query_params(request: Request) -> None:
    route = request.scope.get("route")
    if route is None or not hasattr(route, "dependant"):
        return
    extra = sorted(set(request.query_params) - _collect_declared(route.dependant))
    if extra:
        raise HTTPException(
            status_code=422,
            detail=(
                f"unknown query parameter(s): {', '.join(extra)}. This desk "
                "lists names; it does not rank them, so no ordering or sort "
                "parameter exists on any of its endpoints."
            ),
        )


# No `/api` prefix here: server.py adds it at registration, as every sibling
# router does.
router = APIRouter(
    tags=["fundamentals-desk"],
    dependencies=[Depends(_reject_unknown_query_params)],
)


def _domains(section: str) -> tuple[str, ...]:
    """The section's domains, or 404.

    An unknown section must NOT render as an empty desk: an empty desk is a
    claim that the section exists and has nothing in it, which is a different
    and false statement.
    """
    domains = SECTIONS.get(section)
    if domains is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown section {section!r}; known: {sorted(SECTIONS)}",
        )
    return domains


@router.get("/fundamentals/{section}/calendar", response_model=DeskCalendarResponse)
def desk_calendar(
    section: str,
    chain: str | None = Query(
        default=None,
        description=(
            "Scope to one chain's members, resolved server-side from "
            "membership. The ONLY filter — response order is fixed."
        ),
    ),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> DeskCalendarResponse:
    """Next prints across the section, upstream to downstream."""
    return desk.desk_calendar(
        repo.conn,
        schema=settings.db_schema,
        section=section,
        domains=_domains(section),
        chain=chain,
    )


@router.get("/fundamentals/{section}/delta", response_model=DeltaRailResponse)
def desk_delta(
    section: str,
    since: date | None = Query(
        default=None,
        description=(
            "Read events Argon FIRST KNEW on or after this date. A date, not "
            "an instant: `research_events.first_known_at` is a date column, "
            "and a midnight timestamp would claim a precision the ledger "
            "does not hold."
        ),
    ),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> DeltaRailResponse:
    """What changed since the operator last looked."""
    return desk.delta_rail(
        repo.conn,
        schema=settings.db_schema,
        domains=_domains(section),
        since=since or (date.today() - timedelta(days=DEFAULT_DELTA_DAYS)),
    )


@router.get("/fundamentals/{section}/matrix", response_model=DeskMatrixResponse)
def desk_matrix(
    section: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> DeskMatrixResponse:
    """chain × metric: medians over per-name dots, never weighted."""
    return desk.desk_matrix(
        repo.conn,
        schema=settings.db_schema,
        section=section,
        domains=_domains(section),
    )


@router.get("/fundamentals/{section}/profit-pool", response_model=list[ProfitPoolLayer])
def desk_profit_pool(
    section: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> list[ProfitPoolLayer]:
    """Layers side by side. Descriptive — no arrows, by design."""
    return desk.profit_pool(
        repo.conn, schema=settings.db_schema, domains=_domains(section)
    )


@router.get("/fundamentals/{section}/limits", response_model=DeskLimitsResponse)
def desk_limits(
    section: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> DeskLimitsResponse:
    """What the desk cannot say, computed rather than asserted."""
    return desk.desk_limits(
        repo.conn, schema=settings.db_schema, domains=_domains(section)
    )


@router.get(
    "/fundamentals/{section}/node/underwriting",
    response_model=list[NodeUnderwritingRow],
)
def node_underwriting(
    section: str,
    chain: str = Query(
        description=(
            "The chain to underwrite. A QUERY parameter because most real "
            "chain names contain a slash and a %2F-encoded path param 404s."
        ),
    ),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> list[NodeUnderwritingRow]:
    """One chain's members with their filed line items alongside."""
    return desk.node_underwriting(
        repo.conn,
        schema=settings.db_schema,
        domains=_domains(section),
        chain=chain,
    )
