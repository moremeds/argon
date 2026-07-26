"""Does the crowding price leg predict forward relative return?

Motivation: the panel reduces three legs to one label via a min-band rule
(state = weakest leg's band). That rule is a modelling choice, not a measured
one. This asks whether ANY threshold on the price leg -- the only leg with a
multi-year sample -- separates "entering crowding" from "climaxing", by
measuring forward SPY-relative returns conditional on the leg's value.

Answer: no. See docs/research/2026-07-26-sector-crowding-lifecycle.md.

Data:
  prices  apex /bars/{ticker} 1d, 2021-06-22..2026-07-24 (Tailscale, network
          required). Starts after the XLE/SMH adjustment seam at 2021-06-11.
  bench   SPY, same source.

Reproduce:
    uv run python scripts/research/sector_crowding_lifecycle.py

Writes docs/research/2026-07-26-sector-crowding-lifecycle.json (full panel).
"""

from __future__ import annotations

import json
import pathlib
import statistics

import httpx

APEX = "http://100.66.147.98:8322"
OUT = pathlib.Path("docs/research/2026-07-26-sector-crowding-lifecycle.json")

START = "2021-06-22"  # after the XLE/SMH adjustment seam
BENCH = "SPY"
W = 63  # reports.sector_crowding.RETURN_WINDOW
MIN_HIST = 60  # reports.sector_crowding.MIN_HISTORY_POINTS
MOM = 10  # recent relative-momentum lookback
HORIZONS = (5, 10, 21, 42)
SPLIT = "2024-01-01"
SECTORS = [
    "XLB",
    "XLC",
    "XLE",
    "XLF",
    "XLI",
    "XLK",
    "XLP",
    "XLRE",
    "XLU",
    "XLV",
    "XLY",
    "SOXX",
    "SMH",
    "IGV",
    "MAGS",
]


def fetch() -> dict[str, list[tuple[str, float]]]:
    out: dict[str, list[tuple[str, float]]] = {}
    with httpx.Client(timeout=60) as c:
        for t in [*SECTORS, BENCH]:
            r = c.get(f"{APEX}/bars/{t}", params={"timeframe": "1d", "limit": 5000})
            r.raise_for_status()
            j = r.json()
            bars = j if isinstance(j, list) else (j.get("bars") or j.get("data") or [])
            rows = sorted(
                ((b["time"][:10], float(b["close"])) for b in bars if b.get("close")),
                key=lambda x: x[0],
            )
            seams = [
                rows[i][0]
                for i in range(1, len(rows))
                if abs(rows[i][1] / rows[i - 1][1] - 1) > 0.25
            ]
            kept = [(d, c_) for d, c_ in rows if d >= START]
            print(
                f"{t:<6} raw={len(rows):>5} kept={len(kept):>5}  "
                f"{kept[0][0]}..{kept[-1][0]}"
                + (f"  PRE-START SEAMS {seams}" if seams else "")
            )
            out[t] = kept
    return out


def pct_rank(hist: list[float], v: float) -> float:
    return 100.0 * sum(1 for h in hist if h < v) / len(hist)


def build(raw: dict) -> list[dict]:
    bench = dict(raw[BENCH])
    panel = []
    for t in SECTORS:
        rows = [(d, c) for d, c in raw[t] if d in bench]
        dates = [d for d, _ in rows]
        px = [c for _, c in rows]
        bp = [bench[d] for d in dates]
        n = len(rows)
        rel: list[float | None] = [None] * n
        for i in range(W, n):
            rel[i] = (px[i] / px[i - W] - 1) * 100 - (bp[i] / bp[i - W] - 1) * 100
        for i in range(W, n):
            # expanding, point-in-time: only observations strictly before i
            hist = [rel[j] for j in range(W, i) if rel[j] is not None]
            if len(hist) < MIN_HIST:
                continue
            rec: dict = {
                "ticker": t,
                "date": dates[i],
                "i": i,
                "rel63": rel[i],
                "pct": pct_rank(hist, rel[i]),
                "mom10": (px[i] / px[i - MOM] - 1) * 100
                - (bp[i] / bp[i - MOM] - 1) * 100,
            }
            for h in HORIZONS:
                rec[f"fwd{h}"] = (
                    (px[i + h] / px[i] - 1) * 100 - (bp[i + h] / bp[i] - 1) * 100
                    if i + h < n
                    else None
                )
            panel.append(rec)
    return panel


def summarize(rows: list[dict], h: int):
    v = [r[f"fwd{h}"] for r in rows if r.get(f"fwd{h}") is not None]
    if len(v) < 20:
        return (len(v), None, None, None)
    hit = 100.0 * sum(1 for x in v if x > 0) / len(v)
    # every h-th bar per ticker -> non-overlapping forward windows
    nov = [
        r[f"fwd{h}"] for r in rows if r.get(f"fwd{h}") is not None and r["i"] % h == 0
    ]
    t = (
        statistics.mean(nov) / (statistics.pstdev(nov) / len(nov) ** 0.5)
        if len(nov) > 5 and statistics.pstdev(nov) > 0
        else None
    )
    return (len(v), statistics.mean(v), hit, t)


def table(title: str, groups: list[tuple[str, list[dict]]]) -> None:
    print(f"\n=== {title} ===")
    hdr = f"{'bucket':<28}{'n':>7}" + "".join(
        f"{'fwd' + str(h):>9}{'hit%':>7}{'t':>7}" for h in HORIZONS
    )
    print(hdr)
    print("-" * len(hdr))
    for label, rows in groups:
        line = f"{label:<28}{len(rows):>7}"
        for h in HORIZONS:
            _, m, hit, t = summarize(rows, h)
            line += (
                f"{m:>+9.2f}{hit:>7.0f}"
                + (f"{t:>7.1f}" if t is not None else f"{'-':>7}")
                if m is not None
                else f"{'-':>9}{'-':>7}{'-':>7}"
            )
        print(line)


BUCKETS = {
    "ENTRY   50<=p<90 mom>+2": lambda r: 50 <= r["pct"] < 90 and r["mom10"] > 2,
    "DIP-BUY 50<=p<90 mom<-2": lambda r: 50 <= r["pct"] < 90 and r["mom10"] < -2,
    "OK      p>=90    mom>+2": lambda r: r["pct"] >= 90 and r["mom10"] > 2,
    "CLIMAX  p>=90    mom<=0": lambda r: r["pct"] >= 90 and r["mom10"] <= 0,
}


def main() -> None:
    panel = build(fetch())
    print(f"\npanel: {len(panel)} sector-days, {len(SECTORS)} tickers, from {START}")

    edges = [(0, 10), (10, 25), (25, 50), (50, 75), (75, 90), (90, 95), (95, 101)]
    table(
        "FORWARD RELATIVE RETURN BY PRICE-LEG PERCENTILE",
        [
            (f"pct {lo}-{min(hi, 100)}", [r for r in panel if lo <= r["pct"] < hi])
            for lo, hi in edges
        ],
    )
    table(
        "TOP DECILE (pct>=90) BY RECENT 10d RELATIVE MOMENTUM",
        [
            ("mom10 > +2%", [r for r in panel if r["pct"] >= 90 and r["mom10"] > 2]),
            (
                "mom10 0..+2%",
                [r for r in panel if r["pct"] >= 90 and 0 < r["mom10"] <= 2],
            ),
            (
                "mom10 -2..0%",
                [r for r in panel if r["pct"] >= 90 and -2 < r["mom10"] <= 0],
            ),
            ("mom10 < -2%", [r for r in panel if r["pct"] >= 90 and r["mom10"] <= -2]),
        ],
    )

    print(f"\n=== SPLIT-SAMPLE VALIDATION (fwd21, split {SPLIT}) ===")
    for label, fn in BUCKETS.items():
        sel = [r for r in panel if fn(r)]
        for tag, sub in (
            ("full   ", sel),
            ("2021-23", [r for r in sel if r["date"] < SPLIT]),
            ("2024-26", [r for r in sel if r["date"] >= SPLIT]),
        ):
            n, m, hit, t = summarize(sub, 21)
            print(
                f"  {label:<26} {tag}  n={n:>5}  "
                + (
                    f"mean={m:+6.2f}  hit={hit:3.0f}%  t={t:+5.1f}"
                    if m is not None and t is not None
                    else "(thin)"
                )
            )
        print()

    print("=== TICKER CONCENTRATION (fwd21 mean per bucket) ===")
    for label, fn in BUCKETS.items():
        sel = [r for r in panel if fn(r)]
        by: dict[str, list[float]] = {}
        for r in sel:
            if r.get("fwd21") is not None:
                by.setdefault(r["ticker"], []).append(r["fwd21"])
        top = sorted(by.items(), key=lambda kv: -len(kv[1]))[:6]
        print(
            f"  {label:<26} "
            + "  ".join(f"{k}:{statistics.mean(v):+.2f}(n{len(v)})" for k, v in top)
        )

    print("\n=== POWER: detectable effect at |t|=2 ===")
    for h in (21, 42):
        v = [r[f"fwd{h}"] for r in panel if r.get(f"fwd{h}") is not None]
        sd = statistics.pstdev(v)
        print(f"  fwd{h}: sd={sd:.2f}%")
        for n_, lbl in (
            (85, "premium leg (140d x 15t, non-overlapping)"),
            (170, "flow leg (~250d x 15t)"),
            (1100, "price leg (5y)"),
        ):
            print(f"      n={n_:<5} {lbl:<44} needs {2 * sd / n_**0.5:.2f}%")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(panel) + "\n")
    print(f"\nfull panel -> {OUT}")


if __name__ == "__main__":
    main()
