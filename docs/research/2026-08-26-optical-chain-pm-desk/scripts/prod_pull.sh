#!/bin/bash
# Pull the optical-chain PM dataset from the MINI (prod). The local dev DB lags
# prod by months on exactly the newest filings and on valuation anchors.
set -euo pipefail
OUT="$(dirname "$0")"
TK="'AAOI','AMZN','ANET','AVGO','CIEN','COHR','CRDO','FN','GOOGL','LITE','META','MRVL','MSFT','NTAP','ORCL','POET'"

run() { ssh macmini "/opt/homebrew/bin/psql -h 127.0.0.1 -d option_wizard -tAF$'\t' -c \"$1\""; }

# Statements: newest vintage per (ticker, period, statement) via DISTINCT ON obs_id DESC.
run "
SELECT DISTINCT ON (ticker, period_end, statement)
  ticker, period_end::text, statement, coalesce(filing_published_at::text,''),
  coalesce(raw_jsonb->>'total_revenue',''), coalesce(raw_jsonb->>'gross_profit',''),
  coalesce(raw_jsonb->>'operating_income',''), coalesce(raw_jsonb->>'cost_of_revenue',''),
  coalesce(raw_jsonb->>'research_and_development',''), coalesce(raw_jsonb->>'net_income',''),
  coalesce(raw_jsonb->>'inventory',''), coalesce(raw_jsonb->>'total_current_assets',''),
  coalesce(raw_jsonb->>'current_net_receivables',''), coalesce(raw_jsonb->>'total_shareholder_equity',''),
  coalesce(raw_jsonb->>'capital_expenditures',''), coalesce(raw_jsonb->>'operating_cashflow','')
FROM uw_scan.fundamental_statement_obs
WHERE ticker IN ($TK) AND period_type='quarterly' AND period_end >= '2018-01-01'
ORDER BY ticker, period_end, statement, obs_id DESC" > "$OUT/prod_stmt.tsv"

# Valuation anchors: newest per ticker.
run "
SELECT DISTINCT ON (ticker) ticker, company_type, method, spot::text,
  coalesce(spot_percentile::text,''), coalesce(buy_below::text,''),
  coalesce(observe_mid::text,''), history_quarters::text, confidence, as_of::text
FROM uw_scan.valuation_anchors WHERE ticker IN ($TK)
ORDER BY ticker, as_of DESC, result_id DESC" > "$OUT/prod_val.tsv"

# Disclosed segment exposure.
run "
SELECT ticker, chain, coalesce(magnitude::text,''), coalesce(role,''), coalesce(source_ref,''), coalesce(as_of::text,'')
FROM uw_scan.company_exposure WHERE valid_to IS NULL AND chain='Optical-Communication'
ORDER BY magnitude DESC NULLS LAST" > "$OUT/prod_expo.tsv" 2>/dev/null || echo -n > "$OUT/prod_expo.tsv"

wc -l "$OUT"/prod_*.tsv
