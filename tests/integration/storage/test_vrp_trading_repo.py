from datetime import date


def test_candidate_roundtrip(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_candidate(
        ticker="NVDA",
        as_of=date(2026, 6, 22),
        structure="iron_condor",
        spot=120.0,
        iv=0.45,
        vrp_z=1.8,
        hold_days=20,
        short_put=110.0,
        long_put=104.0,
        short_call=130.0,
        long_call=136.0,
        entry_credit=1.8,
        max_loss=4.2,
        put_width=6.0,
        call_width=6.0,
        bucket_sector="Semis",
        bucket_verdict="HARVEST_SELLABLE",
        earnings_clear=True,
        contracts=1,
    )
    repo.conn.commit()
    rows = repo.fetch_vrp_candidates(as_of=date(2026, 6, 22))
    assert rows[0]["ticker"] == "NVDA"
    assert rows[0]["bucket_verdict"] == "HARVEST_SELLABLE"


def test_paper_open_is_idempotent_per_day(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    base = dict(
        ticker="AAPL",
        opened_on=date(2026, 6, 22),
        hold_days=20,
        expiry_on=date(2026, 7, 21),
        short_put=180.0,
        long_put=174.0,
        short_call=200.0,
        long_call=206.0,
        entry_credit=1.5,
        max_loss=4.5,
        contracts=1,
        spot_entry=190.0,
        iv_entry=0.30,
    )
    pid = repo.open_vrp_paper_position(**base)
    repo.conn.commit()
    assert isinstance(pid, int)
    dup = repo.open_vrp_paper_position(**base)  # same (ticker, opened_on)
    repo.conn.commit()
    assert dup is None
    assert len(repo.fetch_open_vrp_paper_positions()) == 1


def test_close_position(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    pid = repo.open_vrp_paper_position(
        ticker="MSFT",
        opened_on=date(2026, 6, 1),
        hold_days=20,
        expiry_on=date(2026, 6, 29),
        short_put=400.0,
        long_put=390.0,
        short_call=450.0,
        long_call=460.0,
        entry_credit=2.0,
        max_loss=8.0,
        contracts=1,
        spot_entry=425.0,
        iv_entry=0.25,
    )
    repo.conn.commit()
    repo.close_vrp_paper_position(
        pid, closed_on=date(2026, 6, 29), exit_value=0.5, realized_pnl=150.0
    )
    repo.conn.commit()
    closed = repo.fetch_vrp_paper_positions(status="closed")
    assert closed[0]["realized_pnl"] == 150.0
    assert not repo.fetch_open_vrp_paper_positions()
