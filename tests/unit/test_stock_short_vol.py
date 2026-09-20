"""Per-ticker short-vol decision logic. Real TSLA 2026-06-24: spot 382.35, IV30 0.473.

CHAIN below is a small synthetic put ladder (round strikes, hand-picked deltas/IV)
used only to exercise the chain-based strike-selection path — it is not a captured
market snapshot. Two legs are deliberately given per-strike deltas that land EXACTLY
on the target deltas (0.25 short / 0.125 wing) so selection is unambiguous, and
deliberately different IVs so a test can prove pricing uses each leg's OWN IV
rather than one flat vol (the bug this file's rewrite fixes).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.reports.stock_short_vol import (
    select_chain_bull_put_spread,
    build_short_vol,
    decide_short_vol,
)
from uw_scan.reports.vrp_structure import bs_price

AS_OF = date(2026, 6, 24)
SPOT = 382.35
IV = 0.473
RV = 0.40
CLEAR_EARNINGS = date(2026, 10, 1)  # well beyond AS_OF + 45d (2026-08-08)

EXPIRY = date(2026, 8, 8)  # ~45 calendar days out, matches HOLD_CAL_DAYS
CHAIN_LEGS = [
    {"strike": 365, "delta": -0.32, "iv": 0.46},
    {"strike": 350, "delta": -0.25, "iv": 0.473},  # exact short-delta match
    {"strike": 330, "delta": -0.16, "iv": 0.50},
    {"strike": 310, "delta": -0.125, "iv": 0.55},  # exact wing-delta match
    {"strike": 290, "delta": -0.06, "iv": 0.60},
]
CHAIN = {"captured_on": AS_OF, "expiry": EXPIRY, "spot": SPOT, "legs": CHAIN_LEGS}


def test_trade_when_rich_sellable_and_earnings_clear():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
        chain=CHAIN,
    )
    assert sig.action == "TRADE"
    assert sig.skip_reason is None
    assert sig.spot == Decimal(str(SPOT))  # priced off the chain's own captured spot
    # picks the real listed strikes whose captured deltas match the targets exactly
    assert sig.short_put == Decimal("350")
    assert sig.long_put == Decimal("310")
    assert sig.credit is not None and sig.credit > 0
    assert sig.max_loss is not None and sig.max_loss > 0
    assert sig.weight is not None and sig.weight > 0
    assert sig.short_delta == Decimal("0.25")
    assert sig.wing_delta == Decimal("0.125")


def test_skip_when_vol_not_rich():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.01,
        vrp_z_20=0.3,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert "not rich" in (sig.skip_reason or "")
    assert sig.weight == Decimal("0")
    assert sig.short_put is None


def test_skip_when_sector_not_sellable():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=False,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"


def test_skip_when_earnings_unknown():
    # passes_gate proves an earnings calendar EXISTS, but the next date is unknown →
    # never sell vol blind (matches scanner.gates.earnings_gate: None → block).
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=None,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "next earnings date unknown"


def test_skip_when_earnings_date_is_stale():
    # a stored next-earnings date in the past is stale, not "inside the window" —
    # the next print already happened and the real next one is unknown.
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=date(2026, 5, 1),  # before AS_OF
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "next earnings date stale"


def test_macro_class_trades_without_earnings():
    # ETF/index sellable bucket: no earnings to clear, so unknown earnings must NOT
    # block (mirrors vrp_gate exempting non-single_name classes).
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=None,
        require_earnings=False,
        chain=CHAIN,
    )
    assert sig.action == "TRADE"


def test_skip_when_earnings_in_window():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=date(2026, 7, 5),  # ~11 days out
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "earnings inside hold window"


def test_skip_when_no_iv():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=None,
        rv=RV,
        vrp=None,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no usable IV/spot"


def test_skip_and_no_decimal_nan_when_z_nonfinite():
    # early rolling-window rows carry NaN vrp_z_20 → must NOT reach Decimal("NaN")
    # (Pydantic rejects non-finite). Non-finite numerics normalize to None.
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=float("nan"),
        vrp_z_20=float("nan"),
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "insufficient vol history"
    assert sig.vrp_z is None and sig.vrp is None


def test_skip_uses_gate_skip_reason_when_provided():
    # "no earnings calendar" must not masquerade as "sector vol not sellable".
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=False,
        gate_skip_reason="no earnings calendar",
        next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no earnings calendar"


def test_skip_when_no_captured_chain():
    # rich/sellable/earnings-clear but the surface capture never ran for this
    # ticker (new listing, or a capture gap) — must not fall back to a model.
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
        chain=None,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no captured option chain"
    assert sig.short_put is None


def test_skip_when_captured_chain_has_no_spot():
    # The snapshot's own spot is the only basis whose deltas match the captured
    # legs — with it missing we must SKIP, never substitute the caller's spot.
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
        chain={**CHAIN, "spot": None},
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "captured chain has no spot"
    assert sig.short_put is None


def test_trade_reports_the_deltas_the_selected_strikes_actually_carry():
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
        chain=CHAIN,
    )
    assert sig.action == "TRADE"
    # the fixture deltas of the SELECTED legs (350 / 310), not the targets
    assert sig.short_put_delta == Decimal("0.25")
    assert sig.long_put_delta == Decimal("0.125")
    assert sig.chain_captured_on == AS_OF
    assert sig.expiry == EXPIRY


def test_skip_when_no_listed_strike_below_the_short_leg():
    thin_chain = {
        "captured_on": AS_OF,
        "expiry": EXPIRY,
        "spot": SPOT,
        "legs": [{"strike": 350, "delta": -0.25, "iv": IV}],  # only one leg captured
    }
    sig = decide_short_vol(
        as_of=AS_OF,
        spot=SPOT,
        iv=IV,
        rv=RV,
        vrp=0.073,
        vrp_z_20=1.6,
        gate_ok=True,
        next_earnings_date=CLEAR_EARNINGS,
        chain=thin_chain,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no listed strikes near target delta"


def test_select_bull_put_spread_prices_off_each_legs_own_iv():
    # The regression test for the flat-vol bug: short (350) and wing (310) carry
    # DIFFERENT captured IVs (0.473 vs 0.55). Pricing at one flat IV would give a
    # different credit than pricing each leg at its own IV.
    T = (EXPIRY - AS_OF).days / 365.0
    sel = select_chain_bull_put_spread(
        CHAIN_LEGS, SPOT, EXPIRY, AS_OF, 0.04, short_delta=0.25, wing_delta=0.125
    )
    assert sel is not None
    st = sel.spread
    assert (sel.short_delta, sel.wing_delta) == (0.25, 0.125)  # the ACTUAL deltas
    expected_short = bs_price(SPOT, 350, T, 0.04, 0.473, is_call=False)
    expected_long = bs_price(SPOT, 310, T, 0.04, 0.55, is_call=False)
    flat_vol_long = bs_price(SPOT, 310, T, 0.04, 0.473, is_call=False)
    assert st.leg_premiums == (expected_short, expected_long)
    assert expected_long != flat_vol_long  # proves the leg's own IV was actually used
    assert st.credit == expected_short - expected_long


class _StubRepo:
    def __init__(
        self,
        series,
        *,
        sellable_sector=None,
        has_earnings_calendar=False,
        chain=CHAIN,
    ):
        self._series = series
        self._sellable_sector = sellable_sector
        self._has_earnings = has_earnings_calendar
        self._chain = chain

    def fetch_vrp_daily_series(self, ticker, *, limit=60):
        return self._series

    def fetch_vrp_harvest_by_sector(self):
        if self._sellable_sector is None:
            return []
        return [
            {
                "sector": self._sellable_sector,
                "deviation_class": "RICH",
                "verdict": "HARVEST_SELLABLE",
            }
        ]

    def fetch_vrp_harvest_multihorizon(self):
        return []

    def fetch_watchlist_sector(self, ticker):
        return "Technology"

    def fetch_historical_earnings_dates(self, ticker):
        return {date(2026, 1, 15)} if self._has_earnings else set()

    def fetch_latest_next_earnings_date(self, ticker):
        return CLEAR_EARNINGS

    def fetch_put_chain_near_dte(self, ticker, as_of, target_dte):
        return self._chain


def _row(d, iv=IV):
    return {"market_date": d, "iv": iv, "rv": RV, "vrp": 0.073, "vrp_z_20": 1.6}


def test_build_returns_none_without_history():
    assert build_short_vol(_StubRepo([]), "TSLA", SPOT) is None


def test_build_skips_when_sector_not_sellable():
    sig = build_short_vol(_StubRepo([_row(AS_OF)]), "TSLA", SPOT)
    # empty sellable sets → single_name gate returns None → SKIP with the sector reason
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"


def test_build_skips_with_no_earnings_calendar_reason():
    # sellable sector but no historical earnings → distinct, honest reason (not "sector")
    repo = _StubRepo([_row(AS_OF)], sellable_sector="Technology")
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "no earnings calendar"


def test_build_trades_through_real_gate_path():
    # sellable sector + earnings calendar + clear next print → populated TRADE row.
    repo = _StubRepo(
        [_row(AS_OF)], sellable_sector="Technology", has_earnings_calendar=True
    )
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "TRADE"
    assert sig.short_put is not None and sig.long_put is not None
    assert sig.as_of == AS_OF


def test_build_skips_when_capture_never_ran():
    repo = _StubRepo(
        [_row(AS_OF)],
        sellable_sector="Technology",
        has_earnings_calendar=True,
        chain=None,
    )
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "no captured option chain"


def test_build_walks_back_past_null_iv_latest_row():
    # newest row has NULL iv; the card must use the most recent usable row, not go dead.
    newer, older = date(2026, 6, 24), date(2026, 6, 23)
    series = [_row(newer, iv=None), _row(older, iv=IV)]  # DESC, like the real query
    repo = _StubRepo(series, sellable_sector="Technology", has_earnings_calendar=True)
    sig = build_short_vol(repo, "TSLA", SPOT)
    assert sig is not None and sig.action == "TRADE"  # did NOT skip "no usable IV/spot"
    assert sig.as_of == older  # as_of reflects the row actually used
    assert sig.iv == Decimal(str(IV))
