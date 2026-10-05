from uw_scan.storage.repository import Repository


def test_upsert_and_fetch_latest_gex(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    payload = {
        "ticker": "SPX",
        "spot": 5800.12,
        "net_gex": -2_400_000_000,
        "levels": {"max_magnet": {"strike": 5780, "gamma": 1.5e9}},
        "profile": [],
    }
    repo.upsert_gex_snapshot(ticker="SPX", payload=payload)
    result = repo.fetch_latest_gex(ticker="SPX")
    assert result is not None
    assert result["spot"] == 5800.12
    assert result["levels"]["max_magnet"]["strike"] == 5780


def test_fetch_latest_gex_filters_by_ticker(seeded_db_empty_cards: Repository) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_gex_snapshot(ticker="SPX", payload={"spot": 5800})
    repo.upsert_gex_snapshot(ticker="SPY", payload={"spot": 580})
    spx = repo.fetch_latest_gex(ticker="SPX")
    spy = repo.fetch_latest_gex(ticker="SPY")
    assert spx is not None and spx["spot"] == 5800
    assert spy is not None and spy["spot"] == 580


def test_fetch_latest_gex_returns_none_for_unknown_ticker(
    seeded_db_empty_cards: Repository,
) -> None:
    assert seeded_db_empty_cards.fetch_latest_gex(ticker="UNKNOWN") is None


def test_fetch_latest_gex_populates_scan_time_and_ticker_when_missing(
    seeded_db_empty_cards: Repository,
) -> None:
    repo = seeded_db_empty_cards
    repo.upsert_gex_snapshot(ticker="SPX", payload={"spot": 5800})
    result = repo.fetch_latest_gex(ticker="SPX")
    assert result is not None
    assert result["ticker"] == "SPX"
    assert result["scan_time"]  # populated from scanned_at


def test_fetch_intraday_sessions_returns_grouped_rth_points(
    seeded_db_empty_cards: Repository,
) -> None:
    """fetch_intraday_sessions groups by ET trading date, ASC sorted,
    filtered to RTH 09:30-16:00 ET."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    repo = seeded_db_empty_cards
    et = ZoneInfo("America/New_York")
    schema = repo._schema

    # Seed three sessions with mixed RTH + pre-market ticks. Override the
    # default-now scanned_at so we control ET grouping.
    seeds = [
        # 06-09 ET: one pre-market (filtered out) + two RTH
        (datetime(2026, 6, 9, 8, 0, tzinfo=et), 7400.0, -50000.0, 7395.0, 0.18),
        (datetime(2026, 6, 9, 10, 0, tzinfo=et), 7402.0, -49000.0, 7396.0, 0.18),
        (datetime(2026, 6, 9, 15, 30, tzinfo=et), 7405.0, -48000.0, 7398.0, 0.19),
        # 06-10 ET: two RTH
        (datetime(2026, 6, 10, 9, 30, tzinfo=et), 7406.0, -47000.0, 7400.0, 0.19),
        (datetime(2026, 6, 10, 14, 0, tzinfo=et), 7410.0, -46000.0, 7402.0, 0.20),
    ]
    for ts, spot, net_gex, flip, iv in seeds:
        payload = {
            "spot": spot,
            "net_gex": net_gex,
            "levels": {"gex_flip": {"strike": flip, "gamma": 1.0}},
            "iv": {"iv30d": iv},
        }
        with repo._conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.gex_snapshots "
                "(ticker, data_date, scanned_at, payload) "
                "VALUES (%s, %s, %s, %s::jsonb)",
                ("SPX", ts.date(), ts, _json_dump(payload)),
            )
        repo._conn.commit()

    out = repo.fetch_intraday_sessions(ticker="SPX", sessions=5, rth_only=True)
    assert len(out) == 2
    assert out[0]["et_date"].isoformat() == "2026-06-09"
    assert out[1]["et_date"].isoformat() == "2026-06-10"
    # Pre-market 08:00 row filtered out → 2 RTH points on 06-09.
    assert len(out[0]["points"]) == 2
    assert len(out[1]["points"]) == 2
    # Ascending order within each session.
    assert out[0]["points"][0]["spot"] == 7402.0
    assert out[0]["points"][1]["spot"] == 7405.0
    assert out[1]["points"][0]["gex_flip"] == 7400.0
    assert out[1]["points"][1]["iv30d"] == 0.20

    # rth_only=False keeps the pre-market row.
    out_all = repo.fetch_intraday_sessions(
        ticker="SPX", sessions=5, rth_only=False
    )
    assert len(out_all[0]["points"]) == 3


def _json_dump(payload: dict) -> str:
    import json

    return json.dumps(payload)


def test_fetch_metrics_history_latest_scan_per_day(
    seeded_db_empty_cards: Repository,
) -> None:
    """Latest scan per data_date wins, a missing bias reads None, other tickers
    and NULL data_date rows are ignored, and LIMIT keeps the newest days."""
    from datetime import date, datetime
    from zoneinfo import ZoneInfo

    repo = seeded_db_empty_cards
    et = ZoneInfo("America/New_York")

    def at(day: int, hour: int) -> datetime:
        return datetime(2026, 6, day, hour, 0, tzinfo=et)

    rows = [
        # 06-09: two scans, the later one must win
        ("SPX", date(2026, 6, 9), at(9, 10), 7390.0, "bullish"),
        ("SPX", date(2026, 6, 9), at(9, 15), 7395.0, "bearish"),
        # 06-10: no bias in the payload
        ("SPX", date(2026, 6, 10), at(10, 11), 7400.0, None),
        # 06-08: oldest day, dropped by limit=2
        ("SPX", date(2026, 6, 8), at(8, 11), 7380.0, "neutral"),
        # other ticker and a NULL data_date row on the newest timestamp
        ("SPY", date(2026, 6, 10), at(10, 15), 740.0, "bullish"),
        ("SPX", None, at(11, 9), 7500.0, "bullish"),
    ]
    with repo._conn.cursor() as cur:
        for ticker, d, ts, flip, bias in rows:
            payload: dict = {
                "levels": {"gex_flip": {"strike": flip}},
                "iv": {"iv30d": 0.18},
                "vol_pc": 0.9,
            }
            if bias is not None:
                payload["bias"] = {"direction": bias}
            cur.execute(
                f"INSERT INTO {repo._schema}.gex_snapshots "
                "(ticker, data_date, scanned_at, payload) VALUES (%s, %s, %s, %s::jsonb)",
                (ticker, d, ts, _json_dump(payload)),
            )
    repo._conn.commit()

    out = repo.fetch_metrics_history(ticker="spx", limit=2)
    assert list(out) == [date(2026, 6, 10), date(2026, 6, 9)]
    assert out[date(2026, 6, 10)] == {
        "flip": 7400.0,
        "iv_30d": 0.18,
        "vol_pc": 0.9,
        "bias": None,
    }
    assert out[date(2026, 6, 9)]["flip"] == 7395.0
    assert out[date(2026, 6, 9)]["bias"] == "bearish"
