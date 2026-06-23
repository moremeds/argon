# Regime page data source — local FS vs R2

Date: 2026-06-02
Status: decision report (no code change yet)

## TL;DR

Keep the layered architecture; pick the source per call site, not globally.

- **Scan-time / request-time reads → Postgres (unchanged).** Neither local FS nor R2 belongs on the page-render path.
- **Nightly hydrator → local FS, with R2 as the reconciliation target.** The mac mini is the warehouse host; local reads are 10–100× faster than R2 reads, and DR comes from a separate `warehouse → R2 push`, not from making the read remote.
- **Backfills / multi-year replay → R2 directly** (already the 2026-05-25 standing rule).
- **MacBook detached from the mini → R2** via the existing `lake_resolver` fallback.

The mac-mini-as-warehouse-host doesn't change which layer should sit on the critical path. It just makes the local layer cheap enough to be worth wiring as the hot path for the offline jobs that already exist.

---

## 1. Context

The mac mini (`100.66.147.98`) now hosts both:

- The shared Postgres instance (`option_wizard` DB, schema `uw_scan`).
- The local mirror of the market-warehouse parquet lake at `~/market-warehouse/data-lake/bronze/asset_class={volatility,equity,...}/symbol=<sym>/1d.parquet`.

The regime page (`web/app/regime/page.tsx`) renders CRI, VCG, GEX, and vol-backdrop. Its underlying inputs come from a small set of "local-retrieved" series:

| Indicator | Inputs | Storage today | Lookback | Heaviness |
|-----------|--------|---------------|----------|-----------|
| CRI | VIX, VVIX, COR1M, SPY closes | `vol_index_daily` + `daily_ohlc` (Postgres) | 200d | ~280 rows aligned |
| VCG | VIX, VVIX, HYG (credit proxy) | `vol_index_daily` (Postgres) | 200d | ~280 rows aligned |
| GEX | per-strike Γ + spot | UW REST API (live) | snapshot | 1 HTTP call |
| Vol backdrop | VIX/VIX3M/VVIX/COR1M | `vol_index_daily` (Postgres) | 90d | ~250 rows |

Postgres rows are upserted by a nightly `vol_index_lake_sync` job that today reads from the **local** parquet lake (`src/uw_scan/worker/jobs/vol_index_lake_sync.py`). A `lake_resolver` already exists (`src/uw_scan/sources/lake_resolver.py:69-95`) that picks R2 when `R2_*` env vars are configured, else falls back to local. So the choice is not "wire new code" — it's "which side do we default to."

The warehouse side has a `scripts/sync_to_r2.py` that can push local → R2, but I haven't confirmed it's on a schedule. Flagged below.

## 2. What "the data" actually is

This is small data, not big data:

- Volatility lake (`asset_class=volatility`): ~49 MB total, 16 symbols, ~9k rows per symbol.
- Credit/equity slice the regime touches (HYG/JNK/LQD/SPX): a few MB.
- Per-scan working set (200 trading days × 4 symbols): single-digit kilobytes once parsed.

Both approaches comfortably fit in RAM; neither has a streaming-vs-batch tradeoff. The differences are entirely in **latency**, **failure modes**, and **operational coupling**.

## 3. Approach A — Local file directory

Read from `~/market-warehouse/data-lake/bronze/asset_class=volatility/symbol=VIX/1d.parquet` via `pyarrow.dataset` / `duckdb` / `pd.read_parquet`.

**Pros**

- **Latency is essentially free.** Cold load of the full 49 MB volatility tree is ~5–20ms on the mac mini's SSD; warm load (page cache) is sub-millisecond. The OS page cache will retain it indefinitely as long as it's accessed regularly.
- **No external dependency.** Survives Cloudflare incidents, expired R2 tokens, account-level throttling, or a misconfigured endpoint URL.
- **No credential surface.** Nothing to leak, rotate, or scope.
- **Trivial to debug.** `ls`, `duckdb -c "SELECT * FROM read_parquet('…')"`, `pyarrow.dataset.dataset(…).to_table()` all just work. Errors are filesystem errors, not partial-S3-listing-with-truncation errors.

**Cons**

- **Single point of failure.** If the mini's disk dies between the last `sync_to_r2.py` run and now, anything ingested in that window is gone. The cost of this is bounded by how regularly the push runs (open question §6).
- **No cross-machine consistency by default.** A laptop that wants to render the regime page locally either has to Tailscale-mount the mini's filesystem (couples to the mini's uptime and the VPN), maintain a parallel local mirror (drift risk), or read from R2 anyway (which defeats the local-only choice).
- **Couples the regime app to filesystem layout.** Moving the warehouse path (external SSD, NAS, different home dir) requires touching every consumer's config.

## 4. Approach B — R2

Read via `s3://market-data/market-warehouse/data-lake/bronze/…` using `pyarrow.fs.S3FileSystem` with the account-scoped endpoint, or `duckdb` with `httpfs`.

**Pros**

- **Single source of truth across machines.** Mac mini, MacBook, any future host see byte-identical data. The cross-machine consistency story becomes "they both read R2," which is unambiguous.
- **Disaster recovery is automatic.** Lose the mini's disk and the data is intact — provided the push loop is closed (§6).
- **Decouples the app from filesystem layout.** The config surface shrinks to `R2_BUCKET` + prefix.
- **Egress is free (Cloudflare R2)**, so the marginal cost of reads is genuinely zero rather than "cheap."

**Cons**

- **Network is on the critical path.** Even mac mini → Cloudflare's nearest PoP → mac mini is ~30–80 ms RTT before HTTPS handshake and parquet partition fetching. Cold reads for the volatility tree land in the 200–500 ms range. This isn't a problem for a nightly job, but it would be catastrophic on a per-page-load path.
- **Cloudflare-side availability is on the critical path** for any job that reads from R2. R2 has had multi-region outages.
- **Credential surface.** `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` have to be present (and current) wherever the regime API or worker runs.
- **Harder to debug.** Listings can be truncated, prefix-vs-key bugs are silent, region/endpoint misconfig produces opaque errors.

## 5. The decisive axis — read pattern × latency budget

Latency only matters where the read is on the critical path.

| Read | Cadence | Latency budget | Right source |
|------|---------|----------------|--------------|
| `vol_index_lake_sync` nightly hydrator | 1×/day | minutes | **Local** — fastest; R2 reconciliation is a separate concern |
| CRI / VCG scan (snapshot recompute) | ~1/min (worker) | < 500 ms | **Postgres** — neither parquet source is appropriate here |
| `/regime`, `/regime/vcg`, `/regime/vol-backdrop` API | per page load | < 100 ms | **Postgres** — already the case |
| Multi-year backfill / replay | occasional | minutes | **R2** — per 2026-05-25 directive |
| Cross-machine read (laptop reading mini's data) | occasional | seconds | **R2** — only consistent option when detached |

Two observations follow from this table:

1. **No regime page-render path tolerates a 200 ms parquet round-trip.** Whichever side you wire as the lake reader, the request-time path must continue to be Postgres. The local-vs-R2 question is only live for the hydrator and for backfills — not for the page itself.
2. **The mac-mini-as-warehouse-host doesn't shift any of the latency budgets.** It just makes Approach A's "essentially free" cell genuinely free for the nightly job that runs on the same box.

## 6. Recommendation

The two approaches are not mutually exclusive; the codebase already supports both. The right policy is to assign each call site to the source that matches its latency budget.

1. **Keep Postgres on the request-time path** for `/regime`, `/regime/vcg`, `/regime/vol-backdrop`, CRI snapshots, and VCG snapshots. No change.
2. **Default the nightly `vol_index_lake_sync` job to local FS** when the warehouse mirror is present on the same host. The `lake_resolver` already produces a `Local` root when R2 env vars are absent; configure the mini's worker env to omit `R2_*` for this job's scope (or add an explicit `UW_LAKE_PREFER=local` switch). Trade-off accepted: this job will not detect data that exists in R2 but not in the local mirror — which is fine, because the local mirror IS the canonical write target.
3. **Default backfills / replays to R2** (already specified by the 2026-05-25 rule).
4. **MacBook should read from R2** via the existing fallback — no change needed there beyond ensuring `R2_*` env vars are set on the laptop.
5. **Close the local → R2 push loop on a schedule.** This is the load-bearing assumption behind picking local-as-primary; without it, Approach A's DR cost is unbounded. Recommend: launchd or cron job on the mini that runs `market-data-warehouse/scripts/sync_to_r2.py` after `vol_index_lake_sync` completes.

The decision framing isn't "which one wins" — it's "what is each one for." Local FS is the hot path for jobs that share a disk with the warehouse. R2 is the durability layer and the cross-machine layer. Postgres is the request-time layer. Each does the thing it's best at.

## 7. Open questions / things I didn't verify

- **Is `sync_to_r2.py` actually scheduled on the mini today?** I confirmed the script exists at `market-data-warehouse/scripts/sync_to_r2.py`; I did not confirm a launchd / cron entry. If it's manual-only, the DR value of Approach A is theoretical until that loop is closed.
- **Measured RTT mac mini → R2.** I quoted 30–80 ms from typical Cloudflare-PoP latency; this should be measured directly before committing to the recommendation. A `time aws s3 ls s3://market-data/market-warehouse/data-lake/bronze/asset_class=volatility/ --endpoint-url …` on the mini would settle it.
- **Does any other "local-retrieved" regime input bypass the parquet lake?** GEX reads UW REST live (not lake), and FRED/COMEX/LBMA series in the gold pipeline have their own fetchers. This report covers the vol-index and OHLC inputs; the gold-side dataflow needs its own pass if a parallel decision is needed there.
- **Postgres availability dependency.** The recommendation keeps Postgres on the request path. If Postgres is down, the regime page is down — that's not a new risk, but worth noting that "local FS on the hot path" is NOT one of our options today (the regime API doesn't read parquet directly), and adding it would be a separate architectural change.
