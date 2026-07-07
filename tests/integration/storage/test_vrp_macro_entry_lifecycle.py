"""Storage read-back for the VRP-macro trade-lifecycle layer (#223)."""

from datetime import date, datetime, timezone

from uw_scan.storage.repository import Repository


def _entry_kwargs(**over):
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


def _quote(entry_id, as_of, leg, strike, bid, ask, spot, session="rth"):
    return dict(
        entry_id=entry_id,
        as_of=as_of,
        session=session,
        leg=leg,
        strike=strike,
        opt_right="P",
        nbbo_bid=bid,
        nbbo_ask=ask,
        iv=0.17,
        delta=-0.25,
        gamma=0.001,
        vega=8.0,
        theta=-1.2,
        und_spot=spot,
        source="xenon_ib",
        greeks_source="bs",
        source_asof=None,
    )


def _seed_two_marks(repo: Repository) -> int:
    eid = repo.insert_vrp_macro_entry(**_entry_kwargs())
    t0 = datetime(2026, 6, 24, 14, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)
    # birth: short mid 12.2, wing mid 4.2 -> credit 8.0
    repo.insert_vrp_macro_entry_quotes(
        [
            _quote(eid, t0, "short_above", 5800, 12.0, 12.4, 6000),
            _quote(eid, t0, "wing_above", 5600, 4.0, 4.4, 6000),
        ]
    )
    # later: short mid 6.0, wing mid 2.0 -> value 4.0 -> pnl 4.0
    repo.insert_vrp_macro_entry_quotes(
        [
            _quote(eid, t1, "short_above", 5800, 5.8, 6.2, 6050, session="eod"),
            _quote(eid, t1, "wing_above", 5600, 1.8, 2.2, 6050, session="eod"),
        ]
    )
    return eid


def test_lifecycle_list_first_last_marks(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    eid = _seed_two_marks(repo)
    rows = repo.list_vrp_macro_entry_lifecycle(name="SPX")
    assert len(rows) == 1
    r = rows[0]
    assert r["entry_id"] == eid
    assert float(r["entry_short_mid"]) == 12.2
    assert float(r["entry_wing_mid"]) == 4.2
    assert float(r["last_short_mid"]) == 6.0
    assert float(r["last_wing_mid"]) == 2.0
    assert float(r["last_spot"]) == 6050
    assert r["n_marks"] == 2


def test_lifecycle_list_entry_id_filter_and_empty(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    eid = _seed_two_marks(repo)
    # entry with no quotes still surfaces (open cohort, no marks yet)
    eid2 = repo.insert_vrp_macro_entry(
        **_entry_kwargs(birth_date=date(2026, 6, 25), origin="button")
    )
    only = repo.list_vrp_macro_entry_lifecycle(entry_id=eid2)
    assert len(only) == 1 and only[0]["entry_id"] == eid2
    assert only[0]["n_marks"] == 0
    assert only[0]["entry_short_mid"] is None
    assert repo.list_vrp_macro_entry_lifecycle(entry_id=eid)[0]["n_marks"] == 2


def test_lifecycle_pnl_series_ordered(seeded_db_empty_cards: Repository):
    repo = seeded_db_empty_cards
    eid = _seed_two_marks(repo)
    series = repo.fetch_vrp_macro_entry_pnl_series(eid)
    assert len(series) == 2
    assert series[0]["as_of"] < series[1]["as_of"]
    assert float(series[0]["short_mid"]) == 12.2
    assert float(series[1]["wing_mid"]) == 2.0
    assert series[1]["session"] == "eod"
