from datetime import date, datetime, timezone

from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository


def _repo(seeded_db_empty_cards) -> UwHistoricalAlphaRepository:
    return UwHistoricalAlphaRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )


def test_upsert_gex_levels_idempotent(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    row = {
        "ticker": "AAPL",
        "market_date": date(2026, 6, 30),
        "call_wall": "210.5",
        "put_wall": "190",
        "gamma_flip": "200",
        "gamma_magnet": "205",
        "spot": "201",
        "raw_jsonb": {"call_wall": "210.5"},
    }
    assert r.upsert_gex_levels([row]) == 1
    assert r.upsert_gex_levels([{**row, "call_wall": "211"}]) == 1  # upsert, no dup
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT call_wall FROM uw_scan.uw_gex_levels_daily WHERE ticker='AAPL'"
        )
        rows = cur.fetchall()
    assert len(rows) == 1
    assert str(rows[0][0]) == "211"  # DO UPDATE applied


def test_upsert_volatility_signal_source_mask_array(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    row = {
        "ticker": "AAPL",
        "market_date": date(2026, 6, 30),
        "anomaly_direction": "up",
        "anomaly_score": "1.2",
        "vol_character": "trending",
        "vrp_rank": "0.4",
        "risk_premium": "0.02",
        "source_mask": ["anomaly", "vrp"],
    }
    assert r.upsert_volatility_signal([row]) == 1
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT source_mask FROM uw_scan.uw_volatility_signal_daily "
            "WHERE ticker='AAPL'"
        )
        assert cur.fetchone()[0] == ["anomaly", "vrp"]


def test_upsert_short_pressure(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    row = {
        "ticker": "AAPL",
        "market_date": date(2026, 6, 30),
        "short_interest": "140526320",
        "si_float": "0.0095",
        "days_to_cover": "1.2",
        "ftd_quantity": "6502",
        "short_volume": "7093110",
        "total_volume": "13979096",
        "short_volume_ratio": "0.5",
    }
    assert r.upsert_short_pressure([row]) == 1
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT ftd_quantity FROM uw_scan.uw_short_pressure_daily "
            "WHERE ticker='AAPL'"
        )
        assert str(cur.fetchone()[0]) == "6502"


def test_insert_dark_lit_prints_ignores_dupe(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    p = {
        "source": "darkpool",
        "tracking_id": "T1",
        "ticker": "AAPL",
        "executed_at": datetime(2026, 6, 30, 14, tzinfo=timezone.utc),
        "market_date": date(2026, 6, 30),
        "price": "201",
        "size": 100,
        "sale_cond_codes": ["prior_reference_price"],
        "raw_jsonb": {},
    }
    assert r.insert_dark_lit_prints([p]) == 1
    assert r.insert_dark_lit_prints([p]) == 1  # returns len(rows); DO NOTHING
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*), max(sale_cond_codes) FROM uw_scan.uw_dark_lit_flow_prints"
        )
        cnt, scc = cur.fetchone()
    assert cnt == 1  # only one physical row
    assert scc == ["prior_reference_price"]


def test_insert_intraday_flow_bars_dedupe_by_source(seeded_db_empty_cards):
    r = _repo(seeded_db_empty_cards)
    ts = datetime(2026, 6, 30, 13, 30, tzinfo=timezone.utc)
    base = {
        "ticker": "AAPL",
        "market_date": date(2026, 6, 30),
        "ts": ts,
        "expiry": date(1, 1, 1),
        "raw_jsonb": {},
    }
    net = {**base, "source": "net_prem_ticks", "net_call_premium": "1000"}
    greek = {**base, "source": "greek_flow", "dir_delta_flow": "5"}
    assert r.insert_intraday_flow_bars([net, greek]) == 2
    assert r.insert_intraday_flow_bars([net]) == 1  # DO NOTHING on same PK
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.uw_intraday_option_flow_bars")
        assert cur.fetchone()[0] == 2  # two sources at same ts = two rows
