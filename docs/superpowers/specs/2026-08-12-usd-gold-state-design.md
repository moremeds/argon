# USD transmission and gold state design (MC3 Part B)

**Status:** specified. Preregistered before any USD or gold engine was written. The source
measurements in §2 were taken against live publishers on 2026-08-21 and changed two of this
document's rulings before implementation started.

**Parent plan:** `docs/superpowers/plans/2026-08-12-macro-mc3-usd-gold-state.md`
**Part A (upstream):** `docs/superpowers/specs/2026-08-21-rates-market-layer-design.md`

---

## 0. Deviations from the plan

1. **B2 was probed before B1 was written.** The plan orders the spec first, but the spec
   cannot name a primary anchor honestly without knowing which candidate is vintage-bearing.
   The probe ran first and its verdict is cited throughout:
   `docs/research/2026-08-12-usd-source-probe/VERDICT.md`.

2. **There is no `sources/fed_h10.py`.** The Fed's H.10 broad-dollar indices are published
   through FRED/ALFRED, which this desk already has a vintage-aware client and contract
   table for. A second FRED client would duplicate `sources/fred_macro.py` and give the two
   copies room to disagree about what a vintage is. `DTWEXBGS` and `RTWEXBGS` are registered
   in `SERIES_CONTRACT` exactly like the Part A funding series. `sources/bis_eer.py` IS
   created, because BIS is a genuinely different publisher with a different protocol.

3. **BIS is a cross-check and never evidence.** Measured: its SDMX data message carries no
   real-time dimension, so it has no vintage to select. A domain whose premise is replay
   cannot rest on a source with no record of its own past beliefs. See §2.3.

4. **The gold price in the fixture is a fund close, not a spot fix.** FRED's LBMA gold fix
   `GOLDPMGBD228NLBM` was retired and now answers HTTP 400, and Yahoo is banned by standing
   rule, so the free gold price this desk actually has is the traded GLD close from
   massive — which is what `reports/gold_posture.py` already reads as `GLD_CLOSE`. It is
   labelled `vendor` rather than `official` and the fixture says so in `provenance`, so a
   later reader does not mistake a fund's settled close for a London fix.

## 1. What the USD domain is, and what it must not become

USD is a **transmission** domain. It does not re-answer what inflation is doing or what the
committee did — MC2 and Part A already answer those, and their answers are consumed as
upstream state IDs rather than recomputed from their inputs.

**The double-count prohibition.** These inputs are owned upstream and may not be re-read as
USD's own factors:

| input                                        | owned by      | USD may                              |
| -------------------------------------------- | ------------- | ------------------------------------ |
| real yields (`DFII10`)                       | MC2 rates     | reference the rates state ID         |
| inflation compensation (`T10YIE`, `T5YIFR`)  | MC2 inflation | reference the inflation state ID     |
| policy paths (SEP / dealer / market-implied) | MC2 rates     | reference the rates state ID         |
| `supply`, `positioning`, `plumbing`          | **Part A**    | read the observations by causal role |

Part A's roles are the reason this plan and MC3 are one plan. If USD sourced funding and
positioning for itself, the same publisher payload would be ingested twice under two owners,
and the two copies would drift on the first parser change. The rule: **one publisher payload,
one owner, many readers.**

### 1.1 USD factors

| factor                          | role                       | series              | owned here |
| ------------------------------- | -------------------------- | ------------------- | ---------- |
| broad dollar level and momentum | `curve`                    | `DTWEXBGS`          | yes        |
| real broad dollar               | `decomposition_component`  | `RTWEXBGS`          | yes        |
| relative policy                 | `policy_actual` (upstream) | rates state ID      | no         |
| funding / liquidity             | `plumbing`                 | Part A observations | no         |
| positioning                     | `positioning`              | Part A observations | no         |

`DTWEXBGS` is the **required** anchor. With it absent the state abstains — no static value,
no third-party quote, no substitution of the real index for the nominal one. They answer
different questions: a nominal index moving while the real one does not is an inflation
differential, which is a fact the state should be able to report rather than erase.

### 1.2 Revisions are load-bearing here in a way they were not in Part A

The Fed restates this index: **1,265 revised periods** in `DTWEXBGS` against **zero** for
SOFR, EFFR and RRPONTSYD. Two consequences the engine must honour:

- a replay selects the vintage in force at `as_of`, never the latest value. The repository
  already does this; what changes is that here it is not a formality.
- `compute_confidence`'s `revision_penalty` will fire on this domain in normal operation. A
  USD state carrying a revision drag is correct, not broken, and must not be tuned away.

## 2. Sources, measured

### 2.1 The anchor is a weekly release carrying daily observations

`DTWEXBGS` mints **293 vintages in 5.61 years — 52.2 a year**, because the H.10 goes out
weekly with the week's daily values together. The funding series mint ~250 a year. Under
FRED's 2000-vintage cap that is **32.7 years of headroom** against EFFR's 2.3, so the daily
window constraint that binds Part A does not bind here.

### 2.2 `DTWEXM` is dead

Last observation 2019-12-31. It still answers every request, and everything it says is
history. Recorded so no later reader re-tries it.

### 2.3 BIS: a 200 that is not a success

BIS content-negotiates on `Accept` alone, and the status code does not say whether you got
what you asked for:

| request                        | status  | media type         |
| ------------------------------ | ------- | ------------------ |
| no `Accept`, no `format`       | **200** | `application/xml`  |
| `Accept: …sdmx.data+json…`     | 200     | `application/json` |
| `format=jsondata`, no `Accept` | **406** | `application/xml`  |

A client that omits the header **succeeds** and hands a JSON parser SDMX-ML. Non-trading
days return the string `NaN`, which is an absence and is never coerced to zero. And the data
message has no real-time dimension — hence cross-check only.

## 3. The gold domain

Gold keeps its three lenses. This milestone does not change what they say; it changes what
they can prove they read.

| lens                      | what it is                                                  | what it may never become                 |
| ------------------------- | ----------------------------------------------------------- | ---------------------------------------- |
| 1 — structural flow       | central-bank reserves, ETF holdings, COMEX/LBMA inventory   | —                                        |
| 2 — regime-gated cyclical | real yields, USD, positioning, gated on the post-2022 break | —                                        |
| 3 — valuation overlay     | long-run anchors                                            | a price target, an allocation, or a size |

**The provenance defect this task exists to close.** `reports/gold_posture.py:380` pins a
four-entry `inputs_used` manifest — `DFII10`, `GLD_CLOSE`, `T5YIFR`, `CPIAUCSL` — while the
orchestrator consumes roughly eleven inputs. Every consumed row gets a typed evidence
association, and an absent optional input is recorded as an **omission reason**, never as a
fabricated evidence id. A manifest that names four of eleven is worse than no manifest: it
reads as a complete audit trail.

**The post-2022 regime gate stays load-bearing.** Gold decoupled from real yields after 2022,
and a Lens 2 that averages across the break describes neither side of it.

## 4. Contradictions

| rule                                 | fires when                                                                                 |
| ------------------------------------ | ------------------------------------------------------------------------------------------ |
| `usd_against_relative_policy`        | the broad dollar moves against what the policy differential implies over the same window   |
| `gold_against_real_yields_post_2022` | gold and real yields move together where the pre-2022 relationship says they should oppose |
| `gold_flow_against_cyclical`         | structural flows are strong while the cyclical lens is adverse                             |

A contradiction reports that evidence disagrees. It never resolves into a direction and never
changes a state label.

## 5. Golden scenarios

Frozen in `tests/fixtures/macro/usd_gold_golden.json`. Every value is fetched from the live
publisher at authoring time. The `expect` blocks are preregistered predictions and must not
be edited to match whatever the engines produce.

| #   | id                                               | what it pins                                                                                               |
| --- | ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- |
| 1   | `usd_strength_against_easing_policy`             | the dollar rising while the committee eases; the contradiction fires and no policy direction is inferred   |
| 2   | `gold_and_real_yields_decoupled_post_2022`       | both rising together, which the pre-2022 relationship forbids; the regime gate is what makes it reportable |
| 3   | `strong_official_flows_against_adverse_cyclical` | Lens 1 strong, Lens 2 adverse; neither is allowed to overwrite the other                                   |
| 4   | `usd_anchor_absent_state_abstains`               | no `DTWEXBGS` vintage at `as_of` → `UNKNOWN`, and the real index is NOT substituted                        |
| 5   | `broad_dollar_revised_after_the_fact`            | a period whose vintage changed; the replay reads the vintage in force, and the revision penalty is visible |

### 5.1 What was frozen, and the two constructions worth knowing

Generator: `scripts/research/build_usd_gold_golden.py`. Reproduce with
`uv run python scripts/research/build_usd_gold_golden.py`. It refuses to overwrite a frozen
`expect` block without `--rewrite-predictions`, which logs the prior text.

| #   | window                    | the measured disagreement                                                       |
| --- | ------------------------- | -------------------------------------------------------------------------------- |
| 1   | 2024-09-16 → 2024-12-31   | `DTWEXBGS` 121.4976 → 129.2775 (+6.4%) while `EFFR` falls 5.33 → 4.33            |
| 2   | 2025-10-01 → 2025-12-31   | `GLD_CLOSE` 356.03 → 396.31 (+11.3%) while `DFII10` rises 1.77 → 1.93            |
| 3   | 2024-08-19 → 2024-10-23   | GLD tonnage +4.05% while `DFII10` +14bp and `DTWEXBGS` +2.31%                    |
| 4   | as_of 2020-06-30          | 22 anchor periods present, 0 passing `available_at <= as_of`; `RTWEXBGS` present |
| 5   | period 2026-08-03         | 120.7739 (published 08-10) restated to 119.6951 (08-17)                          |

**`owned_by` is the double-count prohibition made checkable.** Every input row carries it.
`EFFR` and `DFII10` are tagged `policy_rates`, so a test can assert USD and gold referenced
them as upstream rather than claiming them as domain-owned factors. §1 states the rule in
prose; without this tag there is nothing for a test to fail on.

**Scenario 4 freezes the anchor's rows rather than an empty list.** The 22 periods exist and
every vintage of them carries `available_at >= 2021-01-01`, because `DTWEXBGS` is a daily
contract and `request_window()` bounds daily series at `DAILY_VINTAGE_START`. Applying
`available_at <= as_of` yields nothing. Freezing an empty leg instead would have proved only
that an empty list is empty; freezing the real rows proves the predicate is what excludes
them. The `RTWEXBGS` sibling *is* available at that `as_of` (112.9934 for 2020-05-01), which
is what makes the refusal to substitute a decision rather than an absence of options.

## 6. Exit criteria

- USD state uses an official free primary; no static, Yahoo or third-party quote is ever
  promoted to anchor;
- upstream inflation / rates / market-layer evidence is referenced, never duplicated;
- every consumed gold input appears in typed provenance or as an explicit omission;
- the post-2022 regime gate remains load-bearing;
- gold replay and legacy compatibility pass;
- no forecast, allocation or sizing claim is promoted.
