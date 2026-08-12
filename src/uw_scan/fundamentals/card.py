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


def _checks_for(feature: str, violated: dict[str, list[str]]) -> list[str]:
    """Check names firing on any raw field this feature consumes."""
    return sorted(
        {
            check
            for source in FEATURE_INPUTS[feature]
            for check in violated.get(source, [])
        }
    )


def _row_violations(
    row: dict[str, Any], by_obs: dict[int, dict[str, list[str]]]
) -> dict[str, list[str]]:
    """Collapse one score row's observations into field -> checks."""
    out: dict[str, list[str]] = {}
    for obs_id in row.get("source_obs_ids") or []:
        for field, checks in by_obs.get(obs_id, {}).items():
            out.setdefault(field, []).extend(checks)
    return out


def build_history(
    series: list[dict[str, Any]],
    by_obs: dict[int, dict[str, list[str]]],
) -> dict[str, Any]:
    """A ticker's score series reshaped for plotting, oldest first.

    Suppressed points become `null` rather than being dropped, so the x-axis
    stays aligned across all seven features and the renderer draws a GAP. A
    dropped point would silently shift the line and interpolate straight through
    a quarter we do not believe — a smooth, confident, wrong chart, which is
    worse than a broken one.
    """
    dates: list[str] = []
    composite: list[float | None] = []
    features: dict[str, list[float | None]] = {f: [] for f in FEATURES}

    for row in series:
        dates.append(row["knowledge_date"].isoformat())
        composite.append(_num(row.get("composite")))
        violated = _row_violations(row, by_obs)
        for feature in FEATURES:
            value = _num(row.get(feature))
            features[feature].append(None if _checks_for(feature, violated) else value)
    return {"dates": dates, "composite": composite, "features": features}


def build_percentiles(
    cross_section: list[dict[str, Any]],
    by_obs: dict[int, dict[str, list[str]]],
    ticker: str,
) -> dict[str, Any]:
    """Where one name sits in its knowledge-quarter panel, per feature.

    Disbelieved values are removed from the PANEL, not just from the subject.
    Leaving them in would rank every name against ~46 tickers whose
    `gross_margin` reads exactly 1.0 because UW echoed revenue into gross
    profit — the top of that distribution would be built from the very rows the
    card refuses to display.

    A percentile is locational and nothing more. It is not a quality score and
    not an expected return: the 2026-08-12 cost study measured zero gross alpha
    from this composite at every slice.
    """
    clean: dict[str, list[float]] = {f: [] for f in FEATURES}
    clean["composite"] = []
    subject: dict[str, float | None] = {}

    for row in cross_section:
        violated = _row_violations(row, by_obs)
        for key in (*FEATURES, "composite"):
            value = _num(row.get(key))
            if key != "composite" and _checks_for(key, violated):
                value = None
            if value is not None:
                clean[key].append(value)
            if row["ticker"] == ticker:
                subject[key] = value

    out: dict[str, Any] = {"panel_size": len(cross_section), "values": {}}
    for key, values in clean.items():
        mine = subject.get(key)
        if mine is None or not values:
            out["values"][key] = None
            continue
        at_or_below = sum(1 for v in values if v <= mine)
        out["values"][key] = {
            "percentile": at_or_below / len(values),
            # Stated per feature because it differs: a name missing `roe` is
            # absent from that panel but present in the others, and a percentile
            # whose denominator is unnamed is not a fact.
            "n": len(values),
        }
    return out


def build_card(
    *,
    ticker: str,
    row: dict[str, Any],
    violated: dict[str, list[str]],
    engine_version: str,
    history: dict[str, Any] | None = None,
    percentiles: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One score row + its input violations -> the card payload.

    `violated` maps a raw provider field (`gross_profit`) to the check names that
    fired on it, as returned by `FundamentalObsRepository.violated_fields`.

    `history` and `percentiles` are optional so the card still assembles when a
    name has one quarter or sits in an empty bucket — a trajectory is context,
    not a precondition for stating a level.
    """
    subscores: list[dict[str, Any]] = []
    missing: list[str] = []
    suppressed: list[str] = []

    for feature in FEATURES:
        checks = _checks_for(feature, violated)
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
                "series": (history or {}).get("features", {}).get(feature) or [],
                "percentile": ((percentiles or {}).get("values") or {}).get(feature),
            }
        )

    return {
        "ticker": ticker,
        "composite": _num(row.get("composite")),
        "composite_series": (history or {}).get("composite") or [],
        "composite_percentile": ((percentiles or {}).get("values") or {}).get(
            "composite"
        ),
        "series_dates": (history or {}).get("dates") or [],
        "panel_size": (percentiles or {}).get("panel_size") or 0,
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
