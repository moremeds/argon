from decimal import Decimal

from uw_scan.cards.canary_payload_hash import canonical_payload_hash


def test_hash_stable_across_two_runs():
    payload = {"a": 1, "b": [3.14, 2.718], "c": {"nested": True}}
    assert canonical_payload_hash(payload) == canonical_payload_hash(payload)


def test_key_reorder_does_not_change_hash():
    p1 = {"a": 1, "b": 2}
    p2 = {"b": 2, "a": 1}
    assert canonical_payload_hash(p1) == canonical_payload_hash(p2)


def test_decimal_vs_float_same_value_same_hash():
    p1 = {"score": 47.300000}
    p2 = {"score": Decimal("47.300000")}
    assert canonical_payload_hash(p1) == canonical_payload_hash(p2)


def test_prior_field_is_excluded():
    p1 = {"a": 1}
    p2 = {"a": 1, "_prior": {"row_id": 99, "payload": {"a": 999}}}
    assert canonical_payload_hash(p1) == canonical_payload_hash(p2)


def test_pinned_hash_for_known_payload():
    """Regression — if this fixture's hash changes, the serialization format
    drifted. Update the constant ONLY when the change is intentional and
    versioned via composite_version bump.

    v0.4: pinned digest is HARDCODED below — no placeholder branch. The
    digest was computed once against the v0.4 _normalize implementation
    (sorted keys, decimal-string Decimal+float, no _prior, no whitespace).
    A future change to the normalizer that produces a different digest
    fails this test loudly, forcing a composite_version bump or revert.
    """
    payload = {
        "date": "2026-05-26",
        "canary": {"score": 47.3, "band": "WATCH"},
    }
    EXPECTED = "04a26d1f6f4ce814963b500e30a23f01c4e8a86d268370140e58d78d49af01c4"
    assert canonical_payload_hash(payload) == EXPECTED
