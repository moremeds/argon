"""Aggregate UW option-contracts rows into per-(expiry, strike) snapshots
that back the Flow tab's Volume + OI strike-profile charts."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable

from uw_scan.models import OptionChainPerStrikeRow, OptionContractRow

logger = logging.getLogger(__name__)

# OCC 21-char: ROOT (<=6, left-justified) | YYMMDD | C/P | STRIKE * 1000 (8 digits)
_OCC_RE = re.compile(
    r"^(?P<root>.{1,6}?)\s*(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<type>[CP])(?P<strike>\d{8})$"
)


def pick_target_expiries(
    contracts: Iterable[OptionContractRow],
    *,
    target_dtes: Iterable[int],
    today: date,
) -> list[date]:
    """Return the available expiries closest to each target DTE.

    Result is sorted, deduplicated, and bounded to expiries that actually
    exist in the contracts list. If a target DTE has no candidate (e.g.,
    0DTE on a ticker without daily expiries), it is skipped silently.
    """
    available = sorted(
        {
            parsed[0]
            for c in contracts
            if (parsed := _parse_occ(c.option_symbol)) is not None
            and parsed[0] >= today
        }
    )
    if not available:
        return []
    picked: set[date] = set()
    for dte in sorted(set(target_dtes)):
        if dte < 0:
            continue
        nearest = min(available, key=lambda e: abs((e - today).days - dte))
        picked.add(nearest)
    return sorted(picked)


def _parse_occ(symbol: str) -> tuple[date, str, Decimal] | None:
    m = _OCC_RE.match(symbol)
    if not m:
        return None
    yy = int(m["yy"])
    year = 2000 + yy if yy < 80 else 1900 + yy
    try:
        expiry = date(year, int(m["mm"]), int(m["dd"]))
    except ValueError as exc:
        logger.debug("invalid OCC date %s: %s", symbol, repr(exc))
        return None
    strike = Decimal(m["strike"]) / Decimal(1000)
    return expiry, m["type"], strike


def aggregate_chain_per_strike(
    contracts: Iterable[OptionContractRow],
    *,
    spot: Decimal,
    max_pct_from_spot: Decimal,
    max_dte_days: int,
    today: date,
) -> list[OptionChainPerStrikeRow]:
    """Group contracts by (expiry, strike), summing call/put volume and OI.

    Filters out strikes more than ``max_pct_from_spot`` from spot and expiries
    further than ``max_dte_days`` from ``today``. Contracts whose OCC symbol
    fails to parse are dropped with a debug log — callers see those as
    "no data" at that strike.
    """

    grouped: dict[tuple[date, Decimal], dict[str, int]] = defaultdict(
        lambda: {"call_volume": 0, "put_volume": 0, "call_oi": 0, "put_oi": 0}
    )

    for c in contracts:
        parsed = _parse_occ(c.option_symbol)
        if parsed is None:
            logger.debug("unparseable OCC symbol skipped: %s", c.option_symbol)
            continue
        expiry, opt_type, strike = parsed
        dte = (expiry - today).days
        if dte < 0 or dte > max_dte_days:
            continue
        pct = abs(strike - spot) / spot if spot > 0 else Decimal(0)
        if pct > max_pct_from_spot:
            continue
        slot = grouped[(expiry, strike)]
        if opt_type == "C":
            slot["call_volume"] += c.volume or 0
            slot["call_oi"] += c.open_interest or 0
        else:
            slot["put_volume"] += c.volume or 0
            slot["put_oi"] += c.open_interest or 0

    rows = [
        OptionChainPerStrikeRow(
            expiry=expiry,
            strike=strike,
            call_volume=vals["call_volume"] or None,
            put_volume=vals["put_volume"] or None,
            call_oi=vals["call_oi"] or None,
            put_oi=vals["put_oi"] or None,
        )
        for (expiry, strike), vals in sorted(
            grouped.items(), key=lambda kv: (kv[0][0], kv[0][1])
        )
    ]
    return rows
