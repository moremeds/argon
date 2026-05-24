"""Official Treasury supply sources for rates dashboard."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)

TREASURY_AUCTIONS_URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"
TREASURY_AUCTION_RESULTS_BASE = (
    "https://fiscaldata.treasury.gov/static-data/published-reports/"
    "auctions-query/results/"
)
FISCALDATA_DEBT_TO_PENNY_URL = (
    "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/"
    "accounting/od/debt_to_penny"
)


@dataclass(frozen=True)
class TreasuryAuctionRow:
    cusip: str
    security_type: str
    security_term: str
    auction_date: date
    issue_date: date | None
    offering_amount: Decimal | None
    high_rate: Decimal | None
    bid_to_cover: Decimal | None
    direct_bidder_pct: Decimal | None
    indirect_bidder_pct: Decimal | None
    primary_dealer_pct: Decimal | None
    tail_indicator: str
    source_url: str | None


@dataclass(frozen=True)
class TreasuryDebtRecord:
    record_date: date
    debt_held_public: Decimal | None
    intragov_holdings: Decimal | None
    total_public_debt: Decimal | None
    source_url: str


RecordHook = Callable[["TreasurySupplyProvider", ExternalApiRequestEvent], None]


class TreasurySupplyProvider:
    AUCTIONS_URL = TREASURY_AUCTIONS_URL
    DEBT_TO_PENNY_URL = FISCALDATA_DEBT_TO_PENNY_URL
    PROVIDER = "treasury_supply"

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
        job_name: str | None = None,
    ):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request
        self._job_name = job_name

    def __enter__(self) -> "TreasurySupplyProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_recent_auctions(
        self, *, start: date | None = None
    ) -> list[TreasuryAuctionRow]:
        params = {"format": "json"}
        response = self._get_with_telemetry(self.AUCTIONS_URL, params)
        response.raise_for_status()
        rows: list[TreasuryAuctionRow] = []
        for raw in json.loads(response.text):
            try:
                parsed = _auction_from_mapping(raw)
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.debug("treasury auction row parse skipped: %s", repr(exc))
                continue
            if start is not None and parsed.auction_date < start:
                continue
            if parsed.security_type not in {"Bill", "Note", "Bond"}:
                continue
            rows.append(parsed)
        return rows

    def fetch_latest_debt(self) -> TreasuryDebtRecord | None:
        params = {"sort": "-record_date", "page[size]": "1"}
        response = self._get_with_telemetry(self.DEBT_TO_PENNY_URL, params)
        response.raise_for_status()
        data = json.loads(response.text).get("data", [])
        if not data:
            return None
        return _debt_from_mapping(data[0])

    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._build_event(
                    url,
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
                url,
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
            logger.debug("treasury_supply telemetry %r", event)

    def _build_event(
        self,
        url: str,
        started_at: datetime,
        finished_at: datetime,
        params: dict[str, Any],
        *,
        status_code: int | None,
        error_message: str | None,
    ) -> ExternalApiRequestEvent:
        path = _path_for_url(url)
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=_endpoint_key_for_url(url),
            method="GET",
            path=path,
            path_template=path,
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


def _auction_from_mapping(row: dict[str, Any]) -> TreasuryAuctionRow:
    high_rate = _dec(_field(row, "highYield")) or _dec(_field(row, "highDiscountRate"))
    total_accepted = _dec(_field(row, "totalAccepted"))
    return TreasuryAuctionRow(
        cusip=_field(row, "cusip"),
        security_type=_field(row, "securityType"),
        security_term=_field(row, "securityTerm"),
        auction_date=_parse_date(_field(row, "auctionDate")),
        issue_date=_parse_optional_date(_field(row, "issueDate")),
        offering_amount=_dec(_field(row, "offeringAmount")),
        high_rate=high_rate,
        bid_to_cover=_dec(_field(row, "bidToCoverRatio")),
        direct_bidder_pct=_pct(_dec(_field(row, "directBidderAccepted")), total_accepted),
        indirect_bidder_pct=_pct(
            _dec(_field(row, "indirectBidderAccepted")), total_accepted
        ),
        primary_dealer_pct=_pct(
            _dec(_field(row, "primaryDealerAccepted")), total_accepted
        ),
        tail_indicator=_tail_indicator(_field(row, "securityTerm")),
        source_url=_auction_result_url(_field(row, "pdfFilenameCompetitiveResults")),
    )


def _debt_from_mapping(row: dict[str, Any]) -> TreasuryDebtRecord:
    return TreasuryDebtRecord(
        record_date=_parse_date(_field(row, "record_date")),
        debt_held_public=_dec(_field(row, "debt_held_public_amt")),
        intragov_holdings=_dec(_field(row, "intragov_hold_amt")),
        total_public_debt=_dec(_field(row, "tot_pub_debt_out_amt")),
        source_url=FISCALDATA_DEBT_TO_PENNY_URL,
    )


def _field(row: dict[str, Any], name: str) -> str:
    value = row.get(name)
    if value is None:
        return ""
    return str(value).strip()


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw[:10])


def _parse_optional_date(raw: str) -> date | None:
    if not raw:
        return None
    return _parse_date(raw)


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    return Decimal(str(raw).replace(",", "").strip())


def _pct(value: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if value is None or denominator in (None, Decimal("0")):
        return None
    return (value / denominator * Decimal("100")).quantize(Decimal("0.1"))


def _tail_indicator(term: str) -> str:
    lower = term.lower()
    if "week" in lower or "day" in lower or "year" not in lower:
        return "bill"
    year_match = re.search(r"(\d+)-year", lower)
    if year_match is None:
        return "other"
    years = int(year_match.group(1))
    if years >= 20:
        return "long-end"
    if years >= 7:
        return "belly"
    if years >= 2:
        return "front-end"
    return "other"


def _auction_result_url(filename: str) -> str | None:
    if not filename:
        return None
    return f"{TREASURY_AUCTION_RESULTS_BASE}{filename}"


def _path_for_url(url: str) -> str:
    if "treasurydirect.gov" in url:
        return "/TA_WS/securities/auctioned"
    return "/services/api/fiscal_service/v2/accounting/od/debt_to_penny"


def _endpoint_key_for_url(url: str) -> str:
    if "treasurydirect.gov" in url:
        return "treasury_direct_auctioned"
    return "fiscaldata_debt_to_penny"
