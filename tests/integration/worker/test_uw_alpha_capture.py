import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.storage.uw_historical_alpha_repository import UwHistoricalAlphaRepository
from uw_scan.worker.jobs.uw_alpha_capture import (
    capture_dark_lit_for,
    capture_gex_levels_for,
    capture_intraday_flow_for,
    capture_short_pressure_for,
    capture_volatility_signal_for,
    gex_levels_capture,
)

FIX = Path("tests/fixtures/uw")
MD = date(2026, 6, 30)


def _fx(name):
    return json.loads((FIX / name).read_text())


_PAYLOADS = {
    EndpointSlug.GEX_LEVELS: _fx("gex_levels_aapl.json"),
    EndpointSlug.VOLATILITY_ANOMALY: _fx("volatility_anomaly_aapl.json"),
    EndpointSlug.VOLATILITY_CHARACTER: _fx("volatility_character_aapl.json"),
    EndpointSlug.VOLATILITY_VRP: _fx("volatility_vrp_aapl.json"),
    EndpointSlug.NET_PREM_TICKS: _fx("net_prem_ticks_aapl.json"),
    EndpointSlug.GREEK_FLOW: _fx("greek_flow_aapl.json"),
    EndpointSlug.LIT_FLOW: _fx("lit_flow_aapl.json"),
    EndpointSlug.DARKPOOL_TICKER: _fx("darkpool_aapl.json"),
    EndpointSlug.SHORT_INTEREST_FLOAT: _fx("interest_float_aapl.json"),
    EndpointSlug.FTDS: _fx("ftds_aapl.json"),
    EndpointSlug.VOLUMES_BY_EXCHANGE: _fx("volumes_by_exchange_aapl.json"),
}


class _FakeUwClient:
    def __init__(self):
        self.rate_limit = SimpleNamespace(
            daily_count=0, minute_remaining=110, minute_reset=None
        )

    def get(
        self,
        slug,
        ticker=None,
        params: dict[str, Any] | None = None,
        run_id=None,
        *,
        option_symbol=None,
    ):
        resp = httpx.Response(
            200,
            json=_PAYLOADS[slug],
            request=httpx.Request("GET", "https://example/x"),
        )
        return resp, {}


def _alpha(repo):
    return UwHistoricalAlphaRepository(repo.conn, schema=repo._schema)


def test_capture_gex_levels_writes_real_row(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    alpha = _alpha(repo)
    run_id = repo.insert_scan_run("AAPL", notes="uw_alpha_gex_capture")
    n = capture_gex_levels_for(_FakeUwClient(), repo, alpha, run_id, "AAPL", MD)
    assert n == 1
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT call_wall FROM uw_scan.uw_gex_levels_daily "
            "WHERE ticker='AAPL' AND market_date=%s",
            (MD,),
        )
        assert cur.fetchone()[0] is not None


def test_capture_volatility_signal_merges_three_legs(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("AAPL", notes="vol")
    n = capture_volatility_signal_for(
        _FakeUwClient(), repo, _alpha(repo), run_id, "AAPL", MD
    )
    assert n == 1
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT vrp_rank, source_mask FROM uw_scan.uw_volatility_signal_daily "
            "WHERE ticker='AAPL' AND market_date=%s",
            (MD,),
        )
        rank, mask = cur.fetchone()
    assert rank is not None
    assert set(mask) == {"anomaly", "character", "vrp"}


def test_capture_short_pressure_asof(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    run_id = repo.insert_scan_run("AAPL", notes="short")
    n = capture_short_pressure_for(
        _FakeUwClient(), repo, _alpha(repo), run_id, "AAPL", MD
    )
    assert n == 1
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT short_interest, ftd_quantity FROM uw_scan.uw_short_pressure_daily "
            "WHERE ticker='AAPL' AND market_date=%s",
            (MD,),
        )
        si, ftd = cur.fetchone()
    assert si is not None  # 2026-06-30 is a settlement date in the fixture
    assert ftd is not None  # ftds fixture has a 2026-06-30 row


def test_capture_intraday_and_dark_lit_write_rows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    rid1 = repo.insert_scan_run("AAPL", notes="intraday")
    n_intraday = capture_intraday_flow_for(
        _FakeUwClient(), repo, _alpha(repo), rid1, "AAPL", MD
    )
    rid2 = repo.insert_scan_run("AAPL", notes="darklit")
    n_dl = capture_dark_lit_for(_FakeUwClient(), repo, _alpha(repo), rid2, "AAPL", MD)
    assert n_intraday > 0 and n_dl > 0
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(DISTINCT source) FROM uw_scan.uw_intraday_option_flow_bars"
        )
        assert cur.fetchone()[0] == 2  # net_prem_ticks + greek_flow
        cur.execute(
            "SELECT count(DISTINCT source) FROM uw_scan.uw_dark_lit_flow_prints"
        )
        assert cur.fetchone()[0] == 2  # darkpool + lit_flow


def test_gex_levels_capture_wrapper_real_path(
    seeded_db_empty_cards, _migrated_settings
):
    repo = seeded_db_empty_cards
    target = repo.list_active_watchlist()[0].ticker
    summary = gex_levels_capture(
        repo=repo,
        client=_FakeUwClient(),
        settings=_migrated_settings,
        ticker_filter=lambda t: t == target,
    )
    assert summary["tickers"] == 1
    assert summary["rows"] == 1
    assert summary["errors"] == 0
    # advisory lock released -> re-acquire succeeds
    from uw_scan.worker.jobs.uw_alpha_capture import GEX_LEVELS_CAPTURE_LOCK

    assert repo.try_advisory_lock(GEX_LEVELS_CAPTURE_LOCK)
    repo.release_advisory_lock(GEX_LEVELS_CAPTURE_LOCK)
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.uw_gex_levels_daily WHERE ticker=%s",
            (target,),
        )
        assert cur.fetchone()[0] == 1
