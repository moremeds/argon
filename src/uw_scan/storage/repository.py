"""Persistence layer: thin wrapper around psycopg cursors.

One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
"""

from __future__ import annotations

from ._base import _BaseMixin

# Pure helpers live in _helpers.py since the PR-1 split. provider_day_bounds,
# status_family_for, and redact_params are imported from this module by
# sources/ohlc.py, api/client.py, api/routers/health.py, api/routers/provider_usage.py,
# and tests — keep them re-exported.
from ._helpers import provider_day_bounds, redact_params, status_family_for
from .audit import _AuditMixin
from .cockpit import _CockpitMixin
from .external_api import _ExternalApiMixin
from .fetchers import _FetchersMixin

# noqa: F401 below — _aggressor_label_confidence and _flow_footprint_label
# are re-exports for scripts/backfill_flow_footprint.py which imports them
# from uw_scan.storage.repository. Removing them would break the script.
from .flow import (
    _aggressor_label_confidence,  # noqa: F401
    _flow_footprint_label,  # noqa: F401
    _FlowMixin,
)
from .fundamentals import _FundamentalsMixin
from .gex import _GexMixin
from .gold import _GoldMixin
from .gold_etf import _GoldEtfMixin
from .health import _HealthMixin
from .jobs import _JobsMixin
from .market_data import _MarketDataMixin
from .matrix_state import _MatrixStateMixin
from .options import _OptionsMixin
from .pipeline_benchmark import _PipelineBenchmarkMixin
from .positioning import _PositioningMixin
from .rates_repository import _RatesMixin
from .regime_classification_repository import (  # noqa: F401
    ClassificationRunAlreadyExists,
    RegimeClassificationRepository,
)

# Row dataclasses live in rows.py since the PR-1 split. Re-exported here so
# existing callers (`from uw_scan.storage.repository import JobRow`) continue
# to work without changing import paths.
from .rows import (
    DailyOhlcRow,
    ExternalApiBreakdownRow,
    ExternalApiRequestRow,
    ExternalApiUsageSummary,
    IntradayQuoteRow,
    JobRow,
    PcrHistoryRow,
    PipelineBenchmarkSnapshotRow,
    PipelineScannerFreshnessRow,
    RecordHealthRow,
    RescanQueueSummaryRow,
    ScanDurationSummaryRow,
    ThroughputSummaryRow,
    WatchlistCardRow,
    WatchlistRow,
    WsConsumerStateRow,
)
from .scan_outputs import _ScanOutputsMixin
from .scan_results import _ScanResultsMixin
from .scan_runs import _ScanRunsMixin
from .skew import _SkewMixin
from .trade_insights_ai import _TradeInsightsAiMixin
from .volatility_raw import _VolatilityRawMixin
from .volatility_v2 import _VolatilityV2Mixin
from .watchlist import _WatchlistMixin
from .ws_consumer_state import _WsConsumerStateMixin

__all__ = [
    "Repository",
    "DailyOhlcRow",
    "ExternalApiBreakdownRow",
    "ExternalApiRequestRow",
    "ExternalApiUsageSummary",
    "IntradayQuoteRow",
    "JobRow",
    "PcrHistoryRow",
    "PipelineBenchmarkSnapshotRow",
    "PipelineScannerFreshnessRow",
    "RecordHealthRow",
    "RescanQueueSummaryRow",
    "ScanDurationSummaryRow",
    "ThroughputSummaryRow",
    "WatchlistCardRow",
    "WatchlistRow",
    "WsConsumerStateRow",
    "provider_day_bounds",
    "redact_params",
    "status_family_for",
]


class Repository(
    _AuditMixin,
    _CockpitMixin,
    _ExternalApiMixin,
    _FetchersMixin,
    _FlowMixin,
    _FundamentalsMixin,
    _GexMixin,
    _GoldMixin,
    _GoldEtfMixin,
    _HealthMixin,
    _JobsMixin,
    _MarketDataMixin,
    _MatrixStateMixin,
    _OptionsMixin,
    _PipelineBenchmarkMixin,
    _PositioningMixin,
    _RatesMixin,
    _ScanOutputsMixin,
    _ScanResultsMixin,
    _ScanRunsMixin,
    _SkewMixin,
    _TradeInsightsAiMixin,
    _VolatilityRawMixin,
    _VolatilityV2Mixin,
    _WatchlistMixin,
    _WsConsumerStateMixin,
    _BaseMixin,
):
    """Repository wraps a psycopg connection and exposes typed CRUD.

    Per-domain persistence methods live on mixins. _BaseMixin stays last in
    the MRO because it owns __init__ and the conn property.
    """
