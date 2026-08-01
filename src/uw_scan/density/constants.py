"""Frozen constants of the v13 SPX density model — vendored VERBATIM from signal-lab.

Source: signal-lab @ 0f893513 ($LAB = plugins/signal-lab/skills/signal-lab), validated by
run 2026-08-01-spx-density-v13 (verdict PASS). DO NOT EDIT VALUES — the golden parity test
(tests/unit/density/test_parity_golden.py) pins behaviour; any change here is a different
model wearing the same name.

Origins:
  scripts/forward_paths.py:13,623        QUANTILES, GJR_MIN_OBS
  research/runs/_shd_v5.py:27-32         HORIZONS, H_MAX, M_PATHS, LAM
  research/runs/_shd_v6.py:29-31,459-461 V5_ANCHOR, SEED_BASE, seed_for
  research/runs/_v8_estimator.py:18-38   MULTI_STARTS, T_START_NU, CHANNEL_*
  research/runs/_shd_v8.py:63,65         MAX_FAILURE_CARRY_DAYS, LOGLIK_TOL
  research/runs/_v8_arms.py:59-70        OVERLAY_BURN_IN, OVERLAY_MIN_POOL, EWMA_LAMBDA
  research/runs/_v6_certification.py:62  BAND_80
Argon-added (anchors, not model parameters): PANEL_SHA256, PANEL_FIRST_DATE.
"""

from __future__ import annotations

from datetime import date

QUANTILES: tuple[float, ...] = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)

GJR_MIN_OBS = 756  # v5 §3: below this, the caller falls back to arm A and labels `degraded`

HORIZONS = (1, 2, 3, 5)
H_MAX = max(HORIZONS)
M_PATHS = 10000
LAM = 0.94

# --- §3.3 parity anchor — FROZEN ----------------------------------------------------------
V5_ANCHOR = 755  # the index the v6 driver ITERATES from
SEED_BASE = 20260728


def seed_for(i: int) -> int:
    """v5's exact per-date seed. A function of the PANEL INDEX, never of loop position."""
    return SEED_BASE + (i - V5_ANCHOR)


#: §3.2. Index 0 is the arch package's own default; §5.3's no-harm invariant depends on that,
#: because it makes `B`'s attempt set a superset of `A_default_v8`'s. Constants, NEVER sampled —
#: a randomised multi-start would make availability itself seed-dependent.
MULTI_STARTS: tuple[tuple[float, float, float, float], ...] = (
    (0.05, 0.05, 0.05, 0.85),
    (0.02, 0.02, 0.02, 0.90),
    (0.10, 0.10, 0.10, 0.70),
    (0.20, 0.01, 0.15, 0.60),
)
#: §3.2. Student-t carries a trailing `nu` the Normal model does not.
T_START_NU = 8.0

CHANNEL_OK = "ok"
CHANNEL_TOO_SHORT = "too_short"
CHANNEL_EXCEPTION = "exception"
CHANNEL_NOT_CONVERGED = "not_converged"
CHANNEL_NON_FINITE = "non_finite"
CHANNEL_INVALID_PARAMS = "invalid_params"
CHANNEL_NON_STATIONARY = "non_stationary"
CHANNEL_BAD_NU = "bad_nu"
CHANNEL_NON_FINITE_LL = "non_finite_loglik"

MAX_FAILURE_CARRY_DAYS = 10
LOGLIK_TOL = 1e-6

#: §3.5. PASSED EXPLICITLY at the call site, never taken from `gjr_std_boot_cone`'s signature
#: defaults (see _v8_arms.py:59-64 for the full rationale).
OVERLAY_BURN_IN = 252
OVERLAY_MIN_POOL = 756

#: §5's EWMA baseline decay, likewise passed explicitly.
EWMA_LAMBDA = LAM

BAND_80 = (QUANTILES.index(0.10), QUANTILES.index(0.90))  # v5 §4(3)

# --- argon-added anchors (not model parameters) -------------------------------------------
PANEL_SHA256 = "bd95c2ab96610b492f9ebdeaa4485e918fca2c1b80c122127aa9743c5e102c81"
PANEL_FIRST_DATE = date(
    2009, 9, 18
)  # panel row 0 — the origin of the seed's index frame
