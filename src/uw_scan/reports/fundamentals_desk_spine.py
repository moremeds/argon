"""The desk's argument spine: demand, transmission, and the boundary.

`fundamentals_desk.py` answers what the desk HOLDS, chain by chain. This
module answers the three questions that give those holdings an order:

  1. capex  — is the money still coming? The one exogenous input.
  3. cases  — does it transmit? The two chains whose stages are ranked.
  scope     — what is deliberately outside, under its own name.

Read-only over the warm store, like its sibling: zero UW, zero IB, zero lake.

WHY CAPEX HAS A DATA PATH AT ALL, HAVING BEEN DEMOTED ONCE
------------------------------------------------------------
`CapexContextStrip` (removed with this module's arrival) argued that
hyperscaler capex is on every sell-side deck and so cannot be where this
desk's edge comes from, and that building a fetcher for it would re-promote a
figure the spec demoted. That argument was about EDGE and it still holds: the
capex panel is not a signal and nothing downstream is ranked by it.

What changed is the page's structure. Every revenue figure on this desk is
somebody else's capital expenditure, so capex is the only number here not
derived from another number here. It is the PREMISE, and a surface that
answers "does it transmit?" without first establishing "is it still coming?"
is answering question three with question one unasked. The strip's own sign
warning survives verbatim in the web layer: for the names that SPEND it,
rising capex is a cost line arriving as depreciation, not evidence of demand.

THE ONE PLACE DOLLARS ARE SUMMED ACROSS COMPANIES
---------------------------------------------------
Nowhere else on this desk is a currency amount added across names, because
the store holds FILED figures and summing gross profit put the Foundry chain
at roughly $930B a quarter on the strength of TSM and UMC filing in TWD. The
capex panel is the single exception and it is bounded three ways: only USD
filers are in it, the excluded names travel with the answer in
`DeskCapexResponse.excluded`, and a quarter missing any panel member's
revenue reports a null intensity rather than a partial ratio.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.models.fundamentals_desk import (
    CapexQuarter,
    CaseStage,
    CaseStageMember,
    DeskCapexResponse,
    DeskCase,
    ScopeGroup,
)
from uw_scan.reports.fundamentals_desk_inputs import (
    as_float,
    distinct_tickers,
    memberships,
    percentiles,
)
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.fundamentals_desk import FundamentalsDeskRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

#: The chain the capex panel is drawn from. A chain name rather than a ticker
#: list so that adding a hyperscaler is a taxonomy row, not a code change.
CAPEX_CHAIN = "Cloud/Hyperscaler"

#: How far back the panel reaches. Three-plus years, so the intensity line has
#: a pre-buildout base to be read against — a two-quarter window would show a
#: level and no decision.
CAPEX_SINCE = date(2023, 1, 1)

#: Case identity: URL slug and display label per research domain. A domain
#: with ranked stages but no entry here still becomes a case, under its own
#: domain name — the registry names cases, it does not gate them.
CASE_IDENTITY: dict[str, tuple[str, str]] = {
    "optical_communication": ("optical", "Optical interconnect"),
    "dc_buildout": ("datacenter", "Datacenter buildout"),
}


def _num(text: str | None) -> float | None:
    """Filed text -> FINITE float, or None.

    The store holds what the provider served and a bad string must cost one
    datapoint, not the request. `float()` alone is not that check: it accepts
    ``"NaN"`` and ``"Infinity"``, and either one poisons every sum and median
    it reaches before failing at JSON serialization as a 500 — turning one
    malformed cell into a dead endpoint. A non-finite filed value is a missing
    value, which is what this returns.
    """
    if text is None:
        return None
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _calendar_quarter(period_end: date) -> str:
    """The CALENDAR quarter containing a fiscal period's end date. The
    approximation that lets a May-ending filer sit beside a June-ending one."""
    return f"{period_end.year}Q{(period_end.month - 1) // 3 + 1}"


def _bucket(
    rows: Sequence[tuple[str, date, str]],
) -> dict[str, dict[str, float]]:
    """`[(ticker, period_end, filed_text)]` -> `{quarter: {ticker: value}}`."""
    acc: dict[str, dict[str, float]] = {}
    for ticker, period_end, text in rows:
        value = _num(text)
        if value is None:
            continue
        acc.setdefault(_calendar_quarter(period_end), {})[ticker] = value
    return acc


def desk_capex(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str]
) -> DeskCapexResponse:
    """Quarterly capital expenditure for the section's customer panel."""
    desk = FundamentalsDeskRepository(conn, schema=schema)
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    members: list[dict[str, Any]] = []
    if version is not None:
        members = memberships(
            conn, schema=schema, version=version, domains=domains, chain=CAPEX_CHAIN
        )
    panel = distinct_tickers(members)

    non_usd = desk.non_usd_currencies(panel)
    included = [t for t in panel if t not in non_usd]
    excluded = {t: non_usd[t][0] for t in panel if t in non_usd}
    if not included:
        # An empty panel is an unanswerable question, not an answer of zero.
        # The web layer says so; it must never render as a flat capex line.
        return DeskCapexResponse(
            chain=CAPEX_CHAIN, included=[], excluded=excluded, quarters=[]
        )

    capex = _bucket(
        desk.quarterly_line_item(
            included,
            statement="cash_flow",
            field="capital_expenditures",
            since=CAPEX_SINCE,
        )
    )
    revenue = _bucket(
        desk.quarterly_line_item(
            included,
            statement="income",
            field="total_revenue",
            since=CAPEX_SINCE,
        )
    )

    quarters: list[CapexQuarter] = []
    for quarter in sorted(capex):
        filed = sorted(capex[quarter])
        rev_q = revenue.get(quarter, {})
        quarters.append(
            CapexQuarter(
                quarter=quarter,
                capex_usd=sum(capex[quarter].values()),
                # All-or-nothing: a five-name numerator over a four-name
                # denominator is not an intensity.
                revenue_usd=(
                    sum(rev_q[t] for t in filed)
                    if all(t in rev_q for t in filed)
                    else None
                ),
                tickers=filed,
                complete=filed == included,
            )
        )
    return DeskCapexResponse(
        chain=CAPEX_CHAIN, included=included, excluded=excluded, quarters=quarters
    )


def desk_cases(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str]
) -> list[DeskCase]:
    """The section's chains whose stages carry an explicit order.

    A domain qualifies by having `layer_rank > 0` rows and by nothing else.
    That is the whole gate: where the taxonomy ranks stages, a dollar's path
    is structure and can be drawn; where it does not, drawing one would invent
    the edges the chain map deliberately refuses to draw.
    """
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    if version is None:
        return []
    rows = [
        r
        for r in memberships(conn, schema=schema, version=version, domains=domains)
        if int(r["layer_rank"] or 0) > 0
    ]
    if not rows:
        return []

    desk = FundamentalsDeskRepository(conn, schema=schema)
    engine = FundamentalScoresRepository(conn, schema=schema).active_version()
    tickers = distinct_tickers(rows)
    rollups = desk.latest_per_ticker(tickers)
    non_usd = desk.non_usd_currencies(tickers)
    pcts = percentiles(conn, schema=schema, engine=engine, tickers=tickers)

    by_domain: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for row in rows:
        by_domain.setdefault(row["domain"], {}).setdefault(row["layer"], []).append(row)

    cases: list[DeskCase] = []
    for domain in sorted(by_domain):
        slug, label = CASE_IDENTITY.get(domain, (domain, domain))
        stages: list[CaseStage] = []
        for layer, layer_rows in by_domain[domain].items():
            members = [
                CaseStageMember(
                    ticker=ticker,
                    rev_yoy=as_float((rollups.get(ticker) or {}).get("rev_yoy")),
                    gross_margin=as_float(
                        (rollups.get(ticker) or {}).get("gross_margin")
                    ),
                    spot_percentile=pcts.get(ticker, (None, ""))[0],
                    reported_currency=(non_usd.get(ticker) or [None])[0],
                )
                for ticker in distinct_tickers(layer_rows)
            ]
            yoys = [m.rev_yoy for m in members if m.rev_yoy is not None]
            gms = [m.gross_margin for m in members if m.gross_margin is not None]
            stages.append(
                CaseStage(
                    layer=layer,
                    chain=sorted({r["chain"] for r in layer_rows})[0],
                    rank=min(int(r["layer_rank"]) for r in layer_rows),
                    members=members,
                    # UNWEIGHTED, and over reporting members only. `reporting`
                    # prints beside it so the median never stands alone.
                    median_rev_yoy=statistics.median(yoys) if yoys else None,
                    median_gross_margin=statistics.median(gms) if gms else None,
                    reporting=len(yoys),
                    total=len(members),
                )
            )
        stages.sort(key=lambda s: (s.rank, s.layer))
        cases.append(DeskCase(domain=domain, slug=slug, label=label, stages=stages))
    return cases


def desk_scope(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str]
) -> list[ScopeGroup]:
    """The taxonomy groups outside this section, under their own names."""
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    if version is None:
        return []
    return [
        ScopeGroup(**row)
        for row in FundamentalsDeskRepository(
            conn, schema=schema
        ).chains_outside_domains(version=version, domains=domains)
    ]
