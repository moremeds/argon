"""Every `_self_check()` in the fundamentals package actually runs in CI.

Four modules ship one — `fx`, `scoring`, `statements`, `valuation` — and until
this file existed **no test invoked any of them**. They executed only when a
human typed `uv run python -m uw_scan.fundamentals.<module>`, which is the same
defect as the anchor lane having no scheduled caller: a check that exists, looks
like coverage, and never fires.

That mattered concretely. `valuation._self_check` carries the only assertions
that an `unclassified` name bands on the pooled default at `medium` confidence,
and that `anchor_inputs_hash` responds to each of its six inputs — both written
2026-08-12 to lock down live bugs, both unenforced.

Parametrized over the discovered module list rather than a hand-written one, so
a fifth module with a self-check is covered the day it lands instead of the day
someone remembers to add it here.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

import uw_scan.fundamentals as pkg


def _modules_with_self_check() -> list[str]:
    found = []
    for info in pkgutil.iter_modules(pkg.__path__):
        mod = importlib.import_module(f"{pkg.__name__}.{info.name}")
        if callable(getattr(mod, "_self_check", None)):
            found.append(info.name)
    return sorted(found)


SELF_CHECKED = _modules_with_self_check()


def test_the_package_still_has_self_checks_to_run():
    """Guards the discovery itself: a rename that emptied the list would make
    every test below vacuously pass."""
    assert set(SELF_CHECKED) >= {"fx", "scoring", "statements", "valuation"}, (
        SELF_CHECKED
    )


@pytest.mark.parametrize("name", SELF_CHECKED)
def test_self_check_passes(name: str, capsys: pytest.CaptureFixture[str]):
    mod = importlib.import_module(f"{pkg.__name__}.{name}")
    mod._self_check()
    # Each ends with a "... ok" print; swallow it so -s output stays readable.
    capsys.readouterr()
