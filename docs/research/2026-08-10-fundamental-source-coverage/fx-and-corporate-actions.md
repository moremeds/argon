# FX and corporate actions from the mini lake

*Probed 2026-08-11 · companion to `README.md`, which is script-generated and overwritten on every
run — this file is hand-maintained. Spec `docs/superpowers/specs/2026-08-10-fundamental-pm-agent-design.md` §3.2, §4.4.*

Probed to answer whether the deferred currency contract has a data source. It does, locally, at zero
API cost.

Reproduce (needs the `macmini` ssh alias):

```bash
ssh macmini 'ls ~/market-warehouse/data-lake/bronze/asset_class=fx'
scp macmini:'~/market-warehouse/data-lake/bronze/asset_class=fx/symbol=USDTWD/1d.parquet' .
uv run python -c "import pyarrow.parquet as pq; t=pq.read_table('1d.parquet'); print(t.schema, t.num_rows)"
```

| Series | Needed by | Rows | Span | Schema |
|---|---|---:|---|---|
| `symbol=USDTWD/1d.parquet` | TSM (reports TWD) | 5,395 | 2004-03-24 → 2026-08-10 | `trade_date, symbol_id, open, high, low, close, adj_close, volume` |
| `symbol=EURUSD/1d.parquet` | ASML (reports EUR) | 5,889 | 2003-12-01 → 2026-08-10 | identical |

21 FX symbols are present in total. The schema is exactly what
`sources/lake.read_vol_index_parquet` already consumes, so reading it needs only an `"fx"` entry in
`lake_resolver._ASSET_CLASS_TO_LOCAL_ATTR` and `_ASSET_CLASS_CANARY` plus a settings attribute —
a registration, not a research task.

## Three findings that bound what this unblocks

1. **The lake holds no fundamentals.** `raw/massive` contains only
   `us_stocks_sip/{day,minute}_aggs_v1`. TSM stays `annual_only` and ASML `history_only`. FX was
   never the blocker for those two names — the missing quarterly statements are. What the lake
   removes is the *translation* unknown, not the *statement* gap.
2. **ADR dividends are already USD.**
   `bronze/asset_class=corporate_action/symbol={TSM,ASML}/events.parquet` carries `currency = USD`
   on every `cash_dividend` row, because ADR dividends are paid in USD at source. The dividend leg
   needs no translation.
3. **The ADR ratio is still unsourced.** Not in the FX series, not in the corporate-action events,
   and not derivable from the splits — TSM's split rows are fractional stock dividends
   (`1 → 1.014995` in 2006, `1 → 1.003` in 2007, `1 → 1.003025` in 2008), not an ADR restatement.
   It must be pinned per ticker before any foreign-issuer per-share anchor is computed.

## Observation-model precedent

The corporate-action parquet is a shipped precedent for this project's tier-1 storage design. Its
columns are `action_id`, `provider`, `provider_event_id`, `event_revision`, `supersedes_action_id`,
`symbol`, `action_type`, `ex_date`, …, `status`, `fetched_at`, `payload_hash`.

Mapping to the spec's `*_obs` tables: `payload_hash` ≡ `content_hash`, `provider_event_id` ≡
`provider_record_id`, `fetched_at` ≡ `last_seen_at`. Prefer the shipped names where they fit.

The spec goes further only for **multi-fact extraction runs** (§6): one event per row makes
`supersedes_action_id` + `status` sufficient here, but an extraction run emits a *set* of facts, and
a run re-emitting `{A}` after `{A, B}` must retract `B` without touching `A` — which a scalar
supersession pointer cannot express. Hence `filing_extraction_run_facts`.
