#!/usr/bin/env python
"""Measure the only decomposition residual in the rates domain that can carry information.

Two sums here look like reconciliations and are identities:

* FRED derives ``T10YIE`` as ``DGS10 - DFII10``, so nominal = real + breakeven cannot
  fail. Measured residual across both probed yield episodes: 0.0bp.
* Inside the Cleveland Fed model, the expected short real rate is itself derived by
  subtracting the real term premium from the modelled real yield, so adding the premium
  back reproduces the modelled nominal by construction.

What is left is the gap between the Cleveland model's nominal and the yield the market
actually traded. This probe measures its distribution so the engine's tolerance is set
from evidence rather than picked, and records whether a 25bp tolerance would fire
routinely or rarely.

Reproduce::

    FRED_API_KEY=... uv run python scripts/research/mc2_decomposition_residual_probe.py \
        --out docs/research/2026-08-18-mc2-decomposition-residual
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from uw_scan.sources.cleveland_fed import ClevelandFedInflationProvider

FRED_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
UA = {"User-Agent": "argon-macro-research/0.1 (personal research desk)"}


def fetch_dgs10(api_key: str) -> dict[date, Decimal]:
    with httpx.Client(timeout=45.0, headers=UA) as client:
        response = client.get(
            FRED_OBSERVATIONS,
            params={
                "series_id": "DGS10",
                "file_type": "json",
                "api_key": api_key,
                "observation_start": "1999-01-01",
            },
        )
        response.raise_for_status()
    return {
        date.fromisoformat(row["date"]): Decimal(row["value"])
        for row in response.json()["observations"]
        if row["value"] != "."
    }


def first_traded_on_or_after(
    prices: dict[date, Decimal], start: date
) -> Decimal | None:
    """The Cleveland model is dated to the first of the month; markets are not open then."""
    candidates = sorted(day for day in prices if start <= day <= _plus_days(start, 7))
    return prices[candidates[0]] if candidates else None


def _plus_days(day: date, count: int) -> date:
    return date.fromordinal(day.toordinal() + count)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    api_key = os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("FRED_API_KEY is required")

    with ClevelandFedInflationProvider() as provider:
        model_rows = provider.fetch_model_rows()
    traded = fetch_dgs10(api_key)

    residuals: list[dict[str, Any]] = []
    for row in model_rows:
        modelled = (
            row.model_real_yield_10y
            + row.expected_inflation_10y
            + row.inflation_risk_premium_10y
        )
        market = first_traded_on_or_after(traded, row.obs_date)
        if market is None:
            continue
        residuals.append(
            {
                "obs_date": row.obs_date.isoformat(),
                "modelled_nominal_10y": float(modelled),
                "traded_nominal_10y": float(market),
                "residual_bps": float((market - Decimal(str(modelled))) * 100),
                # Recomputed here to show the intra-model sum is a no-op, not a check.
                "intra_model_identity_residual_bps": float(
                    (
                        Decimal(str(modelled))
                        - (
                            Decimal(
                                str(
                                    row.model_real_yield_10y - row.real_risk_premium_10y
                                )
                            )
                            + Decimal(str(row.expected_inflation_10y))
                            + Decimal(str(row.real_risk_premium_10y))
                            + Decimal(str(row.inflation_risk_premium_10y))
                        )
                    )
                    * 100
                ),
            }
        )

    absolute = [abs(row["residual_bps"]) for row in residuals]
    recent = [
        abs(row["residual_bps"]) for row in residuals if row["obs_date"] >= "2016-01-01"
    ]
    identity = [abs(row["intra_model_identity_residual_bps"]) for row in residuals]
    summary = {
        "measured_at": datetime.now(UTC).isoformat(),
        "n_months": len(residuals),
        "window": [residuals[0]["obs_date"], residuals[-1]["obs_date"]],
        "abs_residual_bps": _distribution(absolute),
        "abs_residual_bps_since_2016": _distribution(recent),
        "share_exceeding_25bp": round(
            sum(1 for value in absolute if value > 25) / len(absolute), 4
        ),
        "share_exceeding_50bp": round(
            sum(1 for value in absolute if value > 50) / len(absolute), 4
        ),
        "share_exceeding_100bp": round(
            sum(1 for value in absolute if value > 100) / len(absolute), 4
        ),
        "intra_model_identity_max_abs_bps": max(identity),
        "intra_model_identity_note": (
            "The model's own components reproduce its nominal to floating-point noise "
            "because the expected short real rate is DEFINED as the modelled real yield "
            "minus the real term premium. A tolerance test over them asserts an identity "
            "against itself."
        ),
    }

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "residuals.json").write_text(
        json.dumps({"summary": summary, "rows": residuals}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))
    return 0


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "median": round(statistics.median(ordered), 1),
        "p75": round(ordered[int(len(ordered) * 0.75)], 1),
        "p90": round(ordered[int(len(ordered) * 0.90)], 1),
        "max": round(ordered[-1], 1),
    }


if __name__ == "__main__":
    raise SystemExit(main())
