"""Every advisory-lock key, frozen (I-53/I-54).

Two jobs that pick the same key silently skip each other: the second one logs
"lock held; skipping" and does nothing. So a key is an identity, and moving one is
a behaviour change. This golden was captured from the constants on main before the
lock registry existed; the registry must reproduce it exactly, except where a
deliberate re-key changes it in its own commit.
"""

from __future__ import annotations

GOLDEN: dict[str, int] = {
    "flow_data_refresh[worker 0]": 91501,
    "flow_data_refresh[worker 1]": 91502,
    "intraday_refresh": 91502,
    "greek_daily_refresh": 91503,
    "intraday_backfill": 91504,
    "pipeline_benchmark": 91601,
    "data_gap_healer": 92010,
    "cockpit_snapshot": 92201,
    "discovery_scan": 92401,
    "uw_alpha_gex_levels": 10801,
    "uw_alpha_volatility": 10802,
    "uw_alpha_short_pressure": 10803,
    "uw_alpha_intraday_flow": 10804,
    "uw_alpha_dark_lit": 10805,
    "mcp_event": 727_000_154,
}


def current_keys() -> dict[str, int]:
    from uw_scan.storage.mcp_events import MCP_EVENT_LOCK
    from uw_scan.worker.jobs import uw_alpha_capture as alpha
    from uw_scan.worker.jobs.cockpit_daily_snapshot import COCKPIT_SNAPSHOT_LOCK
    from uw_scan.worker.jobs.data_gap_healer import _LOCK_KEY as GAP
    from uw_scan.worker.jobs.discovery_scan import DISCOVERY_SCAN_LOCK
    from uw_scan.worker.jobs.flow_data_refresh import FLOW_REFRESH_LOCK
    from uw_scan.worker.jobs.greek_exposure_daily_refresh import (
        GREEK_DAILY_REFRESH_LOCK,
    )
    from uw_scan.worker.jobs.option_intraday_jobs import (
        INTRADAY_BACKFILL_LOCK,
        INTRADAY_REFRESH_LOCK,
    )
    from uw_scan.worker.jobs.pipeline_benchmark import PIPELINE_BENCHMARK_LOCK_KEY

    return {
        # scheduler.py passes lock_key=91501 + settings.worker_index
        "flow_data_refresh[worker 0]": FLOW_REFRESH_LOCK + 0,
        "flow_data_refresh[worker 1]": FLOW_REFRESH_LOCK + 1,
        "intraday_refresh": INTRADAY_REFRESH_LOCK,
        "greek_daily_refresh": GREEK_DAILY_REFRESH_LOCK,
        "intraday_backfill": INTRADAY_BACKFILL_LOCK,
        "pipeline_benchmark": PIPELINE_BENCHMARK_LOCK_KEY,
        "data_gap_healer": GAP,
        "cockpit_snapshot": COCKPIT_SNAPSHOT_LOCK,
        "discovery_scan": DISCOVERY_SCAN_LOCK,
        "uw_alpha_gex_levels": alpha.GEX_LEVELS_CAPTURE_LOCK,
        "uw_alpha_volatility": alpha.VOLATILITY_CAPTURE_LOCK,
        "uw_alpha_short_pressure": alpha.SHORT_PRESSURE_CAPTURE_LOCK,
        "uw_alpha_intraday_flow": alpha.INTRADAY_FLOW_CAPTURE_LOCK,
        "uw_alpha_dark_lit": alpha.DARK_LIT_CAPTURE_LOCK,
        "mcp_event": MCP_EVENT_LOCK,
    }


def test_lock_keys_match_golden():
    assert current_keys() == GOLDEN
