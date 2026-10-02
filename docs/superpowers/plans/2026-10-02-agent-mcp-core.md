# Agent MCP — workstream A (core / infra) plan

Spec: `docs/superpowers/specs/2026-10-02-agent-mcp-design.md`. Branch `feat/agent-mcp-core` → merges into `feat/agent-mcp`.
Owner: `argon-2e`. Workers via `herd`, ~40 turns each, different-model review of Opus-worker output.

## Tasks

### A1 — migration 153 + token CLI (Python)

- `src/uw_scan/storage/migrations/153_mcp_auth.sql`: `mcp_token`, `mcp_access_log` exactly per spec; idempotent (`IF NOT EXISTS`).
- `src/uw_scan/control_argon_mcp.py` (new module; `control_argon.py` is 731 lines): `mcp-token create <label>` prints a `secrets.token_urlsafe(32)` token ONCE and stores `sha256` hex; `revoke <label>` sets `revoked_at`; `list` shows label/created/revoked (never hashes). Wire the subcommand into `control_argon.py`'s parser only.
- Register the two tables wherever the new-temporal-table CI gates require (policy doc).
- Tests: unit for hashing + CLI arg parsing; integration for create→revoke round-trip.

### A2 — MCP server (`web/mcp/server.ts`)

- Plain `node:http` + `@modelcontextprotocol/sdk` `StreamableHTTPServerTransport` (stateful sessions, needed for SSE). Route `POST|GET|DELETE /mcp`; `GET /healthz` → 200.
- Bearer auth before the transport: `sha256(token)` lookup in `mcp_token where revoked_at is null`, 60 s in-process cache; 401 otherwise.
- Register every entry of `TOOLS` (zod `inputSchema`); wrap each handler to write one `mcp_access_log` row (label, tool, args, status ok|error, response bytes, duration).
- `ToolCtx.apiGet`: `fetch(ARGON_API_URL + "/api" + path, {method: "GET"})`, query from params, JSON or throw. No other HTTP verb exists in the module.
- SSE: on each GET stream open, call `subscribeEvents(ctx, send)` from `mcp/events.ts`; send keepalive comment every 30 s; unsubscribe on close.
- Env: `MCP_DATABASE_URL` (argon_mcp role), `ARGON_API_URL` (default `http://api:8400`), `MCP_PORT` (default 8500).

### A3 — `read` + `list_endpoints`

- Allowlist = GET paths from the API's `/openapi.json` (fetched once at boot, refreshed hourly) minus a denylist constant (empty unless the operator names paths). Path-template match (`/stock/{ticker}/technicals`).
- `list_endpoints()` → `[{path, summary, params}]`. `read(path, params)` → rejects non-allowlisted path with a clear error, else `apiGet`.

### A4 — build + image

- `web/package.json` script `build:mcp`: esbuild bundle `mcp/server.ts` → `.mcp-dist/server.mjs` (platform node, format esm; external: `pg-native`, `lightweight-charts`, `fancy-canvas` — tools import `lib/volumeProfile.ts`, never `lib/lwc/*`).
- `docker/web.Dockerfile`: run `build:mcp` in the builder stage; copy `.mcp-dist/server.mjs` into the runtime image. Web `CMD` unchanged.

### A5 — compose + tunnel + role + runbook

- `docker-compose.yml`: `mcp` service (argon-web image, `command: ["node", "mcp-server.mjs"]`, `ports: 127.0.0.1:8500:8500`, healthcheck `/healthz`); `cloudflared` service (`cloudflare/cloudflared` image, `tunnel run`, `TUNNEL_TOKEN` from env file).
- `scripts/ops/mcp_role.sql`: `CREATE ROLE argon_mcp LOGIN`, `GRANT USAGE` + `SELECT ON ALL TABLES` in `uw_scan`, `ALTER DEFAULT PRIVILEGES … GRANT SELECT`, `INSERT` on `mcp_access_log`, `INSERT, UPDATE` on `mcp_event_cursor`, sequence usage for those two.
- `docs/runbooks/agent-mcp.md`: operator steps (create tunnel + public hostname `mcp.rsiarc.com` → `http://mcp:8500` in Cloudflare dashboard, put token in `/opt/argon/.env`, run role SQL as superuser, mint tokens, configure Grok/OpenAI).

### A6 — integration + acceptance

- Merge B and C into `feat/agent-mcp`; run the full CI-equivalent locally; walk acceptance items 1, 4, 5 (+ 2, 3 with B/C); CHANGELOG `[Unreleased]` entry; one PR `feat/agent-mcp` → `main`.

## Separate PR — Q10 (`fix/web-bind-localhost`)

- `docker-compose.yml` web `ports: "127.0.0.1:3001:3001"`; runbook note for `tailscale serve --bg 3001` on the mini; check the live `/opt/argon/compose.yml` first.

## Verification per task

A1: `uv run ruff check`, `uv run pytest tests/unit/…` + targeted integration. A2/A3: vitest for auth + allowlist matching, and a local run against `control-argon up` with a minted token (curl initialize → tools/list → read). A4: `docker build -f docker/web.Dockerfile` then run `node mcp-server.mjs` in the image. A5: `docker compose config` valid.
