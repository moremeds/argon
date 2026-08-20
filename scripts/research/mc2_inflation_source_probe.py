#!/usr/bin/env python
"""Probe which free official inflation sources this desk can actually reach, and
which of them carry point-in-time vintages.

MC2 requires that every state replay under ``available_at <= as_of``.  A source
that serves only its current (already-revised) value cannot satisfy that for any
historical date, no matter how official it is.  This probe measures two separate
properties per candidate source: **reachability** and **vintage support**.

Reproduce::

    uv run python scripts/research/mc2_inflation_source_probe.py
    uv run python scripts/research/mc2_inflation_source_probe.py --out docs/research/.../probe.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# A contactable agent string is what BLS's published terms ask non-browser
# clients to send; the probe records whether honouring that changes the outcome.
CONTACT_UA = "argon-macro-probe/0.1 (personal research desk)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

# CPI-U, all items, NSA -- the headline series every candidate source publishes.
BLS_CPI_SERIES = "CUUR0000SA0"
# FRED's seasonally adjusted CPI-U index, and the CPI release whose calendar it follows.
FRED_CPI_SERIES = "CPIAUCSL"
FRED_CPI_RELEASE_ID = 10


def _probe(name: str, fn: Any) -> dict[str, Any]:
    try:
        return {"name": name, **fn()}
    except Exception as exc:  # noqa: BLE001 - a probe records failures, never raises
        return {"name": name, "reachable": False, "error": repr(exc)}


def _http_shape(response: httpx.Response) -> dict[str, Any]:
    body = response.content
    return {
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "body_head": response.text[:200],
    }


def probe_bls_api(client: httpx.Client, user_agent: str) -> dict[str, Any]:
    response = client.post(
        "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        json={"seriesid": [BLS_CPI_SERIES], "startyear": "2025", "endyear": "2026"},
        headers={"Content-Type": "application/json", "User-Agent": user_agent},
    )
    shape = _http_shape(response)
    return {
        "url": "https://api.bls.gov/publicAPI/v1/timeseries/data/",
        "user_agent": user_agent,
        "reachable": response.status_code == 200,
        "serves_vintages": False,
        "vintage_note": "BLS returns the current value for each period; no as-of parameter exists.",
        **shape,
    }


def probe_bls_site(client: httpx.Client, user_agent: str) -> dict[str, Any]:
    url = "https://www.bls.gov/news.release/cpi.nr0.htm"
    response = client.get(
        url, headers={"User-Agent": user_agent}, follow_redirects=True
    )
    return {
        "url": url,
        "user_agent": user_agent,
        "reachable": response.status_code == 200,
        "serves_vintages": False,
        "vintage_note": "A news release is one vintage; the archive is not addressable by as-of date.",
        **_http_shape(response),
    }


def probe_bea_api(client: httpx.Client) -> dict[str, Any]:
    url = "https://apps.bea.gov/api/data"
    response = client.get(
        url,
        params={
            "method": "GetData",
            "datasetname": "NIPA",
            "TableName": "T20804",
            "Frequency": "M",
            "Year": "2026",
            "ResultFormat": "JSON",
        },
        headers={"User-Agent": CONTACT_UA},
    )
    shape = _http_shape(response)
    # The dangerous case: a credential failure that does not look like one.
    silent_failure = response.status_code == 200 and shape["content_length"] == 0
    return {
        "url": url,
        "requires_credential": "UserID",
        "credential_held": bool(os.environ.get("BEA_USER_ID", "").strip()),
        "reachable": response.status_code == 200 and shape["content_length"] > 0,
        "fails_silently_without_credential": silent_failure,
        "serves_vintages": False,
        "vintage_note": "BEA serves current NIPA values; revisions overwrite in place.",
        **shape,
    }


def probe_bea_site(client: httpx.Client) -> dict[str, Any]:
    url = "https://www.bea.gov/data/personal-consumption-expenditures-price-index"
    response = client.get(
        url, headers={"User-Agent": CONTACT_UA}, follow_redirects=True
    )
    return {
        "url": url,
        "reachable": response.status_code == 200,
        "serves_vintages": False,
        "vintage_note": "Landing page; the release archive is not addressable by as-of date.",
        "last_modified": response.headers.get("last-modified"),
        **_http_shape(response),
    }


def probe_alfred_vintages(client: httpx.Client, api_key: str) -> dict[str, Any]:
    """The decisive measurement: does the source tell us when each value became knowable?"""
    url = "https://api.stlouisfed.org/fred/series/observations"
    response = client.get(
        url,
        params={
            "series_id": FRED_CPI_SERIES,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": "2026-01-01",
            "realtime_start": "2026-01-01",
            "realtime_end": "9999-12-31",
        },
        headers={"User-Agent": CONTACT_UA},
    )
    if response.status_code != 200:
        return {
            "url": url,
            "reachable": False,
            "serves_vintages": False,
            **_http_shape(response),
        }
    observations = response.json().get("observations", [])
    realtime_starts = sorted({obs["realtime_start"] for obs in observations})
    # A revised period appears more than once, each row carrying its own vintage.
    periods = [obs["date"] for obs in observations]
    revised_periods = sorted({p for p in periods if periods.count(p) > 1})
    return {
        "url": url,
        "series_id": FRED_CPI_SERIES,
        "reachable": True,
        "serves_vintages": len(realtime_starts) > 1,
        "credential_held": bool(api_key),
        "observation_rows": len(observations),
        "distinct_vintage_dates": realtime_starts,
        "periods_with_more_than_one_vintage": revised_periods,
        "sample_rows": observations[:3],
        "http_status": response.status_code,
    }


def probe_alfred_revisions(client: httpx.Client, api_key: str) -> dict[str, Any]:
    """Does the source preserve superseded values, or overwrite them?

    Seasonally adjusted CPI is re-seasonalised every February, so a period that is
    two years old has been restated twice.  A replay engine is only honest if it
    can still read what was published originally.
    """
    url = "https://api.stlouisfed.org/fred/series/observations"
    response = client.get(
        url,
        params={
            "series_id": FRED_CPI_SERIES,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": "2024-01-01",
            "observation_end": "2024-06-01",
            "realtime_start": "2024-01-01",
            "realtime_end": "9999-12-31",
        },
        headers={"User-Agent": CONTACT_UA},
    )
    if response.status_code != 200:
        return {
            "url": url,
            "reachable": False,
            "serves_vintages": False,
            **_http_shape(response),
        }
    observations = response.json().get("observations", [])
    by_period: dict[str, list[dict[str, str]]] = {}
    for obs in observations:
        by_period.setdefault(obs["date"], []).append(obs)
    restated = {
        period: [
            {
                "realtime_start": o["realtime_start"],
                "realtime_end": o["realtime_end"],
                "value": o["value"],
            }
            for o in rows
        ]
        for period, rows in by_period.items()
        if len({o["value"] for o in rows}) > 1
    }
    return {
        "url": url,
        "series_id": FRED_CPI_SERIES,
        "reachable": True,
        "serves_vintages": bool(restated),
        "periods_probed": sorted(by_period),
        "periods_whose_value_was_restated": sorted(restated),
        "restatements": restated,
        "supersede_semantics": "each vintage carries a half-open [realtime_start, realtime_end] validity window",
        "http_status": response.status_code,
    }


def probe_fred_release_calendar(client: httpx.Client, api_key: str) -> dict[str, Any]:
    """Cross-check: vintage dates should coincide with the publisher's release dates."""
    url = "https://api.stlouisfed.org/fred/release/dates"
    response = client.get(
        url,
        params={
            "release_id": FRED_CPI_RELEASE_ID,
            "api_key": api_key,
            "file_type": "json",
            "realtime_start": "2026-01-01",
            "sort_order": "desc",
            "limit": 24,
        },
        headers={"User-Agent": CONTACT_UA},
    )
    if response.status_code != 200:
        return {"url": url, "reachable": False, **_http_shape(response)}
    dates = [row["date"] for row in response.json().get("release_dates", [])]
    return {
        "url": url,
        "release_id": FRED_CPI_RELEASE_ID,
        "reachable": True,
        "release_dates": sorted(dates),
        "http_status": response.status_code,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", type=Path, default=None, help="write the audit JSON here"
    )
    args = parser.parse_args()

    api_key = os.environ.get("FRED_API_KEY", "").strip()

    started_at = datetime.now(UTC)
    with httpx.Client(timeout=30.0) as client:
        sources = [
            _probe("bls_api_contact_ua", lambda: probe_bls_api(client, CONTACT_UA)),
            _probe("bls_api_browser_ua", lambda: probe_bls_api(client, BROWSER_UA)),
            _probe("bls_site_browser_ua", lambda: probe_bls_site(client, BROWSER_UA)),
            _probe("bea_api_no_credential", lambda: probe_bea_api(client)),
            _probe("bea_site", lambda: probe_bea_site(client)),
            _probe(
                "alfred_cpi_vintages", lambda: probe_alfred_vintages(client, api_key)
            ),
            _probe(
                "alfred_cpi_revisions", lambda: probe_alfred_revisions(client, api_key)
            ),
            _probe(
                "fred_cpi_release_calendar",
                lambda: probe_fred_release_calendar(client, api_key),
            ),
        ]
    finished_at = datetime.now(UTC)

    vintage_capable = [s["name"] for s in sources if s.get("serves_vintages")]
    unreachable = [s["name"] for s in sources if not s.get("reachable")]

    # The cross-check that makes ALFRED's realtime_start trustworthy as available_at.
    alfred = next(s for s in sources if s["name"] == "alfred_cpi_vintages")
    calendar = next(s for s in sources if s["name"] == "fred_cpi_release_calendar")
    vintages = set(alfred.get("distinct_vintage_dates") or [])
    releases = set(calendar.get("release_dates") or [])
    audit = {
        "probe": "mc2_inflation_source_probe",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "fred_api_key_present": bool(api_key),
        "sources": sources,
        "summary": {
            "unreachable": unreachable,
            "vintage_capable": vintage_capable,
            "vintages_are_a_subset_of_published_release_dates": bool(vintages)
            and vintages.issubset(releases),
            "vintage_dates_not_on_the_release_calendar": sorted(vintages - releases),
        },
    }

    payload = json.dumps(audit, indent=2, sort_keys=False)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + "\n", encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
