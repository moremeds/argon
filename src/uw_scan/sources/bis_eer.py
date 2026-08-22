"""BIS effective exchange rates -- the USD anchor's independent cross-check.

Source: https://stats.bis.org/api/v2, dataflow ``BIS/WS_EER``, key ``D.N.B.US``.
Verdict: ``docs/research/2026-08-12-usd-source-probe/VERDICT.md``.

**This module cannot produce evidence, and that is deliberate.**  A BIS SDMX data message
carries no real-time dimension, so there is no vintage to select: it can corroborate
today's level and can never answer what the level was believed to be on a past date.  A
domain whose whole premise is replay cannot rest on that.  So the parser returns
``BisEerReading`` -- a plain cross-check reading with no ``available_at``, no vintage hash
and no artifact -- rather than anything the evidence store would accept.  The type is the
enforcement; a comment would not survive the first person in a hurry.

Two traps this client exists to not fall into:

* **A bare request succeeds and returns XML.**  BIS content-negotiates on ``Accept`` alone
  and the status code does not say whether you got what you asked for.  Measured:

  =============================  ======  ==================
  request                        status  media type
  =============================  ======  ==================
  no Accept, no format           200     application/xml
  Accept: ...sdmx.data+json...   200     application/json
  format=jsondata, no Accept     406     application/xml
  =============================  ======  ==================

  A client that forgets the header gets HTTP 200 and hands SDMX-ML to a JSON parser, so
  ``raise_for_status`` is not the check.  The media type is.

* **Non-trading days come back as the string ``NaN``.**  That is an absence.  Coercing it
  to zero would report the dollar as having no value on a bank holiday.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import httpx

logger = logging.getLogger(__name__)

SOURCE: Final = "bis"
PARSER_VERSION: Final = "bis_eer/1"

BASE_URL: Final = "https://stats.bis.org/api/v2"
#: Daily, nominal, broad basket, United States.  Frequency.Type.Basket.Reference-area.
US_NOMINAL_BROAD_DAILY: Final = "D.N.B.US"
DATAFLOW: Final = "BIS/WS_EER/1.0"

#: The header that selects JSON.  Load-bearing -- see the module docstring.
SDMX_JSON_ACCEPT: Final = "application/vnd.sdmx.data+json;version=1.0.0"
JSON_MEDIA_TYPE: Final = "application/json"

#: The publisher's own absence marker for a non-trading day.
NOT_TRADED: Final = "NaN"


class BisEerError(RuntimeError):
    """The cross-check could not be read. Never silently a missing cross-check."""


@dataclass(frozen=True)
class BisEerReading:
    """One BIS effective-exchange-rate level.

    Deliberately NOT a ``MacroObservation``: no ``available_at``, no vintage, no artifact.
    BIS publishes no record of its own past beliefs, so a reading here is only ever
    "what BIS says the level is now", and nothing in this dataclass can be promoted into
    a point-in-time evidence row by a caller who was not paying attention.
    """

    #: The observation period the level belongs to.
    period: date
    #: ``None`` on a non-trading day. Never zero.
    value: Decimal | None
    series_key: str
    #: Constant, and repeated on every row so it travels with the data rather than
    #: living in a docstring the caller did not read.
    vintage_bearing: bool = False


class BisEerProvider:
    DEFAULT_TIMEOUT_S: Final = 60.0

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.Client | None = None,
    ) -> None:
        # trust_env=False: httpx otherwise falls through to getproxies(), which on macOS
        # reads the system network pane. Four rates clients inherited ambient proxy
        # config and froze every native run while the Linux container was immune -- so a
        # green production deploy is not evidence the call is safe.
        self._client = client or httpx.Client(
            base_url=base_url,
            timeout=timeout_s,
            trust_env=False,
            follow_redirects=True,
            headers={"Accept": SDMX_JSON_ACCEPT},
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "BisEerProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_us_broad_nominal(self, *, last_n: int = 10) -> list[BisEerReading]:
        """The most recent US nominal broad effective-exchange-rate levels."""
        path = f"/data/dataflow/{DATAFLOW}/{US_NOMINAL_BROAD_DAILY}"
        try:
            response = self._client.get(
                path,
                params={"lastNObservations": str(last_n)},
                headers={"Accept": SDMX_JSON_ACCEPT},
            )
        except httpx.HTTPError as exc:
            raise BisEerError(f"BIS EER transport failure: {exc!r}") from exc
        return parse_eer(
            status_code=response.status_code,
            media_type=response.headers.get("content-type", ""),
            body=response.content,
        )


def parse_eer(*, status_code: int, media_type: str, body: bytes) -> list[BisEerReading]:
    """Normalize one SDMX-JSON data message.

    Split out from the fetch so the content-negotiation trap is testable without a
    network round trip -- the 200-that-is-XML case is the whole reason this module has a
    parser of its own.
    """
    if status_code != 200:
        raise BisEerError(f"BIS EER returned HTTP {status_code}")
    if media_type.split(";")[0].strip() != JSON_MEDIA_TYPE:
        raise BisEerError(
            f"BIS EER returned HTTP 200 with media type {media_type!r}. A bare request "
            "content-negotiates to SDMX-ML, so a 200 is not by itself a success: the "
            f"{SDMX_JSON_ACCEPT!r} Accept header is what selects JSON"
        )
    try:
        payload: Any = json.loads(body)
    except ValueError as exc:
        raise BisEerError(f"BIS EER body is not JSON: {exc!r}") from exc

    try:
        data = payload["data"]
        datasets = data["dataSets"]
        structure = data["structure"]
    except (KeyError, TypeError) as exc:
        raise BisEerError(
            f"BIS EER body is JSON but not an SDMX data message: missing {exc!r}"
        ) from exc

    if not datasets:
        # A published-nothing answer, distinct from a transport or negotiation failure.
        return []
    series_map = datasets[0].get("series") or {}
    if not series_map:
        return []

    periods = [
        value["id"] for value in structure["dimensions"]["observation"][0]["values"]
    ]
    out: list[BisEerReading] = []
    for series_key, series in series_map.items():
        for index, point in (series.get("observations") or {}).items():
            try:
                period = periods[int(index)]
            except (IndexError, ValueError) as exc:
                raise BisEerError(
                    f"BIS EER observation index {index!r} has no matching period"
                ) from exc
            out.append(
                BisEerReading(
                    period=_period(period),
                    value=_value(point[0] if point else None),
                    series_key=series_key,
                )
            )
    return sorted(out, key=lambda row: (row.series_key, row.period))


def _period(raw: str) -> date:
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC).date()
    except ValueError as exc:
        raise BisEerError(f"BIS EER period {raw!r} is not a date") from exc


def _value(raw: object) -> Decimal | None:
    # NaN is the publisher saying the market was closed. It is an absence, and the one
    # thing it must never become is a number.
    if raw is None or raw == NOT_TRADED:
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise BisEerError(f"BIS EER value {raw!r} is not numeric") from exc
