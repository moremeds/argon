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

from uw_scan.reports.vrp_macro_signal import WINNER, MacroSignalConfig

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
