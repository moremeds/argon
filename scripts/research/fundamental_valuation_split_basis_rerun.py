#!/usr/bin/env python
"""M3.2 — rerun the own-history valuation test on a split-CONSISTENT price basis.

    uv run python scripts/research/fundamental_valuation_split_basis_rerun.py

WHAT WAS WRONG, AND WHY IT SURVIVED REVIEW
------------------------------------------
`fundamental_valuation_timeseries.py` measured `sales_to_ev` within-ticker IC at
+0.0744 (t 5.77) — the single strongest fundamental result Argon holds, and the
one `/scanner/value` rests on. It built market cap as

    market_cap = RAW bronze close x common_stock_shares_outstanding

and its header states the premise out loud:

    "adj_close is retroactively split-adjusted while
     common_stock_shares_outstanding is as-reported, and multiplying the two
     mixes reference frames across every split."

The premise is FALSE, and the same repository documents the correction in
`worker/jobs/fundamental_anchors.load_closes`: "The provider restates historical
share counts onto today's post-split basis". Measured again here on the local
statement store: TSLA runs 3,372M -> 3,369M -> 3,101M -> 3,540M and BKNG
1,024M -> 1,034M -> 794M -> 770M across periods containing splits, with NO
split-sized discontinuity anywhere. An as-reported series would jump by the split
factor on the split date. These do not.

So the research paired a RESTATED share count with an UNRESTATED price and
produced a market cap wrong by the split factor for every quarter before a split
— which is precisely the contamination the header believed it was avoiding. It
survived review because the reasoning is correct given the premise; only the
premise was never measured.

WHY THIS MATTERS FOR THE SIGN, NOT JUST THE NOISE
-------------------------------------------------
The error is not random. Before a split the market cap is understated by the
split factor, so the yield reads far too HIGH — the name looks cheap. After the
split the distortion vanishes. A split is preceded, on average, by a large price
RUN-UP. So the contaminated construction systematically labels a name "cheap"
immediately before the period in which its price rose, which manufactures exactly
the positive IC the verdict reported. Whether that accounts for all, some, or
none of +0.0744 is what this measures.

METHOD
------
Identical harness, identical universe, identical windows, one substitution: the
market-cap price becomes livewire's SILVER close with the DIVIDEND half of the
adjustment undone, which is the same `split_only_close` production already uses
for the shipped band. Both bases run in ONE pass over ONE panel, so the
comparison cannot drift on universe, date range, or code version.

The old verdict is not overwritten. It stays as the record of what was measured
under the old premise; this is a second artifact beside it.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_ARGV = list(sys.argv)
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fundamental_timeseries_test as T  # noqa: E402
import fundamental_valuation_control as VC  # noqa: E402
import fundamental_valuation_timeseries as VT  # noqa: E402

V = T.V

import psycopg  # noqa: E402

from uw_scan.config import Settings  # noqa: E402

OUT_DIR = Path("docs/research/2026-08-25-valuation-split-basis-rerun")

#: The expanding window the original verdict was measured with, plus the trailing
#: window the shipped band actually uses. Two, not four: this run exists to
#: compare PRICE BASES, and multiplying window variants would turn a focused
#: comparison into a grid where the headline is whichever cell reads best.
WINDOWS = (None, 20)

SIGNALS = VT.SIGNALS
CONTROL = VT.CONTROL


def _split_factors(tickers: list[str]) -> dict[str, list[tuple[Any, float]]]:
    """ticker -> [(split date, ratio)], from `uw_scan.corporate_actions`.

    Production builds the same basis by dividing livewire's SILVER close by its
    stored adjustment factors. That tier is EMPTY on this machine (the directory
    exists and holds zero symbols), so it is rebuilt here from Argon's own
    corporate-action ledger, which is an independent record of the same fact.

    The two agree where both are checkable: production documents BKNG at a 25.0
    factor on 2026-04-06, and this table holds exactly that row.
    """
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(
            f"""SELECT ticker, event_date, split_ratio
                  FROM {settings.db_schema}.corporate_actions
                 WHERE event_type = 'split' AND split_ratio IS NOT NULL
                   AND split_ratio > 0 AND ticker = ANY(%s)
                 ORDER BY ticker, event_date""",
            ([t.upper() for t in tickers],),
        )
        out: dict[str, list[tuple[Any, float]]] = {}
        for t, d, r in cur.fetchall():
            out.setdefault(t, []).append((d, float(r)))
    return out


def _split_only_closes(
    tickers: list[str], bronze: dict[str, list]
) -> dict[str, list]:
    """Bronze closes restated onto TODAY's share basis — the shares' own frame.

    `split_only(t, d) = close(t, d) / prod(ratio for every split AFTER d)`.

    Dividends are deliberately NOT adjusted for, matching production: a cash
    dividend genuinely lowers market cap and nothing restates the share count for
    it, so removing it would understate every historical market cap on a payer
    and bias the whole band cheap.
    """
    factors = _split_factors(tickers)
    out: dict[str, list] = {}
    for t, series in bronze.items():
        splits = factors.get(t)
        if not splits:
            # No split in this name's history: bronze already IS the basis.
            out[t] = series
            continue
        rebased = []
        for d, px in series:
            divisor = 1.0
            for ev_date, ratio in splits:
                if ev_date > d:
                    divisor *= ratio
            rebased.append((d, px / divisor))
        out[t] = rebased
    return out


def _panel(uw, tickers, adj, price_src) -> dict[str, list[dict[str, Any]]]:
    """Build the within-ticker z-score panel under ONE market-cap price source."""
    rows: dict[str, list[dict[str, Any]]] = {}
    dropped = 0
    for t in tickers:
        if t not in adj or t not in price_src:
            continue
        bs = uw[t]["balance-sheets"]
        periods = sorted(uw[t]["income-statements"])
        raw_vals: list[dict[str, float | None]] = []
        keep: list[tuple[int, Any]] = []
        for i, p in enumerate(periods):
            know = T.knowledge_date(uw, t, p)
            shares = V._f(bs.get(p), "common_stock_shares_outstanding")
            px = VC.close_on_or_before(price_src[t], know)
            if not shares or shares <= 0 or not px:
                dropped += 1
                continue
            raw_vals.append(VT.ratios(uw, t, periods, i, px * shares))
            keep.append((i, know))

        raw_past = [
            VT.trailing_return(adj[t], know, T.HORIZONS["2q"]) for _, know in keep
        ]
        zs = {
            f"{s}|w{w}": VT.rolling_z([r[s] for r in raw_vals], w)
            for s in SIGNALS
            for w in WINDOWS
        }
        zs[CONTROL] = T.expanding_z(
            [(-r if r is not None else None) for r in raw_past]
        )

        obs: list[dict[str, Any]] = []
        for j, (_, know) in enumerate(keep):
            entry: dict[str, Any] = {
                "know": know,
                "bucket": f"{know.year}Q{(know.month - 1) // 3 + 1}",
            }
            for key in zs:
                entry[key] = zs[key][j]
            if all(entry[f"{s}|w{WINDOWS[0]}"] is None for s in SIGNALS):
                continue
            for h, days in T.HORIZONS.items():
                ret, dd = T.forward_outcomes(adj[t], know, days)
                entry[f"ret_{h}"], entry[f"dd_{h}"] = ret, dd
            obs.append(entry)
        if len(obs) >= T.MIN_OBS:
            rows[t] = obs

    # De-market by knowledge quarter, exactly as the original does.
    by_bucket: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for obs in rows.values():
        for e in obs:
            for h in T.HORIZONS:
                for kind in ("ret", "dd"):
                    v = e[f"{kind}_{h}"]
                    if v is not None:
                        by_bucket[e["bucket"]][f"{kind}_{h}"].append(v)
    means = {
        b: {k: sum(v) / len(v) for k, v in d.items() if v}
        for b, d in by_bucket.items()
    }
    for obs in rows.values():
        for e in obs:
            for h in T.HORIZONS:
                for kind in ("ret", "dd"):
                    v = e[f"{kind}_{h}"]
                    mu = means.get(e["bucket"], {}).get(f"{kind}_{h}")
                    e[f"{kind}_{h}_dm"] = (v - mu) if None not in (v, mu) else None
    return rows, dropped


def _ics(rows, only: set[str] | None = None) -> dict[str, Any]:
    """Per-ticker time-series IC. `only` restricts to a cohort.

    The cohort split is the sharp test. An aggregate over 251 names can absorb a
    real distortion affecting 30% of them, so "the correction barely moved the
    headline" is only evidence if it also holds among the names that were
    actually exposed to a split.
    """
    out: dict[str, Any] = {}
    keys = [f"{s}|w{w}" for s in SIGNALS for w in WINDOWS] + [CONTROL]
    src = rows if only is None else {t: o for t, o in rows.items() if t in only}
    for signal in keys:
        for h in T.HORIZONS:
            for outcome in (f"ret_{h}", f"ret_{h}_dm"):
                ics = []
                for obs in src.values():
                    xs = [
                        (e[signal], e[outcome])
                        for e in obs
                        if e.get(signal) is not None and e.get(outcome) is not None
                    ]
                    if len(xs) < T.MIN_OBS:
                        continue
                    ic = V.spearman([a for a, _ in xs], [b for _, b in xs])
                    if ic is not None:
                        ics.append(ic)
                if ics:
                    s = V.summarize(ics)
                    s["n_tickers"] = s.pop("n_quarters")
                    out[f"{signal}|{outcome}"] = s
    return out


def _partials(rows) -> dict[str, Any]:
    """Partial IC holding pure reversal constant — the confound that eats these."""
    out: dict[str, Any] = {}
    for signal in [f"{s}|w{w}" for s in SIGNALS for w in WINDOWS]:
        for outcome in ("ret_2q_dm",):
            ics = []
            for obs in rows.values():
                trio = [
                    (e[signal], e[outcome], e[CONTROL])
                    for e in obs
                    if e.get(signal) is not None
                    and e.get(outcome) is not None
                    and e.get(CONTROL) is not None
                ]
                if len(trio) < T.MIN_OBS:
                    continue
                ic = VC.partial_spearman(
                    [a for a, _, _ in trio],
                    [b for _, b, _ in trio],
                    [c for _, _, c in trio],
                )
                if ic is not None:
                    ics.append(ic)
            if ics:
                s = V.summarize(ics)
                s["n_tickers"] = s.pop("n_quarters")
                out[f"{signal}|{outcome}"] = s
    return out


def _date(period: str):
    from datetime import date as _d

    return _d.fromisoformat(period[:10])


def _fmt(s: dict[str, Any] | None) -> str:
    if not s or s.get("mean_ic") is None:
        return "-"
    t = s.get("t_stat")
    return f"{s['mean_ic']:+.4f} t{t:+.2f}" if t is not None else f"{s['mean_ic']:+.4f}"


def main() -> int:
    print("1. loading statements ...", flush=True)
    uw = T.load_from_db()
    tickers = sorted(uw)
    print(f"   {len(tickers)} tickers")

    adj = V.load_prices(tickers)              # outcomes: total-return adjusted
    bronze = VC.load_raw_close(tickers)       # OLD market-cap basis
    silver = _split_only_closes(tickers, bronze)  # NEW market-cap basis
    print(
        f"   prices: {len(adj)} adjusted (outcomes), "
        f"{len(bronze)} bronze (old), {len(silver)} split-only (new)"
    )

    # Names with a split INSIDE their own statement window — the only ones the
    # correction can move at all.
    factors = _split_factors(tickers)
    exposed: set[str] = set()
    for t in tickers:
        periods = sorted(uw[t]["income-statements"])
        if not periods:
            continue
        lo = _date(periods[0])
        hi = _date(periods[-1])
        if any(lo <= d <= hi for d, _ in factors.get(t, [])):
            exposed.add(t)
    print(f"   split-exposed tickers: {len(exposed)} of {len(tickers)}")

    results: dict[str, Any] = {}
    for label, src in (("old_raw_close", bronze), ("corrected_split_only", silver)):
        print(f"2. panel on {label} ...", flush=True)
        rows, dropped = _panel(uw, tickers, adj, src)
        print(f"   {len(rows)} tickers, dropped {dropped} quarters")
        results[label] = {
            "tickers": len(rows),
            "dropped_quarters": dropped,
            "ic": _ics(rows),
            "ic_split_exposed": _ics(rows, only=exposed),
            "partial_holding_reversal": _partials(rows),
        }
        results[label]["split_exposed_tickers"] = len(exposed & set(rows))

    payload = {
        "question": (
            "Does the own-history valuation IC survive a split-CONSISTENT market "
            "cap? The original paired restated shares with unrestated prices."
        ),
        "universe": len(tickers),
        "windows": [w if w is not None else "expanding" for w in WINDOWS],
        "min_obs_per_ticker": T.MIN_OBS,
        "control": CONTROL,
        "reproduce": (
            "uv run python scripts/research/"
            "fundamental_valuation_split_basis_rerun.py"
        ),
        "results": results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "rerun.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"
    )

    print("\n" + "=" * 78)
    print(f"{'signal|outcome':<44} {'OLD raw':>15} {'CORRECTED':>15}")
    print("=" * 78)
    old_ic = results["old_raw_close"]["ic"]
    new_ic = results["corrected_split_only"]["ic"]
    for key in sorted(set(old_ic) | set(new_ic)):
        if not key.endswith("ret_2q_dm"):
            continue
        o, n = old_ic.get(key), new_ic.get(key)
        fo = _fmt(o)
        fn = _fmt(n)
        print(f"{key:<44} {fo:>15} {fn:>15}")
    print("\n" + "=" * 78)
    print("SPLIT-EXPOSED COHORT ONLY (the names the correction can move)")
    print(f"{'signal|outcome':<44} {'OLD raw':>15} {'CORRECTED':>15}")
    print("=" * 78)
    old_x = results["old_raw_close"]["ic_split_exposed"]
    new_x = results["corrected_split_only"]["ic_split_exposed"]
    for key in sorted(set(old_x) | set(new_x)):
        if not key.endswith("ret_2q_dm"):
            continue
        print(f"{key:<44} {_fmt(old_x.get(key)):>15} {_fmt(new_x.get(key)):>15}")
    print(f"\nwrote {OUT_DIR}/rerun.json")
    return 0


if __name__ == "__main__":
    sys.argv = _ARGV
    raise SystemExit(main())
