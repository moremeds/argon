"""$1M capital · brp sweep · slippage impact.

Three brp levels (0.20 / 0.32 / 0.50) at $1,000,000 capital.
Two cost scenarios per run:
  ZERO  — no commission, no slippage  (theoretical ceiling)
  REAL  — defaults: 1% half-spread + $0.65/leg commission, round-trip

Slippage model (CostModel.total per rung):
  slip_pts  = Σ_legs max(slip_min, slip_frac × |leg_mid|)
  slip_$    = slip_pts × 100 × contracts × 2 (round-trip)
  commission = $0.65 × n_legs × contracts × 2

Live margin reference: $17,500 per spread (SPX ~7,100, today from UI).

Reproduce (mini):
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
  UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x \\
  uv run python scripts/research/vrp_1m_slippage.py
"""

from __future__ import annotations

import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.storage.repository import Repository

CAPITAL = 1_000_000
BRPS = [0.20, 0.32, 0.50]
CURRENT_MARGIN = 17_500  # live SPX ~7,100, from UI screenshot


def _zero_cost_settings(real: Settings) -> Settings:
    """Same as real but with all costs zeroed."""
    return real.model_copy(
        update={
            "vrp_cost_per_contract": 0.0,
            "vrp_slippage_frac": 0.0,
            "vrp_slippage_min": 0.0,
        }
    )


def _run(loaded_spx, settings: Settings, brp: float) -> dict:
    cfg = CapitalConfig(
        capital=CAPITAL,
        base_risk_pct=brp,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    ledger = simulate_account({"SPX": loaded_spx}, settings, cfg)
    return account_metrics(ledger, cfg, settings.vrp_risk_free_rate)


def main() -> None:
    settings = Settings.from_env()
    zero_s = _zero_cost_settings(settings)

    try:
        conn = psycopg.connect(settings.db_dsn())
    except Exception as e:
        print(f"DB connect failed: {e}", file=sys.stderr)
        sys.exit(1)

    repo = Repository(conn, schema=settings.db_schema)
    loaded = load_index_vol(repo, "SPX")
    conn.close()

    print(f"\n{'=' * 74}")
    print(f"  VRP @ $1,000,000 — SPX BULL PUT SPREAD · HOLD TO EXPIRY")
    print(f"  Slippage: 1% half-spread per leg + $0.65/leg commission (round-trip)")
    print(f"  Live margin today: ${CURRENT_MARGIN:,}/spread  |  Data: 2006-2026 (19yr)")
    print(f"{'=' * 74}")

    rows = {}
    for brp in BRPS:
        contracts_now = int(brp * CAPITAL / CURRENT_MARGIN)
        real = _run(loaded, settings, brp)
        zero = _run(loaded, zero_s, brp)
        rows[brp] = {"real": real, "zero": zero, "contracts": contracts_now}
        print(f"  computed brp={brp:.2f}  contracts/entry={contracts_now}")

    # ── Per-brp detail blocks ────────────────────────────────────────────────
    for brp in BRPS:
        r = rows[brp]["real"]
        z = rows[brp]["zero"]
        c = rows[brp]["contracts"]

        ann_real = r.get("ann_return_gross", 0) * CAPITAL
        ann_zero = z.get("ann_return_gross", 0) * CAPITAL
        slip_drag = ann_zero - ann_real

        mo_real = ann_real / 12
        mo_zero = ann_zero / 12
        mo_drag = slip_drag / 12

        print(f"\n{'─' * 74}")
        print(
            f"  brp = {brp:.2f}   →   {c} contracts/entry   (budget = ${brp * CAPITAL:,.0f})"
        )
        print(f"{'─' * 74}")
        print(
            f"  {'Metric':<28}  {'No slippage':>14}  {'With slippage':>14}  {'Drag':>10}"
        )
        print(f"  {'─' * 70}")

        def row(name, z_val, r_val, fmt=lambda v: f"${v:>12,.0f}"):
            drag = r_val - z_val
            drag_s = f"({abs(drag):,.0f})" if drag < 0 else f"+{drag:,.0f}"
            print(f"  {name:<28}  {fmt(z_val):>14}  {fmt(r_val):>14}  {drag_s:>10}")

        def pct(v):
            return f"{v * 100:>11.1f}%"

        row("Avg monthly income", mo_zero, mo_real)
        row("Annual income", ann_zero, ann_real)
        row("CAGR gross", z.get("cagr_gross", 0), r.get("cagr_gross", 0), pct)
        row("Sharpe", z.get("sharpe", 0), r.get("sharpe", 0), lambda v: f"{v:>13.2f}")
        row(
            "Max drawdown %",
            z.get("maxdd_pct", 0),
            r.get("maxdd_pct", 0),
            lambda v: f"{v * 100:>11.1f}%",
        )
        row("Win rate", z.get("win_rate", 0), r.get("win_rate", 0), pct)
        row("Skip rate", z.get("skip_rate", 0), r.get("skip_rate", 0), pct)
        row(
            "Entries/yr",
            z.get("n_rungs", 0) / 19,
            r.get("n_rungs", 0) / 19,
            lambda v: f"{v:>13.1f}",
        )

        print(
            f"\n  Annual slippage drag        : ${slip_drag:>12,.0f}  ({slip_drag / ann_zero * 100:.1f}% of gross)"
        )
        print(f"  Monthly slippage drag       : ${mo_drag:>12,.0f}")
        print(
            f"  Per-rung drag (÷ entries)   : ${slip_drag / max(r.get('n_rungs', 1), 1):>12,.0f}"
        )

    # ── Summary table ────────────────────────────────────────────────────────
    print(f"\n{'=' * 74}")
    print(f"  SUMMARY — $1,000,000 · WITH SLIPPAGE (deployable numbers)")
    print(f"{'─' * 74}")
    print(
        f"  {'brp':>6}  {'Contracts':>10}  {'Monthly':>12}  {'Annual':>10}  "
        f"{'CAGR':>7}  {'Sharpe':>7}  {'MaxDD':>8}  {'Skip%':>6}"
    )
    print(f"  {'─' * 70}")
    for brp in BRPS:
        r = rows[brp]["real"]
        c = rows[brp]["contracts"]
        ann = r.get("ann_return_gross", 0) * CAPITAL
        tag = (
            " ← recommended"
            if brp == 0.20
            else (" ← fragile IS" if brp == 0.32 else "")
        )
        print(
            f"  {brp:>6.2f}  {c:>10}  ${ann / 12:>10,.0f}  ${ann:>8,.0f}  "
            f"{r.get('cagr_gross', 0) * 100:>6.1f}%  {r.get('sharpe', 0):>7.2f}  "
            f"{r.get('maxdd_pct', 0) * 100:>7.1f}%  {r.get('skip_rate', 0) * 100:>5.1f}%{tag}"
        )

    print(f"\n  Max simultaneous slots: 6  (hold 30td ÷ cadence 5td)")
    print(
        f"  Max margin at once:  6 × {rows[BRPS[0]]['contracts']} contracts × ${CURRENT_MARGIN:,}"
    )
    print(f"  MaxDD warning: numbers are vs $1M starting capital (non-compounding);")
    print(f"  forward (post-2011) maxDD is far smaller — worst ≈ -10% (see MASTER doc)")
    print(f"{'=' * 74}\n")


if __name__ == "__main__":
    main()
