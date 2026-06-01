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
    # Force the iv_rank fallback path so this test asserts on iv_rank.close = 5800.0
    # rather than whatever /stock-state currently returns for SPX.
    monkeypatch.setattr(
        gex_scanner, "fetch_stock_state_snapshot", lambda c, r, rid, t: None
    )

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
    monkeypatch.setattr(
        gex_scanner, "fetch_stock_state_snapshot", lambda c, r, rid, t: None
    )
    with pytest.raises(RuntimeError):
        gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    with seeded_db_empty_cards.conn.cursor() as cur:
        cur.execute("SELECT status FROM uw_scan.scan_runs ORDER BY run_id DESC LIMIT 1")
        status = cur.fetchone()[0]
    assert status == "error"


def _stub_minimal_chain(monkeypatch):
    """Stub iv_rank + strike + aggregate fetchers with bare minimum rows."""
    monkeypatch.setattr(
        gex_scanner,
        "fetch_iv_rank_rows",
        lambda c, r, rid, t: [
            {
                "date": "2026-05-16",
                "close": "7400.0",
                "volatility": "0.15",
                "iv_rank_1y": "30.0",
            },
        ],
    )
    monkeypatch.setattr(
        gex_scanner,
        "fetch_strike_gex",
        lambda c, r, rid, t: [
            {
                "strike": 7400,
                "call_gex": 1e8,
                "put_gex": -1e8,
                "net_gex": 0,
                "call_delta": 0.5,
                "put_delta": -0.5,
                "net_delta": 0,
            },
        ],
    )
    monkeypatch.setattr(
        gex_scanner,
        "fetch_aggregate_gex",
        lambda c, r, rid, t: [],
    )
    monkeypatch.setattr(gex_scanner, "fetch_vol_pc", lambda c, r, rid, t: None)


def test_run_uses_stock_state_when_available(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    """When /stock-state returns, scanner uses its intraday close, not iv_rank.close."""
    _stub_minimal_chain(monkeypatch)
    monkeypatch.setattr(
        gex_scanner,
        "fetch_stock_state_snapshot",
        lambda c, r, rid, t: {
            "spot": 7408.5,
            "prev_close": 7501.24,
            "market_time": "regular",
            "tape_time": "2026-05-15T20:46:05Z",
            "source": "stock_state",
        },
    )

    gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    payload = seeded_db_empty_cards.fetch_latest_gex(ticker="SPX")

    assert payload["spot"] == 7408.5  # stock-state, not iv_rank.close (7400.0)
    assert payload["prev_close"] == 7501.24
    assert payload["market_time"] == "regular"
    assert payload["tape_time"] == "2026-05-15T20:46:05Z"
    assert payload["spot_source"] == "stock_state"
    assert payload["day_change"] == round(7408.5 - 7501.24, 4)
    assert payload["day_change_pct"] == round((7408.5 - 7501.24) / 7501.24 * 100, 4)


def test_run_falls_back_to_iv_rank_when_stock_state_fails(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    """When /stock-state fetcher returns None, scanner uses iv_rank.close + tags source."""
    _stub_minimal_chain(monkeypatch)
    monkeypatch.setattr(
        gex_scanner, "fetch_stock_state_snapshot", lambda c, r, rid, t: None
    )

    gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")
    payload = seeded_db_empty_cards.fetch_latest_gex(ticker="SPX")

    assert payload["spot"] == 7400.0  # iv_rank.close
    assert payload["prev_close"] is None
    assert payload["market_time"] is None
    assert payload["tape_time"] is None
    assert payload["spot_source"] == "iv_rank_eod"
    assert payload["day_change"] is None
    assert payload["day_change_pct"] is None


def test_run_persists_greek_exposure_daily_tail(
    seeded_db_empty_cards: Repository,
    mock_client: UwClient,
    monkeypatch,
) -> None:
    """After a scan, the /greek-exposure history rows land in
    uw_scan.greek_exposure_daily — via the shared parser util."""
    from datetime import date

    from uw_scan.storage.greek_exposure_repository import (
        GreekExposureDailyRepository,
    )

    _stub_minimal_chain(monkeypatch)
    monkeypatch.setattr(
        gex_scanner, "fetch_stock_state_snapshot", lambda c, r, rid, t: None
    )

    # Override fetch_aggregate_gex (whose body now delegates to the shared
    # parser util — see B1.5) to return rows the scanner will both use for
    # net_dex AND persist into greek_exposure_daily.
    fake_rows = [
        {
            "date": date(2026, 5, 13),
            "call_gex": 2e9,
            "put_gex": -1e9,
            "call_delta": 1e7,
            "put_delta": -1e6,
            "net_gex": 1e9,
            "net_dex": 9e6,
        },
        {
            "date": date(2026, 5, 14),
            "call_gex": 2.1e9,
            "put_gex": -1.0e9,
            "call_delta": 1.1e7,
            "put_delta": -1.1e6,
            "net_gex": 1.1e9,
            "net_dex": 9.9e6,
        },
        {
            "date": date(2026, 5, 15),
            "call_gex": 1.9e9,
            "put_gex": -1.0e9,
            "call_delta": 0.9e7,
            "put_delta": -0.9e6,
            "net_gex": 0.9e9,
            "net_dex": 8.1e6,
        },
    ]
    monkeypatch.setattr(
        gex_scanner, "fetch_aggregate_gex", lambda c, r, rid, t: fake_rows
    )

    gex_scanner.run(mock_client, seeded_db_empty_cards, ticker="SPX")

    daily_repo = GreekExposureDailyRepository(
        seeded_db_empty_cards.conn,
        schema=seeded_db_empty_cards._schema,
    )
    rows = daily_repo.fetch_history("SPX", days=10)
    assert len(rows) == 3
    assert rows[-1]["call_gex"] == pytest.approx(1.9e9)
    assert rows[-1]["net_gex"] == pytest.approx(0.9e9)  # generated column


# Pass-6 calibration patch: lock in PR #108's gex.py error-path fix.
# Verifies that when a fetcher raises, the scan_run row is sealed
# status='error' (not stuck 'running') AND the original exception
# propagates uncovered. Pre-PR-108, finish_scan_run's UPDATE was
# silently rolled back at conn close, leaving an orphan running row.

class _SimulatedFetcherFailure(RuntimeError):
    """Stand-in for a fetcher raising in the middle of gex.run."""


def test_run_seals_status_error_when_fetcher_raises(
    seeded_db_empty_cards: Repository, mock_client: UwClient, monkeypatch
):
    def _boom(*_args, **_kwargs):
        raise _SimulatedFetcherFailure("simulated upstream failure")

    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", _boom)

    repo = seeded_db_empty_cards

    with pytest.raises(_SimulatedFetcherFailure):
        gex_scanner.run(mock_client, repo, ticker="SPY")

    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT status, finished_at FROM uw_scan.scan_runs "
            "WHERE ticker = 'SPY' AND notes = 'gex_scan_SPY' "
            "ORDER BY run_id DESC LIMIT 1"
        )
        row = cur.fetchone()

    assert row is not None, "scan_runs row must be inserted before the fetcher raised"
    assert row[0] == "error", "scan_run must be sealed status='error', not stuck 'running'"
    assert row[1] is not None, "finished_at must be populated by the error-path commit"
