#!/usr/bin/env python
"""Author the MC2 golden-scenario fixture from real, point-in-time source data.

Every value in the fixture is fetched from the live source at authoring time and
frozen together with the vintage that made it knowable.  Nothing is invented and
nothing is rounded into place: an ``as_of`` in a scenario selects the vintage the
engine must reproduce, so the fixture doubles as the point-in-time contract.

The ``expect`` blocks are **preregistered predictions**.  They are written before
``macro/inflation.py`` and ``macro/rates.py`` exist and must not be edited to match
whatever those engines happen to produce.

Reproduce::

    FRED_API_KEY=... uv run python scripts/build_inflation_rates_golden.py \
        --out tests/fixtures/macro/inflation_rates_golden.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

FRED_BASE = "https://api.stlouisfed.org/fred"
UA = {"User-Agent": "argon-macro-fixture-author/0.1 (personal research desk)"}

# Series carry their publisher transform in the id suffix, not the title:
# M158 is annualised month-over-month, M159 is year-over-year.  Recorded per
# input so the engine can refuse to combine two factors whose units differ.
SERIES_UNITS = {
    "PCEPILFE": ("index_2017_100_sa", "index"),
    "PCEPI": ("index_2017_100_sa", "index"),
    "CPILFESL": ("index_1982_84_100_sa", "index"),
    "CPIAUCSL": ("index_1982_84_100_sa", "index"),
    "MEDCPIM158SFRBCLE": (
        "percent_change_annual_rate",
        "publisher_transformed_mom_annualized",
    ),
    "TRMMEANCPIM158SFRBCLE": (
        "percent_change_annual_rate",
        "publisher_transformed_mom_annualized",
    ),
    "CORESTICKM159SFRBATL": (
        "percent_change_from_year_ago",
        "publisher_transformed_yoy",
    ),
    "MICH": ("percent", "level"),
    "T10YIE": ("percent", "level"),
    "T5YIFR": ("percent", "level"),
    "DGS10": ("percent", "level"),
    "DFII10": ("percent", "level"),
}


class Fred:
    """Minimal ALFRED reader.  Every call is vintage-aware on purpose."""

    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._client = httpx.Client(timeout=45.0, headers=UA)

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        last: httpx.Response | None = None
        for attempt in range(4):
            response = self._client.get(
                f"{FRED_BASE}/{path}",
                params={**params, "api_key": self._key, "file_type": "json"},
            )
            content_type = response.headers.get("content-type", "")
            if response.status_code == 200 and content_type.startswith(
                "application/json"
            ):
                return response.json()
            last = response
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(
            f"FRED {path} unavailable after retries: "
            f"http={last.status_code if last else 'n/a'} "
            f"body={last.text[:160] if last else 'n/a'!r}"
        )

    def as_known_on(self, series_id: str, as_of: str) -> list[dict[str, str]]:
        """Observations exactly as they stood on ``as_of`` -- the PIT read."""
        payload = self._get(
            "series/observations",
            {"series_id": series_id, "realtime_start": as_of, "realtime_end": as_of},
        )
        return [obs for obs in payload["observations"] if obs["value"] != "."]

    def all_vintages(
        self, series_id: str, start: str, end: str
    ) -> list[dict[str, str]]:
        payload = self._get(
            "series/observations",
            {
                "series_id": series_id,
                "observation_start": start,
                "observation_end": end,
                "realtime_start": "1776-07-04",
                "realtime_end": "9999-12-31",
            },
        )
        return [obs for obs in payload["observations"] if obs["value"] != "."]


def _input_row(series_id: str, obs: dict[str, str], role: str) -> dict[str, Any]:
    unit, transform = SERIES_UNITS[series_id]
    return {
        "series_id": series_id,
        "period_end": obs["date"],
        "value": obs["value"],
        "unit": unit,
        "publisher_transform": transform,
        "available_at": obs["realtime_start"],
        "causal_role": role,
        "source": "fred",
        "source_kind": "first_party_publisher",
        "cost_class": "free_publisher",
    }


def _yoy(rows: list[dict[str, str]], period: str) -> str | None:
    """Publisher-index year-over-year, computed within a single vintage."""
    by_period = {row["date"]: row["value"] for row in rows}
    year, month, day = period.split("-")
    prior = f"{int(year) - 1}-{month}-{day}"
    if period not in by_period or prior not in by_period:
        return None
    ratio = Decimal(by_period[period]) / Decimal(by_period[prior]) - 1
    return str(round(ratio * 100, 2))


def _latest_at_or_before(
    rows: list[dict[str, str]], period: str
) -> dict[str, str] | None:
    eligible = [row for row in rows if row["date"] <= period]
    return max(eligible, key=lambda row: row["date"]) if eligible else None


def realized_inflation_scenario(
    fred: Fred, *, scenario_id: str, as_of: str, period: str, expect: dict[str, Any]
) -> dict[str, Any]:
    """Scenarios 1, 2 and 6: realized inflation read exactly as of a past date."""
    inputs: list[dict[str, Any]] = []
    derived: dict[str, Any] = {}
    for series_id, role in (
        ("PCEPILFE", "realized"),
        ("PCEPI", "realized"),
        ("CPILFESL", "realized"),
        ("CPIAUCSL", "realized"),
        ("MEDCPIM158SFRBCLE", "breadth"),
        ("TRMMEANCPIM158SFRBCLE", "breadth"),
        ("CORESTICKM159SFRBATL", "stickiness"),
        ("MICH", "expectations_survey"),
    ):
        rows = fred.as_known_on(series_id, as_of)
        chosen = _latest_at_or_before(rows, period)
        if chosen is None:
            derived.setdefault("absent_at_as_of", []).append(series_id)
            continue
        inputs.append(_input_row(series_id, chosen, role))
        if series_id in {"PCEPILFE", "PCEPI", "CPILFESL", "CPIAUCSL"}:
            value = _yoy(rows, chosen["date"])
            if value is not None:
                derived[f"{series_id}_yoy_percent"] = value
            # The three-month change the direction label is read from.
            three_months_back = _shift_months(chosen["date"], 3)
            prior_yoy = _yoy(rows, three_months_back)
            if value is not None and prior_yoy is not None:
                derived[f"{series_id}_yoy_change_3m_pp"] = str(
                    round(Decimal(value) - Decimal(prior_yoy), 2)
                )
            derived[f"{series_id}_latest_period_at_as_of"] = chosen["date"]
        else:
            # Publisher-transformed series: the level IS the rate, so the 3m change
            # is a plain difference.  Recorded so every contradiction rule that reads
            # a direction can be checked against the fixture instead of asserted.
            by_period = {row["date"]: row["value"] for row in rows}
            back = _shift_months(chosen["date"], 3)
            if back in by_period:
                derived[f"{series_id}_change_3m"] = str(
                    round(Decimal(chosen["value"]) - Decimal(by_period[back]), 2)
                )
            derived[f"{series_id}_latest_period_at_as_of"] = chosen["date"]

    return {
        "id": scenario_id,
        "domain": "inflation",
        "as_of": as_of,
        "target_period": period,
        "inputs": inputs,
        "derived_from_inputs": derived,
        "expect": expect,
    }


def _shift_months(period: str, back: int) -> str:
    year, month, day = (int(part) for part in period.split("-"))
    total = year * 12 + (month - 1) - back
    return f"{total // 12:04d}-{total % 12 + 1:02d}-{day:02d}"


def yield_episode_scenario(
    fred: Fred, *, scenario_id: str, start: str, end: str, expect: dict[str, Any]
) -> dict[str, Any]:
    """Scenarios 4 and 5: a nominal move attributed to real yields and compensation."""
    inputs: list[dict[str, Any]] = []
    series = {
        "DGS10": "curve",
        "DFII10": "decomposition_component",
        "T10YIE": "decomposition_component",
    }
    frames: dict[str, dict[str, str]] = {}
    for series_id, role in series.items():
        rows = fred.as_known_on(series_id, end)
        window = {row["date"]: row for row in rows if start <= row["date"] <= end}
        frames[series_id] = {date: row["value"] for date, row in window.items()}
        for date in (min(window), max(window)):
            inputs.append(_input_row(series_id, window[date], role))

    common = sorted(set.intersection(*(set(frame) for frame in frames.values())))
    first, last = common[0], common[-1]

    def change_bp(series_id: str) -> str:
        delta = Decimal(frames[series_id][last]) - Decimal(frames[series_id][first])
        return str(round(delta * 100, 1))

    return {
        "id": scenario_id,
        "domain": "rates",
        "as_of": end,
        "window": {"first_common_session": first, "last_common_session": last},
        "inputs": inputs,
        "derived_from_inputs": {
            "nominal_change_bp": change_bp("DGS10"),
            "real_change_bp": change_bp("DFII10"),
            "breakeven_change_bp": change_bp("T10YIE"),
            "identity_residual_bp": str(
                round(
                    (
                        Decimal(frames["DGS10"][last])
                        - Decimal(frames["DFII10"][last])
                        - Decimal(frames["T10YIE"][last])
                    )
                    * 100,
                    1,
                )
            ),
            "identity_note": (
                "T10YIE is defined by the publisher as DGS10 - DFII10, so this residual is an "
                "identity check on the fetch, never evidence about term premium."
            ),
        },
        "expect": expect,
    }


def revision_scenario(fred: Fred) -> dict[str, Any]:
    """Scenario 6b: the same period, three published values, one correct replay."""
    rows = fred.all_vintages("CPIAUCSL", "2024-01-01", "2024-01-01")
    vintages = [
        {
            "value": row["value"],
            "available_at": row["realtime_start"],
            "superseded_at": row["realtime_end"],
        }
        for row in sorted(rows, key=lambda r: r["realtime_start"])
    ]
    return {
        "id": "stale_and_revised_realized_inflation",
        "domain": "inflation",
        "as_of": "2024-06-01",
        "target_period": "2024-01-01",
        "inputs": [
            {
                "series_id": "CPIAUCSL",
                "period_end": "2024-01-01",
                "vintages": vintages,
                "unit": SERIES_UNITS["CPIAUCSL"][0],
                "causal_role": "realized",
                "source": "fred",
                "source_kind": "first_party_publisher",
                "cost_class": "free_publisher",
            }
        ],
        "derived_from_inputs": {
            "vintage_count": len(vintages),
            "value_visible_at_as_of": next(
                (
                    v["value"]
                    for v in vintages
                    if v["available_at"] <= "2024-06-01" <= v["superseded_at"]
                ),
                None,
            ),
            "value_visible_today": vintages[-1]["value"],
        },
        "expect": {
            "state_basis_value": next(
                (
                    v["value"]
                    for v in vintages
                    if v["available_at"] <= "2024-06-01" <= v["superseded_at"]
                ),
                None,
            ),
            "must_not_read": vintages[-1]["value"],
            "confidence_terms": {"revision_penalty": "greater_than_zero"},
            "confidence_reasons_include": [
                "load_bearing_input_revised_since_prior_state"
            ],
            "note": "A replay must return the vintage in force at as_of, never the current value.",
        },
    }


def missing_period_scenario(fred: Fred) -> dict[str, Any]:
    """Scenario 6a: October 2025 CPI does not exist.  Abstain, never interpolate."""
    rows = fred.as_known_on("CPIAUCSL", "2026-01-15")
    window = {
        row["date"]: row["value"]
        for row in rows
        if "2025-06-01" <= row["date"] <= "2026-01-01"
    }
    return {
        "id": "absent_period_from_publication_gap",
        "domain": "inflation",
        "as_of": "2026-01-15",
        "target_period": "2025-10-01",
        "inputs": [
            {
                "series_id": "CPIAUCSL",
                "observed_window": window,
                "unit": SERIES_UNITS["CPIAUCSL"][0],
                "causal_role": "realized",
                "source": "fred",
                "source_kind": "first_party_publisher",
                "cost_class": "free_publisher",
            }
        ],
        "derived_from_inputs": {
            "periods_present": sorted(window),
            "target_period_present": "2025-10-01" in window,
            "cause": "no CPI was published for October 2025 (federal government shutdown)",
        },
        "expect": {
            "target_period_state": "INDETERMINATE",
            "must_not": [
                "forward_fill_the_missing_period",
                "substitute_a_different_series_for_the_missing_period",
                "compute_a_3m_change_spanning_the_hole_and_label_it_3m",
            ],
            "confidence_reasons_include": ["required_period_absent_at_as_of"],
        },
    }


def policy_paths_scenario() -> dict[str, Any]:
    """Scenario 3: four independently sourced policy paths that must never merge.

    The market path is a live probability snapshot with no retrievable history, so
    this scenario can only be anchored at authoring time.  That is a property of the
    source, not a shortcut: there is no date in the past for which a market-implied
    path can be reconstructed from any source this desk can reach.
    """
    from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesPathProvider
    from uw_scan.sources.fed_sep import FedSepProvider, parse_sep_release
    from uw_scan.sources.fomc_statement import (
        FomcStatementProvider,
        parse_fomc_statement,
    )

    year = datetime.now(UTC).year
    with FomcStatementProvider() as provider:
        statement = parse_fomc_statement(provider.fetch_bundles(years=(year,))[-1])
    with FedSepProvider() as provider:
        sep = parse_sep_release(provider.fetch_bundles(years=(year,))[-1])

    target_range = f"{statement.target_range_lower}-{statement.target_range_upper}"
    with FedFundsFuturesPathProvider() as provider:
        market_points = provider.fetch_latest_path(current_target_range=target_range)

    sep_funds = [
        {
            "horizon": projection.horizon,
            "median": str(projection.median),
            "central_tendency": [str(bound) for bound in projection.central_tendency],
            "range": [str(bound) for bound in projection.range],
            "participant_dots": len(projection.participant_distribution),
        }
        for projection in sep.projections
        if projection.variable == "federal_funds_rate"
    ]
    market = [
        {
            "meeting_date": str(point.meeting_date),
            "implied_rate": str(point.implied_rate),
            "stance": point.stance,
            "probabilities": {k: str(v) for k, v in point.probabilities.items()},
        }
        for point in market_points
    ]

    midpoint = (statement.target_range_lower + statement.target_range_upper) / 2
    sep_end_year = next(
        (row["median"] for row in sep_funds if row["horizon"] == str(year)), None
    )
    market_end_year = market[-1]["implied_rate"] if market else None
    spread_bp = (
        str(round((Decimal(market_end_year) - Decimal(sep_end_year)) * 100, 1))
        if sep_end_year and market_end_year
        else None
    )

    return {
        "id": "policy_paths_kept_separate",
        "domain": "rates",
        "as_of": datetime.now(UTC).date().isoformat(),
        "inputs": [
            {
                "path": "actual",
                "causal_role": "policy_actual",
                "source": "federal_reserve_fomc",
                "source_kind": "official",
                "meeting_date": str(statement.meeting_date),
                "target_range_lower": str(statement.target_range_lower),
                "target_range_upper": str(statement.target_range_upper),
                "midpoint": str(midpoint),
                "action": statement.action,
                "vote_split": statement.vote_split,
                "voter_names_stated": statement.voter_names_stated,
            },
            {
                "path": "committee_projection",
                "causal_role": "policy_committee",
                "source": "federal_reserve_sep",
                "source_kind": "official",
                "release_date": str(sep.release_date),
                "federal_funds_rate": sep_funds,
            },
            {
                "path": "market_implied",
                "causal_role": "policy_market_shadow",
                "source": "frenzy_capital_fed_watch",
                "source_kind": "third_party_shadow",
                "load_bearing": False,
                "points": market,
            },
        ],
        "derived_from_inputs": {
            "actual_midpoint": str(midpoint),
            f"sep_median_end_{year}": sep_end_year,
            f"market_implied_end_{year}": market_end_year,
            "committee_vs_market_spread_bp": spread_bp,
            "spread_is_between_forward_paths_only": (
                "The actual midpoint is where rates ARE, not where they are going.  "
                "Including it in the spread measures curve slope, not path disagreement."
            ),
            "arithmetic_mean_of_the_two_paths": (
                str((Decimal(sep_end_year) + Decimal(market_end_year)) / 2)
                if sep_end_year and market_end_year
                else None
            ),
            "why_the_mean_is_meaningless": (
                "SEP dots fall on an eighth-point grid and market pricing is a probability-weighted "
                "contract rate.  Their average is neither: no participant projected it and no "
                "contract prices it."
            ),
        },
        "expect": {
            "state": "ON_HOLD",
            "direction": "RISING",
            # Measured, not assumed: the two forward paths sit 7.5bp apart, which is
            # inside one policy move.  They AGREE, and the engine must not manufacture
            # a contradiction out of noise.  The disagreement branch cannot be anchored
            # in real data -- the market path is a live snapshot with no history -- so it
            # is covered by a labelled threshold test in tests/unit/macro/test_rates_state.py.
            "contradictions_exclude": ["policy_paths_disagree"],
            "forward_path_spread_bp_below_threshold": True,
            "paths_reported_separately": [
                "actual",
                "committee_projection",
                "market_implied",
            ],
            "must_not": [
                "average_any_two_policy_paths",
                "attribute_an_anonymous_sep_dot_to_the_chair",
                "treat_a_missing_dealer_path_as_a_neutral_vote",
            ],
            "market_path_is_load_bearing": False,
            "note": (
                "The dealer path is absent here.  Its absence must lower confidence and appear in "
                "confidence_reasons; it must never be filled by the other three."
            ),
        },
    }


def build(fred: Fred) -> dict[str, Any]:
    scenarios = [
        realized_inflation_scenario(
            fred,
            scenario_id="disinflation_with_sticky_services",
            as_of="2023-07-28",
            period="2023-06-01",
            expect={
                "state": "WELL_ABOVE_TARGET",
                "direction": "FALLING",
                # Measured, not assumed: sticky core fell 0.81pp over the same three
                # months, so it CONFIRMS the disinflation and that rule must stay quiet.
                # What is genuinely divergent is the LEVEL gap -- headline 2.97 against
                # core 4.10 -- which is a different rule.
                "contradictions_include": ["headline_core_divergence"],
                "contradictions_exclude": [
                    "stickiness_not_confirming_disinflation",
                    "breadth_contradicts_core",
                ],
                "confidence_band": [0.55, 0.90],
                "note": (
                    "Headline and core are far apart in level while moving the same way. "
                    "Level divergence and direction divergence are separate claims and the "
                    "engine must not report one as the other."
                ),
            },
        ),
        realized_inflation_scenario(
            fred,
            scenario_id="broad_reacceleration",
            as_of="2022-02-25",
            period="2022-01-01",
            expect={
                "state": "WELL_ABOVE_TARGET",
                "direction": "RISING",
                # Median breadth (+0.89) confirms core (+1.03), but trimmed-mean runs
                # the other way (-0.90) in the same window.  Two breadth measures from
                # one publisher disagreeing is itself information and must surface.
                "contradictions_include": ["breadth_measures_disagree"],
                "contradictions_exclude": [
                    "breadth_contradicts_core",
                    "stickiness_not_confirming_disinflation",
                ],
                "confidence_band": [0.70, 1.00],
                "note": (
                    "The core move is broad on the median measure, so breadth does not "
                    "contradict core -- but the breadth measures contradict each other, "
                    "which lowers confidence without changing the state."
                ),
            },
        ),
        yield_episode_scenario(
            fred,
            scenario_id="nominal_led_by_real_yields",
            start="2024-09-01",
            end="2025-01-31",
            expect={
                "attribution": "real_led",
                "real_share_of_nominal_change": "greater_than_half",
                "must_not": ["describe_curve_slope_as_term_premium"],
                "term_premium_source_required": "cleveland_fed_model",
                "note": "Both legs move; the engine states the split instead of picking a driver.",
            },
        ),
        yield_episode_scenario(
            fred,
            scenario_id="supply_pressure_with_neutral_macro",
            start="2023-07-01",
            end="2023-11-30",
            expect={
                "attribution": "real_led",
                "breakeven_change_is_approximately_zero": True,
                "contradictions_include": [
                    "supply_pressure_without_macro_confirmation"
                ],
                "inflation_state_unchanged_by_this_episode": True,
                "note": (
                    "Nominal rises with inflation compensation flat, so nothing here is "
                    "evidence about the inflation regime."
                ),
            },
        ),
        policy_paths_scenario(),
        missing_period_scenario(fred),
        revision_scenario(fred),
    ]
    return {
        "schema_version": "1",
        "authored_at": datetime.now(UTC).isoformat(),
        "spec": "docs/superpowers/specs/2026-08-18-inflation-rates-state-design.md",
        "provenance": {
            "realized_and_market_series": "FRED/ALFRED, vintage-aware",
            "why_not_bls_or_bea": (
                "BLS returns HTTP 403 on every host from this network; BEA returns HTTP 200 with a "
                "zero-length body without a UserID.  Neither publishes vintages.  See "
                "docs/research/2026-08-18-mc2-inflation-source-probe/."
            ),
            "values_are_real": (
                "Every number was fetched from the live source at authoring time and frozen with "
                "the vintage that made it knowable."
            ),
        },
        "scenarios": scenarios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("FRED_API_KEY is required to author the fixture")

    fred = Fred(api_key)
    try:
        fixture = build(fred)
    finally:
        fred.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} with {len(fixture['scenarios'])} scenarios")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
