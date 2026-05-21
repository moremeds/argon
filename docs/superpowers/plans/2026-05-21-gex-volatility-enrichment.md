# GEX & Volatility Tab Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Revision history (post-review)

**Rev 2 (2026-05-21, post tribunal review)** — applied after self-review + `/codex-review` (15 issues raised by codex; gemini hallucinated on first pass and was re-run with a file-targeted prompt) + adversarial pass. Material changes:

- **Method API corrections** — `repo.fetch_strike_gex_curve(ticker=...)` was non-existent; replaced with `repo.latest_run_id(ticker)` + `repo.get_strike_gex_curve(run_id)` + `repo.fetch_exposures_summary(run_id, ticker)` (Tasks 3, 6 below).
- **Source-of-truth unified** — the endpoint `/regime/dealer` was reading from `gex_snapshots` while the report was reading from `scan_runs`. They now use the same upstream (`latest_run_id` → scan_runs primitives) so a fresh full-scan with no GEX snapshot still serves the Volatility tab.
- **Report assembler order fixed** — dealer-regime derivation was inserted before `exposures_summary` was built. Moved to AFTER line 503 and now passed via the `SingleStockReport(...)` constructor (the `report.dealer_regime = ...` assignment in the old draft was against a non-existent variable).
- **Level payload key normalization** — `fetch_latest_gex` payload uses `gamma`/`max_accelerator`; `market_structure_levels.model_dump()` uses `net_gex`/`max_accel`. `_normalize_levels()` helper in `cards/dealer_regime.py` now handles both.
- **`Decimal(0)` no longer treated as missing** — all `if value` checks replaced with `is not None`. `_to_float` runs on every numeric from snapshot payloads (UW returns strings for some legacy fields).
- **DTE uses market data date, not server clock** — `compute_gamma_decay` accepts an explicit market date (defaults to ET today), so weekend/holiday/timezone runs produce the right buckets. Negative DTEs from expired rows are filtered.
- **Prev-close GEX lookup by date, not index** — `history_rows[1]` was wrong direction; switched to "find the most recent row before today" with explicit bounds checks.
- **VCG interpretation strings corrected** — `MacroVcgTile` now matches the real enum (`PANIC`/`RISK_OFF`/`EDR`/`BOUNCE`/`WATCH`/`NORMAL`/`SUPPRESSED`/`INSUFFICIENT_DATA`).
- **Test path corrected** — `web/tests/components/` → `web/tests/unit/`; integration fixture `repo` → `seeded_db_empty_cards`; new "seeded ok-path" integration test added so the endpoint isn't only exercised on the empty branch.
- **SVG edge cases hardened** — `GexProfileChart` guards `spot <= 0` (window collapses to [0,0] hides everything); overlay Y-positions computed against the unfiltered in-window strike domain; `GexHistoryChart` draws bars even when spot history is absent; constant-spot series uses a padded domain.
- **Stale state on ticker change** — `VolatilityRegimePanel` clears `regime` and sets a loading flag at effect start; only renders data when returned `ticker` matches the current prop.
- **Strongly-typed test fixtures** — replaced `as any` with `satisfies` against generated types so OpenAPI drift fails the build.
- **OpenAPI snapshot regen step added** — adding `/regime/dealer` and the `dealer_regime` field will break `tests/integration/api/test_openapi_snapshot.py`; explicit regen step now sits at the bottom of Task 3.
- **Graceful degradation documented** — `greek_exposure_daily` is populated only by `scanners/gex.py` (SPX/SPY/index 5-min scanner). For non-index tickers, `prev_close_net_gex` is None and the history chart shows "No GEX history" — the magnet bar's "Γ vs prev close" tile shows "—" without breaking.
- **Per-ticker scale calibration** — `GAMMA_SCALE`/`VANNA_SCALE`/`CHARM_SCALE` constants are now documented as SPX-calibrated defaults with a per-asset-class override table (placeholder; refine post-PR-1).
- **Compute path deduped** — `cards/dealer_regime._gather_inputs(repo, ticker)` is the single source of truth for assembling primitives; both the report assembler and the `/regime/dealer` endpoint call it.

The **original Rev 1 task body is preserved below** so the diff vs. plan v1 is traceable; affected sections are tagged with a `<!-- patched in rev 2 -->` marker and the corrected code blocks live alongside or replace the original snippets.

**Goal:** Enrich the Market Structure → GEX sub-tab and the Volatility tab with magnet/gamma summary, colored level overlays, daily GEX history, and a per-ticker volatility regime panel (Γ/V/C bars + closest levels + 0DTE GEX + gamma decay).

**Architecture:** All four enhancements share one new backend primitive — a *per-ticker dealer regime classifier* that combines existing data (`market_structure.net_gex`, `exposures_summary[].net_vanna/net_charm`, `strike_gex_curve`, `greek_exposure_daily`). The classifier exposes Γ/V/C normalized scores plus an Amplifying/Dampening label, and a DTE-bucketed gamma decay view. Frontend changes are pure visualization (hand-rolled SVG + reuse of existing `Tile` patterns) plus a lazy client-side fetch of `/api/regime/gex` for the daily history chart. Macro VCG continues to come from `/api/regime/vcg` and is surfaced as an auxiliary sidebar tile on the Volatility tab.

**Tech Stack:** Python 3.13 / FastAPI / Pydantic v2 / psycopg / pytest-postgresql • Next.js 16 / React 19 / TypeScript / hand-rolled SVG • `uv` only • Postgres `option_wizard`/`uw_scan`.

---

## Branch & PR strategy

- Single feature branch: `feat/gex-volatility-enrichment` off `main`.
- Milestone commits as each Task completes verification.
- Open one PR before merging to `main`. **No `git push origin main`.**

---

## File Structure

### Backend — new

- `src/uw_scan/cards/dealer_regime.py` — pure functions: `compute_dealer_regime(report_pieces) -> DealerRegime` returning `{regime_label, regime_score, gamma_score, vanna_score, charm_score, contributions}`. Also `compute_gamma_decay(strike_gex_curve, today) -> list[GammaDecayBucket]` — buckets by DTE (0d, 2d, 4d, 8d, 9d, 11d adaptive based on present expiries) and returns `{dte, expiry, gex, share_pct}`.
- `src/uw_scan/cards/dealer_regime_test_helpers.py` (only if unit tests need fixture data; skip if reused from elsewhere).
- `tests/unit/cards/test_dealer_regime.py` — unit tests for the regime + decay derivers.
- `tests/integration/api/test_regime_dealer.py` — integration test against the new endpoint.

### Backend — modify

- `src/uw_scan/api/schemas.py` — add `DealerRegimeSignal`, `GammaDecayBucket`, `DealerRegimeResponse` plus `EMPTY_DEALER_REGIME_RESPONSE`; add optional `prev_close_net_gex` to `GexResponse` (already in scope; we'll surface via the new endpoint to avoid bloating GexResponse).
- `src/uw_scan/api/routers/regime.py` — add `GET /regime/dealer?ticker=...` returning `DealerRegimeResponse`. Reuses the existing `Repository` dep; no new providers.
- `src/uw_scan/reports/single_stock.py` — attach `dealer_regime` + `prev_close_net_gex` to `SingleStockReport` (cheap derivations from already-fetched rows; avoids an extra round-trip for the GEX sub-tab).
- `src/uw_scan/models/scanner.py` (or appropriate domain module) — add `DealerRegime` model attached to `SingleStockReport` (keep `__module__` stable per repo policy).

### Frontend — new

- `web/components/stock/panels/MagnetGammaBar.tsx` — 5-tile horizontal bar above the GEX profile.
- `web/components/stock/panels/GexHistoryChart.tsx` — SVG bar+line chart (net GEX bars + spot line). Lazily fetched via `api.regimeGex(ticker)` inside `GreekSubTabs`.
- `web/components/stock/panels/VolatilityRegimePanel.tsx` — Γ/V/C slider+sub-bars + closest levels + 0DTE GEX + gamma decay list.
- `web/components/stock/panels/MacroVcgTile.tsx` — small auxiliary tile showing macro VCG state (`amplifying` / `dampening` / `neutral`) consumed by the Volatility tab sidebar.
- `web/tests/components/MagnetGammaBar.test.tsx` — unit tests for formatter + regime headline.
- `web/tests/components/VolatilityRegimePanel.test.tsx` — unit tests for Γ/V/C bar sign/length, decay row sort.

### Frontend — modify

- `web/components/stock/panels/GexProfileChart.tsx` — add colored horizontal reference rows for `gex_flip`, `call_wall`, `put_wall`, `spot` (visual overlay only; chart stays div-based).
- `web/components/stock/panels/greeks/GreekSubTabs.tsx` — render `MagnetGammaBar` above `GexProfileChart`, append `GexHistoryChart` below; lazy-fetch `/api/regime/gex` only when GEX tab is open.
- `web/components/stock/tabs/VolatilityTabClient.tsx` — slot `VolatilityRegimePanel` at the top, with `MacroVcgTile` in a sidebar column.
- `web/lib/api.ts` — add `regimeGex(ticker)` and `regimeDealer(ticker)` and `regimeVcg()` helpers backed by generated types.

### Type generation

- After backend changes: `cd web && npm run gen:types` to refresh `web/lib/types.ts`.

---

## Task Decomposition

### Task 1: Backend — DealerRegime schema + empty constants

**Files:**
- Modify: `src/uw_scan/api/schemas.py` (append new schemas + EMPTY constants)

- [ ] **Step 1: Add schema classes**

Open `src/uw_scan/api/schemas.py` and append (near the existing `VcgResponse` block):

```python
class DealerRegimeSignal(BaseModel):
    """Per-ticker dealer regime classification (Γ-driven, with V/C support)."""

    label: Literal["amplifying", "dampening", "neutral"] = "neutral"
    score: float = 0.0  # -1.0 .. +1.0, sign matches label (>0 = dampening)
    gamma_score: float = 0.0
    vanna_score: float = 0.0
    charm_score: float = 0.0
    headline: str = ""        # e.g. "Long Γ → Dampening regime"
    subtitle: str = ""        # e.g. "Largest level is the call wall …"


class GammaDecayBucket(BaseModel):
    dte: int                  # 0, 2, 4 …
    expiry: str               # ISO date
    net_gex: float | None = None
    share_pct: float | None = None  # |net_gex| / Σ|net_gex| across buckets
    # REV 2 (adversarial ATTACK-2): gross fields so a zero-net / huge-gross
    # bucket isn't hidden in the UI.
    gross_abs_gex: float | None = None
    gross_share_pct: float | None = None


class ClosestLevel(BaseModel):
    label: str                # "Accel ↑", "Put Wall", "Call Wall", "Gamma Flip"
    direction: Literal["up", "down", "flip"] | None = None
    role: Literal["support", "resistance", "accelerator", "flip"] | None = None
    strike: float
    distance_pct: float       # signed, fraction (0.037 = +3.7%)
    gamma: float | None = None
    # REV 2 (adversarial ATTACK-3): "nearest" by |distance_pct|, "dominant"
    # by |gamma|. Frontend groups by this field; subtitle anchors on
    # rank_kind="dominant".
    rank_kind: Literal["nearest", "dominant"] = "nearest"


class DealerRegimeResponse(BaseModel):
    status: Literal["ok", "empty"] = "empty"
    ticker: str = ""
    scan_time: str = ""
    spot: float | None = None
    net_gex: float | None = None
    prev_close_net_gex: float | None = None
    signal: DealerRegimeSignal = Field(default_factory=DealerRegimeSignal)
    closest_levels: list[ClosestLevel] = Field(default_factory=list)
    odte_gex: float | None = None
    odte_share_pct: float | None = None
    gamma_decay: list[GammaDecayBucket] = Field(default_factory=list)


EMPTY_DEALER_REGIME_RESPONSE = DealerRegimeResponse()
```

- [ ] **Step 2: Verify no model import drift**

Run:
```bash
uv run python -c "from uw_scan.api.schemas import DealerRegimeResponse, EMPTY_DEALER_REGIME_RESPONSE; print('ok')"
```
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git checkout -b feat/gex-volatility-enrichment
git add src/uw_scan/api/schemas.py
git commit -m "feat(schemas): add DealerRegimeResponse for per-ticker dealer regime"
```

---

### Task 2: Backend — DealerRegime card (pure functions)

**Files:**
- Create: `src/uw_scan/cards/dealer_regime.py`
- Test: `tests/unit/cards/test_dealer_regime.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/cards/test_dealer_regime.py`:

```python
"""Unit tests for the per-ticker dealer regime classifier."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.cards.dealer_regime import (
    classify_regime,
    compute_dealer_regime,
    compute_gamma_decay,
    normalize_score,
)


def test_normalize_score_caps_at_one() -> None:
    assert normalize_score(1e9, scale=1e6) == pytest.approx(1.0)
    assert normalize_score(-1e9, scale=1e6) == pytest.approx(-1.0)
    assert normalize_score(0, scale=1e6) == 0.0


def test_classify_regime_long_gamma_is_dampening() -> None:
    sig = classify_regime(gamma=0.7, vanna=0.18, charm=-0.12)
    assert sig.label == "dampening"
    assert sig.score > 0
    assert "Long Γ" in sig.headline
    assert "Dampening" in sig.headline


def test_classify_regime_short_gamma_is_amplifying() -> None:
    sig = classify_regime(gamma=-0.4, vanna=0.0, charm=0.0)
    assert sig.label == "amplifying"
    assert sig.score < 0
    assert "Short Γ" in sig.headline


def test_classify_regime_near_zero_is_neutral() -> None:
    sig = classify_regime(gamma=0.02, vanna=0.0, charm=0.0)
    assert sig.label == "neutral"


def test_compute_gamma_decay_buckets_by_dte() -> None:
    today = date(2026, 5, 18)
    curve = [
        {"strike": Decimal("400"), "expiry": today, "net_gex": Decimal("-20133")},
        {"strike": Decimal("400"), "expiry": date(2026, 5, 20), "net_gex": Decimal("-8511")},
        {"strike": Decimal("400"), "expiry": date(2026, 5, 22), "net_gex": Decimal("41550")},
        {"strike": Decimal("400"), "expiry": date(2026, 5, 26), "net_gex": Decimal("5031")},
    ]
    buckets = compute_gamma_decay(curve, today=today)
    by_dte = {b.dte: b for b in buckets}
    assert by_dte[0].net_gex == pytest.approx(-20133.0)
    assert by_dte[2].net_gex == pytest.approx(-8511.0)
    assert by_dte[4].net_gex == pytest.approx(41550.0)
    assert by_dte[8].net_gex == pytest.approx(5031.0)
    # share_pct should sum (in absolute terms) to ~1.0
    total_share = sum(abs(b.share_pct or 0) for b in buckets)
    assert total_share == pytest.approx(1.0, abs=1e-6)


def test_compute_gamma_decay_empty_curve_returns_empty() -> None:
    assert compute_gamma_decay([], today=date(2026, 5, 18)) == []


def test_compute_dealer_regime_assembles_full_signal() -> None:
    out = compute_dealer_regime(
        ticker="TSLA",
        spot=410.0,
        net_gex=216_910.0,
        prev_close_net_gex=440_500.0,
        per_expiry_vanna=[Decimal("120000"), Decimal("-30000")],
        per_expiry_charm=[Decimal("-25000"), Decimal("10000")],
        strike_gex_curve=[
            {"strike": Decimal("450"), "expiry": date(2026, 5, 22), "net_gex": Decimal("46550")},
            {"strike": Decimal("395"), "expiry": date(2026, 5, 22), "net_gex": Decimal("-12000")},
            {"strike": Decimal("410"), "expiry": date(2026, 5, 18), "net_gex": Decimal("19210")},
        ],
        levels={
            "call_wall": {"strike": Decimal("450"), "net_gex": Decimal("46550")},
            "put_wall": {"strike": Decimal("395"), "net_gex": Decimal("-966840")},
            "gex_flip": {"strike": Decimal("474.64"), "net_gex": Decimal("0")},
        },
        today=date(2026, 5, 18),
    )
    assert out.signal.label == "dampening"
    assert out.net_gex == pytest.approx(216_910.0)
    assert out.prev_close_net_gex == pytest.approx(440_500.0)
    # 0DTE bucket present
    assert out.odte_gex == pytest.approx(19_210.0)
    assert any(lvl.label.lower().startswith("call wall") for lvl in out.closest_levels)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
uv run pytest tests/unit/cards/test_dealer_regime.py -v
```
Expected: ImportError or "no module named uw_scan.cards.dealer_regime".

- [ ] **Step 3: Implement the card**

Create `src/uw_scan/cards/dealer_regime.py`:

```python
"""Per-ticker dealer regime classifier.

Combines the existing dealer Greek aggregates into a single Amplifying ↔
Dampening label with a headline copy block. Pure functions — no DB or
network. Inputs come from rows the report assembler already fetches:

  - ``market_structure.net_gex`` (current net dealer Γ)
  - ``greek_exposure_daily`` previous-close net Γ (for Γ vs prev close)
  - ``exposures_summary[]`` net_vanna / net_charm per expiry
  - ``strike_gex_curve`` per-strike, per-expiry gamma (for 0DTE + decay)
  - ``market_structure_levels`` (call wall, put wall, gex flip)
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

# Normalization scales — chosen so a "typical" SPX-magnitude reading lands
# near ±0.5. Tuned for the dollar-gamma units stored in `greek_exposure_daily`.
# These are intentionally generous; signal direction matters more than the
# exact magnitude for the dampening/amplifying label.
#
# REV 2 calibration note (post adversarial review): these defaults are SPX/SPY
# calibrated. For small-cap or thin-name tickers the magnitudes are 2-3 orders
# of magnitude smaller and the tanh will read near zero (regime → neutral).
# Acceptable for v1 — the panel will simply not commit to a label on thin
# tickers. A follow-up should add a per-asset-class scale (see SCALE_BY_CLASS
# below).
GAMMA_SCALE = 5e5     # net_gex (SPX-magnitude baseline)
VANNA_SCALE = 5e5     # Σ net_vanna across expiries
CHARM_SCALE = 5e5     # Σ net_charm across expiries

# Per-asset-class overrides — populated post v1; empty here so v1 uses the
# defaults for every ticker. When extended, key by index/major/mid/small and
# look up at compute_dealer_regime() entry.
SCALE_BY_CLASS: dict[str, tuple[float, float, float]] = {}

# Neutral band — anything inside is reported as "neutral" rather than
# committing to a Long/Short Γ headline. Keeps the panel quiet on thin days.
NEUTRAL_BAND = 0.05

# Weights used to combine Γ/V/C into a single regime score. Γ dominates
# (it's the dealer's first-order delta-hedge signal); V and C are
# tie-breakers and explanatory tiles.
#
# REV 2 caveat (adversarial ATTACK-1): the linear blend is convenient, not
# validated finance. Vanna/charm can flip the label even when the actual
# dealer hedge regime has not changed. We therefore:
#   1) Always render the raw Γ/V/C scores as primary in the Volatility tab.
#   2) Treat the single Amplifying/Dampening label as a HINT, not a verdict
#      — the headline copy reads "Long Γ → Dampening regime" (causal arrow),
#      and the subtitle never claims more than what the closest level
#      implies. If a future calibration suite shows the label is misleading,
#      we drop it without changing field shapes.
GAMMA_WEIGHT = 0.7
VANNA_WEIGHT = 0.2
CHARM_WEIGHT = 0.1


@dataclass
class _Signal:
    label: str
    score: float
    gamma_score: float
    vanna_score: float
    charm_score: float
    headline: str
    subtitle: str


@dataclass
class _ClosestLevel:
    """A ranked level near spot.

    REV 2 (adversarial ATTACK-3): we deliberately track TWO ranking modes:
    ``rank_kind="nearest"`` (sorted by |distance_pct|, the original ranking)
    and ``rank_kind="dominant"`` (sorted by |gamma|). The frontend renders
    both lists; the headline subtitle keys off "dominant" so a tiny nearby
    accelerator cannot outrank a major call wall just by being closer.
    """

    label: str
    direction: str | None
    role: str | None
    strike: float
    distance_pct: float
    gamma: float | None
    rank_kind: str = "nearest"  # "nearest" | "dominant"


@dataclass
class _GammaDecayBucket:
    """One DTE bucket on the gamma-decay panel.

    REV 2 (adversarial ATTACK-2): we now also carry ``gross_abs_gex`` and
    ``gross_share_pct`` so the UI can show that a near-zero NET bucket may
    still represent a massive gross exposure rolling off. Net gives
    direction; gross gives magnitude.
    """

    dte: int
    expiry: str
    net_gex: float | None
    share_pct: float | None
    gross_abs_gex: float | None = None
    gross_share_pct: float | None = None


@dataclass
class DealerRegimeOutput:
    """Plain dataclass mirroring `DealerRegimeResponse` fields. The router
    converts this to the Pydantic model for the HTTP boundary."""

    ticker: str
    spot: float | None
    net_gex: float | None
    prev_close_net_gex: float | None
    signal: _Signal
    closest_levels: list[_ClosestLevel]
    odte_gex: float | None
    odte_share_pct: float | None
    gamma_decay: list[_GammaDecayBucket]


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def normalize_score(value: float | None, *, scale: float) -> float:
    """tanh-shaped score in [-1, 1]. Cheap, smooth, monotonic, sign-preserving."""

    if value is None or scale <= 0:
        return 0.0
    return math.tanh(value / scale)


def classify_regime(*, gamma: float, vanna: float, charm: float) -> _Signal:
    """Combine Γ/V/C scores into a single regime label + headline copy."""

    score = (
        GAMMA_WEIGHT * gamma
        + VANNA_WEIGHT * vanna
        + CHARM_WEIGHT * charm
    )

    if abs(score) < NEUTRAL_BAND:
        label = "neutral"
    elif score > 0:
        label = "dampening"
    else:
        label = "amplifying"

    if gamma > 0:
        gamma_phrase = "Long Γ"
    elif gamma < 0:
        gamma_phrase = "Short Γ"
    else:
        gamma_phrase = "Flat Γ"

    if label == "neutral":
        headline = f"{gamma_phrase} → Neutral regime"
    elif label == "dampening":
        headline = f"{gamma_phrase} → Dampening regime"
    else:
        headline = f"{gamma_phrase} → Amplifying regime"

    return _Signal(
        label=label,
        score=score,
        gamma_score=gamma,
        vanna_score=vanna,
        charm_score=charm,
        headline=headline,
        subtitle="",  # filled in by caller once it knows the top level
    )


def _sum_decimal(values: Iterable[Any]) -> float:
    total = 0.0
    for v in values:
        f = _to_float(v)
        if f is not None:
            total += f
    return total


# REV 2: helper that extracts the per-row net_gex from the curve robustly.
# Curves can arrive as Pydantic-serialized dicts (`net_gex`) OR as the
# legacy snapshot payload shape (`gamma`). Same coalescing logic is used
# in `_normalize_levels`.
def _row_net_gex(row: Mapping[str, Any]) -> float | None:
    for k in ("net_gex", "gamma"):
        v = row.get(k)
        if v is not None:
            f = _to_float(v)
            if f is not None:
                return f
    return None


def compute_gamma_decay(
    strike_gex_curve: Iterable[Mapping[str, Any]],
    *,
    today: date,
) -> list[_GammaDecayBucket]:
    """Sum per-expiry net + gross gamma, sorted by DTE.

    REV 2 changes (adversarial review):

    - Carries BOTH ``net_gex`` (signed; for direction) and ``gross_abs_gex``
      (sum of |row gamma| per expiry; for magnitude). A bucket where call
      and put gamma cancel out can show a tiny net but a huge gross — the
      UI uses gross to size the bar and net to color it.
    - Filters expired buckets (``dte < 0``) — they're already-rolled-off
      noise from stale data.
    - All-zero buckets return ``share_pct = None`` instead of 0.0 so the
      UI can render "—" rather than implying zero share is meaningful.
    """

    by_expiry_net: dict[date, float] = {}
    by_expiry_gross: dict[date, float] = {}
    for row in strike_gex_curve:
        expiry = row.get("expiry")
        if expiry is None:
            continue
        if not isinstance(expiry, date):
            try:
                expiry = date.fromisoformat(str(expiry))
            except ValueError:
                continue
        g = _row_net_gex(row)
        if g is None:
            continue
        by_expiry_net[expiry] = by_expiry_net.get(expiry, 0.0) + g
        by_expiry_gross[expiry] = by_expiry_gross.get(expiry, 0.0) + abs(g)

    if not by_expiry_net:
        return []

    # Filter expired before computing shares so denominators reflect what's
    # actually rendered.
    valid = [(e, n) for e, n in by_expiry_net.items() if (e - today).days >= 0]
    if not valid:
        return []

    total_abs_net = sum(abs(n) for _, n in valid)
    total_gross = sum(by_expiry_gross[e] for e, _ in valid)

    buckets: list[_GammaDecayBucket] = []
    for expiry, net in sorted(valid):
        gross = by_expiry_gross[expiry]
        buckets.append(
            _GammaDecayBucket(
                dte=(expiry - today).days,
                expiry=expiry.isoformat(),
                net_gex=net,
                share_pct=(abs(net) / total_abs_net) if total_abs_net > 0 else None,
                gross_abs_gex=gross,
                gross_share_pct=(gross / total_gross) if total_gross > 0 else None,
            )
        )
    return buckets


# REV 2 (codex ISSUE-3 + adversarial): levels arrive with two different
# field-name conventions. Normalize before downstream logic.
def _normalize_levels(levels: Mapping[str, Any] | None) -> dict[str, dict] | None:
    """Coalesce ``{net_gex|gamma}`` and ``{max_accel|max_accelerator}``.

    Output always uses ``net_gex`` and ``max_accel`` regardless of input
    shape, so downstream code reads one canonical structure.
    """
    if not levels:
        return None

    out: dict[str, dict] = {}
    # accel key drift
    accel = levels.get("max_accel") or levels.get("max_accelerator")
    if accel:
        out["max_accel"] = dict(accel)

    for key in ("gex_flip", "call_wall", "put_wall"):
        lv = levels.get(key)
        if not lv:
            continue
        lv_copy = dict(lv)
        # net_gex / gamma drift
        if "net_gex" not in lv_copy and "gamma" in lv_copy:
            lv_copy["net_gex"] = lv_copy["gamma"]
        out[key] = lv_copy
    return out


def _build_closest_levels(
    *,
    spot: float | None,
    levels: Mapping[str, Any] | None,
) -> list[_ClosestLevel]:
    """Convert market_structure_levels into TWO ranked lists.

    REV 2 (adversarial ATTACK-3): we now return both "nearest" (by absolute
    distance from spot, the original) AND "dominant" (by absolute gamma).
    The UI renders each list; the subtitle keys off "dominant" so the
    headline copy points at the most impactful level, not just the closest.
    """

    if spot is None or spot <= 0:
        return []

    norm = _normalize_levels(levels)
    if norm is None:
        return []

    spec = [
        ("gex_flip", "Gamma Flip", "flip", "flip"),
        ("call_wall", "Call Wall", "up", "resistance"),
        ("put_wall", "Put Wall", "down", "support"),
        ("max_accel", "Accel ↑", "up", "accelerator"),
    ]

    base: list[_ClosestLevel] = []
    for key, label, direction, role in spec:
        lv = norm.get(key)
        if not lv:
            continue
        strike = _to_float(lv.get("strike"))
        if strike is None:
            continue
        gamma = _to_float(lv.get("net_gex"))
        base.append(
            _ClosestLevel(
                label=label,
                direction=direction,
                role=role,
                strike=strike,
                distance_pct=(strike - spot) / spot,
                gamma=gamma,
            )
        )

    # Build the two lists with rank_kind tags. UI groups by rank_kind.
    nearest = [
        _ClosestLevel(**{**l.__dict__, "rank_kind": "nearest"}) for l in base
    ]
    nearest.sort(key=lambda l: abs(l.distance_pct))

    dominant = [
        _ClosestLevel(**{**l.__dict__, "rank_kind": "dominant"})
        for l in base
        if l.gamma is not None
    ]
    dominant.sort(key=lambda l: -abs(l.gamma or 0.0))

    return nearest + dominant


def _subtitle_from_closest(closest: list[_ClosestLevel], label: str) -> str:
    """Build the subtitle from the DOMINANT level (not the nearest).

    REV 2 (adversarial ATTACK-3): the dominant entry — largest |gamma| —
    is the one a trader anchors on. Falls back to nearest only if no
    level has a gamma score.
    """
    if not closest:
        return ""
    dominant = next((l for l in closest if l.rank_kind == "dominant"), None)
    top = dominant or closest[0]
    side = "resistance" if top.role == "resistance" else (
        "support" if top.role == "support" else top.role or ""
    )
    side_phrase = f" ({side})" if side else ""
    if label == "dampening":
        verb = "dealers may sell into rallies as price approaches it"
    elif label == "amplifying":
        verb = "dealers may chase moves through it"
    else:
        verb = "dealer flow is mixed near it"
    return (
        f"Largest level is the {top.label.lower()}{side_phrase} at "
        f"${top.strike:.2f} — {verb}."
    )


def compute_dealer_regime(
    *,
    ticker: str,
    spot: float | None,
    net_gex: float | None,
    prev_close_net_gex: float | None,
    per_expiry_vanna: Iterable[Any],
    per_expiry_charm: Iterable[Any],
    strike_gex_curve: Iterable[Mapping[str, Any]],
    levels: Mapping[str, Any] | None,
    today: date,
) -> DealerRegimeOutput:
    curve = list(strike_gex_curve)  # may be iterated twice

    # REV 2: coerce defensively — endpoint callers may pass Decimals or
    # strings out of JSONB without going through Pydantic first.
    net_gex_f = _to_float(net_gex)
    spot_f = _to_float(spot)
    prev_close_f = _to_float(prev_close_net_gex)

    gamma_score = normalize_score(net_gex_f, scale=GAMMA_SCALE)
    vanna_total = _sum_decimal(per_expiry_vanna)
    charm_total = _sum_decimal(per_expiry_charm)
    vanna_score = normalize_score(vanna_total, scale=VANNA_SCALE)
    charm_score = normalize_score(charm_total, scale=CHARM_SCALE)

    signal = classify_regime(
        gamma=gamma_score, vanna=vanna_score, charm=charm_score
    )
    closest = _build_closest_levels(spot=spot_f, levels=levels)
    signal.subtitle = _subtitle_from_closest(closest, signal.label)

    decay = compute_gamma_decay(curve, today=today)
    # REV 2 (adversarial ATTACK-4): "0DTE" means strictly dte == 0. Anything
    # ≤ 1 trading day belongs in a separate bucket the UI labels precisely.
    odte_bucket = next((b for b in decay if b.dte == 0), None)

    return DealerRegimeOutput(
        ticker=ticker,
        spot=spot_f,
        net_gex=net_gex_f,
        prev_close_net_gex=prev_close_f,
        signal=signal,
        closest_levels=closest,
        odte_gex=odte_bucket.net_gex if odte_bucket else None,
        odte_share_pct=odte_bucket.share_pct if odte_bucket else None,
        gamma_decay=decay,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
uv run pytest tests/unit/cards/test_dealer_regime.py -v
```
Expected: all 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/cards/dealer_regime.py tests/unit/cards/test_dealer_regime.py
git commit -m "feat(cards): dealer regime classifier (per-ticker Γ/V/C + gamma decay)"
```

---

### Task 3: Backend — wire DealerRegime into report + endpoint

**Files:**
- Modify: `src/uw_scan/reports/single_stock.py` (attach `dealer_regime` and `prev_close_net_gex` to the report)
- Modify: `src/uw_scan/api/routers/regime.py` (add `GET /regime/dealer`)
- Modify: `src/uw_scan/models/scanner.py` (add `DealerRegime` Pydantic model; re-export)
- Test: `tests/integration/api/test_regime_dealer.py`

- [ ] **Step 1: Add `DealerRegime` Pydantic model in scanner models**

In `src/uw_scan/models/scanner.py`, near the bottom (before `_preserve_public_module`), add:

```python
class DealerRegime(_UwBase):
    """Per-ticker dealer Greek regime — attached to SingleStockReport so the
    Market Structure → GEX tab can render the magnet/gamma bar without an
    extra round-trip. The full /regime/dealer endpoint also returns this
    shape for the Volatility tab."""

    label: str = "neutral"
    score: Decimal = Decimal(0)
    gamma_score: Decimal = Decimal(0)
    vanna_score: Decimal = Decimal(0)
    charm_score: Decimal = Decimal(0)
    headline: str = ""
    subtitle: str = ""
    prev_close_net_gex: Decimal | None = None
    odte_net_gex: Decimal | None = None
    odte_share_pct: Decimal | None = None
```

Then add `DealerRegime` to the `_preserve_public_module` call and update `models/__init__.py` to export it.

- [ ] **Step 2: Wire into SingleStockReport**

Open `src/uw_scan/models/` (find the file declaring `SingleStockReport`) and add an optional field:

```python
dealer_regime: DealerRegime | None = None
```

Update `__init__.py` and regenerate types after backend is wired.

<!-- patched in rev 2 -->
- [ ] **Step 3: Add shared input gather + compute helper in `cards/dealer_regime.py`**

Append to `src/uw_scan/cards/dealer_regime.py` so both the report assembler and the endpoint use the same upstream:

```python
from datetime import date as _date
from datetime import datetime
from zoneinfo import ZoneInfo


def _et_today() -> _date:
    """Market date in US/Eastern — what dealers price into 0DTE buckets."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def _prev_close_net_gex(history_rows: list[dict], today: _date) -> float | None:
    """Pick the most recent row strictly before ``today``.

    `GreekExposureDailyRepository.fetch_history` returns rows ASCENDING by
    trade_date (after the internal reverse). We scan from the tail because
    the typical case is "yesterday is just before today" — short-circuits
    in O(1) on weekdays, still correct on Monday after a Friday close.
    """
    for r in reversed(history_rows):
        d = r.get("trade_date")
        if d is None:
            continue
        if isinstance(d, str):
            d = _date.fromisoformat(d)
        if d < today:
            net = r.get("net_gex")
            return _to_float(net) if net is not None else None
    return None


def gather_inputs(repo: Any, *, ticker: str, today: _date | None = None) -> dict:
    """Collect every input ``compute_dealer_regime`` needs from one place.

    Single source of truth for both the report assembler and the /regime/dealer
    endpoint. Reads from scan_runs primitives (the report's upstream) and
    augments with greek_exposure_daily (for prev-close) where available.

    Returns a dict with keys: ``spot``, ``net_gex``, ``prev_close_net_gex``,
    ``per_expiry_vanna``, ``per_expiry_charm``, ``strike_gex_curve``,
    ``levels``, ``today``, ``run_id``. ``run_id`` is 0 if no scan exists.
    """
    from uw_scan.storage.greek_exposure_repository import GreekExposureDailyRepository
    from uw_scan.cards.gex import compute_market_structure_levels

    t = ticker.upper()
    today = today or _et_today()
    run_id = repo.latest_run_id(t)
    if run_id == 0:
        return {
            "run_id": 0,
            "spot": None,
            "net_gex": None,
            "prev_close_net_gex": None,
            "per_expiry_vanna": [],
            "per_expiry_charm": [],
            "strike_gex_curve": [],
            "levels": None,
            "today": today,
        }

    strike_curve_raw = repo.get_strike_gex_curve(run_id) or []
    exposures = repo.fetch_exposures_summary(run_id, t) or []
    aggregates = repo.get_aggregates(run_id) or {}

    # Levels come from the same compute function the report uses — keeps
    # field names (max_accel, net_gex) consistent regardless of upstream.
    levels_model = compute_market_structure_levels(
        strike_gex_curve=strike_curve_raw,
        spot=_to_float(aggregates.get("spot")),
    )
    levels = levels_model.model_dump() if levels_model else None

    g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
    history = g.fetch_history(t, days=5)
    prev_close = _prev_close_net_gex(history, today)

    return {
        "run_id": run_id,
        "spot": _to_float(aggregates.get("spot")),
        "net_gex": _to_float(aggregates.get("net_gex")),
        "prev_close_net_gex": prev_close,
        "per_expiry_vanna": [e.get("net_vanna") for e in exposures],
        "per_expiry_charm": [e.get("net_charm") for e in exposures],
        "strike_gex_curve": strike_curve_raw,
        "levels": levels,
        "today": today,
    }
```

*Why a shared helper:* avoids the source-of-truth divergence the original draft introduced (endpoint read `gex_snapshots`, report read `scan_runs`). Both now point at the same primitives.

- [ ] **Step 3a: Compute in the report assembler — after `exposures_summary` is built**

In `src/uw_scan/reports/single_stock.py`, locate the existing block where `exposures_summary` is built (around line 503 — `summary_raw = repo.fetch_exposures_summary(run_id, ticker)`). Insert AFTER that and BEFORE the `return SingleStockReport(...)` constructor call (around line 540):

```python
from uw_scan.cards.dealer_regime import compute_dealer_regime, gather_inputs

# … existing code through `exposures_summary` … (line 503 in v1)

inputs = gather_inputs(repo, ticker=ticker)
dealer_regime_out = compute_dealer_regime(
    ticker=ticker.upper(),
    spot=inputs["spot"],
    net_gex=inputs["net_gex"],
    prev_close_net_gex=inputs["prev_close_net_gex"],
    per_expiry_vanna=inputs["per_expiry_vanna"],
    per_expiry_charm=inputs["per_expiry_charm"],
    strike_gex_curve=inputs["strike_gex_curve"],
    levels=inputs["levels"],
    today=inputs["today"],
)

dealer_regime_model = DealerRegime(
    label=dealer_regime_out.signal.label,
    score=Decimal(str(dealer_regime_out.signal.score)),
    gamma_score=Decimal(str(dealer_regime_out.signal.gamma_score)),
    vanna_score=Decimal(str(dealer_regime_out.signal.vanna_score)),
    charm_score=Decimal(str(dealer_regime_out.signal.charm_score)),
    headline=dealer_regime_out.signal.headline,
    subtitle=dealer_regime_out.signal.subtitle,
    prev_close_net_gex=(
        Decimal(str(inputs["prev_close_net_gex"]))
        if inputs["prev_close_net_gex"] is not None
        else None
    ),
    odte_net_gex=(
        Decimal(str(dealer_regime_out.odte_gex))
        if dealer_regime_out.odte_gex is not None
        else None
    ),
    odte_share_pct=(
        Decimal(str(dealer_regime_out.odte_share_pct))
        if dealer_regime_out.odte_share_pct is not None
        else None
    ),
)
```

Then in the existing `return SingleStockReport(...)` call (line ~540), add a new keyword argument **AT THE END of the kwargs list** (do NOT re-order the existing ones; this preserves Pydantic field validation order):

```python
return SingleStockReport(
    # … existing kwargs unchanged …
    next_earnings_date=next_earnings_date,
    dealer_regime=dealer_regime_model,
)
```

- [ ] **Step 3b: Update `src/uw_scan/models/stock.py` imports + field**

Edit the `.scanner` import block (currently lines 19-25) to add `DealerRegime`:

```python
from .scanner import (
    DealerRegime,
    ExposuresSummaryRow,
    MarketAggregates,
    MarketStructureLevels,
    StrikeExposureRow,
    StrikeGexBucket,
)
```

Add the new field to `SingleStockReport` (after `next_earnings_date`, line ~134):

```python
dealer_regime: DealerRegime | None = None
```

Add `DealerRegime` to the `_preserve_public_module(...)` call at the bottom of `stock.py`.

Finally, in `src/uw_scan/models/__init__.py`, re-export `DealerRegime` from the scanner module and add it to `__all__` (mirrors the existing `MarketStructureLevels` re-export).

- [ ] **Step 4: Add `GET /regime/dealer` endpoint — uses the SAME `gather_inputs` helper**

In `src/uw_scan/api/routers/regime.py`, append:

```python
from datetime import date as _date

from uw_scan.api.schemas import (
    EMPTY_DEALER_REGIME_RESPONSE,
    ClosestLevel,
    DealerRegimeResponse,
    DealerRegimeSignal,
    GammaDecayBucket,
)
from uw_scan.cards.dealer_regime import compute_dealer_regime, gather_inputs


@router.get("/dealer", response_model=DealerRegimeResponse)
def get_dealer_regime(
    repo: Annotated[Repository, Depends(get_repo)],
    ticker: str = Query(..., min_length=1, max_length=10),
) -> DealerRegimeResponse:
    t = ticker.upper()
    inputs = gather_inputs(repo, ticker=t)
    if inputs["run_id"] == 0:
        empty = EMPTY_DEALER_REGIME_RESPONSE.model_copy(deep=True)
        empty.ticker = t
        return empty

    out = compute_dealer_regime(
        ticker=t,
        spot=inputs["spot"],
        net_gex=inputs["net_gex"],
        prev_close_net_gex=inputs["prev_close_net_gex"],
        per_expiry_vanna=inputs["per_expiry_vanna"],
        per_expiry_charm=inputs["per_expiry_charm"],
        strike_gex_curve=inputs["strike_gex_curve"],
        levels=inputs["levels"],
        today=inputs["today"],
    )

    return DealerRegimeResponse(
        status="ok",
        ticker=t,
        scan_time="",  # scan_time lives on the snapshot if we surface it later; not load-bearing here
        spot=out.spot,
        net_gex=out.net_gex,
        prev_close_net_gex=out.prev_close_net_gex,
        signal=DealerRegimeSignal(
            label=out.signal.label,
            score=out.signal.score,
            gamma_score=out.signal.gamma_score,
            vanna_score=out.signal.vanna_score,
            charm_score=out.signal.charm_score,
            headline=out.signal.headline,
            subtitle=out.signal.subtitle,
        ),
        closest_levels=[
            ClosestLevel(
                label=l.label,
                direction=l.direction,
                role=l.role,
                strike=l.strike,
                distance_pct=l.distance_pct,
                gamma=l.gamma,
            )
            for l in out.closest_levels
        ],
        odte_gex=out.odte_gex,
        odte_share_pct=out.odte_share_pct,
        gamma_decay=[
            GammaDecayBucket(
                dte=b.dte,
                expiry=b.expiry,
                net_gex=b.net_gex,
                share_pct=b.share_pct,
            )
            for b in out.gamma_decay
        ],
    )
```

**Graceful degradation notes (added in rev 2):**

- `greek_exposure_daily` is populated only by `scanners/gex.py`, which runs as the SPX/SPY (and other index) GEX scanner every 5 min. For non-index tickers, `_prev_close_net_gex` returns `None` → the magnet bar's "Γ vs prev close" tile shows "—" and the frontend should not crash. This is intentional graceful degradation — surface the gap in UI copy, do not synthesize data.
- `repo.latest_run_id(ticker)` already excludes `gex_scan_*` runs (per `scan_runs.py:15`), so this endpoint always uses the **full-scan** run as the source — same as the report. Avoids the case where a 5-min GEX scan masks the staler full-scan data.

- [ ] **Step 5: Write integration test**

Create `tests/integration/api/test_regime_dealer.py` — REV 2: uses the real
`seeded_db_empty_cards` fixture from `tests/integration/conftest.py`, and
covers BOTH the empty path and a seeded ok path (codex ISSUE-14):

```python
"""Integration tests for GET /api/regime/dealer."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from uw_scan.api.server import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_dealer_regime_empty_for_unseeded_ticker(seeded_db_empty_cards) -> None:  # noqa: ARG001 — fixture seeds the test DB
    r = _client().get("/api/regime/dealer", params={"ticker": "ZZZ"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "empty"
    assert body["ticker"] == "ZZZ"
    assert body["signal"]["label"] == "neutral"


def test_dealer_regime_ok_for_seeded_ticker(seeded_db_with_cards) -> None:
    """End-to-end through gather_inputs → compute_dealer_regime → response."""
    repo = seeded_db_with_cards
    run_id = repo.latest_run_id("TSLA")
    assert run_id > 0

    # Seed strike_gex_curve (one expiry, two strikes) so gamma_decay
    # produces a single non-empty bucket.
    repo.persist_strike_gex_curve(
        run_id=run_id,
        rows=[
            {"strike": Decimal("450"), "expiry": "2026-05-22", "net_gex": Decimal("46550"), "call_gex": Decimal("46550"), "put_gex": Decimal("0")},
            {"strike": Decimal("395"), "expiry": "2026-05-22", "net_gex": Decimal("-12000"), "call_gex": Decimal("0"), "put_gex": Decimal("-12000")},
        ],
    )
    # Seed exposures_summary so vanna/charm scores are non-zero.
    repo.persist_exposures_summary(
        run_id=run_id,
        ticker="TSLA",
        rows=[{"expiry": "2026-05-22", "dte": 4, "net_vanna": Decimal("120000"), "net_charm": Decimal("-25000")}],
    )
    # Seed aggregates so spot + net_gex resolve.
    repo.upsert_aggregates(
        run_id=run_id,
        rows={"spot": Decimal("410"), "net_gex": Decimal("216910")},
    )

    r = _client().get("/api/regime/dealer", params={"ticker": "TSLA"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["ticker"] == "TSLA"
    # Long Γ from positive net_gex → expect either "dampening" or "neutral"
    # depending on Vanna/Charm contribution; assert the sign of the gamma score.
    assert body["signal"]["gamma_score"] > 0
    # closest_levels carries both ranking modes
    rank_kinds = {l["rank_kind"] for l in body["closest_levels"]}
    assert "nearest" in rank_kinds
    # gamma_decay has the seeded expiry bucket
    assert any(b["expiry"] == "2026-05-22" for b in body["gamma_decay"])
```

**Note**: `repo.persist_strike_gex_curve`, `repo.persist_exposures_summary`,
`repo.upsert_aggregates` are placeholder names — use the actual write methods
the corresponding workers use (`tests/integration/test_gex_scanner.py` and
`tests/integration/worker/test_cockpit_snapshot_persists_exposures_summary.py`
demonstrate the production write paths). The implementer should grep those
tests, copy the write pattern, and adapt the column types. The intent of this
ok-path test is to exercise `gather_inputs → compute_dealer_regime → JSON
response` end-to-end against a real DB.

- [ ] **Step 6: Run pytest**

Run:
```bash
uv run pytest tests/unit/cards/test_dealer_regime.py tests/integration/api/test_regime_dealer.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/uw_scan/api/routers/regime.py src/uw_scan/reports/single_stock.py src/uw_scan/models/scanner.py src/uw_scan/models/__init__.py tests/integration/api/test_regime_dealer.py
git commit -m "feat(regime): expose per-ticker dealer regime via /regime/dealer + report"
```

---

### Task 4: Frontend — regenerate types, add API helpers

**Files:**
- Generate: `web/lib/types.ts`
- Modify: `web/lib/api.ts`

- [ ] **Step 1: Regenerate types**

Run:
```bash
cd web && npm run gen:types
```
Expected: `web/lib/types.ts` updated; diff shows `DealerRegimeResponse`, `GammaDecayBucket`, `ClosestLevel`, `DealerRegimeSignal`, `DealerRegime`.

- [ ] **Step 2: Add API helpers**

Edit `web/lib/api.ts`. Near the other type aliases:

```typescript
type RegimeGexResponse = Json<"/api/regime/gex", "get">;
type RegimeDealerResponse = Json<"/api/regime/dealer", "get">;
type RegimeVcgResponse = Json<"/api/regime/vcg", "get">;
```

Near the other `api.*` methods (alphabetical with the existing ones), add:

```typescript
regimeGex: (ticker: string): Promise<RegimeGexResponse> =>
  _fetch<RegimeGexResponse>(`/api/regime/gex?ticker=${encodeURIComponent(ticker)}`),
regimeDealer: (ticker: string): Promise<RegimeDealerResponse> =>
  _fetch<RegimeDealerResponse>(`/api/regime/dealer?ticker=${encodeURIComponent(ticker)}`),
regimeVcg: (): Promise<RegimeVcgResponse> => _fetch<RegimeVcgResponse>(`/api/regime/vcg`),
```

Export the response types:

```typescript
export type {
  // existing exports …
  RegimeGexResponse,
  RegimeDealerResponse,
  RegimeVcgResponse,
};
```

- [ ] **Step 3: Typecheck**

Run:
```bash
cd web && npm run typecheck
```
Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add web/lib/types.ts web/lib/api.ts
git commit -m "feat(web): regenerate types; add regimeGex/regimeDealer/regimeVcg api helpers"
```

---

### Task 5: Frontend — MagnetGammaBar component

**Files:**
- Create: `web/components/stock/panels/MagnetGammaBar.tsx`
- Test: `web/tests/components/MagnetGammaBar.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/tests/components/MagnetGammaBar.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MagnetGammaBar } from "@/components/stock/panels/MagnetGammaBar";

const baseReport = {
  ticker: "TSLA",
  market_structure: { spot: 410, net_gex: 216910 },
  market_structure_levels: {
    call_wall: { strike: 450, net_gex: 46550 },
    put_wall: { strike: 395, net_gex: -966840 },
    gex_flip: { strike: 474.64, net_gex: 0 },
  },
  dealer_regime: {
    label: "dampening",
    headline: "Long Γ → Dampening regime",
    subtitle:
      "Largest level is the call wall (resistance) at $450.00 — dealers may sell into rallies as price approaches it.",
    prev_close_net_gex: 440500,
    odte_net_gex: -20133,
  },
} as any;

describe("MagnetGammaBar", () => {
  it("renders the regime headline and subtitle", () => {
    render(<MagnetGammaBar report={baseReport} />);
    expect(screen.getByText(/Long Γ → Dampening regime/i)).toBeInTheDocument();
    expect(screen.getByText(/Largest level is the call wall/i)).toBeInTheDocument();
  });

  it("shows the five metrics", () => {
    render(<MagnetGammaBar report={baseReport} />);
    expect(screen.getByText(/Net dealer/i)).toBeInTheDocument();
    expect(screen.getByText(/vs prev close/i)).toBeInTheDocument();
    expect(screen.getByText(/Top wall/i)).toBeInTheDocument();
    expect(screen.getByText(/Flip distance/i)).toBeInTheDocument();
    expect(screen.getByText(/0–1d rolls off/i)).toBeInTheDocument();
  });

  it("formats flip distance from spot", () => {
    render(<MagnetGammaBar report={baseReport} />);
    // Flip 474.64 vs spot 410 → +15.8%
    expect(screen.getByText(/\+15\.8%/)).toBeInTheDocument();
  });

  it("renders nothing when dealer_regime missing", () => {
    const empty = { ...baseReport, dealer_regime: null };
    const { container } = render(<MagnetGammaBar report={empty} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd web && npm run test -- MagnetGammaBar
```
Expected: FAIL — component not found.

- [ ] **Step 3: Implement the component**

Create `web/components/stock/panels/MagnetGammaBar.tsx`:

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
  display: "flex",
  flexDirection: "column",
  gap: 10,
};

const labelStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

const headlineStyle: React.CSSProperties = {
  fontSize: 16,
  fontWeight: 700,
  color: "var(--text-primary)",
};

const subtitleStyle: React.CSSProperties = {
  fontSize: 11,
  color: "var(--text-secondary)",
  fontStyle: "italic",
};

const tilesRowStyle: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(5, 1fr)",
  gap: 12,
  borderTop: "1px solid var(--border-dim)",
  paddingTop: 10,
};

const tileLabel: React.CSSProperties = {
  ...labelStyle,
  fontSize: 9,
};

const tileValue: React.CSSProperties = {
  fontSize: 14,
  fontWeight: 600,
  marginTop: 2,
};

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(2)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function deltaColor(v: number | null | undefined): string {
  if (v == null) return "var(--text-muted)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

function regimeColor(label: string | null | undefined): string {
  if (label === "dampening") return "var(--positive)";
  if (label === "amplifying") return "var(--negative)";
  return "var(--warning)";
}

export function MagnetGammaBar({ report }: { report: Report }) {
  const regime = report.dealer_regime;
  if (!regime) return null;

  const spot = toNum(report.market_structure?.spot);
  const netGex = toNum(report.market_structure?.net_gex);
  const prevClose = toNum(regime.prev_close_net_gex);
  const odte = toNum(regime.odte_net_gex);

  const lv = report.market_structure_levels;
  const callWall = lv?.call_wall ? toNum(lv.call_wall.strike) : null;
  const callWallGex = lv?.call_wall ? toNum(lv.call_wall.net_gex) : null;
  const putWall = lv?.put_wall ? toNum(lv.put_wall.strike) : null;
  const putWallGex = lv?.put_wall ? toNum(lv.put_wall.net_gex) : null;
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;

  // Pick the wall with larger |gex| to label as "top wall".
  const useCallTop =
    (callWallGex != null ? Math.abs(callWallGex) : 0) >=
    (putWallGex != null ? Math.abs(putWallGex) : 0);
  const topWallStrike = useCallTop ? callWall : putWall;
  const topWallGex = useCallTop ? callWallGex : putWallGex;

  const deltaVsPrev =
    netGex != null && prevClose != null ? netGex - prevClose : null;
  const deltaPct =
    netGex != null && prevClose != null && prevClose !== 0
      ? deltaVsPrev! / Math.abs(prevClose)
      : null;
  const flipDistPct =
    flip != null && spot != null && spot > 0 ? (flip - spot) / spot : null;

  return (
    <div style={panelStyle}>
      <div style={labelStyle}>
        <span style={{ color: "var(--accent-warm)" }}>MAGNET</span>{" "}
        <span style={{ color: "var(--text-muted)" }}>· GAMMA</span>
      </div>
      <div style={{ ...headlineStyle, color: regimeColor(regime.label) }}>
        {regime.headline}
      </div>
      {regime.subtitle && <div style={subtitleStyle}>{regime.subtitle}</div>}

      <div style={tilesRowStyle}>
        {/* Net dealer Γ */}
        <div>
          <div style={tileLabel}>Net dealer Γ</div>
          <div style={{ ...tileValue, color: deltaColor(netGex) }}>
            {fmtMoney(netGex)}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              {netGex != null && netGex >= 0 ? "Long" : "Short"}
            </span>
          </div>
        </div>

        {/* Γ vs prev close */}
        <div>
          <div style={tileLabel}>Γ vs prev close</div>
          <div style={{ ...tileValue, color: deltaColor(deltaVsPrev) }}>
            {fmtMoney(deltaVsPrev)}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              {fmtPct(deltaPct, 0)}
            </span>
          </div>
        </div>

        {/* Top wall */}
        <div>
          <div style={tileLabel}>Top wall</div>
          <div style={tileValue}>
            ${topWallStrike?.toFixed(2) ?? "—"}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              {fmtMoney(topWallGex)}
            </span>
          </div>
        </div>

        {/* Flip distance */}
        <div>
          <div style={tileLabel}>Flip distance</div>
          <div
            style={{ ...tileValue, color: deltaColor(flipDistPct) }}
          >
            {fmtPct(flipDistPct, 1)}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              at ${flip?.toFixed(2) ?? "—"}
            </span>
          </div>
        </div>

        {/* 0–1d rolls off */}
        <div>
          <div style={tileLabel}>0–1d rolls off</div>
          <div style={{ ...tileValue, color: deltaColor(odte) }}>
            {fmtMoney(odte)}{" "}
            <span style={{ color: "var(--text-muted)", fontSize: 11 }}>
              by tomorrow
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd web && npm run test -- MagnetGammaBar
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/panels/MagnetGammaBar.tsx web/tests/components/MagnetGammaBar.test.tsx
git commit -m "feat(web): MagnetGammaBar — regime headline + 5-tile dealer Γ summary"
```

---

### Task 6: Frontend — colored reference rows on GexProfileChart

**Files:**
- Modify: `web/components/stock/panels/GexProfileChart.tsx`

- [ ] **Step 1: Extend GexProfileChart with colored level rows**

Edit `GexProfileChart.tsx`:

1. Read the gamma-flip strike from `report.market_structure_levels.gex_flip` (already in the type).
2. Inside the per-row block (around line 124), add `isFlip` detection. The flip is unlikely to land *on* a strike — so render it as a synthetic absolutely-positioned line overlaying the bar canvas, not as a row. Add the same for spot when spot doesn't land on a strike row.
3. Color tokens (match the screenshot):
   - Call Wall: `var(--positive)` (green) — already used
   - Put Wall: `var(--negative)` (red) — already used
   - Spot: `var(--accent-vol)` (cyan)
   - Gamma Flip: `var(--accent-vivid)` (purple)
4. The simplest implementation: after the `strikes.map` block, append an absolute-positioned overlay `<div>` parented to the same flex container. For each non-on-strike level (flip, sometimes spot), draw a 1px dashed line at the row position interpolated by strike value.

Replace the entire `GexProfileChart` function with:

```tsx
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

const MIN_ABS_GEX = 100;
const WINDOW_PCT = 0.15;

const panelStyle: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 20,
  fontFamily: "var(--font-mono)",
};

const headingStyle: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
};

function fmtPct(v: number, digits = 2): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtMoney(v: number): string {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e6)
    return `${sign}$${(abs / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1e3)
    return `${sign}$${(abs / 1e3).toLocaleString("en-US", { maximumFractionDigits: 1 })}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

export function GexProfileChart({ report }: { report: Report }) {
  const curve = report.strike_gex_curve;
  const spot = toNum(report.market_structure.spot);
  const lv = report.market_structure_levels;
  const callWall = lv?.call_wall ? toNum(lv.call_wall.strike) : null;
  const putWall = lv?.put_wall ? toNum(lv.put_wall.strike) : null;
  const flip = lv?.gex_flip ? toNum(lv.gex_flip.strike) : null;

  const perStrike = new Map<number, number>();
  for (const b of curve) {
    const s = toNum(b.strike);
    const g = toNum(b.net_gex);
    if (s == null || g == null) continue;
    perStrike.set(s, (perStrike.get(s) ?? 0) + g);
  }

  const center = spot ?? 0;
  const winLo = center * (1 - WINDOW_PCT);
  const winHi = center * (1 + WINDOW_PCT);
  let closestToSpot: number | null = null;
  if (spot != null) {
    let bestDist = Infinity;
    for (const s of perStrike.keys()) {
      if (s < winLo || s > winHi) continue;
      const d = Math.abs(s - spot);
      if (d < bestDist) {
        bestDist = d;
        closestToSpot = s;
      }
    }
  }

  const strikes = Array.from(perStrike.entries())
    .filter(([s, g]) => {
      if (s < winLo || s > winHi) return false;
      const isWall = s === callWall || s === putWall;
      const isSpotAnchor = s === closestToSpot;
      return isWall || isSpotAnchor || Math.abs(g) >= MIN_ABS_GEX;
    })
    .sort((a, b) => b[0] - a[0]);

  const maxAbs = Math.max(...strikes.map(([, g]) => Math.abs(g)), 1);
  const ROW_H = 22;
  const LABEL_W = 110;
  const BAR_W = 280;
  const VALUE_W = 90;
  const TAG_W = 130;
  const ROW_W = LABEL_W + BAR_W + VALUE_W + TAG_W;

  // Map any continuous strike value to a vertical pixel offset within the
  // rendered strike list. We interpolate between adjacent strike rows when
  // the level falls between two strikes. Returns null if the level is
  // outside the rendered window.
  function strikeToY(level: number): number | null {
    if (strikes.length === 0) return null;
    const hi = strikes[0][0]; // top of the chart (highest strike)
    const lo = strikes[strikes.length - 1][0];
    if (level > hi + (hi - lo) * 0.05) return null;
    if (level < lo - (hi - lo) * 0.05) return null;
    // Find the pair of adjacent strikes the level sits between.
    for (let i = 0; i < strikes.length - 1; i++) {
      const a = strikes[i][0];
      const b = strikes[i + 1][0];
      if (level <= a && level >= b) {
        const t = (a - level) / (a - b);
        return (i + t) * ROW_H + ROW_H / 2;
      }
    }
    // Outside the inner pairs but inside the safety band → clamp.
    return level >= hi ? ROW_H / 2 : (strikes.length - 1) * ROW_H + ROW_H / 2;
  }

  type Overlay = {
    label: string;
    color: string;
    y: number;
    strike: number;
  };
  const overlays: Overlay[] = [];
  if (spot != null) {
    const y = strikeToY(spot);
    if (y != null)
      overlays.push({
        label: `Spot $${spot.toFixed(2)}`,
        color: "var(--accent-vol)",
        y,
        strike: spot,
      });
  }
  if (flip != null) {
    const y = strikeToY(flip);
    if (y != null)
      overlays.push({
        label: `Gamma flip $${flip.toFixed(2)}`,
        color: "var(--accent-vivid)",
        y,
        strike: flip,
      });
  }
  if (callWall != null) {
    const y = strikeToY(callWall);
    if (y != null)
      overlays.push({
        label: `Call Wall $${callWall.toFixed(2)}`,
        color: "var(--positive)",
        y,
        strike: callWall,
      });
  }
  if (putWall != null) {
    const y = strikeToY(putWall);
    if (y != null)
      overlays.push({
        label: `Put Wall $${putWall.toFixed(2)}`,
        color: "var(--negative)",
        y,
        strike: putWall,
      });
  }

  return (
    <div style={panelStyle}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 16,
        }}
      >
        <div style={headingStyle}>GEX Profile — Net gamma by strike</div>
        <div style={{ display: "flex", gap: 16, fontSize: 11 }}>
          <span style={{ color: "var(--positive)" }}>■ Positive (stabilizing)</span>
          <span style={{ color: "var(--negative)" }}>■ Negative (destabilizing)</span>
        </div>
      </div>

      <div
        style={{
          maxWidth: ROW_W,
          margin: "0 auto",
          position: "relative",
        }}
      >
        {strikes.map(([strike, gex]) => {
          const pct = spot != null ? (strike - spot) / spot : 0;
          const widthPct = (Math.abs(gex) / maxAbs) * 50;
          const isPos = gex >= 0;
          const isCallWall = callWall != null && strike === callWall;
          const isPutWall = putWall != null && strike === putWall;
          const isSpotRow = closestToSpot != null && strike === closestToSpot;

          const strikeColor = isCallWall
            ? "var(--positive)"
            : isPutWall
              ? "var(--negative)"
              : isSpotRow
                ? "var(--accent-vol)"
                : "var(--text-primary)";
          const strikeBold = isCallWall || isPutWall || isSpotRow;

          return (
            <div
              key={strike}
              style={{
                display: "grid",
                gridTemplateColumns: `${LABEL_W}px ${BAR_W}px ${VALUE_W}px ${TAG_W}px`,
                alignItems: "center",
                height: ROW_H,
                fontSize: 11,
              }}
            >
              <div
                style={{
                  textAlign: "right",
                  paddingRight: 12,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                }}
              >
                <span style={{ color: "var(--text-muted)" }}>{fmtPct(pct, 2)}</span>{" "}
                <span style={{ color: strikeColor, fontWeight: strikeBold ? 700 : 400 }}>
                  {strike}
                </span>
              </div>

              <div style={{ position: "relative", height: ROW_H }}>
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    top: 0,
                    bottom: 0,
                    width: 1,
                    background: "var(--border-dim)",
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    top: 3,
                    bottom: 3,
                    left: isPos ? "50%" : `${50 - widthPct}%`,
                    width: `${widthPct}%`,
                    background: isPos ? "var(--positive)" : "var(--negative)",
                    opacity: 0.85,
                  }}
                />
              </div>

              <div
                style={{
                  paddingLeft: 12,
                  color: isPos ? "var(--positive)" : "var(--negative)",
                  whiteSpace: "nowrap",
                  textAlign: "left",
                }}
              >
                {fmtMoney(gex)}
              </div>

              <div />
            </div>
          );
        })}

        {/* Overlay reference lines */}
        <div
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            pointerEvents: "none",
          }}
        >
          {overlays.map((o) => (
            <div
              key={`${o.label}-${o.strike}`}
              style={{
                position: "absolute",
                left: LABEL_W,
                right: 0,
                top: o.y,
                height: 0,
                borderTop: `1px dashed ${o.color}`,
                display: "flex",
                justifyContent: "flex-end",
                alignItems: "flex-start",
              }}
            >
              <span
                style={{
                  background: "var(--bg-panel)",
                  color: o.color,
                  fontSize: 9,
                  letterSpacing: 1,
                  textTransform: "uppercase",
                  padding: "1px 4px",
                  marginTop: -7,
                  marginRight: 2,
                  whiteSpace: "nowrap",
                }}
              >
                {o.label}
              </span>
            </div>
          ))}
        </div>

        {strikes.length === 0 && (
          <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
            No strike-gamma data in the ±{(WINDOW_PCT * 100).toFixed(0)}% window around spot.
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual visual check via dev server**

Run:
```bash
bash scripts/dev.sh   # if not running
```
Open `http://localhost:3001/stock/TSLA` → Market Structure → GEX tab. Verify four colored dashed lines (cyan/purple/green/red) appear with labels Spot / Gamma flip / Call Wall / Put Wall.

- [ ] **Step 3: Lint + typecheck**

```bash
cd web && npm run typecheck && npm run lint
```
Expected: zero errors.

- [ ] **Step 4: Commit**

```bash
git add web/components/stock/panels/GexProfileChart.tsx
git commit -m "feat(web): colored reference lines (flip/walls/spot) on GEX profile"
```

---

### Task 7: Frontend — GexHistoryChart (daily 90d bar+line)

**Files:**
- Create: `web/components/stock/panels/GexHistoryChart.tsx`

- [ ] **Step 1: Implement the chart**

Create `web/components/stock/panels/GexHistoryChart.tsx`:

```tsx
"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { RegimeGexResponse } from "@/lib/api";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
};

const HEADING: React.CSSProperties = {
  fontSize: 12,
  color: "var(--text-secondary)",
  marginBottom: 8,
};

type Bar = { date: string; net_gex: number | null; spot: number | null };

function buildBars(resp: RegimeGexResponse | null): Bar[] {
  const hist = resp?.history ?? [];
  return hist.map((h) => ({
    date: h.date,
    net_gex: h.net_gex ?? null,
    spot: h.spot ?? null,
  }));
}

export function GexHistoryChart({ ticker }: { ticker: string }) {
  const [data, setData] = useState<RegimeGexResponse | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .regimeGex(ticker)
      .then((r) => {
        if (!cancelled) {
          setData(r);
          setErr(null);
        }
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  const bars = useMemo(() => buildBars(data), [data]);

  if (loading) {
    return (
      <div style={PANEL}>
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>Loading…</div>
      </div>
    );
  }

  if (err || bars.length === 0) {
    return (
      <div style={PANEL}>
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No GEX history yet.
        </div>
      </div>
    );
  }

  const W = 760;
  const H = 280;
  const PAD = { top: 20, right: 50, bottom: 24, left: 56 };
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;

  const gexValues = bars
    .map((b) => b.net_gex)
    .filter((v): v is number => v != null);
  const spotValues = bars
    .map((b) => b.spot)
    .filter((v): v is number => v != null);

  if (gexValues.length === 0 || spotValues.length === 0) {
    return (
      <div style={PANEL}>
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          Thin GEX/spot history for {ticker}.
        </div>
      </div>
    );
  }

  const gexMax = Math.max(...gexValues.map(Math.abs), 1);
  const yGex = (v: number) =>
    PAD.top + innerH / 2 - (v / gexMax) * (innerH / 2 - 4);

  const spotMin = Math.min(...spotValues);
  const spotMax = Math.max(...spotValues);
  const spotRange = spotMax - spotMin || 1;
  const ySpot = (v: number) =>
    PAD.top + innerH - ((v - spotMin) / spotRange) * innerH;

  const barW = innerW / bars.length;

  return (
    <div style={PANEL}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
        <div style={{ display: "flex", gap: 12, fontSize: 10 }}>
          <span style={{ color: "var(--accent-warm)" }}>— Price</span>
          <span style={{ color: "var(--accent-vivid)" }}>■ Net Gamma</span>
        </div>
      </div>
      <svg width={W} height={H} role="img" aria-label="Daily GEX history">
        <title>Daily GEX history — net gamma bars with price overlay</title>
        {/* Zero line for GEX */}
        <line
          x1={PAD.left}
          x2={W - PAD.right}
          y1={PAD.top + innerH / 2}
          y2={PAD.top + innerH / 2}
          stroke="var(--border-dim)"
          strokeWidth={1}
        />
        {/* GEX bars */}
        {bars.map((b, i) => {
          if (b.net_gex == null) return null;
          const x = PAD.left + i * barW + 1;
          const y0 = PAD.top + innerH / 2;
          const y = yGex(b.net_gex);
          return (
            <rect
              key={b.date}
              x={x}
              y={Math.min(y, y0)}
              width={Math.max(barW - 2, 1)}
              height={Math.abs(y - y0)}
              fill="var(--accent-vivid)"
              opacity={0.7}
            />
          );
        })}
        {/* Spot line */}
        <polyline
          fill="none"
          stroke="var(--accent-warm)"
          strokeWidth={1.5}
          points={bars
            .map((b, i) =>
              b.spot == null
                ? null
                : `${PAD.left + i * barW + barW / 2},${ySpot(b.spot)}`,
            )
            .filter(Boolean)
            .join(" ")}
        />
        {/* Y-axis labels (GEX left, Spot right) */}
        <text x={PAD.left - 8} y={PAD.top + 8} textAnchor="end" fontSize={9} fill="var(--text-muted)">
          {fmtTick(gexMax)}
        </text>
        <text
          x={PAD.left - 8}
          y={PAD.top + innerH - 4}
          textAnchor="end"
          fontSize={9}
          fill="var(--text-muted)"
        >
          {fmtTick(-gexMax)}
        </text>
        <text
          x={W - PAD.right + 8}
          y={PAD.top + 8}
          fontSize={9}
          fill="var(--text-muted)"
        >
          {spotMax.toFixed(0)}
        </text>
        <text
          x={W - PAD.right + 8}
          y={PAD.top + innerH - 4}
          fontSize={9}
          fill="var(--text-muted)"
        >
          {spotMin.toFixed(0)}
        </text>
      </svg>
    </div>
  );
}

function fmtTick(v: number): string {
  const abs = Math.abs(v);
  const sign = v >= 0 ? "" : "-";
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(0)}K`;
  return `${sign}${abs.toFixed(0)}`;
}
```

- [ ] **Step 2: Typecheck**

```bash
cd web && npm run typecheck
```
Expected: zero errors.

- [ ] **Step 3: Commit**

```bash
git add web/components/stock/panels/GexHistoryChart.tsx
git commit -m "feat(web): GexHistoryChart — 90d historical net gamma + spot overlay"
```

---

### Task 8: Frontend — wire MagnetGammaBar + GexHistoryChart into GreekSubTabs

**Files:**
- Modify: `web/components/stock/panels/greeks/GreekSubTabs.tsx`

- [ ] **Step 1: Add components above and below GEX tab body**

Replace the `tab === "GEX"` block:

```tsx
{tab === "GEX" && (
  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <MagnetGammaBar report={report} />
    <GexProfileChart report={report} />
    <GexHistoryChart ticker={report.ticker} />
  </div>
)}
```

Add the imports at the top:

```tsx
import { MagnetGammaBar } from "@/components/stock/panels/MagnetGammaBar";
import { GexHistoryChart } from "@/components/stock/panels/GexHistoryChart";
```

- [ ] **Step 2: Verify in browser**

Run dev server, open `/stock/TSLA` → Market Structure → GEX tab. Verify magnet bar above, profile chart in middle with colored lines, history chart below.

- [ ] **Step 3: Commit**

```bash
git add web/components/stock/panels/greeks/GreekSubTabs.tsx
git commit -m "feat(web): integrate MagnetGammaBar + GexHistoryChart into GEX sub-tab"
```

---

### Task 9: Frontend — VolatilityRegimePanel + MacroVcgTile

**Files:**
- Create: `web/components/stock/panels/VolatilityRegimePanel.tsx`
- Create: `web/components/stock/panels/MacroVcgTile.tsx`
- Test: `web/tests/components/VolatilityRegimePanel.test.tsx`

- [ ] **Step 1: Write failing test for VolatilityRegimePanel**

Create `web/tests/components/VolatilityRegimePanel.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VolatilityRegimePanel } from "@/components/stock/panels/VolatilityRegimePanel";

const fixture = {
  status: "ok",
  ticker: "TSLA",
  spot: 410,
  net_gex: 216910,
  signal: {
    label: "dampening",
    score: 0.62,
    gamma_score: 0.7,
    vanna_score: 0.18,
    charm_score: -0.12,
    headline: "Long Γ → Dampening regime",
    subtitle: "Largest level …",
  },
  closest_levels: [
    {
      label: "Accel ↑",
      direction: "up",
      role: "accelerator",
      strike: 410,
      distance_pct: 0,
      gamma: 19210,
    },
    {
      label: "Put Wall",
      direction: "down",
      role: "support",
      strike: 395,
      distance_pct: -0.037,
      gamma: -966840,
    },
    {
      label: "Call Wall",
      direction: "up",
      role: "resistance",
      strike: 450,
      distance_pct: 0.098,
      gamma: 46550,
    },
  ],
  odte_gex: -20132.93,
  odte_share_pct: 0.07,
  gamma_decay: [
    { dte: 0, expiry: "2026-05-18", net_gex: -20133, share_pct: 0.21 },
    { dte: 2, expiry: "2026-05-20", net_gex: -8511, share_pct: 0.09 },
    { dte: 4, expiry: "2026-05-22", net_gex: 41550, share_pct: 0.43 },
    { dte: 8, expiry: "2026-05-26", net_gex: 5031, share_pct: 0.05 },
  ],
} as any;

describe("VolatilityRegimePanel", () => {
  it("shows Dampening label and Γ/V/C values", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    expect(screen.getByText(/Dampening/i)).toBeInTheDocument();
    expect(screen.getByText(/\+0\.70/)).toBeInTheDocument();
    expect(screen.getByText(/\+0\.18/)).toBeInTheDocument();
    expect(screen.getByText(/-0\.12/)).toBeInTheDocument();
  });

  it("lists closest levels sorted by proximity", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    const rows = screen.getAllByTestId("closest-level-row");
    expect(rows[0]).toHaveTextContent(/Accel/);
    expect(rows[1]).toHaveTextContent(/Put Wall/);
    expect(rows[2]).toHaveTextContent(/Call Wall/);
  });

  it("renders 0DTE GEX and chain share", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    expect(screen.getByText(/0DTE GEX/i)).toBeInTheDocument();
    expect(screen.getByText(/7% of chain/i)).toBeInTheDocument();
  });

  it("renders gamma decay rows", () => {
    render(<VolatilityRegimePanel data={fixture} />);
    expect(screen.getAllByTestId("decay-row")).toHaveLength(4);
  });
});
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd web && npm run test -- VolatilityRegimePanel
```
Expected: FAIL — component not found.

- [ ] **Step 3: Implement VolatilityRegimePanel**

Create `web/components/stock/panels/VolatilityRegimePanel.tsx`:

```tsx
"use client";

import type { RegimeDealerResponse } from "@/lib/api";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 16,
  fontFamily: "var(--font-mono)",
  display: "flex",
  flexDirection: "column",
  gap: 12,
  width: "100%",
  maxWidth: 360,
};

const SECTION_LABEL: React.CSSProperties = {
  fontSize: 9,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

function regimeColor(label: string | null | undefined): string {
  if (label === "dampening") return "var(--positive)";
  if (label === "amplifying") return "var(--negative)";
  return "var(--warning)";
}

function fmtScore(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
}

function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;
}

function fmtMoney(v: number | null | undefined): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(2)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function SubBar({
  label,
  score,
}: {
  label: string;
  score: number | null | undefined;
}) {
  const v = score ?? 0;
  const color = v >= 0 ? "var(--positive)" : "var(--negative)";
  const widthPct = Math.min(Math.abs(v) * 100, 100);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <span style={{ width: 14, fontWeight: 700 }}>{label}</span>
      <div style={{ position: "relative", flex: 1, height: 6 }}>
        <div
          style={{
            position: "absolute",
            left: "50%",
            top: 0,
            bottom: 0,
            width: 1,
            background: "var(--border-dim)",
          }}
        />
        <div
          style={{
            position: "absolute",
            top: 1,
            bottom: 1,
            left: v >= 0 ? "50%" : `${50 - widthPct / 2}%`,
            width: `${widthPct / 2}%`,
            background: color,
          }}
        />
      </div>
      <span style={{ width: 50, textAlign: "right", color, fontSize: 11 }}>
        {fmtScore(v)}
      </span>
    </div>
  );
}

export function VolatilityRegimePanel({
  data,
}: {
  data: RegimeDealerResponse | null;
}) {
  if (!data || data.status !== "ok") {
    return (
      <div style={PANEL}>
        <div style={SECTION_LABEL}>Volatility Regime</div>
        <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
          No dealer regime data yet.
        </div>
      </div>
    );
  }

  const { signal, closest_levels = [], odte_gex, odte_share_pct, gamma_decay = [] } = data;
  const labelColor = regimeColor(signal.label);

  const sliderScore = signal.score ?? 0;
  // map score in [-1, 1] → [0, 100%]
  const sliderPct = ((sliderScore + 1) / 2) * 100;

  const decayMaxAbs = Math.max(...gamma_decay.map((b) => Math.abs(b.net_gex ?? 0)), 1);

  return (
    <div style={PANEL}>
      {/* Regime header */}
      <div>
        <div style={SECTION_LABEL}>Volatility Regime</div>
        <div
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: labelColor,
            textTransform: "capitalize",
          }}
        >
          {signal.label}
        </div>
        {signal.subtitle && (
          <div style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 4 }}>
            {signal.subtitle}
          </div>
        )}
      </div>

      {/* Slider */}
      <div>
        <div
          style={{
            position: "relative",
            height: 8,
            background:
              "linear-gradient(90deg, var(--negative) 0%, var(--warning) 50%, var(--positive) 100%)",
            borderRadius: 4,
          }}
        >
          <div
            style={{
              position: "absolute",
              left: `${sliderPct}%`,
              top: -2,
              bottom: -2,
              width: 2,
              background: "var(--text-primary)",
            }}
          />
        </div>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: 10,
            color: "var(--text-muted)",
            marginTop: 4,
          }}
        >
          <span>Amplifying</span>
          <span>Dampening</span>
        </div>
      </div>

      {/* Γ/V/C sub-bars */}
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <SubBar label="Γ" score={signal.gamma_score} />
        <SubBar label="V" score={signal.vanna_score} />
        <SubBar label="C" score={signal.charm_score} />
      </div>

      {/* Closest levels */}
      <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <div style={SECTION_LABEL}>Closest Levels</div>
          <div style={{ ...SECTION_LABEL, fontStyle: "italic" }}>by proximity</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 6 }}>
          {closest_levels.map((l) => {
            const directionGlyph =
              l.direction === "up" ? "↑" : l.direction === "down" ? "↓" : "·";
            const color =
              l.role === "support"
                ? "var(--positive)"
                : l.role === "resistance"
                  ? "var(--warning)"
                  : l.role === "accelerator"
                    ? "var(--negative)"
                    : "var(--text-primary)";
            return (
              <div
                key={`${l.label}-${l.strike}`}
                data-testid="closest-level-row"
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 2,
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <span style={{ color, fontWeight: 700 }}>
                    {l.label} {directionGlyph} @ ${l.strike.toFixed(2)}
                  </span>
                  <span style={{ color, fontSize: 10, letterSpacing: 1 }}>
                    {l.role?.toUpperCase()}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
                  {fmtPct(l.distance_pct, 1)} from spot · {fmtMoney(l.gamma)} gamma
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* 0DTE GEX */}
      <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 10 }}>
        <div style={{ display: "flex", justifyContent: "space-between" }}>
          <div style={SECTION_LABEL}>0DTE GEX</div>
          <div style={SECTION_LABEL}>expires today</div>
        </div>
        <div
          style={{
            fontSize: 18,
            fontWeight: 700,
            color: (odte_gex ?? 0) >= 0 ? "var(--positive)" : "var(--negative)",
            marginTop: 4,
          }}
        >
          {fmtMoney(odte_gex)}{" "}
          <span style={{ color: "var(--text-muted)", fontSize: 10 }}>
            {odte_share_pct != null ? `${Math.round(odte_share_pct * 100)}% of chain` : ""}
          </span>
        </div>
      </div>

      {/* Gamma decay */}
      <div style={{ borderTop: "1px solid var(--border-dim)", paddingTop: 10 }}>
        <div style={SECTION_LABEL}>Gamma Decay Over Time</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
          {gamma_decay.map((b) => {
            const widthPct = (Math.abs(b.net_gex ?? 0) / decayMaxAbs) * 100;
            const color = (b.net_gex ?? 0) >= 0 ? "var(--positive)" : "var(--negative)";
            return (
              <div
                key={b.expiry}
                data-testid="decay-row"
                style={{
                  display: "grid",
                  gridTemplateColumns: "40px 90px 1fr 90px",
                  alignItems: "center",
                  fontSize: 11,
                  gap: 8,
                }}
              >
                <span style={{ color, fontWeight: 700 }}>{b.dte}d</span>
                <span style={{ color: "var(--text-muted)" }}>{b.expiry}</span>
                <div
                  style={{
                    position: "relative",
                    height: 4,
                    background: "var(--bg-panel)",
                    border: "1px solid var(--border-dim)",
                    borderRadius: 2,
                  }}
                >
                  <div
                    style={{
                      position: "absolute",
                      left: 0,
                      top: 0,
                      bottom: 0,
                      width: `${widthPct}%`,
                      background: color,
                    }}
                  />
                </div>
                <span style={{ textAlign: "right", color }}>{fmtMoney(b.net_gex)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement MacroVcgTile**

Create `web/components/stock/panels/MacroVcgTile.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RegimeVcgResponse } from "@/lib/api";

const PANEL: React.CSSProperties = {
  background: "var(--bg-panel)",
  border: "1px solid var(--border-dim)",
  borderRadius: 4,
  padding: 12,
  fontFamily: "var(--font-mono)",
  display: "flex",
  flexDirection: "column",
  gap: 6,
};

export function MacroVcgTile() {
  const [data, setData] = useState<RegimeVcgResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .regimeVcg()
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const interp = data?.signal?.interpretation ?? null;
  const z = data?.signal?.vcg ?? null;

  const color =
    interp === "credit_stress_lagging_vol"
      ? "var(--warning)"
      : interp === "vol_stress_lagging_credit"
        ? "var(--negative)"
        : interp === "aligned"
          ? "var(--positive)"
          : "var(--text-muted)";

  return (
    <div style={PANEL}>
      <div
        style={{
          fontSize: 9,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        Macro VCG
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, color }}>
        {interp ?? "—"}
      </div>
      <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
        z = {z != null ? z.toFixed(2) : "—"}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run tests**

```bash
cd web && npm run test -- VolatilityRegimePanel && npm run typecheck
```
Expected: all PASS, zero TS errors.

- [ ] **Step 6: Commit**

```bash
git add web/components/stock/panels/VolatilityRegimePanel.tsx web/components/stock/panels/MacroVcgTile.tsx web/tests/components/VolatilityRegimePanel.test.tsx
git commit -m "feat(web): VolatilityRegimePanel + MacroVcgTile for Volatility tab"
```

---

### Task 10: Frontend — wire VolatilityRegimePanel into VolatilityTabClient

**Files:**
- Modify: `web/components/stock/tabs/VolatilityTabClient.tsx`

- [ ] **Step 1: Fetch /regime/dealer client-side**

Edit `VolatilityTabClient.tsx`. Add imports + state + fetch:

```tsx
import { VolatilityRegimePanel } from "../panels/VolatilityRegimePanel";
import { MacroVcgTile } from "../panels/MacroVcgTile";
import type { RegimeDealerResponse } from "@/lib/api";

// inside the component:
const [regime, setRegime] = useState<RegimeDealerResponse | null>(null);
useEffect(() => {
  let cancelled = false;
  api
    .regimeDealer(ticker)
    .then((r) => {
      if (!cancelled) setRegime(r);
    })
    .catch(() => {
      if (!cancelled) setRegime(null);
    });
  return () => {
    cancelled = true;
  };
}, [ticker]);
```

- [ ] **Step 2: Slot the panel into the layout**

Wrap the existing content so the regime panel hugs the right side of the top region:

```tsx
return (
  <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16 }}>
      <VolMetricsCard header={series.header} />
      <VolatilityRegimePanel data={regime} />
    </div>

    {banner && (
      // existing banner …
    )}

    <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16 }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {/* existing analytical-series + today's-snapshot grids */}
      </div>
      <MacroVcgTile />
    </div>

    {/* VrpSpreadPanel … */}
  </div>
);
```

(Keep all existing panels in place — only the wrappers change.)

- [ ] **Step 3: Manual visual check**

Open `/stock/TSLA` → Volatility tab. Verify regime panel renders right of VolMetricsCard with the slider and Γ/V/C bars; macro VCG tile shows in the side column.

- [ ] **Step 4: Lint + typecheck**

```bash
cd web && npm run typecheck && npm run lint
```
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add web/components/stock/tabs/VolatilityTabClient.tsx
git commit -m "feat(web): slot VolatilityRegimePanel + MacroVcgTile into Volatility tab"
```

---

### Task 11: End-to-end manual verification + PR

- [ ] **Step 1: Run full test suite**

```bash
uv run pytest -x
cd web && npm run typecheck && npm run lint && npm run test
```
Expected: all green.

- [ ] **Step 2: Manual smoke test**

In a fresh dev session (`bash scripts/dev.sh`), navigate to:
- `/stock/TSLA` → Market Structure → GEX → confirm magnet bar, colored lines, history chart
- `/stock/SPY` → Market Structure → GEX → repeat
- `/stock/TSLA` → Volatility → confirm regime panel + VCG tile

For each: confirm there are no console errors and that numbers look reasonable vs. the existing legacy tiles (`GexLevelTiles`).

- [ ] **Step 3: Open PR**

```bash
git push -u origin feat/gex-volatility-enrichment
gh pr create --title "feat: GEX magnet bar, colored levels, history chart, volatility regime panel" --body "$(cat <<'EOF'
## Summary
- Adds per-ticker dealer regime classifier (Γ/V/C scores + Amplifying/Dampening label) at `cards/dealer_regime.py` and exposes it via `GET /api/regime/dealer` and on `SingleStockReport.dealer_regime`.
- New Market Structure → GEX sub-tab UI: MagnetGammaBar (5 tiles + regime headline) above, colored Spot / Flip / Call Wall / Put Wall reference lines on the strike chart, and a 90-day daily GEX history chart below.
- New Volatility tab UI: VolatilityRegimePanel (slider + Γ/V/C bars + closest levels + 0DTE GEX + gamma decay) and a small MacroVcgTile sidebar referencing the existing macro VCG signal.

## Test plan
- [ ] uv run pytest -x
- [ ] web typecheck + lint + vitest
- [ ] Manual smoke: /stock/TSLA, /stock/SPY (Market Structure → GEX, Volatility)
- [ ] Verify no console errors in browser
EOF
)"
```

Expected: PR URL returned. Do **not** merge from CLI — wait for CI and user review.

- [ ] **Step 4: Codex review gate**

Per `apex` policy reused in this repo, before merging run `/codex-review` against the PR diff. Address any P1 issues with follow-up commits on the same branch.

---

## Self-review check (updated rev 2)

- **Spec coverage:** Image 8 → Tasks 5 + 8 (MagnetGammaBar + integration). Image 9 → Task 7 (GexHistoryChart). Image 10 → Task 6 (colored lines). Image 11 → Tasks 9 + 10 (VolatilityRegimePanel + integration). Per-ticker regime classifier (foundation for 8 and 11) → Tasks 1-3. Macro VCG sidebar (per user choice) → Task 9 (MacroVcgTile).
- **Placeholder scan:** every step has either a code block or an exact command. No "TBD" / "implement later" / "add appropriate validation".
- **Type consistency:** `DealerRegimeResponse` shape is consistent across schema (Task 1), card output mapping (Task 2/3), and frontend consumers (Tasks 9/10). `gamma_decay` carries `dte`, `expiry`, `net_gex`, `share_pct`, `gross_abs_gex`, `gross_share_pct`. `closest_levels` carries `rank_kind` ∈ {nearest, dominant}. Field names match between Python (`odte_gex`) and TS (`odte_gex` via gen:types).
- **Rev 2 patch traceability:** every patch is anchored to either a codex issue (15), gemini-2 issue (2 valid out of 8), or adversarial attack (5). False positives from gemini's first hallucinated pass and the second pass's bogus `/regime/gex doesn't exist` and `snap["levels"] is a Pydantic model` claims were dismissed with evidence.
- **Source-of-truth check:** `cards/dealer_regime.gather_inputs(repo, ticker=...)` is the single entry that both the report assembler (Task 3a) and the endpoint (Task 4) call. No second data path exists.
- **Graceful-degradation check:** with `greek_exposure_daily` populated only for the GEX scanner universe (SPX/SPY/index complex), non-index tickers will have `prev_close_net_gex=None`, an empty history chart, and a 0DTE bucket only if `strike_gex_curve` covers today — all surfaced as muted "—" or "No GEX history" copy, never as a crash.

## Risks called out

- **`repository.py` integration** — fixed in rev 2. Task 3 now uses `repo.latest_run_id(ticker)` + `repo.get_strike_gex_curve(run_id)` + `repo.fetch_exposures_summary(run_id, ticker)` (the same primitives `reports/single_stock.py` uses). No new methods are added to `repository.py` — per the standing rule that new domains get their own leaf module.
- **Wide-table types regenerated** — `npm run gen:types` will produce a sizable diff in `web/lib/types.ts`. Commit it as a single step (Task 4) so review can scan it independently.
- **Macro VCG availability** — `MacroVcgTile` will render `—` if `/regime/vcg` has no snapshot yet. That's intentional — don't add stale-data warnings; the panel degrades gracefully.
- **Dev server reload** — APScheduler worker doesn't hot-reload. After backend changes, restart workers (see `memory/feedback_check_worker_etime_before_debugging.md`).

---

## Rev 2 patch appendix — remaining task overrides

The following corrections override the matching sections above. They were folded into the plan during the post-review patch pass; tasks reference these by number.

### A) Task 2 — additional unit tests required

Append to `tests/unit/cards/test_dealer_regime.py`:

```python
def test_dealer_regime_neutral_band_below_threshold() -> None:
    # Sub-threshold weighted score → "neutral", not "dampening".
    sig = classify_regime(gamma=0.01, vanna=0.02, charm=-0.01)
    assert sig.label == "neutral"

def test_compute_gamma_decay_zero_net_keeps_gross() -> None:
    # Two strikes cancel at the same expiry → net=0 but gross > 0.
    today = date(2026, 5, 18)
    curve = [
        {"strike": Decimal("400"), "expiry": date(2026, 5, 22), "net_gex": Decimal("100000")},
        {"strike": Decimal("400"), "expiry": date(2026, 5, 22), "net_gex": Decimal("-100000")},
    ]
    buckets = compute_gamma_decay(curve, today=today)
    assert len(buckets) == 1
    b = buckets[0]
    assert b.net_gex == pytest.approx(0.0)
    assert b.gross_abs_gex == pytest.approx(200_000.0)
    assert b.share_pct is None  # net is all-zero → undefined share
    assert b.gross_share_pct == pytest.approx(1.0)

def test_compute_gamma_decay_filters_expired() -> None:
    today = date(2026, 5, 18)
    curve = [
        {"strike": Decimal("400"), "expiry": date(2026, 5, 15), "net_gex": Decimal("999")},  # past
        {"strike": Decimal("400"), "expiry": date(2026, 5, 22), "net_gex": Decimal("100")},
    ]
    buckets = compute_gamma_decay(curve, today=today)
    assert {b.dte for b in buckets} == {4}

def test_normalize_levels_accepts_both_field_names() -> None:
    raw = {
        "call_wall": {"strike": "450.0", "gamma": "46550"},        # legacy snapshot shape
        "put_wall": {"strike": "395.0", "net_gex": "-966840"},     # report shape
        "max_accelerator": {"strike": "410.0", "gamma": "19210"},  # legacy key
    }
    out = _normalize_levels(raw)
    assert out is not None
    assert "max_accel" in out
    assert out["call_wall"]["net_gex"] == "46550"
    assert out["put_wall"]["net_gex"] == "-966840"

def test_build_closest_levels_returns_nearest_and_dominant() -> None:
    levels = {
        "call_wall": {"strike": 450, "net_gex": 5_000_000},   # far + dominant
        "put_wall": {"strike": 408, "net_gex": -50_000},      # nearest + small
    }
    out = _build_closest_levels(spot=410.0, levels=levels)
    nearest = [l for l in out if l.rank_kind == "nearest"]
    dominant = [l for l in out if l.rank_kind == "dominant"]
    assert nearest[0].label == "Put Wall"
    assert dominant[0].label == "Call Wall"
```

Also re-name and split the existing all-decay test so each test covers exactly one behavior. Total count: 12 tests (was 7).

### B) Task 4 — type regen diff

Expected new schemas in `web/lib/types.ts` after `npm run gen:types`:

- `components["schemas"]["DealerRegimeResponse"]`
- `components["schemas"]["DealerRegimeSignal"]`
- `components["schemas"]["ClosestLevel"]` (with `rank_kind`)
- `components["schemas"]["GammaDecayBucket"]` (with `gross_abs_gex`, `gross_share_pct`)
- `components["schemas"]["DealerRegime"]` (re-exported via the scanner namespace alongside `MarketStructureLevels`)
- New path entry `/api/regime/dealer` under `paths`

### C) Task 5 — MagnetGammaBar test path + partial-data UX

- **Path**: `web/tests/unit/MagnetGammaBar.test.tsx` (NOT `web/tests/components/`).
- **Fixtures**: replace `as any` with `satisfies Pick<components["schemas"]["SingleStockReport"], "ticker" | "market_structure" | "market_structure_levels" | "dealer_regime">`.
- **Partial-data UX**: when `dealer_regime` is present but `prev_close_net_gex === null` or `odte_net_gex === null`, render the tile with `—` and `text-muted` color rather than skipping the tile (preserves the 5-column grid).
- **Test additions**: `it("shows — for missing prev close")` and `it("shows — for missing 0DTE")`.

### D) Task 6 — GexProfileChart hardening

In addition to the existing changes, apply these guards in `GexProfileChart.tsx`:

```tsx
// Bail out cleanly when spot is missing or zero — earlier draft would
// collapse the render window to [0, 0] and hide every strike.
if (spot == null || spot <= 0) {
  return (
    <div style={panelStyle}>
      <div style={headingStyle}>GEX Profile — Net gamma by strike</div>
      <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
        Spot price unavailable for {report.ticker}.
      </div>
    </div>
  );
}
```

`strikeToY()` must interpolate over **all in-window strikes**, not the post-`MIN_ABS_GEX` filtered list:

```tsx
const inWindowStrikes = Array.from(perStrike.keys())
  .filter((s) => s >= winLo && s <= winHi)
  .sort((a, b) => b - a); // top-to-bottom render order

// strikeToY interpolates over inWindowStrikes, not `strikes` (the
// filtered list used for bar rendering). Otherwise an overlay anchor
// (flip / wall / spot) whose strike falls into a row filtered out by
// MIN_ABS_GEX disappears from the chart even though it's inside the
// ±15% window.
function strikeToY(level: number): number | null {
  if (inWindowStrikes.length === 0) return null;
  const hi = inWindowStrikes[0];
  const lo = inWindowStrikes[inWindowStrikes.length - 1];
  if (level > hi || level < lo) return null;
  for (let i = 0; i < inWindowStrikes.length - 1; i++) {
    const a = inWindowStrikes[i];
    const b = inWindowStrikes[i + 1];
    if (level <= a && level >= b) {
      const t = (a - level) / (a - b);
      // Same row pixel-height ROW_H as the visible strike list.
      return (i + t) * ROW_H + ROW_H / 2;
    }
  }
  return null;
}
```

Add a unit test `web/tests/unit/GexProfileChart.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GexProfileChart } from "@/components/stock/panels/GexProfileChart";

const baseReport = {
  ticker: "TSLA",
  market_structure: { spot: 410, net_gex: 216910 },
  market_structure_levels: {
    call_wall: { strike: 450, net_gex: 46550 },
    put_wall: { strike: 395, net_gex: -966840 },
    gex_flip: { strike: 474.64, net_gex: 0 },
  },
  strike_gex_curve: [
    { strike: 395, expiry: "2026-05-22", net_gex: -100000 },
    { strike: 410, expiry: "2026-05-22", net_gex: 50 },          // below MIN_ABS_GEX
    { strike: 450, expiry: "2026-05-22", net_gex: 200000 },
  ],
} as any;

describe("GexProfileChart", () => {
  it("renders nothing meaningful when spot is missing", () => {
    const r = { ...baseReport, market_structure: { spot: null, net_gex: null } };
    render(<GexProfileChart report={r} />);
    expect(screen.getByText(/Spot price unavailable/)).toBeInTheDocument();
  });

  it("renders all four colored overlay labels", () => {
    render(<GexProfileChart report={baseReport} />);
    expect(screen.getByText(/Call Wall/)).toBeInTheDocument();
    expect(screen.getByText(/Put Wall/)).toBeInTheDocument();
    expect(screen.getByText(/Gamma flip/)).toBeInTheDocument();
    expect(screen.getByText(/Spot/)).toBeInTheDocument();
  });
});
```

### E) Task 7 — GexHistoryChart responsive + bars-without-spot

Replace the fixed-dimension SVG with a responsive viewBox and decouple bar rendering from spot availability:

```tsx
const VB_W = 760;
const VB_H = 280;
// const VB = `0 0 ${VB_W} ${VB_H}`;
// <svg viewBox={VB} preserveAspectRatio="xMidYMid meet" width="100%" height="100%" …>
```

Render bars whenever `gexValues.length > 0` (do not gate on `spotValues.length`). When `spotValues.length === 0`, skip the spot line + right Y-axis labels:

```tsx
if (gexValues.length === 0) {
  return (
    <div style={PANEL}>
      <div style={HEADING}>Daily Gamma Exposure (GEX) — {ticker}</div>
      <div style={{ color: "var(--text-muted)", fontSize: 11 }}>
        No GEX history yet for {ticker} — populated only for tickers covered by
        the GEX scanner (index complex).
      </div>
    </div>
  );
}
// Compute spot scale only when spot is present.
const hasSpot = spotValues.length > 0;
const spotMin = hasSpot ? Math.min(...spotValues) : 0;
const spotMax = hasSpot ? Math.max(...spotValues) : 0;
// Use a padded domain so a constant spot doesn't hug the floor.
const padding = (spotMax - spotMin) * 0.1 || Math.max(spotMax * 0.05, 1);
const dMin = spotMin - padding;
const dMax = spotMax + padding;
const ySpot = (v: number) =>
  PAD.top + innerH - ((v - dMin) / (dMax - dMin)) * innerH;
```

Wrap the parent container with a width-aware sizing rule so the chart actually flexes:

```tsx
<div style={{ ...PANEL, width: "100%" }}>
  …
  <div style={{ width: "100%", aspectRatio: `${VB_W} / ${VB_H}` }}>
    <svg viewBox={`0 0 ${VB_W} ${VB_H}`} preserveAspectRatio="xMidYMid meet" width="100%" height="100%" …>
```

Add a unit test `web/tests/unit/GexHistoryChart.test.tsx` covering the empty-history case and the bars-without-spot case (mock `api.regimeGex`).

### F) Task 9 — VolatilityRegimePanel + MacroVcgTile

**Path**: `web/tests/unit/VolatilityRegimePanel.test.tsx`.

**Render nearest + dominant**: the panel now reads `closest_levels` and groups them by `rank_kind` — render two short lists ("Nearest" and "Dominant") rather than one mixed sort:

```tsx
const nearestLevels = (closest_levels ?? []).filter((l) => l.rank_kind === "nearest");
const dominantLevels = (closest_levels ?? []).filter((l) => l.rank_kind === "dominant");
// … render each list with its own section heading.
```

**0DTE label**: change the section heading from "0DTE GEX" to "Today's GEX (0DTE)" and add a sibling tile "Next session" using `gamma_decay.find(b => b.dte > 0 && b.dte <= 1)` (or the nearest forward expiry) so the headline stops over-claiming "by tomorrow" (per adversarial ATTACK-4).

**Gamma decay row**: render both net and gross magnitudes:

```tsx
<span style={{ color, fontWeight: 700 }}>{b.dte}d</span>
<span style={{ color: "var(--text-muted)" }}>{b.expiry}</span>
{/* gross magnitude bar — colored gray to distinguish from net */}
<div style={{ … width: `${(b.gross_share_pct ?? 0) * 100}%`, background: "var(--text-muted)" }} />
{/* net direction bar overlaid */}
<div style={{ … width: `${(b.share_pct ?? 0) * 100}%`, background: color }} />
<span style={{ textAlign: "right", color }}>{fmtMoney(b.net_gex)}</span>
<span style={{ textAlign: "right", color: "var(--text-muted)" }}>{fmtMoney(b.gross_abs_gex)} gross</span>
```

**MacroVcgTile correct VCG interpretation strings**:

```tsx
type VcgState =
  | "PANIC"
  | "RISK_OFF"
  | "EDR"
  | "BOUNCE"
  | "WATCH"
  | "NORMAL"
  | "SUPPRESSED"
  | "INSUFFICIENT_DATA";

const VCG_COLOR: Record<VcgState, string> = {
  PANIC: "var(--negative)",
  RISK_OFF: "var(--negative)",
  EDR: "var(--warning)",
  BOUNCE: "var(--positive)",
  WATCH: "var(--warning)",
  NORMAL: "var(--positive)",
  SUPPRESSED: "var(--text-muted)",
  INSUFFICIENT_DATA: "var(--text-muted)",
};

const interp = (data?.signal?.interpretation as VcgState | undefined) ?? "INSUFFICIENT_DATA";
const color = VCG_COLOR[interp];
```

Also add a smoke test for `MacroVcgTile` (`web/tests/unit/MacroVcgTile.test.tsx`) — render with mocked `api.regimeVcg()` returning each interpretation enum value; assert the color CSS variable matches.

**Strongly-typed fixtures everywhere**: replace `as any` with `satisfies RegimeDealerResponse` (and the like). If a partial fixture is needed for a small test, use a typed factory:

```tsx
function makeRegime(overrides: Partial<RegimeDealerResponse> = {}): RegimeDealerResponse {
  return { status: "ok", ticker: "TSLA", spot: 410, … , ...overrides };
}
```

### G) Task 10 — VolatilityTabClient clears stale state on ticker change

Replace the existing `useEffect` block in the Rev 1 draft with:

```tsx
const [regime, setRegime] = useState<RegimeDealerResponse | null>(null);
const [regimeLoading, setRegimeLoading] = useState(true);

useEffect(() => {
  let cancelled = false;
  // Drop stale state immediately so the panel doesn't render the
  // previous ticker's regime until the new fetch resolves.
  setRegime(null);
  setRegimeLoading(true);
  api
    .regimeDealer(ticker)
    .then((r) => {
      if (cancelled) return;
      // Belt-and-suspenders: only accept the payload if the server
      // confirms the ticker we requested (handles a fast double-switch).
      if (r.ticker === ticker.toUpperCase()) {
        setRegime(r);
      }
    })
    .catch(() => {
      if (!cancelled) setRegime(null);
    })
    .finally(() => {
      if (!cancelled) setRegimeLoading(false);
    });
  return () => {
    cancelled = true;
  };
}, [ticker]);
```

Pass `loading={regimeLoading}` to `VolatilityRegimePanel` so it can render a quiet skeleton.

### H) Task 11 — OpenAPI snapshot regen step (NEW)

Insert before the manual smoke step:

- [ ] **Step 0: Regenerate OpenAPI snapshot**

Adding `/api/regime/dealer` and `dealer_regime` field will fail `tests/integration/api/test_openapi_snapshot.py`. After all backend tasks are done:

```bash
uv run python -c "
from uw_scan.api.server import create_app
from fastapi.testclient import TestClient
import json, pathlib
app = create_app()
client = TestClient(app)
spec = client.get('/openapi.json').json()
pathlib.Path('tests/integration/api/openapi.snapshot.json').write_text(
    json.dumps(spec, indent=2, sort_keys=True) + '\n'
)
print('snapshot regenerated')
"
uv run pytest tests/integration/api/test_openapi_snapshot.py -v
```
Expected: snapshot regenerated, snapshot test passes.

### I) Compute path deduped — confirm both call sites use `gather_inputs`

After the changes in Task 3a + 3b + 4, the report assembler and the endpoint share exactly one upstream helper (`cards/dealer_regime.gather_inputs`). Verify with:

```bash
grep -rn "gather_inputs\|compute_dealer_regime" src/uw_scan/
```
Expected: only two callers — `reports/single_stock.py` and `api/routers/regime.py` (plus the card module itself).

### J) Adversarial deltas folded in (summary)

For traceability, these are the adversarial-driven changes applied above:

| Attack | What changed | Where |
|--------|--------------|-------|
| 1 — Γ/V/C linear blend is unvalidated finance | Added explicit caveat in module constants; raw Γ/V/C remain primary | Task 2 constants block |
| 2 — Net per-expiry hides gross | Added `gross_abs_gex` and `gross_share_pct` fields on `GammaDecayBucket`; UI renders both bars | Task 1 schema + Task 2 card + Task 9 panel |
| 3 — Closest ≠ dominant | Split closest_levels into "nearest" and "dominant" rankings via `rank_kind`; subtitle reads dominant | Task 2 card + Task 1 schema + Task 9 panel |
| 4 — 0DTE labeling | UI renames to "Today's GEX (0DTE)" and adds "Next session" tile | Task 9 panel |
| 5 — Fixed 760×280 SVG | Switched to viewBox + aspectRatio container, responsive across widths | Task 7 chart |

---

## REV 3 — Pre-implementation verification patch (2026-05-21)

Verified the open assumptions from the rev-2 confidence assessment against the actual codebase and the local Postgres state. **This appendix supersedes the gather_inputs body and the placeholder method names from rev-2 wherever they conflict.**

### V1) gather_inputs data sources were wrong

**Verified (rev-2 was broken):**
- `repo.get_aggregates(run_id)` returns a Pydantic `MarketAggregates` model — NOT a dict. `aggregates.get("spot")` would `AttributeError`.
- `MarketAggregates` only contains `call_oi_total`, `put_oi_total`, `call_volume_*`, `pcr_oi`, `pcr_vol`, `iv30d`, `market_cap`, `aum`. **It does NOT contain `spot` or `net_gex`.** Even attribute access would yield `None`.
- The report assembler at `single_stock.py:126-150` builds `MarketStructure.spot` from `repo.fetch_realized_vol_latest(ticker)['price']` (with `max_pain_rows[0].close` as fallback) — NOT from `get_aggregates`.
- The report assembler at `single_stock.py:129-134` builds `MarketStructure.net_gex` from `repo.fetch_exposures_aggregate(run_id, ticker)['total_call_gex'] + ['total_put_gex']` — NOT from `get_aggregates`.

**Corrected `gather_inputs` body** (replaces lines 853-879 of the plan):

```python
strike_curve_raw = repo.get_strike_gex_curve(run_id) or []
exposures = repo.fetch_exposures_summary(run_id, t) or []

# Spot — same source as the report's MarketStructure.spot.
rv_row = repo.fetch_realized_vol_latest(t) or {}
spot_raw = rv_row.get("price")
spot_f = _to_float(spot_raw)

# Net GEX — same source/derivation as the report.
exp_agg = repo.fetch_exposures_aggregate(run_id, t) or {}
total_call_gex = exp_agg.get("total_call_gex")
total_put_gex = exp_agg.get("total_put_gex")
net_gex_f: float | None = None
if total_call_gex is not None and total_put_gex is not None:
    net_gex_f = _to_float(total_call_gex) + _to_float(total_put_gex)

# Build typed StrikeGexBucket list — compute_market_structure_levels()
# requires it (attribute access on b.net_gex inside the aggregator).
from uw_scan.models import StrikeGexBucket
from decimal import Decimal as _Dec
curve_typed: list[StrikeGexBucket] = []
for row in strike_curve_raw:
    if row.get("strike") is None or row.get("expiry") is None:
        continue
    curve_typed.append(
        StrikeGexBucket(
            strike=_Dec(str(row["strike"])),
            expiry=row["expiry"],
            net_gex=_Dec(str(row["net_gex"])) if row.get("net_gex") is not None else None,
            call_gex=_Dec(str(row["call_gex"])) if row.get("call_gex") is not None else None,
            put_gex=_Dec(str(row["put_gex"])) if row.get("put_gex") is not None else None,
        )
    )

# compute_market_structure_levels signature is (curve, spot) — positional.
# Param names are `curve` and `spot`, NOT `strike_gex_curve`.
levels_model = compute_market_structure_levels(
    curve_typed,
    _Dec(str(spot_f)) if spot_f is not None else None,
)
levels = levels_model.model_dump(mode="json") if levels_model else None

g = GreekExposureDailyRepository(repo.conn, schema=repo._schema)
history = g.fetch_history(t, days=5)
prev_close = _prev_close_net_gex(history, today)

return {
    "run_id": run_id,
    "spot": spot_f,
    "net_gex": net_gex_f,
    "prev_close_net_gex": prev_close,
    "per_expiry_vanna": [e.get("net_vanna") for e in exposures],
    "per_expiry_charm": [e.get("net_charm") for e in exposures],
    "strike_gex_curve": strike_curve_raw,  # dicts — consumers parse as needed
    "levels": levels,
    "today": today,
}
```

### V2) compute_market_structure_levels signature

**Verified at `src/uw_scan/cards/gex.py:109`:**

```python
def compute_market_structure_levels(
    curve: list[StrikeGexBucket],   # param name is `curve`, NOT `strike_gex_curve`
    spot: Decimal | None,
) -> MarketStructureLevels:
```

Rev-2 used `strike_gex_curve=` kwarg, which would `TypeError`. All call sites in this plan must use positional args (as the existing call at `single_stock.py:477` does) or `curve=` kwarg. Also: the function expects typed `StrikeGexBucket` objects — `b.net_gex` attribute access in the aggregator would fail on raw dicts.

### V3) Real integration test write methods (not placeholders)

**Verified — these are the actual write methods on `Repository`:**

| Rev-2 placeholder | Actual method | Location |
|---|---|---|
| `persist_strike_gex_curve(run_id, rows)` | `set_strike_gex_curve(run_id, curve: list[dict])` | `storage/scan_runs.py:122` |
| `persist_exposures_summary(run_id, ticker, rows)` | `upsert_exposures_summary(run_id, ticker, market_date, rows)` | `storage/options.py:214` |
| `upsert_aggregates(run_id, rows)` | `set_aggregates(run_id, agg: MarketAggregates)` | `storage/scan_runs.py:97` |

**BUT — also verified `MarketAggregates` does not contain spot/net_gex.** So the cleaner integration-test seeding pattern is the one already used by `tests/integration/test_gex_scanner.py:20-101`: monkeypatch `gex_scanner.fetch_iv_rank_rows` / `fetch_strike_gex` / `fetch_aggregate_gex` / `fetch_stock_state_snapshot` / `fetch_vol_pc`, then call `gex_scanner.run(client, repo, ticker="TSLA")`. That writes the full set of rows the regime path needs.

**Corrected ok-path test seeding (replaces lines 1091-1111):**

```python
# Seed via the production scanner path — same approach used by
# tests/integration/test_gex_scanner.py — so we exercise the real
# persistence layer (set_strike_gex_curve / upsert_exposures_summary /
# set_aggregates) rather than ad-hoc inserts.
monkeypatch.setattr(
    gex_scanner, "fetch_iv_rank_rows",
    lambda c, r, rid, t: [{"date": "2026-05-20", "close": "410.0",
                           "volatility": "0.4", "iv_rank_1y": "60.0"}],
)
monkeypatch.setattr(
    gex_scanner, "fetch_strike_gex",
    lambda c, r, rid, t: [
        {"strike": 450, "call_gex": 46550, "put_gex": 0,    "net_gex":  46550,
         "call_delta": 0.2, "put_delta": -0.1, "net_delta": 0.1},
        {"strike": 395, "call_gex": 0,     "put_gex": -12000, "net_gex": -12000,
         "call_delta": 0.4, "put_delta": -0.5, "net_delta": -0.1},
    ],
)
monkeypatch.setattr(gex_scanner, "fetch_aggregate_gex",
    lambda c, r, rid, t: [{"date": "2026-05-20", "call_gex": 46550,
                           "put_gex": -12000, "call_delta": 0.2,
                           "put_delta": -0.5}])
monkeypatch.setattr(gex_scanner, "fetch_vol_pc", lambda c, r, rid, t: 0.85)
monkeypatch.setattr(gex_scanner, "fetch_stock_state_snapshot",
    lambda c, r, rid, t: None)
gex_scanner.run(mock_client, repo, ticker="TSLA")
# At this point set_strike_gex_curve, set_aggregates (MarketAggregates),
# and greek_exposure_daily inserts have all fired via the production path.
```

The `repo.upsert_exposures_summary(...)` for vanna/charm seeding still needs an explicit write — that path isn't covered by `gex_scanner.run`. Use the real signature:

```python
from datetime import date as _date
repo.upsert_exposures_summary(
    run_id=run_id,
    ticker="TSLA",
    market_date=_date(2026, 5, 20),
    rows=[
        {
            "expiry": _date(2026, 5, 22), "dte": 2,
            "spot": Decimal("410"),
            "net_vanna": Decimal("120000"), "top_vanna_strike": Decimal("400"),
            "top_vanna_value": Decimal("80000"), "delta_shock_1pt_iv": Decimal("12000"),
            "vanna_regime": None, "vanna_flip": None, "vanna_headline": None, "vanna_subtitle": None,
            "net_charm": Decimal("-25000"), "charm_pin_strike": Decimal("410"),
            "charm_above_sum": Decimal("-30000"), "charm_below_sum": Decimal("5000"),
            "charm_imbalance_pct": Decimal("0.7"), "charm_signal_quality": "ok",
            "charm_flip": None, "charm_headline": None, "charm_subtitle": None,
        },
    ],
)
```

(Implementer should still grep `tests/integration/worker/test_cockpit_snapshot_persists_exposures_summary.py` to confirm the column nullability — non-null defaults may have shifted since this plan was drafted.)

### V4) GAMMA_SCALE = 5e5 calibration confirmed against real DB

**Verified against live data** (`exposures_by_expiry_strike` aggregated by `SUM(call_gex + put_gex)`):

| Ticker | Net GEX (real) | tanh(net_gex / 5e5) | Interpretation |
|---|---|---|---|
| SPY    | ~194,309   | 0.37  | mild long-γ |
| NVDA   | ~649,979   | 0.86  | strong long-γ |
| AAPL   | ~257,718   | 0.50  | moderate long-γ |
| TSLA   | ~81,085    | 0.16  | near-neutral |

The constant `GAMMA_SCALE = 5e5` produces sensible spreads across the score range for real production magnitudes. **Calibration concern from rev-2 (adversarial ATTACK-1) substantially reduced.**

Per-ticker scale calibration is still worthwhile but not blocking — the default delivers a usable signal on shipped data.

### V5) greek_exposure_daily zero-values warning (data state in local DB)

**Verified blocker for the "Γ vs prev close" tile** in development:

```sql
SELECT ticker, trade_date, call_gex, put_gex, net_gex
  FROM uw_scan.greek_exposure_daily
 WHERE ticker IN ('SPX','SPY') ORDER BY trade_date DESC LIMIT 10;
```

…returns all-zero values for the last two weeks. The `payload->>` JSONB also reads `0.0`. `net_gex` is a `GENERATED ALWAYS AS (call_gex + put_gex) STORED` column.

**Implication:**
- `prev_close_net_gex` in `gather_inputs` will be `0` for SPX/SPY in this dev DB.
- The magnet bar's `Γ vs prev close` tile will render as `0%` until the persistence path that writes `call_gex` / `put_gex` is debugged.
- This is **not** a bug in the new code being added by this plan — it's a pre-existing data state. Tracked separately. Task 1's schema/UI must render gracefully when `prev_close_net_gex == 0` or `None` (already covered by the "Decimal(0) handled correctly" rev-2 fix).

**Recommendation for the implementer:** run the same `SELECT` after each Task-3 verification to know whether the panel will be reading real prev-close data or zero. If still zero post-implementation, file a separate issue against the `_persist_greek_exposure_daily` writer (likely a unit/precision bug at the parser util).

### V6) vitest test discovery confirmed

`web/vitest.config.ts` has `include: ["tests/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"]`. Tests under `web/tests/unit/**/*.test.tsx` will be picked up. **No change needed.**

### V7) _preserve_public_module signature confirmed

`src/uw_scan/models/_base.py:17` is `_preserve_public_module(*model_types: type[object]) -> None`. Variadic. Passing `DealerRegime` alongside the existing models in `scanner.py` (or in a new `regime.py` module if scoped that way) works as planned.

### V8) models/__init__.py export pattern confirmed

Re-exports happen as `from .scanner import (..., DealerRegime, ...)`. Plan instruction to add `DealerRegime` to that block matches the existing pattern verbatim.

### Confidence after REV 3

| Surface | Pre-V3 | Post-V3 |
|---|---|---|
| `gather_inputs` data flow | 60% (broken — wrong keys + wrong return type) | **95%** (verified against single_stock.py:126-150) |
| `compute_market_structure_levels` call | 65% (wrong kwarg) | **95%** (signature + typed-list requirement verified) |
| Integration test write methods | 50% (placeholders) | **90%** (real names cited + production seeding path used) |
| GAMMA_SCALE calibration | 50% (unverified) | **85%** (real SPY/NVDA/AAPL/TSLA magnitudes back the choice) |
| Models export pattern | 70% (pattern-matched) | **95%** (signature + existing usage verified) |
| Vitest discovery | 70% | **95%** (config glob matches) |
| Local DB prev-close data | unknown | **documented gap** (zero values; render guard already in place) |
| Overall | ~70% | **~90%** |

Remaining open items below 95% are:
- Γ/V/C linear blend financial validity — still an unvalidated finance call; caveat carried forward
- SVG responsive `viewBox` integration into existing chart sizing — frontend work to do at implementation, not a plan defect
- The `_persist_greek_exposure_daily` zero-write bug is pre-existing and out of scope for this plan

