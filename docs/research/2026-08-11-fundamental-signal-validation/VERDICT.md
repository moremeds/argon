# VERDICT — the ranked composite does not work; ship the descriptive card

*2026-08-11 · hand-written, not regenerated · numbers in `results.md` / `validation.json` ·
reproduce: `UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_signal_validation.py`*

Run **before** P1b built any ingest, on the reasoning that the whole dataset sits behind ~100 API
calls and it is cheaper to test a method than to build storage for one that may not work.

## The headline

**The §5.2 composite has no predictive content in this cohort.**

| Horizon | mean IC | t-stat | hit rate | quarters |
|---|---:|---:|---:|---:|
| 1 quarter | **−0.0132** | −0.34 | 46.8% | 77 |
| 2 quarters | **−0.0089** | −0.21 | 48.7% | 76 |

A hit rate below 50% and a t-stat inside ±0.4 is not a weak signal — it is the absence of one. **Do
not ship a ranked composite.** That was already the recommendation on breadth grounds; it is now
measured rather than argued.

## The more interesting result: two components are significantly inverted

| Signal | 1q IC | t | 2q IC | t | spec direction |
|---|---:|---:|---:|---:|---|
| `asset_turnover` | **−0.155** | **−4.30** | −0.086 | −2.34 | higher better |
| `op_margin` | −0.073 | −2.14 | **−0.108** | **−3.06** | higher better |
| `rev_growth` | +0.024 | 0.69 | +0.042 | 1.07 | higher better |
| `neg_net_debt_ebitda` | +0.038 | 0.89 | +0.019 | 0.47 | higher better |
| `gross_margin` | +0.001 | 0.03 | −0.007 | −0.19 | higher better |
| `roe` | −0.037 | −0.98 | −0.043 | −1.18 | higher better |
| `fcf_margin` | −0.014 | −0.40 | −0.003 | −0.06 | higher better |

Two of §5.2's declared directions are **backwards** over this window, and not marginally so. The
composite reads as null partly because inverted components cancel against flat ones.

**The economic story is coherent, which is exactly why it should be distrusted.** Low asset turnover
means a large asset base relative to revenue — the names building fabs and data centres. Low
operating margin means room to expand rather than margin already harvested. Over 2013–2025 in this
cohort, *the companies investing beat the companies harvesting.* That is a clean description of the
AI capex buildout.

It is also a **regime description, not an edge**. It says what happened in the sample; it gives no
reason to expect the same in the next regime, and a capex cycle that turns would reverse it. Under
the spec's own post-hoc test — would the frame have predicted this without knowing the outcome? —
the answer is no.

## Why even the negative results are contaminated

**The universe is survivorship-selected.** These 25 names were chosen because they are *today's* AI
supply chain. Testing what predicted their 2013–2025 returns asks which characteristics preceded
success among companies already known to have succeeded. NVDA in 2010 was not obviously going to be
NVDA in 2026, but the sample assumes it. This inflates any relationship between "was investing
heavily" and "went up", because the names that invested heavily *and failed* are not in the cohort.

Three further limits, all recorded rather than worked around:

- **Cross-section is thin**: median 11 names per quarter (min 8, max 14), not 25 — the deep-history
  names carry the early quarters.
- **Quarterly ICs are not independent.** The t-stats treat 77 quarters as 77 observations; in one
  correlated industry with overlapping TTM windows they are worth materially fewer. Read t = −4.3 as
  "clearly not zero", not as a precise confidence level.
- **PIT is partial**: 460 of 874 observations carry a real `filing_date`; the rest are lagged 45 days
  from period end. The lag errs late, so it cannot manufacture signal, but it blurs timing.
- **3 of 25 tickers have no price data** locally (VRT, VST, NOW) and PLTR's history is truncated —
  the local lake mirror is incomplete and ~3 months stale. The mini holds the full copy and was
  unreachable during this run.

## What this changes

1. **Do not ship a ranked composite or a sortable score.** No evidence supports ordering these names
   against each other on fundamentals.
2. **Ship the descriptive card** — per-subscore values, trends, and absences, presented as context
   beside the options surface. That was option 2 of three; it now has evidence behind it rather than
   a sample-size argument.
3. **Fix or drop the two inverted directions.** §5.2 asserts "higher better" for `op_margin` and
   `asset_turnover` as declared priors. The data contradicts both. Since the inversion is best
   explained as a regime artifact, the honest move is to **drop the direction claim** and render the
   levels and trends without a good/bad verdict — not to flip the sign and claim an edge.
4. **P1b remains worth building** for the descriptive surface. Nothing here argues against ingesting
   the data; it argues against ranking on it.

## What would change the verdict

- A **non-survivorship universe** — the AI chain as it looked at each point in time, including names
  that dropped out. This is the single biggest fix and it is not cheap.
- **Breadth**: 200+ names across sectors, where cross-sectional rank has something to work with.
- A **time-series** framing instead of cross-sectional: does a name's own fundamental deterioration
  precede its own drawdown? That question is untouched here and is not survivorship-contaminated in
  the same way, because each name is compared against itself.

The third is cheap and is the obvious next test if anyone wants to keep pulling this thread.
