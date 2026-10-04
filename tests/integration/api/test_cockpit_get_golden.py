"""Golden of every cockpit GET response (I-34 proof).

Written BEFORE the dealer analytics moved from storage/cockpit.py into
cards/. Each scenario reuses the seeding of an existing test in
test_cockpit_endpoint.py (the test runs first, on a fresh DB, with its own
assertions), then every ``GET /api/cockpit/{ticker}/*`` route the app
registers is called for each index ticker, and status + body must equal the
committed ``golden/cockpit_gets.json``.

The seeds use fixed dates and the cockpit compute reads no clock; the one
DB-side clock it reports is each table's latest ``inserted_at`` (the state
tab's freshness block), so after seeding every ``inserted_at`` is pinned to a
fixed instant. ``PGTZ``
pins how timestamptz renders, and floats are rounded to 9 significant digits,
because libm/numpy last bits differ between macOS and the Linux CI runner
(see test_regime_get_golden.py).

Regenerate (only for an intentional response change):
``COCKPIT_GOLDEN_WRITE=1 uv run pytest tests/integration/api/test_cockpit_get_golden.py``
"""

from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import pytest

from tests.integration.api import test_cockpit_endpoint as scenarios

GOLDEN = Path(__file__).resolve().parent / "golden" / "cockpit_gets.json"
TICKERS = ("SPY", "QQQ", "IWM")

SCENARIOS = [
    "test_cockpit_state_latest_returns_state_and_freshness",
    "test_cockpit_phase4_tabs_return_read_models",
    "test_cockpit_flow_im_exposes_flow_alert_classifier_inputs",
    "test_cockpit_flow_im_exposes_expected_abs_move",
    "test_cockpit_tabs_use_source_date_without_state_snapshot",
    "test_cockpit_dealer_pin_uses_latest_oi_snapshot_and_marks_source_date",
    "test_cockpit_freshness_oi_reports_stale_snapshot",
    "test_cockpit_dealer_metrics_use_exposure_fallback_without_chain_oi",
    "test_cockpit_dealer_excludes_same_day_pin_candidate",
    "test_cockpit_dealer_flow_color_uses_last_three_trading_event_dates",
    "test_cockpit_dealer_metrics_can_read_persisted_signal_rows",
]


def _round_floats(value):
    if isinstance(value, float):
        return float(f"{value:.9g}")
    if isinstance(value, dict):
        return {k: _round_floats(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_floats(v) for v in value]
    return value


def _cockpit_paths(client) -> list[str]:
    return sorted(
        r.path
        for r in client.app.routes
        if getattr(r, "path", "").startswith("/api/cockpit/")
        and "GET" in getattr(r, "methods", ())
    )


def _sweep(client) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for template in _cockpit_paths(client):
        for ticker in TICKERS:
            path = template.replace("{ticker}", ticker)
            r = client.get(path)
            try:
                body = r.json()
            except ValueError:
                body = r.text
            out[path] = {"status": r.status_code, "body": _round_floats(body)}
    return out


@pytest.fixture
def pinned_client(monkeypatch, client):
    monkeypatch.setenv("PGTZ", "UTC")
    return client


PINNED_INSERTED_AT = "2026-05-15T21:00:00+00:00"


def _pin_inserted_at(repo) -> None:
    """``inserted_at`` defaults to now(); pin it so freshness is stable."""
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.columns "
            "WHERE table_schema = 'uw_scan' AND column_name = 'inserted_at' "
            "AND table_name IN (SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'uw_scan' AND table_type = 'BASE TABLE')"
        )
        for (table,) in cur.fetchall():
            cur.execute(
                f"UPDATE uw_scan.{table} SET inserted_at = %s "
                "WHERE inserted_at IS NOT NULL",
                (PINNED_INSERTED_AT,),
            )
    repo.conn.commit()


def _golden() -> dict:
    return json.loads(GOLDEN.read_text()) if GOLDEN.exists() else {}


@pytest.mark.parametrize("scenario", ["empty", *SCENARIOS])
def test_cockpit_gets_match_golden(scenario, pinned_client, seeded_db_empty_cards):
    if scenario != "empty":
        fn = getattr(scenarios, scenario)
        available = {
            "client": pinned_client,
            "seeded_db_empty_cards": seeded_db_empty_cards,
        }
        fn(**{name: available[name] for name in inspect.signature(fn).parameters})
        _pin_inserted_at(seeded_db_empty_cards)
    got = json.loads(json.dumps(_sweep(pinned_client), sort_keys=True, default=str))

    if os.environ.get("COCKPIT_GOLDEN_WRITE") == "1":
        golden = _golden()
        golden[scenario] = got
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(golden, sort_keys=True, indent=1) + "\n")
        pytest.skip("golden written")
    assert got == _golden()[scenario], (
        f"cockpit GET responses changed for scenario {scenario}; "
        "diff against tests/integration/api/golden/cockpit_gets.json"
    )
