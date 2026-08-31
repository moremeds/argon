"""Shared report scaffolding: the frozen manifest, the basis guard, the refusal.

Split out of `research_report_assemble` on the seam that actually exists — three
per-type assemblers on one side, the three things every one of them must do on
the other. Keeping them together took that module past the 500-line budget the
moment a third report type arrived.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from uw_scan.fundamentals.claims import REGISTRY
from uw_scan.storage.research_events import ResearchEventsRepository


def _manifest(
    *,
    engine_version: str | None,
    taxonomy_version: str | None,
    evidence_policy: str,
    as_of: date,
    scope: dict[str, Any],
) -> dict[str, Any]:
    """The frozen question. Everything needed to reproduce the content."""
    return {
        "engine_version": engine_version,
        "taxonomy_version": taxonomy_version,
        "evidence_policy": evidence_policy,
        "as_of": as_of.isoformat(),
        "scope": scope,
        # Pinned so a change to the assembler itself invalidates the replay
        # rather than silently producing different content under the same
        # manifest.
        "assembler_version": "report-assembler-v1",
    }


#: Manifest fields a block's evidence may restate. If it restates one, it must
#: agree — a report that mixes two engine versions or two taxonomy versions is
#: not one answer, it is two answers stapled together, and the reader has no way
#: to tell which block came from which.
_PINNED_FIELDS = ("engine_version", "taxonomy_version")


def check_single_basis(
    manifest: dict[str, Any], blocks: list[dict[str, Any]]
) -> None:
    """Refuse a report whose blocks disagree with the manifest. Raises ValueError.

    Called before every publish and before every hash. The alternative — letting
    it through and noting the mixture in prose — produces a document whose
    numbers are individually true and jointly meaningless.
    """
    for block in blocks:
        evidence = block.get("evidence") or {}
        for field in _PINNED_FIELDS:
            if field not in evidence:
                continue
            if evidence[field] != manifest.get(field):
                raise ValueError(
                    f"block {block['block_kind']!r} claims {field}="
                    f"{evidence[field]!r} but the manifest froze "
                    f"{manifest.get(field)!r}; a report carries ONE basis"
                )
        as_of = evidence.get("as_of") or evidence.get("known_by")
        if as_of is not None and as_of != manifest.get("as_of"):
            raise ValueError(
                f"block {block['block_kind']!r} is as-of {as_of!r} but the "
                f"manifest froze {manifest.get('as_of')!r}"
            )


def _unsupported_block(
    ordinal: int, events_repo: ResearchEventsRepository, extra: list[str]
) -> dict[str, Any]:
    killed = [c for c in events_repo.classes() if c["status"] == "killed"]
    capped = [
        c.key for c in REGISTRY if c.authority.value == "descriptive"
    ]
    # Grouped by reason, not listed per class. Six classes die of one cause —
    # "it lives in SEC document text, which Argon does not fetch" — and printing
    # that sentence six times buries the one thing the reader needs, which is
    # WHICH capabilities are missing and WHY, in that order.
    by_reason: dict[str, list[str]] = {}
    for c in killed:
        by_reason.setdefault(c["rationale"], []).append(c["event_class"])
    return {
        "ordinal": ordinal,
        "block_kind": "unsupported",
        "title": "What this report cannot answer",
        "payload": {
            "killed_event_classes": [
                {"classes": sorted(classes), "why": reason}
                for reason, classes in sorted(
                    by_reason.items(), key=lambda kv: (-len(kv[1]), kv[0])
                )
            ],
            "descriptive_only": capped,
            "notes": extra,
        },
        "derivation": (
            "research_event_classes where status='killed', plus claim-registry "
            "entries capped at descriptive"
        ),
    }
