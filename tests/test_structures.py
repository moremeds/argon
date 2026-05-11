from uw_scan.models import SignalDirection
from uw_scan.structures import suggest_structure


def test_suggest_call_debit_spread_for_bullish_deep_conviction():
    idea = suggest_structure(direction=SignalDirection.BULLISH, setup_types=["Deep Conviction Directional"], iv_rank=45)
    assert idea.structure_type == "Call debit spread candidate"
    assert idea.max_risk_note == "Sizing deferred"


def test_suggest_iron_condor_for_high_iv_earnings():
    idea = suggest_structure(direction=SignalDirection.NEUTRAL, setup_types=["Earnings IV Crush"], iv_rank=82)
    assert idea.structure_type == "Defined-risk iron condor candidate"
