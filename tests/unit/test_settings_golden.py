"""Golden of every Settings field: its env name, type, both defaults, and how env parses.

Baseline for the D6 config refactor (I-70). Each refactor batch must leave this golden
byte-identical: no env name dropped or renamed, no default changed, no parse changed.

Per field it records:
- ``env``: the env names ``from_env`` reads for it, derived from the source by AST.
  ``env_fallback`` holds the names reached through a local (the lake roots fall back
  under ``MARKET_WAREHOUSE_LAKE``).
- ``type``: the annotation; ``class_default``: what bare ``Settings(...)`` uses;
  ``env_default``: what ``from_env`` gives with no env set. The two defaults are
  separate code paths, and they already differ for the lake roots.
- ``probes``: the parsed value (or the exception type) for a fixed list of input
  strings per type, one env name set at a time.

Hermetic: every known env name is removed and settings load from an empty env file,
so a developer's ``.env`` / shell cannot change the result. Paths under ``$HOME``
are written as ``~``.

``test_every_env_name_is_read`` is the behavioural check behind the AST column:
setting the name must change that field, so a name that only appears in the source
cannot pass.

Regenerate ONLY on purpose: ``UPDATE_SETTINGS_GOLDEN=1 uv run pytest <this file>``.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

import uw_scan.config as config
from uw_scan.config import Settings

GOLDEN = Path(__file__).parent / "fixtures" / "settings_golden.json"

_READERS = {"get", "_env_bool", "_parse_csv_env", "_parse_int_csv_env"}
#: Read outside from_env (the DB-isolation bypass); cleared so it cannot leak in.
_ALSO_CLEAR = ("UW_SCAN_ALLOW_DB_MISMATCH",)
_API_KEY = "golden-key"

#: Inputs per base type. ``""`` is in every list: empty-string handling differs by field.
_PROBES: dict[str, tuple[str, ...]] = {
    "bool": ("true", "1", "yes", "on", " true ", "TRUE", "false", ""),
    "int": ("7", ""),
    "float": ("7.5", ""),
    "Decimal": ("7.5", ""),
    "str": ("probe", ""),
    "Path": ("/probe", ""),
    "SecretStr": ("probe", ""),
    "list[str]": ("a, b", ""),
    "list[int]": ("1, 2", ""),
}
#: Fields whose generic probe cannot show the env is read: the DB-isolation tripwire
#: rejects an arbitrary host/db pair, and the validators reject a lone out-of-range
#: value. Each probe below is a legal value that differs from the default.
_FIELD_PROBES: dict[str, tuple[str, ...]] = {
    "db_host": ("localhost", ""),
    "db_name": ("option_wizard_test", ""),
}


def _env_map() -> dict[str, tuple[list[str], list[str]]]:
    """field -> (env names read directly, env names reached through a local)."""
    src = inspect.getsource(config)
    tree = ast.parse(src)
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "from_env"
    )
    assigns = {
        t.id: node.value
        for node in ast.walk(fn)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Name)
    }

    def reads(expr: ast.AST) -> list[str]:
        out = []
        for n in ast.walk(expr):
            if (
                isinstance(n, ast.Call)
                and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
                in _READERS
                and n.args
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)
            ):
                out.append(n.args[0].value)
        return out

    def via_locals(expr: ast.AST, seen: frozenset[str] = frozenset()) -> list[str]:
        out = []
        for n in ast.walk(expr):
            if isinstance(n, ast.Name) and n.id in assigns and n.id not in seen:
                value = assigns[n.id]
                out += reads(value) + via_locals(value, seen | {n.id})
        return out

    call = next(
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Call)
        and getattr(n.value.func, "id", None) == "cls"
    ).value
    result = {}
    for kw in call.keywords:
        direct = list(dict.fromkeys(reads(kw.value)))
        indirect = list(dict.fromkeys(via_locals(kw.value)))
        result[kw.arg] = (direct, indirect) if direct else (indirect, [])
    return result


ENV_MAP = _env_map()
ALL_ENV = sorted({n for d, f in ENV_MAP.values() for n in d + f} | set(_ALSO_CLEAR))


def _type_name(annotation: object) -> str:
    text = (
        getattr(annotation, "__name__", None) if isinstance(annotation, type) else None
    )
    text = text or str(annotation)
    return re.sub(r"\b(?:[a-z_]\w*\.)+(\w+)", r"\1", text)


def _base_type(type_name: str) -> str:
    return (
        type_name.replace(" | None", "").replace("Optional[", "").rstrip("]")
        if ("Optional[" in type_name)
        else type_name.replace(" | None", "")
    )


def _ser(value: object) -> object:
    if isinstance(value, SecretStr):
        return f"secret:{value.get_secret_value()}"
    if isinstance(value, Path):
        text = str(value)
        home = str(Path.home())
        return "~" + text[len(home) :] if text.startswith(home) else text
    if isinstance(value, Decimal):
        return f"Decimal:{value}"
    if isinstance(value, (list, tuple)):
        return [_ser(v) for v in value]
    return value


def _class_default(name: str) -> object:
    field = Settings.model_fields[name]
    if field.is_required():
        return "<required>"
    if field.default_factory is not None:
        return _ser(field.default_factory())
    return _ser(field.default)


@pytest.fixture
def load(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """``load({env: value})`` -> Settings or the exception, every other name unset."""
    empty = tmp_path / "empty.env"
    empty.write_text("")
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UW_SCAN_API_KEY", _API_KEY)

    def _load(env: dict[str, str] | None = None) -> Settings | Exception:
        env = env or {}
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        try:
            return Settings.from_env(env_path=empty)
        except Exception as exc:  # recorded, not raised: a rejection is behaviour too
            return exc
        finally:
            for key in env:
                if key == "UW_SCAN_API_KEY":
                    monkeypatch.setenv(key, _API_KEY)
                else:
                    monkeypatch.delenv(key, raising=False)

    return _load


def _outcome(result: Settings | Exception, field: str) -> object:
    if isinstance(result, Exception):
        return {"error": type(result).__name__}
    return _ser(getattr(result, field))


def _probes_for(field: str, type_name: str) -> tuple[str, ...]:
    return _FIELD_PROBES.get(field) or _PROBES[_base_type(type_name)]


def _build(load) -> dict[str, dict]:
    baseline = load()
    assert isinstance(baseline, Settings), baseline
    golden = {}
    for name, info in Settings.model_fields.items():
        type_name = _type_name(info.annotation)
        direct, fallback = ENV_MAP.get(name, ([], []))
        record: dict[str, object] = {
            "type": type_name,
            "env": direct or None,
            "class_default": _class_default(name),
            "env_default": _ser(getattr(baseline, name)),
        }
        if fallback:
            record["env_fallback"] = fallback
            record["fallback_probes"] = {
                f"{env}=/probe": _outcome(load({env: "/probe"}), name)
                for env in fallback
            }
        if direct:
            record["probes"] = {
                env: {
                    repr(raw): _outcome(load({env: raw}), name)
                    for raw in _probes_for(name, type_name)
                }
                for env in direct
            }
        golden[name] = record
    return golden


def test_settings_golden(load) -> None:
    current = _build(load)
    if os.environ.get("UPDATE_SETTINGS_GOLDEN") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n")
    golden = json.loads(GOLDEN.read_text())
    assert sorted(current) == sorted(golden)
    for name in sorted(golden):
        assert current[name] == golden[name], name


def test_every_env_name_is_read(load) -> None:
    """Setting each AST-derived env name changes its field (or is rejected by it)."""
    baseline = load()
    assert isinstance(baseline, Settings)
    silent = []
    for name, (direct, fallback) in ENV_MAP.items():
        type_name = _type_name(Settings.model_fields[name].annotation)
        default = _ser(getattr(baseline, name))
        for env in direct:
            if env == "UW_SCAN_API_KEY":
                changed = [_outcome(load({env: "other-key"}), name)]
            else:
                changed = [
                    _outcome(load({env: raw}), name)
                    for raw in _probes_for(name, type_name)
                ]
            if all(c == default for c in changed):
                silent.append(f"{name} <- {env}")
        for env in fallback:
            if _outcome(load({env: "/probe"}), name) == default:
                silent.append(f"{name} <- {env} (fallback)")
    assert not silent, silent


def test_env_map_covers_every_env_driven_field() -> None:
    """Only the two deliberately default-only fields have no env name."""
    assert set(Settings.model_fields) - set(ENV_MAP) == {
        "full_scan_crons",
        "record_health_daily_window_hours",
    }
    assert set(ENV_MAP) <= set(Settings.model_fields)
    names = [n for d, _ in ENV_MAP.values() for n in d]
    assert len(names) == len(set(names)), "an env name feeds two fields"
