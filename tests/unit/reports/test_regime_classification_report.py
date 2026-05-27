from __future__ import annotations

import pandas as pd

from uw_scan.reports.regime_classification_report import render_report


def _basic_args(**overrides):
    args = dict(
        run_id=42,
        label_version=1,
        eval_start="2007-01-03",
        eval_end="2026-05-26",
        n_days=4545,
        verdict={
            "overall": "PASS",
            "macro_f1": 0.6,
            "eligible_core_classes": [],
            "inconclusive_core_classes": [],
            "rare_inconclusive": [],
            "reason": None,
        },
        failure_mode={
            "primary": "adequate_v1",
            "secondary_modes": [],
            "not_evaluable": [],
        },
        per_class={},
        cm_overall=pd.DataFrame(),
        cm_by_period={},
        weighted_f1=0.65,
        kappa=0.50,
        named_crisis_overlay=[],
        vcg_source={"run_id": 6, "composite_version": "1", "credit_proxy": "HYG"},
        data_vintages=None,
    )
    args.update(overrides)
    return args


def test_report_contains_construct_validity_paragraph():
    report = render_report(**_basic_args())
    expected = (
        "This classification score measures descriptive agreement with an "
        "externally defined market-state taxonomy. It is not an alpha test"
    )
    assert expected in report


def test_report_renders_data_vintages_section_when_provided():
    """v0.3 / CL-6: post-hoc components disclosed via Data vintages."""
    report = render_report(
        **_basic_args(
            data_vintages=[
                {
                    "component": "NFCI",
                    "vintage": "as_of latest",
                    "lag": "3-5 days release lag",
                    "interpretation": "post-hoc; non-tradable signal",
                },
            ]
        )
    )
    assert "Data vintages" in report
    assert "NFCI" in report
    assert "non-tradable signal" in report


def test_report_deterministic_same_inputs_same_bytes():
    args = _basic_args()
    assert render_report(**args) == render_report(**args)


def test_report_no_wall_clock_timestamp_in_body():
    report = render_report(**_basic_args())
    assert "Generated at" not in report
    assert "Run timestamp" not in report
