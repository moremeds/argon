from uw_scan.config import UwScanConfig
from uw_scan.ingest.planner import SourceCandidate, build_call_plan


def test_call_plan_dedupes_tickers_and_respects_cap():
    config = UwScanConfig(max_requests_per_cycle=20, max_deep_surface_tickers=2)
    candidates = [
        SourceCandidate(ticker="NVDA", option_symbol="NVDA260619C00650000", source_label="UW"),
        SourceCandidate(ticker="NVDA", option_symbol="NVDA260619C00650000", source_label="TV"),
        SourceCandidate(ticker="AMD", option_symbol=None, source_label="TV"),
    ]
    plan = build_call_plan(candidates, market_date="2026-05-11", config=config)
    assert plan.total_requests <= 20
    assert plan.unique_tickers == ["AMD", "NVDA"]
    assert plan.unique_option_symbols == ["NVDA260619C00650000"]
    tracking_calls = [call for call in plan.calls if call.tier == "tracking"]
    assert tracking_calls[0].ticker == "NVDA"


def test_call_plan_marks_truncated_when_cap_exceeded():
    config = UwScanConfig(max_requests_per_cycle=5)
    candidates = [SourceCandidate(ticker=f"T{idx}", option_symbol=None, source_label="TV") for idx in range(10)]
    plan = build_call_plan(candidates, market_date="2026-05-11", config=config)
    assert plan.truncated is True
    assert plan.total_requests == 5


def test_call_plan_expands_deep_surface_by_important_expiry():
    config = UwScanConfig(max_requests_per_cycle=50, max_deep_surface_tickers=1, max_expiries_per_ticker=2)
    candidates = [SourceCandidate(ticker="NVDA", option_symbol=None, source_label="UW")]
    plan = build_call_plan(
        candidates,
        market_date="2026-05-11",
        config=config,
        important_expiries_by_ticker={"NVDA": ["2026-06-19", "2026-09-18", "2027-01-15"]},
    )
    deep_calls = [call for call in plan.calls if call.tier == "deep_surface"]
    assert len(deep_calls) == 6
    assert {call.expiry for call in deep_calls} == {"2026-06-19", "2026-09-18"}
    assert all(call.ticker == "NVDA" for call in deep_calls)
