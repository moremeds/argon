"""/stock/{ticker}/fundamentals assembly (moved from ``api/routers/stock.py``, I-39).

The router parses the params and maps the two lookup failures to HTTP codes;
this module reads the three fundamental repositories and builds the card.
"""

from __future__ import annotations

from typing import Any

import psycopg

from uw_scan.fundamentals.card import build_card, build_history, build_percentiles
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository


class NoActiveMethod(LookupError):
    """No fundamental method version is active (a stack-wide condition)."""


class NoScore(LookupError):
    """The active method has no score row for this ticker."""


def assemble_fundamental_card(
    conn: psycopg.Connection, schema: str, ticker: str, *, quarters: int
) -> dict[str, Any]:
    """The card payload for one name; raises NoActiveMethod or NoScore."""
    scores = FundamentalScoresRepository(conn, schema=schema)
    engine = scores.active_version()
    if engine is None:
        raise NoActiveMethod
    row = scores.latest_for_ticker(ticker, engine)
    if row is None:
        raise NoScore(ticker)
    obs = FundamentalObsRepository(conn, schema=schema)
    violated = obs.violated_fields(row.get("source_obs_ids") or [])

    series = scores.series_for_ticker(ticker, engine, limit=quarters)
    cross = scores.cross_section(row["as_of"], engine)
    # One violation query covering the trajectory AND the comparison panel. Per
    # row it would be ~290 round-trips for a single card.
    obs_ids = sorted(
        {i for r in (*series, *cross) for i in (r.get("source_obs_ids") or [])}
    )
    by_obs = obs.violations_by_obs(obs_ids)

    # Scoped to the SAME engine_version as the subscores. A band computed under a
    # retired method rendering beside live subscores would look current, with
    # nothing on screen to say the two came from different methods.
    anchors = FundamentalAnchorsRepository(conn, schema=schema).latest_for_ticker(
        ticker, engine
    )

    return build_card(
        ticker=ticker,
        row=row,
        violated=violated,
        engine_version=engine,
        history=build_history(series, by_obs),
        percentiles=build_percentiles(cross, by_obs, ticker),
        anchors=anchors,
    )
