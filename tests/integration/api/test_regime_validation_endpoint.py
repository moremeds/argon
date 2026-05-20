"""Endpoint contract test for GET /api/regime/validation."""

from __future__ import annotations


def test_validation_endpoint_returns_backtest_md(client) -> None:
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 200
    body = resp.json()
    assert "backtest_md" in body
    assert body["backtest_md"].startswith("# CRI Backtest")
    assert "backtest_csv_rows" in body
    assert body["backtest_csv_rows"] > 0


def test_validation_endpoint_includes_oos_summary(client) -> None:
    resp = client.get("/api/regime/validation")
    body = resp.json()
    assert body["oos"] is not None
    assert body["oos"]["interpretation"]
    assert len(body["oos"]["scores"]) >= 2


# --- Failure-mode tests -----------------------------------------------


def test_validation_404_when_backtest_md_missing(client, monkeypatch, tmp_path) -> None:
    from uw_scan.api.routers import regime_validation

    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 404
    assert "cri-backtest.md" in resp.json()["detail"]


def test_validation_500_when_oos_summary_malformed(
    client, monkeypatch, tmp_path
) -> None:
    from uw_scan.api.routers import regime_validation

    (tmp_path / "cri-backtest.md").write_text("# CRI Backtest\n")
    (tmp_path / "cri-backtest.csv").write_text("date,score\n2026-01-01,5\n")
    (tmp_path / "oos-summary.json").write_text("{not valid json")
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 500
    assert "malformed" in resp.json()["detail"]


def test_validation_rejects_symlink_under_docs_dir(
    client, monkeypatch, tmp_path
) -> None:
    from uw_scan.api.routers import regime_validation

    secret = tmp_path / "secret.md"
    secret.write_text("SECRET DO NOT LEAK")
    (tmp_path / "cri-backtest.md").symlink_to(secret)
    monkeypatch.setattr(regime_validation, "_DOCS_REGIME", tmp_path.resolve())
    resp = client.get("/api/regime/validation")
    assert resp.status_code == 404
    assert "regular file" in resp.json()["detail"]
