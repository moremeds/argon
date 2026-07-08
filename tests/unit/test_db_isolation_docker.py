"""DB-isolation tripwire: the Docker `host.docker.internal` route.

Containers reach host-native Postgres via `host.docker.internal`; the tripwire
must allow the prodlike/local/test DB names on that host and still refuse an
illegal pairing (unless the explicit one-off override is set). See the Docker
migration design spec and `config._HOST_DB_RULES`.
"""

import pytest

from uw_scan.config import _enforce_db_isolation


@pytest.mark.parametrize(
    "db_name",
    ["option_wizard", "option_wizard_local", "option_wizard_test"],
)
def test_docker_host_allows_legal_db_names(db_name: str) -> None:
    # Must not raise for any of the three legal names on host.docker.internal.
    _enforce_db_isolation("host.docker.internal", db_name)


def test_docker_host_allows_xdist_test_db_prefix() -> None:
    # pytest-xdist per-worker test DBs share the isolated test tier.
    _enforce_db_isolation("host.docker.internal", "option_wizard_test_gw0")


def test_docker_host_refuses_illegal_db_name(monkeypatch: pytest.MonkeyPatch) -> None:
    # No override → an unlisted DB name on the Docker host is refused.
    monkeypatch.delenv("UW_SCAN_ALLOW_DB_MISMATCH", raising=False)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        _enforce_db_isolation("host.docker.internal", "some_other_db")


def test_override_still_bypasses_docker_host(monkeypatch: pytest.MonkeyPatch) -> None:
    # The blanket override remains an escape hatch even on the Docker host —
    # which is exactly why the container `.env` must NOT set it (see spec #1).
    monkeypatch.setenv("UW_SCAN_ALLOW_DB_MISMATCH", "1")
    _enforce_db_isolation("host.docker.internal", "some_other_db")
