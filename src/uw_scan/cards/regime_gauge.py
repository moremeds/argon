"""Correlation gauge — rolling Gold ↔ DFII10 across 4 windows, levels + returns.

Default thresholds:
  state = 'operative'  if corr_252d_level in [-1.00, -0.50]
        = 'partial'    if corr_252d_level in (-0.50, -0.20]
        = 'suspended'  otherwise

Per docs/research/gold-sdf-framework/04-three-layer-architecture.md these
thresholds are heuristic; Phase A2 calibrates empirically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class CorrelationGauge:
    corr_60d_level: Decimal | None
    corr_126d_level: Decimal | None
    corr_252d_level: Decimal | None
    corr_504d_level: Decimal | None
    corr_252d_returns: Decimal | None
    state: str


def _align(
    series_a: list[tuple[date, Decimal]],
    series_b: list[tuple[date, Decimal]],
) -> tuple[list[date], list[float], list[float]]:
    a_map = dict(series_a)
    b_map = dict(series_b)
    common = sorted(set(a_map) & set(b_map))
    return (
        common,
        [float(a_map[d]) for d in common],
        [float(b_map[d]) for d in common],
    )


def _pearson(xs: list[float], ys: list[float]) -> Decimal | None:
    if len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
    if den_x == 0.0 or den_y == 0.0:
        return None
    return Decimal(str(num / (den_x * den_y))).quantize(Decimal("0.0001"))


def _trailing(values: list[float], window: int) -> list[float] | None:
    if len(values) < window:
        return None
    return values[-window:]


def _log_returns(values: list[float]) -> list[float]:
    out: list[float] = []
    for prev, curr in zip(values[:-1], values[1:], strict=True):
        if prev <= 0 or curr <= 0:
            out.append(0.0)
        else:
            out.append(math.log(curr / prev))
    return out


def classify_gauge_state(corr_252_level: Decimal | None) -> str:
    if corr_252_level is None:
        return "suspended"
    if Decimal("-1.0") <= corr_252_level <= Decimal("-0.5"):
        return "operative"
    if Decimal("-0.5") < corr_252_level <= Decimal("-0.2"):
        return "partial"
    return "suspended"


def compute_correlation_gauge(
    gold_series: list[tuple[date, Decimal]],
    dfii10_series: list[tuple[date, Decimal]],
    *,
    as_of: date,
) -> CorrelationGauge:
    g_filtered = [(d, v) for d, v in gold_series if d <= as_of]
    t_filtered = [(d, v) for d, v in dfii10_series if d <= as_of]
    _dates, gold_vals, tips_vals = _align(g_filtered, t_filtered)
    if len(gold_vals) < 60:
        return CorrelationGauge(None, None, None, None, None, "suspended")

    def corr_window(w: int) -> Decimal | None:
        g = _trailing(gold_vals, w)
        t = _trailing(tips_vals, w)
        if g is None or t is None:
            return None
        return _pearson(g, t)

    corr_60 = corr_window(60)
    corr_126 = corr_window(126)
    corr_252 = corr_window(252)
    corr_504 = corr_window(504)

    g_ret = _log_returns(gold_vals)
    t_ret = _log_returns(tips_vals)
    g_ret_w = _trailing(g_ret, 252)
    t_ret_w = _trailing(t_ret, 252)
    corr_252_returns = _pearson(g_ret_w, t_ret_w) if g_ret_w and t_ret_w else None

    state = classify_gauge_state(corr_252)
    return CorrelationGauge(
        corr_60d_level=corr_60,
        corr_126d_level=corr_126,
        corr_252d_level=corr_252,
        corr_504d_level=corr_504,
        corr_252d_returns=corr_252_returns,
        state=state,
    )
