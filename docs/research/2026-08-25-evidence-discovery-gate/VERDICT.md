# Six event classes live, eight killed — and the kills are the deliverable

**Measured 2026-08-25** on `option_wizard_local`. Artifact: `gate.json`.

Reproduce:

```bash
uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.worker.jobs.research_events_derive import (
    register_discovery_gate, derive_events, derive_risk_facts)
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c:
    print(register_discovery_gate(c))
    print(derive_events(c))
    print(derive_risk_facts(c, engine_version='fundamentals-v2:77aea364'))
"
```

## Live classes

| class | rows | source |
|---|---|---|
| `statement_published` | 45,196 | `fundamental_statement_obs.filing_published_at` |
| `sec_filing` | 37,510 | `sec_filing_index` |
| `geographic_disclosure` | 7,088 | `revenue_breakdown_obs` (geographical axis) |
| `segment_disclosure` | 3,203 | `revenue_breakdown_obs` (business-segment axis) |
| `sec_amendment` | 1,806 | `sec_filing_index` (`is_amendment`) |
| `input_violation` | 1,006 | `fundamental_obs_violations` |

## Killed classes

| class | rows | why |
|---|---|---|
| `restatement` | **1** | ONE multi-version identity in 87,177 observations. A class that fires once is an anecdote, not a class. Revive when real version history accrues. |
| `customer_concentration` | 0 | lives in SEC document **text**, which Argon does not fetch |
| `supplier_relationship` | 0 | same |
| `backlog` | 0 | same |
| `capex_guidance` | 0 | same |
| `debt_maturity` | 0 | same |
| `management_guidance` | 0 | same |
| `product_regulatory` | 0 | requires a licensed news source |

A killed class **refuses writes** — the repository raises rather than warning.
An event in a killed class is exactly the fabrication the gate exists to
prevent, and a class represented as supported-but-empty makes a timeline look
complete. Every company response therefore carries the killed list, so a reader
of a supply-chain-free timeline is told why it is supply-chain-free.

## Deterministic risk facts

Every risk is an observed value against a threshold, plus the computation a
breach invalidates. No prose — a risk expressed only as a sentence cannot be
checked, replayed, or shown to have improved.

| risk | breached | evaluated | threshold |
|---|---|---|---|
| `unevidenced_company_type` | **319** | 449 | classification came from evidence |
| `stale_result` | 73 | 400 | 45 days |
| `thin_pit_evidence` | 54 | 401 | 50% of observations dated |

The largest is `unevidenced_company_type` at 319 of 449: those names' valuation
method is the pooled-universe default rather than a routed one, and the risk fact
names exactly what that invalidates.

## Two clocks, enforced

`occurred_at` is when an event happened; `first_known_at` is when Argon could
know. A CHECK forbids the second preceding the first, and every historical read
predicates on `first_known_at`. NVDA's April 2026 quarter ended 2026-04-26 and
its 10-Q published 2026-05-20 — a replay standing at 2026-05-01 correctly sees
nothing.

## What this does NOT establish

- **No extraction precision is claimed**, because nothing is extracted from
  prose. Every live class is a projection of structured data Argon already
  ingested, so the failure mode is a wrong projection, not a wrong reading.
- **No catalyst is forward-looking.** These are events that HAVE happened.
  Scheduled future earnings exist in the UW calendar but are not events here.
- **`restatement` being dead is a statement about Argon's history, not about
  companies.** Version history began accruing on 2026-08-16; a store with eight
  days of capture cannot show restatements.
