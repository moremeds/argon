# Macro desk — Treasuries page (tab 02) plan

Status: PLAN ONLY (design v3 asks for a plan first for the Treasuries page). No code in the macro-overview PR.
Date: 2026-10-13.

## Scope

Tab 02 (`/macro/rates`, `components/rates/CurveDesk.tsx`) keeps every section it has: the curve,
the 10-year split, drivers, supply, positioning, funding and auctions. Three changes:

### 1. Gold's real-yield sensitivity beside the 10-year split

- Add one panel next to `components/rates/sections/DecompositionSection.tsx` (the
  "Model decomposition" panel). It reuses `SensitivityPanel`'s real-yield row from
  `components/macro/goldFactor/GoldFactorPanels.tsx`, or a one-row variant of it.
- Data: `/api/gold/factor`, the last point's `b_r` with `b_r_lo95`/`b_r_hi95`. On prod on
  2026-10-13 that was about −0.05 %/bp, and the interval crosses zero.
- Copy: the interval prints with the point estimate, plus "interval crosses zero" when it
  spans zero, plus the research label "Describes the past, not a forecast · the direction
  test (Phase 3) failed".
- Live only, like the gold tab. `/api/gold/factor` has no `as_of`, so a replay hides the panel.

### 2. The "model accounts for 0.0bp" row

What I checked in code (not on prod data):

- `rates/calculations.py::_decomposition_attribution_row` computes `model_nominal_10y_bps`
  as the Cleveland model value at `as_of` minus its value at `prior_date`.
- The model is monthly. When both dates read the same monthly vintage, the difference is
  exactly 0.0.
- `DecompositionSection.tsx` "Move drivers" then prints "the Cleveland model accounts for
  +0.0bps". That reads as "the model explains nothing", but it really means "no new model
  value in this window".

Fix (backend and web, one PR):

- Return the two vintage dates (or a `model_vintage_changed: bool`) on
  `RatesDecompositionAttribution`.
- When the vintage did not change, the web shows "no new monthly model value in this window" instead of 0.0.
- This adds fields to a public API model, so it needs an OpenAPI snapshot update and
  `gen:types`.

Before building, confirm on prod that the 1M row's two dates do share one vintage. Use
`/api/rates/snapshot` → `decomposition.clarida_model_date` and the window dates.

### 3. Data date and release time on each yield

- Each yield tile (DGS10, DFII10, T10YIE, and the curve points) shows its observation date
  and when FRED published it. `GoldInputSeriesPoint.release_date` already carries the
  publish date for FRED series.
- The publish schedule for H.15 yields on FRED is unverified. Read it from stored
  `release_date` values before printing any fixed time. DFII10 is the series whose
  lag lets the gold factor model's `last_date` trail the FX legs (seen on 2026-10-13:
  `last_date` 2026-10-08).

## Acceptance

- The 10-year split shows gold's real-yield sensitivity with its interval. The numbers
  match `/api/gold/factor`.
- No "0.0bp" model attribution prints for a window with no new model vintage.
- Every yield shows its data date and release date.
- Existing rates tests, the OpenAPI snapshot and `gen:types` are updated in the same PR.

## Out of scope

- Any new rates data source.
- The Gold Gate engine rewrite (`macro/gold_state.py`), which is a separate decision.
