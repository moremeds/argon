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
    """Term structure of 25Δ RR: front (nearest) vs back (furthest) expiry.

    Returns 'unknown' when a second expiry is missing — most ticker-dates carry a
    single expiry, and one point is NOT evidence of a flat term structure.
    Conflating the two would poison the markout-ready snapshot store: a later
    term-structure markout could not tell 'no data' from 'genuinely flat'."""
    if front_rr is None or back_rr is None:
        return "unknown"
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
    """FALLBACK market regime from SPY 21d realized-vol percentile (vs 252d).

    HIGH_VOL only at the >=70th percentile (genuinely elevated), not the 50th — a
    coin-flip split labelled half of all days HIGH_VOL and carried no information.
    This is the fallback only: the canonical regime tag is the latest CRI level
    (Repository.fetch_latest_market_regime); this is used when no CRI snapshot exists.
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
    return "HIGH_VOL" if pct >= 70.0 else "LOW_VOL"


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
    except (TypeError, ValueError) as exc:
        log.debug("borrow_flag coercion skipped: %s", repr(exc))
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


# Defined-risk structure families keyed on the EVIDENCE-GATED lean (never on
# deviation×tail posture — see Phase-2 hardening correction A). Both are long-premium
# debit spreads: max loss = net debit, no naked leg. Target deltas pick the wings.
_STRUCTURE_FAMILIES: dict[str, dict] = {
    "BEARISH_TILT": {
        "kind": "put_debit_spread",
        "legs": [
            {"action": "BUY", "right": "PUT", "target_delta": -0.25},
            {"action": "SELL", "right": "PUT", "target_delta": -0.12},
        ],
    },
    "BULLISH_TILT": {
        "kind": "call_debit_spread",
        "legs": [
            {"action": "BUY", "right": "CALL", "target_delta": 0.25},
            {"action": "SELL", "right": "CALL", "target_delta": 0.12},
        ],
    },
}

_FAMILY_PHRASE = {
    "put_debit_spread": "put-debit-spread — defined risk",
    "call_debit_spread": "call-debit-spread — defined risk",
}


def structure_family(directional_lean: dict) -> dict | None:
    """Structure descriptor for an already-gated lean. None for NEUTRAL — V1's
    anti-overtrading default. Single source consumed by both _express_structure
    (the string) and select_structure_legs (the concrete strikes)."""
    return _STRUCTURE_FAMILIES.get((directional_lean or {}).get("lean") or "")


def _express_structure(deviation_class: str, lean: str) -> str:
    """Defined-risk structure string. NO naked shorts: every structure is a debit
    vertical (long premium, max loss = net debit). Derived from structure_family so the
    string and the concrete legs (select_structure_legs) never drift."""
    fam = structure_family({"lean": lean})
    if fam is None:
        return ""
    return _FAMILY_PHRASE.get(fam["kind"], "")


def select_structure_legs(
    *,
    family: dict | None,
    exposure_rows: list[dict],
    dte_lo: int = 21,
    dte_hi: int = 60,
    dte_pref: int = 35,
    earnings_note: str = "",
) -> dict:
    """Pick concrete legs for `family` by nearest target delta within one expiry.
    Pure — exposure_rows: dicts with expiry, strike, dte, put_delta/call_delta.
    Returns a structure_detail dict (kind, legs, dte_target, status, note)."""
    if family is None:
        return {
            "kind": "",
            "legs": [],
            "dte_target": None,
            "status": "suppressed",
            "note": "",
        }
    # candidate expiries inside the swing window; prefer the one nearest dte_pref
    by_expiry: dict = {}
    for r in exposure_rows or []:
        dte = r.get("dte")
        if dte is None or not (dte_lo <= int(dte) <= dte_hi):
            continue
        by_expiry.setdefault(r["expiry"], []).append(r)
    if not by_expiry:
        return {
            "kind": family["kind"],
            "legs": [],
            "dte_target": None,
            "status": "no_chain",
            "note": "",
        }
    expiry = min(by_expiry, key=lambda e: abs(int(by_expiry[e][0]["dte"]) - dte_pref))
    chain = by_expiry[expiry]
    dte_target = int(chain[0]["dte"])
    delta_key = "put_delta" if family["legs"][0]["right"] == "PUT" else "call_delta"

    legs: list[dict] = []
    for leg in family["legs"]:
        target = leg["target_delta"]
        cands = [r for r in chain if r.get(delta_key) is not None]
        if not cands:
            return {
                "kind": family["kind"],
                "legs": [],
                "dte_target": dte_target,
                "status": "no_chain",
                "note": "",
            }
        best = min(cands, key=lambda r: abs(float(r[delta_key]) - target))
        legs.append(
            {
                "action": leg["action"],
                "right": leg["right"],
                "strike": best["strike"],
                "target_delta": target,
                "actual_delta": best[delta_key],
                "expiry": expiry,
                "dte": dte_target,
            }
        )
    # Defined-risk guard (standing rule: no naked shorts). The long (first) and short
    # (second) legs must form a DEBIT spread in the intended direction — the long wing
    # nearer ATM than the short wing. PUT debit: long strike > short strike. CALL debit:
    # long strike < short strike. A degenerate/non-monotonic chain that would invert this
    # (turning it into a short-premium credit spread) yields no_chain instead.
    long_leg, short_leg = legs[0], legs[1]
    ok = (
        long_leg["strike"] > short_leg["strike"]
        if long_leg["right"] == "PUT"
        else long_leg["strike"] < short_leg["strike"]
    )
    if not ok:
        return {
            "kind": family["kind"],
            "legs": [],
            "dte_target": dte_target,
            "status": "no_chain",
            "note": "",
        }
    note = "defined risk; long-premium debit spread"
    if earnings_note:
        note += f"; {earnings_note}"
    return {
        "kind": family["kind"],
        "legs": legs,
        "dte_target": dte_target,
        "status": "ready",
        "note": note,
    }


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
    # Regime left the verdict bucket key (migration 076): robustness is enforced in
    # the markout's per-quarter catastrophic-degradation gate, not by a live
    # regime-match. `regime` is now context only (shown in the basis below).
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
        f"(survived the per-quarter catastrophic gate); borrow normal today "
        f"(point-in-time borrow history unavailable — borrow-clean subset is "
        f"approximate, so this is a tilt, not a forecast); current regime {regime}"
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
    # `tail` may arrive as the raw sign label ("put_skew"/"call_skew") or the short
    # form ("put"/"call"); render a clean phrase either way so no enum underscore
    # leaks into the prose.
    sign_phrase = {
        "put": "put-skew",
        "put_skew": "put-skew",
        "call": "call-skew",
        "call_skew": "call-skew",
        "flat": "flat skew",
        "unknown": "skew",
    }.get(tail, "skew")
    # Spec §11: summary_line is the relative-value/context body ONLY. Direction is
    # confined to `directional_lean` (the single field allowed to express it).
    summary = (
        f"{deviation_class} {sign_phrase} ({asset_class}); drive: {drive_class}; "
        f"{rho_txt}. {rv_body}"
    )
    # Scannable breakdown of the same read — one bullet per component, each with a
    # plain-English explanation. Same §11 rule: no directional language here.
    wing_word = {
        "put": "Puts",
        "put_skew": "Puts",
        "call": "Calls",
        "call_skew": "Calls",
    }.get(tail)
    if wing_word:
        rr_sign = "positive" if wing_word == "Puts" else "negative"
        shape_body = f"{wing_word} are the richer wing ({rr_sign} 25Δ RR); "
    else:
        shape_body = "Neither wing clearly richer; "
    shape_body += {
        "RICH": "stretched vs its 180-day baseline.",
        "CHEAP": "underpriced vs its 180-day baseline.",
        "NORMAL": "near its 180-day baseline.",
    }.get(deviation_class, "near its 180-day baseline.")
    drive_body = {
        "PANIC": "Vol bid into weakness — defensive demand; treat as downside fear.",
        "CHASE": "Vol bid into strength — upside convexity chase, not defensive hedging.",
        "STRUCTURAL": "Persistent, non-event bid — the current structural skew regime.",
    }.get(drive_class, "Skew driver not clearly classified.")
    rho_label = "confirmed" if rho_confirms else "not confirmed"
    rho_body = (
        "ρ confirms — vol moves with spot as the skew implies."
        if rho_confirms
        else "ρ doesn't confirm — positioning/skew dislocation, not a clean spot-vol signal."
    )
    rv_label = {"RICH": "fade/finance", "CHEAP": "own optionality"}.get(
        deviation_class, "no edge"
    )
    rv_bullet_body = {
        "RICH": "Rich vs baseline: fade or finance the expensive wing via "
        "defined-risk structures.",
        "CHEAP": "Cheap vs baseline: own the underpriced wing, especially if "
        "catalyst/tape agrees.",
        "NORMAL": "Near baseline: no skew edge today — needs another pillar to "
        "carry the trade.",
    }.get(deviation_class, "No relative-value skew edge today.")
    summary_bullets = [
        {"label": f"Shape — {deviation_class} {sign_phrase}", "body": shape_body},
        {"label": f"Drive — {drive_class}", "body": drive_body},
        {"label": f"Spot–vol link — {rho_label}", "body": rho_body},
        {"label": f"Relative value — {rv_label}", "body": rv_bullet_body},
    ]
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
        "summary_bullets": summary_bullets,
    }
