"""Assembly of the per-ticker fundamental card (spec §7, deterministic blocks).

Pure compute — no I/O, no DB. Takes a persisted `fundamental_scores` row plus the
violations attached to the observations it was computed from, and returns the
shape the API model serializes.

**This is the reduced card, deliberately.** Of §7's nine blocks only three have
backing data at stage 2 — subscores/composite, coverage, and provenance. The rest
(anchor band, method+confidence, target gap, concentration, narrative, audit
verdicts) need stages 3-5 and are absent rather than stubbed: an empty block that
looks like a block reads as "no data for this name", which is a different and
false claim.

Two honesty constraints are enforced here rather than in the UI, because a
rendering choice can be changed by anyone styling a component:

1. A feature whose *input* was flagged renders as `na`. The stored value is left
   exactly as computed — editing `features.py` would change validated math and
   break the reproducibility of every published result.
2. `direction` is carried per feature and is None for three of the seven. A card
   that ramps all seven "green = high" asserts directions the 2026-08-12
   validation measured as inverted or never tested.
"""

from __future__ import annotations

from typing import Any

from uw_scan.fundamentals.features import (
    FEATURE_DIRECTION,
    FEATURE_INPUTS,
    FEATURE_UNITS,
    FEATURES,
)


def _num(value: Any) -> float | None:
    """NUMERIC columns come back as Decimal; the contract is float | None."""
    return None if value is None else float(value)


def build_card(
    *,
    ticker: str,
    row: dict[str, Any],
    violated: dict[str, list[str]],
    engine_version: str,
) -> dict[str, Any]:
    """One score row + its input violations -> the card payload.

    `violated` maps a raw provider field (`gross_profit`) to the check names that
    fired on it, as returned by `FundamentalObsRepository.violated_fields`.
    """
    subscores: list[dict[str, Any]] = []
    missing: list[str] = []
    suppressed: list[str] = []

    for feature in FEATURES:
        checks = sorted(
            {
                check
                for source in FEATURE_INPUTS[feature]
                for check in violated.get(source, [])
            }
        )
        value = _num(row.get(feature))
        if checks:
            # Suppressed, not missing: we HAVE a number and are declining to show
            # it. The coverage block reports the two separately so a reader can
            # tell "never reported" from "reported and not believed".
            suppressed.append(feature)
            value = None
        elif value is None:
            missing.append(feature)
        subscores.append(
            {
                "feature": feature,
                "value": value,
                "unit": FEATURE_UNITS[feature],
                "direction": FEATURE_DIRECTION[feature],
                "suppressed_by": checks,
            }
        )

    return {
        "ticker": ticker,
        "composite": _num(row.get("composite")),
        "subscores": subscores,
        "coverage": {
            # Straight from the persisted column rather than recomputed: this is
            # what the composite was actually scored on, and a recomputation here
            # would silently diverge if suppression changed after the fact.
            "features_present": int(row["features_present"]),
            "features_total": len(FEATURES),
            "missing": missing,
            "suppressed": suppressed,
        },
        "provenance": {
            "engine_version": engine_version,
            "inputs_hash": row["inputs_hash"],
            "as_of": row["as_of"],
            "period_end": row["period_end"],
            # The date the world could have known this. The card renders THIS,
            # never the bucket `as_of` — 28 rows carry a future `as_of` purely
            # because the 45-day filing fallback overshoots the newest quarter.
            "knowledge_date": row["knowledge_date"],
            "filing_date_known": bool(row["filing_date_known"]),
            "source_obs_count": len(row.get("source_obs_ids") or []),
        },
    }
