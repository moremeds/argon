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


def test_atm_iv_comes_from_the_grid_session_not_a_stale_iv_rank_row(
    seeded_db_empty_cards,
):
    """The IV must be pinned to the requested session, never carried forward.

    iv_rank_history covers only 4 tickers per session, so the natural
    `market_date <= as_of ORDER BY DESC` lookup returned a months-old reading
    for 85 of 114 grid tickers on 2026-07-24 — May IV compared against July
    realised vol, with no error and no log line. load_atm_iv reads the grid at
    an exact (market_date, expiry), so a session with no capture returns None
    (a skipped ticker) rather than a stale number that looks fine.
    """
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    # Real IWM 2026-07-24 rows: spot 291.44, nearest strike 291 -> (call+put)/2.
    for strike, call_iv, put_iv in (
        (272.0, 0.286910000244214, 0.251489543772415),
        (291.0, 0.216271148592203, 0.195577289932588),
        (306.0, 0.172509740706994, 0.148603775785557),
    ):
        conn.execute(
            "INSERT INTO uw_scan.option_surface_grid_daily "
            "(ticker, market_date, expiry, strike, call_iv, put_iv, underlying_spot) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            ("IWM", _AS_OF, _EXP, strike, call_iv, put_iv, _SPOT),
        )
    conn.commit()

    # Nearest strike to spot 291.44 is 291 -> (0.216271149 + 0.195577290) / 2.
    assert repo.load_atm_iv("IWM", _AS_OF, _EXP, _SPOT) == pytest.approx(
        0.2059242192623955, rel=1e-12
    )
    # A session with no capture yields None, not a carried-forward value.
    assert repo.load_atm_iv("IWM", date(2026, 7, 23), _EXP, _SPOT) is None
    assert repo.load_atm_iv("NVDA", _AS_OF, _EXP, _SPOT) is None


def _grid_row(conn, ticker, market_date, strike, spot):
    conn.execute(
        "INSERT INTO uw_scan.option_surface_grid_daily "
        "(ticker, market_date, expiry, strike, call_iv, put_iv, underlying_spot) "
        "VALUES (%s,%s,%s,%s,0.2,0.2,%s)",
        (ticker, market_date, _EXP, strike, spot),
    )


def test_load_spot_falls_back_to_the_close_when_the_grid_spot_is_null(
    seeded_db_empty_cards,
):
    """Grid spot first; daily_ohlc close when the column is NULL.

    underlying_spot is 0% populated before 2026-06 on option_wizard. Without the
    fallback every pre-June session returns None and the ticker is skipped.
    """
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    for strike in (272.0, 291.0, 306.0):
        _grid_row(conn, "IWM", _AS_OF, strike, None)
    conn.execute(
        "INSERT INTO uw_scan.daily_ohlc (ticker, date, close, source) "
        "VALUES (%s,%s,%s,'massive.com')",
        ("IWM", _AS_OF, _SPOT),
    )
    conn.commit()

    assert repo.load_spot("IWM", _AS_OF) == pytest.approx(_SPOT)


def test_load_spot_prefers_the_grid_spot_over_the_close(seeded_db_empty_cards):
    """When both exist the grid wins — it is the scale the strikes are quoted on."""
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    for strike in (272.0, 291.0, 306.0):
        _grid_row(conn, "IWM", _AS_OF, strike, 290.0)
    conn.execute(
        "INSERT INTO uw_scan.daily_ohlc (ticker, date, close, source) "
        "VALUES (%s,%s,%s,'massive.com')",
        ("IWM", _AS_OF, _SPOT),
    )
    conn.commit()

    assert repo.load_spot("IWM", _AS_OF) == pytest.approx(290.0)


def test_load_spot_rejects_a_split_adjusted_close_against_unadjusted_strikes(
    seeded_db_empty_cards,
):
    """The adjusted/unadjusted seam must yield None, never a rescaled candidate.

    daily_ohlc is back-adjusted; option_surface_grid_daily is as-traded. After
    KORU's 20-for-1 its close reads ~$21 while its strikes still spanned
    125..1900, so pairing them puts every leg absurdly far OTM and makes the
    greeks meaningless. Measured on option_wizard this affects 174 of 16373
    ticker-sessions across KLAC, KORU and CRWD. A scale-mismatched candidate is
    not a worse row — it is a fabricated one, so it is dropped.
    """
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    for strike in (125.0, 725.0, 1900.0):  # real KORU pre-split strike range
        _grid_row(conn, "KORU", _AS_OF, strike, None)
    conn.execute(  # real back-adjusted KORU close for 2026-07-13
        "INSERT INTO uw_scan.daily_ohlc (ticker, date, close, source) "
        "VALUES (%s,%s,%s,'massive.com')",
        ("KORU", _AS_OF, 20.9595),
    )
    conn.commit()

    assert repo.load_spot("KORU", _AS_OF) is None


def test_atm_iv_resolves_when_the_grid_has_no_underlying_spot(
    seeded_db_empty_cards,
):
    """Pre-2026-06 grid rows carry a NULL underlying_spot; the IV must still resolve.

    This is the regression for the second of the two NULL-spot dependencies.
    While load_atm_iv ordered by `abs(strike - underlying_spot)`, every session
    before 2026-06 matched nothing and the ticker was silently skipped — the
    replay produced zero candidates for five of seven months and looked like an
    absent signal rather than an absent column.
    """
    conn = seeded_db_empty_cards.conn
    repo = ThetaHarvesterRepository(conn, "uw_scan")
    for strike, call_iv, put_iv in (
        (272.0, 0.286910000244214, 0.251489543772415),
        (291.0, 0.216271148592203, 0.195577289932588),
    ):
        conn.execute(
            "INSERT INTO uw_scan.option_surface_grid_daily "
            "(ticker, market_date, expiry, strike, call_iv, put_iv, underlying_spot) "
            "VALUES (%s,%s,%s,%s,%s,%s,NULL)",
            ("IWM", _AS_OF, _EXP, strike, call_iv, put_iv),
        )
    conn.commit()

    assert repo.load_atm_iv("IWM", _AS_OF, _EXP, _SPOT) == pytest.approx(
        0.2059242192623955, rel=1e-12
    )
