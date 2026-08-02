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

#: Verbatim-vendored numeric modules (the signal-lab v13 SPX density port). Their bodies
#: are byte-identical to signal-lab @ 0f893513 by design — see the header of
#: src/uw_scan/density/cone.py — so the two bare `except Exception:` handlers inside the v8
#: estimator (`_attempt`, `fit_gjr`) cannot be given logging without making argon's copy a
#: different estimator from the one v13 validated. Both are deliberate: returning a rejected
#: `Attempt`/None is how a failed fit routes to the labelled `degraded` fallback, and the
#: research records the rejection through its channel field rather than through a log line.
#: Behaviour is pinned instead by the zero-tolerance golden parity test
#: (tests/unit/density/test_parity_golden.py), which is a stronger guarantee than this rule.
#: Listed file by file, never as a directory glob — a new non-vendored module under
#: density/ must still be checked.
_VENDORED_EXEMPT = (
    "uw_scan/density/constants.py",
    "uw_scan/density/cone.py",
    "uw_scan/density/fit.py",
)


def _is_vendored(path: Path) -> bool:
    posix = path.as_posix()
    return any(posix.endswith(suffix) for suffix in _VENDORED_EXEMPT)


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
            if _is_vendored(py):
                continue
            all_errors.extend(lint_file(py))

    if all_errors:
        for err in all_errors:
            print(err)
        return 1
    print("ok: no banned except patterns")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
