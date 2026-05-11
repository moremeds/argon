from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from uw_scan.analysis import build_stock_analysis
from uw_scan.api.client import UwApiClient
from uw_scan.api.endpoints import UwEndpoint
from uw_scan.config import UwScanConfig
from uw_scan.fixtures import demo_dashboard
from uw_scan.models import DashboardViewModel, Opportunity, SignalDirection, SnapshotSummary
from uw_scan.request_budget import estimate_request_budget
from uw_scan.scoring import score_flow_candidate
from uw_scan.sources.uw_analysis import build_analysis_inputs_from_payloads
from uw_scan.sources.uw_flow import flow_rows_from_payload
from uw_scan.structures import suggest_structure


@dataclass(frozen=True)
class DashboardNotice:
    level: str
    message: str


def run_fixture_pipeline(config: UwScanConfig) -> DashboardViewModel:
    dashboard = demo_dashboard()
    budget = estimate_request_budget(
        flow_rows=len(dashboard.flow_rows),
        watchlist_symbols=sum(len(source.imported_symbols) for source in dashboard.watchlist_sources),
        deep_surface_tickers=min(len(dashboard.surface_metrics), config.max_deep_surface_tickers),
        important_expiries_per_ticker=1,
        config=config,
    )
    return dashboard.model_copy(update={"request_budget": budget})


def _direction_for_flow(option_type: str, side: str) -> SignalDirection:
    if option_type == "put" and side in {"ask", "buy", "above_ask"}:
        return SignalDirection.BEARISH
    if option_type == "call" and side in {"ask", "buy", "above_ask"}:
        return SignalDirection.BULLISH
    return SignalDirection.NEUTRAL


def _opportunities_from_flow_rows(flow_rows) -> list[Opportunity]:
    opportunities: list[Opportunity] = []
    for row in flow_rows:
        oi = row.open_interest or 0
        ask_side_pct = 0.85 if row.side in {"ask", "buy", "above_ask"} else 0.45
        score = score_flow_candidate(
            volume=row.volume,
            open_interest=row.open_interest,
            ask_side_pct=ask_side_pct,
            premium=float(row.premium),
            is_single_leg=True,
            moneyness_pct=0.08,
            dte=row.dte,
        )
        setup_types = ["Deep Conviction Directional"] if score.score >= 4 else ["Flow Watch"]
        if oi and row.volume > oi:
            setup_types.append("Opening Interest Candidate")
        direction = _direction_for_flow(row.option_type, row.side)
        opportunities.append(
            Opportunity(
                ticker=row.ticker,
                contract_label=f"{row.ticker} {row.expiry.isoformat()} {row.strike}{row.option_type[0].upper()}",
                direction=direction,
                score=score.score,
                setup_types=setup_types,
                confirmations=score.confirmations,
                warnings=score.warnings or ["Next OI update required for opening/closing confirmation"],
                source_labels=[row.source_label],
                structure_idea=suggest_structure(direction=direction, setup_types=setup_types, iv_rank=None),
            )
        )
    return sorted(opportunities, key=lambda item: item.score, reverse=True)


def _endpoint_for_ticker(endpoint: UwEndpoint, ticker: str) -> str:
    return endpoint.path.format(ticker=ticker)


def _fetch_analysis_payloads(client: UwApiClient, *, ticker: str, expiry: str | None, market_date: str) -> dict[str, object]:
    calls = {
        "iv_rank": (_endpoint_for_ticker(UwEndpoint.IV_RANK, ticker), {}),
        "volatility_stats": (_endpoint_for_ticker(UwEndpoint.VOLATILITY_STATS, ticker), {}),
        "term_structure": (_endpoint_for_ticker(UwEndpoint.IV_TERM_STRUCTURE, ticker), {}),
        "greek_exposure": (
            _endpoint_for_ticker(UwEndpoint.GREEK_EXPOSURE_BY_STRIKE_EXPIRY, ticker),
            {"expiry": expiry} if expiry else {},
        ),
        "spot_exposures": (
            _endpoint_for_ticker(UwEndpoint.SPOT_EXPOSURES_BY_STRIKE_EXPIRY, ticker),
            {"expirations[]": [expiry]} if expiry else {},
        ),
        "oi_per_strike": (_endpoint_for_ticker(UwEndpoint.OI_PER_STRIKE, ticker), {}),
        "darkpool": (_endpoint_for_ticker(UwEndpoint.DARKPOOL_TICKER, ticker), {}),
    }
    payloads: dict[str, object] = {}
    for key, (endpoint, params) in calls.items():
        response = client.get(endpoint=endpoint, params=params, market_date=market_date)
        payloads[key] = response.json_payload
    return payloads


def _ranked_tickers_for_analysis(flow_rows, *, limit: int) -> list[str]:
    if not flow_rows:
        return []
    premiums: dict[str, Decimal] = {}
    first_seen: dict[str, int] = {}
    for index, row in enumerate(flow_rows):
        ticker = row.ticker.upper()
        premiums[ticker] = premiums.get(ticker, Decimal("0")) + abs(row.premium)
        first_seen.setdefault(ticker, index)
    ranked = sorted(premiums, key=lambda ticker: (-premiums[ticker], first_seen[ticker], ticker))
    return ranked[: max(1, limit)]


def _first_expiry_for_ticker(flow_rows, ticker: str) -> str | None:
    for row in flow_rows:
        if row.ticker.upper() == ticker.upper():
            return row.expiry.isoformat() if row.expiry else None
    return None


def _stock_analyses_from_live_payloads(client: UwApiClient, flow_rows, market_date: str, *, max_tickers: int):
    analyses = []
    for ticker in _ranked_tickers_for_analysis(flow_rows, limit=max_tickers):
        expiry = _first_expiry_for_ticker(flow_rows, ticker)
        payloads = _fetch_analysis_payloads(client, ticker=ticker, expiry=expiry, market_date=market_date)
        inputs = build_analysis_inputs_from_payloads(
            ticker=ticker,
            flow_rows=flow_rows,
            payloads=payloads,
            data_date=market_date,
        )
        analyses.append(build_stock_analysis(inputs))
    return analyses


def run_live_pipeline(
    config: UwScanConfig,
    *,
    client: UwApiClient | None = None,
) -> tuple[DashboardViewModel, list[DashboardNotice]]:
    if not config.api_key and client is None:
        return run_fixture_pipeline(config), [
            DashboardNotice("warning", "Live polling needs UW_SCAN_API_KEY. Showing analysis fixtures.")
        ]
    client = client or UwApiClient(api_key=config.api_key or "")
    response = client.get(
        endpoint=UwEndpoint.FLOW_ALERTS.path,
        params={"limit": config.max_flow_rows},
        market_date="live",
    )
    flow_rows = flow_rows_from_payload(response.json_payload, source_label="UW Flow Poll", limit=config.max_flow_rows)
    if not flow_rows:
        return run_fixture_pipeline(config), [
            DashboardNotice(
                "warning",
                "UW live request returned no parseable flow rows. Showing analysis fixtures while parser mappings are calibrated.",
            )
        ]
    base = run_fixture_pipeline(config)
    stock_analyses = []
    analysis_notice: DashboardNotice | None = None
    try:
        stock_analyses = _stock_analyses_from_live_payloads(
            client,
            flow_rows,
            market_date="live",
            max_tickers=config.max_analysis_tickers,
        )
    except Exception as exc:
        analysis_notice = DashboardNotice(
            "warning",
            f"Live enrichment failed: {type(exc).__name__}. Showing flow-only opportunities until UW payload mappings are calibrated.",
        )
    budget = estimate_request_budget(
        flow_rows=len(flow_rows),
        watchlist_symbols=sum(len(source.imported_symbols) for source in base.watchlist_sources),
        deep_surface_tickers=min(len({row.ticker for row in flow_rows}), config.max_deep_surface_tickers),
        important_expiries_per_ticker=1,
        config=config,
    )
    dashboard = base.model_copy(
        update={
            "flow_rows": flow_rows,
            "opportunities": _opportunities_from_flow_rows(flow_rows),
            "stock_analyses": stock_analyses,
            "request_budget": budget,
            "snapshots": [
                SnapshotSummary(
                    run_id=response.request_fingerprint[:12],
                    mode="live",
                    started_at_utc=base.generated_at_utc,
                    source_count=1,
                    opportunity_count=len(flow_rows),
                )
            ],
        }
    )
    notices = [DashboardNotice("success", f"Fetched {len(flow_rows)} live UW flow rows.")]
    if analysis_notice:
        notices.append(analysis_notice)
    elif stock_analyses:
        notices.append(DashboardNotice("success", f"Built computed analyses for {len(stock_analyses)} tickers."))
    return dashboard, notices


def dashboard_for_mode(mode: str, config: UwScanConfig) -> tuple[DashboardViewModel, list[DashboardNotice]]:
    if mode == "Live polling" and not config.api_key:
        return run_live_pipeline(config)
    if mode == "Live polling":
        try:
            return run_live_pipeline(config)
        except Exception as exc:  # UI boundary: keep app usable when live integration fails.
            return run_fixture_pipeline(config), [
                DashboardNotice(
                    level="error",
                    message=f"Live UW polling failed: {type(exc).__name__}. Showing analysis fixtures; check credentials, entitlements, and endpoint response shape.",
                )
            ]
    if mode == "Snapshot replay":
        return run_fixture_pipeline(config), [
            DashboardNotice(
                level="info",
                message="Snapshot replay UI is scaffolded, but no saved Postgres snapshot is loaded yet. Showing analysis fixtures.",
            )
        ]
    return run_fixture_pipeline(config), []
