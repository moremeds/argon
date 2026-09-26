"""Macro short-vol signal — the promoted winner config + its laddered/sized
backtest + a current-week readout for (manual or automated) execution.

The 20-yr SPX+VIX sweep (docs/research/vrp/_iterations/macro-short-vol-verdict.md, reproduced
by scripts/_vrp_macro_param_sweep.py) found the dominant lever is **sizing by how
rich vol is**, not the structure or the entry-spacing. The winner:

    bull put spread · short_delta 0.25 / wing 0.125 · ~30 trading-day hold ·
    weekly entry · `ramp+` vrp-z sizing (0 at z<=0, full at z>=0.5) · hold to expiry

→ SPX monthly-ROR Sharpe ~1.65 (in-sample-tuned; discount to ~1.3-1.6 live),
and the *same* config rescues QQQ from 0.27 to 1.00 out-of-sample — i.e. the edge
is structural index-VRP, not SPX-overfit.

This module makes that config first-class engine code instead of script-only:
`WINNER` is the canonical default, `backtest_laddered` is the tested engine that
reproduces the note's headline Sharpe, and `current_macro_signal` emits the
actionable weekly readout (vrp_z → size weight → strikes/credit/max-loss).

Research/engine layer: like `vrp_macro_drawdown`, it returns results rather than
persisting them. Wiring `current_macro_signal` to a nightly job + table (so the
weekly readout lands in Postgres and the UI) is the deploy step, deliberately
left out of this slice.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from math import sqrt
from statistics import fmean, pstdev
from typing import Any
from zoneinfo import ZoneInfo

from uw_scan.reports.vrp_macro_drawdown import (
    SIGNAL_LOOKBACK_DAYS,
    _Loaded,
    load_index_vol,
)
from uw_scan.reports.vrp_macro_harvest import _settle
from uw_scan.reports.vrp_structure import (
    BullPutSpread,
    CostModel,
    build_bull_put_spread,
    legs_from_strike_ivs,
    select_bull_put_spread,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MacroSignalConfig:
    """The promoted winner. Defaults ARE the canonical config; override per call
    only for research. `wing_delta = short_delta * wing_frac` keeps the long wing
    strictly inside the short strike (0 < wing < short < 0.5)."""

    short_delta: float = 0.25
    wing_frac: float = 0.5  # → wing_delta 0.125
    hold_days: int = 30  # ~30 trading days ≈ 40-45 calendar DTE (VIX is 30d IV)
    cadence: int = 5  # weekly entry (5 trading days)
    sizing: str = "ramp+"  # the dominant lever; see size_weight()
    ramp_full_z: float = 0.5  # full size at vrp_z >= this; 0 at z <= 0
    structure: str = "bull_put_spread"

    @property
    def wing_delta(self) -> float:
        return self.short_delta * self.wing_frac


WINNER = MacroSignalConfig()


def size_weight(z: float | None, cfg: MacroSignalConfig = WINNER) -> float:
    """vrp-z → position-size multiplier in [0, 1]. `always` ignores the signal;
    every gated rule treats an undefined z (insufficient history) as skip (0).
        gate0 : 1 if z>=0 else 0
        ramp  : 1 at z>=0, linear→0 at z=-ramp_full_z, 0 below
        ramp+ : 0 at z<=0, linear→1 at z>=ramp_full_z   (the winner)"""
    if cfg.sizing == "always":
        return 1.0
    if z is None:
        return 0.0
    if cfg.sizing == "gate0":
        return 1.0 if z >= 0 else 0.0
    if cfg.sizing == "ramp":
        return 1.0 if z >= 0 else max(0.0, (z + cfg.ramp_full_z) / cfg.ramp_full_z)
    if cfg.sizing == "ramp+":
        return min(1.0, max(0.0, z / cfg.ramp_full_z))
    raise ValueError(f"unknown sizing rule {cfg.sizing!r}")


def _sharpe_maxdd(monthly: dict) -> tuple[float, float, float]:
    """Zero-fill the contiguous month span; return (annualized Sharpe, maxDD of the
    cumulative curve, annualized mean return). ROR excludes the risk-free rate (it is
    earned on collateral), so monthly ROR is already an excess return."""
    if not monthly:
        return float("nan"), 0.0, 0.0
    yms = sorted(monthly)
    (y0, m0), (y1, m1) = yms[0], yms[-1]
    series: list[float] = []
    y, m = y0, m0
    while (y, m) <= (y1, m1):
        series.append(monthly.get((y, m), 0.0))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    sd = pstdev(series)
    sharpe = fmean(series) / sd * sqrt(12) if sd > 0 else float("nan")
    cum = peak = mdd = 0.0
    for x in series:
        cum += x
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return sharpe, mdd, fmean(series) * 12


def _cost_model(settings) -> CostModel:
    return CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )


def backtest_laddered(
    loaded: _Loaded,
    settings,
    cfg: MacroSignalConfig = WINNER,
    *,
    min_date: _date | None = None,
) -> dict[str, Any]:
    """Weekly-laddered, vrp-z-sized bull-put-spread backtest — the engine version of
    the research sweep's winning cell. Constant-risk (slot-account): each month's
    book return is the size-weighted sum of rung RORs exiting that month, divided by
    the number of concurrent slots (≈ hold_days / cadence). Returns monthly-ROR
    Sharpe, maxDD, Calmar and the per-month series (so sleeves can be composed)."""
    if cfg.structure != "bull_put_spread":
        raise ValueError(
            f"backtest_laddered only supports bull_put_spread, got {cfg.structure!r}"
        )
    adj = loaded.adj
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    z_map = {row["market_date"]: row["vrp_z_20"] for row in loaded.rows}
    cost = _cost_model(settings)
    r = settings.vrp_risk_free_rate
    n = len(adj)
    max_slots = max(1, round(cfg.hold_days / cfg.cadence))
    by_month: dict[tuple[int, int], float] = defaultdict(float)
    nrung = 0
    for pi in range(0, n - cfg.hold_days, cfg.cadence):
        d, s0 = adj[pi]
        if min_date and d < min_date:
            continue
        iv = iv_map.get(d)
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        w = size_weight(z_map.get(d), cfg)
        if w <= 0:
            continue
        try:
            st = build_bull_put_spread(
                s0,
                float(iv),
                cfg.hold_days / 252.0,
                r,
                short_delta=cfg.short_delta,
                wing_delta=cfg.wing_delta,
            )
        except ValueError as exc:  # degenerate strikes — skip this rung
            log.debug("bull-put-spread build skipped on %s: %s", d, repr(exc))
            continue
        _net, ror, _breached, exit_date, _spot = _settle(
            st, pi, cfg.hold_days, adj, iv_map, r, cost=cost, contracts=1
        )
        by_month[(exit_date.year, exit_date.month)] += w * ror
        nrung += 1
    monthly = {k: v / max_slots for k, v in by_month.items()}
    sharpe, maxdd, annror = _sharpe_maxdd(monthly)
    return {
        "n": nrung,
        "sharpe": sharpe,
        "maxdd": maxdd,
        "annror": annror,
        "calmar": (annror / abs(maxdd)) if maxdd < 0 else float("inf"),
        "monthly": monthly,
    }


@dataclass(frozen=True)
class MacroSignal:
    """The actionable weekly readout. `action` is TRADE iff `weight > 0`; on SKIP the
    structure fields are None.

    `strike_basis` says how the strikes were obtained, and it is never silent:

    - ``"listed_skew"`` — real listed strikes from the nightly
      `vrp_macro_entry_grid`, each leg priced off its OWN captured IV.
      `short_put_delta` / `long_put_delta` are then the deltas those strikes
      ACTUALLY carry, and `expiry` / `strike_grid_date` name the grid used.
    - ``"flat_vol_model"`` — no grid for this name (QQQ/IWM have none), so the
      strikes come from inverting one flat ATM vol. Under put skew the wing
      lands too shallow (its true delta is well above the target), so these are
      modeled strikes, not tradeable listed ones; the deltas are None.
    """

    name: str
    as_of: _date
    spot: float
    iv: float
    rv20: float | None
    vrp: float | None
    vrp_z: float | None
    weight: float
    action: str  # "TRADE" | "SKIP"
    short_put: float | None
    long_put: float | None
    credit: float | None
    max_loss: float | None
    put_width: float | None
    hold_days: int
    short_delta: float
    wing_delta: float
    short_put_delta: float | None = None
    long_put_delta: float | None = None
    strike_basis: str | None = None
    strike_grid_date: _date | None = None
    expiry: _date | None = None


def _resolve_spread(
    repo,
    settings,
    name: str,
    cfg: MacroSignalConfig,
    *,
    spot: float,
    iv: float,
    as_of: _date,
) -> tuple[BullPutSpread, dict[str, Any]]:
    """Strikes for a TRADE, skew-aware when we have a real chain to read.

    Preferred: the nightly `vrp_macro_entry_grid` (the same cache the entry-capture
    path reads) supplies the listed strikes plus each strike's own IV → the legs
    sit where the target deltas ACTUALLY are. Fallback: `build_bull_put_spread`,
    one flat ATM vol, labeled `flat_vol_model` so nobody reads its wing as a
    delta-true listed strike."""
    r = settings.vrp_risk_free_rate
    grid = repo.fetch_vrp_macro_entry_grid(name, as_of)
    if grid and grid.get("strike_ivs"):
        expiry = grid["chosen_expiry"]
        T = max((expiry - as_of).days, 1) / 365.0
        sel = select_bull_put_spread(
            legs_from_strike_ivs(spot, T, r, grid["strike_ivs"]),
            spot,
            T,
            r,
            short_delta=cfg.short_delta,
            wing_delta=cfg.wing_delta,
        )
        if sel is not None:
            return sel.spread, {
                "short_put_delta": sel.short_delta,
                "long_put_delta": sel.wing_delta,
                "strike_basis": "listed_skew",
                "strike_grid_date": grid["for_date"],
                "expiry": expiry,
            }
        log.warning(
            "%s: strike grid %s could not bracket the wing — flat-vol fallback",
            name,
            grid.get("for_date"),
        )
    st = build_bull_put_spread(
        spot,
        iv,
        cfg.hold_days / 252.0,
        r,
        short_delta=cfg.short_delta,
        wing_delta=cfg.wing_delta,
    )
    return st, {
        "short_put_delta": None,
        "long_put_delta": None,
        "strike_basis": "flat_vol_model",
        "strike_grid_date": None,
        "expiry": None,
    }


def current_macro_signal(
    repo,
    settings,
    name: str = "SPX",
    cfg: MacroSignalConfig = WINNER,
    *,
    as_of: _date | None = None,
    lake_root=None,
) -> MacroSignal:
    """Compute this week's signal for `name` (default SPX) as of `as_of` (default the
    latest available close). Picks the most recent row with usable IV+spot on or
    before the cutoff, maps vrp_z → size weight, and (if trading) builds the modeled
    bull put spread to quote strikes/credit/max-loss for a manual or automated fill."""
    since = (as_of or _date.today()) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
    loaded = load_index_vol(repo, name, lake_root=lake_root, since=since)
    spot_map = dict(loaded.adj)
    chosen: dict | None = None
    for row in reversed(loaded.rows):
        d = row["market_date"]
        if as_of is not None and d > as_of:
            continue
        iv = row["iv"]
        if iv is None or iv <= 0 or spot_map.get(d, 0.0) <= 0:
            continue
        chosen = row
        break
    if chosen is None:
        raise ValueError(f"no usable {name} vol row on or before {as_of or 'latest'}")
    d = chosen["market_date"]
    spot = spot_map[d]
    iv = float(chosen["iv"])
    z = chosen["vrp_z_20"]
    w = size_weight(z, cfg)
    common = dict(
        name=name,
        as_of=d,
        spot=spot,
        iv=iv,
        rv20=chosen.get("rv"),
        vrp=chosen.get("vrp"),
        vrp_z=z,
        hold_days=cfg.hold_days,
        short_delta=cfg.short_delta,
        wing_delta=cfg.wing_delta,
    )
    if w <= 0:
        return MacroSignal(
            weight=0.0,
            action="SKIP",
            short_put=None,
            long_put=None,
            credit=None,
            max_loss=None,
            put_width=None,
            **common,
        )
    st, strikes = _resolve_spread(repo, settings, name, cfg, spot=spot, iv=iv, as_of=d)
    return MacroSignal(
        weight=w,
        **strikes,
        action="TRADE",
        short_put=st.short_put,
        long_put=st.long_put,
        credit=st.credit,
        max_loss=st.max_loss,
        put_width=st.put_width,
        **common,
    )


def current_macro_signal_live(
    repo,
    settings,
    name: str = "SPX",
    cfg: MacroSignalConfig = WINNER,
    *,
    live_spot: float,
    live_iv: float,
    as_of: _date | None = None,
    lake_root=None,
) -> MacroSignal:
    """Live variant of `current_macro_signal`: spot/iv come from an intraday quote
    (index spot + VIX/100), while rv20 and the trailing-252d vrp distribution are the
    latest EOD values. vrp_z is recomputed as the EOD path does — population z-score of
    `live_iv - rv20` against the trailing 252 EOD vrp values (matching
    vrp_macro_drawdown._build_loaded: fmean/pstdev, z_window=252).

    Convention (codex-review ISSUE-1): the z-window is the trailing-252 EOD vrp ending at
    the latest EOD row and does NOT include live_vrp itself. This (a) is well-defined
    whether or not today's EOD bar exists and (b) reproduces the EOD vrp_z exactly when
    live_iv == eod_iv (the live<->eod invariant)."""
    # Guard bad ticks (zero/negative VIX or spot). The EOD path skips rows with iv<=0;
    # do the same here. Raising ValueError lets the endpoint fall back to EOD and the
    # worker's per-leg try/except skip — never feed a garbage iv into build_bull_put_spread.
    if live_iv <= 0 or live_spot <= 0:
        raise ValueError(
            f"{name}: non-positive live quote (spot={live_spot}, iv={live_iv})"
        )
    since = (as_of or _date.today()) - timedelta(days=SIGNAL_LOOKBACK_DAYS)
    loaded = load_index_vol(repo, name, lake_root=lake_root, since=since)
    # latest EOD row with a usable rv (rv is None for the first rv_window days);
    # capture its index directly — do NOT use list.index() (rows are dicts → ambiguous).
    eod = None
    eod_idx = -1
    n = len(loaded.rows)
    for back, row in enumerate(reversed(loaded.rows)):
        if as_of is not None and row["market_date"] > as_of:
            continue
        if row.get("rv") is not None:
            eod = row
            eod_idx = n - 1 - back
            break
    if eod is None:
        raise ValueError(f"no usable {name} rv row on or before {as_of or 'latest'}")
    rv20 = float(eod["rv"])
    live_vrp = live_iv - rv20
    hist = [r["vrp"] for r in loaded.rows[: eod_idx + 1] if r["vrp"] is not None]
    z: float | None = None
    if len(hist) >= 252:
        w_ = hist[-252:]
        sd = pstdev(w_)
        z = (live_vrp - fmean(w_)) / sd if sd > 0 else None
    weight = size_weight(z, cfg)  # size_weight returns 0.0 when z is None
    common = dict(
        name=name,
        as_of=eod["market_date"],
        spot=live_spot,
        iv=live_iv,
        rv20=rv20,
        vrp=live_vrp,
        vrp_z=z,
        hold_days=cfg.hold_days,
        short_delta=cfg.short_delta,
        wing_delta=cfg.wing_delta,
    )
    if weight <= 0:
        return MacroSignal(
            weight=0.0,
            action="SKIP",
            short_put=None,
            long_put=None,
            credit=None,
            max_loss=None,
            put_width=None,
            **common,
        )
    st, strikes = _resolve_spread(
        repo,
        settings,
        name,
        cfg,
        spot=live_spot,
        iv=live_iv,
        # Value the structure at the LIVE date: the grid lookup's staleness window
        # and T both key off it. The EOD row's market_date can be several days back
        # (a vol-data gap walks it back), which would price a stale, too-long T.
        # Every statistical field above stays on eod["market_date"].
        as_of=as_of
        if as_of is not None
        else datetime.now(ZoneInfo("America/New_York")).date(),
    )
    return MacroSignal(
        weight=weight,
        **strikes,
        action="TRADE",
        short_put=st.short_put,
        long_put=st.long_put,
        credit=st.credit,
        max_loss=st.max_loss,
        put_width=st.put_width,
        **common,
    )
