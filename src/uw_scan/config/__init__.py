"""Application settings. ``Settings.from_env()`` is the entry point.

The implementation lives in submodules; this package re-exports every name that was
importable from the old flat ``uw_scan/config.py``, so ``from uw_scan.config import X``
keeps working.
"""

from uw_scan.config._env import (
    _env_bool,
    _load_dotenv,
    _parse_csv_env,
    _parse_int_csv_env,
)
from uw_scan.config.db_isolation import _HOST_DB_RULES, _enforce_db_isolation
from uw_scan.config.apex import DEFAULT_APEX_API_URL
from uw_scan.config.settings import Settings

__all__ = [
    "DEFAULT_APEX_API_URL",
    "Settings",
    "_HOST_DB_RULES",
    "_enforce_db_isolation",
    "_env_bool",
    "_load_dotenv",
    "_parse_csv_env",
    "_parse_int_csv_env",
]
