"""Build the rates Treasury supply panel."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from uw_scan.models import (
    RatesSupplyAuctionRow,
    RatesSupplyPanel,
    RatesSummaryTile,
)
from uw_scan.rates.utils import latest_float


def build_supply_panel(
    observations: dict[str, list[dict[str, Any]]],
    *,
    as_of: date,
    auction_rows: list[dict[str, Any]],
    debt_row: dict[str, Any] | None,
    source_failed: bool = False,
) -> RatesSupplyPanel:
    auction_details = [
        RatesSupplyAuctionRow.model_validate(_auction_payload(row))
        for row in auction_rows
    ]
    display_auctions = _select_display_auctions(auction_details)
    fiscal = _supply_fiscal_tiles(observations, as_of=as_of, debt_row=debt_row)
    if not display_auctions and not fiscal:
        return RatesSupplyPanel(
            notes=[
                "Treasury auction and FiscalData supply feeds failed to refresh."
                if source_failed
                else "Treasury auction and FiscalData supply feeds are not persisted yet."
            ],
            status="stale" if source_failed else "missing",
        )
    status = "ok" if display_auctions and _has_live_debt_tile(fiscal) else "partial"
    if source_failed:
        status = "stale"
    return RatesSupplyPanel(
        auctions=_supply_summary_tiles(display_auctions, auction_details),
        recent_auctions=display_auctions,
        fiscal=fiscal,
        notes=[] if status == "ok" else ["Some Treasury supply inputs are unavailable."],
        supply_read=_supply_read(display_auctions, fiscal),
        status=status,
    )


def _auction_payload(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    amount = out.get("offering_amount")
    if amount is not None:
        amount_dec = amount if isinstance(amount, Decimal) else Decimal(str(amount))
        out["offering_amount"] = float(
            (amount_dec / Decimal("1000000000")).quantize(Decimal("0.1"))
        )
    for key in (
        "high_rate",
        "bid_to_cover",
        "direct_bidder_pct",
        "indirect_bidder_pct",
        "primary_dealer_pct",
    ):
        value = out.get(key)
        if value is not None:
            out[key] = float(value if isinstance(value, Decimal) else Decimal(str(value)))
    return out


def _select_display_auctions(
    auctions: list[RatesSupplyAuctionRow],
) -> list[RatesSupplyAuctionRow]:
    if not auctions:
        return []
    latest_by_bucket: dict[str, RatesSupplyAuctionRow] = {}
    for row in sorted(auctions, key=lambda item: item.auction_date, reverse=True):
        bucket = row.tail_indicator or "other"
        latest_by_bucket.setdefault(bucket, row)
    preferred = ["long-end", "belly", "front-end", "bill"]
    selected = [latest_by_bucket[key] for key in preferred if key in latest_by_bucket]
    if len(selected) < 4:
        seen = {(row.cusip, row.auction_date) for row in selected}
        for row in sorted(auctions, key=lambda item: item.auction_date, reverse=True):
            key = (row.cusip, row.auction_date)
            if key not in seen:
                selected.append(row)
                seen.add(key)
            if len(selected) >= 4:
                break
    return selected[:4]


def _supply_summary_tiles(
    display_auctions: list[RatesSupplyAuctionRow],
    all_auctions: list[RatesSupplyAuctionRow],
) -> list[RatesSummaryTile]:
    tiles: list[RatesSummaryTile] = []
    long_end = next(
        (row for row in display_auctions if row.tail_indicator == "long-end"), None
    )
    if long_end is not None:
        tiles.append(
            RatesSummaryTile(
                label="Long-end BTC",
                value=long_end.bid_to_cover,
                unit="x",
                status="ok" if long_end.bid_to_cover is not None else "missing",
            )
        )
    coupon_amount = _auction_amount_sum(
        row for row in all_auctions if row.security_type in {"Note", "Bond"}
    )
    if coupon_amount is not None:
        tiles.append(
            RatesSummaryTile(
                label="Coupon auctions",
                value=coupon_amount,
                unit="$bn",
                status="ok",
            )
        )
    bill_share = _bill_share(all_auctions)
    if bill_share is not None:
        tiles.append(
            RatesSummaryTile(
                label="Bill share",
                value=bill_share,
                unit="%",
                status="ok",
            )
        )
    return tiles


def _auction_amount_sum(rows) -> float | None:
    values = [row.offering_amount for row in rows if row.offering_amount is not None]
    if not values:
        return None
    return float(sum(values))


def _bill_share(auctions: list[RatesSupplyAuctionRow]) -> float | None:
    total = _auction_amount_sum(auctions)
    bills = _auction_amount_sum(row for row in auctions if row.security_type == "Bill")
    if total in (None, 0) or bills is None:
        return None
    return round(bills / total * 100, 1)


def _supply_fiscal_tiles(
    observations: dict[str, list[dict[str, Any]]],
    *,
    as_of: date,
    debt_row: dict[str, Any] | None,
) -> list[RatesSummaryTile]:
    tiles: list[RatesSummaryTile] = []
    if debt_row:
        public_debt = _trillion(debt_row.get("debt_held_public"))
        total_debt = _trillion(debt_row.get("total_public_debt"))
        tiles.extend(
            [
                RatesSummaryTile(
                    label="Public debt",
                    value=public_debt,
                    unit="$T",
                    status="ok" if public_debt is not None else "missing",
                ),
                RatesSummaryTile(
                    label="Total debt",
                    value=total_debt,
                    unit="$T",
                    status="ok" if total_debt is not None else "missing",
                ),
            ]
        )
    tga = latest_float(observations, "WTREGEN", as_of, divisor=1_000_000)
    if tga is not None:
        tiles.append(
            RatesSummaryTile(
                label="TGA",
                value=tga,
                unit="$T",
                status="ok",
            )
        )
    return tiles


def _trillion(value: Any) -> float | None:
    if value is None:
        return None
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    return float((dec / Decimal("1000000000000")).quantize(Decimal("0.01")))


def _supply_read(
    auctions: list[RatesSupplyAuctionRow], fiscal: list[RatesSummaryTile]
) -> str | None:
    parts: list[str] = []
    long_end = next((row for row in auctions if row.tail_indicator == "long-end"), None)
    if long_end is not None:
        tone = _auction_tone(long_end)
        parts.append(
            "TreasuryDirect auction results show "
            f"{long_end.security_term} {long_end.security_type} demand is {tone}"
        )
    fiscal_by_label = {item.label: item for item in fiscal}
    if public_debt := fiscal_by_label.get("Public debt"):
        if public_debt.value is not None:
            parts.append(f"FiscalData public debt is ${public_debt.value:.2f}T")
    if tga := fiscal_by_label.get("TGA"):
        if tga.value is not None:
            parts.append(f"TGA is ${tga.value:.2f}T")
    return "; ".join(parts) + "." if parts else None


def _has_live_debt_tile(fiscal: list[RatesSummaryTile]) -> bool:
    debt_labels = {"Public debt", "Total debt"}
    return any(
        tile.label in debt_labels and tile.status == "ok" and tile.value is not None
        for tile in fiscal
    )


def _auction_tone(row: RatesSupplyAuctionRow) -> str:
    bid_to_cover = row.bid_to_cover
    if bid_to_cover is None:
        return "unclassified"
    if row.tail_indicator == "long-end" and bid_to_cover < 2.35:
        return "soft"
    if bid_to_cover >= 2.6:
        return "firm"
    return "mixed"
