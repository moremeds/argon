"""Identity and candidate-id helpers for Trade Insights AI validators."""

from __future__ import annotations

from typing import Any

from uw_scan.reports._shared_validation import STRATEGY_FAMILY_IDS

def _candidate_map(deterministic_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(candidate.get("idea_id")): candidate
        for candidate in deterministic_payload.get("candidate_structures") or []
        if candidate.get("idea_id") is not None
    }


def _known_idea_id(idea_id: str, candidates: dict[str, dict[str, Any]]) -> bool:
    return idea_id in candidates or idea_id in STRATEGY_FAMILY_IDS
