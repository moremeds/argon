"""Does a name's own fundamental deterioration precede its own drawdown?

    uv run python scripts/research/fundamental_timeseries_test.py

THE QUESTION THIS ASKS, AND WHY IT IS NOT THE ONE ALREADY ANSWERED
------------------------------------------------------------------
`fundamental_signal_validation.py` measures a CROSS-SECTIONAL rank IC: given 245
names on one date, does the composite order their forward returns? That question
needs a wide panel, which is why it was unanswerable on the 25-name cohort.

This measures a TIME-SERIES IC: within ONE name, across ITS OWN history, does the
composite falling below that name's own norm precede that name's own weakness? It
never forms a cross-section, so the thin-panel problem that dominated three
revisions of the cross-sectional verdict does not apply here at all — this test
works at any universe width, including 25.

It is also the question the product rests on. The card is a per-ticker analyst:
subscores, an anchor band, a bear case and an invalidation level for ONE company.
Nothing on it orders two tickers against each other.

METHOD
------
- Features and the `spearman` implementation are IMPORTED from the cross-sectional
  validation, not reimplemented. A test that rewrites the metric tests the
  rewrite, not the claim.
- Statements come from Postgres (`fundamental_statement_obs`), reshaped into the
  exact dict the validated `build_features` already consumes. Reading the durable
  store rather than the research cache also proves the DB round-trip preserves
  everything the research path needs.
- Z-scores are WITHIN-TICKER and EXPANDING: at period i, a feature is scored
  against that ticker's own history up to and including i. No future data.
- Outcomes are reported RAW and DE-MARKETED. De-marketing subtracts the mean
  outcome across all tickers sharing the knowledge quarter. This matters more than
  it looks: fundamentals deteriorate broadly in recessions, so a raw time-series
  result would largely be "everything falls together" — macro, not name selection.
- Two outcomes: forward return, and forward max drawdown (worst cumulative return
  from entry within the window). The hypothesis names DRAWDOWN specifically, and a
  signal can predict downside without predicting the mean.
- Two signals: LEVEL (is this name weak versus its own norm) and CHANGE (has it
  deteriorated over four quarters). "Deterioration precedes drawdown" is the
  change signal; level is the control that says whether change adds anything.

READING THE T-STATS
-------------------
The unit of observation is the TICKER: each contributes one time-series IC, and
the t-stat runs across tickers. For the RAW outcome those ICs share a common macro
driver, so its t-stat is inflated and should be read as directional only. The
de-marketed residuals are far less correlated, so its t-stat is the defensible one.
Lead with de-marketed.
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fundamental_signal_validation as V  # noqa: E402

from uw_scan.config import Settings  # noqa: E402

OUT_DIR = Path("docs/research/2026-08-12-fundamental-timeseries-test")

STATEMENT_KEY = {
    "income": "income-statements",
    "balance": "balance-sheets",
    "cash_flow": "cash-flows",
}

# Quarters of a ticker's own history required before its z-score means anything.
# Below ~12 the score is dominated by its own sample, and the TTM features need
# 8 quarters of warmup before they even exist.
MIN_HISTORY = 12

# Observations required before a ticker contributes a time-series IC. A Spearman
# on 24 points still carries SE ~0.21, so each ticker's IC is individually noisy —
# the aggregate is what carries the claim, and this floor keeps the aggregate from
# being an average of near-noise.
MIN_OBS = 24

# Four quarters. The change signal must span a full fiscal year or it measures
# seasonality in the filer's own business rather than deterioration.
CHANGE_LAG = 4

HORIZONS = {"1q": 63, "2q": 126}


# ---------- load ----------


def load_from_db() -> dict[str, Any]:
    """Reshape `fundamental_statement_obs` into the cache dict `build_features` eats.

    Newest observation wins per (ticker, period, statement): a restatement is a
    new immutable row, so "current" means the highest obs_id, never an edit.
    """
    settings = Settings.from_env()
    out: dict[str, Any] = defaultdict(
        lambda: {
            "income-statements": {},
            "balance-sheets": {},
            "cash-flows": {},
            "filing_dates": {},
        }
    )
    sql = f"""
        SELECT DISTINCT ON (ticker, period_end, statement)
               ticker, period_end, statement, raw_jsonb, filing_published_at
          FROM {settings.db_schema}.fundamental_statement_obs
         WHERE period_type = 'quarterly'
         ORDER BY ticker, period_end, statement, obs_id DESC
    """
    with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute(sql)
        for ticker, period_end, statement, raw, filed in cur.fetchall():
            key = STATEMENT_KEY.get(statement)
            if key is None:
                continue
            period = period_end.isoformat()
            out[ticker][key][period] = raw
            if filed:
                out[ticker]["filing_dates"][period] = filed.isoformat()
    return dict(out)


def knowledge_date(uw: dict, t: str, period: str) -> date:
    fd = uw[t]["filing_dates"].get(period)
    if fd:
        return date.fromisoformat(fd[:10])
    return date.fromisoformat(period[:10]) + timedelta(days=V.FALLBACK_LAG_DAYS)


def _entry_index(px: list[tuple[date, float]], know: date) -> int | None:
    """First index strictly after the knowledge date. Same rule as the
    cross-sectional test, so entry timing cannot differ between them."""
    lo, hi = 0, len(px)
    while lo < hi:
        mid = (lo + hi) // 2
        if px[mid][0] > know:
            hi = mid
        else:
            lo = mid + 1
    return lo if lo < len(px) else None


def forward_outcomes(
    px: list[tuple[date, float]], know: date, horizon: int
) -> tuple[float | None, float | None]:
    """(forward return, forward max drawdown) from the first close after `know`.

    Max drawdown is the worst cumulative return from ENTRY within the window, not
    peak-to-trough. That is the quantity a holder actually experiences after
    acting on the signal, and peak-to-trough would credit the signal for declines
    from a high it never told you to sell at.
    """
    i = _entry_index(px, know)
    if i is None or i + horizon >= len(px):
        return (None, None)
    p0 = px[i][1]
    if p0 <= 0:
        return (None, None)
    path = [px[j][1] / p0 - 1 for j in range(i, i + horizon + 1)]
    return (path[-1], min(path))


# ---------- within-ticker scoring ----------


def expanding_z(values: list[float | None]) -> list[float | None]:
    """Z-score each point against this ticker's own history up to and including it.

    Expanding rather than full-sample: a full-sample mean would let 2026 data set
    the norm a 2008 observation is scored against, which is look-ahead wearing a
    statistician's hat.
    """
    out: list[float | None] = []
    seen: list[float] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        seen.append(v)
        if len(seen) < MIN_HISTORY:
            out.append(None)
            continue
        mu = sum(seen) / len(seen)
        sd = math.sqrt(sum((x - mu) ** 2 for x in seen) / len(seen))
        out.append(((v - mu) / sd) if sd else 0.0)
    return out


def ticker_series(
    feats: dict[str, dict[str, float | None]], periods: list[str]
) -> list[float | None]:
    """Within-ticker composite: mean of available expanding z-scores.

    Requires 4 of 7 features present, the same floor the cross-sectional
    composite uses — so the two differ ONLY in what they standardize against.
    """
    zs = {f: expanding_z([feats[p].get(f) for p in periods]) for f in V.FEATURES}
    out: list[float | None] = []
    for i in range(len(periods)):
        got = [zs[f][i] for f in V.FEATURES if zs[f][i] is not None]
        out.append(sum(got) / len(got) if len(got) >= 4 else None)
    return out


# ---------- main ----------


def main() -> int:
    print("1. loading statements from Postgres ...", flush=True)
    uw = load_from_db()
    print(f"   {len(uw)} tickers")

    feats = V.build_features(uw)
    prices = V.load_prices(sorted(uw))
    print(f"   {len(prices)} tickers with lake prices")

    # Per ticker: an ordered observation list. `bucket` groups by knowledge
    # quarter so de-marketing compares names that knew things at the same time —
    # the same fix the cross-sectional test needed for its cross-sections.
    rows: dict[str, list[dict[str, Any]]] = {}
    for t, pf in feats.items():
        px = prices.get(t)
        if not px:
            continue
        periods = sorted(pf)
        comp = ticker_series(pf, periods)
        obs: list[dict[str, Any]] = []
        for i, p in enumerate(periods):
            if comp[i] is None:
                continue
            know = knowledge_date(uw, t, p)
            entry = {"period": p, "know": know, "level": comp[i]}
            entry["change"] = (
                comp[i] - comp[i - CHANGE_LAG]
                if i >= CHANGE_LAG and comp[i - CHANGE_LAG] is not None
                else None
            )
            entry["bucket"] = f"{know.year}Q{(know.month - 1) // 3 + 1}"
            for h, days in HORIZONS.items():
                ret, dd = forward_outcomes(px, know, days)
                entry[f"ret_{h}"], entry[f"dd_{h}"] = ret, dd
            obs.append(entry)
        if len(obs) >= MIN_OBS:
            rows[t] = obs
    print(f"   {len(rows)} tickers with >= {MIN_OBS} scored observations")

    # De-market: subtract the mean outcome across every ticker in the same
    # knowledge quarter. Without this the test largely measures "fundamentals and
    # prices both fall in recessions", which is macro, not name selection.
    by_bucket: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for obs in rows.values():
        for e in obs:
            for h in HORIZONS:
                for kind in ("ret", "dd"):
                    v = e[f"{kind}_{h}"]
                    if v is not None:
                        by_bucket[e["bucket"]][f"{kind}_{h}"].append(v)
    means = {
        b: {k: sum(v) / len(v) for k, v in d.items() if v} for b, d in by_bucket.items()
    }
    for obs in rows.values():
        for e in obs:
            for h in HORIZONS:
                for kind in ("ret", "dd"):
                    v, mu = (
                        e[f"{kind}_{h}"],
                        means.get(e["bucket"], {}).get(f"{kind}_{h}"),
                    )
                    e[f"{kind}_{h}_dm"] = (v - mu) if None not in (v, mu) else None

    # Per-ticker time-series IC, then aggregate across tickers.
    results: dict[str, Any] = {}
    for signal in ("level", "change"):
        for h in HORIZONS:
            for outcome in (f"ret_{h}", f"dd_{h}", f"ret_{h}_dm", f"dd_{h}_dm"):
                ics, per_ticker = [], {}
                for t, obs in rows.items():
                    xs = [
                        (e[signal], e[outcome])
                        for e in obs
                        if e.get(signal) is not None and e.get(outcome) is not None
                    ]
                    if len(xs) < MIN_OBS:
                        continue
                    ic = V.spearman([a for a, _ in xs], [b for _, b in xs])
                    if ic is not None:
                        ics.append(ic)
                        per_ticker[t] = round(ic, 4)
                # SE straight from the IC distribution, never recovered as
                # mean/t: that division degenerates exactly when the mean is
                # near zero, which is precisely the null case whose detection
                # floor matters most.
                se = None
                if len(ics) > 1:
                    mu = sum(ics) / len(ics)
                    var = sum((x - mu) ** 2 for x in ics) / (len(ics) - 1)
                    se = math.sqrt(var / len(ics))
                results[f"{signal}|{outcome}"] = {
                    **V.summarize(ics),
                    "standard_error": se,
                    "detection_floor": (2 * se) if se is not None else None,
                    "n_tickers": len(ics),
                    "positive_share": (
                        round(sum(1 for i in ics if i > 0) / len(ics), 3)
                        if ics
                        else None
                    ),
                    "per_ticker": per_ticker,
                }

    # Multiple comparisons. 2 signals x 2 horizons x 4 outcomes = 16 hypotheses on
    # one dataset; at alpha 0.05 that is ~0.8 false positives expected before any
    # real effect exists. Reporting the best t without this correction is how a
    # null result gets published as a finding, so the adjustment is persisted in
    # the artifact rather than left to the reader.
    #
    # Normal approximation for the p-value: df = n_tickers - 1 is ~249 here, where
    # the t and normal tails agree to well past the third decimal.
    tested = [(k, r) for k, r in results.items() if r.get("t_stat") is not None]
    for _, r in tested:
        r["p_value"] = math.erfc(abs(r["t_stat"]) / math.sqrt(2))
    ordered = sorted(tested, key=lambda kv: kv[1]["p_value"])
    m = len(ordered)
    for rank, (_, r) in enumerate(ordered, start=1):
        r["bh_threshold"] = 0.05 * rank / m
        r["bonferroni_threshold"] = 0.05 / m
        r["survives_bonferroni"] = r["p_value"] < 0.05 / m
    # Benjamini-Hochberg: largest rank whose p is under its threshold; everything
    # at or below that rank is a discovery.
    cutoff = 0
    for rank, (_, r) in enumerate(ordered, start=1):
        if r["p_value"] <= r["bh_threshold"]:
            cutoff = rank
    for rank, (_, r) in enumerate(ordered, start=1):
        r["survives_bh"] = rank <= cutoff

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "gates": {
            "min_history": MIN_HISTORY,
            "min_obs": MIN_OBS,
            "change_lag": CHANGE_LAG,
        },
        "tickers_scored": len(rows),
        "observations": sum(len(o) for o in rows.values()),
        "reproduce": "uv run python scripts/research/fundamental_timeseries_test.py",
        "results": results,
    }
    (OUT_DIR / "timeseries.json").write_text(json.dumps(payload, indent=1))

    lines = [
        "# Fundamental time-series test — within-ticker deterioration vs own drawdown",
        "",
        f"{len(rows)} tickers, {payload['observations']:,} scored observations. "
        f"Unit of observation is the ticker; t-stat runs across tickers.",
        "",
        "`_dm` = de-marketed (knowledge-quarter mean removed). **Lead with those** —",
        "the raw t-stats share a macro driver across tickers and are inflated.",
        "",
        f"16 hypotheses were tested on one dataset. Bonferroni threshold is "
        f"p < {0.05 / max(len(tested), 1):.4f} (|t| > ~3.0); the "
        "Benjamini-Hochberg column is the less conservative check.",
        "",
        "| signal | outcome | mean IC | t | p | tickers | share > 0 | BH | Bonf |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    for key, r in results.items():
        sig, out = key.split("|")
        ic = "na" if r.get("mean_ic") is None else f"{r['mean_ic']:+.4f}"
        t = "na" if r.get("t_stat") is None else f"{r['t_stat']:+.2f}"
        p = "na" if r.get("p_value") is None else f"{r['p_value']:.4f}"
        share = "na" if r["positive_share"] is None else f"{r['positive_share']}"
        bh = "pass" if r.get("survives_bh") else "—"
        bonf = "pass" if r.get("survives_bonferroni") else "—"
        lines.append(
            f"| {sig} | {out} | {ic} | {t} | {p} | "
            f"{r['n_tickers']} | {share} | {bh} | {bonf} |"
        )
    (OUT_DIR / "results.md").write_text("\n".join(lines) + "\n")

    print(f"\n2. wrote {OUT_DIR}/timeseries.json and results.md\n")
    for key, r in results.items():
        if r.get("mean_ic") is None:
            continue
        print(
            f"   {key:28} IC {r['mean_ic']:+.4f}  t {r['t_stat']:+6.2f}  "
            f"n {r['n_tickers']:3}  >0 {r['positive_share']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
