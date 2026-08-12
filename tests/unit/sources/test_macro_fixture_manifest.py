from __future__ import annotations

import hashlib
import json
from pathlib import Path


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"


def test_official_macro_fixture_manifest_matches_exact_committed_bytes() -> None:
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    names: set[str] = set()
    urls: set[str] = set()

    for artifact in manifest["artifacts"]:
        name = artifact["name"]
        raw = (FIXTURES / name).read_bytes()
        assert name not in names
        assert artifact["url"] not in urls
        assert len(raw) == artifact["content_length"]
        assert hashlib.sha256(raw).hexdigest() == artifact["sha256"]
        names.add(name)
        urls.add(artifact["url"])
