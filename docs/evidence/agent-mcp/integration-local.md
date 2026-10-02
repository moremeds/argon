# Agent MCP — integrated local verification (A + B + C, after review rounds 1–5)

Branch `feat/agent-mcp` @ `c4140efa`, 2026-10-02, MacBook. Includes the fixes for
Codex Astra rounds 1 (A+C) and 2 (B) and the joint Astra + Claude Fable round 3:
A `37f05b33`, `c0105a20`, `16299b45`, `f4223bfa`, `4eabad28`; B `46c70c8a`,
`ed638a8e`, `ac8ddde6`; C `d6bafba5`.

Round 4 → 5 delta (`c4140efa..99e81104`: C `4c6ef9c5` event recovery under the
lock, A `682ef156` guard test, runbook/evidence docs) is Python + docs only, so
the Python gates were re-run at `99e81104`: ruff exit 0, unit **2942 passed**,
integration **1742 passed, 9 skipped**. The web/MCP rows below are from `c4140efa`
(no web/MCP file changed since). Round 5: Claude Fable APPROVE (two LOW residuals);
Codex Astra CHANGES NEEDED on one residual — transaction-start `now()` cannot order a
snapshot write against another scan's emit when a failed emit overlaps it — accepted
as disclosed best-effort delivery (CHANGELOG).

## CI-equivalent gates

| Gate        | Command                                                                                                        | Result                 |
| ----------- | -------------------------------------------------------------------------------------------------------------- | ---------------------- |
| ruff        | `uv run ruff check src/ tests/ scripts/`                                                                       | exit 0                 |
| unit        | `uv run pytest tests/unit -q`                                                                                  | 2941 passed            |
| integration | `UW_SCAN_DB_USER=chenxi UW_SCAN_TEST_DB_NAME=option_wizard_test_integ uv run pytest tests/integration -q -n 4` | 1735 passed, 9 skipped |
| typecheck   | `npm run typecheck`                                                                                            | exit 0                 |
| lint        | `npm run lint`                                                                                                 | exit 0                 |
| vitest      | `npx vitest run`                                                                                               | 188 files, 1507 passed |
| bundle      | `npm run build:mcp`                                                                                            | exit 0                 |
| image       | `docker build -f docker/web.Dockerfile .`                                                                      | exit 0                 |
| e2e (CI)    | `npm run test:e2e:technicals`                                                                                  | 7 passed               |

## MCP end-to-end (option_wizard_local, role argon_mcp)

API `uvicorn` :8401 and `node web/.mcp-dist/server.mjs` :8501 from this worktree,
`MCP_DATABASE_URL` as `argon_mcp`. Client: a fetch-based JSON-RPC script that mints
its own tokens via `control-argon mcp-token create`, emits events via `emit_event`,
and revokes at the end (scratchpad, not committed).

```
no token                           401
bad token                          401
initialize                         200 server=argon-mcp
tools/list                         list_endpoints,read,technicals_scan,ticker_snapshot,regime_state,market_overview,get_events
list_endpoints                     110 GET; trade-insights listed=false preview listed=true
read /health, /watchlist           ok
read "/nope/x"                     ERROR not an allowlisted GET endpoint
read "/stock/%2e%2e/health"        ERROR invalid path
read "/stock/../health"            ERROR invalid path
read "//health"                    ERROR invalid path
read "/stock/..\\health"           ERROR invalid path
read "/stock/AAPL?x=1"             ERROR invalid path
read "/stock/AAPL#f"               ERROR invalid path
read "/stock/AAPL/trade-insights"  ERROR not an allowlisted GET endpoint
read volatility/series             ERROR not an allowlisted GET endpoint (BackgroundTasks backfill)
read template ticker=^VIX          reaches API as /stock/%5EVIX (404: no local data)
read template ticker=..            ERROR invalid value for path param 'ticker'
read path=42 (schema-invalid)      ERROR input validation (and access-logged)
read preview AAPL                  ok
technicals_scan AAPL,NVDA,SPY      ok
ticker_snapshot AAPL / NVDA / SPY  ok
trade_insight_snapshots rows       before=83761 after=83761
ticker_snapshot ../health          ERROR input validation (ticker pattern)
technicals_scan ../health          ERROR input validation (ticker pattern)
regime_state                       ok
market_overview                    ok
technicals_scan * markers (AAPL)   hve_markers=9 low_vol_markers=270 vp_lvn=5 vp_zones=5
SSE open                           200
SSE got event                      true
2nd SSE on same session            409
get_events #2                      {"events":[],"cursor":"24","more":false}
12 SSE streams open                200 x12
argon_mcp backends                 2          (one shared LISTEN client + one query)
tools/list under 12 streams        200 in 3ms
fan-out to all 12                  12
SSE got event after revoke         false
SSE stream ended after revoke      true
after revoke, same sid             401
access_log rows (one token)        error:14 ok:13   (= every call, incl. 3 schema-invalid)
```

Writes as `argon_mcp` (psql): `permission denied` on `watchlist`, `mcp_token`,
`mcp_access_log` (DELETE), `mcp_event`, `trade_insight_snapshots`.

## UI components (old vs new render)

B moved derivations out of 18 components into `web/lib/**`. Two `next dev`
servers against the same API: baseline `3356ef3a` (before B) on :3091 and
`187b02ce` on :3092. A Playwright crawler compared `main` innerText, with relative
ages and clock times masked:

- `/`, `/regime` and all 7 regime tabs (tide, gex, cri, vcg, grg, canary, validation)
- `/stock/{AAPL,NVDA,SPY}` and their tabs (market-structure, technicals, volatility,
  skew, flow, fundamentals, trade-insights, trade-plan)
- clicked sub-tabs: technicals → magnet, market-structure → charm, vanna

48 views, all identical, zero page errors on either build. Report:
`output/playwright/mcp-ui-diff/report2.json` (local).

Parity (`web/scripts/mcp-parity.ts`, API :8401, web :3092, AAPL NVDA SPY): exit 0,
`vpMatch: true` for all three.

## Not verifiable on this machine

- Token auth inside the container against the mini's Postgres, the Cloudflare
  tunnel and a real Grok/OpenAI agent run: operator steps after deploy
  (`docs/runbooks/agent-mcp.md`).
