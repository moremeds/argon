"""TopNetImpactRepository roundtrip, the per-update rank-change carry, and the
bullish/bearish balanced split.

Tickers + net_premium are REAL observed values from
GET /api/market/top-net-impact?date=2026-06-26 (frozen). `rank` is our own
computed position field; the two captures vary it to exercise the prev_rank
carry that drives the chart's ▲▼ rank delta.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.storage.top_net_impact_repository import TopNetImpactRepository

_D = date(2026, 6, 26)

# Real frozen net premiums (2026-06-26).
_NP = {
    "TSLA": Decimal("61902126.00"),
    "LLY": Decimal("37500038.00"),
    "QQQ": Decimal("33450376.00"),
    "NVDA": Decimal("-23943821.00"),
    "SPY": Decimal("-93300000.00"),
    "MU": Decimal("-103000000.00"),
}


def _cap(ranks: dict[str, int]) -> list[dict]:
    return [
        {"data_date": _D, "ticker": t, "net_premium": _NP[t], "rank": r}
        for t, r in ranks.items()
    ]


def test_first_capture_marks_all_new(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = TopNetImpactRepository(repo.conn, schema=repo._schema)
    r.upsert_rows(_cap({"TSLA": 1, "LLY": 2, "NVDA": 3}))

    _, rows = r.fetch_latest(data_date=_D, limit=10)
    by = {row["ticker"]: row for row in rows}
    # First capture: no prior rank → "new this session".
    assert by["TSLA"]["prev_rank"] is None
    assert by["TSLA"]["rank_change"] is None


def test_rank_change_on_reshuffle(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = TopNetImpactRepository(repo.conn, schema=repo._schema)
    # Capture 1: TSLA #1, LLY #2, NVDA #3.
    r.upsert_rows(_cap({"TSLA": 1, "LLY": 2, "NVDA": 3}))
    # Capture 2: LLY climbs to #1, TSLA slips to #2, NVDA flat.
    r.upsert_rows(_cap({"LLY": 1, "TSLA": 2, "NVDA": 3}))

    _, rows = r.fetch_latest(data_date=_D, limit=10)
    by = {row["ticker"]: row for row in rows}
    assert by["LLY"]["rank_change"] == 1  # ▲1 (prev 2 → 1)
    assert by["TSLA"]["rank_change"] == -1  # ▼1 (prev 1 → 2)
    assert by["NVDA"]["rank_change"] == 0  # unchanged


def test_balanced_split_keeps_both_extremes(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = TopNetImpactRepository(repo.conn, schema=repo._schema)
    # 3 bullish + 3 bearish.
    r.upsert_rows(_cap({"TSLA": 1, "LLY": 2, "QQQ": 3, "NVDA": 4, "SPY": 5, "MU": 6}))
    # limit=4 → top 2 + bottom 2; the mid pair (QQQ, NVDA) drops out.
    _, rows = r.fetch_latest(data_date=_D, limit=4)
    tickers = [row["ticker"] for row in rows]
    assert tickers == ["TSLA", "LLY", "SPY", "MU"]  # sorted DESC, extremes kept
