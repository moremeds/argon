"""Regime-state guidance rules: the packaged guidance.md parser and the
AST-whitelist evaluator for each rule's ``condition``.

Pure, no DB. ``GET /api/regime/guidance`` (``api/routers/regime_validation.py``)
selects the active rule with these.
"""

from __future__ import annotations

import ast
import logging
import operator as _op
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Package data — ships inside the wheel/image. See
# docs/superpowers/specs/2026-07-20-runtime-asset-durability-design.md.
GUIDANCE_MD: Traversable = files("uw_scan.cards") / "data" / "guidance.md"


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


def evaluate_condition(expr: str, ctx: dict[str, Any]) -> bool:
    tree = ast.parse(expr, mode="eval")
    return bool(_eval_node(tree, ctx))


def parse_guidance_md(path: Traversable | Path = GUIDANCE_MD) -> list[dict[str, Any]]:
    """Split guidance.md on `---` separators; load YAML frontmatter + body."""
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        logger.error(
            "guidance.md unreadable at %s (%s) — is it shipping as package data?",
            path,
            repr(exc),
        )
        return []
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
