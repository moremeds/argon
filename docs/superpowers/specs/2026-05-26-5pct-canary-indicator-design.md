# 5% Canary Indicator — Design

**Date:** 2026-05-26
**Status:** Approved for implementation planning (v0.3). Not yet approved for merge/ship.
**Surface:** New `/regime` sub-tab "5% Canary"; new Postgres table `uw_scan.canary_snapshots`; new backtest rows under existing `regime_backtest_runs` table
**Companion docs:**
- `docs/research/regime/cri-methodology.md` (prior art, mirrored structure)
- `docs/research/regime/vcg-methodology.md` (prior art, mirrored structure)
- `docs/research/regime/2023-thrasher-5pct-canary.pdf` (primary literature anchor)

## Revision history

- **v0.1 (2026-05-26)** — initial design after brainstorming
- **v0.3 (2026-05-26)** — second-pass review patches (5 implementation-detail fixes):
  - **Causal Confirmed Canary detection**: replace "look forward 42 days" wording with a sequential per-day state machine — a confirmation can only be emitted on the day the 2nd consecutive close-below-SMA-200 actually occurs, using only data ≤ D. Eliminates look-ahead risk.
  - **4-state Speed model**: explicit `CONFIRMED_ONLY` / `BTD_ONLY` / `BOTH_ACTIVE_AMBIGUOUS` / `NEUTRAL`. Both-active is capped at WATCH (was: collapsing into BTD via the original cap rule).
  - **Close-only `higher_closing_low`** definition replacing the ambiguous `spx_higher_low` (no OHLC data needed; matches the "no new data" project rule).
  - **Execution-lagged labels**: forward returns computed from D+1 close, not D close. Removes the ~17:30 ET signal-known-before-fill bias.
  - **DB CHECK constraints** for `score`, `band`, `warning_state`, `score_form` + **canonical payload hash** definition (sorted keys, decimal serialization) so `payload_hash` is reproducible.
  - **Minimum-event-count rule** in §8.6 — event-level gate marks `insufficient_events` rather than hard-failing when n is below threshold.
  - **Calibration wording softened** in §7.2 — "starting values" are explicitly illustrative priors, not a measured spot-check.
- **v0.2 (2026-05-26)** — incorporates P0 review fixes:
  - **OOS leakage fix:** form sweep now uses train / validation / final-test split (was: train / test only, with form chosen on the test window)
  - **Confirmed-Canary cap:** while Confirmed Canary is the only active speed event, composite is hard-capped at WATCH band (≤49). Cap-lift conditions explicit. Was: speed=0 with additive composite, which let vol tiers print STRONG BUY during a bearish warning
  - **VIX/VIX3M reframed:** scores *normalization-from-peak* rather than *raw backwardation level*, matching the rest of the indicator's "resolution-from-stress" framing
  - **Lookback corrected:** 350 *trading* rows / 500 calendar days requested (was: 350 calendar days, which is only ~250 trading rows)
  - **Threshold calibration formalized:** hard rule (p25 floor, p90 ceiling on train-window observations) replacing "adjust so the band distribution is sensible"
  - **Event de-duplication state machine** specified
  - **Validation report expanded** with band-level metrics, per-tier ablation, event-level evaluation, block bootstrap CIs
  - **Schema:** scalar columns for indexable queries + `warning_state` column
  - **Force-recompute mode** for warm-store corrections
  - **Test suite scaffolding** added (§19)

---

## 1. Problem

The existing **CRI** (Crash Risk Indicator) is structurally *coincident*. Per
`cri-methodology.md` §8: "VIX raw level alone captures most of the predictive
signal" — the indicator reliably reads `>30/100` only after equity stress is
already visible in spot. The existing **VCG** indicator carries the same
limitation: its own methodology doc admits "VCG is descriptive, not predictive
… SUPPRESSED days −5 through −1, BOUNCE day 0, RISK_OFF day +3."

Operationally, that means neither indicator tells the user *during* a stress
episode whether the bottom is in. The question the user actually faces — "VIX
is 30, should I be adding risk?" — is unanswered by current regime tooling.

This spec introduces a third regime indicator, the **5% Canary**, scoped to
predict *crash resolution* rather than crash onset. The score increases as
dip-buy conditions strengthen. Same data sources, same persistence pattern,
same backtest harness as CRI / VCG.

## 2. Goals

1. Score every trading day on a 0–100 scale of *favorability for adding equity
   risk*, with a clear band map (NONE / WATCH / BUY / STRONG BUY).
2. Emit a **separate `warning_state`** field that surfaces when Thrasher's
   bearish Confirmed Canary is active — independent of the additive composite.
   While bearish warning is active and no recovery condition has been met,
   the composite is hard-capped at WATCH band (≤49). The score and warning
   state are two outputs of one indicator, not collapsed into one number.
3. Compose the score from signals that have **published academic or
   long-sample empirical evidence** for predicting forward equity returns —
   not pattern-matching against single crash episodes.
4. Preserve the project's architectural patterns: clipped ramps where
   possible, snapshot table with scalar columns + JSONB payload,
   `composite_version` field, OOS gate in CI.
5. Reuse existing data sources (`uw_scan.vol_index_daily`) — zero new
   fetchers, zero new external API dependencies for v1.
6. Backtest-driven calibration: the scoring functional form is *chosen by the
   data*, not declared by the author. Strict train / validation / final-test
   separation prevents the form-selection AUC from leaking into the OOS
   report.

## 3. Non-goals

- **No changes to CRI or VCG.** The Thrasher signals are candidates to enrich
  CRI's predictive side later; that's a separate spec.
- **No new data sources.** Put/call ratios, gamma exposure, breadth, HYG
  cross-asset — all deferred to a v2.
- **No options-flow input.** Pure vol-complex + price-action only.
- **No trading-strategy translation.** The indicator outputs a regime score;
  it does *not* size positions or generate trade entries.
- **No CRI-style crash trigger.** The indicator is a gradient; no binary
  "fire / no-fire" boolean lives next to the score.

## 4. Literature anchors

Verified primary sources informing component selection:

| Signal | Primary citation |
|---|---|
| VIX-Spike-Reversion (tactical) | Whaley, R.E. (2000). "The Investor Fear Gauge." *Journal of Portfolio Management* 26(3): 12-17 |
| VIX/VIX3M Backwardation (tactical) | Macrosynergy (2023). "VIX term structure as a trading signal." `macrosynergy.com/research/vix-term-structure-as-a-trading-signal/` |
| Variance Risk Premium (structural) | Bollerslev, T., Tauchen, G., Zhou, H. (2009). "Expected Stock Returns and Variance Risk Premia." *Review of Financial Studies* 22(11): 4463-4492 |
| COR1M Peak-and-Decay (structural) | Driessen, J., Maenhout, P., Vilkov, G. (2009). "The Price of Correlation Risk." *Journal of Finance* 64(3): 1377-1406 |
| VVIX/VIX Recovery (structural) | CBOE (2012). *Double the Fun with CBOE's VVIX Index* whitepaper |
| Confirmed 5% Canary + Buy The Dip (speed) | Thrasher, A. (2023). *The 5% Canary*. NAAIM White Paper Contest. PDF preserved at `docs/research/regime/2023-thrasher-5pct-canary.pdf` |

Practitioner backtests cited inline in §6 where they inform a specific
calibration choice. The peer-reviewed citations carry interpretive weight; the
practitioner backtests carry magnitude estimates.

## 5. Architecture

```
src/uw_scan/
├── cards/
│   └── canary_scoring.py             # NEW — pure math: 6 signal scorers + composite
├── scanners/
│   └── canary.py                     # NEW — orchestrator (vol_index_daily → scoring → persist)
├── storage/
│   ├── canary_snapshot_repository.py # NEW — focused storage module (NOT extension of repository.py)
│   └── migrations/
│       └── 06X_canary_snapshots.sql  # NEW — table + indexes
├── worker/jobs/
│   └── regime_jobs.py                # EXTEND — add canary_scan alongside cri_scan / vcg_scan
└── api/routers/
    └── regime.py                     # EXTEND — add GET /api/regime/canary{,/history,/validation}

web/
├── app/regime/page.tsx               # EXTEND — add "5% Canary" sub-tab
└── components/regime/
    ├── CanarySubTab.tsx              # NEW
    ├── CanaryValidationPanel.tsx     # NEW
    └── primitives/
        └── RegimePill.tsx            # NEW — three-state pill for Speed tier

docs/research/regime/
└── canary-methodology.md             # NEW — source of truth, mirrors cri-methodology.md

scripts/
└── backtest_canary.py                # NEW — form-sweep backtest harness
```

### Data flow

```
vol_index_daily (parquet-lake-backed warm store)
     │
     ├── VIX, VVIX, VIX3M, COR1M, SPX
     │
     ▼
cards/canary_scoring.run_analysis()
     (pure numpy math; no IO; selectable score_form)
     │
     ▼
scanners/canary.run() ───persist───► uw_scan.canary_snapshots
                                     (JSONB payload, composite_version=1, score_form=<frozen>)
```

Read-only against `vol_index_daily`; no external API calls. Same data-source
discipline as `scanners/cri.py`.

## 6. The composite

Three orthogonal tiers totaling 100 points. The per-signal formulas in
§6.1–6.3 are written in their **linear form** for illustration; the actual
runtime form is chosen by the backtest sweep described in §7.3 and frozen as
`SCORE_FORM` in `cards/canary_scoring.py`.

```
┌────────────────────────────────────────────────────────────────────┐
│ TACTICAL VOL (0-30) — vol events, 3-10 day horizon                 │
│   VIX-Spike-Reversion          0-15                                │
│   VIX/VIX3M Backwardation      0-15                                │
├────────────────────────────────────────────────────────────────────┤
│ STRUCTURAL VOL (0-50) — vol state, 10-60 day horizon               │
│   Variance Risk Premium (VRP)  0-21                                │
│   COR1M Peak-and-Decay         0-17                                │
│   VVIX/VIX Recovery            0-12                                │
├────────────────────────────────────────────────────────────────────┤
│ PRICE SPEED (0-20) — Thrasher 2023 brachistochrone signal          │
│   Confirmed Canary active*     0                                   │
│   Neither active               8                                   │
│   Buy The Dip active*          20                                  │
└────────────────────────────────────────────────────────────────────┘
   * Active = signal fired within trailing 42 trading days.

   raw_score    = clip(tactical + structural + speed, 0, 100)
   canary_score = apply_warning_cap(raw_score, speed_state)
```

### Warning-cap rule (the Thrasher veto) — 4-state model

```python
# Inputs (from §6.3 event detection — all evaluated using only data ≤ today):
#   confirmed_canary_active : bool   # within last 42 trading days
#   buy_the_dip_active      : bool   # within last 42 trading days
#   spx_above_sma200_2d     : bool   # SPX closed above SMA-200 for 2 consecutive days
#   vix_term_normalized     : bool   # vix/vix3m < 1.00 today
#   higher_closing_low      : bool   # close-only definition (see below)

# Close-only "higher_closing_low" (no OHLC data needed):
#   prior_low_close  = min(spx_close[-20:-5])    # closing low of the prior 15-session window
#   recent_low_close = min(spx_close[-5:])       # closing low of the last 5 sessions
#   higher_closing_low = (
#       recent_low_close > prior_low_close
#       and spx_close_today > sma_200 * 0.98     # SPX within ~2% of SMA-200 or above
#   )

# Step 1: classify speed_state (4-state explicit model)
if confirmed_canary_active and buy_the_dip_active:
    speed_state = "BOTH_ACTIVE_AMBIGUOUS"
    speed_score = 8
elif confirmed_canary_active:
    speed_state = "CONFIRMED_CANARY_ACTIVE"
    speed_score = 0
elif buy_the_dip_active:
    speed_state = "BUY_THE_DIP_ACTIVE"
    speed_score = 20
else:
    speed_state = "NEUTRAL"
    speed_score = 8

# Step 2: cap-lift evaluation (only meaningful when CONFIRMED_CANARY_ACTIVE)
cap_lift_conditions = {
    "spx_above_sma200_2d": spx_above_sma200_2d,
    "vix_term_normalized_and_higher_closing_low": vix_term_normalized and higher_closing_low,
}
cap_cleared_early = any(cap_lift_conditions.values())

# Step 3: apply cap and emit warning_state
if speed_state == "CONFIRMED_CANARY_ACTIVE":
    if cap_cleared_early:
        canary_score = raw_score
        warning_state = "NONE"
        cap_applied = False
    else:
        canary_score = min(raw_score, 49)         # hard cap at top of WATCH band
        warning_state = "CONFIRMED_CANARY_ACTIVE"
        cap_applied = (raw_score > 49)
elif speed_state == "BOTH_ACTIVE_AMBIGUOUS":
    canary_score = min(raw_score, 49)             # ambiguous → cap to WATCH
    warning_state = "BOTH_ACTIVE_AMBIGUOUS"
    cap_applied = (raw_score > 49)
elif speed_state == "BUY_THE_DIP_ACTIVE":
    canary_score = raw_score
    warning_state = "BUY_THE_DIP_ACTIVE"
    cap_applied = False
else:  # NEUTRAL
    canary_score = raw_score
    warning_state = "NONE"
    cap_applied = False
```

**Why both-active is capped, not cleared**: when both events fire inside the
same 42-day window (rare but possible during whipsaw regimes — Mar 2020 had
both ingredients within weeks), the regime is genuinely ambiguous. Treating
ambiguity as bullish would silently override the bearish warning the
indicator is supposed to surface. WATCH band + `BOTH_ACTIVE_AMBIGUOUS`
badge is the honest representation.

**Cap auto-clears** when `confirmed_canary_active` returns False — the 42-day
activity window expiring from §6.3 — even if no cap-lift condition has
fired.

**Cap-lift conditions are evaluated daily, not "stuck"**. If
`spx_above_sma200_2d=True` on day D clears the cap, and then SPX falls back
below SMA-200 on day D+1, the cap re-engages on D+1. This is intentional —
the cap-lift is a *current-state* check, not a one-time event.

### Band map (mirrors CRI's 4-band model)

| Band | Range | Meaning |
|---|---|---|
| NONE | 0 ≤ score < 25 | No dip-buy setup |
| WATCH | 25 ≤ score < 50 | One tier firing; setup forming. Bearish-warning cap pins to ≤49 |
| BUY | 50 ≤ score < 75 | Multiple tiers firing; favorable add-risk window |
| STRONG BUY | 75 ≤ score ≤ 100 | All tiers firing; historically aligned with major bottoms |

`warning_state` is independent of `band` and is shown as a separate UI badge.
It can be `CONFIRMED_CANARY_ACTIVE` while the score is in any band ≤49.

### 6.1 Tactical Vol tier (0-30)

**VIX-Spike-Reversion (0-15)** — Whaley-derived

```
vix_peak_10d  = max(VIX[-10:])
spike_active  = (vix_peak_10d >= 30)
pullback_pct  = max(0, (vix_peak_10d - vix_today) / vix_peak_10d)
score = clip(pullback_pct / 0.30 * 15, 0, 15) if spike_active else 0
```

- Fires only when VIX peaked ≥ 30 in last 10 sessions.
- Saturates at 30 % retracement from that peak.

**VIX/VIX3M Backwardation-Normalizing (0-15)**

```
ratio_today    = vix_today / vix3m_today
ratio_peak_10d = max(vix/vix3m over last 10 sessions)
backwardation_was_extreme = (ratio_peak_10d >= 1.05)
normalization_pct = max(0, (ratio_peak_10d - ratio_today) / ratio_peak_10d)
score = clip((normalization_pct - 0.05) / (0.20 - 0.05) * 15, 0, 15) if backwardation_was_extreme else 0
```

- **Reframed (v0.2):** Original v0.1 design scored *raw backwardation level*,
  which is conceptually inconsistent with the rest of the indicator (every
  other signal scores resolution-from-a-stress-peak). Raw backwardation is
  often the panic event itself, not its resolution; v0.1 would have rewarded
  panic acceleration.
- v0.2 fires only when VIX/VIX3M was extreme (≥1.05) in the last 10 sessions,
  then scores the *retracement* of the ratio toward contango.
- Saturates at 20 % normalization from the peak ratio.
- The Macrosynergy backwardation-=-oversold framing is preserved through the
  gate (we still require an extreme backwardation to have occurred); the
  bullish score accrues during the *unwind* of that backwardation.

### 6.2 Structural Vol tier (0-50)

**Variance Risk Premium (0-21)** — Bollerslev/Tauchen/Zhou 2009

```
RV_20d = sqrt(252) * std(log_returns_spx[-20:]) * 100   # annualized vol, %
VRP    = VIX**2 - RV_20d**2                             # variance points
score  = clip((VRP - 50) / (300 - 50) * 21, 0, 21)
```

- Floor at VRP=50 prevents calm-day signal noise.
- Saturates at VRP=300 (empirically observed in 2008-Q4, 2020-Mar).

**COR1M Peak-and-Decay (0-17)** — Driessen-Maenhout-Vilkov framing

```
cor_peak_60d  = max(COR1M[-60:])
peak_elevated = (cor_peak_60d >= 60)
decay_pct     = max(0, (cor_peak_60d - cor1m_today) / cor_peak_60d)
score = clip(decay_pct / 0.30 * 17, 0, 17) if peak_elevated else 0
```

- Fires only when COR1M peaked ≥ 60 in last 60 sessions.
- Saturates at 30 % decay from peak.
- The 60 threshold matches CRI's crash-trigger threshold for consistency.

**VVIX/VIX Recovery (0-12)**

```
vvr_today    = vvix_today / vix_today
vvr_min_60d  = min(vvix/vix over last 60)
compressed   = (vvr_min_60d <= 4.0)
score = clip((vvr_today - 3.5) / (5.0 - 3.5) * 12, 0, 12) if compressed else 0
```

- Fires only when ratio compressed below 4.0 in last 60 sessions.
- Saturates at ratio recovery to 5.0.
- Lowest weight: practitioner-only evidence base.

### 6.3 Price Speed tier (0-20) — Thrasher 2023

The Speed tier scores by translating Thrasher's two discrete events
(Confirmed 5% Canary, Buy The Dip) into a three-state daily score. The two
events are defined exactly as in the paper; the daily-score translation is
ours.

**Event definitions (verbatim Thrasher):**

- **5% Canary event** fires on the first close where SPX closes ≤ 95 % of its
  trailing 252-day high *and* the count of trading days from that 252-day
  high to today is ≤ 15.
- **Confirmed 5% Canary event** fires on the day SPX prints its second
  consecutive close below the 200-day SMA, when that second close falls
  within 42 trading days *after* a 5% Canary event.
- **Buy The Dip event** fires on the first close where SPX closes ≤ 95 % of
  its trailing 252-day high, the count of trading days from that high is >
  15, *and* the 50-day SMA is above the 200-day SMA on that same close.

**Daily score derivation (depends on the 4-state model in §6 cap-rule):**

The `speed_score` value (0 / 8 / 20) and the `speed_state` label
(`CONFIRMED_CANARY_ACTIVE` / `BUY_THE_DIP_ACTIVE` / `BOTH_ACTIVE_AMBIGUOUS`
/ `NEUTRAL`) are computed by the cap-rule block in §6 (the 4-state model).
Refer to §6 for the per-state mapping; this section defines only the
underlying `canary_active` / `btd_active` flags those derive from.

**Why 42 trading days for the activity window:** Thrasher reports his
edge-magnitude tables at the 42-day-after-signal horizon (Table 2), with peak
median gain at exactly that horizon. Our activity window matches that
empirical horizon — after 42 trading days the signal's published edge has
been realized.

**Both-active is a real regime, not an oddity:** Confirmed Canary and Buy
The Dip are mutually-exclusive *at fire time* (they require disjoint
`days_to_5pct` counts: ≤15 vs >15), but they can both be "active" within
the same trailing 42-day window when two distinct events occur — e.g., a
fast decline fires the Canary, then a subsequent slower decline within 42
days fires Buy The Dip against the same anchor or a new anchor. v0.3
elevates this to a first-class state (`BOTH_ACTIVE_AMBIGUOUS`) rather than
silently collapsing into one branch. The cap rule in §6 caps the composite
in this state.

**All Speed tier thresholds (5 %, 15 days, 42 days, 50-day SMA, 200-day SMA)
are frozen verbatim from Thrasher 2023 and never subject to calibration.**
This is the indicator's single strongest evidence-anchored signal; we do not
re-tune Thrasher's published parameters against our own backtest.

### Causal event detection state machine

All three events (`5pct_canary`, `buy_the_dip`, `confirmed_canary`) use a
sequential per-day state machine. **No event may be emitted using data
strictly after its fire date.** Production daily scorer and historical
backtest run the *identical* loop so backtest results cannot diverge from
production behaviour.

```python
# Per-day state (persisted in the snapshot payload as an opaque dict
# under speed.anchor for replay/audit):
#   last_high_date          : date of the most recent 252d closing high
#   last_high_value         : float — that close's value (the anchor)
#   canary_fired_for_high   : bool  — a 5pct_canary already fired against this anchor
#   btd_fired_for_high      : bool  — a buy_the_dip   already fired against this anchor
#   open_canary_windows     : list[dict] — each entry tracks one open Confirmed-Canary
#                             confirmation window:
#                               {
#                                 "canary_fire_date": date,
#                                 "expires_after":   date (canary_fire_date + 42 td),
#                                 "consec_below_sma200": int   # 0, 1, or 2
#                               }

# At each new daily scan for date D, using ONLY data with date ≤ D:

# Step 1 — anchor update
new_high_today = (spx_close[D] >= max(spx_close[D-251:D+1]))
if new_high_today:
    last_high_date        = D
    last_high_value       = spx_close[D]
    canary_fired_for_high = False
    btd_fired_for_high    = False

# Step 2 — primary-event detection (5pct_canary OR buy_the_dip)
days_since_high   = trading_days_between(last_high_date, D)
five_pct_breach   = (spx_close[D] <= 0.95 * last_high_value)

if five_pct_breach:
    if days_since_high <= 15 and not canary_fired_for_high:
        emit("5pct_canary", fire_date=D)
        canary_fired_for_high = True
        open_canary_windows.append({
            "canary_fire_date":    D,
            "expires_after":       D + 42_trading_days,
            "consec_below_sma200": 0,
        })
    elif days_since_high > 15 and not btd_fired_for_high and (sma_50[D] > sma_200[D]):
        emit("buy_the_dip", fire_date=D)
        btd_fired_for_high = True

# Step 3 — Confirmed Canary detection (causal — fires ONLY on the day the
# 2nd consecutive close-below-SMA-200 actually happens, inside an open window)
below_sma200_today = (spx_close[D] < sma_200[D])

for window in list(open_canary_windows):
    if D > window["expires_after"]:
        open_canary_windows.remove(window)
        continue

    if below_sma200_today:
        window["consec_below_sma200"] += 1
    else:
        window["consec_below_sma200"] = 0       # reset on any close at/above SMA-200

    if window["consec_below_sma200"] >= 2:
        emit("confirmed_canary", fire_date=D)
        open_canary_windows.remove(window)      # window is consumed on confirmation

# Step 4 — "active" flags for today's score (42-day trailing window from fire day)
canary_active = any(confirmed_canary fire_date in (D-42_td, D])
btd_active    = any(buy_the_dip      fire_date in (D-42_td, D])
```

**Causality requirement (the look-ahead-free contract):**

> For any backtest row at date D, the values of `canary_active`,
> `btd_active`, and `warning_state` must be computable using only the rows
> with date ≤ D. No backtest implementation may "forward-fill" a Confirmed
> Canary onto its underlying 5% Canary's fire day. The state machine above
> is the canonical, production-shipping implementation; backtests run the
> same loop against historical data.

A unit test (`test_canary_causality.py`, §19) enforces this by feeding
truncated histories `data[:K]` for each `K` and asserting the snapshot at
date `data[K-1]` is byte-identical to the K-th snapshot of a full
end-to-end run.

**Why one-event-per-anchor**: without the anchor-locking rule, a long
drawdown with choppy bottoming behaviour could re-fire `5pct_canary` every
day SPX re-breached the same anchor's 95 % level, inflating the "active"
window artificially. The anchor-reset rule mirrors how Thrasher's chart
(Figure 5) treats each 5 %-decline-from-a-52-week-high as one distinct dot.

**Why windows are *consumed* on confirmation**: once a Confirmed Canary
fires inside an open window, that window is removed so a third
close-below-SMA-200 inside the same 42-day post-Canary period does not
re-fire a duplicate Confirmed Canary. Each `5pct_canary` event can give
rise to at most one `confirmed_canary` event.

**Reset behaviour**: primary events lock to their anchor. A new 252-day
closing high resets both `canary_fired_for_high` and `btd_fired_for_high`
flags so a subsequent decline against the *new* high can fire fresh events.

## 7. Calibration

### 7.1 Class A — frozen thresholds (never tuned)

| Threshold | Source |
|---|---|
| Speed tier — all parameters | Thrasher 2023 verbatim |
| VIX spike-active threshold = 30 | Whaley framework |
| VIX/VIX3M backwardation midpoint = 1.0 | Definitional |
| COR1M peak-qualifying threshold = 60 | Matches CRI crash trigger |

### 7.2 Class B — empirically calibrated (hard rule)

Each smooth-signal threshold is set by the following procedure on the **train
window** (§7.3 — 2007-2014). The same procedure runs once at calibration
time, persisted to `docs/research/regime/canary-calibration-v1.json`, and
never changes during the form sweep.

```
For each smooth signal:
  - floor   = train-window p25 of the signal's value during its
              positive-condition observations (i.e., days when the signal's
              gate is satisfied)
  - ceiling = train-window p90 of the same observations
  - No author override unless documented in canary-calibration-v1.json with:
      - reason (one paragraph)
      - empirical evidence (data table or histogram)
      - reviewer signoff
```

**Starting values — illustrative priors only.** These are *not* measured
percentiles from `vol_index_daily`; they are the v0.1 starting points
preserved here as illustrative anchors for reviewers. Final values are
generated by `scripts/backtest_canary.py --calibrate` and committed in
`canary-calibration-v1.json`. Any deviation from the rule in §7.2 (above)
must appear as an entry in the JSON's `author_overrides` array with reason
and reviewer signoff.

| Signal | Gate condition (positive obs) | Floor (~p25) | Ceiling (~p90) |
|---|---|---|---|
| VIX-Spike pullback | `spike_active` (vix_peak_10d ≥ 30) | 0.05 retracement | 0.30 retracement |
| VIX/VIX3M normalization | `backwardation_was_extreme` (ratio_peak_10d ≥ 1.05) | 0.05 normalization | 0.20 normalization |
| VRP (variance points) | always (no gate) | 50 | 300 |
| COR1M decay | `peak_elevated` (cor_peak_60d ≥ 60) | 0.05 decay | 0.30 decay |
| VVIX/VIX recovery | `compressed` (vvr_min_60d ≤ 4.0) | 3.5 (ratio) | 5.0 (ratio) |

The calibration script (`scripts/backtest_canary.py --calibrate`) writes the
final values into `canary-calibration-v1.json` along with the train-window
band distribution it produced. A v2 calibration would generate
`canary-calibration-v2.json` alongside a `composite_version` bump — old
files stay for audit.

### 7.3 Three-window split + functional-form sweep

**The crucial OOS hygiene fix (v0.2):** the form selection AUC and the final
report AUC are measured on *different* windows. Without this split, the
"OOS" report leaks because we picked the form on the same data we report.

**Windows:**

| Window | Range | Purpose |
|---|---|---|
| **Train** | 2007-01-01 → 2014-12-31 (~8 years) | Compute calibration floors/ceilings (§7.2). Touched once. |
| **Validation** | 2015-01-01 → 2019-12-31 (~5 years) | Sweep four scoring forms; pick the winner by AUC. Touched once at form selection. |
| **Final test** | 2020-01-01 → present (~6+ years incl. COVID + 2022 bear) | The OOS gate. Never touched until form is locked. |

**Form sweep:**

Four forms applied uniformly across all five smooth signals (Speed tier is
exempt — its 3-state structure has no continuous form):

| Form | Math |
|---|---|
| linear | `M × clip((x-f)/(c-f), 0, 1)` |
| convex | `M × clip(((x-f)/(c-f))^1.5, 0, 1)` |
| concave | `M × clip(((x-f)/(c-f))^0.5, 0, 1)` |
| sigmoid | `M / (1 + exp(-10 × (norm - 0.5)))` |

**Fairness constraints:**
- Each form uses the *same* floor/ceiling per signal (from train-window
  calibration).
- No per-form parameter tuning (no sweeping `p ∈ {1.2, 1.5, 2.0}`).
- Each form applied uniformly across all five smooth signals.

**Selection procedure:**

```
1. CALIBRATE   on train window 2007-2014  → floors/ceilings → canary-calibration-v1.json
2. SWEEP       on validation 2015-2019     → AUC table per form per label
3. SELECT      form that beats `linear` AUC by ≥ 0.02 on ≥ 2 of 3 labels
   - tie / no winner → default to `linear` (Occam + project precedent)
4. FREEZE      winner into SCORE_FORM constant in cards/canary_scoring.py
5. REPORT      final OOS AUC on the test window 2020-present.
               This is the AUC that ships to the OOS gate.
6. LOCKED      after v1 publish, none of these windows are re-touched
               without bumping composite_version.
```

The losing forms' AUC tables stay in `regime_backtest_runs` for transparency
and for future v2 hypothesis comparison, but only the winner's row carries
`summary.is_winning_form=true`.

**Walk-forward roll forward (annual)**: after one year of post-publish data
accrues, we re-run step 5 only — the final test window grows, but train and
validation are frozen at v1's boundaries. A new train/validation re-fit
requires a v2 composite_version bump and a new spec.

## 8. Validation

### 8.1 Labels and the entry-on-next-close convention

The scanner runs at 17:30 ET — *after* market close on day D. The user
cannot fill at the D close. **All forward-return labels are computed
relative to the next trading day's close** (`entry_date = D+1`), not D
itself. This removes the silent execution-lag bias that would inflate AUC
by ~0.01-0.02 if labels were `close[D+h] / close[D] - 1`.

Convention:
```
signal_date = D                                  # the row the score lives on
entry_date  = next_trading_day_after(D)          # D+1 (typically the next business day)
forward_return(h) = spx_close[entry_date + h_td] / spx_close[entry_date] - 1
```

Daily-level binary labels (using the entry-on-next-close convention):

| Label | Definition |
|---|---|
| `up5d_2pct` | `forward_return(5) ≥ 0.02` |
| `up20d_5pct` | `forward_return(20) ≥ 0.05` |
| `up60d_10pct` | `forward_return(60) ≥ 0.10` |

**Plus** event-level labels (one observation per event, prevents overlap-inflation).
Event-level labels also use entry-on-next-close after the event's fire date:

| Event-level label | Definition |
|---|---|
| `fwd_42d_max_drawup` | `max(spx_close[entry+1 : entry+43]) / spx_close[entry] - 1` |
| `fwd_42d_max_drawdown` | `min(spx_close[entry+1 : entry+43]) / spx_close[entry] - 1` |
| `lower_low_30d` | Any close in `[entry+1 : entry+31]` is below `spx_close[entry]` |
| `recovery_60d` | `spx_close` makes a new 252d closing high within `[entry+1 : entry+61]` |

The event-level labels apply to **Buy The Dip events** specifically (the
indicator's bullish-side claim). Confirmed Canary events get the symmetric
bearish event-level table in §8.3.

### 8.2 Three-window split (see §7.3)

Calibration on train (2007-2014), form selection on validation (2015-2019),
final OOS reporting on test (2020-present). All metrics in §8.3 are computed
**on the test window only** for the final report.

### 8.3 Validation report contents

`scripts/backtest_canary.py --write-summary` produces a markdown report and
persists the structured data to `regime_backtest_runs`. The report and
`/api/regime/canary/validation` endpoint include:

**Daily-row metrics (composite and ablation):**
1. Composite AUC by label (3 labels × 1 form = 3 numbers)
2. **Speed-only AUC** by label (ablation — speed tier alone)
3. **Vol-only AUC** by label (ablation — tactical + structural, no speed)
4. **Composite minus Speed-only delta** by label (the marginal value of the vol tiers)

**Band-level metrics:**
5. Band distribution on the test window (count of NONE / WATCH / BUY / STRONG BUY days)
6. Forward 20d return mean + median, by band, vs unconditional 20d
7. **Max adverse excursion (MAE)** mean + median, by band (the "did I eat a leg down" metric)
8. **Hit rate vs unconditional** — fraction of days in each band where `up20d_5pct=1`, minus the unconditional rate on the test window

**Event-level metrics (Buy The Dip events):**
9. Number of unique BTD events on the test window
10. Median `fwd_42d_max_drawup` per event
11. Median `fwd_42d_max_drawdown` per event (the "MAE per event" metric)
12. Fraction of events with `lower_low_30d=1` ("bull-trap rate")
13. Fraction of events with `recovery_60d=1` ("real bottom rate")
14. **Block bootstrap 95% CIs** on each event-level statistic, using
    12-month blocks to handle overlapping-observation autocorrelation

**Event-level metrics (Confirmed Canary events, for the bearish side):**
15. Number of unique Confirmed Canary events on the test window
16. Median `fwd_42d_max_drawdown` per event (validates the bearish-warning claim)
17. Fraction of events followed by a >5% additional drawdown in 60d

**Warning-state metrics:**
18. Fraction of test-window days with `warning_state = CONFIRMED_CANARY_ACTIVE`
19. SPX forward 20d return mean during warning vs non-warning days
20. Number of days the cap was binding (raw_score ≥ 50 but capped to 49)

### 8.4 Persistence

Backtest results land in the existing `uw_scan.regime_backtest_runs` +
`uw_scan.regime_backtest_daily` tables (migration 057), with `indicator` set
to `'canary'`. Each form-sweep run inserts one row per form; the winning
form's row carries `summary.is_winning_form=true`. Event-level statistics
land in `summary.events` as structured JSON.

### 8.5 OOS gate

`tests/integration/regime/test_canary_oos_gate.py` reads the latest
`is_winning_form=true` run at the current `composite_version` and asserts:

- AUC `up5d_2pct` ≥ `LAST_KNOWN_AUC_UP5D_2PCT - 0.02`
- AUC `up20d_5pct` ≥ `LAST_KNOWN_AUC_UP20D_5PCT - 0.02`
- AUC `up60d_10pct` ≥ `LAST_KNOWN_AUC_UP60D_10PCT - 0.02`
- **Event-level**: median BTD `fwd_42d_max_drawup` ≥ `LAST_KNOWN_BTD_DRAWUP - 0.01`

`LAST_KNOWN_*` constants are set in the v1 publish PR and updated in lockstep
with any future `composite_version` bump.

### 8.6 Acceptance bar for v1 to ship

All of:

- AUC > 0.55 on at least 2 of 3 daily labels
- AUC `up60d_10pct` > 0.58 (BTZ-anchored — the structural tier should be
  strongest at the BTZ paper's published quarterly horizon)
- **Event-level BTD median `fwd_42d_max_drawup` ≥ 3.0 %** (sanity check
  against Thrasher's published 5.55 % median — we allow some degradation
  from his sample window but require the directional claim to hold)
- **Event-level BTD `lower_low_30d` rate ≤ 35 %** (bull-trap rate sanity check)
- **Event-level Confirmed Canary median `fwd_42d_max_drawdown` ≥ 4 % deeper
  than unconditional** (sanity check on the bearish-warning side; this is
  what justifies the cap)
- **Block-bootstrap 95% CI on the BTD `fwd_42d_max_drawup` median is
  strictly positive** (event-level statistical significance, not just
  daily-row AUC), **conditional on the minimum-event-count rule below**

If any bar is not met, the indicator goes back to design before merging.

### 8.7 Minimum-event-count rule

Buy The Dip and Confirmed Canary are sparse events — Thrasher reports 15
Confirmed Canaries and ~50 BTDs on SPX 1980-2022. Our test window
(2020-present) is only ~6 years, so the event count can be 0-3 for either
type at v1-publish time.

To avoid hard-failing the event-level gate on small-n, the acceptance bar
adapts:

```
N_btd_test     = count of Buy The Dip events on test window 2020-present
N_canary_test  = count of Confirmed Canary events on test window

if N_btd_test < 3:
    btd_event_gate = "insufficient_events_skipped"
    # The daily-AUC bars (8.6 first four bullets) must still pass.
    # The event-level BTD gate is informational only.
else:
    btd_event_gate = (
        median(btd_fwd_42d_max_drawup) >= 0.03
        and (btd_lower_low_30d_rate <= 0.35)
        and (block_bootstrap_95ci_low(btd_fwd_42d_max_drawup) > 0)
    )

# Symmetric for Confirmed Canary:
if N_canary_test < 3:
    canary_event_gate = "insufficient_events_skipped"
else:
    canary_event_gate = (
        median(canary_fwd_42d_max_drawdown) <= unconditional_median_drawdown - 0.04
    )
```

When either gate is marked `insufficient_events_skipped`, the validation
report includes an **expanded "long-sample event report"** that runs the
same event-level metrics against the *whole* available history (train +
validation + test) — for context only, not for the OOS gate. The
long-sample numbers are clearly labeled as in-sample-contaminated and never
used to justify shipping.

Rationale: a hard fail on n<3 conflates "indicator is bad" with "we lived
through a calm half-decade." The gate stays informative for the cases it
can decide and stays honest about the cases it cannot.

## 9. Persistence schema

```sql
-- migrations/06X_canary_snapshots.sql (idempotent — IF NOT EXISTS)
CREATE TABLE IF NOT EXISTS uw_scan.canary_snapshots (
    id                BIGSERIAL PRIMARY KEY,
    data_date         DATE NOT NULL,
    composite_version SMALLINT NOT NULL DEFAULT 1,
    score_form        TEXT NOT NULL,            -- 'linear' | 'convex' | 'concave' | 'sigmoid'

    -- v0.2: scalar columns for indexable queries (history charts, validation lookups,
    -- recent-best-score queries) — JSONB column retains the full structured payload.
    score             NUMERIC(5,2) NOT NULL,    -- 0.00-100.00 (post-cap)
    raw_score         NUMERIC(5,2) NOT NULL,    -- pre-cap composite (for debugging the cap)
    band              TEXT NOT NULL,            -- 'NONE' | 'WATCH' | 'BUY' | 'STRONG_BUY'
    tactical_score    NUMERIC(5,2) NOT NULL,    -- 0.00-30.00
    structural_score  NUMERIC(5,2) NOT NULL,    -- 0.00-50.00
    speed_score       SMALLINT     NOT NULL,    -- 0, 8, 20
    warning_state     TEXT NOT NULL,            -- 'NONE' | 'CONFIRMED_CANARY_ACTIVE' | 'BUY_THE_DIP_ACTIVE'

    payload           JSONB NOT NULL,           -- full structured payload (see §9.1)
    payload_hash      TEXT NOT NULL,            -- sha256 of payload, for force-recompute audit
    inserted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS canary_snapshots_date_version_idx
    ON uw_scan.canary_snapshots (data_date, composite_version);

CREATE INDEX IF NOT EXISTS canary_snapshots_version_date_desc_idx
    ON uw_scan.canary_snapshots (composite_version, data_date DESC);

CREATE INDEX IF NOT EXISTS canary_snapshots_inserted_idx
    ON uw_scan.canary_snapshots (inserted_at DESC);

CREATE INDEX IF NOT EXISTS canary_snapshots_warning_idx
    ON uw_scan.canary_snapshots (warning_state, data_date DESC)
    WHERE warning_state != 'NONE';

-- v0.3: CHECK constraints to keep scalar columns honest (idempotent)
ALTER TABLE uw_scan.canary_snapshots
    ADD CONSTRAINT IF NOT EXISTS canary_score_range_chk
    CHECK (score >= 0 AND score <= 100 AND raw_score >= 0 AND raw_score <= 100);

ALTER TABLE uw_scan.canary_snapshots
    ADD CONSTRAINT IF NOT EXISTS canary_band_chk
    CHECK (band IN ('NONE', 'WATCH', 'BUY', 'STRONG_BUY'));

ALTER TABLE uw_scan.canary_snapshots
    ADD CONSTRAINT IF NOT EXISTS canary_warning_state_chk
    CHECK (warning_state IN (
        'NONE',
        'CONFIRMED_CANARY_ACTIVE',
        'BUY_THE_DIP_ACTIVE',
        'BOTH_ACTIVE_AMBIGUOUS'
    ));

ALTER TABLE uw_scan.canary_snapshots
    ADD CONSTRAINT IF NOT EXISTS canary_score_form_chk
    CHECK (score_form IN ('linear', 'convex', 'concave', 'sigmoid'));

ALTER TABLE uw_scan.canary_snapshots
    ADD CONSTRAINT IF NOT EXISTS canary_tier_scores_chk
    CHECK (
        tactical_score   BETWEEN 0 AND 30
        AND structural_score BETWEEN 0 AND 50
        AND speed_score      IN (0, 8, 20)
    );
```

**Note on `ADD CONSTRAINT IF NOT EXISTS`:** PostgreSQL 9.6+ supports this
syntax. If the project's Postgres version is older, fall back to a
DO $$ BEGIN ... EXCEPTION WHEN duplicate_object THEN NULL; END $$;
wrapper. Verify against the project's Postgres minimum-supported version
in the implementation plan.

### 9.0a Canonical `payload_hash` definition

`payload_hash` must be reproducible across processes, machines, and Python
versions so that the no-op-on-replay guarantee works across worker
restarts and force-recompute audits.

```python
import hashlib
import json
from decimal import Decimal

def _canonical_default(obj):
    if isinstance(obj, Decimal):
        # 6 decimal places is sufficient resolution for any scalar we serialize;
        # this prevents float-vs-Decimal repr drift between runs.
        return format(obj, ".6f")
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def canonical_payload_hash(payload: dict) -> str:
    """SHA-256 of the payload with deterministic key ordering and no
    whitespace. The ``_prior`` audit field (if present) is excluded so a
    force-recompute can detect identical-content rewrites."""
    pruned = {k: v for k, v in payload.items() if k != "_prior"}
    encoded = json.dumps(
        pruned,
        sort_keys=True,
        separators=(",", ":"),
        default=_canonical_default,
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

The same function is used by:
- `scanners/canary.py` at insert time
- `--force-recompute` to detect identical-content rewrites
- The OOS replay test (`test_canary_causality.py`) to assert byte-identity

A unit test pins the hash of a known-good payload fixture so any future
serialization-format change breaks loudly.

### 9.1 Payload shape

```json
{
  "date": "2026-05-26",
  "canary": {
    "score": 47.3,
    "raw_score": 47.3,
    "band": "WATCH",
    "warning_state": "NONE",
    "composite_version": 1,
    "score_form": "linear",
    "cap_applied": false,
    "cap_lift_conditions": {
      "spx_above_sma200_2d": true,
      "vix_term_normalized": true,
      "spx_higher_low": true
    }
  },
  "tactical_vol": {
    "score": 12.4,
    "vix_spike_revert": { "score": 8.1, "spike_active": true, "pullback_pct": 0.16, "vix_peak_10d": 31.2 },
    "vix_vix3m_back":   { "score": 4.3, "backwardation_was_extreme": true, "ratio_peak_10d": 1.07, "ratio_today": 1.01, "normalization_pct": 0.056 }
  },
  "structural_vol": {
    "score": 26.9,
    "vrp":               { "score": 13.2, "vrp": 187.4, "vix2": 412.0, "rv2_20d": 224.6 },
    "cor1m_decay":       { "score": 9.7, "peak_60d": 68, "current": 54, "decay_pct": 0.206 },
    "vvix_vix_recovery": { "score": 4.0, "current": 4.1, "min_60d": 3.6 }
  },
  "speed": {
    "score": 8,
    "state": "neutral",
    "confirmed_canary_active": false,
    "buy_the_dip_active": false,
    "last_canary_fire_date": null,
    "last_btd_fire_date": null,
    "days_since_high_to_5pct": null,
    "sma50_above_sma200": true,
    "anchor": { "high_252d_date": "2026-04-12", "high_252d_value": 5187.4, "canary_fired_for_high": false, "btd_fired_for_high": false }
  },
  "inputs": {
    "vix": 22.3, "vvix": 92.1, "vix3m": 22.1, "cor1m": 54.0, "spx_close": 5023.4, "sma_50": 5040.1, "sma_200": 4870.3
  }
}
```

## 10. API surface

```
GET /api/regime/canary
    200 → latest snapshot payload + UI reference markers (matches CRI shape)
    503 → no snapshot exists at current composite_version

GET /api/regime/canary/history?days=30
    200 → { rows: [{ date, score, band, tactical_vol, structural_vol, speed }, ...] }

GET /api/regime/canary/validation
    200 → latest is_winning_form=true row from regime_backtest_runs for indicator='canary'
    503 → no completed run exists at current composite_version
```

Routes added to `src/uw_scan/api/routers/regime.py`; no new router module.

## 11. Worker schedule

Add `canary_scan` to `worker/jobs/regime_jobs.py`. Scheduler call in
`src/uw_scan/worker/scheduler.py`:

```
Every weekday at 17:30 ET (after market close + 90 min for warm-store rollup):
    1. vol_index_daily nightly rollup        [existing]
    2. cri_scan(conn)                        [existing]
    3. vcg_scan(conn)                        [existing]
    4. canary_scan(conn)                     [NEW]
```

Same lock pattern, same error handling, same idempotency guarantees as
CRI/VCG.

**Idempotency and force-recompute (v0.2):**

- **Default mode**: re-running on the same `(data_date, composite_version)`
  is a no-op (unique index protects). This is the normal worker behaviour.
- **`--force-recompute` mode**: overwrites the existing row for the given
  date/version. The previous row's `payload` and `payload_hash` are
  preserved in the new row's `payload._prior` for audit. Required when
  upstream `vol_index_daily` data is corrected (e.g., a delayed COR1M
  publish, an SPX close fix). Logs at WARNING level. Available via
  `scripts/backtest_canary.py --recompute-date YYYY-MM-DD` for ad-hoc
  invocations.

Lookback per scan: **350 trading rows** (not calendar days). The scanner
requests 500 calendar days from `vol_index_daily` and asserts at least 350
valid aligned trading rows after the inner-join across VIX / VVIX / VIX3M /
COR1M / SPX. If fewer than 350 aligned trading rows are available (boundary
case at the start of the series), the scan logs `canary_scan_skipped_thin_data`
and returns None — same pattern as `scanners/cri.py`.

## 12. Web UI

```
web/app/regime/page.tsx
    SubTabs: [CRI] [VCG] [5% Canary] [Validation]
                       └─── CanarySubTab.tsx
                            ├─ ScoreHero          (large 0-100 dial, band label)
                            ├─ TierStrips × 3
                            │   ├─ Tactical Vol     — 2 ComponentBars
                            │   ├─ Structural Vol   — 3 ComponentBars
                            │   └─ Price Speed      — 1 RegimePill (three states)
                            ├─ HistoryChart       (30/90/365d toggle)
                            └─ ValidationLink → CanaryValidationPanel.tsx
```

Reuses `web/components/regime/primitives/ComponentBar.tsx` and `HistoryChart.tsx`.
**One new primitive** required: `RegimePill.tsx` for the Speed tier (three-state
pill — Confirmed Canary / Neutral / Buy The Dip — does not fit a 0-25 bar
shape).

Generated TS types refresh: `cd web && npm run gen:types` after the API change.

## 13. CLI

```bash
# Run all four forms, persist each to regime_backtest_runs, write summary
uv run python scripts/backtest_canary.py --form-sweep --write-summary

# Single-form re-run (debugging / v2 hypotheses)
uv run python scripts/backtest_canary.py --form linear

# Render the latest persisted run as markdown
uv run python -m uw_scan.reports.regime_backtest_report --indicator canary --latest
```

## 14. Lookback budget

| Use | Trading days required |
|---|---|
| 52-week rolling high | 252 |
| SMA-200 | 200 |
| Post-canary confirmation window | 42 |
| COR1M peak window | 60 |
| Realized vol | 20 |
| **Worst case** | **252 + 42 = 294 trading days** |
| **Scanner MIN_ALIGNED_BARS** | **350 trading rows** (slack of 56) |
| **Calendar days requested from vol_index_daily** | **500** (covers worst-case holiday/weekend density) |

**v0.2 fix:** v0.1 specified "350 calendar days" which is only ~250 trading
days — under-spec'd for the 294-trading-day floor. v0.2 uses trading-row
counts and requests enough calendar days that the inner-join across the
five vol-complex series produces ≥350 trading rows even in the
boundary-case (early-2007 thin VVIX data, holiday-heavy windows).

First valid snapshot lands once 350 aligned trading rows are available —
practically ~Q1 2007 once VVIX has accumulated enough history.

## 15. What we deliberately do NOT add

- No new `vol_index_daily` columns. Realized vol computed on-the-fly.
- No new fetchers. All inputs already nightly-rolled to `vol_index_daily`.
- No CRI changes. Cross-pollination of Thrasher signals into CRI is a
  separate spec.
- No options-flow inputs (P/C ratio, gamma, breadth).
- No new backtest tables. Reuse `regime_backtest_runs` with `indicator='canary'`.
- No PCA-fitted or regression-fitted weights. Differentiated weights are set
  by evidence-tier, not by walk-forward regression on returns.
- No real-time intraday scoring. Once-daily after market close, like CRI/VCG.

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Speed tier dominates AUC, vol tiers add noise | §8.3 publishes per-tier AUC ablation (composite / speed-only / vol-only / delta). If Speed alone ≥ composite within 0.01 AUC across all labels, document and reconsider tier weights in v2 |
| Calm-day floor too high (false BUY readings) | Conditional gates on four of five vol signals + Speed=8 neutral keep calm-day floor at ~10-15. Backtest band-distribution metric (§8.3 #5) verifies. |
| Confirmed Canary suppressed by additive vol scores | **Hard cap at WATCH (≤49) while bearish-warning active and no cap-lift condition fires** (§6 cap rule). Backtest acceptance bar (§8.6) requires Confirmed Canary days to show measurably worse forward drawdowns vs unconditional — if not, the cap isn't doing its job. |
| Form-sweep leaks into OOS report | **Three-window split** (§7.3): calibrate on train, select form on validation, report on test — only the test window data are reported. |
| Form-sweep overfits despite split | Each form uses *same* floor/ceiling; no per-form parameter tuning; ≥ 0.02 margin rule prevents noise-driven flips; uniform form across all five smooth signals (no per-signal form mixing) |
| Daily-row labels inflate confidence due to overlap | **Event-level evaluation** (§8.3 #9-17) plus **block bootstrap CIs** (§8.3 #14) — daily AUC numbers report alongside event-level statistics with their effective sample size |
| Thrasher's signal does not generalize past 2022 | OOS test window 2020-present includes COVID + 2022 bear + 2023 SVB; acceptance bar §8.6 includes event-level statistical significance; if generalization breaks pre-merge, v1 doesn't ship |
| Author discretion in threshold calibration | Hard rule (§7.2): floor=p25, ceiling=p90 of train-window positive observations. Author overrides require documented signoff in `canary-calibration-v1.json`. |
| Drawdown event re-fires inside the same anchor window | Event de-duplication state machine (§6.3): one fire per 252d high anchor, reset only on a new 252d closing high. |
| Methodology drift between code and doc | OOS gate + CI guardrail in `tests/integration/regime/test_canary_oos_gate.py` blocks merge on regression; `docs/research/regime/CLAUDE.md` enforces sync-on-change rule for CRI/VCG, extend it to canary |
| Upstream warm-store data correction silently leaves a stale snapshot | `--force-recompute` mode (§11) overwrites with prior-payload-hash audit trail |
| Naive backtest forward-fills Confirmed Canary onto its underlying 5% Canary fire day | **Causal sequential state machine** (§6.3) — Confirmed Canary only emits on the day the 2nd consecutive close-below-SMA-200 occurs. Replay test (`test_canary_causality.py`) asserts byte-identical snapshots when feeding truncated histories. |
| Both-active state silently collapses into BTD via cap-clearing | **4-state explicit model** (§6 cap rule) — `BOTH_ACTIVE_AMBIGUOUS` is a first-class state capped at WATCH, never silently classified as bullish. |
| Execution-lag bias in forward-return labels | **Entry-on-next-close convention** (§8.1) — all forward returns computed from `entry_date = D+1`, removing the ~17:30 ET signal-known-before-fill bias. |
| Event-level gate hard-fails on small test-window event counts | **Minimum-event-count rule** (§8.7) — event gate marked `insufficient_events_skipped` rather than failing when n<3; daily-AUC bars still apply. |
| `payload_hash` drifts across processes due to dict ordering or Decimal repr | **Canonical hash function** (§9.0a) — sorted keys, no whitespace, fixed Decimal format. Unit test pins hash of a known-good fixture. |

## 17. Open questions for plan stage

None blocking. The implementation plan should:

1. Calibrate Class B thresholds on the train window *before* the form sweep
   (§7.2 hard rule).
2. Write `canary-calibration-v1.json` and commit it alongside the code that
   reads it.
3. Sequence the migration before any code paths that read the new scalar
   columns.

## 18. Out of scope (v2 candidates)

- Put/call ratio extreme as a 7th signal (Pan & Poteshman 2006 + CBOE study)
- HYG–SPX divergence as a confirming gate
- Zweig Breadth Thrust (requires NYSE adv/dec data not in `vol_index_daily`)
- Cross-pollinating Thrasher's Confirmed Canary into CRI's predictive side
- Real-time intraday refresh
- Promoting `score_form` to a per-signal choice (rather than one-form-fits-all)
- Bayesian regime-switching weights as an alternative to the form sweep
- Multi-asset extension (Russell 2000, EAFE, EM)

## 19. Test suite scaffolding

The implementation plan must produce at minimum the following test files
before v1 ships:

### Unit tests

```
tests/unit/cards/test_canary_scoring.py
    - score is clipped to [0, 100]
    - all six component scores are monotonic in their intended direction
    - calm-day baseline (VIX 14, all vol gates closed) produces score ≤ 15
    - convex / concave / sigmoid forms produce expected mid-range scores
      against reference fixtures
    - missing-input handling is explicit (NaN in any input → NormalizationError)
    - cap rule binds when speed_state == CONFIRMED_CANARY_ACTIVE and no cap-lift
    - cap rule binds when speed_state == BOTH_ACTIVE_AMBIGUOUS (always)
    - cap-lift conditions individually clear the cap when they apply
    - higher_closing_low uses ONLY close prices (regression test: no OHLC lookup)

tests/unit/cards/test_canary_speed_events.py
    - 5% Canary fires only once per 252-day high anchor
    - Buy The Dip requires days_since_high > 15 AND sma_50 > sma_200
    - Both primary events reset only on a new 252-day closing high
    - 42-day activity window includes the fire day itself (T+0)
    - speed_state covers all four cases:
        - CONFIRMED_CANARY_ACTIVE / BUY_THE_DIP_ACTIVE / BOTH_ACTIVE_AMBIGUOUS / NEUTRAL
    - Both-active fixture returns BOTH_ACTIVE_AMBIGUOUS (NOT BTD_ONLY)
    - speed_score mapping is exhaustive (0, 8, 20 — no other value possible)

tests/unit/cards/test_canary_confirmed_canary_state_machine.py
    - confirmed_canary fires only on day the 2nd consecutive close < SMA-200 occurs
    - confirmation window opens on canary_fire_date, expires after 42 trading days
    - any close ≥ SMA-200 resets consec_below_sma200 to 0 inside the window
    - window is consumed (removed) on confirmation — no second confirmation per canary
    - expired windows are removed
    - two concurrent open windows (rare) are independently tracked

tests/unit/cards/test_canary_causality.py
    - For each truncation K in [350, 400, 500, ..., len(history)]:
        - Run scanner on data[:K] alone (production path)
        - Compare snapshot for date data[K-1].date against the K-th snapshot of a
          full end-to-end run
        - Assert payload_hash is byte-identical
    - This test FAILS if any implementation forward-fills a label or uses
      data with date > D when computing the snapshot for date D.

tests/unit/cards/test_canary_calibration.py
    - canary-calibration-v1.json is loaded at module import
    - floor/ceiling values match the persisted JSON within rounding tolerance
    - author-override entries surface in calibration metadata

tests/unit/storage/test_canary_payload_hash.py
    - canonical_payload_hash() is stable across two runs of the same input
    - reordering payload keys does NOT change the hash
    - swapping float ↔ Decimal at the same value does NOT change the hash
    - injecting a _prior field does NOT change the hash (excluded from hashing)
    - pinned hash for fixtures/canary_calm_day.json matches a frozen constant
```

### Integration tests

```
tests/integration/regime/test_canary_scanner.py
    - scanner requires ≥350 aligned trading rows (not calendar days)
    - no future rows consumed (snapshot at date D uses only data ≤ D)
    - same (data_date, composite_version) idempotency
    - --force-recompute overwrites and stores _prior in payload
    - payload_hash differs after force-recompute, matches on no-op replay

tests/integration/regime/test_canary_oos_gate.py
    - reads latest is_winning_form=true regime_backtest_runs row
    - asserts daily AUCs within LAST_KNOWN_* ± 0.02
    - asserts event-level BTD drawup within LAST_KNOWN ± 0.01
      OR event-gate is marked insufficient_events_skipped (per §8.7)
    - asserts per-tier ablation (composite ≥ speed-only by some delta)
    - asserts block-bootstrap 95% CI on BTD drawup is strictly positive
      (conditional on event-count gate)
    - asserts forward-return labels use entry_date = D+1 (regression test:
      a known-good fixture's label set is pinned)

tests/integration/regime/test_canary_warning_state.py
    - persisted warning_state column matches payload.canary.warning_state
    - days with raw_score > 49 + warning_state=CONFIRMED_CANARY_ACTIVE
      end up with score = 49 (cap binds)
    - days that meet a cap-lift condition write cap_applied=false even when
      confirmed_canary_active=true
    - BOTH_ACTIVE_AMBIGUOUS days are always capped (cap_lift conditions
      do NOT clear the cap in this state)

tests/integration/regime/test_canary_db_constraints.py
    - inserting score = 150 raises CheckViolation
    - inserting band = 'INVALID' raises CheckViolation
    - inserting warning_state = 'PANIC' raises CheckViolation
    - inserting speed_score = 12 raises CheckViolation (must be 0/8/20)
    - inserting score_form = 'exponential' raises CheckViolation
```

### Test data fixtures

```
tests/fixtures/regime/canary_calm_day.json       # VIX 14 baseline
tests/fixtures/regime/canary_confirmed_canary.json   # bearish-warning fixture
tests/fixtures/regime/canary_buy_the_dip.json    # bullish event fixture
tests/fixtures/regime/canary_strong_buy.json     # all-three-tiers firing
tests/fixtures/regime/canary_cap_binding.json    # cap active, score=49 with raw>49
```
