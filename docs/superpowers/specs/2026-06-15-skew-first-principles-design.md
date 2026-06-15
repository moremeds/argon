# Skew First Principles — per-ticker Skew tab (design)

**Date:** 2026-06-15
**Status:** Design — awaiting review
**Source material:** `docs/notes/options/02-Skew的第一性原理.md` (theoptionsbook.com appendix B, integrated)

---

## 1. Goal

A per-ticker **"Skew"** tab on the stock detail page that operationalizes the doc's
first-principles framework: read a ticker's skew as the **shape of its risk-neutral
distribution**, positioned against **its own historical baseline** (the doc's core
signal), explained by **spot-vol correlation ρ**, contextualized by **asset-class
baseline** and **borrow cost**, with a **deterministic** decision-chain read that
includes an **evidence-gated directional lean** — plus a **Tier-1 markout validation**
run on the ~13-month backfill so both the read and the lean ship evidence-backed rather
than asserting unproven edge.

**Positioning (research-grounded):** this is primarily a **regime / positioning +
relative-value (mean-reversion)** tool. It *does* express a **directional lean**, but the
lean is **earned, not asserted**: it shows a non-neutral tilt only for a bucket the
Tier-1 markout proved separates forward returns, that passes the live **borrow gate**
(hard-to-borrow → suppressed, because ~2/3 of apparent skew edge is the borrow-fee
confound), and that is outside an earnings window and a blown-up regime. Where those
conditions aren't met the lean is **NEUTRAL with a stated reason** (relative-value read
only). The read never emits a naked or unvalidated directional call.

## 2. Why this framing (evidence)

Web research (verified primary sources) on whether single-name skew predicts returns:

- **Xing, Zhang & Zhao (2010, JFQA)** — steep-smirk stocks underperformed the
  least-steep by ~10.9%/yr, persisting ~6 months, driven by informed put-buying before
  bad earnings. Real and large — **in-sample**.
  https://www.cambridge.org/core/services/aop-cambridge-core/content/view/ECFD16BA9ACBDC8D577D1BD866FBEA72/S0022109010000220a.pdf/what-does-the-individual-option-volatility-smirk-tell-us-about-future-equity-returns.pdf
- **Cremers & Weinbaum (2010, JFQA)** — expensive-call stocks beat expensive-put stocks
  ~50 bps/wk; **authors document decay over their own sample**.
  https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/deviations-from-putcall-parity-and-stock-return-predictability/D9BA8F97580328AAFD7988B092FE5D50
- **Muravyev, Pearson & Pollet (2025, JFE)** — *the decisive finding*: ~2/3 of
  option-signal return predictability is the **stock borrow fee** in disguise. Adjust
  for borrow cost (or drop hard-to-borrow names) and the residual edge "is not actually
  profitable." Borrow cost is both the source of the signal and the limit to arbitrage.
  https://fmai.memberclicks.net/assets/docs/Derivatives2022/MuravyevPearsonPollet.pdf
  / press release: https://giesbusiness.illinois.edu/news/2026/01/07/study--borrowing-fee-is-the-variable-that-debunks-theory-that-options-predict-future-stock-returns
- **No peer-reviewed study isolates the 25Δ risk-reversal as a clean single-name return
  predictor.** Practitioner sources (CBOE, MenthorQ, SpotGamma) treat RR as
  positioning/sentiment, not forecast.

**Verdict:** single-name skew is a **weak, decayed, largely non-exploitable directional
signal** but a **defensible relative-value / regime input**. This is exactly the
framing of this design, and it dictates the Phase-2 methodology (mean-reversion primary;
directional only as **borrow-conditioned** secondary — otherwise we would "rediscover"
the borrow-fee artifact and fool ourselves).

## 3. Practical, tradable ideas the tab supports (ranked by computability)

1. **Skew/RR mean-reversion (RV)** — the only family with explicit computable triggers:
   RR ≳2σ from its 30-day mean *or* at a 52-week percentile extreme → fade toward
   baseline via **defined-risk** verticals/collars (never naked RR). **Tab's core signal.**
2. **Directional overlay — "protect cheap / finance rich"** — the **defined-risk
   structure that expresses the evidence-gated directional lean** (§5 `directional_lean`):
   RR cheap → buy puts/put-spread at a discount; RR rich → finance the directional leg by
   selling the expensive wing (collar / put-spread-collar). The *structure* is always
   available as relative-value; it carries a directional tilt only when a `TRADABLE_*`
   bucket verdict and the borrow/earnings/regime gates permit. Defined-risk always.
3. **Spot-vol ρ regime tag (panic vs chase)** — macro/beta (ρ<0, spot↓+vol↑ → real
   hedging fear) vs idiosyncratic (ρ>0 on a violent own-rally → mechanical/FOMO chase).
   Contextualizes every other reading.
4. **Steepener / flattener** (skew slope across strikes) — deferred (Tier 2): needs
   multi-strike surface + Greek management.
5. **Skew / put-skew harvesting** — real premium but **left-tail blowup** failure mode →
   surfaced as a *warning/context* metric only, never a trigger (aligns with no-naked-shorts).

Sign convention is **explicit**: equity RR = `IV(25Δ put) − IV(25Δ call)` (normally
positive for equities). The exact sign of the persisted UW `risk_reversal` field is
pinned in the implementation plan against a live sample before any classifier uses it.

## 4. Data availability (verified on the mini warm store, 2026-06-15)

Everything Track A and the Tier-1 validation need is already persisted — **no UW re-pull
for V1**:

| Series | Table | Depth |
|---|---|---|
| 25Δ RR skew (level + per-expiry history) | `risk_reversal_skew_history` | 115 tickers · 2025-05-13 → 2026-06-12 |
| ATM IV + RV + close price | `realized_volatility_history` | 116 tickers · 2025-05-12 → 2026-06-12 · IV 100% non-null |
| Smile per expiry | `iv_smile_snapshots` | 49 tickers · ~1 month |
| Borrow fee / short data | `short_interest_snapshots` (UW `/api/shorts/{ticker}/data` → `fee_rate`, `days_to_cover`) | latest per run (point-in-time current; limited history) |

Implication: for any snapshot date in 2025-05 → 2025-12 there is already a full **T+20
forward window on disk**, so Tier-1 markout is runnable now. UW
`historical-risk-reversal-skew` (params `date`, `expiry`, `timeframe`, `delta`; ~1yr
series per call) is a **depth-extension / new-ticker** path only, not a V1 prerequisite.

## 5. Architecture

Follows the Volatility-tab pattern: persisted raw → pure derivers → report assembler →
RSC tab → client island. Module-size budget respected (each new file < 500 lines).

### Backend
- **Deriver** `src/uw_scan/cards/skew_first_principles.py` — pure functions, no I/O:
  - `compute_spot_vol_rho(prices, ivs, window)` → ρ over 63d (primary) + 21d (fast).
  - `compute_skew_baseline(rr_history)` → z-score vs 180d, percentile vs 252d.
  - `classify_deviation(z, pct)` → `RICH | CHEAP | NORMAL`.
  - `classify_skew_term(front_rr, back_rr)` → `front_steep | back_steep | flat`.
  - `classify_drive(price_trend, rho_sign, bid_wing)` → `PANIC | CHASE | STRUCTURAL`.
  - `asset_class_baseline(ticker, tags)` → class + expected sign + typical depth.
  - `borrow_flag(fee_rate, days_to_cover)` → `hard_to_borrow | normal | unknown`.
  - `resolve_directional_lean(deviation_class, drive_class, asset_class, regime,
    borrow_flag, earnings_gate, verdict)` → `{lean: BULLISH_TILT | BEARISH_TILT | NEUTRAL,
    confidence: low|med|high, basis: text, express: defined_risk_structure}`. Pure:
    takes the matching pre-computed bucket `verdict` (loaded by the assembler — see the
    verdict store below) and applies the live gates. A non-neutral lean requires a
    `TRADABLE_*` verdict **and** `borrow_flag != hard_to_borrow` **and** no active
    earnings window; any gate failing forces `NEUTRAL` with the reason recorded in `basis`.
  - `build_read(signals)` → structured `{tail, rho_confirms, drive, deviation_class,
    class_context, borrow_context, earnings_gate, directional_lean, summary_line}`. The
    relative-value body is always interpretive; the `directional_lean` is the only field
    permitted to express direction, and only through `resolve_directional_lean`.
- **Storage** `src/uw_scan/storage/skew_analytics.py` + migration
  `src/uw_scan/storage/migrations/0XX_skew_analytics_snapshot.sql` (next free number).
  Two tables: the per-ticker-per-day `skew_analytics_snapshot` (§6) and a small
  **`skew_directional_verdicts`** store (the markout's per-bucket conclusions — what
  unlocks a non-neutral lean). Keying the verdict store: `(asset_class, deviation_class,
  drive_class, regime)` → `{verdict: TRADABLE_BULL | TRADABLE_BEAR | NONE, confidence,
  forward_sep, n, borrow_clean, survives_gate, as_of}`. Written by the validation/backfill
  job; read by the assembler and handed to `resolve_directional_lean` (keeps the deriver
  pure). Empty/absent verdict → lean is NEUTRAL, so the tab is safe before validation runs.
- **Report** `src/uw_scan/reports/skew_analytics.py` — stitch latest snapshot + history
  series + smile + structured read into the response; look up the matching row in
  `skew_directional_verdicts` and pass it into `resolve_directional_lean`; persist derived
  snapshot (standing "persist analytical results" rule).
- **Model** `src/uw_scan/models/skew.py` re-exported from `models/__init__.py`
  (preserve `__module__`, update `__all__`, run export/field/OpenAPI checks).
- **API** `GET /api/stock/{ticker}/skew` — read latest snapshot; live-compute fallback
  if missing/stale (mirrors the vol-tab pattern). Thin router → assembler.
- **Job** `src/uw_scan/worker/jobs/skew_analytics.py`:
  - `nightly_skew_analytics_rollup` — slot after the 18:00 vol rollup; iterate watchlist;
    one `basis='eod'` row per ticker per day; reads only warm store.
  - `skew_analytics_backfill(start, end)` — historical mode computing snapshots across
    the full ~13 months (for the Tier-1 validation set).
- **Markout harness** `src/uw_scan/reports/skew_markout.py` (or a focused worker job),
  mirroring `worker/jobs/trade_insight_outcome_backfill.py`: given
  `(ticker, market_date, bucket, spot)` join T+5/10/20 forward returns (+ forward RR /
  forward IV) from `realized_volatility_history.price`. Generic enough that Phase-2
  Tier 2/3 signals reuse it.

### Frontend
- `web/components/stock/tabs/SkewTab.tsx` (RSC) → `SkewTabClient.tsx` (client island).
- Panels (hand-rolled SVG, Argon tokens): posture tiles, **skew-history chart** with
  percentile bands + "you are here" marker, **ρ panel** (63d/21d tiles + mini ρ series),
  **skew term structure** (front vs back RR), reused `SmileChart`, **asset-class
  spectrum strip** (where the ticker sits, expected vs actual sign), **The Read** panel.
  The Read panel renders the relative-value body plus a distinct **Directional Lean**
  block: tilt badge (BULLISH/BEARISH/NEUTRAL) with confidence, the `basis` line, and —
  when non-neutral — the defined-risk structure that expresses it. NEUTRAL renders its
  reason (e.g. "not yet validated", "hard-to-borrow → borrow-fee confound", "earnings
  window") so the absence of a lean is legible, never blank.
- New `["skew", "Skew"]` entry in `web/components/stock/TabBar.tsx` between Volatility
  and Flow; route wired in `web/app/stock/[ticker]/[tab]/page.tsx`.
- After the model change: `cd web && npm run gen:types`, commit the `lib/types.ts` diff.

## 6. Persistence — `skew_analytics_snapshot` (markout-ready)

PK `(ticker, market_date, basis)`, `basis='eod'`, idempotent upsert
(`ON CONFLICT … DO UPDATE`). Columns:

| Column | Purpose |
|---|---|
| `spot` | anchor for forward-return join (markout-ready) |
| `rr_25d`, `skew_25d` | current level (sign convention pinned) |
| `rr_z_180d`, `rr_pct_252d` | deviation vs own baseline (the core signal) |
| `deviation_class` | `RICH \| CHEAP \| NORMAL` |
| `skew_term_class`, `front_rr`, `back_rr` | term structure of skew |
| `rho_spotvol_63d`, `rho_spotvol_21d`, `rho_sign` | spot-vol correlation |
| `drive_class` | `PANIC \| CHASE \| STRUCTURAL` |
| `asset_class`, `class_expected_sign` | asset-class baseline context |
| `borrow_flag`, `borrow_fee_rate`, `days_to_cover` | borrow/short context (JFE confound) |
| `earnings_gate` | whether an earnings/event window is active (`block \| pass \| unknown`) |
| `regime` | market regime label (`HIGH_VOL \| LOW_VOL \| UNKNOWN`) — the verdict-bucket key (added during planning) |
| `directional_lean` | `BULLISH_TILT \| BEARISH_TILT \| NEUTRAL` (evidence-gated) |
| `lean_confidence`, `lean_basis` | `low\|med\|high` + why the lean is what it is (incl. gate that forced NEUTRAL) |
| `read_summary` (text), `read_json` (jsonb) | the deterministic read (lean nested in `read_json`) |
| `inserted_at` | wall-clock write time |

Forward returns are **not** stored — computed in markout by joining price history on
`market_date + N`. The `spot`+`date` anchor is what makes the row markout-ready.

## 7. Tier-1 markout validation (folded into V1)

1. Backfill `skew_analytics_snapshot` across the ~13 months via
   `skew_analytics_backfill`.
2. Run the markout harness: bucket by `deviation_class` and `drive_class`; measure
   forward outcomes on two hypotheses:
   - **Primary — RV mean-reversion:** does extreme RR (RICH/CHEAP) revert? (forward ΔRR)
   - **Secondary — directional, borrow-conditioned:** do buckets separate forward stock
     returns **after** neutralizing/excluding hard-to-borrow names (`borrow_flag`)?
3. Apply the **per-regime catastrophic-degradation gate** (aggregate metrics hide
   regime blowups) and **web-validate** any empirical claim before it enters the UI.
4. **Persist per-bucket verdicts** into `skew_directional_verdicts`: a bucket earns
   `TRADABLE_BULL` / `TRADABLE_BEAR` only if its directional separation is material,
   holds on the borrow-clean subset (hard-to-borrow names excluded/neutralized), and
   survives the per-regime gate; otherwise `NONE`. These rows are precisely what unlocks
   a non-neutral `directional_lean` in The Read — the lean cannot exist without a verdict
   that cleared all three bars.
5. Output a research note under `docs/research/`. **Findings govern the read engine's
   allowed language**: relative-value body is always interpretive; the directional lean
   stays NEUTRAL unless backed by a `TRADABLE_*` verdict.

## 8. Phase 2 (deferred) — broader markout shortlist

All plug into the same markout harness. Tiered by current data depth:

- **Tier 2 (thin now, ~1mo — accrues forward or per-date UW backfill):** term-structure
  contango/backwardation (`iv_term_snapshots`), smile butterfly / RR-term
  (`iv_smile_snapshots`).
- **Tier 3 (not persisted as history → needs a backfill job first):** option flow
  BTO-sweep imbalance / OTM concentration (UW `flow-alerts`; doc 03's strongest claim),
  OI change / Vol-OI surge (UW `oi-change`), GEX / gamma-flip (UW `greek-exposure`
  history; only 3 tickers stored today).

## 9. Testing

- **Unit:** ρ on known series, z/percentile, all classifiers, read-text rules,
  asset-class map, borrow flag, markout join math, sign-convention guard.
  `resolve_directional_lean` gate matrix: verdict-absent → NEUTRAL; `TRADABLE_BEAR` +
  normal borrow → BEARISH_TILT; same verdict + hard-to-borrow → NEUTRAL (reason recorded);
  same verdict + active earnings window → NEUTRAL.
- **Integration (pytest-postgresql):** snapshot upsert + idempotency, backfill mode,
  endpoint shape, markout join on seeded forward closes, markout-readiness assertion
  (snapshot has spot+date sufficient to join forwards), verdict-store write/read +
  assembler wiring (seeded `TRADABLE_*` row surfaces as a non-neutral lean; no row →
  NEUTRAL).
- **Web:** vitest panels (deviation badge color, read rendering, ρ tiles, directional-lean
  badge + NEUTRAL-with-reason rendering); `gen:types` drift check.

## 10. Defaults (override anytime)

- ρ windows: 63d primary, 21d fast.
- Baseline: z vs 180d (matches `matrix_state` convention), percentile vs 252d (1y).
- Deviation thresholds: `RICH/CHEAP` when |z| ≥ 1.5 **or** percentile ≥ 85 / ≤ 15.
- Borrow flag: `hard_to_borrow` when `fee_rate` above a configurable threshold (pinned
  against the UW sample in the plan).
- Directional lean: NEUTRAL unless a `TRADABLE_*` verdict exists for the bucket; hard
  gates (borrow / earnings / regime) always override to NEUTRAL. Verdict "material
  separation" threshold pinned during the Tier-1 validation, not hardcoded blind.
- Tab placement: between Volatility and Flow; label "Skew".

## 11. Risks / open items

- **Sign convention** of the persisted `risk_reversal` field must be confirmed against a
  live UW sample before classifiers consume it (UW spec says "put − call"; one sample
  showed negative — pin it in the plan).
- **Borrow-fee history** is shallow (latest-per-run), so Phase-2 directional conditioning
  is cross-sectional/current rather than fully point-in-time — documented as a limitation.
- **Asset-class baseline** is a small static map seeded from watchlist tags
  (Macro/Credit/Sector-ETF) + explicit overrides; not derivable purely from the 20-tag
  taxonomy. Kept intentionally small (YAGNI).
- **Read engine** never emits a naked or unvalidated directional call. The directional
  lean is the only field allowed to express direction, and only via a `TRADABLE_*`
  verdict that cleared borrow/earnings/regime gates; everything it suggests is
  defined-risk. A bug that lets a lean appear without a backing verdict is a correctness
  failure (covered by a unit test asserting verdict-absent → NEUTRAL).
- **Lean over-trust:** even a validated lean is low/med confidence on decayed, in-sample
  effects. UI must show confidence + basis prominently and never present the lean as a
  high-conviction signal — it's a tilt, not a forecast.
