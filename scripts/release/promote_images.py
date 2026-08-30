#!/usr/bin/env python3
"""Promote a complete immutable Argon image set to ``:latest`` with rollback."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path


class PromotionError(RuntimeError):
    """Image preflight, promotion, verification, or rollback failed."""


RunCommand = Callable[[list[str]], str]
ProbeCommand = Callable[[list[str]], tuple[int, str]]
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _run_command(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        stderr = getattr(exc, "stderr", "") or ""
        detail = stderr.strip() or str(exc)
        raise PromotionError(f"command failed ({' '.join(command)}): {detail}") from exc
    return completed.stdout


def _probe_command(command: list[str]) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise PromotionError(f"could not execute {' '.join(command)}: {exc}") from exc
    return completed.returncode, f"{completed.stdout}\n{completed.stderr}".strip()


def _inspect_digest(ref: str, *, run: RunCommand) -> str:
    raw = run(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            ref,
            "--format",
            "{{json .Manifest}}",
        ]
    )
    try:
        payload = json.loads(raw)
        digest = payload["digest"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PromotionError(f"invalid manifest inspection for {ref}: {raw!r}") from exc
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise PromotionError(f"invalid manifest digest for {ref}: {digest!r}")
    return digest


def require_version_tags_absent(
    *,
    owner: str,
    version: str,
    images: Sequence[str],
    probe: ProbeCommand = _probe_command,
) -> None:
    """Fail closed unless every immutable version tag is proven absent."""
    if not owner or not version or not images:
        raise ValueError("owner, version, and at least one image are required")
    missing_markers = ("not found", "manifest unknown", "no such manifest")
    for image in images:
        ref = f"ghcr.io/{owner.lower()}/{image}:{version}"
        returncode, output = probe(
            [
                "docker",
                "buildx",
                "imagetools",
                "inspect",
                ref,
                "--format",
                "{{json .Manifest}}",
            ]
        )
        if returncode == 0:
            raise PromotionError(
                f"immutable version tag already exists and will not be overwritten: {ref}"
            )
        if not any(marker in output.lower() for marker in missing_markers):
            raise PromotionError(
                f"could not prove version tag absence for {ref}: {output}"
            )


def _retag(*, target: str, source: str, digest: str, run: RunCommand) -> None:
    run(
        [
            "docker",
            "buildx",
            "imagetools",
            "create",
            "--tag",
            target,
            f"{source}@{digest}",
        ]
    )


def promote_images(
    *,
    owner: str,
    version: str,
    images: Sequence[str],
    expected_digests: Mapping[str, str],
    run: RunCommand = _run_command,
) -> dict[str, str]:
    """Promote every immutable version image, rolling back on partial failure.

    All version and current-latest manifests are inspected before the first tag
    mutation. Requiring an existing latest digest makes rollback deterministic;
    first-ever repository bootstrap must create both latest tags out of band.
    """
    if not owner or not version or not images:
        raise ValueError("owner, version, and at least one image are required")
    if set(expected_digests) != set(images):
        raise ValueError("expected digests must match the complete image set")
    for image, digest in expected_digests.items():
        if not _DIGEST_RE.fullmatch(digest):
            raise ValueError(f"invalid build digest for {image}: {digest!r}")

    bases = {name: f"ghcr.io/{owner.lower()}/{name}" for name in images}
    new_digests: dict[str, str] = {}
    old_digests: dict[str, str] = {}

    # Preflight the complete release set before mutating either shared latest tag.
    for name, base in bases.items():
        new_digests[name] = _inspect_digest(f"{base}:{version}", run=run)
        if new_digests[name] != expected_digests[name]:
            raise PromotionError(
                f"{base}:{version} does not match build output: "
                f"expected {expected_digests[name]}, observed {new_digests[name]}"
            )
    for name, base in bases.items():
        old_digests[name] = _inspect_digest(f"{base}:latest", run=run)

    touched: list[str] = []
    try:
        for name, base in bases.items():
            # Include the current target before the mutation command: a registry
            # command can fail after accepting a tag update.
            touched.append(name)
            _retag(
                target=f"{base}:latest",
                source=base,
                digest=new_digests[name],
                run=run,
            )
            observed = _inspect_digest(f"{base}:latest", run=run)
            if observed != new_digests[name]:
                raise PromotionError(
                    f"digest verification failed for {base}:latest: "
                    f"expected {new_digests[name]}, observed {observed}"
                )
    except Exception as original:
        rollback_errors: list[str] = []
        for name in reversed(touched):
            base = bases[name]
            try:
                _retag(
                    target=f"{base}:latest",
                    source=base,
                    digest=old_digests[name],
                    run=run,
                )
                restored = _inspect_digest(f"{base}:latest", run=run)
                if restored != old_digests[name]:
                    raise PromotionError(
                        f"rollback digest mismatch: expected {old_digests[name]}, "
                        f"observed {restored}"
                    )
            except Exception as rollback_error:
                rollback_errors.append(f"{name}: {rollback_error}")
        detail = f"; rollback errors: {', '.join(rollback_errors)}" if rollback_errors else ""
        if isinstance(original, PromotionError):
            raise PromotionError(f"{original}{detail}") from original
        raise PromotionError(f"image promotion failed: {original}{detail}") from original

    return new_digests


def _load_digest_dir(path: Path, images: Sequence[str]) -> dict[str, str]:
    expected: dict[str, str] = {}
    for image in images:
        digest_path = path / image
        try:
            digest = digest_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise PromotionError(
                f"could not read build digest for {image}: {digest_path}: {exc}"
            ) from exc
        if not _DIGEST_RE.fullmatch(digest):
            raise PromotionError(f"invalid build digest for {image}: {digest!r}")
        expected[image] = digest
    return expected


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("require-absent", "promote"):
        command = commands.add_parser(name)
        command.add_argument("--owner", required=True)
        command.add_argument("--version", required=True)
        command.add_argument(
            "--images", nargs="+", default=("argon-app", "argon-web")
        )
        if name == "promote":
            command.add_argument("--digest-dir", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "require-absent":
            require_version_tags_absent(
                owner=args.owner,
                version=args.version,
                images=tuple(args.images),
            )
            print(f"version tags are absent for {', '.join(args.images)}")
            return 0
        expected = _load_digest_dir(args.digest_dir, args.images)
        promoted = promote_images(
            owner=args.owner,
            version=args.version,
            images=tuple(args.images),
            expected_digests=expected,
        )
    except (PromotionError, ValueError) as exc:
        print(f"image promotion failed: {exc}", file=sys.stderr)
        return 1
    for image, digest in promoted.items():
        print(f"promoted {image}:latest -> {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
