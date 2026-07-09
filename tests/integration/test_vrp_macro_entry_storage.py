from datetime import date, datetime, timezone

from uw_scan.storage.repository import Repository


def _min_entry_kwargs(**over):
    kw = dict(
        name="SPX",
        birth_date=date(2026, 6, 24),
        born_at=datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc),
        origin="auto",
        expiry=date(2026, 8, 7),
        hold_days=30,
        spot_at_birth=6000,
        iv_at_birth=0.16,
        vrp_z_at_birth=0.6,
        weight_at_birth=1.0,
        action_at_birth="TRADE",
        short_delta=0.25,
        wing_delta=0.125,
        short_above=5800,
        short_below=5790,
        wing_above=5600,
        wing_below=5590,
    )
    kw.update(over)
    return kw


def test_insert_entry_idempotent_and_fetch_open(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    kw = _min_entry_kwargs()
    eid1 = repo.insert_vrp_macro_entry(**kw)
    eid2 = repo.insert_vrp_macro_entry(**kw)  # same day, auto -> idempotent
    assert eid1 == eid2
    rows = repo.fetch_open_vrp_macro_entries("SPX", date(2026, 6, 25))
    assert len(rows) == 1 and rows[0]["entry_id"] == eid1
    # the 4 strikes surface under the short leg-names the job consumes
    assert rows[0]["short_above"] == 5800 and rows[0]["wing_below"] == 5590
    assert repo.fetch_open_vrp_macro_entries("SPX", date(2026, 8, 8)) == []  # expired


def test_button_cohorts_not_deduped_and_excluded_from_open(
    seeded_db_empty_cards: Repository,
):
    repo = seeded_db_empty_cards
    b1 = repo.insert_vrp_macro_entry(**_min_entry_kwargs(origin="button"))
    b2 = repo.insert_vrp_macro_entry(**_min_entry_kwargs(origin="button"))
    assert b1 != b2  # each click is its own one-shot capture
    # button cohorts are never returned to the snapshot loop
    assert repo.fetch_open_vrp_macro_entries("SPX", date(2026, 6, 25)) == []


def test_insert_quotes_upsert(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    eid = repo.insert_vrp_macro_entry(**_min_entry_kwargs())
    q = dict(
        entry_id=eid,
        as_of=datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc),
        session="rth",
        leg="short_above",
        strike=5800,
        opt_right="P",
        nbbo_bid=12.0,
        nbbo_ask=12.4,
        iv=0.17,
        delta=-0.26,
        gamma=0.001,
        vega=8.0,
        theta=-1.2,
        und_spot=6000,
        source="xenon_ib",
        greeks_source="bs",
        source_asof=None,
    )
    repo.insert_vrp_macro_entry_quotes([q])
    repo.insert_vrp_macro_entry_quotes([{**q, "nbbo_bid": 11.5}])  # same PK -> update
    got = repo.fetch_vrp_macro_entry_quotes(eid)
    assert len(got) == 1 and float(got[0]["nbbo_bid"]) == 11.5


def test_grid_cache_upsert_and_fetch(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 24),
        chosen_expiry=date(2026, 8, 6),
        strikes=[6865.0, 6870.0, 7085.0, 7090.0],
    )
    # same (name, for_date) overwrites
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 24),
        chosen_expiry=date(2026, 8, 6),
        strikes=[6860.0, 6865.0, 7085.0, 7090.0, 7095.0],
    )
    got = repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 24))
    assert got is not None
    assert got["chosen_expiry"] == date(2026, 8, 6)
    assert [float(s) for s in got["strikes"]] == [
        6860.0,
        6865.0,
        7085.0,
        7090.0,
        7095.0,
    ]
    # no strike_ivs passed → column is NULL (flat-vol fallback)
    assert got["strike_ivs"] is None


def test_grid_cache_strike_ivs_roundtrip(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 24),
        chosen_expiry=date(2026, 8, 6),
        strikes=[6860.0, 7090.0],
        strike_ivs={6860.0: 0.184, 7090.0: 0.152},
    )
    got = repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 24))
    assert got is not None
    # JSON keys come back as strings; values as floats
    assert {float(k): v for k, v in got["strike_ivs"].items()} == {
        6860.0: 0.184,
        7090.0: 0.152,
    }


def test_grid_cache_stale_fallback_and_expiry_guard(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    # a grid cached two days earlier, expiry still open
    repo.upsert_vrp_macro_entry_grid(
        name="SPX",
        for_date=date(2026, 6, 22),
        chosen_expiry=date(2026, 8, 4),
        strikes=[6865.0, 7090.0],
    )
    # asking 2 days later (within the 4-day staleness window) reuses the prior grid
    got = repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 24))
    assert got is not None and got["for_date"] == date(2026, 6, 22)
    # but a grid older than the staleness bound is NOT reused (would birth too-near
    # an expiry vs the intended ~43 DTE) → skip, don't persist an off-strategy cohort
    assert repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 6, 27)) is None
    # never reuse a grid whose chosen expiry has already passed
    assert repo.fetch_vrp_macro_entry_grid("SPX", date(2026, 8, 5)) is None
    # cold cache for an unknown name → None
    assert repo.fetch_vrp_macro_entry_grid("QQQ", date(2026, 6, 24)) is None


def test_grid_cache_rejects_empty_strikes(seeded_db_empty_cards: Repository):
    import psycopg

    repo = seeded_db_empty_cards
    # the DB CHECK forbids an empty grid (a useless row that would shadow the
    # stale-fallback and break birth's leg resolution)
    try:
        repo.upsert_vrp_macro_entry_grid(
            name="SPX",
            for_date=date(2026, 6, 24),
            chosen_expiry=date(2026, 8, 6),
            strikes=[],
        )
        raised = False
    except psycopg.errors.CheckViolation:
        repo.conn.rollback()
        raised = True
    assert raised
