"""Structural and smoke tests for scripts/compare_vcg_lead_time.py.

The zero-DB-in-loop test loads the script via importlib (scripts/ is
intentionally NOT a Python package — adding __init__.py would break the
existing `uv run python scripts/<x>.py` invocation pattern across the repo).
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path


def _load_comparator_module():
    """Load scripts/compare_vcg_lead_time.py without making scripts/ a package.

    Registers the loaded module in sys.modules before exec_module so dataclass
    field resolution can find the module via __module__ lookup. Without this,
    the @dataclass decorator's InitVar-detection path raises AttributeError
    on the first frozen dataclass it encounters.
    """
    name = "compare_vcg_lead_time"
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parents[2] / "scripts/compare_vcg_lead_time.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_per_cell_functions_do_not_reference_psycopg() -> None:
    """Spec §15 lock-in: the per-cell loop and compute_cell must not perform
    DB queries. Source-text scan rather than runtime probe because runtime
    probing would require a real DB connection, defeating the purpose."""
    mod = _load_comparator_module()
    forbidden = ("psycopg", ".cursor(", "cur.execute", ".connect(")
    for fn in (mod.compute_cell, mod.run_all_cells, mod.evaluate_gate):
        src = inspect.getsource(fn)
        for needle in forbidden:
            assert needle not in src, (
                f"{fn.__name__} references {needle!r} — DB access inside the "
                f"per-cell loop violates spec §15 (zero-DB-in-loop invariant)"
            )


def test_comparator_module_exports_expected_dataclasses() -> None:
    mod = _load_comparator_module()
    for name in (
        "ProxyRun",
        "BatchData",
        "CellResult",
        "GateVerdict",
        "batch_load_all",
        "run_all_cells",
        "evaluate_gate",
        "write_report",
    ):
        assert hasattr(mod, name), f"comparator missing export: {name}"


def test_drawdown_definitions_match_spec() -> None:
    mod = _load_comparator_module()
    assert [d.name for d in mod.DRAWDOWN_DEFS] == ["Fast", "Medium", "Major"]
    assert mod.DRAWDOWN_DEFS[0].threshold == 0.05
    assert mod.DRAWDOWN_DEFS[2].window_days == 60


def test_period_slices_cover_four_regime_buckets() -> None:
    mod = _load_comparator_module()
    names = [p[0] for p in mod.PERIOD_SLICES]
    assert names == ["pre-2020", "2020-COVID", "2021-2022-rates", "2023-2026-AI"]
