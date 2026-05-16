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
