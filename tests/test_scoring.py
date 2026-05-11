from uw_scan.scoring import score_flow_candidate


def test_score_flow_candidate_deep_conviction_call():
    score = score_flow_candidate(
        volume=2400,
        open_interest=900,
        ask_side_pct=0.88,
        premium=1_250_000,
        is_single_leg=True,
        moneyness_pct=0.04,
        dte=39,
    )
    assert score.score == 5
    assert "Volume > OI" in score.confirmations


def test_score_flow_candidate_warns_on_low_dte():
    score = score_flow_candidate(
        volume=2400,
        open_interest=900,
        ask_side_pct=0.88,
        premium=1_250_000,
        is_single_leg=True,
        moneyness_pct=0.04,
        dte=1,
    )
    assert score.score == 4
    assert "DTE below minimum" in score.warnings
