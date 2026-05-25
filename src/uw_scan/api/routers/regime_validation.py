"""Read-only endpoints for the /regime/validation sub-page + guidance.

GET /api/regime/validation — returns the warm-store backtest markdown +
  CSV row count + a hand-curated OOS summary loaded from
  docs/research/regime/oos-summary.json.

GET /api/regime/guidance — added in a follow-on commit (T9). Returns the
  active regime-state guidance rule selected from
  docs/research/regime/guidance.md based on the current CRI snapshot.
"""

from __future__ import annotations

import ast
import csv
import logging
import operator as _op
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, HTTPException

from uw_scan.api.deps import get_repo
from uw_scan.api.models.regime_validation import (
    GuidanceResponse,
    OosSummary,
    ValidationResponse,
)
from uw_scan.cards.cri_scorers import COMPOSITE_VERSION as CRI_COMPOSITE_VERSION
from uw_scan.reports.regime_backtest_report import render_backtest_markdown
from uw_scan.storage.cri_snapshot_repository import CriSnapshotRepository
from uw_scan.storage.regime_backtest_repository import RegimeBacktestRepository
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/regime", tags=["regime"])

# src/uw_scan/api/routers/regime_validation.py
# parents[0]=routers  [1]=api  [2]=uw_scan  [3]=src → .parent = repo root
_DOCS_REGIME = (
    Path(__file__).resolve().parents[3].parent / "docs" / "research" / "regime"
).resolve()


def _safe_doc_path(filename: str) -> Path:
    """Resolve docs/research/regime/<filename> with four guards.

    1. No directory components in `filename`.
    2. The literal path must NOT be a symlink (check BEFORE resolve —
       resolve follows links and erases the symlink-ness).
    3. Resolved target stays within `_DOCS_REGIME` (defense in depth).
    4. Resolved target is a regular file.
    """
    if "/" in filename or filename.startswith("."):
        raise HTTPException(400, f"invalid filename: {filename!r}")
    raw = _DOCS_REGIME / filename
    if raw.is_symlink():
        raise HTTPException(404, f"{filename}: not a regular file (symlink)")
    if not raw.exists():
        raise HTTPException(404, f"{filename}: not found")
    candidate = raw.resolve()
    if not candidate.is_relative_to(_DOCS_REGIME):
        raise HTTPException(400, "path escapes docs/research/regime/")
    if not candidate.is_file():
        raise HTTPException(404, f"{filename}: not a regular file")
    return candidate


def _read_oos_summary() -> OosSummary | None:
    try:
        path = _safe_doc_path("oos-summary.json")
    except HTTPException as exc:
        if exc.status_code == 404:
            return None
        raise
    try:
        return OosSummary.model_validate_json(path.read_text())
    except Exception as exc:
        raise HTTPException(500, f"oos-summary.json malformed: {exc!r}") from exc


def _count_csv_rows(filename: str) -> int:
    try:
        path = _safe_doc_path(filename)
    except HTTPException as exc:
        if exc.status_code == 404:
            return 0
        raise
    with path.open() as f:
        return sum(1 for _ in csv.DictReader(f))


# ── AST-whitelist evaluator (security boundary) ──────────────────────
#
# Why the AST whitelist (not eval): eval with empty __builtins__ is
# sandbox-escapable (subclass-walk attacks are well-documented). The
# conditions live in a checked-in markdown file, but that file is
# editable by anyone with repo write access — a typo or a malicious PR
# shouldn't be able to RCE. The whitelist parses one Python expression
# and rejects every node type that isn't in the allowed set, so the
# worst a bad condition can do is raise ValueError.

_CMP_OPS: dict[type[ast.cmpop], Any] = {
    ast.Eq: _op.eq,
    ast.NotEq: _op.ne,
    ast.Lt: _op.lt,
    ast.LtE: _op.le,
    ast.Gt: _op.gt,
    ast.GtE: _op.ge,
    ast.Is: _op.is_,
    ast.IsNot: _op.is_not,
}
_BOOL_OPS: dict[type[ast.boolop], Any] = {
    ast.And: lambda values: all(values),
    ast.Or: lambda values: any(values),
}
_UNARY_OPS: dict[type[ast.unaryop], Any] = {ast.Not: _op.not_}


def _eval_node(node: ast.AST, ctx: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body, ctx)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, str, bool)) or node.value is None:
            return node.value
        raise ValueError(f"constant type {type(node.value).__name__} forbidden")
    if isinstance(node, ast.Name):
        if node.id in ctx:
            return ctx[node.id]
        raise ValueError(f"unknown name {node.id!r}")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, ctx)
        result = True
        for op_node, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval_node(comparator, ctx)
            fn = _CMP_OPS.get(type(op_node))
            if fn is None:
                raise ValueError(f"forbidden compare op {type(op_node).__name__}")
            result = result and fn(left, right)
            left = right
        return result
    if isinstance(node, ast.BoolOp):
        fn = _BOOL_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"forbidden bool op {type(node.op).__name__}")
        return fn(_eval_node(v, ctx) for v in node.values)
    if isinstance(node, ast.UnaryOp):
        fn = _UNARY_OPS.get(type(node.op))
        if fn is None:
            raise ValueError(f"forbidden unary op {type(node.op).__name__}")
        return fn(_eval_node(node.operand, ctx))
    raise ValueError(f"forbidden node {type(node).__name__}")


def _evaluate_condition(expr: str, ctx: dict[str, Any]) -> bool:
    tree = ast.parse(expr, mode="eval")
    return bool(_eval_node(tree, ctx))


def _parse_guidance_md() -> list[dict[str, Any]]:
    """Split guidance.md on `---` separators; load YAML frontmatter + body."""
    try:
        path = _safe_doc_path("guidance.md")
    except HTTPException as exc:
        if exc.status_code == 404:
            return []
        raise
    text = path.read_text()
    chunks = [c.strip() for c in text.split("\n---\n")]
    if chunks and chunks[0].startswith("---"):
        chunks[0] = chunks[0].lstrip("-").strip()
    rules: list[dict[str, Any]] = []
    i = 0
    while i + 1 < len(chunks):
        front_raw, body = chunks[i], chunks[i + 1]
        if not front_raw or not body:
            i += 2
            continue
        try:
            meta = yaml.safe_load(front_raw) or {}
        except yaml.YAMLError as exc:
            logger.warning("guidance_yaml_skipped chunk=%d err=%s", i, repr(exc))
            i += 2
            continue
        if isinstance(meta, dict) and {"state", "condition", "posture"} <= meta.keys():
            meta["body_md"] = body
            rules.append(meta)
        i += 2
    return rules


def _select_rule(
    rules: list[dict[str, Any]], snapshot: dict[str, Any]
) -> dict[str, Any] | None:
    """First rule whose condition evaluates True against the snapshot.

    Missing optional fields stay None, not 0.0. Coercing vix_vix3m_ratio
    to 0.0 when VIX3M is absent would falsely match the low_contango
    rule and serve a confident "premium-selling friendly" guidance for a
    snapshot whose term structure is literally unknown. None propagates
    through comparisons as TypeError, which we catch and skip — so the
    fall-through correctly lands on a level-only rule.
    """
    cri_block = snapshot.get("cri") or {}
    ctx: dict[str, Any] = {
        "level": cri_block.get("level", "LOW"),
        "vix_vix3m_ratio": snapshot.get("vix_vix3m_ratio"),
        "vrp": snapshot.get("vrp"),
        "vix_zscore_30d": snapshot.get("vix_zscore_30d"),
    }
    for rule in rules:
        try:
            ok = _evaluate_condition(rule["condition"], ctx)
        except (ValueError, SyntaxError, TypeError) as exc:
            logger.warning(
                "guidance_condition_skipped state=%s err=%s",
                rule.get("state"),
                repr(exc),
            )
            continue
        if ok:
            return rule
    return None


@router.get("/guidance", response_model=GuidanceResponse)
def get_guidance(
    repo: Annotated[Repository, Depends(get_repo)],
) -> GuidanceResponse:
    snap_repo = CriSnapshotRepository(repo.conn, schema=repo._schema)
    snap = snap_repo.fetch_latest()
    if snap is None:
        raise HTTPException(404, "no CRI snapshot — run the scanner first")
    rules = _parse_guidance_md()
    if not rules:
        raise HTTPException(500, "guidance.md missing or has no parseable rules")
    rule = _select_rule(rules, snap)
    if rule is None:
        raise HTTPException(500, "no guidance rule matched the current snapshot")
    return GuidanceResponse(
        state=rule["state"],
        posture=rule["posture"],
        body_md=rule["body_md"],
        matched_condition=rule["condition"],
    )


@router.get("/validation", response_model=ValidationResponse)
def get_validation(
    repo: Annotated[Repository, Depends(get_repo)],
) -> ValidationResponse:
    """DB-first; falls back to checked-in files during the deploy transition.

    The fallback block is removed in a follow-up PR after the prod gate in
    docs/superpowers/specs/2026-05-24-regime-research-closure-design.md §10.4
    is satisfied (≥1 completed CRI run in prod at the current
    cri_scorers.COMPOSITE_VERSION).
    """
    rb = RegimeBacktestRepository(repo.conn, schema=repo._schema)
    # No composite_version arg -> RegimeBacktestRepository defaults to
    # str(cri_scorers.COMPOSITE_VERSION). Experimental runs at other versions
    # are query-only via SQL and do NOT leak into the API surface.
    run = rb.find_latest_run("cri")
    if run is not None:
        daily = rb.fetch_daily_for_run(run["id"])
        oos_payload = (run.get("summary") or {}).get("oos")
        return ValidationResponse(
            backtest_md=render_backtest_markdown(run, daily),
            backtest_csv_rows=len(daily),
            oos=OosSummary.model_validate(oos_payload) if oos_payload else None,
        )

    # Transitional fallback — see docstring. Log LOUDLY: this path is hit
    # when the code constant has advanced past the prod-DB record (calibration
    # bump without a re-run), and the data we serve is stale-by-one-version.
    # Operators should see this in the logs and re-run scripts/backtest_cri.py.
    logger.warning(
        "regime/validation falling back to on-disk files: no completed "
        "regime_backtest_runs row at composite_version=%s. Re-run "
        "scripts/backtest_cri.py to refresh the DB record.",
        CRI_COMPOSITE_VERSION,
    )
    md_path = _safe_doc_path("cri-backtest.md")
    return ValidationResponse(
        backtest_md=md_path.read_text(),
        backtest_csv_rows=_count_csv_rows("cri-backtest.csv"),
        oos=_read_oos_summary(),
    )
