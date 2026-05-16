"""Repository base mixin: owns __init__, conn property, and the _schema /
_conn attributes that every per-domain mixin reads.

Mixed in LAST in the Repository inheritance order so domain mixins can
shadow specific behavior if needed (none do today). Domain mixins MUST NOT
define their own __init__ — Python's MRO calls only the leftmost __init__,
and skipping super() chains the way mixin __init__ would creates
hard-to-debug initialization gaps."""

from __future__ import annotations

import psycopg


class _BaseMixin:
    """Owns the connection and schema. Other mixins reference self._conn and
    self._schema; this class is what makes them concrete."""

    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema

    @property
    def conn(self) -> psycopg.Connection:
        return self._conn
