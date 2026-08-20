#!/usr/bin/env python
"""Add the observation history the MC2 inflation engine needs to derive its own rates.

The original fixture froze one value per series per scenario plus the derived
year-over-year and three-month changes.  That is enough to state a prediction but not
enough to *check* one: an engine that is handed a YoY has not computed a YoY, and the
plan requires the engine to compute publisher transforms itself from observations
available by ``as_of``.

So this pass adds, per inflation scenario, the sixteen months of real history ending at
the target period -- enough for a year-over-year at the target period and another one
three months earlier.  It is strictly additive.  ``derived_from_inputs`` and ``expect``
are preregistered predictions and are never touched; in fact this script asserts the
newly fetched target-period value equals the one already frozen, so a silent publisher
restatement between the two authoring runs cannot slip through unnoticed.

Availability here is the TRUE first-publication instant.  The original pass read ALFRED
with ``realtime_start = realtime_end = as_of``, which makes the publisher clamp every
returned window to the query window and report ``realtime_start = as_of`` for every row.
That is an artifact of asking, not a fact about publishing.  Reading the unbounded
vintage history and selecting the row in force at ``as_of`` recovers the real instant,
which is what the freshness term has to measure against.

Reproduce::

    FRED_API_KEY=... uv run python scripts/build_inflation_rates_golden_history.py \
        --fixture tests/fixtures/macro/inflation_rates_golden.json
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from build_inflation_rates_golden import Fred, SERIES_UNITS

#: Sixteen months: a YoY needs twelve, and the three-month change of that YoY needs
#: three more, plus the target period itself.
HISTORY_MONTHS = 16

SERIES_ROLES = (
    ("PCEPILFE", "realized"),
    ("PCEPI", "realized"),
    ("CPILFESL", "realized"),
    ("CPIAUCSL", "realized"),
    ("MEDCPIM158SFRBCLE", "breadth"),
    ("TRMMEANCPIM158SFRBCLE", "breadth"),
    ("CORESTICKM159SFRBATL", "stickiness"),
    ("MICH", "expectations_survey"),
)


def _shift_months(period: str, back: int) -> str:
    year, month, day = (int(part) for part in period.split("-"))
    total = year * 12 + (month - 1) - back
    return f"{total // 12:04d}-{total % 12 + 1:02d}-{day:02d}"


def in_force_at(rows: list[dict[str, str]], as_of: str) -> list[dict[str, str]]:
    """One row per period: the vintage that was the published value on ``as_of``.

    ``realtime_end`` is the last day the value was current, inclusive, so the test is
    ``realtime_start <= as_of <= realtime_end`` rather than a half-open comparison.
    """
    chosen: dict[str, dict[str, str]] = {}
    for row in rows:
        if row["realtime_start"] <= as_of <= row["realtime_end"]:
            chosen[row["date"]] = {
                "period_end": row["date"],
                "value": row["value"],
                "available_at": row["realtime_start"],
            }
    return [chosen[period] for period in sorted(chosen)]


def history_for(fred: Fred, scenario: dict[str, Any]) -> dict[str, Any]:
    as_of = scenario["as_of"]
    period = scenario["target_period"]
    start = _shift_months(period, HISTORY_MONTHS - 1)
    frozen = {row["series_id"]: row["value"] for row in scenario["inputs"]}

    history: dict[str, Any] = {}
    for series_id, _role in SERIES_ROLES:
        rows = in_force_at(fred.all_vintages(series_id, start, period), as_of)
        if not rows:
            continue
        unit, transform = SERIES_UNITS[series_id]
        at_target = [row for row in rows if row["period_end"] == period]
        if series_id in frozen and at_target:
            assert at_target[0]["value"] == frozen[series_id], (
                f"{series_id} at {period} now reads {at_target[0]['value']} but the "
                f"fixture froze {frozen[series_id]}; a restatement between authoring "
                "runs must be recorded deliberately, not absorbed"
            )
        history[series_id] = {
            "unit": unit,
            "publisher_transform": transform,
            "observations": rows,
        }
    return history


def window_history_for(fred: Fred, scenario: dict[str, Any]) -> dict[str, Any]:
    """History for a scenario that froze an explicit observed window.

    The publication-gap scenario recorded which periods exist but not when each became
    knowable, and the engine needs the latter to select vintages at all.  The frozen
    values are asserted unchanged so this pass cannot quietly repair the gap it exists
    to demonstrate.
    """
    as_of = scenario["as_of"]
    history: dict[str, Any] = {}
    for row in scenario["inputs"]:
        window = row["observed_window"]
        series_id = row["series_id"]
        rows = in_force_at(
            fred.all_vintages(series_id, min(window), max(window)), as_of
        )
        observed = {item["period_end"]: item["value"] for item in rows}
        assert observed == window, (
            f"{series_id} window now reads {observed} but the fixture froze {window}"
        )
        unit, transform = SERIES_UNITS[series_id]
        history[series_id] = {
            "unit": unit,
            "publisher_transform": transform,
            "observations": rows,
        }
    return history


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("FRED_API_KEY is required to author the fixture")

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    fred = Fred(api_key)
    added = 0
    try:
        for scenario in fixture["scenarios"]:
            if scenario["domain"] != "inflation" or "target_period" not in scenario:
                continue
            if any("observed_window" in row for row in scenario["inputs"]):
                scenario["observation_history"] = window_history_for(fred, scenario)
                added += 1
                print(
                    f"{scenario['id']}: {len(scenario['observation_history'])} series"
                )
                continue
            if not any("value" in row for row in scenario["inputs"]):
                continue  # already carries its own vintage list
            scenario["observation_history"] = history_for(fred, scenario)
            added += 1
            print(f"{scenario['id']}: {len(scenario['observation_history'])} series")
    finally:
        fred.close()

    args.fixture.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"added history to {added} scenarios in {args.fixture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
