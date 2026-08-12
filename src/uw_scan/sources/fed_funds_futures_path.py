"""Fed funds futures implied policy path source.

Frenzy Capital publishes an SSR JSON snapshot of fed-funds-futures move
probabilities. We use it as a free/delayed alternative to the paid CME FedWatch
API and label it as third-party futures-derived data throughout the rates
dashboard.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

import httpx

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.normalize import NormalizationError
from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import status_family_for

logger = logging.getLogger(__name__)

PathStance = Literal["CUT", "HOLD", "HIKE", "UNKNOWN"]
PARSER_VERSION = "frenzy_fedwatch.v1"
SOURCE = "frenzy_capital"
_PROBABILITY_LABELS = {
    "cut_gt25": "Cut 50 bp",
    "cut_25": "Cut 25 bp",
    "hold": "Hold",
    "hike_25": "Hike 25 bp",
    "hike_gt25": "Hike 50 bp",
}


@dataclass(frozen=True)
class FedFundsFuturesPathPoint:
    meeting_date: date
    label: str
    probability: float
    stance: PathStance
    target_range: str | None
    implied_rate: Decimal | None = None
    probabilities: dict[str, Decimal] | None = None
    source: str = "Frenzy Capital Fed Watch"

    def to_payload(self) -> dict[str, object]:
        return {
            "meeting_date": self.meeting_date,
            "label": self.label,
            "probability": self.probability,
            "stance": self.stance,
            "target_range": self.target_range,
            "source": self.source,
            "status": "ok",
            "implied_rate": self.implied_rate,
            "probabilities": self.probabilities,
        }


@dataclass(frozen=True)
class FedFundsFuturesSourceBundle:
    artifact: MacroSourceArtifact

    @classmethod
    def from_bytes(
        cls,
        *,
        source_url: str,
        raw_bytes: bytes,
        retrieved_at: datetime,
    ) -> "FedFundsFuturesSourceBundle":
        content_hash, content_length = macro_artifact_content_identity(
            raw_bytes=raw_bytes
        )
        return cls(
            artifact=MacroSourceArtifact(
                source=SOURCE,
                source_kind="third_party_shadow",
                source_record_id=f"frenzy-fedwatch:{content_hash}",
                source_url=source_url,
                published_at=None,
                available_at=retrieved_at,
                retrieved_at=retrieved_at,
                last_seen_at=retrieved_at,
                content_hash=content_hash,
                parser_version=PARSER_VERSION,
                quality_status="partial",
                cost_class="free_third_party_shadow",
                media_type="text/html",
                content_length=content_length,
                raw_bytes=raw_bytes,
            )
        )


@dataclass(frozen=True)
class FedFundsFuturesSnapshot:
    source_url: str
    source_record_id: str
    available_at: datetime
    delay_status: Literal["unknown"]
    delay_minutes: None
    points: tuple[FedFundsFuturesPathPoint, ...]


RecordHook = Callable[["FedFundsFuturesPathProvider", ExternalApiRequestEvent], None]


class FedFundsFuturesPathProvider:
    BASE_URL = "https://www.frenzycap.com/fedwatch"
    PATH = ""
    PROVIDER = "frenzy_capital"
    ENDPOINT_KEY = "fed_funds_futures_path"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
        job_name: str | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._record_request_fn = record_request
        self._job_name = job_name

    def __enter__(self) -> "FedFundsFuturesPathProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_latest_path(
        self, *, current_target_range: str | None
    ) -> list[FedFundsFuturesPathPoint]:
        bundle = self.fetch_bundle(retrieved_at=datetime.now(UTC))
        return list(
            parse_fed_funds_futures_snapshot(
                bundle, current_target_range=current_target_range
            ).points
        )

    def fetch_bundle(
        self, *, retrieved_at: datetime | None = None
    ) -> FedFundsFuturesSourceBundle:
        response = self._get()
        response.raise_for_status()
        return FedFundsFuturesSourceBundle.from_bytes(
            source_url=str(response.request.url),
            raw_bytes=response.content,
            retrieved_at=retrieved_at or datetime.now(UTC),
        )

    def _get(self) -> httpx.Response:
        started_at = datetime.now(UTC)
        path = self.PATH
        try:
            response = self._client.get(f"{self._base_url}{path}")
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._event(
                    path,
                    started_at,
                    finished_at,
                    status_code=None,
                    error_message=str(exc),
                )
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._event(
                path,
                started_at,
                finished_at,
                status_code=response.status_code,
                error_message=None,
            )
        )
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("fed funds futures path telemetry %r", event)

    def _event(
        self,
        path: str,
        started_at: datetime,
        finished_at: datetime,
        *,
        status_code: int | None,
        error_message: str | None,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            method="GET",
            path=path,
            path_template=path,
            params={},
            status_code=status_code,
            status_family=status_family_for(
                status_code, transport_error=status_code is None
            ),
            latency_ms=max((finished_at - started_at).total_seconds() * 1000, 0),
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
            job_name=self._job_name,
        )


@dataclass(frozen=True)
class _ParsedPathRow:
    meeting_date: date
    implied_rate: Decimal | None
    raw_probabilities: dict[str, object]


class _FrenzyFedWatchParser:
    _DATA_RE = re.compile(r"window\.__SSR_DATA__\s*=\s*(\{.*?\});\s*</script>", re.S)

    def parse(self, html: str) -> list[_ParsedPathRow]:
        match = self._DATA_RE.search(html)
        if match is None:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise NormalizationError(
                "Frenzy Fed Watch SSR payload is not valid JSON"
            ) from exc

        raw_meetings = payload.get("meetings")
        if not isinstance(raw_meetings, list):
            raise NormalizationError("Frenzy meetings must be a list")
        rows: list[_ParsedPathRow] = []
        for index, item in enumerate(raw_meetings):
            if not isinstance(item, dict):
                raise NormalizationError(f"Frenzy meeting {index} must be an object")
            rows.append(_row_from_frenzy_meeting(item, index=index))
        return rows


def parse_fed_funds_futures_snapshot(
    bundle: FedFundsFuturesSourceBundle,
    *,
    current_target_range: str | None,
) -> FedFundsFuturesSnapshot:
    raw = bundle.artifact.raw_bytes
    if raw is None:
        raise NormalizationError("Frenzy artifact is missing raw HTML bytes")
    try:
        html = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise NormalizationError("Frenzy HTML is not valid UTF-8") from exc
    rows = _FrenzyFedWatchParser().parse(html)
    if not rows:
        raise NormalizationError(
            "Frenzy Fed Watch payload did not contain meeting rows"
        )
    current_range = _target_range(current_target_range)
    out: list[FedFundsFuturesPathPoint] = []
    for row in rows:
        probabilities = _validate_probability_distribution(
            row.raw_probabilities,
            meeting_date=row.meeting_date,
        )
        best = _best_probability_bucket(probabilities)
        if best is None:
            raise NormalizationError(
                f"Frenzy {row.meeting_date} probability distribution is empty"
            )
        if row.implied_rate is None or not row.implied_rate.is_finite():
            raise NormalizationError(
                f"Frenzy {row.meeting_date} implied rate must be finite"
            )
        total = sum(probabilities.values(), Decimal(0))
        if not Decimal("0.999") <= total <= Decimal("1.001"):
            raise NormalizationError(
                f"Frenzy {row.meeting_date} probability total {total} != 1"
            )
        stance, step_bps = _stance_and_step(best[0])
        out.append(
            FedFundsFuturesPathPoint(
                meeting_date=row.meeting_date,
                label=f"{row.meeting_date.month}/{row.meeting_date.day}",
                probability=round(float(best[1] * Decimal(100)), 1),
                stance=stance,
                target_range=_shift_target_range(current_range, step_bps),
                implied_rate=row.implied_rate,
                probabilities=probabilities,
            )
        )
    if not out:
        raise NormalizationError(
            "Frenzy Fed Watch payload did not contain complete probability rows"
        )
    return FedFundsFuturesSnapshot(
        source_url=bundle.artifact.source_url or "",
        source_record_id=bundle.artifact.source_record_id,
        available_at=bundle.artifact.available_at,
        delay_status="unknown",
        delay_minutes=None,
        points=tuple(out),
    )


def _row_from_frenzy_meeting(
    item: dict[str, object],
    *,
    index: int,
) -> _ParsedPathRow:
    raw_meeting = item.get("meeting_date")
    if not isinstance(raw_meeting, str):
        raise NormalizationError(f"Frenzy meeting {index} is missing meeting_date")
    try:
        meeting_date = date.fromisoformat(raw_meeting)
    except ValueError as exc:
        raise NormalizationError(
            f"Frenzy meeting {index} has invalid meeting_date"
        ) from exc

    raw_probabilities = item.get("probabilities")
    if not isinstance(raw_probabilities, dict):
        raise NormalizationError(
            f"Frenzy {meeting_date} probabilities must be an object"
        )
    return _ParsedPathRow(
        meeting_date=meeting_date,
        implied_rate=_parse_decimal(item.get("post_rate")),
        raw_probabilities=raw_probabilities,
    )


def _validate_probability_distribution(
    raw: dict[str, object],
    *,
    meeting_date: date,
) -> dict[str, Decimal]:
    keys = set(raw)
    expected = set(_PROBABILITY_LABELS)
    if keys != expected:
        missing = sorted(expected - keys)
        unknown = sorted(keys - expected)
        raise NormalizationError(
            f"Frenzy {meeting_date} probability keys changed; "
            f"missing={missing}, unknown={unknown}"
        )
    probabilities: dict[str, Decimal] = {}
    for key, label in _PROBABILITY_LABELS.items():
        probability = _parse_decimal(raw[key])
        if (
            probability is None
            or not probability.is_finite()
            or probability < 0
            or probability > 1
        ):
            raise NormalizationError(
                f"Frenzy {meeting_date} {key} probability must be finite "
                "and between 0 and 1"
            )
        probabilities[label] = probability
    return probabilities


def _parse_decimal(raw: object) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", raw.replace(",", ""))
        if match is None:
            return None
        raw = match.group(0)
    try:
        return Decimal(str(raw))
    except InvalidOperation as exc:
        logger.debug("skipping invalid Frenzy decimal value: %s", repr(exc))
        return None


def _best_probability_bucket(
    probabilities: dict[str, Decimal]
) -> tuple[str, Decimal] | None:
    if not probabilities:
        return None
    return max(probabilities.items(), key=lambda item: item[1])


def _stance_and_step(label: str) -> tuple[PathStance, Decimal]:
    if label == "Hold":
        return "HOLD", Decimal("0")
    match = re.fullmatch(r"(Cut|Hike)\s+(\d+)\s+bp", label)
    if match is None:
        return "UNKNOWN", Decimal("0")
    step = Decimal(match.group(2)) / Decimal(100)
    if match.group(1) == "Cut":
        return "CUT", -step
    return "HIKE", step


def _target_range(raw: str | None) -> tuple[Decimal, Decimal] | None:
    if raw is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", raw)
    if match is None:
        return None
    try:
        return Decimal(match.group(1)), Decimal(match.group(2))
    except InvalidOperation as exc:
        logger.debug("skipping invalid target range: %s", repr(exc))
        return None


def _shift_target_range(
    target_range: tuple[Decimal, Decimal] | None, step: Decimal
) -> str | None:
    if target_range is None:
        return None
    lower, upper = target_range
    return f"{lower + step:.2f}-{upper + step:.2f}%"
