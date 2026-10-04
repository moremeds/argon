"""Import-boundary ratchet (I-41): lower layers must not import higher ones.

Pure AST over ``src/uw_scan`` -- nothing is imported, no new dependency. Relative
imports are resolved, because ``from ..api.endpoints import X`` is how
``sources/uw.py`` used to reach into ``api``.

``FORBIDDEN`` names the top-level packages a package may not import. ``KNOWN``
freezes the violations that existed when the rule landed; it is a ratchet both
ways: a new violation fails, and so does a listed one that no longer exists (delete
the entry). Fix a frozen entry when its file is next touched.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "uw_scan"

_DOMAINS_NO_WORKER = (
    "reports",
    "scanners",
    "scanner",
    "macro",
    "fundamentals",
    "rates",
)

FORBIDDEN: dict[str, frozenset[str]] = {
    # The contract layer: plain models, importing no behaviour.
    "models": frozenset(
        {"api", "worker", "storage", "sources", "reports", "cards", "scanners"}
        | {"scanner", "macro", "fundamentals", "rates"}
    ),
    # Derivers are pure functions on rows.
    "cards": frozenset({"api", "worker", "storage", "reports", "scanners"}),
    "storage": frozenset({"api", "worker", "sources"}),
    "sources": frozenset({"api", "worker", "reports", "scanners"}),
    **{d: frozenset({"worker"}) for d in _DOMAINS_NO_WORKER},
}

#: ``uw_scan.normalize`` is the UW payload normalizer. Everyone else raises the
#: shared ``uw_scan.errors.NormalizationError`` (I-58).
NORMALIZE_IMPORTERS = frozenset({"pipeline.py", "sources/uw.py"})

#: (file relative to src/uw_scan, imported module) -> why it is still allowed.
KNOWN: dict[tuple[str, str], str] = {
    ("cards/dealer_regime.py", "uw_scan.storage.greek_exposure_repository"): (
        "I-32: frozen; fix when the file is next touched"
    ),
    ("cards/derive.py", "uw_scan.storage.repository"): (
        "I-32: frozen; fix when the file is next touched"
    ),
    ("cards/matrix_state.py", "uw_scan.storage.repository"): (
        "I-32: frozen; fix when the file is next touched"
    ),
    ("sources/earnings_calendar.py", "uw_scan.api.client"): (
        "UwClient lives in api/; moves with the per-client status contract (5c)"
    ),
    ("sources/uw.py", "uw_scan.api.client"): (
        "UwClient lives in api/; moves with the per-client status contract (5c)"
    ),
    ("sources/uw_gold_options.py", "uw_scan.api.client"): (
        "UwClient lives in api/; moves with the per-client status contract (5c)"
    ),
}


def _imported_modules(path: Path, tree: ast.AST, src: Path = SRC) -> list[str]:
    """Absolute module names imported by ``path``, relative imports resolved."""
    parts = path.relative_to(src.parent).with_suffix("").parts
    package = list(parts[:-1])  # a module's package; for __init__ the package itself
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                out.append(".".join(base + ([node.module] if node.module else [])))
            elif node.module:
                out.append(node.module)
        elif isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
    return out


def _violations(src: Path = SRC) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in src.rglob("*.py"):
        rel = path.relative_to(src).as_posix()
        layer = rel.split("/")[0].removesuffix(".py")
        for module in _imported_modules(path, ast.parse(path.read_text()), src):
            bits = module.split(".")
            if bits[0] != "uw_scan" or len(bits) < 2:
                continue
            if bits[1] in FORBIDDEN.get(layer, ()):
                found.add((rel, module))
            if bits[1] == "normalize" and rel not in NORMALIZE_IMPORTERS | {
                "normalize.py"
            }:
                found.add((rel, module))
    return found


def test_no_new_boundary_violations():
    new = sorted(_violations() - KNOWN.keys())
    assert not new, (
        "import crosses a layer boundary (see FORBIDDEN in this file). Move the "
        f"shared piece down a layer instead of importing up: {new}"
    )


def test_known_violations_are_a_ratchet():
    fixed = sorted(KNOWN.keys() - _violations())
    assert not fixed, f"no longer violates; delete from KNOWN: {fixed}"


def test_detector_resolves_relative_imports(tmp_path: Path):
    """Keeps the guard from passing vacuously on the shape that hid I-31."""
    pkg = tmp_path / "uw_scan"
    (pkg / "sources").mkdir(parents=True)
    (pkg / "api").mkdir()
    (pkg / "sources" / "x.py").write_text(
        "from ..api.endpoints import EndpointSlug\nfrom uw_scan.normalize import N\n"
    )
    (pkg / "api" / "endpoints.py").write_text("")
    assert _violations(pkg) == {
        ("sources/x.py", "uw_scan.api.endpoints"),
        ("sources/x.py", "uw_scan.normalize"),
    }
