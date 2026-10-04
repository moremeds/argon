"""SEC EDGAR submissions — the only source that dates a filing rather than a fetch.

Every other availability signal Argon holds answers "when did WE first see this
content". SEC answers "when did the world see it", which is the one question a
leak-free replay needs. Free, keyless, and outside every provider budget.

THREE THINGS THAT WILL BITE
---------------------------
1. `filings.recent` is a WINDOW, not the history. Older filings live in
   `filings.files[]` as separate archive documents. NVDA's `recent` block holds
   1,010 rows of every form type; following the archives yields 111 *periodic*
   filings spanning 2006 to 2026. Read only `recent` and a 20-year panel
   silently becomes a 3-year one — with no error to notice.
2. The macOS system proxy kills this host. With `HTTPS_PROXY` set,
   `www.sec.gov` fails `SSL_ERROR_SYSCALL`; bypassed, it returns 200. Same
   class of failure as `MassiveWsClient` passing `proxy=None`, and the reason
   `sec_client` hard-codes `trust_env=False` rather than leaving it to a caller.
3. A descriptive `User-Agent` carrying a contact address is REQUIRED. Without
   one SEC returns 403 for every request, including the ticker map.

Rate limit is 10 requests/second. `sec_client` does not enforce it; callers
space their own requests (the refresh job sleeps between tickers).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from typing import Any

import httpx

from uw_scan.models.sec import SecFiling
from uw_scan.sources.source_errors import SourceUnavailable

logger = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://data.sec.gov/submissions/{name}"

#: Periodic reports only. An 8-K announces, a Form 4 reports ownership; neither
#: publishes the statements Argon stores, so neither can date one.
SEC_FORMS = frozenset({"10-Q", "10-K", "20-F", "40-F"})


def _parse_date(value: Any) -> date | None:
    if not value or not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        _ = repr(exc)  # CI Guardrail 2: unparseable date -> drop, never guess
        return None


def _rows(block: Any) -> list[SecFiling]:
    """One parallel-array block (`recent`, or an archive document) -> filings."""
    if not isinstance(block, dict):
        return []
    accessions = block.get("accessionNumber") or []
    forms = block.get("form") or []
    report_dates = block.get("reportDate") or []
    filing_dates = block.get("filingDate") or []
    n = min(len(accessions), len(forms), len(report_dates), len(filing_dates))

    out: list[SecFiling] = []
    for i in range(n):
        form = str(forms[i]).strip()
        # An amendment is the base form plus "/A". Both must survive parsing:
        # the amendment is not evidence of publication, it is evidence that this
        # period's content cannot be dated at all.
        base = form[:-2] if form.endswith("/A") else form
        if base not in SEC_FORMS:
            continue
        report = _parse_date(report_dates[i])
        filed = _parse_date(filing_dates[i])
        if report is None or filed is None:
            continue
        out.append(
            SecFiling(
                accession=str(accessions[i]).strip(),
                form=form,
                report_date=report,
                filing_date=filed,
                is_amendment=form.endswith("/A"),
            )
        )
    return out


def parse_submissions(payload: Any) -> list[SecFiling]:
    """Parse a submissions document's `filings.recent` block. Never raises."""
    if not isinstance(payload, dict):
        return []
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return []
    return _rows(filings.get("recent"))


def parse_archive(payload: Any) -> list[SecFiling]:
    """Parse an archive document, which is the bare parallel-array block."""
    return _rows(payload)


def archive_names(payload: Any) -> list[str]:
    """The `filings.files[].name` documents holding everything before `recent`."""
    if not isinstance(payload, dict):
        return []
    filings = payload.get("filings")
    if not isinstance(filings, dict):
        return []
    files = filings.get("files")
    if not isinstance(files, list):
        return []
    return [str(f["name"]) for f in files if isinstance(f, dict) and f.get("name")]


def sec_client(user_agent: str, timeout: float = 30.0) -> httpx.Client:
    """An httpx client that can actually reach SEC.

    `trust_env=False` is not a preference. See this module's docstring: with the
    macOS proxy pane populated, every request to `www.sec.gov` dies in the TLS
    handshake, and the failure looks like an outage rather than a config.
    """
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "SEC requires a descriptive User-Agent carrying a contact email; "
            f"got {user_agent!r}. Without one every request returns 403."
        )
    return httpx.Client(
        trust_env=False,
        timeout=timeout,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )


def _get_json(client: httpx.Client, url: str) -> dict:
    """GET one SEC JSON object. A transport error, a non-2xx, an undecodable
    body or a non-object body raises SourceUnavailable (I-15); nothing else is
    caught, so a programming error propagates (I-17)."""
    try:
        resp = client.get(url)
        resp.raise_for_status()
        body = resp.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceUnavailable("sec", f"{url}: {exc!r}") from exc
    if not isinstance(body, dict):
        raise SourceUnavailable("sec", f"{url}: body is {type(body).__name__}")
    return body


def fetch_cik_map(client: httpx.Client) -> dict[str, str]:
    """ticker -> 10-digit zero-padded CIK. Raises SourceUnavailable when SEC
    cannot answer.

    The zero-padding is load-bearing: `data.sec.gov` 404s on an unpadded CIK.
    """
    payload = _get_json(client, SEC_TICKERS_URL)
    out: dict[str, str] = {}
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip().upper()
        cik = entry.get("cik_str")
        if not ticker or cik is None:
            continue
        try:
            out[ticker] = str(int(cik)).zfill(10)
        except (ValueError, TypeError) as exc:  # one malformed entry, not the map
            logger.debug("sec cik map skip %s: %s", ticker, repr(exc))
    return out


def fetch_filings(client: httpx.Client, cik: str) -> list[SecFiling]:
    """Every periodic filing for one CIK, archives included.

    Returns a deduplicated, chronologically sorted list; an empty list means
    only "SEC answered and lists no periodic filings". If the submissions
    document OR any archive page cannot be fetched, raises SourceUnavailable:
    a list missing an archive page would under-report this issuer's filings.
    """
    payload = _get_json(client, SEC_SUBMISSIONS_URL.format(cik=cik))
    seen: set[SecFiling] = set(parse_submissions(payload))
    for name in archive_names(payload):
        seen.update(parse_archive(_get_json(client, SEC_ARCHIVE_URL.format(name=name))))
    return sorted(seen, key=lambda f: (f.report_date, f.filing_date, f.accession))


def periodic_only(filings: Iterable[SecFiling]) -> list[SecFiling]:
    """Non-amendment periodic filings. The amendments are handled separately."""
    return [f for f in filings if not f.is_amendment]
