"""When a statement content VERSION became usable — the vocabulary, frozen.

Pure compute: four evidence classes, two historical admission policies, and the
validation that keeps a timestamp attached only to a class that earns one. No
SQL, no provider parsing, no scoring.

WHY THIS MODULE EXISTS AT ALL
-----------------------------
`fundamental_statement_obs` is already an honest immutable ledger: one row per
normalized content version, a restatement lands as a NEW row, nothing is edited
in place. What it never carried is *when each version became available*, so the
reader answered that question with the only ordering it had — `obs_id DESC` —
and with NO CUTOFF AT ALL. Every historical question got today's panel, so
scoring buckets consumed figures the market had not seen.

The ordering itself is not what bit. `obs_id` is a BIGSERIAL assigned in the same
INSERT as `first_observed_at`, so an `obs_id` ordering and a capture-time ordering
are monotonic with each other by construction and cannot disagree — measured 0
disagreements over all 200 multi-version identities on production, 2026-08-24. The
ordering becomes load-bearing only once `true_pit` exists, because a publication
date is sourced independently of insertion order. Until then this module's
deliverable is the CUTOFF, not the sort key.

Availability is evidence, not a column default, and the evidence for one version
can STRENGTHEN later (a capture bound today, an SEC amendment artifact next
month). That is why claims live in an append-only child table and why the class
lives here rather than as a CHECK constraint alone.

THE FOUR CLASSES
----------------
`true_pit`          positive version-level publication/amendment evidence for
                    this exact content. The only class a leak-free replay may use.
`capture_bounded`   Argon holds this exact content and first saw it at
                    `available_at`. Safe to admit at or after that instant, and
                    deliberately conservative: the world may well have known
                    earlier, and this class never claims otherwise.
`current_vintage`   usable for today's page, no historical claim whatsoever.
                    Every legacy row starts here.
`unknown`           not even a usable timestamp. Fails closed everywhere.

The period's `filing_published_at` does NOT promote a version to `true_pit`. It
describes when the ORIGINAL filing was published; a later content hash for the
same period is a different artifact and inherits none of that date's authority.
Treating the two as one is exactly the confusion this module is here to prevent.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any


class EvidenceClass(StrEnum):
    """How strongly a content version's availability instant is supported."""

    TRUE_PIT = "true_pit"
    CAPTURE_BOUNDED = "capture_bounded"
    CURRENT_VINTAGE = "current_vintage"
    UNKNOWN = "unknown"


class EvidencePolicy(StrEnum):
    """What a historical (as-of) read is willing to admit.

    There is deliberately no `ANY` or `BEST_EFFORT` member. The permissive read
    is a separate reader — `current_statement_panel` — because a policy that
    silently degrades to current-vintage is indistinguishable from the bug this
    work exists to fix.
    """

    TRUE_PIT_ONLY = "true_pit_only"
    CAPTURE_BOUNDED = "capture_bounded"


#: Classes carrying an availability instant. The complement must not carry one:
#: a `current_vintage` row with a timestamp reads as a historical claim to every
#: later query, which is the failure mode in miniature.
TIMED_CLASSES = frozenset({EvidenceClass.TRUE_PIT, EvidenceClass.CAPTURE_BOUNDED})

EVIDENCE_CLASSES = frozenset(EvidenceClass)

_POLICY_CLASSES: dict[EvidencePolicy, frozenset[EvidenceClass]] = {
    EvidencePolicy.TRUE_PIT_ONLY: frozenset({EvidenceClass.TRUE_PIT}),
    EvidencePolicy.CAPTURE_BOUNDED: TIMED_CLASSES,
}

#: Ordering used ONLY to break a tie between two claims supporting the same
#: version at the same instant, and to pick which claim gets named in audit
#: metadata. It is never an ordering over versions — that is `available_at`'s job.
_STRENGTH: dict[EvidenceClass, int] = {
    EvidenceClass.TRUE_PIT: 3,
    EvidenceClass.CAPTURE_BOUNDED: 2,
    EvidenceClass.CURRENT_VINTAGE: 1,
    EvidenceClass.UNKNOWN: 0,
}

#: Deterministic rule identities. `UNIQUE (obs_id, claim_key)` makes a replay of
#: the same rule over the same observation a no-op, so these are the reason the
#: backfill is resumable without a progress table. Bump the suffix to re-derive
#: under a new rule; never mutate the claims an old rule wrote.
CLAIM_KEY_LEGACY_CURRENT_VINTAGE = "legacy_current_vintage:v1"
CLAIM_KEY_CAPTURE_FIRST_OBSERVED = "capture:first_observed_at:v1"

#: `evidence_source` values these two rules stamp. A source names WHO vouched,
#: the class names HOW STRONGLY.
SOURCE_ARGON_LEGACY = "argon_legacy_classification"
SOURCE_ARGON_CAPTURE = "argon_capture"


def normalize_claim(
    evidence_class: EvidenceClass | str, available_at: datetime | None
) -> tuple[EvidenceClass, datetime | None]:
    """Validate one claim's (class, instant) pair. Raises `ValueError` on abuse.

    Called by every writer before SQL so the refusal carries a sentence rather
    than a constraint name, and so a naive datetime never reaches a comparison
    against an aware cutoff.
    """
    try:
        cls = EvidenceClass(evidence_class)
    except ValueError as exc:
        raise ValueError(
            f"unknown evidence_class {evidence_class!r}; "
            f"expected one of {sorted(c.value for c in EvidenceClass)}"
        ) from exc

    if cls in TIMED_CLASSES:
        if available_at is None:
            raise ValueError(f"{cls.value} requires available_at")
        if available_at.tzinfo is None or available_at.utcoffset() is None:
            raise ValueError(
                f"{cls.value} available_at must be timezone-aware; "
                "a naive instant cannot be compared against an as-of cutoff"
            )
    elif available_at is not None:
        raise ValueError(
            f"{cls.value} must not carry available_at — it makes no "
            "version-availability claim"
        )
    return cls, available_at


def policy_classes(policy: EvidencePolicy | str) -> frozenset[EvidenceClass]:
    """The classes `policy` admits. Frozen, so a caller cannot widen it in place."""
    return _POLICY_CLASSES[EvidencePolicy(policy)]


def admits(policy: EvidencePolicy | str, evidence_class: EvidenceClass | str) -> bool:
    """Whether `policy` accepts a claim of `evidence_class` as usable history."""
    return EvidenceClass(evidence_class) in policy_classes(policy)


def claim_strength(evidence_class: EvidenceClass | str) -> int:
    """Tie-break rank — higher wins when two claims share an instant."""
    return _STRENGTH[EvidenceClass(evidence_class)]


def audit_violations(report: Mapping[str, Any]) -> list[str]:
    """Invariants a coverage report must satisfy, as sentences. Empty is a pass.

    These are the checks that make the artifact worth publishing. A coverage
    report nobody can falsify is a press release: every line below names a way
    the classification could be quietly wrong while every count still looked
    plausible.
    """
    problems: list[str] = []

    by_class = report.get("by_evidence_class") or {}
    if sum(by_class.values()) != report.get("claims", 0):
        problems.append(
            f"class counts sum to {sum(by_class.values())} but the table holds "
            f"{report.get('claims')} claims"
        )

    unknown = set(by_class) - {c.value for c in EvidenceClass}
    if unknown:
        problems.append(f"claims carry classes outside the vocabulary: {sorted(unknown)}")

    if report.get("true_pit_without_evidence"):
        problems.append(
            f"{report['true_pit_without_evidence']} true_pit claims carry no "
            "artifact reference or no instant — true-PIT is a claim about a "
            "specific publication and must point at it"
        )

    if report.get("untimed_claims_carrying_an_instant"):
        problems.append(
            f"{report['untimed_claims_carrying_an_instant']} current_vintage/"
            "unknown claims carry available_at — they make no availability claim "
            "and a timestamp on them reads as one"
        )

    if report.get("unclaimed_observations"):
        problems.append(
            f"{report['unclaimed_observations']} observations carry no claim at "
            "all — they are invisible to every historical policy"
        )

    for row in report.get("selection_check") or []:
        if row["available_at"] > row["cutoff"]:
            problems.append(
                f"as-of selection returned {row['ticker']} {row['period']} "
                f"available {row['available_at']} past its cutoff {row['cutoff']}"
            )

    return problems
