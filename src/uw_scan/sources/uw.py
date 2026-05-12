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
    FlowAlert,
    GreekExposureRow,
    GreeksRow,
    InterpolatedIvRow,
    IvRankRow,
    MaxPainRow,
    OiChangeRow,
    OiPerStrikeRow,
    OptionContractRow,
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
) -> dict:
    path = build_path(slug, ticker)
    started = datetime.now(UTC)
    resp, _hdrs = client.get(slug, ticker=ticker, params=params)
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
) -> list[GreeksRow]:
    body = _fetch_json(
        client,
        repo,
        run_id,
        EndpointSlug.GREEKS,
        ticker,
        params={"expiry": expiry},
    )
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
    limit: int = 50,
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
