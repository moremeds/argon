"""Phase 0 spike — verify UW history availability for the 6-dim matrix backtest.

Runs the questions from docs/research/six-dimension-matrix/09-backtest-plan.md §4 Phase 0:

  * Earliest non-empty date for /api/stock/{T}/greeks (per-strike greeks; date param)
  * Earliest non-empty date for /api/stock/{T}/greek-exposure/strike-expiry (date param)
  * Earliest non-empty date for /api/stock/{T}/spot-exposures/expiry-strike (date param)
  * Coverage window of /api/stock/{T}/historical-risk-reversal-skew (rolling window, no date param)

Per the project rule: this script *does* hit the live UW API and *does* need UW_SCAN_API_KEY.
It is intentionally read-only (no DB writes, no fetcher reuse) so it can be run from a
fresh shell without booting the rest of the stack.

Usage:
    UW_SCAN_API_KEY=... uv run python scripts/uw_history_spike.py

Output is Markdown to stdout — paste into the backtest plan or this script's PR.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

BASE_URL = "https://api.unusualwhales.com"
TICKERS = ["SPY", "QQQ", "IWM", "SPX"]
PROBE_YEARS = [2018, 2019, 2020, 2021, 2022, 2023, 2024]
SKEW_DELTA = 25
HTTP_TIMEOUT = 20.0


@dataclass
class Probe:
    ticker: str
    probe_date: str
    expiry: str
    status: int
    rows: int
    note: str = ""


def third_friday(d: date) -> date:
    first = d.replace(day=1)
    first_friday_offset = (4 - first.weekday()) % 7
    return first + timedelta(days=first_friday_offset + 14)


def probe_endpoint(
    client: httpx.Client,
    ticker: str,
    path: str,
    params: dict,
    probe_date: str,
    expiry: str,
) -> Probe:
    url = f"{BASE_URL}{path.replace('{ticker}', ticker)}"
    try:
        resp = client.get(url, params=params)
    except httpx.HTTPError as exc:
        return Probe(ticker, probe_date, expiry, -1, 0, note=f"transport: {exc}")
    if resp.status_code != 200:
        snippet = resp.text[:120].replace("\n", " ")
        return Probe(ticker, probe_date, expiry, resp.status_code, 0, note=snippet)
    body = resp.json()
    data = body.get("data", body) if isinstance(body, dict) else body
    rows = len(data) if isinstance(data, list) else (1 if data else 0)
    return Probe(ticker, probe_date, expiry, 200, rows)


def section_strike_level(client: httpx.Client, label: str, path: str) -> None:
    print(f"\n## {label} (`{path}`)\n")
    print("| ticker | probe date | expiry | status | rows |")
    print("|---|---|---|---|---|")
    for ticker in TICKERS:
        for year in PROBE_YEARS:
            d = date(
                year, 6, 15
            )  # mid-June: well inside the year, after Jan/Feb holidays
            exp = third_friday(d)
            p = probe_endpoint(
                client,
                ticker,
                path,
                params={"date": d.isoformat(), "expiry": exp.isoformat()},
                probe_date=d.isoformat(),
                expiry=exp.isoformat(),
            )
            note = f" — {p.note}" if p.note else ""
            print(
                f"| {ticker} | {p.probe_date} | {p.expiry} | {p.status} | {p.rows}{note} |"
            )


def section_skew_window(client: httpx.Client) -> None:
    print(
        "\n## Historical 25Δ risk-reversal skew (`/api/stock/{ticker}/historical-risk-reversal-skew`)\n"
    )
    print(
        "This endpoint returns a *rolling window*, not point-in-time — no `date` parameter."
    )
    print(
        "Reports the count of rows + the earliest and latest dates in the returned series.\n"
    )
    print("| ticker | expiry probed | status | rows | earliest | latest |")
    print("|---|---|---|---|---|---|")
    today = date.today()
    expiry = third_friday(today.replace(day=1) + timedelta(days=32))
    for ticker in TICKERS:
        url = f"{BASE_URL}/api/stock/{ticker}/historical-risk-reversal-skew"
        params = {"expiry": expiry.isoformat(), "delta": SKEW_DELTA}
        try:
            resp = client.get(url, params=params)
        except httpx.HTTPError as exc:
            print(f"| {ticker} | {expiry} | -1 | 0 | — | — | transport: {exc}")
            continue
        if resp.status_code != 200:
            snippet = resp.text[:120].replace("\n", " ")
            print(f"| {ticker} | {expiry} | {resp.status_code} | 0 | — | — | {snippet}")
            continue
        body = resp.json()
        rows = body.get("data", []) if isinstance(body, dict) else body
        if not rows:
            print(f"| {ticker} | {expiry} | 200 | 0 | — | — |")
            continue
        dates = [r.get("date") for r in rows if isinstance(r, dict) and r.get("date")]
        earliest = min(dates) if dates else "—"
        latest = max(dates) if dates else "—"
        print(f"| {ticker} | {expiry} | 200 | {len(rows)} | {earliest} | {latest} |")


def main() -> None:
    api_key = os.environ.get("UW_SCAN_API_KEY", "").strip()
    if not api_key:
        sys.exit("UW_SCAN_API_KEY not set. Export it or pass via .env before running.")

    print("# UW history availability spike")
    print()
    print(f"Run date: {date.today().isoformat()}")
    print(f"Tickers: {', '.join(TICKERS)}")
    print(f"Probe years: {', '.join(str(y) for y in PROBE_YEARS)}")
    print()
    print("Interpretation:")
    print(
        "- `rows > 0` at year Y ⇒ UW has per-strike history available for that probe date."
    )
    print(
        "- `status 200` with `rows = 0` ⇒ endpoint accepted the date but returned empty;"
    )
    print("  could be a market holiday or genuine no-history.")
    print("- `status 404 / 422` ⇒ UW does not serve that date.")

    with httpx.Client(
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
    ) as client:
        section_strike_level(client, "Per-strike greeks", "/api/stock/{ticker}/greeks")
        section_strike_level(
            client,
            "Greek exposure (by strike, single expiry)",
            "/api/stock/{ticker}/greek-exposure/strike-expiry",
        )
        section_strike_level(
            client,
            "Spot exposures (by strike, single expiry)",
            "/api/stock/{ticker}/spot-exposures/expiry-strike",
        )
        section_skew_window(client)


if __name__ == "__main__":
    main()
