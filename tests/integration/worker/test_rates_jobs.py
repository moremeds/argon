from __future__ import annotations

import os
from datetime import UTC, date, datetime
from decimal import Decimal

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.sources.cleveland_fed import ClevelandFedInflationRecord
from uw_scan.sources.cftc_tff import CftcTffTreasuryRow
from uw_scan.sources.fred import FredObservation
from uw_scan.sources.treasury_supply import TreasuryAuctionRow, TreasuryDebtRecord
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.rates_jobs import (
    _history_start_for_snapshot,
    rates_fred_ingest_job,
)


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set; refusing to write into the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def migrated_settings(seeded_db_empty_cards) -> Settings:
    # seeded_db_empty_cards drives the session migrate + per-test baseline
    # restore. The job under test opens its own connection from settings.db_dsn().
    return _test_settings()


class _Provider:
    def __init__(self, *, api_key, record_request=None, job_name=None):
        self.api_key = api_key
        self.record_request = record_request
        self.job_name = job_name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_observations(self, series_id, *, start=None, end=None):
        values = {
            "DGS1MO": "3.66",
            "DGS3MO": "3.67",
            "DGS6MO": "3.77",
            "DGS1": "3.83",
            "DGS2": "4.13",
            "DGS3": "4.20",
            "DGS5": "4.32",
            "DGS7": "4.50",
            "DGS10": "4.67",
            "DGS20": "5.19",
            "DGS30": "5.18",
            "DFII10": "2.13",
            "T10YIE": "2.48",
            "T5YIFR": "2.35",
            "EFFR": "3.63",
            "SOFR": "3.65",
            "DFEDTARL": "3.50",
            "DFEDTARU": "3.75",
            "WALCL": "6728502",
            "WRESBAL": "3129559",
            "RRPONTSYD": "24.87",
            "WTREGEN": "781292",
        }
        if series_id not in values:
            return []
        return [
            FredObservation(
                series_id=series_id,
                obs_date=date(2026, 5, 20),
                value=Decimal(values[series_id]),
                realtime_start=date(2026, 5, 20),
                realtime_end=date(2026, 5, 20),
            )
        ]


class _FailingCurveProvider(_Provider):
    def fetch_observations(self, series_id, *, start=None, end=None):
        if series_id == "DGS10":
            raise RuntimeError("DGS10 unavailable")
        return super().fetch_observations(series_id, start=start, end=end)


class _ClevelandProvider:
    def __init__(self, *, record_request=None, job_name=None):
        self.record_request = record_request
        self.job_name = job_name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_model_rows(self, *, start=None):
        return [
            ClevelandFedInflationRecord(
                obs_date=date(2026, 5, 1),
                expected_inflation_10y=Decimal("2.4761367"),
                real_risk_premium_10y=Decimal("1.2312081"),
                inflation_risk_premium_10y=Decimal("0.3489275"),
                model_real_yield_10y=Decimal("1.6340507389933305"),
            )
        ]


class _FomcProvider:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_meetings(self, *, years):
        return [
            {
                "event_date": date(2026, 4, 28),
                "event_end_date": date(2026, 4, 29),
                "label": "April 28-29 FOMC",
                "action": "Hold",
                "vote_split": "8-4",
                "source_url": "https://www.federalreserve.gov/monetarypolicy/fomc.htm",
            }
        ]


class _PolicyPathProvider:
    def __init__(
        self,
        *,
        base_url="https://www.frenzycap.com/fedwatch",
        record_request=None,
        job_name=None,
    ):
        self.base_url = base_url
        self.record_request = record_request
        self.job_name = job_name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_latest_path(self, *, current_target_range):
        assert current_target_range == "3.50-3.75%"
        return [
            {
                "meeting_date": date(2026, 6, 17),
                "label": "6/17",
                "probability": 99.0,
                "stance": "HOLD",
                "target_range": "3.50-3.75%",
                "source": "Frenzy Capital Fed Watch",
                "status": "ok",
            }
        ]


class _CftcTffProvider:
    def __init__(self, *, record_request=None, job_name=None):
        self.record_request = record_request
        self.job_name = job_name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_treasury_rows(self, *, start=None):
        return [
            CftcTffTreasuryRow(
                contract_code="043602",
                contract_name="UST 10Y NOTE",
                commodity_name="T-NOTES, 6.5-10 YEAR",
                tenor_bucket="10Y",
                obs_date=date(2026, 5, 19),
                release_date=date(2026, 5, 22),
                open_interest=Decimal("4544233"),
                dealer_long=Decimal("416965"),
                dealer_short=Decimal("514194"),
                dealer_net=Decimal("-97229"),
                asset_mgr_long=Decimal("2155592"),
                asset_mgr_short=Decimal("854840"),
                asset_mgr_net=Decimal("1300752"),
                lev_money_long=Decimal("625134"),
                lev_money_short=Decimal("1819579"),
                lev_money_net=Decimal("-1194445"),
                other_rept_long=Decimal("189323"),
                other_rept_short=Decimal("319340"),
                other_rept_net=Decimal("-130017"),
                dealer_net_pct_oi=Decimal("-2.1"),
                asset_mgr_net_pct_oi=Decimal("28.6"),
                lev_money_net_pct_oi=Decimal("-26.3"),
            )
        ]


class _TreasurySupplyProvider:
    def __init__(self, *, record_request=None, job_name=None):
        self.record_request = record_request
        self.job_name = job_name

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def fetch_recent_auctions(self, *, start=None):
        return [
            TreasuryAuctionRow(
                cusip="912810UL0",
                security_type="Bond",
                security_term="30-Year",
                auction_date=date(2026, 5, 14),
                issue_date=date(2026, 5, 15),
                offering_amount=Decimal("25000000000"),
                high_rate=Decimal("5.046"),
                bid_to_cover=Decimal("2.30"),
                direct_bidder_pct=Decimal("20.3"),
                indirect_bidder_pct=Decimal("56.5"),
                primary_dealer_pct=Decimal("23.2"),
                tail_indicator="long-end",
                source_url="https://fiscaldata.treasury.gov/static-data/published-reports/auctions-query/results/R_20260514_1.pdf",
            )
        ]

    def fetch_latest_debt(self):
        return TreasuryDebtRecord(
            record_date=date(2026, 5, 21),
            debt_held_public=Decimal("31374788661132.13"),
            intragov_holdings=Decimal("7696411796234.32"),
            total_public_debt=Decimal("39071200457366.45"),
            source_url="https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/debt_to_penny",
        )


def test_rates_job_requires_fred_api_key(migrated_settings: Settings):
    with pytest.raises(RuntimeError, match="FRED_API_KEY"):
        rates_fred_ingest_job(
            dsn=migrated_settings.db_dsn(),
            fred_api_key=None,
            provider_factory=_Provider,
            computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        )


def test_rates_job_history_start_includes_ytd_anchor_buffer():
    assert _history_start_for_snapshot(
        date(2026, 5, 20), lookback_days=45
    ) == date(2025, 12, 18)
    assert _history_start_for_snapshot(
        date(2026, 1, 10), lookback_days=45
    ) == date(2025, 11, 26)


def test_rates_job_persists_observations_and_snapshot(migrated_settings: Settings):
    result = rates_fred_ingest_job(
        dsn=migrated_settings.db_dsn(),
        fred_api_key="fred-test",
        provider_factory=_Provider,
        cleveland_provider_factory=_ClevelandProvider,
        fomc_provider_factory=_FomcProvider,
        policy_path_provider_factory=_PolicyPathProvider,
        cftc_tff_provider_factory=_CftcTffProvider,
        treasury_supply_provider_factory=_TreasurySupplyProvider,
        computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
    )

    assert result.inserted_observations > 0
    assert result.failed_series == []
    assert result.snapshot_date == date(2026, 5, 20)

    with psycopg.connect(migrated_settings.db_dsn()) as conn:
        repo = Repository(conn, schema=migrated_settings.db_schema)
        row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    assert row["payload"]["as_of"] == "2026-05-20"
    assert row["payload"]["decomposition"]["nominal_10y"] == 4.67
    assert row["payload"]["decomposition"]["model_source"] == (
        "Cleveland Fed Inflation Expectations"
    )
    assert row["payload"]["decomposition"]["expected_short_inflation_10y"] == 2.48
    assert row["payload"]["policy"]["target_range"] == "3.50-3.75%"
    assert row["payload"]["policy"]["last_meeting"]["vote_split"] == "8-4"
    assert row["payload"]["policy"]["implied_path"][0]["source"] == (
        "Frenzy Capital Fed Watch"
    )
    assert row["payload"]["positioning"]["status"] == "ok"
    assert row["payload"]["positioning"]["details"][0]["contract_code"] == "043602"
    assert (
        row["payload"]["positioning"]["details"][0]["lev_money_net_pct_oi"] == -26.3
    )
    assert "CFTC TFF" in row["payload"]["positioning"]["positioning_read"]
    assert row["payload"]["supply"]["status"] == "ok"
    assert row["payload"]["supply"]["recent_auctions"][0]["security_term"] == "30-Year"
    assert row["payload"]["supply"]["fiscal"][0]["label"] == "Public debt"


def test_rates_job_refuses_snapshot_when_required_curve_series_fails(
    migrated_settings: Settings,
):
    with pytest.raises(RuntimeError, match="required FRED Treasury curve series"):
        rates_fred_ingest_job(
            dsn=migrated_settings.db_dsn(),
            fred_api_key="fred-test",
            provider_factory=_FailingCurveProvider,
            cleveland_provider_factory=_ClevelandProvider,
            computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        )

    with psycopg.connect(migrated_settings.db_dsn()) as conn:
        repo = Repository(conn, schema=migrated_settings.db_schema)
        assert repo.fetch_latest_rates_snapshot() is None
        assert repo.fetch_rates_series("CLEVE_EXPECTED_INFLATION_10Y")


def test_rates_job_keeps_raw_observations_when_snapshot_build_fails(
    migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def fail_snapshot(*_args, **_kwargs):
        raise ValueError("snapshot assembler failed")

    monkeypatch.setattr("uw_scan.worker.jobs.rates_jobs.build_rates_snapshot", fail_snapshot)

    with pytest.raises(ValueError, match="snapshot assembler failed"):
        rates_fred_ingest_job(
            dsn=migrated_settings.db_dsn(),
            fred_api_key="fred-test",
            provider_factory=_Provider,
            cleveland_provider_factory=_ClevelandProvider,
            computed_at=datetime(2026, 5, 20, 22, tzinfo=UTC),
        )

    with psycopg.connect(migrated_settings.db_dsn()) as conn:
        repo = Repository(conn, schema=migrated_settings.db_schema)
        rows = repo.fetch_rates_series("DGS10", from_date=date(2026, 5, 1))

    assert len(rows) == 1
    assert rows[0]["value"] == Decimal("4.67")
