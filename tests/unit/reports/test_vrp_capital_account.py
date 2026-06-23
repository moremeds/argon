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
