# Verdict — USD sources (2026-08-21)

## Chosen

| role                            | series                                            | publisher                             | why                                                                     |
| ------------------------------- | ------------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------------- |
| `broad_dollar` (primary anchor) | `DTWEXBGS`                                        | Federal Reserve H.10, via FRED/ALFRED | the only broad-dollar index that is both current and vintage-bearing    |
| `broad_dollar_real`             | `RTWEXBGS`                                        | Federal Reserve, via FRED/ALFRED      | the CPI-deflated sibling; a different question, not a substitute        |
| cross-check                     | BIS effective exchange rates, `WS_EER` `D.N.B.US` | Bank for International Settlements    | an independent second institution, usable **only** on the current value |

## What the measurement changed

### 1. The H.10 broad dollar is a WEEKLY release carrying daily observations

The instinct is to treat `DTWEXBGS` like `SOFR` — a daily series minting a vintage every
publication day, ~250 a year, running down FRED's 2000-vintage cap in about eight years.
It is not. Measured over 5.61 years from `DAILY_VINTAGE_START`:

|                               | vintages | per year | headroom under the 2000 cap |
| ----------------------------- | -------- | -------- | --------------------------- |
| `SOFR` / `EFFR` / `RRPONTSYD` | ~1,405   | ~250     | **2.3–2.4 years**           |
| `DTWEXBGS`                    | **293**  | **52.2** | **32.7 years**              |

The H.10 goes out weekly and publishes the week's daily values together, so the vintage
count tracks releases rather than observation days. Consequence: the daily-window
constraint that constrains the funding series is not a live risk here, and
`test_daily_vintage_start_has_not_expired` keeps its margin from EFFR, not from this.

### 2. The Fed revises this index; the funding series do not

**1,265 revised periods** in `DTWEXBGS` against **zero** for SOFR, EFFR and RRPONTSYD.
That is not a defect, it is a different publisher discipline — and it is load-bearing for
this domain in a way it never was for Part A:

- a replay must select the vintage in force at `as_of`, not the latest value, or every
  historical USD state silently reads today's restatement;
- `compute_confidence`'s `revision_penalty` will legitimately fire on this domain, and a
  USD state showing a revision drag is correct rather than broken.

`RTWEXBGS` revises too (138 periods), on 90 vintages.

### 3. BIS is reachable, and cannot be replayed

The endpoint answers anonymously with no key and no rate limit hit across the probe. Two
things about it are traps.

**A bare request succeeds and returns XML.** BIS content-negotiates on `Accept` alone,
and the status code does not tell you whether you got what you asked for:

| request                                                | status  | media type         |
| ------------------------------------------------------ | ------- | ------------------ |
| no `Accept`, no `format`                               | **200** | `application/xml`  |
| `Accept: application/vnd.sdmx.data+json;version=1.0.0` | 200     | `application/json` |
| `format=jsondata`, no `Accept`                         | **406** | `application/xml`  |
| `format=jsondata` + `Accept`                           | 200     | `application/json` |

So a client that omits the header does not fail — it hands a JSON parser SDMX-ML. The
`format` query parameter is not a substitute: alone it is refused outright. This was
initially mis-measured in the other direction (the 406 was read as "the Accept header is
required", when the header's real job is selecting JSON and the 406 came from `format`);
the table above is the corrected measurement.

**The data message carries no real-time dimension.** There is no vintage to select, so
BIS can corroborate today's level and can never answer what the level was believed to be
on a past date. It is therefore a cross-check and never evidence for a point-in-time
state. Non-trading days come back as the string `NaN`, which is an absence and must never
be coerced to zero.

## Rejected

| candidate                         | reason                                                                                                                                                                 |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DTWEXM` (Major Currencies index) | **discontinued** — last observation 2019-12-31. It still answers, and everything it says is history.                                                                   |
| Yahoo / `DXY` quote feeds         | banned by standing rule, enforced by `scripts/check_no_yahoo.py`. `DXY` is also an ICE product with a fixed six-currency basket, not an official trade-weighted index. |
| BIS as the primary anchor         | not vintage-bearing (above). A domain whose whole premise is replay cannot rest on a source with no history of its own beliefs.                                        |

`DTWEXAFEGS` and `DTWEXEMEGS` (advanced-economies and emerging-market sub-indices) both
pass every clause and are **not adopted here**: the USD state names one broad anchor, and
adding two sub-baskets that decompose it would enlarge every `inputs_hash` without adding
a factor the state reads. They are available if a later milestone wants the composition.

## Standing consequence for the adapter

Any client added for these sets `trust_env=False`. Four rates clients inherited ambient
macOS proxy configuration and froze every native run while the Linux container was immune
— so a green production deploy is not evidence the call is safe.
