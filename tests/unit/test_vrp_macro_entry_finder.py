import pytest
from uw_scan.reports.vrp_macro_entry import resolve_entry_contracts


def test_brackets_each_target_above_and_below():
    # SPX-like: spot 6000, IV 0.16, ~43 cal DTE, 5-pt grid
    listed = [5500 + 5 * i for i in range(120)]  # 5500..6095
    ec = resolve_entry_contracts(
        spot=6000,
        sigma=0.16,
        T=43 / 365,
        r=0.04,
        listed_strikes=listed,
        short_delta=0.25,
        wing_delta=0.125,
    )
    assert ec.short_below < ec.short_above
    assert ec.wing_below < ec.wing_above
    assert ec.wing_above < ec.short_below  # wing strictly below short (deeper OTM put)
    assert all(
        k in listed
        for k in (ec.short_above, ec.short_below, ec.wing_above, ec.wing_below)
    )


def test_raises_when_no_bracket():
    with pytest.raises(ValueError):
        resolve_entry_contracts(
            spot=6000,
            sigma=0.16,
            T=43 / 365,
            r=0.04,
            listed_strikes=[6000],
            short_delta=0.25,
            wing_delta=0.125,
        )
