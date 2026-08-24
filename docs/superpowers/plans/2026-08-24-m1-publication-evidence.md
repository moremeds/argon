# M1-A: SEC Publication Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`
> (recommended) or `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking. Use
> `superpowers:test-driven-development` for every behaviour change and
> `superpowers:verification-before-completion` before any completion claim.

**Goal:** move `true_pit` availability coverage off zero by joining Argon's statement
observations to SEC periodic filings, so that leak-free historical replay becomes
possible at all.

**Architecture:** a new read-only SEC source (`data.sec.gov` submissions API, free, no
provider budget) populates an immutable filing index. A separate, deliberately strict
rule issues `true_pit` claims into the existing `fundamental_obs_availability` table —
only where the mapping from content version to publication artifact is unambiguous.
Everything else stays `capture_bounded`. No existing claim is rewritten; no scoring,
card, or API behaviour changes.

**Tech Stack:** Python 3.13 via `uv`, httpx, psycopg 3, PostgreSQL, pytest +
pytest-postgresql.

**Spec:** measurements and rationale in
`docs/research/2026-08-24-fundamental-observation-availability/README.md`;
program context in
`docs/superpowers/plans/2026-08-24-fundamental-pm-research-system-program.md`
(milestone M1). Predecessor: `docs/plans/2026-08-24-fundamental-observation-asof.md`
(Pre-Job 0, complete).

---

## Why this, and why only this

Pre-Job 0 shipped the availability contract and ran against production on
2026-08-24. What it measured re-scoped M1:

| Measured on prod                                | Value                                    |
| ----------------------------------------------- | ---------------------------------------- |
| Observations                                    | 89,758 / 420 tickers / periods 1998→2026 |
| **Capture window**                              | **2026-08-16 → 2026-08-23 (8 days)**     |
| `true_pit` claims                               | **0**                                    |
| `capture_bounded` claims                        | 89,758                                   |
| Multi-version identities                        | 200 (405 rows, 42 tickers)               |
| `obs_id` pick vs availability pick              | **identical on all 200**                 |
| Score rows whose `as_of` predates first capture | **32,557 of 33,283 (97.8%)**             |

Two consequences drive this plan:

1. **The as-of reader currently buys nothing in selection.** `capture_bounded`
   availability _is_ `first_observed_at`, and `obs_id` is a BIGSERIAL assigned at the
   same insert — monotonic by construction, so they can never disagree. Divergence
   only becomes possible once availability is sourced independently of capture order,
   i.e. once `true_pit` exists.
2. **Replayable history begins 2026-08-16.** Every `TRUE_PIT_ONLY` replay returns
   empty, and every `CAPTURE_BOUNDED` replay before that date returns empty. M3
   (corrected research) cannot start.

So the binding constraint is publication evidence, not canonical multi-source
reconciliation. **Explicitly deferred to later M1 slices**, each needing its own child
plan written after this one's evidence: multi-source canonical reconciliation (M1-B),
the typed provenance graph replacing `source_obs_ids BIGINT[]` (M1-C), and governed
company identity/`company_type` coverage (M1-D). None of them moves `true_pit`.

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`.
- **SEC requires a descriptive `User-Agent`** carrying a contact address, or it returns 403. Rate limit is 10 requests/second; stay under it.
- **The SEC client MUST bypass the system proxy.** Verified 2026-08-24: with macOS
  proxy env set, `https://www.sec.gov` fails with `SSL_ERROR_SYSCALL`; with the proxy
  bypassed it returns 200. Same class of failure as `MassiveWsClient`, which passes
  `proxy=None` for the same reason.
- **Zero UW / IB / massive budget.** SEC is free. This job must never appear in the UW
  budget governor.
- **No claim is ever updated.** `fundamental_obs_availability` is append-only; a new
  rule version means a new `claim_key`, never a rewrite.
- **`filing_published_at` never promotes anything to `true_pit`** — it describes the
  period's _original_ filing, not the content version Argon holds.
- **Never commit without an explicit user request.** Draft first, wait.
- **Migrations are idempotent** (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`).
- **A new temporal table needs a `DatasetRegistryEntry` AND a regenerated
  `docs/runbooks/data-gap-dataset-policy.md`** in this same PR —
  `test_data_gap_full_coverage.py` scans the live schema and
  `test_committed_policy_doc_is_in_sync_with_registry` byte-compares the doc. The doc
  is generated; hand-editing it fails CI.
- **CHANGELOG rides this PR** under `[Unreleased]`.

## The rule this plan implements

A content version earns `true_pit` **only** when all four hold:

1. its identity `(source, ticker, period_end, period_type, statement)` has **exactly one**
   content version — with two or more, Argon cannot tell which one it holds;
2. **exactly one** non-amendment periodic filing (`10-Q`, `10-K`, `20-F`, `40-F`)
   matches `period_end` within ±7 days;
3. that period has **no amendment** (`…/A`) filing in the index — an amendment means the
   content may be the restated version wearing the original's date;
4. the matched filing's `filing_date` is not in the future.

Otherwise: **no claim is written.** The observation keeps its `capture_bounded` claim
and the panel keeps working exactly as it does today.

Condition 3 is the one that makes this honest. UW serves _current_ data: if a company
restated, our single stored version may be the restated content. Claiming it was
available at the original filing date would be `filing_published_at`'s trap wearing SEC
clothes.

## Measured expectations (verified 2026-08-24, NVDA)

|                                             |                         |
| ------------------------------------------- | ----------------------- |
| SEC periodic filings for NVDA (CIK 1045810) | 111, spanning 2006→2026 |
| NVDA periods with an amendment              | 4                       |
| Argon NVDA quarterly periods                | 82                      |
| Join at tolerance **0 days**                | 11 (13.4%)              |
| Join at tolerance **7 days**                | 77 (**93.9%**), 5 miss  |

The tolerance is not optional and not a guess. SEC's `reportDate` for NVDA's April 2026
quarter is `2026-04-26`; Argon's `period_end` is `2026-04-30`. This is the _same_
52/53-week fiscal-calendar mismatch already documented between UW's statement endpoints
and `fundamental-breakdown` (0 of 885 matched at tolerance 0). Reuse the existing
tolerance and its exact-first rule; do not invent a second one.

Treat 93.9% as one ticker's figure, not the universe's. Task 6 measures the real one.

## File Structure

| File                                                          | Responsibility                                                                                                                      |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `src/uw_scan/sources/sec_submissions.py`                      | HTTP + parse. Fetch `company_tickers.json` and per-CIK submissions (including paginated archives); return typed rows. Never raises. |
| `src/uw_scan/fundamentals/publication_evidence.py`            | Pure rule: given one identity's versions and the period's filings, return a claim or a refusal reason. No SQL, no HTTP.             |
| `src/uw_scan/storage/migrations/132_sec_filing_index.sql`     | `sec_filing_index` + `sec_cik_map`. Immutable, content-keyed.                                                                       |
| `src/uw_scan/storage/sec_filing_index.py`                     | Standalone repository for both tables.                                                                                              |
| `src/uw_scan/worker/jobs/sec_filing_index_refresh.py`         | Fetch → persist the index. Zero provider budget.                                                                                    |
| `src/uw_scan/worker/jobs/fundamental_publication_evidence.py` | Apply the rule, write `true_pit` claims, return counters by refusal reason.                                                         |
| `scripts/backfill/sec_publication_evidence.py`                | Operator entry point for both jobs plus `--measure`.                                                                                |
| `src/uw_scan/reports/data_gap_healer.py`                      | Two `DatasetRegistryEntry` rows.                                                                                                    |
| `docs/runbooks/fundamental-observation-availability.md`       | Extend with the SEC path.                                                                                                           |

---

## Task 0: Re-prove the baseline

**Files:** none.

- [ ] **Step 1: Confirm branch and worktree**

```bash
git branch --show-current
git status --short
```

Expected: `feat/fundamental-pm-research-system` (or a fresh branch off it), and only
intended files dirty. Stop on any unexpected modification.

- [ ] **Step 2: Confirm Pre-Job 0 is live on production**

```bash
ssh macmini '/opt/homebrew/opt/postgresql@17/bin/psql -h 127.0.0.1 -U argon_app -d option_wizard -tAc "
SELECT evidence_class, count(*) FROM uw_scan.fundamental_obs_availability GROUP BY 1 ORDER BY 1"'
```

Expected: `capture_bounded|89758` and `current_vintage|89758`, no `true_pit`. If
`true_pit` rows already exist, STOP — someone ran a rule this plan does not know about.

- [ ] **Step 3: Run the fundamentals baseline**

Use a private test database so a concurrent session in another worktree cannot deadlock
you (they share `option_wizard_test`):

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/unit/fundamentals \
  tests/integration/storage/test_fundamental_observation_availability.py \
  tests/integration/storage/test_fundamental_observation_panels.py -q
```

Expected: all pass. Record the exact count.

---

## Task 1: SEC submissions source

**Files:**

- Create: `src/uw_scan/sources/sec_submissions.py`
- Create: `tests/unit/sources/test_sec_submissions.py`

**Interfaces:**

- Consumes: nothing from earlier tasks.
- Produces:
  - `SEC_FORMS: frozenset[str]` — `{"10-Q", "10-K", "20-F", "40-F"}`
  - `@dataclass(frozen=True) SecFiling(accession: str, form: str, report_date: date, filing_date: date, is_amendment: bool)`
  - `parse_submissions(payload: dict) -> list[SecFiling]`
  - `fetch_cik_map(client) -> dict[str, str]` — ticker → 10-digit zero-padded CIK
  - `fetch_filings(client, cik: str) -> list[SecFiling]` — follows `filings.files[]` archives
  - `sec_client(user_agent: str) -> httpx.Client`

- [ ] **Step 1: Write the failing parser tests**

Real NVDA rows, frozen from `https://data.sec.gov/submissions/CIK0001045810.json`
fetched 2026-08-24.

```python
"""Parsing SEC submissions into filing evidence.

Frozen from NVDA's real submissions payload, 2026-08-24. The amendment rows are
the load-bearing ones: a period carrying a `/A` is a period where Argon cannot
tell which content version it holds, and the whole rule turns on detecting them.
"""

from __future__ import annotations

from datetime import date

from uw_scan.sources.sec_submissions import SecFiling, parse_submissions

PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": [
                "0001045810-26-000052",
                "0001045810-26-000021",
                "0001045810-25-000230",
                "0000891618-04-000000",
                "0001045810-24-000316",
            ],
            "form": ["10-Q", "10-K", "10-Q", "10-K/A", "4"],
            "reportDate": [
                "2026-04-26",
                "2026-01-25",
                "2025-10-26",
                "2004-01-25",
                "2024-10-27",
            ],
            "filingDate": [
                "2026-05-20",
                "2026-02-25",
                "2025-11-19",
                "2004-05-20",
                "2024-11-20",
            ],
        }
    }
}


def test_only_periodic_forms_survive():
    out = parse_submissions(PAYLOAD)
    assert {f.form for f in out} == {"10-Q", "10-K", "10-K/A"}
    assert all(f.form != "4" for f in out), "ownership forms are not periodic reports"


def test_an_amendment_is_flagged():
    amended = [f for f in parse_submissions(PAYLOAD) if f.is_amendment]
    assert len(amended) == 1
    assert amended[0].form == "10-K/A"
    assert amended[0].report_date == date(2004, 1, 25)


def test_dates_are_parsed_not_strings():
    f = next(f for f in parse_submissions(PAYLOAD) if f.accession == "0001045810-26-000052")
    assert f.report_date == date(2026, 4, 26)
    assert f.filing_date == date(2026, 5, 20)


def test_a_row_missing_its_report_date_is_dropped_not_guessed():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001045810-26-000052"],
                "form": ["10-Q"],
                "reportDate": [""],
                "filingDate": ["2026-05-20"],
            }
        }
    }
    assert parse_submissions(payload) == []


def test_an_empty_payload_is_empty_not_an_error():
    assert parse_submissions({}) == []
    assert parse_submissions({"filings": {}}) == []


def test_rows_are_hashable_and_deduplicate():
    out = parse_submissions(PAYLOAD)
    assert len(set(out)) == len(out)
    assert isinstance(out[0], SecFiling)
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/unit/sources/test_sec_submissions.py -q
```

Expected: `ModuleNotFoundError: No module named 'uw_scan.sources.sec_submissions'`.

- [ ] **Step 3: Implement the source**

```python
"""SEC EDGAR submissions — periodic filings as publication evidence.

Free, public, and NOT on any provider budget: this source exists precisely
because every paid source Argon holds answers "what is the current data", never
"when did THIS version become public".

TWO THINGS THAT WILL BITE
-------------------------
SEC returns 403 without a descriptive User-Agent carrying a contact address; the
limit is 10 requests/second. And the client MUST bypass the system proxy —
verified 2026-08-24, `https://www.sec.gov` fails with SSL_ERROR_SYSCALL through
the macOS proxy pane and returns 200 without it, the same failure class that made
`MassiveWsClient` pass `proxy=None`.

`filings.recent` holds only the newest window (1,009 rows for NVDA); everything
older sits in `filings.files[].name` archives that must be fetched separately, or
a 29-year panel silently becomes a 3-year one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime

import httpx

log = logging.getLogger(__name__)

SEC_BASE = "https://data.sec.gov"
SEC_WWW = "https://www.sec.gov"

#: Periodic reports that carry a fiscal period. Ownership (`4`), current reports
#: (`8-K`) and holdings (`13F-HR`) describe no period and are dropped.
SEC_FORMS = frozenset({"10-Q", "10-K", "20-F", "40-F"})


@dataclass(frozen=True)
class SecFiling:
    accession: str
    form: str
    report_date: date
    filing_date: date
    is_amendment: bool


def _parse_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        _ = repr(exc)  # CI Guardrail 2: unparseable date -> drop, never raise
        return None


def parse_submissions(payload: dict) -> list[SecFiling]:
    """Periodic filings from one submissions payload (or one archive page)."""
    block = payload.get("filings", {}).get("recent") if "filings" in payload else payload
    if not block:
        return []
    forms = block.get("form") or []
    out: list[SecFiling] = []
    for i, form in enumerate(forms):
        base = form[:-2] if form.endswith("/A") else form
        if base not in SEC_FORMS:
            continue
        report = _parse_date((block.get("reportDate") or [None] * len(forms))[i])
        filed = _parse_date((block.get("filingDate") or [None] * len(forms))[i])
        if report is None or filed is None:
            continue
        out.append(
            SecFiling(
                accession=(block.get("accessionNumber") or [""] * len(forms))[i],
                form=form,
                report_date=report,
                filing_date=filed,
                is_amendment=form.endswith("/A"),
            )
        )
    return out


def sec_client(user_agent: str, timeout: float = 30.0) -> httpx.Client:
    """A client that identifies itself and ignores the system proxy."""
    return httpx.Client(
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        timeout=timeout,
        trust_env=False,
    )


def fetch_cik_map(client: httpx.Client) -> dict[str, str]:
    """ticker -> zero-padded 10-digit CIK. Empty dict on any failure."""
    try:
        resp = client.get(f"{SEC_WWW}/files/company_tickers.json")
        if resp.status_code != 200:
            log.warning("sec: company_tickers HTTP %s", resp.status_code)
            return {}
        return {
            row["ticker"].upper(): f"{int(row['cik_str']):010d}"
            for row in resp.json().values()
            if row.get("ticker")
        }
    except Exception:
        log.exception("sec: company_tickers failed")
        return {}


def fetch_filings(client: httpx.Client, cik: str) -> list[SecFiling]:
    """Every periodic filing for one CIK, recent window plus archives."""
    try:
        resp = client.get(f"{SEC_BASE}/submissions/CIK{cik}.json")
        if resp.status_code != 200:
            log.warning("sec: submissions HTTP %s for CIK %s", resp.status_code, cik)
            return []
        payload = resp.json()
    except Exception:
        log.exception("sec: submissions failed for CIK %s", cik)
        return []

    out = list(parse_submissions(payload))
    for archive in payload.get("filings", {}).get("files") or []:
        name = archive.get("name")
        if not name:
            continue
        try:
            more = client.get(f"{SEC_BASE}/submissions/{name}")
            if more.status_code == 200:
                out.extend(parse_submissions(more.json()))
        except Exception:
            log.exception("sec: archive %s failed for CIK %s", name, cik)
    return sorted(set(out), key=lambda f: (f.report_date, f.accession))
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/sources/test_sec_submissions.py -q
uv run ruff check src/uw_scan/sources/sec_submissions.py tests/unit/sources/test_sec_submissions.py
```

Expected: PASS, clean.

- [ ] **Step 5: Verify against the live API once, by hand**

```bash
uv run python -c "
from uw_scan.sources.sec_submissions import sec_client, fetch_cik_map, fetch_filings
c = sec_client('argon-research lcxxcllcx@gmail.com')
m = fetch_cik_map(c)
print('cik entries:', len(m), 'NVDA:', m.get('NVDA'))
f = fetch_filings(c, m['NVDA'])
print('NVDA periodic filings:', len(f), 'amendments:', sum(x.is_amendment for x in f))
"
```

Expected (verified 2026-08-24): ~10,403 CIK entries, `NVDA: 0001045810`, ~111 filings,
4 amendments. A materially different count means SEC changed its payload — investigate
before continuing.

- [ ] **Step 6: Commit** _(only with explicit user authorization)_

```bash
git add src/uw_scan/sources/sec_submissions.py tests/unit/sources/test_sec_submissions.py
git commit -m "feat(fundamentals): read SEC periodic filings as publication evidence"
```

---

## Task 2: The pure matching rule

**Files:**

- Create: `src/uw_scan/fundamentals/publication_evidence.py`
- Create: `tests/unit/fundamentals/test_publication_evidence.py`

**Interfaces:**

- Consumes: `SecFiling` from Task 1.
- Produces:
  - `PUBLICATION_TOLERANCE_DAYS: int` (= 7)
  - `CLAIM_KEY_SEC_PUBLICATION: str` (= `"sec:publication:v1"`)
  - `SOURCE_SEC_EDGAR: str` (= `"sec_edgar"`)
  - `@dataclass(frozen=True) PublicationMatch(accession: str, filing_date: date)`
  - `match_publication(period_end, filings, *, version_count) -> tuple[PublicationMatch | None, str]`
    returning `(match, reason)` where `reason` is `"matched"` or a refusal slug.

- [ ] **Step 1: Write the failing rule tests**

```python
"""When SEC evidence may promote a stored version to true_pit, and when it may not.

Every refusal below is a way the join could look successful while being wrong.
The amendment case is the important one: UW serves CURRENT data, so for a period
that was later amended, the single version Argon holds may be the RESTATED
content. Dating it at the original filing is exactly the look-ahead the
availability contract exists to prevent, wearing SEC's authority instead of
`filing_published_at`'s.
"""

from __future__ import annotations

from datetime import date

from uw_scan.fundamentals.publication_evidence import match_publication
from uw_scan.sources.sec_submissions import SecFiling

ORIGINAL = SecFiling(
    accession="0001045810-26-000052",
    form="10-Q",
    report_date=date(2026, 4, 26),
    filing_date=date(2026, 5, 20),
    is_amendment=False,
)
AMENDMENT = SecFiling(
    accession="0001045810-26-000099",
    form="10-Q/A",
    report_date=date(2026, 4, 26),
    filing_date=date(2026, 7, 1),
    is_amendment=True,
)
NEIGHBOUR = SecFiling(
    accession="0001045810-26-000021",
    form="10-K",
    report_date=date(2026, 1, 25),
    filing_date=date(2026, 2, 25),
    is_amendment=False,
)


def test_a_clean_single_version_period_matches():
    match, reason = match_publication(date(2026, 4, 30), [ORIGINAL], version_count=1)
    assert reason == "matched"
    assert match.accession == ORIGINAL.accession
    assert match.filing_date == date(2026, 5, 20)


def test_the_four_day_calendar_gap_is_tolerated():
    # SEC says 2026-04-26; UW says 2026-04-30. Same quarter, different spelling.
    match, _ = match_publication(date(2026, 4, 30), [ORIGINAL], version_count=1)
    assert match is not None


def test_an_exact_match_beats_a_nearer_looking_neighbour():
    exact = SecFiling("acc-exact", "10-Q", date(2026, 4, 30), date(2026, 5, 21), False)
    match, _ = match_publication(date(2026, 4, 30), [exact, ORIGINAL], version_count=1)
    assert match.accession == "acc-exact"


def test_a_multi_version_identity_is_refused():
    match, reason = match_publication(date(2026, 4, 30), [ORIGINAL], version_count=2)
    assert match is None
    assert reason == "multi_version"


def test_an_amended_period_is_refused_even_with_a_clean_original():
    match, reason = match_publication(
        date(2026, 4, 30), [ORIGINAL, AMENDMENT], version_count=1
    )
    assert match is None
    assert reason == "amended"


def test_two_non_amendment_filings_in_the_window_are_refused():
    twin = SecFiling("acc-twin", "10-K", date(2026, 4, 28), date(2026, 5, 22), False)
    match, reason = match_publication(
        date(2026, 4, 30), [ORIGINAL, twin], version_count=1
    )
    assert match is None
    assert reason == "ambiguous"


def test_a_period_beyond_the_tolerance_does_not_match():
    match, reason = match_publication(date(2026, 4, 30), [NEIGHBOUR], version_count=1)
    assert match is None
    assert reason == "no_filing"


def test_no_filings_at_all_is_refused():
    match, reason = match_publication(date(2026, 4, 30), [], version_count=1)
    assert match is None
    assert reason == "no_filing"


def test_a_filing_date_before_its_own_period_end_is_refused():
    impossible = SecFiling(
        "acc-bad", "10-Q", date(2026, 4, 26), date(2026, 4, 1), False
    )
    match, reason = match_publication(date(2026, 4, 30), [impossible], version_count=1)
    assert match is None
    assert reason == "filed_before_period"
```

- [ ] **Step 2: Run and confirm failure**

```bash
uv run pytest tests/unit/fundamentals/test_publication_evidence.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the rule**

```python
"""Does SEC evidence justify calling a stored version true_pit? Usually not.

Pure compute. Four conditions, all of which must hold; every failure returns a
NAMED reason so the job can report a refusal distribution rather than a bare
success count. A rule that only reports what it matched cannot be audited.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from uw_scan.sources.sec_submissions import SecFiling

#: Read off the same recovery curve as the UW two-endpoint mismatch: SEC reports
#: the true fiscal period end, the statement endpoints normalise to a calendar
#: month end. NVDA's April 2026 quarter is 2026-04-26 at SEC and 2026-04-30 in
#: Argon. Measured 2026-08-24: NVDA joins 11/82 periods at tolerance 0 and 77/82
#: at tolerance 7. Quarters sit ~91 days apart, so the window cannot reach a
#: neighbour.
PUBLICATION_TOLERANCE_DAYS = 7

CLAIM_KEY_SEC_PUBLICATION = "sec:publication:v1"
SOURCE_SEC_EDGAR = "sec_edgar"


@dataclass(frozen=True)
class PublicationMatch:
    accession: str
    filing_date: date


def match_publication(
    period_end: date,
    filings: Sequence[SecFiling],
    *,
    version_count: int,
) -> tuple[PublicationMatch | None, str]:
    """`(match, reason)`. A match means true_pit is defensible; anything else does not.

    `version_count` is how many content versions Argon holds for this identity.
    With more than one there is no way to tell WHICH one is in hand, so the rule
    refuses before it even looks at SEC.
    """
    if version_count != 1:
        return (None, "multi_version")

    window = [
        f
        for f in filings
        if abs((f.report_date - period_end).days) <= PUBLICATION_TOLERANCE_DAYS
    ]
    if not window:
        return (None, "no_filing")

    # An amendment anywhere in the window means the content may be the restated
    # version. UW serves current data and does not say which vintage it gave us.
    if any(f.is_amendment for f in window):
        return (None, "amended")

    originals = [f for f in window if not f.is_amendment]
    exact = [f for f in originals if f.report_date == period_end]
    candidates = exact or originals
    if len(candidates) != 1:
        return (None, "ambiguous")

    chosen = candidates[0]
    if chosen.filing_date < chosen.report_date:
        return (None, "filed_before_period")
    return (PublicationMatch(chosen.accession, chosen.filing_date), "matched")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/unit/fundamentals/test_publication_evidence.py -q
uv run ruff check src/uw_scan/fundamentals/publication_evidence.py \
  tests/unit/fundamentals/test_publication_evidence.py
```

Expected: PASS, clean.

- [ ] **Step 5: Commit** _(only with explicit user authorization)_

```bash
git add src/uw_scan/fundamentals/publication_evidence.py tests/unit/fundamentals/test_publication_evidence.py
git commit -m "feat(fundamentals): rule for when SEC evidence justifies true_pit"
```

---

## Task 3: Filing-index schema and repository

**Files:**

- Create: `src/uw_scan/storage/migrations/132_sec_filing_index.sql`
- Create: `src/uw_scan/storage/sec_filing_index.py`
- Create: `tests/integration/storage/test_sec_filing_index.py`

**Interfaces:**

- Consumes: `SecFiling` from Task 1.
- Produces:
  - `SecFilingIndexRepository(conn, schema="uw_scan")` with
    `upsert_cik_map(mapping: dict[str, str]) -> int`,
    `cik_for(tickers: Sequence[str]) -> dict[str, str]`,
    `record_filings(cik: str, ticker: str, filings: Sequence[SecFiling]) -> int`,
    `filings_for(ticker: str) -> list[SecFiling]`,
    `index_counts() -> dict[str, int]`

- [ ] **Step 1: Confirm 132 is free**

```bash
ls src/uw_scan/storage/migrations | tail -5
```

Expected: highest is `131_fundamental_scores_evidence_policy.sql`. If not, take the next
free number and update this plan before continuing.

- [ ] **Step 2: Write the failing schema/repository tests**

```python
"""The SEC filing index: immutable, content-keyed, re-runnable.

`UNIQUE (accession)` is the whole idempotency story — an accession number is
SEC's own immutable identifier for one filing, so a re-fetch collides and writes
nothing rather than growing the table on every run.
"""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.sources.sec_submissions import SecFiling
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository

NVDA_Q = SecFiling("0001045810-26-000052", "10-Q", date(2026, 4, 26), date(2026, 5, 20), False)
NVDA_K = SecFiling("0001045810-26-000021", "10-K", date(2026, 1, 25), date(2026, 2, 25), False)
NVDA_A = SecFiling("0001045810-26-000099", "10-Q/A", date(2026, 4, 26), date(2026, 7, 1), True)


def _repo(seeded) -> SecFilingIndexRepository:
    return SecFilingIndexRepository(seeded.conn, schema=seeded._schema)


def test_filings_round_trip(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    assert repo.record_filings("0001045810", "NVDA", [NVDA_Q, NVDA_K]) == 2
    out = repo.filings_for("NVDA")
    assert {f.accession for f in out} == {NVDA_Q.accession, NVDA_K.accession}
    assert all(isinstance(f, SecFiling) for f in out)


def test_a_refetch_writes_nothing(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.record_filings("0001045810", "NVDA", [NVDA_Q])
    assert repo.record_filings("0001045810", "NVDA", [NVDA_Q]) == 0
    assert len(repo.filings_for("NVDA")) == 1


def test_the_amendment_flag_survives_the_round_trip(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.record_filings("0001045810", "NVDA", [NVDA_Q, NVDA_A])
    amended = [f for f in repo.filings_for("NVDA") if f.is_amendment]
    assert len(amended) == 1 and amended[0].form == "10-Q/A"


def test_cik_map_upserts_and_reads_back(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_cik_map({"NVDA": "0001045810", "AAPL": "0000320193"})
    assert repo.cik_for(["NVDA", "AAPL", "NOPE"]) == {
        "NVDA": "0001045810",
        "AAPL": "0000320193",
    }


def test_cik_map_is_idempotent(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_cik_map({"NVDA": "0001045810"})
    repo.upsert_cik_map({"NVDA": "0001045810"})
    assert repo.cik_for(["NVDA"]) == {"NVDA": "0001045810"}


def test_empty_inputs_are_noops(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    assert repo.record_filings("0001045810", "NVDA", []) == 0
    assert repo.upsert_cik_map({}) == 0
    assert repo.filings_for("NVDA") == []


def test_index_counts_report_what_landed(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_cik_map({"NVDA": "0001045810"})
    repo.record_filings("0001045810", "NVDA", [NVDA_Q, NVDA_K, NVDA_A])
    counts = repo.index_counts()
    assert counts["filings"] == 3
    assert counts["amendments"] == 1
    assert counts["tickers"] == 1
```

- [ ] **Step 3: Run and confirm failure**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/storage/test_sec_filing_index.py -q
```

Expected: `ModuleNotFoundError: No module named 'uw_scan.storage.sec_filing_index'`.

- [ ] **Step 4: Write the migration**

```sql
-- 132_sec_filing_index.sql — SEC periodic filings as publication evidence, and
-- the ticker->CIK map needed to fetch them. Additive and idempotent.
--
-- WHY THIS TABLE EXISTS
-- ---------------------
-- Every paid source Argon holds answers "what is the current data". None answers
-- "when did THIS version become public". Measured 2026-08-24, that gap left
-- `true_pit` at 0 of 89,758 observations and made every leak-free replay empty.
--
-- WHY accession IS THE KEY
-- ------------------------
-- An accession number is SEC's own immutable identifier for one filing. Keying on
-- it makes a re-fetch a no-op rather than a duplicate, with no content hash to
-- compute and no fetch timestamp to accidentally key on.
--
-- WHY THE AMENDMENT FLAG IS STORED RATHER THAN DERIVED AT READ TIME
-- -----------------------------------------------------------------
-- It is the single most consequential field: a period carrying an amendment is a
-- period where Argon cannot tell which content version it holds, so the rule
-- REFUSES to issue true_pit there. Deriving it from a string suffix at every read
-- would put that decision in three places.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.sec_cik_map (
    ticker      TEXT PRIMARY KEY,
    cik         TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.sec_cik_map IS
    'ticker -> zero-padded 10-digit CIK, from SEC company_tickers.json. A cache, '
    'not a series: refreshing it costs one request for the whole universe.';

CREATE TABLE IF NOT EXISTS uw_scan.sec_filing_index (
    accession     TEXT PRIMARY KEY,
    cik           TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    form          TEXT NOT NULL,
    -- The fiscal period the filing REPORTS ON. SEC gives the filer's true period
    -- end; Argon's statement rows carry a calendar month end. For a 52/53-week
    -- filer the two never coincide, which is why the match is tolerant.
    report_date   DATE NOT NULL,
    -- When the filing became public. This is the true_pit instant.
    filing_date   DATE NOT NULL,
    is_amendment  BOOLEAN NOT NULL,
    fetched_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE uw_scan.sec_filing_index IS
    'SEC periodic filings (10-Q/10-K/20-F/40-F and their amendments). Immutable, '
    'keyed on SEC accession so a re-fetch is a no-op.';

COMMENT ON COLUMN uw_scan.sec_filing_index.is_amendment IS
    'TRUE for a /A form. A period with one is a period where Argon cannot tell '
    'which content version it holds, so no true_pit claim is issued there.';

-- The rule reads "every filing for this ticker near this period".
CREATE INDEX IF NOT EXISTS ix_sec_filing_index_ticker_period
    ON uw_scan.sec_filing_index (ticker, report_date);
```

- [ ] **Step 5: Implement the repository**

```python
"""SEC filing index and CIK map (migration 132).

Standalone repository — new persistence domains get their own module from method
one (storage split rule, CLAUDE.md). Every writer commits, matching
`FundamentalObsRepository`.
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from uw_scan.sources.sec_submissions import SecFiling


class SecFilingIndexRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_cik_map(self, mapping: dict[str, str]) -> int:
        if not mapping:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.sec_cik_map (ticker, cik)
                 VALUES (%s, %s)
            ON CONFLICT (ticker) DO UPDATE
                    SET cik = EXCLUDED.cik, updated_at = now()
        """
        with self.conn.cursor() as cur:
            cur.executemany(sql, sorted(mapping.items()))
        self.conn.commit()
        return len(mapping)

    def cik_for(self, tickers: Sequence[str]) -> dict[str, str]:
        if not tickers:
            return {}
        sql = f"SELECT ticker, cik FROM {self._schema}.sec_cik_map WHERE ticker = ANY(%s)"
        with self.conn.cursor() as cur:
            cur.execute(sql, (list(tickers),))
            return dict(cur.fetchall())

    def record_filings(
        self, cik: str, ticker: str, filings: Sequence[SecFiling]
    ) -> int:
        """Insert filings. Returns how many were genuinely new."""
        if not filings:
            return 0
        sql = f"""
            INSERT INTO {self._schema}.sec_filing_index
                        (accession, cik, ticker, form, report_date, filing_date,
                         is_amendment)
                 VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (accession) DO NOTHING
        """
        before = self._count()
        with self.conn.cursor() as cur:
            cur.executemany(
                sql,
                [
                    (f.accession, cik, ticker, f.form, f.report_date, f.filing_date,
                     f.is_amendment)
                    for f in filings
                ],
            )
        self.conn.commit()
        return self._count() - before

    def filings_for(self, ticker: str) -> list[SecFiling]:
        sql = f"""
            SELECT accession, form, report_date, filing_date, is_amendment
              FROM {self._schema}.sec_filing_index
             WHERE ticker = %s
             ORDER BY report_date, accession
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (ticker,))
            return [SecFiling(*row) for row in cur.fetchall()]

    def index_counts(self) -> dict[str, int]:
        sql = f"""
            SELECT count(*), count(*) FILTER (WHERE is_amendment),
                   count(DISTINCT ticker)
              FROM {self._schema}.sec_filing_index
        """
        with self.conn.cursor() as cur:
            cur.execute(sql)
            filings, amendments, tickers = cur.fetchone()
        return {
            "filings": int(filings),
            "amendments": int(amendments),
            "tickers": int(tickers),
        }

    def _count(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT count(*) FROM {self._schema}.sec_filing_index")
            return int(cur.fetchone()[0])
```

- [ ] **Step 6: Run tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/storage/test_sec_filing_index.py \
  tests/integration/storage/test_migrations.py -q
uv run ruff check src/uw_scan/storage/sec_filing_index.py \
  tests/integration/storage/test_sec_filing_index.py
```

Expected: PASS, clean.

- [ ] **Step 7: Register both tables with the gap healer**

In `src/uw_scan/reports/data_gap_healer.py`, beside the other `fundamentals` entries,
add:

```python
        DatasetRegistryEntry(
            "sec_filing_index",
            "fundamentals",
            # `provenance`: an immutable record of what SEC published, keyed on
            # SEC's own accession. Nothing arrives on a cadence Argon controls and
            # nothing is ever rewritten; a gap is repaired by re-running the
            # refresh, which is free and idempotent.
            "provenance",
            date_col="filing_date",
            ticker_col="ticker",
            expected_frequency="event",
            provider="external",
            granularity="none",
            healer_adapter=None,
            source_system="sec_edgar",
            retention_days=None,
            reason=(
                "SEC periodic filings used as publication evidence (migration "
                "132). Free, no provider budget. Heal by re-running "
                "scripts/backfill/sec_publication_evidence.py --index."
            ),
            reason_verified_on=date(2026, 8, 24),
        ),
        DatasetRegistryEntry(
            "sec_cik_map",
            "fundamentals",
            # A cache with one row per ticker and no time dimension worth auditing.
            "excluded",
            ticker_col="ticker",
            expected_frequency="none",
            reason="ticker->CIK cache from SEC company_tickers.json; refreshed whole, no cadence",
            reason_verified_on=date(2026, 8, 24),
        ),
```

- [ ] **Step 8: Regenerate the policy doc and run both gates**

The doc is GENERATED. Do not hand-edit it.

```bash
uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/worker/test_data_gap_full_coverage.py \
  tests/unit/reports/test_data_gap_dataset_policy.py \
  tests/unit/reports/test_full_coverage.py -q
```

Expected: PASS. A failure naming `unregistered temporal tables remain` means an entry is
missing or misspelled.

- [ ] **Step 9: Commit** _(only with explicit user authorization)_

```bash
git add src/uw_scan/storage/migrations/132_sec_filing_index.sql \
        src/uw_scan/storage/sec_filing_index.py \
        tests/integration/storage/test_sec_filing_index.py \
        src/uw_scan/reports/data_gap_healer.py \
        docs/runbooks/data-gap-dataset-policy.md
git commit -m "feat(fundamentals): SEC filing index schema and repository"
```

---

## Task 4: Index refresh job

**Files:**

- Create: `src/uw_scan/worker/jobs/sec_filing_index_refresh.py`
- Create: `tests/integration/worker/test_sec_filing_index_refresh.py`

**Interfaces:**

- Consumes: Tasks 1 and 3.
- Produces: `sec_filing_index_refresh(*, conn, client, schema="uw_scan", tickers=None, tier="ranked") -> dict[str, int]`
  with counters `tickers`, `filings_inserted`, `no_cik`, `no_filings`, `failed`.

- [ ] **Step 1: Write the failing job tests**

The SEC transport is stubbed; the database is real.

```python
"""Fetching the filing index end to end, with a stubbed SEC and a real database."""

from __future__ import annotations

from datetime import date

import pytest

from uw_scan.sources.sec_submissions import SecFiling
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository
from uw_scan.worker.jobs.sec_filing_index_refresh import sec_filing_index_refresh

NVDA_Q = SecFiling("0001045810-26-000052", "10-Q", date(2026, 4, 26), date(2026, 5, 20), False)


class _StubSec:
    def __init__(self, cik_map=None, filings=None, blow_up=False):
        self.cik_map = {"NVDA": "0001045810"} if cik_map is None else cik_map
        self.filings = {"0001045810": [NVDA_Q]} if filings is None else filings
        self.blow_up = blow_up
        self.calls: list[str] = []

    def fetch_cik_map(self, _client):
        return self.cik_map

    def fetch_filings(self, _client, cik):
        self.calls.append(cik)
        if self.blow_up:
            raise RuntimeError("sec down")
        return self.filings.get(cik, [])


@pytest.fixture
def universe(seeded_db_empty_cards):
    obs = FundamentalObsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    obs.seed_universe("ranked", [("NVDA", None, "test"), ("AMD", None, "test")])
    return seeded_db_empty_cards


def _run(seeded, stub, monkeypatch, **kw):
    from uw_scan.worker.jobs import sec_filing_index_refresh as mod

    monkeypatch.setattr(mod, "fetch_cik_map", stub.fetch_cik_map)
    monkeypatch.setattr(mod, "fetch_filings", stub.fetch_filings)
    return sec_filing_index_refresh(
        conn=seeded.conn, client=object(), schema=seeded._schema, **kw
    )


def test_filings_land_for_universe_names(universe, monkeypatch):
    totals = _run(universe, _StubSec(), monkeypatch)
    assert totals["filings_inserted"] == 1
    repo = SecFilingIndexRepository(universe.conn, schema=universe._schema)
    assert len(repo.filings_for("NVDA")) == 1


def test_a_ticker_with_no_cik_is_counted_not_crashed(universe, monkeypatch):
    totals = _run(universe, _StubSec(), monkeypatch)
    assert totals["no_cik"] == 1  # AMD is in the universe, absent from the map


def test_a_rerun_inserts_nothing(universe, monkeypatch):
    stub = _StubSec()
    _run(universe, stub, monkeypatch)
    second = _run(universe, stub, monkeypatch)
    assert second["filings_inserted"] == 0


def test_one_failing_ticker_does_not_abort_the_run(universe, monkeypatch):
    totals = _run(universe, _StubSec(blow_up=True), monkeypatch)
    assert totals["failed"] == 1
    assert totals["tickers"] == 0


def test_an_empty_universe_spends_nothing(seeded_db_empty_cards, monkeypatch):
    stub = _StubSec()
    totals = _run(seeded_db_empty_cards, stub, monkeypatch)
    assert totals == {
        "tickers": 0,
        "filings_inserted": 0,
        "no_cik": 0,
        "no_filings": 0,
        "failed": 0,
    }
    assert stub.calls == []
```

- [ ] **Step 2: Run and confirm failure**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/worker/test_sec_filing_index_refresh.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the job**

```python
"""Populate the SEC filing index for the fundamental universe.

Zero provider budget: SEC is free, so this job is deliberately NOT routed through
`uw_budget` and must never be. It is rate-limited instead, because SEC's published
ceiling is 10 requests/second and exceeding it gets an IP blocked rather than
throttled.

Self-gating: an unseeded tier yields no tickers and the job returns having made no
request at all.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence

import psycopg

from uw_scan.sources.sec_submissions import fetch_cik_map, fetch_filings
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository

log = logging.getLogger(__name__)

#: SEC publishes a 10 req/s ceiling. One CIK costs 1-3 requests (submissions plus
#: archives), so 0.15s between tickers keeps a wide margin without making a
#: 420-name run take longer than a couple of minutes.
SLEEP_BETWEEN_TICKERS = 0.15


def sec_filing_index_refresh(
    *,
    conn: psycopg.Connection,
    client,
    schema: str = "uw_scan",
    tickers: Sequence[str] | None = None,
    tier: str = "ranked",
) -> dict[str, int]:
    """Fetch and persist SEC periodic filings. Returns counters; safe to re-run."""
    obs = FundamentalObsRepository(conn, schema=schema)
    index = SecFilingIndexRepository(conn, schema=schema)

    names = list(tickers) if tickers is not None else obs.list_universe(tier)
    totals = {
        "tickers": 0,
        "filings_inserted": 0,
        "no_cik": 0,
        "no_filings": 0,
        "failed": 0,
    }
    if not names:
        log.info("sec_filing_index_refresh: tier %r is empty — nothing to do", tier)
        return totals

    cik_map = fetch_cik_map(client)
    if cik_map:
        index.upsert_cik_map({t: cik_map[t] for t in names if t in cik_map})

    for ticker in names:
        cik = cik_map.get(ticker)
        if not cik:
            totals["no_cik"] += 1
            continue
        try:
            filings = fetch_filings(client, cik)
            if not filings:
                totals["no_filings"] += 1
                continue
            totals["filings_inserted"] += index.record_filings(cik, ticker, filings)
            totals["tickers"] += 1
        except Exception:
            # One bad ticker must not abort a 420-name run; the write path is
            # keyed on accession, so a partial run resumes cleanly.
            totals["failed"] += 1
            log.exception("sec_filing_index_refresh: %s failed", ticker)
        time.sleep(SLEEP_BETWEEN_TICKERS)

    log.info("sec_filing_index_refresh: %s", totals)
    return totals
```

- [ ] **Step 4: Run tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/worker/test_sec_filing_index_refresh.py -q
uv run ruff check src/uw_scan/worker/jobs/sec_filing_index_refresh.py \
  tests/integration/worker/test_sec_filing_index_refresh.py
```

Expected: PASS, clean.

- [ ] **Step 5: Commit** _(only with explicit user authorization)_

```bash
git add src/uw_scan/worker/jobs/sec_filing_index_refresh.py \
        tests/integration/worker/test_sec_filing_index_refresh.py
git commit -m "feat(fundamentals): SEC filing index refresh job"
```

---

## Task 5: Issue true_pit claims

**Files:**

- Create: `src/uw_scan/worker/jobs/fundamental_publication_evidence.py`
- Create: `tests/integration/worker/test_fundamental_publication_evidence.py`

**Interfaces:**

- Consumes: Tasks 2, 3, and the existing `FundamentalObsAvailabilityRepository`.
- Produces: `fundamental_publication_evidence(*, conn, schema="uw_scan", tickers=None, tier="ranked") -> dict[str, int]`
  with counters `identities`, `matched`, `claims_written`, and one per refusal reason
  (`multi_version`, `amended`, `ambiguous`, `no_filing`, `filed_before_period`).

- [ ] **Step 1: Write the failing tests**

```python
"""Promoting stored versions to true_pit, and refusing to.

The refusal tests carry the weight. Each one is a case where a join LOOKS
successful and the resulting claim would be false — and where the observable
consequence is that `TRUE_PIT_ONLY` starts returning data it should not.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from uw_scan.fundamentals.observation_time import EvidenceClass, EvidencePolicy
from uw_scan.fundamentals.publication_evidence import CLAIM_KEY_SEC_PUBLICATION
from uw_scan.fundamentals.statements import FIELD_MAP_VERSION, content_hash, normalize
from uw_scan.sources.sec_submissions import SecFiling
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.fundamental_observation_panels import statement_panel_as_of
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository
from uw_scan.worker.jobs.fundamental_publication_evidence import (
    fundamental_publication_evidence,
)

PERIOD = date(2026, 4, 30)
ORIGINAL = SecFiling("acc-original", "10-Q", date(2026, 4, 26), date(2026, 5, 20), False)
AMENDMENT = SecFiling("acc-amend", "10-Q/A", date(2026, 4, 26), date(2026, 7, 1), True)


def _row(ticker: str, assets: int) -> dict:
    payload = normalize(
        {
            "ticker": ticker,
            "fiscal_date_ending": PERIOD.isoformat(),
            "report_type": "quarterly",
            "total_assets": str(assets),
            "total_liabilities": "64000000000",
            "total_shareholder_equity": "195474000000",
        }
    )
    return {
        "source": "uw",
        "ticker": ticker,
        "period_end": PERIOD,
        "period_type": "quarterly",
        "statement": "balance",
        "content_hash": content_hash(payload),
        "provider_record_id": None,
        "filing_accession": None,
        "filing_published_at": date(2026, 5, 20),
        "raw_jsonb": payload,
        "field_map_version": FIELD_MAP_VERSION,
    }


def _setup(seeded, *, versions: int, filings: list[SecFiling]):
    obs = FundamentalObsRepository(seeded.conn, schema=seeded._schema)
    obs.seed_universe("ranked", [("NVDA", None, "test")])
    for i in range(versions):
        obs.record_statements([_row("NVDA", 259474000000 + i)])
    SecFilingIndexRepository(seeded.conn, schema=seeded._schema).record_filings(
        "0001045810", "NVDA", filings
    )
    FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).seed_claims(EvidenceClass.CAPTURE_BOUNDED)
    return seeded


def _counts(seeded):
    return FundamentalObsAvailabilityRepository(
        seeded.conn, schema=seeded._schema
    ).claim_counts()


def _run(seeded):
    return fundamental_publication_evidence(conn=seeded.conn, schema=seeded._schema)


def test_a_clean_period_earns_true_pit(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL])
    totals = _run(seeded)
    assert totals["matched"] == 1
    assert totals["claims_written"] == 1
    assert _counts(seeded)[EvidenceClass.TRUE_PIT] == 1


def test_the_claim_carries_the_accession_and_the_filing_date(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL])
    _run(seeded)
    with seeded.conn.cursor() as cur:
        cur.execute(
            f"""SELECT evidence_ref, available_at::date, evidence_source, claim_key
                  FROM {seeded._schema}.fundamental_obs_availability
                 WHERE evidence_class = 'true_pit'"""
        )
        ref, at, source, key = cur.fetchone()
    assert ref == "acc-original"
    assert at == date(2026, 5, 20)
    assert source == "sec_edgar"
    assert key == CLAIM_KEY_SEC_PUBLICATION


def test_an_amended_period_earns_nothing(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL, AMENDMENT])
    totals = _run(seeded)
    assert totals["amended"] == 1
    assert EvidenceClass.TRUE_PIT not in _counts(seeded)


def test_a_multi_version_identity_earns_nothing(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=2, filings=[ORIGINAL])
    totals = _run(seeded)
    assert totals["multi_version"] == 1
    assert EvidenceClass.TRUE_PIT not in _counts(seeded)


def test_a_period_with_no_filing_earns_nothing(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[])
    totals = _run(seeded)
    assert totals["no_filing"] == 1
    assert EvidenceClass.TRUE_PIT not in _counts(seeded)


def test_the_capture_claim_is_never_touched(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL])
    before = _counts(seeded)[EvidenceClass.CAPTURE_BOUNDED]
    _run(seeded)
    assert _counts(seeded)[EvidenceClass.CAPTURE_BOUNDED] == before


def test_a_rerun_writes_no_duplicate_claim(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL])
    _run(seeded)
    second = _run(seeded)
    assert second["claims_written"] == 0
    assert _counts(seeded)[EvidenceClass.TRUE_PIT] == 1


def test_true_pit_replay_now_returns_the_period(seeded_db_empty_cards):
    """The payoff: before this job, TRUE_PIT_ONLY was empty at every cutoff."""
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL])
    empty = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    assert empty == {}
    _run(seeded)
    panel = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2026, 6, 1, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    assert panel["NVDA"]["balance-sheets"][PERIOD.isoformat()]["total_assets"]


def test_the_claim_does_not_enter_before_its_filing_date(seeded_db_empty_cards):
    seeded = _setup(seeded_db_empty_cards, versions=1, filings=[ORIGINAL])
    _run(seeded)
    early = statement_panel_as_of(
        seeded.conn,
        as_of=datetime(2026, 5, 19, tzinfo=UTC),
        evidence_policy=EvidencePolicy.TRUE_PIT_ONLY,
        schema=seeded._schema,
    )
    assert early == {}
```

- [ ] **Step 2: Run and confirm failure**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/worker/test_fundamental_publication_evidence.py -q
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the job**

```python
"""Promote stored statement versions to true_pit where SEC can vouch for them.

Reads only tables Argon already holds — no provider call, no budget. Writes only
NEW claims under `sec:publication:v1`; the existing capture-bounded claim is left
exactly where it is, because a stronger claim lands BESIDE its predecessor rather
than replacing it (migration 130).

WHY THE COUNTERS NAME EVERY REFUSAL
-----------------------------------
A job that reports only what it matched cannot be audited: "12,000 claims written"
looks identical whether the other 77,000 were correctly refused or silently
dropped. Every refusal reason is counted and logged, and the operator artifact in
Task 6 reports the distribution.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import psycopg

from uw_scan.fundamentals.observation_time import EvidenceClass
from uw_scan.fundamentals.publication_evidence import (
    CLAIM_KEY_SEC_PUBLICATION,
    SOURCE_SEC_EDGAR,
    match_publication,
)
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository

log = logging.getLogger(__name__)

REFUSALS = ("multi_version", "amended", "ambiguous", "no_filing", "filed_before_period")


def fundamental_publication_evidence(
    *,
    conn: psycopg.Connection,
    schema: str = "uw_scan",
    tickers: Sequence[str] | None = None,
    tier: str = "ranked",
) -> dict[str, int]:
    """Issue true_pit claims where SEC evidence is unambiguous. Safe to re-run."""
    obs = FundamentalObsRepository(conn, schema=schema)
    index = SecFilingIndexRepository(conn, schema=schema)
    avail = FundamentalObsAvailabilityRepository(conn, schema=schema)

    names = list(tickers) if tickers is not None else obs.list_universe(tier)
    totals = {"identities": 0, "matched": 0, "claims_written": 0}
    totals.update({r: 0 for r in REFUSALS})
    if not names:
        log.info("fundamental_publication_evidence: tier %r is empty", tier)
        return totals

    for ticker in names:
        filings = index.filings_for(ticker)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT period_end, min(obs_id), count(*)
                  FROM {schema}.fundamental_statement_obs
                 WHERE ticker = %s
                 GROUP BY source, ticker, period_end, period_type, statement
                """,
                (ticker,),
            )
            identities = cur.fetchall()

        claims = []
        for period_end, obs_id, versions in identities:
            totals["identities"] += 1
            match, reason = match_publication(
                period_end, filings, version_count=int(versions)
            )
            if match is None:
                totals[reason] += 1
                continue
            totals["matched"] += 1
            claims.append(
                {
                    "obs_id": obs_id,
                    "claim_key": CLAIM_KEY_SEC_PUBLICATION,
                    "evidence_class": EvidenceClass.TRUE_PIT,
                    # Midnight UTC on the filing date. SEC publishes a DATE, not
                    # an instant, and inventing an intraday time would assert
                    # precision the source does not have.
                    "available_at": _midnight_utc(match.filing_date),
                    "evidence_source": SOURCE_SEC_EDGAR,
                    "evidence_ref": match.accession,
                    "evidence_jsonb": {"form_matched_on": "report_date"},
                }
            )
        totals["claims_written"] += avail.record_claims(claims)

    log.info("fundamental_publication_evidence: %s", totals)
    return totals


def _midnight_utc(day):
    from datetime import UTC, datetime, time

    return datetime.combine(day, time.min).replace(tzinfo=UTC)
```

- [ ] **Step 4: Run tests**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/integration/worker/test_fundamental_publication_evidence.py -q
uv run ruff check src/uw_scan/worker/jobs/fundamental_publication_evidence.py \
  tests/integration/worker/test_fundamental_publication_evidence.py
```

Expected: PASS, clean.

- [ ] **Step 5: Commit** _(only with explicit user authorization)_

```bash
git add src/uw_scan/worker/jobs/fundamental_publication_evidence.py \
        tests/integration/worker/test_fundamental_publication_evidence.py
git commit -m "feat(fundamentals): issue true_pit claims from SEC filing evidence"
```

---

## Task 6: Operator entry point and measurement

**Files:**

- Create: `scripts/backfill/sec_publication_evidence.py`
- Modify: `docs/runbooks/fundamental-observation-availability.md`
- Create: `docs/research/2026-08-24-fundamental-observation-availability/publication_evidence.md`

- [ ] **Step 1: Write the script**

```python
"""Build the SEC filing index and issue true_pit claims (migration 132).

    uv run python scripts/backfill/sec_publication_evidence.py --index
    uv run python scripts/backfill/sec_publication_evidence.py --claims
    uv run python scripts/backfill/sec_publication_evidence.py --index --claims

Entry point for `worker/jobs/sec_filing_index_refresh.py` and
`worker/jobs/fundamental_publication_evidence.py`. The jobs hold all the logic —
this script only builds the connection and the SEC client.

Cost: ZERO provider budget. SEC is free; the index pass is rate-limited to stay
well under SEC's 10 req/s ceiling and takes ~2 minutes for 420 names. The claims
pass makes no network call at all.
"""

from __future__ import annotations

import argparse
import logging
import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.sources.sec_submissions import sec_client
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.storage.sec_filing_index import SecFilingIndexRepository
from uw_scan.worker.jobs.fundamental_publication_evidence import (
    fundamental_publication_evidence,
)
from uw_scan.worker.jobs.sec_filing_index_refresh import sec_filing_index_refresh

DEFAULT_UA = "argon-research lcxxcllcx@gmail.com"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true", help="fetch and persist SEC filings")
    ap.add_argument("--claims", action="store_true", help="issue true_pit claims")
    ap.add_argument("--tickers", help="comma-separated scope")
    ap.add_argument("--tier", default="ranked")
    ap.add_argument("--user-agent", default=DEFAULT_UA)
    args = ap.parse_args()
    if not (args.index or args.claims):
        ap.error("pass --index, --claims, or both")

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    settings = Settings.from_env()
    tickers = args.tickers.split(",") if args.tickers else None

    with psycopg.connect(settings.db_dsn()) as conn:
        if args.index:
            with sec_client(args.user_agent) as client:
                print(
                    sec_filing_index_refresh(
                        conn=conn,
                        client=client,
                        schema=settings.db_schema,
                        tickers=tickers,
                        tier=args.tier,
                    )
                )
            print(SecFilingIndexRepository(conn, schema=settings.db_schema).index_counts())

        if args.claims:
            print(
                fundamental_publication_evidence(
                    conn=conn,
                    schema=settings.db_schema,
                    tickers=tickers,
                    tier=args.tier,
                )
            )
            counts = FundamentalObsAvailabilityRepository(
                conn, schema=settings.db_schema
            ).claim_counts()
            for cls, n in sorted(counts.items()):
                print(f"  {cls.value:<16} {n:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Dry-run against the local development database**

```bash
uv run python scripts/backfill/sec_publication_evidence.py --index --tickers NVDA
uv run python scripts/backfill/sec_publication_evidence.py --claims --tickers NVDA
```

Expected: the index pass reports roughly 111 filings for NVDA; the claims pass reports a
refusal distribution. Do NOT interpret local counts as production evidence.

- [ ] **Step 3: Extend the runbook**

Add a section to `docs/runbooks/fundamental-observation-availability.md` covering: the
SEC index and its zero cost, the four conditions for `true_pit`, the refusal reasons and
what each means, and the fact that a refusal is the expected outcome for amended and
multi-version periods rather than a failure.

Replace the "Expect true-PIT coverage to be zero" section with the measured figure once
Task 7 has run, keeping the original reasoning about `filing_published_at`.

- [ ] **Step 4: Commit** _(only with explicit user authorization)_

```bash
git add scripts/backfill/sec_publication_evidence.py \
        docs/runbooks/fundamental-observation-availability.md
git commit -m "feat(fundamentals): operator path for SEC publication evidence"
```

---

## Task 7: Verification and the measured artifact

- [ ] **Step 1: Run the full relevant suite**

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest \
  tests/unit/sources/test_sec_submissions.py \
  tests/unit/fundamentals \
  tests/integration/storage/test_sec_filing_index.py \
  tests/integration/storage/test_fundamental_observation_availability.py \
  tests/integration/storage/test_fundamental_observation_panels.py \
  tests/integration/worker/test_sec_filing_index_refresh.py \
  tests/integration/worker/test_fundamental_publication_evidence.py \
  tests/integration/worker/test_data_gap_full_coverage.py \
  tests/unit/reports/test_data_gap_dataset_policy.py -q
```

Then the whole suite, because a migration touches the shared schema:

```bash
UW_SCAN_TEST_DB_NAME=option_wizard_test_asof uv run pytest -q
uv run ruff check src/ tests/ scripts/
uv run python scripts/check_no_yahoo.py
git diff --check
git status --short
```

Record exact pass/fail/skip counts. Do not summarise a failure away.

- [ ] **Step 2: Prove migration idempotency on a fresh database**

```bash
psql -h 127.0.0.1 -d postgres -c 'DROP DATABASE IF EXISTS "option_wizard_test_idem"' \
  -c 'CREATE DATABASE "option_wizard_test_idem"' \
  -c 'GRANT ALL ON DATABASE "option_wizard_test_idem" TO argon_app'
UW_SCAN_API_KEY=x UW_SCAN_DB_NAME=option_wizard_test_idem UW_SCAN_ALLOW_DB_MISMATCH=1 \
  uv run python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.storage.migrate_runner import apply_migrations
s = Settings.from_env().model_copy(update={'db_name':'option_wizard_test_idem'})
for run in (1,2):
    with psycopg.connect(s.db_dsn(), autocommit=True) as c: apply_migrations(c, log=lambda _m: None)
    print('pass', run, 'OK')
"
psql -h 127.0.0.1 -d postgres -c 'DROP DATABASE "option_wizard_test_idem"'
```

Expected: both passes OK.

- [ ] **Step 3: Run against production — ONLY with explicit authorization**

Prod is `option_wizard` on the mini. Migrations apply out-of-band; both new tables are
additive and ignored by the currently deployed image.

```bash
export UW_SCAN_DB_PASSWORD="$(ssh macmini 'grep -m1 "^UW_SCAN_DB_PASSWORD=" /opt/argon/.env | cut -d= -f2-' | tr -d '\r\n')"
UW_SCAN_API_KEY=x UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/sec_publication_evidence.py --index
UW_SCAN_API_KEY=x UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/sec_publication_evidence.py --claims
UW_SCAN_API_KEY=x UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
  uv run python scripts/backfill/fundamental_observation_availability.py \
    --audit docs/research/2026-08-24-fundamental-observation-availability/coverage-with-sec.json
```

- [ ] **Step 4: Write the measured artifact**

Create `docs/research/2026-08-24-fundamental-observation-availability/publication_evidence.md`
reporting, with the exact command, host, database, and commit:

- SEC filings indexed, tickers covered, amendments found;
- identities examined and the **full refusal distribution** (`multi_version`, `amended`,
  `ambiguous`, `no_filing`, `filed_before_period`);
- `true_pit` claims written, as a count and as a share of 89,758;
- the earliest `true_pit` `available_at` — i.e. **how far back leak-free replay now
  reaches**, which is the number this whole milestone exists to move;
- what a `TRUE_PIT_ONLY` replay returns at three cutoffs (e.g. 2015-06-30, 2020-06-30,
  2026-06-30), measured through `statement_panel_as_of`, not asserted;
- tickers with zero true-PIT coverage and why.

State plainly whether M3 (corrected research) is now unblocked. If true-PIT reach is
still too shallow for the research that needs it, say so and stop — do not let a
milestone that shipped software but not capability be recorded as a success.

- [ ] **Step 5: Update the handover and CHANGELOG**

Add an M1-A section to
`docs/handover/2026-08-24-fundamental-pm-research-system-claude-handover.md` with the
measured figures, and an `[Unreleased]` CHANGELOG entry.

- [ ] **Step 6: Stop for review**

No commit, push, PR, or image deploy without explicit authorization.

---

## Completion gate

M1-A is ready for review only when all hold:

- the four conditions are implemented as written and each refusal is counted separately;
- no `true_pit` claim exists without an accession reference and a filing date;
- `filing_published_at` promotes nothing;
- an amended period and a multi-version identity both earn zero claims, proven by test;
- a `true_pit` claim never admits before its own filing date, proven through the real
  as-of reader;
- capture-bounded claims are untouched and the current card/anchor path is unchanged;
- both new tables are registered and the policy doc is regenerated, not hand-edited;
- migrations rerun cleanly on a fresh database;
- the full suite, ruff, no-Yahoo and diff checks are recorded with exact counts;
- the measured artifact states how far back leak-free replay actually reaches, and
  whether that unblocks M3;
- no commit, push, PR, or production change occurred without authorization.

## Explicitly out of scope

- M1-B canonical multi-source reconciliation (SEC XBRL _facts_ vs UW figures);
- M1-C typed provenance graph replacing `source_obs_ids BIGINT[]`;
- M1-D company identity/`company_type` coverage;
- backfilling `filing_accession` on the observation rows (the claim's `evidence_ref`
  carries it; writing it onto the immutable observation is a separate decision);
- re-running any historical research or upgrading any verdict;
- scheduling either job on the worker — both stay operator-invoked until the measured
  coverage justifies a cadence.
