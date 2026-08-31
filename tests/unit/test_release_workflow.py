from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "release.yml"


def _workflow() -> tuple[dict, str]:
    text = WORKFLOW_PATH.read_text()
    return yaml.safe_load(text), text


def _run_text(job: dict) -> str:
    return "\n".join(str(step.get("run", "")) for step in job.get("steps", []))


def test_release_runs_are_serialized_without_cancelling_older_release():
    workflow, _ = _workflow()

    assert workflow["concurrency"] == {
        "group": "argon-release",
        "cancel-in-progress": False,
    }


def test_verify_requires_actions_read_and_exact_sha_ci_gate():
    workflow, _ = _workflow()
    verify = workflow["jobs"]["verify"]
    run_text = _run_text(verify)

    assert workflow["permissions"]["contents"] == "read"
    assert workflow["permissions"]["actions"] == "read"
    assert "scripts/release/require_ci_success.py" in run_text
    assert '"$GITHUB_SHA"' in run_text
    assert "git merge-base --is-ancestor" in run_text
    assert "scripts/release/validate_release.py" in run_text
    assert "git show origin/main:VERSION" in run_text


def test_release_does_not_rerun_a_weaker_duplicate_test_suite():
    workflow, _ = _workflow()
    release_commands = "\n".join(_run_text(job) for job in workflow["jobs"].values())

    forbidden = (
        "pytest tests/",
        "npm run test",
        "npm run typecheck",
        "npm run lint",
        "npm run build",
    )
    for command in forbidden:
        assert command not in release_commands


def test_image_matrix_pushes_only_immutable_version_tags():
    workflow, _ = _workflow()
    build = workflow["jobs"]["build-images"]
    run_text = _run_text(build)
    buildx = next(
        step for step in build["steps"] if step.get("uses", "").startswith("docker/build-push-action")
    )

    assert set(build["needs"]) == {"verify", "image-preflight"}
    assert ":latest" not in run_text
    assert buildx["with"]["tags"] == "${{ steps.meta.outputs.tag }}"
    assert buildx["id"] == "build"
    assert "actions/upload-artifact@v4" in " ".join(
        step.get("uses", "") for step in build["steps"]
    )


def test_existing_version_tags_block_build_before_matrix_starts():
    workflow, _ = _workflow()
    preflight = workflow["jobs"]["image-preflight"]

    assert preflight["needs"] == "verify"
    assert "require-absent" in _run_text(preflight)


def test_final_promotion_waits_for_both_matrix_builds():
    workflow, _ = _workflow()
    promote = workflow["jobs"]["promote-latest"]

    assert set(promote["needs"]) == {"verify", "build-images"}
    assert "is-prerelease == 'false'" in promote["if"]
    assert "scripts/release/promote_images.py" in _run_text(promote)
    assert "--digest-dir" in _run_text(promote)
    assert "actions/download-artifact@v4" in " ".join(
        step.get("uses", "") for step in promote["steps"]
    )


def test_github_release_is_published_after_required_image_path():
    workflow, _ = _workflow()
    publish = workflow["jobs"]["publish"]

    assert set(publish["needs"]) == {"verify", "build-images", "promote-latest"}
    assert "needs.build-images.result == 'success'" in publish["if"]
    assert "needs.promote-latest.result == 'success'" in publish["if"]
    assert "needs.verify.outputs.is-prerelease == 'true'" in publish["if"]


def test_prerelease_classification_is_a_verify_output_used_by_downstream_jobs():
    workflow, _ = _workflow()
    verify = workflow["jobs"]["verify"]

    assert verify["outputs"]["is-prerelease"] == "${{ steps.release.outputs.prerelease }}"
    assert verify["outputs"]["version"] == "${{ steps.release.outputs.version }}"


def test_untrusted_release_values_enter_shell_only_through_step_env():
    workflow, _ = _workflow()

    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            run = str(step.get("run", ""))
            assert "${{ needs.verify.outputs.version }}" not in run
            assert "${{ github.ref_name }}" not in run
