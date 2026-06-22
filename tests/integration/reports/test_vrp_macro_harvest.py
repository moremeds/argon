from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_harvest import run_vrp_macro_harvest


def _seed(repo, ticker, *, price=100.0):
    """Quiet, persistently-rich macro name: high IV, flat realized path, no earnings."""
    start = date(2024, 1, 1)
    with repo.conn.cursor() as cur:
        for i in range(90):
            d = start + timedelta(days=i)
            cur.execute(
                "INSERT INTO uw_scan.vrp_daily(ticker,market_date,iv,rv,vrp,vrp_z_20) "
                "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, 0.55, 0.12, 0.43, 1.5),
            )
            cur.execute(
                "INSERT INTO uw_scan.realized_volatility_history(ticker,market_date,price) "
                "VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (ticker, d, price),
            )
    repo.conn.commit()


def test_macro_harvest_sweeps_structures_per_direction(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo, "SPY")
    _seed(repo, "IWM")
    out = run_vrp_macro_harvest(
        repo=repo,
        settings=Settings(api_key=SecretStr("test")),
        directions={"SPY": "bullish", "IWM": "neutral"},
    )
    assert out["cells"] > 0
    assert set(out["names"]) == {"SPY", "IWM"}

    rows = repo.fetch_vrp_macro_sweep_results()
    structures = {(r["ticker"], r["structure"]) for r in rows}
    # bullish SPY → both put structures; neutral IWM → condor only
    assert ("SPY", "bull_put_spread") in structures
    assert ("SPY", "cash_secured_put") in structures
    assert ("IWM", "iron_condor") in structures
    assert ("IWM", "bull_put_spread") not in structures  # neutral name, no put-only

    # full + holdout scopes both persisted, and breakeven_win_rate is populated
    spy = [
        r for r in rows if r["ticker"] == "SPY" and r["structure"] == "bull_put_spread"
    ]
    assert {r["scope"] for r in spy} == {"full", "holdout"}
    assert any(r["breakeven_win_rate"] is not None for r in spy)


def test_macro_harvest_skips_names_absent_from_universe(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed(repo, "SPY")
    out = run_vrp_macro_harvest(
        repo=repo,
        settings=Settings(api_key=SecretStr("test")),
        directions={"SPY": "bullish", "QQQ": "bullish"},  # QQQ not seeded
    )
    assert out["names"] == ["SPY"]  # QQQ silently skipped (not in vrp universe)
