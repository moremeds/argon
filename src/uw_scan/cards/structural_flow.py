"""Lens 1 — structural-flow posture composition.

Pure function: consumes repository row dataclasses, emits a posture struct
with z-scored signals and a deterministic narrative template.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class CbReserveSnapshot:
    country_iso3: str
    obs_month: date
    reserves_t: Decimal | None
    bucket: str


@dataclass(frozen=True)
class EtfHoldingSnapshot:
    ticker: str
    obs_date: date
    holdings_oz: Decimal | None


@dataclass(frozen=True)
class EtfFlowSnapshot:
    ticker: str
    obs_date: date
    share_change: Decimal | None


@dataclass(frozen=True)
class InventorySnapshot:
    exchange: str
    obs_date: date
    registered_oz: Decimal | None
    vault_oz: Decimal | None


@dataclass(frozen=True)
class CotSnapshot:
    release_date: date
    mm_net: Decimal | None


@dataclass(frozen=True)
class FxSnapshot:
    pair: str
    obs_date: date
    rate: Decimal


@dataclass(frozen=True)
class StructuralPosture:
    cb_strategic_12m_sum_t: Decimal | None
    cb_tactical_12m_sum_t: Decimal | None
    cb_diversifier_12m_sum_t: Decimal | None
    gld_holdings_t: Decimal | None
    gld_30d_net_flow_t: Decimal | None
    comex_registered_oz: Decimal | None
    comex_20d_roc_pct: Decimal | None
    cot_mm_net_pct: Decimal | None
    structural_state_label: str
    narrative_text: str


GLD_OZ_PER_SHARE_PROXY = Decimal("0.0931")
TROY_OZ_PER_TONNE = Decimal("32150.7466")


def _sum_by_bucket(
    cb_rows: list[CbReserveSnapshot], bucket: str, cutoff: date
) -> Decimal | None:
    rows = [
        r
        for r in cb_rows
        if r.bucket == bucket and r.obs_month >= cutoff and r.reserves_t is not None
    ]
    if not rows:
        return None
    return sum((r.reserves_t for r in rows), Decimal("0"))


def _percentile(values: list[Decimal], target: Decimal) -> Decimal | None:
    if not values:
        return None
    below = sum(1 for v in values if v <= target)
    return Decimal(str(below / len(values))).quantize(Decimal("0.001"))


def compute_structural_posture(
    *,
    cb_rows: list[CbReserveSnapshot],
    etf_rows: list[EtfHoldingSnapshot],
    inventory_rows: list[InventorySnapshot],
    cot_rows: list[CotSnapshot],
    fx_rows: list[FxSnapshot],
    gold_series: list[tuple[date, Decimal]],
    as_of: date,
    etf_flow_rows: list[EtfFlowSnapshot] | None = None,
) -> StructuralPosture:
    twelve_months_ago = as_of - timedelta(days=365)

    cb_strat = _sum_by_bucket(cb_rows, "strategic_accumulator", twelve_months_ago)
    cb_tact = _sum_by_bucket(cb_rows, "tactical_defender", twelve_months_ago)
    cb_div = _sum_by_bucket(cb_rows, "reserve_diversifier", twelve_months_ago)

    gld_rows = sorted(
        [r for r in etf_rows if r.ticker == "GLD" and r.holdings_oz is not None],
        key=lambda r: r.obs_date,
    )
    gld_now = gld_rows[-1].holdings_oz if gld_rows else None
    gld_holdings_t = gld_now / TROY_OZ_PER_TONNE if gld_now is not None else None

    if len(gld_rows) >= 30:
        delta_30d = gld_rows[-1].holdings_oz - gld_rows[-30].holdings_oz
        gld_30d_net_flow_t = delta_30d / TROY_OZ_PER_TONNE
    else:
        flow_cutoff = as_of - timedelta(days=30)
        gld_flow_shares = [
            r.share_change
            for r in (etf_flow_rows or [])
            if r.ticker == "GLD"
            and r.obs_date >= flow_cutoff
            and r.obs_date <= as_of
            and r.share_change is not None
        ]
        if gld_flow_shares:
            gld_30d_net_flow_t = (
                sum(gld_flow_shares, Decimal("0")) * GLD_OZ_PER_SHARE_PROXY
            ) / TROY_OZ_PER_TONNE
        else:
            gld_30d_net_flow_t = None

    comex_rows = sorted(
        [
            r
            for r in inventory_rows
            if r.exchange == "COMEX" and r.registered_oz is not None
        ],
        key=lambda r: r.obs_date,
    )
    comex_now = comex_rows[-1].registered_oz if comex_rows else None
    if len(comex_rows) >= 20 and comex_rows[-20].registered_oz not in (
        None,
        Decimal("0"),
    ):
        comex_20d_roc_pct = (
            comex_rows[-1].registered_oz - comex_rows[-20].registered_oz
        ) / comex_rows[-20].registered_oz
    else:
        comex_20d_roc_pct = None

    cot_sorted = sorted(
        [r for r in cot_rows if r.mm_net is not None and r.release_date <= as_of],
        key=lambda r: r.release_date,
    )
    if len(cot_sorted) >= 52:
        latest_mm = cot_sorted[-1].mm_net
        window = [r.mm_net for r in cot_sorted[-260:]]
        cot_mm_net_pct = _percentile(window, latest_mm)
    else:
        cot_mm_net_pct = None

    label = _classify_structural(cb_strat, gld_30d_net_flow_t, comex_20d_roc_pct)
    narrative = _narrate_structural(
        label, cb_strat, gld_30d_net_flow_t, comex_20d_roc_pct, cot_mm_net_pct
    )

    return StructuralPosture(
        cb_strategic_12m_sum_t=cb_strat,
        cb_tactical_12m_sum_t=cb_tact,
        cb_diversifier_12m_sum_t=cb_div,
        gld_holdings_t=gld_holdings_t,
        gld_30d_net_flow_t=gld_30d_net_flow_t,
        comex_registered_oz=comex_now,
        comex_20d_roc_pct=comex_20d_roc_pct,
        cot_mm_net_pct=cot_mm_net_pct,
        structural_state_label=label,
        narrative_text=narrative,
    )


def _classify_structural(
    cb_strat: Decimal | None,
    gld_flow: Decimal | None,
    comex_roc: Decimal | None,
) -> str:
    if cb_strat is not None and cb_strat > Decimal("500"):
        if gld_flow is not None and gld_flow < Decimal("0"):
            return "structural-bid-cb-led"
        return "structural-bid-intact"
    if gld_flow is not None and gld_flow > Decimal("20"):
        return "western-institutional-return"
    return "structural-mixed"


def _narrate_structural(
    label: str,
    cb_strat: Decimal | None,
    gld_flow: Decimal | None,
    comex_roc: Decimal | None,
    cot_pct: Decimal | None,
) -> str:
    parts: list[str] = []
    if label == "structural-bid-cb-led":
        parts.append(
            "Structural bid CB-led — ETF flows still outflowing, "
            "central bank accumulators dominant."
        )
    elif label == "structural-bid-intact":
        parts.append("Structural bid intact.")
    elif label == "western-institutional-return":
        parts.append(
            "Western institutional flow turning positive — "
            "possible regime reactivation signal."
        )
    else:
        parts.append("Structural posture mixed.")
    if cb_strat is not None:
        parts.append(f"CB strategic accumulators 12m sum: {cb_strat:.0f} tonnes.")
    if gld_flow is not None:
        parts.append(f"GLD 30d net flow: {gld_flow:+.1f} tonnes.")
    if comex_roc is not None:
        parts.append(f"COMEX registered 20d ROC: {comex_roc * 100:+.1f}%.")
    if cot_pct is not None:
        parts.append(f"COT managed-money net at {cot_pct * 100:.0f}th percentile.")
    return " ".join(parts)
