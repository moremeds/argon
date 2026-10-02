# Agent MCP — design + parallel work split

Status: APPROVED by the operator 2026-10-02 (grilling session, Q1–Q31). Lead session: `argon-2e`.

## Goal

A single-user, read-only remote MCP server so cloud agents (Grok bot, OpenAI) and local
agents can read everything the argon web UI shows, and receive pushed events.

## Decisions (binding)

| Area                         | Decision                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Protocol                     | One remote MCP server, streamable HTTP. No WebSocket.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| Ingress                      | `https://mcp.rsiarc.com/mcp` via a Cloudflare **named** tunnel (`rsiarc.com` NS is already Cloudflare). `cloudflared` runs as a container in `/opt/argon/compose.yml` and routes ONLY to the `mcp` service. SSE keepalive every 30 s (Cloudflare drops idle at 125 s). Web + API stay off the public internet.                                                                                                                                                                                                                                                                                                                                              |
| Process                      | Reuses the `argon-web` image (no new image, no release-workflow change), separate compose service `mcp` with its own command. `docker/web.Dockerfile` gains a step that bundles `web/mcp/server.ts` (+ the `web/lib` code it imports) into one JS file.                                                                                                                                                                                                                                                                                                                                                                                                     |
| Auth                         | Bearer token only (operator confirmed Grok bot + OpenAI both send bearer). One token per agent (`grok`, `openai`, `local`, …). DB stores only the hash. `uv run control-argon mcp-token create <label>` / `revoke <label>`. 401 on missing/revoked. No OAuth.                                                                                                                                                                                                                                                                                                                                                                                               |
| Read-only guarantee          | Dedicated Postgres role `argon_mcp`: SELECT on business tables, write ONLY on `mcp_access_log` and `mcp_event_cursor`. The `read` tool forwards only GET, only to allowlisted paths. The MCP code contains no non-GET call to the internal API.                                                                                                                                                                                                                                                                                                                                                                                                             |
| Access log                   | One row per tool call: token label, tool, args, status, response bytes, duration.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Tools                        | `list_endpoints`, `read(path, params)`, `technicals_scan(tickers?, fields?)`, `ticker_snapshot(ticker)`, `regime_state()`, `market_overview()`, `get_events()`, plus SSE subscription.                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| "UI shows it ⇒ bot reads it" | Browser-computed values are served by importing the SAME TypeScript (`web/lib/*`) the UI uses — no Python port. Component-inline derivations (cockpit VRP z, vanna/charm totals, CRI components, VIX/VIX3M, GEX retag, chain-flow C/P, etc.) are extracted into `web/lib` functions in this same change; their values fold into `ticker_snapshot` / `regime_state`.                                                                                                                                                                                                                                                                                         |
| technicals_scan              | All ~170 active watchlist tickers. Every Technicals-tab value: API-served (SMA, dual MACD, RSI, z, RV20, kinematics, RS, forward returns, magnets, VWAP anchor) and browser-computed (EMA 5/20/50, BB, ATR band, vol MA50 + HVE/low-vol markers, chanlun 笔/中枢/买卖点/线段/背离/★weekly resonance at UI default params, volume profile POC/VA/shelves/LVN, FVG, return distribution, kinematics verdict, magnet tiles). EOD layer + live layer, each with `as_of`. `fields` + `tickers` filters, columnar output. EOD layer cached in memory, invalidated after the nightly technicals refresh; live layer merged at read time (same as `mergeLiveHead`). |
| Events pushed                | VRP macro signal flip; CRI / VCG regime change (EOD AND live; live has a 1 h cooldown per subject); the two existing ops alerts (`send_alert`: UW budget wall, job failing). Technicals are NOT events — the bot reads and judges.                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Event delivery               | Durable inbox table, 30-day retention, per-token cursor. Local agents: SSE subscription (real-time). Cloud agents: `get_events()` at the start of each run returns unread and advances the cursor. ChatGPT MCP Events webhooks = v2.                                                                                                                                                                                                                                                                                                                                                                                                                        |
| Out of scope                 | Writes of any kind, OAuth, multi-user, nightly chanlun persistence.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Separate PR                  | Q10: web container binds `127.0.0.1:3001` + `tailscale serve` (LAN currently reaches all 18 mutating routes through `:3001`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

## Interface contracts (code against these; changes go through the lead)

### Branches / worktrees

- Integration branch: `feat/agent-mcp` (one PR → `main` at the end). Sub-branches merge into it.
- Worktrees under `.worktrees/` only. **Never `git checkout` in the primary checkout.**

| Workstream                          | Session           | Branch                  | Worktree                      |
| ----------------------------------- | ----------------- | ----------------------- | ----------------------------- |
| A core/infra + integration          | `argon-2e` (lead) | `feat/agent-mcp-core`   | `.worktrees/agent-mcp-core`   |
| B data tools + `web/lib` extraction | `argon-fa`        | `feat/agent-mcp-data`   | `.worktrees/agent-mcp-data`   |
| C events                            | `argon-69`        | `feat/agent-mcp-events` | `.worktrees/agent-mcp-events` |

### Migration numbers (pre-assigned — do not take others)

- `153_mcp_auth.sql` (A): `mcp_token(id serial pk, label text unique not null, token_hash text not null, created_at timestamptz default now(), revoked_at timestamptz)`, `mcp_access_log(id bigserial pk, token_label text, tool text, args jsonb, status text, response_bytes int, duration_ms int, at timestamptz default now())`.
- `154_mcp_events.sql` (C): `mcp_event(id bigserial pk, kind text not null, subject text not null, basis text not null check (basis in ('eod','live','ops')), payload jsonb not null, emitted_at timestamptz default now())`, `mcp_event_cursor(token_label text pk, last_event_id bigint not null default 0, updated_at timestamptz default now())`.
- The `argon_mcp` role is created OUT-OF-BAND (no migration creates roles; `argon_app` is NOSUPERUSER). A owns `scripts/ops/mcp_role.sql` + the runbook step. Grants must cover future tables (`ALTER DEFAULT PRIVILEGES`).

### MCP tool module shape (A defines in the first core commit; B/C only add files)

```
web/mcp/types.ts        // McpTool, ToolCtx  (A)
web/mcp/server.ts       // transport, bearer auth, access log, tool registry, SSE keepalive (A)
web/mcp/tools/index.ts  // the registry list (A creates with all 7 entries as stubs)
web/mcp/tools/<name>.ts // one file per tool: export const tool: McpTool
```

`McpTool = { name, description, inputSchema (zod), handler(args, ctx: ToolCtx) => Promise<unknown> }`
`ToolCtx = { db: pg.Pool /* argon_mcp role */, apiGet(path, params) /* GET-only, internal API */, tokenLabel: string }`

Ownership: A — `list_endpoints`, `read`. B — `technicals_scan`, `ticker_snapshot`, `regime_state`, `market_overview`. C — `get_events` + the SSE subscription handler (A exposes the hook in `server.ts`; C fills it).

### Columnar response shape (all bulk tools)

`{ as_of: { eod: <iso>, live: <iso|null> }, columns: string[], rows: unknown[][] }`. Default `fields` = a compact set chosen by B and documented in the tool description.

### Event emission (Python side, C)

- `src/uw_scan/storage/mcp_events.py`: `emit_event(conn, *, kind, subject, basis, payload, cooldown=None)`, which inserts into `mcp_event` and runs `NOTIFY mcp_event, '<id>'`. `cooldown` (timedelta) skips the insert if the same `(kind, subject, basis)` was emitted within the window. Live regime emitters pass `timedelta(hours=1)`.
- Emitters run on a state CHANGE vs the previous persisted state, never on every scan.
- `alerts.send_alert` also calls `emit_event(kind='ops', basis='ops', …)` and keeps its webhook behaviour.
- Retention: a daily job deletes `mcp_event` rows older than 30 days.
- The TS side `LISTEN mcp_event` for real-time SSE fan-out; `get_events` reads `id > cursor` and advances `mcp_event_cursor`.

## Acceptance (definition of done)

1. Claude Code connects to `https://mcp.rsiarc.com/mcp` with a bearer token; all 7 tools callable; `technicals_scan` returns every active watchlist ticker.
2. For 3 sampled tickers, the bot's EMA, chanlun points and volume profile equal the web UI's values exactly.
3. A simulated CRI flip arrives in real time on a local SSE subscription; a different token's `get_events` returns it once, then returns empty.
4. `read` rejects any non-allowlisted path; an `UPDATE` as `argon_mcp` fails with a permission error.
5. Missing/revoked token → 401; every call writes one `mcp_access_log` row.
6. Extracted components: existing vitest + e2e stay green.
7. Q10 PR: `:3001` unreachable from the LAN, reachable over Tailscale.
8. One real run by a Grok or OpenAI agent (operator configures its token).

## Process

Each session writes a bounded plan for its workstream and runs it via `/execute-plan`, delegating labor through `herd` (~40-turn budget per worker; Opus-worker output reviewed by a different model). Cross-workstream needs → `SendMessage` to `argon-2e`. CHANGELOG `[Unreleased]` entry: A writes it at integration.

## Open facts to verify early

- B, FIRST: confirm `web/lib/{indicators,chanlun,chanlunSeg,volumeProfile,fvg}.ts` and `web/lib/lwc/volumeProfile.ts` import cleanly in plain Node (no React/DOM/lightweight-charts). Report to `argon-2e` immediately; this also gates A's bundling plan.
- A: the live `/opt/argon/compose.yml` on the mini vs the repo template (port binds, Q10).
