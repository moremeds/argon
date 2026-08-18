"""Is a wide valuation band INSTABILITY, or a one-way re-rating?

The width gate refuses a band whose cheap end and expensive end differ by more
than `MAX_BAND_WIDTH`, and states it as a stability claim — "too unstable to
anchor a price to". That sentence cannot tell two very different shapes apart:

  oscillation   the yield swings both ways inside the window. The name really
                has no settled valuation, and refusing is right.
  re-rating     the yield walks one way and stays there. The window straddles two
                regimes; the old one is not a price anyone can get back to. The
                band is not unstable so much as OBSOLETE at its far end.

Both produce the same hi/lo. Only the second is what a name that re-rated through
the AI cycle looks like, and the refused list is full of them. This measures
which shape each name is, so the gate can be argued with a number.

Discriminator: Spearman rho of the name's own yield against quarter index, over
the same trailing window the band uses. |rho| near 1 is a one-way walk, near 0 is
a series that swings. Reported beside split-half means, because a rank
correlation says "one way" without saying how far.

Reads the warm store and the local lake. No UW, no IB, no network.

Reproduce (MacBook, against the local warm store):

    UW_SCAN_DB_HOST=127.0.0.1 UW_SCAN_DB_USER=chenxi \
    UW_SCAN_DB_NAME=option_wizard_local UW_SCAN_ALLOW_DB_MISMATCH=1 \
    uv run python scripts/research/valuation_band_width_anatomy.py \
        --out docs/research/2026-08-18-valuation-band-refusal
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.fx import METHOD_STATEMENTS, USD_LIKE, load_fx
from uw_scan.fundamentals.valuation import (
    EV_DENOMINATED,
    LEVELS,
    DRIFT_MONOTONE,
    MAX_BAND_WIDTH,
    METHOD_NUMERATOR,
    MIN_HISTORY,
    TYPE_YIELD,
    WINDOW_QUARTERS,
    percentile,
    price_at_yield,
    yield_drift,
)
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.worker.jobs.fundamental_anchors import (
    _history,
    load_raw_closes,
    statement_currencies,
)


def anatomy(conn, settings: Settings) -> list[dict[str, Any]]:
    schema = settings.db_schema
    obs = FundamentalObsRepository(conn, schema=schema)
    types = FundamentalAnchorsRepository(conn, schema=schema).company_types()
    panel = obs.statement_panel(None)
    universe = sorted(t for t in panel if t in types)
    closes = load_raw_closes(settings.lake_credit_etf_root, universe)
    currencies = {
        t: statement_currencies(panel[t], sorted(panel[t]["income-statements"]))
        for t in universe
    }
    fx = {
        c: load_fx(settings.lake_fx_root, c)
        for c in {v for by in currencies.values() for v in by.values() if v not in USD_LIKE}
    }

    out: list[dict[str, Any]] = []
    for ticker in universe:
        per, px = panel[ticker], closes.get(ticker)
        if not px:
            continue
        company_type = types[ticker]
        method = TYPE_YIELD.get(company_type)
        if method is None:
            continue
        periods = sorted(per["income-statements"])
        by_statement = currencies.get(ticker) or {}
        if any(
            by_statement.get(st) not in USD_LIKE and not fx.get(str(by_statement.get(st)))
            for st in METHOD_STATEMENTS[method]
        ):
            continue  # the FX guard refuses these before width is ever reached

        hist, latest, latest_i = _history(
            per, periods, px, method, currencies=by_statement, fx=fx
        )
        if latest_i < 0:
            continue
        window = hist[-WINDOW_QUARTERS:]
        if len(window) < MIN_HISTORY:
            continue

        clean = sorted(window)
        nd = (latest.get("net_debt") or 0.0) if method in EV_DENOMINATED else 0.0
        shares = latest.get("shares")
        fundamental = latest.get(METHOD_NUMERATOR[method])
        if not shares or not fundamental or fundamental <= 0:
            continue
        ends = {
            name: price_at_yield(
                target_yield=percentile(clean, LEVELS[name]),
                fundamental=fundamental,
                net_debt=nd,
                shares=shares,
            )
            for name in ("buy_below", "risk_above")
        }
        lo, hi = ends["buy_below"], ends["risk_above"]
        if lo is None or hi is None or lo <= 0:
            continue

        half = len(window) // 2
        first, second = window[:half], window[-half:]
        out.append(
            {
                "ticker": ticker,
                "company_type": company_type,
                "method": method,
                "width": hi / lo,
                "refused_on_width": hi / lo > MAX_BAND_WIDTH,
                "quarters": len(window),
                "window_last_period": periods[latest_i],
                "rho_yield_vs_time": yield_drift(window),
                "first_half_mean_yield": sum(first) / len(first),
                "second_half_mean_yield": sum(second) / len(second),
                "current_yield": window[-1],
                "current_is_extreme": (
                    "cheapest"
                    if window[-1] >= max(window)
                    else "richest"
                    if window[-1] <= min(window)
                    else None
                ),
            }
        )
    return out


def _monotone(rows: list[dict], cut: float = DRIFT_MONOTONE) -> list[dict]:
    return [r for r in rows if abs(r["rho_yield_vs_time"]) >= cut]


def render(rows: list[dict]) -> str:
    wide = [r for r in rows if r["refused_on_width"]]
    narrow = [r for r in rows if not r["refused_on_width"]]
    lines = [
        "# Wide bands: instability, or a one-way re-rating?",
        "",
        f"{len(rows)} routed names with a usable window; {len(wide)} exceed the "
        f"{MAX_BAND_WIDTH:.0f}x width limit.",
        "",
        "`rho` is `valuation.yield_drift` — the rank correlation of a name's own "
        f"yield against time, over the same trailing window the band is built "
        f"from. |rho| >= {DRIFT_MONOTONE} is a one-way walk; near 0 swings both "
        "ways. **Yield is the inverse of a multiple**, so a falling yield "
        "(negative rho) means the name got more expensive.",
        "",
        f"- monotone (|rho| >= 0.7) among the {len(wide)} refused on width: "
        f"**{len(_monotone(wide))}**",
        f"- monotone among the {len(narrow)} that pass: "
        f"**{len(_monotone(narrow))}**",
        "",
        "## Every name refused on width",
        "",
        "| ticker | method | width | rho | 1st-half yield | 2nd-half yield | "
        "shape | current | last period |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for r in sorted(wide, key=lambda x: x["rho_yield_vs_time"]):
        drift = r["second_half_mean_yield"] - r["first_half_mean_yield"]
        shape = (
            ("re-rated UP" if drift < 0 else "de-rated")
            if abs(r["rho_yield_vs_time"]) >= DRIFT_MONOTONE
            else "swings"
        )
        lines.append(
            f"| {r['ticker']} | {r['method']} | {r['width']:.1f}x | "
            f"{r['rho_yield_vs_time']:+.2f} | {r['first_half_mean_yield']:.4f} | "
            f"{r['second_half_mean_yield']:.4f} | {shape} | "
            f"{r['current_is_extreme'] or 'interior'} | "
            f"{r['window_last_period']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        rows = anatomy(conn, settings)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "width_anatomy.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n"
    )
    report = render(rows)
    (out / "WIDTH_ANATOMY.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
