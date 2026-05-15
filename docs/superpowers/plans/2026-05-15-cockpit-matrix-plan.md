# Cockpit Matrix — Plan

**Branch**: `feat/cockpit-matrix`
**Worktree**: `~/.config/superpowers/worktrees/unusual-whales/cockpit-matrix`
**Last revised**: 2026-05-15
**Research backing**: `docs/superpowers/research/six-dimension-matrix/00-overview.md` through `09-backtest-plan.md`

Single actionable plan for the 6-dimension options matrix. Built framework-first, backtest-deferred. Replaces piecemeal reading of 9 research docs as the working spec.

> **Reader's note**: this plan is executed by codex. Every file path, function name, and column reference is verifiable against the branch HEAD. Where research-doc terminology and shipped-code terminology disagree, the "Known inconsistencies" section near the end names the disagreement and the resolution rule.

---

## Goal

Ship a 4-ticker (SPX/SPY/QQQ/IWM) options-matrix product called **Cockpit** at `/cockpit/[ticker]`. Each weekday, read 6 dimensions of the option surface (vanna, charm, skew, term, implied-move + flow, VRP), label each as `vol_up` / `vol_down` / `neutral` per §0.1, and surface an aggregate consistency tier per §0.2.

The matrix is a **decision-blocker**, not an alpha generator (research takeaway #2). Its job is to refuse low-confidence trades.

## Non-goals (v1)

- Single-name tickers — explicit per Limitation #4
- Strategy backtest — UW per-strike greeks history is locked at 30 trading days (verified 2026-05-15). Backtest is parked to Phase 6
- Trading from the Cockpit — display-only; no order placement, no portfolio sync
- Vanna/charm reasoning on single-stock AI — the `src/uw_scan/reports/trade_insights_ai.py:965` blacklist tuple `("charm", "vanna", "short_interest")` stays intact

---

## What you will see, by phase

| Phase | What you SEE in the product | Status |
|---|---|---|
| **1** Data accumulation | Nothing visible. Job writes daily to existing tables; `matrix_state_snapshots` is created but empty. | ✅ MERGED on `feat/cockpit-matrix` |
| **0** Skew sanity check | A script plot + one-paragraph go/no-go memo. No product change. | NEXT |
| **2** Matrix deriver | One `matrix_state_snapshots` row per ticker per day, DB-queryable. Still no UI. | After Phase 0 |
| **2.5** Dry-mode validation | 1 week of logging-only deriver runs. Distribution audit; no UI; no user impact. Blocks Phase 3 if labels are pathological. | After Phase 2 |
| **3** State tab | `/cockpit/SPY` (and the rest of the surviving universe) renders the 6-dim heatmap + consistency tier. **First visible product.** | After Phase 2.5 |
| **4** Remaining 4 tabs | Dealer / Surface / Flow+IM / VRP tabs render. Cockpit feature-complete for display. | After Phase 3 |
| **5** Tuning loop | Thresholds refit monthly; State tab shows the active threshold version. | After Phase 4 + 30+ days data |
| **6** Backtest | Parked. Re-evaluate at month 6 against **pre-committed cells** (Phase 6 §Evaluation cells). | Gated on Phase 5 |

Confidence levels (honest):

- **Wiring confidence: high.** Full suite (`uv run pytest --collect-only -q` reports 307 tests as of 2026-05-15) green, scheduler imports clean, migration idempotent, job mirrors the proven `flow_data_refresh` pattern.
- **Framework-produces-useful-labels confidence: low.** All §0.1 thresholds (`±1.0`, `> 0.7`, `< 0.3`, etc.) are paper-derived from the podcast slides and academic literature. None are calibrated against live data yet. **That is the whole reason Phase 5 exists.**

---

## Phase 1 — Data accumulation (✅ merged)

Three commits on `feat/cockpit-matrix`:

1. `src/uw_scan/storage/migrations/022_matrix_state_snapshots.sql` — table created; rows added by Phase 2
2. `src/uw_scan/cards/option_chain.py` — `pick_target_expiries(contracts, target_dtes, today)` helper + 5 unit tests
3. `src/uw_scan/worker/jobs/cockpit_daily_snapshot.py` — job + 3 settings (`cockpit_tickers`, `cockpit_snapshot_cron`, `cockpit_target_dtes`) + scheduler wiring

**Job behavior**: Mon–Fri 16:30 ET, single-flight via `pg_try_advisory_lock(92201)`. Per ticker (SPX/SPY/QQQ/IWM):

1. realized vol → `realized_volatility_history`
2. IV rank → `iv_rank_history`
3. term structure → `iv_term_snapshots`
4. interpolated IV → `interpolated_iv_snapshots`
5. option contracts (limit 500) → `pick_target_expiries([0,14,30,90])` → for each expiry:
   - greeks → `greeks_by_expiry_strike`
   - greek exposure → `exposures_by_expiry_strike`
6. skew (Δ=25) → `risk_reversal_skew_history`

**Outstanding for Phase 1**:

- [ ] Smoke run before tomorrow's first scheduled fire. One-shot invocation that bypasses the scheduler:
  ```bash
  cd /Users/chenxi/.config/superpowers/worktrees/unusual-whales/cockpit-matrix
  uv run python -c "
  from uw_scan.config import Settings
  from uw_scan.api.client import UwClient
  from uw_scan.storage.repository import Repository
  import psycopg
  from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot
  s = Settings.from_env()
  with psycopg.connect(s.db_dsn()) as conn:
      with UwClient(api_key=s.api_key.get_secret_value(), base_url=s.base_url, timeout=s.request_timeout_seconds) as uw:
          cockpit_daily_snapshot(repo=Repository(conn, schema=s.db_schema), client=uw, settings=s)
  "
  ```
  **Strict acceptance criteria (each must pass for Phase 1 to be declared stable)**:
  - All 4 tickers complete without unhandled exceptions
  - SPY, QQQ, IWM each log non-zero `greeks=N exposures=N skew=N` for at least 2 of the picked expiries
  - **SPX-specific gate** (this is the litmus test): SPX must log non-zero greeks rows for at least 1 expiry. If SPX logs `no expiries found, skipping greeks` OR all SPX expiries return `greeks=0 exposures=0`, **SPX is OUT of v1**. Drop it by editing `src/uw_scan/config.py` default `cockpit_tickers` to `["SPY", "QQQ", "IWM"]` (preserves env-var override). Document the reason in the PR description with the smoke output pasted in. Re-investigate SPX after Phase 5 via UW endpoint pricing (`SPXW` weeklies, native-SPX-index endpoint) — separate work item.
  - If a non-SPX ticker logs `no expiries found, skipping greeks`, Phase 2 deriver MUST still produce a row for that ticker that day (label = `insufficient_data`); this is not a Phase 1 blocker but is a Phase 2 acceptance criterion.
- [ ] Open PR (`gh pr create --base main --head feat/cockpit-matrix`)

---

## Phase 0 — Skew sanity check (~1 day, do BEFORE Phase 2)

The §0.1 skew row says `skew_25d_zscore_180d > +1.0` → vol-down and `< −1.0` → vol-up. If this sign convention is inverted in our data, every Phase 2+ row will be inverted; fixing afterward is a migration. So validate first against the 1 year of skew history we already have (UW's `historical-risk-reversal-skew` rolling endpoint has no history wall).

**Deliverable**: `docs/superpowers/research/six-dimension-matrix/reviews/2026-05-XX-skew-sanity.md` with a verdict (proceed / fix §0.1 first).

**Procedure**:

1. Create `scripts/notebooks/cockpit_skew_sanity.py` (script form; we don't have a notebook workflow)
2. Pull trailing year of `risk_reversal_skew_history` rows for SPY/QQQ/IWM/SPX
3. Compute `skew_25d_zscore_180d` (rolling 180-day z-score) per §0.1
4. Plot (matplotlib via `uv run`, save to `/tmp/`):
   - distribution of `skew_25d_zscore_180d` per ticker
   - time series with z=+1 / z=−1 bands highlighted
   - overlay known risk-off windows: any 2025 Aug carry-unwind episode, any 2025 banking-stress episode, 2026-Q1 if applicable
5. **Acceptance**: extreme-negative-skew days visibly cluster around known risk-off; extreme-positive appear in calm or post-event sessions
6. **Fail mode**: if the sign is inverted, fix `00-overview.md` §0.1 + write a one-paragraph note in the review doc, then proceed to Phase 2

**On the historical skew rows already in the DB**: Phase 1 has been accumulating raw `risk_reversal_skew_history` rows since the job started. Those rows are **raw API values** — not direction-mapped — so a §0.1 sign-convention fix changes only the deriver's *interpretation*, never the rows themselves. No data migration is needed. The first Phase 2 deriver run after a §0.1 fix produces correct labels for every accumulated day in one pass.

This is cheap (a few thousand rows, single API/DB query, one chart) and de-risks the rest of the build.

---

## State machine specification (formal)

This is the authoritative spec for what `build_matrix_state` computes. Phase 2 implements it verbatim; Phases 5/6 reference it. If the spec changes, the deriver changes — they are deliberately co-located. Read this section *before* Phase 2.

### Output type

`build_matrix_state(repo, ticker, market_date, threshold_version=1) -> MatrixState`. Full Pydantic model in Phase 2 §Deliverable. Critical fields:

- 7 per-dim states: `vanna_state`, `charm_state`, `skew_state`, `term_state`, `im_state`, `flow_state`, `vrp_state` ∈ {`vol_up`, `vol_down`, `neutral`, `stale`}
- `consistency_tier` ∈ {`strict`, `strong`, `weak`, `no_trade`, `insufficient_data`} (post-Phase-2.5: possibly `display_only` if Option A)
- `cluster_coverage_ok: bool`
- `term_classification` ∈ {`contango`, `event_back`, `liquidity_back`, `mixed`, `None`}
- Decimal mirror of source inputs for replay/audit

`vrp_sign_flip_30d_status` is NOT on the model — it is log-only per Known Inconsistency #4.

### Input contract

The deriver reads from exactly these tables (via `Repository` methods, one query per call):

| Source table | Read pattern | Used by |
|---|---|---|
| `greeks_by_expiry_strike` | latest by `(ticker, market_date)` across all expiries the Phase 1 job picked | Vanna, Charm |
| `exposures_by_expiry_strike` | latest by `(ticker, market_date)` | Vanna proxy |
| `option_chain_per_strike` | latest by `(ticker, market_date)`, expiries ≤ 5d, ±2% spot band | Charm v1 pin-distance proxy (OI source) |
| `risk_reversal_skew_history` | latest by `(ticker, market_date)` + trailing 180d for z-score | Skew |
| `iv_term_snapshots` | latest by `(ticker, market_date)` | Term |
| `interpolated_iv_snapshots` | latest by `(ticker, market_date)` + trailing 30d for VRP-flip | IM (placeholder), VRP, VRP-flip detector |
| `realized_volatility_history` | latest by `(ticker, market_date)` + trailing 30d for VRP-flip | VRP, VRP-flip detector |
| `iv_rank_history` | latest by `(ticker, market_date)` | (informational; not a §0.1 input in v1) |

### "Fresh" — v1 operational definition

A dim is `fresh` for `(ticker, market_date)` **iff** the deriver's read against the source table returns at least one row matching that `(ticker, market_date)` key. Otherwise the dim is `stale`.

This is intentionally daily-resolution and weaker than research §0.3's intraday thresholds (30-min RTH for Vanna/Charm/IM/Flow). Research §0.3 thresholds become operational only when an intraday refresh job lands (parked — see Known Inconsistency #3). The deriver MUST NOT consult wall-clock time; it MUST use the `market_date` passed in. Replays for `market_date = 2026-05-10` always evaluate freshness as "is there a row for 2026-05-10?", regardless of when the replay runs.

**IM and Flow are stale-by-design in v1** (no event-calendar table, no flow-footprint classifier). They are stale not because their source tables are empty but because v1 explicitly emits `stale` for them. When IM/Flow plumbing lands, these dims become fresh-eligible.

### Algorithm (9 steps)

Inputs: `repo`, `ticker`, `market_date`. Output: `MatrixState`. Steps run in order; no short-circuits. Each step's *write* may be guarded; nothing skips downstream steps.

1. **Read.** Query each source table per the input contract above (one Repository method per query).
2. **Label per §0.1.** For each fresh dim, compute the §0.1 direction label → `vol_up` / `vol_down` / `neutral`. For each stale dim, the label is `stale` directly (do NOT pass stale through as `neutral`).
3. **Determine `fresh_set`.** The set of dims whose source data is present AND whose §0.1 mapping is enabled in v1. In v1: `fresh_set ⊆ {Vanna, Charm, Skew, Term, VRP}`. IM and Flow are excluded from `fresh_set` by design (their states are stored but they do not count for `expected_fresh_set` in v1 — see §Partial-plumbing transitions below for how `expected_fresh_set` grows). Compute `dim5_vote` from `(im_state, flow_state)` per the merger in Phase 2 §"v1 dim-5 merger"; if `dim5_vote ∈ {vol_up, vol_down, neutral}` AND IM+Flow are in `expected_fresh_set`, add the synthetic `dim_5` to `fresh_set` with that label.
4. **Compute `cluster_coverage_ok` (unconditional).** Set `cluster_coverage_ok = False` if `vanna_state ∈ {neutral, stale}` AND `charm_state ∈ {neutral, stale}`; else `True`. This flag is computed regardless of tier outcome — it is an independent field that records whether the dealer-flow cluster confirms the read.
5. **Apply `insufficient_data` rule.** If `|expected_fresh_set \ fresh_set| ≥ 2`, set `consistency_tier = insufficient_data`. Otherwise leave `consistency_tier` unset for now (filled by step 6). `expected_fresh_set` in v1 = `{V, C, Skew, Term, VRP}`. (Partial-plumbing transitions below.)
6. **Apply directional-count tier (only if step 5 did not set `insufficient_data`).** Let `N = |fresh_set|`, `agree = max(vol_up_count, vol_down_count)`, `neutral_fresh = |fresh_set| − agree − (count of conflicting directional)`. Compute tier from the table:

   | Pattern | Tier |
   |---|---|
   | Directional conflict (both `vol_up` and `vol_down` present in `fresh_set`) | `no_trade` (overrides everything else this step) |
   | `agree == N` (all fresh dims agree, 0 neutral) | `strict` |
   | `agree == N − 1` AND `neutral_fresh == 1` | `strong` |
   | `agree == N − 2` AND `neutral_fresh == 2` AND neither neutral is `vrp_state` or `term_state` | `weak` |
   | `agree == N − 2` AND `neutral_fresh == 2` AND one neutral is `vrp_state` or `term_state` | `no_trade` (per §0.2 weak-tier exclusion clause) |
   | `agree ≤ N − 3` (3+ neutrals, no conflict) | `no_trade` |

7. **Apply cluster-coverage override (only if step 6 set `tier ∈ {strict, strong, weak}`).** If `cluster_coverage_ok == False` from step 4 AND `consistency_tier ∈ {strict, strong, weak}`, set `consistency_tier = no_trade`. Does NOT override `insufficient_data` (step 5 wins) and does NOT override `no_trade` set in step 6 (no double-downgrade needed).
8. **Apply VRP sign-flip override and emit structured log.** Compute `vrp_sign_flip_30d_status` from the 30-day VRP series (`iv_atm_30d - rv_30d` joined by `(ticker, market_date)`). Set `aligned_days = |joined_rows|`. If `aligned_days < 30`: `status = "insufficient_history"`, `override_applied = False`. Else: compute sign-flip detector; `status = True` or `False`. If `status == True` AND `consistency_tier ∈ {strict, strong, weak}`: force `vrp_state = vol_up` AND downgrade `consistency_tier` by one step (`strict→strong→weak→no_trade`); set `override_applied = True`. Else `override_applied = False`. Emit the structured log line (Phase 2 §"Structured log contract") in all cases — log line is unconditional even when override doesn't fire.
9. **Return** `MatrixState`.

### Precedence (formal, picks the close calls)

`consistency_tier` resolution priority (highest first):

1. **`insufficient_data`** — set by step 5 when ≥2 dims of `expected_fresh_set` are stale. This is the highest-priority tier: when we cannot reliably count fresh dims, we cannot draw a `no_trade` *conclusion* either. `insufficient_data` is a meta-tier ("we cannot evaluate") that wins over content-tiers ("we evaluated; here's the outcome").
2. **`no_trade`** — set by step 6 (directional-count: conflict, or 2-neutral with VRP/Term as one of them, or ≥3 neutrals) OR by step 7 (cluster-coverage downgrade of strict/strong/weak) OR by step 8 (VRP sign-flip downgrade from weak). Multiple content-tier paths converge on `no_trade`.
3. **Directional tiers `weak` / `strong` / `strict`** — set by step 6 from the directional count.

VRP sign-flip override (step 8) operates **only within** the content-tier set `{strict, strong, weak}`. It NEVER promotes; it NEVER fires against `insufficient_data` or `no_trade`; it NEVER fires when status is not literally `True`.

Cluster-coverage flag (step 4) and tier override (step 7) are decoupled. The flag is computed unconditionally in step 4 from `vanna_state` and `charm_state`; the tier override fires in step 7 only when the flag is False AND the current tier is content. The flag and the tier are independent fields. A row may legitimately have `consistency_tier = insufficient_data` AND `cluster_coverage_ok = False` simultaneously — both pieces of information are useful (the first says "couldn't count", the second says "even if we had, V+C didn't help").

### Partial-plumbing transitions

The `expected_fresh_set` used in step 5's `insufficient_data` trigger represents *abstract voting positions*, not stored fields. The dim-5 position (the IM+Flow merged vote) enters `expected_fresh_set` only when the merger can produce a non-stale value. Under the v1 stale-wins merger (`dim5_vote = stale` whenever either IM or Flow is stale), this means dim-5 enters only when BOTH halves are plumbed — OR when a partial-plumb PR explicitly picks Option (b) "relax" for the merger.

The "≥2 stale" constant never changes. Only `expected_fresh_set` grows:

| Plumb state | `expected_fresh_set` | dim-5 contributes? | Notes |
|---|---|---|---|
| **v1** (today) | `{V, C, Skew, Term, VRP}` | No — both stale by design | Default state |
| **IM lands alone, dim5 merger Option (a) stale-wins** | `{V, C, Skew, Term, VRP}` (unchanged) | No — merger returns stale because Flow stale | dim-5 absent until Flow also plumbs |
| **IM lands alone, dim5 merger Option (b) relax-to-fresh-side** | `{V, C, Skew, Term, VRP, dim_5}` | Yes — dim-5 inherits IM's label | Partial-plumb PR must explicitly choose Option (b) to take this row |
| **Flow lands alone, Option (a)** | `{V, C, Skew, Term, VRP}` (unchanged) | No | symmetric with IM-alone Option (a) |
| **Flow lands alone, Option (b)** | `{V, C, Skew, Term, VRP, dim_5}` | Yes — dim-5 inherits Flow's label | symmetric |
| **Full 6-dim** (both IM and Flow plumbed) | `{V, C, Skew, Term, VRP, dim_5}` | Yes — dim-5 = `dim5_vote(im, flow)` per merger | Matches research §0.2's 6-dim framing |

The partial-plumb option choice (a vs b) is binding on `expected_fresh_set` as well as on the merger function. Phase 2 §"Partial-rollout caveat" (required PR gate) covers BOTH updates atomically — a PR that updates the merger to Option (b) without growing `expected_fresh_set` (or vice versa) fails review.

### Determinism guarantee

`build_matrix_state(ticker, market_date)` is deterministic **given the state of the source tables at deriver-run-time**. The function is referentially transparent over its actual reads; it does NOT consult wall-clock time, does NOT use random state, does NOT cache across calls.

Replays for the same `(ticker, market_date)` later may produce different output if source-table rows have changed since the original run. Mutability surface:

| Source table | Write pattern | Mutability per (ticker, market_date) |
|---|---|---|
| `realized_volatility_history` | UPSERT | mutable |
| `iv_rank_history` | UPSERT | mutable |
| `risk_reversal_skew_history` | UPSERT | mutable |
| `iv_term_snapshots` | INSERT (per run_id) | append-only — most-recent run wins on read |
| `interpolated_iv_snapshots` | INSERT (per run_id) | append-only — most-recent run wins on read |
| `greeks_by_expiry_strike` | INSERT (per run_id) | append-only — most-recent run wins on read |
| `exposures_by_expiry_strike` | INSERT (per run_id) | append-only — most-recent run wins on read |
| `option_chain_per_strike` | DELETE + UPSERT (per market_date) | atomically mutable per market_date |

The VRP sign-flip 30-day window reads from RV+IV across 30 prior days. If any of those 30 days has been re-upserted (RV) or had a newer run appended (IV via `interpolated_iv_snapshots`), the flip detector output can change. The deriver's row in `matrix_state_snapshots` is a snapshot of the framework's read at one moment, not a perpetual ground truth.

**Implications for Phase 6 backtest**: replay fidelity requires either (a) snapshotting all source rows alongside `matrix_state_snapshots`, or (b) accepting that historical replays may slightly drift from the original deriver run. Phase 6 design notes this constraint.

### Golden examples (worked traces)

Phase 2 unit tests MUST include all six examples. Use these as the parametrized inputs.

#### Example 1 — Happy-path strict

Inputs: V=vol_down (fresh), C=vol_down (fresh), Skew=vol_down (fresh, z=+1.4), Term=vol_down (fresh, contango), VRP=vol_down (fresh, z=+0.7, no sign-flip), IM=stale, Flow=stale.

Trace:
- Step 3: `dim5_vote = stale`. `fresh_set = {V, C, Skew, Term, VRP}`. `expected_fresh_set \ fresh_set = ∅` → 0 stale.
- Step 4: V/C both directional → `cluster_coverage_ok = True`.
- Step 5: 0 < 2 → no `insufficient_data`.
- Step 6: N=5, agree=5 (vol_down), neutral_fresh=0. Pattern "agree == N" → `strict`.
- Step 7: flag is True → no override.
- Step 8: status = `False` → no override; log emitted with `override_applied = False`.

Output: `consistency_tier = "strict"`, `cluster_coverage_ok = True`, all 5 v1-fresh dims labeled vol_down, IM and Flow stale.

#### Example 2 — Empty-greeks day (V+C both stale)

Inputs: V=stale, C=stale (no rows in `greeks_by_expiry_strike` for today), Skew=neutral (fresh), Term=vol_down (fresh), VRP=vol_down (fresh), IM=stale, Flow=stale.

Trace:
- Step 3: `dim5_vote = stale` (both stale). `fresh_set = {Skew, Term, VRP}`. `expected_fresh_set \ fresh_set = {V, C}` → 2 stale.
- Step 4 (unconditional flag): V=stale, C=stale → both non-directional → `cluster_coverage_ok = False`.
- Step 5: 2 ≥ 2 → `consistency_tier = insufficient_data`.
- Step 6: guarded by "only if step 5 did not set insufficient_data" → skipped.
- Step 7: guarded by "only if step 6 set tier ∈ {strict, strong, weak}" → skipped (tier is insufficient_data).
- Step 8: VRP sign-flip status computed; override guarded by "tier ∈ {strict, strong, weak}" → not applied. Log line still emitted with `override_applied = False`.

Output: `consistency_tier = "insufficient_data"`, `cluster_coverage_ok = False`, vanna_state = charm_state = `stale`.

#### Example 3 — VRP sign-flip downgrades strong→weak

Inputs: V=vol_down (fresh), C=vol_down (fresh), Skew=vol_down (fresh), Term=vol_down (fresh), VRP=neutral (fresh, z=+0.2), IM=stale, Flow=stale. 30+ aligned RV+IV days present; sign-flip detector returns `True`.

Trace:
- Step 3: `dim5_vote = stale`. `fresh_set = {V, C, Skew, Term, VRP}`. 0 stale of expected_fresh_set.
- Step 4: V/C both directional → `cluster_coverage_ok = True`.
- Step 5: 0 < 2 → no `insufficient_data`.
- Step 6: N=5, agree=4 (vol_down), neutral_fresh=1 (VRP). Pattern "agree == N − 1 AND neutral_fresh == 1" → `strong`. (Note: §0.2's "weak requires neither neutral is VRP or Term" applies only at the weak tier when there are 2 neutrals; here we have 1 neutral, so the rule doesn't kick in.)
- Step 7: flag True → no override.
- Step 8: status = `True`, tier ∈ `{strict, strong, weak}` → force `vrp_state = vol_up`, downgrade `strong → weak`, `override_applied = True`. Log emitted.

Output: `consistency_tier = "weak"`, `cluster_coverage_ok = True`, `vrp_state` flipped to `vol_up`.

#### Example 4 — VRP sign-flip insufficient_history

Same inputs as Example 3 but only 25 aligned RV+IV days exist (Phase 1 forward window not yet 30 days deep).

Trace:
- Steps 1–7 identical: tier reaches `strong`.
- Step 8: `aligned_days = 25 < 30` → status = `insufficient_history`, override skipped. Tier stays `strong`. Log emitted with `override_applied = False`, `aligned_days = 25`.

Output: `consistency_tier = "strong"`, `vrp_state = "neutral"` (unchanged).

#### Example 5 — Skew+Term stale (multiple non-V/C stale)

Inputs: V=neutral (fresh), C=vol_down (fresh), Skew=stale (no rows today), Term=stale (no rows today), VRP=vol_down (fresh), IM=stale, Flow=stale. 30+ aligned RV+IV days; status = `False`.

Trace:
- Step 3: `dim5_vote = stale`. `fresh_set = {V, C, VRP}`. `expected_fresh_set \ fresh_set = {Skew, Term}` → 2 stale.
- Step 4: V=neutral, C=vol_down → NOT both non-directional → `cluster_coverage_ok = True`.
- Step 5: 2 ≥ 2 → `consistency_tier = insufficient_data`.
- Steps 6–7: guarded → skipped.
- Step 8: tier not content → override skipped; log emitted.

Output: `consistency_tier = "insufficient_data"`, `cluster_coverage_ok = True`. (Counter-intuitive but correct: V+C are fine; we just lack Skew+Term to evaluate.)

#### Example 6 — IM-only plumb (post-v1 transition)

Inputs (after IM plumbing lands, Flow still stale): V=vol_down, C=vol_down, Skew=vol_down, Term=vol_down, VRP=vol_down (all fresh), IM=neutral (fresh — first plumb), Flow=stale.

This example splits into two sub-traces, depending on which option the IM-PR's required acceptance gate chose for the partial-plumb dim5 merger:

**Example 6a — Option (a) "stale-wins" kept** (recommended default; matches the dim5_vote code at Phase 2 §"v1 dim-5 merger"):

- Step 3: `dim5_vote = stale` (Flow stale). `fresh_set = {V, C, Skew, Term, VRP}` — dim_5 NOT added (vote is stale). `expected_fresh_set = {V, C, Skew, Term, VRP}` per partial-plumbing table row "Option (a)".
- Step 4: V=vol_down, C=vol_down (both directional) → `cluster_coverage_ok = True`.
- Step 5: `expected_fresh_set \ fresh_set = ∅` → 0 stale → no `insufficient_data`.
- Step 6: N=5, agree=5, neutral_fresh=0. Pattern "agree == N" → `strict`.
- Step 7: flag is True → no override.
- Step 8: VRP sign-flip status=False → no override; log emitted.

Output: `consistency_tier = "strict"`, `cluster_coverage_ok = True`. The IM signal is effectively discarded (its `im_state=neutral` is stored but it's not a voting position because dim_5 is stale).

**Example 6b — Option (b) "relax to fresh side"** (the IM-PR chose to relax the merger):

- Step 3: `dim5_vote = neutral` (IM=neutral propagates; Flow=stale discarded with reduced confidence). `fresh_set = {V, C, Skew, Term, VRP, dim_5}` with `dim_5_label = neutral`. `expected_fresh_set = {V, C, Skew, Term, VRP, dim_5}` per partial-plumbing table row "Option (b)".
- Step 4: same → `cluster_coverage_ok = True`.
- Step 5: 0 stale → no `insufficient_data`.
- Step 6: N=6, agree=5, neutral_fresh=1 (dim_5). Pattern "agree == N − 1 AND neutral_fresh == 1" → `strong`.
- Step 7–8: same as 6a path.

Output: `consistency_tier = "strong"`, `cluster_coverage_ok = True`. The IM signal is recorded as a fresh neutral, dropping the joint count from strict to strong.

The choice between 6a and 6b is binding on the IM-PR; reviewers reject the PR if `expected_fresh_set` and `dim5_vote` aren't updated in lock-step per the partial-plumbing transitions table above.

---

## Phase 2 — Matrix state deriver

**Deliverable**: `src/uw_scan/cards/matrix_state.py` with the pure function below + `MatrixState` Pydantic model in `src/uw_scan/models.py` (follow the `VRPAssessment` / `SetupClassification` patterns already in that file).

```python
# src/uw_scan/models.py — add alongside existing classes
class MatrixState(_UwBase):
    ticker: str
    market_date: date
    # §0.1 direction labels — literal type-narrowed in the actual code
    vanna_state: Literal["vol_up", "vol_down", "neutral", "stale"]
    charm_state: Literal["vol_up", "vol_down", "neutral", "stale"]
    skew_state:  Literal["vol_up", "vol_down", "neutral", "stale"]
    term_state:  Literal["vol_up", "vol_down", "neutral", "stale"]
    im_state:    Literal["vol_up", "vol_down", "neutral", "stale"]
    flow_state:  Literal["vol_up", "vol_down", "neutral", "stale"]
    vrp_state:   Literal["vol_up", "vol_down", "neutral", "stale"]
    consistency_tier: Literal["strict", "strong", "weak", "no_trade", "insufficient_data"]
    cluster_coverage_ok: bool
    term_classification: Literal["contango", "event_back", "liquidity_back", "mixed"] | None
    # Underlying inputs (mirrors columns in migration 022)
    skew_25d_zscore_180d: Decimal | None
    iv_atm_30d:           Decimal | None
    rv_30d:               Decimal | None
    vrp:                  Decimal | None
    vrp_zscore_60d:       Decimal | None  # NOTE: research doc references vrp_zscore_252d, migration 022 has _60d. See "Known inconsistencies"
    implied_move_pct:     Decimal | None
    front_iv:             Decimal | None
    back_iv:              Decimal | None
    pin_distance_sigma:   Decimal | None
    # NOTE on freshness fields (per Codex R2 ISSUE — UI needs §0.3 freshness pills):
    # MatrixState itself does NOT carry per-dim freshness timestamps. The Phase 3
    # state endpoint derives the freshness pills by reading the most recent
    # `inserted_at` / `market_date` from each source table at request time
    # (`risk_reversal_skew_history`, `iv_term_snapshots`, etc.). Rationale: the row
    # in `matrix_state_snapshots` is a snapshot at deriver-run-time; the freshness
    # pill the user sees needs to reflect read-time staleness, not deriver-time
    # staleness. If a future need to persist deriver-time freshness emerges, add a
    # `freshness_state: dict[str, datetime | None]` field + migration 024 column.

# src/uw_scan/cards/matrix_state.py
def build_matrix_state(
    repo: Repository,
    *,
    ticker: str,
    market_date: date,
    threshold_version: int = 1,   # accepted-but-not-persisted in Phase 2 — see note below
) -> MatrixState: ...
# Phase 2 NOTE on `threshold_version` (resolves Codex ISSUE-8): migration 022 has no
# `threshold_version` column. Phase 2 deriver accepts the parameter for forward-compat
# but the upsert MUST NOT attempt to write it (the column doesn't exist yet). Migration
# 023 (Phase 5 §Mechanics) adds the column and updates `upsert_matrix_state_snapshot`
# to persist it. Until then, the param defaults to 1 and is effectively a no-op so
# call-sites can already pass it without breaking. Add a `# TODO(phase-5): persist
# threshold_version after migration 023` comment at the upsert call-site.
```

**Behavior**: Phase 2 implements the algorithm specified in §"State machine specification (formal)" above. That section is the single source of truth for: input contract, fresh-vs-stale definition, the 7-step algorithm, precedence rules, partial-plumbing transitions, determinism guarantee, and 6 golden-test examples.

The remaining content of Phase 2 (below) covers implementation-only concerns the spec does not: v1 dimensional coverage, the Charm proxy formula, the cluster-coverage relief valve (Phase 2.5 decision gate), and wiring.

**Structured log contract for VRP sign-flip** (referenced by Phase 2.5 audit acceptance criterion #4 and by §"State machine specification" step 8): the deriver emits exactly one `logger.info(...)` per `(ticker, market_date)` run:

```python
logger.info(
    "cockpit_matrix: vrp_sign_flip ticker=%s market_date=%s status=%s aligned_days=%d override_applied=%s",
    ticker, market_date, status, aligned_days, override_applied,
    extra={
        "event": "vrp_sign_flip",
        "ticker": ticker,
        "market_date": market_date.isoformat(),
        "status": status,                   # one of True/False/insufficient_history
        "aligned_days": aligned_days,       # int, may be 0
        "override_applied": override_applied,  # bool — whether tier was actually downgraded
    },
)
```

The Phase 2.5 audit script greps `event=vrp_sign_flip` (or reads the `extra` payload if the logger handler emits JSON) to count override frequency per ticker.

### v1 dimensional coverage — what actually votes

The framework expects 6 voting dims. v1 ships with fewer fully-plumbed dims; the deriver must be honest about this rather than pretend missing dims are "neutral":

| Dim | v1 status | Direction label source |
|---|---|---|
| Vanna | partial | EOD greeks only; no intraday flow-color overlay. Direction from `dealer_net_vanna_proxy` sign + 3-day directional imbalance rollup if computable, else `neutral` |
| Charm | **simplified proxy** — see "Charm v1 simplification" below | EOD pin-distance proxy |
| Skew | full | §0.1 mapping against `risk_reversal_skew_history` |
| Term | full | 4-state classifier from `iv_term_snapshots` |
| IM | **always `stale` in v1** | Event-calendar table doesn't exist; no `implied_move_event_percentile` to compute. The deriver should emit `stale`, not `neutral`, so it correctly excludes from the count |
| Flow | **always `stale` in v1** | 4-footprint classifier deferred; raw flow data exists but the direction-mapping in §0.1 requires the matrix's own emergent read (a circular reference). The deriver should emit `stale` |
| VRP | proxy | Strict VRP settlement table not built; v1 uses IV−RV proxy and computes `vrp_zscore_60d` against trailing 60d. Sign-flip detector computed inline from same series |

**Effective consistency count in v1**: 4–5 dims (Vanna + Charm + Skew + Term + VRP), with IM and Flow excluded as stale. The §0.2 tier table must evaluate against this reduced denominator (e.g., `(4 vol_down, 0 conflict, 2 stale)` → strict-equivalent on the 4-fresh basis). Document the v1 denominator on the State tab so users see "5 fresh dims, 4 agree" rather than "5/6".

This is intentional — the framework's "6 dims" is aspirational for v1; we ship with honest dim-counting and grow into the full 6 as IM and Flow plumbing lands.

**im / flow → dim-5 merger** (resolves Codex ISSUE-7): `MatrixState` stores `im_state` and `flow_state` as separate columns (mirrors migration 022 schema), but the §0.2 consistency-tier counter reads them as a single "dim-5 vote" per research §1 footnote line 53. Merger rule:

```python
def dim5_vote(im_state, flow_state):
    if im_state == "stale" or flow_state == "stale":
        return "stale"
    if im_state == flow_state:
        return im_state           # same direction → counts as one directional vote
    return "neutral"              # mixed read → dim-5 contributes neutral to the count
```

The State tab renders ONE merged "Flow + IM" cell (not two), labeled with the merged vote. The underlying `im_state` and `flow_state` are exposed in the "Show inputs" collapsible for audit. v1 always shows the merged cell as `stale` until IM/Flow plumbing lands.

**Partial-rollout caveat** (Codex R2 ISSUE-7 followup): when ONE of IM/Flow lands but the other is still stale, the merger above returns `stale`, discarding the fresh half-signal. This is intentional for v1 — a single-source dim-5 read is not the same as the framework's joint Flow+IM reading. When IM ships alone (or vice versa), revisit this merger: either (a) keep it stale-wins and ship Flow+IM only when both are plumbed, or (b) relax to "if one side is stale, return the other side's direction with reduced confidence". Do not relax silently. **Required PR acceptance gate** (Codex R3): any future PR that plumbs IM-alone OR Flow-alone MUST include (i) a 5-day dim5-merger audit similar to Phase 2.5 with the new dim labeled, (ii) an explicit decision row in the PR description picking option (a) or (b), and (iii) the dim5_vote function updated only if (b) is chosen. PR reviewers must reject the change if any of (i)/(ii)/(iii) is missing. This gate lives here in the plan; copy it into the IM/Flow PR description when that work starts.

### Charm v1 simplification — pin distance proxy

The full §0.1 charm rule needs `pin_distance_sigma`, which the research doc describes loosely. The full classifier needs intraday spot vol, OPEX proximity, strike-OI clustering. v1 ships a **deliberately simplified proxy**:

```python
# v1 proxy: vol-scaled distance from spot to nearest high-OI strike at the nearest expiry ≤ 5d
def pin_distance_sigma_v1(spot, nearest_strike, rv_30d, dte_days):
    if rv_30d is None or rv_30d <= 0 or dte_days <= 0:
        return None
    sigma_to_expiry = spot * rv_30d * (dte_days / 252) ** 0.5
    return abs(spot - nearest_strike) / sigma_to_expiry if sigma_to_expiry > 0 else None

# "nearest high-OI strike" = strike with max(call_oi + put_oi) within ±2% of spot
# at the nearest expiry with dte ≤ 5. If no expiry ≤ 5d exists, charm_state = neutral.
```

What this proxy gets right: ±2% spot band + max-OI strike captures the dominant pin candidate for OPEX weeks. Vol-scaling normalizes across regimes.

What this proxy gets wrong: ignores OI dispersion (a pin candidate with 50% of OI is weaker than one with 90%), ignores intraday spot-vol regime change, ignores cross-strike gamma profile. These refinements are Phase 5+ work, gated on whether Phase 2.5 distribution audit shows charm_state ever firing usefully.

Document this proxy in `cards/matrix_state.py` docstring as `pin_distance_sigma_v1` — not the eventual `pin_distance_sigma`. Future versions land alongside a Phase 5 threshold refit.

**OI source — Phase 2 prerequisite** (resolves Codex ISSUE-3, with R2 corrections): `greeks_by_expiry_strike` (migration 001) holds the per-strike greeks but **NOT** `call_oi` / `put_oi`. OI per strike lives in `option_chain_per_strike` (migration 015), which is populated by `flow_data_refresh.py` — and that job iterates `repo.list_watchlist_cards()`.

**Round-2 check (2026-05-15)** revealed two reasons Option A (trust `flow_data_refresh`) does **not** work for v1:

- Watchlist seed (`006_seed_watchlist.sql:58–60`) has **SPY, QQQ, IWM but not SPX**. If SPX survives the Phase 1 smoke, `flow_data_refresh` produces zero OI rows for SPX.
- Scheduler cadence: `flow_data_refresh` runs at **18:15 ET**, *after* `cockpit_daily_snapshot` at 16:30 ET (`scheduler.py:302–314`). Same-day OI is not available when the deriver runs.

So Option B is the v1 default:

**Option B (v1)** — extend `cockpit_daily_snapshot.py` to also fetch + persist the option chain for the Cockpit universe. The flow_data_refresh code at `flow_data_refresh.py:62–83` is the reference shape. Required call sequence (each input has a real source noted):

1. `fetch_option_contracts(client, repo, run_id, ticker, limit=500)` — already called at `cockpit_daily_snapshot.py:118` for the expiry-picker; reuse that result, no second fetch
2. Get a same-day `spot` price per ticker. Source: `repo.latest_spot_price(ticker)` (used by `flow_data_refresh.py:60–63`) — falls back to the most recent realized-vol row's underlying price, or a fresh `fetch_spot_price` call if the repo helper is missing. If `spot` is unavailable, log a warning and skip OI persistence for that ticker (don't crash the job)
3. `aggregate_chain_per_strike(contracts, spot=spot, max_pct_from_spot=settings.cockpit_oi_band_pct, max_dte_days=settings.cockpit_oi_max_dte, today=market_date)` — mirrors `option_chain.py:69`. Defaults proposed: `cockpit_oi_band_pct = 0.10` (±10% around spot covers the dominant pin candidates) and `cockpit_oi_max_dte = 7` (a bit beyond the Charm proxy's ≤5d window for safety margin). Add both as new `Settings` fields with the same envvar-parse pattern as `cockpit_target_dtes`
4. `repo.delete_option_chain_per_strike(ticker, market_date)` BEFORE the upsert — same pattern as `flow_data_refresh.py:82`. Without this, a same-day re-run leaves stale strikes from the previous run
5. `repo.upsert_option_chain_per_strike(ticker, market_date, chain_rows)` — `flow_data_refresh.py:83`

This duplicates OI fetches for tickers also on the watchlist, but eliminates the timing dependency and covers SPX. Phase 2 PR adds this upsert path plus the two new `Settings` fields plus a smoke-log line counting per-ticker chain rows.

**Option A (deferred until after watchlist + scheduler are aligned)** — if a future change adds SPX to the watchlist AND reorders flow_data_refresh to run before cockpit_daily_snapshot, the deriver could read directly from `option_chain_per_strike`. Not v1.

Phase 1 smoke (§Outstanding) adds an OI-fetch log line to the smoke output to confirm the new Phase 2 upsert path works. Decision recorded in the Phase 2 PR description.

### Cluster-coverage relief valve (decision gate from Phase 2.5)

§0.2's cluster-coverage rule forces `no_trade` whenever Vanna and Charm are both neutral or stale. With v1's reduced dim coverage this rule may fire on most days, producing a useless State tab. **Phase 2.5 measures this**. If the dry-mode audit shows >80% `no_trade`, ship with one of:

- **Option A (preferred)**: keep the rule but rename the tier. `no_trade` becomes `display_only` — the directional labels still render on the State tab; users see why the matrix is muted; the "do not trade" semantic moves to a separate field that lights up only when the rule has *positive* signal (strict/strong tier reached). The default empty state is "no signal" not "DO NOT TRADE" — different UX. **Schema-compatibility note**: migration 022's `consistency_tier` CHECK constraint only allows `('strict','strong','weak','no_trade','insufficient_data')`. Adding `display_only` as a persisted tier requires a **migration 024** (see §"Migration ownership") that drops the old CHECK and adds the new one (or extends the allowed set). If Option A lands, sequence: migration 024 (relax/extend CHECK), then deriver change, then UI relabeling — atomically in one PR.
- **Option B**: relax the rule for v1. Cluster-coverage only forces `no_trade` when both Vanna AND Charm are *stale* (not just neutral). Neutral-but-fresh means the dealer flow exists but doesn't have direction — that's information, not absence of information.
- **Option C**: keep the rule as-is. Acceptable only if Phase 2.5 audit shows <80% `no_trade` — i.e., the rule isn't actually pathological in practice.

The Phase 2.5 acceptance criterion picks one of A/B/C. Do not pre-decide.

**Wiring** (resolves Codex ISSUE-1 — the per-ticker loop lives INSIDE the job, not in the scheduler closure):

Call `build_matrix_state` from inside `cockpit_daily_snapshot.py`, immediately after the existing per-ticker `repo.conn.commit()` at `cockpit_daily_snapshot.py:76`. Open a **fresh repo handle** (not reuse the just-committed `repo`) so the deriver reads through a clean transaction — the deriver reads from tables the same job just wrote to; reading own-uncommitted-writes works under `READ COMMITTED` but is brittle.

The scheduler closure (`scheduler.py:244–252`) stays unchanged: it still opens one repo and calls `cockpit_daily_snapshot(repo=repo, client=uw, settings=settings)`. The deriver call goes inside the job's per-ticker loop, not in the closure (where `ticker` and `market_date` aren't even in scope).

Code shape — insert immediately after line 76 of `cockpit_daily_snapshot.py`:

```python
# Top of file — NEW imports needed (cockpit_daily_snapshot.py doesn't import psycopg today)
import psycopg                                                  # NEW
from uw_scan.cards.matrix_state import build_matrix_state       # NEW (Phase 2 deliverable)

# cockpit_daily_snapshot.py — inside the per-ticker for-loop in cockpit_daily_snapshot()
for ticker in tickers:
    run_id = repo.insert_scan_run(ticker, notes="cockpit_daily_snapshot")
    try:
        _snapshot_ticker(...)            # existing
        repo.finish_scan_run(run_id, status="ok")
        repo.conn.commit()               # existing — line 76
        # NEW: derive matrix state in a fresh transaction so a deriver failure
        # does NOT roll back the just-committed source-table writes.
        try:
            with psycopg.connect(settings.db_dsn()) as deriver_conn:
                deriver_repo = Repository(deriver_conn, schema=settings.db_schema)
                state = build_matrix_state(deriver_repo, ticker=ticker, market_date=market_date)
                deriver_repo.upsert_matrix_state_snapshot(state)
                # TODO(phase-5): once migration 023 adds threshold_version,
                # pass state.threshold_version through to upsert and persist it
                deriver_conn.commit()
        except Exception as deriver_exc:   # noqa: BLE001
            logger.exception(
                "cockpit_daily_snapshot: %s deriver failed: %r",
                ticker, deriver_exc,
                extra={"deriver_failed": True},
            )
    except Exception as exc:             # existing — outer per-ticker catch
        repo.conn.rollback()
        logger.exception("cockpit_daily_snapshot: %s failed: %r", ticker, exc)
```

The deriver `try/except` is **inner** (after the outer commit). Its log line carries `deriver_failed=True` so the Phase 2.5 audit can distinguish source-job-failures (which roll back source rows) from deriver-failures (which leave source rows on disk but no `matrix_state_snapshots` row). The outer rollback only fires for source-job failures, not deriver failures.

**Tests** at `tests/unit/cards/test_matrix_state.py` — integration tests at `tests/integration/cards/test_matrix_state_db.py`:

- Unit: golden-input direction-mapping table — one parametrized test per §0.1 row, with the row's threshold boundaries
- Unit: cluster-coverage override fires when V+C both neutral (regardless of other 4 dims)
- Unit: stale-denominator math — `(2 vol_down, 2 vol_up, 2 stale)` evaluates as `(2, 4)` not `(2, 6)`
- Unit: VRP sign-flip override forces `vol_up` even when z-score band would say `neutral`
- Integration: full pipeline — seed source tables with known data, run `build_matrix_state`, assert label + tier
- Integration: empty-greeks case produces `insufficient_data`, not a crash

**Sign-convention test caveat**: `00 §0.4` claims "SPX baseline `risk_reversal` is negative" by UW convention. Codex must verify this against real `risk_reversal_skew_history` rows BEFORE locking the test (the research doc is unverified on this specific point). If real data shows the opposite sign, fix §0.1 + the deriver mapping; do not flip the test to make it pass.

**Definition of done**:

- Smoke run on SPY (re-using the Phase 1 smoke pattern, with the wired-in deriver call) produces exactly one `matrix_state_snapshots` row
- `uv run pytest tests/unit/cards/test_matrix_state.py tests/integration/cards/test_matrix_state_db.py` is green
- `uv run pytest` overall remains green (no regression in 120+ existing tests)
- No new fields added to `matrix_state_snapshots` migration — Phase 2 fills the existing columns. Schema changes wait for Phase 5 (migration 023 for `threshold_version`)

---

## Phase 2.5 — Dry-mode validation (1 week, blocks Phase 3)

The deriver is running and writing rows. Before any UI ships, audit the actual label distribution against the framework's implicit assumptions. **No UI changes during this phase.**

**Why this exists**: Phase 0 sanity-checks only skew (the reference impl). Vanna, Charm, IM, Flow, VRP have no pre-deriver validation. If the matrix produces pathological output (95% one bucket, missing dim coverage, sign-inverted labels we missed in Phase 0), we want to discover that in the DB, not from a user noticing the State tab is always grey.

### Procedure

1. After Phase 2 lands, let the scheduler run normally for **5 trading days** (1 week). Do not touch the codepath; the goal is to observe steady-state behavior. Weekend gap is fine — 5 weekdays = 5 × surviving-tickers rows in `matrix_state_snapshots`.
2. At day 5, run `scripts/cockpit/dry_mode_audit.py` (new). CLI shape:

   ```
   uv run python scripts/cockpit/dry_mode_audit.py \
       --start 2026-MM-DD              # first market_date to include (inclusive)
       --end   2026-MM-DD              # last market_date to include (inclusive)
       --tickers SPX,SPY,QQQ,IWM       # comma-separated; default = settings.cockpit_tickers
       --output docs/.../reviews/2026-MM-DD-dry-mode-audit.md
       [--strict]                      # exit 1 if any acceptance criterion fails
   ```

   Reads from: `matrix_state_snapshots`, `greeks_by_expiry_strike`, `risk_reversal_skew_history`, `iv_term_snapshots`, `interpolated_iv_snapshots`, `realized_volatility_history`. Repository methods enumerated in the script (one query per question — never raw SQL in the script).

   Exit codes: `0` = report written, all 5 criteria pass · `1` = report written, at least one criterion fails AND `--strict` set · `2` = script error (DB unreachable, no rows in window, etc.). Without `--strict`, the script always exits `0` if it produced a report.

   The markdown report contents:
   - **Row count check**: `surviving_tickers × 5` rows present (e.g., 20 for SPX-included, 15 if SPX dropped). Any gap → which day, which ticker, why
   - **Distribution per ticker × dim**: percentage of `vol_up` / `vol_down` / `neutral` / `stale` labels. Expected: skew/term have non-trivial directional split; IM/Flow are 100% stale (by design per v1 coverage); vanna/charm/VRP show *some* directional movement
   - **Consistency tier histogram per ticker**: counts of `strict`/`strong`/`weak`/`no_trade`/`insufficient_data`. The headline number
   - **Cluster-coverage fire rate**: `% rows where cluster_coverage_ok == False` per ticker
   - **Threshold-band visit rate**: for each §0.1 threshold (skew z, vrp z, etc.), what fraction of observations land in the directional vs neutral band

### Acceptance criteria (all must hold to proceed to Phase 3)

1. **Distribution sanity**: for each surviving ticker, the max single bucket of `consistency_tier` is **<80%**. If max ≥80%, trigger the cluster-coverage relief valve in Phase 2 (Option A / B / C) and re-run dry-mode for another 5 days.
2. **No silent crashes**: every (ticker, market_date) cell that should exist (per scheduler runs) is present in `matrix_state_snapshots`. Missing rows mean the deriver threw and the job's try/except swallowed it — find and fix.
3. **Dim plumbing sanity**: skew and term show *both* directional and neutral labels in the 5-day window. If skew is 100% one direction, sign convention is still wrong even though Phase 0 thought it was right — escalate.
4. **VRP sign-flip rule not pathological**: `vrp_state` doesn't show >50% `vol_up` from the sign-flip override alone (that would mean the inline detector is too sensitive).
5. **IM and Flow are 100% stale**: confirms v1 coverage gap is documented, not silently mis-labeled as neutral.

### Failure modes and responses

| Symptom | Most likely cause | Response |
|---|---|---|
| ≥80% `no_trade` for all surviving tickers | Cluster-coverage rule too tight given EOD-only data | Apply relief valve Option A (preferred) — rename tier to `display_only`, separate "do not trade" semantic |
| ≥80% `no_trade` for some tickers, not others | Per-ticker dim plumbing gap | Audit which dims are stale on the affected tickers; fix or document |
| One dim always one direction (e.g., charm always `vol_up`) | Threshold inverted or proxy formula bug | Re-derive from a sample row by hand; fix the rule; do NOT flip the test |
| Missing rows for some days | Deriver exception swallowed by the OUTER per-ticker `try/except` in `cockpit_daily_snapshot()` (lines 77–80 — `_snapshot_ticker` itself has no try/except) | Surface the exception. Two options: (a) raise instead of `logger.exception` in the outer catch when `settings.cockpit_dry_mode_strict=True`; (b) add a separate `cockpit_failures` log/table the audit script reads. Option (a) is simpler for v1. **Wiring** (Codex R3): the `cockpit_dry_mode_strict` field does NOT exist on `Settings` yet (verified at `src/uw_scan/config.py:58-89`). The Phase 2.5 PR that delivers the audit script also adds: (i) `cockpit_dry_mode_strict: bool = False` to the `Settings` dataclass following the snake-case pattern, (ii) an env-var parse line `cockpit_dry_mode_strict=_parse_bool_env("COCKPIT_DRY_MODE_STRICT", default=False)` in `Settings.from_env()`, (iii) the outer-catch guard `if settings.cockpit_dry_mode_strict: raise` immediately before the existing `logger.exception` call, (iv) a unit test toggling the flag and asserting raise-vs-log behavior |
| `cluster_coverage_ok == False` >80% | Both Vanna and Charm proxies firing `neutral` too often | Investigate whether the proxies have enough sensitivity, or document and apply relief valve |

### Definition of done

- 5-day audit report written and committed to `reviews/`
- All 5 acceptance criteria green
- Cluster-coverage relief-valve decision (A/B/C) recorded in the audit report
- PR opened for any code changes (relief valve, threshold fixes, dim-plumbing fixes)

**Estimated wall-clock**: 1 calendar week (the 5 trading days) + ~half-day to write the audit script + ~half-day to review and decide. Total: ~6 calendar days. Codex can complete the audit script + criteria docs immediately after Phase 2 lands; the 5-day wait is wall-clock-bound.

---

## Phase 3 — API + State tab UI

**API** — new file `src/uw_scan/api/routers/cockpit.py`:

- `GET /api/cockpit/{ticker}/state` (optional query `?asof=YYYY-MM-DD`, default = most recent row) → latest `MatrixState` for that ticker, plus a `freshness` object (see below)
- Universe guard: HTTP 404 if `ticker.upper() not in {t.upper() for t in settings.cockpit_tickers}` — read the universe from `settings.cockpit_tickers` (NOT a hardcoded set). This couples the API guard to the worker's universe so the Phase 1 §smoke "drop SPX" path automatically narrows the API surface without an API-side code change. Enforce at the route handler, not in the repository — the boundary belongs at the API edge
- **Freshness reader** (resolves Codex R3): new `Repository.fetch_matrix_source_freshness(ticker, market_date)` returns a dict like `{"vanna_charm": datetime|None, "skew": ..., "term": ..., "im_vrp": ..., "vrp_rv": ..., "oi": ...}` — one timestamp (the most recent `inserted_at` per source table for that ticker/market_date) per dim cluster. Cockpit router calls this alongside the state-fetch, joins them into the response body as `{"state": MatrixState, "freshness": {...}}`. UI freshness pills then apply §0.3 thresholds (`now() - timestamp > threshold` → grey/hatched). The repository method is one query per source table (per "one method per query" rule); the router-side helper is a thin aggregator
- Mount in `src/uw_scan/api/server.py` using the existing pattern (verbatim):
  ```python
  from uw_scan.api.routers import cockpit
  app.include_router(cockpit.router, prefix="/api", tags=["cockpit"])
  ```
  Insert next to the other `app.include_router(...)` calls at lines ~31–38

**UI** — Next.js:

- Route `web/app/cockpit/[ticker]/page.tsx` (RSC, fetches from API at request time)
- `web/app/cockpit/[ticker]/StateTab.tsx`:
  - 6 dimension cells in a row; coloring: green = vol_down, red = vol_up, grey = neutral, hatched = stale
  - Top-line consistency-tier badge (`STRICT` / `STRONG` / `WEAK` / `NO-TRADE` / `INSUFFICIENT-DATA`) with color and one-line explanation
  - Freshness pill per dim (uses §0.3 thresholds)
  - "Show inputs" collapsible: dumps the underlying snapshot row (skew z, IV30d, RV30d, VRP, IM%, front/back IV, pin distance) — auditable
- Regenerate `web/lib/types.ts` via `cd web && npm run gen:types` after the API change. Type regen alone is **not sufficient** — also (a) add a typed wrapper `api.cockpitState(ticker, asof?)` (and per-tab wrappers in Phase 4) to `web/lib/api.ts` mirroring the existing wrappers at lines 18–117, and (b) refresh the OpenAPI snapshot at `tests/integration/api/openapi.snapshot.json` — `tests/integration/api/test_openapi_snapshot.py` is snapshot-guarded and will fail until the snapshot is updated. Both updates land in the same Phase 3 PR
- Argon dark theme; reuse existing watchlist styling primitives

**Smoke acceptance**: `http://localhost:3001/cockpit/SPY` renders end-to-end for all 4 tickers; freshness flags show correctly when a dim's source table is stale.

---

## Phase 4 — Dealer / Surface / Flow+IM / VRP tabs

Each tab is a different read of Phase 1 inputs. No new derivers required for v1.

| Tab | Reads from | Key viz |
|---|---|---|
| **Dealer** | `greeks_by_expiry_strike`, `exposures_by_expiry_strike` | per-expiry vanna + charm strike profile (SVG, no chart library) |
| **Surface** | `risk_reversal_skew_history`, `iv_term_snapshots` | 25Δ skew timeline + front/back IV term curve |
| **Flow+IM** | existing flow alerts + new IM derivation from `interpolated_iv_snapshots` | 4-footprint table (raw, no classifier in v1) + IM vs prior-event distribution |
| **VRP** | `iv_rank_history`, `realized_volatility_history` | proxy VRP timeline + z-score band |

Each tab is a `Cockpit*Tab.tsx` component; tab navigation is local state on the page (no route changes). Endpoints `GET /api/cockpit/{ticker}/{tab}` mirror the State endpoint pattern.

**v1 simplification (deferred to post-v1)**:
- 4-footprint flow classifier (Phase 3 of `08 §4`) — Flow+IM tab shows raw flow for now
- IM event-percentile vs historical distribution — needs an earnings/macro calendar table; Flow+IM tab shows raw IM until that lands

---

## Phase 5 — Tuning loop

The §0.1 thresholds are paper defaults. After 30+ trading days of `matrix_state_snapshots`, refit each one against the actual distribution. **The expectation is that at least 3 of the 9 thresholds move off their defaults within 90 days; if none do, the refit procedure is too conservative — investigate.**

### Threshold registry

| Threshold | Default | Calibration procedure | Data needed | Refit cadence |
|---|---|---|---|---|
| `skew_25d_zscore_180d` band | ±1.0 | Per ticker: choose `\|z\| > X` to cover **top/bottom 15% of trailing-180d days** (risk-budget target) | 180+ days of skew history (✅ have via UW) | monthly; alert if 15% target slips ±5% |
| `pin_distance_sigma` (charm pin gate) | 1.0 | ROC: label "true pin" = `\|close − strike\| < 0.25% at expiry`; vary threshold to maximize Youden's J | 60+ OPEX days with intraday charm + spot | quarterly |
| `iv_30d_threshold` (charm vol-up gate) | `p70(IV_30d_180d)` | rolling 180d 70th-percentile per ticker | 180 days of `interpolated_iv` | monthly |
| `implied_move_event_percentile` cutoffs | 0.3 / 0.7 | by-event-type empirical CDF of (`\|realized post-event return\| / implied_move`) | 20+ events per type per ticker (~1y) | per event-type, when sample size reaches 20 |
| `vrp_zscore` band | ±0.5 | rolling 252d z; choose threshold to cover ~25% of days | 252+ days of strict VRP settlements (needs `vrp_30d_settlements` table — see `08 §2.6`) | quarterly |
| `vrp_sign_flip_30d` window | 30d | logistic regression: `P(forward stress regime in next N days) ~ sign-flip × window` | full forward dataset | annually |
| Consistency-tier rules (5/6, 4/6, 5/1) | hardcoded per §0.2 | A/B inclusion vs exclusion of 5/1 trades; report Sharpe delta | Phase 6 deliverable (gated) | gated on Phase 6 |
| Freshness windows per dim (§0.3) | 30min RTH / 24h skew / 5min flow | empirical: measure actual update cadence by table | 30 days of accumulated data | one-time after Phase 1 |
| Target DTEs `[0, 14, 30, 90]` | hardcoded | inspect strike-density + term-structure curvature; possibly add 60d or drop 0d | 30 days of accumulated chain data | one-time |
| §0.2 "weak" tier exclusion clause (currently: VRP & Term must not be the neutral ones) | hardcoded per §0.2 | A/B mutual-information: which dim pair, when neutral, most degrades the matrix's predictive value? Phase 5 may find Skew is the actually-highest-info dim once data is real | 90+ days × 4 tickers | annually after Phase 5 has 90+ days |

### Mechanics

- **Prerequisite migration**: `023_matrix_state_threshold_version.sql` — adds `threshold_version INTEGER NOT NULL DEFAULT 1` to `matrix_state_snapshots`. Migration 022 does NOT include this column; Phase 5 cannot start without 023.
- **Threshold storage**: `src/uw_scan/cards/matrix_state_thresholds.py` — versioned frozen dataclass; default literals; `version: int`, `refit_at: datetime`, `notes: str`. Each new version is a NEW dataclass class (e.g. `ThresholdsV1`, `ThresholdsV2`) so older rows replay against the exact literals that produced them
- **Refit script**: `scripts/cockpit/refit_thresholds.py` — reads `matrix_state_snapshots` + source tables, prints the proposed new threshold dataclass to stdout for PR-review (does NOT auto-write or auto-commit). The human pastes it into the thresholds file
- **Version pin**: `build_matrix_state` accepts `threshold_version: int`; writes that value into the row. Old rows remain replayable against their original thresholds by re-running with the matching version
- **Backfill convention**: migration 023 adds `threshold_version INTEGER NOT NULL DEFAULT 1`. Rows written *before* migration 023 will get `version=1` from the NOT NULL DEFAULT — they did not literally record the version at write time. This is a convention, not a recorded fact. Document this in the dry-mode-audit report so anyone reading old rows knows the version pin is implicit for pre-023 data
- **Surfaced on UI**: State tab footer shows `Thresholds v3 · last refit 2026-08-01` (sourced from the snapshot row's `threshold_version` + the dataclass's `refit_at`)
- **Cadence**: monthly review — pull freshest snapshots, refit any threshold whose criteria are met, PR the new dataclass version + a `reviews/2026-MM-thresholds-vN.md` note explaining what moved and why

### Why this matters more than "ship the deriver"

The deriver is mechanical (apply rules from a table). The thresholds are what make the rules right. A deriver with bad thresholds produces confident-looking nonsense. Phase 5 is where the framework moves from "paper plausible" to "evidence-supported" — and where most of the actual judgement lives.

---

## Phase 6 — Backtest (parked, re-evaluate at month 6)

**Why parked**: UW history wall verified 2026-05-15 — per-strike greeks return 403 beyond ~30 trading days. The full 2018–2025 backtest in `09 §3` is infeasible without external data.

**Three unblock paths** (cost-ranked):

1. **Forward accumulation only** (current choice): $0; wait 12–24 months for statistical power. Strategy 1 needs ~50 trades OOS per `09 §7`; at SPX rate (~1 consistent setup per 3 weeks) that's 3+ years
2. **ORATS Near-EOD flat-file**: $599 one-time; 19 years × 5000+ symbols including all 4 Cockpit tickers. Decisive but uncommitted spend; user-authorized at $599
3. **UW Data Shop Option Chains**: $180/ticker × 1y, no 5y option. $720 for 4 tickers × 1y. Worse $/year than ORATS
4. **UW subscription upgrade**: pricing not verified; ask UW sales

### Pre-committed evaluation cells (write this down NOW, before data accumulates)

Cross-product naively has 4 tickers × 5 tiers × 3 0DTE-regime cohorts × event/non-event = **120 cells**. With 500 snapshots that's ~4 obs/cell. Standard multiple-testing controls (deflated Sharpe, White's Reality Check per `09 §6.9`) eat that edge by definition. **If we leave cell selection to month 6, we will p-hack the cell that happens to look best.**

So commit now, in writing, to the cells that matter:

| Cell | Why this is THE cell | Expected effect direction |
|---|---|---|
| **Primary**: SPY × `consistency_tier == "strict"` × VIX < 18 × non-event days | The framework's home turf per `09 §6.5`; "consistent vol-down" Strategy 1 is the cleanest signal; SPY has the most volume and the cleanest dealer-flow regime | Strategy 1 forward returns positive, Sharpe ≥ 0.5 over the cohort |
| **Secondary 1**: SPY × `strict` × VIX 18-28 × non-event | Mid-regime stress test — does the matrix's edge survive mild volatility? | Sharpe still positive, possibly degraded |
| **Secondary 2**: QQQ × `strict` × VIX < 18 × non-event | Independence check (≈ 0.75 corr with SPY); does the matrix work outside the SPX/SPY pair? | Sharpe positive but ≈ 60% of SPY result |
| **Falsification**: any ticker × `no_trade` (or `display_only`) × any regime | If `no_trade` returns are *better* than `strict`, the matrix has signal but reversed | `no_trade` returns at or below random baseline |

**VIX data dependency** (resolves Codex ISSUE-10): the cells above use `VIX < 18` / `VIX 18-28` cohort gates, but VIX is not in the Phase 1 source-table list (lines ~59–66). Before Phase 6 can run, one of:

- **Option A (cheapest)**: at evaluation time, pull historical VIX_close from UW's `/api/stock/VIX/ohlc/1d` (the real shape is `/api/stock/{ticker}/ohlc/{candle_size}` per `docs/uw-samples/unusual_whales_api_spec.yaml`) for the 6-month window — single-shot read, no recurring infra. Verify VIX is queryable on this UW tier during Phase 0 (it's a separate, 30-minute spike).
- **Option B (cleaner long-term)**: add `fetch_vix_close` to `cockpit_daily_snapshot.py` so VIX accumulates forward alongside the rest of the matrix inputs. Adds one row/day to a new `vix_history` table or reuses `realized_volatility_history` with `ticker = 'VIX'`.
- **Option C (substitute)**: replace VIX cohort gates with SPY `iv_atm_30d` quintiles (already in `interpolated_iv_snapshots`). Less interpretable for readers but zero new infra.

Decision deferred to Phase 6 kickoff. Until then, treat the VIX-cohort cells as "blocked on a VIX source decision" — they don't impair Phases 1–5.

Cells explicitly NOT evaluated at month 6 (research extensions, separate decision):
- IWM (lowest volume; least-confident inference)
- SPX (likely dropped in Phase 1; if kept, evaluate separately as European-settlement validation, never in the headline)
- `weak` consistency tier
- 0DTE-dominant regime (cohort starts at 2023; with only 6 months of forward data we don't have a pre-0DTE cohort to compare against)
- Event days (require the event-calendar table that doesn't exist in v1)

**Decision criteria at month 6** (when ~125 trading days × surviving tickers ≈ 375–500 snapshots exist):

- **Green** (proceed to ORATS purchase / Phase 6 backtest): Primary cell shows Sharpe ≥ 0.5 (deflated) AND falsification cell is at or below baseline
- **Yellow** (extend forward-accumulation 6 more months, no purchase yet): Primary cell shows Sharpe 0.0–0.5 OR signs are right but sample is too small for deflated significance
- **Red** (framework revision needed before any external-data spend): Primary cell Sharpe < 0, OR falsification cell beats primary cell

The deflated-Sharpe correction per Bailey-López de Prado uses `N = 4` (the four cells above) for selection bias, NOT 120. This is the entire point of pre-committing: keeping N small enough that the correction doesn't eat real edge.

**$30 SPY 30d Data Shop validation purchase** (user-authorized but not executed): confirms data-shop schema agrees numerically with live API. Worth doing before any larger external-data spend, but not on the critical path for Phase 1–5.

---

## Parked / out-of-scope

| Item | Where parked | Why |
|---|---|---|
| Single-name extension | research `09 §11` | Limitation #4 — index-pricing-pressure phenomena |
| Vanna/charm on stock-detail AI | `src/uw_scan/reports/trade_insights_ai.py:965` blacklist tuple (`charm`/`vanna`/`short_interest`) | Product decision; blacklist stays |
| 4-footprint flow classifier | research `08 §4` item 13 | Phase 4 ships without it; raw flow data only |
| IM event-percentile vs historical | research `08 §4` item 6 | Needs earnings/macro calendar; deferred |
| Bekaert-Hoerova VRP decomposition | research `08 §4` item 15 | Optional Phase-3 refinement |
| NDX/RUT, sector ETFs | research `09 §11` | Universe expansion gated on v1 success |
| Cockpit AI (`reports/cockpit_ai.py`) | research `08 §4` item 14 | After all 5 tabs ship + Phase 5 starts producing stable labels |

---

## Build-prerequisite vocabulary

The plan references several names that *do not yet exist in the codebase* — they are placeholders for things that land in later phases (or never, if the eventual research direction differs). Codex should treat any name in this table as a "to-be-built" symbol when reading the plan, not assume it's already in `src/uw_scan/`.

| Symbol | Type | Plan location | Lands in | Notes |
|---|---|---|---|---|
| `MatrixState` | Pydantic model in `src/uw_scan/models.py` | Phase 2 | Phase 2 | Spec is in Phase 2 §deliverable |
| `build_matrix_state` | function in `src/uw_scan/cards/matrix_state.py` | Phase 2 | Phase 2 | Signature in Phase 2 §deliverable |
| `pin_distance_sigma_v1` | docstring identifier in `cards/matrix_state.py` | Phase 2 §Charm | Phase 2 | Code sketch in Phase 2 §Charm |
| `upsert_matrix_state_snapshot` | `Repository` method | Phase 2 | Phase 2 | One method per query per `storage/CLAUDE.md` |
| `dealer_net_vanna_proxy`, `dealer_net_charm_proxy` | research-doc concepts (per `08 §172–180`) | Phase 2 §v1 coverage | NOT v1 | v1 reads vanna directionality from `dealer_net_vanna_proxy` if implementable, else `neutral`. The proxy itself is Phase 5+ work — v1 vanna_state is `neutral` until then |
| `vanna_signals`, `charm_signals` | aspirational tables in research `08` | Phase 5+ | Phase 5+ | Plan never reads from these; named for cross-ref only |
| `vrp_30d_settlements` | aspirational strict-VRP table | Phase 5 §threshold registry | Phase 5+ | v1 uses IV−RV proxy + `vrp_zscore_60d` |
| `implied_move_event_percentile` | aspirational classifier output | Phase 5 §threshold registry | NOT v1 | Requires event-calendar table (deferred). IM stays `stale` in v1 |
| `aggressor_label_confidence` | research §0.1 reference | research-doc only | not in plan | Flow row of §0.1 uses this; v1 flow_state is `stale` so it doesn't fire |
| `vrp_sign_flip_30d_status` | log-only string from Phase 2 deriver | §"State machine specification" step 8 | Phase 2 | Three values: `True`, `False`, `insufficient_history`. **Log-only in v1** — not a `MatrixState` field, not a column in `matrix_state_snapshots`. Surfaced via `logger.info` for the dry-mode audit to count |
| `EXPECTED_FRESH_DIMS_V1` | module-level Python constant in `cards/matrix_state.py` | §"State machine specification" step 5 + Phase 2 deliverable | Phase 2 | Concrete value: `frozenset({"vanna", "charm", "skew", "term", "vrp"})`. Single source of truth for the v1 expected-fresh set. Partial-plumbing PRs replace this constant atomically with their merger update — single edit point gates the algorithm transition |
| `display_only` | candidate `consistency_tier` value if Phase 2.5 Option A fires | Phase 2.5 §Relief valve | Phase 2.5 (conditional) | Not yet allowed by migration 022's CHECK constraint. If Option A lands, requires **migration 024** (see §"Migration ownership") to extend the constraint |
| `fetch_vix_close` | function in `cockpit_daily_snapshot.py` (or new `sources/vix.py`) | Phase 6 §"VIX data dependency" Option B | Phase 6 (conditional on Option B) | Not v1 |
| `vix_history` | new table OR reuse of `realized_volatility_history` with `ticker='VIX'` | Phase 6 §"VIX data dependency" Option B | Phase 6 (conditional on Option B) | Decision punted to Phase 6 kickoff |
| `cockpit_dry_mode_strict` | new boolean in `Settings` | Phase 2.5 §Failure modes | Phase 2.5 | Default `False`; toggle to surface deriver exceptions during the audit |
| `scripts/cockpit/dry_mode_audit.py` | new audit script | Phase 2.5 §Procedure | Phase 2.5 | CLI spec in §Procedure |
| `scripts/cockpit/refit_thresholds.py` | new refit script | Phase 5 §Mechanics | Phase 5 | One-paragraph spec; full I/O contract = Phase 5 PR |
| `scripts/notebooks/cockpit_skew_sanity.py` | new sanity script | Phase 0 | Phase 0 | Plot + verdict |
| `src/uw_scan/cards/matrix_state_thresholds.py` | versioned-dataclass module | Phase 5 §Mechanics | Phase 5 | Code shape = "ThresholdsV1 / V2 / …" frozen dataclasses |
| `src/uw_scan/api/routers/cockpit.py` | new router | Phase 3 | Phase 3 | Mounted at `/api/cockpit` |
| `web/lib/api.ts` `api.cockpitState` wrapper | new typed wrapper | Phase 3 §UI | Phase 3 | Mirrors existing wrappers at lines 18–117 |
| Migration `023_matrix_state_threshold_version.sql` | new migration | Phase 5 §Mechanics | Phase 5 | Adds `threshold_version INTEGER NOT NULL DEFAULT 1` to `matrix_state_snapshots` AND bundles a `COMMENT ON COLUMN cluster_coverage_ok` update per Known Inconsistency #10 |
| Migration `024_matrix_state_display_only_tier.sql` | conditional new migration | Phase 2.5 §Relief valve Option A | Phase 2.5 (conditional) | Extends `consistency_tier` CHECK to include `display_only`. ONLY runs if Phase 2.5 audit triggers Option A. If Option B or C is chosen, migration 024 is never written |

If any of these symbols look "real" in a grep, it means a later phase has merged. If grep returns nothing, the symbol is still build-prerequisite vocabulary.

---

## Migration ownership

Several plan sections reference future migrations. To prevent collisions:

| # | File | Bundle | Triggered by | Notes |
|---|---|---|---|---|
| 022 | `022_matrix_state_snapshots.sql` | Phase 1 — `matrix_state_snapshots` table | already merged | On disk now |
| 023 | `023_matrix_state_threshold_version.sql` | (a) `ADD COLUMN threshold_version INTEGER NOT NULL DEFAULT 1` AND (b) `COMMENT ON COLUMN cluster_coverage_ok IS '...neutral OR both stale...'` per Known Inconsistency #10 | Phase 5 starts | One migration, two changes, atomic. The COMMENT update has no behavioral impact — it just brings the SQL annotation in sync with deriver behavior |
| 024 | `024_matrix_state_display_only_tier.sql` | Extend `consistency_tier` CHECK to include `display_only` | **Conditional**: only if Phase 2.5 audit selects Option A | If Option B or C wins the audit, migration 024 is never written. If Option A wins, this migration MUST land before any deriver code can persist `display_only` |
| 025+ | reserved | future Pydantic field additions (e.g., `freshness_state`, persisted `vrp_sign_flip_30d_status`) | only if a future decision flips those from log-only/derived to persisted | Not currently planned |

**Rule**: if a phase needs a schema change not in the table above, allocate the next free number and add a row here before writing the SQL. Do not silently overload an existing migration number.

---

## Known inconsistencies between research docs and shipped code

Codex should resolve each of these the first time it touches the affected area, and either fix the doc or the code so the disagreement disappears.

| # | Disagreement | Source of truth | Resolution |
|---|---|---|---|
| 1 | Research `00 §0.1` references `vrp_zscore_252d`; migration 022 column is `vrp_zscore_60d` | Migration 022 (it's already on disk; changing it requires a migration 023) | Phase 2 deriver computes a 60-day z-score, populates `vrp_zscore_60d`. Update `00 §0.1` to say `vrp_zscore_60d > +0.5` / `< −0.5`. The 252-day window was the research-doc default; 60 days is what the shipped table holds |
| 2 | Research `00 §0.4` claims "SPX baseline `risk_reversal` is negative" — not yet verified against real `risk_reversal_skew_history` rows | Live data | Phase 0 sanity check answers this. If SPX skew rows show the opposite sign, fix the §0.1 direction-mapping for skew BEFORE Phase 2 |
| 3 | Research `00 §0.3` says Vanna/Charm stale = 30min RTH; Phase 1 job only runs once daily at 16:30 ET | Phase 1 reality | Phase 2 deriver treats Vanna/Charm as fresh if the most-recent `greeks_by_expiry_strike` row is from `market_date`. The 30-min intraday threshold becomes meaningful only after Phase 1.5 (intraday refresh) lands — that's parked |
| 4 | `vrp_sign_flip_30d` referenced in §0.2 has no column anywhere | Phase 2 will derive inline | Compute from the last 30 days of `vrp` values from `realized_volatility_history` + `interpolated_iv_snapshots`. If fewer than 30 *aligned* (ticker, market_date) joined rows exist, set `vrp_sign_flip_30d_status = "insufficient_history"` (NOT silently False) and skip the override — leave `vrp_state` from §0.1, no tier downgrade. The status is **log-only in v1** (emitted via `logger.info` from the deriver); it is NOT a field on `MatrixState` and NOT a column in `matrix_state_snapshots`. If a future need to surface this on the UI emerges, add a Pydantic field + migration 024 column |
| 5 | Phase 1 job's `no expiries found` path produces a day with no per-strike rows | Code reality | Phase 2 deriver maps this to `vanna_state = stale`, `charm_state = stale`, `consistency_tier = insufficient_data`. Worked trace in §"State machine specification" Example 2 |
| 6 | Research `08 §4` build-sequence has 15 items; this plan's Phase 1–5 covers ~10 of them | Plan supersedes the build sequence | The remaining items (Bekaert-Hoerova VRP, NDX/RUT, etc.) are in the "Parked" section below. Build-sequence ordering in `08 §4` is no longer authoritative for execution order — this plan is |
| 7 | Research framework names "6 dimensions"; v1 ships with effectively 5 voting dims (IM and Flow always `stale` until calendar + footprint classifier land) | Plan §"v1 dimensional coverage" | Deriver labels IM and Flow as `stale`, not `neutral`. State tab displays "5 fresh dims, N agree" — never "5/6" or "6/6". When IM and Flow plumbing lands, denominator transitions to 6 cleanly without label-semantic change |
| 8 | Research `00 §0.4` def-of-done assumes the cluster-coverage rule produces useful tiers; Phase 2.5 audit may show this is pathological | Phase 2.5 audit + relief-valve decision | If audit fires the relief valve (Option A renaming `no_trade` → `display_only`), `00 §0.4` def-of-done items 4 and 5 need a one-line update reflecting the new tier name. Defer that edit until the relief-valve decision is final |
| 9 | Plan repeatedly described the AI blacklist as the "vanna/charm blacklist". Actual tuple at `src/uw_scan/reports/trade_insights_ai.py:965` is `("charm", "vanna", "short_interest")` | Code reality | All three terms stay in the tuple. The Cockpit work does NOT touch the `short_interest` element. Mentions of the blacklist must cite the full tuple to stay accurate. Plan locations already corrected: §Non-goals, §Parked, §Immediate next actions §"NOT do unilaterally" |
| 10 | Migration 022 lines 64–66 `COMMENT ON COLUMN cluster_coverage_ok` says the flag is `False when both Vanna and Charm are neutral (no dealer-flow confirmation per Limitation #1) — forces NO-TRADE in §0.2`. §"State machine specification" step 4 extends this to "both Vanna AND Charm are neutral **OR stale**" (the no-greeks empty-source path also forces flag=False; step 7 then applies the tier override to no_trade only when tier is content) | Spec step 4 + step 7 (the extension makes the deriver robust to empty-source days; the flag/tier split formalizes them) | Phase 2 deriver implements the broader "neutral OR stale" trigger. Migration 023 (the threshold-version migration) **bundles** a `COMMENT ON COLUMN` update for `cluster_coverage_ok` to: `False when both Vanna and Charm are neutral OR both stale (no dealer-flow confirmation OR empty source — forces NO-TRADE unless tier is already insufficient_data)`. See §"Migration ownership" for the full migration 023 contents |
| 11 | Plan §Phase 3 originally hardcoded the API universe guard to `{"SPX","SPY","QQQ","IWM"}`, decoupling it from the worker's `settings.cockpit_tickers`. After SPX is potentially dropped by the Phase 1 smoke (§88), the API would still accept SPX requests and 404 confusingly | Plan §Phase 3 (now reads `settings.cockpit_tickers`) | Already fixed in the plan body. Codex implementing the router must read from settings, not from a local set literal |

When fixing #1 or #2 in the research doc, leave a one-line note at the top of the affected section: `> Updated 2026-MM-DD per plan §"Known inconsistencies" — was X, now Y.` Preserves the audit trail.

---

## Cross-references

| Topic | File |
|---|---|
| Framework + per-dim research | `docs/superpowers/research/six-dimension-matrix/00-overview.md` through `07-limitations.md` |
| Implementation gap audit | `08-implementation-gaps.md` |
| Backtest design (now parked) | `09-backtest-plan.md` |
| UW history spike (the blocking finding) | `reviews/2026-05-15-uw-history-spike.md` |
| §0 codex review | `reviews/2026-05-15-codex-section0.md` |
| Aggressor classification semantics | memory `project_aggressor_classification_semantics.md` |
| Data persistence rule | memory `feedback_persist_results_to_db.md` |

---

## Immediate next actions

In order. Each step is a complete-able codex turn.

1. **Phase 1 smoke** — run the inline `uv run python -c "..."` block from Phase 1 §Outstanding. Expected: 4 INFO log lines, no exceptions, non-zero row counts. Failure modes to handle:
   - 401 from UW → key in `.env` is bad / expired
   - 0 rows from `fetch_realized_volatility` → endpoint contract change; re-run `scripts/uw_history_spike.py` to confirm boundary
   - `no expiries found` on SPX → SPX index options use different OCC root; verify `pick_target_expiries` actually finds rows for SPX (this is a known fragility — investigate before declaring Phase 1 stable)

2. **Open PR** — `cd ~/.config/superpowers/worktrees/unusual-whales/cockpit-matrix && gh pr create --base main --head feat/cockpit-matrix --title "feat: Phase 1 cockpit-matrix data accumulation" --body "$(...)"`. Body summarizes the 3 commits + links this plan doc. Do NOT merge — wait for CI green + user review.

3. **Phase 0** — create `scripts/notebooks/cockpit_skew_sanity.py` (script, not notebook — repo has no notebook workflow). Pull trailing-year skew rows, compute z-scores, plot to `/tmp/cockpit_skew_*.png`, write verdict to `docs/superpowers/research/six-dimension-matrix/reviews/2026-05-XX-skew-sanity.md`. Commit on `feat/cockpit-matrix`.

4. **Phase 2** — only if Phase 0 verdict is "proceed". Otherwise fix `00 §0.1` skew sign-convention first, re-run Phase 0, then start Phase 2. Phase 2 deliverable: `cards/matrix_state.py` + `MatrixState` model + repository methods + tests + scheduler wiring + charm-v1-proxy implementation per Phase 2 §"Charm v1 simplification". Target: one PR per phase from here on.

5. **Phase 2.5** — after Phase 2 lands, let scheduler run 5 trading days, then run dry-mode audit. Apply cluster-coverage relief valve (A/B/C) per the audit's findings. Open PR with any required code changes. **Do not start Phase 3 until 5 acceptance criteria are green.**

**What codex should NOT do unilaterally**:

- Modify any file in `docs/superpowers/research/six-dimension-matrix/` other than `reviews/*.md` — the framework docs are stable references; structural changes need user approval
- Merge any PR
- Change the `src/uw_scan/reports/trade_insights_ai.py:965` blacklist tuple (`("charm", "vanna", "short_interest")`)
- Add `vanna`/`charm` to any `single-stock` codepath
- Change `cockpit_target_dtes` defaults without a PR-attached note explaining why
