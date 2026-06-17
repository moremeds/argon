"""Single source of truth for the running release version.

Both the FastAPI app factory (`api/server.py`) and the health router import
`app_version()` from here. Keeping it in a neutral leaf module avoids the
circular import that would arise if a router imported it back from
`api/server.py` (which imports the routers).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# version.py lives at src/uw_scan/version.py → repo root is parents[2].
_VERSION_FILE = Path(__file__).resolve().parents[2] / "VERSION"


def app_version() -> str:
    """Read the release version from the repo-root VERSION file.

    Falls back to a sentinel if the file is missing (e.g. an odd packaging).
    """
    try:
        return _VERSION_FILE.read_text().strip()
    except OSError as exc:
        logger.warning("VERSION file unreadable; using sentinel version: %s", repr(exc))
        return "0.0.0+unknown"
