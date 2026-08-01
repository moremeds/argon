"""Dealer gamma levels (call wall / put wall / gamma flip) for chart overlays.

WHY THIS EXISTS RATHER THAN READING gex_snapshots DIRECTLY: argon's own wall computation
(`cards/gex.py::_market_structure_levels`) takes a plain argmax of call-side and put-side
gamma across ALL strikes with no constraint that the call wall sit above spot or the put
wall below it. Its comments say "typically above spot"; nothing enforces it. Measured on
SPX 2026-07-23..07-28 the two collapsed onto a single strike and sat BELOW spot:

    date        spot    call_wall  put_wall  gamma_flip
    2026-07-28  7383    7000       7000      7525
    2026-07-25  7412    7000       7000      7475

A chart line reading "call wall (resistance) 7,000" under a 7,383 spot is not a weaker
signal, it is a false one. So:

  * UW's own daily levels (`uw_gex_levels_daily`) are PRIMARY — computed upstream, and the
    table is a proper (ticker, market_date) daily series.
  * `gex_snapshots` is the fallback, using the last snapshot of the day.
  * Either way a side-guard runs: a call wall at or below spot, or a put wall at or above
    spot, is DROPPED and named in `dropped`. A missing line is honest; a wrong one is not.

Gamma flip is exempt from the guard — it legitimately sits on either side of spot (that is
what makes it the flip), and its observed values track spot closely.

Not fixing cards/gex.py here on purpose: it feeds the GEX tab, the cockpit, dealer_regime
and the AI prompt payloads, so changing its numbers is a far wider blast radius than a
chart overlay. Tracked separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class GammaLevels:
    """Levels valid for a chart drawn at `spot`. Any field may be None."""

    as_of: date | None = None
    spot: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    gamma_flip: float | None = None
    source: str | None = None  # 'uw_gex_levels_daily' | 'gex_snapshots' | None
    dropped: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return (
            self.call_wall is None and self.put_wall is None and self.gamma_flip is None
        )


def apply_side_guard(
    *,
    spot: float | None,
    call_wall: float | None,
    put_wall: float | None,
) -> tuple[float | None, float | None, list[str]]:
    """Drop walls that sit on the wrong side of spot. Returns (call, put, dropped names).

    With no spot we cannot judge the sides, so both walls are dropped — refusing to draw
    beats drawing something unverifiable.
    """
    dropped: list[str] = []
    if spot is None:
        return None, None, ["call_wall", "put_wall"]
    if call_wall is not None and call_wall <= spot:
        dropped.append("call_wall")
        call_wall = None
    if put_wall is not None and put_wall >= spot:
        dropped.append("put_wall")
        put_wall = None
    return call_wall, put_wall, dropped


def resolve_levels(
    *,
    uw_row: dict | None,
    gex_row: dict | None,
    fallback_spot: float | None = None,
) -> GammaLevels:
    """UW daily levels first, else the day's last gex_snapshot, else empty.

    `fallback_spot` (normally the cone's anchor close) is used when the chosen row carries
    no spot of its own — without a spot the side-guard cannot run at all.
    """
    row, source = (
        (uw_row, "uw_gex_levels_daily") if uw_row else (gex_row, "gex_snapshots")
    )
    if not row:
        return GammaLevels()

    spot = _f(row.get("spot"))
    if spot is None:
        spot = fallback_spot
    call_wall, put_wall, dropped = apply_side_guard(
        spot=spot,
        call_wall=_f(row.get("call_wall")),
        put_wall=_f(row.get("put_wall")),
    )
    return GammaLevels(
        as_of=row.get("market_date") or row.get("data_date"),
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=_f(row.get("gamma_flip")),
        source=source,
        dropped=dropped,
    )


def _f(v: object) -> float | None:
    """Numeric-or-None. Type-checked rather than try/except: psycopg hands back
    Decimal for NUMERIC and float for float8, and anything else here is a caller
    bug worth surfacing as a missing level rather than a swallowed exception.
    `bool` is excluded deliberately — it is an int subclass and would coerce to
    1.0/0.0, which would be a nonsense price level."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float, Decimal)):
        return float(v)
    return None
