"""High-level UW fetchers: API call → persist raw + audit → return typed model.

Each fetcher writes the audit row and the compressed payload BEFORE returning.
On normalizer failure raises `NormalizationError` (no silent skipping).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .. import normalize
from ..api.client import UwClient, UwHTTPError
from .uw_endpoints import EndpointSlug, build_path
from ..models import (
    BulkScreenerRow,
    EtfInOutflowRow,
    FlowAlert,
    GexLevelsRow,
    GreekExposureByExpiryRow,
    GreekExposureRow,
    GreeksRow,
    OptionContractIntradayBucket,
    OptionContractRow,
    OptionsDailyRow,
    SkewRow,
    SpotExposureRow,
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
    memo = UwFetchMemoRepository(repo.conn, schema=repo.schema)
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
# Uniform fetchers: a table keyed by public function name (I-57). The slug is a
# column, not the key: several slugs back two fetchers (DARKPOOL_TICKER feeds
# fetch_darkpool_ticker and fetch_darkpool_prints). Each family builds the same
# request every old wrapper built by hand; a fetcher that does anything else
# (extra params, memo, a 400/422 policy, a normalizer needing more than the
# body) stays an explicit function below. Return annotations are strings so
# inspect.signature matches the hand-written originals exactly.
# ---------------------------------------------------------------------------
def _date_params(market_date: date | None, **extra: Any) -> dict[str, Any] | None:
    params: dict[str, Any] = dict(extra)
    if market_date is not None:
        params["date"] = market_date.isoformat()
    return params or None


def _raw(body: dict) -> dict:
    return body


def _named(fn: Any, name: str, returns: str, doc: str | None) -> Any:
    fn.__name__ = fn.__qualname__ = name
    fn.__annotations__["return"] = returns
    fn.__doc__ = doc
    return fn


def _ticker_fetcher(
    name: str, slug: EndpointSlug, normalizer: Any, returns: str, doc: str | None = None
) -> Any:
    """(client, repo, run_id, ticker) -> normalizer(body). No params."""

    def fetcher(client: UwClient, repo: Repository, run_id: int, ticker: str):
        return normalizer(_fetch_json(client, repo, run_id, slug, ticker))

    return _named(fetcher, name, returns, doc)


def _ticker_date_fetcher(
    name: str, slug: EndpointSlug, normalizer: Any, returns: str
) -> Any:
    """+ market_date: sends ?date= only when replaying a past session."""

    def fetcher(
        client: UwClient,
        repo: Repository,
        run_id: int,
        ticker: str,
        market_date: date | None = None,
    ):
        body = _fetch_json(
            client, repo, run_id, slug, ticker, params=_date_params(market_date)
        )
        return normalizer(body)

    return _named(fetcher, name, returns, None)


def _ticker_date_limit_fetcher(
    name: str, slug: EndpointSlug, normalizer: Any, returns: str
) -> Any:
    """+ market_date + limit (default 500)."""

    def fetcher(
        client: UwClient,
        repo: Repository,
        run_id: int,
        ticker: str,
        market_date: date | None = None,
        limit: int = 500,
    ):
        body = _fetch_json(
            client,
            repo,
            run_id,
            slug,
            ticker,
            params=_date_params(market_date, limit=limit),
        )
        return normalizer(body)

    return _named(fetcher, name, returns, None)


# fmt: off
_S = EndpointSlug
_N = normalize

# ?date= replays a past session; measured to be honoured 2026-08-16
# (docs/research/2026-08-16-replay-endpoint-matrix.md). No date = live path.
# /volatility/stats returns the stats AS OF that session (one row).
fetch_iv_rank = _ticker_date_fetcher("fetch_iv_rank", _S.IV_RANK, _N.normalize_iv_rank, "list[IvRankRow]")
fetch_volatility_stats = _ticker_date_fetcher("fetch_volatility_stats", _S.VOLATILITY_STATS, _N.normalize_volatility_stats, "list[VolStatsRow]")
fetch_term_structure = _ticker_date_fetcher("fetch_term_structure", _S.TERM_STRUCTURE, _N.normalize_term_structure, "list[TermStructureRow]")
fetch_interpolated_iv = _ticker_date_fetcher("fetch_interpolated_iv", _S.INTERPOLATED_IV, _N.normalize_interpolated_iv, "list[InterpolatedIvRow]")
fetch_oi_per_strike = _ticker_date_fetcher("fetch_oi_per_strike", _S.OI_PER_STRIKE, _N.normalize_oi_per_strike, "list[OiPerStrikeRow]")
fetch_oi_change = _ticker_date_fetcher("fetch_oi_change", _S.OI_CHANGE, _N.normalize_oi_change, "list[OiChangeRow]")
fetch_max_pain = _ticker_date_fetcher("fetch_max_pain", _S.MAX_PAIN, _N.normalize_max_pain, "list[MaxPainRow]")
fetch_darkpool_ticker = _ticker_date_fetcher("fetch_darkpool_ticker", _S.DARKPOOL_TICKER, _N.normalize_darkpool_ticker, "list[DarkPoolPrint]")
# UW historical-alpha: gex-levels / volatility / net-prem / greek-flow honor
# ?date= (as-of). Not memoized: past-date history is not a same-day snapshot.
fetch_volatility_anomaly = _ticker_date_fetcher("fetch_volatility_anomaly", _S.VOLATILITY_ANOMALY, _N.normalize_vol_anomaly, "list[VolAnomalyRow]")
fetch_volatility_character = _ticker_date_fetcher("fetch_volatility_character", _S.VOLATILITY_CHARACTER, _N.normalize_vol_character, "list[VolCharacterRow]")
fetch_volatility_vrp = _ticker_date_fetcher("fetch_volatility_vrp", _S.VOLATILITY_VRP, _N.normalize_vol_vrp, "list[VolVrpRow]")
fetch_greek_flow = _ticker_date_fetcher("fetch_greek_flow", _S.GREEK_FLOW, _N.normalize_greek_flow, "list[GreekFlowRow]")
fetch_net_prem_ticks = _ticker_date_limit_fetcher("fetch_net_prem_ticks", _S.NET_PREM_TICKS, _N.normalize_net_prem_ticks, "list[NetPremTickRow]")
fetch_lit_flow = _ticker_date_limit_fetcher("fetch_lit_flow", _S.LIT_FLOW, _N.normalize_dark_lit, "list[DarkLitPrint]")
# Same DARKPOOL_TICKER slug as fetch_darkpool_ticker, plus date + limit
# selectors so it can backfill history.
fetch_darkpool_prints = _ticker_date_limit_fetcher("fetch_darkpool_prints", _S.DARKPOOL_TICKER, _N.normalize_dark_lit, "list[DarkLitPrint]")

fetch_realized_volatility = _ticker_fetcher("fetch_realized_volatility", _S.REALIZED_VOLATILITY, _N.normalize_realized_volatility, "list[RealizedVolRow]")
fetch_short_data = _ticker_fetcher("fetch_short_data", _S.SHORT_DATA, _N.normalize_short_data, "list[ShortDataRow]")
fetch_etf_info = _ticker_fetcher("fetch_etf_info", _S.ETF_INFO, _N.normalize_etf_info, "EtfInfo")
# Positioning (M4 trade-framework): each returns an aggregated dict keyed to
# uw_positioning columns. See normalize.py + storage/positioning.py.
fetch_short_interest_float = _ticker_fetcher("fetch_short_interest_float", _S.SHORT_INTEREST_FLOAT, _N.normalize_short_interest_float, "dict")
fetch_institution_ownership = _ticker_fetcher("fetch_institution_ownership", _S.INSTITUTION_OWNERSHIP, _N.normalize_institution_ownership, "dict")
fetch_insider_ticker_flow = _ticker_fetcher("fetch_insider_ticker_flow", _S.INSIDER_TICKER_FLOW, _N.normalize_insider_ticker_flow, "dict")
fetch_earnings_history = _ticker_fetcher("fetch_earnings_history", _S.EARNINGS, _N.normalize_earnings_history, "dict")
# ?date= is ignored by these two: FTDs return full history, volumes-by-exchange
# a rolling window. The capture layer selects / aggregates the as-of rows.
fetch_ftds = _ticker_fetcher("fetch_ftds", _S.FTDS, _N.normalize_ftds, "list[FtdRow]")
fetch_volumes_by_exchange = _ticker_fetcher("fetch_volumes_by_exchange", _S.VOLUMES_BY_EXCHANGE, _N.normalize_volumes_by_exchange, "list[VolumesByExchangeRow]")
# fmt: on
fetch_greek_exposure_by_strike = _ticker_fetcher(
    "fetch_greek_exposure_by_strike",
    _S.GREEK_EXPOSURE_BY_STRIKE,
    _raw,
    "dict",
    doc="""Fetch /api/stock/{ticker}/greek-exposure/strike — aggregated per-strike GEX.

    Returns the raw body; scanner consumes ``body["data"]`` as a list of rows
    with string-valued ``strike``, ``call_gex``, ``put_gex``, ``call_delta``,
    ``put_delta`` fields (caller does ``float()`` casting).
    """,
)
fetch_stock_state = _ticker_fetcher(
    "fetch_stock_state",
    _S.STOCK_STATE,
    _raw,
    "dict",
    doc="""Fetch /api/stock/{ticker}/stock-state — last trade snapshot.

    Returns the body envelope; ``body["data"]`` carries
    ``close, prev_close, open, high, low, volume, total_volume, market_time, tape_time``.

    Works uniformly for indices (SPX) and ETFs (SPY/QQQ/IWM). For SPX,
    ``volume`` and ``total_volume`` are 0 by design (indices don't trade), and
    ``market_time`` stays "regular" past 16:00 ET because SPX has no postmarket
    — use ``tape_time`` to judge freshness, not ``market_time``.
    """,
)


# ---------------------------------------------------------------------------
# Fetchers — explicit (non-uniform)
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
    return normalize.normalize_market_tide(body)


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
    return normalize.normalize_top_net_impact(body)


def fetch_economic_calendar(
    client: UwClient, repo: Repository, run_id: int
) -> list[dict]:
    """The economic calendar for the current & next week (UW's own window --
    no date params, no history). One call covers every event; the caller
    persists a row per (event, time) so history accrues capture over capture.

    `forecast`/`prev` are UW's own free-text values (may carry '%', 'K', or be
    blank) -- kept as-is, never parsed into a number here. Parsing/units live
    in the reports layer's verified event->FRED-series mapping only.
    """
    body = _fetch_json(
        client, repo, run_id, EndpointSlug.ECONOMIC_CALENDAR, None, params=None
    )
    return normalize.normalize_economic_calendar(body)


# --------------------------------------------------------------------------- #
# UW historical-alpha fetchers. gex-levels / volatility / net-prem / greek-flow
# honor ?date= (as-of); interest-float / ftds / volumes-by-exchange ignore it and
# return full/rolling history (the capture layer selects the as-of row). Not
# memoized — past-date history is not a slow-moving same-day snapshot.
# --------------------------------------------------------------------------- #


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
