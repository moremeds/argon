# Historical Replay Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `pipeline.run_single_stock` an optional `market_date` so the deep-scan tables lost in the 2026-08-11→14 outage can be re-fetched from UW at their true dates, and refuse — in code — to write any dataset whose UW endpoint ignores the date parameter.

**Architecture:** Parameterize the existing pipeline rather than fork it. `run_single_stock(..., market_date=None)` behaves exactly as today when `market_date is None`; when a date is supplied it (a) passes `date=` to the nine fetchers measured to honor it, (b) stamps the six hardcoded `_date.today()` call sites from the parameter, and (c) skips the three datasets whose endpoints return today's data regardless of `date=` — writing those under a historical stamp would fabricate. A thin CLI walks (ticker, date) pairs and is resumable.

**Tech Stack:** Python 3.13, `uv`, psycopg 3, pytest, httpx MockTransport. UW REST (standard tier).

**Spec:** No separate spec document. The empirical basis is the measured endpoint matrix in §Endpoint Evidence below, probed live against UW on 2026-08-16 for AAPL with `date=2026-08-12`. Re-run the probe in Task 1 before trusting it.

## Global Constraints

- **uv only** — `uv run pytest`, never bare `pytest`.
- **No fabrication / no synthetic data.** A row may only be written under a historical `market_date` if the provider's response for that date differs from its response for another date. This is enforced by code in Task 2, not by convention.
- **Live path behavior must not change.** `market_date=None` is the default and must produce byte-identical behavior to today. Every task that touches `pipeline.py` re-runs the existing pipeline tests.
- **Tests use real tickers at real prices, frozen** — capture a real UW payload once, commit it as a fixture with its as-of date, assert against that snapshot. No network at test runtime. No placeholder symbols.
- **Never commit without explicit user request.** Steps below include commits; get sign-off before running them.
- **Module size budget** — target <500 lines/file. `pipeline.py` is 472 lines today; Task 3 adds ~40. If it crosses 500, split the replay orchestration into `pipeline_replay.py` rather than growing it further.
- **Branch:** `feat/historical-replay-backfill`. Open a PR before merging to `main`. CHANGELOG entry rides this PR.

---

## Endpoint Evidence

Measured 2026-08-16, AAPL, `date=2026-08-12` vs `date=2026-08-14`, live UW standard tier.

| Fetcher | Endpoint | Behavior | Replay action |
|---|---|---|---|
| `fetch_term_structure` | `/volatility/term-structure` | HONORS — rows dated 08-12 | add `market_date` |
| `fetch_interpolated_iv` | `/interpolated-iv` | HONORS | add `market_date` |
| `fetch_spot_exposures` | `/spot-exposures/expiry-strike` | HONORS | add `market_date` |
| `fetch_oi_per_strike` | `/oi-per-strike` | HONORS | add `market_date` |
| `fetch_oi_change` | `/oi-change` | HONORS (`curr_date`) | add `market_date` |
| `fetch_greek_exposure` | `/greek-exposure/strike-expiry` | HONORS | add `market_date` |
| `fetch_max_pain` | `/max-pain` | no date field, but **body differs by date** | add `market_date`; caller stamps |
| `fetch_option_contracts` | `/option-contracts` | no date field, **body differs by date** | add `market_date`; caller stamps |
| `fetch_darkpool_ticker` | `/darkpool/{ticker}` | `executed_at` respects date | add `market_date` |
| `fetch_greeks` | `/greeks` | HONORS — **already has `date`** | pass through |
| `fetch_greek_exposure_by_expiry` | `/greek-exposure/expiry` | HONORS — **already has `date`** | pass through |
| `fetch_volatility_stats` | `/volatility/stats` | body differs by date — **already has `date`** | pass through |
| `fetch_skew` | `/historical-risk-reversal-skew` | **SERIES** — one call returns 250 rows incl. 08-11→14 | no change needed |
| `fetch_realized_volatility` | `/volatility/realized` | **SERIES** | no change needed |
| `fetch_iv_rank` | `/iv-rank` | **SERIES** | no change needed |
| `fetch_flow_alerts` | `/option-trades/flow-alerts` | **IGNORES date — identical body** | **REFUSE** |
| `fetch_short_data` | `/shorts/{ticker}/data` | **IGNORES date — identical body** | **REFUSE** |
| `upsert_options_volume_daily` src | `/options-volume` | **IGNORES date** — asked 08-12, returned 08-14 | **REFUSE** |

Hardcoded `_date.today()` sites in `src/uw_scan/pipeline.py` that must be driven by the parameter: lines **262**, **275** (`upsert_exposures_summary`), **297** (max-pain `market_date`), **392** (`append_pcr_history`), **419** (`run_scanner_detectors` `today=`). Plus `_today_et()` at line **196**, which selects `nearest_expiry` and must anchor to the replay date so the replayed expiry matches what that session actually traded.

**Verified precedent:** on 2026-08-16, `fetch_skew(...,"2026-09-18")` for AAPL returned 250 rows spanning 2026-08-07→14 and `upsert_skew_rows` persisted 08-11→14 at correct dates with zero code change. Task 1 exploits exactly this.

---

## File Structure

- `src/uw_scan/sources/uw.py` — add `market_date: _date | None = None` to nine fetchers. Each is a thin `_fetch_json` wrapper; the change is one conditional `params["date"] = market_date.isoformat()` per fetcher.
- `src/uw_scan/pipeline.py` — add `market_date` param to `run_single_stock`; replace six `today()` stamps; skip the three refused datasets when replaying; skip scanner/trade-insight side effects when replaying.
- `src/uw_scan/pipeline_replay_policy.py` *(new, ~40 lines)* — the allow/deny sets plus `assert_replayable()`. Separate file so the refusal is testable in isolation and reviewable as policy, not buried in a 470-line pipeline.
- `scripts/backfill/pipeline_replay_backfill.py` *(new)* — CLI walking (ticker, date) pairs; resumable; UW-capped; `--confirm` gated.
- `tests/unit/test_pipeline_replay_policy.py` *(new)*
- `tests/unit/test_uw_fetchers_market_date.py` *(new)*
- `tests/unit/test_pipeline_replay.py` *(new)*
- `tests/fixtures/uw/` — frozen real payloads for the new fetcher tests.

---

### Task 1: Backfill `risk_reversal_skew_history` (zero pipeline change)

`/historical-risk-reversal-skew` returns a full trailing series that already contains 2026-08-11→14, so a plain re-fetch heals it with no date plumbing at all. This ships value before any risky refactor and is independently revertible.

Scope note — the other two SERIES-shaped tables need nothing here:
- `realized_volatility_history` is **already at 170/170** for 2026-08-11→14 (healed 2026-08-16 by the gap healer's `realized_volatility` adapter). Do not re-run it.
- `iv_rank_history` is **cockpit-only** (4 rows/day, SPX/SPY/QQQ/IWM) and is written by `cockpit_daily_snapshot` — it is handled in **Task 6**, not here.

Baseline before starting: `risk_reversal_skew_history` has 1 ticker on each of 08-11→14 (an AAPL feasibility probe run on 2026-08-16), against ~170 expected. **Note the freshness monitor already reports this table as healthy** — it keys on `max_data_date`, so one ticker un-freezes the whole table. Coverage, not max-date, is the acceptance criterion here.

**Expiry selection is load-bearing.** The primary key is `(ticker, market_date, delta, expiry)` and the nightly pipeline writes each ticker's *nearest* expiry as-of the scan (`pipeline.py:196-217` — nearest non-expired from the term structure, falling back to `_next_friday`). A single fixed `--expiry` for all tickers would write real, correctly-dated data under the *wrong* expiry, silently diverging from the nightly convention and leaving consumers reading a different contract than history. Select per ticker using the same rule the pipeline uses; do not hardcode one expiry across the watchlist.

**Files:**
- Create: `scripts/backfill/series_reheal.py`
- Test: `tests/unit/scripts/test_series_reheal.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `series_reheal(repo, client, tickers: list[str], expiry: str) -> dict[str, int]` returning `{"skew_rows": int, "tickers": int}`. Not used by later tasks.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/scripts/test_series_reheal.py
from datetime import date
from unittest.mock import MagicMock

from uw_scan.models.volatility import SkewRow


def test_series_reheal_persists_every_returned_date(monkeypatch):
    """The skew endpoint returns a trailing series; reheal must persist ALL of it,
    not just the newest row — that is the whole point of the series path."""
    import scripts.backfill.series_reheal as mod

    rows = [
        SkewRow(ticker="AAPL", date=date(2026, 8, 11), expiry=date(2026, 9, 18), delta=25, skew=0.031),
        SkewRow(ticker="AAPL", date=date(2026, 8, 12), expiry=date(2026, 9, 18), delta=25, skew=0.028),
    ]
    monkeypatch.setattr(mod.uw_sources, "fetch_skew", lambda *a, **k: rows)
    monkeypatch.setattr(mod, "nearest_expiry", lambda *a, **k: "2026-09-18")
    repo = MagicMock()
    repo.upsert_skew_rows.return_value = len(rows)

    out = mod.series_reheal(repo, MagicMock(), ["AAPL"], date(2026, 8, 11))

    assert out["skew_rows"] == 2
    assert repo.upsert_skew_rows.call_args[0][1] == rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/scripts/test_series_reheal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.backfill.series_reheal'`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python
"""Re-heal the UW datasets whose endpoints return a trailing SERIES.

/historical-risk-reversal-skew, /iv-rank and /volatility/realized all return a
~250-row trailing series regardless of any `date` param, so one call per ticker
re-persists every session in the window — including any the stack missed while
it was down. No date plumbing is required; that is why this is separate from the
replay work.

Verified 2026-08-16: AAPL returned 250 skew rows spanning 2026-08-07..14 and
upsert_skew_rows persisted 08-11..14 at their correct dates.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
    uv run python scripts/backfill/series_reheal.py --anchor 2026-08-11 --confirm
"""
from __future__ import annotations

import argparse
import logging
from datetime import date as _date

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources import uw as uw_sources
from uw_scan.storage.repository import Repository

logger = logging.getLogger("series_reheal")


def nearest_expiry(client, repo, run_id: int, ticker: str, anchor: _date) -> str | None:
    """The expiry the nightly pipeline would have used — same rule as pipeline.py:196.

    Nearest non-expired expiry from the term structure; None if the term structure
    is empty (caller skips the ticker rather than inventing an expiry, which would
    write the right numbers against the wrong contract).
    """
    term_rows = uw_sources.fetch_term_structure(client, repo, run_id, ticker)
    valid = sorted(r.expiry for r in term_rows if r.expiry >= anchor)
    return valid[0].isoformat() if valid else None


def series_reheal(repo, client, tickers: list[str], anchor: _date) -> dict[str, int]:
    total = skipped = 0
    for ticker in tickers:
        run_id = repo.insert_scan_run(ticker, notes="series_reheal")
        try:
            expiry = nearest_expiry(client, repo, run_id, ticker, anchor)
            if expiry is None:
                skipped += 1
                repo.finish_scan_run(run_id, status="ok")
                logger.info("series_reheal: %s has no live expiry — skipped", ticker)
                continue
            rows = uw_sources.fetch_skew(client, repo, run_id, ticker, expiry)
            total += repo.upsert_skew_rows(ticker, rows)
            repo.finish_scan_run(run_id, status="ok")
        except Exception as exc:  # noqa: BLE001
            repo.finish_scan_run(run_id, status="error")
            logger.warning("series_reheal failed for %s: %r", ticker, exc)
    return {"skew_rows": total, "tickers": len(tickers), "skipped": skipped}


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--anchor",
        required=True,
        help="YYYY-MM-DD; expiries are chosen as the nearest non-expired one from "
        "this date, matching the nightly pipeline's rule. Use the FIRST outage "
        "session (2026-08-11) so the contract matches what that week traded.",
    )
    ap.add_argument("--confirm", action="store_true", help="required; this spends UW calls")
    args = ap.parse_args()
    if not args.confirm:
        print("refusing to run without --confirm (UW-bound)")
        return 2
    s = Settings.from_env()
    repo = Repository(psycopg.connect(s.db_dsn()), schema=s.db_schema)
    client = UwClient(
        api_key=s.api_key.get_secret_value(),
        base_url=s.base_url,
        timeout=s.request_timeout_seconds,
    )
    tickers = [c.ticker for c in repo.list_watchlist_cards()]
    out = series_reheal(repo, client, tickers, _date.fromisoformat(args.anchor))
    repo.conn.commit()
    logger.info("series_reheal complete: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/scripts/test_series_reheal.py -v`
Expected: PASS

- [ ] **Step 5: Run against the mini and verify the dates landed**

```bash
ssh macmini 'export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin
docker cp /tmp/series_reheal.py argon-worker-uw-0-1:/app/scripts/backfill/
docker exec argon-worker-uw-0-1 /app/.venv/bin/python \
  scripts/backfill/series_reheal.py --anchor 2026-08-11 --confirm'
```

Then confirm coverage moved off 2026-08-10:

```sql
SELECT market_date, count(DISTINCT ticker)
  FROM uw_scan.risk_reversal_skew_history
 WHERE market_date BETWEEN '2026-08-11' AND '2026-08-14'
 GROUP BY 1 ORDER BY 1;
```

Expected: four rows, ticker counts approaching the 170-name watchlist.

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill/series_reheal.py tests/unit/scripts/test_series_reheal.py
git commit -m "feat(backfill): re-heal SERIES-shaped UW datasets without date plumbing"
```

---

### Task 2: Replay policy module (the refusal, in code)

**Files:**
- Create: `src/uw_scan/pipeline_replay_policy.py`
- Test: `tests/unit/test_pipeline_replay_policy.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `REPLAY_SAFE: frozenset[str]`, `REPLAY_REFUSED: dict[str, str]`, and `assert_replayable(dataset: str) -> None` which raises `ReplayRefused` (a `ValueError` subclass) for a refused dataset. Task 3 imports all three.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pipeline_replay_policy.py
import pytest

from uw_scan.pipeline_replay_policy import (
    REPLAY_REFUSED,
    REPLAY_SAFE,
    ReplayRefused,
    assert_replayable,
)


def test_safe_dataset_passes():
    assert_replayable("oi_by_strike") is None


@pytest.mark.parametrize("dataset", ["flow_events", "short_interest_snapshots", "options_volume_daily"])
def test_endpoints_that_ignore_date_are_refused(dataset):
    """These three return an identical body for different `date` values, so a
    historical stamp would label today's data as the past — fabrication."""
    with pytest.raises(ReplayRefused) as exc:
        assert_replayable(dataset)
    assert "ignores" in str(exc.value).lower()


def test_safe_and_refused_are_disjoint():
    assert not (REPLAY_SAFE & set(REPLAY_REFUSED))


def test_every_refusal_carries_its_evidence():
    for dataset, reason in REPLAY_REFUSED.items():
        assert "2026-08-16" in reason, f"{dataset} refusal must cite the measurement date"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_pipeline_replay_policy.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.pipeline_replay_policy'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Which datasets may be re-fetched under a historical market_date.

A dataset is replay-safe ONLY if UW's response for one date differs from its
response for another. Where the endpoint ignores `date` and always returns the
latest session, writing that payload under a past market_date would present
today's numbers as history — fabrication, which CLAUDE.md forbids outright. The
refusal therefore lives in code, not in a comment.

Evidence: probed live 2026-08-16 (AAPL, date=2026-08-12 vs date=2026-08-14,
standard tier), comparing the sha256 of the `data` array.
"""

from __future__ import annotations


class ReplayRefused(ValueError):
    """Raised when a caller asks to replay a dataset that cannot be dated."""


REPLAY_SAFE: frozenset[str] = frozenset(
    {
        "iv_term_snapshots",
        "interpolated_iv_snapshots",
        "exposures_summary",
        "exposures_by_expiry_strike",
        "greeks_by_expiry_strike",
        "oi_by_strike",
        "oi_change_events",
        "max_pain_by_expiry",
        "option_contract_snapshots",
        "dark_pool_events",
    }
)

REPLAY_REFUSED: dict[str, str] = {
    "flow_events": (
        "UW /option-trades/flow-alerts ignores `date` — measured 2026-08-16, "
        "identical response body for 2026-08-12 and 2026-08-14"
    ),
    "flow_alerts_daily_rollup": (
        "derived from flow_events, which cannot be dated — measured 2026-08-16"
    ),
    "short_interest_snapshots": (
        "UW /shorts/{ticker}/data ignores `date` — measured 2026-08-16, "
        "identical response body for 2026-08-12 and 2026-08-14"
    ),
    "options_volume_daily": (
        "UW /options-volume ignores `date` — measured 2026-08-16, asked for "
        "2026-08-12 and received a row dated 2026-08-14"
    ),
}


def assert_replayable(dataset: str) -> None:
    """Raise ReplayRefused if `dataset` must not be written at a historical date."""
    reason = REPLAY_REFUSED.get(dataset)
    if reason is not None:
        raise ReplayRefused(f"{dataset}: {reason}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_pipeline_replay_policy.py -v`
Expected: PASS (4 tests, one parametrized ×3)

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/pipeline_replay_policy.py tests/unit/test_pipeline_replay_policy.py
git commit -m "feat(pipeline): add replay policy refusing datasets whose UW endpoint ignores date"
```

---

### Task 3: Add `market_date` to the nine fetchers

**Files:**
- Modify: `src/uw_scan/sources/uw.py` (`fetch_term_structure`, `fetch_interpolated_iv`, `fetch_spot_exposures`, `fetch_oi_per_strike`, `fetch_oi_change`, `fetch_greek_exposure`, `fetch_max_pain`, `fetch_option_contracts`, `fetch_darkpool_ticker`)
- Test: `tests/unit/test_uw_fetchers_market_date.py`

**Interfaces:**
- Consumes: nothing.
- Produces: each of the nine gains a trailing keyword `market_date: _date | None = None`. When `None` the params dict is unchanged (live behavior identical); when set, `params["date"] = market_date.isoformat()`. Task 4 calls them with this keyword.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_uw_fetchers_market_date.py
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from uw_scan.sources import uw

FIX = Path("tests/fixtures/uw")


def _patch_fetch_json(monkeypatch, payload, captured):
    def fake_fetch_json(client, repo, run_id, slug, ticker, params=None, **kw):
        captured.update(slug=slug, ticker=ticker, params=params)
        return payload

    monkeypatch.setattr(uw, "_fetch_json", fake_fetch_json)


@pytest.mark.parametrize(
    "fn_name,fixture,extra_args",
    [
        ("fetch_oi_per_strike", "oi_per_strike_aapl.json", ()),
        ("fetch_oi_change", "oi_change_aapl.json", ()),
        ("fetch_max_pain", "max_pain_aapl.json", ()),
        ("fetch_term_structure", "term_structure_aapl.json", ()),
        ("fetch_interpolated_iv", "interpolated_iv_aapl.json", ()),
    ],
)
def test_market_date_is_sent_as_date_param(monkeypatch, fn_name, fixture, extra_args):
    captured: dict = {}
    _patch_fetch_json(monkeypatch, json.loads((FIX / fixture).read_text()), captured)
    fn = getattr(uw, fn_name)
    fn(MagicMock(), MagicMock(), 1, "AAPL", *extra_args, market_date=date(2026, 8, 12))
    assert captured["params"]["date"] == "2026-08-12"


@pytest.mark.parametrize(
    "fn_name,fixture", [("fetch_oi_per_strike", "oi_per_strike_aapl.json")]
)
def test_omitting_market_date_leaves_params_unchanged(monkeypatch, fn_name, fixture):
    """Live path must be byte-identical: no `date` key when market_date is None."""
    captured: dict = {}
    _patch_fetch_json(monkeypatch, json.loads((FIX / fixture).read_text()), captured)
    getattr(uw, fn_name)(MagicMock(), MagicMock(), 1, "AAPL")
    assert "date" not in (captured["params"] or {})
```

- [ ] **Step 2: Capture the fixtures (one-time, real payloads)**

Frozen real AAPL responses, as-of 2026-08-12. Run once and commit the files:

```bash
UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard uv run python - <<'PY'
import httpx, json, pathlib
from uw_scan.config import Settings
s = Settings.from_env()
h = {"Authorization": f"Bearer {s.api_key.get_secret_value()}", "Accept": "application/json"}
out = pathlib.Path("tests/fixtures/uw")
for name, path, extra in [
    ("oi_per_strike_aapl.json", "/api/stock/AAPL/oi-per-strike", {}),
    ("oi_change_aapl.json", "/api/stock/AAPL/oi-change", {}),
    ("max_pain_aapl.json", "/api/stock/AAPL/max-pain", {}),
    ("term_structure_aapl.json", "/api/stock/AAPL/volatility/term-structure", {}),
    ("interpolated_iv_aapl.json", "/api/stock/AAPL/interpolated-iv", {}),
]:
    p = {"date": "2026-08-12"}; p.update(extra)
    r = httpx.get(f"{s.base_url}{path}", params=p, headers=h, timeout=30)
    r.raise_for_status()
    (out / name).write_text(json.dumps(r.json(), indent=2))
    print("wrote", name)
PY
```

Some of these fixtures may already exist — check `ls tests/fixtures/uw/` first and reuse rather than overwrite, so unrelated tests keep their snapshot.

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_uw_fetchers_market_date.py -v`
Expected: FAIL — `TypeError: fetch_oi_per_strike() got an unexpected keyword argument 'market_date'`

- [ ] **Step 4: Write minimal implementation**

Apply this shape to each of the nine. Example for `fetch_oi_per_strike`:

```python
def fetch_oi_per_strike(
    client: UwClient,
    repo: Repository,
    run_id: int,
    ticker: str,
    market_date: _date | None = None,
) -> list[OiPerStrikeRow]:
    params: dict[str, Any] = {}
    if market_date is not None:
        params["date"] = market_date.isoformat()
    body = _fetch_json(
        client, repo, run_id, EndpointSlug.OI_PER_STRIKE, ticker, params=params or None
    )
    return normalize.normalize_oi_per_strike(body)
```

For fetchers that already build a `params` dict (e.g. `fetch_option_contracts` with `limit`, `fetch_darkpool_ticker` with `limit`, `fetch_spot_exposures` with `expirations[]`), add only the two `market_date` lines — do not restructure the existing params.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_uw_fetchers_market_date.py -v`
Expected: PASS

- [ ] **Step 6: Verify the live path did not change**

Run: `uv run pytest tests/unit -k "uw_fetchers or normalize or pipeline" -q`
Expected: PASS, no regressions.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/sources/uw.py tests/unit/test_uw_fetchers_market_date.py tests/fixtures/uw/
git commit -m "feat(sources): optional market_date on the nine date-honoring UW fetchers"
```

---

### Task 4: Thread `market_date` through `run_single_stock`

**Files:**
- Modify: `src/uw_scan/pipeline.py:146` (signature), `:196`, `:262`, `:275`, `:297`, `:392`, `:419`
- Test: `tests/unit/test_pipeline_replay.py`

**Interfaces:**
- Consumes: `uw_scan.pipeline_replay_policy.REPLAY_REFUSED` (Task 2); the nine `market_date=` fetcher kwargs (Task 3).
- Produces: `run_single_stock(ticker: str, client: UwClient, repo: Repository, market_date: _date | None = None) -> SingleStockReport`. Task 5's CLI calls it with `market_date` set.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_pipeline_replay.py
from datetime import date
from unittest.mock import MagicMock

from uw_scan import pipeline

# There is NO pre-existing pipeline test file in this repo (verified 2026-08-16),
# so this harness is the one you write. Every UW fetcher run_single_stock calls
# must be stubbed or the test will attempt a live request.
_FETCHERS = (
    "fetch_bulk_screener_ticker", "fetch_darkpool_ticker", "fetch_flow_alerts",
    "fetch_greek_exposure", "fetch_greek_exposure_by_expiry", "fetch_greeks",
    "fetch_interpolated_iv", "fetch_max_pain", "fetch_oi_change",
    "fetch_oi_per_strike", "fetch_option_contracts", "fetch_realized_volatility",
    "fetch_short_data", "fetch_skew", "fetch_spot_exposures",
    "fetch_term_structure", "fetch_volatility_stats",
)


def _stub_all_fetchers(monkeypatch):
    for name in _FETCHERS:
        monkeypatch.setattr(pipeline.uw_sources, name, lambda *a, **k: [])


def test_replay_stamps_the_supplied_date_not_today(monkeypatch):
    """exposures_summary / pcr_history are stamped from _date.today() on the live
    path; under replay they must carry the replay date or the row lands mis-dated."""
    seen: dict = {}
    repo = MagicMock()
    repo.insert_scan_run.return_value = 1
    repo.upsert_exposures_summary.side_effect = lambda **kw: seen.setdefault(
        "exposures_market_date", kw["market_date"]
    )
    _stub_all_fetchers(monkeypatch)

    pipeline.run_single_stock("AAPL", MagicMock(), repo, market_date=date(2026, 8, 12))

    assert seen["exposures_market_date"] == date(2026, 8, 12)


def test_replay_does_not_write_refused_datasets(monkeypatch):
    """flow_events and short_interest_snapshots come from endpoints that ignore
    `date`; replaying them would fabricate, so they must be skipped entirely."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 1
    _stub_all_fetchers(monkeypatch)

    pipeline.run_single_stock("AAPL", MagicMock(), repo, market_date=date(2026, 8, 12))

    repo.insert_flow_events.assert_not_called()
    repo.insert_short_interest_snapshot.assert_not_called()
    repo.upsert_flow_alerts_daily_rollup.assert_not_called()


def test_live_path_still_writes_everything(monkeypatch):
    """market_date=None must behave exactly as before — refused datasets are only
    refused under replay."""
    repo = MagicMock()
    repo.insert_scan_run.return_value = 1
    _stub_all_fetchers(monkeypatch)

    pipeline.run_single_stock("AAPL", MagicMock(), repo)

    repo.insert_flow_events.assert_called()
```

Note: these tests need the UW calls stubbed. Follow the mocking already used in the existing pipeline tests — run `ls tests/unit | grep -i pipeline` and mirror that file's harness rather than inventing a new one. If no pipeline test exists, stub every `uw_sources.fetch_*` used by `run_single_stock` with `monkeypatch.setattr(pipeline.uw_sources, name, lambda *a, **k: [])`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_pipeline_replay.py -v`
Expected: FAIL — `TypeError: run_single_stock() got an unexpected keyword argument 'market_date'`

- [ ] **Step 3: Write minimal implementation**

Signature and anchor:

```python
def run_single_stock(
    ticker: str,
    client: UwClient,
    repo: Repository,
    market_date: _date | None = None,
) -> SingleStockReport:
    """Run the full S1 pipeline against UW for `ticker` and persist everything.

    ``market_date=None`` is the live path and is unchanged. When a date is given
    the pipeline REPLAYS that session: date-honoring fetchers receive ``date=``,
    every persisted stamp comes from the parameter rather than ``today()``, and
    the datasets in ``REPLAY_REFUSED`` are skipped because their UW endpoints
    ignore ``date`` (writing them would back-date today's numbers).
    """
    ticker = ticker.upper()
    replay = market_date is not None
    stamp = market_date or _date.today()
    anchor = market_date or _today_et()
```

Then, mechanically:
- line 196 `today_et = _today_et()` → `today_et = anchor`
- lines 262, 275 `market_date=_date.today()` → `market_date=stamp`
- line 297 `market_date = _date.today()` → `market_date = stamp`
- line 392 `snapshot_date=_date.today()` → `snapshot_date=stamp`
- line 419 `today=_date.today()` → `today=stamp`
- pass `market_date=market_date` to the nine fetchers from Task 3.

Guard each refused dataset:

```python
        # 1. Flow alerts — REFUSED under replay: /option-trades/flow-alerts returns
        # an identical body for different `date` values (measured 2026-08-16), so a
        # replayed write would stamp today's alerts with a past date.
        if not replay:
            flow_alerts = uw_sources.fetch_flow_alerts(
                client, repo, run_id, ticker, limit=FLOW_ALERT_LIMIT
            )
            ticker_alerts = [a for a in flow_alerts if a.ticker == ticker]
            repo.insert_flow_events(run_id, ticker, ticker_alerts)
            repo.upsert_flow_alerts_daily_rollup(
                run_id=run_id,
                ticker=ticker,
                alerts=ticker_alerts,
                alert_limit=FLOW_ALERT_LIMIT,
            )
        else:
            ticker_alerts = []
```

Apply the same `if not replay:` guard to the `fetch_short_data` → `insert_short_interest_snapshot` block, and to the scanner-detector and trade-insight blocks near lines 400–430 (those emit live decision artifacts; replaying them would inject past-dated signals into a live surface).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_pipeline_replay.py -v`
Expected: PASS

- [ ] **Step 5: Verify no live regression**

Run: `uv run pytest tests/unit tests/integration -q`
Expected: PASS. Any failure here means the live path changed — fix before proceeding.

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/pipeline.py tests/unit/test_pipeline_replay.py
git commit -m "feat(pipeline): optional market_date replays a past session; refuse undatable datasets"
```

---

### Task 5: Replay backfill CLI

**Files:**
- Create: `scripts/backfill/pipeline_replay_backfill.py`
- Test: `tests/unit/scripts/test_pipeline_replay_backfill.py`

**Interfaces:**
- Consumes: `run_single_stock(..., market_date=...)` (Task 4).
- Produces: `missing_pairs(repo, table, dates, tickers) -> list[tuple[date, str]]` and a `main()` CLI. Nothing depends on it.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/scripts/test_pipeline_replay_backfill.py
from datetime import date
from unittest.mock import MagicMock


def test_missing_pairs_skips_rows_already_present():
    """Resumability: a (date, ticker) already in the table must not be re-fetched,
    so a capped run can be resumed without paying twice."""
    import scripts.backfill.pipeline_replay_backfill as mod

    repo = MagicMock()
    cur = repo.conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [(date(2026, 8, 11), "AAPL")]

    pairs = mod.missing_pairs(
        repo, "oi_by_strike", [date(2026, 8, 11), date(2026, 8, 12)], ["AAPL"]
    )

    assert pairs == [(date(2026, 8, 12), "AAPL")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/scripts/test_pipeline_replay_backfill.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python
"""Replay past sessions through the production pipeline to heal deep-scan tables.

Walks (date, ticker) pairs that `oi_by_strike` is missing — the widest of the
replayable tables, so it is the coverage proxy — and calls the SAME
`run_single_stock` the nightly scan uses, with `market_date` set. Resumable:
pairs already present are skipped, so a budget-capped run can simply be re-run.

Datasets whose UW endpoint ignores `date` are skipped by the pipeline itself
(see uw_scan.pipeline_replay_policy) and can never be healed this way.

Reproduce:
  UW_SCAN_DB_HOST=100.66.147.98 UW_SCAN_DB_NAME=option_wizard \
    uv run python scripts/backfill/pipeline_replay_backfill.py \
      --start 2026-08-11 --end 2026-08-14 --max-tickers 170 --confirm
"""
from __future__ import annotations

import argparse
import logging
from datetime import date as _date
from datetime import timedelta

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.pipeline import run_single_stock
from uw_scan.storage.repository import Repository

logger = logging.getLogger("pipeline_replay_backfill")


def missing_pairs(repo, table: str, dates: list[_date], tickers: list[str]):
    with repo.conn.cursor() as cur:
        cur.execute(
            f"SELECT market_date, ticker FROM {repo._schema}.{table} "
            "WHERE market_date = ANY(%s) GROUP BY market_date, ticker",
            (list(dates),),
        )
        have = {(r[0], r[1].upper()) for r in cur.fetchall()}
    return [
        (d, t) for d in dates for t in tickers if (d, t.upper()) not in have
    ]


def _weekdays(start: _date, end: _date) -> list[_date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--max-tickers", type=int, default=None)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()
    if not args.confirm:
        print("refusing to run without --confirm (UW-bound)")
        return 2

    s = Settings.from_env()
    repo = Repository(psycopg.connect(s.db_dsn()), schema=s.db_schema)
    client = UwClient(
        api_key=s.api_key.get_secret_value(),
        base_url=s.base_url,
        timeout=s.request_timeout_seconds,
    )
    tickers = [c.ticker for c in repo.list_watchlist_cards()]
    if args.max_tickers:
        tickers = tickers[: args.max_tickers]
    dates = _weekdays(_date.fromisoformat(args.start), _date.fromisoformat(args.end))
    pairs = missing_pairs(repo, "oi_by_strike", dates, tickers)
    logger.info("replay: %d (date,ticker) pairs to fill", len(pairs))

    ok = failed = 0
    for d, t in pairs:
        try:
            run_single_stock(t, client, repo, market_date=d)
            repo.conn.commit()
            ok += 1
        except Exception as exc:  # noqa: BLE001
            repo.conn.rollback()
            failed += 1
            logger.warning("replay failed %s %s: %r", d, t, exc)
    logger.info("replay complete: ok=%d failed=%d", ok, failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/scripts/test_pipeline_replay_backfill.py -v`
Expected: PASS

- [ ] **Step 5: Single-ticker smoke on the mini, then verify the dates**

```bash
ssh macmini 'export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin
docker exec argon-worker-uw-0-1 /app/.venv/bin/python \
  scripts/backfill/pipeline_replay_backfill.py \
    --start 2026-08-12 --end 2026-08-12 --max-tickers 1 --confirm'
```

```sql
SELECT market_date, count(*) FROM uw_scan.oi_by_strike
 WHERE market_date = '2026-08-12' GROUP BY 1;
SELECT count(*) FROM uw_scan.flow_events
 WHERE created_at::date = '2026-08-12';   -- MUST stay 0: refused dataset
```

Expected: `oi_by_strike` gains rows dated 2026-08-12; `flow_events` count unchanged. **If `flow_events` grew, stop — the refusal guard is not wired and rows are being fabricated.**

- [ ] **Step 6: Commit**

```bash
git add scripts/backfill/pipeline_replay_backfill.py tests/unit/scripts/test_pipeline_replay_backfill.py
git commit -m "feat(backfill): resumable pipeline replay CLI for historical sessions"
```

---

### Task 6: Date-parameterize the cockpit snapshot

`option_chain_per_strike`, `iv_rank_history` and `matrix_state_snapshots` are written by `cockpit_daily_snapshot`, which already computes a `market_date` internally but exposes no parameter. It covers only the four cockpit tickers, so this is a much smaller change than Task 4.

**Files:**
- Modify: `src/uw_scan/worker/jobs/cockpit_daily_snapshot.py:52` (signature) and its internal `market_date` derivation
- Test: `tests/unit/test_cockpit_daily_snapshot_market_date.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `cockpit_daily_snapshot(*, repo, client, settings, market_date: _date | None = None) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_cockpit_daily_snapshot_market_date.py
from datetime import date
from unittest.mock import MagicMock

from uw_scan.worker.jobs import cockpit_daily_snapshot as mod


def test_market_date_flows_into_chain_persist(monkeypatch):
    seen: dict = {}

    # NOTE: _persist_option_chain_per_strike is KEYWORD-ONLY and its rows arg is
    # named `contracts` (not `rows`) — see cockpit_daily_snapshot.py:250.
    def _spy(*, repo, ticker, market_date, contracts, oi_band_pct, oi_max_dte):
        seen["d"] = market_date

    monkeypatch.setattr(mod, "_persist_option_chain_per_strike", _spy)
    repo = MagicMock()
    repo.try_advisory_lock.return_value = True
    mod.cockpit_daily_snapshot(
        repo=repo, client=MagicMock(), settings=MagicMock(), market_date=date(2026, 8, 12)
    )
    assert seen["d"] == date(2026, 8, 12)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_cockpit_daily_snapshot_market_date.py -v`
Expected: FAIL — unexpected keyword argument `market_date`

- [ ] **Step 3: Write minimal implementation**

```python
def cockpit_daily_snapshot(
    *, repo: Repository, client: UwClient, settings: Settings,
    market_date: _date | None = None,
) -> None:
    """Snapshot greeks/exposures/skew/IV/RV for every Cockpit ticker.

    ``market_date`` replays a past session (outage repair); ``None`` is the live
    nightly path and is unchanged.
    """
```

Replace the internal date derivation with `market_date or <existing expression>` and pass `market_date=market_date` to the fetchers from Task 3 that this job calls.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_cockpit_daily_snapshot_market_date.py -v`
Expected: PASS

- [ ] **Step 5: Backfill the four cockpit tickers for the outage window**

```bash
ssh macmini 'export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin
docker exec argon-worker-uw-0-1 /app/.venv/bin/python -c "
import psycopg
from datetime import date
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.api.client import UwClient
from uw_scan.worker.jobs.cockpit_daily_snapshot import cockpit_daily_snapshot
s=Settings.from_env(); repo=Repository(psycopg.connect(s.db_dsn()), schema=s.db_schema)
cl=UwClient(api_key=s.api_key.get_secret_value(), base_url=s.base_url, timeout=s.request_timeout_seconds)
for d in (11,12,13,14):
    cockpit_daily_snapshot(repo=repo, client=cl, settings=s, market_date=date(2026,8,d))
    repo.conn.commit(); print(\"done\", d)
"'
```

- [ ] **Step 6: Commit**

```bash
git add src/uw_scan/worker/jobs/cockpit_daily_snapshot.py tests/unit/test_cockpit_daily_snapshot_market_date.py
git commit -m "feat(cockpit): optional market_date for historical snapshot replay"
```

---

### Task 7: Run the full backfill and re-derive dependents

**Files:** none modified — this is the execution and verification task.

**Interfaces:**
- Consumes: Tasks 1, 5, 6.
- Produces: a verified-clean outage window.

- [ ] **Step 1: Run the replay for the full window**

Budget: the replay is ~15 UW calls per (ticker, date). 170 tickers × 4 dates ≈ **10,200 calls**. Check headroom first — `uw rate state` is logged on every call; the daily ceiling is 120,000 and resets at 00:00 UTC.

```bash
ssh macmini 'export PATH=$PATH:/usr/local/bin:/opt/homebrew/bin
docker exec -d argon-worker-uw-0-1 sh -c "/app/.venv/bin/python \
  scripts/backfill/pipeline_replay_backfill.py --start 2026-08-11 --end 2026-08-14 --confirm \
  > /tmp/replay.log 2>&1"'
```

- [ ] **Step 2: Re-derive the tables computed FROM the replayed inputs**

`skew_analytics_snapshot`, `skew_swing_greeks`, `vanna_signals` and `charm_signals` are derived from the now-restored chain data. Re-run the same entry points the scheduler uses:

```bash
docker exec argon-worker-massive-0-1 /app/.venv/bin/python -c "
import psycopg
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.skew_analytics import nightly_skew_analytics_rollup
s=Settings.from_env(); repo=Repository(psycopg.connect(s.db_dsn()), schema=s.db_schema)
nightly_skew_analytics_rollup(repo=repo); repo.conn.commit(); print('rollup done')"
```

- [ ] **Step 3: Verify coverage per table**

```sql
SELECT 'oi_by_strike' t, market_date, count(DISTINCT ticker) FROM uw_scan.oi_by_strike
  WHERE market_date BETWEEN '2026-08-11' AND '2026-08-14' GROUP BY 1,2
UNION ALL SELECT 'iv_term_snapshots', market_date, count(DISTINCT ticker) FROM uw_scan.iv_term_snapshots
  WHERE market_date BETWEEN '2026-08-11' AND '2026-08-14' GROUP BY 1,2
UNION ALL SELECT 'exposures_summary', market_date, count(DISTINCT ticker) FROM uw_scan.exposures_summary
  WHERE market_date BETWEEN '2026-08-11' AND '2026-08-14' GROUP BY 1,2
ORDER BY 1,2;
```

Expected: each table shows four dates with ticker counts near 170.

- [ ] **Step 4: Verify NO fabrication occurred**

```sql
SELECT count(*) FROM uw_scan.flow_events        WHERE created_at::date BETWEEN '2026-08-11' AND '2026-08-14';
SELECT count(*) FROM uw_scan.short_interest_snapshots WHERE snapshot_date BETWEEN '2026-08-11' AND '2026-08-14';
SELECT count(*) FROM uw_scan.options_volume_daily     WHERE trade_date BETWEEN '2026-08-11' AND '2026-08-14';
```

Expected: **all three return 0.** A non-zero count means a refused dataset was written and the run must be rolled back for those dates.

- [ ] **Step 5: Sanity-check values, not just presence**

Compare the replayed sessions against the known-good 2026-08-10 baseline — row counts within the same order of magnitude and IV distributions in family:

```sql
SELECT market_date, count(*) rows, round(avg(call_iv)::numeric,4) avg_iv, min(call_iv), max(call_iv)
  FROM uw_scan.iv_term_snapshots
 WHERE market_date BETWEEN '2026-08-07' AND '2026-08-14' GROUP BY 1 ORDER BY 1;
```

Expected: 08-11→14 sit in the same range as 08-07 and 08-10. A day that is an order of magnitude off means a truncated or mis-dated fetch — investigate before accepting.

- [ ] **Step 6: Re-run the freshness monitor and confirm the frozen count dropped**

```bash
docker exec argon-worker-massive-0-1 /app/.venv/bin/python -c "
import psycopg
from datetime import date
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.data_freshness_monitor import data_freshness_monitor
s=Settings.from_env(); repo=Repository(psycopg.connect(s.db_dsn()), schema=s.db_schema)
r=data_freshness_monitor(repo=repo, settings=s, today=date.today()); repo.conn.commit()
print('frozen:', r.get('frozen'))"
```

Expected: frozen count falls from 26 toward ~10 (the residue being the lake-blocked, pre-existing, and permanently-refused tables).

- [ ] **Step 7: Update CHANGELOG and open the PR**

```bash
# add an [Unreleased] entry describing the replay capability and the refusal policy
git add CHANGELOG.md
git commit -m "docs(changelog): historical replay backfill"
git push -u origin feat/historical-replay-backfill
gh pr create --title "feat: historical replay backfill for deep-scan tables" --body "$(cat <<'EOF'
Adds an optional `market_date` to `run_single_stock` so a past session can be
re-fetched from UW at its true date, healing the deep-scan tables lost in the
2026-08-11..14 outage.

Datasets whose UW endpoint ignores `date` (`flow_events`, `short_interest_snapshots`,
`options_volume_daily`) are refused in code — writing them under a historical stamp
would present today's numbers as history. Evidence and measurement date are recorded
in `uw_scan/pipeline_replay_policy.py`.

`market_date=None` is the live nightly path and is unchanged.

Plan: docs/superpowers/plans/2026-08-16-historical-replay-backfill.md
EOF
)"
```

---

## Out of Scope (and why)

| Table | Blocker | Note |
|---|---|---|
| `flow_events`, `flow_alerts_daily_rollup` | UW endpoint ignores `date` | Permanently unrecoverable. Refused in code (Task 2). |
| `short_interest_snapshots`, `uw_positioning` | `/shorts/{ticker}/data` ignores `date` | Same. `uw_positioning` needs its own probe — it is fed by `/interest-float/v2`, untested here. |
| `options_volume_daily` | `/options-volume` ignores `date` | Same. |
| `option_intraday_buckets` | needs `oi_change_events` mover sessions | Becomes recoverable AFTER Task 7 restores `oi_change_events`; re-run `scripts/backfill/intraday_buckets_backfill.py --all --since 2026-08-11 --confirm` then. |
| `vcg_snapshots`, `index_ohlc_daily`, HYG/JNK/LQD | market-data-warehouse lake still recovering | Not an argon bug. Re-run `vol_index_lake_sync` + `credit_etf_lake_sync` + `vcg.recover_recent_gaps` once the lake catches up. |
| `grg_snapshots` | `scanners/grg.run` has no `as_of` | Small follow-up; UW's `/greek-exposure` series makes it feasible. Deliberately deferred to keep this plan one subsystem. |
| `exchange_inventory_daily` | CME returns 403 (blocks scraping) since 2026-06-01 | Pre-existing, unrelated to the outage. |
| `iv_source_validation` | IB canary, ~100-line IB cap, no historical mode | Low value; would need xenon/IB historical greeks. |

## Risks

1. **UW retention closes.** The window that makes this possible is finite. Probes on 2026-08-16 succeeded for 2026-08-12; the surface archive suggests ~180 days, but that is not verified for these endpoints. **Run Task 1 and Task 5's smoke early** to confirm the window is still open before investing in Tasks 3–4.
2. **A refused dataset slips through.** Mitigated by Task 5 Step 5 and Task 7 Step 4, which assert zero rows for all three refused tables. Treat a non-zero count as a stop-the-line defect.
3. **Live path regression.** Every pipeline task ends with the full unit + integration suite. `market_date=None` must stay byte-identical.
4. **Scanner pollution.** Replaying scanner detectors would emit past-dated candidates into a live decision surface. Task 4 skips them under replay; verify `scanner_candidate_snapshots` gains no rows for 08-11→14.
