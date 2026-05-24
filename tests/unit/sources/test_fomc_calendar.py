from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx

from uw_scan.sources.fomc_calendar import FomcCalendarProvider


CALENDAR_HTML = """
<html><body>
<h4>2026 FOMC Meetings</h4>
<div class="row fomc-meeting">
  <div>April</div><div>28-29</div>
  Statement: <a href="/monetarypolicy/fomcstatement20260429.htm">HTML</a>
</div>
<div class="row fomc-meeting">
  <div>June</div><div>16-17*</div>
</div>
</body></html>
"""

STATEMENT_HTML = """
<html><body>
<p>The Committee decided to maintain the target range for the federal funds
rate at 3-1/2 to 3-3/4 percent.</p>
<p>Voting for the monetary policy action were Jerome H. Powell, John C.
Williams, Michael S. Barr, and Michelle W. Bowman. Voting against this action
were Christopher J. Waller and Adriana D. Kugler.</p>
</body></html>
"""


def _response(path: str, text: str) -> httpx.Response:
    return httpx.Response(200, text=text, request=httpx.Request("GET", path))


def test_fomc_calendar_provider_extracts_meetings_and_statement_vote_split() -> None:
    responses = [
        _response(FomcCalendarProvider.CALENDAR_PATH, CALENDAR_HTML),
        _response("/monetarypolicy/fomcstatement20260429.htm", STATEMENT_HTML),
    ]
    with patch.object(FomcCalendarProvider, "_get", side_effect=responses):
        with FomcCalendarProvider() as provider:
            meetings = provider.fetch_meetings(years=(2026,))

    april = meetings[0]
    assert april.start_date == date(2026, 4, 28)
    assert april.end_date == date(2026, 4, 29)
    assert april.action == "Hold"
    assert april.vote_split == "4-2"
    assert april.source_url.endswith("fomcstatement20260429.htm")
