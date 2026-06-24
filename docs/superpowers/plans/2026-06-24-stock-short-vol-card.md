# Per-Stock Short-Vol Card Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-ticker "Short-Vol" card to the stock detail page's Market Structure tab, mirroring the SPX Macro Short-Vol card, on the same row as Directional Bias.

**Architecture:** Read-time derivation only. The analytical result (`vrp_daily`: per-ticker `iv`/`rv`/`vrp_z_20`, refreshed nightly) is already persisted. A new pure function reshapes the latest row into a TRADE/SKIP readout with a flat-vol-modeled bull-put-spread, gated by the existing sellable-by-sector rule. It is folded into the existing `SingleStockReport` payload (no new endpoint, no client poll, no job, no migration) and rendered by a server-side panel. The sizing function (`size_weight`) and the spread builder (`build_bull_put_spread`) are reused as-is from the macro path; the TRADE/SKIP *verdict* is intentionally **stricter** than macro's `weight>0` — single names additionally require `vrp_z ≥ RICH_Z (1.0)`, a sellable sector, and a known earnings date clear of the hold window (the approved design).

**Tech Stack:** Python 3.13 (`uv`), FastAPI + Pydantic v2, Next.js 16 RSC + TypeScript, Vitest, pytest.

## Global Constraints

- `uv` only — `uv run pytest`, never bare `pytest`.
- **No naked shorts** — bull put spread is defined-risk (long wing caps loss). OK.
- **Persist analytical results to Postgres** — satisfied: `vrp_daily` is already persisted nightly; this card is a read-time reshape of it (same pattern as `build_vrp` on the Volatility tab). No new persistence.
- **No synthetic data in tests** — fixtures use the real ticker **TSLA** at its real **2026-06-24** values (spot `382.35`, IV30 `0.473` from the live page). `vrp_z_20` is the variable under test, set per case.
- **Decimal over float** for prices/IV/RV/Greeks in models (`models/stock.py`). FastAPI serializes `Decimal` as a JSON **string**; the web reads via `toNum`.
- **Module size budget** <500 lines/file — new `reports/stock_short_vol.py` stays well under.
- **API contract**: adding a schema requires regenerating `tests/integration/api/openapi.snapshot.json` and `web/lib/types.ts`. `types.ts` is "alphabetically frozen" — see Task 2 for the surgical path.
- **Never commit without explicit user request** — this plan's commits are pre-authorized by the user's "execute" instruction; each task ends with one commit.
- Branch: `feat/stock-vrp-z` (already checked out in this worktree).

---

### Task 1: `StockShortVol` model + `decide_short_vol`/`build_short_vol` (Python core)

**Files:**
- Modify: `src/uw_scan/models/stock.py` (add `StockShortVol`, register in `_preserve_public_module`)
- Modify: `src/uw_scan/models/__init__.py` (export `StockShortVol`)
- Create: `src/uw_scan/reports/stock_short_vol.py`
- Test: `tests/unit/test_stock_short_vol.py`

**Interfaces:**
- Consumes: `size_weight`, `WINNER`, `MacroSignalConfig` from `reports.vrp_macro_signal`; `build_bull_put_spread` from `reports.vrp_structure`; `passes_gate`, `sellable_single_name_sectors`, `sellable_asset_classes` from `reports.vrp_gate`; `repo.fetch_vrp_daily_series(ticker, *, limit)` from `storage.volatility_v2`.
- Produces (later tasks rely on these exact names/types):
  - `StockShortVol` Pydantic model (fields below).
  - `decide_short_vol(*, as_of, spot, iv, rv, vrp, vrp_z_20, gate_ok, next_earnings_date, require_earnings=True, risk_free_rate=RISK_FREE_RATE, cfg=WINNER) -> StockShortVol` — pure, no I/O. Normalizes non-finite inputs to None; unknown earnings → SKIP for single names (`require_earnings=True`), exempt for macro/ETF.
  - `build_short_vol(repo, ticker, spot) -> StockShortVol | None` — I/O wrapper; reads the latest `vrp_daily` row + gate + a reliable next-earnings date (`repo.fetch_latest_next_earnings_date`); `None` iff the ticker has no `vrp_daily` history.

- [ ] **Step 1: Add the `StockShortVol` model**

In `src/uw_scan/models/stock.py`, add this class immediately after `VRPAssessment` (after line ~60):

```python
class StockShortVol(_UwBase):
    """Per-ticker short-vol (sell-premium) readout for the Market Structure tab —
    the single-name sibling of the SPX MacroSignal. EOD basis (latest vrp_daily row).
    action=TRADE only when vol is rich (vrp_z_20 >= 1.0) AND the ticker's sector is in
    the sellable set AND earnings are clear of the hold window; else SKIP with a reason.
    Strikes/credit/max_loss are flat-vol modeled (conservative floor)."""

    as_of: _date
    basis: str = "eod"
    action: str  # "TRADE" | "SKIP"
    skip_reason: str | None = None
    iv: Decimal | None = None
    rv20: Decimal | None = None
    vrp: Decimal | None = None
    vrp_z: Decimal | None = None
    weight: Decimal | None = None
    short_put: Decimal | None = None
    long_put: Decimal | None = None
    put_width: Decimal | None = None
    credit: Decimal | None = None
    max_loss: Decimal | None = None
    hold_days: int
    short_delta: Decimal
    wing_delta: Decimal
```

Add `short_vol: StockShortVol | None = None` to `SingleStockReport`, immediately after the `vrp: VRPAssessment` line (~line 96):

```python
    vrp: VRPAssessment
    # Single-name short-vol readout (sell-premium TRADE/SKIP + modeled spread).
    # Derived at read time from the latest vrp_daily row; None when no history.
    short_vol: StockShortVol | None = None
```

Add `StockShortVol` to the `_preserve_public_module(...)` call at the bottom of the file (append it to the existing argument list).

- [ ] **Step 2: Export the model**

In `src/uw_scan/models/__init__.py`, add `StockShortVol` to the `from .stock import (...)` block (line ~127) and to `__all__` (alongside the other stock exports, e.g. after `"SingleStockReport",`).

- [ ] **Step 3: Write the failing unit test**

Create `tests/unit/test_stock_short_vol.py`:

```python
"""Per-ticker short-vol decision logic. Real TSLA 2026-06-24: spot 382.35, IV30 0.473."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.reports.stock_short_vol import build_short_vol, decide_short_vol

AS_OF = date(2026, 6, 24)
SPOT = 382.35
IV = 0.473
RV = 0.40
CLEAR_EARNINGS = date(2026, 10, 1)  # well beyond AS_OF + 45d (2026-08-08)


def test_trade_when_rich_sellable_and_earnings_clear():
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV, vrp=0.073, vrp_z_20=1.6,
        gate_ok=True, next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "TRADE"
    assert sig.skip_reason is None
    assert sig.short_put is not None and sig.short_put < Decimal(str(SPOT))
    assert sig.long_put is not None and sig.long_put < sig.short_put
    assert sig.credit is not None and sig.credit > 0
    assert sig.max_loss is not None and sig.max_loss > 0
    assert sig.weight is not None and sig.weight > 0
    assert sig.short_delta == Decimal("0.25")
    assert sig.wing_delta == Decimal("0.125")


def test_skip_when_vol_not_rich():
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV, vrp=0.01, vrp_z_20=0.3,
        gate_ok=True, next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert "not rich" in (sig.skip_reason or "")
    assert sig.weight == Decimal("0")
    assert sig.short_put is None


def test_skip_when_sector_not_sellable():
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV, vrp=0.073, vrp_z_20=1.6,
        gate_ok=False, next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"


def test_skip_when_earnings_unknown():
    # passes_gate proves an earnings calendar EXISTS, but the next date is unknown →
    # never sell vol blind (matches scanner.gates.earnings_gate: None → block).
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV, vrp=0.073, vrp_z_20=1.6,
        gate_ok=True, next_earnings_date=None,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "earnings date unavailable"


def test_macro_class_trades_without_earnings():
    # ETF/index sellable bucket: no earnings to clear, so unknown earnings must NOT
    # block (mirrors vrp_gate exempting non-single_name classes).
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV, vrp=0.073, vrp_z_20=1.6,
        gate_ok=True, next_earnings_date=None, require_earnings=False,
    )
    assert sig.action == "TRADE"


def test_skip_when_earnings_in_window():
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV, vrp=0.073, vrp_z_20=1.6,
        gate_ok=True, next_earnings_date=date(2026, 7, 5),  # ~11 days out
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "earnings inside hold window"


def test_skip_when_no_iv():
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=None, rv=RV, vrp=None, vrp_z_20=1.6,
        gate_ok=True, next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "no usable IV/spot"


def test_skip_and_no_decimal_nan_when_z_nonfinite():
    # early rolling-window rows carry NaN vrp_z_20 → must NOT reach Decimal("NaN")
    # (Pydantic rejects non-finite). Non-finite numerics normalize to None.
    sig = decide_short_vol(
        as_of=AS_OF, spot=SPOT, iv=IV, rv=RV,
        vrp=float("nan"), vrp_z_20=float("nan"),
        gate_ok=True, next_earnings_date=CLEAR_EARNINGS,
    )
    assert sig.action == "SKIP"
    assert sig.skip_reason == "insufficient vol history"
    assert sig.vrp_z is None and sig.vrp is None


class _StubRepo:
    def __init__(self, series):
        self._series = series

    def fetch_vrp_daily_series(self, ticker, *, limit=60):
        return self._series

    def fetch_vrp_harvest_by_sector(self):
        return []

    def fetch_vrp_harvest_multihorizon(self):
        return []

    def fetch_watchlist_sector(self, ticker):
        return "Technology"

    def fetch_historical_earnings_dates(self, ticker):
        return set()

    def fetch_latest_next_earnings_date(self, ticker):
        return CLEAR_EARNINGS


def test_build_returns_none_without_history():
    assert build_short_vol(_StubRepo([]), "TSLA", SPOT) is None


def test_build_skips_when_gate_blocks():
    series = [{"market_date": AS_OF, "iv": IV, "rv": RV, "vrp": 0.073, "vrp_z_20": 1.6}]
    sig = build_short_vol(_StubRepo(series), "TSLA", SPOT)
    # empty sellable sets → single_name gate returns None → SKIP
    assert sig is not None and sig.action == "SKIP"
    assert sig.skip_reason == "sector vol not sellable"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_stock_short_vol.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'uw_scan.reports.stock_short_vol'`.

- [ ] **Step 5: Write the implementation**

Create `src/uw_scan/reports/stock_short_vol.py`:

```python
"""Per-ticker short-vol readout — single-name sibling of the SPX MacroSignal.

Reshapes the latest persisted vrp_daily row (iv/rv/vrp_z_20) into a TRADE/SKIP
action with a flat-vol-modeled bull put spread, gated by the sellable-by-sector
rule. Pure read-time derivation: vrp_daily is the already-persisted analytical
result, refreshed nightly by worker.volatility_jobs.nightly_vol_analytics_rollup.
"""

from __future__ import annotations

import math
from datetime import date as _date
from datetime import timedelta
from decimal import Decimal

from uw_scan.models import StockShortVol
from uw_scan.reports.vrp_gate import (
    passes_gate,
    sellable_asset_classes,
    sellable_single_name_sectors,
)
from uw_scan.reports.vrp_macro_signal import WINNER, MacroSignalConfig, size_weight
from uw_scan.reports.vrp_structure import build_bull_put_spread

RICH_Z = 1.0  # vol "rich enough" to sell — matches reports.vrp_markout.RICH_Z
# ponytail: flat r mirrors settings.vrp_risk_free_rate default (config.py:311);
# tiny effect at short DTE. Thread settings here only if r ever needs to be non-default.
RISK_FREE_RATE = 0.04
# 30 trading-day hold ≈ 6 calendar weeks; exclude a name whose next earnings prints
# inside that window (the (entry, expiry] earnings landmine).
HOLD_CAL_DAYS = 45


def _finite(v: object) -> float | None:
    """Coerce to a finite float, else None. Guards against NaN/inf — the rolling
    vrp_z_20 window emits NaN on short histories (cards/vol_series.py), and Pydantic
    rejects Decimal('NaN')."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _dec(v: float | None) -> Decimal | None:
    if v is None:
        return None
    return Decimal(str(v))


def decide_short_vol(
    *,
    as_of: _date,
    spot: float | None,
    iv: float | None,
    rv: float | None,
    vrp: float | None,
    vrp_z_20: float | None,
    gate_ok: bool,
    next_earnings_date: _date | None,
    require_earnings: bool = True,
    risk_free_rate: float = RISK_FREE_RATE,
    cfg: MacroSignalConfig = WINNER,
) -> StockShortVol:
    """Map one ticker's latest VRP row → TRADE/SKIP readout. Pure: no I/O.

    `gate_ok` is the result of reports.vrp_gate.passes_gate (sellable bucket). TRADE
    additionally requires vol rich (z>=RICH_Z) and a usable IV+spot. For single names
    (`require_earnings=True`) it also requires a KNOWN next-earnings date outside the
    hold window — unknown earnings conservatively SKIP (matches
    scanner.gates.earnings_gate: None → block). Macro/ETF classes don't report
    earnings (`require_earnings=False`), mirroring vrp_gate's own asset-class split.
    """
    spot = _finite(spot)
    iv = _finite(iv)
    rv = _finite(rv)
    vrp = _finite(vrp)
    z = _finite(vrp_z_20)

    common = dict(
        as_of=as_of,
        iv=_dec(iv),
        rv20=_dec(rv),
        vrp=_dec(vrp),
        vrp_z=_dec(z),
        hold_days=cfg.hold_days,
        short_delta=_dec(cfg.short_delta),
        wing_delta=_dec(cfg.wing_delta),
    )

    usable = iv is not None and iv > 0 and spot is not None and spot > 0
    rich = z is not None and z >= RICH_Z
    window_end = as_of + timedelta(days=HOLD_CAL_DAYS)
    earnings_clear = next_earnings_date is not None and next_earnings_date > window_end

    if not usable:
        reason: str | None = "no usable IV/spot"
    elif z is None:
        reason = "insufficient vol history"
    elif not rich:
        reason = f"vol not rich (vrp_z {z:.2f} < {RICH_Z:.1f})"
    elif not gate_ok:
        reason = "sector vol not sellable"
    elif require_earnings and next_earnings_date is None:
        reason = "earnings date unavailable"
    elif require_earnings and not earnings_clear:
        reason = "earnings inside hold window"
    else:
        reason = None

    if reason is not None:
        return StockShortVol(
            action="SKIP", skip_reason=reason, weight=Decimal("0"), **common
        )

    # tradeable — spot/iv are finite & positive here. Build the modeled spread;
    # degenerate strikes fall back to SKIP.
    try:
        st = build_bull_put_spread(
            spot,
            iv,
            cfg.hold_days / 252.0,
            risk_free_rate,
            short_delta=cfg.short_delta,
            wing_delta=cfg.wing_delta,
        )
    except ValueError:
        return StockShortVol(
            action="SKIP",
            skip_reason="degenerate spread strikes",
            weight=Decimal("0"),
            **common,
        )

    return StockShortVol(
        action="TRADE",
        skip_reason=None,
        weight=_dec(size_weight(z, cfg)),
        short_put=_dec(st.short_put),
        long_put=_dec(st.long_put),
        put_width=_dec(st.put_width),
        credit=_dec(st.credit),
        max_loss=_dec(st.max_loss),
        **common,
    )


def build_short_vol(repo, ticker: str, spot: float | None) -> StockShortVol | None:
    """I/O wrapper: read the latest vrp_daily row, the sellable gate, and a reliable
    next-earnings date, then decide. Returns None when the ticker has no vrp_daily
    history (new/illiquid name).

    Earnings come from repo.fetch_latest_next_earnings_date (most-recent reported
    next-earnings across flow_events) — more reliable than the report's
    current-top-alert promotion, which is often None even for names that report.
    """
    series = repo.fetch_vrp_daily_series(ticker, limit=1)
    if not series:
        return None
    row = series[0]
    gate = passes_gate(
        repo,
        ticker,
        sellable_sectors=sellable_single_name_sectors(repo),
        sellable_classes=sellable_asset_classes(repo, hold_days=WINNER.hold_days),
    )
    # Only single names carry the earnings landmine; indices/ETFs don't report
    # (vrp_gate makes the same split).
    require_earnings = gate is not None and gate.asset_class == "single_name"
    return decide_short_vol(
        as_of=row["market_date"],
        spot=spot,
        iv=row.get("iv"),
        rv=row.get("rv"),
        vrp=row.get("vrp"),
        vrp_z_20=row.get("vrp_z_20"),
        gate_ok=gate is not None,
        next_earnings_date=repo.fetch_latest_next_earnings_date(ticker),
        require_earnings=require_earnings,
    )
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_stock_short_vol.py -v`
Expected: PASS (10 tests).

- [ ] **Step 7: Run the models export guard**

Run: `uv run pytest tests/unit/test_models_exports.py -v`
Expected: PASS (confirms `StockShortVol` export surface is consistent).

- [ ] **Step 8: Commit**

```bash
git add src/uw_scan/models/stock.py src/uw_scan/models/__init__.py \
        src/uw_scan/reports/stock_short_vol.py tests/unit/test_stock_short_vol.py
git commit -m "feat(stock): per-ticker short-vol decision + StockShortVol model"
```

---

### Task 2: Wire into the stock report + regen contract (snapshot + types.ts)

**Files:**
- Modify: `src/uw_scan/reports/single_stock.py` (import + compute `short_vol`, pass to `SingleStockReport`)
- Modify: `tests/integration/api/openapi.snapshot.json` (regenerate)
- Modify: `web/lib/types.ts` (add `StockShortVol` schema + `short_vol` field)

**Interfaces:**
- Consumes: `build_short_vol` from Task 1; `SingleStockReport.short_vol` field from Task 1.
- Produces: `report.short_vol: StockShortVol | null` on the `/api/stock/{ticker}` payload (consumed by Task 3/4).

- [ ] **Step 1: Add a module logger to `single_stock.py`**

`single_stock.py` has no logger today. Add at the top (after the `import` block):

```python
import logging

logger = logging.getLogger(__name__)
```

- [ ] **Step 2: Wire `build_short_vol` into the assembler (defensively)**

In `src/uw_scan/reports/single_stock.py`, add the import near the other `reports` imports at the top:

```python
from uw_scan.reports.stock_short_vol import build_short_vol
```

In `assemble_single_stock_report`, after `market_structure` and `next_earnings_date` are computed and before `return SingleStockReport(`, add the call **wrapped** — the short-vol card is non-critical and must never take down the stock page (mirrors the `# noqa: BLE001` pattern at `pipeline.py:94`). Note the EOD-spot basis: `short_vol` is modeled off `market_structure.spot` (the EOD close at assembly time, consistent with the EOD `as_of` and the card's "EOD SNAPSHOT" label); the router's `_with_latest_spot` later patches only the *header* display spot, not the card.

```python
    try:
        short_vol = build_short_vol(
            repo,
            ticker,
            float(market_structure.spot) if market_structure.spot is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 — short-vol card is non-critical; never break the page
        logger.warning("short_vol build failed for %s: %s", ticker, repr(exc))
        short_vol = None
```

In the `return SingleStockReport(...)` constructor call, add the kwarg next to `next_earnings_date=next_earnings_date,`:

```python
        next_earnings_date=next_earnings_date,
        short_vol=short_vol,
```

- [ ] **Step 3: Keep the existing report-assembly test green**

`tests/unit/test_report_assembly.py` exercises `assemble_single_stock_report` with a hand-rolled `_StubRepo`. The new call needs `fetch_vrp_daily_series` on that stub (returning `[]` so `build_short_vol` returns `None` without touching the gate). Add to `_StubRepo`:

```python
    def fetch_vrp_daily_series(self, ticker: str, *, limit: int = 60) -> list[dict]:
        return []
```

And add an assertion to the assembly test that the new field defaults cleanly (find the test that builds the report and asserts on its sections; add):

```python
    assert report.short_vol is None
```

Run: `uv run pytest tests/unit/test_report_assembly.py -v`
Expected: PASS (proves the new wiring degrades to `None` without a stub method explosion — not via exception-swallowing).

- [ ] **Step 4: Confirm the OpenAPI snapshot test now fails (contract changed)**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: FAIL — "OpenAPI schemas changed" (the new `StockShortVol` schema + `short_vol` property are not yet in the snapshot).

- [ ] **Step 5: Regenerate the snapshot**

The snapshot is the full `/openapi.json` dumped `sort_keys=True, indent=2` (deterministic → minimal diff). Run:

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from uw_scan.api.server import app
spec = app.openapi()
p = Path("tests/integration/api/openapi.snapshot.json")
p.write_text(json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
print("wrote", p)
PY
```

Verify the diff is small and only adds `StockShortVol` + `short_vol`:

```bash
git diff --stat tests/integration/api/openapi.snapshot.json
```

Expected: a modest `+N` insertion (the new schema block + one property ref). If the whole file churns, the original lacked a trailing newline — check `tail -c1 tests/integration/api/openapi.snapshot.json | xxd` and drop the `+ "\n"` to match. (The test asserts parsed-JSON equality, so it passes regardless of formatting; the formatting only keeps the diff reviewable.)

- [ ] **Step 6: Re-run the snapshot test to verify it passes**

Run: `uv run pytest tests/integration/api/test_openapi_snapshot.py -v`
Expected: PASS.

- [ ] **Step 7: Regenerate `web/lib/types.ts`**

Primary path (API must be reachable on :8400 — start it with `bash scripts/dev.sh` or `make`-equivalent if not running):

```bash
cd web && npm run gen:types && cd ..
git diff --stat web/lib/types.ts
```

**If the diff shows only the additions** (a `StockShortVol:` block + a `short_vol?:` line under `SingleStockReport`), keep it and skip to Step 6.

**If the diff reorders hundreds/thousands of lines** (the known "alphabetically frozen" trap), discard and splice in only the two new pieces — extracted from a *fresh* generation so they match `openapi-typescript` output byte-for-byte (no hand-authoring, no JSDoc-orphan risk). Do it via a script (not the Edit tool — a prettier hook reflows tool-driven edits):

```bash
git checkout web/lib/types.ts
cd web && npx openapi-typescript http://127.0.0.1:8400/openapi.json -o /tmp/types.new.ts && cd ..
uv run python - <<'PY'
import re
from pathlib import Path

new = Path("/tmp/types.new.ts").read_text()
cur = Path("web/lib/types.ts").read_text()

def extract_block(src, name):
    """Full `        {name}: { ... };` block, including any preceding JSDoc comment."""
    decl = re.search(rf"\n( *){name}: \{{", src)
    assert decl, f"{name} not found in generated types"
    indent = decl.group(1)
    start = decl.start() + 1
    cm = re.search(r"( *)/\*\*(?:(?!\*/).)*\*/\n\Z", src[:start], re.S)  # preceding /** */
    block_start = cm.start() if cm else start
    close = re.search(rf"\n{indent}}};\n", src[start:])
    assert close, f"{name} block close not found"
    return src[block_start:start + close.end()]

sv_block = extract_block(new, "StockShortVol")
fld = re.search(r"\n( *short_vol\?: [^\n]*\n)", new)
assert fld, "short_vol field not found in generated types"
field = fld.group(1)

# Insert StockShortVol before StrikeExposureRow — and before ITS JSDoc comment.
m = re.search(r"\n( *)StrikeExposureRow: \{", cur)
assert m, "StrikeExposureRow anchor not found"
istart = m.start() + 1
cm = re.search(r"( *)/\*\*(?:(?!\*/).)*\*/\n\Z", cur[:istart], re.S)
ins = cm.start() if cm else istart
cur = cur[:ins] + sv_block + cur[ins:]

# Insert short_vol field right after short_int_note in SingleStockReport.
needle = re.search(r"\n *short_int_note: string;\n", cur)
assert needle, "short_int_note anchor not found"
cur = cur.replace(needle.group(0), needle.group(0) + field, 1)

Path("web/lib/types.ts").write_text(cur)
print("spliced StockShortVol schema + short_vol field")
PY
```

This extracts the exact `StockShortVol` block and `short_vol` line from a throwaway full generation, so the spliced content is identical to what `gen:types` would emit — and it anchors the schema insert *before* `StrikeExposureRow`'s JSDoc comment so that comment stays attached to `StrikeExposureRow`. After running, `git diff --stat web/lib/types.ts` should show only the additions.

- [ ] **Step 8: Verify types + typecheck**

```bash
cd web && npm run typecheck && cd ..
```
Expected: no errors. (Confirms `report.short_vol` and the `StockShortVol` schema resolve.)

- [ ] **Step 9: Commit**

```bash
git add src/uw_scan/reports/single_stock.py tests/unit/test_report_assembly.py \
        tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(stock): expose short_vol on SingleStockReport + regen contract"
```

---

### Task 3: `ShortVolPanel` component (frontend, Vitest)

**Files:**
- Create: `web/components/stock/panels/ShortVolPanel.tsx`
- Test: `web/tests/unit/ShortVolPanel.test.tsx`

**Interfaces:**
- Consumes: `components["schemas"]["SingleStockReport"]` (now with `short_vol`) from Task 2; `toNum` from `@/lib/formatters`.
- Produces: `export function ShortVolPanel({ report }: { report: Report })` — a pure server-renderable panel (no hooks), consumed by Task 4. Test ids: `short-vol-panel`, `short-vol-action`.

- [ ] **Step 1: Write the failing test**

Create `web/tests/unit/ShortVolPanel.test.tsx`:

```tsx
/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShortVolPanel } from "@/components/stock/panels/ShortVolPanel";
import type { components } from "@/lib/types";

type Report = components["schemas"]["SingleStockReport"];

// Real TSLA 2026-06-24 spot; short_vol shaped like the serialized API response
// (Decimal → string).
const base = { ticker: "TSLA" } as unknown as Report;
const withShortVol = (sv: unknown): Report =>
  ({ ...base, short_vol: sv }) as Report;

const tradeSv = {
  as_of: "2026-06-24", basis: "eod", action: "TRADE", skip_reason: null,
  iv: "0.473", rv20: "0.40", vrp: "0.073", vrp_z: "1.6", weight: "1",
  short_put: "360", long_put: "340", put_width: "20", credit: "4.2", max_loss: "15.8",
  hold_days: 30, short_delta: "0.25", wing_delta: "0.125",
};

const skipSv = {
  ...tradeSv, action: "SKIP", skip_reason: "sector vol not sellable", weight: "0",
  short_put: null, long_put: null, put_width: null, credit: null, max_loss: null,
};

describe("ShortVolPanel", () => {
  it("renders TRADE with spread strikes and the bull-put footer", () => {
    render(<ShortVolPanel report={withShortVol(tradeSv)} />);
    expect(screen.getByTestId("short-vol-action").textContent).toBe("TRADE");
    expect(screen.getByText(/Sell 360 \/ buy 340 put/)).toBeTruthy();
    expect(
      screen.getByText(/Bull put spread 0\.25Δ\/0\.125Δ · ~30d hold/),
    ).toBeTruthy();
  });

  it("renders SKIP with the reason and IV/RV", () => {
    render(<ShortVolPanel report={withShortVol(skipSv)} />);
    expect(screen.getByTestId("short-vol-action").textContent).toBe("SKIP");
    expect(screen.getByText("sector vol not sellable")).toBeTruthy();
    expect(screen.getByText(/IV 47\.3% \/ RV20 40\.0%/)).toBeTruthy();
  });

  it("renders a no-data state when short_vol is null", () => {
    render(<ShortVolPanel report={withShortVol(null)} />);
    expect(screen.getByTestId("short-vol-panel")).toBeTruthy();
    expect(screen.getByText(/No vol data/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npm run test -- ShortVolPanel`
Expected: FAIL — cannot resolve `@/components/stock/panels/ShortVolPanel`.

- [ ] **Step 3: Write the component**

Create `web/components/stock/panels/ShortVolPanel.tsx`:

```tsx
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  minWidth: 0,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const pct = (x: number | null) =>
  x == null ? "—" : `${(x * 100).toFixed(1)}%`;
const f = (x: number | null, d = 2) => (x == null ? "—" : x.toFixed(d));

export function ShortVolPanel({ report }: { report: Report }) {
  const s = report.short_vol;

  const header = (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 12,
      }}
    >
      <span style={labelStyle}>SHORT-VOL · {report.ticker}</span>
      <span style={{ ...labelStyle, fontSize: 9, letterSpacing: 0.5 }}>
        EOD SNAPSHOT
      </span>
    </div>
  );

  if (!s) {
    return (
      <div style={panelStyle} data-testid="short-vol-panel">
        {header}
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          No vol data yet.
        </div>
      </div>
    );
  }

  const trade = s.action === "TRADE";
  const color = trade ? "var(--positive)" : "var(--text-muted)";
  const reasons = trade
    ? [
        `vrp_z ${f(toNum(s.vrp_z))} · weight ${f(toNum(s.weight))} (size)`,
        `Sell ${f(toNum(s.short_put), 0)} / buy ${f(toNum(s.long_put), 0)} put`,
        `Credit ${f(toNum(s.credit))} · max loss ${f(toNum(s.max_loss))} per spread`,
      ]
    : [
        `vrp_z ${f(toNum(s.vrp_z))} · weight ${f(toNum(s.weight))}`,
        `IV ${pct(toNum(s.iv))} / RV20 ${pct(toNum(s.rv20))}`,
      ];

  return (
    <div style={panelStyle} data-testid="short-vol-panel">
      {header}
      <div
        data-testid="short-vol-action"
        style={{
          color,
          fontSize: 28,
          fontWeight: 700,
          letterSpacing: 1,
          marginBottom: 10,
        }}
      >
        {s.action}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {reasons.map((r, i) => (
          <div key={i} style={{ color: "var(--text-secondary)", fontSize: 12 }}>
            {r}
          </div>
        ))}
        {!trade && s.skip_reason ? (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            {s.skip_reason}
          </div>
        ) : null}
      </div>
      <div
        style={{
          marginTop: 12,
          paddingTop: 10,
          borderTop: "1px solid var(--border-dim)",
          color: "var(--text-muted)",
          fontSize: 11,
        }}
      >
        Bull put spread {toNum(s.short_delta)}Δ/{toNum(s.wing_delta)}Δ · ~
        {s.hold_days}d hold
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web && npm run test -- ShortVolPanel`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/ShortVolPanel.tsx web/tests/unit/ShortVolPanel.test.tsx
git commit -m "feat(web): ShortVolPanel — per-stock short-vol card"
```

---

### Task 4: Place `ShortVolPanel` on the Directional-Bias row

**Files:**
- Modify: `web/components/stock/tabs/MarketStructureTab.tsx`

**Interfaces:**
- Consumes: `ShortVolPanel` from Task 3.

- [ ] **Step 1: Add the import**

In `web/components/stock/tabs/MarketStructureTab.tsx`, add after the `DirectionalBiasPanel` import:

```tsx
import { ShortVolPanel } from "../panels/ShortVolPanel";
```

- [ ] **Step 2: Make the row a 3-column grid and add the panel**

Change `gridTemplateColumns: "1fr 1fr"` to `gridTemplateColumns: "1fr 1fr 1fr"`, and add the panel as the third child after `DirectionalBiasPanel`:

```tsx
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr 1fr",
          gap: 12,
        }}
      >
        <ExpectedRangeBar report={report} />
        <DirectionalBiasPanel report={report} history={historyRows} />
        <ShortVolPanel report={report} />
      </div>
```

- [ ] **Step 3: Typecheck**

Run: `cd web && npm run typecheck && cd ..`
Expected: no errors.

- [ ] **Step 4: Visual verification (real path)**

Start the stack if not running (`bash scripts/dev.sh`), open a real ticker that has `vrp_daily` history (e.g. `http://localhost:3001/stock/TSLA`), Market Structure tab. Confirm the Short-Vol card renders as the third card on the Directional-Bias row, with a TRADE or SKIP verdict, `vrp_z · weight`, `IV / RV20`, and the bull-put footer (or `No vol data yet.` for a ticker without history). Screenshot to `output/playwright/stock-short-vol-card.png`.

If the Expected-Range bar looks cramped at 1/3 width, change `gridTemplateColumns` to `"1.3fr 1fr 1fr"` and re-verify.

**Operational note (not a code bug):** the TRADE verdict depends on the VRP research tables `vrp_harvest_by_sector` / `vrp_harvest_multihorizon` being populated (the sellable-by-sector gate). On the prod mini these are kept fresh by the existing VRP jobs (`vrp_candidates` uses the same gate). On a fresh local dev DB that hasn't run those jobs, the tables are empty → every name reads `SKIP — sector vol not sellable`. That's expected; verify against a ticker known to be in a sellable sector, or confirm on the mini.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/tabs/MarketStructureTab.tsx
git commit -m "feat(web): add Short-Vol card to Market Structure directional-bias row"
```

---

## Self-Review

**1. Spec coverage** (against the approved design):
- "Same UI card, per stock" → Task 3 `ShortVolPanel` mirrors `MacroShortVolCard` content (verdict, `vrp_z·weight`, `IV/RV20`, bull-put footer) using the row's `panelStyle`. ✓
- "Same line as Directional Bias" → Task 4, 2→3 column grid. ✓
- "Full readout" (verdict + vrp_z + weight + IV/RV + concrete spread) → `decide_short_vol` TRADE branch builds strikes/credit/max_loss; panel renders them. ✓
- "Sector gate + vrp_z" verdict → `decide_short_vol`: `rich (z≥RICH_Z) AND gate_ok AND known earnings clear of window`. ✓
- Bull put spread reused (condor = noted upgrade path) → `build_bull_put_spread` reused. ✓
- EOD basis, no new endpoint/job/migration → folded into `assemble_single_stock_report`; `basis="eod"`, EOD-close spot. ✓
- Persist-results rule → `vrp_daily` already persisted; read-time reshape only. ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows full content; commands have expected output. ✓

**3. Type consistency:** `decide_short_vol`/`build_short_vol` signatures match between Task 1 definition, the Task 1 test, and the Task 2 caller. `StockShortVol` field names match across model (Task 1), TS schema (Task 2), and panel reads (Task 3). `gate_ok` used consistently. ✓

**4. Robustness (hardened after independent review):**
- **Unknown earnings never TRADE** — `passes_gate` only proves a calendar *exists*; the next date is sourced from `fetch_latest_next_earnings_date` and `None` → SKIP "earnings date unavailable" (matches `scanner.gates.earnings_gate`). ✓
- **Non-finite `vrp_z_20`/iv never reach Pydantic** — `_finite()` normalizes NaN/inf → None (the rolling z-window emits NaN on short histories); `Decimal("NaN")` can't form. ✓
- **Card failure never breaks the page** — `build_short_vol` is wrapped in `try/except … # noqa: BLE001` in the assembler; logs + degrades to `short_vol=None`. ✓
- **Existing `test_report_assembly.py` stays green** — Task 2 Step 3 adds `fetch_vrp_daily_series→[]` to its stub + asserts `short_vol is None` (clean degrade, not exception-swallow). ✓

**Known risk flagged in-plan:** `web/lib/types.ts` regen may reorder the whole file — Task 2 Step 7 gives both the clean-diff path and a robust extract-and-splice fallback (content lifted from a fresh generation, anchored before `StrikeExposureRow`'s JSDoc). The OpenAPI snapshot test compares parsed JSON, so it is robust to formatting.
