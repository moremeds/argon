"""High-level UW fetchers: API call → persist raw + audit → return typed model.

Each fetcher writes the audit row and the compressed payload BEFORE returning.
On normalizer failure raises `NormalizationError` (no silent skipping).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from .. import normalize
from ..api.client import UwClient
from ..api.endpoints import EndpointSlug, build_path
from ..models import (
    BulkScreenerRow,
    DarkPoolPrint,
    EtfInfo,
    EtfInOutflowRow,
    FlowAlert,
    GreekExposureByExpiryRow,
    GreekExposureRow,
    GreeksRow,
    InterpolatedIvRow,
    IvRankRow,
    MaxPainRow,
    OiChangeRow,
    OiPerStrikeRow,
    OptionContractIntradayBucket,
    OptionContractRow,
    OptionsDailyRow,
    RealizedVolRow,
    ShortDataRow,
    SkewRow,
    SpotExposureRow,
    TermStructureRow,
    VolStatsRow,
)
from ..storage.repository import Repository

logger = logging.getLogger(__name__)


def _persist_audit(
    repo: Repository,
    run_id: int,
    slug: EndpointSlug,
    path: str,
    params: dict[str, Any],
    status_code: int,
    started: datetime,
    finished: datetime,
    client: UwClient,
    body: Any,
    error: str | None = None,
) -> None:
    audit_id = repo.insert_audit_row(
        run_id=run_id,
        endpoint_slug=str(slug),
        endpoint_path=path,
        params=params,
        status_code=status_code,
        started_at=started,
        finished_at=finished,
        daily_req_count=client.rate_limit.daily_count,
        minute_req_remaining=client.rate_limit.minute_remaining,
        minute_req_reset=client.rate_limit.minute_reset,
        error_message=error,
    )
    payload = body if isinstance(body, (dict, list)) else {"_raw_text": str(body)}
    repo.insert_raw_payload(audit_id, payload)


def _fetch_json(
    client: UwClient,
    repo: Repository,
    run_id: int,
    slug: EndpointSlug,
    ticker: str | None,
    params: dict[str, Any] | None = None,
    *,
    option_symbol: str | None = None,
) -> dict:
    path = build_path(slug, ticker, option_symbol=option_symbol)
    started = datetime.now(UTC)
    resp, _hdrs = client.get(
        slug,
        ticker=ticker,
        params=params,
        run_id=run_id,
        option_symbol=option_symbol,
    )
    finished = datetime.now(UTC)
    body = resp.json()
    _persist_audit(
        repo,
        run_id,
        slug,
        path,
        params or {},
        resp.status_code,
        started,
        finished,
        client,
        body,
    )
    return body


# ---------------------------------------------------------------------------
# Fetchers — one per endpoint slug
# ---------------------------------------------------------------------------
def fetch_flow_alerts(
    client: UwClient, repo: Repository, run_id: int, ticker: str, limit: int = 100
) -> list[FlowAlert]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.FLOW_ALERTS,
        None,
        params={"ticker_symbol": ticker, "limit": limit},
    )
    return normalize.normalize_flow_alerts(body)


def fetch_market_flow_alerts(
    client: UwClient, repo: Repository, run_id: int, limit: int = 200
) -> list[FlowAlert]:
    """Market-wide flow alerts (no ticker filter) for the scanner's discovery feed.

    Same endpoint and audit path as fetch_flow_alerts, but omits ticker_symbol so
    UW returns alerts across the whole market. Each FlowAlert carries its own
    ticker — discovery groups by it.
    """
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.FLOW_ALERTS,
        None,
        params={"limit": limit},
    )
    return normalize.normalize_flow_alerts(body)


def fetch_iv_rank(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[IvRankRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.IV_RANK, ticker)
    return normalize.normalize_iv_rank(body)


def fetch_volatility_stats(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[VolStatsRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.VOLATILITY_STATS, ticker)
    return normalize.normalize_volatility_stats(body)


def fetch_realized_volatility(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[RealizedVolRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.REALIZED_VOLATILITY, ticker)
    return normalize.normalize_realized_volatility(body)


def fetch_term_structure(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[TermStructureRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.TERM_STRUCTURE, ticker)
    return normalize.normalize_term_structure(body)


def fetch_interpolated_iv(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[InterpolatedIvRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.INTERPOLATED_IV, ticker)
    return normalize.normalize_interpolated_iv(body)


def fetch_skew(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    expiry: str,
    delta: int = 25,
) -> list[SkewRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.SKEW,
        ticker,
        params={"expiry": expiry, "delta": delta},
    )
    return normalize.normalize_skew(body, expiry_hint=expiry)


def fetch_greek_exposure(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    expiry: str,
) -> list[GreekExposureRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE,
        ticker,
        params={"expiry": expiry},
    )
    return normalize.normalize_greek_exposure(body)


def fetch_greek_exposure_by_expiry(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    date: str | None = None,
) -> list[GreekExposureByExpiryRow]:
    """Fetch /api/stock/{ticker}/greek-exposure/expiry — all expiries in one call.

    Per-expiry aggregates across all strikes (call_vanna, put_vanna, call_charm,
    put_charm, call_delta, put_delta, call_gex, put_gex, dte). No strike-level
    granularity. Used to populate the multi-expiry Vanna/Charm dropdown without
    incurring N × greek-exposure/strike-expiry calls.
    """
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE_BY_EXPIRY,
        ticker,
        params={"date": date} if date is not None else None,
    )
    return normalize.normalize_greek_exposure_by_expiry(body)


def fetch_greek_exposure_by_strike(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> dict:
    """Fetch /api/stock/{ticker}/greek-exposure/strike — aggregated per-strike GEX.

    Returns the raw body; scanner consumes ``body["data"]`` as a list of rows
    with string-valued ``strike``, ``call_gex``, ``put_gex``, ``call_delta``,
    ``put_delta`` fields (caller does ``float()`` casting).
    """
    return _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE_BY_STRIKE,
        ticker,
    )


def fetch_greek_exposure_history(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    *,
    timeframe: str | None = None,
) -> dict:
    """Fetch /api/stock/{ticker}/greek-exposure — aggregate GEX over time.

    Used for net_dex computation and (eventually) historical bias trend.

    ``timeframe`` is the optional UW window selector ("YTD", "1Y", "2M", …).
    Default (None) keeps UW's ~90-session default — that's what ``gex.py``
    relies on. The GRG scanner passes "1Y" so its z-window is fully warmed
    before the YTD display window.
    """
    params = {"timeframe": timeframe} if timeframe else None
    return _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE_HISTORY,
        ticker,
        params=params,
    )


def fetch_stock_state(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> dict:
    """Fetch /api/stock/{ticker}/stock-state — last trade snapshot.

    Returns the body envelope; ``body["data"]`` carries
    ``close, prev_close, open, high, low, volume, total_volume, market_time, tape_time``.

    Works uniformly for indices (SPX) and ETFs (SPY/QQQ/IWM). For SPX,
    ``volume`` and ``total_volume`` are 0 by design (indices don't trade), and
    ``market_time`` stays "regular" past 16:00 ET because SPX has no postmarket
    — use ``tape_time`` to judge freshness, not ``market_time``.
    """
    return _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.STOCK_STATE,
        ticker,
    )


def fetch_spot_exposures(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    expiry: str,
) -> list[SpotExposureRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.SPOT_EXPOSURES,
        ticker,
        params={"expirations[]": [expiry]},
    )
    return normalize.normalize_spot_exposures(body)


def fetch_greeks(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    expiry: str,
    date: str | None = None,
) -> list[GreeksRow]:
    params: dict[str, Any] = {"expiry": expiry}
    if date is not None:
        params["date"] = date
    body = _fetch_json(client, repo, run_id, EndpointSlug.GREEKS, ticker, params=params)
    return normalize.normalize_greeks(body)


def fetch_oi_per_strike(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[OiPerStrikeRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.OI_PER_STRIKE, ticker)
    return normalize.normalize_oi_per_strike(body)


def fetch_oi_change(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[OiChangeRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.OI_CHANGE, ticker)
    return normalize.normalize_oi_change(body)


def fetch_max_pain(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[MaxPainRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.MAX_PAIN, ticker)
    return normalize.normalize_max_pain(body)


def fetch_option_contracts(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    limit: int = 500,
) -> list[OptionContractRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTION_CONTRACTS,
        ticker,
        params={"limit": limit},
    )
    return normalize.normalize_option_contracts(body)


def fetch_option_contracts_by_symbol(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    option_symbols: list[str],
) -> list[OptionContractRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTION_CONTRACTS_BY_SYMBOL,
        ticker,
        params={"option_symbol[]": option_symbols},
    )
    return normalize.normalize_option_contracts_by_symbol(body)


def fetch_option_contracts_by_expiry(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    expiry: str,
) -> list[OptionContractRow]:
    """Full option-contract chain for one expiry (``expiry`` = YYYY-MM-DD).

    Uncapped for a single expiry (SPX ~270 rows < the 500 ticker-level cap that
    bites the unfiltered list). Carries NBBO (nbbo_bid/nbbo_ask) + implied_volatility
    per strike but NOT per-contract greeks — those are BS-computed downstream from
    the marked IV. Strike + expiry parse from each row's OCC ``option_symbol``.
    Used by the VRP macro entry-capture job for strike discovery + the UW NBBO
    fallback (xenon/IB is the NBBO of record).
    """
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTION_CONTRACTS,
        ticker,
        params={"expiry": expiry},
    )
    return normalize.normalize_option_contracts(body)


def fetch_option_contract_intraday(
    client: UwClient,
    repo: Repository,
    run_id: int,
    option_symbol: str,
    date: str,
) -> list[OptionContractIntradayBucket]:
    """Per-minute intraday bars for a single option contract on a given date.

    UW's OI delta is daily (premarket-published); this endpoint is the only
    way to see when the volume that built that OI actually printed.
    """
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTION_CONTRACT_INTRADAY,
        None,
        params={"date": date},
        option_symbol=option_symbol,
    )
    return normalize.normalize_option_contract_intraday(body)


def fetch_options_volume_daily(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    limit: int = 200,
) -> list[OptionsDailyRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTIONS_VOLUME_DAILY,
        ticker,
        params={"limit": limit},
    )
    return normalize.normalize_options_volume_daily(body)


def fetch_darkpool_ticker(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[DarkPoolPrint]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.DARKPOOL_TICKER, ticker)
    return normalize.normalize_darkpool_ticker(body)


def fetch_short_data(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[ShortDataRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.SHORT_DATA, ticker)
    return normalize.normalize_short_data(body)


def fetch_bulk_screener(
    client: UwClient,
    repo: Repository,
    run_id: int,
    **params: Any,
) -> list[BulkScreenerRow]:
    """Fetch `/api/screener/stocks`. Persists raw + audit. Returns typed rows.

    Default params: `is_s_p_500=true`, `limit=100` (matches saved S0 sample).
    Caller can override via kwargs.
    """
    if "is_s_p_500" not in params:
        params["is_s_p_500"] = "true"
    if "limit" not in params:
        params["limit"] = 100
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.BULK_SCREENER_STOCKS,
        None,
        params=params,
    )
    return normalize.normalize_bulk_screener(body)


def fetch_bulk_screener_ticker(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> BulkScreenerRow | None:
    """Fetch one row from `/api/screener/stocks` scoped to a single ticker.

    Thin wrapper over `fetch_bulk_screener` — inherits audit / raw payload
    persistence and the canonical normalize path. Returns `None` when the
    screener has no row for the ticker.

    Calls the lower-level _fetch_json directly to avoid `fetch_bulk_screener`'s
    `is_s_p_500=true` default, which would filter out everything except the 500.
    The opposite default (`is_s_p_500=false`) is just as wrong — it filters out
    S&P 500 names like AAPL/MSFT/NVDA. We want the ticker either way.
    """
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.BULK_SCREENER_STOCKS,
        None,
        params={"ticker": ticker, "limit": 1},
    )
    rows = normalize.normalize_bulk_screener(body)
    return rows[0] if rows else None


def fetch_etf_info(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> EtfInfo:
    body = _fetch_json(client, repo, run_id, EndpointSlug.ETF_INFO, ticker)
    return normalize.normalize_etf_info(body)


def fetch_etf_in_outflow(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    *,
    start_date: str,
    end_date: str,
) -> list[EtfInOutflowRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.ETF_IN_OUTFLOW,
        ticker,
        params={"start_date": start_date, "end_date": end_date},
    )
    return normalize.normalize_etf_in_outflow(body, ticker=ticker)


# ---------------------------------------------------------------------------
# Positioning fetchers (M4 trade-framework) — each returns an aggregated dict
# keyed to uw_positioning columns. See normalize.py + storage/positioning.py.
# ---------------------------------------------------------------------------
def fetch_short_interest_float(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> dict:
    body = _fetch_json(client, repo, run_id, EndpointSlug.SHORT_INTEREST_FLOAT, ticker)
    return normalize.normalize_short_interest_float(body)


def fetch_analyst_ratings(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> dict:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.ANALYST_RATINGS,
        None,
        params={"ticker": ticker},
    )
    return normalize.normalize_analyst_ratings(body)


def fetch_institution_ownership(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> dict:
    body = _fetch_json(client, repo, run_id, EndpointSlug.INSTITUTION_OWNERSHIP, ticker)
    return normalize.normalize_institution_ownership(body)


def fetch_insider_ticker_flow(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> dict:
    body = _fetch_json(client, repo, run_id, EndpointSlug.INSIDER_TICKER_FLOW, ticker)
    return normalize.normalize_insider_ticker_flow(body)


def fetch_earnings_history(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> dict:
    body = _fetch_json(client, repo, run_id, EndpointSlug.EARNINGS, ticker)
    return normalize.normalize_earnings_history(body)
