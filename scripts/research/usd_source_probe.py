"""Probe the official USD sources before any adapter is written.

Reproduce:
    uv run python scripts/research/usd_source_probe.py

Answers three questions the USD state cannot be built without:

* which broad-dollar series is vintage-bearing, and therefore replayable;
* whether the independent cross-check is reachable at all, and on what terms;
* which candidates are dead, so a later reader does not re-try them.

Zero rows, transport errors and "not published" stay distinct outcomes.  A source that
answers an auth or content-negotiation failure with an empty body would otherwise be
recorded as having legitimately published nothing.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from uw_scan.worker.jobs.macro_series_ingest import (
    ALL_VINTAGES_END,
    ALL_VINTAGES_START,
    DAILY_VINTAGE_START,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "research" / "2026-08-12-usd-source-probe"
FRED = "https://api.stlouisfed.org/fred"
BIS = "https://stats.bis.org/api/v2"

#: The header that selects JSON.  BIS content-negotiates on Accept alone, and the status
#: code does not tell you whether you got what you asked for:
#:
#:   no Accept, no format       -> HTTP 200, application/xml   <- the trap
#:   Accept: ...+json           -> HTTP 200, application/json
#:   format=jsondata, no Accept -> HTTP 406
#:   format=jsondata + Accept   -> HTTP 200, application/json
#:
#: So a client that omits this header SUCCEEDS and hands a JSON parser SDMX-ML.  The
#: ``format`` query parameter is not a substitute -- alone it is refused outright -- which
#: makes the header the only load-bearing part.  Measured 2026-08-21.
BIS_ACCEPT = "application/vnd.sdmx.data+json;version=1.0.0"

#: FRED refuses a real-time window spanning more than 2000 vintage dates.
VINTAGE_CAP = 2000

CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("DTWEXBGS", "daily", "nominal broad dollar, the H.10 headline"),
    ("RTWEXBGS", "monthly", "real broad dollar, CPI-deflated"),
    ("DTWEXAFEGS", "daily", "nominal advanced-economies dollar"),
    ("DTWEXEMEGS", "daily", "nominal emerging-market dollar"),
    ("DTWEXM", "daily", "the pre-2020 major-currencies index"),
)


def client() -> httpx.Client:
    # trust_env=False: httpx otherwise falls through to getproxies(), which on macOS
    # reads the system network pane.  Four rates clients froze on exactly that, and the
    # Linux container was immune -- so a green prod is not evidence the call is safe.
    return httpx.Client(timeout=90.0, trust_env=False, follow_redirects=True)


def probe_fred(
    http: httpx.Client, series_id: str, assumed: str, key: str
) -> dict[str, Any]:
    meta = http.get(
        f"{FRED}/series",
        params={"series_id": series_id, "api_key": key, "file_type": "json"},
    )
    if meta.status_code != 200:
        return {"exists": False, "http_status": meta.status_code, "verdict": "REJECT"}
    series = meta.json()["seriess"][0]
    frequency = {"D": "daily", "W": "weekly", "M": "monthly"}.get(
        series["frequency_short"], series["frequency_short"]
    )

    daily = frequency == "daily"
    params: dict[str, Any] = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
    }
    if daily:
        params |= {
            "observation_start": DAILY_VINTAGE_START.isoformat(),
            "realtime_start": DAILY_VINTAGE_START.isoformat(),
            "realtime_end": ALL_VINTAGES_END.isoformat(),
        }
    else:
        params |= {
            "observation_start": "2015-01-01",
            "realtime_start": ALL_VINTAGES_START.isoformat(),
            "realtime_end": ALL_VINTAGES_END.isoformat(),
        }
    obs_response = http.get(f"{FRED}/series/observations", params=params)
    out: dict[str, Any] = {
        "exists": True,
        "title": series["title"],
        "units": series["units_short"],
        "declared_frequency": frequency,
        "assumed_frequency": assumed,
        "observation_start": series["observation_start"],
        "observation_end": series["observation_end"],
        "observations_http_status": obs_response.status_code,
    }
    if obs_response.status_code != 200:
        out["verdict"] = "REJECT"
        out["reason"] = f"observations returned HTTP {obs_response.status_code}"
        return out

    rows = obs_response.json()["observations"]
    vintages = Counter(row["realtime_start"] for row in rows)
    per_period = Counter(row["date"] for row in rows)
    span_years = _years(rows[0]["date"], series["observation_end"]) if rows else 0.0
    per_year = round(len(vintages) / span_years, 1) if span_years else 0.0
    out |= {
        "rows": len(rows),
        "distinct_vintages": len(vintages),
        "span_years": round(span_years, 2),
        "vintages_per_year": per_year,
        "headroom_years": (
            round((VINTAGE_CAP - len(vintages)) / per_year, 1) if per_year else None
        ),
        # A revised period is what makes this publisher different from SOFR: the Fed
        # restates the index, so a replay must select a vintage rather than a value.
        "revised_periods": sum(1 for count in per_period.values() if count > 1),
        "first_observation": rows[0]["date"] if rows else None,
        "first_observation_vintage": rows[0]["realtime_start"] if rows else None,
    }
    # Discontinued: the publisher still answers, and everything it says is history.
    if series["observation_end"] < "2025-01-01":
        out["verdict"] = "REJECT"
        out["reason"] = (
            f"discontinued: last observation {series['observation_end']}, so it can "
            "describe no current condition"
        )
    else:
        out["verdict"] = "SELECT"
    return out


def probe_bis(http: httpx.Client) -> dict[str, Any]:
    """The independent cross-check, and what it can and cannot be used for."""
    url = f"{BIS}/data/dataflow/BIS/WS_EER/1.0/D.N.B.US"
    params = {"lastNObservations": "5"}
    bare = http.get(url, params=params)
    forced = http.get(url, params={**params, "format": "jsondata"})
    with_accept = http.get(url, params=params, headers={"Accept": BIS_ACCEPT})

    def media(response: httpx.Response) -> str:
        return response.headers.get("content-type", "").split(";")[0]

    out: dict[str, Any] = {
        "url": url,
        # Status alone is not the answer: the bare request SUCCEEDS and returns SDMX-ML,
        # so a client that forgets the header gets HTTP 200 and feeds XML to a JSON
        # parser. Recorded as (status, media type) pairs for exactly that reason.
        "bare_request": [bare.status_code, media(bare)],
        "format_param_only": [forced.status_code, media(forced)],
        "with_sdmx_accept": [with_accept.status_code, media(with_accept)],
        "accept_header_selects_json": media(bare) != "application/json"
        and media(with_accept) == "application/json",
        "anonymous_access": with_accept.status_code == 200,
    }
    if with_accept.status_code != 200:
        out["verdict"] = "REJECT"
        out["reason"] = (
            f"HTTP {with_accept.status_code} even with an SDMX Accept header"
        )
        return out

    payload = with_accept.json()
    dataset = payload["data"]["dataSets"][0]
    structure = payload["data"]["structure"]
    dates = [
        value["id"] for value in structure["dimensions"]["observation"][0]["values"]
    ]
    series_key, series = next(iter(dataset["series"].items()))
    observations = {
        dates[int(index)]: point[0] for index, point in series["observations"].items()
    }
    out |= {
        "series_key": series_key,
        "dimensions": [
            (dim["id"], dim["values"][0]["id"])
            for dim in structure["dimensions"]["series"]
        ],
        "observations": observations,
        # NaN on non-trading days, which is an absence and never a zero.
        "non_trading_days_are_nan": any(v == "NaN" for v in observations.values()),
        # The decisive one: an SDMX data message carries no real-time dimension, so
        # there is no vintage to select and nothing here can be replayed.
        "vintage_bearing": False,
        "verdict": "SELECT_AS_CROSS_CHECK_ONLY",
        "reason": (
            "reachable anonymously and current, but the data message carries no "
            "real-time dimension: it can corroborate today's level and can never "
            "answer what the level was believed to be on a past date"
        ),
    }
    return out


def _years(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days / 365.25


def main() -> int:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FRED_API_KEY")
    if not key:
        print("FRED_API_KEY is required", file=sys.stderr)
        return 1

    http = client()
    fred = {
        series_id: probe_fred(http, series_id, assumed, key)
        for series_id, assumed, _note in CANDIDATES
    }
    result = {
        "probed_at": datetime.now(UTC).isoformat(),
        "spec": "docs/superpowers/archive/specs/2026-08-12-usd-gold-state-design.md",
        "vintage_cap": VINTAGE_CAP,
        "daily_vintage_start": DAILY_VINTAGE_START.isoformat(),
        "fred_broad_dollar": fred,
        "bis_effective_exchange_rate": probe_bis(http),
        "candidate_notes": {sid: note for sid, _f, note in CANDIDATES},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "probe.json").write_text(json.dumps(result, indent=1) + "\n")

    print(f"wrote {OUT / 'probe.json'}")
    for series_id, row in fred.items():
        print(
            f"  {series_id:12s} {row.get('verdict', '?'):8s} "
            f"{row.get('declared_frequency', '?'):8s} "
            f"vintages={row.get('distinct_vintages', '-')} "
            f"revised={row.get('revised_periods', '-')} "
            f"{row.get('reason', '')}"
        )
    bis = result["bis_effective_exchange_rate"]
    print(
        f"  BIS EER      {bis['verdict']}  bare={bis.get('bare_request')}  "
        f"accept_selects_json={bis.get('accept_header_selects_json')}  "
        f"vintage_bearing={bis.get('vintage_bearing')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
