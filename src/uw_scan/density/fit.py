"""v8 estimator + arm registry — vendored VERBATIM from signal-lab.

Source: signal-lab @ 0f893513, research/runs/_v8_estimator.py + research/runs/_v8_arms.py
(+ fit_gjr from scripts/forward_paths.py — dead code on arm G, kept so _fit stays verbatim).
Only this header, the imports, and the ARGON-ADDED "skewt" family differ from source;
every body below is byte-identical on the vendored `normal`/`t` paths (the sole permitted
edits: two function-local `from scripts.forward_paths import ...` lines deleted — both
names are module-level imports here). The skewt additions are branch-guarded on
`family == "skewt"`, so no vendored code path changes behaviour; the golden parity test
(arm G, Normal) is the standing proof. Frozen behaviours the parity
test pins: all 5 starts evaluated unconditionally (no early exit); select_attempt argmax
over admissible loglik, ties within LOGLIK_TOL -> lowest grid index via min over the
eligible set; _attempt catches bare Exception around model.fit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from uw_scan.density.cone import GJR_MIN_OBS, _to_pct_log
from uw_scan.density.constants import (
    CHANNEL_BAD_NU,
    CHANNEL_BAD_SKEW,
    CHANNEL_EXCEPTION,
    CHANNEL_INVALID_PARAMS,
    CHANNEL_NON_FINITE,
    CHANNEL_NON_FINITE_LL,
    CHANNEL_NON_STATIONARY,
    CHANNEL_NOT_CONVERGED,
    CHANNEL_OK,
    CHANNEL_TOO_SHORT,
    LOGLIK_TOL,
    MAX_FAILURE_CARRY_DAYS,
    MULTI_STARTS,
    SKEWT_START_LAMBDA,
    T_START_NU,
)

#: ARGON-ADDED. The innovation families `fit_v8` accepts. `normal`/`t` are v13's;
#: `skewt` is Hansen (1994)'s skewed t (arch's `SkewStudent`), parameterised by `eta`
#: (degrees of freedom, arch bound [2.05, 300]) and `lambda` (skewness, bound [-1, 1],
#: SYMMETRIC AT 0 where the density is exactly Student-t with nu = eta).
FAMILIES = ("normal", "t", "skewt")

@dataclass(frozen=True)
class Attempt:
    """One start's outcome. Recorded whether or not it is admissible — §2's classification needs
    the rejected attempts' log-likelihoods, and v7's probe had none of this."""

    grid_index: int
    admissible: bool
    channel: str
    loglik: float
    persistence: float
    converged: bool
    params: dict | None


def _guard(p: dict, family: str) -> tuple[bool, str, float]:
    """§3.3 admissibility, minus convergence (the caller supplies that). v5's guard unchanged."""
    vals = [p["omega"], p["alpha"], p["gamma"], p["beta"]]
    if family == "t":
        vals.append(p.get("nu", float("nan")))
    if family == "skewt":
        vals += [p.get("eta", float("nan")), p.get("lambda", float("nan"))]
    if not all(np.isfinite(v) for v in vals):
        return False, CHANNEL_NON_FINITE, float("nan")
    if p["omega"] <= 0.0 or p["alpha"] < 0.0 or p["beta"] < 0.0 or p["alpha"] + p["gamma"] < 0.0:
        return False, CHANNEL_INVALID_PARAMS, float("nan")
    # E[I(r<0)] = 1/2 for a symmetric innovation, so a GJR's persistence is alpha + gamma/2 + beta.
    # Kept UNCHANGED for skewt, deliberately: under an asymmetric innovation the exact term is
    # the half second moment E[z^2 * 1{z<0}], which is not 1/2 — but `cone.gjr_var_path` (frozen,
    # vendored, shared by every arm) seeds its recursion with omega / (1 - alpha - gamma/2 - beta),
    # so a guard using a DIFFERENT persistence could admit a fit whose simulator seed is negative.
    # The screen stays consistent with the simulator; the approximation is documented, not hidden.
    pers = p["alpha"] + p["gamma"] / 2.0 + p["beta"]
    if pers >= 1.0:
        return False, CHANNEL_NON_STATIONARY, float(pers)
    # §3.3 / §10.1: nu <= 2 leaves sqrt((nu-2)/nu) undefined, so the unit-variance standardisation
    # that keeps the S-vs-S+R substitution shape-only cannot be formed. The t quantiles themselves
    # are finite for any nu > 0; the constraint is about the normalisation, not their existence.
    if family == "t" and not (2.0 < p["nu"] < np.inf):
        return False, CHANNEL_BAD_NU, float(pers)
    # ARGON-ADDED, skewt only. `eta` is the same normalisation constraint as `nu` above.
    # `lambda` is Hansen's skewness: the density's b = sqrt(1 + 3*lambda^2 - a^2)
    # normalisation collapses at |lambda| = 1, so the OPEN interval is the admissible set
    # and a fit pinned on the bound is rejected rather than published.
    if family == "skewt":
        if not (2.0 < p["eta"] < np.inf):
            return False, CHANNEL_BAD_NU, float(pers)
        if not (-1.0 < p["lambda"] < 1.0):
            return False, CHANNEL_BAD_SKEW, float(pers)
    return True, CHANNEL_OK, float(pers)


def _attempt(hist: np.ndarray, family: str, grid_index: int, starts) -> Attempt:
    from arch.univariate import GARCH, Normal, SkewStudent, StudentsT, ZeroMean

    nan = float("nan")
    r_pct = _to_pct_log(hist)
    if r_pct.size < GJR_MIN_OBS:
        return Attempt(grid_index, False, CHANNEL_TOO_SHORT, nan, nan, False, None)
    dist = Normal()
    if family == "t":
        dist = StudentsT()
    elif family == "skewt":
        dist = SkewStudent()  # ARGON-ADDED: Hansen (1994), params (eta, lambda)
    model = ZeroMean(
        r_pct,
        volatility=GARCH(p=1, o=1, q=1),
        distribution=dist,
    )
    try:
        kw = {} if starts is None else {"starting_values": np.asarray(starts, dtype=float)}
        res = model.fit(disp="off", show_warning=False, **kw)
    except Exception:
        return Attempt(grid_index, False, CHANNEL_EXCEPTION, nan, nan, False, None)

    converged = int(getattr(res, "convergence_flag", 1)) == 0
    p = {
        "omega": float(res.params.get("omega", nan)),
        "alpha": float(res.params.get("alpha[1]", nan)),
        "gamma": float(res.params.get("gamma[1]", nan)),
        "beta": float(res.params.get("beta[1]", nan)),
    }
    if family == "t":
        p["nu"] = float(res.params.get("nu", nan))
    if family == "skewt":
        # arch names them exactly "eta" and "lambda"; keep its names so the persisted
        # params_jsonb is readable against the library that produced them. Extra keys are
        # inert downstream — `gjr_var_path` / `_gjr_simulate` read omega/alpha/gamma/beta only.
        p["eta"] = float(res.params.get("eta", nan))
        p["lambda"] = float(res.params.get("lambda", nan))
    loglik = float(getattr(res, "loglikelihood", nan))
    ok, channel, pers = _guard(p, family)
    if not np.isfinite(loglik):
        # A finite log-likelihood is a NECESSARY condition for admissibility, not a formality:
        # without it the §3.3 argmax has nothing to rank, `max_ll - nan <= tol` is False for every
        # attempt, and the eligible set comes back empty — turning a fit that should have been
        # rejected into a ValueError inside the selector.
        return Attempt(grid_index, False, CHANNEL_NON_FINITE_LL, loglik, pers, converged, None)
    if not converged:
        # §3.3: convergence is part of admissibility. `fit_gjr` never checked it — and its own
        # docstring says v5 §3 required exactly this routing, so the check was specified from the
        # start and never implemented. Recorded, not retro-fitted onto v5/v6/v7.
        return Attempt(grid_index, False, CHANNEL_NOT_CONVERGED, loglik, pers, False, None)
    return Attempt(grid_index, ok, channel, loglik, pers, True, p if ok else None)


def select_attempt(attempts: list[Attempt], *, loglik_tol: float = LOGLIK_TOL) -> Attempt | None:
    """§3.3's two-step rule: argmax over the admissible set, ties broken by LOWEST grid index.

    NOT pairwise comparison — "is this a tie?" is not transitive, so a pairwise scan can return
    different winners depending on iteration order.

    The finiteness filter is enforced at BOTH ends — `_attempt` rejects a non-finite loglik, and
    this refuses to rank one. Defence in depth, because an `Attempt` constructed by any other
    producer must not be able to empty the eligible set and raise out of the selector.
    """
    admissible = [a for a in attempts if a.admissible and np.isfinite(a.loglik)]
    if not admissible:
        return None
    max_ll = max(a.loglik for a in admissible)
    eligible = [a for a in admissible if max_ll - a.loglik <= loglik_tol]
    return min(eligible, key=lambda a: a.grid_index)


def _start_for(family: str, sv: tuple[float, float, float, float]):
    """The distribution's starting values appended to a variance start (§3.2's grid).

    ARGON-ADDED for `skewt` only; `normal` and `t` return exactly what the vendored
    comprehension returned. The skew start is the SYMMETRIC point, so multi-start does not
    seed an asymmetry the data did not ask for.
    """
    if family == "t":
        return (*sv, T_START_NU)
    if family == "skewt":
        return (*sv, T_START_NU, SKEWT_START_LAMBDA)
    return sv


def fit_v8(
    hist: np.ndarray,
    *,
    family: str = "normal",
    multi_start: bool = True,
    loglik_tol: float = LOGLIK_TOL,
) -> tuple[dict | None, list[Attempt]]:
    """§3.3. Returns `(selected_params_or_None, every_attempt)`.

    ALL starts are always evaluated — early exit would make selection order-dependent, and §2's
    classification needs the losers' log-likelihoods. `multi_start=False` is `A_default_v8`: the
    same admissibility contract, grid index 0 only.

    Selection is `select_attempt`'s two-step eligible-set rule.
    """
    if family not in FAMILIES:
        raise ValueError(f"family must be one of {FAMILIES}, got {family!r}")

    grid: list = [None]  # index 0 == the arch package's own default starting values
    if multi_start:
        grid += [_start_for(family, sv) for sv in MULTI_STARTS]

    attempts = [_attempt(hist, family, i, sv) for i, sv in enumerate(grid)]
    won = select_attempt(attempts, loglik_tol=loglik_tol)
    return (won.params if won is not None else None), attempts


def fit_gjr(returns_hist: np.ndarray) -> dict | None:
    """ZeroMean + GJR-GARCH(1,1,1) on percent log returns. None if the fit is unusable.

    ZeroMean, NOT ConstantMean (v5 §3, F-2): arm A is zero-drift by construction, so a fitted
    mean would make this arm differ from A in LOCATION as well as SCALE and any win could come
    from drift rather than from conditional scale.

    Returning None rather than raising is the contract: v5 §3 requires non-convergence,
    invalid parameters and non-finite variance to all route to the labelled `degraded`
    fallback, and the caller cannot distinguish those if this raises."""
    from arch.univariate import GARCH, ZeroMean

    r_pct = _to_pct_log(returns_hist)
    if r_pct.size < GJR_MIN_OBS:
        return None
    try:
        res = ZeroMean(r_pct, volatility=GARCH(p=1, o=1, q=1)).fit(
            disp="off", show_warning=False
        )
    except Exception:
        return None
    p = {
        "omega": float(res.params.get("omega", np.nan)),
        "alpha": float(res.params.get("alpha[1]", np.nan)),
        "gamma": float(res.params.get("gamma[1]", np.nan)),
        "beta": float(res.params.get("beta[1]", np.nan)),
    }
    if not all(np.isfinite(v) for v in p.values()):
        return None
    # Non-negative variance and stationarity. E[I(r<0)] = 1/2 for a symmetric innovation, so
    # the persistence of a GJR is alpha + gamma/2 + beta.
    if p["omega"] <= 0.0 or p["alpha"] < 0.0 or p["beta"] < 0.0 or p["alpha"] + p["gamma"] < 0.0:
        return None
    if p["alpha"] + p["gamma"] / 2.0 + p["beta"] >= 1.0:
        return None
    return p


@dataclass(frozen=True)
class ArmSpec:
    """`legacy` is `fit_gjr` VERBATIM — no convergence check, no start grid. It exists to
    reproduce v7, never as a production candidate, and it is the only arm that does not share the
    §3.3 admissibility contract."""

    family: str
    multi_start: bool
    retry: bool
    max_carry: int
    legacy: bool = False


#: §5.2. `retry=False, max_carry=0` is the SCHEDULED behaviour v6/v7 ran: a rejected refit is not
#: re-attempted, so the whole 21-day block is disabled. `G`/`H` add §3.4's ladder on top.
ARMS: dict[str, ArmSpec] = {
    "A_legacy": ArmSpec("normal", False, False, 0, legacy=True),
    "A_default_v8": ArmSpec("normal", False, False, 0),
    "B": ArmSpec("normal", True, False, 0),
    "C": ArmSpec("t", False, False, 0),
    "F": ArmSpec("t", True, False, 0),
    "G": ArmSpec("normal", True, True, MAX_FAILURE_CARRY_DAYS),
    "H": ArmSpec("t", True, True, MAX_FAILURE_CARRY_DAYS),
    # ARGON-ADDED research arm: arm G's configuration with an ASYMMETRIC innovation
    # (Hansen skewed-t) in the likelihood. Multi-character key on purpose — it is not one
    # of signal-lab's lettered v8 arms and must not read as one. Research-only; `forecast.ARM`
    # stays "G".
    "SKEWT": ArmSpec("skewt", True, True, MAX_FAILURE_CARRY_DAYS),
}


def _fit(spec: ArmSpec, hist: np.ndarray):
    """Returns `(params_or_None, attempts)`. Legacy has no attempt instrumentation by definition —
    it is v7's fitter, and adding instrumentation would make it a different estimator."""
    if spec.legacy:

        return fit_gjr(hist), []
    return fit_v8(hist, family=spec.family, multi_start=spec.multi_start)
