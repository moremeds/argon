from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx

from uw_scan.sources.fed_funds_futures_path import FedChirpPolicyPathProvider


FEDCHIRP_HTML = """
<p>The fed funds futures curve. as of 2026-05-22.</p>
<h3 class="path__h3">Per-meeting probability buckets</h3>
<table class="rxn cards">
  <tbody>
    <tr>
      <td data-label="Meeting" class="rxn__meeting">2026-06-17</td>
      <td data-label="Implied rate after"><strong>3.611%</strong></td>
      <td data-label="Delta at meeting">-1.6 bp</td>
      <td data-label="Cut 25 bp">6%</td>
      <td data-label="Hold">94%</td>
      <td data-label="Hike 25 bp">0%</td>
    </tr>
    <tr>
      <td data-label="Meeting" class="rxn__meeting">2026-07-29</td>
      <td data-label="Implied rate after"><strong>3.855%</strong></td>
      <td data-label="Delta at meeting">+24.4 bp</td>
      <td data-label="Cut 25 bp">0%</td>
      <td data-label="Hold">3%</td>
      <td data-label="Hike 25 bp">97%</td>
    </tr>
  </tbody>
</table>
"""


def test_fed_chirp_policy_path_provider_parses_futures_implied_rows() -> None:
    response = httpx.Response(
        200,
        text=FEDCHIRP_HTML,
        request=httpx.Request("GET", "https://www.fedchirp.com/"),
    )

    with patch.object(FedChirpPolicyPathProvider, "_get", return_value=response):
        with FedChirpPolicyPathProvider() as provider:
            rows = provider.fetch_latest_path(current_target_range="3.50-3.75%")

    assert len(rows) == 2
    assert rows[0].meeting_date == date(2026, 6, 17)
    assert rows[0].label == "6/17"
    assert rows[0].probability == 94.0
    assert rows[0].stance == "HOLD"
    assert rows[0].target_range == "3.50-3.75%"
    assert rows[0].source == "FedChirp fed funds futures"

    assert rows[1].meeting_date == date(2026, 7, 29)
    assert rows[1].probability == 97.0
    assert rows[1].stance == "HIKE"
    assert rows[1].target_range == "3.75-4.00%"
