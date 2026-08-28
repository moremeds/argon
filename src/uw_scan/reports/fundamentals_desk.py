"""The fundamentals industry desk's six answers (spec §3, Task 13).

Read-only over the warm store: zero UW, zero IB, zero lake. Every number here
was persisted by a job, so a page read cannot make the surface's cost unbounded
or its answer un-replayable.

Who is on the desk, and what is held per name, lives in
`fundamentals_desk_inputs.py` — this module only SHAPES those inputs into the
six responses. That split is where the taxonomy's extension contract and the
membership-grain dedupe are documented; read it first.

WHY THERE IS NO ORDERING PARAMETER ANYWHERE
---------------------------------------------
The desk LISTS; it never RANKS. Cross-sectional value measured INVERTED in this
universe (`book_to_price` IC -0.0365, t -2.32) while own-history value is the
one measured claim (`sales_to_ev` within-ticker IC +0.0744, t 5.77), and the
cross-sectional composite correlates 0.89 with its own growth input. Every
order here is FIXED and carries no valuation information: read-through order
for the calendar (report_date, then layer_rank), the desk's knowledge clock for
the delta rail (`first_known_at` DESC), and `layer_rank` for chains.

ABSENCE IS THE STATEMENT
--------------------------
A missing figure is null and named, never zero and never carried forward from a
neighbouring period. `coverage_missing` NAMES the tickers because "12/18" is
decoration and "missing: COHR" is actionable; `percentile_state` says WHICH of
six nothings a null percentile is, because `no_compatible_run` (a fact about
Argon) is not `no_coverage` (a claim about a real business).
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.fundamentals.underwriting import underwriting_features
from uw_scan.models.fundamentals_desk import (
    ChainExposureCoverage,
    ChainMetricCell,
    CohortSlice,
    DeltaRailEvent,
    DeltaRailResponse,
    DeskCalendarResponse,
    DeskCalendarRow,
    DeskLimitsResponse,
    DeskMatrixResponse,
    MemberDot,
    MembershipEvidenceCount,
    NodeUnderwritingRow,
    ProfitPoolLayer,
)
from uw_scan.reports.fundamentals_desk_inputs import (
    as_float,
    buckets,
    chain_order,
    cohorts,
    distinct_tickers,
    memberships,
    percentiles,
    require_chain,
)
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.earnings_reactions import EarningsReactionsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_panels import current_statement_panel
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository
from uw_scan.storage.fundamentals_desk import FundamentalsDeskRepository
from uw_scan.storage.implied_move import ImpliedMoveRepository
from uw_scan.storage.research_taxonomy import ResearchTaxonomyRepository

#: The delta rail's classes. `sec_filing` and `statement_published` are BOTH
#: here and are collapsed downstream — see `_collapse_one_filing`.
RAIL_CLASSES = (
    "statement_published",
    "sec_filing",
    "band_entry",
    "band_exit",
    "implied_move_shift",
    "coverage_change",
    "bucket_flip",
)

#: Reactions shown per calendar row. Four because that is what a reader holds
#: in one glance, and because UW's own `last_1d_reactions` is four.
MAX_REACTIONS = 4

#: The three metrics the matrix carries. `valuation_percentile` is special —
#: see `_cell`.
METRICS = ("rev_yoy", "gross_margin", "valuation_percentile")

#: Spec §3f, fixed. Legitimately prose: the reason a number is withheld is not
#: itself a number, and publishing it buys more trust than any number that
#: could be added in its place.
WITHHELD_COMPOSITE = (
    "The internal cross-sectional composite is not shown. It correlates 0.89 "
    "with its own growth input, so ordering names by it would ship a disguised "
    "growth screen under a fundamentals label. The measured record is narrower "
    "than that ordering implies: own-history value works (sales_to_ev, "
    "within-ticker 2q IC +0.0744, t 5.77) while cross-sectional value measured "
    "INVERTED in this same universe (book_to_price IC -0.0365, t -2.32). This "
    "desk therefore lists names; it does not rank them."
)

#: The sign inversion between the two net-income lines — the ONE genuine
#: integrity check on this axis, and separate from the descriptive basis
#: difference beside it. Measured 5 of 28,973 rows.
NI_SIGN_FLIP_CHECK = "net_income_sign_flipped_across_statements"


# --------------------------------------------------------------- calendar


def desk_calendar(
    conn: psycopg.Connection,
    *,
    schema: str,
    section: str,
    domains: Sequence[str],
    chain: str | None = None,
    today: date | None = None,
) -> DeskCalendarResponse:
    """Next prints across the section, upstream to downstream.

    Rows are MEMBERSHIP-grained — the one place on the desk that does not
    dedupe. A print's place in the chain IS the row, so a name in two chains
    appears under each; collapsing it would mean picking a chain for it, which
    is a judgement the desk has no basis to make, and would hide the other
    membership entirely.

    `today` is the desk's clock, injectable so a test can freeze it (the
    `reports/gamma_levels.py` pattern). It is NOT a request parameter and never
    reaches OpenAPI: the calendar is "what prints next", and letting a caller
    move the clock would let it ask a question the surface does not answer.
    Defaulting it here rather than at the call site keeps the router honest —
    the router passes nothing.
    """
    today = today or date.today()
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    # BEFORE the no-version early return, not after: with no active taxonomy
    # no chain exists, so an unknown `?chain=` must still 404 rather than be
    # answered with an empty desk by a shorter route.
    require_chain(conn, schema=schema, version=version, domains=domains, chain=chain)
    if version is None:
        return DeskCalendarResponse(section=section, as_of=today, rows=[])

    members = memberships(
        conn, schema=schema, version=version, domains=domains, chain=chain
    )
    tickers = distinct_tickers(members)
    if not tickers:
        return DeskCalendarResponse(section=section, as_of=today, rows=[])

    # `on_or_after=today` is the floor: a print that has happened is history,
    # and a calendar that showed it would be answering a different question.
    prints = EarningsCalendarRepository(conn, schema=schema).next_prints(
        on_or_after=today, tickers=tickers
    )
    moves = ImpliedMoveRepository(conn, schema=schema).latest_for(tickers)
    reactions = EarningsReactionsRepository(conn, schema=schema).reactions_for(tickers)
    engine = FundamentalScoresRepository(conn, schema=schema).active_version()
    pcts = percentiles(conn, schema=schema, engine=engine, tickers=tickers)

    by_ticker: dict[str, list[dict[str, Any]]] = {}
    for m in members:
        by_ticker.setdefault(m["ticker"], []).append(m)

    rows: list[DeskCalendarRow] = []
    for p in prints:
        # THE IMPLIED MOVE BELONGS TO ONE PRINT, AND ONLY THAT PRINT.
        # `implied_move_snapshot` writes a row only while a print is inside its
        # lookahead window, so for the ~70 days a quarter when a name has no
        # imminent print its NEWEST row is last quarter's — computed for a
        # print that has already happened. Attaching it to the next print
        # renders a stale number as "the market-implied move", which is the
        # carry-forward this module exists to refuse. `report_date` says which
        # print the row is for; if it is not this one, the answer is "not
        # covered".
        move = moves.get(p["ticker"])
        if move is not None and move["report_date"] != p["report_date"]:
            move = None
        pct, state = pcts.get(p["ticker"], (None, "no_coverage"))
        for m in by_ticker.get(p["ticker"], []):
            rows.append(
                DeskCalendarRow(
                    ticker=p["ticker"],
                    report_date=p["report_date"],
                    # NULL session is a real third value, never a guess.
                    session=p["session"],
                    chain=m["chain"],
                    layer=m["layer"],
                    layer_rank=int(m["layer_rank"] or 0),
                    implied_move_pct=(
                        as_float(move["implied_move_pct"]) if move else None
                    ),
                    implied_move_asof=move["market_date"] if move else None,
                    reactions=[
                        float(r["pct_move"])
                        for r in reactions.get(p["ticker"], [])[:MAX_REACTIONS]
                    ],
                    spot_percentile=pct,
                    percentile_state=state,
                )
            )
    # Fixed order: the print date, then how far upstream it sits. `chain` and
    # `ticker` only break ties, so the order is stable and carries no valuation
    # information.
    rows.sort(key=lambda r: (r.report_date, r.layer_rank, r.chain, r.ticker))
    return DeskCalendarResponse(section=section, as_of=today, rows=rows)


# ------------------------------------------------------------- delta rail


def _collapse_one_filing(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One filing, one rail entry.

    `sec_filing` and `statement_published` can both fire for the same print.
    Keep `statement_published` (the richer fact — it carries the period) and
    record the suppressed class in `detail["also"]`, so the rail says the
    filing was seen twice rather than showing the operator the same filing
    twice or silently dropping one of its two sources.
    """
    pairs = {"sec_filing", "statement_published"}
    kept: list[dict[str, Any]] = []
    seen: dict[tuple[str, date], dict[str, Any]] = {}
    for e in events:
        if e["event_class"] not in pairs:
            kept.append(e)
            continue
        key = (e["ticker"], e["occurred_at"])
        prior = seen.get(key)
        if prior is None:
            seen[key] = e
            kept.append(e)
            continue
        winner, loser = (
            (prior, e) if prior["event_class"] == "statement_published" else (e, prior)
        )
        if winner is e:
            kept[kept.index(prior)] = e
            seen[key] = e
        detail = dict(winner.get("detail_jsonb") or {})
        also = sorted({*detail.get("also", []), loser["event_class"]})
        winner["detail_jsonb"] = {**detail, "also": also}
    # RE-SORT, because the collapse moves a date into another event's slot.
    # The winner is substituted into the LOSER's position, and the two do not
    # share a clock: SEC indexing routinely lags statement ingest, so the
    # surviving `statement_published` carries an OLDER `first_known_at` than
    # the `sec_filing` slot it now occupies, and the rail comes out ascending
    # in the middle. Stable, so events sharing a `first_known_at` keep the
    # `event_id DESC` order the query gave them.
    kept.sort(key=lambda e: e["first_known_at"], reverse=True)
    return kept


def delta_rail(
    conn: psycopg.Connection,
    *,
    schema: str,
    domains: Sequence[str],
    since: date,
    limit: int = 200,
) -> DeltaRailResponse:
    """What changed since `since`, on the desk's KNOWLEDGE clock."""
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    if version is None:
        return DeltaRailResponse(since=since, events=[])
    tickers = distinct_tickers(
        memberships(conn, schema=schema, version=version, domains=domains)
    )
    if not tickers:
        return DeltaRailResponse(since=since, events=[])

    with conn.cursor() as cur:
        # Predicates on `first_known_at`, never `occurred_at`: "what changed"
        # is a question about when ARGON learned something. Filtering on when
        # it happened would drop a filing Argon only saw last night.
        cur.execute(
            f"""SELECT event_class, ticker, occurred_at, first_known_at, title,
                       detail_jsonb
                  FROM {schema}.research_events
                 WHERE ticker = ANY(%s) AND event_class = ANY(%s)
                   AND first_known_at >= %s AND superseded_by IS NULL
                 ORDER BY first_known_at DESC, event_id DESC
                 LIMIT %s""",
            (tickers, list(RAIL_CLASSES), since, limit),
        )
        cols = [d.name for d in cur.description]
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    return DeltaRailResponse(
        since=since,
        events=[
            DeltaRailEvent(
                event_class=e["event_class"],
                ticker=e["ticker"],
                occurred_at=e["occurred_at"],
                first_known_at=e["first_known_at"],
                title=e["title"],
                detail=e.get("detail_jsonb") or {},
            )
            for e in _collapse_one_filing(rows)
        ],
    )


# ------------------------------------------------------------------ matrix


def _dots(
    metric: str,
    tickers: Sequence[str],
    rollups: dict[str, dict[str, Any]],
    pcts: dict[str, tuple[float | None, str]],
) -> list[MemberDot]:
    """One dot per DISTINCT ticker. Never weighted, never dropped for being
    null — a name with no figure is a dot with `value=None` and a state that
    says which kind of nothing it is."""
    dots: list[MemberDot] = []
    for ticker in tickers:
        if metric == "valuation_percentile":
            pct, state = pcts.get(ticker, (None, "no_coverage"))
            # A percentile is not a filed figure, so it has no knowledge date
            # to be honest or dishonest about — null, which is not `False`.
            dots.append(
                MemberDot(
                    ticker=ticker,
                    value=pct,
                    state=state,
                    knowledge_date_estimated=None,
                )
            )
            continue
        row = rollups.get(ticker)
        if row is None:
            dots.append(
                MemberDot(
                    ticker=ticker,
                    value=None,
                    state="no_compatible_run",
                    knowledge_date_estimated=None,
                )
            )
            continue
        dots.append(
            MemberDot(
                ticker=ticker,
                value=as_float(row[metric]),
                # A rollup row exists; a null metric within it means an
                # integrity check fired on the field it consumes. The row WAS
                # computed, so the state is `ok` and the null is the answer.
                state="ok",
                # Inverts the stored column deliberately: `knowledge_date_known`
                # True means a real filing date, so `estimated` is its negation.
                # The estimate errs EARLY for late filers and manufactures
                # look-ahead — carried so a consumer can see it, never filtered
                # on here.
                knowledge_date_estimated=not row["knowledge_date_known"],
            )
        )
    return dots


def _cell(
    chain: str,
    metric: str,
    dots: list[MemberDot],
    slices: list[CohortSlice],
    members_total: int,
) -> ChainMetricCell:
    values = [d.value for d in dots if d.value is not None]
    median: float | None = None
    if metric != "valuation_percentile" and values:
        # UNWEIGHTED, always. A revenue-weighted chain margin is the largest
        # member's margin wearing the chain's label — measured as actively
        # misleading, and banned. And `valuation_percentile` gets NO median at
        # all: own-history percentiles are NAME facts, so any aggregate over
        # them is the banned "chain percentile distribution" (spec §3).
        median = statistics.median(values)
    return ChainMetricCell(
        chain=chain,
        metric=metric,
        median=median,
        dots=dots,
        cohorts=slices,
        coverage_missing=[d.ticker for d in dots if d.value is None],
        members_total=members_total,
    )


def _matrix_inputs(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str]
) -> tuple[list[dict[str, Any]], dict, dict, dict]:
    """`(memberships, rollups, percentiles, buckets)` — the matrix and the
    profit pool read the same four things, so they resolve them the same way."""
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    if version is None:
        return ([], {}, {}, {})
    members = memberships(conn, schema=schema, version=version, domains=domains)
    tickers = distinct_tickers(members)
    engine = FundamentalScoresRepository(conn, schema=schema).active_version()
    return (
        members,
        FundamentalsDeskRepository(conn, schema=schema).latest_per_ticker(tickers),
        percentiles(conn, schema=schema, engine=engine, tickers=tickers),
        buckets(conn, schema=schema, engine=engine, tickers=tickers),
    )


def _group_by_chain(members: Sequence[dict[str, Any]]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for m in members:
        grouped.setdefault(m["chain"], []).append(m)
    return grouped


def desk_matrix(
    conn: psycopg.Connection, *, schema: str, section: str, domains: Sequence[str]
) -> DeskMatrixResponse:
    """chain × metric, one dot per DISTINCT ticker, medians unweighted."""
    members, rollups, pcts, by_bucket = _matrix_inputs(
        conn, schema=schema, domains=domains
    )
    chains = chain_order(members)
    by_chain = _group_by_chain(members)

    cells: list[ChainMetricCell] = []
    for chain in chains:
        tickers = distinct_tickers(by_chain[chain])
        slices = cohorts(by_bucket, tickers)
        for metric in METRICS:
            cells.append(
                _cell(
                    chain,
                    metric,
                    _dots(metric, tickers, rollups, pcts),
                    slices,
                    len(tickers),
                )
            )
    return DeskMatrixResponse(section=section, chains=chains, cells=cells)


# ------------------------------------------------------------- profit pool


def profit_pool(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str]
) -> list[ProfitPoolLayer]:
    """Where gross profit sits, layer by layer — side by side, no arrows.

    The hyperscaler-capex -> supplier-revenue timing edge was tested and did
    not validate (headline 0.59 collapsing to 0.25 matched-growth), so this may
    not be read as propagation, and `ProfitPoolLayer` carries no field that
    would let it be rendered as one.
    """
    members, rollups, _pcts, _by_bucket = _matrix_inputs(
        conn, schema=schema, domains=domains
    )
    by_chain = _group_by_chain(members)

    layers: list[ProfitPoolLayer] = []
    for chain in chain_order(members):
        rows = by_chain[chain]
        tickers = distinct_tickers(rows)
        present = [t for t in tickers if t in rollups]
        margins = [
            as_float(rollups[t]["gross_margin"])
            for t in present
            if rollups[t]["gross_margin"] is not None
        ]
        yoys = [
            as_float(rollups[t]["rev_yoy"])
            for t in present
            if rollups[t]["rev_yoy"] is not None
        ]
        layers.append(
            ProfitPoolLayer(
                chain=chain,
                layer_rank=min(int(r["layer_rank"] or 0) for r in rows),
                median_gross_margin=statistics.median(margins) if margins else None,
                median_rev_yoy=statistics.median(yoys) if yoys else None,
                dots=_dots("gross_margin", tickers, rollups, {}),
            )
        )
    return layers


# ------------------------------------------------------------------ limits


def desk_limits(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str]
) -> DeskLimitsResponse:
    """What the desk cannot say, as numbers (spec §3f: computed, not prose).

    The NI split is DESCRIPTIVE. Income-statement `net_income` is
    attributable-to-parent post-discontinued-ops while the cash-flow statement
    opens from consolidated NI including NCI (ASC 230 indirect), so a
    disagreement is usually correct accounting on BOTH sides — measured on 342
    of 419 tickers. Argon stores no NCI field and cannot attribute it, which is
    exactly why it must never be rendered as an integrity failure. The
    sign-flip count beside it IS a violation, and is kept separate for that
    reason.
    """
    obs = FundamentalObsRepository(conn, schema=schema)
    tax = ResearchTaxonomyRepository(conn, schema=schema)
    version = tax.active_version()

    members: list[dict[str, Any]] = []
    if version is not None:
        members = memberships(conn, schema=schema, version=version, domains=domains)
    # SCOPED TO THE SECTION, like every other number in this response. An
    # unscoped scan would name VZ and GE under a header reading "AI/Semi —
    # what this desk cannot say": true of the universe, false of this desk, and
    # nothing on the card would mark the change of population. A section with
    # no members asks about no tickers and gets zeroes, which is the honest
    # answer rather than the universe's.
    ni = obs.net_income_basis_summary(tickers=distinct_tickers(members))

    evidence: list[MembershipEvidenceCount] = []
    coverage: list[ChainExposureCoverage] = []
    if version is not None:
        counts: dict[str, int] = {}
        for m in members:
            counts[m["evidence_class"]] = counts.get(m["evidence_class"], 0) + 1
        evidence = [
            MembershipEvidenceCount(evidence_class=cls, memberships=n)
            for cls, n in sorted(counts.items())
        ]
        section_chains = {m["chain"] for m in members}
        coverage = [
            ChainExposureCoverage(chain=chain, **row)
            for chain, row in sorted(tax.exposure_coverage(version).items())
            if chain in section_chains
        ]

    return DeskLimitsResponse(
        ni_basis_agree=ni["agree"],
        ni_basis_differ=ni["differ"],
        ni_largest_basis_differences=[r["ticker"] for r in ni["by_ticker"]],
        ni_sign_flip_violations=obs.violation_count(NI_SIGN_FLIP_CHECK),
        withheld_composite=WITHHELD_COMPOSITE,
        membership_evidence=evidence,
        exposure_coverage=coverage,
    )


# ------------------------------------------------------------ underwriting


def _raw(panel: dict[str, Any], key: str, period: str, field: str) -> str | None:
    """The filed line item, VERBATIM. Not reformatted and not coerced — the
    point of showing it is that the reader can check the derived figure against
    exactly what the provider served."""
    value = (panel[key].get(period) or {}).get(field)
    return None if value is None else str(value)


def node_underwriting(
    conn: psycopg.Connection, *, schema: str, domains: Sequence[str], chain: str
) -> list[NodeUnderwritingRow]:
    """DIO, SBC/revenue, and share-count change for one chain's members, each
    beside the filed line items it was derived from (spec §4 trust
    requirement #1: the raw values and the filing date travel WITH the figure,
    not behind another request).

    Computed per request over the chain's members (measured at <=20 names per
    chain): the payloads are already in the warm store, and caching them would
    be a second place for the as-of to disagree with itself.

    A member with no statements produces NO row. That is not a silent drop —
    the matrix's `coverage_missing` names it — but this endpoint's row shape
    requires a period, and inventing one would be worse than omitting it.
    """
    version = ResearchTaxonomyRepository(conn, schema=schema).active_version()
    # Guard BEFORE the no-version early return — see `desk_calendar`.
    require_chain(conn, schema=schema, version=version, domains=domains, chain=chain)
    if version is None:
        return []
    tickers = distinct_tickers(
        memberships(conn, schema=schema, version=version, domains=domains, chain=chain)
    )
    if not tickers:
        return []

    panel = current_statement_panel(conn, tickers=tickers, schema=schema)
    feats = underwriting_features(panel)

    rows: list[NodeUnderwritingRow] = []
    for ticker in tickers:
        periods = feats.get(ticker) or {}
        if not periods:
            continue
        period = max(periods)
        values = periods[period]
        per = panel[ticker]
        filed = per["filing_dates"].get(period)
        rows.append(
            NodeUnderwritingRow(
                ticker=ticker,
                period_end=date.fromisoformat(period),
                dio=values["dio"],
                sbc_to_revenue=values["sbc_to_revenue"],
                # BASIC period-end shares, never "diluted": no diluted share
                # key exists at any tier of the UW store.
                shares_outstanding_yoy=values["shares_outstanding_yoy"],
                filing_published_at=date.fromisoformat(filed) if filed else None,
                inventory_raw=_raw(per, "balance-sheets", period, "inventory"),
                cost_of_revenue_raw=_raw(
                    per, "income-statements", period, "cost_of_revenue"
                ),
                sbc_raw=_raw(per, "cash-flows", period, "stock_based_compensation"),
                shares_outstanding_raw=_raw(
                    per, "balance-sheets", period, "common_stock_shares_outstanding"
                ),
                state="ok",
            )
        )
    return rows
