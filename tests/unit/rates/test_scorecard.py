from uw_scan.rates.scorecard import (
    DEFAULT_SCORECARD_GROUPS,
    compute_composite_score,
    compute_coverage,
    build_scorecard,
    _duration_stance,
    score_group,
)


def test_default_scorecard_weights_match_reference_layout():
    assert [group.weight for group in DEFAULT_SCORECARD_GROUPS] == [
        25,
        25,
        15,
        15,
        10,
        10,
    ]


def test_group_score_is_average_of_available_factor_scores():
    group = DEFAULT_SCORECARD_GROUPS[0].model_copy(
        deep=True,
        update={
            "factors": [
                {"label": "a", "score": -2.0, "status": "ok"},
                {"label": "b", "score": 1.0, "status": "ok"},
                {"label": "c", "score": None, "status": "missing"},
            ]
        },
    )

    assert score_group(group) == -0.5


def test_composite_score_is_weighted_average_of_available_groups():
    groups = [
        DEFAULT_SCORECARD_GROUPS[0].model_copy(update={"weight": 25, "score": -1.0}),
        DEFAULT_SCORECARD_GROUPS[1].model_copy(update={"weight": 25, "score": 1.0}),
        DEFAULT_SCORECARD_GROUPS[2].model_copy(update={"weight": 50, "score": None}),
    ]

    assert compute_composite_score(groups) == 0.0


def test_composite_renormalises_over_surviving_weight():
    """The behaviour that made a stance untrustworthy, pinned so it cannot drift back.

    One populated group out of six produces the same composite as six populated groups
    would. The number is not wrong -- it is the honest mean of what arrived -- but it
    carries no signal about how much arrived, which is why coverage travels with it.
    """
    groups = [group.model_copy(deep=True) for group in DEFAULT_SCORECARD_GROUPS]
    groups[0].score = 1.0
    assert compute_composite_score(groups) == 1.0
    assert compute_coverage(groups) == 0.25


def test_coverage_is_the_share_of_scored_weight():
    groups = [group.model_copy(deep=True) for group in DEFAULT_SCORECARD_GROUPS]
    assert compute_coverage(groups) == 0.0
    for group in groups:
        group.score = 0.0
    assert compute_coverage(groups) == 1.0


def test_a_missing_score_is_unknown_rather_than_neutral():
    """Absence of evidence and a balanced reading are opposite claims."""
    assert _duration_stance(None, 1.0) == "UNKNOWN"


def test_a_confident_score_below_the_coverage_floor_is_refused():
    assert _duration_stance(-1.0, 0.45) == "UNKNOWN"
    assert _duration_stance(-1.0, 0.5) == "SELL"
    assert _duration_stance(1.0, 0.5) == "BUY"


def test_the_live_scorecard_cannot_reach_a_stance_on_todays_feeds():
    """Three of six groups are hard-coded as missing until the Phase 2 feeds land.

    That is 45% of the weight, below the floor, so the desk reports UNKNOWN with the
    coverage stated instead of a BUY or SELL built on half the evidence.
    """
    scorecard = build_scorecard(
        ten_year_1m_delta_bps=40.0,
        curve_score=0.0,
        effr=5.5,
        real_10y=2.4,
        breakeven_10y=2.6,
    )
    assert scorecard.composite_score is not None
    assert scorecard.coverage == 0.45
    assert scorecard.duration_stance == "UNKNOWN"
    assert "Macro Fundamentals" in scorecard.coverage_detail
