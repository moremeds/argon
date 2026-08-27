# Chain analysis node — design

**Status:** implemented for one node (`Optical-Communication`); five datacenter
chains measured as buildable at zero incremental vendor cost and not yet seeded.

**Code:** `src/uw_scan/fundamentals/chain_nodes.py` (the catalogue),
`src/uw_scan/worker/jobs/research_report_assemble.py` (the assembler),
`src/uw_scan/worker/jobs/research_taxonomy_seed.py` (seeding + exposure
derivation).

**Tests:** `tests/integration/storage/test_research_reports.py`
(catalogue↔assembler binding, exposure grain),
`tests/integration/storage/test_chain_segment_alias.py` (alias specificity).

---

## 1. What a node is

One industry chain, analysed by a fixed set of components. `Optical-Communication`
(光模块) is the first. The intended siblings are the datacenter build-out chains —
power, cooling, colo, generation, construction — which argon already carries as
membership rows with no layer structure.

A node is **data, not code**. `assemble_chain_report` takes the chain as a
parameter and is already generic over it. Standing up a new node requires three
kinds of row and no new assembler logic.

## 2. The components

Declared in `chain_nodes.CHAIN_COMPONENTS`. Every component names its purpose,
what it reads, what it costs, the keys its payload carries, and the strongest
claim it may make.

| kind              | reads                                                              | UW calls | authority           |
| ----------------- | ------------------------------------------------------------------ | -------- | ------------------- |
| `scope`           | `research_taxonomy_versions`                                       | 0        | —                   |
| `unsupported`     | `research_event_classes`                                           | 0        | —                   |
| `chain_coverage`  | `chain_membership`, `company_exposure`                             | 0        | —                   |
| `chain_members`   | `chain_membership`, warm scores/dimensions                         | 0        | `research_priority` |
| `chain_aggregate` | warm scores/dimensions                                             | 0        | `research_priority` |
| `chain_exposure`  | `company_exposure`, `revenue_breakdown_obs`, `chain_segment_alias` | 0        | —                   |

The company and comparison shapes reuse `scope`, `unsupported` and
`chain_exposure` and add their own; `chain_nodes.SHAPE_ORDER` is the authority on
emission order for all three.

**The catalogue is bound to the assembler by test**, not by convention:
`test_the_catalogue_matches_what_the_assembler_actually_emits` asserts the
emitted kinds are a subsequence of the declared order, that every `required`
component appears, and that each block's `authority` equals the declared one. A
catalogue nothing checks is documentation that drifts, and the cost and authority
fields are read by other code.

### 2.1 Why every component costs zero vendor calls

All six read the warm store. The vendor spend sits upstream, in the jobs that
fill that store, and it is shared across every chain simultaneously:

- `fundamental_ingest_daily` — ~900 UW calls/month for the **whole universe**
- `fundamental_concentration_capture` — ~450 UW calls/run, monthly, the source
  of `revenue_breakdown_obs` and therefore of every magnitude

Measured 2026-08-26 on the argon universe:

| chain                 | members | in universe | with statements | with segments |
| --------------------- | ------- | ----------- | --------------- | ------------- |
| Optical-Communication | 16      | 16          | 16              | 15            |
| Generation/Nuclear    | 14      | 14          | 14              | 13            |
| Power/Electrical      | 9       | 9           | 9               | 9             |
| EPC/Construction      | 8       | 8           | 8               | 8             |
| Cooling/Thermal       | 7       | 7           | 7               | 7             |
| DC-REIT/Colo          | 6       | 6           | 4               | 5             |

Every member of every datacenter chain is already in the universe, and **42 of the
44 already carry statements** — DC-REIT/Colo is the one gap, at 4 of 6. **Adding
those five nodes costs no incremental vendor calls** — only taxonomy rows. `Cost.uw_calls`
is an int on every component so that a future component which does call a vendor
cannot be added without saying so, and
`test_every_declared_component_is_free_of_vendor_calls` fails if one is.

## 3. Standing up a new node

1. **`research_chains`** — one row per layer: `domain`, `chain`, `layer`,
   `layer_rank`, `description`. Ranks are **sparse** (10, 20, 30, 40, 70) so a
   layer discovered later slots between two existing ones without renumbering the
   chain. Optical deliberately leaves 50 and 60 empty.

   This is the step that was skipped for 38 of argon's 39 chains: they carry a
   single placeholder layer `L3` at rank 0, which is why their reports render a
   chain with no shape and their layer codes carry no meaning.

2. **`chain_membership`** — one row per `(chain, layer, ticker)`. A company in
   two layers is **two rows**, so every count over this table must dedupe by
   ticker. Retire a member with `valid_to`, never `DELETE`: the table is
   temporally versioned and reads filter `valid_to IS NULL`.

3. **`chain_segment_alias`** — optional, and only needed to turn a filer's
   disclosed segment into a magnitude. See §4.

## 4. Resolving a segment to a chain

An alias `pattern` is matched case-insensitively as a **substring** of the XBRL
member tag's local name, on a named axis.

**Longest pattern wins, because a longer pattern is a narrower claim.** An
equally specific tie across two different chains is **refused**, not guessed —
`counters["ambiguous"]` records it and nothing is written.

This replaced a first-match-wins loop over an unordered `SELECT`. The failure it
produced, on prod data:

- `datacenter` (AI-Cloud/NeoCloud) is a substring of
  `datacenterandcommunications` (Optical-Communication). Coherent's Datacom &
  Communications segment — **74.6% of revenue, the best-evidenced optical
  exposure argon holds** — was filed under the cloud chain.
- The same collision filed HPE's Data Center Networking segment under cloud, and
  because `company_exposure` upserts `ON CONFLICT DO NOTHING`, that 3.0% row then
  **blocked** HPE's genuine 72.2% Cloud/AI exposure from ever being written.
- Optical's only two remaining magnitudes were therefore an over-broad match on a
  non-member (APH, `communicationssolutions`, 61.5%) and the smallest segment of
  a near-pure-play (CIEN, `blueplanetautomation`, 1.5%).

After the fix the optical node carries four magnitudes and each is labelled
`is_member`. Two open data questions remain, deliberately visible rather than
silently corrected:

- **APH 61.5%** — `communicationssolutions` is Amphenol's entire communications
  segment (antennas, RF, mobile, datacom interconnect), not optical
  communication. The alias is over-broad. APH is also not a chain member.
- **CIEN 1.5%** — `blueplanetautomation` is Ciena's smallest segment. The same
  filing discloses `cien:NetworkingPlatformsSegmentMember` (81% of revenue) on
  the segment axis and `cien:OpticalNetworkingMember` (70%) on
  `srt:ProductOrServiceAxis`. Either is a better claim; neither is currently an
  alias.

Both are **rule** problems, not resolver problems, and changing a rule changes a
published number — so they are surfaced on the node's page and left for an
explicit decision.

## 5. The cross-section trap

`fundamental_scores.as_of` looks like a freshness timestamp and is not. It is a
**cross-section identifier**: `fundamental_scoring` buckets names by _knowledge
quarter_ and z-scores each bucket independently against its own population, then
stamps the bucket with `max(knowledge_date)`.

Consequence: a name is not "stale", it is **measured against a different ruler**.
Off-calendar filers are structurally in an older bucket than calendar filers, and
no backfill changes that. Measured on the optical node, 2026-08-26:

- bucket `2026-08-21` — 366 names — 10 optical members (calendar filers, June
  quarter reported)
- bucket `2026-06-25` — 411 names — 6 optical members (AVGO, CIEN, CRDO, MRVL,
  NTAP, ORCL: fiscal quarters that have not been reported yet)

**Presentation rule.** The node renders one ranked list when its members share a
single bucket, and two cohorts — reported / awaiting — when they do not, never a
merged ranking across buckets. The straddle is exactly the reporting season; when
the season closes the members collapse into one bucket and the single list
returns on its own. The rule reads off the data and needs no calendar.

`chain_aggregate` currently means the mean over whichever rows are newest per
ticker, which mixes rulers. That is a known limitation of the aggregate, not of
the members block.

## 6. Open items

1. **The chain shape emits no `risks` block.** `assemble_chain_report` never
   calls `risks_for()`; only the company shape does. So a `stale_result` breach
   is flagged when the operator asks about one company and silent when they ask
   about a chain containing it.
2. **`chain_aggregate` mixes cross-sections** (§5). Either restrict it to the
   dominant bucket and say so, or abstain on a straddle.
3. **APH and CIEN alias rules** (§4).
4. **38 chains have no layer set** (§3.1). The datacenter five are the first
   worth seeding, and cost nothing extra to seed.
