"""Which recorded integrity failures are allowed to reach the math. Pure compute.

Argon has recorded statement violations since migration 114, and until now they
did exactly one thing: suppress a figure on the CARD. `violated_fields`' own
docstring says so — "the raw feature stays as computed and the DISPLAY layer
suppresses it". That was a deliberate, defensible choice at the time: editing
features would have changed validated math and broken the reproducibility of
every published result.

The cost is that a flagged number still SORTED the cross-section. A gross margin
of exactly 1.0, known to be a provider echo, still contributed a z-score that
moved every other name's rank. The card refused to show it and the ranking used
it anyway.

This module closes that, and the way it stays compatible with the paragraph above
is by being versioned rather than retroactive: exclusions apply under a NEW engine
version. Every `fundamentals-v1` row replays byte-identically, because none of
this code runs for it.

THREE EFFECTS, NOT ONE
----------------------
`exclude_field`        the named field is untrustworthy; anything derived from it
                       is withheld. The rest of the observation is fine.
`exclude_observation`  the statement contradicts itself, so no single field on it
                       is defensible — not just the one the check happened to
                       name.
`warn_only`            recorded, inspectable, and deliberately NOT excluded.
                       Kept as a category so that adding a noisy check later does
                       not require choosing between "silently ignore" and "delete
                       a third of the panel".

WHY EXCLUSION PROPAGATES THROUGH THE TTM WINDOW
-----------------------------------------------
The part that is easy to get wrong. Features are not per-quarter reads: `rev_ttm`
sums four quarters, so one bad `total_revenue` in quarter Q contaminates Q, Q+1,
Q+2 and Q+3. `rev_growth` compares TTM at i against TTM at i-4, so its reach is
eight quarters. Excluding only the violated quarter's own row would leave three
quarters of the damage in the math while the counters reported the field handled
— a worse state than not excluding at all, because it looks fixed.

`FEATURE_WINDOW` below mirrors the arithmetic in `features.build_features` and
must be edited with it, the same standing requirement `FEATURE_INPUTS` already
carries.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum

from uw_scan.fundamentals.features import FEATURE_INPUTS, FEATURES


class ViolationEffect(StrEnum):
    EXCLUDE_FIELD = "exclude_field"
    EXCLUDE_OBSERVATION = "exclude_observation"
    WARN_ONLY = "warn_only"


#: One entry per check in `statements.check_violations`. A check with no entry
#: raises rather than defaulting, so adding a check forces the effect decision
#: instead of letting it silently become warn-only.
CHECK_EFFECTS: dict[str, ViolationEffect] = {
    # UW echoes total_revenue into gross_profit while still reporting a positive
    # cost_of_revenue. The field is wrong; the rest of the income statement is
    # internally consistent, so only gross_profit's dependents go.
    "gross_profit_equals_revenue_despite_costs": ViolationEffect.EXCLUDE_FIELD,
    # A share count off by orders of magnitude. Not a feature input, but it is
    # the denominator of every per-share and market-cap figure downstream.
    "implausible_share_count": ViolationEffect.EXCLUDE_FIELD,
    # liabilities + equity exceeds assets in the direction NCI cannot explain.
    # The statement contradicts itself, so no single line on it is defensible.
    "accounting_identity_reversed": ViolationEffect.EXCLUDE_OBSERVATION,
    # Negative total liabilities is not a small error; it is a sign flip, and a
    # sign flip anywhere on a balance sheet impugns the whole statement.
    "negative_total_liabilities": ViolationEffect.EXCLUDE_OBSERVATION,
    # Cash-flow net_income has the opposite sign of the income statement's, at
    # nearly the same magnitude -- a vendor sign inversion isolated to that one
    # figure (see `check_net_income_sign_flip`). The rest of the income
    # statement (revenue, margins, etc.) is unaffected, so only net_income and
    # its dependents (`roe`) go, not the whole observation.
    "net_income_sign_flipped_across_statements": ViolationEffect.EXCLUDE_FIELD,
}

#: How many trailing quarters each feature reads. Mirrors `build_features`:
#: quarterly ratios read one period, TTM ratios read four, and `rev_growth`
#: compares two TTM windows four apart, so it reaches eight.
FEATURE_WINDOW: dict[str, int] = {
    "rev_growth": 8,
    "gross_margin": 1,
    "op_margin": 1,
    "fcf_margin": 4,
    "roe": 4,
    "neg_net_debt_ebitda": 4,
    "asset_turnover": 4,
}

#: Every field any feature reads. `exclude_observation` withholds all of them.
ALL_FEATURE_INPUTS: frozenset[str] = frozenset(
    f for fields in FEATURE_INPUTS.values() for f in fields
)

VALIDITY_POLICY_OFF = "off"
VALIDITY_POLICY_EXCLUDE = "exclude"


def effect_for(check_name: str) -> ViolationEffect:
    """The declared effect. Raises on an unregistered check, deliberately.

    A `.get(..., WARN_ONLY)` default would mean a new integrity check silently
    does nothing, which is indistinguishable from not having written it.
    """
    try:
        return CHECK_EFFECTS[check_name]
    except KeyError as exc:
        raise KeyError(
            f"check {check_name!r} has no declared ViolationEffect; add one to "
            "CHECK_EFFECTS — a check with no effect is a check that does nothing"
        ) from exc


def excluded_fields(violations: Mapping[str, Sequence[str]]) -> set[str]:
    """`{field: [check, ...]}` -> the fields whose values must not be used.

    An `exclude_observation` check widens to every feature input on the
    observation, not just the field the check happened to name.
    """
    out: set[str] = set()
    for field, checks in violations.items():
        for check in checks:
            effect = effect_for(check)
            if effect is ViolationEffect.EXCLUDE_OBSERVATION:
                return set(ALL_FEATURE_INPUTS) | {field}
            if effect is ViolationEffect.EXCLUDE_FIELD:
                out.add(field)
    return out


def features_touching(fields: set[str]) -> set[str]:
    """Which features read any of `fields`."""
    return {
        feat
        for feat in FEATURES
        if any(src in fields for src in FEATURE_INPUTS.get(feat, ()))
    }


def contaminated(
    periods: Sequence[str], violated_by_period: Mapping[str, set[str]]
) -> dict[str, set[str]]:
    """period -> features that must be withheld, TTM contamination included.

    `periods` must be chronologically sorted — the same order `build_features`
    iterates. A violated field at index i withholds its dependent features at
    every index from i up to i + window - 1, because those are the periods whose
    trailing window still contains i.
    """
    out: dict[str, set[str]] = {p: set() for p in periods}
    for i, period in enumerate(periods):
        bad = violated_by_period.get(period)
        if not bad:
            continue
        for feat in features_touching(bad):
            span = FEATURE_WINDOW.get(feat, 1)
            for j in range(i, min(i + span, len(periods))):
                out[periods[j]].add(feat)
    return out


def apply_validity(
    features: Mapping[str, Mapping[str, Mapping[str, float | None]]],
    violated_by_ticker_period: Mapping[str, Mapping[str, set[str]]],
) -> tuple[dict[str, dict[str, dict[str, float | None]]], dict[str, int]]:
    """Withhold contaminated feature values. Returns (features, counters).

    The shape in and out is identical to `build_features`', so this is a filter a
    caller can skip entirely — which is exactly what the v1 engine does.
    """
    cleaned: dict[str, dict[str, dict[str, float | None]]] = {}
    counters: dict[str, int] = {"values_excluded": 0, "periods_touched": 0}
    for ticker, by_period in features.items():
        periods = sorted(by_period)
        withhold = contaminated(periods, violated_by_ticker_period.get(ticker, {}))
        out_periods: dict[str, dict[str, float | None]] = {}
        for period in periods:
            drop = withhold.get(period) or set()
            row = dict(by_period[period])
            hit = 0
            for feat in drop:
                if row.get(feat) is not None:
                    row[feat] = None
                    hit += 1
            if hit:
                counters["values_excluded"] += hit
                counters["periods_touched"] += 1
            out_periods[period] = row
        cleaned[ticker] = out_periods
    return cleaned, counters


#: Which code version runs which policy. THE coupling: a validity policy is part
#: of the method, not a runtime flag, so it cannot be set independently of the
#: version a result is stamped with. Two independently-settable constants is how
#: a suite stays green while production computes something the version does not
#: describe — the failure already recorded for the macro engine/parameter pair.
VALIDITY_BY_CODE_VERSION: dict[str, str] = {
    "fundamentals-v1": VALIDITY_POLICY_OFF,
    "fundamentals-v2": VALIDITY_POLICY_EXCLUDE,
}


def policy_for_engine(engine_version: str) -> str:
    """`fundamentals-v2:abc12345` -> its validity policy. Raises if unregistered.

    Refusing an unknown code version is the point: an engine whose validity
    behaviour nobody declared must not silently inherit v1's (no exclusions) and
    publish rows claiming a method it does not run.
    """
    code = engine_version.split(":", 1)[0]
    try:
        return VALIDITY_BY_CODE_VERSION[code]
    except KeyError as exc:
        raise KeyError(
            f"engine {engine_version!r} has no declared validity policy; add "
            f"{code!r} to VALIDITY_BY_CODE_VERSION"
        ) from exc
