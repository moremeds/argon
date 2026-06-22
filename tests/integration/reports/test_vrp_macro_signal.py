"""Promoted winner config end-to-end: the laddered/sized backtest runs over a real
Postgres-backed SPX+VIX series, and the weekly readout emits TRADE/SKIP + strikes."""

import math
from datetime import date, timedelta

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import (
    WINNER,
    backtest_laddered,
    current_macro_signal,
)


def _seed_spx_vix_varied(repo, *, days=420):
    """Rising SPX (low realized) + a VIX that oscillates well above realized vol, so
    VRP is rich on average but its z-score still swings positive↔negative — enough
    history (20d RV + 252d z window) for vrp_z to be defined over the tail."""
    start = date(2018, 1, 1)
    px = 2700.0
    with repo.conn.cursor() as cur:
        for i in range(days):
            d = start + timedelta(days=i)
            px *= 1.0004  # steady low-vol uptrend
            vix = 20.0 + 6.0 * math.sin(i / 40.0)  # oscillate ~14..26
            cur.execute(
                "INSERT INTO uw_scan.vol_index_daily(symbol,trade_date,close) "
                "VALUES ('SPX',%s,%s) ON CONFLICT (symbol,trade_date) DO NOTHING",
                (d, round(px, 2)),
            )
            cur.execute(
                "INSERT INTO uw_scan.vol_index_daily(symbol,trade_date,close) "
                "VALUES ('VIX',%s,%s) ON CONFLICT (symbol,trade_date) DO NOTHING",
                (d, round(vix, 2)),
            )
    repo.conn.commit()


def _settings():
    return Settings(api_key=SecretStr("test"))


def test_current_signal_trades_when_vol_is_rich(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    loaded = load_index_vol(repo, "SPX")
    # the richest day on record (highest vrp_z) must produce a sized TRADE
    rich = max(
        (r for r in loaded.rows if r["vrp_z_20"] is not None),
        key=lambda r: r["vrp_z_20"],
    )
    sig = current_macro_signal(repo, _settings(), "SPX", as_of=rich["market_date"])

    assert sig.action == "TRADE"
    assert 0.0 < sig.weight <= 1.0
    assert sig.vrp_z is not None and sig.vrp_z > 0
    # a real bull put spread: sell a put below spot, buy a lower wing, collect credit
    assert sig.short_put < sig.spot
    assert sig.long_put < sig.short_put
    assert sig.credit > 0
    assert 0 < sig.max_loss
    assert math.isclose(sig.max_loss, sig.put_width - sig.credit, rel_tol=1e-9)
    assert sig.hold_days == 30 and sig.short_delta == 0.25 and sig.wing_delta == 0.125
    # context fields are surfaced for the human reading the signal
    assert sig.iv > 0 and sig.rv20 is not None and sig.vrp is not None


def test_current_signal_skips_before_zscore_history_exists(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    loaded = load_index_vol(repo, "SPX")
    # an early date — fewer than 252 VRP observations → vrp_z undefined → SKIP
    early = loaded.rows[100]["market_date"]
    sig = current_macro_signal(repo, _settings(), "SPX", as_of=early)

    assert sig.action == "SKIP"
    assert sig.weight == 0.0
    assert sig.vrp_z is None
    assert sig.short_put is None and sig.credit is None and sig.max_loss is None


def test_laddered_backtest_runs_over_history(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    loaded = load_index_vol(repo, "SPX")
    out = backtest_laddered(loaded, _settings(), WINNER)

    assert out["n"] > 0  # the ramp+ gate let some weekly rungs through
    assert out["maxdd"] <= 0.0  # drawdown is non-positive by construction
    assert isinstance(out["sharpe"], float)
    assert out["monthly"]  # per-month series is populated for sleeve composition


def test_always_on_takes_more_rungs_than_ramp_plus(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spx_vix_varied(repo)
    loaded = load_index_vol(repo, "SPX")
    from uw_scan.reports.vrp_macro_signal import MacroSignalConfig

    ramp_plus = backtest_laddered(loaded, _settings(), WINNER)
    always = backtest_laddered(loaded, _settings(), MacroSignalConfig(sizing="always"))
    # the vrp-z gate is selective: it must enter on no more weeks than always-on
    assert ramp_plus["n"] <= always["n"]
    assert always["n"] > 0
