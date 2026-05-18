"""Pure normalizers: raw UW JSON → typed Pydantic models.

Strict key access — KeyError on missing required keys. No fallback chains.
Field names mirror docs/uw-samples/*.json.
"""

from __future__ import annotations

from decimal import Decimal

from .models import (
    BulkScreenerRow,
    DarkPoolPrint,
    EtfInOutflowRow,
    EtfInfo,
    FlowAlert,
    GreekExposureRow,
    GreeksRow,
    InterpolatedIvRow,
    IvRankRow,
    MaxPainRow,
    OiChangeRow,
    OiPerStrikeRow,
    OptionContractRow,
    OptionsDailyRow,
    RealizedVolRow,
    ShortDataRow,
    SkewRow,
    SpotExposureRow,
    TermStructureRow,
    VolStatsRow,
)


class NormalizationError(Exception):
    """Raised when a payload cannot be normalized."""


def _data_list(payload: dict) -> list[dict]:
    if "data" not in payload:
        raise NormalizationError(
            f"payload missing 'data' key; got {list(payload.keys())}"
        )
    raw = payload["data"]
    if not isinstance(raw, list):
        raise NormalizationError(
            f"payload['data'] expected list, got {type(raw).__name__}"
        )
    return raw


def normalize_flow_alerts(payload: dict) -> list[FlowAlert]:
    rows = _data_list(payload)
    return [FlowAlert(**r) for r in rows]


def normalize_iv_rank(payload: dict) -> list[IvRankRow]:
    rows = _data_list(payload)
    return [IvRankRow(**r) for r in rows]


def normalize_volatility_stats(payload: dict) -> list[VolStatsRow]:
    """`volatility_stats` returns a single `data` object (not array) — wrap as list-of-1."""
    if "data" not in payload:
        raise NormalizationError(
            f"payload missing 'data' key; got {list(payload.keys())}"
        )
    raw = payload["data"]
    if isinstance(raw, dict):
        return [VolStatsRow(**raw)]
    if isinstance(raw, list):
        return [VolStatsRow(**r) for r in raw]
    raise NormalizationError(
        f"volatility_stats['data'] expected dict/list, got {type(raw).__name__}"
    )


def normalize_realized_volatility(payload: dict) -> list[RealizedVolRow]:
    rows = _data_list(payload)
    return [RealizedVolRow(**r) for r in rows]


def normalize_term_structure(payload: dict) -> list[TermStructureRow]:
    rows = _data_list(payload)
    return [TermStructureRow(**r) for r in rows]


def normalize_interpolated_iv(payload: dict) -> list[InterpolatedIvRow]:
    rows = _data_list(payload)
    return [InterpolatedIvRow(**r) for r in rows]


def normalize_skew(payload: dict, expiry_hint: str | None = None) -> list[SkewRow]:
    """`skew` payload rows lack `expiry` (it's an input param). expiry_hint lets us
    annotate each row so storage can key by it."""
    rows = _data_list(payload)
    out: list[SkewRow] = []
    for r in rows:
        row = dict(r)
        if expiry_hint and "expiry" not in row:
            row["expiry"] = expiry_hint
        out.append(SkewRow(**row))
    return out


def normalize_greek_exposure(payload: dict) -> list[GreekExposureRow]:
    rows = _data_list(payload)
    return [GreekExposureRow(**r) for r in rows]


def normalize_spot_exposures(payload: dict) -> list[SpotExposureRow]:
    rows = _data_list(payload)
    out: list[SpotExposureRow] = []
    for r in rows:
        # Pydantic with extra=ignore drops the *_ask/_bid/_vol variants we don't keep.
        out.append(SpotExposureRow(**r))
    return out


def normalize_greeks(payload: dict) -> list[GreeksRow]:
    rows = _data_list(payload)
    return [GreeksRow(**r) for r in rows]


def normalize_oi_per_strike(payload: dict) -> list[OiPerStrikeRow]:
    rows = _data_list(payload)
    return [OiPerStrikeRow(**r) for r in rows]


def normalize_oi_change(payload: dict) -> list[OiChangeRow]:
    rows = _data_list(payload)
    return [OiChangeRow(**r) for r in rows]


def normalize_max_pain(payload: dict) -> list[MaxPainRow]:
    rows = _data_list(payload)
    return [MaxPainRow(**r) for r in rows]


def normalize_option_contracts(payload: dict) -> list[OptionContractRow]:
    rows = _data_list(payload)
    return [OptionContractRow(**r) for r in rows]


def normalize_options_volume_daily(payload: dict) -> list[OptionsDailyRow]:
    rows = _data_list(payload)
    return [OptionsDailyRow(**r) for r in rows]


def normalize_option_contracts_by_symbol(payload: dict) -> list[OptionContractRow]:
    """Same shape as `option_contracts` (verified vs samples)."""
    return normalize_option_contracts(payload)


def normalize_darkpool_ticker(payload: dict) -> list[DarkPoolPrint]:
    rows = _data_list(payload)
    return [DarkPoolPrint(**r) for r in rows]


def normalize_short_data(payload: dict) -> list[ShortDataRow]:
    """Intraday snapshots — multiple rows per day. Caller picks latest by timestamp."""
    rows = _data_list(payload)
    return [ShortDataRow(**r) for r in rows]


def normalize_bulk_screener(payload: dict) -> list[BulkScreenerRow]:
    """Normalize `/api/screener/stocks` response.

    Verified against `docs/uw-samples/bulk_screener_stocks_sp500.json`: body has
    `{"data": [...]}` envelope. Strict — raises NormalizationError otherwise.
    """
    if not isinstance(payload, dict):
        raise NormalizationError(
            f"bulk_screener payload expected dict, got {type(payload).__name__}"
        )
    if "data" not in payload:
        raise NormalizationError(
            f"bulk_screener payload missing 'data' key; got {list(payload.keys())}"
        )
    raw = payload["data"]
    if not isinstance(raw, list):
        raise NormalizationError(
            f"bulk_screener payload['data'] expected list, got {type(raw).__name__}"
        )
    return [BulkScreenerRow(**r) for r in raw]


def normalize_etf_info(payload: dict) -> EtfInfo:
    if "data" not in payload:
        raise NormalizationError(
            f"etf_info payload missing 'data' key; got {list(payload.keys())}"
        )
    raw = payload["data"]
    if not isinstance(raw, dict):
        raise NormalizationError(
            f"etf_info payload['data'] expected object, got {type(raw).__name__}"
        )
    return EtfInfo(**raw)


def normalize_etf_in_outflow(payload: dict, *, ticker: str) -> list[EtfInOutflowRow]:
    return [EtfInOutflowRow(ticker=ticker.upper(), **row) for row in _data_list(payload)]


# ---------------------------------------------------------------------------
# Helpers for "current" row selection
# ---------------------------------------------------------------------------
def latest_by_date(rows: list, key: str = "date"):
    if not rows:
        return None
    return max(rows, key=lambda r: getattr(r, key))


def latest_by_timestamp(rows: list[ShortDataRow]) -> ShortDataRow | None:
    if not rows:
        return None
    return max(rows, key=lambda r: r.timestamp)


def to_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
