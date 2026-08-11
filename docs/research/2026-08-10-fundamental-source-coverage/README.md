# Fundamental source coverage — massive, core 25

*Probed 2026-08-10 · P1a data-contract spike · spec `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md`*

Reproduce:

```bash
MASSIVE_API_KEY=... uv run python scripts/research/fundamental_source_coverage.py
```

Every count below is a **quarterly** count taken at a constant per-endpoint limit (`/vX` 100 — it 400s above that; `/v2` 1000), and an HTTP error is recorded as `null` rather than `0` — three earlier readings of these endpoints were wrong for exactly those two reasons.

This file is REGENERATED on every run. Hand-written findings live in `fx-and-corporate-actions.md` (mini-lake FX series, ADR-ratio gap, observation-model precedent) — put narrative there, not here.

## Summary

| State | Meaning | Tickers |
|---|---|---|
| `covered` | current `/vX` quarterly data | AMAT, AMD, AMZN, ANET, APP, AVGO, CEG, CRWD, DELL, ETN, GEV, GOOGL, META, MRVL, MSFT, MU, NOW, NVDA, ORCL, PLTR, SMCI, VRT, VST |
| `history_only` | no current data; `/v2` quarterly history exists | ASML |
| `annual_only` | **unusable** — only annual/trailing rows | TSM |

## Per ticker

| Ticker | State | `/vX` Q | `/vX` span | units | `/v2` Q | `/v2` span | `/v2` all | USD variants | FX rate |
|---|---|---:|---|---|---:|---|---:|---|---|
| NVDA | `covered` | 64 | 2010-04-29 → 2026-04-26 | USD,USD / shares,shares | 88 | 1998-10-25 → 2020-01-26 | 405 | yes | yes |
| AMD | `covered` | 65 | 2010-03-25 → 2026-06-27 | USD,USD / shares,shares | 93 | 1997-12-28 → 2020-03-28 | 425 | yes | yes |
| AVGO | `covered` | 61 | 2011-01-30 → 2026-05-03 | USD,USD / shares,shares | 43 | 2009-08-02 → 2020-02-02 | 205 | yes | yes |
| MRVL | `covered` | 66 | 2009-08-01 → 2026-05-02 | USD,USD / shares,shares | 76 | 2000-04-30 → 2020-02-01 | 366 | yes | yes |
| TSM | `annual_only` | 0 | — | — | 0 | — | 76 | — | — |
| ASML | `history_only` | 0 | — | — | 93 | 2002-06-30 → 2019-12-31 | 391 | yes | yes |
| AMAT | `covered` | 67 | 2009-07-26 → 2026-04-26 | USD,USD / shares,shares | 91 | 1997-10-26 → 2020-01-26 | 419 | yes | yes |
| MU | `covered` | 63 | 2010-12-02 → 2026-05-28 | USD,USD / shares,shares | 90 | 1997-11-27 → 2020-02-27 | 415 | yes | yes |
| MSFT | `covered` | 66 | 2009-09-30 → 2026-06-30 | USD,USD / shares,shares | 108 | 1993-12-31 → 2020-03-31 | 491 | yes | yes |
| GOOGL | `covered` | 38 | 2017-03-31 → 2026-06-30 | USD,USD / shares,shares | 72 | 2004-03-31 → 2020-03-31 | 320 | yes | yes |
| AMZN | `covered` | 69 | 2009-03-30 → 2026-06-30 | USD,USD / shares,shares | 93 | 1997-03-31 → 2020-03-31 | 430 | yes | yes |
| META | `covered` | 16 | 2022-06-30 → 2026-06-30 | USD,USD / shares,shares | 0 | — | 0 | — | — |
| ORCL | `covered` | 63 | 2009-08-31 → 2026-05-31 | USD,USD / shares,shares | 107 | 1993-11-30 → 2020-02-29 | 489 | yes | yes |
| ANET | `covered` | 49 | 2014-03-30 → 2026-06-30 | USD,USD / shares,shares | 24 | 2014-03-31 → 2019-12-31 | 124 | yes | yes |
| VRT | `covered` | 26 | 2020-03-31 → 2026-06-30 | USD,USD / shares,shares | 8 | 2018-03-31 → 2019-12-31 | 48 | yes | yes |
| ETN | `covered` | 68 | 2009-03-30 → 2026-06-30 | USD,USD / shares,shares | 92 | 1997-12-31 → 2020-03-31 | 423 | yes | yes |
| GEV | `covered` | 8 | 2024-06-30 → 2026-06-30 | USD,USD / shares,shares | 0 | — | 0 | — | — |
| CEG | `covered` | 27 | 2009-03-30 → 2026-06-30 | USD,USD / shares,shares | 53 | 1999-03-31 → 2011-12-31 | 247 | yes | yes |
| VST | `covered` | 35 | 2017-06-30 → 2026-03-31 | USD,USD / shares,shares | 15 | 2016-09-30 → 2019-12-31 | 68 | yes | yes |
| DELL | `covered` | 44 | 2009-10-30 → 2026-05-01 | USD,USD / shares,shares | 16 | 2016-04-29 → 2020-01-31 | 83 | yes | yes |
| SMCI | `covered` | 48 | 2011-09-30 → 2026-03-31 | USD,USD / shares,shares | 48 | 2006-12-31 → 2019-12-31 | 240 | yes | yes |
| PLTR | `covered` | 25 | 2020-06-30 → 2026-06-30 | USD,USD / shares,shares | 0 | — | 0 | — | — |
| CRWD | `covered` | 27 | 2019-07-31 → 2026-04-30 | USD,USD / shares,shares | 5 | 2019-01-31 → 2020-01-31 | 35 | yes | yes |
| NOW | `covered` | 59 | 2009-09-30 → 2026-06-30 | USD,USD / shares,shares | 34 | 2012-03-31 → 2020-03-31 | 164 | yes | yes |
| APP | `covered` | 38 | 2011-03-30 → 2026-06-30 | USD,USD / shares,shares | 0 | — | 0 | — | — |
