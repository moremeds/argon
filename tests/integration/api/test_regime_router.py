from fastapi.testclient import TestClient

from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
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


def test_get_cri_returns_empty_when_no_snapshot(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr(CriSnapshotRepository, "fetch_latest", lambda self: None)
    r = client.get("/api/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "empty"
    assert body["cri"]["score"] == 0.0
    assert body["cri"]["level"] == "LOW"
    assert body["history"] == []


def test_get_cri_returns_payload_when_snapshot_exists(
    client: TestClient, monkeypatch
) -> None:
    def stub(self):
        return {
            "date": "2026-05-15",
            "vix": 18.43,
            "vvix": 92.9,
            "cor1m": 10.8,
            "spx_distance_pct": -2.5,
            "realized_vol": 14.2,
            "cri": {
                "score": 33.4,
                "level": "ELEVATED",
                "components": {
                    "vix": 8.0,
                    "vvix": 12.0,
                    "correlation": 6.4,
                    "momentum": 7.0,
                },
            },
            "cta": {
                "realized_vol": 14.2,
                "exposure_pct": 70.4,
                "forced_reduction_pct": 29.6,
                "forced_reduction": True,
                "est_selling_bn": 103.6,
                "selling_usd_b": 103.6,
            },
            "crash_trigger": {
                "fired": False,
                "triggered": False,
                "conditions": {
                    "spx_below_100d_ma": True,
                    "realized_vol_gt_25": False,
                    "cor1m_gt_60": False,
                },
                "values": {"realized_vol": 14.2, "cor1m": 10.8},
            },
            "history": [],
            "spy_closes": [],
            "scan_time": "2026-05-15T20:30:00+00:00",
        }

    monkeypatch.setattr(CriSnapshotRepository, "fetch_latest", stub)
    r = client.get("/api/regime")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["cri"]["score"] == 33.4
    assert body["cri"]["level"] == "ELEVATED"
    assert body["cri"]["components"]["vvix"] == 12.0
    assert body["cta"]["forced_reduction"] is True
    assert body["crash_trigger"]["conditions"]["spx_below_100d_ma"] is True


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


def test_post_cri_scan_runs_scanner(client: TestClient, monkeypatch) -> None:
    """Router must call scanner.run(conn, schema=...) and surface the row_id."""
    calls = []

    def _stub_run(conn_arg, schema: str = "uw_scan"):
        calls.append(("conn_passed" if conn_arg is not None else "no_conn", schema))
        return 99

    monkeypatch.setattr("uw_scan.scanners.cri.run", _stub_run)
    r = client.post("/api/regime/scan")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "ok"
    assert body["scanner"] == "cri"
    assert body["row_id"] == 99
    assert calls[0][0] == "conn_passed"


def test_post_cri_scan_returns_skipped_on_thin_data(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setattr("uw_scan.scanners.cri.run", lambda conn, schema="uw_scan": None)
    r = client.post("/api/regime/scan")
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "thin_data"
    assert body["row_id"] is None
