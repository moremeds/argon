"""The market-layer ingest against a real database, where the read path is the point.

A unit test can prove a parser produces the right ``available_at``.  What it cannot prove is
that the row then comes back out under the point-in-time gate — and that gate is the whole
reason this milestone exists.  ``fetch_macro_series_as_of`` joins the observation to its
artifact and bounds both, so an artifact written without ``vintage_bearing`` returns nothing
for any replay before the fetch, which reads as missing data rather than as a broken query.

Every payload here is real, captured from TreasuryDirect and CFTC on 2026-08-21 and shared
with ``tests/unit/macro/test_rates_market.py`` so both layers parse identical bytes.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.macro_market_layer_ingest import macro_market_layer_ingest_job

PAYLOADS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "fixtures/macro/rates_market_publisher_payloads.json"
    ).read_text()
)

#: After every instant in the payloads, because a vintage may not postdate the fetch that
#: reported it and the store refuses one that does.
RETRIEVED_AT = datetime(2026, 8, 21, 12, tzinfo=UTC)

TEN_YEAR_SHARE = "043602|lev_money_net_pct_oi"


def _payload(key: str) -> bytes:
    return json.dumps(PAYLOADS[key]).encode()


def _settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail("UW_SCAN_TEST_DB_NAME is not set", pytrace=False)
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used")
    return Settings.from_env().model_copy(update={"db_name": test_db})


class _Provider:
    """Serves prepared publisher payloads; the job must never reach a network."""

    def __init__(self, raw: bytes, url: str) -> None:
        self._raw = raw
        self._url = url
        self.calls = 0
        self.security_types: list[str] = []

    def __enter__(self) -> "_Provider":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def fetch_auctions_payload(self, *, security_type: str) -> tuple[bytes, str]:
        self.calls += 1
        self.security_types.append(security_type)
        return self._raw, self._url

    def fetch_treasury_payload(self, *, start: date) -> tuple[bytes, str]:
        self.calls += 1
        return self._raw, self._url


def _run(
    settings: Settings,
    *,
    auctions: bytes | None = None,
    positioning: bytes | None = None,
    observed_at: datetime = RETRIEVED_AT,
):
    supply = _Provider(
        auctions if auctions is not None else _payload("auctions"),
        "https://www.treasurydirect.gov/TA_WS/securities/auctioned?type=Note",
    )
    tff = _Provider(
        positioning if positioning is not None else _payload("positioning_stretched"),
        "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
    )
    return macro_market_layer_ingest_job(
        dsn=settings.db_dsn(),
        # One supply type: the two share a source, so ingesting Note and Bond from one
        # stubbed payload would resolve the second as an unchanged re-read and make the
        # created counts below say nothing about the write path.
        supply_types=("Note",),
        observed_at=observed_at,
        supply_provider_factory=lambda: supply,
        positioning_provider_factory=lambda: tff,
        max_attempts=1,
    )


def _series_as_of(settings: Settings, series_id: str, as_of: datetime) -> list[dict]:
    with psycopg.connect(settings.db_dsn()) as conn:
        return Repository(conn, schema="uw_scan").fetch_macro_series_as_of(
            series_id, as_of, preferred_sources=("treasurydirect", "cftc")
        )


def test_supply_and_positioning_land_as_evidence(seeded_db_empty_cards) -> None:
    settings = _settings()
    result = _run(settings)

    assert result.status == "ok", result.error_message
    assert result.feeds_succeeded == 2
    assert result.observations_created > 0

    ten_year = _series_as_of(settings, "10-Year|Note", RETRIEVED_AT)
    assert [(row["period_end"], row["value_numeric"]) for row in ten_year] == [
        (date(2026, 8, 12), Decimal("42000000000"))
    ]
    assert ten_year[0]["unit"] == "usd_offering_amount"
    assert ten_year[0]["source"] == "treasurydirect"
    # The announcement, a week before the auction it describes.
    assert ten_year[0]["available_at"] == datetime(2026, 8, 5, 4, tzinfo=UTC)

    share = _series_as_of(settings, TEN_YEAR_SHARE, RETRIEVED_AT)
    # -2,034,339 / 5,050,378 and -2,419,070 / 5,268,466, to four places.
    assert [row["value_numeric"] for row in share] == [
        Decimal("-40.2809"),
        Decimal("-45.9160"),
    ]
    assert share[0]["published_at"] == share[0]["available_at"]


def test_a_replay_before_the_release_sees_nothing(seeded_db_empty_cards) -> None:
    """Golden scenario 5 through the read path, which is where it can actually fail.

    CFTC loaded report 2026-06-16 on Monday 2026-06-22; the retired ``obs_date + 3 days``
    rule said Friday 2026-06-19.  An ``as_of`` inside that gap must return no row.  The
    unit test proves the parser stamps the right instant; this proves the query honours it.
    """
    settings = _settings()
    result = _run(settings, positioning=_payload("positioning_holiday"))
    assert result.status == "ok", result.error_message

    inside_the_gap = datetime(2026, 6, 19, 20, tzinfo=UTC)
    assert _series_as_of(settings, TEN_YEAR_SHARE, inside_the_gap) == []

    after_the_release = datetime(2026, 6, 23, tzinfo=UTC)
    visible = _series_as_of(settings, TEN_YEAR_SHARE, after_the_release)
    assert [row["period_end"] for row in visible] == [date(2026, 6, 16)]


def test_bulk_loaded_history_replays_from_the_load_not_the_report(
    seeded_db_empty_cards,
) -> None:
    """R1 end to end: a load event is late, and late is the safe direction.

    Both report dates share Socrata's 2022-09-13 backfill instant, so neither is visible in
    2018 when the positions were held.  That is the honest state of a row we first saw in
    2022, and it is recoverable -- migration 119 allows exactly one ``NULL -> value``
    resolution of ``published_at`` if a real instant is ever verified.
    """
    settings = _settings()
    assert (
        _run(settings, positioning=_payload("positioning_bulk_loaded")).status == "ok"
    )

    when_the_positions_were_held = datetime(2018, 12, 21, tzinfo=UTC)
    assert _series_as_of(settings, TEN_YEAR_SHARE, when_the_positions_were_held) == []

    after_the_load = datetime(2022, 9, 14, tzinfo=UTC)
    loaded = _series_as_of(settings, TEN_YEAR_SHARE, after_the_load)
    assert [row["period_end"] for row in loaded] == [
        date(2018, 12, 11),
        date(2018, 12, 18),
    ]
    assert all(row["published_at"] is None for row in loaded)


def test_reingesting_identical_bytes_creates_nothing(seeded_db_empty_cards) -> None:
    """A re-read is a witness to a vintage, not a new one.

    The scheduled job runs daily against publishers that release weekly or on an auction
    calendar, so most runs re-fetch bytes already stored.  If those minted observations,
    the store would grow a phantom revision history out of its own cron.
    """
    settings = _settings()
    first = _run(settings)
    second = _run(settings, observed_at=RETRIEVED_AT.replace(hour=18))

    assert second.observations_created == 0
    assert second.observations_unchanged == first.observations_created


def test_a_broken_payload_keeps_its_bytes_and_spares_the_other_feed(
    seeded_db_empty_cards,
) -> None:
    """The bytes that broke the parser are the bytes needed to fix it.

    ``:created_at`` dropped from a real row is the shape a Socrata ``$select`` regression
    actually takes.  Positioning must fail, its payload must survive, and supply must be
    entirely unaffected -- feed isolation is why one publisher's schema change cannot take
    the layer down with it.
    """
    settings = _settings()
    broken = json.dumps(
        [
            {k: v for k, v in row.items() if k != ":created_at"}
            for row in PAYLOADS["positioning_stretched"]
        ]
    ).encode()

    result = _run(settings, positioning=broken)

    assert result.failed_feeds == ("cftc:tff",)
    assert result.status == "degraded"
    assert "created_at" in (result.error_message or "")
    assert _series_as_of(settings, TEN_YEAR_SHARE, RETRIEVED_AT) == []
    assert _series_as_of(settings, "10-Year|Note", RETRIEVED_AT), "supply is untouched"

    expected_hash, expected_length = macro_artifact_content_identity(raw_bytes=broken)
    with psycopg.connect(settings.db_dsn()) as conn:
        row = conn.execute(
            """
            SELECT content_length, raw_bytes, vintage_bearing, source
            FROM uw_scan.macro_source_artifacts
            WHERE content_hash = %s
            """,
            (expected_hash,),
        ).fetchone()
    assert row is not None, "the payload that broke the parser was not preserved"
    assert row[0] == expected_length
    assert bytes(row[1]) == broken
    assert row[2] is True
    assert row[3] == "cftc"


def test_each_supply_type_is_requested_on_its_own(seeded_db_empty_cards) -> None:
    """One request per instrument type, or the deep half of the history never arrives."""
    settings = _settings()
    providers: list[_Provider] = []

    def supply_factory() -> _Provider:
        provider = _Provider(
            _payload("auctions"),
            "https://www.treasurydirect.gov/TA_WS/securities/auctioned",
        )
        providers.append(provider)
        return provider

    result = macro_market_layer_ingest_job(
        dsn=settings.db_dsn(),
        observed_at=RETRIEVED_AT,
        supply_provider_factory=supply_factory,
        positioning_provider_factory=lambda: _Provider(
            _payload("positioning_stretched"),
            "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
        ),
        max_attempts=1,
    )

    assert result.status == "ok", result.error_message
    assert [t for p in providers for t in p.security_types] == ["Note", "Bond"]
