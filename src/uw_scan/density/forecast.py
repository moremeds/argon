"""Orchestration for the SPX density cone — argon's port of _forward_cone.py.

The numeric core is vendored verbatim in density/{constants,cone,fit}.py; this module
reimplements only the runner glue, mirroring signal-lab's
research/runs/2026-08-01-spx-fan-forward/_forward_cone.py (@ 0f893513):
series build, the zero-tolerance agreement rail, fit -> cone -> labelled fallback,
the EWMA arm-A baseline, and row emission.

THE TRAP THIS FILE EXISTS TO PREVENT: seed_for(i) is a function of the PANEL index. The
frozen panel starts 2009-09-18; argon's vol_index_daily SPX starts 1975. Feeding the full
argon series would silently change every seed and every bootstrap draw — same model,
different numbers, no error. So the series is anchored at PANEL_FIRST_DATE and the entire
panel window must match the frozen panel positionally (dates) and exactly (closes), or we
refuse to publish.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from uw_scan.density.cone import (
    _ewma_sigma_series,
    arm_a_quantiles,
    ewma_cone,
    gjr_std_boot_cone,
)
from uw_scan.density.constants import (
    BAND_80,
    EWMA_LAMBDA,
    GJR_MIN_OBS,
    H_MAX,
    HORIZONS,
    M_PATHS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    PANEL_SHA256,
    QUANTILES,
    seed_for,
)
from uw_scan.density.fit import ARMS, _fit

ARM = "G"  # the v13-validated arm; frozen

DENSITY_BINS = 64
# Clip the histogram axis to this percentile span. With M=10,000 draws a single tail path
# can stretch a min/max range far enough to squash the body of the distribution into a
# handful of bins; the excluded draws are counted, never silently dropped.
DENSITY_CLIP = (0.005, 0.995)


class PanelMismatchError(RuntimeError):
    """DB series disagrees with the frozen panel — publishing would silently change the model."""


class SeriesTooShortError(RuntimeError):
    pass


@dataclass(frozen=True)
class ForecastResult:
    as_of: date
    anchor_close: float
    fallback_used: bool
    params: dict[str, float] | None
    seed: int
    provenance: dict[str, Any]
    rows: list[dict[str, Any]]


def _panel_path() -> Path:
    return Path(__file__).resolve().parent / "data" / "panel.parquet"


def load_frozen_panel() -> pd.DataFrame:
    """Hash raw bytes then parse — same order as _forward_cone.authenticated_panel."""
    raw = _panel_path().read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != PANEL_SHA256:
        raise PanelMismatchError(
            f"frozen panel digest {digest[:16]} != {PANEL_SHA256[:16]}"
        )
    return (
        pd.read_parquet(_panel_path()).sort_values("trade_date").reset_index(drop=True)
    )


def _forward_weekdays(anchor: date, n: int) -> list[date]:
    """_forward_cone.forward_trading_days, ported: pure weekday advance, no holiday
    calendar. An estimate for display — the settle pass corrects target_date to the
    actual H-th trading day (the model's horizon is trading days: bootstrap steps)."""
    out: list[date] = []
    d = anchor
    while len(out) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return out


def _density_bins(draws: np.ndarray) -> dict[str, Any] | None:
    """Histogram one horizon's Monte-Carlo draws, in cumulative simple-return units.

    Read-out only: these are the SAME draws `cone.cum_return_q` was taken from, so this
    adds no model surface and cannot move a quantile. Returns None when the draws are
    unusable (degenerate range), which the chart treats as "bands only".
    """
    d = np.asarray(draws, dtype=float)
    d = d[np.isfinite(d)]
    if d.size == 0:
        return None
    lo, hi = (float(x) for x in np.quantile(d, DENSITY_CLIP))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return None
    counts, _ = np.histogram(d, bins=DENSITY_BINS, range=(lo, hi))
    return {
        "lo": lo,
        "hi": hi,
        "n_bins": DENSITY_BINS,
        "counts": [int(c) for c in counts],
        "total": int(d.size),
        "clipped": int(d.size) - int(counts.sum()),
    }


def compute_forecast(
    bars: Sequence[tuple[date, float]], *, as_of: date | None = None
) -> ForecastResult:
    """bars: full SPX (trade_date, close) ascending, starting at PANEL_FIRST_DATE.

    Agreement rail over the panel window: positional date equality pins the index frame
    (seed_for is panel-index arithmetic), close equality pins the values. Either failing
    -> PanelMismatchError, never a cone.

    `as_of` truncates the series to reconstruct what the model would have issued that
    night. Truncating INSIDE the panel window is legitimate and is what v13's own
    backtest did: the prefix still starts at panel row 0, so index i remains the correct
    panel index for that date and seed_for(i) is unchanged. The rail then runs over the
    overlap. The "shorter than the panel" refusal applies only to a live run (as_of=None),
    where a short series means a stale mirror, not a deliberate rewind.
    """
    panel = load_frozen_panel()
    p_dates = [d.date() for d in pd.to_datetime(panel["trade_date"])]
    p_closes = panel["close"].to_numpy(dtype=float)
    n = len(panel)

    b_dates = [b[0] for b in bars]
    closes_all = np.array([b[1] for b in bars], dtype=float)
    if as_of is not None:
        keep = sum(1 for d in b_dates if d <= as_of)
        b_dates, closes_all = b_dates[:keep], closes_all[:keep]
    elif len(bars) < n:
        raise PanelMismatchError(
            f"db series has {len(bars)} rows, frozen panel has {n}"
        )

    # Compare over whatever part of the panel window the (possibly truncated) series
    # covers — a prefix anchored at panel row 0 pins the index frame just as well.
    m = min(len(b_dates), n)
    if b_dates[:m] != p_dates[:m]:
        k = next(j for j in range(m) if b_dates[j] != p_dates[j])
        raise PanelMismatchError(
            f"date misalignment at panel index {k}: db {b_dates[k]} != panel {p_dates[k]}"
        )
    delta = float(np.abs(closes_all[:m] - p_closes[:m]).max()) if m else 0.0
    if delta > 0:
        raise PanelMismatchError(
            f"close disagreement over the panel window: max abs {delta}"
        )

    # v13 §4.2 frame: ret = close.pct_change(); r = ret[1:] (drop the NaN row 0).
    # pct_change is a/b - 1, NOT diff/b — the two differ in float and parity pins this.
    r = closes_all[1:] / closes_all[:-1] - 1.0
    dates_r = b_dates[1:]
    closes_r = closes_all[1:]
    if r.size < GJR_MIN_OBS:
        raise SeriesTooShortError(f"{r.size} returns < GJR_MIN_OBS {GJR_MIN_OBS}")

    i = len(r) - 1  # the anchor: the freshest close that exists
    anchor_date = dates_r[i]
    anchor_close = float(closes_r[i])
    hist = r[: i + 1]
    cone_seed = int(seed_for(i))

    spec = ARMS[ARM]
    params, _attempts = _fit(spec, hist)
    fallback_used = False
    cone = None
    if params is not None:
        cone = gjr_std_boot_cone(
            hist,
            anchor_close,
            pd.Timestamp(anchor_date),
            H_MAX,
            params,
            M=M_PATHS,
            seed=cone_seed,
            burn_in=OVERLAY_BURN_IN,
            min_pool=OVERLAY_MIN_POOL,
        )
    if cone is None:
        # §4.2's fallback, labelled — never silently substituted. Same seed, by design.
        fallback_used = True
        cone = ewma_cone(
            hist,
            anchor_close,
            pd.Timestamp(anchor_date),
            H_MAX,
            lam=EWMA_LAMBDA,
            quantiles=QUANTILES,
            M=M_PATHS,
            seed=cone_seed,
        )

    # the baseline the candidate was scored against (arm A: analytic, seed-independent)
    sig = _ewma_sigma_series(r, lam=EWMA_LAMBDA)
    qa = arm_a_quantiles(sig[i], H_MAX)
    lo, hi = BAND_80
    fwd = _forward_weekdays(anchor_date, H_MAX)

    rows: list[dict[str, Any]] = []
    for h in range(1, H_MAX + 1):
        cq = cone.at(h)
        bq = qa[h - 1]
        row: dict[str, Any] = {
            "h": h,
            "target_date": fwd[h - 1],
            "scored_horizon": h in HORIZONS,
        }
        for q, v in zip(QUANTILES, cq, strict=True):
            row[f"q{round(q * 100):02d}"] = float(v)
        for q, v in zip(QUANTILES, bq, strict=True):
            row[f"baseline_q{round(q * 100):02d}"] = float(v)
        row["band80_width"] = float(cq[hi] - cq[lo])
        row["baseline_band80_width"] = float(bq[hi] - bq[lo])
        row["width_ratio"] = float((cq[hi] - cq[lo]) / (bq[hi] - bq[lo]))
        # Index samples by horizon VALUE, matching Cone.at()'s contract — arms whose
        # horizons are non-contiguous would break a bare h-1.
        row["density_bins_jsonb"] = None
        if cone.samples is not None:
            j = int(np.where(cone.horizons == h)[0][0])
            row["density_bins_jsonb"] = _density_bins(cone.samples[j])
        rows.append(row)

    params_j: dict[str, float] | None = None
    if params is not None:
        params_j = {k: float(v) for k, v in params.items()}
        params_j["persistence"] = (
            params_j["alpha"] + params_j["gamma"] / 2.0 + params_j["beta"]
        )

    provenance = {
        "arm": ARM,
        "panel_sha256": PANEL_SHA256,
        "series_index": i,
        "n_returns": int(hist.size),
        "cone_seed": cone_seed,
        "overlap_days_checked": n,
        "max_abs_close_disagreement": delta,
        "fresh_bars_beyond_panel": len(b_dates) - n,
        "anchor_date": str(anchor_date),
    }
    return ForecastResult(
        as_of=anchor_date,
        anchor_close=anchor_close,
        fallback_used=fallback_used,
        params=params_j,
        seed=cone_seed,
        provenance=provenance,
        rows=rows,
    )


def result_to_db_rows(result: ForecastResult, *, origin: str) -> list[dict[str, Any]]:
    return [
        {
            "as_of": result.as_of,
            "anchor_close": result.anchor_close,
            "params_jsonb": result.params,
            "fallback_used": result.fallback_used,
            "origin": origin,
            "provenance_jsonb": result.provenance,
            **row,
        }
        for row in result.rows
    ]
