# The valuation band was priced against the wrong share basis

**Date:** 2026-08-21 · **Status:** fixed on `fix/anchors-split-adjusted-prices`
**Scope:** `valuation_anchors`, `GET /api/scanner/value`, the Fundamentals card band

## Finding

`valuation_anchors` builds each name's band from 20 quarters of
`fundamental / shares ÷ price`. The two legs were on different corporate-action
bases:

- **UW restates `common_stock_shares_outstanding` onto today's post-split basis**,
  back to the start of the panel.
- **Bronze stores closes unadjusted** (`adj_close` is an unpopulated copy of
  `close`). The job read bronze.

So `fundamental / shares` arrives in today's units while the price does not, and
every quarter before a split yields a number wrong by the split factor.

Verified against the mini's store, 2026-08-21 — each is the real count times the
factor of a split that had not yet happened:

| ticker | our 2021-12-31 shares | actual then | split |
|---|---|---|---|
| TSLA | 3,100,522,833 | ~1,033M | 3-for-1, 2022-08-25 |
| KLAC | 1,523,310,000 | ~152M | 10-for-1, 2026-06-12 |
| BKNG | 1,034,275,000 | ~41M | 25-for-1, 2026-04-06 |

## Damage, measured against each band's own window

Not a fixed cutoff — the 20 most recent quarterly `period_end`s per ticker plus
the 45-day knowledge lag, which is the window `_history` actually prices.

```
banded names at as_of 2026-08-18                335
  split cliff inside the yield window            26   (19 splits, 7 real price moves)
  of those, rendered IN THE BUY ZONE             12
```

BKNG is the clearest case: 20 quarters of sales yield 25x too low set
`buy_below` at **$4,702.64** against a **$208.25** spot, so the name read as
cheap. A reverse split runs the same error the other way — CXAI's 50-for-1 put
its band at $0.11–$0.40 against a $4.26 spot.

## The lake already solves this — in a tier argon was not reading

livewire derives a **silver** tier: fully back-adjusted daily bars with
`price_adjustment_factor` and `split_volume_factor` per session, published only
after every artifact validates (`scripts/livewire_store.py rebuild-silver`).
13,240 equity symbols on 2026-08-21. Argon's containers already mount the whole
lake at `/lake:ro`, so it was reachable the entire time — `lake_resolver.py`
just addresses `bronze/` and nothing pointed anywhere else.

Silver dominates anything reconstructable from bronze on three counts.

**It repairs the 2021-06-11 basis seam.** Every bronze equity series steps that
day, `source='legacy'` on both sides, in both directions — TSLA 203.37 → 609.89,
WMT 46.63 → 140.75. Those are later splits showing through one segment and not
the other: pre-seam rows were back-adjusted by a legacy backfill, post-seam rows
are raw, and the two were concatenated without reconciling.

**It is per-symbol, where an argon-side clamp can only be global.** The first
version of this fix clamped every series to 2021-06-11. That is livewire's
boundary for the *ambiguous* symbols and nobody else's:

| ticker | bronze `price_basis` | silver spans |
|---|---|---|
| TSLA / WMT / CTAS | mixed legacy | 2021-06-11 → 2026-08-20 |
| KLAC | `raw` throughout (11,044 rows) | **1980-10-08** → 2026-08-20 |
| BKNG | `raw` throughout | 1999-03-30 → 2026-08-20 |

The global clamp cost KLAC forty years of history to fix a defect KLAC does not
have.

**Where it cannot establish a basis it publishes nothing** — a refusal argon can
read, rather than a wrong number argon has to detect. 18 of the 450 universe
names have no silver artifact on 2026-08-21, and it is exactly the set whose
bronze `price_basis` is `unknown`:

```
HON    n=11445  basis={'unknown': 11418, 'raw': 27}   -> no silver
CMCSA  n=11443  basis={'unknown': 11416, 'raw': 27}   -> no silver
BKNG   n= 6892  basis={'raw': 6892}                   -> silver
```

Full list: AIG ALB APLD AXON CCEP CCJ CFLT CMCSA CNC CXAI CYBR ECL HON JNPR
LOGI MSTR PSTG TRI.

## Column algebra: split-only, not total-return

Silver's `close` is adjusted for splits **and** dividends. Only the split half
belongs in a valuation yield:

```
market_cap(t) = shares_actual(t)   x price_actual(t)
              = shares_restated(t) x [price_actual(t) / split_factor(t)]
              = shares_restated(t) x split_only_close(t)
```

Nothing restates a share count for a cash dividend — the dividend genuinely
lowered market cap — so leaving silver's dividend adjustment in understates every
historical market cap on a payer, inflates its historical yields, and biases the
whole band cheap against an unadjusted spot. So:

```
split_only_close = close / (price_adjustment_factor x split_volume_factor)
```

Verified exact against raw bronze, 2026-08-21:

| ticker | date | silver `close` | split_only | raw bronze | svf |
|---|---|---|---|---|---|
| BKNG | 2026-04-02 | 167.3493 | **167.7700** | 4194.25 | 25.0 |
| BKNG | 2026-04-06 | 175.7482 | **176.1900** | 176.19 | 1.0 |
| TSLA | 2022-08-19 | 296.6667 | 296.6667 | 890.00 | 3.0 |

BKNG pays a dividend, so `split_only` ≠ `close`; TSLA does not, so its factors
are exact reciprocals and nothing is divided out. `176.19` matching raw exactly
at `svf=1` is the identity check.

### apex serves the fully-adjusted close, so it cannot source this

apex's `GET /bars/{ticker}` is the desk's normal price/bar read and it is indeed
silver-grade — its BKNG close for 2026-04-02 is `167.349`, which is silver's
`close` **verbatim**. That is exactly why it cannot source a valuation band: the
number it serves is the total-return one, dividends divided out and all, and the
endpoint exposes no adjustment parameter and neither factor column. Split-only is
not derivable from what apex returns.

Two names isolate each half cleanly, measured 2026-08-22:

| ticker | event | `pf x svf` | silver `close` | split_only | raw bronze |
|---|---|---|---|---|---|
| CRWD | 4-for-1 split, **no dividend** | **1.000000** | 99.7800 | 99.7800 | 399.12 |
| ETR | **dividend**, no split | 0.988670 | 113.5982 | **114.9000** | **114.9000** |
| BKNG | both | 0.997492 | 167.3493 | 167.7700 | 4194.25 |

CRWD's factors cancel to exactly 1.0, so silver's close already IS the split-only
close and apex would be correct for it. ETR never split, so its whole factor is
dividend: apex serves 113.5982 where the market-cap-correct price is 114.90. That
1.13% error would enter every one of ETR's 20 quarters, compounding backwards,
and it biases the band **cheap** — the direction that puts a name on the buy
list. It is the same bug class this document is about, entering by another door.

The pair also verifies the arithmetic in both degenerate directions: pure-split
reproduces bronze/`svf` exactly, pure-dividend reproduces raw bronze exactly.

## Fix

1. `fundamental_anchors` reads **silver**, dividing out the dividend factor.
2. Names with no silver artifact fall back to raw bronze — provably equivalent
   when no split falls inside the window being priced, since an
   unknown-but-consistent basis IS today's basis when nothing has restated the
   shares since. `_bronze_basis_refusal` decides this per ticker.
3. A name with no silver **and** an in-window split is **refused**, not banded.
   So is a name with **no corporate-action record at all** — see below.
4. `corporate_actions_refresh_once` covers the fundamental universe (it held
   137 of 450), because that store is the evidence step 2 runs on. It fires at
   17:35 ET, 45 minutes before `fundamental_refresh`.
5. `ANCHOR_RULES_REV` 3 → 4, so corrected rows are not dropped by
   `ON CONFLICT DO NOTHING` — no hashed input changes when only prices do.

### The guard read missing data as clean data

Step 2 is only sound while "no split on record" means the ingest looked and
found none. Measured on the mini, 2026-08-22:

| | |
|---|---|
| fundamental universe | 450 |
| with **zero** `corporate_actions` rows | **313** |
| of the 18 silver-less names, zero rows | **15** |
| ingested names (188) with zero rows | **0** |

313 is exactly 450 − 137, the universe minus what the deployed ingest covered.
So for 15 of the 18 names that must be priced from bronze — AIG, ALB, AXON,
CCEP, CFLT, CMCSA, CNC, CXAI, CYBR, ECL, HON, JNPR, LOGI, PSTG, TRI — the guard
returned "no split in window" because **nobody had asked**, not because none
happened. CMCSA and ECL have both split inside a 20-quarter window historically.
CMCSA was showing IN THE BUY ZONE on that basis, `buy_below` 35.27 vs a 26.42
spot.

`_bronze_basis_refusal` now requires positive evidence — any split or dividend
row for the ticker — and refuses without it. Zero rows is a sound proxy for
never-asked because a 12-split/24-dividend lookback catches nearly every
established name: of the 188 tickers the ingest did cover, not one had zero rows.

Its three known false positives are named rather than assumed. Probing massive
directly for all 18 silver-less names, only **CFLT, CYBR and PSTG** return no
split *and* no dividend, so no amount of ingesting will ever make them
verifiable. None of the three carries a band in either measured state, so the
coverage cost today is zero — but the ceiling is real, and an event table cannot
record a non-event. The upgrade path, if it ever matters, is a per-ticker ingest
coverage row written by `corporate_actions_refresh_once`, not a sentinel event.

Effect on the 2026-08-22 store, run against production writing nothing
(`STAGE_SPLITS=0`): refusals rise 4 → 10, and the six added are exactly the
never-ingested names that had bands (ALB, AXON, CMCSA, CNC, ECL, LOGI). With the
widened ingest simulated faithfully — its splits **and** its dividends —
(`STAGE_SPLITS=1`) it returns to 4: CXAI, HON, MSTR, TRI, the four with a real
in-window split. CCEP is the case that proves dividends belong in the evidence:
0 splits, 22 dividends, and it comes back with a band.

### A missing silver tier failed silently

`load_closes` skips a symbol whose parquet is absent, so an absent *tier* — a
bad mount, a livewire path change — yielded an empty dict, put all 450 names on
the bronze fallback, and reinstated the original bug without a single error.
The job now refuses to start unless `silver_root` is a directory. The previous
day's bands stand, which beats minting a universe of wrong ones.

### Why not adjust bronze in argon

The first attempt did, using massive's `/v3/reference/splits`. It worked for
forward splits and then made KLAC *worse* (9.47 → 9.98), because the legacy
segment already contains whatever splits were known at backfill time — CTAS's
2024 4-for-1 is baked in, KLAC's 2026 10-for-1 is not — and that date is
undocumented. The attempt before that scored price gaps with a volume
level-shift confirmation: ~1.0 recall on real splits, and it still called DOCU's
42% crash on 2021-12-03 a split. Any threshold loose enough to catch a 2-for-1
(gap 2.00) sits inside the range real crashes occupy. Neither is needed once the
producer's own adjusted tier is read.

## Result, verified against production writing nothing

`insert_anchors` swapped for a collector, splits for the 18 silver-less names
staged inside the transaction, `conn.rollback()` at exit.

```
considered 420 · banded 321 · refused 53 · unadjustable_prices 5 · written 416
```

Bands that moved more than 10%, and where the name sat relative to its band:

```
BKNG   spot   209.87   buy_below  4702.64 ->  190.13    IN -> --
KLAC   spot   185.86   buy_below   570.25 ->   62.82    IN -> --
CRWD   spot   190.34   buy_below   362.53 ->   90.07    IN -> --
NOW    spot   129.75   buy_below   861.91 ->  169.06    IN -> IN
CTAS   spot   203.52   buy_below   222.00 ->  156.50    IN -> --
FAST   spot    50.66   buy_below    51.45 ->   34.25    IN -> --
ETR    spot   107.34   buy_below    81.17 ->   32.79    -- -> --
APH    spot   153.11   buy_below   149.80 ->   84.48    -- -> --
WMT    spot   103.84   buy_below    98.79 ->   59.26    -- -> --
```

**Refused, correctly** — no silver series and a split inside the window:

```
CXAI   spot     3.94   was buy_below     0.11   (50-for-1, 2026-08-18)
TRI    spot   105.88   was buy_below   137.82   IN ZONE (buyback consolidations)
MSTR   spot   112.39   was buy_below   101.23   (1-for-10, 2024-08-08)
HON    spot   218.32   was buy_below   167.04   (1000-for-1061, 2025-10-30)
```

### The error also ran the other way

A split inside the window makes a name's own yield history look like it spans
two regimes, so the 4x width gate refused it. Seven names gain a real band, and
every one of them split in-window:

```
NVDA   spot   216.85   buy_below   245.33   IN ZONE   (1-for-4 2021, 1-for-10 2024)
AVGO   spot   364.03   buy_below   131.88             (1-for-10, 2024-07-15)
LRCX   spot   310.53   buy_below    79.32             (1-for-10, 2024-10-03)
ORLY   spot    89.08   buy_below    75.47             (1-for-15, 2025-06-10)
DECK   spot    88.86   buy_below   106.71   IN ZONE   (1-for-6,  2024-09-17)
SMCI   spot    36.50   buy_below    39.94   IN ZONE   (1-for-10, 2024-10-01)
BKSY   spot    26.73   buy_below     6.37             (8-for-1,  2024-09-09)
```

NVDA was refused in production for an *"own 20-quarter valuation range spans
16.9x, wider than the 4x limit"*. That span was its two splits — 4x in 2021 and
10x in 2024, 40x combined — not its valuation. **A previous session diagnosed
that refusal as a genuine two-regime yield window and concluded the 20-quarter
window was the cause. That was wrong**; the window is fine and the prices were
not.

## Verified in the production container, 2026-08-22

Each check ran in a throwaway container against `/opt/argon/.env` and the real
lake mount, never the running worker.

| Question | Answer |
|---|---|
| Does `/lake/silver/asset_class=equity` exist on the mini? | **yes** — the new hard fail will not self-inflict an outage |
| Does the SHIPPED image resolve `lake_fx_root`? | **no** — `/root/market-warehouse/.../fx`, `exists=False`. The bug is live in production right now |
| Does the FIXED config resolve it? | **yes** — `/lake/bronze/asset_class=fx`, `exists=True`, 21 symbols |
| Does `load_fx` orient an inverted pair correctly? | **yes** — EUR returns 0.85490 per USD, the reciprocal of the lake's `EURUSD` 1.16973. TWD 31.82, JPY 158.795, GBP 0.73251 |
| Does an absent currency return empty? | **yes** — DKK is EMPTY, so NVO is refused rather than banded unconverted |
| Does massive return splits newest-first? | **yes** — AAPL `2020-08-31 ... 1987-06-16` descending, so `split_limit=12` truncates away only pre-window history |
| Can the widened ingest finish inside its 45-minute gap? | **yes** — 20 tickers x 2 calls in 9.2s = 0.458 s/ticker, projecting **3.4 min** for 450 names |
| Does bumping `ANCHOR_RULES_REV` change `inputs_hash`? | **yes** — `rules.rev` is in the hash payload (`valuation.py`), and `test_anchor_reachability.py` monkeypatches the rev and asserts the hash moves |

Reproduce: `apex_vs_silver_check.py` in this directory carries the throwaway-
container pattern; the other probes used the same shape with
`--env-file /opt/argon/.env`.

## Residual, not fixed

**COHR** keeps a 5.42x cliff on 2022-07-01: II-VI acquired Coherent and took its
ticker, so the series concatenates two companies. massive correctly reports no
split. A ticker-identity seam is a different defect class and no discriminator
separates it from a real move, so it is recorded here rather than guessed at in
code. (CXAI had the same seam from its 2023 SPAC; it is now refused for the
unrelated reason that it has no adjustable series at all.)

**Upstream, for livewire:** the 18 `price_basis='unknown'` symbols are the
remaining gap. Every one that gets resolved returns a band automatically and
`unadjustable_prices` falls. That counter is the metric to watch.

**Found while measuring this, fixed in the same change:** 12 foreign filers were
refused for want of an FX series the lake was carrying. Two faults stacked.
`lake_fx_root` had no case in `Settings.from_env` at all, so it fell back to
`$HOME` — `/root/market-warehouse/…` in the container, which has never existed;
every lake root now falls back under `market_warehouse_lake_root`. And
`fx_symbol` looked only for `USD<CCY>` while the mini's lake publishes `EURUSD`
(1.16973, USD per EUR) and no `USDEUR`; `load_fx` now reads either orientation
and inverts `<CCY>USD`. `no_fx` 12 → 1, `converted` 0 → 11.

Direction verified against real filings rather than inferred from the bands
looking plausible — a 35% EUR error prints a perfectly plausible band:

```
ASML 2026-06-30   reported     9.33 B EUR  @ 0.85490 EUR/USD  ->    10.87 B USD
TSM  2026-06-30   reported  1270.38 B TWD  @ 31.82   TWD/USD  ->    40.45 B USD
```

TSM's figure is not `1270.38 / 31.82 = 39.92` because a flow takes the TTM
AVERAGE rate, not the closing one — the two-rate rule, working.

**NVO stays refused, correctly.** It reports DKK and the lake carries no DKK
series in either orientation. Upstream ask for livewire, not something to paper
over with an unconverted band.

## Reproduce

`STAGE_SPLITS=0` reads the split store exactly as production has it — the state
the job meets if it deploys between the 17:35 ingest and the 18:20 band run.
`STAGE_SPLITS=1` stages the silver-less names' splits inside the transaction to
simulate the post-deploy store. Both roll back and write nothing.

colima shares no arbitrary host paths, so the patched tree goes in with
`docker cp` into a *throwaway* container — never into the running worker, whose
writable layer would then survive a restart onto unmerged code.

```bash
tar czf /tmp/argonpatch.tgz \
  src/uw_scan/worker/jobs/fundamental_anchors.py \
  src/uw_scan/worker/jobs/fundamental_refresh.py \
  src/uw_scan/storage/corporate_actions.py \
  src/uw_scan/fundamentals/fx.py src/uw_scan/fundamentals/valuation.py \
  src/uw_scan/config.py \
  docs/research/2026-08-21-lake-price-basis-split-contamination/prod_validation.py
scp /tmp/argonpatch.tgz macmini:/tmp/argonpatch.tgz

ssh macmini 'D=/opt/homebrew/bin/docker
T=$($D create --network argon_default --add-host=host.docker.internal:host-gateway \
  -v /Volumes/DATA_LAKE/livewire/data-lake:/lake:ro \
  --env-file /opt/argon/.env \
  -e UW_SCAN_DB_HOST=host.docker.internal -e MARKET_WAREHOUSE_LAKE=/lake \
  -e LAKE_CREDIT_ETF_ROOT=/lake/bronze/asset_class=equity \
  -e LAKE_VOL_INDEX_ROOT=/lake/bronze/asset_class=volatility \
  -e STAGE_SPLITS=0 --entrypoint sh ghcr.io/moremeds/argon-app:latest \
  -c "cd /app && tar xzf /tmp/p.tgz && python docs/research/2026-08-21-lake-price-basis-split-contamination/prod_validation.py")
$D cp /tmp/argonpatch.tgz $T:/tmp/p.tgz; $D start -a $T; $D rm -f $T'
```

The split-contamination count before the fix:

```bash
ssh macmini "/opt/homebrew/bin/docker exec -i argon-worker-massive-0-1 python -" \
  < scripts/research/valuation_split_contamination_probe.py
```

Coverage of `corporate_actions` over the universe, and the three names that stay
unverifiable, are read straight from the mini:

```sql
-- zero-row share of the universe (313 of 450 on 2026-08-22)
WITH u AS (SELECT DISTINCT ticker FROM uw_scan.fundamental_universe)
SELECT count(*) FILTER (WHERE NOT EXISTS (
         SELECT 1 FROM uw_scan.corporate_actions c WHERE c.ticker = u.ticker)) AS zero_rows,
       count(*) AS universe
FROM u;
```
