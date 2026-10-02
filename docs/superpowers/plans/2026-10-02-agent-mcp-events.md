## Execution contract — read before Task 1

You are worker `argon-c-impl` (kind `devin`, requested model `swe-2-max`), working in
`/Users/chenxi/projects/argon/.worktrees/agent-mcp-events` on branch `feat/agent-mcp-events`.
The operational lead and final acceptor is the Claude Code session in herdr pane `wD:p3`
(Claude Opus 5.5); `LEAD_PANE=wD:p3` receives reports. You cannot accept or expand scope.
Mode: implementation. Commit policy: one commit per task (M1..M5 below = Task 1..5), conventional
style `feat(mcp-events): …` / `test(mcp-events): …`.

Before project edits, load the global rules (`~/.config/devin/AGENTS.md`, `~/.claude/CLAUDE.md`),
the repo `CLAUDE.md` and this plan. In your Task 1 report evidence, state cwd, requested and observed
model (canonical: SWE), and the rule files actually loaded. Do not spawn further workers.

1. Scope. Implement only Tasks 1–5 (= M1–M5), in order. Anything else: report it, do not do it.
2. Files. You own: `src/uw_scan/storage/migrations/154_mcp_events.sql`, `src/uw_scan/storage/mcp_events.py`,
   `src/uw_scan/scanners/{cri,vcg}.py`, `src/uw_scan/worker/jobs/{vrp_macro_signal,regime_live}.py`,
   `src/uw_scan/alerts.py`, `src/uw_scan/worker/scheduler.py` (retention job only),
   `src/uw_scan/reports/data_gap_healer.py` (REGISTRY entries only), `docs/runbooks/data-gap-dataset-policy.md`
   (regenerated, never hand-edited), `web/mcp/events.ts`, `web/mcp/tools/get_events.ts`,
   `web/tests/unit/mcp/**`, new tests under `tests/unit/**` and `tests/integration/**`, `output/herd/agent-mcp-events/**`.
   You never write: `web/mcp/{server,types}.ts`, `web/mcp/tools/index.ts`, other `web/mcp/tools/*`,
   `web/package*.json`, any `.env*`, any migration other than 154, `AGENTS.md`/`CLAUDE.md`.
2b. Ground truth: the spec `docs/superpowers/specs/2026-10-02-agent-mcp-design.md` ("Interface
   contracts", "Event emission"), `web/mcp/types.ts` (`EventStreamHook` takes `(ctx, send, close)`),
   `memory reference: new temporal tables trip test_data_gap_full_coverage + test_data_gap_dataset_policy`.
   Read the code you change; do not trust this plan's line-level claims without checking.
3. Environment. Commands only inside this worktree; temp files under `output/herd/agent-mcp-events/tmp/`.
   DBs: ONLY `option_wizard_test_events` (integration tests: `UW_SCAN_DB_NAME=option_wizard_test_events`)
   and `option_wizard_local` on 127.0.0.1 for Task 5. Never the mini, never `option_wizard`, never Tailscale
   100.66.147.98. No network calls besides local Postgres. No `git checkout`/`switch`/`stash`/`reset`.
   Use `uv run …` only (never bare python/pip/pytest).
4. Evidence. Each task leaves `output/herd/agent-mcp-events/t<n>.md` with exact commands, exit codes, and
   pasted (trimmed) output.
5. Commits. Commit each task. No push, PR, merge, rebase. NO attribution trailers: no `Co-Authored-By`,
   no `Generated with` — a commit carrying one is rejected.
6. Review gate. Stop after every task. Report exactly one line via
   `herdr agent prompt wD:p3 "herd-report argon-c-impl task <n>: commit <sha>, evidence <path>, deviations: <text|none>"`.
   Do not start the next task until the lead replies `herd-continue <n+1>`.
7. Rejections. On `herd-reject <n>: <reason>`, fix on top with a new commit; never amend.
8. Blocked. Pre-approved: edit the owned files; `uv run ruff …`, `uv run pytest …`, `bash scripts/migrate.sh`
   against option_wizard_local/option_wizard_test_events, `cd web && npm run typecheck|test|lint`,
   `npx vitest …`, `npx tsx …` for a local check script, `git add/commit/status/diff/log`. Anything else → ask.
9. Deviations. Name any step not done as written in the report line.

# Agent MCP — workstream C (events) plan

Spec: `docs/superpowers/specs/2026-10-02-agent-mcp-design.md` ("Interface contracts", "Event emission" bind).
Branch `feat/agent-mcp-events` → merges into `feat/agent-mcp`. Worktree `.worktrees/agent-mcp-events`.

## Non-goals

No edits to `web/mcp/{server,types}.ts`, `web/mcp/tools/index.ts`, other tools, `web/package*.json`.
No cursor advance on the SSE path (SSE is a live tap; the cursor belongs to `get_events`).
Technicals are not events.

## M1 — schema + emitter core (Python)

- `src/uw_scan/storage/migrations/154_mcp_events.sql`: exactly the spec DDL for `mcp_event` and
  `mcp_event_cursor`, idempotent (`IF NOT EXISTS`), plus index `(kind, subject, basis, emitted_at DESC)`
  for the cooldown probe.
- `src/uw_scan/storage/mcp_events.py`:
  - `emit_event(conn, *, kind, subject, basis, payload, cooldown=None) -> int | None` — first statement
    `SELECT pg_advisory_xact_lock(<fixed MCP_EVENT_LOCK int>)`: held to the caller's commit, it forces
    commit order = id order (else `get_events` can advance past an uncommitted lower id and lose it) and
    makes probe+insert atomic. Then the cooldown probe
    (`emitted_at > now() - cooldown` on the same triple) → `INSERT … RETURNING id` →
    `SELECT pg_notify('mcp_event', id::text)`. Does NOT commit; NOTIFY delivers on the caller's commit.
    Returns the id, or None when the cooldown suppressed it.
  - `emit_on_change(conn, *, kind, subject, basis, prev, new, payload, cooldown=None)` — emits only when
    `prev is not None and new is not None and prev != new` (first-ever row is not a change; a degraded
    scan yielding None must not emit a flip to null). Payload gets `{"from": prev, "to": new}` merged.
  - `purge_old_events(conn, days=30) -> int`.
- Gates: register ALL FOUR MCP tables (`mcp_token`, `mcp_access_log` from A's 153, plus `mcp_event`,
  `mcp_event_cursor`) — lead-approved; A does not touch REGISTRY or the policy doc — in `REGISTRY` (`reports/data_gap_healer.py`) as
  `audit_mode="excluded"`, group `operational_provenance`, with a `reason`; regenerate
  `docs/runbooks/data-gap-dataset-policy.md`.

Verify: integration test `tests/integration/storage/test_mcp_events.py` — insert + a second connection
`LISTEN mcp_event` receives the id after commit; cooldown suppresses a repeat within the window and
allows it after; `emit_on_change` no-ops on equal / None prev; purge deletes only >30d rows.

## M2 — emitters on state change

Each site reads the previous persisted state BEFORE writing, then calls `emit_on_change` and commits
immediately (short tx — ids must commit in order or `get_events`' `id > cursor` can skip one).

| Site                                                                      | kind               | subject            | state                         | basis | cooldown |
| ------------------------------------------------------------------------- | ------------------ | ------------------ | ----------------------------- | ----- | -------- |
| `scanners/cri.py::run` (only when `as_of is None`, i.e. not gap recovery) | `cri_regime`       | `CRI`              | `payload["cri"]["level"]`     | eod   | none     |
| `scanners/cri.py::run_live` (when `persist`)                              | `cri_regime`       | `CRI`              | same                          | live  | 1 h      |
| `scanners/vcg.py::run` (as_of None)                                       | `vcg_regime`       | proxy (e.g. `HYG`) | `payload["signal"]["regime"]` | eod   | none     |
| `scanners/vcg.py::run_live` (persist)                                     | `vcg_regime`       | proxy              | same                          | live  | 1 h      |
| `worker/jobs/vrp_macro_signal.py`                                         | `vrp_macro_signal` | name               | `action`                      | eod   | none     |
| `worker/jobs/regime_live.py` VRP leg                                      | `vrp_macro_signal` | `SPX`              | `action`                      | live  | 1 h      |
| `alerts.send_alert`                                                       | `ops`              | title              | — (always)                    | ops   | none     |

Prev-state reads: CRI/VCG `fetch_latest(basis=…)` (VCG also `proxy=`); VRP
`fetch_latest_vrp_macro_signals([name], basis=…)`. VRP EOD: collect changes inside the loop, emit them
just before the existing single `repo.conn.commit()` (not mid-loop — the loop holds a long tx).
`send_alert`: emit through its own autocommit connection (`storage.ops_health._ops_conn` pattern) BEFORE the
empty-webhook early return, in its own never-raise `try`. Return value keeps meaning "webhook delivered".
Webhook failure and DB-emit failure are independent; neither raises (`may_spend` depends on that).

Every site must read prev BEFORE the insert: CRI/VCG `insert_snapshot` self-commits, so a read after it
compares the row to itself and never emits. Verify: integration tests per site that seed a prior snapshot
with a different state and assert exactly one `mcp_event` row, AND same state → zero rows (the second case
is what catches read-after-write); `send_alert` with no webhook URL still emits.

## M3 — retention job

Scheduler `mcp_event_retention`, daily 04:10 ET, calls `purge_old_events`, pinned to the primary worker the
same way `_sector_rs_daily` is gated (one role runs it). No flag (pure housekeeping).

## M4 — TS side

- `web/mcp/tools/get_events.ts`: input `{ limit?: int 1..500 = 100 }`. One transaction on a pool client:
  `INSERT INTO mcp_event_cursor(token_label) VALUES ($1) ON CONFLICT (token_label) DO UPDATE SET token_label = EXCLUDED.token_label RETURNING last_event_id`
  (locks the row; concurrent calls for one token serialize) → `SELECT … FROM mcp_event WHERE id > $cursor ORDER BY id LIMIT $limit + 1` (the extra row sets `more`)
  → `UPDATE mcp_event_cursor SET last_event_id = $max, updated_at = now()` when rows came back → COMMIT.
  Returns `{ events: [...], cursor, more: boolean }`. Only writes `mcp_event_cursor` (argon_mcp-legal).
- `web/mcp/events.ts`: `subscribeEvents` takes a dedicated `ctx.db.connect()` client, `LISTEN mcp_event`,
  on notification `SELECT … FROM mcp_event WHERE id = $1` → `send(row)`; unsubscribe = `UNLISTEN` + release.
  Contract `EventStreamHook = (ctx, send, close)`: on a pg client error, release the client and call
  `close()`; server.ts ends the stream and the client's reconnect re-invokes the hook. No reconnect
  logic inside the hook.
- vitest: `web/tests/unit/mcp/getEvents.test.ts` with a fake pg client asserting the statement order,
  the cursor advance to max id, and no UPDATE on empty.

## M5 — acceptance item 3 (real DB, local)

Script-free check against `option_wizard_local` after `bash scripts/migrate.sh`: a node runner subscribes
via `subscribeEvents`, Python `emit_on_change` simulates a CRI flip (`NORMAL→ELEVATED`) and commits; the
subscriber receives it within 1 s; `get_events` as token `t2` returns it once, then empty. Evidence
pasted into the merge message. Full SSE-over-HTTP check runs at integration once A's `server.ts` lands.

## Test DB

Three MCP worktrees run integration tests concurrently; use a private DB so `DROP SCHEMA` does not clash:
`UW_SCAN_DB_NAME=option_wizard_test_events` for every integration run in this worktree.

## Gate before merging into `feat/agent-mcp`

`uv run ruff check src/ tests/ scripts/`, `uv run pytest tests/unit/`, the new + touched integration
tests (cri/vcg scanner, regime_live, vrp, data-gap gates), `cd web && npm run typecheck && npm run test`.
