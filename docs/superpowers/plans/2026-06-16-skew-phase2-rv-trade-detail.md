# Skew Phase-2 (Increment-1) Implementation Plan — RV-trigger research + concrete strike-by-delta detail

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two coupled, independently-testable increments on the shipped V1 Skew tab: (1b) turn the descriptive RR mean-reversion into a *persisted, tail-split, walk-forward-gated* verdict store + research note; (1a) when V1's already-gated `directional_lean` is non-neutral, enrich it with concrete **strike-by-delta** legs + suggested DTE, defined-risk and earnings-blocked, surfaced in the Signal Detail card.

**Architecture:** Backend-first. 1b extends the existing `run_skew_markout` harness (no new live data) and adds one idempotent table. 1a adds one repo read (per-strike greeks already persisted in `exposures_by_expiry_strike`), one pure deriver (strike selection by target delta), wires it into the pure `build_skew_snapshot_row` via callers that fetch greeks, surfaces it through `read_json` + typed models + the React card. No new feed, no Black-Scholes recompute, no spread-P&L/net-of-cost claim (data-blocked — see hardened design doc §"Hardening review").

**Tech Stack:** Python 3.13 (`uv` only), FastAPI + Pydantic v2, psycopg 3, pandas (markout), Next.js 16 + React 19 + TypeScript, Vitest + Playwright, pytest + pytest-postgresql. Types flow API → `web/lib/types.ts` via `npm run gen:types`.

**Authoritative scope source:** `docs/research/skew-mean-reversion-trade-structures-phase2.md` → `## Hardening review (2026-06-16)`. Increment-1 = "concretize the gated read + RR-trigger research". Everything else (net-of-cost validation, delta-hedge helper, Layer-2 cross-pillar gate) is explicitly split out.

**Standing rules in force:** uv only; persist analytical results to Postgres; no naked shorts (defined-risk only); idempotent migrations (`IF NOT EXISTS`); CI Guardrail 2 (every `except` must `log...repr(exc)`/`.exception`/`raise`); `Decimal` over float for price/IV/greeks; `<500` lines/file target; never commit without the user's request (milestone commits are pre-authorized for this build); never `git push origin main`.

---

## File Structure

**New files:**
- `src/uw_scan/storage/migrations/074_skew_phase2.sql` — `skew_rv_reversion_verdicts` table (idempotent).
- `tests/integration/reports/test_skew_rv_markout.py` — RV markout: tail-split keys, expected-sign gate, walk-forward holdout, idempotency.
- `tests/unit/cards/test_skew_structure_legs.py` — pure strike-selection deriver tests.
- `docs/research/skew-rr-reversion-trigger-2026-06.md` — research note; the empirical table is filled during execution by running the harness on `option_wizard_local`.

**Modified files:**
- `src/uw_scan/reports/skew_markout.py` — add `tail` dim + walk-forward + write RV verdicts; return RV stats.
- `src/uw_scan/storage/skew.py` (`_SkewMixin`) — `upsert_skew_rv_reversion_verdict` + `get_skew_rv_reversion_verdict`.
- `src/uw_scan/storage/options.py` (`_OptionsMixin`) — `fetch_latest_exposures_by_strike` (read `exposures_by_expiry_strike`).
- `src/uw_scan/cards/skew_first_principles.py` — `structure_family()` (single source for the structure descriptor), refactor `_express_structure()` to derive its string from it, `select_structure_legs()` (pure strike-by-delta picker).
- `src/uw_scan/models/skew.py` — `SkewStructureLeg`, `SkewStructureDetail`; add `structure_detail` to `SkewDirectionalLean`.
- `src/uw_scan/models/__init__.py` — export the two new models.
- `src/uw_scan/reports/skew_analytics.py` — accept `exposure_rows`, compute `structure_detail` when lean non-neutral, map into `SkewDirectionalLean`.
- `src/uw_scan/worker/jobs/skew_analytics.py` — nightly rollup fetches latest exposures per ticker and passes them through; backfill passes `None`.
- `tests/unit/cards/test_skew_first_principles.py` — `structure_family`/`_express_structure` parity.
- `tests/unit/reports/test_skew_snapshot_row.py` — structure_detail present when non-neutral + exposures, absent otherwise.
- `tests/integration/reports/test_skew_markout.py` — keep green after signature/return changes.
- `web/lib/types.ts` — regenerated.
- `tests/integration/api/openapi.snapshot.json` — regenerated.
- `web/components/stock/panels/SkewSignalDetail.tsx` — render structure legs when present.
- `web/tests/unit/SkewSignalDetail.test.tsx` — structure-detail render + absence.
- `web/tests/e2e/skew-tab.spec.ts` — assert structure block when a non-neutral name is shown; tolerate NEUTRAL.

**Milestone → commit seams:**
- **M0** docs: hardened design doc + this plan.
- **M1** 1b backend: migration + storage + markout tail-split/walk-forward + tests.
- **M2** 1a backend: greeks read + deriver + models + assembler/worker wiring + tests.
- **M3** 1a contract+UI: gen:types + openapi snapshot + React card + vitest + e2e.
- **M4** research note (run harness) + full verification.

---

## Task 0: Milestone M0 — commit hardened design doc + this plan

**Files:**
- Modify (already edited): `docs/research/skew-mean-reversion-trade-structures-phase2.md`
- Create: `docs/superpowers/plans/2026-06-16-skew-phase2-rv-trade-detail.md` (this file)

- [ ] **Step 1: Verify the hardening edits are present**

Run: `grep -c "Hardening review (2026-06-16)" docs/research/skew-mean-reversion-trade-structures-phase2.md`
Expected: `1`

- [ ] **Step 2: Commit docs**

```bash
git add docs/research/skew-mean-reversion-trade-structures-phase2.md docs/superpowers/plans/2026-06-16-skew-phase2-rv-trade-detail.md
git commit -m "docs(skew): harden Phase-2 design + increment-1 plan (RV-trigger + strike detail)"
```

---

## Task 1: Migration — `skew_rv_reversion_verdicts` (M1)

**Files:**
- Create: `src/uw_scan/storage/migrations/074_skew_phase2.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 074_skew_phase2.sql — Phase-2 increment-1.
-- skew_rv_reversion_verdicts: per (asset_class, deviation_class, tail) conclusion of
-- whether the 25d RR mean-reverts (descriptive RV axis, distinct from the directional
-- skew_directional_verdicts). Gated by a time-ordered walk-forward holdout on the RR
-- history (the only OOS test the ~1yr RR data supports). NO spread-P&L / net-of-cost.
-- Idempotent.

SET search_path TO uw_scan, public;

CREATE TABLE IF NOT EXISTS uw_scan.skew_rv_reversion_verdicts (
  asset_class          TEXT NOT NULL,     -- index_macro | sector_etf | credit | single_name
  deviation_class      TEXT NOT NULL,     -- RICH | CHEAP | NORMAL
  tail                 TEXT NOT NULL,     -- put_skew | call_skew | flat
  verdict              TEXT NOT NULL,     -- REVERTS | NONE
  mean_drr             NUMERIC,           -- mean forward ΔRR (T+20) over the full sample
  mean_drr_holdout     NUMERIC,           -- mean forward ΔRR over the time-ordered holdout
  n                    INTEGER,
  n_holdout            INTEGER,
  survives_walkforward BOOLEAN,           -- holdout preserves the full-sample sign + magnitude
  survives_window_gate BOOLEAN,           -- no calendar quarter reverses the aggregate with larger magnitude
  as_of                DATE,
  inserted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (asset_class, deviation_class, tail)
);

COMMENT ON TABLE uw_scan.skew_rv_reversion_verdicts
  IS 'Per-bucket RR mean-reversion conclusion (descriptive RV axis). REVERTS requires expected sign (CHEAP->+, RICH->-), |mean| over threshold, n over min, a time-ordered walk-forward holdout that preserves sign+magnitude, AND a per-calendar-quarter catastrophic-degradation gate (no sub-window reverses the aggregate with larger magnitude). In-sample over a single ~1yr window; NOT a P&L claim.';
```

- [ ] **Step 2: Apply against a scratch test DB and verify idempotency**

Run: `bash scripts/migrate.sh && bash scripts/migrate.sh`
Expected: both runs succeed; second run is a no-op (no errors). If `migrate.sh` targets local, confirm `option_wizard_local`; the table now exists.

- [ ] **Step 3: Commit** (committed together at end of M1, Task 4 Step 5.)

---

## Task 2: Storage — RV reversion verdict upsert/get (M1)

**Files:**
- Modify: `src/uw_scan/storage/skew.py` (`_SkewMixin`)
- Test: `tests/integration/storage/test_skew_storage.py` (extend)

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/storage/test_skew_storage.py`:

```python
def test_rv_reversion_verdict_roundtrip(repo):
    from datetime import date
    repo.upsert_skew_rv_reversion_verdict(
        asset_class="single_name",
        deviation_class="CHEAP",
        tail="put_skew",
        verdict="REVERTS",
        mean_drr=0.0514,
        mean_drr_holdout=0.041,
        n=1472,
        n_holdout=520,
        survives_walkforward=True,
        survives_window_gate=True,
        as_of=date(2026, 6, 16),
    )
    repo.conn.commit()
    got = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert got is not None
    assert got["verdict"] == "REVERTS"
    assert got["survives_walkforward"] is True
    assert got["survives_window_gate"] is True
    # upsert is idempotent on the PK
    repo.upsert_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew",
        verdict="NONE", mean_drr=0.0, mean_drr_holdout=0.0, n=1, n_holdout=0,
        survives_walkforward=False, survives_window_gate=False, as_of=date(2026, 6, 16),
    )
    repo.conn.commit()
    got2 = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert got2["verdict"] == "NONE"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/integration/storage/test_skew_storage.py::test_rv_reversion_verdict_roundtrip -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'upsert_skew_rv_reversion_verdict'`.

- [ ] **Step 3: Implement the two methods**

Add to `_SkewMixin` in `src/uw_scan/storage/skew.py` (after `get_skew_directional_verdict`):

```python
    def upsert_skew_rv_reversion_verdict(
        self,
        *,
        asset_class: str,
        deviation_class: str,
        tail: str,
        verdict: str,
        mean_drr: Any,
        mean_drr_holdout: Any,
        n: int,
        n_holdout: int,
        survives_walkforward: bool,
        survives_window_gate: bool,
        as_of: _date,
    ) -> None:
        sql = (
            f"INSERT INTO {self._schema}.skew_rv_reversion_verdicts "
            "(asset_class, deviation_class, tail, verdict, mean_drr, mean_drr_holdout, "
            " n, n_holdout, survives_walkforward, survives_window_gate, as_of, inserted_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
            "ON CONFLICT (asset_class, deviation_class, tail) DO UPDATE SET "
            "verdict=EXCLUDED.verdict, mean_drr=EXCLUDED.mean_drr, "
            "mean_drr_holdout=EXCLUDED.mean_drr_holdout, n=EXCLUDED.n, "
            "n_holdout=EXCLUDED.n_holdout, "
            "survives_walkforward=EXCLUDED.survives_walkforward, "
            "survives_window_gate=EXCLUDED.survives_window_gate, "
            "as_of=EXCLUDED.as_of, inserted_at=now()"
        )
        with self._conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    asset_class,
                    deviation_class,
                    tail,
                    verdict,
                    mean_drr,
                    mean_drr_holdout,
                    n,
                    n_holdout,
                    survives_walkforward,
                    survives_window_gate,
                    as_of,
                ),
            )

    def get_skew_rv_reversion_verdict(
        self, *, asset_class: str, deviation_class: str, tail: str
    ) -> dict[str, Any] | None:
        sql = (
            f"SELECT * FROM {self._schema}.skew_rv_reversion_verdicts "
            "WHERE asset_class=%s AND deviation_class=%s AND tail=%s"
        )
        with self._conn.cursor() as cur:
            cur.execute(sql, (asset_class, deviation_class, tail))
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description or []]
            return dict(zip(cols, row, strict=False))
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/integration/storage/test_skew_storage.py::test_rv_reversion_verdict_roundtrip -v`
Expected: PASS.

---

## Task 3: Markout — tail-split + walk-forward + write RV verdicts (M1)

**Files:**
- Modify: `src/uw_scan/reports/skew_markout.py`
- Test: `tests/integration/reports/test_skew_rv_markout.py` (create)

**Background:** `run_skew_markout` already accumulates `meanrev[(asset_class, deviation_class)] = [ΔRR,...]` (lines ~92-100, 146-149). We (a) add `tail` from `sign(rr_25d)`, (b) keep `market_date` per obs for time-ordering, (c) compute a time-ordered holdout, (d) write RV verdicts. The directional (secondary) path is untouched.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/reports/test_skew_rv_markout.py`. Mirror the `repo` fixture + seeding style of `tests/integration/reports/test_skew_markout.py` (verified: it uses the session `seeded_db_empty_cards` fixture and raw-cursor inserts; there is NO `seed_*` repo helper). Full file:

```python
from datetime import date, timedelta

import pytest

from uw_scan.reports.skew_markout import (
    _expected_drr_sign,
    _rv_walkforward,
    run_skew_markout,
)


@pytest.fixture
def repo(seeded_db_empty_cards):
    return seeded_db_empty_cards


def _seed_cheap_reverting_bucket(repo, ticker="QCOM"):
    """A single_name CHEAP/put_skew bucket whose 25d RR climbs (re-richens) across the
    whole window: forward ΔRR(T+20) is positive everywhere, so the time-ordered holdout
    survives. Seeds BOTH the snapshot anchors AND risk_reversal_skew_history (the forward
    RR series skew_markout._rr_series reads, delta=25). RR stays > 0 so every anchor
    buckets as tail=put_skew."""
    base = date(2025, 1, 2)
    snaps = []
    for i in range(80):
        d = base + timedelta(days=i)
        rr = 0.02 + 0.002 * i  # +0.02 .. +0.178, all put_skew, monotonically richening
        snaps.append({
            "ticker": ticker, "market_date": d, "basis": "eod",
            "spot": 100.0 + i, "rr_25d": rr, "skew_25d": rr,
            "deviation_class": "CHEAP", "skew_term_class": "flat",
            "drive_class": "STRUCTURAL", "asset_class": "single_name",
            "regime": "LOW_VOL", "borrow_flag": "normal",
        })
    repo.upsert_skew_analytics_snapshots(snaps)
    with repo.conn.cursor() as cur:
        for i in range(80):
            d = base + timedelta(days=i)
            rr = 0.02 + 0.002 * i
            cur.execute(
                "INSERT INTO uw_scan.risk_reversal_skew_history "
                "(ticker, market_date, delta, expiry, risk_reversal) "
                "VALUES (%s, %s, 25, %s, %s) ON CONFLICT DO NOTHING",
                (ticker, d, base + timedelta(days=40), rr),
            )
    repo.conn.commit()


def test_rv_markout_writes_reverting_verdict(repo):
    _seed_cheap_reverting_bucket(repo)
    out = run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)
    assert "rv_reversion" in out and out["rv_verdicts_written"] >= 1
    v = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert v is not None
    assert v["verdict"] == "REVERTS"
    assert float(v["mean_drr"]) > 0          # CHEAP re-richens => positive ΔRR
    assert v["survives_walkforward"] is True
    assert v["survives_window_gate"] is True  # single-quarter seed: no sub-window blowup


def test_rv_markout_idempotent(repo):
    _seed_cheap_reverting_bucket(repo)
    run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)
    run_skew_markout(repo=repo, min_n=1, sep_threshold=0.005)  # second run = no-op upsert
    v = repo.get_skew_rv_reversion_verdict(
        asset_class="single_name", deviation_class="CHEAP", tail="put_skew"
    )
    assert v["verdict"] == "REVERTS"
```

NOTE (verified Pass-1): `run_skew_markout`'s `min_n` only gates the DIRECTIONAL path; the RV path uses the module constants `RV_MIN_N=30` etc., so n=60 here passes regardless of `min_n=1`.

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/integration/reports/test_skew_rv_markout.py -v`
Expected: FAIL — `KeyError: 'rv_reversion'` (and no verdict written).

- [ ] **Step 3: Implement the walk-forward helper + tail key + verdict writes**

In `src/uw_scan/reports/skew_markout.py`:

(a) Add the constants + a pure helper near the top (after `HORIZON`):

```python
RV_HOLDOUT_FRAC = 0.40        # time-ordered tail fraction held out for OOS check
RV_MIN_N = 30                 # min obs to even consider an RV verdict
RV_SEP_THRESHOLD = 0.005      # |mean ΔRR| floor (full sample)
RV_HOLDOUT_THRESHOLD = 0.003  # |mean ΔRR| floor on the holdout


def _expected_drr_sign(deviation_class: str) -> int:
    """CHEAP re-richens (+), RICH flattens (-), else no directional reversion claim."""
    if deviation_class == "CHEAP":
        return 1
    if deviation_class == "RICH":
        return -1
    return 0


def _rv_survives_window_gate(obs: list[dict], overall_mean: float) -> bool:
    """Per-calendar-quarter catastrophic-degradation gate (mirrors the directional
    _survives_window_gate; standing rule: feedback_per_regime_catastrophic_gate).
    Fail if ANY quarter's mean ΔRR reverses the aggregate sign with LARGER magnitude —
    i.e. the aggregate is hiding a sub-window blowup. obs items carry 'drr' + 'market_date'."""
    if abs(overall_mean) < 1e-9:
        return False
    by_q: dict[tuple, list[float]] = {}
    for o in obs:
        d = o["market_date"]
        by_q.setdefault((d.year, (d.month - 1) // 3), []).append(o["drr"])
    for vals in by_q.values():
        if not vals:
            continue
        m = sum(vals) / len(vals)
        if m * overall_mean < 0 and abs(m) > abs(overall_mean):
            return False
    return True


def _rv_walkforward(obs: list[dict], expected_sign: int) -> dict:
    """obs: [{'drr': float, 'market_date': date}], any order. Returns the verdict dict.
    REVERTS requires expected sign + magnitude (full & holdout) AND the quarterly
    catastrophic-degradation gate. Holdout = the latest RV_HOLDOUT_FRAC of obs by
    market_date (time-ordered, no leak)."""
    n = len(obs)
    if n < RV_MIN_N or expected_sign == 0:
        return {"verdict": "NONE", "mean_drr": None, "mean_drr_holdout": None,
                "n": n, "n_holdout": 0, "survives_walkforward": False,
                "survives_window_gate": False}
    ordered = sorted(obs, key=lambda o: o["market_date"])
    cut = int(round(n * (1.0 - RV_HOLDOUT_FRAC)))
    holdout = ordered[cut:]
    mean_full = sum(o["drr"] for o in ordered) / n
    mean_hold = (sum(o["drr"] for o in holdout) / len(holdout)) if holdout else 0.0
    sign_ok = (mean_full * expected_sign > 0) and (mean_hold * expected_sign > 0)
    mag_ok = abs(mean_full) >= RV_SEP_THRESHOLD and abs(mean_hold) >= RV_HOLDOUT_THRESHOLD
    survives_wf = bool(sign_ok and mag_ok)
    survives_window = _rv_survives_window_gate(ordered, mean_full)
    reverts = bool(survives_wf and survives_window)
    return {"verdict": "REVERTS" if reverts else "NONE",
            "mean_drr": mean_full, "mean_drr_holdout": mean_hold,
            "n": n, "n_holdout": len(holdout),
            "survives_walkforward": survives_wf,
            "survives_window_gate": survives_window}
```

(b) Change the meanrev accumulation to carry `tail` + `market_date`. Replace the meanrev block in the Pass-1 loop:

```python
            if fwd_rr is not None:
                tail = "put_skew" if float(rr0) > 0 else (
                    "call_skew" if float(rr0) < 0 else "flat")
                meanrev[(s["asset_class"], s["deviation_class"], tail)].append(
                    {"drr": fwd_rr - float(rr0), "market_date": s["market_date"]}
                )
```

(c) After the directional-verdict write loop (after `written += 1`), add the RV verdict write loop and include RV stats in the return dict:

```python
    rv_written = 0
    rv_report = {}
    for (asset_class, deviation_class, tail), drr_obs in meanrev.items():
        wf = _rv_walkforward(drr_obs, _expected_drr_sign(deviation_class))
        repo.upsert_skew_rv_reversion_verdict(
            asset_class=asset_class,
            deviation_class=deviation_class,
            tail=tail,
            verdict=wf["verdict"],
            mean_drr=wf["mean_drr"],
            mean_drr_holdout=wf["mean_drr_holdout"],
            n=wf["n"],
            n_holdout=wf["n_holdout"],
            survives_walkforward=wf["survives_walkforward"],
            survives_window_gate=wf["survives_window_gate"],
            as_of=today,
        )
        rv_written += 1
        rv_report[f"{asset_class}/{deviation_class}/{tail}"] = wf
```

(d) Update `mean_reversion` (now keyed by the 3-tuple) and the return dict. Replace the old `mean_reversion = {...}` comprehension and the `return {...}`:

```python
    mean_reversion = {
        f"{a}/{d}/{t}": {
            "mean_dRR": (sum(o["drr"] for o in v) / len(v) if v else None),
            "n": len(v),
        }
        for (a, d, t), v in meanrev.items()
    }
    repo.conn.commit()
    log.info(
        "run_skew_markout wrote %d directional + %d rv verdicts over %d snapshots",
        written, rv_written, len(snaps),
    )
    return {
        "verdicts_written": written,
        "rv_verdicts_written": rv_written,
        "snapshots": len(snaps),
        "mean_reversion": mean_reversion,   # PRIMARY hypothesis, descriptive
        "rv_reversion": rv_report,          # PRIMARY hypothesis, now gated + walk-forward
    }
```

- [ ] **Step 4: Run the new + existing markout tests**

Run: `uv run pytest tests/integration/reports/test_skew_rv_markout.py tests/integration/reports/test_skew_markout.py -v`
Expected: all PASS. (If `test_skew_markout.py` asserted on the old 2-tuple `mean_reversion` keys, update those assertions to the 3-tuple form — that is the only allowed edit there.)

- [ ] **Step 5: Add a unit test for the pure walk-forward helper**

Append to `tests/integration/reports/test_skew_rv_markout.py` (pure, no DB; `_rv_walkforward`/`_expected_drr_sign`/`date` are already imported at the top of the file):

```python
def test_walkforward_rejects_when_holdout_flips():
    # full-sample positive but the recent holdout goes negative => NONE
    obs = [{"drr": 0.02, "market_date": date(2025, 1, 1) + timedelta(days=i)}
           for i in range(40)]
    obs += [{"drr": -0.03, "market_date": date(2025, 3, 1) + timedelta(days=i)}
            for i in range(40)]
    out = _rv_walkforward(obs, _expected_drr_sign("CHEAP"))
    assert out["verdict"] == "NONE"
    assert out["survives_walkforward"] is False


def test_walkforward_skips_normal_and_small_n():
    assert _rv_walkforward([], _expected_drr_sign("NORMAL"))["verdict"] == "NONE"
    tiny = [{"drr": 0.05, "market_date": date(2025, 1, 1)}]
    assert _rv_walkforward(tiny, _expected_drr_sign("CHEAP"))["verdict"] == "NONE"


def test_walkforward_rejects_when_a_quarter_blows_up():
    # full-sample AND holdout positive, but Q2 reverses harder than the aggregate ->
    # catastrophic-degradation gate fails -> NONE (mirrors the directional AC-F4 gate).
    obs = [{"drr": 0.05, "market_date": date(2025, 1, 1) + timedelta(days=i)}
           for i in range(40)]                                            # Q1 +0.05
    obs += [{"drr": -0.20, "market_date": date(2025, 4, 1) + timedelta(days=i)}
            for i in range(10)]                                           # Q2 big negative
    obs += [{"drr": 0.05, "market_date": date(2025, 7, 1) + timedelta(days=i)}
            for i in range(40)]                                           # Q3 +0.05 (holdout)
    out = _rv_walkforward(obs, _expected_drr_sign("CHEAP"))
    assert out["survives_walkforward"] is True      # holdout (Q3) is clean
    assert out["survives_window_gate"] is False      # Q2 blowup caught
    assert out["verdict"] == "NONE"
```

Run: `uv run pytest tests/integration/reports/test_skew_rv_markout.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit M1**

```bash
git add src/uw_scan/storage/migrations/074_skew_phase2.sql src/uw_scan/storage/skew.py \
        src/uw_scan/reports/skew_markout.py \
        tests/integration/storage/test_skew_storage.py \
        tests/integration/reports/test_skew_rv_markout.py \
        tests/integration/reports/test_skew_markout.py
git commit -m "feat(skew): RR mean-reversion verdict store — tail-split + walk-forward gate"
```

---

## Task 4: Storage — `fetch_latest_exposures_by_strike` (M2)

**Files:**
- Modify: `src/uw_scan/storage/options.py` (`_OptionsMixin`)
- Test: `tests/integration/storage/test_skew_storage.py` (extend) — OR `tests/integration/storage/test_options_*.py` if one exists for that table (check first).

**Background:** per-strike greeks with delta are persisted in `exposures_by_expiry_strike` (written by `insert_greek_exposure_rows`; cols `run_id, ticker, market_date, expiry, strike, dte, call_delta, put_delta, call_gex, put_gex, call_vanna, put_vanna, call_charm, put_charm`). There is no read for it yet.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/integration/storage/test_skew_storage.py` (verified Pass-1: that file already defines `def repo(seeded_db_empty_cards)`; the real run-creation helper is `insert_scan_run(ticker, notes="")`; `insert_greek_exposure_rows` maps `GreekExposureRow.date → market_date`). Add `from decimal import Decimal` and `from uw_scan import models` at the file's import block if absent:

```python
def test_fetch_latest_exposures_by_strike(repo):
    from datetime import date
    run_id = repo.insert_scan_run(ticker="QCOM")
    rows = [
        models.GreekExposureRow(
            date=date(2026, 6, 15), expiry=date(2026, 7, 18), strike=Decimal("95"),
            dte=33, call_delta=Decimal("0.62"), put_delta=Decimal("-0.38")),
        models.GreekExposureRow(
            date=date(2026, 6, 15), expiry=date(2026, 7, 18), strike=Decimal("90"),
            dte=33, call_delta=Decimal("0.74"), put_delta=Decimal("-0.26")),
    ]
    repo.insert_greek_exposure_rows(run_id, "QCOM", rows)
    repo.conn.commit()
    got = repo.fetch_latest_exposures_by_strike("QCOM", dte_max=70)
    assert len(got) == 2
    assert {r["strike"] for r in got} == {Decimal("95"), Decimal("90")}
    assert all("put_delta" in r and "dte" in r for r in got)


def test_fetch_latest_exposures_reads_only_the_newest_run(repo):
    from datetime import date
    ex = date(2026, 7, 18)
    # two runs on the SAME market_date — the later run (higher run_id) wins.
    old = repo.insert_scan_run(ticker="QCOM")
    repo.insert_greek_exposure_rows(old, "QCOM", [
        models.GreekExposureRow(date=date(2026, 6, 15), expiry=ex, strike=Decimal("70"),
                                dte=33, put_delta=Decimal("-0.20"))])
    new = repo.insert_scan_run(ticker="QCOM")
    repo.insert_greek_exposure_rows(new, "QCOM", [
        models.GreekExposureRow(date=date(2026, 6, 15), expiry=ex, strike=Decimal("95"),
                                dte=33, put_delta=Decimal("-0.26"))])
    repo.conn.commit()
    got = repo.fetch_latest_exposures_by_strike("QCOM", dte_max=70)
    assert {r["strike"] for r in got} == {Decimal("95")}   # only the newest run's chain
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/integration/storage/test_skew_storage.py::test_fetch_latest_exposures_by_strike -v`
Expected: FAIL — no `fetch_latest_exposures_by_strike`.

- [ ] **Step 3: Implement the read (latest market_date for the ticker, within DTE bound)**

Add to `_OptionsMixin` in `src/uw_scan/storage/options.py`:

```python
    def fetch_latest_exposures_by_strike(
        self, ticker: str, *, dte_max: int = 70
    ) -> list[dict[str, Any]]:
        """Per-strike greeks (incl. call/put delta) for the ticker's most recent
        exposures RUN, within `dte_max`. Keyed on max(run_id) — NOT max(market_date) —
        so two scan runs on the same date never stitch two chains together (the table
        is run-keyed: PK (run_id, ticker, expiry, strike)). Source for skew
        strike-by-delta selection. Ordered by expiry, strike ASC. Empty list if none."""
        sql = (
            "SELECT expiry, strike, dte, call_delta, put_delta "
            f"FROM {self._schema}.exposures_by_expiry_strike "
            "WHERE ticker = %s "
            "  AND run_id = ("
            f"    SELECT max(run_id) FROM {self._schema}.exposures_by_expiry_strike "
            "      WHERE ticker = %s) "
            "  AND (dte IS NULL OR dte <= %s) "
            "ORDER BY expiry ASC, strike ASC"
        )
        t = ticker.upper()
        with self._conn.cursor() as cur:
            cur.execute(sql, (t, t, dte_max))
            cols = [d.name for d in cur.description or []]
            return [dict(zip(cols, row, strict=False)) for row in cur.fetchall()]
```

Confirm `from typing import Any` is imported in `options.py` (it is used throughout; add if missing).

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/integration/storage/test_skew_storage.py::test_fetch_latest_exposures_by_strike -v`
Expected: PASS.

---

## Task 5: Models — `SkewStructureLeg` + `SkewStructureDetail` (M2)

**Files:**
- Modify: `src/uw_scan/models/skew.py`
- Modify: `src/uw_scan/models/__init__.py`
- Test: `tests/unit/test_models_exports.py` (already enforces export surface — no edit, must stay green)

- [ ] **Step 1: Add the models**

In `src/uw_scan/models/skew.py`, add before `class SkewDirectionalLean`:

```python
class SkewStructureLeg(_UwBase):
    action: str = ""          # BUY | SELL
    right: str = ""           # PUT | CALL
    strike: Decimal | None = None
    target_delta: Decimal | None = None   # the delta we aimed for (e.g. -0.25)
    actual_delta: Decimal | None = None    # delta of the chosen strike
    expiry: _date | None = None
    dte: int | None = None


class SkewStructureDetail(_UwBase):
    kind: str = ""            # put_debit_spread | call_debit_spread
    legs: list[SkewStructureLeg] = []
    dte_target: int | None = None
    status: str = "ready"     # ready | no_chain | suppressed
    note: str = ""            # e.g. "defined risk; exit before earnings 2026-07-18"
```

Add `structure_detail` to `SkewDirectionalLean`:

```python
class SkewDirectionalLean(_UwBase):
    lean: str = "NEUTRAL"
    confidence: str = "low"
    basis: str = ""
    express: str = ""
    structure_detail: SkewStructureDetail | None = None
```

Add both new classes to the `_preserve_public_module(...)` call at the bottom.

- [ ] **Step 2: Export from the package root**

In `src/uw_scan/models/__init__.py`, add `SkewStructureLeg` and `SkewStructureDetail` to the `.skew` import block and to `__all__` (keep alphabetical/grouped as the file does).

- [ ] **Step 3: Add an export-verification block (the existing test won't otherwise check the new models)**

`tests/unit/test_models_exports.py`'s `PUBLIC_MODEL_EXPORTS` is a hand-maintained subset; simply running it would NOT verify the new models. Append a dedicated block mirroring `test_new_exposure_models_exported` (verified to exist at lines 161-171):

```python
def test_new_skew_structure_models_exported():
    assert "SkewStructureLeg" in models.__all__
    assert "SkewStructureDetail" in models.__all__
    # _preserve_public_module rewrites __module__ so OpenAPI component names stay stable
    assert models.SkewStructureLeg.__module__ == "uw_scan.models"
    assert models.SkewStructureDetail.__module__ == "uw_scan.models"
```

Run: `uv run pytest tests/unit/test_models_exports.py -v`
Expected: PASS — new names importable from `uw_scan.models`, in `__all__`, `__module__` preserved. (FAIL first if Step 1/2 are incomplete.)

---

## Task 6: Deriver — `structure_family` + `select_structure_legs` (M2)

**Files:**
- Modify: `src/uw_scan/cards/skew_first_principles.py`
- Test: `tests/unit/cards/test_skew_structure_legs.py` (create)
- Test: `tests/unit/cards/test_skew_first_principles.py` (extend — express parity)

**Design:** `structure_family(lean)` is the single source of the structure descriptor; `_express_structure` derives its string from it (keep V1's existing strings for the bear/bull debit-spread cases). `select_structure_legs` is pure: given the family's target deltas + exposure rows + a DTE window, pick the nearest strike per leg.

- [ ] **Step 1: Write the failing deriver test**

Create `tests/unit/cards/test_skew_structure_legs.py`:

```python
from datetime import date
from decimal import Decimal

from uw_scan.cards import skew_first_principles as sk


def _exposures():
    # one expiry at dte=33; put_delta spans the wing range we need
    ex = date(2026, 7, 18)
    return [
        {"expiry": ex, "strike": Decimal("105"), "dte": 33, "put_delta": Decimal("-0.50")},
        {"expiry": ex, "strike": Decimal("100"), "dte": 33, "put_delta": Decimal("-0.38")},
        {"expiry": ex, "strike": Decimal("95"), "dte": 33, "put_delta": Decimal("-0.26")},
        {"expiry": ex, "strike": Decimal("88"), "dte": 33, "put_delta": Decimal("-0.13")},
        {"expiry": ex, "strike": Decimal("80"), "dte": 33, "put_delta": Decimal("-0.05")},
    ]


def test_bearish_picks_put_debit_spread_by_delta():
    fam = sk.structure_family({"lean": "BEARISH_TILT"})
    assert fam["kind"] == "put_debit_spread"
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=_exposures(), dte_lo=21, dte_hi=60, dte_pref=35)
    assert detail["status"] == "ready"
    assert detail["kind"] == "put_debit_spread"
    legs = detail["legs"]
    assert len(legs) == 2
    buy, sell = legs[0], legs[1]
    assert buy["action"] == "BUY" and buy["right"] == "PUT"
    assert buy["strike"] == Decimal("95")    # closest to -0.25
    assert sell["action"] == "SELL" and sell["strike"] == Decimal("88")  # closest to -0.12
    # defined-risk: long wing strike strictly above the short wing strike
    assert buy["strike"] > sell["strike"]


def test_no_chain_when_exposures_empty():
    fam = sk.structure_family({"lean": "BULLISH_TILT"})
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=[], dte_lo=21, dte_hi=60, dte_pref=35)
    assert detail["status"] == "no_chain"
    assert detail["legs"] == []


def test_neutral_has_no_family():
    assert sk.structure_family({"lean": "NEUTRAL"}) is None


def test_inverted_put_chain_yields_no_chain():
    # non-monotonic chain: the -0.25-target leg lands on a LOWER strike than the
    # -0.12-target leg -> would be a credit (short-premium) spread -> rejected.
    ex = date(2026, 7, 18)
    bad = [
        {"expiry": ex, "strike": Decimal("95"), "dte": 33, "put_delta": Decimal("-0.12")},
        {"expiry": ex, "strike": Decimal("88"), "dte": 33, "put_delta": Decimal("-0.26")},
    ]
    fam = sk.structure_family({"lean": "BEARISH_TILT"})
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=bad, dte_lo=21, dte_hi=60, dte_pref=35)
    assert detail["status"] == "no_chain"
    assert detail["legs"] == []


def test_bullish_picks_call_debit_spread_by_delta():
    ex = date(2026, 7, 18)
    chain = [
        {"expiry": ex, "strike": Decimal("100"), "dte": 33, "call_delta": Decimal("0.50")},
        {"expiry": ex, "strike": Decimal("105"), "dte": 33, "call_delta": Decimal("0.26")},
        {"expiry": ex, "strike": Decimal("112"), "dte": 33, "call_delta": Decimal("0.13")},
        {"expiry": ex, "strike": Decimal("120"), "dte": 33, "call_delta": Decimal("0.05")},
    ]
    fam = sk.structure_family({"lean": "BULLISH_TILT"})
    assert fam["kind"] == "call_debit_spread"
    detail = sk.select_structure_legs(
        family=fam, exposure_rows=chain, dte_lo=21, dte_hi=60, dte_pref=35)
    assert detail["status"] == "ready"
    buy, sell = detail["legs"]
    assert buy["action"] == "BUY" and buy["right"] == "CALL"
    assert buy["strike"] == Decimal("105")     # closest to +0.25
    assert sell["strike"] == Decimal("112")    # closest to +0.12
    assert buy["strike"] < sell["strike"]      # defined-risk bull call (debit) spread
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/unit/cards/test_skew_structure_legs.py -v`
Expected: FAIL — no `structure_family` / `select_structure_legs`.

- [ ] **Step 3: Implement the family descriptor + refactor `_express_structure`**

In `src/uw_scan/cards/skew_first_principles.py`, add above `_express_structure`:

```python
# Defined-risk structure families keyed on the EVIDENCE-GATED lean (never on
# deviation×tail posture — see Phase-2 hardening correction A). Both are long-premium
# debit spreads: max loss = net debit, no naked leg. Target deltas pick the wings.
_STRUCTURE_FAMILIES: dict[str, dict] = {
    "BEARISH_TILT": {
        "kind": "put_debit_spread",
        "legs": [
            {"action": "BUY", "right": "PUT", "target_delta": -0.25},
            {"action": "SELL", "right": "PUT", "target_delta": -0.12},
        ],
    },
    "BULLISH_TILT": {
        "kind": "call_debit_spread",
        "legs": [
            {"action": "BUY", "right": "CALL", "target_delta": 0.25},
            {"action": "SELL", "right": "CALL", "target_delta": 0.12},
        ],
    },
}

_FAMILY_PHRASE = {
    "put_debit_spread": "put-debit-spread — defined risk",
    "call_debit_spread": "call-debit-spread — defined risk",
}


def structure_family(directional_lean: dict) -> dict | None:
    """Structure descriptor for an already-gated lean. None for NEUTRAL — V1's
    anti-overtrading default. Single source consumed by both _express_structure
    (the string) and select_structure_legs (the concrete strikes)."""
    return _STRUCTURE_FAMILIES.get((directional_lean or {}).get("lean") or "")
```

Replace the body of `_express_structure` so it derives from the family (preserves the existing strings' intent — defined-risk debit spread per lean):

```python
def _express_structure(deviation_class: str, lean: str) -> str:
    """Defined-risk structure string. NO naked shorts: every structure is a debit
    vertical (long premium, max loss = net debit). Derived from structure_family so
    the string and the concrete legs never drift."""
    fam = structure_family({"lean": lean})
    if fam is None:
        return ""
    return _FAMILY_PHRASE.get(fam["kind"], "")
```

Then add the pure strike picker:

```python
def select_structure_legs(
    *,
    family: dict | None,
    exposure_rows: list[dict],
    dte_lo: int = 21,
    dte_hi: int = 60,
    dte_pref: int = 35,
    earnings_note: str = "",
) -> dict:
    """Pick concrete legs for `family` by nearest target delta within one expiry.
    Pure — exposure_rows: dicts with expiry, strike, dte, put_delta/call_delta.
    Returns a structure_detail dict (kind, legs, dte_target, status, note)."""
    if family is None:
        return {"kind": "", "legs": [], "dte_target": None,
                "status": "suppressed", "note": ""}
    # candidate expiries inside the swing window; prefer the one nearest dte_pref
    by_expiry: dict = {}
    for r in exposure_rows or []:
        dte = r.get("dte")
        if dte is None or not (dte_lo <= int(dte) <= dte_hi):
            continue
        by_expiry.setdefault(r["expiry"], []).append(r)
    if not by_expiry:
        return {"kind": family["kind"], "legs": [], "dte_target": None,
                "status": "no_chain", "note": ""}
    expiry = min(by_expiry, key=lambda e: abs(int(by_expiry[e][0]["dte"]) - dte_pref))
    chain = by_expiry[expiry]
    dte_target = int(chain[0]["dte"])
    delta_key = "put_delta" if family["legs"][0]["right"] == "PUT" else "call_delta"

    legs: list[dict] = []
    for leg in family["legs"]:
        target = leg["target_delta"]
        cands = [r for r in chain if r.get(delta_key) is not None]
        if not cands:
            return {"kind": family["kind"], "legs": [], "dte_target": dte_target,
                    "status": "no_chain", "note": ""}
        best = min(cands, key=lambda r: abs(float(r[delta_key]) - target))
        legs.append({
            "action": leg["action"], "right": leg["right"],
            "strike": best["strike"], "target_delta": target,
            "actual_delta": best[delta_key], "expiry": expiry, "dte": dte_target,
        })
    # Defined-risk guard (standing rule: no naked shorts). The long (first) and short
    # (second) legs must form a DEBIT spread in the intended direction — the long wing
    # nearer ATM than the short wing. PUT debit: long strike > short strike. CALL debit:
    # long strike < short strike. A degenerate/non-monotonic chain that would invert this
    # (turning it into a short-premium credit spread) yields no_chain instead.
    long_leg, short_leg = legs[0], legs[1]
    ok = (
        long_leg["strike"] > short_leg["strike"]
        if long_leg["right"] == "PUT"
        else long_leg["strike"] < short_leg["strike"]
    )
    if not ok:
        return {"kind": family["kind"], "legs": [], "dte_target": dte_target,
                "status": "no_chain", "note": ""}
    note = "defined risk; long-premium debit spread"
    if earnings_note:
        note += f"; {earnings_note}"
    return {"kind": family["kind"], "legs": legs, "dte_target": dte_target,
            "status": "ready", "note": note}
```

- [ ] **Step 4: Run deriver tests**

Run: `uv run pytest tests/unit/cards/test_skew_structure_legs.py -v`
Expected: PASS.

- [ ] **Step 5: Update + run the existing express test for parity**

In `tests/unit/cards/test_skew_first_principles.py`, the existing assertions on `_express_structure` strings may have expected `"put-debit-spread (sell the lower put wing to finance) — defined risk"` or `"call-debit-spread or put-credit-spread — defined risk"`. Update them to the new single-source strings (`"put-debit-spread — defined risk"`, `"call-debit-spread — defined risk"`) and add:

```python
def test_express_matches_structure_family():
    from uw_scan.cards import skew_first_principles as sk
    assert sk._express_structure("RICH", "BEARISH_TILT") == "put-debit-spread — defined risk"
    assert sk._express_structure("CHEAP", "BULLISH_TILT") == "call-debit-spread — defined risk"
    assert sk._express_structure("NORMAL", "NEUTRAL") == ""
    assert sk.structure_family({"lean": "NEUTRAL"}) is None
```

Run: `uv run pytest tests/unit/cards/test_skew_first_principles.py -v`
Expected: PASS.

---

## Task 7: Assembler + worker wiring — attach `structure_detail` (M2)

**Files:**
- Modify: `src/uw_scan/reports/skew_analytics.py`
- Modify: `src/uw_scan/worker/jobs/skew_analytics.py`
- Test: `tests/unit/reports/test_skew_snapshot_row.py` (extend)
- Test: `tests/integration/api/test_skew.py` (keep green; optionally assert field presence)

**Design:** `build_skew_snapshot_row` stays pure but gains an `exposure_rows` param. When `lean != NEUTRAL` AND `asset_class != "index_macro"` AND `earnings_gate != "block"` AND `exposure_rows` provided, compute `structure_detail` and attach to the lean dict. Callers fetch exposures.

- [ ] **Step 1: Write the failing assembler-row test**

Append to `tests/unit/reports/test_skew_snapshot_row.py`. Verified Pass-1: reuse the file's existing `_rr_series()` / `_rv_series()` helpers and the EXACT bearish kwargs from `test_build_row_bearish_with_seeded_verdict` (NVDA → single_name; `next_earnings_date=None` → egate `unknown` ≠ `block`; the seeded verdict has NO `regime` key, so `resolve_directional_lean`'s regime-gate is skipped → lean = BEARISH_TILT). Add `from decimal import Decimal` to the imports:

```python
def test_structure_detail_present_when_non_neutral_with_exposures():
    rr = _rr_series()
    ex = date(2026, 8, 1)
    exposures = [
        {"expiry": ex, "strike": Decimal("95"), "dte": 33, "put_delta": Decimal("-0.26")},
        {"expiry": ex, "strike": Decimal("88"), "dte": 33, "put_delta": Decimal("-0.13")},
    ]
    row = build_skew_snapshot_row(
        ticker="NVDA",
        market_date=rr[-1]["market_date"],
        rr_series=rr,
        expiry_rows=[{"expiry": date(2026, 8, 1), "risk_reversal": 0.05}],
        rv_series=_rv_series(),
        spy_rv_series=_rv_series(),
        positioning={"si_fee_rate": 0.25, "si_days_to_cover": 1.2},
        next_earnings_date=None,
        verdict={
            "verdict": "TRADABLE_BEAR", "confidence": "med", "forward_sep": -0.02,
            "borrow_clean": True, "survives_gate": True,
        },
        sector=None,
        today=rr[-1]["market_date"],
        exposure_rows=exposures,
    )
    assert row["directional_lean"] == "BEARISH_TILT"  # precondition: lean is gated on
    sd = row["read_json"]["directional_lean"]["structure_detail"]
    assert sd is not None and sd["status"] == "ready"
    assert sd["kind"] == "put_debit_spread"
    assert len(sd["legs"]) == 2
    assert sd["legs"][0]["action"] == "BUY" and sd["legs"][0]["strike"] == Decimal("95")


def test_structure_detail_absent_when_neutral():
    # The existing NEUTRAL happy-path kwargs (verdict=None) must yield NO structure even
    # if exposures are supplied — increment-1 gates on a non-neutral lean.
    rr = _rr_series()
    row = build_skew_snapshot_row(
        ticker="NVDA",
        market_date=rr[-1]["market_date"],
        rr_series=rr,
        expiry_rows=[{"expiry": date(2026, 8, 1), "risk_reversal": 0.05}],
        rv_series=_rv_series(),
        spy_rv_series=_rv_series(),
        positioning={"si_fee_rate": 0.25, "si_days_to_cover": 1.2},
        next_earnings_date=None,
        verdict=None,
        sector=None,
        today=rr[-1]["market_date"],
        exposure_rows=[{"expiry": date(2026, 8, 1), "strike": Decimal("95"),
                        "dte": 33, "put_delta": Decimal("-0.26")}],
    )
    assert row["directional_lean"] == "NEUTRAL"
    assert row["read_json"]["directional_lean"]["structure_detail"] is None
```

NOTE: the existing two tests in this file omit `exposure_rows`; the new kwarg MUST default to `None` (Task 7 Step 3) so they stay green unchanged.

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/unit/reports/test_skew_snapshot_row.py -v`
Expected: FAIL — `build_skew_snapshot_row` has no `exposure_rows` kwarg / no `structure_detail` key.

- [ ] **Step 3: Implement in `build_skew_snapshot_row`**

Add `exposure_rows: list[dict] | None = None` to the signature (keyword-only, after `today`). After `lean = sk.resolve_directional_lean(...)` and before `tail = sk.skew_sign_label(rr_25d)`, insert:

```python
    # Concrete strike-by-delta detail — ONLY when the lean is already gated non-neutral
    # (Phase-2 increment-1). Non-index only; suppressed during an earnings block.
    fam = sk.structure_family(lean)
    if (
        fam is not None
        and cls["asset_class"] != "index_macro"
        and egate != "block"
        and exposure_rows
    ):
        earn_note = (
            f"exit before earnings {next_earnings_date.isoformat()}"
            if next_earnings_date is not None
            else "swing hold; exit before next earnings"
        )
        lean["structure_detail"] = sk.select_structure_legs(
            family=fam, exposure_rows=exposure_rows, earnings_note=earn_note
        )
    else:
        lean["structure_detail"] = None
```

(`build_read` already receives `directional_lean=lean`, so the detail rides into `read_json["directional_lean"]`.)

- [ ] **Step 4: Map `structure_detail` into the typed response**

In `assemble_skew_analysis`, where it builds `SkewDirectionalLean(...)` (around line 298-303), add the mapping. First fetch exposures before the second `build_skew_snapshot_row` call:

```python
    exposures = repo.fetch_latest_exposures_by_strike(t, dte_max=70)
```

Pass `exposure_rows=exposures` into the SECOND `build_skew_snapshot_row(...)` call (the one with the real `verdict`). Then where `SkewDirectionalLean(...)` is constructed, add:

```python
        directional_lean=SkewDirectionalLean(
            lean=lean["lean"],
            confidence=lean["confidence"],
            basis=lean["basis"],
            express=lean["express"],
            structure_detail=_to_structure_detail(lean.get("structure_detail")),
        ),
```

Add a small typed mapper near `_dec` in `skew_analytics.py`:

```python
from uw_scan.models import SkewStructureDetail, SkewStructureLeg  # add to existing import


def _to_structure_detail(d: dict | None) -> SkewStructureDetail | None:
    if not d:
        return None
    return SkewStructureDetail(
        kind=d.get("kind", ""),
        dte_target=d.get("dte_target"),
        status=d.get("status", "ready"),
        note=d.get("note", ""),
        legs=[
            SkewStructureLeg(
                action=g.get("action", ""), right=g.get("right", ""),
                strike=_dec(g.get("strike")), target_delta=_dec(g.get("target_delta")),
                actual_delta=_dec(g.get("actual_delta")),
                expiry=g.get("expiry"), dte=g.get("dte"),
            )
            for g in d.get("legs", [])
        ],
    )
```

- [ ] **Step 5: Wire the nightly worker rollup to pass exposures**

In `src/uw_scan/worker/jobs/skew_analytics.py`, `_build_for_date` signature: add `exposure_rows: list[dict] | None = None` and pass it into BOTH `build_skew_snapshot_row` calls. In `nightly_skew_analytics_rollup`, before calling `_build_for_date`, fetch once per ticker:

```python
        exposures = repo.fetch_latest_exposures_by_strike(ticker, dte_max=70)
```

and pass `exposure_rows=exposures`. In `skew_analytics_backfill`, pass `exposure_rows=None` (historical days have no point-in-time chain — structure detail is a live-only enrichment; documented).

- [ ] **Step 5b: Make `read_json` JSON-safe at persistence (structure_detail adds Decimal/date)**

`build_skew_snapshot_row` puts the in-memory read dict (now containing `Decimal` strikes/deltas and a `_date` expiry inside `structure_detail`) into `read_json`, and `upsert_skew_analytics_snapshots` wraps it with `Jsonb(...)`, whose default `json.dumps` raises on `Decimal`/`date`. Fix the wrap (the in-memory `row["read_json"]` used by `assemble_skew_analysis` for the typed response is UNAFFECTED — only the persisted JSON is stringified, and nothing reads structure_detail back from the persisted JSON).

In `src/uw_scan/storage/skew.py`, add near the imports:

```python
import json
from functools import partial

_json_safe_dumps = partial(json.dumps, default=str)  # Decimal/date -> str for JSONB
```

In `upsert_skew_analytics_snapshots`, change the `read_json` wrap:

```python
            tail = tuple(
                Jsonb(r.get(c), dumps=_json_safe_dumps)
                if c == "read_json" and r.get(c) is not None
                else r.get(c)
                for c in _SNAP_COLUMNS
            )
```

Write the failing integration test FIRST in `tests/integration/storage/test_skew_storage.py`:

```python
def test_snapshot_persists_structure_detail_with_decimal_and_date(repo):
    from datetime import date
    from decimal import Decimal
    row = {
        "ticker": "QCOM", "market_date": date(2026, 6, 16), "basis": "eod",
        "deviation_class": "CHEAP", "directional_lean": "BEARISH_TILT",
        "read_summary": "x",
        "read_json": {
            "directional_lean": {
                "lean": "BEARISH_TILT",
                "structure_detail": {
                    "kind": "put_debit_spread", "dte_target": 33, "status": "ready",
                    "note": "defined risk",
                    "legs": [{"action": "BUY", "right": "PUT", "strike": Decimal("95"),
                              "target_delta": Decimal("-0.25"),
                              "actual_delta": Decimal("-0.26"),
                              "expiry": date(2026, 7, 18), "dte": 33}],
                },
            },
        },
    }
    repo.upsert_skew_analytics_snapshots([row])   # must NOT raise on Decimal/date
    repo.conn.commit()
    got = repo.get_skew_analytics_latest("QCOM")
    sd = got["read_json"]["directional_lean"]["structure_detail"]
    assert sd["legs"][0]["strike"] in ("95", "95.00", "95")  # stringified by default=str
    assert sd["legs"][0]["expiry"] == "2026-07-18"
```

Run: `uv run pytest tests/integration/storage/test_skew_storage.py::test_snapshot_persists_structure_detail_with_decimal_and_date -v`
Expected: FAIL first (psycopg `TypeError: Object of type Decimal is not JSON serializable`), PASS after the `dumps=_json_safe_dumps` change.

- [ ] **Step 6: Run backend tests**

Run: `uv run pytest tests/unit/reports/test_skew_snapshot_row.py tests/integration/api/test_skew.py tests/integration/worker/test_skew_jobs.py tests/integration/storage/test_skew_storage.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit M2**

```bash
git add src/uw_scan/storage/options.py src/uw_scan/storage/skew.py \
        src/uw_scan/models/skew.py src/uw_scan/models/__init__.py \
        src/uw_scan/cards/skew_first_principles.py src/uw_scan/reports/skew_analytics.py \
        src/uw_scan/worker/jobs/skew_analytics.py \
        tests/unit/cards/test_skew_structure_legs.py tests/unit/cards/test_skew_first_principles.py \
        tests/unit/reports/test_skew_snapshot_row.py tests/integration/storage/test_skew_storage.py \
        tests/unit/test_models_exports.py
git commit -m "feat(skew): concrete strike-by-delta detail on the gated directional lean"
```

---

## Task 8: API contract — regenerate types + OpenAPI snapshot (M3)

**Files:**
- Modify: `web/lib/types.ts` (generated)
- Modify: `tests/integration/api/openapi.snapshot.json` (generated)

- [ ] **Step 1: Confirm the snapshot drifts (test fails) after the model change**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: FAIL — `components.schemas` changed (new `SkewStructureDetail` / `SkewStructureLeg`, new `structure_detail` property). This proves the contract grew.

- [ ] **Step 2: Regenerate the committed snapshot** (verified format: `indent=2, sort_keys=True`, trailing newline; produced via `create_app().openapi()` — no DB, no TestClient needed)

```bash
uv run python -c "
import json
from uw_scan.api.server import create_app
spec = create_app().openapi()
with open('tests/integration/api/openapi.snapshot.json', 'w') as f:
    json.dump(spec, f, indent=2, sort_keys=True)
    f.write('\n')
"
uv run pytest tests/integration/api/test_openapi_snapshot.py -v   # now PASS
```

- [ ] **Step 3: Regenerate TypeScript types** (the `gen:types` script targets the LIVE API at `http://127.0.0.1:8400`, so the API must be running)

```bash
# in one shell: bring up the API (or the full stack) — e.g. bash scripts/dev.sh
cd web && npm run gen:types
```
Expected: `lib/types.ts` diff adds `SkewStructureDetail`, `SkewStructureLeg`, and `structure_detail` on the lean type. If the API is not runnable in this environment, generate from the local spec instead: `cd web && npx openapi-typescript ../tests/integration/api/openapi.snapshot.json -o lib/types.ts` (same source of truth, just regenerated above).

- [ ] **Step 4: Typecheck**

Run: `cd web && npm run typecheck`
Expected: PASS (no drift, no unused-type errors).

---

## Task 9: UI — render structure legs in the Signal Detail card (M3)

**Files:**
- Modify: `web/components/stock/panels/SkewSignalDetail.tsx`
- Test: `web/tests/unit/SkewSignalDetail.test.tsx` (extend)

**Design:** below the existing Evidence rows (after the `express` row, inside the right `metric-card`), render a compact, defined-risk structure block when `lean.structure_detail?.status === "ready"`. Keep the VCG/mono aesthetic. When absent or not "ready", render nothing new (NEUTRAL names look exactly like V1).

- [ ] **Step 1: Write the failing vitest**

Append to `web/tests/unit/SkewSignalDetail.test.tsx` (mirror the existing render-helper + mock-data pattern in that file):

```tsx
it("renders the defined-risk structure legs when status is ready", () => {
  const data = makeData({
    read: {
      directional_lean: {
        lean: "BEARISH_TILT", confidence: "high", basis: "validated …",
        express: "put-debit-spread — defined risk",
        structure_detail: {
          kind: "put_debit_spread", dte_target: 33, status: "ready",
          note: "defined risk; exit before earnings 2026-07-18",
          legs: [
            { action: "BUY", right: "PUT", strike: "95", target_delta: "-0.25",
              actual_delta: "-0.26", expiry: "2026-07-18", dte: 33 },
            { action: "SELL", right: "PUT", strike: "88", target_delta: "-0.12",
              actual_delta: "-0.13", expiry: "2026-07-18", dte: 33 },
          ],
        },
      },
    },
  });
  render(<SkewSignalDetail data={data} />);
  expect(screen.getByTestId("skew-structure-detail")).toBeInTheDocument();
  expect(screen.getByText(/put-debit-spread/i)).toBeInTheDocument();
  expect(screen.getByText(/BUY/)).toBeInTheDocument();
  expect(screen.getByText(/95/)).toBeInTheDocument();
  expect(screen.getByText(/defined risk/i)).toBeInTheDocument();
});

it("renders no structure block for a NEUTRAL lean", () => {
  const data = makeData({
    read: { directional_lean: { lean: "NEUTRAL", structure_detail: null } },
  });
  render(<SkewSignalDetail data={data} />);
  expect(screen.queryByTestId("skew-structure-detail")).not.toBeInTheDocument();
});
```

(Use the file's existing `makeData` deep-merge helper; if it shallow-merges, extend the mock object fully.)

- [ ] **Step 2: Run it to confirm it fails**

Run: `cd web && npm run test -- SkewSignalDetail`
Expected: FAIL — no `skew-structure-detail` testid.

- [ ] **Step 3: Implement the structure block**

In `SkewSignalDetail.tsx`, add a presentational helper above `SkewSignalDetail`:

```tsx
function StructureDetail({
  detail,
}: {
  detail: NonNullable<SkewAnalysisResponse["read"]["directional_lean"]["structure_detail"]>;
}) {
  if (detail.status !== "ready" || !detail.legs?.length) return null;
  return (
    <div
      data-testid="skew-structure-detail"
      style={{
        borderTop: "1px solid var(--border-dim, var(--line-grid))",
        marginTop: "8px",
        paddingTop: "8px",
      }}
    >
      <div style={{ ...labelStyle, marginBottom: "6px" }}>
        Structure · {detail.kind.replace(/_/g, "-")}
        {detail.dte_target ? ` · ${detail.dte_target}DTE` : ""}
      </div>
      {detail.legs.map((leg, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontFamily: "var(--font-mono)",
            fontSize: "11px",
            padding: "2px 0",
          }}
        >
          <span style={{ color: "var(--text-muted)" }}>
            {leg.action} {leg.right}
          </span>
          <span style={{ color: "var(--text-secondary)" }}>
            {leg.strike != null ? String(leg.strike) : "—"}
            {leg.actual_delta != null ? ` (Δ ${fmtSigned(toNum(leg.actual_delta) ?? 0, 2)})` : ""}
          </span>
        </div>
      ))}
      {detail.note ? (
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: "10px",
            color: "var(--text-muted)",
            marginTop: "5px",
            lineHeight: 1.4,
          }}
        >
          {detail.note}
        </div>
      ) : null}
    </div>
  );
}
```

Render it inside the right `metric-card`, immediately after the closing `</div>` of the evidence-rows block (after the `regime` `EvidenceRow`), still inside the bordered evidence container:

```tsx
            <EvidenceRow label="regime" value={data.regime} />
            {lean.structure_detail ? (
              <StructureDetail detail={lean.structure_detail} />
            ) : null}
```

- [ ] **Step 4: Run vitest + typecheck**

Run: `cd web && npm run test -- SkewSignalDetail && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit M3**

```bash
git add web/lib/types.ts tests/integration/api/openapi.snapshot.json \
        web/components/stock/panels/SkewSignalDetail.tsx web/tests/unit/SkewSignalDetail.test.tsx
git commit -m "feat(skew): surface concrete strike-by-delta structure in the Signal Detail card"
```

---

## Task 10: E2E — extend the Skew tab spec (M3/M4)

**Files:**
- Modify: `web/tests/e2e/skew-tab.spec.ts`

**Design:** the e2e hits a real running stack. Most names are NEUTRAL (no structure block) — assert the structure block is *optional but well-formed when present*: if `skew-lean-pill` is not NEUTRAL, `skew-structure-detail` must exist and show ≥2 legs; if NEUTRAL, it must be absent. Pick a ticker likely to be non-neutral if the suite already targets one; otherwise keep it tolerant.

- [ ] **Step 1: Add the conditional assertion**

Append to `web/tests/e2e/skew-tab.spec.ts` (inside the existing Skew-tab describe, reuse its navigation/setup):

```ts
test("structure detail appears only for a non-neutral lean", async ({ page }) => {
  // navigate to the skew tab (reuse the spec's existing helper / beforeEach)
  const pill = page.getByTestId("skew-lean-pill");
  await expect(pill).toBeVisible();
  const lean = (await pill.textContent())?.trim() ?? "";
  const block = page.getByTestId("skew-structure-detail");
  if (lean === "NEUTRAL") {
    await expect(block).toHaveCount(0);
  } else {
    await expect(block).toBeVisible();
    await expect(block).toContainText(/-spread/);
    // at least two legs (BUY + SELL lines)
    await expect(block.getByText(/BUY|SELL/)).toHaveCount(2);
  }
});
```

- [ ] **Step 2: Run e2e if a stack is available**

Run (from repo root, with API+web up — `bash scripts/dev.sh` or the e2e's own webServer): `cd web && npm run test:e2e -- skew-tab`
Expected: PASS. If no stack/data is available in the execution environment, record this as the one explicitly-unverified item and run it during the final verification step against the running dev stack.

---

## Task 11: Milestone M4 — research note + full verification

**Files:**
- Create: `docs/research/skew-rr-reversion-trigger-2026-06.md`

- [ ] **Step 1: Run the RV markout harness on real local data**

The backfill already populated `skew_analytics_snapshot` on `option_wizard_local` (per the V1 markout note). Run the harness and capture the RV reversion output:

`_repo` in `scheduler.py` is a CONTEXT MANAGER (`@contextmanager def _repo(settings) -> Iterator[Repository]`), so it must be entered with `with`:

```bash
uv run python -c "
import json
from uw_scan.config import Settings
from uw_scan.worker.scheduler import _repo
from uw_scan.reports.skew_markout import run_skew_markout
with _repo(Settings()) as repo:
    out = run_skew_markout(repo=repo)
print(json.dumps(out['rv_reversion'], indent=2, default=str))
"
```

This runs against whatever DB the env points at — confirm it is `option_wizard_local` (the three-tier tripwire blocks a mini host + local name, so a stray `.env` mistake fails loudly rather than writing prod).

- [ ] **Step 2: Write the research note**

Create `docs/research/skew-rr-reversion-trigger-2026-06.md` with: method (tail-split keys, expected-sign gate, time-ordered 40% holdout, thresholds), the captured per-bucket table (verdict / mean_drr / mean_drr_holdout / n / survives_walkforward), and the loud limitations (single ~1yr in-sample window; holdout and train share regime; descriptive RV axis, **no spread-P&L / net-of-cost** — that validation is data-blocked and split out). Cross-reference `docs/research/skew-first-principles-markout-2026-06.md` for the primary numbers (do not duplicate the directional table).

- [ ] **Step 3: Full backend test sweep**

Run: `uv run pytest tests/unit/cards/ tests/unit/reports/ tests/integration/reports/test_skew_markout.py tests/integration/reports/test_skew_rv_markout.py tests/integration/storage/test_skew_storage.py tests/integration/api/test_skew.py tests/integration/worker/test_skew_jobs.py tests/unit/test_models_exports.py -v`
Expected: all PASS.

- [ ] **Step 4: CI guardrail + migration idempotency + web suite**

Run: `uv run python scripts/_lint_except.py src` → expect "ok: no banned except patterns".
Run: `bash scripts/migrate.sh && bash scripts/migrate.sh` → both succeed (idempotent).
Run: `cd web && npm run typecheck && npm run test` → PASS.

- [ ] **Step 5: Browser/e2e verification**

Bring up the dev stack and open a stock page → Skew tab for both a NEUTRAL and (if available) a non-neutral name; confirm the structure block renders legs + the defined-risk note for the non-neutral one and is absent for NEUTRAL. Capture a screenshot under `output/playwright/`. Run `cd web && npm run test:e2e -- skew-tab`.

- [ ] **Step 6: Commit M4**

```bash
git add docs/research/skew-rr-reversion-trigger-2026-06.md web/tests/e2e/skew-tab.spec.ts
git commit -m "docs(skew): RR mean-reversion trigger research note + e2e structure assertion"
```

---

## Verification matrix (fill during execution)

| Claim | Evidence | How to re-verify |
|---|---|---|
| RV verdict store gated by walk-forward | `test_skew_rv_markout.py` green + `_rv_walkforward` unit cases | `uv run pytest tests/integration/reports/test_skew_rv_markout.py -v` |
| Tail-split keys persisted | `skew_rv_reversion_verdicts` rows keyed (asset_class, deviation_class, tail) | `psql -c "select * from uw_scan.skew_rv_reversion_verdicts"` |
| Strikes picked by target delta | `test_skew_structure_legs.py` green | `uv run pytest tests/unit/cards/test_skew_structure_legs.py -v` |
| Structure only on non-neutral lean | assembler-row tests + vitest absence test | `uv run pytest tests/unit/reports/test_skew_snapshot_row.py -v` |
| No naked legs | both families are debit spreads; deriver asserts distinct strikes | inspect `_STRUCTURE_FAMILIES` + `select_structure_legs` |
| Contract in sync | `gen:types` diff + openapi snapshot test green | `cd web && npm run gen:types` (empty diff) |
| Migration idempotent | two `migrate.sh` runs no-op | `bash scripts/migrate.sh && bash scripts/migrate.sh` |
| UI renders legs | vitest + e2e + screenshot | `cd web && npm run test -- SkewSignalDetail` |
| No P&L/net-of-cost claim made | research note states it explicitly; no such code path | read `docs/research/skew-rr-reversion-trigger-2026-06.md` |

## Out of scope (split-out follow-on plans — do NOT build here)
- Net-of-cost / OOS spread-P&L validation (data-blocked: chain ~5d, greeks ~30d history).
- Delta-hedge sizing helper (Structure 3).
- Layer-2 cross-pillar gate in the backend trade-blast AI pipeline (`framework{}`), not `FrameworkTab.tsx`.
- Wiring the RV reversion verdict to *also* unlock structure detail for NEUTRAL-lean names (deliberate: needs the walk-forward to validate first).
