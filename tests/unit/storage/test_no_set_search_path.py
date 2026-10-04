"""No storage module may SET search_path on the caller's connection.

Repositories schema-qualify their SQL instead; SET on a shared/pooled conn
silently changes session state for later users. Migration files under
``migrations/`` are excluded — they SET their own paths by design.
"""

from pathlib import Path

STORAGE_DIR = Path(__file__).parents[3] / "src" / "uw_scan" / "storage"


def test_no_set_search_path_in_storage_sources() -> None:
    offenders = [
        p.name for p in STORAGE_DIR.glob("*.py") if "SET search_path" in p.read_text()
    ]
    assert not offenders, f"SET search_path found in: {offenders}"
