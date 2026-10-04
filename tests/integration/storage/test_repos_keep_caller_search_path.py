"""Standalone repositories must not touch the caller's search_path.

Every one of these repositories used to run ``SET search_path TO <schema>``
inside ``__init__`` on the caller-owned connection — silently changing session
state for every later user of a shared or pooled conn. All their SQL is now
schema-qualified, so construction and reads must leave ``search_path`` alone.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.storage.backtest_repository import BacktestRepository
from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.data_freshness_repository import DataFreshnessRepository
from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
from uw_scan.storage.grg_snapshot_repository import GrgSnapshotRepository
from uw_scan.storage.market_tide_sentiment_repository import (
    MarketTideSentimentRepository,
)
from uw_scan.storage.market_tide_snapshot_repository import (
    MarketTideSnapshotRepository,
)
from uw_scan.storage.option_intraday_repository import OptionIntradayBucketRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
from uw_scan.storage.regime_classification_repository import (
    RegimeClassificationRepository,
)
from uw_scan.storage.technical_live_repository import TechnicalLiveRepository
from uw_scan.storage.technical_vwap_anchor_repository import (
    TechnicalVwapAnchorRepository,
)
from uw_scan.storage.technicals_repository import TechnicalsRepository
from uw_scan.storage.top_net_impact_repository import TopNetImpactRepository
from uw_scan.storage.trade_insight_outcomes_repository import (
    TradeInsightOutcomeRepository,
)
from uw_scan.storage.uw_fetch_memo import UwFetchMemoRepository
from uw_scan.storage.uw_historical_alpha_repository import (
    UwHistoricalAlphaRepository,
)
from uw_scan.storage.vcg_snapshot_repository import VcgSnapshotRepository
from uw_scan.storage.vol_index_repository import VolIndexRepository

pytestmark = pytest.mark.integration

# One cheap call that hits each repository's own table on an empty schema.
# UwHistoricalAlphaRepository is write-only, so its entry is the smallest
# legal upsert row (uncommitted; the per-test fixture resets regardless).
# DataGapHealerRepository is excluded — it keeps its SET search_path for now
# (removed after the healer split qualifies its callers).
_CASES = [
    (BacktestRepository, "fetch_run_results", (0,), {}),
    (ChanlunSignalRepository, "list_non_terminal", ("ZZZZ",), {}),
    (CriSnapshotRepository, "fetch_latest", (), {}),
    (DataFreshnessRepository, "latest_snapshot", (), {}),
    (GreekExposureDailyRepository, "fetch_history", ("ZZZZ", 5), {}),
    (GrgSnapshotRepository, "fetch_latest", (), {}),
    (MarketTideSentimentRepository, "fetch_history", (), {"days": 5}),
    (MarketTideSnapshotRepository, "fetch_sessions", (), {"sessions": 1}),
    (
        OptionIntradayBucketRepository,
        "fetch_buckets",
        ("ZZZZ", date(2026, 1, 1)),
        {},
    ),
    (RegimeBacktestRepository, "fetch_daily_for_run", (0,), {}),
    (
        RegimeClassificationRepository,
        "find_completed_classification_run",
        (),
        {"vcg_source_run_id": 0, "label_version": 0},
    ),
    (TechnicalLiveRepository, "fetch", ("ZZZZ",), {}),
    (TechnicalVwapAnchorRepository, "get", ("ZZZZ",), {}),
    (TechnicalsRepository, "fetch_latest", ("ZZZZ",), {}),
    (TopNetImpactRepository, "fetch_latest", (), {}),
    (TradeInsightOutcomeRepository, "fetch_pending", (), {"limit": 1}),
    (UwFetchMemoRepository, "get", ("ZZZZ", "endpoint", date(2026, 1, 1)), {}),
    (
        UwHistoricalAlphaRepository,
        "upsert_gex_levels",
        ([{"ticker": "ZZZZ", "market_date": date(2026, 1, 1)}],),
        {},
    ),
    (VcgSnapshotRepository, "fetch_latest", (), {}),
    (VolIndexRepository, "latest_date_for", ("VIX",), {}),
]


@pytest.mark.parametrize(
    ("cls", "method", "args", "kwargs"),
    _CASES,
    ids=[cls.__name__ for cls, *_ in _CASES],
)
def test_repo_leaves_caller_search_path(
    seeded_db_empty_cards, cls, method, args, kwargs
) -> None:
    conn = seeded_db_empty_cards.conn
    with conn.cursor() as cur:
        cur.execute("SET search_path TO public")

    repo = cls(conn, schema="uw_scan")
    getattr(repo, method)(*args, **kwargs)

    with conn.cursor() as cur:
        cur.execute("SHOW search_path")
        assert cur.fetchone()[0] == "public"
