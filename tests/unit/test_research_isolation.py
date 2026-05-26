"""Hard Guarantee #1: production code paths must not reference research symbols.

AST-based scan rather than `__dict__` introspection — catches aliased imports
(`from cards.vcg_basket import build_basket as _bb`) that runtime `__dict__`
inspection would expose under different names.

The test is intentionally pessimistic: it scans for ANY reference to the
research module path or to the research-only symbol names anywhere in the
production AST. Production files added in future PRs that need to surface
research data must do so through the repository (run_scope='research'
filter) — never by importing the research helpers directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

PRODUCTION_FILES = (
    REPO / "src/uw_scan/scanners/vcg.py",
    REPO / "src/uw_scan/api/routers/regime_validation.py",
)

FORBIDDEN_MODULES = ("uw_scan.cards.vcg_basket",)
FORBIDDEN_NAMES = ("RESEARCH_COMPOSITE_VERSIONS", "compute_vcg_composite")


def _imports_in(tree: ast.AST) -> set[tuple[str, str | None]]:
    """Returns set of (module_path, imported_name_or_None) for every import.

    Captures `import X`, `from Y import Z`, and `from Y import Z as W`.
    """
    out: set[tuple[str, str | None]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.add((alias.name, None))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for alias in node.names:
                out.add((mod, alias.name))
    return out


def _name_references_in(tree: ast.AST) -> set[str]:
    """All Name and Attribute references — catches `vcg_scoring.compute_vcg_composite`
    even when the parent module is imported aliased.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


def test_production_files_do_not_import_research_modules_or_names() -> None:
    for path in PRODUCTION_FILES:
        assert path.exists(), f"production file does not exist: {path}"
        tree = ast.parse(path.read_text())
        imports = _imports_in(tree)
        references = _name_references_in(tree)
        for mod, _name in imports:
            for forbidden_mod in FORBIDDEN_MODULES:
                assert not mod.startswith(forbidden_mod), (
                    f"{path.name} imports forbidden research module {mod}"
                )
        for forbidden_name in FORBIDDEN_NAMES:
            assert forbidden_name not in references, (
                f"{path.name} references forbidden research name {forbidden_name}"
            )
            for _mod, imported in imports:
                assert imported != forbidden_name, (
                    f"{path.name} imports forbidden research name {forbidden_name}"
                )
