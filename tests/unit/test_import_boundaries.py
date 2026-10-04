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

#: Research code (I-89, D3): FAILED or unpromoted verdicts that still accrue
#: evidence. Files or packages, relative to src/uw_scan. A research verdict must
#: never reach an alert or a proposal, so the two may not import each other.
RESEARCH = frozenset(
    {
        "scanners/theta_harvester",
        "reports/theta_harvester_markout",
        "storage/theta_harvester_repository",
        "worker/jobs/theta_harvester",
        "reports/sector_rs",
        "worker/jobs/sector_rs_daily",
        "reports/vrp_candidates",
        "reports/vrp_backtest",
        "worker/jobs/vrp_trading_jobs",
        "storage/vrp_trading",
        "reports/skew_markout",
        "worker/jobs/vrp_research_jobs",
        "storage/vrp_research",
        "chanlun",
    }
)

#: The outbound surfaces: the ops webhook and the mcp_event stream. Any future
#: top-level ``alerts*`` / ``proposals*`` module or package joins automatically.
ALERT_FILES = frozenset({"alerts.py", "storage/mcp_events.py"})


def _is_alert(rel: str) -> bool:
    return rel in ALERT_FILES or rel.split("/")[0].startswith(("alerts", "proposals"))


def _is_research(rel: str) -> bool:
    stem = rel.removesuffix(".py").removesuffix("/__init__")
    return any(stem == e or stem.startswith(e + "/") for e in RESEARCH)


def _matches(module: str, rels: list[str]) -> bool:
    """``module`` is one of ``rels`` (src-relative paths) or inside one."""
    dotted = [f"uw_scan.{r.replace('/', '.')}" for r in rels]
    return any(module == d or module.startswith(d + ".") for d in dotted)


#: (file relative to src/uw_scan, imported module) -> why it is still allowed.
KNOWN: dict[tuple[str, str], str] = {
    ("cards/dealer_regime.py", "uw_scan.storage.greek_exposure_repository"): (
        "I-32: frozen; fix when the file is next touched"
    ),
    ("cards/derive.py", "uw_scan.storage.rows"): (
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


def _imported_modules(
    path: Path, tree: ast.AST, src: Path = SRC, names: bool = False
) -> list[str]:
    """Absolute module names imported by ``path``, relative imports resolved.

    ``names`` also yields ``module.name`` for each ``from module import name``,
    so ``from uw_scan.reports import sector_rs`` is seen as that submodule.
    """
    parts = path.relative_to(src.parent).with_suffix("").parts
    package = list(parts[:-1])  # a module's package; for __init__ the package itself
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + ([node.module] if node.module else []))
            elif node.module:
                module = node.module
            else:
                continue
            out.append(module)
            if names:
                out.extend(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
    return out


def _violations(src: Path = SRC) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for path in src.rglob("*.py"):
        rel = path.relative_to(src).as_posix()
        layer = rel.split("/")[0].removesuffix(".py")
        tree = ast.parse(path.read_text())
        for module in _imported_modules(path, tree, src, names=True):
            if _is_alert(rel) and _matches(module, sorted(RESEARCH)):
                found.add((rel, module))  # (a) an alert reads research output
            if _is_research(rel) and (
                _matches(module, ["storage/mcp_events"])
                or module.startswith(("uw_scan.alerts", "uw_scan.proposals"))
            ):
                found.add((rel, module))  # (b) research emits an alert
        for module in _imported_modules(path, tree, src):
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


def test_research_entries_exist():
    """A renamed research file would silently void its rule."""
    missing = sorted(
        e
        for e in RESEARCH
        if not (SRC / f"{e}.py").is_file() and not (SRC / e).is_dir()
    )
    assert not missing, f"RESEARCH names a path that does not exist: {missing}"


def test_research_alert_rule_fires(tmp_path: Path):
    """Both directions, both import spellings, on a synthetic tree."""
    pkg = tmp_path / "uw_scan"
    for d in ("scanners", "storage", "chanlun", "proposals"):
        (pkg / d).mkdir(parents=True)
    (pkg / "alerts.py").write_text(
        "import uw_scan.scanners.theta_harvester\n"
        "from uw_scan.chanlun import lifecycle\n"
        "from uw_scan.scanners import cri\n"  # not research: allowed
    )
    (pkg / "proposals" / "x.py").write_text("from ..reports import sector_rs\n")
    (pkg / "scanners" / "theta_harvester.py").write_text(
        "from uw_scan.storage.mcp_events import emit_event\n"
    )
    (pkg / "chanlun" / "core.py").write_text("from uw_scan import alerts\n")
    assert _violations(pkg) == {
        ("alerts.py", "uw_scan.scanners.theta_harvester"),
        ("alerts.py", "uw_scan.chanlun"),
        ("alerts.py", "uw_scan.chanlun.lifecycle"),
        ("proposals/x.py", "uw_scan.reports.sector_rs"),
        ("scanners/theta_harvester.py", "uw_scan.storage.mcp_events"),
        ("scanners/theta_harvester.py", "uw_scan.storage.mcp_events.emit_event"),
        ("chanlun/core.py", "uw_scan.alerts"),
    }


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
