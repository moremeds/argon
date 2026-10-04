from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
from fastapi.testclient import TestClient

from tests.unit.test_trade_insights_ai import _sample_outcome_for
from uw_scan.api.deps import get_repo, get_settings
from uw_scan.api.server import create_app
from uw_scan.config import Settings
from uw_scan.models import (
    CandidateStructure,
    FlowSnapshot,
    InsightLeg,
    MarketAggregates,
    MarketStructure,
    SingleStockReport,
    TradeInsightsHeader,
    TradeInsightsResponse,
    VolatilityProfile,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VRPAssessment,
)
from uw_scan.reports.trade_insights_ai import PROMPT_VERSION
from uw_scan.storage.repository import Repository


def _claim(repo, analysis_id):
    """Stamp a claim on one row (as the worker's claim does) and return the
    token -- complete/fail require it (I-06)."""
    with repo.conn.cursor() as cur:
        cur.execute(
            "UPDATE uw_scan.trade_insight_ai_analyses SET status = 'running', "
            "started_at = now(), claim_token = gen_random_uuid() "
            "WHERE analysis_id = %s RETURNING claim_token",
            (analysis_id,),
        )
        return cur.fetchone()[0]


def _settings_for_repo(
    repo: Repository,
    *,
    deepseek_enabled: bool = True,
) -> Settings:
    """Test settings. DeepSeek is the only provider; the default keeps it ON
    so tests don't have to pass it explicitly."""
    return Settings.from_env().model_copy(
        update={
            "db_name": repo.conn.info.dbname,
            "db_schema": repo._schema,
            "trade_insights_ai_deepseek_enabled": deepseek_enabled,
            "trade_insights_ai_deepseek_model": "",
        }
    )


def _deepseek_stub(body: dict) -> dict:
    """Extract the deepseek stub from a POST response."""
    return next(a for a in body["analyses"] if a["provider"] == "deepseek")


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
    # Realistic full_scan: persist aggregates so latest_run_id treats this as
    # the canonical renderable run (see scan_runs.latest_run_id).
    repo.set_aggregates(
        run_id, MarketAggregates(call_oi_total=1000, iv30d=Decimal("0.30"))
    )
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
    client = _client_for_settings(_settings_for_repo(repo, deepseek_enabled=False))

    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})

    # The only provider is disabled → 503
    assert response.status_code == 503
    with repo.conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {repo._schema}.trade_insight_ai_analyses")
        assert cur.fetchone()[0] == 0


def test_trade_insights_ai_post_queues_and_get_fetches_status(
    seeded_db_empty_cards,
    monkeypatch,
):
    """POST returns the single deepseek stub; GET by id works."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={})

    assert response.status_code == 202
    body = response.json()
    assert "analyses" in body and len(body["analyses"]) == 1
    deepseek = _deepseek_stub(body)
    assert deepseek["provider"] == "deepseek"
    assert deepseek["status"] == "queued"
    assert deepseek["model"] == "deepseek-default"
    assert deepseek["reused"] is False

    status = client.get(
        f"/api/stock/TSLA/trade-insights/ai-analysis/{deepseek['analysis_id']}"
    )
    assert status.status_code == 200
    assert status.json()["analysis_id"] == deepseek["analysis_id"]
    assert status.json()["provider"] == "deepseek"
    assert (
        client.get(
            f"/api/stock/AAPL/trade-insights/ai-analysis/{deepseek['analysis_id']}"
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
    client = _client_for_settings(_settings_for_repo(repo))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    first_ds = _deepseek_stub(first)
    latest = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest")

    assert latest.status_code == 200
    pair = latest.json()
    # No succeeded rows yet → every provider slot null
    assert pair["codex"] is None
    assert pair["claude"] is None
    assert pair["deepseek"] is None

    row = repo.get_trade_insight_ai_analysis(first_ds["analysis_id"], ticker="TSLA")
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        first_ds["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="done",
        claim_token=_claim(repo, first_ds["analysis_id"]),
    )
    repo.conn.commit()

    latest_after_complete = client.get(
        "/api/stock/TSLA/trade-insights/ai-analysis/latest"
    ).json()
    assert (
        latest_after_complete["deepseek"]["analysis_id"] == first_ds["analysis_id"]
    )
    assert latest_after_complete["deepseek"]["status"] == "succeeded"
    assert latest_after_complete["codex"] is None
    assert latest_after_complete["claude"] is None

    forced = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"force_rerun": True},
    ).json()
    forced_ds = _deepseek_stub(forced)
    assert forced_ds["analysis_id"] != first_ds["analysis_id"]

    # Latest still shows the prior succeeded row — the new one is queued, not
    # yet succeeded.
    latest_after_rerun = client.get(
        "/api/stock/TSLA/trade-insights/ai-analysis/latest"
    ).json()
    assert (
        latest_after_rerun["deepseek"]["analysis_id"] == first_ds["analysis_id"]
    )


def test_trade_insights_ai_post_reuses_active_analysis_for_same_input(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Second POST reuses the queued deepseek row."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    second = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    first_ds = _deepseek_stub(first)
    second_ds = _deepseek_stub(second)

    assert second_ds["analysis_id"] == first_ds["analysis_id"]
    assert second_ds["status"] == "queued"
    assert second_ds["reused"] is True
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
    """Second POST reuses the succeeded row; force_rerun makes a new queued
    row."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    first = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    first_ds = _deepseek_stub(first)
    row = repo.get_trade_insight_ai_analysis(first_ds["analysis_id"], ticker="TSLA")
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        first_ds["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="done",
        claim_token=_claim(repo, first_ds["analysis_id"]),
    )
    repo.conn.commit()

    reused = _deepseek_stub(
        client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    )
    forced = _deepseek_stub(
        client.post(
            "/api/stock/TSLA/trade-insights/ai-analysis",
            json={"force_rerun": True},
        ).json()
    )

    assert reused["analysis_id"] == first_ds["analysis_id"]
    assert reused["status"] == "succeeded"
    assert reused["reused"] is True
    assert forced["analysis_id"] != first_ds["analysis_id"]
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
    client = _client_for_settings(_settings_for_repo(repo))
    first = _deepseek_stub(
        client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    )

    _patch_api_sources(monkeypatch, net_premium="999")
    second = _deepseek_stub(
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


# --- single-provider mode (deepseek is the only provider) ---


def test_trade_insights_ai_post_returns_single_deepseek_stub(
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
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"deepseek"}
    for stub in body["analyses"]:
        assert "analysis_id" in stub
        assert stub["status"] == "queued"
        assert stub["reused"] is False


def test_trade_insights_ai_post_providers_filter_without_deepseek_is_empty(
    seeded_db_empty_cards,
    monkeypatch,
):
    """A providers filter naming only removed/unknown providers yields an
    empty analyses list — deepseek is enabled but unlisted."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": ["codex", "claude"]},
    )
    assert response.status_code == 202
    assert response.json()["analyses"] == []


def test_trade_insights_ai_latest_returns_keyed_dict_all_null_initially(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["current_prompt_version"] == PROMPT_VERSION
    assert body["current_prompt_label"] == PROMPT_VERSION.removeprefix(
        "trade-insights-ai-"
    )
    assert body["codex"] is None
    assert body["claude"] is None
    assert body["deepseek"] is None
    # v5.2: provider_consensus is computed at GET time; with no rows it
    # reports consensus_grade='missing' and the agreement booleans default
    # to False.
    assert body["provider_consensus"]["consensus_grade"] == "missing"


def test_trade_insights_ai_latest_with_deepseek_succeeded(
    seeded_db_empty_cards,
    monkeypatch,
):
    """Complete the deepseek row; the removed providers' slots stay null."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    body = client.post("/api/stock/TSLA/trade-insights/ai-analysis", json={}).json()
    deepseek = _deepseek_stub(body)
    assert deepseek is not None

    row = repo.get_trade_insight_ai_analysis(
        deepseek["analysis_id"], ticker="TSLA"
    )
    assert row is not None
    repo.complete_trade_insight_ai_analysis(
        deepseek["analysis_id"],
        outcome=_sample_outcome_for(row["analysis_input_jsonb"]),
        markdown="deepseek-done",
        claim_token=_claim(repo, deepseek["analysis_id"]),
    )
    repo.conn.commit()

    pair = client.get("/api/stock/TSLA/trade-insights/ai-analysis/latest").json()
    assert pair["deepseek"]["analysis_id"] == deepseek["analysis_id"]
    assert pair["deepseek"]["status"] == "succeeded"
    assert pair["codex"] is None
    assert pair["claude"] is None


def test_trade_insights_ai_post_providers_filter_runs_only_deepseek(
    seeded_db_empty_cards,
    monkeypatch,
):
    """{providers: ['deepseek']} enqueues the deepseek row."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    body = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": ["deepseek"]},
    ).json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"deepseek"}


def test_trade_insights_ai_post_providers_filter_intersects_with_enabled(
    seeded_db_empty_cards,
    monkeypatch,
):
    """providers=['codex','deepseek'] intersects the single enabled provider
    to deepseek only."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    body = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": ["codex", "deepseek"]},
    ).json()
    providers = {a["provider"] for a in body["analyses"]}
    assert providers == {"deepseek"}


def test_trade_insights_ai_post_providers_empty_list_falls_back_to_all_enabled(
    seeded_db_empty_cards,
    monkeypatch,
):
    """providers=[] (empty list) is treated as "no filter" — legacy all-enabled
    behavior.

    Empty list is falsy in Python, so the server-side filter resolves to None.
    The UI guards against sending [] but the backend tolerates it without crashing.
    """
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis",
        json={"providers": []},
    )
    assert response.status_code == 202
    # Empty `providers` list is treated as "no providers" (falsy → server-side
    # filter is None → all-enabled behavior). This is intentional so
    # the UI's "Run with everything" path with `providers=[]` doesn't no-op.
    providers = {a["provider"] for a in response.json()["analyses"]}
    assert providers == {"deepseek"}


def test_trade_insights_get_writes_nothing_and_refresh_persists(
    seeded_db_empty_cards,
    monkeypatch,
):
    """I-21: GET /trade-insights (and /preview) write 0 rows; the snapshot write
    lives on POST /trade-insights/refresh. All three return the same body."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    def _counts() -> tuple[int, int]:
        with repo.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {repo._schema}.trade_insight_snapshots")
            snaps = int(cur.fetchone()[0])
            cur.execute(f"SELECT count(*) FROM {repo._schema}.trade_insight_candidates")
            cands = int(cur.fetchone()[0])
        return snaps, cands

    before = _counts()
    got = client.get("/api/stock/TSLA/trade-insights")
    preview = client.get("/api/stock/TSLA/trade-insights/preview")
    assert got.status_code == preview.status_code == 200
    assert _counts() == before  # neither GET wrote

    refreshed = client.post("/api/stock/TSLA/trade-insights/refresh")
    assert refreshed.status_code == 200
    assert got.json() == preview.json() == refreshed.json()
    assert _counts()[0] == before[0] + 1  # the explicit POST did write


def test_trade_insights_preview_404_without_runs(
    seeded_db_empty_cards,
    monkeypatch,
):
    repo = seeded_db_empty_cards
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))
    assert client.get("/api/stock/ZZZZ/trade-insights/preview").status_code == 404
