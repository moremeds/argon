"""Gold-options snapshot for GLD/GDX/IAU — Phase A1 implementation.

Composes existing UW fetchers (interpolated_iv, oi_per_strike, option_contracts,
skew) and reduces them to a single per-(ticker, obs_date) snapshot row in
`uw_gold_options_daily`. Per spec §4.7 the table is persistence-only in A1:
no Lens or KPI reads from it, but the backtest accumulates history from day
one so Phase A2's consuming view has data to chart.

Two snapshot fields are intentionally `None` in A1:
- `put_25d_iv_30d` / `call_25d_iv_30d` — SkewRow exposes risk-reversal only;
  per-leg IVs require the GREEKS endpoint and would double the per-ticker
  UW call budget. Wire when the Phase A2 view actually needs them.
- `dealer_gamma_est` — would require fetch_greek_exposure across every
  expiry and a strike-weighted sum. Same justification.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ..api.client import UwClient
from ..cards.option_chain import pick_target_expiries
from ..models import InterpolatedIvRow, OiPerStrikeRow, SkewRow
from ..storage.repository import Repository
from .uw import (
    fetch_interpolated_iv,
    fetch_oi_per_strike,
    fetch_option_contracts,
    fetch_skew,
)

GOLD_OPTIONS_TICKERS: tuple[str, ...] = ("GLD", "GDX", "IAU")

_IV_TOLERANCE_DAYS = 5


@dataclass(frozen=True)
class GoldOptionsSnapshot:
    """Per-ticker daily snapshot shape for `uw_gold_options_daily`."""

    ticker: str
    obs_date: date
    atm_iv_30d: Decimal | None
    atm_iv_60d: Decimal | None
    put_25d_iv_30d: Decimal | None
    call_25d_iv_30d: Decimal | None
    skew_25d_30d: Decimal | None
    put_call_oi_ratio: Decimal | None
    dealer_gamma_est: Decimal | None


def fetch_gold_options_snapshot(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    obs_date: date,
) -> GoldOptionsSnapshot:
    """Build a single-row daily snapshot by composing existing UW fetchers."""
    interp_rows = fetch_interpolated_iv(client, repo, run_id, ticker)
    atm_iv_30d = _iv_for_days(interp_rows, days=30)
    atm_iv_60d = _iv_for_days(interp_rows, days=60)

    oi_rows = fetch_oi_per_strike(client, repo, run_id, ticker)
    pc_ratio = _put_call_oi_ratio(oi_rows)

    skew_25d_30d: Decimal | None = None
    contracts = fetch_option_contracts(client, repo, run_id, ticker, limit=500)
    expiries = pick_target_expiries(contracts, target_dtes=[30], today=obs_date)
    if expiries:
        skew_rows = fetch_skew(
            client, repo, run_id, ticker, expiries[0].isoformat(), delta=25
        )
        skew_25d_30d = _risk_reversal_25d(skew_rows)

    return GoldOptionsSnapshot(
        ticker=ticker,
        obs_date=obs_date,
        atm_iv_30d=atm_iv_30d,
        atm_iv_60d=atm_iv_60d,
        put_25d_iv_30d=None,
        call_25d_iv_30d=None,
        skew_25d_30d=skew_25d_30d,
        put_call_oi_ratio=pc_ratio,
        dealer_gamma_est=None,
    )


def _iv_for_days(rows: list[InterpolatedIvRow], *, days: int) -> Decimal | None:
    if not rows:
        return None
    best = min(rows, key=lambda r: abs(r.days - days))
    if abs(best.days - days) > _IV_TOLERANCE_DAYS:
        return None
    return best.volatility


def _put_call_oi_ratio(rows: list[OiPerStrikeRow]) -> Decimal | None:
    put_total = Decimal(0)
    call_total = Decimal(0)
    for r in rows:
        if r.put_oi is not None:
            put_total += Decimal(r.put_oi)
        if r.call_oi is not None:
            call_total += Decimal(r.call_oi)
    if call_total == 0:
        return None
    return put_total / call_total


def _risk_reversal_25d(rows: list[SkewRow]) -> Decimal | None:
    if not rows:
        return None
    for r in rows:
        if r.delta == 25:
            return r.risk_reversal
    return rows[0].risk_reversal
