# apex coverage audit — S&P 500 + Nasdaq-100 (517 tickers)

Probed apex `/bars/{t}?timeframe=1d` back to 1990 (apex_url=http://100.66.147.98:8322).

## Status breakdown
- full: 485
- post_floor_start: 14
- floor_truncated: 12
- thin: 6

## Needs enrichment: 18 tickers
`missing` (no bars), `thin` (<200 bars), or `floor_truncated`
(starts in 2021-05-10..2021-06-30, the livewire backfill floor — existed earlier).
`post_floor_start` names are likely genuine post-2021 IPOs with full history;
verify individually. See needs_enrichment.csv for the actionable list.

Files: coverage/apex_coverage.csv, coverage/needs_enrichment.csv
