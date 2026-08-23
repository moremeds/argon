# A future knowledge date stamped a whole cross-section

Measured against production `option_wizard` on 2026-08-23. Read-only.

## Finding

`fundamental_scoring` keys each cross-section on a **knowledge quarter** and sets
`as_of` to the bucket's MAXIMUM knowledge date. When a filer's real filing date is
unknown, `_knowledge_date` estimates `period_end + FALLBACK_LAG_DAYS` (45d). For a
fresh quarter that estimate has not arrived, and one such name stamps every row in
its bucket with a future date.

## The A/B, against the real panel

Both arms run the **fixed** `_build_buckets`; the control disables the cutoff by
setting it to 2099-01-01, which reproduces the shipped behaviour. If the arms agreed,
the production panel would not express the defect and the run would prove nothing.

```
db = option_wizard  (read-only)
universe(ranked) = 450  panel tickers = 420

withheld  no-cutoff=0   cutoff=2026-08-23: 2

latest bucket = 2026Q3
  ARM A (no cutoff, = shipped): as_of=2026-09-14  names=363
  ARM B (cutoff today, = fix): as_of=2026-08-17  names=361
  names withheld from 2026Q3: ['AMAT', 'CSCO']
    AMAT: period=2026-07-31 knowledge=2026-09-14 filing_date_known=False
    CSCO: period=2026-07-31 knowledge=2026-09-14 filing_date_known=False

every unarrived row across ALL buckets: {'AMAT': 2026-09-14, 'CSCO': 2026-09-14}

persisted future-dated rows still in the table: max_as_of=2026-09-14 rows=371
```

`as_of` moves 2026-09-14 → **2026-08-17** (EXTR's real filing date, the latest that
had actually arrived) at a cost of two names out of 363.

## Damage, stated precisely

The 371 rows are **every 2026Q3 score the table holds** — the poisoned bucket is the
latest one, not a bucket sitting on top of fresher rows:

```
as_of      | rows
2026-09-14 |  371   <- 2026Q3, poisoned
2026-06-25 |  412
2026-06-22 |  253
2026-03-31 |  406
```

So the shadowing is **prospective**, not retrospective. `latest_for_ticker` orders
`as_of DESC`; every correct recompute for the rest of the quarter carries a lower
(because arrived) `as_of` than 2026-09-14, so it would land in the table and never
surface until the calendar reached September 14. A re-run under the old code also
writes nothing new — identical rows hit `ON CONFLICT DO NOTHING` — so the card is
pinned to the 2026-08-16 compute.

The quieter half: AMAT and CSCO contributed to the other 361 names' z-scores using
figures the market had not seen.

## Correction

An earlier draft of the PR body claimed rows at `as_of` 2026-08-20 already existed and
were being shadowed. That was wrong — those were `valuation_anchors` rows, which accrue
daily on the compute date. `fundamental_scores` buckets by knowledge quarter and has no
2026-08-20 row. The claim is removed, not softened.

## Reproduce

```bash
# on the mini; needs the FIXED fundamental_scoring.py, so copy it into a THROWAWAY
# container — never `docker cp` into a running one (its writable layer survives a
# restart onto unmerged code).
scp docs/research/2026-08-23-scoring-knowledge-cutoff/prod_ab_probe.py macmini:/tmp/
scp src/uw_scan/worker/jobs/fundamental_scoring.py macmini:/tmp/fundamental_scoring_fixed.py
ssh macmini 'D=/opt/homebrew/bin/docker
$D create --name argon-probe129 --env-file /opt/argon/.env \
  --add-host host.docker.internal:host-gateway \
  -v /Volumes/DATA_LAKE/livewire/data-lake:/lake:ro \
  ghcr.io/moremeds/argon-app:latest python /probe129.py
$D cp /tmp/probe129.py argon-probe129:/probe129.py
$D cp /tmp/fundamental_scoring_fixed.py argon-probe129:/app/src/uw_scan/worker/jobs/fundamental_scoring.py
$D start -a argon-probe129; $D rm -f argon-probe129'
```

`TODAY` is pinned in the probe rather than read from the clock, so the run reproduces.
