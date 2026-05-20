"""Mean-reversion signals derived from CBOE vol-complex series.

Pure functions; no DB, no network. Inputs are floats / numpy arrays.

References & calibration:

- VRP (Variance Risk Premium). **Vol-unit form**: IV − RV (both annualized
  in % points). We use the vol-unit form for practitioner readability on
  the tile. The canonical academic form (Bollerslev/Tauchen/Zhou 2009,
  "Expected Stock Returns and Variance Risk Premia", RFS 22(11)) is
  **variance-unit**: VIX² − RV². The two carry the same sign and similar
  semantics for the dashboard; we surface vol-units so the value reads in
  the same scale as VIX itself. Positive VRP (the usual case) means
  implied vol exceeds realized — compression toward zero or going
  negative often precedes vol mean-reversion. Realized vol must be
  annualized in % points (matches the units of VIX) and uses the same
  window as cri_scoring.VOL_WINDOW (currently 20 trading days).

- VIX z-score (30d). Today's VIX vs the trailing 30 closes (mean, std).
  ±2σ is the conventional mean-reversion trigger threshold per the
  rolling-z-score literature (QuantStock, iPresage). 30d is the common
  short-window lookback for daily charts.

- VIX/VIX3M ratio. Front-end vs 3-month VIX. Conventional regime bands
  (Macrosynergy "VIX term structure as a trading signal"; volradar.com):
    - < 0.85  → deep contango       (calm, premium-selling friendly)
    - 0.85–0.95 → normal contango   (the modal regime — ~85% of days)
    - 0.95–1.00 → warning / flat    (curve about to flip)
    - 1.00–1.10 → backwardation     (front-end stress, vol expansion)
    - > 1.10  → deep backwardation  (panic / dislocation)
  The cross above 1.0 from below has historically preceded every major
  drawdown in the 1990–2025 window.

See docs/research/regime/cri-methodology.md §6 for how these surface in
the UI.
"""

from __future__ import annotations

import math

import numpy as np

ZSCORE_WINDOW = 30


def compute_vrp(*, vix: float, realized_vol: float) -> float:
    """VRP = VIX (implied) − realized vol. Both in % annualized points."""
    if math.isnan(vix) or math.isnan(realized_vol):
        return float("nan")
    return float(vix - realized_vol)


def vix_zscore_30d(vix_history: np.ndarray) -> float:
    """Z-score of the latest VIX value against the trailing 30 closes.

    Returns NaN if fewer than ZSCORE_WINDOW + 1 observations are provided,
    or if the trailing std is zero (degenerate flat input) and today
    differs from the mean.
    """
    if vix_history is None or len(vix_history) < ZSCORE_WINDOW + 1:
        return float("nan")
    window = vix_history[-(ZSCORE_WINDOW + 1) : -1]
    mu = float(np.mean(window))
    sigma = float(np.std(window, ddof=1))
    if sigma == 0.0:
        return 0.0 if float(vix_history[-1]) == mu else float("nan")
    return (float(vix_history[-1]) - mu) / sigma


def vix_vix3m_ratio(*, vix: float, vix3m: float) -> float:
    """Front-end / 3-month VIX ratio. <1 contango; >1 backwardation."""
    if math.isnan(vix) or math.isnan(vix3m) or vix3m <= 0:
        return float("nan")
    return float(vix / vix3m)


def compute_pullback_20d(prices: np.ndarray) -> float:
    """Today's drawdown from the trailing-20-session high, in % points.

    Returns 0.0 when today *is* the 20d high, negative otherwise.
    NaN when fewer than 20 closes are available or the rolling high is
    non-positive (degenerate input).
    """
    if prices is None or len(prices) < 20:
        return float("nan")
    window = prices[-20:]
    high = float(np.max(window))
    today = float(window[-1])
    if high <= 0:
        return float("nan")
    return float((today / high - 1) * 100)


def compute_vix_delta_3d(vix: np.ndarray) -> float:
    """Absolute change in VIX over the last 3 sessions, in points.

    Positive = vol expanding fast. Returns NaN with fewer than 4
    observations or non-finite endpoints.
    """
    if vix is None or len(vix) < 4:
        return float("nan")
    today = float(vix[-1])
    t_minus_3 = float(vix[-4])
    if np.isnan(today) or np.isnan(t_minus_3):
        return float("nan")
    return today - t_minus_3
