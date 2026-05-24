from datetime import date, datetime, timezone
from decimal import Decimal

from uw_scan.models import (
    CandidateStructure,
    InsightLeg,
    TradeInsightsHeader,
    TradeInsightsResponse,
)
from uw_scan.reports.trade_insights import (
    ParsedOptionSymbol,
    _atm_straddles_by_expiry,
    _build_candidates,
    _credit_spread_math,
    _mid,
    _normalized_contracts,
    assemble_trade_insights,
    parse_option_symbol,
)


def test_trade_insights_response_serializes_required_shape():
    response = TradeInsightsResponse(
        ticker="TSLA",
        header=TradeInsightsHeader(
            dominant_bias="NEUTRAL_SHORT_VOL",
            primary_setup="IV_RV_SPREAD_MEAN_REVERSION",
            confidence_label="MEDIUM",
            data_quality_label="MIXED",
            idea_count=1,
        ),
        candidate_structures=[
            CandidateStructure(
                idea_id="A",
                structure="call_credit_spread",
                thesis="Front premium is elevated.",
                expression_type="SHORT_VOL",
                rank=1,
                max_loss=Decimal("1.25"),
                legs=[
                    InsightLeg(
                        side="sell",
                        option_symbol="TSLA260515C00430000",
                        option_right="C",
                        expiry="2026-05-15",
                        strike=Decimal("430"),
                        mid=Decimal("9.50"),
                    )
                ],
            )
        ],
    )

    body = response.model_dump(mode="json")
    assert body["ticker"] == "TSLA"
    assert body["header"]["dominant_bias"] == "NEUTRAL_SHORT_VOL"
    assert body["candidate_structures"][0]["legs"][0]["strike"] == "430"
    assert body["source_reconciliation"]["status"] == "UNKNOWN"


def test_parse_option_symbol_occ_style():
    parsed = parse_option_symbol("TSLA260515C00430000")
    assert parsed == ParsedOptionSymbol(
        root="TSLA",
        expiry=date(2026, 5, 15),
        right="C",
        strike=Decimal("430"),
    )


def test_parse_option_symbol_rejects_bad_symbol():
    assert parse_option_symbol("bad") is None


def test_mid_uses_nbbo_when_present():
    assert _mid({"nbbo_bid": Decimal("1.00"), "nbbo_ask": Decimal("1.20")}) == Decimal(
        "1.10"
    )


def test_mid_falls_back_to_last_price():
    assert _mid({"last_price": Decimal("0.95")}) == Decimal("0.95")


def test_credit_spread_math_caps_loss_by_width_minus_credit():
    net_credit, max_loss, max_profit = _credit_spread_math(
        short_mid=Decimal("1.80"),
        long_mid=Decimal("0.55"),
        width=Decimal("5"),
    )
    assert net_credit == Decimal("1.25")
    assert max_loss == Decimal("3.75")
    assert max_profit == Decimal("1.25")


def _contract(
    symbol: str,
    *,
    bid: str,
    ask: str,
    iv: str = "0.52",
    volume: int = 1000,
    oi: int = 800,
):
    return {
        "option_symbol": symbol,
        "last_price": Decimal(bid),
        "nbbo_bid": Decimal(bid),
        "nbbo_ask": Decimal(ask),
        "implied_volatility": Decimal(iv),
        "open_interest": oi,
        "prev_oi": max(oi - 50, 0),
        "volume": volume,
        "ask_volume": int(volume * 0.55),
        "bid_volume": int(volume * 0.35),
        "total_premium": Decimal(bid) * Decimal(volume),
    }


class FakeTradeInsightsRepo:
    """Fixture spans the swing-HOLD entry window (21-60 DTE) so the
    deterministic candidate generator can build all 5 structures (verticals,
    iron condor, straddle, calendar). Dates relative to as_of=2026-05-13:
    6/12 = 30 DTE (swing sweet spot, rank 0), 7/24 = 72 DTE (outside swing
    entry window but inside calendar far-leg max of 90 DTE)."""

    def fetch_option_contracts_rich(self, run_id: int, ticker: str):
        return [
            # Swing entry (30 DTE): full strike grid for verticals + condor + straddle
            _contract(
                "TSLA260612P00420000", bid="6.10", ask="6.30", volume=450, oi=500
            ),
            _contract(
                "TSLA260612P00425000", bid="8.00", ask="8.20", volume=600, oi=700
            ),
            _contract(
                "TSLA260612P00430000", bid="10.20", ask="10.50", volume=900, oi=850
            ),
            _contract(
                "TSLA260612C00430000", bid="9.40", ask="9.60", volume=1500, oi=1000
            ),
            _contract(
                "TSLA260612C00435000", bid="6.90", ask="7.10", volume=1200, oi=800
            ),
            # Calendar far leg (72 DTE): single ATM call for the calendar spread.
            _contract(
                "TSLA260724C00430000",
                bid="13.80",
                ask="14.20",
                iv="0.48",
                volume=700,
                oi=900,
            ),
        ]

    def fetch_iv_term_rows(self, run_id: int, ticker: str):
        return [
            {
                "expiry": date(2026, 6, 12),
                "dte": 30,
                "implied_move_perc": Decimal("0.048"),
            },
            {
                "expiry": date(2026, 7, 24),
                "dte": 72,
                "implied_move_perc": Decimal("0.067"),
            },
        ]

    def fetch_source_reconciliation_rows(self, run_id: int, ticker: str):
        return []


def test_assemble_trade_insights_builds_research_response():
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )

    assert response.ticker == "TSLA"
    # V1 only emits MIXED or INSUFFICIENT; READY is reserved for a later patch
    # that wires event/source/liquidity gates fully.
    assert response.header.data_quality_label == "MIXED"
    assert response.signal_stack
    assert response.flow_table
    assert response.term_structure_table
    assert response.candidate_structures
    assert all(c.max_loss is not None for c in response.candidate_structures)
    assert {
        "call_credit_spread",
        "put_credit_spread",
        "iron_condor",
        "long_straddle",
        "calendar_spread",
    }.issubset({c.structure for c in response.candidate_structures})
    assert response.source_reconciliation.status == "UNKNOWN"
    assert response.header.preferred_idea_id == "A"
    assert response.synthesis.preferred_idea_id == "A"
    assert response.synthesis.best_risk_reward_idea_id == "A"
    assert response.candidate_structures[0].status == "preferred"
    assert all(
        c.status in {"preferred", "candidate"} for c in response.candidate_structures
    )
    assert not any(c.status == "needs_check" for c in response.candidate_structures)
    assert "Executable recommendation language" not in response.synthesis.avoid
    assert (
        "Confirm event calendar through all expiries"
        in response.synthesis.required_before_sizing
    )


def test_atm_straddles_preserve_input_order_for_equal_distance_ties():
    """ATM selection uses stable min() semantics for equal strike distance.

    This locks the pre-index behavior: when 425C and 435C are both 5 points
    from spot, the earlier input contract wins, and the put is selected nearest
    that chosen call strike.
    """
    contracts = _normalized_contracts(
        [
            _contract("TSLA260612C00425000", bid="7.00", ask="7.20"),
            _contract("TSLA260612C00435000", bid="6.00", ask="6.20"),
            _contract("TSLA260612P00425000", bid="4.00", ask="4.20"),
            _contract("TSLA260612P00435000", bid="5.00", ask="5.20"),
        ]
    )

    straddles = _atm_straddles_by_expiry(contracts, Decimal("430"))

    assert straddles[date(2026, 6, 12)] == Decimal("11.20")


def test_calendar_spread_preserves_far_call_order_for_same_strike():
    """Calendar lookup must preserve current far_calls list order per strike."""
    contracts = _normalized_contracts(
        [
            _contract("TSLA260612C00430000", bid="9.00", ask="9.20"),
            # Same strike/distance far calls: current stable far_calls ordering
            # chooses the first input row, not necessarily the earliest expiry.
            _contract("TSLA260724C00430000", bid="14.00", ask="14.20"),
            _contract("TSLA260717C00430000", bid="13.00", ask="13.20"),
        ]
    )

    candidates = _build_candidates(
        contracts,
        Decimal("430"),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
    )

    calendar = next(c for c in candidates if c.structure == "calendar_spread")
    assert calendar.legs[1].option_symbol == "TSLA260724C00430000"


def test_iron_condor_max_loss_matches_width_minus_total_credit():
    """Locks in the corrected formula: max(call_width, put_width) - total_credit.

    With the fake fixture (5-point wings on both sides, ~4.75 total credit),
    max loss should be 0.25 per spread, not max(call_spread.max_loss,
    put_spread.max_loss). The earlier draft of the plan used the latter and
    over-stated max loss by ~10x.
    """
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )
    ic = next(c for c in response.candidate_structures if c.structure == "iron_condor")
    call_spread = next(
        c for c in response.candidate_structures if c.structure == "call_credit_spread"
    )
    put_spread = next(
        c for c in response.candidate_structures if c.structure == "put_credit_spread"
    )

    expected_credit = (call_spread.net_credit_debit or Decimal("0")) + (
        put_spread.net_credit_debit or Decimal("0")
    )
    assert ic.net_credit_debit == expected_credit
    assert ic.max_profit == expected_credit
    # Both wings are 5 points wide in the fixture; max wing breach loss is
    # width - total_credit, not the max of the per-wing losses.
    assert ic.max_loss == Decimal("5") - expected_credit


# ─────────────────────────────────────────────────────────────────────────
# v5 M2: directional debit candidates + dte_band + expression_delta tagging.
# ─────────────────────────────────────────────────────────────────────────


def test_candidate_menu_includes_directional_debit_structures():
    """v5 M2: the candidate menu MUST surface directional debit structures
    (bull_call_spread, bear_put_spread, long_call, long_put) so the AI has
    something concrete to pick when directional_bias=LONG_DELTA or
    SHORT_DELTA. The v4 menu emitted only credit spreads / iron condor /
    straddle / calendar — biased toward vol-selling — which is the exact
    failure mode v5 is built to eliminate."""
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )
    structures = {c.structure for c in response.candidate_structures}
    assert "bull_call_spread" in structures, (
        "directional_swing LONG_DELTA needs a debit call structure"
    )
    assert "bear_put_spread" in structures, (
        "directional_swing SHORT_DELTA needs a debit put structure"
    )
    assert "long_call" in structures, "unbounded-upside long-delta missing"
    assert "long_put" in structures, "bounded-downside short-delta missing"


def test_candidate_menu_tags_dte_band_and_expression_delta():
    """v5 M2: every candidate must carry a non-empty dte_band ("momentum",
    "standard", or "trend") and expression_delta ("long_delta",
    "short_delta", or "neutral") so the v5 prompt can pattern-match
    candidates to the chosen directional_bias and dte_band."""
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )
    expected_delta_by_structure = {
        "call_credit_spread": "short_delta",
        "put_credit_spread": "long_delta",
        "iron_condor": "neutral",
        "long_straddle": "neutral",
        "calendar_spread": "neutral",
        "bull_call_spread": "long_delta",
        "bear_put_spread": "short_delta",
        "long_call": "long_delta",
        "long_put": "short_delta",
    }
    for cand in response.candidate_structures:
        # dte_band non-empty for every candidate whose first leg has an expiry
        # in the swing window (which all do, per the fixture).
        assert cand.dte_band in {"momentum", "standard", "trend"}, (
            f"{cand.structure} has bad dte_band={cand.dte_band!r}"
        )
        expected_delta = expected_delta_by_structure[cand.structure]
        assert cand.expression_delta == expected_delta, (
            f"{cand.structure} expression_delta={cand.expression_delta!r}, "
            f"expected {expected_delta!r}"
        )


def test_dte_band_helper_partitions_window_correctly():
    """v5 M2: the _dte_band helper splits the 14-75 DTE window into three
    bands. This pins the band boundaries so the prompt's DTE-band rule
    (M3) stays in sync with the assembler's tagging."""
    from uw_scan.reports.trade_insights import _dte_band

    assert _dte_band(14) == "momentum"
    assert _dte_band(21) == "momentum"
    assert _dte_band(30) == "momentum"
    assert _dte_band(31) == "standard"
    assert _dte_band(38) == "standard"
    assert _dte_band(44) == "standard"
    assert _dte_band(45) == "trend"
    assert _dte_band(60) == "trend"
    assert _dte_band(75) == "trend"


def test_dte_window_widened_to_14_75():
    """v5 M2: SWING_DTE_MIN dropped from 21 to 14 so the momentum band
    (14-30) admits short-DTE breakout entries that v4 rejected as
    horizon_mismatch. SWING_DTE_MAX raised from 60 to 75 so the trend band
    (45-75) admits longer-DTE trend-continuation entries."""
    from uw_scan.reports.trade_insights import SWING_DTE_MAX, SWING_DTE_MIN

    assert SWING_DTE_MIN == 14
    assert SWING_DTE_MAX == 75


def test_bull_call_spread_math_is_debit_with_capped_profit():
    """v5 M2: the bull_call_spread generator must report NEGATIVE
    net_credit_debit (it's a debit) and max_profit = (width - debit), not
    the credit-spread sign convention."""
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )
    bull_call = next(
        c for c in response.candidate_structures if c.structure == "bull_call_spread"
    )
    # Two legs: buy lower strike call, sell higher strike call.
    assert len(bull_call.legs) == 2
    assert bull_call.legs[0].side == "buy"
    assert bull_call.legs[1].side == "sell"
    assert bull_call.legs[0].strike < bull_call.legs[1].strike
    # Debit reported as NEGATIVE net_credit_debit (consistent w/ long_straddle).
    assert bull_call.net_credit_debit is not None
    assert bull_call.net_credit_debit < Decimal("0")
    # Max loss == debit; max profit == width - debit.
    width = bull_call.legs[1].strike - bull_call.legs[0].strike
    debit = -bull_call.net_credit_debit
    assert bull_call.max_loss == debit
    assert bull_call.max_profit == width - debit


def test_bear_put_spread_math_is_debit_with_capped_profit():
    """Mirror of bull_call test: bear_put_spread is debit, max profit
    bounded by (width - debit)."""
    response = assemble_trade_insights(
        ticker="TSLA",
        run_id=1,
        repo=FakeTradeInsightsRepo(),
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        spot=Decimal("428"),
    )
    bear_put = next(
        c for c in response.candidate_structures if c.structure == "bear_put_spread"
    )
    assert len(bear_put.legs) == 2
    assert bear_put.legs[0].side == "buy"
    assert bear_put.legs[1].side == "sell"
    assert bear_put.legs[0].strike > bear_put.legs[1].strike  # buy higher, sell lower
    assert bear_put.net_credit_debit is not None
    assert bear_put.net_credit_debit < Decimal("0")
    width = bear_put.legs[0].strike - bear_put.legs[1].strike
    debit = -bear_put.net_credit_debit
    assert bear_put.max_loss == debit
    assert bear_put.max_profit == width - debit
