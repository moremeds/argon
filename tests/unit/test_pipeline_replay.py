"""`run_single_stock(market_date=...)` replays a past session honestly.

Three properties matter and each has a test:
  1. every stamp comes from the replay date, not today();
  2. datasets whose UW endpoint ignores `date` are never written;
  3. `market_date=None` behaves exactly as it does today.
"""

from datetime import date
from unittest.mock import MagicMock

import pytest

from uw_scan import pipeline

_FETCHERS = (
    "fetch_bulk_screener_ticker",
    "fetch_darkpool_ticker",
    "fetch_flow_alerts",
    "fetch_greek_exposure",
    "fetch_greek_exposure_by_expiry",
    "fetch_greeks",
    "fetch_interpolated_iv",
    "fetch_max_pain",
    "fetch_oi_change",
    "fetch_oi_per_strike",
    "fetch_option_contracts",
    "fetch_realized_volatility",
    "fetch_short_data",
    "fetch_skew",
    "fetch_spot_exposures",
    "fetch_term_structure",
    "fetch_volatility_stats",
)


def _stub_all_fetchers(monkeypatch, record=None):
    for name in _FETCHERS:
        def _make(n):
            def _f(*a, **k):
                if record is not None:
                    record.setdefault(n, []).append(k)
                # this one returns a single row or None, not a list
                return None if n == "fetch_bulk_screener_ticker" else []

            return _f

        monkeypatch.setattr(pipeline.uw_sources, name, _make(name))


def _repo():
    repo = MagicMock()
    repo.insert_scan_run.return_value = 1
    return repo


@pytest.fixture(autouse=True)
def _stub_pure_compute(monkeypatch):
    """Neutralise the assembly/scoring helpers — this file tests date plumbing,
    not report assembly, and a MagicMock repo cannot satisfy them."""
    monkeypatch.setattr(pipeline, "_safe_spot_for_derive", lambda repo, ticker: None)
    monkeypatch.setattr(
        pipeline, "assemble_single_stock_report", lambda t, r, repo: MagicMock()
    )
    monkeypatch.setattr(pipeline.scoring, "classify_setup_c", lambda report: None)


def test_replay_stamps_the_supplied_date_not_today(monkeypatch):
    seen: dict = {}
    repo = _repo()
    repo.upsert_exposures_summary.side_effect = lambda **kw: seen.setdefault(
        "exposures", kw["market_date"]
    )
    repo.insert_max_pain_rows.side_effect = lambda *a: seen.setdefault("max_pain", a[2])
    repo.append_pcr_history.side_effect = lambda **kw: seen.setdefault(
        "pcr", kw["snapshot_date"]
    )
    _stub_all_fetchers(monkeypatch)
    # exposures_summary only writes when the aggregate fetch returns rows
    monkeypatch.setattr(
        pipeline.uw_sources, "fetch_greek_exposure_by_expiry", lambda *a, **k: [object()]
    )
    monkeypatch.setattr(
        pipeline.cards_exposures, "build_summary_rows_from_aggregate", lambda *a, **k: []
    )

    pipeline.run_single_stock("AAPL", MagicMock(), repo, market_date=date(2026, 8, 12))

    assert seen["exposures"] == date(2026, 8, 12)
    assert seen["max_pain"] == date(2026, 8, 12)


def test_replay_does_not_write_datasets_whose_endpoint_ignores_date(monkeypatch):
    """/shorts/{ticker}/data returns an identical body for any date (measured
    2026-08-16), so a replayed write would back-date today's numbers."""
    repo = _repo()
    _stub_all_fetchers(monkeypatch)

    pipeline.run_single_stock("AAPL", MagicMock(), repo, market_date=date(2026, 8, 12))

    repo.insert_short_interest_snapshot.assert_not_called()


def test_replay_does_not_emit_live_decision_artifacts(monkeypatch):
    """Scanner candidates and trade insights are live surfaces; injecting
    past-dated rows into them would pollute a decision surface."""
    called: dict = {}
    monkeypatch.setattr(
        pipeline,
        "run_scanner_detectors",
        lambda **kw: called.setdefault("scanner", True),
    )
    monkeypatch.setattr(
        pipeline,
        "_persist_trade_insights_for_run",
        lambda **kw: called.setdefault("insights", True),
    )
    _stub_all_fetchers(monkeypatch)

    pipeline.run_single_stock("AAPL", MagicMock(), _repo(), market_date=date(2026, 8, 12))

    assert "scanner" not in called
    assert "insights" not in called


def test_replay_passes_market_date_to_the_fetchers(monkeypatch):
    record: dict = {}
    _stub_all_fetchers(monkeypatch, record)

    pipeline.run_single_stock("AAPL", MagicMock(), _repo(), market_date=date(2026, 8, 12))

    for name in ("fetch_oi_per_strike", "fetch_max_pain", "fetch_term_structure"):
        assert record[name][0]["market_date"] == date(2026, 8, 12), name


def test_live_path_still_writes_everything(monkeypatch):
    """market_date=None must behave exactly as before."""
    repo = _repo()
    called: dict = {}
    monkeypatch.setattr(
        pipeline, "run_scanner_detectors", lambda **kw: called.setdefault("scanner", True)
    )
    _stub_all_fetchers(monkeypatch)
    monkeypatch.setattr(
        pipeline.normalize, "latest_by_timestamp", lambda rows: object()
    )

    pipeline.run_single_stock("AAPL", MagicMock(), repo)

    repo.insert_flow_events.assert_called()
    repo.insert_short_interest_snapshot.assert_called()
    assert called.get("scanner") is True


def test_live_path_sends_no_date_to_fetchers(monkeypatch):
    record: dict = {}
    _stub_all_fetchers(monkeypatch, record)

    pipeline.run_single_stock("AAPL", MagicMock(), _repo())

    assert record["fetch_oi_per_strike"][0].get("market_date") is None
