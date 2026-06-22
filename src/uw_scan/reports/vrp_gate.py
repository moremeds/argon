"""Shared eligibility gate for the VRP iron-condor backtest + candidate emitter.

Two gated paths, one per validated edge:

- **single_name** — gated on its sector's RICH bucket being `HARVEST_SELLABLE`
  (`vrp_harvest_by_sector`) AND a real earnings calendar, so the `(entry, expiry]`
  earnings exclusion is honest. This is the original v1 edge.
- **index_macro / sector_etf / credit** ("macro") — gated on that *asset class's*
  RICH bucket at the matching horizon being `HARVEST_SELLABLE`
  (`vrp_harvest_multihorizon`). No earnings requirement: indices/ETFs don't report,
  so there is no earnings landmine to exclude.

Keeping the gate in one place stops the backtest, the candidate emitter, and the
research notebook from drifting apart.
"""

from __future__ import annotations

from dataclasses import dataclass

from uw_scan.cards.skew_first_principles import asset_class_baseline


@dataclass(frozen=True)
class GateResult:
    asset_class: str
    bucket_key: str  # sector name (single_name) | asset_class label (macro)
    verdict: str = "HARVEST_SELLABLE"


def sellable_single_name_sectors(repo) -> set[str]:
    """Sectors whose RICH single-name bucket is HARVEST_SELLABLE."""
    return {
        r["sector"]
        for r in repo.fetch_vrp_harvest_by_sector()
        if r["deviation_class"] == "RICH" and r["verdict"] == "HARVEST_SELLABLE"
    }


def sellable_asset_classes(repo, *, hold_days: int) -> set[str]:
    """Non-single_name asset classes whose RICH bucket at `hold_days` is sellable.

    Matches on the exact multihorizon row (asset_class, RICH, horizon == hold_days).
    If we backtest a horizon the study never measured, no macro class matches and
    macro is conservatively excluded — single_name still gates on its own table.
    """
    out: set[str] = set()
    for r in repo.fetch_vrp_harvest_multihorizon():
        if (
            r["asset_class"] != "single_name"
            and r["deviation_class"] == "RICH"
            and r["verdict"] == "HARVEST_SELLABLE"
            and int(r["horizon"]) == int(hold_days)
        ):
            out.add(r["asset_class"])
    return out


def passes_gate(
    repo,
    ticker: str,
    *,
    sellable_sectors: set[str],
    sellable_classes: set[str],
) -> GateResult | None:
    """Return the GateResult for an admissible ticker, or None if it is gated out."""
    sector = repo.fetch_watchlist_sector(ticker)
    ac = asset_class_baseline(ticker, sector=sector)["asset_class"]
    if ac == "single_name":
        key = sector or "unknown"
        if key not in sellable_sectors:
            return None
        # No earnings calendar → can't honor the (entry, expiry] exclusion → skip,
        # else we'd manufacture a SELLABLE edge by ignoring earnings risk.
        if not repo.fetch_historical_earnings_dates(ticker):
            return None
        return GateResult(asset_class=ac, bucket_key=key)
    # macro / sector_etf / credit: gated on the per-asset-class multihorizon verdict.
    if ac not in sellable_classes:
        return None
    return GateResult(asset_class=ac, bucket_key=ac)
