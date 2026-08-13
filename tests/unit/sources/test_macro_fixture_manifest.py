from __future__ import annotations

import hashlib
import json
from pathlib import Path


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"


def test_official_macro_fixture_manifest_matches_exact_committed_bytes() -> None:
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    names: set[str] = set()
    identities: set[tuple[str, str]] = set()

    for artifact in manifest["artifacts"]:
        name = artifact["name"]
        raw = (FIXTURES / name).read_bytes()
        assert name not in names
        identity = (artifact["url"], artifact["sha256"])
        assert identity not in identities
        assert len(raw) == artifact["content_length"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        names.add(name)
        identities.add(identity)
