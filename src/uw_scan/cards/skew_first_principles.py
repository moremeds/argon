"""Pure first-principles skew derivers. No DB, no IO — dicts/lists in, scalars out.

Sign convention (UW): risk_reversal = IV(25d put) - IV(25d call).
Positive => put-skew; negative => call-skew. Stored as-is, never flipped.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def compute_spot_vol_rho(rows: list[dict], *, window: int = 63) -> float | None:
    """Pearson corr of daily delta-log(price) vs delta(IV) over the last `window`
    paired deltas. rows: dicts with 'price' and 'implied_volatility', date ASC."""
    df = pd.DataFrame(rows)
    if df.empty or len(df) < window + 1:
        return None
    px = pd.to_numeric(df.get("price"), errors="coerce")
    iv = pd.to_numeric(df.get("implied_volatility"), errors="coerce")
    if px is None or iv is None:
        return None
    dlog_px = np.log(px.where(px > 0)).diff()
    div = iv.diff()
    pair = pd.DataFrame({"dpx": dlog_px, "div": div}).dropna().tail(window)
    if len(pair) < window:
        return None
    if pair["dpx"].std(ddof=1) == 0 or pair["div"].std(ddof=1) == 0:
        return None
    rho = pair["dpx"].corr(pair["div"])
    return None if pd.isna(rho) else float(rho)


def compute_skew_baseline(
    rr_series: list[float | None], *, z_window: int = 180, pct_window: int = 252
) -> dict:
    """z = (latest - mean) / std over trailing z_window; pct = % of trailing
    pct_window strictly below latest. min 30 obs each, else None."""
    s = pd.Series([x for x in rr_series if x is not None], dtype="float64")
    if s.empty:
        return {"z": None, "pct": None, "latest": None, "n": 0}
    latest = float(s.iloc[-1])
    z = None
    zwin = s.tail(z_window)
    if len(zwin) >= 30:
        mu = float(zwin.mean())
        sd = float(zwin.std(ddof=1))
        if sd and sd > 0:
            z = (latest - mu) / sd
    pct = None
    pwin = s.tail(pct_window)
    if len(pwin) >= 30:
        pct = float((pwin < latest).mean() * 100.0)
    return {"z": z, "pct": pct, "latest": latest, "n": int(len(s))}


def classify_deviation(
    z, pct, *, z_hi: float = 1.5, pct_hi: float = 85.0, pct_lo: float = 15.0
) -> str:
    rich = (z is not None and z >= z_hi) or (pct is not None and pct >= pct_hi)
    cheap = (z is not None and z <= -z_hi) or (pct is not None and pct <= pct_lo)
    if rich and not cheap:
        return "RICH"
    if cheap and not rich:
        return "CHEAP"
    return "NORMAL"


def classify_skew_term(front_rr, back_rr, *, eps: float = 0.005) -> str:
    if front_rr is None or back_rr is None:
        return "flat"
    d = float(front_rr) - float(back_rr)
    if d > eps:
        return "front_steep"
    if d < -eps:
        return "back_steep"
    return "flat"


def classify_drive(price_trend, rho, *, eps: float = 1e-9) -> str:
    """PANIC: price falling + rho<0 (vol up as spot down = real hedging fear).
    CHASE: price rising + rho>0 (vol up as spot up = mechanical/FOMO chase)."""
    if price_trend is None or rho is None:
        return "STRUCTURAL"
    if price_trend < -eps and rho < -eps:
        return "PANIC"
    if price_trend > eps and rho > eps:
        return "CHASE"
    return "STRUCTURAL"


def classify_market_regime(spy_rv_series: list[dict]) -> str:
    """HIGH_VOL/LOW_VOL from SPY 21d realized-vol percentile (vs 252d), >50 = HIGH.
    spy_rv_series: dicts with 'price', date ASC. Self-contained; no analytics table."""
    df = pd.DataFrame(spy_rv_series)
    if df.empty or "price" not in df or len(df) < 60:
        return "UNKNOWN"
    px = pd.to_numeric(df["price"], errors="coerce")
    ret = np.log(px.where(px > 0)).diff()
    rvol = ret.rolling(21, min_periods=21).std() * np.sqrt(252)
    rvol = rvol.dropna()
    if len(rvol) < 30:
        return "UNKNOWN"
    latest = float(rvol.iloc[-1])
    pct = float((rvol.tail(252) < latest).mean() * 100.0)
    return "HIGH_VOL" if pct >= 50.0 else "LOW_VOL"


# Small static asset-class map (YAGNI — extend only when a real ticker needs it).
_INDEX_MACRO: frozenset[str] = frozenset(
    {"SPY", "SPX", "QQQ", "IWM", "DIA", "VIX", "VXX", "TLT", "GLD"}
)


def asset_class_baseline(ticker: str, *, sector: str | None = None) -> dict:
    t = (ticker or "").upper()
    sec = (sector or "").strip().lower()
    if t in _INDEX_MACRO or sec in {"macro", "index"}:
        return {"asset_class": "index_macro", "expected_sign": "put_skew"}
    if sec == "credit":
        return {"asset_class": "credit", "expected_sign": "put_skew"}
    if sec in {"sector-etf", "etf", "sector etf"}:
        return {"asset_class": "sector_etf", "expected_sign": "put_skew"}
    return {"asset_class": "single_name", "expected_sign": "mixed"}


def borrow_flag(fee_rate, days_to_cover, *, fee_htb_pct: float = 1.0) -> str:
    if fee_rate is None:
        return "unknown"
    try:
        return "hard_to_borrow" if float(fee_rate) >= fee_htb_pct else "normal"
    except (TypeError, ValueError):
        return "unknown"


def skew_sign_label(rr: float | None, *, eps: float = 1e-6) -> str:
    """Documented sign invariant: rr = IV(put)-IV(call). >0 put-skew, <0 call-skew."""
    if rr is None:
        return "unknown"
    if rr > eps:
        return "put_skew"
    if rr < -eps:
        return "call_skew"
    return "flat"


def _express_structure(deviation_class: str, lean: str) -> str:
    """Defined-risk structure expressing the lean. NO naked shorts (standing rule):
    every structure is a vertical spread or a long option — never a bare short
    call/put and never a stock-assuming 'collar'."""
    if lean == "BEARISH_TILT":
        if deviation_class == "RICH":
            # finance by selling the lower (cheaper) put wing INSIDE a debit spread
            return (
                "put-debit-spread (sell the lower put wing to finance) — defined risk"
            )
        return "put-debit-spread — defined risk"
    if lean == "BULLISH_TILT":
        if deviation_class == "CHEAP":
            return "call-debit-spread (cheap downside hedge available) — defined risk"
        return "call-debit-spread or put-credit-spread — defined risk"
    return ""


def resolve_directional_lean(
    *,
    deviation_class: str,
    drive_class: str,
    asset_class: str,
    regime: str,
    borrow_flag: str,
    earnings_gate: str,
    verdict: dict | None,
) -> dict:
    """Evidence-gated lean. Non-neutral requires a TRADABLE_* verdict AND
    borrow_flag != hard_to_borrow AND earnings_gate != block. Any gate failing
    forces NEUTRAL with the reason recorded in `basis`."""

    def neutral(basis: str) -> dict:
        return {"lean": "NEUTRAL", "confidence": "low", "basis": basis, "express": ""}

    v = (verdict or {}).get("verdict")
    if not v or v == "NONE":
        return neutral(
            "no proven separation for this bucket yet — relative-value read only"
        )
    # Hard gate: the verdict must have been validated for the CURRENT regime.
    # The assembler looks up by current regime so these normally match; this is
    # defense-in-depth (a stale/mis-keyed verdict can never leak a lean).
    if (verdict or {}).get("regime") and verdict["regime"] != regime:
        return neutral("current regime differs from the validated regime — suppressed")
    if borrow_flag == "hard_to_borrow":
        return neutral(
            "hard-to-borrow — borrow-fee confound suppresses the directional lean"
        )
    if earnings_gate == "block":
        return neutral("earnings window active — directional lean suppressed")

    conf = (verdict or {}).get("confidence") or "low"
    sep = (verdict or {}).get("forward_sep")
    sep_txt = f"{float(sep) * 100:+.1f}%/20d" if sep is not None else "validated"
    if v == "TRADABLE_BEAR":
        lean = "BEARISH_TILT"
    elif v == "TRADABLE_BULL":
        lean = "BULLISH_TILT"
    else:
        return neutral("unrecognized verdict — neutral")
    basis = (
        f"validated — {deviation_class} {asset_class} bucket separated {sep_txt} "
        f"(survived regime gate); borrow normal => edge not a borrow artifact"
    )
    return {
        "lean": lean,
        "confidence": conf,
        "basis": basis,
        "express": _express_structure(deviation_class, lean),
    }


def build_read(
    *,
    tail: str,
    rho,
    rho_confirms: bool,
    drive_class: str,
    deviation_class: str,
    asset_class: str,
    class_expected_sign: str,
    borrow_flag: str,
    earnings_gate: str,
    directional_lean: dict,
) -> dict:
    """Stitch the deterministic read. The relative-value body is interpretive;
    `directional_lean` is the only field permitted to express direction."""
    rho_txt = (
        "spot-vol corr confirms the read"
        if rho_confirms
        else "spot-vol corr does not confirm — treat as positioning, not fear"
    )
    rv_body = {
        "RICH": "skew is rich vs its own baseline — historically mean-reverts; "
        "finance the expensive wing with a defined-risk vertical spread.",
        "CHEAP": "skew is cheap vs its own baseline — downside protection is on sale.",
        "NORMAL": "skew is near its own baseline — no relative-value edge today.",
    }.get(deviation_class, "no relative-value edge today.")
    # Spec §11: summary_line is the relative-value/context body ONLY. Direction is
    # confined to `directional_lean` (the single field allowed to express it).
    summary = (
        f"{deviation_class} {tail}-skew ({asset_class}); drive={drive_class}; "
        f"{rho_txt}. {rv_body}"
    )
    return {
        "tail": tail,
        "rho": rho,
        "rho_confirms": rho_confirms,
        "drive": drive_class,
        "deviation_class": deviation_class,
        "class_context": f"{asset_class} (expected {class_expected_sign})",
        "borrow_context": borrow_flag,
        "earnings_gate": earnings_gate,
        "directional_lean": directional_lean,
        "summary_line": summary,
    }
