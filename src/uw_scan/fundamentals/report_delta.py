"""What changed between two report versions. Pure compute, no I/O.

A versioned report whose only feature is "there is a newer one" answers nothing.
The delta is the product: an operator re-opening a report in November asks what
moved since August, and every block is comparable because both versions froze
their manifests.

WHY A MANIFEST DIFFERENCE IS REPORTED SEPARATELY FROM A VALUE DIFFERENCE
-----------------------------------------------------------------------
Two reports can differ because the WORLD moved or because the METHOD did. A
company's priority falling 0.4 means one thing when both versions ran under
`fundamentals-v2` and a completely different thing when the engine changed
between them. Collapsing the two into one "changed" list is how a method change
gets read as news.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

#: Absolute change below which a numeric move is not worth an operator's
#: attention. Not a significance threshold — nothing here is a test — just the
#: line under which a report would be listing noise.
MATERIAL_ABS = 0.05


def _index(blocks: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping]:
    return {(b["block_kind"], b["title"]): b for b in blocks}


def _numeric_leaves(payload: Any, prefix: str = "") -> dict[str, float]:
    """Flatten a payload to its numeric leaves, keyed by path.

    Lists are indexed rather than zipped by position-independent key, which is
    correct here because every list a report block emits is already ordered
    deterministically by the assembler.
    """
    out: dict[str, float] = {}
    if isinstance(payload, Mapping):
        for k, v in payload.items():
            out.update(_numeric_leaves(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(payload, (list, tuple)):
        for i, v in enumerate(payload):
            out.update(_numeric_leaves(v, f"{prefix}[{i}]"))
    elif isinstance(payload, bool):
        # bool is an int subclass; treating True as 1.0 would report a flag flip
        # as a 1.0 numeric move.
        pass
    elif isinstance(payload, (int, float)):
        out[prefix] = float(payload)
    return out


def manifest_delta(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Which frozen versions/as-ofs changed between the two reports."""
    keys = set(previous) | set(current)
    out = []
    for key in sorted(keys):
        before, after = previous.get(key), current.get(key)
        if before != after:
            out.append({"field": key, "before": before, "after": after})
    return out


def block_delta(
    previous: Sequence[Mapping[str, Any]],
    current: Sequence[Mapping[str, Any]],
    *,
    material_abs: float = MATERIAL_ABS,
) -> dict[str, Any]:
    """Added, removed, and materially-moved blocks between two versions."""
    prev_idx, curr_idx = _index(previous), _index(current)
    added = sorted(set(curr_idx) - set(prev_idx))
    removed = sorted(set(prev_idx) - set(curr_idx))

    moved: list[dict[str, Any]] = []
    for key in sorted(set(prev_idx) & set(curr_idx)):
        before = _numeric_leaves(prev_idx[key].get("payload_jsonb")
                                 or prev_idx[key].get("payload") or {})
        after = _numeric_leaves(curr_idx[key].get("payload_jsonb")
                                or curr_idx[key].get("payload") or {})
        changes = []
        for path in sorted(set(before) | set(after)):
            b, a = before.get(path), after.get(path)
            if b is None or a is None:
                # An appearing or disappearing number is always material: it is
                # the difference between "we know this" and "we do not".
                changes.append({"path": path, "before": b, "after": a})
            elif abs(a - b) >= material_abs:
                changes.append(
                    {"path": path, "before": b, "after": a, "change": a - b}
                )
        if changes:
            moved.append(
                {"block_kind": key[0], "title": key[1], "changes": changes}
            )

    return {
        "added": [{"block_kind": k, "title": t} for k, t in added],
        "removed": [{"block_kind": k, "title": t} for k, t in removed],
        "moved": moved,
    }


def report_delta(
    previous: Mapping[str, Any] | None,
    current: Mapping[str, Any],
    *,
    material_abs: float = MATERIAL_ABS,
) -> dict[str, Any]:
    """The full delta. `None` previous means this is a first version, not a change."""
    if previous is None:
        return {
            "is_first_version": True,
            "manifest": [],
            "blocks": {"added": [], "removed": [], "moved": []},
            "summary": "first version; nothing to compare against",
        }

    manifest = manifest_delta(
        previous.get("manifest_jsonb") or {}, current.get("manifest_jsonb") or {}
    )
    blocks = block_delta(
        previous.get("blocks") or [], current.get("blocks") or [],
        material_abs=material_abs,
    )
    n_moved = sum(len(m["changes"]) for m in blocks["moved"])
    parts = []
    if manifest:
        # Stated FIRST and separately: a method change reframes every value
        # change under it, and burying it in a list of movements invites the
        # reader to treat a re-versioning as news about companies.
        parts.append(
            f"{len(manifest)} manifest field(s) changed "
            f"({', '.join(m['field'] for m in manifest)})"
        )
    if blocks["added"]:
        parts.append(f"{len(blocks['added'])} block(s) added")
    if blocks["removed"]:
        parts.append(f"{len(blocks['removed'])} block(s) removed")
    if n_moved:
        parts.append(f"{n_moved} value(s) moved by >= {material_abs}")
    return {
        "is_first_version": False,
        "manifest": manifest,
        "blocks": blocks,
        "summary": "; ".join(parts) if parts else "no material change",
    }
