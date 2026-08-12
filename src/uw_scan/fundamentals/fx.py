"""Currency translation for foreign filers' statements.

Pure compute plus one parquet read. Run
`uv run python -m uw_scan.fundamentals.fx` for the self-check.

WHY THIS EXISTS
---------------
Enterprise value adds a market cap (a USD quote x a share count) to balance-sheet
figures taken from a filing. When the filer reports in another currency those two
terms are in different units, and the result is not merely imprecise — it is
meaningless. Measured 2026-08-12 across the 257-name panel, five filers report
non-USD (`reported_currency` on every UW statement row): TSM in TWD, ASML/CCEP/NOK
in EUR, NBIS in RUB.

**The dangerous case is the small error, not the large one.** TSM's TWD/USD gap
drove enterprise value negative and tripped the `build_anchors` guard. ASML's
~16% EUR gap did not: it produced a full band at `confidence: high`, which is
indistinguishable on screen from a correct one. A guard that only catches the
catastrophic case leaves the quiet one in production.

Nor is it a constant that cancels in a percentile. USDEUR ran 0.747 to 0.859 over
2005-2026, so an unconverted history is distorted by a factor that MOVES — it
reshapes the distribution the band's percentiles are drawn from, rather than
sliding it.

THE TWO-RATE RULE
-----------------
Flows (revenue, EBITDA, cash flow) accrue across a period and translate at the
AVERAGE rate over that period. Stocks (debt, cash) exist at an instant and
translate at the CLOSE rate on that date. Using one rate for both is the standard
shortcut and it is wrong in exactly the direction that matters here: a TTM
numerator translated at today's close silently reprices four quarters of trading
at one day's rate.

SYMBOL CONVENTION
-----------------
`USD<CCY>` in the lake holds **<CCY> per one USD** (USDEUR closed 0.8586 on
2026-05-18, i.e. EUR per USD). So `usd = local / rate`. Getting this inverted is
a ~35% error on EUR that still produces plausible-looking prices, so the
direction is asserted in the self-check against a real observed level rather than
left to the reader.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)

BAR_FILENAME = "1d.parquet"

#: Treated as already-USD. `None` appears on older rows that predate UW adding
#: the field, and every ticker carrying it in the measured panel is a US filer.
USD_LIKE = frozenset({"USD", None, ""})


def fx_symbol(currency: str) -> str:
    """Lake symbol for a reporting currency. `USD<CCY>` = <CCY> per one USD."""
    return f"USD{currency.upper()}"


def load_fx(root: Path, currency: str) -> list[tuple[date, float]]:
    """Daily rates for one currency, ascending. Empty when the series is absent.

    Empty is a real answer and callers must refuse the ticker on it rather than
    fall back to an unconverted figure — an unconverted band is the silent wrong
    answer this module exists to prevent.
    """
    path = root / f"symbol={fx_symbol(currency)}" / BAR_FILENAME
    if not path.exists():
        return []
    import pyarrow.parquet as pq

    try:
        tab = pq.read_table(str(path), columns=["trade_date", "close"])
    except (OSError, ValueError) as exc:
        log.warning("fx: unreadable series for %s: %s", currency, repr(exc))
        return []
    rows = [
        (d, float(c))
        for d, c in zip(
            tab.column("trade_date").to_pylist(), tab.column("close").to_pylist()
        )
        if d is not None and c is not None and float(c) > 0
    ]
    return sorted(rows)


def rate_on_or_before(series: list[tuple[date, float]], when: date) -> float | None:
    """Close rate at or before `when`. Never after — that is look-ahead."""
    lo, hi, found = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= when:
            found = series[mid][1]
            lo = mid + 1
        else:
            hi = mid - 1
    return found


def average_rate(
    series: list[tuple[date, float]], start: date, end: date
) -> float | None:
    """Mean rate across (start, end] — the flow leg of the two-rate rule.

    Falls back to the close at `end` when the window holds no observations, which
    happens only for a period predating the series. Stated rather than silent:
    the caller cannot distinguish the two from the number alone.
    """
    window = [r for d, r in series if start < d <= end]
    if window:
        return sum(window) / len(window)
    return rate_on_or_before(series, end)


#: Which statement each figure comes from, and whether it is a flow or a stock.
#:
#: CURRENCY IS PER STATEMENT, NOT PER FILER. Measured on NBIS 2026-03-31: income
#: and balance report USD while the cash-flow statement reports RUB, in the same
#: quarter. A per-ticker currency model reads one of the three and applies it to
#: all — which for NBIS would have divided USD revenue by a ruble rate.
FIELD_SOURCE: dict[str, tuple[str, str]] = {
    "total_revenue": ("income", "flow"),
    "ebitda": ("income", "flow"),
    "fcf": ("cash_flow", "flow"),
    "net_debt": ("balance", "stock"),
}

#: Statements each method actually reads. A method is only blocked by a currency
#: it depends on: NBIS's RUB cash-flow statement does not stop `sales_to_ev`,
#: which needs income + balance and finds both in USD.
METHOD_STATEMENTS: dict[str, tuple[str, ...]] = {
    "sales_to_ev": ("income", "balance"),
    "ebitda_to_ev": ("income", "balance"),
    "fcf_yield": ("cash_flow",),
}


def convert(
    inputs: dict[str, float | None],
    *,
    currencies: dict[str, str | None],
    series_by_ccy: dict[str, list[tuple[date, float]]],
    period_end: date,
    ttm_start: date,
) -> dict[str, float | None] | None:
    """One quarter's figures translated to USD, each at ITS OWN statement's rate.

    Returns None when a figure needs a currency with no series — refusing is the
    point, since the alternative is an unconverted number that looks correct.

    `shares` is NOT converted: a share count has no currency, and dividing it by
    an FX rate is the classic form of this bug, producing a market cap wrong by
    the rate squared.
    """
    out = dict(inputs)
    for field, (statement, kind) in FIELD_SOURCE.items():
        value = inputs.get(field)
        if value is None:
            continue
        ccy = currencies.get(statement)
        if ccy in USD_LIKE:
            continue
        series = series_by_ccy.get(str(ccy)) or []
        if not series:
            return None
        rate = (
            average_rate(series, ttm_start, period_end)
            if kind == "flow"
            else rate_on_or_before(series, period_end)
        )
        if not rate:
            return None
        out[field] = value / rate
    return out


def _self_check() -> None:
    # Real observed USDEUR levels: 0.7467 (2005-03-09) and 0.8586 (2026-05-18).
    series = [(date(2005, 3, 9), 0.7466587), (date(2026, 5, 18), 0.8585755)]
    eur = dict.fromkeys(("income", "balance", "cash_flow"), "EUR")
    end, start = date(2026, 5, 18), date(2025, 5, 18)

    assert fx_symbol("eur") == "USDEUR"
    assert rate_on_or_before(series, date(2026, 6, 1)) == 0.8585755
    assert rate_on_or_before(series, date(2005, 3, 8)) is None

    # DIRECTION. EUR 100 at 0.8586 EUR/USD is ~USD 116, not ~USD 86. Inverting
    # this is a ~35% error that still prints a plausible price.
    got = convert(
        {"total_revenue": 100.0, "ebitda": None, "net_debt": 100.0, "shares": 5.0},
        currencies=eur,
        series_by_ccy={"EUR": series},
        period_end=end,
        ttm_start=start,
    )
    assert 116.0 < got["total_revenue"] < 117.0, got["total_revenue"]
    assert got["shares"] == 5.0, "a share count has no currency"
    assert got["ebitda"] is None, "a missing figure stays missing"

    # The two-rate rule: flows take the window average, stocks the close.
    wide = [
        (date(2026, 1, 1), 0.80),
        (date(2026, 3, 1), 0.90),
        (date(2026, 5, 18), 1.00),
    ]
    two = convert(
        {"total_revenue": 90.0, "net_debt": 90.0, "shares": 1.0},
        currencies=eur,
        series_by_ccy={"EUR": wide},
        period_end=end,
        ttm_start=date(2025, 12, 31),
    )
    assert abs(two["total_revenue"] - 90.0 / 0.90) < 1e-9, two["total_revenue"]
    assert abs(two["net_debt"] - 90.0 / 1.00) < 1e-9, two["net_debt"]

    # NBIS's real shape: a RUB cash-flow statement beside USD income and balance
    # in the SAME quarter. Only fields sourced from the RUB statement may be
    # touched, and a per-ticker currency model would have converted all three.
    mixed = {"income": "USD", "balance": "USD", "cash_flow": "RUB"}
    got = convert(
        {"total_revenue": 100.0, "net_debt": 50.0, "fcf": None},
        currencies=mixed,
        series_by_ccy={},
        period_end=end,
        ttm_start=start,
    )
    assert got["total_revenue"] == 100.0 and got["net_debt"] == 50.0, got
    # ... and once the RUB-sourced field is actually present, it refuses.
    assert (
        convert(
            {"total_revenue": 100.0, "fcf": 10.0},
            currencies=mixed,
            series_by_ccy={},
            period_end=end,
            ttm_start=start,
        )
        is None
    )

    # A method is only blocked by a currency it reads.
    assert METHOD_STATEMENTS["sales_to_ev"] == ("income", "balance")
    assert METHOD_STATEMENTS["fcf_yield"] == ("cash_flow",)
    assert set(FIELD_SOURCE) == {"total_revenue", "ebitda", "fcf", "net_debt"}

    print("fx self-check ok")


if __name__ == "__main__":
    _self_check()
