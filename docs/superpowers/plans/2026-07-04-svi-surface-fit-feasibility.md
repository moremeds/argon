# SVI Surface-Fit Feasibility Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer one question — can we fit clean, arbitrage-free raw-SVI smiles to argon's banked UW IV grid (`option_surface_grid_daily`), so the fitted-vs-marked residual is trustworthy enough to later become a surface-mispricing signal?

**Architecture:** A pure numpy/scipy module (`scripts/research/svi_fit.py`) fits raw-SVI per single expiry and computes the two no-arb diagnostics (butterfly `g(k)≥0`, calendar monotonicity). A read-only runner (`scripts/research/svi_surface_fit_probe.py`) pulls a representative panel of real smiles off the mini, fits each, and writes full traces + a summary. A research note records the PASS/FAIL verdict. **This is a feasibility spike** — no production job, table, API, or UI. If the gate passes, the productionized signal gets its own brainstorm/spec/plan.

**Tech Stack:** Python 3.13 via `uv`; numpy (already available) + scipy + matplotlib (added in Task 1); psycopg 3; pytest. Overlay figures render to PNG (matplotlib, Agg backend) and the same marked-vs-fit data is also emitted as CSV.

## Global Constraints

- **uv only** — `uv run pytest`, `uv add scipy`; never bare `python`/`pip`.
- **DB→DB, read-only, ZERO UW/IB calls.** Read the mini's `option_wizard` via env override: `UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1`.
- **Decimal→float at the numpy boundary** — grid columns are `NUMERIC` (psycopg returns `Decimal`); cast to `float` before array math.
- **Persist the full trace** to `docs/research/svi-surface-fit/` (every fitted smile's params + RMSE + violations), and record the exact reproduce command. stdout-only is data loss.
- **Spike only** — do not add a scheduler job, migration, storage method, API route, or web component.
- **Exclude 0–4 DTE** smiles (`(expiry - market_date) >= 5`) — known-noisy (the rr_25d/#207 lesson); panel targets 7/30/90 DTE.
- **Module size budget** <500 lines/file.
- **No `Co-Authored-By: Claude` trailer** on commits.
- **Artifacts under `docs/research/svi-surface-fit/`**, never the repo root.
- Worktree already exists: `.worktrees/svi-surface-fit` on `feat/svi-surface-fit` (off `main` `e6830c3`). Work there.

---

### Task 1: Add scipy + scaffold the research directory

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `docs/research/svi-surface-fit/.gitkeep`

**Interfaces:**
- Produces: scipy + matplotlib importable in the uv env; the output directory exists.

- [ ] **Step 1: Add scipy + matplotlib**

```bash
cd /Users/chenxi/projects/argon/.worktrees/svi-surface-fit
uv add scipy matplotlib
```

- [ ] **Step 2: Verify they import**

Run: `uv run python -c "import numpy, scipy, matplotlib; print('numpy', numpy.__version__, 'scipy', scipy.__version__, 'mpl', matplotlib.__version__)"`
Expected: prints all three versions, exit 0.

- [ ] **Step 3: Scaffold the output dir**

```bash
mkdir -p docs/research/svi-surface-fit && touch docs/research/svi-surface-fit/.gitkeep
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock docs/research/svi-surface-fit/.gitkeep
git commit -m "chore(svi): add scipy + matplotlib deps + scaffold research dir for SVI fit spike"
```

---

### Task 2: Pure raw-SVI fit + no-arb diagnostics (TDD)

**Files:**
- Create: `scripts/research/svi_fit.py`
- Test: `tests/unit/test_svi_fit.py`

**Interfaces:**
- Produces (consumed by Task 3):
  - `SVIParams(a, b, rho, m, sigma)` — frozen dataclass; `.as_tuple()`.
  - `raw_svi_total_variance(k: np.ndarray, p: SVIParams) -> np.ndarray`
  - `butterfly_g(k: np.ndarray, p: SVIParams) -> np.ndarray`
  - `fit_raw_svi(k, w, weights=None) -> tuple[SVIParams, float]` (float = RMSE in total-variance units)
  - `rmse_vol_points(k, iv, p, t_years) -> float`
  - `build_smile(rows, spot, market_date, expiry) -> (k, iv, w, t_years, strikes)`
  - `calendar_violations(fitted_by_expiry, ref_k=0.0) -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_svi_fit.py`:

```python
import numpy as np
from datetime import date

from scripts.research.svi_fit import (
    SVIParams, raw_svi_total_variance, butterfly_g, fit_raw_svi,
    rmse_vol_points, build_smile, calendar_violations,
)


def test_fit_recovers_known_params():
    true = SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.0, sigma=0.1)
    k = np.linspace(-0.5, 0.5, 21)
    w = raw_svi_total_variance(k, true)
    p, _ = fit_raw_svi(k, w)
    iv = np.sqrt(w / 0.25)
    assert rmse_vol_points(k, iv, p, 0.25) < 0.05  # noiseless -> near-exact


def test_butterfly_g_hand_value_and_benign_is_arbfree():
    p = SVIParams(a=0.04, b=0.4, rho=-0.3, m=0.0, sigma=0.1)
    assert abs(butterfly_g(np.array([0.0]), p)[0] - 2.9541) < 1e-3  # hand-derived at k=0
    grid = np.linspace(-1.0, 1.0, 201)
    assert butterfly_g(grid, p).min() >= 0.0  # benign smile is arb-free


def test_build_smile_uses_otm_wings():
    rows = [
        {"strike": 90, "call_iv": 0.25, "put_iv": 0.30},
        {"strike": 110, "call_iv": 0.22, "put_iv": 0.28},
    ]
    k, iv, w, t, strikes = build_smile(
        rows, spot=100.0, market_date=date(2026, 1, 1), expiry=date(2026, 4, 1))
    assert list(strikes) == [90.0, 110.0]
    assert abs(iv[0] - 0.30) < 1e-12 and abs(iv[1] - 0.22) < 1e-12  # put wing, call wing
    assert abs(k[0] - np.log(0.9)) < 1e-12


def test_calendar_violations_flags_decreasing_variance():
    near = SVIParams(a=0.05, b=0.3, rho=-0.2, m=0.0, sigma=0.1)      # w(0)=0.08
    far_ok = SVIParams(a=0.09, b=0.3, rho=-0.2, m=0.0, sigma=0.1)    # w(0)=0.12 -> ok
    far_bad = SVIParams(a=0.02, b=0.3, rho=-0.2, m=0.0, sigma=0.1)   # w(0)=0.05 -> arb
    assert calendar_violations([(1, 0.1, near), (2, 0.3, far_ok)]) == 0
    assert calendar_violations([(1, 0.1, near), (2, 0.3, far_bad)]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_svi_fit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.research.svi_fit'`.

- [ ] **Step 3: Implement the module**

Create `scripts/research/svi_fit.py`:

```python
"""Raw-SVI (Gatheral) single-expiry smile fit + no-arbitrage diagnostics.

Pure numpy/scipy. No DB, no I/O. Feasibility-spike core for the surface
mispricing signal (radon-adoption R1). See docs/research/svi-surface-fit/.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import log
from typing import Any, Iterable

import numpy as np
from scipy.optimize import least_squares


@dataclass(frozen=True)
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        return (self.a, self.b, self.rho, self.m, self.sigma)


def raw_svi_total_variance(k: np.ndarray, p: SVIParams) -> np.ndarray:
    """w(k) = a + b(rho(k-m) + sqrt((k-m)^2 + sigma^2))."""
    km = np.asarray(k, float) - p.m
    return p.a + p.b * (p.rho * km + np.sqrt(km * km + p.sigma * p.sigma))


def _svi_deriv(k: np.ndarray, p: SVIParams) -> tuple[np.ndarray, np.ndarray]:
    km = np.asarray(k, float) - p.m
    root = np.sqrt(km * km + p.sigma * p.sigma)
    w1 = p.b * (p.rho + km / root)
    w2 = p.b * p.sigma * p.sigma / (root ** 3)
    return w1, w2


def butterfly_g(k: np.ndarray, p: SVIParams) -> np.ndarray:
    """Gatheral g(k); g>=0 everywhere <=> no butterfly (density) arbitrage."""
    k = np.asarray(k, float)
    w = raw_svi_total_variance(k, p)
    w1, w2 = _svi_deriv(k, p)
    return (1.0 - k * w1 / (2.0 * w)) ** 2 - (w1 * w1 / 4.0) * (1.0 / w + 0.25) + w2 / 2.0


def fit_raw_svi(k, w, weights=None) -> tuple[SVIParams, float]:
    """Least-squares raw-SVI fit of total variance w(k). Multi-start over (m, sigma).

    Returns (params, rmse_total_variance). Bounds: b>=0, |rho|<1, sigma>0.
    """
    k = np.asarray(k, float)
    w = np.asarray(w, float)
    sw = np.ones_like(w) if weights is None else np.sqrt(np.asarray(weights, float))

    def resid(theta):
        return sw * (raw_svi_total_variance(k, SVIParams(*theta)) - w)

    lo = [1e-8, 1e-8, -0.999, float(k.min()) - 0.5, 1e-4]
    hi = [max(float(w.max()), 1e-6) * 2.0 + 1e-6, 10.0, 0.999, float(k.max()) + 0.5, 5.0]
    a0 = max(float(w.min()), 1e-6)
    m_at_min = float(k[int(np.argmin(w))]) if k.size else 0.0
    best = None
    for m0 in {0.0, m_at_min}:
        for s0 in (0.05, 0.2, 0.5):
            theta0 = [a0, 0.1, -0.3, float(np.clip(m0, lo[3], hi[3])), s0]
            try:
                sol = least_squares(resid, theta0, bounds=(lo, hi),
                                    method="trf", max_nfev=2000)
            except Exception:
                continue
            if best is None or sol.cost < best.cost:
                best = sol
    if best is None:
        raise RuntimeError("SVI fit failed for all starts")
    p = SVIParams(*(float(x) for x in best.x))
    rmse_w = float(np.sqrt(np.mean((raw_svi_total_variance(k, p) - w) ** 2)))
    return p, rmse_w


def rmse_vol_points(k, iv, p: SVIParams, t_years: float) -> float:
    """RMSE(marked IV, SVI IV) in VOL POINTS (0.5 == half a vol point)."""
    w = np.maximum(raw_svi_total_variance(np.asarray(k, float), p), 0.0)
    iv_fit = np.sqrt(w / t_years)
    return float(np.sqrt(np.mean((iv_fit - np.asarray(iv, float)) ** 2)) * 100.0)


def build_smile(rows: Iterable[dict[str, Any]], spot: float,
                market_date: date, expiry: date):
    """OTM-wing smile: put_iv for K<spot, call_iv for K>=spot.

    Returns (k, iv, w, t_years, strikes) as numpy arrays. Null/<=0 IV rows dropped.
    """
    t_years = (expiry - market_date).days / 365.0
    ks, ivs, strikes_used = [], [], []
    for r in rows:
        strike = float(r["strike"])
        iv_raw = r["put_iv"] if strike < spot else r["call_iv"]
        if iv_raw is None or strike <= 0.0:
            continue
        iv = float(iv_raw)
        if iv <= 0.0:
            continue
        ks.append(log(strike / spot))
        ivs.append(iv)
        strikes_used.append(strike)
    k = np.array(ks, float)
    iv = np.array(ivs, float)
    return k, iv, iv * iv * t_years, t_years, np.array(strikes_used, float)


def calendar_violations(fitted_by_expiry, ref_k: float = 0.0) -> int:
    """Count expiries where total variance at ref_k DROPS vs the prior (shorter) one."""
    items = sorted(fitted_by_expiry, key=lambda x: x[1])  # by t_years
    prev_w, viol = None, 0
    for _exp, _t, p in items:
        wk = float(raw_svi_total_variance(np.array([ref_k]), p)[0])
        if prev_w is not None and wk < prev_w - 1e-9:
            viol += 1
        prev_w = wk
    return viol
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_svi_fit.py -q`
Expected: PASS (4 passed). If `test_fit_recovers_known_params` is flaky, widen the multi-start set — do NOT loosen the assertion.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/svi_fit.py tests/unit/test_svi_fit.py
git commit -m "feat(svi): pure raw-SVI fit + butterfly/calendar no-arb diagnostics"
```

---

### Task 3: Panel runner + smoke run against the mini

**Files:**
- Create: `scripts/research/svi_surface_fit_probe.py`
- Writes (traces): `docs/research/svi-surface-fit/fits.csv`, `docs/research/svi-surface-fit/overlays.csv`, `docs/research/svi-surface-fit/figs/*.png`

**Interfaces:**
- Consumes: everything from `scripts/research/svi_fit.py`; `uw_scan.config.Settings`.
- Produces: the two CSV traces, per-ticker overlay PNGs, and a stdout SUMMARY (liquid RMSE p50/p90, butterfly violation rate). Thin orchestration — all math lives in the tested module.

- [ ] **Step 1: Implement the runner**

Create `scripts/research/svi_surface_fit_probe.py`:

```python
"""SVI fit feasibility probe over banked option_surface_grid_daily (mini, read-only).

Fits raw-SVI to a real panel of smiles; reports RMSE (vol pts) + butterfly/calendar
violation rates; writes full traces. ZERO UW/IB calls.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python scripts/research/svi_surface_fit_probe.py
"""
from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import psycopg

from uw_scan.config import Settings
from scripts.research.svi_fit import (
    build_smile, butterfly_g, calendar_violations, fit_raw_svi,
    raw_svi_total_variance, rmse_vol_points,
)

logger = logging.getLogger("svi_probe")
logging.basicConfig(level=logging.INFO, format="%(message)s")

LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
TARGET_DTES = [7, 30, 90]
DTE_FLOOR = 5
N_DATES = 10
OUT = Path("docs/research/svi-surface-fit")


def thinnest_tickers(cur, n=2):
    """Data-driven 'illiquid' set: fewest strikes-per-expiry on the latest date."""
    cur.execute(
        "SELECT ticker, count(*)::float / count(DISTINCT expiry) AS spe "
        "FROM option_surface_grid_daily "
        "WHERE market_date=(SELECT max(market_date) FROM option_surface_grid_daily) "
        "GROUP BY ticker ORDER BY spe ASC LIMIT %s", (n,))
    return [r[0] for r in cur.fetchall()]


def pick_dates(cur, ticker):
    cur.execute(
        "SELECT DISTINCT market_date FROM option_surface_grid_daily "
        "WHERE ticker=%s ORDER BY market_date", (ticker,))
    all_d = [r[0] for r in cur.fetchall()]
    if len(all_d) <= N_DATES:
        return all_d
    idx = np.linspace(0, len(all_d) - 1, N_DATES).round().astype(int)
    return [all_d[i] for i in sorted(set(int(x) for x in idx))]


def nearest_expiries(cur, ticker, mdate):
    cur.execute(
        "SELECT DISTINCT expiry FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND (expiry - market_date) >= %s "
        "ORDER BY expiry", (ticker, mdate, DTE_FLOOR))
    exps = [r[0] for r in cur.fetchall()]
    chosen = {}
    for tgt in TARGET_DTES:
        if not exps:
            break
        best = min(exps, key=lambda e: abs((e - mdate).days - tgt))
        chosen[best] = (best - mdate).days
    return chosen


def load_smile_rows(cur, ticker, mdate, expiry):
    cur.execute(
        "SELECT strike, call_iv, put_iv, underlying_spot "
        "FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND expiry=%s ORDER BY strike",
        (ticker, mdate, expiry))
    rows, spot = [], None
    for strike, civ, piv, us in cur.fetchall():
        rows.append({"strike": strike, "call_iv": civ, "put_iv": piv})
        if us is not None:
            spot = float(us)
    return rows, spot


def _write_csv(path: Path, rows: list[dict]):
    if not rows:
        logger.info("no rows for %s", path)
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("wrote %s (%d rows)", path, len(rows))


def _summary(rows: list[dict]):
    if not rows:
        logger.info("SUMMARY: no fits")
        return
    liq = [r for r in rows if r["liquid"]]
    rmse = np.array([r["rmse_volpts"] for r in liq]) if liq else np.array([np.nan])
    bfly = np.array([r["min_butterfly_g"] for r in rows])
    logger.info("SUMMARY  smiles=%d liquid=%d  RMSE volpts p50=%.3f p90=%.3f",
                len(rows), len(liq), float(np.median(rmse)), float(np.percentile(rmse, 90)))
    logger.info("  butterfly violation rate (min g<0): %.1f%% of %d",
                100.0 * float((bfly < 0).mean()), len(bfly))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    fits_rows: list[dict] = []
    overlay_rows: list[dict] = []
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        panel = LIQUID + thinnest_tickers(cur, 2)
        logger.info("panel: %s", panel)
        for ticker in panel:
            liquid = ticker in LIQUID
            for mdate in pick_dates(cur, ticker):
                fitted_for_cal = []
                start = len(fits_rows)
                for expiry, dte in nearest_expiries(cur, ticker, mdate).items():
                    rows, spot = load_smile_rows(cur, ticker, mdate, expiry)
                    if spot is None or len(rows) < 8:
                        continue
                    k, iv, w, t, strikes = build_smile(rows, spot, mdate, expiry)
                    if len(k) < 8 or t <= 0:
                        continue
                    try:
                        p, _ = fit_raw_svi(k, w)
                    except Exception as exc:
                        logger.info("fit fail %s %s %s: %r", ticker, mdate, expiry, exc)
                        continue
                    gmin = float(butterfly_g(np.linspace(k.min(), k.max(), 200), p).min())
                    fitted_for_cal.append((expiry, t, p))
                    fits_rows.append(dict(
                        ticker=ticker, market_date=mdate, expiry=expiry, dte=dte,
                        n_strikes=len(k), a=p.a, b=p.b, rho=p.rho, m=p.m, sigma=p.sigma,
                        rmse_volpts=round(rmse_vol_points(k, iv, p, t), 4),
                        min_butterfly_g=round(gmin, 6), liquid=liquid))
                    if abs(dte - 30) <= 10:  # eyeball overlay set = the ~30d expiry
                        iv_fit = np.sqrt(np.maximum(raw_svi_total_variance(k, p), 0.0) / t)
                        for st, kk, mi, fi in zip(strikes, k, iv, iv_fit):
                            overlay_rows.append(dict(
                                ticker=ticker, market_date=mdate, expiry=expiry,
                                strike=st, k=round(float(kk), 5),
                                iv_marked=round(float(mi), 5), iv_fit=round(float(fi), 5),
                                resid_volpts=round(float((mi - fi) * 100.0), 4)))
                cal = calendar_violations(fitted_for_cal)
                for fr in fits_rows[start:]:
                    fr["calendar_viol_on_date"] = cal
    _write_csv(OUT / "fits.csv", fits_rows)
    _write_csv(OUT / "overlays.csv", overlay_rows)
    render_figs(overlay_rows, OUT)
    _summary(fits_rows)
    return 0


def render_figs(overlay_rows: list[dict], out_dir: Path, max_figs: int = 8) -> None:
    """One marked-vs-fit PNG per ticker (latest date's ~30d smile), capped at max_figs."""
    if not overlay_rows:
        return
    plt.switch_backend("Agg")  # headless: render to file, no display
    groups: dict = defaultdict(list)
    for r in overlay_rows:
        groups[(r["ticker"], r["market_date"], r["expiry"])].append(r)
    latest: dict = {}
    for key in groups:
        tk, md, _ = key
        if tk not in latest or md > latest[tk][1]:
            latest[tk] = key
    (out_dir / "figs").mkdir(exist_ok=True)
    picked = list(latest.values())[:max_figs]
    for key in picked:
        pts = sorted(groups[key], key=lambda r: r["k"])
        ks = [p["k"] for p in pts]
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.scatter(ks, [p["iv_marked"] for p in pts], s=12, color="#d62728", label="marked IV")
        ax.plot(ks, [p["iv_fit"] for p in pts], color="#1f77b4", label="SVI fit")
        ax.set_xlabel("log-moneyness k")
        ax.set_ylabel("implied vol")
        ax.set_title(f"{key[0]} {key[1]} exp {key[2]}")
        ax.legend()
        fig.tight_layout()
        fname = f"{key[0]}_{key[1]}_{key[2]}.png".replace(" ", "")
        fig.savefig(out_dir / "figs" / fname, dpi=110)
        plt.close(fig)
    logger.info("wrote %d overlay figs to %s", len(picked), out_dir / "figs")


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Smoke-run against the mini (read-only)**

Run:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
UW_SCAN_ALLOW_DB_MISMATCH=1 \
uv run python scripts/research/svi_surface_fit_probe.py
```
Expected: logs `panel: [...]`, `wrote docs/research/svi-surface-fit/fits.csv (N rows)` with N in the low hundreds, `wrote .../overlays.csv`, `wrote K overlay figs to docs/research/svi-surface-fit/figs`, and a `SUMMARY` line with a finite RMSE p50 and a butterfly violation %.

- [ ] **Step 3: Sanity-check the trace**

Run: `uv run python -c "import csv; rows=list(csv.DictReader(open('docs/research/svi-surface-fit/fits.csv'))); print(len(rows), 'fits;', sum(float(r['rmse_volpts'])<1.0 for r in rows if r['liquid']=='True'), 'liquid under 1 vol pt')"`
Expected: prints a fit count and how many liquid fits are under 1 vol point (a rough health read — not a hard gate).

- [ ] **Step 4: Commit**

```bash
git add scripts/research/svi_surface_fit_probe.py docs/research/svi-surface-fit/fits.csv docs/research/svi-surface-fit/overlays.csv docs/research/svi-surface-fit/figs
git commit -m "feat(svi): panel runner + banked-smile fit traces + overlay figs (feasibility probe)"
```

---

### Task 4: Research note + gate verdict

**Files:**
- Create: `docs/research/svi-surface-fit/README.md`

**Interfaces:**
- Consumes: `fits.csv` / `overlays.csv` numbers from Task 3.
- Produces: the human-readable PASS/FAIL verdict + reproduce command.

- [ ] **Step 1: Compute the headline numbers**

Run:
```bash
uv run python -c "
import csv, statistics as st
r=[x for x in csv.DictReader(open('docs/research/svi-surface-fit/fits.csv'))]
liq=[x for x in r if x['liquid']=='True']
rm=[float(x['rmse_volpts']) for x in liq]
bf=[float(x['min_butterfly_g']) for x in r]
cal=[int(x['calendar_viol_on_date']) for x in r]
print('n_fits', len(r), 'n_liquid', len(liq))
print('rmse volpts p50', round(st.median(rm),3), 'p90', round(sorted(rm)[int(0.9*len(rm))-1],3))
print('butterfly violation rate', round(100*sum(g<0 for g in bf)/len(bf),1),'%')
print('date-panels with >=1 calendar viol', sum(c>0 for c in cal))
"
```

- [ ] **Step 2: Write the note**

Create `docs/research/svi-surface-fit/README.md` filling the bracketed values from Step 1:

```markdown
# SVI Surface-Fit Feasibility Gate — 2026-07-04

**Question:** can raw-SVI fit argon's banked UW IV grid cleanly and arb-free enough
that the fitted-vs-marked residual is a trustworthy mispricing signal?

**Verdict: [PASS | MIXED | FAIL]** — [one-sentence justification].

## Method
- Source: `option_surface_grid_daily` (mini `option_wizard`, read-only), 6-mo history.
- Panel: liquid {SPY,QQQ,NVDA,AAPL,TSLA,MU} + 2 runtime-thinnest tickers × {7,30,90} DTE × ~10 dates.
- Smile from OTM wings (put_iv K<spot, call_iv K>=spot); k=ln(K/spot); w=iv^2*T; T=cal-days/365.
- Raw-SVI (Gatheral) fit via scipy least_squares, multi-start over (m, sigma).
- No-arb diagnostics: butterfly g(k)>=0; calendar total-variance monotonicity at k=0.
- Excludes 0-4 DTE.

## Results
- Fits: [n_fits] ([n_liquid] liquid).
- Fit RMSE (liquid): p50 [x.xx] vol pts, p90 [x.xx] vol pts.
- Butterfly violation rate (min g<0): [xx.x]% of smiles.
- Calendar: [k] date-panels with >=1 violation.
- Failure mode on thin chains: [describe what the thinnest-ticker fits looked like].

## Read
[Is the residual trustworthy? Where does it break — wings? thin chains? short DTE?
What would productionization need — SSVI for calendar arb? wing weighting? IB-IV
cross-check? Name the concrete next step, or the reason to stop here.]

## Reproduce
`UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/research/svi_surface_fit_probe.py`
Traces: `fits.csv` (per-smile params/RMSE/violations), `overlays.csv` (marked-vs-fit per strike, ~30d), `figs/*.png` (per-ticker overlay plots).
```

- [ ] **Step 3: Commit**

```bash
git add docs/research/svi-surface-fit/README.md
git commit -m "docs(svi): feasibility-gate verdict + method + reproduce"
```

---

## Notes for the executor

- **`test_fit_recovers_known_params` is the load-bearing check** — if the fitter can't recover its own synthetic smile, nothing downstream is trustworthy. Never weaken its assertion; fix the fitter (init/multi-start) instead.
- **`test_butterfly_g_hand_value` pins the g(k) formula** at k=0 (≈2.9541, hand-derived for a=0.04,b=0.4,ρ=−0.3,m=0,σ=0.1). A drift here means the diagnostic is wrong, which would silently mislabel arb.
- The runner is **thin orchestration** — its correctness rests on Task 2's tested module + the smoke run. No pytest for the DB path (integration DB is the test-schema, not the prod grid).
- If the smoke run finds the mini unreachable (Tailscale down), that is an environment blocker, not a code failure — report it, don't fabricate numbers.
