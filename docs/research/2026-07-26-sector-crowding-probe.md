# Sector crowding probe — absolute vs per-ETF percentile

**Date:** 2026-07-26 · **Data as of:** 2026-07-24 (UW), iv_rank 2026-07-25
**Source framework:** https://x.com/bitfool1/status/2079479920162734401 (板块拥挤度, 2026-07-21)

**Reproduce:**

```bash
uv run python scripts/research/sector_crowding_probe.py
```

Writes the full result set to `docs/research/2026-07-26-sector-crowding-probe.json`.

## The framework as stated

Three legs, conjunctive — 三者同时出现，才算真正拥挤:

1. 3-month return relative to SPY
2. 1-month net flow ÷ AUM, banded `<2%` normal / `2–5%` warm / `>5%` crowded / `>10%` extreme
3. NTM P/E level and expansion

## Result

```
SOXX: dropped 1 unmatched session(s)
SMH: dropped 1 unmatched session(s)
IGV: dropped 1 unmatched session(s)

SPY 3M return: +3.79%
unmatched sessions dropped across the universe: 3

ETF      AUM$B  3M vs SPY   pctile  1M flow/AUM   relSD
-------------------------------------------------------
SOXX      45.5    +53.69%      97%      +21.46%    12.9
SMH       67.0    +17.88%      46%       +1.91%    13.8
XLK      178.5     +9.09%      70%       +0.28%    10.1
XLV      161.4     +6.50%      79%       +0.52%     7.9
XLF       55.8     +3.14%      99%       +4.98%     3.5
XLI      182.0     +2.58%      64%       +0.07%     7.1
XLE       59.4     +1.23%      51%       -0.55%    16.5
XLRE      44.9     -0.36%      63%       +0.74%     5.5
XLU       46.2     -0.85%      61%       +0.50%     8.7
XLP       83.2     -2.45%      57%       +0.28%     9.2
XLB       50.3     -6.76%      39%       +0.74%    11.1
IGV       11.7     -7.32%      69%       -8.27%     9.4
XLY      108.8    -12.34%       0%       +0.28%     3.1
XLC      105.4    -14.40%      11%       -0.53%     5.7

ABSOLUTE ranking:   SOXX > SMH > XLK > XLV > XLF > XLI > XLE > XLRE > XLU > XLP > XLB > IGV > XLY > XLC
PERCENTILE ranking: XLF > SOXX > XLV > XLK > IGV > XLI > XLRE > XLU > XLP > XLE > SMH > XLB > XLC > XLY
```

`unmatched sessions dropped: 3` is the expected steady state, not a warning —
one session each for SOXX, SMH and IGV that SPY does not carry (see "Data
limitations" below). Every fixture frozen into the test suite reproduces from
this run exactly, so the date-join and the module agree.

## Finding: leg 1 cannot use the absolute spread

The trailing SD of the 3M SPY-relative spread ranges from 3.1 (XLY) to 16.5
(XLE). Ranking the universe on the raw spread therefore ranks volatility, not
crowding — a high-beta sector tops the table in any up-tape.

The two rankings genuinely disagree:

- absolute: `SOXX > SMH > XLK`
- self-percentile: `XLF > SOXX > XLV`

XLF at +3.14% is its own 99th percentile and the absolute method buries it at
rank 5. SMH at +17.88% is only its own 46th and the absolute method promotes it
to rank 2.

So leg 1 scores on the ETF's own trailing percentile. Leg 2 keeps the source
framework's absolute bands, because dividing by AUM already removes the size
effect — that normalization is what makes those thresholds comparable across
funds in the first place.

## Data limitations found

- **UW `aum` is mixed-unit.** Billions for the 12 SPDR sector ETFs
  (`XLK` → `180.775642`), raw dollars for everything else
  (`SOXX` → `45064294868`). Both landed unconverted in `etf_aum_cache`.
  Fixed in this change by `normalize_etf_aum`, applied on read and write.
  The watchlist card's `aum` is a different read path
  (`scan_runs.aggregates` → raw `etf_info` payload) and is still unnormalized.
- **ARKK has no flow data.** `/api/etfs/ARKK/in-outflow` returns 0 rows
  (verified 2026-07-24), so it is excluded from the universe.
- **UW in-outflow coverage is uneven, and position-alignment is unsafe.**
  Over 2025-07-01 → 2026-07-24 the 11 SPDR sector ETFs and SPY each return
  267 sessions, but `SOXX`/`IGV` return 238 and `SMH` returns 204 — and each
  of the three carries one session SPY does not have. An earlier draft of this
  probe aligned the ETF and benchmark series **by list position**, which for
  those three compares different dates at every index. Date-joining moves the
  numbers materially:

  | ETF | 3M rel (position) | 3M rel (date-join) | pctile (position) | pctile (date-join) |
  |---|---|---|---|---|
  | SOXX | +50.26% | **+53.69%** | 96% | **97%** |
  | SMH | +12.67% | **+17.88%** | 18% | **46%** |
  | IGV | −1.18% | **−7.32%** | 86% | **69%** |

  The 11 SPDRs are unaffected (identical to 2 dp). `reports/sector_crowding.py`
  and this probe both inner-join on `obs_date`; the probe prints the dropped
  count so a future regression is visible.
- **The benchmark leg has to be joined too, not just the ETF leg.** Caught on
  the first live run of this script (2026-07-26). The probe joined `rows` to
  SPY by date but then subtracted SPY's *own* last-63-rows return — a single
  number for the whole universe — instead of the benchmark's return over each
  ticker's aligned window. For the 11 SPDRs those are the same number, so it
  looked correct; for SOXX and IGV it compared a ~135-day ETF return against a
  ~92-day SPY return and overstated the spread by 5.22 points each
  (SOXX `+58.91%` / 99th, IGV `−2.10%` / 87th). Worse, `rel_hist` two lines
  below already joined correctly, so today's value was being scored against a
  history computed a different way. `reports/sector_crowding.py` never had this
  bug — it has always used `_window_return(bench, last, RETURN_WINDOW)` on the
  joined list. Fixed in the probe; the table above is post-fix and reproduces
  every frozen test fixture.
- **A 63-row window is not 3 calendar months for every ETF.** Because of those
  same coverage gaps, the last 63 observations span 92 calendar days for SPY,
  XLK, XLY and SMH but **135 days for SOXX and IGV** (measured 2026-07-26). The
  date join makes each ETF's spread an honest ETF-minus-SPY comparison over its
  own available sessions, and leg 1 is scored against that ETF's own trailing
  history, so the *score* is self-consistent. The *raw* number labelled "3M" is
  not directly comparable across tickers. Moving leg 1 to a calendar-anchored
  window would fix the label; it is deliberately out of scope here and is
  flagged as an open question.

## Leg 3: substituted, not implemented as stated

ETF NTM P/E needs Σ(weight × constituent forward EPS). UW exposes no forward
estimates and massive/Polygon fundamentals are trailing. The source framework's
own screenshot shows SOXX NTM P/E behind a "🔒 Upgrade" gate, so it is not
sourceable on our tier at any effort.

Substituted: **iv_rank spread vs SPY**. Free from `watchlist_card`, and it asks
the same question — is the crowd paying up — about convexity instead of
earnings.

## Deferred: trailing P/E from holdings

Buildable, not built. It would need a constituent-weights table, a fundamentals
sweep over ~500 names against the 86 currently in `massive_fundamentals`, and a
nightly job to keep both fresh.

Worse than the cost, it would be **trailing**, not forward. Trailing P/E *falls*
while a sector gets more crowded during an earnings upcycle — the precise case
the source framework uses the forward measure to catch. A trailing proxy would
read "cheapening" exactly when the leg is supposed to fire, which is worse than
having no third leg. Revisit only with a real forward-estimates source.
