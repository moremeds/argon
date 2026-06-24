"""Capital ladder — how much do I need, what do I get?

Runs the hold-to-expiry WINNER strategy (SPX bull put spread, ramp+) at
multiple capital sizes and both recommended brp levels (0.20 and 0.32).

Reproduce (mini):
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \\
  UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x \\
  uv run python scripts/research/vrp_capital_ladder.py
"""

from __future__ import annotations

import math
import sys
from statistics import mean

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.vrp_capital_account import (
    CapitalConfig,
    account_metrics,
    simulate_account,
)
from uw_scan.reports.vrp_macro_drawdown import load_index_vol
from uw_scan.reports.vrp_macro_signal import WINNER
from uw_scan.storage.repository import Repository

# Capital levels to test
CAPITALS = [60_000, 100_000, 143_000, 200_000, 300_000, 400_000, 600_000]
BRPS = [0.20, 0.32]

# Today's live margin from the UI screenshot: 1 SPX spread = $17,500
CURRENT_MARGIN = 17_500


def contracts_at_entry(capital: float, brp: float, margin: float) -> int:
    return math.floor(brp * capital / margin)


def main() -> None:
    settings = Settings.from_env()
    try:
        conn = psycopg.connect(settings.db_dsn())
    except Exception as e:
        print(f"DB connect failed: {e}", file=sys.stderr)
        sys.exit(1)

    repo = Repository(conn, schema=settings.db_schema)
    rf = settings.vrp_risk_free_rate
    loaded = load_index_vol(repo, "SPX")
    conn.close()

    # Run all combinations
    results: dict[tuple, dict] = {}
    for brp in BRPS:
        for capital in CAPITALS:
            cfg = CapitalConfig(
                capital=capital,
                base_risk_pct=brp,
                overlay_mult=0.0,
                rich_threshold=99.0,
                names=("SPX",),
                min_date=None,
            )
            m = account_metrics(
                simulate_account({"SPX": loaded}, settings, cfg), cfg, rf
            )
            results[(brp, capital)] = m

    # ── Header ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print(f"  VRP CAPITAL LADDER — SPX BULL PUT SPREAD · HOLD TO EXPIRY · RAMP+ GATE")
    print(f"  Strategy: sell 0.25Δ put + buy 0.125Δ wing · ~45 cal DTE entry · weekly")
    print(f"  Data: SPX+VIX 2006-2026 (19 yr, 2008 included)")
    print(f"  Live margin (today, SPX ~7,100): ${CURRENT_MARGIN:,} per spread")
    print(f"{'=' * 78}")

    for brp in BRPS:
        tag = "† fragile/IS" if brp == 0.32 else "★ recommended"
        print(f"\n{'─' * 78}")
        print(f"  BASE_RISK_PCT = {brp:.2f}  ({tag})")
        print(
            f"  Each entry risks {brp * 100:.0f}% of capital; contracts = floor({brp * 100:.0f}% × capital ÷ margin)"
        )
        print(f"{'─' * 78}")
        print(
            f"  {'Capital':>10}  {'Contracts':>10}  {'Avg monthly':>12}  {'Annual':>10}  "
            f"{'CAGR':>7}  {'Sharpe':>7}  {'MaxDD':>8}  {'Skip%':>6}  {'Win%':>5}"
        )
        print(
            f"  {'':>10}  {'@ today':>10}  {'income':>12}  {'income':>10}  "
            f"{'gross':>7}  {'':>7}  {'':>8}  {'':>6}  {'':>5}"
        )
        print(f"  {'─' * 75}")

        for capital in CAPITALS:
            m = results[(brp, capital)]
            contracts_now = contracts_at_entry(capital, brp, CURRENT_MARGIN)
            avg_monthly = (
                m.get("ann_return_gross", 0) * capital / 12
            )  # ann gross × capital / 12
            annual = avg_monthly * 12
            cagr = m.get("cagr_gross", 0) * 100
            sharpe = m.get("sharpe", 0)
            maxdd = m.get("maxdd_pct", 0) * 100
            skip = m.get("skip_rate", 0) * 100
            win = m.get("win_rate", 0) * 100

            # flag rows where capital is too thin to trade at today's margin
            flag = "  ← CAN'T TRADE TODAY" if contracts_now == 0 else ""
            flag = "  ← 1 spread" if contracts_now == 1 else flag
            print(
                f"  ${capital:>9,}  {contracts_now:>10}  ${avg_monthly:>10,.0f}  ${annual:>8,.0f}  "
                f"{cagr:>6.1f}%  {sharpe:>7.2f}  {maxdd:>7.1f}%  {skip:>5.1f}%  {win:>4.0f}%"
                f"{flag}"
            )

    # ── Honest risk section ──────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print(f"  RISK ANCHORS (from 2006-2026 history)")
    print(f"{'─' * 78}")
    print(f"  Worst drawdown     : −50% of capital  (2009 GFC, brp 0.20)")
    print(f"                       −79% of capital  (2009 GFC, brp 0.32)")
    print(
        f"  Worst single month : see monthly std-dev — can lose 2–4 months in 1 event"
    )
    print(f"  Rule: size your account to SURVIVE −50% before sizing for income")
    print(
        f"        → minimum safe capital for brp 0.20: $100k (−50% = −$50k; still solvent)"
    )
    print(
        f"        → minimum safe capital for brp 0.32: $143k (can afford 1 spread always)"
    )

    # ── Contracts-now table ──────────────────────────────────────────────────
    print(f"\n{'=' * 78}")
    print(
        f"  TODAY'S SPREAD (live margin ${CURRENT_MARGIN:,}) — contracts you can open right now"
    )
    print(f"{'─' * 78}")
    print(f"  {'Capital':>10}   {'brp 0.20':>10}   {'brp 0.32':>10}")
    print(f"  {'─' * 40}")
    for capital in CAPITALS:
        c20 = contracts_at_entry(capital, 0.20, CURRENT_MARGIN)
        c32 = contracts_at_entry(capital, 0.32, CURRENT_MARGIN)
        print(f"  ${capital:>9,}   {c20:>10}   {c32:>10}")

    print(f"\n  Max slots open simultaneously: 6  (hold 30td ÷ cadence 5td)")
    print(f"  But gate fires ~36% of weeks → avg 2-3 open at once in rich-vol")
    print(
        f"  Capital to fund ALL 6 slots at today's margin: 6 × ${CURRENT_MARGIN:,} = ${6 * CURRENT_MARGIN:,}"
    )
    print(f"{'=' * 78}\n")


if __name__ == "__main__":
    main()
