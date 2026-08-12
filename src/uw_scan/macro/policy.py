"""Pure assembly of independent policy paths."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal

from uw_scan.models.macro import (
    PolicyComparison,
    PolicyPath,
    PolicyPathKind,
    PolicyPathSlot,
    PolicySourceFreshness,
)

_KINDS: tuple[PolicyPathKind, ...] = (
    "actual",
    "committee_projection",
    "dealer_expectations",
    "market_implied",
)
_MISSING_REASON = {
    kind: f"no PIT-eligible {kind.replace('_', ' ')} policy release" for kind in _KINDS
}


def assemble_policy_paths(
    paths: Iterable[PolicyPath],
    *,
    as_of: datetime,
    freshness_by_kind: dict[PolicyPathKind, PolicySourceFreshness] | None = None,
) -> PolicyComparison:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    by_kind: dict[PolicyPathKind, PolicyPath] = {}
    for path in paths:
        if path.kind in by_kind:
            raise ValueError(f"duplicate policy path kind: {path.kind}")
        if path.available_at > as_of:
            raise ValueError(f"{path.kind} available after comparison as_of")
        by_kind[path.kind] = path

    slots = {
        kind: PolicyPathSlot(
            kind=kind,
            path=by_kind.get(kind),
            missing_reason=None if kind in by_kind else _MISSING_REASON[kind],
            freshness=(freshness_by_kind or {}).get(
                kind,
                PolicySourceFreshness(
                    source=by_kind[kind].source if kind in by_kind else kind,
                    status="missing",
                ),
            ),
        )
        for kind in _KINDS
    }
    return PolicyComparison(
        as_of=as_of,
        actual=slots["actual"],
        committee_projection=slots["committee_projection"],
        dealer_expectations=slots["dealer_expectations"],
        market_implied=slots["market_implied"],
        contradictions=_contradictions(by_kind),
    )


def _contradictions(paths: dict[PolicyPathKind, PolicyPath]) -> list[str]:
    indexed = {
        kind: {point.horizon: point.rate_percent for point in path.points}
        for kind, path in paths.items()
    }
    output: list[str] = []
    kinds = [kind for kind in _KINDS if kind in indexed]
    for index, left_kind in enumerate(kinds):
        for right_kind in kinds[index + 1 :]:
            for horizon in sorted(
                indexed[left_kind].keys() & indexed[right_kind].keys()
            ):
                difference_bps = abs(
                    indexed[left_kind][horizon] - indexed[right_kind][horizon]
                ) * Decimal(100)
                if difference_bps == 0:
                    continue
                output.append(
                    f"{left_kind} vs {right_kind} differ by "
                    f"{_render_decimal(difference_bps)} bps at {horizon}"
                )
    return output


def _render_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
