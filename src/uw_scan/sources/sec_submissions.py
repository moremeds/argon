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
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://data.sec.gov/submissions/{name}"

#: Periodic reports only. An 8-K announces, a Form 4 reports ownership; neither
#: publishes the statements Argon stores, so neither can date one.
SEC_FORMS = frozenset({"10-Q", "10-K", "20-F", "40-F"})


@dataclass(frozen=True)
class SecFiling:
    """One periodic filing. Frozen and hashable so a caller can dedupe archives.

    `report_date` is SEC's `reportDate` — the fiscal period the filing covers,
    which is NOT reliably equal to Argon's `period_end` (52/53-week calendars
    disagree by a few days). `filing_date` is when it became public.
    """

    accession: str
    form: str
    report_date: date
    filing_date: date
    is_amendment: bool


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


def _get_json(client: httpx.Client, url: str) -> Any | None:
    """Never-raise GET. A caller distinguishes "no data" from "failed" by count."""
    try:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:  # noqa: BLE001 - never-raise client boundary
        logger.warning("sec fetch failed url=%s err=%s", url, repr(exc))
        return None


def fetch_cik_map(client: httpx.Client) -> dict[str, str]:
    """ticker -> 10-digit zero-padded CIK. Empty dict on failure, never raises.

    The zero-padding is load-bearing: `data.sec.gov` 404s on an unpadded CIK.
    """
    payload = _get_json(client, SEC_TICKERS_URL)
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        ticker = str(entry.get("ticker") or "").strip().upper()
        cik = entry.get("cik_str")
        if not ticker or cik is None:
            continue
        out[ticker] = str(int(cik)).zfill(10)
    return out


def fetch_filings(client: httpx.Client, cik: str) -> list[SecFiling]:
    """Every periodic filing for one CIK, archives included. Never raises.

    Returns a deduplicated, chronologically sorted list. An empty list means
    either "no periodic filings" or "the fetch failed" — the refresh job
    separates those by counting `None` payloads, not by list length here.
    """
    payload = _get_json(client, SEC_SUBMISSIONS_URL.format(cik=cik))
    if payload is None:
        return []
    seen: set[SecFiling] = set(parse_submissions(payload))
    for name in archive_names(payload):
        archive = _get_json(client, SEC_ARCHIVE_URL.format(name=name))
        if archive is not None:
            seen.update(parse_archive(archive))
    return sorted(seen, key=lambda f: (f.report_date, f.filing_date, f.accession))


def periodic_only(filings: Iterable[SecFiling]) -> list[SecFiling]:
    """Non-amendment periodic filings. The amendments are handled separately."""
    return [f for f in filings if not f.is_amendment]
