from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_spx_vix, run_spx_vix_drawdown


def _seed_spx_vix(repo, *, days=320):
    """Gently-rising SPX + steady VIX in vol_index_daily — enough history for the
    20d realized window + 20d hold to produce entry-spaced trades."""
    start = date(2020, 1, 1)
    px = 3000.0
    with repo.conn.cursor() as cur:
        for i in range(days):
            d = start + timedelta(days=i)
            px *= 1.0005  # ~steady uptrend, low realized vol
            cur.execute(
                "INSERT INTO uw_scan.vol_index_daily(symbol,trade_date,close) "
                "VALUES ('SPX',%s,%s) ON CONFLICT (symbol,trade_date) DO NOTHING",
                (d, round(px, 2)),
            )
            cur.execute(
                "INSERT INTO uw_scan.vol_index_daily(symbol,trade_date,close) "
                "VALUES ('VIX',%s,%s) ON CONFLICT (symbol,trade_date) DO NOTHING",
                (d, 22.0),  # IV ~22% >> realized of a steady drift → rich, sellable
            )
    repo.conn.commit()


def test_drawdown_loader_builds_iv_and_spot(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spx_vix(repo)
    loaded = load_spx_vix(repo, start=date(2020, 1, 1))
    assert len(loaded.adj) > 250  # spot series
    assert loaded.rows[-1]["iv"] == 0.22  # VIX/100
    assert loaded.events == []  # index → no earnings


def test_drawdown_runs_bull_put_spread_over_history(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spx_vix(repo)
    out = run_spx_vix_drawdown(
        repo=repo,
        settings=Settings(api_key=SecretStr("test")),
        structure="bull_put_spread",
        short_delta=0.25,
        hold_days=20,
    )
    assert out["overall"]["n_trades"] > 0
    assert out["years"]  # per-year buckets present
    # steady uptrend + rich IV → the bull put spread should win most trades
    assert out["overall"]["win_rate"] > 0.5
    assert out["max_drawdown_ror"] <= 0  # drawdown is non-positive by construction
