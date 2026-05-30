"""Pure normalizers: raw UW JSON → typed Pydantic models.

Strict key access — KeyError on missing required keys. No fallback chains.
Field names mirror docs/uw-samples/*.json.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .models import (
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


# --------------------------------------------------------------------------- #
# M4 positioning helpers + normalizers. These return aggregated dicts keyed to
# uw_positioning columns (not Pydantic models) — they feed a wide snapshot
# upsert, not the API contract. Field names verified against the UW OpenAPI
# spec (docs/uw-samples/unusual_whales_api_spec.yaml); no recorded samples
# exist for these endpoints.
# --------------------------------------------------------------------------- #
def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"cannot parse Decimal from {value!r}") from exc


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise NormalizationError(f"cannot parse date from {value!r}") from exc


def _data_obj(payload: dict) -> dict:
    if "data" not in payload:
        raise NormalizationError(
            f"payload missing 'data' key; got {list(payload.keys())}"
        )
    raw = payload["data"]
    if not isinstance(raw, dict):
        raise NormalizationError(
            f"payload['data'] expected dict, got {type(raw).__name__}"
        )
    return raw


def normalize_short_interest_float(payload: dict) -> dict:
    """V2 short-interest+float `data` object → uw_positioning si_* columns."""
    raw = _data_obj(payload)
    return {
        "si_pct_float": _dec(raw.get("si_float")),
        "si_short_interest": _dec(raw.get("short_interest")),
        "si_total_float": _dec(raw.get("total_float")),
        "si_days_to_cover": _dec(raw.get("days_to_cover")),
        "si_shares_available": _dec(raw.get("short_shares_available")),
        "si_fee_rate": _dec(raw.get("fee_rate")),
        "si_rebate_rate": _dec(raw.get("rebate_rate")),
        "si_market_date": _date_or_none(raw.get("market_date")),
    }


def normalize_analyst_ratings(payload: dict) -> dict:
    """Analyst-ratings `data` array → buy/hold/sell counts + target avg/hi/lo.

    `recommendation` enum is buy|hold|sell (UW spec); substring match keeps us
    robust to feeds that emit 'Strong Buy' / 'Outperform' variants.
    """
    rows = _data_list(payload)
    buy = hold = sell = 0
    targets: list[Decimal] = []
    for r in rows:
        rec = str(r.get("recommendation") or "").strip().lower()
        if "buy" in rec or "outperform" in rec or "overweight" in rec:
            buy += 1
        elif "sell" in rec or "underperform" in rec or "underweight" in rec:
            sell += 1
        elif rec:
            hold += 1
        target = _dec(r.get("target"))
        if target is not None and target > 0:
            targets.append(target)
    return {
        "analyst_buy": buy,
        "analyst_hold": hold,
        "analyst_sell": sell,
        "analyst_target_avg": (
            sum(targets) / Decimal(len(targets)) if targets else None
        ),
        "analyst_target_hi": max(targets) if targets else None,
        "analyst_target_lo": min(targets) if targets else None,
    }


def normalize_institution_ownership(payload: dict) -> dict:
    """Institutional-ownership `data` array (one row per holder) → count + value."""
    rows = _data_list(payload)
    total_value = Decimal(0)
    have_value = False
    for r in rows:
        value = _dec(r.get("inst_value"))
        if value is None:
            value = _dec(r.get("value"))
        if value is not None:
            total_value += value
            have_value = True
    return {
        "inst_holder_count": len(rows) or None,
        "inst_total_value": total_value if have_value else None,
    }


def normalize_insider_ticker_flow(payload: dict) -> dict:
    """Insider ticker-flow `data` array (rows split by buy_sell) → vol + net premium."""
    rows = _data_list(payload)
    buy_vol = Decimal(0)
    sell_vol = Decimal(0)
    buy_prem = Decimal(0)
    sell_prem = Decimal(0)
    for r in rows:
        side = str(r.get("buy_sell") or "").strip().lower()
        volume = _dec(r.get("volume")) or Decimal(0)
        premium = _dec(r.get("premium")) or Decimal(0)
        if "buy" in side:
            buy_vol += volume
            buy_prem += premium
        elif "sell" in side:
            sell_vol += volume
            sell_prem += premium
    if not rows:
        return {
            "insider_buy_volume": None,
            "insider_sell_volume": None,
            "insider_net_flow": None,
        }
    return {
        "insider_buy_volume": buy_vol,
        "insider_sell_volume": sell_vol,
        "insider_net_flow": buy_prem - sell_prem,
    }


def normalize_earnings_history(payload: dict) -> dict:
    """Historical earnings `data` array → positive/total post-earnings reactions
    over the most recent 4 reports (conviction factor 4)."""
    rows = _data_list(payload)
    recent = sorted(rows, key=lambda r: str(r.get("report_date") or ""), reverse=True)[
        :4
    ]
    moves = [_dec(r.get("post_earnings_move_1d")) for r in recent]
    moves = [m for m in moves if m is not None]
    if not moves:
        return {"earn_reactions_positive": None, "earn_reactions_total": None}
    positive = sum(1 for m in moves if m > 0)
    return {
        "earn_reactions_positive": positive,
        "earn_reactions_total": len(moves),
    }


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


def normalize_greek_exposure_by_expiry(
    payload: dict,
) -> list[GreekExposureByExpiryRow]:
    rows = _data_list(payload)
    return [GreekExposureByExpiryRow(**r) for r in rows]


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


def normalize_option_contract_intraday(
    payload: dict,
) -> list[OptionContractIntradayBucket]:
    rows = _data_list(payload)
    return [OptionContractIntradayBucket(**r) for r in rows]


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
    return [
        EtfInOutflowRow(ticker=ticker.upper(), **row) for row in _data_list(payload)
    ]


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
