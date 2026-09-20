"""Skew-aware strike selection for the SPX macro short-vol signal.

Fixture: a FROZEN real snapshot of the prod SPX `vrp_macro_entry_grid` for
for_date 2026-09-18 (chosen_expiry 2026-10-30) alongside that session's signal
inputs (spot 7637.76, ATM iv 0.1544, r 0.04). Nothing here touches the network
or the DB.
"""

from datetime import date

from uw_scan.reports.vrp_macro_signal import WINNER, current_macro_signal
from uw_scan.reports.vrp_structure import (
    build_bull_put_spread,
    legs_from_strike_ivs,
    select_bull_put_spread,
)

AS_OF = date(2026, 9, 18)
EXPIRY = date(2026, 10, 30)
SPOT = 7637.76
ATM_IV = 0.1544
R = 0.04
T = (EXPIRY - AS_OF).days / 365.0

# strike -> put IV, exactly as captured (jsonb keys are strings in prod).
STRIKE_IVS = {
    "6900": 0.22197, "6925": 0.21946, "6950": 0.21567, "6975": 0.21355,
    "7000": 0.20929, "7025": 0.20738, "7050": 0.20317, "7075": 0.20159,
    "7100": 0.19813, "7125": 0.19503, "7150": 0.19094, "7175": 0.18748,
    "7200": 0.18432, "7225": 0.18198, "7250": 0.17836, "7275": 0.17562,
    "7300": 0.17215, "7325": 0.16946, "7350": 0.16636, "7375": 0.16339,
    "7400": 0.15989, "7425": 0.15788, "7450": 0.15400, "7475": 0.15218,
    "7500": 0.14918, "7525": 0.14607, "7550": 0.14372, "7575": 0.14135,
    "7600": 0.13847, "7625": 0.13597, "7650": 0.13362, "7675": 0.13086,
    "7700": 0.12830,
}  # fmt: skip

LEGS = legs_from_strike_ivs(SPOT, T, R, STRIKE_IVS)
DELTA_BY_STRIKE = {strike: dmag for strike, _iv, dmag in LEGS}


def _delta_at(strike: float) -> float:
    """|put delta| at a listed strike under the fixture's own skew."""
    return DELTA_BY_STRIKE[strike]


def test_selected_strikes_carry_the_deltas_they_claim():
    sel = select_bull_put_spread(LEGS, SPOT, T, R, short_delta=0.25, wing_delta=0.125)
    assert sel is not None
    assert sel.spread.short_put % 25 == 0  # a real listed strike
    assert sel.spread.long_put % 25 == 0
    assert sel.spread.long_put < sel.spread.short_put
    assert abs(sel.short_delta - 0.25) < 0.02
    assert abs(sel.wing_delta - 0.125) < 0.02
    # each leg priced off its OWN iv
    assert sel.short_iv == STRIKE_IVS[str(int(sel.spread.short_put))]
    assert sel.wing_iv == STRIKE_IVS[str(int(sel.spread.long_put))]


def test_flat_vol_wing_is_far_too_shallow_under_real_skew():
    """The regression this fix exists for: inverting ONE flat ATM vol puts the
    "0.125 delta" wing at a strike that actually carries >0.15 delta."""
    flat = build_bull_put_spread(
        SPOT, ATM_IV, WINNER.hold_days / 252.0, R, short_delta=0.25, wing_delta=0.125
    )
    nearest_listed = min(
        DELTA_BY_STRIKE, key=lambda k: abs(k - flat.long_put)
    )  # 7225, the listed strike the flat-vol wing lands on
    assert abs(nearest_listed - flat.long_put) < 25
    assert _delta_at(nearest_listed) > 0.15
    sel = select_bull_put_spread(LEGS, SPOT, T, R, short_delta=0.25, wing_delta=0.125)
    assert sel is not None
    assert sel.spread.long_put < nearest_listed  # the honest wing sits lower


def test_no_strike_below_the_short_returns_none():
    only_one_below_nothing = [(7650.0, 0.13362, 0.25)]
    assert (
        select_bull_put_spread(
            only_one_below_nothing, SPOT, T, R, short_delta=0.25, wing_delta=0.125
        )
        is None
    )
    # two legs, but the nearest-0.25-delta leg is the LOWEST strike → no wing
    no_wing = [(7000.0, 0.20929, 0.25), (7600.0, 0.13847, 0.48)]
    assert (
        select_bull_put_spread(no_wing, SPOT, T, R, short_delta=0.25, wing_delta=0.125)
        is None
    )


class _StubSettings:
    vrp_risk_free_rate = R


class _StubRepo:
    """Only the two reads `current_macro_signal` makes on the repo."""

    def __init__(self, grid):
        self._grid = grid

    def fetch_vrp_macro_entry_grid(self, name, for_date, **_kw):
        return self._grid


_ROWS = [{"market_date": AS_OF, "iv": ATM_IV, "rv": 0.10, "vrp": 0.05, "vrp_z_20": 1.2}]


class _StubLoaded:
    adj = [(AS_OF, SPOT)]
    pidx = {AS_OF: 0}
    rows = _ROWS
    events: list = []


def _patch_load(monkeypatch):
    monkeypatch.setattr(
        "uw_scan.reports.vrp_macro_signal.load_index_vol",
        lambda repo, name, **kw: _StubLoaded(),
    )


def test_current_macro_signal_uses_the_grid_when_present(monkeypatch):
    _patch_load(monkeypatch)
    grid = {
        "for_date": AS_OF,
        "chosen_expiry": EXPIRY,
        "strikes": [float(k) for k in STRIKE_IVS],
        "strike_ivs": STRIKE_IVS,
    }
    sig = current_macro_signal(_StubRepo(grid), _StubSettings(), "SPX")
    assert sig.action == "TRADE"
    assert sig.strike_basis == "listed_skew"
    assert sig.strike_grid_date == AS_OF
    assert sig.expiry == EXPIRY
    assert sig.short_put % 25 == 0 and sig.long_put % 25 == 0
    assert abs(sig.short_put_delta - 0.25) < 0.02
    assert abs(sig.long_put_delta - 0.125) < 0.02


def test_current_macro_signal_falls_back_and_says_so(monkeypatch):
    _patch_load(monkeypatch)
    sig = current_macro_signal(_StubRepo(None), _StubSettings(), "QQQ")
    assert sig.action == "TRADE"
    assert sig.strike_basis == "flat_vol_model"
    assert sig.short_put_delta is None
    assert sig.long_put_delta is None
    assert sig.strike_grid_date is None
    assert sig.expiry is None
    assert sig.short_put % 25 != 0  # a modeled, continuous strike
