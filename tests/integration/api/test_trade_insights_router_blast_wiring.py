"""Wiring contract: confirm the blast lane router passes ohlcv_rows /
positioning_payload / fundamentals_payload / macro_payload through to the
blast assembler, AND that the insights lane never receives those kwargs.

Regression target: before this PR, the router omitted the 5 optional kwargs
the blast assembler accepts, so every succeeded blast row degraded to
`{available: False}` across tape/positioning/fundamentals/macro and the
8-factor conviction ledger collapsed to ~1-2/8.

These tests only assert the wiring contract — that the keys are present
with the right shape. End-to-end conviction-ledger improvements are
verified via the live smoke-test in the PR description.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from tests.integration.api.test_trade_insights_ai_endpoint import (
    _client_for_settings,
    _patch_api_sources,
    _seed_run,
    _settings_for_repo,
)
from uw_scan.storage.repository import Repository

_BLAST_MACRO_SERIES = (
    "VIXCLS",
    "ANFCI",
    "NFCI",
    "DGS10",
    "BAMLH0A0HYM2",
    "GVZCLS",
)


def _seed_ohlc_rows(repo: Repository, *, ticker: str, n: int) -> None:
    """Seed `n` consecutive daily_ohlc rows ending today. Synthetic monotonic
    rise from 100 → 100 + n; enough bars to exercise tape derivations
    without requiring a full 260-bar fixture."""
    base_date = date.today() - timedelta(days=n - 1)
    for i in range(n):
        close = Decimal(100 + i)
        repo.upsert_daily_ohlc(
            ticker=ticker,
            date=base_date + timedelta(days=i),
            open=close,
            high=close + Decimal("1"),
            low=close - Decimal("1"),
            close=close,
            volume=1_000_000,
            source="test",
        )


def _seed_positioning(repo: Repository, *, ticker: str) -> None:
    repo.upsert_uw_positioning(
        ticker=ticker,
        snapshot_date=date.today(),
        si_pct_float=Decimal("15.0"),
        si_days_to_cover=Decimal("3.2"),
        earn_reactions_positive=3,
        earn_reactions_total=4,
        next_er_date=date.today() + timedelta(days=60),
    )
    repo.conn.commit()


def _seed_fundamentals(repo: Repository, *, ticker: str) -> None:
    repo.upsert_massive_fundamentals(
        ticker=ticker,
        period_end=date(2026, 3, 31),
        fiscal_period="Q1",
        revenue=Decimal("21_000_000_000"),
        gross_margin=Decimal("0.45"),
        op_margin=Decimal("0.12"),
        net_margin=Decimal("0.09"),
        fcf=Decimal("2_500_000_000"),
        total_debt=Decimal("8_000_000_000"),
        shareholders_equity=Decimal("60_000_000_000"),
        diluted_shares=Decimal("3_500_000_000"),
    )
    repo.conn.commit()


def _seed_macro(repo: Repository, *, as_of: datetime) -> None:
    for i, series_id in enumerate(_BLAST_MACRO_SERIES):
        repo.insert_macro_series_daily(
            series_id=series_id,
            obs_date=date.today() - timedelta(days=1),
            value=Decimal(10 + i),
            as_of=as_of,
            release_date=None,
            source="test",
            source_url=None,
        )
    repo.conn.commit()


def _fetch_analysis_input_jsonb(repo: Repository) -> dict:
    """Return analysis_input_jsonb from the most recently inserted row."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT analysis_input_jsonb
              FROM {repo._schema}.trade_insight_ai_analyses
              ORDER BY requested_at DESC
              LIMIT 1
            """,
        )
        row = cur.fetchone()
    assert row is not None, "no trade_insight_ai_analyses row was persisted"
    return row[0]


def test_blast_lane_emits_all_four_payload_sections_even_with_empty_sources(
    seeded_db_empty_cards,
    monkeypatch,
) -> None:
    """Wiring contract: blast lane must always emit tape/positioning/
    fundamentals/macro keys in analysis_input_jsonb, even when the
    underlying source tables are empty (sections degrade to available=False
    but the keys themselves are present)."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis?kind=blast", json={}
    )
    assert response.status_code == 202, response.text

    analysis_input = _fetch_analysis_input_jsonb(repo)

    # All four blast-only sections must be present
    assert "tape" in analysis_input, (
        "tape missing — blast lane wiring regressed; "
        f"keys present: {sorted(analysis_input.keys())}"
    )
    assert "positioning" in analysis_input
    assert "fundamentals" in analysis_input
    assert "macro" in analysis_input

    # With empty source tables, each section's available flag is False
    assert analysis_input["tape"]["available"] is False
    assert analysis_input["positioning"]["available"] is False
    assert analysis_input["fundamentals"]["available"] is False
    # macro is None when no series exist — assembler emits {available: False}
    assert analysis_input["macro"]["available"] is False


def test_blast_lane_picks_up_seeded_source_data(
    seeded_db_empty_cards,
    monkeypatch,
) -> None:
    """When the four source tables are populated, the blast payload picks
    up the data — tape.available=True with bars>0, positioning.available
    =True with si_pct_float, etc."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    _seed_ohlc_rows(repo, ticker="TSLA", n=60)
    _seed_positioning(repo, ticker="TSLA")
    _seed_fundamentals(repo, ticker="TSLA")
    _seed_macro(repo, as_of=datetime.now(timezone.utc))
    repo.conn.commit()
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis?kind=blast", json={}
    )
    assert response.status_code == 202, response.text

    analysis_input = _fetch_analysis_input_jsonb(repo)

    tape = analysis_input["tape"]
    assert tape["available"] is True
    assert tape["bars"] == 60
    assert tape["dma_50"] is not None  # 60 bars > 50, dma_50 computable
    assert tape["return_5d"] is not None
    assert tape["return_20d"] is not None
    assert tape["drawdown_from_6m_high"] is not None

    positioning = analysis_input["positioning"]
    assert positioning["available"] is True
    assert positioning["si_pct_float"] == "15.0"
    assert positioning["earn_reactions_positive"] == 3
    assert positioning["earn_reactions_total"] == 4

    fundamentals = analysis_input["fundamentals"]
    assert fundamentals["available"] is True
    assert fundamentals["fiscal_period"] == "Q1"

    macro = analysis_input["macro"]
    assert macro["available"] is not False
    # All 6 curated series surface as nested objects
    for series_id in _BLAST_MACRO_SERIES:
        assert series_id in macro, (
            f"{series_id} missing from blast macro payload; "
            f"keys: {sorted(macro.keys())}"
        )
        assert macro[series_id]["value"] is not None


def test_insights_lane_does_not_receive_blast_only_payload_sections(
    seeded_db_empty_cards,
    monkeypatch,
) -> None:
    """Regression assertion: the v5.3 insights lane must continue to omit
    tape/positioning/fundamentals/macro from its analysis_input. The
    insights assembler doesn't take those kwargs at all, so passing them
    would raise TypeError. The conditional-extra-kwargs wiring guarantees
    the insights lane stays byte-identical."""
    repo = seeded_db_empty_cards
    _seed_run(repo)
    # Even seed the source tables — insights lane must IGNORE them.
    _seed_ohlc_rows(repo, ticker="TSLA", n=60)
    _seed_positioning(repo, ticker="TSLA")
    _patch_api_sources(monkeypatch)
    client = _client_for_settings(_settings_for_repo(repo))

    response = client.post(
        "/api/stock/TSLA/trade-insights/ai-analysis?kind=insights", json={}
    )
    assert response.status_code == 202, response.text

    analysis_input = _fetch_analysis_input_jsonb(repo)

    blast_only_keys = {"tape", "fundamentals", "positioning", "macro"}
    leaked = blast_only_keys & set(analysis_input.keys())
    assert not leaked, (
        f"insights lane leaked blast-only keys: {sorted(leaked)}; "
        "the extra_kwargs gate must be is_blast-conditional"
    )
