from __future__ import annotations

from scripts.research.fomc_sep_source_probe import (
    classify_probe_state,
    probe_exit_code,
)


def test_probe_state_distinguishes_http_parse_empty_and_ok() -> None:
    assert (
        classify_probe_state(http_statuses=[503], parse_error=None, row_count=None)
        == "http_error"
    )
    assert (
        classify_probe_state(
            http_statuses=[200, 200],
            parse_error="publisher schema changed",
            row_count=None,
        )
        == "parse_error"
    )
    assert (
        classify_probe_state(http_statuses=[200], parse_error=None, row_count=0)
        == "empty"
    )
    assert (
        classify_probe_state(http_statuses=[200, 200], parse_error=None, row_count=4)
        == "ok"
    )


def test_probe_state_does_not_treat_missing_transport_evidence_as_success() -> None:
    assert (
        classify_probe_state(http_statuses=[], parse_error=None, row_count=4)
        == "http_error"
    )


def test_optional_market_shadow_does_not_control_official_source_gate() -> None:
    payload = {
        "sources": {
            "federal_reserve_fomc": {"state": "ok"},
            "federal_reserve_sep": {"state": "ok"},
            "new_york_fed_sme": {"state": "ok"},
            "frenzy_capital": {"state": "http_error"},
        }
    }

    assert probe_exit_code(payload) == 0
    assert probe_exit_code(payload, require_shadow=True) == 1

    payload["sources"]["federal_reserve_sep"]["state"] = "parse_error"
    assert probe_exit_code(payload) == 1
