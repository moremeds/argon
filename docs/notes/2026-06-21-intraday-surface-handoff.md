# Handoff — intraday option surface (parked)

> Originally (2026-06-21) tracked two threads. **Thread A — argon EOD
> option-surface capture — has since shipped**: PR #145 merged,
> `worker/jobs/option_surface_capture.py` is on `main` with the full-term-structure
> fix (enumerate via `fetch_greek_exposure_by_expiry`, not the 500-volume-capped
> `/option-contracts`). Only the intraday thread below remains parked.

Pick up from the "Resume" section. Nothing is broken.

---

## Intraday option surface (the parked feature)

### What it is
Capture an **intraday** option surface (IV + greeks per strike) on a cadence — e.g. SPX/VIX every 10–30 min, other watchlist tickers ~hourly. Distinct from the EOD recorder (shipped).

### Decisions already made (this session)
1. **Home = finish xenon's `option_chain_snapshotter` (NOT build in argon).** argon reads it via the existing `SELECT` grant. The user confirmed this.
2. **Coverage = decide AFTER an IB timing probe** (let real throughput set cadence/scope).
3. **Storage = TimescaleDB** (xenon's already-chosen design: hypertable, day-partitioned, compressed). Not argon-Postgres (unpartitioned, would need net-new partitioning) and not parquet (argon has no parquet WRITE path; the lake is read-only from argon's side).

### Source research conclusion (UW explored thoroughly; IB confirmed)
There is **no single UW query** for an intraday full surface with IV **and** greeks on our current tier:
- UW `/greeks?expiry=` — IV + all greeks per strike, but **EOD-only** (no intraday refresh). 1 call/expiry.
- UW `/option-contracts` — **intraday IV per contract but NO greeks**; 500-row volume cap; no `date` param.
- UW `/spot-exposures/expiry-strike` — **intraday GEX (Δ/Γ/charm/vanna $) but NO IV**; ~1–2 calls/ticker.
- UW WebSocket `contract_screener` — intraday IV+greeks per contract, **requires Advanced plan (our key gets 403)**.
- **IB (via xenon) is the only intraday IV+greeks source** on what we own. Per-contract `reqMktData` snapshot; fan-out across lines.
- Fallback if ever UW-based: `/option-contracts` IV-only + compute greeks locally (Black-Scholes).

### xenon current state (branch `feat/option-chain-snapshotter`)
Design done, schema built, service NOT built:
- Design + impl plan: `docs/plans/2026-06-02-option-chain-snapshotter-{design,IMPL}.md`
- Schema migration (shipped): `scripts/migrations/option_chain/versions/001_initial_schema.py` — TimescaleDB DB `option_chain` (host mini `100.66.147.98:5432`), schema `archive`, owner `option_chain_writer`, **`argon_app` already has SELECT on `archive.*`**. 5 tables incl. `archive.option_chain` (per-sweep per-contract: snapshot_ts, con_id, ticker, expiry, strike, right, bid/ask/sizes, last, volume, oi, iv, delta, gamma, vega, theta, underlying_px, run_id) + `archive.underlying_ohlcv`.
- Design scope: SPX/NDX/RUT/VIX, 10-min RTH cadence, ~33k contracts, full sweep estimated **30–70 min** via IB fan-out (so true 10-min is realistic only for a subset, e.g. SPX+VIX — matches user's priority).
- clientIds 95/96 (`src/xenon/clients/ib_client.py`), advisory lock 7343001, `ib_async>=1.0.0` dep, spike `scripts/spike/option_chain_minimal.py` (ran live 2026-06-02).
- **Service module `src/xenon/option_chain_snapshotter/` does NOT exist** (PRs 4–9 of a 10-PR plan unbuilt: config/hours/queue/limiter/pool/storage/universe/persister/snapshot_worker/ohlcv_worker/__main__ + launchd PR 10).

### The PR-2 IB behavior probe (UNCOMMITTED, recreatable)
`scripts/research/probe_ib_option_chain.py` in **xenon** — the PR-2 "Day-1 IB behavior probe" (HALT gate). Transcribed verbatim from the impl plan's PR-2 §Task 2.1. **Compiles + imports resolve** (`CLIENT_IDS['option_chain_snapshotter_a']=95`). Untracked, not gitignored. It: qualifies SPX/NDX/RUT/VIX as Index contracts (per-ticker exchanges: SPX/CBOE, NDX/NASDAQ, RUT/RUSSELL, VIX/CBOE) → `reqSecDefOptParams` (checks SPX→SPXW weeklies + expiry counts) → times 50 SPX-strike snapshots (bid/ask, modelGreeks, snapshot-end) + early-line-release detection → 200-msg pacing burst → emits JSON with a contracts-per-second `cps` and `verdict: OK|HALT`. HALT if cps<3, 0 expiries, no SPXW, or pacing<25 msg/s.

### Why the probe was NOT run yet
- Must run **on the mini** (gateway is local there; running over Tailscale from the MacBook would distort the ms timings) during **RTH (Mon–Fri 09:30–16:00 ET)**. Plan says run vs **paper**; live would be read-only (snapshots + contract-details, no orders) but the 200-msg burst + fan-out shouldn't hit the prod link unsupervised on a closed market.
- **Only the mini's LIVE gateway is up** (`100.66.147.98:4001`); paper `4002` is down everywhere; nothing on localhost.

### Open questions (unanswered — were mid-clarification when tabled)
- Run logistics: paper-vs-live; who triggers (user on mini, or me via SSH if available); whether to run a safe **structure-only** subset (steps 1–2, qualify + chain coverage) now to validate early.
- Coverage scope beyond the 4 indices (the user's "other watchlist tickers hourly"): extend xenon's IB universe to single names, or argon/UW IV-only for single names, or indices-only v1.

### Resume
1. Run the probe on the mini during RTH (paper preferred). Read `cps` / `verdict`. If HALT (<3 cps), revisit the design before building the service.
2. If OK: implement xenon's PRs 4–9 (the `option_chain_snapshotter` service module) per `docs/plans/2026-06-02-option-chain-snapshotter-IMPL.md`, then PR 10 (launchd).
3. Wire argon to READ `archive.option_chain` for surface research (the SELECT grant already exists).
4. This is a xenon-repo effort with its own conventions (uv, superpowers, codex-review/review-cycle).
