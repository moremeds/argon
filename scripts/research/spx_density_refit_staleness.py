"""How much does refit cadence move the cone? (spec §2.1's measurement, committed)

Fits arm G at the committed 2026-07-30 anchor, then with params fitted 5/10/21/42/63
trading days earlier, drawing the SAME anchor cone from each vector — exactly what the
v13 recovery_ladder does on a non-refit day. Answers: is daily refitting worth anything
over monthly?

Reproduce:
  uv run python scripts/research/spx_density_refit_staleness.py
Writes docs/research/spx-density-cone/refit_staleness.json (committed trace).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from uw_scan.density.cone import gjr_std_boot_cone
from uw_scan.density.constants import (
    BAND_80,
    H_MAX,
    M_PATHS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    seed_for,
)
from uw_scan.density.fit import ARMS, _fit
from uw_scan.density.forecast import load_frozen_panel

REPO = Path(__file__).resolve().parents[2]
GOLDEN = REPO / "tests" / "fixtures" / "density" / "forward_forecast_golden.json"
OUT = REPO / "docs" / "research" / "spx-density-cone" / "refit_staleness.json"


def main() -> int:
    golden = json.loads(GOLDEN.read_text())
    panel = load_frozen_panel()
    closes = list(panel["close"].astype(float))
    closes += [float(b["close"]) for b in golden["provenance"]["fresh_bars_appended"]]
    arr = np.asarray(closes, dtype=float)
    r = arr[1:] / arr[:-1] - 1.0

    i = len(r) - 1
    hist = r[: i + 1]
    anchor_close = float(golden["anchor"]["close"])
    anchor_ts = pd.Timestamp(golden["anchor"]["date"])
    seed = int(seed_for(i))
    lo, hi = BAND_80

    rows = []
    for age in (0, 5, 10, 21, 42, 63):
        params, _ = _fit(ARMS["G"], r[: i + 1 - age])
        if params is None:
            rows.append({"param_age_days": age, "fitted": False})
            continue
        cone = gjr_std_boot_cone(
            hist,
            anchor_close,
            anchor_ts,
            H_MAX,
            params,
            M=M_PATHS,
            seed=seed,
            burn_in=OVERLAY_BURN_IN,
            min_pool=OVERLAY_MIN_POOL,
        )
        rows.append(
            {
                "param_age_days": age,
                "fitted": True,
                "params": {k: float(v) for k, v in params.items()},
                "persistence": float(
                    params["alpha"] + params["gamma"] / 2.0 + params["beta"]
                ),
                "band80_pct": {
                    h: round(float(cone.at(h)[hi] - cone.at(h)[lo]) * 100, 4)
                    for h in range(1, H_MAX + 1)
                },
            }
        )

    base = next(x for x in rows if x["param_age_days"] == 0 and x.get("fitted"))
    for x in rows:
        if x.get("fitted"):
            x["band80_delta_vs_fresh_bp"] = {
                h: round((x["band80_pct"][h] - base["band80_pct"][h]) * 100, 2)
                for h in base["band80_pct"]
            }

    out = {
        "reproduce": "uv run python scripts/research/spx_density_refit_staleness.py",
        "anchor": {
            "date": golden["anchor"]["date"],
            "close": anchor_close,
            "index": i,
            "seed": seed,
        },
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
