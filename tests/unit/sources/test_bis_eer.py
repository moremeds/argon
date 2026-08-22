"""Contract tests for the BIS effective-exchange-rate cross-check.

Both fixtures are real responses frozen on 2026-08-21 from
``stats.bis.org/api/v2``, dataflow ``BIS/WS_EER/1.0``, key ``D.N.B.US``:

* ``bis_eer_us_broad_nominal.json`` -- the SDMX-JSON message returned when the
  ``Accept`` header selects JSON;
* ``bis_eer_bare_request.xml`` -- what the SAME url returns with ``Accept: */*``.
  It is an HTTP **200**. That file exists so the negotiation trap is tested against
  the publisher's actual bytes rather than a hand-written stand-in.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from uw_scan.sources.bis_eer import (
    DATAFLOW,
    SDMX_JSON_ACCEPT,
    US_NOMINAL_BROAD_DAILY,
    BisEerError,
    BisEerProvider,
    BisEerReading,
    parse_eer,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
JSON_BODY = (FIXTURES / "bis_eer_us_broad_nominal.json").read_bytes()
XML_BODY = (FIXTURES / "bis_eer_bare_request.xml").read_bytes()
JSON_CT = "application/json;charset=UTF-8"
XML_CT = "application/xml;charset=UTF-8"


def _parse(
    *, body: bytes = JSON_BODY, media_type: str = JSON_CT, status: int = 200
) -> list[BisEerReading]:
    return parse_eer(status_code=status, media_type=media_type, body=body)


class TestContentNegotiation:
    def test_a_200_carrying_xml_is_refused(self) -> None:
        """The trap this module exists for.

        BIS content-negotiates on ``Accept`` alone, so a client that omits the header
        does not fail -- it succeeds and hands SDMX-ML to a JSON parser.
        ``raise_for_status`` would pass this response through.
        """
        with pytest.raises(BisEerError) as excinfo:
            _parse(body=XML_BODY, media_type=XML_CT)
        # The message must name BOTH halves: the status that looked like success and
        # the media type that was actually returned. Either alone sends the reader
        # looking in the wrong place.
        assert "200" in str(excinfo.value)
        assert "application/xml" in str(excinfo.value)

    def test_the_refusal_names_the_header_that_fixes_it(self) -> None:
        with pytest.raises(BisEerError, match="sdmx.data\\+json"):
            _parse(body=XML_BODY, media_type=XML_CT)

    def test_charset_suffix_does_not_defeat_the_media_type_check(self) -> None:
        # The live response is 'application/json;charset=UTF-8', never the bare type.
        assert _parse(media_type="application/json;charset=UTF-8")

    def test_a_non_200_is_a_failure_not_an_absence(self) -> None:
        with pytest.raises(BisEerError, match="HTTP 406"):
            _parse(status=406, media_type=XML_CT)


class TestAbsence:
    def test_nan_is_an_absence_and_never_a_zero(self) -> None:
        """Non-trading days come back as the string ``NaN``.

        The frozen window spans two weekends, so this is the publisher's own data
        rather than a constructed edge case.
        """
        rows = _parse()
        absent = [row for row in rows if row.value is None]
        assert absent, "fixture must contain at least one non-trading day"
        assert all(row.value != Decimal(0) for row in absent)
        assert {row.period.weekday() for row in absent} <= {5, 6}

    def test_a_published_nothing_is_not_an_error(self) -> None:
        body = json.loads(JSON_BODY)
        body["data"]["dataSets"] = []
        assert _parse(body=json.dumps(body).encode()) == []

    def test_a_dataset_with_no_series_is_not_an_error(self) -> None:
        body = json.loads(JSON_BODY)
        body["data"]["dataSets"][0]["series"] = {}
        assert _parse(body=json.dumps(body).encode()) == []


class TestCrossCheckOnly:
    def test_a_reading_carries_no_availability(self) -> None:
        """The structural reason BIS can never be evidence.

        A SDMX data message has no real-time dimension, so there is no vintage to
        select and nothing here can answer what the level was believed to be on a past
        date. A reading therefore has no ``available_at`` to promote into the evidence
        store -- the type refuses, not a comment.
        """
        row = _parse()[0]
        assert not hasattr(row, "available_at")
        assert not hasattr(row, "vintage_hash")
        assert not hasattr(row, "superseded_at")

    def test_every_reading_declares_itself_not_vintage_bearing(self) -> None:
        assert all(row.vintage_bearing is False for row in _parse())

    def test_the_flag_cannot_be_flipped_on_a_frozen_reading(self) -> None:
        row = _parse()[0]
        with pytest.raises(Exception):
            row.vintage_bearing = True  # type: ignore[misc]


class TestParsing:
    def test_the_frozen_window_parses_to_real_levels(self) -> None:
        rows = _parse()
        assert len(rows) == 12
        priced = [row for row in rows if row.value is not None]
        assert len(priced) == 8
        assert rows[0].period == date(2026, 8, 7)
        assert rows[0].value == Decimal("102.1")
        assert rows[-1].period == date(2026, 8, 18)
        assert rows[-1].value == Decimal("101.87")

    def test_readings_are_ordered_by_period(self) -> None:
        rows = _parse()
        assert [row.period for row in rows] == sorted(row.period for row in rows)

    def test_a_json_body_that_is_not_sdmx_fails_closed(self) -> None:
        with pytest.raises(BisEerError, match="not an SDMX data message"):
            _parse(body=b'{"hello": "world"}')

    def test_an_unparseable_body_fails_closed(self) -> None:
        with pytest.raises(BisEerError, match="not JSON"):
            _parse(body=b"{not json")

    def test_a_non_numeric_value_fails_closed_rather_than_becoming_none(self) -> None:
        """``NaN`` is the ONE absence marker. Anything else unparseable is a defect.

        Widening the ``None`` branch to catch every bad value would turn a publisher
        format change into a silent run of empty trading days.
        """
        body = json.loads(JSON_BODY)
        series = next(iter(body["data"]["dataSets"][0]["series"].values()))
        first = next(iter(series["observations"]))
        series["observations"][first] = ["not-a-number"]
        with pytest.raises(BisEerError, match="not numeric"):
            _parse(body=json.dumps(body).encode())

    def test_an_observation_index_with_no_period_fails_closed(self) -> None:
        body = json.loads(JSON_BODY)
        series = next(iter(body["data"]["dataSets"][0]["series"].values()))
        series["observations"]["999"] = ["102.0"]
        with pytest.raises(BisEerError, match="no matching period"):
            _parse(body=json.dumps(body).encode())


class TestTheFetchPath:
    """The client, not just the parser.

    ``parse_eer`` was split out so the negotiation trap is testable without a network
    round trip — but that left the half that actually TALKS to BIS untested, including
    the one line that makes the whole module correct: sending the Accept header.
    """

    class _StubClient:
        """Records the request and replays a canned response."""

        def __init__(self, response: httpx.Response | Exception) -> None:
            self.response = response
            self.calls: list[dict[str, object]] = []

        def get(self, path, *, params=None, headers=None):
            self.calls.append({"path": path, "params": params, "headers": headers})
            if isinstance(self.response, Exception):
                raise self.response
            return self.response

        def close(self) -> None:
            pass

    @staticmethod
    def _ok() -> httpx.Response:
        return httpx.Response(200, content=JSON_BODY, headers={"content-type": JSON_CT})

    def test_the_accept_header_is_sent_on_the_request(self) -> None:
        """Not merely set on the client: an injected client may not carry it.

        A bare request returns HTTP 200 with XML, so this header is the only thing
        standing between the parser and SDMX-ML.
        """
        stub = self._StubClient(self._ok())
        with BisEerProvider(client=stub) as provider:
            provider.fetch_us_broad_nominal()
        assert stub.calls[0]["headers"]["Accept"] == SDMX_JSON_ACCEPT

    def test_it_asks_for_the_us_broad_nominal_daily_series(self) -> None:
        stub = self._StubClient(self._ok())
        with BisEerProvider(client=stub) as provider:
            provider.fetch_us_broad_nominal(last_n=7)
        assert US_NOMINAL_BROAD_DAILY in str(stub.calls[0]["path"])
        assert DATAFLOW in str(stub.calls[0]["path"])
        assert stub.calls[0]["params"] == {"lastNObservations": "7"}

    def test_a_transport_failure_is_a_named_error_not_a_bare_httpx_one(self) -> None:
        """A caller must not have to know this module talks HTTP to handle its failure.

        And it must never look like an absence: a cross-check that could not be reached
        is a different fact from one that disagreed.
        """
        stub = self._StubClient(httpx.ConnectError("no route to host"))
        with BisEerProvider(client=stub) as provider:
            with pytest.raises(BisEerError, match="transport failure"):
                provider.fetch_us_broad_nominal()

    def test_the_fetch_path_returns_parsed_readings(self) -> None:
        stub = self._StubClient(self._ok())
        with BisEerProvider(client=stub) as provider:
            rows = provider.fetch_us_broad_nominal()
        assert len(rows) == 12
        assert all(row.vintage_bearing is False for row in rows)

    def test_a_200_with_xml_still_fails_through_the_client(self) -> None:
        # The trap has to survive the fetch path too, not just a direct parse call.
        stub = self._StubClient(
            httpx.Response(200, content=XML_BODY, headers={"content-type": XML_CT})
        )
        with BisEerProvider(client=stub) as provider:
            with pytest.raises(BisEerError, match="application/xml"):
                provider.fetch_us_broad_nominal()
