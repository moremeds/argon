"""Build point-in-time S&P 500 + Nasdaq-100 membership tables from Wikipedia.

Fetches raw wikitext (or reads a cached snapshot), parses the `constituents`
and `changes` wikitables, and writes:
  - sp500_current.csv, ndx100_current.csv  (today's members)
  - index_membership_changes.csv           (long-form add/remove events, dated)
  - raw wikitext snapshots (frozen trace)
  - membership_summary.md

Reproduce:
  uv run python scripts/research/build_index_membership.py --out <dir>
(add --cache-dir <dir> to reuse saved wikitext instead of refetching)
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.request
from pathlib import Path

PAGES = {
    "sp500": "List_of_S%26P_500_companies",
    "ndx100": "Nasdaq-100",
}
RAW_URL = "https://en.wikipedia.org/w/index.php?title={title}&action=raw"


def fetch(title: str) -> str:
    url = RAW_URL.format(title=title)
    req = urllib.request.Request(url, headers={"User-Agent": "argon-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (fixed wikipedia host)
        return resp.read().decode("utf-8")


def _strip_refs(s: str) -> str:
    s = re.sub(r"<ref[^>]*/>", "", s)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.DOTALL)
    return s


def clean_ticker(cell: str) -> str:
    """Extract a bare ticker from wiki cell forms: {{NyseSymbol|MMM}}, [[X]], ADBE."""
    cell = _strip_refs(cell).strip()
    # {{NyseSymbol|MMM}}, {{BZX link|CBOE}}, {{NasdaqSymbol|ADBE}} -> arg after last '|'
    m = re.search(r"\{\{[^{}]*\|([^{}|]+)\}\}", cell)
    if m:
        cell = m.group(1)
    cell = cell.replace("{{", "").replace("}}", "")
    cell = cell.replace("[[", "").replace("]]", "")
    cell = cell.split("|")[-1]  # [[link|display]] -> display
    return cell.strip().upper()


def clean_text(cell: str) -> str:
    cell = _strip_refs(cell)
    cell = re.sub(r"\{\{[^}]*\}\}", "", cell)  # drop templates
    cell = cell.replace("[[", "").replace("]]", "")
    if "|" in cell:  # [[target|display]] -> display
        cell = cell.split("|")[-1]
    return cell.strip()


def extract_table(wikitext: str, table_id: str) -> list[list[str]]:
    """Return each data row of the wikitable with id=table_id as a list of cell strings.

    Handles both single-line (`a || b || c`) and multi-line (`|a\n|b`) cell layouts.
    Header (`!`) lines are skipped.
    """
    # Slice from the table's opening brace to its closing `|}`.
    start = wikitext.find(f'id="{table_id}"')
    if start == -1:
        raise ValueError(f'table id="{table_id}" not found')
    open_brace = wikitext.rfind("{|", 0, start)
    end = wikitext.find("\n|}", start)
    body = wikitext[open_brace:end]

    rows: list[list[str]] = []
    cur: list[str] | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-"):  # new row
            if cur is not None:
                rows.append(cur)
            cur = []
            continue
        if cur is None:  # before first row (the `{|`/header preamble)
            continue
        if stripped.startswith("!"):  # header cell inside a row -> not data
            continue
        if stripped.startswith("|") and not stripped.startswith("|}"):
            payload = stripped[1:]
            # split on '||' but each new '|' line is already its own cell
            for cell in payload.split("||"):
                cur.append(cell.strip())
    if cur:
        rows.append(cur)
    return [r for r in rows if any(c for c in r)]


def parse_sp500_current(wt: str) -> list[dict]:
    out = []
    for r in extract_table(wt, "constituents"):
        if len(r) < 7:
            continue
        out.append(
            {
                "ticker": clean_ticker(r[0]),
                "security": clean_text(r[1]),
                "gics_sector": clean_text(r[2]),
                "gics_sub_industry": clean_text(r[3]),
                "date_added": clean_text(r[5]),
                "cik": clean_text(r[6]),
            }
        )
    return out


def parse_ndx_current(wt: str) -> list[dict]:
    out = []
    for r in extract_table(wt, "constituents"):
        if len(r) < 2:
            continue
        out.append(
            {
                "ticker": clean_ticker(r[0]),
                "company": clean_text(r[1]),
                "icb_industry": clean_text(r[2]) if len(r) > 2 else "",
                "icb_subsector": clean_text(r[3]) if len(r) > 3 else "",
            }
        )
    return out


DATE_RE = re.compile(r"[A-Z][a-z]+ \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}")


def parse_changes(wt: str, index_name: str) -> list[dict]:
    """Changes table: Date | AddTicker | AddSec | RemTicker | RemSec | Reason.

    Emits one long-form row per non-empty add and per non-empty remove.
    """
    events = []
    for r in extract_table(wt, "changes"):
        if len(r) < 5 or not DATE_RE.search(r[0]):
            continue
        date = clean_text(r[0])
        add_t, add_s = clean_ticker(r[1]), clean_text(r[2])
        rem_t, rem_s = clean_ticker(r[3]), clean_text(r[4])
        reason = clean_text(r[5]) if len(r) > 5 else ""
        if add_t:
            events.append(
                {
                    "index": index_name,
                    "date": date,
                    "action": "added",
                    "ticker": add_t,
                    "security": add_s,
                    "reason": reason,
                }
            )
        if rem_t:
            events.append(
                {
                    "index": index_name,
                    "date": date,
                    "action": "removed",
                    "ticker": rem_t,
                    "security": rem_s,
                    "reason": reason,
                }
            )
    return events


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def run(out_dir: Path, cache_dir: Path | None) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = {}
    for key, title in PAGES.items():
        cached = cache_dir / f"{key}.wikitext" if cache_dir else None
        if cached and cached.exists():
            raw[key] = cached.read_text()
        else:
            raw[key] = fetch(title)
        (out_dir / f"{key}.wikitext").write_text(raw[key])  # freeze snapshot

    sp = parse_sp500_current(raw["sp500"])
    ndx = parse_ndx_current(raw["ndx100"])
    changes = parse_changes(raw["sp500"], "sp500") + parse_changes(
        raw["ndx100"], "ndx100"
    )

    write_csv(
        out_dir / "sp500_current.csv",
        sp,
        ["ticker", "security", "gics_sector", "gics_sub_industry", "date_added", "cik"],
    )
    write_csv(
        out_dir / "ndx100_current.csv",
        ndx,
        ["ticker", "company", "icb_industry", "icb_subsector"],
    )
    write_csv(
        out_dir / "index_membership_changes.csv",
        changes,
        ["index", "date", "action", "ticker", "security", "reason"],
    )

    union = sorted({r["ticker"] for r in sp} | {r["ticker"] for r in ndx})
    (out_dir / "universe_union.csv").write_text("ticker\n" + "\n".join(union) + "\n")

    summary = f"""# Index membership — S&P 500 + Nasdaq-100

Source: Wikipedia raw wikitext (frozen snapshots saved alongside).

- S&P 500 current members: {len(sp)}
- Nasdaq-100 current members: {len(ndx)}
- Union (unique tickers): {len(union)}
- Membership change events (long-form add/remove): {len(changes)}
  - S&P 500 events: {sum(1 for c in changes if c["index"] == "sp500")}
  - Nasdaq-100 events: {sum(1 for c in changes if c["index"] == "ndx100")}

Files: sp500_current.csv, ndx100_current.csv, index_membership_changes.csv,
universe_union.csv, sp500.wikitext, ndx100.wikitext
"""
    (out_dir / "membership_summary.md").write_text(summary)
    print(summary)

    # ponytail: one runnable check that fails loudly if parsing regresses
    sp_t = {r["ticker"] for r in sp}
    ndx_t = {r["ticker"] for r in ndx}
    assert 480 <= len(sp) <= 520, f"SP500 count off: {len(sp)}"
    assert 95 <= len(ndx) <= 110, f"NDX count off: {len(ndx)}"
    assert {"AAPL", "MSFT", "MMM"} <= sp_t, "SP500 missing known members"
    assert {"ADBE", "AMD"} <= ndx_t, "NDX missing known members"
    assert any(c["ticker"] == "YHOO" for c in changes), "SP500 changes missing YHOO"
    assert len(changes) > 200, f"too few change events: {len(changes)}"
    print("self-check: OK")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", required=True)
    p.add_argument("--cache-dir", default=None)
    return p.parse_args()


if __name__ == "__main__":
    a = parse_args()
    run(Path(a.out), Path(a.cache_dir) if a.cache_dir else None)
    sys.exit(0)
