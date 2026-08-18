"""Survey the valuation-anchor band across a whole watchlist, from a live API.

Answers one question: for every name the desk actually watches, does the
Fundamentals card render a price band, and when it does not, WHY not. The
refusal reasons are the payload — `confidence_reasons` is the only place the
band's gates surface, and nothing aggregates them.

Reads only. No DB, no UW/IB spend: `/api/stock/{t}/fundamentals` is served from
the warm store.

Reproduce:

    uv run python scripts/research/valuation_band_survey.py \
        --base https://<host> \
        --out docs/research/2026-08-18-valuation-band-refusal

Writes `survey.json` (every ticker, full anchor payload) and `SURVEY.md` (the
tally) into --out. stdout is a summary, not the artifact.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

LEVELS = ("buy_below", "observe_low", "observe_mid", "observe_high", "risk_above")

#: Refusal messages interpolate the offending magnitude, so they never group as
#: literals. Collapse each to its gate before tallying.
_FAMILIES: tuple[tuple[str, str], ...] = (
    (r"range spans", "band too wide"),
    (r"numerator is not positive", "numerator not positive"),
    (r"shares outstanding", "no shares outstanding"),
    (r"quarters? of", "history too short"),
    (r"no .*(price|spot)", "no spot"),
)


def _family(reason: str) -> str:
    for pattern, label in _FAMILIES:
        if re.search(pattern, reason):
            return label
    return reason


def _is_company(card: dict) -> bool:
    """Fund or operating company, from the two fields the watchlist carries.

    `aum` is the reliable half. `sector` catches the funds the desk tags by
    theme rather than by wrapper — but only the explicit `Sector-ETF` tag, since
    a thematic tag is not evidence either way. A few thematic tickers therefore
    still count as companies here; they are named in the report so a reader can
    check rather than trust the classification.
    """
    return card.get("aum") is None and card.get("sector") != "Sector-ETF"


def _get(url: str, timeout: float, *, attempts: int = 3) -> Any:
    """A transport failure is one row, not a stop — but it must not be mistaken
    for an answer. The tunnel in front of prod drops connections under
    concurrency, and a dropped connection and a real 404 mean opposite things
    here, so only the HTTP status is taken as final."""
    last: dict[str, Any] = {}
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            return {"_http_error": exc.code}
        except Exception as exc:  # noqa: BLE001
            last = {"_error": repr(exc)}
            time.sleep(1.5 * (attempt + 1))
    return last


def survey(
    base: str,
    tickers: list[str],
    *,
    workers: int,
    timeout: float,
    meta: dict[str, dict] | None = None,
) -> list[dict]:
    meta = meta or {}

    def one(ticker: str) -> dict:
        doc = _get(f"{base}/api/stock/{ticker}/fundamentals", timeout)
        anchors = (doc or {}).get("anchors") or {}
        # A 404 on the card means "no score row". That has two very different
        # causes — no statements ingested at all, or statements present and
        # scoring behind — and only the statements endpoint separates them.
        has_statements = None
        if doc.get("_http_error") == 404:
            st = _get(f"{base}/api/stock/{ticker}/fundamentals/statements", timeout)
            has_statements = st.get("_http_error") != 404 and "_error" not in st
        return {
            "ticker": ticker,
            "error": doc.get("_error") or doc.get("_http_error"),
            "has_statements": has_statements,
            "is_company": _is_company(meta.get(ticker, {})),
            "sector": meta.get(ticker, {}).get("sector"),
            "company_type": anchors.get("company_type"),
            "method": anchors.get("method"),
            "levels_present": sum(anchors.get(k) is not None for k in LEVELS),
            "confidence": anchors.get("confidence"),
            "history_quarters": anchors.get("history_quarters"),
            "spot": anchors.get("spot"),
            "spot_percentile": anchors.get("spot_percentile"),
            "as_of": anchors.get("as_of"),
            "reasons": anchors.get("confidence_reasons") or [],
            "has_anchors_block": bool(anchors),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return sorted(pool.map(one, tickers), key=lambda r: r["ticker"])


def render(rows: list[dict], base: str) -> str:
    banded = [r for r in rows if r["levels_present"] == len(LEVELS)]
    refused = [r for r in rows if r["has_anchors_block"] and not r["levels_present"]]
    absent = [r for r in rows if not r["has_anchors_block"] and not r["error"]]
    errors = [r for r in rows if r["error"]]
    # A fund files no statements, so its absence is correct and must not share a
    # denominator with an operating company's.
    funds = [r for r in errors if not r["is_company"]]
    unscored = [r for r in errors if r["is_company"]]
    no_statements = [r for r in unscored if r["has_statements"] is False]
    scoring_behind = [r for r in unscored if r["has_statements"] is True]
    companies = len(rows) - len(funds)

    fams = Counter(_family(x) for r in refused for x in r["reasons"])
    by_method = Counter(r["method"] for r in refused)
    conf = Counter(r["confidence"] for r in banded)

    out = [
        "# Valuation-band survey — full watchlist",
        "",
        f"Source: `{base}` · {len(rows)} watchlist tickers, of which {companies} "
        f"are operating companies ({len(funds)} funds/ETFs file no statements and "
        "are excluded from every ratio below).",
        "",
        f"- banded (5/5 levels): **{len(banded)}** "
        f"({len(banded) / max(1, companies):.0%} of operating companies)",
        f"- scored, band refused: **{len(refused)}** "
        f"({len(refused) / max(1, len(banded) + len(refused)):.0%} of scored names)",
        f"- no score row, no statements ingested: **{len(no_statements)}**",
        f"- no score row, statements present: **{len(scoring_behind)}**",
        f"- anchors block missing from a scored card: **{len(absent)}**",
        "",
        "## Refusal reasons",
        "",
        "| gate | names |",
        "| --- | ---: |",
    ]
    out += [f"| {k} | {v} |" for k, v in fams.most_common()]
    out += [
        "",
        "## Refusals by method",
        "",
        "| method | names |",
        "| --- | ---: |",
    ]
    out += [f"| {k} | {v} |" for k, v in by_method.most_common()]
    out += [
        "",
        "## Confidence among banded names",
        "",
        "| confidence | names |",
        "| --- | ---: |",
    ]
    out += [f"| {k} | {v} |" for k, v in conf.most_common()]
    out += [
        "",
        "## Every refusal",
        "",
        "| ticker | method | hq | reason |",
        "| --- | --- | ---: | --- |",
    ]
    out += [
        f"| {r['ticker']} | {r['method']} | {r['history_quarters']} | "
        f"{'; '.join(r['reasons'])} |"
        for r in refused
    ]
    if absent:
        out += ["", "## No anchors block", "", ", ".join(r["ticker"] for r in absent)]
    if no_statements:
        out += [
            "",
            "## Operating companies with no statements ingested",
            "",
            ", ".join(r["ticker"] for r in no_statements),
        ]
    if scoring_behind:
        out += [
            "",
            "## Statements ingested, still no score",
            "",
            ", ".join(r["ticker"] for r in scoring_behind),
        ]
    if funds:
        out += [
            "",
            "## Funds / ETFs (correctly absent)",
            "",
            ", ".join(r["ticker"] for r in funds),
        ]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="API origin, e.g. http://127.0.0.1:8400")
    ap.add_argument("--out", required=True, help="directory for survey.json + SURVEY.md")
    ap.add_argument("--tickers", default="", help="comma list; default = live watchlist")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument(
        "--render-only",
        action="store_true",
        help="re-render SURVEY.md from an existing survey.json, no requests",
    )
    ap.add_argument("--timeout", type=float, default=60.0)
    args = ap.parse_args()

    base = args.base.rstrip("/")
    out = Path(args.out)
    if args.render_only:
        saved = json.loads((out / "survey.json").read_text())
        (out / "SURVEY.md").write_text(render(saved["rows"], saved["base"]))
        print((out / "SURVEY.md").read_text())
        return

    meta: dict[str, dict] = {}
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        doc = _get(f"{base}/api/watchlist", args.timeout)
        tickers = [t["ticker"] for t in doc["tickers"]]
        meta = {t["ticker"]: t for t in doc["tickers"]}

    rows = survey(
        base, tickers, workers=args.workers, timeout=args.timeout, meta=meta
    )

    out.mkdir(parents=True, exist_ok=True)
    (out / "survey.json").write_text(
        json.dumps({"base": base, "rows": rows}, indent=2, sort_keys=True) + "\n"
    )
    report = render(rows, base)
    (out / "SURVEY.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()
