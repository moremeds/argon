from uw_scan.rates.scorecard import (
    DEFAULT_SCORECARD_GROUPS,
    compute_composite_score,
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
