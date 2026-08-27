"""`underwriting_features` — DIO, SBC/revenue, diluted-share YoY (spec §5-v).

Descriptive only: NEVER asserts these values join `FEATURES` or the composite.
See `src/uw_scan/fundamentals/features.py` for the raw-key probe this fixture
data was chosen to exercise.

AAPL's real last FIVE fiscal quarters, frozen 2026-08-28 from
`option_wizard_local`'s `uw_scan.fundamental_statement_obs` (the local dev warm
store — every figure exactly as UW reports it, verified by direct query):

    SELECT DISTINCT ON (period_end) period_end, raw_jsonb->>'inventory'
      FROM uw_scan.fundamental_statement_obs
     WHERE statement='balance' AND period_type='quarterly' AND ticker='AAPL'
     ORDER BY period_end, obs_id DESC;
    -- (and the same shape for income's cost_of_revenue/total_revenue, and
    --  cash_flow's stock_based_compensation)

FIVE, not fewer — `share_count_yoy` needs a period four quarters before the
last one to have anything to divide against, mirroring why
`test_feature_details.py`'s NVDA fixture is TEN rather than five for
`rev_growth`'s TTM-vs-4-quarters-earlier comparison.

Raw-key probe result (see `features.py`): `diluted_average_shares` (or any
diluted/weighted-average share-count field, under any name) is NOT present in
ANY ingested UW income statement. `share_count_yoy` therefore evaluates to
None for every real row below — that IS the correct, honest output, not a bug
in this fixture. `_prior_period` (the index-based lookback the feature would
use if the key ever appears) is tested directly, in isolation, on real period
labels, since the feature itself can never produce a discriminating fixture
while the key stays absent.
"""

from __future__ import annotations

from uw_scan.fundamentals.features import (
    FEATURES,
    _prior_period,
    underwriting_features,
)

# period_end -> (inventory, cost_of_revenue, total_revenue, stock_based_compensation)
_AAPL_RAW = {
    "2025-06-30": (5925000000, 50318000000, 94036000000, 3168000000),
    "2025-09-30": (5718000000, 54125000000, 102466000000, 3183000000),
    "2025-12-31": (5875000000, 74525000000, 143756000000, 3594000000),
    "2026-03-31": (6747000000, 56403000000, 111184000000, 3528000000),
    "2026-06-30": (11092000000, 54647000000, 109417000000, 3401000000),
}

_PERIODS = sorted(_AAPL_RAW)


def _panel(raw: dict[str, tuple[int, int, int, int]]) -> dict[str, dict]:
    inc, bs, cf = {}, {}, {}
    for period, (inv, cogs, rev, sbc) in raw.items():
        bs[period] = {"inventory": str(inv)}
        inc[period] = {"cost_of_revenue": str(cogs), "total_revenue": str(rev)}
        cf[period] = {"stock_based_compensation": str(sbc)}
    return {
        "income-statements": inc,
        "balance-sheets": bs,
        "cash-flows": cf,
    }


AAPL = {"AAPL": _panel(_AAPL_RAW)}


def test_never_joins_the_scored_features_list():
    """The single most important constraint in the brief, stated as a test."""
    assert "dio" not in FEATURES
    assert "sbc_to_revenue" not in FEATURES
    assert "share_count_yoy" not in FEATURES


def test_dio_matches_the_formula_exactly_every_period():
    out = underwriting_features(AAPL)["AAPL"]
    for period, (inv, cogs, _rev, _sbc) in _AAPL_RAW.items():
        assert out[period]["dio"] == inv / cogs * 91.25


def test_sbc_to_revenue_matches_the_formula_exactly_every_period():
    out = underwriting_features(AAPL)["AAPL"]
    for period, (_inv, _cogs, rev, sbc) in _AAPL_RAW.items():
        assert out[period]["sbc_to_revenue"] == sbc / rev


def test_share_count_yoy_is_none_everywhere_because_the_key_is_absent():
    """The honest-absence contract: no proxy, no silent substitution, no zero."""
    out = underwriting_features(AAPL)["AAPL"]
    assert all(out[p]["share_count_yoy"] is None for p in _PERIODS)


def test_dio_none_propagation_when_cogs_is_absent():
    raw = dict(_AAPL_RAW)
    panel = _panel(raw)
    del panel["income-statements"]["2026-06-30"]["cost_of_revenue"]
    out = underwriting_features({"AAPL": panel})["AAPL"]
    assert out["2026-06-30"]["dio"] is None
    # Untouched periods still compute — absence does not poison the series.
    assert out["2025-06-30"]["dio"] == 5925000000 / 50318000000 * 91.25


def test_dio_none_propagation_when_inventory_is_absent():
    panel = _panel(_AAPL_RAW)
    del panel["balance-sheets"]["2026-06-30"]["inventory"]
    out = underwriting_features({"AAPL": panel})["AAPL"]
    assert out["2026-06-30"]["dio"] is None


def test_sbc_none_propagation_when_sbc_is_absent():
    panel = _panel(_AAPL_RAW)
    del panel["cash-flows"]["2026-06-30"]["stock_based_compensation"]
    out = underwriting_features({"AAPL": panel})["AAPL"]
    assert out["2026-06-30"]["sbc_to_revenue"] is None
    assert out["2025-06-30"]["sbc_to_revenue"] == 3168000000 / 94036000000


def test_sbc_none_propagation_when_revenue_is_absent():
    panel = _panel(_AAPL_RAW)
    del panel["income-statements"]["2026-06-30"]["total_revenue"]
    out = underwriting_features({"AAPL": panel})["AAPL"]
    assert out["2026-06-30"]["sbc_to_revenue"] is None


def test_zero_cogs_returns_none_not_a_division_blowup():
    """Constructed edge case (real AAPL fixture, COGS doctored to 0) — a
    no-COGS-reporting quarter must not raise ZeroDivisionError. AAPL never
    actually reports zero COGS; this exercises the guard the way
    `test_zero_cost_of_revenue_is_not_flagged` does in `test_statements.py`."""
    panel = _panel(_AAPL_RAW)
    panel["income-statements"]["2026-06-30"]["cost_of_revenue"] = "0"
    out = underwriting_features({"AAPL": panel})["AAPL"]
    assert out["2026-06-30"]["dio"] is None


def test_zero_revenue_returns_none_not_a_division_blowup():
    panel = _panel(_AAPL_RAW)
    panel["income-statements"]["2026-06-30"]["total_revenue"] = "0"
    out = underwriting_features({"AAPL": panel})["AAPL"]
    assert out["2026-06-30"]["sbc_to_revenue"] is None


def test_share_count_yoy_none_when_fewer_than_five_quarters_exist():
    """Structural guard, checked in combination with `_prior_period` below:
    dropping the earliest quarter leaves only four, one short of the fifth
    `share_count_yoy` needs for its 4-quarters-back endpoint."""
    raw = {p: v for p, v in _AAPL_RAW.items() if p != "2025-06-30"}
    out = underwriting_features({"AAPL": _panel(raw)})["AAPL"]
    assert out["2026-06-30"]["share_count_yoy"] is None


# ---------------------------------------------------------------------------
# `_prior_period` in isolation — real AAPL period labels, no financial values.
#
# This is the discriminating test for the YoY prior-period lookup: because
# `diluted_average_shares` is absent from every real row (see module docstring
# probe), `underwriting_features`'s own `share_count_yoy` output is None
# regardless of whether the lookback arithmetic is right or wrong — a test
# that only checks the wired-up feature output could never fail on a broken
# lookback. Testing `_prior_period` directly closes that gap.
# ---------------------------------------------------------------------------


def test_prior_period_is_four_sorted_slots_back():
    assert _prior_period(_PERIODS, 4) == "2025-06-30"
    assert _prior_period(_PERIODS, 3, lookback=3) == "2025-06-30"


def test_prior_period_is_none_below_the_lookback():
    assert _prior_period(_PERIODS, 3) is None
    assert _prior_period(_PERIODS, 0) is None


def test_prior_period_is_index_based_not_calendar_arithmetic():
    """The discriminating case: a naive '365 days back' would land on a date
    that plain does not exist in a real quarterly period list (AAPL's own
    2026-06-30 minus 365 days is 2025-07-01, not 2025-06-30), and would need
    to fall back to nearest-match or fail outright. Index-based lookback has
    no such failure mode — it names the ACTUAL sorted entry, whatever its
    calendar distance."""
    assert "2025-07-01" not in _PERIODS
    assert _prior_period(_PERIODS, 4) == "2025-06-30"
