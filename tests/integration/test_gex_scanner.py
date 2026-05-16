import pytest

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.scanners import gex as gex_scanner
from uw_scan.storage.repository import Repository


@pytest.fixture
def mock_client() -> UwClient:
    """Real UwClient instance — UW calls are monkeypatched at the scanner-fetcher level."""
    s = Settings.from_env()
    return UwClient(
        api_key=s.api_key.get_secret_value(),
        base_url=s.base_url,
        timeout=s.request_timeout_seconds,
    )


def test_run_persists_payload_with_full_xenon_shape(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    monkeypatch.setattr(
        gex_scanner,
        "fetch_iv_rank_rows",
        lambda c, r, rid, t: [
            {
                "date": "2026-05-16",
                "close": "5800.0",
                "volatility": "0.18",
                "iv_rank_1y": "35.0",
            },
        ],
    )
    monkeypatch.setattr(
        gex_scanner,
        "fetch_strike_gex",
        lambda c, r, rid, t: [
            {
                "strike": 5750,
                "call_gex": 1e8,
                "put_gex": -3e8,
                "net_gex": -2e8,
                "call_delta": 0.4,
                "put_delta": -0.6,
                "net_delta": -0.2,
            },
            {
                "strike": 5800,
                "call_gex": 2e8,
                "put_gex": -2e8,
                "net_gex": 0,
                "call_delta": 0.5,
                "put_delta": -0.5,
                "net_delta": 0,
            },
            {
                "strike": 5850,
                "call_gex": 3e8,
                "put_gex": -1e8,
                "net_gex": 2e8,
                "call_delta": 0.6,
                "put_delta": -0.4,
                "net_delta": 0.2,
            },
        ],
    )
    monkeypatch.setattr(
        gex_scanner,
        "fetch_aggregate_gex",
        lambda c, r, rid, t: [
            {
                "date": "2026-05-16",
                "call_gex": 1e10,
                "put_gex": -1e10,
                "call_delta": 0.5,
                "put_delta": -0.5,
            },
        ],
    )
    monkeypatch.setattr(gex_scanner, "fetch_vol_pc", lambda c, r, rid, t: 0.85)

    row_id = gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    assert row_id > 0

    payload = seeded_db_empty_cards.fetch_latest_gex(ticker="SPX")
    assert payload is not None
    assert payload["spot"] == 5800.0
    assert payload["ticker"] == "SPX"
    assert payload["mq"] is None
    assert "profile" in payload
    assert isinstance(payload["profile"], list)
    assert payload["iv"]["source"] == "uw"
    assert payload["iv"]["iv30d"] == 0.18
    assert payload["iv"]["iv_rank"] == 35.0
    assert payload["vol_pc"] == 0.85


def test_run_raises_when_iv_rank_empty(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", lambda c, r, rid, t: [])
    with pytest.raises(RuntimeError, match="could not fetch spot"):
        gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")


def test_run_marks_scan_run_error_when_aborted(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", lambda c, r, rid, t: [])
    with pytest.raises(RuntimeError):
        gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute("SELECT status FROM uw_scan.scan_runs ORDER BY run_id DESC LIMIT 1")
        status = cur.fetchone()[0]
    assert status == "error"
