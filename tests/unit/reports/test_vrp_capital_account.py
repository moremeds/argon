import math
from datetime import date

from uw_scan.reports.vrp_macro_drawdown import INDEX_SPECS


def test_spy_in_index_specs():
    spec = INDEX_SPECS["SPY"]
    assert spec["vol"] == "VIX"
    assert spec["spot_source"] == "lake"
    assert spec["spot_symbol"] == "SPY"
    assert spec["start"] == date(2006, 1, 1)


# --- Task 2: desired_contracts ---------------------------------------------
from uw_scan.reports.vrp_capital_account import CapitalConfig, desired_contracts


def test_desired_contracts_base_floor_no_overlay():
    # w=1 full base, 5% of $50k = $2500 risk; mlpc=$1000 → floor(2.5)=2 base, z below threshold → 0 overlay
    cfg = CapitalConfig(base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 0.4, 1000.0, cfg)
    assert (base, overlay) == (2, 0)


def test_desired_contracts_base_scaled_by_w():
    # ramp+ half-size w=0.5 → $1250 risk / $1000 = floor(1.25)=1
    cfg = CapitalConfig(base_risk_pct=0.05, rich_threshold=1.0)
    base, overlay = desired_contracts(0.5, 0.25, 1000.0, cfg)
    assert (base, overlay) == (1, 0)


def test_desired_contracts_overlay_fires_when_rich():
    # z >= rich_threshold=1.0 → overlay = floor(overlay_mult(1.0)*0.05*50000 / 1000) = floor(2.5)=2
    cfg = CapitalConfig(base_risk_pct=0.05, overlay_mult=1.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 1.2, 1000.0, cfg)
    assert (base, overlay) == (2, 2)


def test_desired_contracts_overlay_not_w_scaled():
    # overlay is binary-fixed, independent of w; double mult → floor(2*2500/1000)=5
    cfg = CapitalConfig(base_risk_pct=0.05, overlay_mult=2.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 1.5, 1000.0, cfg)
    assert overlay == 5


def test_desired_contracts_zero_weight_zero_base():
    cfg = CapitalConfig(base_risk_pct=0.05, rich_threshold=1.0)
    base, overlay = desired_contracts(0.0, None, 1000.0, cfg)
    assert (base, overlay) == (0, 0)


def test_desired_contracts_unaffordable_single_contract_is_zero():
    # mlpc bigger than the whole risk budget → 0 base
    cfg = CapitalConfig(base_risk_pct=0.05, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 0.4, 9000.0, cfg)  # 2500/9000 → floor 0
    assert base == 0


def test_desired_contracts_no_overlay_without_base():
    # base floors to 0 (budget < 1 contract) but overlay_mult=2 would round up → must be 0:
    # an "extra set" needs a base set to add to. base_risk%=0.03×50k=$1500 < mlpc $1600.
    cfg = CapitalConfig(base_risk_pct=0.03, overlay_mult=2.0, rich_threshold=1.0)
    base, overlay = desired_contracts(1.0, 1.5, 1600.0, cfg)  # base floor(1500/1600)=0
    assert (base, overlay) == (0, 0)


# --- Task 3: simulate_account ----------------------------------------------
from datetime import timedelta
from types import SimpleNamespace

from uw_scan.reports.vrp_capital_account import AccountResult, simulate_account
from uw_scan.reports.vrp_macro_drawdown import _Loaded


def _settings():
    # real config defaults, frozen here so the unit test needs no env/DB
    return SimpleNamespace(
        vrp_risk_free_rate=0.04,
        vrp_cost_per_contract=0.65,
        vrp_slippage_frac=0.01,
        vrp_slippage_min=0.05,
        vrp_cost_round_trip=True,
    )


def _synthetic_loaded(*, spot, iv, z, start=date(2020, 1, 1), n=80):
    """A labelled SYNTHETIC _Loaded (test double of load_index_vol output) for
    exercising the LEDGER — not market data. Flat spot/iv/z across n trading days
    (weekday-spaced) so contract math is hand-checkable."""
    dates = []
    d = start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    adj = [(dd, float(spot)) for dd in dates]
    pidx = {dd: k for k, dd in enumerate(dates)}
    rows = [
        {"market_date": dd, "iv": float(iv), "rv": None, "vrp": None, "vrp_z_20": z}
        for dd in dates
    ]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def test_simulate_single_name_opens_weekly_rungs():
    # one name, ample capital, cheap-but-positive z (w<1 via ramp+) → base only, no skips
    loaded = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)
    cfg = CapitalConfig(
        capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0, names=("SPY",)
    )
    res = simulate_account({"SPY": loaded}, _settings(), cfg)
    assert isinstance(res, AccountResult)
    assert res.n_skipped_rungs == 0
    assert all(r.contracts >= 1 for r in res.rungs)
    # weekly cadence over (n - hold_days) = (80 - 30) trading days → entries at 0,5,...,45 → 10 rungs
    assert len(res.rungs) == 10


def test_simulate_overlay_adds_contracts_when_rich():
    cheap = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)  # w<1, no overlay
    rich = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5)  # w=1 + overlay fires
    cfg = CapitalConfig(
        capital=50_000.0,
        base_risk_pct=0.05,
        overlay_mult=1.0,
        rich_threshold=1.0,
        names=("SPY",),
    )
    c_cheap = sum(
        r.contracts for r in simulate_account({"SPY": cheap}, _settings(), cfg).rungs
    )
    c_rich = sum(
        r.contracts for r in simulate_account({"SPY": rich}, _settings(), cfg).rungs
    )
    assert c_rich > c_cheap


def test_simulate_capital_cap_forces_skips():
    # tiny capital + rich z (wants base+overlay) → most rungs can't fit → skips logged
    rich = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5)
    cfg = CapitalConfig(
        capital=3_000.0,
        base_risk_pct=0.50,
        overlay_mult=2.0,
        rich_threshold=1.0,
        names=("SPY",),
    )
    res = simulate_account({"SPY": rich}, _settings(), cfg)
    assert res.contracts_filled_total < res.contracts_desired_total
    assert res.n_skipped_rungs > 0


def test_simulate_exit_frees_capital():
    # Sizing is PROPORTIONAL (base_risk_pct × capital), so shrinking capital shrinks
    # per-rung size too — utilisation stays ~6×base_risk_pct regardless of capital
    # level. To make capital genuinely BIND, raise base_risk_pct: ~6 concurrent weekly
    # rungs (30d hold / 5d cadence) at 30% each would want ~180% of capital. Capital
    # must therefore bind (skips). But margin is released at each rung's expiry, so new
    # rungs keep opening across the window — far more rungs fill than fit at once,
    # which can ONLY happen if exits free capital (no recycling ⇒ fill once, then all
    # skip forever ⇒ at most `concurrent_capacity` rungs).
    rich = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5, n=120)
    cfg = CapitalConfig(
        capital=50_000.0,
        base_risk_pct=0.30,
        overlay_mult=0.0,
        rich_threshold=1.0,
        names=("SPY",),
    )
    res = simulate_account({"SPY": rich}, _settings(), cfg)
    assert res.n_skipped_rungs > 0  # capital bound at least once
    # the first rung opens on an empty account → full size; capacity = how many such
    # full rungs fit at once.
    full_rung_margin = res.rungs[0].margin
    concurrent_capacity = math.floor(cfg.capital / full_rung_margin)
    assert (
        len(res.rungs) > concurrent_capacity
    )  # recycled: more filled than fit at once
    # never over-deploys: peak utilisation <= 100% of capital
    peak = max(u for _, u in res.util_by_date)
    assert peak <= 1.0 + 1e-9


def test_simulate_shared_capital_across_names():
    # two names competing for one pool deploy more total than each alone but never > capital
    a = _synthetic_loaded(spot=400.0, iv=0.20, z=1.5)
    b = _synthetic_loaded(spot=300.0, iv=0.22, z=1.5)
    cfg = CapitalConfig(
        capital=50_000.0,
        base_risk_pct=0.05,
        overlay_mult=1.0,
        rich_threshold=1.0,
        names=("SPY", "QQQ"),
    )
    res = simulate_account({"SPY": a, "QQQ": b}, _settings(), cfg)
    assert {r.name for r in res.rungs} == {"SPY", "QQQ"}
    assert max(u for _, u in res.util_by_date) <= 1.0 + 1e-9


def test_simulate_respects_capcfg_names_ignores_extra_loadeds():
    # a loaded sleeve absent from capcfg.names must NOT trade (names is authoritative)
    spy = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)
    extra = _synthetic_loaded(spot=100.0, iv=0.50, z=2.0)
    cfg = CapitalConfig(
        capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0, names=("SPY",)
    )
    res = simulate_account({"SPY": spy, "ZZZ": extra}, _settings(), cfg)
    assert {r.name for r in res.rungs} == {"SPY"}  # ZZZ ignored despite being passed
