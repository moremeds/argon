"""``uw_scan.config`` keeps every name the old flat ``config.py`` exposed (D6 batch 1).

src, scripts and tests import these from ``uw_scan.config``, private helpers included
(``_load_dotenv`` in scripts/profile_review, ``_enforce_db_isolation`` in control_argon
and tests). Moving code between submodules must not break those imports.
"""

import importlib

import uw_scan.config

NAMES = (
    "DEFAULT_APEX_API_URL",
    "Settings",
    "_HOST_DB_RULES",
    "_enforce_db_isolation",
    "_env_bool",
    "_load_dotenv",
    "_parse_csv_env",
    "_parse_int_csv_env",
)


def test_every_old_name_still_imports_from_the_package() -> None:
    module = importlib.import_module("uw_scan.config")
    missing = [name for name in NAMES if not hasattr(module, name)]
    assert missing == []
    assert sorted(module.__all__) == sorted(NAMES)


def test_package_has_a_file() -> None:
    # scripts/profile_review/db_observations.py reports uw_scan.config.__file__.
    assert uw_scan.config.__file__.endswith("config/__init__.py")
