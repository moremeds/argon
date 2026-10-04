"""Guard the public API contract: OpenAPI schema must not silently change."""

from __future__ import annotations

import json
from pathlib import Path

SNAP = Path(__file__).resolve().parent / "openapi.snapshot.json"


def test_openapi_paths_match_snapshot(client):
    current = client.get("/openapi.json").json()
    expected = json.loads(SNAP.read_text())
    assert sorted(current["paths"].keys()) == sorted(expected["paths"].keys()), (
        "OpenAPI paths changed — regenerate tests/integration/api/openapi.snapshot.json "
        "if the change is intentional."
    )
    for path, methods in expected["paths"].items():
        for method in methods:
            assert method in current["paths"][path], (
                f"Method {method.upper()} {path} removed from OpenAPI"
            )
    assert current["components"]["schemas"] == expected["components"]["schemas"], (
        "OpenAPI schemas changed — regenerate tests/integration/api/openapi.snapshot.json "
        "if the change is intentional."
    )


_SPLIT_PREFIXES = (
    "/api/regime",
    "/api/macro",
    "/api/gold",
    "/api/rates",
    "/api/health",
)


def test_regime_macro_operations_match_snapshot_exactly(client):
    """I-37/I-40: the regime router split and the resolve_instant move must
    keep every operation byte-identical (operationId, params, responses,
    tags, docs), not only the path set."""
    current = client.get("/openapi.json").json()["paths"]
    expected = json.loads(SNAP.read_text())["paths"]
    touched = sorted(p for p in expected if p.startswith(_SPLIT_PREFIXES))
    assert touched == sorted(p for p in current if p.startswith(_SPLIT_PREFIXES))
    for path in touched:
        assert current[path] == expected[path], f"OpenAPI operation changed: {path}"
