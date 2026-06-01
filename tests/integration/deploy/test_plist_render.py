"""Verify each launchd plist template renders to valid Apple plist XML.

Each template uses sed-style __PLACEHOLDER__ substitution. This test renders
each template with realistic values, writes the output to a temp file, and
runs `plutil -lint` to verify the result is well-formed plist XML.

If this test fails, the bootstrap script's `render_plist` step will also fail
on the mini — fix the template before phase 2.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATES_DIR = REPO_ROOT / "config" / "templates"

# Substitutions that mirror what macmini-bootstrap.sh applies.
COMMON_SUBS = {
    "__PROJECT_DIR__": "/Users/moremeds/projects/unusual-whales",
    "__USER__": "moremeds",
    "__BREW_PREFIX__": "/opt/homebrew",
    "__UV_BIN__": "/opt/homebrew/bin/uv",
    "__NODE_BIN__": "/opt/homebrew/bin/node",
    "__NPM_BIN__": "/opt/homebrew/bin/npm",
}

# Worker template needs role + index substitutions too.
WORKER_SUBS = {
    **COMMON_SUBS,
    "__ROLE__": "uw",
    "__INDEX__": "0",
    "__COUNT__": "2",
}


def _render(template_path: Path, subs: dict[str, str]) -> str:
    text = template_path.read_text()
    for placeholder, value in subs.items():
        text = text.replace(placeholder, value)
    return text


@pytest.mark.parametrize(
    "template_name,subs",
    [
        ("com.argon.api.plist.template", COMMON_SUBS),
        ("com.argon.web.plist.template", COMMON_SUBS),
        ("com.argon.worker.plist.template", WORKER_SUBS),
        ("com.argon.massive-ws.plist.template", COMMON_SUBS),
        ("com.argon.backup.plist.template", COMMON_SUBS),
    ],
)
def test_template_renders_to_valid_plist(
    tmp_path: Path, template_name: str, subs: dict[str, str]
) -> None:
    template_path = TEMPLATES_DIR / template_name
    assert template_path.exists(), f"template not found: {template_path}"
    rendered = _render(template_path, subs)

    # No leftover placeholders.
    assert "__" not in rendered, (
        f"unsubstituted placeholder in {template_name}:\n"
        + "\n".join(line for line in rendered.splitlines() if "__" in line)
    )

    # Apple plist XML validation via plutil.
    out_path = tmp_path / "rendered.plist"
    out_path.write_text(rendered)
    result = subprocess.run(
        ["plutil", "-lint", str(out_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"plutil rejected {template_name}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_services_list_matches_template_set() -> None:
    """Every label in config/services.list must be producible from some template."""
    services_path = REPO_ROOT / "config" / "services.list"
    assert services_path.exists()
    labels = [
        line.strip()
        for line in services_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert len(labels) == 13, f"expected 13 services, found {len(labels)}: {labels}"

    # Static labels (one plist each).
    static = {"com.argon.api", "com.argon.web", "com.argon.massive-ws"}
    # Parameterized worker labels: 5 roles × 2 indices = 10.
    worker_roles = {"uw", "massive", "ai-codex", "ai-claude", "ai-deepseek"}
    expected_workers = {
        f"com.argon.worker.{role}-{idx}" for role in worker_roles for idx in (0, 1)
    }
    expected = static | expected_workers
    assert set(labels) == expected, (
        f"unexpected/missing labels:\n"
        f"  missing from services.list: {sorted(expected - set(labels))}\n"
        f"  extra in services.list: {sorted(set(labels) - expected)}"
    )
