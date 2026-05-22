from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
from fastapi.testclient import TestClient

from tests.test_trade_insights_ai import _sample_outcome_for
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.models import (
    CandidateStructure,
    FlowSnapshot,
    InsightLeg,
    MarketStructure,
    SingleStockReport,
    TradeInsightsHeader,
    TradeInsightsResponse,
    VolatilityProfile,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VRPAssessment,
)
from uw_scan.storage.repository import Repository


def _settings_for_repo(
    repo: Repository,
    *,
    enabled: bool = True,
    claude_enabled: bool = False,
) -> Settings:
    """Test settings. Defaults to codex-only for backwards-compatibility with
    the pre-existing tests; set claude_enabled=True to exercise both providers."""
    return Settings.from_env().model_copy(
        update={
            "db_name": repo.conn.info.dbname,
            "db_schema": repo._schema,
            "trade_insights_ai_enabled": enabled,
            "trade_insights_ai_model": "",
            "trade_insights_ai_claude_enabled": claude_enabled,
            "trade_insights_ai_claude_model": "",
        }
    )


def _codex_stub(body: dict) -> dict:
    """Extract the codex stub from a paired POST response."""
    return next(a for a in body["analyses"] if a["provider"] == "codex")


def _claude_stub(body: dict) -> dict | None:
    """Extract the claude stub if present, else None."""
    for a in body["analyses"]:
        if a["provider"] == "claude":
            return a
    return None


def _client_for_settings(settings: Settings) -> TestClient:
    app = create_app()

    def _override_settings() -> Settings:
        return settings

    def _override_repo():
        conn = psycopg.connect(settings.db_dsn())
        try:
            yield Repository(conn, schema=settings.db_schema)
        finally:
            conn.close()

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_repo] = _override_repo
    return TestClient(app)


def _seed_run(repo: Repository) -> int:
    run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(run_id, status="ok")
    repo.conn.commit()
    return run_id


def _stock_report(run_id: int, *, net_premium: str = "100") -> SingleStockReport:
    return SingleStockReport(
        run_id=run_id,
        ticker="TSLA",
        generated_at=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        market_structure=MarketStructure(spot=Decimal("380.88")),
        volatility=VolatilityProfile(iv=Decimal("0.42")),
        flow=FlowSnapshot(
            ticker="TSLA",
            flow_count=1,
            net_premium=Decimal(net_premium),
            bull_premium=Decimal(net_premium),
            bear_premium=Decimal("0"),
            ask_side_premium=Decimal(net_premium),
            bid_side_premium=Decimal("0"),
        ),
        vrp=VRPAssessment(vrp=Decimal("0.07"), signal="thin", note=""),
    )


def _trade_insights_response() -> TradeInsightsResponse:
    return TradeInsightsResponse(
        ticker="TSLA",
        as_of=datetime(2026, 5, 13, 20, 0, tzinfo=timezone.utc),
        header=TradeInsightsHeader(
            dominant_bias="BULLISH",
            primary_setup="CHEAP_VOL_BREAKOUT",
            confidence_label="MEDIUM",
            data_quality_label="MIXED",
            idea_count=1,
        ),
        candidate_structures=[
            CandidateStructure(
                idea_id="A",
                structure="bull_call_spread",
                thesis="Cheap vol with bullish flow.",
                expression_type="LONG_DELTA",
                rank=1,
                status="needs_check",
                risk_flags=["verify_bid_ask"],
                max_loss=Decimal("6.40"),
                max_profit=Decimal("8.60"),
                legs=[
                    InsightLeg(
                        side="buy",
                        option_symbol="TSLA260417C00385000",
                        option_right="C",
                        expiry=date(2026, 4, 17),
                        strike=Decimal("385"),
                        mid=Decimal("6.40"),
                    )
                ],
            )
        ],
    )


def _volatility_response() -> VolatilitySeriesResponse:
    return VolatilitySeriesResponse(
        ticker="TSLA",
        as_of=date(2026, 5, 13),
        backfill_status="ready",
        header=VolHeaderBlock(
            iv=Decimal("0.42"), rv=Decimal("0.31"), iv_rank=Decimal("3.4")
        ),
    )


def _patch_api_sources(monkeypatch, *, net_premium: str = "100") -> None:
    def fake_stock_report(ticker, run_id, repo):
        return _stock_report(run_id, net_premium=net_premium)

    monkeypatch.setattr(
        "uw_scan.api.routers.trade_insights.assemble_single_stock_report",
        fake_stock_report,
    )
    monkeypatch.setattr(
        "uw_scan.api.routers.trade_insights.assemble_trade_insights",
        lambda **kwargs: _trade_insights_response(),
    )
    monkeypatch.setattr(
        "uw_scan.api.routers.trade_insights.assemble_volatility_series",
        lambda **kwargs: _volatility_response(),
        raising=False,
    )


def test_trade_insights_ai_post_returns_503_when_disabled(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo, enabled=False))

    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})

    # Both providers disabled → 503
    assert response.status_code == 503
    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {repo._schema}.trade_insight_ai_analyses")
        assert cur.fetchone()[0] == 0


def test_trade_insights_ai_post_queues_and_get_fetches_status(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Codex-only mode: POST returns one stub; GET by id works."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo, claude_enabled=False))

    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})

    assert response.status_code == 202
    body = response.json()
    assert "analyses" in body and len(body["analyses"]) == 1
    codex = _codex_stub(body)
    assert codex["provider"] == "codex"
    assert codex["status"] == "queued"
    assert codex["model"] == "codex-default"
    assert codex["reused"] is False

    status = client.get(
        f"/api/stock/TSLA/trade-insights/ai-analysis/{codex['analysis_id']}"
    )
    assert status.status_code == 200
    assert status.json()["analysis_id"] == codex["analysis_id"]
    assert status.json()["provider"] == "codex"
    assert (
        client.get(
            f"/api/stock/AAPL/trade-insights/ai-analysis/{codex['analysis_id']}"
        ).status_code
        == 404
    )


def test_trade_insights_ai_latest_resumes_active_progress(
    seeded_db_empty_cards,
    monkeypatch,
):
    """/latest is keyed by provider; succeeded slot persists across force_rerun
    until the new row completes."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo, claude_enabled=False))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    first_codex = _codex_stub(first)
    latest = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest")

    assert latest.status_code == 200
    pair = latest.json()
    # No succeeded rows yet → both slots null
    assert pair["codex"] is None
    assert pair["claude"] is None

    row = repo.get_trade_insight_ai_analysis(first_codex["analysis_id"], ticker="TSLA")
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        first_codex["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="done",
    )
    repo.conn.commit()

    latest_after_complete = client.get(
        "/api/stock/TSLA/trade-insights/ai-analysis/latest"
    ).json()
    assert latest_after_complete["codex"]["analysis_id"] == first_codex["analysis_id"]
    assert latest_after_complete["codex"]["status"] == "succeeded"
    assert latest_after_complete["claude"] is None

    forced = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"force_rerun": True},
    ).json()
    forced_codex = _codex_stub(forced)
    assert forced_codex["analysis_id"] != first_codex["analysis_id"]

    # Latest still shows the prior succeeded row — the new one is queued, not
    # yet succeeded.
    latest_after_rerun = client.get(
        "/api/stock/TSLA/trade-insights/ai-analysis/latest"
    ).json()
    assert latest_after_rerun["codex"]["analysis_id"] == first_codex["analysis_id"]


def test_trade_insights_ai_post_reuses_active_analysis_for_same_input(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Codex-only mode: second POST reuses the queued codex row."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo, claude_enabled=False))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    second = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    first_codex = _codex_stub(first)
    second_codex = _codex_stub(second)

    assert second_codex["analysis_id"] == first_codex["analysis_id"]
    assert second_codex["status"] == "queued"
    assert second_codex["reused"] is True
    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {repo._schema}.trade_insight_ai_analyses")
        assert cur.fetchone()[0] == 1


def test_trade_insights_ai_get_rejects_malformed_analysis_id(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.get("/api/stock/TSLA/trade-insights/ai-analysis/not-a-uuid")

    assert response.status_code == 422


def test_trade_insights_ai_post_reuses_success_and_force_rerun_creates_new(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Codex-only mode: second POST reuses succeeded row; force_rerun makes a
    new queued row."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo, claude_enabled=False))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    first_codex = _codex_stub(first)
    row = repo.get_trade_insight_ai_analysis(first_codex["analysis_id"], ticker="TSLA")
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        first_codex["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="done",
    )
    repo.conn.commit()

    reused = _codex_stub(
        client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    )
    forced = _codex_stub(
        client.post(
            "/api/stock/TSLA/trade-insights/ai-analysis",
            json={"force_rerun": True},
        ).json()
    )

    assert reused["analysis_id"] == first_codex["analysis_id"]
    assert reused["status"] == "succeeded"
    assert reused["reused"] is True
    assert forced["analysis_id"] != first_codex["analysis_id"]
    assert forced["status"] == "queued"


def test_trade_insights_ai_analysis_hash_changes_when_source_tabs_change(
    seeded_db_empty_cards,
    monkeypatch,
):
    """When upstream sources change, the analysis_input_hash differs so each
    POST creates a fresh row. The DB row holds analysis_input_hash; verify
    via the row, not the stub (stubs don't expose hashes)."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch, net_premium="100")
    client = _client_for_settings(_settings_for_repo(repo, claude_enabled=False))
    first = _codex_stub(
        client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    )

    _patch_api_sources(monkeypatch, net_premium="999")
    second = _codex_stub(
        client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    )

    first_row = repo.get_trade_insight_ai_analysis(first["analysis_id"], ticker="TSLA")
    second_row = repo.get_trade_insight_ai_analysis(
        second["analysis_id"], ticker="TSLA"
    )
    assert first_row is not None and second_row is not None
    assert (
        first_row["trade_insights_input_hash"]
        == second_row["trade_insights_input_hash"]
    )
    assert first_row["analysis_input_hash"] != second_row["analysis_input_hash"]


# --- new paired-mode tests (both providers enabled) ---


def test_trade_insights_ai_post_returns_one_stub_per_enabled_provider(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=True)
    )

    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})
    assert response.status_code == 202
    body = response.json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"codex", "claude"}
    for stub in body["analyses"]:
        assert "analysis_id" in stub
        assert stub["status"] == "queued"
        assert stub["reused"] is False


def test_trade_insights_ai_post_skips_disabled_provider(
    seeded_db_empty_cards,
    monkeypatch,
):
    """When claude is disabled, only codex is returned."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=False)
    )

    body = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"codex"}


def test_trade_insights_ai_latest_returns_keyed_dict_both_null_initially(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=True)
    )

    response = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest")
    assert response.status_code == 200
    assert response.json() == {"codex": None, "claude": None}


def test_trade_insights_ai_latest_with_one_provider_succeeded(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Cache-mixed case: complete one provider's row, leave the other queued."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=True)
    )

    body = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    codex = _codex_stub(body)
    claude = _claude_stub(body)
    assert codex is not None and claude is not None

    row = repo.get_trade_insight_ai_analysis(codex["analysis_id"], ticker="TSLA")
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        codex["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="codex-done",
    )
    repo.conn.commit()

    pair = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest").json()
    assert pair["codex"]["analysis_id"] == codex["analysis_id"]
    assert pair["codex"]["status"] == "succeeded"
    assert pair["claude"] is None


def test_trade_insights_ai_post_providers_filter_runs_only_listed(
    seeded_db_empty_cards,
    monkeypatch,
):
    """{providers: ['claude']} enqueues only claude — codex is skipped even though enabled.

    Models the UI 'skip stuck provider' flow: if codex is already in-flight,
    the next Run sends providers=['claude'] so codex is not re-enqueued.
    """
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=True)
    )

    body = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": ["claude"]},
    ).json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"claude"}


def test_trade_insights_ai_post_providers_filter_intersects_with_enabled(
    seeded_db_empty_cards,
    monkeypatch,
):
    """providers=['codex','claude'] with claude disabled still only returns codex."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=False)
    )

    body = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": ["codex", "claude"]},
    ).json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"codex"}


def test_trade_insights_ai_post_providers_empty_list_falls_back_to_all_enabled(
    seeded_db_empty_cards,
    monkeypatch,
):
    """providers=[] (empty list) is treated as "no filter" — legacy all-enabled behavior.

    Empty list is falsy in Python, so the server-side filter resolves to None.
    The UI guards against sending [] but the backend tolerates it without crashing.
    """
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(
        _settings_for_repo(repo, enabled=True, claude_enabled=True)
    )

    response = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": []},
    )
    assert response.status_code == 202
    # Empty `providers` list is treated as "no providers" (falsy → server-side
    # filter is None → legacy all-enabled behavior). This is intentional so
    # the UI's "Run with everything" path with `providers=[]` doesn't no-op.
    providers = {a["provider"] for a in response.json()["analyses"]}
    assert providers == {"codex", "claude"}
