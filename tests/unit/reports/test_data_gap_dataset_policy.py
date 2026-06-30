"""The dataset-policy doc is generated from the registry (one source of truth):
every registered dataset must appear, so the runbook can never silently drop a
table. Run this after registry changes; if it fails, regenerate the doc."""

from __future__ import annotations

from pathlib import Path

from uw_scan.reports.data_gap_healer import (
    REGISTRY,
    render_dataset_policy_markdown,
)

_DOC = Path("docs/runbooks/data-gap-dataset-policy.md")


def test_policy_render_covers_every_registry_row() -> None:
    md = render_dataset_policy_markdown()
    for e in REGISTRY:
        assert f"| {e.table_name} |" in md, f"{e.table_name} missing from policy doc"


def test_policy_render_lists_each_group() -> None:
    md = render_dataset_policy_markdown()
    for group in {e.dataset_group for e in REGISTRY}:
        assert f"## {group}" in md


def test_committed_policy_doc_is_in_sync_with_registry() -> None:
    # the committed runbook must match the generator, so it can't drift
    assert _DOC.exists(), "run the generator to create the policy doc"
    assert _DOC.read_text() == render_dataset_policy_markdown(), (
        "policy doc is stale — regenerate: "
        'uv run python -c "from uw_scan.reports.data_gap_healer import '
        "render_dataset_policy_markdown as r; "
        "open('docs/runbooks/data-gap-dataset-policy.md','w').write(r())\""
    )
