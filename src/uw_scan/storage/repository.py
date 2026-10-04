"""Persistence layer: thin wrapper around psycopg cursors.

One method per insert/select. No `**kwargs` splatting from arbitrary dicts.
"""

from __future__ import annotations

from ._base import _BaseMixin
from .audit import _AuditMixin
from .cockpit import _CockpitMixin
from .corporate_actions import _CorporateActionsMixin
from .external_api import _ExternalApiMixin
from .fetchers import _FetchersMixin
from .flow import _FlowMixin
from .fundamentals import _FundamentalsMixin
from .gex import _GexMixin
from .gold import _GoldMixin
from .gold_etf import _GoldEtfMixin
from .health import _HealthMixin
from .jobs import _JobsMixin
from .macro_context import _MacroContextMixin
from .macro_context_snapshot import _MacroContextSnapshotMixin
from .macro_domain_state import _MacroDomainStateMixin
from .macro_policy_observations import _MacroPolicyObservationMixin
from .macro_release_status import _MacroReleaseStatusMixin
from .macro_series_observations import _MacroSeriesObservationMixin
from .market_data import _MarketDataMixin
from .matrix_state import _MatrixStateMixin
from .option_surface import _OptionSurfaceMixin
from .options import _OptionsMixin
from .pipeline_benchmark import _PipelineBenchmarkMixin
from .positioning import _PositioningMixin
from .rates_repository import _RatesMixin
from .scan_outputs import _ScanOutputsMixin
from .scan_results import _ScanResultsMixin
from .scan_runs import _ScanRunsMixin
from .skew import _SkewMixin
from .trade_insights_ai import _TradeInsightsAiMixin
from .volatility_raw import _VolatilityRawMixin
from .volatility_v2 import _VolatilityV2Mixin
from .vrp_macro_entry import _VrpMacroEntryMixin
from .vrp_macro_signal import _VrpMacroSignalMixin
from .vrp_markout import _VrpMarkoutMixin
from .vrp_research import _VrpResearchMixin
from .vrp_trading import _VrpTradingMixin
from .watchlist import _WatchlistMixin
from .ws_consumer_state import _WsConsumerStateMixin

__all__ = ["Repository"]


class Repository(
    _AuditMixin,
    _CockpitMixin,
    _CorporateActionsMixin,
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
    _MacroContextMixin,
    _MacroContextSnapshotMixin,
    _MacroDomainStateMixin,
    _MacroPolicyObservationMixin,
    _MacroSeriesObservationMixin,
    _MacroReleaseStatusMixin,
    _MatrixStateMixin,
    _OptionSurfaceMixin,
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
    _VrpMacroEntryMixin,
    _VrpMacroSignalMixin,
    _VrpMarkoutMixin,
    _VrpResearchMixin,
    _VrpTradingMixin,
    _WatchlistMixin,
    _WsConsumerStateMixin,
    _BaseMixin,
):
    """Repository wraps a psycopg connection and exposes typed CRUD.

    Per-domain persistence methods live on mixins. _BaseMixin stays last in
    the MRO because it owns __init__ and the conn property.
    """
