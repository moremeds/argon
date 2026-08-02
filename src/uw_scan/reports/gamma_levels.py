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

Gamma flip is exempt from the SIDE guard — it legitimately sits on either side of spot,
that is what makes it the flip. That left it with no guard at all, which turned out to
matter: UW's `/gex-levels` returns `gamma_flip` null on most SPX sessions and, when it
does resolve, a value 8-9% above spot. So it gets a DISTANCE guard instead — see
`apply_flip_guard`.

Not fixing cards/gex.py here on purpose: it feeds the GEX tab, the cockpit, dealer_regime
and the AI prompt payloads, so changing its numbers is a far wider blast radius than a
chart overlay. Tracked separately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# How far back a level row may be and still be drawn. The capture is daily, so this
# absorbs a long weekend plus a couple of missed nights and no more. Beyond it the walls
# describe a market that has since moved: an unbounded `market_date <= as_of` lookback
# would happily draw levels from a session months old, and the side-guard would not catch
# it because those walls are consistent with THAT session's spot, not today's.
LEVELS_MAX_AGE_DAYS = 7

# How far from spot a gamma flip may sit and still be drawn, as a fraction of spot.
#
# 5% is a JUDGEMENT CALL, not a derived threshold. It was picked to keep everything that
# behaves like a near-spot zero-gamma crossing (argon's own snapshots sit well inside 2%)
# while rejecting what UW returns for SPX. Probed 2026-08-02 over eight sessions,
# `/api/stock/SPX/gex-levels` gave gamma_flip null on six and 8109.8 / 8156.26 on the
# other two — both ~8-9% above a ~7450-7490 spot, both non-round where every other field
# in the same payload is a listed strike (7500 / 7300 / 6910). A fractional value that
# far out is a root-find extrapolating past the traded strike range, not a crossing; it
# also contradicts UW's own regime badge on the same screen, which read positive gamma
# ("dampening") and so implies a flip at or below spot.
#
# Widen it if a legitimate flip is ever observed outside — but require the evidence.
FLIP_MAX_DISTANCE_PCT = 0.05


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


def apply_flip_guard(
    *,
    spot: float | None,
    gamma_flip: float | None,
) -> tuple[float | None, list[str]]:
    """Drop a gamma flip too far from spot to be a credible zero-gamma crossing.

    Distance, not side, is the discriminator here — see FLIP_MAX_DISTANCE_PCT for the
    observations that set the threshold. With no spot there is nothing to measure
    against, so the flip goes, same as the walls do.
    """
    if gamma_flip is None:
        return None, []
    if spot is None or spot <= 0:
        return None, ["gamma_flip"]
    if abs(gamma_flip - spot) / spot > FLIP_MAX_DISTANCE_PCT:
        return None, ["gamma_flip"]
    return gamma_flip, []


def resolve_levels(
    *,
    uw_row: dict | None,
    gex_row: dict | None,
    chart_spot: float | None = None,
) -> GammaLevels:
    """UW daily levels first, else the day's last gex_snapshot, else empty.

    `chart_spot` is the price the chart is actually drawn at (for the cone, its anchor
    close) and is the guard's reference when given. The level row's own spot is only used
    when the caller has none: a wall is judged by whether it sits on the right side of the
    price the reader sees, not of a spot from the session the level was captured in. The
    two coincide on a same-day row and diverge exactly when the row is stale — which is
    the case worth getting right.
    """
    row, source = (
        (uw_row, "uw_gex_levels_daily") if uw_row else (gex_row, "gex_snapshots")
    )
    if not row:
        return GammaLevels()

    spot = chart_spot if chart_spot is not None else _f(row.get("spot"))
    call_wall, put_wall, dropped = apply_side_guard(
        spot=spot,
        call_wall=_f(row.get("call_wall")),
        put_wall=_f(row.get("put_wall")),
    )
    gamma_flip, flip_dropped = apply_flip_guard(
        spot=spot, gamma_flip=_f(row.get("gamma_flip"))
    )
    return GammaLevels(
        as_of=row.get("market_date") or row.get("data_date"),
        spot=spot,
        call_wall=call_wall,
        put_wall=put_wall,
        gamma_flip=gamma_flip,
        source=source,
        dropped=dropped + flip_dropped,
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
