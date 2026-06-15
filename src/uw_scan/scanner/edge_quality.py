"""Edge-quality scorer for scanner discovery (radon parity, premium-free).

Ports radon ``scripts/discover.py`` (analyze_darkpool_day / calculate_score /
options-bias / confluence) to Decimal arithmetic. Premium is a FILTER applied
upstream in the job — it is NEVER an input to this score.

The directional dark-pool helper here is distinct from
``signals/dark_pool_accumulation.py`` (which clusters prints near spot and is
direction-neutral). This one classifies each print buy/sell by
``price >= midpoint(nbbo_bid, nbbo_ask)`` and aggregates per day, matching
radon's accumulation/distribution model.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any, Literal

Bias = Literal["bullish", "bearish", "neutral", "mixed"]
DpDirection = Literal["ACCUMULATION", "DISTRIBUTION", "NEUTRAL", "NO_DATA"]

# Must sum to 100. Mirrors radon WEIGHTS. The job overrides these from config.
DEFAULT_WEIGHTS: dict[str, Decimal] = {
    "dp_strength": Decimal("30"),
    "dp_sustained": Decimal("20"),
    "confluence": Decimal("20"),
    "vol_oi": Decimal("15"),
    "sweeps": Decimal("15"),
}

_ACC = Decimal("0.55")
_DIST = Decimal("0.45")
_HALF = Decimal("0.5")
_HUNDRED = Decimal("100")


def _mid(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    return (bid + ask) / Decimal("2")


def analyze_darkpool_day(trades: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Buy/sell split for a set of dark-pool prints (radon analyze_darkpool_day)."""
    trades = list(trades)
    if not trades:
        return {
            "buy_ratio": None,
            "direction": "NO_DATA",
            "strength": Decimal("0"),
            "prints": 0,
        }

    buy_vol = Decimal("0")
    sell_vol = Decimal("0")
    for t in trades:
        size = Decimal(str(t.get("size") or 0))
        price = t.get("price")
        mid = _mid(t.get("nbbo_bid"), t.get("nbbo_ask"))
        if price is None or mid is None:
            continue
        if Decimal(str(price)) >= mid:
            buy_vol += size
        else:
            sell_vol += size

    total = buy_vol + sell_vol
    if total <= 0:
        return {
            "buy_ratio": None,
            "direction": "NO_DATA",
            "strength": Decimal("0"),
            "prints": len(trades),
        }

    ratio = buy_vol / total
    if ratio >= _ACC:
        direction: DpDirection = "ACCUMULATION"
        strength = (ratio - _HALF) * Decimal("200")
    elif ratio <= _DIST:
        direction = "DISTRIBUTION"
        strength = (_HALF - ratio) * Decimal("200")
    else:
        direction = "NEUTRAL"
        strength = Decimal("0")

    return {
        "buy_ratio": ratio,
        "direction": direction,
        "strength": min(strength, _HUNDRED),
        "prints": len(trades),
    }


def directional_darkpool(window: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate + sustained-direction analysis over a warm dark-pool window.

    ``window`` rows are SignalsRepository.fetch_dark_pool_window dicts
    (tracking_id, executed_at, price, size, nbbo_bid, nbbo_ask). Groups by
    execution date, counts consecutive most-recent days sharing the aggregate
    direction.
    """
    window = list(window)
    # Dedup by tracking_id. The warm table stores the SAME print under a new
    # run_id on every discovery tick (insert_dark_pool_rows conflicts on
    # (run_id, tracking_id), not tracking_id alone) and fetch_dark_pool_window
    # does NOT dedup — so today's prints would otherwise be counted ~N times
    # across the day, inflating buy/sell volume and DP strength.
    seen_tids: set = set()
    deduped: list[dict[str, Any]] = []
    for row in window:
        tid = row.get("tracking_id")
        if tid is not None and tid in seen_tids:
            continue
        if tid is not None:
            seen_tids.add(tid)
        deduped.append(row)
    window = deduped
    aggregate = analyze_darkpool_day(window)

    by_day: dict[Any, list[dict[str, Any]]] = {}
    for row in window:
        ts = row.get("executed_at")
        if ts is None:
            continue  # rows without a timestamp can't be day-grouped/sustained
        day = ts.date() if hasattr(ts, "date") else ts
        by_day.setdefault(day, []).append(row)

    # Most-recent day first. Keys are all real dates now, so sorting is safe
    # (a None key here would raise TypeError comparing None to date).
    daily = [
        {"date": day, **analyze_darkpool_day(rows)}
        for day, rows in sorted(by_day.items(), key=lambda kv: kv[0], reverse=True)
    ]

    sustained = 0
    if daily:
        first_dir = daily[0]["direction"]
        if first_dir in ("ACCUMULATION", "DISTRIBUTION"):
            sustained = 1
            for d in daily[1:]:
                if d["direction"] == first_dir:
                    sustained += 1
                else:
                    break

    return {
        "aggregate": aggregate,
        "daily": daily,
        "sustained_days": sustained,
        "total_prints": sum(d["prints"] for d in daily),
    }


def options_bias(*, calls: int, puts: int) -> Bias:
    if calls > puts * 1.5:
        return "bullish"
    if puts > calls * 1.5:
        return "bearish"
    return "mixed"


def has_confluence(bias: Bias, dp_direction: str | None) -> bool:
    return (bias == "bullish" and dp_direction == "ACCUMULATION") or (
        bias == "bearish" and dp_direction == "DISTRIBUTION"
    )


def _vol_oi_score(ratio: Decimal) -> Decimal:
    if ratio <= Decimal("1.0"):
        return Decimal("0")
    if ratio <= Decimal("2.0"):
        return (ratio - Decimal("1.0")) * Decimal("50")
    if ratio <= Decimal("4.0"):
        return Decimal("50") + (ratio - Decimal("2.0")) * Decimal("25")
    return _HUNDRED


def _sweep_score(count: int) -> Decimal:
    if count <= 0:
        return Decimal("0")
    if count == 1:
        return Decimal("50")
    return _HUNDRED


def calculate_score(
    *,
    dp_strength: Decimal,
    dp_sustained: int,
    has_confluence: bool,
    vol_oi_ratio: Decimal,
    sweep_count: int,
    weights: dict[str, Decimal] | None = None,
) -> dict[str, Any]:
    """Normalized 0–100 edge-quality score. Premium is intentionally absent."""
    w = weights or DEFAULT_WEIGHTS
    components = {
        "dp_strength": min(dp_strength, _HUNDRED),
        "dp_sustained": min(Decimal(dp_sustained) * Decimal("20"), _HUNDRED),
        "confluence": _HUNDRED if has_confluence else Decimal("0"),
        "vol_oi": _vol_oi_score(vol_oi_ratio),
        "sweeps": _sweep_score(sweep_count),
    }
    weighted = {k: (components[k] * w[k] / _HUNDRED) for k in components}
    total = sum(weighted.values(), Decimal("0"))
    return {
        "total": total,
        "components": components,
        "weighted": weighted,
    }
