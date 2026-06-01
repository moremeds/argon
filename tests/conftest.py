from __future__ import annotations

import os


def pytest_configure() -> None:
    # Local safety default: integration fixtures still point at an isolated DB,
    # but developers do not need to prefix every pytest command.
    os.environ.setdefault("UW_SCAN_TEST_DB_NAME", "argon_test")
