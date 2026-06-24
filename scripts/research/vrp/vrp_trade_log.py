"""Real per-trade fill log for the iteration-4 base case (SPX WINNER, $143k floor account).

Mirrors `vrp_capital_account.simulate_account`'s base path EXACTLY — same candidate
schedule, same sizing + capital cap, same `_settle` settlement — but records every filled
rung's full detail: entry day, spot, VIX, vrp_z, the two strikes, credit, max-loss,
contracts, margin, exit day, settlement spot, breach, net P&L, ROR.

Writes the full log to docs/research/vrp/_iterations/iter4-trade-log.csv and prints the 2008 (GFC) and
2022 (bear) windows. Real data only (SPX+VIX from vol_index_daily). No synthetic values.

Run (MacBook local):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_trade_log.py
"""

from __future__ import annotations

import csv
import math
import pathlib

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CONTRACT_MULTIPLIER,
    CapitalConfig,
    _cost_model,
    _entry_indices,
    desired_contracts,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_harvest import _settle
from uw_scan.reports.vrp_macro_signal import size_weight
from uw_scan.reports.vrp_structure import build_bull_put_spread
from uw_scan.storage.repository import Repository

OUT = pathlib.Path("docs/research/vrp/_iterations/iter4-trade-log.csv")
# the iteration-4 base case: $143k trade-throughout account, 20% risk/spread, SPX-only,
# non-compounding, no overlay/tranche (matches base_noncomp / baseline_iter3_spx).
CAPCFG = CapitalConfig(
    capital=143_000.0,
    base_risk_pct=0.20,
    overlay_mult=0.0,
    rich_threshold=99.0,
    names=("SPX",),
)
FIELDS = [
    "entry_date",
    "spot",
    "vix",
    "rv",
    "vrp_z",
    "w",
    "short_put",
    "long_put",
    "width",
    "credit_pts",
    "credit_usd",
    "max_loss_usd",
    "contracts",
    "margin_usd",
    "exit_date",
    "exit_spot",
    "breached",
    "net_pnl_usd",
    "ror",
]


def build_trade_log(loaded, settings, capcfg: CapitalConfig) -> list[dict]:
    """Faithful replay of simulate_account's base path with full per-trade logging."""
    cfg = capcfg.base_cfg
    cost = _cost_model(settings)
    r = settings.vrp_risk_free_rate
    hold = cfg.hold_days
    nm = capcfg.names[0]
    ld = loaded
    iv_map = {row["market_date"]: row["iv"] for row in ld.rows}
    rv_map = {row["market_date"]: row["rv"] for row in ld.rows}
    z_map = {row["market_date"]: row["vrp_z_20"] for row in ld.rows}

    opened: list[tuple] = []  # (entry, exit, margin)
    rows: list[dict] = []
    for pi in _entry_indices(ld, hold, capcfg, nm):
        d = ld.adj[pi][0]
        iv = iv_map.get(d)
        s0 = ld.adj[pi][1]
        if iv is None or iv <= 0 or s0 <= 0:
            continue
        z = z_map.get(d)
        w = size_weight(z, cfg)
        try:
            st = build_bull_put_spread(
                s0,
                float(iv),
                hold / 252.0,
                r,
                short_delta=cfg.short_delta,
                wing_delta=cfg.wing_delta,
            )
        except ValueError:
            continue
        mlpc = st.max_loss * CONTRACT_MULTIPLIER
        base_d, overlay_d = desired_contracts(
            w, z, mlpc, capcfg, sizing_capital=capcfg.capital
        )
        total_d = base_d + overlay_d
        if total_d <= 0:
            continue
        exit_date = ld.adj[pi + hold][0]
        deployed = sum(m for (_e, xd, m) in opened if xd > d)
        available = capcfg.capital - deployed
        affordable = math.floor(available / mlpc) if mlpc > 0 else 0
        actual = min(total_d, max(0, affordable))
        if actual <= 0:
            continue  # capital-skip (not a fill)
        net, ror, breached, x_d, x_spot = _settle(
            st, pi, hold, ld.adj, iv_map, r, cost=cost, contracts=actual
        )
        opened.append((d, exit_date, mlpc * actual))
        rows.append(
            {
                "entry_date": d,
                "spot": round(s0, 2),
                "vix": round(float(iv) * 100, 2),
                "rv": round(rv_map.get(d), 4) if rv_map.get(d) is not None else None,
                "vrp_z": round(z, 3) if z is not None else None,
                "w": round(w, 3),
                "short_put": round(st.short_put, 1),
                "long_put": round(st.long_put, 1),
                "width": round(st.put_width, 1),
                "credit_pts": round(st.credit, 3),
                "credit_usd": round(st.credit * CONTRACT_MULTIPLIER * actual, 0),
                "max_loss_usd": round(mlpc, 0),
                "contracts": actual,
                "margin_usd": round(mlpc * actual, 0),
                "exit_date": x_d,
                "exit_spot": round(x_spot, 2),
                "breached": breached,
                "net_pnl_usd": round(net, 0),
                "ror": round(ror, 3),
            }
        )
    return rows


def main() -> None:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    repo = Repository(conn, schema=settings.db_schema)
    try:
        spx = load_index_vol(repo, "SPX")
        rows = build_trade_log(spx, settings, CAPCFG)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        with OUT.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="raise")
            w.writeheader()
            w.writerows(rows)
        print(f"wrote {len(rows)} fills -> {OUT}")
        n_win = sum(1 for r in rows if r["net_pnl_usd"] > 0)
        print(
            f"total net P&L ${sum(r['net_pnl_usd'] for r in rows):,.0f}  "
            f"win-rate {n_win / len(rows):.1%}  breach-rate "
            f"{sum(1 for r in rows if r['breached']) / len(rows):.1%}\n"
        )
        for label, yr in (("GFC 2008", 2008), ("Bear 2022", 2022)):
            sub = [r for r in rows if r["entry_date"].year == yr]
            print(f"=== {label} — {len(sub)} fills ===")
            print(
                f"{'entry':>10} {'spot':>8} {'vix':>6} {'z':>6} {'w':>5} "
                f"{'Kshort':>8} {'Klong':>8} {'cr$':>7} {'ctr':>4} "
                f"{'exit':>10} {'S_T':>8} {'br':>3} {'netP&L':>9}"
            )
            for r in sub:
                print(
                    f"{str(r['entry_date']):>10} {r['spot']:>8.0f} {r['vix']:>6.1f} "
                    f"{(r['vrp_z'] if r['vrp_z'] is not None else float('nan')):>6.2f} "
                    f"{r['w']:>5.2f} {r['short_put']:>8.0f} {r['long_put']:>8.0f} "
                    f"{r['credit_usd']:>7,.0f} {r['contracts']:>4} {str(r['exit_date']):>10} "
                    f"{r['exit_spot']:>8.0f} {('Y' if r['breached'] else '.'): >3} "
                    f"{r['net_pnl_usd']:>9,.0f}"
                )
            print(
                f"  -> {label} net ${sum(r['net_pnl_usd'] for r in sub):,.0f} "
                f"over {len(sub)} fills, {sum(1 for r in sub if r['breached'])} breached\n"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
