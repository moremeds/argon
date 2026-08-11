# Universe breadth — how wide can the cross-section get?

*Probed 2026-08-11 · REGENERATED on every run · interpretation lives in `VERDICT.md`*

```bash
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_universe_breadth_probe.py
```

Gates: local price history >= 2500 daily bars starting <= 2013-01-01, AND >= 40 quarters of UW statements.

| | count |
|---|---:|
| lake candidates (price gate) | 263 |
| **usable (both gates)** | **245** |
| UW http errors (unknown, not absent) | 0 |

## Survivorship controls

Delisted/merged names, probed to establish whether a point-in-time universe is constructible at all. `uw_quarters: 0` with `http: 200` is a genuine empty result, not a transport failure.

| Ticker | in lake | UW http | UW quarters |
|---|---|---:|---:|
| ATVI | False | 200 | 0 |
| XLNX | False | 200 | 0 |
| TWTR | False | 200 | 0 |
| SIVB | False | 200 | 0 |
| FRC | False | 200 | 0 |
| VMW | False | 200 | 0 |

Both sources carry live tickers only. Widening the universe buys statistical power; it cannot buy survivorship correction.
