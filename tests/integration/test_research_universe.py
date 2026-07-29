"""Research cohort storage + the nightly capture job's self-gating.

The cohort exists so the option-surface grid can accrue for tickers that are NOT
on the watchlist (migration 110). The two behaviours worth pinning are that an
unknown cohort reads as empty rather than raising, and that the capture job
therefore spends zero UW calls when nothing is seeded — a default-on flag is only
safe if that holds.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.storage.repository import Repository
from uw_scan.storage.research_universe import ResearchUniverseRepository
from uw_scan.worker.jobs.option_surface_research_capture import (
    option_surface_research_capture,
)

COHORT = "test_cohort_v1"


def _seed(repo: Repository, rows: list[tuple[str, str]]) -> None:
    sql = f"""
        INSERT INTO {repo._schema}.research_universe
               (cohort, ticker, sector, marketcap, option_oi, source, selected_on)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (cohort, ticker) DO NOTHING
    """
    with repo.conn.cursor() as cur:
        for ticker, sector in rows:
            cur.execute(
                sql,
                (
                    COHORT,
                    ticker,
                    sector,
                    1_000_000_000,
                    250_000,
                    "test",
                    date(2026, 7, 29),
                ),
            )
    repo.conn.commit()


def test_unknown_cohort_reads_empty_not_error(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    ru = ResearchUniverseRepository(repo.conn, schema=repo._schema)
    assert ru.list_cohort_tickers("no_such_cohort") == []
    assert ru.list_cohort("no_such_cohort") == []


def test_cohort_round_trips_with_its_tags(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    # Real tickers at their real sectors — CSCO and MRK were both selected into
    # the shipped cohort on 2026-07-29.
    _seed(repo, [("CSCO", "Technology"), ("MRK", "Healthcare")])
    ru = ResearchUniverseRepository(repo.conn, schema=repo._schema)

    assert ru.list_cohort_tickers(COHORT) == ["CSCO", "MRK"]
    rows = ru.list_cohort(COHORT)
    # Ordered by sector, so Healthcare precedes Technology.
    assert [r["ticker"] for r in rows] == ["MRK", "CSCO"]
    assert [r["sector"] for r in rows] == ["Healthcare", "Technology"]
    assert rows[0]["option_oi"] == 250_000


def test_capture_spends_nothing_on_an_unseeded_cohort(
    seeded_db_empty_cards: Repository,
):
    """A default-on flag is only safe if an unseeded cohort is a no-op.

    The client is a sentinel that fails the test if touched at all — asserting
    "returned 0" alone would still pass if the job had burned UW calls first.
    """

    class _ExplodingClient:
        def __getattr__(self, name: str):  # pragma: no cover - must never run
            raise AssertionError(f"UW client used for an empty cohort: .{name}")

    written = option_surface_research_capture(
        repo=seeded_db_empty_cards,
        client=_ExplodingClient(),
        cohort="never_seeded",
        today=date(2026, 7, 29),
    )
    assert written == 0


@pytest.mark.parametrize("cohort", ["", "  "])
def test_blank_cohort_is_also_a_no_op(seeded_db_empty_cards: Repository, cohort: str):
    # A misconfigured OPTION_SURFACE_RESEARCH_COHORT must not fan out to every
    # row in the table; it must match nothing.
    ru = ResearchUniverseRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert ru.list_cohort_tickers(cohort) == []
