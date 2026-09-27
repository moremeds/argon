#!/usr/bin/env python
"""Sector RS breadth probe — spec 2026-09-26 §6, pre-registered.

H1. For a gics group on date t, C = rs_1m(t) > 0 AND breadth_1m(t) in the
bottom tercile of that group's own history. Then P(rs_1m(t+21) < 0 | C)
exceeds the unconditional P(rs_1m(t+21) < 0) for that group.

Method, fixed before any data is read:
- Observations: per group, every STEP-th (21st) row of its session series.
  They do not overlap, and t+21 is the next observation on the same grid.
  A pair is dropped when t or t+21 is degraded, or when rs_1m(t), rs_1m(t+21)
  or the conditioning breadth is NULL.
- Tercile: expanding. The cut at t is the 1/3 quantile (inclusive method) of
  the group's non-degraded DAILY breadth values strictly before t. An
  observation with fewer than MIN_HISTORY past values is not eligible for C
  or for the baseline.
- Baseline: P(rs_1m(t+21) < 0) over the same eligible observations.
- Bootstrap: 95% CI on (p_C − p_base), resampling eligible pairs with
  replacement (BOOT_B, SEED). The pooled resample pools pairs across groups
  and ignores group clustering; that is stated in VERDICT.md.
- Effective start: per group, the first non-degraded row from which every
  full COVERAGE_WINDOW (252-session) window is >= COVERAGE_FLOOR (95%)
  non-degraded. Earlier rows are dropped; groups that never qualify are
  excluded and reported.
- Holdout: in_sample as_of < 2019-01-01; oos as_of >= 2019-01-01. XLC
  (Communication Services, first bar 2018-06-19) is OOS-only.
- Variants: breadth_1m (primary: it decides PASS/FAIL) and breadth_3m
  (pre-registered in the spec, reported with its own gate line).
- Gate, primary variant, OOS: pooled diff > 0 with CI low > 0, AND no group
  whose diff is below −(its own CI half-width).

Reads gics rows only (spec §6). Both kinds carry TODAY's membership over
history (survivorship-biased); VERDICT.md states it.

Writes docs/research/<run-date>-sector-rs-breadth/{VERDICT.md, results.csv,
observations.csv} and prints the reproduce command.

Reproduce:
    uv run python scripts/research/sector_rs_breadth_probe.py
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import psycopg

HOLDOUT = date(2019, 1, 1)
COVERAGE_WINDOW = 252
COVERAGE_FLOOR = 0.95
STEP = 21
MIN_HISTORY = 63
BOOT_B = 5000
SEED = 20260926
VARIANTS = ("breadth_1m", "breadth_3m")
PRIMARY = "breadth_1m"


@dataclass(frozen=True)
class DailyRow:
    group_key: str
    as_of: date
    rs_1m: float | None
    breadth_1m: float | None
    breadth_3m: float | None
    degraded: bool


@dataclass(frozen=True)
class Pair:
    group_key: str
    as_of: date
    variant: str
    breadth: float
    cut: float
    cond: bool
    outcome_neg: bool


@dataclass(frozen=True)
class Result:
    variant: str
    split: str
    group: str
    n: int
    n_c: int
    p_c: float | None
    p_base: float | None
    diff: float | None
    ci_lo: float | None
    ci_hi: float | None
    effective_start: date | None = None


def effective_start(rows: list[DailyRow]) -> date | None:
    """First non-degraded row from which every full 252-session window is >= 95% clean.

    `rows`: one group, ascending by as_of. None when the group is shorter than
    one window or its last full window already fails, i.e. it never qualifies.
    Walks backward from the last full window and stops at the first failing
    one, so the O(n) prefix sum is the whole cost.
    """
    n = len(rows)
    if n < COVERAGE_WINDOW:
        return None
    clean = [0] * (n + 1)
    for i, r in enumerate(rows):
        clean[i + 1] = clean[i] + (not r.degraded)
    start: int | None = None
    for i in range(n - COVERAGE_WINDOW, -1, -1):
        if (clean[i + COVERAGE_WINDOW] - clean[i]) / COVERAGE_WINDOW < COVERAGE_FLOOR:
            break
        if not rows[i].degraded:
            start = i
    return None if start is None else rows[start].as_of


def monthly_pairs(rows: list[DailyRow], variant: str) -> list[Pair]:
    """One group's rows, ascending by as_of → its eligible (t, t+21) pairs."""
    out: list[Pair] = []
    past: list[float] = []
    for i, t in enumerate(rows):
        if i % STEP == 0 and i + STEP < len(rows) and len(past) >= MIN_HISTORY:
            nxt = rows[i + STEP]
            b = getattr(t, variant)
            if (
                not t.degraded
                and not nxt.degraded
                and b is not None
                and t.rs_1m is not None
                and nxt.rs_1m is not None
            ):
                cut = statistics.quantiles(past, n=3, method="inclusive")[0]
                out.append(
                    Pair(
                        t.group_key,
                        t.as_of,
                        variant,
                        b,
                        cut,
                        cond=t.rs_1m > 0 and b <= cut,
                        outcome_neg=nxt.rs_1m < 0,
                    )
                )
        v = getattr(t, variant)
        if not t.degraded and v is not None:
            past.append(v)
    return out


def stats(
    pairs: list[Pair],
) -> tuple[int, int, float | None, float | None, float | None]:
    """(n, n_C, p_C, p_base, p_C − p_base). p_C/diff are None when C never fired."""
    n = len(pairs)
    cond = [p for p in pairs if p.cond]
    p_base = sum(p.outcome_neg for p in pairs) / n if n else None
    if not cond or p_base is None:
        return n, len(cond), None, p_base, None
    p_c = sum(p.outcome_neg for p in cond) / len(cond)
    return n, len(cond), p_c, p_base, p_c - p_base


def bootstrap_ci(
    pairs: list[Pair], *, b: int = BOOT_B, seed: int = SEED
) -> tuple[float | None, float | None]:
    """Percentile 95% CI of p_C − p_base; (None, None) when C is too rare to resample."""
    if not pairs:
        return None, None
    rng = random.Random(seed)
    diffs: list[float] = []
    n = len(pairs)
    for _ in range(b):
        d = stats([pairs[rng.randrange(n)] for _ in range(n)])[4]
        if d is not None:
            diffs.append(d)
    if len(diffs) < b // 2:
        return None, None
    diffs.sort()
    return diffs[int(0.025 * (len(diffs) - 1))], diffs[int(0.975 * (len(diffs) - 1))]


def _result(
    variant: str,
    split: str,
    group: str,
    pairs: list[Pair],
    b: int,
    start: date | None = None,
) -> Result:
    n, n_c, p_c, p_base, diff = stats(pairs)
    lo, hi = bootstrap_ci(pairs, b=b)
    return Result(variant, split, group, n, n_c, p_c, p_base, diff, lo, hi, start)


def evaluate(
    pairs_by_group: dict[str, list[Pair]],
    variant: str,
    *,
    starts: dict[str, date | None] | None = None,
    b: int = BOOT_B,
) -> list[Result]:
    starts = starts or {}
    splits = (
        ("all", lambda d: True),
        ("in_sample", lambda d: d < HOLDOUT),
        ("oos", lambda d: d >= HOLDOUT),
    )
    out: list[Result] = []
    for split, keep in splits:
        pooled: list[Pair] = []
        for g in sorted(pairs_by_group):
            ps = [p for p in pairs_by_group[g] if keep(p.as_of)]
            pooled.extend(ps)
            out.append(_result(variant, split, g, ps, b, starts.get(g)))
        out.append(_result(variant, split, "POOLED", pooled, b))
    return out


def gate(results: list[Result], variant: str) -> tuple[bool, list[str]]:
    oos = [r for r in results if r.variant == variant and r.split == "oos"]
    pooled = next((r for r in oos if r.group == "POOLED"), None)
    reasons: list[str] = []
    if (
        pooled is None
        or pooled.diff is None
        or pooled.ci_lo is None
        or pooled.ci_hi is None
    ):
        reasons.append("pooled OOS: C never fired or too rare to bootstrap")
    elif not (pooled.diff > 0 and pooled.ci_lo > 0):
        reasons.append(
            f"pooled OOS diff {pooled.diff:+.3f}, CI [{pooled.ci_lo:+.3f}, "
            f"{pooled.ci_hi:+.3f}] does not exclude zero on the positive side"
        )
    for r in oos:
        if r.group == "POOLED" or r.diff is None or r.ci_lo is None or r.ci_hi is None:
            continue
        half = (r.ci_hi - r.ci_lo) / 2
        if r.diff < -half:
            reasons.append(
                f"{r.group}: OOS diff {r.diff:+.3f} below −half-width {half:.3f}"
            )
    return (not reasons), reasons


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{x:+.3f}"


def render_verdict(
    results: list[Result],
    gates: dict[str, tuple[bool, list[str]]],
    *,
    coverage: dict[str, tuple[date, date | None, int]],
    db_label: str,
    n_rows: int,
    reproduce: str,
) -> str:
    primary_pass, primary_why = gates[PRIMARY]
    lines = [
        "# Sector RS breadth probe — VERDICT",
        "",
        f"**Verdict: {'PASS' if primary_pass else 'FAIL'}** (primary variant `{PRIMARY}`, "
        "gate of spec 2026-09-26 §6).",
        "",
        f"- Source: `uw_scan.sector_rs_daily` gics rows on {db_label} ({n_rows} rows read).",
        f"- Reproduce: `{reproduce}`",
        f"- Grid: every {STEP}th session per group; tercile expanding over past daily "
        f"breadth (min {MIN_HISTORY}); bootstrap B={BOOT_B}, seed {SEED}; holdout {HOLDOUT}.",
        "- The pooled bootstrap resamples pairs across groups and ignores group clustering.",
        "- Breadth uses TODAY's S&P 500 membership over every session, and delisted names "
        "have no adjusted bars, so former members are absent: survivorship-biased by construction.",
        "",
        "## Effective sample start per group",
        "",
        f"First non-degraded row from which every {COVERAGE_WINDOW}-session window is "
        f">= {COVERAGE_FLOOR:.0%} non-degraded; earlier rows are excluded.",
        "",
        "| group | first row | effective start | rows excluded | note |",
        "|---|---|---|---|---|",
    ]
    for g, (first, start, excluded) in sorted(coverage.items()):
        if start is None:
            note = "excluded: never reaches the coverage floor"
        elif start >= HOLDOUT:
            note = "OOS-only (no in-sample)"
        else:
            note = ""
        lines.append(f"| {g} | {first} | {start or '—'} | {excluded} | {note} |")
    lines.append("")
    for variant in VARIANTS:
        ok, why = gates[variant]
        lines += [
            f"## `{variant}` — gate {'PASS' if ok else 'FAIL'}"
            + (
                " (pre-registered secondary; does not change the verdict)"
                if variant != PRIMARY
                else ""
            ),
            "",
            *(f"- {w}" for w in why),
            "",
            "| split | group | n | n_C | p_C | p_base | diff | CI 95% |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in results:
            if r.variant != variant:
                continue
            lines.append(
                f"| {r.split} | {r.group} | {r.n} | {r.n_c} | {_fmt(r.p_c)} | "
                f"{_fmt(r.p_base)} | {_fmt(r.diff)} | [{_fmt(r.ci_lo)}, {_fmt(r.ci_hi)}] |"
            )
        lines.append("")
    return "\n".join(lines)


def _load(conn: psycopg.Connection, schema: str) -> dict[str, list[DailyRow]]:
    by_group: dict[str, list[DailyRow]] = {}
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT group_key, as_of, rs_1m, breadth_1m, breadth_3m, degraded
                  FROM {schema}.sector_rs_daily
                 WHERE group_kind = 'gics'
                 ORDER BY group_key, as_of"""
        )
        for row in cur.fetchall():
            by_group.setdefault(row[0], []).append(DailyRow(*row))
    return by_group


def main() -> int:
    from uw_scan.config import Settings

    ap = argparse.ArgumentParser(description="Sector RS breadth probe (spec §6)")
    ap.add_argument("--run-date", type=date.fromisoformat, default=date.today())
    ap.add_argument("--out-root", default="docs/research")
    ap.add_argument("--boot", type=int, default=BOOT_B)
    args = ap.parse_args()

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        rows = _load(conn, settings.db_schema)
    n_rows = sum(len(v) for v in rows.values())
    db_label = f"{settings.db_host}/{settings.db_name}"
    coverage: dict[str, tuple[date, date | None, int]] = {}
    kept: dict[str, list[DailyRow]] = {}
    for g, rs in rows.items():
        start = effective_start(rs)
        kept[g] = [r for r in rs if start is not None and r.as_of >= start]
        coverage[g] = (rs[0].as_of, start, len(rs) - len(kept[g]))
    starts = {g: c[1] for g, c in coverage.items()}

    results: list[Result] = []
    gates: dict[str, tuple[bool, list[str]]] = {}
    all_pairs: list[Pair] = []
    for variant in VARIANTS:
        pairs = {g: monthly_pairs(rs, variant) for g, rs in kept.items()}
        all_pairs.extend(p for ps in pairs.values() for p in ps)
        res = evaluate(pairs, variant, starts=starts, b=args.boot)
        results.extend(res)
        gates[variant] = gate(res, variant)

    out = Path(args.out_root) / f"{args.run_date.isoformat()}-sector-rs-breadth"
    out.mkdir(parents=True, exist_ok=True)
    reproduce = (
        "uv run python scripts/research/sector_rs_breadth_probe.py "
        f"--run-date {args.run_date.isoformat()} --boot {args.boot}"
    )
    with (out / "results.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(Result.__dataclass_fields__))
        w.writeheader()
        w.writerows(asdict(r) for r in results)
    with (out / "observations.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(Pair.__dataclass_fields__))
        w.writeheader()
        w.writerows(asdict(p) for p in all_pairs)
    (out / "VERDICT.md").write_text(
        render_verdict(
            results,
            gates,
            coverage=coverage,
            db_label=db_label,
            n_rows=n_rows,
            reproduce=reproduce,
        )
        + "\n"
    )
    print(f"wrote {out}/VERDICT.md, results.csv, observations.csv")
    print(f"reproduce: {reproduce}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
