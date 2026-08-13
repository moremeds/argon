from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup, Tag

from uw_scan.sources.fomc_release_discovery import discover_official_release_result


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


def _without_parent_class(
    raw: bytes,
    *,
    href_suffix: str,
    class_name: str,
) -> bytes:
    soup = BeautifulSoup(raw, "html.parser")
    anchor = next(
        link
        for link in soup.find_all("a", href=True)
        if str(link["href"]).endswith(href_suffix)
    )
    parent = anchor.find_parent(class_=class_name)
    assert isinstance(parent, Tag)
    parent["class"] = [
        value for value in parent.get("class", []) if value != class_name
    ]
    return soup.encode()


def _fixture_get(*, calendar: bytes, history: bytes | None = None):
    def fake_get(url: str) -> httpx.Response:
        if url == CALENDAR_URL:
            return _response(url, calendar)
        if url.endswith("fomchistorical2020.htm"):
            return (
                _response(url, history)
                if history is not None
                else _response(url, status=404)
            )
        if url.endswith(".pdf"):
            return _response(url, b"%PDF exact", media_type="application/pdf")
        if "monetary2020" in url:
            stem = url.rsplit("/", 1)[-1].removesuffix(".htm")
            return _response(
                url,
                f'<a href="/monetarypolicy/files/{stem}1.pdf">PDF</a>'.encode(),
            )
        return _response(url, b"<html>SEP</html>")

    return fake_get


def test_current_census_rejects_canonical_statement_missed_by_row_selector() -> None:
    calendar = _without_parent_class(
        (FIXTURES / "fomc_calendar_current.html").read_bytes(),
        href_suffix="monetary20250129a.htm",
        class_name="fomc-meeting",
    )

    result = discover_official_release_result(
        get=_fixture_get(calendar=calendar),
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )

    rejections = result.page_outcomes[0].slot_rejections
    assert result.coverage_complete is False
    assert {slot.identity for slot in rejections} == {
        "fomc-statement:monetary20250129a"
    }
    assert "not mapped" in (rejections[0].error_message or "")


@pytest.mark.parametrize(
    ("release_type", "href_suffix", "expected_identity"),
    [
        (
            "statement",
            "monetary20200303a.htm",
            "fomc-statement:monetary20200303a",
        ),
        (
            "sep",
            "FOMC20200610SEPcompilation.pdf",
            "fed-sep:fomcprojtabl20200610",
        ),
    ],
)
def test_history_census_rejects_marker_missed_by_panel_selector(
    release_type: str,
    href_suffix: str,
    expected_identity: str,
) -> None:
    history = _without_parent_class(
        (FIXTURES / "fomc_historical_2020.html").read_bytes(),
        href_suffix=href_suffix,
        class_name="panel-padded",
    )

    result = discover_official_release_result(
        get=_fixture_get(
            calendar=(FIXTURES / "fomc_calendar_current.html").read_bytes(),
            history=history,
        ),
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2020,),
        release_type=release_type,  # type: ignore[arg-type]
        as_of_date=date(2026, 8, 13),
    )

    history_page = result.page_outcomes[1]
    assert result.coverage_complete is False
    assert {slot.identity for slot in history_page.slot_rejections} == {
        expected_identity
    }
    assert "not mapped" in (history_page.slot_rejections[0].error_message or "")


def test_history_census_rejects_statement_without_classifiable_heading() -> None:
    history = b"""
    <section>
      <h5>Special publication - 2020</h5>
      <a href="/newsevents/pressreleases/monetary20200303a.htm">Statement</a>
    </section>
    """

    result = discover_official_release_result(
        get=_fixture_get(calendar=b"<html></html>", history=history),
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2020,),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )

    rejection = result.page_outcomes[1].slot_rejections[0]
    assert result.coverage_complete is False
    assert rejection.identity == "fomc-statement:monetary20200303a"
    assert "event classification" in (rejection.error_message or "")


def test_current_census_excludes_bounded_strategy_context_without_hiding_rates() -> (
    None
):
    calendar = (FIXTURES / "fomc_calendar_current.html").read_bytes()

    result = discover_official_release_result(
        get=_fixture_get(calendar=calendar),
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )

    assert result.coverage_complete is True
    assert result.page_outcomes[0].slots_rejected == 0
    assert "fomc-statement:monetary20250822a" not in {
        candidate.release_key for candidate in result.candidates
    }


def test_current_census_excludes_strategy_field_canonical_pdf_sibling() -> None:
    soup = BeautifulSoup(
        (FIXTURES / "fomc_calendar_current.html").read_bytes(), "html.parser"
    )
    strategy = next(
        link
        for link in soup.find_all("a", href=True)
        if str(link["href"]).endswith("monetary20250822a.htm")
    )
    strategy.insert_before(
        BeautifulSoup(
            '<a href="/monetarypolicy/files/monetary20250822a1.pdf">PDF</a> | ',
            "html.parser",
        )
    )

    result = discover_official_release_result(
        get=_fixture_get(calendar=soup.encode()),
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="statement",
        as_of_date=date(2026, 8, 13),
    )

    assert result.coverage_complete is True
    assert result.page_outcomes[0].slots_rejected == 0


@pytest.mark.parametrize(
    ("release_type", "expected_current", "expected_history"),
    [("statement", 45, 10), ("sep", 22, 3)],
)
def test_frozen_census_preserves_accepted_release_counts(
    release_type: str,
    expected_current: int,
    expected_history: int,
) -> None:
    result = discover_official_release_result(
        get=_fixture_get(
            calendar=(FIXTURES / "fomc_calendar_current.html").read_bytes(),
            history=(FIXTURES / "fomc_historical_2020.html").read_bytes(),
        ),
        base_url=BASE_URL,
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=tuple(range(2020, 2027)),
        release_type=release_type,  # type: ignore[arg-type]
        as_of_date=date(2026, 8, 13),
    )

    current, history = result.page_outcomes[0], result.page_outcomes[1]
    assert (current.slots_accepted, current.slots_rejected) == (expected_current, 0)
    assert (history.slots_accepted, history.slots_rejected) == (expected_history, 0)
