"""Stage-2 scoring: cross-sectional z-scores, composite, and result identity.

Pure compute. Like `features.py`, this is the validated math and the research
scripts import it rather than owning a copy — verified by re-running the wide
validation and confirming `validation_wide.json` byte-identical.

WHAT THE COMPOSITE IS, AND THE THREE THINGS IT IS NOT
-----------------------------------------------------
It is a cross-sectional z-score mean over the seven features, equally weighted.
That construction is the one carrying the validated IC (0.039 leak-free, t 2.67);
see `docs/research/2026-08-12-fundamental-weighting-probe/DECISION.md` for why the
spec's rubric weights are seeded INACTIVE instead.

It is not an expected return — the cost study found zero gross alpha at every
slice. It is not a risk score — the top decile carries roughly double the middle's
>20%-loss rate. It is not a per-name forecast — the within-ticker test is a powered
null. It orders typical outcomes across a wide cross-section, and that is the whole
of the claim.

Run `uv run python -m uw_scan.fundamentals.scoring` for the self-check.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

from uw_scan.fundamentals.features import FEATURES

# A cross-section thinner than this cannot produce a meaningful z-score: the
# standardization would be dominated by the handful of names in it.
MIN_CROSS_SECTION = 8

# A name scored on fewer than this many of the seven features is not comparable to
# one scored on all seven, so it gets no composite rather than a flattering partial.
MIN_FEATURES = 4

CODE_VERSION = "fundamentals-v1"


def zscore(vals: Mapping[str, float]) -> dict[str, float]:
    """Population z-score across a cross-section. Zero-variance -> all zeros."""
    v = list(vals.values())
    n = len(v)
    mu = sum(v) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in v) / n) if n > 1 else 0.0
    return {k: ((x - mu) / sd if sd else 0.0) for k, x in vals.items()}


def composite_scores(
    zs: Mapping[str, Mapping[str, float]],
    tickers: Any,
    weights: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """Weighted mean of available z-scores, renormalized by what is present.

    Renormalizing by presence rather than by the full weight vector is what makes
    a name with five features comparable to one with seven, instead of silently
    penalized for the two it is missing.
    """
    comp: dict[str, float] = {}
    for t in tickers:
        num = den = 0.0
        got = 0
        for f in zs:
            if t not in zs[f]:
                continue
            w = 1.0 if weights is None else float(weights.get(f, 0.0))
            if not w:
                continue
            num += w * zs[f][t]
            den += w
            got += 1
        if got >= MIN_FEATURES and den:
            comp[t] = num / den
    return comp


def cross_section_z(
    rows: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, float]]:
    """Per-feature z-scores across one knowledge-quarter cross-section."""
    zs: dict[str, dict[str, float]] = {}
    for feat in FEATURES:
        vals = {
            t: d["features"][feat]
            for t, d in rows.items()
            if d["features"].get(feat) is not None
        }
        if len(vals) >= MIN_CROSS_SECTION:
            zs[feat] = zscore(vals)
    return zs


def param_hash(params: Mapping[str, float]) -> str:
    """Stable hash of a parameter set. Values are formatted, never floated into
    the blob raw, so 0.1 and 0.10 cannot produce different versions."""
    blob = json.dumps(
        {k: f"{float(v):.10g}" for k, v in sorted(params.items())},
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def engine_version(
    params: Mapping[str, float], code_version: str = CODE_VERSION
) -> str:
    """Derived, never hand-bumped: `{code_version}:{param_hash[:8]}`.

    Derivation is the point — a hand-set version can be forgotten after a
    parameter edit, which silently reinterprets every historical result as though
    it came from the new method.
    """
    return f"{code_version}:{param_hash(params)[:8]}"


def inputs_hash(
    *,
    features: Mapping[str, float | None],
    company_type: str | None,
    engine: str,
) -> str:
    """Identity of the INPUTS a result was computed from.

    Covers `company_type` and the engine version, not just the financial figures.
    Financials alone would let a company_type flip produce new scores under an
    unchanged hash, leaving the stale row alive and indistinguishable from the
    fresh one — the same silent-and-confident failure class as a missing commit.
    """
    payload = {
        "features": {
            k: (None if features.get(k) is None else f"{float(features[k]):.10g}")
            for k in FEATURES
        },
        "company_type": company_type,
        "engine": engine,
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _self_check() -> None:
    rows = {
        "AAA": {"features": dict.fromkeys(FEATURES, 1.0)},
        "BBB": {"features": dict.fromkeys(FEATURES, 2.0)},
        "CCC": {"features": dict.fromkeys(FEATURES, 3.0)},
    }
    for i in range(6):  # pad to MIN_CROSS_SECTION
        rows[f"P{i}"] = {"features": dict.fromkeys(FEATURES, 2.0)}
    zs = cross_section_z(rows)
    assert set(zs) == set(FEATURES), "every feature should z-score here"
    comp = composite_scores(zs, rows)
    assert comp["CCC"] > comp["BBB"] > comp["AAA"], comp

    # Presence renormalization: a name with 4 features sits on the same scale as
    # one with 7, rather than being pulled toward zero by the missing three.
    partial = {f: zs[f] for f in FEATURES[:4]}
    assert abs(composite_scores(partial, ["CCC"])["CCC"] - comp["CCC"]) < 1e-9

    # Below the feature floor, no composite at all.
    assert composite_scores({f: zs[f] for f in FEATURES[:3]}, ["CCC"]) == {}

    # A zero-variance cross-section must not divide by zero.
    flat = {"X": 5.0, "Y": 5.0}
    assert zscore(flat) == {"X": 0.0, "Y": 0.0}

    # Version derivation is stable and formatting-insensitive.
    assert engine_version({"a": 0.1}) == engine_version({"a": 0.10})
    assert engine_version({"a": 0.1}) != engine_version({"a": 0.2})

    # company_type is part of input identity, not decoration.
    f = dict.fromkeys(FEATURES, 1.0)
    e = engine_version({"a": 1})
    assert inputs_hash(features=f, company_type="chips", engine=e) != inputs_hash(
        features=f, company_type="software", engine=e
    )
    assert inputs_hash(features=f, company_type="chips", engine=e) == inputs_hash(
        features=f, company_type="chips", engine=e
    )
    print("scoring self-check ok")


if __name__ == "__main__":
    _self_check()
