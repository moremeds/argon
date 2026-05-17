"""Gold-options snapshot for GLD/GDX/IAU — DEFERRED for Phase A1.

Phase A1 does not consume options snapshots: `uw_gold_options_daily` is
persistence-only per spec §4.7 so the backtest accumulates history from
day one, while no A1 lens or posture row reads from it.

Wiring the actual UW chain fetcher requires the same plumbing as every
other UW endpoint in this repo:
- Add `OPTIONS_CHAIN` (or similar) to `uw_scan.api.endpoints.EndpointSlug`
- Wire its path template into `build_path(slug, ticker)`
- Implement `fetch_gold_options_snapshot(client, repo, run_id, ticker, ...)`
  as a module-level free function following the `fetch_iv_rank` pattern

The typed snapshot dataclass below documents the eventual shape so the
worker job (Task 23) can either skip gold-options or persist `None`-filled
rows until the endpoint is wired.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


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
