from __future__ import annotations

from datetime import date
from decimal import Decimal

import uw_scan.worker.jobs.option_surface_iv_canary as canary


def _seed_grid(repo, ticker, d, spot):
    for expiry in (date(2026, 7, 17), date(2026, 8, 21)):
        repo.upsert_option_surface_grid(
            ticker,
            d,
            spot,
            [
                {
                    "expiry": expiry,
                    "strike": Decimal("250"),
                    "call_iv": Decimal("0.50"),
                    "put_iv": Decimal("0.52"),
                },
            ],
        )
    repo.conn.commit()


def test_canary_persists_diffs_and_returns_median(seeded_db_with_cards, monkeypatch):
    repo = seeded_db_with_cards
    d = date(2026, 6, 19)
    card = next(c for c in repo.list_watchlist_cards() if c.ticker == "TSLA")
    _seed_grid(repo, "TSLA", d, card.spot or Decimal("250"))

    # IB reports 0.55 vs UW 0.50 -> abs_diff 0.05 on every contract.
    monkeypatch.setattr(canary, "fetch_ib_option_iv", lambda **k: Decimal("0.55"))

    median = canary.option_surface_iv_canary(
        repo=repo, settings=_FakeSettings(), today=d
    )

    assert median == Decimal("0.05")
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM uw_scan.iv_source_validation WHERE ticker='TSLA'"
        )
        assert cur.fetchone()[0] == 2  # front 2 expiries


class _FakeSettings:
    xenon_query_api_url = "http://x:8421"
    xenon_query_api_key = None
    option_surface_iv_canary_warn_threshold = 0.02
