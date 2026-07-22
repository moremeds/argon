"""Hermetic env for worker unit tests.

Several tests here boot the real ``scheduler.main()`` to assert job-registration
wiring. ``main()`` calls ``Settings.from_env()``, which loads the developer's
``.env`` for any key not already in the process environment.

Since 2026-07-20 ``_validate_worker_settings`` refuses to boot when retired R2
settings are present (R2's producer died 2026-05-21). A developer whose ``.env``
still carries ``R2_*`` would otherwise see every scheduler-wiring test fail with
that guard — a false negative unrelated to what the test checks. CI has no
``.env`` so it never sees R2, which would make this a local-only flake.

Neutralise it by pinning the four R2 keys to empty strings before each test.
``from_env`` maps empty → ``None`` (config.py), so ``_r2_fully_configured`` is
False and the guard stays quiet. Any test that genuinely wants R2 configured can
override these with ``monkeypatch.setenv`` — none in this directory do.
"""

from __future__ import annotations

import pytest

_R2_KEYS = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET",
)


@pytest.fixture(autouse=True)
def _neutralise_retired_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _R2_KEYS:
        monkeypatch.setenv(key, "")
