"""Who is on the desk, and what is known about each name (Task 13).

Split out of `reports/fundamentals_desk.py` when that module passed the repo's
<500-line target. The seam is a real one, not a technical layering: this
module answers "which names does this section contain, and what does Argon
hold for each" — a question about the TAXONOMY and the per-name stores — while
`fundamentals_desk.py` shapes those answers into the desk's six responses. All
six assemblers read from here; none of them re-derives membership.

THE TAXONOMY IS THE ONLY EXTENSION POINT
------------------------------------------
Every ticker set is resolved from `research_chains` × `chain_membership` at
request time. A NEW chain — or a new section — is therefore taxonomy ROWS,
never a code change: no constant to append, no assembler branch, no route.
That is spec §2's extension contract, and
`test_rows_only_chain_reaches_both_endpoints` is the test that would catch it
being broken.

TWO GRAINS, AND CONFUSING THEM IS THE RECURRING BUG
-----------------------------------------------------
`chain_membership` is grained `(chain, layer, ticker)`. A name in two layers is
TWO rows. Anything counted or aggregated per name dedupes to DISTINCT tickers
first (`distinct_tickers`) or the numerator outruns its own denominator. The
calendar is the deliberate exception — see that assembler.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg

from uw_scan.models.fundamentals_desk import CohortSlice


class UnknownChain(LookupError):
    """A `?chain=` that does not exist on this desk.

    Its own type rather than an empty result, for the reason the section 404
    already gives: an empty desk is a claim that the thing exists and has
    nothing in it, which is a different and false statement. A typo in a link
    would otherwise render as a real, empty node.
    """


def require_chain(
    conn: psycopg.Connection,
    *,
    schema: str,
    version: str | None,
    domains: Sequence[str],
    chain: str | None,
) -> None:
    """Raise `UnknownChain` unless `chain` exists in one of these domains.

    Scoped to the SECTION's domains, not to the taxonomy at large: asking the
    ai-semi desk for `Banks` is asking for something that does not exist THERE,
    and answering `200 []` would say the AI/semi desk contains an empty Banks
    node. A chain that does exist here and genuinely holds no rows still
    answers `200 []` — *exists but empty* is a real and different answer from
    *does not exist*.

    `version=None` (no active taxonomy) means NO chain exists, so every named
    chain is unknown. Callers must run this BEFORE their own no-version early
    return, or the un-taxonomied desk answers `200 []` to a typo — the same
    false claim this function exists to refuse, reached by a different route.
    """
    if chain is None:
        return
    if version is None:
        raise UnknownChain(chain)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT 1 FROM {schema}.research_chains
                 WHERE taxonomy_version = %s AND domain = ANY(%s) AND chain = %s
                 LIMIT 1""",
            (version, list(domains), chain),
        )
        if cur.fetchone() is None:
            raise UnknownChain(chain)


def as_float(value: Any) -> float | None:
    """`Decimal`/`None` -> `float`/`None`. Never a 0.0 default: a null here is
    "Argon does not have this", and defaulting it would put a name with no
    data at whatever the reader takes zero to mean."""
    return None if value is None else float(value)


def memberships(
    conn: psycopg.Connection,
    *,
    schema: str,
    version: str,
    domains: Sequence[str],
    chain: str | None = None,
) -> list[dict[str, Any]]:
    """Open memberships in the section's domains, at MEMBERSHIP grain.

    `valid_to IS NULL` is what "open" means — a closed interval is history, and
    a desk that read it would show a name in a chain it has left.

    The `domain` filter only DISCRIMINATES because Task 19 gave chains a real
    per-chain domain map. Before it every chain carried `ai_infrastructure` and
    a section tuple selected all 38, putting Banks and Sector-ETF on the
    AI/semi desk.
    """
    where = "c.taxonomy_version = %s AND c.domain = ANY(%s)"
    params: list[Any] = [version, list(domains)]
    if chain is not None:
        where += " AND c.chain = %s"
        params.append(chain)
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT c.chain, c.layer, c.layer_rank, m.ticker, m.evidence_class
                  FROM {schema}.research_chains c
                  JOIN {schema}.chain_membership m
                    ON m.taxonomy_version = c.taxonomy_version
                   AND m.chain = c.chain AND m.layer = c.layer
                   AND m.valid_to IS NULL
                 WHERE {where}
                 ORDER BY c.chain, c.layer_rank, m.ticker""",
            params,
        )
        cols = [d.name for d in cur.description]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


def distinct_tickers(rows: Sequence[dict[str, Any]]) -> list[str]:
    """DISTINCT tickers, alphabetical. The dedupe that keeps a name in two
    layers from counting twice."""
    return sorted({r["ticker"] for r in rows})


def chain_order(rows: Sequence[dict[str, Any]]) -> list[str]:
    """Chains ordered by their MINIMUM `layer_rank`, ties alphabetically.

    Never by a metric — an ordering that moved with the numbers would be the
    cross-sectional ranking this desk exists not to make. Minimum rather than
    any other summary because a chain's place in the read-through order is
    where it FIRST appears, upstream.
    """
    lowest: dict[str, int] = {}
    for r in rows:
        rank = int(r["layer_rank"] or 0)
        lowest[r["chain"]] = min(lowest.get(r["chain"], rank), rank)
    return sorted(lowest, key=lambda c: (lowest[c], c))


def percentiles(
    conn: psycopg.Connection, *, schema: str, engine: str | None, tickers: Sequence[str]
) -> dict[str, tuple[float | None, str]]:
    """Per ticker: `(own-history percentile, the state explaining a null)`.

    `spot_percentile` is a YIELD percentile — 0.80 means CHEAP against this
    name's OWN history. It is never a cross-sectional rank and must never
    become an ordering key: cross-sectional value measured INVERTED in this
    universe.

    Four different nothings, and collapsing them is how "the job never ran"
    gets read as "this company has no fundamentals":

    - no active engine           -> `unsupported_capability` for everyone
    - a band row with a value    -> `ok`
    - a band row, no value       -> `unsupported_capability`: the method
      REFUSED to price this name (its own range was too wide), which is a
      capability statement, not a missing run
    - no band row, statements    -> `no_compatible_run`
    - no band row, no statements -> `no_coverage`
    """
    if not tickers:
        return {}
    names = [t.upper() for t in tickers]
    if engine is None:
        return {t: (None, "unsupported_capability") for t in names}

    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT ON (ticker) ticker, spot_percentile
                  FROM {schema}.valuation_anchors
                 WHERE engine_version = %s AND ticker = ANY(%s)
                 ORDER BY ticker, as_of DESC, result_id DESC""",
            (engine, names),
        )
        banded = dict(cur.fetchall())
        cur.execute(
            f"""SELECT DISTINCT ticker FROM {schema}.fundamental_statement_obs
                 WHERE ticker = ANY(%s)""",
            (names,),
        )
        with_statements = {r[0] for r in cur.fetchall()}

    out: dict[str, tuple[float | None, str]] = {}
    for ticker in names:
        if ticker in banded:
            pct = banded[ticker]
            out[ticker] = (
                (float(pct), "ok")
                if pct is not None
                else (None, "unsupported_capability")
            )
        elif ticker in with_statements:
            out[ticker] = (None, "no_compatible_run")
        else:
            out[ticker] = (None, "no_coverage")
    return out


def buckets(
    conn: psycopg.Connection, *, schema: str, engine: str | None, tickers: Sequence[str]
) -> dict[str, date]:
    """Per ticker: the newest cross-section bucket it sits in.

    `fundamental_scores.as_of` is a peer-group IDENTIFIER, not a freshness
    stamp — two names on different `as_of` values were never compared with each
    other, which is what makes the cohort split necessary rather than cosmetic.
    """
    if not tickers or engine is None:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT ON (ticker) ticker, as_of
                  FROM {schema}.fundamental_scores
                 WHERE engine_version = %s AND ticker = ANY(%s)
                 ORDER BY ticker, as_of DESC, result_id DESC""",
            (engine, [t.upper() for t in tickers]),
        )
        return dict(cur.fetchall())


def cohorts(by_ticker: dict[str, date], tickers: Sequence[str]) -> list[CohortSlice]:
    """Newest bucket = 'reported'; every older one = 'awaiting'.

    A name with no score is in NO cohort: it has not entered any cross section,
    and inventing one for it would place it in a peer group it was never
    measured against. A chain whose members all share one bucket gets ONE
    slice — a second, empty one would render as a straddle that is not
    happening.
    """
    present = {t: by_ticker[t] for t in tickers if t in by_ticker}
    if not present:
        return []
    grouped: dict[date, list[str]] = {}
    for ticker, as_of in present.items():
        grouped.setdefault(as_of, []).append(ticker)
    newest = max(grouped)
    return [
        CohortSlice(
            as_of=as_of,
            label="reported" if as_of == newest else "awaiting",
            tickers=sorted(grouped[as_of]),
        )
        for as_of in sorted(grouped, reverse=True)
    ]
