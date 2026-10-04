from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

import uw_scan.worker.jobs.option_surface_iv_canary as canary
from uw_scan.sources.source_errors import SourceUnavailable


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


def _ib_iv_rows(repo, ticker):
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT expiry, ib_iv FROM uw_scan.iv_source_validation "
            "WHERE ticker=%s ORDER BY expiry",
            (ticker,),
        )
        return cur.fetchall()


def test_one_unavailable_leg_is_recorded_without_ib_and_run_continues(
    seeded_db_with_cards, monkeypatch
):
    """Unit = one contract leg: an outage on one leg keeps the UW side of that
    row (ib_iv NULL, as before) and the other leg's comparison."""
    repo = seeded_db_with_cards
    d = date(2026, 6, 19)
    card = next(c for c in repo.list_watchlist_cards() if c.ticker == "TSLA")
    _seed_grid(repo, "TSLA", d, card.spot or Decimal("250"))

    def one_down(**k):
        if k["expiry"] == "20260717":
            raise SourceUnavailable("xenon_query", "ConnectError('down')")
        return Decimal("0.55")

    monkeypatch.setattr(canary, "fetch_ib_option_iv", one_down)
    median = canary.option_surface_iv_canary(
        repo=repo, settings=_FakeSettings(), today=d
    )

    assert median == Decimal("0.05")
    assert _ib_iv_rows(repo, "TSLA") == [
        (date(2026, 7, 17), None),
        (date(2026, 8, 21), Decimal("0.55")),
    ]


def test_every_leg_unavailable_fails_the_run(seeded_db_with_cards, monkeypatch):
    """xenon down, or XENON_QUERY_API_KEY missing (a 401 on every leg), used to
    read as "no comparisons available" at INFO. Now the job fails, after the
    UW side of every row is persisted."""
    repo = seeded_db_with_cards
    d = date(2026, 6, 19)
    card = next(c for c in repo.list_watchlist_cards() if c.ticker == "TSLA")
    _seed_grid(repo, "TSLA", d, card.spot or Decimal("250"))

    def down(**_k):
        raise SourceUnavailable("xenon_query", "HTTPStatusError 401")

    monkeypatch.setattr(canary, "fetch_ib_option_iv", down)
    with pytest.raises(SourceUnavailable, match="legs unavailable"):
        canary.option_surface_iv_canary(repo=repo, settings=_FakeSettings(), today=d)
    assert [r[1] for r in _ib_iv_rows(repo, "TSLA")] == [None, None]


class _FakeSettings:
    xenon_query_api_url = "http://x:8421"
    xenon_query_api_key = None
    option_surface_iv_canary_warn_threshold = 0.02
