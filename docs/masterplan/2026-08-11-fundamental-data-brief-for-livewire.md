# Fundamental data — requirements brief for livewire

*Written 2026-08-11 by argon · every number below is measured, with a reproduce command · consumers: livewire (ingestion), argon (fundamental PM agent, spec `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`)*

---

## Executive summary

argon is building a fundamental analytics layer over 25 AI-supply-chain names. Two weeks of source probing produced one conclusion that should change livewire's plan, and several that should change how it ingests.

**The headline: Unusual Whales, which we already pay for, is a materially better fundamentals source than massive — and nobody in the stack had checked.**

|  | UW | massive `/vX` |
|---|---|---|
| Tickers covered (of 25) | **25** | 23 |
| Ticker-quarters | **1,673** | 1,092 |
| History starts | **2005–2006** | 2009–2010 |
| Negative liabilities | **0.2%** | 5.1% |
| Impossible share counts | **0.0%** | 15.1% |
| Currency tagging | **explicit per row** | per-leaf XBRL unit |
| Capex, EBITDA, D&A, cash, total debt, SBC | **100% of cohort** | **absent entirely** |

The two names massive cannot cover — TSM and ASML — return 83 quarterly rows each from UW, through 2026-06-30, tagged `TWD` and `EUR`. Where both sources have data they agree: 16/16 fields exact for NVDA, MSFT, AMAT, MU, AVGO.

**Three things livewire should take away:**

1. **Ingest UW fundamentals as a new bronze asset class.** It is strictly better than the alternative on every axis measured, and it is already inside our existing subscription and budget.
2. **An integrity gate is not optional.** massive `/vX` serves GOOGL a **−478,746,000,000** liability and NVDA a **−28,000,000** share count in their most recent quarters. Any lake that stores what it is handed will propagate those. The checks are arithmetic, not judgement, and are specified in §5.3.
3. **Point-in-time needs a second call.** The statement endpoints carry only `fiscal_date_ending` — the period end, not the publication date. `filing_date` + `accession_no` live on a *different* endpoint. Without joining them, nothing built on this lake is backtestable.

**One correction to argon's own spec, made here rather than buried:** the spec states that segment/KPI disclosure is "absent at any tier from every provider." That is wrong. UW returns 287 revenue-breakdown rows for NVDA with XBRL dimensional axes — Data Center $75.2B, Hyperscale $37.9B, and a geographic split — for the most recent quarter. See §3.3.4.

---

## 1. What argon is trying to build, in one paragraph

A per-ticker fundamental card plus an industry-chain screen for 25 AI-supply-chain names (chips → cloud → datacenter infra → apps/models). The method computes TTM aggregates, growth, margins, a company-type-routed valuation anchor, and subscores. It is a **descriptive context layer** sitting beside the options/vol surface, not an alpha source — the universe is too small and too correlated to validate a ranked score against (8 quarters at full cohort). livewire does not need to care about the method; it needs to care that the inputs are complete, honest, and point-in-time.

---

## 2. The requirement, ranked

Ranked by what blocks the most downstream work, not by ease.

### P0 — required for anything to render

| # | Need | Best source | Status |
|---|---|---|---|
| R1 | Quarterly income statement, balance sheet, cash flow, 25 tickers | UW statements | ✅ available, unbuilt |
| R2 | Explicit reporting currency per row | UW `reported_currency` | ✅ available |
| R3 | Publication timestamp (`filing_date`) for PIT | UW `fundamental-breakdown` | ✅ available, **separate call** |
| R4 | Integrity gate on ingest | our own code | ❌ must be built |
| R5 | Share count (diluted + outstanding) | UW `common_stock_shares_outstanding` | ✅ 100% cohort |

### P1 — required for the method to be more than a scorecard

| # | Need | Best source | Status |
|---|---|---|---|
| R6 | Capex, D&A, SBC → real FCF | UW `cash-flows` | ✅ 100% cohort |
| R7 | Cash + all debt tiers → net debt, EV | UW `balance-sheets` | ✅ 100% cohort (`current_debt` null — see §6.2) |
| R8 | EBITDA / EBIT | UW `income-statements` | ✅ 100% cohort |
| R9 | Segment + geographic revenue | UW `fundamental-breakdown.rev_breakdown` | ✅ available, **undocumented in our stack** |
| R10 | FX daily for TWD, EUR | **livewire lake, already present** | ✅ 21 FX symbols, 2003→present |
| R11 | ADR share factor | massive `/v2 shareFactor` | ⚠️ frozen at 2020-Q1 |

### P2 — wanted, unavailable, do not design around

| # | Need | Status |
|---|---|---|
| R12 | Forward analyst estimates | ❌ UW Advanced+ tier |
| R13 | Earnings-call transcripts | ❌ UW Advanced+ tier |
| R14 | Named customer/supplier graph | ❌ **does not exist in filings** — measured, §3.4 |
| R15 | Noncontrolling interest | ❌ not in UW schema; ~14% of rows need it |
| R16 | Backlog, bookings, forward guidance | ❌ no structured source at any tier |

---

## 3. Channels explored — the complete record

Everything tried, including the dead ends and the three separate times a wrong URL produced a wrong conclusion.

### 3.1 massive `/vX/reference/financials`

Ticker as **query param**. `timeframe=quarterly`. **`limit` max is 100 — it returns HTTP 400 above that.**

- 23/25 covered. TSM returns 0 quarterly rows (annual/trailing only). ASML returns 0.
- Depth varies **8–69 quarters** (GEV 8, META 16, PLTR 25, GOOGL 38, AMZN 69).
- Leaf shape `{value, unit, label, order}` under `financials.{income_statement,balance_sheet,cash_flow_statement,comprehensive_income}`.
- 73 distinct fields across the cohort; **coverage is not universal** — `sga_expense` 48%, `long_term_debt` 65%, `intangible_assets` 65%, `gross_profit` 87%.
- **Emits no capex, no FCF, no total debt, no cash, no D&A, no SBC, no EBITDA, no interest expense.**
- **Integrity, current data, 272 rows:** negative liabilities 5.1%, implausible share counts 15.1%, balance identity break 4.0%.
- Envelope: `request_id` varies per call; `results` rows byte-identical across identical calls.

### 3.2 massive `/v2/reference/financials/{ticker}`

Ticker in the **URL path** — a different form from `/vX`. `limit=1000` accepted.

- **Frozen at ~2020-Q1.** Not a current source. Was briefly chosen as the backbone on field count alone before its end-date was checked; that was wrong and is recorded here so nobody repeats it.
- 103 flat camelCase fields including USD-normalized variants (`revenuesUSD`, `debtUSD`) and `foreignCurrencyUSDExchangeRate`.
- **Uniquely carries `shareFactor`** — the ADR ratio. TSM `0.2` (1 ADS = 5 ordinary), ASML `1`. TSM's TWD revenue ÷ 30.2 reproduces `revenuesUSD` to 0.001%.
- Zero rows for META, GEV, PLTR, APP (FB→META rename, 2024 spinoff, post-freeze IPOs — flagged, not confirmed).

### 3.3 Unusual Whales statement endpoints ⭐

**The routes are PLURAL.** The singular forms return `404 {"error":"Route not found"}`.

```
GET /api/stock/{ticker}/income-statements      30 fields
GET /api/stock/{ticker}/balance-sheets         42 fields
GET /api/stock/{ticker}/cash-flows             34 fields
GET /api/stock/{ticker}/fundamental-breakdown  general[54] + rev_breakdown + annual_only
```

Rows carry `report_type` (`quarterly` | `annual`), `fiscal_date_ending`, `reported_currency`, `inserted_at`, `updated_at`.

#### 3.3.1 Coverage — all 25, no exceptions

| Ticker | Q rows | Span | Ccy | | Ticker | Q rows | Span | Ccy |
|---|---:|---|---|---|---|---:|---|---|
| NVDA | 82 | 2006-01→2026-04 | USD | | GEV | 14 | 2023-03→2026-06 | USD |
| AMD | 83 | 2005-12→2026-06 | USD | | CEG | 55 | 2012-09→2026-03 | USD |
| AVGO | 78 | 2007-01→2026-04 | USD | | VST | 83 | 2005-09→2026-06 | USD |
| MRVL | 82 | 2006-01→2026-04 | USD | | DELL | 53 | 2012-10→2026-04 | USD |
| **TSM** | **83** | **2005-12→2026-06** | **TWD** | | SMCI | 82 | 2005-12→2026-03 | USD |
| **ASML** | **83** | **2005-12→2026-06** | **EUR** | | PLTR | 30 | 2019-03→2026-06 | USD |
| AMAT | 82 | 2006-01→2026-04 | USD | | CRWD | 34 | 2018-01→2026-04 | USD |
| MU | 83 | 2005-11→2026-05 | USD | | NOW | 64 | 2010-09→2026-06 | USD |
| MSFT | 83 | 2005-12→2026-06 | USD | | APP | 31 | 2018-12→2026-06 | USD |
| GOOGL | 83 | 2005-12→2026-06 | USD | | META | 66 | 2010-03→2026-06 | USD |
| AMZN | 83 | 2005-12→2026-06 | USD | | ANET | 55 | 2012-12→2026-06 | USD |
| ORCL | 83 | 2005-11→2026-05 | USD | | VRT | 35 | 2017-12→2026-06 | USD |
| ETN | 83 | 2005-12→2026-06 | USD | | | | | |

**Total 1,673 ticker-quarters.** AMZN and VST show a `None` currency on some rows — livewire should default-and-flag, not assume USD.

#### 3.3.2 Integrity — same checks, one standard

1,668 quarterly balance-sheet rows: negative liabilities **0.2%** (4 rows), negative assets **0%**, implausible share counts **0%**.

`assets = liabilities + equity` fails on 14.2%. **This is not a defect.** The true identity is `A = L + E_parent + NCI`, UW exposes no NCI field, and 236 of 237 gaps run one direction, concentrated in MU, CEG, ORCL, TSM, DELL, AMD — all consolidating filers. Read it as the size of the missing-NCI problem (§6.1).

#### 3.3.3 Point-in-time — the join livewire must not skip

Statement endpoints have **no filing date**. `fundamental-breakdown.general` has all four:

```json
{"filing_date": "2026-05-20", "accession_no": "0001045810-26-000052",
 "formtype": "10-Q", "report_period_end_date": "2026-04-26"}
```

Join on `fiscal_date_ending` ≡ `report_period_end_date`. **Coverage is 68 rows vs 82 quarterly for NVDA — the join is incomplete and livewire must record which periods have no publication date rather than defaulting them.**

`accession_no` is a free SEC linkage for any future filing-text work.

#### 3.3.4 Segment revenue — the spec said this didn't exist

`fundamental-breakdown.rev_breakdown`, NVDA: **287 rows, 236 dimensional**, with real XBRL axes:

| `rev_group` | rows | axis |
|---|---:|---|
| product | 162 | `srt:ProductOrServiceAxis`, `us-gaap:StatementBusinessSegmentsAxis` |
| country | 75 | `srt:StatementGeographicalAxis` |
| continent | 25 | |
| rewards | 25 | |

Most recent quarter (2026-04-26): Data Center **$75.2B**, Hyperscale **$37.9B**, AI/Clouds/Industrial **$37.4B**, Compute & Networking segment **$74.6B**, Graphics **$7.1B**, Edge Computing **$6.4B**; geography US **$63.8B**, Taiwan **$12.0B**.

This is the single most valuable undiscovered dataset found in this exercise. Geographic revenue concentration is also a partial substitute for the customer-concentration edge that §3.4 shows cannot be recovered from filing text.

### 3.4 SEC EDGAR full-text search

Probed live. **Controls pass** — `"CoWoS"` → 10 hits, all NVDA 10-Ks, so the probe works.

- `"one customer accounted for"` → ~9,261 hits
- `"NVIDIA accounted for"` → **0 hits**

Filers disclose the 10%-customer *amount* (ASC 280-10-50-42 requires it) but overwhelmingly **not the identity**. A named supply-chain edge graph cannot be built from filings. Do not schedule work for it.

### 3.5 SEC XBRL `companyfacts` / `companyconcept` — NOT probed

Free, no key, and the obvious fallback for anything UW lacks (notably NCI). **This is the top unexplored channel** — see §6.1.

### 3.6 livewire's own lake — already has more than argon knew

Probed on the mini at `~/market-warehouse/data-lake`:

- **`bronze/asset_class=fx/`** — 21 symbols. `USDTWD` 5,395 rows from 2004-03-24; `EURUSD` 5,889 rows from 2003-12-01; both current to 2026-08-10. Schema identical to the vol-index parquet argon already reads. **This solves R10 at zero cost.** argon needs only an `"fx"` entry in `lake_resolver._ASSET_CLASS_TO_LOCAL_ATTR` and `_ASSET_CLASS_CANARY`.
- **`bronze/asset_class=corporate_action/`** — universe-scale. TSM/ASML dividends already `currency = USD` (ADR dividends pay in USD at source), so the dividend leg needs no translation.
- **`raw/massive/us_stocks_sip/{day,minute}_aggs_v1`** — prices only. **The lake holds no fundamentals today.**

### 3.7 UW gated tiers — confirmed unavailable

`/api/companies/{ticker}/earnings-estimates`, `/api/companies/{ticker}/transcripts/{quarter}` — Advanced+. The old note that "UW fundamentals are 403" referred to this `companies/*` family and was **wrongly generalized** to the `stock/*` statement routes, which is why nobody checked them for months.

### 3.8 FMP — not configured

No `FMP_API_KEY` in the environment. Listed third in argon's source priority but not an available channel today.

---

## 4. Verdict — source precedence

```
1  UW statements          backbone. 25/25, 2005→present, currency-tagged, cleanest
2  massive /vX            cross-check only. Its disagreements are how we detect UW drift
3  SEC XBRL companyfacts  gap filler (NCI, anything UW nulls). Free. UNPROBED
4  massive /v2            historical tail + ADR shareFactor only. Frozen 2020-Q1
—  explicit `na`          when all fail. A covered-looking row over an uncovered name is the worst outcome
```

This **inverts** what argon's spec currently says (massive `/vX` as backbone, UW as fallback). The spec will be corrected; livewire should build to this ordering.

Keeping massive as a live cross-check is deliberate, not redundant: two independent sources on the same quarter is the only mechanism that catches silent vendor drift. It already earned its keep — the disagreements are what exposed `/vX`'s defects.

---

## 5. What livewire should build

### 5.1 New bronze asset class: `fundamentals`

Follows the existing Hive convention:

```
data-lake/bronze/asset_class=fundamentals/symbol=<TICKER>/
    income_statement.parquet
    balance_sheet.parquet
    cash_flow.parquet
    filing_meta.parquet      # filing_date, accession_no, formtype  (§3.3.3)
    rev_breakdown.parquet    # segment + geographic               (§3.3.4)
```

Requires a `BronzeClient` schema variant and an entry in `_ASSET_CLASS_CANARY` — canary `NVDA` (deepest coverage, all fields present).

### 5.2 Schema requirements — non-negotiable columns

Every statement row:

| Column | Why |
|---|---|
| `ticker`, `fiscal_date_ending`, `report_type` | the business key; `report_type` separates quarterly from annual |
| `reported_currency` | **never assume USD** — TSM is TWD, ASML is EUR, some rows are null |
| `filing_published_at` | from the `fundamental-breakdown` join. **Null is a valid, recorded value — never a default** |
| `accession_no`, `formtype` | SEC linkage, and the natural dedupe key for restatements |
| `source`, `fetched_at`, `payload_hash` | provenance; matches the corporate-action convention already shipped |
| `event_revision`, `supersedes_*` | restatements. **Model this like `asset_class=corporate_action` already does** |

The corporate-action partition already implements immutable-observation-with-revision (`action_id`, `provider_event_id`, `event_revision`, `supersedes_action_id`, `status`, `fetched_at`, `payload_hash`). **Reuse that pattern verbatim rather than inventing a second one.**

### 5.3 The integrity gate — mandatory, and cheap

Run on ingest. Store the row **either way** — quarantining the payload destroys the evidence that a vendor is wrong — but write a violation record and mark the field unusable.

| Check | Rule | Measured rate (massive / UW) |
|---|---|---|
| `negative_liabilities` | `total_liabilities >= 0` | 5.1% / 0.2% |
| `negative_assets` | `total_assets >= 0` | 0% / 0% |
| `implausible_share_count` | `shares >= 1_000_000` when revenue > 0 | 15.1% / 0% |
| `unexplained_balance_gap` | `\|(L+E) − A\| / A <= 0.005` | 4.0% / 14.2% ⚠️ |

⚠️ The last is **not** a defect count for UW — see §6.1. Report it, don't act on it, until NCI is sourced.

These test identities, not plausibility ranges. A rule that fires on "unusual" needs per-company tuning and becomes a judgement call; these are arithmetic and need none.

**Two protocol rules that cost us real time and belong in the ingest code:**

1. **An HTTP error is never a zero.** Record the status. A 400/404 written as `rows=0` reads as "no coverage" and is indistinguishable from truth. This produced three wrong conclusions in this project.
2. **Probe limits must be per-endpoint constants.** `/vX` 400s above `limit=100`; `/v2` accepts 1000. A shared limit silently 400s one endpoint for every ticker.

### 5.4 Point-in-time discipline

`fiscal_date_ending` is when the quarter *ended*. `filing_date` is when the world could have known. **Any backtest filters on the latter.** Since the join is incomplete (68/82 for NVDA), livewire must expose which periods lack a publication date so consumers can exclude them rather than silently treat them as known-at-period-end.

### 5.5 FX — a registration, not a project

The rates are already in the lake (§3.6). What is missing is only the resolver wiring. Translation math: `local ÷ rate = USD`, verified against `/v2`'s own USD variants to 0.001%.

### 5.6 Cadence

Fundamentals change ~4×/year per ticker. **Weekly is ample**; daily is waste. UW's `updated_at` makes restatement detection cheap — refetch, compare `payload_hash`, write a new revision only on change. Budget impact is negligible: 25 tickers × 4 endpoints = 100 calls against a 120k/day ceiling with ~45k current burn.

---

## 6. What livewire should explore — open questions

### 6.1 Noncontrolling interest — the biggest real gap ⭐

~14% of UW balance-sheet rows can't be decomposed because NCI is missing, concentrated in MU, CEG, ORCL, TSM, DELL, AMD. This corrupts equity-based ratios for exactly the consolidating filers where they matter most.

**SEC XBRL `companyconcept` for `MinorityInterest` / `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` is free and unprobed.** Highest-value next probe in this whole document.

### 6.2 `current_debt` is in the schema and null for all 25

The probe measures non-null rates precisely because a schema key is not data. Worth one call to SEC XBRL to see whether it's recoverable, since net-debt calculations want the current tranche.

### 6.3 Does the segment breakdown generalize beyond NVDA?

287 rows for NVDA is excellent. **Not yet measured for the other 24.** If coverage is broad this deserves its own parquet and its own analysis surface; if it's NVDA-only it's a curiosity. One probe answers it.

### 6.4 ADR share factor needs a live source

`/v2 shareFactor` is frozen at 2020-Q1. ADR ratios change rarely but they do change. Candidates: SEC 20-F cover page, the depositary bank's own disclosure. Unprobed.

### 6.5 The four zero-row `/v2` tickers

META, GEV, PLTR, APP return zero. Hypotheses — FB→META rename, GEV's 2024 spinoff, post-freeze IPOs — are **flagged, not confirmed**. Only matters if `/v2` history is wanted for them.

### 6.6 massive as a live cross-check

Worth building the two-source comparison as a standing job rather than a one-off script. It is the only mechanism that catches a vendor silently changing its derivation.

---

## 7. Gotchas that cost us time

| Gotcha | Cost |
|---|---|
| `/v2` takes ticker in the **path**, `/vX` as a **query param** | 404 read as "no coverage", 3 separate times |
| UW statement routes are **plural** | singular forms 404 with `Route not found` |
| "UW fundamentals are 403" was about `companies/*`, not `stock/*` | **months of not checking the better source** |
| `/vX` 400s above `limit=100`; `/v2` accepts 1000 | a shared limit zeroed all 25 tickers |
| An unfiltered `/v2` count mixes `Q`/`Y`/`YA`/`T` | quarterly counts overstated ~5× |
| `A = L + E` is false for consolidating filers | 14.2% of UW rows misread as defective |
| massive `/vX` `fcf = OCF + ICF` (argon's current code) | **is not free cash flow** — ICF includes acquisitions and securities |
| `long_term_debt` as total debt (argon's current code) | omits current debt; null for 8/23 names |

---

## 8. Reproduce everything

```bash
# 1. which tickers have data, per source
MASSIVE_API_KEY=... uv run python scripts/research/fundamental_source_coverage.py

# 2. field map, /vX n /v2 overlap, hash rule, ADR ratio, integrity
MASSIVE_API_KEY=... uv run python scripts/research/fundamental_field_contract.py

# 3. UW coverage + integrity + head-to-head vs massive
UW_SCAN_API_KEY=... MASSIVE_API_KEY=... uv run python scripts/research/uw_fundamentals_probe.py
```

Artifacts, all committed under `docs/research/2026-08-10-fundamental-source-coverage/`:

| File | Contents |
|---|---|
| `coverage.json` / `README.md` | per-ticker source coverage matrix |
| `field_contract.json` / `field-contract.md` | 30-field map, inventory, overlap, exclusion list, ADR, integrity |
| `uw_fundamentals.json` / `uw-fundamentals.md` | UW coverage, null rates, integrity, head-to-head |
| `fx-and-corporate-actions.md` | lake FX series, ADR gap, observation-model precedent |

`README.md`, `field-contract.md` and `uw-fundamentals.md` are **script-generated and overwritten on every run**. Hand-written narrative goes in `fx-and-corporate-actions.md` or this brief.

---

## 9. Suggested sequence for livewire

| Order | Work | Why first |
|---|---|---|
| 1 | Probe SEC XBRL `companyfacts` for NCI + `current_debt` (§6.1, §6.2) | free, unblocks 14% of rows, decides whether XBRL is tier-3 or tier-1 |
| 2 | Probe segment coverage across all 25 (§6.3) | one call per ticker; decides whether §3.3.4 is a feature or a footnote |
| 3 | `asset_class=fundamentals` bronze + UW ingest (§5.1, §5.2) | the actual build |
| 4 | Integrity gate (§5.3) | must land **with** the ingest, not after |
| 5 | PIT join + missing-publication-date reporting (§5.4) | without it nothing is backtestable |
| 6 | Register `asset_class=fx` in the resolver (§5.5) | small, unblocks foreign issuers |
| 7 | massive cross-check as a standing job (§6.6) | drift detection, not urgent |

Steps 1 and 2 are probes, cost nothing, and either of them could change step 3's schema. **Do them before building.**
