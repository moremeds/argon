"""OOS gate for the CRI composite version currently in code.

Enforces the calibration contract documented in
``docs/research/regime/oos-summary.json`` and ``cri-methodology.md``:

* The current composite version's AUC on the dd5 (SPX -5% within 20 sessions)
  and dd10 (SPX -10% within 60 sessions) forward-drawdown labels must stay
  within a documented tolerance of the v1 published baseline.

The tolerance (``BASELINE_TOLERANCE``) is intentionally larger than the
"within statistical noise" range the methodology notebook uses for v1 vs v2
(0.001). It is set at 0.02 AUC points to permit principled trade-offs (e.g.
v3 explicitly trades dd10 sensitivity for dd5 sensitivity in exchange for
tactical-pullback responsiveness — the documented purpose of the v3
calibration).

The gate's job is to catch *unintended* regression and gross drift, not to
preserve identical numbers across calibrations. When a calibration change
is intentional, update ``V1_AUC_BASELINE`` constants in this file alongside
the methodology doc. CI then enforces the new baseline going forward.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

OOS_PATH = (
    Path(__file__).resolve().parents[3]
    / "docs"
    / "research"
    / "regime"
    / "oos-summary.json"
)

# v1 published baselines from cri-validation.ipynb §9.
V1_AUC_BASELINE: dict[str, float] = {"dd5": 0.620, "dd10": 0.647}

# Max permissible drop in AUC vs v1 baseline. 0.02 AUC points (~3% relative)
# allows documented trade-offs while still catching gross regressions.
BASELINE_TOLERANCE = 0.02


@pytest.fixture(scope="module")
def oos_summary() -> dict:
    if not OOS_PATH.exists():
        pytest.skip(
            f"{OOS_PATH} missing — regenerate via "
            "`uv run python scripts/backtest_cri.py --write-oos-summary`"
        )
    return json.loads(OOS_PATH.read_text())


def _find(versions: list[dict], version: int) -> dict:
    matches = [v for v in versions if v.get("version") == version]
    assert matches, f"version={version} not present in oos-summary.json"
    return matches[0]


def _current_version(versions: list[dict]) -> dict:
    """The highest version number in the summary — the one this code emits."""
    non_v1 = [v for v in versions if v.get("version", 0) > 1]
    assert non_v1, "no non-v1 version in oos-summary.json"
    return max(non_v1, key=lambda v: v["version"])


def test_v1_baseline_constants_match_oos_summary(oos_summary) -> None:
    """v1 row in oos-summary.json must carry the published baseline.

    Catches accidental edits to the v1 entry (which would silently lower the
    bar for v3+ to pass).
    """
    v1 = _find(oos_summary["versions"], 1)
    assert v1["auc_dd5"] == V1_AUC_BASELINE["dd5"], (
        f"v1 dd5 AUC drifted from published baseline: "
        f"{v1['auc_dd5']} vs {V1_AUC_BASELINE['dd5']}"
    )
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
        "Do NOT merge — calibration meaningfully degrades short-horizon "
        "crash detection. Either re-tune or update V1_AUC_BASELINE in this "
        "file alongside the methodology doc."
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
        "Do NOT merge — calibration meaningfully degrades long-horizon "
        "crash detection. Either re-tune or update V1_AUC_BASELINE in this "
        "file alongside the methodology doc."
    )


def test_oos_summary_documents_label_definitions(oos_summary) -> None:
    """Labels section must exist with explicit window+threshold definitions.

    Defense in depth: catches the case where label definitions drift but
    the AUC numbers don't — a silent integrity failure mode.
    """
    labels = oos_summary.get("labels", [])
    by_name = {label["name"]: label["definition"] for label in labels}
    assert "label_dd5" in by_name
    assert "label_dd10" in by_name
    assert "20 trading days" in by_name["label_dd5"]
    assert "60 trading days" in by_name["label_dd10"]
