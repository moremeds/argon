"""Migration 159 widens ``external_api_requests_provider_check`` to every
provider the source telemetry path can emit.

Two layers of guard:

1. Text contract — the file must keep the shapes that make it replay-safe on
   every API boot (there is no schema_migrations table): a
   ``pg_constraint``/``pg_get_constraintdef`` ``LIKE ALL`` guard,
   ``DROP CONSTRAINT IF EXISTS``, and ``ADD ... NOT VALID`` — never a table
   scan, never a ``VALIDATE``.
2. Drift guard — the provider literals in the migration's CHECK list AND in
   its guard array must equal the ``PROVIDER`` constants of the eleven hook
   clients plus the two inline literals (``provider="massive"`` in ohlc.py,
   ``provider="uw"`` in api/client.py). A new source client whose provider
   string never reaches this list fails here, not silently at runtime when
   the recorder swallows the CHECK violation.

Pure file parsing — no DB, in the style of test_migration_dml_allowlist.py
and test_agent_runs_neutrality.py.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from uw_scan.storage.migrate_runner import MIGRATIONS_DIR

MIGRATION = MIGRATIONS_DIR / "159_external_api_requests_provider_check.sql"
UW_SCAN_DIR = MIGRATIONS_DIR.parent.parent

#: The 11 clients that emit provider=self.PROVIDER through record_or_log.
HOOK_CLIENT_FILES = (
    "cftc_cot.py",
    "cftc_tff.py",
    "cleveland_fed.py",
    "etf_holdings.py",
    "fed_funds_futures_path.py",
    "fred.py",
    "gpr.py",
    "lbma.py",
    "treasury_supply.py",
    "wgc_cb.py",
    "wgc_etf.py",
)
#: Clients that inline their provider string instead of a PROVIDER constant.
INLINE_PROVIDER_FILES = (
    UW_SCAN_DIR / "sources" / "ohlc.py",
    UW_SCAN_DIR / "api" / "client.py",
)


def _class_provider_constant(path: Path) -> str:
    """Return the ``PROVIDER = "<str>"`` class attribute of the client in ``path``."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for stmt in node.body:
            if (
                isinstance(stmt, ast.Assign)
                and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)
                and any(
                    isinstance(t, ast.Name) and t.id == "PROVIDER" for t in stmt.targets
                )
            ):
                return stmt.value.value
    raise AssertionError(f"{path.name} lost its PROVIDER class constant")


def _provider_kwarg_literal(path: Path) -> str:
    """Return the literal passed as ``provider=...`` anywhere in ``path``."""
    tree = ast.parse(path.read_text())
    hits = {
        kw.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
        if kw.arg == "provider"
        and isinstance(kw.value, ast.Constant)
        and isinstance(kw.value.value, str)
    }
    assert len(hits) == 1, (
        f"{path.name} should emit exactly one provider literal, got {hits}"
    )
    return hits.pop()


def _emitted_providers() -> set[str]:
    providers = {
        _class_provider_constant(UW_SCAN_DIR / "sources" / name)
        for name in HOOK_CLIENT_FILES
    }
    providers |= {_provider_kwarg_literal(p) for p in INLINE_PROVIDER_FILES}
    return providers


def _check_list_providers(sql: str) -> set[str]:
    m = re.search(r"provider\s+IN\s*\(([^)]*)\)", sql)
    assert m, "migration 159 lost its CHECK (provider IN (...)) list"
    return set(re.findall(r"'([a-z_0-9]+)'", m.group(1)))


def _guard_array_providers(sql: str) -> set[str]:
    m = re.search(r"LIKE\s+ALL\s*\(\s*ARRAY\[([^\]]+)\]", sql, re.IGNORECASE)
    assert m, "migration 159 lost its LIKE ALL guard array"
    return {
        literal.replace("''", "'").strip("%'")
        for literal in re.findall(r"'((?:[^']|'')*)'", m.group(1))
    }


def test_migration_159_is_replay_safe_by_construction():
    sql = MIGRATION.read_text()
    # Header convention shared by every migration file.
    assert "SET search_path TO uw_scan, public;" in sql
    # Guarded DO block: the widened check is only rebuilt when the existing
    # definition does not already accept every provider — so a second boot is
    # a pg_constraint lookup, never an external_api_requests scan.
    assert re.search(r"DO\s+\$\$", sql)
    assert "pg_constraint" in sql
    assert "pg_get_constraintdef" in sql
    assert re.search(r"LIKE\s+ALL", sql, re.IGNORECASE)
    assert "'uw_scan.external_api_requests'::regclass" in sql
    # The guard is also true when NO constraint exists — the DROP must be
    # tolerant of that case.
    assert "DROP CONSTRAINT IF EXISTS external_api_requests_provider_check" in sql
    # NOT VALID keeps ADD scan-free on the large table; a later VALIDATE pass
    # would re-introduce the scan on every boot, so it must stay absent.
    assert "ADD CONSTRAINT external_api_requests_provider_check" in sql
    assert "NOT VALID" in sql
    assert "VALIDATE CONSTRAINT" not in sql


def test_migration_159_provider_list_matches_emitted_providers():
    sql = MIGRATION.read_text()
    emitted = _emitted_providers()
    assert len(emitted) == 13, f"expected 13 telemetry providers, got {sorted(emitted)}"
    assert _check_list_providers(sql) == emitted
    assert _guard_array_providers(sql) == emitted
