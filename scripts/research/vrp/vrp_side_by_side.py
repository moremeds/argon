"""Side-by-side VRP strategy analysis: 3 exit rules × capital scaling.

Three exit variants on the WINNER config (SPX bull put spread, 0.25Δ/0.125Δ,
~30 trading-day entry, weekly ramp+ gate):
  A) 15 trading DTE remaining  (hold 15 trading days, ~21 cal DTE at exit)
  B) 15 calendar DTE remaining (hold 20 trading days, ~10 trading DTE at exit)
  C) Hold to expiry            (hold 30 trading days, 0 DTE)

Capital scaling section shows 1/2/3 concurrent spreads.

Reproduce (mini):
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
  UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x \\
  uv run python scripts/research/vrp_side_by_side.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from statistics import mean, median, pstdev

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER, _cost_model, size_weight
from uw_scan.reports.vrp_structure import build_bull_put_spread
from uw_scan.storage.repository import Repository

ENTRY_HOLD = WINNER.hold_days  # 30 trading days (~45 cal DTE entry)
CONTRACTS = 1

# Exit variants: (label, exit_after_trading_days)
EXITS = [
    ("15 trd DTE", 15),  # hold 15 trading days → 15 trading DTE remain (~21 cal)
    ("15 cal DTE", 20),  # hold 20 trading days → 10 trading DTE remain (~15 cal)
    ("To expiry", 30),  # hold to expiry (0 DTE)
]


def _backtest_one(loaded, settings, cost, exit_after: int) -> list[dict]:
    adj = loaded.adj
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    vrpz_map = {row["market_date"]: row.get("vrp_z_20") for row in loaded.rows}

    t_entry = ENTRY_HOLD / 252.0
    t_exit = max(0.0, (ENTRY_HOLD - exit_after) / 252.0)
    r = settings.vrp_risk_free_rate

    trades: list[dict] = []
    last_k = -WINNER.cadence

    for row in sorted(loaded.rows, key=lambda x: x["market_date"]):
        d = row["market_date"]
        pi = loaded.pidx.get(d)
        if pi is None:
            continue
        if pi + ENTRY_HOLD >= len(adj):
            break
        if pi - last_k < WINNER.cadence:
            continue

        z = vrpz_map.get(d)
        w = size_weight(z, WINNER)
        if w <= 0:
            continue

        iv = iv_map.get(d)
        if not iv or iv <= 0:
            continue
        _, S_entry = adj[pi]

        spread = build_bull_put_spread(
            S_entry,
            iv,
            t_entry,
            r,
            short_delta=WINNER.short_delta,
            wing_delta=WINNER.wing_delta,
        )
        credit_usd = spread.credit * cost.multiplier * CONTRACTS
        margin_usd = spread.max_loss * cost.multiplier * CONTRACTS

        exit_k = pi + exit_after
        if exit_k >= len(adj):
            break
        d_exit, S_exit = adj[exit_k]

        # T=0 at expiry → intrinsic regardless of IV; use dummy IV
        iv_exit = iv_map.get(d_exit) or 0.2
        close_val = spread.value(S_exit, t_exit, r, iv_exit)
        captured_usd = (spread.credit - close_val) * cost.multiplier * CONTRACTS

        breached = any(adj[k][1] <= spread.short_put for k in range(pi + 1, exit_k + 1))

        trades.append(
            {
                "entry_date": d,
                "exit_date": d_exit,
                "credit_usd": credit_usd,
                "margin_usd": margin_usd,
                "captured_usd": captured_usd,
                "breached": breached,
            }
        )
        last_k = pi

    return trades


def _metrics(trades: list[dict]) -> dict:
    if not trades:
        return {}
    monthly: dict[tuple, list[float]] = defaultdict(list)
    for t in trades:
        ym = (t["entry_date"].year, t["entry_date"].month)
        monthly[ym].append(t["captured_usd"])
    monthly_totals = [sum(v) for v in monthly.values()]

    caps = [t["captured_usd"] for t in trades]
    marg = [t["margin_usd"] for t in trades]
    cred = [t["credit_usd"] for t in trades]
    return {
        "n_trades": len(trades),
        "n_months": len(monthly),
        "avg_margin": mean(marg),
        "max_margin": max(marg),
        "avg_credit": mean(cred),
        "avg_captured": mean(caps),
        "capture_pct": mean(caps) / mean(cred) * 100,
        "win_rate": sum(1 for c in caps if c > 0) / len(caps) * 100,
        "breach_rate": sum(1 for t in trades if t["breached"]) / len(trades) * 100,
        "trades_per_mo": len(trades) / len(monthly),
        "avg_monthly": mean(monthly_totals),
        "med_monthly": median(monthly_totals),
        "best_month": max(monthly_totals),
        "worst_month": min(monthly_totals),
        "std_monthly": pstdev(monthly_totals),
        "loss_months": sum(1 for m in monthly_totals if m < 0),
        "ann_income": mean(monthly_totals) * 12,
    }


def main() -> None:
    settings = Settings.from_env()
    try:
        conn = psycopg.connect(settings.db_dsn())
    except Exception as e:
        print(f"DB connect failed: {e}", file=sys.stderr)
        sys.exit(1)

    repo = Repository(conn, schema=settings.db_schema)
    cost = _cost_model(settings)
    loaded = load_index_vol(repo, "SPX")
    conn.close()

    results = {}
    for label, exit_after in EXITS:
        trades = _backtest_one(loaded, settings, cost, exit_after)
        results[label] = _metrics(trades)
        print(f"  computed: {label}  ({len(trades)} trades)")

    # ── Header ───────────────────────────────────────────────────────────────
    W = 16
    labels = [lbl for lbl, _ in EXITS]
    sep = "─" * (14 + W * 3)

    def row(name, fmt, *vals):
        cells = "".join(f"{v:{W}}" for v in vals)
        print(f"  {name:<30}{cells}")

    def fmt_usd(v):
        return f"${v:>10,.0f}"

    def fmt_pct(v):
        return f"{v:>9.1f}%"

    def fmt_n(v):
        return f"{v:>10.1f}"

    print(f"\n{'=' * 62}")
    print(
        f"  VRP — SPX BULL PUT SPREAD · 1 CONTRACT · {results[labels[0]]['n_trades']} entries (19yr)"
    )
    print("  Entry: ~45 cal DTE (30 trading days) | Ramp+ VRP-z gate")
    print(f"{'=' * 62}")
    print(f"  {'':30}{'15 trd DTE':>{W}}{'15 cal DTE':>{W}}{'To expiry':>{W}}")
    print(f"  {'':30}{'(hold 15td)':>{W}}{'(hold 20td)':>{W}}{'(hold 30td)':>{W}}")
    print(f"  {sep}")

    m = {lbl: results[lbl] for lbl in labels}
    print(f"\n  {'CAPITAL':}")
    row(
        "Avg margin / spread",
        fmt_usd,
        *[fmt_usd(m[lbl]["avg_margin"]) for lbl in labels],
    )
    row(
        "Max margin (today~$7.4k SPX)",
        fmt_usd,
        *[fmt_usd(m[lbl]["max_margin"]) for lbl in labels],
    )

    print(f"\n  {'PER-TRADE':}")
    row("Avg entry credit", fmt_usd, *[fmt_usd(m[lbl]["avg_credit"]) for lbl in labels])
    row(
        "Avg captured at exit",
        fmt_usd,
        *[fmt_usd(m[lbl]["avg_captured"]) for lbl in labels],
    )
    row("Capture ratio", fmt_pct, *[fmt_pct(m[lbl]["capture_pct"]) for lbl in labels])
    row("Win rate", fmt_pct, *[fmt_pct(m[lbl]["win_rate"]) for lbl in labels])
    row("Breach rate", fmt_pct, *[fmt_pct(m[lbl]["breach_rate"]) for lbl in labels])

    print(f"\n  {'MONTHLY INCOME (1 spread)':}")
    row("Trades / month", fmt_n, *[fmt_n(m[lbl]["trades_per_mo"]) for lbl in labels])
    row(
        "Avg monthly income",
        fmt_usd,
        *[fmt_usd(m[lbl]["avg_monthly"]) for lbl in labels],
    )
    row(
        "Median monthly income",
        fmt_usd,
        *[fmt_usd(m[lbl]["med_monthly"]) for lbl in labels],
    )
    row("Best month", fmt_usd, *[fmt_usd(m[lbl]["best_month"]) for lbl in labels])
    row("Worst month", fmt_usd, *[fmt_usd(m[lbl]["worst_month"]) for lbl in labels])
    row("Monthly std-dev", fmt_usd, *[fmt_usd(m[lbl]["std_monthly"]) for lbl in labels])
    row(
        "Loss months",
        fmt_n,
        *[f"{m[lbl]['loss_months']:>9.0f}/{m[lbl]['n_months']}" for lbl in labels],
    )
    row("Annual income", fmt_usd, *[fmt_usd(m[lbl]["ann_income"]) for lbl in labels])

    # ── Capital scaling ──────────────────────────────────────────────────────
    # Concurrent spreads = how many weekly entries can overlap.
    # For expiry hold (30td / cadence 5) max overlap ≈ 6; for 15td exit ≈ 3; 20td exit ≈ 4.
    # Capital at N spreads = N × max_margin (conservative: size for worst-case simultaneous margin).
    print(f"\n{'=' * 62}")
    print('  CAPITAL SCALING — "To expiry" variant (WINNER as designed)')
    print("  Max overlap ≈ 6 slots (hold 30td / cadence 5td)")
    print(f"{'=' * 62}")
    print(
        f"  {'Spreads':>8}  {'Capital needed':>16}  {'Avg monthly':>12}  {'Annual':>10}  {'Note':}"
    )

    base = m["To expiry"]
    max_m = base["max_margin"]
    avg_mo = base["avg_monthly"]
    for n in [1, 2, 3, 4, 6]:
        capital = max_m * n * 1.2  # 20% buffer over max-margin for the slot count
        note = {
            1: "bare minimum — 1 slot",
            2: "2 slots staggered",
            3: "3 slots staggered",
            4: "4 slots staggered",
            6: "full 6-slot book (WINNER research scale)",
        }[n]
        print(
            f"  {n:>8}  ${capital:>14,.0f}  ${avg_mo * n:>10,.0f}  ${avg_mo * n * 12:>8,.0f}  {note}"
        )

    print(f"\n  Margin per spread (today's SPX): max ${max_m:,.0f}")
    print("  Note: margin scales with SPX level — add 30% buffer vs today's figure")
    print("  Live vrp_z signal (2026-06-18): −1.95 → SKIP (no new entries now)")
    print(f"{'=' * 62}\n")


if __name__ == "__main__":
    main()
