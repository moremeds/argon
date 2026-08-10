#!/usr/bin/env python
"""P1a data-contract spike — measure massive coverage for the fundamental core 25.

Spec: docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md (§3.2, P1a).

Three readings of these endpoints were wrong before this script existed, each a
measurement-protocol error that returned a clean-looking integer:

1. `/v2` takes the ticker in the URL PATH, `/vX` takes it as a query param.
   Querying `/v2` in `/vX` form returns 404 — which a row-count probe reads as
   "no coverage".
2. An unfiltered `/v2` count mixes annual/quarterly/trailing rows. The pipeline
   is quarterly, so only `type=Q` counts are comparable.
3. Probe limits must be identical across tickers or the numbers are not
   comparable at all.

So this script records, per ticker: the HTTP status (an error is never a zero),
the quarterly count separately from the unfiltered count, and the observed XBRL
units — because a value without its unit cannot be valued.

Reproduce:

    MASSIVE_API_KEY=... uv run python scripts/research/fundamental_source_coverage.py

Writes `coverage.json` + `README.md` under
`docs/research/2026-08-10-fundamental-source-coverage/`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

# Core 25 from spec §4.3. Not read from watchlist_taxonomy: that module carries
# chain MEMBERSHIP, and this cohort is a spec-defined analysis universe. If the
# two drift, the spec is authoritative.
CORE_25 = [
    # L1 Chip & System
    "NVDA",
    "AMD",
    "AVGO",
    "MRVL",
    "TSM",
    "ASML",
    "AMAT",
    "MU",
    # L2 Cloud & Data
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "ORCL",
    # L3 Datacenter Infra
    "ANET",
    "VRT",
    "ETN",
    "GEV",
    "CEG",
    "VST",
    # L4/L5 App & Model
    "DELL",
    "SMCI",
    "PLTR",
    "CRWD",
    "NOW",
    "APP",
]

# Constant per endpoint and across every ticker — see docstring (3). They differ
# because the endpoints do: /vX rejects limit>100 with HTTP 400, /v2 accepts 1000.
# A shared 1000 silently 400s /vX for all 25 names, which reads as "no current
# coverage anywhere" if the status is not checked.
VX_LIMIT = 100
V2_LIMIT = 1000
OUT_DIR = Path("docs/research/2026-08-10-fundamental-source-coverage")


def _span(values: list[str]) -> tuple[str | None, str | None]:
    ok = sorted(v for v in values if v)
    return (ok[0], ok[-1]) if ok else (None, None)


def probe_vx(client: httpx.Client, ticker: str) -> dict[str, Any]:
    """Current-data endpoint. Ticker is a QUERY PARAM here."""
    resp = client.get(
        "/vX/reference/financials",
        params={"ticker": ticker, "timeframe": "quarterly", "limit": VX_LIMIT},
    )
    out: dict[str, Any] = {"http_status": resp.status_code}
    if resp.status_code != 200:
        out["error"] = resp.text[:200]
        return out
    rows = resp.json().get("results") or []
    first, last = _span([r.get("end_date", "") for r in rows])
    units: set[str] = set()
    for r in rows[:5]:  # units are stable per filer; 5 rows is plenty
        for section in (r.get("financials") or {}).values():
            for leaf in (section or {}).values():
                if isinstance(leaf, dict) and leaf.get("unit"):
                    units.add(str(leaf["unit"]))
    out.update(
        quarterly_rows=len(rows),
        first_period=first,
        last_period=last,
        units=sorted(units),
        cik=rows[0].get("cik") if rows else None,
    )
    return out


def probe_v2(client: httpx.Client, ticker: str) -> dict[str, Any]:
    """Frozen history endpoint. Ticker is a PATH SEGMENT here."""
    out: dict[str, Any] = {}
    for label, params in (
        ("quarterly", {"limit": V2_LIMIT, "type": "Q"}),
        ("all_types", {"limit": V2_LIMIT}),
    ):
        resp = client.get(f"/v2/reference/financials/{ticker}", params=params)
        if resp.status_code != 200:
            out[f"{label}_http_status"] = resp.status_code
            out[f"{label}_rows"] = None  # explicitly NOT zero
            continue
        rows = resp.json().get("results") or []
        out[f"{label}_http_status"] = 200
        out[f"{label}_rows"] = len(rows)
        if label == "quarterly" and rows:
            first, last = _span([r.get("reportPeriod", "") for r in rows])
            out["first_period"] = first
            out["last_period"] = last
            # USD-normalised variants + the FX rate answer the currency contract
            # for the historical window (spec F-2).
            sample = rows[0]
            out["has_usd_variants"] = any(k.endswith("USD") for k in sample)
            out["fx_rate_present"] = "foreignCurrencyUSDExchangeRate" in sample
            out["fx_rate_sample"] = sample.get("foreignCurrencyUSDExchangeRate")
    return out


def classify(vx: dict[str, Any], v2: dict[str, Any]) -> str:
    """What the quarterly pipeline can actually consume."""
    if vx.get("quarterly_rows"):
        return "covered"
    if v2.get("quarterly_rows"):
        return "history_only"  # needs a current-data fallback
    if v2.get("all_types_rows"):
        return "annual_only"  # unusable by a quarterly pipeline
    return "absent"


def main() -> int:
    key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if not key:
        print("MASSIVE_API_KEY is not set", file=sys.stderr)
        return 2

    results: dict[str, Any] = {}
    with httpx.Client(
        base_url="https://api.massive.com",
        headers={"Authorization": f"Bearer {key}"},
        timeout=60.0,
    ) as client:
        for ticker in CORE_25:
            vx = probe_vx(client, ticker)
            v2 = probe_v2(client, ticker)
            results[ticker] = {"vX": vx, "v2": v2, "state": classify(vx, v2)}
            print(
                f"{ticker:<6} {results[ticker]['state']:<13} "
                f"vX_q={vx.get('quarterly_rows')} "
                f"v2_q={v2.get('quarterly_rows')} "
                f"v2_all={v2.get('all_types_rows')} "
                f"units={','.join(vx.get('units') or []) or '-'}",
                flush=True,
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "probed_at": "2026-08-10",
        "vx_limit": VX_LIMIT,
        "v2_limit": V2_LIMIT,
        "reproduce": (
            "MASSIVE_API_KEY=... uv run python "
            "scripts/research/fundamental_source_coverage.py"
        ),
        "tickers": results,
    }
    (OUT_DIR / "coverage.json").write_text(json.dumps(payload, indent=2) + "\n")
    (OUT_DIR / "README.md").write_text(_render_markdown(results))
    print(f"\nwrote {OUT_DIR}/coverage.json and README.md")
    return 0


def _render_markdown(results: dict[str, Any]) -> str:
    by_state: dict[str, list[str]] = {}
    for t, r in results.items():
        by_state.setdefault(r["state"], []).append(t)

    lines = [
        "# Fundamental source coverage — massive, core 25",
        "",
        "*Probed 2026-08-10 · P1a data-contract spike ·"
        " spec `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`*",
        "",
        "Reproduce:",
        "",
        "```bash",
        "MASSIVE_API_KEY=... uv run python"
        " scripts/research/fundamental_source_coverage.py",
        "```",
        "",
        "Every count below is a **quarterly** count taken at a constant per-endpoint"
        " limit (`/vX` 100 — it 400s above that; `/v2` 1000), and an HTTP error is recorded as `null` rather than `0` —"
        " three earlier readings of these endpoints were wrong for exactly those"
        " two reasons.",
        "",
        "## Summary",
        "",
        "| State | Meaning | Tickers |",
        "|---|---|---|",
    ]
    meaning = {
        "covered": "current `/vX` quarterly data",
        "history_only": "no current data; `/v2` quarterly history exists",
        "annual_only": "**unusable** — only annual/trailing rows",
        "absent": "no rows from either endpoint",
    }
    for state in ("covered", "history_only", "annual_only", "absent"):
        if state in by_state:
            lines.append(
                f"| `{state}` | {meaning[state]} | "
                f"{', '.join(sorted(by_state[state]))} |"
            )

    lines += [
        "",
        "## Per ticker",
        "",
        "| Ticker | State | `/vX` Q | `/vX` span | units | `/v2` Q | `/v2` span"
        " | `/v2` all | USD variants | FX rate |",
        "|---|---|---:|---|---|---:|---|---:|---|---|",
    ]
    for t in CORE_25:
        r = results[t]
        vx, v2 = r["vX"], r["v2"]
        vx_span = (
            f"{vx.get('first_period')} → {vx.get('last_period')}"
            if vx.get("quarterly_rows")
            else "—"
        )
        v2_span = (
            f"{v2.get('first_period')} → {v2.get('last_period')}"
            if v2.get("quarterly_rows")
            else "—"
        )
        lines.append(
            f"| {t} | `{r['state']}` | {vx.get('quarterly_rows')} | {vx_span} | "
            f"{','.join(vx.get('units') or []) or '—'} | {v2.get('quarterly_rows')} |"
            f" {v2_span} | {v2.get('all_types_rows')} | "
            f"{'yes' if v2.get('has_usd_variants') else '—'} | "
            f"{'yes' if v2.get('fx_rate_present') else '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
