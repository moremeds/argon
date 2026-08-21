# USD source probe (MC3 Part B, Task B2)

Probed live on 2026-08-21. Raw results: `probe.json`. Verdict: `VERDICT.md`.

Reproduce:

```
uv run python scripts/research/usd_source_probe.py
```

Answers three questions the USD state cannot be built without: which broad-dollar series
is vintage-bearing and therefore replayable, whether the independent cross-check is
reachable and on what terms, and which candidates are dead so a later reader does not
re-try them.

| series | frequency | units | span | vintages | revised periods | verdict |
|---|---|---|---|---|---|---|
| `DTWEXBGS` | daily | Index Jan 2006=100 | 2006-01-02..2026-08-14 | 293 | 1265 | **SELECT** |
| `RTWEXBGS` | monthly | Index Jan 2006=100 | 2006-01-01..2026-07-01 | 90 | 138 | **SELECT** |
| `DTWEXAFEGS` | daily | Index Jan 2006=100 | 2006-01-02..2026-08-14 | 293 | 1265 | **SELECT** |
| `DTWEXEMEGS` | daily | Index Jan 2006=100 | 2006-01-02..2026-08-14 | 293 | 1265 | **SELECT** |
| `DTWEXM` | daily | Index Mar 1973=100 | 1973-01-02..2019-12-31 | 0 | 0 | **REJECT** |

BIS effective exchange rates: `SELECT_AS_CROSS_CHECK_ONLY`, anonymous access
`True`, vintage-bearing `False`.
