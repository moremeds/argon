# Valuation control — is the margin inversion expensiveness in disguise?

*Probed 2026-08-11 · REGENERATED on every run · 245 names, 80 quarters, 2q forward return*

```bash
UW_SCAN_API_KEY=... uv run python scripts/research/fundamental_valuation_control.py
```

Cross-section width: min 146, median 239, max 245.

## Own IC

| Signal | IC | t | quarters |
|---|---:|---:|---:|
| `book_to_price` | -0.0365 | -2.321 | 80 |
| `gross_margin` | -0.0194 | -1.723 | 80 |
| `op_margin` | -0.027 | -2.729 | 80 |
| `earnings_yield` | -0.0194 | -1.426 | 77 |
| `fcf_yield` | 0.0285 | 2.837 | 77 |

## Margin IC controlling for valuation

| Margin | control | partial IC | t | quarters |
|---|---|---:|---:|---:|
| `gross_margin` | `earnings_yield` | -0.018 | -1.611 | 77 |
| `gross_margin` | `book_to_price` | -0.0271 | -2.685 | 80 |
| `gross_margin` | `fcf_yield` | -0.0144 | -1.257 | 77 |
| `op_margin` | `earnings_yield` | -0.0231 | -2.348 | 77 |
| `op_margin` | `book_to_price` | -0.0306 | -3.008 | 80 |
| `op_margin` | `fcf_yield` | -0.0298 | -2.91 | 77 |

> Market cap uses RAW close x as-reported shares; adj_close would mix reference frames across splits. Yields are fundamental/price so the ranking stays monotone through zero earnings.
