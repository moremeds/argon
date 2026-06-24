"""Forward entry-capture: resolve the SPX bull-put-spread the Macro Short-Vol
signal would place onto *listed* strikes, then quote each leg.

`resolve_entry_contracts` is pure (no I/O): it maps the BS target strike for the
0.25Δ short and 0.125Δ wing onto the nearest listed strikes that bracket each
target. `quote_leg` (Task 4) quotes a resolved leg IB-primary / UW-fallback with
BS-computed greeks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vrp_structure import strike_for_delta


@dataclass(frozen=True)
class EntryContracts:
    short_above: float
    short_below: float
    wing_above: float
    wing_below: float


def _bracket(target: float, strikes_sorted: list[float]) -> tuple[float, float]:
    """Nearest listed strike strictly below and strictly above `target`.
    Raises ValueError if the grid lacks a strike on either side."""
    below: float | None = None
    above: float | None = None
    for k in strikes_sorted:
        if k < target:
            below = k
        elif k > target:
            above = k
            break
    if below is None or above is None:
        raise ValueError(
            f"listed strikes do not bracket target {target:.2f} "
            f"(range {strikes_sorted[0]}..{strikes_sorted[-1]})"
        )
    return below, above


def resolve_entry_contracts(
    *,
    spot: float,
    sigma: float,
    T: float,
    r: float,
    listed_strikes: list[float],
    short_delta: float = 0.25,
    wing_delta: float = 0.125,
) -> EntryContracts:
    """BS target strike per delta, snapped to the listed strikes that bracket it.

    Flat-vol target (skew ignored — the realized leg delta is recorded at quote
    time). Both legs are puts (`is_call=False`). Raises ValueError if the grid
    can't bracket a target."""
    strikes_sorted = sorted(set(listed_strikes))
    short_target = strike_for_delta(spot, T, r, sigma, short_delta, is_call=False)
    wing_target = strike_for_delta(spot, T, r, sigma, wing_delta, is_call=False)
    short_below, short_above = _bracket(short_target, strikes_sorted)
    wing_below, wing_above = _bracket(wing_target, strikes_sorted)
    return EntryContracts(
        short_above=short_above,
        short_below=short_below,
        wing_above=wing_above,
        wing_below=wing_below,
    )
