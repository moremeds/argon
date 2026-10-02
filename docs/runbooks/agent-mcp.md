# Agent MCP — operator runbook

Remote, read-only MCP server for cloud agents (Grok, OpenAI) and local agents.
One public endpoint — `https://mcp.rsiarc.com/mcp` — fronted by a Cloudflare
named tunnel. Everything else (web :3001, api :8400) stays off the internet.

Surface: 7 tools (`list_endpoints`, `read`, `technicals_scan`,
`ticker_snapshot`, `regime_state`, `market_overview`, `get_events`) + an SSE
event stream (`GET /mcp` with `Accept: text/event-stream`).

## 1. Named tunnel (one time, Cloudflare dashboard)

1. Zero Trust → Networks → Tunnels → **Create a tunnel** → Cloudflared. Name it
   (e.g. `argon-mcp`).
2. Copy the **tunnel token** Cloudflare shows — it is the only credential the
   connector needs (cert.pem is not used with token mode).
3. Public hostname → **Add**: subdomain `mcp`, domain `rsiarc.com` → service
   type **HTTP**, URL `mcp:8500` (the compose service name + port — the tunnel
   runs on the compose network). Save.

## 2. /opt/argon/mcp.env (NOT .env)

The mcp + cloudflared services read ONLY this file — keep it separate from
`/opt/argon/.env`, which holds the `argon_app` DB password and provider keys
the public-facing containers must not carry:

```
install -m 600 /dev/null /opt/argon/mcp.env   # root-only, like .env
cat >> /opt/argon/mcp.env <<'EOF'
MCP_DATABASE_URL=postgres://argon_mcp:<password>@host.docker.internal:5432/option_wizard
TUNNEL_TOKEN=<token from step 1>
EOF
```

Do NOT put either var in `/opt/argon/.env` — the other services already have
their own env and the mcp pair deliberately does not read it.

`ARGON_API_URL` defaults to `http://api:8400` in compose — do not override.
Sizing note: if a `mem_limit` is ever added to the mcp service keep it
>= 512 MB — the technicals warm cache alone runs ~170 MB.

## 3. Database role (one time, run as superuser on the mini)

```
psql -U postgres -d option_wizard -f scripts/ops/mcp_role.sql
\password argon_mcp          # set the password that goes in MCP_DATABASE_URL
```

The role is `LOGIN`, SELECT-only on `uw_scan` (existing + future tables via
`ALTER DEFAULT PRIVILEGES FOR ROLE argon_app`), plus two writes:
`INSERT mcp_access_log`, `SELECT/INSERT/UPDATE mcp_event_cursor`. Migrations
153+154 are applied by the api service's self-migrate on next deploy.

## 4. Bring the services up

```
cd /opt/argon
docker compose up -d mcp cloudflared
docker compose ps            # mcp healthy, cloudflared running
curl -s http://127.0.0.1:8500/healthz   # {"ok":true} on the mini itself
```

## 5. Mint / revoke tokens

Inside the **api** container (control-argon ships in the app image):

```
docker compose exec api python -m uw_scan.control_argon mcp-token create grok
# prints the raw token ONCE — hand it to the agent config, then it is gone
docker compose exec api python -m uw_scan.control_argon mcp-token list
docker compose exec api python -m uw_scan.control_argon mcp-token revoke grok
```

Revocation takes effect on the token's **next request** (no cache window —
even an already-open session gets 401).

## 6. Agent configuration

Every agent gets the same URL + its own bearer token:

- URL: `https://mcp.rsiarc.com/mcp`
- Header: `Authorization: Bearer <token from step 5>`

Grok / OpenAI "custom MCP connector" UI: paste the URL, add the Authorization
header. Local agents (Claude Code, Codex): same URL+header in their MCP
client config. First call each run should be `get_events` (drains the
token's durable cursor), then `list_endpoints` for the readable GET surface.

## Failure modes

| Symptom | Check |
| --- | --- |
| 401 on everything | token revoked or wrong — `mcp-token list` on the mini |
| 502 from Cloudflare | `docker compose ps mcp` unhealthy → `docker compose logs mcp` |
| tunnel container down | `TUNNEL_TOKEN` unset/wrong in `.env` |
| reads return empty | `MCP_DATABASE_URL` points at a DB without migrations 153+154 |
| SELECT works, calls 500 | argon_mcp missing `INSERT mcp_access_log` — re-run step 3 |
