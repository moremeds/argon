from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from scripts.research.fomc_sep_source_probe import (
    aggregate_release_reports,
    classify_probe_state,
    probe_exit_code,
)
from uw_scan.sources.fomc_release_contracts import FomcReleaseCandidate


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


# Real 2020 FOMC statement dates; the candidate contract validates the release
# key, its embedded date, and both artifact URLs against the publisher's own
# naming, so an invented key cannot be constructed here.
_MARCH_2020 = date(2020, 3, 15)
_APRIL_2020 = date(2020, 4, 29)
_JUNE_2020 = date(2020, 6, 10)


def _stem(event_date: date) -> str:
    return f"monetary{event_date:%Y%m%d}a"


def _candidate(
    event_date: date,
    *,
    event_class: str = "scheduled_meeting",
) -> FomcReleaseCandidate:
    stem = _stem(event_date)
    return FomcReleaseCandidate(
        release_key=f"fomc-statement:{stem}",
        release_type="statement",
        event_date=event_date,
        event_class=event_class,
        discovery_url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
        html_url=f"https://www.federalreserve.gov/newsevents/pressreleases/{stem}.htm",
        pdf_url=f"https://www.federalreserve.gov/newsevents/pressreleases/{stem}1.pdf",
    )


def _artifact(event_date: date, *, media_type: str = "text/html") -> SimpleNamespace:
    stem = _stem(event_date)
    return SimpleNamespace(
        source_url=f"https://www.federalreserve.gov/newsevents/pressreleases/{stem}.htm",
        content_hash=f"hash-{stem}-{media_type}",
        content_length=1024,
        media_type=media_type,
        parser_version="fomc_statement.v1",
        published_at=None,
        available_at=datetime(2026, 8, 17, tzinfo=UTC),
        retrieved_at=datetime(2026, 8, 17, tzinfo=UTC),
    )


def _outcome(
    event_date: date,
    *,
    bundle: object | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    event_class: str = "scheduled_meeting",
) -> SimpleNamespace:
    return SimpleNamespace(
        candidate=_candidate(event_date, event_class=event_class),
        artifacts=(
            _artifact(event_date),
            _artifact(event_date, media_type="application/pdf"),
        ),
        bundle=bundle,
        error_type=error_type,
        error_message=error_message,
    )


def test_every_discovered_release_is_reported_not_only_the_newest() -> None:
    """One parse failure among many must not be invisible.

    Selecting max(meeting_date) makes the failure rate structurally zero: the
    probe reads exactly one release and calls the source healthy. The parser sat
    at 1-of-25 while this said "ok" for precisely that reason.
    """
    outcomes = [
        _outcome(_MARCH_2020, bundle=object(), event_class="unscheduled_meeting"),
        _outcome(
            _APRIL_2020,
            error_type="uw_scan.normalize.NormalizationError",
            error_message="unreadable target range",
        ),
        _outcome(_JUNE_2020, bundle=object()),
    ]

    report = aggregate_release_reports(
        outcomes, parse=lambda bundle: {"row_count": 1}
    )

    assert report["releases_discovered"] == 3
    assert report["releases_succeeded"] == 2
    assert report["releases_failed"] == 1
    assert [item["release_key"] for item in report["releases"]] == [
        "fomc-statement:monetary20200315a",
        "fomc-statement:monetary20200429a",
        "fomc-statement:monetary20200610a",
    ]
    assert [item["state"] for item in report["releases"]] == [
        "ok",
        "parse_error",
        "ok",
    ]
    assert report["state"] == "parse_error"


def test_a_failed_release_records_its_error_and_the_bytes_it_did_obtain() -> None:
    """Evidence that landed stays reported even when the reading failed."""
    outcomes = [
        _outcome(
            _MARCH_2020,
            error_type="uw_scan.normalize.NormalizationError",
            error_message="unreadable target range",
            event_class="unscheduled_meeting",
        )
    ]

    report = aggregate_release_reports(
        outcomes, parse=lambda bundle: {"row_count": 1}
    )

    failed = report["releases"][0]
    assert failed["state"] == "parse_error"
    assert failed["error_type"].endswith("NormalizationError")
    assert failed["error_message"] == "unreadable target range"
    assert failed["artifact_hashes"] == {
        "text/html": "hash-monetary20200315a-text/html",
        "application/pdf": "hash-monetary20200315a-application/pdf",
    }
    assert failed["event_date"] == _MARCH_2020
    assert failed["event_class"] == "unscheduled_meeting"


def test_a_release_that_parses_to_nothing_is_not_ok() -> None:
    """An empty normalized release is a silent failure, not a success."""
    outcomes = [_outcome(_MARCH_2020, bundle=object())]

    report = aggregate_release_reports(
        outcomes, parse=lambda bundle: {"row_count": 0}
    )

    assert report["releases"][0]["state"] == "empty"
    assert report["state"] == "empty"
    assert report["releases_succeeded"] == 0


def test_a_parser_raising_inside_the_probe_degrades_only_its_release() -> None:
    def parse(bundle: object) -> dict[str, object]:
        if bundle is first:
            raise ValueError("publisher schema changed")
        return {"row_count": 1}

    first = object()
    outcomes = [
        _outcome(_MARCH_2020, bundle=first),
        _outcome(_JUNE_2020, bundle=object()),
    ]

    report = aggregate_release_reports(outcomes, parse=parse)

    assert [item["state"] for item in report["releases"]] == ["parse_error", "ok"]
    assert report["releases"][0]["error_type"] == "builtins.ValueError"
    assert report["releases_succeeded"] == 1


def test_all_release_coverage_drives_the_official_exit_code() -> None:
    payload = {
        "sources": {
            "federal_reserve_fomc": {"state": "parse_error"},
            "federal_reserve_sep": {"state": "ok"},
            "new_york_fed_sme": {"state": "ok"},
            "frenzy_capital": {"state": "ok"},
        }
    }

    assert probe_exit_code(payload) == 1
