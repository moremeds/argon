"""Level-1 ground-truth label derivation for VCG regime-classification accuracy.

All functions pure (no DB, no I/O). derive_level1_frame returns a DataFrame
with label_components for audit/replay payload persistence (v0.3 / CL-3).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS_PER_YEAR = 252

CANONICAL_CLASSES = ("NORMAL", "SUPPRESSED", "EDR", "RISK_OFF", "PANIC", "BOUNCE")


def compute_realized_vol(close: pd.Series, *, window: int) -> pd.Series:
    """Annualized close-to-close realized volatility on a `window`-day window."""
    returns = np.log(close / close.shift(1))
    return returns.rolling(window).std(ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR)


def compute_trailing_drawdown(close: pd.Series, *, window: int) -> pd.Series:
    """Drawdown from the rolling `window`-day peak. Always <= 0."""
    rolling_peak = close.rolling(window, min_periods=1).max()
    return close / rolling_peak - 1.0


def compute_rolling_percentile_rank(
    series: pd.Series, *, window: int, tie_rule: str = "strict_lt"
) -> pd.Series:
    """Percentile rank of current day vs prior (window-1) days.

    tie_rule (v0.3 / CO-3 — must be set explicitly to choose semantics):
        "strict_lt"     — (cohort < today).sum() / (window-1); ties -> 0
        "le"            — (cohort <= today).sum() / (window-1); ties -> 1
        "average_rank"  — mean of the above; ties -> ~0.5
    """
    if window < 2:
        raise ValueError("window must be >= 2")
    if tie_rule not in ("strict_lt", "le", "average_rank"):
        raise ValueError(
            f"tie_rule must be 'strict_lt'/'le'/'average_rank', got {tie_rule!r}"
        )

    def _rank(arr: np.ndarray) -> float:
        today = arr[-1]
        cohort = arr[:-1]
        if np.isnan(today) or np.isnan(cohort).any():
            return np.nan
        n = float(len(cohort))
        if tie_rule == "strict_lt":
            return float((cohort < today).sum()) / n
        if tie_rule == "le":
            return float((cohort <= today).sum()) / n
        return (float((cohort < today).sum()) + float((cohort <= today).sum())) / (
            2 * n
        )

    return series.rolling(window).apply(_rank, raw=True)


def classify_level1_instantaneous(row: dict, *, thresholds: dict) -> str:
    """Single-day classification — no BOUNCE/transition history.

    Precedence: PANIC > RISK_OFF > EDR > SUPPRESSED > NORMAL.
    BOUNCE is layered on by apply_bounce_state_machine per spec section 6.5.
    """
    vix_pct = row["vix_pct"]
    vvix_pct = row["vvix_pct"]
    rv_pct = row["rv_pct"]
    credit_pct = row["credit_pct"]
    dd = row["dd"]
    p_supp = thresholds["P_SUPP"]
    p_ro = thresholds["P_RO"]
    p_panic = thresholds["P_PANIC"]
    dd_edr = thresholds["DD_EDR"]
    n_low = thresholds["NORMAL_LOW"]
    n_high = thresholds["NORMAL_HIGH"]
    n_dd = thresholds["NORMAL_DD"]

    if vix_pct >= p_panic and rv_pct >= p_panic:
        return "PANIC"
    if credit_pct >= p_ro or (vix_pct >= p_ro and vvix_pct >= p_ro):
        return "RISK_OFF"
    if -dd >= dd_edr:
        return "EDR"
    if vix_pct < p_supp and rv_pct < p_supp and credit_pct < p_supp:
        return "SUPPRESSED"
    if (
        n_low <= vix_pct <= n_high
        and n_low <= vvix_pct <= n_high
        and n_low <= rv_pct <= n_high
        and n_low <= credit_pct <= n_high
        and -dd < n_dd
    ):
        return "NORMAL"
    # Fall-through: with widened NORMAL band (v0.3 / CO-4), this branch
    # should be very rare in production data — keep it as NORMAL.
    return "NORMAL"


def apply_bounce_state_machine(
    instant_labels: list[str], *, n_bounce: int
) -> list[str]:
    """Layer BOUNCE on top of instantaneous labels per spec section 6.5.

    Trigger: first non-stress day after PANIC or RISK_OFF.
    Duration: n_bounce trading days.
    Termination: PANIC/RISK_OFF reactivation closes window.
    Precedence: BOUNCE > EDR > SUPPRESSED > NORMAL during active window.
    """
    out: list[str] = []
    bounce_remaining = 0

    for i, label in enumerate(instant_labels):
        if label in ("PANIC", "RISK_OFF"):
            bounce_remaining = 0
            out.append(label)
            continue

        prior_was_stress = i > 0 and instant_labels[i - 1] in ("PANIC", "RISK_OFF")
        if prior_was_stress:
            bounce_remaining = n_bounce

        if bounce_remaining > 0:
            out.append("BOUNCE")
            bounce_remaining -= 1
        else:
            out.append(label)

    return out


def derive_level1_frame(
    *,
    vix: pd.Series,
    vvix: pd.Series,
    spx: pd.Series,
    credit_stress: pd.Series,
    thresholds: dict,
) -> pd.DataFrame:
    """Compose Level-1 labels + components + raw NFCI value (v0.3 / CL-3).

    Returns DataFrame indexed by trade_date with columns:
        truth_label   — final post-BOUNCE label
        instant_label — pre-BOUNCE instantaneous classification
        vix_pct, vvix_pct, rv_pct, credit_pct, dd — derived components
        NFCI_value    — raw NFCI input (for replay determinism — v0.3 / CL-3)
    """
    window = int(thresholds["rolling_window_days"])
    rv_window = int(thresholds["realized_vol_window_days"])
    tie_rule = thresholds.get("percentile_tie_rule", "strict_lt")

    vix_pct = compute_rolling_percentile_rank(vix, window=window, tie_rule=tie_rule)
    vvix_pct = compute_rolling_percentile_rank(vvix, window=window, tie_rule=tie_rule)
    realized = compute_realized_vol(spx, window=rv_window)
    rv_pct = compute_rolling_percentile_rank(realized, window=window, tie_rule=tie_rule)
    credit_pct = compute_rolling_percentile_rank(
        credit_stress, window=window, tie_rule=tie_rule
    )
    dd = compute_trailing_drawdown(spx, window=window)

    components = pd.DataFrame(
        {
            "vix_pct": vix_pct,
            "vvix_pct": vvix_pct,
            "rv_pct": rv_pct,
            "credit_pct": credit_pct,
            "dd": dd,
            "NFCI_value": credit_stress,  # v0.3 / CL-3 — raw input snapshot
        }
    )

    instant: list[str] = []
    valid_mask: list[bool] = []
    for _, row in components.iterrows():
        check_row = row.drop("NFCI_value")  # NFCI_value is data, not signal
        if check_row.isna().any():
            instant.append("")
            valid_mask.append(False)
            continue
        instant.append(
            classify_level1_instantaneous(check_row.to_dict(), thresholds=thresholds)
        )
        valid_mask.append(True)

    n_bounce = int(thresholds["N_BOUNCE"])
    with_bounce = apply_bounce_state_machine(instant, n_bounce=n_bounce)

    frame = components.copy()
    frame["instant_label"] = instant
    frame["truth_label"] = with_bounce
    mask = pd.Series(valid_mask, index=frame.index)
    frame.loc[~mask, "instant_label"] = pd.NA
    frame.loc[~mask, "truth_label"] = pd.NA
    return frame
