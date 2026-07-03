"""Walk-forward replay engine — look-ahead-free by construction.

Replays a chronologically ordered signal series. At each origin t the entry
rule sees the history of points dated <= t (and only those) and returns a
signed position weight. A non-flat position is marked against the FORWARD
return keyed at t — the return realized over the window that starts after the
decision. That keying is the whole no-lookahead guarantee.

The engine is scalar return-space on purpose: multi-leg options structures
(condors, spreads) are priced by strategy code into forward_returns; the trade
record carries the origin's signal payload for the trace. Pure logic — no DB,
no network. Reference shape: radon scripts/backtest/engine.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Mapping, Sequence

from uw_scan.backtest.metrics import (
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
)

EntryRule = Callable[[Sequence["SignalPoint"], "SignalPoint"], float]


@dataclass(frozen=True)
class SignalPoint:
    """One dated row of a replayed signal series. The engine never inspects
    `signal` — only the strategy's entry rule does."""

    date: date
    signal: Mapping[str, Any]


def walk_forward_backtest(
    series: Sequence[SignalPoint],
    forward_returns: Mapping[date, float],
    entry_rule: EntryRule,
    *,
    cost_fraction: float = 0.0,
    periods_per_year: int = 252,
) -> dict:
    """Replay `series` in date order. entry_rule sees ONLY series[: i + 1] at
    origin i. cost_fraction is a round-trip cost as a fraction of notional,
    scaled by |position|. Origins with no forward return are counted in
    skipped_no_forward, never silently dropped."""
    ordered = sorted(series, key=lambda p: p.date)
    trades: list[dict] = []
    skipped_no_forward = 0
    for i, point in enumerate(ordered):
        history = ordered[: i + 1]
        position = float(entry_rule(history, point))
        if position == 0.0:
            continue
        if point.date not in forward_returns:
            skipped_no_forward += 1
            continue
        gross = position * forward_returns[point.date]
        net = gross - cost_fraction * abs(position)
        trades.append(
            {
                "date": point.date,
                "position": position,
                "gross_return": gross,
                "net_return": net,
            }
        )
    returns = [t["net_return"] for t in trades]
    return {
        "trades": trades,
        "n_trades": len(trades),
        "skipped_no_forward": skipped_no_forward,
        "sharpe": annualized_sharpe(returns, periods_per_year=periods_per_year),
        "max_drawdown": additive_max_drawdown(returns),
        "hit_rate": hit_rate(returns),
    }
