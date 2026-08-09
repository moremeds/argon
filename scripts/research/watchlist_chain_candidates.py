"""Screen watchlist-extension candidates for the 5-layer / 25-chain taxonomy.

The 五层蛋糕 taxonomy below is the single source of truth: this script emits the
CSV that the review doc is built from, so the two cannot drift.

Every candidate is verified against UW `/api/screener/stocks` — a ticker that
comes back with no row is delisted/acquired/uncovered and is marked UNVERIFIED
rather than silently recommended.

Reproduce (regenerates every artifact in the directory; needs UW_SCAN_API_KEY.
`UW_SCAN_ALLOW_DB_MISMATCH=1` is required because this is a one-off script, not
a stack process, so it trips `config._enforce_db_isolation`):

    UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python \
        scripts/research/watchlist_chain_candidates.py \
        --have  docs/research/2026-08-09-watchlist-industry-chains/current_watchlist.csv \
        --out   docs/research/2026-08-09-watchlist-industry-chains/candidates.csv \
        --doc   docs/research/2026-08-09-watchlist-industry-chains/SELECT.md \
        --final docs/research/2026-08-09-watchlist-industry-chains/FINAL.md \
        --hot   docs/research/2026-08-09-watchlist-industry-chains/hot.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from uw_scan.api.client import UwClient
from uw_scan.api.endpoints import EndpointSlug
from uw_scan.config import Settings
from uw_scan.watchlist_taxonomy import AI, LAYERS

# TAXONOMY moved to uw_scan.watchlist_taxonomy when the chain join table needed
# it — app code must not import from scripts/. Rebuilt here in this script's
# legacy (id, name, chains) shape so the renderers below stay untouched. One
# definition, three consumers: this screener, the membership seeder, the API.
TAXONOMY: dict[str, tuple[str, str, dict[str, list[str]]]] = {
    layer.key: (layer.name, layer.name, {c: list(t) for c, t in layer.chains.items()})
    for layer in LAYERS
    if layer.focus == AI
}

# The watchlist covers four focus areas. The 5-layer model is the shape of ONE
# of them (the AI industrial chain) — not the whole watchlist, and the other
# three are not leftovers.
OTHER_FOCUS: dict[str, tuple[str, list[str]]] = {
    layer.name: (layer.name, list(layer.chains))
    for layer in LAYERS
    if layer.focus != AI
}

FIELDS = (
    "full_name",
    "sector",
    "marketcap",
    "total_open_interest",
    "avg_30_day_call_volume",
    "avg_30_day_put_volume",
    "avg30_volume",
    "close",
)
BATCH = 40


def screen(client: UwClient, tickers: list[str]) -> dict[str, dict]:
    """Return {ticker: {field: value}} for every ticker UW has a screener row for."""
    out: dict[str, dict] = {}
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i : i + BATCH]
        resp, _ = client.get(
            EndpointSlug.BULK_SCREENER_STOCKS,
            params={"ticker": ",".join(batch), "limit": len(batch) + 10},
        )
        for row in json.loads(resp.text).get("data", []):
            out[row["ticker"]] = {f: row.get(f) for f in FIELDS}
        print(f"  screened {len(batch)} -> {len(out)} rows so far")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--have",
        type=Path,
        required=True,
        help="CSV of current watchlist (ticker,sector)",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--doc", type=Path, help="also render the tick-box selection doc")
    ap.add_argument(
        "--final", type=Path, help="render the post-selection final structure"
    )
    ap.add_argument(
        "--hot", type=Path, help="market-wide option-hot sweep, taxonomy-blind"
    )
    ap.add_argument(
        "--min-mcap", type=float, default=2e9, help="junk floor, default 2e9"
    )
    ap.add_argument("--min-oi", type=float, default=200_000, help="option OI floor")
    ap.add_argument(
        "--min-act",
        type=float,
        default=5_000,
        help="avg 30d call+put contracts/day floor",
    )
    args = ap.parse_args()

    have = {r["ticker"]: r["sector"] for r in csv.DictReader(args.have.open())}

    pairs = [
        (lid, cn, chain, t)
        for lid, (cn, _en, chains) in TAXONOMY.items()
        for chain, tickers in chains.items()
        for t in tickers
    ]
    universe = sorted({t for *_, t in pairs})
    print(
        f"taxonomy: {len(pairs)} (chain,ticker) pairs over {len(universe)} distinct tickers"
    )

    settings = Settings.from_env()
    # .get_secret_value() is load-bearing: SecretStr stringifies to "**********",
    # which UW rejects with a 401 "token not in UUID format".
    with UwClient(api_key=settings.api_key.get_secret_value()) as client:
        rows = screen(client, universe)

    # Candidates are NEW tickers only — tickers already on the watchlist are not
    # re-categorised here, they only appear as per-chain "already covered" context.
    args.out.parent.mkdir(parents=True, exist_ok=True)
    n_new = 0
    with args.out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["layer", "layer_cn", "chain", "ticker", "status", *FIELDS])
        for lid, cn, chain, t in pairs:
            if t in have:
                continue
            data = rows.get(t)
            w.writerow(
                [
                    lid,
                    cn,
                    chain,
                    t,
                    "NEW" if data else "UNVERIFIED",
                    *[(data or {}).get(f, "") for f in FIELDS],
                ]
            )
            n_new += 1

    coverage = args.out.with_name("chain_coverage.csv")
    with coverage.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["layer", "layer_cn", "chain", "n_have", "have_tickers"])
        for lid, (cn, _en, chains) in TAXONOMY.items():
            for chain, tickers in chains.items():
                owned = sorted(t for t in tickers if t in have)
                w.writerow([lid, cn, chain, len(owned), " ".join(owned)])

    missing = sorted(t for t in universe if t not in rows and t not in have)
    print(f"wrote {args.out}  ({n_new} candidate rows, HAVE excluded)")
    print(f"wrote {coverage}")
    print(f"UNVERIFIED (no UW screener row — delisted/acquired/uncovered): {missing}")

    if args.doc:
        render_doc(args.doc, pairs, rows, have, missing)
        print(f"wrote {args.doc}")

    if args.final:
        render_final(args.final, rows, have, args.min_mcap, args.min_oi, args.min_act)
        print(f"wrote {args.final}")

    if args.hot:
        in_tax = {t for _l, _c, _ch, t in pairs}
        picked = {
            t
            for t, r in rows.items()
            if selected(r, args.min_mcap, args.min_oi, args.min_act)
        }
        with UwClient(api_key=settings.api_key.get_secret_value()) as client:
            hot = screen_hot(client)
        ranked = sorted(
            ((t, d) for t, d in hot.items() if t not in have and t not in picked),
            key=lambda kv: (
                -(
                    _f(kv[1].get("avg_30_day_call_volume"))
                    + _f(kv[1].get("avg_30_day_put_volume"))
                )
            ),
        )
        with args.hot.open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["ticker", "in_taxonomy", "activity_per_day", *FIELDS])
            for t, d in ranked:
                act = _f(d.get("avg_30_day_call_volume")) + _f(
                    d.get("avg_30_day_put_volume")
                )
                w.writerow(
                    [t, "yes" if t in in_tax else "no", int(act)]
                    + [d.get(f, "") for f in FIELDS]
                )
        print(
            f"wrote {args.hot}  ({len(ranked)} option-hot names not already selected)"
        )


def screen_hot(client: UwClient, pages: int = 3) -> dict[str, dict]:
    """Market-wide sweep for sustained option activity, taxonomy-blind.

    Two order keys because the screener sorts on one field: avg 30d call volume
    finds churn, total OI finds depth. A name hot on either is worth seeing, so
    we union them and re-rank on call+put activity locally.
    """
    out: dict[str, dict] = {}
    for order in ("avg_30_day_call_volume", "total_open_interest"):
        for page in range(pages):
            resp, _ = client.get(
                EndpointSlug.BULK_SCREENER_STOCKS,
                params={
                    "order": order,
                    "order_direction": "desc",
                    "limit": 50,
                    "offset": page,
                    "issue_types[]": "Common Stock",
                },
            )
            for row in json.loads(resp.text).get("data", []):
                out[row["ticker"]] = {f: row.get(f) for f in FIELDS}
        print(f"  hot sweep by {order}: {len(out)} cumulative")
    return out


def selected(row: dict, min_mcap: float, min_oi: float, min_act: float) -> bool:
    """Selection bar: option activity is the real filter, cap only excludes junk.

    Market cap is deliberately a low floor, not a real screen. WULF at $8.5B
    trades ~195k contracts/day — more than most mega-caps here — so a $10B cap
    floor would delete most of AI-Cloud/NeoCloud and all of AI-Native-Software,
    which are the chains this taxonomy exists to reach. Cap measures company
    size; argon consumes option surface, and in these chains the two decouple.
    """
    activity = _f(row.get("avg_30_day_call_volume")) + _f(
        row.get("avg_30_day_put_volume")
    )
    return (
        _f(row.get("marketcap")) >= min_mcap
        and _f(row.get("total_open_interest")) >= min_oi
        and activity >= min_act
    )


def render_final(
    path: Path,
    rows: dict[str, dict],
    have: dict[str, str],
    min_mcap: float,
    min_oi: float,
    min_act: float,
) -> None:
    """Render the taxonomy as it would stand once the selected names are added.

    Chains are OVERLAPPING tag sets, not a partition: NVDA is legitimately in
    L1 Computer/GPU and X M7 at once. Membership is therefore many-to-many and
    costs nothing — UW bills per distinct ticker scanned, not per tag — so the
    two numbers to watch are memberships (UI density) and distinct tickers
    (budget). `watchlist.sector` cannot store this; it needs a join table.
    """
    out = [
        "# Final structure — filtered selection",
        "",
        f"Bar: marketcap ≥ ${min_mcap / 1e9:,.0f}B (junk floor only) · "
        f"option OI ≥ {min_oi / 1000:,.0f}k · "
        f"avg option activity ≥ {min_act:,.0f} contracts/day.",
        "",
        "The watchlist covers four focus areas. The 五层蛋糕 5-layer model is the shape",
        "of **one** of them — AI 产业链 — and applies only there. 大盘与宏观 / 主题 /",
        "防御 are equally deliberate coverage with their own chains, listed below",
        "unchanged. They are not leftovers of the AI cut.",
        "",
        "Generated by `scripts/research/watchlist_chain_candidates.py --final`.",
        "",
    ]
    distinct: set[str] = set()
    in_tax: set[str] = set()
    memberships = 0
    for lid, (cn, en, chains) in TAXONOMY.items():
        out += ["", f"## {lid} {cn} ({en})", ""]
        for chain, tickers in chains.items():
            owned = [t for t in tickers if t in have]
            added = [
                t
                for t in tickers
                if t not in have
                and t in rows
                and selected(rows[t], min_mcap, min_oi, min_act)
            ]
            in_tax.update(owned)
            distinct.update(owned + added)
            memberships += len(owned) + len(added)
            out.append(f"**{chain}** ({len(owned) + len(added)})")
            if owned:
                out.append(f"- have: {' '.join(owned)}")
            if added:
                out.append(f"- add: {' '.join(added)}")
            if not owned and not added:
                out.append("- _empty at this bar_")
            out.append("")

    others = sorted(t for t in have if t not in in_tax)
    by_tag: dict[str, list[str]] = {}
    for t in others:
        by_tag.setdefault(have[t], []).append(t)

    placed: set[str] = set()
    for cn, (en, tags) in OTHER_FOCUS.items():
        members = {tag: by_tag[tag] for tag in tags if tag in by_tag}
        n = sum(len(v) for v in members.values())
        out += ["", f"## {cn} ({en}) — {n}, unchanged", ""]
        for tag in tags:
            if tag in members:
                placed.add(tag)
                out.append(
                    f"- **{tag}** ({len(members[tag])}): {' '.join(sorted(members[tag]))}"
                )

    stray = {k: v for k, v in by_tag.items() if k not in placed}
    if stray:
        out += ["", "## Unassigned tags — need a home", ""]
        for tag, ts in stray.items():
            out.append(f"- **{tag}** ({len(ts)}): {' '.join(sorted(ts))}")

    adds = sorted(t for t in distinct if t not in have)
    out += [
        "",
        f"Memberships in the AI taxonomy: {memberships} over {len(distinct)} distinct",
        f"tickers ({memberships - len(distinct)} multi-chain). Memberships drive UI",
        "density; only distinct tickers cost UW budget.",
        "",
        f"New tickers added: {len(adds)} → +{len(adds) * CALLS_PER_TICKER_DAY / 1000:.1f}k UW calls/day.",
        f"Other focus areas (大盘与宏观 / 主题 / 防御), unchanged: {len(others)}.",
        f"Watchlist total: {len(have) + len(adds)}.",
        "",
        f"Adds: {' '.join(adds)}",
    ]
    path.write_text("\n".join(out) + "\n")


def _f(x: object) -> float:
    try:
        return float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


# Option OI is the selection axis, not marketcap: argon derives GEX / skew / VRP
# from the option chain, so a big name with a thin chain buys nothing here.
TIER_A_OI = 200_000
TIER_B_OI = 50_000
CALLS_PER_TICKER_DAY = 240  # measured 2026-08-03..07 on the mini, see doc header


def render_doc(
    path: Path,
    pairs: list[tuple[str, str, str, str]],
    rows: dict[str, dict],
    have: dict[str, str],
    missing: list[str],
) -> None:
    def tier(t: str) -> str:
        oi = _f(rows.get(t, {}).get("total_open_interest"))
        return "A" if oi >= TIER_A_OI else ("B" if oi >= TIER_B_OI else "C")

    out: list[str] = [
        "# Watchlist extension — 五层蛋糕 industry-chain candidates",
        "",
        "Generated, do not hand-edit the tables — edit `LAYERS` in",
        "`src/uw_scan/watchlist_taxonomy.py` and re-run:",
        "",
        "```",
        "UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python \\",
        "  scripts/research/watchlist_chain_candidates.py \\",
        "  --have  docs/research/2026-08-09-watchlist-industry-chains/current_watchlist.csv \\",
        "  --out   docs/research/2026-08-09-watchlist-industry-chains/candidates.csv \\",
        "  --doc   docs/research/2026-08-09-watchlist-industry-chains/SELECT.md \\",
        "  --final docs/research/2026-08-09-watchlist-industry-chains/FINAL.md \\",
        "  --hot   docs/research/2026-08-09-watchlist-industry-chains/hot.csv",
        "```",
        "",
        "Tick `[x]` to add. **Only NEW tickers appear here** — the 114 already on the",
        "watchlist are shown per chain as `have:` context and are never re-categorised.",
        "",
        f"- **Tier A** — option OI ≥ {TIER_A_OI // 1000}k. Real chain, argon can compute GEX/skew/VRP.",
        f"- **Tier B** — OI {TIER_B_OI // 1000}k–{TIER_A_OI // 1000}k. Usable, thinner surface.",
        f"- **Tier C** — OI < {TIER_B_OI // 1000}k. Listed for completeness; not recommended.",
        "",
        f"Budget: measured ~{CALLS_PER_TICKER_DAY} UW calls/day per watchlist ticker.",
        "Weekday burn 2026-08-03..07 was 63–65k against the 120k account cap, splitting",
        "**live 33.6k / 80k ceiling** but **research 22.6k / 30k ceiling** — the research",
        "pool is the binding constraint (only ~7.4k headroom), not the account cap. A new",
        "watchlist ticker bills BOTH pools (full_scan is live; surface/GEX capture and the",
        "gap healer are research), so research runs out first.",
        "",
        f"Rejected by the UW screener (delisted / acquired / uncovered): {', '.join(missing) or 'none'}.",
        "",
    ]

    seen: set[tuple[str, str]] = set()
    for lid, cn, chain, _t in pairs:
        if (lid, chain) in seen:
            continue
        seen.add((lid, chain))
        members = [t for a, _b, c, t in pairs if a == lid and c == chain]
        owned = sorted(t for t in members if t in have)
        cands = sorted(
            (t for t in members if t not in have and t in rows),
            key=lambda t: -_f(rows[t].get("total_open_interest")),
        )
        out.append(f"### {lid} {cn} · {chain}")
        out.append("")
        out.append(f"`have ({len(owned)}):` {' '.join(owned) if owned else '— none —'}")
        out.append("")
        for tr in ("A", "B", "C"):
            group = [t for t in cands if tier(t) == tr]
            if not group:
                continue
            out.append(f"*Tier {tr}*")
            for t in group:
                d = rows[t]
                out.append(
                    f"- [ ] **{t}** · {_f(d.get('marketcap')) / 1e9:,.0f}B mcap · "
                    f"OI {_f(d.get('total_open_interest')) / 1000:,.0f}k · "
                    f"{str(d.get('full_name', ''))[:34].title()}"
                )
            out.append("")
    path.write_text("\n".join(out) + "\n")


if __name__ == "__main__":
    main()
