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
    VolHeaderBlock,
    VolatilityProfile,
    VolatilitySeriesResponse,
    VRPAssessment,
)
from uw_scan.storage.repository import Repository


def _settings_for_repo(repo: Repository, *, enabled: bool = True) -> Settings:
    return Settings.from_env().model_copy(
        update={
            "db_name": repo.conn.info.dbname,
            "db_schema": repo._schema,
            "trade_insights_ai_enabled": enabled,
            "trade_insights_ai_model": "",
        }
    )


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
        header=VolHeaderBlock(iv=Decimal("0.42"), rv=Decimal("0.31"), iv_rank=Decimal("3.4")),
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

    assert response.status_code == 503
    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {repo._schema}.trade_insight_ai_analyses")
        assert cur.fetchone()[0] == 0


def test_trade_insights_ai_post_queues_and_get_fetches_status(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["model"] == "codex-default"
    assert body["trade_insights_input_hash"]
    assert body["analysis_input_hash"]
    assert body["outcome"] is None
    assert body["reused"] is False

    status = client.get(f"/api/stock/TSLA/trade-insights/ai-analysis/{body['analysis_id']}")
    assert status.status_code == 200
    assert status.json()["analysis_id"] == body["analysis_id"]
    assert client.get(f"/api/stock/AAPL/trade-insights/ai-analysis/{body['analysis_id']}").status_code == 404


def test_trade_insights_ai_post_reuses_success_and_force_rerun_creates_new(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    row = repo.get_trade_insight_ai_analysis(first["analysis_id"], ticker="TSLA")
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        first["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="done",
    )
    repo.conn.commit()

    reused = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    forced = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"force_rerun": True},
    ).json()

    assert reused["analysis_id"] == first["analysis_id"]
    assert reused["status"] == "succeeded"
    assert reused["reused"] is True
    assert reused["markdown"] == "done"
    assert forced["analysis_id"] != first["analysis_id"]
    assert forced["status"] == "queued"


def test_trade_insights_ai_analysis_hash_changes_when_source_tabs_change(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch, net_premium="100")
    client = _client_for_settings(_settings_for_repo(repo))
    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()

    _patch_api_sources(monkeypatch, net_premium="999")
    second = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()

    assert second["trade_insights_input_hash"] == first["trade_insights_input_hash"]
    assert second["analysis_input_hash"] != first["analysis_input_hash"]
