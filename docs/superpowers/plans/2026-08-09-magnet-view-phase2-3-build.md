# Magnet View — Phase 2/3 build plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the "Magnet View" sub-tab inside the stock Technicals tab — the reference chart's layout and style, with an options-implied cone whose bands carry measured confidence labels and 0.618 levels demoted to unlabelled geometry.

**Architecture:** Pure compute in `cards/magnets.py` (already holds `Pivot`/`all_pivots`), a contract model in `models/magnets.py`, one read-only endpoint `GET /stock/{ticker}/magnets`, and four React components under `web/components/stock/tabs/technicals/`. The sub-tab toggles the existing chart via `localStorage`, matching the pattern `TechnicalsPriceChart.tsx` already uses.

**Tech Stack:** Python 3.13 (`uv` only), FastAPI + Pydantic v2, psycopg 3, Next.js 16 + React 19, lightweight-charts v5.2, vitest.

**Branch:** `feat/technicals-magnet-view` (already checked out, 10 commits ahead of `main`). Do not open a new branch — Task 0 lands on this one.

## Global Constraints

- **The shipped cone must be constructed identically to the calibrated one.** Same `sigma` source (`atm_iv_at_horizon` on `option_surface_grid_daily`), same `target_dte = round(h * 7/5)`, same `T = h/252`, same z-definition. If any of these drift, the measured coverage numbers in `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md` no longer describe what is drawn. Task 2 enforces this with a round-trip test.
- **Horizons: 5, 10, 21 trading days.** Bands at **1.0σ and 1.96σ only**. No 99% band — the research measured the far tail needs 8–17% more width than the closed form (`VERDICT.md`, inverse table).
- **`k_shrink` ships as 1.0** (uncalibrated) and **MULTIPLIES** z, so k < 1 narrows the band — matching the research's `coverage(z_test / k_train, level)` convention (`magnet_cone_calibration.py:314`). Dividing would draw the reciprocal band. The parameter stays in the signature because a corrected G2 estimator is pre-registered future work.
- **Band labels state MEASURED confidence with its 95% interval and the sample window**, never a bare nominal or a bare point estimate. Per horizon, from `confidence_curve.csv`.
- **0.618 levels render as unlabelled geometry** with role text "0.618 extension (no measured edge)". No target sentence, no distance-% headline, no "+30.7%" framing. G1 failed and was confirmed after data cleaning.
- **Palette follows the reference, not argon CSS tokens** — a deliberate documented deviation (spec §5.1). Do not "fix" it.
- **Jitter must be deterministic** (seeded from price-bin index, never `Math.random`) — Task 9.
- **No synthetic prices in tests.** Every price fixture is real AAPL OHLC frozen from the mini at authoring time, in `tests/fixtures/aapl_daily.py`. No round-number ladders, no placeholder tickers.
- No `Co-Authored-By` trailers. CHANGELOG entry rides this branch. Never `git add -A`.

## Reconciliation with the spec and the research verdict

Three points where the controlling documents disagree with each other or with
this plan. Each is resolved explicitly so the outcome reads as a decision.

**0. The spec contradicts itself about the fan; §1.2 wins and the paths are cut.**
Spec §5.2 describes "three dashed level-seeking paths … green `bull path` →
STRETCH". Spec §1.2 says the opposite, as a stated design consequence:

> **Design consequence:** argon replaces the decorative fan with a real forward
> density. The rendering primitive for that already exists.

§1.2 is the earlier and more fundamental statement — it is the reason the cone
research was commissioned at all — and `VERDICT.md` §"What Plan B ships" item 2
independently pushes the same way. **So the scenario paths are not built.** The
cone is the fan's replacement, not its backdrop.

This also removes the objection that a line terminating at STRETCH promotes a
disproven level as a destination: nothing terminates there. The 0.618 levels
remain as price lines in the level stack, labelled "no measured edge", and the
disagreement spec §5.2 wants visible is carried by those lines sitting inside or
outside the cone drawn on the same axis — which `build_read` also states in words.

An earlier draft of this plan kept the paths and argued they should merely be
de-emphasised. That was wrong: it defended a fan the spec had already retired.

**1. 21d ships, at 1.0σ / 1.96σ, not at the empirical 1.011σ / 2.139σ.**
Two separate objections have to be cleared, because the spec and the verdict
disagree for different reasons.

_Why 21d ships at all, against spec §3.3's "withheld"._ The spec withheld it on
one stated ground: **6 non-overlapping windows per ticker has no power**. That
reason is now obsolete. The corrected run reports 21d with **708 independent
observations** under the panel block bootstrap (`VERDICT.md` §E1), not 6 — the
spec was counting per-ticker non-overlapping windows before the pooled
dependence structure was measured. Its CIs are still the widest of the three
(mean band CI width 7.9pt vs 4.5pt at 5d) and the legend says so.

_Why not the verdict's widening._ The verdict suggested 1.011σ / 2.139σ so the
band delivers the _nominal_ 68.27% / 95%. Rejected.

The obvious objection to rejecting it is that this plan happily _labels_ with the
same in-sample measurement it refuses to _fit_ with — so answer that first,
because it is the load-bearing distinction:

> Using a measurement to **set** the band makes the band a fitted object with one
> free parameter per horizon, and the number it then advertises (95%) is the
> target it was fitted to hit — unfalsifiable on the data that produced it.
> Using it to **describe** a band the model fixed in advance is an ordinary
> backward-looking statistic: the band would sit at 1.96σ whether or not anyone
> had measured it, and the label reports what happened, which the same data can
> legitimately answer.

That asymmetry is the argument. The Global-Constraint clash is a consequence of
it, not a second independent reason: once the band moves to 2.139σ, the
`confidence_curve.csv` numbers stop describing what is on screen and there is
nothing honest left to label it with.

So 21d draws the closed-form band and labels the truth: 67.7% and 93.3%, **with
the interval**. Its legend carries one extra clause — _"21d errors run narrow;
treat this band as a floor"_ — which is the disclosure the verdict was reaching
for, without the fit.

**2. The magnet dot-cloud profile is deferred to its own task (Task 9), not cut.**
Spec §5.2 wants the volume-at-price profile rendered as a jittered dot cloud with
the last 15 sessions in gold. the computed bins carry aggregate buy/sell volume
and **no recency provenance** (`VpBin` at `web/lib/volumeProfile.ts:21-26`), so "add a render mode, the maths is
untouched" is false — the gold subset needs the bin computation extended, in a
primitive the Price view also uses. That is a real change to shared code and it
is the one piece of this plan with zero analytic content. It ships last, behind
everything that carries measurement.

## Measured constants (from Phase 1 — do not re-derive)

Cone band → measured confidence **and its 95% panel-bootstrap interval**, for the
legend:

| Horizon | 1.0σ contains      | 1.96σ contains     | n dates |
| ------- | ------------------ | ------------------ | ------- |
| 5d      | 70.9% [67.7, 75.5] | 95.1% [93.9, 96.3] | 149     |
| 10d     | 71.2% [66.6, 75.8] | 94.7% [92.4, 96.5] | 144     |
| 21d     | 67.7% [61.7, 73.1] | 93.3% [90.1, 96.4] | 133     |

Source: `docs/research/2026-08-08-magnet-cone-calibration/confidence_curve.csv`.

**The interval is not optional decoration — it ships in the label.** A bare
"70.9%" reads as a precise probability when the underlying estimate spans nearly
8 points, comes from a single ~8-month window in one volatility regime, and is a
backward-looking frequency rather than a forecast for the next 5 days. The legend
therefore reads _"1σ band held 71% of moves (67.7–75.5%, 149 sessions,
Dec 2025–Jul 2026)"_ — a measurement with its uncertainty and its window, not a
probability claim. `MEASURED_CONFIDENCE` carries the point estimate for the
tooltip; `MEASURED_CONFIDENCE_CI` carries the interval.

## File structure

| File                                                                | Responsibility                                                                     |
| ------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `src/uw_scan/reports/magnet_data.py` (commit in Task 0)             | corporate-action + calendar-gap guards                                             |
| `tests/fixtures/aapl_daily.py` (create)                             | 45 real frozen AAPL sessions, shared by unit + integration tests                   |
| `src/uw_scan/cards/magnets.py` (modify)                             | add `magnet_levels`, `cone`, `build_read` beside existing `Pivot`/`all_pivots`     |
| `src/uw_scan/models/magnets.py` (create)                            | `MagnetPivot`, `MagnetLevels`, `MagnetConeBand`, `MagnetCandle`, `MagnetsResponse` |
| `src/uw_scan/api/routers/stock.py` (modify)                         | `GET /stock/{ticker}/magnets`                                                      |
| `web/lib/api.ts` (modify)                                           | `api.magnets(ticker)`                                                              |
| `web/components/stock/tabs/technicals/MagnetSubTab.tsx` (create)    | composite + data fetch + toggle                                                    |
| `web/components/stock/tabs/technicals/MagnetChart.tsx` (create)     | the chart                                                                          |
| `web/components/stock/tabs/technicals/MagnetTable.tsx` (create)     | level table                                                                        |
| `web/components/stock/tabs/technicals/MagnetRead.tsx` (create)      | THE READ bullets                                                                   |
| `web/lib/lwc/volumeProfile.ts` (modify)                             | add dot-cloud render mode + `binJitter`                                            |
| `web/tests/e2e/{magnet-view.spec.ts,technicals-fixture-server.mjs}` | browser coverage: no console errors, no NaN, no `%` on a 0.618 label               |

**No new `lib/lwc` primitive.** The cone edges and the scenario paths are forward
`LineSeries`, the shape `DensityConeChart.tsx:355-380` already uses. See Task 7.

**Already done in Phase 1, do not redo:** spec §4's `last_pivot_index` → `all_pivots`
refactor shipped in commit `83b0387`; `cards/technicals.py:528` is already a thin
wrapper and `tests/unit/test_magnets_pivots.py` guards it against a frozen copy.

---

### Task 0: Land the Phase-1 corrections

Phase 1 ran, then two data-integrity defects were found and fixed, and both
experiments were re-run. Those corrections are still in the working tree. Task 4
imports `trim_to_clean_segment`, so nothing downstream can start until this lands.

The last committed message (`a8dd3d5`, "Phase 1 verdict — G1/G2/G3 all FAIL") is
now **wrong**: G2 passes at 5d and G3 reversed. Do not rewrite that commit; the
new one supersedes it and says so.

**Files:**

- Commit (modified): `src/uw_scan/reports/magnet_data.py`, `tests/unit/test_magnet_data.py`, `scripts/research/magnet_cone_calibration.py`, `scripts/research/magnet_first_passage.py`, and the six modified files under `docs/research/2026-08-08-magnet-cone-calibration/`
- Commit (new): `docs/research/2026-08-08-magnet-cone-calibration/confidence_curve.csv`, `docs/superpowers/plans/2026-08-09-magnet-view-phase2-3-build.md`

- [ ] **Step 1: Confirm the guards are green and lint-clean**

```bash
uv run pytest tests/unit/test_magnet_data.py -v
uv run ruff check src/uw_scan/reports/magnet_data.py tests/unit/test_magnet_data.py \
                  scripts/research/magnet_cone_calibration.py scripts/research/magnet_first_passage.py
```

Expected: 19 passed, lint clean.

- [ ] **Step 2: Confirm the verdict matches the re-run artefacts**

```bash
uv run python -c "
import json, pathlib
d = pathlib.Path('docs/research/2026-08-08-magnet-cone-calibration')
s = json.loads((d / 'summary.json').read_text())
q = s['data_quality_drops']
assert q['split_spanning_windows'] == 72 and q['calendar_gap_windows'] == 15, q
assert s['n_obs'] == 47034 and s['n_tickers'] == 119, (s['n_obs'], s['n_tickers'])
g2 = s['g2_oos_calibration']['5']
assert round(g2['k_train'], 4) == 0.9747, g2['k_train']
assert g2['oos_cov_1.0_improved'] is True
assert (d / 'confidence_curve.csv').exists()
print('corrected run confirmed:', s['date_range'], q['split_dates_by_ticker'])
"
```

Expected: prints `corrected run confirmed: ['2025-12-26', '2026-07-31'] {'CRWD': ...}`.
Every assert is the difference between the corrected run and the first pass — if
any fires, the committed artefacts are the stale run and the re-run must be redone
before anything downstream is trusted.

- [ ] **Step 3: Stage exactly these paths — nothing else**

`git status -s` currently lists eight untracked entries that belong to unrelated
work (`2026-07-27-regime-flip-rate.md`, `2026-07-29-garch-vs-rv21-vrp-verdict.md`,
`garch-vrp-2026-07-29/`, `2026-07-26-sector-crowding-panel.md`, and four
`scripts/research/*.py` probes). **They must not enter this commit.** Never
`git add -A` / `git add .`.

```bash
git add src/uw_scan/reports/magnet_data.py \
        tests/unit/test_magnet_data.py \
        scripts/research/magnet_cone_calibration.py \
        scripts/research/magnet_first_passage.py \
        docs/research/2026-08-08-magnet-cone-calibration/
git status -s --  # verify: only the paths above show as staged
```

- [ ] **Step 4: Commit the corrections**

```bash
git commit -m "$(cat <<'EOF'
fix(research): corporate-action and calendar-gap guards; re-run Phase 1

Supersedes a8dd3d5's verdict. 87 of 47,121 observations (0.18%) were
corrupt: 72 spanning three unadjusted corporate actions in daily_ohlc
(CRWD 4:1, KORU 20:1) and 15 from positional i+h indexing walking across
SPCX's ticker-reuse calendar gap. One of those had z = 53.9 and carried
~16% of the pooled variance the G2 gate fit its scale factor on.

Cleaned, std(z) 1.1157 -> 0.9748 and excess kurtosis 361 -> 0.85 at 5d.
G2 now PASSES at 5d; G3 reverses to "table justified" at all horizons.
G1 is unchanged - every edge estimate moved by less than 0.003, so the
0.618 null is robust.

Guards: find_price_discontinuities / trim_to_clean_segment at ln(2), read
off a measured 2.6x gap between the largest real move (0.5428) and the
smallest split (1.3957); plus a calendar-span check in the E1 runner.
21d now runs and is reported.
EOF
)"
```

- [ ] **Step 5: Commit the plan**

```bash
git add docs/superpowers/plans/2026-08-09-magnet-view-phase2-3-build.md
git commit -m "docs: Plan B — magnet view Phase 2/3 build plan"
```

- [ ] **Step 6: Verify the tree is clean of this work**

```bash
git status -s
```

Expected: only the eight unrelated untracked entries remain.

---

### Task 1: Shared price fixture + `magnet_levels`

**Files:**

- Create: `tests/fixtures/aapl_daily.py`
- Modify: `src/uw_scan/cards/magnets.py`
- Test: `tests/unit/test_magnets_levels.py`

**Interfaces:**

- Consumes: `all_pivots(df, k) -> list[Pivot]` (exists), `Pivot(index, kind, price, confirmed_index)`
- Produces: `magnet_levels(df, k=3.0) -> dict | None` with keys `resistance`, `support`, `stretch`, `down`, `sma20`, `last`, `leg_state`, `pivot_a`, `pivot_b`; and `aapl_frame()` from the fixture module

`all_pivots` returns `[]` for any frame shorter than **30 bars**. Every test here
therefore uses the real 45-bar fixture — a 8-bar toy frame yields `None` for the
wrong reason and would pass while testing nothing.

- [ ] **Step 1: Create the shared fixture**

`tests/fixtures/` exists but holds only JSON data and has no `__init__.py`, while
`tests/` and `tests/unit/` do. Namespace-package resolution would probably make
the import work anyway; do not rely on it:

```bash
touch tests/fixtures/__init__.py
```

```python
# tests/fixtures/aapl_daily.py
"""Real AAPL sessions, frozen from uw_scan.daily_ohlc on the mini 2026-08-09.

Captured once at authoring time; no network at test time. 45 sessions
2026-06-04..2026-08-07, chosen because they contain a clean two-pivot swing:
a bottom at 275.15 (2026-06-25) and a top at 340.08 (2026-07-28), both of which
`all_pivots` confirms at k=3.0. 45 > the 30-bar floor `all_pivots` enforces.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

# (date, open, high, low, close, volume)
ROWS: list[tuple[str, float, float, float, float, int]] = [
    ("2026-06-04", 313.23, 313.54, 309.65, 311.23, 44869134),
    ("2026-06-05", 312.86, 315.17, 307.15, 307.34, 65310502),
    ("2026-06-08", 308.739, 317.4, 301.17, 301.54, 77949082),
    ("2026-06-09", 300.275, 300.75, 287.78, 290.55, 70108847),
    ("2026-06-10", 290.74, 294.75, 287.38, 291.58, 52793266),
    ("2026-06-11", 293.72, 297, 289.59, 295.63, 42572497),
    ("2026-06-12", 296.03, 297.14, 289.62, 291.13, 38784789),
    ("2026-06-15", 294.12, 297.78, 291.7, 296.42, 45732573),
    ("2026-06-16", 295.245, 300.48, 293.97, 299.24, 39874404),
    ("2026-06-17", 300.845, 302.07, 294.36, 295.95, 42745060),
    ("2026-06-18", 298.11, 300.57, 295.62, 298.01, 85962201),
    ("2026-06-22", 297.31, 302.42, 296.76, 297.01, 44879914),
    ("2026-06-23", 297.538, 301.64, 294.18, 294.3, 52010929),
    ("2026-06-24", 295.355, 299.7, 292.94, 293.08, 53083961),
    ("2026-06-25", 287.4, 288.8, 273.75, 275.15, 107253659),
    ("2026-06-26", 275, 285.95, 274.21, 283.78, 261775450),
    ("2026-06-29", 286.73, 288.3697, 279.85, 281.74, 66427002),
    ("2026-06-30", 281.17, 289.94, 280.695, 289.36, 65100155),
    ("2026-07-01", 293.44, 296.59, 289.195, 294.38, 50161042),
    ("2026-07-02", 294.12, 309.42, 293.68, 308.63, 75400626),
    ("2026-07-06", 307.36, 314.2, 307, 312.66, 53589977),
    ("2026-07-07", 315.29, 315.48, 310.15, 310.66, 42490002),
    ("2026-07-08", 311.91, 314.82, 307.05, 313.39, 41323480),
    ("2026-07-09", 310.51, 316.53, 308.16, 316.22, 48124490),
    ("2026-07-10", 314.72, 316.91, 312.17, 315.32, 34131684),
    ("2026-07-13", 317.015, 323.45, 315.78, 317.31, 43257804),
    ("2026-07-14", 313.76, 316.19, 311.91, 314.86, 35755535),
    ("2026-07-15", 317.615, 328.73, 317.32, 327.5, 60957644),
    ("2026-07-16", 328.005, 334.68, 326.79, 333.26, 62970617),
    ("2026-07-17", 331.98, 334.99, 329.0006, 333.74, 63407059),
    ("2026-07-20", 333.505, 333.71, 323.68, 326.59, 53468008),
    ("2026-07-21", 323.13, 329.6, 322.2204, 327.74, 41338917),
    ("2026-07-22", 327.87, 328.9995, 323.34, 325.89, 38755929),
    ("2026-07-23", 321.73, 323.3, 319.35, 321.66, 40840778),
    ("2026-07-24", 321.79, 334.37, 321.62, 333.02, 47489415),
    ("2026-07-27", 334.54, 339.57, 334.02, 336.91, 49604297),
    ("2026-07-28", 340.03, 342.89, 335.6, 340.08, 51859042),
    ("2026-07-29", 339.73, 344.5699, 337.3501, 338.19, 56090840),
    ("2026-07-30", 333.1, 334.75, 329.59, 333.43, 74817792),
    ("2026-07-31", 304.81, 310.69, 300, 308.91, 132489137),
    ("2026-08-03", 309.58, 311.8, 302.56, 303.42, 75052205),
    ("2026-08-04", 302.725, 310.42, 301.32, 309.38, 68000969),
    ("2026-08-05", 309.36, 311.71, 305.67, 311, 49438763),
    ("2026-08-06", 314.34, 316.2894, 309.23, 312.41, 46290975),
    ("2026-08-07", 311.45, 314.81, 310.74, 313.33, 34468584),
]


def aapl_frame() -> pd.DataFrame:
    """The fixture as the DataFrame `load_adjusted_closes` produces."""
    return pd.DataFrame(
        [
            (date.fromisoformat(d), o, h, low, c, v)
            for d, o, h, low, c, v in ROWS
        ],
        columns=["date", "open", "high", "low", "close", "volume"],
    )
```

- [ ] **Step 2: Write the failing test**

```python
# tests/unit/test_magnets_levels.py
import pytest

from tests.fixtures.aapl_daily import aapl_frame
from uw_scan.cards.magnets import magnet_levels

# all_pivots(aapl_frame(), k=3.0) confirms three pivots; the last two are
# bottom 275.15 (2026-06-25) and top 340.08 (2026-07-28). Verified against the
# mini 2026-08-09.
_R, _S = 340.08, 275.15


def test_magnet_levels_picks_the_last_two_confirmed_pivots():
    lv = magnet_levels(aapl_frame(), k=3.0)
    assert lv["resistance"] == pytest.approx(_R)
    assert lv["support"] == pytest.approx(_S)


def test_magnet_levels_reproduces_the_0618_arithmetic():
    lv = magnet_levels(aapl_frame(), k=3.0)
    assert lv["stretch"] == pytest.approx(_R + 0.618 * (_R - _S))
    assert lv["down"] == pytest.approx(_S - 0.618 * (_R - _S))


def test_magnet_levels_marks_falling_when_the_top_is_the_later_pivot():
    # The later pivot is the 340.08 top and price has come off it, so the leg
    # is working DOWN from resistance.
    assert magnet_levels(aapl_frame(), k=3.0)["leg_state"] == "falling"


def test_magnet_levels_returns_none_when_no_pivot_confirms():
    # k=50 puts the reversal threshold at 50x ATR(14) — nothing confirms.
    assert magnet_levels(aapl_frame(), k=50.0) is None


def test_magnet_levels_returns_none_on_a_frame_below_the_pivot_floor():
    # all_pivots requires >= 30 bars; 20 must yield None, not a fabricated swing.
    assert magnet_levels(aapl_frame().head(20), k=3.0) is None


def test_magnet_levels_reports_sma20_and_last():
    df = aapl_frame()
    lv = magnet_levels(df, k=3.0)
    assert lv["last"] == pytest.approx(313.33)
    assert lv["sma20"] == pytest.approx(float(df["close"].tail(20).mean()))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_magnets_levels.py -v`
Expected: FAIL — `ImportError: cannot import name 'magnet_levels'`

- [ ] **Step 4: Write the implementation**

```python
# append to src/uw_scan/cards/magnets.py
FIB = 0.618


def magnet_levels(df: pd.DataFrame, k: float = 3.0) -> dict | None:
    """The four levels, SMA20 and leg state from the last two ZigZag pivots.

    `leg_state` is "rising" when the LATER pivot is the bottom (price is working
    up off support) and "falling" otherwise. Returns None when fewer than two
    pivots exist — a chart with no measurable swing has no magnet levels, and
    fabricating them from the window's min/max would invent a swing.

    Uses `Pivot.index`, not `confirmed_index`: this draws where the extreme sits
    on the chart. Any forward test must use `confirmed_index` instead.
    """
    pivots = all_pivots(df, k=k)
    if len(pivots) < 2:
        return None
    a, b = pivots[-2], pivots[-1]
    rising = b.kind == "bottom"
    resistance = a.price if rising else b.price
    support = b.price if rising else a.price
    if resistance <= support:
        return None
    leg = resistance - support
    close = df["close"].astype(float)
    return {
        "resistance": float(resistance),
        "support": float(support),
        "stretch": float(resistance + FIB * leg),
        "down": float(support - FIB * leg),
        "sma20": float(close.tail(20).mean()) if len(close) >= 20 else None,
        "last": float(close.iloc[-1]),
        "leg_state": "rising" if rising else "falling",
        "pivot_a": {"index": a.index, "kind": a.kind, "price": float(a.price)},
        "pivot_b": {"index": b.index, "kind": b.kind, "price": float(b.price)},
    }
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_magnets_levels.py -v && uv run ruff check src/uw_scan/cards/magnets.py tests/fixtures/aapl_daily.py`
Expected: 6 passed, lint clean

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/cards/magnets.py tests/unit/test_magnets_levels.py \
        tests/fixtures/aapl_daily.py tests/fixtures/__init__.py
git commit -m "feat(magnets): magnet_levels — 0.618 levels and leg state"
```

---

### Task 2: `cone` — bands that match the calibrated construction

**Files:**

- Modify: `src/uw_scan/cards/magnets.py`
- Test: `tests/unit/test_magnets_cone.py`

**Interfaces:**

- Produces: `cone(spot, atm_iv_by_horizon, k_shrink=1.0) -> list[dict]` — one entry per (horizon, band) with `horizon`, `band_sigma`, `measured_confidence`, `upper`, `lower`; plus module constants `CONE_HORIZONS`, `CONE_BANDS`, `MEASURED_CONFIDENCE`

**This is the load-bearing task.** The z-definition must invert the research's exactly.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_magnets_cone.py
import math

import pytest

from uw_scan.cards.magnets import CONE_BANDS, CONE_HORIZONS, cone


def test_cone_inverts_the_research_z_definition_exactly():
    """The calibration defined z = (log_ret + 0.5*sigma^2*T) / (sigma*sqrt(T)).
    The drawn band must be the exact inverse or the measured coverage in
    VERDICT.md does not describe what is on screen."""
    spot, sigma, h = 313.33, 0.2271, 5
    t = h / 252.0
    bands = cone(spot, {5: sigma})
    upper = next(
        b for b in bands if b["horizon"] == 5 and b["band_sigma"] == 1.0
    )["upper"]
    # forward-solve z from the drawn price and assert it returns 1.0
    z = (math.log(upper / spot) + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    assert z == pytest.approx(1.0, abs=1e-12)


def test_cone_lower_band_is_the_negative_z():
    spot, sigma, h = 313.33, 0.2334, 10
    t = h / 252.0
    lower = next(
        b
        for b in cone(spot, {10: sigma})
        if b["horizon"] == 10 and b["band_sigma"] == 1.96
    )["lower"]
    z = (math.log(lower / spot) + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    assert z == pytest.approx(-1.96, abs=1e-12)


def test_cone_labels_carry_measured_not_nominal_confidence():
    b = next(
        x
        for x in cone(313.33, {5: 0.2271})
        if x["band_sigma"] == 1.0 and x["horizon"] == 5
    )
    assert b["measured_confidence"] == pytest.approx(0.709)  # not 0.6827
    b21 = next(
        x
        for x in cone(313.33, {21: 0.2364})
        if x["band_sigma"] == 1.96 and x["horizon"] == 21
    )
    assert b21["measured_confidence"] == pytest.approx(0.933)  # not 0.95


def test_cone_draws_no_band_wider_than_196_sigma():
    # The far tail needs 8-17% more width than the closed form; a 99% band drawn
    # from it would be wrong by more than any other band on the chart.
    assert max(CONE_BANDS) == 1.96


def test_cone_skips_horizons_with_no_usable_iv():
    got = cone(313.33, {5: 0.2271, 10: None, 21: 0.0})
    assert {b["horizon"] for b in got} == {5}


def test_cone_returns_two_bands_per_usable_horizon():
    got = cone(313.33, {h: 0.23 for h in CONE_HORIZONS})
    assert len(got) == len(CONE_HORIZONS) * len(CONE_BANDS)


def test_cone_k_shrink_below_one_narrows_the_band():
    """k_shrink MULTIPLIES z. The research calibrates with
    `coverage(z_test / k_train, level)`, so its calibrated band accepts
    |z| < k*level — feeding k_train=0.9747 here must make the band NARROWER,
    the direction the variance risk premium implies. Getting this backwards
    draws the reciprocal band and is silent, because it ships at k=1.0."""
    narrow = next(
        b for b in cone(313.33, {5: 0.2271}, k_shrink=0.9) if b["band_sigma"] == 1.0
    )
    base = next(
        b for b in cone(313.33, {5: 0.2271}, k_shrink=1.0) if b["band_sigma"] == 1.0
    )
    assert narrow["upper"] < base["upper"]
    assert narrow["lower"] > base["lower"]


def test_cone_k_shrink_reproduces_the_research_calibrated_band():
    # G2 at 5d fit k_train = 0.9747. The band drawn at (band=1.0, k=0.9747) must
    # be the price where the research's z_test/k_train equals 1.0.
    spot, sigma, h, k = 313.33, 0.2271, 5, 0.9747
    t = h / 252.0
    upper = next(
        b
        for b in cone(spot, {5: sigma}, k_shrink=k)
        if b["horizon"] == 5 and b["band_sigma"] == 1.0
    )["upper"]
    z_obs = (math.log(upper / spot) + 0.5 * sigma**2 * t) / (sigma * math.sqrt(t))
    assert z_obs / k == pytest.approx(1.0, abs=1e-12)


def test_cone_rejects_a_non_positive_k_shrink():
    with pytest.raises(ValueError):
        cone(313.33, {5: 0.2271}, k_shrink=0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_magnets_cone.py -v`
Expected: FAIL — `ImportError: cannot import name 'cone'`

- [ ] **Step 3: Write the implementation**

`math` is already imported at the top of `magnets.py` — do not add it again.

```python
# append to src/uw_scan/cards/magnets.py
TRADING_DAYS = 252
CONE_HORIZONS = (5, 10, 21)
CONE_BANDS = (1.0, 1.96)

# Measured 2026-08-09 on 47,034 observations / 119 tickers, 2025-12-26..2026-07-31.
# These are what each band ACTUALLY contained, not the lognormal nominal. The
# legend shows these numbers. Source: confidence_curve.csv.
# No 2.576 band: the far tail needs 8-17% more width than the closed form.
MEASURED_CONFIDENCE: dict[tuple[int, float], float] = {
    (5, 1.0): 0.709,
    (5, 1.96): 0.951,
    (10, 1.0): 0.712,
    (10, 1.96): 0.947,
    (21, 1.0): 0.677,
    (21, 1.96): 0.933,
}

# 95% panel block bootstrap (resample blocks of dates, keep every ticker). Ships
# WITH the point estimate because the intervals are 2.4-11.4pt wide: a bare
# "70.9%" reads as a probability, and it is a backward-looking frequency over one
# ~8-month regime. The label shows both.
MEASURED_CONFIDENCE_CI: dict[tuple[int, float], tuple[float, float]] = {
    (5, 1.0): (0.677, 0.755),
    (5, 1.96): (0.939, 0.963),
    (10, 1.0): (0.666, 0.758),
    (10, 1.96): (0.924, 0.965),
    (21, 1.0): (0.617, 0.731),
    (21, 1.96): (0.901, 0.964),
}

# Sessions behind each horizon's estimate — shown in the legend so the window is
# never implicit.
MEASURED_N_DATES: dict[int, int] = {5: 149, 10: 144, 21: 133}


def cone(
    spot: float,
    atm_iv_by_horizon: dict[int, float | None],
    k_shrink: float = 1.0,
) -> list[dict]:
    """Options-implied price bands, inverting the calibration's z exactly.

        z = (ln(S_t+h / S_t) + 0.5*sigma^2*T) / (sigma*sqrt(T))
    =>  S_t+h = S_t * exp(z*sigma*sqrt(T) - 0.5*sigma^2*T)

    k_shrink MULTIPLIES z, so k < 1 narrows the band — matching both the name and
    the calibration's own convention. The research computes coverage as
    `coverage(z_test / k_train, level)` (`magnet_cone_calibration.py:314`), i.e.
    the calibrated band at `level` accepts realised residuals with
    `|z| < k*level`. In price space that is `z_draw = band * k`. Dividing here
    instead would draw the RECIPROCAL band: feed in the research's own
    `k_train = 0.9747` and you would get a band 2.6% too WIDE where the
    calibration made it 2.5% narrower. The parameter ships at 1.0 so the
    direction is currently inert — which is exactly why it has a test.

    Ships at 1.0. The G2 gate's fitted scale passed at 5d only (coverage
    0.7000 -> 0.6873 against a 0.6827 nominal) and moved 10d/21d the WRONG way,
    because it fits by `std` and cannot correct an over-coverage miss. Shipping
    a constant justified by one horizon out of three would be worse than
    shipping none, and at k=1.0 every drawn band's nominal coverage already sits
    inside its measured 95% CI. The corrected estimator (MAD, or direct quantile
    targeting) is pre-registered in VERDICT.md as research, not build.
    """
    if k_shrink <= 0:
        raise ValueError(f"k_shrink must be positive, got {k_shrink}")
    out: list[dict] = []
    for h in CONE_HORIZONS:
        sigma = atm_iv_by_horizon.get(h)
        if sigma is None or sigma <= 0:
            continue
        t = h / TRADING_DAYS
        drift = 0.5 * sigma**2 * t
        vol = sigma * math.sqrt(t)
        for band in CONE_BANDS:
            z = band * k_shrink
            out.append(
                {
                    "horizon": h,
                    "band_sigma": band,
                    "measured_confidence": MEASURED_CONFIDENCE[(h, band)],
                    "measured_ci_lo": MEASURED_CONFIDENCE_CI[(h, band)][0],
                    "measured_ci_hi": MEASURED_CONFIDENCE_CI[(h, band)][1],
                    "measured_n_dates": MEASURED_N_DATES[h],
                    "upper": float(spot * math.exp(z * vol - drift)),
                    "lower": float(spot * math.exp(-z * vol - drift)),
                }
            )
    return out
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_magnets_cone.py -v && uv run ruff check src/uw_scan/cards/magnets.py`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/magnets.py tests/unit/test_magnets_cone.py
git commit -m "feat(magnets): options-implied cone with measured confidence labels"
```

---

### Task 3: `build_read` — deterministic bullets, no forecast claims

**Files:**

- Modify: `src/uw_scan/cards/magnets.py`
- Test: `tests/unit/test_magnets_read.py`

**Interfaces:**

- Produces: `build_read(levels: dict, bands: list[dict]) -> list[str]`

Spec §4 sketched `build_read(levels, cone, ctx)`. The `ctx` argument is dropped:
nothing on this route carries the RSI/vol context it was for, and the tiles source
that from the `TechnicalsResponse` the tab already holds (Task 5). An unused third
parameter is scaffolding for a caller that does not exist.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_magnets_read.py
from uw_scan.cards.magnets import build_read

_LEVELS = {
    "resistance": 340.08,
    "support": 275.15,
    "stretch": 380.21,
    "down": 235.02,
    "sma20": 320.0,
    "last": 313.33,
    "leg_state": "falling",
    "pivot_a": {"index": 14, "kind": "bottom", "price": 275.15},
    "pivot_b": {"index": 36, "kind": "top", "price": 340.08},
}
def _band(sigma: float, conf: float, lo: float, hi: float, up: float, dn: float) -> dict:
    return {
        "horizon": 10,
        "band_sigma": sigma,
        "measured_confidence": conf,
        "measured_ci_lo": lo,
        "measured_ci_hi": hi,
        "measured_n_dates": 144,
        "upper": up,
        "lower": dn,
    }


_BANDS = [
    _band(1.0, 0.712, 0.666, 0.758, 328.0, 299.0),
    _band(1.96, 0.947, 0.924, 0.965, 343.0, 286.0),
]


def test_read_never_states_a_price_target():
    joined = " ".join(build_read(_LEVELS, _BANDS)).lower()
    assert "target" not in joined
    assert "will " not in joined


def test_read_flags_when_the_0618_stretch_sits_outside_the_cone():
    # stretch 380.21 is above the 1.96 sigma upper of 343.0 -> must be called out
    assert "outside" in " ".join(build_read(_LEVELS, _BANDS)).lower()


def test_read_flags_the_downside_too():
    assert "outside" in " ".join(build_read(_LEVELS, _BANDS)).lower()


def test_read_marks_the_0618_level_as_having_no_measured_edge():
    assert any("no measured edge" in line for line in build_read(_LEVELS, _BANDS))


def test_read_quotes_the_widest_band_not_the_narrowest():
    joined = " ".join(build_read(_LEVELS, _BANDS))
    assert "343.00" in joined and "286.00" in joined


def test_read_quotes_the_10d_band_when_several_horizons_are_present():
    # max(key=band_sigma) would return the 5d entry (first tie wins). The read
    # must name 10d.
    five = [
        {**b, "horizon": 5, "upper": b["upper"] + 50, "lower": b["lower"] - 50}
        for b in _BANDS
    ]
    joined = " ".join(build_read(_LEVELS, [*five, *_BANDS]))
    assert "10d range" in joined
    assert "393.00" not in joined  # the 5d upper, deliberately not quoted


def test_read_survives_an_empty_band_list():
    lines = build_read(_LEVELS, [])
    assert lines and all(isinstance(x, str) for x in lines)


def test_read_survives_a_missing_sma20():
    lines = build_read({**_LEVELS, "sma20": None}, _BANDS)
    assert not any("SMA20" in line for line in lines)


def test_read_is_deterministic():
    assert build_read(_LEVELS, _BANDS) == build_read(_LEVELS, _BANDS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_magnets_read.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_read'`

- [ ] **Step 3: Write the implementation**

```python
# append to src/uw_scan/cards/magnets.py
def build_read(levels: dict, bands: list[dict]) -> list[str]:
    """Deterministic description of what is drawn. Describes, never predicts.

    G1 measured the 0.618 extension against a matched null at five ZigZag
    thresholds — 938 legs at the loosest, 226 at the tightest, overlapping
    samples of the same history, NOT 2,547 independent legs — and found no
    edge: every OOS ticker-clustered CI spans zero. So this states geometry
    and states the options-implied band, and where they disagree it says so —
    it never asserts price will reach a level.
    """
    last, state = levels["last"], levels["leg_state"]
    lines = [
        f"Leg is {state}: support {levels['support']:.2f}, "
        f"resistance {levels['resistance']:.2f}, last {last:.2f}.",
        f"0.618 extension sits at {levels['stretch']:.2f} up / "
        f"{levels['down']:.2f} down — geometry only, no measured edge.",
    ]
    if levels.get("sma20") is not None:
        side = "above" if last >= levels["sma20"] else "below"
        lines.append(f"Price is {side} SMA20 ({levels['sma20']:.2f}).")

    if not bands:
        lines.append("No options surface for this session — cone not drawn.")
        return lines

    # WHICH band the read quotes is a decision, not a max(). `bands` spans three
    # horizons x two sigmas, so max(key=band_sigma) would silently return the
    # FIRST 1.96 entry — the 5d one — because max keeps the earliest tie. Pick
    # 10d explicitly, on ONE ground: it matches the 1-2 week swing horizon the
    # rest of the desk reasons in. It is NOT the best-calibrated horizon — 5d is
    # (95.09% vs a 95% nominal, against 10d's 94.66%). Fall back 10 -> 5 -> 21.
    quoted = next(
        (
            b
            for h in (10, 5, 21)
            for b in bands
            if b["horizon"] == h and b["band_sigma"] == max(CONE_BANDS)
        ),
        None,
    )
    if quoted is None:
        # Unreachable while every horizon emits every band in CONE_BANDS. Kept
        # because the read must not raise if that invariant is ever edited.
        lines.append("Cone drawn, but no band at the quoted width.")
        return lines
    widest = quoted
    # Rounded to whole points and quoted WITH its interval: the estimate's own CI
    # is 2.4-11.4pt wide, so a one-decimal figure would imply precision the
    # measurement does not have.
    lines.append(
        f"Options price a {widest['horizon']}d range of "
        f"{widest['lower']:.2f}-{widest['upper']:.2f} — that band held "
        f"{widest['measured_confidence']:.0%} of past moves "
        f"({widest['measured_ci_lo']:.0%}-{widest['measured_ci_hi']:.0%}, "
        f"{widest['measured_n_dates']} sessions)."
    )
    outside = []
    if levels["stretch"] > widest["upper"]:
        outside.append("upside")
    if levels["down"] < widest["lower"]:
        outside.append("downside")
    if outside:
        # Deliberately NOT "the market is not pricing a move that far": the band
        # is a 1.96-sigma CENTRAL interval that historically held ~93-95% of
        # moves, so 5-7% of the distribution lives outside it. Saying the move is
        # unpriced would be a false statement about the options market.
        lines.append(
            f"The 0.618 {' and '.join(outside)} extension sits outside that "
            "central band — reaching it needs a move in the tail the options "
            "surface prices as uncommon, not one it rules out."
        )
    return lines
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_magnets_read.py -v && uv run ruff check src/uw_scan/cards/magnets.py`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/magnets.py tests/unit/test_magnets_read.py
git commit -m "feat(magnets): deterministic read builder"
```

---

### Task 4: Contract model + `GET /stock/{ticker}/magnets`

**Files:**

- Create: `src/uw_scan/models/magnets.py`
- Modify: `src/uw_scan/models/__init__.py` (import block **and** `__all__`), `src/uw_scan/api/routers/stock.py`, `tests/integration/conftest.py`
- Test: `tests/integration/api/test_magnets_endpoint.py`

**Interfaces:**

- Consumes: `magnet_levels`, `cone`, `build_read`, `CONE_HORIZONS`, `all_pivots`; `reports.magnet_data.{load_adjusted_closes, trim_to_clean_segment, load_all_expiry_iv_curves, load_all_session_spots, atm_iv_at_horizon}`
- Produces: `MagnetsResponse` with `ticker`, `as_of`, `levels`, `bands`, `pivots`, `read`, `candles`, `atm_iv_30d`, `atm_iv_30d_chg_5d`

`pivots` is on the contract because Task 6 draws the ZigZag polyline and the A/B
markers from it. Recomputing the ZigZag in TypeScript would be a second
implementation of the detector that can silently disagree with the one the levels
came from.

**This route body was dry-run against the mini on 2026-08-09** before the plan was
finalised — the loader chain, the six-session curve window, the NaN filter, the
date-based pivot rebasing and `to_dict("records")` were executed on ten real
tickers, all as-of 2026-08-07:

| Ticker | bars | candles | pivots | bands | levels |
| ------ | ---- | ------- | ------ | ----- | ------ |
| AAPL | 276 | 180 | 7 | 6 | R=340.08 S=275.15 falling |
| NVDA | 276 | 180 | 9 | 6 | R=235.74 S=190.01 rising |
| SPY  | 331 | 180 | 5 | 6 | R=759.57 S=725.43 rising |
| SOXL | 276 | 180 | 8 | 6 | R=300.77 S=180.65 falling |
| CRWD |  81 |  81 | 4 | 6 | R=210.73 S=179.38 rising |
| KORU |  72 |  72 | 5 | 6 | R=54.54 S=30.50 falling |
| SPCX |  39 |  39 | 0 | 6 | **None** |

Zero NaN reached serialisation, every pivot index landed inside `candles`, and
every band had `lower < upper`. The last three rows are the ones that matter:
CRWD (276→81 bars) and KORU (276→72) are `trim_to_clean_segment` cutting at the
4:1 and 20:1 splits, and SPCX exercises the `levels is None` branch — 39 bars
after its relisting, too few for two confirmed pivots, so the route must return
200 with null levels and an empty `read`, not an error.

- [ ] **Step 1: Add the seeding fixture**

`seeded_db_with_ohlc` seeds 30 monotonically-rising synthetic bars — a monotonic
series confirms no pivots, so it exercises only the `levels is None` path and
carries no options surface at all. Add a fixture with the real frozen data.

The file imports `datetime`, `timedelta`, `timezone` from `datetime` but **not**
`date`, which this fixture needs. Extend that import first.

```python
# tests/integration/conftest.py — extend the existing datetime import
from datetime import date, datetime, timedelta, timezone


@pytest.fixture
def seeded_db_with_aapl_magnets(
    seeded_db_empty_cards, _migrated_settings: Settings
) -> Repository:
    """Real frozen AAPL OHLC + one grid session, enough for the magnets route.

    45 real sessions containing a confirmed two-pivot swing, plus the ATM strike
    of every expiry captured on 2026-08-07 so `atm_iv_at_horizon` resolves at
    5d/10d/21d. Values frozen from the mini 2026-08-09; no network at test time.
    """
    from tests.fixtures.aapl_daily import ROWS

    repo = seeded_db_empty_cards
    for d, o, h, low, c, v in ROWS:
        repo.upsert_daily_ohlc(
            ticker="AAPL",
            date=date.fromisoformat(d),
            open=Decimal(str(o)),
            high=Decimal(str(h)),
            low=Decimal(str(low)),
            close=Decimal(str(c)),
            volume=v,
            source="massive.com",
        )
    # (expiry, strike, call_iv, put_iv) at spot 313.196 on market_date 2026-08-07.
    grid = [
        ("2026-08-10", 312.5, 0.152276812549349, 0.166385201913912),
        ("2026-08-12", 312.5, 0.213907233632553, 0.219063329403123),
        ("2026-08-14", 312.5, 0.230149308917646, 0.224059844224928),
        ("2026-08-17", 312.5, 0.214363939578810, 0.210516029229766),
        ("2026-08-19", 312.5, 0.227821059594149, 0.220946765536718),
        ("2026-08-21", 312.5, 0.238583052423656, 0.228134013289602),
        ("2026-08-28", 315.0, 0.239786341911712, 0.222899290501027),
        ("2026-09-04", 315.0, 0.246726028227753, 0.224161187448352),
    ]
    # `Repository` exposes `.conn` (a property on _BaseMixin) but NOT `.schema` —
    # only the private `_schema`. Take it from settings, the same way
    # `routers/health.py:387` does.
    schema = _migrated_settings.db_schema
    with repo.conn.cursor() as cur:
        for expiry, strike, civ, piv in grid:
            cur.execute(
                f"""
                INSERT INTO {schema}.option_surface_grid_daily
                    (ticker, market_date, expiry, strike, underlying_spot,
                     call_iv, put_iv, source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'uw_greeks')
                ON CONFLICT DO NOTHING
                """,
                ("AAPL", date(2026, 8, 7), date.fromisoformat(expiry),
                 Decimal(str(strike)), Decimal("313.196"),
                 Decimal(str(civ)), Decimal(str(piv))),
            )
    repo.conn.commit()
    return repo
```

Column set verified against `src/uw_scan/storage/migrations/077_option_surface_grid.sql`.
NOT NULL columns are `(ticker, market_date, expiry, strike)` — the primary key —
plus `source` and `inserted_at`, both of which have defaults. Every greek column
is nullable. The eight named columns above are therefore sufficient; `inserted_at`
is deliberately left to its `now()` default.

- [ ] **Step 2: Write the failing test**

```python
# tests/integration/api/test_magnets_endpoint.py
import pytest


def test_magnets_endpoint_returns_levels_from_the_real_swing(
    client, seeded_db_with_aapl_magnets
):
    r = client.get("/api/stock/AAPL/magnets")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["as_of"] == "2026-08-07"
    lv = body["levels"]
    assert lv["resistance"] == pytest.approx(340.08)
    assert lv["support"] == pytest.approx(275.15)
    assert lv["stretch"] == pytest.approx(340.08 + 0.618 * (340.08 - 275.15))


def test_magnets_endpoint_returns_bands_with_measured_confidence(
    client, seeded_db_with_aapl_magnets
):
    body = client.get("/api/stock/AAPL/magnets").json()
    assert body["bands"], "grid session seeded but no cone produced"
    assert {b["horizon"] for b in body["bands"]} == {5, 10, 21}
    for b in body["bands"]:
        assert b["band_sigma"] in (1.0, 1.96)
        assert 0.5 < b["measured_confidence"] < 1.0
        assert b["lower"] < b["upper"]


def test_magnets_endpoint_returns_pivots_for_the_zigzag(
    client, seeded_db_with_aapl_magnets
):
    pivots = client.get("/api/stock/AAPL/magnets").json()["pivots"]
    assert len(pivots) >= 2
    assert pivots[-1]["kind"] == "top"
    assert {p["kind"] for p in pivots} <= {"top", "bottom"}


def test_magnets_endpoint_read_never_promises_a_target(
    client, seeded_db_with_aapl_magnets
):
    joined = " ".join(client.get("/api/stock/AAPL/magnets").json()["read"]).lower()
    assert "target" not in joined
    assert "no measured edge" in joined


def test_magnets_endpoint_404s_without_price_history(client, seeded_db_empty_cards):
    assert client.get("/api/stock/NOSUCHTICKER/magnets").status_code == 404


def test_magnets_endpoint_returns_200_with_no_surface(client, seeded_db_with_ohlc):
    # AAPL has bars but no grid session: levels may be None and bands empty, and
    # that is a 200 with an honest empty payload, not an error.
    r = client.get("/api/stock/AAPL/magnets")
    assert r.status_code == 200
    assert r.json()["bands"] == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/integration/api/test_magnets_endpoint.py -v`
Expected: FAIL — 404 on an unregistered route

- [ ] **Step 4: Write the model**

Models end with `_preserve_public_module(...)`. That call is the invariant, not
the base class — `technicals.py` subclasses `_UwBase` while `gold.py` uses a bare
`BaseModel` and both call it. `_UwBase` is used here for its
`extra="ignore"` config. Skipping `_preserve_public_module` leaves
`__module__` pointing at the implementation module, which renames the OpenAPI
component and breaks the contract-identity rule in CLAUDE.md.

```python
# src/uw_scan/models/magnets.py
"""Contract models for the Technicals magnet sub-tab."""

from __future__ import annotations

from datetime import date

from uw_scan.models._base import _preserve_public_module, _UwBase


class MagnetPivot(_UwBase):
    index: int
    kind: str
    price: float


class MagnetLevels(_UwBase):
    resistance: float
    support: float
    stretch: float
    down: float
    sma20: float | None
    last: float
    leg_state: str
    pivot_a: MagnetPivot
    pivot_b: MagnetPivot


class MagnetConeBand(_UwBase):
    horizon: int
    band_sigma: float
    measured_confidence: float
    measured_ci_lo: float
    measured_ci_hi: float
    measured_n_dates: int
    upper: float
    lower: float


class MagnetCandle(_UwBase):
    date: date
    open: float
    high: float
    low: float
    close: float
    # Nullable: daily_ohlc.volume is `int | None`, and the route's NaN filter
    # covers OHLC only. A bar with a real price and an unknown volume is still
    # drawable — a non-optional float here would 500 on it.
    volume: float | None


class MagnetsResponse(_UwBase):
    ticker: str
    as_of: date
    levels: MagnetLevels | None
    bands: list[MagnetConeBand]
    pivots: list[MagnetPivot]
    read: list[str]
    candles: list[MagnetCandle]
    atm_iv_30d: float | None
    atm_iv_30d_chg_5d: float | None


# Preserve __module__ = "uw_scan.models" so OpenAPI component names don't drift
_preserve_public_module(
    MagnetPivot,
    MagnetLevels,
    MagnetConeBand,
    MagnetCandle,
    MagnetsResponse,
)
```

Add to `src/uw_scan/models/__init__.py` — both the import block and `__all__`.
`tests/unit/test_models_exports.py` does **not** discover new models: it checks a
hardcoded `PUBLIC_MODEL_EXPORTS` list (`test_models_exports.py:1-150`), so the
five `Magnet*` names must be appended to that list too or the guard silently
ignores them.

```python
from uw_scan.models.magnets import (
    MagnetCandle,
    MagnetConeBand,
    MagnetLevels,
    MagnetPivot,
    MagnetsResponse,
)
```

- [ ] **Step 5: Write the route**

Add to the existing import blocks at the top of `src/uw_scan/api/routers/stock.py`:

```python
from uw_scan.cards.magnets import CONE_HORIZONS, all_pivots, build_read, cone, magnet_levels
from uw_scan.models import MagnetsResponse
from uw_scan.reports.magnet_data import (
    atm_iv_at_horizon,
    load_adjusted_closes,
    load_all_expiry_iv_curves,
    load_all_session_spots,
    trim_to_clean_segment,
)
```

`MagnetsResponse` goes into the existing alphabetised `from uw_scan.models import (...)`
block; the others are new top-level imports. Also extend the existing
`from fastapi import APIRouter, Depends, HTTPException` line with `Query`.

```python
# src/uw_scan/api/routers/stock.py — add near the other GET handlers
_MAGNET_CANDLE_WINDOW = 180


@router.get("/stock/{ticker}/magnets", response_model=MagnetsResponse)
def get_magnets(
    ticker: str,
    k_atr: float = Query(3.0, gt=0.0, le=20.0),
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> MagnetsResponse:
    """Magnet levels + options-implied cone. Read-only.

    k_atr defaults to 3.0 only because that is the existing last_pivot_index
    default — G1 failed, so no threshold was selected on merit. It stays a query
    param so the sweep's other rungs stay inspectable from the UI without a
    redeploy; nothing writes it. It is BOUNDED because it is user input at a
    trust boundary: k_atr <= 0 makes the reversal threshold zero, every bar
    becomes a pivot, and the response grows to one entry per bar.

    Uses `repo.conn` + `settings.db_schema`, the pattern this codebase already
    uses when a router needs a raw connection (see `routers/health.py:387`);
    the magnet_data loaders take a connection, not a Repository.
    """
    ticker = ticker.upper()
    conn, schema = repo.conn, settings.db_schema

    raw = trim_to_clean_segment(load_adjusted_closes(conn, ticker, schema))
    # Drop incomplete bars ONCE, up front, so every consumer sees one frame.
    #
    # Two reasons this cannot be a candles-only filter. (1) NaN is not JSON —
    # daily_ohlc.open/high/low are nullable DOUBLE PRECISION, load_adjusted_closes
    # coerces NULL to NaN, Pydantic accepts NaN and FastAPI's encoder then raises
    # "Out of range float values are not JSON compliant". (2) `all_pivots` calls
    # `atr14`, which reads high/low/prev-close — a NaN high makes ATR NaN, the
    # detector's `math.isfinite` guard sets the threshold to inf, and the pivot
    # silently never confirms. Filtering only the drawn candles would leave the
    # geometry computed on a different set of rows than the chart displays.
    px = raw[raw[["open", "high", "low", "close"]].notna().all(axis=1)].reset_index(
        drop=True
    )
    if px.empty:
        raise HTTPException(status_code=404, detail=f"no price history for {ticker}")

    as_of = px["date"].iloc[-1]
    spot = float(px["close"].iloc[-1])

    # Only six grid sessions are needed: `as_of` for the cone and the fifth one
    # back for the IV delta. `load_all_expiry_iv_curves` interpolates a VALUES
    # list one row per session passed in, so handing it every session builds a
    # ~180-row VALUES join against the full chain to use two of them.
    spots = load_all_session_spots(conn, ticker, schema)
    sessions = sorted(d for d in spots if d <= as_of)
    wanted = {d: spots[d] for d in sessions[-6:]}
    curves = load_all_expiry_iv_curves(conn, ticker, wanted, schema)

    curve = curves.get(as_of, [])
    # Same target_dte mapping the calibration used: h trading days -> h*7/5
    # calendar days. Drift here and the measured-confidence labels stop
    # describing the drawn band.
    ivs = {h: atm_iv_at_horizon(curve, max(1, round(h * 7 / 5))) for h in CONE_HORIZONS}

    iv30 = atm_iv_at_horizon(curve, 30)
    iv30_prior = (
        atm_iv_at_horizon(curves.get(sessions[-6], []), 30) if len(sessions) >= 6 else None
    )

    levels = magnet_levels(px, k=k_atr)
    bands = cone(spot, ivs)
    window = px.tail(_MAGNET_CANDLE_WINDOW).reset_index(drop=True)
    # Pivot indices are positions in `px`; the chart indexes into `candles`.
    # Rebase BY DATE rather than by subtracting `len(px) - len(window)`. The
    # subtraction happens to be correct today because `window` is a plain tail of
    # `px`, but it silently becomes wrong the moment anything else filters rows
    # between the two — which is exactly the bug the up-front NaN filter above
    # was introduced to avoid. A pivot older than the window is omitted, not
    # clamped: a clamped marker points at a bar the pivot did not occur on.
    window_pos = {d: i for i, d in enumerate(window["date"])}
    px_dates = px["date"].tolist()
    pivots = [
        {"index": window_pos[px_dates[p.index]], "kind": p.kind, "price": p.price}
        for p in all_pivots(px, k=k_atr)
        if px_dates[p.index] in window_pos
    ]
    return MagnetsResponse(
        ticker=ticker,
        as_of=as_of,
        levels=levels,
        bands=bands,
        pivots=pivots,
        read=build_read(levels, bands) if levels else [],
        candles=window.to_dict("records"),
        atm_iv_30d=iv30,
        atm_iv_30d_chg_5d=(
            iv30 - iv30_prior if iv30 is not None and iv30_prior is not None else None
        ),
    )
```

**`levels` is computed on the full `px`, `candles` is the last 180 bars.** That is
deliberate: a swing whose support pivot predates the window is still the live
swing, and clipping the pivot search to the drawn window would make the levels
change every time the chart's range changed.

- [ ] **Step 6: Regenerate the OpenAPI snapshot**

`tests/integration/api/test_openapi_snapshot.py` asserts the full
`components.schemas` dict AND the sorted path list against a committed snapshot.
A new endpoint plus five new `Magnet*` schemas fails it. There is no regen
script, and the file's exact serialisation matters — verified 2026-08-09 to be
`json.dumps(..., indent=2, sort_keys=True)` plus a trailing newline:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test uv run python -c "
import json, pathlib
from fastapi.testclient import TestClient
from uw_scan.api.server import create_app
spec = TestClient(create_app()).get('/openapi.json').json()
p = pathlib.Path('tests/integration/api/openapi.snapshot.json')
p.write_text(json.dumps(spec, indent=2, sort_keys=True) + '\n')
"
git diff --stat tests/integration/api/openapi.snapshot.json
```

Expected: the diff adds `/api/stock/{ticker}/magnets` and the five `Magnet*`
schemas and **nothing else**. If unrelated paths or schemas move, stop — the
snapshot was stale before this change and that is a separate PR.

- [ ] **Step 7: Run tests and regenerate types**

```bash
uv run pytest tests/integration/api/test_magnets_endpoint.py tests/integration/api/test_openapi_snapshot.py -v
uv run pytest tests/unit/test_models_exports.py -v
cd web && npm run gen:types && git diff --stat lib/types.ts
```

Expected: PASS; `web/lib/types.ts` gains the `Magnet*` shapes.

**`gen:types` is not an offline command.** It runs
`openapi-typescript http://127.0.0.1:8400/openapi.json`, so the FastAPI process
must be up first (`bash scripts/dev.sh`, or the API alone). Without it the
command fails on connection refused — and worse, running it against an API
process started _before_ Step 5 silently regenerates types with no magnet
endpoint and no error. Restart the API, then regenerate.

- [ ] **Step 8: Add the client method**

```ts
// web/lib/api.ts — type alias beside the other stock aliases
export type MagnetsResponse = Json<"/api/stock/{ticker}/magnets", "get">;

// ... and inside `export const api = {`
  magnets: (ticker: string): Promise<MagnetsResponse> =>
    _fetch<MagnetsResponse>(`/api/stock/${ticker}/magnets`),
```

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/models/magnets.py src/uw_scan/models/__init__.py \
        src/uw_scan/api/routers/stock.py tests/integration/conftest.py \
        tests/integration/api/test_magnets_endpoint.py \
        tests/integration/api/openapi.snapshot.json \
        web/lib/types.ts web/lib/api.ts
git commit -m "feat(magnets): GET /stock/{ticker}/magnets endpoint and contract"
```

---

### Task 5: Sub-tab shell, table and read

**Files:**

- Create: `web/components/stock/tabs/technicals/{MagnetSubTab,MagnetTable,MagnetRead}.tsx`
- Modify: `web/components/stock/tabs/TechnicalsTab.tsx`
- Test: `web/tests/components/magnetTable.test.tsx`

**Interfaces:**

- Consumes: `MagnetsResponse` from `web/lib/api.ts`; `TechnicalsResponse` passed down from `TechnicalsTab`
- Produces: `<MagnetSubTab ticker={string} technicals={TechnicalsResponse} />`

**Where the four tiles get their data.** Spec §5.1 asks for VOLUME · RSI 14 ·
MOMENTUM · ATM IV. Three of those already live on the `TechnicalsResponse` that
`TechnicalsTab` fetches — but **on its `series` rows, not at the top level**:
`TechnicalsSeriesRow` carries `rsi14`, `rsi_slope5`, `volume`, `macd_hist_atr`,
so the tiles read `technicals.series.at(-1)`. ATM IV comes from `atm_iv_30d` /
`atm_iv_30d_chg_5d` on the magnets payload. Nothing new is fetched.

The spec's `sector 5d` subtitle field is **dropped** — no source on either
payload, and inventing one would be a fabricated number on a chart.

- [ ] **Step 1: Write the failing test**

```tsx
// web/tests/components/magnetTable.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MagnetTable from "@/components/stock/tabs/technicals/MagnetTable";

const LEVELS = {
  resistance: 340.08,
  support: 275.15,
  stretch: 380.21,
  down: 235.02,
  sma20: 320,
  last: 313.33,
  leg_state: "falling",
  pivot_a: { index: 14, kind: "bottom", price: 275.15 },
  pivot_b: { index: 36, kind: "top", price: 340.08 },
};

describe("MagnetTable", () => {
  it("labels the 0.618 rows as having no measured edge", () => {
    render(<MagnetTable levels={LEVELS} />);
    expect(screen.getAllByText(/no measured edge/i).length).toBe(2);
  });

  it("never renders a distance-percent headline", () => {
    const { container } = render(<MagnetTable levels={LEVELS} />);
    expect(container.textContent).not.toMatch(/[+-]\d+\.\d%/);
  });

  it("renders all five rows in price order", () => {
    render(<MagnetTable levels={LEVELS} />);
    for (const label of ["STRETCH", "RESISTANCE", "LAST", "SUPPORT", "DOWN"])
      expect(screen.getByText(label)).toBeTruthy();
  });

  it("renders nothing when there is no confirmed swing", () => {
    const { container } = render(<MagnetTable levels={null} />);
    expect(container.textContent).toMatch(/no confirmed swing/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npm run test -- magnetTable`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `MagnetTable.tsx`**

```tsx
// web/components/stock/tabs/technicals/MagnetTable.tsx
"use client";

import type { MagnetsResponse } from "@/lib/api";

type Levels = NonNullable<MagnetsResponse["levels"]>;

// Reference palette, deliberately NOT argon CSS tokens (spec §5.1). The colour
// IS the role — do not swap these for theme variables.
export const MAGNET_COLORS = {
  stretch: "#22d3ee", // cyan
  resistance: "#fb7185", // salmon
  last: "#facc15", // yellow
  support: "#4ade80", // green
  down: "#f59e0b", // amber
} as const;

const NO_EDGE = "0.618 extension — no measured edge";

export default function MagnetTable({ levels }: { levels: Levels | null }) {
  if (!levels)
    return (
      <div
        style={{ fontFamily: "var(--font-mono)", fontSize: 12, opacity: 0.6 }}
      >
        No confirmed swing — fewer than two ZigZag pivots at this threshold.
      </div>
    );

  const rows: { label: string; price: number; color: string; role: string }[] =
    [
      {
        label: "STRETCH",
        price: levels.stretch,
        color: MAGNET_COLORS.stretch,
        role: NO_EDGE,
      },
      {
        label: "RESISTANCE",
        price: levels.resistance,
        color: MAGNET_COLORS.resistance,
        role: "last confirmed swing high",
      },
      {
        label: "LAST",
        price: levels.last,
        color: MAGNET_COLORS.last,
        role: "current close",
      },
      {
        label: "SUPPORT",
        price: levels.support,
        color: MAGNET_COLORS.support,
        role: "last confirmed swing low",
      },
      {
        label: "DOWN",
        price: levels.down,
        color: MAGNET_COLORS.down,
        role: NO_EDGE,
      },
    ];

  return (
    <table
      style={{
        width: "100%",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
        borderCollapse: "collapse",
      }}
    >
      <tbody>
        {rows.map((r) => (
          <tr
            key={r.label}
            style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}
          >
            <td
              style={{
                color: r.color,
                fontWeight: 700,
                padding: "4px 8px 4px 0",
              }}
            >
              {r.label}
            </td>
            <td style={{ textAlign: "right", padding: "4px 12px 4px 0" }}>
              {r.price.toFixed(2)}
            </td>
            <td style={{ opacity: 0.65 }}>{r.role}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Implement `MagnetRead.tsx`**

```tsx
// web/components/stock/tabs/technicals/MagnetRead.tsx
"use client";

export default function MagnetRead({ read }: { read: string[] }) {
  return (
    <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
      <div
        style={{
          fontWeight: 700,
          letterSpacing: 1,
          marginBottom: 6,
          opacity: 0.8,
        }}
      >
        THE READ
      </div>
      <ul style={{ margin: 0, paddingLeft: 16, lineHeight: 1.6 }}>
        {read.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <div
        style={{
          marginTop: 10,
          fontStyle: "italic",
          opacity: 0.5,
          fontSize: 11,
        }}
      >
        Scenario paths are illustrative, not forecasts. The 0.618 extension was
        tested against a matched null at five ZigZag thresholds and showed no
        edge.
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Implement `MagnetSubTab.tsx`**

```tsx
// web/components/stock/tabs/technicals/MagnetSubTab.tsx
"use client";

import { useEffect, useState } from "react";

import { api, type MagnetsResponse, type TechnicalsResponse } from "@/lib/api";
import MagnetRead from "./MagnetRead";
import MagnetTable from "./MagnetTable";

// Measured coverage per horizon, from the Phase 1 calibration. Kept here as the
// single legend source; the numbers themselves come off the API per band.
const BAND_NOTE: Record<number, string> = {
  5: "",
  10: "",
  21: " · 21d errors run narrow; treat this band as a floor",
};

export default function MagnetSubTab({
  ticker,
  technicals,
}: {
  ticker: string;
  technicals: TechnicalsResponse | null;
}) {
  const [data, setData] = useState<MagnetsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(null);
    api
      .magnets(ticker)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [ticker]);

  if (error)
    return (
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        {error}
      </div>
    );
  if (!data)
    return (
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        Loading…
      </div>
    );

  // rsi14 lives on TechnicalsSeriesRow, NOT on TechnicalsResponse — the response
  // carries `series: TechnicalsSeriesRow[]`. Read the last row.
  const row = technicals?.series?.at(-1) ?? null;
  const rsi = row?.rsi14 ?? null;
  const iv = data.atm_iv_30d;
  const dIv = data.atm_iv_30d_chg_5d;
  const state = data.levels?.leg_state ?? "no swing";

  const pct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const tiles: { label: string; headline: string; delta: string | null }[] = [
    {
      label: "VOLUME",
      headline:
        row?.volume != null ? `${(row.volume / 1e6).toFixed(1)}M` : "na",
      delta: null,
    },
    {
      label: "RSI 14",
      headline: rsi != null ? rsi.toFixed(1) : "na",
      delta:
        row?.rsi_slope5 != null
          ? `${row.rsi_slope5 >= 0 ? "+" : ""}${row.rsi_slope5.toFixed(1)} 5d`
          : null,
    },
    {
      label: "MOMENTUM",
      headline:
        row?.macd_hist_atr != null ? row.macd_hist_atr.toFixed(2) : "na",
      delta:
        row?.macd_slope3 != null
          ? `${row.macd_slope3 >= 0 ? "▲" : "▼"} 3d`
          : null,
    },
    {
      label: "ATM IV",
      headline: iv != null ? pct(iv).replace("+", "") : "na",
      delta:
        dIv != null
          ? `${dIv >= 0 ? "+" : ""}${(dIv * 100).toFixed(1)}pt 5d`
          : null,
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div style={{ fontSize: 20, fontWeight: 800, color: "#4ade80" }}>
          {data.ticker} · {state.toUpperCase()}
        </div>
        <div
          style={{ fontFamily: "var(--font-mono)", fontSize: 11, opacity: 0.6 }}
        >
          {[
            state,
            rsi != null ? `RSI ${rsi.toFixed(1)}` : null,
            data.levels
              ? `${data.levels.pivot_b.kind} @ ${data.levels.pivot_b.price.toFixed(2)}`
              : null,
            iv != null
              ? `ATM IV ${(iv * 100).toFixed(1)}%${dIv != null ? ` (${dIv >= 0 ? "+" : ""}${(dIv * 100).toFixed(1)}pt 5d)` : ""}`
              : null,
          ]
            .filter(Boolean)
            .join(" | ")}
        </div>
      </div>

      {/* Task 6 replaces this line with <MagnetChart data={data} />. Left as a
          placeholder so THIS task typechecks on its own — importing a component
          the next task creates makes Step 7's `npm run typecheck` fail. */}
      <div
        style={{
          height: 420,
          opacity: 0.4,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
      >
        chart pending (Task 6)
      </div>

      {/* Spec §5.1 item 3: four tiles, label left / headline + delta right.
          "na" is rendered literally when a source is missing — never a zero or a
          dash that could read as a real reading. */}
      <div
        data-testid="magnet-tiles"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8,
        }}
      >
        {tiles.map((t) => (
          <div
            key={t.label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              padding: "6px 10px",
              border: "1px solid rgba(255,255,255,0.08)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            <span style={{ opacity: 0.55, letterSpacing: 0.5 }}>{t.label}</span>
            <span>
              <strong style={{ fontSize: 13 }}>{t.headline}</strong>
              {t.delta ? (
                <span style={{ opacity: 0.5, marginLeft: 6 }}>{t.delta}</span>
              ) : null}
            </span>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <MagnetTable levels={data.levels} />
        <MagnetRead read={data.read} />
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          opacity: 0.5,
          fontStyle: "italic",
        }}
      >
        {data.bands
          .filter((b) => b.band_sigma === 1.96)
          .map(
            (b) =>
              `${b.horizon}d 1.96σ band held ${Math.round(b.measured_confidence * 100)}% of moves ` +
              `(${(b.measured_ci_lo * 100).toFixed(1)}–${(b.measured_ci_hi * 100).toFixed(1)}%, ` +
              `${b.measured_n_dates} sessions, Dec 2025–Jul 2026)${BAND_NOTE[b.horizon] ?? ""}`,
          )
          .join("   ·   ")}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Wire the toggle into `TechnicalsTab.tsx`**

Same `localStorage` pattern `TechnicalsPriceChart.tsx` uses (`OVERLAY_MODE_KEY`,
`CHANLUN_KEY`, …). Read lazily inside `useState` so SSR does not touch
`localStorage`.

**Name collision, read this first:** `TechnicalsTab` already binds `view` — it is
the timeframe-sliced series, passed as `data={view}` at `TechnicalsTab.tsx:456`
and to five other children. The new state is therefore `subView`, and the existing
`view` is left alone. Do not rename the existing one.

```tsx
// near the other imports
import MagnetSubTab from "./technicals/MagnetSubTab";

const SUB_VIEW_KEY = "technicals:view";

// inside TechnicalsTab, beside the other useState calls
const [subView, setSubView] = useState<"chart" | "magnet">(() => {
  if (typeof window === "undefined") return "chart";
  // READ is guarded too, not just the write: localStorage access itself throws
  // when storage is disabled, which would take the whole tab down on mount.
  // TechnicalsPriceChart.tsx:76 guards both sides for the same reason.
  try {
    return localStorage.getItem(SUB_VIEW_KEY) === "magnet" ? "magnet" : "chart";
  } catch {
    return "chart";
  }
});
const selectSubView = (v: "chart" | "magnet") => {
  setSubView(v);
  try {
    localStorage.setItem(SUB_VIEW_KEY, v);
  } catch {
    /* private mode — the toggle still works, it just does not persist */
  }
};
```

Then, in the returned tree, replace the `<TechnicalsPriceChart .../>` element
(currently at `TechnicalsTab.tsx:456`) with the switch below, leaving
`<TechnicalsKpiStrip>` and `<ReorderableList>` untouched. The
`<TechnicalsPriceChart>` props are copied verbatim from what is there today —
`data={view}` stays `data={view}`:

```tsx
<>
  <div
    data-testid="magnet-view-toggle"
    style={{
      display: "flex",
      gap: 6,
      fontFamily: "var(--font-mono)",
      fontSize: 11,
    }}
  >
    {(["chart", "magnet"] as const).map((v) => (
      <button
        key={v}
        onClick={() => selectSubView(v)}
        style={{
          padding: "2px 8px",
          cursor: "pointer",
          opacity: subView === v ? 1 : 0.5,
          border: "1px solid rgba(255,255,255,0.15)",
          background: "transparent",
          color: "inherit",
        }}
      >
        {v === "chart" ? "PRICE" : "MAGNET VIEW"}
      </button>
    ))}
  </div>
  {subView === "chart" ? (
    <TechnicalsPriceChart
      data={view}
      fullRows={data.series ?? []}
      control={<TimeframeSelect value={timeframe} onChange={setTimeframe} />}
    />
  ) : (
    <MagnetSubTab ticker={data.ticker} technicals={data} />
  )}
</>
```

The two elements are wrapped in a fragment because they replace a single child of
the outer flex column — dropping them in as two bare siblings changes nothing
about the layout but does not parse as one expression.

The timeframe selector lives inside `TechnicalsPriceChart`'s `control` slot, so it
disappears on the magnet view. That is correct: the magnet chart's window is fixed
at 180 sessions by the endpoint and a selector that changed nothing would lie.

- [ ] **Step 7: Run tests**

Run: `cd web && npm run test -- magnetTable && npm run typecheck && npm run lint`
Expected: 4 passed, typecheck clean

- [ ] **Step 8: Commit**

```bash
git add web/components/stock/tabs/technicals/ web/components/stock/tabs/TechnicalsTab.tsx \
        web/tests/components/magnetTable.test.tsx
git commit -m "feat(magnets): sub-tab shell, level table and read panel"
```

---

### Task 6: `MagnetChart` — candles, SMA20, ZigZag, pivots, level bands

**Files:**

- Create: `web/components/stock/tabs/technicals/MagnetChart.tsx`

Reuse `ISeriesApi.createPriceLine` for the level bands (pattern at
`TechnicalsPriceChart.tsx:635`) and `createSeriesMarkers` for the A/B pivot
triangles (pattern at `TechnicalsPriceChart.tsx:8,528`).

**Five** price lines, not four: STRETCH / RESISTANCE / LAST / SUPPORT / DOWN.
Spec §5.1's table lists five and the reference draws LAST as its own yellow
dashed line with a filled label box; "four levels" elsewhere in the spec counts
the geometry-derived ones and omits LAST.

Levels render as **translucent bands with a solid core**, not hairlines (spec §5.1).
The band half-width is 0.25% of the level — wide enough to read as a zone, narrow
enough not to overlap adjacent levels on a normal swing.

**`createPriceLine` cannot fill.** Three stacked price lines make a hairline
sandwich, not a zone. The fill comes from `lib/lwc/bandsIndicator.ts`'s
`BandsIndicator` — the same primitive `TechnicalsPriceChart.tsx:500-505` already
attaches for the anchored-VWAP envelope. Its `setBandData(BandPoint[])` takes
explicit `{time, upper, lower}` points, so a horizontal zone is two points at
constant values. One instance per level, each with its own `fillColor`.

Two points is safe, not a degenerate case: `ClosestTimeIndexFinder._performSearch`
guards `high < 0` and otherwise runs an ordinary binary search, and
`UpperLowerInRange.getMinMax` chunks by 4 so a 2-element array collapses to a
single chunk (`bandsIndicator.ts:87-90,126-137`). Two valid points form one
contiguous run and paint one quad — which is exactly a horizontal zone.

**Marker shapes: a documented fidelity gap.** Spec §5.1 asks for hollow triangles.
Lightweight-charts v5 ships `arrowUp` / `arrowDown` / `circle` / `square`
(`web/node_modules/lightweight-charts/dist/typings.d.ts:4922`) — all filled, no
triangle and no outline mode. Hollow triangles would need a custom
`ISeriesPrimitive`. **Use the filled arrows** and accept the deviation: the
information (which pivot, which side, what colour) is fully carried, and a
bespoke marker primitive is a poor trade for outline-vs-fill. Record it in the
CHANGELOG entry rather than silently diverging from the spec.

BB(20,2σ) is NOT here — it attaches in Task 7, so `BandsIndicator` gains its
second consumer in one place rather than being wired here and rewritten there.

- [ ] **Step 1: Implement the chart and swap out Task 5's placeholder**

In `MagnetSubTab.tsx`, restore `import MagnetChart from "./MagnetChart";` and
replace the `chart pending (Task 6)` div with `<MagnetChart data={data} />`.

```tsx
// web/components/stock/tabs/technicals/MagnetChart.tsx
"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import type { MagnetsResponse } from "@/lib/api";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { MAGNET_COLORS } from "./MagnetTable";

const BAND_HALF_WIDTH = 0.0025; // 0.25% of the level — a zone, not a hairline

function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i]!;
    if (i >= n) sum -= values[i - n]!;
    out.push(i >= n - 1 ? sum / n : null);
  }
  return out;
}

export default function MagnetChart({ data }: { data: MagnetsResponse }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current || data.candles.length === 0) return;
    const chart: IChartApi = createChart(host.current, {
      autoSize: true, // house pattern (DensityConeChart.tsx:117) — no ResizeObserver
      height: 420,
      layout: { background: { color: "transparent" }, textColor: "#94a3b8" },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, rightOffset: 24 },
    });

    const price = chart.addSeries(CandlestickSeries, {
      upColor: "#4ade80",
      downColor: "#fb7185",
      borderVisible: false,
      wickUpColor: "#4ade80",
      wickDownColor: "#fb7185",
    });
    price.setData(
      data.candles.map((c) => ({
        time: c.date as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    const closes = data.candles.map((c) => c.close);
    const ma = chart.addSeries(LineSeries, { color: "#c4b5fd", lineWidth: 2 });
    ma.setData(
      sma(closes, 20)
        .map((v, i) =>
          v == null ? null : { time: data.candles[i]!.date as Time, value: v },
        )
        .filter((x): x is { time: Time; value: number } => x !== null),
    );

    // ZigZag polyline through the confirmed pivots, plus the last close so the
    // live leg is visible. Pivot indices are already rebased to `candles`.
    if (data.pivots.length >= 2) {
      const zig = chart.addSeries(LineSeries, {
        color: "#818cf8",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        crosshairMarkerVisible: false,
      });
      const last = data.candles[data.candles.length - 1]!;
      zig.setData([
        ...data.pivots.map((p) => ({
          time: data.candles[p.index]!.date as Time,
          value: p.price,
        })),
        { time: last.date as Time, value: last.close },
      ]);
    }

    // A / B markers on the last two pivots only — the reference labels exactly two.
    const ab = data.pivots.slice(-2);
    const markers: SeriesMarker<Time>[] = ab.map((p, i) => ({
      time: data.candles[p.index]!.date as Time,
      position: p.kind === "top" ? "aboveBar" : "belowBar",
      color: p.kind === "top" ? "#fb7185" : "#4ade80",
      shape: p.kind === "top" ? "arrowDown" : "arrowUp",
      text: i === 0 ? "A" : "B",
    }));
    createSeriesMarkers(price, markers);

    // Five levels: a solid core price-line plus a FILLED translucent zone.
    // createPriceLine cannot fill, so the zone is a BandsIndicator — the same
    // primitive TechnicalsPriceChart.tsx:500-505 attaches for BB.
    if (data.levels) {
      const lv = data.levels;
      const first = data.candles[0]!.date as Time;
      // The zone must reach PAST the last candle, into the projection zone where
      // Task 7 draws the cone. That overlap is the whole read: a 0.618 level whose
      // zone runs outside the cone is visibly outside it. Stopping the zone at the
      // last bar would leave the two objects on disjoint x-ranges and there would
      // be nothing to compare. 30 calendar days covers the 21d horizon (~29d).
      const lastBarDate = data.candles[data.candles.length - 1]!.date;
      const edge = new Date(`${lastBarDate}T00:00:00Z`);
      edge.setUTCDate(edge.getUTCDate() + 30);
      const last = edge.toISOString().slice(0, 10) as Time;
      const levels: [number, string, LineStyle, string][] = [
        [lv.stretch, MAGNET_COLORS.stretch, LineStyle.Dashed, "STRETCH"],
        [
          lv.resistance,
          MAGNET_COLORS.resistance,
          LineStyle.Solid,
          "RESISTANCE",
        ],
        [lv.last, MAGNET_COLORS.last, LineStyle.Dashed, "LAST"],
        [lv.support, MAGNET_COLORS.support, LineStyle.Solid, "SUPPORT"],
        [lv.down, MAGNET_COLORS.down, LineStyle.Dashed, "DOWN"],
      ];
      for (const [value, color, style, title] of levels) {
        price.createPriceLine({
          price: value,
          color,
          lineWidth: 2,
          lineStyle: style,
          axisLabelVisible: true,
          title,
        });
        // Two points at constant values = a horizontal filled zone spanning the
        // drawn window. `${color}22` is ~13% alpha: readable as an area, never
        // competing with the candles.
        const zone = new BandsIndicator({
          lineColor: "transparent",
          fillColor: `${color}22`,
          lineWidth: 1,
        });
        price.attachPrimitive(zone);
        zone.setBandData([
          {
            time: first,
            upper: value * (1 + BAND_HALF_WIDTH),
            lower: value * (1 - BAND_HALF_WIDTH),
          },
          {
            time: last,
            upper: value * (1 + BAND_HALF_WIDTH),
            lower: value * (1 - BAND_HALF_WIDTH),
          },
        ]);
      }
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return <div ref={host} style={{ width: "100%" }} />;
}
```

BB(20,2σ) is added in Task 7 alongside the other primitives, so the
`bandsIndicator` attach happens once rather than being written here and rewritten
there.

- [ ] **Step 2: Add automated coverage via the existing Playwright harness**

Spec §6 rules out vitest for charts (lightweight-charts needs `matchMedia`, which
jsdom lacks). It does **not** rule out a real browser, and this repo already has
one wired: `web/playwright.technicals.config.ts` boots
`tests/e2e/technicals-fixture-server.mjs` (a 54-line stub API on :18400) plus a
production Next build, and `tests/e2e/technicals-tab.spec.ts` asserts the chart
renders with **zero console errors and no `NaN` in the DOM**. That is exactly the
class of bug a screenshot does not catch, so wire the magnet view into it rather
than relying on eyeballing.

Add a `/api/stock/DRYRUN/magnets` branch to the fixture server beside the existing
`/technicals` one at `technicals-fixture-server.mjs:44`, serving a payload with
two pivots, non-null levels and six bands. Add `data-testid="magnet-chart"` to
`MagnetChart.tsx`'s host div and `data-testid="magnet-view-toggle"` to the
selector buttons from Task 5. Then extend the config's `testMatch` to
`/(technicals-tab|magnet-view)\.spec\.ts/` and add:

```ts
// web/tests/e2e/magnet-view.spec.ts
import { expect, test, type Page } from "@playwright/test";

const consoleErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  consoleErrors.set(page, errors);
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await page.route(
    /\/stock\/DRYRUN\/(?!technicals|magnets)(?:[^?]*)/,
    (route) =>
      route.fulfill({ status: 200, contentType: "text/x-component", body: "" }),
  );
  await page.goto("/stock/DRYRUN/technicals");
  await page.getByTestId("magnet-view-toggle").getByText("MAGNET VIEW").click();
});

test("magnet chart renders without console errors or NaN", async ({ page }) => {
  await expect(page.getByTestId("magnet-chart")).toBeVisible();
  const body = (await page.textContent("body")) ?? "";
  expect(body).not.toMatch(/NaN/);
  expect(body).not.toMatch(/undefined/);
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("the 0.618 rows are labelled as having no measured edge", async ({
  page,
}) => {
  await expect(page.getByText(/no measured edge/i).first()).toBeVisible();
  // The failed geometry must never carry a percentage.
  const body = (await page.textContent("body")) ?? "";
  expect(body).not.toMatch(/0\.618[^.]{0,40}%/);
});

test("band legend shows the interval, not a bare point estimate", async ({
  page,
}) => {
  await expect(page.getByText(/held \d+% of moves \(\d/)).toBeVisible();
});

test("the sub-view choice survives a reload", async ({ page }) => {
  await page.reload();
  await expect(page.getByTestId("magnet-chart")).toBeVisible();
});
```

Run: `cd web && npm run test:e2e:technicals`
Expected: the existing technicals specs plus these four pass.

- [ ] **Step 3: Eyeball it against real data**

The e2e run uses stub data, so it proves the component is wired, not that the
numbers look right. Run `bash scripts/dev.sh`, open
`http://localhost:3001/stock/AAPL`, Technicals → MAGNET VIEW, and capture to
`output/playwright/magnet-chart-aapl.png`.
Expected: candles + SMA20 + dashed ZigZag + A/B markers + five coloured level
bands, resistance at 340.08 and support at 275.15 (the swing verified against the
mini 2026-08-09).

- [ ] **Step 4: Commit**

```bash
git add web/components/stock/tabs/technicals/MagnetChart.tsx \
        web/components/stock/tabs/technicals/MagnetSubTab.tsx \
        web/tests/e2e/magnet-view.spec.ts web/tests/e2e/technicals-fixture-server.mjs \
        web/playwright.technicals.config.ts
git commit -m "feat(magnets): magnet chart with level bands and pivot markers"
```

---

### Task 7: Right edge — BB(20,2σ) and the options-implied cone

**Files:**

- Modify: `web/components/stock/tabs/technicals/MagnetChart.tsx`

**No new `lib/lwc` file, and no scenario paths.** Two earlier drafts of this plan
were wrong here and both are recorded so nobody re-derives them:

1. A `web/lib/lwc/scenarioPaths.ts` `ISeriesPrimitive` was going to draw the
   forward dashed paths. `DensityConeChart.tsx:355-380` already draws that exact
   shape with a plain `chart.addSeries(LineSeries, {lineStyle: Dashed})` and a
   two-point `setData`. A primitive class buys nothing.
2. The paths themselves are cut entirely — spec §1.2 replaces the decorative fan
   with the cone. See "Reconciliation" §0.

The cone is likewise plain `LineSeries`, not `densityProfile.ts`: that primitive
renders a filled density histogram, which this view does not draw.

**Twelve cone series, not six.** `data.bands` holds six `(horizon, sigma)`
records — 3 horizons × 2 sigmas — and each contributes an upper AND a lower edge.
Twelve short segments radiating from the last bar is the fan look; if it reads as
noise in the browser check, drop the 1.0σ pair (six segments) rather than
thinning the 1.96σ pair, because 1.96σ is the band the legend quotes.

BB(20,2σ) attaches here via `lib/lwc/bandsIndicator.ts`, which Task 6 already
imports for the level zones.

Keep the `history ← | → scenarios` divider caption verbatim — it is what makes
the right edge legible as projection rather than data.

- [ ] **Step 1: Add the cone to `MagnetChart`**

```tsx
// inside MagnetChart's useEffect, after the level zones
const lastBar = data.candles[data.candles.length - 1]!;
// Horizon in CALENDAR days so the right-edge distance is proportional to what
// the band means. Same h*7/5 mapping the calibration used for target_dte.
const future = (tradingDays: number) => {
  const d = new Date(`${lastBar.date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + Math.round((tradingDays * 7) / 5));
  return d.toISOString().slice(0, 10) as Time;
};

for (const b of data.bands) {
  const t = future(b.horizon);
  for (const edge of [b.upper, b.lower]) {
    const s = chart.addSeries(LineSeries, {
      // 1.96σ is the quoted band, so it is the more visible one.
      color: b.band_sigma === 1.96 ? "#38bdf8cc" : "#38bdf866",
      lineWidth: 1,
      lineStyle: LineStyle.Solid,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    s.setData([
      { time: lastBar.date as Time, value: lastBar.close },
      { time: t, value: edge },
    ]);
  }
}
```

- [ ] **Step 2: Attach BB(20,2σ)**

```tsx
// BB(20,2sigma) on the candle series — same primitive as the level zones.
const closes20 = data.candles.map((c) => c.close);
const bb = new BandsIndicator({
  lineColor: "transparent",
  fillColor: "rgba(196,181,253,0.10)",
  lineWidth: 1,
});
price.attachPrimitive(bb);
bb.setBandData(
  data.candles.map((c, i) => {
    if (i < 19) return { time: c.date as Time };
    const w = closes20.slice(i - 19, i + 1);
    const m = w.reduce((a, x) => a + x, 0) / 20;
    const sd = Math.sqrt(w.reduce((a, x) => a + (x - m) ** 2, 0) / 20);
    return { time: c.date as Time, upper: m + 2 * sd, lower: m - 2 * sd };
  }),
);
```

`BandPoint` allows `{time}` with no `upper`/`lower` — that is how the first 19
bars are represented, and `contiguousValidRuns` (`bandsIndicator.ts:225`) splits
the fill on those gaps rather than interpolating across them.

- [ ] **Step 3: Add the divider caption**

A single centred `history ← | → scenarios` label at the last bar's x-position,
rendered as ordinary absolutely-positioned DOM over the chart host (not a chart
primitive — it is a static caption, and a primitive for it would be the same
mistake as `scenarioPaths.ts`).

- [ ] **Step 4: Verify**

```bash
cd web && npm run typecheck && npm run test && npm run test:e2e:technicals
```

Then browser-check the right edge; capture `output/playwright/magnet-right-edge-aapl.png`.
Expected: BB fill behind the candles, twelve cone segments fanning right from the
last bar with the 1.96σ pair more visible, the divider caption, and **no dashed
path terminating at STRETCH or DOWN**.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/tabs/technicals/MagnetChart.tsx
git commit -m "feat(magnets): BB bands and the options-implied cone"
```

---

### Task 8: CHANGELOG and docs

**Files:**

- Modify: `CHANGELOG.md`, `CLAUDE.md` ("Where to look first" table)

- [ ] **Step 1: Add the `[Unreleased]` entry**

```markdown
### Added

- **Technicals "Magnet View" sub-tab** — reference-style chart with ZigZag pivots,
  five magnet levels, and an options-implied cone at 5/10/21d whose bands are
  labelled with measured (not nominal) confidence **and its 95% interval**. The
  0.618 extension renders as unlabelled geometry: it was tested against a matched
  null at five ZigZag thresholds (938 legs at the loosest) and showed no edge, so
  nothing on the view asserts price will reach it. Two deliberate deviations from
  the reference: pivot markers are filled arrows (lightweight-charts v5 has no
  hollow-triangle shape), and the decorative scenario fan is replaced by the cone
  rather than drawn alongside it.
  Research: `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md`.

### Fixed

- **Corporate-action and calendar-gap guards for `daily_ohlc`-derived research**
  (`reports/magnet_data.py`). Unadjusted splits (CRWD 4:1, KORU 20:1) and a ticker
  reuse (SPCX) were inflating `std(z)` to 1.116 with excess kurtosis 361.
```

- [ ] **Step 2: Add the CLAUDE.md row**

```markdown
| Technicals Magnet View (levels + options-implied cone) | `cards/magnets.py` + `models/magnets.py` + `api/routers/stock.py` (`/magnets`) + `web/components/stock/tabs/technicals/*` + `lib/{volumeProfile,lwc/volumeProfile}.ts` (dot-cloud mode); research `docs/research/2026-08-08-magnet-cone-calibration/VERDICT.md` (G1 failed — 0.618 is geometry only), plan `docs/superpowers/plans/2026-08-09-magnet-view-phase2-3-build.md` |
```

- [ ] **Step 3: Full verification — reproduce the whole CI job, not just ruff+pytest**

`.github/workflows/ci.yml`'s "lint + unit" job is nine steps and the web job runs
`npm run build`, not just typecheck. Running only `ruff` + `pytest` locally is how
a green local run turns into a red PR.

```bash
python3 scripts/release/version_sync_check.py
uv run ruff check src/ tests/ scripts/
uv run python scripts/_lint_except.py src
uv run python scripts/check_no_yahoo.py
uv run python scripts/check_runtime_assets.py
! grep -rE 'class _Fake(Cursor|Connection)' tests/integration/
! grep -rE '"\|".join\(' src/
! grep -rE 'from tests' src/
! grep -rE 'from uw_scan\.fixtures' src/
uv run python scripts/check_migration_prefixes.py
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v
cd web && npm run typecheck && npm run test && npm run lint && npm run build
cd web && npm run test:e2e:technicals   # ci.yml:198 — the job this plan added specs to
```

Expected: all green. Note the third grep — Guardrail 3 forbids `from tests` in
`src/` only, so the new `tests/fixtures/aapl_daily.py` import inside `tests/` is
fine; do not "fix" it by moving the fixture into `src/`.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md CLAUDE.md
git commit -m "docs(magnets): changelog and where-to-look entries"
```

---

### Task 9: Magnet dot-cloud profile (deferred — ships last)

**Files:**

- Modify: `web/lib/volumeProfile.ts` — the **binning maths** (`VpBin`, `computeVolumeProfile`)
- Modify: `web/lib/lwc/volumeProfile.ts` — the **renderer** (`VolumeProfileIndicator`)
- Modify: `web/components/stock/tabs/technicals/MagnetChart.tsx`
- Test: `web/tests/lib/volumeProfile.test.ts` (exists — append)

**Two files, not one.** `lib/volumeProfile.ts` computes bins; `lib/lwc/volumeProfile.ts`
paints them (`lib/lwc/volumeProfile.ts:5` says so explicitly). The recency data
belongs in the first, the dot mode in the second. Editing only the renderer
cannot work — see below.

Spec §5.2's magnet profile: volume-at-price as a jittered dot cloud, red above
spot, green below, **gold for the last 15 sessions**, a smooth envelope on the
outer edge, and a ★ at the heaviest shelf.

**Why this is its own task and goes last.** The plan originally claimed this was
"a render mode; the binning, POC and value-area maths are untouched." That is
false. `VpBin` is `{low, high, buy, sell}` (`web/lib/volumeProfile.ts:21-26`) —
aggregate buy/sell volume per price bin with **no recency provenance whatsoever**.
The gold subset cannot be derived from the existing bins at any price; it needs a
second aggregation over the last 15 bars against identical bin boundaries, which
means changing the computed data shape in a module the Price view also consumes.

That is real risk in shared code, and this layer carries **zero analytic
content** — it is the one purely decorative deliverable in the plan. Everything
that carries a measurement ships first. If the branch has to be cut short, this
is what gets dropped, and the view is complete without it.

- [ ] **Step 1: Extend `VpBin` with a recent slice**

```ts
// web/lib/volumeProfile.ts
export type VpBin = {
  low: number; // bin price bounds
  high: number;
  buy: number;
  sell: number;
  recent: number; // buy+sell from the last RECENT_BARS bars only
};

export const RECENT_BARS = 15; // spec §5.2: "gold = last 15d"
```

`computeVolumeProfile` gains one branch in its existing per-bar loop: when the
bar's index is `>= bars.length - RECENT_BARS`, also add its volume to
`bin.recent`. It reuses the loop's own `lo`/`hi`/`binCount` — do **not** compute
bin boundaries a second time for the subset, or the gold dots land in bins the
bars did not belong to.

- [ ] **Step 2: Write the failing tests**

```ts
// web/tests/lib/volumeProfile.test.ts — append
import { binJitter } from "@/lib/lwc/volumeProfile";

describe("binJitter", () => {
  it("is deterministic for a given bin and dot index", () => {
    expect(binJitter(7, 3)).toBe(binJitter(7, 3));
  });

  it("differs across bins so the cloud does not look striped", () => {
    expect(binJitter(7, 3)).not.toBe(binJitter(8, 3));
  });

  it("differs across dots within a bin", () => {
    expect(binJitter(7, 3)).not.toBe(binJitter(7, 4));
  });

  it("stays within the unit interval", () => {
    for (let b = 0; b < 50; b++)
      for (let d = 0; d < 10; d++) {
        expect(binJitter(b, d)).toBeGreaterThanOrEqual(0);
        expect(binJitter(b, d)).toBeLessThan(1);
      }
  });
});
```

Add two more against the new field, reusing `SPY_BARS` from
`web/tests/unit/fixtures/spyBars` — the same real-bar fixture the existing
`volumeProfile.test.ts` already imports: (a) `bin.recent <= bin.buy + bin.sell` for every bin,
and (b) `sum(bin.recent)` equals the total volume of the last 15 bars. (b) is the
invariant that catches a misaligned second aggregation — the failure mode where
gold dots appear in the wrong bins is otherwise invisible except by eye.

- [ ] **Step 3: Run to verify they fail**

Run: `cd web && npm run test -- volumeProfile`
Expected: FAIL — `binJitter` not exported (the file's existing tests still pass)

- [ ] **Step 4: Implement `binJitter`**

```ts
// web/lib/lwc/volumeProfile.ts — add
/** Deterministic jitter in [0,1). Seeded from (bin, dot) so the cloud does not
 *  shimmer on re-render or pan. Never Math.random.
 *
 *  ponytail: sin-hash, the standard shader trick. Not cryptographic and it does
 *  not need to be — it needs to be stable and to decorrelate adjacent bins. */
export function binJitter(bin: number, dot: number): number {
  const x = Math.sin(bin * 127.1 + dot * 311.7) * 43758.5453;
  return x - Math.floor(x);
}
```

- [ ] **Step 5: Add the `dots` render mode**

Add `mode: "bars" | "dots"` to `VolumeProfileOptions` (`lib/lwc/volumeProfile.ts:51`),
defaulting to `"bars"` so every existing caller keeps its current painting
byte-for-byte. The `dots` branch draws one dot per volume quantum per bin at
`x = binRight - binJitter(binIdx, dotIdx) * binWidth`, colours by
`binMidPrice >= spot ? red : green`, overpaints the first `bin.recent`-worth of
dots in gold, strokes the envelope through the outermost dot of each bin, and
marks `pocIdx` with ★ plus its price.

- [ ] **Step 6: Verify**

```bash
cd web && npm run test -- volumeProfile && npm run typecheck && npm run lint
cd web && npm run test:e2e:technicals
```

Then browser-check BOTH surfaces: the magnet view shows the dot cloud, and the
**Price view's volume-profile toggle still paints bars**. That second check is
the one that matters — this task edits shared code.
Capture `output/playwright/magnet-right-edge-aapl.png`.

- [ ] **Step 7: Commit**

```bash
git add web/lib/volumeProfile.ts web/lib/lwc/volumeProfile.ts \
        web/tests/lib/volumeProfile.test.ts \
        web/components/stock/tabs/technicals/MagnetChart.tsx
git commit -m "feat(magnets): dot-cloud volume profile render mode"
```

---

## Self-review

**Spec coverage.** §4 backend → Tasks 1–4 (all four functions plus endpoint; the
`last_pivot_index` refactor already shipped in Phase 1, commit `83b0387`). §5 web
→ Tasks 5–7 + 9 (four components, localStorage toggle, reuse table). §5.1 palette
and layout → Tasks 5/6, including the four tiles. §5.2 right edge → Tasks 7 and 9.
§6 testing → per-task tests; the no-vitest-for-charts rule is honoured, and the
gap it leaves is closed by the Playwright harness in Task 6 rather than by a
screenshot. §7 risks → surface depth is unchanged and disclosed in the read;
cross-sectional correlation was handled in Phase 1.

**Spec requirements deliberately NOT met, each with its reason.**

| Spec                               | Not met               | Why                                                                                                                                         |
| ---------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| §5.1 header subtitle `sector 5d`   | dropped               | no source on either payload; inventing one puts a fabricated number on a chart                                                              |
| §5.1 hollow triangle pivot markers | filled arrows instead | lightweight-charts v5 has no triangle or outline marker shape (`typings.d.ts:4922`); a custom primitive is a poor trade for outline-vs-fill |
| §5.2 scenario paths                | not built             | spec §1.2 replaces the decorative fan with the cone; see "Reconciliation" §0                                                                |
| §3.3 "21d withheld"                | 21d ships             | the spec withheld on 6 non-overlapping windows/ticker; the corrected run measures 21d with 708 independent observations                     |
| §2 pattern registry, §7.4 earnings | deferred              | unchanged from the spec's own deferral                                                                                                      |

**Statement corrected from an earlier draft:** this plan does not "ship no 0.618
targets" in the sense of removing them from the chart — STRETCH and DOWN are
still drawn as price lines. What it removes is every claim attached to them: no
target sentence, no distance-%, no path terminating on them, and role text that
says "no measured edge". The levels are geometry the user can see; nothing
asserts price will reach them.

**Deliberately not covered.** The corrected-G2-estimator work (fit by MAD or
direct quantile targeting) and the per-ticker-`k`-beats-pooled test are
pre-registered in `VERDICT.md` and are **not** in this plan — they are research,
not build.

**Type consistency.** `magnet_levels` returns the dict consumed by `build_read` and
by `MagnetLevels`; `cone` returns the list consumed by `build_read` and
`MagnetConeBand`. `CONE_HORIZONS`, `CONE_BANDS` and `all_pivots` are imported by
the router and by `build_read`. `MAGNET_COLORS` is exported from `MagnetTable.tsx`
and imported by `MagnetChart.tsx`. `BandsIndicator` is used by Tasks 6 and 7.
`binJitter` is exported from `volumeProfile.ts` and tested there (Task 9).
`api.magnets` returns `MagnetsResponse`, the same alias `MagnetSubTab` consumes.

**Sequencing.** Task 0 → 1 → 2 → 3 are strictly ordered (4 imports all of 1–3 plus
Task 0's `trim_to_clean_segment`). Task 5 needs Task 4's `types.ts` and ships a
placeholder where the chart goes, so it typechecks without Task 6. Task 6 creates
`MagnetChart`, swaps that placeholder out, and consumes Task 5's `MAGNET_COLORS`.
Task 7 modifies Task 6's file. Task 8 closes the branch. **Task 9 is optional and
last** — the view is complete and shippable without it.
