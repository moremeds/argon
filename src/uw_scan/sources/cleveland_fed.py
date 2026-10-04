"""Federal Reserve Bank of Cleveland inflation expectations model source."""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.rates.series import (
    CLEVE_EXPECTED_INFLATION_10Y,
    CLEVE_INFLATION_RISK_PREMIUM_10Y,
    CLEVE_MODEL_REAL_YIELD_10Y,
    CLEVE_REAL_RISK_PREMIUM_10Y,
)
from uw_scan.sources._http import (
    RequestOutcome,
    get_with_telemetry,
    record_or_log,
    request_event,
)
from uw_scan.storage.provider_usage import ExternalApiRequestEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClevelandFedInflationRecord:
    obs_date: date
    expected_inflation_10y: Decimal
    real_risk_premium_10y: Decimal
    inflation_risk_premium_10y: Decimal
    model_real_yield_10y: Decimal

    def to_observation_rows(self) -> list[dict[str, Any]]:
        common = {
            "obs_date": self.obs_date,
            "realtime_start": self.obs_date,
            "realtime_end": self.obs_date,
            "release_date": self.obs_date,
            "source_url": ClevelandFedInflationProvider.LANDING_URL,
        }
        return [
            {
                **common,
                "series_id": CLEVE_EXPECTED_INFLATION_10Y,
                "value": self.expected_inflation_10y,
            },
            {
                **common,
                "series_id": CLEVE_REAL_RISK_PREMIUM_10Y,
                "value": self.real_risk_premium_10y,
            },
            {
                **common,
                "series_id": CLEVE_INFLATION_RISK_PREMIUM_10Y,
                "value": self.inflation_risk_premium_10y,
            },
            {
                **common,
                "series_id": CLEVE_MODEL_REAL_YIELD_10Y,
                "value": self.model_real_yield_10y,
            },
        ]


RecordHook = Callable[["ClevelandFedInflationProvider", ExternalApiRequestEvent], None]


class ClevelandFedInflationProvider:
    """Fetch Cleveland Fed's official model output CSVs.

    Chart 1 provides expected inflation plus real/inflation risk premia. Chart 2
    provides the model real 10Y yield. We combine them into the Clarida-style
    four-factor split used by the rates page.
    """

    BASE_URL = "https://www.clevelandfed.org"
    LANDING_URL = f"{BASE_URL}/indicators-and-data/inflation-expectations"
    CHART1_PATH = (
        "/-/media/files/webcharts/inflationexpectations/"
        "inflationexpectations_chart1.csv"
    )
    CHART2_PATH = (
        "/-/media/files/webcharts/inflationexpectations/"
        "inflationexpectations_chart2.csv"
    )
    PROVIDER = "cleveland_fed"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
        job_name: str | None = None,
        trust_env: bool = False,
    ):
        self._base_url = base_url.rstrip("/")
        # Ambient proxy config is not inherited -- see sources/fred.py for the
        # failure this prevents: httpx reads a macOS system HTTPS proxy even with
        # the *_PROXY environment variables unset, and the TLS handshake to this
        # publisher then dies with SSL: UNEXPECTED_EOF_WHILE_READING.
        self._client = httpx.Client(timeout=timeout_s, trust_env=trust_env)
        self._record_request_fn = record_request
        self._job_name = job_name

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ClevelandFedInflationProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_model_rows(
        self, *, start: date | None = None
    ) -> list[ClevelandFedInflationRecord]:
        chart1 = self._fetch_chart1()
        chart2 = self._fetch_chart2()
        out: list[ClevelandFedInflationRecord] = []
        for obs_date, risk_row in chart1.items():
            if start is not None and obs_date < start:
                continue
            model_real = chart2.get(obs_date)
            if model_real is None:
                continue
            out.append(
                ClevelandFedInflationRecord(
                    obs_date=obs_date,
                    expected_inflation_10y=risk_row["expected_inflation_10y"],
                    real_risk_premium_10y=risk_row["real_risk_premium_10y"],
                    inflation_risk_premium_10y=risk_row["inflation_risk_premium_10y"],
                    model_real_yield_10y=model_real,
                )
            )
        return sorted(out, key=lambda row: row.obs_date)

    def _fetch_chart1(self) -> dict[date, dict[str, Decimal]]:
        response = self._get_with_telemetry(self.CHART1_PATH, {"sc_lang": "en"})
        response.raise_for_status()
        out: dict[date, dict[str, Decimal]] = {}
        for row in csv.DictReader(io.StringIO(response.text)):
            try:
                obs_date = date.fromisoformat(row["date"].strip())
                out[obs_date] = {
                    "expected_inflation_10y": Decimal(row["expected_inflation"]),
                    "real_risk_premium_10y": Decimal(row["real_risk_premium"]),
                    "inflation_risk_premium_10y": Decimal(
                        row["inflation_risk_premium"]
                    ),
                }
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.warning("cleveland_fed: skip chart1 row %r (%s)", row, repr(exc))
        return out

    def _fetch_chart2(self) -> dict[date, Decimal]:
        response = self._get_with_telemetry(self.CHART2_PATH, {"sc_lang": "en"})
        response.raise_for_status()
        out: dict[date, Decimal] = {}
        for row in csv.DictReader(io.StringIO(response.text)):
            try:
                out[date.fromisoformat(row["date"].strip())] = Decimal(
                    row["model_yield"]
                )
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.warning("cleveland_fed: skip chart2 row %r (%s)", row, repr(exc))
        return out

    def _get_with_telemetry(self, path: str, params: dict[str, Any]) -> httpx.Response:
        def record(outcome: RequestOutcome) -> None:
            event = request_event(
                outcome,
                provider=self.PROVIDER,
                endpoint_key="inflation_expectations_csv",
                path=path,
                params=params,
                job_name=self._job_name,
            )
            record_or_log(self._record_request_fn, self, event, "cleveland_fed")

        return get_with_telemetry(
            self._client,
            f"{self._base_url}{path}",
            params=params,
            record=record,
            transport_error_text=str,
            error_body_text=lambda _response: None,
        )
