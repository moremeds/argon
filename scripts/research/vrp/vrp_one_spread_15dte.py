"""1-spread · 15-DTE-exit analysis.

Replays WINNER entries on SPX but exits mid-hold at T+15 trading days (instead
of hold-to-expiry at T+30). One contract always. Reports:
  - per-trade: margin, entry credit, captured premium at T+15 exit
  - monthly: total premium captured, trades opened
  - summary: avg margin per spread, avg monthly income, win rate

Entry logic is IDENTICAL to WINNER (ramp+ vrp-z gate, weekly cadence, 0.25Δ / 0.125Δ
bull put spread, 30-trading-day T at entry). Exit logic: close at pi+15 using
BS repricing with the prevailing VIX at that date.

Reproduce (mini, freshest data):
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_one_spread_15dte.py

Reproduce (local):
  UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_NAME=option_wizard_local \
  UW_SCAN_DB_USER=$USER UW_SCAN_API_KEY=x \
  uv run python scripts/research/vrp_one_spread_15dte.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from statistics import mean, pstdev

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER, _cost_model, size_weight
from uw_scan.reports.vrp_structure import build_bull_put_spread
from uw_scan.storage.repository import Repository

# Strategy: enter at ~30 trading days (~45 cal DTE), exit at 15 remaining.
# EXIT_AFTER_TRADING = 15 → 15 trading days remain at exit (~21 cal DTE)
# EXIT_AFTER_TRADING = 20 → 10 trading days remain at exit (~15 cal DTE)
EXIT_AFTER = 20  # trading days after entry → exit; change to 20 for 15 cal DTE exit
ENTRY_HOLD = WINNER.hold_days  # 30 — sets entry T and expiry position
CONTRACTS = 1  # always 1 spread


def run(repo: Repository, settings: Settings) -> None:
    cost = _cost_model(settings)
    loaded = load_index_vol(repo, "SPX")
    adj = loaded.adj  # list[(date, spot)]
    iv_map = {row["market_date"]: row["iv"] for row in loaded.rows}
    vrpz_map = {row["market_date"]: row.get("vrp_z_20") for row in loaded.rows}

    t_entry_years = ENTRY_HOLD / 252.0  # T at entry (~30/252)
    t_exit_years = (ENTRY_HOLD - EXIT_AFTER) / 252.0  # T remaining at exit (15/252)
    r_annual = settings.vrp_risk_free_rate

    entries: list[dict] = []
    last_entry_k = -WINNER.cadence  # enforce weekly cadence (5-bar gap)

    for row in sorted(loaded.rows, key=lambda x: x["market_date"]):
        d = row["market_date"]
        pi = loaded.pidx.get(d)
        if pi is None:
            continue
        # need EXIT_AFTER bars ahead for exit pricing and ENTRY_HOLD bars for expiry
        if pi + ENTRY_HOLD >= len(adj):
            break

        # cadence gate: at least WINNER.cadence bars since last entry
        if pi - last_entry_k < WINNER.cadence:
            continue

        # vrp-z gate (ramp+)
        z = vrpz_map.get(d)
        w = size_weight(z, WINNER)
        if w <= 0:
            continue

        iv = iv_map.get(d)
        if not iv or iv <= 0:
            continue
        _, S_entry = adj[pi]

        # build spread at entry (same as WINNER)
        spread = build_bull_put_spread(
            S_entry,
            iv,
            t_entry_years,
            r_annual,
            short_delta=WINNER.short_delta,
            wing_delta=WINNER.wing_delta,
        )

        credit_usd = spread.credit * cost.multiplier * CONTRACTS
        margin_usd = spread.max_loss * cost.multiplier * CONTRACTS

        # exit at pi + EXIT_AFTER with BS mid-price
        exit_k = pi + EXIT_AFTER
        if exit_k >= len(adj):
            break
        d_exit, S_exit = adj[exit_k]
        iv_exit = iv_map.get(d_exit)
        if not iv_exit or iv_exit <= 0:
            # no IV at exit date — skip (rare)
            continue

        close_val = spread.value(S_exit, t_exit_years, r_annual, iv_exit)
        captured_usd = (spread.credit - close_val) * cost.multiplier * CONTRACTS

        # breach check: was short strike hit at any point before exit?
        breached = any(adj[k][1] <= spread.short_put for k in range(pi + 1, exit_k + 1))

        entries.append(
            {
                "entry_date": d,
                "exit_date": d_exit,
                "spot": S_entry,
                "iv": iv,
                "z": z,
                "w": w,
                "short_strike": spread.short_put,
                "long_strike": spread.long_put,
                "width": spread.put_width,
                "credit_usd": credit_usd,
                "margin_usd": margin_usd,
                "captured_usd": captured_usd,
                "breached": breached,
            }
        )
        last_entry_k = pi

    if not entries:
        print("No entries found — check DB connectivity / min_date")
        return

    # ── Monthly aggregation ──────────────────────────────────────────────────
    monthly: dict[tuple[int, int], list[float]] = defaultdict(list)
    for e in entries:
        ym = (e["entry_date"].year, e["entry_date"].month)
        monthly[ym].append(e["captured_usd"])

    monthly_totals = [sum(v) for v in monthly.values()]
    credits = [e["credit_usd"] for e in entries]
    captures = [e["captured_usd"] for e in entries]
    margins = [e["margin_usd"] for e in entries]
    wins = sum(1 for c in captures if c > 0)

    print(f"\n{'=' * 62}")
    print("  VRP 1-SPREAD · 15-DTE EXIT — SPX BULL PUT SPREAD")
    print(f"  {entries[0]['entry_date']} → {entries[-1]['entry_date']}")
    print(f"{'=' * 62}")

    print("\n── CAPITAL / MARGIN ─────────────────────────────────────────")
    print(f"  Margin per spread (avg)  : ${mean(margins):>9,.0f}")
    print(
        f"  Margin per spread (max)  : ${max(margins):>9,.0f}   ← size your account to this"
    )
    print(f"  Margin per spread (min)  : ${min(margins):>9,.0f}   ← cheap-market low")
    print("  (margin = max_loss × 100; scales with SPX level)")

    print("\n── PER-TRADE PREMIUM ────────────────────────────────────────")
    print(
        f"  Avg entry credit         : ${mean(credits):>9,.0f}   (full hold-to-expiry value)"
    )
    print(
        f"  Avg captured @ T+{EXIT_AFTER:<2}     : ${mean(captures):>9,.0f}   ← what you actually collect"
    )
    print(
        f"  Capture ratio            : {mean(captures) / mean(credits) * 100:>8.1f}%   of entry credit"
    )
    print(
        f"  Win rate                 : {wins / len(entries) * 100:>8.1f}%   (captured > $0)"
    )
    print(
        f"  Trades in breach at exit : {sum(1 for e in entries if e['breached']):<4}  / {len(entries)}"
    )

    print("\n── MONTHLY INCOME (1 spread at a time) ─────────────────────")
    print(f"  Avg trades / month       : {len(entries) / len(monthly):>8.1f}")
    print(f"  Avg monthly income       : ${mean(monthly_totals):>9,.0f}")
    print(
        f"  Median monthly income    : ${sorted(monthly_totals)[len(monthly_totals) // 2]:>9,.0f}"
    )
    print(f"  Best month               : ${max(monthly_totals):>9,.0f}")
    print(f"  Worst month              : ${min(monthly_totals):>9,.0f}")
    print(f"  Monthly std-dev          : ${pstdev(monthly_totals):>9,.0f}")
    print(
        f"  Months with loss         : {sum(1 for m in monthly_totals if m < 0):<4}  / {len(monthly_totals)}"
    )

    print("\n── ANNUALISED ────────────────────────────────────────────────")
    avg_margin = mean(margins)
    ann_income = mean(monthly_totals) * 12
    print(f"  Annual income (avg)      : ${ann_income:>9,.0f}")
    print(
        f"  Return on avg margin     : {ann_income / avg_margin * 100:>8.1f}%   per year"
    )

    print("\n── LAST 10 TRADES ────────────────────────────────────────────")
    print(
        f"  {'Entry':>10}  {'Exit':>10}  {'SPX':>7}  {'VIX':>5}  "
        f"{'z':>5}  {'Credit':>7}  {'Captured':>8}  {'Breach':>6}"
    )
    for e in entries[-10:]:
        print(
            f"  {str(e['entry_date']):>10}  {str(e['exit_date']):>10}  "
            f"{e['spot']:>7,.0f}  {e['iv'] * 100:>5.1f}  "
            f"{(e['z'] or 0):>5.2f}  ${e['credit_usd']:>6,.0f}  "
            f"${e['captured_usd']:>7,.0f}  {'YES' if e['breached'] else 'no':>6}"
        )

    print(f"\n  Total trades: {len(entries)}   Total months: {len(monthly)}")
    print(f"{'=' * 62}\n")


def main() -> None:
    settings = Settings.from_env()
    try:
        conn = psycopg.connect(settings.db_dsn())
    except Exception as e:
        print(f"DB connect failed: {e}", file=sys.stderr)
        sys.exit(1)
    repo = Repository(conn, schema=settings.db_schema)
    try:
        run(repo, settings)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
