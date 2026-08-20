# Inflation and rates state design (MC2)

**Status:** preregistered. Written before the engines exist, so the golden scenarios in
`tests/fixtures/macro/inflation_rates_golden.json` are predictions, not descriptions.

**Goal:** turn MC0/MC1 evidence into two point-in-time domain states — `inflation` and `rates` —
that say what regime we are in, which way it is moving, how fast, and **how much of that we
actually know**. Replaces a composite score that could look confident while standing on one
populated input.

Reads: `uw_scan.macro_observations` (MC0 contract), `uw_scan.macro_source_artifacts`, and the four
MC1 policy paths. Writes: `uw_scan.macro_domain_states` + `macro_domain_state_evidence`.

---

## 0. Deviations from the MC2 plan

Recorded rather than silently absorbed. Each is measured, not assumed.

| # | Plan says | Reality | Consequence |
|---|---|---|---|
| D1 | `sources/bls.py`, `sources/bea.py` from BLS/BEA | BLS returns **403 on every host** under both a contact and a browser agent string; BEA returns **HTTP 200 / 0 bytes** without a UserID | Neither module is built. ALFRED is the realized-inflation source. Evidence: [`docs/research/2026-08-18-mc2-inflation-source-probe/`](../../research/2026-08-18-mc2-inflation-source-probe/README.md) |
| D2 | migration `116_macro_domain_states.sql` | 116 is MC1's `macro_source_status`; 122 is `revenue_breakdown_obs`, merged 2026-08-18; 123/124 were then claimed by `company_sector` and `valuation_anchors_method_nullable` while this branch was open | MC2's migrations are **`125_macro_domain_states.sql`** and **`126_macro_vintage_bearing_artifacts.sql`** |
| D3 | scenario 3 is "dovish SEP but hawkish market pricing" | Measured: SEP end-2026 **3.80** vs market **3.875** — a **7.5bp** spread, i.e. the paths *agree* | Scenario is renamed `policy_paths_kept_separate` and asserts the contradiction does **not** fire. The disagreement branch has no real anchor (the market path is a live snapshot with no history), so it moves to a labelled threshold test |
| D4 | "test decompositions whose components do not add within tolerance" over nominal/real/breakeven | `T10YIE` is **defined** as `DGS10 − DFII10`; measured residual is 0.0bp in both probed episodes | The reconciliation rule applies only to the Cleveland Fed model's explicit components. A tolerance test over the FRED triple asserts an identity against itself |
| D5 | spec filename dated `2026-08-12` | authored 2026-08-18 | filename carries the authoring date, per repo convention |
| D6 | §4's completeness floor forces `INDETERMINATE` for every domain | Scenario 3 preregisters `ON_HOLD` with only the policy paths present and no curve/supply/positioning/plumbing data | For **rates**, the load-bearing set is the three official policy paths, not all nine factors. Supply and positioning do not bear on whether the committee cut, held or hiked, so their absence must not erase a published fact. The market path is excluded as a third-party shadow |
| D7 | "test decompositions whose components do not add within tolerance" over the Cleveland components | The Cleveland model's expected short real rate is **defined** as modelled real yield minus real term premium, so adding the premium back is a no-op. Measured intra-model residual: **0.0bp across all 332 months** | The only failable residual is the Cleveland modelled nominal against the **traded** `DGS10`. Its tolerance is calibrated, not picked: the two normally differ by 41bp (63bp since 2016), so the 25bp default would have fired on **66.9%** of months. Set to 85bp — the post-2016 p90, firing on 11 of 332 months, all in the 2022 repricing. Evidence: [`docs/research/2026-08-18-mc2-decomposition-residual/`](../../research/2026-08-18-mc2-decomposition-residual/README.md) |

## 1. What each state is

A `MacroDomainState` is one row per `(domain, as_of, engine_version, inputs_hash)`:

```text
domain              inflation | rates
state               a LEVEL regime label -- where we are
direction           RISING | FALLING | FLAT | UNKNOWN -- which way it is moving
velocity            how fast, with an explicit metric, unit and window
confidence          [0,1], a function of what we know, never of how big the signal is
confidence_reasons  the per-term breakdown that produced that number
contradictions      named rules that fired, with the values that fired them
factors             per-input sub-states, each with its own freshness and source
evidence_refs       exact obs_id FKs with a causal role
```

`state` and `direction` are deliberately separate. "Above target but falling" and "above target and
rising" are the same level and opposite situations; a single scalar cannot carry both, which is how
the legacy composite lost the distinction.

## 2. Inflation

### 2.1 The target basis is PCE, and this is load-bearing

The FOMC's 2 percent objective is stated on the **PCE** price index. Core CPI has run persistently
above core PCE across the whole sample — at 2024-06, core CPI YoY was 3.27 while core PCE was near
2.6. Scoring CPI against a 2 percent threshold therefore mislabels the regime by roughly one policy
move, permanently and in one direction.

So: **`state` is computed on core PCE year-over-year.** CPI is not discarded — it arrives about two
weeks earlier and is the higher-frequency corroborator — but it enters as its own factor and as a
contradiction input, never as the level being thresholded.

### 2.2 Inputs

| series | role | unit | transform | cadence |
|---|---|---|---|---|
| `PCEPILFE` | `realized` (**state basis**) | index 2017=100, SA | YoY from index | monthly, ~30d lag |
| `PCEPI` | `realized` | index 2017=100, SA | YoY from index | monthly, ~30d lag |
| `CPILFESL` | `realized` (corroborator) | index 1982-84=100, SA | YoY from index | monthly, ~13d lag |
| `CPIAUCSL` | `realized` (corroborator) | index 1982-84=100, SA | YoY from index | monthly, ~13d lag |
| `MEDCPIM158SFRBCLE` | `breadth` | **% change at annual rate** | none — publisher-transformed | monthly |
| `TRMMEANCPIM158SFRBCLE` | `breadth` | **% change at annual rate** | none — publisher-transformed | monthly |
| `CORESTICKM159SFRBATL` | `stickiness` | **% change from year ago** | none — publisher-transformed | monthly |
| `MICH` | `expectations_survey` | percent, NSA | none | monthly |
| `T10YIE`, `T5YIFR` | `expectations_market` | percent | none | daily |

**The three "core inflation" siblings carry three different transforms.** `MED` and `TRMMEAN` are
annualised month-over-month; `CORESTICK` is year-over-year. The suffix encodes it — `M158` versus
`M159` — and the titles do not. Treating them as commensurable is a silent unit error, so each
observation stores the publisher's unit string verbatim and the engine refuses to combine two
factors whose units differ.

Per the plan, **no source module computes a YoY**. A transform belongs to the series definition and
is applied in `macro/inflation.py` against observations already stored in publisher units.

### 2.3 Market compensation is not expectations

`T10YIE` and `T5YIFR` are breakevens: expected inflation **plus** an inflation risk premium **minus**
a TIPS liquidity premium. They are labelled `expectations_market` and are never presented as pure
expectations, and never averaged with `MICH`. When the two disagree the engine raises a contradiction
rather than splitting the difference.

### 2.4 State labels

Thresholds are versioned engine parameters, hashed into `inputs_hash` — not module constants.

| `state` | core PCE YoY |
|---|---|
| `BELOW_TARGET` | < 1.75 |
| `AT_TARGET` | 1.75 – 2.25 |
| `ABOVE_TARGET` | 2.25 – 3.00 |
| `WELL_ABOVE_TARGET` | > 3.00 |
| `INDETERMINATE` | completeness below floor, or no eligible core PCE observation at `as_of` |

`direction` from the three-month change in core PCE YoY: `FALLING` at ≤ −0.15pp, `RISING` at
≥ +0.15pp, `FLAT` between. `velocity` carries both `core_pce_yoy_change_3m` (pp) and
`core_pce_3m_annualized` (percent, annual rate), each with its window.

### 2.5 Contradictions

| rule | fires when |
|---|---|
| `cpi_pce_divergence` | \|core CPI YoY − core PCE YoY − 0.30\| > 0.50 (0.30 is the documented wedge) |
| `headline_core_divergence` | \|headline YoY − core YoY\| > 1.00pp |
| `stickiness_not_confirming_disinflation` | `direction` is `FALLING` while sticky core YoY has not fallen over 3m |
| `breadth_contradicts_core` | median-CPI 3m change and core-PCE 3m change have opposite signs |
| `expectations_diverge_from_realized` | realized `FALLING` while survey **and** market expectations both rise ≥ 0.20pp over 3m |
| `breadth_measures_disagree` | median-CPI and trimmed-mean 3m changes have opposite signs. Added after the 2022-01 anchor showed median at +0.89 and trimmed-mean at −0.90 in the same window — two breadth measures from one publisher pointing opposite ways |

## 3. Rates

### 3.1 The four paths never merge

`state` describes what the committee **has done**, which is a fact:
`EASING | ON_HOLD | TIGHTENING | INDETERMINATE`, from the actual target range over the trailing two
meetings.

Every forward path — committee (SEP), dealer (NY Fed SME), market (third-party shadow) — is a
separate factor carrying its own implied end-horizon rate, source, source kind, release date and
freshness. `direction` is the direction those paths **agree** on; when they disagree it is `UNKNOWN`
and `policy_paths_disagree` fires.

There is no configuration under which the engine produces a blended path. At authoring time the SEP
median for end-2026 is 3.80 and the market-implied rate is 3.875; their average, 3.8375, is not on
the SEP's eighth-point dot grid and is not a rate any participant projected or any contract prices.
It is an artifact of averaging, and it is exactly the number a composite would have reported.

An anonymous SEP dot is never attributed to the Chair, and a missing path degrades confidence — it
never becomes a neutral vote.

### 3.2 Factors

| factor | inputs | role |
|---|---|---|
| `policy_actual` | FOMC statement target range, action, vote | `policy_actual` |
| `policy_committee` | SEP `federal_funds_rate` medians + dot distribution | `policy_committee` |
| `policy_dealer` | NY Fed SME | `policy_dealer` |
| `policy_market_shadow` | fed funds futures snapshot | `policy_market_shadow` |
| `curve` | `DGS3MO`, `DGS2`, `DGS10`, `DGS30` | `curve` |
| `decomposition` | `DGS10`, `DFII10`, `T10YIE`, Cleveland model components | `decomposition_component` |
| `supply` | Treasury/FiscalData issuance | `supply` |
| `positioning` | CFTC TFF | `positioning` |
| `plumbing` | `WALCL`, `WRESBAL`, `RRPONTSYD`, `WTREGEN` | `plumbing` |

### 3.3 Slope is shape, not term premium

Curve steepness is reported as steepness. The words "term premium" appear only against
`real_term_premium_10y`, which comes from the Cleveland Fed's estimated model — a model output with
its own vintage and its own uncertainty, not a spread between two traded yields.

`nominal = real + breakeven` is an **identity** here, because FRED derives `T10YIE` from `DGS10` and
`DFII10`. Measured residual across two multi-month episodes: 0.0bp. The engine therefore records the
attribution (how much of a nominal move was real versus compensation) but raises
`decomposition_components_do_not_reconcile` **only** over the Cleveland model's explicit components,
where a residual is real information.

### 3.4 Contradictions

| rule | fires when |
|---|---|
| `policy_paths_disagree` | spread of **forward** path rates at a **common horizon** > 25bp. The actual path is excluded: it is where rates are, not where they are going, so including it measures curve slope rather than disagreement |
| `path_conflicts_with_actual` | a forward path implies the opposite direction to the actual regime |
| `decomposition_components_do_not_reconcile` | The Cleveland **modelled** 10y nominal differs from the **traded** `DGS10` by more than 85bp. Not the component sum — that is an identity (D7), measured at 0.0bp across 332 months |
| `supply_pressure_without_macro_confirmation` | new-issue coupon size at a strict multi-quarter high **and** the nominal 10y moved ≥ 25bp **and** inflation compensation moved < 10bp. Elevated is a new high against the previous four new issues rather than a percentage over a baseline: auction sizes step in increments Treasury chooses, so "higher than it has been all year" is a statement about the publisher's decisions rather than about a threshold we picked |

## 4. Confidence

Deterministic, and **never a function of signal magnitude**:

```text
confidence = clamp(0, 1,
    completeness x freshness x quality x (1 - revision_penalty) x (1 - contradiction_penalty))
```

| term | definition |
|---|---|
| `completeness` | load-bearing inputs present at `as_of` ÷ load-bearing inputs required |
| `freshness` | per input, 1.0 within its expected cadence, decaying linearly to 0 at 3x cadence; aggregated as the weighted minimum |
| `quality` | `valid` counts 1.0, `partial` counts 0.5, `invalid`/`quarantined` are excluded upstream |
| `revision_penalty` | share of load-bearing inputs whose value changed vintage since the prior state |
| `contradiction_penalty` | 0.15 per fired rule, capped at 0.60 |

Two hard rails:

- `completeness < 0.50` forces `state = INDETERMINATE` and `confidence ≤ 0.25`, whatever the
  surviving inputs say. **This is the defect being fixed**: `compute_composite_score` renormalises
  over surviving weight, so one populated group out of six yields a full-magnitude composite and a
  confident `BUY`/`SELL`.
- A missing input is never a neutral input. `_duration_stance(None)` returned `"NEUTRAL"`, rendering
  absence as a considered view; it now returns `UNKNOWN`, and so does any score standing on less
  than half the scorecard weight. See §4.1.

`confidence_reasons` records every term with its value and the inputs that drove it, so a number can
be argued with rather than merely believed.

**Per-domain load-bearing sets** (D6). Completeness is measured against the inputs the *state*
stands on, not against every factor the domain reports:

| domain | load-bearing | reported but not load-bearing |
|---|---|---|
| inflation | the eight realized/breadth/stickiness/survey series | market compensation (`T10YIE`, `T5YIFR`) |
| rates | the three official policy paths (actual, SEP, dealer) | the market shadow, curve, decomposition, supply, positioning, plumbing |

For rates this matters twice over. Missing supply data cannot make "the committee held in July"
unknowable, so it must not erase the state. And the market shadow is deliberately outside the
required set — counting it would let a third-party estimate stand in for an absent dealer survey and
report full coverage, which is the exact substitution this domain refuses.

### 4.1 The legacy scorecard

`RatesScorecard` keeps `composite_score` unchanged — it is the honest weighted mean of the groups
that reported — and gains `coverage`, the share of group weight actually scored. `duration_stance`
gains `UNKNOWN` and returns it whenever the score is absent **or** coverage sits below 0.50.

On today's feeds that is not hypothetical: three of six groups are hard-coded as missing until the
Phase 2 macro, supply and positioning feeds land, so coverage is **0.45** and the desk has been
printing a `BUY`/`SELL`/`NEUTRAL` built on 45% of its own weight. It now prints `UNKNOWN` with the
coverage stated, and the synthesis sentence beneath it stops narrating a lean the stance has already
refused.

## 5. Point-in-time semantics

An observation is eligible when `available_at <= as_of`, per the MC0 contract. For realized
inflation `available_at` is ALFRED's `realtime_start`, which the source probe verified is a subset of
the publisher's own release calendar with zero exceptions.

Vintages are why this is safe. January 2024 CPI reads 309.685 from 2024-02-13, 309.794 from
2025-02-12, and 309.698 from 2026-02-13. A replay at `as_of = 2024-06-01` must return **309.685**.
Reading today's value into a historical state is the backdating defect MC1 found twice in its own
layers; here the source prevents it structurally.

**Provenance is downgraded and says so.** FRED redistributes BLS and BEA data, so a realized
inflation observation carries `source_kind = first_party_publisher` and
`cost_class = free_publisher`, not `official`/`free_official`. The chain runs
`observation → FRED artifact → (BLS release, unreachable from this desk)`. The vintage record is
FRED's own first-party product — BLS publishes no vintages at all — which is what makes the
classification honest rather than merely convenient.

## 6. Missing data, and the case we already have

`state` abstains rather than interpolating. There is no forward-fill of a realized series across a
missing period and no substitution of a different series for an absent one.

This is not hypothetical: **October 2025 CPI does not exist.** `CPIAUCSL` runs 2025-09 (324.245) then
2025-11 (325.063), with no October row, because of the government shutdown. Any engine that
forward-fills produces a fabricated month; any engine that computes a 3-month change across the hole
without noticing produces a 2-month change labelled as 3. Scenario 6 pins both behaviours.

## 7. Golden scenarios

Six preregistered cases in `tests/fixtures/macro/inflation_rates_golden.json`. Every input value is
real, fetched at authoring time and frozen with its `available_at`; no value is invented.

**Rows 1 and 2 were corrected during authoring, before any engine existed.** The first draft predicted
`ABOVE_TARGET` with `stickiness_not_confirming_disinflation` for scenario 1; the measured anchor put
core PCE at 4.10 (above the 3.00 boundary) and sticky core down 0.83pp over the same window — it
confirmed the disinflation rather than contradicting it, and the real signature was a 1.13pp *level*
gap between headline and core. Scenario 2 then surfaced median CPI at +0.89 against trimmed mean at
−0.90, which no rule covered, and `breadth_measures_disagree` was added to cover it. Predictions are
allowed to lose to measurements taken before the thing being predicted is built; they are not allowed
to change afterwards.

Each realized-inflation scenario carries an `observation_history` block: the sixteen months of real
vintage-stamped observations ending at the target period, enough for a year-over-year at that period
and another three months earlier. It exists so the engine derives its own transforms rather than
being handed the answer — an engine given a year-over-year has not computed one. `available_at` there
is the true first-publication instant, recovered by reading the unbounded vintage history and
selecting the row in force at `as_of`; querying ALFRED with `realtime_start = realtime_end = as_of`
makes the publisher clamp every window to the query and report `as_of` for every row, which is an
artifact of asking rather than a fact about publishing.

| # | id | anchor | expected |
|---|---|---|---|
| 1 | `disinflation_with_sticky_services` | 2023-06 | `WELL_ABOVE_TARGET`/`FALLING`, `headline_core_divergence` fires, `stickiness_not_confirming_disinflation` **must not** |
| 2 | `broad_reacceleration` | 2022-01 | `WELL_ABOVE_TARGET`/`RISING`, `breadth_measures_disagree` fires, `breadth_contradicts_core` **must not** |
| 3 | `policy_paths_kept_separate` | 2026-08-18 | `ON_HOLD`/`RISING`, paths kept separate, `policy_paths_disagree` **must not** fire — measured spread is 7.5bp |
| 4 | `nominal_led_by_real_yields` | 2024-09-03 → 2025-01-31 | attribution real-led (+43 of +74bp), breakeven contribution stated, no term-premium claim |
| 5 | `supply_pressure_with_neutral_macro` | 2023-07-03 → 2023-11-30 | +41bp nominal with **−4bp** breakeven; 10y new-issue size 35B → 38B → 40B after four flat quarters, so `supply_pressure_without_macro_confirmation` fires and the inflation state is untouched |
| 6 | `stale_and_revised_realized_inflation` | 2025-10 absent; 2024-01 three vintages | abstains on the hole; replay at 2024-06-01 returns 309.685, not 309.698 |

## 8. Exit criteria this design must satisfy

- states replay under `available_at <= as_of`;
- exact observation FKs reconstruct every state;
- incomplete data abstains or degrades explicitly;
- policy paths never merge;
- slope is not presented as term premium;
- legacy stance is visibly experimental and cannot become confident from missing groups;
- real worker/database/API/browser path passes.
