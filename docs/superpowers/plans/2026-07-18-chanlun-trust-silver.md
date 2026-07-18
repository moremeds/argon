# Chanlun Trust Probe (silver bars) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, on corporate-action-adjusted (silver) daily bars, how much the operator can trust chanlun 背离 (顶/底背离) and 买卖点 (1/2/3 B/S) — both repaint stability and forward-return edge — and persist the full trace.

**Architecture:** One research script, `scripts/research/chanlun_trust_probe.py`, reusing the existing chanlun Python port (`uw_scan.chanlun`) and apex bar client (`uw_scan.sources.apex.fetch_bars`). Walk-forward prefix replay over a frozen ~200-ticker universe: for each daily prefix, compute chanlun, track when each mark first reaches `confirmed=true`, and measure signed forward returns from the **confirmation bar's close** (honest, point-in-time) and from the **extreme's close** (hindsight ghost). Compare against a same-ticker unconditional baseline with a bootstrap CI. No production surface — no migration, API, worker, or UI.

**Tech Stack:** Python 3.13 (via `uv`), stdlib only (`csv`, `statistics`, `random`, `argparse`), existing `uw_scan.chanlun` + `uw_scan.sources.apex`.

## Global Constraints

- **uv only** — run everything as `uv run python ...` / `uv run pytest`, never bare `python`/`pytest`.
- **No fabricated market data** — bars come from apex; the universe list is materialized once from a real source (UW screener) and committed with an as-of date. Never invent tickers or prices. A `[]` from `fetch_bars` means "skip", never "success with zero".
- **Point-in-time only** — the compute at prefix `bars[:i+1]` may never see a bar with index > i. Any final-series quantity (final-confirmed set, baseline) is used only for post-hoc scoring, never fed back into the confirmation-detection loop.
- **Persist the full trace** — every confirmed mark × every horizon lands in `per_signal_trace.csv`; `summary.md` records the exact reproduce command. stdout-only is data loss.
- **This is not a strategy** — no costs, sizing, or promotion gate. Report edge as an upper bound (mega-cap survivorship, no frictions).
- **Never commit without explicit user request** — the commit steps below are drafted; wait for the operator's go before running them.

**Reference — signatures this plan relies on (already in the repo):**
- `uw_scan.chanlun.full.compute_chanlun_full(bars: list[ChanlunBar]) -> ChanlunFullResult` (`.vertices`, `.points`, `.divergences`; each element carries `.time: str`, `.price: float`, `.kind: str`, `.confirmed: bool`).
- `uw_scan.chanlun.lifecycle.derive_marks(full, bars) -> list[Mark]` — `Mark(category, kind, extreme_date: date, extreme_price: float, is_native_confirmed: bool)`; `category ∈ {"vertex","divergence","point"}`, point `kind ∈ {1B,1S,2B,2S,3B,3S}`, vertex/divergence `kind ∈ {top,bottom}`.
- `uw_scan.chanlun.lifecycle.mark_side(kind) -> str` — `"bottom"` (bullish) or `"top"` (bearish).
- `uw_scan.chanlun.types.ChanlunBar(time: str, high: float, low: float, close: float)`.
- `uw_scan.sources.apex.fetch_bars(ticker, timeframe, start: date, *, limit=0) -> list[dict]` — dicts keyed `time` (ISO string), `high`, `low`, `close`. Always pass an explicit `start`.

---

### Task 1: Frozen universe list

**Files:**
- Create: `docs/research/2026-07-18-chanlun-trust-silver/universe.csv`
- Create: `scripts/research/_chanlun_trust_universe.py` (one-off materializer, kept for reproducibility)

**Interfaces:**
- Produces: `universe.csv` with header `ticker,as_of` — ~200 rows, each a real US large-cap/liquid-ETF apex has ≥3y of clean 1d bars for. Task 4 reads the `ticker` column.

- [ ] **Step 1: Materialize a candidate list from a real source**

Use the UW stock screener MCP tool to pull the top liquid names by market cap (real source, no fabrication):

Call `mcp__unusual-whales__get_stock_screener` (check the tool schema for the market-cap sort key) and collect the top ~250 tickers by market cap. If that MCP tool is unavailable in the execution session, fall back to `mcp__massive` grouped-daily ranked by dollar volume (`close × volume`), top ~250. Do **not** use `uw_scan.sources.etf_holdings` — it is gold-only (GLD/IAU/GLDM/PHYS), not broad equity. Record today's date as `as_of`.

- [ ] **Step 2: Filter to apex-covered, ≥3y of clean bars**

```python
# scripts/research/_chanlun_trust_universe.py
from datetime import date, timedelta
from uw_scan.sources.apex import fetch_bars

CANDIDATES = [...]  # paste the ~250 tickers from Step 1
AS_OF = date.today().isoformat()
start = date.today() - timedelta(days=int(3.2 * 365))
kept = []
for t in CANDIDATES:
    bars = fetch_bars(t, "1d", start, limit=0)
    if len(bars) >= 700:  # ~3y of sessions; drops gap/newly-listed names
        kept.append(t)
print(f"kept {len(kept)}/{len(CANDIDATES)}")
with open("docs/research/2026-07-18-chanlun-trust-silver/universe.csv", "w") as f:
    f.write("ticker,as_of\n")
    for t in kept:
        f.write(f"{t},{AS_OF}\n")
```

- [ ] **Step 3: Run it**

Run: `uv run python scripts/research/_chanlun_trust_universe.py`
Expected: prints `kept N/250` with N ≈ 180–220; `universe.csv` written.

- [ ] **Step 4: Sanity-check the file**

Run: `uv run python -c "import csv; rows=list(csv.DictReader(open('docs/research/2026-07-18-chanlun-trust-silver/universe.csv'))); print(len(rows), rows[0], rows[-1])"`
Expected: count 180–220; first/last rows show a real ticker + an ISO `as_of` date.

- [ ] **Step 5: Commit** *(await explicit user go)*

```bash
git add docs/research/2026-07-18-chanlun-trust-silver/universe.csv scripts/research/_chanlun_trust_universe.py
git commit -m "research(chanlun): freeze ~200-name universe for trust probe"
```

---

### Task 2: Prefix-replay confirmation engine

**Files:**
- Create: `scripts/research/chanlun_trust_probe.py`

**Interfaces:**
- Consumes: `compute_chanlun_full`, `derive_marks`, `mark_side`, `ChanlunBar`, `fetch_bars`.
- Produces:
  - `load_daily(ticker) -> tuple[list[ChanlunBar], list[float], list[date]] | None` — `(bars, closes, session_dates)`; `None` when apex returns no bars.
  - `ConfTrace` dataclass: `ticker, category, kind, extreme_date, extreme_price, extreme_idx, confirm_idx: int | None, ever_confirmed_live: bool, final_confirmed: bool`.
  - `replay_confirmations(ticker, bars, session_dates) -> list[ConfTrace]` — one `ConfTrace` per mark identity `(category, kind, extreme_date, round(extreme_price,4))` seen anywhere in the replay.

- [ ] **Step 1: Write the module header, imports, and constants**

```python
#!/usr/bin/env python
"""Chanlun trust probe on silver (adjusted) daily bars.

Walk-forward prefix replay over a frozen ~200-name universe. For each mark
(顶/底背离 + 1/2/3 B/S), record the prefix at which it first reaches
confirmed=true, whether that confirmation survives to the final series
(repaint), and signed forward returns from the confirmation close (honest)
and the extreme close (hindsight ghost) vs a same-ticker baseline.

NOT a strategy: no costs/sizing; edge is an upper bound.
Reproduce: uv run python scripts/research/chanlun_trust_probe.py
"""
from __future__ import annotations

import argparse
import csv
import random
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from uw_scan.chanlun.full import compute_chanlun_full
from uw_scan.chanlun.lifecycle import derive_marks, mark_side
from uw_scan.chanlun.types import ChanlunBar
from uw_scan.sources.apex import fetch_bars

WARMUP = 60                       # skip degenerate early prefixes
HORIZONS = [1, 3, 5, 10, 20]      # trading days
HISTORY_DAYS = int(5.3 * 365)
EDGE_CATEGORIES = ["divergence", "point"]  # vertices are structural, not signals
OUT_DIR = Path("docs/research/2026-07-18-chanlun-trust-silver")
UNIVERSE_CSV = OUT_DIR / "universe.csv"
REPRODUCE = "uv run python scripts/research/chanlun_trust_probe.py"
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 20260718
```

- [ ] **Step 2: Write `load_daily`**

```python
def load_daily(ticker: str):
    """Full-history adjusted 1d bars from apex with an EXPLICIT start.
    Returns (bars, closes, session_dates) or None (never fabricate)."""
    start = date.today() - timedelta(days=HISTORY_DAYS)
    raw = fetch_bars(ticker, "1d", start, limit=0)
    if not raw:
        return None
    bars = [
        ChanlunBar(time=b["time"][:10], high=b["high"], low=b["low"], close=b["close"])
        for b in raw
    ]
    closes = [b.close for b in bars]
    session_dates = [date.fromisoformat(b.time) for b in bars]
    return bars, closes, session_dates
```

- [ ] **Step 3: Write the `ConfTrace` dataclass and `replay_confirmations`**

```python
@dataclass
class ConfTrace:
    ticker: str
    category: str
    kind: str
    extreme_date: date
    extreme_price: float
    extreme_idx: int
    confirm_idx: int | None        # session idx where confirmed=true first seen
    ever_confirmed_live: bool
    final_confirmed: bool


def replay_confirmations(ticker, bars, session_dates) -> list[ConfTrace]:
    date_to_idx = {d: i for i, d in enumerate(session_dates)}
    # first_confirmed[key] = session idx i where is_native_confirmed first True
    first_confirmed: dict[tuple, int] = {}
    seen: dict[tuple, tuple] = {}  # key -> (category, kind, extreme_date, extreme_price)
    for i in range(WARMUP, len(bars)):
        full = compute_chanlun_full(bars[: i + 1])
        for m in derive_marks(full, bars[: i + 1]):
            key = (m.category, m.kind, m.extreme_date, round(m.extreme_price, 4))
            seen.setdefault(key, (m.category, m.kind, m.extreme_date, m.extreme_price))
            if m.is_native_confirmed and key not in first_confirmed:
                first_confirmed[key] = i
    # Final full-series pass: which keys are confirmed at the end (repaint check).
    full_final = compute_chanlun_full(bars)
    final_conf: set[tuple] = {
        (m.category, m.kind, m.extreme_date, round(m.extreme_price, 4))
        for m in derive_marks(full_final, bars)
        if m.is_native_confirmed
    }
    out: list[ConfTrace] = []
    for key, (cat, kind, xdate, xprice) in seen.items():
        xidx = date_to_idx.get(xdate)
        if xidx is None:
            continue  # extreme not a session date (shouldn't happen) — skip, don't crash the run
        cidx = first_confirmed.get(key)
        out.append(
            ConfTrace(
                ticker=ticker,
                category=cat,
                kind=kind,
                extreme_date=xdate,
                extreme_price=xprice,
                extreme_idx=xidx,
                confirm_idx=cidx,
                ever_confirmed_live=cidx is not None,
                final_confirmed=key in final_conf,
            )
        )
    return out
```

- [ ] **Step 4: Smoke-run the engine on two tickers**

Add a temporary bottom block, run, then remove it:

```python
if __name__ == "__main__":
    for t in ["AAPL", "NVDA"]:
        loaded = load_daily(t)
        assert loaded, f"no bars for {t}"
        tr = replay_confirmations(t, loaded[0], loaded[2])
        conf = [x for x in tr if x.ever_confirmed_live]
        retract = [x for x in conf if not x.final_confirmed]
        print(t, "marks", len(tr), "confirmed", len(conf), "retracted", len(retract))
```

Run: `uv run python scripts/research/chanlun_trust_probe.py`
Expected: two lines; `confirmed` in the hundreds per name, `retracted` a small fraction (single digits / low-teens % of confirmed — matches the July 100%-retention-for-vertices/div finding on clean bars). Then delete this temporary block.

- [ ] **Step 5: Commit** *(await explicit user go)*

```bash
git add scripts/research/chanlun_trust_probe.py
git commit -m "research(chanlun): prefix-replay confirmation engine for trust probe"
```

---

### Task 3: Forward-return + baseline + bootstrap metrics

**Files:**
- Modify: `scripts/research/chanlun_trust_probe.py`

**Interfaces:**
- Consumes: `ConfTrace`, `mark_side`, module closes arrays.
- Produces:
  - `fwd_return(closes, i, h) -> float | None`
  - `direction(kind) -> float` — `+1.0` bullish / `-1.0` bearish (via `mark_side`).
  - `baseline_means(closes) -> dict[int, float]` — unconditional mean forward return per horizon.
  - `cluster_bootstrap_ci(rows, seed) -> tuple[float, float]` — deterministic 95% CI, resampling tickers (clusters) not marks.
  - `aggregate(rows) -> list[dict]` — per (category-token, horizon, entry) summary rows.
  - `_selftest()` — assert-based self-check.

- [ ] **Step 1: Write the pure metric helpers**

```python
def fwd_return(closes: list[float], i: int, h: int) -> float | None:
    j = i + h
    if j >= len(closes) or closes[i] == 0:
        return None
    return closes[j] / closes[i] - 1.0


def direction(kind: str) -> float:
    return 1.0 if mark_side(kind) == "bottom" else -1.0


def baseline_means(closes: list[float]) -> dict[int, float]:
    """Unconditional (direction-agnostic) mean forward return per horizon."""
    out: dict[int, float] = {}
    for h in HORIZONS:
        rs = [
            closes[k + h] / closes[k] - 1.0
            for k in range(WARMUP, len(closes) - h)
            if closes[k] != 0
        ]
        out[h] = statistics.fmean(rs) if rs else 0.0
    return out


def cluster_bootstrap_ci(rows: list[dict], seed: int) -> tuple[float, float]:
    """Deterministic 95% CI of the mean edge, resampling TICKERS (clusters), not
    individual marks. Same-ticker forward returns overlap in time and are
    correlated; a per-mark bootstrap would treat them as independent and return a
    spuriously tight CI, overstating significance. Resampling whole tickers
    respects the dominant (within-ticker) correlation. nan if <2 tickers."""
    by_ticker: dict[str, list[float]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], []).append(r["edge"])
    tickers = list(by_ticker)
    if len(tickers) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(BOOTSTRAP_N):
        pool: list[float] = []
        for _ in range(len(tickers)):
            pool.extend(by_ticker[rng.choice(tickers)])
        if pool:
            means.append(statistics.fmean(pool))
    means.sort()
    return (means[int(0.025 * len(means))], means[int(0.975 * len(means))])
```

- [ ] **Step 2: Write the per-signal row builder**

`category_token` = `kind` for points (`1B`…`3S`), else `category` (`divergence`). Signed edge is `dir * (ret - baseline)`.

```python
def signal_rows(trace: ConfTrace, closes: list[float], base: dict[int, float]) -> list[dict]:
    # Score ONLY marks that eventually confirmed, so the confirmation entry and
    # the extreme (ghost) entry measure the SAME population — isolating the cost
    # of entry timing (the ~8-bar lookahead), not also swapping in never-confirmed
    # provisional-tail noise. A mark that never confirms is not a tradeable signal.
    if trace.category not in EDGE_CATEGORIES or trace.confirm_idx is None:
        return []
    d = direction(trace.kind)
    token = trace.kind if trace.category == "point" else trace.category
    rows = []
    for entry_name, entry_idx in (
        ("confirmation", trace.confirm_idx),  # honest
        ("extreme", trace.extreme_idx),       # hindsight ghost
    ):
        if entry_idx is None:
            continue
        for h in HORIZONS:
            ret = fwd_return(closes, entry_idx, h)
            if ret is None:
                continue
            rows.append(
                {
                    "ticker": trace.ticker,
                    "category_token": token,
                    "kind": trace.kind,
                    "extreme_date": trace.extreme_date.isoformat(),
                    "entry": entry_name,
                    "horizon": h,
                    "signed_ret": d * ret,
                    "signed_baseline": d * base[h],
                    "edge": d * (ret - base[h]),
                    "correct": 1 if d * ret > 0 else 0,
                }
            )
    return rows
```

- [ ] **Step 3: Write the aggregator**

```python
def aggregate(rows: list[dict]) -> list[dict]:
    """Group by (category_token, entry, horizon) -> summary with bootstrap CI."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["category_token"], r["entry"], r["horizon"]), []).append(r)
    out = []
    for (token, entry, h), rs in sorted(groups.items()):
        edges = [r["edge"] for r in rs]
        lo, hi = cluster_bootstrap_ci(rs, BOOTSTRAP_SEED)
        out.append(
            {
                "category_token": token,
                "entry": entry,
                "horizon": h,
                "n": len(rs),
                "hit_rate": statistics.fmean(r["correct"] for r in rs),
                "mean_signed_ret": statistics.fmean(r["signed_ret"] for r in rs),
                "median_signed_ret": statistics.median(r["signed_ret"] for r in rs),
                "mean_baseline": statistics.fmean(r["signed_baseline"] for r in rs),
                "mean_edge": statistics.fmean(edges),
                "edge_ci_lo": lo,
                "edge_ci_hi": hi,
                "ci_excludes_zero": lo > 0 or hi < 0,
            }
        )
    return out
```

- [ ] **Step 4: Write `_selftest` and wire a `--selftest` flag**

```python
def _selftest() -> None:
    closes = [100.0, 101.0, 102.0, 99.0]
    assert abs(fwd_return(closes, 0, 1) - 0.01) < 1e-9
    assert fwd_return(closes, 3, 1) is None            # off the end
    assert direction("3B") == 1.0 and direction("3S") == -1.0
    assert direction("bottom") == 1.0 and direction("top") == -1.0
    # signed edge: a bearish mark that falls is positive edge vs a flat baseline
    base = {1: 0.0}
    tr = ConfTrace("X", "point", "3S", date(2024, 1, 2), 102.0, 2, 2, True, True)
    r = signal_rows(tr, closes, base)
    conf = [x for x in r if x["entry"] == "confirmation" and x["horizon"] == 1][0]
    assert conf["signed_ret"] > 0 and conf["correct"] == 1   # 102 -> 99 down, bearish correct
    # a never-confirmed mark yields NO edge rows (both entries gated on confirmation)
    assert signal_rows(ConfTrace("X", "point", "3S", date(2024, 1, 2), 102.0, 2, None, False, False), closes, base) == []
    # cluster bootstrap is deterministic and brackets a positive mean (2 tickers, all +edge)
    crows = [{"ticker": "A", "edge": 0.01}, {"ticker": "A", "edge": 0.02},
             {"ticker": "B", "edge": 0.015}, {"ticker": "B", "edge": 0.03}]
    lo, hi = cluster_bootstrap_ci(crows, BOOTSTRAP_SEED)
    assert lo > 0 and hi > lo
    print("selftest OK")
```

Add to the (still temporary) `__main__`:

```python
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
```

- [ ] **Step 5: Run the self-check**

Run: `uv run python scripts/research/chanlun_trust_probe.py --selftest`
Expected: `selftest OK` (non-zero exit / AssertionError if any metric is wrong).

- [ ] **Step 6: Commit** *(await explicit user go)*

```bash
git add scripts/research/chanlun_trust_probe.py
git commit -m "research(chanlun): forward-return, baseline, bootstrap metrics + selftest"
```

---

### Task 4: Artifact writers, main loop, full run

**Files:**
- Modify: `scripts/research/chanlun_trust_probe.py`
- Create (by running): `docs/research/2026-07-18-chanlun-trust-silver/per_signal_trace.csv`, `.../summary.md`

**Interfaces:**
- Consumes: everything above + `UNIVERSE_CSV`.
- Produces: `main(argv)` with flags `--tickers T1,T2` (override universe for a smoke run) and `--limit N`; writes both artifacts.

- [ ] **Step 1: Write the universe loader and repaint aggregator**

```python
def load_universe() -> list[str]:
    with UNIVERSE_CSV.open() as f:
        return [row["ticker"] for row in csv.DictReader(f)]


def repaint_rows(traces: list[ConfTrace]) -> list[dict]:
    """Per category_token: retraction rate among ever-confirmed-live marks."""
    groups: dict[str, list[ConfTrace]] = {}
    for t in traces:
        token = t.kind if t.category == "point" else t.category
        groups.setdefault(token, []).append(t)
    out = []
    for token, ts in sorted(groups.items()):
        conf = [t for t in ts if t.ever_confirmed_live]
        retract = [t for t in conf if not t.final_confirmed]
        out.append(
            {
                "category_token": token,
                "n_marks": len(ts),
                "n_confirmed_live": len(conf),
                "retraction_rate": (len(retract) / len(conf)) if conf else float("nan"),
            }
        )
    return out
```

- [ ] **Step 2: Write the CSV + summary writers**

```python
def write_trace_csv(rows: list[dict], path: Path) -> None:
    cols = ["ticker", "category_token", "kind", "extreme_date", "entry",
            "horizon", "signed_ret", "signed_baseline", "edge", "correct"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def write_summary(edge_agg, repaint, n_tickers, path: Path) -> None:
    lines = [
        "# Chanlun trust probe — silver (adjusted) daily bars",
        "",
        f"Tickers: {n_tickers} | Horizons: {HORIZONS} | Entry: confirmation (honest) vs extreme (hindsight ghost)",
        f"Reproduce: `{REPRODUCE}`",
        "",
        "Edge = signed_ret − same-ticker unconditional baseline, scored ONLY on marks "
        "that eventually confirmed (confirmation entry = honest; extreme entry = same "
        "marks, hindsight ghost). `ci_excludes_zero` flags where the cluster-bootstrap "
        "95% CI (resampled by ticker) is entirely one side of 0.",
        "",
        "Caveats: (1) the CI resamples tickers to respect within-ticker overlap but "
        "still assumes tickers are independent and ignores residual serial correlation "
        "— read `ci_excludes_zero` as suggestive, not a p-value. (2) `retraction_rate` "
        "counts a mark that migrated to a more-extreme endpoint (supersession) as "
        "retracted. (3) NOT a strategy: no costs/sizing; mega-cap survivorship → the "
        "edge is an upper bound.",
        "",
        "## Repaint stability (ever-confirmed-live → still confirmed in final series)",
        "",
        "| category | n_marks | n_confirmed | retraction_rate |",
        "|---|---|---|---|",
    ]
    for r in repaint:
        lines.append(
            f"| {r['category_token']} | {r['n_marks']} | {r['n_confirmed_live']} "
            f"| {r['retraction_rate']:.3f} |"
        )
    lines += [
        "",
        "## Forward-return edge (confirmation entry = headline; extreme = ghost)",
        "",
        "| category | entry | horizon | n | hit_rate | mean_edge | CI_lo | CI_hi | CI≠0 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for a in edge_agg:
        lines.append(
            f"| {a['category_token']} | {a['entry']} | {a['horizon']} | {a['n']} "
            f"| {a['hit_rate']:.3f} | {a['mean_edge']:+.4f} | {a['edge_ci_lo']:+.4f} "
            f"| {a['edge_ci_hi']:+.4f} | {'yes' if a['ci_excludes_zero'] else ''} |"
        )
    path.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 3: Write `main` and replace the temporary `__main__`**

```python
def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--tickers", default="", help="comma list; overrides universe (smoke)")
    ap.add_argument("--limit", type=int, default=0, help="cap ticker count")
    args = ap.parse_args(argv)
    if args.selftest:
        _selftest()
        return 0

    tickers = args.tickers.split(",") if args.tickers else load_universe()
    if args.limit:
        tickers = tickers[: args.limit]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_traces: list[ConfTrace] = []
    all_signal_rows: list[dict] = []
    skipped = []
    for n, t in enumerate(tickers, 1):
        loaded = load_daily(t)
        if not loaded:
            skipped.append(t)
            continue
        bars, closes, sess = loaded
        traces = replay_confirmations(t, bars, sess)
        base = baseline_means(closes)
        all_traces.extend(traces)
        for tr in traces:
            all_signal_rows.extend(signal_rows(tr, closes, base))
        print(f"[{n}/{len(tickers)}] {t}: {len(traces)} marks")

    edge_agg = aggregate(all_signal_rows)
    repaint = repaint_rows(all_traces)
    write_trace_csv(all_signal_rows, OUT_DIR / "per_signal_trace.csv")
    write_summary(edge_agg, repaint, len(tickers) - len(skipped),
                  OUT_DIR / "summary.md")
    print(f"done: {len(all_signal_rows)} signal-rows, skipped {len(skipped)}: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Smoke-run on two tickers**

Run: `uv run python scripts/research/chanlun_trust_probe.py --tickers AAPL,NVDA`
Expected: two `[n/2]` lines, a `done:` line with a few-thousand signal-rows; `per_signal_trace.csv` and `summary.md` written under the research dir. Open `summary.md` and confirm both tables render with plausible numbers (retraction_rate low for divergence; hit_rates near 0.5 with small edges).

- [ ] **Step 5: Verify the self-check still passes**

Run: `uv run python scripts/research/chanlun_trust_probe.py --selftest`
Expected: `selftest OK`.

- [ ] **Step 6: Full run over the frozen universe**

Run: `uv run python scripts/research/chanlun_trust_probe.py`
Expected: ~200 progress lines; a `done:` line; both artifacts populated over the full universe. Runtime **~4–5 minutes single-process** (measured 2026-07-18: ~1.3s/ticker for AAPL's ~1266 prefixes, so ~200 names ≈ 4.2 min). If a real run is far slower, investigate before narrowing the universe. Skim `summary.md` for the verdict per category.

- [ ] **Step 7: Commit** *(await explicit user go)*

```bash
git add scripts/research/chanlun_trust_probe.py docs/research/2026-07-18-chanlun-trust-silver/
git commit -m "research(chanlun): trust probe over silver bars — repaint + forward-edge trace"
```

---

## Self-Review

**Spec coverage:**
- Repaint stability → Task 2 (`ever_confirmed_live`/`final_confirmed`) + Task 4 `repaint_rows`. ✓
- Forward-return edge, confirmation vs extreme entry → Task 3 `signal_rows` (both entries). ✓
- Same-ticker baseline + bootstrap CI → Task 3 `baseline_means`/`bootstrap_ci`/`aggregate`. ✓
- Per category × horizon, thin-category visibility → `aggregate` emits `n` + `ci_excludes_zero`. ✓
- ~200-name frozen universe from a real source → Task 1. ✓
- Point-in-time (no lookahead) → replay only ever computes on `bars[:i+1]`; final-series pass used only for repaint scoring, not fed back. ✓
- Persist full trace + reproduce command → Task 4 writers. ✓
- No production surface → no migration/API/worker/UI touched. ✓

**Placeholder scan:** none — every step carries runnable code or an exact command. (Task 1 Step 1's candidate list is materialized live from the UW screener; that's a real-source fetch, not a placeholder.)

**Type consistency:** `ConfTrace` fields defined in Task 2 are used identically in Tasks 3–4; `signal_rows`/`aggregate`/`write_summary` column keys match across writer and aggregator; `category_token` derivation (`kind` for points else `category`) is identical in `signal_rows`, `repaint_rows`. ✓

**Runtime, measured:** the full run recomputes `compute_chanlun_full` per prefix per ticker (~200 × ~1300). Measured 2026-07-18 at ~1.3s/ticker → **~4 min total single-process**, so no parallelism is needed (YAGNI — the per-ticker multiprocessing option stays unbuilt unless a future universe expansion makes it slow).

---

## Task 5 (added 2026-07-18): quality improvements (executed)

After the first full run, four robustness upgrades were folded into the same
script (no new files) in response to "can we improve quality" + "how long is a
signal valid / bounced-then-failed":

1. **State-conditioned baseline** — `state_baseline(closes)` buckets every bar by
   its trailing-`STATE_LOOKBACK`(=20)-session return into per-ticker quantiles
   (`STATE_BUCKETS`=5); `signal_rows` emits `state_edge` alongside `edge`. Isolates
   the signal's marginal value beyond the momentum regime it fires in (a 底背离
   fires after a decline, so the unconditional edge partly just captures post-decline
   drift). `aggregate(rows, field)` runs on both columns; summary §3 is the honest one.
2. **Period robustness** — `period_robustness()` splits each ticker's confirmation-entry
   marks at its session midpoint (H1/H2) and flags `same_sign`. An edge that flips
   between halves is a period artifact ([[feedback_per_regime_catastrophic_gate]]).
   Summary §4.
3. **Markout + breach-survival** — `markout_survival()` from the confirmation bar:
   mean signed markout path, survival curve (fraction whose marked extreme is not yet
   re-broken; bottom = later low < level, top = later high > level via
   `_first_breach_offset`), `bounced_breach_rate` (breach among marks that first moved
   the predicted way within `BOUNCE_H`=5d), and time-to-breach (median/p90).
   `MARKOUT_HORIZONS`=[1,3,5,10,20,40,60]. Summary §5 — answers the validity-window
   question. Requires bars retained per ticker (`bars_by_ticker`/`closes_by_ticker`).
4. **Cheap honesty** — lag-to-confirm distribution (`lag_rows`, validates ~8-bar
   lookahead on clean bars), multiple-comparisons caveat (~80 cells → ~4 chance
   flags; trust cross-horizon + cross-period consistency), and an economic-floor
   caveat (`COST_HURDLE`=0.15% round-trip).

Trace CSV gains `period` + `state_edge` columns. Selftest extended to cover
state_baseline, `_first_breach_offset`, and `period_robustness`. Same reproduce
command; runtime unchanged (the new passes are O(n) vs the O(n²) replay).

## Task 6 (added 2026-07-18): accuracy-improvement research (executed)

After a deep-research literature pass (`docs/research/` note pending; sources:
Aronson 2006, Pan-Poteshman 2006, Cremers-Weinbaum 2010, Muravyev-Pearson-Pollet
2025, Lo-Mamaysky-Wang 2000, Connors/Alvarez), two conditioning phases were added:

- **Phase 1 (in-data, cheap):** `rolling_above_sma` (200-DMA) + momentum-bucket depth
  → `trend_agree`/`depth_favorable`/`mom_bucket` columns; `conditioning_report` (§6).
  **Result: the 200-DMA trend filter genuinely lifts the divergence signal** — 底背离
  above / 顶背离 below → hit 0.52→0.57, edge +0.50%→+0.65% at 10d, CI-positive and
  period-robust (n≈1030). Depth (still-oversold at entry) does not help; 三买 stays
  negative. The most-replicated literature conditioner earns its keep, modestly.

- **Phase 2 (orthogonal, GEX):** `_chanlun_trust_gex.py` caches UW single-name net
  dealer gamma (call_gamma+put_gamma) per (ticker,date) → `gex_history.csv` (165.8k
  rows, ~2023-08→present — the tier caps single-name history at ~730 trading days).
  `build_regime_series` tags each confirmation's dealer-gamma regime (as-of, no
  lookahead); `gex_edge_report` (§7a) + `gex_survival` (§7b). **Result: NO clean
  improvement.** GEX-regime does not lift the divergence signal in the research-
  predicted direction; it shows a counterintuitive *negative*-gamma edge (+0.86% vs
  +0.27% pos, 10d) that (a) is on ~half the sample, (b) contradicts the literature
  mechanism, (c) has no period-robustness check possible in a 2.8y window dominated
  by a few V-shaped selloffs, and (d) matches the prior weak/confounded GEX evidence
  in this stack. Treated as a NULL result for the orthogonal lever, not an edge.

The full options-flow lever the research ranked #1 (Pan-Poteshman open-buy P/C) is
**not feasible on the current UW tier** (single-name history caps at ~2.8y; open-buy
volume not available as a cheap per-ticker series). Documented, deferred.

Trace CSV gains `mom_bucket`/`trend_agree`/`depth_favorable`/`gamma_regime`. New
durable artifacts: `gex_history.csv`. Cache materializer: `_chanlun_trust_gex.py`.
