from fastapi.testclient import TestClient

from uw_scan.storage.repository import Repository


def test_get_gex_returns_empty_shape_when_no_data(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        Repository, "fetch_latest_gex", lambda self, *, ticker="SPX": None
    )
    r = client.get("/api/regime/gex")
    assert r.status_code == 200
    data = r.json()
    assert data["spot"] is None
    assert data["levels"]["max_magnet"] is None
    assert data["profile"] == []
    assert data["mq"] is None


def test_get_gex_defaults_to_spx_and_uppercases_ticker(
    client: TestClient, monkeypatch
) -> None:
    seen = {}

    def stub(self, *, ticker="SPX"):
        seen["ticker"] = ticker
        return None

    monkeypatch.setattr(Repository, "fetch_latest_gex", stub)
    client.get("/api/regime/gex")
    assert seen["ticker"] == "SPX"
    client.get("/api/regime/gex?ticker=spy")
    assert seen["ticker"] == "SPY"


def test_get_cri_returns_pending_sentinel(client: TestClient) -> None:
    r = client.get("/api/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["scanner"] == "cri"
    assert body["reason"] == "ib_via_r2_not_wired"


def test_get_vcg_returns_pending_sentinel(client: TestClient) -> None:
    r = client.get("/api/regime/vcg")
    body = r.json()
    assert body["status"] == "pending"
    assert body["scanner"] == "vcg"


def test_post_gex_scan_runs_scanner(client: TestClient, monkeypatch) -> None:
    """Router must construct a UwClient and pass (client, repo, ticker) to scanner.run."""
    calls = []

    def _stub_run(client_arg, repo_arg, ticker="SPX"):
        calls.append(
            ("client_passed" if client_arg is not None else "no_client", ticker)
        )
        return 42

    monkeypatch.setattr("uw_scan.scanners.gex.run", _stub_run)
    r = client.post("/api/regime/gex/scan?ticker=spy")
    assert r.status_code == 202
    body = r.json()
    assert body["scanner"] == "gex"
    assert body["ticker"] == "SPY"
    assert body["row_id"] == 42
    assert calls == [("client_passed", "SPY")]


def test_post_cri_scan_returns_pending(client: TestClient) -> None:
    r = client.post("/api/regime/scan")
    assert r.status_code == 202
    body = r.json()
    assert body["scanner"] == "cri"
    assert "ib_via_r2_not_wired" in body["reason"]
