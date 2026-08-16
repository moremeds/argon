# 2026-08-16 — v0.12.0 release + populating the fundamental lane on prod

Point-in-time operational record. Written so this session can be abandoned at any
moment and picked up by someone (or some agent) with no other context.

**Everything below is idempotent.** Nothing here is harmed by being re-run.

---

## 1. What shipped

**v0.12.0**, PR #333, tag published `2026-08-16T04:13:14Z`, `prerelease: false`.
0.11.4 → 0.12.0. Contents: fundamentals tier-1 ingest, validated composite,
valuation anchors, card-flip + `GET /stock/{ticker}/fundamentals/statements`;
macro immutable evidence contract. All four release jobs green.

Migrations **114, 115, 117, 118** applied to prod for the first time.

**Deploy cost ~200s of hard API downtime** — `api` runs
`migrate_runner && exec uvicorn`, so every `/api/*` route returned HTTP 500 for
3m20s while migrations ran. Next.js kept serving pages 200 throughout, so "the
web is up" was NOT evidence the deploy was fine. Recovery is the real signal:
uvicorn only starts if the migrations succeeded.

Verify: `curl -s http://100.66.147.98:3001/api/health | jq .version` → `0.12.0`

---

## 2. Why the fundamentals card was dark, and what is being done

Migrations create the schema. **Nothing populates it.** Immediately post-deploy
every fundamental table on prod read zero:

```
universe 0 · statement_obs 0 · method_versions 0 · method_state 0
scores 0 · company_type 0 · valuation_anchors 0
```

The card returned honest errors from working routes, not breakage:
`/fundamentals` → 503 `"no active fundamental method version"`,
`/fundamentals/statements` → 404 `"no statements for NVDA"`.

`fundamental_method_versions` is **not seeded by migration** — it is written by
the scoring code (`storage/fundamental_scores.py`), so it appears only once step
3 below runs against a non-empty panel.

### How this is being run

SSH to the mini is **denied from this laptop** (`publickey`). Its Postgres **is**
reachable on Tailscale (`100.66.147.98:5432`), and the DB tripwire sanctions this
exact pair, so every command below runs from the MacBook with:

```bash
export UW_SCAN_DB_HOST=100.66.147.98
export UW_SCAN_DB_NAME=option_wizard
```

Both are required. Setting only the host trips the guard (mini host + local name).

### Step 1 — seed the universe — DONE

```bash
uv run python scripts/seed_fundamental_universe.py            # --dry-run first
```
Result: `core=25 ranked=257`, **257 distinct tickers**. Zero external calls.

### Step 2 — ingest statements — RUNNING at time of writing

```bash
KEY=$(grep -m1 '^UW_SCAN_API_KEY=' /Users/chenxi/projects/argon/.env | cut -d= -f2-)
UW_SCAN_API_KEY="$KEY" \
  uv run python scripts/backfill/fundamental_ingest_backfill.py --tier ranked
```

4 UW calls per ticker → ~1,030 total against a 120k/day budget. Expect ~63,000
rows (~247/ticker). **Safe to re-run** — content-hash + `ON CONFLICT`, so a
killed run resumes by simply starting again; already-ingested tickers cost their
4 calls and write nothing.

The script logs only at completion. Track it by row growth instead:

```bash
uv run python -c "
import sys; sys.path.insert(0,'src')
from uw_scan.config import Settings
import psycopg
s=Settings.from_env()
with psycopg.connect(s.db_dsn(), connect_timeout=15) as c, c.cursor() as cur:
    cur.execute('select count(*), count(distinct ticker) from uw_scan.fundamental_statement_obs')
    print('rows %s | tickers %s/257' % cur.fetchone())
"
```

Progress observed: 3 → 167 → 183 tickers. **If the ticker count is stuck and no
process is running, just re-run step 2.**

### Step 3 — refresh: routing → method version → scores → bands — NOT YET RUN

```bash
uv run python -c "
import sys; sys.path.insert(0,'src')
from uw_scan.config import Settings
from uw_scan.worker.jobs.fundamental_refresh import fundamental_refresh
import psycopg
s=Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    print(fundamental_refresh(conn=conn, settings=s))
"
```

Zero external calls. **This is the step that clears the 503.**

It is also **already scheduled on the mini** — `fundamental_refresh`, nightly
18:20 ET, massive-0, `UW_SCAN_FUNDAMENTAL_REFRESH_ENABLED` default on. So if
nobody runs it by hand, prod self-heals at the next 18:20 ET **provided step 2
finished**.

Caveat if run from the MacBook: the anchor-band stage reads unadjusted closes
from the **local parquet lake**, so a laptop run computes prod bands from the
laptop's mirror. The mini's own lake mount is unverified (no SSH).

---

## 3. What to verify when it is done

```bash
uv run python -c "
import sys; sys.path.insert(0,'src')
from uw_scan.config import Settings
import psycopg
s=Settings.from_env()
q=[('universe','select count(*) from uw_scan.fundamental_universe where removed_at is null'),
   ('statement rows','select count(*) from uw_scan.fundamental_statement_obs'),
   ('statement tickers','select count(distinct ticker) from uw_scan.fundamental_statement_obs'),
   ('method_versions','select count(*) from uw_scan.fundamental_method_versions'),
   ('method_state','select count(*) from uw_scan.fundamental_method_state'),
   ('company_type','select count(*) from uw_scan.fundamental_company_type'),
   ('scores','select count(*) from uw_scan.fundamental_scores'),
   ('valuation_anchors','select count(distinct ticker) from uw_scan.valuation_anchors')]
with psycopg.connect(s.db_dsn()) as c, c.cursor() as cur:
    for k,sql in q:
        cur.execute(sql); print('%-20s %s' % (k, cur.fetchone()[0]))
"
```

Expected, benchmarked against the identical local run:

| | expected | why |
|---|---|---|
| universe | 257 | seeded |
| statement tickers | 257 | tier `ranked` |
| method_versions / method_state | 1 / 1 | written by the scoring code |
| company_type | 257 | routing covers everything |
| scores | 257 | **locally the scorer has ZERO failures on its input** |
| valuation_anchors tickers | ~254 | 254/257 have `1d.parquet`; 3 legitimately lack bars |

Then the card itself:

```bash
curl -s http://100.66.147.98:3001/api/stock/NVDA/fundamentals | head -c 200
```
A 200 with a body replaces the 503. Web check: `/stock/NVDA` → Fundamentals tab.

**If scores land but `valuation_anchors` is ~0**, the band stage could not read
the lake. That is the answer to open question #3 in
`docs/superpowers/plans/2026-08-13-fundamental-lane-next.md`, and it means the
band was never accruing on the mini.

---

## 4. The separate, unresolved incident — `full_scan` dead since 2026-08-10

**Not caused by this release. Not fixed by it. Independent of everything above.**

- `/api/health` → `ok: false`, `"63 expected full scans missed"`,
  `last_full_scan_at` **2026-08-11**, scheduler lag 116h.
- **26 of 54 tables frozen**; 19 at a hard cliff (15 stop 2026-08-10, 4 stop
  2026-08-11). Not decay — one event.
- The frozen set is exactly the **per-strike chain level** `full_scan` writes:
  `greeks_by_expiry_strike`, `oi_by_strike`, `option_chain_per_strike`,
  `interpolated_iv_snapshots`, `iv_rank_history`, `iv_term_snapshots`,
  `options_volume_daily`, `risk_reversal_skew_history`,
  `exposures_by_expiry_strike`, `uw_positioning`, `gex_snapshots`,
  `exposures_summary`, `max_pain_by_expiry`, `pcr_history`, `vcg_snapshots`, …
- **Diagnostic pair:** `gex_snapshots` (full_scan) frozen while
  `uw_gex_levels_daily` (own job) current. Same domain, different job path.
- Dedicated jobs ran clean through 2026-08-14. `ws_consumer` healthy on
  `xenon_ws` throughout. **`option_surface_grid_daily` is INTACT (2026-08-14)** —
  the only dataset where a missed night is unrecoverable.
- v0.11.4 released 2026-08-10 — tight correlation with the cliff, **not proof**.
- The v0.12.0 restart did **not** clear it, but 2026-08-16 is a **weekend**, so
  `full_scan` would not fire anyway. **The hypothesis is untested, not refuted.**

### THE ONE THING TO CHECK ON THE NEXT TRADING DAY

```bash
curl -s http://100.66.147.98:3001/api/health | jq '{ok, reason, last_full_scan_at}'
```

- `last_full_scan_at` moves off 2026-08-11 → it was wedged worker state; the
  restart fixed it. Backfill the 19 frozen tables from UW.
- Still 2026-08-11 → **v0.11.4 carries a defect that v0.12.0 inherited** (nothing
  in v0.12.0 touches the scan path). That outranks all fundamental-lane work.

### Also worth fixing

Health reports codex/claude AI workers 0/2 healthy since 2026-07-08 because it
expects 2 of each while docker-compose deliberately runs none. A permanent red
is how a real one went unnoticed for five days.

---

## 5. Where the rest of the work lives

- Plan: `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` (3 PRs +
  decision record D1–D6). **Nothing in it is built.**
- P4 verdict: `docs/research/2026-08-13-fundamental-concentration-axis/VERDICT.md`
  — the earlier "geography 0/257" was a probe bug; corrected to segment 184/401,
  geography 128/401. Computable, still **not** an edge.
- Cluster verdict: `docs/research/2026-08-13-ai-capex-demand-ledger/CLUSTER-VERDICT.md`
- Branch `misc/capex-demand-ledger` — research commits, **no PR opened yet**.
