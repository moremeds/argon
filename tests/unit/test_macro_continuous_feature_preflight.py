"""The AR(1) correction, tested directly — it is the pivot of the MC6 verdict.

`eff_n` is the only number that separates "294 weekly reads" from "12.8 independent
observations", and the whole `descriptive_only` verdict turns on it. A wrong correction
would not fail anything else in the repo: the script prints, the doc quotes the print,
and nobody would know.
"""

from __future__ import annotations

import math

from scripts.research.macro_continuous_feature_preflight import ar1_effective_n


class TestASlowSeriesCarriesFewerObservationsThanItsLength:
    def test_a_constant_carries_exactly_one(self) -> None:
        # Not zero: reading the same number 300 times is one observation, not none.
        rho, eff = ar1_effective_n([5.0] * 300)
        assert (rho, eff) == (1.0, 1.0)

    def test_a_monotone_ramp_is_worth_a_fraction_of_its_length(self) -> None:
        rho, eff = ar1_effective_n([float(i) for i in range(300)])
        assert rho > 0.95
        assert eff < 10, (
            f"a 300-point ramp scored {eff}; it is one trend, not 300 draws"
        )

    def test_an_alternating_series_is_worth_more_than_its_length(self) -> None:
        # Negative autocorrelation genuinely carries more than N independent draws.
        rho, eff = ar1_effective_n([1.0, -1.0] * 150)
        assert rho < -0.95
        assert eff > 300

    def test_too_short_to_estimate_returns_the_raw_count(self) -> None:
        rho, eff = ar1_effective_n([1.0, 2.0])
        assert math.isnan(rho)
        assert eff == 2.0


class TestTheVerdictsCitedNumbersReproduce:
    """The doc quotes measured values; this pins the arithmetic behind them.

    Measured 2026-08-24 over 294 weekly instants, 2021-01-04..2026-08-18.
    """

    def test_dtwexbgs_momentum_scores_about_thirteen(self) -> None:
        # rho as measured for `usd change.DTWEXBGS`, the quantity the USD engine's
        # threshold sits on. 280 points is what the replay actually produced.
        eff = 280 * (1 - 0.9127) / (1 + 0.9127)
        assert 12.5 < eff < 13.0, eff

    def test_reaching_a_modest_effective_hundred_takes_decades(self) -> None:
        weeks = 100 * (1 + 0.9127) / (1 - 0.9127)
        assert weeks / 52 > 40, (
            "the verdict claims 42 years; a shorter answer changes it"
        )
