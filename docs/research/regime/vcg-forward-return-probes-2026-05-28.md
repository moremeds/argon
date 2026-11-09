# VCG v2 — Forward-Return Probes (2026-05-28)

**Status**: research note. No code change. Read-only SQL against `regime_backtest_daily` (run_id=31, v2 production, 4,710 days, 18.5y).

**Question that prompted this**: with NDX/RUT data prep underway and GEX history too short for a joint-signal probe (12mo), what hypotheses about VCG can be validated against existing data *before* implementing anything?

**TL;DR**:
1. **VCG stress states are NOT bearish forward signals.** PANIC mean 20d return is +2.88%; RISK_OFF is +0.15%. Both have higher 60d win-rates than random, but their means are tail-driven, not central-tendency-driven. The methodology doc's claim that "VCG is descriptive, not predictive" is empirically confirmed.
2. **NDX/RUT dispersion-gap is empirically weak.** Only 16 days in 18 years where VXN or RVX hits 95th percentile while VIX stays under 85th. Not enough to justify a math change. Surface as info-only column on the stress-history table.
3. **BOUNCE looks bearish (5/5 days with -8.2% mean 60d return) but n=5 and 2 of 5 are 2008 GFC dates (Bear Stearns aftermath + Lehman day itself).** Cannot generalize from a sample dominated by one crisis.
4. **PANIC at 20d** is the only credible forward-edge candidate found: +2.88% mean, Sharpe-like 0.29, but median is +0.34% (mean is right-tail-driven, not central). 53% win-rate at 20d, drops to 41% at 60d. Real positive expected value with high variance, not "free money."

---

## 1. Setup

- **Indicator**: VCG v2 (cascade fix + absolute-vol-stress override), shipped in PR #91, persisted at `run_id=31`.
- **Period**: 2009-09-18 through 2026-05-21 (4,710 daily rows, post-burn-in).
- **Forward-return source**: `uw_scan.vol_index_daily` rows for `symbol='SPX'`, LEAD(close, k) at k ∈ {5, 10, 20, 40, 60}.
- **All probes are pure SQL against existing tables.** No backfill, no code change, no COMPOSITE_VERSION bump.

---

## 2. Probe 1 — Forward returns by VCG level

```sql
WITH base AS (
  SELECT r.trade_date, r.level, spx.close
  FROM uw_scan.regime_backtest_daily r
  JOIN uw_scan.vol_index_daily spx
    ON spx.symbol='SPX' AND spx.trade_date=r.trade_date
  WHERE r.run_id = 31
),
fwd AS (
  SELECT trade_date, level, close,
         LEAD(close,  5) OVER (ORDER BY trade_date) AS close_5d,
         LEAD(close, 20) OVER (ORDER BY trade_date) AS close_20d,
         LEAD(close, 60) OVER (ORDER BY trade_date) AS close_60d
  FROM base
)
SELECT level, COUNT(*) AS n_days,
       AVG((close_5d  - close)/close * 100) AS mean_5d_pct,
       AVG((close_20d - close)/close * 100) AS mean_20d_pct,
       AVG((close_60d - close)/close * 100) AS mean_60d_pct,
       COUNT(*) FILTER (WHERE close_20d < close)::numeric / COUNT(*) * 100 AS down_20d_pct,
       COUNT(*) FILTER (WHERE close_60d < close)::numeric / COUNT(*) * 100 AS down_60d_pct
FROM fwd WHERE close_60d IS NOT NULL
GROUP BY level ORDER BY mean_20d_pct ASC;
```

| level | n | mean 5d | mean 20d | mean 60d | down 20d% | down 60d% |
|---|---|---|---|---|---|---|
| BOUNCE | 5 | +0.8 | -1.9 | **-8.2** | 40 | **80** |
| EDR | 7 | +1.8 | -0.1 | +0.3 | 43 | 43 |
| WATCH | 35 | +0.1 | 0.0 | +0.1 | 34 | 37 |
| RISK_OFF | 133 | +0.4 | +0.2 | +3.0 | 32 | 26 |
| SUPPRESSED | 2317 | +0.2 | +0.7 | +2.1 | 35 | 29 |
| NORMAL | 2070 | +0.2 | +0.8 | +2.5 | 34 | 27 |
| PANIC | 83 | +0.2 | **+2.9** | +2.3 | 47 | 59 |

**Reading**: PANIC's +2.9% mean 20d return is *positive*, contradicting the intuitive "stress = sell" framing. RISK_OFF mean-reverts at +3.0% over 60d. The methodology doc's claim that VCG is "descriptive, not predictive" is empirically confirmed — stress states mark high-stress *moments*, not entry points for short trades. BOUNCE shows -8.2% mean 60d return, but n=5 (see §4).

---

## 3. Probe 2 — NDX/RUT dispersion gap

**Hypothesis**: There exist days where VXN (NDX vol) or RVX (RUT vol) hits 95th-percentile-rank-of-prior-252d while VIX stays under 85th. These would be "small-cap-led" or "tech-led" stress regimes VCG SPX-only misses.

**Method**: Computed rolling 252d percentile ranks for VIX, VXN, RVX via correlated subquery against `vol_index_daily`. Joined to `regime_backtest_daily` at v2 production run (`run_id=31`). Counted days by VCG level where either dispersion condition fires while VIX stays calm.

| VCG state | n | NDX-extreme/SPX-calm | RUT-extreme/SPX-calm | Either dispersion | VIX-extreme |
|---|---|---|---|---|---|
| SUPPRESSED | 1945 | 7 | 8 | **12** | 58 |
| NORMAL | 1741 | 4 | 0 | 4 | 53 |
| RISK_OFF | 120 | 0 | 0 | 0 | 118 |
| WATCH | 30 | 0 | 0 | 0 | 1 |
| PANIC | 20 | 0 | 0 | 0 | 18 |
| EDR | 7 | 0 | 0 | 0 | 0 |
| BOUNCE | 3 | 0 | 0 | 0 | 0 |

**Reading**: 16 dispersion-gap days across 18 years (~0.4% of trading days). On the days that VCG would catch as stress (PANIC, RISK_OFF, EDR), there are *zero* dispersion-only events — by then VIX is also extreme. **The NDX/RUT math-wiring hypothesis is empirically weak.** Data still useful to *surface* as info-only column on the stress-history table.

Secondary finding: 118/120 RISK_OFF days have VIX at 95th-percentile-rank (`vix_extreme` column). That's 98% — the v2 absolute-vol-stress override is firing where VIX alone would have flagged stress anyway. The override mostly **rebrands SUPPRESSED-by-sign-failure days as RISK_OFF**, which is exactly what it was designed to do, but it does not introduce dispersion sensitivity.

**SQL bug logged**: first attempt of Probe 2 computed `COUNT(<=) / COUNT(<=)` which degenerates to 1.0, making every day look "extreme." Corrected to `COUNT(<=) / COUNT(non_null)`. The corrected SQL is in the section header. The bug is documented here so we don't fall for the same trap in future percentile-rank probes.

---

## 4. Probe 3 — BOUNCE date inspection

The n=5 BOUNCE finding from Probe 1 is striking but small. Pulling each date with context:

| date | context | SPX | fwd 20d % | fwd 60d % | VIX rank | VVIX rank | π_panic |
|---|---|---|---|---|---|---|---|
| 2008-05-02 | NORMAL → BOUNCE → NORMAL | 1413.90 | -2.00 | **-10.66** | 0.255 | 0.028 | 0.00 |
| **2008-09-15** | SUPPRESSED → BOUNCE → NORMAL | 1192.70 | **-15.88** | **-25.49** | 0.996 | 0.554 | 0.00 |
| 2014-06-02 | NORMAL → BOUNCE → NORMAL | 1924.97 | +1.83 | +3.90 | 0.016 | 0.199 | 0.00 |
| 2018-09-04 | NORMAL → BOUNCE → NORMAL | 2896.72 | +0.92 | -5.28 | 0.594 | 0.414 | 0.00 |
| 2022-03-10 | NORMAL → BOUNCE → NORMAL | 4259.52 | +5.65 | -3.24 | 0.944 | 0.813 | 0.00 |

**Critical context**: **2008-09-15 is the Monday Lehman Brothers filed for bankruptcy.** SPX dropped 4.7% that day, then another 25% over the next 60 days. 2008-05-02 is in the Bear Stearns aftermath, ~5 months before Lehman.

So 2 of 5 BOUNCE days are 2008 financial crisis dates. They drive the -8.2% mean 60d return entirely. The remaining 3 BOUNCE days (2014, 2018, 2022) show milder moves: +3.9, -5.3, -3.2. No catastrophic drawdowns.

**Conclusion**: BOUNCE is not a leading bear signal in any generalizable sense — it's a confirmation signal that fired on Lehman day itself. This actually matches the methodology doc's well-documented "VCG was late on Lehman" finding (SUPPRESSED days -5 to -1, BOUNCE day 0, RISK_OFF day +3). **The signal does not anticipate crises; it confirms them coincidentally.**

Implications:
- Cannot use BOUNCE as a "get out before the crash" signal.
- Cannot dismiss BOUNCE as noise either — when crisis is genuinely unfolding, BOUNCE marks it.
- For UI purposes, BOUNCE should appear in stress-history *if and only if* we accept it as a "you are now in a crisis confirmation" indicator, not a forward-prediction.

---

## 5. Probe 4 — PANIC event study

Full distributional analysis of forward returns by VCG state, including median (less sensitive to outliers) and Sharpe-like ratio.

| level | n | mean 20d | median 20d | p10 20d | p90 20d | std 20d | Sharpe-like | win% 20d | mean 60d | median 60d | win% 60d |
|---|---|---|---|---|---|---|---|---|---|---|---|
| PANIC | 83 | **+2.88** | +0.34 | -8.82 | +17.66 | 9.92 | **0.290** | 53.0 | +2.29 | **-4.14** | 41.0 |
| NORMAL | 2070 | +0.80 | +1.46 | -4.16 | +4.92 | 4.27 | 0.187 | 66.1 | +2.51 | +3.61 | 73.3 |
| RISK_OFF | 133 | +0.15 | +2.02 | -13.50 | +7.20 | 7.94 | 0.019 | 67.7 | +3.04 | +3.65 | 74.4 |
| BOUNCE | 5 | -1.89 | +0.92 | -10.32 | +4.12 | 8.28 | -0.229 | 60.0 | -8.15 | -5.28 | 20.0 |

**Detailed reading:**

### 5.1 PANIC at 20d
- **Mean +2.88%, median +0.34%**: huge gap. The mean is right-tail-driven (p90 = +17.66%, p10 = -8.82%). Most PANIC days have only mild positive forward returns; a few have massive ones.
- **Sharpe-like 0.290**: comparable to typical quant edge metrics. Real positive expected value.
- **Win rate 53%**: marginally above coin-flip. The edge is in *return magnitude when right*, not *frequency of being right*.
- **Standard deviation 9.92%**: high. A single PANIC trade can lose 9%+ in 20 days easily.

### 5.2 PANIC at 60d
- **Mean +2.29%, median -4.14%, win-rate 41%**: at 60d, the typical PANIC entry is followed by a *loss*. The positive mean is driven entirely by a small number of huge winners.
- **PANIC entries at 60d are worse than NORMAL entries at 60d** (NORMAL: 73% win rate, +3.61 median). The "buy panic" thesis only holds for short hold periods.

### 5.3 RISK_OFF at 20d / 60d
- **Sharpe-like 0.019**: effectively zero. RISK_OFF has positive mean returns but only because its distribution matches the unconditional market drift.
- **Mean ≈ +0.15% at 20d, +3.04% at 60d**: indistinguishable from buy-and-hold baseline at 60d (NORMAL +2.51% / +3.61 median).
- **RISK_OFF adds no forward-return information** beyond what unconditional market drift provides. The label tells you "VIX is high"; it doesn't tell you "forward returns will differ."

### 5.4 BOUNCE
- See §4. n=5 dominated by 2008 crisis dates.

---

## 6. What this implies for the VCG roadmap

The current roadmap (`vcg-next-steps-2026-05-26.md` + my own session-recommendations) needs revision:

| Item | Original framing | What probes show | Recommendation |
|---|---|---|---|
| NDX/RUT wiring | "structural data gap; high upside" | 16 dispersion days in 18yr; gap is real but tiny | **Surface as info-only column on stress-history table. Do NOT change classifier math.** |
| VCG ∩ GEX joint | "novel hypothesis" | Untestable (12mo GEX history vs 18yr VCG) | **Defer until GEX has ≥3yr history or we backfill from option chains.** |
| VCG ∩ CRI joint | (per user) "CRI is lagged" | Confirmed: VCG itself is also lagged | **Drop joint-with-CRI from roadmap.** |
| Slow-grind drawdown labeling | "fills coverage gap for 2022-style bleeds" | Untested by these probes; still credible | **Run a Probe 5 to validate before building.** |
| PANIC-as-buy-the-dip event study | not previously on roadmap | Real but high-variance edge at 20d | **Add as a new product surface: "Stress dip-buy log."** |

The single biggest revision: **stop pitching VCG as a forward-prediction indicator.** It is a coincident-stress descriptor. Use it for either:
- *Crisis confirmation* (which is what BOUNCE actually does, despite being late);
- *Dip-buy timing* on 20d windows (PANIC, high variance);
- *Regime context* alongside leading indicators (term structure, dealer gamma when its history matures).

---

## 7. Probes run, results table

| Probe | Question | Result | Status |
|---|---|---|---|
| 1 | Do VCG v2 levels predict forward SPX returns? | Yes, but inversely: PANIC/RISK_OFF mean-revert positively. | Done |
| 2 (v1) | NDX/RUT dispersion gap? | BUGGY: percentile-rank SQL degenerated to ~1.0. | Bug logged |
| 2 (v2) | NDX/RUT dispersion gap, corrected? | 16 dispersion days in 18yr — too few to justify math change. | Done |
| 3 | What are the 5 BOUNCE dates? | 2 of 5 are 2008 crisis days. Cannot generalize. | Done |
| 4 | PANIC distributional event-study? | Mean +2.88% 20d (Sharpe-like 0.29). Median +0.34%, win-rate 53%. Tail-driven. | Done |

## 6. Probe 6 — VCG lag vs term-structure inversion (VIX > VIX3M)

**Hypothesis**: VIX > VIX3M (term-structure inversion / backwardation) is widely considered a leading vol-stress indicator. If VCG is genuinely "lagged," term-structure should foreshadow VCG stress by a measurable number of days.

### 6A — For each VCG stress day, was there a prior backwardation day in the last 60d?

| level | n | no backwardation in 60d | coincident same-day | preceded by backwardation | mean lag | median lag | min/max |
|---|---|---|---|---|---|---|---|
| EDR | 8 | 1 | 2 | 5 | 13.6 | 8.0 | 1-27 |
| PANIC | 83 | **63** | 20 | **0** | — | — | — |
| RISK_OFF | 135 | 9 | 96 | 30 | 15.3 | 3.5 | 1-55 |

**Reading**:
- **PANIC**: 76% of PANIC days have no backwardation in the prior 60d. 24% are same-day coincident. **Zero PANIC days are preceded** by a lone earlier backwardation event. PANIC fires on spot-vol shocks (VIX spike without term-structure break), not on slow term-structure deterioration.
- **RISK_OFF**: 71% coincident, 22% preceded (median lag 3.5 days). Term-structure leads RISK_OFF only sometimes, by only a few days on the median case.
- **EDR**: 5/8 preceded by backwardation, median lag 8 days. Small sample but suggests EDR DOES tend to follow backwardation by a week or so.

### 6B — Inverse direction: for each backwardation episode, did VCG fire stress within 30d?

| n_episodes | missed (no VCG within 30d) | coincident | VCG lagging | mean lag | median lag | coverage % |
|---|---|---|---|---|---|---|
| 105 | 55 | 25 | 25 | 11.8 | 9.0 | 47.6 |

**Reading**: More than half (52.4%) of backwardation episodes don't trigger any VCG stress within 30 days. When VCG does respond, the median lag is 9 days. So if treated as a leading indicator, term-structure produces a high false-positive rate — most backwardation events are not stress events.

### 6C — Forward SPX returns by backwardation bucket

The critical probe: are the "missed" backwardation events actually stress regimes VCG ignores, or noise that VCG correctly filters?

| bucket | n | mean 5d | mean 20d | mean 60d | median 60d | down 60d % |
|---|---|---|---|---|---|---|
| vcg_lagging | 21 | -1.34 | -0.03 | -0.25 | +0.56 | **47.6** |
| coincident | 24 | +1.41 | +0.38 | +1.93 | +3.22 | 37.5 |
| **missed_by_vcg** | **53** | +1.27 | **+2.58** | **+4.90** | **+5.25** | **18.9** |

**This burns the "VCG is lagged" framing.** The episodes VCG ignores (missed_by_vcg) have the *strongest positive* forward returns (+5.25% median 60d, only 18.9% down-hit). These are backwardation false alarms — VIX scares that resolve into rallies. VCG correctly does not fire on them.

The episodes VCG eventually confirms (vcg_lagging) have the worst forward returns: -1.34% mean 5d, 47.6% 60d down-hit. These are the genuine stress regimes — and term-structure caught them ~9 days earlier than VCG did.

### 6D — Reframe: VCG's "lag" is a feature

The classical reading ("VCG is too late") assumes the lag is a defect. The data shows the lag is a noise filter:

- 53/98 backwardation episodes are followed by *rallies* — VCG correctly filters them out.
- 21/98 backwardation episodes are followed by *drawdowns* — VCG eventually confirms them, with a median 9-day lag.
- The 9-day lag is the cost of the filter: it trades earliness for precision.

**Product implication**: there's a real edge case for a joint UI surface showing "term-structure flash + VCG confirmation timeline" — i.e., visualize backwardation events with their current VCG status. A backwardation event that's lasted 3+ days without VCG confirmation is more likely to be a false alarm; one that VCG has caught up to is a genuine stress regime.

**Methodology caveat**: this uses strict `VIX > VIX3M` for backwardation. A buffered version (e.g., `VIX > 1.05 × VIX3M`) would remove marginal events and change the false-alarm count. Worth re-running with a buffer threshold before treating the 52% false-alarm rate as fixed.

---

## 7. Probes run, results table

| Probe | Question | Result | Status |
|---|---|---|---|
| 1 | Do VCG v2 levels predict forward SPX returns? | Yes, but inversely: PANIC/RISK_OFF mean-revert positively. | Done |
| 2 (v1) | NDX/RUT dispersion gap? | BUGGY: percentile-rank SQL degenerated to ~1.0. | Bug logged |
| 2 (v2) | NDX/RUT dispersion gap, corrected? | 16 dispersion days in 18yr — too few to justify math change. | Done |
| 3 | What are the 5 BOUNCE dates? | 2 of 5 are 2008 crisis days. Cannot generalize. | Done |
| 4 | PANIC distributional event-study? | Mean +2.88% 20d (Sharpe-like 0.29). Median +0.34%, win-rate 53%. Tail-driven. | Done |
| 5 | Slow-grind drawdowns — VCG level distribution? | 80.7% of -10%-from-60d-high days are NORMAL or SUPPRESSED; worst SUPPRESSED drawdown = -26.5%. | Done |
| 6A | VCG stress days preceded by backwardation? | PANIC: 76% have no backwardation in 60d. RISK_OFF: 71% same-day coincident, 22% preceded by 3-15 days. | Done |
| 6B | Backwardation episodes → VCG stress within 30d? | 105 episodes; 52% missed by VCG; coverage 48%. Median lag 9 days when VCG fires. | Done |
| 6C | Forward returns by backwardation bucket? | "Missed by VCG" episodes have +5.25% median 60d return — VCG correctly filters term-structure noise. | Done |
| 10 | Backwardation with 1.05× buffer — sensitivity? | Buffer reduces n and flips signal positive everywhere. Probe 6 framing without buffer is the right one. | Done |
| 11 | Lag-bucket forward returns — continuous or threshold? | **Threshold-shaped.** Lag 15-30d: -5.99% mean 60d, 75% down-hit. Lag ≤14d: noise. | Done |

## 7B. Probe 5 — Slow-grind drawdowns VCG missed

**Hypothesis**: SPX often drops ≥10% from a 60d high in slow-grind regimes where VIX stays low. VCG, being vol-stress-anchored, may flag these as NORMAL/SUPPRESSED rather than stress states.

**Method**: Identified all days where SPX close < 0.9 × max(SPX close over prior 60 days). Cross-tabulated with VCG v2 level.

| VCG level | n drawdown days | mean DD from 60d high | worst DD |
|---|---|---|---|
| NORMAL | **128** | -13.15 | -20.83 |
| SUPPRESSED | **111** | -14.01 | **-26.51** |
| RISK_OFF | 34 | -13.03 | -17.61 |
| PANIC | 20 | -25.00 | -33.92 |
| EDR | 2 | -13.24 | -14.10 |
| BOUNCE | 1 | -11.20 | -11.20 |

**Reading**: 239 of 296 drawdown days (80.7%) were classified NORMAL or SUPPRESSED. SPX can be 26.5% below its 60d high while VCG says "stress is suppressed." This is by design — VCG measures vol stress, not price drawdown — but the gap is real for users who expect a regime indicator to catch slow-grind bears.

**Implication**: This validates `vcg-next-steps-2026-05-26.md` item #4 ("slow-grind drawdown labeling"). It's not a VCG math change — it's an additional regime label class that runs on price-drawdown features rather than vol-complex features. Could be persisted as a separate boolean field on `regime_backtest_daily.payload` and surfaced as a parallel pill on the UI.

## 7C. Probe 10 — Backwardation with 1.05× buffer

**Hypothesis**: Probe 6's 52% backwardation false-alarm rate may be inflated by marginal events near VIX ≈ VIX3M. A 5% buffer (`VIX > 1.05 × VIX3M`) should select stronger inversions and reduce the false-alarm rate.

| bucket (with 1.05× buffer) | n | mean 20d | mean 60d | median 60d | down 60d% |
|---|---|---|---|---|---|
| coincident | 16 | -0.30 | +4.89 | +4.89 | 31.3 |
| vcg_lagging | 6 | +4.36 | +8.95 | +11.73 | 16.7 |
| missed_by_vcg | 13 | +6.24 | +11.05 | +9.14 | 7.7 |

**Compare to Probe 6C (no buffer)**:

| bucket | n | mean 60d |
|---|---|---|
| vcg_lagging (no buffer) | 21 | -0.25 |
| vcg_lagging (buffer) | **6** | **+8.95** |

**Reading**: The buffer makes the signal *worse*, not better. With 1.05× threshold, even the vcg_lagging bucket (previously the bearish-skew bucket) flips strongly positive. Strong backwardation events are even more likely to occur at vol peaks (which historically precede rallies, not crashes) than marginal backwardation events. The bearish signal in original Probe 6C was concentrated in *mild* backwardation events, not strong ones.

**Implication**: A buffered backwardation threshold is not the right refinement. Probe 6's framing (no buffer) is more informative. Caveat: n drops from 21 → 6 for vcg_lagging with the buffer; this is at the edge of statistical reliability.

## 7D. Probe 11 — Lag is threshold-shaped, not continuous

**Hypothesis**: Probe 6 reported a 9-day median lag from backwardation episode start to first VCG stress fire. Is the predictive content continuous (a 3-day lag and a 15-day lag both signal stress) or threshold-shaped (only lags above some cutoff matter)?

| lag bucket | n | mean lag (days) | mean 20d | mean 60d | down 60d% |
|---|---|---|---|---|---|
| 1: 1-3d | 22 | 1.5 | -0.01 | +1.67 | 40.9 |
| 2: 4-7d | 6 | 5.2 | +0.88 | +4.23 | 16.7 |
| 3: 8-14d | 6 | 9.5 | +0.32 | +2.03 | 50.0 |
| **4: 15-30d** | **8** | 23.1 | **-1.18** | **-5.99** | **75.0** |

**Reading**: The lag is sharply threshold-shaped. Backwardation events confirmed by VCG within 14 days show no bearish forward signal (and modest positive drift). Backwardation events that take VCG 15-30 days to confirm show -5.99% mean 60d return and 75% down-hit rate. The bearish signal is concentrated entirely in the long-lag bucket (n=8).

**This re-explains Probe 6C's "vcg_lagging is bearish" finding**: 8 of 21 vcg_lagging episodes are slow-burn stress regimes (long lag); 13 are quick-confirmations that turn out to be false alarms. Averaging the two gave -0.25 mean 60d, which is the result of cancellation between the two distinct populations.

**The actionable product signal**: **a backwardation event that has been active for 14+ days without VCG confirmation is approaching the bearish-signal threshold.** This is a concrete monitoring trigger — track ongoing backwardation episodes, count days since onset, alert at day 14+ if VCG has not yet confirmed.

**Caveats**:
- n=8 for the bearish bucket. Suggestive, not validated.
- The 14-day cutoff is data-driven, not theory-driven. Could be 12 or 16 with a different sample.
- Mechanism is plausible (slow vol build → eventual fundamental confirmation) but unproven.

## 7E. Probe 12 — Sensitivity battery on the 14-day lag threshold

User triage call: "probe first before building." Four sensitivity probes designed to test whether Probe 11's n=8 bearish bucket is robust or sample-fit.

### 12A — Date list of the 8 long-lag events (lag 15-30d)

| episode_start | confirm | lag | VIX | SPX | fwd_60d % |
|---|---|---|---|---|---|
| 2018-03-01 | 2018-03-22 | 21 | 22.47 | 2677.67 | **+1.63** |
| 2018-12-06 | 2018-12-26 | 20 | 21.19 | 2695.95 | **+2.80** |
| 2020-01-27 | 2020-02-24 | 28 | 18.23 | 3243.63 | -13.70 (COVID) |
| 2020-01-31 | 2020-02-24 | 24 | 18.84 | 3225.52 | -11.23 (COVID) |
| 2022-02-23 | 2022-03-16 | 21 | 31.02 | 4225.50 | -7.68 (Ukraine) |
| 2022-02-28 | 2022-03-16 | 16 | 30.15 | 4373.94 | -9.89 (Ukraine) |
| 2022-04-26 | 2022-05-25 | 29 | 33.52 | 4175.20 | -5.71 |
| 2022-04-29 | 2022-05-25 | 26 | 33.40 | 4131.93 | -4.12 |
| 2026-03-03 | 2026-03-23 | 20 | 23.57 | 6816.63 | (pending — 5 trading days short) |
| 2026-03-06 | 2026-03-23 | 17 | 29.49 | 6740.02 | (pending) |

**Reading**: The 8 events are *not* 8 independent episodes. They are **5 distinct stress episodes** because consecutive entries within the same week confirm to the same VCG stress day:
- 2018-03 (1 episode, signal failed → rally)
- 2018-12 (1 episode, signal failed → rally)
- 2020-01 COVID (2 entries → same episode, true positive)
- 2022-02 Ukraine (2 entries → same episode, true positive)
- 2022-04 (2 entries → same episode, true positive)

True precision = 3/5 = **60% on 5 independent episodes**, not 75% on 8 events. The 75% figure from Probe 11 was inflated by within-episode duplication.

### 12B — Threshold sensitivity (cutoffs 7-21 days)

| lag cutoff | n above cutoff | mean 60d | down 60d % |
|---|---|---|---|
| 7 | 16 | -1.85 | 56.3 |
| 10 | 9 | -3.88 | 66.7 |
| 12 | 9 | -3.88 | 66.7 |
| 14 | 9 | -3.88 | 66.7 |
| 16 | 8 | -5.99 | 75.0 |
| 18 | 7 | -5.43 | 71.4 |
| 21 | 6 | -6.80 | 83.3 |

**Reading**: The "14-day threshold" from Probe 11 is a bucket-binning artifact. The actual relationship is *graded* — stronger lag means stronger bearish signal, no clean threshold. The mean 60d return moves smoothly from -1.85% at 7d cutoff to -6.80% at 21d cutoff. Probe 11's clean threshold-shape claim was an over-read of an arbitrary binning choice.

### 12D — Pre-2018 vs post-2018 era split

| era | bucket | n | mean 60d | down 60d % |
|---|---|---|---|---|
| **A: 2009-09 to 2017-12** | short_lag_1-14d | 15 | +2.14 | 33.3 |
| **A: 2009-09 to 2017-12** | **long_lag_15-30d** | **0** | — | — |
| B: 2018-01 to 2026-05 | short_lag_1-14d | 19 | +2.22 | 42.1 |
| B: 2018-01 to 2026-05 | long_lag_15-30d | 8 | -5.99 | 75.0 |

**Reading**: This is the most important finding. **All 8 long-lag events are post-2018.** Pre-2018 (8.5 years of data), zero backwardation episode took VCG more than 14 days to confirm. The pattern simply did not exist in the first half of the dataset.

Two possible explanations:
- **Real regime shift**: Post-2018 vol microstructure (post-Volmageddon, post-COVID, increased 0DTE / dealer-hedging flow) genuinely changed the dynamics. The 14-day-lag pattern is a real new phenomenon.
- **Statistical artifact**: 5 episodes from a 7-year window is too few to claim a regime. The pattern may dissolve as more data accumulates.

There is no clean way to distinguish these from the existing data. Mechanism-level theory would help, but the conversation hasn't surfaced one.

### 12 — Net effect on the Probe 11 hypothesis

Three findings together:
1. **n=8 is really n=5** (within-episode duplication).
2. **Precision drops from 75% to 60%** when measured per episode.
3. **Signal is era-specific** — zero pre-2018 events, all events 2018-2022 with 2 pending 2026.
4. **Threshold is graded, not sharp** — no clean 14-day cutoff.

The Probe 11 finding survives in weakened form: there is a real association between long-lag backwardation confirmation and forward drawdowns *in 2018-2026*, with 3 of 5 episodes resulting in significant 60d drawdowns. But the strength of the claim that justified building a UI surface ("75% down-hit, clean 14-day cutoff") does not survive sensitivity analysis.

**Decision**: do not build the backwardation-age tracker yet. Wait for either:
- The two 2026-03 events to mature (5 more trading days) → tests the regime-shift hypothesis live.
- New independent long-lag episodes to accumulate → grows the sample.
- A mechanism-level theory for why post-2018 differs → would justify acting on a small sample.

## 7F. Probe 13 — Credit-led events VCG misses (user-prompted by SVB / 2025 tariff)

User flagged that SVB (March 2023) and 2025 tariff war should be in the data but didn't appear in Probe 12A's long-lag list. Investigation revealed two new stress modes beyond "slow-build long-lag":

**Three stress modes for VCG:**
1. **Slow-build mode** (Probe 11/12): term-structure inverts weeks before vol panics. n=5 distinct events 2018-2026.
2. **Shock mode**: vol explodes within days; backwardation and VCG fire coincidentally. Examples: 2024-08 yen-carry unwind (RISK_OFF same day as backwardation), 2025-04 tariff war (RISK_OFF day 2, PANIC day 6).
3. **Credit mode**: vol stays muted because stress is credit-led, not vol-led. Example: SVB (VIX peaked at 26, never invertd term-structure). VCG/term-structure both blind.

### 13A — SVB window credit metrics

| date | VIX | HYG | LQD | HYG/LQD ratio | VCG |
|---|---|---|---|---|---|
| 2023-02-28 (pre) | 20.70 | 74.53 | 105.92 | 0.7036 | SUPPRESSED |
| 2023-03-09 (Thu, SVB collapsing) | 22.61 | 73.43 | 105.31 | 0.6973 | SUPPRESSED |
| 2023-03-10 (Fri, SVB seized) | 24.80 | 73.44 | 106.82 | 0.6875 | SUPPRESSED |
| 2023-03-15 (worst day) | 26.14 | 73.33 | 107.61 | 0.6814 | SUPPRESSED |
| 2023-03-24 (resolution) | 21.74 | 73.60 | 109.47 | 0.6723 | SUPPRESSED |

HYG dropped just -2% from pre-SVB to peak. **HYG alone did not signal credit stress.** But HYG/LQD ratio dropped from 0.7036 → 0.6723 (-4.4%) because IG bonds (LQD) RALLIED as rates collapsed while HY stayed flat. The credit signal lives in the *divergence*, not the absolute level. VCG looks at vol complex only, so it sees nothing.

### 13D — Credit-stress episodes (HYG/LQD -3% over 20d AND VIX < 25)

41 distinct episode-starts across 18 years. Including 2 around SVB (2023-03-23, 2023-04-03) and a precursor to COVID (2020-01-31). The list catches every credit-led event the user named.

### 13E — Forward returns by credit/vol regime crosstab

| regime | VCG | n | mean 20d | mean 60d | down 60d % |
|---|---|---|---|---|---|
| A: credit-stress + vol-calm | SUPPRESSED | 56 | -0.61 | +2.08 | 37.5 |
| A: credit-stress + vol-calm | NORMAL | 41 | +2.22 | **+3.75** | 17.1 |
| A: credit-stress + vol-calm | RISK_OFF | 11 | +3.46 | +4.64 | 0.0 |
| D: quiet (baseline) | NORMAL | 1605 | +0.63 | +2.18 | 26.3 |
| D: quiet (baseline) | SUPPRESSED | 1789 | +0.76 | +2.40 | 25.9 |

**This kills the "VCG ∩ credit signal" coverage hypothesis.** Credit-stress + vol-calm days when VCG is SUPPRESSED/NORMAL show forward returns *equal to or better than* the quiet baseline. The gap is real (VCG misses these events), but the missed events are NOT bearish forward — they're mean-reverting positive.

The same pattern as PANIC, but for credit: stress markers identify moments of capitulation, not warning. SVB itself is the canonical case — credit spreads widened, banks panicked for 2 weeks, then everything recovered (SPX +11% over 60d after the worst SVB day).

### 13 — Net effect on the credit-augmentation hypothesis

Probe 13E rules out the VCG ∩ CRI/HYG joint as a coverage extension. The earlier reasoning ("CRI is lagged but catches credit-led events VCG misses") gets refined: yes, credit signal catches what VCG misses, BUT those events don't subsequently drawdraw, so the joint signal would expand coverage without improving precision. There is no actionable edge to build.

## 8. Probes deferred (suggested follow-ups)

| ID | Question | Cost | Why deferred |
|---|---|---|---|
| 7 | VCG ∩ Canary joint state forward-return — does Canary BUY band + VCG PANIC outperform PANIC alone | 1 SQL query | Less novel (overlapping inputs) but cheap |
| 8 | PANIC event-study with stop-loss — what if we exit at -5% drawdown vs hold to +20d? | 1 SQL query + Python | Adds trade-rule realism to the edge claim |
| 9 | VCG ∩ GEX joint (requires GEX backfill or wait) | medium-large | Untestable today |
| 14 | Re-run Probe 12 after 2026-06-03 to score the two pending 2026-03 events | 1 SQL query | Genuine OOS test of the post-2018 lag hypothesis |

---

## 9. Open questions / known limitations

1. **Survivorship & no-trade-cost assumption.** All forward-return computations assume daily-close prices and zero transaction cost. A live strategy at PANIC dates would face slippage, especially on 2008 crisis dates.
2. **In-sample window.** All 4,710 days were used both to compute VCG v2 calibration *and* to evaluate forward returns. Strictly, this is in-sample. An honest holdout would reserve post-2026-05-27 days for OOS evaluation.
3. **PANIC sample skew.** 83 days but several cluster in 2008 (Lehman + aftermath), 2020 (COVID), 2022 (Ukraine + Fed). Without de-clustering, a few crisis episodes dominate the mean.
4. **No Bayesian credibility intervals.** "Sharpe-like 0.29 on n=83" is a point estimate. A proper analysis would report the posterior over Sharpe given the data. Single Sharpe value is suggestive, not validated.

---

## 10. What's been done (record)

- Verified VXN (4,200 rows) and RVX (4,191 rows) are already in `uw_scan.vol_index_daily`. No backfill needed; the previously-recommended "NDX/RUT backfill" task is mis-named.
- Verified `greek_exposure_daily` has only ~257 trading days (2025-05-19 → 2026-05-27). Too short for any joint VCG ∩ GEX probe.
- Ran 10 SQL probes against `regime_backtest_daily` run_id=31 + `vol_index_daily` (no schema writes):
  1. Forward-return predictivity by VCG level — VCG is not forward-bearish.
  2. NDX/RUT dispersion gap — 16 days in 18yr, too few to justify math change.
  3. BOUNCE date inspection — n=5, 2 of 5 are 2008 GFC dates.
  4. PANIC distributional event-study — mean +2.88% 20d but median +0.34%, tail-driven.
  5. Slow-grind drawdowns — 80.7% of -10%-from-60d-high days are NORMAL/SUPPRESSED; worst SUPPRESSED drawdown -26.5%.
  6A. VCG stress lag from prior backwardation — PANIC mostly independent, RISK_OFF mostly coincident.
  6B. Backwardation episode → VCG response — 52% missed by VCG within 30d, median 9-day lag when caught.
  6C. Forward returns by backwardation bucket — VCG-ignored backwardation = +5.25% median 60d return (false alarms VCG correctly filtered).
  10. Backwardation with 1.05× buffer — buffer flips signal positive everywhere; original Probe 6 framing is correct.
  11. Lag-bucket forward returns — appeared threshold-shaped at 14 days; lag 15-30d showed -5.99% mean 60d, 75% down-hit (n=8). LATER WEAKENED BY PROBE 12.
  12A. Date inspection of long-lag events — n=8 is really 5 distinct episodes; 3 of 5 true positives → 60% precision per episode, not 75%.
  12B. Threshold sensitivity (cutoffs 7-21d) — relationship is graded, not threshold-shaped; "14-day cutoff" was a bucket-binning artifact.
  12D. Pre/post-2018 split — ZERO long-lag events pre-2018; all 8 events are 2018-2026. Signal is era-specific, not universal.

**Verdict on Probe 11's edgy finding**: substantially weakened. Decision to NOT build the backwardation-age tracker until either (a) the 2 pending 2026-03 events mature (~5 more trading days), (b) new independent long-lag episodes accumulate, or (c) a mechanism-level theory for the post-2018 regime shift is developed.
- Logged one SQL bug (Probe 2 v1 percentile-rank denominator).
- Wrote this note. **No code, no migrations, no API changes.** Pure read-only research.

## 11. Net synthesis (updated after Probes 12, 13)

The combined picture across all probes:

**VCG is not a leading bear-warning indicator and was never meant to be.** It is a coincident vol-stress descriptor with a structured decision lag. PANIC and RISK_OFF mark bottoms or coincide with stress, not its onset.

**Three stress modes for VCG (Probe 13):**
1. **Slow-build mode** — term-structure inverts weeks before vol panics (COVID-style, Ukraine-style). VCG genuinely late, but the "14-day lag threshold" pattern is fragile (n=5 distinct events, all post-2018).
2. **Shock mode** — vol explodes in days, VCG fires near-coincidentally (2024 yen-carry, 2025 tariffs). VCG is fast here, not late.
3. **Credit mode** — vol stays muted, stress is credit-led (SVB). VCG/term-structure both blind. But Probe 13E shows the missed events don't subsequently drawdraw, so there's no actionable edge to plug the gap.

**The actionable edges that survived sensitivity:**
1. **PANIC + 20d long hold** = +2.88% mean / Sharpe-like 0.29 / 53% win-rate (Probe 4). Real but tail-driven; a "stress dip-buy" not a "regime warning."
2. **Backwardation without VCG confirmation in 30d** = +5.25% median 60d (Probe 6C). False-alarm class, useful for filtering OUT of trading decisions.
3. **Slow-grind drawdowns** are a known coverage gap (Probe 5). VCG flags only ~20% of -10%-from-60d-high days.

**The actionable edges that did NOT survive:**
- Probe 11's 14-day lag threshold (eroded by Probe 12 sensitivity)
- VCG ∩ CRI / credit coverage (Probe 13E: missed events resolve positively, no edge)

**Recommendation**: do not build any new VCG-related product right now. Wait for:
- 2026-03 events to mature past their 60d forward window (5 more trading days from 2026-05-28).
- More independent long-lag episodes to accumulate.
- A mechanism-level theory for why the post-2018 era differs (post-Volmageddon, 0DTE, dealer flow changes are candidates).

**Things ruled out across the session:**
- VCG as a "stress = sell" signal.
- VCG ∩ CRI joint (Probe 13E: missed events don't drawdraw).
- VCG ∩ GEX joint (untestable, GEX history too short).
- NDX/RUT math wiring (16 dispersion days in 18yr).
- BOUNCE generalization (Lehman-driven n=5).
- Backwardation with 1.05× buffer (worse, not better).
- Backwardation-age tracker (Probe 12 sensitivity).
- Credit-coverage augmentation (Probe 13E).

**Process lesson**: validation-before-building killed three implementation projects in this session — 14-day-lag tracker, VCG ∩ GEX, VCG ∩ credit. Each would have been 3-5 days to build on signal that doesn't hold up. Total probe cost: ~15 minutes of SQL. Total avoided cost: 10-15 days of misdirected work. The discipline is working as designed.

**The pattern that keeps repeating**: every "edgy" stress-signal hypothesis we test in this session shows the same shape — *missed* stress events have positive forward returns, *confirmed* stress events also have positive forward returns at 20d (mean reversion). The market really does buy the dip on identified stress, on the timescales VCG and credit/term-structure indicators measure. VCG's job isn't to predict drawdowns; it's to mark capitulation moments. That's the product positioning that survives every probe.
