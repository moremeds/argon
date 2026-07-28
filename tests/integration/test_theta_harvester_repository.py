"""Repository round-trip against a real Postgres schema (pytest-postgresql)."""

from datetime import date

import pytest

from uw_scan.scanners.theta_harvester import (
    DealerSupport,
    OptionLeg,
    build_candidate,
    select_short_strangle,
)
from uw_scan.storage.theta_harvester_repository import ThetaHarvesterRepository

# Frozen real capture — IWM, 2026-07-24, expiry 2026-08-21. Same provenance as
# the Task 3 unit fixtures; see the header comment there for the source query.
_AS_OF = date(2026, 7, 24)
_EXP = date(2026, 8, 21)
_SPOT = 291.44


def _candidate(ticker="IWM", score_spot=_SPOT):
    # Legs are LONG-convention (theta <= 0, gamma >= 0), matching
    # option_surface_grid_daily. select_short_strangle does the negation, so
    # the fixture never hand-writes position signs — see Task 3.
    put = OptionLeg(
        _EXP,
        272.0,
        "P",
        0.251489543772415,
        -0.154573982720319,
        -0.0861128240264245,
        0.0117240381034907,
        0.191878725809937,
    )
    call = OptionLeg(
        _EXP,
        306.0,
        "C",
        0.172509740706994,
        0.156401472783266,
        -0.0595290822132382,
        0.0172246813925854,
        0.193372401778545,
    )
    structure = select_short_strangle([put, call], spot=_SPOT, as_of=_AS_OF)
    assert structure is not None and structure.theta > 0
    return build_candidate(
        ticker=ticker,
        as_of=_AS_OF,
        structure=structure,
        spot=score_spot,
        iv=0.208,
        hv20=0.1107879091536324,
        hv60=0.18596313086572983,
        trend_20d_pct=-1.8605278236543121,
        range_score=0.5346021068062862,
        dealer=DealerSupport("SUPPORT", 5.0e8, 280.0),
    )


def test_upsert_then_read_round_trips_every_persisted_field(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    assert repo.upsert_candidates([_candidate()]) == 1

    rows = repo.read_candidates(as_of=_AS_OF)
    assert len(rows) == 1
    row = rows[0]
    assert row["ticker"] == "IWM"
    assert row["verdict"] == "THETA_HARVEST"
    assert float(row["put_strike"]) == 272.0
    assert float(row["call_strike"]) == 306.0
    assert row["gate_dealer_support"] is True
    assert row["credit_ib"] is None
    assert float(row["entry_credit_theo"]) == pytest.approx(
        float(row["put_mark"]) + float(row["call_mark"])
    )


def test_upsert_is_idempotent_on_ticker_and_as_of(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    repo.upsert_candidates([_candidate()])
    repo.upsert_candidates([_candidate(score_spot=292.55)])
    rows = repo.read_candidates(as_of=_AS_OF)
    assert len(rows) == 1
    assert float(rows[0]["underlying_spot"]) == 292.55


def test_set_ib_credit_populates_only_the_quote_columns(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    repo.upsert_candidates([_candidate()])
    before = repo.read_candidates(as_of=_AS_OF)[0]

    repo.set_ib_credit("IWM", _AS_OF, credit=4.15, source="xenon_ib")
    after = repo.read_candidates(as_of=_AS_OF)[0]

    assert float(after["credit_ib"]) == pytest.approx(4.15)
    assert after["credit_source"] == "xenon_ib"
    assert after["credit_quoted_at"] is not None
    # The markout basis must be untouched by a live quote.
    assert after["entry_credit_theo"] == before["entry_credit_theo"]


def test_identity_change_purges_stale_markouts(seeded_db_empty_cards):
    """A rescan that picks a DIFFERENT structure must not inherit the old
    structure's P&L. Silent inheritance is worse than a missing markout: the
    numbers look valid and describe a trade that was never selected."""
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    repo.upsert_candidates([_candidate()])
    conn.execute(
        "INSERT INTO uw_scan.theta_harvester_markouts "
        "(ticker, as_of, horizon_days, mark_date, pnl) VALUES (%s,%s,%s,%s,%s)",
        ("IWM", _AS_OF, 7, date(2026, 7, 31), 1.25),
    )
    conn.commit()
    assert _markout_count(conn) == 1

    # Same (ticker, as_of), different call strike -> identity changed.
    moved = _candidate()
    moved_call = OptionLeg(
        _EXP,
        307.0,
        "C",
        0.172509740706994,
        0.156401472783266,
        -0.0595290822132382,
        0.0172246813925854,
        0.193372401778545,
    )
    structure = select_short_strangle(
        [moved.structure.put, moved_call], spot=_SPOT, as_of=_AS_OF
    )
    assert structure is not None
    repo.upsert_candidates([_replace_structure(moved, structure)])

    assert _markout_count(conn) == 0
    assert float(repo.read_candidates(as_of=_AS_OF)[0]["call_strike"]) == 307.0


def test_identical_rescan_keeps_existing_markouts(seeded_db_empty_cards):
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    repo.upsert_candidates([_candidate()])
    conn.execute(
        "INSERT INTO uw_scan.theta_harvester_markouts "
        "(ticker, as_of, horizon_days, mark_date, pnl) VALUES (%s,%s,%s,%s,%s)",
        ("IWM", _AS_OF, 7, date(2026, 7, 31), 1.25),
    )
    conn.commit()

    repo.upsert_candidates([_candidate(score_spot=292.55)])
    assert _markout_count(conn) == 1


def test_read_candidates_orders_by_score_descending(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    repo.upsert_candidates([_candidate(ticker="QQQ"), _candidate(ticker="IWM")])
    rows = repo.read_candidates(as_of=_AS_OF)
    scores = [float(r["score"]) for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_latest_as_of_returns_none_on_empty_table(seeded_db_empty_cards):
    repo = ThetaHarvesterRepository(seeded_db_empty_cards.conn, "uw_scan")
    assert repo.latest_as_of() is None


def _markout_count(conn) -> int:
    return conn.execute(
        "SELECT count(*) FROM uw_scan.theta_harvester_markouts"
    ).fetchone()[0]


def _replace_structure(candidate, structure):
    import dataclasses

    return dataclasses.replace(candidate, structure=structure)
