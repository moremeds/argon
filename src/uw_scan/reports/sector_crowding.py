"""Sector-ETF crowding score (板块拥挤度).

Three conjunctive legs, adapted from
https://x.com/bitfool1/status/2079479920162734401 (2026-07-21):

  price    3M return minus the benchmark's, expressed as that ETF's OWN
           trailing percentile. Absolute spread is not comparable across the
           universe -- the trailing SD of the 3M spread ranges from 3.1 (XLY)
           to 16.5 (XLE), so ranking on raw spread ranks volatility, not
           crowding. XLF at +3.14% is its 99th percentile; SMH at +17.88% is
           its 46th.
  flow     21-session net premium flow / AUM, scored on the tweet's published
           2% / 5% / 10% bands. Dividing by AUM already removes the size
           effect, so absolute bands ARE comparable here and are kept.
  premium  iv_rank minus the benchmark's iv_rank. Substitutes for the tweet's
           NTM P/E, which needs constituent forward EPS that neither UW nor
           massive expose on our tier. Same question -- is the crowd paying up
           -- asked about convexity instead of earnings.

STATE is the weakest leg's band, not the mean's. The tweet is explicit that
the legs are conjunctive (三者同时出现，才算真正拥挤); a mean would let one
extreme leg manufacture a CROWDED badge on its own. SCORE stays the mean so
rows sort with some granularity inside a state, and `binding_leg` names which
leg is holding the state down so a demotion is always explainable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date as _date
from datetime import timedelta
from typing import Any, Protocol

from uw_scan.storage.market_data import normalize_etf_aum

RETURN_WINDOW = 63
FLOW_WINDOW = 21
MIN_SESSIONS = RETURN_WINDOW + FLOW_WINDOW
MIN_HISTORY_POINTS = 60
LOOKBACK_DAYS = 400

BENCHMARK = "SPY"
SECTOR_CROWDING_TICKERS = (
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    "SOXX",
    "SMH",
    "IGV",
)
# ARKK is deliberately absent: UW's /api/etfs/ARKK/in-outflow returns 0 rows.
# Verified 2026-07-24. Re-add if UW starts publishing it.

# (flow_pct, score) anchors for piecewise-linear interpolation, clamped
# outside the ends. Derived from the tweet's bands: <2% normal, 2-5% warm,
# 5%+ crowded, 10%+ extreme.
FLOW_BREAKPOINTS: tuple[tuple[float, float], ...] = (
    (-5.0, 0.0),
    (0.0, 20.0),
    (2.0, 40.0),
    (5.0, 70.0),
    (10.0, 90.0),
    (25.0, 100.0),
)
IVR_SPREAD_CAP = 60.0

BAND_CROWDED = 75.0
BAND_WARM = 50.0
BAND_NORMAL = 25.0

_BAND_RANK = {"COLD": 0, "NORMAL": 1, "WARM": 2, "CROWDED": 3}


@dataclass(frozen=True)
class CrowdingLeg:
    name: str
    raw: float | None
    score: float | None
    band: str | None


def pct_rank(history: Sequence[float], value: float) -> float | None:
    """Percentile of `value` within `history`, 0-100. None if no history."""
    if not history:
        return None
    below = sum(1 for h in history if h < value)
    return 100.0 * below / len(history)


def flow_score(flow_aum_pct: float) -> float:
    """Map 1M-flow/AUM percent onto 0-100 via the tweet's bands."""
    lo_x, lo_y = FLOW_BREAKPOINTS[0]
    if flow_aum_pct <= lo_x:
        return lo_y
    for (x0, y0), (x1, y1) in zip(FLOW_BREAKPOINTS, FLOW_BREAKPOINTS[1:], strict=False):
        if flow_aum_pct <= x1:
            span = x1 - x0
            return y0 + (flow_aum_pct - x0) / span * (y1 - y0)
    return FLOW_BREAKPOINTS[-1][1]


def premium_score(ivr_spread: float) -> float:
    """Map an iv_rank spread (percentage points vs benchmark) onto 0-100."""
    if ivr_spread <= 0.0:
        return 0.0
    return min(ivr_spread, IVR_SPREAD_CAP) / IVR_SPREAD_CAP * 100.0


def band_of(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= BAND_CROWDED:
        return "CROWDED"
    if score >= BAND_WARM:
        return "WARM"
    if score >= BAND_NORMAL:
        return "NORMAL"
    return "COLD"


def combine(
    legs: Sequence[CrowdingLeg],
) -> tuple[float | None, str | None, str | None]:
    """(mean score, weakest-leg band, name of the leg pinning that band).

    Needs at least two present legs -- a single leg is a reading, not a
    conjunction, and badging it would overstate what we know.
    """
    present = [leg for leg in legs if leg.score is not None and leg.band is not None]
    if len(present) < 2:
        return (None, None, None)
    score = sum(leg.score for leg in present) / len(present)
    weakest = min(_BAND_RANK[leg.band] for leg in present)
    in_band = [leg for leg in present if _BAND_RANK[leg.band] == weakest]
    binding = min(in_band, key=lambda leg: leg.score)
    return (score, binding.band, binding.name)


_AUM_MAX_AGE = timedelta(days=30)

# watchlist_card only refreshes when a ticker scans, so an unbounded iv_rank
# read scores the premium leg on whatever the last successful scan left behind.
# Five days clears a long weekend plus one holiday; anything older means the
# ticker stopped scanning and the leg should go absent, not stale.
_IVR_MAX_AGE = timedelta(days=5)


class _CrowdingRepo(Protocol):
    """The three reads build_sector_crowding needs. Declared structurally so
    the unit tests can pass a fake without touching Postgres."""

    def fetch_etf_flows_daily(
        self, ticker: str, **kwargs: Any
    ) -> list[dict[str, Any]]: ...

    def get_recent_etf_aum(self, ticker: str, *, max_age: timedelta) -> Any: ...

    def fetch_iv_ranks(
        self, tickers: Sequence[str], *, max_age: timedelta
    ) -> dict[str, float]: ...


@dataclass(frozen=True)
class CrowdingSeriesPoint:
    obs_date: _date
    etf_cum_return: float
    bench_cum_return: float
    flow_aum_pct: float | None


@dataclass(frozen=True)
class CrowdingRow:
    ticker: str
    price: CrowdingLeg
    flow: CrowdingLeg
    premium: CrowdingLeg
    score: float | None
    state: str | None
    binding_leg: str | None
    series: list[CrowdingSeriesPoint]


def _valid(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rows carrying a usable close, in date order.

    Returns the ROWS, not the closes. Filtering a parallel list of closes and
    leaving `rows` untouched desynchronizes them: rows[i] would no longer be
    the row closes[i] came from, so flow windows and chart dates would silently
    describe different observations than the returns.
    """
    return [r for r in rows if r.get("close") is not None and float(r["close"]) > 0]


def _window_return(closes: Sequence[float], end: int, window: int) -> float | None:
    """Percent return over `window` sessions ending at index `end`."""
    start = end - window
    if start < 0 or closes[start] == 0:
        return None
    return (closes[end] / closes[start] - 1.0) * 100.0


def _flow_ratio(
    rows: list[dict[str, Any]], end: int, aum: float | None
) -> float | None:
    start = end - FLOW_WINDOW + 1
    if start < 0 or not aum:
        return None
    total = sum(
        float(r["premium_change_usd"])
        for r in rows[start : end + 1]
        if r.get("premium_change_usd") is not None
    )
    return 100.0 * total / aum


def build_sector_crowding(
    *,
    repo: _CrowdingRepo,
    tickers: Sequence[str] = SECTOR_CROWDING_TICKERS,
    benchmark: str = BENCHMARK,
) -> tuple[_date | None, list[CrowdingRow]]:
    """Rank `tickers` by crowding against `benchmark`.

    Read-time compute over etf_flows_daily + etf_aum_cache + watchlist_card.
    Every input is already persisted; nothing here is the only copy of
    anything, which is why the score itself needs no table.
    """
    # Bound the read. Unbounded, the percentile leg silently changes meaning as
    # the table accrues -- in year three it would rank today against three years
    # of history, which is not the statistic the probe validated. Same window as
    # the capture, so the read never asks for rows the job does not maintain.
    since = _date.today() - timedelta(days=LOOKBACK_DAYS)

    bench_rows = repo.fetch_etf_flows_daily(benchmark, from_date=since)
    bench_by_date = {r["obs_date"]: float(r["close"]) for r in _valid(bench_rows)}
    if len(bench_by_date) < MIN_SESSIONS:
        return (None, [])

    iv_ranks = repo.fetch_iv_ranks([*tickers, benchmark], max_age=_IVR_MAX_AGE)
    bench_ivr = iv_ranks.get(benchmark.upper())

    out: list[CrowdingRow] = []
    as_of: _date | None = None

    for ticker in tickers:
        # Inner-join on obs_date. Aligning by POSITION -- truncating both lists
        # to the shorter length -- silently compares different sessions the
        # first time either series is missing a day: one dropped UW row, or a
        # holiday one venue observes. Every subsequent index is then shifted,
        # and nothing about the output looks wrong.
        paired = [
            (r, float(r["close"]), bench_by_date[r["obs_date"]])
            for r in _valid(repo.fetch_etf_flows_daily(ticker, from_date=since))
            if r["obs_date"] in bench_by_date
        ]
        if len(paired) < MIN_SESSIONS:
            continue

        rows = [p[0] for p in paired]
        closes = [p[1] for p in paired]
        bench = [p[2] for p in paired]
        n = len(paired)
        last = n - 1

        row_date = rows[last]["obs_date"]
        as_of = row_date if as_of is None else max(as_of, row_date)

        etf_r = _window_return(closes, last, RETURN_WINDOW)
        bench_r = _window_return(bench, last, RETURN_WINDOW)
        rel = None if etf_r is None or bench_r is None else etf_r - bench_r

        # Trailing history of the SAME relative-return metric, so the
        # percentile answers "extreme for this ETF", not "extreme vs XLU".
        #
        # `history` deliberately INCLUDES today's own value: the loop runs to
        # n-1. pct_rank counts strictly-below, so today can never print 100 --
        # the ceiling is (len-1)/len, about 99.1 over a year. That matches the
        # probe that produced every frozen fixture. Excluding today would look
        # tidier and would silently shift every expected percentile in the
        # tests. Do not "fix" it.
        history: list[float] = []
        for i in range(RETURN_WINDOW + FLOW_WINDOW, n):
            a = _window_return(closes, i, RETURN_WINDOW)
            b = _window_return(bench, i, RETURN_WINDOW)
            if a is not None and b is not None:
                history.append(a - b)
        price_score = (
            pct_rank(history, rel)
            if rel is not None and len(history) >= MIN_HISTORY_POINTS
            else None
        )
        price = CrowdingLeg("price", rel, price_score, band_of(price_score))

        aum_raw = repo.get_recent_etf_aum(ticker, max_age=_AUM_MAX_AGE)
        aum = normalize_etf_aum(aum_raw)
        ratio = _flow_ratio(rows, last, float(aum) if aum else None)
        f_score = None if ratio is None else flow_score(ratio)
        flow = CrowdingLeg("flow", ratio, f_score, band_of(f_score))

        etf_ivr = iv_ranks.get(ticker.upper())
        spread = None if etf_ivr is None or bench_ivr is None else etf_ivr - bench_ivr
        p_score = None if spread is None else premium_score(spread)
        premium = CrowdingLeg("premium", spread, p_score, band_of(p_score))

        score, state, binding = combine([price, flow, premium])

        # Every historical bar divides by TODAY's AUM -- etf_aum_cache keeps
        # one row per ticker, so there is no AUM history to divide by. If a
        # fund grew 40% over the window, its older bars read ~40% low. The
        # bars are a shape cue, not a measurement; the scored leg only ever
        # uses the newest point, where the AUM is current. Same simplification
        # the probe made. Storing an AUM series would fix it, and needs a table.
        series = []
        # RETURN_WINDOW counts INTERVALS, so the scored window spans
        # RETURN_WINDOW+1 observations -- _window_return divides closes[end] by
        # closes[end - RETURN_WINDOW]. Starting the chart at n - RETURN_WINDOW
        # would rebase one session late and the chart's final ETF-minus-bench
        # value would not equal price.raw (measured on the Task 3 fixture:
        # 64.27603 charted vs 64.71898 scored). Locked by an assertion in the
        # test below.
        window_start = max(0, n - 1 - RETURN_WINDOW)
        base_etf, base_bench = closes[window_start], bench[window_start]
        for i in range(window_start, n):
            series.append(
                CrowdingSeriesPoint(
                    obs_date=rows[i]["obs_date"],
                    etf_cum_return=(closes[i] / base_etf - 1.0) * 100.0,
                    bench_cum_return=(bench[i] / base_bench - 1.0) * 100.0,
                    flow_aum_pct=_flow_ratio(rows, i, float(aum) if aum else None),
                )
            )

        out.append(
            CrowdingRow(
                ticker=ticker.upper(),
                price=price,
                flow=flow,
                premium=premium,
                score=score,
                state=state,
                binding_leg=binding,
                series=series,
            )
        )

    # Group by verdict first so CROWDED rows sit together, then by score
    # inside a band. Sorting on score alone would interleave states, which
    # reads as a broken table.
    # Negated numerics rather than reverse=True, which would also flip the
    # ticker tiebreak to Z->A.
    out.sort(
        key=lambda r: (
            -_BAND_RANK.get(r.state or "COLD", -1),
            -(r.score if r.score is not None else -1.0),
            r.ticker,
        )
    )
    return (as_of, out)
