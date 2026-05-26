"""OOS gate for the CRI composite version currently in code.

Reads summary.oos.versions[] from the latest COMPLETED CRI run in
uw_scan.regime_backtest_runs. The previous on-disk
docs/research/regime/oos-summary.json source was retired in the regime
closure (2026-05); see
docs/superpowers/archive/specs/2026-05-24-regime-research-closure-design.md.

Calibration-provenance contract:
  - The seed fixture (tests/integration/regime/conftest.py) reads
    `LAST_KNOWN_AUC_DD5` / `LAST_KNOWN_AUC_DD10` from cri_scorers.py to
    construct the v{COMPOSITE_VERSION} row.
  - Bumping COMPOSITE_VERSION REQUIRES updating both LAST_KNOWN_AUC_*
    constants in the same PR. PR review enforces this.
  - The gate then verifies recorded AUC >= v1 baseline - BASELINE_TOLERANCE.
  - If no completed run exists at the current version, the test FAILS (does
    NOT skip) — a silent skip would disable the regression gate.
"""

from __future__ import annotations

from typing import Any

import pytest

from uw_scan.cards.cri_scorers import COMPOSITE_VERSION
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository

V1_AUC_BASELINE: dict[str, float] = {"dd5": 0.620, "dd10": 0.647}
BASELINE_TOLERANCE = 0.02


@pytest.fixture
def oos_summary(seeded_db_empty_cards, seed_cri_backtest_run) -> dict[str, Any]:
    """Return summary.oos from the latest completed CRI run for the current version.

    Both fixtures are function-scoped (matching `seeded_db_empty_cards` from
    tests/integration/conftest.py — which calls _reset_and_migrate per test).
    `seed_cri_backtest_run` seeds the run; this fixture reads it back.
    """
    repo = seeded_db_empty_cards
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    run = rb.find_latest_run("cri", composite_version=str(COMPOSITE_VERSION))
    assert run is not None, (
        f"no completed CRI run at composite_version={COMPOSITE_VERSION} "
        "in test DB — seed_cri_backtest_run fixture failed?"
    )
    oos = (run.get("summary") or {}).get("oos")
    assert oos is not None, "run.summary.oos missing — backtest produced no AUC"
    return oos


def _find(versions: list[dict], version: int) -> dict:
    matches = [v for v in versions if v.get("version") == version]
    assert matches, f"version={version} not present in summary.oos.versions"
    return matches[0]


def _current_version(versions: list[dict]) -> dict:
    non_v1 = [v for v in versions if v.get("version", 0) > 1]
    assert non_v1, "no non-v1 version in summary.oos.versions"
    return max(non_v1, key=lambda v: v["version"])


def test_v1_baseline_constants_match_summary(oos_summary) -> None:
    v1 = _find(oos_summary["versions"], 1)
    assert v1["auc_dd5"] == V1_AUC_BASELINE["dd5"]
    assert v1["auc_dd10"] == V1_AUC_BASELINE["dd10"]


def test_current_version_within_tolerance_on_dd5(oos_summary) -> None:
    current = _current_version(oos_summary["versions"])
    v1 = _find(oos_summary["versions"], 1)
    auc = current["auc_dd5"]
    assert auc is not None, "current version missing auc_dd5"
    floor = v1["auc_dd5"] - BASELINE_TOLERANCE
    assert auc >= floor, (
        f"v{current['version']} dd5 AUC ({auc:.4f}) is more than "
        f"{BASELINE_TOLERANCE:.3f} below v1 baseline ({v1['auc_dd5']:.3f}). "
        "If this is an intentional calibration trade-off, update "
        "LAST_KNOWN_AUC_DD5 in cri_scorers.py AND V1_AUC_BASELINE['dd5'] in "
        "this file in the same PR."
    )


def test_current_version_within_tolerance_on_dd10(oos_summary) -> None:
    current = _current_version(oos_summary["versions"])
    v1 = _find(oos_summary["versions"], 1)
    auc = current["auc_dd10"]
    assert auc is not None, "current version missing auc_dd10"
    floor = v1["auc_dd10"] - BASELINE_TOLERANCE
    assert auc >= floor, (
        f"v{current['version']} dd10 AUC ({auc:.4f}) is more than "
        f"{BASELINE_TOLERANCE:.3f} below v1 baseline ({v1['auc_dd10']:.3f}). "
        "If this is an intentional calibration trade-off, update "
        "LAST_KNOWN_AUC_DD10 in cri_scorers.py AND V1_AUC_BASELINE['dd10'] "
        "in this file in the same PR."
    )


def test_summary_documents_label_definitions(oos_summary) -> None:
    """Labels section must exist with explicit window+threshold definitions.

    Defense in depth: catches the case where label definitions drift but
    the AUC numbers don't — a silent integrity failure mode.
    """
    by_name = {label["name"]: label["definition"] for label in oos_summary["labels"]}
    assert "label_dd5" in by_name
    assert "label_dd10" in by_name
    assert "20 trading days" in by_name["label_dd5"]
    assert "60 trading days" in by_name["label_dd10"]
