"""Contract models for the generic agent-run transport.

What is checked here is the boundary: the shape fields the store's CHECK
constraints also enforce, and the deliberate REFUSAL to type the view document.
An ingest that rejected a document argon has no model for would fail at the
door on a writer's deploy instead of rendering one section short.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from uw_scan.models import AgentRunIngest

# Frozen from the recorded option-wizard run of 2026-09-03.
VIEW = {
    "date": "2026-09-03",
    "tape": [
        {"label": "SPY", "value": "772.80"},
        {"label": "IWM", "value": "294.93"},
        {"label": "HY OAS", "value": "2.65%", "source": "BAMLH0A0HYM2, 2026-09-01"},
    ],
}


def _payload(**over):
    base = dict(
        tenant="option-wizard",
        kind="premarket",
        run_day=date(2026, 9, 3),
        run_id="ow-2026-09-03-premarket-1",
        code_sha="a1b2c3d",
        schema_version=1,
        outcome="completed",
        headline="SPY 772.80, one sentence.",
        view=VIEW,
    )
    base.update(over)
    return base


def test_week_key_is_optional_and_kept_verbatim_when_sent():
    assert AgentRunIngest(**_payload()).week_key is None
    assert AgentRunIngest(**_payload(week_key="2026-W36")).week_key == "2026-W36"


def test_the_view_passes_through_untouched():
    """argon never interprets the document; schema_version is the real contract."""
    model = AgentRunIngest(**_payload())
    assert model.view == VIEW
    assert model.report == {}


@pytest.mark.parametrize(
    "override",
    [
        {"tenant": "Option Wizard"},
        {"kind": "PREMARKET"},
        {"kind": "a" * 33},
        {"week_key": "2026-36"},
        {"outcome": "ok"},
        {"schema_version": 0},
        {"view": {}},
    ],
    ids=[
        "tenant-not-a-slug",
        "kind-not-lowercase",
        "kind-too-long",
        "week-key-wrong-shape",
        "outcome-not-a-recorded-state",
        "schema-version-below-one",
        "empty-view-is-not-a-document",
    ],
)
def test_the_boundary_refuses_what_the_store_would_refuse(override):
    with pytest.raises(ValidationError):
        AgentRunIngest(**_payload(**override))
