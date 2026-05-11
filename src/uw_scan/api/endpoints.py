from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class EndpointDef:
    operation: str
    path: str
    docs_url: str


class UwEndpoint(Enum):
    FLOW_ALERTS = EndpointDef("flow_alerts", "/api/option-trades/flow-alerts", "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.flow_alerts")
    FULL_TAPE = EndpointDef("full_tape", "/api/option-trades/full-tape/{date}", "https://api.unusualwhales.com/docs/operations/PublicApi.OptionTradeController.full_tape")
    OPTION_CHAINS = EndpointDef("option_chains", "/api/stock/{ticker}/option-chains", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.option_chains")
    OPTION_CONTRACTS = EndpointDef("option_contracts", "/api/stock/{ticker}/option-contracts", "https://api.unusualwhales.com/docs/operations/PublicApi.OptionContractController.option_contracts")
    OI_CHANGE = EndpointDef("oi_change", "/api/stock/{ticker}/oi-change", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_change")
    OI_PER_EXPIRY = EndpointDef("oi_per_expiry", "/api/stock/{ticker}/oi-per-expiry", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_per_expiry")
    OI_PER_STRIKE = EndpointDef("oi_per_strike", "/api/stock/{ticker}/oi-per-strike", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.oi_per_strike")
    VOL_OI_PER_EXPIRY = EndpointDef("vol_oi_per_expiry", "/api/stock/{ticker}/option/volume-oi-expiry", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.vol_oi_per_expiry")
    IV_RANK = EndpointDef("iv_rank", "/api/stock/{ticker}/iv-rank", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.iv_rank")
    VOLATILITY_STATS = EndpointDef("volatility_stats", "/api/stock/{ticker}/volatility/stats", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.volatility_stats")
    INTERPOLATED_IV = EndpointDef("interpolated_iv", "/api/stock/{ticker}/interpolated-iv", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.interpolated_iv")
    REALIZED_VOLATILITY = EndpointDef("realized_volatility", "/api/stock/{ticker}/volatility/realized", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.realized_volatility")
    IV_TERM_STRUCTURE = EndpointDef("iv_term_structure", "/api/stock/{ticker}/volatility/term-structure", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.implied_volatility_term_structure")
    GREEKS = EndpointDef("greeks", "/api/stock/{ticker}/greeks", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greeks")
    GREEK_EXPOSURE_BY_STRIKE_EXPIRY = EndpointDef("greek_exposure_by_strike_expiry", "/api/stock/{ticker}/greek-exposure/strike-expiry", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.greek_exposure_by_strike_expiry")
    SPOT_EXPOSURES_BY_STRIKE_EXPIRY = EndpointDef("spot_exposures_by_strike_expiry", "/api/stock/{ticker}/spot-exposures/expiry-strike", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.spot_exposures_by_strike_expiry_v2")
    MAX_PAIN = EndpointDef("max_pain", "/api/stock/{ticker}/max-pain", "https://api.unusualwhales.com/docs/operations/PublicApi.TickerController.max_pain")
    DARKPOOL_RECENT = EndpointDef("darkpool_recent", "/api/darkpool/recent", "https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.darkpool_recent")
    DARKPOOL_TICKER = EndpointDef("darkpool_ticker", "/api/darkpool/{ticker}", "https://api.unusualwhales.com/docs/operations/PublicApi.DarkpoolController.darkpool_ticker")

    @property
    def operation(self) -> str:
        return self.value.operation

    @property
    def path(self) -> str:
        return self.value.path

    @property
    def docs_url(self) -> str:
        return self.value.docs_url
