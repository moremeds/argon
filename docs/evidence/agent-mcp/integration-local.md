# Agent MCP — integrated local verification (A + B + C, after review fixes)

Branch `feat/agent-mcp` @ `187b02ce`, 2026-10-02, MacBook. Includes the fixes for
Codex Astra review rounds 1 (A+C) and 2 (B): A task 7 `37f05b33`, task 8
`c0105a20` + `16299b45`, B `46c70c8a` + `ed638a8e`.

## CI-equivalent gates

| Gate        | Command                                                                                                        | Result                 |
| ----------- | -------------------------------------------------------------------------------------------------------------- | ---------------------- |
| ruff        | `uv run ruff check src/ tests/ scripts/`                                                                       | exit 0                 |
| unit        | `uv run pytest tests/unit -q`                                                                                  | 2939 passed            |
| integration | `UW_SCAN_DB_USER=chenxi UW_SCAN_TEST_DB_NAME=option_wizard_test_integ uv run pytest tests/integration -q -n 4` | 1729 passed, 9 skipped |
| typecheck   | `npm run typecheck`                                                                                            | exit 0                 |
| lint        | `npm run lint`                                                                                                 | exit 0                 |
| vitest      | `npx vitest run`                                                                                               | 188 files, 1498 passed |
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
list_endpoints                     111 GET; trade-insights listed=false preview listed=true
read /health, /watchlist           ok
read "/nope/x"                     ERROR not an allowlisted GET endpoint
read "/stock/%2e%2e/health"        ERROR invalid path
read "/stock/../health"            ERROR invalid path
read "//health"                    ERROR invalid path
read "/stock/..\\health"           ERROR invalid path
read "/stock/AAPL?x=1"             ERROR invalid path
read "/stock/AAPL#f"               ERROR invalid path
read "/stock/AAPL/trade-insights"  ERROR not an allowlisted GET endpoint
read preview AAPL                  ok
technicals_scan AAPL,NVDA,SPY      ok
ticker_snapshot AAPL / NVDA / SPY  ok
trade_insight_snapshots rows       before=83755 after=83755
ticker_snapshot ../health          ERROR input validation (ticker pattern)
technicals_scan ../health          ERROR input validation (ticker pattern)
regime_state                       ok
market_overview                    ok
SSE open                           200
SSE got event                      true
get_events #2                      {"events":[],"cursor":"10","more":false}
12 SSE streams open                200 x12
argon_mcp backends                 2          (one shared LISTEN client + one query)
tools/list under 12 streams        200 in 5ms
fan-out to all 12                  12
SSE got event after revoke         false
SSE stream ended after revoke      true
after revoke, same sid             401
access_log rows (one token)        error:8 ok:12
```

Writes as `argon_mcp` (psql): `permission denied` on `watchlist`, `mcp_token`,
`mcp_access_log` (DELETE), `mcp_event`, `trade_insight_snapshots`. Schema-invalid
tool calls are rejected by the SDK before the logging wrapper and leave no
access-log row (accepted; they reach no data).

## UI components (old vs new render)

B moved derivations out of 18 components into `web/lib/**`. Two `next dev`
servers against the same API: baseline `3356ef3a` (before B) on :3091 and
`187b02ce` on :3092. A Playwright crawler compared `main` innerText, with relative
ages and clock times masked:

- `/`, `/regime` and all 7 regime tabs (tide, gex, cri, vcg, grg, canary, validation)
- `/stock/{AAPL,NVDA,SPY}` and their tabs (market-structure, technicals, volatility,
  skew, flow, fundamentals, trade-insights, trade-plan)
- clicked sub-tabs: technicals → magnet, market-structure → charm, vanna

36 views, all identical, zero page errors on either build. Report:
`output/playwright/mcp-ui-diff/report*.json` (local).

Parity (`web/scripts/mcp-parity.ts`, API :8401, web :3092, AAPL NVDA SPY): exit 0,
`vpMatch: true` for all three.

## Not verifiable on this machine

- Token auth inside the container against the mini's Postgres, the Cloudflare
  tunnel and a real Grok/OpenAI agent run: operator steps after deploy
  (`docs/runbooks/agent-mcp.md`).
