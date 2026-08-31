from __future__ import annotations

import math
import random

import pytest

from scripts.backtest_canary import _auc


def _pairwise_reference(scores: list[float], labels: list[int | None]) -> float:
    pairs = [(score, label) for score, label in zip(scores, labels) if label is not None]
    positives = [score for score, label in pairs if label == 1]
    negatives = [score for score, label in pairs if label == 0]
    if not positives or not negatives:
        return float("nan")
    wins = ties = 0
    for positive in positives:
        for negative in negatives:
            if positive > negative:
                wins += 1
            elif positive == negative:
                ties += 1
    return (wins + 0.5 * ties) / (len(positives) * len(negatives))


@pytest.mark.parametrize(
    ("scores", "labels", "expected"),
    [
        ([], [], math.nan),
        ([1.0, 2.0], [None, None], math.nan),
        ([1.0, 2.0], [1, 1], math.nan),
        ([1.0, 2.0], [0, 0], math.nan),
        ([2.0, 1.0], [1, 0], 1.0),
        ([1.0, 2.0], [1, 0], 0.0),
        ([1.0, 1.0], [1, 0], 0.5),
        ([1.0, 1.0, 2.0, 2.0], [0, 1, 0, 1], 0.5),
        ([3.0, 1.0, 3.0, 2.0], [1, 0, None, 0], 1.0),
    ],
)
def test_auc_edge_cases_preserve_pairwise_semantics(scores, labels, expected):
    actual = _auc(scores, labels)
    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == expected


@pytest.mark.parametrize("seed", range(25))
def test_auc_matches_pairwise_reference_with_ties_and_missing_labels(seed: int):
    rng = random.Random(seed)
    scores = [round(rng.uniform(-3, 3), 1) for _ in range(150)]
    labels = [rng.choice((0, 1, None)) for _ in scores]

    expected = _pairwise_reference(scores, labels)
    actual = _auc(scores, labels)

    if math.isnan(expected):
        assert math.isnan(actual)
    else:
        assert actual == expected


class _CountingScore:
    comparisons = 0

    def __init__(self, value: int) -> None:
        self.value = value

    @classmethod
    def _compare(cls) -> None:
        cls.comparisons += 1

    def __lt__(self, other: object) -> bool:
        type(self)._compare()
        return self.value < other.value  # type: ignore[attr-defined]

    def __gt__(self, other: object) -> bool:
        type(self)._compare()
        return self.value > other.value  # type: ignore[attr-defined]

    def __eq__(self, other: object) -> bool:
        type(self)._compare()
        return isinstance(other, _CountingScore) and self.value == other.value


def test_auc_comparison_growth_is_subquadratic():
    # 200 positives × 200 negatives makes the old pairwise implementation perform
    # at least 40,000 comparisons. Sorting/grouping stays comfortably below 10,000.
    scores = [_CountingScore(i) for i in range(400)]
    labels = [i % 2 for i in range(400)]
    _CountingScore.comparisons = 0

    assert _auc(scores, labels) > 0
    assert _CountingScore.comparisons < 10_000
