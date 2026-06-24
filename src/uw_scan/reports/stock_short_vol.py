"""Per-ticker short-vol readout — single-name sibling of the SPX MacroSignal.

Reshapes the latest persisted vrp_daily row (iv/rv/vrp_z_20) into a TRADE/SKIP
action with a flat-vol-modeled bull put spread, gated by the sellable-by-sector
rule. Pure read-time derivation: vrp_daily is the already-persisted analytical
result, refreshed nightly by worker.volatility_jobs.nightly_vol_analytics_rollup.
"""

from __future__ import annotations

import logging
import math
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal

from uw_scan.models import StockShortVol
from uw_scan.reports.vrp_gate import evaluate_gate
from uw_scan.reports.vrp_macro_signal import WINNER, MacroSignalConfig, size_weight
from uw_scan.reports.vrp_markout import RICH_Z  # single source for the richness cutoff
from uw_scan.reports.vrp_structure import build_bull_put_spread

log = logging.getLogger(__name__)

# RICH_Z (vol "rich enough" to sell) is imported from vrp_markout — one threshold.
# ponytail: flat r mirrors settings.vrp_risk_free_rate default (config.py:311);
# tiny effect at short DTE. Thread settings here only if r ever needs to be non-default.
RISK_FREE_RATE = 0.04
# 30 trading-day hold ≈ 6 calendar weeks; exclude a name whose next earnings prints
# inside that window (the (entry, expiry] earnings landmine).
HOLD_CAL_DAYS = 45


def _finite(v: object) -> float | None:
    """Coerce to a finite float, else None. Guards against NaN/inf — the rolling
    vrp_z_20 window emits NaN on short histories (cards/vol_series.py), and Pydantic
    rejects Decimal('NaN')."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError) as exc:
        log.debug("non-finite coercion skipped: %s", repr(exc))
        return None
    return f if math.isfinite(f) else None


def _dec(v: float | None) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def _usable_iv(row: dict) -> bool:
    """The walk-back predicate: a row is usable when its iv is finite and positive."""
    iv = _finite(row.get("iv"))
    return iv is not None and iv > 0


def decide_short_vol(
    *,
    as_of: _date,
    spot: float | None,
    iv: float | None,
    rv: float | None,
    vrp: float | None,
    vrp_z_20: float | None,
    gate_ok: bool,
    next_earnings_date: _date | None,
    gate_skip_reason: str | None = None,
    require_earnings: bool = True,
    risk_free_rate: float = RISK_FREE_RATE,
    cfg: MacroSignalConfig = WINNER,
) -> StockShortVol:
    """Map one ticker's latest VRP row → TRADE/SKIP readout. Pure: no I/O.

    `gate_ok` is the result of reports.vrp_gate.passes_gate (sellable bucket). TRADE
    additionally requires vol rich (z>=RICH_Z) and a usable IV+spot. For single names
    (`require_earnings=True`) it also requires a KNOWN next-earnings date outside the
    hold window — unknown earnings conservatively SKIP (matches
    scanner.gates.earnings_gate: None → block). Macro/ETF classes don't report
    earnings (`require_earnings=False`), mirroring vrp_gate's own asset-class split.
    """
    spot = _finite(spot)
    iv = _finite(iv)
    rv = _finite(rv)
    vrp = _finite(vrp)
    z = _finite(vrp_z_20)

    common = dict(
        as_of=as_of,
        spot=_dec(spot),
        iv=_dec(iv),
        rv20=_dec(rv),
        vrp=_dec(vrp),
        vrp_z=_dec(z),
        hold_days=cfg.hold_days,
        short_delta=_dec(cfg.short_delta),
        wing_delta=_dec(cfg.wing_delta),
    )

    usable = iv is not None and iv > 0 and spot is not None and spot > 0
    rich = z is not None and z >= RICH_Z
    window_end = as_of + timedelta(days=HOLD_CAL_DAYS)

    if not usable:
        reason: str | None = "no usable IV/spot"
    elif z is None:
        reason = "insufficient vol history"
    elif not rich:
        reason = f"vol not rich (vrp_z {z:.2f} < {RICH_Z:.1f})"
    elif not gate_ok:
        # gate_skip_reason distinguishes "sector not sellable" from "no earnings
        # calendar" — both collapse the gate to None, but the user needs the real one.
        reason = gate_skip_reason or "sector vol not sellable"
    elif require_earnings and next_earnings_date is None:
        reason = "next earnings date unknown"
    elif require_earnings and next_earnings_date < as_of:
        # A past date is stale (the print already happened, the next is unknown) — not
        # "inside the window". Surface that honestly rather than mislabeling it.
        reason = "next earnings date stale"
    elif require_earnings and next_earnings_date <= window_end:
        reason = "earnings inside hold window"
    else:
        reason = None

    if reason is not None:
        return StockShortVol(
            action="SKIP", skip_reason=reason, weight=Decimal("0"), **common
        )

    # tradeable — spot/iv are finite & positive here. Build the modeled spread;
    # degenerate strikes fall back to SKIP.
    try:
        st = build_bull_put_spread(
            spot,
            iv,
            cfg.hold_days / 252.0,
            risk_free_rate,
            short_delta=cfg.short_delta,
            wing_delta=cfg.wing_delta,
        )
    except ValueError as exc:
        log.debug("degenerate short-vol spread strikes: %s", repr(exc))
        return StockShortVol(
            action="SKIP",
            skip_reason="degenerate spread strikes",
            weight=Decimal("0"),
            **common,
        )

    return StockShortVol(
        action="TRADE",
        skip_reason=None,
        weight=_dec(size_weight(z, cfg)),
        short_put=_dec(st.short_put),
        long_put=_dec(st.long_put),
        put_width=_dec(st.put_width),
        credit=_dec(st.credit),
        max_loss=_dec(st.max_loss),
        **common,
    )


def build_short_vol(repo, ticker: str, spot: float | None) -> StockShortVol | None:
    """I/O wrapper: read the most recent usable vrp_daily row, the sellable gate, and
    a reliable next-earnings date, then decide. Returns None when the ticker has no
    vrp_daily history (new/illiquid name).

    The latest row can carry a NULL iv on a day the deriver had no data, so we walk
    back to the most recent row with a usable IV (mirrors the macro sibling) rather
    than going dead on a single bad day. as_of then reflects the row actually used,
    so a stale read surfaces honestly on the card.

    Earnings come from repo.fetch_latest_next_earnings_date (most-recent reported
    next-earnings across flow_events) — more reliable than the report's
    current-top-alert promotion, which is often None even for names that report.
    """
    series = repo.fetch_vrp_daily_series(ticker, limit=7)
    if not series:
        return None
    # series is market_date DESC → the first usable row is the most recent one.
    row = next((r for r in series if _usable_iv(r)), series[0])
    # evaluate_gate computes only the sellable table this ticker's asset class needs
    # (single_name → by_sector; macro → multihorizon), not both — one scan per page.
    gate, gate_skip_reason = evaluate_gate(repo, ticker, hold_days=WINNER.hold_days)
    # Only single names carry the earnings landmine; indices/ETFs don't report
    # (vrp_gate makes the same split).
    require_earnings = gate is not None and gate.asset_class == "single_name"
    return decide_short_vol(
        as_of=row["market_date"],
        spot=spot,
        iv=row.get("iv"),
        rv=row.get("rv"),
        vrp=row.get("vrp"),
        vrp_z_20=row.get("vrp_z_20"),
        gate_ok=gate is not None,
        next_earnings_date=repo.fetch_latest_next_earnings_date(ticker),
        gate_skip_reason=gate_skip_reason,
        require_earnings=require_earnings,
    )
