"""US rates mirror ingestion and snapshot jobs."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

import psycopg

from uw_scan.rates.series import (
    CLEVELAND_FED_MODEL_SERIES,
    RATES_FRED_SERIES,
    YIELD_CURVE_SERIES,
)
from uw_scan.rates.snapshot import build_rates_snapshot
from uw_scan.sources.cme_fedwatch import CmeFedWatchProvider
from uw_scan.sources.cleveland_fed import ClevelandFedInflationProvider
from uw_scan.sources.fomc_calendar import FomcCalendarProvider
from uw_scan.sources.fred import FredProvider, RecordHook
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


class RatesFredProvider(Protocol):
    def __enter__(self) -> "RatesFredProvider": ...

    def __exit__(self, *_exc: object) -> object: ...

    def fetch_observations(
        self, series_id: str, *, start: date | None = None, end: date | None = None
    ): ...


RatesProviderFactory = Callable[..., RatesFredProvider]


class RatesClevelandFedProvider(Protocol):
    def __enter__(self) -> "RatesClevelandFedProvider": ...

    def __exit__(self, *_exc: object) -> object: ...

    def fetch_model_rows(self, *, start: date | None = None): ...


RatesClevelandProviderFactory = Callable[..., RatesClevelandFedProvider]


class RatesFomcProvider(Protocol):
    def __enter__(self) -> "RatesFomcProvider": ...

    def __exit__(self, *_exc: object) -> object: ...

    def fetch_meetings(self, *, years): ...


RatesFomcProviderFactory = Callable[..., RatesFomcProvider]


class RatesCmeProvider(Protocol):
    def __enter__(self) -> "RatesCmeProvider": ...

    def __exit__(self, *_exc: object) -> object: ...

    def fetch_latest_path(self, *, current_target_range: str | None): ...


RatesCmeProviderFactory = Callable[..., RatesCmeProvider]


@dataclass(frozen=True)
class RatesIngestResult:
    inserted_observations: int
    failed_series: list[str]
    snapshot_date: date
    computed_at: datetime


def rates_fred_ingest_job(
    *,
    dsn: str,
    fred_api_key: str | None,
    schema: str = "uw_scan",
    lookback_days: int = 45,
    record_request: RecordHook | None = None,
    provider_factory: RatesProviderFactory = FredProvider,
    cleveland_provider_factory: RatesClevelandProviderFactory = (
        ClevelandFedInflationProvider
    ),
    fomc_provider_factory: RatesFomcProviderFactory = FomcCalendarProvider,
    cme_provider_factory: RatesCmeProviderFactory = CmeFedWatchProvider,
    cme_fedwatch_api_token: str | None = None,
    cme_application_name: str = "uw-scan",
    computed_at: datetime | None = None,
) -> RatesIngestResult:
    if not fred_api_key:
        raise RuntimeError("FRED_API_KEY is required for rates_fred_ingest")

    now = computed_at or datetime.now(UTC)
    start = _history_start_for_snapshot(now.date(), lookback_days=lookback_days)
    failed: list[str] = []
    inserted = 0

    with psycopg.connect(dsn) as conn:
        repo = Repository(conn, schema=schema)
        with provider_factory(
            api_key=fred_api_key,
            record_request=record_request,
            job_name="rates_fred_ingest",
        ) as fred:
            for series_id in RATES_FRED_SERIES:
                try:
                    observations = fred.fetch_observations(series_id, start=start)
                    rows = [
                        {
                            "series_id": obs.series_id,
                            "obs_date": obs.obs_date,
                            "value": obs.value,
                            "realtime_start": obs.realtime_start or obs.obs_date,
                            "realtime_end": obs.realtime_end or obs.obs_date,
                            "release_date": None,
                            "source_url": None,
                        }
                        for obs in observations
                    ]
                    inserted += repo.upsert_rates_observation_rows(
                        rows, seen_at=now, source="FRED"
                    )
                except Exception as exc:
                    failed.append(series_id)
                    logger.exception(
                        "rates_fred_ingest: series=%s failed: %r", series_id, exc
                    )
        try:
            with cleveland_provider_factory(
                record_request=record_request,
                job_name="rates_cleveland_fed_ingest",
            ) as cleveland:
                model_rows = cleveland.fetch_model_rows(start=start)
                rows = [
                    row
                    for record in model_rows
                    for row in record.to_observation_rows()
                ]
                inserted += repo.upsert_rates_observation_rows(
                    rows, seen_at=now, source="CLEVELAND_FED"
                )
        except Exception as exc:
            failed.extend(CLEVELAND_FED_MODEL_SERIES)
            logger.exception("rates_cleveland_fed_ingest failed: %r", exc)

        conn.commit()
        _raise_if_required_curve_failed(failed)
        observations_by_series = {
            series_id: repo.fetch_rates_series(series_id, from_date=start)
            for series_id in (*RATES_FRED_SERIES, *CLEVELAND_FED_MODEL_SERIES)
        }
        policy_events: list[dict[str, Any]] = []
        try:
            with fomc_provider_factory() as fomc:
                policy_events = [
                    _to_payload(row)
                    for row in fomc.fetch_meetings(
                        years=(now.year - 1, now.year, now.year + 1)
                    )
                ]
                inserted += repo.upsert_rates_policy_events(
                    policy_events, seen_at=now, source="FED_FOMC"
                )
        except Exception as exc:
            failed.append("FED_FOMC")
            logger.exception("rates_fomc_calendar_ingest failed: %r", exc)

        policy_path: list[dict[str, Any]] = []
        if cme_fedwatch_api_token:
            try:
                with cme_provider_factory(
                    api_token=cme_fedwatch_api_token,
                    application_name=cme_application_name,
                ) as cme:
                    path_rows = cme.fetch_latest_path(
                        current_target_range=_target_range_from_observations(
                            observations_by_series, now.date()
                        )
                    )
                    policy_path = [_to_payload(row) for row in path_rows]
                    inserted += repo.upsert_rates_policy_path(
                        policy_path,
                        snapshot_date=now.date(),
                        seen_at=now,
                        source="CME_FEDWATCH",
                    )
            except Exception as exc:
                failed.append("CME_FEDWATCH")
                logger.exception("rates_cme_fedwatch_ingest failed: %r", exc)

        policy_events = repo.fetch_rates_policy_events(
            from_date=date(now.year - 1, 1, 1), to_date=date(now.year + 1, 12, 31)
        )
        policy_path = repo.fetch_latest_rates_policy_path()
        snapshot = build_rates_snapshot(
            observations_by_series,
            computed_at=now,
            failed_series=set(failed),
            policy_events=policy_events,
            policy_path=policy_path,
        )
        payload = snapshot.model_dump(mode="json")
        repo.insert_rates_snapshot(
            snapshot_date=snapshot.as_of,
            computed_at=snapshot.computed_at,
            payload=payload,
            source_freshness=payload["source_freshness"],
        )
        conn.commit()

    return RatesIngestResult(
        inserted_observations=inserted,
        failed_series=failed,
        snapshot_date=snapshot.as_of,
        computed_at=snapshot.computed_at,
    )


def _history_start_for_snapshot(as_of: date, *, lookback_days: int) -> date:
    year_start_buffer = date(as_of.year, 1, 1) - timedelta(days=14)
    lookback_start = as_of - timedelta(days=lookback_days)
    return min(lookback_start, year_start_buffer)


def _raise_if_required_curve_failed(failed_series: list[str]) -> None:
    failed_curve = sorted(set(failed_series) & set(YIELD_CURVE_SERIES.values()))
    if not failed_curve:
        return
    raise RuntimeError(
        "required FRED Treasury curve series failed; refusing to publish rates "
        f"snapshot: {', '.join(failed_curve)}"
    )


def _to_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    to_payload = getattr(row, "to_payload", None)
    if callable(to_payload):
        return to_payload()
    raise TypeError(f"unsupported rates policy source row: {type(row)!r}")


def _target_range_from_observations(
    observations: dict[str, list[dict[str, Any]]], as_of: date
) -> str | None:
    lower = _latest_decimal(observations, "DFEDTARL", as_of)
    upper = _latest_decimal(observations, "DFEDTARU", as_of)
    if lower is None or upper is None:
        return None
    return f"{lower:.2f}-{upper:.2f}%"


def _latest_decimal(
    observations: dict[str, list[dict[str, Any]]], series_id: str, as_of: date
) -> Decimal | None:
    rows = [row for row in observations.get(series_id, []) if row["obs_date"] <= as_of]
    if not rows:
        return None
    value = max(rows, key=lambda row: row["obs_date"])["value"]
    return value if isinstance(value, Decimal) else Decimal(str(value))
