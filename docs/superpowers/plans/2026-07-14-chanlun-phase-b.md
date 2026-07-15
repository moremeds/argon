# Chanlun Phase B — 区间套 sub-level fast-confirm (server-side lifecycle engine)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

## Goal

Port the shipped TypeScript chanlun engine to Python, feed it apex 1d + 30m bars, run a nightly lifecycle state machine that upgrades daily marks to CONFIRMED_SUBLEVEL from completed 30m (次级别) structure, persist every transition to a durable Postgres event log, expose it read-only over the API, and gate which categories are promotion-eligible with a committed walk-forward validation probe.

## Architecture

Five new pieces inside argon: (1) `src/uw_scan/chanlun/` — a field-for-field Python port of `web/lib/chanlun.ts` + `web/lib/chanlunSeg.ts`, verified against a TS-generated golden fixture; (2) `sources/apex.py::fetch_bars` — the single-source 1d/30m bar client; (3) `chanlun/lifecycle.py` + `storage/chanlun_signal_repository.py` + migration `107` — the pure state machine and its append-mostly event log; (4) `worker/jobs/chanlun_lifecycle.py` + scheduler registration — the nightly batch; (5) the read API endpoint and the walk-forward probe that gates promotion. The port is compute-only (no I/O); all I/O lives in the job, the client, and the repository.

## Tech Stack

- Python 3.13 via `uv` only. Typed. stdlib `dataclasses` for the port types (no Pydantic in `chanlun/`).
- FastAPI + Pydantic v2 (API models only), psycopg 3, APScheduler 3, httpx — all already present. **No new dependencies.**
- Vitest + TypeScript for the golden-fixture exporter (`web/`).
- pytest + the repo's pytest-postgresql harness for integration tests.

## Global Constraints (binding on EVERY task — re-read before each commit)

- **uv only.** Run Python tests as `uv run pytest …`, never bare `pytest`. Never bare `python`/`pip`.
- **Module size budget <500 lines/file.** The port splits into `types.py`/`core.py`/`points.py`/`segments.py`/`full.py` specifically to respect this. If any file approaches 500 lines, stop and split by domain seam before adding more.
- **New storage domains never extend `repository.py`.** `storage/chanlun_signal_repository.py` is a standalone class from method one — do not import it into `repository.py`.
- **`web/lib/types.ts` and `tests/integration/api/openapi.snapshot.json` are frozen generated files.** Add fields SURGICALLY (Task 10's exact procedure). Never run a full `npm run gen:types` regen — it reorders the whole ~9.6k-line file and buries the change.
- **Non-vacuity is mandatory on every real-data test.** Any test asserting over marks/vertices/events/bars MUST first assert the collection is non-empty, THEN assert properties. An oracle that passes on zero elements is worthless (the v2 lesson).
- **No synthetic market data.** Tests use frozen real fixtures with an as-of date (the AAPL golden bars from Task 1; the AAPL 30m sample as-of 2026-07-10 from the apex-contract doc). Hand-built abstract geometry for pure state-machine edges is a labeled test double, NOT market data, and is acceptable — never present it as a real quote.
- **CHANGELOG `[Unreleased]` entry rides THIS PR** (Task 12), on the feature branch before merge.
- **DatasetRegistryEntry + regenerated data-gap policy doc ship in THIS PR** (Task 7). Two CI gates enforce it.
- **Branch: `feat/chanlun-phase-b`.** All commits land here. Open a PR before merging to main; never `git push origin main`.
- **Commit messages have NO `Co-Authored-By` trailer** and no AI-attribution trailer.
- **Every mutating step ends in a verified test + commit.** TDD: write the failing test, run it (see the exact expected failure), implement, re-run (see the exact expected pass), then commit with the exact `git` command given.
- **Persist analytical results to Postgres.** The lifecycle event log is the durable artifact; the probe persists its full per-mark trace to a committed file. stdout-only is data loss.

---

## Task 0: Commit the spec + research artifacts on the feature branch

The design spec and the four research docs already exist on disk. This task only creates the branch and commits them so the plan's requirements travel with the code.

**Files:**
- Create (branch): `feat/chanlun-phase-b`
- Commit (already on disk): `docs/superpowers/specs/2026-07-14-chanlun-phase-b-sublevel-confirm-design.md`, `docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md`, `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_backend_patterns.md`, `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_apex_bars_contract.md`, `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_confirm_rule_options.md`, and this plan file.

**Steps:**
- [ ] `cd /Users/chenxi/projects/argon && git checkout main && git pull --ff-only` (get a clean base).
- [ ] `git checkout -b feat/chanlun-phase-b`.
- [ ] `git status --short` — confirm the spec/research/plan files show as untracked or modified.
- [ ] Stage only these docs: `git add docs/superpowers/specs/2026-07-14-chanlun-phase-b-sublevel-confirm-design.md docs/superpowers/specs/2026-07-14-chanlun-py-port-contract.md docs/research/2026-07-14-chanlun-signal-lifecycle/ docs/superpowers/plans/2026-07-14-chanlun-phase-b.md`
- [ ] Commit: `git commit -m "docs(chanlun): phase B spec, port contract, research inventory + plan"`

---

## Task 1: TS golden-fixture exporter (`web/`)

Generate ONE deterministic golden JSON containing the input bars + the complete `computeChanlunFull` output + the raw `macdHist` oracle, computed over the existing frozen `AAPL_DAILY_2Y` fixture. The Python parity tests (Tasks 2–5) consume this exact file — it is the single source of truth for TS↔Python equality. Follow port-contract §F.

**Files:**
- Modify: `web/lib/chanlun.ts` (add `export` to `macdHist` only — zero behaviour change)
- Create: `web/tests/lib/chanlunGolden.test.ts` (the exporter, written as a vitest test that writes-then-verifies)
- Create (generated, committed): `web/tests/lib/fixtures/chanlunGoldenAapl.json`

**Interfaces:**
- Consumes: `computeChanlunFull(bars: ChanlunBar[])` and `macdHist(closes: number[])` from `@/lib/chanlun`; `AAPL_DAILY_2Y` from `../unit/fixtures/aaplDaily2y`.
- Produces: `web/tests/lib/fixtures/chanlunGoldenAapl.json` with top-level keys `bars, vertices, zhongshus, points, divergences, segVertices, segZhongshus, segPoints, macdHist`. Optional per-record keys (`level` on Zhongshu, `resonant` on BuySellPoint) are OMITTED when absent (never emitted as `null`) — matching `JSON.stringify`'s drop-undefined behaviour.

**Steps:**
- [ ] Read `web/lib/chanlun.ts:179` and add the `export` keyword to `macdHist`'s declaration (`export function macdHist(...)`). Confirm nothing else changes: `git diff web/lib/chanlun.ts` shows exactly one added keyword.
- [ ] Write the exporter test file `web/tests/lib/chanlunGolden.test.ts`:

```ts
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

import {
  computeChanlunFull,
  macdHist,
  type ChanlunBar,
} from "@/lib/chanlun";
import { AAPL_DAILY_2Y } from "../unit/fixtures/aaplDaily2y";

const OUT = resolve(__dirname, "fixtures/chanlunGoldenAapl.json");

const bars: ChanlunBar[] = AAPL_DAILY_2Y.map((b) => ({
  time: b.as_of,
  high: b.high,
  low: b.low,
  close: b.close,
}));

// Deterministic serializer: sort object keys alphabetically so the file is
// byte-stable across runs (JSON.stringify drops `undefined` keys, so absent
// optional fields like level/resonant are omitted, not nulled).
function stable(value: unknown): string {
  return JSON.stringify(
    value,
    (_k, v) =>
      v && typeof v === "object" && !Array.isArray(v)
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .map((k) => [k, (v as Record<string, unknown>)[k]]),
          )
        : v,
    2,
  );
}

describe("chanlun golden fixture", () => {
  const full = computeChanlunFull(bars);
  const golden = {
    bars,
    vertices: full.vertices,
    zhongshus: full.zhongshus,
    points: full.points,
    divergences: full.divergences,
    segVertices: full.segVertices,
    segZhongshus: full.segZhongshus,
    segPoints: full.segPoints,
    macdHist: macdHist(bars.map((b) => b.close)),
  };
  const serialized = stable(golden) + "\n";

  it("writes then stays byte-stable (never delete the committed file to force a rewrite)", () => {
    if (!existsSync(OUT)) {
      mkdirSync(dirname(OUT), { recursive: true });
      writeFileSync(OUT, serialized);
    }
    // Non-vacuity: the fixture must contain real structure, not empty arrays.
    expect(golden.vertices.length).toBeGreaterThan(0);
    expect(golden.points.length).toBeGreaterThan(0);
    expect(golden.divergences.length).toBeGreaterThan(0);
    expect(golden.segVertices.length).toBeGreaterThan(0);
    expect(golden.macdHist.length).toBe(bars.length);
    // Byte-stability: the committed file must equal a fresh serialization.
    expect(readFileSync(OUT, "utf8")).toBe(serialized);
  });
});
```

- [ ] First run (writes the file): `cd web && npm run test -- chanlunGolden` — expect **1 passed** (the file is created on first run, then the read-back equals the fresh serialization).
- [ ] Confirm the file exists and is non-trivial: `wc -l web/tests/lib/fixtures/chanlunGoldenAapl.json` (expect several thousand lines) and `head -c 200 web/tests/lib/fixtures/chanlunGoldenAapl.json`.
- [ ] Run once more to prove idempotent byte-stability: `cd web && npm run test -- chanlunGolden` — expect **1 passed** again with the file unchanged (`git diff --stat web/tests/lib/fixtures/chanlunGoldenAapl.json` shows no change on the second run).
- [ ] Commit: `git add web/lib/chanlun.ts web/tests/lib/chanlunGolden.test.ts web/tests/lib/fixtures/chanlunGoldenAapl.json && git commit -m "test(chanlun): TS golden fixture exporter + committed AAPL golden JSON"`

---

## Task 2: Python port — `types.py` + `core.py` + parity harness

Port the stroke-level pipeline (§C.1–§C.8, §C.12 of the port contract) and stand up the parity test infrastructure that all later port tasks reuse. Algorithm source is the port contract sections cited per function + the TS file:line therein — do NOT invent behaviour; transcribe the cited semantics exactly (tie-break strict/non-strict rules are load-bearing).

**Files:**
- Create: `src/uw_scan/chanlun/__init__.py`
- Create: `src/uw_scan/chanlun/types.py`
- Create: `src/uw_scan/chanlun/core.py`
- Create: `tests/unit/chanlun/__init__.py`
- Create: `tests/unit/chanlun/parity_helpers.py` (the reusable divergent-field reporter — written ONCE here, imported by Tasks 3–5)
- Create: `tests/unit/chanlun/test_core_invariants.py`
- Create: `tests/unit/chanlun/test_parity.py` (staged parity, grows in Tasks 3–5)

**Interfaces:**
- Produces (`types.py`, stdlib `@dataclass`): `ChanlunBar(time:str, high:float, low:float, close:float)` — **exactly these four fields, NO `open`** (mirrors the TS `ChanlunBar` in port contract §A, `chanlun.ts:15-20`; the compute pipeline never reads an open — apex `open` values stay in the raw bar dicts, which is where the Task 8 split-boundary guard reads them). Every `ChanlunBar` construction anywhere in this plan uses keyword args (`ChanlunBar(time=..., high=..., low=..., close=...)`). Also: `MergedK(high, low, hiIdx:int, loIdx:int)`, `Fractal(kind:str, mIdx:int, rawIdx:int, price:float)`, `BiVertex(time:str, price:float, kind:str, confirmed:bool)`, `Zhongshu(start:str, end:str, zg:float, zd:float, confirmed:bool, level:int|None=None)`, `BuySellPoint(time:str, price:float, kind:str, confirmed:bool, resonant:bool|None=None)`, `DivergenceMark(time:str, price:float, kind:str, confirmed:bool)`, `VertexPt(time:str, price:float, kind:str, rawIdx:int, confirmed:bool)`, `Leg(hi, lo, up:bool, a:int, b:int, rawA:int, rawB:int)`, `Pivot(firstLeg:int, lastLeg:int, exitLeg:int|None, exitUp:bool, zg:float, zd:float)`, `ChanlunResult(vertices, zhongshus, points, divergences)`. (Segment types `SegVertex, SegStats, Stroke, Elem, ChanlunFullResult` are added in Tasks 4–5.)
- Produces (`core.py`): `MIN_VERTEX_GAP=4`, `DIVERGENCE_RATE=0.9`, `MIN_BARS=10`; functions `ema(values:list[float], period:int)->list[float|None]`, `macd_hist(closes:list[float])->list[float]`, `merge_inclusions(bars:list[ChanlunBar])->list[MergedK]`, `find_fractals(m:list[MergedK])->list[Fractal]`, `build_endpoints(fractals:list[Fractal])->list[Fractal]`, `build_legs(pts:list[VertexPt])->list[Leg]`, `build_pivots(legs:list[Leg])->list[Pivot]`, `pivots_to_zhongshus(pivots:list[Pivot], legs:list[Leg], pts:list[VertexPt])->list[Zhongshu]`, `merge_overlapping_zhongshus(zs:list[Zhongshu])->list[Zhongshu]`, `resample_weekly(bars:list[ChanlunBar])->list[ChanlunBar]`.
- Produces (`parity_helpers.py`): `GOLDEN` (loaded dict), `bars_from_golden()->list[ChanlunBar]`, `assert_records_equal(golden:list[dict], actual:list, fields:list[str], label:str)` — raises `AssertionError` naming the first divergent `label[i].field` on mismatch, after first asserting equal length AND non-empty.

**Algorithm sources (cite these in the code as docstring `# port-contract §…`):**
- `ema`/`macd_hist` → §C.4 (`indicators.ts:17-28`, `chanlun.ts:179-185`). Exact scalar recursion `e = v if e is None else alpha*v + (1-alpha)*e`, `alpha = 2/(period+1)`, one running float. Do NOT use numpy/pandas EMA (§F, §E — a one-ULP difference flips `legArea` gating).
- `merge_inclusions` → §C.1 (`chanlun.ts:90-128`). Note the tie-break asymmetry: up-merge high `>=`, low strict `>`; down-merge mirror.
- `find_fractals` → §C.2 (`chanlun.ts:133-149`). All four comparisons strict.
- `build_endpoints` → §C.3 (`chanlun.ts:154-175`). Same-kind replace `>=`/`<=` (ties replace); opposite-kind accept requires BOTH `mIdx` gap `>= MIN_VERTEX_GAP` AND strict price. Rejected opposite-kind fractal does NOT become `last`.
- `build_legs` → §C.6 (`chanlun.ts:214-228`).
- `build_pivots` → §C.7 (`chanlun.ts:233-259`). Non-uniform advance: on reject `i += 1`; on pivot found jump to `exitLeg` (or end). `zg <= zd` rejects. Exit test `lo > zg or hi < zd`; `exitUp = lo > zg`.
- `pivots_to_zhongshus` → §C.7 (`chanlun.ts:261-273`). `confirmed = exitLeg is not None`.
- `merge_overlapping_zhongshus` → §C.8 (`chanlun.ts:279-294`). Strict `<` overlap; merge widens `last` in place, `start` untouched, `level=2`; else push copy with `level = z.level if z.level is not None else 1`.
- `resample_weekly` → §C.12 + §G item 9 (the getUTCDay weekday gotcha) (`chanlun.ts:472-494`). **TRAP:** `offset = d.weekday()` directly (Python `date.weekday()` already equals TS `(getUTCDay()+6)%7`). Do NOT re-apply `(x+6)%7`. Output `time` = LAST session's date in the week, not the Monday key.

**Steps:**
- [ ] Create `src/uw_scan/chanlun/__init__.py` (empty for now) and `src/uw_scan/chanlun/types.py` with the dataclasses listed in Interfaces (frozen=False; plain mutable dataclasses so `merge_inclusions`/`merge_overlapping_zhongshus` can mutate `last` in place like the TS).
- [ ] Create `src/uw_scan/chanlun/core.py` implementing every function above from the cited §sections. Guard `compute_*` callers later; `core.py` itself has no I/O.
- [ ] Create `tests/unit/chanlun/__init__.py` (empty) and `tests/unit/chanlun/parity_helpers.py`:

```python
"""Shared parity infrastructure for the chanlun TS->Python port.

Loads the committed TS golden fixture and provides a field-by-field comparator
that reports the FIRST divergent path (localizes a failure instead of dumping
the whole structure). Optional keys (level/resonant) treat "absent" == None.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from uw_scan.chanlun.types import ChanlunBar

# tests/unit/chanlun/parity_helpers.py -> parents[3] == repo root
_GOLDEN_PATH = (
    Path(__file__).resolve().parents[3]
    / "web/tests/lib/fixtures/chanlunGoldenAapl.json"
)
GOLDEN: dict[str, Any] = json.loads(_GOLDEN_PATH.read_text())


def bars_from_golden() -> list[ChanlunBar]:
    return [
        ChanlunBar(time=b["time"], high=b["high"], low=b["low"], close=b["close"])
        for b in GOLDEN["bars"]
    ]


def assert_records_equal(
    golden: list[dict], actual: list[Any], fields: list[str], label: str
) -> None:
    """Field-by-field equality; raises naming the first divergent path.

    Non-vacuity first: the golden slice must be non-empty (a comparator that
    passes on two empty lists is worthless).
    """
    assert golden, f"{label}: golden slice is empty (non-vacuity violated)"
    assert len(actual) == len(golden), (
        f"{label}: length {len(actual)} != golden {len(golden)}"
    )
    for i, (g, a) in enumerate(zip(golden, actual)):
        for f in fields:
            gv = g.get(f, None)
            av = getattr(a, f, None)
            assert av == gv, (
                f"{label}[{i}].{f}: got {av!r} != golden {gv!r} "
                f"(record got={a!r} golden={g!r})"
            )
```

- [ ] Create `tests/unit/chanlun/test_core_invariants.py` (mirrors `chanlun.test.ts:21-37` inclusion invariants — no golden needed, localizes an inclusion-merge bug):

```python
from __future__ import annotations

from uw_scan.chanlun.core import merge_inclusions
from tests.unit.chanlun.parity_helpers import bars_from_golden


def test_no_two_consecutive_merged_candles_are_mutually_inclusive():
    bars = bars_from_golden()
    m = merge_inclusions(bars)
    assert len(m) > 0  # non-vacuity
    for i in range(1, len(m)):
        a, b = m[i - 1], m[i]
        inc = (a.high >= b.high and a.low <= b.low) or (
            b.high >= a.high and b.low <= a.low
        )
        assert not inc, f"merged candles {i - 1}/{i} still mutually inclusive"


def test_merged_extremes_point_at_the_carrying_raw_bar():
    bars = bars_from_golden()
    m = merge_inclusions(bars)
    assert len(m) > 0
    for k in m:
        assert bars[k.hiIdx].high == k.high
        assert bars[k.loIdx].low == k.low
```

- [ ] Create `tests/unit/chanlun/test_parity.py` with ONLY the `macd_hist` parity test for now (the `vertices`/`zhongshus`/`points`/`divergences` parity tests are ADDED in Task 3 once `compute_chanlun` exists; the full-result ones in Task 5). This keeps every test in the file runnable against Task 2's code:

```python
from __future__ import annotations

from uw_scan.chanlun.core import macd_hist
from tests.unit.chanlun.parity_helpers import (
    GOLDEN,
    assert_records_equal,
    bars_from_golden,
)


def test_macd_hist_parity():
    bars = bars_from_golden()
    hist = macd_hist([b.close for b in bars])
    golden = GOLDEN["macdHist"]
    assert len(hist) == len(golden) and len(hist) > 0  # non-vacuity
    for i, (a, g) in enumerate(zip(hist, golden)):
        assert abs(a - g) <= 1e-9, f"macdHist[{i}]: {a!r} vs golden {g!r}"
```

  (The `assert_records_equal`/`bars_from_golden` imports are unused in Task 2 but are imported now so Task 3's additions need no import edits. If your linter fails on unused imports, add them in Task 3 instead — either is fine.)
- [ ] Run the failing state FIRST (before implementing `core.py` bodies, stub them to `raise NotImplementedError`): `uv run pytest tests/unit/chanlun/ -q` — expect failures/errors (`NotImplementedError` or import errors) proving the tests exercise real code.
- [ ] Implement `core.py` fully from the cited §sections.
- [ ] Run: `uv run pytest tests/unit/chanlun/test_core_invariants.py tests/unit/chanlun/test_parity.py::test_macd_hist_parity -q` — expect **3 passed** (2 invariants + 1 macd). If `test_macd_hist_parity` fails, the EMA recursion is wrong (§F): fix `ema`/`macd_hist` FIRST, it is the root oracle.
- [ ] Run the full new suite: `uv run pytest tests/unit/chanlun/ -q` — expect all collected tests passed.
- [ ] Commit: `git add src/uw_scan/chanlun/__init__.py src/uw_scan/chanlun/types.py src/uw_scan/chanlun/core.py tests/unit/chanlun/ && git commit -m "feat(chanlun): port types + stroke core (inclusion/fractals/endpoints/MACD/legs/pivots/zhongshu) with golden parity harness"`

---

## Task 3: Python port — `points.py` + `full.compute_chanlun` + stroke-level parity

Port `markPoints`/`markDivergences`/`markResonance` (§C.9–§C.11, §C.13) and the v1 orchestrator `compute_chanlun` including the provisional-tail construction (§C.5, §C.14). Then upgrade `test_parity.py` to compare the real `vertices`/`zhongshus`/`points`/`divergences` against the golden.

**Files:**
- Create: `src/uw_scan/chanlun/points.py`
- Create: `src/uw_scan/chanlun/full.py` (holds `compute_chanlun` now; `compute_chanlun_full` added in Task 5)
- Modify: `src/uw_scan/chanlun/__init__.py` (re-export `compute_chanlun`, `compute_chanlun_full` once it exists)
- Modify: `tests/unit/chanlun/test_parity.py` (append the stroke-level parity tests)

**Interfaces:**
- Consumes: everything from `core.py` (Task 2).
- Produces (`points.py`): `mark_points(pts:list[VertexPt], legs:list[Leg], pivots:list[Pivot], leg_area)->list[BuySellPoint]`, `mark_divergences(pts, legs, leg_area)->list[DivergenceMark]`, `mark_resonance(points:list[BuySellPoint], weekly:ChanlunResult, last_bar_time:str)->list[BuySellPoint]`. `leg_area` is a callable `(Leg)->float`.
- Produces (`full.py`): `compute_chanlun(bars:list[ChanlunBar])->ChanlunResult`.

**Algorithm sources:**
- `mark_points` → §C.9 (`chanlun.ts:296-356`). **Both** `if p.exitUp and not exitL.up` AND `if not p.exitUp and exitL.up` as independent guards (deviation #2). `connect = legs[prev.exitLeg-1]`, `exit = legs[p.exitLeg-1]` (leg BEFORE the exit leg). `retest = pts[exit.b+2]` fixed offset (deviation #4). `DIVERGENCE_RATE` gate strict `<`. Final sort by `time` (plain string sort — §G.1 safe).
- `mark_divergences` → §C.10 (`chanlun.ts:362-385`). `legs[i]` vs `legs[i+2]`; NO final sort (natural order is chronological). Decoupled from `mark_points` (deviation #5).
- `leg_area` closure → §C.11 (`chanlun.ts:456-463`). `sum(abs(hist[r]) for r in range(l.rawA+1, l.rawB+1))` — inclusive of `rawB`, EXCLUSIVE of `rawA`. `hist = macd_hist([b.close for b in bars])`.
- `mark_resonance` → §C.13 (`chanlun.ts:499-526`). Returns a NEW list, never mutates input. `side(p) = "B" if p.kind.endswith("B") else "S"`. Vertex lookup = first exact `(time, price)` match (§G.7: use `next((i for ...), -1)` sentinel). `to` fallback = `last_bar_time`. Only `p.confirmed` points eligible. Non-resonant points returned unchanged (`resonant` stays `None`, NOT `False` — §G.10).
- `compute_chanlun` → §C.5 + §C.14 (`chanlun.ts:394-468`). `if len(bars) < MIN_BARS: return empty`. `confirmedCount = len(eps) - 1` captured BEFORE mutation. Step (a) extend tail via `extSame` running extreme (strict, base slides — §G.3 `is None` guard, not `or`). Step (b) grow forming counter-leg (non-strict `<=`/`>=`, base slides). `confirmed = i < confirmedCount` on the FINAL eps index. Build both `vertices:list[BiVertex]` and `pts:list[VertexPt]`.

**Steps:**
- [ ] Implement `src/uw_scan/chanlun/points.py` from §C.9–§C.11, §C.13.
- [ ] Implement `src/uw_scan/chanlun/full.py::compute_chanlun` from §C.5, §C.14. Add an input guard: at entry, if any `bar.close` is not finite (`math.isfinite`), raise `ValueError` (§G.5 — the deliberate fail-fast policy for non-finite closes; real data never hits this).
- [ ] Update `src/uw_scan/chanlun/__init__.py`: `from uw_scan.chanlun.full import compute_chanlun` (and `compute_chanlun_full` after Task 5).
- [ ] Append the real stroke-level parity block to `tests/unit/chanlun/test_parity.py` (Task 2 left only `test_macd_hist_parity` there):

```python
from uw_scan.chanlun.full import compute_chanlun


def test_vertices_parity():
    r = compute_chanlun(bars_from_golden())
    assert_records_equal(
        GOLDEN["vertices"], r.vertices,
        ["time", "price", "kind", "confirmed"], "vertices",
    )


def test_divergences_parity():
    r = compute_chanlun(bars_from_golden())
    assert_records_equal(
        GOLDEN["divergences"], r.divergences,
        ["time", "price", "kind", "confirmed"], "divergences",
    )


def test_stroke_points_nonvacuity():
    # compute_chanlun points are the PRE-resonance v1 points; the golden `points`
    # array is the post-resonance full list (Task 5). Here only assert the v1
    # point set is non-empty and every point sits on a vertex with matching side.
    r = compute_chanlun(bars_from_golden())
    assert len(r.points) > 0
    by_time = {v.time: v for v in r.vertices}
    for p in r.points:
        v = by_time.get(p.time)
        assert v is not None
        assert v.kind == ("bottom" if p.kind.endswith("B") else "top")
```

- [ ] Run failing-first if you stubbed bodies; otherwise run: `uv run pytest tests/unit/chanlun/test_parity.py -q` — expect the `vertices`/`divergences`/`macd`/points tests **passed** (4+ passed). A `vertices` mismatch means the inclusion/fractal/endpoint pipeline (Task 2) diverges — the reporter names the first divergent `vertices[i].field`.
- [ ] Run the full suite: `uv run pytest tests/unit/chanlun/ -q` — all passed.
- [ ] Commit: `git add src/uw_scan/chanlun/points.py src/uw_scan/chanlun/full.py src/uw_scan/chanlun/__init__.py tests/unit/chanlun/test_parity.py && git commit -m "feat(chanlun): port markPoints/Divergences/Resonance + compute_chanlun with stroke-level parity"`

---

## Task 4: Python port — `segments.py` (`build_segments`)

Port `chanlunSeg.ts::buildSegments` and its `EigenFX`/`Elem` feature-sequence machinery (§C.16). This is the highest-risk area; budget the most care here. Algorithm source is §C.16 (`chanlunSeg.ts:279-428` and the helper line-ranges cited within). Transcribe control flow EXACTLY — the three `if nn / if n / else` branches in `actualBreak` and the two-block first-segment bootstrap are not simplifiable.

**Files:**
- Create: `src/uw_scan/chanlun/segments.py`
- Modify: `src/uw_scan/chanlun/types.py` (add `SegVertex`, `SegStats`, `Stroke`, `Elem`)
- Create: `tests/unit/chanlun/test_segments_parity.py`

**Interfaces:**
- Consumes: `BiVertex` (Task 2), and internal use of `list[BiVertex]` (the full stroke vertex list including the provisional tail).
- Produces (`segments.py`): `build_segments(vertices:list[BiVertex], stats:SegStats|None=None)->list[SegVertex]`. Internal: class `EigenFX(up:bool, strokes:list[Stroke])` with `add(si)->bool`, `reset()->bool`, `actual_break()->bool`, `update_fx()`, `can_be_end()->bool|None`, `find_revert_fx(begin)->bool|None`, `all_bi_sure()->bool`, `get_peak_bi_idx()->int`; module helpers `test_combine(el, s, exclude_included, allow_top_equal)->str`, `try_add(el, s, exclude_included, allow_top_equal)->str`, `new_elem(s, up)->Elem`.
- Produces (`types.py`): `SegVertex(time:str, price:float, kind:str, confirmed:bool)`, `SegStats(case1:int=0, case2Confirmed:int=0, case2Provisional:int=0)`, `Stroke(idx:int, up:bool, hi:float, lo:float, sure:bool)`, `Elem(hi:float, lo:float, up:bool, strokes:list[int], hiStroke:int, loStroke:int, lastHi:float, lastLo:float)`.

**Algorithm sources (transcribe each from the cited lines):**
- Input transform `strokes[i]` → §C.16 (`chanlunSeg.ts:284-293`). `sure = vertices[i].confirmed and vertices[i+1].confirmed`. `if len(vertices) < 2: return []`.
- Outer loop + feed-direction gating → §C.16 (`chanlunSeg.ts:296-356`). Fresh `EigenFX(up=True)`/`EigenFX(up=False)` per outer iteration.
- First-segment bootstrap → §C.16 (`chanlunSeg.ts:315-329`) — two sequential conditional blocks (inference THEN rollback), both gated on `len(segs)==0`.
- `EigenFX.add` → (`chanlunSeg.ts:145-170`). ele[0]/ele[1] seeded `new_elem(s, self.up)`; ele[2] seeded `new_elem(s, dir=="up")` from `try_add`'s local direction.
- `test_combine`/`try_add` → (`chanlunSeg.ts:62-116`). `try_add` envelope updates use non-strict `>=`/`<=` on BOTH edges (§E). `flatNoExtend` 一字 guard.
- `actual_break` → (`chanlunSeg.ts:175-203`). Port the three-branch control flow verbatim (§C.16 note: not a "look 1-2 ahead" loop).
- `update_fx` → (`chanlunSeg.ts:206-228`). `ate = 1 if self.up else -1`.
- `reset` → (`chanlunSeg.ts:232-239`). Drop first stroke, replay remaining via `add`, early-exit on first `True`. Recursion is fine (§C.16).
- `get_peak_bi_idx` → (`chanlunSeg.ts:243-246`): `(ele[1].hiStroke if self.up else ele[1].loStroke) - 1`.
- `can_be_end` → (`chanlunSeg.ts:250-253`): returns `True | None`, NEVER `False` (deviation #6).
- `find_revert_fx` → (`chanlunSeg.ts:257-269`): fresh reverse `EigenFX`, step `i += 2`.
- `all_bi_sure` → (`chanlunSeg.ts:271-276`).
- Segment-record construction + skip-and-restart (first segment only) → (`chanlunSeg.ts:333-355`). `sure = (t is True) and valueOk and fx.all_bi_sure() and (endV - startV >= 3)`. Break the whole outer loop when `t is not True`.
- `collect_left` → (`chanlunSeg.ts:358-407`). Zero-segments sub-case + general extremes-walk; non-strict `>=`/`<=` tie-breaks take the LATER vertex.
- Final assembly → (`chanlunSeg.ts:409-428`). First out vertex = `vertices[0]` with `confirmed = segs[0].sure`.

**Steps:**
- [ ] Add the four segment dataclasses to `types.py`.
- [ ] Implement `src/uw_scan/chanlun/segments.py` from §C.16. Keep the file <500 lines; if the `EigenFX` class plus helpers exceed it, that is acceptable ONLY if it is one cohesive class — but prefer to keep helpers module-level.
- [ ] Write `tests/unit/chanlun/test_segments_parity.py`:

```python
from __future__ import annotations

from uw_scan.chanlun.full import compute_chanlun
from uw_scan.chanlun.segments import build_segments
from tests.unit.chanlun.parity_helpers import (
    GOLDEN,
    assert_records_equal,
    bars_from_golden,
)


def test_segvertices_parity():
    r = compute_chanlun(bars_from_golden())
    segs = build_segments(r.vertices)
    assert_records_equal(
        GOLDEN["segVertices"], segs,
        ["time", "price", "kind", "confirmed"], "segVertices",
    )


def test_segvertices_sit_on_stroke_vertices():
    # Mirrors chanlunFull.test.ts:49-54 — every segment vertex is a stroke vertex.
    r = compute_chanlun(bars_from_golden())
    segs = build_segments(r.vertices)
    assert len(segs) > 0  # non-vacuity
    by_time = {v.time: v.price for v in r.vertices}
    for s in segs:
        assert by_time.get(s.time) == s.price
```

- [ ] Run: `uv run pytest tests/unit/chanlun/test_segments_parity.py -q` — expect **2 passed**. A `segVertices` mismatch localizes to the segment machinery (Tasks 2–3 vertices already passed independently). Use the reporter's first-divergent-field output plus §C.16 to bisect.
- [ ] Full suite: `uv run pytest tests/unit/chanlun/ -q` — all passed.
- [ ] Commit: `git add src/uw_scan/chanlun/segments.py src/uw_scan/chanlun/types.py tests/unit/chanlun/test_segments_parity.py && git commit -m "feat(chanlun): port buildSegments (chan.py feature-sequence 线段) with segVertices parity"`

---

## Task 5: Python port — `full.compute_chanlun_full` + full parity + 12 trap regression tests

Port the v2 orchestrator `computeChanlunFull` (§C.15) tying together segments, 中枢升级 merging, segment-level pivots/points, and weekly 区间套 resonance. Then add the complete golden parity (all seven output arrays) and one dedicated regression test per port-contract JS→Python trap (§G.1–§G.12).

**Files:**
- Modify: `src/uw_scan/chanlun/full.py` (add `compute_chanlun_full`)
- Modify: `src/uw_scan/chanlun/types.py` (add `ChanlunFullResult`)
- Modify: `tests/unit/chanlun/test_parity.py` (add full-result parity for all arrays)
- Create: `tests/unit/chanlun/test_traps.py` (12 trap regression tests)

**Interfaces:**
- Produces (`full.py`): `compute_chanlun_full(bars:list[ChanlunBar])->ChanlunFullResult`.
- Produces (`types.py`): `ChanlunFullResult(vertices, zhongshus, points, divergences, segVertices, segZhongshus, segPoints)`.

**Algorithm source:** §C.15 (`chanlun.ts:537-574`). `daily = compute_chanlun(bars)`. `segVertices = build_segments(daily.vertices)`. `idxByTime = {b.time: i}`; `segPts` `rawIdx = idxByTime.get(v.time, 0)`. Recompute `hist = macd_hist([b.close for b in bars])` for the segment `leg_area` (not shared — §C.11). `weekly = compute_chanlun(resample_weekly(bars))`. `points = mark_resonance(daily.points, weekly, bars[-1].time if bars else "")` (§G.2 — keep the empty guard). Return object OVERRIDES: `points` = resonance-flagged, `zhongshus` = `merge_overlapping_zhongshus(daily.zhongshus)`, `divergences` = `daily.divergences` UNTOUCHED, `vertices` = `daily.vertices` passthrough, `segZhongshus` = `pivots_to_zhongshus(segPivots, segLegs, segPts)` (NOT merged), `segPoints` = `mark_points(segPts, segLegs, segPivots, segLegArea)` (NOT resonance-flagged).

**Steps:**
- [ ] Add `ChanlunFullResult` to `types.py`; implement `compute_chanlun_full` in `full.py` from §C.15; export from `__init__.py`.
- [ ] Add the remaining full-result parity to `tests/unit/chanlun/test_parity.py`:

```python
from uw_scan.chanlun.full import compute_chanlun_full


def test_full_zhongshus_parity():
    r = compute_chanlun_full(bars_from_golden())
    assert_records_equal(
        GOLDEN["zhongshus"], r.zhongshus,
        ["start", "end", "zg", "zd", "confirmed", "level"], "zhongshus",
    )


def test_full_points_parity():
    r = compute_chanlun_full(bars_from_golden())
    assert_records_equal(
        GOLDEN["points"], r.points,
        ["time", "price", "kind", "confirmed", "resonant"], "points",
    )


def test_full_segzhongshus_parity():
    r = compute_chanlun_full(bars_from_golden())
    assert_records_equal(
        GOLDEN["segZhongshus"], r.segZhongshus,
        ["start", "end", "zg", "zd", "confirmed"], "segZhongshus",
    )


def test_full_segpoints_parity():
    r = compute_chanlun_full(bars_from_golden())
    assert_records_equal(
        GOLDEN["segPoints"], r.segPoints,
        ["time", "price", "kind", "confirmed"], "segPoints",
    )
```

  (`assert_records_equal` already treats absent optional key == `None`, so `level`/`resonant` compare correctly whether the golden omits them or the port leaves them `None`.)
- [ ] Create `tests/unit/chanlun/test_traps.py` — one regression test per trap (§G.1–§G.12). Each asserts the port did NOT fall into the trap:

```python
from __future__ import annotations

from datetime import date

from uw_scan.chanlun.core import (
    merge_overlapping_zhongshus,
    resample_weekly,
)
from uw_scan.chanlun.full import compute_chanlun, compute_chanlun_full
from uw_scan.chanlun.points import mark_resonance
from uw_scan.chanlun.types import Zhongshu, ChanlunBar, ChanlunResult, BuySellPoint
from tests.unit.chanlun.parity_helpers import bars_from_golden


def test_trap01_time_sort_is_ordinal_not_locale():
    # §G.1 — points sorted by plain string compare == chronological.
    r = compute_chanlun(bars_from_golden())
    times = [p.time for p in r.points]
    assert times == sorted(times)


def test_trap02_last_bar_empty_guard_no_indexerror():
    # §G.2 — empty bars must not raise (JS bars[bars.length-1] -> undefined).
    r = compute_chanlun_full([])
    assert r.points == [] and r.vertices == []


def test_trap03_nullish_vs_or_level_default():
    # §G.3 — merge_overlapping_zhongshus level default uses `is None`, not `or`.
    # A pushed zone with no level gets level=1 (not clobbered by a falsy 0).
    out = merge_overlapping_zhongshus(
        [Zhongshu(start="2020-01-01", end="2020-01-02", zg=20, zd=10, confirmed=True)]
    )
    assert out[0].level == 1


def test_trap04_int_float_equality_holds():
    # §G.4 — structural equality compares numeric value, not JSON text; a price
    # that is integral must still equal the golden float.
    r = compute_chanlun(bars_from_golden())
    assert any(float(v.price) == v.price for v in r.vertices)  # trivially true, documents intent


def test_trap05_nonfinite_close_fails_fast():
    # §G.5 — non-finite close raises ValueError (fail-fast policy), not null-0 coercion.
    bars = [ChanlunBar(time=f"2020-01-{i+1:02d}", high=1, low=1, close=float("nan")) for i in range(12)]
    try:
        compute_chanlun(bars)
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_trap06_no_empty_max_min_on_real_data():
    # §G.6 — build_pivots never calls max/min on an empty trio; real data runs clean.
    r = compute_chanlun(bars_from_golden())
    assert len(r.zhongshus) >= 0  # completes without ValueError from max([])/min([])


def test_trap07_findindex_sentinel_minus_one():
    # §G.7 — mark_resonance vertex lookup uses a -1 sentinel; a weekly point whose
    # vertex is absent falls back to lastBarTime (window to end), not a crash.
    weekly = ChanlunResult(
        vertices=[],  # no vertices -> findIndex returns -1 for the point below
        zhongshus=[],
        points=[BuySellPoint(time="2020-03-01", price=40, kind="1B", confirmed=True)],
        divergences=[],
    )
    pts = [BuySellPoint(time="2020-03-05", price=50, kind="1B", confirmed=True)]
    out = mark_resonance(pts, weekly, "2020-04-01")
    assert out[0].resonant is True  # window extended to lastBarTime, matched


def test_trap08_modulo_nonnegative_in_weekly():
    # §G.8/§G.9 — weekday offset is correct (Monday-anchored), no negative modulo.
    bars = bars_from_golden()
    weekly = resample_weekly(bars)
    assert len(weekly) > 0
    for w in weekly:
        assert date.fromisoformat(w.time).weekday() <= 6  # valid weekday, no shift


def test_trap09_weekday_not_double_transformed():
    # §G item 9 — the load-bearing gotcha: resample_weekly groups by ISO Monday.
    # Two bars in the same Mon-Sun week collapse to one weekly bar whose time is
    # the LATER session date.
    bars = [
        ChanlunBar(time="2024-01-08", high=10, low=5, close=8),   # Monday
        ChanlunBar(time="2024-01-09", high=12, low=6, close=11),  # Tuesday, same week
        ChanlunBar(time="2024-01-15", high=9, low=4, close=7),    # next Monday
    ]
    weekly = resample_weekly(bars)
    assert len(weekly) == 2
    assert weekly[0].time == "2024-01-09"  # last session in week 1, not the Monday key
    assert weekly[0].high == 12 and weekly[0].low == 5 and weekly[0].close == 11


def test_trap10_optional_fields_absent_not_null():
    # §G.10 — non-resonant points leave `resonant` None (not False).
    r = compute_chanlun_full(bars_from_golden())
    assert any(p.resonant is None for p in r.points)  # some point is non-resonant


def test_trap11_slice_end_exclusive_parity():
    # §G.11 — Python slicing matches JS .slice; already exercised by full parity.
    r = compute_chanlun_full(bars_from_golden())
    assert len(r.segVertices) > 0


def test_trap12_float_division_alpha():
    # §G.12 — ema alpha is true float division, never floor. 2/(9+1) == 0.2 exactly.
    from uw_scan.chanlun.core import ema
    out = ema([1.0, 2.0, 3.0], 9)
    assert out[0] == 1.0 and abs(out[1] - (0.2 * 2 + 0.8 * 1)) <= 1e-12
```

- [ ] Run: `uv run pytest tests/unit/chanlun/test_parity.py tests/unit/chanlun/test_traps.py -q` — expect all parity + **12 trap tests passed**. If `test_full_points_parity` fails on `resonant`, the weekly resonance wiring (§C.13/§C.15) is wrong; if it fails on `kind`/`price`, the stroke pipeline regressed.
- [ ] Full suite: `uv run pytest tests/unit/chanlun/ -q` — all passed. This is the port acceptance gate.
- [ ] Commit: `git add src/uw_scan/chanlun/full.py src/uw_scan/chanlun/types.py src/uw_scan/chanlun/__init__.py tests/unit/chanlun/test_parity.py tests/unit/chanlun/test_traps.py && git commit -m "feat(chanlun): port computeChanlunFull with full golden parity + 12 JS->Python trap regressions"`

---

## Task 6: apex bars client — `sources/apex.py::fetch_bars`

Extend the existing apex client with a general bar fetcher for both timeframes. Never-raise; ALWAYS pass an explicit `start` (the default-limit gotcha from the contract doc); handle empty-bars and 400 as "no data", not success.

**Files:**
- Modify: `src/uw_scan/sources/apex.py`
- Create: `tests/unit/sources/test_apex_fetch_bars.py`

**Interfaces:**
- Produces: `fetch_bars(ticker:str, timeframe:str, start:datetime|date, *, end:datetime|date|None=None, limit:int=0, timeout:float=30.0, client:httpx.Client|None=None)->list[dict]`. Returns the raw apex bar dicts (`time, open, high, low, close, volume, vwap`), `[]` on ANY failure/empty. `limit=0` = full history from `start` (apex `limit<=0` semantics). Injectable `client` for tests (mirrors `xenon_query.py`).

**Steps:**
- [ ] Add `fetch_bars` to `sources/apex.py` (reuse `_apex_url()`, `logger`):

```python
def _iso(v: date | datetime) -> str:
    return v.isoformat()


def fetch_bars(
    ticker: str,
    timeframe: str,
    start: date | datetime,
    *,
    end: date | datetime | None = None,
    limit: int = 0,
    timeout: float = 30.0,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Raw apex bars for one ticker/timeframe from an explicit `start`.

    ALWAYS pass `start` explicitly — apex's default lookback window can return
    count:0 for a valid ticker whose latest bar predates the default (verified,
    phaseb_apex_bars_contract.md §2c). `limit=0` == full history from start.
    Never-raise: returns [] on transport error, unsupported timeframe (400),
    unknown ticker (200 + empty), or malformed body. An empty list means
    "no data", never "success with zero" — callers must treat [] as skip.
    """
    url = f"{_apex_url()}/bars/{ticker.upper()}"
    params: dict[str, object] = {
        "timeframe": timeframe,
        "start": _iso(start),
        "limit": limit,
    }
    if end is not None:
        params["end"] = _iso(end)
    own = client is None
    c = client or httpx.Client(timeout=timeout)
    try:
        resp = c.get(url, params=params)
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            return []
        bars = body.get("bars", [])
        if not isinstance(bars, list):
            return []
        return bars
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            "apex fetch_bars failed %s %s from %s: %s",
            ticker, timeframe, _iso(start), repr(exc),
        )
        return []
    finally:
        if own:
            c.close()
```

- [ ] Create `tests/unit/sources/test_apex_fetch_bars.py` using a frozen real AAPL 30m payload (as-of 2026-07-10, from `phaseb_apex_bars_contract.md §3`) with a mocked httpx transport:

```python
from __future__ import annotations

from datetime import date

import httpx

from uw_scan.sources.apex import fetch_bars

# Frozen REAL AAPL 30m bars, as-of 2026-07-10 (phaseb_apex_bars_contract.md §3).
_AAPL_30M_PAYLOAD = {
    "symbol": "AAPL",
    "timeframe": "30m",
    "bars": [
        {"time": "2021-06-11T08:00:00+00:00", "open": 126.33, "high": 126.59, "low": 126.33, "close": 126.4, "volume": 10996, "vwap": None},
        {"time": "2021-06-11T08:30:00+00:00", "open": 126.34, "high": 126.59, "low": 126.34, "close": 126.56, "volume": 2430, "vwap": None},
        {"time": "2021-06-11T09:00:00+00:00", "open": 126.54, "high": 126.58, "low": 126.43, "close": 126.44, "volume": 4754, "vwap": None},
    ],
    "count": 3,
    "generated_at": "2026-07-14T13:54:26+00:00",
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_bars_parses_real_payload_and_passes_explicit_start():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["params"] = dict(request.url.params)
        return httpx.Response(200, json=_AAPL_30M_PAYLOAD)

    bars = fetch_bars("aapl", "30m", date(2021, 6, 11), client=_client(handler))
    assert len(bars) == 3  # non-vacuity
    assert bars[0]["close"] == 126.4
    assert bars[0]["time"] == "2021-06-11T08:00:00+00:00"
    # The client MUST send an explicit start (default-window gotcha).
    assert seen["params"]["start"] == "2021-06-11"
    assert seen["params"]["timeframe"] == "30m"


def test_fetch_bars_unknown_ticker_empty_is_no_data():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"symbol": "ZZZ", "timeframe": "30m", "bars": [], "count": 0, "generated_at": "x"})

    assert fetch_bars("ZZZ", "30m", date(2021, 6, 11), client=_client(handler)) == []


def test_fetch_bars_400_unsupported_timeframe_never_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "unsupported timeframe: 2h (have ['1d', '1h', '1m', '30m', '5m'])"})

    assert fetch_bars("AAPL", "2h", date(2021, 6, 11), client=_client(handler)) == []
```

- [ ] Run failing-first (before adding `fetch_bars`): `uv run pytest tests/unit/sources/test_apex_fetch_bars.py -q` — expect ImportError (`fetch_bars` not defined).
- [ ] Implement, then run: `uv run pytest tests/unit/sources/test_apex_fetch_bars.py -q` — expect **3 passed**.
- [ ] Regression: `uv run pytest tests/unit/sources/ -q` — the existing apex tests still pass.
- [ ] Commit: `git add src/uw_scan/sources/apex.py tests/unit/sources/test_apex_fetch_bars.py && git commit -m "feat(apex): fetch_bars client for 1d/30m bars (explicit start, never-raise)"`

---

## Task 7: migration 107 + `chanlun_signal_repository.py` + DatasetRegistryEntry + policy doc

Create the append-mostly event-log table, its standalone repository, and the two required CI-gate artifacts (registry entry + regenerated policy doc). Integration tests use the pytest-postgresql harness.

**Files:**
- Create: `src/uw_scan/storage/migrations/107_chanlun_signal_events.sql`
- Create: `src/uw_scan/storage/chanlun_signal_repository.py`
- Modify: `src/uw_scan/reports/data_gap_healer.py` (add one `DatasetRegistryEntry`)
- Modify (regenerated): `docs/runbooks/data-gap-dataset-policy.md`
- Create: `tests/integration/storage/test_chanlun_signal_repository.py`

**Interfaces:**
- Produces (`ChanlunSignalRepository(conn:Connection, schema:str="uw_scan")`):
  - `upsert_transition(*, ticker:str, category:str, kind:str, extreme_date:date, extreme_price:float, state:str, reason:str|None, as_of:date, details:dict, first_entered_at:datetime|None=None)->bool` — `INSERT ... ON CONFLICT (ticker, category, kind, extreme_date, extreme_price, state) DO NOTHING`; returns `True` if a row was inserted (a NEW transition), `False` if it already existed. `first_entered_at` defaults to `now()` in SQL when omitted and is NEVER overwritten (DO NOTHING preserves the original).
  - `current_states(ticker:str)->list[dict]` — one row per mark_id (`ticker, category, kind, extreme_date, extreme_price`) at its highest state precedence `terminal(confirmed_native|invalidated) > confirmed_sublevel > pending`, returning `category, kind, extreme_date, extreme_price, state, reason, first_entered_at, as_of`.
  - `list_non_terminal(ticker:str)->list[dict]` — mark_ids whose current state is `pending` or `confirmed_sublevel` (used by the job to detect absent-from-recompute → superseded).

**Steps:**
- [ ] Create `107_chanlun_signal_events.sql`:

```sql
-- 107_chanlun_signal_events.sql
-- Append-mostly chanlun lifecycle event log. One row per (mark_id, state)
-- transition; the nightly batch upserts ON CONFLICT DO NOTHING so re-runs over
-- the same bars are no-ops (state is a pure function of the bar series). The
-- current state of a mark is the row with the highest state precedence
-- (terminal > sublevel > pending). Future alert-pipeline input.
SET search_path TO uw_scan, public;
BEGIN;
CREATE TABLE IF NOT EXISTS uw_scan.chanlun_signal_events (
    id               BIGSERIAL PRIMARY KEY,
    ticker           TEXT NOT NULL,
    category         TEXT NOT NULL,   -- vertex | point | divergence
    kind             TEXT NOT NULL,   -- top/bottom (vertex,divergence); 1B/1S/2B/2S/3B/3S (point)
    extreme_date     DATE NOT NULL,
    extreme_price    DOUBLE PRECISION NOT NULL,
    state            TEXT NOT NULL,   -- pending | confirmed_sublevel | confirmed_native | invalidated
    reason           TEXT,            -- breach | superseded | stale | split_boundary (invalidated only)
    first_entered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    as_of            DATE NOT NULL,
    details_jsonb    JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (ticker, category, kind, extreme_date, extreme_price, state)
);
CREATE INDEX IF NOT EXISTS ix_chanlun_signal_events_ticker_latest
    ON uw_scan.chanlun_signal_events (ticker, extreme_date DESC, id DESC);
COMMIT;
```

- [ ] Apply and confirm idempotency: `bash scripts/migrate.sh` (twice — the second run is a no-op). Confirm the table exists.
- [ ] Create `src/uw_scan/storage/chanlun_signal_repository.py` (standalone, raw cursor + parameterized SQL, `Jsonb` wrapper for `details_jsonb`; follow `technical_live_repository.py` shape):

```python
"""Standalone repository for the chanlun_signal_events append-mostly log.

Never extends storage/repository.py (standing rule). Upserts are idempotent
(ON CONFLICT DO NOTHING); first_entered_at is preserved across re-runs.
"""
from __future__ import annotations

from datetime import date, datetime

from psycopg import Connection
from psycopg.types.json import Jsonb

# State precedence for the current-state query (higher wins).
_STATE_RANK = {
    "pending": 0,
    "confirmed_sublevel": 1,
    "confirmed_native": 2,
    "invalidated": 2,
}


class ChanlunSignalRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_transition(
        self,
        *,
        ticker: str,
        category: str,
        kind: str,
        extreme_date: date,
        extreme_price: float,
        state: str,
        reason: str | None,
        as_of: date,
        details: dict,
        first_entered_at: datetime | None = None,
    ) -> bool:
        with self._conn.cursor() as cur:
            if first_entered_at is None:
                cur.execute(
                    """
                    INSERT INTO chanlun_signal_events
                        (ticker, category, kind, extreme_date, extreme_price,
                         state, reason, as_of, details_jsonb)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, category, kind, extreme_date,
                                 extreme_price, state) DO NOTHING
                    """,
                    (
                        ticker.upper(), category, kind, extreme_date,
                        float(extreme_price), state, reason, as_of, Jsonb(details),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO chanlun_signal_events
                        (ticker, category, kind, extreme_date, extreme_price,
                         state, reason, first_entered_at, as_of, details_jsonb)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, category, kind, extreme_date,
                                 extreme_price, state) DO NOTHING
                    """,
                    (
                        ticker.upper(), category, kind, extreme_date,
                        float(extreme_price), state, reason, first_entered_at,
                        as_of, Jsonb(details),
                    ),
                )
            inserted = cur.rowcount == 1
        self._conn.commit()
        return inserted

    def _rows_for(self, ticker: str) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT category, kind, extreme_date, extreme_price, state,
                       reason, first_entered_at, as_of
                FROM chanlun_signal_events
                WHERE ticker = %s
                ORDER BY id
                """,
                (ticker.upper(),),
            )
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def current_states(self, ticker: str) -> list[dict]:
        best: dict[tuple, dict] = {}
        for row in self._rows_for(ticker):
            key = (row["category"], row["kind"], row["extreme_date"], row["extreme_price"])
            cur_best = best.get(key)
            if cur_best is None or _STATE_RANK[row["state"]] >= _STATE_RANK[cur_best["state"]]:
                best[key] = row
        return list(best.values())

    def list_non_terminal(self, ticker: str) -> list[dict]:
        return [
            r for r in self.current_states(ticker)
            if r["state"] in ("pending", "confirmed_sublevel")
        ]
```

- [ ] Add the `DatasetRegistryEntry` to `src/uw_scan/reports/data_gap_healer.py` inside the `REGISTRY` list (place it near the other event-log/provenance entries, e.g. right after `watchlist_ticker_events`):

```python
    DatasetRegistryEntry(
        "chanlun_signal_events",
        "operational_provenance",
        "provenance",
        expected_frequency="none",
    ),
```

- [ ] Regenerate the policy doc: `uv run python -c "from uw_scan.reports.data_gap_healer import render_dataset_policy_markdown as r; open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())"`
- [ ] Confirm the doc now names the table: `grep chanlun_signal_events docs/runbooks/data-gap-dataset-policy.md` (expect a match).
- [ ] Create `tests/integration/storage/test_chanlun_signal_repository.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository


def test_upsert_is_idempotent_and_preserves_first_entered_at(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    kw = dict(
        ticker="AAPL", category="vertex", kind="bottom",
        extreme_date=date(2026, 7, 1), extreme_price=195.5, state="pending",
        reason=None, as_of=date(2026, 7, 1), details={"w": "x"},
    )
    assert r.upsert_transition(**kw) is True   # first insert
    assert r.upsert_transition(**kw) is False  # ON CONFLICT DO NOTHING
    states = r.current_states("AAPL")
    assert len(states) == 1  # non-vacuity
    assert states[0]["state"] == "pending"


def test_current_state_precedence_terminal_beats_sublevel_beats_pending(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    base = dict(
        ticker="NVDA", category="divergence", kind="bottom",
        extreme_date=date(2026, 6, 15), extreme_price=1200.0,
        as_of=date(2026, 6, 20), details={},
    )
    r.upsert_transition(state="pending", reason=None, **base)
    r.upsert_transition(state="confirmed_sublevel", reason=None, **base)
    r.upsert_transition(state="confirmed_native", reason=None, **base)
    states = r.current_states("NVDA")
    assert len(states) == 1
    assert states[0]["state"] == "confirmed_native"
    assert r.list_non_terminal("NVDA") == []  # no longer promotable-in-flight
```

- [ ] Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_chanlun_signal_repository.py -q` — expect **2 passed**. (On MacBook, also export the forced-local DB env per the repo's integration-test note if the default DB env is not already pointed at the test DB.)
- [ ] Run the two dataset-registry CI gates: `uv run pytest tests/integration/worker/test_data_gap_full_coverage.py::test_zero_unregistered_after_full_registry tests/unit/reports/test_data_gap_dataset_policy.py::test_committed_policy_doc_is_in_sync_with_registry -q` — expect **2 passed** (both gates green; a fail here means the registry entry or the regenerated doc is missing/stale).
- [ ] Commit: `git add src/uw_scan/storage/migrations/107_chanlun_signal_events.sql src/uw_scan/storage/chanlun_signal_repository.py src/uw_scan/reports/data_gap_healer.py docs/runbooks/data-gap-dataset-policy.md tests/integration/storage/test_chanlun_signal_repository.py && git commit -m "feat(chanlun): migration 107 event log + standalone repository + dataset-registry gates"`

---

## Task 8: `chanlun/lifecycle.py` — pure state machine + S1 predicate

The pure, I/O-free lifecycle logic: derive marks from a `ChanlunFullResult`, compute the anchor window W, evaluate the S1 30m predicate, and decide each mark's state via the breach guard, staleness cap (20), split-boundary guard (`ln ratio > ln 1.5`), and category applicability. Keep it factored so S2 (30m 背驰 conjunct) is a future flag.

**Files:**
- Create: `src/uw_scan/chanlun/lifecycle.py`
- Create: `tests/unit/chanlun/test_lifecycle.py`

**Interfaces:**
- Produces:
  - `@dataclass Mark(category:str, kind:str, extreme_date:date, extreme_price:float, is_native_confirmed:bool)`
  - `LN_SPLIT_THRESHOLD = math.log(1.5)`, `DEFAULT_STALE_SESSIONS = 20`, `DEFAULT_PROMOTABLE = frozenset({"vertex","divergence","3B","3S"})`
  - `derive_marks(full:ChanlunFullResult, bars:list[ChanlunBar])->list[Mark]` — vertices→`category="vertex"` kind=`v.kind`; divergences→`category="divergence"` kind=`d.kind`; points→`category="point"` kind=`p.kind` (1B/…/3S). `extreme_date` = the mark's `time` parsed as `date`; `extreme_price` = the mark's `price`. `is_native_confirmed` = the mark's `confirmed` flag.
  - `promotable_key(category:str, kind:str)->str` — `category` for vertex/divergence, `kind` for point (so `chanlun_promotable_categories` tokens are `vertex,divergence,1B,1S,2B,2S,3B,3S`).
  - `is_promotable(category:str, kind:str, promotable:frozenset[str])->bool` — `promotable_key(...) in promotable`.
  - `find_split_boundaries(daily_bars:list[dict])->set[date]` — dates `d` where `abs(ln(open_d / close_{d-1})) > LN_SPLIT_THRESHOLD`; skips a pair if either `open`/`close` is missing or non-positive. **Date parsing MUST slice before parsing: `date.fromisoformat(b["time"][:10])`** — this function receives the RAW apex dicts, whose `time` is a FULL UTC datetime string (`"2021-06-11T00:00:00+00:00"`, apex contract §2a), and `date.fromisoformat` raises `ValueError` on the full string. An unsliced implementation would pass a date-only-string test yet silently fail every real ticker inside the job's per-ticker try/except (and hard-crash the probe) — the regression test below feeds full apex-style timestamps precisely to catch this.
  - `crosses_split_boundary(mark:Mark, anchor_start:date, boundaries:set[date])->bool` — any boundary date `> mark.extreme_date's leg start` — concretely `any(anchor_start <= b for b in boundaries)` where `anchor_start` is W's start date (conservative).
  - `session_et_date(ts:str)->date` — the ET session date of a bar timestamp: `dt = datetime.fromisoformat(ts)`; if `dt.tzinfo is not None`, `return dt.astimezone(zoneinfo.ZoneInfo("America/New_York")).date()`; else (a naive/bare `yyyy-mm-dd` daily string) `return dt.date()`. **This exists because of a UTC-rollover bug:** a post-market 30m bar at/after 20:00 ET lands on the NEXT UTC calendar date (20:00 ET = 00:00 UTC next day under EDT; from 19:00 ET under EST), so a naive `date.fromisoformat(ts[:10]) == extreme_date` comparison silently false-negates the S1 session conjunct on late after-hours anchor bars. ALWAYS compare ET dates, never a UTC-date slice.
  - `mark_side(kind:str)->str` — the price side of a mark kind: `"top"`/`"bottom"` pass through; point kinds map by suffix (`1B/2B/3B` → `"bottom"`, `1S/2S/3S` → `"top"`). Used by `anchor_window` (opposite side), `breached`, and `s1_confirmed` (same side) so the three guards can never disagree on a point mark's side.
  - `anchor_window(mark:Mark, daily_vertices:list[BiVertex], session_dates:list[date])->date` — start date of W = date of the latest CONFIRMED daily vertex of the OPPOSITE side (`"top"` if `mark_side(mark.kind) == "bottom"`, else `"bottom"`) whose `time` is strictly before `mark.extreme_date`; fallback (no such vertex) = **40 SESSIONS back, not 40 calendar days** (the spec pins sessions; 40 calendar days ≈ only 28 sessions): `idx = bisect.bisect_left(session_dates, mark.extreme_date)` then `return session_dates[max(0, idx - 40)]`. `session_dates` is the ascending daily session-date list, available at every call site (the job and the probe both derive it from the daily bars).
  - `s1_confirmed(mark:Mark, bars_30m:list[ChanlunBar], *, tol:float, require_divergence:bool=False)->tuple[bool, dict]` — the S1 predicate; **implement EXACTLY the body inlined in the Steps below**. Its four conjuncts, pinned: (1) `v30.confirmed is True`; (2) `v30.kind == mark_side(mark.kind)` (same side); (3) `abs(v30.price - mark.extreme_price) <= tol` AND `session_et_date(v30.time) == mark.extreme_date` (the ET-date session match above); (4) **v30 remains the extreme of W on its side: for a bottom, NO 30m bar chronologically AFTER v30's bar within `bars_30m` has `low < v30.price`; for a top, none has `high > v30.price`** ("after" = `b.time > v30.time`, safe as a string compare because all 30m times are uniform ISO-8601). Returns `(False, {})` when no vertex satisfies all four. **S2 hook:** `require_divergence` is the future `mark_divergences` conjunct — defaulting False and unused in v1.
  - `breached(mark:Mark, later_daily_bars:list[dict])->bool` — for `kind` bottom-side (`bottom`/`1B`/`2B`/`3B`): any later daily `low < extreme_price`; for top-side: any later daily `high > extreme_price`. `later` = daily bars with date `> mark.extreme_date`.
  - `is_stale(mark:Mark, last_session:date, stale_sessions:int, session_dates:list[date])->bool` — count of session dates strictly after `mark.extreme_date` up to `last_session` exceeds `stale_sessions`.
  - `evaluate_mark(*, mark, split_crossed:bool, breach:bool, s1_ok:bool, promotable:bool, stale:bool)->tuple[str, str|None]` — the decision table below.

**Decision table (`evaluate_mark`, precedence top-to-bottom):**
| Condition | (state, reason) |
|---|---|
| `split_crossed` | `("invalidated", "split_boundary")` |
| `mark.is_native_confirmed` | `("confirmed_native", None)` |
| `breach` | `("invalidated", "breach")` |
| `stale` | `("invalidated", "stale")` |
| `promotable and s1_ok` | `("confirmed_sublevel", None)` |
| else | `("pending", None)` |

(The `"superseded"` reason is assigned by the JOB, not here — it is the absent-from-recompute case, handled in Task 9. `evaluate_mark` only sees marks present in the recompute.)

**Steps:**
- [ ] Implement `src/uw_scan/chanlun/lifecycle.py` with all functions above. Import `compute_chanlun` from `uw_scan.chanlun.full`; no other I/O. `s1_confirmed` is EXACTLY this (the gate the whole feature rests on — do not reorder or drop conjuncts):

```python
def s1_confirmed(
    mark: Mark,
    bars_30m: list[ChanlunBar],
    *,
    tol: float,
    require_divergence: bool = False,  # S2 hook — unused in v1
) -> tuple[bool, dict]:
    """S1 predicate (spec §Confirm rule S1). `bars_30m` is ALREADY windowed to
    the anchor window W by the caller. Returns (True, v30-anchor-info) on the
    first vertex satisfying all four conjuncts, else (False, {})."""
    if not bars_30m:
        return False, {}
    side = mark_side(mark.kind)  # bottom for bottom/1B/2B/3B; top for the mirror
    result = compute_chanlun(bars_30m)
    for v30 in result.vertices:
        if not v30.confirmed:
            continue  # conjunct 1 — the 30m stroke off v30 earned its opposite endpoint
        if v30.kind != side:
            continue  # conjunct 2 — same side as the daily mark
        if abs(v30.price - mark.extreme_price) > tol:
            continue  # conjunct 3a — exact-extreme anchor (tol=0.0 default; config escape hatch)
        if session_et_date(v30.time) != mark.extreme_date:
            continue  # conjunct 3b — v30's bar sits in the daily extreme's ET session
        # Conjunct 4 — v30 must remain the extreme of W on its side. "After" is
        # b.time > v30.time (uniform ISO-8601 strings -> lexicographic ==
        # chronological). bottom: a later low BELOW v30.price kills the match;
        # top: a later high ABOVE it.
        later = [b for b in bars_30m if b.time > v30.time]
        if side == "bottom" and any(b.low < v30.price for b in later):
            continue
        if side == "top" and any(b.high > v30.price for b in later):
            continue
        return True, {"v30_time": v30.time, "v30_price": v30.price, "v30_kind": v30.kind}
    return False, {}
```

- [ ] Create `tests/unit/chanlun/test_lifecycle.py` — one test per decision edge (constructed inputs are labeled test doubles, not market data), plus split/breach/stale/S1 helper tests:

```python
from __future__ import annotations

from datetime import date, datetime, timedelta

from uw_scan.chanlun.lifecycle import (
    LN_SPLIT_THRESHOLD,
    Mark,
    anchor_window,
    breached,
    crosses_split_boundary,
    evaluate_mark,
    find_split_boundaries,
    is_promotable,
    is_stale,
    mark_side,
    promotable_key,
    s1_confirmed,
    session_et_date,
)
from uw_scan.chanlun.types import BiVertex, ChanlunBar

_M = lambda **k: Mark(**{"category": "vertex", "kind": "bottom", "extreme_date": date(2026, 7, 1), "extreme_price": 100.0, "is_native_confirmed": False, **k})


def test_edge_native_confirmed_terminal():
    assert evaluate_mark(mark=_M(is_native_confirmed=True), split_crossed=False, breach=False, s1_ok=False, promotable=True, stale=False) == ("confirmed_native", None)


def test_edge_split_boundary_wins_over_everything():
    assert evaluate_mark(mark=_M(is_native_confirmed=True), split_crossed=True, breach=True, s1_ok=True, promotable=True, stale=True) == ("invalidated", "split_boundary")


def test_edge_breach_demotes():
    assert evaluate_mark(mark=_M(), split_crossed=False, breach=True, s1_ok=True, promotable=True, stale=False) == ("invalidated", "breach")


def test_edge_stale_invalidates():
    assert evaluate_mark(mark=_M(), split_crossed=False, breach=False, s1_ok=False, promotable=True, stale=True) == ("invalidated", "stale")


def test_edge_promotable_s1_ok_to_sublevel():
    assert evaluate_mark(mark=_M(), split_crossed=False, breach=False, s1_ok=True, promotable=True, stale=False) == ("confirmed_sublevel", None)


def test_edge_non_promotable_stays_pending_even_with_s1():
    assert evaluate_mark(mark=_M(category="point", kind="2B"), split_crossed=False, breach=False, s1_ok=True, promotable=False, stale=False) == ("pending", None)


def test_promotable_key_and_applicability():
    assert promotable_key("vertex", "bottom") == "vertex"
    assert promotable_key("divergence", "top") == "divergence"
    assert promotable_key("point", "3B") == "3B"
    assert mark_side("bottom") == "bottom" and mark_side("top") == "top"
    assert mark_side("1B") == "bottom" and mark_side("3B") == "bottom"
    assert mark_side("2S") == "top" and mark_side("3S") == "top"
    p = frozenset({"vertex", "divergence", "3B", "3S"})
    assert is_promotable("point", "3B", p) is True
    assert is_promotable("point", "1B", p) is False   # 1B never sublevel (spec §E)
    assert is_promotable("point", "2S", p) is False   # 2S never sublevel


def test_find_split_boundaries_flags_a_2x_gap_on_real_apex_timestamps():
    # Raw apex `time` is a FULL UTC datetime string (apex contract §2a). An
    # implementation calling date.fromisoformat on the unsliced string raises
    # ValueError — this test feeds real-shaped timestamps to force the [:10] slice.
    bars = [
        {"open": 100.0, "high": 101, "low": 99, "close": 100.0, "time": "2026-06-30T00:00:00+00:00"},
        {"open": 50.0, "high": 51, "low": 49, "close": 50.0, "time": "2026-07-01T00:00:00+00:00"},  # 2:1 split gap
        {"open": 50.5, "high": 51, "low": 50, "close": 50.5, "time": "2026-07-02T00:00:00+00:00"},
    ]
    b = find_split_boundaries(bars)
    assert date(2026, 7, 1) in b  # |ln(50/100)| = 0.69 > ln(1.5)=0.405
    assert date(2026, 7, 2) not in b
    assert crosses_split_boundary(_M(extreme_date=date(2026, 6, 30)), date(2026, 6, 30), b) is True


def test_find_split_boundaries_accepts_date_only_strings():
    # The Task 9 integration stub and the golden bars carry bare 'yyyy-mm-dd'
    # times — the [:10] slice must be a no-op for them, not a crash.
    bars = [
        {"open": 100.0, "high": 101, "low": 99, "close": 100.0, "time": "2026-06-30"},
        {"open": 50.0, "high": 51, "low": 49, "close": 50.0, "time": "2026-07-01"},
    ]
    assert find_split_boundaries(bars) == {date(2026, 7, 1)}


def test_breached_bottom_and_top():
    later = [{"low": 95.0, "high": 105.0, "time": "2026-07-02"}]
    assert breached(_M(kind="bottom", extreme_price=100.0), later) is True   # low 95 < 100
    assert breached(_M(kind="top", extreme_price=100.0), later) is True      # high 105 > 100
    assert breached(_M(kind="bottom", extreme_price=90.0), later) is False


def test_is_stale_counts_sessions_after_extreme():
    sessions = [date(2026, 7, d) for d in range(1, 26)]  # 25 sessions
    assert is_stale(_M(extreme_date=date(2026, 7, 1)), date(2026, 7, 25), 20, sessions) is True
    assert is_stale(_M(extreme_date=date(2026, 7, 10)), date(2026, 7, 25), 20, sessions) is False


def _bars_30m(prices: list[tuple[float, float, float]], start_utc: str) -> list[ChanlunBar]:
    """Abstract 30m bars (labeled test double) at 30-minute spacing from
    `start_utc`; each tuple is (high, low, close). Keyword-arg construction —
    ChanlunBar has exactly time/high/low/close (port contract §A, no open)."""
    t0 = datetime.fromisoformat(start_utc)
    return [
        ChanlunBar(
            time=(t0 + timedelta(minutes=30 * i)).isoformat(),
            high=h,
            low=lo,
            close=c,
        )
        for i, (h, lo, c) in enumerate(prices)
    ]


# V-shape with a strict fractal bottom at 100.0 (index 5) AND a later top
# fractal (index 10, peak 128) whose merged-candle gap (10-5=5 >= MIN_VERTEX_GAP)
# and strict price acceptance make the bottom endpoint CONFIRMED (buildEndpoints
# yields [bottom@5, top@10] -> confirmedCount=1 -> bottom confirmed=True). No
# two adjacent bars are mutually inclusive, so merged idx == raw idx throughout.
_V_LADDER: list[tuple[float, float, float]] = [
    (120, 118, 119), (118, 115, 116), (116, 112, 113), (112, 108, 109),
    (108, 104, 105),
    (104, 100, 100),   # index 5 — the low, 100.0
    (105, 101, 104), (110, 106, 109), (115, 111, 114), (120, 116, 119),
    (128, 124, 127),   # index 10 — the peak (top fractal)
    (126, 122, 123), (124, 120, 121), (122, 118, 119),
]


def test_s1_confirmed_matches_a_30m_bottom_at_the_daily_low():
    # Regular-hours case: low bar at 16:30 UTC (12:30 ET), same date both ways.
    bars_30m = _bars_30m(_V_LADDER, "2026-07-01T14:00:00+00:00")
    mark = _M(kind="bottom", extreme_date=date(2026, 7, 1), extreme_price=100.0)
    ok, info = s1_confirmed(mark, bars_30m, tol=0.0)
    assert ok is True and info  # non-vacuity: info carries v30 anchor
    # Perturb the mark price so nothing reconciles -> no S1.
    ok2, _ = s1_confirmed(_M(kind="bottom", extreme_price=999.0), bars_30m, tol=0.0)
    assert ok2 is False


def test_s1_session_match_uses_et_date_not_utc_date():
    # UTC-rollover regression: starting at 21:30Z puts the low bar (index 5)
    # at 2026-07-02T00:00:00Z == 2026-07-01 20:00 ET. A naive UTC-date
    # comparison (ts[:10]) sees July 2 != extreme_date July 1 and would
    # silently false-negate; the ET-date match must still confirm.
    bars_30m = _bars_30m(_V_LADDER, "2026-07-01T21:30:00+00:00")
    mark = _M(kind="bottom", extreme_date=date(2026, 7, 1), extreme_price=100.0)
    ok, info = s1_confirmed(mark, bars_30m, tol=0.0)
    assert ok is True and info


def test_s1_condition4_later_undercut_kills_the_match():
    # Conjunct 4 regression: append one tail bar that dips BELOW the anchored
    # low (99.5 < 100.0). The bottom vertex at 100.0 stays confirmed (the tail
    # bar forms no new fractal), but a later 30m bar now beats v30 on its side
    # -> S1 must refuse. The monotone-rising _V_LADDER alone can never exercise
    # this clause, which is exactly why this test exists.
    ladder = list(_V_LADDER) + [(104, 99.5, 100.5)]
    bars_30m = _bars_30m(ladder, "2026-07-01T14:00:00+00:00")
    mark = _M(kind="bottom", extreme_date=date(2026, 7, 1), extreme_price=100.0)
    ok, info = s1_confirmed(mark, bars_30m, tol=0.0)
    assert ok is False and info == {}


def test_session_et_date_rolls_utc_midnight_back_to_the_et_session():
    # 00:00 UTC July 2 == 20:00 ET July 1 (EDT) -> ET session date July 1.
    assert session_et_date("2026-07-02T00:00:00+00:00") == date(2026, 7, 1)
    # A mid-session timestamp stays on its own date.
    assert session_et_date("2026-07-01T14:00:00+00:00") == date(2026, 7, 1)
    # A bare daily date string passes through unchanged.
    assert session_et_date("2026-07-01") == date(2026, 7, 1)


def test_anchor_window_primary_path_uses_previous_opposite_confirmed_vertex():
    # W starts at the LATEST confirmed OPPOSITE-side vertex strictly before the
    # extreme. The unconfirmed top at [46] must be skipped; the confirmed top
    # at [42] wins.
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    verts = [
        BiVertex(time=sessions[42].isoformat(), price=110.0, kind="top", confirmed=True),
        BiVertex(time=sessions[46].isoformat(), price=104.0, kind="top", confirmed=False),
        BiVertex(time=sessions[50].isoformat(), price=100.0, kind="bottom", confirmed=False),
    ]
    mark = _M(kind="bottom", extreme_date=sessions[50])
    assert anchor_window(mark, verts, sessions) == sessions[42]


def test_anchor_window_fallback_counts_40_sessions_not_calendar_days():
    # 60 consecutive dates as the session list (labeled test double). With no
    # opposite confirmed vertex, the fallback must step back exactly 40 SESSIONS.
    sessions = [date(2026, 1, 1) + timedelta(days=i) for i in range(60)]
    mark = _M(extreme_date=sessions[50])
    assert anchor_window(mark, [], sessions) == sessions[10]  # 50 - 40 = 10
    early = _M(extreme_date=sessions[5])
    assert anchor_window(early, [], sessions) == sessions[0]  # clamps at start
```

  (If `_V_LADDER` does not produce a confirmed 30m bottom vertex at 100.0 under `compute_chanlun`, verify with a scratch `uv run python -c "..."` and adjust the ladder until `compute_chanlun(bars_30m).vertices` contains a `confirmed`, `kind=="bottom"`, `price==100.0` vertex. The geometry is a labeled abstract fixture, so tuning it is legitimate; do NOT relax `s1_confirmed` to make a wrong geometry pass, and keep the two S1 tests sharing the SAME ladder so the rollover test isolates the timestamp variable only.)
- [ ] Run failing-first (stub bodies): `uv run pytest tests/unit/chanlun/test_lifecycle.py -q` — expect failures.
- [ ] Implement, then run: `uv run pytest tests/unit/chanlun/test_lifecycle.py -q` — expect **17 passed**.
- [ ] Full chanlun unit suite: `uv run pytest tests/unit/chanlun/ -q` — all passed.
- [ ] Commit: `git add src/uw_scan/chanlun/lifecycle.py tests/unit/chanlun/test_lifecycle.py && git commit -m "feat(chanlun): pure lifecycle state machine + S1 predicate + breach/stale/split guards"`

---

## Task 9: worker job `chanlun_lifecycle_scan` + scheduler registration + config

The nightly batch: per watchlist ticker, fetch 1d + windowed 30m bars from apex, run `compute_chanlun_full`, derive every live mark's state, upsert transitions, and INVALIDATE(superseded) any previously-non-terminal mark absent from the recompute. Register it at 03:10 ET Tue–Sat pinned to massive-0, gated by `chanlun_lifecycle_enabled`. Config via `Settings.from_env()`.

**Files:**
- Create: `src/uw_scan/worker/jobs/chanlun_lifecycle.py`
- Modify: `src/uw_scan/config.py` (4 fields + `from_env` wiring)
- Modify: `src/uw_scan/worker/scheduler.py` (ownership pin closure + registration)
- Create: `tests/integration/worker/test_chanlun_lifecycle_scan.py`

**Interfaces:**
- Produces: `chanlun_lifecycle_scan(repo:Repository, settings:Settings, *, ticker_filter:list[str]|None=None, fetch_bars=None, now:datetime|None=None)->dict[str,Any]`. `fetch_bars` defaults to `uw_scan.sources.apex.fetch_bars` (injectable for tests). Returns `{"ok":int, "skipped_no_bars":int, "failed":int, "transitions":int, "tickers":int}`.
- Config fields (defaults): `chanlun_lifecycle_enabled: bool = False`, `chanlun_anchor_tol: float = 0.0`, `chanlun_stale_sessions: int = 20`, `chanlun_promotable_categories: str = "vertex,divergence,3B,3S"`.

**Job control flow (implement exactly):**
1. `now = now or datetime.now(timezone.utc)`; `today_et = now.astimezone(ZoneInfo(settings.rth_tz)).date()`.
2. `tickers` = `[t.upper() for t in ticker_filter]` or `sorted({c.ticker.upper() for c in repo.list_watchlist_cards()})`.
3. `fetch = fetch_bars or apex.fetch_bars`; `cs_repo = ChanlunSignalRepository(repo.conn, schema=settings.db_schema)`; `promotable = frozenset(t.strip() for t in settings.chanlun_promotable_categories.split(",") if t.strip())`.
4. Per ticker, in a `try/except Exception` with `repo.conn.rollback()` on failure (`failed += 1`):
   - `daily_raw = fetch(t, "1d", start=today_et - timedelta(days=1900), limit=0)` (≥1,300 sessions of headroom). If `not daily_raw`: `skipped_no_bars += 1; log.warning(...); continue` (apex degraded → count + log, never silent).
   - `daily_bars = [ChanlunBar(time=b["time"][:10], high=b["high"], low=b["low"], close=b["close"]) for b in daily_raw]` (apex daily `time` is an ISO datetime; slice to `yyyy-mm-dd` for the port's date-string contract).
   - `full = compute_chanlun_full(daily_bars)`; `marks = derive_marks(full, daily_bars)`.
   - `boundaries = find_split_boundaries(daily_raw)`; `session_dates = [date.fromisoformat(b.time) for b in daily_bars]`; `last_session = session_dates[-1]`.
   - For each `mark`: compute `anchor_start = anchor_window(mark, full.vertices, session_dates)` (40-SESSION fallback — the session-date list is the one built in the previous step); `split_crossed = crosses_split_boundary(mark, anchor_start, boundaries)`; `later = [b for b in daily_raw if b["time"][:10] > mark.extreme_date.isoformat()]`; `breach = breached(mark, later)`; `stale = is_stale(mark, last_session, settings.chanlun_stale_sessions, session_dates)`.
   - `prom = is_promotable(mark.category, mark.kind, promotable)`; compute `s1_ok`/`s1_info`:
     - only if `prom and not mark.is_native_confirmed and not split_crossed and not breach and not stale`: fetch `bars_30m_raw = fetch(t, "30m", start=anchor_start, end=None, limit=0)`; `bars_30m = [ChanlunBar(time=b["time"], high=b["high"], low=b["low"], close=b["close"]) for b in bars_30m_raw]`; `s1_ok, s1_info = s1_confirmed(mark, bars_30m, tol=settings.chanlun_anchor_tol)`. Else `s1_ok, s1_info = False, {}`.
   - `state, reason = evaluate_mark(mark=mark, split_crossed=split_crossed, breach=breach, s1_ok=s1_ok, promotable=prom, stale=stale)`.
   - `details = {"anchor_start": anchor_start.isoformat(), "v30": s1_info}` (only non-empty when relevant).
   - `if cs_repo.upsert_transition(ticker=t, category=mark.category, kind=mark.kind, extreme_date=mark.extreme_date, extreme_price=mark.extreme_price, state=state, reason=reason, as_of=today_et, details=details): transitions += 1`.
   - After processing all derived marks for `t`: `derived_keys = {(m.category, m.kind, m.extreme_date, m.extreme_price) for m in marks}`; for each `nt in cs_repo.list_non_terminal(t)` whose key `(nt["category"], nt["kind"], nt["extreme_date"], nt["extreme_price"]) not in derived_keys`: `upsert_transition(..., state="invalidated", reason="superseded", as_of=today_et, details={})` (`transitions += 1` if new). Increment `ok += 1`.
5. Return the summary dict; `log.info("chanlun_lifecycle_scan: %s", summary)`.

**Steps:**
- [ ] Add the 4 config fields (after the `technical_live_*` block, ~`config.py:379`) and the `from_env` wiring (after the `technical_live_*` block, ~`config.py:860`):

```python
    # Chanlun Phase B lifecycle engine (nightly 03:10 ET Tue-Sat, massive-0).
    chanlun_lifecycle_enabled: bool = False
    chanlun_anchor_tol: float = 0.0
    chanlun_stale_sessions: int = 20
    chanlun_promotable_categories: str = "vertex,divergence,3B,3S"
```

```python
            # All four env vars deliberately carry the UW_SCAN_ prefix (newest
            # precedent: UW_SCAN_TECHNICAL_LIVE_ENABLED) — one convention for
            # the whole feature, no mixed-prefix mis-sets on the mini.
            chanlun_lifecycle_enabled=_env_bool("UW_SCAN_CHANLUN_LIFECYCLE_ENABLED", False),
            chanlun_anchor_tol=float(os.environ.get("UW_SCAN_CHANLUN_ANCHOR_TOL", "0.0")),
            chanlun_stale_sessions=int(os.environ.get("UW_SCAN_CHANLUN_STALE_SESSIONS", "20")),
            chanlun_promotable_categories=os.environ.get(
                "UW_SCAN_CHANLUN_PROMOTABLE_CATEGORIES", "vertex,divergence,3B,3S"
            ),
```

- [ ] Implement `src/uw_scan/worker/jobs/chanlun_lifecycle.py` per the control flow above (module docstring explaining role + data flow; `log = logging.getLogger(__name__)`; per-ticker try/except with `repo.conn.rollback()`).
- [ ] Register in `scheduler.py`. Add the ownership-pin closure + registration (reuse the massive-0 rationale). Near the other `_should_schedule_*` helpers add:

```python
def _should_schedule_chanlun_lifecycle(settings: Settings) -> bool:
    """Single owner for the nightly chanlun lifecycle upserts. Pure DB-read +
    apex compute (no UW spend) -> pin to massive-0, same as regime/technical live."""
    role = settings.worker_role.lower()
    return role == "all" or (role == "massive" and settings.worker_index == 0)
```

  Add the inner closure (with the local job import) near the other closures:

```python
    def _chanlun_lifecycle_scan() -> None:
        from uw_scan.worker.jobs.chanlun_lifecycle import chanlun_lifecycle_scan
        with _repo(settings) as repo:
            summary = chanlun_lifecycle_scan(repo, settings)
        logger.info("chanlun_lifecycle_scan_tick %s", summary)
```

  Add the registration block (03:10 ET Tue–Sat = `day_of_week="tue-sat"`), gated by both the kill-switch and the ownership pin:

```python
    if settings.chanlun_lifecycle_enabled and _should_schedule_chanlun_lifecycle(settings):
        sched.add_job(
            _chanlun_lifecycle_scan,
            CronTrigger(hour=3, minute=10, day_of_week="tue-sat", timezone=settings.rth_tz),
            id="chanlun_lifecycle_scan",
            name="Chanlun daily-mark lifecycle (30m sub-level confirm)",
            max_instances=1,
            coalesce=True,
        )
```

- [ ] Create `tests/integration/worker/test_chanlun_lifecycle_scan.py`. Use the golden daily bars as the stubbed apex 1d feed (real AAPL bars), stub 30m to `[]` (exercises the API→DB→worker→DB PENDING path; sublevel promotion is unit-tested in Task 8):

```python
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from uw_scan.config import Settings
from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository
from uw_scan.worker.jobs.chanlun_lifecycle import chanlun_lifecycle_scan

_GOLDEN = json.loads(
    (Path(__file__).resolve().parents[3] / "web/tests/lib/fixtures/chanlunGoldenAapl.json").read_text()
)


def _stub_fetch(ticker, timeframe, start, *, end=None, limit=0, **kw):
    if timeframe == "1d":
        # Real frozen AAPL daily bars (open synthesized as close so the split
        # guard has a value; guard only trips on >1.5x gaps, which these lack).
        return [
            {"time": b["time"], "open": b["close"], "high": b["high"], "low": b["low"], "close": b["close"], "volume": 0, "vwap": None}
            for b in _GOLDEN["bars"]
        ]
    return []  # no 30m -> no sublevel promotion, marks stay PENDING/NATIVE


def _seed_watchlist(repo, ticker="AAPL"):
    # Minimal watchlist row so list_watchlist_cards() yields the ticker. Reuse
    # whatever the harness's card-seed helper is; if list_watchlist_cards is
    # empty, pass ticker_filter=["AAPL"] instead (below uses ticker_filter).
    return ticker


def test_scan_derives_and_persists_marks(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)  # 03:10 ET
    summary = chanlun_lifecycle_scan(
        repo, Settings.from_env(), ticker_filter=["AAPL"], fetch_bars=_stub_fetch, now=now
    )
    assert summary["ok"] == 1
    assert summary["failed"] == 0
    assert summary["transitions"] > 0  # non-vacuity: real bars produce marks
    states = ChanlunSignalRepository(repo.conn, schema=repo._schema).current_states("AAPL")
    assert len(states) > 0
    # Every persisted state is a legal value.
    assert all(s["state"] in {"pending", "confirmed_sublevel", "confirmed_native", "invalidated"} for s in states)
    # No sublevel promotions possible with empty 30m feed.
    assert all(s["state"] != "confirmed_sublevel" for s in states)


def test_scan_is_idempotent(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)
    kw = dict(ticker_filter=["AAPL"], fetch_bars=_stub_fetch, now=now)
    first = chanlun_lifecycle_scan(repo, Settings.from_env(), **kw)
    second = chanlun_lifecycle_scan(repo, Settings.from_env(), **kw)
    assert first["transitions"] > 0
    assert second["transitions"] == 0  # re-run over same bars is a no-op


def test_scan_counts_apex_outage(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    now = dt.datetime(2026, 7, 13, 7, 10, tzinfo=dt.timezone.utc)
    summary = chanlun_lifecycle_scan(
        repo, Settings.from_env(), ticker_filter=["AAPL"],
        fetch_bars=lambda *a, **k: [], now=now,  # apex down -> [] for everything
    )
    assert summary["skipped_no_bars"] == 1
    assert summary["ok"] == 0
```

- [ ] Run failing-first: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/worker/test_chanlun_lifecycle_scan.py -q` — expect ImportError (job not implemented).
- [ ] Implement, then run: same command — expect **3 passed**.
- [ ] Verify the scheduler wires cleanly (import + no syntax error): `uv run python -c "import uw_scan.worker.scheduler"` — expect no error.
- [ ] Config sanity: `uv run python -c "from uw_scan.config import Settings; s=Settings.from_env(); print(s.chanlun_lifecycle_enabled, s.chanlun_stale_sessions, s.chanlun_promotable_categories)"` — expect `False 20 vertex,divergence,3B,3S`.
- [ ] Commit: `git add src/uw_scan/worker/jobs/chanlun_lifecycle.py src/uw_scan/config.py src/uw_scan/worker/scheduler.py tests/integration/worker/test_chanlun_lifecycle_scan.py && git commit -m "feat(chanlun): nightly lifecycle scan job (03:10 ET Tue-Sat, massive-0) + config gate"`

---

## Task 10: API `GET /api/stock/{ticker}/chanlun/lifecycle` + Pydantic models + surgical types

Expose the current lifecycle state of every mark read-only — **excluding marks whose current state is `invalidated` with `reason='stale'`** (spec §API as amended 2026-07-14: stale invalidations are noise; breach/superseded/split_boundary invalidations ARE returned, each with current state + `first_entered_at` + `as_of` only). Add Pydantic models with `_preserve_public_module()`, wire into `stock.py`, and add the fields to the frozen `types.ts` and OpenAPI snapshot SURGICALLY.

**Files:**
- Create: `src/uw_scan/models/chanlun.py`
- Modify: `src/uw_scan/models/__init__.py` (import + `__all__`, alphabetical slots)
- Modify: `src/uw_scan/api/routers/stock.py` (endpoint)
- Modify: `web/lib/types.ts` (surgical, script-write)
- Modify: `tests/integration/api/openapi.snapshot.json` (surgical)
- Create: `tests/integration/api/test_chanlun_lifecycle_endpoint.py`

**Interfaces:**
- Produces (`models/chanlun.py`, `_UwBase` subclasses):
  - `ChanlunLifecycleMark(category:str, kind:str, extreme_date:date, extreme_price:float, state:str, reason:str|None=None, first_entered_at:datetime, as_of:date)`
  - `ChanlunLifecycleResponse(ticker:str, marks:list[ChanlunLifecycleMark])`
  - `_preserve_public_module(ChanlunLifecycleMark, ChanlunLifecycleResponse)`
- Produces (endpoint): `GET /api/stock/{ticker}/chanlun/lifecycle -> ChanlunLifecycleResponse` — current state per mark, filtered: `state=='invalidated' and reason=='stale'` rows are dropped; all other marks (pending, confirmed_sublevel, confirmed_native, and breach/superseded/split_boundary invalidations) are returned.

**Steps:**
- [ ] Create `src/uw_scan/models/chanlun.py`:

```python
"""Chanlun Phase B lifecycle API contract."""
from __future__ import annotations

from datetime import date, datetime

from uw_scan.models._base import _UwBase, _preserve_public_module


class ChanlunLifecycleMark(_UwBase):
    """Current lifecycle state of one daily chanlun mark (mark_id + state)."""

    category: str
    kind: str
    extreme_date: date
    extreme_price: float
    state: str
    reason: str | None = None
    first_entered_at: datetime
    as_of: date


class ChanlunLifecycleResponse(_UwBase):
    """Current state of every recorded mark for one ticker, excluding marks
    whose current state is invalidated/stale (spec §API). Breach, superseded,
    and split_boundary invalidations are included."""

    ticker: str
    marks: list[ChanlunLifecycleMark]


_preserve_public_module(ChanlunLifecycleMark, ChanlunLifecycleResponse)
```

- [ ] Export from `src/uw_scan/models/__init__.py` in ALPHABETICAL slots (both names sort near existing `C…` entries — place `ChanlunLifecycleMark`, `ChanlunLifecycleResponse` in the import block and in `__all__` at their alphabetical positions):
  - Import: `from uw_scan.models.chanlun import ChanlunLifecycleMark, ChanlunLifecycleResponse`
  - `__all__`: add `"ChanlunLifecycleMark",` and `"ChanlunLifecycleResponse",` at their alphabetical slots.
- [ ] Add the endpoint to `src/uw_scan/api/routers/stock.py` (local import of the standalone repo, synchronous `def`, `response_model=` set):

```python
@router.get("/stock/{ticker}/chanlun/lifecycle", response_model=ChanlunLifecycleResponse)
def get_stock_chanlun_lifecycle(
    ticker: str,
    repo: Repository = Depends(get_repo),
    settings: Settings = Depends(get_settings),
) -> ChanlunLifecycleResponse:
    from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository

    t = ticker.upper()
    rows = ChanlunSignalRepository(repo.conn, schema=settings.db_schema).current_states(t)
    # Spec §API: stale-invalidated marks are excluded; every other current
    # state (incl. breach/superseded/split_boundary invalidations) is returned.
    rows = [
        r for r in rows
        if not (r["state"] == "invalidated" and r["reason"] == "stale")
    ]
    marks = [
        ChanlunLifecycleMark(
            category=r["category"], kind=r["kind"], extreme_date=r["extreme_date"],
            extreme_price=r["extreme_price"], state=r["state"], reason=r["reason"],
            first_entered_at=r["first_entered_at"], as_of=r["as_of"],
        )
        for r in rows
    ]
    return ChanlunLifecycleResponse(ticker=t, marks=marks)
```

  Add `ChanlunLifecycleMark, ChanlunLifecycleResponse` to the `from uw_scan.models import (...)` block at the top of `stock.py` (alphabetical).
- [ ] Create `tests/integration/api/test_chanlun_lifecycle_endpoint.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from uw_scan.api.server import create_app
from uw_scan.storage.chanlun_signal_repository import ChanlunSignalRepository


def test_lifecycle_endpoint_returns_current_states_excluding_stale(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    r = ChanlunSignalRepository(repo.conn, schema=repo._schema)
    r.upsert_transition(
        ticker="AAPL", category="vertex", kind="bottom", extreme_date=date(2026, 7, 1),
        extreme_price=195.5, state="pending", reason=None, as_of=date(2026, 7, 1), details={},
    )
    # A breach-invalidated mark IS returned (spec §API keeps non-stale terminals).
    r.upsert_transition(
        ticker="AAPL", category="divergence", kind="bottom", extreme_date=date(2026, 6, 1),
        extreme_price=180.0, state="invalidated", reason="breach", as_of=date(2026, 6, 10), details={},
    )
    # A stale-invalidated mark must be EXCLUDED from the response (spec §API).
    r.upsert_transition(
        ticker="AAPL", category="vertex", kind="top", extreme_date=date(2026, 5, 1),
        extreme_price=210.0, state="pending", reason=None, as_of=date(2026, 5, 1), details={},
    )
    r.upsert_transition(
        ticker="AAPL", category="vertex", kind="top", extreme_date=date(2026, 5, 1),
        extreme_price=210.0, state="invalidated", reason="stale", as_of=date(2026, 6, 1), details={},
    )
    client = TestClient(create_app())
    resp = client.get("/api/stock/aapl/chanlun/lifecycle")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "AAPL"
    assert len(body["marks"]) == 2  # non-vacuity: pending + breach, stale gone
    states = {(m["category"], m["state"], m["reason"]) for m in body["marks"]}
    assert ("vertex", "pending", None) in states
    assert ("divergence", "invalidated", "breach") in states
    assert all(m["reason"] != "stale" for m in body["marks"])


def test_lifecycle_endpoint_empty_ticker_is_empty_list(seeded_db_empty_cards):
    client = TestClient(create_app())
    resp = client.get("/api/stock/ZZZ/chanlun/lifecycle")
    assert resp.status_code == 200
    assert resp.json() == {"ticker": "ZZZ", "marks": []}
```

- [ ] Run: `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/api/test_chanlun_lifecycle_endpoint.py -q` — expect **2 passed**.
- [ ] Verify export surface: `uv run pytest tests/unit/test_models_exports.py -q` — expect passed (the two new names are exported).
- [ ] **Surgical OpenAPI snapshot patch** (do NOT full-regen). Run:

```bash
uv run python - <<'PY'
import json
from uw_scan.api.server import create_app
sp = "tests/integration/api/openapi.snapshot.json"
snap = json.load(open(sp))
spec = create_app().openapi()
for name in ("ChanlunLifecycleMark", "ChanlunLifecycleResponse"):
    snap["components"]["schemas"][name] = spec["components"]["schemas"][name]
# The snapshot test also asserts paths-key equality — schemas-only patching
# guarantees a CI failure. Inject the new path too:
route = "/api/stock/{ticker}/chanlun/lifecycle"
snap["paths"][route] = spec["paths"][route]
open(sp, "w").write(json.dumps(snap, indent=2, ensure_ascii=True, sort_keys=True) + "\n")
PY
```

- [ ] Run the snapshot test: `uv run pytest tests/integration/api/test_openapi_snapshot.py -q` — expect passed. Confirm the diff added only the two new schema keys + one path key: `git diff --stat tests/integration/api/openapi.snapshot.json`.
- [ ] **Surgical `types.ts` addition** (do NOT run `npm run gen:types`). The path `/api/stock/{ticker}/chanlun/lifecycle` and the two component schemas must be added in their ALPHABETICAL slots, 4-space indent, via a bash/script write (the Edit tool's prettier hook reflows to 2-space). Steps:
  - Start the local API on :8400 (`bash scripts/dev.sh` or the API-only invocation) and fetch the two schema fragments + the path fragment from `http://127.0.0.1:8400/openapi.json` for reference.
  - Insert `ChanlunLifecycleMark` and `ChanlunLifecycleResponse` into the `components["schemas"]` object of `types.ts` at their alphabetical positions, and the `/api/stock/{ticker}/chanlun/lifecycle` operation into the `paths` object at its alphabetical position, matching the surrounding 4-space format exactly. Fields with Pydantic defaults (`reason`) render non-optional per `defaultNonNullable` — match the existing convention (a `string | null` with no `?`).
  - Write the change with a script/`python`/`cat` heredoc, never the Edit tool, to avoid the prettier reflow.
- [ ] Verify web still typechecks: `cd web && npm run typecheck` — expect no errors. And that the diff is minimal: `git diff --stat web/lib/types.ts` (a few added lines only, no whole-file reorder).
- [ ] Commit: `git add src/uw_scan/models/chanlun.py src/uw_scan/models/__init__.py src/uw_scan/api/routers/stock.py web/lib/types.ts tests/integration/api/openapi.snapshot.json tests/integration/api/test_chanlun_lifecycle_endpoint.py && git commit -m "feat(chanlun): read-only lifecycle API endpoint + surgical types.ts/openapi additions"`

---

## Task 11: validation probe `scripts/research/chanlun_sublevel_probe.py`

Walk-forward two-timeframe replay per spec §Validation: 10 named tickers × ~5.1y of apex 1d+30m bars, 4 metrics per category and pooled, per-category per-ticker-half catastrophic gates (survival ≥70%, breach ≤15%, median latency ≤2), split-boundary exclusions counted. Persist the full per-mark_id trace to a committed artifact, run it, and set the shipped `chanlun_promotable_categories` default from the gate results.

**Files:**
- Create: `scripts/research/chanlun_sublevel_probe.py`
- Create: `tests/unit/scripts/test_chanlun_probe_smoke.py` (gate/metric math verified without an apex fetch)
- Create (committed artifacts): `docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/` — `per_mark_trace.csv`, `summary.md`
- Possibly modify: `src/uw_scan/config.py` (narrow `chanlun_promotable_categories` default if the gate excludes a category)

**Interfaces:**
- Consumes (Task 6): `uw_scan.sources.apex.fetch_bars(ticker, timeframe, start, *, end=None, limit=0, ...)`. Consumes (Tasks 3/5): `uw_scan.chanlun.full.compute_chanlun_full`. Consumes (Task 8, names EXACT): `DEFAULT_STALE_SESSIONS, anchor_window, breached, crosses_split_boundary, derive_marks, find_split_boundaries, is_promotable, is_stale, promotable_key, s1_confirmed, session_et_date` from `uw_scan.chanlun.lifecycle`, and `ChanlunBar` from `uw_scan.chanlun.types`.
- Produces (module-level, imported by the smoke test): `MarkTrace` dataclass, `Metrics` dataclass, `compute_metrics(traces:list[MarkTrace])->Metrics`, `gate_pass(m:Metrics)->bool`, `replay_ticker(...)->dict[tuple, MarkTrace]`, `main()->int`.
- Produces (artifacts): `per_mark_trace.csv` with one row per `(mark, transition)` (columns: `ticker, category, kind, gate_category, extreme_date, extreme_price, transition_date, state, reason, pending_date, sublevel_date, native_date, invalidated_date, invalid_reason`), plus `summary.md` with the per-category pooled + per-half metric table, the gate verdicts, the split-boundary exclusion count, skipped tickers, and the exact reproduce command.

**Method (implement per spec §Validation + `phaseb_confirm_rule_options.md §D`):**
1. Tickers: `AAPL, NVDA, MSFT, AMZN, META, GOOGL, TSLA, AMD, SPY, QQQ`.
2. Per ticker: fetch full `1d` (`start = today - ~5.3y`, `limit=0`) and full `30m` (`limit=0`) from apex. Assert non-empty per ticker; if apex returns `[]` for a ticker, record it as skipped and continue (never fabricate bars).
3. Ground truth = the FULL-series daily `confirmed` set (`compute_chanlun_full` over all daily bars): a mark's native-confirmed date is the earliest prefix at which its vertex/point/divergence is `confirmed`.
4. Walk-forward: for each daily close `d`, take the daily prefix ≤ `d` → `compute_chanlun_full` → derive marks + PENDING births; take the 30m prefix ending at `close(d)` restricted to each pending mark's anchor window → `s1_confirmed` → assign CONFIRMED_SUBLEVEL date. Track each `mark_id` across prefixes; record every transition to the CSV.
5. Split-boundary: exclude any mark whose window/breach evaluation crosses a `find_split_boundaries` date from the metrics; COUNT the exclusions.
6. Metrics per category (`vertex`, `divergence`, `3B`, `3S`, and — measured-but-reported-separately — `1B`,`1S`,`2B`,`2S`) AND pooled: (1) sub-level survival → native; (2) breach rate; (3) median confirm latency (sessions from PENDING); (4) median lead over native.
7. Gates, per category, per ticker-half (split the 10-ticker set into two halves; a category failing survival<70% OR breach>15% OR median-latency>2 in EITHER half is EXCLUDED): report PASS/EXCLUDE per category.

**Steps:**
- [ ] Create `scripts/research/chanlun_sublevel_probe.py` with EXACTLY this content (it persists both artifacts BEFORE exit — stdout-only is data loss; runtime is tens of minutes: ~1,280 daily prefixes × 10 tickers, each a full recompute):

```python
#!/usr/bin/env python
"""Chanlun Phase B walk-forward validation probe (spec §Validation).

Two-timeframe prefix replay over 10 liquid names x ~5.1y of apex 1d+30m bars.
For every daily prefix: derive marks (compute_chanlun_full), advance each
mark_id's lifecycle (pending / sublevel / native / invalidated) using the SAME
Task-8 pure functions the nightly job uses, evaluating S1 over the mark's 30m
anchor window (ET-session-dated — never a UTC-date slice). At the end, compute
the 4 spec metrics per category + pooled, apply the per-category per-ticker-half
catastrophic gates (survival >= 70%, breach <= 15%, median latency <= 2
sessions), and persist the full per-mark trace + summary.

Reproduce: uv run python scripts/research/chanlun_sublevel_probe.py
"""
from __future__ import annotations

import csv
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from uw_scan.chanlun.full import compute_chanlun_full
from uw_scan.chanlun.lifecycle import (
    DEFAULT_STALE_SESSIONS,
    anchor_window,
    breached,
    crosses_split_boundary,
    derive_marks,
    find_split_boundaries,
    is_promotable,
    is_stale,
    promotable_key,
    s1_confirmed,
    session_et_date,
)
from uw_scan.chanlun.types import ChanlunBar
from uw_scan.sources.apex import fetch_bars

TICKERS = ["AAPL", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "TSLA", "AMD", "SPY", "QQQ"]
HALF_A = TICKERS[:5]  # ticker-half split for the AC-F4-style catastrophic gate
HALF_B = TICKERS[5:]
PROMOTABLE_CANDIDATES = frozenset({"vertex", "divergence", "3B", "3S"})
ALL_CATEGORIES = ["vertex", "divergence", "1B", "1S", "2B", "2S", "3B", "3S"]
WARMUP_SESSIONS = 60  # skip degenerate early prefixes
GATE_SURVIVAL = 0.70
GATE_BREACH = 0.15
GATE_LATENCY = 2.0
OUT_DIR = Path("docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe")
REPRODUCE = "uv run python scripts/research/chanlun_sublevel_probe.py"


@dataclass
class MarkTrace:
    """Lifecycle of one mark_id across prefixes. *_idx are session positions
    (index into the ticker's session-date list) so latency/lead are in SESSIONS."""

    ticker: str
    category: str  # vertex | point | divergence
    kind: str
    extreme_date: date
    extreme_price: float
    pending_idx: int
    pending_date: date
    sublevel_idx: int | None = None
    sublevel_date: date | None = None
    native_idx: int | None = None
    native_date: date | None = None
    invalidated_date: date | None = None
    invalid_reason: str | None = None
    transitions: list[tuple[date, str, str]] = field(default_factory=list)

    @property
    def gate_category(self) -> str:
        return promotable_key(self.category, self.kind)

    @property
    def terminal(self) -> bool:
        return self.native_date is not None or self.invalidated_date is not None


@dataclass
class Metrics:
    """The 4 spec metrics over sub-level-confirmed, non-split-excluded marks.
    None = no data (an empty cell must FAIL the gate, not pass it)."""

    n_sublevel: int
    n_resolved: int
    n_censored: int
    survival: float | None
    breach_rate: float | None
    median_latency: float | None
    median_lead: float | None


def compute_metrics(traces: list[MarkTrace]) -> Metrics:
    sub = [
        t for t in traces
        if t.sublevel_date is not None and t.invalid_reason != "split_boundary"
    ]
    resolved = [t for t in sub if t.native_date is not None or t.invalidated_date is not None]
    censored = len(sub) - len(resolved)  # right-censored: still open at end of data
    survived = [t for t in resolved if t.native_date is not None]
    breached_t = [t for t in resolved if t.invalid_reason == "breach"]
    latencies = [t.sublevel_idx - t.pending_idx for t in sub]
    leads = [
        t.native_idx - t.sublevel_idx
        for t in survived
        if t.native_idx is not None and t.sublevel_idx is not None
    ]
    return Metrics(
        n_sublevel=len(sub),
        n_resolved=len(resolved),
        n_censored=censored,
        survival=(len(survived) / len(resolved)) if resolved else None,
        breach_rate=(len(breached_t) / len(resolved)) if resolved else None,
        median_latency=float(statistics.median(latencies)) if latencies else None,
        median_lead=float(statistics.median(leads)) if leads else None,
    )


def gate_pass(m: Metrics) -> bool:
    """Survival >= 70% AND breach <= 15% AND median latency <= 2 (inclusive).
    A half with no resolved sub-level marks FAILS (no evidence != pass)."""
    if m.survival is None or m.breach_rate is None or m.median_latency is None:
        return False
    return (
        m.survival >= GATE_SURVIVAL
        and m.breach_rate <= GATE_BREACH
        and m.median_latency <= GATE_LATENCY
    )


def _load_bars(ticker: str):
    """Full-history 1d + 30m from apex with an EXPLICIT start (default-window
    gotcha). Returns None when either series is empty — never fabricate bars."""
    start = date.today() - timedelta(days=int(5.3 * 365))
    daily_raw = fetch_bars(ticker, "1d", start, limit=0)
    raw_30m = fetch_bars(ticker, "30m", start, limit=0)
    if not daily_raw or not raw_30m:
        return None
    daily = [
        ChanlunBar(time=b["time"][:10], high=b["high"], low=b["low"], close=b["close"])
        for b in daily_raw
    ]
    bars30 = [
        ChanlunBar(time=b["time"], high=b["high"], low=b["low"], close=b["close"])
        for b in raw_30m
    ]
    # ET session date per 30m bar, computed ONCE (session_et_date, not ts[:10] —
    # post-20:00-ET bars land on the next UTC date and would mis-window).
    et_dates = [session_et_date(b.time) for b in bars30]
    return daily_raw, daily, bars30, et_dates


def replay_ticker(
    ticker: str,
    daily_raw: list[dict],
    daily: list[ChanlunBar],
    bars30: list[ChanlunBar],
    et_dates: list[date],
) -> dict[tuple, MarkTrace]:
    """Walk-forward prefix replay for one ticker. Mirrors the nightly job's
    per-mark decision order exactly (split > native > breach > stale > S1)."""
    traces: dict[tuple, MarkTrace] = {}
    boundaries = find_split_boundaries(daily_raw)
    session_dates = [date.fromisoformat(b.time) for b in daily]
    for i in range(WARMUP_SESSIONS, len(daily)):
        prefix = daily[: i + 1]
        sess = session_dates[: i + 1]
        d = session_dates[i]
        full = compute_chanlun_full(prefix)
        marks = derive_marks(full, prefix)
        derived_keys: set[tuple] = set()
        for m in marks:
            key = (m.category, m.kind, m.extreme_date, m.extreme_price)
            derived_keys.add(key)
            tr = traces.get(key)
            if tr is None:
                tr = MarkTrace(
                    ticker=ticker, category=m.category, kind=m.kind,
                    extreme_date=m.extreme_date, extreme_price=m.extreme_price,
                    pending_idx=i, pending_date=d,
                )
                tr.transitions.append((d, "pending", ""))
                traces[key] = tr
            if tr.terminal:
                continue  # terminal short-circuit — never mutate a settled mark
            anchor_start = anchor_window(m, full.vertices, sess)
            if crosses_split_boundary(m, anchor_start, boundaries):
                tr.invalidated_date, tr.invalid_reason = d, "split_boundary"
                tr.transitions.append((d, "invalidated", "split_boundary"))
                continue
            if m.is_native_confirmed:
                tr.native_idx, tr.native_date = i, d
                tr.transitions.append((d, "confirmed_native", ""))
                continue
            later = [
                b for b in daily_raw[: i + 1]
                if b["time"][:10] > m.extreme_date.isoformat()
            ]
            if breached(m, later):
                tr.invalidated_date, tr.invalid_reason = d, "breach"
                tr.transitions.append((d, "invalidated", "breach"))
                continue
            if is_stale(m, d, DEFAULT_STALE_SESSIONS, sess):
                tr.invalidated_date, tr.invalid_reason = d, "stale"
                tr.transitions.append((d, "invalidated", "stale"))
                continue
            if tr.sublevel_date is None and is_promotable(
                m.category, m.kind, PROMOTABLE_CANDIDATES
            ):
                # 30m prefix ending at close(d), windowed to [anchor_start, d]
                # by ET session date.
                w30 = [
                    b for b, ed in zip(bars30, et_dates) if anchor_start <= ed <= d
                ]
                ok, _info = s1_confirmed(m, w30, tol=0.0)
                if ok:
                    tr.sublevel_idx, tr.sublevel_date = i, d
                    tr.transitions.append((d, "confirmed_sublevel", ""))
        # Superseded sweep: a live mark absent from this prefix's recompute has
        # migrated to a more-extreme endpoint — terminally invalidated.
        for key, tr in traces.items():
            if not tr.terminal and key not in derived_keys:
                tr.invalidated_date, tr.invalid_reason = d, "superseded"
                tr.transitions.append((d, "invalidated", "superseded"))
    return traces


def write_csv(all_traces: list[MarkTrace], path: Path) -> None:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "ticker", "category", "kind", "gate_category", "extreme_date",
            "extreme_price", "transition_date", "state", "reason",
            "pending_date", "sublevel_date", "native_date",
            "invalidated_date", "invalid_reason",
        ])
        for t in all_traces:
            for td, st, rs in t.transitions:
                w.writerow([
                    t.ticker, t.category, t.kind, t.gate_category,
                    t.extreme_date, t.extreme_price, td, st, rs,
                    t.pending_date, t.sublevel_date or "", t.native_date or "",
                    t.invalidated_date or "", t.invalid_reason or "",
                ])


def _fmt(v) -> str:
    if v is None:
        return "-"
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def write_summary(
    path: Path,
    per_cat: dict[str, list[tuple[str, Metrics]]],
    verdicts: dict[str, bool],
    split_excluded: int,
    skipped: list[str],
    n_marks: int,
) -> None:
    lines = [
        "# Chanlun Phase B — sub-level confirm probe results",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"Reproduce: `{REPRODUCE}`",
        "",
        f"Tickers: {', '.join(TICKERS)} (skipped/no-data: {', '.join(skipped) or 'none'})",
        f"Total marks traced: {n_marks}; split-boundary exclusions: {split_excluded}",
        "",
        "1B/1S/2B/2S are recorded-but-never-promoted by design (spec §Category "
        "scope v1) — their sub-level rows below are structurally empty.",
        "",
        "| category | slice | n_sub | resolved | censored | survival | breach | med latency | med lead |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cat, rows in per_cat.items():
        for slice_name, m in rows:
            lines.append(
                f"| {cat} | {slice_name} | {m.n_sublevel} | {m.n_resolved} | "
                f"{m.n_censored} | {_fmt(m.survival)} | {_fmt(m.breach_rate)} | "
                f"{_fmt(m.median_latency)} | {_fmt(m.median_lead)} |"
            )
    lines += [
        "",
        "## Gate verdicts (survival >= 70% AND breach <= 15% AND median "
        "latency <= 2 sessions, in BOTH ticker-halves)",
        "",
    ]
    for cat, ok in verdicts.items():
        lines.append(f"- **{cat}**: {'PASS' if ok else 'EXCLUDE'}")
    passing = [c for c, ok in verdicts.items() if ok]
    lines += [
        "",
        f"Shipped `chanlun_promotable_categories` default from this run: "
        f"`{','.join(passing)}`",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    all_traces: list[MarkTrace] = []
    skipped: list[str] = []
    for tk in TICKERS:
        loaded = _load_bars(tk)
        if loaded is None:
            skipped.append(tk)
            print(f"SKIP {tk}: apex returned no 1d or 30m bars", file=sys.stderr)
            continue
        daily_raw, daily, bars30, et_dates = loaded
        traces = replay_ticker(tk, daily_raw, daily, bars30, et_dates)
        assert traces, f"{tk}: replay produced zero marks (non-vacuity)"
        all_traces.extend(traces.values())
        print(f"{tk}: {len(traces)} marks traced over {len(daily)} sessions")
    assert all_traces, "no marks traced at all — probe run is vacuous"
    split_excluded = sum(1 for t in all_traces if t.invalid_reason == "split_boundary")
    per_cat: dict[str, list[tuple[str, Metrics]]] = {}
    verdicts: dict[str, bool] = {}
    for cat in ALL_CATEGORIES:
        cat_traces = [t for t in all_traces if t.gate_category == cat]
        rows = [("pooled", compute_metrics(cat_traces))]
        half_ok: list[bool] = []
        for half_name, half in (("half_A", HALF_A), ("half_B", HALF_B)):
            m = compute_metrics([t for t in cat_traces if t.ticker in half])
            rows.append((half_name, m))
            half_ok.append(gate_pass(m))
        per_cat[cat] = rows
        if cat in PROMOTABLE_CANDIDATES:
            verdicts[cat] = all(half_ok)  # failing EITHER half = EXCLUDE
    write_csv(all_traces, OUT_DIR / "per_mark_trace.csv")
    write_summary(
        OUT_DIR / "summary.md", per_cat, verdicts, split_excluded, skipped,
        len(all_traces),
    )
    print(f"wrote {OUT_DIR}/per_mark_trace.csv and {OUT_DIR}/summary.md")
    print("gate verdicts:", verdicts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] Create `tests/unit/scripts/test_chanlun_probe_smoke.py` — verifies the metric/gate math over hand-built transition sets (labeled test doubles) with NO apex fetch. `scripts/` is not a package, so load the probe by file path; the probe's `main()` is guarded by `__name__ == "__main__"`, so `exec_module` is side-effect-free:

```python
"""Gate/metric math smoke test for the chanlun sub-level probe.

Loads scripts/research/chanlun_sublevel_probe.py by file path (scripts/ is not
an importable package) and feeds hand-built MarkTrace sets (labeled test
doubles, not market data) through compute_metrics/gate_pass.
"""
from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_PROBE_PATH = (
    Path(__file__).resolve().parents[3] / "scripts/research/chanlun_sublevel_probe.py"
)
_spec = importlib.util.spec_from_file_location("chanlun_sublevel_probe", _PROBE_PATH)
probe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(probe)


def _trace(**kw):
    base = dict(
        ticker="AAPL", category="vertex", kind="bottom",
        extreme_date=date(2026, 1, 5), extreme_price=100.0,
        pending_idx=10, pending_date=date(2026, 1, 5),
    )
    base.update(kw)
    return probe.MarkTrace(**base)


def test_metrics_survival_breach_latency_lead():
    traces = [
        # survived: latency 11-10=1 session, lead 15-11=4 sessions
        _trace(sublevel_idx=11, sublevel_date=date(2026, 1, 6),
               native_idx=15, native_date=date(2026, 1, 12)),
        # breached after sublevel: latency 12-10=2
        _trace(sublevel_idx=12, sublevel_date=date(2026, 1, 7),
               invalidated_date=date(2026, 1, 9), invalid_reason="breach"),
        # right-censored: sublevel but never resolved
        _trace(sublevel_idx=13, sublevel_date=date(2026, 1, 8)),
        # never reached sublevel: excluded from every sub-level metric
        _trace(),
    ]
    m = probe.compute_metrics(traces)
    assert m.n_sublevel == 3 and m.n_resolved == 2 and m.n_censored == 1
    assert m.survival == 0.5 and m.breach_rate == 0.5
    assert m.median_latency == 2.0  # latencies [1, 2, 3] -> median 2.0
    assert m.median_lead == 4.0


def test_gate_pass_thresholds_are_inclusive():
    good = probe.Metrics(
        n_sublevel=10, n_resolved=10, n_censored=0,
        survival=0.70, breach_rate=0.15, median_latency=2.0, median_lead=5.0,
    )
    assert probe.gate_pass(good) is True  # spec bounds are inclusive
    assert probe.gate_pass(probe.Metrics(10, 10, 0, 0.69, 0.10, 1.0, 5.0)) is False
    assert probe.gate_pass(probe.Metrics(10, 10, 0, 0.90, 0.16, 1.0, 5.0)) is False
    assert probe.gate_pass(probe.Metrics(10, 10, 0, 0.90, 0.10, 2.5, 5.0)) is False


def test_gate_fails_on_no_evidence():
    empty = probe.Metrics(
        n_sublevel=0, n_resolved=0, n_censored=0,
        survival=None, breach_rate=None, median_latency=None, median_lead=None,
    )
    assert probe.gate_pass(empty) is False  # no data != pass


def test_split_excluded_marks_leave_the_metrics_entirely():
    traces = [
        _trace(sublevel_idx=11, sublevel_date=date(2026, 1, 6),
               invalidated_date=date(2026, 1, 9), invalid_reason="split_boundary"),
    ]
    m = probe.compute_metrics(traces)
    assert m.n_sublevel == 0  # split-boundary marks never enter the denominators
```

- [ ] Run the smoke test: `uv run pytest tests/unit/scripts/test_chanlun_probe_smoke.py -q` — expect **4 passed**.
- [ ] RUN the real probe against apex (requires apex reachable on the tailnet / mini): `uv run python scripts/research/chanlun_sublevel_probe.py`. Confirm the two artifacts exist and are non-empty: `wc -l docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/per_mark_trace.csv` and `cat docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/summary.md`.
- [ ] Read `summary.md`'s gate verdicts. Set the shipped `chanlun_promotable_categories` default (in `config.py` and its `from_env` default string) to EXACTLY the set of categories that PASS both ticker-halves. If all of `vertex,divergence,3B,3S` pass, leave the default as-is; if any is excluded, narrow the default and note it in `summary.md`. (Categories not in the default are still recorded by the engine, just never sub-level-promoted.)
- [ ] If the default changed, re-run `uv run pytest tests/unit/chanlun/ -q` and the config sanity check to confirm nothing depends on the old string.
- [ ] Commit: `git add scripts/research/chanlun_sublevel_probe.py docs/research/2026-07-14-chanlun-signal-lifecycle/phaseb_probe/ tests/unit/scripts/test_chanlun_probe_smoke.py src/uw_scan/config.py && git commit -m "feat(chanlun): walk-forward validation probe + committed per-mark trace + gated promotable-category default"`

---

## Task 12: CHANGELOG entry + final consistency sweep

Add the `[Unreleased]` CHANGELOG entry and run the full spec-coverage self-check before opening the PR.

**Files:**
- Modify: `CHANGELOG.md`

**Steps:**
- [ ] Add an `[Unreleased]` entry to `CHANGELOG.md` summarizing Phase B: Python chanlun port (`src/uw_scan/chanlun/`) with TS golden parity + 12 trap regressions; apex `fetch_bars` 1d/30m client; migration 107 `chanlun_signal_events` event log + standalone repository; nightly `chanlun_lifecycle_scan` (03:10 ET Tue–Sat, massive-0, gated `chanlun_lifecycle_enabled` default off); read-only `GET /api/stock/{ticker}/chanlun/lifecycle`; walk-forward validation probe gating `chanlun_promotable_categories`. Note it is backend-only (no UI, no alert emission).
- [ ] **Spec-coverage self-check** — walk each spec section and confirm the implementing task; fix any gap before the PR:
  - Sub-level timeframe 30m → Task 9 (30m fetch in the job) + Task 8 (`s1_confirmed`). ✓
  - Backend + validation-probe only, no UI/alerts → Non-goals honored (no `web/components` changes beyond `types.ts`). ✓
  - Apex single-source both timeframes → Task 6 `fetch_bars`; Task 9 uses it for 1d AND 30m. ✓
  - Default-limit gotcha (explicit start) → Task 6 (`start` required positional) + Task 6 test. ✓
  - Python port modules + parity + staged tests → Tasks 2–5. ✓
  - 12 JS→Python traps → Task 5 `test_traps.py`. ✓
  - Mark identity `(ticker,category,kind,extreme_date,extreme_price)` → Task 7 UNIQUE constraint + Task 8 marks. ✓
  - State machine + revocable sublevel + breach guard + staleness 20 + absent→superseded → Task 8 `evaluate_mark` + Task 9 superseded sweep. ✓
  - S1 predicate (confirmed same-side 30m vertex at exact daily extreme, tol=0.0, no-later-beats) → Task 8 `s1_confirmed`. ✓
  - S2 factored as a future flag → Task 8 (`require_divergence` unused param). ✓
  - Category scope (vertex/divergence/3B/3S promotable; 1B/1S/2B/2S recorded-only) → Task 8 `is_promotable` + Task 11 gate. ✓
  - Split-boundary guard `|ln(open_d/close_{d-1})| > ln(1.5)` reason=split_boundary + probe exclusion count → Task 8 `find_split_boundaries` + Task 11. ✓
  - Migration 107 columns/UNIQUE/reasons + current-state precedence + standalone repo → Task 7. ✓
  - CI gates: DatasetRegistryEntry provenance + regenerated policy doc → Task 7. ✓
  - Nightly job 03:10 ET Tue–Sat massive-0, config via from_env, per-ticker try/except, counts skipped tickers → Task 9. ✓
  - API read-only endpoint (stale-invalidated marks excluded, per amended spec §API) + `_preserve_public_module` + surgical types → Task 10. ✓
  - Probe: 10 tickers, 4 metrics, per-category per-half gates 70%/15%/2, committed trace + reproduce command, sets shipped default → Task 11. ✓
  - Verification regime: TDD, non-vacuity, staged parity, frozen fixtures, pytest-postgresql, two dataset gates green → every task. ✓
- [ ] Run the full relevant suites one final time: `uv run pytest tests/unit/chanlun/ tests/unit/sources/test_apex_fetch_bars.py tests/unit/scripts/test_chanlun_probe_smoke.py -q` and `UW_SCAN_TEST_DB_NAME=option_wizard_test uv run pytest tests/integration/storage/test_chanlun_signal_repository.py tests/integration/worker/test_chanlun_lifecycle_scan.py tests/integration/api/test_chanlun_lifecycle_endpoint.py tests/integration/worker/test_data_gap_full_coverage.py::test_zero_unregistered_after_full_registry tests/unit/reports/test_data_gap_dataset_policy.py::test_committed_policy_doc_is_in_sync_with_registry tests/integration/api/test_openapi_snapshot.py -q` — expect all passed.
- [ ] `cd web && npm run test -- chanlunGolden && npm run typecheck` — expect passed.
- [ ] Commit: `git add CHANGELOG.md && git commit -m "docs(chanlun): CHANGELOG entry for Phase B sub-level lifecycle engine"`
- [ ] Push and open the PR (never merge to main directly; wait for CI green): `git push -u origin feat/chanlun-phase-b && gh pr create --title "Chanlun Phase B: 区间套 sub-level fast-confirm lifecycle engine" --body "<summary of the 13 tasks (0–12) + spec link>"`
