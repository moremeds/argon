"""Does apex's /bars close equal silver's close, and is either split-only?

Prints, for one date, each ticker's silver `close`, its two adjustment factors,
the split-only close reconstructed as `close / (pf * svf)`, and raw bronze.
CRWD isolates the split half (no dividend, factors cancel to 1.0), ETR the
dividend half (never split, svf == 1.0), BKNG carries both.

Reproduce (the lake lives on the mini):

  scp docs/research/2026-08-21-lake-price-basis-split-contamination/\
apex_vs_silver_check.py macmini:/tmp/apexchk.py
  ssh macmini 'D=/opt/homebrew/bin/docker
  C=$($D create -v /Volumes/DATA_LAKE/livewire/data-lake:/lake:ro \
      ghcr.io/moremeds/argon-app:latest python /tmp/apexchk.py)
  $D cp /tmp/apexchk.py $C:/tmp/apexchk.py; $D start -a $C; $D rm -f $C'

  # and apex's own answer, to compare against the silver `close` column:
  curl -s "http://100.66.147.98:8322/bars/BKNG?timeframe=1d\
&start=2026-04-01T00:00:00&end=2026-04-03T00:00:00&limit=0"

Measured 2026-08-22: apex returned 167.349 for BKNG on 2026-04-02, matching
silver `close` 167.3493 and NOT split_only 167.7700.
"""

import pyarrow.parquet as pq
from datetime import date

TARGET = date(2026, 4, 2)
for sym in ["BKNG", "CRWD", "ETR"]:
    sp = f"/lake/silver/asset_class=equity/symbol={sym}/1d.parquet"
    bp = f"/lake/bronze/asset_class=equity/symbol={sym}/1d.parquet"
    try:
        t = pq.read_table(
            sp,
            columns=["trade_date", "close", "price_adjustment_factor", "split_volume_factor"],
        ).to_pydict()
    except Exception as e:
        print(sym, "silver ERR", repr(e))
        t = None
    if t:
        hit = False
        for i, d in enumerate(t["trade_date"]):
            if d == TARGET:
                c = float(t["close"][i])
                pf = float(t["price_adjustment_factor"][i])
                svf = float(t["split_volume_factor"][i])
                prod = pf * svf
                print(
                    f"{sym} SILVER close={c:.4f} pf={pf:.6f} svf={svf:.6f} "
                    f"pf*svf={prod:.6f} split_only={c / prod:.4f}"
                )
                hit = True
                break
        if not hit:
            print(sym, "silver: no row at", TARGET)
    try:
        b = pq.read_table(bp, columns=["trade_date", "close"]).to_pydict()
    except Exception as e:
        print(sym, "bronze ERR", repr(e))
        continue
    hit = False
    for i, d in enumerate(b["trade_date"]):
        if d == TARGET:
            bc = float(b["close"][i])
            print(f"{sym} BRONZE close={bc:.4f}")
            hit = True
            break
    if not hit:
        print(sym, "bronze: no row at", TARGET)
