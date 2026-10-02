# Agent MCP — integrated local verification (A + C, before B)

Branch `feat/agent-mcp` @ `dace05cb`, 2026-10-02, MacBook. B's four data tools
(`technicals_scan`, `ticker_snapshot`, `regime_state`, `market_overview`) are still
stubs here; re-run this after B merges.

## CI-equivalent gates

| Gate        | Command                                                                                                        | Result                 |
| ----------- | -------------------------------------------------------------------------------------------------------------- | ---------------------- |
| ruff        | `uv run ruff check src/ tests/ scripts/`                                                                       | exit 0                 |
| unit        | `uv run pytest tests/unit -q`                                                                                  | 2939 passed            |
| integration | `UW_SCAN_DB_USER=chenxi UW_SCAN_TEST_DB_NAME=option_wizard_test_integ uv run pytest tests/integration -q -n 4` | 1727 passed, 9 skipped |
| typecheck   | `npm run typecheck`                                                                                            | exit 0                 |
| lint        | `npm run lint`                                                                                                 | exit 0                 |
| vitest      | `npx vitest run`                                                                                               | 165 files, 1277 passed |
| bundle      | `npm run build:mcp`                                                                                            | exit 0                 |
| image       | `docker build -f docker/web.Dockerfile .`                                                                      | exit 0                 |

## End-to-end (option_wizard_local, role argon_mcp)

Migrations 153/154 and `scripts/ops/mcp_role.sql` re-applied with `ON_ERROR_STOP=1`:
all exit 0 (idempotent). API: `uvicorn` on :8401 from this worktree. MCP:
`node web/.mcp-dist/server.mjs` on :8501 with `MCP_DATABASE_URL` as `argon_mcp`.
Client: a fetch-based JSON-RPC script (scratchpad, not committed).

```
no token                     401
bad token                    401
initialize                   200 server=argon-mcp sid=true
tools/list                   list_endpoints,read,technicals_scan,ticker_snapshot,regime_state,market_overview,get_events
list_endpoints               111 GET endpoints
read /health                 ok
read /watchlist              ok
read /nope/x                 ERROR not an allowlisted GET endpoint
read /stock/%2e%2e/health    ERROR invalid path
read /stock/../health        ERROR invalid path
read //health                ERROR invalid path
SSE open                     200
SSE got argon_event          data: {"jsonrpc":"2.0","method":"notifications/argon_event","params":{"event":{"id":"5","kind":"regime","subject":"VERIFY","basis":"live",...
get_events #1                ok (backlog delivered)
get_events #2                ok {"events":[],"cursor":"5","more":false}
after revoke, same sid       401   (revocation immediate, no cache)
```

Writes as `argon_mcp` (psql):

```
update uw_scan.watchlist ...            ERROR: permission denied for table watchlist
insert into uw_scan.mcp_token ...       ERROR: permission denied for table mcp_token
delete from uw_scan.mcp_access_log ...  ERROR: permission denied for table mcp_access_log
insert into uw_scan.mcp_event ...       ERROR: permission denied for table mcp_event
```

`mcp_access_log`: one row per tool call with label, tool, ok|error, bytes, duration
(rejected `read` calls logged as `error`).

## Not verifiable on this machine

- Token auth inside the container: Docker Desktop for Mac does not publish
  `--network host` ports, and local Postgres listens on localhost only. The mini's
  `pg_hba.conf` is `host all all` (scram) for 127.0.0.1, 192.168.50.0/24 and the
  tailnet, with `listen_addresses='*'`, the same rules the api container already
  uses, so `argon_mcp` needs only the operator's role and password step. Check
  it on the mini after deploy (runbook).
- Cloudflare tunnel, Grok/OpenAI connection: operator steps after deploy.
