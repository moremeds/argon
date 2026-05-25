"""Self-contained snapshot test for the VCG markdown renderer."""

from __future__ import annotations

from datetime import date

from uw_scan.reports.regime_vcg_backtest_report import render_vcg_backtest_markdown


def _make_daily() -> list[dict]:
    base = [
        ("NORMAL", -0.50, -0.50, -0.02, -0.04, True),
        ("SUPPRESSED", 0.80, 0.80, 0.03, -0.05, False),
        ("EDR", -1.20, -1.20, -0.08, -0.02, True),
        ("RISK_OFF", -2.10, -2.10, -0.09, -0.06, True),
        ("PANIC", -3.40, -0.00, -0.05, -0.08, True),
    ]
    return [
        {
            "trade_date": date(2024, 1, 2 + i),
            "score": row[1],
            "level": row[0],
            "payload": {
                "vcg": row[1],
                "vcg_adj": row[2],
                "beta1": row[3],
                "beta2": row[4],
                "sign_ok": row[5],
                "interpretation": row[0],
            },
        }
        for i, row in enumerate(base)
    ]


def test_render_vcg_produces_expected_markdown_substrings() -> None:
    daily = _make_daily()
    run = {
        "indicator": "vcg",
        "composite_version": "1",
        "start_date": date(2007, 1, 3),
        "end_date": daily[-1]["trade_date"],
        "window_days": 21,
        "n_days": len(daily),
        "summary": {
            "oos": None,
            "extras": {
                "credit_proxy": "HYG",
                "interpretation_distribution": {
                    "NORMAL": 1,
                    "SUPPRESSED": 1,
                    "EDR": 1,
                    "RISK_OFF": 1,
                    "PANIC": 1,
                },
                "ro_count": 1,
                "edr_count": 1,
                "bounce_count": 0,
            },
        },
    }
    actual = render_vcg_backtest_markdown(run, daily)
    assert "VCG Backtest" in actual
    assert "**Credit proxy:** HYG" in actual
    assert "**Date range:** 2024-01-02 → 2024-01-06" in actual
    for level in ("NORMAL", "SUPPRESSED", "EDR", "RISK_OFF", "PANIC"):
        assert f"| {level} |" in actual, f"missing {level} row in distribution table"


def test_render_vcg_empty_daily_returns_placeholder() -> None:
    run = {
        "indicator": "vcg",
        "composite_version": "1",
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 1, 1),
        "window_days": 21,
        "n_days": 0,
        "summary": {"oos": None, "extras": {}},
    }
    assert (
        render_vcg_backtest_markdown(run, [])
        == "# VCG Backtest\n\n_No daily rows available._\n"
    )
