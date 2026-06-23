"""$50k dollar-account ledger for the two-layer macro short-vol book.

REUSES (does not reimplement) the validated flat-vol pricing and VRP loaders:
`build_bull_put_spread` + `_settle` (P&L), `load_index_vol` (IV/spot/vrp_z),
`size_weight`/`WINNER` (the deployed 1.65-Sharpe ramp+ sizing). This layer adds the
dollar accounting the ROR engine deliberately discards: a single shared $50k
buying-power line, integer contracts floored to a risk-% of capital, capital-capped
entries (shortfalls logged, never silent), a daily margin path → utilisation, and
per-month dollar P&L → CAGR / Sharpe / maxDD.

Base layer  = WINNER (ramp+ vrp-z-sized bull put spread, weekly, DTE30, 0.25/0.125Δ).
Overlay     = binary: + overlay_mult sets of the same spread when vrp_z >= rich_threshold.

Research/engine layer — returns results; the runner (scripts/research/vrp_capital_sweep.py)
persists them. Reproduce: see that script's docstring.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as _date

from uw_scan.reports.vrp_macro_drawdown import _Loaded
from uw_scan.reports.vrp_macro_harvest import _settle
from uw_scan.reports.vrp_macro_signal import WINNER, MacroSignalConfig, size_weight
from uw_scan.reports.vrp_structure import CostModel, build_bull_put_spread

log = logging.getLogger(__name__)

CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class CapitalConfig:
    """One shared cash account. `base_risk_pct` is the fraction of `capital` that a
    full-size (w=1) base rung risks; the overlay risks `overlay_mult × base_risk_pct`
    of capital when `vrp_z >= rich_threshold`. `base_cfg` is the deployed winner."""

    capital: float = 50_000.0
    base_risk_pct: float = 0.05
    overlay_mult: float = 1.0
    rich_threshold: float = 1.0
    names: tuple[str, ...] = ("SPY", "QQQ", "IWM")
    min_date: _date | None = None
    base_cfg: MacroSignalConfig = WINNER


def desired_contracts(
    w: float, z: float | None, max_loss_per_contract: float, capcfg: CapitalConfig
) -> tuple[int, int]:
    """(base, overlay) integer contract counts before the shared-capital cap.

    base    = floor(w × base_risk_pct × capital / max_loss_per_contract)   (ramp+ w)
    overlay = floor(overlay_mult × base_risk_pct × capital / max_loss_per_contract)
              when base >= 1 and z >= rich_threshold, else 0  (binary, not w-scaled)

    The overlay is an *extra set added to a base* — if the account can't afford even
    one base contract (base == 0), there is no position to add to, so overlay is 0 too.
    This prevents a degenerate "overlay-only, no base" trade when base floors to 0 but
    overlay_mult rounds up (e.g. base_risk_pct=0.03 on SPY at $1.6k margin, overlay_mult=2).
    """
    if max_loss_per_contract <= 0:
        return 0, 0
    base = 0
    if w > 0:
        base = math.floor(
            w * capcfg.base_risk_pct * capcfg.capital / max_loss_per_contract
        )
    overlay = 0
    if (
        base >= 1
        and z is not None
        and z >= capcfg.rich_threshold
        and capcfg.overlay_mult > 0
    ):
        overlay = math.floor(
            capcfg.overlay_mult
            * capcfg.base_risk_pct
            * capcfg.capital
            / max_loss_per_contract
        )
    return base, overlay


@dataclass(frozen=True)
class Rung:
    name: str
    entry_date: _date
    exit_date: _date
    contracts: int
    margin: float
    net_pnl: float
    breached: bool


@dataclass
class AccountResult:
    rungs: list[Rung]
    monthly_excess: dict[tuple[int, int], float]
    util_by_date: list[tuple[_date, float]]
    n_desired_rungs: int
    n_skipped_rungs: int
    contracts_desired_total: int
    contracts_filled_total: int
    span: tuple[_date, _date]


def _cost_model(settings) -> CostModel:
    return CostModel(
        settings.vrp_cost_per_contract,
        settings.vrp_slippage_frac,
        settings.vrp_slippage_min,
        round_trip=settings.vrp_cost_round_trip,
    )


def simulate_account(
    loadeds: dict[str, _Loaded], settings, capcfg: CapitalConfig
) -> AccountResult:
    """Event-driven shared-$50k ledger. See module docstring + plan Task 3 semantics."""
    cfg = capcfg.base_cfg
    cost = _cost_model(settings)
    r = settings.vrp_risk_free_rate
    hold = cfg.hold_days

    # per-name lookups — capcfg.names is authoritative (KeyError if a name is missing
    # from loadeds, which is the correct loud failure; extra loadeds keys are ignored).
    iv_maps = {
        nm: {row["market_date"]: row["iv"] for row in loadeds[nm].rows}
        for nm in capcfg.names
    }
    z_maps = {
        nm: {row["market_date"]: row["vrp_z_20"] for row in loadeds[nm].rows}
        for nm in capcfg.names
    }

    # 1. candidate weekly entries across names. Same-date entries are economically
    # simultaneous; rotate their order by date ordinal so no name is systematically
    # first to consume shared buying power (plain alphabetical would bias, e.g. always
    # filling IWM/QQQ before SPY when capital binds). Rotation is unbiased on average.
    name_pos = {nm: i for i, nm in enumerate(capcfg.names)}
    k_names = max(1, len(capcfg.names))
    candidates: list[tuple[_date, str, int]] = []
    for nm in capcfg.names:
        ld = loadeds[nm]
        n = len(ld.adj)
        for pi in range(0, max(0, n - hold), cfg.cadence):
            d = ld.adj[pi][0]
            if capcfg.min_date and d < capcfg.min_date:
                continue
            candidates.append((d, nm, pi))
    candidates.sort(key=lambda c: (c[0], (name_pos[c[1]] + c[0].toordinal()) % k_names))

    # 2. simulate
    opened: list[tuple[_date, _date, float]] = []  # (entry, exit, margin)
    rungs: list[Rung] = []
    monthly: dict[tuple[int, int], float] = defaultdict(float)
    n_desired = n_skipped = desired_tot = filled_tot = 0

    for d, nm, pi in candidates:
        ld = loadeds[nm]
        iv = iv_maps[nm].get(d)
        s0 = ld.adj[pi][1]
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        z = z_maps[nm].get(d)
        w = size_weight(z, cfg)
        try:
            st = build_bull_put_spread(
                s0,
                float(iv),
                hold / 252.0,
                r,
                short_delta=cfg.short_delta,
                wing_delta=cfg.wing_delta,
            )
        except ValueError as exc:  # degenerate strikes
            log.debug("bull-put build skipped %s %s: %s", nm, d, repr(exc))
            continue
        mlpc = st.max_loss * CONTRACT_MULTIPLIER
        base_d, overlay_d = desired_contracts(w, z, mlpc, capcfg)
        total_d = base_d + overlay_d
        if total_d <= 0:
            continue
        n_desired += 1
        desired_tot += total_d
        exit_date = ld.adj[pi + hold][0]
        deployed = sum(m for (_e, xd, m) in opened if xd > d)
        available = capcfg.capital - deployed
        affordable = math.floor(available / mlpc) if mlpc > 0 else 0
        actual = min(total_d, max(0, affordable))
        if actual <= 0:
            n_skipped += 1
            log.debug(
                "capital-skip %s %s: desired=%d available=%.0f mlpc=%.0f",
                nm,
                d,
                total_d,
                available,
                mlpc,
            )
            continue
        if actual < total_d:
            log.debug("capital-partial %s %s: filled=%d/%d", nm, d, actual, total_d)
        filled_tot += actual
        net, _ror, breached, x_d, _x_spot = _settle(
            st, pi, hold, ld.adj, iv_maps[nm], r, cost=cost, contracts=actual
        )
        margin = mlpc * actual
        monthly[(x_d.year, x_d.month)] += net / capcfg.capital
        opened.append((d, exit_date, margin))
        rungs.append(Rung(nm, d, exit_date, actual, margin, net, bool(breached)))

    # 3. daily utilisation over the union of trading dates on [first_entry, last_exit).
    # Exposure is [entry, exit) so margin is already 0 on last_exit — exclude it (dd >=
    # last_exit) rather than appending a spurious zero point that would dilute util_mean.
    all_dates = sorted({dd for nm in capcfg.names for dd, _ in loadeds[nm].adj})
    lo = capcfg.min_date or (all_dates[0] if all_dates else None)
    util_by_date: list[tuple[_date, float]] = []
    if rungs and lo is not None:
        last_exit = max(r_.exit_date for r_ in rungs)
        for dd in all_dates:
            if dd < lo or dd >= last_exit:
                continue
            deployed = sum(m for (e, xd, m) in opened if e <= dd < xd)
            util_by_date.append((dd, deployed / capcfg.capital))

    if rungs:
        span = (min(r_.entry_date for r_ in rungs), max(r_.exit_date for r_ in rungs))
    else:
        span = (lo or _date(1970, 1, 1), lo or _date(1970, 1, 1))

    return AccountResult(
        rungs=rungs,
        monthly_excess=dict(monthly),
        util_by_date=util_by_date,
        n_desired_rungs=n_desired,
        n_skipped_rungs=n_skipped,
        contracts_desired_total=desired_tot,
        contracts_filled_total=filled_tot,
        span=span,
    )
