# Sector relative strength + breadth (`sector_rs_daily`) — design

Status: DRAFT 2026-09-26. Research-first: the table and nightly job ship; a UI
ships only if the research question in §6 clears its gate.

## 1. Why

GICS in argon today answers one question: which valuation yield a name gets
(`company_sector` → `VENDOR_SECTOR_TO_TYPE` → `company_type`). It answers
nothing about whether a sector is leading, and nothing about whether a
"leading" sector is a sector or one name (Communication Services +5% RS on 26%
breadth is META, not a sector). The watchlist is AI/semi-concentrated, so the
same trap applies to argon's own chains: Semi-Logic strong, or NVDA strong?

Two measurements, both zero-UW-cost after a one-time classification fill:

- **RS** — group return minus S&P 500 return over 1M/3M/6M/12M.
- **Breadth** — share of the group's constituents that beat the S&P 500 over
  the same window. Breadth is what separates "sector" from "single name".

Not built: the RRG four-quadrant graph (RS-Ratio / RS-Momentum are 10-week and
4-week moving-average crossovers, descriptive, same family as the GEX
regime-persistence and VCG forward-return lines already closed as
not-predictive). Nothing in this spec is a trade signal.

## 2. Two group kinds, one table

| `group_kind` | groups                           | RS weighting                                                                                                            | breadth constituents                                           | membership source                                                                             |
| ------------ | -------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `gics`       | 11 SPDR sector ETFs              | `etf` — the ETF's own close vs SPY; official cap-weighted GICS sector, no market-cap data and no GICS map needed for RS | S&P 500 members, mapped ticker→sector through `company_sector` | vendored `src/uw_scan/sources/data/sp500_members.json` (copy of livewire `presets/sp500.json`; see §4 for why not the membership route) |
| `chain`      | every chain in `watchlist_chain` | `equal` — mean member return vs SPY (no ETF exists; the row says so)                                                    | the chain's members                                            | `uw_scan.watchlist_chain`                                                                     |

ETF map (fixed, in code): XLK Technology, XLC Communication Services, XLY
Consumer Cyclical, XLP Consumer Defensive, XLE Energy, XLF Financial Services,
XLV Healthcare, XLI Industrials, XLB Basic Materials, XLRE Real Estate, XLU
Utilities. The right-hand labels are the vendor's (`company_sector.sector`
vocabulary, Yahoo-style, one-to-one with GICS sectors); `Energy` here is oil
and gas, never argon's chain `Energy` (power infra) — the two vocabularies stay
in separate `group_kind`s and are never joined (see migration `123` header).

Benchmark for both kinds: SPY adjusted close. Windows: 21 / 63 / 126 / 252
trading days, labelled `1m` / `3m` / `6m` / `12m`, ending on the last daily
close ≤ `as_of`. Returns are plain price returns on adjusted closes; RS is the
difference of the two returns (not a ratio), in percentage points.

## 3. Table — migration `152_sector_rs_daily.sql`

```sql
CREATE TABLE IF NOT EXISTS uw_scan.sector_rs_daily (
    as_of          DATE NOT NULL,
    group_kind     TEXT NOT NULL CHECK (group_kind IN ('gics','chain')),
    group_key      TEXT NOT NULL,          -- 'Technology' | 'Semi-Logic' ...
    weighting      TEXT NOT NULL CHECK (weighting IN ('etf','equal')),
    rs_symbol      TEXT,                   -- 'XLK' for etf rows, NULL for equal
    n_members      INTEGER NOT NULL,       -- constituents in the group at as_of
    n_classified   INTEGER NOT NULL,       -- == n_members for both kinds today (a member with a NULL sector belongs to no group; the index-level unclassified count is a job counter, acceptance §9.3). Kept so a future multi-source label can report partial coverage per row
    n_priced       INTEGER NOT NULL,       -- members with a close on BOTH boundary dates of SPY's 252-day window (a name delisted mid-window is not 'priced' on stale data)
    rs_1m  DOUBLE PRECISION, rs_3m  DOUBLE PRECISION, rs_6m  DOUBLE PRECISION, rs_12m DOUBLE PRECISION,
    breadth_1m DOUBLE PRECISION, breadth_3m DOUBLE PRECISION, breadth_6m DOUBLE PRECISION, breadth_12m DOUBLE PRECISION,
    degraded       BOOLEAN NOT NULL DEFAULT FALSE,  -- n_priced < 0.8 * n_members, or an RS input missing
    source         TEXT NOT NULL,          -- 'apex' | 'daily_ohlc'
    computed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (as_of, group_kind, group_key)
);
```

Breadth for window `w` = (members with return_w > SPY return_w) / n_priced_w;
`n_priced` stores the 252-day count; a member counts for window `w` only if it has a close on both of SPY's boundary dates for `w`. The shorter windows use their own count in
the compute but only the longest is persisted (the coverage question is "can
we trust the 12m number", the others are supersets). A `degraded` row is still
written — it is the coverage statement — but the research script excludes it.

Idempotent `ON CONFLICT (as_of, group_kind, group_key) DO UPDATE` on every
column. Nightly re-runs and backfills converge on the same row.

## 4. Sources and cost

**Bars.** apex bulk route `GET /v1/equity/bars?symbols=A,B,C&timeframe=1d&start=&end=&limit=0&price_mode=adjusted&listing=any`
(apex `src/api/routes/bulk_bars.py`, live on the mini since v0.1.12; confirmed
by the apex session 2026-09-26). 1–200 symbols per call, `start`/`end` must be
tz-aware ISO (a bare date is a 400), response `{"symbols": {SYM: {"listing_status",
"truncated", "bars": [...]}}, "missing": {SYM: reason}}`; every per-symbol
failure lands in `missing`, never fails the call; all series pinned to one
Silver revision. `sources/apex.py` gains
`fetch_bulk_daily_closes(symbols, *, start, end) -> dict[str, dict[date, float]]`
over it (chunks of 200; the S&P 500 is three calls, ~12 s measured). A symbol in
`missing` is absent from the dict and the caller counts it under `n_priced`,
never as a zero return. Fallback for the 12 ETF/SPY symbols only: `daily_ohlc`
(massive), tagged `source='daily_ohlc'`.

**Two lake limits that bound the survivorship claim (both measured by the
apex session 2026-09-26).** (a) livewire adjusts only LISTED names, so
`listing=any&price_mode=adjusted` returns delisted former members in `missing`
("no Silver for delisted names"); their bars exist only raw, a different basis.
(b) livewire's security master is not usable for membership yet: apex
`/v1/membership/sp500` at `as_of` before 2026-09-17 returns roughly half the
members, and even TODAY's list is 485 rows of which ~35 carry `symbol: null`,
several are dead tickers (BHGE, SBC, PKI, FISV) and META/XOM/AVGO/LIN are
absent (measured 2026-09-26 via apex-lake `get_index_members`; filed as
livewire #158, https://github.com/moremeds/livewire/issues/158 — the store
was partly repaired 2026-09-24 but the sp500 PIT republish is blocked, and
several identity errors remain). Ruling:
argon does NOT call the membership route. Membership comes from a vendored
copy of livewire's `presets/sp500.json` (503 tickers, clean, the list
livewire itself ingests from) at `src/uw_scan/sources/data/sp500_members.json` with
`as_of` and the livewire commit it was copied from; `scripts/research/sync_sp500_members.py`
refreshes it from a livewire checkout. The preset's own label says it was
compiled from Wikipedia in March 2026, so "current" means the March 2026
index until livewire refreshes the preset; `as_of` records the copy date, not
the index date. The presets are not in the lake mount
the container sees, which is why it is vendored rather than read. Both the
nightly job and the backfill use this **current** list and adjusted closes
for listed names only; delisted former members are counted in `n_members` (when the membership
is known) but never priced, so breadth carries survivorship bias over the
backfill window and the row's `n_priced/n_members` shows how much. Over a
1998 start that set is large (most of today's list was not the 1999 index),
which is exactly what the §4 coverage exclusion and the §6 effective-start
report exist to bound; the verdict states the surviving n. Upgrade path, out of scope:
livewire fixes the security master and publishes Silver for delisted names;
the job then switches to apex `/v1/membership/sp500?known_at=as_of` and the
backfill re-runs. The nightly job is
unaffected (it reads today's membership).

**History depth.** Measured 2026-09-26 the sector ETFs started at the
2021-06-11 seed (XLF 2021-05-18); livewire #157
(https://github.com/moremeds/livewire/issues/157) backfilled them through IB
on 2026-09-27. Silver (what `price_mode=adjusted` reads) as measured on the
mini by the livewire session on 2026-09-27, silver rev 81, via apex adjusted
bars:

| symbol                 | first_date | note                                                                      |
| ---------------------- | ---------- | ------------------------------------------------------------------------- |
| SPY                    | 1993-01-29 |                                                                           |
| XLV XLI XLP            | 1998-12-22 | 4 sessions after the 1998-12-16 launch; clean                             |
| XLF                    | 1998-12-22 | **was wrong before 2016-09-19, fixed in rev 88 (2026-10-01)**: the XLRE spin-off is booked as both a $4.44 dividend and a 1.139 split, a false +31% jump on 2016-09-19 |
| XLK XLY XLB XLU XLE    | 2021-06-11 | still the old seed: IB served pre-2025 bars already adjusted for the 2025-12-05 2:1 split, livewire labelled them raw, Silver's seam check cut them; fix in progress under #157 |
| XLRE                   | 2015-10-08 | 1 session after launch; clean                                             |
| XLC                    | 2018-06-19 | 1 session after launch; clean                                             |
| PKG (a constituent)    | 2000-01-28 |                                                                           |

The five cut funds need no code: apex returns no adjusted bars before
2021-06-11, the RS input is missing, the row is `degraded`, and a `--force`
re-run fills it once Silver republishes. XLF does need code, because its bad
history is served as if it were good: each `gics` group carries an optional
`rs_valid_from` date, and any RS window whose start anchor precedes it is
NULL (so the row is `degraded`). The only entry was XLF → 2016-09-19.
**Update 2026-10-01:** Silver rev 88 fixed the XLF seam (2016-09-16 → 09-19
moves +0.7%, no daily move over 17% outside 2008-09), so the entry is removed
before the first backfill and no `--force` re-run is needed.

Nothing fills the first 1–4 sessions (IB has no earlier bars, massive stops
at 5 years); they are irrelevant at a 252-day window. So `etf`-weighted RS
runs ~27 years for all nine 1998 funds (XLF included since rev 88). What does NOT run that long is breadth: the
vendored current list applied to 1999 prices names that were not listed then,
so early `n_priced/n_members` is low and those rows are `degraded` (< 80%)
and excluded from the probe. The probe reports the first date each group
clears 80% coverage; that, not 1998, is the effective sample start, and the
§6 verdict states it. The backfill must not start before Silver has
published the new history for all nine 1998 funds — the backfill's
pre-flight asks apex for adjusted January-1999 bars for each of them and
aborts naming the funds still missing (today: XLK XLY XLB XLU XLE).

**Classification fill (the only UW spend, one-time).** `company_sector` holds
450 names today, mostly the fundamental universe; `company_sector_refresh`
(04:40 ET daily, uw-0) asks UW `/stock/{ticker}/info` once per name that has
no row. Its universe query (`tickers_needing_fetch`) is widened to include
current `sp500` members, which costs an estimated ~330 calls on the first run
after deploy (485 members minus the overlap) and zero afterwards. Former
members that UW no longer classifies get a recorded NULL and fall out of the
breadth denominator by belonging to no group (logged as `unclassified` by the job). The run cap in that job
(`max_calls`) already bounds a universe explosion; raise it if it binds.

Membership is applied as **current classification over the whole window**
(and, for `chain` rows, today's chain membership over the whole backfill —
argon keeps no chain history, so backfilled chain rows carry look-ahead and
the §6 probe reads `gics` rows only),
the same convention as the reference tool. The known distortion: GICS moved
names into Communication Services in 2018-09, and XLRE split from XLF in
2015-10; with a 2021+ ETF history neither reclassification falls inside the
sample, so this is a documentation note, not a measured bias.

## 5. Code shape

- `reports/sector_rs.py` — pure compute. `compute_group_rows(as_of, groups, closes, spy_closes) -> list[SectorRsRow]`; no I/O, no DB. One function serves the nightly job and the backfill (no duplicate logic, the rule the research capture/catch-up pair already follows).
- `storage/sector_rs.py` — `SectorRsRepository.upsert_rows`, `latest(as_of, group_kind)`, `history(group_kind, group_key, since)`. Own module; not added to `repository.py` beyond assembly.
- `sources/apex.py` — `fetch_bulk_daily_closes` (above).
- `worker/jobs/sector_rs_daily.py` — resolves membership (`sources/sp500_members.py::sp500_members()` — the vendored list — for `gics`, `watchlist_chain` for `chain`), pulls closes, calls the compute, upserts today's rows, logs `{groups, degraded, source}` counters. Scheduler: 21:30 ET Mon–Fri, `massive-0`, after `ohlc_pull` (17:30) and the freshness monitor (21:00), `max_instances=1`, `coalesce=True`. Gate `UW_SCAN_SECTOR_RS_ENABLED`, default **off** (flip on the mini after the backfill lands).
- `scripts/backfill/sector_rs_backfill.py --start --end [--group-kind]` — same core, one row-set per trading day, resumable (skips dates already present unless `--force`). Persists to the same table; that is the research trace.
- `worker/jobs/company_sector_refresh.py` — universe widened per §4.
- `/api/health` `freshness`: enrol `sector_rs_daily` in `MONITORED_TABLES` (a new temporal table needs the freshness gate and the dataset-policy doc row; see `docs/runbooks/data-gap-dataset-policy.md`). Not enrolled in the gap healer: the backfill script is the heal.

Read surface: none in this PR. No router, no `types.ts` change. The research
script reads the table directly.

## 6. Research question and gate

Script `scripts/research/sector_rs_breadth_probe.py`, output committed under
`docs/research/<run-date>-sector-rs-breadth/` (dated the day the probe runs) (`VERDICT.md` + the full
result CSV + the exact reproduce command), run after the backfill covers the
full ETF history (1998-12-22 onward for the nine, per §4).

**H1.** For a `gics` group on date _t_, condition C = `rs_1m(t) > 0` and
`breadth_1m(t)` in the bottom tercile of that group's own history. Then
P(`rs_1m(t+21) < 0` | C) exceeds the unconditional P(`rs_1m(t+21) < 0`) for
that group.

Method: non-overlapping monthly observations (every 21st trading day per
group), `degraded` rows excluded, tercile computed expanding (only past values
of the group, so C is knowable at _t_). Report per-group and pooled
conditional probability, baseline, n, bootstrap 95% CI on the difference, and
a holdout split at 2019-01-01 (in-sample from each group's effective start
→ 2018-12, out-of-sample 2019-01 → present; XLC therefore has no in-sample
and is reported OOS-only, XLRE ~3 years in-sample). Also report the same test with `breadth_3m` as the
conditioning variable, pre-registered here so it is not a second look.

Sample size: nine groups × up to ~320 months plus XLRE/XLC ≈ 3,000 pooled
observations before the coverage exclusion, of which C selects roughly a
third of the positive-RS months. The coverage exclusion (§4) removes the early
years where the current list is too thin; the verdict reports the surviving n
per group and pooled.

**Gate to a UI:** pooled OOS difference > 0 with the bootstrap CI excluding
zero, and no group where the conditional probability is below baseline by
more than the CI half-width (the per-regime catastrophic-degradation pattern).
Fail → the table stays as descriptive data on the stock/regime pages' backlog,
no panel is built, and `VERDICT.md` records the numbers.

## 7. Tests

- `tests/unit/reports/test_sector_rs.py` — frozen real closes for SPY, XLK and
  three Technology constituents over a fixed 260-session window ending on a
  stated as-of date (fetched once at authoring time, hardcoded, no network):
  RS sign and magnitude, breadth count, `n_priced` when one member is short a
  window, `degraded` flips at < 80% coverage, `equal` vs `etf` weighting
  selects the right numerator.
- `tests/unit/sources/test_apex_bulk.py` — bulk parser: absent symbol absent
  from the dict, `truncated` page handled, error body → `{}` never raises.
- `tests/integration/storage/test_sector_rs_repository.py` — upsert
  idempotence, `history` ordering.
- Job test: membership resolution stubbed, compute called once per group kind,
  counters logged; the `chain` kind on an empty `watchlist_chain` writes zero
  rows and does not fail the run.

## 8. Out of scope

RRG quadrant chart; any web panel (gated on §6); cap-weighting chains (no
market-cap history in argon); sub-industry (GICS L2–L4) grouping — the vendor
sector is one level and the chain taxonomy already is argon's L2; livewire ETF
backfill (named as the upgrade path in §4).

## 9. Acceptance

1. `sector_rs_daily` populated for every trading day from 1998-12-22 to the
   current close for both group kinds (`chain` rows from the earliest date
   its members price). `rs_12m IS NOT NULL` on ≥ 95% of `gics` rows from each
   fund's first_date + 252 sessions (≈2000-01 for the nine 1998 funds,
   2016-10 for XLRE, 2019-07 for XLC): that is the ETF leg,
   which has no coverage problem. The `degraded` share (the breadth leg) is REPORTED per
   group per year, not gated — its early years are thin by construction and
   the §6 effective start is where it becomes usable. An empty group is also
   `degraded`.
2. Nightly job writes today's 11 + N rows on the mini within one session of
   the flag flip; freshness block shows the table.
3. `company_sector` covers ≥ 95% of current `sp500` members after one refresh
   run.
4. `docs/research/…/VERDICT.md` exists with the §6 numbers and the reproduce
   command, and states PASS or FAIL against the gate.
