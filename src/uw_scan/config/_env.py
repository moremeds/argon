"""Env parsing helpers and the minimal ``.env`` loader used by ``Settings.from_env``."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr
from pydantic.fields import FieldInfo

# ponytail: logger name kept from the old flat module, so log routing is unchanged.
logger = logging.getLogger("uw_scan.config")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_env(name: str, *, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _parse_int_csv_env(name: str, *, default: list[int]) -> list[int]:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader. We deliberately do not depend on python-dotenv.

    Reads KEY=VALUE lines, ignores comments and blanks, only sets keys that are
    not already present in the process environment. This makes `set -a; source .env`
    take precedence over our own loader.
    """
    if not env_path.exists():
        return
    try:
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError as exc:
        logger.exception("failed to read .env file %s: %s", env_path, repr(exc))


@dataclass(frozen=True)
class EnvVar:
    """Field metadata: the env var ``Settings.from_env`` reads for this field.

    Declared next to the field as ``Annotated[int, EnvVar("UW_SCAN_DB_PORT")]``. Unset
    means the field's own default, so the class default and the env default are one
    value. ``blank_is_default`` also maps an empty string to the default.
    """

    name: str
    blank_is_default: bool = False


#: Parse an env string by the field's annotation. Extended as field groups move here.
_PARSERS: dict[object, Callable[[str], Any]] = {
    str: str,
    int: int,
    SecretStr: SecretStr,
}


def _env_var(info: FieldInfo) -> EnvVar | None:
    return next((m for m in info.metadata if isinstance(m, EnvVar)), None)


def env_raw(model: type[BaseModel], field: str) -> str:
    """The raw env string for one declared field, or its default when unset."""
    info = model.model_fields[field]
    spec = _env_var(info)
    assert spec is not None, field
    return os.environ.get(spec.name, info.default)


def read_env_fields(model: type[BaseModel]) -> dict[str, Any]:
    """Parsed values for every ``EnvVar`` field whose env var is set (not defaulted)."""
    out: dict[str, Any] = {}
    for name, info in model.model_fields.items():
        spec = _env_var(info)
        if spec is None:
            continue
        raw = os.environ.get(spec.name)
        if raw is None or (spec.blank_is_default and not raw):
            continue
        out[name] = _PARSERS[info.annotation](raw)
    return out
