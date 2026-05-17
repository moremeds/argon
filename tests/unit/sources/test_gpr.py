"""GPR daily index parser — xls (BIFF8) as of 2026-05."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx

from uw_scan.sources.gpr import GprProvider


def _fake_response(body: bytes = b"\x00", status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        content=body,
        request=httpx.Request("GET", GprProvider.DEFAULT_URL),
    )


def _fake_workbook(header: list[str], rows: list[list[object]]) -> MagicMock:
    """Build a MagicMock with the xlrd Sheet/Workbook surface we use."""
    sheet = MagicMock()
    sheet.nrows = 1 + len(rows)
    sheet.ncols = len(header)
    table = [header, *rows]
    sheet.cell_value.side_effect = lambda r, c: table[r][c]
    workbook = MagicMock()
    workbook.sheet_by_index.return_value = sheet
    return workbook


def test_gpr_parses_xls_skips_blank_and_unparseable() -> None:
    wb = _fake_workbook(
        header=["DAY", "GPRD"],
        rows=[
            [20260512, 118.4],
            [20260513, 121.2],
            [20260514, ""],  # blank — skipped
            ["abc", 99.0],  # unparseable DAY — skipped
            [20260515, 109.7],
        ],
    )
    with (
        patch.object(GprProvider, "_get_with_telemetry") as mock_get,
        patch("uw_scan.sources.gpr.xlrd.open_workbook", return_value=wb),
    ):
        mock_get.return_value = _fake_response()
        with GprProvider() as p:
            rows = p.fetch_daily(start=date(2026, 5, 12))
    assert [r.obs_date for r in rows] == [
        date(2026, 5, 12),
        date(2026, 5, 13),
        date(2026, 5, 15),
    ]
    assert rows[0].value == Decimal("118.4")


def test_gpr_filters_by_start_date() -> None:
    wb = _fake_workbook(
        header=["DAY", "GPRD"],
        rows=[
            [20260510, 100.0],
            [20260513, 121.2],
        ],
    )
    with (
        patch.object(GprProvider, "_get_with_telemetry") as mock_get,
        patch("uw_scan.sources.gpr.xlrd.open_workbook", return_value=wb),
    ):
        mock_get.return_value = _fake_response()
        with GprProvider() as p:
            rows = p.fetch_daily(start=date(2026, 5, 12))
    assert [r.obs_date for r in rows] == [date(2026, 5, 13)]


def test_gpr_telemetry_records() -> None:
    wb = _fake_workbook(header=["DAY", "GPRD"], rows=[[20260512, 118.4]])
    captured = []

    def fake_record(_self, event):
        captured.append(event)

    with (
        patch.object(GprProvider, "_record_request", fake_record),
        patch("uw_scan.sources.gpr.httpx.Client.get") as mock_get,
        patch("uw_scan.sources.gpr.xlrd.open_workbook", return_value=wb),
    ):
        mock_get.return_value = _fake_response()
        with GprProvider() as p:
            p.fetch_daily(start=date(2026, 5, 12))

    assert len(captured) == 1
    event = captured[0]
    assert event.provider == "gpr"
    assert event.endpoint_key == "gpr_daily_xls"
    assert event.status_code == 200
    assert event.status_family == "2xx"
