"""Currency translation for foreign filers.

The failure mode this guards is a *quiet* one. TSM's TWD/USD gap drove enterprise
value negative and tripped the `build_anchors` guard; ASML's ~16% EUR gap did
not — it produced a full band at `confidence: high`, indistinguishable on screen
from a correct one. Every test here is aimed at the quiet case.

Rates are real observed USDEUR levels; the mixed-currency fixture is NBIS's real
2026-03-31 shape.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.fundamentals.fx import (
    FIELD_SOURCE,
    METHOD_STATEMENTS,
    USD_LIKE,
    average_rate,
    convert,
    fx_symbol,
    rate_on_or_before,
)

# USDEUR = EUR per one USD. Real closes: 0.7467 (2005-03-09), 0.8586 (2026-05-18).
SERIES = [(date(2005, 3, 9), 0.7466587), (date(2026, 5, 18), 0.8585755)]
EUR = dict.fromkeys(("income", "balance", "cash_flow"), "EUR")
END, START = date(2026, 5, 18), date(2025, 5, 18)


def _conv(inputs, currencies=EUR, series=None):
    return convert(
        inputs,
        currencies=currencies,
        series_by_ccy={"EUR": SERIES} if series is None else series,
        period_end=END,
        ttm_start=START,
    )


def test_the_conversion_direction_is_divide_not_multiply():
    """EUR 100 at 0.8586 EUR/USD is ~USD 116, not ~USD 86. Inverting this is a
    ~35% error that still prints an entirely plausible share price."""
    got = _conv({"total_revenue": 100.0})
    assert 116.0 < got["total_revenue"] < 117.0


def test_a_share_count_is_never_converted():
    """Dividing a share count by an FX rate is the classic form of this bug — it
    produces a market cap wrong by the rate squared."""
    assert _conv({"total_revenue": 100.0, "shares": 5.0})["shares"] == 5.0


def test_flows_take_the_window_average_and_stocks_the_close():
    """A TTM numerator translated at today's close silently reprices four
    quarters of trading at one day's rate."""
    wide = {
        "EUR": [
            (date(2026, 1, 1), 0.80),
            (date(2026, 3, 1), 0.90),
            (date(2026, 5, 18), 1.00),
        ]
    }
    got = convert(
        {"total_revenue": 90.0, "net_debt": 90.0},
        currencies=EUR,
        series_by_ccy=wide,
        period_end=END,
        ttm_start=date(2025, 12, 31),
    )
    assert got["total_revenue"] == pytest.approx(90.0 / 0.90)
    assert got["net_debt"] == pytest.approx(90.0 / 1.00)


def test_currency_is_resolved_per_statement_not_per_filer():
    """NBIS's real 2026-03-31 shape: USD income and balance beside a RUB
    cash-flow statement, in the same quarter. A per-filer model picks one and
    applies it to figures never denominated in it."""
    mixed = {"income": "USD", "balance": "USD", "cash_flow": "RUB"}
    got = _conv(
        {"total_revenue": 100.0, "net_debt": 50.0, "fcf": None},
        currencies=mixed,
        series={},
    )
    assert got["total_revenue"] == 100.0
    assert got["net_debt"] == 50.0


def test_a_field_from_an_unconvertible_statement_refuses_the_quarter():
    mixed = {"income": "USD", "balance": "USD", "cash_flow": "RUB"}
    assert _conv({"total_revenue": 100.0, "fcf": 10.0}, mixed, {}) is None


def test_a_missing_series_refuses_rather_than_passing_the_figure_through():
    """The whole point: an unconverted figure is the silent wrong answer."""
    assert _conv({"total_revenue": 5.0}, EUR, {}) is None


def test_usd_passes_through_untouched():
    usd = dict.fromkeys(("income", "balance", "cash_flow"), "USD")
    assert _conv({"total_revenue": 5.0}, usd, {}) == {"total_revenue": 5.0}


def test_an_unstated_currency_is_treated_as_usd():
    """`None` appears on rows predating UW adding the field; every ticker
    carrying it in the measured panel is a US filer."""
    assert None in USD_LIKE
    unknown = dict.fromkeys(("income", "balance", "cash_flow"), None)
    assert _conv({"total_revenue": 5.0}, unknown, {}) == {"total_revenue": 5.0}


def test_a_method_is_only_blocked_by_a_statement_it_reads():
    """`sales_to_ev` reads income + balance, so NBIS's RUB cash-flow statement
    must not cost it a band."""
    assert METHOD_STATEMENTS["sales_to_ev"] == ("income", "balance")
    assert METHOD_STATEMENTS["ebitda_to_ev"] == ("income", "balance")
    assert METHOD_STATEMENTS["fcf_yield"] == ("cash_flow",)


def test_every_converted_field_declares_its_statement_and_kind():
    assert set(FIELD_SOURCE) == {"total_revenue", "ebitda", "fcf", "net_debt"}
    assert FIELD_SOURCE["net_debt"] == ("balance", "stock")
    assert FIELD_SOURCE["fcf"] == ("cash_flow", "flow")


def test_rate_lookup_never_reads_the_future():
    assert rate_on_or_before(SERIES, date(2026, 6, 1)) == 0.8585755
    assert rate_on_or_before(SERIES, date(2005, 3, 8)) is None


def test_average_rate_falls_back_to_the_close_on_an_empty_window():
    """Happens only for a period predating the series; stated rather than silent
    because the caller cannot tell the two apart from the number."""
    assert average_rate(SERIES, date(1990, 1, 1), date(1990, 6, 1)) is None
    assert average_rate(SERIES, date(2026, 5, 17), date(2026, 5, 18)) == 0.8585755


def test_symbol_convention_is_local_per_usd():
    assert fx_symbol("twd") == "USDTWD"
    assert fx_symbol("EUR") == "USDEUR"
