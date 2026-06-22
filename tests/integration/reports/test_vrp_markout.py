from __future__ import annotations

from datetime import date, timedelta

import pytest

from uw_scan.reports.vrp_markout import run_vrp_markout


def _seed_vrp_daily(repo, ticker, rows):
    """rows: list of (market_date, iv, rv, vrp_z_20)."""
    repo.upsert_vrp_daily_rows(
        [
            {
                "ticker": ticker,
                "market_date": d,
                "iv": iv,
                "rv": rv,
                "vrp": (iv - rv),
                "vrp_z_20": z,
            }
            for (d, iv, rv, z) in rows
        ]
    )
    repo.conn.commit()


def _seed_macro(repo, ticker):
    """Tag the ticker 'Macro' so asset_class_baseline → index_macro — no earnings
    coverage needed, and the single_name earnings safeguard does not apply."""
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) VALUES (%s, 'Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL",
            (ticker,),
        )
    repo.conn.commit()


def _seed_earnings(repo, ticker, dates):
    """Seed flow_events earnings coverage (run_id FK + unique alert_id required)."""
    run_id = repo.insert_scan_run(ticker=ticker)
    with repo.conn.cursor() as cur:
        for i, d in enumerate(dates):
            cur.execute(
                f"INSERT INTO {repo._schema}.flow_events "
                "(run_id, alert_id, ticker, next_earnings_date) VALUES (%s, %s, %s, %s)",
                (run_id, f"a{i}", ticker, d),
            )
    repo.conn.commit()


def test_run_vrp_markout_marks_rich_bucket_sellable(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")  # index_macro → no earnings coverage required
    # 80 daily rows; RICH signal; iv 0.30, rv 0.20 → realized_VRP +0.10 (over the
    # 0.02 threshold). Scorable obs = anchors 0..59 (i+20 < 80) = 60.
    rows = [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)]
    _seed_vrp_daily(repo, "MACX", rows)

    out = run_vrp_markout(repo=repo)
    assert out["tickers"] >= 1

    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    rich = verdicts[("index_macro", "RICH")]
    assert rich["verdict"] == "HARVEST_SELLABLE"
    assert float(rich["mean_realized_vrp"]) > 0.02
    assert rich["survives_walkforward"] is True
    assert rich["survives_window_gate"] is True
    assert rich["confidence"] == "med"
    assert rich["n"] >= 20


def test_run_vrp_markout_flat_signal_is_none(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")
    # RICH signal but ZERO harvest (iv == rv) → mean 0 → NONE.
    rows = [(start + timedelta(days=i), 0.20, 0.20, 1.5) for i in range(80)]
    _seed_vrp_daily(repo, "MACX", rows)

    run_vrp_markout(repo=repo)
    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    assert verdicts[("index_macro", "RICH")]["verdict"] == "NONE"


def test_run_vrp_markout_excludes_earnings_windows(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    panel = [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)]
    # Both single_name → SAME bucket. Both need earnings COVERAGE so the
    # safeguard does not skip them. CLEAN's earnings is far-future (no window
    # straddles it → 60 obs); ERN's is mid-series at index 10 (anchors 0..9
    # straddle it → 10 dropped → 50 obs).
    _seed_vrp_daily(repo, "CLEAN", panel)
    _seed_earnings(repo, "CLEAN", [date(2030, 1, 1)])
    _seed_vrp_daily(repo, "ERN", panel)
    _seed_earnings(repo, "ERN", [start + timedelta(days=10)])

    out = run_vrp_markout(repo=repo)
    assert out["tickers"] == 2
    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    # 60 (CLEAN, no drops) + 50 (ERN, 10 dropped) = 110, not 120.
    assert verdicts[("single_name", "RICH")]["n"] == 110


def test_run_vrp_markout_skips_single_name_without_earnings_coverage(
    seeded_db_empty_cards,
):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    rows = [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)]
    _seed_vrp_daily(repo, "NOFLOW", rows)  # single_name, NO flow_events earnings

    out = run_vrp_markout(repo=repo)
    # AC2 safeguard: cannot honor the earnings exclusion → skipped entirely.
    assert out["tickers"] == 0
    assert repo.fetch_vrp_harvest_verdicts() == []


def test_run_vrp_markout_exposes_rich_cheap_spread(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")  # index_macro (no earnings needed)
    # rv constant 0.20. RICH days (z=1.5) iv=0.30 → harvest 0.10; CHEAP days
    # (z=-1.5) iv=0.25 → harvest 0.05. spread = 0.10 - 0.05 = 0.05.
    rows = []
    for i in range(100):
        if i < 50:
            rows.append((start + timedelta(days=i), 0.30, 0.20, 1.5))
        else:
            rows.append((start + timedelta(days=i), 0.25, 0.20, -1.5))
    _seed_vrp_daily(repo, "MACX", rows)

    run_vrp_markout(repo=repo)
    verdicts = {
        (v["asset_class"], v["deviation_class"]): v
        for v in repo.fetch_vrp_harvest_verdicts()
    }
    rich = verdicts[("index_macro", "RICH")]
    cheap = verdicts[("index_macro", "CHEAP")]
    assert float(rich["mean_realized_vrp"]) == pytest.approx(0.10, abs=1e-9)
    assert float(cheap["mean_realized_vrp"]) == pytest.approx(0.05, abs=1e-9)
    # AC3: the RICH-CHEAP spread is exposed on every bucket row of the asset class.
    assert float(rich["rich_cheap_spread"]) == pytest.approx(0.05, abs=1e-9)
    assert float(cheap["rich_cheap_spread"]) == pytest.approx(0.05, abs=1e-9)


def test_run_vrp_markout_clears_stale_verdicts(seeded_db_empty_cards):
    # Full-rewrite guarantee: a bucket the current run does NOT produce must not
    # keep serving a stale prior verdict (the DELETE-then-insert in one txn).
    repo = seeded_db_empty_cards
    repo.upsert_vrp_harvest_verdict(
        asset_class="sector_etf",
        deviation_class="RICH",
        verdict="HARVEST_SELLABLE",
        mean_realized_vrp=0.09,
        mean_holdout=0.08,
        rich_cheap_spread=0.04,
        n=99,
        n_holdout=40,
        survives_walkforward=True,
        survives_window_gate=True,
        confidence="med",
        as_of=date(2026, 1, 1),
    )
    repo.conn.commit()
    start = date(2026, 1, 1)
    _seed_macro(repo, "MACX")  # current run only produces index_macro buckets
    _seed_vrp_daily(
        repo,
        "MACX",
        [(start + timedelta(days=i), 0.30, 0.20, 1.5) for i in range(80)],
    )

    run_vrp_markout(repo=repo)
    classes = {v["asset_class"] for v in repo.fetch_vrp_harvest_verdicts()}
    assert "sector_etf" not in classes  # stale row cleared by the full rewrite
    assert "index_macro" in classes
