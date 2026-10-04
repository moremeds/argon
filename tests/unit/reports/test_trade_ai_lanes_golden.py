"""Golden of both Trade Insights AI lanes (I-80 proof).

Written BEFORE trade_blast and trade_insights_ai were made to share one
implementation. For the insights lane (v5.3 card) and the blast lane
(framework view) it records, on the same real-shaped TSLA fixture used by
tests/unit/test_trade_insights_ai.py: the prompt version, the analysis
input, its hash, the prompt payload, the full prompt text, the output JSON
schema, and the validated outcome + Markdown for the validator modes the
worker uses (insights: strict and lenient; blast: lenient + soft).

The only wall-clock values in either lane are the blast framework sections'
``age_days`` / ``stale`` (already excluded from the input hash). They are
pinned after the build so the prompt bytes are stable; their computation is
covered by test_analysis_input_framework_sections.py.

Regenerate (only for an intentional prompt/output change):
``TRADE_AI_GOLDEN_WRITE=1 uv run pytest tests/unit/reports/test_trade_ai_lanes_golden.py``
"""

from __future__ import annotations

import copy
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from tests.unit.reports.validator_rules.test_framework_rules import build_framework
from tests.unit.test_trade_insights_ai import _sample_outcome, _source_payloads
from uw_scan.reports import trade_blast, trade_insights_ai

GOLDEN = Path(__file__).resolve().parent / "golden" / "trade_ai_lanes.json"
PRODUCED_AT = datetime(2026, 3, 24, 20, 18, 42, tzinfo=timezone.utc)
LANES = {"insights": trade_insights_ai, "blast": trade_blast}

# Framework inputs for the blast lane (fixed dates; values shaped like the
# positioning/fundamentals/macro/flow rows the router reads).
FRAMEWORK_KWARGS = {
    "positioning_payload": {
        "snapshot_date": date(2026, 3, 23),
        "si_pct_float": Decimal("0.031"),
        "si_days_to_cover": Decimal("1.2"),
        "analyst_buy": 24,
        "analyst_hold": 15,
        "analyst_sell": 9,
        "analyst_target_avg": Decimal("312.50"),
        "inst_holder_count": 3410,
        "insider_net_flow": Decimal("-1250000"),
        "earn_reactions_positive": 5,
        "earn_reactions_total": 8,
        "next_er_date": date(2026, 4, 22),
    },
    "fundamentals_payload": {
        "period_end": date(2025, 12, 31),
        "fiscal_period": "Q4 2025",
        "revenue": Decimal("25707000000"),
        "gross_margin": Decimal("0.162"),
        "op_margin": Decimal("0.061"),
        "fcf": Decimal("2034000000"),
    },
    "macro_payload": {"as_of": date(2026, 3, 24), "vix": Decimal("18.5")},
    "flow_series_payload": {"net_call_premium_3d": Decimal("1000"), "persistence": 3},
    "ohlcv_rows": [
        {
            "date": date(2026, 3, d),
            "open": 370 + d,
            "high": 375 + d,
            "low": 365 + d,
            "close": 372 + d,
            "volume": 90_000_000,
        }
        for d in range(16, 25)
        if date(2026, 3, d).weekday() < 5
    ],
}


def _jsonable(value):
    return json.loads(json.dumps(value, sort_keys=True, default=str))


def _analysis_input(lane: str) -> dict:
    payloads = _source_payloads()
    extra = FRAMEWORK_KWARGS if lane == "blast" else {}
    out = LANES[lane].build_trade_insights_ai_analysis_input(
        ticker="TSLA",
        run_id=123,
        trade_insights_input_hash="sha256-trade-insights",
        trade_insights_payload=payloads["trade_insights"],
        stock_report_payload=payloads["stock_report"],
        stock_history_payload=payloads["stock_history"],
        volatility_series_payload=payloads["volatility"],
        **extra,
    )
    for section in ("positioning", "fundamentals", "macro"):
        if isinstance(out.get(section), dict) and "age_days" in out[section]:
            out[section]["age_days"] = 0  # wall-clock; see module docstring
            out[section]["stale"] = False
    return out


def _validated(module, outcome, payload, **mode) -> dict:
    try:
        parsed = module.validate_trade_insights_ai_outcome(
            copy.deepcopy(outcome), payload, produced_at=PRODUCED_AT, **mode
        )
    except ValueError as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "outcome": parsed.model_dump(mode="json"),
        "markdown": module.render_trade_insights_ai_markdown(parsed),
    }


def _lane_record(lane: str) -> dict:
    module = LANES[lane]
    analysis_input = _analysis_input(lane)
    prompt_payload = module.build_trade_insights_ai_prompt_payload(
        analysis_input, produced_at=PRODUCED_AT
    )
    outcome = _sample_outcome()
    outcome["snapshot"]["analysis_input_hash"] = prompt_payload["analysis_input_hash"]
    partial = {
        "schema_version": "WRONG_VERSION",
        "ticker": "WRONG",
        "headline": {"title": "TSLA — bullish swing setup", "entry_state": "ACTIVE"},
        "missing_data": ["headline.stance not produced by provider"],
    }
    record = {
        "prompt_version": module.PROMPT_VERSION,
        "analysis_input": _jsonable(analysis_input),
        "analysis_input_hash": module.hash_trade_insights_ai_analysis_input(
            analysis_input
        ),
        "prompt_payload": _jsonable(prompt_payload),
        "prompt": module.build_trade_insights_ai_prompt(prompt_payload),
        "output_schema": _jsonable(module.trade_insights_ai_output_schema()),
    }
    if lane == "insights":
        record["validate_strict"] = _validated(module, outcome, prompt_payload)
        record["validate_lenient"] = _validated(
            module, outcome, prompt_payload, lenient=True
        )
        record["validate_lenient_partial"] = _validated(
            module, partial, prompt_payload, lenient=True
        )
    else:
        framed = {**outcome, "framework": build_framework()}
        # ACTIVE with an unfired entry trigger: soft mode auto-corrects it.
        unfired = copy.deepcopy(outcome)
        unfired["headline"]["entry_state"] = "ACTIVE"
        unfired["thesis_trigger"] = {
            "level": "382.50",
            "meaning": "breakout_continuation_confirmed",
            "fired": True,
            "evidence_close": "385.00",
            "evidence_date": "2026-03-24",
            "source_path": "tabs.market_structure.stock_history.rows[-1].spot",
        }
        unfired["entry_trigger"] = {**unfired["thesis_trigger"], "fired": False}
        for name, case in (
            ("plain", outcome),
            ("framework", framed),
            ("partial", partial),
            ("active_unfired", unfired),
        ):
            record[f"validate_soft_{name}"] = _validated(
                module, case, prompt_payload, lenient=True, soft=True
            )
    return _jsonable(record)


def _golden() -> dict:
    return json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}


@pytest.mark.parametrize("lane", list(LANES))
def test_trade_ai_lane_matches_golden(lane):
    got = _lane_record(lane)
    if os.environ.get("TRADE_AI_GOLDEN_WRITE") == "1":
        golden = _golden()
        golden[lane] = got
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(golden, sort_keys=True, indent=1) + "\n")
        pytest.skip("golden written")
    expected = _golden()[lane]
    assert got.keys() == expected.keys()
    for key in expected:
        assert got[key] == expected[key], (
            f"trade-ai {lane} lane changed: {key}; "
            "diff against tests/unit/reports/golden/trade_ai_lanes.json"
        )
