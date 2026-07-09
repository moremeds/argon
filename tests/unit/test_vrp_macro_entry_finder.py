import pytest

from uw_scan.reports.vrp_macro_entry import resolve_entry_contracts
from uw_scan.reports.vrp_structure import bs_delta


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


def test_skew_aware_bracket_sits_below_flat_vol_and_straddles_delta():
    # SPX-shaped: spot 7400, ~43 cal DTE, r 4%, 5-pt grid. Modeled put skew (NOT
    # observed market data): IV rises ~1 vol per 100 pts below spot off a 13-vol
    # ATM — a realistic monotone smile used purely as a bracketing-function input.
    spot, T, r = 7400.0, 43 / 365, 0.04
    listed = [6600 + 5 * i for i in range(200)]  # 6600..7595
    atm_iv = 0.13
    strike_ivs = {k: atm_iv + max(0.0, spot - k) / 100.0 * 0.01 for k in listed}

    flat = resolve_entry_contracts(
        spot=spot, sigma=atm_iv, T=T, r=r, listed_strikes=listed
    )
    skew = resolve_entry_contracts(
        spot=spot, sigma=atm_iv, T=T, r=r, listed_strikes=listed, strike_ivs=strike_ivs
    )

    # Put skew lifts OTM IV → the real Δ0.25 / Δ0.125 strikes sit BELOW flat-vol's
    # (the bug: flat-vol legs came out too shallow, Δ~0.28 / ~0.17).
    assert skew.short_above < flat.short_above
    assert skew.wing_above < flat.wing_above

    # And the picked bracket actually straddles the target delta under each
    # strike's OWN IV — which flat-vol never guarantees.
    def dmag(k):
        return -bs_delta(spot, k, T, r, strike_ivs[k], is_call=False)

    assert dmag(skew.short_below) < 0.25 < dmag(skew.short_above)
    assert dmag(skew.wing_below) < 0.125 < dmag(skew.wing_above)
    assert skew.wing_above < skew.short_below  # wing strictly deeper OTM than short


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
