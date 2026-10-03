"""Every httpx client in src/ must opt out of ambient proxy config.

httpx reads the macOS *system* proxy even when no *_PROXY env var is set. A
desk Mac with a system HTTPS proxy then routes market/official-data calls
through it, and some hosts answer `SSL: UNEXPECTED_EOF_WHILE_READING` — the
FRED rates lane stalled exactly this way (see sources/fred.py). The fix is
`trust_env=False` at construction; this test keeps a new client from
regressing it. Clients a caller injects (`client or httpx.Client(...)`) are
covered because the fallback construction is itself checked.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "uw_scan"
# Every httpx entry point that builds a transport and so reads proxy config.
_CONSTRUCTORS = {
    "Client",
    "AsyncClient",
    "get",
    "post",
    "put",
    "delete",
    "stream",
    "request",
}


def _missing_trust_env() -> list[str]:
    missing: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr in _CONSTRUCTORS
                and isinstance(func.value, ast.Name)
                and func.value.id == "httpx"
            ):
                continue
            if not any(kw.arg == "trust_env" for kw in node.keywords):
                missing.append(
                    f"{path.relative_to(SRC.parent)}:{node.lineno} httpx.{func.attr}"
                )
    return missing


def test_every_httpx_client_sets_trust_env() -> None:
    assert _missing_trust_env() == []
