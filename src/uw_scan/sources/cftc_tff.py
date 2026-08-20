"""CFTC Traders in Financial Futures for Treasury futures positioning."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)

CFTC_TFF_FUTURES_ONLY_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CFTC_TFF_TREASURY_SUBGROUP = "Interest Rates - U.S. Treasury"

TREASURY_TFF_CONTRACTS: dict[str, str] = {
    "042601": "2Y",
    "044601": "5Y",
    "043602": "10Y",
    "043607": "Ultra 10Y",
    "020601": "Bond",
    "020604": "Ultra Bond",
    "04360Y": "Micro 10Y Yield",
    "045L2T": "Treasury Repo",
}


@dataclass(frozen=True)
class CftcTffTreasuryRow:
    contract_code: str
    contract_name: str
    commodity_name: str | None
    tenor_bucket: str
    obs_date: date
    release_date: date
    open_interest: Decimal | None
    dealer_long: Decimal | None
    dealer_short: Decimal | None
    dealer_net: Decimal | None
    asset_mgr_long: Decimal | None
    asset_mgr_short: Decimal | None
    asset_mgr_net: Decimal | None
    lev_money_long: Decimal | None
    lev_money_short: Decimal | None
    lev_money_net: Decimal | None
    other_rept_long: Decimal | None
    other_rept_short: Decimal | None
    other_rept_net: Decimal | None
    dealer_net_pct_oi: Decimal | None
    asset_mgr_net_pct_oi: Decimal | None
    lev_money_net_pct_oi: Decimal | None


RecordHook = Callable[["CftcTffProvider", ExternalApiRequestEvent], None]


class CftcTffProvider:
    URL = CFTC_TFF_FUTURES_ONLY_URL
    ENDPOINT_PATH = "/resource/gpe5-46if.json"
    ENDPOINT_KEY = "cftc_tff_futures_only"
    PROVIDER = "cftc_tff"

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
        job_name: str | None = None,
        trust_env: bool = False,
    ):
        # Ambient proxy config is not inherited -- see sources/fred.py for the
        # failure this prevents: httpx reads a macOS system HTTPS proxy even with
        # the *_PROXY environment variables unset, and the TLS handshake to this
        # publisher then dies with SSL: UNEXPECTED_EOF_WHILE_READING.
        self._client = httpx.Client(timeout=timeout_s, trust_env=trust_env)
        self._record_request_fn = record_request
        self._job_name = job_name

    def __enter__(self) -> "CftcTffProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_treasury_rows(
        self, *, start: date | None = None
    ) -> list[CftcTffTreasuryRow]:
        clauses = [
            f'commodity_subgroup_name="{CFTC_TFF_TREASURY_SUBGROUP}"',
            "futonly_or_combined=\"FutOnly\"",
        ]
        if start is not None:
            clauses.append(
                f'report_date_as_yyyy_mm_dd >= "{start.isoformat()}T00:00:00"'
            )
        params = {
            "$where": " AND ".join(clauses),
            "$order": "report_date_as_yyyy_mm_dd ASC, contract_market_name ASC",
            "$limit": "50000",
        }
        response = self._get_with_telemetry(self.URL, params)
        response.raise_for_status()
        out: list[CftcTffTreasuryRow] = []
        for row in json.loads(response.text):
            try:
                parsed = _row_from_mapping(row)
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.debug("cftc tff row parse skipped: %s", repr(exc))
                continue
            if parsed.contract_code not in TREASURY_TFF_CONTRACTS:
                continue
            out.append(parsed)
        return out

    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._build_event(
                    started_at,
                    finished_at,
                    params,
                    status_code=None,
                    error_message=repr(exc)[:1000],
                )
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._build_event(
                started_at,
                finished_at,
                params,
                status_code=response.status_code,
                error_message=(
                    response.text[:1000] if response.status_code >= 400 else None
                ),
            )
        )
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("cftc_tff telemetry %r", event)

    def _build_event(
        self,
        started_at: datetime,
        finished_at: datetime,
        params: dict[str, Any],
        *,
        status_code: int | None,
        error_message: str | None,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            method="GET",
            path=self.ENDPOINT_PATH,
            path_template=self.ENDPOINT_PATH,
            params=redact_params(params),
            status_code=status_code,
            status_family=status_family_for(
                status_code, transport_error=status_code is None
            ),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            error_message=error_message,
            job_name=self._job_name,
        )


def _row_from_mapping(row: dict[str, Any]) -> CftcTffTreasuryRow:
    contract_code = _field(row, "cftc_contract_market_code")
    obs = _obs_date(row)
    dealer_long = _dec(_field(row, "dealer_positions_long_all"))
    dealer_short = _dec(_field(row, "dealer_positions_short_all"))
    asset_mgr_long = _dec(_field(row, "asset_mgr_positions_long"))
    asset_mgr_short = _dec(_field(row, "asset_mgr_positions_short"))
    lev_long = _dec(_field(row, "lev_money_positions_long"))
    lev_short = _dec(_field(row, "lev_money_positions_short"))
    other_long = _dec(_field(row, "other_rept_positions_long"))
    other_short = _dec(_field(row, "other_rept_positions_short"))
    open_interest = _dec(_field(row, "open_interest_all"))
    dealer_net = _net(dealer_long, dealer_short)
    asset_mgr_net = _net(asset_mgr_long, asset_mgr_short)
    lev_net = _net(lev_long, lev_short)
    return CftcTffTreasuryRow(
        contract_code=contract_code,
        contract_name=_field(row, "contract_market_name"),
        commodity_name=_field(row, "commodity_name") or None,
        tenor_bucket=TREASURY_TFF_CONTRACTS.get(contract_code, "Other Treasury"),
        obs_date=obs,
        release_date=obs + timedelta(days=3),
        open_interest=open_interest,
        dealer_long=dealer_long,
        dealer_short=dealer_short,
        dealer_net=dealer_net,
        asset_mgr_long=asset_mgr_long,
        asset_mgr_short=asset_mgr_short,
        asset_mgr_net=asset_mgr_net,
        lev_money_long=lev_long,
        lev_money_short=lev_short,
        lev_money_net=lev_net,
        other_rept_long=other_long,
        other_rept_short=other_short,
        other_rept_net=_net(other_long, other_short),
        dealer_net_pct_oi=_pct_oi(dealer_net, open_interest),
        asset_mgr_net_pct_oi=_pct_oi(asset_mgr_net, open_interest),
        lev_money_net_pct_oi=_pct_oi(lev_net, open_interest),
    )


def _field(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if value is None:
        return ""
    return str(value).strip()


def _obs_date(row: dict[str, Any]) -> date:
    raw = _field(row, "report_date_as_yyyy_mm_dd")
    return date.fromisoformat(raw[:10])


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return Decimal(str(raw).replace(",", "").strip())


def _net(long: Decimal | None, short: Decimal | None) -> Decimal | None:
    if long is None or short is None:
        return None
    return long - short


def _pct_oi(value: Decimal | None, open_interest: Decimal | None) -> Decimal | None:
    if value is None or open_interest in (None, Decimal("0")):
        return None
    return (value / open_interest * Decimal("100")).quantize(Decimal("0.1"))
