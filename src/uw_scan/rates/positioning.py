"""Build the rates positioning panel from CFTC TFF rows."""

from __future__ import annotations

from datetime import date
from typing import Any

from uw_scan.models import (
    RatesPositioningPanel,
    RatesPositioningRow,
    RatesSummaryTile,
)

LONG_END_TFF_CODES = {"043602", "043607", "020601", "020604"}
FRONT_END_TFF_CODES = {"042601", "044601"}


def build_positioning_panel(
    rows: list[dict[str, Any]], *, source_failed: bool = False
) -> RatesPositioningPanel:
    details = [RatesPositioningRow.model_validate(row) for row in rows]
    if not details:
        return RatesPositioningPanel(
            positioning_read=(
                "CFTC TFF Treasury futures positioning failed to refresh."
                if source_failed
                else "CFTC TFF Treasury futures positioning is not persisted yet."
            ),
            status="stale" if source_failed else "missing",
        )

    long_end = [row for row in details if row.contract_code in LONG_END_TFF_CODES]
    front_end = [row for row in details if row.contract_code in FRONT_END_TFF_CODES]
    lev_long_end = _sum_attr(long_end, "lev_money_net")
    asset_long_end = _sum_attr(long_end, "asset_mgr_net")
    dealer_long_end = _sum_attr(long_end, "dealer_net")
    lev_front_end = _sum_attr(front_end, "lev_money_net")
    basis_proxy = _basis_proxy(lev_long_end, asset_long_end)
    latest_release = max(
        (row.release_date for row in details if row.release_date is not None),
        default=None,
    )
    summary_tiles = [
        RatesSummaryTile(
            label="Leveraged funds · long end",
            value=lev_long_end,
            unit="contracts",
            status="ok" if lev_long_end is not None else "missing",
        ),
        RatesSummaryTile(
            label="Leveraged funds · front end",
            value=lev_front_end,
            unit="contracts",
            status="ok" if lev_front_end is not None else "missing",
        ),
        RatesSummaryTile(
            label="Asset managers · long end",
            value=asset_long_end,
            unit="contracts",
            status="ok" if asset_long_end is not None else "missing",
        ),
        RatesSummaryTile(
            label="Dealer/intermediary · long end",
            value=dealer_long_end,
            unit="contracts",
            status="ok" if dealer_long_end is not None else "missing",
        ),
        RatesSummaryTile(
            label="Basis proxy",
            value=basis_proxy,
            unit="contracts",
            status="ok" if basis_proxy is not None else "partial",
        ),
    ]
    return RatesPositioningPanel(
        rows=summary_tiles,
        details=details,
        positioning_read=_positioning_read(
            latest_release=latest_release,
            lev_long_end=lev_long_end,
            asset_long_end=asset_long_end,
            basis_proxy=basis_proxy,
        ),
        status=_positioning_status(summary_tiles, source_failed=source_failed),
    )


def _sum_attr(rows: list[RatesPositioningRow], attr: str) -> float | None:
    values = [getattr(row, attr) for row in rows]
    numeric = [value for value in values if value is not None]
    if not numeric:
        return None
    return float(sum(numeric))


def _basis_proxy(lev_net: float | None, asset_net: float | None) -> float | None:
    if lev_net is None or asset_net is None:
        return None
    if lev_net >= 0 or asset_net <= 0:
        return 0.0
    return min(abs(lev_net), asset_net)


def _positioning_read(
    *,
    latest_release: date | None,
    lev_long_end: float | None,
    asset_long_end: float | None,
    basis_proxy: float | None,
) -> str:
    release = latest_release.isoformat() if latest_release is not None else "latest"
    lev_text = _contracts_text(lev_long_end)
    asset_text = _contracts_text(asset_long_end)
    basis_text = _contracts_text(basis_proxy)
    return (
        f"CFTC TFF {release}: leveraged funds are net {lev_text} on long-end "
        f"Treasury futures, asset managers are net {asset_text}, and the basis proxy "
        f"is {basis_text}."
    )


def _contracts_text(value: float | None) -> str:
    if value is None:
        return "n/a"
    side = "long" if value > 0 else "short" if value < 0 else "flat"
    return f"{abs(value):,.0f} contracts {side}"


def _positioning_status(
    rows: list[RatesSummaryTile], *, source_failed: bool = False
) -> str:
    if source_failed:
        return "stale"
    if any(row.status == "ok" and row.value is not None for row in rows):
        return "ok"
    return "partial"
