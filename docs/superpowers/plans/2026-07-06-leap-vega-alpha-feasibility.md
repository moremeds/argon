# LEAP Vega-Alpha Feasibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine whether radon's "cheap LEAP" thesis — HV20/HV60 minus a long-dated option's ATM IV is a wide positive gap ⇒ the market underprices forward vol ⇒ buying the LEAP is long-vega alpha — is a real, backtestable edge in argon's banked data, and deliver an honest verdict doc.

**Architecture:** Two-stage read-only research spike, mirroring the merged SVI spike (PR #219). Stage 1 is a cheap, falsifiable convergence gate (DB + apex bars only): does a wide entry gap predict the *same LEAP contract's* IV rising over the next 20/40 trading days? Stage 2 runs **only if Stage 1 shows signal** — it marks flagged LEAPs forward and decomposes gross P&L (`vega·ΔIV + delta·ΔS + theta·Δt`), then reports the break-even spread versus a realistic LEAP spread range. All findings persist to `docs/research/leap-vega-alpha/` as a verdict doc + full CSV traces.

**Tech Stack:** Python 3.13 via `uv`; psycopg 3 (read-only over mini `option_wizard`); numpy + scipy (`spearmanr`, already a dep from the SVI work); httpx (apex `/bars`); pytest. Reuses `scripts/research/svi_fit.py::forward_from_delta` for the ATM anchor.

## Global Constraints

- **uv only** — every command is `uv run ...`; never bare `python`/`pytest`.
- **Read-only DB** — this spike issues zero writes/DDL to `option_surface_grid_daily` or any table. It makes **zero UW/IB calls**.
- **DB isolation env** — all DB-touching commands run with `UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1` (mini, prodlike). `Settings.from_env()` requires a `UW_SCAN_API_KEY` present via `.env`/`.env.local` — copy both from the main checkout (gitignored) into the worktree before running; the key only satisfies a config presence guard (no UW calls made).
- **Persist every trace** — full result set (every config × every metric) lands as committed CSVs under `docs/research/leap-vega-alpha/`, plus the exact reproduce command in the verdict doc. stdout-only is data loss.
- **Single-regime caveat is load-bearing** — history is ~6 months / one regime (2025-12-26 → 2026-07-02, 129 dates). The verdict doc must state up front that this validates a short-horizon proxy, **not** hold-to-expiry harvest, and a Stage-1 pass is a "wait for more history" green light, not a deploy signal.
- **No observed NBBO** — the grid carries IV + greeks but no bid/ask, and no historical LEAP NBBO exists. Stage 2 cost is therefore **modeled via break-even**, never a fabricated observed spread.
- **Units decimal** — grid `call_iv`/`put_iv` are decimal (e.g. `0.177`). HV is computed decimal (`0.30` = 30%). Gap thresholds are decimal: {0.10, 0.15, 0.20, 0.25}. Report vol points = decimal × 100.
- **Greek convention** — per repo CLAUDE.md the grid stores IB-native greeks rescaled to BS convention (**vega ×100** = per 1.00 decimal-vol move; **theta ×365** = per calendar year). Stage 2 must verify this empirically against one contract before trusting the P&L decomposition (see Task 5, Step 1).
- **Module size** — target <500 lines/file; the pure library and each probe stay well under.
- **No commits to main / no PR without explicit request** — all commits land on `feat/leap-vega-alpha`. CHANGELOG entry rides this branch (Task 6).
- **Worktree** — already created at `.worktrees/leap-vega-alpha/` on `feat/leap-vega-alpha` (based on `origin/main`, includes the reusable `scripts/research/svi_fit.py`). All paths below are relative to that worktree root.

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/research/leap_vega_alpha.py` (create) | Pure library: `realized_vol`, `atm_iv`, `entry_gap`, `stage1_metrics`. No I/O. Unit-tested. |
| `tests/unit/test_leap_vega_alpha.py` (create) | Unit tests for the four pure functions. |
| `scripts/research/leap_convergence_probe.py` (create) | Stage 1 runner: DB + apex → per-(ticker,expiry,date) gap + forward ΔIV; writes traces; prints summary; makes the kill decision. |
| `scripts/research/leap_pnl_probe.py` (create, GATED) | Stage 2 runner: forward P&L decomposition + break-even spread. Only built if Stage 1 lives. |
| `docs/research/leap-vega-alpha/README.md` (create) | Stage 1 verdict (convergence gate). |
| `docs/research/leap-vega-alpha/edge-test.md` (create, GATED) | Stage 2 verdict (P&L + break-even), or a "gate failed, Stage 2 not run" stub. |
| `docs/research/leap-vega-alpha/*.csv` (create) | `gap_observations.csv`, `convergence_metrics.csv`, `pnl_metrics.csv` — durable traces. |
| `CHANGELOG.md` (modify) | `[Unreleased] Added` entry. |

---

### Task 1: Realized-vol utility

**Files:**
- Create: `scripts/research/leap_vega_alpha.py`
- Test: `tests/unit/test_leap_vega_alpha.py`

**Interfaces:**
- Produces: `realized_vol(closes: Sequence[float], window: int, ann: float = 252.0) -> float | None` — annualized sample stdev of daily log returns over the trailing `window` returns; `None` if fewer than `window + 1` closes.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_leap_vega_alpha.py
import numpy as np
import pytest
from scripts.research.leap_vega_alpha import realized_vol


def test_realized_vol_known_series():
    # 4 closes -> 3 alternating log returns; hand-computed HV.
    # rets = [ln1.02, -ln1.02, ln1.02]; sample-std * sqrt(252) = 0.363.
    hv = realized_vol([100.0, 102.0, 100.0, 102.0], window=3)
    assert hv == pytest.approx(0.363, abs=1e-3)


def test_realized_vol_flat_series_is_zero():
    assert realized_vol([50.0, 50.0, 50.0, 50.0], window=3) == pytest.approx(0.0, abs=1e-12)


def test_realized_vol_insufficient_data_returns_none():
    assert realized_vol([100.0, 101.0], window=20) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'realized_vol'`.

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/research/leap_vega_alpha.py
"""Pure library for the LEAP vega-alpha feasibility spike (read-only research).

realized_vol / atm_iv / entry_gap / stage1_metrics — no I/O, unit-tested.
Consumed by scripts/research/leap_convergence_probe.py (Stage 1) and
leap_pnl_probe.py (Stage 2). Reuses forward_from_delta from svi_fit.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np


def realized_vol(closes: Sequence[float], window: int, ann: float = 252.0) -> float | None:
    """Annualized sample stdev of daily log returns over the trailing `window` returns."""
    if closes is None or len(closes) < window + 1:
        return None
    tail = np.asarray(closes[-(window + 1):], dtype=float)
    rets = np.diff(np.log(tail))
    return float(np.std(rets, ddof=1) * np.sqrt(ann))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_vega_alpha.py tests/unit/test_leap_vega_alpha.py
git commit -m "feat(leap): realized-vol utility for vega-alpha spike"
```

---

### Task 2: ATM-IV extractor + entry gap

**Files:**
- Modify: `scripts/research/leap_vega_alpha.py`
- Test: `tests/unit/test_leap_vega_alpha.py`

**Interfaces:**
- Consumes: `realized_vol` (Task 1); `forward_from_delta` from `scripts.research.svi_fit`.
- Produces:
  - `atm_iv(rows: list[dict]) -> float | None` — IV at the money. `rows` each have `strike`, `call_iv`, `call_delta`. Picks the strike whose `call_delta` is nearest 0.5 and returns its `call_iv`; `None` if no usable row.
  - `entry_gap(hv20: float | None, hv60: float | None, atm: float | None) -> float | None` — `max(hv20, hv60) - atm`; `None` if `atm` is None or both HVs are None.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_leap_vega_alpha.py
from scripts.research.leap_vega_alpha import atm_iv, entry_gap


def test_atm_iv_picks_nearest_half_delta():
    rows = [
        {"strike": 90.0, "call_iv": 0.40, "call_delta": 0.80},
        {"strike": 100.0, "call_iv": 0.30, "call_delta": 0.52},  # nearest 0.5
        {"strike": 110.0, "call_iv": 0.35, "call_delta": 0.20},
    ]
    assert atm_iv(rows) == pytest.approx(0.30)


def test_atm_iv_none_when_no_delta():
    assert atm_iv([{"strike": 100.0, "call_iv": 0.3, "call_delta": None}]) is None


def test_entry_gap_uses_max_hv():
    # max(0.28, 0.35) - 0.20 = 0.15
    assert entry_gap(0.28, 0.35, 0.20) == pytest.approx(0.15)
    assert entry_gap(None, 0.35, 0.20) == pytest.approx(0.15)
    assert entry_gap(0.28, 0.35, None) is None
    assert entry_gap(None, None, 0.20) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -k "atm_iv or entry_gap" -v`
Expected: FAIL with `ImportError: cannot import name 'atm_iv'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/research/leap_vega_alpha.py


def atm_iv(rows: list[dict]) -> float | None:
    """IV at the strike whose call_delta is nearest 0.5 (ATM proxy)."""
    usable = [
        r for r in rows
        if r.get("call_delta") is not None and r.get("call_iv") is not None
    ]
    if not usable:
        return None
    best = min(usable, key=lambda r: abs(float(r["call_delta"]) - 0.5))
    return float(best["call_iv"])


def entry_gap(hv20: float | None, hv60: float | None, atm: float | None) -> float | None:
    """max(hv20, hv60) - atm_iv, all decimal. None if atm missing or both HVs missing."""
    if atm is None:
        return None
    hvs = [h for h in (hv20, hv60) if h is not None]
    if not hvs:
        return None
    return max(hvs) - atm
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_vega_alpha.py tests/unit/test_leap_vega_alpha.py
git commit -m "feat(leap): ATM-IV extractor + entry-gap"
```

---

### Task 3: Stage-1 convergence metrics

**Files:**
- Modify: `scripts/research/leap_vega_alpha.py`
- Test: `tests/unit/test_leap_vega_alpha.py`

**Interfaces:**
- Produces: `stage1_metrics(gaps: Sequence[float], d_ivs: Sequence[float], threshold: float) -> dict` — takes aligned entry gaps and same-contract forward ΔIV (decimal). Returns
  `{"n": int, "rank_ic": float, "baseline_mean_div": float, "flagged_n": int, "flagged_mean_div": float, "hit_rate": float}` where:
  - `rank_ic` = Spearman correlation of `gaps` vs `d_ivs` (positive ⇒ wider gap predicts IV rising),
  - `baseline_mean_div` = mean ΔIV over all pairs (unconditional control),
  - flagged = subset with `gap >= threshold`,
  - `hit_rate` = fraction of flagged with `d_iv > 0`.
  NaNs where a stat is undefined (e.g. `flagged_n == 0`).

- [ ] **Step 1: Write the failing test**

```python
# append to tests/unit/test_leap_vega_alpha.py
from scripts.research.leap_vega_alpha import stage1_metrics


def test_stage1_metrics_positive_relationship():
    # ΔIV increases monotonically with gap -> rank_ic == 1.0
    gaps = [0.05, 0.10, 0.20, 0.30]
    d_ivs = [-0.01, 0.00, 0.02, 0.05]
    m = stage1_metrics(gaps, d_ivs, threshold=0.15)
    assert m["n"] == 4
    assert m["rank_ic"] == pytest.approx(1.0)
    assert m["flagged_n"] == 2          # gaps 0.20, 0.30
    assert m["hit_rate"] == pytest.approx(1.0)   # both ΔIV > 0
    assert m["flagged_mean_div"] == pytest.approx(0.035)


def test_stage1_metrics_no_flagged():
    m = stage1_metrics([0.01, 0.02], [0.0, 0.0], threshold=0.15)
    assert m["flagged_n"] == 0
    assert np.isnan(m["hit_rate"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -k stage1 -v`
Expected: FAIL with `ImportError: cannot import name 'stage1_metrics'`.

- [ ] **Step 3: Write minimal implementation**

```python
# append to scripts/research/leap_vega_alpha.py
from scipy.stats import spearmanr


def stage1_metrics(gaps, d_ivs, threshold: float) -> dict:
    """Convergence metrics: rank-IC of gap vs forward ΔIV, plus flagged-subset stats."""
    g = np.asarray(gaps, dtype=float)
    d = np.asarray(d_ivs, dtype=float)
    n = int(g.size)
    rank_ic = float(spearmanr(g, d).statistic) if n >= 2 else float("nan")
    flagged = g >= threshold
    fn = int(flagged.sum())
    return {
        "n": n,
        "rank_ic": rank_ic,
        "baseline_mean_div": float(d.mean()) if n else float("nan"),
        "flagged_n": fn,
        "flagged_mean_div": float(d[flagged].mean()) if fn else float("nan"),
        "hit_rate": float((d[flagged] > 0).mean()) if fn else float("nan"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_vega_alpha.py tests/unit/test_leap_vega_alpha.py
git commit -m "feat(leap): Stage-1 convergence metrics (rank-IC + flagged stats)"
```

---

### Task 4: Stage-1 convergence probe (integration runner + verdict)

**Files:**
- Create: `scripts/research/leap_convergence_probe.py`
- Create: `docs/research/leap-vega-alpha/README.md`
- Create (by running): `docs/research/leap-vega-alpha/{gap_observations,convergence_metrics}.csv`

**Interfaces:**
- Consumes: everything from Tasks 1–3; `forward_from_delta` from `svi_fit`; `Settings.from_env`; apex `/bars/{ticker}`.
- Produces: `main() -> int`. Run as a module (repo root on `sys.path` for the `scripts` namespace):
  `... uv run python -m scripts.research.leap_convergence_probe`.

**Design notes (read before writing):**
- **Panel:** the LIQUID set `["SPY","QQQ","NVDA","AAPL","TSLA","MU"]` plus 4 more high-OI single names from the banked universe (query the 10 tickers with the most LEAP rows on the latest date). LEAP tenor per (ticker,date) = the expiry nearest **420 DTE** with `(expiry - market_date) >= 365`.
- **Entry dates:** all 129 banked dates that leave ≥ `h` forward grid-dates for the same contract (so ΔIV is measurable). Horizons `h ∈ {20, 40}` trading days = 20/40 grid-dates ahead for that (ticker, expiry).
- **ATM contract:** per (ticker, expiry, entry date) load grid rows, clip to `call_delta ∈ [0.05, 0.95]` (reuse the SVI delta band — kills junk deep-wing marks), pick the ATM strike via `atm_iv` and record that exact strike. Forward ΔIV = same (ticker, expiry, strike)'s `call_iv` at entry+h minus at entry.
- **HV:** fetch each ticker's daily closes once from apex `/bars/{ticker}?timeframe=1d&start=<entry_min-100d>&end=<entry_max>`; compute `realized_vol(closes_up_to_entry, 20)` and `(…, 60)` as of each entry date. apex history predates the surface window, so HV60 is available even for early entries.
- **Sanity gates that must print (fail loud, don't silently proceed):** (a) HV and IV both decimal and in a plausible band (0.05–3.0); (b) forward ΔIV distribution not degenerate (std > 0); (c) ≥ 200 aligned (entry, h) pairs or the run is under-powered — log it.
- **Kill decision:** for each `h` and threshold in {0.10,0.15,0.20,0.25}, print `stage1_metrics`. Signal = flagged `hit_rate` materially > 0.5 **and** positive `rank_ic` **and** `flagged_mean_div > baseline_mean_div`, consistently across thresholds. Otherwise the gate FAILS → write the negative README, do **not** proceed to Stage 2.

- [ ] **Step 1: Write the probe runner**

```python
# scripts/research/leap_convergence_probe.py
"""Stage 1 — LEAP cheap-vol convergence gate (read-only: DB + apex bars, ZERO UW/IB).

Does a wide HV-minus-LEAP-ATM-IV entry gap predict the SAME contract's IV rising
over the next 20/40 trading days? Writes traces + prints the kill decision.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

import httpx
import numpy as np
import psycopg

from scripts.research.leap_vega_alpha import atm_iv, entry_gap, realized_vol, stage1_metrics
from uw_scan.config import Settings

logger = logging.getLogger("leap_probe")
logging.basicConfig(level=logging.INFO, format="%(message)s")

LIQUID = ["SPY", "QQQ", "NVDA", "AAPL", "TSLA", "MU"]
TARGET_DTE = 420
DTE_FLOOR = 365
HORIZONS = [20, 40]
THRESHOLDS = [0.10, 0.15, 0.20, 0.25]
DELTA_BAND = (0.05, 0.95)
APEX = "http://100.66.147.98:8322"
OUT = Path("docs/research/leap-vega-alpha")


def apex_closes(ticker: str, start: dt.date, end: dt.date) -> dict[dt.date, float]:
    """Date->close from apex daily bars. Empty dict on any failure (logged)."""
    url = f"{APEX}/bars/{ticker}?timeframe=1d&start={start}&end={end}"
    try:
        r = httpx.get(url, timeout=15.0)
        r.raise_for_status()
        bars = r.json().get("bars", [])
    except Exception as exc:  # noqa: BLE001 - research probe, log and skip ticker
        logger.info("apex fail %s: %r", ticker, exc)
        return {}
    out = {}
    for b in bars:
        d = dt.date.fromisoformat(b["time"][:10])
        if b.get("close") is not None:
            out[d] = float(b["close"])
    return out


def hv_asof(closes_by_date: dict[dt.date, float], asof: dt.date, window: int) -> float | None:
    series = [c for d, c in sorted(closes_by_date.items()) if d <= asof]
    return realized_vol(series, window)


def top_leap_tickers(cur, n: int) -> list[str]:
    cur.execute(
        "SELECT ticker, count(*) AS c FROM option_surface_grid_daily "
        "WHERE market_date=(SELECT max(market_date) FROM option_surface_grid_daily) "
        "AND (expiry-market_date) >= %s GROUP BY ticker ORDER BY c DESC LIMIT %s",
        (DTE_FLOOR, n),
    )
    return [r[0] for r in cur.fetchall()]


def leap_expiry(cur, ticker: str, mdate: dt.date) -> dt.date | None:
    cur.execute(
        "SELECT expiry FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND (expiry-market_date) >= %s "
        "ORDER BY abs((expiry-market_date) - %s) LIMIT 1",
        (ticker, mdate, DTE_FLOOR, TARGET_DTE),
    )
    row = cur.fetchone()
    return row[0] if row else None


def atm_rows(cur, ticker: str, mdate: dt.date, expiry: dt.date) -> list[dict]:
    cur.execute(
        "SELECT strike, call_iv, call_delta FROM option_surface_grid_daily "
        "WHERE ticker=%s AND market_date=%s AND expiry=%s ORDER BY strike",
        (ticker, mdate, expiry),
    )
    lo, hi = DELTA_BAND
    return [
        {"strike": s, "call_iv": (float(c) if c is not None else None),
         "call_delta": (float(d) if d is not None else None)}
        for s, c, d in cur.fetchall()
        if d is not None and lo <= float(d) <= hi
    ]


def iv_on(cur, ticker: str, expiry: dt.date, strike, mdate: dt.date) -> float | None:
    cur.execute(
        "SELECT call_iv FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND strike=%s AND market_date=%s",
        (ticker, expiry, strike, mdate),
    )
    row = cur.fetchone()
    return float(row[0]) if row and row[0] is not None else None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    s = Settings.from_env()
    obs: list[dict] = []
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        panel = list(dict.fromkeys(LIQUID + top_leap_tickers(cur, 10)))
        logger.info("panel: %s", panel)
        cur.execute("SELECT DISTINCT market_date FROM option_surface_grid_daily ORDER BY market_date")
        all_dates = [r[0] for r in cur.fetchall()]
        dmin, dmax = all_dates[0], all_dates[-1]
        for ticker in panel:
            closes = apex_closes(ticker, dmin - dt.timedelta(days=120), dmax)
            if not closes:
                continue
            # per-ticker grid dates (index positions let us step h forward)
            cur.execute(
                "SELECT DISTINCT market_date FROM option_surface_grid_daily "
                "WHERE ticker=%s ORDER BY market_date", (ticker,))
            tdates = [r[0] for r in cur.fetchall()]
            pos = {d: i for i, d in enumerate(tdates)}
            for i, mdate in enumerate(tdates):
                expiry = leap_expiry(cur, ticker, mdate)
                if expiry is None:
                    continue
                rows = atm_rows(cur, ticker, mdate, expiry)
                atm = atm_iv(rows)
                if atm is None:
                    continue
                strike = min(rows, key=lambda r: abs(r["call_delta"] - 0.5))["strike"]
                hv20 = hv_asof(closes, mdate, 20)
                hv60 = hv_asof(closes, mdate, 60)
                gap = entry_gap(hv20, hv60, atm)
                if gap is None:
                    continue
                for h in HORIZONS:
                    j = i + h
                    if j >= len(tdates):
                        continue
                    fwd = iv_on(cur, ticker, expiry, strike, tdates[j])
                    if fwd is None:
                        continue
                    obs.append(dict(
                        ticker=ticker, market_date=mdate, expiry=expiry, strike=strike,
                        dte=(expiry - mdate).days, hv20=hv20, hv60=hv60, atm_iv=atm,
                        gap=round(gap, 5), horizon=h, iv_fwd=fwd,
                        d_iv=round(fwd - atm, 5),
                    ))
    _write_csv(OUT / "gap_observations.csv", obs)
    _summary_and_metrics(obs)
    return 0


def _write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        logger.info("no rows for %s", path)
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    logger.info("wrote %s (%d rows)", path, len(rows))


def _summary_and_metrics(obs: list[dict]) -> None:
    metric_rows: list[dict] = []
    for h in HORIZONS:
        sub = [o for o in obs if o["horizon"] == h]
        if len(sub) < 2:
            logger.info("h=%d: under-powered (%d pairs)", h, len(sub))
            continue
        gaps = [o["gap"] for o in sub]
        d_ivs = [o["d_iv"] for o in sub]
        # sanity gates
        ivs = [o["atm_iv"] for o in sub]
        if not all(0.05 <= v <= 3.0 for v in ivs):
            logger.info("WARN h=%d: IV out of plausible band", h)
        if np.std(d_ivs) == 0:
            logger.info("WARN h=%d: degenerate ΔIV (std=0)", h)
        if len(sub) < 200:
            logger.info("WARN h=%d: only %d pairs (<200) — under-powered", h, len(sub))
        for thr in THRESHOLDS:
            m = stage1_metrics(gaps, d_ivs, thr)
            m.update(horizon=h, threshold=thr)
            metric_rows.append(m)
            logger.info(
                "h=%d thr=%.2f  n=%d rankIC=%.3f base_dIV=%.4f  flagged=%d hit=%.3f mean_dIV=%.4f",
                h, thr, m["n"], m["rank_ic"], m["baseline_mean_div"],
                m["flagged_n"], m["hit_rate"], m["flagged_mean_div"],
            )
    _write_csv(OUT / "convergence_metrics.csv", metric_rows)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the probe against the mini (real data)**

Run:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
```
Expected: panel printed; `wrote docs/research/leap-vega-alpha/gap_observations.csv (N rows)` with N in the thousands; a metrics block per horizon×threshold; `convergence_metrics.csv` written. Copy `.env` + `.env.local` from the main checkout into the worktree first if `Settings.from_env()` errors on a missing key.

- [ ] **Step 3: Verify the evidence critically**

Read `convergence_metrics.csv`. Confirm: (a) `n` ≥ 200 per horizon (else note under-power in the verdict); (b) IVs were in-band (no WARN); (c) ΔIV not degenerate. Then apply the kill decision: is flagged `hit_rate` materially > 0.5 with positive `rank_ic` and `flagged_mean_div > baseline_mean_div`, consistently across thresholds?

- [ ] **Step 4: Write the Stage-1 verdict**

Write `docs/research/leap-vega-alpha/README.md`: the falsified claim, method (panel, tenor, HV source, ATM anchor, delta band), the metrics table copied from the CSV, and the verdict (SIGNAL → proceed to Stage 2 / NO SIGNAL → stop). Lead with the single-regime caveat. Include the exact reproduce command. Mirror the tone/structure of the merged SVI `docs/research/svi-surface-fit/README.md`.

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_convergence_probe.py docs/research/leap-vega-alpha/README.md \
        docs/research/leap-vega-alpha/gap_observations.csv docs/research/leap-vega-alpha/convergence_metrics.csv
git commit -m "feat(leap): Stage-1 convergence probe + verdict"
```

---

### Task 5: Stage-2 short-hold vega P&L (GATED on Stage-1 signal)

> **Gate:** Only do this task if Task 4's verdict is SIGNAL. If NO SIGNAL, skip to Task 6 and write the `edge-test.md` stub noting the gate failed and Stage 2 was intentionally not run (cite the SVI precedent: a clean negative is a valid deliverable).

**Files:**
- Create: `scripts/research/leap_pnl_probe.py`
- Create: `docs/research/leap-vega-alpha/edge-test.md`
- Create (by running): `docs/research/leap-vega-alpha/pnl_metrics.csv`

**Interfaces:**
- Consumes: `gap_observations.csv` (flagged entries) + the grid greeks (`call_vega`, `call_delta`, `call_theta`) + apex closes for ΔS.
- Produces: `main() -> int`, run as `... uv run python -m scripts.research.leap_pnl_probe`.

- [ ] **Step 1: Verify greek units empirically (before trusting P&L)**

Run this one-off check and record the result in `edge-test.md`:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
uv run python - <<'PY'
import psycopg
from uw_scan.config import Settings
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c, c.cursor() as cur:
    cur.execute("SET search_path TO uw_scan, public")
    cur.execute("SELECT ticker,expiry,strike,call_iv,call_delta,call_vega,call_theta,call_gamma "
                "FROM option_surface_grid_daily WHERE ticker='AAPL' AND (expiry-market_date)>=365 "
                "AND call_delta BETWEEN 0.45 AND 0.55 "
                "ORDER BY market_date DESC LIMIT 3")
    for r in cur.fetchall(): print(r)
PY
```
Expected: interpret vega magnitude. Under BS "vega ×100" convention a ~1yr ATM equity option's `call_vega` ≈ price move per 1.0 decimal-vol; a per-1%-vol reading is ~1/100th that. Set the P&L scale from what you observe; if the observed magnitude contradicts the CLAUDE.md note, trust the data and document the discrepancy. **Do not proceed until the unit is pinned.**

- [ ] **Step 2: Write the P&L probe**

```python
# scripts/research/leap_pnl_probe.py
"""Stage 2 — forward vega-alpha P&L on Stage-1-flagged LEAP entries (read-only).

Reads gap_observations.csv, marks each flagged entry forward h days, decomposes
gross P&L = vega·ΔIV + delta·ΔS + theta·Δt, and reports the BREAK-EVEN spread
(the entry spread in vol points that would erase the edge) — never an observed
spread, because no historical LEAP NBBO exists.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
"""

from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

import numpy as np
import psycopg

from scripts.research.leap_convergence_probe import apex_closes
from uw_scan.config import Settings

logger = logging.getLogger("leap_pnl")
logging.basicConfig(level=logging.INFO, format="%(message)s")

OUT = Path("docs/research/leap-vega-alpha")
FLAG_THRESHOLD = 0.15  # set to the Stage-1 threshold that showed signal
VEGA_PER = 100.0       # set from Task 5 Step 1: decimal-vol move covered by call_vega


def _greeks(cur, ticker, expiry, strike, mdate):
    cur.execute(
        "SELECT call_iv, call_delta, call_vega, call_theta FROM option_surface_grid_daily "
        "WHERE ticker=%s AND expiry=%s AND strike=%s AND market_date=%s",
        (ticker, expiry, strike, mdate),
    )
    r = cur.fetchone()
    if not r or any(v is None for v in r):
        return None
    return dict(iv=float(r[0]), delta=float(r[1]), vega=float(r[2]), theta=float(r[3]))


def main() -> int:
    src = OUT / "gap_observations.csv"
    if not src.exists():
        logger.info("run Stage 1 first (%s missing)", src)
        return 1
    with src.open() as f:
        flagged = [r for r in csv.DictReader(f) if float(r["gap"]) >= FLAG_THRESHOLD]
    s = Settings.from_env()
    pnl_rows: list[dict] = []
    close_cache: dict[str, dict] = {}
    with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SET search_path TO uw_scan, public")
        for r in flagged:
            tk, exp = r["ticker"], dt.date.fromisoformat(r["expiry"])
            strike, m0, h = r["strike"], dt.date.fromisoformat(r["market_date"]), int(r["horizon"])
            g0 = _greeks(cur, tk, exp, strike, m0)
            if g0 is None:
                continue
            cur.execute(
                "SELECT DISTINCT market_date FROM option_surface_grid_daily "
                "WHERE ticker=%s ORDER BY market_date", (tk,))
            tdates = [x[0] for x in cur.fetchall()]
            if m0 not in tdates:
                continue
            j = tdates.index(m0) + h
            if j >= len(tdates):
                continue
            m1 = tdates[j]
            g1 = _greeks(cur, tk, exp, strike, m1)
            if g1 is None:
                continue
            if tk not in close_cache:
                close_cache[tk] = apex_closes(tk, m0 - dt.timedelta(days=10), tdates[-1])
            closes = close_cache[tk]
            if m0 not in closes or m1 not in closes:
                continue
            d_iv = g1["iv"] - g0["iv"]
            d_s = closes[m1] - closes[m0]
            d_t = (m1 - m0).days / 365.0
            pnl_vega = g0["vega"] * d_iv * (VEGA_PER / 100.0)  # to per-1%-consistent $ if needed
            pnl_delta = g0["delta"] * d_s
            pnl_theta = g0["theta"] * d_t
            gross = pnl_vega + pnl_delta + pnl_theta
            pnl_rows.append(dict(
                ticker=tk, market_date=m0, expiry=exp, strike=strike, horizon=h,
                gap=r["gap"], d_iv=round(d_iv, 5), d_s=round(d_s, 4),
                pnl_vega=round(pnl_vega, 4), pnl_delta=round(pnl_delta, 4),
                pnl_theta=round(pnl_theta, 4), gross=round(gross, 4),
                vega=g0["vega"],
                breakeven_spread_vp=round(abs(pnl_vega) / g0["vega"] * 100.0, 4) if g0["vega"] else None,
            ))
    _write(pnl_rows)
    return 0


def _write(rows: list[dict]) -> None:
    if not rows:
        logger.info("no flagged P&L rows")
        return
    with (OUT / "pnl_metrics.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    gross = np.array([r["gross"] for r in rows])
    vega_pnl = np.array([r["pnl_vega"] for r in rows])
    logger.info("flagged=%d  mean gross $=%.3f  mean vega-P&L $=%.3f  win%%=%.1f",
                len(rows), gross.mean(), vega_pnl.mean(), 100 * (gross > 0).mean())
    be = np.array([r["breakeven_spread_vp"] for r in rows if r["breakeven_spread_vp"] is not None])
    logger.info("median break-even spread = %.2f vol pts (compare to realistic LEAP spread 1-3+ vp)",
                float(np.median(be)))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run it against real data**

Run:
```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
```
Expected: `pnl_metrics.csv` written; a mean gross $, mean vega-P&L $, win %, and median break-even spread printed.

- [ ] **Step 4: Write the Stage-2 verdict**

Write `docs/research/leap-vega-alpha/edge-test.md`: the greek-unit finding (Step 1), the P&L decomposition table, the break-even spread vs realistic LEAP spread (1–3+ vol points — cite that ATM LEAP spreads are wide), and the taker verdict. Mirror the merged SVI `residual-edge-test.md`. State the single-regime caveat and that vega-P&L, not delta, must be the edge (delta is directional noise to be hedged, not harvested).

- [ ] **Step 5: Commit**

```bash
git add scripts/research/leap_pnl_probe.py docs/research/leap-vega-alpha/edge-test.md \
        docs/research/leap-vega-alpha/pnl_metrics.csv
git commit -m "feat(leap): Stage-2 vega-alpha P&L + break-even verdict"
```

---

### Task 6: CHANGELOG entry + final polish

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/research/leap-vega-alpha/README.md` (cross-link to `edge-test.md` if Stage 2 ran; else note gate stopped at Stage 1)

- [ ] **Step 1: Add the `[Unreleased]` entry**

Under `## [Unreleased]` → `### Added` in `CHANGELOG.md`, add one line:
```markdown
- LEAP vega-alpha feasibility spike (`docs/research/leap-vega-alpha/`): tested radon's cheap-LEAP thesis (HV−LEAP-IV gap → long-vega alpha) on 6 months of banked surface data. Verdict: <SIGNAL / NO SIGNAL — fill from the run>. Reusable pure lib `scripts/research/leap_vega_alpha.py` + convergence/P&L probes.
```

- [ ] **Step 2: Run the full unit suite once more**

Run: `uv run pytest tests/unit/test_leap_vega_alpha.py -v`
Expected: all pass (8 tests).

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md docs/research/leap-vega-alpha/README.md
git commit -m "docs(leap): changelog entry + verdict cross-links"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** convergence gate (Tasks 1–4), gated P&L (Task 5), verdict docs + traces (Tasks 4–6), single-regime caveat (Global Constraints + verdict steps), break-even cost model (Task 5). All design points map to a task.
- **Placeholder scan:** the only intentional fill-ins are run-output values (metrics, verdict direction, `VEGA_PER`/`FLAG_THRESHOLD` set from Stage-1/greek-unit findings) — these are results-from-real-runs, not design placeholders, and each is flagged at its step.
- **Type consistency:** `realized_vol`/`atm_iv`/`entry_gap`/`stage1_metrics` signatures are used identically in the probes; `atm_iv` and the probe's `strike` selection use the same nearest-0.5-delta rule.
- **Reuse:** `forward_from_delta` available from the merged `svi_fit.py`; delta band `(0.05, 0.95)` carried over verbatim; verdict docs mirror the SVI spike structure.

## Reproduce (whole spike)

```bash
# Stage 1 (always):
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_convergence_probe
# Stage 2 (only if Stage 1 shows signal):
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -m scripts.research.leap_pnl_probe
uv run pytest tests/unit/test_leap_vega_alpha.py -v
```
