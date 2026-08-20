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
    prior_paths: Iterable[PolicyPath] | None = None,
    freshness_by_kind: dict[PolicyPathKind, PolicySourceFreshness] | None = None,
    missing_reasons: dict[PolicyPathKind, str] | None = None,
) -> PolicyComparison:
    """Assemble four independent slots, never a blended path.

    ``missing_reasons`` overrides the default "no PIT-eligible release" wording
    for a kind the caller could not read.  A row that exists but cannot be
    parsed is a different operational fact from one that was never published,
    and collapsing the two sends an operator looking for the wrong outage.

    ``prior_paths`` are EARLIER releases from the same publishers, attached to
    their own slot so a reader can see how one publisher moved between its own
    releases.  They are deliberately kept out of ``_contradictions``: that check
    asks whether two publishers disagree at one instant, and a release from three
    months ago disagreeing with today is the passage of time, not a contradiction.

    Their order is the CALLER's, preserved as given, and the caller is expected to
    supply newest release first.  Re-sorting them here on ``available_at`` was
    tried and is wrong for the same reason it was wrong in the query that feeds
    this: that column records when we fetched a release, so a backfill that walked
    an archive oldest-first would hand back a history in the order we happened to
    download it.  The release date lives on the observation row, which only the
    repository read can see.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    by_kind: dict[PolicyPathKind, PolicyPath] = {}
    for path in paths:
        if path.kind in by_kind:
            raise ValueError(f"duplicate policy path kind: {path.kind}")
        if path.available_at > as_of:
            raise ValueError(f"{path.kind} available after comparison as_of")
        by_kind[path.kind] = path

    earlier_by_kind: dict[PolicyPathKind, list[PolicyPath]] = {}
    for path in prior_paths or ():
        if path.available_at > as_of:
            raise ValueError(f"prior {path.kind} available after comparison as_of")
        if path.kind not in by_kind:
            raise ValueError(f"prior {path.kind} release has no current release")
        if path.source_record_id == by_kind[path.kind].source_record_id:
            continue
        earlier_by_kind.setdefault(path.kind, []).append(path)

    slots = {
        kind: PolicyPathSlot(
            kind=kind,
            path=by_kind.get(kind),
            prior=earlier_by_kind.get(kind, []),
            missing_reason=(
                None
                if kind in by_kind
                else (missing_reasons or {}).get(kind, _MISSING_REASON[kind])
            ),
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
