"""One-off: freeze the EWMA-fallback golden from signal-lab's ORIGINAL ewma_cone.

The GJR golden (forward_forecast_golden.json) exercises _fit + gjr_std_boot_cone; it never
touches ewma_cone/_gbm_samples. This fixture covers the fallback branch, generated from the
UNVENDORED source so vendoring errors cannot self-certify.

Reproduce (signal-lab's engine moved from the skill wrapper to the repo root on 2026-08-01;
scripts/forward_paths.py there is hash-identical to the pinned 0f893513 blob):
  uv run python scripts/research/spx_density_ewma_golden_gen.py \
      --signal-lab /Users/chenxi/projects/signal-lab
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
PANEL = REPO / "src" / "uw_scan" / "density" / "data" / "panel.parquet"
OUT = REPO / "tests" / "fixtures" / "density" / "ewma_fallback_golden.json"

N_LAST = (
    400  # short slice: long enough to be a realistic series, short enough to be fast
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal-lab", required=True)
    lab = Path(ap.parse_args().signal_lab).expanduser()
    sys.path.insert(0, str(lab))
    from scripts.forward_paths import QUANTILES, ewma_cone  # the ORIGINALS

    golden = json.loads(GOLDEN.read_text())
    panel = pd.read_parquet(PANEL).sort_values("trade_date").reset_index(drop=True)
    closes = list(panel["close"].astype(float))
    closes += [float(b["close"]) for b in golden["provenance"]["fresh_bars_appended"]]
    closes = np.asarray(closes, dtype=float)
    r = closes[1:] / closes[:-1] - 1.0

    hist = r[-N_LAST:]
    anchor_close = float(golden["anchor"]["close"])
    anchor_date = golden["anchor"]["date"]
    seed = int(golden["model"]["cone_seed"])

    cone = ewma_cone(
        hist,
        anchor_close,
        pd.Timestamp(anchor_date),
        5,
        lam=0.94,
        quantiles=QUANTILES,
        M=10000,
        seed=seed,
    )
    OUT.write_text(
        json.dumps(
            {
                "generated_from": "signal-lab ORIGINAL scripts/forward_paths.ewma_cone @ 0f893513",
                "reproduce": "uv run python scripts/research/spx_density_ewma_golden_gen.py --signal-lab <signal-lab repo root>",
                "n_last_returns": N_LAST,
                "anchor_date": anchor_date,
                "anchor_close": anchor_close,
                "seed": seed,
                "lam": 0.94,
                "cum_return_q": {
                    str(h): [float(v) for v in cone.at(h)] for h in range(1, 6)
                },
            },
            indent=2,
        )
    )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
