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
