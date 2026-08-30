from __future__ import annotations

import json

import pytest

from scripts.release.promote_images import (
    PromotionError,
    promote_images,
    require_version_tags_absent,
)


NEW_APP = "sha256:" + "a" * 64
NEW_WEB = "sha256:" + "b" * 64
OLD_APP = "sha256:" + "c" * 64
OLD_WEB = "sha256:" + "d" * 64


class _Registry:
    def __init__(self, refs: dict[str, str]) -> None:
        self.refs = dict(refs)
        self.commands: list[list[str]] = []
        self.fail_create_for: str | None = None
        self.ignore_create_for: str | None = None

    def run(self, command: list[str]) -> str:
        self.commands.append(command)
        if command[:4] == ["docker", "buildx", "imagetools", "inspect"]:
            ref = command[4]
            if ref not in self.refs:
                raise PromotionError(f"missing image: {ref}")
            return json.dumps({"digest": self.refs[ref]})
        if command[:4] == ["docker", "buildx", "imagetools", "create"]:
            assert command[4] == "--tag"
            target = command[5]
            source = command[6]
            if target == self.fail_create_for:
                self.fail_create_for = None
                raise PromotionError(f"simulated promotion failure: {target}")
            if "@" not in source:
                raise AssertionError(f"source is not digest-pinned: {source}")
            digest = source.rsplit("@", 1)[1]
            if target != self.ignore_create_for:
                self.refs[target] = digest
            return ""
        raise AssertionError(f"unexpected command: {command}")


def _refs() -> dict[str, str]:
    return {
        "ghcr.io/moremeds/argon-app:1.2.3": NEW_APP,
        "ghcr.io/moremeds/argon-web:1.2.3": NEW_WEB,
        "ghcr.io/moremeds/argon-app:latest": OLD_APP,
        "ghcr.io/moremeds/argon-web:latest": OLD_WEB,
    }


def _expected() -> dict[str, str]:
    return {"argon-app": NEW_APP, "argon-web": NEW_WEB}


def test_promotes_both_images_from_digest_pinned_immutable_tags():
    registry = _Registry(_refs())

    result = promote_images(
        owner="moremeds",
        version="1.2.3",
        images=("argon-app", "argon-web"),
        expected_digests=_expected(),
        run=registry.run,
    )

    assert result == {
        "argon-app": NEW_APP,
        "argon-web": NEW_WEB,
    }
    assert registry.refs["ghcr.io/moremeds/argon-app:latest"] == NEW_APP
    assert registry.refs["ghcr.io/moremeds/argon-web:latest"] == NEW_WEB


def test_preflight_checks_all_immutable_images_before_first_mutation():
    refs = _refs()
    del refs["ghcr.io/moremeds/argon-web:1.2.3"]
    registry = _Registry(refs)

    with pytest.raises(PromotionError, match="missing image"):
        promote_images(
            owner="moremeds",
            version="1.2.3",
            images=("argon-app", "argon-web"),
            expected_digests=_expected(),
            run=registry.run,
        )

    assert not any("create" in command for command in registry.commands)
    assert registry.refs["ghcr.io/moremeds/argon-app:latest"] == OLD_APP


def test_partial_promotion_failure_restores_already_changed_latest_tag():
    registry = _Registry(_refs())
    registry.fail_create_for = "ghcr.io/moremeds/argon-web:latest"

    with pytest.raises(PromotionError, match="simulated promotion failure"):
        promote_images(
            owner="moremeds",
            version="1.2.3",
            images=("argon-app", "argon-web"),
            expected_digests=_expected(),
            run=registry.run,
        )

    assert registry.refs["ghcr.io/moremeds/argon-app:latest"] == OLD_APP
    assert registry.refs["ghcr.io/moremeds/argon-web:latest"] == OLD_WEB


def test_digest_verification_failure_rolls_back_changed_tag():
    registry = _Registry(_refs())
    registry.ignore_create_for = "ghcr.io/moremeds/argon-app:latest"

    with pytest.raises(PromotionError, match="digest verification failed"):
        promote_images(
            owner="moremeds",
            version="1.2.3",
            images=("argon-app", "argon-web"),
            expected_digests=_expected(),
            run=registry.run,
        )

    assert registry.refs["ghcr.io/moremeds/argon-app:latest"] == OLD_APP
    assert registry.refs["ghcr.io/moremeds/argon-web:latest"] == OLD_WEB


def test_build_digest_mismatch_blocks_promotion_before_latest_mutation():
    registry = _Registry(_refs())
    expected = _expected()
    expected["argon-web"] = "sha256:" + "e" * 64

    with pytest.raises(PromotionError, match="does not match build output"):
        promote_images(
            owner="moremeds",
            version="1.2.3",
            images=("argon-app", "argon-web"),
            expected_digests=expected,
            run=registry.run,
        )

    assert not any("create" in command for command in registry.commands)


def test_version_tag_preflight_accepts_only_explicit_not_found_results():
    probes = iter(
        [
            (1, "ERROR: argon-app:1.2.3: not found"),
            (1, "manifest unknown"),
        ]
    )

    require_version_tags_absent(
        owner="moremeds",
        version="1.2.3",
        images=("argon-app", "argon-web"),
        probe=lambda _command: next(probes),
    )


def test_version_tag_preflight_rejects_existing_tag():
    with pytest.raises(PromotionError, match="already exists"):
        require_version_tags_absent(
            owner="moremeds",
            version="1.2.3",
            images=("argon-app",),
            probe=lambda _command: (0, "manifest"),
        )


def test_version_tag_preflight_does_not_treat_registry_outage_as_absent():
    with pytest.raises(PromotionError, match="could not prove version tag absence"):
        require_version_tags_absent(
            owner="moremeds",
            version="1.2.3",
            images=("argon-app",),
            probe=lambda _command: (1, "503 Service Unavailable"),
        )
