"""sec_filing_index_refresh against a real schema: the I-15 unit rule.

Unit = one issuer (each commits as it lands). The CIK map is the shared input,
so SEC failing to serve it fails the run; an issuer SEC cannot answer for is
counted; the run fails only when no issuer could be fetched. The submissions
payload is the frozen real NVDA one from tests/unit/sources.
"""

from __future__ import annotations

import httpx
import pytest

from tests.unit.sources.test_sec_submissions import PAYLOAD
from uw_scan.sources.source_errors import SourceUnavailable
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository
from uw_scan.worker.jobs import sec_filing_index_refresh as job_mod

_TICKERS = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"},
    "1": {"cik_str": 2488, "ticker": "AMD", "title": "AMD"},
}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(job_mod, "_SLEEP_SECONDS", 0)


def _client(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        r = routes.get(request.url.path)
        return r if r is not None else httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def _refresh(repo, client):
    return job_mod.sec_filing_index_refresh(
        conn=repo.conn, schema="uw_scan", tickers=["NVDA", "AMD"], client=client
    )


def test_one_issuer_unavailable_is_counted_and_the_other_persists(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    client = _client(
        {
            "/files/company_tickers.json": httpx.Response(200, json=_TICKERS),
            "/submissions/CIK0001045810.json": httpx.Response(200, json=PAYLOAD),
            # the archive page the real NVDA payload lists under filings.files
            "/submissions/CIK0001045810-submissions-001.json": httpx.Response(
                200, json=PAYLOAD["filings"]["recent"]
            ),
            "/submissions/CIK0000002488.json": httpx.Response(503, text="busy"),
        }
    )
    counters = _refresh(repo, client)

    assert counters["unavailable"] == 1
    assert counters["no_filings"] == 0
    assert counters["filings_inserted"] > 0
    assert SecFilingIndexRepository(repo.conn, "uw_scan").filings_for("NVDA")


def test_every_issuer_unavailable_fails_the_run(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _client(
        {
            "/files/company_tickers.json": httpx.Response(200, json=_TICKERS),
            "/submissions/CIK0001045810.json": httpx.Response(503, text="busy"),
            "/submissions/CIK0000002488.json": httpx.Response(503, text="busy"),
        }
    )
    with pytest.raises(SourceUnavailable, match="2 issuers unavailable"):
        _refresh(repo, client)


def test_cik_map_unavailable_fails_the_run(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    client = _client({"/files/company_tickers.json": httpx.Response(403, text="UA")})
    with pytest.raises(SourceUnavailable, match="403"):
        _refresh(repo, client)
