"""Contract tests for the ALFRED-backed realized-inflation adapter.

The fixture is a real FRED response frozen on 2026-08-18, containing three CPI
periods that have each been restated twice.  Those restatements are the whole
point: the adapter's job is to make a past state readable as it was published,
not as it now reads.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from uw_scan.sources.fred_macro import (
    SERIES_CONTRACT,
    FredSeriesBundle,
    observations_known_on,
    parse_fred_series,
)

from uw_scan.normalize import NormalizationError

FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
RETRIEVED_AT = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
SERIES_URL = "https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL"


def _bundle(
    *, raw: bytes | None = None, series_id: str = "CPIAUCSL"
) -> FredSeriesBundle:
    return FredSeriesBundle.from_bytes(
        series_id=series_id,
        source_url=SERIES_URL,
        raw_bytes=raw
        if raw is not None
        else (FIXTURES / "fred_cpi_vintages.json").read_bytes(),
        retrieved_at=RETRIEVED_AT,
    )


class TestVintageIdentity:
    def test_each_restatement_is_its_own_observation(self) -> None:
        rows = parse_fred_series(_bundle())
        january = [row for row in rows if row.period_end == date(2024, 1, 1)]
        assert len(january) == 3, (
            "three published values must produce three observations"
        )
        assert [row.value_numeric for row in january] == [
            Decimal("309.685"),
            Decimal("309.794"),
            Decimal("309.698"),
        ]

    def test_availability_is_the_vintage_not_the_period(self) -> None:
        rows = parse_fred_series(_bundle())
        first = next(
            row
            for row in rows
            if row.period_end == date(2024, 1, 1)
            and row.value_numeric == Decimal("309.685")
        )
        # January 2024 CPI was published on 2024-02-13, not on 2024-01-01.
        assert first.available_at.date() == date(2024, 2, 13)
        assert first.period_end == date(2024, 1, 1)

    def test_restatements_of_one_period_have_distinct_identities(self) -> None:
        rows = parse_fred_series(_bundle())
        january = [row for row in rows if row.period_end == date(2024, 1, 1)]
        assert len({row.vintage_hash for row in january}) == 3

    def test_observation_never_predates_its_artifact_retrieval_for_open_vintages(
        self,
    ) -> None:
        rows = parse_fred_series(_bundle())
        for row in rows:
            assert row.available_at <= RETRIEVED_AT, (
                "a vintage cannot become available after we retrieved the payload"
            )


class TestPointInTimeSelection:
    """The defect this whole milestone exists to prevent: reading today's value into the past."""

    def test_replay_returns_the_vintage_in_force(self) -> None:
        rows = parse_fred_series(_bundle())
        known = observations_known_on(rows, as_of=datetime(2024, 6, 1, tzinfo=UTC))
        january = [row for row in known if row.period_end == date(2024, 1, 1)]
        assert len(january) == 1
        assert january[0].value_numeric == Decimal("309.685")

    def test_replay_does_not_return_a_later_restatement(self) -> None:
        rows = parse_fred_series(_bundle())
        known = observations_known_on(rows, as_of=datetime(2024, 6, 1, tzinfo=UTC))
        values = {
            row.value_numeric for row in known if row.period_end == date(2024, 1, 1)
        }
        assert Decimal("309.698") not in values, (
            "current value must not leak into a 2024 replay"
        )

    def test_replay_before_first_publication_returns_nothing(self) -> None:
        rows = parse_fred_series(_bundle())
        known = observations_known_on(rows, as_of=datetime(2024, 2, 1, tzinfo=UTC))
        assert [row for row in known if row.period_end == date(2024, 1, 1)] == []

    def test_the_last_day_of_a_vintage_still_resolves_to_that_vintage(self) -> None:
        """FRED's ``realtime_end`` is inclusive; a half-open window must close after it.

        309.685 was the published value through 2025-02-11, and 309.794 took over on
        2025-02-12.  Closing the window at the start of 2025-02-11 makes the period
        vanish for a whole day -- a replay on that date would report no CPI at all.
        """
        rows = parse_fred_series(_bundle())
        for probe, expected in (
            ("2025-02-10", Decimal("309.685")),
            ("2025-02-11", Decimal("309.685")),
            ("2025-02-12", Decimal("309.794")),
        ):
            known = observations_known_on(
                rows, as_of=datetime.fromisoformat(f"{probe}T12:00:00+00:00")
            )
            january = [row for row in known if row.period_end == date(2024, 1, 1)]
            assert [row.value_numeric for row in january] == [expected], probe

    def test_replay_today_returns_the_current_value(self) -> None:
        rows = parse_fred_series(_bundle())
        known = observations_known_on(rows, as_of=RETRIEVED_AT)
        january = [row for row in known if row.period_end == date(2024, 1, 1)]
        assert [row.value_numeric for row in january] == [Decimal("309.698")]


class TestUnitsAndTransforms:
    def test_publisher_transform_is_recorded_not_inferred(self) -> None:
        # M158 is annualised month-over-month; M159 is year-over-year.  Same publisher,
        # near-identical titles, different meanings.
        assert (
            SERIES_CONTRACT["MEDCPIM158SFRBCLE"].publisher_transform == "mom_annualized"
        )
        assert SERIES_CONTRACT["CORESTICKM159SFRBATL"].publisher_transform == "yoy"
        assert SERIES_CONTRACT["CPIAUCSL"].publisher_transform == "index_level"

    def test_index_series_are_not_labelled_as_rates(self) -> None:
        assert SERIES_CONTRACT["CPIAUCSL"].unit == "index_1982_84_100_sa"
        assert "percent" not in SERIES_CONTRACT["CPIAUCSL"].unit

    def test_unknown_series_fails_closed(self) -> None:
        with pytest.raises(NormalizationError, match="unregistered"):
            _bundle(series_id="NOTASERIES")

    def test_the_adapter_computes_no_derived_rate(self) -> None:
        """Transforms belong to the engine; a source module reports what was published."""
        rows = parse_fred_series(_bundle())
        for row in rows:
            assert row.unit == SERIES_CONTRACT["CPIAUCSL"].unit
            assert row.value_numeric > 100, "an index level, never a percentage change"


class TestFailureStatesRemainDistinct:
    """BEA answers a missing credential with HTTP 200 and zero bytes.  Zero rows,
    an empty body and a transport error must never collapse into one outcome."""

    def test_zero_rows_is_not_an_error(self) -> None:
        payload = json.dumps(
            {"observations": [], "realtime_start": "2026-08-18"}
        ).encode()
        rows = parse_fred_series(_bundle(raw=payload))
        assert rows == []

    def test_empty_body_fails_closed(self) -> None:
        with pytest.raises(NormalizationError, match="empty"):
            parse_fred_series(_bundle(raw=b""))

    def test_body_without_an_observations_key_fails_closed(self) -> None:
        payload = json.dumps(
            {"error_code": 400, "error_message": "Bad Request"}
        ).encode()
        with pytest.raises(NormalizationError, match="observations"):
            parse_fred_series(_bundle(raw=payload))

    def test_unparseable_body_fails_closed(self) -> None:
        with pytest.raises(NormalizationError, match="JSON"):
            parse_fred_series(_bundle(raw=b"<HTML><H1>Access Denied</H1></HTML>"))

    def test_a_row_missing_its_vintage_fails_the_release(self) -> None:
        payload = json.dumps(
            {"observations": [{"date": "2024-01-01", "value": "309.685"}]}
        ).encode()
        with pytest.raises(NormalizationError, match="realtime_start"):
            parse_fred_series(_bundle(raw=payload))

    def test_a_suppressed_value_is_skipped_not_zeroed(self) -> None:
        payload = json.dumps(
            {
                "observations": [
                    {
                        "date": "2024-01-01",
                        "value": ".",
                        "realtime_start": "2024-02-13",
                        "realtime_end": "9999-12-31",
                    }
                ]
            }
        ).encode()
        assert parse_fred_series(_bundle(raw=payload)) == []


class TestArtifactIdentity:
    def test_artifact_records_the_redistributor_not_the_statistical_agency(
        self,
    ) -> None:
        artifact = _bundle().artifact
        # BLS is unreachable from this desk and publishes no vintages; the vintage
        # record is FRED's own product, so the provenance says FRED.
        assert artifact.source == "fred"
        assert artifact.source_kind == "first_party_publisher"
        assert artifact.cost_class == "free_publisher"

    def test_artifact_hash_covers_the_exact_bytes(self) -> None:
        raw = (FIXTURES / "fred_cpi_vintages.json").read_bytes()
        assert _bundle(raw=raw).artifact.content_length == len(raw)
        assert (
            _bundle(raw=raw).artifact.content_hash
            == _bundle(raw=raw).artifact.content_hash
        )
        assert (
            _bundle(raw=raw + b" ").artifact.content_hash
            != _bundle(raw=raw).artifact.content_hash
        )

    def test_artifact_availability_is_retrieval_for_a_rolling_query(self) -> None:
        # A series query is not a dated release: the bytes only became available when
        # we asked for them.  Backdating them to a period start would be the exact
        # defect MC1 fixed twice.
        assert _bundle().artifact.available_at == RETRIEVED_AT
        assert _bundle().artifact.published_at is None


class TestBroadDollarContract:
    """The USD anchor and its real sibling, registered on the same table as the rest.

    There is no ``sources/fed_h10.py``: the H.10 indices are published through
    FRED/ALFRED, and a second FRED client would give the two copies room to disagree
    about what a vintage is.  Recorded as deviation 2 in the design spec.
    """

    def test_the_anchor_and_its_real_sibling_are_registered_to_usd(self) -> None:
        for series_id in ("DTWEXBGS", "RTWEXBGS"):
            assert SERIES_CONTRACT[series_id].domain == "usd"

    def test_the_anchor_is_daily_and_the_real_index_is_not(self) -> None:
        # Not cosmetic: request_window() splits on this, so getting it wrong sends the
        # monthly series through the daily 2021 window and truncates 15 years of it.
        assert SERIES_CONTRACT["DTWEXBGS"].frequency == "daily"
        assert SERIES_CONTRACT["RTWEXBGS"].frequency == "monthly"

    def test_the_anchor_cadence_is_weekly_despite_a_daily_frequency(self) -> None:
        """A daily series whose staleness clock runs weekly, and it is not a typo.

        The H.10 goes out once a week carrying the week's daily observations together,
        so ``DTWEXBGS`` mints 52.2 vintages a year against roughly 250 for SOFR.  A
        cadence of 1 would mark the required USD anchor stale from Monday to Thursday of
        an ordinary week, and the state abstains when its anchor is missing -- so the
        wrong number here does not degrade the reading, it deletes it four days in five.
        Measured in docs/research/2026-08-12-usd-source-probe/VERDICT.md.
        """
        assert SERIES_CONTRACT["DTWEXBGS"].cadence_days == 7
        assert SERIES_CONTRACT["SOFR"].cadence_days == 1

    def test_both_indices_report_the_same_units_and_are_still_not_substitutes(
        self,
    ) -> None:
        # Identical units are exactly why the substitution is tempting: nothing about
        # the numbers themselves says one is CPI-deflated. The refusal has to be a rule.
        assert (
            SERIES_CONTRACT["DTWEXBGS"].unit
            == SERIES_CONTRACT["RTWEXBGS"].unit
            == "index_jan_2006_100"
        )

    def test_the_index_is_not_labelled_a_rate(self) -> None:
        assert SERIES_CONTRACT["DTWEXBGS"].publisher_transform == "index_level"

    def test_the_discontinued_major_currencies_index_is_unregistered(self) -> None:
        """``DTWEXM`` still answers every request, and everything it says is history.

        Last observation 2019-12-31.  It is absent rather than commented out because a
        registered contract is a thing the ingest will fetch.
        """
        assert "DTWEXM" not in SERIES_CONTRACT
