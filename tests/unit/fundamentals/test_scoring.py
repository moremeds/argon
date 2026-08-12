"""Composite construction and result identity (migration 115, stage 2).

The identity tests are load-bearing: `(ticker, as_of, engine_version, inputs_hash)`
is the primary key of an immutable result, so a hash that misses an input silently
keeps a stale row alive, and a version that can be hand-set silently reinterprets
history under the wrong method.
"""

from __future__ import annotations

import pytest

from uw_scan.fundamentals.features import FEATURES
from uw_scan.fundamentals.scoring import (
    MIN_CROSS_SECTION,
    composite_scores,
    cross_section_z,
    engine_version,
    inputs_hash,
    param_hash,
    zscore,
)


def _rows(values: dict[str, float]) -> dict[str, dict]:
    return {t: {"features": dict.fromkeys(FEATURES, v)} for t, v in values.items()}


def test_composite_orders_by_feature_level():
    rows = _rows({f"P{i}": 2.0 for i in range(MIN_CROSS_SECTION)})
    rows.update(_rows({"LOW": 1.0, "HIGH": 3.0}))
    comp = composite_scores(cross_section_z(rows), rows)
    assert comp["HIGH"] > comp["LOW"]


def test_presence_renormalization_keeps_partial_names_comparable():
    """A name scored on 4 features must sit on the same scale as one scored on 7,
    not be dragged toward zero by the three it lacks."""
    rows = _rows({f"P{i}": 2.0 for i in range(MIN_CROSS_SECTION)})
    rows["HIGH"] = {"features": dict.fromkeys(FEATURES, 3.0)}
    zs = cross_section_z(rows)
    full = composite_scores(zs, ["HIGH"])["HIGH"]
    partial = composite_scores({f: zs[f] for f in FEATURES[:4]}, ["HIGH"])["HIGH"]
    assert partial == pytest.approx(full)


def test_below_the_feature_floor_there_is_no_composite():
    rows = _rows({f"P{i}": 2.0 for i in range(MIN_CROSS_SECTION)})
    rows["THIN"] = {"features": dict.fromkeys(FEATURES, 3.0)}
    zs = cross_section_z(rows)
    assert composite_scores({f: zs[f] for f in FEATURES[:3]}, ["THIN"]) == {}


def test_thin_cross_section_produces_no_zscores():
    """Standardizing across a handful of names would be dominated by them."""
    rows = _rows({f"P{i}": float(i) for i in range(MIN_CROSS_SECTION - 1)})
    assert cross_section_z(rows) == {}


def test_zero_variance_does_not_divide_by_zero():
    assert zscore({"A": 5.0, "B": 5.0}) == {"A": 0.0, "B": 0.0}


def test_engine_version_is_formatting_insensitive():
    """0.1 and 0.10 are one parameter set; producing two versions would fork the
    result history on a typo."""
    assert engine_version({"a": 0.1}) == engine_version({"a": 0.10})
    assert param_hash({"a": 0.1}) == param_hash({"a": 0.10})


def test_engine_version_changes_with_parameters():
    assert engine_version({"a": 0.1}) != engine_version({"a": 0.2})


def test_engine_version_is_derived_from_code_and_params():
    v = engine_version({"a": 1.0}, code_version="probe")
    assert v.startswith("probe:") and len(v.split(":")[1]) == 8


def test_inputs_hash_covers_company_type():
    """The reason this is not just a hash of the financials: a company_type flip
    changes the valuation method while the figures stay put, and a hash blind to
    it would leave the stale result indistinguishable from the fresh one."""
    f = dict.fromkeys(FEATURES, 1.0)
    e = engine_version({"a": 1.0})
    assert inputs_hash(features=f, company_type="chips", engine=e) != inputs_hash(
        features=f, company_type="software", engine=e
    )


def test_inputs_hash_covers_engine_version():
    f = dict.fromkeys(FEATURES, 1.0)
    assert inputs_hash(
        features=f, company_type=None, engine=engine_version({"a": 1.0})
    ) != inputs_hash(features=f, company_type=None, engine=engine_version({"a": 2.0}))


def test_inputs_hash_is_stable_and_sensitive():
    e = engine_version({"a": 1.0})
    f = dict.fromkeys(FEATURES, 1.0)
    assert inputs_hash(features=f, company_type="x", engine=e) == inputs_hash(
        features=dict(f), company_type="x", engine=e
    )
    changed = dict(f, roe=1.0000001)
    assert inputs_hash(features=changed, company_type="x", engine=e) != inputs_hash(
        features=f, company_type="x", engine=e
    )


def test_inputs_hash_distinguishes_missing_from_zero():
    """`None` and `0.0` are different facts — one is an absent input, the other a
    reported figure — and must not collide."""
    e = engine_version({"a": 1.0})
    missing = dict.fromkeys(FEATURES, 1.0) | {"roe": None}
    zero = dict.fromkeys(FEATURES, 1.0) | {"roe": 0.0}
    assert inputs_hash(features=missing, company_type=None, engine=e) != inputs_hash(
        features=zero, company_type=None, engine=e
    )
