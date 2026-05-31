"""Leniency coercion for the framework{} block (leniency/framework.py).

Confirms the coercer collapses Claude-style cosmetic drift so the strict
Pydantic contract (min_length=8 factors, defined_risk bool) parses, WITHOUT
inventing data: missing factors pad to `na`, absent defined_risk fails safe.
"""

from __future__ import annotations

from decimal import Decimal

from uw_scan.models import TradeFramework
from uw_scan.reports.trade_blast.leniency.framework import (
    CANONICAL_CONVICTION_FACTORS,
    _coerce_framework,
)


def test_candidate_net_greeks_direction_word_coerced_to_none():
    # Live regression: DeepSeek emitted net_delta/net_vega = "long" (a direction
    # word) where the contract expects Decimal | None. Non-numeric must degrade
    # to None so the candidate still validates — never a decimal_parsing crash.
    raw = {
        "candidates": [
            {
                "name": "Bull Call Spread",
                "net_delta": "long",
                "net_vega": "long",
                "defined_risk": True,
            }
        ]
    }
    out = _coerce_framework(raw, candidates={})
    cand = out["candidates"][0]
    assert cand["net_delta"] is None
    assert cand["net_vega"] is None
    assert cand["defined_risk"] is True


def test_candidate_net_greeks_numeric_preserved_as_decimal():
    raw = {
        "candidates": [
            {"name": "X", "net_delta": "0.42", "net_vega": -1.3, "defined_risk": True}
        ]
    }
    out = _coerce_framework(raw, candidates={})
    cand = out["candidates"][0]
    assert cand["net_delta"] == Decimal("0.42")
    assert cand["net_vega"] == Decimal("-1.3")


def test_candidate_net_greeks_absent_keys_untouched():
    raw = {"candidates": [{"name": "Y", "defined_risk": False}]}
    out = _coerce_framework(raw, candidates={})
    assert "net_delta" not in out["candidates"][0]
    assert "net_vega" not in out["candidates"][0]


def test_coerce_framework_conviction_string_to_int():
    raw = {"conviction": {"score": "4", "factors": [{"name": "x", "status": "yes"}]}}
    out = _coerce_framework(raw, candidates={})
    assert out["conviction"]["score"] == 4
    assert isinstance(out["conviction"]["score"], int)


def test_coerce_pads_to_eight_canonical_factors():
    raw = {"conviction": {"score": 0, "factors": []}}
    out = _coerce_framework(raw, candidates={})
    factors = out["conviction"]["factors"]
    assert len(factors) == 8
    assert [f["name"] for f in factors] == list(CANONICAL_CONVICTION_FACTORS)
    # padded factors are na, never a bluffed yes
    assert all(f["status"] == "na" for f in factors)


def test_coerce_matches_paraphrased_factor_by_norm():
    # Model emits one canonical factor with hyphen/case drift -> matched, kept yes.
    raw = {
        "conviction": {
            "score": 1,
            "factors": [
                {
                    "name": "Short Interest >10% (squeeze potential)",
                    "status": "yes",
                    "note": "SI 14%",
                }
            ],
        }
    }
    out = _coerce_framework(raw, candidates={})
    factors = {f["name"]: f for f in out["conviction"]["factors"]}
    si = factors["Short interest >10% (squeeze potential)"]
    assert si["status"] == "yes"
    assert si["note"] == "SI 14%"
    assert len(out["conviction"]["factors"]) == 8


def test_coerce_defined_risk_inferred_from_name():
    raw = {"candidates": [{"name": "bull put spread"}]}  # defined_risk omitted
    out = _coerce_framework(raw, candidates={})
    # "spread" token → inferred as defined-risk
    assert out["candidates"][0]["defined_risk"] is True


def test_coerce_defined_risk_defaults_false_for_naked_structure():
    raw = {"candidates": [{"name": "short call"}]}  # genuinely naked
    out = _coerce_framework(raw, candidates={})
    assert out["candidates"][0]["defined_risk"] is False


def test_coerce_norms_best_setup_and_candidate_names():
    raw = {
        "best_setup": {"structure": "Bull Put Spread"},
        "candidates": [{"name": "Bull Put Spread", "defined_risk": True}],
    }
    out = _coerce_framework(raw, candidates={})
    assert out["best_setup"]["structure"] == "bull_put_spread"
    assert out["candidates"][0]["name"] == "bull_put_spread"


def test_coerced_framework_roundtrips_through_pydantic():
    # A loose Claude framework (3 factors, string score, missing defined_risk on
    # a stand_aside) must parse after coercion thanks to factor padding.
    raw = {
        "header": {
            "thesis_one_liner": "thin",
            "position_type": "stand_aside",
            "spot": "100",
            "conviction_n": "0",
        },
        "three_axis": {
            "direction": {"verdict": "neutral", "prose": "p"},
            "vega": {"regime": "low_iv", "prose": "p"},
            "asymmetry": {
                "rule_on": False,
                "structure_family": "pin_vega",
                "prose": "p",
            },
        },
        "gamma": {"regime": "long", "prose": "p"},
        "catalyst": {"handling": "stand_aside", "prose": "p"},
        "conviction": {
            "score": "0",
            "factors": [{"name": "Short interest >10%", "status": "na"}],
        },
        "confluence": {"aligned": False, "signals": [], "prose": "p"},
        "pitfalls": [],
        "candidates": [],
        "best_setup": {
            "structure": "stand_aside",
            "legs": [],
            "rationale": "r",
            "invalidation": "inv",
        },
        "what_changes": [],
        "bottom_line": "stand aside",
    }
    out = _coerce_framework(raw, candidates={})
    fw = TradeFramework.model_validate(out)  # must not raise (8 factors padded)
    assert fw.header.conviction_n == 0
    assert len(fw.conviction.factors) == 8
