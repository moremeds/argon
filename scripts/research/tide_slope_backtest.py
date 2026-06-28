"""Backtest: does the EOD market-tide slope/sentiment predict SPY forward return?

Signal is known at session close (tide bars captured through ~16:10 ET), so the
tradeable forward return is close[d] → close[d+1] (and d+3) — NO look-ahead.

Joins market_tide_sentiment_daily (DB) to SPY daily closes (Apex /bars, the
directive-aligned bars source). Reports mean forward return by state, directional
hit rate, and slope↔return correlation, plus the volume-confirmed subset.

⚠ Sample is ~30 sessions (UW market-tide lookback cap) — a FEASIBILITY PROBE,
not a verdict. Nothing here clears significance; the EOD table accrues daily for
a real test later. Full per-session trace is written so the figures reproduce.

Reproduce:
  uv run python scripts/research/tide_slope_backtest.py
Outputs:
  docs/research/tide-slope/results.csv   (every session + sentiment + fwd return)
  docs/research/tide-slope/summary.md    (the stats + this caveat)
"""

from __future__ import annotations

import csv
import os
from datetime import date, timedelta

import httpx
import psycopg

from uw_scan.config import Settings

APEX = os.environ.get("APEX_API_URL", "http://100.66.147.98:8322").rstrip("/")
OUT_DIR = "docs/research/tide-slope"


def _spy_daily_closes(lo: date, hi: date) -> dict[date, float]:
    r = httpx.get(
        f"{APEX}/bars/SPY",
        params={"timeframe": "1d", "start": lo.isoformat(), "end": hi.isoformat()},
        timeout=20,
    )
    r.raise_for_status()
    out: dict[date, float] = {}
    for b in r.json().get("bars", []):
        t, c = b.get("time"), b.get("close")
        if t and c is not None:
            out[date.fromisoformat(t[:10])] = float(c)
    return out


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / (sxx**0.5 * syy**0.5)


def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    r = [0.0] * len(v)
    i = 0
    while i < len(v):
        j = i
        while j + 1 < len(v) and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return _pearson(_ranks(xs), _ranks(ys))


def _mean(v: list[float]) -> float | None:
    return sum(v) / len(v) if v else None


def main() -> int:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT data_date, state, magnitude, driver, momentum, "
            f"spread::float8, session_slope::float8, recent_slope::float8, "
            f"trend_strength::float8, volume_confirms, bars "
            f"FROM {settings.db_schema}.market_tide_sentiment_daily ORDER BY data_date"
        )
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
    conn.close()
    if not rows:
        print("no sentiment rows — run the sentiment backfill first")
        return 1

    lo = rows[0]["data_date"] - timedelta(days=3)
    hi = rows[-1]["data_date"] + timedelta(days=8)
    closes = _spy_daily_closes(lo, hi)
    trading_days = sorted(closes)

    def fwd(d: date, n: int) -> float | None:
        later = [td for td in trading_days if td > d]
        if d not in closes or len(later) < n:
            return None
        return closes[later[n - 1]] / closes[d] - 1.0

    recs = []
    for r in rows:
        d = r["data_date"]
        recs.append(
            {
                **r,
                "spy_close": closes.get(d),
                "fwd_ret_1d": fwd(d, 1),
                "fwd_ret_3d": fwd(d, 3),
            }
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(f"{OUT_DIR}/results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
        w.writeheader()
        w.writerows(recs)

    # ── analysis on rows with a 1d forward return ──
    usable = [r for r in recs if r["fwd_ret_1d"] is not None]
    by_state: dict[str, list[float]] = {}
    for r in usable:
        by_state.setdefault(r["state"], []).append(r["fwd_ret_1d"])

    def hit_rate(rs: list[dict], contrarian: bool = False) -> tuple[int, int]:
        hits = tot = 0
        for r in rs:
            pred = {"BULLISH": 1, "BEARISH": -1}.get(r["state"], 0)
            if pred == 0:
                continue
            if contrarian:
                pred = -pred
            realized = 1 if r["fwd_ret_1d"] > 0 else -1
            tot += 1
            hits += int(pred == realized)
        return hits, tot

    # Price-momentum control: the session's OWN close-to-close return is also
    # known at close[d]. If sign(that) predicts the next day as well as the tide
    # slope does, the slope adds no edge beyond plain price momentum.
    def prev_ret(d: date) -> float | None:
        earlier = [td for td in trading_days if td < d]
        if d not in closes or not earlier:
            return None
        return closes[d] / closes[earlier[-1]] - 1.0

    mom_hits = mom_tot = 0
    for r in usable:
        pr = prev_ret(r["data_date"])
        if pr is None or pr == 0:
            continue
        mom_tot += 1
        mom_hits += int((1 if pr > 0 else -1) == (1 if r["fwd_ret_1d"] > 0 else -1))

    slopes = [r["session_slope"] for r in usable if r["session_slope"] is not None]
    rets = [r["fwd_ret_1d"] for r in usable if r["session_slope"] is not None]
    signed_trend = [
        (1 if r["session_slope"] > 0 else -1) * (r["trend_strength"] or 0)
        for r in usable
        if r["session_slope"] is not None
    ]
    conf = [r for r in usable if r["volume_confirms"]]

    h, t = hit_rate(usable)
    ch, ct = hit_rate(usable, contrarian=True)
    hc, tc = hit_rate(conf)

    # ── data-driven verdict (so the saved trace never goes stale) ──
    pear = _pearson(slopes, rets) if len(slopes) >= 3 else None
    crit_r = 1.96 / (len(slopes) ** 0.5) if len(slopes) >= 3 else None  # ~p<.05
    tf_rate = h / t if t else 0.0
    ctrl_rate = mom_hits / mom_tot if mom_tot else 0.0
    base = _mean([r["fwd_ret_1d"] for r in usable]) or 0.0
    nb = {st: len(vs) for st, vs in by_state.items()}
    sig = pear is not None and crit_r is not None and abs(pear) >= crit_r
    beats_ctrl = tf_rate > ctrl_rate + 0.03
    if sig and beats_ctrl:
        conf_word = "LOW" if len(usable) < 150 else "MED"
        verdict = (
            f"**SUGGESTIVE ({conf_word} confidence).** The slope's directional "
            f"hit rate ({tf_rate:.0%}) beats the naive price-momentum control "
            f"({ctrl_rate:.0%}) and the slope↔return correlation "
            f"({pear:+.2f}) clears the ~{crit_r:.2f} significance bar at this n — "
            f"so the options-flow slope carries information beyond price trend. "
            f"Keep collecting; recalibrate the trend_strength buckets before "
            f"treating it as tradeable."
        )
    elif (pear is None) or (not sig and abs(tf_rate - 0.5) <= 0.05):
        verdict = (
            f"**DESCRIPTIVE — NO predictive edge.** Directional hit rate "
            f"{tf_rate:.0%} ≈ coin flip and ≈ the price-momentum control "
            f"({ctrl_rate:.0%}); correlation {pear:+.2f} is below the "
            f"~{crit_r:.2f} significance bar; the BULLISH/BEARISH next-day means "
            f"barely separate. The slope reads CURRENT sentiment well but does "
            f"NOT forecast next-day SPY return on this sample. Earlier small-n "
            f"'edges' were single-regime artifacts. Treat it as a sentiment "
            f"descriptor, not a signal (cf. the VCG 'descriptive, not "
            f"predictive' finding)."
        )
    else:
        verdict = (
            f"**MIXED / INCONCLUSIVE.** hit_rate {tf_rate:.0%}, control "
            f"{ctrl_rate:.0%}, corr {pear:+.2f} vs ~{crit_r:.2f} sig bar. No "
            f"clean call — keep collecting and re-run."
        )

    lines = [
        "# Market-tide slope/sentiment — forward-return probe",
        "",
        f"- Sessions with EOD sentiment: **{len(recs)}** "
        f"({recs[0]['data_date']} → {recs[-1]['data_date']})",
        f"- Sessions with a 1d forward SPY return: **{len(usable)}**",
        f"- State balance: {nb.get('BULLISH', 0)} BULLISH / "
        f"{nb.get('BEARISH', 0)} BEARISH / {nb.get('BALANCED', 0)} BALANCED · "
        f"baseline next-day drift {base:+.3%}",
        f"- n = {len(usable)}; significance bar on the correlation is "
        f"~{crit_r:.2f} (|r| below it ⇒ not distinguishable from noise).",
        "",
        "## Mean next-day SPY return by sentiment state",
        "",
        "| State | n | mean fwd_ret_1d | median |",
        "|---|---|---|---|",
    ]
    for st, vs in sorted(by_state.items()):
        sv = sorted(vs)
        med = sv[len(sv) // 2]
        lines.append(f"| {st} | {len(vs)} | {_mean(vs):+.4%} | {med:+.4%} |")
    base = _mean([r["fwd_ret_1d"] for r in usable])
    lines += [
        f"| ALL (baseline) | {len(usable)} | {base:+.4%} | — |",
        "",
        "## Directional skill (predict next-day sign from state)",
        "",
        f"- Trend-following hit rate: **{h}/{t} = {(h / t if t else 0):.0%}**",
        f"- Contrarian (fade) hit rate: **{ch}/{ct} = {(ch / ct if ct else 0):.0%}**",
        f"- Trend-following, volume-confirmed only: "
        f"**{hc}/{tc} = {(hc / tc if tc else 0):.0%}**",
        f"- **Control — naive price momentum** (sign of the session's own "
        f"return): **{mom_hits}/{mom_tot} = {(mom_hits / mom_tot if mom_tot else 0):.0%}**",
        "",
        "## Slope ↔ next-day return correlation",
        "",
        f"- Pearson(session_slope, fwd_ret_1d): "
        f"**{_pearson(slopes, rets) if len(slopes) >= 3 else None}**",
        f"- Spearman(session_slope, fwd_ret_1d): "
        f"**{_spearman(slopes, rets) if len(slopes) >= 3 else None}**",
        f"- Pearson(signed_trend_strength, fwd_ret_1d): "
        f"**{_pearson(signed_trend, rets) if len(signed_trend) >= 3 else None}**",
        "",
        "## How to read this",
        "",
        "Trend-following hit rate **above** the price-momentum control **and** "
        "|corr| above the significance bar ⇒ the options-flow slope leads price "
        "with info beyond the trend. Hit rate ≈ control ≈ 50% and |corr| below the "
        "bar ⇒ descriptive only — no forecast power.",
        "",
        "## Caveats",
        "",
        "1. **Beats price momentum?** The control is the key confound: if the "
        "slope's hit rate ≈ the naive price-momentum control, it adds no edge "
        "beyond yesterday's price.",
        "2. **Multiple looks.** Several cuts were tested (state buckets, contrarian, "
        "volume-confirmed, two corr flavours); no multiple-comparison correction — "
        "discount borderline results accordingly.",
        "3. **Regime span.** Check the state balance above. A one-sided sample "
        "(all-bull or all-bear) flatters any momentum signal; a balanced sample "
        "(both states well-represented) is the fairer test.",
        "4. **EOD close-to-close, no costs.** Signal known at close[d]; return is "
        "close[d]→close[d+1]. No slippage/fees modeled.",
        "",
        f"## Verdict\n\n{verdict}",
        "",
        "Reproduce: `uv run python scripts/research/tide_slope_backtest.py`",
        "",
    ]
    summary = "\n".join(lines)
    with open(f"{OUT_DIR}/summary.md", "w") as f:
        f.write(summary)
    print(summary)
    print(f"\nwrote {OUT_DIR}/results.csv  +  {OUT_DIR}/summary.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
