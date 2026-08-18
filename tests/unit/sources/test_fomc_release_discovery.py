from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from uw_scan.normalize import NormalizationError
from uw_scan.sources.fed_sep import FedSepProvider
from uw_scan.sources.fomc_release_contracts import (
    FomcDiscoverySlotOutcome,
    FomcReleaseCandidate,
)
from uw_scan.sources.fomc_release_discovery import (
    _complete_historical_statement,
    _validate_historical_sep,
    discover_official_release_result,
)
from uw_scan.sources.fomc_release_dom import inventory_current_release_page
from uw_scan.sources.fomc_statement import FomcStatementProvider


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
BASE_URL = "https://www.federalreserve.gov"
CALENDAR_URL = f"{BASE_URL}/monetarypolicy/fomccalendars.htm"


def _response(
    url: str,
    content: bytes = b"",
    *,
    status: int = 200,
    media_type: str = "text/html",
) -> httpx.Response:
    return httpx.Response(
        status,
        content=content,
        headers={"content-type": media_type},
        request=httpx.Request("GET", url),
    )


def _statement_row(raw_date: str, *, field: bytes) -> bytes:
    month = date.fromisoformat(
        f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
    ).strftime("%B")
    return b"".join(
        (
            b'<div class="row fomc-meeting">',
            f'<div class="fomc-meeting__month"><strong>{month}</strong></div>'.encode(),
            f'<div class="fomc-meeting__date">{int(raw_date[6:])}</div>'.encode(),
            field,
            b"</div>",
        )
    )


def _calendar(year: int, *rows: bytes) -> bytes:
    return b"".join(
        (
            f'<div class="panel panel-default"><h4>{year} FOMC Meetings</h4>'.encode(),
            *rows,
            b"</div>",
        )
    )


def _valid_statement_field(raw_date: str) -> bytes:
    return (
        "<div><strong>Statement:</strong>"
        f'<a href="/monetarypolicy/files/monetary{raw_date}a1.pdf">PDF</a>'
        f'<a href="/newsevents/pressreleases/monetary{raw_date}a.htm">HTML</a>'
        "</div>"
    ).encode()


def test_slot_outcome_is_bounded_and_rejects_inconsistent_status() -> None:
    with pytest.raises(ValueError, match="accepted slot"):
        FomcDiscoverySlotOutcome(
            slot_id="statement:2025-01-29",
            year=2025,
            release_type="statement",
            identity=None,
            status="accepted",
        )
    with pytest.raises(ValueError, match="bounded"):
        FomcDiscoverySlotOutcome(
            slot_id="statement:2025-01-29",
            year=2025,
            release_type="statement",
            identity="fomc-statement:monetary20250129a",
            status="rejected",
            error_type="ReleaseDiscoveryError",
            error_message="x" * 501,
        )


def test_current_statement_inventory_rejects_missing_entire_field() -> None:
    current = _calendar(
        2025,
        _statement_row("20250129", field=_valid_statement_field("20250129")),
        _statement_row("20250319", field=b"<div>Press Conference</div>"),
    )

    def fake_get(url: str) -> httpx.Response:
        if url == CALENDAR_URL:
            return _response(url, current)
        return _response(url, status=404)

    result = discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="statement",
        as_of_date=date(2025, 12, 31),
    )

    current_page = result.page_outcomes[0]
    assert (
        current_page.slots_seen,
        current_page.slots_accepted,
        current_page.slots_rejected,
    ) == (2, 1, 1)
    assert current_page.slot_rejections[0].identity == (
        "fomc-statement:monetary20250319a"
    )
    assert "missing Statement field" in (
        current_page.slot_rejections[0].error_message or ""
    )
    assert result.coverage_complete is False
    assert result.missing_years == (2025,)


def test_current_inventory_rejects_unparseable_elapsed_row_instead_of_skipping() -> (
    None
):
    current = b"""
    <div class="panel panel-default"><h4>2025 FOMC Meetings</h4>
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month"><strong>Smarch</strong></div>
        <div class="fomc-meeting__date">unknown</div>
      </div>
    </div>
    """

    inventory = inventory_current_release_page(
        current,
        discovery_url=CALENDAR_URL,
        years=(2025,),
        release_type="statement",
        as_of_date=date(2026, 1, 2),
    )

    assert len(inventory.slots) == 1
    assert inventory.slots[0].status == "rejected"
    assert inventory.slots[0].identity is None
    assert "meeting date" in (inventory.slots[0].error_message or "")


def test_current_inventory_rejects_artifact_date_incoherent_with_meeting_row() -> None:
    current = _calendar(
        2025,
        _statement_row("20250319", field=_valid_statement_field("20250129")),
    )

    inventory = inventory_current_release_page(
        current,
        discovery_url=CALENDAR_URL,
        years=(2025,),
        release_type="statement",
        as_of_date=date(2025, 12, 31),
    )

    assert inventory.candidates == ()
    assert len(inventory.slots) == 1
    assert inventory.slots[0].status == "rejected"
    assert inventory.slots[0].identity == "fomc-statement:monetary20250319a"
    assert "meeting row date" in (inventory.slots[0].error_message or "")


def test_frozen_current_inventory_accounts_for_cross_month_statement_rows() -> None:
    inventory = inventory_current_release_page(
        (FIXTURES / "fomc_calendar_current.html").read_bytes(),
        discovery_url=CALENDAR_URL,
        years=tuple(range(2021, 2027)),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )

    assert len(inventory.slots) == 45
    assert sum(slot.status == "accepted" for slot in inventory.slots) == 45
    assert not [slot for slot in inventory.slots if slot.status == "rejected"]
    keys = {candidate.release_key for candidate in inventory.candidates}
    assert "fomc-statement:monetary20230201a" in keys
    assert "fomc-statement:monetary20230503a" in keys
    assert "fomc-statement:monetary20240501a" in keys


def test_historical_accepted_identity_reconciles_current_rejected_slot() -> None:
    current = _calendar(
        2025,
        _statement_row("20250319", field=b"<div>Press Conference</div>"),
    )
    history = b"""
    <div class="panel panel-default panel-padded">
      <h5>March 18-19 Meeting - 2025</h5>
      <a href="/newsevents/pressreleases/monetary20250319a.htm">Statement</a>
    </div>
    """

    def fake_get(url: str) -> httpx.Response:
        if url == CALENDAR_URL:
            return _response(url, current)
        if url.endswith("fomchistorical2025.htm"):
            return _response(url, history)
        if url.endswith("monetary20250319a.htm"):
            return _response(
                url,
                b'<a href="/monetarypolicy/files/monetary20250319a1.pdf">PDF</a>',
            )
        return _response(url, b"%PDF exact", media_type="application/pdf")

    result = discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="statement",
        as_of_date=date(2026, 1, 2),
    )

    assert result.coverage_complete is True
    assert result.missing_years == ()
    assert [item.release_key for item in result.candidates] == [
        "fomc-statement:monetary20250319a"
    ]
    assert result.page_outcomes[0].slots_rejected == 1
    assert result.page_outcomes[1].slots_accepted == 1


def test_current_sep_inventory_rejects_off_host_starred_slot() -> None:
    valid = b"""
    <div><strong>Projection Materials</strong>
      <a href="/monetarypolicy/files/fomcprojtabl20250319.pdf">PDF</a>
      <a href="/monetarypolicy/fomcprojtabl20250319.htm">HTML</a>
    </div>
    """
    off_host = b"""
    <div><strong>Projection Materials</strong>
      <a href="https://evil.example/fomcprojtabl20250618.pdf">PDF</a>
      <a href="https://evil.example/fomcprojtabl20250618.htm">HTML</a>
    </div>
    """
    march = _statement_row("20250319", field=valid).replace(b">19<", b">18-19*<")
    june = _statement_row("20250618", field=off_host).replace(b">18<", b">17-18*<")
    current = _calendar(2025, march, june)

    def fake_get(url: str) -> httpx.Response:
        if url == CALENDAR_URL:
            return _response(url, current)
        return _response(url, status=404)

    result = discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="sep",
        as_of_date=date(2025, 12, 31),
    )

    assert result.page_outcomes[0].slots_seen == 2
    assert result.page_outcomes[0].slots_rejected == 1
    assert result.coverage_complete is False


@pytest.mark.parametrize(("release_type", "expected"), [("statement", 10), ("sep", 3)])
def test_frozen_2020_history_accounts_every_source_marker(
    release_type: str, expected: int
) -> None:
    calendar = (FIXTURES / "fomc_calendar_current.html").read_bytes()
    history = (FIXTURES / "fomc_historical_2020.html").read_bytes()

    def fake_get(url: str) -> httpx.Response:
        if url == CALENDAR_URL:
            return _response(url, calendar)
        if url.endswith("fomchistorical2020.htm"):
            return _response(url, history)
        if url.endswith(".pdf"):
            return _response(url, b"%PDF exact", media_type="application/pdf")
        if "monetary2020" in url:
            stem = url.rsplit("/", 1)[-1].removesuffix(".htm")
            return _response(
                url,
                f'<a href="/monetarypolicy/files/{stem}1.pdf">PDF</a>'.encode(),
            )
        return _response(url, b"<html>SEP</html>")

    result = discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2020,),
        release_type=release_type,  # type: ignore[arg-type]
        as_of_date=date(2026, 8, 13),
    )

    history_page = result.page_outcomes[1]
    assert history_page.slots_seen == expected
    assert history_page.slots_accepted == expected
    assert history_page.slots_rejected == 0


def test_clock_injection_attempts_2026_archive_only_after_2026() -> None:
    requested: list[str] = []

    def fake_get(url: str) -> httpx.Response:
        requested.append(url)
        if url == CALENDAR_URL:
            return _response(url, b"<html></html>")
        return _response(url, status=404)

    discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2026,),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )
    assert not any("fomchistorical2026" in url for url in requested)

    requested.clear()
    discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2026,),
        release_type="statement",
        as_of_date=date(2027, 1, 2),
    )
    assert any("fomchistorical2026" in url for url in requested)


def test_statement_provider_uses_retrieved_at_as_discovery_clock() -> None:
    with patch.object(
        FomcStatementProvider, "discover_result", autospec=True
    ) as discover:
        discover.return_value.coverage_complete = False
        discover.return_value.missing_years = (2026,)
        with FomcStatementProvider() as provider:
            with pytest.raises(NormalizationError):
                provider.fetch_outcomes(
                    years=(2026,),
                    retrieved_at=datetime(2027, 1, 2, tzinfo=UTC),
                )

    assert discover.call_args.kwargs["as_of_date"] == date(2027, 1, 2)


def test_statement_transient_validation_keeps_url_for_provider_retry() -> None:
    current = b"<html></html>"
    history = b"""
    <div class="panel panel-default panel-padded">
      <h5>March 3 (unscheduled) Meeting - 2020</h5>
      <a href="/newsevents/pressreleases/monetary20200303a.htm">Statement</a>
    </div>
    """
    statement = (FIXTURES / "fomc_statement_2020_03_03.html").read_bytes()
    pdf_url = f"{BASE_URL}/monetarypolicy/files/monetary20200303a1.pdf"
    pdf_calls = 0

    def fake_get(url: str) -> httpx.Response:
        nonlocal pdf_calls
        if url == CALENDAR_URL:
            return _response(url, current)
        if url.endswith("fomchistorical2020.htm"):
            return _response(url, history)
        if url.endswith("monetary20200303a.htm"):
            return _response(url, statement)
        if url == pdf_url:
            pdf_calls += 1
            if pdf_calls == 1:
                raise httpx.ReadTimeout("validation timed out")
            return _response(url, b"%PDF exact", media_type="application/pdf")
        raise AssertionError(url)

    discovery = discover_official_release_result(
        get=fake_get,
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2020,),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )
    assert discovery.coverage_complete is True
    assert discovery.candidates[0].pdf_url == pdf_url
    assert "ReadTimeout" in (discovery.candidates[0].discovery_error or "")

    def provider_get(_provider: FomcStatementProvider, url: str) -> httpx.Response:
        return fake_get(url)

    with (
        patch.object(
            FomcStatementProvider,
            "discover_result",
            autospec=True,
            return_value=discovery,
        ),
        patch.object(
            FomcStatementProvider, "_get", autospec=True, side_effect=provider_get
        ),
    ):
        with FomcStatementProvider() as provider:
            outcomes = provider.fetch_outcomes(
                years=(2020,), retrieved_at=datetime(2026, 8, 13, tzinfo=UTC)
            )

    assert pdf_calls == 2
    assert len(outcomes[0].artifacts) == 2
    assert outcomes[0].bundle is not None
    assert outcomes[0].error_type == "ReleaseDiscoveryError"


def test_sep_transient_validation_retains_bounded_derived_urls() -> None:
    candidate = FomcReleaseCandidate(
        release_key="fed-sep:fomcprojtabl20200610",
        release_type="sep",
        event_date=date(2020, 6, 10),
        event_class=None,
        discovery_url=f"{BASE_URL}/monetarypolicy/fomchistorical2020.htm",
        html_url=f"{BASE_URL}/monetarypolicy/fomcprojtabl20200610.htm",
        pdf_url=f"{BASE_URL}/monetarypolicy/files/fomcprojtabl20200610.pdf",
    )

    def fake_get(url: str) -> httpx.Response:
        if url == candidate.html_url:
            raise httpx.ReadTimeout("validation timed out")
        return _response(url, b"%PDF exact", media_type="application/pdf")

    validated = _validate_historical_sep(candidate, get=fake_get)

    assert validated.html_url == candidate.html_url
    assert validated.pdf_url == candidate.pdf_url
    assert "ReadTimeout" in (validated.discovery_error or "")


def test_sep_not_found_validation_clears_only_absent_url() -> None:
    candidate = FomcReleaseCandidate(
        release_key="fed-sep:fomcprojtabl20200610",
        release_type="sep",
        event_date=date(2020, 6, 10),
        event_class=None,
        discovery_url=f"{BASE_URL}/monetarypolicy/fomchistorical2020.htm",
        html_url=f"{BASE_URL}/monetarypolicy/fomcprojtabl20200610.htm",
        pdf_url=f"{BASE_URL}/monetarypolicy/files/fomcprojtabl20200610.pdf",
    )

    def fake_get(url: str) -> httpx.Response:
        if url == candidate.html_url:
            return _response(url, status=404)
        return _response(url, b"%PDF exact", media_type="application/pdf")

    validated = _validate_historical_sep(candidate, get=fake_get)

    assert validated.html_url is None
    assert validated.pdf_url == candidate.pdf_url
    assert "404" in (validated.discovery_error or "")


def test_statement_not_found_validation_does_not_retain_absent_pdf() -> None:
    candidate = FomcReleaseCandidate(
        release_key="fomc-statement:monetary20200303a",
        release_type="statement",
        event_date=date(2020, 3, 3),
        event_class="unscheduled_meeting",
        discovery_url=f"{BASE_URL}/monetarypolicy/fomchistorical2020.htm",
        html_url=f"{BASE_URL}/newsevents/pressreleases/monetary20200303a.htm",
        pdf_url=None,
    )
    pdf_url = f"{BASE_URL}/monetarypolicy/files/monetary20200303a1.pdf"

    def fake_get(url: str) -> httpx.Response:
        if url == candidate.html_url:
            return _response(
                url,
                b'<a href="/monetarypolicy/files/monetary20200303a1.pdf">PDF</a>',
            )
        assert url == pdf_url
        return _response(url, status=404)

    validated = _complete_historical_statement(candidate, get=fake_get)

    assert validated.pdf_url is None
    assert "404" in (validated.discovery_error or "")


def test_sep_provider_rejects_real_slot_coverage_failure() -> None:
    current = _calendar(
        2025,
        _statement_row(
            "20250319", field=b"<div>missing projection field</div>"
        ).replace(b">19<", b">18-19*<"),
    )

    def fake_get(_provider: FedSepProvider, url: str) -> httpx.Response:
        if url == CALENDAR_URL:
            return _response(url, current)
        return _response(url, status=404)

    with patch.object(FedSepProvider, "_get", autospec=True, side_effect=fake_get):
        with FedSepProvider() as provider:
            with pytest.raises(NormalizationError, match="incomplete.*2025"):
                provider.fetch_outcomes(
                    years=(2025,),
                    retrieved_at=datetime(2025, 12, 31, tzinfo=UTC),
                )
