"""What a second version of a report is allowed to claim changed.

The delta is the reason a versioned report is worth more than a timestamped
one. These tests pin the two distinctions that make it readable: a METHOD change
is reported apart from a WORLD change, and an appearing/disappearing number is
never filtered out as immaterial.
"""

from __future__ import annotations

from uw_scan.fundamentals.report_delta import (
    MATERIAL_ABS,
    block_delta,
    manifest_delta,
    report_delta,
)
from uw_scan.storage.research_reports import content_hash


def _block(ordinal=0, kind="dimensions", title="Research-priority dimensions", **payload):
    return {
        "ordinal": ordinal,
        "block_kind": kind,
        "title": title,
        # A block reads as `payload` fresh from the assembler and as
        # `payload_jsonb` back from the DB; the delta must handle both.
        "payload": dict(payload),
        "payload_jsonb": dict(payload),
        "evidence": {},
        "derivation": None,
        "authority": None,
    }


def test_the_hash_ignores_key_order_but_not_values():
    """Otherwise the replay gate fails on Python dict ordering, not on content."""
    a = [_block(growth=1.0, valuation=2.0)]
    b = [_block(valuation=2.0, growth=1.0)]
    assert content_hash(a) == content_hash(b)

    c = [_block(growth=1.0, valuation=2.5)]
    assert content_hash(a) != content_hash(c)


def test_the_hash_ignores_block_insertion_order():
    """Ordinal is the ordering; the assembler's append order must not leak in."""
    one, two = _block(0, "scope", "S", n=1), _block(1, "risks", "R", n=2)
    assert content_hash([one, two]) == content_hash([two, one])


def test_a_method_change_is_reported_apart_from_a_value_change():
    """A composite that fell because the ENGINE changed is not news about a company."""
    prev = {
        "manifest_jsonb": {"engine_version": "fundamentals-v1:aaaaaaaa"},
        "blocks": [_block(priority=1.00)],
    }
    curr = {
        "manifest_jsonb": {"engine_version": "fundamentals-v2:bbbbbbbb"},
        "blocks": [_block(priority=0.20)],
    }
    d = report_delta(prev, curr)
    assert d["manifest"] == [
        {
            "field": "engine_version",
            "before": "fundamentals-v1:aaaaaaaa",
            "after": "fundamentals-v2:bbbbbbbb",
        }
    ]
    # The manifest clause comes FIRST in the summary so the reader reframes the
    # value move before reading it.
    assert d["summary"].startswith("1 manifest field(s) changed")
    assert "1 value(s) moved" in d["summary"]


def test_an_appearing_number_is_always_material():
    """`None` -> 0.01 is smaller than MATERIAL_ABS and still the biggest news there is."""
    prev = {"manifest_jsonb": {}, "blocks": [_block()]}
    curr = {"manifest_jsonb": {}, "blocks": [_block(fcf_margin=0.001)]}
    moved = report_delta(prev, curr)["blocks"]["moved"]
    assert moved[0]["changes"] == [
        {"path": "fcf_margin", "before": None, "after": 0.001}
    ]


def test_a_flag_flip_is_not_reported_as_a_numeric_move():
    """bool subclasses int; True->False would otherwise read as a 1.0 move."""
    prev = {"manifest_jsonb": {}, "blocks": [_block(abstains=True)]}
    curr = {"manifest_jsonb": {}, "blocks": [_block(abstains=False)]}
    assert report_delta(prev, curr)["blocks"]["moved"] == []


def test_noise_below_the_line_is_not_listed():
    prev = {"manifest_jsonb": {}, "blocks": [_block(priority=1.0)]}
    curr = {
        "manifest_jsonb": {},
        "blocks": [_block(priority=1.0 + MATERIAL_ABS / 2)],
    }
    d = report_delta(prev, curr)
    assert d["blocks"]["moved"] == []
    assert d["summary"] == "no material change"


def test_a_first_version_is_not_a_change():
    d = report_delta(None, {"manifest_jsonb": {}, "blocks": []})
    assert d["is_first_version"] is True
    assert d["summary"] == "first version; nothing to compare against"


def test_added_and_removed_blocks_are_named():
    prev = [_block(0, "scope", "S"), _block(2, "risks", "R")]
    curr = [_block(0, "scope", "S"), _block(3, "events", "E")]
    d = block_delta(prev, curr)
    assert d["added"] == [{"block_kind": "events", "title": "E"}]
    assert d["removed"] == [{"block_kind": "risks", "title": "R"}]


def test_manifest_delta_reports_both_directions():
    d = manifest_delta({"a": 1, "b": 2}, {"b": 2, "c": 3})
    assert d == [
        {"field": "a", "before": 1, "after": None},
        {"field": "c", "before": None, "after": 3},
    ]
