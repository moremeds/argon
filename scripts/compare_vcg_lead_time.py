#!/usr/bin/env python3
"""VCG composite vs single-proxy lead-time comparator.

Invariant (locked by spec §15): zero database queries between the start of
the per-cell loop and report assembly. All data is batch-loaded upfront.

Produces docs/research/regime/vcg-composite-validation-2026-05-26.md with:
  1. Methodology recap (explicit gate aggregation language)
  2. Data coverage (per-benchmark bar counts, used/dropped)
  3. Per-period results matrix
  4. Disagreement diagnostic
  5. Promotion gate verdicts
  6. Quoted numbers
  7. Run inventory + artifact appendix + replay query templates
"""

from __future__ import annotations

import argparse
import bisect
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT / "src"))

from uw_scan.cards.drawdown import (  # noqa: E402
    DrawdownDefinition,
    detect_drawdown_events,
)
from uw_scan.cards.vcg_validation_metrics import (  # noqa: E402
    actionable_lead_days,
    alarm_day_ratio,
    close_to_trough_lead_days,
    fp_day_rate,
    fp_episode_rate,
    hit_rate,
    ro_episodes,
    utility_score,
)
from uw_scan.config import Settings  # noqa: E402
from uw_scan.storage.regime_backtest_repository import (  # noqa: E402
    RegimeBacktestRepository,
)

log = logging.getLogger("compare_vcg_lead_time")

# Cash indices — broad / mega-cap-tech / small-cap-credit. NDX/RUT presence
# is opportunistic; the comparator drops anything below the 4000-bar threshold
# and the report's §2 surfaces what was actually used.
BENCHMARKS = ("SPX", "NDX", "RUT")
DRAWDOWN_DEFS = (
    DrawdownDefinition("Fast", 0.05, 10),
    DrawdownDefinition("Medium", 0.07, 20),
    DrawdownDefinition("Major", 0.10, 60),
)
PERIOD_SLICES = (
    ("pre-2020", date(2008, 1, 1), date(2019, 12, 31)),
    ("2020-COVID", date(2020, 1, 1), date(2020, 12, 31)),
    ("2021-2022-rates", date(2021, 1, 1), date(2022, 12, 31)),
    ("2023-2026-AI", date(2023, 1, 1), date(2026, 5, 26)),
)
FP_HORIZON_DAYS = {"Fast": 30, "Medium": 30, "Major": 60}


@dataclass(frozen=True)
class ProxyRun:
    run_id: int
    credit_proxy: str
    composite_method: str
    composite_version: str
    daily: pd.DataFrame  # index=date, columns=['score','level','payload']


@dataclass(frozen=True)
class BatchData:
    benchmarks: dict[str, pd.Series]
    runs: list[ProxyRun]
    trading_days_by_period: dict[str, list[date]]


def load_benchmarks(conn: psycopg.Connection) -> dict[str, pd.Series]:
    """Reads cash-index closes from vol_index_daily. Drops anything under
    4000 bars with a logged warning; the report's coverage table surfaces
    the gap."""
    out: dict[str, pd.Series] = {}
    for ticker in BENCHMARKS:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_date, close FROM uw_scan.vol_index_daily "
                "WHERE symbol = %s AND close IS NOT NULL ORDER BY trade_date",
                (ticker,),
            )
            rows = cur.fetchall()
        if len(rows) < 4000:
            log.warning(
                "%s has only %d bars in vol_index_daily; dropping from "
                "validation universe",
                ticker,
                len(rows),
            )
            continue
        out[ticker] = pd.Series({r[0]: float(r[1]) for r in rows}, name=ticker)
    return out


def load_research_runs(repo: RegimeBacktestRepository) -> list[ProxyRun]:
    """Longest-coverage run per (credit_proxy, composite_method, composite_version).

    Smoke runs over a short date window must not displace the canonical
    full-history backtest for the same key. We sort by n_days DESC (with
    created_at DESC as tiebreak) and keep the first occurrence of each key,
    so the fullest coverage always wins.
    """
    runs = repo.list_research_runs(indicator="vcg", limit=200)
    runs.sort(key=lambda r: (r.get("n_days") or 0, r["created_at"]), reverse=True)
    seen: set[tuple[str, str, str]] = set()
    out: list[ProxyRun] = []
    for r in runs:
        key = (r["credit_proxy"], r["composite_method"], r["composite_version"])
        if key in seen:
            continue
        seen.add(key)
        daily = repo.fetch_daily_for_run(r["id"])
        df = pd.DataFrame(daily).set_index("trade_date") if daily else pd.DataFrame()
        out.append(
            ProxyRun(
                run_id=r["id"],
                credit_proxy=r["credit_proxy"],
                composite_method=r["composite_method"],
                composite_version=r["composite_version"],
                daily=df,
            )
        )
    return out


def batch_load_all(settings: Settings) -> BatchData:
    """ALL DB queries happen here. After return, no further DB access permitted."""
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = RegimeBacktestRepository(conn, schema=settings.db_schema)
        benchmarks = load_benchmarks(conn)
        runs = load_research_runs(repo)
    tdays_by_period: dict[str, list[date]] = {}
    if benchmarks:
        all_dates = sorted(set.union(*[set(s.index) for s in benchmarks.values()]))
        for name, start, end in PERIOD_SLICES:
            tdays_by_period[name] = [d for d in all_dates if start <= d <= end]
    return BatchData(
        benchmarks=benchmarks, runs=runs, trading_days_by_period=tdays_by_period
    )


# ---------------- per-cell metrics ----------------


@dataclass(frozen=True)
class CellResult:
    period: str
    benchmark: str
    drawdown_def: str
    credit_proxy: str
    composite_method: str
    n_events: int
    median_close_lead: float
    median_actionable_lead: float
    hit_rate: float
    fp_day_rate: float
    fp_short_horizon_rate: float
    fp_event_window_rate: float
    fp_episode_rate: float
    precision_day: float
    recall_event: float
    alarm_day_ratio: float
    ro_episode_count: int
    median_ro_episode_length_bdays: float
    disagreement_vs_hyg_rate: float
    utility_score: float


def _ro_signal_from_daily(daily: pd.DataFrame) -> pd.Series:
    """Extract RO bool series. Defensively handles BOTH payload shapes:

    - Composite (this PR): payload['signal']['ro']
    - Single-proxy (existing scripts/backtest_vcg.py): payload['ro']
    """
    if daily.empty or "payload" not in daily.columns:
        return pd.Series(dtype=bool)

    def _is_ro(row: object) -> bool:
        if not isinstance(row, dict):
            return False
        sig = row.get("signal")
        if isinstance(sig, dict) and "ro" in sig:
            return bool(sig.get("ro"))
        return bool(row.get("ro"))

    flags = daily["payload"].apply(_is_ro)
    return flags.astype(bool)


def _fp_short_horizon_rate(
    ro: pd.Series,
    *,
    closes: pd.Series,
    trading_days: list[date],
    horizon_days: int = 10,
    threshold: float = 0.02,
) -> float:
    """RO days with no forward drawdown >= threshold within horizon_days bdays.
    Spec §8 diagnostic — reported alongside FP_episode_rate."""
    on = ro[ro]
    if on.empty or closes.empty:
        return float("nan")
    tds = trading_days
    fp = 0
    for d in on.index:
        d_real = d.date() if hasattr(d, "date") else d
        ci = bisect.bisect_left(tds, d_real)
        if ci >= len(tds) or tds[ci] != d_real:
            continue
        horizon_end = tds[min(ci + horizon_days, len(tds) - 1)]
        window = closes[(closes.index >= d_real) & (closes.index <= horizon_end)]
        if window.empty:
            fp += 1
            continue
        peak = window.iloc[0]
        trough = window.min()
        drawdown = (peak - trough) / peak if peak > 0 else 0.0
        if drawdown < threshold:
            fp += 1
    return fp / len(on)


def compute_cell(
    period: str,
    benchmark: str,
    defn: DrawdownDefinition,
    run: ProxyRun,
    closes: pd.Series,
    trading_days: list[date],
    *,
    hyg_ro: pd.Series | None = None,
) -> CellResult:
    """Per-cell metrics. Lead-time values in TRADING days."""
    closes_p = closes[
        (closes.index >= trading_days[0]) & (closes.index <= trading_days[-1])
    ]
    events = detect_drawdown_events(closes_p, defn)
    ro_full = _ro_signal_from_daily(run.daily)
    ro = ro_full[
        (ro_full.index >= trading_days[0]) & (ro_full.index <= trading_days[-1])
    ]

    hr = hit_rate(events, ro_signal=ro, trading_days=trading_days, peak_lookback=30)

    leads_actionable: list[int] = []
    leads_close: list[int] = []
    for e in events:
        peak_idx = bisect.bisect_left(trading_days, e.peak_date)
        window_lo = trading_days[max(0, peak_idx - 30)]
        ro_in = ro[(ro.index >= window_lo) & (ro.index <= e.trough_date) & (ro)]
        if ro_in.empty:
            continue
        ro_date = ro_in.index[0]
        ro_date = ro_date.date() if hasattr(ro_date, "date") else ro_date
        cl = close_to_trough_lead_days(ro_date, e.trough_date, trading_days)
        leads_close.append(cl)
        a = actionable_lead_days(ro_date, e.trough_date, trading_days)
        if a >= 0:
            leads_actionable.append(a)

    eps = ro_episodes(ro)

    fp_d = fp_day_rate(
        ro,
        events=events,
        trading_days=trading_days,
        horizon_days=defn.window_days,
    )
    fp_e = fp_episode_rate(
        ro,
        events=events,
        trading_days=trading_days,
        horizon_days=FP_HORIZON_DAYS[defn.name],
    )
    fp_short = _fp_short_horizon_rate(
        ro,
        closes=closes_p,
        trading_days=trading_days,
        horizon_days=10,
        threshold=0.02,
    )
    fp_event_window = fp_day_rate(
        ro,
        events=events,
        trading_days=trading_days,
        horizon_days=FP_HORIZON_DAYS[defn.name],
    )

    ro_total = int(ro.sum())
    tp_days = ro_total - int(fp_d * max(ro_total, 1)) if not pd.isna(fp_d) else 0
    fp_days = int(fp_d * max(ro_total, 1)) if not pd.isna(fp_d) else 0
    precision_day = (
        (tp_days / (tp_days + fp_days)) if (tp_days + fp_days) > 0 else float("nan")
    )
    events_caught = int(round(hr * len(events))) if events and not pd.isna(hr) else 0
    recall_event = (events_caught / len(events)) if events else float("nan")

    if hyg_ro is None or hyg_ro.empty:
        disagreement = float("nan")
    else:
        common_idx = ro.index.intersection(hyg_ro.index)
        if len(common_idx) == 0:
            disagreement = float("nan")
        else:
            disagreement = float((ro.loc[common_idx] != hyg_ro.loc[common_idx]).mean())

    median_actionable = (
        float(pd.Series(leads_actionable).median())
        if leads_actionable
        else float("nan")
    )

    if eps:
        lengths = [close_to_trough_lead_days(a, b, trading_days) + 1 for a, b in eps]
        median_ep_len = float(pd.Series(lengths).median())
    else:
        median_ep_len = float("nan")

    return CellResult(
        period=period,
        benchmark=benchmark,
        drawdown_def=defn.name,
        credit_proxy=run.credit_proxy,
        composite_method=run.composite_method,
        n_events=len(events),
        median_close_lead=(
            float(pd.Series(leads_close).median()) if leads_close else float("nan")
        ),
        median_actionable_lead=median_actionable,
        hit_rate=hr,
        fp_day_rate=fp_d,
        fp_short_horizon_rate=fp_short,
        fp_event_window_rate=fp_event_window,
        fp_episode_rate=fp_e,
        precision_day=precision_day,
        recall_event=recall_event,
        alarm_day_ratio=alarm_day_ratio(ro),
        ro_episode_count=len(eps),
        median_ro_episode_length_bdays=median_ep_len,
        disagreement_vs_hyg_rate=disagreement,
        utility_score=utility_score(
            median_lead=median_actionable,
            hit_rate_val=hr,
            fp_episode_rate_val=fp_e,
            k_fp=5.0,
        ),
    )


def run_all_cells(data: BatchData) -> list[CellResult]:
    """Sequential per-cell loop. Spec §15 lock: NO database queries here.

    Per-cell disagreement is computed against HYG's RO series for the same
    (period, benchmark, defn).
    """
    cells: list[CellResult] = []
    runs_by_proxy = {r.credit_proxy: r for r in data.runs}
    hyg_run = runs_by_proxy.get("HYG")
    hyg_ro_full = _ro_signal_from_daily(hyg_run.daily) if hyg_run is not None else None

    for period_name, *_ in PERIOD_SLICES:
        tdays = data.trading_days_by_period.get(period_name, [])
        if not tdays:
            continue
        if hyg_ro_full is not None and not hyg_ro_full.empty:
            hyg_ro_p = hyg_ro_full[
                (hyg_ro_full.index >= tdays[0]) & (hyg_ro_full.index <= tdays[-1])
            ]
        else:
            hyg_ro_p = None
        for bench_name, closes in data.benchmarks.items():
            for defn in DRAWDOWN_DEFS:
                for run in data.runs:
                    cells.append(
                        compute_cell(
                            period_name,
                            bench_name,
                            defn,
                            run,
                            closes,
                            tdays,
                            hyg_ro=hyg_ro_p,
                        )
                    )
    return cells


# ---------------- gate evaluator ----------------


@dataclass(frozen=True)
class GateVerdict:
    composite_method: str
    primary_utility_passed: bool
    primary_lead_passed: bool
    robustness_fp_passed: bool
    robustness_alarm_passed: bool
    robustness_hit_rate_passed: bool
    single_regime_dominance_passed: bool
    overall_pass: bool
    quoted_numbers: dict[str, str]


def _slice_value_primary(
    cells: list[CellResult], period: str, proxy: str, metric: str
) -> float:
    for c in cells:
        if (
            c.period == period
            and c.benchmark == "SPX"
            and c.drawdown_def == "Fast"
            and c.credit_proxy == proxy
        ):
            return getattr(c, metric)
    return float("nan")


def _slice_value_robustness(
    cells: list[CellResult], period: str, proxy: str, metric: str
) -> float:
    vals = [
        getattr(c, metric)
        for c in cells
        if c.period == period and c.credit_proxy == proxy and c.n_events > 0
    ]
    vals = [v for v in vals if not pd.isna(v)]
    if not vals:
        return float("nan")
    return float(pd.Series(vals).median())


def _best_single(
    cells: list[CellResult],
    period: str,
    metric: str,
    method: str = "primary",
) -> float:
    candidates = []
    for proxy in ("HYG", "JNK", "LQD"):
        v = (
            _slice_value_primary(cells, period, proxy, metric)
            if method == "primary"
            else _slice_value_robustness(cells, period, proxy, metric)
        )
        if not pd.isna(v):
            candidates.append(v)
    if not candidates:
        return float("nan")
    return max(candidates)


def evaluate_gate(
    cells: list[CellResult], composite_proxy: str, composite_method: str
) -> GateVerdict:
    periods = [p[0] for p in PERIOD_SLICES]
    util_wins = 0
    for p in periods:
        comp = _slice_value_primary(cells, p, composite_proxy, "utility_score")
        best = _best_single(cells, p, "utility_score")
        if not pd.isna(comp) and not pd.isna(best) and comp > best:
            util_wins += 1
    primary_utility_passed = util_wins >= 3

    lead_breaches = 0
    lead_strong_wins = 0
    improvements: list[tuple[str, float]] = []
    for p in periods:
        comp = _slice_value_primary(cells, p, composite_proxy, "median_actionable_lead")
        best = _best_single(cells, p, "median_actionable_lead")
        if pd.isna(comp) or pd.isna(best):
            continue
        diff = comp - best
        if diff < -0.5:
            lead_breaches += 1
        if diff >= 1.0:
            lead_strong_wins += 1
        improvements.append((p, max(0.0, diff)))
    primary_lead_passed = (lead_breaches == 0) and (lead_strong_wins >= 2)

    def _rob(metric: str, threshold: float, kind: str) -> bool:
        wins = 0
        for p in periods:
            comp = _slice_value_robustness(cells, p, composite_proxy, metric)
            best = _best_single(cells, p, metric, method="robustness")
            if pd.isna(comp) or pd.isna(best):
                continue
            if kind in ("fp", "alarm"):
                if best == 0:
                    if comp <= threshold:
                        wins += 1
                else:
                    rel = (comp - best) / best
                    if rel <= threshold:
                        wins += 1
            elif kind == "hitrate":
                # Asymmetric: composite must not be MORE THAN 5% WORSE than
                # the best single proxy. A composite that BEATS the baseline
                # must NOT fail this gate (`abs(...)` would have done so).
                if comp >= best - threshold:
                    wins += 1
        return wins >= 3

    rob_fp = _rob("fp_episode_rate", 0.10, "fp")
    rob_alarm = _rob("alarm_day_ratio", 0.20, "alarm")
    rob_hit = _rob("hit_rate", 0.05, "hitrate")

    total_improvement = sum(d for _, d in improvements)
    if total_improvement < 1.0:
        single_regime_ok = False
    else:
        max_p_improvement = max((d for _, d in improvements), default=0.0)
        single_regime_ok = max_p_improvement <= 0.5 * total_improvement

    overall = all(
        [
            primary_utility_passed,
            primary_lead_passed,
            rob_fp,
            rob_alarm,
            rob_hit,
            single_regime_ok,
        ]
    )

    quoted = {
        "primary_utility_wins": f"{util_wins}/4",
        "primary_lead_breaches": str(lead_breaches),
        "primary_lead_strong_wins": str(lead_strong_wins),
        "total_improvement_days": f"{total_improvement:.2f}",
        "max_period_improvement_share": (
            f"{max((d for _, d in improvements), default=0.0) / total_improvement:.2f}"
            if total_improvement > 0
            else "n/a"
        ),
    }
    return GateVerdict(
        composite_method=composite_method,
        primary_utility_passed=primary_utility_passed,
        primary_lead_passed=primary_lead_passed,
        robustness_fp_passed=rob_fp,
        robustness_alarm_passed=rob_alarm,
        robustness_hit_rate_passed=rob_hit,
        single_regime_dominance_passed=single_regime_ok,
        overall_pass=overall,
        quoted_numbers=quoted,
    )


# ---------------- report assembly ----------------


def write_report(
    out_path: Path,
    cells: list[CellResult],
    verdicts: list[GateVerdict],
    data: BatchData,
) -> None:
    """Spec §8 step 6 deliverable: full validation report markdown."""
    enabled_benchmarks = list(data.benchmarks.keys())
    n_cells_per_slice = len(enabled_benchmarks) * len(DRAWDOWN_DEFS)
    lines: list[str] = [
        "# VCG composite proxy — drawdown lead-time validation report",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "Spec: docs/superpowers/archive/specs/2026-05-26-vcg-composite-research-design.md",
        "",
        "## 1. Methodology recap",
        "",
        "Per-cell metrics computed against pre-declared:",
        f"- Benchmarks (enabled): {', '.join(enabled_benchmarks) or '(none)'}",
        f"- Drawdown defs: {', '.join(d.name for d in DRAWDOWN_DEFS)}",
        f"- Periods: {', '.join(p[0] for p in PERIOD_SLICES)}",
        "",
        "**Promotion gate aggregation** (lock-in, no author discretion):",
        "- Primary utility + primary lead gates: computed on `(SPX, Fast)` cell only.",
        f"- Robustness FP/alarm/hit-rate gates: median across all {n_cells_per_slice} "
        "enabled benchmark x drawdown_def cells with n_events > 0.",
        "- FP definition: an RO is NOT a false positive iff any event interval "
        "`[peak, trough]` overlaps `[ro_date, ro_date + H_def]` trading days.",
        "- Gate metric: `FP_episode_rate` (NOT `FP_day_rate`). Both reported.",
        "",
        "## 2. Data coverage",
        "",
        "| Benchmark | First bar | Last bar | Bars | Used? | Drop reason |",
        "|---|---|---|---|---|---|",
    ]
    PREFERRED = ("SPX", "NDX", "RUT")
    for ticker in PREFERRED:
        s = data.benchmarks.get(ticker)
        if s is None:
            lines.append(
                f"| {ticker} | -- | -- | 0 | NO | < 4000 bars or absent from "
                "vol_index_daily |"
            )
            continue
        lines.append(
            f"| {ticker} | {min(s.index)} | {max(s.index)} | {len(s)} | YES | -- |"
        )
    lines.extend(["", "## 3. Per-period results matrix", ""])
    by_period: dict[tuple[str, str], list[CellResult]] = {}
    for c in cells:
        by_period.setdefault((c.period, c.drawdown_def), []).append(c)
    for (period, defn_name), period_cells in sorted(by_period.items()):
        lines.append(f"### {period} -- {defn_name}")
        lines.append("")
        lines.append(
            "| Proxy | Method | Bench | N | Med Act Lead | Med Close Lead | "
            "Hit | FP day | FP ep | FP short | Prec | Recall | Alarm % | "
            "RO eps | Med EpLen | Disagr | Utility |"
        )
        lines.append("|" + "---|" * 17)
        for c in sorted(period_cells, key=lambda r: (r.credit_proxy, r.benchmark)):
            lines.append(
                f"| {c.credit_proxy} | {c.composite_method} | {c.benchmark} | "
                f"{c.n_events} | {c.median_actionable_lead:.2f} | "
                f"{c.median_close_lead:.2f} | {c.hit_rate:.2%} | "
                f"{c.fp_day_rate:.2%} | {c.fp_episode_rate:.2%} | "
                f"{c.fp_short_horizon_rate:.2%} | {c.precision_day:.2%} | "
                f"{c.recall_event:.2%} | {c.alarm_day_ratio:.2%} | "
                f"{c.ro_episode_count} | "
                f"{c.median_ro_episode_length_bdays:.1f} | "
                f"{c.disagreement_vs_hyg_rate:.2%} | "
                f"{c.utility_score:.3f} |"
            )
        lines.append("")

    lines.append("## 4. Disagreement diagnostic")
    lines.append("")
    lines.append(
        "Days where each composite variant's RO signal disagrees with the "
        "HYG single-proxy baseline. Aggregated as median "
        "`disagreement_vs_hyg_rate` over all enabled cells, per variant."
    )
    lines.append("")
    lines.append("| Method | Median disagreement % |")
    lines.append("|---|---|")
    by_method: dict[str, list[float]] = {}
    for c in cells:
        if not pd.isna(c.disagreement_vs_hyg_rate):
            by_method.setdefault(c.composite_method, []).append(
                c.disagreement_vs_hyg_rate
            )
    for method, rates in sorted(by_method.items()):
        med = float(pd.Series(rates).median()) if rates else float("nan")
        lines.append(f"| {method} | {med:.2%} |")
    lines.append("")

    lines.append("## 5. Promotion gate verdicts")
    lines.append("")
    lines.append(
        "| Method | Primary util | Primary lead | Robust FP | Robust alarm | "
        "Robust hit | Regime dominance | **Overall** |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")

    def _mark(b: bool) -> str:
        return "PASS" if b else "FAIL"

    for v in verdicts:
        lines.append(
            f"| {v.composite_method} | {_mark(v.primary_utility_passed)} | "
            f"{_mark(v.primary_lead_passed)} | "
            f"{_mark(v.robustness_fp_passed)} | "
            f"{_mark(v.robustness_alarm_passed)} | "
            f"{_mark(v.robustness_hit_rate_passed)} | "
            f"{_mark(v.single_regime_dominance_passed)} | "
            f"**{_mark(v.overall_pass)}** |"
        )
    lines.append("")
    lines.append("## 6. Quoted numbers")
    lines.append("")
    for v in verdicts:
        lines.append(f"### {v.composite_method}")
        for k, val in v.quoted_numbers.items():
            lines.append(f"- {k}: {val}")
        lines.append("")

    lines.append("## 7. Run inventory + artifact appendix")
    lines.append("")
    lines.append(
        "| run_id | indicator | composite_version | composite_method | "
        "credit_proxy | run_scope |"
    )
    lines.append("|---|---|---|---|---|---|")
    for run in sorted(data.runs, key=lambda r: r.run_id):
        lines.append(
            f"| {run.run_id} | vcg | {run.composite_version} | "
            f"{run.composite_method} | {run.credit_proxy} | research |"
        )
    lines.append("")
    lines.append("### Query templates (for replay)")
    lines.append("")
    lines.append("```sql")
    lines.append("-- Production v1 HYG row (Hard Guarantee #2 default selection)")
    lines.append("SELECT * FROM uw_scan.regime_backtest_runs")
    lines.append(" WHERE indicator='vcg' AND run_scope='production'")
    lines.append("   AND composite_version='1' AND credit_proxy='HYG'")
    lines.append("   AND composite_method='single_proxy' AND completed_at IS NOT NULL")
    lines.append(" ORDER BY created_at DESC LIMIT 1;")
    lines.append("")
    lines.append("-- All research candidate rows (composite)")
    lines.append("SELECT id, composite_version, composite_method, credit_proxy,")
    lines.append("       summary->'extras'->>'weight_artifact_sha256' AS sha")
    lines.append("  FROM uw_scan.regime_backtest_runs")
    lines.append(" WHERE indicator='vcg' AND run_scope='research'")
    lines.append("   AND composite_method <> 'single_proxy'")
    lines.append(" ORDER BY created_at DESC;")
    lines.append("```")
    out_path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        default="docs/research/regime/vcg-composite-validation-2026-05-26.md",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    settings = Settings.from_env()
    data = batch_load_all(settings)
    cells = run_all_cells(data)
    composite_proxies = [
        ("COMPOSITE_RP3", "risk_parity_3"),
        ("COMPOSITE_RP_HYJK", "risk_parity_hyjk"),
        ("COMPOSITE_HY_MINUS_IG", "hy_minus_ig_spread"),
        ("COMPOSITE_EQ3", "equal_weight_3"),
    ]
    verdicts = [evaluate_gate(cells, p, m) for p, m in composite_proxies]
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(out_path, cells, verdicts, data)
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
