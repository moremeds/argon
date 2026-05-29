from uw_scan.models import TradeFramework


def test_trade_framework_minimal_stand_aside():
    fw = TradeFramework.model_validate(
        {
            "header": {
                "thesis_one_liner": "no edge",
                "position_type": "stand_aside",
                "spot": "100.00",
                "conviction_n": 0,
            },
            "three_axis": {
                "direction": {"verdict": "neutral", "prose": "mixed"},
                "vega": {
                    "regime": "low_iv",
                    "ivr": "20",
                    "term_slope": "flat",
                    "prose": "cheap",
                },
                "asymmetry": {
                    "rule_on": False,
                    "structure_family": "pin_vega",
                    "prose": "n/a",
                },
            },
            "gamma": {
                "regime": "long",
                "flip_strike": None,
                "call_wall": None,
                "put_wall": None,
                "prose": "stable",
            },
            "catalyst": {
                "next_er_date": None,
                "dte_to_er": None,
                "implied_move": None,
                "handling": "stand_aside",
                "prose": "no event",
            },
            # exactly 8 factors required (min_length=8); all na here -> score 0
            "conviction": {
                "score": 0,
                "prose": "insufficient",
                "factors": [{"name": f"f{i}", "status": "na"} for i in range(8)],
            },
            "confluence": {"aligned": False, "signals": [], "prose": "none"},
            "pitfalls": [],
            "candidates": [],
            "best_setup": {
                "structure": "stand_aside",
                "legs": [],
                "cost": None,
                "max_risk": None,
                "rationale": "no data",
                "why_not_alternatives": "",
                "invalidation": "re-engage when tape resolves",
            },
            "what_changes": [],
            "bottom_line": "stand aside",
        }
    )
    assert fw.header.position_type == "stand_aside"
    assert fw.best_setup.structure == "stand_aside"


def test_trade_framework_rejects_unknown_field():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        TradeFramework.model_validate({"header": {}, "bogus": 1})
