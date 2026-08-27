"""Valuation arithmetic — identity hashing, yields, percentiles, price inversion,
and the drift/shape descriptors. Pure numeric compute; no policy.

Split out of `valuation.py` under M2.1's module-size budget and re-exported from
it, so no import site changed. Nothing here decides anything: every threshold it
compares against is imported from `valuation_policy`.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from uw_scan.fundamentals.features import _f, _ttm
from uw_scan.fundamentals import valuation_policy as _policy
from uw_scan.fundamentals.valuation_policy import (
    DRIFT_LEAN,
    DRIFT_MONOTONE,
    EV_DENOMINATED,
)

def anchor_inputs_hash(
    *,
    company_type: str,
    engine: str,
    fundamental: float | None,
    net_debt: float | None,
    shares: float | None,
    history_n: int,
) -> str:
    """Identity of ONE band: its inputs, its routing, and the rules that made it.

    Anchors cannot reuse `scoring.inputs_hash`. That function hashes the seven
    scoring FEATURES by name, and a band's inputs are none of them — so every
    anchor row was hashing an all-null feature map and reducing to a function of
    `company_type` and `engine` alone. Measured 2026-08-12: a run that computed
    233 bands wrote 0 rows, because the identity could not see that the numbers
    had changed. That is the silent-and-confident failure the schema comment
    claims this key prevents, sitting inside the key itself.
    METHOD RULES ARE PART OF THE IDENTITY, and that is the second half of the
    bug. The same inputs under a NEW rule are a different result — the
    missing-end guard turns JPM from a three-level band into a refusal without
    touching a single input — and `ON CONFLICT DO NOTHING` would drop the
    correction and keep the wrong row. Hashing the thresholds and the rules
    revision means a rule change appends the corrected row instead.
    """
    payload = {
        "company_type": company_type,
        "engine": engine,
        "inputs": {
            k: (None if v is None else f"{float(v):.10g}")
            for k, v in (
                ("fundamental", fundamental),
                ("net_debt", net_debt),
                ("shares", shares),
                ("history_n", history_n),
            )
        },
        # Read through the module, not through names bound at import. These
        # constants ARE the identity: a test that proves "changing a rule changes
        # the hash" has to be able to change one, and `from X import CONST` binds
        # the value once and makes that unprovable.
        "rules": {
            "rev": _policy.ANCHOR_RULES_REV,
            "levels": _policy.LEVELS,
            "window": _policy.WINDOW_QUARTERS,
            "min_history": _policy.MIN_HISTORY,
            "thin_history": _policy.THIN_HISTORY,
            "stale_days": _policy.STALE_DAYS,
            "max_band_width": _policy.MAX_BAND_WIDTH,
        },
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def quarter_inputs(
    statements: dict[str, dict[str, Any]], periods: list[str], i: int
) -> dict[str, float | None]:
    """The figures one quarter's yield is built from.

    Numerators are TTM (four quarters, all-or-nothing — a three-quarter "TTM"
    understates by ~25% and is indistinguishable from a real decline). Balance
    sheet items are point-in-time stocks, taken at the quarter itself.
    """
    p = periods[i]
    inc, bs, cf = (
        statements.get("income-statements", {}),
        statements.get("balance-sheets", {}),
        statements.get("cash-flows", {}),
    )
    ocf = _ttm(cf, periods, i, "operating_cashflow")
    capex = _ttm(cf, periods, i, "capital_expenditures")
    debt = _f(bs.get(p), "short_long_term_debt_total")
    cash = _f(bs.get(p), "cash_and_cash_equivalents")
    return {
        "total_revenue": _ttm(inc, periods, i, "total_revenue"),
        "ebitda": _ttm(inc, periods, i, "ebitda"),
        # capex is signed inconsistently by the provider; abs() makes FCF the
        # same quantity regardless of which convention arrived.
        "fcf": (ocf - abs(capex)) if None not in (ocf, capex) else None,
        "shares": _f(bs.get(p), "common_stock_shares_outstanding"),
        "net_debt": (debt or 0.0) - (cash or 0.0),
    }


#: The numerator each method divides. Kept beside TYPE_YIELD so adding a method
#: is one entry in each, and a missing pair fails loudly at the lookup.
METHOD_NUMERATOR = {
    "sales_to_ev": "total_revenue",
    "ebitda_to_ev": "ebitda",
    "fcf_yield": "fcf",
}


def yield_at(
    method: str, inputs: dict[str, float | None], price: float | None
) -> float | None:
    """One quarter's valuation yield at a given share price.

    None whenever any leg is missing or the denominator is non-positive. A
    net-cash name can carry EV <= 0, which would flip the yield's sign and rank
    it as infinitely cheap — those quarters are dropped from the history rather
    than allowed to define its top percentile.
    """
    num = inputs.get(METHOD_NUMERATOR[method])
    shares = inputs.get("shares")
    if num is None or not shares or shares <= 0 or price is None or price <= 0:
        return None
    denom = price * shares
    if method in EV_DENOMINATED:
        denom += inputs.get("net_debt") or 0.0
    return (num / denom) if denom > 0 else None


def percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated order statistic. `sorted_vals` must be ascending."""
    if not sorted_vals:
        raise ValueError("empty")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = p * (len(sorted_vals) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_vals[lo]
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)


def rank_percentile(sorted_vals: list[float], value: float) -> float:
    """Fraction of history at or below `value` — where spot sits in its own range."""
    if not sorted_vals:
        raise ValueError("empty")
    return sum(1 for v in sorted_vals if v <= value) / len(sorted_vals)


def price_at_yield(
    *, target_yield: float, fundamental: float, net_debt: float, shares: float
) -> float | None:
    """Invert a yield back to the share price that would produce it.

    None when the target yield is non-positive (the inversion diverges through
    zero and would emit a wildly large or negative "price"), or when the implied
    price is itself non-positive — which is a real answer for a name whose net
    debt already exceeds the enterprise value the target implies, but not a
    tradeable level, so it is withheld rather than drawn.
    """
    if target_yield <= 0 or shares <= 0:
        return None
    price = (fundamental / target_yield - net_debt) / shares
    return price if price > 0 else None


def yield_drift(window: list[float]) -> float:
    """Rank correlation of a yield window against time. -1 walks down, +1 up.

    The width gate cannot tell two very different shapes apart, and it states the
    wrong one. A band spans 17x either because the yield SWINGS — no settled
    valuation, refusing is right and "too unstable" is the true word — or because
    it WALKS one way and stays there, which is a window straddling two regimes
    and the opposite of unstable.

    Measured over the 246-name local panel on 2026-08-18
    (`docs/research/2026-08-18-valuation-band-refusal/WIDTH_ANATOMY.md`), both
    shapes appear among the refused: AVGO -0.90, LRCX -0.85, MSTR -0.83 walked
    down (the multiple expanded), NVDA +0.68 and NFLX +0.66 walked up (the
    fundamental outgrew the price), ACRE -0.07 and APLD -0.25 genuinely swing.

    This does NOT license moving the threshold, and the same probe is why: the
    monotone share is 38% among refused names against 36% among those that pass,
    and a Mann-Whitney on rho gives p=0.16. Shape does not separate wide bands
    from narrow ones as a population. It separates them ONE NAME AT A TIME, which
    is the only claim the refusal line needs to make.

    TIES TAKE THE AVERAGE RANK, and skipping that is not a rounding detail. A
    stable sort hands the earlier index the lower rank inside a tie group, which
    manufactures an upward trend out of nothing: a perfectly alternating series
    scored +0.57 before this, and the sentence it drives would have called that
    window a one-way regime shift.

    The index side has no ties by construction, so with the value side corrected
    this is the Pearson correlation of the two rank vectors.
    """
    n = len(window)
    if n < 2:
        return 0.0
    order = sorted(range(n), key=lambda i: window[i])
    rank = [0.0] * n
    start = 0
    while start < n:
        stop = start
        while stop + 1 < n and window[order[stop + 1]] == window[order[start]]:
            stop += 1
        shared = (start + stop) / 2
        for position in range(start, stop + 1):
            rank[order[position]] = shared
        start = stop + 1
    mean = (n - 1) / 2
    den = sum((i - mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    num = sum((i - mean) * (rank[i] - mean) for i in range(n))
    spread = sum((r - mean) ** 2 for r in rank)
    if spread == 0:
        return 0.0
    return num / (den * spread) ** 0.5


def _shape(window: list[float]) -> str:
    """How the refusal describes the window it is refusing, in measured terms."""
    rho = yield_drift(window)
    if abs(rho) < DRIFT_LEAN:
        return f"swinging both ways with no one-way drift (rho {rho:+.2f})"
    direction = (
        "the multiple expanded through it"
        if rho < 0
        else "the fundamental outgrew the price through it"
    )
    walk = "walking one way" if abs(rho) >= DRIFT_MONOTONE else "leaning one way"
    return (
        f"{walk} rather than swinging (rho {rho:+.2f}) — the window covers two "
        f"valuation regimes, not one, because {direction}"
    )


def _over(value: float, limit: float) -> str:
    """Format a ratio at the coarsest precision that still reads ABOVE `limit`.

    A marginal refusal has to survive its own rounding. AVGO on 2026-08-18 spans
    4.04x against a 4.0x limit, and `:.0f` rendered it "spans 4x — too unstable
    to anchor a price to": a sentence that refutes itself, on the only line the
    reader has to go on. One decimal fixes AVGO and breaks the next name in at
    4.004x, so the precision follows the number rather than being guessed once.
    """
    for places in (1, 2, 3):
        text = f"{value:.{places}f}"
        if float(text) > limit:
            return text
    return f"{value:.3f}"
