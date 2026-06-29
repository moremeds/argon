"""Market-tide slope/sentiment — quantifies the UW Daily Market Tide guide.

The guide reads sentiment off the DIVERGENCE of the net call-premium (NCP) and
net put-premium (NPP) lines. We collapse that into one line, the spread
S = NCP - NPP (bullish when calls pull above puts), and capture its slope:

  • session slope  — OLS over the whole day (overall drift / context)
  • recent slope   — OLS over the last RECENT_BARS 5-min bars (the guide's
                     "becoming increasingly" bullish/bearish — momentum)

Strength is the divergence ratio trend_strength = |net displacement| / range,
in [0,1]: a monotone one-way spread → ~1 (strong, parallel lines pulling apart);
a choppy round-trip ending where it started → ~0 (balanced). This is scale-free
and avoids a spurious-regression t-stat on the cumulative/I(1) spread series.
The dominant leg (slope of NCP vs NPP) names WHY (call buying / call selling /
put buying / put unwinding). Net volume's slope confirms or contradicts.

Pure functions over already-persisted bars — shared by the live `/market-tide`
endpoint and the nightly EOD persistence job. FLOW-SENTIMENT descriptor, not a
price predictor (the EOD table is the backtest material to validate that).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

# Recent-slope window in 5-min bars (30 min). The capture is every 5 min today.
RECENT_BARS = 6
# Minimum bars before a state is meaningful (early-session guard).
MIN_BARS = 8
# trend_strength buckets (|net displacement| / range, 0..1).
# ponytail: heuristic cuts; recalibrate once the EOD backtest has history.
TREND_LEANING = 0.25
TREND_STRONG = 0.60


@dataclass(frozen=True)
class TideSentiment:
    state: str  # BULLISH | BEARISH | BALANCED | WARMING_UP
    magnitude: str  # FLAT | LEANING | STRONG
    driver: str  # call buying | call selling | put buying | put unwinding | —
    momentum: str  # accelerating | easing | reversing | —
    spread: float | None  # current S = NCP - NPP ($)
    session_slope: float | None  # $/hr
    recent_slope: float | None  # $/hr
    trend_strength: float | None  # |net displacement| / range, 0..1 (divergence)
    volume_confirms: bool | None  # net-volume drift agrees with the spread drift
    bars: int

    def to_dict(self) -> dict:
        return asdict(self)


def _ols_slope(xs: list[float], ys: list[float]) -> float | None:
    """OLS slope of ys on xs (units: y per x). None if undetermined."""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    return num / den


@dataclass(frozen=True)
class _Bar:
    minutes: float
    ncp: float
    npp: float
    nv: float | None


def _extract(points: list) -> list[_Bar]:
    """Normalize point dicts/models → bars with minutes-from-open, NCP/NPP/NV.
    Drops bars missing premium; tolerates dict or attribute access."""

    def g(p, key):
        return p.get(key) if isinstance(p, dict) else getattr(p, key, None)

    raw: list[tuple[datetime, float, float, float | None]] = []
    for p in points:
        ts = g(p, "ts")
        ncp = g(p, "net_call_premium")
        npp = g(p, "net_put_premium")
        nv = g(p, "net_volume")
        if ts is None or ncp is None or npp is None:
            continue
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        raw.append((ts, float(ncp), float(npp), None if nv is None else float(nv)))
    if not raw:
        return []
    raw.sort(key=lambda r: r[0])
    t0 = raw[0][0]
    return [
        _Bar((ts - t0).total_seconds() / 60.0, ncp, npp, nv) for ts, ncp, npp, nv in raw
    ]


def compute_sentiment(points: list, *, recent_bars: int = RECENT_BARS) -> TideSentiment:
    """Sentiment for one session's bars (any order). Empty/thin → WARMING_UP."""
    bars = _extract(points)
    n = len(bars)
    if n < 2:
        return TideSentiment(
            "WARMING_UP", "FLAT", "—", "—", None, None, None, None, None, n
        )

    minutes = [b.minutes for b in bars]
    spreads = [b.ncp - b.npp for b in bars]
    spread_now = spreads[-1]

    session_slope = _ols_slope(minutes, spreads)  # $/min
    k = min(recent_bars, n)
    recent_slope = _ols_slope(minutes[-k:], spreads[-k:])  # $/min
    # Driver: dS = dNCP - dNPP over the full session; larger-|slope| leg = cause.
    mC = _ols_slope(minutes, [b.ncp for b in bars])
    mP = _ols_slope(minutes, [b.npp for b in bars])

    # Volume confirmation: does the day's net-volume drift agree with S's drift?
    nv_pts = [(b.minutes, b.nv) for b in bars if b.nv is not None]
    mV = (
        _ols_slope([m for m, _ in nv_pts], [v for _, v in nv_pts])
        if len(nv_pts) >= 2
        else None
    )
    volume_confirms: bool | None = None
    if mV is not None and session_slope not in (None, 0) and mV != 0:
        volume_confirms = (mV > 0) == (session_slope > 0)

    # Divergence / trend strength: |net displacement| / total range, in [0,1].
    displacement = spreads[-1] - spreads[0]
    rng = max(spreads) - min(spreads)
    trend_strength = abs(displacement) / rng if rng > 0 else 0.0

    driver = "—"
    if mC is not None and mP is not None:
        if abs(mC) >= abs(mP):
            driver = "call buying" if mC > 0 else "call selling"
        else:
            driver = "put buying" if mP > 0 else "put unwinding"

    # Momentum: recent slope vs the session drift.
    momentum = "—"
    if recent_slope is not None and session_slope not in (None, 0):
        if (recent_slope > 0) == (session_slope > 0):
            momentum = (
                "accelerating" if abs(recent_slope) >= abs(session_slope) else "easing"
            )
        else:
            momentum = "reversing"

    # State + magnitude from direction (session drift) × divergence strength.
    if n < MIN_BARS or session_slope is None:
        state, magnitude = "WARMING_UP", "FLAT"
    elif trend_strength < TREND_LEANING:
        state, magnitude = "BALANCED", "FLAT"
    else:
        state = "BULLISH" if session_slope > 0 else "BEARISH"
        magnitude = "STRONG" if trend_strength >= TREND_STRONG else "LEANING"

    def per_hr(v: float | None) -> float | None:
        return None if v is None else v * 60.0

    return TideSentiment(
        state=state,
        magnitude=magnitude,
        driver=driver,
        momentum=momentum,
        spread=spread_now,
        session_slope=per_hr(session_slope),
        recent_slope=per_hr(recent_slope),
        trend_strength=trend_strength,
        volume_confirms=volume_confirms,
        bars=n,
    )


if __name__ == "__main__":
    # Self-check: a steadily-widening bullish spread reads BULLISH/STRONG,
    # call-led, volume-confirmed; a flat spread reads BALANCED.
    from datetime import timedelta, timezone

    t0 = datetime(2026, 6, 26, 13, 30, tzinfo=timezone.utc)

    def mk(i, ncp, npp, nv=0):
        return {
            "ts": t0 + timedelta(minutes=5 * i),
            "net_call_premium": ncp,
            "net_put_premium": npp,
            "net_volume": nv,
        }

    rising = [mk(i, ncp=1e6 * i, npp=-2e5 * i, nv=1000 * i) for i in range(12)]
    s = compute_sentiment(rising)
    assert s.state == "BULLISH", s
    assert s.magnitude == "STRONG", s
    assert s.driver == "call buying", s
    assert s.momentum in ("accelerating", "easing"), s
    assert s.volume_confirms is True, s
    assert s.spread is not None and s.spread > 0

    flat = [mk(i, ncp=1e6, npp=1e6, nv=0) for i in range(12)]
    assert compute_sentiment(flat).state == "BALANCED", compute_sentiment(flat)

    thin = compute_sentiment([mk(0, 1e6, 0)])
    assert thin.state == "WARMING_UP", thin

    print("market_tide_sentiment self-check OK")
