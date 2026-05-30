"""Integration test for positioning_refresh_once — real repo + fake UW client.

The fake client returns a different spec-derived payload per endpoint slug; the
job fans out the five fetchers, aggregates, and upserts one uw_positioning row
per ticker. Asserts persistence, idempotency, and shard (ticker_filter) respect.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.worker.jobs.positioning_jobs import positioning_refresh_once

_PAYLOADS: dict[EndpointSlug, dict[str, Any]] = {
    EndpointSlug.SHORT_INTEREST_FLOAT: {
        "data": {
            "si_float": "0.0734",
            "short_interest": 175611155,
            "total_float": 2392000000,
            "days_to_cover": "1.205",
            "market_date": "2026-05-15",
        }
    },
    EndpointSlug.ANALYST_RATINGS: {
        "data": [
            {"recommendation": "buy", "target": "420.0"},
            {"recommendation": "hold", "target": "300.0"},
        ]
    },
    EndpointSlug.INSTITUTION_OWNERSHIP: {
        "data": [
            {"name": "VANGUARD", "inst_value": "1095205923.0"},
            {"name": "BLACKROCK", "inst_value": "900000000.0"},
        ]
    },
    EndpointSlug.INSIDER_TICKER_FLOW: {
        "data": [
            {"buy_sell": "buy", "premium": "664386", "volume": 244331},
            {"buy_sell": "sell", "premium": "100000", "volume": 50000},
        ]
    },
    EndpointSlug.EARNINGS: {
        "data": [
            {"report_date": "2024-11-10", "post_earnings_move_1d": "0.0724"},
            {"report_date": "2024-08-02", "post_earnings_move_1d": "-0.02"},
        ]
    },
}


class _MultiFakeUwClient:
    def __init__(self) -> None:
        self.rate_limit = SimpleNamespace(
            daily_count=0, minute_remaining=110, minute_reset=None
        )

    def get(
        self,
        slug: EndpointSlug,
        ticker: str | None = None,
        params: dict[str, Any] | None = None,
        run_id: int | None = None,
        *,
        option_symbol: str | None = None,
    ) -> tuple[httpx.Response, dict[str, str]]:
        resp = httpx.Response(
            200,
            json=_PAYLOADS[slug],
            request=httpx.Request("GET", "https://example/x"),
        )
        return resp, {}


def _first_active_ticker(repo) -> str:
    actives = repo.list_active_watchlist()
    assert actives, "watchlist seed is empty"
    return actives[0].ticker


def test_job_persists_aggregated_row_for_shard(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    target = _first_active_ticker(repo)
    client = _MultiFakeUwClient()

    n = positioning_refresh_once(repo, client, ticker_filter=lambda t: t == target)
    assert n == 1  # only the one shard ticker processed

    row = repo.get_uw_positioning(target)
    assert row is not None
    assert row["snapshot_date"] == date.today()
    assert row["si_pct_float"] == Decimal("0.0734")
    assert row["analyst_buy"] == 1
    assert row["analyst_hold"] == 1
    assert row["inst_holder_count"] == 2
    assert row["inst_total_value"] == Decimal("1995205923.0")
    assert row["insider_net_flow"] == Decimal("564386")
    assert row["earn_reactions_positive"] == 1
    assert row["earn_reactions_total"] == 2
    assert row["next_er_date"] is None  # sourced separately (M6); na for now
    assert row["raw_jsonb"]["analyst_ratings"]["analyst_buy"] == 1


def test_job_is_idempotent_on_rerun(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    target = _first_active_ticker(repo)
    client = _MultiFakeUwClient()
    shard = lambda t: t == target  # noqa: E731

    positioning_refresh_once(repo, client, ticker_filter=shard)
    positioning_refresh_once(repo, client, ticker_filter=shard)

    with repo._conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.uw_positioning WHERE ticker = %s",
            (target.upper(),),
        )
        assert cur.fetchone()[0] == 1  # same (ticker, snapshot_date) key


def test_job_skips_tickers_outside_shard(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _MultiFakeUwClient()
    n = positioning_refresh_once(repo, client, ticker_filter=lambda t: False)
    assert n == 0
