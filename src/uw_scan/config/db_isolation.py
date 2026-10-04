"""Three-tier DB isolation: refuse a (host, db_name) pair from the wrong tier."""

from __future__ import annotations

import logging

from uw_scan.config._env import _env_bool

# ponytail: logger name kept from the old flat module, so log routing is unchanged.
logger = logging.getLogger("uw_scan.config")


# Host → set of legal db names. Refuses to start on (host, db_name) mismatch
# so a stray .env on the wrong machine cannot write into the wrong tier.
#   100.66.147.98 = Mac mini Tailscale (prodlike): option_wizard for the live
#                   data feed; option_wizard_test allowed too because
#                   integration tests on the macbook (with .env.local active)
#                   reach the mini's test DB via migrate.sh.
#   127.0.0.1     = local Postgres on macbook / CI: option_wizard_local for
#                   dev work, option_wizard_test for pytest (wiped by
#                   integration fixtures via DROP SCHEMA CASCADE).
# Override with UW_SCAN_ALLOW_DB_MISMATCH=1 for one-off ad-hoc scripts
# (e.g. backfilling from R2 into a scratch DB on the macbook).
_HOST_DB_RULES: dict[str, frozenset[str]] = {
    "100.66.147.98": frozenset({"option_wizard", "option_wizard_test"}),
    "127.0.0.1": frozenset({"option_wizard_local", "option_wizard_test"}),
    "localhost": frozenset({"option_wizard_local", "option_wizard_test"}),
    # Docker: containers reach host-native Postgres via host.docker.internal.
    # On the mini that host DB is prodlike `option_wizard`; local/CI Docker
    # smoke runs target `option_wizard_local`; integration tests use the test
    # tier. Keeping this rule meaningful means the container `.env` must NOT
    # carry UW_SCAN_ALLOW_DB_MISMATCH=1 (which bypasses ALL isolation checks) —
    # the clean container path is a legal pair here, no override.
    "host.docker.internal": frozenset(
        {"option_wizard", "option_wizard_local", "option_wizard_test"}
    ),
}


def _enforce_db_isolation(db_host: str, db_name: str) -> None:
    allowed = _HOST_DB_RULES.get(db_host)
    if allowed is None or db_name in allowed:
        return
    # pytest-xdist gives each worker its own per-worker test DB
    # (option_wizard_test_gw0, option_wizard_test_gw1, …). These are the same
    # isolated test tier as option_wizard_test — wiped per fixture, never prod — so
    # allow the prefix wherever the bare test DB is allowed.
    if "option_wizard_test" in allowed and db_name.startswith("option_wizard_test_"):
        return
    if _env_bool("UW_SCAN_ALLOW_DB_MISMATCH"):
        logger.warning(
            "DB isolation override active: host=%s db_name=%s "
            "(UW_SCAN_ALLOW_DB_MISMATCH=1)",
            db_host,
            db_name,
        )
        return
    raise RuntimeError(
        f"Refusing to start: UW_SCAN_DB_HOST={db_host!r} is not allowed to "
        f"target UW_SCAN_DB_NAME={db_name!r}. Allowed on this host: "
        f"{sorted(allowed)}. Set UW_SCAN_ALLOW_DB_MISMATCH=1 to override "
        "(one-off scripts only)."
    )
