"""The transport must not learn what a tenant's runs mean.

This is argon's mirror of helium's `core-neutrality` contract. Storage, models
and the router carry one tenant's vocabulary the moment somebody finds it
convenient — a `phase` column, a CHECK enumerating labels, a special case for
one kind — and the next tenant becomes a migration instead of an insert.

Docstrings are exempt: explaining the design in prose is how the rule survives.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

TRANSPORT_FILES = [
    REPO_ROOT / "src/uw_scan/storage/migrations/148_agent_runs.sql",
    REPO_ROOT / "src/uw_scan/storage/agent_runs.py",
    REPO_ROOT / "src/uw_scan/models/agent_runs.py",
    REPO_ROOT / "src/uw_scan/api/routers/agent_runs.py",
]

FORBIDDEN = (
    "flash",
    "premarket",
    "intraday",
    "option_wizard",
    "call spread",
    "put spread",
    "strike",
    "expiry",
)

MESSAGE = (
    "the transport is generic; Flash's words belong in web/components/flash/."
)


def _strip_sql_comments(text: str) -> str:
    lines = []
    for line in text.splitlines():
        head, _, _ = line.partition("--")
        lines.append(head)
    return "\n".join(lines)


def _strip_python_docstrings(text: str) -> str:
    tree = ast.parse(text)
    doc_nodes: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            doc_nodes.add(id(body[0]))
            body[0].value.value = ""
    return ast.unparse(tree)


@pytest.mark.parametrize("path", TRANSPORT_FILES, ids=lambda p: p.name)
def test_the_transport_never_learns_a_tenants_vocabulary(path: Path):
    raw = path.read_text()
    body = (
        _strip_sql_comments(raw)
        if path.suffix == ".sql"
        else _strip_python_docstrings(raw)
    )
    lowered = body.lower()
    leaked = [word for word in FORBIDDEN if word in lowered]
    assert leaked == [], f"{path.name} leaks {leaked}: {MESSAGE}"
