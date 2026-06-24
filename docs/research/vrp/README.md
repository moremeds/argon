# VRP — Macro Short-Vol Harvest (results)

**Final results of the volatility-risk-premium research line.** This README is the
distilled verdict; every number is `[COMPUTED]` from the saved traces in
[`_iterations/`](./_iterations/) (full reports, notebooks, CSVs, and the per-iteration
verdicts live there). Reproduce commands are listed at the bottom.

> **One-line verdict.** A defined-risk **bull put spread on SPX/SPY, sized by a VRP-z
> richness gate and held to expiry, is the first real, drawdown-robust edge in the whole
> VRP investigation — Sharpe ≈ 1.65 over 2006–2026 (incl. 2008/2020/2022). But on raw
> total return it only *matches* buy-and-hold SPY; the edge is a smoother ride and capital
> efficiency, so its role is a risk-adjusted sleeve / diversifier, not a return engine.**

---

## 1. The deployed signal (entry / exit rules)

`WINNER` in `src/uw_scan/reports/vrp_macro_signal.py` (promoted to tested engine code):

| Element | Rule |
|---|---|
| **Structure** | Bull put spread (defined-risk): **sell 0.25Δ put, buy 0.125Δ put** as the wing/stop |
| **Signal** | Index IV proxy = VIX/100 (QQQ→VXN, IWM→RVX); RV = 20d realized; **VRP = IV − RV**, z-scored over trailing 252d |
| **Entry cadence** | **Weekly** — a candidate every 5 trading days |
| **Entry gate** | `ramp+`: trade only when **vrp_z > 0**; size `w = clamp(vrp_z / 0.5, 0, 1)` (0 at z≤0, full at z≥0.5). *Vol must be rich to deploy.* |
| **Hold / exit** | **30 trading days (≈ 43 cal. days)**, held to expiry, settled at intrinsic. No profit-take, no stop — the long wing is the defined-risk floor |
| **Pricing (backtest)** | Flat-vol Black–Scholes (skew ignored → modeled put-spread credit is a **conservative floor**; real fills ≥ modeled) |
| **Δ knob** | 0.25Δ is the top-Sharpe, widest-cushion cell; 0.30/0.35Δ raise base return at ~equal Sharpe (a free return/cushion dial) |
| **Rejected** | **DTE=20** (the superseded original anchor — 0.92 vs DTE30's 1.07), 50% profit-take (hurts Sharpe 0.92→0.76), DTE=7 (flat-30d-IV artifact), CSP (ROR≈0), always-on (the gate beats it everywhere), IWM sleeve (drags) |

**Why 30 trading days, not 20.** [COMPUTED — `_iterations/macro-short-vol-verdict.md`] The
original hypothesis was an always-on **20-DTE** seller (Sharpe 0.92). The delta×DTE sweep then
promoted **~30 trading days (≈6 weeks, 40–45 calendar DTE)** as the sweet spot — *higher* Sharpe
**and** *shallower* drawdown than 20 (Δ0.25: DTE20 0.92 / maxDD −4.22 → DTE30 1.07 / −2.34).
DTE=7 screens highest of all but is a flat-30d-VIX pricing artifact; with constant-maturity 30d
VIX the clean band is DTE≈20–30, and 30 wins it. Neither later iteration (capital-utilisation,
robustness §2.5) re-opened this — both run hold=30. So "hold to expiry, ~30 trading days" is the
settled answer; **20-DTE is the rejected predecessor, not the target.**

**Live signal as of 2026-06-18 (mini): SKIP** — spot 7501, vrp_z **−1.95**, weight 0.00.
Vol is cheap, the gate is shut → stand aside. Confirms it's a rich-vol harvester, not an
always-on seller.

---

## 2. Metrics

### 2.1 Capital-blind return-on-risk (the canonical "1.65 Sharpe")

`backtest_laddered(SPX, WINNER)` — scale-invariant, constant-risk slots, no $ cap:

| Window | Sharpe | annROR | maxDD | Calmar | rungs |
|---|--:|--:|--:|--:|--:|
| **Full 2006→2026-06-18 (incl. 2008)** | **1.652** | 0.530 | −0.796 | 0.67 | 522 |
| 2009→2026-06-18 (excl. 2008) | 1.834 | 0.566 | −0.590 | 0.96 | 480 |

**1.652 is THE headline** (full history). Earlier "~2.0" readings were in-sample-flattered
cells — the saved trace pins the honest number at 1.65.

### 2.2 The $50k tradeable reality

Same WINNER run as a real **$50,000** cash account (integer contracts, capital-capped, idle
cash earns rf 4%, gross = excess + rf). `base_risk_pct` = fraction of $50k a full-size rung risks.

**SPX direct** (cash-settled, European, §1256; one spread ≈ $15.7k margin ≈ 31% of $50k):

| base_risk_pct | Sharpe | CAGR gross | util mean | skip% | win% | breach% | entries/yr |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.20 | 1.43 | 14.2% | 0.31 | 0.4% | 91% | 11% | 17.9 |
| 0.32 | 1.98 † | 16.6% | 0.49 | 14% | 93% | 9% | 18.9 |
| 0.50 | 1.87 | 17.7% | 0.61 | 31% | 93% | 9% | 17.1 |

**SPY direct** (same signal, 1/10th lump → granular, ~$1.7k margin):

| base_risk_pct | Sharpe | CAGR gross | util mean | skip% | win% | breach% | entries/yr |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 0.10 | 1.43 | 11.1% | 0.24 | 0% | 90% | 12% | 26.7 |
| **0.20** | **1.56** | **14.7%** | 0.49 | 0% | 90% | 12% | 27.6 |
| 0.35 | 1.63 | 16.4% | 0.64 | 16% | 91% | 12% | 23.7 |
| 0.50 | 1.62 | 17.1% | 0.70 | 26% | 91% | 11% | 20.8 |

† SPX/0.32's 1.98 is partly a capital-cap-as-quality-filter artifact (in-sample fragile);
the robust SPX read is **0.20 → 1.43**. `util_mean` caps ~0.7 because the ramp+ gate forces
idle cash in cheap vol — that idleness is the price of the edge.

### 2.3 Max drawdown — two different events

| Config | maxDD $ (abs) [when] | maxDD % of peak [when] |
|---|---|---|
| SPX direct, brp 0.20 | −$28,565 [2018-11] | **−49.8%** [2009-03] |
| SPX direct, brp 0.32 | −$39,291 [2009-03] | **−78.6%** [2009-03] |
| SPY direct, brp 0.10 | −$22,672 [2018-11] | **−18.4%** [2009-03] |
| **SPY direct, brp 0.20** | −$40,028 [2018-11] | **−41.0%** [2009-03] |

Biggest *%* hit is the **2009 GFC start** (sold puts into the crash, equity ≈ $50k → trough);
biggest *$* hit comes later at higher equity. Honest risk for the recommended SPY @ 0.20:
**≈ −41% of capital** (Mar-2009) or **≈ −$40k absolute** (Nov-2018).

### 2.4 Single-name decomposition — why a 3-name blend dilutes

Capital-blind ROR Sharpe under the winner config: **SPX ≈ 1.6–1.8**, **QQQ 1.00 (OOS — the
vrp-z gate *rescues* it from 0.27)**, **IWM 0.41 (−128% maxDD, choppy small-cap RV)**.
SPX+QQQ blends to ≈1.6 at little cost (QQQ is a genuine second sleeve); adding IWM drags the
book to ~1.0. **Single-name S&P wins; drop IWM.**

### 2.5 Iteration-4 robustness — is the edge overfit? (no)

Two iterations followed the WINNER and stress-tested it; this section folds both in. Each driver
re-runs (or resamples) the backtest hundreds of times — cells are the resulting **Sharpe
distribution** (`iter4-mc.csv`, SEED 20260623). Baseline = the iteration-3 SPX **$-account**,
weekly-stride **1.68** (the capital-blind laddered headline is **1.65** — §2.1; same engine,
different normalisation, do not conflate).

| Stress test | p5 | median | p95 |
|---|--:|--:|--:|
| Config-perturb (Δ 0.20–0.30, hold 20–40d, ramp_z 0.3–0.7) | **1.05** | 1.39 | 1.64 |
| Entry-day jitter | 1.19 | 1.37 | 1.60 |
| Block-bootstrap (resample monthly returns) | 1.05 | 1.67 | 2.54 |
| Random start year | 1.60 | 1.97 | 2.73 |
| Random start *inside* the 2007–09 GFC | 1.62 | 1.65 | 2.02 |
| SPY buy-and-hold (benchmark) | — | 0.62 | — |

- **Not a knife-edge config.** Perturbing the tuned knobs (incl. hold 20–40d) holds Sharpe at
  **p5 1.05**; every distribution sits far above SPY buy-hold (0.62). The edge survives the config
  search that produced it — it is not an artifact of the exact winner cell.
- **Entry weekday is second-order — Tuesday best, but don't pin it.** Single-weekday Sharpes span
  **1.33 (Fri) → 1.53 (Tue)**, *all below* the natural 5-day stride (**1.65**). Tuesday is the best
  fixed day, but committing to any one weekday is slightly *worse* than letting the weekly cadence
  diversify day-of-week exposure. Edge stays >1.3 every day → **keep the weekly stride; Tuesday only
  matters if you must pin a day.**
- **Starting at a bear-market top *helps*.** Every post-shock start beats full history (Sharpe
  **1.87–2.58 vs 1.68**, +150–180% over 36 months) — selling elevated post-crash vol harvests the
  richest premium on the recovery. (The entry-day drawdown risk below still applies if you are
  *already* positioned when the shock hits.)
- **"Extra set when rich" is leverage, not edge — two independent tests agree.** Iteration-4
  (single $143k account): the same-day **contract overlay** marginally *hurts* Sharpe (1.668 vs
  1.680), the **staggered tranche** barely helps (1.705), both deepen drawdown ~$40k.
  Capital-utilisation ($50k, SPY/QQQ/IWM): the overlay lifts gross return 0.474→0.605 but Sharpe is
  flat-to-down (1.06→1.05) and maxDD blows **past total capital** (−1.012 of $50k). Only a
  *tightly-gated* overlay (rich_threshold ≥1.5, fires rarely) nudges Sharpe up (1.06→1.18).
  **`base_risk_pct` is the only real lever; skip the overlay.**
- **The real risk is utilisation, not the signal.** At 20%/spread × ~6 concurrent rungs the book
  runs ~100% deployed (`util_peak` 1.00), so 2008 takes a **−90% drawdown on the base and >−100%
  on the extra-position arms** (a brief ruin event) — the capital-blind Sharpe completely hides
  this. Size **≤ ~16%/spread** to stay under the cap.
- **Capital reality — a six-figure strategy.** SPX spread max-loss rises **~15× over 2007→2026**
  with spot; the honest *trade-throughout* account is **~$143k at 20% risk** (a $10k-start book goes
  dormant by ~2015, unable to afford a modern spread). SPY (~$1.7k/spread) is the small-account vehicle.
- **Compounding vs non-compounding.** Non-compounding (fixed % of the *original* capital) is the
  honest book. Compounding lifts CAGR to ~57% but *lowers* Sharpe (1.68→1.46) and scales the dollar
  drawdown to the (enormous) equity — a ruin mirage (see §3 for the safe sub-linear cap).
- **The 2008 breach lesson.** The three big losses (of **470 fills, 91.1% win, 11.3% breach,
  +$1.47M** total) were **late-May/early-June 2008 entries at VIX 17–18** — vrp_z was positive (rich
  vs the trailing year) but **absolute** vol was low, right before the summer plunge. Selling
  "rich-vs-trailing" does **not** protect against a low-absolute-vol regime that then cracks — the
  direct case for the regime kill-switch (§5.3).

---

## 3. Equity curve vs buy-and-hold

![Equity vs buy-and-hold SPY](./equity-curve.png)

Headline, 2009 → 2026-06 (mini), $50k start:

| Curve | terminal equity | CAGR | maxDD % of peak |
|---|--:|--:|--:|
| **Short-vol SPY 0.20 (non-comp)** | $490,109 | 14.1% | −41.0% (2009 GFC) |
| Buy & hold SPY (price only) | $499,912 | 14.2% | **−24.8%** (2022) |
| Short-vol SPX 0.32 (non-comp, aggressive) | $646,716 | 15.7% | −78.6% (2009 GFC) |

**The humbling read.** The non-compounding SPY-0.20 book ≈ buy-and-hold SPY on total return
($490k vs $500k) — and on a *fair* basis (buy-hold **+ ~1.8%/yr dividends** vs short-vol + rf
on ~half-idle cash) buy-hold likely **wins** on raw return, while also having a **shallower**
drawdown (−25% vs −41%). The short-vol edge is the **smoother monthly ride** (Sharpe ~1.56 vs
~0.7) and **capital efficiency** (~half the $50k sits free, available for other sleeves), **not**
raw return or drawdown. (The 2009–2026 bull window flatters buy-hold and the $50k ledgers
exclude 2008.)

**Compounding is a ruin trap.** Sizing each rung off *current* equity turns 14%→55% CAGR on
paper ($490k → $100M) but deepens maxDD to **−64%** (the XIV / Feb-2018 Volmageddon dynamic)
and is un-realisable (SPY put-spread capacity won't scale to $100M). The safe middle ground is
**sub-linear compounding capped at ~$200k–$400k (4–8×)**: captures most of the uplift (CAGR
15.7% → 24–29% on SPX) while bounding the *forward* (2011+) drawdown to −7% to −10%.

---

## 4. Conclusion

1. **Real, drawdown-robust edge** — clears its breakeven over 20 years including 2008/2020/2022;
   the conservative flat-vol model *understates* the put-spread credit. **Monte-Carlo-robust**
   (Sharpe p5 **1.05** under config/timing perturbation — §2.5), not a single overfit cell.
   Settled structure: **~30-trading-day** hold (DTE20 was the rejected predecessor, §1).
2. **Tradeable on $50k two ways, both single-name S&P:** SPX direct (best Sharpe 1.4–2.0, lumpy
   at ~31%/contract, ~19 entries/yr) or **SPY direct** (Sharpe 1.43–1.63, granular, ~27/yr — the
   pragmatic small-account vehicle).
3. **It does NOT beat buy-and-hold on raw return** — it matches it with a smoother ride. Treat it
   as a **risk-adjusted sleeve / diversifier**, sized to a drawdown you can survive — not a
   standalone return engine.
4. **`base_risk_pct` is the only real lever** (trades CAGR for drawdown + skip-rate). The "extra
   set when very rich" overlay is **leverage, not edge** (Sharpe flat — confirmed by two
   independent tests, §2.5). The binding constraint is **utilisation**: size ≤ ~16%/spread or the
   2008 cap breach turns into ruin.
5. **Recommended deployable:** SPX at `base_risk_pct ≈ 0.20–0.32`, sub-linear compounding capped at
   ~$200k–$400k, gate `ramp+`, **drop IWM**. Or SPY @ 0.20 for granularity on a small account.

**Promoted to engine.** `vrp_macro_signal.py::WINNER` reproduces the headline cell bit-for-bit
(SPX Sharpe 1.6524, maxDD −0.7960, n=522). Library only — **not yet scheduled/persisted/surfaced**.

---

## 5. Can we improve it? (next steps, ranked)

The research left the edge *modeled-robust but un-traded*. Highest-value improvements, all grounded
in flagged gaps — confidence noted, none yet run:

1. **Reprice the backtest off argon's real captured IV surface, not flat VIX.** [INFERRED, HIGH]
   The single biggest caveat is flat-vol BS (skew ignored). argon now durably records a full-chain
   IV grid (`option_surface_capture`, migrations 077/078). Re-running the harvest priced off the
   *real* per-strike/expiry surface would (a) tighten the put-spread credit from "conservative
   floor" to actual, and (b) finally settle whether the **iron condor's** +0.156 ROR is real or a
   flat-vol call-side artifact — the one open structural question. This is the cleanest win and the
   data already exists.

2. **Build the forward NBBO recorder.** [KNOWN gap, HIGH] Every verdict names this as *the* remaining
   gap between "robust in a conservative model" and "traded." Real-fill bid/ask is the only thing the
   flat-vol model can't supply; the single-name condor died precisely because its edge sat *inside*
   one leg's spread (±$0.09/share flipped the sign).

3. **Cross-wire the regime indicators as a kill-switch / second gate.** [INFERRED, MED] The vrp-z gate
   is purely a *richness* gate; it has no *regime* veto. The `regime/` research already computes
   VIX/VIX3M term structure, CRI, and VCG — and `regime/guidance.md` literally says
   *"elevated_backwardation → no new short-vol."* Testing a term-structure / CRI-CRITICAL / VCG-PANIC
   veto on entry directly addresses the **untested kill-switch hypothesis** flagged in iteration 4,
   and is the most plausible way to cut the −64% compounding tail (flatten before the crash that kills
   short vol, rather than sizing *into* it).

4. **Get an honest 2008 dollar-drawdown.** [KNOWN gap, MED] The $50k ledgers start 2009-01-01 — they
   exclude the worst tail. The capital-blind series already spans 2006; re-running the dollar ledger
   from 2006 would replace the cap-invariant −63.6% (a 2009-start artifact) with a real
   GFC-through-the-account number. Cheap, and it's the most honest risk figure we're missing.

5. **Signal-driven early exit (not a static take).** [GUESS, LOW] The 50% profit-take was rejected, but
   a *different* idea is untested: close when the harvest is realized — i.e. when vrp_z mean-reverts
   below 0 mid-hold (the richness that justified the trade is gone). Distinct from a fixed % take; may
   recover the gamma/assignment benefit the static take forfeited. Low confidence — easily a wash.

> Items 1–3 also *connect the three research lines in this folder*: the VRP harvest, the captured
> option surface, and the regime indicators are currently siloed. The highest-leverage version of this
> strategy is the bull put spread **priced off the real surface** and **gated by both richness (vrp-z)
> and regime (term structure / CRI / VCG)**.

---

## 6. Reproduce / artifacts

All artifacts live in [`_iterations/`](./_iterations/). Repro commands (write back into `_iterations/`):

| What | Command |
|---|---|
| Param sweep (verifies the 1.65 numbers) | `uv run python scripts/_vrp_macro_param_sweep.py` |
| $50k 3-name capital sweep → `capital-sweep-results.csv` | `uv run python scripts/research/vrp/vrp_capital_sweep.py` |
| Iteration-4 robustness CSVs | `uv run python scripts/research/vrp/vrp_robustness_run.py` |
| Full trade log → `iter4-trade-log.csv` | `uv run python scripts/research/vrp/vrp_trade_log.py` |
| Rebuild findings notebooks | `scripts/_build_vrp_*_notebook.py` |

**Full detail:** [`_iterations/MASTER-macro-short-vol-capital-utilisation-2026-06-23.md`](./_iterations/MASTER-macro-short-vol-capital-utilisation-2026-06-23.md)
(comprehensive report) and the per-iteration verdicts
([`macro-short-vol-verdict.md`](./_iterations/macro-short-vol-verdict.md) — the 1.65 winner origin;
[`macro-capital-utilisation-verdict.md`](./_iterations/macro-capital-utilisation-verdict.md) — $50k ledger;
[`single-name-condor-verdict.md`](./_iterations/single-name-condor-verdict.md) — the parked condor that
motivated the macro pivot).

**Engine code (not in this folder):** `src/uw_scan/reports/vrp_macro_signal.py` (`WINNER`,
`current_macro_signal`), `vrp_macro_drawdown.py`, `vrp_capital_account.py`.

## 7. Forward entry-capture markout dataset (live, since 2026-06-24)

Sections 1–6 tell you *whether* to sell vol. This dataset records *what the fill
actually was* and *how it marks out* to expiry — the real forward NBBO + greeks of
the SPX bull-put-spread the signal would place, tracked daily. It is the durable
research artifact (standing rule); query it directly via SQL/notebook.

**Tables** (migration `085`):
- `vrp_macro_entry` — one cohort header per born entry (the 4 put contracts
  bracketing the 0.25Δ short / 0.125Δ wing at the ~43-cal-DTE expiry). `origin` is
  `auto` (one/day, idempotent per `(name, birth_date)` via a partial unique index)
  or `button` (on-demand one-shot from the regime card; never re-snapshotted).
- `vrp_macro_entry_quote` — the time series: every open `auto` cohort's 4 legs
  snapshotted at **8 marks/day** (10:00–15:00 ET hourly + 15:55 EOD + 16:10
  post-close), tapering to EOD-only after `vrp_macro_entry_taper_calendar_days`
  (30) held, until expiry. PK `(entry_id, as_of, leg)`.

**Provenance columns — filter on these:**
- `source` ∈ `{xenon_ib, uw}` — where the **NBBO + marked IV + underlying spot**
  came from. xenon/IB is primary (true NBBO + IV via xenon's `/options/greeks`);
  UW is the delayed fallback (`/option-contracts?expiry=` — NBBO + IV, no greeks).
- `greeks_source` ∈ `{bs, none}` — greeks are **always BS-computed** from the
  marked IV (one-model consistency: IB theta is per-*day*, BS per-*year* — storing
  source greeks would corrupt the markout series). `bs` = a real IV was present;
  `none` = IV absent → greeks are degenerate `0.0` (filter these out). The
  `delta/gamma/vega/theta` columns are always BS, never the source's native greeks.
- `source_asof` — the provider's own timestamp (UW delay); null on the IB path.

**Reproduce** (one real mark via the real worker path — the scheduler fires this
8×/day on massive-0, gated by `vrp_macro_entry_capture_enabled`):
```bash
uv run --frozen python -c "
from uw_scan.config import Settings
from uw_scan.worker.scheduler import _repo
from uw_scan.worker.jobs.vrp_macro_entry import vrp_macro_entry_snapshot_once
s = Settings.from_env()
with _repo(s) as repo:
    print(vrp_macro_entry_snapshot_once(repo, s, session='rth', birth=True))
"
# audit which feed actually quoted each leg:
#   SELECT source, greeks_source, count(*) FROM uw_scan.vrp_macro_entry_quote GROUP BY 1,2;
```
The IB-primary path needs `XENON_QUERY_API_KEY` in the **worker** env (the URL now
defaults to the mini's authenticated `http://127.0.0.1:8321`) — without the key every
leg silently falls back to `source='uw'` (the never-raise quoter swallows the 401).
Set the key once in the mini's argon `.env` (same value as xenon's `/opt/xenon/.env`).

**Live-verified 2026-06-24** (real prod IB, real `vrp_macro_entry_snapshot_once`):
SPX 2026-08-07, 3/4 legs `source=xenon_ib` — 0.25Δ short K7100 @ 75.6/76.8 (BS
δ −0.247), 0.125Δ wing K6800 @ 39.1/40.1 (BS δ −0.129, IV 0.230 vs short 0.196 =
visible put skew); the deep K6775 wing (unlisted) fell back to `uw`/`none` cleanly
without dropping the cohort's other 3 legs.

**Code:** `reports/vrp_macro_entry.py` (`resolve_entry_contracts`, `quote_leg`) +
`worker/jobs/vrp_macro_entry.py` + `storage/vrp_macro_entry.py` +
`api/routers/regime.py` (`/vrp-macro-signal/entry/{preview,capture}`) +
`web/components/regime/MacroShortVolCard.tsx`. Plan:
[`docs/superpowers/plans/2026-06-24-vrp-macro-entry-capture.md`](../../superpowers/plans/2026-06-24-vrp-macro-entry-capture.md).

---

## 8. Per-spread income & capital requirements (2026-06-24)

> **Context.** What does 1 SPX bull put spread actually earn, and how much capital
> do you need to run the full 6-slot book? Scripts in `scripts/research/vrp/` answer
> this concretely. All numbers: WINNER config, 2007–2026, 631 entries, ramp+ gate,
> 1% half-spread slippage + $0.65/leg commission (round-trip), SPX margin $17,500/spread
> (live at SPX ~7,446, 2026-06-24).

### 8.1 Exit variant — what you actually capture

Three hold periods on the same entries (`vrp_side_by_side.py`):

| Metric | 15 trd DTE exit | 15 cal DTE exit | **Hold to expiry** |
|---|--:|--:|--:|
| Hold duration | 15 trading days | 20 trading days | 30 trading days |
| Avg entry credit | $1,645 | $1,645 | $1,645 |
| **Avg captured at exit** | **$501** | **$634** | **$922** |
| Capture ratio | 30.4% | 38.5% | **56%** |
| Win rate | — | — | **87.8%** |
| Breach rate (short hit) | — | — | 35.2% |
| Avg monthly income (1 spread) | $1,450 | $1,836 | **$2,669** |
| Best month | — | — | ~+$10,000 |
| Worst month | — | — | −$51,319 |
| Annual income (1 spread) | $17,400 | $22,000 | **$32,000** |

**Key takeaway.** The 15-DTE early exit captures only 30% of credit because you're buying
back both legs with ~15 trading days of vol still embedded. The strategy is designed to
hold to expiry — the long wing's time-value decay is *the* P&L driver. Exiting early
forfeits most of it.

**Max concurrent slots.** Hold 30td ÷ cadence 5td = **6 slots max** (confirmed in backtest:
all 6 were simultaneously open during 2007-05-16). With the ramp+ gate firing ~36% of
weeks, *average* simultaneous open positions is 2–3.

### 8.2 Capital ladder — what you need to deploy

`scripts/research/vrp/vrp_capital_ladder.py` — hold to expiry, slippage included:

| Capital | Contracts @ brp 0.20 | Monthly income | Annual income | CAGR | Sharpe |
|--:|--:|--:|--:|--:|--:|
| $60,000 | 0 ← **can't trade** | — | — | — | — |
| $100,000 | 1 | ~$3,400 | ~$41k | 14.0% | 1.39 |
| $143,000 | 1 | ~$3,600 | ~$43k | 14.0% | 1.39 |
| **$200,000** | **2** | **~$6,800** | **~$82k** | **14.4%** | **1.42** |
| $300,000 | 3 | ~$10,200 | ~$123k | 14.5% | 1.43 |
| $400,000 | 4 | ~$13,600 | ~$163k | 14.6% | 1.43 |
| $600,000 | 6 | ~$20,400 | ~$245k | 14.7% | 1.43 |

Monthly income = `ann_return_gross × capital / 12`. Sharpe stabilises at ~1.43 above
$143k (enough contracts to express the full signal). At **brp 0.32** you get 1 more
contract per tier and ~0.4% higher CAGR at the cost of deeper drawdown (−79% GFC vs
−50%). The **$143k floor** is the minimum to trade throughout as SPX grows; $60k can
no longer afford even 1 contract at brp 0.20 with SPX at 7,400+.

### 8.3 $1M case — slippage impact

`scripts/research/vrp/vrp_1m_slippage.py` — what a $1M deployment looks like:

| brp | Contracts/entry | Monthly | Annual | CAGR | Sharpe | Skip% |
|--:|--:|--:|--:|--:|--:|--:|
| **0.20 ★** | **11** | **$53,200** | **$639k** | **14.7%** | **1.72** | **0%** |
| 0.32 | 18 | $67,100 | $805k | 16.0% | 1.65 | 11.2% |
| 0.50 | 28 | $76,700 | $920k | 16.7% | 1.48 | 24.5% |

**Slippage drag is flat 7.4% of gross** regardless of brp (~$47k/yr at brp 0.20).
It does not worsen with scale because the per-leg cost is a fixed % of the mid-price.
At brp 0.20 you can deploy all 11 contracts without skipping any entries (skip 0%).
At brp 0.50 the ramp+ gate causes a 24.5% skip rate — the gate fires less frequently
when the sizing is aggressive relative to buying power.

Max margin at full 6-slot deployment: **6 × 11 × $17,500 = $1,155,000** — effectively
100% deployed at peak. Size your account to survive a −50% drawdown before sizing for
income (see §2.3).

### 8.4 Reproduce commands

```bash
# All four scripts below; run on mini for freshest data
BASE="UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard UW_SCAN_DB_USER=argon_app UW_SCAN_API_KEY=x"

# Exit variant comparison (3 hold periods, capital scaling)
eval $BASE uv run python scripts/research/vrp/vrp_side_by_side.py

# Capital ladder ($60k → $600k, brp 0.20 / 0.32)
eval $BASE uv run python scripts/research/vrp/vrp_capital_ladder.py

# $1M case, slippage impact (brp 0.20 / 0.32 / 0.50)
eval $BASE uv run python scripts/research/vrp/vrp_1m_slippage.py

# Single spread, 15-DTE mid-hold exit (reference / curiosity)
eval $BASE uv run python scripts/research/vrp/vrp_one_spread_15dte.py
```
