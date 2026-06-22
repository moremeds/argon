from datetime import date

from fastapi.testclient import TestClient

from uw_scan.api.deps import get_repo
from uw_scan.api.server import create_app


def _client(repo):
    app = create_app()
    app.dependency_overrides[get_repo] = lambda: repo
    return TestClient(app)


def test_candidates_endpoint(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    repo.upsert_vrp_candidate(
        ticker="NVDA",
        as_of=date(2026, 6, 22),
        structure="iron_condor",
        spot=120.0,
        iv=0.45,
        vrp_z=1.8,
        hold_days=20,
        short_put=110.0,
        long_put=104.0,
        short_call=130.0,
        long_call=136.0,
        entry_credit=1.8,
        max_loss=4.2,
        put_width=6.0,
        call_width=6.0,
        bucket_sector="Semis",
        bucket_verdict="HARVEST_SELLABLE",
        earnings_clear=True,
        contracts=1,
    )
    repo.conn.commit()
    r = _client(repo).get("/api/vrp/candidates")
    assert r.status_code == 200
    body = r.json()
    assert body["candidates"][0]["ticker"] == "NVDA"
    assert body["disclaimer"]  # flat-vol limitation surfaced
