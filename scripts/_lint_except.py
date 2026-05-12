"""AST walker enforcing Implementation Guardrail 2.

Flags any ExceptHandler whose body does not call logging.exception(...), logger.exception(...),
reference repr(exc), traceback, or re-raise.

Usage:
    uv run python scripts/_lint_except.py src app
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _names_in_node(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _check_handler(handler: ast.ExceptHandler) -> bool:
    """Return True if the handler has acceptable logging/repr/traceback semantics."""
    for stmt in ast.walk(handler):
        if isinstance(stmt, ast.Raise):
            return True
        if isinstance(stmt, ast.Call):
            # logging.exception(...) / logger.exception(...) / log.exception(...)
            if isinstance(stmt.func, ast.Attribute) and stmt.func.attr == "exception":
                return True
            # repr(exc)
            if isinstance(stmt.func, ast.Name) and stmt.func.id == "repr":
                return True
        if isinstance(stmt, ast.Name) and stmt.id == "traceback":
            return True
        if isinstance(stmt, ast.Attribute) and stmt.attr in {"format_exc", "print_exc"}:
            return True
    names = _names_in_node(handler)
    if "traceback" in names:
        return True
    return False


def lint_file(path: Path) -> list[str]:
    src = path.read_text()
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:  # pragma: no cover
        return [f"{path}: SYNTAX ERROR — {exc!r}"]

    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            # Bare `except:` or `except Exception:` without name binding are still checked.
            if not _check_handler(node):
                errors.append(
                    f"{path}:{node.lineno} except-handler lacks "
                    "logging.exception / repr(exc) / traceback / raise"
                )
    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: _lint_except.py <path> [<path>...]", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    for root in argv[1:]:
        p = Path(root)
        if not p.exists():
            print(f"skip (not found): {p}", file=sys.stderr)
            continue
        for py in p.rglob("*.py"):
            all_errors.extend(lint_file(py))

    if all_errors:
        for err in all_errors:
            print(err)
        return 1
    print("ok: no banned except patterns")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
