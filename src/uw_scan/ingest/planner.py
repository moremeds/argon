from __future__ import annotations

from dataclasses import dataclass

from uw_scan.config import UwScanConfig


@dataclass(frozen=True)
class SourceCandidate:
    ticker: str
    option_symbol: str | None
    source_label: str


@dataclass(frozen=True)
class PlannedCall:
    tier: str
    endpoint_name: str
    ticker: str | None = None
    option_symbol: str | None = None
    expiry: str | None = None


@dataclass(frozen=True)
class CallPlan:
    market_date: str
    unique_tickers: list[str]
    unique_option_symbols: list[str]
    calls: list[PlannedCall]
    total_requests: int
    truncated: bool


def build_call_plan(
    candidates: list[SourceCandidate],
    *,
    market_date: str,
    config: UwScanConfig,
    important_expiries_by_ticker: dict[str, list[str]] | None = None,
) -> CallPlan:
    tickers = sorted({candidate.ticker.upper() for candidate in candidates})
    contract_tickers = {
        candidate.option_symbol: candidate.ticker.upper()
        for candidate in candidates
        if candidate.option_symbol
    }
    option_symbols = sorted(contract_tickers)
    important_expiries = {
        ticker.upper(): expiries[: config.max_expiries_per_ticker]
        for ticker, expiries in (important_expiries_by_ticker or {}).items()
    }
    calls: list[PlannedCall] = [
        PlannedCall(tier="discovery", endpoint_name="flow_alerts"),
        PlannedCall(tier="discovery", endpoint_name="tradingview_import"),
    ]
    for symbol in option_symbols:
        calls.append(
            PlannedCall(
                tier="tracking",
                endpoint_name="option_contracts",
                ticker=contract_tickers[symbol],
                option_symbol=symbol,
            )
        )
    for ticker in tickers[: config.max_watchlist_tickers]:
        calls.extend(
            [
                PlannedCall(tier="enrichment", endpoint_name="option_chains", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="option_contracts", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="oi_change", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="oi_per_expiry", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="oi_per_strike", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="vol_oi_per_expiry", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="max_pain", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="iv_rank", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="volatility_stats", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="interpolated_iv", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="realized_volatility", ticker=ticker),
                PlannedCall(tier="enrichment", endpoint_name="iv_term_structure", ticker=ticker),
            ]
        )
    for ticker in tickers[: config.max_deep_surface_tickers]:
        for expiry in important_expiries.get(ticker, []):
            calls.extend(
                [
                    PlannedCall(tier="deep_surface", endpoint_name="greeks", ticker=ticker, expiry=expiry),
                    PlannedCall(tier="deep_surface", endpoint_name="greek_exposure_by_strike_expiry", ticker=ticker, expiry=expiry),
                    PlannedCall(tier="deep_surface", endpoint_name="spot_exposures_by_strike_expiry", ticker=ticker, expiry=expiry),
                ]
            )
    truncated = len(calls) > config.max_requests_per_cycle
    calls = calls[: config.max_requests_per_cycle]
    return CallPlan(
        market_date=market_date,
        unique_tickers=tickers,
        unique_option_symbols=option_symbols,
        calls=calls,
        total_requests=len(calls),
        truncated=truncated,
    )
