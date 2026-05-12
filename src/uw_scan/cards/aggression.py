"""Aggression % derivation: ask_side / (ask_side + bid_side)."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.models import FlowSnapshot


def compute_aggression_pct(flow: FlowSnapshot) -> Decimal | None:
    """Return aggression in [0, 1]; None when total premium is zero."""
    ask = flow.ask_side_premium or Decimal("0")
    bid = flow.bid_side_premium or Decimal("0")
    total = ask + bid
    if total == 0:
        return None
    return ask / total
