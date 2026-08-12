from __future__ import annotations

from copy import deepcopy

import pytest

from scripts.research.macro_legacy_inventory import (
    ALLOWED_DOMAINS,
    RELATION_CONTRACTS,
    REQUIRED_RELATIONS,
    validate_inventory,
)


def _inventory() -> dict:
    relations = []
    for name in sorted(REQUIRED_RELATIONS):
        contract = RELATION_CONTRACTS[name]
        relations.append(
            {
                "name": name,
                "relation_kind": contract["relation_kind"],
                "row_count": 0,
                "primary_key": [],
                "date_span": {"min": None, "max": None},
                "dimensions": {},
                "contract": contract,
            }
        )
    return {"relations": relations}


def test_inventory_contract_covers_current_rates_and_gold_relations() -> None:
    assert len(REQUIRED_RELATIONS) == 19
    assert set(RELATION_CONTRACTS) == REQUIRED_RELATIONS
    assert RELATION_CONTRACTS["wgc_etf_monthly_canonical"]["relation_kind"] == "view"
    assert {
        contract["domain"] for contract in RELATION_CONTRACTS.values()
    } <= ALLOWED_DOMAINS


def test_validate_inventory_rejects_unknown_contract_domain() -> None:
    inventory = _inventory()
    inventory["relations"][0]["contract"] = {
        **inventory["relations"][0]["contract"],
        "domain": "inflation_gold",
    }

    with pytest.raises(ValueError, match="unknown domain"):
        validate_inventory(inventory)


def test_validate_inventory_accepts_complete_sorted_inventory() -> None:
    validate_inventory(_inventory())


def test_validate_inventory_rejects_missing_or_unsorted_relations() -> None:
    missing = _inventory()
    missing["relations"].pop()
    with pytest.raises(ValueError, match="coverage mismatch"):
        validate_inventory(missing)

    unsorted = deepcopy(_inventory())
    unsorted["relations"].reverse()
    with pytest.raises(ValueError, match="not sorted"):
        validate_inventory(unsorted)
