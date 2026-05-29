# Trade Framework View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the deterministic trade-plan tab with an AI-driven "Framework" view that ports the `trade-skills` knowledge library + judgment style into the existing Trade Insights AI pipeline as an additive `framework{}` block, rendered per-provider (Codex / Claude / DeepSeek) as a reasoned decision stack ending in one decisive best setup.

**Architecture:** One AI run per provider, two views. The existing audit tab is unchanged; the trade-plan tab becomes a client-island Framework view polling the same `trade_insight_ai_analyses` rows. The structured outcome already serializes to `outcome_jsonb` (JSONB) and returns via the existing `/latest` endpoint — so the output-contract change is purely additive (new Pydantic model + validator rule + leniency hook + prompt-version bump; **no new migration, no new endpoint, no storage change**). New data (UW positioning + massive fundamentals + macro) is fetched by worker jobs into Postgres and read into the payload at POST time; absent data degrades to `na`, never fabricated.

**Tech Stack:** Python 3.13 (`uv` only), FastAPI + Pydantic v2, psycopg 3, APScheduler 3; Next.js 16 + React 19 + TypeScript (hand-rolled SVG charts, Argon dark theme); pytest + pytest-postgresql, Vitest + Playwright; types via `openapi-typescript` → `web/lib/types.ts`.

---

## Spec

Design spec: `docs/superpowers/specs/2026-05-29-trade-framework-view-design.md` (in this worktree). Read it before starting — this plan implements its 15 sections.

## Pre-flight (already done by the planner — verify, don't redo)

- Worktree: `.worktrees/feat-trade-framework-view` on branch `feat/trade-framework-view`, **based on `origin/main` (`95d370e`, DeepSeek merged)** — NOT the stale local `main` (which lacks DeepSeek). Verify with `git -C . log --oneline -1` → should show `95d370e feat(trade-insights-ai): add DeepSeek …`.
- Migration baseline: highest is **`064_trade_insights_ai_provider_metadata.sql`**. New migrations start at **`065`**.
- `RUNNERS = {codex, claude, deepseek}` in `worker/jobs/trade_insights_ai.py`. `TradeInsightAiProvider = Literal["codex","claude","deepseek"]` in `models/trade_insights_ai_parts/base.py`.
- `PROMPT_VERSION = "trade-insights-ai-v5.3"` in `reports/trade_insights_ai/prompt_text.py`.

### Baseline test gate (run before Milestone 1)

```bash
cd /Users/chenxi/projects/unusual-whales/.worktrees/feat-trade-framework-view
uv sync --extra postgres
uv run pytest tests/unit/test_models_exports.py tests/unit/reports -q
cd web && npm install && npm run typecheck && npm run test -- --run
```
Expected: PASS (establishes a clean baseline; if anything fails it's pre-existing — record it and ask before proceeding).

---

## Cross-cutting standing rules (apply to EVERY task)

- **`uv` only** — `uv run pytest`, never bare `pytest`/`python`/`pip`.
- **No naked shorts** — every `candidates[]` and `best_setup` must be defined-risk; the validator enforces it.
- **Persist analytical results to Postgres** — fundamentals/positioning land in tables.
- **No secrets to model subprocesses** — UW/massive fetching happens only in worker jobs; never passed to `codex exec`/`claude --print`. DeepSeek's `DEEPSEEK_API_KEY` is read in-process by its HTTP runner.
- **Migrations idempotent** — `IF NOT EXISTS`, `ON CONFLICT DO NOTHING`.
- **Module budget** — target <500 lines/file; the KB constant module is pure data (acceptable, like `prompt_text.py`).
- **Contract identity** — new models are additive; preserve `models.__all__` (add new names), preserve `__module__` via `_preserve_public_module`, regenerate OpenAPI snapshot + `web/lib/types.ts`.
- **No `Co-Authored-By: Claude` trailer.** Never commit without this plan's explicit commit steps (milestone commits are pre-authorized for this project).
- **Screenshots** → `output/playwright/`.

---

## File structure (created / modified)

**Created — backend AI contract**
- `src/uw_scan/models/trade_insights_ai_parts/framework.py` — `TradeFramework` + nested models.
- `src/uw_scan/reports/trade_insights_ai/validator_rules/framework.py` — `apply_framework_rules`.
- `src/uw_scan/reports/trade_insights_ai/leniency/framework.py` — `_coerce_framework`.
- `src/uw_scan/reports/trade_insights_ai/trade_framework_kb.py` — `TRADE_FRAMEWORK_KNOWLEDGE` (loads vendored `kb/*.md`).
- `src/uw_scan/reports/trade_insights_ai/kb/*.md` — vendored trade-skills library (verbatim copy).

**Created — backend data layer**
- `src/uw_scan/sources/massive_fundamentals.py` — Polygon-shaped fundamentals client.
- `src/uw_scan/storage/fundamentals.py` — `_FundamentalsMixin`.
- `src/uw_scan/storage/positioning.py` — `_PositioningMixin`.
- `src/uw_scan/worker/jobs/fundamentals_jobs.py` — massive-role nightly refresh.
- `src/uw_scan/worker/jobs/positioning_jobs.py` — uw-role daily refresh.
- `src/uw_scan/cards/framework_tape.py` — pure OHLCV-derivation deriver.
- `src/uw_scan/storage/migrations/066_massive_fundamentals.sql`, `065_uw_positioning.sql`.

**Created — frontend**
- `web/components/stock/tabs/FrameworkTab.tsx` — client island (replaces `TradePlanTab.tsx`).
- `web/components/stock/tabs/framework/*.tsx` — decision-stack section components.

**Modified — backend**
- `models/trade_insights_ai_parts/base.py` (+ framework enums), `models/trade_insights_ai.py` (+ `framework` field + import + `_preserve_public_module`), `models/__init__.py` (+ exports).
- `reports/trade_insights_ai/prompt_text.py` (`PROMPT_VERSION` → v6.0), `analysis_input.py` (KB injection + payload sections), `validators.py` (call `apply_framework_rules`), `trade_insights_ai_lenient.py` (call `_coerce_framework`).
- `sources/uw.py` (+ T1 fetchers), `api/endpoints.py` (+ T1 slugs), `worker/scheduler.py` (+ 2 jobs), `storage/repository.py` (+ 2 mixins), `config.py` (+ cron/TTL settings).
- `reports/single_stock.py` (delete trade-plan producers), `models/stock.py` (delete `TradePlan`/`TradePlanLeg` + field).

**Modified — frontend**
- `web/app/stock/[ticker]/[tab]/page.tsx` (rewire `trade-plan` → client island), `useAiAnalysisPolling.ts` + `api.ts` (extend `PROVIDERS`/types to include `deepseek`).

**Modified — tests/contract**
- `tests/unit/test_models_exports.py`, `tests/unit/test_report_assembly.py`, `tests/integration/api/openapi.snapshot.json` (regenerate), `web/lib/types.ts` (regenerate).

---

# Milestone 1 — Framework output contract (Pydantic model + schema + exports)

The spine. Everything downstream references this shape. The schema auto-includes the field via `model_json_schema()`, so this milestone alone makes `framework{}` valid contract.

### Task 1.1: Add framework enums to `base.py`

**Files:**
- Modify: `src/uw_scan/models/trade_insights_ai_parts/base.py`

- [ ] **Step 1: Append the framework Literal enums** after the existing `TradeInsightAiProvider` line (after base.py:51):

```python
# --- Trade Framework (v6.0) enums ---
FrameworkPositionType = Literal["swing", "leaps", "stand_aside"]
FrameworkDirectionVerdict = Literal["bull", "bear", "neutral"]
FrameworkVegaRegime = Literal["event_iv", "demand_iv", "low_iv"]
FrameworkStructureFamily = Literal["directional_defined_risk", "pin_vega"]
FrameworkGammaRegime = Literal["short", "long"]
FrameworkCatalystHandling = Literal["exit_before_print", "stand_aside", "hold_through_leaps"]
FrameworkFactorStatus = Literal["yes", "no", "na"]
```

- [ ] **Step 2: Verify import** — these are consumed by `framework.py` (Task 1.2). No test yet; covered by Task 1.3.

### Task 1.2: Create the `TradeFramework` model

**Files:**
- Create: `src/uw_scan/models/trade_insights_ai_parts/framework.py`
- Test: `tests/unit/models/test_trade_framework_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/models/test_trade_framework_model.py
from uw_scan.models import TradeFramework


def test_trade_framework_minimal_stand_aside():
    fw = TradeFramework.model_validate(
        {
            "header": {"thesis_one_liner": "no edge", "position_type": "stand_aside",
                       "spot": "100.00", "conviction_n": 0},
            "three_axis": {
                "direction": {"verdict": "neutral", "prose": "mixed"},
                "vega": {"regime": "low_iv", "ivr": "20", "term_slope": "flat", "prose": "cheap"},
                "asymmetry": {"rule_on": False, "structure_family": "pin_vega", "prose": "n/a"},
            },
            "gamma": {"regime": "long", "flip_strike": None, "call_wall": None,
                      "put_wall": None, "prose": "stable"},
            "catalyst": {"next_er_date": None, "dte_to_er": None, "implied_move": None,
                         "handling": "stand_aside", "prose": "no event"},
            # exactly 8 factors required (min_length=8); all na here → score 0
            "conviction": {"score": 0, "prose": "insufficient",
                           "factors": [{"name": f"f{i}", "status": "na"} for i in range(8)]},
            "confluence": {"aligned": False, "signals": [], "prose": "none"},
            "pitfalls": [],
            "candidates": [],
            "best_setup": {"structure": "stand_aside", "legs": [], "cost": None,
                           "max_risk": None, "rationale": "no data", "why_not_alternatives": "",
                           "invalidation": "re-engage when tape resolves"},
            "what_changes": [],
            "bottom_line": "stand aside",
        }
    )
    assert fw.header.position_type == "stand_aside"
    assert fw.best_setup.structure == "stand_aside"


def test_trade_framework_rejects_unknown_field():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        TradeFramework.model_validate({"header": {}, "bogus": 1})
```

- [ ] **Step 2: Run it, verify it fails**

Run: `uv run pytest tests/unit/models/test_trade_framework_model.py -q`
Expected: FAIL — `ImportError: cannot import name 'TradeFramework'`.

- [ ] **Step 3: Write `framework.py`** (all models subclass `TradeInsightAiBase` → `extra="forbid"`; nullable fields use `| None` so strict-mode `required` still allows null, matching `underlying_price: str | None`):

```python
"""Trade Framework (v6.0) contract — the ported trade-skills decision stack.

Additive block on TradeInsightAiOutcome. Prose fields are intentionally
unvalidated (free narrative). Structural invariants (conviction bounds,
defined-risk, best_setup↔candidates linkage) are enforced by
reports/trade_insights_ai/validator_rules/framework.py, not here.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import Field

from .base import (
    FrameworkCatalystHandling,
    FrameworkDirectionVerdict,
    FrameworkFactorStatus,
    FrameworkGammaRegime,
    FrameworkPositionType,
    FrameworkStructureFamily,
    FrameworkVegaRegime,
    TradeInsightAiBase,
)


class TradeFrameworkHeader(TradeInsightAiBase):
    thesis_one_liner: str
    position_type: FrameworkPositionType
    spot: Decimal | None = None
    conviction_n: int = Field(ge=0, le=8)  # canonical == conviction.score (validator-enforced)


class TradeFrameworkDirection(TradeInsightAiBase):
    verdict: FrameworkDirectionVerdict
    prose: str


class TradeFrameworkVega(TradeInsightAiBase):
    regime: FrameworkVegaRegime
    ivr: Decimal | None = None
    term_slope: str | None = None
    prose: str


class TradeFrameworkAsymmetry(TradeInsightAiBase):
    rule_on: bool
    structure_family: FrameworkStructureFamily
    prose: str


class TradeFrameworkThreeAxis(TradeInsightAiBase):
    direction: TradeFrameworkDirection
    vega: TradeFrameworkVega
    asymmetry: TradeFrameworkAsymmetry


class TradeFrameworkGamma(TradeInsightAiBase):
    regime: FrameworkGammaRegime
    flip_strike: Decimal | None = None
    call_wall: Decimal | None = None
    put_wall: Decimal | None = None
    prose: str


class TradeFrameworkCatalyst(TradeInsightAiBase):
    next_er_date: str | None = None
    dte_to_er: int | None = None
    implied_move: Decimal | None = None
    handling: FrameworkCatalystHandling
    prose: str


class TradeFrameworkFactor(TradeInsightAiBase):
    name: str
    status: FrameworkFactorStatus
    note: str = ""


class TradeFrameworkConviction(TradeInsightAiBase):
    score: int = Field(ge=0, le=8)
    # Exactly the 8 canonical bull-conviction factors (KB strategies.md / pitfall 24).
    # min/max 8 surfaces as minItems/maxItems in the strict schema so Codex/DeepSeek
    # emit all 8; the leniency layer pads missing canonical factors as `na` before
    # Claude output is validated. `score` counts only `yes` → the N/8 denominator is fixed.
    factors: list[TradeFrameworkFactor] = Field(min_length=8, max_length=8)
    prose: str = ""


class TradeFrameworkSignal(TradeInsightAiBase):
    name: str
    direction: str


class TradeFrameworkConfluence(TradeInsightAiBase):
    aligned: bool
    signals: list[TradeFrameworkSignal] = Field(default_factory=list)
    prose: str = ""


class TradeFrameworkPitfall(TradeInsightAiBase):
    id: str
    title: str
    triggered: bool
    note: str = ""


class TradeFrameworkCandidate(TradeInsightAiBase):
    name: str
    legs: list[str] = Field(default_factory=list)
    debit_credit: str | None = None
    net_delta: Decimal | None = None
    net_vega: Decimal | None = None
    pnl_bull: str | None = None
    pnl_base: str | None = None
    pnl_bear: str | None = None
    defined_risk: bool


class TradeFrameworkBestSetup(TradeInsightAiBase):
    structure: str  # a candidates[].name OR the literal "stand_aside" (validator-checked)
    legs: list[str] = Field(default_factory=list)
    # cost / max_risk / pnl_* are intentionally expressive STRINGS, not Decimal: the
    # trade-skills counterfactual style uses ranges/multiples ("~97%", "2-3x", "$1.20
    # debit", "capped +$380") — central to the TSEM lesson. The machine-checked safety
    # property is `candidates[].defined_risk: bool` (no naked shorts), not a parsed number.
    cost: str | None = None
    max_risk: str | None = None
    rationale: str
    why_not_alternatives: str = ""
    invalidation: str


class TradeFrameworkWhatChanges(TradeInsightAiBase):
    signal: str
    effect: str


class TradeFramework(TradeInsightAiBase):
    header: TradeFrameworkHeader
    three_axis: TradeFrameworkThreeAxis
    gamma: TradeFrameworkGamma
    catalyst: TradeFrameworkCatalyst
    conviction: TradeFrameworkConviction
    confluence: TradeFrameworkConfluence
    pitfalls: list[TradeFrameworkPitfall] = Field(default_factory=list)
    candidates: list[TradeFrameworkCandidate] = Field(default_factory=list)
    best_setup: TradeFrameworkBestSetup
    what_changes: list[TradeFrameworkWhatChanges] = Field(default_factory=list)
    bottom_line: str
```

- [ ] **Step 4: Wire the field onto the outcome.** In `src/uw_scan/models/trade_insights_ai.py`:
  - Add to the `from .trade_insights_ai_parts.base import (...)` block (base.py:13-28) nothing (enums consumed only in framework.py), and add a new import after it:
    ```python
    from .trade_insights_ai_parts.framework import (
        TradeFramework,
        TradeFrameworkBestSetup,
        TradeFrameworkCandidate,
        TradeFrameworkCatalyst,
        TradeFrameworkConfluence,
        TradeFrameworkConviction,
        TradeFrameworkFactor,
        TradeFrameworkGamma,
        TradeFrameworkHeader,
        TradeFrameworkPitfall,
        TradeFrameworkSignal,
        TradeFrameworkThreeAxis,
        TradeFrameworkWhatChanges,
        TradeFrameworkDirection,
        TradeFrameworkVega,
        TradeFrameworkAsymmetry,
    )
    ```
  - Add the field to `TradeInsightAiOutcome` after `guardrails` (after trade_insights_ai.py:475):
    ```python
        framework: TradeFramework | None = None
    ```
  - Add all the imported framework classes to the `_preserve_public_module(...)` call (trade_insights_ai.py:578-613) so their `__module__` stays stable for OpenAPI component naming.

- [ ] **Step 5: Run, verify it passes** — `uv run pytest tests/unit/models/test_trade_framework_model.py -q` → PASS.

### Task 1.3: Export from `models/__init__.py`

**Files:**
- Modify: `src/uw_scan/models/__init__.py`
- Modify: `tests/unit/test_models_exports.py`

- [ ] **Step 1:** In `models/__init__.py`, add to the `from .trade_insights_ai import (...)` block (init.py:137-173): `TradeFramework,` plus the nested public names (`TradeFrameworkHeader`, `TradeFrameworkThreeAxis`, `TradeFrameworkDirection`, `TradeFrameworkVega`, `TradeFrameworkAsymmetry`, `TradeFrameworkGamma`, `TradeFrameworkCatalyst`, `TradeFrameworkConviction`, `TradeFrameworkFactor`, `TradeFrameworkConfluence`, `TradeFrameworkSignal`, `TradeFrameworkPitfall`, `TradeFrameworkCandidate`, `TradeFrameworkBestSetup`, `TradeFrameworkWhatChanges`).

- [ ] **Step 2:** Add the same names to `__all__` (init.py:291-325 block).

- [ ] **Step 3:** Update `tests/unit/test_models_exports.py` — add the **16** new names (`TradeFramework` + its 15 nested component models) to the expected `__all__` surface (alphabetically placed near the other `TradeInsightAi*`/`TradeFramework*` entries). (Note: this same test loses `"TradePlan"`/`"TradePlanLeg"` in Milestone 8 — do not remove those yet.)

- [ ] **Step 4: Run** — `uv run pytest tests/unit/test_models_exports.py -q` → PASS.

### Task 1.4: Schema auto-inclusion test + commit

**Files:**
- Test: `tests/unit/reports/test_trade_insights_ai_schema.py` (add a test; create if absent)

- [ ] **Step 1: Write the test**

```python
def test_output_schema_includes_framework():
    from uw_scan.reports.trade_insights_ai import trade_insights_ai_output_schema
    schema = trade_insights_ai_output_schema(strict=True, strip_lookaround_regex=True)
    assert "framework" in schema["properties"]
    assert "TradeFramework" in schema["$defs"]
    # strict mode forces every top-level property required; framework allows null via anyOf
    assert "framework" in schema["required"]
```

- [ ] **Step 2: Run** — `uv run pytest tests/unit/reports/test_trade_insights_ai_schema.py -q` → PASS (no code change needed; `model_json_schema()` already includes it).

- [ ] **Step 3: Verify gate** — `uv run pytest tests/unit/models tests/unit/test_models_exports.py tests/unit/reports -q` → PASS.

- [ ] **Step 4: Commit**

```bash
git add src/uw_scan/models/trade_insights_ai_parts/base.py \
        src/uw_scan/models/trade_insights_ai_parts/framework.py \
        src/uw_scan/models/trade_insights_ai.py \
        src/uw_scan/models/__init__.py \
        tests/unit/models/test_trade_framework_model.py \
        tests/unit/test_models_exports.py \
        tests/unit/reports/test_trade_insights_ai_schema.py
git commit -m "feat(trade-framework): add additive TradeFramework output contract"
```

---

# Milestone 2 — Framework validator + leniency coercion

Structural invariants the prompt promises. Runs in BOTH strict and lenient modes (defined-risk is a safety check). Skips cleanly when `framework is None`.

### Task 2.1: Write `apply_framework_rules`

**Files:**
- Create: `src/uw_scan/reports/trade_insights_ai/validator_rules/framework.py`
- Test: `tests/unit/reports/validator_rules/test_framework_rules.py`

- [ ] **Step 1: Write the failing tests** (cover: None→skip; conviction bounds; conviction.score == count(yes); header.conviction_n == score; defined-risk enforcement; best_setup linkage; stand_aside precedence; asymmetry na-aware):

```python
import pytest
from uw_scan.models import TradeInsightAiOutcome
from uw_scan.reports.trade_insights_ai.validator_rules.framework import apply_framework_rules


def _outcome_with_framework(fw: dict | None):
    # Build a minimal valid TradeInsightAiOutcome with framework attached.
    # Reuse the fixture helper from test_trade_framework_model where possible.
    ...  # construct via TradeInsightAiOutcome.model_construct or a shared fixture


def test_none_framework_is_noop():
    apply_framework_rules_on(None)  # helper that calls apply_framework_rules with framework=None


def test_naked_candidate_rejected():
    with pytest.raises(ValueError, match="defined_risk"):
        apply_framework_rules_on(framework_with_candidate(defined_risk=False))


def test_best_setup_must_match_candidate_or_stand_aside():
    with pytest.raises(ValueError, match="best_setup.structure"):
        apply_framework_rules_on(framework_best_setup="ghost_structure", candidates=["bull_put_spread"])


def test_conviction_count_mismatch_rejected():
    with pytest.raises(ValueError, match="conviction.score"):
        apply_framework_rules_on(score=4, yes_factors=2)


def test_conviction_n_must_equal_score():
    with pytest.raises(ValueError, match="conviction_n"):
        apply_framework_rules_on(conviction_n=3, score=4, yes_factors=4)


def test_stand_aside_precedence():
    with pytest.raises(ValueError, match="stand_aside"):
        apply_framework_rules_on(handling="stand_aside", best_setup="bull_put_spread")


def test_asymmetry_rule_on_requires_score_ge_4():
    with pytest.raises(ValueError, match="asymmetry"):
        apply_framework_rules_on(rule_on=True, score=3, yes_factors=3)


def test_asymmetry_rule_off_rejected_when_score_ge_4():
    # biconditional: score>=4 with rule_on=False is also a violation
    with pytest.raises(ValueError, match="asymmetry"):
        apply_framework_rules_on(rule_on=False, score=4, yes_factors=4)


def test_position_type_stand_aside_requires_best_setup_stand_aside():
    with pytest.raises(ValueError, match="stand_aside"):
        apply_framework_rules_on(position_type="stand_aside", best_setup="bull_put_spread")
```

(Implement the small `apply_framework_rules_on`/`framework_with_candidate` helpers in the test module to build outcomes — keep them local and explicit.)

- [ ] **Step 2: Run** — FAIL (`ImportError`).

- [ ] **Step 3: Write the rule.** Pattern mirrors `validator_rules/structure.py` (raises `ValueError`). `best_setup.structure` matches a candidate **verbatim** via a local `_norm` (case-fold + whitespace/hyphen normalization only — no alias/family fuzzing; the prompt makes the model echo the exact candidate name):

```python
"""Framework (v6.0) structural invariants. Raises ValueError on violation.

Prose fields are not validated. These checks enforce the assertive-but-honest
contract: conviction is a real count of yes-factors, every candidate is
defined-risk (no naked shorts), and best_setup commits to a real candidate
or an explicit stand_aside.
"""

from __future__ import annotations

from typing import Any

from uw_scan.models import TradeInsightAiOutcome


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def apply_framework_rules(
    parsed: TradeInsightAiOutcome,
    deterministic_payload: dict[str, Any] | None = None,
) -> None:
    fw = parsed.framework
    if fw is None:
        return  # provider omitted framework (legacy row or lenient skip) — graceful

    # 1. conviction.score == count of factors with status == "yes"
    yes_count = sum(1 for f in fw.conviction.factors if f.status == "yes")
    if fw.conviction.score != yes_count:
        raise ValueError(
            f"conviction.score ({fw.conviction.score}) must equal count of "
            f"yes factors ({yes_count})"
        )
    # 2. header.conviction_n == conviction.score
    if fw.header.conviction_n != fw.conviction.score:
        raise ValueError(
            f"header.conviction_n ({fw.header.conviction_n}) must equal "
            f"conviction.score ({fw.conviction.score})"
        )
    # 3. every candidate is defined-risk (no naked shorts — HARD safety)
    for cand in fw.candidates:
        if not cand.defined_risk:
            raise ValueError(
                f"framework candidate {cand.name!r} is not defined_risk "
                "(no naked shorts allowed)"
            )
    # 4. best_setup.structure resolves to a candidate name OR "stand_aside"
    bs = _norm(fw.best_setup.structure)
    if bs != "stand_aside":
        cand_names = {_norm(c.name): c for c in fw.candidates}
        match = cand_names.get(bs)
        if match is None:
            raise ValueError(
                f"best_setup.structure {fw.best_setup.structure!r} is neither "
                "'stand_aside' nor any candidates[].name"
            )
        if not match.defined_risk:
            raise ValueError(
                f"best_setup picked non-defined-risk candidate {match.name!r}"
            )
    # 5. stand_aside precedence: catalyst.handling==stand_aside ⇒ best_setup==stand_aside
    if fw.catalyst.handling == "stand_aside" and bs != "stand_aside":
        raise ValueError(
            "catalyst.handling=stand_aside requires best_setup.structure=stand_aside"
        )
    # 5b. position_type stand_aside ⟺ best_setup stand_aside (overall stance must agree)
    if (fw.header.position_type == "stand_aside") != (bs == "stand_aside"):
        raise ValueError(
            "header.position_type and best_setup.structure must agree on "
            f"stand_aside (position_type={fw.header.position_type!r}, "
            f"best_setup={fw.best_setup.structure!r})"
        )
    # 6. asymmetry.rule_on ⟺ conviction.score >= 4 (BOTH directions enforced).
    #    The "indeterminate / <4 non-na factors" case is SUBSUMED: yes ⊆ non-na, so
    #    non_na_count < 4 ⇒ score < 4 ⇒ rule_on must be False. No separate check needed;
    #    the "insufficient data" distinction lives in conviction.prose (spec §8), not here.
    if fw.three_axis.asymmetry.rule_on != (fw.conviction.score >= 4):
        raise ValueError(
            "asymmetry.rule_on must equal (conviction.score >= 4) "
            f"(rule_on={fw.three_axis.asymmetry.rule_on}, "
            f"score={fw.conviction.score})"
        )
```

- [ ] **Step 4: Wire it into `validators.py`.** Add the import next to the other `validator_rules` imports (validators.py:24-46):
  ```python
  from .validator_rules.framework import apply_framework_rules
  ```
  And call it after `_check_entry_state_derivation(parsed)` (validators.py:255):
  ```python
      apply_framework_rules(parsed, deterministic_payload)
  ```

- [ ] **Step 5: Run** — `uv run pytest tests/unit/reports/validator_rules/test_framework_rules.py -q` → PASS.

### Task 2.2: Leniency coercion for framework drift

**Files:**
- Create: `src/uw_scan/reports/trade_insights_ai/leniency/framework.py`
- Modify: `src/uw_scan/reports/trade_insights_ai_lenient.py`
- Test: `tests/unit/reports/leniency/test_framework_coerce.py`

- [ ] **Step 1: Write the failing test** — feed a Claude-style framework dict with cosmetic drift (conviction as string `"4"`, structure name `"Bull Put Spread"` vs candidate `"bull_put_spread"`, missing `defined_risk` defaulting) and assert the coerced dict parses + the structure normalizes:

```python
def test_coerce_framework_conviction_string_to_int():
    from uw_scan.reports.trade_insights_ai.leniency.framework import _coerce_framework
    raw = {"conviction": {"score": "4", "factors": [{"name": "x", "status": "yes"}] }}
    out = _coerce_framework(raw, candidates={})
    assert out["conviction"]["score"] == 4
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Write `_coerce_framework(raw, candidates)`** — (a) normalize conviction `score`/`header.conviction_n` string→int; (b) **pad the conviction ledger to exactly the 8 canonical factors** — define a module-level `CANONICAL_CONVICTION_FACTORS` tuple of the 8 names (from Task 3.3 / spec §8); for any canonical factor missing from `raw["conviction"]["factors"]`, append it with `status:"na"`; map paraphrased names toward canonical by `_norm` (case/space/hyphen) so the model's wording variants collapse onto the canonical 8 (lenient-only — cosmetic drift, not a hard rule); (c) lower/normalize enum-ish strings; (d) default `defined_risk` to `False` when absent (so the validator REJECTS rather than silently passing a naked candidate — fail-safe); (e) apply the same `_norm` (case/space/hyphen, **no alias fuzzing**) to `best_setup.structure` and each `candidates[].name` so the validator's verbatim match is drift-tolerant. Keep it small; return the mutated dict. Follow the dispatch style of the other `leniency/*` helpers.

- [ ] **Step 4: Hook into `_coerce_claude_outcome_dict`** in `trade_insights_ai_lenient.py` — in the `coerced` dict assembly, add:
  ```python
  if isinstance(data.get("framework"), dict):
      coerced["framework"] = _coerce_framework(data["framework"], candidates)
  ```
  (Import `_coerce_framework` at the top with the other leniency imports.)

- [ ] **Step 5: Run** — `uv run pytest tests/unit/reports/leniency/test_framework_coerce.py -q` → PASS.

- [ ] **Step 6: Verify + commit**

```bash
uv run pytest tests/unit/reports -q
git add src/uw_scan/reports/trade_insights_ai/validator_rules/framework.py \
        src/uw_scan/reports/trade_insights_ai/validators.py \
        src/uw_scan/reports/trade_insights_ai/leniency/framework.py \
        src/uw_scan/reports/trade_insights_ai_lenient.py \
        tests/unit/reports/validator_rules/test_framework_rules.py \
        tests/unit/reports/leniency/test_framework_coerce.py
git commit -m "feat(trade-framework): framework validator rule + lenient coercion"
```

---

# Milestone 3 — Prompt KB embedding + decision stack + version bump

Ports the trade-skills library verbatim into the prompt and bumps `PROMPT_VERSION` to `v6.0`.

**⚠️ Version-bump cascade:** `PROMPT_VERSION` is checked in three places — the worker fails+requeues rows whose `prompt_version` mismatches; the schema stamps it as `const`; the validator rejects mismatched `schema_version`. After the bump, any queued v5.3 rows get failed (expected). Bump once in `prompt_text.py` and all consumers follow.

### Task 3.1: Vendor the trade-skills KB into the package

**Files:**
- Create: `src/uw_scan/reports/trade_insights_ai/kb/` (vendored `.md` files)

- [ ] **Step 1: Copy the library verbatim** from `/Users/chenxi/projects/trade-skills/plugins/trade/skills/trade/` into `src/uw_scan/reports/trade_insights_ai/kb/`:
  - `SKILL.md` (124 lines)
  - `frameworks/gamma-framework.md`, `frameworks/strategies.md`, `frameworks/price-action-framework.md`
  - `pitfalls/01-…md` … `pitfalls/24-…md` (24 files; skip `_template.md`, keep `README.md` optional)
  - `ticker/{app,cbrs,intc,mag7,nok,snow,tsem}-*.md` (7 case studies; skip `_template.md`)
  - Total ≈ 3,170 lines / ~191 KB / ~47.7K tokens.

```bash
SRC=/Users/chenxi/projects/trade-skills/plugins/trade/skills/trade
DST=src/uw_scan/reports/trade_insights_ai/kb
mkdir -p "$DST/frameworks" "$DST/pitfalls" "$DST/ticker"
cp "$SRC/SKILL.md" "$DST/"
cp "$SRC/references/gamma-framework.md" "$SRC/references/strategies.md" \
   "$SRC/references/price-action-framework.md" "$DST/frameworks/"
cp "$SRC/references/pitfalls/"[0-9]*.md "$DST/pitfalls/"
cp "$SRC/references/ticker/"{app,cbrs,intc,mag7,nok,snow,tsem}-*.md "$DST/ticker/"
```

- [ ] **Step 2: Ensure packaging includes `*.md`.** Confirm `pyproject.toml` ships package data under `src/uw_scan/` (it lives under the package, so the editable/`uv` install picks it up; if a build `[tool.hatch.build]`/`[tool.setuptools.package-data]` glob exists, add `"reports/trade_insights_ai/kb/**/*.md"`). Record what you found.

### Task 3.2: Build the KB constant module

**Files:**
- Create: `src/uw_scan/reports/trade_insights_ai/trade_framework_kb.py`
- Test: `tests/unit/reports/test_trade_framework_kb.py`

- [ ] **Step 1: Write the failing test**

```python
def test_kb_contains_core_anchors():
    from uw_scan.reports.trade_insights_ai.trade_framework_kb import TRADE_FRAMEWORK_KNOWLEDGE
    kb = TRADE_FRAMEWORK_KNOWLEDGE
    assert "Tape" in kb and "DCF" in kb            # operating principle
    assert "Direction" in kb and "Vega" in kb and "Asymmetry" in kb  # 3 axes
    assert "TSEM" in kb or "tsem" in kb            # case study present
    assert len(kb) > 100_000                        # full library, not a stub
```

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Write the loader** (import-time concat into a module constant; deterministic order; no per-request FS read):

```python
"""Embedded trade-skills knowledge base (v6.0).

Loads the vendored markdown library at import time into a single string
constant. The model subprocess has no filesystem, so the KB must be baked
into the prompt at build time. Kept in its own module so prompt assembly
stays under the line budget (the constant is pure data, like prompt_text.py).
"""

from __future__ import annotations

from importlib import resources

_KB_DIR = resources.files(__package__).joinpath("kb")
_ORDER = [
    ("Operating principles & 3-axis framework", ["SKILL.md"]),
    ("Frameworks", ["frameworks/gamma-framework.md",
                    "frameworks/strategies.md",
                    "frameworks/price-action-framework.md"]),
    ("Pitfalls", [f"pitfalls/{name}" for name in _pitfall_files()]),  # sorted 01..24
    ("Case studies", [f"ticker/{name}" for name in _ticker_files()]),
]


def _read(rel: str) -> str:
    return _KB_DIR.joinpath(rel).read_text(encoding="utf-8")


def _build() -> str:
    parts: list[str] = ["# TRADE FRAMEWORK KNOWLEDGE (ported from trade-skills)\n"]
    for section, files in _ORDER:
        parts.append(f"\n\n## {section}\n")
        for rel in files:
            parts.append(f"\n\n### {rel}\n\n{_read(rel)}")
    return "".join(parts)


TRADE_FRAMEWORK_KNOWLEDGE = _build()
```

  Implement `_pitfall_files()` / `_ticker_files()` to list+sort the directory entries (via `resources.files(...).joinpath("pitfalls").iterdir()`), filtering to `*.md`. (Define them above `_ORDER`.)

- [ ] **Step 4: Run** — `uv run pytest tests/unit/reports/test_trade_framework_kb.py -q` → PASS.

### Task 3.3: Inject KB + framework decision-stack directives into the prompt; bump version

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai/prompt_text.py`
- Modify: `src/uw_scan/reports/trade_insights_ai/analysis_input.py`
- Test: `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py`

- [ ] **Step 1: Write the failing test**

```python
def test_prompt_includes_kb_and_framework_directives():
    from datetime import datetime, timezone
    from uw_scan.reports.trade_insights_ai import (
        build_trade_insights_ai_prompt, build_trade_insights_ai_prompt_payload, PROMPT_VERSION,
    )
    payload = build_trade_insights_ai_prompt_payload(
        {"ticker": "TEST", "prompt_version": PROMPT_VERSION},
        produced_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )
    prompt = build_trade_insights_ai_prompt(payload)
    assert "TRADE FRAMEWORK KNOWLEDGE" in prompt
    assert "best_setup" in prompt          # framework directive present
    assert PROMPT_VERSION == "trade-insights-ai-v6.0"
```

- [ ] **Step 2: Run** — FAIL (version still v5.3; no KB).

- [ ] **Step 3: Bump version** — in `prompt_text.py` line 10: `PROMPT_VERSION = "trade-insights-ai-v6.0"`.

- [ ] **Step 4: Inject the KB + framework directives** in `analysis_input.py::build_trade_insights_ai_prompt` (analysis_input.py:506-675). Add the import at top:
  ```python
  from .trade_framework_kb import TRADE_FRAMEWORK_KNOWLEDGE
  ```
  Insert the KB and a new framework-directive block into the returned f-string — place the KB after `CONTRACT_PROMPT` and before the "Integration notes" line, and append the framework-output directives near the end (before `"Emit only JSON …"`). The directives must state:
  - Produce the full decision stack into `framework{}`: `header → three_axis → gamma → catalyst → conviction → confluence → pitfalls → candidates (each with Bull/Base/Bear P/L) → best_setup → what_changes → bottom_line`.
  - **Best setup (TSEM counterfactual):** run counterfactual P/L across `candidates`; `best_setup.why_not_alternatives` must justify the pick against runners-up. High internal-vs-consensus gap → `directional_defined_risk`, not `pin_vega`; calendar/diagonal only when implied-move ÷ distance-to-short-strike ≤ ~0.75.
  - **Assertive but honest:** commit to one `best_setup`; any factor with no data is `status:"na"`, never bluffed. When core inputs (tape/flow/IV) are absent → `position_type:"stand_aside"` + "insufficient data".
  - **Earnings (swing-default, LEAPS-aware):** decide `catalyst.handling` FIRST against a fixed pre-structure ~10-14d hold window — `exit_before_print`/`stand_aside` when ER is inside it; `hold_through_leaps` only when `position_type:"leaps"`. Then pick `best_setup` consistent with it.
  - **Defined-risk only:** every `candidates[]` and `best_setup` is defined-risk (no naked shorts).
  - The conviction ledger contains **exactly the 8 canonical factors** (verbatim from the embedded KB — `references/strategies.md` / pitfall 24), each with `status:"yes"|"no"|"na"` and a `note`. Emit all 8 in this order; absent/unsourceable data → `"na"` (never a bluffed `"yes"`):
    1. `3+ independent channel checks aligned bullish` — **always `na`** (out of scope, §5.3).
    2. `Sector / thematic narrative actively re-rating` — `yes/no` from news/flow context, else `na`.
    3. `Stock down >20% from recent high (de-risked setup)` — from `tape` drawdown-from-6M-high.
    4. `Past 4 quarters: ≥3 positive earnings reactions` — from earnings history.
    5. `NEW information likely to be disclosed (new customer tier/product/guide raise/M&A)` — usually `na` (whisper/channel; reasoning-only).
    6. `Net options flow back-month bullish (call-premium dominance, 5-day rolling)` — from `flow_series`.
    7. `Short interest >10% (squeeze potential)` — from `positioning` SI% float.
    8. `Implied move materially below recent realized average` — from `vol` IV-vs-RV.
    Factors 1 and 5 are structurally `na` here → realistic ceiling ≈ 6/8. `header.conviction_n` MUST equal `conviction.score` MUST equal the count of `conviction.factors` with `status:"yes"` (so `score ∈ 0..8`). `asymmetry.rule_on` ⟺ `conviction.score >= 4` (both directions).
  - `header.position_type:"stand_aside"` ⟺ `best_setup.structure:"stand_aside"` (the overall stance and the chosen setup must agree on whether a trade is entered now).
  - **Candidate naming (so verbatim best_setup match is robust):** each `candidates[].name` MUST be a generic strategy identifier (e.g. `"bull put spread"`, `"call debit spread"`, `"iron condor"`) — put all strikes / expirations / ratios in the `legs` array, NOT in `name`. `best_setup.structure` then echoes the chosen candidate's `name` **exactly** (or the literal `"stand_aside"`).
  - `best_setup.structure` is exactly one of `candidates[].name` OR the literal `"stand_aside"`.

- [ ] **Step 5: Run** — `uv run pytest tests/unit/reports/test_trade_insights_ai_prompt_assembly.py -q` → PASS.

### Task 3.4: Prompt-size measurement gate (spec §13 risk)

**Files:**
- Test: `tests/unit/reports/test_prompt_size_budget.py`

- [ ] **Step 1: Measure the assembled prompt size** with a realistic payload and assert headroom. Confirm each provider's context window from current docs (WebFetch the provider docs — do not guess):
  - Claude (`claude --print`, Opus/Sonnet): 200K tokens.
  - Codex (`gpt-5.x`): confirm ≥ 200K.
  - DeepSeek (`deepseek-v4-pro`): **WebFetch `https://api-docs.deepseek.com`** for the v4-pro context window. The current system already sends ~350 KB prompts to all three (worker CLAUDE.md), so large-context is established; the KB adds ~191 KB.

```python
def test_assembled_prompt_within_budget():
    # build a representative payload (reuse an existing fixture), assemble the prompt,
    # assert byte length < an agreed ceiling (record the measured size in the test).
    ...
```

- [ ] **Step 2: Decision gate (record outcome in the test/commit message).** If measured tokens exceed any provider's confirmed context window: trim the **case studies** first (largest chunk, ~22K tokens) for that provider's path only — never trim pitfalls/frameworks (the core judgment). Default (expected): full KB fits all three; no trim. **Do not silently truncate** — if you trim, `log`/document which files were dropped and for which provider.

- [ ] **Step 3: Verify + commit**

```bash
uv run pytest tests/unit/reports -q
git add src/uw_scan/reports/trade_insights_ai/kb \
        src/uw_scan/reports/trade_insights_ai/trade_framework_kb.py \
        src/uw_scan/reports/trade_insights_ai/prompt_text.py \
        src/uw_scan/reports/trade_insights_ai/analysis_input.py \
        tests/unit/reports/test_trade_framework_kb.py \
        tests/unit/reports/test_trade_insights_ai_prompt_assembly.py \
        tests/unit/reports/test_prompt_size_budget.py \
        pyproject.toml
git commit -m "feat(trade-framework): embed trade-skills KB + framework directives, bump prompt to v6.0"
```

---

# Milestone 4 — Data layer T1 (UW positioning)

New UW fetchers on our tier → persisted tables → uw-role daily refresh job. **Before writing each fetcher, read `docs/uw-samples/unusual_whales_api.md` + the matching sample JSON to confirm the exact path and response field names** (CLAUDE.md rule — do not guess field names).

### Task 4.0: Confirm endpoint paths + shapes from uw-samples

- [ ] Read `docs/uw-samples/unusual_whales_api.md` and `docs/uw-samples/unusual_whales_api_spec.yaml` for: short interest float (`/api/shorts/{ticker}/interest-float`), analyst ratings (`/api/screener/analysts`), institutional ownership (`/api/institution/{ticker}/ownership`), insider flow (`/api/insider/{ticker}/ticker-flow`), economic calendar (`/api/market/economic-calendar`), earnings (`/api/earnings/{ticker}`). Record the exact path templates + the response field names you will extract. If any sample JSON exists under `docs/uw-samples/*.json`, prefer it as the field-name source of truth. **Confirm the earnings source yields the forward `next_er_date`** (the catalyst section needs it); if `/api/earnings/{ticker}` is history-only, source `next_er_date` from the existing stock/ticker payload and mark `na` if absent.

### Task 4.1: Add endpoint slugs

**Files:**
- Modify: `src/uw_scan/api/endpoints.py`
- Test: `tests/unit/test_endpoints.py` (extend if present)

- [ ] **Step 1:** Add to `EndpointSlug` (endpoints.py:14-40) and `REGISTRY` (endpoints.py:50-149), following the existing `Endpoint(slug, path_template, required_params)` shape. Use the paths confirmed in 4.0, e.g.:
  ```python
  SHORT_INTEREST_FLOAT = "short_interest_float"   # "/api/shorts/{ticker}/interest-float"
  ANALYST_RATINGS      = "analyst_ratings"        # "/api/screener/analysts"
  INSTITUTION_OWNERSHIP= "institution_ownership"  # "/api/institution/{ticker}/ownership"
  INSIDER_TICKER_FLOW  = "insider_ticker_flow"    # "/api/insider/{ticker}/ticker-flow"
  ECONOMIC_CALENDAR    = "economic_calendar"      # "/api/market/economic-calendar"
  EARNINGS             = "earnings"               # "/api/earnings/{ticker}"  (verify not already integrated)
  ```
- [ ] **Step 2:** Test `build_path(EndpointSlug.SHORT_INTEREST_FLOAT, "NVDA")` returns the expected path. Run → PASS.

### Task 4.2: Migration `065_uw_positioning.sql`

**Files:**
- Create: `src/uw_scan/storage/migrations/065_uw_positioning.sql`

- [ ] **Step 1:** Write idempotent DDL. One table per domain (or a wide `uw_positioning` snapshot table keyed by `(ticker, snapshot_date)`), each row timestamped (`fetched_at timestamptz default now()`) for the freshness-TTL check. Columns from 4.0's confirmed fields. Example skeleton (adjust columns to verified fields):
  ```sql
  CREATE TABLE IF NOT EXISTS uw_scan.uw_positioning (
    ticker text NOT NULL,
    snapshot_date date NOT NULL,
    si_pct_float numeric, analyst_buy int, analyst_hold int, analyst_sell int,
    analyst_target_avg numeric, analyst_target_hi numeric, analyst_target_lo numeric,
    inst_ownership_pct numeric, insider_net_flow numeric,
    raw_jsonb jsonb, fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, snapshot_date)
  );
  ```
- [ ] **Step 2:** `bash scripts/migrate.sh` against a scratch DB; run twice → second run is a no-op. Record output.

### Task 4.3: Storage mixin

**Files:**
- Create: `src/uw_scan/storage/positioning.py`
- Modify: `src/uw_scan/storage/repository.py`
- Test: `tests/integration/storage/test_positioning_storage.py`

- [ ] **Step 1: Write the failing integration test** (pytest-postgresql, real DB) — upsert a positioning row, read it back, assert round-trip + `ON CONFLICT` overwrite.
- [ ] **Step 2:** Implement `_PositioningMixin` (pattern = `storage/flow.py::_FlowMixin`: `_conn`/`_schema` class attrs; `upsert_uw_positioning(...)` with `ON CONFLICT (ticker, snapshot_date) DO UPDATE`; `get_uw_positioning(ticker) -> dict | None`).
- [ ] **Step 3:** Add `_PositioningMixin` to the `Repository(...)` base list + re-export in `repository.py` (mirror the `_FlowMixin` lines).
- [ ] **Step 4:** Run → PASS.

### Task 4.4: Fetchers + normalize

**Files:**
- Modify: `src/uw_scan/sources/uw.py`
- Modify: `src/uw_scan/normalize.py`
- Test: `tests/unit/sources/test_uw_positioning_fetchers.py`

- [ ] **Step 1: Write the failing test** — feed a recorded sample payload (from `docs/uw-samples/`), assert the normalize function returns the typed values; assert `NormalizationError` on a malformed payload.
- [ ] **Step 2:** Implement each fetcher following `sources/uw.py::fetch_flow_alerts` (call `_fetch_json(client, repo, run_id, EndpointSlug.X, ticker, params=...)` → `normalize.normalize_X(body)`). Add `normalize_*` functions for each.
- [ ] **Step 3:** Run → PASS.

### Task 4.5: Worker job + scheduler wiring

**Files:**
- Create: `src/uw_scan/worker/jobs/positioning_jobs.py`
- Modify: `src/uw_scan/worker/scheduler.py`
- Modify: `src/uw_scan/config.py`
- Test: `tests/integration/worker/test_positioning_job.py`

- [ ] **Step 1: Write the failing integration test** — run the job once against a fake UW client returning sample payloads; assert rows persisted; assert idempotent on re-run; assert it respects the shard `ticker_filter`.
- [ ] **Step 2:** Implement `positioning_refresh_once(repo, client, *, ticker_filter=None)` (pattern = `jobs/ohlc_pull.py::ohlc_pull_once`: iterate `repo.list_active_watchlist()`, skip outside shard, fetch+upsert per ticker, `logger.exception` on per-ticker failure, return count). **Daily cadence — NOT folded into `full_scan`** (avoids multiplying scan-loop UW QPS).
- [ ] **Step 3:** Add `positioning_refresh_cron` to `config.py` (default e.g. `"0 6 * * 0-4"` ET) following the SecretStr/env-read pattern. Register in `scheduler.py` under `if "uw" in groups:` with `CronTrigger.from_crontab(settings.positioning_refresh_cron, timezone=settings.rth_tz)` (mirror the `full_scan` registration; respect the per-worker shard filter).
- [ ] **Step 4:** Run → PASS.

- [ ] **Step 5: Commit**

```bash
uv run pytest tests/unit/sources tests/integration/storage/test_positioning_storage.py tests/integration/worker/test_positioning_job.py -q
git add src/uw_scan/api/endpoints.py src/uw_scan/sources/uw.py src/uw_scan/normalize.py \
        src/uw_scan/storage/positioning.py src/uw_scan/storage/repository.py \
        src/uw_scan/storage/migrations/065_uw_positioning.sql \
        src/uw_scan/worker/jobs/positioning_jobs.py src/uw_scan/worker/scheduler.py \
        src/uw_scan/config.py tests/unit/sources tests/integration/storage tests/integration/worker
git commit -m "feat(trade-framework): UW positioning fetchers + storage + daily refresh job"
```

---

# Milestone 5 — Data layer T2 (massive fundamentals)

Polygon-shaped fundamentals client → persisted tables → massive-role nightly refresh. `MASSIVE_API_KEY` already in `config.py` (may be unset — job no-ops + warns, never crashes).

### Task 5.1: Confirm massive endpoints

- [ ] Read `docs/research/goyal-saretto-ipca-options/09-massive-fundamentals-coverage.md` + `https://massive.com/docs/llms.txt` to confirm the exact paths: `/vX/reference/financials`, `…/fundamentals/float`, `…/corporate-actions/{dividends,splits}`. Record path templates + response field names. (Rates backdrop: **prefer reusing `storage/rates_repository.py` / the FRED gold source** where it covers 10Y nominal + breakevens; only fall back to massive `…/economy/{treasury-yields,inflation-expectations}` for gaps — decide here and record.)

### Task 5.2: Migration + client + storage + job (TDD, mirror Milestone 4)

**Files:**
- Create: `src/uw_scan/storage/migrations/066_massive_fundamentals.sql`
- Create: `src/uw_scan/sources/massive_fundamentals.py`
- Create: `src/uw_scan/storage/fundamentals.py`
- Modify: `src/uw_scan/storage/repository.py`, `src/uw_scan/worker/scheduler.py`, `src/uw_scan/config.py`
- Create: `src/uw_scan/worker/jobs/fundamentals_jobs.py`
- Tests: `tests/unit/sources/test_massive_fundamentals.py`, `tests/integration/storage/test_fundamentals_storage.py`, `tests/integration/worker/test_fundamentals_job.py`

- [ ] **Step 1:** Migration `066` — `massive_fundamentals` table keyed `(ticker, period_end)` with revenue, gross/op/net margin, fcf, total_debt, share_count_delta, float, plus `dividends`/`splits` (own tables or columns), `raw_jsonb`, `fetched_at`. Idempotent. `migrate.sh` ×2 → no-op.
- [ ] **Step 2:** `MassiveFundamentalsProvider` — pattern = `sources/ohlc.py::MassiveOhlcProvider` (httpx.Client, `Authorization: Bearer {api_key}`, base `https://api.massive.com`). One request method per endpoint; raise on non-2xx; parse Polygon-shaped `results`. Write the failing unit test first (sample payload → typed values).
- [ ] **Step 3:** `_FundamentalsMixin` (pattern = `_FlowMixin`); add to `Repository` + re-export. Failing integration test first (round-trip).
- [ ] **Step 4:** `fundamentals_refresh_once(repo, provider, *, ticker_filter=None)` (pattern = `ohlc_pull_once`); **nightly cadence**, massive role. If `provider is None` (no `MASSIVE_API_KEY`) → no-op + warn. Failing integration test first. Add `fundamentals_refresh_cron` to `config.py` (e.g. `"0 19 * * 0-4"` ET, after `ohlc_pull`); register in `scheduler.py` under `if "massive" in groups:`.
- [ ] **Step 5:** Run all M5 tests → PASS.

- [ ] **Step 6: Commit**

```bash
uv run pytest tests/unit/sources/test_massive_fundamentals.py tests/integration/storage/test_fundamentals_storage.py tests/integration/worker/test_fundamentals_job.py -q
git add src/uw_scan/storage/migrations/066_massive_fundamentals.sql \
        src/uw_scan/sources/massive_fundamentals.py src/uw_scan/storage/fundamentals.py \
        src/uw_scan/storage/repository.py src/uw_scan/worker/jobs/fundamentals_jobs.py \
        src/uw_scan/worker/scheduler.py src/uw_scan/config.py \
        tests/unit/sources/test_massive_fundamentals.py tests/integration/storage tests/integration/worker
git commit -m "feat(trade-framework): massive fundamentals client + storage + nightly refresh job"
```

---

# Milestone 6 — Payload enrichment

Wire the new tables + already-plumbed signals + tape derivations into the AI payload. Every section is `na`-tolerant (emit `null` + an availability flag).

### Task 6.1: Tape deriver

**Files:**
- Create: `src/uw_scan/cards/framework_tape.py`
- Test: `tests/unit/cards/test_framework_tape.py`

- [ ] **Step 1: Write the failing test** — feed stored OHLCV rows, assert derived: 3-close trend, nearest S/R + touch counts, 50/200-DMA, drawdown-from-6M-high, volume vs 5d/30d (distribution-day flag), 5d pre-earnings run, post-earnings gap. Empty input → all-`None` (na), no crash.
- [ ] **Step 2:** Implement `derive_framework_tape(ohlcv_rows, *, next_earnings_date=None) -> dict` — pure function, `Decimal` math, returns numbers (the model never computes these).
- [ ] **Step 3:** Run → PASS.

### Task 6.2: Add payload sections

**Files:**
- Modify: `src/uw_scan/reports/trade_insights_ai/analysis_input.py`
- Test: `tests/unit/reports/test_analysis_input_framework_sections.py`

- [ ] **Step 1: Write the failing test** — call `build_trade_insights_ai_analysis_input` with new kwargs and assert the payload carries `positioning` (SI%/analysts/inst-own/insider), `fundamentals`, `macro` (VIX, hours-to-next-print + suppression flag, rates backdrop), `flow_series` (multi-day net call−put premium + 3-day persistence), `tape`; and that absent inputs produce `null` + availability flags (not omitted, not fabricated).
- [ ] **Step 2:** Extend `build_trade_insights_ai_analysis_input` (analysis_input.py:217) with new params (`positioning_payload`, `fundamentals_payload`, `macro_payload`, `ohlcv_rows`) and add the bounded sections to the returned dict. Apply freshness TTL: mark `na` when stale (~100d fundamentals, ~5 trading days positioning, ~1d macro/VIX) using the stored `fetched_at`. `net_call_premium`/`net_put_premium` + VIX are already persisted — read them; do not re-fetch.
- [ ] **Step 3:** Update the POST caller (the router/report path that calls `build_trade_insights_ai_analysis_input` — grep for it) to pass the new payloads from `repo.get_uw_positioning(...)`, `repo.get_massive_fundamentals(...)`, the macro/VIX reads, and stored OHLCV. (These are request-time reads from the warm store, per the R2-vs-warm-store rule: API request-time reads hit Postgres.) Also pass `next_er_date` (from the earnings source / existing payload) into `derive_framework_tape` and the `catalyst` payload section, and derive `implied_move` from the ATM straddle of the expiry bracketing earnings (T0 chain/IV) — not fetched; if `next_er_date` is unavailable the `catalyst` section degrades to `na`.
- [ ] **Step 4:** Run → PASS. Also re-run `tests/unit/reports/test_trade_insights_ai_prompt_assembly.py` (payload changed) → PASS.

- [ ] **Step 5: Commit**

```bash
uv run pytest tests/unit/cards/test_framework_tape.py tests/unit/reports -q
git add src/uw_scan/cards/framework_tape.py src/uw_scan/reports/trade_insights_ai/analysis_input.py \
        tests/unit/cards tests/unit/reports
git commit -m "feat(trade-framework): enrich AI payload with positioning + fundamentals + macro + tape"
```

---

# Milestone 7 — Frontend Framework view

Rewire the `trade-plan` route to a client island that polls per-provider (3-way) and renders the decision stack. Reuses the existing polling hook, fold pattern, and SVG helpers. **No new endpoint** — `framework{}` rides inside the existing `/latest` outcome.

### Task 7.1: Extend the polling hook + API client to 3 providers

**Files:**
- Modify: `web/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling.ts`
- Modify: `web/lib/api.ts`
- Test: `web/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling.test.ts` (extend)

- [ ] **Step 1:** Change `PROVIDERS` (useAiAnalysisPolling.ts:14) to `["codex", "claude", "deepseek"] as const`. Update `EMPTY_LATEST`/`EMPTY_PENDING` to include `deepseek`. The `TradeInsightAiLatestPair` type already has a `deepseek` field, so `latestForTicker.deepseek` is valid.
- [ ] **Step 2:** Update `api.ts::tradeInsightsAiAnalysis` body type `providers?: ("codex"|"claude")[]` → add `"deepseek"`.
- [ ] **Step 3:** Note the **intended cross-effect**: this lights up a `[DeepSeek]` tab in the existing audit panel too (the model docstring anticipated this). Verify the audit panel renders DeepSeek without error (it already handles per-provider state). Add/extend a vitest asserting the hook now tracks 3 providers. Run `cd web && npm run test -- --run useAiAnalysisPolling` → PASS.

### Task 7.2: Build the FrameworkTab client island

**Files:**
- Create: `web/components/stock/tabs/FrameworkTab.tsx`
- Create: `web/components/stock/tabs/framework/{Header,ThreeAxis,Gamma,Catalyst,Conviction,Confluence,Pitfalls,Candidates,BestSetup,WhatChanges}.tsx`
- Modify: `web/app/stock/[ticker]/[tab]/page.tsx`
- Test: `web/components/stock/tabs/FrameworkTab.test.tsx`

- [ ] **Step 1: Write the failing vitest** — render `FrameworkTab` with a mocked `useAiAnalysisPolling` returning a succeeded framework for codex, a failed claude, and a null deepseek; assert: provider toggle shows 3 tabs with state badges; the active provider renders the decision stack ending in best_setup; `na` factors render as `na` (not blank); the consensus banner shows "single provider" when <2 have a framework.
- [ ] **Step 2: Rewire the route.** In `page.tsx`, remove `"trade-plan": TradePlanTab` from `REPORT_TABS` and add a special-case (like `trade-insights`) before the `REPORT_TABS` lookup:
  ```tsx
  if (tab === "trade-plan") return <FrameworkTab ticker={ticker} gexCurve={report?.gex_profile ?? null} />;
  ```
  (FrameworkTab is a client island taking `ticker` — it polls for the `framework{}`. `gexCurve` is an
  **optional read-only** prop: the RSC `page.tsx` already has `report`, so it passes the existing GEX-profile
  series purely as a static backdrop for the gamma section. The framework data itself still comes from polling;
  `gexCurve` is never required.)
- [ ] **Step 3: Implement `FrameworkTab.tsx`** (`"use client"`) — call `useAiAnalysisPolling(ticker)`; render a `[Codex] [Claude] [DeepSeek]` toggle (reuse/extend `ProviderTabBar`); per active provider, render `framework{}` from `latestForTicker[provider]?.outcome?.framework`; show explicit state (queued/running/failed/stale/null-framework) with a badge + reason, never blank; a consensus banner on top comparing `header.position_type` + `best_setup.structure` family across the providers that have a framework (require ≥2; else "single provider").
- [ ] **Step 4: Implement the section components** — collapsible sections (reuse the fold pattern from `VcgStressHistorySection.tsx`: `useState(true)`, chevron, `section-header`/`section-body`). Order mirrors the spine. Conviction renders `●●●●○○○○ N/8` with per-factor `yes/no/na` tooltips. Gamma overlays the framework's flip/call-wall/put-wall markers (from `framework.gamma`) on the optional `gexCurve` backdrop via `web/lib/svgChart.ts` (`finiteDomain` → `linearScale` → `pathFromPoints` for the curve when `gexCurve` is present; a vertical line at the flip strike + wall markers either way). When `gexCurve` is null, render the three markers on a bare price axis — do NOT fabricate a curve series (the `framework.gamma` block carries only the 3 strike points, not a series). Best-setup is the visual climax (structure, legs, cost, max-risk, invalidation). DeepSeek `reasoning_content` (from `latest.deepseek.outcome` / `provider_metadata`) → optional collapsible "model reasoning" beneath `bottom_line`, off by default. Argon dark theme; `MetricGrid`/`DataTable`/`sectionHeading` primitives.
- [ ] **Step 5:** Run `cd web && npm run test -- --run FrameworkTab` → PASS. `cd web && npm run typecheck` → clean.

### Task 7.3: Playwright tab interaction

**Files:**
- Test: `web/tests/e2e/framework-tab.spec.ts` (or the repo's e2e location)

- [ ] **Step 1:** Add a Playwright test: navigate to `/stock/<ticker>/trade-plan`, assert the 3-way toggle, fold expand/collapse, and best_setup render. Screenshots → `output/playwright/`.
- [ ] **Step 2:** Run the spec (against the dev stack). Record pass/fail. If the UI can't be exercised headless in this environment, disclose it explicitly rather than claiming green.

- [ ] **Step 3: Commit**

```bash
cd web && npm run typecheck && npm run test -- --run
cd /Users/chenxi/projects/unusual-whales/.worktrees/feat-trade-framework-view
git add web/components/stock/panels/tradeInsightsAi web/lib/api.ts \
        web/components/stock/tabs/FrameworkTab.tsx web/components/stock/tabs/framework \
        web/app/stock/[ticker]/[tab]/page.tsx web/tests
git commit -m "feat(trade-framework): Framework tab client island (3-way provider, decision stack)"
```

---

# Milestone 8 — Remove the deterministic trade plan

Scoped, deliberate API contract change. **Keep** `setup`/`SetupClassification` (powers watchlist + scanner).

### Task 8.1: Confirm dead-code status, then delete producers

**Files:**
- Modify: `src/uw_scan/reports/single_stock.py`
- Modify: `src/uw_scan/models/stock.py`

- [ ] **Step 1:** `git grep -n "build_trade_plan_for_report\|_build_trade_plan\|\.trade_plan\|trade_plan=" src web tests` — enumerate all callers. The report already sets `trade_plan=None` (single_stock.py:588), so `build_trade_plan_for_report` may be dead. Confirm before deleting.
- [ ] **Step 2:** Delete `_build_trade_plan` (single_stock.py:293-415) and `build_trade_plan_for_report` (single_stock.py:607-615); remove the `trade_plan=None` kwarg from the `SingleStockReport(...)` constructor (single_stock.py:588); remove `TradePlan`/`TradePlanLeg` from the `from ..models import (...)` block (single_stock.py:29-30).
- [ ] **Step 3:** In `models/stock.py`, delete `class TradePlanLeg` (stock.py:63-72) and `class TradePlan` (stock.py:73-78) and the `trade_plan: TradePlan | None = None` field on `SingleStockReport` (stock.py:115). Remove `TradePlan`/`TradePlanLeg` from `models/__init__.py` imports + `__all__`.
- [ ] **Step 4:** Delete the old `web/components/stock/tabs/TradePlanTab.tsx` (now superseded by `FrameworkTab.tsx`) and remove its import from `page.tsx`.

### Task 8.2: Update tests + regenerate contract

**Files:**
- Modify: `tests/unit/test_models_exports.py`, `tests/unit/test_report_assembly.py`
- Modify: `tests/integration/api/openapi.snapshot.json`, `web/lib/types.ts`

- [ ] **Step 1:** Remove `"TradePlan"`/`"TradePlanLeg"` from `tests/unit/test_models_exports.py` (lines 33-34) — leaving the Milestone-1 framework additions intact.
- [ ] **Step 2:** Remove/replace the `assert report.trade_plan is None` at `tests/unit/test_report_assembly.py:328`.
- [ ] **Step 3:** Regenerate OpenAPI snapshot + types:
  ```bash
  uv run pytest tests/integration/api -q -k openapi   # will fail until regenerated
  # regenerate the snapshot per the repo's snapshot-refresh mechanism, then:
  cd web && npm run gen:types
  ```
  Confirm `web/lib/types.ts` drops `TradePlan`/`TradePlanLeg` and gains `TradeFramework*`. Confirm no other response model embeds `TradePlan` (grep).
- [ ] **Step 4:** Run `uv run pytest tests/unit/test_models_exports.py tests/unit/test_report_assembly.py tests/integration/api -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/uw_scan/reports/single_stock.py src/uw_scan/models/stock.py src/uw_scan/models/__init__.py \
        web/components/stock/tabs/TradePlanTab.tsx web/app/stock/[ticker]/[tab]/page.tsx \
        tests/unit/test_models_exports.py tests/unit/test_report_assembly.py \
        tests/integration/api/openapi.snapshot.json web/lib/types.ts
git commit -m "feat(trade-framework): remove deterministic trade_plan (scoped contract change)"
```

---

# Milestone 9 — Integration, real-path smoke, final contract sync

### Task 9.1: End-to-end integration (pytest-postgresql, no mocked DB)

**Files:**
- Test: `tests/integration/worker/test_framework_end_to_end.py`

- [ ] **Step 1: Write the test** — enqueue an analysis for all three providers (use fake/stub runners returning framework-bearing outcomes); assert the worker produces `framework{}` for each, the framework validator passes (defined-risk, conviction linkage), `/latest` returns `framework{}` per provider, and the provider CHECK constraint still passes. Include a row where Claude omits `framework` → validator skips, frontend would show null-state.
- [ ] **Step 2:** Run → PASS.

### Task 9.2: Real-path smoke (standing rule — API→DB→worker→DB→UI, no /tmp side-channel)

- [ ] **Step 1:** Bring up the dev stack (`bash scripts/dev.sh`), POST a real analysis for one watchlist ticker, let the `ai-codex`/`ai-claude`/`ai-deepseek` workers process it, and open `/stock/<ticker>/trade-plan` in the browser. Confirm the Framework decision stack renders per provider ending in a decisive `best_setup` (or `stand_aside`). Screenshot → `output/playwright/`. If a provider key/CLI is unavailable in this environment, disclose which leg was not exercised.

### Task 9.3: Final contract + full-suite sync

- [ ] **Step 1:** `cd web && npm run gen:types` (idempotent — diff should be empty after Milestone 8). `uv run pytest -q` (full suite). `cd web && npm run typecheck && npm run test -- --run`.
- [ ] **Step 2:** Re-verify standing rules: no naked shorts (validator green), no Yahoo, no secrets to subprocesses (UW/massive fetch only in worker jobs), analytical results persisted (fundamentals/positioning tables). Migrations idempotent (`migrate.sh` ×2).

- [ ] **Step 3: Commit (if anything changed) + open PR**

```bash
git add -A
git commit -m "test(trade-framework): end-to-end integration + final contract sync"
git push -u origin feat/trade-framework-view
gh pr create --base main --title "feat: AI-driven Trade Framework view (ports trade-skills)" \
  --body "Implements docs/superpowers/specs/2026-05-29-trade-framework-view-design.md. Replaces the deterministic trade-plan tab with a per-provider (Codex/Claude/DeepSeek) AI Framework decision stack. Additive framework{} on TradeInsightAiOutcome (no migration/endpoint for the contract); new UW positioning + massive fundamentals data layer (migrations 065/066); deterministic trade_plan removed (scoped contract change). Module-budget note: trade_framework_kb is a pure-data constant module."
```
(Never `git push origin main`. No `Co-Authored-By` trailer.)

---

## Self-Review (planner — checked against the spec)

**Spec coverage:** §4 architecture → M1-M9. §5 data layer → M4 (T1)/M5 (T2), T0 derivations → M6.1 tape + M6.2 already-plumbed reads. §6 payload → M6. §7 prompt KB + decision stack → M3. §8 output contract → M1 (model/schema) + M2 (validator/leniency), persistence (no migration) confirmed. §9 frontend → M7. §10 removal → M8. §11 testing → tests in every milestone + M9. §12 sequencing → reordered to contract-first (dependency-sound; noted below). §13 risks → M3.4 prompt-size gate; na-degradation in M6; TTL in M4.2/M5/M6. §14 success criteria → M9.2 smoke.

**Sequencing deviation from spec §12:** spec suggested data-layer-first; this plan does **contract-first** (M1-M3) then data (M4-M6) then frontend/removal. Rationale: the payload (M6), frontend (M7), and prompt (M3) all reference the `framework{}` shape, so establishing the contract first lets every later test assert against a fixed shape. The data layer (M4/M5) is independent of the contract and could equally run first — either order ships.

**Type consistency:** `TradeFramework` field names in M1 ↔ validator field access in M2 ↔ prompt directives in M3 ↔ frontend reads in M7 all use the same names (`header.conviction_n`, `conviction.score`, `conviction.factors[].status`, `best_setup.structure`, `candidates[].defined_risk`, `catalyst.handling`, `three_axis.asymmetry.rule_on`). `PROMPT_VERSION = "trade-insights-ai-v6.0"` used consistently across schema const, validator check, and worker requeue.

**Placeholder scan:** Data-layer fetcher/storage code is pattern-anchored (exact file:line of the canonical example + the unique slug/SQL/columns) rather than reproduced verbatim, because the exact UW/massive response field names MUST be confirmed from `docs/uw-samples/` + `09-massive-fundamentals-coverage.md` at implementation time (Tasks 4.0/5.1) — inventing them here would violate the no-fabrication rule. All novel/central code (framework model, validator, leniency, KB loader, prompt directives, frontend tab) is given in full.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-29-trade-framework-view.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration (superpowers:subagent-driven-development).
2. **Inline Execution** — execute tasks in this session with checkpoints (superpowers:executing-plans).
