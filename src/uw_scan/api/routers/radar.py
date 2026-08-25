"""Company dimensions v2 and the Fundamental PM Research Radar (M4).

Read-only over the warm store. Zero UW, zero IB, zero lake: every number here was
persisted by a ledgered run, and a page read that reached a provider would make
the surface's cost unbounded and its answer un-replayable.

WHY EVERY RESPONSE CARRIES A STATE
----------------------------------
An empty `rows` list is six different situations, four of which are not "this
company has no fundamentals": nothing computed under this contract, a stale run,
a capability Argon cannot support, a failed run, or genuinely no statements. The
first four are facts about ARGON; only the last is a fact about the company, and
a surface that renders them identically makes a claim it cannot support.
"""

from __future__ import annotations

import logging
from datetime import date

import psycopg
from fastapi import APIRouter, Depends, Query

from uw_scan.api.deps import get_repo, get_settings
from uw_scan.config import Settings
from uw_scan.fundamentals.claims import claim_for
from uw_scan.fundamentals.dimensions import AGGREGATE_DIMENSIONS, DIMENSIONS
from uw_scan.models import (
    ChainCell,
    ChainDrilldownResponse,
    ChainMatrixResponse,
    ChainMember,
    CompanyDimensionsResponse,
    FundamentalRunRef,
    RadarDimension,
    RadarResponse,
    RadarRow,
    RadarScope,
)
from uw_scan.storage.fundamental_dimensions import FundamentalDimensionsRepository
from uw_scan.storage.repository import Repository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

log = logging.getLogger(__name__)

# No `/api` prefix here: server.py adds it at registration, the same as
# every sibling router.
router = APIRouter(tags=["radar"])

#: The registry key whose permission licenses the Radar's default ordering.
RADAR_ORDERING_CLAIM = "composite"

#: A compatible run older than this reads as `stale_run` rather than `ok`. Not a
#: correctness threshold — the numbers stay exactly as computed — but the
#: difference between "this is current" and "this is what we last computed",
#: which an operator must be told rather than left to infer from a date.
STALE_DAYS = 45

#: |z| above which a dimension is flagged extreme. Not a filter and not a cap —
#: the value is returned exactly as computed. It marks the rows where the sort is
#: being driven by a tail, which the claim registry already warns about ("the top
#: decile is riskier than the middle"). Measured: |z|>10 is 0.03-0.3% of rows.
EXTREME_Z = 10.0


def _dimension(row: dict) -> RadarDimension:
    return RadarDimension(
        dimension=row["dimension"],
        value=float(row["value"]) if row["value"] is not None else None,
        inputs_present=int(row["inputs_present"] or 0),
        inputs_expected=int(row["inputs_expected"] or 0),
        authority=row["authority"],
        detail=row.get("detail_jsonb") or {},
    )


def _has_statements(conn: psycopg.Connection, schema: str, ticker: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT 1 FROM {schema}.fundamental_statement_obs
                 WHERE ticker = %s LIMIT 1""",
            (ticker.upper(),),
        )
        return cur.fetchone() is not None


@router.get(
    "/stock/{ticker}/fundamentals/dimensions",
    response_model=CompanyDimensionsResponse,
)
def company_dimensions(
    ticker: str,
    engine_version: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> CompanyDimensionsResponse:
    """One name's independent dimensions, or the state explaining their absence."""
    conn = repo.conn
    schema = settings.db_schema
    symbol = ticker.upper()
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = engine_version or scores.active_version()

    if engine is None:
        return CompanyDimensionsResponse(
            ticker=symbol,
            state="unsupported_capability",
            reason=(
                "no active method version is seeded; nothing can be computed "
                "under any contract"
            ),
        )

    rows = FundamentalDimensionsRepository(conn, schema=schema).for_ticker(
        symbol, engine_version=engine
    )
    if not rows:
        # The distinction that matters: is this a gap in ARGON or a fact about
        # the company? Answering both with an empty list makes the second claim.
        if not _has_statements(conn, schema, symbol):
            return CompanyDimensionsResponse(
                ticker=symbol,
                state="no_coverage",
                reason=f"Argon holds no statement observations for {symbol}",
            )
        return CompanyDimensionsResponse(
            ticker=symbol,
            state="no_compatible_run",
            reason=(
                f"statements exist for {symbol} but nothing has been computed "
                f"under engine {engine}"
            ),
        )

    as_of = max(r["as_of"] for r in rows.values())
    age = (date.today() - as_of).days
    evidence = rows.get("evidence_quality", {})
    return CompanyDimensionsResponse(
        ticker=symbol,
        state="stale_run" if age > STALE_DAYS else "ok",
        dimensions=[_dimension(r) for r in sorted(rows.values(), key=lambda r: r["dimension"])],
        run=FundamentalRunRef(
            run_id=None,
            engine_version=engine,
            evidence_policy="current_vintage",
            as_of=as_of,
            as_of_cutoff=None,
            computed_at=None,
            status="succeeded",
        ),
        reason=(
            f"newest compatible result is {age} days old (>{STALE_DAYS})"
            if age > STALE_DAYS
            else None
        ),
        evidence_coverage=(
            float(evidence["value"]) if evidence.get("value") is not None else None
        ),
    )


@router.get("/scanner/radar", response_model=RadarResponse)
def radar(
    tier: str = Query(default="ranked"),
    engine_version: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    min_dimensions: int = Query(
        default=2,
        ge=0,
        le=4,
        description="Hide names whose aggregate rested on fewer dimensions.",
    ),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> RadarResponse:
    """Cross-universe attention routing, ordered only as the claim registry allows.

    NO HIDDEN RENORMALIZATION. Two names whose aggregates rest on different
    dimension sets are both returned, each carrying `dimensions_present` and
    `missing_dimensions`, and the caller sees the denominators rather than a
    column of numbers that silently mean different things.
    """
    conn = repo.conn
    schema = settings.db_schema
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = engine_version or scores.active_version()
    claim = claim_for(RADAR_ORDERING_CLAIM)

    scope = RadarScope(
        universe="fundamental_universe",
        tier=tier,
        as_of=None,
        evidence_policy="current_vintage",
        engine_version=engine,
        names=0,
        names_without_result=0,
    )
    if engine is None:
        return RadarResponse(
            scope=scope,
            rows=[],
            ordering=RADAR_ORDERING_CLAIM,
            ordering_authority=claim.authority.value,
            prohibited=list(claim.prohibited),
            state="unsupported_capability",
            reason="no active method version is seeded",
        )

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT count(*) FROM {schema}.fundamental_universe
                 WHERE tier = %s AND removed_at IS NULL""",
            (tier,),
        )
        scope.names = int(cur.fetchone()[0])

        # Newest as_of per (ticker, dimension) under this engine, restricted to
        # the tier. DISTINCT ON rather than a window function: one index scan,
        # and the ordering is the same one the index already provides.
        cur.execute(
            f"""
            SELECT DISTINCT ON (d.ticker, d.dimension)
                   d.ticker, d.dimension, d.value, d.inputs_present,
                   d.inputs_expected, d.authority, d.detail_jsonb, d.as_of,
                   t.company_type
              FROM {schema}.fundamental_dimensions d
              JOIN {schema}.fundamental_universe u
                ON u.ticker = d.ticker AND u.tier = %s AND u.removed_at IS NULL
              LEFT JOIN {schema}.fundamental_company_type t ON t.ticker = d.ticker
             WHERE d.engine_version = %s
             ORDER BY d.ticker, d.dimension, d.as_of DESC
            """,
            (tier, engine),
        )
        by_ticker: dict[str, dict] = {}
        for (
            tkr, dim, value, present, expected, authority, detail, as_of, ctype,
        ) in cur.fetchall():
            entry = by_ticker.setdefault(
                tkr, {"company_type": ctype, "as_of": as_of, "dims": {}}
            )
            entry["dims"][dim] = {
                "dimension": dim,
                "value": value,
                "inputs_present": present,
                "inputs_expected": expected,
                "authority": authority,
                "detail_jsonb": detail or {},
            }
            entry["as_of"] = max(entry["as_of"], as_of)

    rows: list[RadarRow] = []
    for tkr, entry in by_ticker.items():
        dims = entry["dims"]
        priority = dims.get("priority")
        present = [d for d in AGGREGATE_DIMENSIONS if dims.get(d, {}).get("value") is not None]
        if len(present) < min_dimensions:
            continue
        evidence = dims.get("evidence_quality", {})
        rows.append(
            RadarRow(
                ticker=tkr,
                company_type=entry["company_type"],
                priority=(
                    float(priority["value"])
                    if priority and priority["value"] is not None
                    else None
                ),
                priority_authority=(
                    priority["authority"] if priority else "descriptive"
                ),
                dimensions_present=len(present),
                dimensions_expected=len(AGGREGATE_DIMENSIONS),
                missing_dimensions=[
                    d for d in AGGREGATE_DIMENSIONS if d not in present
                ],
                dimensions=[
                    _dimension(dims[d]) for d in sorted(dims) if d in DIMENSIONS
                ],
                evidence_coverage=(
                    float(evidence["value"])
                    if evidence.get("value") is not None
                    else None
                ),
                as_of=entry["as_of"],
                extreme_dimensions=sorted(
                    d
                    for d, v in dims.items()
                    if d in DIMENSIONS
                    and v.get("value") is not None
                    and abs(float(v["value"])) > EXTREME_Z
                ),
            )
        )

    # Descending priority, nulls LAST. A refused aggregate must not sort to the
    # top of a list the operator reads top-down.
    rows.sort(key=lambda r: (r.priority is None, -(r.priority or 0.0), r.ticker))
    scope.names_without_result = max(scope.names - len(by_ticker), 0)

    # An empty table over a NON-empty universe is not "ok with no rows" — it is
    # "nothing has been computed under this contract", which is a fact about
    # Argon and not about 449 companies. This is the whole reason the state model
    # exists, so the Radar must not be the surface that ignores it.
    state = "ok"
    reason = None
    if not by_ticker and scope.names:
        state = "no_compatible_run"
        reason = (
            f"{scope.names} names in tier {tier!r} but no dimensions computed "
            f"under engine {engine} — run the scoring job under an engine whose "
            "validity policy emits dimensions"
        )

    return RadarResponse(
        scope=scope,
        rows=rows[:limit],
        ordering=RADAR_ORDERING_CLAIM,
        ordering_authority=claim.authority.value,
        prohibited=list(claim.prohibited),
        state=state,
        reason=reason,
    )


#: What a chain aggregate may never be read as. Measured, not stylistic: the
#: capex-demand ledger's cross-name relationship collapsed from +0.247 to +0.015
#: (p=0.44) once same-SECTOR pairs were compared, which is the finding that a
#: chain — as membership — is a sector by another name.
CHAIN_PROHIBITED = [
    "a causal claim — no edge in this taxonomy has demonstrated forward "
    "information, so nothing propagates from one layer to another",
    "a supplier/customer relationship — membership is semantic, and a named "
    "counterparty requires a named source",
    "an economic exposure, unless the row carries a disclosed magnitude "
    "(measured at 4 of 316 members)",
]

#: A cell needs at least this many members with a compatible result before it
#: reports a mean. Below it the cell abstains: a mean over one name is that
#: name's number wearing a chain's label.
MIN_CELL_MEMBERS = 3


@router.get("/research/chains/matrix", response_model=ChainMatrixResponse)
def chain_matrix(
    taxonomy_version: str | None = Query(default=None),
    engine_version: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ChainMatrixResponse:
    """chain × layer matrix, rolled up from compatible company results.

    Read-time rollup, not a cached aggregate: the inputs are already persisted
    and a cache here would be a second place for the as-of to disagree with
    itself.
    """
    conn = repo.conn
    schema = settings.db_schema
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    version = taxonomy_version or tax.active_version()
    engine = engine_version or FundamentalScoresRepository(
        conn, schema=schema
    ).active_version()

    if version is None:
        return ChainMatrixResponse(
            taxonomy_version="",
            engine_version=engine,
            cells=[],
            state="unsupported_capability",
            reason="no active taxonomy version is published",
            prohibited=CHAIN_PROHIBITED,
        )

    params: list[object] = [engine, version]
    domain_clause = ""
    if domain:
        domain_clause = " AND c.domain = %s"
        params.append(domain)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, value
                  FROM {schema}.fundamental_dimensions
                 WHERE engine_version = %s AND dimension = 'priority'
                 ORDER BY ticker, as_of DESC
            )
            SELECT c.domain, c.chain, c.layer, c.layer_rank,
                   count(m.membership_id)                              AS members,
                   count(l.ticker)                                     AS with_result,
                   avg(l.value)                                        AS priority_mean,
                   count(DISTINCT e.ticker) FILTER
                        (WHERE e.magnitude IS NOT NULL)                AS with_magnitude
              FROM {schema}.research_chains c
              LEFT JOIN {schema}.chain_membership m
                     ON m.taxonomy_version = c.taxonomy_version
                    AND m.chain = c.chain AND m.layer = c.layer
                    AND m.valid_to IS NULL
              LEFT JOIN latest l ON l.ticker = m.ticker
              LEFT JOIN {schema}.company_exposure e
                     ON e.taxonomy_version = m.taxonomy_version
                    AND e.chain = m.chain AND e.ticker = m.ticker
                    AND e.valid_to IS NULL
             WHERE c.taxonomy_version = %s{domain_clause}
             GROUP BY c.domain, c.chain, c.layer, c.layer_rank
             ORDER BY c.domain, c.chain, c.layer_rank, c.layer
            """,
            params,
        )
        rows = cur.fetchall()

    cells: list[ChainCell] = []
    for dom, chain, layer, rank, members, with_result, mean, with_mag in rows:
        abstain = None
        value = None
        if members == 0:
            abstain = "no members in this cell"
        elif with_result < MIN_CELL_MEMBERS:
            # A mean over one or two names is those names' number wearing a
            # chain's label. Abstaining says so; rendering it would not.
            abstain = (
                f"only {with_result} of {members} members carry a compatible "
                f"result ({MIN_CELL_MEMBERS} required)"
            )
        else:
            value = float(mean) if mean is not None else None
        cells.append(
            ChainCell(
                chain=chain,
                layer=layer,
                domain=dom,
                layer_rank=int(rank or 0),
                members=int(members),
                with_result=int(with_result),
                priority_mean=value,
                with_magnitude=int(with_mag or 0),
                abstain_reason=abstain,
            )
        )

    return ChainMatrixResponse(
        taxonomy_version=version,
        engine_version=engine,
        cells=cells,
        coverage=tax.exposure_coverage(version),
        prohibited=CHAIN_PROHIBITED,
    )


@router.get("/research/chains/{chain}", response_model=ChainDrilldownResponse)
def chain_members(
    chain: str,
    layer: str | None = Query(default=None),
    taxonomy_version: str | None = Query(default=None),
    engine_version: str | None = Query(default=None),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ChainDrilldownResponse:
    """The names behind a cell, each with its exposure evidence."""
    conn = repo.conn
    schema = settings.db_schema
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    version = taxonomy_version or tax.active_version()
    engine = engine_version or FundamentalScoresRepository(
        conn, schema=schema
    ).active_version()

    if version is None:
        return ChainDrilldownResponse(
            taxonomy_version="",
            chain=chain,
            layer=layer,
            members=[],
            state="unsupported_capability",
            reason="no active taxonomy version is published",
        )

    where = "m.taxonomy_version = %s AND m.chain = %s AND m.valid_to IS NULL"
    params: list[object] = [engine, version, chain]
    if layer:
        where += " AND m.layer = %s"
        params.append(layer)

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, value
                  FROM {schema}.fundamental_dimensions
                 WHERE engine_version = %s AND dimension = 'priority'
                 ORDER BY ticker, as_of DESC
            )
            SELECT m.ticker, m.layer, m.evidence_class, m.approved_by,
                   e.role, e.direction, e.magnitude, e.magnitude_basis,
                   e.status, e.source_ref, l.value
              FROM {schema}.chain_membership m
              LEFT JOIN {schema}.company_exposure e
                     ON e.taxonomy_version = m.taxonomy_version
                    AND e.chain = m.chain AND e.ticker = m.ticker
                    AND e.valid_to IS NULL
              LEFT JOIN latest l ON l.ticker = m.ticker
             WHERE {where}
             ORDER BY m.layer, m.ticker
            """,
            params,
        )
        rows = cur.fetchall()

    members = [
        ChainMember(
            ticker=t,
            layer=lay,
            evidence_class=ev,
            approved_by=by,
            role=role,
            direction=direction,
            magnitude=float(mag) if mag is not None else None,
            magnitude_basis=basis,
            exposure_status=status,
            source_ref=ref,
            priority=float(pri) if pri is not None else None,
        )
        for t, lay, ev, by, role, direction, mag, basis, status, ref, pri in rows
    ]
    return ChainDrilldownResponse(
        taxonomy_version=version,
        chain=chain,
        layer=layer,
        members=members,
        state="ok" if members else "no_coverage",
        reason=None if members else f"no members in {chain!r} under {version}",
    )
