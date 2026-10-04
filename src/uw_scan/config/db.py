"""Postgres connection settings (D6 concern group: db)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, SecretStr

from uw_scan.config._env import EnvVar


class DbSettings(BaseModel):
    db_host: Annotated[str, EnvVar("UW_SCAN_DB_HOST")] = "127.0.0.1"
    db_port: Annotated[int, EnvVar("UW_SCAN_DB_PORT")] = 5432
    db_name: Annotated[str, EnvVar("UW_SCAN_DB_NAME")] = "option_wizard_local"
    db_schema: Annotated[str, EnvVar("UW_SCAN_DB_SCHEMA")] = "uw_scan"
    db_user: Annotated[str, EnvVar("UW_SCAN_DB_USER", blank_is_default=True)] = (
        "argon_app"
    )
    db_password: Annotated[SecretStr, EnvVar("UW_SCAN_DB_PASSWORD")] = SecretStr("")

    def db_dsn(self) -> str:
        """Return a libpq-style DSN. Password omitted when blank (peer/trust auth)."""
        pw = self.db_password.get_secret_value()
        password_clause = f" password={pw}" if pw else ""
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={self.db_user}{password_clause}"
        )
