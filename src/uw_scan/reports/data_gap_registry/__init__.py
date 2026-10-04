"""The full dataset registry, split by data domain into part files.

``data_gap_healer`` built one module-level ``REGISTRY`` list: a literal of the
core/actively-healed datasets followed by ``extend`` blocks for full coverage
(T7). The parts below are concatenated in exactly that order.
"""

from uw_scan.reports.data_gap_registry.core_watchlist import CORE_WATCHLIST
from uw_scan.reports.data_gap_registry.derived_volatility import DERIVED_VOLATILITY
from uw_scan.reports.data_gap_registry.fundamentals import FUNDAMENTALS
from uw_scan.reports.data_gap_registry.fundamentals_derived import (
    FUNDAMENTALS_DERIVED,
)
from uw_scan.reports.data_gap_registry.gold_rates_macro import GOLD_RATES_MACRO
from uw_scan.reports.data_gap_registry.options_chain import OPTIONS_CHAIN
from uw_scan.reports.data_gap_registry.options_chain_replay import (
    OPTIONS_CHAIN_REPLAY,
)
from uw_scan.reports.data_gap_registry.regime_marketwide import REGIME_MARKETWIDE
from uw_scan.reports.data_gap_registry.research_artifact import RESEARCH_ARTIFACT
from uw_scan.reports.data_gap_registry.state_provenance import STATE_PROVENANCE
from uw_scan.reports.data_gap_types import DatasetRegistryEntry

# Core registry: the actively-healed warm-store datasets + key state tables.
# Group names match the policy buckets in the dataset-policy runbook.
#
# --- full coverage (T7): every remaining temporal table classified -----------
# Strict modes are kept only for tables we actually heal; big un-healable
# per-ticker tables are freshness_only (the data_freshness monitor already
# covers them) to avoid a gap-item explosion. macro/FRED/rates/gold are
# freshness_only for audit but carry a run_once_lookback heal adapter (re-run
# the idempotent ingest over a lookback window).
REGISTRY: list[DatasetRegistryEntry] = [
    *OPTIONS_CHAIN,
    *CORE_WATCHLIST,
    *DERIVED_VOLATILITY,
    *STATE_PROVENANCE,
    *RESEARCH_ARTIFACT,
    *OPTIONS_CHAIN_REPLAY,
    *REGIME_MARKETWIDE,
    *GOLD_RATES_MACRO,
    *FUNDAMENTALS,
    *FUNDAMENTALS_DERIVED,
]
