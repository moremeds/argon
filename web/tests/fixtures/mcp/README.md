# MCP tool fixtures (frozen real payloads)

Captured 2026-10-02T09:31Z from the argon FastAPI (main @ 18e25964) over the local
`option_wizard_local` DB. Captured with
`curl http://127.0.0.1:8499/api<path>`; one file per endpoint.

- `{aapl,nvda,spy}_technicals.json`: `GET /stock/{T}/technicals`. EOD as_of is 2026-09-18.
  `series` is trimmed to the last 500 rows (2024-09-20 → 2026-09-18). The rows are unmodified.
- `*_technicals_live.json`: `GET /stock/{T}/technicals/live`. `captured_at` is 2026-07-11, which is older
  than the EOD head. Tests that exercise the live merge must inject `now` and use a constructed
  `captured_at`-relative clock rather than wall time.
- `*_magnets.json`, `*_stock.json`, `*_trade_insights.json`: the matching stock-page endpoints.
- `spy_cockpit_{vrp,dealer,state}.json`: `GET /cockpit/SPY/{vrp,dealer,state}`.
- `regime_*.json`: `GET /regime/{gex?ticker=SPX,quotes,vol-backdrop,cri/live,cri/history?days=90}`.
- `regime.json`, `regime_vcg.json`, `regime_vcg_live.json`, `regime_vrp_macro_signal.json`,
  `regime_vrp_macro_signal_live.json`: `GET /regime`, `/regime/vcg`, `/regime/vcg/live`,
  `/regime/vrp-macro-signal`, `/regime/vrp-macro-signal/live`. These were added in the same session
  (2026-10-02, same API and DB).
- `watchlist.json`, `watchlist_chains.json`: `GET /watchlist`, `GET /watchlist/chains`.

Do not hand-edit values. To refresh, re-capture all of them together.
