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
