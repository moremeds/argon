"""Per-banded-name: does a corporate-action cliff fall inside the yield window
the band was actually built from?

Read-only. Measures the contamination that `LAKE_BASIS_SEAM` + split adjustment
in `worker/jobs/fundamental_anchors.py` exist to remove, so it doubles as the
after-check: re-run once bands have been rebuilt and the count should fall to the
names whose splits `corporate_actions` still lacks.

Reproduce (on the mini, where the lake and prod DB live):

    ssh macmini "/opt/homebrew/bin/docker exec -i argon-worker-massive-0-1 python -" \
      < scripts/research/valuation_split_contamination_probe.py

Verdict and the 2026-08-21 numbers:
`docs/research/2026-08-21-lake-price-basis-split-contamination/VERDICT.md`
"""
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pyarrow.parquet as pq

from uw_scan.config import Settings

SEAM = date(2021, 6, 11)  # legacy back-adjusted -> raw as-traded
LAG = timedelta(days=45)

s = Settings.from_env()
root = Path(s.lake_credit_etf_root)


def near_simple_ratio(r):
    for n in range(1, 51):
        for m in (1, 2, 3, 4):
            if m > 1 and n % m == 0:
                continue
            for cand, label in ((n / m, f"{n}:{m}"), (m / n, f"{m}:{n}")):
                if cand > 1.05 and abs(r / cand - 1) < 0.02:
                    return label
    return None


with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute(
        """SELECT DISTINCT ON (ticker) ticker, spot, buy_below, history_quarters, spot_percentile
             FROM uw_scan.valuation_anchors
            WHERE as_of='2026-08-18' AND buy_below IS NOT NULL
            ORDER BY ticker, result_id DESC"""
    )
    banded = {r[0]: r[1:] for r in cur.fetchall()}
    cur.execute(
        """SELECT ticker, period_end FROM uw_scan.fundamental_statement_obs
            WHERE statement='income' AND ticker = ANY(%s)""",
        (list(banded),),
    )
    periods: dict[str, list[date]] = {}
    for t, p in cur.fetchall():
        periods.setdefault(t, []).append(p)

rows_out, crosses_seam, clean = [], 0, 0
for t, (spot, buy_below, hq, pct) in sorted(banded.items()):
    ps = sorted(set(periods.get(t, [])), reverse=True)[: hq or 20]
    if not ps:
        continue
    start = min(ps) + LAG
    p = root / f"symbol={t}" / "1d.parquet"
    if not p.exists():
        continue
    tab = pq.read_table(str(p), columns=["trade_date", "close"])
    ser = sorted(
        (d, float(c))
        for d, c in zip(
            tab.column("trade_date").to_pylist(), tab.column("close").to_pylist()
        )
        if d is not None and c is not None and d >= start
    )
    if start < SEAM:
        crosses_seam += 1
    worst = None
    for a, b in zip(ser, ser[1:]):
        if a[1] <= 0:
            continue
        gap = max(b[1] / a[1], a[1] / b[1])
        lab = near_simple_ratio(gap) if gap >= 1.6 else None
        if lab and (worst is None or gap > worst[0]):
            worst = (gap, a[0], b[0], lab)
    if worst is None:
        clean += 1
        continue
    rows_out.append((t, start, worst, float(spot), float(buy_below), float(pct or 0)))

inzone = [r for r in rows_out if r[3] < r[4]]
print(f"banded names checked: {len(banded)}")
print(f"  window starts before the 2021-06-11 basis seam: {crosses_seam}")
print(f"  no split cliff inside the window:               {clean}")
print(f"  SPLIT CLIFF INSIDE THE WINDOW:                  {len(rows_out)}")
print(f"    of those, currently rendered IN THE BUY ZONE: {len(inzone)}")
print()
print("ticker|window_start|cliff_date|ratio|gap|spot|buy_below|spot_pct|in_buy_zone")
for t, start, (gap, a, b, lab), spot, bb, pct in sorted(rows_out, key=lambda r: -r[2][0]):
    print(
        f"{t}|{start}|{b}|{lab}|{gap:.2f}|{spot:.2f}|{bb:.2f}|{pct:.2f}|{spot < bb}"
    )
