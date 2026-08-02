"""Shared parity-tolerance helper for the v13 density golden tests.

Not a test module — imported by test_parity_golden.py and test_forecast.py so the two
goldens cannot drift apart on what "matches the research" means.

The bound and its justification live in test_parity_golden.py's module docstring; the
short version: discrete things (panel index, seed, dates) are asserted exactly, and the
float chain is bounded because the golden was fitted on macOS/arm64 while CI runs
Linux/x86-64, where the iterative GJR maximum-likelihood fit converges to a marginally
different stationary point (measured 1.1e-7 relative on omega; 1 ULP on the analytic
EWMA path). A structural port error moves results by >= 1e-3, which this still catches.
"""

from __future__ import annotations

#: Six-plus orders of magnitude below any structural error, ~10x above the measured
#: cross-platform convergence noise.
REL_TOL = 1e-6
#: Keeps near-zero quantiles (the p50 is ~1e-3) off an unreachable relative bound.
ABS_FLOOR = 1e-12


class Drift:
    """Assert each value is within the bound; remember the worst for the CI log."""

    def __init__(self) -> None:
        self.worst = 0.0
        self.where = "-"

    def check(self, got: float, want: float, where: str) -> None:
        got, want = float(got), float(want)
        delta = abs(got - want)
        assert delta <= max(ABS_FLOOR, REL_TOL * abs(want)), (
            f"{where} drifted beyond the cross-platform bound: "
            f"{got!r} vs {want!r} (|delta| {delta:.3e})"
        )
        rel = delta / abs(want) if want else delta
        if rel > self.worst:
            self.worst, self.where = rel, where

    def report(self, label: str) -> None:
        print(
            f"\n[parity] {label}: worst relative delta {self.worst:.3e} "
            f"at {self.where} (bound {REL_TOL:.0e})"
        )
