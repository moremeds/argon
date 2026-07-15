#!/usr/bin/env python
"""Chanlun Phase B walk-forward validation probe (spec §Validation).

Two-timeframe prefix replay over 10 liquid names x ~5.1y of apex 1d+30m bars.
For every daily prefix: derive marks (compute_chanlun_full), advance each
mark_id's lifecycle (pending / sublevel / native / invalidated) using the SAME
Task-8 pure functions the nightly job uses, evaluating S1 over the mark's 30m
anchor window (ET-session-dated — never a UTC-date slice). At the end, compute
the 4 spec metrics per category + pooled, apply the per-category per-ticker-half
catastrophic gates (survival >= 70%, breach <= 15%, median latency <= 2
sessions), and persist the full per-mark trace + summary.

Reproduce: uv run python scripts/research/chanlun_sublevel_probe.py
"""

from __future__ import annotations

import csv
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from uw_scan.chanlun.full import compute_chanlun_full
from uw_scan.chanlun.lifecycle import (
    DEFAULT_STALE_SESSIONS,
    anchor_window,
    breached,
    crosses_split_boundary,
    derive_marks,
    find_split_boundaries,
    is_promotable,
    is_stale,
    promotable_key,
    s1_confirmed,
    session_et_date,
)
from uw_scan.chanlun.types import ChanlunBar
from uw_scan.sources.apex import fetch_bars

TICKERS = ["AAPL", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ"]
HALF_A = TICKERS[:5]  # ticker-half split for the AC-F4-style catastrophic gate
HALF_B = TICKERS[5:]
PROMOTABLE_CANDIDATES = frozenset({"vertex", "divergence", "3B", "3S"})
ALL_CATEGORIES = ["vertex", "divergence", "1B", "1S", "2B", "2S", "3B", "3S"]
WARMUP_SESSIONS = 60  # skip degenerate early prefixes
GATE_SURVIVAL = 0.70
GATE_BREACH = 0.15
GATE_LATENCY = 2.0
OUT_DIR = Path("docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe")
REPRODUCE = "uv run python scripts/research/chanlun_sublevel_probe.py"


@dataclass
class MarkTrace:
    """Lifecycle of one mark_id across prefixes. *_idx are session positions
    (index into the ticker's session-date list) so latency/lead are in SESSIONS."""

    ticker: str
    category: str  # vertex | point | divergence
    kind: str
    extreme_date: date
    extreme_price: float
    pending_idx: int
    pending_date: date
    sublevel_idx: int | None = None
    sublevel_date: date | None = None
    native_idx: int | None = None
    native_date: date | None = None
    invalidated_date: date | None = None
    invalid_reason: str | None = None
    transitions: list[tuple[date, str, str]] = field(default_factory=list)

    @property
    def gate_category(self) -> str:
        return promotable_key(self.category, self.kind)

    @property
    def terminal(self) -> bool:
        return self.native_date is not None or self.invalidated_date is not None


@dataclass
class Metrics:
    """The 4 spec metrics over sub-level-confirmed, non-split-excluded marks.
    None = no data (an empty cell must FAIL the gate, not pass it)."""

    n_sublevel: int
    n_resolved: int
    n_censored: int
    survival: float | None
    breach_rate: float | None
    median_latency: float | None
    median_lead: float | None


def compute_metrics(traces: list[MarkTrace]) -> Metrics:
    sub = [
        t
        for t in traces
        if t.sublevel_date is not None and t.invalid_reason != "split_boundary"
    ]
    resolved = [
        t for t in sub if t.native_date is not None or t.invalidated_date is not None
    ]
    censored = len(sub) - len(resolved)  # right-censored: still open at end of data
    survived = [t for t in resolved if t.native_date is not None]
    breached_t = [t for t in resolved if t.invalid_reason == "breach"]
    latencies = [t.sublevel_idx - t.pending_idx for t in sub]
    leads = [
        t.native_idx - t.sublevel_idx
        for t in survived
        if t.native_idx is not None and t.sublevel_idx is not None
    ]
    return Metrics(
        n_sublevel=len(sub),
        n_resolved=len(resolved),
        n_censored=censored,
        survival=(len(survived) / len(resolved)) if resolved else None,
        breach_rate=(len(breached_t) / len(resolved)) if resolved else None,
        median_latency=float(statistics.median(latencies)) if latencies else None,
        median_lead=float(statistics.median(leads)) if leads else None,
    )


def gate_pass(m: Metrics) -> bool:
    """Survival >= 70% AND breach <= 15% AND median latency <= 2 (inclusive).
    A half with no resolved sub-level marks FAILS (no evidence != pass)."""
    if m.survival is None or m.breach_rate is None or m.median_latency is None:
        return False
    return (
        m.survival >= GATE_SURVIVAL
        and m.breach_rate <= GATE_BREACH
        and m.median_latency <= GATE_LATENCY
    )


def _load_bars(ticker: str):
    """Full-history 1d + 30m from apex with an EXPLICIT start (default-window
    gotcha). Returns None when either series is empty — never fabricate bars."""
    start = date.today() - timedelta(days=int(5.3 * 365))
    daily_raw = fetch_bars(ticker, "1d", start, limit=0)
    raw_30m = fetch_bars(ticker, "30m", start, limit=0)
    if not daily_raw or not raw_30m:
        return None
    daily = [
        ChanlunBar(time=b["time"][:10], high=b["high"], low=b["low"], close=b["close"])
        for b in daily_raw
    ]
    bars30 = [
        ChanlunBar(time=b["time"], high=b["high"], low=b["low"], close=b["close"])
        for b in raw_30m
    ]
    # ET session date per 30m bar, computed ONCE (session_et_date, not ts[:10] —
    # post-20:00-ET bars land on the next UTC date and would mis-window).
    et_dates = [session_et_date(b.time) for b in bars30]
    return daily_raw, daily, bars30, et_dates


def replay_ticker(
    ticker: str,
    daily_raw: list[dict],
    daily: list[ChanlunBar],
    bars30: list[ChanlunBar],
    et_dates: list[date],
) -> dict[tuple, MarkTrace]:
    """Walk-forward prefix replay for one ticker. Mirrors the nightly job's
    per-mark decision order exactly (split > native > breach > stale > S1)."""
    traces: dict[tuple, MarkTrace] = {}
    session_dates = [date.fromisoformat(b.time) for b in daily]
    for i in range(WARMUP_SESSIONS, len(daily)):
        # Prefix-restricted split detection: only splits observable as of
        # session i may invalidate a day-i decision. Computing this ONCE over
        # the full series (as originally written) leaked FUTURE split
        # knowledge into day-d decisions — reviewer-caught walk-forward defect.
        boundaries = find_split_boundaries(daily_raw[: i + 1])
        prefix = daily[: i + 1]
        sess = session_dates[: i + 1]
        d = session_dates[i]
        full = compute_chanlun_full(prefix)
        marks = derive_marks(full, prefix)
        derived_keys: set[tuple] = set()
        for m in marks:
            key = (m.category, m.kind, m.extreme_date, m.extreme_price)
            derived_keys.add(key)
            tr = traces.get(key)
            if tr is None:
                tr = MarkTrace(
                    ticker=ticker,
                    category=m.category,
                    kind=m.kind,
                    extreme_date=m.extreme_date,
                    extreme_price=m.extreme_price,
                    pending_idx=i,
                    pending_date=d,
                )
                tr.transitions.append((d, "pending", ""))
                traces[key] = tr
            if tr.terminal:
                continue  # terminal short-circuit — never mutate a settled mark
            anchor_start = anchor_window(m, full.vertices, sess)
            if crosses_split_boundary(m, anchor_start, boundaries):
                tr.invalidated_date, tr.invalid_reason = d, "split_boundary"
                tr.transitions.append((d, "invalidated", "split_boundary"))
                continue
            if m.is_native_confirmed:
                tr.native_idx, tr.native_date = i, d
                tr.transitions.append((d, "confirmed_native", ""))
                continue
            later = [
                b
                for b in daily_raw[: i + 1]
                if b["time"][:10] > m.extreme_date.isoformat()
            ]
            if breached(m, later):
                tr.invalidated_date, tr.invalid_reason = d, "breach"
                tr.transitions.append((d, "invalidated", "breach"))
                continue
            if is_stale(m, d, DEFAULT_STALE_SESSIONS, sess):
                tr.invalidated_date, tr.invalid_reason = d, "stale"
                tr.transitions.append((d, "invalidated", "stale"))
                continue
            if tr.sublevel_date is None and is_promotable(
                m.category, m.kind, PROMOTABLE_CANDIDATES
            ):
                # 30m prefix ending at close(d), windowed to [anchor_start, d]
                # by ET session date.
                w30 = [b for b, ed in zip(bars30, et_dates) if anchor_start <= ed <= d]
                ok, _info = s1_confirmed(m, w30, tol=0.0)
                if ok:
                    tr.sublevel_idx, tr.sublevel_date = i, d
                    tr.transitions.append((d, "confirmed_sublevel", ""))
        # Superseded sweep: a live mark absent from this prefix's recompute has
        # migrated to a more-extreme endpoint — terminally invalidated.
        for key, tr in traces.items():
            if not tr.terminal and key not in derived_keys:
                tr.invalidated_date, tr.invalid_reason = d, "superseded"
                tr.transitions.append((d, "invalidated", "superseded"))
    return traces


def write_csv(all_traces: list[MarkTrace], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "ticker",
                "category",
                "kind",
                "gate_category",
                "extreme_date",
                "extreme_price",
                "transition_date",
                "state",
                "reason",
                "pending_date",
                "sublevel_date",
                "native_date",
                "invalidated_date",
                "invalid_reason",
            ]
        )
        for t in all_traces:
            for td, st, rs in t.transitions:
                w.writerow(
                    [
                        t.ticker,
                        t.category,
                        t.kind,
                        t.gate_category,
                        t.extreme_date,
                        t.extreme_price,
                        td,
                        st,
                        rs,
                        t.pending_date,
                        t.sublevel_date or "",
                        t.native_date or "",
                        t.invalidated_date or "",
                        t.invalid_reason or "",
                    ]
                )


def _fmt(v) -> str:
    if v is None:
        return "-"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def write_summary(
    path: Path,
    per_cat: dict[str, list[tuple[str, Metrics]]],
    verdicts: dict[str, bool],
    split_excluded: int,
    skipped: list[str],
    n_marks: int,
) -> None:
    lines = [
        "# Chanlun Phase B — sub-level confirm probe results",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Reproduce: `{REPRODUCE}`",
        "",
        f"Tickers: {', '.join(TICKERS)} (skipped/no-data: {', '.join(skipped) or 'none'})",
        f"Total marks traced: {n_marks}; split-boundary exclusions: {split_excluded}",
        "",
        "1B/1S/2B/2S are recorded-but-never-promoted by design (spec §Category "
        "scope v1) — their sub-level rows below are structurally empty.",
        "",
        "| category | slice | n_sub | resolved | censored | survival | breach | med latency | med lead |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cat, rows in per_cat.items():
        for slice_name, m in rows:
            lines.append(
                f"| {cat} | {slice_name} | {m.n_sublevel} | {m.n_resolved} | "
                f"{m.n_censored} | {_fmt(m.survival)} | {_fmt(m.breach_rate)} | "
                f"{_fmt(m.median_latency)} | {_fmt(m.median_lead)} |"
            )
    lines += [
        "",
        "## Gate verdicts (survival >= 70% AND breach <= 15% AND median "
        "latency <= 2 sessions, in BOTH ticker-halves)",
        "",
    ]
    for cat, ok in verdicts.items():
        lines.append(f"- **{cat}**: {'PASS' if ok else 'EXCLUDE'}")
    passing = [c for c, ok in verdicts.items() if ok]
    lines += [
        "",
        f"Shipped `chanlun_promotable_categories` default from this run: "
        f"`{','.join(passing)}`",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_traces: list[MarkTrace] = []
    skipped: list[str] = []
    for tk in TICKERS:
        loaded = _load_bars(tk)
        if loaded is None:
            skipped.append(tk)
            print(f"SKIP {tk}: apex returned no 1d or 30m bars", file=sys.stderr)
            continue
        daily_raw, daily, bars30, et_dates = loaded
        traces = replay_ticker(tk, daily_raw, daily, bars30, et_dates)
        assert traces, f"{tk}: replay produced zero marks (non-vacuity)"
        all_traces.extend(traces.values())
        print(f"{tk}: {len(traces)} marks traced over {len(daily)} sessions")
    assert all_traces, "no marks traced at all — probe run is vacuous"
    split_excluded = sum(1 for t in all_traces if t.invalid_reason == "split_boundary")
    per_cat: dict[str, list[tuple[str, Metrics]]] = {}
    verdicts: dict[str, bool] = {}
    for cat in ALL_CATEGORIES:
        cat_traces = [t for t in all_traces if t.gate_category == cat]
        rows = [("pooled", compute_metrics(cat_traces))]
        half_ok: list[bool] = []
        for half_name, half in (("half_A", HALF_A), ("half_B", HALF_B)):
            m = compute_metrics([t for t in cat_traces if t.ticker in half])
            rows.append((half_name, m))
            half_ok.append(gate_pass(m))
        per_cat[cat] = rows
        if cat in PROMOTABLE_CANDIDATES:
            verdicts[cat] = all(half_ok)  # failing EITHER half = EXCLUDE
    write_csv(all_traces, OUT_DIR / "per_mark_trace.csv")
    write_summary(
        OUT_DIR / "summary.md",
        per_cat,
        verdicts,
        split_excluded,
        skipped,
        len(all_traces),
    )
    print(f"wrote {OUT_DIR}/per_mark_trace.csv and {OUT_DIR}/summary.md")
    print("gate verdicts:", verdicts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
