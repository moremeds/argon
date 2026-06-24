"""GET /api/regime/vrp-macro-signal/live — live recompute with EOD fallback."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from tests.integration.api.test_vrp_macro_signal_endpoint import _seed_spx_skip
from tests.integration.reports.test_vrp_macro_signal import _seed_spx_vix_varied


def test_live_returns_live_basis_with_fresh_quotes(
    client: TestClient, seeded_db_empty_cards
) -> None:
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    now = datetime.now(timezone.utc)
    repo.bulk_upsert_intraday_quotes(
        [
            ("SPX", Decimal("7300.0"), now, "xenon_ws"),
            ("VIX", Decimal("25.5"), now, "xenon_ws"),
        ]
    )
    repo.conn.commit()

    res = client.get("/api/regime/vrp-macro-signal/live")
    assert res.status_code == 200
    body = res.json()
    assert body["basis"] == "live"
    assert body["signal"]["name"] == "SPX"
    assert body["signal"]["action"] in ("TRADE", "SKIP")
    assert set(body["live_quotes"]) == {"SPX", "VIX"}


def test_live_falls_back_to_eod_when_no_fresh_quotes(
    client: TestClient, seeded_db_empty_cards
) -> None:
    _seed_spx_skip(seeded_db_empty_cards)  # one basis='eod' SPX row, no fresh quotes

    res = client.get("/api/regime/vrp-macro-signal/live")
    assert res.status_code == 200
    body = res.json()
    assert body["basis"] == "eod"
    assert body["signal"]["name"] == "SPX"
    assert body["signal"]["action"] == "SKIP"


def test_live_empty_when_nothing_seeded(
    client: TestClient, seeded_db_empty_cards
) -> None:
    res = client.get("/api/regime/vrp-macro-signal/live")
    assert res.status_code == 200
    body = res.json()
    assert body["basis"] == "eod"
    assert body["signal"] is None
