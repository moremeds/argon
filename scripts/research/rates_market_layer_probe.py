"""Probe the three rates market-layer publishers and persist the evidence.

Reproduce:
    uv run python scripts/research/rates_market_layer_probe.py

Answers, against live endpoints:

  plumbing     do the four FRED candidates exist, at the frequency the spec assumed, and
               does each clear FRED's 2000-vintage ceiling under the window
               ``request_window`` would actually build for it?
  supply       does TreasuryDirect expose a publication instant, do its date parameters
               work, and how many rows come back?
  positioning  does the CFTC payload carry a release field, is Socrata's ``:created_at``
               a real release instant, and where is the bulk-load boundary?

Writes docs/research/2026-08-21-rates-market-layer-probe/probe.json.  Every number in the
VERDICT comes from that file; nothing is quoted from memory.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, date, datetime
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
OUT = ROOT / "docs" / "research" / "2026-08-21-rates-market-layer-probe" / "probe.json"

FRED_SERIES = "https://api.stlouisfed.org/fred/series"
FRED_OBS = "https://api.stlouisfed.org/fred/series/observations"
TREASURY = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"
CFTC = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
TEN_YEAR_FUTURE = "043602"

#: (series_id, frequency the spec assumed).  A mismatch is a rejection, not a shrug: the
#: frequency decides which vintage window request_window builds, so a series that is not
#: what the spec thought gets the wrong window silently.
CANDIDATES = (
    ("SOFR", "daily"),
    ("EFFR", "daily"),
    ("RRPONTSYD", "daily"),
    ("WRESBAL", "weekly"),
)
VINTAGE_CAP = 2000
#: Two years of headroom at the measured growth rate, per the spec's decision rule.
REQUIRED_HEADROOM_YEARS = 2.0

FRED_FREQ = {
    "D": "daily",
    "W": "weekly",
    "M": "monthly",
    "Q": "quarterly",
    "A": "annual",
}


def client() -> httpx.Client:
    # trust_env=False or httpx falls through to getproxies(), which reads the macOS
    # system network pane.  Four rates clients froze on exactly that.
    return httpx.Client(timeout=90.0, trust_env=False)


def probe_fred(http: httpx.Client, key: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "cap": VINTAGE_CAP,
        "daily_vintage_start": DAILY_VINTAGE_START.isoformat(),
        "series": {},
    }
    for series_id, assumed in CANDIDATES:
        row: dict[str, Any] = {"assumed_frequency": assumed}
        meta = http.get(
            FRED_SERIES,
            params={"series_id": series_id, "api_key": key, "file_type": "json"},
        )
        if meta.status_code != 200:
            row["exists"] = False
            row["http_status"] = meta.status_code
            row["verdict"] = "REJECT: series does not resolve"
            out["series"][series_id] = row
            continue

        detail = meta.json()["seriess"][0]
        actual = FRED_FREQ.get(detail["frequency_short"], detail["frequency_short"])
        row |= {
            "exists": True,
            "title": detail["title"],
            "actual_frequency": actual,
            "units": detail["units_short"],
            "observation_start": detail["observation_start"],
            "observation_end": detail["observation_end"],
            "frequency_matches_assumption": actual == assumed,
        }

        # The window request_window() would build for this series, given its real frequency.
        if actual == "daily":
            obs_start, rt_start = DAILY_VINTAGE_START, DAILY_VINTAGE_START
        else:
            obs_start, rt_start = (
                date.fromisoformat(detail["observation_start"]),
                ALL_VINTAGES_START,
            )
        row["window"] = {
            "observation_start": obs_start.isoformat(),
            "realtime_start": rt_start.isoformat(),
            "realtime_end": ALL_VINTAGES_END.isoformat(),
        }

        obs = http.get(
            FRED_OBS,
            params={
                "series_id": series_id,
                "api_key": key,
                "file_type": "json",
                "observation_start": obs_start.isoformat(),
                "realtime_start": rt_start.isoformat(),
                "realtime_end": ALL_VINTAGES_END.isoformat(),
            },
        )
        row["observations_http_status"] = obs.status_code
        if obs.status_code != 200:
            row["error_body"] = obs.text[:400]
            row["verdict"] = "REJECT: window exceeds the publisher's vintage ceiling"
            out["series"][series_id] = row
            continue

        rows = obs.json()["observations"]
        vintages = {r["realtime_start"] for r in rows}
        first = min(
            (r for r in rows if r["value"] != "."),
            key=lambda r: r["date"],
            default=None,
        )
        span_years = (
            date.fromisoformat(max(r["date"] for r in rows))
            - date.fromisoformat(min(r["date"] for r in rows))
        ).days / 365.25
        per_year = len(vintages) / span_years if span_years else 0.0
        headroom = (
            (VINTAGE_CAP - len(vintages)) / per_year if per_year else float("inf")
        )
        row |= {
            "rows": len(rows),
            "distinct_vintages": len(vintages),
            "span_years": round(span_years, 2),
            "vintages_per_year": round(per_year, 1),
            "headroom_years": round(headroom, 1),
            "first_observation": first["date"] if first else None,
            # The correctness condition for a bounded daily window: the earliest row's true
            # vintage must not be the window edge, or it was clamped.
            "first_observation_true_vintage": first["realtime_start"]
            if first
            else None,
            "first_vintage_is_window_edge": bool(
                first and first["realtime_start"] == rt_start.isoformat()
            ),
        }
        ok = (
            row["frequency_matches_assumption"]
            and len(vintages) < VINTAGE_CAP
            and headroom >= REQUIRED_HEADROOM_YEARS
            and not row["first_vintage_is_window_edge"]
        )
        reasons = []
        if not row["frequency_matches_assumption"]:
            reasons.append(f"frequency is {actual}, spec assumed {assumed}")
        if len(vintages) >= VINTAGE_CAP:
            reasons.append(f"{len(vintages)} vintages at or over the {VINTAGE_CAP} cap")
        if headroom < REQUIRED_HEADROOM_YEARS:
            reasons.append(
                f"only {headroom:.1f}y headroom, rule requires {REQUIRED_HEADROOM_YEARS}"
            )
        if row["first_vintage_is_window_edge"]:
            reasons.append(
                "earliest vintage equals the window edge, so it may be clamped"
            )
        row["verdict"] = "SELECT" if ok else "REJECT: " + "; ".join(reasons)
        out["series"][series_id] = row
    return out


def probe_treasury(http: httpx.Client) -> dict[str, Any]:
    plain = http.get(TREASURY, params={"format": "json"})
    plain.raise_for_status()
    rows = plain.json()
    dates = sorted(r["auctionDate"][:10] for r in rows)

    # Do the documented date parameters actually filter?
    windowed = http.get(
        TREASURY,
        params={
            "format": "json",
            "dateFieldName": "auctionDate",
            "startDate": "2024-01-01",
            "endDate": "2024-03-31",
        },
    )
    w_rows = windowed.json() if windowed.status_code == 200 else []
    w_dates = sorted(r["auctionDate"][:10] for r in w_rows)
    honoured = (
        bool(w_dates) and w_dates[0] >= "2024-01-01" and w_dates[-1] <= "2024-03-31"
    )

    # The TIPS collision: same term, same securityType, different `type`, half the size.
    collisions = []
    for term in ("10-Year", "30-Year"):
        by_type: dict[str, list[int]] = {}
        for r in rows:
            if (
                r.get("securityTerm") == term
                and r.get("reopening") == "No"
                and r.get("offeringAmount")
            ):
                by_type.setdefault(r.get("type", "?"), []).append(
                    int(r["offeringAmount"])
                )
        if len(by_type) > 1:
            collisions.append(
                {
                    "securityTerm": term,
                    "securityTypes": sorted(
                        {
                            r["securityType"]
                            for r in rows
                            if r.get("securityTerm") == term
                        }
                    ),
                    "types": {
                        t: {"n": len(v), "median_offering": sorted(v)[len(v) // 2]}
                        for t, v in by_type.items()
                    },
                }
            )

    sample = next(
        r
        for r in rows
        if r.get("securityTerm") == "10-Year"
        and r.get("reopening") == "No"
        and r.get("type") == "Note"
    )
    return {
        "rows_returned": len(rows),
        "auction_date_range": [dates[0], dates[-1]],
        "has_announcement_date": "announcementDate" in sample,
        "date_parameters_honoured": honoured,
        "date_parameter_note": (
            "startDate/endDate are accepted and ignored; the endpoint returns the same "
            f"{len(rows)}-row cap of most-recent auctions. The window must be applied client-side."
        )
        if not honoured
        else "date parameters filter as documented",
        "sample_row": {
            k: sample.get(k)
            for k in (
                "cusip",
                "securityTerm",
                "securityType",
                "type",
                "announcementDate",
                "auctionDate",
                "offeringAmount",
            )
        },
        "announcement_lead_days": (
            date.fromisoformat(sample["auctionDate"][:10])
            - date.fromisoformat(sample["announcementDate"][:10])
        ).days,
        "term_type_collisions": collisions,
    }


def probe_cftc(http: httpx.Client) -> dict[str, Any]:
    one = http.get(CFTC, params={"$limit": "1"})
    one.raise_for_status()
    fields = sorted(one.json()[0].keys())
    release_fields = [
        f for f in fields if "release" in f.lower() or "publish" in f.lower()
    ]

    full = http.get(
        CFTC,
        params={
            "$select": "report_date_as_yyyy_mm_dd,:created_at",
            "$where": f"cftc_contract_market_code='{TEN_YEAR_FUTURE}'",
            "$order": "report_date_as_yyyy_mm_dd",
            "$limit": "5000",
        },
    )
    full.raise_for_status()
    rows = full.json()

    spans: dict[str, set[str]] = {}
    for r in rows:
        spans.setdefault(r[":created_at"], set()).add(
            r["report_date_as_yyyy_mm_dd"][:10]
        )
    loads = {ts: sorted(d) for ts, d in spans.items() if len(d) > 1}

    bulk = max(loads, key=lambda ts: len(loads[ts])) if loads else None
    incremental = [r for r in rows if r[":created_at"] != bulk]

    # Does obs_date + 3 days match the real load instant?  Measured on the incremental
    # rows only -- the bulk rows have no release instant to compare against.
    mismatches = []
    for r in incremental:
        obs = date.fromisoformat(r["report_date_as_yyyy_mm_dd"][:10])
        actual = datetime.fromisoformat(r[":created_at"].replace("Z", "+00:00")).date()
        derived = date.fromordinal(obs.toordinal() + 3)
        if actual != derived:
            mismatches.append(
                {
                    "report_date": obs.isoformat(),
                    "derived_release": derived.isoformat(),
                    "actual_created_at": r[":created_at"],
                    "days_late_vs_rule": (actual - derived).days,
                }
            )

    times = Counter(r[":created_at"][11:16] for r in incremental)
    return {
        "field_count": len(fields),
        "publisher_release_fields": release_fields,
        "has_publisher_release_field": bool(release_fields),
        "socrata_created_at_available": True,
        "rows": len(rows),
        "bulk_load_timestamp": bulk,
        "bulk_load_row_count": len(rows) - len(incremental),
        "bulk_load_report_date_range": [loads[bulk][0], loads[bulk][-1]]
        if bulk
        else None,
        "incremental_rows": len(incremental),
        "incremental_report_date_range": (
            [
                min(r["report_date_as_yyyy_mm_dd"][:10] for r in incremental),
                max(r["report_date_as_yyyy_mm_dd"][:10] for r in incremental),
            ]
            if incremental
            else None
        ),
        "derived_rule": "obs_date + 3 days (sources/cftc_tff.py:210)",
        "derived_rule_mismatches": len(mismatches),
        "derived_rule_mismatch_rate": round(len(mismatches) / len(incremental), 4)
        if incremental
        else None,
        "derived_rule_always_early": all(m["days_late_vs_rule"] > 0 for m in mismatches)
        if mismatches
        else None,
        "derived_rule_mismatch_detail": mismatches,
        "release_time_utc_distribution": dict(times.most_common(5)),
        "release_time_is_constant": len(times) == 1,
    }


def main() -> None:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise SystemExit("FRED_API_KEY is required")
    http = client()

    payload = {
        "probed_at": datetime.now(UTC).isoformat(),
        "spec": "docs/superpowers/archive/specs/2026-08-21-rates-market-layer-design.md",
        "plumbing_fred": probe_fred(http, key),
        "supply_treasurydirect": probe_treasury(http),
        "positioning_cftc": probe_cftc(http),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")

    for series_id, row in payload["plumbing_fred"]["series"].items():
        print(f"  {series_id:<11} {row['verdict']}")
    t = payload["supply_treasurydirect"]
    print(
        f"  treasury    announcementDate={t['has_announcement_date']} "
        f"lead={t['announcement_lead_days']}d date_params_honoured={t['date_parameters_honoured']} "
        f"collisions={len(t['term_type_collisions'])}"
    )
    c = payload["positioning_cftc"]
    print(
        f"  cftc        release_field={c['has_publisher_release_field']} "
        f"bulk={c['bulk_load_row_count']} incremental={c['incremental_rows']} "
        f"rule_wrong={c['derived_rule_mismatches']} ({c['derived_rule_mismatch_rate']})"
    )


if __name__ == "__main__":
    main()
