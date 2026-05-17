# WGC ETF Flow Corpus

Date: 2026-05-17

## Source contract

World Gold Council publishes the Goldhub ETF-flows archive at:

`https://www.gold.org/goldhub/research/etf-flows`

The listing pages are public and expose monthly XLSX download links under
`/download/file/<id>/ETF...xlsx`. The XLSX files themselves are Goldhub-gated:
anonymous HTTP requests return 403, while an authenticated browser session can
download them.

Do not commit cookies or session material. Supported operational modes:

- `WGC_GOLDHUB_COOKIE`: environment-only cookie header for scheduled authenticated downloads.
- `WGC_ETF_FLOWS_WORKBOOK_PATH`: local workbook file or directory of exported workbooks.

## Persisted schema

Migration `046_wgc_etf_monthly.sql` creates `uw_scan.wgc_etf_monthly`.

It stores one row per `(ticker, obs_date, source_url)` with:

- fund identity: `ticker`, `fund_name`, `fund_type`, `region`, `country`
- market context: `gold_price_usd_oz`, aggregate ounces/tonnes/value
- fund metrics: `holdings_tonnes`, `demand_tonnes`, `flow_usd_mn`
- lineage: `source_url`, `source_label`, `as_of`, `source`

Keeping `source_url` in the primary key preserves workbook revisions instead of
flattening historical snapshots.

The ingest also bridges GLD/IAU/GLDM/PHYS monthly holdings into
`etf_holdings_daily` with `source='WGC'`, so existing Lens 1 readers can use the
data without a new API surface.

## Parser coverage

Modern workbooks use:

- `Holdings by month`
- `Demand by month`
- `Fund flows by month`

Legacy workbooks use combinations of:

- `All holdings by month`
- `Delta tonnes by month`
- `All flows US$ by month`
- `All fund flows` / `All fund flows by fund`

The fallback table parser captures current-month snapshot rows when a workbook
lacks a full historical holdings sheet.

## Local load result

Authenticated scrape on 2026-05-17 downloaded 78 workbooks from Dec 2018 through
Mar 2026 into `output/wgc_etf_workbooks/`.

Local Postgres load result:

- `wgc_etf_monthly`: 1,338,260 rows
- distinct `source_url`: 78
- distinct tickers: 234
- date range: 2003-03-31 to 2026-03-31
- rows with `demand_tonnes`: 678,265
- rows with `flow_usd_mn`: 620,624
- WGC bridge holdings rows: GLD 257, IAU 255, GLDM 94, PHYS 194

Latest WGC workbook in this load: `20717_ETF_Flows_March_2026.xlsx`.
