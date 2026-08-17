"""High-level UW fetchers: API call → persist raw + audit → return typed model.

Each fetcher writes the audit row and the compressed payload BEFORE returning.
On normalizer failure raises `NormalizationError` (no silent skipping).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from .. import normalize
from ..api.client import UwClient, UwHTTPError
from ..api.endpoints import EndpointSlug, build_path
from ..models import (
    BulkScreenerRow,
    DarkLitPrint,
    DarkPoolPrint,
    EtfInfo,
    EtfInOutflowRow,
    FlowAlert,
    FtdRow,
    GexLevelsRow,
    GreekExposureByExpiryRow,
    GreekExposureRow,
    GreekFlowRow,
    GreeksRow,
    InterpolatedIvRow,
    IvRankRow,
    MaxPainRow,
    NetPremTickRow,
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
    VolAnomalyRow,
    VolCharacterRow,
    VolStatsRow,
    VolumesByExchangeRow,
    VolVrpRow,
)
from ..storage.repository import Repository
from ..storage.uw_fetch_memo import UwFetchMemoRepository

# Alias for signatures that already bind a parameter named `date` (the UW
# string form) and still need the datetime.date type for `market_date`.
_date_type = date

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# Stable per-fetcher memo labels. NOT the raw endpoint slug: fetch_option_contracts
# and fetch_option_contracts_by_expiry share the OPTION_CONTRACTS slug but return
# different-shaped data, so the memo must distinguish them by caller intent.
_MEMO_OPTION_CONTRACTS = "option_contracts"
_MEMO_GREEK_EXPOSURE_BY_EXPIRY = "greek_exposure_by_expiry"


def _memoized_fetch_json(
    client: UwClient,
    repo: Repository,
    run_id: int,
    slug: EndpointSlug,
    ticker: str,
    params: dict[str, Any] | None,
    *,
    endpoint_label: str,
    force_refresh: bool,
) -> dict:
    """Same-day dedupe wrapper around `_fetch_json` (issue #225).

    Consults the `(ticker, endpoint_label, ET-today)` memo BEFORE the live call.
    A HIT reuses the stored payload (a budget SAVE, recorded on the memo row);
    a MISS spends budget then stores the payload for later same-day callers.
    `force_refresh=True` bypasses the read but still refreshes the stored row.
    """
    as_of = datetime.now(_ET).date()
    memo = UwFetchMemoRepository(repo.conn, schema=repo._schema)
    if not force_refresh:
        cached = memo.get(ticker, endpoint_label, as_of)
        if cached is not None:
            logger.info(
                "uw_fetch_memo HIT %s/%s %s — budget SAVE (no UW spend)",
                ticker,
                endpoint_label,
                as_of.isoformat(),
            )
            return cached
    body = _fetch_json(client, repo, run_id, slug, ticker, params=params)
    memo.put(ticker, endpoint_label, as_of, body)
    return body


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
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[IvRankRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.IV_RANK, ticker, params=params)
    return normalize.normalize_iv_rank(body)


def fetch_volatility_stats(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[VolStatsRow]:
    # /volatility/stats is a historical-selector: ?date=YYYY-MM-DD returns the
    # stats AS OF that session (one row). Omitting it returns the current row
    # (the nightly path). The gap healer passes market_date to backfill history.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(
        client, repo, run_id, EndpointSlug.VOLATILITY_STATS, ticker, params=params
    )
    return normalize.normalize_volatility_stats(body)


def fetch_realized_volatility(
    client: UwClient, repo: Repository, run_id: int, ticker: str
) -> list[RealizedVolRow]:
    body = _fetch_json(client, repo, run_id, EndpointSlug.REALIZED_VOLATILITY, ticker)
    return normalize.normalize_realized_volatility(body)


def fetch_term_structure(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[TermStructureRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.TERM_STRUCTURE, ticker, params=params)
    return normalize.normalize_term_structure(body)


def fetch_interpolated_iv(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[InterpolatedIvRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.INTERPOLATED_IV, ticker, params=params)
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
    market_date: date | None = None,
) -> list[GreekExposureRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params: dict[str, Any] = {"expiry": expiry}
    if market_date is not None:
        params["date"] = market_date.isoformat()
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE,
        ticker,
        params=params,
    )
    return normalize.normalize_greek_exposure(body)


def fetch_greek_exposure_by_expiry(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    date: str | None = None,
    *,
    force_refresh: bool = False,
    market_date: _date_type | None = None,
) -> list[GreekExposureByExpiryRow]:
    """Fetch /api/stock/{ticker}/greek-exposure/expiry — all expiries in one call.

    Per-expiry aggregates across all strikes (call_vanna, put_vanna, call_charm,
    put_charm, call_delta, put_delta, call_gex, put_gex, dte). No strike-level
    granularity. Used to populate the multi-expiry Vanna/Charm dropdown without
    incurring N × greek-exposure/strike-expiry calls.

    The current-day path (`date is None`) is same-day memoized (issue #225) —
    several jobs re-fetch this identical per-ticker aggregate each day. An
    explicit historical `date` selector bypasses the memo (it targets a specific
    past session, not today's slow-moving snapshot). `force_refresh=True` forces
    a fresh UW call on the current-day path.
    """
    if date is not None:
        body = _fetch_json(
            client,
            repo,
            run_id,
            EndpointSlug.GREEK_EXPOSURE_BY_EXPIRY,
            ticker,
            params={"date": date},
        )
        return normalize.normalize_greek_exposure_by_expiry(body)
    # A same-day memo and a historical replay are incompatible: the memo keys on
    # (ticker, endpoint, ET-today), so under replay a HIT would hand back TODAY's
    # payload to be stamped with a past date, and a MISS would store the HISTORICAL
    # payload under today's key and poison the live nightly path. Replay therefore
    # bypasses the memo entirely — it neither reads nor writes it.
    if market_date is not None:
        body = _fetch_json(
            client,
            repo,
            run_id,
            EndpointSlug.GREEK_EXPOSURE_BY_EXPIRY,
            ticker,
            params={"date": market_date.isoformat()},
        )
        return normalize.normalize_greek_exposure_by_expiry(body)
    body = _memoized_fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_EXPOSURE_BY_EXPIRY,
        ticker,
        None,
        endpoint_label=_MEMO_GREEK_EXPOSURE_BY_EXPIRY,
        force_refresh=force_refresh,
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
    market_date: date | None = None,
) -> list[SpotExposureRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params: dict[str, Any] = {"expirations[]": [expiry]}
    if market_date is not None:
        params["date"] = market_date.isoformat()
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.SPOT_EXPOSURES,
        ticker,
        params=params,
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
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[OiPerStrikeRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.OI_PER_STRIKE, ticker, params=params)
    return normalize.normalize_oi_per_strike(body)


def fetch_oi_change(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[OiChangeRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.OI_CHANGE, ticker, params=params)
    return normalize.normalize_oi_change(body)


def fetch_max_pain(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[MaxPainRow]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.MAX_PAIN, ticker, params=params)
    return normalize.normalize_max_pain(body)


def fetch_option_contracts(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    limit: int = 500,
    *,
    force_refresh: bool = False,
    market_date: date | None = None,
) -> list[OptionContractRow]:
    # Slow-moving ticker-level chain — same-day memoized (issue #225). Multiple
    # jobs re-fetch this identical list per day; the first spends budget, the
    # rest reuse it. `force_refresh=True` forces a fresh UW call.
    # A same-day memo and a historical replay are incompatible: the memo keys on
    # (ticker, endpoint, ET-today), so under replay a HIT would hand back TODAY's
    # payload to be stamped with a past date, and a MISS would store the HISTORICAL
    # payload under today's key and poison the live nightly path. Replay therefore
    # bypasses the memo entirely — it neither reads nor writes it.
    if market_date is not None:
        body = _fetch_json(
            client,
            repo,
            run_id,
            EndpointSlug.OPTION_CONTRACTS,
            ticker,
            params={"limit": limit, "date": market_date.isoformat()},
        )
        return normalize.normalize_option_contracts(body)
    body = _memoized_fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.OPTION_CONTRACTS,
        ticker,
        {"limit": limit},
        endpoint_label=_MEMO_OPTION_CONTRACTS,
        force_refresh=force_refresh,
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
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[DarkPoolPrint]:
    # market_date replays a past session; measured to be honoured 2026-08-16
    # (docs/research/2026-08-16-replay-endpoint-matrix.md). None = live path.
    params = {"date": market_date.isoformat()} if market_date is not None else None
    body = _fetch_json(client, repo, run_id, EndpointSlug.DARKPOOL_TICKER, ticker, params=params)
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
    market_date: date | None = None,
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
    params: dict[str, Any] = {"ticker": ticker, "limit": 1}
    if market_date is not None:
        params["date"] = market_date.isoformat()
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.BULK_SCREENER_STOCKS,
        None,
        params=params,
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


def fetch_market_tide(
    client: UwClient,
    repo: Repository,
    run_id: int,
    trading_date: date | None = None,
) -> list[dict]:
    """Market-wide 5-min options tide for one session (defaults to today).

    Returns the full intraday series in a single call — 81-82 bars 09:30→16:10
    ET for a complete RTH session. Each parsed bar carries the UW bar timestamp,
    the session date, and the net call/put premium + net volume for that bucket.
    Raises NormalizationError on a missing field rather than silently skipping a
    bar (the chart/backfill must know if UW changed shape).
    """
    params: dict[str, Any] = {}
    if trading_date is not None:
        params["date"] = trading_date.isoformat()
    try:
        body = _fetch_json(
            client, repo, run_id, EndpointSlug.MARKET_TIDE, None, params=params or None
        )
    except UwHTTPError as exc:
        # No usable data for this date — not an error: 400 = pre-open / not yet
        # published; 422 = future EST date (a backfill walking from "today" hits
        # this when it's still that day in ET). Skip either. Telemetry already
        # recorded the response.
        if exc.status_code in (400, 422):
            logger.info(
                "market-tide: %d (no data) date=%s", exc.status_code, trading_date
            )
            return []
        raise
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise normalize.NormalizationError(
            f"market-tide: expected 'data' list, got {type(rows).__name__}"
        )
    out: list[dict] = []
    for r in rows:
        try:
            out.append(
                {
                    "ts": datetime.fromisoformat(r["timestamp"]),
                    "data_date": date.fromisoformat(r["date"]),
                    "net_call_premium": Decimal(str(r["net_call_premium"])),
                    "net_put_premium": Decimal(str(r["net_put_premium"])),
                    "net_volume": (
                        int(r["net_volume"])
                        if r.get("net_volume") is not None
                        else None
                    ),
                }
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise normalize.NormalizationError(
                f"market-tide: malformed bar {r!r}"
            ) from exc
    return out


def fetch_top_net_impact(
    client: UwClient,
    repo: Repository,
    run_id: int,
    trading_date: date | None = None,
    limit: int = 40,
) -> list[dict]:
    """Market-wide ranking of tickers by net option premium for one session.

    `net_premium` = net_call_premium - net_put_premium (cumulative for the day).
    UW returns the top bullish + bearish tickers; we keep the full list and let
    the caller assign ranks. One call covers the whole market. Raises
    NormalizationError on a missing field rather than silently skipping.
    """
    params: dict[str, Any] = {"limit": limit}
    if trading_date is not None:
        params["date"] = trading_date.isoformat()
    try:
        body = _fetch_json(
            client, repo, run_id, EndpointSlug.TOP_NET_IMPACT, None, params=params
        )
    except UwHTTPError as exc:
        # 400 = not yet published; 422 = future EST date. Either → no data.
        if exc.status_code in (400, 422):
            logger.info(
                "top-net-impact: %d (no data) date=%s", exc.status_code, trading_date
            )
            return []
        raise
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise normalize.NormalizationError(
            f"top-net-impact: expected 'data' list, got {type(rows).__name__}"
        )
    out: list[dict] = []
    for r in rows:
        try:
            out.append(
                {
                    "ticker": str(r["ticker"]).upper(),
                    "net_premium": Decimal(str(r["net_premium"])),
                }
            )
        except (KeyError, ValueError, TypeError, InvalidOperation) as exc:
            raise normalize.NormalizationError(
                f"top-net-impact: malformed row {r!r}"
            ) from exc
    return out


# --------------------------------------------------------------------------- #
# UW historical-alpha fetchers. gex-levels / volatility / net-prem / greek-flow
# honor ?date= (as-of); interest-float / ftds / volumes-by-exchange ignore it and
# return full/rolling history (the capture layer selects the as-of row). Not
# memoized — past-date history is not a slow-moving same-day snapshot.
# --------------------------------------------------------------------------- #
def _date_params(market_date: date | None, **extra: Any) -> dict[str, Any] | None:
    params: dict[str, Any] = dict(extra)
    if market_date is not None:
        params["date"] = market_date.isoformat()
    return params or None


def fetch_gex_levels(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> GexLevelsRow | None:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GEX_LEVELS,
        ticker,
        params=_date_params(market_date),
    )
    md = market_date or datetime.now(_ET).date()
    return normalize.normalize_gex_levels(body, ticker, md)


def fetch_volatility_anomaly(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[VolAnomalyRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.VOLATILITY_ANOMALY,
        ticker,
        params=_date_params(market_date),
    )
    return normalize.normalize_vol_anomaly(body)


def fetch_volatility_character(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[VolCharacterRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.VOLATILITY_CHARACTER,
        ticker,
        params=_date_params(market_date),
    )
    return normalize.normalize_vol_character(body)


def fetch_volatility_vrp(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[VolVrpRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.VOLATILITY_VRP,
        ticker,
        params=_date_params(market_date),
    )
    return normalize.normalize_vol_vrp(body)


def fetch_net_prem_ticks(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
    limit: int = 500,
) -> list[NetPremTickRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.NET_PREM_TICKS,
        ticker,
        params=_date_params(market_date, limit=limit),
    )
    return normalize.normalize_net_prem_ticks(body)


def fetch_greek_flow(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
) -> list[GreekFlowRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEK_FLOW,
        ticker,
        params=_date_params(market_date),
    )
    return normalize.normalize_greek_flow(body)


def fetch_lit_flow(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
    limit: int = 500,
) -> list[DarkLitPrint]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.LIT_FLOW,
        ticker,
        params=_date_params(market_date, limit=limit),
    )
    return normalize.normalize_dark_lit(body)


def fetch_darkpool_prints(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: date | None = None,
    limit: int = 500,
) -> list[DarkLitPrint]:
    # New fetcher: the existing fetch_darkpool_ticker sends neither date nor limit,
    # so it can't backfill history. Same DARKPOOL_TICKER slug, with selectors.
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.DARKPOOL_TICKER,
        ticker,
        params=_date_params(market_date, limit=limit),
    )
    return normalize.normalize_dark_lit(body)


def fetch_ftds(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> list[FtdRow]:
    # ?date= is ignored; returns full FTD history. The capture selects the row.
    body = _fetch_json(client, repo, run_id, EndpointSlug.FTDS, ticker)
    return normalize.normalize_ftds(body)


def fetch_volumes_by_exchange(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> list[VolumesByExchangeRow]:
    # ?date= is ignored; returns a rolling per-exchange window. The capture
    # aggregates the rows for the target date.
    body = _fetch_json(client, repo, run_id, EndpointSlug.VOLUMES_BY_EXCHANGE, ticker)
    return normalize.normalize_volumes_by_exchange(body)


def fetch_short_interest_history(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
) -> list[dict]:
    """Full dated interest-float history (raw dicts, most-recent-first).

    Distinct from fetch_short_interest_float, which returns only the LATEST
    snapshot: the short-pressure capture selects the as-of row for the target
    market_date (the endpoint ignores ?date= and always returns full history),
    so stamping an old date with the latest short interest is avoided.
    """
    body = _fetch_json(client, repo, run_id, EndpointSlug.SHORT_INTEREST_FLOAT, ticker)
    rows = body.get("data")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
