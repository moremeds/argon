from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path


def _load_script_module():
    name = "score_vcg_classification_accuracy"
    spec = importlib.util.spec_from_file_location(
        name,
        Path(__file__).resolve().parents[2]
        / "scripts/score_vcg_classification_accuracy.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_script_exports_expected_functions():
    mod = _load_script_module()
    for name in (
        "load_label_contract",
        "load_input_series",
        "load_vcg_daily",
        "derive_truth_frame",
        "score_against_vcg",
        "compute_named_crisis_overlay",
        "persist_and_render",
        "render_replay",
        "main",
    ):
        assert hasattr(mod, name), f"script missing export: {name}"


def test_zero_db_in_loop_guard():
    """Spec section 12: classification scoring loop has zero DB queries."""
    mod = _load_script_module()
    forbidden = ("psycopg.connect", "cur.execute", ".cursor(")
    for fn_name in (
        "derive_truth_frame",
        "score_against_vcg",
        "compute_named_crisis_overlay",
    ):
        fn = getattr(mod, fn_name)
        src = inspect.getsource(fn)
        for needle in forbidden:
            assert needle not in src, (
                f"{fn_name} references {needle!r} — DB access in per-cell loop "
                f"violates spec section 12 zero-DB-in-loop invariant"
            )
