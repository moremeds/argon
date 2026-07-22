"""Endpoint contract test for GET /api/regime/guidance."""

from __future__ import annotations

from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository


def _calm_snapshot() -> dict:
    """LOW level, contango (VIX/VIX3M ~0.86)."""
    return {
        "date": "2026-05-19",
        "vix": 18.0,
        "vix3m": 21.0,
        "vrp": 5.2,
        "vix_zscore_30d": -0.3,
        "vix_vix3m_ratio": 18.0 / 21.0,
        "cri": {
            "score": 8.0,
            "level": "LOW",
            "components": {
                "vix": 1.8,
                "vvix": 2.0,
                "correlation": 1.4,
                "momentum": 2.8,
            },
        },
    }


def _calm_snapshot_missing_vix3m() -> dict:
    out = _calm_snapshot()
    out["vix3m"] = None
    out["vix_vix3m_ratio"] = None
    return out


def test_guidance_returns_a_rule(client, monkeypatch) -> None:
    monkeypatch.setattr(
        CriSnapshotRepository, "fetch_latest", lambda self: _calm_snapshot()
    )
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"]
    assert body["posture"] in {"opportunistic", "neutral", "cautious", "defensive"}
    assert body["body_md"]


def test_guidance_selects_low_contango_for_calm_market(client, monkeypatch) -> None:
    monkeypatch.setattr(
        CriSnapshotRepository, "fetch_latest", lambda self: _calm_snapshot()
    )
    resp = client.get("/api/regime/guidance")
    body = resp.json()
    # VIX 18 / VIX3M 21 → 0.857 < 0.95 → low_contango
    assert body["state"] == "low_contango"
    assert body["posture"] == "opportunistic"


# --- Failure-mode tests -----------------------------------------------


def test_guidance_404_when_no_snapshot(client, monkeypatch) -> None:
    monkeypatch.setattr(CriSnapshotRepository, "fetch_latest", lambda self: None)
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 404
    assert "snapshot" in resp.json()["detail"]


def test_guidance_500_when_guidance_md_missing(client, monkeypatch, tmp_path) -> None:
    from uw_scan.api.routers import regime_validation

    # tmp_path/guidance.md does not exist -> _parse_guidance_md returns []
    # -> the endpoint raises HTTPException(500, "guidance.md missing ...").
    monkeypatch.setattr(regime_validation, "_GUIDANCE_MD", tmp_path / "guidance.md")
    monkeypatch.setattr(
        CriSnapshotRepository, "fetch_latest", lambda self: _calm_snapshot()
    )
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 500
    assert "guidance.md" in resp.json()["detail"]


def test_guidance_skips_malformed_rule_and_falls_through(
    client, monkeypatch, tmp_path
) -> None:
    """A typo'd condition is skipped (warning logged), not propagated as 500."""
    from uw_scan.api.routers import regime_validation

    (tmp_path / "guidance.md").write_text(
        '---\nstate: bad\ncondition: "level == NOTAQUOTE"\nposture: neutral\n---\n'
        "body for bad rule\n"
        "---\nstate: low_neutral\ncondition: \"level == 'LOW'\"\nposture: neutral\n---\n"
        "body for low_neutral\n"
    )
    monkeypatch.setattr(regime_validation, "_GUIDANCE_MD", tmp_path / "guidance.md")
    monkeypatch.setattr(
        CriSnapshotRepository, "fetch_latest", lambda self: _calm_snapshot()
    )
    resp = client.get("/api/regime/guidance")
    assert resp.status_code == 200
    assert resp.json()["state"] == "low_neutral"


def test_guidance_falls_back_to_missing_term_structure(client, monkeypatch) -> None:
    """Missing VIX3M must NOT auto-match 'low_contango' (the < 0.95 trap)."""
    monkeypatch.setattr(
        CriSnapshotRepository,
        "fetch_latest",
        lambda self: _calm_snapshot_missing_vix3m(),
    )
    resp = client.get("/api/regime/guidance")
    body = resp.json()
    assert body["state"] == "low_missing_term_structure"
    assert body["posture"] == "neutral"
