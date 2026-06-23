import math
from datetime import date, timedelta
from types import SimpleNamespace

from uw_scan.reports.vrp_capital_account import (
    AccountResult,
    CapitalConfig,
    Rung,
    account_metrics,
    desired_contracts,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import INDEX_SPECS, _Loaded


def test_spy_in_index_specs():
    spec = INDEX_SPECS["SPY"]
    assert spec["vol"] == "VIX"
    assert spec["spot_source"] == "lake"
    assert spec["spot_symbol"] == "SPY"
    assert spec["start"] == date(2006, 1, 1)


# --- Task 2: desired_contracts ---------------------------------------------
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


# --- Task 4: account_metrics -----------------------------------------------
def test_account_metrics_handcomputed_returns():
    # two months: +1% then -0.5% of $50k → mean 0.25%/mo → ann excess 3%, gross 7% (rf 4%)
    res = AccountResult(
        rungs=[
            Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 500.0, False),
            Rung("SPY", date(2020, 2, 3), date(2020, 2, 28), 1, 1000.0, -250.0, True),
        ],
        monthly_excess={(2020, 1): 0.01, (2020, 2): -0.005},
        util_by_date=[(date(2020, 1, 6), 0.02), (date(2020, 1, 7), 0.04)],
        n_desired_rungs=2,
        n_skipped_rungs=0,
        contracts_desired_total=2,
        contracts_filled_total=2,
        span=(date(2020, 1, 6), date(2020, 2, 28)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert m["n_rungs"] == 2
    assert abs(m["ann_return_excess"] - 0.03) < 1e-9  # 0.0025 * 12
    assert abs(m["ann_return_gross"] - 0.07) < 1e-9
    assert abs(m["total_return_excess"] - 0.005) < 1e-9
    assert abs(m["win_rate"] - 0.5) < 1e-9
    assert abs(m["breach_rate"] - 0.5) < 1e-9
    assert abs(m["util_peak"] - 0.04) < 1e-9
    assert abs(m["util_mean"] - 0.03) < 1e-9


def test_account_metrics_maxdd_dollars():
    # +$1000 then -$1500 of P&L on $50k → peak +0.02, trough +0.02-0.03 → maxdd -0.03*50000 = -1500
    res = AccountResult(
        rungs=[
            Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 1000.0, False)
        ],
        monthly_excess={(2020, 1): 0.02, (2020, 2): -0.03},
        util_by_date=[],
        n_desired_rungs=1,
        n_skipped_rungs=0,
        contracts_desired_total=1,
        contracts_filled_total=1,
        span=(date(2020, 1, 6), date(2020, 2, 28)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["maxdd_dollars"] + 1500.0) < 1e-6
    assert abs(m["maxdd_pct"] + 0.03) < 1e-9


def test_account_metrics_cagr_geometric():
    # series [+1%, -0.5%] over 2 months → years=2/12, total_excess=0.005.
    # cagr_excess = 1.005^(12/2) - 1; gross adds rf-compounded cash over 1/6 year.
    res = AccountResult(
        rungs=[
            Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 500.0, False)
        ],
        monthly_excess={(2020, 1): 0.01, (2020, 2): -0.005},
        util_by_date=[],
        n_desired_rungs=2,
        n_skipped_rungs=0,
        contracts_desired_total=2,
        contracts_filled_total=2,
        span=(date(2020, 1, 6), date(2020, 2, 28)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["years"] - 2 / 12) < 1e-12
    assert abs(m["cagr_excess"] - (1.005 ** (12 / 2) - 1)) < 1e-9
    gross_total = (1.04) ** (2 / 12) - 1 + 0.005
    assert abs(m["cagr_gross"] - ((1 + gross_total) ** (12 / 2) - 1)) < 1e-9


def test_account_metrics_skip_and_fill_rates():
    res = AccountResult(
        rungs=[
            Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 10.0, False)
        ],
        monthly_excess={(2020, 1): 0.0002},
        util_by_date=[(date(2020, 1, 6), 0.02)],
        n_desired_rungs=4,
        n_skipped_rungs=1,
        contracts_desired_total=10,
        contracts_filled_total=6,
        span=(date(2020, 1, 6), date(2020, 1, 31)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert abs(m["skip_rate"] - 0.25) < 1e-9
    assert abs(m["fill_rate"] - 0.6) < 1e-9


def test_account_metrics_zero_fills_gap_months():
    # Jan +2%, (Feb empty), Mar +2% → contiguous series [0.02, 0.0, 0.02] over 3 months.
    # mean = 0.0133.. → ann excess 0.16; the empty Feb must be zero-filled, not dropped,
    # or Sharpe/maxDD would be wrong.
    res = AccountResult(
        rungs=[
            Rung("SPY", date(2020, 1, 6), date(2020, 1, 31), 1, 1000.0, 1000.0, False)
        ],
        monthly_excess={(2020, 1): 0.02, (2020, 3): 0.02},
        util_by_date=[],
        n_desired_rungs=2,
        n_skipped_rungs=0,
        contracts_desired_total=2,
        contracts_filled_total=2,
        span=(date(2020, 1, 6), date(2020, 3, 31)),
    )
    m = account_metrics(res, CapitalConfig(capital=50_000.0), rf=0.04)
    assert (
        abs(m["ann_return_excess"] - (0.04 / 3 * 12)) < 1e-9
    )  # mean of [.02,0,.02]=.0133*12
    assert abs(m["total_return_excess"] - 0.04) < 1e-9
    assert m["maxdd_dollars"] <= 0.0  # monotone-up curve → no drawdown


# --- Task 1 (iter4): compounding ------------------------------------------
def test_desired_contracts_sizing_capital_overrides_capital():
    # base sized off sizing_capital, not capcfg.capital: 5% of $100k / $1000 = floor(5)=5
    cfg = CapitalConfig(capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0)
    base, _ = desired_contracts(1.0, 0.4, 1000.0, cfg, sizing_capital=100_000.0)
    assert base == 5


def test_compounding_grows_position_after_wins():
    # A flat, always-winning synthetic SPX: equity rises → compounding sizes bigger
    # later rungs than the fixed-capital book. 5% risk × ~6 concurrent rungs ≈ 30% util,
    # so no capital cap — the only thing that grows later rungs is compounding.
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=300)
    base = CapitalConfig(
        capital=50_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
        compounding=False,
    )
    comp = CapitalConfig(
        capital=50_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
        compounding=True,
    )
    rb = simulate_account({"SPX": ld}, _settings(), base)
    rc = simulate_account({"SPX": ld}, _settings(), comp)
    assert rc.rungs[-1].contracts >= rb.rungs[-1].contracts
    assert sum(r.contracts for r in rc.rungs) > sum(r.contracts for r in rb.rungs)


# --- Task 2 (iter4): weekday + jitter -------------------------------------
def test_entry_weekday_filters_to_one_weekday():
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
        entry_weekday=2,  # Wednesday
    )
    res = simulate_account({"SPX": ld}, _settings(), cfg)
    assert res.rungs
    assert all(r.entry_date.weekday() == 2 for r in res.rungs)


def test_entry_jitter_is_deterministic_for_a_seed():
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
        entry_jitter=2,
        jitter_seed=7,
    )
    a = simulate_account({"SPX": ld}, _settings(), cfg)
    b = simulate_account({"SPX": ld}, _settings(), cfg)
    assert [r.entry_date for r in a.rungs] == [r.entry_date for r in b.rungs]


def test_entry_jitter_zero_matches_plain_stride():
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    plain = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    jit0 = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
        entry_jitter=0,
        jitter_seed=7,
    )
    assert [
        r.entry_date for r in simulate_account({"SPX": ld}, _settings(), plain).rungs
    ] == [r.entry_date for r in simulate_account({"SPX": ld}, _settings(), jit0).rungs]


# --- Task 3 (iter4): staggered extra tranche ------------------------------
def test_extra_tranche_adds_staggered_rungs_when_rich():
    # z=1.0 >= rich_threshold 1.0 everywhere → every base week spawns a +2-day extra
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=1.0, n=200)
    plain = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=1.0,
        names=("SPX",),
    )
    extra = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=1.0,
        names=("SPX",),
        extra_tranche=True,
        extra_tranche_stagger=2,
    )
    rp = simulate_account({"SPX": ld}, _settings(), plain)
    rx = simulate_account({"SPX": ld}, _settings(), extra)
    assert len(rx.rungs) > len(rp.rungs)
    # extra entries land 2 trading days off the weekly stride → some not in the base set
    base_dates = {r.entry_date for r in rp.rungs}
    assert any(r.entry_date not in base_dates for r in rx.rungs)


def test_extra_tranche_silent_when_never_rich():
    # z=0.2 < rich_threshold 1.0 → no extra fires; identical to plain
    ld = _synthetic_loaded(spot=100.0, iv=0.30, z=0.2, n=200)
    plain = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=1.0,
        names=("SPX",),
    )
    extra = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=1.0,
        names=("SPX",),
        extra_tranche=True,
    )
    rp = simulate_account({"SPX": ld}, _settings(), plain)
    rx = simulate_account({"SPX": ld}, _settings(), extra)
    assert [r.entry_date for r in rp.rungs] == [r.entry_date for r in rx.rungs]


def test_all_iter4_flags_off_matches_legacy_defaults():
    # Golden reconciliation: the six new flags at their DEFAULTS must be a pure no-op.
    # Same fixture as test_simulate_single_name_opens_weekly_rungs (which pins len==10).
    ld = _synthetic_loaded(spot=400.0, iv=0.20, z=0.3)
    default = CapitalConfig(
        capital=50_000.0, base_risk_pct=0.05, rich_threshold=1.0, names=("SPY",)
    )
    explicit = CapitalConfig(
        capital=50_000.0,
        base_risk_pct=0.05,
        rich_threshold=1.0,
        names=("SPY",),
        compounding=False,
        entry_weekday=None,
        entry_jitter=0,
        extra_tranche=False,
        extra_tranche_stagger=2,
    )
    a = simulate_account({"SPY": ld}, _settings(), default)
    b = simulate_account({"SPY": ld}, _settings(), explicit)
    assert a.rungs == b.rungs  # Rung is a frozen dataclass → value equality
    assert a.monthly_excess == b.monthly_excess
    assert a.util_by_date == b.util_by_date
    assert (
        a.n_desired_rungs,
        a.n_skipped_rungs,
        a.contracts_desired_total,
        a.contracts_filled_total,
        a.span,
    ) == (
        b.n_desired_rungs,
        b.n_skipped_rungs,
        b.contracts_desired_total,
        b.contracts_filled_total,
        b.span,
    )
    assert len(a.rungs) == 10  # legacy invariant still holds
