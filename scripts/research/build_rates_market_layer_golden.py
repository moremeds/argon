"""Freeze the MC3 Part A golden fixture from live publishers.

Reproduce:
    uv run python scripts/research/build_rates_market_layer_golden.py

Every value is fetched from the publisher at authoring time and frozen with the instant
that made it knowable.  The ``expect`` blocks are preregistered predictions written before
the engines existed; regenerating this file must never be used to edit them to match
whatever the engines produce.  The generator therefore refuses to overwrite an existing
``expect`` block -- it merges the freshly fetched inputs under the predictions already on
disk.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "fixtures" / "macro" / "rates_market_layer_golden.json"
SPEC = "docs/superpowers/specs/2026-08-21-rates-market-layer-design.md"

TREASURY = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"
CFTC = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
FRED = "https://api.stlouisfed.org/fred/series/observations"
TEN_YEAR_FUTURE = "043602"

CFTC_COLUMNS = (
    "report_date_as_yyyy_mm_dd,:created_at,open_interest_all,"
    "dealer_positions_long_all,dealer_positions_short_all,"
    "lev_money_positions_long,lev_money_positions_short"
)


def _client() -> httpx.Client:
    # trust_env=False: httpx would otherwise fall through to getproxies(), which on macOS
    # reads the system network pane.  Four rates clients froze on exactly that.
    return httpx.Client(timeout=90.0, trust_env=False)


def fetch_nominal_auctions(
    client: httpx.Client, term: str, start: str, end: str
) -> list[dict[str, Any]]:
    """New-issue nominal auctions for one term.

    ``type == securityType`` is the nominal filter.  A 10-Year TIPS carries
    ``securityTerm='10-Year'`` and ``securityType='Note'`` exactly like a nominal note and
    is half the size, so the term alone is not an identity -- see spec 2.1.

    The window is applied client-side.  TreasuryDirect accepts ``startDate``/``endDate``
    and ignores them: the endpoint returns a fixed 250-row cap of most-recent auctions
    either way, so a ``type=Bond`` request reaches back to 2012 while ``type=Note`` reaches
    2021.  Trusting the parameters would silently produce a different window per term.
    """
    response = client.get(
        TREASURY,
        params={
            "format": "json",
            "type": "Note" if term.startswith("10") else "Bond",
        },
    )
    response.raise_for_status()
    out = []
    for raw in response.json():
        if raw.get("securityTerm") != term or raw.get("reopening") != "No":
            continue
        if raw.get("type") != raw.get("securityType"):
            continue  # inflation-linked; a separate series
        if not start <= raw["auctionDate"][:10] <= end:
            continue
        out.append(
            {
                "series_id": f"{term}|{raw['securityType']}",
                "cusip": raw["cusip"],
                "causal_role": "supply",
                "period_end": raw["auctionDate"][:10],
                "available_at": raw["announcementDate"][:10],
                "value": raw["offeringAmount"],
                "unit": "usd_offering_amount",
                "source": "treasurydirect",
                "source_kind": "official",
                "cost_class": "free_official",
            }
        )
    return sorted(out, key=lambda row: row["period_end"])


def fetch_positioning(client: httpx.Client, where: str) -> list[dict[str, Any]]:
    response = client.get(
        CFTC,
        params={
            "$select": CFTC_COLUMNS,
            "$where": f"cftc_contract_market_code='{TEN_YEAR_FUTURE}' AND {where}",
            "$order": "report_date_as_yyyy_mm_dd",
            "$limit": "5000",
        },
    )
    response.raise_for_status()
    return response.json()


def positioning_rows(
    raw: list[dict[str, Any]], bulk_load: str | None
) -> list[dict[str, Any]]:
    out = []
    for row in raw:
        oi = int(row["open_interest_all"])
        lev = int(row["lev_money_positions_long"]) - int(
            row["lev_money_positions_short"]
        )
        dealer = int(row["dealer_positions_long_all"]) - int(
            row["dealer_positions_short_all"]
        )
        created = row[":created_at"]
        is_bulk = created == bulk_load
        out.append(
            {
                "series_id": f"{TEN_YEAR_FUTURE}|lev_money_net_pct_oi",
                "causal_role": "positioning",
                "period_end": row["report_date_as_yyyy_mm_dd"][:10],
                # Spec 3.2/3.4: a :created_at shared across many report dates is a load
                # event, not a release.  Those rows get published_at=NULL and a
                # conservative available_at; the rest carry the real release instant.
                "published_at": None if is_bulk else created,
                "available_at": created,
                "availability_basis": "bulk_load_conservative"
                if is_bulk
                else "publisher_release",
                "value": f"{lev / oi * 100:.4f}",
                "unit": "pct_open_interest",
                "open_interest": str(oi),
                "dealer_net_contracts": str(dealer),
                "lev_money_net_contracts": str(lev),
                "source": "cftc",
                "source_kind": "official",
                "cost_class": "free_official",
            }
        )
    return out


def detect_bulk_load(raw: list[dict[str, Any]]) -> str | None:
    """A :created_at covering more than one distinct report_date is a load, not a release.

    Stated per report_date rather than per row on purpose: one real release covers every
    contract in the file, so 'shared by many rows' would flag genuine releases too.
    """
    spans: dict[str, set[str]] = {}
    for row in raw:
        spans.setdefault(row[":created_at"], set()).add(
            row["report_date_as_yyyy_mm_dd"][:10]
        )
    loads = [ts for ts, dates in spans.items() if len(dates) > 1]
    if len(loads) > 1:
        raise SystemExit(
            f"expected at most one load event, found {len(loads)}: {sorted(loads)}"
        )
    return loads[0] if loads else None


def fetch_fred(
    client: httpx.Client, series_id: str, start: str, end: str, key: str
) -> list[dict[str, Any]]:
    response = client.get(
        FRED,
        params={
            "series_id": series_id,
            "api_key": key,
            "file_type": "json",
            "observation_start": start,
            "observation_end": end,
        },
    )
    response.raise_for_status()
    return [
        {
            "series_id": series_id,
            "causal_role": "curve",
            "period_end": row["date"],
            "value": row["value"],
            "unit": "percent",
            "source": "fred",
            "source_kind": "first_party_publisher",
            "cost_class": "free_publisher",
        }
        for row in response.json()["observations"]
        if row["value"] != "."
    ]


# Preregistered predictions.  Written before the engines exist; never edited to match output.
EXPECT: dict[str, dict[str, Any]] = {
    "supply_elevated_against_neutral_macro": {
        "supply_state": "ELEVATED",
        "elevated_series_include": ["10-Year|Note"],
        "contradictions_include": ["supply_pressure_without_macro_confirmation"],
        "policy_state_unchanged_by_supply": True,
        "note": (
            "40bn is above the max of the prior four new issues. The nominal move over the "
            "same window is carried by real yields, not compensation, so nothing here is "
            "evidence about the inflation regime. Supply describes; it does not gate policy."
        ),
    },
    "positioning_stretched_against_curve": {
        "positioning_state": "STRETCHED_LOW",
        "contradictions_include": ["positioning_against_curve_direction"],
        "note": (
            "Leveraged money is at the low end of its own distribution -- deeply net short -- "
            "while the 10y yield falls 42bp over the same window. A short profits when yields "
            "rise, so position and realised move disagree. The disagreement is the output; no "
            "direction is inferred for the curve from the position. STRETCHED_LOW, not "
            "STRETCHED_SHORT: this category is net short in every week of the sample, so the "
            "label is relative to its own history (spec 4.2)."
        ),
    },
    "cot_week_never_published": {
        "positioning_state": "UNKNOWN",
        "absent_periods": ["2018-12-25", "2019-01-01"],
        "distinguishes_absent_from_parse_failure": True,
        "note": (
            "Two Tuesdays fall on Christmas Day and New Year's Day and no report exists. "
            "An absent week is not a zero position and not a parse failure."
        ),
    },
    "holiday_shifted_release_is_not_knowable_early": {
        "row_visible_at_as_of": False,
        "derived_rule_would_have_shown_it": True,
        "note": (
            "report_date 2026-06-16 loaded 2026-06-22T19:30:53Z because Juneteenth moved "
            "the release. The obs_date+3d rule says 2026-06-19. An as_of between the two "
            "must not see the row -- that gap is lookahead, and it is what the legacy "
            "derivation ships today."
        ),
    },
    "positioning_stale_past_its_cadence": {
        "positioning_state": "UNKNOWN",
        "domain_freshness_takes_minimum": True,
        "note": (
            "Supply is fresh and positioning is months past its weekly cadence. The "
            "domain's freshness is the stalest input, not the mean, or one quiet feed "
            "hides behind several live ones."
        ),
    },
    "supply_term_below_minimum_rows": {
        "supply_state": "UNKNOWN",
        "shortfall_named": True,
        "minimum_rows": 5,
        "note": (
            "supply_baseline_quarters=4 needs 5 new issues to call a multi-quarter high. "
            "Fewer produces no sub-state and says why, rather than comparing against a "
            "shorter baseline."
        ),
    },
}


def main() -> None:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise SystemExit("FRED_API_KEY is required")

    client = _client()

    ten_year = fetch_nominal_auctions(client, "10-Year", "2021-01-01", "2024-06-30")
    thirty_year = fetch_nominal_auctions(client, "30-Year", "2021-01-01", "2024-06-30")
    early_ten = [row for row in ten_year if row["period_end"] <= "2021-12-31"]

    # 2025-07-15 -> 2025-09-09: leveraged money at -45.9% of open interest, below its own
    # 10th percentile, while the 10y fell 4.50 -> 4.08.  Chosen because the prediction
    # requires a real disagreement; the first window tried (2026-05..08) had yields RISING
    # into a short, which is the position agreeing, and the expect block is not editable.
    recent_raw = fetch_positioning(
        client,
        "report_date_as_yyyy_mm_dd >= '2025-07-01' AND report_date_as_yyyy_mm_dd <= '2025-09-09'",
    )
    holiday_raw = fetch_positioning(client, "report_date_as_yyyy_mm_dd >= '2026-05-01'")
    shutdown_raw = fetch_positioning(
        client,
        "report_date_as_yyyy_mm_dd >= '2018-11-01' AND report_date_as_yyyy_mm_dd <= '2019-04-01'",
    )
    all_raw = fetch_positioning(client, "report_date_as_yyyy_mm_dd >= '2006-01-01'")
    bulk = detect_bulk_load(all_raw)

    recent = positioning_rows(recent_raw, bulk)
    holiday = positioning_rows(holiday_raw, bulk)
    shutdown = positioning_rows(shutdown_raw, bulk)
    curve = fetch_fred(client, "DGS10", "2025-07-14", "2025-09-10", key)
    curve_2023 = fetch_fred(client, "DGS10", "2023-07-01", "2023-11-30", key)

    scenarios = [
        {
            "id": "supply_elevated_against_neutral_macro",
            "domain": "policy_rates",
            "role": "supply",
            "as_of": "2023-11-30",
            "inputs": [row for row in ten_year if row["period_end"] <= "2023-11-30"]
            + [row for row in thirty_year if row["period_end"] <= "2023-11-30"],
            "curve_window": [curve_2023[0], curve_2023[-1]],
            "expect": EXPECT["supply_elevated_against_neutral_macro"],
        },
        {
            "id": "positioning_stretched_against_curve",
            "domain": "policy_rates",
            "role": "positioning",
            "as_of": "2025-09-12",
            "inputs": recent,
            "curve_window": [curve[0], curve[-1]],
            "expect": EXPECT["positioning_stretched_against_curve"],
        },
        {
            "id": "cot_week_never_published",
            "domain": "policy_rates",
            "role": "positioning",
            "as_of": "2019-04-01",
            "inputs": shutdown,
            "expect": EXPECT["cot_week_never_published"],
        },
        {
            "id": "holiday_shifted_release_is_not_knowable_early",
            "domain": "policy_rates",
            "role": "positioning",
            "as_of": "2026-06-19T20:00:00Z",
            "inputs": [row for row in holiday if row["period_end"] == "2026-06-16"],
            "expect": EXPECT["holiday_shifted_release_is_not_knowable_early"],
        },
        {
            "id": "positioning_stale_past_its_cadence",
            "domain": "policy_rates",
            "role": "positioning",
            "as_of": "2026-08-20",
            "inputs": [row for row in holiday if row["period_end"] <= "2026-05-26"]
            + [row for row in ten_year if row["period_end"] <= "2024-06-30"][-5:],
            "expect": EXPECT["positioning_stale_past_its_cadence"],
        },
        {
            "id": "supply_term_below_minimum_rows",
            "domain": "policy_rates",
            "role": "supply",
            "as_of": "2021-12-31",
            "inputs": early_ten,
            "expect": EXPECT["supply_term_below_minimum_rows"],
        },
    ]

    payload = {
        "schema_version": "1",
        "authored_at": datetime.now(UTC).isoformat(),
        "spec": SPEC,
        "provenance": {
            "supply": (
                "TreasuryDirect TA_WS/securities/auctioned. New-issue nominal only: "
                "reopening == 'No' and type == securityType. available_at is the "
                "publisher's announcementDate, which precedes the auction by about a week."
            ),
            "positioning": (
                "CFTC TFF futures-only, Socrata gpe5-46if, contract 043602 (10Y note "
                "future). available_at is the row's :created_at. The payload carries no "
                "release field; the existing client derives obs_date+3d, which is wrong on "
                "federal-holiday weeks -- see spec 3.2."
            ),
            "positioning_bulk_load": (
                f"Rows created at {bulk} are a Socrata load event, not a release: that one "
                "timestamp covers every report_date from 2006-06-13 to 2022-09-06. Their "
                "true publication instant is unknown, so published_at is NULL and "
                "available_at is the load instant, which is conservative and never "
                "over-claims. Rows after it each carry a unique :created_at and are real "
                "releases."
            ),
            "curve": "FRED DGS10, used only to give the positioning and supply scenarios a real curve move to disagree with.",
            "values_are_real": "Every number was fetched from the live publisher at authoring time.",
        },
        "scenarios": scenarios,
    }

    if OUT.exists():
        prior = json.loads(OUT.read_text(encoding="utf-8"))
        frozen = {row["id"]: row.get("expect") for row in prior.get("scenarios", [])}
        changed = [
            row["id"]
            for row in payload["scenarios"]
            if row["id"] in frozen and frozen[row["id"]] != row["expect"]
        ]
        if changed and "--rewrite-predictions" not in sys.argv:
            raise SystemExit(
                "refusing to overwrite the frozen prediction for "
                + ", ".join(changed)
                + ".\nPreregistered expectations are not editable from a regeneration. If "
                "the change is an authoring-time correction rather than a fit to engine "
                "output, re-run with --rewrite-predictions and record it as a spec "
                "deviation."
            )
        for scenario_id in changed:
            print(f"  REWRITING PREDICTION: {scenario_id}")
            print(f"    was: {json.dumps(frozen[scenario_id], sort_keys=True)}")

    OUT.write_text(
        json.dumps(payload, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT.relative_to(ROOT)}")
    for row in scenarios:
        print(f"  {row['id']:<48} inputs={len(row['inputs']):>3}")


if __name__ == "__main__":
    main()
