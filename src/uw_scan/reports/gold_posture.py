"""Orchestrator: read inputs, run all four lens cards, persist posture row.

Called by the daily `gold_posture_compute` worker job. Tracks the exact
(series_id, obs_date, as_of) triples that contributed to the row in
`inputs_jsonb` so the replay endpoint can audit posture deterministically.

Also computes the GOLD COMPASS UI payloads (spot, data_freshness,
decomposition_rows, correlation_history, posture chips, history series)
and persists them to gold_posture_daily so replay reproduces byte-for-byte.
"""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from uw_scan.cards.cyclical_zones import compute_cyclical_posture
from uw_scan.cards.regime_gauge import compute_correlation_gauge
from uw_scan.cards.structural_flow import (
    CbReserveSnapshot,
    CotSnapshot,
    EtfFlowSnapshot,
    EtfHoldingSnapshot,
    InventorySnapshot,
    compute_structural_posture,
)
from uw_scan.cards.valuation import compute_valuation_overlay
from uw_scan.macro.gold import evidence_manifest, read_gold_inputs
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


def _series_to_tuples(
    rows: list[dict[str, Any]], date_key: str
) -> list[tuple[date, Decimal]]:
    return [(r[date_key], r["value"]) for r in rows if r.get("value") is not None]


# ----- GOLD COMPASS helpers ---------------------------------------------------


def _derive_posture_chip(
    *,
    lens: str,
    state_label: str | None,
    gauge_state: str,
    valuation_flag: str | None,
    has_data: bool,
) -> str:
    """Map a lens's internal state to the UI posture chip (deterministic)."""
    if not has_data:
        return "DEGRADED"
    if lens == "L2" and gauge_state == "suspended":
        return "SUSPENDED"
    if lens == "L3":
        if valuation_flag in {"High", "Severe"}:
            return "STRETCHED"
        if valuation_flag == "Moderate":
            return "NEUTRAL"
        return "FAVORABLE"
    if state_label and any(
        tok in state_label for tok in ("intact", "favorable", "operative")
    ):
        return "FAVORABLE"
    return "NEUTRAL"


def _spot_from_gold_rows(gold_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not gold_rows or len(gold_rows) < 2:
        return None
    last_row = gold_rows[-1]
    prev_row = gold_rows[-2]
    last = Decimal(str(last_row["value"]))
    prev = Decimal(str(prev_row["value"]))
    delta_abs = last - prev
    delta_pct = delta_abs / prev if prev else Decimal("0")
    last_5 = gold_rows[-5:] if len(gold_rows) >= 5 else gold_rows
    vals = [Decimal(str(r["value"])) for r in last_5]
    return {
        "last": str(last),
        "delta_abs": str(delta_abs),
        "delta_pct": str(delta_pct),
        "high": str(max(vals)),
        "low": str(min(vals)),
        "open": str(vals[0]),
    }


def _stale_seconds(as_of: datetime, now: datetime) -> int:
    return int((now - as_of).total_seconds())


def _rolling_corr_pairs(
    s1: list[tuple[date, Decimal]],
    s2: list[tuple[date, Decimal]],
    *,
    window: int,
    step: int = 21,
) -> list[tuple[date, Decimal]]:
    """Naive monthly-stride rolling correlation of two daily series."""
    d2 = dict(s2)
    aligned: dict[date, tuple[Decimal, Decimal]] = {}
    for d, v in s1:
        if d in d2:
            aligned[d] = (v, d2[d])
    dates = sorted(aligned)
    if len(dates) < window:
        return []
    out: list[tuple[date, Decimal]] = []
    for i in range(window, len(dates), step):
        slice_dates = dates[i - window : i]
        xs = [float(aligned[d][0]) for d in slice_dates]
        ys = [float(aligned[d][1]) for d in slice_dates]
        try:
            corr = statistics.correlation(xs, ys)
        except statistics.StatisticsError as exc:
            logger.debug("rolling corr window skipped: %s", repr(exc))
            continue
        if corr != corr:  # NaN
            continue
        out.append((dates[i - 1], Decimal(str(round(corr, 4)))))
    return out


def _decomposition_rows_from_lenses(
    structural: Any, cyclical: Any, valuation: Any
) -> list[dict[str, Any]]:
    """Flatten each lens's headline heuristic z-scores into a decomposition list.

    Values are pulled from already-computed lens snapshots. Where a lens does
    not yet expose a particular z-score the entry is silently skipped (the v1
    cards expose only what they can compute). Sorted descending by |contribution|
    and capped at 12 rows."""
    rows: list[dict[str, Any]] = []
    candidates: list[tuple[str, str, Any]] = [
        ("L1", "CB Δ12M", getattr(structural, "cb_strategic_z", None)),
        ("L1", "COMEX ROC", getattr(structural, "comex_20d_roc_z", None)),
        ("L1", "ETF flow", getattr(structural, "etf_flow_z", None)),
        ("L1", "COT MM", getattr(structural, "cot_mm_z", None)),
        ("L1", "UW skew", getattr(structural, "uw_skew_z", None)),
        ("L2", "DFII10", getattr(cyclical, "dfii10_z", None)),
        ("L2", "GPR", getattr(cyclical, "gpr_z", None)),
        ("L2", "DXY", getattr(cyclical, "dxy_z", None)),
        ("L3", "Gold/CPI", getattr(valuation, "real_price_z", None)),
        ("L3", "Gold/M2", getattr(valuation, "gold_m2_z", None)),
    ]
    for lens_id, name, value in candidates:
        if value is None:
            continue
        rows.append(
            {
                "lens": lens_id,
                "factor": name,
                "contribution": str(Decimal(str(round(float(value), 3)))),
            }
        )
    rows.sort(key=lambda r: abs(float(r["contribution"])), reverse=True)
    return rows[:12]


def _pre_2022_band(
    corr_series: list[tuple[date, Decimal]],
) -> dict[str, Any] | None:
    pre = [float(v) for d, v in corr_series if d.year < 2022]
    if len(pre) < 20:
        return None
    mean = statistics.fmean(pre)
    std = statistics.pstdev(pre)
    return {
        "mean": str(Decimal(str(round(mean, 4)))),
        "std": str(Decimal(str(round(std, 4)))),
    }


# ---- derived-metric helpers (new fields wired in 044) ----


def _trailing_window(series: list[tuple[date, Decimal]], window: int) -> list[float]:
    if len(series) < window:
        return [float(v) for _, v in series]
    return [float(v) for _, v in series[-window:]]


def _rolling_z(series: list[tuple[date, Decimal]], window: int) -> Decimal | None:
    """Z-score of the latest value vs the trailing `window`-day mean/std."""
    if len(series) < window:
        return None
    vals = [float(v) for _, v in series[-window:]]
    mean = statistics.fmean(vals)
    std = statistics.pstdev(vals)
    if std == 0:
        return None
    z = (vals[-1] - mean) / std
    return Decimal(str(round(z, 4)))


def _rolling_sigma(series: list[tuple[date, Decimal]], window: int) -> Decimal | None:
    """Population stdev of the trailing `window`-day values."""
    if len(series) < window:
        return None
    vals = [float(v) for _, v in series[-window:]]
    std = statistics.pstdev(vals)
    return Decimal(str(round(std, 4)))


def _rank_percentile(series: list[tuple[date, Decimal]], window: int) -> Decimal | None:
    """Where today's value sits within the trailing window (0..1)."""
    if len(series) < 2:
        return None
    pool = _trailing_window(series, window)
    if len(pool) < 2:
        return None
    latest = pool[-1]
    leq = sum(1 for v in pool if v <= latest)
    pct = leq / len(pool)
    return Decimal(str(round(pct, 4)))


def _cot_mm_4w_change_sigma(
    cot_rows: list[CotSnapshot], *, as_of: date
) -> Decimal | None:
    """Z-score of latest managed-money net 4-week change vs trailing changes."""
    rows = sorted(
        [r for r in cot_rows if r.mm_net is not None and r.release_date <= as_of],
        key=lambda r: r.release_date,
    )
    if len(rows) < 6:
        return None
    values = [float(r.mm_net) for r in rows]
    changes = [values[idx] - values[idx - 4] for idx in range(4, len(values))]
    if len(changes) < 2:
        return None
    mean = statistics.fmean(changes)
    std = statistics.pstdev(changes)
    if std == 0:
        return None
    return Decimal(str(round((changes[-1] - mean) / std, 4)))


# Conversion constants
_OZ_PER_TONNE = Decimal("32150.7466")


def _lbma_30d_momentum_t(inv_rows: list[dict[str, Any]]) -> Decimal | None:
    """LBMA inventory is monthly; report last-month minus prior-month in tonnes."""
    rows = [r for r in inv_rows if r.get("vault_oz") is not None]
    if len(rows) < 2:
        return None
    delta_oz = Decimal(str(rows[-1]["vault_oz"])) - Decimal(str(rows[-2]["vault_oz"]))
    return (delta_oz / _OZ_PER_TONNE).quantize(Decimal("0.1"))


# ----- main orchestrator ------------------------------------------------------


def compute_and_persist_gold_posture(
    repo: Repository,
    *,
    as_of: date,
    computed_at: datetime | None = None,
) -> None:
    if computed_at is None:
        computed_at = datetime.now(UTC)

    # One read per DECLARED input, so the manifest below and the rows the lenses see
    # come from the same list. The four-entry manifest this replaces was not written
    # wrong -- it went stale as reads were added beside it, and a hand-maintained copy
    # would go stale again. See uw_scan.macro.gold.
    readings = read_gold_inputs(repo, as_of)

    gold_rows = list(readings["GLD_CLOSE"].rows)
    dfii10_rows = list(readings["DFII10"].rows)
    gold_series = _series_to_tuples(gold_rows, "obs_date")
    dfii10_series = _series_to_tuples(dfii10_rows, "obs_date")
    gauge = compute_correlation_gauge(gold_series, dfii10_series, as_of=as_of)

    cb_db_rows = list(readings["cb_gold_reserves_monthly"].rows)
    cb_snapshots = [
        CbReserveSnapshot(
            country_iso3=r["country_iso3"],
            obs_month=r["obs_month"],
            reserves_t=r.get("reserves_t"),
            bucket=r["bucket"],
        )
        for r in cb_db_rows
    ]
    etf_db = list(readings["etf_holdings_daily"].rows)
    etf_snapshots = [
        EtfHoldingSnapshot(
            ticker="GLD", obs_date=r["obs_date"], holdings_oz=r.get("holdings_oz")
        )
        for r in etf_db
    ]
    etf_flow_snapshots = [
        EtfFlowSnapshot(
            ticker="GLD",
            obs_date=r["obs_date"],
            share_change=r.get("share_change"),
        )
        for r in readings["etf_flows_daily"].rows
    ]
    inv_db = list(readings["exchange_inventory_daily"].rows)
    inv_snapshots = [
        InventorySnapshot(
            exchange="COMEX",
            obs_date=r["obs_date"],
            registered_oz=r.get("registered_oz"),
            vault_oz=None,
        )
        for r in inv_db
    ]
    cot_db = list(readings["cot_gold_weekly"].rows)
    cot_snapshots = [
        CotSnapshot(release_date=r["release_date"], mm_net=r.get("mm_net"))
        for r in cot_db
    ]

    structural = compute_structural_posture(
        cb_rows=cb_snapshots,
        etf_rows=etf_snapshots,
        inventory_rows=inv_snapshots,
        cot_rows=cot_snapshots,
        fx_rows=[],  # declared not-read: see GOLD_INPUTS['fx']
        gold_series=gold_series,
        as_of=as_of,
        etf_flow_rows=etf_flow_snapshots,
    )

    cpi_rows = list(readings["CPIAUCSL"].rows)
    cpi_now = cpi_rows[-1]["value"] if cpi_rows else None
    cpi_prior_year = next(
        (
            r["value"]
            for r in cpi_rows
            if r["obs_month"] == date(as_of.year - 1, as_of.month, 1)
        ),
        None,
    )
    cpi_yoy = (
        ((cpi_now / cpi_prior_year) - 1) * 100 if cpi_now and cpi_prior_year else None
    )

    t5yifr_rows = list(readings["T5YIFR"].rows)
    t5yifr = t5yifr_rows[-1]["value"] if t5yifr_rows else None
    dfii10 = dfii10_series[-1][1] if dfii10_series else None
    dfii10_60d_chg = None
    if len(dfii10_series) >= 60:
        dfii10_60d_chg = (dfii10_series[-1][1] - dfii10_series[-60][1]) * 100  # bps

    cyclical = compute_cyclical_posture(
        cpi_yoy=cpi_yoy,
        t5yifr=t5yifr,
        dfii10=dfii10,
        dfii10_60d_change_bps=dfii10_60d_chg,
        factors={},
        gauge_state=gauge.state,
    )

    m2_rows = list(readings["M2SL"].rows)
    m2_series = [(r["obs_month"], r["value"]) for r in m2_rows]
    valuation = compute_valuation_overlay(
        gold_series=gold_series,
        cpi_series=[(r["obs_month"], r["value"]) for r in cpi_rows],
        m2_series=m2_series,
        spx_series=[],  # declared not-read: see GOLD_INPUTS['spx']
        as_of=as_of,
    )

    # Every declared input, present or explained. The predecessor named four of twelve
    # and read as a complete audit trail, which is worse than naming none.
    inputs_used = evidence_manifest(readings)

    # ---- GOLD COMPASS UI payloads ------------------------------------------
    now = datetime.now(UTC)
    spot = _spot_from_gold_rows(gold_rows)
    has_structural = bool(cb_db_rows and etf_db and inv_db)
    has_cyclical = cpi_now is not None and t5yifr is not None and dfii10 is not None
    has_valuation = valuation.real_price_percentile is not None

    posture_chips = {
        "L1": _derive_posture_chip(
            lens="L1",
            state_label=structural.structural_state_label,
            gauge_state=gauge.state,
            valuation_flag=None,
            has_data=has_structural,
        ),
        "L2": _derive_posture_chip(
            lens="L2",
            state_label=cyclical.zone_label,
            gauge_state=gauge.state,
            valuation_flag=None,
            has_data=has_cyclical,
        ),
        "L3": _derive_posture_chip(
            lens="L3",
            state_label=None,
            gauge_state=gauge.state,
            valuation_flag=valuation.flag,
            has_data=has_valuation,
        ),
    }

    dxy_rows = repo.fetch_macro_series_daily("DTWEXBGS", to_date=as_of)
    gpr_rows = repo.fetch_macro_series_daily("GPRD", to_date=as_of)
    dxy_series = _series_to_tuples(dxy_rows, "obs_date")
    gpr_series = _series_to_tuples(gpr_rows, "obs_date")
    window5y_start = as_of - timedelta(days=365 * 5)
    gold_5y = [(d, v) for d, v in gold_series if d >= window5y_start]
    dfii10_5y = [(d, v) for d, v in dfii10_series if d >= window5y_start]
    dxy_5y = [(d, v) for d, v in dxy_series if d >= window5y_start]
    gpr_5y = [(d, v) for d, v in gpr_series if d >= window5y_start]
    corr_gold_dfii10 = _rolling_corr_pairs(gold_5y, dfii10_5y, window=252)
    corr_gold_dxy = _rolling_corr_pairs(gold_5y, dxy_5y, window=252)
    corr_gold_gpr = _rolling_corr_pairs(gold_5y, gpr_5y, window=252)

    data_freshness_inputs: dict[str, datetime | None] = {
        "FRED": dfii10_rows[-1]["as_of"] if dfii10_rows else None,
        "GPR": gpr_rows[-1]["as_of"] if gpr_rows else None,
        "ETF": etf_db[-1].get("as_of") if etf_db else None,
        "COMEX": inv_db[-1].get("as_of") if inv_db else None,
        "COT": cot_db[-1].get("as_of") if cot_db else None,
        "WGC": cb_db_rows[-1].get("as_of") if cb_db_rows else None,
    }
    data_freshness = [
        {
            "id": sid,
            "last_as_of": ts.isoformat() if ts is not None else None,
            "stale_seconds": _stale_seconds(ts, now) if ts is not None else None,
            "status": "ok" if ts is not None else "missing",
        }
        for sid, ts in data_freshness_inputs.items()
    ]

    # ---- derived metrics (044 extensions) ---------------------------------
    # FX basket (DXY) z-score over the trailing year, plus 60d volatility.
    fx_basket_dxy_z = _rolling_z(dxy_series, window=252)
    dxy_60d_sigma = _rolling_sigma(dxy_series, window=60)
    dxy_latest = dxy_series[-1][1] if dxy_series else None

    # GPR latest value + 52w rank percentile.
    gpr_latest = gpr_series[-1][1] if gpr_series else None
    gpr_pct_52w = _rank_percentile(gpr_series, window=252)

    # T5YIFR 52w rank percentile (latest already pulled above).
    t5yifr_series = _series_to_tuples(t5yifr_rows, "obs_date")
    t5yifr_pct_52w = _rank_percentile(t5yifr_series, window=252)
    cot_mm_4w_change_sigma = _cot_mm_4w_change_sigma(cot_snapshots, as_of=as_of)

    # LBMA vault: month-over-month delta in tonnes.
    lbma_rows = repo.fetch_exchange_inventory_daily(
        "LBMA", from_date=as_of - timedelta(days=400)
    )
    lbma_30d_momentum_t = _lbma_30d_momentum_t(lbma_rows)

    # UW 25Δ skew — latest GLD snapshot (A1 stores the raw decimal; a sigma
    # calibration needs more history than the 9 snapshots accumulated so far).
    uw_25d_skew_sigma: Decimal | None = None
    uw_gld_rows = repo.fetch_uw_gold_options_daily(
        "GLD", from_date=as_of - timedelta(days=30)
    )
    if uw_gld_rows:
        latest_skew = uw_gld_rows[-1].get("skew_25d_30d")
        if latest_skew is not None:
            uw_25d_skew_sigma = Decimal(str(latest_skew))

    decomposition_rows = _decomposition_rows_from_lenses(
        structural, cyclical, valuation
    )
    gld_history_rows = [
        {
            "obs_date": r["obs_date"].isoformat(),
            "value": str(Decimal(str(r["holdings_oz"])) / _OZ_PER_TONNE),
        }
        for r in etf_db
        if r["obs_date"] >= window5y_start and r.get("holdings_oz") is not None
    ]
    gold_history_rows = [
        {"obs_date": d.isoformat(), "value": str(v)} for d, v in gold_5y
    ]
    correlation_history = {
        "gold_dfii10": [
            {"obs_date": d.isoformat(), "value": str(v)} for d, v in corr_gold_dfii10
        ],
        "gold_dxy": [
            {"obs_date": d.isoformat(), "value": str(v)} for d, v in corr_gold_dxy
        ],
        "gold_gpr": [
            {"obs_date": d.isoformat(), "value": str(v)} for d, v in corr_gold_gpr
        ],
        "pre_2022_band": _pre_2022_band(corr_gold_dfii10),
    }

    repo.insert_gold_posture_daily(
        obs_date=as_of,
        computed_at=computed_at,
        gauge_corr_60d=gauge.corr_60d_level,
        gauge_corr_126d=gauge.corr_126d_level,
        gauge_corr_252d=gauge.corr_252d_level,
        gauge_corr_504d=gauge.corr_504d_level,
        gauge_corr_252d_returns=gauge.corr_252d_returns,
        gauge_state=gauge.state,
        structural_state_label=structural.structural_state_label,
        cb_strategic_12m_sum_t=structural.cb_strategic_12m_sum_t,
        cb_tactical_12m_sum_t=structural.cb_tactical_12m_sum_t,
        cb_diversifier_12m_sum_t=structural.cb_diversifier_12m_sum_t,
        gld_holdings_t=structural.gld_holdings_t,
        gld_30d_net_flow_t=structural.gld_30d_net_flow_t,
        comex_registered_oz=structural.comex_registered_oz,
        comex_20d_roc_pct=structural.comex_20d_roc_pct,
        cot_mm_net_pct=structural.cot_mm_net_pct,
        cyclical_zone_label=cyclical.zone_label,
        cpi_yoy=cyclical.cpi_yoy,
        t5yifr=cyclical.t5yifr,
        dfii10=cyclical.dfii10,
        dfii10_60d_change_bps=cyclical.dfii10_60d_change_bps,
        factors_jsonb=cyclical.factors,
        valuation_flag=valuation.flag,
        real_price_percentile=valuation.real_price_percentile,
        gold_m2_ratio_percentile=valuation.gold_m2_ratio_percentile,
        gold_spx_ratio_percentile=valuation.gold_spx_ratio_percentile,
        structural_posture_text=structural.narrative_text,
        cyclical_posture_text=cyclical.narrative_text,
        valuation_posture_text=valuation.narrative_text,
        inputs_jsonb=inputs_used,
        structural_posture_chip=posture_chips["L1"],
        cyclical_posture_chip=posture_chips["L2"],
        valuation_posture_chip=posture_chips["L3"],
        spot_jsonb=spot,
        data_freshness_jsonb=data_freshness,
        decomposition_jsonb=decomposition_rows,
        correlation_history_jsonb=correlation_history,
        gld_history_jsonb=gld_history_rows,
        gold_history_jsonb=gold_history_rows,
        # 044 extensions
        lbma_30d_momentum_t=lbma_30d_momentum_t,
        uw_25d_skew_sigma=uw_25d_skew_sigma,
        fx_basket_dxy_z=fx_basket_dxy_z,
        xau_cny_premium_pct=None,
        cb_52w_pct=None,
        cot_mm_4w_change_sigma=cot_mm_4w_change_sigma,
        t5yifr_pct_52w=t5yifr_pct_52w,
        dxy=dxy_latest,
        dxy_60d_sigma=dxy_60d_sigma,
        gpr_value=gpr_latest,
        gpr_pct_52w=gpr_pct_52w,
    )
    logger.info("gold_posture: wrote row for %s, gauge_state=%s", as_of, gauge.state)
