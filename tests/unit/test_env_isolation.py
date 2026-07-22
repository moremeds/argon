"""Regression: raw os.environ writes must not leak across tests.

Settings.from_env() → _load_dotenv writes dotenv keys straight into os.environ
(not via monkeypatch), which historically leaked a developer's local .env into
later tests (see the _restore_os_environ fixture in tests/conftest.py). These
two tests exercise that fixture directly: test_a plants a raw sentinel the way
_load_dotenv would; test_b (which runs after it, definition order) asserts the
fixture cleaned it up. Delete the fixture and test_b fails.
"""

from __future__ import annotations

import os

_SENTINEL = "ARGON_ENV_ISOLATION_SENTINEL"


def test_a_plants_a_raw_env_var() -> None:
    os.environ[_SENTINEL] = "leaked"  # raw write, exactly like _load_dotenv
    assert os.environ[_SENTINEL] == "leaked"


def test_b_does_not_see_the_leak() -> None:
    assert _SENTINEL not in os.environ, (
        "the autouse _restore_os_environ fixture in tests/conftest.py did not "
        "clean up test_a's raw os.environ write"
    )
